from __future__ import annotations

import copy
import contextlib
import datetime as dt
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/faz24"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import collect_transcript_ready_pre_enable_evidence as collector  # noqa: E402
import verify_transcript_ready_pre_enable_evidence as verifier  # noqa: E402
from transcript_ready_pre_enable_contract import (  # noqa: E402
    binding_set_sha256_from_sha1s,
    file_sha256,
)


GITOPS_COMMIT = "a" * 40
BACKEND_COMMIT = "b" * 40
AI_COMMIT = "c" * 40
IMAGE_DIGEST = "sha256:" + "1" * 64
STARTUP_SHA = "2" * 64
EVENT_CONTRACT_SHA = "3" * 64
BINDING_SET_SHA = binding_set_sha256_from_sha1s(("4" * 40, "5" * 40))
EMPTY_SET_SHA = verifier.EMPTY_SET_SHA256


def empty_outbox_statuses() -> dict:
    return {
        "pending": 0,
        "claimedActive": 0,
        "claimedStale": 0,
        "dead": 0,
        "published": 0,
        "total": 0,
    }


def artifact_evidence(evidence_type: str) -> dict:
    if evidence_type == "EVENT_CONTRACT":
        return {
            "meetingEventSchema": "meeting.event.v1",
            "readyEventType": "meeting.transcript.ready",
            "analysisRunIdEmission": "non-null-v1",
            "finalizationAnalysisRunId": "uuid-not-null-event-bound",
        }
    if evidence_type == "BACKFILL":
        return {
            "action": "NOOP_ZERO_INVENTORY",
            "beforeNullFinalizationCount": 0,
            "inventorySetSha256": EMPTY_SET_SHA,
            "processedCount": 0,
            "failedCount": 0,
            "afterNullFinalizationCount": 0,
            "resultSetSha256": EMPTY_SET_SHA,
            "analysisRunIdUuid": True,
            "analysisRunIdNotNull": True,
            "occurrenceBound": True,
        }
    if evidence_type == "OUTBOX_REMEDIATION":
        return {
            "action": "NOOP_ZERO_INVENTORY",
            "beforeLegacyByStatus": empty_outbox_statuses(),
            "beforeMalformedReadyCount": 0,
            "inventorySetSha256": EMPTY_SET_SHA,
            "processedCount": 0,
            "purgedCount": 0,
            "republishedCount": 0,
            "failedCount": 0,
            "afterLegacyByStatus": empty_outbox_statuses(),
            "afterMalformedReadyCount": 0,
            "resultSetSha256": EMPTY_SET_SHA,
        }
    if evidence_type == "REDIS_REMEDIATION":
        return {
            "action": "NOOP_ZERO_INVENTORY",
            "beforeLegacyReadyV1Count": 0,
            "beforeMalformedReadyCount": 0,
            "inventorySetSha256": EMPTY_SET_SHA,
            "dlqReceiptSetSha256": EMPTY_SET_SHA,
            "dlqAcceptedCount": 0,
            "xackCount": 0,
            "xdelCount": 0,
            "failedCount": 0,
            "afterLegacyReadyV1Count": 0,
            "afterMalformedReadyCount": 0,
            "afterStreamLength": 3,
            "afterScannedCount": 3,
            "afterCompleteScan": True,
            "afterClassificationDigestSha1": "9" * 40,
            "resultSetSha256": EMPTY_SET_SHA,
        }
    raise AssertionError(f"unsupported evidence type: {evidence_type}")


def policy() -> dict:
    value = json.loads(
        (ROOT / "config/faz24-transcript-ready-pre-enable-policy.v1.json").read_text(
            encoding="utf-8"
        )
    )
    value["producerCapabilities"] = [
        {
            "transcriptImageDigest": IMAGE_DIGEST,
            "backendCommit": BACKEND_COMMIT,
            "eventContractSha256": EVENT_CONTRACT_SHA,
            "gateContractSha256": collector.contract_sha256(
                "transcript_service", "Assert-TranscriptReadyPreEnablePermit"
            ),
            "backfillEvidenceSha256": "6" * 64,
            "outboxRemediationEvidenceSha256": "7" * 64,
            "redisRemediationEvidenceSha256": "8" * 64,
            "analysisRunIdEmission": "non-null-v1",
            "finalizationAnalysisRunId": "uuid-not-null-event-bound",
        }
    ]
    value["hostStartupGuards"] = [
        {
            "platformAiCommit": AI_COMMIT,
            "startupScriptSha256": STARTUP_SHA,
            "permitRequired": True,
        }
    ]
    value["currentBoundary"] = {"enableAuthorized": True, "reason": "test-only"}
    return value


