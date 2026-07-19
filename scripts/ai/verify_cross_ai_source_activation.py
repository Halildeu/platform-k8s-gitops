#!/usr/bin/env python3
"""Verify that a trusted main commit activates the Cross-AI producer stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import NoReturn


COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
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


def verify_activation(
    repo: Path,
    trusted_ref: str,
    expected_sha: str,
    *,
    repository: str,
    workflow_ref: str,
    event_name: str,
    git_ref: str,
    run_id: str,
    run_attempt: str,
    activated_at: str,
) -> dict:
    expected = expected_sha.lower()
    if COMMIT_SHA_RE.fullmatch(expected) is None:
        raise ActivationError("invalid_expected_sha")
    if not repo.is_dir():
        raise ActivationError("invalid_repo")
    expected_workflow_ref = (
        f"{repository}/.github/workflows/ci.yml@refs/heads/main"
    )
    if (
        REPO_RE.fullmatch(repository) is None
        or workflow_ref != expected_workflow_ref
        or event_name != "push"
        or git_ref != "refs/heads/main"
        or not run_id.isdigit()
        or int(run_id) < 1
        or not run_attempt.isdigit()
        or int(run_attempt) < 1
        or UTC_TIMESTAMP_RE.fullmatch(activated_at) is None
    ):
        raise ActivationError("untrusted_activation_context")

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
        "repository": repository,
        "workflow_ref": workflow_ref,
        "event_name": event_name,
        "ref": git_ref,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "activated_at": activated_at,
    }


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--trusted-ref", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--git-ref", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--activated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_activation(
            args.repo.resolve(),
            args.trusted_ref,
            args.expected_sha,
            repository=args.repository,
            workflow_ref=args.workflow_ref,
            event_name=args.event_name,
            git_ref=args.git_ref,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            activated_at=args.activated_at,
        )
    except ActivationError as exc:
        fail(str(exc))
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except OSError:
        fail("activation_output_create_failed")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
