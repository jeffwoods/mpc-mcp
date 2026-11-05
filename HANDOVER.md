# Handover: generated projects now play on hardware

State on 2026-11-04. Repo: ~/claudeprojects/mpc-mcp, pushed to github.com/jeffwoods/mpc-mcp (main). Project memory: `mpc-mcp-project` in ~/.claude/projects/-Users-jeff-claudeprojects/memory/.

## Resolved: Dilla Sketch was silent
"First Project" (OS 2.10 factory content, used as the template) saves `Audio 001.Audio.xpm` with `Mute` and `Solo` True. A soloed program silences every other track, pads included. The generator copied it, so every generated project was silent. Found by bisecting on the hardware against "Coya jam june 21 2", a working 2.15.1 project Jeff saved to the card.

- The generator (`examples/dilla_sketch.py`) clears mute and solo on every program it writes and takes a project name argument. "Dilla Sketch 3" plays on Jeff's Live II.
- `check_project_for_standalone` has a `mix` check that fails on a soloed program.

## Confirmed .sxq facts (see sequence.py and README)
- Track header `47 61 10`: byte 4 is the track index, byte 5 the type (00 drum, 01 keygroup, 03 plugin), and it ends with a length-prefixed program name. `47 61 15` repeats the index in byte 3. `pytT 03` appears on plugin tracks only.
- OS 2.15.1 writes notes as `47 61 11 02 ... <byte 19 = 100>`; older files write `00 ... 00`. Untested whether 2.15 plays the old form; the encoder writes the 2.15 form.

## Open
- The meaning of note byte 19 (21 to 100 in real files; maybe probability).
- 2.15.1 projects write polytouch events with value 0 at tick 0, one per note used; we omit them and it still plays.
- MPC OS 3.10 doesn't add USB MIDI in standalone or remote control for the Live II; its new control feature is MPK keyboards plugged into the MPC. Recommendation was to stay on 2.15.1.

## Hygiene
- Coya Copy and the reference files are on the SD card. The 16 GB internal storage, where Jeff's own projects live, doesn't mount in Controller Mode; only MPC_HDD (Expansions) and the SD card ("Untitled") do. To read one of his projects, have him Save As onto the card.
- Run `dot_clean -m` on new folders on the card. ⌘⌃⇧M unmounts just the MPC's drives (from the "this computer" project).
- Never write over Jeff's existing projects; only create new folders.
