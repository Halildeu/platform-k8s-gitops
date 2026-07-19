#!/usr/bin/env python3
"""Verify a fetched GitHub evidence comment without normalizing its body.

The GitHub comment JSON is read from stdin.  In particular, the body is never
round-tripped through a shell command substitution before its receipt digest
is checked, so trailing newlines and every other UTF-8 byte remain bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

from post_cross_ai_evidence import validate_evidence_text


GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--body-sha256", required=True)
    parser.add_argument("--base-tip-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    if (
        not SHA256_RE.fullmatch(args.body_sha256)
        or not GIT_SHA_RE.fullmatch(args.base_tip_sha)
        or not GIT_SHA_RE.fullmatch(args.base_sha)
        or not GIT_SHA_RE.fullmatch(args.head_sha)
        or not SHA256_RE.fullmatch(args.scope_sha256)
        or args.model not in {"gpt-5.3-codex-spark", "gpt-5.6-sol"}
    ):
        raise SystemExit(2)

    try:
        comment = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        raise SystemExit(1)

    body = comment.get("body") if isinstance(comment, dict) else None
    user = comment.get("user") if isinstance(comment, dict) else None
    if (
        not isinstance(body, str)
        or not body
        or not isinstance(user, dict)
        or user.get("login") != args.owner
        or comment.get("author_association") != "OWNER"
        or not comment.get("created_at")
        or comment.get("created_at") != comment.get("updated_at")
        or hashlib.sha256(body.encode("utf-8")).hexdigest() != args.body_sha256
    ):
        raise SystemExit(1)

    evidence, validated_body_sha256 = validate_evidence_text(body)
    if (
        validated_body_sha256 != args.body_sha256
        or evidence.get("provider") != "openai"
        or evidence.get("requested_model") != args.model
        or evidence.get("actual_model") != args.model
        or evidence.get("reasoning_effort") != "xhigh"
        or evidence.get("sandbox") != "read-only"
        or evidence.get("ephemeral") is not True
        or evidence.get("base_tip_sha") != args.base_tip_sha
        or evidence.get("base_sha") != args.base_sha
        or evidence.get("head_sha") != args.head_sha
        or evidence.get("scope_sha256") != args.scope_sha256
        or evidence.get("verdict") != "AGREE"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
