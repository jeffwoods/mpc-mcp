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
- `read_mpc_sequence`: the notes in an MPC sequence (`.sxq`), per track, in beats
- `scan_mpc_folder`: list projects, programs and sequences on an SD card or USB stick
- `inspect_project`: read-only exploration of `.xpj`, `.xpm` and other MPC files (outline, path, find)
- `summarize_program`: name, type and samples of an `.xpm` program
- `read_drum_pads`: which sample sits on which note in a drum program, such as an expansion kit
- `build_drum_program`: a new drum program from any WAV files, one per note, with mute groups and tuning. Samples are copied in next to it. Mix sounds from several kits with `read_drum_pads`.
- `check_project_for_standalone`: before moving a desktop project onto the hardware, checks the saving version against the hardware OS, files missing or outside the project folder, samples that programs need, plugins the hardware may lack, and sample memory against the hardware's RAM

## What it doesn't do (yet)

- **Write `.xpj` project files.** The format is undocumented and has changed between MPC OS versions. MPC OS 2.10 writes XML (confirmed). Community reports say MPC 3 uses gzip-compressed JSON; others describe it as binary or encrypted. This server reads them defensively and never writes them.
- **Control the MPC's screen or menus.** There's no remote API for that. Everything goes through MIDI and files.
- **Create keygroup programs.** Drum programs only so far.

## Connecting the MPC

Check `midi_ports` after connecting. What we've confirmed on an MPC Live II running MPC OS 2.15.1:
- **Standalone mode:** the MPC does not appear on USB at all. Use a USB MIDI interface to its 5-pin MIDI in/out. Move files by SD card or USB stick.
- **Controller Mode:** the MPC appears as four MIDI ports plus its internal drive and SD card as volumes. Sound then comes from the MPC desktop software, which you can reach through a virtual port (macOS IAC Driver).

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

## File formats we've confirmed

From projects saved by MPC OS 2.10 on an MPC Live II:

- `.xpj`: XML. Tempo, key, mixer, Q-Link assignments and the project's file list.
- `.xpm`: XML programs (drum, keygroup, plugin, audio). A plugin program describes its plugin with `Name`, `ManufacturerName`, `FormatName` and `FileOrID`; built-in instruments have `FormatName` `MPC` (for example `MPC:TubeSynth` by AIR Music Technology).
- `.sxq`: a standard type 1 MIDI file (960 PPQ), but notes are stored as Akai sequencer-specific meta events, not note-on/off: `47 61 11 <flags> <note> <velocity> 00 00 00 40 <length in 7-bit chunks, low first> 00 00 00 00 00 00 <value>`. OS 2.15.1 saves flags `02` and a value that is usually 100 (seen from 21 to 100, possibly probability). Older files have `00` and `00`. Pad pressure is polyphonic aftertouch. A regular MIDI reader sees no notes.
- `.sxq` tracks: each starts with a `47 61 10` header. Byte 4 is the track index and byte 5 the track type (`00` drum, `01` keygroup, `03` plugin). It ends with the program name, length-prefixed. The bytes in between vary by OS version. A `47 61 15` event repeats the track index in byte 3. Plugin tracks, and only those, carry a `pytT 03` event before the track name. Confirmed against projects saved by MPC 2.0 and 2.8 as well as OS 2.10.
- Programs carry their own `Mute` and `Solo`. A soloed program silences every other track, pads included. First Project, the OS 2.10 factory project, ships with its audio program muted and soloed, so anything built from it is silent. `check_project_for_standalone` flags this.
- Drum programs (OS 2.15.1): instrument N is pad N, and `PadNoteMap` gives each pad's note. The default map (A01 = 37, A02 = 36, A03 = 42 ...) covers all 128 notes; expansion kits often use their own. Loading a sample sets the layer's `SampleName` to the file's stem and `SliceEnd` to its frame count minus 1. `build_drum_program` starts from a blank program saved by OS 2.15.1 and changes only those fields, plus mute group, tuning and filter type.
- In Controller Mode (OS 2.15.1), the Live II shows up on a Mac as a USB hub with an audio interface, four MIDI ports ("MPC Public", "MPC Private", "MIDI Port A", "MIDI Port B"), and its internal drive and SD card as volumes.

Reports from other models and OS versions are welcome.

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
