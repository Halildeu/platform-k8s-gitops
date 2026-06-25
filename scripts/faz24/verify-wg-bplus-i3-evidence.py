#!/usr/bin/env python3
"""Validate Faz 24 WG-B+ I3 management audit evidence.

The I3 gate is intentionally metadata-only: it must prove who/when/what for
management access and drift monitors without carrying command contents,
secrets, raw audio, or transcript text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "faz24.wg-bplus.i3.audit.v1"

REQUIRED_CHECK_IDS = [
    "openssh-event-log",
    "powershell-transcription",
    "powershell-script-block",
    "failed-login",
    "wireguard-health",
    "eset-firewall-drift",
    "time-sync",
    "staging-connection-log",
]

REDACTION_FLAGS = [
    "rawAudioIncluded",
    "rawTranscriptIncluded",
    "secretMaterialIncluded",
    "commandContentIncluded",
]

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
    "audio_bytes",
    "audiobytes",
    "audio_base64",
    "audiobase64",
    "transcript_text",
    "transcripttext",
    "script_block_text",
    "scriptblocktext",
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
]

UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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
                            f"{path}: value matches secret/token/private-key pattern",
                        )
                    )
                    break
    return findings


def validate_required_metadata(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    if data.get("schemaVersion") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "schema_version",
                f"schemaVersion must be '{SCHEMA_VERSION}'",
            )
        )

    collected_at = data.get("collectedAt")
    if not isinstance(collected_at, str) or not collected_at.strip():
        findings.append(Finding("required_field", "collectedAt must be a non-empty string"))
    elif not UTC_TIMESTAMP_RE.match(collected_at):
        findings.append(
            Finding("timestamp_format", "collectedAt must use UTC format YYYY-MM-DDTHH:MM:SSZ")
        )

    protected_path = data.get("protectedEvidencePath")
    if not isinstance(protected_path, str) or not protected_path.strip():
        findings.append(
            Finding("required_field", "protectedEvidencePath must be a non-empty string")
        )

    retention_days = data.get("retentionDays")
    if not isinstance(retention_days, int) or not 7 <= retention_days <= 365:
        findings.append(
            Finding(
                "retention_days",
                "retentionDays must be an integer between 7 and 365",
            )
        )

    acl = data.get("acl")
    if not isinstance(acl, dict):
        findings.append(Finding("acl", "acl must be an object"))
    else:
        if acl.get("mode") != "protected":
            findings.append(Finding("acl_mode", "acl.mode must be 'protected'"))
        readers = acl.get("readers")
        writers = acl.get("writers")
        if not isinstance(readers, list) or not readers:
            findings.append(Finding("acl_readers", "acl.readers must be a non-empty list"))
        if not isinstance(writers, list) or not writers:
            findings.append(Finding("acl_writers", "acl.writers must be a non-empty list"))

    redaction = data.get("redaction")
    if not isinstance(redaction, dict):
        findings.append(Finding("redaction", "redaction must be an object"))
    else:
        for flag in REDACTION_FLAGS:
            if redaction.get(flag) is not False:
                findings.append(Finding("redaction_flag", f"redaction.{flag} must be false"))

    return findings


def validate_checks(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    checks = data.get("checks")
    if not isinstance(checks, list):
        return [Finding("checks", "checks must be a list")]

    by_id: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            findings.append(Finding("check_shape", f"checks[{index}] must be an object"))
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            findings.append(Finding("check_id", f"checks[{index}].id must be non-empty"))
            continue
        if check_id in by_id:
            findings.append(Finding("duplicate_check", f"duplicate check id '{check_id}'"))
        by_id[check_id] = check

    for required_id in REQUIRED_CHECK_IDS:
        check = by_id.get(required_id)
        if check is None:
            findings.append(Finding("missing_check", f"missing required check '{required_id}'"))
            continue

        if check.get("status") != "pass":
            findings.append(Finding("check_status", f"{required_id}: status must be 'pass'"))

        for field in ["who", "when", "what", "evidenceRef"]:
            value = check.get(field)
            if not isinstance(value, str) or not value.strip():
                findings.append(
                    Finding("check_required_field", f"{required_id}: {field} must be non-empty")
                )
            elif "\n" in value or len(value) > 220:
                findings.append(
                    Finding(
                        "check_field_bounds",
                        f"{required_id}: {field} must be single-line and <= 220 chars",
                    )
                )

        when = check.get("when")
        if isinstance(when, str) and when.strip() and not UTC_TIMESTAMP_RE.match(when):
            findings.append(
                Finding("timestamp_format", f"{required_id}: when must use UTC format YYYY-MM-DDTHH:MM:SSZ")
            )

        evidence_ref = check.get("evidenceRef")
        if isinstance(evidence_ref, str) and evidence_ref.strip():
            parts = re.split(r"[\\/]+", evidence_ref)
            if (
                evidence_ref.startswith(("/", "\\"))
                or re.match(r"^[A-Za-z]:", evidence_ref)
                or ".." in parts
            ):
                findings.append(
                    Finding(
                        "evidence_ref_bounds",
                        f"{required_id}: evidenceRef must be a relative path under protectedEvidencePath",
                    )
                )

    return findings


def summarize(data: dict[str, Any]) -> list[str]:
    checks = {check["id"]: check for check in data.get("checks", []) if isinstance(check, dict) and "id" in check}
    lines = ["Faz24 WG-B+ I3 evidence: PASS"]
    for check_id in REQUIRED_CHECK_IDS:
        check = checks[check_id]
        lines.append(
            f"- {check_id}: who={check['who']} when={check['when']} what={check['what']}"
        )
    return lines


def validate(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    data, findings = load_json(path)
    if data is None:
        return None, findings

    findings.extend(validate_required_metadata(data))
    findings.extend(validate_checks(data))
    findings.extend(validate_no_leaks(data))
    return data, findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate metadata-only Faz 24 WG-B+ I3 management audit evidence."
    )
    parser.add_argument("evidence", type=Path, help="Path to I3 evidence JSON")
    args = parser.parse_args()

    data, findings = validate(args.evidence)
    if findings:
        print("Faz24 WG-B+ I3 evidence: FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.code}: {finding.message}", file=sys.stderr)
        return 1

    assert data is not None
    print("\n".join(summarize(data)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
