#!/usr/bin/env python3
"""Create an exact-scope, owner-only PII review attestation.

The deterministic scope preparer removes known email and Turkish mobile-phone
patterns, but source diffs may still contain context-dependent personal data.
This explicit gate records that the exact scope digest was inspected before it
is sent to an external provider. Absence of this artifact remains
``tracked_pending`` in the isolated review harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn


SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCHEMA = "cross-ai-pii-review-attestation/v2"
DECISION = "no-sensitive-pii"
REVIEWER_ROLE = "authenticated-repository-owner"
MAX_SCOPE_BYTES = 2_000_000


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def write_create_once(path: Path, content: str) -> str:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except FileExistsError:
        fail("pii_attestation_output_exists")
    except OSError:
        fail("pii_attestation_write_failed")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def gh_json(path: str) -> dict:
    try:
        result = subprocess.run(
            ["gh", "api", path, "--method", "GET"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("pii_reviewer_identity_unverifiable")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        fail("pii_reviewer_identity_unverifiable")
    if result.returncode != 0 or not isinstance(payload, dict):
        fail("pii_reviewer_identity_unverifiable")
    return payload


def verify_authenticated_repository_owner(repo: str) -> str:
    if REPO_RE.fullmatch(repo) is None or shutil.which("gh") is None:
        fail("pii_reviewer_identity_unverifiable")
    actor = gh_json("user")
    repository = gh_json(f"repos/{repo}")
    login = actor.get("login")
    owner = repository.get("owner")
    permissions = repository.get("permissions")
    if (
        not isinstance(login, str)
        or not isinstance(owner, dict)
        or not isinstance(owner.get("login"), str)
        or not isinstance(permissions, dict)
        or permissions.get("admin") is not True
        or repository.get("full_name", "").lower() != repo.lower()
        or login.lower() != owner["login"].lower()
        or login.lower() != repo.split("/", 1)[0].lower()
    ):
        fail("pii_reviewer_not_repository_owner")
    return login


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-file", type=Path, required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--decision", choices=(DECISION,), required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not SHA256_RE.fullmatch(args.scope_sha256):
        fail("invalid_scope_sha256")
    if os.path.lexists(args.output):
        fail("pii_attestation_output_exists")
    reviewer_login = verify_authenticated_repository_owner(args.repo)
    try:
        scope_stat = args.scope_file.stat()
        scope_bytes = args.scope_file.read_bytes()
    except OSError:
        fail("scope_unreadable")
    if (
        not args.scope_file.is_file()
        or scope_stat.st_size < 1
        or scope_stat.st_size > MAX_SCOPE_BYTES
        or scope_stat.st_mode & 0o077
        or hashlib.sha256(scope_bytes).hexdigest() != args.scope_sha256.lower()
    ):
        fail("scope_identity_unverifiable")

    content = json.dumps(
        {
            "schema": SCHEMA,
            "scope_sha256": args.scope_sha256.lower(),
            "decision": DECISION,
            "reviewer_role": REVIEWER_ROLE,
            "repository": args.repo,
            "reviewer_login": reviewer_login,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = write_create_once(args.output, content)
    print(
        json.dumps(
            {
                "ok": True,
                "schema": SCHEMA,
                "scope_sha256": args.scope_sha256.lower(),
                "decision": DECISION,
                "attestation_sha256": digest,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
