"""Read MPC project files without assuming a format.

The .xpj format is undocumented and has changed between MPC OS versions. Community reports say
MPC 2.x wrote text (XML or JSON after a short header) and MPC 3 writes gzip-compressed JSON.
So this module detects what it's looking at, decodes what it can, and lets the caller explore
the structure by path. It never writes .xpj files.
"""

from __future__ import annotations

import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

GZIP_MAGIC = b"\x1f\x8b"
AUDIO = {".wav", ".aif", ".aiff", ".mp3", ".flac"}
MPC_TYPES = {
    ".xpj": "project",
    ".xpm": "program",
    ".xal": "arrangement or audio track data",
    ".sxq": "sequence",
    ".mid": "MIDI file",
    ".xfx": "effect preset",
    ".xmd": "MIDI program",
    ".xpn": "expansion",
}


def decode(path: Path) -> dict[str, Any]:
    """Return {"format": ..., "data": parsed or None, "text": str or None, "notes": [...]}."""
    raw = Path(path).expanduser().read_bytes()
    notes: list[str] = []
    container = "plain"
    if raw[:2] == GZIP_MAGIC:
        raw = gzip.decompress(raw)
        container = "gzip"

    text = _as_text(raw)
    if text is None:
        return {"container": container, "format": "binary", "data": None, "text": None,
                "size": len(raw), "head_hex": raw[:64].hex(" "),
                "notes": ["Not text after decompression. May be encrypted or a binary format."]}

    stripped = text.lstrip("﻿ \r\n\t")
    if stripped.startswith("<"):
        try:
            return {"container": container, "format": "xml", "data": _xml_to_dict(ET.fromstring(stripped)),
                    "text": None, "notes": notes}
        except ET.ParseError as err:
            notes.append(f"Looks like XML but did not parse: {err}")

    data, skipped = _json_after_header(stripped)
    if data is not None:
        if skipped:
            notes.append(f"Skipped {skipped} header line(s) before the JSON body.")
        return {"container": container, "format": "json", "data": data, "text": None, "notes": notes}

    return {"container": container, "format": "text", "data": None, "text": text, "notes": notes}


def _as_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(c.isprintable() or c in "\r\n\t" for c in text[:4096])
    return text if printable >= 0.95 * min(len(text), 4096) else None


def _json_after_header(text: str) -> tuple[Any, int]:
    lines = text.splitlines()
    for skipped in range(min(len(lines), 10)):
        body = "\n".join(lines[skipped:])
        if not body.lstrip().startswith(("{", "[")):
            continue
        try:
            return json.loads(body), skipped
        except json.JSONDecodeError:
            continue
    return None, 0


def _xml_to_dict(el: ET.Element) -> Any:
    children = list(el)
    if not children and not el.attrib:
        return (el.text or "").strip()
    node: dict[str, Any] = {f"@{k}": v for k, v in el.attrib.items()}
    if el.text and el.text.strip() and not children:
        node["#text"] = el.text.strip()
    for child in children:
        value = _xml_to_dict(child)
        if child.tag in node:
            if not isinstance(node[child.tag], list):
                node[child.tag] = [node[child.tag]]
            node[child.tag].append(value)
        else:
            node[child.tag] = value
    return node


def outline(data: Any, depth: int = 3, max_items: int = 8) -> Any:
    """A shape-only view: keys, list lengths, and short scalar previews. For exploring big files."""
    if isinstance(data, dict):
        if depth == 0:
            return f"{{...{len(data)} keys}}"
        shown = list(data.items())[:max_items * 4]
        out = {k: outline(v, depth - 1, max_items) for k, v in shown}
        if len(data) > len(shown):
            out["..."] = f"{len(data) - len(shown)} more keys"
        return out
    if isinstance(data, list):
        if depth == 0 or not data:
            return f"[{len(data)} items]"
        out = [outline(v, depth - 1, max_items) for v in data[:max_items]]
        if len(data) > max_items:
            out.append(f"... {len(data) - max_items} more items")
        return out
    if isinstance(data, str) and len(data) > 80:
        return data[:77] + "..."
    return data


def get_path(data: Any, path: str) -> Any:
    """Walk a dotted path like "tracks.0.events" (list indexes are numbers)."""
    node = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                raise KeyError(f"{part!r} not found. Keys here: {list(node)[:40]}")
            node = node[part]
        else:
            raise KeyError(f"can't go into {type(node).__name__} at {part!r}")
    return node


def find_keys(data: Any, needle: str, limit: int = 50) -> list[str]:
    """Paths of keys containing needle (case-insensitive). Useful for finding where sequences live."""
    hits: list[str] = []
    needle = needle.lower()

    def walk(node: Any, prefix: str) -> None:
        if len(hits) >= limit:
            return
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else []
        for k, v in items:
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(k, str) and needle in k.lower():
                hits.append(path)
            walk(v, path)

    walk(data, "")
    return hits


def scan_folder(folder: Path, max_files: int = 500) -> dict[str, Any]:
    """List MPC-related files under a folder (an SD card, USB stick, or project folder)."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(root)
    found: dict[str, list[str]] = {}
    audio = 0
    count = 0
    for p in sorted(root.rglob("*")):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        ext = p.suffix.lower()
        if ext in AUDIO:
            audio += 1
            continue
        if ext in MPC_TYPES and p.is_file():
            found.setdefault(MPC_TYPES[ext], []).append(str(p.relative_to(root)))
            count += 1
            if count >= max_files:
                break
    return {"root": str(root), "files": found, "audio_files": audio, "truncated": count >= max_files}


def summarize_program(path: Path) -> dict[str, Any]:
    """Name, type and sample list of an .xpm program. Tolerant of version differences."""
    decoded = decode(path)
    if decoded["format"] != "xml":
        return {"format": decoded["format"], "notes": decoded["notes"] + ["Expected XML for .xpm."]}
    root = ET.fromstring(_xml_text(path))
    program = root.find(".//Program")
    name = root.findtext(".//ProgramName")
    samples = sorted({s.text.strip() for s in root.iter("SampleName") if s.text and s.text.strip()})
    return {
        "name": name,
        "type": program.get("type") if program is not None else None,
        "version": root.findtext(".//Version/File_Version") or root.findtext(".//Version"),
        "samples": samples,
    }


def _xml_text(path: Path) -> str:
    raw = Path(path).expanduser().read_bytes()
    if raw[:2] == GZIP_MAGIC:
        raw = gzip.decompress(raw)
    return raw.decode("utf-8").lstrip("﻿")
