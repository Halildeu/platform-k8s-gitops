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
THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
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
UNATTESTED_ACTUAL_MODEL = "not-provider-attested"
CODEX_NATIVE_TRUST_ROOT = "repo-pinned-codex-native-sha256-v1"
TRUSTED_CODEX_NATIVE_SHA256 = {
    ("0.144.1", "codex-darwin-arm64"): "29915529b97697def1a957b0505e770aa6a45744435d62fc263e98d7619e167a",
    ("0.144.1", "codex-darwin-x64"): "c6eb747e4145ecb3bed2647dbd0f8464b190a5ccba964666ef7c98d4681a4a4c",
    ("0.144.1", "codex-linux-arm64"): "9513fa3f5f4ad444ac1e40d972aef0e2664834ec54da987d54aba0dc2f13ea07",
    ("0.144.1", "codex-linux-x64"): "a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902",
}
CODEX_PROVENANCE_KEYS = {
    "schema",
    "thread_id",
    "cli_version",
    "cli_native_target",
    "cli_native_sha256",
    "trust_root",
    "stderr_classification",
}
EVIDENCE_KEYS = {
    "schema",
    "provider",
    "requested_model",
    "actual_model",
    "execution_profile",
    "execution_provenance",
    "base_tip_sha",
    "base_sha",
    "head_sha",
    "scope_sha256",
    "verdict",
    "response_sha256",
    "response",
}
PROVIDER_EXECUTION_PROFILES = {
    "anthropic": "claude-cli-no-session-persistence-exact-scope-v1",
    "openai": "codex-exec-ephemeral-read-only-exact-scope-no-tools-v2",
}
PROVIDER_MODELS = {
    "anthropic": ("claude-opus-4-8",),
    "openai": ("gpt-5.3-codex-spark", "gpt-5.6-sol"),
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
    if evidence.get("schema") != "cross-ai-provider-evidence/v3":
        fail("invalid_evidence_schema")
    expected_execution = PROVIDER_EXECUTION_PROFILES.get(evidence.get("provider"))
    if evidence.get("execution_profile") != expected_execution:
        fail("invalid_execution_profile")
    expected_models = PROVIDER_MODELS.get(evidence.get("provider"), ())
    actual_model_valid = (
        evidence.get("actual_model") == UNATTESTED_ACTUAL_MODEL
        if evidence.get("provider") == "openai"
        else evidence.get("actual_model") == evidence.get("requested_model")
    )
    if evidence.get("requested_model") not in expected_models or not actual_model_valid:
        fail("provider_model_mismatch")
    provenance = evidence.get("execution_provenance")
    if evidence.get("provider") == "openai":
        if not isinstance(provenance, dict) or set(provenance) != CODEX_PROVENANCE_KEYS:
            fail("invalid_execution_provenance")
        pin = TRUSTED_CODEX_NATIVE_SHA256.get(
            (provenance.get("cli_version"), provenance.get("cli_native_target"))
        )
        native_sha256 = provenance.get("cli_native_sha256")
        if (
            provenance.get("schema") != "codex-native-execution-provenance/v1"
            or provenance.get("trust_root") != CODEX_NATIVE_TRUST_ROOT
            or provenance.get("stderr_classification") not in {
                "empty",
                "allowlisted-model-cache-schema-warning-v1",
            }
            or not isinstance(provenance.get("thread_id"), str)
            or THREAD_ID_RE.fullmatch(provenance["thread_id"]) is None
            or pin is None
            or not isinstance(native_sha256, str)
            or SHA256_RE.fullmatch(native_sha256) is None
            or native_sha256 != pin
        ):
            fail("invalid_execution_provenance")
    elif provenance is not None:
        fail("invalid_execution_provenance")
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
                "execution_profile": evidence["execution_profile"],
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
