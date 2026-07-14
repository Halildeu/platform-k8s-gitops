#!/usr/bin/env python3
"""Produce negative/termination child evidence from verified collector runs."""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
import sys
from pathlib import Path
from typing import Any

import view_only_viewer_source_common as common


COLLECTOR_WORKFLOWS = {
    "negative": (
        ".github/workflows/faz22-6-view-only-viewer-matrix-collector.yml",
        "Faz 22.6 VIEW_ONLY viewer matrix collector",
    ),
    "termination": (
        ".github/workflows/faz22-6-view-only-viewer-termination-collector.yml",
        "Faz 22.6 VIEW_ONLY viewer termination collector",
    ),
}
CONTEXT_SCHEMA = "faz22.6.viewOnlyViewerMatrixCollectorContext.v1"
TERMINATION_CASE_CONTEXT_SCHEMA = "faz22.6.viewOnlyViewerTerminationCaseCollectorContext.v1"
MAX_CASE_CONTEXT_DELAY = timedelta(minutes=5)


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
    if evidence_type != "negative":
        raise common.VERIFIER.EvidenceError("only negative evidence uses an aggregate collector run")
    workflow_path, workflow_name = COLLECTOR_WORKFLOWS[evidence_type]
    run = common.VERIFIER.fetch_run(
        client, repository, collector_run_id, workflow_name,
        workflow_path, "matrix collector",
    )
    common.VERIFIER.require_equal(run["head_sha"], head_sha, "matrix collector head SHA")
    expected = {"context.json", "observations/negative.jsonl"}
    return common.fetch_exact_artifact(
        client, repository, collector_run_id,
        f"faz22-6-view-only-viewer-matrix-collector-{evidence_type}-{collector_run_id}",
        expected, expected_head_sha=head_sha,
    )


def fetch_termination_case_files(client: object, repository: str, collector_run_id: int,
                                 head_sha: str, case_name: str) -> dict[str, bytes]:
    if case_name not in common.VERIFIER.TERMINATION_CASES:
        raise common.VERIFIER.EvidenceError("termination collector case is invalid")
    workflow_path, workflow_name = COLLECTOR_WORKFLOWS["termination"]
    run = common.VERIFIER.fetch_run(
        client, repository, collector_run_id, workflow_name,
        workflow_path, f"termination {case_name} collector",
    )
    common.VERIFIER.require_equal(
        run["head_sha"], head_sha, f"termination {case_name} collector head SHA",
    )
    expected = {
        "context.json", f"observations/{case_name}.jsonl", f"audit/{case_name}.jsonl",
    }
    return common.fetch_exact_artifact(
        client, repository, collector_run_id,
        f"faz22-6-view-only-viewer-termination-collector-{case_name}-{collector_run_id}",
        expected, expected_head_sha=head_sha,
    )


def load_context(raw: bytes, evidence_type: str, head_sha: str) -> dict[str, Any]:
    if evidence_type != "negative":
        raise common.VERIFIER.EvidenceError("only negative evidence uses aggregate collector context")
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
    if context["auditSha256"] is not None:
        raise common.VERIFIER.EvidenceError("negative collector must not claim an audit file")
    if common.VERIFIER.scan_hygiene(context):
        raise common.VERIFIER.EvidenceError("collector context evidence hygiene failed")
    return context


