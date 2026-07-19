#!/usr/bin/env python3
"""Verify and post one signed Codex carrier; the owner comment is transport."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.build_cross_ai_evidence import _scope
from scripts.ai.cross_ai_authority import AuthorityUnavailable, load_active_authority
from scripts.ai.trusted_cross_ai_evidence import (
    EVIDENCE_SCHEMA,
    TrustedEvidenceError,
    canonical_bytes,
    validate_github_comment_transport,
    validate_evidence,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import CODEX_MODELS


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def load_canonical_evidence(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        fail("evidence_file_unreadable")
    try:
        validate_github_comment_transport(raw.decode("utf-8"))
    except (UnicodeDecodeError, TrustedEvidenceError):
        fail("invalid_evidence_size")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("invalid_evidence_json")
    if not isinstance(value, dict) or canonical_bytes(value) != raw:
        fail("noncanonical_or_duplicate_evidence_json")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    args = parser.parse_args()

    if not REPO_RE.fullmatch(args.repo) or args.issue < 1:
        fail("invalid_github_target")
    if shutil.which("gh") is None:
        fail("gh_unavailable")
    evidence = load_canonical_evidence(args.evidence_file)
    workspace = args.workspace.expanduser().resolve()
    bindings, scope_bytes = _scope(workspace)
    try:
        capability = evidence.get("capability_snapshot")
        transport_model = (
            capability.get("requestedModel")
            if isinstance(capability, dict)
            else None
        )
        if transport_model not in CODEX_MODELS:
            raise TrustedEvidenceError("transport model is outside the fixed routes")
        authority = load_active_authority(workspace)
        validated = validate_evidence(
            evidence,
            trust_root=authority.trust_root,
            revocations_envelope=authority.revocations_envelope,
            expected_trust_root_sha256=authority.expected_trust_root_sha256,
            codex_executable_policy=authority.codex_executable_policy,
            expected_bindings=bindings,
            scope_bytes=scope_bytes,
            now=datetime.now(timezone.utc),
            require_agree=False,
            expected_model=transport_model,
        )
    except (AuthorityUnavailable, PolicyError, TrustedEvidenceError):
        fail("trusted_evidence_verification_failed")
    body = canonical_bytes(evidence).decode("utf-8")
    try:
        validate_github_comment_transport(body)
    except TrustedEvidenceError:
        fail("invalid_evidence_size")
    payload = json.dumps({"body": body}, ensure_ascii=False, separators=(",", ":"))
    try:
        result = subprocess.run(
            [
                "gh", "api", f"repos/{args.repo}/issues/{args.issue}/comments",
                "--method", "POST", "--input", "-",
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
    review = validated["review"]
    print(
        json.dumps(
            {
                "ok": True,
                "schema": EVIDENCE_SCHEMA,
                "provider": review["providerFamily"],
                "model_id": review["modelId"],
                "model_identity_class": review["modelIdentityClass"],
                "verdict": review["verdict"],
                "review_envelope_sha256": validated["reviewEnvelopeSha256"],
                "ref": api_ref,
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "created_at": created_at,
                "updated_at": updated_at,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
