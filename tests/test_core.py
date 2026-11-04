import gzip
import json
import time

import mido
import pytest

from mpc_mcp import midifile, project
from mpc_mcp.midi_io import MidiRig
from mpc_mcp.notes import NoteEvent, note_name, parse_note
from mpc_mcp.schedule import build_schedule, messages_to_events


def test_note_names():
    assert parse_note("C4") == 60
    assert parse_note("F#3") == 54
    assert parse_note("Bb2") == 46
    assert parse_note("C-1") == 0
    assert parse_note("72") == 72
    assert note_name(61) == "C#4"
    with pytest.raises(ValueError):
        parse_note("H2")
    with pytest.raises(ValueError):
        parse_note(128)


def test_schedule_orders_off_before_retrigger():
    events = [NoteEvent(note=36, start=0, length=1), NoteEvent(note=36, start=1, length=1)]
    sched = build_schedule(events, bpm=120)
    at_half_second = [t.message.type for t in sched if t.seconds == 0.5]
    assert at_half_second == ["note_off", "note_on"]
    assert sched[-1].seconds == 1.0


def test_schedule_loops_and_clock():
    events = [NoteEvent(note="C2", start=0, length=0.5)]
    sched = build_schedule(events, bpm=60, loops=2, loop_beats=4, send_clock=True)
    ons = [t.seconds for t in sched if t.message.type == "note_on"]
    assert ons == [0.0, 4.0]
    assert sum(t.message.type == "clock" for t in sched) == 8 * 24
    assert sched[0].message.type == "start"
    assert sched[-1].message.type == "stop"


def test_recording_pairs_notes():
    stamped = [
        (0.0, mido.Message("note_on", note=60, velocity=90)),
        (0.25, mido.Message("note_on", note=60, velocity=0)),
        (0.5, mido.Message("note_on", note=64, velocity=80)),
    ]
    events = messages_to_events(stamped, bpm=120)
    assert [(e.note, e.start, e.length) for e in events] == [(60, 0.0, 0.5), (64, 1.0, 0.001)]


def test_midi_file_round_trip(tmp_path):
    parts = {
        "bass": [NoteEvent(note="E1", start=0, length=1.5, velocity=110), NoteEvent(note="G1", start=2, length=0.5)],
        "keys": [NoteEvent(note="C4", start=0, length=4, channel=2)],
    }
    path = midifile.write_midi(tmp_path / "out" / "song.mid", parts, bpm=87)
    back = midifile.read_midi(path)
    assert back["bpm"] == 87
    assert [(e["note"], e["start"], e["length"]) for e in back["tracks"]["bass"]] == [(28, 0, 1.5), (31, 2, 0.5)]
    assert back["tracks"]["keys"][0]["channel"] == 2


def test_decode_gzip_json(tmp_path):
    body = {"data": {"tracks": [{"name": "Kick", "events": [{"note": 36}] * 20}]}}
    path = tmp_path / "song.xpj"
    path.write_bytes(gzip.compress(json.dumps(body).encode()))
    d = project.decode(path)
    assert (d["container"], d["format"]) == ("gzip", "json")
    assert project.get_path(d["data"], "data.tracks.0.name") == "Kick"
    assert project.find_keys(d["data"], "event") == ["data.tracks.0.events"]
    assert project.outline(d["data"], depth=5)["data"]["tracks"][0]["events"][-1] == "... 12 more items"


def test_decode_json_after_header(tmp_path):
    path = tmp_path / "old.xpj"
    path.write_text("ACVS\n2.1\n" + json.dumps({"version": 2}))
    d = project.decode(path)
    assert d["format"] == "json" and d["data"] == {"version": 2}
    assert "Skipped 2 header" in d["notes"][0]


def test_decode_binary(tmp_path):
    path = tmp_path / "enc.xpj"
    path.write_bytes(bytes(range(256)) * 4)
    assert project.decode(path)["format"] == "binary"


def test_program_summary(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<MPCVObject><Version><File_Version>2.1</File_Version></Version>
<Program type="Drum"><ProgramName>Dusty Kit</ProgramName><Instruments>
<Instrument number="1"><Layers><Layer number="1"><SampleName>Kick 01</SampleName></Layer>
<Layer number="2"><SampleName></SampleName></Layer></Layers></Instrument>
<Instrument number="2"><Layers><Layer number="1"><SampleName>Snare 03</SampleName></Layer></Layers></Instrument>
</Instruments></Program></MPCVObject>"""
    path = tmp_path / "kit.xpm"
    path.write_text(xml)
    s = project.summarize_program(path)
    assert s == {"name": "Dusty Kit", "type": "Drum", "version": "2.1", "samples": ["Kick 01", "Snare 03"]}


def test_scan_folder(tmp_path):
    (tmp_path / "Beat_[ProjectData]").mkdir()
    (tmp_path / "Beat.xpj").write_text("{}")
    (tmp_path / "Beat_[ProjectData]" / "Kit.xpm").write_text("<x/>")
    (tmp_path / "Beat_[ProjectData]" / "kick.wav").write_bytes(b"RIFF")
    (tmp_path / ".hidden.xpj").write_text("{}")
    s = project.scan_folder(tmp_path)
    assert s["files"] == {"project": ["Beat.xpj"], "program": ["Beat_[ProjectData]/Kit.xpm"]}
    assert s["audio_files"] == 1


def test_live_loopback():
    """Play through a virtual port and record it back, end to end through real CoreMIDI."""
    rig = MidiRig()
    loop_name = "mpc-mcp-loop"
    try:
        listener = mido.open_input(loop_name, virtual=True)
    except (OSError, NotImplementedError) as err:
        pytest.skip(f"virtual MIDI ports unavailable: {err}")
    with listener:
        time.sleep(0.2)
        events = [NoteEvent(note=n, start=i * 0.5, length=0.25) for i, n in enumerate([36, 38, 42])]
        rig.play(loop_name, build_schedule(events, bpm=240))
        time.sleep(0.8)
        got = [m for m in listener.iter_pending() if m.type == "note_on"]
    rig.close()
    assert [m.note for m in got] == [36, 38, 42]
