#!/usr/bin/env python3
"""Append one Coordination Ledger v1 event with a local CAS guard.

This is the writer foundation for the append-only coordination ledger. It is
deliberately local/offline: it validates the existing JSONL ledger from genesis,
checks the expected previous hash, builds a canonical event, validates the
would-be ledger suffix in a temp file, and only then appends the new line.

It does not mutate GitHub issues, Project fields, PR bodies, or materialized
comments.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    # Windows callers still get hash-chain CAS validation, but no local
    # advisory lock. Remote/branch CAS remains the required distributed guard.
    fcntl = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"
EXPECTED_EVENT_SCHEMA = "coordination-ledger-event/v1"
HASH_RE = re.compile(r"^(?:sha256:)?([a-f0-9]{64})$")


class AppendError(Exception):
    """User-facing append refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise AppendError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def canonical_event_line(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_json_value(*, raw: str | None, path: str | None, label: str) -> dict[str, Any]:
    if raw is not None and path is not None:
        raise AppendError(f"{label}: pass either inline JSON or file path, not both")
    if raw is None and path is None:
        raise AppendError(f"{label}: JSON object is required")

    try:
        if path is not None:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        else:
            data = json.loads(raw or "")
    except FileNotFoundError as exc:
        raise AppendError(f"{label}: file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppendError(f"{label}: invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise AppendError(f"{label}: value must be a JSON object")
    return data


def normalize_expected_previous(value: str | None) -> str | None | object:
    if value is None:
        return _NO_EXPECTATION
    normalized = value.strip()
    if normalized.upper() == "GENESIS" or normalized.lower() in {"null", "none"}:
        return None
    match = HASH_RE.match(normalized)
    if not match:
        raise AppendError(
            "--expect-previous-hash must be GENESIS, null, sha256:<64-hex>, or bare 64-hex"
        )
    return match.group(1)


def normalize_replay_hash(value: str | None) -> str | None:
    if value is None:
        return None
    match = HASH_RE.match(value)
    if not match:
        raise AppendError(f"replay returned invalid prefix hash: {value}")
    return match.group(1)


def utc_now_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_committed_at(value: str) -> str:
    try:
        VERIFIER.parse_committed_at(value, 0)
    except Exception as exc:  # noqa: BLE001 - convert verifier exception to CLI refusal
        raise AppendError(str(exc)) from exc
    return value


def replay_existing(ledger: Path, authority: dict[str, set[str]]) -> Any:
    if not ledger.exists():
        return _ReplayEmpty(path=str(ledger))
    result = VERIFIER.replay(ledger, authority)
    if not result.valid:
        prefix = result.valid_prefix_hash or "GENESIS"
        raise AppendError(
            "existing_ledger_invalid "
            f"line={result.invalid_line or 'unknown'} "
            f"valid_prefix_hash=sha256:{prefix} "
            f"reason={result.reason}"
        )
    return result


def validate_expected_previous(expected: str | None | object, current: str | None) -> None:
    if expected is _NO_EXPECTATION:
        return
    if expected != current:
        expected_label = "GENESIS" if expected is None else f"sha256:{expected}"
        actual_label = "GENESIS" if current is None else f"sha256:{current}"
        raise AppendError(f"cas_mismatch expected={expected_label} actual={actual_label}")


def build_event(args: argparse.Namespace, previous_hash: str | None) -> dict[str, Any]:
    payload = load_json_value(raw=args.payload_json, path=args.payload_file, label="payload")
    event = {
        "schemaVersion": EXPECTED_EVENT_SCHEMA,
        "event_uuid": args.event_uuid or str(uuid.uuid4()),
        "event_type": args.event_type,
        "writer_role": args.writer_role,
        "committed_at": ensure_committed_at(args.committed_at or utc_now_z()),
        "previous_event_hash": None if previous_hash is None else f"sha256:{previous_hash}",
        "payload": payload,
    }

    if args.metadata_json is not None or args.metadata_file is not None:
        event["metadata"] = load_json_value(
            raw=args.metadata_json,
            path=args.metadata_file,
            label="metadata",
        )
    if args.comment_binding_json is not None or args.comment_binding_file is not None:
        event["comment_binding"] = load_json_value(
            raw=args.comment_binding_json,
            path=args.comment_binding_file,
            label="comment_binding",
        )
    if args.key_id:
        event["key_id"] = args.key_id
    if args.signature:
        try:
            event["signature"] = json.loads(args.signature)
        except json.JSONDecodeError:
            event["signature"] = args.signature

    event["payload_hash"] = f"sha256:{VERIFIER.sha256_hex(payload)}"
    event["event_hash"] = f"sha256:{VERIFIER.sha256_hex(event)}"
    return event


def ledger_text_with_candidate(ledger: Path, event: dict[str, Any]) -> str:
    body = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
    if body and not body.endswith("\n"):
        body += "\n"
    return body + canonical_event_line(event) + "\n"


def validate_candidate(
    *,
    ledger: Path,
    event: dict[str, Any],
    authority: dict[str, set[str]],
) -> Any:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        candidate_path = Path(handle.name)
        handle.write(ledger_text_with_candidate(ledger, event))

    try:
        result = VERIFIER.replay(candidate_path, authority)
    finally:
        candidate_path.unlink(missing_ok=True)

    if not result.valid:
        prefix = result.valid_prefix_hash or "GENESIS"
        raise AppendError(
            "candidate_ledger_invalid "
            f"line={result.invalid_line or 'unknown'} "
            f"valid_prefix_hash=sha256:{prefix} "
            f"reason={result.reason}"
        )
    return result


@contextmanager
def ledger_lock(ledger: Path) -> Iterator[None]:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger.with_name(f"{ledger.name}.lock")
    with lock_path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_event_line(ledger: Path, event: dict[str, Any]) -> None:
    line = canonical_event_line(event)
    with ledger.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() > 0:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                handle.write(b"\n")
        handle.write(line.encode("utf-8"))
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="JSONL ledger path to append to")
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), help="event authority fixture path")
    parser.add_argument("--event-type", required=True, help="Coordination ledger event_type")
    parser.add_argument("--writer-role", required=True, help="writer_role for the event")
    parser.add_argument("--event-uuid", help="event UUID; generated with uuid4 when omitted")
    parser.add_argument("--committed-at", help="ISO-8601 UTC timestamp ending in Z; defaults to now")
    parser.add_argument(
        "--expect-previous-hash",
        required=True,
        help="CAS guard: GENESIS/null, sha256:<64-hex>, or bare 64-hex",
    )
    parser.add_argument("--key-id", help="optional key_id field")
    parser.add_argument("--signature", help="optional signature field, as string or JSON object")

    payload = parser.add_mutually_exclusive_group(required=True)
    payload.add_argument("--payload-json", help="event payload JSON object")
    payload.add_argument("--payload-file", help="event payload JSON object file")

    metadata = parser.add_mutually_exclusive_group()
    metadata.add_argument("--metadata-json", help="optional metadata JSON object")
    metadata.add_argument("--metadata-file", help="optional metadata JSON object file")

    binding = parser.add_mutually_exclusive_group()
    binding.add_argument("--comment-binding-json", help="optional comment_binding JSON object")
    binding.add_argument("--comment-binding-file", help="optional comment_binding JSON object file")
    return parser.parse_args(argv)


