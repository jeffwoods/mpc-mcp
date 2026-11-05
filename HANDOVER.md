# Handover: generated projects now play on hardware

State on 2026-11-04. Repo: ~/claudeprojects/mpc-mcp, pushed to github.com/jeffwoods/mpc-mcp (main). Project memory: `mpc-mcp-project` in ~/.claude/projects/-Users-jeff-claudeprojects/memory/.

## Resolved: Dilla Sketch was silent
"First Project" (OS 2.10 factory content, used as the template) saves `Audio 001.Audio.xpm` with `Mute` and `Solo` True. A soloed program silences every other track, pads included. The generator copied it, so every generated project was silent. Found by bisecting on the hardware against "Coya jam june 21 2", a working 2.15.1 project Jeff saved to the card.

- The generator (`examples/dilla_sketch.py`) clears mute and solo on every program it writes and takes a project name argument. "Dilla Sketch 3" plays on Jeff's Live II.
- `check_project_for_standalone` has a `mix` check that fails on a soloed program.

## Program builders
`program.py` builds drum and keygroup programs from blank programs OS 2.15.1 wrote (Coya jam's Program 001 and 002, gzipped in `templates/`). MCP tools: `read_drum_pads`, `build_drum_program`, `read_keygroup_zones`, `build_keygroup_program`.
- Drums: confirmed on hardware ("Dilla Sketch 4" played). Rebuilding Coya's Urban Kit reproduced the OS's SampleName, SliceEnd and MuteGroup on all 16 pads.
- Keygroups: `RootNote` = note + 1 (from OS 2.11 expansions); 0 = use the WAV's smpl unity (OS 2.7 expansions). We write the explicit form with KeyTrack True, one instrument per keygroup as the 2.15.1 blank does. Loops set SliceLoop 1 and SliceLoopStart plus LoopStart/LoopEnd. Confirmed on hardware ("Dilla Sketch 6"): bass and keys in tune, Taurus sustains on its loop.
- Keys were silent in Dilla Sketch 3-5 because the Keys track was saved muted: its header was copied from First Project's track 3, which is muted (state byte 07; bit 0 = mute). `retarget_track_header` now clears the mute bit, and `check_project_for_standalone` warns about muted tracks. Keygroup pads in bank A play notes 0-15, so pads only sound when a zone covers those notes (Rhodes starts at 21; use banks C/D).
- "Dilla Sketch 6" is the first generated project with all three tracks playing, all programs built (Taurus and Rhodes zones read from the expansions). Drier than Dilla Sketch 4, whose copied programs had a Compressor Vintage insert.
- Keygroup pads: the builder rotates PadNoteMap so pad 1 is the first C the keygroups cover (Rhodes: bank A = 24-39). Confirmed on hardware: OS 2.15.1 honours a keygroup PadNoteMap ("Dilla Sketch 7" bank A plays the Rhodes).
- Not built: velocity layers (zones_from_program takes the first layer only), insert effects, envelopes other than release.

## Project writer
`song.write_project(template_xpj, out_dir, name, tracks, bpm, bars)` writes programs, the sequence and the .xpj. Every track header is cloned from the template's first track, so any track count works. `examples/dilla_sketch.py` now uses it and rebuilds Dilla Sketch 7 byte for byte, apart from the bass track's state byte (06 instead of 0e). `examples/christmastime.py` writes "Christmastime Karaoke" (6 tracks, 113 bars, B, 95 BPM): chords and form from a chord sheet, bar counts inferred, about a minute longer than the record. Awaiting a hardware test. Bars over 127 are untested (the bar count may be a 7-bit pair). Next: expose write_project as an MCP tool.

## Confirmed .sxq facts (see sequence.py and README)
- Track header `47 61 10`: byte 4 is the track index, byte 5 the type (00 drum, 01 keygroup, 03 plugin), and it ends with a length-prefixed program name. `47 61 15` repeats the index in byte 3. `pytT 03` appears on plugin tracks only. The byte before `00 64 00 00 00 00 00` is track state; bit 0 = mute (confirmed). Bit 3 (0x08, set on First Project's track 2) is unknown; that track played.
- OS 2.15.1 writes notes as `47 61 11 02 ... <byte 19 = 100>`; older files write `00 ... 00`. Untested whether 2.15 plays the old form; the encoder writes the 2.15 form.

## Open
- The meaning of note byte 19 (21 to 100 in real files; maybe probability).
- 2.15.1 projects write polytouch events with value 0 at tick 0, one per note used; we omit them and it still plays.
- MPC OS 3.10 doesn't add USB MIDI in standalone or remote control for the Live II; its new control feature is MPK keyboards plugged into the MPC. Recommendation was to stay on 2.15.1.

## Hygiene
- Coya Copy and the reference files are on the SD card. The 16 GB internal storage, where Jeff's own projects live, doesn't mount in Controller Mode; only MPC_HDD (Expansions) and the SD card ("Untitled") do. To read one of his projects, have him Save As onto the card.
- Run `dot_clean -m` on new folders on the card. ⌘⌃⇧M unmounts just the MPC's drives (from the "this computer" project).
- Never write over Jeff's existing projects; only create new folders.
