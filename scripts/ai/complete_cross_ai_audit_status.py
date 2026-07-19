#!/usr/bin/env python3
"""Clear a Cross-AI pending status only for the audited PR body generation."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
MARKER_RE = re.compile(
    r"<!-- cross-ai-audit-recheck:(\d+):(\d+):([0-9a-f]{64}) -->"
)
AUDIT_CONTEXT = "cross-ai-audit"
PENDING_DESCRIPTION = "Cross-AI evidence changed; trusted audit required"
TRUSTED_WORKFLOW_STATUS_CREATOR = "github-actions[bot]"
RETRY_DESCRIPTION_PREFIX = "Cross-AI audit retry required generation="


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def gh_json(
    arguments: list[str],
    *,
    input_text: str | None = None,
) -> object:
    try:
        result = subprocess.run(
            ["gh", "api", *arguments],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("github_audit_generation_unverifiable")
    if result.returncode != 0:
        fail("github_audit_generation_unverifiable")
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        fail("github_audit_generation_unverifiable")


def flatten_status_pages(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        fail("github_audit_status_history_invalid")
    pages = payload if all(isinstance(item, list) for item in payload) else [payload]
    statuses: list[dict] = []
    for page in pages:
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            fail("github_audit_status_history_invalid")
        statuses.extend(page)
    return statuses


def creator_login(status: dict | None) -> str:
    try:
        return status["creator"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        return ""


def valid_owner_pending(status: dict | None, generation: int, owner: str, url: str) -> bool:
    return bool(
        status
        and status.get("id") == generation
        and status.get("state") == "pending"
        and status.get("context") == AUDIT_CONTEXT
        and status.get("description") == PENDING_DESCRIPTION
        and status.get("target_url") == url
        and creator_login(status) == owner
    )


def valid_retry_pending(status: dict | None, generation: int, url: str) -> bool:
    return bool(
        status
        and status.get("state") == "pending"
        and status.get("context") == AUDIT_CONTEXT
        and status.get("description") == f"{RETRY_DESCRIPTION_PREFIX}{generation}"
        and status.get("target_url") == url
        and creator_login(status) == TRUSTED_WORKFLOW_STATUS_CREATOR
        and isinstance(status.get("id"), int)
        and status["id"] > generation
    )


def post_retry_pending(repo: str, head: str, url: str, generation: int) -> dict:
    payload = json.dumps(
        {
            "state": "pending",
            "context": AUDIT_CONTEXT,
            "description": f"{RETRY_DESCRIPTION_PREFIX}{generation}",
            "target_url": url,
        },
        separators=(",", ":"),
    )
    created = gh_json(
        [f"repos/{repo}/statuses/{head}", "--method", "POST", "--input", "-"],
        input_text=payload,
    )
    if not valid_retry_pending(created, generation, url):
        fail("audit_retry_status_invalid")
    return created


def complete_status(repo: str, issue: int, event_path: Path) -> dict:
    if REPO_RE.fullmatch(repo) is None or issue < 1 or shutil.which("gh") is None:
        fail("invalid_audit_generation_target")
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event_pr = event["pull_request"]
        event_head = event_pr["head"]["sha"].lower()
        event_base = event_pr["base"]["sha"].lower()
        event_body = event_pr.get("body") or ""
        event_url = event_pr["html_url"]
        event_number = event_pr["number"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("invalid_audit_generation_event")
    expected_url = f"https://github.com/{repo}/pull/{issue}"
    if (
        event_number != issue
        or event_url != expected_url
        or SHA_RE.fullmatch(event_head) is None
        or SHA_RE.fullmatch(event_base) is None
    ):
        fail("invalid_audit_generation_event")

    current = gh_json([f"repos/{repo}/pulls/{issue}", "--method", "GET"])
    try:
        current_head = current["head"]["sha"].lower()
        current_base = current["base"]["sha"].lower()
        current_body = current.get("body") or ""
    except (KeyError, TypeError, AttributeError):
        fail("github_pr_generation_mismatch")
    if (
        current.get("state") != "open"
        or current.get("html_url") != expected_url
        or current_head != event_head
        or current_base != event_base
        or current_body != event_body
    ):
        fail("github_pr_generation_mismatch")

    pages = gh_json([
        "--paginate",
        "--slurp",
        f"repos/{repo}/commits/{event_head}/statuses?per_page=100",
        "--method",
        "GET",
    ])
    statuses = flatten_status_pages(pages)
    audit_statuses = [
        status for status in statuses
        if status.get("context") == AUDIT_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    latest_audit = max(audit_statuses, key=lambda status: status["id"], default=None)
    markers = MARKER_RE.findall(event_body)
    if not markers:
        if latest_audit is not None and latest_audit.get("state") == "pending":
            fail("audit_generation_marker_missing")
        return {"ok": True, "action": "no-pending-generation"}
    if len(markers) != 1:
        fail("audit_generation_marker_invalid")
    pending_id, ledger_id, digest = markers[0]
    pending_status_id = int(pending_id)
    ledger_status_id = int(ledger_id)
    if pending_status_id < 1 or ledger_status_id < 1:
        fail("audit_generation_marker_incomplete")

    owner = repo.split("/", 1)[0].lower()
    owner_pending = next(
        (status for status in audit_statuses if status.get("id") == pending_status_id),
        None,
    )
    if not valid_owner_pending(owner_pending, pending_status_id, owner, expected_url):
        fail("audit_generation_owner_pending_invalid")
    ledger = next(
        (status for status in statuses if status.get("id") == ledger_status_id),
        None,
    )
    try:
        ledger_creator = ledger["creator"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        fail("audit_generation_ledger_invalid")
    if (
        ledger.get("context") != f"cross-ai/evidence/{digest}"
        or ledger.get("target_url") != expected_url
        or ledger_creator != owner
    ):
        fail("audit_generation_ledger_invalid")

    success_description = f"Trusted Cross-AI audit passed generation={pending_status_id}"
    if latest_audit is not None and latest_audit.get("state") == "success":
        success_creator = creator_login(latest_audit)
        newer_owner_pending = [
            status for status in audit_statuses
            if status.get("id", 0) > pending_status_id
            and creator_login(status) == owner
            and status.get("state") == "pending"
            and status.get("description") == PENDING_DESCRIPTION
        ]
        if newer_owner_pending:
            next_generation = max(status["id"] for status in newer_owner_pending)
            post_retry_pending(repo, event_head, expected_url, next_generation)
            fail("audit_generation_superseded_after_success")
        if (
            latest_audit.get("description") != success_description
            or latest_audit.get("target_url") != expected_url
            or latest_audit["id"] <= pending_status_id
            or success_creator != TRUSTED_WORKFLOW_STATUS_CREATOR
        ):
            fail("audit_generation_success_invalid")
        return {
            "ok": True,
            "action": "already-current",
            "generation": pending_status_id,
            "status_id": latest_audit["id"],
        }
    if not (
        valid_owner_pending(latest_audit, pending_status_id, owner, expected_url)
        or valid_retry_pending(latest_audit, pending_status_id, expected_url)
    ):
        fail("audit_generation_not_latest_pending")

    payload = json.dumps(
        {
            "state": "success",
            "context": AUDIT_CONTEXT,
            "description": success_description,
            "target_url": expected_url,
        },
        separators=(",", ":"),
    )
    created = gh_json(
        [f"repos/{repo}/statuses/{event_head}", "--method", "POST", "--input", "-"],
        input_text=payload,
    )
    try:
        created_creator = created["creator"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        fail("audit_success_status_invalid")
    if (
        not isinstance(created.get("id"), int)
        or created["id"] <= pending_status_id
        or created.get("state") != "success"
        or created.get("context") != AUDIT_CONTEXT
        or created.get("description") != success_description
        or created.get("target_url") != expected_url
        or created_creator != TRUSTED_WORKFLOW_STATUS_CREATOR
    ):
        fail("audit_success_status_invalid")

    current_after = gh_json([f"repos/{repo}/pulls/{issue}", "--method", "GET"])
    pages_after = gh_json([
        "--paginate",
        "--slurp",
        f"repos/{repo}/commits/{event_head}/statuses?per_page=100",
        "--method",
        "GET",
    ])
    statuses_after = flatten_status_pages(pages_after)
    audit_after = [
        status for status in statuses_after
        if status.get("context") == AUDIT_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    newer_owner_pending = [
        status for status in audit_after
        if status["id"] > pending_status_id
        and status.get("state") == "pending"
        and status.get("description") == PENDING_DESCRIPTION
        and status.get("target_url") == expected_url
        and creator_login(status) == owner
    ]
    try:
        current_after_head = current_after["head"]["sha"].lower()
        current_after_base = current_after["base"]["sha"].lower()
        current_after_body = current_after.get("body") or ""
    except (KeyError, TypeError, AttributeError):
        current_after_head = ""
        current_after_base = ""
        current_after_body = ""
    superseded = bool(
        current_after.get("state") != "open"
        or current_after_head != event_head
        or current_after_base != event_base
        or current_after_body != event_body
        or newer_owner_pending
    )
    if superseded:
        marker_matches = MARKER_RE.findall(current_after_body)
        next_generation = pending_status_id
        if len(marker_matches) == 1:
            candidate = int(marker_matches[0][0])
            if any(valid_owner_pending(status, candidate, owner, expected_url) for status in audit_after):
                next_generation = candidate
        elif newer_owner_pending:
            next_generation = max(status["id"] for status in newer_owner_pending)
        post_retry_pending(repo, event_head, expected_url, next_generation)
        fail("audit_generation_superseded_after_success")
    return {
        "ok": True,
        "action": "marked-current",
        "generation": pending_status_id,
        "status_id": created["id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    args = parser.parse_args()
    result = complete_status(args.repo, args.issue, args.event_path)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
