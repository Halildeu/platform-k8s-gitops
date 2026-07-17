#!/usr/bin/env python3
"""Validate and post one Cross-AI evidence comment without exposing its body.

The GitHub token stays inside the authenticated ``gh`` process. The evidence
body is sent over stdin, never argv, and this helper prints only the API ref,
timestamps and content digest required by the PR receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_BYTES = 60_000
EVIDENCE_KEYS = {
    "schema",
    "provider",
    "requested_model",
    "actual_model",
    "base_tip_sha",
    "base_sha",
    "head_sha",
    "scope_sha256",
    "verdict",
    "response_sha256",
    "response",
}


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def validate_evidence_text(text: str) -> tuple[dict, str]:
    encoded = text.encode("utf-8")
    if not encoded or len(encoded) > MAX_EVIDENCE_BYTES:
        fail("invalid_evidence_size")
    try:
        evidence = json.loads(text)
    except json.JSONDecodeError:
        fail("invalid_evidence_json")
    if not isinstance(evidence, dict) or set(evidence) != EVIDENCE_KEYS:
        fail("invalid_evidence_schema")
    if evidence.get("schema") != "cross-ai-provider-evidence/v1":
        fail("invalid_evidence_schema")
    response = evidence.get("response")
    response_digest = evidence.get("response_sha256")
    if (
        not isinstance(response, str)
        or not response
        or not isinstance(response_digest, str)
        or not SHA256_RE.fullmatch(response_digest)
        or hashlib.sha256(response.encode("utf-8")).hexdigest() != response_digest
    ):
        fail("invalid_response_digest")
    return evidence, hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    args = parser.parse_args()

    if not REPO_RE.fullmatch(args.repo) or args.issue < 1:
        fail("invalid_github_target")
    if shutil.which("gh") is None:
        fail("gh_unavailable")
    try:
        text = args.evidence_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        fail("evidence_file_unreadable")
    evidence, body_sha256 = validate_evidence_text(text)
    payload = json.dumps({"body": text}, ensure_ascii=False, separators=(",", ":"))
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{args.repo}/issues/{args.issue}/comments",
                "--method",
                "POST",
                "--input",
                "-",
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
    print(
        json.dumps(
            {
                "ok": True,
                "provider": evidence["provider"],
                "actual_model": evidence["actual_model"],
                "verdict": evidence["verdict"],
                "ref": api_ref,
                "sha256": body_sha256,
                "created_at": created_at,
                "updated_at": updated_at,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
