#!/usr/bin/env python3
"""Replay verifier for Coordination Ledger v1 JSONL streams.

The verifier is intentionally offline: it validates an append-only JSONL ledger
against the event authority fixture, hash chain, payload hashes, event writer
rules, timestamp monotonicity, and event UUID idempotency. It does not mutate
GitHub, Project fields, issue bodies, or comments.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"
EXPECTED_EVENT_SCHEMA = "coordination-ledger-event/v1"
HASH_RE = re.compile(r"^(?:sha256:)?([a-f0-9]{64})$")
COMMENT_BINDING_TOLERANCE_MINUTES = {
    "normal": 5,
    "degraded": 15,
    "recovery": 15,
}


class LedgerInvalid(Exception):
    """Raised when replay finds the first invalid suffix event."""

    def __init__(self, line: int, reason: str) -> None:
        self.line = line
        self.reason = reason
        super().__init__(f"line {line}: {reason}")


@dataclass(frozen=True)
class ReplayResult:
    path: str
    valid: bool
    valid_events: int
    duplicate_events: int
    valid_prefix_hash: str | None
    invalid_line: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "valid": self.valid,
            "valid_events": self.valid_events,
            "duplicate_events": self.duplicate_events,
            "valid_prefix_hash": self.valid_prefix_hash,
            "invalid_line": self.invalid_line,
            "reason": self.reason,
        }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def normalize_hash(value: Any, field: str, line: int, *, allow_null: bool = False) -> str | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str):
        raise LedgerInvalid(line, f"{field} must be a sha256 hash string")
    match = HASH_RE.match(value)
    if not match:
        raise LedgerInvalid(line, f"{field} must match sha256:<64-hex> or bare 64-hex")
    return match.group(1)


def parse_committed_at(value: Any, line: int) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LedgerInvalid(line, "committed_at must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerInvalid(line, f"committed_at is not parseable: {exc}") from exc


def load_authority(path: Path) -> dict[str, set[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERR: authority fixture not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"ERR: authority fixture invalid JSON: {path}: {exc}", file=sys.stderr)
        sys.exit(2)

    events = raw.get("events")
    if not isinstance(events, dict):
        print(f"ERR: authority fixture missing object field 'events': {path}", file=sys.stderr)
        sys.exit(2)

    parsed: dict[str, set[str]] = {}
    for event_type, body in events.items():
        if not isinstance(event_type, str) or not isinstance(body, dict):
            print(f"ERR: invalid authority event entry: {event_type!r}", file=sys.stderr)
            sys.exit(2)
        writers = body.get("authorizedWriters")
        if not isinstance(writers, list) or not all(isinstance(writer, str) for writer in writers):
            print(f"ERR: invalid authorizedWriters for event {event_type}", file=sys.stderr)
            sys.exit(2)
        parsed[event_type] = set(writers)
    return parsed


def read_event(line_body: str, line_number: int) -> dict[str, Any]:
    try:
        event = json.loads(line_body)
    except json.JSONDecodeError as exc:
        raise LedgerInvalid(line_number, f"invalid JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise LedgerInvalid(line_number, "ledger line must be a JSON object")
    return event


def require_string(event: dict[str, Any], field: str, line: int) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value:
        raise LedgerInvalid(line, f"{field} must be a non-empty string")
    return value


def require_comment_string(binding: dict[str, Any], field: str, line: int) -> str:
    value = binding.get(field)
    if not isinstance(value, str) or not value:
        raise LedgerInvalid(line, f"comment_binding.{field} must be a non-empty string")
    return value


def require_positive_int(value: Any, field: str, line: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LedgerInvalid(line, f"comment_binding.{field} must be a positive integer")


def validate_comment_binding(
    event: dict[str, Any],
    line: int,
    *,
    expected_payload_hash: str,
    committed_at: datetime,
) -> None:
    binding = event.get("comment_binding")
    if binding is None:
        return
    if not isinstance(binding, dict):
        raise LedgerInvalid(line, "comment_binding must be an object")

    surface = require_comment_string(binding, "surface", line)
    if surface != "github_issue_comment":
        raise LedgerInvalid(line, "comment_binding.surface must be github_issue_comment")

    repository = require_comment_string(binding, "repository", line)
    if "/" not in repository:
        raise LedgerInvalid(line, "comment_binding.repository must be owner/repo")

    require_positive_int(binding.get("issue"), "issue", line)
    require_positive_int(binding.get("comment_id"), "comment_id", line)
    require_positive_int(binding.get("author_id"), "author_id", line)
    require_comment_string(binding, "author_login", line)
    require_comment_string(binding, "author_type", line)

    raw_body_hash = normalize_hash(binding.get("raw_body_hash"), "comment_binding.raw_body_hash", line)
    if raw_body_hash is None:
        raise LedgerInvalid(line, "comment_binding.raw_body_hash must be present")

    actual_payload_hash = normalize_hash(binding.get("payload_hash"), "comment_binding.payload_hash", line)
    if actual_payload_hash != expected_payload_hash:
        raise LedgerInvalid(
            line,
            "comment_binding.payload_hash mismatch "
            f"expected=sha256:{expected_payload_hash} actual=sha256:{actual_payload_hash}",
        )

    created_at = parse_committed_at(binding.get("created_at"), line)
    updated_at = parse_committed_at(binding.get("updated_at"), line)
    if updated_at != created_at:
        raise LedgerInvalid(line, "comment_binding.updated_at must equal created_at")

    verification_mode = require_comment_string(binding, "verification_mode", line)
    expected_tolerance = COMMENT_BINDING_TOLERANCE_MINUTES.get(verification_mode)
    if expected_tolerance is None:
        allowed = ", ".join(sorted(COMMENT_BINDING_TOLERANCE_MINUTES))
        raise LedgerInvalid(line, f"comment_binding.verification_mode must be one of: {allowed}")

    tolerance = binding.get("timestamp_tolerance_minutes")
    if tolerance != expected_tolerance:
        raise LedgerInvalid(
            line,
            "comment_binding.timestamp_tolerance_minutes mismatch "
            f"expected={expected_tolerance} actual={tolerance}",
        )

    delta_seconds = abs((created_at - committed_at).total_seconds())
    if delta_seconds > expected_tolerance * 60:
        raise LedgerInvalid(
            line,
            "comment_binding.created_at outside tolerance "
            f"mode={verification_mode} tolerance_minutes={expected_tolerance}",
        )


def validate_new_event(
    event: dict[str, Any],
    line: int,
    authority: dict[str, set[str]],
    last_hash: str | None,
    last_committed_at: datetime | None,
    valid_events: int,
) -> tuple[str, datetime]:
    schema_version = require_string(event, "schemaVersion", line)
    if schema_version != EXPECTED_EVENT_SCHEMA:
        raise LedgerInvalid(line, f"schemaVersion must be {EXPECTED_EVENT_SCHEMA}")

    event_type = require_string(event, "event_type", line)
    if event_type not in authority:
        raise LedgerInvalid(line, f"unknown event_type {event_type!r}")

    writer_role = require_string(event, "writer_role", line)
    if writer_role not in authority[event_type]:
        allowed = ", ".join(sorted(authority[event_type]))
        raise LedgerInvalid(
            line,
            f"writer_role {writer_role!r} is not authorized for {event_type}; allowed={allowed}",
        )

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise LedgerInvalid(line, "payload must be an object")

    expected_payload_hash = sha256_hex(payload)
    actual_payload_hash = normalize_hash(event.get("payload_hash"), "payload_hash", line)
    if actual_payload_hash != expected_payload_hash:
        raise LedgerInvalid(
            line,
            f"payload_hash mismatch expected=sha256:{expected_payload_hash} actual=sha256:{actual_payload_hash}",
        )

    previous_event_hash = normalize_hash(
        event.get("previous_event_hash"), "previous_event_hash", line, allow_null=True
    )
    if valid_events == 0:
        if previous_event_hash is not None:
            raise LedgerInvalid(line, "first event previous_event_hash must be null")
    elif previous_event_hash != last_hash:
        raise LedgerInvalid(
            line,
            f"previous_event_hash mismatch expected=sha256:{last_hash} actual=sha256:{previous_event_hash}",
        )

    committed_at = parse_committed_at(event.get("committed_at"), line)
    if last_committed_at and committed_at < last_committed_at:
        raise LedgerInvalid(
            line,
            f"committed_at moved backwards previous={last_committed_at.isoformat()} current={committed_at.isoformat()}",
        )

    validate_comment_binding(
        event,
        line,
        expected_payload_hash=expected_payload_hash,
        committed_at=committed_at,
    )

    expected_event_hash_material = copy.deepcopy(event)
    expected_event_hash_material.pop("event_hash", None)
    expected_event_hash = sha256_hex(expected_event_hash_material)
    actual_event_hash = normalize_hash(event.get("event_hash"), "event_hash", line)
    if actual_event_hash != expected_event_hash:
        raise LedgerInvalid(
            line,
            f"event_hash mismatch expected=sha256:{expected_event_hash} actual=sha256:{actual_event_hash}",
        )

    return expected_event_hash, committed_at


def replay(path: Path, authority: dict[str, set[str]]) -> ReplayResult:
    last_hash: str | None = None
    last_committed_at: datetime | None = None
    valid_events = 0
    duplicate_events = 0
    seen_event_uuid: dict[str, bytes] = {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                body = raw_line.strip()
                if not body:
                    continue

                event = read_event(body, line_number)
                event_uuid = require_string(event, "event_uuid", line_number)
                canonical_event = canonical_json_bytes(event)

                previous_duplicate = seen_event_uuid.get(event_uuid)
                if previous_duplicate is not None:
                    if previous_duplicate != canonical_event:
                        raise LedgerInvalid(
                            line_number,
                            f"duplicate event_uuid {event_uuid!r} differs from first occurrence",
                        )
                    duplicate_events += 1
                    continue

                next_hash, committed_at = validate_new_event(
                    event, line_number, authority, last_hash, last_committed_at, valid_events
                )
                seen_event_uuid[event_uuid] = canonical_event
                last_hash = next_hash
                last_committed_at = committed_at
                valid_events += 1
    except LedgerInvalid as exc:
        return ReplayResult(
            path=str(path),
            valid=False,
            valid_events=valid_events,
            duplicate_events=duplicate_events,
            valid_prefix_hash=last_hash,
            invalid_line=exc.line,
            reason=exc.reason,
        )
    except FileNotFoundError:
        return ReplayResult(
            path=str(path),
            valid=False,
            valid_events=valid_events,
            duplicate_events=duplicate_events,
            valid_prefix_hash=last_hash,
            invalid_line=None,
            reason="file not found",
        )

    return ReplayResult(
        path=str(path),
        valid=True,
        valid_events=valid_events,
        duplicate_events=duplicate_events,
        valid_prefix_hash=last_hash,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", nargs="+", help="Coordination ledger JSONL file(s) to replay")
    parser.add_argument(
        "--authority",
        default=str(DEFAULT_AUTHORITY_PATH),
        help=f"event authority fixture path (default: {DEFAULT_AUTHORITY_PATH})",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    authority = load_authority(Path(args.authority))
    results = [replay(Path(item), authority) for item in args.ledger]

    if args.json:
        print(json.dumps([result.as_dict() for result in results], indent=2, sort_keys=True))
    else:
        for result in results:
            prefix = result.valid_prefix_hash or "GENESIS"
            if result.valid:
                print(
                    f"[OK] {result.path}: valid_events={result.valid_events} "
                    f"duplicate_events={result.duplicate_events} valid_prefix_hash=sha256:{prefix}"
                )
            else:
                location = f"line={result.invalid_line}" if result.invalid_line else "line=unknown"
                print(
                    f"[FAIL] {result.path}: {location} valid_events={result.valid_events} "
                    f"valid_prefix_hash=sha256:{prefix} reason={result.reason}"
                )

    return 0 if all(result.valid for result in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
