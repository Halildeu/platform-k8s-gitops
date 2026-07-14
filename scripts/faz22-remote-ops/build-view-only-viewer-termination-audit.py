#!/usr/bin/env python3
"""Verify one termination case against the tenant and session WORM chains."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from typing import Any


AUDIT_CHAIN_PATH = Path(__file__).with_name("build-view-only-viewer-audit-summary.py")
AUDIT_CHAIN_SPEC = importlib.util.spec_from_file_location("viewer_audit_chain", AUDIT_CHAIN_PATH)
audit_chain = importlib.util.module_from_spec(AUDIT_CHAIN_SPEC)
assert AUDIT_CHAIN_SPEC and AUDIT_CHAIN_SPEC.loader
sys.modules[AUDIT_CHAIN_SPEC.name] = audit_chain
AUDIT_CHAIN_SPEC.loader.exec_module(audit_chain)


TERMINATION_CASES = {
    "localAbort",
    "killOrRevoke",
    "ttlExpiry",
    "heartbeatLoss",
    "indicatorLoss",
}
RECORD_KINDS = {
    "SESSION_START",
    "OPERATOR_COMMAND",
    "AGENT_OUTPUT",
    "POLICY_EVENT",
    "KILL",
    "SESSION_END",
}
GENESIS_HASH = "0" * 64
SESSION_CHAIN_DOMAIN = "SessionRecordingChain:v1"
KILL_ACK_EVENT = "SESSION_CLOSE:AGENT_KILL_APPLIED"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def length_prefixed(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">I", len(raw)) + raw


def recording_entry_hash(row: dict[str, Any]) -> str:
    fields = (
        SESSION_CHAIN_DOMAIN,
        str(row["seq"]),
        str(row["timestampMillis"]),
        row["kind"],
        row["contentHash"],
        row["previousHash"],
    )
    return hashlib.sha256(b"".join(length_prefixed(field) for field in fields)).hexdigest()


def load_recording_rows(raw: bytes, session_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode("utf-8", errors="strict").splitlines(), 1):
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {
            "chainId", "seq", "timestampMillis", "kind", "contentHash",
            "previousHash", "entryHash",
        }:
            raise ValueError(f"session recording row {line_number} field set mismatch")
        if row["chainId"] != session_id:
            raise ValueError("session recording row belongs to another session")
        rows.append(row)
    if not rows:
        raise ValueError("session recording chain is empty")
    return rows


def verify_recording_chain(rows: list[dict[str, Any]]) -> None:
    expected_previous = GENESIS_HASH
    for expected_seq, row in enumerate(rows):
        if row["seq"] != expected_seq or row["kind"] not in RECORD_KINDS:
            raise ValueError("session recording sequence or kind is invalid")
        if not isinstance(row["timestampMillis"], int) or row["timestampMillis"] < 0:
            raise ValueError("session recording timestamp is invalid")
        if not isinstance(row["contentHash"], str) or not row["contentHash"]:
            raise ValueError("session recording content hash is empty")
        if row["previousHash"] != expected_previous:
            raise ValueError("session recording chain linkage mismatch")
        if recording_entry_hash(row) != row["entryHash"]:
            raise ValueError("session recording entry hash mismatch")
        expected_previous = row["entryHash"]


def build(tenant_raw: bytes, recording_raw: bytes, case_name: str, session_id: str,
          binding: dict[str, str], source_revision: str, observed_at: str) -> dict[str, Any]:
    if case_name not in TERMINATION_CASES:
        raise ValueError("termination case is invalid")
    if set(binding) != audit_chain.BINDING_FIELDS or any(
        not audit_chain.SHA256.fullmatch(str(value)) for value in binding.values()
    ):
        raise ValueError("termination binding is invalid")
    if binding["sessionSha256"] != audit_chain.sha256_text(session_id):
        raise ValueError("termination session binding mismatch")
    if len(set(binding.values())) != 4:
        raise ValueError("termination binding hashes must be distinct")
    if not isinstance(source_revision, str) or len(source_revision) != 40 \
            or any(char not in "0123456789abcdef" for char in source_revision):
        raise ValueError("source revision is invalid")
    audit_chain.normalize_instant(observed_at)

    tenant_rows = audit_chain.load_rows(tenant_raw)
    audit_chain.verify_chain(tenant_rows)
    view_stops = [
        row for row in tenant_rows
        if row["event_type"] == audit_chain.EVENT_TYPE
        and row["action"] == "VIEW_STOP"
        and row["correlation_id"] == session_id
    ]
    if len(view_stops) != 1:
        raise ValueError("exactly one session-bound VIEW_STOP is required")
    stop = view_stops[0]
    metadata = stop.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("sessionId") != session_id \
            or metadata.get("capability") != "VIEW_ONLY" \
            or metadata.get("recording") is not False \
            or metadata.get("attended") is not True:
        raise ValueError("VIEW_STOP metadata envelope mismatch")
    raw_binding = {
        "sessionSha256": audit_chain.sha256_text(session_id),
        "tenantSha256": audit_chain.sha256_text(str(stop["tenant_id"])),
        "operatorSha256": audit_chain.sha256_text(str(stop["performed_by_subject"])),
        "deviceSha256": audit_chain.sha256_text(str(metadata.get("deviceId"))),
    }
    if raw_binding != binding:
        raise ValueError("VIEW_STOP does not match the protected case binding")
    frames_delivered = metadata.get("framesDelivered")
    frames_rendered = metadata.get("framesRenderAcknowledged")
    if not isinstance(frames_delivered, int) or frames_delivered < 1 \
            or not isinstance(frames_rendered, int) or frames_rendered < 0 \
            or frames_rendered > frames_delivered:
        raise ValueError("VIEW_STOP frame counters are invalid")

    recording_rows = load_recording_rows(recording_raw, session_id)
    verify_recording_chain(recording_rows)
    ack_hash = hashlib.sha256(KILL_ACK_EVENT.encode("utf-8")).hexdigest()
    ack_count = sum(
        row["kind"] == "POLICY_EVENT" and row["contentHash"] == ack_hash
        for row in recording_rows
    )
    if case_name == "killOrRevoke" and ack_count != 1:
        raise ValueError("killOrRevoke requires exactly one durable AGENT_KILL_APPLIED record")
    if case_name != "killOrRevoke" and ack_count != 0:
        raise ValueError("non-kill termination case contains an unexpected operator KILL ACK")

    combined = hashlib.sha256(tenant_raw + b"\0" + recording_raw).hexdigest()
    return {
        "schemaVersion": "faz22.6.viewOnlyViewerMatrixAuditRecord.v1",
        "caseName": case_name,
        "sourceRevision": source_revision,
        "observedAt": observed_at,
        "binding": binding,
        "eventType": "VIEW_STOP",
        "outcome": True,
        "chainVerified": True,
        "chainSha256": "sha256:" + combined,
        "chainCheckedCount": len(tenant_rows) + len(recording_rows),
        "framesDelivered": frames_delivered,
        "verificationSource": "tenant-audit-chain-builder",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-audit-chain", required=True, type=Path)
    parser.add_argument("--session-recording-chain", required=True, type=Path)
    parser.add_argument("--case", required=True, choices=sorted(TERMINATION_CASES))
    parser.add_argument("--session-id-env", default="MATRIX_SESSION_ID")
    parser.add_argument("--binding-json", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import os

    result = build(
        args.tenant_audit_chain.read_bytes(), args.session_recording_chain.read_bytes(),
        args.case, os.environ.get(args.session_id_env, ""),
        json.loads(args.binding_json.read_text(encoding="utf-8")),
        args.source_revision, args.observed_at,
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
