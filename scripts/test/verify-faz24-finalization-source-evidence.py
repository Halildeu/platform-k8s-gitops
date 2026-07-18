#!/usr/bin/env python3
"""Validate the bounded immutable-source claims for Faz 24 finalization."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REVIEWED_SOURCE_COMMIT = "df812c57341fb9ea55a7662f3fd308fefd2a45dd"
ARTIFACT_COMMIT = "315f351a8ebf57d83f535617ccf8219749a2afc7"
EXPECTED_ACCEPTED_CLAIMS = {
    "reviewedSourceTree": True,
    "workflowRunOutcomes": True,
    "desiredImageProvenance": False,
    "providerConsensus": False,
    "runtime": False,
    "downstreamAnalysis": False,
}
EXPECTED_RUNS = {
    "testRun": {
        "id": 29632738608,
        "name": "CI - Maven Build Check",
        "path": ".github/workflows/ci-mvn-check.yml",
        "event": "pull_request",
        "runAttempt": 1,
        "workflowId": 265979888,
        "headSha": REVIEWED_SOURCE_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29632738608",
    },
    "authContractRun": {
        "id": 29632738600,
        "name": "CI - Auth Token Evidence",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
        "runAttempt": 1,
        "workflowId": 315554443,
        "headSha": REVIEWED_SOURCE_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29632738600",
    },
    "buildRun": {
        "id": 29633149322,
        "name": "CI - Image Build + GHCR Push",
        "path": ".github/workflows/ci-image-push.yml",
        "event": "push",
        "runAttempt": 1,
        "workflowId": 265996858,
        "headSha": ARTIFACT_COMMIT,
        "conclusion": "success",
        "url": "https://github.com/Halildeu/platform-backend/actions/runs/29633149322",
    },
}
EXPECTED_JOBS = {
    "testRun": {
        (
            88049635369,
            "meeting-service unit + Testcontainers PG test (Faz 24",
            "Run meeting-service tests",
            "success",
        ),
        (
            88049635387,
            "transcript-service unit + Testcontainers PG test (Faz 24",
            "Run transcript-service tests",
            "success",
        ),
        (
            88049635354,
            "common-meeting-events contract test (Faz 24",
            "Run common-meeting-events tests",
            "success",
        ),
    },
    "authContractRun": {
        (
            88049496472,
            "auth-service transcript token mint evidence",
            "Run exact auth-service token mint tests",
            "success",
        )
    },
    "buildRun": {
        (88050625953, "Build + Push auth-service", "Build + Push image", "success"),
        (
            88050626007,
            "Build + Push meeting-service",
            "Build + Push image",
            "success",
        ),
        (
            88050625972,
            "Build + Push transcript-service",
            "Build + Push image",
            "success",
        ),
    },
}
EXPECTED_IMAGES = {
    (
        "auth-service",
        "ghcr.io/halildeu/platform-backend-auth-service",
        "sha256:a48e73bb6d89e56ae427103a54ed5358f29b04fd171771781655dae486397f03",
        88050625953,
        8426177299,
        "Halildeu~platform-backend~TSPWGN.dockerbuild",
        "9b27e5ded54520195c716a110c7320f259a87580fbd21593e61374f867922aa8",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
    (
        "meeting-service",
        "ghcr.io/halildeu/platform-backend-meeting-service",
        "sha256:1da371209763f36119a05f87e5ed78a8439afc9427c03cf41f9e1aaa3d09d682",
        88050626007,
        8426172575,
        "Halildeu~platform-backend~U1O1WU.dockerbuild",
        "f2d066754394f4b753e79a1c34fd5e331441ecd575c6dab556f9d4179d0cec6d",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
    (
        "transcript-service",
        "ghcr.io/halildeu/platform-backend-transcript-service",
        "sha256:22f4df7c042a2c8b19dd0e8f55111ca48057a6258e76d2bdd99c00597ec92be7",
        88050625972,
        8426182932,
        "Halildeu~platform-backend~VV4NZC.dockerbuild",
        "92d5c0b045230f79c79d1ec8ab5c87507e7f4b0bbb84c31cf26c7ed01dc9ab70",
        "pending-post-push-operator-preflight",
        "excluded",
    ),
}
EXPECTED_INVARIANTS = {
    "auth-transcript-service-token-contract",
    "source-window-canonical-identity",
    "meeting-finish-and-outbox-are-atomic",
    "one-thin-ready-outbox-row-per-finalization-version",
    "pt6m-pt1m-pt15m-boundaries-are-exact",
    "finalization-and-ready-outbox-are-one-transactional-operation",
    "outbox-redelivery-does-not-duplicate-logical-effect",
}
EXPECTED_IMPLEMENTATIONS = {
    (
        "transcript-service/src/main/java/com/example/transcript/finalization/TranscriptQuiescentFinalizationProcessor.java",
        "4d1a4169daae145057f46c6831e8f6dffbbc0a75",
    ),
    (
        "transcript-service/src/main/java/com/example/transcript/service/TranscriptFinalizationService.java",
        "e32ff2631ebd8ad7ddc9135e6a143572753fbd3b",
    ),
}
EXPECTED_TESTS = {
    (
        "auth-service/src/test/java/com/example/auth/controller/MeetingAiServiceTokenMintTest.java",
        "12881b068025d2ceced8a12fa51e86eeaf94db32",
        "class-contract",
    ),
    (
        "auth-service/src/test/java/com/example/auth/controller/TranscriptServiceBlankSecretTokenMintTest.java",
        "f05430b163c7ea9c619be048e648c9d76e180167",
        "class-contract",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/repository/TranscriptAssociationMigrationIntegrationTest.java",
        "937003493495bf69176615d3f8d65ad0bc9537b3",
        "latestMigrationBackfillsWindowIdentityAndAddsRestartSafeFinalizationState",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/directstt/DirectSttTranscriptIngestionServiceTest.java",
        "fd01287fb0502d2654b09f9458c2b752fdab1535",
        "createsDraftWithSourceWindowAndCanonicalSessionUuid",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/directstt/DirectSttTranscriptIngestionServiceTest.java",
        "fd01287fb0502d2654b09f9458c2b752fdab1535",
        "postFinalizationNewWindowIsPersistedAndStartsAnotherCycle",
    ),
    (
        "meeting-service/src/test/java/com/example/meeting/repository/MeetingRecordingFinishedOutboxPostgresIntegrationTest.java",
        "802ae62cbc01635b0c5400702ca2a0f003b00120",
        "class-contract",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/service/TranscriptFinalizationServiceTest.java",
        "2b2f6dcc109f6d864ca5fc35f291735f95556417",
        "duplicateOccurrenceCreatesOneThinOutboxEffect",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/finalization/TranscriptFinalizationStateMachineTest.java",
        "af6ade91c566ec790f1363cc4749cc72105f8b29",
        "class-contract",
    ),
    (
        "transcript-service/src/test/java/com/example/transcript/finalization/TranscriptQuiescentFinalizationProcessorTest.java",
        "6ad44937387405f5aa955047698e5b34d2bdd6a2",
        "validSnapshotPersistsIntegrityRowAndReadyEventAtomically",
    ),
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
}
EXPECTED_PRODUCTION_GATES = {
    "test-vault-dr-keyset-and-redis-acl-separation",
    "github-protected-environment-approval",
    "production-secret-owner-and-named-legal-approval",
}
EXPECTED_REVIEW_RECEIPT = {
    "apiUrl": "https://api.github.com/repos/Halildeu/platform-backend/issues/comments/5010138585",
    "commentId": 5010138585,
    "nodeId": "IC_kwDOSLwN9M8AAAABKqCl2Q",
    "author": "Halildeu",
    "authorAssociation": "OWNER",
    "createdAt": "2026-07-18T05:53:13Z",
    "updatedAt": "2026-07-18T05:53:13Z",
    "bodySha256": "0c954b0d61936ca08c67143214a05807a31f9a842738ffc530d236884788b901",
    "remoteVerificationRequired": True,
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
    if not jobs:
        fail(f"run {run.get('id')} has no pinned jobs")
    return {
        (
            item.get("id"),
            item.get("name"),
            item.get("requiredStep"),
            item.get("conclusion"),
        )
        for item in jobs
    }


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-source-evidence.py EVIDENCE_JSON")
    evidence = load(sys.argv[1])
    if evidence.get("schemaVersion") != "faz24-finalization-source-ci.v4":
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
        "fresh namespace and node pod headroom supports three dependency-ordered surge pods",
        "auth issuer Vault property exists and current meeting and transcript ExternalSecrets are healthy before main merge",
        "auth, meeting and transcript ExternalSecrets are Ready before workload availability acceptance",
        "meeting-service credential authenticates to live test Redis with redacted proof",
        "all three immutable digests are pullable and match the reviewed build run",
    }
    if set(preflight.get("requiredChecks", [])) != expected_preflight_checks:
        fail("post-push test preflight contract changed")

    backend = evidence.get("backend", {})
    if backend.get("repository") != "Halildeu/platform-backend":
        fail("backend repository changed")
    if backend.get("repositoryVisibility") != "public":
        fail("public remote evidence access boundary changed")
    if backend.get("reviewedSourceCommit") != REVIEWED_SOURCE_COMMIT:
        fail("reviewed source commit changed")
    if backend.get("artifactCommit") != ARTIFACT_COMMIT:
        fail("artifact commit changed")
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
    if image_tuples != EXPECTED_IMAGES:
        fail("desired image/operator provenance tuple changed")

    implementations = evidence.get("implementationContracts", [])
    if any(set(item) != {"path", "blobSha"} for item in implementations):
        fail("implementation contracts may contain only remotely verifiable fields")
    if {(item.get("path"), item.get("blobSha")) for item in implementations} != (
        EXPECTED_IMPLEMENTATIONS
    ):
        fail("immutable implementation path/blob set changed")

    invariants = evidence.get("invariants", [])
    if {item.get("id") for item in invariants} != EXPECTED_INVARIANTS:
        fail("required invariant set changed")
    if any(
        item.get("status") != "source-pinned-job-level-success" for item in invariants
    ):
        fail("invariants must state their bounded evidence level")
    actual_tests: set[tuple[str, str, str]] = set()
    for invariant in invariants:
        tests = invariant.get("tests", [])
        if not tests:
            fail(f"invariant {invariant.get('id')} has no source-pinned test")
        for test in tests:
            if set(test) != {"path", "blobSha", "method"}:
                fail("test evidence may contain only remotely verifiable fields")
            actual_tests.add(
                (test.get("path"), test.get("blobSha"), test.get("method"))
            )
    if actual_tests != EXPECTED_TESTS:
        fail("immutable test path/blob/method set changed")

    history = evidence.get("reviewHistory", {})
    if history.get("headSha") != REVIEWED_SOURCE_COMMIT:
        fail("review history is not bound to the reviewed source commit")
    if history.get("attestationLevel") != "owner-recorded-provider-summary":
        fail("review history attestation level changed")
    if history.get("independentRemoteAttestations") is not False:
        fail("owner summary must not claim independent provider attestations")
    if history.get("acceptanceEffect") != "excluded":
        fail("owner review summary must remain excluded from acceptance")
    if history.get("remoteReceipt") != EXPECTED_REVIEW_RECEIPT:
        fail("remote owner-summary receipt changed")

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
