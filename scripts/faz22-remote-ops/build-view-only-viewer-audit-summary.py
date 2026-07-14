#!/usr/bin/env python3
"""Verify the live tenant audit chain and emit an identifier-free VIEW_ONLY summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DOMAIN_PREFIX = "endpoint-admin-audit:v1"
HASH_ALGORITHM = "SHA-256"
HASH_VERSION = 1
EVENT_TYPE = "REMOTE_SUPPORT_SCREEN_OBSERVATION"
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
HEX_SHA256 = re.compile(r"^[a-f0-9]{64}$")
EXPECTED_ROW_FIELDS = {
    "id", "tenant_id", "device_id", "command_id", "event_type", "action",
    "performed_by_subject", "correlation_id", "metadata", "before_state",
    "after_state", "occurred_at", "prev_event_hash", "event_hash",
    "event_hash_alg", "event_hash_version",
}
BINDING_FIELDS = {"sessionSha256", "tenantSha256", "operatorSha256", "deviceSha256"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_instant(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("audit occurred_at is not a string")
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z", value)
    if match is None:
        raise ValueError("audit occurred_at is not canonical UTC")
    fraction = (match.group(2) or "").ljust(6, "0")
    if not fraction or int(fraction) == 0:
        return match.group(1) + "Z"
    if fraction.endswith("000"):
        return f"{match.group(1)}.{fraction[:3]}Z"
    return f"{match.group(1)}.{fraction}Z"


def epoch_millis(value: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def instant_order(value: object):
    from datetime import datetime

    return datetime.fromisoformat(normalize_instant(value).replace("Z", "+00:00"))


def canonical_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": row["action"],
        "after_state": row["after_state"],
        "before_state": row["before_state"],
        "command_id": row["command_id"],
        "correlation_id": row["correlation_id"],
        "device_id": row["device_id"],
        "event_hash_alg": row["event_hash_alg"],
        "event_hash_version": row["event_hash_version"],
        "event_type": row["event_type"],
        "id": row["id"],
        "metadata": row["metadata"],
        "occurred_at": normalize_instant(row["occurred_at"]),
        "performed_by_subject": row["performed_by_subject"],
        "tenant_id": row["tenant_id"],
    }


def computed_event_hash(row: dict[str, Any]) -> str:
    previous = row["prev_event_hash"] or "GENESIS"
    payload = canonical_bytes(canonical_payload(row)).decode("utf-8")
    composed = f"{DOMAIN_PREFIX}\nprev={previous}\npayload={payload}"
    return hashlib.sha256(composed.encode("utf-8")).hexdigest()


def load_rows(raw: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode("utf-8", errors="strict").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or set(value) != EXPECTED_ROW_FIELDS:
            raise ValueError(f"audit row {line_number} field set mismatch")
        rows.append(value)
    if not rows:
        raise ValueError("tenant audit chain is empty")
    return rows


def verify_chain(rows: list[dict[str, Any]]) -> None:
    previous: str | None = None
    prior_order: tuple[object, str] | None = None
    for row in rows:
        if row["event_hash_alg"] != HASH_ALGORITHM or row["event_hash_version"] != HASH_VERSION:
            raise ValueError("audit row hash algorithm/version mismatch")
        if not HEX_SHA256.fullmatch(str(row["event_hash"])):
            raise ValueError("audit row event hash is invalid")
        if row["prev_event_hash"] is not None and not HEX_SHA256.fullmatch(str(row["prev_event_hash"])):
            raise ValueError("audit row previous hash is invalid")
        order = (instant_order(row["occurred_at"]), str(row["id"]))
        if prior_order is not None and order <= prior_order:
            raise ValueError("tenant audit rows are not in canonical chain order")
        if row["prev_event_hash"] != previous:
            raise ValueError("tenant audit chain linkage mismatch")
        if computed_event_hash(row) != row["event_hash"]:
            raise ValueError("tenant audit chain event hash mismatch")
        previous = row["event_hash"]
        prior_order = order


def recording_content_writes(raw: bytes, session_id: str) -> int:
    count = 0
    row_count = 0
    policy_event_count = 0
    previous_sequence = -1
    allowed_kinds = {
        "SESSION_START", "OPERATOR_COMMAND", "AGENT_OUTPUT",
        "POLICY_EVENT", "KILL", "SESSION_END",
    }
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if not line.strip():
            continue
        fields = line.split("\t", 3)
        if len(fields) != 4 or fields[0] != session_id:
            raise ValueError("recording row is not bound to the pilot session")
        if not fields[1].isdigit() or int(fields[1]) <= previous_sequence:
            raise ValueError("recording rows are not in strict sequence order")
        previous_sequence = int(fields[1])
        if fields[2] not in allowed_kinds:
            raise ValueError("recording row kind is unknown")
        row_count += 1
        if fields[2] == "POLICY_EVENT":
            policy_event_count += 1
        if fields[2] == "AGENT_OUTPUT":
            count += 1
    if row_count == 0 or policy_event_count == 0:
        raise ValueError("recording audit ledger is empty or lacks a policy event")
    return count


def build(chain_raw: bytes, recording_raw: bytes, session_id: str, stream_id: str,
          browser: dict[str, Any], frame_flow: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", session_id):
        raise ValueError("session id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", stream_id):
        raise ValueError("stream id is invalid")
    binding = browser.get("binding")
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS \
            or any(not SHA256.fullmatch(str(value)) for value in binding.values()):
        raise ValueError("browser binding is invalid")
    if frame_flow.get("binding") != binding:
        raise ValueError("frame-flow binding mismatch")
    first_frame_millis = frame_flow.get("firstObservedAtEpochMillis")
    last_frame_millis = frame_flow.get("lastObservedAtEpochMillis")
    if not isinstance(first_frame_millis, int) or not isinstance(last_frame_millis, int):
        raise ValueError("frame-flow timestamps are invalid")
    if first_frame_millis <= 0 or last_frame_millis < first_frame_millis:
        raise ValueError("frame-flow timestamp order is invalid")

    rows = load_rows(chain_raw)
    verify_chain(rows)
    matches = [
        row for row in rows
        if row["event_type"] == EVENT_TYPE and row["correlation_id"] == session_id
    ]
    starts = [row for row in matches if row["action"] == "VIEW_START"]
    stops = [row for row in matches if row["action"] == "VIEW_STOP"]
    if len(starts) != 1 or len(stops) != 1:
        raise ValueError("exactly one VIEW_START and VIEW_STOP are required")
    start, stop = starts[0], stops[0]

    base_meta = {
        "sessionId": session_id,
        "deviceId": start["metadata"].get("deviceId") if isinstance(start["metadata"], dict) else None,
        "streamId": stream_id,
        "recording": False,
        "attended": True,
        "capability": "VIEW_ONLY",
    }
    if start["metadata"] != base_meta:
        raise ValueError("VIEW_START metadata envelope mismatch")
    expected_stop_keys = set(base_meta) | {"framesDelivered", "framesRenderAcknowledged"}
    if not isinstance(stop["metadata"], dict) or set(stop["metadata"]) != expected_stop_keys:
        raise ValueError("VIEW_STOP metadata field set mismatch")
    if any(stop["metadata"].get(key) != value for key, value in base_meta.items()):
        raise ValueError("VIEW_STOP metadata binding mismatch")
    if start["tenant_id"] != stop["tenant_id"] or start["performed_by_subject"] != stop["performed_by_subject"]:
        raise ValueError("VIEW_START/VIEW_STOP actor binding mismatch")

    raw_binding = {
        "sessionSha256": sha256_text(session_id),
        "tenantSha256": sha256_text(str(start["tenant_id"])),
        "operatorSha256": sha256_text(str(start["performed_by_subject"])),
        "deviceSha256": sha256_text(str(base_meta["deviceId"])),
    }
    if raw_binding != binding:
        raise ValueError("audit rows do not match browser same-session binding")

    start_at = normalize_instant(start["occurred_at"])
    stop_at = normalize_instant(stop["occurred_at"])
    if epoch_millis(start_at) > first_frame_millis:
        raise ValueError("VIEW_START was not committed before first broker delivery")
    if epoch_millis(stop_at) < last_frame_millis:
        raise ValueError("VIEW_STOP precedes the last broker-observed frame")
    delivered = stop["metadata"]["framesDelivered"]
    rendered = stop["metadata"]["framesRenderAcknowledged"]
    if not isinstance(delivered, int) or not isinstance(rendered, int) or delivered < 1 or rendered < 1:
        raise ValueError("VIEW_STOP frame counters are invalid")
    if rendered > delivered:
        raise ValueError("VIEW_STOP rendered count exceeds delivered count")
    content_writes = recording_content_writes(recording_raw, session_id)
    if content_writes != 0:
        raise ValueError("recording-off session contains content storage writes")

    observed_at = browser.get("observedAt")
    if not isinstance(observed_at, str):
        raise ValueError("browser observedAt is invalid")
    return {
        "schemaVersion": "faz22.6-viewer-audit-raw-v1",
        "observedAt": observed_at,
        "binding": binding,
        "chainCheckedCount": len(rows),
        "chainSha256": "sha256:" + hashlib.sha256(chain_raw).hexdigest(),
        "viewStartOccurredAt": start_at,
        "firstFrameObservedAtEpochMillis": first_frame_millis,
        "viewStopOccurredAt": stop_at,
        "viewStartPresent": True,
        "viewStartCommittedBeforeFirstDelivered": True,
        "viewStopPresent": True,
        "hashChainVerified": True,
        "framesDelivered": delivered,
        "framesRenderAcknowledged": rendered,
        "recordingMode": "disabled",
        "contentPersisted": False,
        "contentStorageWrites": content_writes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-chain-jsonl", required=True, type=Path)
    parser.add_argument("--recording-tsv", required=True, type=Path)
    parser.add_argument("--browser-evidence", required=True, type=Path)
    parser.add_argument("--frame-flow-summary", required=True, type=Path)
    parser.add_argument("--session-id-env", default="SESSION_ID")
    parser.add_argument("--stream-id-env", default="OPERATION_ID")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import os

    result = build(
        args.audit_chain_jsonl.read_bytes(), args.recording_tsv.read_bytes(),
        os.environ.get(args.session_id_env, ""), os.environ.get(args.stream_id_env, ""),
        json.loads(args.browser_evidence.read_text(encoding="utf-8")),
        json.loads(args.frame_flow_summary.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
