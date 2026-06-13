#!/usr/bin/env python3
"""Plan Coordination Ledger tombstone and supersede events.

This helper is read-only. It validates the existing ledger and required mirror
evidence, then emits event plans that must be appended through
`emit-ledger-event.sh`. It never mutates GitHub, Project fields, PR bodies,
comments, or the ledger.
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


class TombstoneFlowError(Exception):
    """User-facing flow refusal."""


def load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("coordination_ledger_replay", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise TombstoneFlowError(f"failed to load verifier module from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier_module()


def parse_utc_z(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TombstoneFlowError(f"{field} must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TombstoneFlowError(f"{field} is not parseable: {exc}") from exc


def utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def valid_replay(ledger: Path, authority_path: Path) -> Any:
    authority = VERIFIER.load_authority(authority_path)
    result = VERIFIER.replay(ledger, authority)
    if not result.valid:
        raise TombstoneFlowError(
            "ledger invalid; tombstone/supersede flow fail closed "
            f"line={result.invalid_line} reason={result.reason}"
        )
    return result


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


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def issue_has_ledger_activity(events: list[dict[str, Any]], repo: str, issue: int) -> bool:
    for event in events:
        data = payload(event)
        repository = data.get("repository") or data.get("repo")
        if repository == repo and data.get("issue") == issue:
            return True
    return False


def require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TombstoneFlowError(f"{field} must be a positive integer")
    return value


def load_json_object(path: str | None, label: str) -> dict[str, Any]:
    if not path:
        raise TombstoneFlowError(f"{label} JSON is required")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TombstoneFlowError(f"{label} must be a JSON object")
    return data


def validate_mirror_verification(data: dict[str, Any], repo: str, issue: int, new_issue: int) -> dict[str, Any]:
    if data.get("repository") != repo:
        raise TombstoneFlowError("mirror verification repository mismatch")
    if data.get("issue") != issue or data.get("superseded_by_issue") != new_issue:
        raise TombstoneFlowError("mirror verification old/new issue mismatch")
    for key in ("issue_body_verified", "project_verified", "pr_mirrors_verified"):
        if data.get(key) is not True:
            raise TombstoneFlowError(f"mirror verification requires {key}=true")
    parse_utc_z(data.get("verified_at"), "mirror_verification.verified_at")
    return data


def event_plan(event_type: str, payload_value: dict[str, Any], note: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "writer_role": "coordinator",
        "payload": payload_value,
        "append_with": "scripts/coordination/emit-ledger-event.sh",
        "note": note,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), type=Path)
    parser.add_argument("--phase", choices=("tombstone", "supersede"), required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int, help="old/superseded issue number")
    parser.add_argument("--new-issue", type=int, help="superseding issue number")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--mirror-verification-json")
    parser.add_argument("--now")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        now = parse_utc_z(args.now, "--now") if args.now else datetime.now(timezone.utc).replace(microsecond=0)
        valid_replay(args.ledger, args.authority)
        events = read_events(args.ledger)
        if not issue_has_ledger_activity(events, args.repo, args.issue):
            raise TombstoneFlowError("issue has no ledger activity to tombstone or supersede")

        if args.phase == "tombstone":
            plans = [
                event_plan(
                    "TOMBSTONE_CHAIN",
                    {
                        "repository": args.repo,
                        "issue": args.issue,
                        "reason": args.reason,
                        "tombstoned_at": utc_z(now),
                        "permission": False,
                        "state": "tombstoned",
                    },
                    "append TOMBSTONE_CHAIN to prevent the old issue chain from granting permission",
                )
            ]
        else:
            new_issue = require_positive_int(args.new_issue, "--new-issue")
            if new_issue == args.issue:
                raise TombstoneFlowError("--new-issue must differ from --issue")
            mirror = validate_mirror_verification(
                load_json_object(args.mirror_verification_json, "mirror verification"),
                args.repo,
                args.issue,
                new_issue,
            )
            plans = [
                event_plan(
                    "SUPERSEDE_ISSUE",
                    {
                        "repository": args.repo,
                        "issue": args.issue,
                        "superseded_by_issue": new_issue,
                        "reason": args.reason,
                        "superseded_at": utc_z(now),
                        "old_permission": False,
                        "new_issue_claim_required": True,
                        "mirror_verification": mirror,
                        "state": "superseded",
                    },
                    "append only after issue body, Project, and PR mirrors point at the superseding issue",
                )
            ]

        print(json.dumps({"status": "planned", "permission_granted": False, "plans": plans}, sort_keys=True))
        return 0
    except (TombstoneFlowError, json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "refused_fail_closed",
                    "permission_granted": False,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
