import wave
import xml.etree.ElementTree as ET

import pytest

from mpc_mcp import program
from mpc_mcp.program import Pad, pads_from_program, wav_frames, write_drum_program


def _wav(path, frames=1000, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(width)
        w.setframerate(44100)
        w.writeframes(b"\0" * frames * 2 * width)
    return path


def _instruments(xpm):
    root = ET.parse(xpm).getroot()
    notes = {int(p.get("number")): int(p.findtext("Note")) for p in root.iter("PadNote")}
    out = {}
    for ins in root.iter("Instrument"):
        layer = ins.find("Layers/Layer")
        if layer.findtext("SampleName"):
            out[notes[int(ins.get("number"))]] = (layer.findtext("SampleName"), int(layer.findtext("SliceEnd")),
                                                  int(ins.findtext("MuteGroup")))
    return root, out


def test_blank_is_a_full_215_program():
    root = ET.fromstring(program.blank_drum())
    assert root.findtext("Version/Application_Version") == "2.15.1.1"
    assert len(root.findall("Program/Instruments/Instrument")) == 128
    notes = sorted(int(p.findtext("Note")) for p in root.iter("PadNote"))
    assert notes == list(range(128))


def test_wav_frames(tmp_path):
    assert wav_frames(_wav(tmp_path / "a.wav", 6947, width=3)) == 6947
    (tmp_path / "b.aif").write_bytes(b"FORM....AIFF")
    with pytest.raises(ValueError):
        wav_frames(tmp_path / "b.aif")


def test_build_drum_program(tmp_path):
    src, out = tmp_path / "src", tmp_path / "Song_[ProjectData]"
    src.mkdir(), out.mkdir()
    kick = _wav(src / "Kick.WAV", 500)
    hat = _wav(src / "Hat & Co.WAV", 200)
    files = write_drum_program(out, "My Kit", {36: Pad(kick), 42: Pad(hat, mute_group=1), 44: Pad(hat, mute_group=1)})
    assert files == ["My Kit.Drum.xpm", "Kick.WAV", "Hat & Co.WAV"]
    root, pads = _instruments(out / "My Kit.Drum.xpm")
    assert root.findtext("Program/ProgramName") == "My Kit"
    assert root.findtext("Program/Solo") == "False"
    assert pads == {36: ("Kick", 499, 0), 42: ("Hat & Co", 199, 1), 44: ("Hat & Co", 199, 1)}
    with pytest.raises(FileExistsError):
        write_drum_program(out, "My Kit", {36: Pad(kick)})


def test_name_clash_gets_new_name(tmp_path):
    a, b, out = tmp_path / "a", tmp_path / "b", tmp_path / "out"
    a.mkdir(), b.mkdir(), out.mkdir()
    files = write_drum_program(out, "Kit", {36: Pad(_wav(a / "Kick.wav", 100)), 37: Pad(_wav(b / "Kick.wav", 300))})
    assert files == ["Kit.Drum.xpm", "Kick.wav", "Kick 2.wav"]
    _, pads = _instruments(out / "Kit.Drum.xpm")
    assert pads[36][0] == "Kick" and pads[37] == ("Kick 2", 299, 0)


def test_round_trip_through_pads_from_program(tmp_path):
    src, out, again = tmp_path / "src", tmp_path / "out", tmp_path / "again"
    for d in (src, out, again):
        d.mkdir()
    write_drum_program(out, "Kit", {36: Pad(_wav(src / "K.wav")), 46: Pad(_wav(src / "OH.wav"), mute_group=2, tune=-3)})
    pads = pads_from_program(out / "Kit.Drum.xpm")
    assert {n: (p.sample.name, p.mute_group, p.tune) for n, p in pads.items()} == {36: ("K.wav", 0, 0), 46: ("OH.wav", 2, -3)}
    write_drum_program(again, "Kit", pads)
    assert _instruments(again / "Kit.Drum.xpm")[1] == _instruments(out / "Kit.Drum.xpm")[1]
