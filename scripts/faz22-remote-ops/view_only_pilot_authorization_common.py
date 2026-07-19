"""Canonical byte and digest helpers for bounded VIEW_ONLY authorization receipts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
AI_SCRIPTS = ROOT / "scripts/ai"
for candidate in (ROOT, AI_SCRIPTS):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from trusted_cross_ai_evidence import (
    TrustedEvidenceError,
    canonical_bytes as trusted_canonical_bytes,
    validate_evidence,
    validate_github_comment_transport,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError

CODEX_EVIDENCE_BINDING_KEYS = {
    "base_tip_sha", "base_sha", "head_sha", "scope_sha256",
}
CODEX_ADVISORY_MAX_AGE_HOURS = 168
CODEX_ADVISORY_CLOCK_SKEW = timedelta(minutes=5)
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GITHUB_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CodexEvidenceError(ValueError):
    """Raised when a carried Codex advisory is not valid signed v3 evidence."""


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
    body: str,
    expected_bindings: dict[str, str],
    *,
    scope_bytes: bytes,
    trust_root: dict[str, Any],
    revocations_envelope: dict[str, Any],
    expected_trust_root_sha256: str,
    codex_executable_policy: dict[str, Any],
    issuer_runtime_policy: dict[str, Any],
    authority_observed_at: datetime,
    review_reference_time: datetime,
) -> dict[str, Any]:
    """Verify the comment-carried leaf against independent signed authority."""

    try:
        validate_github_comment_transport(body)
    except TrustedEvidenceError as exc:
        raise CodexEvidenceError("Codex advisory evidence size is invalid") from exc
    try:
        evidence = json.loads(body, object_pairs_hook=_no_duplicate_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CodexEvidenceError("Codex advisory evidence is not strict JSON") from exc
    if trusted_canonical_bytes(evidence).decode("utf-8") != body:
        raise CodexEvidenceError("Codex advisory evidence is not canonical JSON")
    if set(expected_bindings) != CODEX_EVIDENCE_BINDING_KEYS:
        raise CodexEvidenceError("Codex advisory expected binding field set is invalid")
    try:
        validate_evidence(
            evidence,
            trust_root=trust_root,
            revocations_envelope=revocations_envelope,
            expected_trust_root_sha256=expected_trust_root_sha256,
            codex_executable_policy=codex_executable_policy,
            issuer_runtime_policy=issuer_runtime_policy,
            expected_bindings=expected_bindings,
            scope_bytes=scope_bytes,
            now=authority_observed_at,
            review_reference_time=review_reference_time,
            require_agree=True,
        )
    except (PolicyError, TrustedEvidenceError) as exc:
        raise CodexEvidenceError(f"Codex advisory signed authority is invalid: {exc}") from exc
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
