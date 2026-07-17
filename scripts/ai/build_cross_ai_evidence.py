#!/usr/bin/env python3
"""Build one strict cross-ai-provider-evidence/v1 JSON comment body.

The full provider response is read from stdin so it never enters process argv.
The resulting single-line JSON can be posted as an issue comment; the PR receipt
uses SHA-256 of these exact UTF-8 bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import NoReturn


COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
VERDICT_RE = re.compile(r"^VERDICT:\s*(AGREE|REVISE)\s*$", re.IGNORECASE | re.MULTILINE)
PROVIDER_MODELS = {
    "anthropic": "claude-opus-4-8",
    "minimax": "minimax/MiniMax-M3",
    "openai": "gpt-5.6-sol",
}
MAX_RESPONSE_BYTES = 48_000


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=sorted(PROVIDER_MODELS), required=True)
    parser.add_argument("--requested-model", required=True)
    parser.add_argument("--actual-model", required=True)
    parser.add_argument("--base-tip-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--scope-sha256", required=True)
    args = parser.parse_args()

    expected_model = PROVIDER_MODELS[args.provider]
    if args.requested_model != expected_model or args.actual_model != expected_model:
        fail("provider_model_mismatch")
    for value in (args.base_tip_sha, args.base_sha, args.head_sha):
        if not COMMIT_SHA_RE.fullmatch(value):
            fail("invalid_commit_sha")
    if not SHA256_RE.fullmatch(args.scope_sha256):
        fail("invalid_scope_sha256")

    response = sys.stdin.read().strip()
    if not response:
        fail("provider_response_required")
    if len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
        fail("provider_response_too_large")
    verdicts = VERDICT_RE.findall(response)
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if (
        len(verdicts) != 1
        or not lines
        or not VERDICT_RE.fullmatch(lines[-1])
    ):
        fail("provider_verdict_missing_ambiguous_or_nonterminal")
    for priority in ("P0", "P1", "P2"):
        heading = re.compile(
            rf"(?im)^\s*(?:#{{1,6}}\s*)?(?:\*\*)?{priority}(?:\*\*)?"
            r"(?:\s*[—:-].*)?\s*$"
        )
        if not heading.search(response):
            fail("provider_findings_sections_missing")
    verdict = verdicts[0].upper()
    response_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest()
    print(
        json.dumps(
            {
                "schema": "cross-ai-provider-evidence/v1",
                "provider": args.provider,
                "requested_model": args.requested_model,
                "actual_model": args.actual_model,
                "base_tip_sha": args.base_tip_sha.lower(),
                "base_sha": args.base_sha.lower(),
                "head_sha": args.head_sha.lower(),
                "scope_sha256": args.scope_sha256.lower(),
                "verdict": verdict,
                "response_sha256": response_sha256,
                "response": response,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
