#!/usr/bin/env python3
"""Validate the bounded immutable-source claims for Faz 24 finalization."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


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
    },
}
EXPECTED_JOBS = {
    "testRun": {
        (
            88152457058,
            "Maven full reactor build (all 12 modules)",
            "Verify full reactor (12 modules, no tests)",
            "success",
        ),
        (
            88152581595,
            "meeting-service unit + Testcontainers PG test (Faz 24",
            "Run meeting-service tests",
            "success",
        ),
        (
            88152581599,
            "transcript-service unit + Testcontainers PG test (Faz 24",
            "Run transcript-service tests",
            "success",
        ),
        (
            88152581600,
            "audio-gateway-service test (Faz 24",
            "Run audio-gateway-service tests",
            "success",
        ),
        (
            88152581610,
            "common-meeting-events contract test (Faz 24",
            "Run common-meeting-events tests",
            "success",
        ),
    },
    "authContractRun": {
        (
            88152457031,
            "auth-service transcript token mint evidence",
            "Run exact auth-service token mint tests",
            "success",
        )
    },
    "buildRun": {
        (88153460034, "Build + Push auth-service", "Build + Push image", "success"),
        (
            88153460058,
            "Build + Push meeting-service",
            "Build + Push image",
            "success",
        ),
        (
            88153460045,
            "Build + Push transcript-service",
            "Build + Push image",
            "success",
        ),
        (
            88153460060,
            "Build + Push audio-gateway-service",
            "Build + Push image",
            "success",
        ),
    },
}
EXPECTED_IMAGES = {
    (
        "auth-service",
        "ghcr.io/halildeu/platform-backend-auth-service",
        "sha256:dfd6dc43085f7ee362de2f34b038129ebe931e5c7708082e70d6b10346a66abd",
        88153460034,
        8437706174,
        "Halildeu~platform-backend~G8TWF8.dockerbuild",
        "a0785df09cf67a88f1d3ea48a598ad9ef7f53994473315fc91e27f013fc6d7de",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
    (
        "meeting-service",
        "ghcr.io/halildeu/platform-backend-meeting-service",
        "sha256:03378764b00ba1a08fd73fd18ddb3ed3bd7c2ecfaeb8903a9050c0830d6fd4a2",
        88153460058,
        8437707554,
        "Halildeu~platform-backend~8BTZIT.dockerbuild",
        "b85f5aafd665fc7da878c939b4b10d637b465fcdd75ecafda090b9f48f0df16f",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
    (
        "transcript-service",
        "ghcr.io/halildeu/platform-backend-transcript-service",
        "sha256:1c36a94701d203b1191ff8f43179db0a5378175b2b205799c09e2ad04053d238",
        88153460045,
        8437707147,
        "Halildeu~platform-backend~UO37G8.dockerbuild",
        "d124d4d50cd0e7543116a7c44adf1d8cf8486d46fb71c2406400b304e6ba3ab7",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
    (
        "audio-gateway-service",
        "ghcr.io/halildeu/platform-backend-audio-gateway-service",
        "sha256:9c859cbbc3114ab8df5a3bde3305f86fa4de2b76305566333c21edf7617a4fac",
        88153460060,
        8437709729,
        "Halildeu~platform-backend~OHV5SD.dockerbuild",
        "c0d60c229b1f22e0487373e49ebb787bd90ddb96f3d22e8a3339db38c220bb36",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
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
EXPECTED_PRODUCTION_GATES = {
    "test-vault-dr-keyset-and-redis-acl-separation",
    "github-protected-environment-approval",
    "production-secret-owner-and-named-legal-approval",
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


def job_tuples(run: dict[str, Any]) -> set[tuple[Any, Any, Any, Any]]:
    jobs = run.get("jobs", [])
    if not isinstance(jobs, list) or not jobs:
        fail(f"run {run.get('id')} has no pinned jobs")
    if any(
        not isinstance(item, dict)
        or set(item) != {"id", "name", "requiredStep", "conclusion"}
        for item in jobs
    ):
        fail(f"run {run.get('id')} job evidence contains unbound fields")
    values = {
        (
            item.get("id"),
            item.get("name"),
            item.get("requiredStep"),
            item.get("conclusion"),
        )
        for item in jobs
    }
    if len(values) != len(jobs):
        fail(f"run {run.get('id')} contains duplicate pinned jobs")
    return values


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
    for receipt, (provider, model) in zip(receipts, PROVIDER_ORDER, strict=True):
        expected = {
            "provider": provider,
            "requestedModel": model,
            "actualModel": model,
            "baseTipSha": REVIEW_BASE_COMMIT,
            "baseSha": REVIEW_BASE_COMMIT,
            "headSha": REVIEWED_SOURCE_COMMIT,
            "scopeSha256": REVIEW_SCOPE_SHA256,
            "verdict": "AGREE",
        }
        if {key: receipt.get(key) for key in expected} != expected:
            fail("provider receipt model/scope/verdict binding changed")
        for key in ("responseSha256", "bodySha256"):
            value = receipt.get(key)
            if not isinstance(value, str) or len(value) != 64 or value != value.lower():
                fail(f"provider receipt {key} is not a full SHA-256 digest")
            try:
                int(value, 16)
            except ValueError:
                fail(f"provider receipt {key} is not a full SHA-256 digest")
        api_url = receipt.get("apiUrl")
        expected_prefix = (
            "https://api.github.com/repos/Halildeu/platform-backend/issues/comments/"
        )
        if (
            not isinstance(api_url, str)
            or not api_url.startswith(expected_prefix)
            or not api_url.removeprefix(expected_prefix).isdigit()
            or int(api_url.removeprefix(expected_prefix)) < 1
        ):
            fail("provider receipt ref escaped the backend GitHub comment boundary")
        timestamp = receipt.get("createdAt")
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            fail("provider receipt createdAt is invalid")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-source-evidence.py EVIDENCE_JSON")
    evidence = load(sys.argv[1])
    if set(evidence) != EXPECTED_EVIDENCE_KEYS:
        fail("evidence root contains unknown/self-attested fields")
    if evidence.get("schemaVersion") != "faz24-finalization-source-ci.v6":
        fail("unexpected schemaVersion")
    if evidence.get("accepted") is not True:
        fail("bounded source/workflow evidence must be accepted")
    if evidence.get("acceptanceLevel") != "immutable-source-and-workflow-outcomes":
        fail("acceptanceLevel changed")
    if evidence.get("acceptedClaims") != EXPECTED_ACCEPTED_CLAIMS:
        fail("accepted claim boundary changed")
    if evidence.get("runtimeAcceptance") is not False:
        fail("source evidence must not claim runtime acceptance")

    boundary = evidence.get("rolloutBoundary", {})
    ownership = boundary.get("argoApplicationOwnership", {})
    workload_ownership = ownership.get("workloadApplication", {})
    if workload_ownership != {
        "name": "platform-test",
        "path": "kustomize/overlays/test",
        "owns": [
            "auth-service-transcript-service-secret",
            "auth-service",
            "audio-gateway",
            "meeting-service",
            "transcript-service",
        ],
        "sameApplicationWaveOrder": [
            "auth-service-transcript-service-secret:0",
            "auth-service:10",
            "meeting-service:19",
            "transcript-service:20",
        ],
    }:
        fail("platform-test workload ownership/wave contract changed")
    eso_ownership = ownership.get("externalSecretsApplication", {})
    if eso_ownership != {
        "name": "platform-eso-test",
        "path": "kustomize/overlays/test/eso",
        "owns": [
            "audio-gateway-secrets",
            "meeting-service-secrets",
            "transcript-service-secrets",
        ],
    }:
        fail("platform-eso-test ownership contract changed")
    if ownership.get("crossApplicationWaveOrderingClaimed") is not False:
        fail("resource waves cannot claim cross-Application ordering")
    if ownership.get("externalSecretsControllerScope") != (
        "cluster-controller-reconciles-ExternalSecret-resources-independent-of-"
        "Argo-Application-labels"
    ):
        fail("ExternalSecret controller ownership boundary changed")
    if boundary.get("downstreamAnalysisAcceptance") is not False:
        fail("backend rollout must not claim downstream analysis acceptance")
    consumer_gate = boundary.get("nextConsumerGate", {})
    if (
        consumer_gate.get("status") != "tracked-open"
        or consumer_gate.get("issue")
        != "https://github.com/Halildeu/platform-ai/issues/263"
    ):
        fail("downstream analysis must remain tracked by platform-ai#263")
    if not consumer_gate.get("requiredProof"):
        fail("downstream consumer gate must state required runtime proof")

    redis_boundary = boundary.get("testRedisCredential", {})
    if redis_boundary.get("mode") != "shared-default-user-compatibility":
        fail("test Redis credential boundary mode changed")
    if redis_boundary.get("sharedSourcePath") != ("kv/platform/audio-gateway-service"):
        fail("shared test Redis source path changed")
    if set(redis_boundary.get("sharedSourceTargets", [])) != {
        "audio-gateway-secrets",
        "transcript-service-secrets",
    }:
        fail("shared test Redis targets changed")
    if redis_boundary.get("ownedMeetingSourcePath") != "kv/platform/meeting-service":
        fail("meeting-service owned Redis source path changed")
    if redis_boundary.get("ownedMeetingTarget") != "meeting-service-secrets":
        fail("meeting-service owned Redis target changed")
    if redis_boundary.get("migrationIssue") != (
        "https://github.com/Halildeu/platform-k8s-gitops/issues/2614"
    ):
        fail("test Redis ACL migration must remain tracked by #2614")
    if redis_boundary.get("productionPromotionAllowed") is not False:
        fail("shared test Redis credential cannot authorize production")

    preflight = boundary.get("postPushTestPreflight", {})
    if preflight.get("status") != "pending":
        fail("source evidence must not claim post-push preflight")
    if preflight.get("acceptanceEffect") != "blocks-test-deploy-not-source-review":
        fail("post-push preflight acceptance effect changed")
    expected_preflight_checks = {
        "fresh namespace and node pod headroom supports three dependency-ordered surge pods plus the quota-aware audio replacement",
        "auth issuer Vault property exists and current audio, meeting and transcript ExternalSecrets are healthy before main merge",
        "auth, audio, meeting and transcript ExternalSecrets are Ready before workload availability acceptance",
        "meeting-service credential authenticates to live test Redis with redacted proof",
        "all four immutable digests are pullable and match the reviewed build run",
    }
    if set(preflight.get("requiredChecks", [])) != expected_preflight_checks:
        fail("post-push test preflight contract changed")

    backend = evidence.get("backend", {})
    if set(backend) != {
        "repository",
        "repositoryVisibility",
        "reviewedSourceCommit",
        "artifactCommit",
        "pullRequests",
        "testRun",
        "authContractRun",
        "buildRun",
        "desiredImages",
    }:
        fail("backend evidence contains unbound/self-attested fields")
    if backend.get("repository") != "Halildeu/platform-backend":
        fail("backend repository changed")
    if backend.get("repositoryVisibility") != "public":
        fail("public remote evidence access boundary changed")
    if backend.get("reviewedSourceCommit") != REVIEWED_SOURCE_COMMIT:
        fail("reviewed source commit changed")
    if backend.get("artifactCommit") != ARTIFACT_COMMIT:
        fail("artifact commit changed")
    if backend.get("pullRequests") != [
        "https://github.com/Halildeu/platform-backend/pull/865",
        "https://github.com/Halildeu/platform-backend/pull/866",
        "https://github.com/Halildeu/platform-backend/pull/872",
        "https://github.com/Halildeu/platform-backend/pull/888",
        "https://github.com/Halildeu/platform-backend/pull/890",
    ]:
        fail("backend pull-request lineage changed")
    for key, expected in EXPECTED_RUNS.items():
        actual = dict(backend.get(key, {}))
        actual.pop("jobs", None)
        if actual != expected:
            fail(f"{key} metadata changed")
        if job_tuples(backend.get(key, {})) != EXPECTED_JOBS[key]:
            fail(f"{key} exact job contract changed")

    image_tuples = {
        (
            item.get("service"),
            item.get("image"),
            item.get("digest"),
            item.get("buildJobId"),
            item.get("artifactId"),
            item.get("artifactName"),
            item.get("artifactUploadSha256"),
            item.get("provenanceStatus"),
            item.get("acceptanceEffect"),
        )
        for item in backend.get("desiredImages", [])
    }
    if any(
        not isinstance(item, dict)
        or set(item)
        != {
            "service",
            "image",
            "digest",
            "buildJobId",
            "artifactId",
            "artifactName",
            "artifactUploadSha256",
            "provenanceStatus",
            "acceptanceEffect",
        }
        for item in backend.get("desiredImages", [])
    ):
        fail("desired image evidence contains unbound provenance fields")
    if len(image_tuples) != len(backend.get("desiredImages", [])):
        fail("desired image evidence contains duplicate provenance records")
    if image_tuples != EXPECTED_IMAGES:
        fail("desired image/operator provenance tuple changed")

    implementations = evidence.get("implementationContracts", [])
    if any(
        not isinstance(item, dict) or set(item) != {"path", "blobSha"}
        for item in implementations
    ):
        fail("implementation contracts may contain only remotely verifiable fields")
    if {(item.get("path"), item.get("blobSha")) for item in implementations} != (
        EXPECTED_IMPLEMENTATIONS
    ):
        fail("immutable implementation path/blob set changed")

    invariants = evidence.get("invariants", [])
    if not isinstance(invariants, list):
        fail("invariants must be a list")
    actual_invariants: dict[Any, set[tuple[Any, Any, Any]]] = {}
    for invariant in invariants:
        if not isinstance(invariant, dict) or set(invariant) != {
            "id",
            "status",
            "tests",
        }:
            fail("invariant evidence contains counts/assertions or unbound fields")
        if invariant.get("status") != "source-pinned-job-level-success":
            fail("invariants must state their bounded evidence level")
        tests = invariant.get("tests", [])
        if not isinstance(tests, list) or not tests:
            fail(f"invariant {invariant.get('id')} has no source-pinned test")
        records: set[tuple[Any, Any, Any]] = set()
        for test in tests:
            if not isinstance(test, dict) or set(test) != {"path", "blobSha", "method"}:
                fail("test evidence contains counts/assertions or unbound fields")
            records.add((test.get("path"), test.get("blobSha"), test.get("method")))
        if len(records) != len(tests):
            fail(f"invariant {invariant.get('id')} contains duplicate test evidence")
        invariant_id = invariant.get("id")
        if invariant_id in actual_invariants:
            fail(f"invariant {invariant_id} is duplicated")
        actual_invariants[invariant_id] = records
    if actual_invariants != EXPECTED_INVARIANTS:
        fail("immutable invariant-to-test path/blob/method mapping changed")

    if "reviewHistory" in evidence:
        fail("owner summary/self-attestation is not accepted provider evidence")
    require_provider_evidence(
        evidence.get("providerEvidence"),
        evidence.get("acceptedClaims", {}).get("providerConsensus") is True,
    )

    gates = evidence.get("productionGates", [])
    if {item.get("id") for item in gates} != EXPECTED_PRODUCTION_GATES:
        fail("production gate set changed")
    if any(item.get("blocksProductionPromotion") is not True for item in gates):
        fail("every production gate must block production promotion")
    if any(item.get("blocksTestRollout") is not False for item in gates):
        fail("production gates must not falsely block the safe test rollout")
    vault_gate = next(
        item
        for item in gates
        if item.get("id") == "test-vault-dr-keyset-and-redis-acl-separation"
    )
    if vault_gate.get("status") != "tracked-open" or vault_gate.get("issue") != (
        "https://github.com/Halildeu/platform-k8s-gitops/issues/2614"
    ):
        fail("Vault/Redis production gate must remain tracked by #2614")
    if any(
        item.get("status") != "human-only"
        for item in gates
        if item.get("id") != "test-vault-dr-keyset-and-redis-acl-separation"
    ):
        fail("protected environment and owner/legal gates must remain human-only")

    print("PASS: Faz 24 bounded immutable source/workflow evidence")


if __name__ == "__main__":
    main()
