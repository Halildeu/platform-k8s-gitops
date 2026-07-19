#!/usr/bin/env python3
"""Shared response validator; direct provider evidence building is disabled.

Authoritative OpenAI evidence is produced only by run_isolated_codex_review.py,
which executes and observes the fixed isolated Codex profile. Claude remains an
optional non-authoritative challenger until an equivalent verified harness
exists, so stdin responses cannot be repackaged as provider execution proof.
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
VERDICT_RE = re.compile(
    r"^VERDICT:[ \t]*(AGREE|REVISE)[ \t]*$", re.MULTILINE
)
PRIORITY_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?(P[012])(?:\*\*)?"
    r"(?:[ \t]*[—:-].*)?[ \t]*$"
)
NO_FINDINGS_RE = re.compile(r"^None$")
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
TURKISH_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+90|0090|0)\s*\(?5\d{2}\)?(?:[ .-]*\d){7}(?!\d)"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
BEARER_RE = re.compile(
    r"(?<![A-Za-z0-9])bearer[ \t]+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE
)
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\."
    r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
)
KNOWN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|xox[baprs]-[A-Za-z0-9-]{20,}"
    r"|sk_live_[A-Za-z0-9]{16,}"
    r")(?![A-Za-z0-9])"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|session[_-]?secret|"
    r"secret[_-]?access[_-]?key|service[_-]?account[_-]?key|"
    r"signing[_-]?key|hmac[_-]?key|private[_-]?key|credential)\b"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}[\"']?",
    re.IGNORECASE,
)
WEBHOOK_URL_RE = re.compile(
    r"\bwebhook[_-]?url\b\s*[:=]\s*https?://[^\s\"'<>]{12,}",
    re.IGNORECASE,
)
COOKIE_HEADER_RE = re.compile(
    r"^[ \t]*(?:set-)?cookie[ \t]*:[ \t]*[^\r\n]{12,}$",
    re.IGNORECASE | re.MULTILINE,
)
MAX_RESPONSE_BYTES = 48_000
MAX_EVIDENCE_BYTES = 60_000
UNATTESTED_ACTUAL_MODEL = "not-provider-attested"


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def priority_sections(response: str) -> dict[str, str] | None:
    headings = list(PRIORITY_HEADING_RE.finditer(response))
    if [match.group(1).upper() for match in headings] != ["P0", "P1", "P2"]:
        return None
    verdict_match = next(iter(VERDICT_RE.finditer(response)), None)
    if verdict_match is None:
        return None
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index < 2 else verdict_match.start()
        content = response[heading.end():end].strip()
        if not content:
            return None
        sections[heading.group(1).upper()] = content
    return sections


def contains_sensitive_response(response: str) -> bool:
    return bool(
        EMAIL_RE.search(response)
        or TURKISH_PHONE_RE.search(response)
        or PRIVATE_KEY_RE.search(response)
        or BEARER_RE.search(response)
        or JWT_RE.search(response)
        or KNOWN_TOKEN_RE.search(response)
        or SECRET_ASSIGNMENT_RE.search(response)
        or WEBHOOK_URL_RE.search(response)
        or COOKIE_HEADER_RE.search(response)
    )


def validate_provider_response(response: str) -> str:
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
    sections = priority_sections(response)
    if sections is None:
        fail("provider_findings_sections_missing_empty_duplicate_or_out_of_order")
    verdict = verdicts[0]
    if verdict == "AGREE" and (
        not NO_FINDINGS_RE.fullmatch(sections["P0"])
        or not NO_FINDINGS_RE.fullmatch(sections["P1"])
    ):
        fail("provider_agree_contains_p0_or_p1_findings")
    if contains_sensitive_response(response):
        fail("provider_response_contains_sensitive_data")
    return verdict


def serialize_evidence(
    *,
    provider: str,
    requested_model: str,
    actual_model: str,
    base_tip_sha: str,
    base_sha: str,
    head_sha: str,
    scope_sha256: str,
    response: str,
) -> str:
    del (
        provider,
        requested_model,
        actual_model,
        base_tip_sha,
        base_sha,
        head_sha,
        scope_sha256,
        response,
    )
    fail("direct_provider_evidence_builder_disabled")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--requested-model", required=True)
    parser.add_argument("--actual-model", required=True)
    parser.add_argument("--base-tip-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--scope-sha256", required=True)
    args = parser.parse_args()

    response = sys.stdin.read().strip()
    print(
        serialize_evidence(
            provider=args.provider,
            requested_model=args.requested_model,
            actual_model=args.actual_model,
            base_tip_sha=args.base_tip_sha,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            scope_sha256=args.scope_sha256,
            response=response,
        )
    )


if __name__ == "__main__":
    main()
