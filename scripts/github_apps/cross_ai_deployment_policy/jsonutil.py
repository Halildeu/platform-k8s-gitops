"""Bounded duplicate-safe JSON configuration loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import reject


def _mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            reject("JSON_DUPLICATE_KEY", f"duplicate JSON key {key}")
        value[key] = item
    return value


def _reject_float(_value: str) -> None:
    reject("JSON_FLOAT_FORBIDDEN", "configuration JSON must not contain floats")


def loads_json_bytes(
    raw: bytes,
    *,
    max_bytes: int = 4 * 1024 * 1024,
    label: str = "JSON",
) -> dict[str, Any]:
    if not raw or len(raw) > max_bytes:
        reject("JSON_FILE_SIZE_INVALID", f"{label} size is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_mapping,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except UnicodeDecodeError:
        reject("JSON_FILE_INVALID", f"{label} is not UTF-8")
    except json.JSONDecodeError:
        reject("JSON_FILE_INVALID", f"{label} is not valid JSON")
    if not isinstance(value, dict):
        reject("JSON_FILE_INVALID", f"{label} must be an object")
    return value


def load_json_file(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        reject("JSON_FILE_UNAVAILABLE", "configuration file cannot be read")
    return loads_json_bytes(raw, max_bytes=max_bytes, label="configuration JSON")


__all__ = ["load_json_file", "loads_json_bytes"]