def load_termination_case_context(raw: bytes, case_name: str, head_sha: str) -> dict[str, Any]:
    context = common.VERIFIER.load_json_bytes(raw, f"termination {case_name} collector context")
    expected = {
        "schemaVersion", "evidenceType", "caseName", "sourceRevision", "collectedAt",
        "authorizationSha256", "rootBinding", "observationSha256", "auditSha256",
    }
    if set(context) != expected:
        raise common.VERIFIER.EvidenceError("termination case collector context field set mismatch")
    common.VERIFIER.require_equal(
        context["schemaVersion"], TERMINATION_CASE_CONTEXT_SCHEMA,
        "termination case collector context schema",
    )
    common.VERIFIER.require_equal(context["evidenceType"], "termination",
                                  "termination case collector evidence type")
    common.VERIFIER.require_equal(context["caseName"], case_name,
                                  "termination case collector case")
    common.VERIFIER.require_equal(context["sourceRevision"], head_sha,
                                  "termination case collector source revision")
    common.VERIFIER.parse_utc(context["collectedAt"], "termination case collector collectedAt")
    require_binding(context["rootBinding"], "termination case collector root binding")
    for field in ("authorizationSha256", "observationSha256", "auditSha256"):
        if not isinstance(context[field], str) or not common.VERIFIER.SHA256.fullmatch(context[field]):
            raise common.VERIFIER.EvidenceError(f"termination case collector {field} is invalid")
    if common.VERIFIER.scan_hygiene(context):
        raise common.VERIFIER.EvidenceError("termination case collector context evidence hygiene failed")
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
        observed, raw, case = build_termination_case(
            context, case_name, snapshot, snapshot_raw, audit, audit_line,
        )
        latest = observed if latest is None or observed > latest else latest
        files[f"attestations/termination/{case_name}.json"] = raw
        cases[case_name] = case
    payload = {"authorizationSha256": context["authorizationSha256"], "cases": cases}
    payload["suiteSha256"] = common.VERIFIER.digest_json(payload)
    child = common.child(
        "termination", "termination-harness",
        "scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py",
        context["sourceRevision"], latest.isoformat().replace("+00:00", "Z"),
        context["rootBinding"], payload,
    )
    return child, files


def build_termination_case(context: dict[str, Any], case_name: str, snapshot: dict[str, Any],
                           snapshot_raw: bytes, audit: dict[str, Any],
                           audit_line: bytes) -> tuple[Any, bytes, dict[str, Any]]:
    require_binding(snapshot.get("binding"), f"termination {case_name} binding")
    observed = common.VERIFIER.parse_utc(snapshot.get("observedAt"),
                                         f"termination {case_name} observedAt")
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
    latency = attestation["deliveryEndedAtEpochMillis"] - attestation["triggeredAtEpochMillis"]
    case = {
        "observedAt": snapshot["observedAt"],
        "binding": snapshot["binding"],
        "result": "terminated",
        "trigger": snapshot["trigger"],
        "deliveryTerminated": True,
        "terminationLatencyMillis": latency,
        "evidenceSha256": common.VERIFIER.digest_bytes(raw),
        "viewStopAuditSha256": common.VERIFIER.digest_bytes(audit_line),
    }
    return observed, raw, case


def produce(client: object, repository: str, collector_run_id: int,
            head_sha: str, evidence_type: str) -> dict[str, bytes]:
    if evidence_type != "negative":
        raise common.VERIFIER.EvidenceError("termination evidence requires five case collector runs")
    files = fetch_collector_files(client, repository, collector_run_id, head_sha, evidence_type)
    context = load_context(files["context.json"], evidence_type, head_sha)
    observations_raw = files[f"observations/{evidence_type}.jsonl"]
    common.VERIFIER.require_equal(
        common.VERIFIER.digest_bytes(observations_raw), context["observationsSha256"],
        "collector observations digest",
    )
    child, output = build_negative(context, observations_raw)
    child_raw = encode_json(child)
    output[f"evidence/{evidence_type}.json"] = child_raw
    common.VERIFIER.validate_matrix_source_attestations(evidence_type, output, child_raw)
    return output


