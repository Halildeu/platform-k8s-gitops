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
import platform
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, NoReturn


SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCHEMA = "cross-ai-pii-review-attestation/v3"
DECISION = "no-sensitive-pii"
REVIEWER_ROLE = "authenticated-repository-owner"
MAX_SCOPE_BYTES = 2_000_000
MAX_GH_NATIVE_BYTES = 128 * 1024 * 1024
GH_VERSION_RE = re.compile(r"^gh version ([0-9]+\.[0-9]+\.[0-9]+) \([^)]+\)$")
GH_PLATFORM_TARGETS = {
    ("darwin", "arm64"): "gh-darwin-arm64",
    ("darwin", "aarch64"): "gh-darwin-arm64",
    ("darwin", "x86_64"): "gh-darwin-x64",
    ("linux", "arm64"): "gh-linux-arm64",
    ("linux", "aarch64"): "gh-linux-arm64",
    ("linux", "x86_64"): "gh-linux-x64",
    ("linux", "amd64"): "gh-linux-x64",
}
TRUSTED_GH_NATIVE_SHA256 = {
    ("2.92.0", "gh-darwin-arm64"): (
        # Official gh_2.92.0_macOS_arm64.zip native binary.
        "23153214eb1736a96d659fca3b8c50ebe15f8e679abd00a665f287d1465e303e",
        # Homebrew 2.92.0 arm64 bottle installed on the operator Mac.
        "582a40676acf1394fcaf1c8c8bc5bad21806bd8c864b209d37b185c2df45dc92",
    ),
    ("2.92.0", "gh-darwin-x64"): (
        "8e89e1252a70e7a7d609d50bd1e3e727af66b2678f5282a9f4750a238f8aec2e",
    ),
    ("2.92.0", "gh-linux-arm64"): (
        "007955ea7dca7c1372c4f4da380d4b35040e641177b5e1e2f1be5121436d17ef",
    ),
    ("2.92.0", "gh-linux-x64"): (
        "b58e487e37c00c114aa07f14987ce12f5e5abf12b9da8a38937b65ef218f6772",
    ),
}


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


def resolve_gh_native(
    trusted_gh_native_sha256: dict[
        tuple[str, str], str | tuple[str, ...]
    ] | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Resolve one repo-pinned native GitHub CLI, never an arbitrary PATH shim."""
    target = GH_PLATFORM_TARGETS.get(
        (platform.system().lower(), platform.machine().lower())
    )
    candidate = shutil.which("gh")
    if target is None or candidate is None:
        fail("gh_native_untrusted")
    try:
        native = Path(candidate).resolve(strict=True)
        native_stat = native.stat()
        native_bytes = native.read_bytes()
    except OSError:
        fail("gh_native_untrusted")
    if (
        not stat.S_ISREG(native_stat.st_mode)
        or native_stat.st_mode & 0o022
        or not native_bytes
        or len(native_bytes) > MAX_GH_NATIVE_BYTES
    ):
        fail("gh_native_untrusted")
    try:
        version_result = runner(
            [str(native), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("gh_native_untrusted")
    first_line = version_result.stdout.splitlines()[0] if version_result.stdout else ""
    version_match = GH_VERSION_RE.fullmatch(first_line)
    pins = trusted_gh_native_sha256 or TRUSTED_GH_NATIVE_SHA256
    digest = hashlib.sha256(native_bytes).hexdigest()
    accepted_pin = (
        pins.get((version_match.group(1), target)) if version_match else None
    )
    accepted_digests = (
        {accepted_pin}
        if isinstance(accepted_pin, str)
        else set(accepted_pin or ())
    )
    if (
        version_result.returncode != 0
        or version_result.stderr.strip()
        or version_match is None
        or digest not in accepted_digests
    ):
        fail("gh_native_untrusted")
    return native


def gh_json(
    gh: Path,
    path: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict:
    try:
        result = runner(
            [str(gh), "api", "--hostname", "github.com", path, "--method", "GET"],
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


def verify_authenticated_repository_owner(
    repo: str,
    *,
    trusted_gh_native_sha256: dict[
        tuple[str, str], str | tuple[str, ...]
    ] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict:
    if REPO_RE.fullmatch(repo) is None:
        fail("pii_reviewer_identity_unverifiable")
    gh = resolve_gh_native(trusted_gh_native_sha256, runner=runner)
    actor = gh_json(gh, "user", runner=runner)
    repository = gh_json(gh, f"repos/{repo}", runner=runner)
    login = actor.get("login")
    owner = repository.get("owner")
    permissions = repository.get("permissions")
    reviewer_id = actor.get("id")
    repository_id = repository.get("id")
    if (
        not isinstance(login, str)
        or not isinstance(reviewer_id, int)
        or reviewer_id < 1
        or not isinstance(repository_id, int)
        or repository_id < 1
        or not isinstance(owner, dict)
        or not isinstance(owner.get("login"), str)
        or owner.get("id") != reviewer_id
        or not isinstance(permissions, dict)
        or permissions.get("admin") is not True
        or repository.get("full_name", "").lower() != repo.lower()
        or login.lower() != owner["login"].lower()
        or login.lower() != repo.split("/", 1)[0].lower()
        or actor.get("url", "").lower()
        != f"https://api.github.com/users/{login}".lower()
        or actor.get("html_url", "").lower()
        != f"https://github.com/{login}".lower()
        or owner.get("url", "").lower()
        != f"https://api.github.com/users/{login}".lower()
        or owner.get("html_url", "").lower()
        != f"https://github.com/{login}".lower()
        or repository.get("url", "").lower()
        != f"https://api.github.com/repos/{repo}".lower()
        or repository.get("html_url", "").lower()
        != f"https://github.com/{repo}".lower()
    ):
        fail("pii_reviewer_not_repository_owner")
    return {
        "repository": repository["full_name"],
        "repository_id": repository_id,
        "reviewer_login": login,
        "reviewer_id": reviewer_id,
    }


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
    owner_identity = verify_authenticated_repository_owner(args.repo)
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
            **owner_identity,
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
