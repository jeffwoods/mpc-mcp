"""Build drum and keygroup programs (.xpm) from samples.

Every program starts from a blank program that MPC OS 2.15.1 wrote itself (Program 001 and
Program 002 in a real project), so every field the OS expects is there with the OS's own
defaults. Copying expansion or factory programs instead brings their settings along; First
Project's soloed audio program made every project built from it silent.

Drum programs: Instrument N is pad N, and PadNoteMap gives each pad's MIDI note. The blank's map
is the MPC default (pad A01 = 37, A02 = 36, A03 = 42 ...), which covers all 128 notes. Loading a
sample on a pad sets SampleName to the file's stem and SliceEnd to its last frame (frame count
- 1), as the OS does. Pads are given by note, so a sequence or MIDI file playing GM drum notes
hits the samples assigned to those notes.

Keygroup programs: one Instrument per keygroup, numbered from 1, each with a LowNote-HighNote
range, and KeygroupNumKeygroups says how many (the blank has one). A layer's RootNote is the MIDI
note the sample sounds at its own pitch, plus 1; 0 means "use the WAV's smpl unity note". OS 2.11
expansions use the +1 form (sample "Atari(36)" alone on key 36 has RootNote 37, while its smpl
unity is a placeholder 60); OS 2.7 ones use 0 and real unity notes. We write the explicit form.
The blank's PadNoteMap is the identity (pad 1 = note 0), so pad bank A plays notes 0-15, below most
instruments. We rotate it so pad 1 is the first C the keygroups cover. Whether the OS honours a
keygroup PadNoteMap is untested on hardware.
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

TEMPLATES = Path(__file__).with_name("templates")
BLANK_DRUM = TEMPLATES / "blank-2.15.1.Drum.xpm.gz"
BLANK_KEYGROUP = TEMPLATES / "blank-2.15.1.Keygroup.xpm.gz"
INSTRUMENT = re.compile(r'(<Instrument number="(\d+)">)(.*?)(</Instrument>)', re.S)


@dataclass
class Pad:
    sample: Path
    mute_group: int = 0  # pads sharing a group above 0 cut each other off (closed hat chokes open hat)
    tune: int = 0  # semitones


@dataclass
class Zone:
    sample: Path
    root: int  # the MIDI note the sample sounds at its own pitch
    low: int | None = None  # key range; None splits the keyboard halfway between neighbouring roots
    high: int | None = None
    tune: int = 0  # semitones, on top of the root
    loop_start: int | None = None  # frame to loop back to from the end while a key is held


def blank_drum() -> str:
    return gzip.decompress(BLANK_DRUM.read_bytes()).decode("utf-8")


def blank_keygroup() -> str:
    return gzip.decompress(BLANK_KEYGROUP.read_bytes()).decode("utf-8")


def _pad_notes(text: str) -> dict[int, int]:
    """Pad number -> note, from a program's PadNoteMap."""
    root = ET.fromstring(text.lstrip("﻿"))
    return {int(p.get("number")): int(p.findtext("Note")) for p in root.iter("PadNote")}


def wav_info(path: Path) -> tuple[int, int | None]:
    """(frame count, smpl unity note or None) from the RIFF headers. Reads the chunks directly so
    any WAV encoding works, float and extensible included."""
    block_align, unity = None, None
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise ValueError(f"{Path(path).name} isn't a WAV file; only WAV samples are supported")
        while len(chunk := f.read(8)) == 8:
            cid, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if cid == b"fmt ":
                block_align = struct.unpack("<H", f.read(size)[12:14])[0]
                f.seek(size % 2, 1)
            elif cid == b"smpl" and size >= 36:
                unity = struct.unpack("<9I", f.read(36))[3]
                f.seek(size - 36 + size % 2, 1)
            elif cid == b"data":
                if not block_align:
                    raise ValueError(f"{Path(path).name}: data chunk before fmt chunk")
                return size // block_align, unity
            else:
                f.seek(size + size % 2, 1)
    raise ValueError(f"{Path(path).name}: no audio data found")


def wav_frames(path: Path) -> int:
    return wav_info(path)[0]


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


def _target(out_dir: Path, name: str, kind: str) -> Path:
    target = Path(out_dir).expanduser() / f"{name}.{kind}.xpm"
    if target.exists():
        raise FileExistsError(f"{target} already exists; not overwriting")
    return target


