#!/usr/bin/env python3
"""Revalidate bounded Faz 24 evidence against immutable GitHub records."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPOSITORY = "Halildeu/platform-backend"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}"
EXPECTED_PR = 890
REVIEWED_SOURCE_COMMIT = "36fc0ea4b0890e0e8b86809e2107523c7d09ba92"
ARTIFACT_COMMIT = "74f6b9c779e07c38eb970404fdea99502e2b9a69"
REVIEW_BASE_COMMIT = "7f0ed98f4593a5bc73ebda58bfc87a3910764874"
REVIEW_SCOPE_SHA256 = "68d4a4a3284b38c613c967891f97d8c6e13136c7a2e96959afeda2f4d8cb678d"
EXPECTED_ACCEPTED_CLAIMS = {
    "reviewedSourceTree": True,
    "workflowRunOutcomes": True,
    "desiredImageProvenance": False,
    "providerConsensus": False,
    "runtime": False,
    "downstreamAnalysis": False,
}
EXPECTED_EVIDENCE_KEYS = {
    "schemaVersion",
    "generatedAt",
    "accepted",
    "acceptanceLevel",
    "acceptedClaims",
    "runtimeAcceptance",
    "rolloutBoundary",
    "backend",
    "implementationContracts",
    "invariants",
    "providerEvidence",
    "productionGates",
}
EXPECTED_RUNS = {
    "testRun": {
        "id": 29671930063,
        "name": "CI - Maven Build Check",
        "path": ".github/workflows/ci-mvn-check.yml",
        "event": "pull_request",
        "runAttempt": 1,
        "workflowId": 265979888,
        "headSha": REVIEWED_SOURCE_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29671930063",
        "workflowBlobSha": "a8605e603dbb93a3eeab6e53186c142f336920f9",
        "jobs": [
            {
                "id": 88152457058,
                "name": "Maven full reactor build (all 12 modules)",
                "requiredStep": "Verify full reactor (12 modules, no tests)",
                "conclusion": "success",
            },
            {
                "id": 88152581595,
                "name": "meeting-service unit + Testcontainers PG test (Faz 24",
                "requiredStep": "Run meeting-service tests",
                "conclusion": "success",
            },
            {
                "id": 88152581599,
                "name": "transcript-service unit + Testcontainers PG test (Faz 24",
                "requiredStep": "Run transcript-service tests",
                "conclusion": "success",
            },
            {
                "id": 88152581600,
                "name": "audio-gateway-service test (Faz 24",
                "requiredStep": "Run audio-gateway-service tests",
                "conclusion": "success",
            },
            {
                "id": 88152581610,
                "name": "common-meeting-events contract test (Faz 24",
                "requiredStep": "Run common-meeting-events tests",
                "conclusion": "success",
            },
        ],
    },
    "authContractRun": {
        "id": 29671930046,
        "name": "CI - Auth Token Evidence",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "runAttempt": 1,
        "workflowId": 315554443,
        "headSha": REVIEWED_SOURCE_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29671930046",
        "workflowBlobSha": "0bbc1de5292bc61811a08f52d6b0701245cf860b",
        "jobs": [
            {
                "id": 88152457031,
                "name": "auth-service transcript token mint evidence",
                "requiredStep": "Run exact auth-service token mint tests",
                "conclusion": "success",
            }
        ],
    },
    "buildRun": {
        "id": 29672315566,
        "name": "CI - Image Build + GHCR Push",
        "path": ".github/workflows/ci-image-push.yml",
        "event": "push",
        "runAttempt": 1,
        "workflowId": 265996858,
        "headSha": ARTIFACT_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29672315566",
        "workflowBlobSha": "68b4c84e51d32169714e1d64b2db481326aaedb4",
        "jobs": [
            {
                "id": 88153460034,
                "name": "Build + Push auth-service",
                "requiredStep": "Build + Push image",
                "conclusion": "success",
            },
            {
                "id": 88153460058,
                "name": "Build + Push meeting-service",
                "requiredStep": "Build + Push image",
                "conclusion": "success",
            },
            {
                "id": 88153460045,
                "name": "Build + Push transcript-service",
                "requiredStep": "Build + Push image",
                "conclusion": "success",
            },
            {
                "id": 88153460060,
                "name": "Build + Push audio-gateway-service",
                "requiredStep": "Build + Push image",
                "conclusion": "success",
            },
        ],
    },
}
EXPECTED_IMPLEMENTATIONS = {
    (
        "transcript-service/src/main/java/com/example/transcript/finalization/TranscriptQuiescentFinalizationProcessor.java",
        "6adea1091e5c19edd4978ccea57a453fc023ca3f",
    ),
    (
        "transcript-service/src/main/java/com/example/transcript/service/TranscriptFinalizationService.java",
        "266c2051e96acad9e1571356cacb47e7d61f2139",
    ),
}
EXPECTED_INVARIANTS = {
    "auth-transcript-service-token-contract": {
        (
            "auth-service/src/test/java/com/example/auth/controller/MeetingAiServiceTokenMintTest.java",
            "45e23dd91eb5bb2159357bec4e064e41cc92b025",
            "class-contract",
        ),
        (
            "auth-service/src/test/java/com/example/auth/controller/TranscriptServiceBlankSecretTokenMintTest.java",
            "f05430b163c7ea9c619be048e648c9d76e180167",
            "class-contract",
        ),
    },
    "source-window-canonical-identity": {
        (
            "transcript-service/src/test/java/com/example/transcript/repository/TranscriptAssociationMigrationIntegrationTest.java",
            "26f3687e46bed0c65ae65bd100fb3edd80ae83ef",
            "latestMigrationBackfillsWindowIdentityAndAddsRestartSafeFinalizationState",
        ),
        (
            "transcript-service/src/test/java/com/example/transcript/directstt/DirectSttTranscriptIngestionServiceTest.java",
            "b9ada32fd2d7f58674814d89209abf47cd5c21a0",
            "createsDraftWithSourceWindowAndCanonicalSessionUuid",
        ),
        (
            "transcript-service/src/test/java/com/example/transcript/directstt/DirectSttTranscriptIngestionServiceTest.java",
            "b9ada32fd2d7f58674814d89209abf47cd5c21a0",
            "postFinalizationNewWindowIsPersistedAndStartsAnotherCycle",
        ),
    },
    "meeting-finish-and-outbox-are-atomic": {
        (
            "meeting-service/src/test/java/com/example/meeting/repository/MeetingRecordingFinishedOutboxPostgresIntegrationTest.java",
            "6edc0617d3e7b1e1980299189b2f66b260a36c83",
            "class-contract",
        )
    },
    "one-thin-ready-outbox-row-per-finalization-version": {
        (
            "transcript-service/src/test/java/com/example/transcript/service/TranscriptFinalizationServiceTest.java",
            "1631ceb36c4477765d47fe4d87bb7642aa3ce217",
            "duplicateOccurrenceCreatesOneThinOutboxEffect",
        )
    },
    "pt6m-pt1m-pt15m-boundaries-are-exact": {
        (
            "transcript-service/src/test/java/com/example/transcript/finalization/TranscriptFinalizationStateMachineTest.java",
            "af6ade91c566ec790f1363cc4749cc72105f8b29",
            "class-contract",
        )
    },
    "finalization-and-ready-outbox-are-one-transactional-operation": {
        (
            "transcript-service/src/test/java/com/example/transcript/finalization/TranscriptQuiescentFinalizationProcessorTest.java",
            "dd5ebf8dbc58a6d5ac42d0d8fcb6eab6ae65c915",
            "validSnapshotPersistsIntegrityRowAndReadyEventAtomically",
        )
    },
    "outbox-redelivery-does-not-duplicate-logical-effect": {
        (
            "meeting-service/src/test/java/com/example/meeting/events/MeetingEventOutboxPollerPostgresIntegrationTest.java",
            "a78d27567a2047f0e851e706c20ad62bcbd2a483",
            "redeliveryOfSameEventKey_appliesConsumerSideEffectOnlyOnce",
        ),
        (
            "transcript-service/src/test/java/com/example/transcript/events/TranscriptEventOutboxPollerTest.java",
            "4ab26951ac01f280cc5a74083f63af5a1e75d2bc",
            "successfulPublishUsesLeaseFenceBeforeMarkingPublished",
        ),
    },
}
EXPECTED_IMAGES = {
    "auth-service": {
        "service": "auth-service",
        "image": "ghcr.io/halildeu/platform-backend-auth-service",
        "digest": "sha256:dfd6dc43085f7ee362de2f34b038129ebe931e5c7708082e70d6b10346a66abd",
        "buildJobId": 88153460034,
        "artifactId": 8437706174,
        "artifactName": "Halildeu~platform-backend~G8TWF8.dockerbuild",
        "artifactUploadSha256": "a0785df09cf67a88f1d3ea48a598ad9ef7f53994473315fc91e27f013fc6d7de",
        "provenanceStatus": "pending-post-push-operator-preflight",
        "acceptanceEffect": "excluded",
    },
    "meeting-service": {
        "service": "meeting-service",
        "image": "ghcr.io/halildeu/platform-backend-meeting-service",
        "digest": "sha256:03378764b00ba1a08fd73fd18ddb3ed3bd7c2ecfaeb8903a9050c0830d6fd4a2",
        "buildJobId": 88153460058,
        "artifactId": 8437707554,
        "artifactName": "Halildeu~platform-backend~8BTZIT.dockerbuild",
        "artifactUploadSha256": "b85f5aafd665fc7da878c939b4b10d637b465fcdd75ecafda090b9f48f0df16f",
        "provenanceStatus": "pending-post-push-operator-preflight",
        "acceptanceEffect": "excluded",
    },
    "transcript-service": {
        "service": "transcript-service",
        "image": "ghcr.io/halildeu/platform-backend-transcript-service",
        "digest": "sha256:1c36a94701d203b1191ff8f43179db0a5378175b2b205799c09e2ad04053d238",
        "buildJobId": 88153460045,
        "artifactId": 8437707147,
        "artifactName": "Halildeu~platform-backend~UO37G8.dockerbuild",
        "artifactUploadSha256": "d124d4d50cd0e7543116a7c44adf1d8cf8486d46fb71c2406400b304e6ba3ab7",
        "provenanceStatus": "pending-post-push-operator-preflight",
        "acceptanceEffect": "excluded",
    },
    "audio-gateway-service": {
        "service": "audio-gateway-service",
        "image": "ghcr.io/halildeu/platform-backend-audio-gateway-service",
        "digest": "sha256:9c859cbbc3114ab8df5a3bde3305f86fa4de2b76305566333c21edf7617a4fac",
        "buildJobId": 88153460060,
        "artifactId": 8437709729,
        "artifactName": "Halildeu~platform-backend~OHV5SD.dockerbuild",
        "artifactUploadSha256": "c0d60c229b1f22e0487373e49ebb787bd90ddb96f3d22e8a3339db38c220bb36",
        "provenanceStatus": "pending-post-push-operator-preflight",
        "acceptanceEffect": "excluded",
    },
}
PROVIDER_ORDER = (("openai", "gpt-5.3-codex-spark"),)
PROVIDER_HISTORY_KEYS = {
    "status",
    "acceptanceEffect",
    "attestationBoundary",
    "requiredReceiptSchema",
    "requiredProviderOrder",
    "receipts",
}
RECEIPT_LEDGER_KEYS = {
    "provider",
    "requestedModel",
    "actualModel",
    "baseTipSha",
    "baseSha",
    "headSha",
    "scopeSha256",
    "verdict",
    "responseSha256",
    "apiUrl",
    "bodySha256",
    "createdAt",
}
RECEIPT_BODY_KEYS = {
    "schema",
    "provider",
    "requested_model",
    "actual_model",
    "base_tip_sha",
    "base_sha",
    "head_sha",
    "scope_sha256",
    "verdict",
    "response_sha256",
    "response",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SUBAGENT_MARKERS = (
    "subagent",
    "self-attestation",
    "self attestation",
    "owner-recorded provider summary",
    "simulated provider",
)


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
                "--disable",
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
                    "--hostname",
                    "github.com",
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


def github_text(url: str) -> str:
    prefix = f"{API_ROOT}/actions/jobs/"
    if not url.startswith(prefix) or not url.endswith("/logs"):
        fail(f"unexpected authenticated GitHub text URL: {url}")
    if shutil.which("gh") is None:
        fail("GitHub CLI with cross-repository Actions-read access is required")
    endpoint = url.removeprefix("https://api.github.com/")
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                endpoint,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        fail(f"GitHub Actions log fetch timed out: {url}")
    if result.returncode != 0 or not result.stdout:
        fail("GitHub Actions log fetch requires cross-repository Actions-read access")
    return result.stdout


def evidence_run(run: dict[str, Any]) -> dict[str, Any]:
    value = dict(run)
    value.pop("jobs", None)
    return value


def expected_evidence_run(expected: dict[str, Any]) -> dict[str, Any]:
    value = dict(expected)
    value.pop("jobs")
    value.pop("workflowBlobSha")
    return value


def require_run(key: str, run: dict[str, Any]) -> None:
    expected = EXPECTED_RUNS[key]
    if evidence_run(run) != expected_evidence_run(expected):
        fail(f"{key} evidence metadata is not the immutable expected run")
    remote_expected = {
        "id": expected["id"],
        "name": expected["name"],
        "path": expected["path"],
        "event": expected["event"],
        "run_attempt": expected["runAttempt"],
        "workflow_id": expected["workflowId"],
        "head_sha": expected["headSha"],
        "conclusion": "success",
    }
    live = github_json(f"{API_ROOT}/actions/runs/{expected['id']}")
    if {name: live.get(name) for name in remote_expected} != remote_expected:
        fail(f"{key} workflow/path/event/attempt metadata changed")


def require_jobs(key: str, pinned_jobs: list[dict[str, Any]]) -> None:
    expected_run = EXPECTED_RUNS[key]
    expected_jobs = {item["id"]: item for item in expected_run["jobs"]}
    if (
        not isinstance(pinned_jobs, list)
        or any(not isinstance(item, dict) for item in pinned_jobs)
        or len(pinned_jobs) != len(expected_jobs)
    ):
        fail(f"{key} must pin the exact job set")
    pinned_by_id = {item.get("id"): item for item in pinned_jobs}
    if len(pinned_by_id) != len(pinned_jobs) or pinned_by_id != expected_jobs:
        fail(f"{key} job id/name/step contract changed")

    run_id = expected_run["id"]
    payload = github_json(f"{API_ROOT}/actions/runs/{run_id}/jobs?per_page=100")
    jobs = {item.get("id"): item for item in payload.get("jobs", [])}
    for job_id, expected in expected_jobs.items():
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            fail(f"{key} lost exact job {job_id}")
        successful_steps = {
            step.get("name")
            for step in job.get("steps", [])
            if step.get("status") == "completed" and step.get("conclusion") == "success"
        }
        exact_remote = {
            "id": job_id,
            "name": expected["name"],
            "run_id": run_id,
            "run_attempt": expected_run["runAttempt"],
            "head_sha": expected_run["headSha"],
            "workflow_name": expected_run["name"],
            "status": "completed",
            "conclusion": "success",
        }
        if {name: job.get(name) for name in exact_remote} != exact_remote:
            fail(f"{key} exact job metadata changed for {job_id}")
        if expected["requiredStep"] not in successful_steps:
            fail(f"{key} job {job_id} lost required successful step")


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
    encoded = "".join(str(payload.get("content", "")).split())
    try:
        value = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        fail(f"cannot decode remote source blob {blob_sha}: {error}")
    cache[blob_sha] = value
    return value


def invariant_records(evidence: dict[str, Any]) -> dict[str, set[tuple[Any, ...]]]:
    result: dict[str, set[tuple[Any, ...]]] = {}
    for invariant in evidence.get("invariants", []):
        if not isinstance(invariant, dict) or set(invariant) != {
            "id",
            "status",
            "tests",
        }:
            fail("invariant evidence contains self-attested fields")
        if invariant.get("status") != "source-pinned-job-level-success":
            fail("invariant status escaped the bounded evidence level")
        tests = invariant.get("tests")
        if not isinstance(tests, list) or not tests:
            fail(f"invariant {invariant.get('id')} has no immutable test records")
        records: set[tuple[Any, ...]] = set()
        for test in tests:
            if not isinstance(test, dict) or set(test) != {"path", "blobSha", "method"}:
                fail("test evidence contains counts/assertions or unbound fields")
            records.add((test.get("path"), test.get("blobSha"), test.get("method")))
        if len(records) != len(tests):
            fail(f"invariant {invariant.get('id')} contains duplicate test evidence")
        invariant_id = invariant.get("id")
        if invariant_id in result:
            fail(f"invariant {invariant_id} is duplicated")
        result[invariant_id] = records
    return result


def require_source_blobs(evidence: dict[str, Any], tree: dict[str, str]) -> None:
    implementations = evidence.get("implementationContracts", [])
    if not isinstance(implementations, list) or any(
        not isinstance(item, dict) or set(item) != {"path", "blobSha"}
        for item in implementations
    ):
        fail("implementation evidence contains unbound assertion fields")
    implementation_records = {
        (item.get("path"), item.get("blobSha")) for item in implementations
    }
    if len(implementation_records) != len(implementations):
        fail("implementation evidence contains duplicate records")
    if implementation_records != EXPECTED_IMPLEMENTATIONS:
        fail("immutable implementation path/blob contract changed")

    invariants = invariant_records(evidence)
    if invariants != EXPECTED_INVARIANTS:
        fail("immutable invariant-to-test path/blob/method mapping changed")

    workflow_records = {
        (expected["path"], expected["workflowBlobSha"])
        for expected in EXPECTED_RUNS.values()
    }
    source_records = set(EXPECTED_IMPLEMENTATIONS)
    test_records = {
        (path, blob_sha)
        for tests in EXPECTED_INVARIANTS.values()
        for path, blob_sha, _method in tests
    }
    for path, blob_sha in workflow_records | source_records | test_records:
        if tree.get(path) != blob_sha:
            fail(f"reviewed backend path is not bound to expected blob: {path}")

    blobs: dict[str, str] = {}
    for tests in EXPECTED_INVARIANTS.values():
        for path, blob_sha, method in tests:
            content = blob_text(blob_sha, blobs)
            marker = Path(path).stem if method == "class-contract" else method
            if marker not in content:
                fail(
                    f"pinned test marker is missing from immutable blob: {path}#{method}"
                )


def require_image_provenance(backend: dict[str, Any]) -> None:
    images = backend.get("desiredImages")
    if (
        not isinstance(images, list)
        or any(not isinstance(item, dict) for item in images)
        or len(images) != len(EXPECTED_IMAGES)
    ):
        fail("desired images must contain the exact provenance set")
    by_service = {item.get("service"): item for item in images}
    if len(by_service) != len(images) or by_service != EXPECTED_IMAGES:
        fail("desired image digest/job/artifact provenance contract changed")

    for service, expected in EXPECTED_IMAGES.items():
        artifact_id = expected["artifactId"]
        artifact = github_json(f"{API_ROOT}/actions/artifacts/{artifact_id}")
        exact_artifact = {
            "id": artifact_id,
            "name": expected["artifactName"],
            "expired": False,
        }
        if {key: artifact.get(key) for key in exact_artifact} != exact_artifact:
            fail(f"{service} immutable build artifact metadata changed")
        workflow_run = artifact.get("workflow_run", {})
        if (
            workflow_run.get("id") != EXPECTED_RUNS["buildRun"]["id"]
            or workflow_run.get("head_sha") != ARTIFACT_COMMIT
        ):
            fail(f"{service} artifact is not bound to the immutable build run")

        log = github_text(f"{API_ROOT}/actions/jobs/{expected['buildJobId']}/logs")
        required_fragments = {
            expected["digest"],
            f"{expected['image']}@{expected['digest']}",
            f"SHA256 hash of uploaded artifact is {expected['artifactUploadSha256']}",
            f"Artifact successfully finalized ({artifact_id})",
        }
        if any(fragment not in log for fragment in required_fragments):
            fail(f"{service} digest is not bound to its immutable job/artifact log")


def response_sections(response: str) -> dict[str, str] | None:
    lines = response.splitlines()
    positions: dict[str, int] = {}
    for heading in ("P0", "P1", "P2"):
        matches = [index for index, line in enumerate(lines) if line.strip() == heading]
        if len(matches) != 1:
            return None
        positions[heading] = matches[0]
    if not positions["P0"] < positions["P1"] < positions["P2"]:
        return None
    terminal = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"VERDICT: (?:AGREE|REVISE)", line.strip())
    ]
    if len(terminal) != 1 or terminal[0] <= positions["P2"]:
        return None
    if any(line.strip() for line in lines[terminal[0] + 1 :]):
        return None
    return {
        "P0": "\n".join(lines[positions["P0"] + 1 : positions["P1"]]).strip(),
        "P1": "\n".join(lines[positions["P1"] + 1 : positions["P2"]]).strip(),
        "P2": "\n".join(lines[positions["P2"] + 1 : terminal[0]]).strip(),
        "verdict": lines[terminal[0]].strip().removeprefix("VERDICT: "),
    }


def require_receipt_body(
    ledger: dict[str, Any], expected_provider: str, expected_model: str
) -> str:
    api_url = ledger.get("apiUrl")
    expected_prefix = f"{API_ROOT}/issues/comments/"
    if (
        not isinstance(api_url, str)
        or not api_url.startswith(expected_prefix)
        or not api_url.removeprefix(expected_prefix).isdigit()
        or int(api_url.removeprefix(expected_prefix)) < 1
    ):
        fail("provider receipt ref escaped the backend GitHub comment boundary")
    comment = github_json(api_url)
    body = comment.get("body")
    if not isinstance(body, str):
        fail("provider receipt comment body is missing")
    if (
        comment.get("url") != api_url
        or comment.get("user", {}).get("login") != "Halildeu"
        or comment.get("author_association") != "OWNER"
        or comment.get("created_at") != ledger.get("createdAt")
        or comment.get("updated_at") != ledger.get("createdAt")
        or hashlib.sha256(body.encode("utf-8")).hexdigest() != ledger.get("bodySha256")
    ):
        fail("provider receipt remote metadata/body digest changed")
    try:
        receipt = json.loads(body)
    except json.JSONDecodeError as error:
        fail(f"provider receipt body is not structured JSON: {error}")
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_BODY_KEYS:
        fail("provider receipt must use the exact structured schema")

    expected_body = {
        "schema": "cross-ai-provider-evidence/v3",
        "provider": expected_provider,
        "requested_model": expected_model,
        "actual_model": expected_model,
        "base_tip_sha": REVIEW_BASE_COMMIT,
        "base_sha": REVIEW_BASE_COMMIT,
        "head_sha": REVIEWED_SOURCE_COMMIT,
        "scope_sha256": REVIEW_SCOPE_SHA256,
        "verdict": "AGREE",
        "response_sha256": ledger.get("responseSha256"),
    }
    if {key: receipt.get(key) for key in expected_body} != expected_body:
        fail("provider receipt model/scope/verdict binding changed")
    ledger_body = {
        "provider": receipt["provider"],
        "requestedModel": receipt["requested_model"],
        "actualModel": receipt["actual_model"],
        "baseTipSha": receipt["base_tip_sha"],
        "baseSha": receipt["base_sha"],
        "headSha": receipt["head_sha"],
        "scopeSha256": receipt["scope_sha256"],
        "verdict": receipt["verdict"],
        "responseSha256": receipt["response_sha256"],
        "apiUrl": api_url,
        "bodySha256": ledger["bodySha256"],
        "createdAt": ledger["createdAt"],
    }
    if ledger_body != ledger:
        fail("provider receipt ledger does not match the fetched full receipt")

    response = receipt.get("response")
    if (
        not isinstance(response, str)
        or not response
        or not SHA256_RE.fullmatch(str(receipt.get("response_sha256")))
        or hashlib.sha256(response.encode("utf-8")).hexdigest()
        != receipt.get("response_sha256")
    ):
        fail("provider full response digest is invalid")
    if any(marker in response.lower() for marker in SUBAGENT_MARKERS):
        fail("subagent/self-attestation cannot satisfy provider evidence")
    sections = response_sections(response)
    if (
        sections is None
        or sections["P0"] != "None"
        or sections["P1"] != "None"
        or sections["verdict"] != "AGREE"
    ):
        fail("provider response does not contain strict AGREE semantics")
    return str(comment.get("created_at"))


def require_provider_evidence(history: dict[str, Any], consensus: bool) -> None:
    if not isinstance(history, dict) or set(history) != PROVIDER_HISTORY_KEYS:
        fail("provider evidence must use the exact fail-closed schema")
    if history.get("acceptanceEffect") != "excluded-from-source-and-runtime-claims":
        fail("provider evidence escaped its bounded acceptance effect")
    if history.get("attestationBoundary") != "operator-captured-provider-unsigned":
        fail("provider evidence attestation boundary changed")
    if history.get("requiredReceiptSchema") != "cross-ai-provider-evidence/v3":
        fail("provider receipt schema changed")
    expected_order = [provider for provider, _model in PROVIDER_ORDER]
    if history.get("requiredProviderOrder") != expected_order:
        fail("provider order contract changed")
    receipts = history.get("receipts")
    if not isinstance(receipts, list):
        fail("provider receipts must be a list")
    if not receipts:
        if consensus or history.get("status") != "tracked-pending":
            fail("missing provider receipts must remain tracked-pending")
        return
    if len(receipts) != 1 or history.get("status") != "verified" or not consensus:
        fail("provider consensus requires exactly one primary Codex receipt")
    if any(
        not isinstance(item, dict) or set(item) != RECEIPT_LEDGER_KEYS
        for item in receipts
    ):
        fail("provider receipt ledger contains unbound/self-attested fields")
    refs = [item.get("apiUrl") for item in receipts]
    if len(set(refs)) != 1:
        fail("provider receipt refs must be unique")
    [
        require_receipt_body(receipt, provider, model)
        for receipt, (provider, model) in zip(receipts, PROVIDER_ORDER, strict=True)
    ]


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-remote-evidence.py EVIDENCE_JSON")
    evidence = load(sys.argv[1])
    if set(evidence) != EXPECTED_EVIDENCE_KEYS:
        fail("evidence root contains unknown/self-attested fields")
    if (
        evidence.get("schemaVersion") != "faz24-finalization-source-ci.v6"
        or evidence.get("accepted") is not True
        or evidence.get("acceptanceLevel") != "immutable-source-and-workflow-outcomes"
        or evidence.get("runtimeAcceptance") is not False
    ):
        fail("remote guard evidence schema/acceptance boundary changed")
    claims = evidence.get("acceptedClaims")
    if claims != EXPECTED_ACCEPTED_CLAIMS:
        fail("remote guard claim boundary changed")
    if claims["runtime"] is not False or claims["downstreamAnalysis"] is not False:
        fail("remote source guard cannot authorize runtime/downstream acceptance")

    backend = evidence.get("backend", {})
    if (
        backend.get("repository") != REPOSITORY
        or backend.get("repositoryVisibility") != "public"
        or backend.get("reviewedSourceCommit") != REVIEWED_SOURCE_COMMIT
        or backend.get("artifactCommit") != ARTIFACT_COMMIT
    ):
        fail("backend repository/commit boundary changed")

    repository = github_json(API_ROOT)
    if repository.get("full_name") != REPOSITORY:
        fail("backend repository identity changed")
    if (
        repository.get("visibility") != "public"
        or repository.get("private") is not False
    ):
        fail("backend public REST evidence boundary changed")

    pull = github_json(f"{API_ROOT}/pulls/{EXPECTED_PR}")
    if pull.get("merged") is not True:
        fail("backend PR #890 is not merged")
    if pull.get("head", {}).get("sha") != REVIEWED_SOURCE_COMMIT:
        fail("backend PR #890 reviewed head changed")
    if pull.get("base", {}).get("sha") != REVIEW_BASE_COMMIT:
        fail("backend PR #890 base commit changed")
    if pull.get("merge_commit_sha") != ARTIFACT_COMMIT:
        fail("backend PR #890 artifact commit changed")

    reviewed_commit = github_json(f"{API_ROOT}/git/commits/{REVIEWED_SOURCE_COMMIT}")
    artifact_commit = github_json(f"{API_ROOT}/git/commits/{ARTIFACT_COMMIT}")
    if reviewed_commit.get("tree", {}).get("sha") != artifact_commit.get(
        "tree", {}
    ).get("sha"):
        fail("reviewed source and artifact commits no longer have the same tree")

    for key in EXPECTED_RUNS:
        pinned = backend.get(key)
        if not isinstance(pinned, dict):
            fail(f"{key} evidence is missing")
        require_run(key, pinned)
        require_jobs(key, pinned.get("jobs"))

    tree = remote_tree(REVIEWED_SOURCE_COMMIT)
    require_source_blobs(evidence, tree)
    require_image_provenance(backend)
    require_provider_evidence(
        evidence.get("providerEvidence"), claims.get("providerConsensus") is True
    )
    if "reviewHistory" in evidence:
        fail("owner summary/self-attestation is not accepted provider evidence")

    print("PASS: Faz 24 evidence is bound to immutable GitHub source and build records")


if __name__ == "__main__":
    main()
