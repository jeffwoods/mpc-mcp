"""Read MPC sequence files (.sxq).

An .sxq is a standard type 1 MIDI file, but the MPC doesn't store notes as note-on/off. Each note
is a sequencer-specific meta event with Akai's prefix "Ga" (0x47 0x61) and type 0x11:

    47 61 11 00 <note> <velocity> 00 00 00 40 <length, 7-bit chunks, low first> 00 ...

Pad pressure is stored as polyphonic aftertouch. Each track starts with a header event (type 0x10):
byte 4 is the track index, byte 5 the track type (TRACK_TYPES), and it ends with the program name,
length-prefixed. A type 0x15 event repeats the track index in byte 3. Plugin tracks, and only
those, carry a "pytT" 03 event before the track name.

Worked out from files saved by MPC 2.0, 2.8 and OS 2.10; other versions may differ, so anything
unrecognised is counted and reported, not guessed at.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mido

AKAI_PREFIX = b"Ga"
NOTE_EVENT = 0x11
TRACK_HEADER = 0x10
TRACK_STATE = 0x15
TRACK_TYPES = {0x00: "Drum", 0x01: "Keygroup", 0x03: "Plugin"}
PLUGIN_MARKER = b"pytT\x03"


def _name_offset(data: bytes) -> int | None:
    """Offset of the length byte of the trailing program name. The bytes before it vary by OS
    version, so find the earliest length byte whose name runs exactly to the end in printable text."""
    start = len(data)
    while start > 0 and 0x20 <= data[start - 1] < 0x7F:
        start -= 1
    for p in range(max(start - 1, 6), len(data)):
        if data[p] == len(data) - p - 1:
            return p
    return None


def parse_track_header(data: bytes) -> dict[str, Any] | None:
    """Return the track index, type and program name from a track header event, else None."""
    if len(data) < 6 or data[:2] != AKAI_PREFIX or data[2] != TRACK_HEADER:
        return None
    offset = _name_offset(data)
    return {"index": data[4], "type": TRACK_TYPES.get(data[5], f"unknown ({data[5]:#04x})"),
            "program": data[offset + 1:].decode("ascii") if offset is not None else None}


def retarget_track_header(data: bytes, index: int, kind: str, program: str) -> bytes:
    """Copy a track header, pointing it at another track index, type and program."""
    offset = _name_offset(data)
    if offset is None:
        raise ValueError("track header has no program name")
    body = bytearray(data[:offset])
    body[4], body[5] = index, {v: k for k, v in TRACK_TYPES.items()}[kind]
    name = program.encode("ascii")
    return bytes(body) + bytes([len(name)]) + name


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
        header = None
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
                if header is None:
                    header = parse_track_header(bytes(msg.data))
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
        if header:
            entry["type"], entry["program"] = header["type"], header["program"]
        if pressure:
            entry["pressure_events"] = pressure
        if standard_notes:
            entry["note"] = f"{len(standard_notes)} standard note-ons not shown; this file may not be MPC-native"
        if unknown_akai:
            entry["unrecognised_events"] = unknown_akai
        info["tracks"].append(entry)
    return info
