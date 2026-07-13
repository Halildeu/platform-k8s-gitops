#!/usr/bin/env python3
"""Validate and inspect the immutable testai backend digest contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_SERVICES = (
    "auth-service",
    "permission-service",
    "user-service",
    "variant-service",
    "core-data-service",
    "report-service",
    "schema-service",
    "endpoint-admin-service",
    "audio-gateway-service",
    "meeting-service",
    "transcript-service",
    "audit-event-consumer-service",
    "api-gateway",
)

# The source image workflow also publishes these images. They are accepted in
# the dispatch envelope but intentionally excluded from the platform-test
# runtime promotion map.
BUILD_ONLY_SERVICES = ("discovery-server", "notification-orchestrator")
ALLOWED_PAYLOAD_SERVICES = frozenset(REQUIRED_SERVICES + BUILD_ONLY_SERVICES)
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
ENTRY_START_RE = re.compile(r"^[ \t]*-[ \t]+name:[ \t]*\S")
NEWNAME_RE = re.compile(
    r"^[ \t]+newName:[ \t]*ghcr\.io/halildeu/platform-backend-(?P<service>[a-z0-9-]+)[ \t]*$"
)
ENTRY_DIGEST_RE = re.compile(r"^[ \t]+digest:[ \t]*(?P<digest>sha256:[a-f0-9]{64})[ \t]*$")


def fail(message: str) -> None:
    print(f"[backend-testai-digest-contract] FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def decode_payload(raw: str) -> dict[str, object]:
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"digest payload is not JSON: {exc}")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            fail(f"stringified digest payload is not JSON: {exc}")
    if not isinstance(value, dict):
        fail("digest payload must be an object or a stringified object")
    return value


def normalize(raw: str) -> dict[str, str]:
    payload = decode_payload(raw)
    unknown = sorted(set(payload) - ALLOWED_PAYLOAD_SERVICES)
    if unknown:
        fail(f"unknown service key(s): {', '.join(unknown)}")

    missing = [service for service in REQUIRED_SERVICES if service not in payload]
    if missing:
        fail(
            "full runtime map required; missing service key(s): "
            + ", ".join(missing)
        )

    normalized: dict[str, str] = {}
    for service in REQUIRED_SERVICES:
        digest = payload[service]
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            fail(f"{service} digest must match sha256:<64 lowercase hex>")
        normalized[service] = digest

    for service in BUILD_ONLY_SERVICES:
        if service in payload:
            digest = payload[service]
            if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
                fail(f"{service} digest must match sha256:<64 lowercase hex>")

    return normalized


def inspect_overlay(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"kustomization not found: {path}")

    found: dict[str, str] = {}
    current_service: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if ENTRY_START_RE.match(line):
            current_service = None
            continue
        match_name = NEWNAME_RE.match(line)
        if match_name:
            current_service = match_name.group("service")
            continue
        if current_service is None:
            continue
        match_digest = ENTRY_DIGEST_RE.match(line)
        if match_digest:
            if current_service in REQUIRED_SERVICES:
                if current_service in found:
                    fail(f"duplicate image entry for {current_service} in {path}")
                found[current_service] = match_digest.group("digest")
            current_service = None

    missing = [service for service in REQUIRED_SERVICES if service not in found]
    if missing:
        fail(
            f"overlay missing required backend digest(s) in {path}: "
            + ", ".join(missing)
        )
    return {service: found[service] for service in REQUIRED_SERVICES}


def compact(value: dict[str, str]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("normalize", help="read a dispatch map from stdin")
    inspect_parser = subparsers.add_parser("inspect", help="print the overlay runtime map")
    inspect_parser.add_argument(
        "--kustomization",
        default="kustomize/overlays/test/kustomization.yaml",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.command == "normalize":
        raw = sys.stdin.read()
        if not raw.strip():
            fail("digest payload is empty")
        print(compact(normalize(raw)))
        return 0
    if args.command == "inspect":
        print(compact(inspect_overlay(Path(args.kustomization))))
        return 0
    fail(f"unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
