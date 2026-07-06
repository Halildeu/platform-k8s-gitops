#!/usr/bin/env python3
"""Evaluate Coordination Ledger claim state for one issue/session.

The command is read-only. It replays the ledger from genesis, derives the
current coordination state for the requested issue, and emits a small JSON
predicate for `board-sync require-claim`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"


class ClaimStateError(Exception):
    """User-facing refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise ClaimStateError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def parse_utc_z(value: Any, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ClaimStateError(f"{field_name} must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClaimStateError(f"{field_name} is not parseable: {exc}") from exc


def utc_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def payload_repo(data: dict[str, Any]) -> str | None:
    value = data.get("repository") or data.get("repo")
    return value if isinstance(value, str) and value else None


def payload_issue(data: dict[str, Any]) -> int | None:
    value = data.get("issue")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def payload_session(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def matches_issue(data: dict[str, Any], repo: str, issue: int) -> bool:
    return payload_repo(data) == repo and payload_issue(data) == issue


def read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            body = raw_line.strip()
            if not body:
                continue
            data = json.loads(body)
            if isinstance(data, dict):
                events.append(data)
    return events


def replay_or_invalid(path: Path, authority_path: Path) -> tuple[Any, list[dict[str, Any]]]:
    authority = VERIFIER.load_authority(authority_path)
    result = VERIFIER.replay(path, authority)
    if not result.valid:
        return result, []
    return result, read_events(path)


def current_issue_state(events: list[dict[str, Any]], repo: str, issue: int) -> dict[str, Any]:
    state: dict[str, Any] = {
        "permission_state": "no_claim",
        "active_session": None,
        "claim_expires_at": None,
        "last_heartbeat_at": None,
        "heartbeat_interval_minutes": 30,
        "heartbeat_grace_minutes": 45,
        "source_event_uuid": None,
        "deny_code": "ledger_no_active_claim",
        "reason": "no active claim found in ledger",
    }

    for event in events:
        event_type = event.get("event_type")
        data = payload(event)
        if not matches_issue(data, repo, issue):
            continue

        event_uuid = event.get("event_uuid")
        committed_at = parse_utc_z(event.get("committed_at"), "committed_at")

        if event_type == "CLAIM_ACCEPTED":
            session = payload_session(data, "session", "claim_session")
            if not session:
                continue
            state = {
                "permission_state": "active_winner",
                "active_session": session,
                "claim_expires_at": utc_z(
                    parse_utc_z(data.get("claim_expires_at") or data.get("expires_at"), "claim_expires_at")
                ),
                "last_heartbeat_at": utc_z(committed_at),
                "heartbeat_interval_minutes": int(data.get("heartbeat_interval_minutes") or 30),
                "heartbeat_grace_minutes": int(data.get("heartbeat_grace_minutes") or 45),
                "source_event_uuid": event_uuid,
                "deny_code": None,
                "reason": "latest claim accepted",
            }
            continue

        if event_type == "HEARTBEAT_EVIDENCE":
            session = payload_session(data, "session", "claim_session")
            if session and session == state.get("active_session"):
                state["last_heartbeat_at"] = utc_z(committed_at)
            continue

        if event_type in {
            "CLAIM_STALE",
            "CLAIM_EXPIRED",
            "MIRROR_DRIFT_DETECTED",
            "MIRROR_ORPHAN_DETECTED",
            "BLOCKED_FAIL_CLOSED",
        }:
            session = payload_session(data, "session", "claim_session")
            if session and session != state.get("active_session"):
                continue
            state.update(
                {
                    "permission_state": str(event_type).lower(),
                    "deny_code": "ledger_claim_revoked",
                    "reason": f"ledger event {event_type} revokes permission",
                    "source_event_uuid": event_uuid,
                }
            )
            continue

        if event_type == "TAKEOVER_ACCEPTED":
            old_session = payload_session(data, "old_session")
            new_session = payload_session(data, "new_session")
            if state.get("active_session") in {old_session, new_session}:
                state.update(
                    {
                        "permission_state": "takeover_pending_mirror",
                        "active_session": None,
                        "deny_code": "ledger_takeover_pending",
                        "reason": "takeover accepted but not committed",
                        "source_event_uuid": event_uuid,
                    }
                )
            continue

        if event_type == "TAKEOVER_COMMITTED":
            new_session = payload_session(data, "new_session")
            if not new_session:
                continue
            state.update(
                {
                    "permission_state": "active_winner",
                    "active_session": new_session,
                    "claim_expires_at": utc_z(
                        parse_utc_z(data.get("claim_expires_at") or data.get("expires_at"), "claim_expires_at")
                    ),
                    "last_heartbeat_at": utc_z(committed_at),
                    "heartbeat_interval_minutes": int(data.get("heartbeat_interval_minutes") or 30),
                    "heartbeat_grace_minutes": int(data.get("heartbeat_grace_minutes") or 45),
                    "deny_code": None,
                    "reason": "takeover committed",
                    "source_event_uuid": event_uuid,
                }
            )
            continue

        if event_type in {"TOMBSTONE_CHAIN", "SUPERSEDE_ISSUE"}:
            state.update(
                {
                    "permission_state": str(event_type).lower(),
                    "active_session": None,
                    "deny_code": "ledger_issue_superseded",
                    "reason": f"ledger event {event_type} prevents permission",
                    "source_event_uuid": event_uuid,
                }
            )

    return state


def evaluate_state(state: dict[str, Any], requested_session: str, now: datetime) -> dict[str, Any]:
    if state.get("permission_state") != "active_winner":
        return {
            "allowed": False,
            "deny_code": state.get("deny_code") or "ledger_not_active",
            "reason": state.get("reason") or "ledger state is not active winner",
        }

    active_session = state.get("active_session")
    if active_session != requested_session:
        return {
            "allowed": False,
            "deny_code": "ledger_session_mismatch",
            "reason": f"ledger active_session={active_session!r} expected={requested_session!r}",
        }

    expires_at = parse_utc_z(state.get("claim_expires_at"), "claim_expires_at")
    if expires_at is not None and now > expires_at:
        return {
            "allowed": False,
            "deny_code": "ledger_claim_expired",
            "reason": f"ledger claim expired at {utc_z(expires_at)}",
        }

    last_heartbeat_at = parse_utc_z(state.get("last_heartbeat_at"), "last_heartbeat_at")
    if last_heartbeat_at is not None:
        interval = int(state.get("heartbeat_interval_minutes") or 30)
        grace = int(state.get("heartbeat_grace_minutes") or 45)
        heartbeat_deadline = last_heartbeat_at + timedelta(minutes=interval + grace)
        if now > heartbeat_deadline:
            return {
                "allowed": False,
                "deny_code": "ledger_claim_stale",
                "reason": f"ledger heartbeat deadline passed at {utc_z(heartbeat_deadline)}",
            }

    return {"allowed": True, "deny_code": None, "reason": "ledger active winner matches"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--session", required=True)
    parser.add_argument("--now")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    now = parse_utc_z(args.now, "--now") if args.now else datetime.now(timezone.utc).replace(microsecond=0)
    result, events = replay_or_invalid(args.ledger, args.authority)
    if not result.valid:
        prefix = result.valid_prefix_hash
        print(
            json.dumps(
                {
                    "configured": True,
                    "ledger": str(args.ledger),
                    "valid": False,
                    "allowed": False,
                    "deny_code": "invalid_ledger_suffix",
                    "reason": result.reason,
                    "valid_events": result.valid_events,
                    "valid_prefix_hash": None if prefix is None else f"sha256:{prefix}",
                    "invalid_line": result.invalid_line,
                },
                sort_keys=True,
            )
        )
        return 1

    state = current_issue_state(events, args.repo, args.issue)
    decision = evaluate_state(state, args.session, now)
    prefix = result.valid_prefix_hash
    print(
        json.dumps(
            {
                "configured": True,
                "ledger": str(args.ledger),
                "valid": True,
                "allowed": decision["allowed"],
                "deny_code": decision["deny_code"],
                "reason": decision["reason"],
                "permission_state": state.get("permission_state"),
                "active_session": state.get("active_session"),
                "claim_expires_at": state.get("claim_expires_at"),
                "last_heartbeat_at": state.get("last_heartbeat_at"),
                "source_event_uuid": state.get("source_event_uuid"),
                "valid_events": result.valid_events,
                "valid_prefix_hash": None if prefix is None else f"sha256:{prefix}",
            },
            sort_keys=True,
        )
    )
    return 0 if decision["allowed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ClaimStateError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
