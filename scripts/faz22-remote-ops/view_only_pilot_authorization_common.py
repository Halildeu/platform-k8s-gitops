"""Canonical byte and digest helpers for bounded VIEW_ONLY authorization receipts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any


CODEX_EVIDENCE_KEYS = {
    "schema", "provider", "requested_model", "actual_model",
    "reasoning_effort", "sandbox", "ephemeral", "base_tip_sha",
    "base_sha", "head_sha", "scope_sha256", "verdict",
    "response_sha256", "response",
}
CODEX_EVIDENCE_BINDING_KEYS = {
    "base_tip_sha", "base_sha", "head_sha", "scope_sha256",
}
CODEX_ADVISORY_MAX_AGE_HOURS = 168
CODEX_ADVISORY_CLOCK_SKEW = timedelta(minutes=5)
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GITHUB_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
VERDICT = re.compile(r"^VERDICT:[ \t]*(AGREE|REVISE)[ \t]*$", re.MULTILINE)
PRIORITY_HEADING = re.compile(
    r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*)?(P[012])(?:\*\*)?[ \t]*$"
)


class CodexEvidenceError(ValueError):
    """Raised when an owner-selected Codex advisory is not strict v2 evidence."""


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodexEvidenceError("Codex advisory contains a duplicate JSON key")
        result[key] = value
    return result


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def canonical_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return canonical_bytes(receipt) + b"\n"


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def validate_codex_advisory_evidence(
    body: str, expected_bindings: dict[str, str],
) -> dict[str, Any]:
    """Validate exact direct-Codex evidence selected by the owner policy.

    This deliberately duplicates the active evidence contract at the
    authorization boundary. A provider label in policy metadata is not enough:
    the fetched, digest-bound GitHub comment must itself prove the exact model,
    read-only/ephemeral launch contract and a finding-free terminal AGREE.
    """

    if not body or len(body.encode("utf-8")) > 60_000:
        raise CodexEvidenceError("Codex advisory evidence size is invalid")
    try:
        evidence = json.loads(body, object_pairs_hook=_no_duplicate_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CodexEvidenceError("Codex advisory evidence is not strict JSON") from exc
    if not isinstance(evidence, dict) or set(evidence) != CODEX_EVIDENCE_KEYS:
        raise CodexEvidenceError("Codex advisory evidence field set is invalid")
    if json.dumps(evidence, ensure_ascii=False, separators=(",", ":")) != body:
        raise CodexEvidenceError("Codex advisory evidence is not canonical JSON")
    if not (
        evidence["schema"] == "cross-ai-provider-evidence/v2"
        and evidence["provider"] == "openai"
        and evidence["requested_model"] == "gpt-5.6-sol"
        and evidence["actual_model"] == "gpt-5.6-sol"
        and evidence["reasoning_effort"] == "xhigh"
        and evidence["sandbox"] == "read-only"
        and evidence["ephemeral"] is True
        and evidence["verdict"] == "AGREE"
    ):
        raise CodexEvidenceError("Codex advisory execution identity is invalid")
    if any(
        not isinstance(evidence[field], str) or not GIT_SHA.fullmatch(evidence[field])
        for field in ("base_tip_sha", "base_sha", "head_sha")
    ) or not isinstance(evidence["scope_sha256"], str) or not SHA256.fullmatch(
        evidence["scope_sha256"]
    ):
        raise CodexEvidenceError("Codex advisory immutable binding is invalid")
    if set(expected_bindings) != CODEX_EVIDENCE_BINDING_KEYS:
        raise CodexEvidenceError("Codex advisory expected binding field set is invalid")
    for field in CODEX_EVIDENCE_BINDING_KEYS:
        if evidence[field] != expected_bindings[field]:
            raise CodexEvidenceError(f"Codex advisory {field} binding mismatch")
    response = evidence["response"]
    response_sha256 = evidence["response_sha256"]
    if (
        not isinstance(response, str)
        or not response
        or not isinstance(response_sha256, str)
        or not SHA256.fullmatch(response_sha256)
        or hashlib.sha256(response.encode("utf-8")).hexdigest() != response_sha256
    ):
        raise CodexEvidenceError("Codex advisory response digest is invalid")
    verdicts = VERDICT.findall(response)
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    headings = list(PRIORITY_HEADING.finditer(response))
    if (
        len(verdicts) != 1
        or verdicts[0] != "AGREE"
        or not lines
        or lines[-1] != "VERDICT: AGREE"
        or [heading.group(1) for heading in headings] != ["P0", "P1", "P2"]
        or response[:headings[0].start()].strip()
    ):
        raise CodexEvidenceError("Codex advisory response semantics are invalid")
    verdict_match = next(iter(VERDICT.finditer(response)))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index < 2 else verdict_match.start()
        if response[heading.end():end].strip() != "None":
            raise CodexEvidenceError("Codex advisory AGREE contains findings")
    return evidence


def validate_codex_advisory_comment_timing(
    comment: dict[str, Any], reference_time: datetime,
    max_age_hours: int = CODEX_ADVISORY_MAX_AGE_HOURS,
) -> datetime:
    """Require an immutable, recent GitHub comment at the use boundary."""

    if reference_time.tzinfo is None:
        raise CodexEvidenceError("Codex advisory reference time must be timezone-aware")
    if (
        not isinstance(max_age_hours, int)
        or isinstance(max_age_hours, bool)
        or max_age_hours != CODEX_ADVISORY_MAX_AGE_HOURS
    ):
        raise CodexEvidenceError("Codex advisory maximum age is invalid")
    created_at = comment.get("created_at")
    updated_at = comment.get("updated_at")
    if (
        not isinstance(created_at, str)
        or not GITHUB_UTC.fullmatch(created_at)
        or updated_at != created_at
    ):
        raise CodexEvidenceError("Codex advisory comment is edited or has invalid timestamps")
    created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc,
    )
    age = reference_time.astimezone(timezone.utc) - created
    if age < -CODEX_ADVISORY_CLOCK_SKEW:
        raise CodexEvidenceError("Codex advisory comment is from the future")
    if age > timedelta(hours=max_age_hours):
        raise CodexEvidenceError("Codex advisory comment is stale")
    return created
