#!/usr/bin/env python3
"""Prepare one bounded, scanned scope artifact for all Cross-AI channels.

The script derives and verifies the real merge-base, renders the full range,
fails closed on gitleaks findings, redacts email/UPN and Turkish phone-shaped
PII, writes a mode-0600 temporary artifact, and reports its SHA-256. Provider
CLIs must all read this same file; raw `git diff | provider` pipelines are not
canonical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn


COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
TURKISH_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+90|0090|0)\s*\(?5\d{2}\)?(?:[ .-]*\d){7}(?!\d)"
)
PRIVATE_KEY_RE = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
BEARER_RE = re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{12,}")
MAX_SCOPE_BYTES = 2_000_000


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def run_git(repo: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        fail("git_unavailable")
    if result.returncode != 0 or not result.stdout.strip():
        fail("git_metadata_failed")
    return result.stdout.strip()


def run_git_diff(
    repo: Path, base_sha: str, head_sha: str, max_scope_bytes: int
) -> bytes:
    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-ext-diff",
                "--stat",
                "--patch",
                f"{base_sha}...{head_sha}",
            ],
            cwd=repo,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        fail("git_unavailable")
    if result.returncode != 0:
        fail("git_diff_failed")
    if not result.stdout.strip():
        fail("scope_empty")
    if len(result.stdout) > max_scope_bytes:
        fail("scope_too_large")
    return result.stdout


def gitleaks_clean(raw_scope: bytes) -> bool:
    binary = shutil.which("gitleaks")
    if binary is None:
        fail("gitleaks_unavailable")
    with tempfile.TemporaryDirectory(prefix="cross-ai-scan-") as directory:
        root = Path(directory)
        source_dir = root / "source"
        source_dir.mkdir(mode=0o700)
        source = source_dir / "scope.patch"
        source.write_bytes(raw_scope)
        os.chmod(source, 0o600)
        # The default generic-api-key detector treats this repository's exact
        # policy prose ("OAuth client secret, private/signing...") as a value.
        # Suppress only that literal documentation phrase; all default rules
        # and all other matches remain enabled.
        config = root / "gitleaks.toml"
        config.write_text(
            "[extend]\nuseDefault = true\n\n"
            "[[allowlists]]\n"
            "description = \"Cross-AI policy vocabulary false positive\"\n"
            "regexTarget = \"match\"\n"
            "regexes = [\"^OAuth client secret, private/signing/HMAC ?$\"]\n",
            encoding="utf-8",
        )
        os.chmod(config, 0o600)
        result = subprocess.run(
            [
                binary,
                "detect",
                "--no-git",
                "--no-banner",
                "--redact",
                "--config",
                str(config),
                "--source",
                str(source_dir),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_SCOPE_BYTES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not COMMIT_SHA_RE.fullmatch(args.base_sha):
        fail("invalid_base_sha")
    if not COMMIT_SHA_RE.fullmatch(args.head_sha):
        fail("invalid_head_sha")
    if args.max_bytes < 1 or args.max_bytes > 16_000_000:
        fail("invalid_max_bytes")
    repo = args.repo.expanduser().resolve()
    if not (repo / ".git").exists():
        # A linked worktree has a .git file, which exists() also accepts.
        fail("repo_not_found")

    resolved_head = run_git(repo, "rev-parse", args.head_sha)
    base_tip_sha = run_git(repo, "rev-parse", args.base_ref)
    merge_base_sha = run_git(repo, "merge-base", base_tip_sha, resolved_head)
    if resolved_head.lower() != args.head_sha.lower():
        fail("head_sha_resolution_mismatch")
    if merge_base_sha.lower() != args.base_sha.lower():
        fail("base_sha_not_real_merge_base")

    raw_scope = run_git_diff(
        repo, merge_base_sha, resolved_head, max_scope_bytes=args.max_bytes
    )
    if PRIVATE_KEY_RE.search(raw_scope) or BEARER_RE.search(raw_scope):
        fail("high_confidence_secret_detected")
    if not gitleaks_clean(raw_scope):
        fail("gitleaks_finding_detected")

    try:
        scope_text = raw_scope.decode("utf-8")
    except UnicodeDecodeError:
        fail("scope_not_utf8")
    scope_text, email_count = EMAIL_RE.subn("<redacted-email>", scope_text)
    scope_text, phone_count = TURKISH_PHONE_RE.subn(
        "<redacted-phone>", scope_text
    )
    redacted_scope = scope_text.encode("utf-8")
    digest = hashlib.sha256(redacted_scope).hexdigest()

    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(redacted_scope)
        os.chmod(output, 0o600)
    else:
        descriptor, name = tempfile.mkstemp(prefix="cross-ai-scope-", suffix=".patch")
        output = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(redacted_scope)
        os.chmod(output, 0o600)

    print(
        json.dumps(
            {
                "ok": True,
                "base_ref": args.base_ref,
                "base_tip_sha": base_tip_sha.lower(),
                "base_sha": merge_base_sha.lower(),
                "head_sha": resolved_head.lower(),
                "scope_sha256": digest,
                "scope_bytes": len(redacted_scope),
                "email_redactions": email_count,
                "phone_redactions": phone_count,
                "secret_scan": "gitleaks-pass",
                "scope_path": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
