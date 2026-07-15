#!/usr/bin/env python3
"""Fail-closed extraction for small, allowlisted GitHub evidence archives."""

from __future__ import annotations

import argparse
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--expected-file", action="append", required=True)
    parser.add_argument("--max-member-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=32 * 1024 * 1024)
    return parser.parse_args()


def canonical_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or name.endswith("/")
        or path.is_absolute()
        or str(path) != name
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ValueError(f"unsafe or non-canonical zip member: {name!r}")
    return path


def main() -> int:
    args = parse_args()
    expected = args.expected_file
    if len(expected) != len(set(expected)):
        raise ValueError("expected-file entries must be unique")
    expected_paths = {name: canonical_member(name) for name in expected}
    if args.max_member_bytes < 1 or args.max_total_bytes < 1:
        raise ValueError("archive size limits must be positive")

    if args.destination.exists():
        raise FileExistsError(f"destination already exists: {args.destination}")

    with zipfile.ZipFile(args.archive, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("zip contains duplicate members")
        if set(names) != set(expected_paths):
            raise ValueError(
                f"zip member allowlist mismatch: actual={sorted(names)!r} "
                f"expected={sorted(expected_paths)!r}"
            )

        total_size = 0
        for info in infos:
            canonical_member(info.filename)
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ValueError(f"zip symlink is forbidden: {info.filename!r}")
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted zip member is forbidden: {info.filename!r}")
            if info.file_size < 0 or info.file_size > args.max_member_bytes:
                raise ValueError(f"zip member exceeds size limit: {info.filename!r}")
            total_size += info.file_size
            if total_size > args.max_total_bytes:
                raise ValueError("zip exceeds total uncompressed size limit")

        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise ValueError(f"zip CRC validation failed: {corrupt_member!r}")

        args.destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".extract-exact-", dir=args.destination.parent
        ) as staging_raw:
            staging = Path(staging_raw)
            for info in infos:
                target = staging.joinpath(*expected_paths[info.filename].parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = archive.read(info)
                if len(payload) != info.file_size:
                    raise ValueError(f"zip member size mismatch: {info.filename!r}")
                target.write_bytes(payload)
            staging.replace(args.destination)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