class _NoExpectation:
    pass


_NO_EXPECTATION = _NoExpectation()


class _ReplayEmpty:
    def __init__(self, *, path: str) -> None:
        self.path = path
        self.valid = True
        self.valid_events = 0
        self.duplicate_events = 0
        self.valid_prefix_hash = None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ledger = Path(args.ledger)
    expected_previous = normalize_expected_previous(args.expect_previous_hash)
    authority = VERIFIER.load_authority(Path(args.authority))

    with ledger_lock(ledger):
        before = replay_existing(ledger, authority)
        current_hash = normalize_replay_hash(before.valid_prefix_hash)
        validate_expected_previous(expected_previous, current_hash)

        event = build_event(args, current_hash)
        validate_candidate(ledger=ledger, event=event, authority=authority)
        append_event_line(ledger, event)
        after = replay_existing(ledger, authority)

    print(
        json.dumps(
            {
                "ledger": str(ledger),
                "event_uuid": event["event_uuid"],
                "event_type": event["event_type"],
                "writer_role": event["writer_role"],
                "previous_event_hash": event["previous_event_hash"],
                "event_hash": event["event_hash"],
                "valid_events": after.valid_events,
                "valid_prefix_hash": (
                    None if after.valid_prefix_hash is None else f"sha256:{after.valid_prefix_hash}"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except AppendError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
