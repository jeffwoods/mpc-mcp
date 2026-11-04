"""Live MIDI: ports, background playback, and recording."""

from __future__ import annotations

import threading
import time

import mido

from .schedule import Timed, messages_to_events


def list_ports() -> dict[str, list[str]]:
    return {"outputs": mido.get_output_names(), "inputs": mido.get_input_names()}


def _match(name: str, available: list[str]) -> str:
    """Accept an exact port name or a case-insensitive substring like "mpc"."""
    if name in available:
        return name
    hits = [p for p in available if name.lower() in p.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(f"no MIDI port matches {name!r}. Available: {available}")
    raise ValueError(f"{name!r} matches several ports: {hits}")


class MidiRig:
    """Holds open ports so repeated calls don't reopen them, and owns the playback and record threads."""

    def __init__(self) -> None:
        self._outs: dict[str, mido.ports.BaseOutput] = {}
        self._lock = threading.Lock()
        self._play_thread: threading.Thread | None = None
        self._stop_play = threading.Event()
        self._rec_port: mido.ports.BaseInput | None = None
        self._rec_messages: list[tuple[float, mido.Message]] = []
        self._rec_start = 0.0
        self._rec_bpm = 120.0

    def output(self, name: str) -> mido.ports.BaseOutput:
        real = _match(name, mido.get_output_names())
        with self._lock:
            if real not in self._outs or self._outs[real].closed:
                self._outs[real] = mido.open_output(real)
            return self._outs[real]

    def send(self, port: str, message: mido.Message) -> None:
        self.output(port).send(message)

    # Playback

    def play(self, port: str, schedule: list[Timed]) -> float:
        """Start playback in the background. Returns the length in seconds."""
        out = self.output(port)
        self.stop()
        self._stop_play.clear()
        self._play_thread = threading.Thread(target=self._run, args=(out, schedule), daemon=True)
        self._play_thread.start()
        return schedule[-1].seconds if schedule else 0.0

    def _run(self, out: mido.ports.BaseOutput, schedule: list[Timed]) -> None:
        t0 = time.perf_counter()
        sounding: set[tuple[int, int]] = set()
        try:
            for item in schedule:
                wait = t0 + item.seconds - time.perf_counter()
                if wait > 0 and self._stop_play.wait(wait):
                    break
                msg = item.message
                out.send(msg)
                if msg.type == "note_on":
                    sounding.add((msg.channel, msg.note))
                elif msg.type == "note_off":
                    sounding.discard((msg.channel, msg.note))
        finally:
            for ch, note in sounding:
                out.send(mido.Message("note_off", channel=ch, note=note, velocity=0))
            if self._stop_play.is_set() and any(i.message.type == "clock" for i in schedule):
                out.send(mido.Message("stop"))

    def is_playing(self) -> bool:
        return bool(self._play_thread and self._play_thread.is_alive())

    def stop(self) -> None:
        if self.is_playing():
            self._stop_play.set()
            self._play_thread.join(timeout=2)

    def panic(self, port: str) -> None:
        self.stop()
        out = self.output(port)
        for ch in range(16):
            out.send(mido.Message("control_change", channel=ch, control=123, value=0))
            out.send(mido.Message("control_change", channel=ch, control=120, value=0))

    # Recording

    def start_recording(self, port: str, bpm: float) -> str:
        self.stop_recording()
        real = _match(port, mido.get_input_names())
        self._rec_messages = []
        self._rec_bpm = bpm
        self._rec_start = time.perf_counter()
        self._rec_port = mido.open_input(real, callback=self._on_message)
        return real

    def _on_message(self, msg: mido.Message) -> None:
        if msg.type in ("note_on", "note_off", "control_change", "pitchwheel", "program_change"):
            self._rec_messages.append((time.perf_counter() - self._rec_start, msg))

    def is_recording(self) -> bool:
        return self._rec_port is not None

    def stop_recording(self) -> dict:
        if self._rec_port is None:
            return {"recording": False, "events": [], "other_messages": 0}
        self._rec_port.close()
        self._rec_port = None
        stamped = list(self._rec_messages)
        notes = [(t, m) for t, m in stamped if m.type in ("note_on", "note_off")]
        events = messages_to_events(_trim_leading_silence(notes), self._rec_bpm)
        return {
            "recording": False,
            "bpm": self._rec_bpm,
            "events": [e.model_dump() for e in events],
            "other_messages": len(stamped) - len(notes),
            "note": "Start times are measured from the first note played, not from when recording began.",
        }

    def close(self) -> None:
        self.stop()
        self.stop_recording()
        for out in self._outs.values():
            out.close()


def _trim_leading_silence(stamped: list[tuple[float, mido.Message]]) -> list[tuple[float, mido.Message]]:
    if not stamped:
        return stamped
    first = stamped[0][0]
    return [(t - first, m) for t, m in stamped]

