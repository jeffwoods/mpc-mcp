"""A karaoke backing track over the changes of "Wonderful Christmastime" (McCartney, 1979), as a new
MPC project: Linn drums with tambourine, Minimoog bass, a Prophet pulse with echo, Mellotron choir
and glock/tube bells, plus an empty Lead track (Minimoog lead) for the tune.

Usage: python examples/christmastime.py <template.xpj> <expansions dir> <output dir> [project name]

Chords and section order from a chord sheet, in B at 95 BPM. Bar counts are inferred: one bar
per chord in verses, a chorus line is two bars (C#m7 C#m6 D#m7 G#m7 a beat each, then E A9 and a
half bar of B). The solo's 2/4 bar is played as 4/4. The parts are an original arrangement; the
vocal melody and the record's synth riff are left for you to play.
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

from mpc_mcp.program import Pad, zones_from_program
from mpc_mcp.song import Note, Track, write_project

NAME = "Christmastime Karaoke"
BPM = 95
rng = random.Random(1979)

PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
QUALITY = {"": (0, 4, 7), "m": (0, 3, 7), "maj7": (0, 4, 7, 11), "6": (0, 4, 7, 9), "7": (0, 4, 7, 10),
           "m7": (0, 3, 7, 10), "m6": (0, 3, 7, 9), "sus4": (0, 5, 7), "9": (0, 4, 10, 14), "maj13": (0, 4, 11, 21)}

# (chord, beats). "/" gives a bass note.
LINE = [("C#m7", 1), ("C#m6", 1), ("D#m7", 1), ("G#m7", 1), ("E", 1), ("A9", 1), ("B", 2)]
VERSE = [("Bmaj7", 4), ("B6", 4), ("F#sus4", 4), ("B", 4)]
CHORUS = LINE * 2
BRIDGE = [("B", 4), ("C#m7", 4), ("F#7", 4), ("B", 4), ("B", 4), ("C#m7", 4), ("F#7", 8),
          ("B", 2), ("B7", 2), ("B6", 2), ("B", 2), ("B", 4), ("B", 2), ("B7", 2), ("B6", 2), ("B", 2), ("E", 4),
          ("E6", 4), ("E", 4), ("B", 4)]
MIDDLE = [("B", 4), ("C#m7", 4), ("F#7", 4), ("B", 4), ("B", 4), ("C#m7", 4), ("F#7", 8),
          ("B", 4), ("B", 4), ("B", 2), ("F#7", 2), ("F#7", 2), ("Bmaj7", 2)]
SOLO = [("C#m7", 1), ("F#7", 1), ("D#m7", 1), ("G#m7", 1), ("E", 2), ("A9", 2), ("E", 2), ("A9", 2),
        ("E", 1), ("A9", 1), ("D#m7", 1), ("G#m7", 1), ("D#m7", 2), ("G#m7", 2),
        ("C#m7", 1), ("F#7", 1), ("D#m7", 1), ("G#m7", 1), ("E", 1), ("A9", 1), ("B", 2), ("B", 4)]
OUTRO = [("Bmaj7", 2), ("C#m7/B", 2), ("B", 2), ("C#m7/B", 2), ("Bmaj7", 2), ("C#m7/B", 2), ("B", 4),
         ("F#", 2), ("Bmaj7", 2), ("Bmaj7", 4), ("Bmaj13", 8)]
FORM = [("intro", (VERSE + LINE) * 2), ("verse", VERSE), ("chorus", CHORUS), ("verse", VERSE), ("chorus", CHORUS),
        ("bridge", BRIDGE), ("interlude", VERSE), ("chorus", CHORUS), ("verse", VERSE), ("chorus", CHORUS),
        ("middle", MIDDLE), ("verse", VERSE), ("chorus", CHORUS), ("solo", SOLO), ("verse", VERSE),
        ("chorus", CHORUS * 3), ("outro", OUTRO)]

# Sounds: (expansion, program)
PULSE = ("Prophet Rev2 Vol 1", "Pluck")
BASS = ("Moog Minimoog (1970)", "Classic Bass")
CHOIR = ("Tron Choir", "Mix-Mellotron 8 Choir")
BELLS = ("Tron Perc", "Percussion-Mellotron Glocks + Tube Bells")
LEAD = ("Moog Minimoog (1970)", "Mini Lead 01")
KICK, SIDE, SNARE, HAT, OPEN_HAT, CRASH, TAMB = 36, 37, 38, 42, 46, 49, 54  # GM
HATS = 1
KIT = {KICK: ("Linn kick hard", 0), SIDE: ("Linn Sidestick", 0), SNARE: ("Linn Snare mid", 0), HAT: ("Linn cl hat", HATS),
       OPEN_HAT: ("Linn open hat", HATS), CRASH: ("Linn Crash", 0), TAMB: ("Linn Tambourine hard", 0)}


def chord(symbol: str) -> tuple[list[int], int]:
    """(pitch classes above the root as intervals from 0, bass pitch class)."""
    head, _, bass = symbol.partition("/")
    m = re.fullmatch(r"([A-G]#?)(.*)", head)
    root = PC[m[1]]
    return [root + i for i in QUALITY[m[2]]], PC[bass] if bass else root


def voice(tones: list[int], lo: int, hi: int, prev: list[int] | None) -> list[int]:
    """A close voicing within lo-hi, moving as little as possible from the previous one."""
    pcs = sorted({t % 12 for t in tones})
    options = []
    for rot in range(len(pcs)):
        order = pcs[rot:] + pcs[:rot]
        for base in range(lo - 12, hi + 1):
            if base % 12 != order[0]:
                continue
            v = [base]
            for pc in order[1:]:
                v.append(v[-1] + (pc - v[-1]) % 12)
            if v[0] >= lo and v[-1] <= hi:
                options.append(v)
    if not options:
        raise ValueError(f"no voicing for {tones} in {lo}-{hi}")
    if prev is None:
        return min(options, key=lambda v: abs(sum(v) / len(v) - (lo + hi) / 2))
    return min(options, key=lambda v: abs(sum(v) / len(v) - sum(prev) / len(prev)))


def timeline() -> list[dict]:
    """Every chord with its start beat, length, section and bar position in the section."""
    out, t = [], 0.0
    for i, (section, chords) in enumerate(FORM):
        start = t
        for symbol, beats in chords:
            out.append({"t": t, "beats": beats, "symbol": symbol, "section": section, "section_start": start, "index": i})
            t += beats
        for c in out:
            if c["index"] == i:
                c["section_end"] = t
    return out


def h(spread: float = 0.012) -> float:
    return rng.uniform(-spread, spread)


def v(vel: float, spread: int = 6) -> int:
    return max(1, min(127, round(vel + rng.randint(-spread, spread))))


def drums(total: float, sections: list[tuple[str, float, float]]) -> list[Note]:
    notes = []
    for idx, (section, start, end) in enumerate(sections):
        bars = round((end - start) / 4)
        nxt = sections[idx + 1][0] if idx + 1 < len(sections) else None
        for bar in range(bars):
            b = start + bar * 4
            last = bar == bars - 1
            if section == "intro" and bar < 6:
                for e in range(8):  # tambourine and hat alone
                    notes.append(Note(b + e / 2 + h(), TAMB, v(78 if e % 2 else 58), 0.2))
                if bar >= 4:
                    notes += [Note(b + q + h(), HAT, v(50), 0.2) for q in range(4)]
                if bar == 5:
                    notes += [Note(b + 3 + s / 4 + h(0.006), SNARE, v(60 + s * 12), 0.2) for s in range(4)]
                continue
            if section == "outro" and last:
                notes += [Note(b, KICK, 112, 0.5), Note(b, CRASH, 110, 4)]
                continue
            fill = last and nxt not in (None, section) and section != "outro"
            first = bar == 0 and section in ("chorus", "solo", "outro", "interlude") or (section == "verse" and bar == 0 and idx > 1)
            if first:
                notes.append(Note(b + h(0.005), CRASH, v(96), 3))
            soft = section == "intro"
            if section in ("bridge", "middle"):
                notes.append(Note(b + h(0.008), KICK, v(100), 0.5))
                notes.append(Note(b + 2 + h(0.008), SIDE, v(84), 0.3))
                notes += [Note(b + q + h(), HAT, v(56), 0.2) for q in range(4) if not (fill and q == 3)]
                notes += [Note(b + e / 2 + h(), TAMB, v(66 if e % 2 else 48), 0.2) for e in range(8) if not (fill and e >= 6)]
            else:
                kicks = [(0, 108), (1.5, 78), (2, 100)] + ([(3.5, 70)] if bar % 4 == 3 else [])
                notes += [Note(b + k + h(0.008), KICK, v(vel - (18 if soft else 0)), 0.5) for k, vel in kicks]
                notes += [Note(b + s + h(0.01) + 0.01, SNARE, v(98 - (24 if soft else 0)), 0.3) for s in (1, 3) if not (fill and s == 3)]
                for e in range(8):
                    if fill and e >= 6:
                        continue
                    if section == "chorus" and bar % 2 == 1 and e == 7:
                        notes.append(Note(b + 3.5 + h(), OPEN_HAT, v(70), 0.45))
                    else:
                        notes.append(Note(b + e / 2 + h(), HAT, v((72 if e % 2 == 0 else 50) - (14 if soft else 0)), 0.2))
                for s in range(16):  # the jingle: tambourine sixteenths, beats 2 and 4 pushed
                    if fill and s >= 12:
                        continue
                    accent = 92 if s in (4, 12) else 70 if s % 4 == 0 else 52 if s % 2 == 0 else 38
                    notes.append(Note(b + s / 4 + h(0.008), TAMB, v(accent - (12 if soft else 0)), 0.15))
            if fill:
                notes += [Note(b + 3 + s / 4 + h(0.006), SNARE, v(64 + s * 13), 0.2) for s in range(4)]
    return notes


def bass(chords: list[dict]) -> list[Note]:
    notes = []
    for c in chords:
        if c["section"] == "intro" and c["t"] - c["section_start"] < 24:
            continue
        _, pc = chord(c["symbol"])
        root = 28 + (pc - 28) % 12  # E1 to D#2
        t, L = c["t"], c["beats"]
        if c["section"] == "outro" and c["symbol"] == "Bmaj13":
            notes.append(Note(t, root, 100, L - 0.2))
        elif c["section"] in ("bridge", "middle"):
            notes.append(Note(t + h(0.005), root, v(96), L - 0.15))
        elif L >= 4:
            for off in range(0, int(L), 4):
                pattern = [(0, root, 1.3, 108), (1.5, root + 12, 0.35, 82), (2, root, 0.9, 98),
                           (3, root + 7, 0.45, 86), (3.5, root + 12, 0.4, 78)]
                notes += [Note(t + off + o + h(0.006), n, v(vel), ln) for o, n, ln, vel in pattern]
        elif L == 2:
            notes += [Note(t + h(0.006), root, v(104), 0.9), Note(t + 1 + h(0.006), root + 12, v(80), 0.4),
                      Note(t + 1.5 + h(0.006), root + 7, v(86), 0.4)]
        else:
            notes.append(Note(t + h(0.006), root, v(100), L * 0.85))
    return notes


def pulse(chords: list[dict]) -> list[Note]:
    """Staccato stabs, each followed by quieter dotted-eighth echoes, like a synth into a delay."""
    notes, prev = [], None
    for c in chords:
        if c["section"] in ("bridge", "middle"):
            prev = None
            continue
        tones, _ = chord(c["symbol"])
        prev = voice(tones, 59, 78, prev)
        boost = 10 if c["section"] in ("intro", "solo", "interlude") else 0
        if c["section"] == "outro" and c["symbol"] == "Bmaj13":
            echoes = [(0, 100), (0.75, 66), (1.5, 44), (2.25, 30), (3.0, 20)]
        else:
            echoes = []
            for group in range(0, max(int(c["beats"]), 1), 2):
                left = c["beats"] - group
                echoes += [(group + o, vel) for o, vel in ((0, 96), (0.75, 62), (1.5, 40)) if o < left]
        for o, vel in echoes:
            notes += [Note(c["t"] + o + h(0.004) + i * 0.004, n, v(vel + boost, 4), 0.18) for i, n in enumerate(prev)]
    return notes


def choir(chords: list[dict]) -> list[Note]:
    level = {"bridge": 92, "middle": 92, "outro": 84, "chorus": 62, "solo": 58}
    notes, prev = [], None
    for c in chords:
        if c["section"] not in level:
            prev = None
            continue
        tones, _ = chord(c["symbol"])
        prev = voice(tones, 55, 74, prev)
        notes += [Note(c["t"] + 0.02, n, v(level[c["section"]], 3), c["beats"] - 0.06) for n in prev]
    return notes


def bells(chords: list[dict]) -> list[Note]:
    """Eighth-note arpeggios in the bridge, middle eight and solo; a bell on each change in the intro."""
    notes = []
    for c in chords:
        tones, _ = chord(c["symbol"])
        up = voice(tones, 76, 96, None)
        if c["section"] in ("bridge", "middle", "solo"):
            cycle = up + up[-2:0:-1]
            for e in range(int(c["beats"] * 2)):
                notes.append(Note(c["t"] + e / 2 + h(0.006), cycle[e % len(cycle)], v(78 if e % 2 == 0 else 64), 0.45))
        elif c["section"] == "intro" and c["beats"] >= 4:
            notes.append(Note(c["t"] + h(0.006), up[-1], v(70), 2.5))
        elif c["section"] == "outro" and c["symbol"] == "Bmaj13":
            notes += [Note(c["t"] + i * 0.25, n, 70 - i * 4, 6 - i * 0.25) for i, n in enumerate(up)]
    return notes


def main(template_xpj: Path, expansions: Path, out_dir: Path, project: str = NAME) -> None:
    chords = timeline()
    total = chords[-1]["t"] + chords[-1]["beats"]
    sections = []
    for c in chords:
        if not sections or sections[-1][1] != c["section_start"]:
            sections.append((c["section"], c["section_start"], c["section_end"]))
    assert total % 4 == 0 and all((e - s) % 4 == 0 for _, s, e in sections), "sections must be whole bars"

    def zones(spec):
        return zones_from_program(expansions / spec[0] / f"{spec[1]}.xpm")

    kit = {note: Pad(expansions / "Vintage Hardware Collection" / f"{wav}.WAV", group) for note, (wav, group) in KIT.items()}
    tracks = [
        Track("Drums", "Linn Kit", drums(total, sections), pads=kit),
        Track("Bass", "Minimoog Bass", bass(chords), zones=zones(BASS), release=0.08),
        Track("Pulse", "Prophet Pulse", pulse(chords), zones=zones(PULSE), release=0.12),
        Track("Choir", "Mellotron Choir", choir(chords), zones=zones(CHOIR), release=0.35),
        Track("Bells", "Glock Bells", bells(chords), zones=zones(BELLS), release=0.6),
        Track("Lead", "Minimoog Lead", [], zones=zones(LEAD), release=0.15),
    ]
    print(write_project(template_xpj, out_dir, project, tracks, BPM, int(total // 4)))
    print(f"{int(total // 4)} bars, {total / BPM:.1f} minutes")


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:4]), *sys.argv[4:5])
