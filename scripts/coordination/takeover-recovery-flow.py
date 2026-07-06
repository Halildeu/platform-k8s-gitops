#!/usr/bin/env python3
"""Plan Coordination Ledger takeover and recovery events.

This helper is read-only. It verifies the existing ledger, enforces the
two-phase takeover state machine, validates mirror/owner evidence inputs, and
prints event plans that must be appended through the CAS-backed ledger emitter.
It does not mutate GitHub, Project fields, PR bodies, comments, or the ledger.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"


class FlowError(Exception):
    """User-facing flow refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise FlowError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def parse_utc_z(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FlowError(f"{field_name} must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FlowError(f"{field_name} is not parseable: {exc}") from exc


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json_object(path: str | None, label: str) -> dict[str, Any]:
    if not path:
        raise FlowError(f"{label} JSON is required")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FlowError(f"{label} file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FlowError(f"{label} JSON invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise FlowError(f"{label} must be a JSON object")
    return data


def iter_events(ledger: Path) -> list[dict[str, Any]]:
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise FlowError(f"ledger file not found: {ledger}") from exc
    events: list[dict[str, Any]] = []
    for raw_line in lines:
        body = raw_line.strip()
        if not body:
            continue
        data = json.loads(body)
        if isinstance(data, dict):
            events.append(data)
    return events


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def session_from_payload(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def issue_matches(data: dict[str, Any], repo: str, issue: int) -> bool:
    repository = data.get("repository") or data.get("repo")
    return repository == repo and data.get("issue") == issue


def valid_replay(ledger: Path, authority_path: str) -> Any:
    authority = VERIFIER.load_authority(Path(authority_path))
    result = VERIFIER.replay(ledger, authority)
    if not result.valid:
        prefix = result.valid_prefix_hash or "GENESIS"
        raise FlowError(
            "ledger invalid; takeover/recovery fail closed "
            f"line={result.invalid_line or 'unknown'} "
            f"valid_prefix_hash=sha256:{prefix} reason={result.reason}"
        )
    return result


def latest_claim(events: list[dict[str, Any]], repo: str, issue: int, session: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for event in events:
        data = payload(event)
        if event.get("event_type") != "CLAIM_ACCEPTED":
            continue
        if not issue_matches(data, repo, issue):
            continue
        if session_from_payload(data, "session", "claim_session") != session:
            continue
        latest = event
    return latest


def latest_takeover(events: list[dict[str, Any]], repo: str, issue: int, old_session: str, new_session: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for event in events:
        if event.get("event_type") not in {"TAKEOVER_ACCEPTED", "TAKEOVER_COMMITTED", "TAKEOVER_REJECTED"}:
            continue
        data = payload(event)
        if not issue_matches(data, repo, issue):
            continue
        if data.get("old_session") == old_session and data.get("new_session") == new_session:
            latest = event
    return latest


def event_plan(event_type: str, writer_role: str, payload_value: dict[str, Any], note: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "writer_role": writer_role,
        "payload": payload_value,
        "append_with": "scripts/coordination/emit-ledger-event.sh",
        "note": note,
    }


def validate_mirror_verification(data: dict[str, Any], repo: str, issue: int, old_session: str, new_session: str) -> dict[str, Any]:
    required = {
        "issue_body_verified": True,
        "project_verified": True,
        "pr_mirrors_verified": True,
    }
    for key, expected in required.items():
        if data.get(key) is not expected:
            raise FlowError(f"mirror verification requires {key}=true")
    if data.get("repository") != repo or data.get("issue") != issue:
        raise FlowError("mirror verification repository/issue mismatch")
    if data.get("old_session") != old_session or data.get("new_session") != new_session:
        raise FlowError("mirror verification old/new session mismatch")
    parse_utc_z(data.get("verified_at"), "mirror.verified_at")
    return data


def validate_owner_approval(data: dict[str, Any], repo: str, issue: int, session: str) -> dict[str, Any]:
    if data.get("repository") != repo or data.get("issue") != issue or data.get("session") != session:
        raise FlowError("owner approval repository/issue/session mismatch")
    for key in ("approval_comment_id", "approved_by_login", "approved_by_type", "scope", "approved_until", "reason"):
        if key == "approval_comment_id":
            if not isinstance(data.get(key), int) or data.get(key) <= 0:
                raise FlowError("owner approval approval_comment_id must be a positive integer")
        elif not isinstance(data.get(key), str) or not data.get(key):
            raise FlowError(f"owner approval {key} is required")
    parse_utc_z(data["approved_until"], "owner_approval.approved_until")
    return data


def cmd_accept(args: argparse.Namespace, events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    if latest_claim(events, args.repo, args.issue, args.old_session) is None:
        raise FlowError("TAKEOVER_ACCEPTED requires an existing CLAIM_ACCEPTED for old session")
    existing = latest_takeover(events, args.repo, args.issue, args.old_session, args.new_session)
    if existing is not None and existing.get("event_type") != "TAKEOVER_REJECTED":
        raise FlowError(f"takeover already has terminal or pending event {existing.get('event_type')}")
    return [
        event_plan(
            "TAKEOVER_ACCEPTED",
            "coordinator",
            {
                "repository": args.repo,
                "issue": args.issue,
                "old_session": args.old_session,
                "new_session": args.new_session,
                "reason": args.reason,
                "accepted_at": utc_z(now),
                "old_permission": False,
                "new_permission": False,
                "state": "takeover_pending_mirror",
            },
            "append TAKEOVER_ACCEPTED first; neither old nor new session has permission until commit",
        )
    ]


def cmd_commit(args: argparse.Namespace, events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    existing = latest_takeover(events, args.repo, args.issue, args.old_session, args.new_session)
    if existing is None or existing.get("event_type") != "TAKEOVER_ACCEPTED":
        raise FlowError("TAKEOVER_COMMITTED requires latest matching takeover event to be TAKEOVER_ACCEPTED")
    mirror = validate_mirror_verification(
        load_json_object(args.mirror_verification_json, "mirror verification"),
        args.repo,
        args.issue,
        args.old_session,
        args.new_session,
    )
    return [
        event_plan(
            "TAKEOVER_COMMITTED",
            "coordinator",
            {
                "repository": args.repo,
                "issue": args.issue,
                "old_session": args.old_session,
                "new_session": args.new_session,
                "committed_at": utc_z(now),
                "state": "active_winner",
                "old_permission": False,
                "new_permission": True,
                "mirror_verification": mirror,
                "accepted_event_uuid": existing.get("event_uuid"),
            },
            "append only after issue body, Project, and PR mirrors verify",
        )
    ]


def cmd_recovery(args: argparse.Namespace, events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    approval = validate_owner_approval(load_json_object(args.owner_approval_json, "owner approval"), args.repo, args.issue, args.new_session)
    claim = latest_claim(events, args.repo, args.issue, args.new_session)
    claim_event_uuid = None if claim is None else claim.get("event_uuid")
    evidence_payload = {
        "repository": args.repo,
        "issue": args.issue,
        "session": args.new_session,
        "recorded_at": utc_z(now),
        "approval": approval,
        "claim_event_uuid": claim_event_uuid,
    }
    approved_payload = {
        "repository": args.repo,
        "issue": args.issue,
        "session": args.new_session,
        "approved_at": utc_z(now),
        "approved_until": approval["approved_until"],
        "scope": approval["scope"],
        "approval_comment_id": approval["approval_comment_id"],
        "requires_prior_owner_approval_evidence": True,
    }
    return [
        event_plan(
            "OWNER_APPROVAL_EVIDENCE",
            "coordinator",
            evidence_payload,
            "append owner approval evidence before any OWNER_APPROVED recovery grant",
        ),
        event_plan(
            "OWNER_APPROVED",
            "coordinator",
            approved_payload,
            "append only after the preceding OWNER_APPROVAL_EVIDENCE event is in the ledger",
        ),
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH))
    parser.add_argument("--phase", required=True, choices=["accept", "commit", "recovery"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--old-session", default="")
    parser.add_argument("--new-session", required=True)
    parser.add_argument("--reason", default="operator-requested takeover/recovery")
    parser.add_argument("--mirror-verification-json")
    parser.add_argument("--owner-approval-json")
    parser.add_argument("--now")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.issue <= 0:
        raise FlowError("--issue must be positive")
    if args.phase in {"accept", "commit"} and not args.old_session:
        raise FlowError("--old-session is required for takeover accept/commit")
    now = parse_utc_z(args.now, "--now") if args.now else datetime.now(timezone.utc).replace(microsecond=0)
    replay = valid_replay(args.ledger, args.authority)
    events = iter_events(args.ledger)
    if args.phase == "accept":
        plans = cmd_accept(args, events, now)
    elif args.phase == "commit":
        plans = cmd_commit(args, events, now)
    else:
        plans = cmd_recovery(args, events, now)

    print(
        json.dumps(
            {
                "ledger": str(args.ledger),
                "valid_prefix_hash": None if replay.valid_prefix_hash is None else f"sha256:{replay.valid_prefix_hash}",
                "phase": args.phase,
                "repository": args.repo,
                "issue": args.issue,
                "old_session": args.old_session or None,
                "new_session": args.new_session,
                "plans": plans,
                "mutates_github": False,
                "mutates_ledger": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except FlowError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