def produce_termination(client: object, repository: str, collector_runs: dict[str, int],
                        head_sha: str) -> dict[str, bytes]:
    expected_cases = set(common.VERIFIER.TERMINATION_CASES)
    if set(collector_runs) != expected_cases:
        raise common.VERIFIER.EvidenceError("all five termination collector case runs are required")
    if len(set(collector_runs.values())) != len(collector_runs):
        raise common.VERIFIER.EvidenceError("termination collector runs must be distinct")
    observations: list[bytes] = []
    audits: list[bytes] = []
    root_context: dict[str, Any] | None = None
    for case_name in common.VERIFIER.TERMINATION_CASES:
        files = fetch_termination_case_files(
            client, repository, collector_runs[case_name], head_sha, case_name,
        )
        context = load_termination_case_context(files["context.json"], case_name, head_sha)
        if root_context is None:
            root_context = context
        else:
            common.VERIFIER.require_equal(
                context["authorizationSha256"], root_context["authorizationSha256"],
                f"termination {case_name} protected authorization",
            )
            common.VERIFIER.require_equal(
                context["rootBinding"], root_context["rootBinding"],
                f"termination {case_name} canonical root binding",
            )
        observation = files[f"observations/{case_name}.jsonl"]
        audit = files[f"audit/{case_name}.jsonl"]
        common.VERIFIER.require_equal(
            common.VERIFIER.digest_bytes(observation), context["observationSha256"],
            f"termination {case_name} observation digest",
        )
        common.VERIFIER.require_equal(
            common.VERIFIER.digest_bytes(audit), context["auditSha256"],
            f"termination {case_name} audit digest",
        )
        snapshot, _ = common.VERIFIER.load_canonical_matrix_jsonl(
            observation, f"termination {case_name} observation", (case_name,),
        )[case_name]
        common.VERIFIER.load_canonical_matrix_jsonl(
            audit, f"termination {case_name} audit", (case_name,),
        )
        observed_at = common.VERIFIER.parse_utc(
            snapshot.get("observedAt"), f"termination {case_name} observedAt",
        )
        collected_at = common.VERIFIER.parse_utc(
            context["collectedAt"], f"termination {case_name} collectedAt",
        )
        delay = collected_at - observed_at
        if delay < timedelta(0) or delay > MAX_CASE_CONTEXT_DELAY:
            raise common.VERIFIER.EvidenceError(
                f"termination {case_name} collector context is not fresh relative to observation"
            )
        observations.append(observation)
        audits.append(audit)
    assert root_context is not None
    aggregate_context = {
        "sourceRevision": head_sha,
        "authorizationSha256": root_context["authorizationSha256"],
        "rootBinding": root_context["rootBinding"],
    }
    child, output = build_termination(
        aggregate_context, b"".join(observations), b"".join(audits),
    )
    child_raw = encode_json(child)
    output["evidence/termination.json"] = child_raw
    common.VERIFIER.validate_matrix_source_attestations("termination", output, child_raw)
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
    parser.add_argument("--collector-run-id", type=int)
    parser.add_argument("--termination-case-run", action="append", default=[])
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--evidence-type", choices=("negative", "termination"), required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        client = common.VERIFIER.GitHubClient(os.environ.get("GITHUB_TOKEN", ""))
        if args.evidence_type == "negative":
            if args.collector_run_id is None or args.termination_case_run:
                raise common.VERIFIER.EvidenceError("negative evidence requires one collector run")
            files = produce(client, args.repository, args.collector_run_id, args.head_sha, "negative")
        else:
            if args.collector_run_id is not None:
                raise common.VERIFIER.EvidenceError("termination evidence uses case-bound collector runs")
            collector_runs: dict[str, int] = {}
            for item in args.termination_case_run:
                case_name, separator, run_id = item.partition("=")
                if not separator or case_name in collector_runs or not run_id.isdigit():
                    raise common.VERIFIER.EvidenceError("termination case run must be unique CASE=RUN_ID")
                collector_runs[case_name] = int(run_id)
            files = produce_termination(client, args.repository, collector_runs, args.head_sha)
        write_output(args.output_dir, files)
        return 0
    except (common.VERIFIER.EvidenceError, OSError, ValueError, TypeError) as exc:
        print(f"matrix_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
