#!/usr/bin/env python3
"""Validate and post one Cross-AI evidence comment without exposing its body.

The GitHub token stays inside the authenticated ``gh`` process. The evidence
body is sent over stdin, never argv, and this helper prints only the API ref,
timestamps and content digest required by the PR receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NoReturn


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RECHECK_MARKER_RE = re.compile(
    r"(?:\n\n)?<!-- cross-ai-audit-recheck:\d+(?::\d+)?:[0-9a-f]{64} -->\n?"
)
PUBLICATION_LOCK_RE = re.compile(
    r"(?:\n\n)?<!-- cross-ai-publication-lock:([0-9a-f]{64}):([0-9a-f]{64}) -->\n?"
)
ETAG_RE = re.compile(r'^etag:\s*(\S+)\s*$', re.IGNORECASE | re.MULTILINE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
LEDGER_COMMENT_DELAY_SECONDS = 1.1
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
TURKISH_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+90|0090|0)\s*\(?5\d{2}\)?(?:[ .-]*\d){7}(?!\d)"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
BEARER_RE = re.compile(
    r"(?<![A-Za-z0-9])bearer[ \t]+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE
)
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\."
    r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
KNOWN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|xox[baprs]-[A-Za-z0-9-]{20,}"
    r"|sk_live_[A-Za-z0-9]{16,}"
    r")(?![A-Za-z0-9])"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|session[_-]?secret|"
    r"secret[_-]?access[_-]?key|service[_-]?account[_-]?key|"
    r"signing[_-]?key|hmac[_-]?key|private[_-]?key|credential)\b"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}[\"']?",
    re.IGNORECASE,
)
WEBHOOK_URL_RE = re.compile(
    r"\bwebhook[_-]?url\b\s*[:=]\s*https?://[^\s\"'<>]{12,}",
    re.IGNORECASE,
)
COOKIE_HEADER_RE = re.compile(
    r"^[ \t]*(?:set-)?cookie[ \t]*:[ \t]*[^\r\n]{12,}$",
    re.IGNORECASE | re.MULTILINE,
)
MAX_EVIDENCE_BYTES = 60_000
UNATTESTED_ACTUAL_MODEL = "not-provider-attested"
CODEX_NATIVE_TRUST_ROOT = "repo-pinned-codex-native-sha256-v1"
SOURCE_TRUST_ROOT = "trusted-base-cross-ai-sources-sha256-v1"
TRUSTED_CODEX_NATIVE_SHA256 = {
    ("0.144.1", "codex-darwin-arm64"): "29915529b97697def1a957b0505e770aa6a45744435d62fc263e98d7619e167a",
    ("0.144.1", "codex-darwin-x64"): "c6eb747e4145ecb3bed2647dbd0f8464b190a5ccba964666ef7c98d4681a4a4c",
    ("0.144.1", "codex-linux-arm64"): "9513fa3f5f4ad444ac1e40d972aef0e2664834ec54da987d54aba0dc2f13ea07",
    ("0.144.1", "codex-linux-x64"): "a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902",
}
CODEX_PROVENANCE_KEYS = {
    "schema",
    "thread_id",
    "cli_version",
    "cli_native_target",
    "cli_native_sha256",
    "trust_root",
    "stderr_classification",
    "source_trust_root",
    "trusted_base_sha",
    "review_harness_sha256",
    "scope_preparer_sha256",
    "pii_attester_sha256",
    "evidence_builder_sha256",
    "pii_review_status",
    "pii_attestation_sha256",
}
EVIDENCE_KEYS = {
    "schema",
    "provider",
    "requested_model",
    "actual_model",
    "execution_profile",
    "execution_provenance",
    "base_tip_sha",
    "base_sha",
    "head_sha",
    "scope_sha256",
    "verdict",
    "response_sha256",
    "response",
}
PROVIDER_EXECUTION_PROFILES = {
    "openai": "codex-exec-ephemeral-read-only-exact-scope-no-tools-v2",
}
PROVIDER_MODELS = {
    "openai": ("gpt-5.3-codex-spark", "gpt-5.6-sol"),
}
TRUSTED_SOURCE_PATHS = {
    "review_harness_sha256": "scripts/ai/run_isolated_codex_review.py",
    "scope_preparer_sha256": "scripts/ai/prepare_cross_ai_scope.py",
    "pii_attester_sha256": "scripts/ai/attest_cross_ai_scope_pii.py",
    "evidence_builder_sha256": "scripts/ai/build_cross_ai_evidence.py",
}


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def trusted_source_digests_at_commit(
    trusted_base_sha: str,
    repo_root: Path | None = None,
) -> dict[str, str] | None:
    if COMMIT_SHA_RE.fullmatch(trusted_base_sha) is None:
        return None
    root = repo_root or Path(__file__).resolve().parents[2]
    digests: dict[str, str] = {}
    for key, relative_path in TRUSTED_SOURCE_PATHS.items():
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "show", f"{trusted_base_sha}:{relative_path}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        digests[key] = hashlib.sha256(result.stdout).hexdigest()
    return digests


def trusted_base_is_ancestor(
    trusted_base_sha: str,
    pr_base_sha: str,
    repo_root: Path | None = None,
) -> bool:
    if (
        COMMIT_SHA_RE.fullmatch(trusted_base_sha) is None
        or COMMIT_SHA_RE.fullmatch(pr_base_sha) is None
    ):
        return False
    root = repo_root or Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            [
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                trusted_base_sha, pr_base_sha,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def validate_evidence_text(
    text: str,
    trusted_source_loader: Callable[[str], dict[str, str] | None]
    = trusted_source_digests_at_commit,
    pr_base_sha: str | None = None,
    ancestor_checker: Callable[[str, str], bool] = trusted_base_is_ancestor,
) -> tuple[dict, str]:
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > MAX_EVIDENCE_BYTES:
        fail("invalid_evidence_size")
    try:
        evidence = json.loads(text)
    except json.JSONDecodeError:
        fail("invalid_evidence_json")
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_KEYS:
        fail("invalid_evidence_schema")
    if evidence.get("schema") != "cross-ai-provider-evidence/v4":
        fail("invalid_evidence_schema")
    expected_execution = PROVIDER_EXECUTION_PROFILES.get(evidence.get("provider"))
    if evidence.get("execution_profile") != expected_execution:
        fail("invalid_execution_profile")
    expected_models = PROVIDER_MODELS.get(evidence.get("provider"), ())
    actual_model_valid = evidence.get("actual_model") == UNATTESTED_ACTUAL_MODEL
    if evidence.get("requested_model") not in expected_models or not actual_model_valid:
        fail("provider_model_mismatch")
    provenance = evidence.get("execution_provenance")
    if not isinstance(provenance, dict) or set(provenance) != CODEX_PROVENANCE_KEYS:
        fail("invalid_execution_provenance")
    pin = TRUSTED_CODEX_NATIVE_SHA256.get(
        (provenance.get("cli_version"), provenance.get("cli_native_target"))
    )
    native_sha256 = provenance.get("cli_native_sha256")
    if (
        provenance.get("schema") != "codex-native-execution-provenance/v2"
        or provenance.get("trust_root") != CODEX_NATIVE_TRUST_ROOT
        or provenance.get("source_trust_root") != SOURCE_TRUST_ROOT
        or COMMIT_SHA_RE.fullmatch(evidence.get("base_tip_sha", "")) is None
        or provenance.get("trusted_base_sha")
        != evidence.get("base_tip_sha", "").lower()
        or provenance.get("pii_review_status") != "no-sensitive-pii"
        or not isinstance(provenance.get("pii_attestation_sha256"), str)
        or SHA256_RE.fullmatch(provenance["pii_attestation_sha256"]) is None
        or provenance.get("stderr_classification") not in {
            "empty",
            "allowlisted-model-cache-schema-warning-v1",
        }
        or not isinstance(provenance.get("thread_id"), str)
        or THREAD_ID_RE.fullmatch(provenance["thread_id"]) is None
        or pin is None
        or not isinstance(native_sha256, str)
        or SHA256_RE.fullmatch(native_sha256) is None
        or native_sha256 != pin
    ):
        fail("invalid_execution_provenance")
    expected_source_digests = trusted_source_loader(evidence["base_tip_sha"].lower())
    if (
        not isinstance(expected_source_digests, dict)
        or set(expected_source_digests) != set(TRUSTED_SOURCE_PATHS)
        or any(
            not isinstance(value, str) or SHA256_RE.fullmatch(value) is None
            for value in expected_source_digests.values()
        )
    ):
        fail("invalid_execution_provenance")
    for key, expected_digest in expected_source_digests.items():
        if provenance.get(key) != expected_digest.lower():
            fail("invalid_execution_provenance")
    if pr_base_sha is not None and not ancestor_checker(
        provenance["trusted_base_sha"], pr_base_sha.lower()
    ):
        fail("trusted_base_not_pr_base_ancestor")
    response = evidence.get("response")
    response_digest = evidence.get("response_sha256")
    if (
        not isinstance(response, str)
        or not response
        or not isinstance(response_digest, str)
        or not SHA256_RE.fullmatch(response_digest)
        or hashlib.sha256(response.encode("utf-8")).hexdigest() != response_digest
    ):
        fail("invalid_response_digest")
    if (
        EMAIL_RE.search(response)
        or TURKISH_PHONE_RE.search(response)
        or PRIVATE_KEY_RE.search(response)
        or BEARER_RE.search(response)
        or JWT_RE.search(response)
        or KNOWN_TOKEN_RE.search(response)
        or SECRET_ASSIGNMENT_RE.search(response)
        or WEBHOOK_URL_RE.search(response)
        or COOKIE_HEADER_RE.search(response)
    ):
        fail("provider_response_contains_sensitive_data")
    return evidence, hashlib.sha256(encoded).hexdigest()


def status_ledger_payload(
    evidence: dict,
    body_sha256: str,
    issue_number: int,
    pr_url: str,
) -> dict:
    thread_id = evidence["execution_provenance"]["thread_id"]
    return {
        "state": "success" if evidence["verdict"] == "AGREE" else "failure",
        "context": f"cross-ai/evidence/{body_sha256}",
        "description": (
            f"v4 openai {evidence['verdict']} pr={issue_number} "
            f"thread={thread_id}"
        ),
        "target_url": pr_url,
    }


def audit_invalidation_payload(pr_url: str) -> dict:
    return {
        "state": "pending",
        "context": "cross-ai/evidence-publication",
        "description": "Cross-AI evidence publication awaiting trusted audit",
        "target_url": pr_url,
    }


def assert_head_has_no_successful_or_active_audit(
    *,
    repo: str,
    head_sha: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> set[int]:
    """Forbid evidence reuse on a head that can already satisfy protection."""
    try:
        result = runner(
            [
                "gh", "api",
                f"repos/{repo}/commits/{head_sha}/check-runs"
                "?check_name=cross-ai-audit&filter=all&per_page=100",
                "--method", "GET",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_audit_head_preflight_failed")
    try:
        payload = json.loads(result.stdout)
        runs = payload["check_runs"]
        total_count = payload["total_count"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fail("gh_audit_head_preflight_invalid")
    if (
        result.returncode != 0
        or not isinstance(runs, list)
        or not isinstance(total_count, int)
        or total_count != len(runs)
        or total_count > 100
    ):
        fail("gh_audit_head_preflight_invalid")
    identifiers: set[int] = set()
    blocked = False
    for check_run in runs:
        identifier = check_run.get("id") if isinstance(check_run, dict) else None
        if (
            not isinstance(identifier, int)
            or identifier < 1
            or check_run.get("name") != "cross-ai-audit"
            or check_run.get("head_sha", "").lower() != head_sha.lower()
        ):
            fail("gh_audit_head_preflight_invalid")
        identifiers.add(identifier)
        status = check_run.get("status")
        conclusion = check_run.get("conclusion")
        if status != "completed" or conclusion == "success":
            blocked = True
    if blocked:
        fail("gh_audit_head_already_used")
    return identifiers


def github_timestamp_ms(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp() * 1000)


def parse_included_pr_response(output: str) -> tuple[dict, str]:
    normalized = output.replace("\r\n", "\n")
    headers, separator, body = normalized.rpartition("\n\n")
    match = ETAG_RE.search(headers)
    if not separator or match is None:
        fail("gh_pr_snapshot_invalid")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        fail("gh_pr_snapshot_invalid")
    if not isinstance(payload, dict):
        fail("gh_pr_snapshot_invalid")
    return payload, match.group(1)


def load_pr_snapshot(
    *,
    repo: str,
    issue_number: int,
    head_sha: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[dict, str]:
    try:
        result = runner(
            [
                "gh", "api", f"repos/{repo}/pulls/{issue_number}",
                "--method", "GET", "--include",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_pr_snapshot_failed")
    if result.returncode != 0:
        fail("gh_pr_snapshot_failed")
    snapshot, etag = parse_included_pr_response(result.stdout)
    try:
        current_head = snapshot["head"]["sha"].lower()
        current_body = snapshot["body"]
    except (KeyError, TypeError, AttributeError):
        fail("gh_pr_snapshot_invalid")
    if (
        snapshot.get("state") != "open"
        or snapshot.get("draft") is not True
        or current_head != head_sha.lower()
        or not isinstance(current_body, str)
    ):
        fail("gh_pr_snapshot_invalid")
    return snapshot, etag


def acquire_publication_lock(
    *,
    repo: str,
    issue_number: int,
    head_sha: str,
    body_sha256: str,
    publication_token: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Acquire the draft-only PR-body lease before any status mutation."""
    snapshot, etag = load_pr_snapshot(
        repo=repo,
        issue_number=issue_number,
        head_sha=head_sha,
        runner=runner,
    )
    body = snapshot["body"]
    locks = PUBLICATION_LOCK_RE.findall(body)
    marker = (
        "<!-- cross-ai-publication-lock:"
        f"{body_sha256}:{publication_token} -->"
    )
    if locks:
        fail("gh_publication_lock_conflict")
    clean_body = RECHECK_MARKER_RE.sub("", body).rstrip()
    updated_body = f"{clean_body}\n\n{marker}\n"
    if len(updated_body.encode("utf-8")) > 65_536:
        fail("gh_pr_body_invalid")
    try:
        update_result = runner(
            [
                "gh", "api", f"repos/{repo}/pulls/{issue_number}",
                "--method", "PATCH", "-H", f"If-Match: {etag}", "--input", "-",
            ],
            input=json.dumps({"body": updated_body}, separators=(",", ":")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_publication_lock_failed")
    if update_result.returncode != 0:
        fail("gh_publication_lock_failed")
    try:
        updated_pr = json.loads(update_result.stdout)
        updated_head = updated_pr["head"]["sha"].lower()
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("gh_publication_lock_invalid")
    if (
        updated_pr.get("body") != updated_body
        or updated_pr.get("state") != "open"
        or updated_pr.get("draft") is not True
        or updated_head != head_sha.lower()
    ):
        fail("gh_publication_lock_invalid")
    return marker


def patch_recheck_marker(
    *,
    repo: str,
    issue_number: int,
    head_sha: str,
    pending_status_id: int,
    ledger_status_id: int,
    body_sha256: str,
    publication_token: str,
    release_lock: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    snapshot, etag = load_pr_snapshot(
        repo=repo,
        issue_number=issue_number,
        head_sha=head_sha,
        runner=runner,
    )
    locks = PUBLICATION_LOCK_RE.findall(snapshot["body"])
    if len(locks) != 1 or locks[0] != (body_sha256, publication_token):
        fail("gh_publication_lock_lost")
    clean_body = RECHECK_MARKER_RE.sub("", snapshot["body"])
    if release_lock:
        clean_body = PUBLICATION_LOCK_RE.sub("", clean_body)
    clean_body = clean_body.rstrip()
    marker = (
        "<!-- cross-ai-audit-recheck:"
        f"{pending_status_id}:{ledger_status_id}:{body_sha256} -->"
    )
    updated_body = f"{clean_body}\n\n{marker}\n"
    if len(updated_body.encode("utf-8")) > 65_536:
        fail("gh_pr_body_invalid")
    try:
        update_result = runner(
            [
                "gh", "api", f"repos/{repo}/pulls/{issue_number}",
                "--method", "PATCH", "-H", f"If-Match: {etag}", "--input", "-",
            ],
            input=json.dumps({"body": updated_body}, separators=(",", ":")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_audit_recheck_trigger_failed")
    if update_result.returncode != 0:
        fail("gh_audit_recheck_trigger_failed")
    try:
        updated_pr = json.loads(update_result.stdout)
        updated_head = updated_pr["head"]["sha"].lower()
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("gh_audit_recheck_trigger_invalid")
    if (
        updated_pr.get("body") != updated_body
        or updated_pr.get("state") != "open"
        or updated_pr.get("draft") is not True
        or updated_head != head_sha.lower()
    ):
        fail("gh_audit_recheck_trigger_invalid")
    return marker


def publish_evidence(
    *,
    repo: str,
    issue_number: int,
    evidence: dict,
    evidence_text: str,
    body_sha256: str,
    pr_url: str,
    pr_body: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
    head_guard: Callable[..., set[int]] = assert_head_has_no_successful_or_active_audit,
) -> dict:
    """Publish evidence under one exact-head audit generation.

    A draft-only PR-body lease is acquired with ETag CAS before any status
    mutation. The exact-head required status then becomes pending and its
    GitHub status id is written into the leased PR body with CAS.
    Older events cannot clear that newer status because their marker generation
    differs. The ledger id is added only after the immutable status and owner
    comment exist. Any partial publication therefore remains fail-closed.
    """
    if not isinstance(pr_body, str):
        fail("gh_pr_body_invalid")
    head_guard(repo=repo, head_sha=evidence["head_sha"], runner=runner)
    publication_token = secrets.token_hex(32)
    publication_lock = acquire_publication_lock(
        repo=repo,
        issue_number=issue_number,
        head_sha=evidence["head_sha"],
        body_sha256=body_sha256,
        publication_token=publication_token,
        runner=runner,
    )
    invalidation = audit_invalidation_payload(pr_url)
    try:
        invalidation_result = runner(
            [
                "gh", "api",
                f"repos/{repo}/statuses/{evidence['head_sha']}",
                "--method", "POST", "--input", "-",
            ],
            input=json.dumps(invalidation, separators=(",", ":")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_audit_invalidation_failed")
    if invalidation_result.returncode != 0:
        fail("gh_audit_invalidation_failed")
    try:
        invalidation_record = json.loads(invalidation_result.stdout)
        invalidation_ref = invalidation_record["url"]
        invalidation_creator = invalidation_record["creator"]["login"].lower()
        invalidation_id = invalidation_record["id"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("gh_audit_invalidation_invalid")
    if (
        invalidation_record.get("context") != invalidation["context"]
        or not isinstance(invalidation_id, int)
        or invalidation_id < 1
        or invalidation_record.get("state") != invalidation["state"]
        or invalidation_record.get("description") != invalidation["description"]
        or invalidation_record.get("target_url") != invalidation["target_url"]
        or invalidation_creator != repo.split("/", 1)[0].lower()
    ):
        fail("gh_audit_invalidation_invalid")

    # Bind the owner-created pending id to this generation. Every body write
    # re-reads live state and uses If-Match, preserving concurrent user edits.
    patch_recheck_marker(
        repo=repo,
        issue_number=issue_number,
        head_sha=evidence["head_sha"],
        pending_status_id=invalidation_id,
        ledger_status_id=0,
        body_sha256=body_sha256,
        publication_token=publication_token,
        release_lock=False,
        runner=runner,
    )

    expected_status = status_ledger_payload(
        evidence, body_sha256, issue_number, pr_url
    )
    # GitHub's commit-status response omits the commit SHA. The validated
    # evidence head is authoritative because it is embedded in this POST path.
    status_payload = json.dumps(
        expected_status,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        status_result = runner(
            [
                "gh", "api",
                f"repos/{repo}/statuses/{evidence['head_sha']}",
                "--method", "POST", "--input", "-",
            ],
            input=status_payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_status_ledger_failed")
    if status_result.returncode != 0:
        fail("gh_status_ledger_failed")
    try:
        status_record = json.loads(status_result.stdout)
        ledger_ref = status_record["url"]
        ledger_context = status_record["context"]
        ledger_creator = status_record["creator"]["login"].lower()
        ledger_id = status_record["id"]
        ledger_created_at = status_record["created_at"]
        ledger_updated_at = status_record["updated_at"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("gh_status_ledger_invalid")
    ledger_created_at_ms = github_timestamp_ms(ledger_created_at)
    if (
        ledger_context != f"cross-ai/evidence/{body_sha256}"
        or not isinstance(ledger_id, int)
        or ledger_id <= invalidation_id
        or ledger_creator != repo.split("/", 1)[0].lower()
        or status_record.get("state") != expected_status["state"]
        or status_record.get("description") != expected_status["description"]
        or status_record.get("target_url") != pr_url
        or ledger_created_at != ledger_updated_at
        or ledger_created_at_ms is None
    ):
        fail("gh_status_ledger_invalid")

    # GitHub commit-status and issue-comment timestamps have second-level
    # resolution. Cross that boundary before posting so the immutable ledger's
    # publication order is externally provable, then verify it from GitHub's
    # own response rather than trusting the local clock.
    sleeper(LEDGER_COMMENT_DELAY_SECONDS)

    payload = json.dumps(
        {"body": evidence_text}, ensure_ascii=False, separators=(",", ":")
    )
    try:
        result = runner(
            [
                "gh",
                "api",
                f"repos/{repo}/issues/{issue_number}/comments",
                "--method",
                "POST",
                "--input",
                "-",
            ],
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_post_failed")
    if result.returncode != 0:
        fail("gh_post_failed")
    try:
        comment = json.loads(result.stdout)
        api_ref = comment["url"]
        created_at = comment["created_at"]
        updated_at = comment["updated_at"]
    except (json.JSONDecodeError, KeyError, TypeError):
        fail("gh_response_invalid")
    comment_created_at_ms = github_timestamp_ms(created_at)
    if (
        created_at != updated_at
        or comment_created_at_ms is None
        or comment_created_at_ms <= ledger_created_at_ms
    ):
        fail("gh_response_publication_order_invalid")

    recheck_marker = patch_recheck_marker(
        repo=repo,
        issue_number=issue_number,
        head_sha=evidence["head_sha"],
        pending_status_id=invalidation_id,
        ledger_status_id=ledger_id,
        body_sha256=body_sha256,
        publication_token=publication_token,
        release_lock=True,
        runner=runner,
    )
    return {
        "ref": api_ref,
        "created_at": created_at,
        "updated_at": updated_at,
        "ledger_ref": ledger_ref,
        "ledger_context": ledger_context,
        "audit_invalidation_ref": invalidation_ref,
        "audit_generation_id": invalidation_id,
        "publication_lock": publication_lock,
        "audit_recheck_marker": recheck_marker,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    args = parser.parse_args()

    if not REPO_RE.fullmatch(args.repo) or args.issue < 1:
        fail("invalid_github_target")
    if shutil.which("gh") is None:
        fail("gh_unavailable")
    try:
        text = args.evidence_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        fail("evidence_file_unreadable")
    try:
        pr_result = subprocess.run(
            [
                "gh", "api", f"repos/{args.repo}/pulls/{args.issue}",
                "--method", "GET",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        fail("gh_pr_binding_failed")
    if pr_result.returncode != 0:
        fail("gh_pr_binding_failed")
    try:
        pr = json.loads(pr_result.stdout)
        pr_base_sha = pr["base"]["sha"].lower()
        pr_head_sha = pr["head"]["sha"].lower()
        pr_state = pr["state"]
        pr_url = pr["html_url"]
        pr_body = pr["body"]
        pr_draft = pr["draft"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        fail("gh_pr_binding_invalid")
    evidence, body_sha256 = validate_evidence_text(
        text, pr_base_sha=pr_base_sha
    )
    if (
        pr_state != "open"
        or pr_draft is not True
        or evidence["base_tip_sha"].lower() != pr_base_sha
        or evidence["head_sha"].lower() != pr_head_sha
    ):
        fail("github_pr_binding_mismatch")
    expected_pr_url = f"https://github.com/{args.repo}/pull/{args.issue}"
    if pr_url != expected_pr_url:
        fail("gh_pr_binding_invalid")
    publication = publish_evidence(
        repo=args.repo,
        issue_number=args.issue,
        evidence=evidence,
        evidence_text=text,
        body_sha256=body_sha256,
        pr_url=pr_url,
        pr_body=pr_body,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "provider": evidence["provider"],
                "actual_model": evidence["actual_model"],
                "execution_profile": evidence["execution_profile"],
                "verdict": evidence["verdict"],
                "ref": publication["ref"],
                "sha256": body_sha256,
                "created_at": publication["created_at"],
                "updated_at": publication["updated_at"],
                "ledger_ref": publication["ledger_ref"],
                "ledger_context": publication["ledger_context"],
                "audit_invalidation_ref": publication["audit_invalidation_ref"],
                "audit_generation_id": publication["audit_generation_id"],
                "publication_lock": publication["publication_lock"],
                "audit_recheck_marker": publication["audit_recheck_marker"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
