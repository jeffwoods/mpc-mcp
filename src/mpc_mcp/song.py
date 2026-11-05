"""Write a new MPC project: programs, one sequence and the .xpj, using an existing 2.x project as
a template for everything we don't build (project settings, MIDI controller map, audio program,
sequence and track header bytes).

Track headers are all copied from the template's first track and retargeted (index, type,
program, mute cleared), so any number of tracks works whatever the template has. The template's
audio program is copied with mute and solo cleared: First Project saves it muted and soloed,
which silences everything. Never modifies the template and never overwrites.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import mido

from .program import Pad, Zone, write_drum_program, write_keygroup_program
from .sequence import encode_note, retarget_track_header


@dataclass
class Note:
    """Times in beats (quarter notes)."""
    start: float
    note: int
    velocity: int
    length: float


@dataclass
class Track:
    """A track and the program it plays. Give pads for a drum program or zones for a keygroup
    program. Tracks naming the same program share it; only the first one's pads or zones count."""
    name: str
    program: str
    notes: list[Note] = field(default_factory=list)
    pads: dict[int, Pad] | None = None
    zones: list[Zone] | None = None
    release: float | None = None

    @property
    def kind(self) -> str:
        return "Drum" if self.pads is not None else "Keygroup"


def _unsolo(text: str) -> str:
    return text.replace("<Mute>True</Mute>", "<Mute>False</Mute>").replace("<Solo>True</Solo>", "<Solo>False</Solo>")


def _sequence(template: Path, out: Path, name: str, bpm: float, bars: int, tracks: list[Track], programs: list[str]) -> None:
    src = mido.MidiFile(template)
    ppq = src.ticks_per_beat
    mid = mido.MidiFile(type=1, ticks_per_beat=ppq)
    head = mido.MidiTrack()
    for msg in src.tracks[0]:
        if msg.type == "track_name":
            msg = msg.copy(name=name + "\x00")
        elif msg.type == "set_tempo":
            msg = msg.copy(tempo=mido.bpm2tempo(bpm))
        elif msg.type == "sequencer_specific" and bytes(msg.data[:3]) == b"Ga\x00":
            data = list(msg.data)
            data[4], data[8] = bars, bars + 1  # length in bars; loop end bar
            msg = msg.copy(data=data)
        head.append(msg)
    mid.tracks.append(head)

    tpl = src.tracks[1]
    for index, track in enumerate(tracks):
        out_track = mido.MidiTrack()
        for msg in tpl:
            data = bytes(msg.data[:4]) if msg.type == "sequencer_specific" else b""
            if msg.type == "track_name":
                out_track.append(msg.copy(name=track.name + "\x00", time=0))
            elif data[:3] == b"Ga\x10":
                out_track.append(msg.copy(data=list(retarget_track_header(bytes(msg.data), index, track.kind, track.program)), time=0))
            elif data[:3] == b"Ga\x15":
                out_track.append(msg.copy(data=[*msg.data[:3], index, *msg.data[4:]], time=0))
            elif data == b"pytT":
                continue  # plugin tracks only
            elif data[:3] == b"Ga\x11":
                break  # the template's notes; ours replace them
            elif msg.type not in ("polytouch", "end_of_track"):
                out_track.append(msg.copy(time=0))
        now = 0
        for n in sorted(track.notes, key=lambda n: (n.start, n.note)):
            tick = max(round(n.start * ppq), 0)
            out_track.append(mido.MetaMessage("sequencer_specific", time=tick - now,
                                              data=list(encode_note(n.note, n.velocity, round(n.length * ppq)))))
            now = tick
        out_track.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(out_track)

    for program in programs:
        raw = program.encode("ascii")
        mid.tracks.append(mido.MidiTrack([mido.MetaMessage("sequencer_specific", data=[0x47, 0x61, 0x13, len(raw) + 2, 0, *raw, 0, 0]),
                                          mido.MetaMessage("end_of_track")]))
    mid.save(out)


def write_project(template_xpj: Path, out_dir: Path, name: str, tracks: list[Track], bpm: float, bars: int) -> Path:
    """Write <out_dir>/<name>.xpj and its _[ProjectData] folder. Returns the .xpj path."""
    template_xpj = Path(template_xpj).expanduser()
    tpl_data = template_xpj.with_name(f"{template_xpj.stem}_[ProjectData]")
    out_dir = Path(out_dir).expanduser()
    xpj = out_dir / f"{name}.xpj"
    data_dir = out_dir / f"{name}_[ProjectData]"
    if xpj.exists() or data_dir.exists():
        raise FileExistsError(f"{xpj} already exists; not overwriting")
    if not 1 <= bars <= 127:
        raise ValueError("bars must be 1-127")
    if not tracks:
        raise ValueError("a project needs at least one track")
    data_dir.mkdir()

    files = ["All Sequences & Songs.xal"]
    programs: dict[str, Track] = {}
    for track in tracks:
        if track.program in programs:
            if programs[track.program].kind != track.kind:
                raise ValueError(f"program {track.program!r} is used as both drum and keygroup")
            continue
        programs[track.program] = track
        if track.pads is not None:
            files += write_drum_program(data_dir, track.program, track.pads)
        elif track.zones is not None:
            files += write_keygroup_program(data_dir, track.program, track.zones, track.release)
        else:
            raise ValueError(f"track {track.name!r} has neither pads nor zones")

    for keep in ("Project Settings.xml", "Midi Controller.mcn"):
        if (tpl_data / keep).exists():
            shutil.copyfile(tpl_data / keep, data_dir / keep)
    audio = tpl_data / "Audio 001.Audio.xpm"
    names = list(programs)
    if audio.exists():
        (data_dir / audio.name).write_bytes(_unsolo(audio.read_bytes().decode("utf-8")).encode("utf-8"))
        files.append(audio.name)
        names.append("Audio 001")

    xal = (tpl_data / "All Sequences & Songs.xal").read_text(encoding="utf-8")
    seq_name = re.search(r"<Name>([^<]*)</Name>", xal)
    if seq_name:
        xal = xal.replace(f"<Name>{seq_name.group(1)}</Name>", f"<Name>{escape(name)}</Name>", 1)
    (data_dir / "All Sequences & Songs.xal").write_text(xal, encoding="utf-8")
    _sequence(tpl_data / "1.sxq", data_dir / "1.sxq", name, bpm, bars, tracks, names)

    text = template_xpj.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    listing = nl.join(f"    <File>{escape(f'./{data_dir.name}/{f}')}</File>" for f in files)
    text = re.sub(r"<FileList>.*?</FileList>", lambda _: f"<FileList>{nl}{listing}{nl}  </FileList>", text, flags=re.S)
    text = re.sub(r"<BPM>[^<]*</BPM>", f"<BPM>{bpm:.6f}</BPM>", text)
    text = re.sub(r"<MasterTempo.Value>[^<]*</MasterTempo.Value>", f"<MasterTempo.Value>{bpm:.6f}</MasterTempo.Value>", text)
    xpj.write_bytes(text.encode("utf-8"))
    return xpj
