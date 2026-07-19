#!/usr/bin/env python3
"""Verify that a trusted main commit activates the Cross-AI producer stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn


COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACTIVATION_STATUS_CONTEXT = "cross-ai/source-trust-activation"
ACTIVATION_STATUS_DESCRIPTION = "Cross-AI source trust activated"
TRUSTED_STATUS_CREATOR = "github-actions[bot]"
TRUSTED_SOURCE_PATHS = {
    "review_harness_sha256": "scripts/ai/run_isolated_codex_review.py",
    "scope_preparer_sha256": "scripts/ai/prepare_cross_ai_scope.py",
    "pii_attester_sha256": "scripts/ai/attest_cross_ai_scope_pii.py",
    "evidence_builder_sha256": "scripts/ai/build_cross_ai_evidence.py",
}
ACTIVATION_MARKER_PATH = "scripts/ai/cross_ai_source_activation_marker.json"
ACTIVATION_MARKER_BYTES = (
    b'{"issue":2638,"policy":"context-isolated-codex-primary",'
    b'"schema":"cross-ai-source-trust-activation-marker/v1"}\n'
)


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


def derive_activation_epoch(repo: Path, expected_sha: str) -> str:
    """Return the first mainline commit carrying marker plus complete stack."""
    marker_history = (
        run_git(
            repo,
            "rev-list",
            "--first-parent",
            "--reverse",
            expected_sha,
            "--",
            ACTIVATION_MARKER_PATH,
        )
        .decode()
        .splitlines()
    )
    if not marker_history:
        raise ActivationError("activation_epoch_unavailable")
    first_marker_commit = marker_history[0]
    descendants = (
        run_git(
            repo,
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{first_marker_commit}..{expected_sha}",
        )
        .decode()
        .splitlines()
    )
    for candidate in (first_marker_commit, *descendants):
        try:
            if (
                run_git(repo, "show", f"{candidate}:{ACTIVATION_MARKER_PATH}")
                != ACTIVATION_MARKER_BYTES
            ):
                continue
            if not all(
                run_git(repo, "show", f"{candidate}:{relative_path}")
                for relative_path in TRUSTED_SOURCE_PATHS.values()
            ):
                continue
            raw_timestamp = (
                run_git(repo, "show", "-s", "--format=%cI", candidate)
                .decode()
                .strip()
            )
            parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except (ActivationError, UnicodeError, ValueError):
            continue
        if parsed.tzinfo is None:
            continue
        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    raise ActivationError("activation_epoch_unavailable")


def verify_recovery_anchor(
    repo: Path,
    expected_sha: str,
    repository: str,
    anchor_file: Path,
    activated_at: str,
) -> dict:
    try:
        anchor = json.loads(anchor_file.read_text(encoding="utf-8"))
        anchor_sha = anchor["anchor_sha"].lower()
        status = anchor["status"]
        status_id = status["id"]
        status_sha = status["sha"].lower()
        status_creator = status["creator"]["login"].lower()
        status_created_at = status["created_at"]
        target_url = status["target_url"]
        run = anchor["run"]
        action_run_id = run["id"]
        action_run_sha = run["head_sha"].lower()
        action_run_repo = run["repository"]["full_name"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        AttributeError,
    ) as exc:
        raise ActivationError("recovery_anchor_invalid") from exc
    if set(anchor) != {"anchor_sha", "run", "status"}:
        raise ActivationError("recovery_anchor_invalid")
    if (
        COMMIT_SHA_RE.fullmatch(anchor_sha) is None
        or status_sha != anchor_sha
        or not isinstance(status_id, int)
        or status_id < 1
        or status.get("context") != ACTIVATION_STATUS_CONTEXT
        or status.get("state") != "success"
        or status.get("description") != ACTIVATION_STATUS_DESCRIPTION
        or status_creator != TRUSTED_STATUS_CREATOR
    ):
        raise ActivationError("recovery_anchor_invalid")
    target_match = re.fullmatch(
        rf"https://github\.com/{re.escape(repository)}/actions/runs/(\d+)",
        target_url,
    )
    if target_match is None or int(target_match.group(1)) < 1:
        raise ActivationError("recovery_anchor_invalid")
    if (
        not isinstance(action_run_id, int)
        or action_run_id != int(target_match.group(1))
        or action_run_sha != anchor_sha
        or action_run_repo != repository
        or run.get("event") != "push"
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("path") != ".github/workflows/ci.yml"
        or run.get("html_url") != target_url
    ):
        raise ActivationError("recovery_anchor_run_invalid")
    try:
        created = datetime.fromisoformat(status_created_at.replace("Z", "+00:00"))
        activation = datetime.fromisoformat(activated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ActivationError("recovery_anchor_invalid") from exc
    if created.tzinfo is None or activation.tzinfo is None or created < activation:
        raise ActivationError("recovery_anchor_invalid")
    if anchor_sha != expected_sha:
        raise ActivationError("recovery_anchor_not_exact_base")
    return {
        "activation_mode": "durable-main-status-recovery",
        "anchor_sha": anchor_sha,
        "anchor_status_id": status_id,
        "anchor_run_id": str(action_run_id),
    }


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
    recovery_anchor_file: Path | None = None,
) -> dict:
    expected = expected_sha.lower()
    if COMMIT_SHA_RE.fullmatch(expected) is None:
        raise ActivationError("invalid_expected_sha")
    if not repo.is_dir():
        raise ActivationError("invalid_repo")
    expected_workflow_ref = f"{repository}/.github/workflows/ci.yml@refs/heads/main"
    recovery_workflow_ref = (
        f"{repository}/.github/workflows/gate-cross-ai-audit.yml@refs/heads/main"
    )
    primary_context = (
        workflow_ref == expected_workflow_ref and event_name == "push"
    )
    recovery_context = (
        recovery_anchor_file is not None
        and workflow_ref == recovery_workflow_ref
        and event_name == "pull_request_target"
    )
    if (
        REPO_RE.fullmatch(repository) is None
        or not (primary_context or recovery_context)
        or git_ref != "refs/heads/main"
        or not run_id.isdigit()
        or int(run_id) < 1
        or not run_attempt.isdigit()
        or int(run_attempt) < 1
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

    try:
        trusted_marker = run_git(repo, "show", f"{expected}:{ACTIVATION_MARKER_PATH}")
        checkout_marker = (repo / ACTIVATION_MARKER_PATH).read_bytes()
    except ActivationError as exc:
        raise ActivationError("activation_marker_unavailable") from exc
    except OSError as exc:
        raise ActivationError("activation_marker_checkout_unavailable") from exc
    if (
        trusted_marker != ACTIVATION_MARKER_BYTES
        or checkout_marker != ACTIVATION_MARKER_BYTES
    ):
        raise ActivationError("activation_marker_mismatch")

    activated_at = derive_activation_epoch(repo, expected)

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

    result = {
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
    if recovery_anchor_file is not None:
        result.update(
            verify_recovery_anchor(
                repo,
                expected,
                repository,
                recovery_anchor_file,
                activated_at,
            )
        )
        result["schema"] = "cross-ai-source-trust-activation/v2"
    return result


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
    parser.add_argument("--recovery-anchor-file", type=Path)
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
            recovery_anchor_file=args.recovery_anchor_file,
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