def zero_counts() -> dict:
    return {
        "capturedAt": "2026-07-18T12:00:00Z",
        "finalizationNullAnalysisRunId": 0,
        "legacyOutbox": {
            "pending": 0,
            "claimedActive": 0,
            "claimedStale": 0,
            "dead": 0,
            "published": 0,
            "total": 0,
        },
        "malformedReadyOutbox": 0,
        "compatibleReadyOutbox": 2,
        "compatibleBindingSetSha256": BINDING_SET_SHA,
        "readyOutboxTotal": 2,
    }


def schema_ready() -> dict:
    return {
        "databaseName": "transcript",
        "serverAddress": "172.19.0.6",
        "serverPort": 5432,
        "finalizationTablePresent": True,
        "outboxTablePresent": True,
        "analysisRunIdColumnPresent": True,
        "analysisRunIdNotNull": True,
        "analysisRunIdUuid": True,
        "finalizationOccurrenceColumnsPresent": True,
        "outboxRequiredColumnsPresent": True,
    }


def evidence(policy_path: Path, generated_at: str) -> dict:
    counts = zero_counts()
    return {
        "schemaVersion": "faz24.transcriptReadyPreEnableEvidence.v1",
        "generatedAt": generated_at,
        "issue": "platform-k8s-gitops#2610",
        "status": "candidate",
        "source": {
            "gitopsCommit": GITOPS_COMMIT,
            "policySha256": file_sha256(policy_path),
            "queryContractSha256": collector.contract_sha256(
                "transcript_service", "Assert-TranscriptReadyPreEnablePermit"
            ),
            "collectionStartedAt": "2026-07-18T11:59:55Z",
            "collectionFinishedAt": "2026-07-18T12:00:00Z",
        },
        "environment": policy()["environment"],
        "live": {
            "transcriptPod": {
                "collected": True,
                "observedAt": "2026-07-18T11:59:56Z",
                "name": "transcript-service-abc",
                "uid": "11111111-1111-1111-1111-111111111111",
                "ready": True,
                "restartCount": 0,
                "imageDigest": IMAGE_DIGEST,
            },
            "postgresBefore": {
                "collected": True,
                "observedAt": "2026-07-18T11:59:57Z",
                "schema": schema_ready(),
                "counts": copy.deepcopy(counts),
            },
            "redis": {
                "collected": True,
                "observedAt": "2026-07-18T11:59:58Z",
                "host": "172.19.0.250",
                "port": 6379,
                "tls": False,
                "scriptSha256": collector.sha256_bytes(
                    collector.REDIS_LUA.encode("utf-8")
                ),
                "length": 3,
                "firstId": "1-0",
                "lastId": "3-0",
                "maxDeletedEntryId": "0-0",
                "scanned": 3,
                "complete": True,
                "truncated": False,
                "atomicMetadataStable": True,
                "legacyReadyV1": 0,
                "malformedReady": 0,
                "compatibleReady": 2,
                "compatibleBindingSetSha256": BINDING_SET_SHA,
                "otherEvents": 1,
                "classificationDigestSha1": "4" * 40,
                "group": {
                    "exists": False,
                    "pending": 0,
                    "consumers": 0,
                    "lastDeliveredId": "",
                    "entriesRead": -1,
                    "lag": -1,
                },
            },
            "postgresAfter": {
                "collected": True,
                "observedAt": "2026-07-18T11:59:59Z",
                "schema": schema_ready(),
                "counts": copy.deepcopy(counts),
            },
            "gpuHost": {
                "collected": True,
                "observedAt": "2026-07-18T12:00:00Z",
                "computerName": "SRB-AIDENETIMPC",
                "platformAiCommit": AI_COMMIT,
                "repoHeadCommit": AI_COMMIT,
                "deploymentStateMatch": True,
                "startupScriptSha256": STARTUP_SHA,
                "startupGateMarkerPresent": True,
                "runtimeConfigState": "absent",
                "runtimeConfigMatchCount": 0,
                "machineEnvironmentState": "unset",
                "healthReachable": True,
                "healthConsumerPresent": True,
                "healthEnabled": False,
                "healthStatus": "disabled",
                "healthWorkerRunning": False,
                "healthRedisGroupReady": False,
                "probeSha256": collector.sha256_bytes(
                    collector.HOST_POWERSHELL.replace(
                        "__STARTUP_GATE_MARKER__",
                        "Assert-TranscriptReadyPreEnablePermit",
                    ).encode("utf-8")
                ),
            },
        },
        "collectionFailures": [],
        "boundary": {
            "readOnly": True,
            "consumerEnableAttempted": False,
            "workloadMutationAttempted": False,
            "secretValuesIncluded": False,
            "customerContentIncluded": False,
            "enableAuthorized": False,
        },
    }


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.artifact_root = Path(self.directory.name)
        self.path = self.artifact_root / "policy.json"
        self.policy = policy()
        capability = self.policy["producerCapabilities"][0]
        self.claim_path = self.artifact_root / "claim.json"
        self.claim_document = {
            "schemaVersion": "faz24.transcriptReadyEvidenceIssueClaim.v1",
            "gateIssue": "platform-k8s-gitops#2610",
            "issue": "Halildeu/platform-backend#2610",
            "source": "github-project-v2",
            "environment": self.policy["environment"],
            "boardStatusAtClaim": "In Progress",
            "claimedAt": "2026-07-18T11:50:00Z",
            "claimSessionSha256": "e" * 64,
        }
        self.claim_path.write_text(
            json.dumps(self.claim_document, sort_keys=True), encoding="utf-8"
        )
        self.artifact_documents: dict[str, dict] = {}
        self.artifact_paths: dict[str, Path] = {}
        self.artifact_digest_fields: dict[str, str] = {}
        for path_field, digest_field, evidence_type in (
            ("eventContractEvidencePath", "eventContractSha256", "EVENT_CONTRACT"),
            ("backfillEvidencePath", "backfillEvidenceSha256", "BACKFILL"),
            (
                "outboxRemediationEvidencePath",
                "outboxRemediationEvidenceSha256",
                "OUTBOX_REMEDIATION",
            ),
            (
                "redisRemediationEvidencePath",
                "redisRemediationEvidenceSha256",
                "REDIS_REMEDIATION",
            ),
        ):
            artifact = self.artifact_root / f"{evidence_type.lower()}.json"
            document = {
                "schemaVersion": "faz24.transcriptReadyRemediationEvidence.v1",
                "issue": "platform-k8s-gitops#2610",
                "evidenceType": evidence_type,
                "status": "accepted",
                "environment": self.policy["environment"],
                "backendCommit": BACKEND_COMMIT,
                "transcriptImageDigest": IMAGE_DIGEST,
                "gateContractSha256": capability["gateContractSha256"],
                "evidenceIssue": "Halildeu/platform-backend#2610",
                "evidenceIssueClaimPath": self.claim_path.name,
                "evidenceIssueClaimSha256": file_sha256(self.claim_path),
                "completedAt": "2026-07-18T11:55:00Z",
                "evidence": artifact_evidence(evidence_type),
            }
            artifact.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
            capability[path_field] = artifact.name
            capability[digest_field] = file_sha256(artifact)
            self.artifact_documents[evidence_type] = document
            self.artifact_paths[evidence_type] = artifact
            self.artifact_digest_fields[evidence_type] = digest_field
        self.path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.now = dt.datetime(2026, 7, 18, 12, 5, tzinfo=dt.timezone.utc)
        self.evidence = evidence(self.path, "2026-07-18T12:00:00Z")

    def write_artifact(self, evidence_type: str, document: dict) -> None:
        artifact = self.artifact_paths[evidence_type]
        artifact.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        digest_field = self.artifact_digest_fields[evidence_type]
        self.policy["producerCapabilities"][0][digest_field] = file_sha256(artifact)

    def checks(self, value: dict | None = None, policy_value: dict | None = None):
        active_policy = self.policy if policy_value is None else policy_value
        self.path.write_text(json.dumps(active_policy), encoding="utf-8")
        active_evidence = self.evidence if value is None else value
        active_evidence["source"]["policySha256"] = file_sha256(self.path)
        return verifier.validate(
            active_evidence,
            active_policy,
            expected_gitops_commit=GITOPS_COMMIT,
            policy_path=self.path,
            now=self.now,
            artifact_root=self.artifact_root,
        )[0]

    def failed_names(self, value: dict | None = None, policy_value: dict | None = None):
        return {
            check.name for check in self.checks(value, policy_value) if not check.passed
        }

    def test_complete_machine_bound_evidence_passes(self) -> None:
        self.assertEqual(
            [], [check.name for check in self.checks() if not check.passed]
        )

    def test_v2_verdict_binds_exact_live_runtime_and_evidence_bytes(self) -> None:
        self.path.write_text(json.dumps(self.policy), encoding="utf-8")
        self.evidence["source"]["policySha256"] = file_sha256(self.path)
        evidence_path = self.artifact_root / "candidate.json"
        evidence_path.write_text(json.dumps(self.evidence), encoding="utf-8")
        checks, context = verifier.validate(
            self.evidence,
            self.policy,
            expected_gitops_commit=GITOPS_COMMIT,
            policy_path=self.path,
            now=dt.datetime(2026, 7, 18, 12, 0, 4, tzinfo=dt.timezone.utc),
            artifact_root=self.artifact_root,
        )
        verdict = verifier.build_verdict(
            checks=checks,
            context=context,
            policy=self.policy,
            expected_gitops_commit=GITOPS_COMMIT,
            policy_digest=file_sha256(self.path),
            evidence_digest=file_sha256(evidence_path),
            generated_at=dt.datetime(
                2026, 7, 18, 12, 0, 4, tzinfo=dt.timezone.utc
            ),
        )
        self.assertEqual(
            "faz24.transcriptReadyPreEnableVerdict.v2", verdict["schemaVersion"]
        )
        self.assertEqual("test", verdict["binding"]["targetAppEnv"])
        self.assertEqual(
            {
                "transcriptImageDigest": IMAGE_DIGEST,
                "backendCommit": BACKEND_COMMIT,
            },
            verdict["binding"]["producerCapability"],
        )
        self.assertEqual(
            {
                "podUid": "11111111-1111-1111-1111-111111111111",
                "imageDigest": IMAGE_DIGEST,
                "observedAt": "2026-07-18T11:59:56Z",
                "evidenceSha256": file_sha256(evidence_path),
            },
            verdict["binding"]["liveTranscriptPod"],
        )
        self.assertEqual(8, verdict["binding"]["evidenceAgeSeconds"])
        self.assertTrue(all(item["remediation"] == "" for item in verdict["checks"]))

    def test_committed_empty_allowlists_keep_gate_closed(self) -> None:
        blocked = json.loads(
            (
                ROOT / "config/faz24-transcript-ready-pre-enable-policy.v1.json"
            ).read_text(encoding="utf-8")
        )
        failed = self.failed_names(policy_value=blocked)
        self.assertIn("approved_producer_capability", failed)
        self.assertIn("approved_host_startup_guard", failed)
        self.assertIn("policy_enable_boundary", failed)

    def test_missing_or_nullable_analysis_run_column_fails(self) -> None:
        for key in (
            "analysisRunIdColumnPresent",
            "analysisRunIdNotNull",
            "analysisRunIdUuid",
            "finalizationOccurrenceColumnsPresent",
            "outboxRequiredColumnsPresent",
        ):
            with self.subTest(key=key):
                value = copy.deepcopy(self.evidence)
                value["live"]["postgresBefore"]["schema"][key] = False
                value["live"]["postgresAfter"]["schema"][key] = False
                self.assertIn("postgres_schema_capability", self.failed_names(value))

    def test_producer_capability_requires_remediation_evidence_digests(self) -> None:
        for field in (
            "backfillEvidenceSha256",
            "outboxRemediationEvidenceSha256",
            "redisRemediationEvidenceSha256",
        ):
            with self.subTest(field=field):
                policy_value = copy.deepcopy(self.policy)
                del policy_value["producerCapabilities"][0][field]
                self.assertIn(
                    f"producer_capability_{field}",
                    self.failed_names(policy_value=policy_value),
                )

    def test_producer_capability_must_bind_current_gate_contract(self) -> None:
        policy_value = copy.deepcopy(self.policy)
        policy_value["producerCapabilities"][0]["gateContractSha256"] = "0" * 64
        self.assertIn(
            "approved_producer_capability",
            self.failed_names(policy_value=policy_value),
        )

    def test_producer_capability_artifact_bytes_are_verified(self) -> None:
        artifact = self.artifact_root / "backfill.json"
        artifact.write_text("{}", encoding="utf-8")
        self.assertIn(
            "producer_capability_backfill_artifact",
            self.failed_names(),
        )

    def test_artifact_envelopes_cannot_replace_type_specific_evidence(self) -> None:
        for evidence_type in self.artifact_documents:
            with self.subTest(evidence_type=evidence_type):
                document = copy.deepcopy(self.artifact_documents[evidence_type])
                document["evidence"] = {}
                self.write_artifact(evidence_type, document)
                check = f"producer_capability_{evidence_type.lower()}_artifact"
                self.assertIn(check, self.failed_names())
                self.write_artifact(
                    evidence_type, self.artifact_documents[evidence_type]
                )

    def test_remediation_receipt_counts_and_results_are_consistent(self) -> None:
        mutations = {
            "BACKFILL": {
                "action": "BACKFILL",
                "beforeNullFinalizationCount": 1,
                "inventorySetSha256": "a" * 64,
            },
            "OUTBOX_REMEDIATION": {
                "action": "PURGE",
                "beforeLegacyByStatus": {
                    **empty_outbox_statuses(),
                    "pending": 1,
                    "total": 1,
                },
                "beforeMalformedReadyCount": 0,
                "inventorySetSha256": "b" * 64,
            },
            "REDIS_REMEDIATION": {
                "action": "DLQ_ACK_XDEL",
                "beforeLegacyReadyV1Count": 1,
                "inventorySetSha256": "c" * 64,
                "dlqReceiptSetSha256": "d" * 64,
                "xdelCount": 1,
            },
        }
        for evidence_type, mutation in mutations.items():
            with self.subTest(evidence_type=evidence_type):
                document = copy.deepcopy(self.artifact_documents[evidence_type])
                document["evidence"].update(mutation)
                self.write_artifact(evidence_type, document)
                check = f"producer_capability_{evidence_type.lower()}_artifact"
                self.assertIn(check, self.failed_names())
                self.write_artifact(
                    evidence_type, self.artifact_documents[evidence_type]
                )

    def test_positive_inventory_cannot_use_the_empty_set_digest(self) -> None:
        document = copy.deepcopy(self.artifact_documents["BACKFILL"])
        document["evidence"].update(
            {
                "action": "BACKFILL",
                "beforeNullFinalizationCount": 1,
                "processedCount": 1,
            }
        )
        self.write_artifact("BACKFILL", document)
        self.assertIn(
            "producer_capability_backfill_artifact",
            self.failed_names(),
        )

    def test_artifact_must_precede_fresh_scan_and_use_separate_claimed_issue(
        self,
    ) -> None:
        cases = {
            "completion-at-collection-start": {"completedAt": "2026-07-18T11:59:55Z"},
            "gate-issue-reused": {"evidenceIssue": "Halildeu/platform-k8s-gitops#2610"},
            "missing-claim": {"evidenceIssueClaimPath": "missing.json"},
            "empty-claim-receipt": {"evidenceIssueClaimSha256": EMPTY_SET_SHA},
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                document = copy.deepcopy(self.artifact_documents["BACKFILL"])
                document.update(mutation)
                self.write_artifact("BACKFILL", document)
                self.assertIn(
                    "producer_capability_backfill_artifact",
                    self.failed_names(),
                )
                self.write_artifact("BACKFILL", self.artifact_documents["BACKFILL"])

    def test_claim_receipt_bytes_and_schema_are_verified(self) -> None:
        self.claim_path.write_text("{}", encoding="utf-8")
        self.assertIn(
            "producer_capability_backfill_artifact",
            self.failed_names(),
        )

    def test_applied_remediation_receipts_pass_closed_schemas(self) -> None:
        applied = {
            "BACKFILL": {
                "action": "BACKFILL",
                "beforeNullFinalizationCount": 1,
                "inventorySetSha256": "a" * 64,
                "processedCount": 1,
            },
            "OUTBOX_REMEDIATION": {
                "action": "PURGE",
                "beforeLegacyByStatus": {
                    **empty_outbox_statuses(),
                    "published": 1,
                    "total": 1,
                },
                "inventorySetSha256": "b" * 64,
                "processedCount": 1,
                "purgedCount": 1,
            },
            "REDIS_REMEDIATION": {
                "action": "DLQ_ACK_XDEL",
                "beforeLegacyReadyV1Count": 1,
                "inventorySetSha256": "c" * 64,
                "dlqReceiptSetSha256": "d" * 64,
                "dlqAcceptedCount": 1,
                "xdelCount": 1,
            },
        }
        for evidence_type, mutation in applied.items():
            document = copy.deepcopy(self.artifact_documents[evidence_type])
            document["evidence"].update(mutation)
            self.write_artifact(evidence_type, document)
        failed = self.failed_names()
        for evidence_type in applied:
            with self.subTest(evidence_type=evidence_type):
                check = f"producer_capability_{evidence_type.lower()}_artifact"
                self.assertNotIn(check, failed)

    def test_query_contract_binds_event_to_same_finalization_occurrence(self) -> None:
        sql = collector.counts_sql("public")
        for fragment in (
            "COALESCE((ready.doc->>'schema' = 'meeting.event.v1'",
            "finalization.tenant_id = ready.tenant_id",
            "finalization.meeting_id = ready.meeting_id",
            "finalization.session_id = ready.aggregate_id",
            "finalization.finalization_version = CASE",
            "finalization.analysis_run_id::text = ready.doc->>'analysisRunId'",
            "ready.doc->>'tenantId' = ready.tenant_id::text",
            "ready.doc->>'meetingId' = ready.meeting_id::text",
            "ready.doc->>'transcriptSessionId' = ready.aggregate_id::text",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, sql)
        self.assertIn("|| (ready.doc->>'finalizationVersion') || '|'", sql)
        self.assertIn("|| (ready.doc->>'analysisRunId') AS binding", sql)
        for fragment in (
            "lower_uuid(decoded['analysisRunId'])",
            "lower_uuid(decoded['tenantId'])",
            "lower_uuid(decoded['meetingId'])",
            "lower_uuid(decoded['transcriptSessionId'])",
            "positive_integer(decoded['finalizationVersion'])",
            "table.insert(compatible_binding_sha1s",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, collector.REDIS_LUA)

    def test_postgres_ready_classification_must_be_exhaustive(self) -> None:
        value = copy.deepcopy(self.evidence)
        for snapshot in ("postgresBefore", "postgresAfter"):
            value["live"][snapshot]["counts"]["readyOutboxTotal"] = 3
        self.assertIn(
            "postgres_ready_classification_complete", self.failed_names(value)
        )

    def test_null_finalization_rows_fail(self) -> None:
        value = copy.deepcopy(self.evidence)
        for snapshot in ("postgresBefore", "postgresAfter"):
            value["live"][snapshot]["counts"]["finalizationNullAnalysisRunId"] = 1
        self.assertIn("finalization_null_rows", self.failed_names(value))

    def test_each_legacy_outbox_status_fails(self) -> None:
        for status in ("pending", "claimedActive", "claimedStale", "dead", "published"):
            with self.subTest(status=status):
                value = copy.deepcopy(self.evidence)
                for snapshot in ("postgresBefore", "postgresAfter"):
                    legacy = value["live"][snapshot]["counts"]["legacyOutbox"]
                    legacy[status] = 1
                    legacy["total"] = 1
                self.assertIn(f"legacy_outbox_{status}", self.failed_names(value))

    def test_postgres_change_around_redis_scan_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["postgresAfter"]["counts"]["compatibleReadyOutbox"] = 3
        self.assertIn("postgres_double_snapshot_stable", self.failed_names(value))

    def test_stale_component_or_database_capture_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["observedAt"] = "2020-01-01T00:00:00Z"
        self.assertIn("component_observation_window", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        for snapshot in ("postgresBefore", "postgresAfter"):
            value["live"][snapshot]["counts"]["capturedAt"] = "2020-01-01T00:00:00Z"
        self.assertIn("postgres_capture_window", self.failed_names(value))

    def test_wrong_database_or_redis_target_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["postgresBefore"]["schema"]["databaseName"] = "other"
        self.assertIn("postgres_target_identity", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["host"] = "127.0.0.1"
        self.assertIn("redis_target_identity", self.failed_names(value))

    def test_cross_store_binding_mismatch_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["compatibleBindingSetSha256"] = "0" * 64
        self.assertIn("cross_store_compatible_bindings", self.failed_names(value))

    def test_incomplete_or_truncated_redis_scan_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["scanned"] = 2
        value["live"]["redis"]["complete"] = False
        value["live"]["redis"]["truncated"] = True
        self.assertIn("redis_complete_atomic_scan", self.failed_names(value))

    def test_legacy_malformed_or_pending_redis_fails(self) -> None:
        cases = (
            ("legacyReadyV1", "redis_legacy_ready"),
            ("malformedReady", "redis_malformed_ready"),
        )
        for field, check in cases:
            with self.subTest(field=field):
                value = copy.deepcopy(self.evidence)
                value["live"]["redis"][field] = 1
                self.assertIn(check, self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["group"]["pending"] = 1
        self.assertIn("redis_group_pending", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["live"]["redis"]["group"].update(
            {
                "exists": True,
                "consumers": 7,
                "lastDeliveredId": "3-0",
                "entriesRead": 3,
                "lag": 0,
            }
        )
        self.assertIn("redis_group_absent_before_enable", self.failed_names(value))

    def test_enabled_or_unbound_host_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["live"]["gpuHost"]["healthEnabled"] = True
        value["live"]["gpuHost"]["healthStatus"] = "ok"
        value["live"]["gpuHost"]["healthWorkerRunning"] = True
        self.assertIn("host_consumer_default_off", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["live"]["gpuHost"]["startupGateMarkerPresent"] = False
        self.assertIn("approved_host_startup_guard", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        policy_value = copy.deepcopy(self.policy)
        value["live"]["gpuHost"]["platformAiCommit"] = "main"
        value["live"]["gpuHost"]["repoHeadCommit"] = "main"
        policy_value["hostStartupGuards"][0]["platformAiCommit"] = "main"
        failed = self.failed_names(value, policy_value)
        self.assertIn("gpu_host_identity", failed)
        self.assertIn("host_guard_platformAiCommit", failed)
        value = copy.deepcopy(self.evidence)
        value["live"]["gpuHost"]["computerName"] = "OTHER-PC"
        self.assertIn("gpu_host_identity", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["live"]["gpuHost"]["runtimeConfigState"] = "false"
        value["live"]["gpuHost"]["runtimeConfigMatchCount"] = 2
        self.assertIn("host_consumer_default_off", self.failed_names(value))

    def test_stale_or_wrong_digest_evidence_fails(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["generatedAt"] = "2026-07-18T11:00:00Z"
        self.assertIn("freshness", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["source"]["queryContractSha256"] = "0" * 64
        self.assertIn("query_contract_digest", self.failed_names(value))

    def test_sensitive_key_fails_metadata_boundary(self) -> None:
        value = copy.deepcopy(self.evidence)
        value["rawOutput"] = "not allowed"
        self.assertIn("metadata_only", self.failed_names(value))
        for field in ("sessionToken", "refreshToken", "csrfToken", "idToken"):
            with self.subTest(field=field):
                value = copy.deepcopy(self.evidence)
                value["nested"] = [{field: "redacted"}]
                self.assertIn("metadata_only", self.failed_names(value))
        value = copy.deepcopy(self.evidence)
        value["nested"] = [{"transcript": "redacted"}]
        self.assertIn("metadata_only", self.failed_names(value))

    def test_command_timeout_cannot_produce_evidence(self) -> None:
        result = collector.CommandResult(126, "", "TimeoutExpired")
        with self.assertRaisesRegex(collector.ContractError, "command-exit-126"):
            collector.parse_json_output(result, "bounded probe")

    def test_static_guard_detects_multiline_kubernetes_enable(self) -> None:
        module = runpy.run_path(
            str(
                ROOT / "scripts/test/verify-faz24-transcript-ready-pre-enable-static.py"
            )
        )
        manifest = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "env": [
                                    {
                                        "name": "MAI_READY_CONSUMER_ENABLED",
                                        "value": "true",
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
        self.assertTrue(module["object_findings"](manifest))

    def test_static_guard_requires_all_four_render_roles(self) -> None:
        module = runpy.run_path(
            str(
                ROOT / "scripts/test/verify-faz24-transcript-ready-pre-enable-static.py"
            )
        )
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                module["parse_args"]([])
        parsed = module["parse_args"](
            [
                "--test-render",
                "test.yaml",
                "--test-eso-render",
                "test-eso.yaml",
                "--prod-render",
                "prod.yaml",
                "--prod-eso-render",
                "prod-eso.yaml",
            ]
        )
        self.assertEqual(Path("test.yaml"), parsed.test_render)

    def test_policy_rejects_injectable_postgres_schema(self) -> None:
        value = policy()
        value["environment"]["postgresSchema"] = "public.schema"
        self.path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(
            collector.ContractError, "postgresSchema must be a simple lowercase identifier"
        ):
            collector.load_policy(self.path)


if __name__ == "__main__":
    unittest.main()
