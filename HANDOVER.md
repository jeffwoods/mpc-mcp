# Handover: Dilla Sketch loads but is silent

State on 2026-11-04. Repo: ~/claudeprojects/mpc-mcp, pushed to github.com/jeffwoods/mpc-mcp (main). Project memory: `mpc-mcp-project` in ~/.claude/projects/-Users-jeff-claudeprojects/memory/.

## What happened
`examples/dilla_sketch.py` wrote "Dilla Sketch" to the MPC's SD card, using "First Project" (MPC OS 2.10) as a template. Jeff's MPC Live II runs 2.15.1. On the hardware, the sequence title, tracks and keygroups load, but play makes no sound, on drums as well. The drum track uses the confirmed type byte, so the keygroup type guess doesn't explain the silence by itself.

## Ask Jeff first (cheap, splits the cause)
1. Does "First Project" make sound when played? Rules out the MPC's output and volume.
2. In the Grid / event view, are notes visible on the Drums track of Dilla Sketch? No notes means the note encoding is wrong. Notes but no sound means routing, mute or volume.
3. With the Dilla Kit track selected, do the pads sound when hit?

## Suspects, roughly in order
- **Note event encoding.** We write `47 61 11 00 note vel 00 00 00 40 len... ` 20-byte blocks. In the template, each track also had polytouch events at tick 0 (`note 36 val 0`, `note 37 val 0`) before the notes. We dropped all polytouch. They may be part of note storage rather than pad pressure. Compare the template's raw event order closely.
- **Sequence header.** We set bytes 4 and 8 to 4 and 5 (bars, end), inferred from 16/17 in expansion preview .sxq files. If byte 8 means something else, the loop could be zero-length.
- **Mixer or track state.** The track header has a `d` (0x64) byte, maybe volume, kept from the template. Check for mute or solo flags, and program volume in the copied expansion .xpm files.
- **The `Tflg` meta and unknown_meta 112.** Copied verbatim, but check they aren't tied to the old tracks.

## Best next experiment
Have Jeff save a tiny project on the hardware: 1 bar, one drum track, one kick note, one keygroup track with one note. Then diff our generated .sxq against it byte by byte. That also settles the keygroup track type (Ga10 byte 5, `pytT` value).

## Hygiene
- macOS writes `._` files to the card. Run `dot_clean -m` on new folders. The check tool ignores them.
- The card mounts only in Controller Mode, as `Untitled`, with the internal drive as `MPC_HDD`. Connect through the Apple USB-C adapter, not the Anker hub.
- Never write over Jeff's existing projects; only create new folders.
