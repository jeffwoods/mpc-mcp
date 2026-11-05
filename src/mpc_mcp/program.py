"""Build drum programs (.xpm) from samples.

Every program starts from a blank drum program that MPC OS 2.15.1 wrote itself (Program 001 in a
real project), so every field the OS expects is there with the OS's own defaults. Copying
expansion or factory programs instead brings their settings along; First Project's soloed audio
program made every project built from it silent.

In a 2.x drum program, Instrument N is pad N, and PadNoteMap gives each pad's MIDI note. The
blank's map is the MPC default (pad A01 = 37, A02 = 36, A03 = 42 ...), which covers all 128 notes.
Loading a sample on a pad sets SampleName to the file's stem and SliceEnd to its last frame
(frame count - 1), as the OS does. Pads are given by note, so a sequence or MIDI file playing
GM drum notes hits the samples assigned to those notes.
"""

from __future__ import annotations

import gzip
import re
import shutil
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from . import project

BLANK_DRUM = Path(__file__).with_name("templates") / "blank-2.15.1.Drum.xpm.gz"
INSTRUMENT = re.compile(r'(<Instrument number="(\d+)">)(.*?)(</Instrument>)', re.S)


@dataclass
class Pad:
    sample: Path
    mute_group: int = 0  # pads sharing a group above 0 cut each other off (closed hat chokes open hat)
    tune: int = 0  # semitones


def blank_drum() -> str:
    return gzip.decompress(BLANK_DRUM.read_bytes()).decode("utf-8")


def _pad_notes(text: str) -> dict[int, int]:
    """Pad number -> note, from a program's PadNoteMap."""
    root = ET.fromstring(text.lstrip("﻿"))
    return {int(p.get("number")): int(p.findtext("Note")) for p in root.iter("PadNote")}


def wav_frames(path: Path) -> int:
    """Frame count from the RIFF header. Reads the chunks directly so any WAV encoding works,
    float and extensible included."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError(f"{path.name} isn't a WAV file; only WAV samples are supported")
        block_align = None
        while chunk := f.read(8):
            if len(chunk) < 8:
                break
            cid, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if cid == b"fmt ":
                fmt = f.read(size)
                block_align = struct.unpack("<H", fmt[12:14])[0]
                if size % 2:
                    f.read(1)
            elif cid == b"data":
                if not block_align:
                    raise ValueError(f"{path.name}: data chunk before fmt chunk")
                return size // block_align
            else:
                f.seek(size + size % 2, 1)
    raise ValueError(f"{path.name}: no audio data found")


def _set(block: str, tag: str, value: str) -> str:
    block, n = re.subn(rf"<{tag}>[^<]*</{tag}>", f"<{tag}>{value}</{tag}>", block, count=1)
    if not n:
        raise ValueError(f"blank program has no <{tag}>")
    return block


def _load_pad(block: str, sample_name: str, frames: int, pad: Pad) -> str:
    """Fill layer 1 of an instrument block. Instrument-level tags come before <Layers>, layer tags after."""
    head, layers = block.split("<Layers>", 1)
    head = _set(head, "MuteGroup", str(pad.mute_group))
    head = _set(head, "TuneCoarse", str(pad.tune))
    head = _set(head, "FilterType", "0")  # the blank's filter type 2 at full cutoff; expansions use 0 (off)
    first, rest = layers.split("</Layer>", 1)
    first = _set(first, "SampleName", escape(sample_name))
    first = _set(first, "SliceEnd", str(max(frames - 1, 0)))
    return f"{head}<Layers>{first}</Layer>{rest}"


def drum_program_xml(name: str, pads: dict[int, tuple[str, int, Pad]]) -> str:
    """pads: note -> (sample name, frame count, Pad)."""
    text = blank_drum()
    pad_for_note = {note: pad for pad, note in _pad_notes(text).items()}
    by_pad = {}
    for note, entry in pads.items():
        if note not in pad_for_note:
            raise ValueError(f"note {note} is out of range 0-127")
        by_pad[pad_for_note[note]] = entry

    def fill(m: re.Match) -> str:
        entry = by_pad.get(int(m.group(2)))
        body = m.group(3) if entry is None else _load_pad(m.group(3), *entry)
        return f"{m.group(1)}{body}{m.group(4)}"

    text = INSTRUMENT.sub(fill, text)
    return re.sub(r"<ProgramName>[^<]*</ProgramName>", lambda _: f"<ProgramName>{escape(name)}</ProgramName>", text, count=1)


def write_drum_program(out_dir: Path, name: str, pads: dict[int, Pad]) -> list[str]:
    """Write <name>.Drum.xpm into out_dir (a project's _[ProjectData] folder) and copy its samples
    in next to it. Returns the file names written, program first. Never overwrites: a program
    that already exists is an error, and a sample whose name is taken by a different file is
    copied under a new name."""
    out_dir = Path(out_dir).expanduser()
    target = out_dir / f"{name}.Drum.xpm"
    if target.exists():
        raise FileExistsError(f"{target} already exists; not overwriting")
    taken = {f.stem.lower(): f for f in out_dir.iterdir() if f.suffix.lower() in project.AUDIO}
    copied: dict[Path, str] = {}
    entries, written = {}, []
    for note, pad in sorted(pads.items()):
        src = Path(pad.sample).expanduser().resolve()
        frames = wav_frames(src)
        if src not in copied:
            stem, n = src.stem, 2
            while stem.lower() in taken and not _same_file(taken[stem.lower()], src):
                stem, n = f"{src.stem} {n}", n + 1
            dest = out_dir / f"{stem}{src.suffix}"
            if not dest.exists():
                shutil.copyfile(src, dest)
                written.append(dest.name)
            taken[stem.lower()] = dest
            copied[src] = stem
        entries[note] = (copied[src], frames, pad)
    target.write_bytes(drum_program_xml(name, entries).encode("utf-8"))
    return [target.name, *written]


def _same_file(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def pads_from_program(xpm: Path) -> dict[int, Pad]:
    """The note -> sample map of an existing drum program (an expansion kit, say), using that
    program's own PadNoteMap. Samples resolve against the program's folder. Only the first layer
    with a sample is taken; the program's other settings are left behind on purpose."""
    xpm = Path(xpm).expanduser()
    text = project.xml_text(xpm)
    root = ET.fromstring(text)
    prog = root.find("Program")
    if prog is None or prog.get("type") != "Drum":
        raise ValueError(f"{xpm.name} isn't a drum program")
    notes = _pad_notes(text)
    files = {f.stem.lower(): f for f in xpm.parent.iterdir()
             if f.suffix.lower() in project.AUDIO and not f.name.startswith(".")}
    pads: dict[int, Pad] = {}
    for ins in prog.iter("Instrument"):
        names = [(l.findtext("SampleName") or "").strip() for l in ins.iter("Layer")]
        sample = next((n for n in names if n), None)
        number = int(ins.get("number"))
        if sample is None or number not in notes:
            continue
        if sample.lower() not in files:
            raise FileNotFoundError(f"{xpm.name} pad {number} uses {sample!r}, which isn't in {xpm.parent}")
        pads[notes[number]] = Pad(files[sample.lower()], int(ins.findtext("MuteGroup") or 0),
                                  int(ins.findtext("TuneCoarse") or 0))
    return pads