def _copy_samples(out_dir: Path, samples: list[Path]) -> tuple[dict[Path, tuple[str, int]], list[str]]:
    """Copy each WAV into out_dir once. Returns {source: (sample name, frames)} and the files
    written. A name taken by a different file gets a number added; never overwrites."""
    out_dir = Path(out_dir).expanduser()
    taken = {f.stem.lower(): f for f in out_dir.iterdir() if f.suffix.lower() in project.AUDIO}
    copied: dict[Path, tuple[str, int]] = {}
    written = []
    for sample in samples:
        src = Path(sample).expanduser().resolve()
        if src in copied:
            continue
        frames = wav_frames(src)
        stem, n = src.stem, 2
        while stem.lower() in taken and not _same_file(taken[stem.lower()], src):
            stem, n = f"{src.stem} {n}", n + 1
        dest = out_dir / f"{stem}{src.suffix}"
        if not dest.exists():
            shutil.copyfile(src, dest)
            written.append(dest.name)
        taken[stem.lower()] = dest
        copied[src] = (stem, frames)
    return copied, written


def write_drum_program(out_dir: Path, name: str, pads: dict[int, Pad]) -> list[str]:
    """Write <name>.Drum.xpm into out_dir (a project's _[ProjectData] folder) and copy its samples
    in next to it. Returns the file names written, program first. Never overwrites: a program
    that already exists is an error, and a sample whose name is taken by a different file is
    copied under a new name."""
    target = _target(out_dir, name, "Drum")
    pads = dict(sorted(pads.items()))
    copied, written = _copy_samples(out_dir, [p.sample for p in pads.values()])
    entries = {note: (*copied[Path(p.sample).expanduser().resolve()], p) for note, p in pads.items()}
    target.write_bytes(drum_program_xml(name, entries).encode("utf-8"))
    return [target.name, *written]


def _ranges(zones: list[Zone]) -> list[tuple[int, int]]:
    """Key ranges: given ones kept, missing edges meet the neighbour's edge, or split halfway
    between neighbouring roots."""
    out: list[tuple[int, int]] = []
    for i, z in enumerate(zones):
        low = z.low if z.low is not None else 0 if i == 0 else out[i - 1][1] + 1
        if z.high is not None:
            high = z.high
        elif i == len(zones) - 1:
            high = 127
        else:
            nxt = zones[i + 1]
            high = nxt.low - 1 if nxt.low is not None else (z.root + nxt.root) // 2
        if not 0 <= low <= high <= 127:
            raise ValueError(f"zone for {Path(z.sample).name} has an empty or out-of-range key range {low}-{high}")
        out.append((low, high))
    return out


def _load_zone(block: str, sample_name: str, frames: int, zone: Zone, low: int, high: int,
               release: float | None) -> str:
    head, layers = block.split("<Layers>", 1)
    head = _set(head, "LowNote", str(low))
    head = _set(head, "HighNote", str(high))
    head = _set(head, "FilterType", "0")
    if release is not None:
        head = _set(head, "VolumeRelease", f"{release:.6f}")
    first, rest = layers.split("</Layer>", 1)
    first = _set(first, "TuneCoarse", str(zone.tune))
    first = _set(first, "RootNote", str(zone.root + 1))
    first = _set(first, "KeyTrack", "True")
    first = _set(first, "SampleName", escape(sample_name))
    first = _set(first, "SliceEnd", str(max(frames - 1, 0)))
    if zone.loop_start is not None:
        first = _set(first, "LoopStart", str(zone.loop_start))
        first = _set(first, "LoopEnd", str(max(frames - 1, 0)))
        first = _set(first, "SliceLoopStart", str(zone.loop_start))
        first = _set(first, "SliceLoop", "1")
    return f"{head}<Layers>{first}</Layer>{rest}"


