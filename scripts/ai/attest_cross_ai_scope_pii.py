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
from pathlib import Path
from typing import NoReturn


SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
SCHEMA = "cross-ai-pii-review-attestation/v1"
DECISION = "no-sensitive-pii"
REVIEWER_ROLE = "local-scope-reviewer"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-file", type=Path, required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--decision", choices=(DECISION,), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not SHA256_RE.fullmatch(args.scope_sha256):
        fail("invalid_scope_sha256")
    if os.path.lexists(args.output):
        fail("pii_attestation_output_exists")
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
