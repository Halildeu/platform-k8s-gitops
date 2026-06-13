#!/usr/bin/env python3
"""Validate Coordination Ledger PR mirror marker blocks.

The validator is offline/read-only by default. It verifies a snapshot of PR
bodies against a valid Coordination Ledger replay and rejects stale, missing,
or forged `coordination-ledger-pr-mirror:v1` marker blocks.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"
PR_MARKER_START = "<!-- coordination-ledger-pr-mirror:v1"
PR_MARKER_END = "-->"
HASH_RE = re.compile(r"^(?:sha256:)?([a-f0-9]{64})$")

STATE_EVENT_TYPES = {
    "active_winner": {"CLAIM_ACCEPTED", "TAKEOVER_COMMITTED"},
    "takeover_pending_mirror": {"TAKEOVER_ACCEPTED"},
    "superseded": {"PR_SUPERSEDED", "SUPERSEDE_ISSUE"},
    "tombstoned": {"TOMBSTONE_CHAIN"},
    "blocked_fail_closed": {
        "BLOCKED_FAIL_CLOSED",
        "MIRROR_DRIFT_DETECTED",
        "MIRROR_ORPHAN_DETECTED",
        "SECRET_SCAN_FAILED",
        "VERIFY_FAILED",
    },
}


class MirrorValidationError(Exception):
    """User-facing validation refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise MirrorValidationError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def normalize_hash(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise MirrorValidationError(f"{field} must be a sha256 hash string")
    match = HASH_RE.fullmatch(value)
    if not match:
        raise MirrorValidationError(f"{field} must match sha256:<64-hex> or bare 64-hex")
    return f"sha256:{match.group(1)}"


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MirrorValidationError(f"{field} must be a non-empty string")
    return value


def require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MirrorValidationError(f"{field} must be a positive integer")
    return value


def parse_marker(body: str) -> dict[str, str]:
    start = body.find(PR_MARKER_START)
    if start < 0:
        raise MirrorValidationError("PR body missing coordination-ledger-pr-mirror:v1 marker")
    end = body.find(PR_MARKER_END, start)
    if end < 0:
        raise MirrorValidationError("PR marker is not closed")
    marker_body = body[start + len(PR_MARKER_START) : end].strip()
    parsed: dict[str, str] = {}
    for raw_line in marker_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise MirrorValidationError(f"PR marker line missing ':' separator: {line!r}")
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    for key in ("coordination_state", "event_uuid", "event_hash", "session"):
        if not parsed.get(key):
            raise MirrorValidationError(f"PR marker missing {key}")
    parsed["event_hash"] = normalize_hash(parsed["event_hash"], "pr_marker.event_hash")
    return parsed


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def event_sessions(event: dict[str, Any]) -> set[str]:
    data = payload(event)
    sessions = set()
    for key in ("session", "claim_session", "old_session", "new_session", "active_session"):
        value = data.get(key)
        if isinstance(value, str) and value:
            sessions.add(value)
    return sessions


def load_events(ledger: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with ledger.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            body = raw_line.strip()
            if not body:
                continue
            data = json.loads(body)
            if isinstance(data, dict):
                events.append(data)
    return events


def replay_valid(ledger: Path, authority_path: Path) -> Any:
    authority = VERIFIER.load_authority(authority_path)
    result = VERIFIER.replay(ledger, authority)
    if not result.valid:
        raise MirrorValidationError(
            "ledger invalid; PR mirror validation fail closed "
            f"line={result.invalid_line} reason={result.reason}"
        )
    return result


def validate_one(pr: dict[str, Any], events_by_uuid: dict[str, dict[str, Any]], repository: str) -> dict[str, Any]:
    number = require_positive_int(pr.get("number"), "pull_requests[].number")
    body = require_string(pr.get("body"), "pull_requests[].body")
    marker = parse_marker(body)
    event_uuid = marker["event_uuid"]
    event = events_by_uuid.get(event_uuid)
    if event is None:
        raise MirrorValidationError(f"PR #{number} marker event_uuid not present in valid ledger")

    actual_event_hash = normalize_hash(event.get("event_hash"), "ledger.event_hash")
    if marker["event_hash"] != actual_event_hash:
        raise MirrorValidationError(
            f"PR #{number} event_hash mismatch expected={actual_event_hash} actual={marker['event_hash']}"
        )

    state = marker["coordination_state"]
    allowed_types = STATE_EVENT_TYPES.get(state)
    if allowed_types is None:
        raise MirrorValidationError(f"PR #{number} unknown coordination_state {state!r}")
    event_type = event.get("event_type")
    if event_type not in allowed_types:
        raise MirrorValidationError(
            f"PR #{number} state {state!r} cannot point at ledger event_type {event_type!r}"
        )

    sessions = event_sessions(event)
    if sessions and marker["session"] not in sessions:
        raise MirrorValidationError(
            f"PR #{number} session mismatch marker={marker['session']!r} ledger_sessions={sorted(sessions)!r}"
        )

    data = payload(event)
    event_repo = data.get("repository") or data.get("repo")
    if isinstance(event_repo, str) and event_repo and event_repo != repository:
        raise MirrorValidationError(
            f"PR #{number} repository mismatch snapshot={repository!r} ledger={event_repo!r}"
        )

    expected_issue = pr.get("expected_issue")
    if expected_issue is not None:
        expected_issue = require_positive_int(expected_issue, "pull_requests[].expected_issue")
        event_issue = data.get("issue")
        if event_issue != expected_issue:
            raise MirrorValidationError(
                f"PR #{number} expected_issue mismatch expected={expected_issue} ledger={event_issue}"
            )

    return {
        "number": number,
        "coordination_state": state,
        "event_uuid": event_uuid,
        "event_hash": marker["event_hash"],
        "event_type": event_type,
        "session": marker["session"],
        "valid": True,
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MirrorValidationError("snapshot must be a JSON object")
    repository = data.get("repository")
    if not isinstance(repository, str) or "/" not in repository:
        raise MirrorValidationError("snapshot.repository must be owner/repo")
    pull_requests = data.get("pull_requests")
    if not isinstance(pull_requests, list):
        raise MirrorValidationError("snapshot.pull_requests must be a list")
    return data


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path, help="PR mirror snapshot JSON")
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        replay = replay_valid(args.ledger, args.authority)
        snapshot = load_snapshot(args.snapshot)
        events = load_events(args.ledger)
        events_by_uuid = {
            str(event.get("event_uuid")): event
            for event in events
            if isinstance(event.get("event_uuid"), str)
        }
        validated = [
            validate_one(item, events_by_uuid, snapshot["repository"])
            for item in snapshot["pull_requests"]
        ]
        print(
            json.dumps(
                {
                    "valid": True,
                    "fail_closed": False,
                    "ledger_valid_events": replay.valid_events,
                    "validated_pr_mirrors": validated,
                },
                sort_keys=True,
            )
        )
        return 0
    except (MirrorValidationError, json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "fail_closed": True,
                    "reason": str(exc),
                    "permission_granted": False,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
