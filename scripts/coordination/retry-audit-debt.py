#!/usr/bin/env python3
"""Retry local Coordination Ledger audit-debt records through remote CAS.

`board-sync record-deny` intentionally queues a local append-only
`coordination-audit-debt/v1` record and returns nonzero while mutation remains
blocked. This helper is the post-CAS retry path: it converts bounded,
deduplicated local debt into ledger-backed `DENY_RECORDED` events by calling
the existing mirror-safe emitter.

The local queue remains append-only. Successful retry appends a terminal marker
to the same queue instead of editing historical debt records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EMITTER = REPO_ROOT / "scripts" / "coordination" / "emit-ledger-event.sh"
DEFAULT_VERIFIER = REPO_ROOT / "scripts" / "coordination" / "verify-ledger-replay.py"
DEFAULT_QUEUE = Path(".local/coordination-audit-debt.jsonl")
DEFAULT_LEDGER_PATH = "coordination-ledger/events.jsonl"
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
ISSUE_REF_RE = re.compile(r"^(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$")
MAX_DETAILS_JSON_CHARS = 12000


class RetryError(Exception):
    """User-facing retry refusal."""


def utc_now_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def run_json(args: list[str], *, cwd: Path | None = None) -> Any:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RetryError(result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RetryError(f"command returned invalid JSON: {' '.join(args)}: {exc}") from exc


def run_text(args: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RetryError(result.stderr.strip() or result.stdout.strip() or f"command failed: {' '.join(args)}")
    return result.stdout


def require_intent(record: dict[str, Any]) -> dict[str, Any]:
    intent = record.get("intent")
    if not isinstance(intent, dict):
        raise RetryError("audit debt record missing intent object")
    if intent.get("allowed") is not False:
        raise RetryError("audit debt intent must have allowed=false")
    intent_id = intent.get("deny_event_intent_id")
    if not isinstance(intent_id, str) or not HASH_RE.fullmatch(intent_id):
        raise RetryError("audit debt intent has invalid deny_event_intent_id")
    for field in ("deny_code", "issue", "session", "operation"):
        if not isinstance(intent.get(field), str) or not intent[field]:
            raise RetryError(f"audit debt intent missing non-empty {field}")
    return intent


def parse_issue_ref(issue_ref: str) -> tuple[str, int]:
    match = ISSUE_REF_RE.fullmatch(issue_ref)
    if not match:
        raise RetryError(f"intent.issue must be owner/repo#number, got {issue_ref!r}")
    return match.group("repo"), int(match.group("number"))


def bounded_details(value: Any) -> Any:
    try:
        encoded = canonical_json(value)
    except TypeError:
        return [{"code": "details_unserializable", "message": "details were not JSON-serializable"}]
    if len(encoded) <= MAX_DETAILS_JSON_CHARS:
        return value
    return [
        {
            "code": "details_truncated",
            "message": f"details exceeded {MAX_DETAILS_JSON_CHARS} canonical JSON characters",
        }
    ]


def event_uuid_for_intent(intent_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"coordination-ledger:DENY_RECORDED:{intent_id}"))


def build_payload(record: dict[str, Any]) -> dict[str, Any]:
    intent = require_intent(record)
    repository, issue_number = parse_issue_ref(intent["issue"])
    intent_id = intent["deny_event_intent_id"]
    return {
        "repository": repository,
        "issue": issue_number,
        "issue_ref": intent["issue"],
        "session": intent["session"],
        "operation": intent["operation"],
        "deny_code": intent["deny_code"],
        "deny_event_intent_id": intent_id,
        "permission_source": intent.get("permission_source"),
        "details": bounded_details(intent.get("details", [])),
        "queued_at": record.get("queued_at"),
        "retry_source": "coordination-audit-debt/v1",
    }


def load_queue(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if len(records) >= limit:
                break
            body = raw_line.strip()
            if not body:
                continue
            try:
                item = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def terminal_ids(records: list[dict[str, Any]]) -> set[str]:
    emitted: set[str] = set()
    for item in records:
        if item.get("schemaVersion") != "coordination-audit-debt/v1":
            continue
        if item.get("status") not in {"ledger_emitted", "already_in_ledger"}:
            continue
        intent_id = item.get("deny_event_intent_id")
        if isinstance(intent_id, str):
            emitted.add(intent_id)
    return emitted


def pending_records(records: list[dict[str, Any]], already_terminal: set[str]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in records:
        if item.get("schemaVersion") != "coordination-audit-debt/v1":
            continue
        if item.get("status") != "blocked_audit_debt":
            continue
        try:
            intent = require_intent(item)
            build_payload(item)
        except RetryError:
            continue
        intent_id = intent["deny_event_intent_id"]
        if intent_id in seen or intent_id in already_terminal:
            continue
        seen.add(intent_id)
        pending.append(item)
    return pending


def checkout_ledger(remote: str, branch: str, ledger_path: str, verifier: Path) -> tuple[str, set[str]]:
    with tempfile.TemporaryDirectory(prefix="coordination-audit-debt-ledger.") as tmp:
        checkout = Path(tmp) / "ledger"
        result = subprocess.run(
            ["git", "clone", "--quiet", "--branch", branch, "--single-branch", remote, str(checkout)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RetryError(result.stderr.strip() or f"failed to clone ledger branch {branch!r}")

        ledger_file = checkout / ledger_path
        replay = run_json(["python3", str(verifier), "--json", str(ledger_file)])
        if not isinstance(replay, list) or not replay:
            raise RetryError("verifier returned empty replay result")
        result0 = replay[0]
        if not result0.get("valid"):
            raise RetryError(
                "existing_ledger_invalid "
                f"line={result0.get('invalid_line')} reason={result0.get('reason')}"
            )
        prefix = result0.get("valid_prefix_hash")
        expect_previous_hash = "GENESIS" if prefix in (None, "GENESIS") else f"sha256:{prefix}"

        emitted: set[str] = set()
        if ledger_file.exists():
            with ledger_file.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    body = raw_line.strip()
                    if not body:
                        continue
                    try:
                        event = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict) or event.get("event_type") != "DENY_RECORDED":
                        continue
                    payload = event.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    intent_id = payload.get("deny_event_intent_id")
                    if isinstance(intent_id, str) and intent_id:
                        emitted.add(intent_id)
        return expect_previous_hash, emitted


def append_terminal_marker(
    *,
    queue: Path,
    status: str,
    reason: str,
    intent_id: str,
    event_uuid: str | None = None,
    event_hash: str | None = None,
    emitted_at: str | None = None,
    remote: str | None = None,
    branch: str | None = None,
) -> None:
    queue.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "schemaVersion": "coordination-audit-debt/v1",
        "recorded_at": utc_now_z(),
        "status": status,
        "reason": reason,
        "source": "coordination-audit-debt-retry-v1",
        "queue_path": str(queue),
        "deny_event_intent_id": intent_id,
    }
    if event_uuid:
        record["event_uuid"] = event_uuid
    if event_hash:
        record["event_hash"] = event_hash
    if emitted_at:
        record["emitted_at"] = emitted_at
    if remote:
        record["remote"] = remote
    if branch:
        record["branch"] = branch
    with queue.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(record) + "\n")


def make_plan(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for record in records:
        payload = build_payload(record)
        intent_id = payload["deny_event_intent_id"]
        planned.append(
            {
                "deny_event_intent_id": intent_id,
                "repository": payload["repository"],
                "issue": payload["issue"],
                "event_uuid": event_uuid_for_intent(intent_id),
                "event_type": "DENY_RECORDED",
                "writer_role": "coordinator",
                "payload_hash": sha256_payload(payload),
                "payload": payload,
            }
        )
    return planned


def emit_one(args: argparse.Namespace, planned: dict[str, Any], expect_previous_hash: str) -> dict[str, Any]:
    intent_id = planned["deny_event_intent_id"]
    cmd = [
        "bash",
        str(args.emitter),
        "--repo",
        planned["repository"],
        "--issue",
        str(planned["issue"]),
        "--remote",
        args.remote,
        "--branch",
        args.branch,
        "--ledger-path",
        args.ledger_path,
        "--commit-title",
        "coordination ledger DENY_RECORDED retry",
        "--commit-message",
        f"Tracked by #{args.tracked_by}",
        "--expect-previous-hash",
        expect_previous_hash,
        "--event-uuid",
        planned["event_uuid"],
        "--event-type",
        "DENY_RECORDED",
        "--writer-role",
        "coordinator",
        "--committed-at",
        args.committed_at,
        "--payload-json",
        canonical_json(planned["payload"]),
    ]
    if args.post_comment:
        cmd.append("--post-comment")
    else:
        comment_json = Path(args.comment_json_dir) / f"{intent_id}.json"
        cmd.extend(["--comment-json", str(comment_json)])

    return run_json(cmd)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE), help="coordination-audit-debt JSONL queue")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="coordination-ledger")
    parser.add_argument("--ledger-path", default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--tracked-by", default="1526", help="issue number for ledger commit message")
    parser.add_argument("--committed-at", default=utc_now_z())
    parser.add_argument("--emitter", type=Path, default=DEFAULT_EMITTER)
    parser.add_argument("--verifier", type=Path, default=DEFAULT_VERIFIER)
    parser.add_argument("--plan-only", action="store_true", help="emit retry plan JSON without mutating")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--post-comment", action="store_true", help="create real GitHub materialized comments")
    mode.add_argument("--comment-json-dir", help="offline fixture directory keyed by deny_event_intent_id")
    args = parser.parse_args(argv)

    if args.limit <= 0:
        raise RetryError("--limit must be positive")
    if not args.emitter.exists():
        raise RetryError(f"emitter not found: {args.emitter}")
    if not args.verifier.exists():
        raise RetryError(f"verifier not found: {args.verifier}")
    if args.comment_json_dir and not Path(args.comment_json_dir).is_dir():
        raise RetryError(f"--comment-json-dir must exist: {args.comment_json_dir}")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    queue = Path(args.queue)
    records = load_queue(queue, args.limit)
    terminal = terminal_ids(records)
    pending = pending_records(records, terminal)
    expect_previous_hash, already_emitted = checkout_ledger(
        args.remote, args.branch, args.ledger_path, args.verifier
    )
    skipped_already = [record for record in pending if require_intent(record)["deny_event_intent_id"] in already_emitted]
    actionable = [
        record for record in pending
        if require_intent(record)["deny_event_intent_id"] not in already_emitted
    ]
    plan = make_plan(actionable)

    if args.plan_only:
        print(
            json.dumps(
                {
                    "queue": str(queue),
                    "pending_total": len(pending),
                    "already_in_ledger": len(skipped_already),
                    "to_emit": plan,
                    "expect_previous_hash": expect_previous_hash,
                    "post_comment": args.post_comment,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    for record in skipped_already:
        intent = require_intent(record)
        append_terminal_marker(
            queue=queue,
            status="already_in_ledger",
            reason="deny_recorded_event_already_present",
            intent_id=intent["deny_event_intent_id"],
            remote=args.remote,
            branch=args.branch,
        )

    emitted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    current_expect = expect_previous_hash
    for item in plan:
        try:
            result = emit_one(args, item, current_expect)
        except RetryError as exc:
            failed.append({"deny_event_intent_id": item["deny_event_intent_id"], "error": str(exc)})
            break

        append_result = result.get("branch_append", {}).get("append", {})
        event_hash = append_result.get("event_hash")
        current_expect = append_result.get("valid_prefix_hash") or event_hash or current_expect
        append_terminal_marker(
            queue=queue,
            status="ledger_emitted",
            reason="cas_backed_deny_recorded",
            intent_id=item["deny_event_intent_id"],
            event_uuid=item["event_uuid"],
            event_hash=event_hash,
            emitted_at=result.get("committed_at"),
            remote=args.remote,
            branch=args.branch,
        )
        emitted.append(result)

    print(
        json.dumps(
            {
                "queue": str(queue),
                "pending_total": len(pending),
                "already_in_ledger": len(skipped_already),
                "emitted": len(emitted),
                "failed": failed,
                "remaining_unattempted": max(len(plan) - len(emitted) - len(failed), 0),
                "status": "ok" if not failed else "partial_fail_closed",
                "results": emitted,
            },
            sort_keys=True,
        )
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except RetryError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
