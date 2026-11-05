"""Build a 4-bar boom-bap sketch as a new MPC project, using an existing 2.x project as a template.

Usage: python examples/dilla_sketch.py <template.xpj> <expansions dir> <output dir> [project name]

Writes <output dir>/<project name>.xpj (default "Dilla Sketch") and its _[ProjectData] folder. Never modifies the template.
Track-to-program links, bar count and note events follow the .sxq layout documented in the README
and in mpc_mcp.sequence.
"""

from __future__ import annotations

import random
import re
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import mido

from mpc_mcp.program import Pad, pads_from_program, write_drum_program
from mpc_mcp.sequence import PLUGIN_MARKER, encode_note, retarget_track_header

NAME = "Dilla Sketch"
BPM = 88
BARS = 4
PPQ = 960
SIX = PPQ // 4  # one 16th

BASS = ("Moog Taurus I (1975)", "The Taurus", "Taurus Bass", "Keygroup")
KEYS = ("Vintage Hardware Collection", "Acoustic-Rhodes A", "Rhodes", "Keygroup")

KICK, RIM, SNARE, CLAP, HAT, OPEN_HAT = 36, 37, 38, 39, 42, 46  # GM drum notes
KIT_NAME = "Dilla Kit"
HATS = 1  # mute group: the closed hat cuts off the open one
KIT = {  # our note: (expansion, drum program, that program's note for the sound, mute group)
    KICK: ("Vintage Hardware Collection", "Drums-Drumulator.Drum", 36, 0),
    RIM: ("Vintage Hardware Collection", "Drums-Drumulator.Drum", 40, 0),
    SNARE: ("Vintage Hardware Collection", "Drums-Drumulator.Drum", 38, 0),
    CLAP: ("Vintage Hardware Collection", "Drums-Drumulator.Drum", 41, 0),
    HAT: ("Kevin's 808 & 909", "808 One", 44, HATS),
    OPEN_HAT: ("Kevin's 808 & 909", "808 One", 48, HATS),
}
rng = random.Random(1974)


def jitter(lo: int, hi: int) -> int:
    return rng.randint(lo, hi)


def drums() -> list[tuple[int, int, int, int]]:
    """(tick, note, velocity, length). Kicks rush a little, snares drag, hats swing and wobble."""
    ev = []
    kicks = [[0, 3, 10], [0, 7, 10], [0, 3, 10], [0, 3, 10, 14]]
    ghosts = [[], [7, 15], [9], [6]]
    for bar in range(BARS):
        b = bar * 4 * PPQ
        for i, pos in enumerate(kicks[bar]):
            off = jitter(0, 8) if pos == 0 else jitter(-22, 4)
            ev.append((b + pos * SIX + off, KICK, jitter(104, 120) if i == 0 else jitter(86, 104), 200))
        for pos in (4, 12):
            ev.append((b + pos * SIX + jitter(28, 46), SNARE, jitter(106, 122), 200))
        if bar == 3:
            ev.append((b + 12 * SIX + jitter(40, 55), CLAP, 84, 200))
        for pos in ghosts[bar]:
            ev.append((b + pos * SIX + jitter(10, 30), RIM, jitter(34, 54), 120))
        for pos in range(16):
            if bar == 3 and pos >= 14:
                continue
            on_eighth = pos % 2 == 0
            if not on_eighth and rng.random() < 0.2:
                continue
            swing = 0 if on_eighth else 58
            ev.append((b + pos * SIX + swing + jitter(-14, 14), HAT,
                       jitter(78, 98) if on_eighth else jitter(38, 64), 120))
        if bar == 3:
            ev.append((b + 14 * SIX + 52, OPEN_HAT, 82, 400))
    return ev


# Db major ii-V-I-vi, rootless voicings: Ebm9, Ab13, Dbmaj9, Bbm9
CHORDS = [[54, 58, 61, 65], [54, 58, 60, 65], [53, 56, 60, 63], [56, 60, 61, 65]]
ROOTS = [27, 32, 37, 34]  # Eb1, Ab1, Db2, Bb1


