from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.outcome import verify_stage_outcome
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class StageOutcomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.factory = FixtureFactory()
        self.fixture = self.factory.build()
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.registry = IntentRegistry(
            Path(self.directory.name) / "registry.sqlite3",
            ContentAddressedStore(Path(self.directory.name) / "cas"),
        )
        self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=self.fixture.now,
        )
        self.registry.finalize_ref(
            request_id=self.verified.request_id,
            ref_object_id="a" * 40,
            resolved_head_sha=self.verified.payload["subject"]["headSha"],
            finalized_at=self.fixture.now,
        )
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=101,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        subject = self.verified.payload["subject"]
        stage = self.verified.payload["workflowStages"][0]
        self.critical = sha256_digest({"jobs": ["apply"], "steps": ["verify", "apply"]})
        self.artifact_name = (
            f"cross-ai-stage-outcome-{self.verified.request_id}-apply-101-1"
        )
        self.archive = sha256_digest({"archive": "github-artifact-bytes"})
        self.payload = {
            "schemaVersion": "acik.cross-ai-deployment-stage-outcome.v1",
            "requestId": self.verified.request_id,
            "stage": "apply",
            "runId": 101,
            "runAttempt": 1,
            "runStartedAt": "2026-07-16T20:30:00Z",
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "headSha": subject["headSha"],
            "intentRef": subject["intentRef"],
            "sessionSha256": subject["sessionSha256"],
            "workflowBlobSha256": stage["workflowBlobSha256"],
            "criticalJobsSha256": self.critical,
            "sourceArtifactName": self.artifact_name,
            "sourceArchiveSha256": self.archive,
            "artifactSetSha256": subject["artifactSetSha256"],
            "rollbackPlanSha256": subject["rollbackPlanSha256"],
            "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
            "watchdogExpiresAt": "2026-07-16T21:00:00Z",
            "conclusion": "success",
            "createdAt": "2026-07-16T20:30:00Z",
        }

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def verify(self, payload=None):
        return verify_stage_outcome(
            payload or self.payload,
            bundle=self.verified,
            expected_stage="apply",
            expected_run_id=101,
            expected_run_attempt=1,
            expected_run_started_at="2026-07-16T20:30:00Z",
            expected_critical_jobs_sha256=self.critical,
            expected_source_artifact_name=self.artifact_name,
            expected_source_archive_sha256=self.archive,
            now=self.fixture.now,
        )

    def test_verifies_and_atomically_records_success_from_reserved(self) -> None:
        outcome = self.verify()
        self.assertTrue(
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=outcome.payload,
                outcome_digest=outcome.outcome_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now,
            )
        )
        stored = self.registry.cas.get_json(outcome.outcome_digest)
        self.assertEqual(stored["sourceArtifactName"], self.artifact_name)
        self.assertEqual(stored["sourceArchiveSha256"], self.archive)
        self.assertFalse(
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=outcome.payload,
                outcome_digest=outcome.outcome_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now,
            )
        )
        browser = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="browser-evidence",
            run_id=202,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.assertEqual(browser.state, "Reserved")
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="compensating-rollback",
                run_id=303,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )

    def test_rejects_self_asserted_jobs_wrong_binding_and_unbounded_watchdog(
        self,
    ) -> None:
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_BINDING_MISMATCH"):
            verify_stage_outcome(
                self.payload,
                bundle=self.verified,
                expected_stage="apply",
                expected_run_id=101,
                expected_run_attempt=1,
                expected_run_started_at="2026-07-16T20:30:00Z",
                expected_critical_jobs_sha256="sha256:" + ("0" * 64),
                expected_source_artifact_name=self.artifact_name,
                expected_source_archive_sha256=self.archive,
                now=self.fixture.now,
            )
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_BINDING_MISMATCH"):
            verify_stage_outcome(
                self.payload,
                bundle=self.verified,
                expected_stage="apply",
                expected_run_id=101,
                expected_run_attempt=1,
                expected_run_started_at="2026-07-16T20:30:00Z",
                expected_critical_jobs_sha256=self.critical,
                expected_source_artifact_name="wrong-artifact",
                expected_source_archive_sha256=self.archive,
                now=self.fixture.now,
            )
        changed = copy.deepcopy(self.payload)
        changed["headSha"] = "f" * 40
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_BINDING_MISMATCH"):
            self.verify(changed)
        changed = copy.deepcopy(self.payload)
        changed["watchdogExpiresAt"] = "2026-07-16T22:00:00Z"
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_WATCHDOG_INVALID"):
            self.verify(changed)

    def test_accepts_failed_apply_before_watchdog_creation(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["conclusion"] = "failure"
        changed["watchdogExpiresAt"] = None
        outcome = self.verify(changed)
        self.assertEqual(outcome.target_state, "Failed")

    def test_rejects_conflicting_second_outcome(self) -> None:
        outcome = self.verify()
        self.registry.record_stage_outcome(
            request_id=outcome.request_id,
            stage=outcome.stage,
            run_id=outcome.run_id,
            run_attempt=outcome.run_attempt,
            outcome=outcome.payload,
            outcome_digest=outcome.outcome_digest,
            target_state=outcome.target_state,
            recorded_at=self.fixture.now,
        )
        changed = copy.deepcopy(self.payload)
        changed["conclusion"] = "failure"
        conflicting = self.verify(changed)
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_CONFLICT"):
            self.registry.record_stage_outcome(
                request_id=conflicting.request_id,
                stage=conflicting.stage,
                run_id=conflicting.run_id,
                run_attempt=conflicting.run_attempt,
                outcome=conflicting.payload,
                outcome_digest=conflicting.outcome_digest,
                target_state=conflicting.target_state,
                recorded_at=self.fixture.now,
            )

    def test_registry_rechecks_outcome_identity_before_cas_write(self) -> None:
        outcome = self.verify()
        changed = copy.deepcopy(outcome.payload)
        changed["runId"] = 999
        changed_digest = sha256_digest(changed)
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_BINDING_MISMATCH"):
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=changed,
                outcome_digest=changed_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now,
            )
        self.assertFalse(self.registry.cas._path(changed_digest).exists())

        changed = copy.deepcopy(outcome.payload)
        changed["sessionSha256"] = "sha256:" + ("0" * 64)
        changed_digest = sha256_digest(changed)
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_BINDING_MISMATCH"):
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=changed,
                outcome_digest=changed_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now,
            )
        self.assertFalse(self.registry.cas._path(changed_digest).exists())

    def test_registry_rejects_late_outcome_without_orphaning_cas(self) -> None:
        outcome = self.verify()
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_EXPIRED"):
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=outcome.payload,
                outcome_digest=outcome.outcome_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now.replace(hour=22),
            )
        self.assertFalse(self.registry.cas._path(outcome.outcome_digest).exists())

    def test_failed_apply_outcome_unlocks_only_rollback(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["conclusion"] = "failure"
        outcome = self.verify(changed)
        self.registry.record_stage_outcome(
            request_id=outcome.request_id,
            stage=outcome.stage,
            run_id=outcome.run_id,
            run_attempt=outcome.run_attempt,
            outcome=outcome.payload,
            outcome_digest=outcome.outcome_digest,
            target_state=outcome.target_state,
            recorded_at=self.fixture.now,
        )
        rollback = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="compensating-rollback",
            run_id=303,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.assertEqual(rollback.state, "Reserved")
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="browser-evidence",
                run_id=202,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )

    def test_rejects_run_that_started_after_reservation_lease(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["runStartedAt"] = "2026-07-16T21:01:00Z"
        changed["createdAt"] = "2026-07-16T21:02:00Z"
        changed_digest = sha256_digest(changed)
        with self.assertRaisesRegex(PolicyError, "STAGE_RESERVATION_EXPIRED"):
            self.registry.record_stage_outcome(
                request_id=self.verified.request_id,
                stage="apply",
                run_id=101,
                run_attempt=1,
                outcome=changed,
                outcome_digest=changed_digest,
                target_state="Succeeded",
                recorded_at=self.fixture.now.replace(minute=35),
            )
        self.assertFalse(self.registry.cas._path(changed_digest).exists())

    def test_late_success_cannot_overtake_activated_rollback(self) -> None:
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="OutcomeOverdue",
            reason_code="OUTCOME_RECONCILIATION_DEADLINE_EXCEEDED",
            recorded_at=self.fixture.now,
        )
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="CallbackUnknown",
            reason_code="TERMINAL_RUN_WITH_UNSEALED_OUTCOME",
            recorded_at=self.fixture.now,
        )
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="compensating-rollback",
            run_id=303,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        outcome = self.verify()
        with self.assertRaisesRegex(PolicyError, "STAGE_ROLLBACK_IN_PROGRESS"):
            self.registry.record_stage_outcome(
                request_id=outcome.request_id,
                stage=outcome.stage,
                run_id=outcome.run_id,
                run_attempt=outcome.run_attempt,
                outcome=outcome.payload,
                outcome_digest=outcome.outcome_digest,
                target_state=outcome.target_state,
                recorded_at=self.fixture.now,
            )
        self.assertFalse(self.registry.cas._path(outcome.outcome_digest).exists())


if __name__ == "__main__":
    unittest.main()
