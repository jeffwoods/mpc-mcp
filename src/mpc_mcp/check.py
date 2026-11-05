"""Check whether a project (usually one saved by the desktop software) will load and play on
standalone hardware.

Four checks: the saving version against the hardware's OS, files that are missing or live
outside the project folder, plugins the hardware may not have, and sample memory. Read-only.
"""

from __future__ import annotations

import re
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import project

BUILT_IN_MARKERS = ("air music", "akai", "mpc", "inmusic")


def _version(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    nums = re.findall(r"\d+", text)
    return tuple(int(n) for n in nums[:3]) if nums else None


def _fmt(v: tuple[int, ...] | None) -> str:
    return ".".join(map(str, v)) if v else "unknown"


def _result(name: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": name, "status": status, "detail": detail, **extra}


def check_version(decoded: dict[str, Any], target: tuple[int, ...]) -> dict[str, Any]:
    if decoded["format"] == "json" and decoded["container"] == "gzip":
        if target[0] < 3:
            return _result("version", "fail", f"Saved in the MPC 3 format, which OS {_fmt(target)} can't open.")
        return _result("version", "ok", "MPC 3 format.")
    if decoded["format"] != "xml":
        return _result("version", "warn", f"Unrecognised project format ({decoded['format']}); can't read the version.")
    info = decoded["data"].get("Version", {})
    saved = _version(info.get("Application_Version"))
    app = info.get("Application")
    if saved is None:
        return _result("version", "warn", "No application version in the project file.")
    if saved[0] > target[0]:
        return _result("version", "fail", f"Saved by {_fmt(saved)}; the hardware runs {_fmt(target)}.", saved=_fmt(saved))
    if saved[:2] > target[:2]:
        return _result("version", "warn",
                       f"Saved by {_fmt(saved)}, newer than the hardware's {_fmt(target)}. "
                       "It may open, but features from the newer version can be dropped.", saved=_fmt(saved))
    return _result("version", "ok", f"Saved by {app} {_fmt(saved)}; hardware runs {_fmt(target)}.", saved=_fmt(saved))


def _programs(data_dir: Path) -> list[Path]:
    """Program files, skipping macOS "._" metadata files that appear on FAT/exFAT cards."""
    return sorted(p for p in data_dir.glob("*.xpm") if not p.name.startswith("."))


def _project_data_dir(xpj: Path) -> Path:
    return xpj.with_name(f"{xpj.stem}_[ProjectData]")


def check_files(xpj: Path, decoded: dict[str, Any]) -> dict[str, Any]:
    """Every file the project lists should exist and sit inside the project folder."""
    if decoded["format"] != "xml":
        return _result("files", "warn", "Can't read the file list from this project format.")
    listed = decoded["data"].get("FileList", {}).get("File", [])
    listed = [listed] if isinstance(listed, str) else listed
    base = xpj.parent
    data_dir = _project_data_dir(xpj).resolve()
    missing, outside = [], []
    for entry in listed:
        p = Path(entry)
        resolved = (p if p.is_absolute() else base / p).resolve()
        if not resolved.is_relative_to(data_dir):
            outside.append(entry)
        elif not resolved.exists():
            missing.append(entry)
    if missing or outside:
        return _result("files", "fail",
                       f"{len(missing)} listed file(s) missing, {len(outside)} outside the project folder. "
                       "Re-save the project onto the MPC's drive so the samples get copied in.",
                       missing=missing, outside_project=outside)
    return _result("files", "ok", f"All {len(listed)} listed files are inside the project folder.")


def check_samples(xpj: Path) -> dict[str, Any]:
    """Samples named by programs should have a matching file in the project folder."""
    data_dir = _project_data_dir(xpj)
    if not data_dir.is_dir():
        return _result("samples", "fail", f"No project data folder next to the project ({data_dir.name}).")
    stems = {f.stem.lower() for f in data_dir.iterdir() if f.suffix.lower() in project.AUDIO and not f.name.startswith(".")}
    missing: dict[str, list[str]] = {}
    for xpm in _programs(data_dir):
        try:
            names = project.summarize_program(xpm).get("samples", [])
        except (ET.ParseError, UnicodeDecodeError):
            continue
        absent = [n for n in names if n.lower() not in stems]
        if absent:
            missing[xpm.name] = absent
    if missing:
        total = sum(map(len, missing.values()))
        return _result("samples", "fail",
                       f"{total} sample(s) used by programs aren't in the project folder. They may live in an "
                       "expansion or on the computer; re-save so they're copied in.", missing=missing)
    return _result("samples", "ok", "Every sample the programs use is in the project folder.")


def _plugin_records(path: Path) -> list[dict[str, str]] | None:
    """Plugin descriptors in a project or program file: any element with a FormatName child.
    Instruments carry them on <Program>; insert effects are assumed to use the same fields."""
    try:
        root = ET.fromstring(project.xml_text(path))
    except (ET.ParseError, UnicodeDecodeError):
        return None
    return [
        {
            "file": path.name,
            "name": (el.findtext("Name") or "").strip(),
            "maker": (el.findtext("ManufacturerName") or "").strip(),
            "format": (el.findtext("FormatName") or "").strip(),
            "id": (el.findtext("FileOrID") or "").strip(),
        }
        for el in root.iter()
        if el.find("FormatName") is not None
    ]


def check_plugins(xpj: Path) -> dict[str, Any]:
    """Format "MPC" is the hardware's built-in version (confirmed on OS 2.10 files). VST3 or AU
    plugins can't run on standalone 2.x. AIR/Akai ones may have a built-in equivalent."""
    data_dir = _project_data_dir(xpj)
    files = [xpj, *_programs(data_dir)] if data_dir.is_dir() else [xpj]
    records, unreadable = [], []
    for f in files:
        found = _plugin_records(f)
        if found is None:
            unreadable.append(f.name)
            continue
        records += found
        if f.name.endswith(".Plugin.xpm") and not found:
            unreadable.append(f.name)
    foreign = [r for r in records if r["format"].upper() != "MPC"]
    blocked = [r for r in foreign if not any(m in r["maker"].lower() for m in BUILT_IN_MARKERS)]
    akai_desktop = [r for r in foreign if r not in blocked]
    if blocked:
        return _result("plugins", "fail",
                       f"{len(blocked)} third-party plugin(s) won't run on the hardware, so those parts will be "
                       "silent. Swap them for built-in instruments or resample them to audio.",
                       blocked=blocked, plugins=records)
    if akai_desktop or unreadable:
        parts = []
        if akai_desktop:
            parts.append(f"{len(akai_desktop)} Akai/AIR plugin(s) loaded in desktop format; the hardware may "
                         "have a built-in version, but check them after loading")
        if unreadable:
            parts.append(f"couldn't identify the plugin in {len(unreadable)} file(s)")
        return _result("plugins", "warn", "; ".join(parts).capitalize() + ".",
                       plugins=records, unidentified=unreadable)
    if not records:
        return _result("plugins", "ok", "No plugins.")
    names = ", ".join(sorted({r["name"] for r in records}))
    return _result("plugins", "ok", f"All {len(records)} plugin(s) are built-in MPC versions: {names}.",
                   plugins=records)


def check_mix(xpj: Path) -> dict[str, Any]:
    """A soloed program silences every other track, pads included, and nothing on the main
    screens says so. First Project (OS 2.10 factory content) ships with its audio program
    muted and soloed, so any project copied from it is silent."""
    data_dir = _project_data_dir(xpj)
    soloed, muted = [], []
    for xpm in _programs(data_dir) if data_dir.is_dir() else []:
        try:
            prog = ET.fromstring(project.xml_text(xpm)).find("Program")
        except (ET.ParseError, UnicodeDecodeError):
            continue
        if prog is None:
            continue
        if (prog.findtext("Solo") or "").strip() == "True":
            soloed.append(xpm.name)
        if (prog.findtext("Mute") or "").strip() == "True":
            muted.append(xpm.name)
    if soloed:
        return _result("mix", "fail",
                       f"{len(soloed)} program(s) soloed, so everything else is silent, pads included. "
                       "Unsolo them in the Mixer, or set Solo to False in the program file.",
                       soloed=soloed, muted=muted)
    if muted:
        return _result("mix", "warn", f"{len(muted)} program(s) muted.", muted=muted)
    return _result("mix", "ok", "No programs muted or soloed.")


def _audio_bytes(path: Path) -> tuple[int, bool]:
    """Approximate uncompressed size. Returns (bytes, exact)."""
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path)) as w:
                return w.getnframes() * w.getnchannels() * w.getsampwidth(), True
        except (wave.Error, EOFError):
            pass
    return path.stat().st_size, False


