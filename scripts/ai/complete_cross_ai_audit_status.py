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


def complete_status(repo: str, issue: int, event_path: Path) -> dict:
    if REPO_RE.fullmatch(repo) is None or issue < 1 or shutil.which("gh") is None:
        fail("invalid_audit_generation_target")
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event_pr = event["pull_request"]
        event_head = event_pr["head"]["sha"].lower()
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
    ):
        fail("invalid_audit_generation_event")

    current = gh_json([f"repos/{repo}/pulls/{issue}", "--method", "GET"])
    try:
        current_head = current["head"]["sha"].lower()
        current_body = current.get("body") or ""
    except (KeyError, TypeError, AttributeError):
        fail("github_pr_generation_mismatch")
    if (
        current.get("state") != "open"
        or current.get("html_url") != expected_url
        or current_head != event_head
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
        try:
            success_creator = latest_audit["creator"]["login"].lower()
        except (KeyError, TypeError, AttributeError):
            fail("audit_generation_success_invalid")
        if (
            latest_audit.get("description") != success_description
            or latest_audit.get("target_url") != expected_url
            or latest_audit["id"] <= pending_status_id
            or success_creator != owner
        ):
            fail("audit_generation_success_invalid")
        return {
            "ok": True,
            "action": "already-current",
            "generation": pending_status_id,
            "status_id": latest_audit["id"],
        }
    try:
        latest_creator = latest_audit["creator"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        fail("audit_generation_not_latest_pending")
    if (
        latest_audit.get("state") != "pending"
        or latest_audit["id"] != pending_status_id
        or latest_audit.get("description") != PENDING_DESCRIPTION
        or latest_audit.get("target_url") != expected_url
        or latest_creator != owner
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
        or created_creator != owner
    ):
        fail("audit_success_status_invalid")
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
