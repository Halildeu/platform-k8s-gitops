#!/usr/bin/env python3
"""Operator-gated check of image digests against immutable GitHub job logs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPOSITORY = "Halildeu/platform-backend"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load(path: str) -> dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot load evidence: {error}")
    if not isinstance(value, dict):
        fail("evidence root must be an object")
    return value


def gh(args: list[str], label: str) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        fail(f"{label} timed out")
    if result.returncode != 0:
        fail(f"{label} failed; operator Actions-read access is required")
    return result.stdout


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-build-provenance.py EVIDENCE_JSON")
    if shutil.which("gh") is None:
        fail("GitHub CLI is required for operator build provenance")
    evidence = load(sys.argv[1])
    if evidence.get("acceptedClaims", {}).get("desiredImageProvenance") is not False:
        fail("operator preflight cannot mutate static image-provenance acceptance")
    backend = evidence.get("backend", {})
    build_run = backend.get("buildRun", {})
    run_id = build_run.get("id")
    artifact_commit = backend.get("artifactCommit")
    if not isinstance(run_id, int):
        fail("build run id is missing")

    live_run = json.loads(
        gh(
            ["api", f"repos/{REPOSITORY}/actions/runs/{run_id}"],
            "immutable build run fetch",
        )
    )
    expected_run = {
        "id": run_id,
        "name": build_run.get("name"),
        "path": build_run.get("path"),
        "event": build_run.get("event"),
        "run_attempt": build_run.get("runAttempt"),
        "workflow_id": build_run.get("workflowId"),
        "head_sha": artifact_commit,
        "conclusion": "success",
    }
    if {key: live_run.get(key) for key in expected_run} != expected_run:
        fail("live build run metadata no longer matches the pinned run")

    pinned_jobs = {job.get("id"): job for job in build_run.get("jobs", [])}

    for image in backend.get("desiredImages", []):
        service = image.get("service")
        job_id = image.get("buildJobId")
        digest = image.get("digest")
        image_name = image.get("image")
        artifact_id = image.get("artifactId")
        artifact_name = image.get("artifactName")
        artifact_hash = image.get("artifactUploadSha256")
        if not isinstance(job_id, int) or not isinstance(artifact_id, int):
            fail(f"{service} provenance ids are missing")
        if image.get("provenanceStatus") != "pending-post-push-operator-preflight":
            fail(f"{service} provenance status is not operator-pending")
        if image.get("acceptanceEffect") != "excluded":
            fail(f"{service} image provenance escaped the static acceptance boundary")

        pinned_job = pinned_jobs.get(job_id)
        if not isinstance(pinned_job, dict):
            fail(f"{service} build job is not pinned by the reviewed build run")
        live_job = json.loads(
            gh(
                ["api", f"repos/{REPOSITORY}/actions/jobs/{job_id}"],
                f"{service} immutable job metadata fetch",
            )
        )
        successful_steps = {
            step.get("name")
            for step in live_job.get("steps", [])
            if step.get("conclusion") == "success"
        }
        if (
            live_job.get("id") != job_id
            or live_job.get("run_id") != run_id
            or live_job.get("run_attempt") != build_run.get("runAttempt")
            or live_job.get("head_sha") != artifact_commit
            or live_job.get("name") != pinned_job.get("name")
            or live_job.get("workflow_name") != build_run.get("name")
            or live_job.get("status") != "completed"
            or live_job.get("conclusion") != "success"
            or pinned_job.get("requiredStep") not in successful_steps
        ):
            fail(f"{service} live build job metadata no longer matches the pin")

        log = gh(
            [
                "run",
                "view",
                str(run_id),
                "--repo",
                REPOSITORY,
                "--job",
                str(job_id),
                "--log",
            ],
            f"{service} immutable job log fetch",
        )
        required_log_fragments = {
            str(digest),
            f"{image_name}@{digest}",
            f"SHA256 hash of uploaded artifact is {artifact_hash}",
            f"Artifact successfully finalized ({artifact_id})",
        }
        for fragment in required_log_fragments:
            if fragment not in log:
                fail(f"{service} job log lost pinned digest/artifact provenance")

        artifact = json.loads(
            gh(
                [
                    "api",
                    f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}",
                ],
                f"{service} build artifact fetch",
            )
        )
        if (
            artifact.get("id") != artifact_id
            or artifact.get("name") != artifact_name
            or artifact.get("expired") is not False
            or artifact.get("workflow_run", {}).get("id") != run_id
            or artifact.get("workflow_run", {}).get("head_sha") != artifact_commit
        ):
            fail(f"{service} live build artifact metadata changed")

    print("PASS: operator verified immutable build-log and artifact provenance")


if __name__ == "__main__":
    main()
