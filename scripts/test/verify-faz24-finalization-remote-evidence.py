#!/usr/bin/env python3
"""Revalidate bounded Faz 24 source/workflow evidence against GitHub REST."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


API_ROOT = "https://api.github.com/repos/Halildeu/platform-backend"
EXPECTED_PR = 872


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


def parse_json(raw: str, url: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"GitHub REST response is not JSON for {url}: {error}")
    if not isinstance(value, dict):
        fail(f"GitHub REST response must be an object for {url}")
    return value


def anonymous_json(url: str) -> dict[str, Any] | None:
    if shutil.which("curl") is None:
        return None
    try:
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--proto",
                "=https",
                "--max-redirs",
                "0",
                "--max-time",
                "30",
                "--header",
                "Accept: application/vnd.github+json",
                "--header",
                "X-GitHub-Api-Version: 2022-11-28",
                "--header",
                "User-Agent: platform-k8s-gitops-faz24-evidence",
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=35,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return parse_json(result.stdout, url)


def github_json(url: str) -> dict[str, Any]:
    prefix = "https://api.github.com/"
    if not url.startswith(prefix):
        fail(f"unexpected GitHub API URL: {url}")
    endpoint = url.removeprefix(prefix)
    if shutil.which("gh") is not None:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    "--header",
                    "Accept: application/vnd.github+json",
                    "--header",
                    "X-GitHub-Api-Version: 2022-11-28",
                    endpoint,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and result.returncode == 0:
            return parse_json(result.stdout, url)

    anonymous = anonymous_json(url)
    if anonymous is None:
        fail(f"GitHub REST fetch failed with authenticated and public access: {url}")
    return anonymous


def require_run(run: dict[str, Any], pinned: dict[str, Any]) -> None:
    expected = {
        "id": pinned.get("id"),
        "name": pinned.get("name"),
        "path": pinned.get("path"),
        "event": pinned.get("event"),
        "run_attempt": pinned.get("runAttempt"),
        "workflow_id": pinned.get("workflowId"),
        "head_sha": pinned.get("headSha"),
        "conclusion": pinned.get("conclusion"),
    }
    actual = {key: run.get(key) for key in expected}
    if actual != expected:
        fail(f"workflow run metadata changed for {pinned.get('id')}")


def require_jobs(run_id: int, pinned_jobs: list[dict[str, Any]]) -> None:
    payload = github_json(f"{API_ROOT}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = {item.get("id"): item for item in payload.get("jobs", [])}
    if len({item.get("id") for item in pinned_jobs}) != len(pinned_jobs):
        fail(f"workflow run {run_id} contains duplicate pinned job ids")
    for pinned in pinned_jobs:
        job = jobs.get(pinned.get("id"))
        if not isinstance(job, dict):
            fail(f"workflow run {run_id} lost job {pinned.get('id')}")
        if job.get("name") != pinned.get("name"):
            fail(f"workflow job {pinned.get('id')} name changed")
        if job.get("conclusion") != "success" or job.get("run_id") != run_id:
            fail(f"workflow job {pinned.get('id')} is no longer successful")
        successful_steps = {
            step.get("name")
            for step in job.get("steps", [])
            if step.get("conclusion") == "success"
        }
        if pinned.get("requiredStep") not in successful_steps:
            fail(
                f"workflow job {pinned.get('id')} did not complete required step "
                f"{pinned.get('requiredStep')}"
            )


def remote_tree(commit: str) -> dict[str, str]:
    payload = github_json(f"{API_ROOT}/git/trees/{commit}?recursive=1")
    if payload.get("truncated") is not False:
        fail(f"remote tree for {commit} is truncated")
    return {
        item.get("path"): item.get("sha")
        for item in payload.get("tree", [])
        if item.get("type") == "blob"
    }


def blob_text(blob_sha: str, cache: dict[str, str]) -> str:
    if blob_sha in cache:
        return cache[blob_sha]
    payload = github_json(f"{API_ROOT}/git/blobs/{blob_sha}")
    if payload.get("sha") != blob_sha or payload.get("encoding") != "base64":
        fail(f"remote blob metadata changed for {blob_sha}")
    try:
        value = base64.b64decode(payload.get("content", ""), validate=False).decode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError) as error:
        fail(f"cannot decode remote source blob {blob_sha}: {error}")
    cache[blob_sha] = value
    return value


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-remote-evidence.py EVIDENCE_JSON")
    evidence = load(sys.argv[1])
    claims = evidence.get("acceptedClaims", {})
    if claims.get("desiredImageProvenance") is not False:
        fail("remote guard cannot authorize desired image provenance")
    if claims.get("providerConsensus") is not False:
        fail("remote guard cannot authorize provider consensus")
    if claims.get("runtime") is not False:
        fail("remote guard cannot authorize runtime acceptance")

    backend = evidence.get("backend", {})
    reviewed_head = backend.get("reviewedSourceCommit")
    artifact_commit = backend.get("artifactCommit")

    repository = github_json(API_ROOT)
    if repository.get("full_name") != "Halildeu/platform-backend":
        fail("backend repository identity changed")
    if (
        repository.get("visibility") != "public"
        or repository.get("private") is not False
    ):
        fail("backend public REST evidence boundary changed")

    pull = github_json(f"{API_ROOT}/pulls/{EXPECTED_PR}")
    if pull.get("merged") is not True:
        fail("backend PR #872 is not merged")
    if pull.get("head", {}).get("sha") != reviewed_head:
        fail("backend PR #872 reviewed head changed")
    if pull.get("merge_commit_sha") != artifact_commit:
        fail("backend PR #872 artifact commit changed")

    reviewed_commit = github_json(f"{API_ROOT}/git/commits/{reviewed_head}")
    artifact_git_commit = github_json(f"{API_ROOT}/git/commits/{artifact_commit}")
    if reviewed_commit.get("tree", {}).get("sha") != artifact_git_commit.get(
        "tree", {}
    ).get("sha"):
        fail("reviewed source and artifact commits no longer have the same tree")

    for key in ("testRun", "authContractRun", "buildRun"):
        pinned = backend.get(key, {})
        run_id = pinned.get("id")
        if not isinstance(run_id, int):
            fail(f"{key} run id is missing")
        require_run(github_json(f"{API_ROOT}/actions/runs/{run_id}"), pinned)
        require_jobs(run_id, pinned.get("jobs", []))

    tree = remote_tree(str(reviewed_head))
    source_records = list(evidence.get("implementationContracts", []))
    test_records = [
        test
        for invariant in evidence.get("invariants", [])
        for test in invariant.get("tests", [])
    ]
    for record in source_records + test_records:
        path = record.get("path")
        expected_blob = record.get("blobSha")
        if tree.get(path) != expected_blob:
            fail(f"reviewed commit path/blob changed: {path}")

    blobs: dict[str, str] = {}
    for record in test_records:
        method = record.get("method")
        path = record.get("path")
        content = blob_text(str(record.get("blobSha")), blobs)
        if method == "class-contract":
            expected_class = Path(str(path)).stem
            if expected_class not in content:
                fail(f"remote test class is missing from pinned blob: {path}")
        elif not isinstance(method, str) or method not in content:
            fail(f"remote test method is missing from pinned blob: {path}#{method}")

    history = evidence.get("reviewHistory", {})
    if history.get("independentRemoteAttestations") is not False:
        fail("owner summary cannot be treated as independent provider evidence")
    if history.get("acceptanceEffect") != "excluded":
        fail("owner summary must remain excluded from acceptance")
    receipt = history.get("remoteReceipt", {})
    comment = github_json(str(receipt.get("apiUrl", "")))
    body = comment.get("body")
    if not isinstance(body, str):
        fail("review history comment body is missing")
    actual_receipt = {
        "apiUrl": comment.get("url"),
        "commentId": comment.get("id"),
        "nodeId": comment.get("node_id"),
        "author": comment.get("user", {}).get("login"),
        "authorAssociation": comment.get("author_association"),
        "createdAt": comment.get("created_at"),
        "updatedAt": comment.get("updated_at"),
        "bodySha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "remoteVerificationRequired": True,
    }
    if actual_receipt != receipt:
        fail("live owner-summary comment no longer matches its pinned receipt")

    print("PASS: bounded Faz 24 source/workflow claims match GitHub REST truth")


if __name__ == "__main__":
    main()
