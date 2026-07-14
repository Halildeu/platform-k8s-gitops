"""Shared provenance helpers for Faz 22.6 VIEW_ONLY source producers."""

from __future__ import annotations

import importlib.util
import hashlib
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_source_verifier", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load verifier module: {VERIFIER_PATH}")
VERIFIER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)

IMAGE_DIGEST = re.compile(r"@(?P<digest>sha256:[a-f0-9]{64})$")


def fetch_browser_child(client: object, repository: str, run_id: int, head_sha: str) -> dict:
    workflow_path, workflow_name = VERIFIER.EXPECTED_SOURCE_WORKFLOWS["browser"]
    run = VERIFIER.fetch_run(client, repository, run_id, workflow_name, workflow_path, "browser source")
    VERIFIER.require_equal(run["head_sha"], head_sha, "browser source head SHA")
    raw = fetch_exact_artifact(
        client, repository, run_id,
        f"faz22-6-view-only-viewer-browser-evidence-{run_id}",
        {"evidence/browser.json"},
    )["evidence/browser.json"]
    child = VERIFIER.load_json_bytes(raw, "evidence/browser.json")
    VERIFIER.validate_schema(child, VERIFIER.CHILD_SCHEMA, "browser child")
    VERIFIER.require_equal(child["evidenceType"], "browser", "browser evidence type")
    VERIFIER.require_equal(child["sourceRevision"], head_sha, "browser source revision")
    return child


def fetch_exact_artifact(client: object, repository: str, run_id: int, name: str,
                         expected_files: set[str], expected_head_sha: str | None = None) -> dict[str, bytes]:
    listing = client.get_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    matches = [
        item for item in listing.get("artifacts", [])
        if isinstance(item, dict) and item.get("name") == name and item.get("expired") is False
    ]
    if len(matches) != 1:
        raise VERIFIER.EvidenceError(f"artifact identity is not unique: {name}")
    artifact = matches[0]
    if not isinstance(artifact.get("id"), int) or artifact["id"] < 1:
        raise VERIFIER.EvidenceError(f"artifact id is invalid: {name}")
    if not isinstance(artifact.get("digest"), str) or not VERIFIER.SHA256.fullmatch(artifact["digest"]):
        raise VERIFIER.EvidenceError(f"artifact digest is invalid: {name}")
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
        raise VERIFIER.EvidenceError(f"artifact run binding is invalid: {name}")
    if expected_head_sha is not None and workflow_run.get("head_sha") != expected_head_sha:
        raise VERIFIER.EvidenceError(f"artifact source revision binding is invalid: {name}")
    raw_archive = client.get_bytes(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
    VERIFIER.require_equal(VERIFIER.digest_bytes(raw_archive), artifact["digest"], f"{name} archive digest")
    files = VERIFIER.safe_archive_files(raw_archive)
    if set(files) != expected_files:
        raise VERIFIER.EvidenceError(f"artifact file set mismatch: {name}")
    return files


def fetch_runtime_snapshots(client: object, repository: str, browser_run_id: int,
                            head_sha: str) -> dict[str, bytes]:
    expected = {
        "SHA256SUMS", "snapshots/d30-snapshot.json",
        "snapshots/audit-summary.json",
        "snapshots/frame-flow-summary.json",
        "snapshots/metrics-before.prom", "snapshots/metrics-after.prom",
    }
    files = fetch_exact_artifact(
        client, repository, browser_run_id,
        f"faz22-6-view-only-viewer-runtime-snapshots-{browser_run_id}", expected,
        expected_head_sha=head_sha,
    )
    try:
        lines = files["SHA256SUMS"].decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise VERIFIER.EvidenceError("runtime snapshot SHA256SUMS is not ASCII") from exc
    entries = {}
    for line in lines:
        match = re.fullmatch(r"([a-f0-9]{64})  (snapshots/[A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in entries:
            raise VERIFIER.EvidenceError("runtime snapshot SHA256SUMS entry is invalid")
        entries[match.group(2)] = match.group(1)
    if set(entries) != expected - {"SHA256SUMS"}:
        raise VERIFIER.EvidenceError("runtime snapshot SHA256SUMS file set mismatch")
    for name, digest in entries.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise VERIFIER.EvidenceError(f"runtime snapshot digest mismatch: {name}")
    return files


def image_digest(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise VERIFIER.EvidenceError(f"{label} is not an image reference")
    match = IMAGE_DIGEST.search(value)
    if match is None:
        raise VERIFIER.EvidenceError(f"{label} is not digest pinned")
    return match.group("digest")


def child(evidence_type: str, kind: str, tool: str, head_sha: str, observed_at: str,
          binding: dict, payload: dict) -> dict:
    value = {
        "schemaVersion": "faz22.6.viewOnlyViewerProductChildEvidence.v2",
        "evidenceType": evidence_type,
        "sourceRevision": head_sha,
        "observedAt": observed_at,
        "binding": binding,
        "producer": {"kind": kind, "tool": tool, "toolVersion": "v2"},
        "payload": payload,
    }
    VERIFIER.validate_schema(value, VERIFIER.CHILD_SCHEMA, f"{evidence_type} child")
    if VERIFIER.scan_hygiene(value):
        raise VERIFIER.EvidenceError(f"{evidence_type} child evidence hygiene failed")
    return value
