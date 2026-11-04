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
PLUGIN_TAG = re.compile(r"plugin|vst|\bau\b|manufacturer|vendor", re.I)


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
    stems = {f.stem.lower() for f in data_dir.iterdir() if f.suffix.lower() in project.AUDIO}
    missing: dict[str, list[str]] = {}
    for xpm in sorted(data_dir.glob("*.xpm")):
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


def _plugin_strings(path: Path) -> set[str]:
    try:
        root = ET.fromstring(project.xml_text(path))
    except (ET.ParseError, UnicodeDecodeError):
        return set()
    found = set()
    for el in root.iter():
        if PLUGIN_TAG.search(el.tag) and el.text and el.text.strip() and len(el.text.strip()) < 120:
            found.add(el.text.strip())
        for k, v in el.attrib.items():
            if PLUGIN_TAG.search(k) and v.strip():
                found.add(v.strip())
    return found


def check_plugins(xpj: Path) -> dict[str, Any]:
    """Flag plugin programs whose identifiers don't look like Akai's built-in instruments.

    The plugin fields in .xpm files haven't been mapped yet, so this reports what it finds and
    warns rather than fails."""
    data_dir = _project_data_dir(xpj)
    programs = sorted(data_dir.glob("*.Plugin.xpm")) if data_dir.is_dir() else []
    if not programs:
        return _result("plugins", "ok", "No plugin programs.")
    report, suspicious = {}, []
    for xpm in programs:
        strings = sorted(_plugin_strings(xpm))
        report[xpm.name] = strings
        if strings and not any(m in s.lower() for s in strings for m in BUILT_IN_MARKERS):
            suspicious.append(xpm.name)
    if suspicious:
        return _result("plugins", "warn",
                       f"{len(suspicious)} plugin program(s) don't look like Akai built-ins and may be silent "
                       "on the hardware.", programs=report, suspicious=suspicious)
    return _result("plugins", "ok" if all(report.values()) else "warn",
                   f"{len(programs)} plugin program(s); identifiers look like Akai built-ins."
                   if all(report.values()) else
                   f"{len(programs)} plugin program(s); couldn't find plugin identifiers to check.",
                   programs=report)


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
    files = [f for f in data_dir.iterdir() if f.suffix.lower() in project.AUDIO] if data_dir.is_dir() else []
    total, estimated = 0, 0
    for f in files:
        size, exact = _audio_bytes(f)
        total += size
        estimated += not exact
    limit = ram_gb * 1024**3
    share = total / limit if limit else 0
    detail = f"About {total / 1024**2:.0f} MB of audio, {share:.0%} of {ram_gb:g} GB sample RAM."
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
        check_memory(xpj, ram_gb),
    ]
    statuses = {c["status"] for c in checks}
    verdict = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
    return {"project": str(xpj), "target": f"OS {_fmt(target)}, {ram_gb:g} GB sample RAM", "verdict": verdict, "checks": checks}
