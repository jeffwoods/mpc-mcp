"""Read MPC sequence files (.sxq).

An .sxq is a standard type 1 MIDI file, but the MPC doesn't store notes as note-on/off. Each note
is a sequencer-specific meta event with Akai's prefix "Ga" (0x47 0x61) and type 0x11:

    47 61 11 00 <note> <velocity> 00 00 00 40 <length, 7-bit chunks, low first> 00 ...

Pad pressure is stored as polyphonic aftertouch. Worked out from files saved by MPC OS 2.10;
other versions may differ, so anything unrecognised is counted and reported, not guessed at.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mido

AKAI_PREFIX = b"Ga"
NOTE_EVENT = 0x11


def decode_note(data: bytes) -> tuple[int, int, int] | None:
    """Return (note, velocity, length_ticks) for an Akai note event, else None."""
    if len(data) < 12 or data[:2] != AKAI_PREFIX or data[2] != NOTE_EVENT:
        return None
    note, velocity = data[4], data[5]
    length = 0
    for i, b in enumerate(data[10:14]):
        length |= (b & 0x7F) << (7 * i)
    return note, velocity, length


def read_sequence(path: Path) -> dict[str, Any]:
    mid = mido.MidiFile(Path(path).expanduser())
    ppq = mid.ticks_per_beat
    info: dict[str, Any] = {"ppq": ppq, "bpm": None, "time_signature": None, "key": None, "name": None, "tracks": []}

    for index, track in enumerate(mid.tracks):
        name = None
        ticks = 0
        notes = []
        pressure = 0
        standard_notes = []
        unknown_akai = 0
        for msg in track:
            ticks += msg.time
            if msg.type == "track_name":
                name = msg.name.rstrip("\x00")
            elif msg.type == "set_tempo":
                info["bpm"] = round(mido.tempo2bpm(msg.tempo), 3)
            elif msg.type == "time_signature":
                info["time_signature"] = f"{msg.numerator}/{msg.denominator}"
            elif msg.type == "key_signature":
                info["key"] = msg.key
            elif msg.type == "sequencer_specific":
                decoded = decode_note(bytes(msg.data))
                if decoded:
                    note, velocity, length = decoded
                    notes.append({"note": note, "start": round(ticks / ppq, 4),
                                  "length": round(max(length, 1) / ppq, 4), "velocity": velocity})
                elif bytes(msg.data)[:2] != AKAI_PREFIX:
                    unknown_akai += 1
            elif msg.type == "polytouch":
                pressure += 1
            elif msg.type == "note_on" and msg.velocity > 0:
                standard_notes.append(msg.note)
        if index == 0 and not notes:
            info["name"] = name
            continue
        if not notes and not name:
            continue
        entry: dict[str, Any] = {"track": index, "name": name, "notes": notes}
        if pressure:
            entry["pressure_events"] = pressure
        if standard_notes:
            entry["note"] = f"{len(standard_notes)} standard note-ons not shown; this file may not be MPC-native"
        if unknown_akai:
            entry["unrecognised_events"] = unknown_akai
        info["tracks"].append(entry)
    return info
