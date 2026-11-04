import gzip
import json
import struct
import wave

from mpc_mcp.check import check_for_standalone

XPJ = """<?xml version="1.0" encoding="UTF-8"?>
<Project><Version><File_Version>2.1</File_Version><Application>MPC-V</Application>
<Application_Version>{version}</Application_Version><Platform>MacOSX</Platform></Version>
<BPM>90.000000</BPM><FileList>{files}</FileList></Project>"""

DRUM = """<?xml version="1.0" encoding="UTF-8"?>
<MPCVObject><Version><File_Version>2.1</File_Version></Version><Program type="Drum">
<ProgramName>Kit</ProgramName><Instruments><Instrument number="1"><Layers>
{layers}</Layers></Instrument></Instruments></Program></MPCVObject>"""

PLUGIN = """<?xml version="1.0" encoding="UTF-8"?>
<MPCVObject><Program type="Plugin"><ProgramName>Synth</ProgramName>
<Name>{name}</Name><DescriptiveName>{name}</DescriptiveName><FormatName>{fmt}</FormatName>
<ManufacturerName>{maker}</ManufacturerName><FileOrID>{fmt}:{name}</FileOrID></Program></MPCVObject>"""


def _wav(path, frames=1000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(struct.pack("<h", 0) * frames * 2)


def make_project(tmp_path, version="2.15.1.10", samples=("Kick",), extra_layers=(), files_extra=(),
                 plugin=None):
    data = tmp_path / "Song_[ProjectData]"
    data.mkdir()
    listed = []
    for name in samples:
        _wav(data / f"{name}.WAV")
        listed.append(f"./Song_[ProjectData]/{name}.WAV")
    layers = "".join(f"<Layer><SampleName>{n}</SampleName></Layer>" for n in (*samples, *extra_layers))
    (data / "Kit.Drum.xpm").write_text(DRUM.format(layers=layers))
    listed.append("./Song_[ProjectData]/Kit.Drum.xpm")
    if plugin:
        name, maker, fmt = plugin
        (data / "Synth.Plugin.xpm").write_text(PLUGIN.format(name=name, maker=maker, fmt=fmt))
    listed += files_extra
    xpj = tmp_path / "Song.xpj"
    xpj.write_text(XPJ.format(version=version, files="".join(f"<File>{f}</File>" for f in listed)))
    return xpj


def by_name(result):
    return {c["check"]: c for c in result["checks"]}


def test_clean_project_passes(tmp_path):
    r = check_for_standalone(make_project(tmp_path), os_version="2.15.1")
    assert r["verdict"] == "ok", r
    assert by_name(r)["memory"]["samples"] == 1


def test_newer_major_version_fails(tmp_path):
    r = check_for_standalone(make_project(tmp_path, version="3.10.0.5"), os_version="2.15.1")
    assert by_name(r)["version"]["status"] == "fail"
    assert r["verdict"] == "fail"


def test_newer_minor_version_warns(tmp_path):
    r = check_for_standalone(make_project(tmp_path, version="2.16.0.1"), os_version="2.15.1")
    assert by_name(r)["version"]["status"] == "warn"


def test_mpc3_gzip_format_fails_on_2x(tmp_path):
    xpj = make_project(tmp_path)
    xpj.write_bytes(gzip.compress(json.dumps({"tracks": []}).encode()))
    assert by_name(check_for_standalone(xpj, os_version="2.15"))["version"]["status"] == "fail"


def test_sample_outside_project_fails(tmp_path):
    xpj = make_project(tmp_path, files_extra=("/Users/someone/Samples/Snare.wav", "./Song_[ProjectData]/Gone.wav"))
    files = by_name(check_for_standalone(xpj))["files"]
    assert files["status"] == "fail"
    assert files["outside_project"] == ["/Users/someone/Samples/Snare.wav"]
    assert files["missing"] == ["./Song_[ProjectData]/Gone.wav"]


def test_program_sample_not_in_folder_fails(tmp_path):
    xpj = make_project(tmp_path, extra_layers=("Expansion Snare",))
    samples = by_name(check_for_standalone(xpj))["samples"]
    assert samples["status"] == "fail"
    assert samples["missing"] == {"Kit.Drum.xpm": ["Expansion Snare"]}


def test_third_party_plugin_fails(tmp_path):
    xpj = make_project(tmp_path, plugin=("Serum", "Xfer Records", "VST3"))
    plugins = by_name(check_for_standalone(xpj))["plugins"]
    assert plugins["status"] == "fail"
    assert [b["name"] for b in plugins["blocked"]] == ["Serum"]


def test_akai_plugin_in_desktop_format_warns(tmp_path):
    xpj = make_project(tmp_path, plugin=("Hype", "AIR Music Technology", "VST3"))
    assert by_name(check_for_standalone(xpj))["plugins"]["status"] == "warn"


def test_builtin_plugin_ok(tmp_path):
    xpj = make_project(tmp_path, plugin=("TubeSynth", "AIR Music Technology", "MPC"))
    plugins = by_name(check_for_standalone(xpj))["plugins"]
    assert plugins["status"] == "ok" and "TubeSynth" in plugins["detail"]


def test_unidentifiable_plugin_program_warns(tmp_path):
    xpj = make_project(tmp_path)
    (tmp_path / "Song_[ProjectData]" / "Odd.Plugin.xpm").write_text("<MPCVObject><Program/></MPCVObject>")
    plugins = by_name(check_for_standalone(xpj))["plugins"]
    assert plugins["status"] == "warn" and plugins["unidentified"] == ["Odd.Plugin.xpm"]


def test_memory_over_limit_fails(tmp_path):
    xpj = make_project(tmp_path)
    r = check_for_standalone(xpj, ram_gb=0.000001)
    assert by_name(r)["memory"]["status"] == "fail"


def test_ignores_macos_metadata_files(tmp_path):
    xpj = make_project(tmp_path)
    (tmp_path / "Song_[ProjectData]" / "._Kit.Drum.xpm").write_bytes(b"\x00\x05\x16\x07binary")
    (tmp_path / "Song_[ProjectData]" / "._Kick.WAV").write_bytes(b"\x00\x05\x16\x07")
    assert check_for_standalone(xpj)["verdict"] == "ok"
