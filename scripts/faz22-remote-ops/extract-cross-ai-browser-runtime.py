#!/usr/bin/env python3
"""Verify and safely extract the signed browser runtime bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEMBERS = 200_000
RUNTIME_ROOT = PurePosixPath("browser-runtime")
MANIFEST = RUNTIME_ROOT / "runtime-manifest.json"
PACKAGE_JSON = RUNTIME_ROOT / "package.json"
PLAYWRIGHT_PACKAGE_JSON = RUNTIME_ROOT / "node_modules/playwright/package.json"
CHROMIUM_MARKER = RUNTIME_ROOT / "ms-playwright"
DIGEST_PREFIX = "sha256:"


class RuntimeBundleError(ValueError):
    """The runtime archive is not the exact safe bundle selected by evidence."""


def _digest_file(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return f"{DIGEST_PREFIX}{digest.hexdigest()}"


def _validated_name(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.parts[0] != RUNTIME_ROOT.name
    ):
        raise RuntimeBundleError("runtime archive contains an unsafe path")
    return path


def _mkdir_private(path: Path) -> None:
    path.mkdir(mode=0o700)


def _extract_regular(
    member: tarfile.TarInfo, source: tarfile.TarFile, target: Path
) -> None:
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stream = source.extractfile(member)
    if stream is None:
        raise RuntimeBundleError("runtime archive member has no bytes")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    mode = 0o700 if member.mode & 0o111 else 0o600
    descriptor = os.open(target, flags, mode)
    try:
        remaining = member.size
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeBundleError("runtime archive member is truncated")
            view = memoryview(chunk)
            while view:
                written = os.write(descriptor, view)
                if written < 1:
                    raise RuntimeBundleError("runtime archive member cannot be written")
                view = view[written:]
            remaining -= len(chunk)
        if stream.read(1):
            raise RuntimeBundleError("runtime archive member exceeds declared size")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
        stream.close()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeBundleError(
            "runtime manifest or package metadata is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeBundleError(
            "runtime manifest or package metadata is not an object"
        )
    return value


def extract_runtime(archive: Path, expected_digest: str, output: Path) -> None:
    if (
        len(expected_digest) != 71
        or not expected_digest.startswith(DIGEST_PREFIX)
        or any(character not in "0123456789abcdef" for character in expected_digest[7:])
    ):
        raise RuntimeBundleError("expected runtime digest is invalid")
    if output.exists() or output.is_symlink():
        raise RuntimeBundleError("runtime output must not already exist")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(archive, flags)
    except OSError as exc:
        raise RuntimeBundleError("runtime archive is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 1 <= metadata.st_size <= MAX_ARCHIVE_BYTES
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RuntimeBundleError("runtime archive metadata is unsafe")
        if _digest_file(descriptor) != expected_digest:
            raise RuntimeBundleError(
                "runtime archive digest differs from signed evidence"
            )
        with os.fdopen(os.dup(descriptor), "rb", closefd=True) as stream:
            with tarfile.open(fileobj=stream, mode="r:*") as bundle:
                members = bundle.getmembers()
                if not 1 <= len(members) <= MAX_MEMBERS:
                    raise RuntimeBundleError("runtime archive member count is invalid")
                names: set[PurePosixPath] = set()
                expanded = 0
                normalized: list[tuple[PurePosixPath, tarfile.TarInfo]] = []
                for member in members:
                    name = _validated_name(member.name)
                    if name in names:
                        raise RuntimeBundleError(
                            "runtime archive contains duplicate paths"
                        )
                    names.add(name)
                    if not (member.isdir() or member.isreg()):
                        raise RuntimeBundleError(
                            "runtime archive contains links or special files"
                        )
                    if member.uid != 0 or member.gid != 0:
                        raise RuntimeBundleError(
                            "runtime archive ownership is not normalized"
                        )
                    if member.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
                        raise RuntimeBundleError("runtime archive mode is unsafe")
                    expanded += member.size
                    if expanded > MAX_EXPANDED_BYTES:
                        raise RuntimeBundleError(
                            "runtime archive expands beyond its bound"
                        )
                    normalized.append((name, member))
                required = {MANIFEST, PACKAGE_JSON, PLAYWRIGHT_PACKAGE_JSON}
                if not required.issubset(names) or not any(
                    name.parts[:2] == CHROMIUM_MARKER.parts and member.isreg()
                    for name, member in normalized
                ):
                    raise RuntimeBundleError("runtime archive is incomplete")
                _mkdir_private(output)
                for name, member in sorted(
                    normalized, key=lambda item: (len(item[0].parts), str(item[0]))
                ):
                    target = output.joinpath(*name.parts)
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    else:
                        _extract_regular(member, bundle, target)
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeBundleError("runtime archive cannot be safely extracted") from exc
    finally:
        os.close(descriptor)

    manifest = _load_json(output.joinpath(*MANIFEST.parts))
    package = _load_json(output.joinpath(*PACKAGE_JSON.parts))
    playwright = _load_json(output.joinpath(*PLAYWRIGHT_PACKAGE_JSON.parts))
    expected_manifest = {
        "schemaVersion": "acik.cross-ai-browser-runtime.v1",
        "playwrightVersion": "1.60.0",
        "packageRoot": "browser-runtime",
        "browsersPath": "browser-runtime/ms-playwright",
    }
    if manifest != expected_manifest:
        raise RuntimeBundleError("runtime manifest differs from the pinned profile")
    if package.get("private") is not True or playwright.get("version") != "1.60.0":
        raise RuntimeBundleError("runtime Playwright package identity is invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        extract_runtime(args.archive, args.expected_sha256, args.output_dir)
    except RuntimeBundleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
