# mpc-mcp

An unofficial [MCP](https://modelcontextprotocol.io) server for Akai MPC hardware and software. It lets an AI assistant like Claude play parts into your MPC over MIDI, record what you play on the pads, write MIDI files the MPC can import, and look inside MPC project and program files.

Not affiliated with or endorsed by Akai Professional. "MPC" and "Akai" are their trademarks.

## What it does

**Live MIDI**
- `midi_ports`: list MIDI ports
- `play_notes`: play note events (in beats, at a tempo) in the background, looped, optionally sending MIDI clock
- `send_note`, `send_control`, `send_program_change`, `transport`
- `stop_playback`, `midi_panic`
- `start_recording` / `stop_recording`: capture what you play and return it as note events

**Files**
- `write_midi_file`: one track per part. Import the .mid on the MPC.
- `read_midi_file`: read MIDI exported from the MPC
- `scan_mpc_folder`: list projects, programs and sequences on an SD card or USB stick
- `inspect_project`: read-only exploration of `.xpj`, `.xpm` and other MPC files (outline, path, find)
- `summarize_program`: name, type and samples of an `.xpm` program

## What it doesn't do (yet)

- **Write `.xpj` project files.** The format is undocumented and has changed between MPC OS versions. Community reports say MPC 3 uses gzip-compressed JSON; others describe it as binary or encrypted. This server reads them defensively and never writes them.
- **Control the MPC's screen or menus.** There's no remote API for that. Everything goes through MIDI and files.
- **Create `.xpm` programs.** Planned, once it's tested against programs saved by real hardware.

## Connecting the MPC

Any of these should work. Which ones depend on your model and OS version, so check `midi_ports` after connecting.
- A USB MIDI interface to the MPC's 5-pin MIDI in/out
- USB from the MPC to the computer, if your MPC shows up as a MIDI device
- The MPC desktop software, through its MIDI ports or a virtual port (macOS IAC Driver)

On the MPC, set the receiving track's MIDI input to the port and channel you send on. To capture pads, enable MIDI out on the track. To follow `send_clock`, set the MPC to sync to incoming MIDI clock.

## Install

Python 3.11+.

```bash
git clone <repo-url> && cd mpc-mcp
python3 -m venv .venv && .venv/bin/pip install -e .
```

Claude Code:

```bash
claude mcp add mpc -- /path/to/mpc-mcp/.venv/bin/mpc-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{ "mcpServers": { "mpc": { "command": "/path/to/mpc-mcp/.venv/bin/mpc-mcp" } } }
```

## Conventions

Times are in beats (quarter notes). Notes are MIDI numbers or names, with middle C = C4 = 60. Channels are 1-16.

## Development

```bash
.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest
```

The tests include a loopback through a virtual MIDI port, so playback timing is checked against real CoreMIDI (macOS) or ALSA (Linux) without hardware.

Sample files from real MPCs are the most useful contribution. If you can share an `.xpj` or `.xpm` from your MPC OS version (no copyrighted samples needed), open an issue.

## License

MIT
