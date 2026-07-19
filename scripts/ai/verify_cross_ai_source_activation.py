#!/usr/bin/env python3
"""Verify that a trusted main commit activates the Cross-AI producer stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import NoReturn


COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
TRUSTED_SOURCE_PATHS = {
    "review_harness_sha256": "scripts/ai/run_isolated_codex_review.py",
    "scope_preparer_sha256": "scripts/ai/prepare_cross_ai_scope.py",
    "pii_attester_sha256": "scripts/ai/attest_cross_ai_scope_pii.py",
    "evidence_builder_sha256": "scripts/ai/build_cross_ai_evidence.py",
}


class ActivationError(RuntimeError):
    """Stable machine-readable activation failure."""


def run_git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ActivationError("git_unavailable") from exc
    if result.returncode != 0:
        raise ActivationError("git_evidence_unavailable")
    return result.stdout


def verify_activation(repo: Path, trusted_ref: str, expected_sha: str) -> dict:
    expected = expected_sha.lower()
    if COMMIT_SHA_RE.fullmatch(expected) is None:
        raise ActivationError("invalid_expected_sha")
    if not repo.is_dir():
        raise ActivationError("invalid_repo")

    resolved = (
        run_git(repo, "rev-parse", "--verify", f"{trusted_ref}^{{commit}}")
        .decode()
        .strip()
        .lower()
    )
    head = (
        run_git(repo, "rev-parse", "--verify", "HEAD^{commit}")
        .decode()
        .strip()
        .lower()
    )
    if resolved != expected or head != expected:
        raise ActivationError("trusted_ref_binding_mismatch")

    digests: dict[str, str] = {}
    for key, relative_path in TRUSTED_SOURCE_PATHS.items():
        try:
            trusted_bytes = run_git(repo, "show", f"{expected}:{relative_path}")
        except ActivationError as exc:
            raise ActivationError("trusted_source_unavailable") from exc
        try:
            checkout_bytes = (repo / relative_path).read_bytes()
        except OSError as exc:
            raise ActivationError("trusted_source_checkout_unavailable") from exc
        if not trusted_bytes or checkout_bytes != trusted_bytes:
            raise ActivationError("trusted_source_checkout_mismatch")
        digests[key] = hashlib.sha256(trusted_bytes).hexdigest()

    return {
        "ok": True,
        "schema": "cross-ai-source-trust-activation/v1",
        "trusted_sha": expected,
        "source_digests": digests,
    }


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--trusted-ref", required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        result = verify_activation(
            args.repo.resolve(), args.trusted_ref, args.expected_sha
        )
    except ActivationError as exc:
        fail(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