def keys() -> list[tuple[int, int, int, int]]:
    ev = []
    for bar, chord in enumerate(CHORDS):
        b = bar * 4 * PPQ
        for start, length, vel in ((jitter(40, 60), int(2.4 * PPQ), 78), (10 * SIX + jitter(30, 50), int(1.4 * PPQ), 66)):
            for i, note in enumerate(chord):
                ev.append((b + start + i * jitter(9, 16), note, vel + jitter(-6, 6), length))
    return ev


def bass() -> list[tuple[int, int, int, int]]:
    ev = []
    for bar, root in enumerate(ROOTS):
        b = bar * 4 * PPQ
        ev.append((b + jitter(8, 20), root, 108, 5 * SIX))
        ev.append((b + 7 * SIX + jitter(10, 25), root + 12 if bar % 2 else root + 7, 92, SIX + 60))
        ev.append((b + 10 * SIX + jitter(5, 20), root, 102, 4 * SIX))
        if bar == 3:
            ev.append((b + 14 * SIX + 30, ROOTS[0] - 1, 88, SIX + 80))  # chromatic walk back to Eb
    return ev


def build_sequence(template: Path, out: Path, parts: list[tuple[str, str, str, list]]) -> None:
    src = mido.MidiFile(template)
    mid = mido.MidiFile(type=1, ticks_per_beat=src.ticks_per_beat)
    head = mido.MidiTrack()
    for msg in src.tracks[0]:
        if msg.type == "track_name":
            msg = msg.copy(name=NAME + "\x00")
        elif msg.type == "set_tempo":
            msg = msg.copy(tempo=mido.bpm2tempo(BPM))
        elif msg.type == "sequencer_specific" and bytes(msg.data[:3]) == b"Ga\x00":
            data = list(msg.data)
            data[4], data[8] = BARS, BARS + 1
            msg = msg.copy(data=data)
        head.append(msg)
    mid.tracks.append(head)

    for index, (track_name, program, kind, events) in enumerate(parts):
        tpl = src.tracks[1 + index]
        track = mido.MidiTrack()
        if kind == "Plugin":
            track.append(mido.MetaMessage("sequencer_specific", data=list(PLUGIN_MARKER)))
        for msg in tpl:
            if msg.type == "track_name":
                track.append(msg.copy(name=track_name + "\x00", time=0))
            elif msg.type == "sequencer_specific" and bytes(msg.data[:3]) == b"Ga\x10":
                track.append(msg.copy(data=list(retarget_track_header(bytes(msg.data), index, kind, program)), time=0))
            elif msg.type == "sequencer_specific" and bytes(msg.data[:3]) == b"Ga\x15":
                track.append(msg.copy(data=[*msg.data[:3], index, *msg.data[4:]], time=0))
            elif msg.type == "sequencer_specific" and bytes(msg.data[:4]) == b"pytT":
                continue  # plugin-only marker; added above when needed
            elif msg.type == "sequencer_specific" and bytes(msg.data[:3]) == b"Ga\x11":
                break  # template notes start here; ours replace them
            elif msg.type in ("polytouch", "end_of_track"):
                continue
            else:
                track.append(msg.copy(time=0))
        now = 0
        for tick, note, vel, length in sorted(events):
            tick = max(tick, 0)
            track.append(mido.MetaMessage("sequencer_specific", data=list(encode_note(note, vel, length)), time=tick - now))
            now = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(track)

    for program in [p for _, p, _, _ in parts] + ["Audio 001"]:
        name = program.encode()
        data = [0x47, 0x61, 0x13, len(name) + 2, 0x00, *name, 0, 0]
        mid.tracks.append(mido.MidiTrack([mido.MetaMessage("sequencer_specific", data=data),
                                          mido.MetaMessage("end_of_track")]))
    mid.save(out)


