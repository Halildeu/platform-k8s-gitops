#!/usr/bin/env python3
"""Assemble provenance-verified Faz 22.6 viewer product evidence.

Every child must come from its dedicated, successful GitHub Actions workflow
and exact content-addressed artifact. The assembler copies those bytes without
normalization and derives the pilot window from the browser harness record.
The independent verifier remains the acceptance authority after this producer
run has completed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_product_verifier", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - repository invariant
    raise RuntimeError(f"cannot load verifier module: {VERIFIER_PATH}")
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)
GIT_SHA = re.compile(r"^[a-f0-9]{40}$")


class AssemblyError(ValueError):
    """Raised when source provenance cannot support a product evidence root."""


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise AssemblyError(f"{label} mismatch")


def fetch_source(
    client: Any, repository: str, evidence_type: str, run_id: int, head_sha: str,
) -> tuple[dict[str, Any], bytes, dict[str, Any], dict[str, Any]]:
    workflow_path, workflow_name = VERIFIER.EXPECTED_SOURCE_WORKFLOWS[evidence_type]
    run = VERIFIER.fetch_run(
        client, repository, run_id, workflow_name, workflow_path, f"{evidence_type} source",
    )
    require_equal(run["head_sha"], head_sha, f"{evidence_type} source head SHA")
    artifact_name = f"faz22-6-view-only-viewer-{evidence_type}-evidence-{run_id}"
    listing = client.get_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        raise AssemblyError(f"{evidence_type} source artifact listing is invalid")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("name") == artifact_name]
    if len(matches) != 1:
        raise AssemblyError(f"{evidence_type} source artifact identity is not unique")
    artifact = matches[0]
    artifact_id = artifact.get("id")
    artifact_digest = artifact.get("digest")
    if not isinstance(artifact_id, int) or artifact_id < 1:
        raise AssemblyError(f"{evidence_type} source artifact id is invalid")
    if not isinstance(artifact_digest, str) or not VERIFIER.SHA256.fullmatch(artifact_digest):
        raise AssemblyError(f"{evidence_type} source artifact digest is invalid")
    if artifact.get("expired") is not False:
        raise AssemblyError(f"{evidence_type} source artifact is expired")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
        raise AssemblyError(f"{evidence_type} source artifact run binding is invalid")

    archive = client.get_bytes(f"/repos/{repository}/actions/artifacts/{artifact_id}/zip")
    require_equal(VERIFIER.digest_bytes(archive), artifact_digest, f"{evidence_type} source archive digest")
    expected_file = f"evidence/{evidence_type}.json"
    files = VERIFIER.safe_archive_files(archive)
    if set(files) != VERIFIER.source_artifact_files(evidence_type):
        raise AssemblyError(f"{evidence_type} source artifact file set mismatch")
    raw = files[expected_file]
    child = VERIFIER.load_json_bytes(raw, expected_file)
    VERIFIER.validate_schema(child, VERIFIER.CHILD_SCHEMA, expected_file)
    VERIFIER.validate_matrix_source_attestations(evidence_type, files, raw)
    require_equal(child["evidenceType"], evidence_type, f"{evidence_type} child type")
    require_equal(child["sourceRevision"], head_sha, f"{evidence_type} child source revision")
    if scan := VERIFIER.scan_hygiene(child):
        raise AssemblyError(f"{evidence_type} evidence hygiene failed: {'; '.join(scan[:20])}")

    source = {
        "repository": repository,
        "workflowPath": workflow_path,
        "runId": run_id,
        "runAttempt": run["run_attempt"],
        "headSha": run["head_sha"],
        "artifactId": artifact_id,
        "artifactName": artifact_name,
        "artifactDigest": artifact_digest,
        "artifactFile": expected_file,
    }
    return child, raw, source, run


def assemble(
    client: Any,
    repository: str,
    producer_run_id: int,
    producer_run_attempt: int,
    head_sha: str,
    source_run_ids: dict[str, int],
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if repository != VERIFIER.EXPECTED_REPOSITORY:
        raise AssemblyError("repository is not the canonical evidence repository")
    if not GIT_SHA.fullmatch(head_sha):
        raise AssemblyError("producer head SHA is invalid")
    if set(source_run_ids) != VERIFIER.EXPECTED_CHILD_TYPES:
        raise AssemblyError("all seven source run IDs are required")
    if any(not isinstance(value, int) or value < 1 for value in source_run_ids.values()):
        raise AssemblyError("source run IDs must be positive integers")
    if len(set(source_run_ids.values())) != len(source_run_ids):
        raise AssemblyError("each evidence type must use a distinct source run")

    producer_run = client.get_json(f"/repos/{repository}/actions/runs/{producer_run_id}")
    require_equal(producer_run.get("id"), producer_run_id, "producer run id")
    require_equal(producer_run.get("event"), "workflow_dispatch", "producer event")
    require_equal(producer_run.get("head_branch"), "main", "producer branch")
    require_equal(producer_run.get("head_sha"), head_sha, "producer head SHA")
    require_equal(producer_run.get("run_attempt"), producer_run_attempt, "producer run attempt")
    require_equal(producer_run.get("name"), VERIFIER.EXPECTED_WORKFLOW_NAME, "producer workflow name")
    require_equal(producer_run.get("path"), VERIFIER.EXPECTED_WORKFLOW_PATH, "producer workflow path")
    if producer_run.get("status") not in {"in_progress", "completed"}:
        raise AssemblyError("producer run status is invalid")
    producer_started = VERIFIER.parse_utc(producer_run.get("run_started_at"), "producer run start")

    children: dict[str, dict[str, Any]] = {}
    raw_children: dict[str, bytes] = {}
    sources: dict[str, dict[str, Any]] = {}
    for evidence_type in sorted(VERIFIER.EXPECTED_CHILD_TYPES):
        child, raw, source, source_run = fetch_source(
            client, repository, evidence_type, source_run_ids[evidence_type], head_sha,
        )
        observed = VERIFIER.parse_utc(child["observedAt"], f"{evidence_type}.observedAt")
        source_updated = VERIFIER.parse_utc(source_run["updated_at"], f"{evidence_type} source update")
        VERIFIER.validate_source_attestation_timing(
            observed, source_updated, producer_started, evidence_type,
        )
        children[evidence_type] = child
        raw_children[evidence_type] = raw
        sources[evidence_type] = source

    binding = children["browser"]["binding"]
    if len(set(binding.values())) != len(binding):
        raise AssemblyError("binding hashes must be distinct")
    for evidence_type, child in children.items():
        require_equal(child["binding"], binding, f"{evidence_type} same-session binding")

    browser = children["browser"]["payload"]
    pilot_started = VERIFIER.parse_utc(browser["pilotStartedAt"], "browser pilotStartedAt")
    pilot_ended = VERIFIER.parse_utc(browser["pilotEndedAt"], "browser pilotEndedAt")
    pilot_seconds = (pilot_ended - pilot_started).total_seconds()
    if not VERIFIER.MIN_PILOT_SECONDS <= pilot_seconds <= VERIFIER.MAX_PILOT_SECONDS:
        raise AssemblyError("browser-measured pilot duration is outside the bounded window")
    for evidence_type, child in children.items():
        observed = VERIFIER.parse_utc(child["observedAt"], f"{evidence_type}.observedAt")
        latest_observed = pilot_ended + VERIFIER.RUN_CLOCK_SKEW
        if evidence_type in {"negative", "termination"}:
            latest_observed = pilot_started + VERIFIER.MAX_MATRIX_WINDOW
        if observed < pilot_started - VERIFIER.RUN_CLOCK_SKEW or observed > latest_observed:
            raise AssemblyError(f"{evidence_type} observedAt is outside the authorized evidence window")

    generated = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if generated < pilot_ended:
        raise AssemblyError("producer timestamp precedes the browser-measured pilot")
    root = {
        "schemaVersion": VERIFIER.EVIDENCE_SCHEMA,
        "environment": "test",
        "producer": {
            "repository": repository,
            "workflowPath": VERIFIER.EXPECTED_WORKFLOW_PATH,
            "runId": producer_run_id,
            "runAttempt": producer_run_attempt,
            "headSha": head_sha,
        },
        "generatedAt": VERIFIER.utc_seconds(generated),
        "pilot": {
            "startedAt": browser["pilotStartedAt"],
            "endedAt": browser["pilotEndedAt"],
        },
        "binding": binding,
        "scope": {
            "mode": "VIEW_ONLY",
            "recordingMode": "disabled",
            "attended": True,
            "maxViewers": 1,
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
            "legalAcceptance": False,
        },
        "evidence": [
            {
                "type": evidence_type,
                "path": f"evidence/{evidence_type}.json",
                "sha256": VERIFIER.digest_bytes(raw_children[evidence_type]),
                "source": sources[evidence_type],
            }
            for evidence_type in sorted(VERIFIER.EXPECTED_CHILD_TYPES)
        ],
    }
    VERIFIER.validate_schema(root, VERIFIER.ROOT_SCHEMA, "assembled root evidence")
    if scan := VERIFIER.scan_hygiene(root):
        raise AssemblyError("root evidence hygiene failed: " + "; ".join(scan[:20]))
    files = {f"evidence/{name}.json": raw for name, raw in raw_children.items()}
    files["viewer-product-evidence.json"] = (
        json.dumps(root, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return root, files


def write_files(output_dir: Path, files: dict[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise AssemblyError("output directory must be empty")
    for relative, raw in files.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--producer-run-id", type=int, required=True)
    parser.add_argument("--producer-run-attempt", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    for evidence_type in sorted(VERIFIER.EXPECTED_CHILD_TYPES):
        parser.add_argument(f"--{evidence_type}-run-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_ids = {
        name: getattr(args, f"{name}_run_id") for name in VERIFIER.EXPECTED_CHILD_TYPES
    }
    try:
        token = os.environ.get(args.github_token_env, "")
        if not token:
            raise AssemblyError(f"GitHub token environment variable is empty: {args.github_token_env}")
        client = VERIFIER.GitHubClient(token, args.github_api_url)
        root, files = assemble(
            client, args.repository, args.producer_run_id, args.producer_run_attempt,
            args.head_sha, source_ids,
        )
        write_files(args.output_dir, files)
    except (AssemblyError, VERIFIER.EvidenceError, OSError, json.JSONDecodeError) as exc:
        print(f"viewer product evidence assembly failed: {exc}", file=sys.stderr)
        return 1
    print(
        "viewer_product_evidence_assembly=pass "
        f"root_sha256={VERIFIER.digest_json(root)} sources={len(source_ids)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
