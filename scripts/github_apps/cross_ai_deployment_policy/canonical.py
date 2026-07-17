"""Restricted RFC 8785 JSON Canonicalization Scheme implementation.

The deployment evidence schemas intentionally forbid binary floating-point
numbers. Integers are limited to the interoperable IEEE-754 safe range. This
lets the implementation provide deterministic JCS bytes without inheriting a
runtime-specific float serializer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import reject


MAX_SAFE_INTEGER = (1 << 53) - 1


def _validate_string(value: str, path: str) -> None:
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            reject("JCS_INVALID_STRING", f"{path} contains an unpaired surrogate")


def _key_sort_value(value: str) -> bytes:
    # RFC 8785 sorts object property names by UTF-16 code units.
    return value.encode("utf-16-be")


def _render(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            reject("JCS_UNSAFE_INTEGER", f"{path} exceeds the interoperable integer range")
        return str(value)
    if isinstance(value, float):
        reject("JCS_FLOAT_FORBIDDEN", f"{path} must not contain a floating-point number")
    if isinstance(value, str):
        _validate_string(value, path)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(
            _render(item, f"{path}[{index}]") for index, item in enumerate(value)
        ) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                reject("JCS_NON_STRING_KEY", f"{path} contains a non-string object key")
            _validate_string(key, f"{path}.<key>")
        parts: list[str] = []
        for key in sorted(value, key=_key_sort_value):
            rendered_key = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            parts.append(f"{rendered_key}:{_render(value[key], f'{path}.{key}')}")
        return "{" + ",".join(parts) + "}"
    reject("JCS_UNSUPPORTED_TYPE", f"{path} has unsupported type {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 bytes for the restricted JCS profile."""

    return _render(value, "$").encode("utf-8")


def sha256_digest(value: Any) -> str:
    """Return a domain-neutral content digest of canonical JSON."""

    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"