def check_memory(xpj: Path, ram_gb: float) -> dict[str, Any]:
    data_dir = _project_data_dir(xpj)
    files = ([f for f in data_dir.iterdir() if f.suffix.lower() in project.AUDIO and not f.name.startswith(".")]
             if data_dir.is_dir() else [])
    total, estimated = 0, 0
    for f in files:
        size, exact = _audio_bytes(f)
        total += size
        estimated += not exact
    limit = ram_gb * 1024**3
    share = total / limit if limit else 0
    mb = total / 1024**2
    detail = f"About {mb:.1f} MB of audio" if mb < 10 else f"About {mb:.0f} MB of audio"
    detail += f", {share:.0%} of {ram_gb:g} GB sample RAM."
    if estimated:
        detail += f" {estimated} compressed or unreadable file(s) counted at file size, so the real figure is higher."
    detail += " The MPC may hold samples in a larger format than on disk; treat this as a lower bound."
    status = "fail" if share > 1 else "warn" if share > 0.75 else "ok"
    return _result("memory", status, detail, audio_mb=round(total / 1024**2, 1), samples=len(files))


def check_for_standalone(path: Path, os_version: str = "2.15", ram_gb: float = 2.0) -> dict[str, Any]:
    """ram_gb is the hardware's sample RAM. The MPC Live II has 2 GB."""
    xpj = Path(path).expanduser().resolve()
    if xpj.suffix.lower() != ".xpj":
        raise ValueError(f"expected an .xpj project file, got {xpj.name}")
    target = _version(os_version)
    if target is None:
        raise ValueError(f"can't read OS version {os_version!r}")
    decoded = project.decode(xpj)
    checks = [
        check_version(decoded, target),
        check_files(xpj, decoded),
        check_samples(xpj),
        check_plugins(xpj),
        check_mix(xpj),
        check_memory(xpj, ram_gb),
    ]
    statuses = {c["status"] for c in checks}
    verdict = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
    return {"project": str(xpj), "target": f"OS {_fmt(target)}, {ram_gb:g} GB sample RAM", "verdict": verdict, "checks": checks}
