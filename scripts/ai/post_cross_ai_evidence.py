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
VERDICT_RE = re.compile(r"^VERDICT:[ \t]*(AGREE|REVISE)[ \t]*$", re.MULTILINE)
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
MAX_EVIDENCE_BYTES = 60_000
EVIDENCE_KEYS = {
    "schema",
    "provider",
    "requested_model",
    "actual_model",
    "reasoning_effort",
    "sandbox",
    "ephemeral",
    "base_tip_sha",
    "base_sha",
    "head_sha",
    "scope_sha256",
    "verdict",
    "response_sha256",
    "response",
}


def response_contract(response: str) -> tuple[str, dict[str, str]] | None:
    verdicts = VERDICT_RE.findall(response)
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    headings = list(PRIORITY_HEADING_RE.finditer(response))
    if (
        len(verdicts) != 1
        or not lines
        or not VERDICT_RE.fullmatch(lines[-1])
        or [match.group(1).upper() for match in headings] != ["P0", "P1", "P2"]
    ):
        return None
    verdict_match = next(iter(VERDICT_RE.finditer(response)))
    sections: dict[str, str] = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index < 2 else verdict_match.start()
        content = response[heading.end():end].strip()
        if not content:
            return None
        sections[heading.group(1).upper()] = content
    verdict = verdicts[0]
    if verdict == "AGREE" and (
        not NO_FINDINGS_RE.fullmatch(sections["P0"])
        or not NO_FINDINGS_RE.fullmatch(sections["P1"])
        or not NO_FINDINGS_RE.fullmatch(sections["P2"])
    ):
        return None
    return verdict, sections


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
    if evidence.get("schema") != "cross-ai-provider-evidence/v2":
        fail("invalid_evidence_schema")
    if (
        evidence.get("provider") != "openai"
        or evidence.get("requested_model") not in {"gpt-5.3-codex-spark", "gpt-5.6-sol"}
        or evidence.get("actual_model") != evidence.get("requested_model")
        or evidence.get("reasoning_effort") != "xhigh"
        or evidence.get("sandbox") != "read-only"
        or evidence.get("ephemeral") is not True
    ):
        fail("invalid_execution_identity")
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
    parsed_response = response_contract(response)
    if parsed_response is None or evidence.get("verdict") != parsed_response[0]:
        fail("invalid_response_semantics")
    if (
        EMAIL_RE.search(response)
        or TURKISH_PHONE_RE.search(response)
        or PRIVATE_KEY_RE.search(response)
        or BEARER_RE.search(response)
        or JWT_RE.search(response)
        or KNOWN_TOKEN_RE.search(response)
        or SECRET_ASSIGNMENT_RE.search(response)
        or WEBHOOK_URL_RE.search(response)
        or COOKIE_HEADER_RE.search(response)
    ):
        fail("provider_response_contains_sensitive_data")
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
