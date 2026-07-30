#!/usr/bin/env python3
"""Produce broker child evidence from digest-verified live runtime snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import view_only_viewer_source_common as common


LINE = re.compile(
    r"^(?P<name>(?:remote_access_bridge_[a-z0-9_]+|process_start_time_seconds))"
    r"(?:\{(?P<labels>[^{}]+)\})?[ \t]+"
    r"(?P<value>[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)$"
)
SCALARS = {
    "remote_access_bridge_data_frames_total",
    "remote_access_bridge_viewer_started_total",
    "remote_access_bridge_viewer_ended_total",
    "remote_access_bridge_viewer_frames_sent_total",
    "remote_access_bridge_viewer_render_ack_accepted_total",
    "remote_access_bridge_viewer_render_ack_rejected_total",
}
PROCESS_START = "process_start_time_seconds"
MAX_COUNTER = 2**63 - 1
FANOUT = "remote_access_bridge_view_only_fanout_frames_total"
DISPOSITIONS = {"delivered", "dropped-no-viewer", "unauthorized", "mime-rejected"}


def parse_metrics(raw: bytes, label: str) -> dict[tuple[str, str | None], int]:
    result: dict[tuple[str, str | None], int] = {}
    for line in raw.decode("ascii", errors="strict").splitlines():
        match = LINE.fullmatch(line)
        if match is None:
            raise common.VERIFIER.EvidenceError(f"{label} contains an invalid Prometheus sample")
        name = match.group("name")
        labels = match.group("labels")
        disposition: str | None = None
        if name in SCALARS or name == PROCESS_START:
            if labels is not None:
                raise common.VERIFIER.EvidenceError(f"{label} scalar metric has labels: {name}")
        elif name == FANOUT:
            label_match = re.fullmatch(r'disposition="([a-z-]+)"', labels or "")
            if label_match is None or label_match.group(1) not in DISPOSITIONS:
                raise common.VERIFIER.EvidenceError(f"{label} fanout disposition is invalid")
            disposition = label_match.group(1)
        else:
            raise common.VERIFIER.EvidenceError(f"{label} contains an unexpected metric: {name}")
        try:
            value = Decimal(match.group("value"))
        except InvalidOperation as exc:
            raise common.VERIFIER.EvidenceError(f"{label} metric value is invalid") from exc
        if value < 0 or value > MAX_COUNTER \
                or (name != PROCESS_START and value != value.to_integral_value()):
            raise common.VERIFIER.EvidenceError(f"{label} metric is not a non-negative counter")
        key = (name, disposition)
        if key in result:
            raise common.VERIFIER.EvidenceError(f"{label} contains a duplicate metric series")
        result[key] = value if name == PROCESS_START else int(value)
    for metric in SCALARS - {"remote_access_bridge_data_frames_total"}:
        if (metric, None) not in result:
            raise common.VERIFIER.EvidenceError(f"{label} is missing scalar metric: {metric}")
    if (PROCESS_START, None) not in result:
        raise common.VERIFIER.EvidenceError(f"{label} is missing process identity metric")
    return result


def delta(before: dict, after: dict, name: str, disposition: str | None = None) -> int:
    prior = before.get((name, disposition), 0)
    current = after.get((name, disposition), 0)
    if current < prior:
        raise common.VERIFIER.EvidenceError(f"metric counter reset during pilot: {name}")
    return current - prior


def load_strict(raw: bytes, label: str, expected: set[str]) -> dict:
    value = common.VERIFIER.load_json_bytes(raw, label)
    if set(value) != expected:
        raise common.VERIFIER.EvidenceError(f"{label} field set mismatch")
    return value


def produce(client: object, repository: str, browser_run_id: int, head_sha: str) -> dict:
    browser = common.fetch_browser_child(client, repository, browser_run_id, head_sha)
    files = common.fetch_runtime_snapshots(client, repository, browser_run_id, head_sha)
    before_raw = files["snapshots/metrics-before.prom"]
    after_raw = files["snapshots/metrics-after.prom"]
    before = parse_metrics(before_raw, "metrics-before.prom")
    after = parse_metrics(after_raw, "metrics-after.prom")
    if before[(PROCESS_START, None)] != after[(PROCESS_START, None)]:
        raise common.VERIFIER.EvidenceError("broker process restarted during pilot")
    frame_raw = files["snapshots/frame-flow-summary.json"]
    frame = load_strict(frame_raw, "frame-flow-summary.json", {
        "schemaVersion", "observedAt", "binding", "firstSeq", "lastSeq",
        "firstObservedAtEpochMillis", "firstDeliveredAtEpochMillis",
        "lastObservedAtEpochMillis",
        "producedSequenceCount", "brokerReceivedDistinctCount", "sequenceGapCount",
        "dispositions", "rawLogSha256",
    })
    audit_raw = files["snapshots/audit-summary.json"]
    audit = load_strict(audit_raw, "audit-summary.json", {
        "schemaVersion", "observedAt", "binding", "chainCheckedCount", "chainSha256",
        "viewStartOccurredAt", "firstFrameObservedAtEpochMillis", "viewStopOccurredAt",
        "viewStartPresent", "viewStartCommittedBeforeFirstDelivered", "viewStopPresent",
        "hashChainVerified", "framesDelivered", "framesRenderAcknowledged",
        "recordingMode", "contentPersisted", "contentStorageWrites",
    })
    if frame["schemaVersion"] != "faz22.6-viewer-frame-flow-raw-v1":
        raise common.VERIFIER.EvidenceError("frame-flow summary schema mismatch")
    if audit["schemaVersion"] != "faz22.6-viewer-audit-raw-v1":
        raise common.VERIFIER.EvidenceError("audit summary schema mismatch")
    if frame["binding"] != browser["binding"] or audit["binding"] != browser["binding"]:
        raise common.VERIFIER.EvidenceError("runtime snapshot same-session binding mismatch")
    for field in (
        "viewStartPresent", "viewStartCommittedBeforeFirstDelivered",
        "viewStopPresent", "hashChainVerified",
    ):
        if audit[field] is not True:
            raise common.VERIFIER.EvidenceError(f"audit proof failed: {field}")
    if audit["firstFrameObservedAtEpochMillis"] != frame["firstDeliveredAtEpochMillis"]:
        raise common.VERIFIER.EvidenceError("audit/broker first-delivered timestamp mismatch")
    start_millis = int(common.VERIFIER.parse_utc(
        audit["viewStartOccurredAt"], "audit VIEW_START occurredAt",
    ).timestamp() * 1000)
    stop_millis = int(common.VERIFIER.parse_utc(
        audit["viewStopOccurredAt"], "audit VIEW_STOP occurredAt",
    ).timestamp() * 1000)
    if start_millis > frame["firstDeliveredAtEpochMillis"]:
        raise common.VERIFIER.EvidenceError("audit VIEW_START follows first broker delivery")
    if stop_millis < frame["lastObservedAtEpochMillis"]:
        raise common.VERIFIER.EvidenceError("audit VIEW_STOP precedes last broker frame")

    captured = frame["producedSequenceCount"]
    received = frame["brokerReceivedDistinctCount"]
    if not all(isinstance(value, int) and value >= 1 for value in (captured, received)):
        raise common.VERIFIER.EvidenceError("frame-flow state counters are invalid")
    if frame["sequenceGapCount"] != captured - received:
        raise common.VERIFIER.EvidenceError("frame-flow sequence gap count mismatch")
    data_frames = delta(before, after, "remote_access_bridge_data_frames_total")
    started = delta(before, after, "remote_access_bridge_viewer_started_total")
    ended = delta(before, after, "remote_access_bridge_viewer_ended_total")
    sent = delta(before, after, "remote_access_bridge_viewer_frames_sent_total")
    accepted = delta(before, after, "remote_access_bridge_viewer_render_ack_accepted_total")
    rejected = delta(before, after, "remote_access_bridge_viewer_render_ack_rejected_total")
    fanout = {name: delta(before, after, FANOUT, name) for name in DISPOSITIONS}

    if data_frames != received:
        raise common.VERIFIER.EvidenceError("broker DATA metric does not match distinct received frames")
    if started != 1 or ended != 1:
        raise common.VERIFIER.EvidenceError("pilot must start and end exactly one viewer stream")
    if rejected < 1:
        raise common.VERIFIER.EvidenceError("replayed render ACK rejection metric did not advance")
    if fanout["unauthorized"] != 0 or fanout["mime-rejected"] != 0:
        raise common.VERIFIER.EvidenceError("broker observed unauthorized or invalid-MIME VIEW_ONLY frames")
    if fanout["delivered"] + fanout["dropped-no-viewer"] != received:
        raise common.VERIFIER.EvidenceError("fanout disposition deltas do not cover broker-received frames")
    if not captured >= received >= sent >= accepted >= common.VERIFIER.MIN_RENDERED_FRAMES:
        raise common.VERIFIER.EvidenceError("broker state chain is inconsistent")
    if fanout["delivered"] < sent:
        raise common.VERIFIER.EvidenceError("viewer sent metric exceeds delivered fanout offers")
    if sent != browser["payload"]["renderAckAttemptedCount"]:
        raise common.VERIFIER.EvidenceError("viewer sent metric does not match browser ACK attempts")
    if accepted != browser["payload"]["renderAckAcceptedCount"]:
        raise common.VERIFIER.EvidenceError("accepted ACK metric does not match browser evidence")
    if audit["framesDelivered"] != sent or audit["framesRenderAcknowledged"] != accepted:
        raise common.VERIFIER.EvidenceError("audit frame counters do not match broker metrics")
    if browser["payload"].get("inputChannelControlCount") != 0:
        raise common.VERIFIER.EvidenceError("browser exposed an input-channel control")
    if audit["recordingMode"] != "disabled" or audit["contentPersisted"] is not False \
            or audit["contentStorageWrites"] != 0:
        raise common.VERIFIER.EvidenceError("recording-off persistence boundary failed")

    input_channels = {
        "keyboard": False, "mouse": False, "clipboard": False, "fileTransfer": False,
        "credentialEntry": False, "shell": False, "portForward": False, "hiddenControl": False,
    }
    payload = {
        "states": {
            "captured": captured, "brokerReceived": received,
            "viewerDelivered": sent, "viewerRendered": accepted,
        },
        "framesSentMetricDelta": sent,
        "renderAckAcceptedMetricDelta": accepted,
        "renderAckRejectedMetricDelta": rejected,
        "reconnectCount": started - 1,
        "backpressureMode": "latest-wins-single-slot",
        "maxPendingFrames": 1,
        "metricsSnapshotSha256": common.VERIFIER.digest_bytes(before_raw + b"\0" + after_raw),
        "inputChannels": input_channels,
        "dlp": {
            "deliveredPathProven": True,
            "rawContentIncluded": False,
            "maskedFrameSha256": browser["payload"]["maskedFrameSha256"],
        },
        "persistence": {
            "recordingMode": "disabled", "contentPersisted": False, "contentStorageWrites": 0,
        },
    }
    return common.child(
        "broker", "prometheus-query",
        "scripts/faz22-remote-ops/produce-view-only-viewer-broker-evidence.py",
        head_sha, frame["observedAt"], browser["binding"], payload,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--browser-run-id", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = produce(
            common.VERIFIER.GitHubClient(os.environ.get("GITHUB_TOKEN", "")),
            args.repository, args.browser_run_id, args.head_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (common.VERIFIER.EvidenceError, OSError, ValueError) as exc:
        print(f"broker_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
