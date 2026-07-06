#!/usr/bin/env python3
"""Verify Denetim-side Faz 24 I3 SSH authorization evidence.

This verifier consumes the metadata-only JSON produced by
`authorize-denetim-i3-public-key.ps1`. It does not need raw public key material
and must reject private keys, bearer tokens, command contents, or raw paths.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "faz24.i3.denetim.ssh-authorize-package.v1.evidence"
DEFAULT_TARGET_USER = "svc-denetim-agent"
DEFAULT_PUBLIC_KEY_FINGERPRINT = "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y"
DEFAULT_PUBLIC_KEY_LINE_SHA256 = "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff"
DEFAULT_PUBLIC_KEY_BLOB_SHA256 = "e2158a715d03df2ad17d6e2cae3d264096fedbdec9f919d2d07ba84740fab756"

PASS_REASONS = {"authorized-key-added", "authorized-key-present"}
RUNNING_STATUS = "Running"
HEX_16_RE = re.compile(r"^[0-9a-f]{16}$")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]+={0,2}$")

FORBIDDEN_KEY_NAMES = {
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "secret_id",
    "private_key",
    "privatekey",
    "bearer",
    "jwt",
    "cookie",
    "public_key",
    "publickey",
    "raw_public_key",
    "rawpublickey",
    "profile_path",
    "authorized_keys_path",
    "command_line",
    "commandline",
    "command_content",
    "commandcontent",
    "raw_command",
    "rawcommand",
}

SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"ssh-ed25519\s+[A-Za-z0-9+/]+={0,3}"),
    re.compile(r"\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\"'\r\n]+", re.IGNORECASE),
]


@dataclass
class Finding:
    code: str
    message: str


def normalized_key(key: str) -> str:
    return key.replace("-", "_").replace(".", "_").strip().lower()


def iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, None, child


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


def validate_no_leaks(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for path, key, value in iter_values(data):
        if key is not None and normalized_key(key) in FORBIDDEN_KEY_NAMES:
            findings.append(
                Finding(
                    "forbidden_key",
                    f"{path}: key '{key}' is not allowed in metadata-only evidence",
                )
            )
            continue

        if isinstance(value, str):
            for pattern in SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        Finding(
                            "secret_like_value",
                            f"{path}: value matches secret/token/private-key/public-key pattern",
                        )
                    )
                    break
    return findings


def require_equal(findings: list[Finding], code: str, label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        findings.append(Finding(code, f"{label}: expected {expected!r}, got {actual!r}"))


def require_bool_false(findings: list[Finding], label: str, value: Any) -> None:
    if value is not False:
        findings.append(Finding("flag_must_be_false", f"{label}: must be false"))


def require_bool_true(findings: list[Finding], label: str, value: Any) -> None:
    if value is not True:
        findings.append(Finding("flag_must_be_true", f"{label}: must be true"))


def require_optional_bool(findings: list[Finding], label: str, data: dict[str, Any]) -> None:
    if label in data and data[label] is not True and data[label] is not False:
        findings.append(Finding("boolean_shape", f"{label} must be boolean when present"))


def require_sha256_hex(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not SHA256_HEX_RE.match(value):
        findings.append(Finding("sha256_shape", f"{label}: must be 64 lowercase hex chars"))


def require_hash16(findings: list[Finding], label: str, value: Any) -> None:
    if not isinstance(value, str) or not HEX_16_RE.match(value):
        findings.append(Finding("hash16_shape", f"{label}: must be 16 lowercase hex chars"))


def validate_evidence(data: dict[str, Any], args: argparse.Namespace) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(validate_no_leaks(data))

    require_equal(findings, "schema_version", "schemaVersion", data.get("schemaVersion"), SCHEMA_VERSION)
    if not isinstance(data.get("collectedAt"), str) or not UTC_TIMESTAMP_RE.match(data["collectedAt"]):
        findings.append(Finding("timestamp_shape", "collectedAt must use UTC format YYYY-MM-DDTHH:MM:SSZ"))

    require_equal(findings, "status", "status", data.get("status"), "pass")
    if data.get("reason") not in PASS_REASONS:
        findings.append(
            Finding(
                "reason",
                f"reason must be one of {sorted(PASS_REASONS)}, got {data.get('reason')!r}",
            )
        )

    require_equal(findings, "target_user", "targetUser", data.get("targetUser"), args.expected_target_user)
    require_equal(
        findings,
        "expected_public_key_fingerprint",
        "expectedPublicKeyFingerprint",
        data.get("expectedPublicKeyFingerprint"),
        args.expected_public_key_fingerprint,
    )
    require_equal(
        findings,
        "public_key_fingerprint",
        "publicKeyFingerprint",
        data.get("publicKeyFingerprint"),
        args.expected_public_key_fingerprint,
    )
    if not isinstance(data.get("publicKeyFingerprint"), str) or not FINGERPRINT_RE.match(data["publicKeyFingerprint"]):
        findings.append(Finding("fingerprint_shape", "publicKeyFingerprint must be an OpenSSH SHA256 fingerprint"))

    for field, expected in [
        ("expectedPublicKeyLineSha256", args.expected_public_key_line_sha256),
        ("publicKeyLineSha256", args.expected_public_key_line_sha256),
        ("expectedPublicKeyBlobSha256", args.expected_public_key_blob_sha256),
        ("publicKeyBlobSha256", args.expected_public_key_blob_sha256),
    ]:
        require_equal(findings, field, field, data.get(field), expected)
        require_sha256_hex(findings, field, data.get(field))

    require_bool_false(findings, "privateKeyIncluded", data.get("privateKeyIncluded"))
    require_bool_false(findings, "rawPublicKeyIncluded", data.get("rawPublicKeyIncluded"))
    require_bool_true(findings, "aclHardened", data.get("aclHardened"))

    for field in [
        "targetUserCreated",
        "targetUserExisted",
        "targetUserEnabled",
        "eventLogReadersGrantAttempted",
        "eventLogReadersMembershipPresent",
        "profileRegistryPresent",
        "profileCreated",
        "profileFallbackUsed",
    ]:
        require_optional_bool(findings, field, data)

    if "targetUserEnabled" in data:
        require_bool_true(findings, "targetUserEnabled", data.get("targetUserEnabled"))
    if data.get("targetUserCreated") is True and data.get("targetUserExisted") is True:
        findings.append(Finding("target_user_state", "targetUserCreated and targetUserExisted cannot both be true"))
    if data.get("targetUserCreated") is False and data.get("targetUserExisted") is False:
        findings.append(Finding("target_user_state", "targetUserCreated or targetUserExisted must be true when both are present"))
    if data.get("eventLogReadersGrantAttempted") is True and data.get("eventLogReadersMembershipPresent") is not True:
        findings.append(
            Finding(
                "event_log_readers_membership",
                "eventLogReadersMembershipPresent must be true when eventLogReadersGrantAttempted is true",
            )
        )

    key_added = data.get("keyAdded")
    key_already_present = data.get("keyAlreadyPresent")
    if key_added is not True and key_already_present is not True:
        findings.append(Finding("key_presence", "keyAdded or keyAlreadyPresent must be true"))
    if key_added is True and key_already_present is True:
        findings.append(Finding("key_presence", "keyAdded and keyAlreadyPresent cannot both be true"))
    if key_added is not True and key_added is not False:
        findings.append(Finding("boolean_shape", "keyAdded must be boolean"))
    if key_already_present is not True and key_already_present is not False:
        findings.append(Finding("boolean_shape", "keyAlreadyPresent must be boolean"))
    if data.get("sshdRestartAttempted") is not True and data.get("sshdRestartAttempted") is not False:
        findings.append(Finding("boolean_shape", "sshdRestartAttempted must be boolean"))

    require_hash16(findings, "targetUserSidHash", data.get("targetUserSidHash"))
    require_hash16(findings, "profilePathHash", data.get("profilePathHash"))
    require_hash16(findings, "authorizedKeysPathHash", data.get("authorizedKeysPathHash"))

    require_equal(
        findings,
        "sshd_service_status",
        "sshdServiceStatusAfter",
        data.get("sshdServiceStatusAfter"),
        RUNNING_STATUS,
    )
    if not isinstance(data.get("sshdServiceStatusBefore"), str) or not data["sshdServiceStatusBefore"]:
        findings.append(Finding("sshd_service_status", "sshdServiceStatusBefore must be a non-empty string"))

    return findings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("--expected-target-user", default=DEFAULT_TARGET_USER)
    parser.add_argument("--expected-public-key-fingerprint", default=DEFAULT_PUBLIC_KEY_FINGERPRINT)
    parser.add_argument("--expected-public-key-line-sha256", default=DEFAULT_PUBLIC_KEY_LINE_SHA256)
    parser.add_argument("--expected-public-key-blob-sha256", default=DEFAULT_PUBLIC_KEY_BLOB_SHA256)
    parser.add_argument("--summary-json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    data, findings = load_json(args.evidence_json)
    if data is not None:
        findings.extend(validate_evidence(data, args))

    summary = {
        "schemaVersion": "faz24.i3.denetim.ssh-authorize-evidence-verification.v1",
        "status": "pass" if not findings else "fail",
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    if data:
        summary["targetUser"] = data.get("targetUser")
        summary["publicKeyFingerprint"] = data.get("publicKeyFingerprint")
        summary["reason"] = data.get("reason")
        summary["sshdServiceStatusAfter"] = data.get("sshdServiceStatusAfter")

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if findings:
        print("Faz24 I3 Denetim SSH authorize evidence: FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.code}: {finding.message}", file=sys.stderr)
        return 1

    print("Faz24 I3 Denetim SSH authorize evidence: PASS")
    print(f"- targetUser={summary.get('targetUser')}")
    print(f"- publicKeyFingerprint={summary.get('publicKeyFingerprint')}")
    print(f"- reason={summary.get('reason')}")
    print(f"- sshdServiceStatusAfter={summary.get('sshdServiceStatusAfter')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
