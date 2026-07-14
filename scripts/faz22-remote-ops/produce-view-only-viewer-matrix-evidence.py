#!/usr/bin/env python3
"""Produce negative/termination child evidence from a verified collector run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import view_only_viewer_source_common as common


COLLECTOR_WORKFLOW_PATH = ".github/workflows/faz22-6-view-only-viewer-matrix-collector.yml"
COLLECTOR_WORKFLOW_NAME = "Faz 22.6 VIEW_ONLY viewer matrix collector"
CONTEXT_SCHEMA = "faz22.6.viewOnlyViewerMatrixCollectorContext.v1"


def encode_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def require_binding(value: Any, label: str) -> dict[str, str]:
    expected = {"sessionSha256", "tenantSha256", "operatorSha256", "deviceSha256"}
    if not isinstance(value, dict) or set(value) != expected:
        raise common.VERIFIER.EvidenceError(f"{label} field set mismatch")
    for field, digest in value.items():
        if not isinstance(digest, str) or not common.VERIFIER.SHA256.fullmatch(digest):
            raise common.VERIFIER.EvidenceError(f"{label} {field} is invalid")
    if len(set(value.values())) != len(value):
        raise common.VERIFIER.EvidenceError(f"{label} hashes must be distinct")
    return value


def fetch_collector_files(client: object, repository: str, collector_run_id: int,
                          head_sha: str, evidence_type: str) -> dict[str, bytes]:
    run = common.VERIFIER.fetch_run(
        client, repository, collector_run_id, COLLECTOR_WORKFLOW_NAME,
        COLLECTOR_WORKFLOW_PATH, "matrix collector",
    )
    common.VERIFIER.require_equal(run["head_sha"], head_sha, "matrix collector head SHA")
    expected = {"context.json", f"observations/{evidence_type}.jsonl"}
    if evidence_type == "termination":
        expected.add("audit/termination.jsonl")
    return common.fetch_exact_artifact(
        client, repository, collector_run_id,
        f"faz22-6-view-only-viewer-matrix-collector-{evidence_type}-{collector_run_id}",
        expected, expected_head_sha=head_sha,
    )


def load_context(raw: bytes, evidence_type: str, head_sha: str) -> dict[str, Any]:
    context = common.VERIFIER.load_json_bytes(raw, "collector context")
    expected = {
        "schemaVersion", "evidenceType", "sourceRevision", "collectedAt",
        "authorizationSha256", "rootBinding", "observationsSha256", "auditSha256",
    }
    if set(context) != expected:
        raise common.VERIFIER.EvidenceError("collector context field set mismatch")
    common.VERIFIER.require_equal(context["schemaVersion"], CONTEXT_SCHEMA,
                                  "collector context schema")
    common.VERIFIER.require_equal(context["evidenceType"], evidence_type,
                                  "collector evidence type")
    common.VERIFIER.require_equal(context["sourceRevision"], head_sha,
                                  "collector source revision")
    common.VERIFIER.parse_utc(context["collectedAt"], "collector collectedAt")
    require_binding(context["rootBinding"], "collector root binding")
    for field in ("authorizationSha256", "observationsSha256"):
        if not isinstance(context[field], str) or not common.VERIFIER.SHA256.fullmatch(context[field]):
            raise common.VERIFIER.EvidenceError(f"collector {field} is invalid")
    if evidence_type == "termination":
        if not isinstance(context["auditSha256"], str) \
                or not common.VERIFIER.SHA256.fullmatch(context["auditSha256"]):
            raise common.VERIFIER.EvidenceError("collector auditSha256 is invalid")
    elif context["auditSha256"] is not None:
        raise common.VERIFIER.EvidenceError("negative collector must not claim an audit file")
    if common.VERIFIER.scan_hygiene(context):
        raise common.VERIFIER.EvidenceError("collector context evidence hygiene failed")
    return context


def build_negative(context: dict[str, Any], observations_raw: bytes) -> tuple[dict, dict[str, bytes]]:
    observations = common.VERIFIER.load_canonical_matrix_jsonl(
        observations_raw, "negative observations", common.VERIFIER.NEGATIVE_CASES,
    )
    cases: dict[str, Any] = {}
    files: dict[str, bytes] = {"observations/negative.jsonl": observations_raw}
    latest = None
    for case_name in common.VERIFIER.NEGATIVE_CASES:
        snapshot, snapshot_raw = observations[case_name]
        require_binding(snapshot.get("binding"), f"negative {case_name} binding")
        observed = common.VERIFIER.parse_utc(snapshot.get("observedAt"),
                                             f"negative {case_name} observedAt")
        latest = observed if latest is None or observed > latest else latest
        contract = common.VERIFIER.NEGATIVE_CASE_CONTRACT[case_name]
        attestation = {
            "schemaVersion": "faz22.6.viewOnlyViewerNegativeCaseAttestation.v1",
            "caseName": case_name,
            "sourceRevision": context["sourceRevision"],
            "observedAt": snapshot["observedAt"],
            "binding": snapshot["binding"],
            "authorizationSha256": context["authorizationSha256"],
            "runtimeSnapshotSha256": common.VERIFIER.digest_bytes(snapshot_raw),
            "request": snapshot.get("request"),
            "result": {
                "outcome": contract.outcome,
                "requestAccepted": False,
                "deliveryContinued": False,
                "httpStatus": snapshot.get("response", {}).get("httpStatus"),
            },
        }
        common.VERIFIER.validate_matrix_supporting_evidence(
            "negative", case_name, attestation, snapshot, snapshot_raw,
        )
        raw = encode_json(attestation)
        files[f"attestations/negative/{case_name}.json"] = raw
        cases[case_name] = {
            "observedAt": snapshot["observedAt"],
            "binding": snapshot["binding"],
            "result": "fail-closed",
            "outcome": contract.outcome,
            "requestAccepted": False,
            "deliveryContinued": False,
            "httpStatus": contract.http_status,
            "evidenceSha256": common.VERIFIER.digest_bytes(raw),
        }
    payload = {"authorizationSha256": context["authorizationSha256"], "cases": cases}
    payload["suiteSha256"] = common.VERIFIER.digest_json(payload)
    child = common.child(
        "negative", "negative-harness",
        "scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py",
        context["sourceRevision"], latest.isoformat().replace("+00:00", "Z"),
        context["rootBinding"], payload,
    )
    return child, files


def build_termination(context: dict[str, Any], observations_raw: bytes,
                      audit_raw: bytes) -> tuple[dict, dict[str, bytes]]:
    observations = common.VERIFIER.load_canonical_matrix_jsonl(
        observations_raw, "termination observations", common.VERIFIER.TERMINATION_CASES,
    )
    audits = common.VERIFIER.load_canonical_matrix_jsonl(
        audit_raw, "termination audit", common.VERIFIER.TERMINATION_CASES,
    )
    cases: dict[str, Any] = {}
    files: dict[str, bytes] = {
        "observations/termination.jsonl": observations_raw,
        "audit/termination.jsonl": audit_raw,
    }
    latest = None
    for case_name in common.VERIFIER.TERMINATION_CASES:
        snapshot, snapshot_raw = observations[case_name]
        audit, audit_line = audits[case_name]
        require_binding(snapshot.get("binding"), f"termination {case_name} binding")
        observed = common.VERIFIER.parse_utc(snapshot.get("observedAt"),
                                             f"termination {case_name} observedAt")
        latest = observed if latest is None or observed > latest else latest
        attestation = {
            "schemaVersion": "faz22.6.viewOnlyViewerTerminationCaseAttestation.v1",
            "caseName": case_name,
            "sourceRevision": context["sourceRevision"],
            "observedAt": snapshot["observedAt"],
            "binding": snapshot["binding"],
            "authorizationSha256": context["authorizationSha256"],
            "runtimeSnapshotSha256": common.VERIFIER.digest_bytes(snapshot_raw),
            "trigger": snapshot.get("trigger"),
            "triggeredAtEpochMillis": snapshot.get("triggeredAtEpochMillis"),
            "deliveryEndedAtEpochMillis": snapshot.get("deliveryEndedAtEpochMillis"),
            "result": {"deliveryTerminated": True},
            "viewStopAuditSha256": common.VERIFIER.digest_bytes(audit_line),
            "productSignals": snapshot.get("terminal"),
        }
        common.VERIFIER.validate_matrix_supporting_evidence(
            "termination", case_name, attestation, snapshot, snapshot_raw, audit, audit_line,
        )
        raw = encode_json(attestation)
        files[f"attestations/termination/{case_name}.json"] = raw
        latency = attestation["deliveryEndedAtEpochMillis"] - attestation["triggeredAtEpochMillis"]
        cases[case_name] = {
            "observedAt": snapshot["observedAt"],
            "binding": snapshot["binding"],
            "result": "terminated",
            "trigger": snapshot["trigger"],
            "deliveryTerminated": True,
            "terminationLatencyMillis": latency,
            "evidenceSha256": common.VERIFIER.digest_bytes(raw),
            "viewStopAuditSha256": common.VERIFIER.digest_bytes(audit_line),
        }
    payload = {"authorizationSha256": context["authorizationSha256"], "cases": cases}
    payload["suiteSha256"] = common.VERIFIER.digest_json(payload)
    child = common.child(
        "termination", "termination-harness",
        "scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py",
        context["sourceRevision"], latest.isoformat().replace("+00:00", "Z"),
        context["rootBinding"], payload,
    )
    return child, files


def produce(client: object, repository: str, collector_run_id: int,
            head_sha: str, evidence_type: str) -> dict[str, bytes]:
    files = fetch_collector_files(client, repository, collector_run_id, head_sha, evidence_type)
    context = load_context(files["context.json"], evidence_type, head_sha)
    observations_raw = files[f"observations/{evidence_type}.jsonl"]
    common.VERIFIER.require_equal(
        common.VERIFIER.digest_bytes(observations_raw), context["observationsSha256"],
        "collector observations digest",
    )
    if evidence_type == "negative":
        child, output = build_negative(context, observations_raw)
    else:
        audit_raw = files["audit/termination.jsonl"]
        common.VERIFIER.require_equal(
            common.VERIFIER.digest_bytes(audit_raw), context["auditSha256"],
            "collector audit digest",
        )
        child, output = build_termination(context, observations_raw, audit_raw)
    child_raw = encode_json(child)
    output[f"evidence/{evidence_type}.json"] = child_raw
    common.VERIFIER.validate_matrix_source_attestations(evidence_type, output, child_raw)
    return output


def write_output(output_dir: Path, files: dict[str, bytes]) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise common.VERIFIER.EvidenceError("output directory must be empty")
    for name, raw in files.items():
        path = output_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--collector-run-id", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--evidence-type", choices=("negative", "termination"), required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        files = produce(
            common.VERIFIER.GitHubClient(os.environ.get("GITHUB_TOKEN", "")),
            args.repository, args.collector_run_id, args.head_sha, args.evidence_type,
        )
        write_output(args.output_dir, files)
        return 0
    except (common.VERIFIER.EvidenceError, OSError, ValueError, TypeError) as exc:
        print(f"matrix_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
