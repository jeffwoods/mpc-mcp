"""Pure timing: turn note events into time-ordered MIDI messages. No ports, so it's testable."""

from __future__ import annotations

from dataclasses import dataclass

import mido

from .notes import NoteEvent, parse_note

CLOCKS_PER_BEAT = 24


@dataclass(frozen=True)
class Timed:
    seconds: float
    message: mido.Message


def build_schedule(
    events: list[NoteEvent],
    bpm: float,
    loops: int = 1,
    loop_beats: float | None = None,
    send_clock: bool = False,
) -> list[Timed]:
    """Return messages sorted by time. Note-offs sort before note-ons at the same instant,
    so repeated notes retrigger instead of being cut off."""
    if bpm <= 0:
        raise ValueError("bpm must be positive")
    if loops < 1:
        raise ValueError("loops must be at least 1")
    sec_per_beat = 60.0 / bpm
    end = max((e.start + e.length for e in events), default=0.0)
    span = loop_beats if loop_beats is not None else end
    if span <= 0:
        raise ValueError("nothing to play")

    out: list[tuple[float, int, mido.Message]] = []
    for i in range(loops):
        offset = i * span
        for e in events:
            note = parse_note(e.note)
            ch = e.channel - 1
            on = (offset + e.start) * sec_per_beat
            off = (offset + e.start + e.length) * sec_per_beat
            out.append((on, 2, mido.Message("note_on", note=note, velocity=e.velocity, channel=ch)))
            out.append((off, 1, mido.Message("note_off", note=note, velocity=0, channel=ch)))

    total = loops * span * sec_per_beat
    if send_clock:
        out.append((0.0, 0, mido.Message("start")))
        ticks = int(round(loops * span * CLOCKS_PER_BEAT))
        for t in range(ticks):
            out.append((t * sec_per_beat / CLOCKS_PER_BEAT, 0, mido.Message("clock")))
        out.append((total, 3, mido.Message("stop")))

    out.sort(key=lambda x: (x[0], x[1]))
    return [Timed(t, m) for t, _, m in out]


def messages_to_events(stamped: list[tuple[float, mido.Message]], bpm: float) -> list[NoteEvent]:
    """Pair note-on/off from a recording (seconds since start) into beat-timed events."""
    beats_per_sec = bpm / 60.0
    open_notes: dict[tuple[int, int], tuple[float, int]] = {}
    events: list[NoteEvent] = []
    last = 0.0
    for t, msg in stamped:
        last = max(last, t)
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes[(msg.channel, msg.note)] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on"):
            started = open_notes.pop((msg.channel, msg.note), None)
            if started:
                events.append(_event(msg.note, msg.channel, started, t, beats_per_sec))
    for (ch, note), started in open_notes.items():
        events.append(_event(note, ch, started, last, beats_per_sec))
    events.sort(key=lambda e: (e.start, e.note))
    return events


def _event(note: int, channel: int, started: tuple[float, int], ended: float, bps: float) -> NoteEvent:
    t0, vel = started
    return NoteEvent(
        note=note,
        start=round(t0 * bps, 4),
        length=max(round((ended - t0) * bps, 4), 0.001),
        velocity=vel,
        channel=channel + 1,
    )
