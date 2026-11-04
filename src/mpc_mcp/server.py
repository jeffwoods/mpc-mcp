"""MCP server entry point. Tools are thin wrappers; the logic lives in the other modules."""

from __future__ import annotations

import functools
import json
import threading
from pathlib import Path
from typing import Any

import mido
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import midifile, project, sequence
from .midi_io import MidiRig, list_ports
from .notes import NoteEvent, parse_note
from .schedule import build_schedule

INSTRUCTIONS = """\
Tools for working with an Akai MPC (standalone hardware or desktop software).

Live MIDI: call midi_ports first to find the MPC's port names. Substrings like "mpc" are accepted.
On the MPC, set the target track's MIDI input to the channel you send on. play_notes runs in the
background; call stop_playback or midi_panic to stop. With send_clock=true the MPC can follow our
tempo if its sync setting is set to receive MIDI clock.

Times are in beats (quarter notes). Middle C is C4 = 60.

Files: write_midi_file is the reliable way to hand the MPC new parts (import the .mid on the MPC).
inspect_project decodes .xpj and .xpm files read-only; read_mpc_sequence reads the notes in .sxq
sequence files. The .xpj format is undocumented, so explore
with outline, find and path rather than assuming a structure. Never edit .xpj files.
"""

server = MCPServer("mpc", instructions=INSTRUCTIONS)


def tool(fn):
    """Register a tool. Expected failures (bad input, missing files, MIDI port errors) become
    ToolError so the model sees the message; the SDK hides the text of any other exception."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, IndexError, OSError) as err:
            raise ToolError(f"{type(err).__name__}: {err}") from err

    return server.tool()(wrapper)

rig = MidiRig()
_decoded: dict[tuple[str, float], dict[str, Any]] = {}


def _load(path: str) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    key = (str(p), p.stat().st_mtime)
    if key not in _decoded:
        _decoded[key] = project.decode(p)
    return _decoded[key]


def _clip(value: Any, limit: int = 20000) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return {"truncated": True, "size": len(text), "preview": text[:limit],
            "hint": "Use a deeper path or outline with lower depth."}


# Ports and live MIDI


@tool
def midi_ports() -> dict[str, list[str]]:
    """List MIDI input and output ports on this computer."""
    return list_ports()


@tool
def play_notes(
    port: str,
    events: list[NoteEvent],
    bpm: float = 90,
    loops: int = 1,
    loop_beats: float | None = None,
    send_clock: bool = False,
) -> dict[str, Any]:
    """Play note events out a MIDI port in the background.

    loop_beats sets the loop length (for example 16 for four bars of 4/4); otherwise the loop ends
    at the last note-off. send_clock also sends MIDI start, clock and stop.
    """
    schedule = build_schedule(events, bpm=bpm, loops=loops, loop_beats=loop_beats, send_clock=send_clock)
    seconds = rig.play(port, schedule)
    return {"playing": True, "seconds": round(seconds, 2), "messages": len(schedule)}


@tool
def stop_playback() -> dict[str, bool]:
    """Stop background playback. Sounding notes get note-offs."""
    rig.stop()
    return {"playing": rig.is_playing()}


@tool
def send_note(port: str, note: int | str, velocity: int = 100, length_seconds: float = 0.25, channel: int = 1) -> str:
    """Play a single note now. Handy for auditioning a pad or checking the connection."""
    number = parse_note(note)
    out = rig.output(port)
    out.send(mido.Message("note_on", note=number, velocity=velocity, channel=channel - 1))
    threading.Timer(
        length_seconds, out.send, args=(mido.Message("note_off", note=number, velocity=0, channel=channel - 1),)
    ).start()
    return f"sent {number} on channel {channel}"


@tool
def send_control(port: str, control: int, value: int, channel: int = 1) -> str:
    """Send a MIDI CC (0-127). The MPC can map CCs to parameters with MIDI learn."""
    rig.send(port, mido.Message("control_change", control=control, value=value, channel=channel - 1))
    return f"CC{control}={value} on channel {channel}"


@tool
def send_program_change(port: str, program: int, channel: int = 1) -> str:
    """Send a program change (0-127)."""
    rig.send(port, mido.Message("program_change", program=program, channel=channel - 1))
    return f"program {program} on channel {channel}"


@tool
def transport(port: str, action: str) -> str:
    """Send MIDI realtime transport: "start", "stop" or "continue". The MPC responds only if its
    sync settings accept MIDI start/stop from this port."""
    if action not in ("start", "stop", "continue"):
        raise ValueError('action must be "start", "stop" or "continue"')
    rig.send(port, mido.Message(action))
    return action


@tool
def midi_panic(port: str) -> str:
    """Stop playback and send all-notes-off and all-sound-off on every channel."""
    rig.panic(port)
    return "panic sent"


@tool
def start_recording(port: str, bpm: float = 90) -> dict[str, Any]:
    """Start capturing notes from a MIDI input (for example the MPC's pads, with MIDI out enabled).
    Call stop_recording to get the events back in beats at the given bpm."""
    real = rig.start_recording(port, bpm)
    return {"recording": True, "port": real}


@tool
def stop_recording() -> dict[str, Any]:
    """Stop capturing and return what was played as note events."""
    return rig.stop_recording()


# Files


@tool
def write_midi_file(path: str, parts: dict[str, list[NoteEvent]], bpm: float = 90) -> str:
    """Write a type 1 .mid with one track per part (part name becomes the track name).
    Save it to the MPC's SD card or USB stick, then import it on the MPC."""
    return str(midifile.write_midi(Path(path), parts, bpm))


@tool
def read_midi_file(path: str) -> dict[str, Any]:
    """Read a .mid into tempo and per-track note events. Use it on MIDI exported from the MPC."""
    return _clip(midifile.read_midi(Path(path)))


@tool
def read_mpc_sequence(path: str) -> dict[str, Any]:
    """Read an MPC sequence (.sxq, in a project's _[ProjectData] folder) into tempo and per-track
    notes in beats. Read-only."""
    return _clip(sequence.read_sequence(Path(path)), limit=60000)


@tool
def scan_mpc_folder(folder: str) -> dict[str, Any]:
    """List MPC files (projects, programs, sequences, MIDI) under a folder such as a mounted SD card."""
    return project.scan_folder(Path(folder))


@tool
def inspect_project(path: str, mode: str = "outline", query: str = "", depth: int = 3) -> Any:
    """Read-only look inside an .xpj, .xpm or other MPC file.

    mode "outline": structure with keys and list lengths, to the given depth (query is an optional
    starting path). mode "path": the value at a dotted path like "tracks.0" (query is the path).
    mode "find": paths of keys containing the query text, such as "sequence" or "note".
    mode "info": container and format only.
    """
    decoded = _load(path)
    info = {k: v for k, v in decoded.items() if k not in ("data", "text")}
    if decoded["data"] is None:
        if decoded.get("text"):
            info["text_preview"] = decoded["text"][:4000]
        return info
    data = decoded["data"]
    if mode == "info":
        return info
    if mode == "outline":
        return {**info, "outline": _clip(project.outline(project.get_path(data, query), depth=depth))}
    if mode == "path":
        return _clip(project.get_path(data, query))
    if mode == "find":
        return project.find_keys(data, query)
    raise ValueError('mode must be "outline", "path", "find" or "info"')


@tool
def summarize_program(path: str) -> dict[str, Any]:
    """Name, type and sample list for an .xpm drum or keygroup program."""
    return project.summarize_program(Path(path))


def main() -> None:
    try:
        server.run("stdio")
    finally:
        rig.close()


if __name__ == "__main__":
    main()
