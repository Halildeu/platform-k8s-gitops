#!/usr/bin/env python3
"""Validate the publication generation before the native audit job completes."""

from __future__ import annotations

import argparse
import hashlib
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
PUBLICATION_LOCK_RE = re.compile(
    r"<!-- cross-ai-publication-lock:([0-9a-f]{64}):([0-9a-f]{64}) -->"
)
CONSULTATION_COMMIT_RE = re.compile(
    r"(?mi)^Consultation commit:\s*([0-9a-f]{40})\s*$"
)
CONSULTATION_MODE_RE = re.compile(r"(?mi)^Consultation mode:\s*([^\r\n]+?)\s*$")
CODEX_RECEIPT_RE = re.compile(r"(?mi)^Codex receipt:\s*(.+?)\s*$")
RECEIPT_KEYS = frozenset({
    "provider",
    "requested",
    "actual",
    "base_tip",
    "base",
    "head",
    "scope",
    "execution",
    "verdict",
    "ref",
    "sha256",
})
PUBLICATION_CONTEXT = "cross-ai/evidence-publication"
PENDING_DESCRIPTION = "Cross-AI evidence publication awaiting trusted audit"
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


def status_history(repo: str, head: str) -> list[dict]:
    pages = gh_json([
        "--paginate",
        "--slurp",
        f"repos/{repo}/commits/{head}/statuses?per_page=100",
        "--method",
        "GET",
    ])
    return flatten_status_pages(pages)


def consultation_commit(body: str) -> str:
    matches = CONSULTATION_COMMIT_RE.findall(body)
    if len(matches) != 1:
        fail("audit_consultation_commit_invalid")
    return matches[0].lower()


def parse_selected_evidence_fields(body: str) -> dict[str, str] | None:
    matches = CODEX_RECEIPT_RE.findall(body)
    if len(matches) != 1:
        return None
    fields: dict[str, str] = {}
    for token in matches[0].split(";"):
        key, separator, value = token.strip().partition("=")
        normalized = key.strip().lower()
        if (
            not separator
            or normalized not in RECEIPT_KEYS
            or normalized in fields
            or not value.strip()
        ):
            return None
        fields[normalized] = value.strip()
    if fields.keys() != RECEIPT_KEYS:
        return None
    return fields


def selected_evidence_fields(body: str) -> dict[str, str]:
    fields = parse_selected_evidence_fields(body)
    if fields is None:
        fail("audit_selected_evidence_binding_invalid")
    return fields


def selected_evidence_binding(body: str, digest: str, repo: str) -> tuple[int, str]:
    fields = selected_evidence_fields(body)
    ref = fields.get("ref", "")
    ref_match = re.fullmatch(
        rf"https://api\.github\.com/repos/{re.escape(repo)}/issues/comments/(\d+)",
        ref,
    )
    if (
        fields.get("provider", "").lower() != "openai"
        or fields.get("verdict") != "AGREE"
        or fields.get("sha256", "").lower() != digest
        or ref_match is None
    ):
        fail("audit_selected_evidence_binding_invalid")
    return int(ref_match.group(1)), ref


def selected_evidence_snapshot(
    repo: str,
    issue: int,
    comment_id: int,
    ref: str,
    digest: str,
) -> dict:
    payload = gh_json([
        f"repos/{repo}/issues/comments/{comment_id}",
        "--method",
        "GET",
    ])
    expected_issue_url = f"https://api.github.com/repos/{repo}/issues/{issue}"
    try:
        body = payload["body"]
        author = payload["user"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        fail("audit_selected_evidence_invalid")
    owner = repo.split("/", 1)[0].lower()
    if (
        payload.get("id") != comment_id
        or payload.get("url") != ref
        or payload.get("issue_url") != expected_issue_url
        or not isinstance(body, str)
        or hashlib.sha256(body.encode("utf-8")).hexdigest() != digest
        or author != owner
        or payload.get("author_association") != "OWNER"
        or not isinstance(payload.get("created_at"), str)
        or not payload["created_at"]
        or payload.get("updated_at") != payload["created_at"]
    ):
        fail("audit_selected_evidence_invalid")
    return {
        "id": payload["id"],
        "url": payload["url"],
        "issue_url": payload["issue_url"],
        "body_sha256": digest,
        "author": author,
        "author_association": payload["author_association"],
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
    }


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
        and status.get("context") == PUBLICATION_CONTEXT
        and status.get("description") == PENDING_DESCRIPTION
        and status.get("target_url") == url
        and creator_login(status) == owner
    )


