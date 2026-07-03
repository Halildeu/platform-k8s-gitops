#!/usr/bin/env python3
"""Verify Faz 22.6 Denetim SSH public-key operator evidence.

This verifier consumes the metadata JSON emitted on Denetim PC after adding the
staging-sw runner public key for svc-denetim-agent. It proves only the SSH
authorization precondition for the #1580 VIEW_ONLY smoke. It does not prove a
VIEW_ONLY session, does not write the #1580 engineering marker, and does not
carry KVKK/legal signoff.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "faz22.6-denetim-ssh-key-operator-v1"
SUMMARY_SCHEMA_VERSION = "faz22.6-denetim-ssh-key-evidence-verification-v1"
DEFAULT_USER = "svc-denetim-agent"
DEFAULT_PUBLIC_KEY_FINGERPRINT = "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y"
DEFAULT_PUBLIC_KEY_LINE_SHA256 = "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff"

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]+={0,2}$")
SID_RE = re.compile(r"^S-\d(?:-\d+)+$")
UTC_O_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:\\")

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"ssh-ed25519\s+[A-Za-z0-9+/]+={0,3}"),
]


@dataclass
class Finding:
    code: str
    message: str


def iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, child
            yield from iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, child
            yield from iter_values(child, child_path)


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [Finding("json_parse", f"{path}: invalid JSON: {exc}")]
    except OSError as exc:
        return None, [Finding("json_read", f"{path}: cannot read file: {exc}")]

    if not isinstance(data, dict):
        return None, [Finding("json_shape", "top-level evidence must be a JSON object")]
    return data, []


def validate_no_secret_like_values(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for path, value in iter_values(data):
        if not isinstance(value, str):
            continue
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                findings.append(
                    Finding(
                        "secret_like_value",
                        f"{path}: value matches private-key/token/raw-public-key pattern",
                    )
                )
                break
    return findings


def require_equal(findings: list[Finding], code: str, label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        findings.append(Finding(code, f"{label}: expected {expected!r}, got {actual!r}"))


def require_bool(findings: list[Finding], label: str, value: Any, expected: bool) -> None:
    if value is not expected:
        findings.append(Finding("flag_value", f"{label}: must be {str(expected).lower()}"))


def require_nonempty_string(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        findings.append(Finding("string_shape", f"{label}: must be a non-empty string"))


def validate_evidence(data: dict[str, Any], args: argparse.Namespace) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(validate_no_secret_like_values(data))

    require_equal(findings, "schema_version", "schemaVersion", data.get("schemaVersion"), SCHEMA_VERSION)
    require_equal(findings, "user_name", "userName", data.get("userName"), args.expected_user)
    require_equal(
        findings,
        "runner_public_key_fingerprint",
        "runnerPublicKeyFingerprint",
        data.get("runnerPublicKeyFingerprint"),
        args.expected_public_key_fingerprint,
    )
    require_equal(
        findings,
        "runner_public_key_line_sha256",
        "runnerPublicKeyLineSha256",
        data.get("runnerPublicKeyLineSha256"),
        args.expected_public_key_line_sha256,
    )

    if not isinstance(data.get("runnerPublicKeyFingerprint"), str) or not FINGERPRINT_RE.match(
        data["runnerPublicKeyFingerprint"]
    ):
        findings.append(
            Finding("fingerprint_shape", "runnerPublicKeyFingerprint must be an OpenSSH SHA256 fingerprint")
        )
    if not isinstance(data.get("runnerPublicKeyLineSha256"), str) or not SHA256_HEX_RE.match(
        data["runnerPublicKeyLineSha256"]
    ):
        findings.append(Finding("sha256_shape", "runnerPublicKeyLineSha256 must be 64 lowercase hex chars"))

    require_bool(
        findings,
        "authorizedKeysContainsRunnerPublicKey",
        data.get("authorizedKeysContainsRunnerPublicKey"),
        True,
    )
    require_bool(findings, "isLocalAdministratorMember", data.get("isLocalAdministratorMember"), False)

    require_equal(findings, "sshd_status", "sshdStatus", data.get("sshdStatus"), "Running")
    if data.get("sshdStartType") == "Disabled":
        findings.append(Finding("sshd_start_type", "sshdStartType must not be Disabled"))
    require_nonempty_string(findings, "sshdStartType", data.get("sshdStartType"))

    if not isinstance(data.get("createdAtUtc"), str) or not UTC_O_RE.match(data["createdAtUtc"]):
        findings.append(Finding("timestamp_shape", "createdAtUtc must use UTC round-trip format ending in Z"))

    if "userSid" in data and (not isinstance(data["userSid"], str) or not SID_RE.match(data["userSid"])):
        findings.append(Finding("sid_shape", "userSid must have a Windows SID shape when present"))
    for field in ["profilePath", "authorizedKeysPath"]:
        if field in data and (not isinstance(data[field], str) or not WINDOWS_PATH_RE.match(data[field])):
            findings.append(Finding("windows_path_shape", f"{field} must be an absolute Windows path"))

    hygiene = data.get("evidenceHygiene")
    if not isinstance(hygiene, dict):
        findings.append(Finding("evidence_hygiene_shape", "evidenceHygiene must be an object"))
    else:
        require_bool(findings, "evidenceHygiene.privateKeyIncluded", hygiene.get("privateKeyIncluded"), False)
        require_bool(findings, "evidenceHygiene.rawSecretIncluded", hygiene.get("rawSecretIncluded"), False)
        require_bool(findings, "evidenceHygiene.tokenIncluded", hygiene.get("tokenIncluded"), False)
        require_bool(findings, "evidenceHygiene.publicKeyOnly", hygiene.get("publicKeyOnly"), True)

    return findings


def build_summary(data: dict[str, Any] | None, findings: list[Finding]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "status": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
        "boundary": "Denetim PC SSH key evidence only; not VIEW_ONLY evidence, not #1580 marker, not KVKK/legal signoff",
    }
    if data:
        summary.update(
            {
                "userName": data.get("userName"),
                "runnerPublicKeyFingerprint": data.get("runnerPublicKeyFingerprint"),
                "runnerPublicKeyLineSha256": data.get("runnerPublicKeyLineSha256"),
                "authorizedKeysContainsRunnerPublicKey": data.get("authorizedKeysContainsRunnerPublicKey"),
                "isLocalAdministratorMember": data.get("isLocalAdministratorMember"),
                "sshdStatus": data.get("sshdStatus"),
                "sshdStartType": data.get("sshdStartType"),
                "createdAtUtc": data.get("createdAtUtc"),
            }
        )
    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("--expected-user", default=DEFAULT_USER)
    parser.add_argument("--expected-public-key-fingerprint", default=DEFAULT_PUBLIC_KEY_FINGERPRINT)
    parser.add_argument("--expected-public-key-line-sha256", default=DEFAULT_PUBLIC_KEY_LINE_SHA256)
    parser.add_argument("--summary-json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    data, findings = load_json(args.evidence_json)
    if data is not None:
        findings.extend(validate_evidence(data, args))

    summary = build_summary(data, findings)
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if findings:
        print("Faz22.6 Denetim SSH key evidence: FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.code}: {finding.message}", file=sys.stderr)
        return 1

    print("Faz22.6 Denetim SSH key evidence: PASS")
    print(f"- userName={summary.get('userName')}")
    print(f"- runnerPublicKeyFingerprint={summary.get('runnerPublicKeyFingerprint')}")
    print(f"- sshdStatus={summary.get('sshdStatus')}")
    print(f"- authorizedKeysContainsRunnerPublicKey={summary.get('authorizedKeysContainsRunnerPublicKey')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
