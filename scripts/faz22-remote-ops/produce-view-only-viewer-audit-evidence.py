#!/usr/bin/env python3
"""Produce audit child evidence from a verified live tenant-chain summary."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import view_only_viewer_source_common as common


EXPECTED_FIELDS = {
    "schemaVersion", "observedAt", "binding", "chainCheckedCount", "chainSha256",
    "viewStartOccurredAt", "firstFrameObservedAtEpochMillis", "viewStopOccurredAt",
    "viewStartPresent", "viewStartCommittedBeforeFirstDelivered", "viewStopPresent",
    "hashChainVerified", "framesDelivered", "framesRenderAcknowledged",
    "recordingMode", "contentPersisted", "contentStorageWrites",
}


def produce(client: object, repository: str, browser_run_id: int, head_sha: str) -> dict:
    browser = common.fetch_browser_child(client, repository, browser_run_id, head_sha)
    files = common.fetch_runtime_snapshots(client, repository, browser_run_id, head_sha)
    raw = files["snapshots/audit-summary.json"]
    snapshot = common.VERIFIER.load_json_bytes(raw, "audit-summary.json")
    if set(snapshot) != EXPECTED_FIELDS:
        raise common.VERIFIER.EvidenceError("audit summary field set mismatch")
    if snapshot["schemaVersion"] != "faz22.6-viewer-audit-raw-v1":
        raise common.VERIFIER.EvidenceError("audit summary schema mismatch")
    if snapshot["binding"] != browser["binding"]:
        raise common.VERIFIER.EvidenceError("audit/browser same-session binding mismatch")
    common.VERIFIER.parse_utc(snapshot["observedAt"], "audit observedAt")
    common.VERIFIER.parse_utc(snapshot["viewStartOccurredAt"], "VIEW_START occurredAt")
    common.VERIFIER.parse_utc(snapshot["viewStopOccurredAt"], "VIEW_STOP occurredAt")
    if not isinstance(snapshot["chainCheckedCount"], int) or snapshot["chainCheckedCount"] < 2:
        raise common.VERIFIER.EvidenceError("audit chain checked count is invalid")
    if not common.VERIFIER.SHA256.fullmatch(str(snapshot["chainSha256"])):
        raise common.VERIFIER.EvidenceError("audit chain digest is invalid")
    for field in (
        "viewStartPresent", "viewStartCommittedBeforeFirstDelivered",
        "viewStopPresent", "hashChainVerified",
    ):
        if snapshot[field] is not True:
            raise common.VERIFIER.EvidenceError(f"audit proof failed: {field}")
    if snapshot["recordingMode"] != "disabled" or snapshot["contentPersisted"] is not False \
            or snapshot["contentStorageWrites"] != 0:
        raise common.VERIFIER.EvidenceError("audit snapshot recording-off boundary failed")
    delivered = snapshot["framesDelivered"]
    rendered = snapshot["framesRenderAcknowledged"]
    if not isinstance(delivered, int) or not isinstance(rendered, int) \
            or delivered < 1 or rendered < 1 or rendered > delivered:
        raise common.VERIFIER.EvidenceError("audit frame counters are invalid")
    payload = {
        "viewStartPresent": True,
        "viewStartCommittedBeforeFirstDelivered": True,
        "viewStopPresent": True,
        "hashChainVerified": True,
        "framesDelivered": delivered,
        "framesRenderAcknowledged": rendered,
        "snapshotSha256": common.VERIFIER.digest_bytes(raw),
    }
    return common.child(
        "audit", "audit-verifier",
        "scripts/faz22-remote-ops/produce-view-only-viewer-audit-evidence.py",
        head_sha, snapshot["observedAt"], browser["binding"], payload,
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
        print(f"audit_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
