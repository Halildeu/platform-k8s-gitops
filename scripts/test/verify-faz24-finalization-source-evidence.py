#!/usr/bin/env python3
"""Validate the bounded immutable-source claims for Faz 24 finalization."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REVIEWED_SOURCE_COMMIT = "df812c57341fb9ea55a7662f3fd308fefd2a45dd"
ARTIFACT_COMMIT = "315f351a8ebf57d83f535617ccf8219749a2afc7"
REVIEW_BASE_COMMIT = "45451bb2562bb6814eb23ab084a9fd3ee0921d5f"
REVIEW_SCOPE_SHA256 = "9ab88f7e03558238915f713c66e2c37e01f00399353652e399f63c0ddc076775"
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
EXPECTED_INVARIANTS = {
    "auth-transcript-service-token-contract": {
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
    },
    "source-window-canonical-identity": {
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
    },
    "meeting-finish-and-outbox-are-atomic": {
        (
            "meeting-service/src/test/java/com/example/meeting/repository/MeetingRecordingFinishedOutboxPostgresIntegrationTest.java",
            "802ae62cbc01635b0c5400702ca2a0f003b00120",
            "class-contract",
        )
    },
    "one-thin-ready-outbox-row-per-finalization-version": {
        (
            "transcript-service/src/test/java/com/example/transcript/service/TranscriptFinalizationServiceTest.java",
            "2b2f6dcc109f6d864ca5fc35f291735f95556417",
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
            "6ad44937387405f5aa955047698e5b34d2bdd6a2",
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
PROVIDER_ORDER = (
    ("anthropic", "claude-opus-4-8"),
    ("minimax", "minimax/MiniMax-M3"),
    ("openai", "gpt-5.6-sol"),
)
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
    if history.get("requiredReceiptSchema") != "cross-ai-provider-evidence/v1":
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
    if len(receipts) != 3 or history.get("status") != "verified" or not consensus:
        fail("provider consensus requires exactly three structured receipts")
    if any(
        not isinstance(item, dict) or set(item) != RECEIPT_LEDGER_KEYS
        for item in receipts
    ):
        fail("provider receipt ledger contains unbound/self-attested fields")
    refs = [item.get("apiUrl") for item in receipts]
    if len(set(refs)) != 3:
        fail("provider receipt refs must be unique")
    created_at: list[str] = []
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
        created_at.append(timestamp)
    if not created_at[0] < created_at[1] < created_at[2]:
        fail("provider receipts must have strict Claude < MiniMax < Codex order")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-source-evidence.py EVIDENCE_JSON")
    evidence = load(sys.argv[1])
    if set(evidence) != EXPECTED_EVIDENCE_KEYS:
        fail("evidence root contains unknown/self-attested fields")
    if evidence.get("schemaVersion") != "faz24-finalization-source-ci.v5":
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
