"""Write and read standard MIDI files. The MPC imports .mid reliably, so this is the safe write path."""

from __future__ import annotations

from pathlib import Path

import mido

from .notes import NoteEvent, parse_note
from .schedule import messages_to_events

PPQ = 960


def write_midi(path: Path, parts: dict[str, list[NoteEvent]], bpm: float) -> Path:
    """One track per part, type 1 file. Track 0 carries tempo."""
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    tempo = mido.MidiTrack()
    tempo.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tempo.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(tempo)

    for name, events in parts.items():
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        absolute: list[tuple[int, int, mido.Message]] = []
        for e in events:
            note, ch = parse_note(e.note), e.channel - 1
            on = round(e.start * PPQ)
            off = round((e.start + e.length) * PPQ)
            absolute.append((on, 1, mido.Message("note_on", note=note, velocity=e.velocity, channel=ch)))
            absolute.append((off, 0, mido.Message("note_off", note=note, velocity=0, channel=ch)))
        absolute.sort(key=lambda x: (x[0], x[1]))
        now = 0
        for tick, _, msg in absolute:
            track.append(msg.copy(time=tick - now))
            now = tick
        mid.tracks.append(track)

    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(path)
    return path


def read_midi(path: Path) -> dict:
    """Return tempo and per-track note events in beats."""
    mid = mido.MidiFile(Path(path).expanduser())
    bpm = 120.0
    tracks = {}
    for i, track in enumerate(mid.tracks):
        name = f"track {i}"
        ticks = 0
        stamped = []
        for msg in track:
            ticks += msg.time
            if msg.type == "set_tempo":
                bpm = round(mido.tempo2bpm(msg.tempo), 3)
            elif msg.type == "track_name":
                name = msg.name
            elif msg.type in ("note_on", "note_off"):
                stamped.append((ticks / mid.ticks_per_beat, msg))
        if stamped:
            # Times are already in beats; bpm=60 makes the seconds-to-beats conversion a no-op.
            tracks[name] = [e.model_dump() for e in messages_to_events(stamped, bpm=60)]
    return {"bpm": bpm, "tracks": tracks}