def _first_pad_note(low: int) -> int:
    """The first C at or above the lowest covered note."""
    return min(-(-low // 12) * 12, 120)


def _rotate_pads(text: str, first: int) -> str:
    """Pad N plays note (first + N - 1) mod 128, keeping the map a permutation of all 128 notes."""
    def pad(m: re.Match) -> str:
        return f'{m.group(1)}{(first + int(m.group(2)) - 1) % 128}{m.group(3)}'
    head, sep, rest = text.partition("<PadNoteMap>")
    body, end, tail = rest.partition("</PadNoteMap>")
    if not sep or not end:
        raise ValueError("blank keygroup program has no PadNoteMap")
    body = re.sub(r'(<PadNote number="(\d+)">\s*<Note>)\d+(</Note>)', pad, body)
    return head + sep + body + end + tail


def keygroup_program_xml(name: str, zones: list[tuple[str, int, Zone]], release: float | None = None) -> str:
    """zones: (sample name, frame count, Zone), sorted by root."""
    if not 1 <= len(zones) <= 128:
        raise ValueError("a keygroup program needs 1 to 128 zones")
    for z in zones:
        if not 0 <= z[2].root <= 127:
            raise ValueError(f"root note {z[2].root} is out of range 0-127")
    text = blank_keygroup()
    blocks = INSTRUMENT.findall(text)
    if len(blocks) != 1:
        raise ValueError("blank keygroup program should have exactly one instrument")
    _, _, body, _ = blocks[0]
    ranges = _ranges([z for _, _, z in zones])
    built = "\n      ".join(
        f'<Instrument number="{i}">{_load_zone(body, s, frames, z, low, high, release)}</Instrument>'
        for i, ((s, frames, z), (low, high)) in enumerate(zip(zones, ranges), start=1))
    text = INSTRUMENT.sub(lambda _: built, text, count=1)
    text = _set(text, "KeygroupNumKeygroups", str(len(zones)))
    text = _rotate_pads(text, _first_pad_note(ranges[0][0]))
    return re.sub(r"<ProgramName>[^<]*</ProgramName>", lambda _: f"<ProgramName>{escape(name)}</ProgramName>", text, count=1)


def write_keygroup_program(out_dir: Path, name: str, zones: list[Zone], release: float | None = None) -> list[str]:
    """Write <name>.Keygroup.xpm into out_dir and copy its samples in, one keygroup per zone.
    release sets every keygroup's volume release (0-1, as the MPC stores it; the blank's is 0,
    an instant cut on key up). Returns the file names written, program first. Never overwrites."""
    target = _target(out_dir, name, "Keygroup")
    zones = sorted(zones, key=lambda z: (z.root, z.low if z.low is not None else -1))
    copied, written = _copy_samples(out_dir, [z.sample for z in zones])
    entries = [(*copied[Path(z.sample).expanduser().resolve()], z) for z in zones]
    target.write_bytes(keygroup_program_xml(name, entries, release).encode("utf-8"))
    return [target.name, *written]


def _same_file(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def _audio_files(folder: Path) -> dict[str, Path]:
    return {f.stem.lower(): f for f in folder.iterdir() if f.suffix.lower() in project.AUDIO and not f.name.startswith(".")}


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
    files = _audio_files(xpm.parent)
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


def zones_from_program(xpm: Path) -> list[Zone]:
    """The zones of an existing keygroup program (an expansion's, say): sample, root note, key
    range, tuning and loop. A RootNote of 0 falls back to the WAV's smpl unity note, then to 60.
    Only the first layer with a sample is taken, so velocity layers collapse to one."""
    xpm = Path(xpm).expanduser()
    prog = ET.fromstring(project.xml_text(xpm)).find("Program")
    if prog is None or prog.get("type") != "Keygroup":
        raise ValueError(f"{xpm.name} isn't a keygroup program")
    count = int(prog.findtext("KeygroupNumKeygroups") or 0)
    files = _audio_files(xpm.parent)
    zones = []
    for ins in list(prog.iter("Instrument"))[:count]:
        layer = next((l for l in ins.iter("Layer") if (l.findtext("SampleName") or "").strip()), None)
        if layer is None:
            continue
        sample = layer.findtext("SampleName").strip()
        if sample.lower() not in files:
            raise FileNotFoundError(f"{xpm.name} keygroup {ins.get('number')} uses {sample!r}, which isn't in {xpm.parent}")
        path = files[sample.lower()]
        root = int(layer.findtext("RootNote") or 0) - 1
        if root < 0:
            root = wav_info(path)[1] if path.suffix.lower() == ".wav" else None
            root = 60 if root is None else root
        looped = (layer.findtext("SliceLoop") or "0") != "0" or layer.findtext("Loop") == "True"
        zones.append(Zone(path, root, int(ins.findtext("LowNote")), int(ins.findtext("HighNote")),
                          int(layer.findtext("TuneCoarse") or 0),
                          int(layer.findtext("SliceLoopStart") or layer.findtext("LoopStart") or 0) if looped else None))
    return zones
