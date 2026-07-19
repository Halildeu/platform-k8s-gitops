"""Owner-only bounded inputs and create-once canonical evidence outputs."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes
from .errors import reject
from .jsonutil import loads_json_bytes


def read_private_bytes(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        reject("PRIVATE_INPUT_INVALID", f"{label} cannot be opened safely")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 1 <= before.st_size <= maximum
        ):
            reject(
                "PRIVATE_INPUT_INVALID",
                f"{label} must be an owner-only bounded regular file",
            )
        chunks: list[bytes] = []
        observed = 0
        while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1)):
            chunks.append(chunk)
            observed += len(chunk)
            if observed > maximum:
                reject("PRIVATE_INPUT_INVALID", f"{label} exceeds its size limit")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or observed != before.st_size
        ):
            reject("PRIVATE_INPUT_CHANGED", f"{label} changed while being read")
        return b"".join(chunks)
    except OSError:
        reject("PRIVATE_INPUT_INVALID", f"{label} cannot be read safely")
    finally:
        os.close(descriptor)


def load_private_json(
    path: Path,
    *,
    label: str,
    maximum: int = 4 * 1024 * 1024,
) -> dict[str, Any]:
    return loads_json_bytes(
        read_private_bytes(path, label=label, maximum=maximum),
        max_bytes=maximum,
        label=label,
    )


def read_private_text(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> str:
    raw = read_private_bytes(path, label=label, maximum=maximum)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        reject("PRIVATE_INPUT_INVALID", f"{label} must be UTF-8")
    if not value.strip():
        reject("PRIVATE_INPUT_INVALID", f"{label} must not be blank")
    return value


def write_private_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        reject("PRIVATE_OUTPUT_INVALID", "evidence output must be a new file")
    raw = canonical_bytes(value)
    try:
        written = 0
        while written < len(raw):
            size = os.write(descriptor, raw[written:])
            if size <= 0:
                reject("PRIVATE_OUTPUT_INVALID", "evidence output write was incomplete")
            written += size
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size != len(raw)
        ):
            reject("PRIVATE_OUTPUT_INVALID", "evidence output is not owner-only")
    except OSError:
        reject("PRIVATE_OUTPUT_INVALID", "evidence output cannot be written safely")
    finally:
        os.close(descriptor)


__all__ = [
    "load_private_json",
    "read_private_bytes",
    "read_private_text",
    "write_private_json_exclusive",
]
