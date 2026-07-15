#!/usr/bin/env python3
"""Validate Faz 24 WG-B+ I3 management audit evidence.

The I3 gate is intentionally metadata-only: it must prove who/when/what for
management access and drift monitors without carrying command contents,
secrets, raw audio, or transcript text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "faz24.wg-bplus.i3.audit.v2"
CONTROL_CONTRACT_VERSION = "faz24.windows-audit-control.v2"
BUNDLE_MAX_AGE_SECONDS = 900
MAX_FUTURE_SKEW_SECONDS = 300
CANONICAL_DENETIM_TARGET = "svc-denetim-agent@10.99.0.2"
CANONICAL_DENETIM_HOST = "10.99.0.2"
CANONICAL_REMOTE_SNAPSHOT_PATH = (
    r"C:\ProgramData\Acik\Faz24\I3\audit-controls\snapshot\audit-snapshot.json"
)


def sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


CANONICAL_DENETIM_TARGET_HASH = sha256_short(CANONICAL_DENETIM_TARGET)
CANONICAL_DENETIM_HOST_HASH = sha256_short(CANONICAL_DENETIM_HOST)
CANONICAL_REMOTE_SNAPSHOT_PATH_HASH = sha256_short(CANONICAL_REMOTE_SNAPSHOT_PATH)

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
ALLOWED_SOURCE_KINDS = {
    "windows-event-log",
    "windows-system-snapshot",
    "windows-ssh-metadata",
    "linux-management-metadata",
}

TOP_LEVEL_FIELDS = {
    "schemaVersion",
    "collectedAt",
    "protectedEvidencePath",
    "retentionDays",
    "acl",
    "redaction",
    "collector",
    "checks",
}
ACL_FIELDS = {"mode", "readers", "writers"}
REDACTION_FIELDS = set(REDACTION_FLAGS)
CHECK_FIELDS = {"id", "status", "who", "when", "what", "evidenceRef", "control"}
CONTROL_FIELDS = {
    "contractVersion",
    "expected",
    "observed",
    "verdict",
    "source",
    "collectedAt",
    "maxAgeSeconds",
    "ageSeconds",
    "fresh",
    "errorClass",
}
SOURCE_FIELDS = {"kind", "locator"}
COLLECTOR_FIELDS = {
    "runner",
    "denetimTargetHash",
    "lookbackHours",
    "wgInterfaceSelection",
    "remoteSnapshotPathHash",
    "remoteSnapshotSchemaVersion",
    "denetimSshPreflight",
    "stagingWireGuardProbe",
    "remoteCollectorReached",
    "stagingJournalQueryable",
    "stagingJournalMatchCount",
    "stagingAuditRecordWritten",
    "stagingJournalSinceAttemptStart",
    "stagingCorrelationWindowSeconds",
    "stagingWireGuardQueryable",
    "stagingWireGuardPeerCount",
    "stagingSshSocketQueryable",
    "stagingSshSocketCount",
    "localEvidenceWriteContract",
}
SSH_PREFLIGHT_FIELDS = {
    "targetHostHash",
    "targetPort",
    "targetHostIsIpLiteral",
    "routeQueryable",
    "routeExitCode",
    "routeDeviceHash",
    "routeUsesSelectedWireGuardInterface",
    "tcp22Reachable",
    "tcp22ErrorClass",
    "tcp22Errno",
    "sshExitCode",
    "sshFailureClass",
    "sshStdoutPresent",
    "sshStderrPresent",
    "sshErrorFingerprint",
    "sshIdentityConfigured",
    "sshIdentityPathHash",
    "sshIdentityPublicKeyPresent",
    "sshIdentityPublicKeyFingerprint",
    "sshKnownHostsConfigured",
    "sshKnownHostsPathHash",
    "sshKnownHostsContentFingerprint",
    "sshKnownHostsSafePermissions",
}
WG_PROBE_FIELDS = {
    "requestedMode",
    "requestedInterfaceHash",
    "interfacesQueryable",
    "interfacesExitCode",
    "detectedCount",
    "selectedInterfaceHash",
    "probeCount",
    "selectedLatestExitCode",
    "selectedTransferExitCode",
    "selectedEndpointsExitCode",
    "wgToolFound",
    "wgToolKind",
    "wgToolProbeExitCode",
}
LOCAL_WRITE_FIELDS = {"atomic", "fileMode", "directoryMode", "symlinkRejected"}

EXPECTED_FIELDS = {
    "openssh-event-log": {"queryOk", "minimumEventCount"},
    "powershell-transcription": {
        "queryOk",
        "policyEnabled",
        "invocationHeaderEnabled",
        "protectedOutputAcl",
        "protectedSnapshotDirectoryAcl",
        "protectedSnapshotFileAcl",
        "retentionEnforced",
        "maximumRetentionDays",
        "maximumTranscriptBytes",
    },
    "powershell-script-block": {"queryOk", "policyEnabled", "minimumEventCount"},
    "failed-login": {"securityLogQueryable", "auditFailureEnabled"},
    "wireguard-health": {
        "queryOk",
        "minimumRunningServiceCount",
        "minimumInterfaceCount",
        "minimumPeerCount",
        "maximumHandshakeAgeSeconds",
    },
    "eset-firewall-drift": {
        "queryOk",
        "expectedRuleCount",
        "constrainedBroadReviewApproved",
        "minimumEsetCoreRunningCount",
    },
    "time-sync": {
        "queryOk",
        "serviceState",
        "statusCommandExitCode",
        "sourcePresent",
        "sourceSynchronized",
        "syncTypeConfigured",
        "maximumSuccessEventAgeSeconds",
    },
    "staging-connection-log": {
        "remoteCollectorReached",
        "wireGuardQueryable",
        "minimumPeerCount",
        "journalQueryable",
        "minimumJournalMatchCount",
        "auditRecordWritten",
        "journalSinceAttemptStart",
        "maximumCorrelationWindowSeconds",
        "sshSocketQueryable",
        "routeUsesSelectedWireGuardInterface",
    },
}

OBSERVED_FIELDS = {
    "openssh-event-log": {"queryOk", "eventCount"},
    "powershell-transcription": {
        "queryOk",
        "policyEnabled",
        "invocationHeaderEnabled",
        "protectedOutputAcl",
        "protectedSnapshotDirectoryAcl",
        "protectedSnapshotFileAcl",
        "retentionEnforced",
        "transcriptBytes",
        "oldestTranscriptAgeSeconds",
        "retentionDeleteCount",
        "capacityDeleteCount",
    },
    "powershell-script-block": {"queryOk", "policyEnabled", "eventCount"},
    "failed-login": {"securityLogQueryable", "auditFailureEnabled", "eventCount"},
    "wireguard-health": {
        "queryOk",
        "dumpExitCode",
        "runningServiceCount",
        "interfaceCount",
        "peerCount",
        "latestHandshakeAgeSeconds",
    },
    "eset-firewall-drift": {
        "queryOk",
        "expectedRuleCount",
        "expectedRuleMatchCount",
        "broadConflictCount",
        "constrainedBroadReviewCount",
        "approvedConstrainedBroadReviewCount",
        "constrainedBroadReviewApproved",
        "esetCoreRunningCount",
    },
    "time-sync": {
        "queryOk",
        "serviceState",
        "statusCommandExitCode",
        "sourcePresent",
        "sourceSynchronized",
        "syncTypeConfigured",
        "latestSuccessEventAgeSeconds",
    },
    "staging-connection-log": {
        "remoteCollectorReached",
        "wireGuardQueryable",
        "peerCount",
        "journalQueryable",
        "journalMatchCount",
        "auditRecordWritten",
        "journalSinceAttemptStart",
        "correlationWindowSeconds",
        "sshSocketQueryable",
        "sshSocketCount",
        "routeUsesSelectedWireGuardInterface",
    },
}

CANONICAL_EXPECTED: dict[str, dict[str, Any]] = {
    "openssh-event-log": {"queryOk": True, "minimumEventCount": 1},
    "powershell-transcription": {
        "queryOk": True,
        "policyEnabled": True,
        "invocationHeaderEnabled": True,
        "protectedOutputAcl": True,
        "protectedSnapshotDirectoryAcl": True,
        "protectedSnapshotFileAcl": True,
        "retentionEnforced": True,
        "maximumRetentionDays": 14,
        "maximumTranscriptBytes": 1_073_741_824,
    },
    "powershell-script-block": {
        "queryOk": True,
        "policyEnabled": True,
        "minimumEventCount": 1,
    },
    "failed-login": {
        "securityLogQueryable": True,
        "auditFailureEnabled": True,
    },
    "wireguard-health": {
        "queryOk": True,
        "minimumRunningServiceCount": 1,
        "minimumInterfaceCount": 1,
        "minimumPeerCount": 1,
        "maximumHandshakeAgeSeconds": 300,
    },
    "eset-firewall-drift": {
        "queryOk": True,
        "expectedRuleCount": 3,
        "constrainedBroadReviewApproved": True,
        "minimumEsetCoreRunningCount": 2,
    },
    "time-sync": {
        "queryOk": True,
        "serviceState": "Running",
        "statusCommandExitCode": 0,
        "sourcePresent": True,
        "sourceSynchronized": True,
        "syncTypeConfigured": True,
        "maximumSuccessEventAgeSeconds": 86_400,
    },
    "staging-connection-log": {
        "remoteCollectorReached": True,
        "wireGuardQueryable": True,
        "minimumPeerCount": 1,
        "journalQueryable": True,
        "minimumJournalMatchCount": 1,
        "auditRecordWritten": True,
        "journalSinceAttemptStart": True,
        "maximumCorrelationWindowSeconds": 180,
        "sshSocketQueryable": True,
        "routeUsesSelectedWireGuardInterface": True,
    },
}

CANONICAL_WHO = {
    "openssh-event-log": re.compile(
        rf"^windows-transport-target:{CANONICAL_DENETIM_TARGET_HASH}$"
    ),
    "powershell-transcription": re.compile(
        r"^windows-system:audit-snapshot/powershell-policy$"
    ),
    "powershell-script-block": re.compile(
        r"^windows-system:audit-snapshot/powershell-events$"
    ),
    "failed-login": re.compile(r"^windows-system:audit-snapshot/security-audit$"),
    "wireguard-health": re.compile(r"^windows-system:audit-snapshot/wireguard$"),
    "eset-firewall-drift": re.compile(r"^windows-system:audit-snapshot/firewall-eset$"),
    "time-sync": re.compile(r"^windows-system:audit-snapshot/time-service$"),
    "staging-connection-log": re.compile(
        r"^linux-management-plane:ssh-wireguard-correlation$"
    ),
}

CANONICAL_SOURCE = {
    "openssh-event-log": {
        "kind": "windows-event-log",
        "locator": "OpenSSH/Operational",
    },
    "powershell-transcription": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "powershell-script-block": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "failed-login": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "wireguard-health": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "eset-firewall-drift": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "time-sync": {
        "kind": "windows-system-snapshot",
        "locator": "faz24-i3-audit-snapshot",
    },
    "staging-connection-log": {
        "kind": "linux-management-metadata",
        "locator": "staging-management-plane",
    },
}

RAW_IDENTITY_PATTERNS = [
    re.compile(r"\bsvc-denetim-agent\b", re.IGNORECASE),
    re.compile(r"\bdenetim-pc\b", re.IGNORECASE),
    re.compile(r"(?<![0-9a-f])(?:10|127)\.(?:\d{1,3}\.){2}\d{1,3}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])192\.168\.(?:\d{1,3}\.)\d{1,3}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3}(?![0-9a-f])"),
    re.compile(r"\\\\[A-Za-z0-9._-]+\\"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._-]+\\[A-Za-z0-9._-]+\b"),
    re.compile(r"(?<![0-9a-f])(?:\d{1,3}\.){3}\d{1,3}(?![0-9a-f])"),
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
            yield from iter_values(child, child_path)


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    duplicate_keys: list[str] = []

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                duplicate_keys.append(key)
            value[key] = child
        return value

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        return None, [Finding("json_parse", f"{path}: invalid JSON: {exc}")]
    except OSError as exc:
        return None, [Finding("json_read", f"{path}: cannot read file: {exc}")]

    if not isinstance(data, dict):
        return None, [Finding("json_shape", "top-level evidence must be a JSON object")]
    if duplicate_keys:
        names = ", ".join(sorted(set(duplicate_keys)))
        return None, [Finding("duplicate_json_key", f"duplicate JSON key(s): {names}")]
    return data, []


def unknown_fields(value: dict[str, Any], allowed: set[str], path: str) -> list[Finding]:
    return [
        Finding("unknown_field", f"{path}.{key}: field is not allowed by the v2 contract")
        for key in sorted(set(value) - allowed)
    ]


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
            for pattern in RAW_IDENTITY_PATTERNS:
                if pattern.search(value):
                    findings.append(
                        Finding(
                            "raw_identity_value",
                            f"{path}: raw principal, host, private address, or UNC value is not allowed",
                        )
                    )
                    break
    return findings


def validate_contract_shape(data: dict[str, Any]) -> list[Finding]:
    findings = unknown_fields(data, TOP_LEVEL_FIELDS, "$")

    acl = data.get("acl")
    if isinstance(acl, dict):
        findings.extend(unknown_fields(acl, ACL_FIELDS, "$.acl"))

    redaction = data.get("redaction")
    if isinstance(redaction, dict):
        findings.extend(unknown_fields(redaction, REDACTION_FIELDS, "$.redaction"))

    collector = data.get("collector")
    if not isinstance(collector, dict):
        findings.append(Finding("collector", "collector must be an object"))
        return findings
    findings.extend(unknown_fields(collector, COLLECTOR_FIELDS, "$.collector"))

    preflight = collector.get("denetimSshPreflight")
    if not isinstance(preflight, dict):
        findings.append(Finding("collector_preflight", "collector.denetimSshPreflight must be an object"))
    else:
        findings.extend(
            unknown_fields(preflight, SSH_PREFLIGHT_FIELDS, "$.collector.denetimSshPreflight")
        )

    wg_probe = collector.get("stagingWireGuardProbe")
    if not isinstance(wg_probe, dict):
        findings.append(Finding("collector_wg_probe", "collector.stagingWireGuardProbe must be an object"))
    else:
        findings.extend(
            unknown_fields(wg_probe, WG_PROBE_FIELDS, "$.collector.stagingWireGuardProbe")
        )

    local_write = collector.get("localEvidenceWriteContract")
    if not isinstance(local_write, dict):
        findings.append(
            Finding("collector_local_write", "collector.localEvidenceWriteContract must be an object")
        )
    else:
        findings.extend(
            unknown_fields(local_write, LOCAL_WRITE_FIELDS, "$.collector.localEvidenceWriteContract")
        )
        expected_write = {
            "atomic": True,
            "fileMode": "0600",
            "directoryMode": "0700",
            "symlinkRejected": True,
        }
        if local_write != expected_write:
            findings.append(
                Finding(
                    "collector_local_write",
                    "local evidence write contract must require atomic 0600 output in a 0700 directory with symlink rejection",
                )
            )

    return findings


def validate_collector_semantics(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    collector = data.get("collector")
    if not isinstance(collector, dict):
        return findings

    if collector.get("runner") != "self-hosted-management-runner":
        findings.append(Finding("collector_runner", "collector runner must be canonical"))
    if collector.get("denetimTargetHash") != CANONICAL_DENETIM_TARGET_HASH:
        findings.append(
            Finding(
                "collector_target",
                "collector.denetimTargetHash must bind to the canonical Denetim target",
            )
        )
    if collector.get("remoteSnapshotSchemaVersion") != "faz24.windows-audit-snapshot.v2":
        findings.append(
            Finding("collector_snapshot", "remote snapshot schema must be canonical")
        )
    if collector.get("remoteSnapshotPathHash") != CANONICAL_REMOTE_SNAPSHOT_PATH_HASH:
        findings.append(
            Finding(
                "collector_snapshot",
                "collector.remoteSnapshotPathHash must bind to the canonical snapshot path",
            )
        )

    preflight = collector.get("denetimSshPreflight")
    wg_probe = collector.get("stagingWireGuardProbe")
    if not isinstance(preflight, dict) or not isinstance(wg_probe, dict):
        return findings

    if preflight.get("targetHostHash") != CANONICAL_DENETIM_HOST_HASH:
        findings.append(
            Finding(
                "collector_target",
                "SSH preflight targetHostHash must bind to the canonical Denetim host",
            )
        )
    if preflight.get("targetPort") != 22 or preflight.get("targetHostIsIpLiteral") is not True:
        findings.append(
            Finding("collector_target", "SSH preflight must target canonical TCP/22 IP transport")
        )
    if preflight.get("routeQueryable") is not True or preflight.get("routeExitCode") != 0:
        findings.append(Finding("collector_route", "canonical Denetim route must be queryable"))
    route_hash = preflight.get("routeDeviceHash")
    selected_hash = wg_probe.get("selectedInterfaceHash")
    if (
        not isinstance(route_hash, str)
        or re.fullmatch(r"[0-9a-f]{16}", route_hash) is None
        or route_hash != selected_hash
        or preflight.get("routeUsesSelectedWireGuardInterface") is not True
    ):
        findings.append(
            Finding(
                "collector_route",
                "Denetim route device must equal the selected WireGuard interface",
            )
        )
    if (
        preflight.get("tcp22Reachable") is not True
        or preflight.get("sshExitCode") != 0
        or preflight.get("sshFailureClass") != "none"
    ):
        findings.append(
            Finding("collector_ssh", "canonical Denetim SSH preflight must succeed")
        )
    if (
        preflight.get("sshIdentityConfigured") is not True
        or preflight.get("sshIdentityPublicKeyPresent") is not True
    ):
        findings.append(
            Finding("collector_ssh", "dedicated SSH identity metadata must be proven")
        )
    if (
        preflight.get("sshKnownHostsConfigured") is not True
        or preflight.get("sshKnownHostsSafePermissions") is not True
        or re.fullmatch(
            r"[0-9a-f]{16}", str(preflight.get("sshKnownHostsContentFingerprint", ""))
        )
        is None
    ):
        findings.append(
            Finding("collector_ssh", "pinned SSH known_hosts metadata must be proven")
        )

    return findings


def validate_file_security(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        if path.is_symlink():
            return [Finding("evidence_symlink", "evidence file must not be a symbolic link")]
        metadata = path.stat()
    except OSError as exc:
        return [Finding("evidence_stat", f"cannot inspect evidence file metadata: {exc}")]

    if not stat.S_ISREG(metadata.st_mode):
        findings.append(Finding("evidence_file_type", "evidence path must be a regular file"))
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        findings.append(
            Finding("evidence_file_mode", "evidence file must not grant group or other permissions")
        )
    return findings


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def validate_required_metadata(
    data: dict[str, Any], validation_time: datetime
) -> list[Finding]:
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
    elif parse_utc_timestamp(collected_at) is None:
        findings.append(
            Finding("timestamp_format", "collectedAt must use UTC format YYYY-MM-DDTHH:MM:SSZ")
        )
    else:
        bundle_time = parse_utc_timestamp(collected_at)
        assert bundle_time is not None
        actual_age = int((validation_time - bundle_time).total_seconds())
        if not -MAX_FUTURE_SKEW_SECONDS <= actual_age <= BUNDLE_MAX_AGE_SECONDS:
            findings.append(
                Finding(
                    "bundle_freshness",
                    "collectedAt must be within the canonical 900-second validation window",
                )
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
        if readers != ["platform-ops-audit"]:
            findings.append(Finding("acl_readers", "acl.readers must match the exact audit reader set"))
        if writers != [
            "github-actions:self-hosted-staging-sw",
            "windows-system:audit-snapshot",
        ]:
            findings.append(Finding("acl_writers", "acl.writers must match the exact writer set"))

    redaction = data.get("redaction")
    if not isinstance(redaction, dict):
        findings.append(Finding("redaction", "redaction must be an object"))
    else:
        for flag in REDACTION_FLAGS:
            if redaction.get(flag) is not False:
                findings.append(Finding("redaction_flag", f"redaction.{flag} must be false"))

    return findings


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def bool_is(data: dict[str, Any], key: str, expected: bool = True) -> bool:
    return data.get(key) is expected


def nonnegative_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if is_int(value) and value >= 0:
        return value
    return None


def semantic_failure(findings: list[Finding], check_id: str, message: str) -> None:
    findings.append(Finding("control_semantics", f"{check_id}: {message}"))


def validate_control_semantics(
    check_id: str,
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []

    if expected != CANONICAL_EXPECTED[check_id]:
        semantic_failure(
            findings,
            check_id,
            "expected policy must exactly match the repository canonical policy",
        )

    if check_id == "openssh-event-log":
        minimum = expected.get("minimumEventCount")
        count = nonnegative_int(observed, "eventCount")
        if not bool_is(expected, "queryOk") or not bool_is(observed, "queryOk"):
            semantic_failure(findings, check_id, "OpenSSH event log must be queryable")
        if not is_int(minimum) or minimum < 1 or count is None or count < minimum:
            semantic_failure(findings, check_id, "eventCount must meet minimumEventCount")

    elif check_id == "powershell-transcription":
        for field in [
            "queryOk",
            "policyEnabled",
            "invocationHeaderEnabled",
            "protectedOutputAcl",
            "protectedSnapshotDirectoryAcl",
            "protectedSnapshotFileAcl",
            "retentionEnforced",
        ]:
            if not bool_is(expected, field) or not bool_is(observed, field):
                semantic_failure(findings, check_id, f"{field} must be proven true")
        maximum_days = expected.get("maximumRetentionDays")
        maximum_bytes = expected.get("maximumTranscriptBytes")
        transcript_bytes = nonnegative_int(observed, "transcriptBytes")
        oldest_age = nonnegative_int(observed, "oldestTranscriptAgeSeconds")
        for counter in ["retentionDeleteCount", "capacityDeleteCount"]:
            if nonnegative_int(observed, counter) is None:
                semantic_failure(findings, check_id, f"{counter} must be nonnegative")
        if (
            not is_int(maximum_days)
            or maximum_days < 1
            or oldest_age is None
            or oldest_age > maximum_days * 86_400
        ):
            semantic_failure(findings, check_id, "transcript retention age must be bounded")
        if (
            not is_int(maximum_bytes)
            or maximum_bytes < 1_048_576
            or transcript_bytes is None
            or transcript_bytes > maximum_bytes
        ):
            semantic_failure(findings, check_id, "transcript storage bytes must be bounded")

    elif check_id == "powershell-script-block":
        minimum = expected.get("minimumEventCount")
        count = nonnegative_int(observed, "eventCount")
        for field in ["queryOk", "policyEnabled"]:
            if not bool_is(expected, field) or not bool_is(observed, field):
                semantic_failure(findings, check_id, f"{field} must be proven true")
        if not is_int(minimum) or minimum < 1 or count is None or count < minimum:
            semantic_failure(findings, check_id, "eventCount must meet minimumEventCount")

    elif check_id == "failed-login":
        for field in ["securityLogQueryable", "auditFailureEnabled"]:
            if not bool_is(expected, field) or not bool_is(observed, field):
                semantic_failure(findings, check_id, f"{field} must be proven true")
        if nonnegative_int(observed, "eventCount") is None:
            semantic_failure(findings, check_id, "eventCount must be a non-negative integer; zero is valid")

    elif check_id == "wireguard-health":
        if not bool_is(expected, "queryOk") or not bool_is(observed, "queryOk"):
            semantic_failure(findings, check_id, "WireGuard dump must be queryable")
        for observed_key, expected_key in [
            ("runningServiceCount", "minimumRunningServiceCount"),
            ("interfaceCount", "minimumInterfaceCount"),
            ("peerCount", "minimumPeerCount"),
        ]:
            minimum = expected.get(expected_key)
            actual = nonnegative_int(observed, observed_key)
            if not is_int(minimum) or minimum < 1 or actual is None or actual < minimum:
                semantic_failure(findings, check_id, f"{observed_key} must meet {expected_key}")
        maximum_age = expected.get("maximumHandshakeAgeSeconds")
        actual_age = nonnegative_int(observed, "latestHandshakeAgeSeconds")
        if not is_int(maximum_age) or maximum_age < 1 or actual_age is None or actual_age > maximum_age:
            semantic_failure(findings, check_id, "latest handshake must be present and within the declared maximum age")

    elif check_id == "eset-firewall-drift":
        if not bool_is(expected, "queryOk") or not bool_is(observed, "queryOk"):
            semantic_failure(findings, check_id, "firewall policy must be queryable")
        expected_count = expected.get("expectedRuleCount")
        declared_count = nonnegative_int(observed, "expectedRuleCount")
        matched_count = nonnegative_int(observed, "expectedRuleMatchCount")
        if (
            not is_int(expected_count)
            or expected_count < 1
            or declared_count != expected_count
            or matched_count != expected_count
        ):
            semantic_failure(findings, check_id, "all exact expected rules must match")
        if nonnegative_int(observed, "broadConflictCount") != 0:
            semantic_failure(
                findings,
                check_id,
                "unconstrained broad inbound hard-block count must be zero",
            )
        constrained_count = nonnegative_int(observed, "constrainedBroadReviewCount")
        approved_constrained_count = nonnegative_int(
            observed,
            "approvedConstrainedBroadReviewCount",
        )
        if constrained_count is None:
            semantic_failure(
                findings,
                check_id,
                "constrained broad review count must be a non-negative integer",
            )
        if (
            expected.get("constrainedBroadReviewApproved") is not True
            or observed.get("constrainedBroadReviewApproved") is not True
            or approved_constrained_count is None
            or approved_constrained_count != constrained_count
        ):
            semantic_failure(
                findings,
                check_id,
                "constrained broad review approval must match the observed count",
            )
        minimum_eset = expected.get("minimumEsetCoreRunningCount")
        running_eset = nonnegative_int(observed, "esetCoreRunningCount")
        if not is_int(minimum_eset) or minimum_eset < 1 or running_eset is None or running_eset < minimum_eset:
            semantic_failure(findings, check_id, "ESET core running count must meet the declared minimum")

    elif check_id == "time-sync":
        if not bool_is(expected, "queryOk") or not bool_is(observed, "queryOk"):
            semantic_failure(findings, check_id, "time service must be queryable")
        if expected.get("serviceState") != "Running" or observed.get("serviceState") != "Running":
            semantic_failure(findings, check_id, "w32time serviceState must be Running")
        if expected.get("statusCommandExitCode") != 0 or observed.get("statusCommandExitCode") != 0:
            semantic_failure(findings, check_id, "w32tm status command must exit zero")
        if not bool_is(expected, "sourcePresent") or not bool_is(observed, "sourcePresent"):
            semantic_failure(findings, check_id, "time source presence must be proven")
        if not bool_is(expected, "sourceSynchronized") or not bool_is(
            observed, "sourceSynchronized"
        ):
            semantic_failure(
                findings,
                check_id,
                "time source must be synchronized and must not be a local/free-running clock",
            )
        if not bool_is(expected, "syncTypeConfigured") or not bool_is(
            observed, "syncTypeConfigured"
        ):
            semantic_failure(
                findings,
                check_id,
                "Windows Time sync type must be configured for NTP, NT5DS, or AllSync",
            )
        maximum_age = expected.get("maximumSuccessEventAgeSeconds")
        actual_age = nonnegative_int(observed, "latestSuccessEventAgeSeconds")
        if not is_int(maximum_age) or maximum_age < 1 or actual_age is None or actual_age > maximum_age:
            semantic_failure(findings, check_id, "latest success event must be within the declared maximum age")

    elif check_id == "staging-connection-log":
        for field in [
            "remoteCollectorReached",
            "wireGuardQueryable",
            "journalQueryable",
            "auditRecordWritten",
            "journalSinceAttemptStart",
            "sshSocketQueryable",
            "routeUsesSelectedWireGuardInterface",
        ]:
            if not bool_is(expected, field) or not bool_is(observed, field):
                semantic_failure(findings, check_id, f"{field} must be proven true")
        minimum = expected.get("minimumPeerCount")
        count = nonnegative_int(observed, "peerCount")
        if not is_int(minimum) or minimum < 1 or count is None or count < minimum:
            semantic_failure(findings, check_id, "peerCount must meet minimumPeerCount")
        minimum_matches = expected.get("minimumJournalMatchCount")
        match_count = nonnegative_int(observed, "journalMatchCount")
        if (
            not is_int(minimum_matches)
            or minimum_matches < 1
            or match_count is None
            or match_count < minimum_matches
        ):
            semantic_failure(
                findings,
                check_id,
                "journalMatchCount must meet minimumJournalMatchCount",
            )
        maximum_window = expected.get("maximumCorrelationWindowSeconds")
        correlation_window = nonnegative_int(observed, "correlationWindowSeconds")
        if (
            not is_int(maximum_window)
            or maximum_window < 1
            or correlation_window is None
            or correlation_window > maximum_window
        ):
            semantic_failure(
                findings,
                check_id,
                "correlationWindowSeconds must be within the canonical current-attempt window",
            )
        if nonnegative_int(observed, "sshSocketCount") is None:
            semantic_failure(
                findings,
                check_id,
                "sshSocketCount must be a non-negative integer; zero is valid after SSH exits",
            )

    return findings


def validate_control(
    check_id: str,
    check: dict[str, Any],
    *,
    bundle_time: datetime | None,
    validation_time: datetime,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(unknown_fields(check, CHECK_FIELDS, f"$.checks[{check_id}]"))
    control = check.get("control")
    if not isinstance(control, dict):
        return [Finding("control_contract", f"{check_id}: control must be an object")]

    findings.extend(
        unknown_fields(control, CONTROL_FIELDS, f"$.checks[{check_id}].control")
    )

    if control.get("contractVersion") != CONTROL_CONTRACT_VERSION:
        findings.append(
            Finding(
                "control_contract_version",
                f"{check_id}: control.contractVersion must be '{CONTROL_CONTRACT_VERSION}'",
            )
        )

    expected = control.get("expected")
    observed = control.get("observed")
    if not isinstance(expected, dict):
        findings.append(Finding("control_expected", f"{check_id}: control.expected must be an object"))
        expected = {}
    if not isinstance(observed, dict):
        findings.append(Finding("control_observed", f"{check_id}: control.observed must be an object"))
        observed = {}
    findings.extend(
        unknown_fields(
            expected,
            EXPECTED_FIELDS[check_id],
            f"$.checks[{check_id}].control.expected",
        )
    )
    findings.extend(
        unknown_fields(
            observed,
            OBSERVED_FIELDS[check_id],
            f"$.checks[{check_id}].control.observed",
        )
    )

    if control.get("verdict") != "pass":
        findings.append(Finding("control_verdict", f"{check_id}: control.verdict must be 'pass'"))
    if check.get("status") != control.get("verdict"):
        findings.append(Finding("control_status_mismatch", f"{check_id}: status must equal control.verdict"))

    source = control.get("source")
    if not isinstance(source, dict):
        findings.append(Finding("control_source", f"{check_id}: control.source must be an object"))
    else:
        findings.extend(
            unknown_fields(source, SOURCE_FIELDS, f"$.checks[{check_id}].control.source")
        )
        kind = source.get("kind")
        locator = source.get("locator")
        if kind not in ALLOWED_SOURCE_KINDS:
            findings.append(Finding("control_source_kind", f"{check_id}: unsupported source.kind"))
        if not isinstance(locator, str) or not locator.strip() or "\n" in locator or len(locator) > 120:
            findings.append(Finding("control_source_locator", f"{check_id}: source.locator must be bounded"))
        if source != CANONICAL_SOURCE[check_id]:
            findings.append(
                Finding(
                    "control_source_policy",
                    f"{check_id}: source must exactly match the canonical source policy",
                )
            )

    collected_at = control.get("collectedAt")
    control_time = parse_utc_timestamp(collected_at)
    if control_time is None:
        findings.append(Finding("control_timestamp", f"{check_id}: control.collectedAt must be UTC"))
    elif check.get("when") != collected_at:
        findings.append(Finding("control_timestamp_mismatch", f"{check_id}: when must equal control.collectedAt"))

    max_age = control.get("maxAgeSeconds")
    age = control.get("ageSeconds")
    if max_age != BUNDLE_MAX_AGE_SECONDS:
        findings.append(
            Finding(
                "control_max_age",
                f"{check_id}: maxAgeSeconds must equal canonical value {BUNDLE_MAX_AGE_SECONDS}",
            )
        )
    if not is_int(age):
        findings.append(Finding("control_age", f"{check_id}: ageSeconds must be an integer"))
    elif control_time is not None and bundle_time is not None:
        recomputed_bundle_age = int((bundle_time - control_time).total_seconds())
        recomputed_current_age = int((validation_time - control_time).total_seconds())
        if age != recomputed_bundle_age:
            findings.append(
                Finding(
                    "control_age_mismatch",
                    f"{check_id}: ageSeconds must equal the timestamp-derived age",
                )
            )
        if not -MAX_FUTURE_SKEW_SECONDS <= recomputed_bundle_age <= BUNDLE_MAX_AGE_SECONDS:
            findings.append(
                Finding(
                    "control_age",
                    f"{check_id}: control timestamp must be within bundle freshness bounds",
                )
            )
        if not -MAX_FUTURE_SKEW_SECONDS <= recomputed_current_age <= BUNDLE_MAX_AGE_SECONDS:
            findings.append(
                Finding(
                    "control_freshness",
                    f"{check_id}: control timestamp is stale at validation time",
                )
            )
    if control.get("fresh") is not True:
        findings.append(Finding("control_freshness", f"{check_id}: fresh must be true"))
    if control.get("errorClass") != "none":
        findings.append(Finding("control_error", f"{check_id}: errorClass must be 'none' for pass"))

    findings.extend(validate_control_semantics(check_id, expected, observed))
    return findings


def validate_checks(data: dict[str, Any], validation_time: datetime) -> list[Finding]:
    findings: list[Finding] = []
    checks = data.get("checks")
    if not isinstance(checks, list):
        return [Finding("checks", "checks must be a list")]

    by_id: dict[str, dict[str, Any]] = {}
    bundle_time = parse_utc_timestamp(data.get("collectedAt"))
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
        if check_id not in REQUIRED_CHECK_IDS:
            findings.append(Finding("unknown_check", f"unsupported check id '{check_id}'"))
        by_id[check_id] = check

    if len(checks) != len(REQUIRED_CHECK_IDS):
        findings.append(
            Finding("check_count", f"checks must contain exactly {len(REQUIRED_CHECK_IDS)} controls")
        )

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

        who = check.get("who")
        if isinstance(who, str) and not CANONICAL_WHO[required_id].fullmatch(who):
            findings.append(
                Finding(
                    "check_who",
                    f"{required_id}: who must match the canonical redacted principal form",
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

        findings.extend(
            validate_control(
                required_id,
                check,
                bundle_time=bundle_time,
                validation_time=validation_time,
            )
        )

    return findings


def summarize(data: dict[str, Any]) -> list[str]:
    checks = {check["id"]: check for check in data.get("checks", []) if isinstance(check, dict) and "id" in check}
    lines = ["Faz24 WG-B+ I3 evidence: PASS"]
    for check_id in REQUIRED_CHECK_IDS:
        check = checks[check_id]
        control = check["control"]
        lines.append(
            f"- {check_id}: verdict={control['verdict']} "
            f"errorClass={control['errorClass']} fresh={str(control['fresh']).lower()}"
        )
    return lines


def validate(
    path: Path, *, validation_time: datetime | None = None
) -> tuple[dict[str, Any] | None, list[Finding]]:
    data, findings = load_json(path)
    if data is None:
        return None, findings

    effective_validation_time = validation_time or datetime.now(timezone.utc).replace(
        microsecond=0
    )
    if effective_validation_time.tzinfo is None:
        effective_validation_time = effective_validation_time.replace(tzinfo=timezone.utc)
    else:
        effective_validation_time = effective_validation_time.astimezone(timezone.utc)

    findings.extend(validate_file_security(path))
    findings.extend(validate_contract_shape(data))
    findings.extend(validate_collector_semantics(data))
    findings.extend(validate_required_metadata(data, effective_validation_time))
    findings.extend(validate_checks(data, effective_validation_time))
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