def unsolo(text: str) -> str:
    """Clear program-level mute and solo. First Project's audio program is saved muted and soloed,
    which silences every other track, pads included."""
    text = text.replace("<Mute>True</Mute>", "<Mute>False</Mute>")
    return text.replace("<Solo>True</Solo>", "<Solo>False</Solo>")


def copy_program(expansions: Path, spec: tuple[str, str, str, str], data_dir: Path) -> list[str]:
    folder, source, name, kind = spec
    src_dir = expansions / folder
    text = (src_dir / f"{source}.xpm").read_text(encoding="utf-8")
    text = unsolo(re.sub(r"<ProgramName>[^<]*</ProgramName>", f"<ProgramName>{name}</ProgramName>", text, count=1))
    target = data_dir / f"{name}.{kind}.xpm"
    target.write_text(text, encoding="utf-8")
    samples = sorted(set(re.findall(r"<SampleName>([^<]+)</SampleName>", text)))
    files = {f.stem.lower(): f for f in src_dir.iterdir() if f.suffix.lower() in (".wav", ".aif", ".aiff")}
    copied = [target.name]
    for s in samples:
        f = files[s.strip().lower()]
        shutil.copyfile(f, data_dir / f.name)
        copied.append(f.name)
    return copied


def build_kit(expansions: Path, data_dir: Path) -> list[str]:
    """A new drum program from the blank 2.15.1 one, taking each sound from an expansion kit's pads."""
    pads = {}
    for note, (folder, kit, source_note, group) in KIT.items():
        pad = pads_from_program(expansions / folder / f"{kit}.xpm")[source_note]
        pads[note] = Pad(pad.sample, group, pad.tune)
    return write_drum_program(data_dir, KIT_NAME, pads)


def main(template_xpj: Path, expansions: Path, out_dir: Path, project: str = NAME) -> None:
    tpl_data = template_xpj.with_name(f"{template_xpj.stem}_[ProjectData]")
    xpj = out_dir / f"{project}.xpj"
    data_dir = out_dir / f"{project}_[ProjectData]"
    if xpj.exists() or data_dir.exists():
        sys.exit(f"{xpj} already exists; not overwriting")
    data_dir.mkdir()

    files = ["All Sequences & Songs.xal"]
    files += build_kit(expansions, data_dir)
    for spec in (BASS, KEYS):
        files += copy_program(expansions, spec, data_dir)
    for keep in ("Project Settings.xml", "Midi Controller.mcn"):
        shutil.copyfile(tpl_data / keep, data_dir / keep)
    audio = (tpl_data / "Audio 001.Audio.xpm").read_bytes().decode("utf-8")
    (data_dir / "Audio 001.Audio.xpm").write_bytes(unsolo(audio).encode("utf-8"))
    files.append("Audio 001.Audio.xpm")

    xal = (tpl_data / "All Sequences & Songs.xal").read_text(encoding="utf-8")
    (data_dir / "All Sequences & Songs.xal").write_text(xal.replace("My 1st sequence", NAME, 1), encoding="utf-8")

    build_sequence(tpl_data / "1.sxq", data_dir / "1.sxq", [
        ("Drums", KIT_NAME, "Drum", drums()),
        ("Bass", BASS[2], "Keygroup", bass()),
        ("Keys", KEYS[2], "Keygroup", keys()),
    ])

    text = template_xpj.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    listing = nl.join(f"    <File>{escape(f'./{data_dir.name}/{f}')}</File>" for f in files)
    text = re.sub(r"<FileList>.*?</FileList>", lambda _: f"<FileList>{nl}{listing}{nl}  </FileList>", text, flags=re.S)
    text = re.sub(r"<BPM>[^<]*</BPM>", f"<BPM>{BPM:.6f}</BPM>", text)
    text = re.sub(r"<MasterTempo.Value>[^<]*</MasterTempo.Value>", f"<MasterTempo.Value>{BPM:.6f}</MasterTempo.Value>", text)
    xpj.write_bytes(text.encode("utf-8"))
    print(xpj)


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:4]), *sys.argv[4:5])
