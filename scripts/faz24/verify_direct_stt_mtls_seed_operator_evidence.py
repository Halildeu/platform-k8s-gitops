#!/usr/bin/env python3
"""Validate Faz 24 direct-STT mTLS Vault seed operator evidence.

This verifier accepts only the redacted evidence emitted after the operator
helper applies the approved Vault KV v2 merge patch. It proves that the helper
ran with bounded inputs and no retained private material. It does not prove ESO
reconciliation, mounted Secret readiness, direct-STT enablement, /transcribe,
audio e2e, or production readiness.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA_VERSION = "faz24.directSttMtlsSeedOperatorEvidence.v1"
VERIFIER_SCHEMA_VERSION = "faz24.directSttMtlsSeedOperatorEvidenceVerifier.v1"

EXPECTED_OPERATION = "vault-kv-v2-merge-patch"
EXPECTED_VAULT_PATH = "kv/platform/audio-gateway-service"
EXPECTED_PROPERTIES = {
    "direct_stt_ca_crt",
    "direct_stt_client_crt",
    "direct_stt_client_key",
}
EXPECTED_INPUT_FILES = {
    "caCrt": "certificate",
    "clientCrt": "certificate",
    "clientKey": "private-key",
}
BOUNDARY_EXPECTATIONS = {
    "secretValuesIncluded": False,
    "vaultTokenIncluded": False,
    "localFilePathsIncluded": False,
    "rawCommandOutputIncluded": False,
    "kubernetesMutation": False,
    "directSttEnabled": False,
    "transcribeCalled": False,
    "rawAudioSent": False,
    "productionMutation": False,
}

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"-----END CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bAuthorization\s*:", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
    re.compile(r"\baudio/(wav|mpeg)\b", re.IGNORECASE),
    re.compile(r"https?://[^\s\"']+", re.IGNORECASE),
    re.compile(r"/transcribe\b", re.IGNORECASE),
    re.compile(r"(^|[\s\"'=])/(Users|home|tmp|private|var|secure|etc)/[^\s\"']*"),
    re.compile(r"\b[A-Za-z]:\\[^\s\"']+"),
]


@dataclass
class Check:
    name: str
    passed: bool
    message: str


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name=name, passed=passed, message=message))


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


def load_evidence(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    except OSError as exc:
        return None, f"cannot read evidence: {exc}"

    if not isinstance(data, dict):
        return None, "top-level evidence must be a JSON object"
    return data, None


def as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def string_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def validate_no_sensitive_content(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, value in iter_values(data):
        if not isinstance(value, str):
            continue
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                findings.append(f"{path}: secret-like, URL-like, local-path, or raw-media value")
                break

    add(
        checks,
        "no_sensitive_content",
        not findings,
        "redacted metadata only" if not findings else "; ".join(findings[:8]),
    )


def validate_top_level(data: dict[str, Any], checks: list[Check]) -> None:
    add(
        checks,
        "schema_version",
        data.get("schemaVersion") == EVIDENCE_SCHEMA_VERSION,
        f"schemaVersion must be {EVIDENCE_SCHEMA_VERSION}",
    )
    add(checks, "status_pass", data.get("status") == "pass", "status must be pass")
    add(
        checks,
        "failure_reason_empty",
        data.get("failureReason") in (None, ""),
        "failureReason must be absent, null, or empty",
    )
    add(
        checks,
        "generated_at",
        isinstance(data.get("generatedAt"), str)
        and bool(UTC_TIMESTAMP_RE.match(data["generatedAt"])),
        "generatedAt must use UTC YYYY-MM-DDTHH:MM:SSZ",
    )
    add(
        checks,
        "operation",
        data.get("operation") == EXPECTED_OPERATION,
        f"operation must be {EXPECTED_OPERATION}",
    )
    add(
        checks,
        "apply_requested",
        data.get("applyRequested") is True,
        "applyRequested must be true; dry-run evidence is not accepted",
    )


def validate_vault(data: dict[str, Any], checks: list[Check]) -> None:
    vault = data.get("vault")
    if not isinstance(vault, dict):
        add(checks, "vault_shape", False, "vault must be an object")
        return

    properties = string_list(vault.get("properties"))
    add(checks, "vault_path", vault.get("path") == EXPECTED_VAULT_PATH, f"vault.path must be {EXPECTED_VAULT_PATH}")
    add(
        checks,
        "vault_properties",
        properties is not None and set(properties) == EXPECTED_PROPERTIES and len(properties) == len(EXPECTED_PROPERTIES),
        f"vault.properties must exactly be {', '.join(sorted(EXPECTED_PROPERTIES))}",
    )
    add(checks, "vault_token_absent", vault.get("tokenIncluded") is False, "vault.tokenIncluded must be false")
    add(checks, "vault_addr_absent", vault.get("addrIncluded") is False, "vault.addrIncluded must be false")
    add(checks, "vault_token_source", vault.get("tokenSource") == "file", "vault.tokenSource must be file")
    add(checks, "vault_no_raw_token_field", "token" not in vault, "vault must not carry a raw token field")
    add(checks, "vault_no_raw_addr_field", "addr" not in vault and "address" not in vault, "vault must not carry a raw address field")


def validate_input_files(data: dict[str, Any], checks: list[Check]) -> None:
    input_files = data.get("inputFiles")
    if not isinstance(input_files, dict):
        add(checks, "input_files_shape", False, "inputFiles must be an object")
        return

    for key, content_kind in EXPECTED_INPUT_FILES.items():
        item = input_files.get(key)
        if not isinstance(item, dict):
            add(checks, f"input_{key}_shape", False, f"inputFiles.{key} must be an object")
            continue
        add(checks, f"input_{key}_provided", item.get("provided") is True, f"{key}.provided must be true")
        add(checks, f"input_{key}_format", item.get("formatAccepted") is True, f"{key}.formatAccepted must be true")
        add(
            checks,
            f"input_{key}_permissions",
            item.get("permissionsRestricted") is True,
            f"{key}.permissionsRestricted must be true",
        )
        add(
            checks,
            f"input_{key}_path_absent",
            item.get("pathIncluded") is False and "path" not in item and "localPath" not in item,
            f"{key} must not include a local path",
        )
        add(
            checks,
            f"input_{key}_value_absent",
            item.get("valueIncluded") is False and "value" not in item and "content" not in item,
            f"{key} must not include PEM content",
        )
        add(checks, f"input_{key}_content_kind", item.get("contentKind") == content_kind, f"{key}.contentKind must be {content_kind}")


def validate_result(data: dict[str, Any], checks: list[Check]) -> None:
    result = data.get("result")
    if not isinstance(result, dict):
        add(checks, "result_shape", False, "result must be an object")
        return

    http_status = as_int(result.get("httpStatus"))
    add(
        checks,
        "result_http_status",
        http_status is not None and 200 <= http_status <= 299,
        "result.httpStatus must be 2xx",
    )
    add(checks, "result_error_empty", result.get("errorClass") in (None, ""), "result.errorClass must be empty")
    if "vaultRequestIdPresent" in result:
        add(
            checks,
            "result_request_id_bool",
            isinstance(result.get("vaultRequestIdPresent"), bool),
            "result.vaultRequestIdPresent must be boolean when present",
        )


def validate_boundaries(data: dict[str, Any], checks: list[Check]) -> None:
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, dict):
        add(checks, "boundaries_shape", False, "boundaries must be an object")
        return
    for key, expected in BOUNDARY_EXPECTATIONS.items():
        add(checks, f"boundary_{key}", boundaries.get(key) is expected, f"{key} must be {str(expected).lower()}")


def validate_next_verification(data: dict[str, Any], checks: list[Check]) -> None:
    next_verification = string_list(data.get("nextVerification"))
    if next_verification is None:
        add(checks, "next_verification_shape", False, "nextVerification must be a string list")
        return

    joined = " ".join(next_verification).lower()
    add(checks, "next_verification_non_empty", len(next_verification) >= 4, "nextVerification must list the follow-up gates")
    add(checks, "next_verification_eso", "eso" in joined, "nextVerification must mention ESO reconciliation")
    add(checks, "next_verification_external_secret", "externalsecret" in joined, "nextVerification must mention ExternalSecret readiness")
    add(checks, "next_verification_secret_keys", "secret" in joined and "key" in joined, "nextVerification must mention runtime Secret key names")
    add(
        checks,
        "next_verification_preflight",
        "faz24-direct-stt-mtls-preflight-collect.yml" in joined or "preflight" in joined,
        "nextVerification must route to the direct-STT mTLS preflight collector",
    )


def verify(data: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    validate_no_sensitive_content(data, checks)
    validate_top_level(data, checks)
    validate_vault(data, checks)
    validate_input_files(data, checks)
    validate_result(data, checks)
    validate_boundaries(data, checks)
    validate_next_verification(data, checks)
    return checks


def write_summary(path: Path, checks: list[Check]) -> None:
    passed = all(check.passed for check in checks)
    summary = {
        "schemaVersion": VERIFIER_SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "status": "pass" if passed else "fail",
        "passed": sum(1 for check in checks if check.passed),
        "total": len(checks),
        "checks": [asdict(check) for check in checks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_human(checks: list[Check]) -> None:
    for check in checks:
        symbol = "OK" if check.passed else "FAIL"
        print(f"{symbol} {check.name}: {check.message}")
    passed = sum(1 for check in checks if check.passed)
    status = "PASS" if passed == len(checks) else "FAIL"
    print(f"\nFaz 24 direct-STT mTLS seed operator evidence: {status} ({passed}/{len(checks)})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence",
        nargs="?",
        type=Path,
        help="Evidence JSON path. Reads stdin when omitted.",
    )
    parser.add_argument("--summary-json", type=Path, help="Write machine-readable verifier summary JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data, error = load_evidence(args.evidence)
    if error is not None:
        print(f"FAIL evidence_load: {error}", file=sys.stderr)
        if args.summary_json:
            write_summary(args.summary_json, [Check("evidence_load", False, error)])
        return 1
    assert data is not None

    checks = verify(data)
    print_human(checks)
    if args.summary_json:
        write_summary(args.summary_json, checks)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
