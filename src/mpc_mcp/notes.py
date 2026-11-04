"""Note names and the event model shared by playback, recording and MIDI files."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def parse_note(value: int | str) -> int:
    """Turn 60, "60", "C4" or "F#3" into a MIDI note number. Middle C is C4 = 60."""
    if isinstance(value, int):
        number = value
    elif value.strip().lstrip("-").isdigit():
        number = int(value)
    else:
        match = _NOTE_RE.match(value.strip())
        if not match:
            raise ValueError(f"not a note: {value!r}")
        letter, accidental, octave = match.groups()
        number = _NAMES[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental] + (int(octave) + 1) * 12
    if not 0 <= number <= 127:
        raise ValueError(f"note out of range 0-127: {value!r}")
    return number


def note_name(number: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[number % 12]}{number // 12 - 1}"


class NoteEvent(BaseModel):
    """One note. Times are in beats (quarter notes) from the start of the part."""

    note: int | str = Field(description='MIDI number or name like "C4" (middle C) or "F#2"')
    start: float = Field(ge=0, description="Start time in beats")
    length: float = Field(gt=0, default=0.25, description="Duration in beats")
    velocity: int = Field(ge=1, le=127, default=100)
    channel: int = Field(ge=1, le=16, default=1, description="MIDI channel 1-16")

    @field_validator("note")
    @classmethod
    def _check_note(cls, v: int | str) -> int:
        return parse_note(v)
