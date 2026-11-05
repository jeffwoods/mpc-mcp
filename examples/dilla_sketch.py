"""Build a 4-bar boom-bap sketch as a new MPC project, using an existing 2.x project as a template.

Usage: python examples/dilla_sketch.py <template.xpj> <expansions dir> <output dir> [project name]

Writes <output dir>/<project name>.xpj (default "Dilla Sketch") and its _[ProjectData] folder. Never modifies the template.
The project itself is written by mpc_mcp.song.write_project.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from mpc_mcp.program import Pad, pads_from_program, zones_from_program
from mpc_mcp.song import Note, Track, write_project

NAME = "Dilla Sketch"
BPM = 88
BARS = 4
PPQ = 960
SIX = PPQ // 4  # one 16th

# (program name, expansion, keygroup program to take the zones from, volume release)
BASS = ("Taurus Bass", "Moog Taurus I (1975)", "The Taurus", 0.1)
KEYS = ("Rhodes", "Vintage Hardware Collection", "Acoustic-Rhodes A", 0.18)

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


def main(template_xpj: Path, expansions: Path, out_dir: Path, project: str = NAME) -> None:
    def notes(events):
        return [Note(tick / PPQ, note, vel, length / PPQ) for tick, note, vel, length in events]

    def zones(spec):
        _, folder, source, _ = spec
        return zones_from_program(expansions / folder / f"{source}.xpm")

    pads = {}
    for note, (folder, kit, source_note, group) in KIT.items():
        pad = pads_from_program(expansions / folder / f"{kit}.xpm")[source_note]
        pads[note] = Pad(pad.sample, group, pad.tune)
    tracks = [
        Track("Drums", KIT_NAME, notes(drums()), pads=pads),
        Track("Bass", BASS[0], notes(bass()), zones=zones(BASS), release=BASS[3]),
        Track("Keys", KEYS[0], notes(keys()), zones=zones(KEYS), release=KEYS[3]),
    ]
    print(write_project(template_xpj, out_dir, project, tracks, BPM, BARS))


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:4]), *sys.argv[4:5])
