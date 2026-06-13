#!/usr/bin/env python3
"""Detect Coordination Ledger stale claims, mirror drift/orphans, and invalid suffixes.

This is a read-only reaper detector. It does not append ledger events and does
not mutate GitHub issue bodies, Project fields, PR bodies, or comments.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = Path(__file__).with_name("verify-ledger-replay.py")
DEFAULT_AUTHORITY_PATH = REPO_ROOT / "docs" / "coordination" / "ledger-event-authority-v1.json"


class ReaperError(Exception):
    """User-facing reaper refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise ReaperError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


@dataclass
class ClaimState:
    repository: str
    issue: int
    session: str
    accepted_at: datetime
    expires_at: datetime | None
    heartbeat_interval_minutes: int = 30
    heartbeat_grace_minutes: int = 45
    last_heartbeat_at: datetime | None = None
    revoked_by: str | None = None
    revoke_event_uuid: str | None = None
    source_event_uuid: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return claim_key(self.repository, self.issue, self.session)

    @property
    def heartbeat_deadline(self) -> datetime:
        base = self.last_heartbeat_at or self.accepted_at
        return base + timedelta(minutes=self.heartbeat_interval_minutes + self.heartbeat_grace_minutes)


def parse_utc_z(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReaperError(f"{field_name} must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReaperError(f"{field_name} is not parseable: {exc}") from exc


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default


def claim_key(repository: str, issue: int, session: str) -> str:
    return f"{repository}#{issue}|{session}"


def load_json_object(path: str | None, label: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReaperError(f"{label} file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReaperError(f"{label} JSON invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ReaperError(f"{label} must be a JSON object")
    return data


def iter_events(ledger: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with ledger.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                body = raw_line.strip()
                if not body:
                    continue
                data = json.loads(body)
                if isinstance(data, dict):
                    events.append(data)
    except FileNotFoundError as exc:
        raise ReaperError(f"ledger file not found: {ledger}") from exc
    except json.JSONDecodeError as exc:
        raise ReaperError(f"ledger JSONL invalid before replay: {exc}") from exc
    return events


def payload_issue(payload: dict[str, Any]) -> int | None:
    issue = payload.get("issue")
    if isinstance(issue, bool):
        return None
    if isinstance(issue, int) and issue > 0:
        return issue
    return None


def payload_repository(payload: dict[str, Any]) -> str:
    repository = payload.get("repository") or payload.get("repo")
    return repository if isinstance(repository, str) and repository else "UNKNOWN/UNKNOWN"


def payload_session(payload: dict[str, Any]) -> str | None:
    session = payload.get("session") or payload.get("claim_session")
    return session if isinstance(session, str) and session else None


def build_claim_state(event: dict[str, Any]) -> ClaimState | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    issue = payload_issue(payload)
    session = payload_session(payload)
    if issue is None or session is None:
        return None
    expires_raw = payload.get("claim_expires_at") or payload.get("expires_at")
    expires_at = parse_utc_z(expires_raw, "claim_expires_at") if expires_raw else None
    return ClaimState(
        repository=payload_repository(payload),
        issue=issue,
        session=session,
        accepted_at=parse_utc_z(event.get("committed_at"), "committed_at"),
        expires_at=expires_at,
        heartbeat_interval_minutes=safe_int(payload.get("heartbeat_interval_minutes"), 30),
        heartbeat_grace_minutes=safe_int(payload.get("heartbeat_grace_minutes"), 45),
        source_event_uuid=str(event.get("event_uuid") or ""),
        extra=payload,
    )


def derive_claims(events: list[dict[str, Any]]) -> dict[str, ClaimState]:
    claims: dict[str, ClaimState] = {}
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue

        if event_type == "CLAIM_ACCEPTED":
            claim = build_claim_state(event)
            if claim is not None:
                claims[claim.key] = claim
            continue

        issue = payload_issue(payload)
        session = payload_session(payload)
        if issue is None or session is None:
            continue
        repository = payload_repository(payload)
        key = claim_key(repository, issue, session)
        claim = claims.get(key)
        if claim is None:
            continue

        if event_type == "HEARTBEAT_EVIDENCE":
            claim.last_heartbeat_at = parse_utc_z(event.get("committed_at"), "committed_at")
        elif event_type in {"CLAIM_STALE", "CLAIM_EXPIRED", "MIRROR_DRIFT_DETECTED", "MIRROR_ORPHAN_DETECTED", "BLOCKED_FAIL_CLOSED"}:
            claim.revoked_by = str(event_type)
            claim.revoke_event_uuid = str(event.get("event_uuid") or "")
    return claims


def finding(event_type: str, reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "writer_role": "reaper",
        "reason": reason,
        "payload": payload,
    }


def detect_stale_claims(claims: dict[str, ClaimState], now: datetime) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for claim in claims.values():
        if claim.revoked_by:
            continue
        base_payload = {
            "repository": claim.repository,
            "issue": claim.issue,
            "session": claim.session,
            "detected_at": utc_z(now),
            "claim_event_uuid": claim.source_event_uuid,
        }
        if claim.expires_at is not None and now > claim.expires_at:
            payload = dict(base_payload)
            payload["claim_expires_at"] = utc_z(claim.expires_at)
            findings.append(finding("CLAIM_EXPIRED", "claim lease expired", payload))
            continue
        heartbeat_deadline = claim.heartbeat_deadline
        if now > heartbeat_deadline:
            payload = dict(base_payload)
            payload["heartbeat_deadline"] = utc_z(heartbeat_deadline)
            payload["last_heartbeat_at"] = utc_z(claim.last_heartbeat_at or claim.accepted_at)
            findings.append(finding("CLAIM_STALE", "heartbeat deadline passed", payload))
    return findings


def mirror_issue_records(mirror: dict[str, Any]) -> list[dict[str, Any]]:
    records = mirror.get("issues", [])
    if not isinstance(records, list):
        raise ReaperError("mirror.issues must be a list")
    return [item for item in records if isinstance(item, dict)]


def mirror_comment_records(mirror: dict[str, Any]) -> list[dict[str, Any]]:
    records = mirror.get("comments", [])
    if not isinstance(records, list):
        raise ReaperError("mirror.comments must be a list")
    return [item for item in records if isinstance(item, dict)]


def detect_mirror_findings(
    *,
    claims: dict[str, ClaimState],
    events: list[dict[str, Any]],
    mirror: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    latest_by_issue: dict[str, ClaimState] = {}
    for claim in claims.values():
        issue_key = f"{claim.repository}#{claim.issue}"
        latest = latest_by_issue.get(issue_key)
        if latest is None or claim.accepted_at >= latest.accepted_at:
            latest_by_issue[issue_key] = claim

    for item in mirror_issue_records(mirror):
        repository = item.get("repository") or item.get("repo")
        issue = item.get("issue")
        status = item.get("status")
        session = item.get("claim_session") or item.get("session")
        if not isinstance(repository, str) or not repository or not isinstance(issue, int) or issue <= 0:
            continue
        if not isinstance(status, str):
            status = ""
        if not isinstance(session, str):
            session = ""

        issue_key = f"{repository}#{issue}"
        latest = latest_by_issue.get(issue_key)
        if status == "In Progress" and latest is None:
            findings.append(
                finding(
                    "MIRROR_ORPHAN_DETECTED",
                    "mirror In Progress has no ledger claim",
                    {
                        "repository": repository,
                        "issue": issue,
                        "mirror_status": status,
                        "mirror_session": session,
                        "detected_at": utc_z(now),
                    },
                )
            )
            continue
        if latest is None:
            continue
        drift = []
        if status != "In Progress":
            drift.append(f"status={status or '<empty>'}")
        if session and session != latest.session:
            drift.append(f"session={session}")
        if drift:
            findings.append(
                finding(
                    "MIRROR_DRIFT_DETECTED",
                    "mirror does not match latest ledger claim",
                    {
                        "repository": repository,
                        "issue": issue,
                        "ledger_session": latest.session,
                        "mirror_status": status,
                        "mirror_session": session,
                        "drift": drift,
                        "detected_at": utc_z(now),
                    },
                )
            )

    bound_comments: set[tuple[str, int, int]] = set()
    for event in events:
        binding = event.get("comment_binding")
        if not isinstance(binding, dict):
            continue
        repository = binding.get("repository")
        issue = binding.get("issue")
        comment_id = binding.get("comment_id")
        if isinstance(repository, str) and isinstance(issue, int) and isinstance(comment_id, int):
            bound_comments.add((repository, issue, comment_id))

    for comment in mirror_comment_records(mirror):
        repository = comment.get("repository") or comment.get("repo")
        issue = comment.get("issue")
        comment_id = comment.get("comment_id") or comment.get("id")
        if not isinstance(repository, str) or not isinstance(issue, int) or not isinstance(comment_id, int):
            continue
        if (repository, issue, comment_id) not in bound_comments:
            findings.append(
                finding(
                    "ORPHAN_COMMENT_DETECTED",
                    "materialized comment is not bound by any valid ledger event",
                    {
                        "repository": repository,
                        "issue": issue,
                        "comment_id": comment_id,
                        "detected_at": utc_z(now),
                    },
                )
            )
    return findings


def audit_debt_summary(path: str | None, limit: int) -> dict[str, Any]:
    if not path:
        return {"present": False, "total": 0, "unique": 0, "duplicates": 0, "bounded": True}
    debt_path = Path(path)
    if not debt_path.exists():
        return {"present": False, "total": 0, "unique": 0, "duplicates": 0, "bounded": True}

    total = 0
    unique: dict[str, dict[str, Any]] = {}
    invalid = 0
    with debt_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if total >= limit:
                break
            body = raw_line.strip()
            if not body:
                continue
            total += 1
            try:
                item = json.loads(body)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if not isinstance(item, dict):
                invalid += 1
                continue
            intent_id = item.get("deny_event_intent_id") or item.get("intent", {}).get("deny_event_intent_id")
            if not isinstance(intent_id, str) or not intent_id:
                invalid += 1
                continue
            unique.setdefault(intent_id, item)
    return {
        "present": True,
        "total": total,
        "unique": len(unique),
        "duplicates": max(total - invalid - len(unique), 0),
        "invalid": invalid,
        "bounded": total <= limit,
        "limit": limit,
        "retry_supported": True,
        "retry_command": "python3 scripts/coordination/retry-audit-debt.py",
    }


def invalid_suffix_report(args: argparse.Namespace, replay_result: Any, now: datetime) -> dict[str, Any]:
    prefix = replay_result.valid_prefix_hash
    prefix_label = None if prefix is None else f"sha256:{prefix}"
    return {
        "ledger": str(args.ledger),
        "valid": False,
        "fail_closed": True,
        "valid_events": replay_result.valid_events,
        "valid_prefix_hash": prefix_label,
        "invalid_line": replay_result.invalid_line,
        "reason": replay_result.reason,
        "findings": [
            finding(
                "LEDGER_INVALID_SUFFIX",
                "ledger replay found invalid suffix; coordination must fail closed",
                {
                    "ledger": str(args.ledger),
                    "valid_prefix_hash": prefix_label,
                    "invalid_line": replay_result.invalid_line,
                    "invalid_reason": replay_result.reason,
                    "detected_at": utc_z(now),
                },
            )
        ],
        "audit_debt": audit_debt_summary(args.audit_debt_jsonl, args.audit_debt_limit),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path, help="Coordination ledger JSONL path")
    parser.add_argument("--mirror-json", help="optional mirror snapshot JSON fixture")
    parser.add_argument("--audit-debt-jsonl", help="optional local audit debt JSONL")
    parser.add_argument("--audit-debt-limit", type=int, default=200, help="max audit debt records to scan")
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), help="event authority fixture path")
    parser.add_argument("--now", help="ISO-8601 UTC timestamp ending in Z; defaults to current time")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.audit_debt_limit <= 0:
        raise ReaperError("--audit-debt-limit must be positive")
    now = parse_utc_z(args.now, "--now") if args.now else datetime.now(timezone.utc).replace(microsecond=0)
    authority = VERIFIER.load_authority(Path(args.authority))
    replay_result = VERIFIER.replay(args.ledger, authority)

    if not replay_result.valid:
        print(json.dumps(invalid_suffix_report(args, replay_result, now), sort_keys=True))
        return 2

    events = iter_events(args.ledger)
    claims = derive_claims(events)
    mirror = load_json_object(args.mirror_json, "mirror")
    findings = detect_stale_claims(claims, now)
    findings.extend(detect_mirror_findings(claims=claims, events=events, mirror=mirror, now=now))

    print(
        json.dumps(
            {
                "ledger": str(args.ledger),
                "valid": True,
                "fail_closed": False,
                "valid_events": replay_result.valid_events,
                "valid_prefix_hash": (
                    None if replay_result.valid_prefix_hash is None else f"sha256:{replay_result.valid_prefix_hash}"
                ),
                "claims_seen": len(claims),
                "findings": findings,
                "audit_debt": audit_debt_summary(args.audit_debt_jsonl, args.audit_debt_limit),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ReaperError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