def valid_retry_pending(status: dict | None, generation: int, url: str) -> bool:
    return bool(
        status
        and status.get("state") == "pending"
        and status.get("context") == PUBLICATION_CONTEXT
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
            "context": PUBLICATION_CONTEXT,
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


def protect_live_pr_generation(repo: str, current: object, url: str) -> dict | None:
    if not isinstance(current, dict):
        return None
    try:
        head = current["head"]["sha"].lower()
        body = current.get("body") or ""
    except (KeyError, TypeError, AttributeError):
        return None
    if (
        current.get("state") != "open"
        or current.get("html_url") != url
        or SHA_RE.fullmatch(head) is None
        or not isinstance(body, str)
    ):
        return None
    markers = MARKER_RE.findall(body)
    generation = int(markers[0][0]) if len(markers) == 1 else 0
    return post_retry_pending(repo, head, url, generation)


def requires_publication_marker(body: str) -> bool:
    modes = [value.strip().lower() for value in CONSULTATION_MODE_RE.findall(body)]
    return "single" in modes or CODEX_RECEIPT_RE.search(body) is not None


def selected_comment_id(body: str, repo: str) -> int | None:
    fields = parse_selected_evidence_fields(body)
    if fields is None:
        return None
    match = re.fullmatch(
        rf"https://api\.github\.com/repos/{re.escape(repo)}/issues/comments/(\d+)",
        fields.get("ref", ""),
    )
    return int(match.group(1)) if match is not None else None


def failed_check_payload(head: str, url: str, comment_id: int, action: str) -> dict:
    external_id = f"cross-ai-evidence-comment-{comment_id}-{action}"
    return {
        "name": "cross-ai-audit",
        "head_sha": head,
        "status": "completed",
        "conclusion": "failure",
        "details_url": url,
        "external_id": external_id,
        "output": {
            "title": "Selected Cross-AI evidence changed",
            "summary": "Publish a new exact-scope review generation while the PR is draft.",
        },
    }


def valid_failed_check(
    payload: object,
    *,
    head: str,
    url: str,
    comment_id: int,
    action: str,
) -> bool:
    if not isinstance(payload, dict):
        return False
    app = payload.get("app")
    returned_head = payload.get("head_sha")
    return bool(
        isinstance(payload.get("id"), int)
        and payload.get("name") == "cross-ai-audit"
        and isinstance(returned_head, str)
        and returned_head.lower() == head
        and payload.get("status") == "completed"
        and payload.get("conclusion") == "failure"
        and payload.get("details_url") == url
        and payload.get("external_id")
        == f"cross-ai-evidence-comment-{comment_id}-{action}"
        and isinstance(app, dict)
        and app.get("slug") == "github-actions"
    )


def invalidate_selected_comment_mutation(repo: str, event_path: Path) -> dict:
    if REPO_RE.fullmatch(repo) is None or shutil.which("gh") is None:
        fail("invalid_audit_mutation_target")
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        action = event["action"]
        comment = event["comment"]
        comment_id = comment["id"]
        comment_author = comment["user"]["login"].lower()
        comment_association = comment["author_association"]
        issue = event["issue"]
        issue_number = issue["number"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("invalid_audit_mutation_event")
    if (
        action not in {"edited", "deleted"}
        or not isinstance(comment_id, int)
        or not isinstance(issue_number, int)
        or issue_number < 1
    ):
        fail("invalid_audit_mutation_event")
    if not isinstance(issue.get("pull_request"), dict):
        return {"ok": True, "action": "ignored-non-pr-comment"}

    current = gh_json([f"repos/{repo}/pulls/{issue_number}", "--method", "GET"])
    expected_url = f"https://github.com/{repo}/pull/{issue_number}"
    try:
        head = current["head"]["sha"].lower()
        body = current.get("body") or ""
    except (KeyError, TypeError, AttributeError):
        fail("github_pr_mutation_guard_invalid")
    if (
        current.get("state") != "open"
        or current.get("html_url") != expected_url
        or SHA_RE.fullmatch(head) is None
        or not isinstance(body, str)
    ):
        return {"ok": True, "action": "ignored-non-open-pr"}

    owner = repo.split("/", 1)[0].lower()
    selected_id = selected_comment_id(body, repo)
    if (
        selected_id != comment_id
        or comment_author != owner
        or comment_association != "OWNER"
    ):
        return {"ok": True, "action": "ignored-unselected-comment"}

    request = failed_check_payload(head, expected_url, comment_id, action)
    created = gh_json(
        [f"repos/{repo}/check-runs", "--method", "POST", "--input", "-"],
        input_text=json.dumps(request, separators=(",", ":")),
    )
    if not valid_failed_check(
        created,
        head=head,
        url=expected_url,
        comment_id=comment_id,
        action=action,
    ):
        fail("audit_mutation_check_invalid")
    return {
        "ok": True,
        "action": "selected-evidence-mutation-invalidated",
        "comment_action": action,
        "check_run_id": created["id"],
        "head_sha": head,
    }


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
        event_draft = event_pr["draft"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("invalid_audit_generation_event")
    expected_url = f"https://github.com/{repo}/pull/{issue}"
    if (
        event_number != issue
        or event_url != expected_url
        or SHA_RE.fullmatch(event_head) is None
        or SHA_RE.fullmatch(event_base) is None
        or not isinstance(event_draft, bool)
    ):
        fail("invalid_audit_generation_event")

    current = gh_json([f"repos/{repo}/pulls/{issue}", "--method", "GET"])
    try:
        current_head = current["head"]["sha"].lower()
        current_base = current["base"]["sha"].lower()
        current_body = current.get("body") or ""
        current_draft = current["draft"]
    except (KeyError, TypeError, AttributeError):
        fail("github_pr_generation_mismatch")
    if (
        current.get("state") != "open"
        or current.get("html_url") != expected_url
        or current_head != event_head
        or current_base != event_base
        or current_body != event_body
        or current_draft != event_draft
    ):
        protect_live_pr_generation(repo, current, expected_url)
        fail("github_pr_generation_mismatch")

    if PUBLICATION_LOCK_RE.search(event_body):
        protect_live_pr_generation(repo, current, expected_url)
        fail("audit_publication_in_progress")

    markers = MARKER_RE.findall(event_body)
    if not markers:
        if requires_publication_marker(event_body):
            fail("audit_generation_marker_missing")
        statuses = status_history(repo, event_head)
        publication_statuses = [
            status for status in statuses
            if status.get("context") == PUBLICATION_CONTEXT
            and isinstance(status.get("id"), int)
        ]
        latest_publication = max(
            publication_statuses, key=lambda status: status["id"], default=None
        )
        if latest_publication is not None and latest_publication.get("state") == "pending":
            fail("audit_generation_marker_missing")
        return {"ok": True, "action": "no-pending-generation"}
    if len(markers) != 1:
        fail("audit_generation_marker_invalid")
    pending_id, ledger_id, digest = markers[0]
    pending_status_id = int(pending_id)
    ledger_status_id = int(ledger_id)
    if pending_status_id < 1 or ledger_status_id < 1:
        fail("audit_generation_marker_incomplete")

    review_head = consultation_commit(event_body)
    comment_id, evidence_ref = selected_evidence_binding(
        event_body, digest, repo
    )
    evidence_before = selected_evidence_snapshot(
        repo, issue, comment_id, evidence_ref, digest
    )
    source_statuses = status_history(repo, review_head)
    current_statuses = (
        source_statuses if review_head == event_head else status_history(repo, event_head)
    )
    source_publication_statuses = [
        status for status in source_statuses
        if status.get("context") == PUBLICATION_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    current_publication_statuses = [
        status for status in current_statuses
        if status.get("context") == PUBLICATION_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    latest_publication = max(
        current_publication_statuses, key=lambda status: status["id"], default=None
    )

    owner = repo.split("/", 1)[0].lower()
    owner_pending = next(
        (
            status for status in source_publication_statuses
            if status.get("id") == pending_status_id
        ),
        None,
    )
    if not valid_owner_pending(owner_pending, pending_status_id, owner, expected_url):
        fail("audit_generation_owner_pending_invalid")
    ledger = next(
        (status for status in source_statuses if status.get("id") == ledger_status_id),
        None,
    )
    try:
        ledger_creator = ledger["creator"]["login"].lower()
    except (KeyError, TypeError, AttributeError):
        fail("audit_generation_ledger_invalid")
    if (
        ledger_status_id <= pending_status_id
        or ledger.get("context") != f"cross-ai/evidence/{digest}"
        or ledger.get("target_url") != expected_url
        or ledger_creator != owner
    ):
        fail("audit_generation_ledger_invalid")

    newer_source_owner_pending = [
        status for status in source_publication_statuses
        if status.get("id", 0) > pending_status_id
        and creator_login(status) == owner
        and status.get("state") == "pending"
        and status.get("description") == PENDING_DESCRIPTION
    ]
    if newer_source_owner_pending:
        next_generation = max(status["id"] for status in newer_source_owner_pending)
        post_retry_pending(repo, event_head, expected_url, next_generation)
        fail("audit_generation_superseded_before_completion")

    if latest_publication is not None and latest_publication.get("state") == "success":
        fail("audit_publication_generation_invalid")
    current_pending_valid = (
        valid_owner_pending(latest_publication, pending_status_id, owner, expected_url)
        if review_head == event_head
        else latest_publication is None
    ) or valid_retry_pending(latest_publication, pending_status_id, expected_url)
    if not current_pending_valid:
        fail("audit_generation_not_latest_pending")

    # Evidence is published only while the PR is draft. Never leave a successful
    # required check on that head: the later `ready_for_review` event must create
    # the sole merge-authoritative native check without a competing publisher.
    if event_draft:
        fail("audit_ready_for_review_required")

    # Revalidate every mutable transport input before returning. This helper
    # never writes the required merge status: its successful exit lets the
    # trusted-base GitHub Actions job complete its native `cross-ai-audit`
    # check. Publication fencing statuses use a different, non-required
    # context, so no post-validation status write can overtake a newer event.
    current_before_completion = gh_json(
        [f"repos/{repo}/pulls/{issue}", "--method", "GET"]
    )
    source_statuses_before_completion = status_history(repo, review_head)
    current_statuses_before_completion = (
        source_statuses_before_completion
        if review_head == event_head
        else status_history(repo, event_head)
    )
    source_publication_before_completion = [
        status for status in source_statuses_before_completion
        if status.get("context") == PUBLICATION_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    current_publication_before_completion = [
        status for status in current_statuses_before_completion
        if status.get("context") == PUBLICATION_CONTEXT
        and isinstance(status.get("id"), int)
    ]
    newer_owner_pending = [
        status for status in source_publication_before_completion
        if status["id"] > pending_status_id
        and status.get("state") == "pending"
        and status.get("description") == PENDING_DESCRIPTION
        and status.get("target_url") == expected_url
        and creator_login(status) == owner
    ]
    latest_current_before_completion = max(
        current_publication_before_completion,
        key=lambda status: status["id"],
        default=None,
    )
    try:
        current_before_head = current_before_completion["head"]["sha"].lower()
        current_before_base = current_before_completion["base"]["sha"].lower()
        current_before_body = current_before_completion.get("body") or ""
        current_before_draft = current_before_completion["draft"]
    except (KeyError, TypeError, AttributeError):
        current_before_head = ""
        current_before_base = ""
        current_before_body = ""
        current_before_draft = None
    final_pending_valid = (
        valid_owner_pending(
            latest_current_before_completion,
            pending_status_id,
            owner,
            expected_url,
        )
        if review_head == event_head
        else latest_current_before_completion is None
    ) or valid_retry_pending(
        latest_current_before_completion,
        pending_status_id,
        expected_url,
    )
    if (
        current_before_completion.get("state") != "open"
        or current_before_completion.get("html_url") != expected_url
        or current_before_head != event_head
        or current_before_base != event_base
        or current_before_body != event_body
        or current_before_draft is not False
        or PUBLICATION_LOCK_RE.search(current_before_body)
        or newer_owner_pending
        or not final_pending_valid
    ):
        protect_live_pr_generation(repo, current_before_completion, expected_url)
        fail("audit_generation_superseded_before_completion")
    try:
        evidence_final = selected_evidence_snapshot(
            repo, issue, comment_id, evidence_ref, digest
        )
    except SystemExit:
        protect_live_pr_generation(repo, current_before_completion, expected_url)
        fail("audit_selected_evidence_superseded_before_completion")
    if evidence_final != evidence_before:
        protect_live_pr_generation(repo, current_before_completion, expected_url)
        fail("audit_selected_evidence_superseded_before_completion")

    return {
        "ok": True,
        "action": "validated-current",
        "generation": pending_status_id,
        "ledger_status_id": ledger_status_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int)
    events = parser.add_mutually_exclusive_group(required=True)
    events.add_argument("--event-path", type=Path)
    events.add_argument("--comment-event-path", type=Path)
    args = parser.parse_args()
    if args.event_path is not None:
        if args.issue is None:
            fail("invalid_audit_generation_target")
        result = complete_status(args.repo, args.issue, args.event_path)
    else:
        if args.issue is not None:
            fail("invalid_audit_mutation_target")
        result = invalidate_selected_comment_mutation(
            args.repo, args.comment_event_path
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
