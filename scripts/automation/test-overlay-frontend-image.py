#!/usr/bin/env python3
"""Inspect or atomically update the testai frontend image pin.

The test overlay contains a very large, comment-heavy provenance ledger.  This
tool deliberately edits only the canonical frontend entry's ``newTag`` and
``digest`` fields instead of reserializing the YAML document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KUSTOMIZATION = "kustomize/overlays/test/kustomization.yaml"
CANONICAL_IMAGE = "ghcr.io/halildeu/platform-web-frontend-testai"

ENTRY_RE = re.compile(r"^(?P<indent>[ \t]*)-[ \t]+name:[ \t]*(?P<name>\S+)[ \t]*$")
FIELD_RE = re.compile(
    r"^(?P<indent>[ \t]+)(?P<key>newName|newTag|digest):[ \t]*(?P<value>\S+)[ \t]*$"
)
FULL_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
SHORT_SHA_RE = re.compile(r"^[a-f0-9]{7}$")
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
TAG_RE = re.compile(r"^sha-[a-f0-9]{7}$")
SOURCE_REVISION_RE = re.compile(
    r"^(?P<indent>[ \t]+)#[ \t]+sourceRevision:[ \t]*(?P<sha>[a-f0-9]{40})[ \t]*$"
)
FRONTEND_PATCH_RE = re.compile(
    r"^[ \t]*-[ \t]+target:[ \t]*\n"
    r"[ \t]+kind:[ \t]*Deployment[ \t]*\n"
    r"[ \t]+name:[ \t]*frontend[ \t]*\n"
    r"[ \t]+patch:[ \t]*\|-[ \t]*\n"
    r"(?P<body>.*?)(?=^[ \t]*-[ \t]+target:|\Z)",
    re.MULTILINE | re.DOTALL,
)


class ContractError(ValueError):
    """The overlay or requested image violates the narrow frontend contract."""


@dataclass(frozen=True)
class FrontendPin:
    image: str
    source_sha: str | None
    tag: str | None
    digest: str
    entry_start: int
    entry_end: int
    field_indent: str
    tag_line: int | None
    source_line: int | None
    digest_line: int

    def as_dict(self) -> dict[str, str | None]:
        return {
            "image": self.image,
            "source_sha": self.source_sha,
            "tag": self.tag,
            "digest": self.digest,
        }


def _single(
    values: list[tuple[int, str, str]], key: str
) -> tuple[int, str, str] | None:
    if len(values) > 1:
        raise ContractError(f"frontend entry has duplicate {key} fields")
    return values[0] if values else None


def inspect_lines(lines: list[str]) -> FrontendPin:
    entries: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = ENTRY_RE.match(line.rstrip("\r\n"))
        if match and match.group("name") == "frontend":
            entries.append((index, len(match.group("indent")), match.group("indent")))

    if len(entries) != 1:
        raise ContractError(
            f"expected exactly one '- name: frontend' entry, found {len(entries)}"
        )

    start, entry_indent_len, _ = entries[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = ENTRY_RE.match(lines[index].rstrip("\r\n"))
        if match and len(match.group("indent")) == entry_indent_len:
            end = index
            break

    fields: dict[str, list[tuple[int, str, str]]] = {
        "newName": [],
        "newTag": [],
        "digest": [],
    }
    for index in range(start + 1, end):
        match = FIELD_RE.match(lines[index].rstrip("\r\n"))
        if match:
            fields[match.group("key")].append(
                (index, match.group("indent"), match.group("value"))
            )

    source_fields: list[tuple[int, str, str]] = []
    for index in range(start + 1, end):
        match = SOURCE_REVISION_RE.match(lines[index].rstrip("\r\n"))
        if match:
            source_fields.append((index, match.group("indent"), match.group("sha")))

    image_field = _single(fields["newName"], "newName")
    tag_field = _single(fields["newTag"], "newTag")
    digest_field = _single(fields["digest"], "digest")
    source_field = _single(source_fields, "sourceRevision")
    if image_field is None or image_field[2] != CANONICAL_IMAGE:
        actual = image_field[2] if image_field else "<missing>"
        raise ContractError(
            f"frontend newName must be {CANONICAL_IMAGE!r}, got {actual!r}"
        )
    if digest_field is None or not DIGEST_RE.fullmatch(digest_field[2]):
        actual = digest_field[2] if digest_field else "<missing>"
        raise ContractError(f"frontend digest is missing or invalid: {actual!r}")
    if tag_field is not None and not TAG_RE.fullmatch(tag_field[2]):
        raise ContractError(f"frontend newTag is invalid: {tag_field[2]!r}")

    return FrontendPin(
        image=image_field[2],
        source_sha=source_field[2] if source_field else None,
        tag=tag_field[2] if tag_field else None,
        digest=digest_field[2],
        entry_start=start,
        entry_end=end,
        field_indent=digest_field[1],
        tag_line=tag_field[0] if tag_field else None,
        source_line=source_field[0] if source_field else None,
        digest_line=digest_field[0],
    )


def inspect_file(path: Path) -> FrontendPin:
    if not path.is_file():
        raise ContractError(f"kustomization not found: {path}")
    return inspect_lines(path.read_text(encoding="utf-8").splitlines(keepends=True))


def inspect_rollout_contract(text: str) -> dict[str, int | str | None]:
    matches = list(FRONTEND_PATCH_RE.finditer(text))
    if len(matches) != 1:
        raise ContractError(
            f"expected exactly one frontend Deployment patch, found {len(matches)}"
        )
    body = matches[0].group("body")

    def patch_value(path: str) -> str | None:
        match = re.search(
            rf"^[ \t]+path:[ \t]*{re.escape(path)}[ \t]*\n"
            rf"[ \t]+value:[ \t]*(?P<value>\S+)[ \t]*$",
            body,
            re.MULTILINE,
        )
        return match.group("value") if match else None

    return {
        "patch_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "replicas": patch_value("/spec/replicas"),
        "max_surge": patch_value("/spec/strategy/rollingUpdate/maxSurge"),
        "max_unavailable": patch_value("/spec/strategy/rollingUpdate/maxUnavailable"),
        "progress_deadline_seconds": patch_value("/spec/progressDeadlineSeconds"),
    }


def inspect_contract_file(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, object] = inspect_lines(text.splitlines(keepends=True)).as_dict()
    result["rollout"] = inspect_rollout_contract(text)
    return result


def validate_request(
    sha: str, short_sha: str, image: str, tag: str, digest: str
) -> None:
    if not FULL_SHA_RE.fullmatch(sha):
        raise ContractError(
            "sha must be a 40-character lowercase hexadecimal commit id"
        )
    if not SHORT_SHA_RE.fullmatch(short_sha) or short_sha != sha[:7]:
        raise ContractError("short-sha must equal the first seven characters of sha")
    if image != CANONICAL_IMAGE:
        raise ContractError(f"image must be exactly {CANONICAL_IMAGE}")
    if not TAG_RE.fullmatch(tag) or tag != f"sha-{short_sha}":
        raise ContractError("image-tag must equal sha-<short-sha>")
    if not DIGEST_RE.fullmatch(digest):
        raise ContractError("image-digest must match sha256:<64 lowercase hex>")


def apply_pin(
    path: Path,
    *,
    sha: str,
    short_sha: str,
    image: str,
    tag: str,
    digest: str,
    check: bool = False,
) -> list[str]:
    validate_request(sha, short_sha, image, tag, digest)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    pin = inspect_lines(lines)
    changes: list[str] = []

    if pin.source_sha != sha:
        changes.append(f"sourceRevision: {pin.source_sha or '<missing>'} -> {sha}")
        if pin.source_line is None:
            insert_at = pin.tag_line if pin.tag_line is not None else pin.digest_line
            lines.insert(insert_at, f"{pin.field_indent}# sourceRevision: {sha}\n")
        else:
            lines[pin.source_line] = f"{pin.field_indent}# sourceRevision: {sha}\n"

    pin = inspect_lines(lines)
    if pin.tag != tag:
        changes.append(f"tag: {pin.tag or '<missing>'} -> {tag}")
        if pin.tag_line is None:
            lines.insert(pin.digest_line, f"{pin.field_indent}newTag: {tag}\n")
        else:
            lines[pin.tag_line] = f"{pin.field_indent}newTag: {tag}\n"

    # Re-inspect after a possible insertion so the digest line index is exact.
    current = inspect_lines(lines)
    if current.digest != digest:
        changes.append(f"digest: {current.digest} -> {digest}")
        lines[current.digest_line] = f"{current.field_indent}digest: {digest}\n"

    if not changes or check:
        return changes

    updated = "".join(lines)
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return changes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="print the current pin as JSON"
    )
    inspect_parser.add_argument("--kustomization", default=DEFAULT_KUSTOMIZATION)

    apply_parser = subparsers.add_parser(
        "apply", help="atomically update newTag and digest"
    )
    apply_parser.add_argument("--kustomization", default=DEFAULT_KUSTOMIZATION)
    apply_parser.add_argument("--sha", required=True)
    apply_parser.add_argument("--short-sha", required=True)
    apply_parser.add_argument("--image", required=True)
    apply_parser.add_argument("--image-tag", required=True)
    apply_parser.add_argument("--image-digest", required=True)
    apply_parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        path = Path(args.kustomization)
        if args.command == "inspect":
            print(json.dumps(inspect_contract_file(path), sort_keys=True))
            return 0
        changes = apply_pin(
            path,
            sha=args.sha,
            short_sha=args.short_sha,
            image=args.image,
            tag=args.image_tag,
            digest=args.image_digest,
            check=args.check,
        )
        for change in changes:
            print(f"  ~ frontend {change}")
        if not changes:
            print("[frontend-overlay] already at requested immutable pin")
        elif args.check:
            print(f"[frontend-overlay] check: {len(changes)} field(s) would change")
        else:
            print(f"[frontend-overlay] updated {len(changes)} field(s) atomically")
        return 0
    except (ContractError, OSError) as exc:
        print(f"[frontend-overlay] FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
