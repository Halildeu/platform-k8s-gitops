#!/usr/bin/env python3
"""Prepare one bounded, scanned scope artifact for all Cross-AI channels.

The script renders the full merge-base range, fails closed on gitleaks findings,
redacts email-shaped PII, writes a mode-0600 temporary artifact, and reports its
SHA-256. Provider CLIs must all read this same file; raw `git diff | provider`
pipelines are intentionally not canonical.
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
    rb"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
PRIVATE_KEY_RE = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
BEARER_RE = re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{12,}")
MAX_SCOPE_BYTES = 2_000_000


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def run_git_diff(repo: Path, base_sha: str, head_sha: str) -> bytes:
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
    if len(result.stdout) > MAX_SCOPE_BYTES:
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
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not COMMIT_SHA_RE.fullmatch(args.base_sha):
        fail("invalid_base_sha")
    if not COMMIT_SHA_RE.fullmatch(args.head_sha):
        fail("invalid_head_sha")
    repo = args.repo.expanduser().resolve()
    if not (repo / ".git").exists():
        # A linked worktree has a .git file, which exists() also accepts.
        fail("repo_not_found")

    raw_scope = run_git_diff(repo, args.base_sha, args.head_sha)
    if PRIVATE_KEY_RE.search(raw_scope) or BEARER_RE.search(raw_scope):
        fail("high_confidence_secret_detected")
    if not gitleaks_clean(raw_scope):
        fail("gitleaks_finding_detected")

    redacted_scope, email_count = EMAIL_RE.subn(b"<redacted-email>", raw_scope)
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
                "base_sha": args.base_sha.lower(),
                "head_sha": args.head_sha.lower(),
                "scope_sha256": digest,
                "scope_bytes": len(redacted_scope),
                "email_redactions": email_count,
                "secret_scan": "gitleaks-pass",
                "scope_path": str(output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
