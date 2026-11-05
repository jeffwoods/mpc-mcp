import wave
from pathlib import Path

import mido
import pytest

from mpc_mcp import sequence, song
from mpc_mcp.program import Pad, Zone

XPJ = """<?xml version="1.0" encoding="UTF-8"?>
<MPCVObject><Project><BPM>120.000000</BPM><MasterTempo.Value>120.000000</MasterTempo.Value>
  <FileList>
    <File>./T_[ProjectData]/old.xpm</File>
  </FileList></Project></MPCVObject>"""
XAL = "<MPCVObject><Sequences><Sequence number=\"1\"><Name>My 1st sequence</Name></Sequence></Sequences></MPCVObject>"
HEADER = (bytes.fromhex("47 61 10 02 00 00 00 09") + b"All Ports\x00"
          + bytes.fromhex("07 00 64 00 00 00 00 00 10 7f 40") + bytes([6]) + b"Kit 01")


def _wav(path: Path, frames: int = 64) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100)
        w.writeframes(b"\x00\x00" * frames)
    return path


def _template(tmp_path: Path) -> Path:
    data = tmp_path / "T_[ProjectData]"
    data.mkdir()
    (tmp_path / "T.xpj").write_text(XPJ)
    (data / "All Sequences & Songs.xal").write_text(XAL)
    (data / "Audio 001.Audio.xpm").write_text("<Program><Mute>True</Mute><Solo>True</Solo></Program>")
    mid = mido.MidiFile(type=1, ticks_per_beat=960)
    mid.tracks.append(mido.MidiTrack([mido.MetaMessage("track_name", name="My 1st sequence\x00"),
                                      mido.MetaMessage("set_tempo", tempo=500000),
                                      mido.MetaMessage("sequencer_specific", data=[0x47, 0x61, 0, 0, 2, 0, 1, 0, 3, 0])]))
    mid.tracks.append(mido.MidiTrack([mido.MetaMessage("track_name", name="Drums\x00"),
                                      mido.MetaMessage("sequencer_specific", data=list(HEADER)),
                                      mido.MetaMessage("sequencer_specific", data=list(sequence.encode_note(36, 100, 240)))]))
    mid.save(data / "1.sxq")
    return tmp_path / "T.xpj"


def test_write_project(tmp_path):
    template = _template(tmp_path)
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir(), out.mkdir()
    tracks = [
        song.Track("Drums", "Kit", [song.Note(0, 36, 110, 0.25), song.Note(1, 38, 100, 0.25)], pads={36: Pad(_wav(src / "Kick.wav")), 38: Pad(_wav(src / "Snare.wav"))}),
        song.Track("Bass", "Bass", [song.Note(0.5, 40, 90, 1)], zones=[Zone(_wav(src / "B.wav"), 40)]),
        song.Track("Bass 2", "Bass", [song.Note(2, 47, 90, 1)]),
        song.Track("Empty", "Lead", [], zones=[Zone(_wav(src / "L.wav"), 60)]),
    ]
    xpj = song.write_project(template, out, "Song", tracks, bpm=95, bars=8)
    data = out / "Song_[ProjectData]"
    assert "<BPM>95.000000</BPM>" in xpj.read_text() and "old.xpm" not in xpj.read_text()
    assert "./Song_[ProjectData]/Kit.Drum.xpm" in xpj.read_text()
    assert "<Mute>False</Mute><Solo>False</Solo>" in (data / "Audio 001.Audio.xpm").read_text()
    assert "<Name>Song</Name>" in (data / "All Sequences & Songs.xal").read_text()

    seq = sequence.read_sequence(data / "1.sxq")
    assert seq["bpm"] == 95
    got = [(t["name"], t["type"], t["program"], [(n["note"], n["start"]) for n in t["notes"]], t.get("muted")) for t in seq["tracks"]]
    assert got == [("Drums", "Drum", "Kit", [(36, 0), (38, 1)], None), ("Bass", "Keygroup", "Bass", [(40, 0.5)], None),
                   ("Bass 2", "Keygroup", "Bass", [(47, 2)], None), ("Empty", "Keygroup", "Lead", [], None)]
    mid = mido.MidiFile(data / "1.sxq")
    bars = [m for m in mid.tracks[0] if m.type == "sequencer_specific"][0].data
    assert (bars[4], bars[8]) == (8, 9)
    listed = [bytes(t[0].data[5:-2]).decode() for t in mid.tracks[5:]]
    assert listed == ["Kit", "Bass", "Lead", "Audio 001"]

    with pytest.raises(FileExistsError):
        song.write_project(template, out, "Song", tracks, bpm=95, bars=8)
