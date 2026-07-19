#!/usr/bin/env python3
"""Verify a GitHub-carried signed Codex leaf against independent authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.trusted_cross_ai_evidence import (
    TrustedEvidenceError,
    canonical_bytes,
    validate_github_comment_transport,
    validate_evidence,
)
from scripts.ai.cross_ai_authority import (
    AuthorityUnavailable,
    load_active_authority,
    load_revocation_refresh_authority,
    load_staged_activation_authority,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import CODEX_MODELS


GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_AGE = timedelta(days=7)
MAX_FUTURE_SKEW = timedelta(minutes=5)


def parse_github_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--body-sha256", required=True)
    parser.add_argument("--base-tip-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--scope-file", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--model", choices=tuple(sorted(CODEX_MODELS)), required=True)
    args = parser.parse_args()
    if (
        not SHA256_RE.fullmatch(args.body_sha256)
        or not GIT_SHA_RE.fullmatch(args.base_tip_sha)
        or not GIT_SHA_RE.fullmatch(args.base_sha)
        or not GIT_SHA_RE.fullmatch(args.head_sha)
        or not SHA256_RE.fullmatch(args.scope_sha256)
    ):
        raise SystemExit(2)
    try:
        comment = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        raise SystemExit(1)
    body = comment.get("body") if isinstance(comment, dict) else None
    user = comment.get("user") if isinstance(comment, dict) else None
    created_at = parse_github_time(comment.get("created_at")) if isinstance(comment, dict) else None
    now = datetime.now(timezone.utc)
    try:
        validate_github_comment_transport(body)
    except TrustedEvidenceError:
        raise SystemExit(1)
    if (
        not isinstance(user, dict)
        or user.get("login") != args.owner
        or comment.get("author_association") != "OWNER"
        or created_at is None
        or comment.get("created_at") != comment.get("updated_at")
        or created_at < now - MAX_EVIDENCE_AGE
        or created_at > now + MAX_FUTURE_SKEW
        or hashlib.sha256(body.encode("utf-8")).hexdigest() != args.body_sha256
    ):
        raise SystemExit(1)
    try:
        evidence = json.loads(body)
        if canonical_bytes(evidence).decode("utf-8") != body:
            raise TrustedEvidenceError("comment carrier is not canonical")
        scope_bytes = args.scope_file.read_bytes()
        try:
            authority = load_active_authority(args.repo_root, now=now)
        except AuthorityUnavailable as exc:
            bindings = {
                "base_tip_sha": args.base_tip_sha,
                "base_sha": args.base_sha,
                "head_sha": args.head_sha,
                "scope_sha256": args.scope_sha256,
            }
            if "tracked_pending" in str(exc):
                authority = load_staged_activation_authority(
                    args.repo_root,
                    expected_bindings=bindings,
                    scope_bytes=scope_bytes,
                    now=now,
                )
            elif "REVOCATIONS_STALE" in str(exc):
                authority = load_revocation_refresh_authority(
                    args.repo_root,
                    expected_bindings=bindings,
                    scope_bytes=scope_bytes,
                    now=now,
                )
            else:
                raise
        validated = validate_evidence(
            evidence,
            trust_root=authority.trust_root,
            revocations_envelope=authority.revocations_envelope,
            expected_trust_root_sha256=authority.expected_trust_root_sha256,
            codex_executable_policy=authority.codex_executable_policy,
            expected_bindings={
                "base_tip_sha": args.base_tip_sha,
                "base_sha": args.base_sha,
                "head_sha": args.head_sha,
                "scope_sha256": args.scope_sha256,
            },
            scope_bytes=scope_bytes,
            now=now,
            require_agree=True,
            expected_model=args.model,
        )
    except (
        AuthorityUnavailable, OSError, json.JSONDecodeError, PolicyError,
        TrustedEvidenceError,
    ):
        raise SystemExit(1)
    if validated["review"]["modelId"] != args.model:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
