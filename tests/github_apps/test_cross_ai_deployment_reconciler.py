from __future__ import annotations

import copy
import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.reconciler import (
    GitHubOutcomeReconciler,
    OutcomeSweeper,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class FakeGitHub:
    def __init__(self, run, jobs) -> None:
        self.run = run
        self.jobs = jobs

    def workflow_run_attempt(
        self, installation_id: int, repository: str, run_id: int, run_attempt: int
    ):
        return copy.deepcopy(self.run)

    def workflow_jobs(
        self, installation_id: int, repository: str, run_id: int, run_attempt: int
    ):
        return copy.deepcopy(self.jobs)


class FakeArtifactSource:
    def __init__(
        self,
        archive: bytes,
        *,
        product_archives: dict[str, tuple[int, bytes]] | None = None,
    ) -> None:
        self.archive = archive
        self.requested_name: str | None = None
        self.product_archives = product_archives or {}
        self.calls: list[dict[str, object]] = []

    def fetch(self, **kwargs) -> bytes:
        self.calls.append(dict(kwargs))
        self.requested_name = kwargs["artifact_name"]
        if self.requested_name in self.product_archives:
            artifact_id, value = self.product_archives[self.requested_name]
            if kwargs.get("expected_artifact_id") != artifact_id:
                raise PolicyError(
                    "STAGE_PRODUCT_ARTIFACT_MISMATCH",
                    "live product artifact ID differs from stage evidence",
                )
            return value
        return self.archive


class FakePendingRegistry:
    def expire_pending_stages(self):
        return 0

    def pending_stages(self):
        return (
            type("Pending", (), {"request_id": "request-1", "stage": "apply"})(),
            type("Pending", (), {"request_id": "request-2", "stage": "apply"})(),
        )


class FakeReconciler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def reconcile(self, *, request_id: str, stage: str):
        self.calls.append((request_id, stage))
        if request_id == "request-2":
            raise PolicyError("GITHUB_RUN_NOT_TERMINAL", "not complete")
        return object()


def archive(
    evidence: dict[str, object], *, filename: str = "cross-ai-stage-evidence.json"
) -> bytes:
    output = io.BytesIO()
    info = zipfile.ZipInfo(filename, date_time=(2026, 7, 16, 20, 30, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(info, canonical_bytes(evidence))
    return output.getvalue()


class GitHubOutcomeReconcilerTest(unittest.TestCase):
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
        self.run = {
            "id": 101,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_sha": subject["headSha"],
            "head_branch": subject["intentRef"].removeprefix("refs/tags/"),
            "path": stage["workflowPath"],
            "run_started_at": "2026-07-16T20:30:00Z",
            "repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
            "head_repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
        }
        self.jobs = (
            {
                "name": "apply",
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    {
                        "number": 1,
                        "name": "verify signed intent",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "number": 2,
                        "name": "apply reversible overlay",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ],
            },
        )
        self.evidence = {
            "schemaVersion": "acik.cross-ai-deployment-stage-evidence.v1",
            "requestId": self.verified.request_id,
            "stage": "apply",
            "runId": 101,
            "runAttempt": 1,
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "headSha": subject["headSha"],
            "intentRef": subject["intentRef"],
            "sessionSha256": subject["sessionSha256"],
            "workflowBlobSha256": stage["workflowBlobSha256"],
            "artifactSetSha256": subject["artifactSetSha256"],
            "rollbackPlanSha256": subject["rollbackPlanSha256"],
            "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
            "productArtifactId": None,
            "productArtifactName": None,
            "productArtifactDigest": None,
            "watchdogExpiresAt": "2026-07-16T21:00:00Z",
            "conclusion": "success",
            "createdAt": "2026-07-16T20:30:00Z",
        }

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def reconciler(
        self,
        *,
        evidence=None,
        filename="cross-ai-stage-evidence.json",
        now=None,
        product_archives=None,
    ):
        source = FakeArtifactSource(
            archive(evidence or self.evidence, filename=filename),
            product_archives=product_archives,
        )
        value = GitHubOutcomeReconciler(
            installation_id=2222,
            registry=self.registry,
            github=FakeGitHub(self.run, self.jobs),
            artifact_source=source,
            trust_root=self.fixture.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_loader=lambda: self.fixture.revocations_envelope,
            now=lambda: now or self.fixture.now,
        )
        return value, source

    def test_reconciles_live_run_jobs_and_archive_into_durable_outcome(self) -> None:
        reconciler, source = self.reconciler()
        outcome = reconciler.reconcile(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.assertEqual(outcome.target_state, "Succeeded")
        self.assertEqual(
            source.requested_name,
            f"cross-ai-stage-outcome-{self.verified.request_id}-apply-101-1",
        )
        self.assertRegex(
            outcome.payload["criticalJobsSha256"], r"^sha256:[a-f0-9]{64}$"
        )
        self.assertRegex(
            outcome.payload["sourceArchiveSha256"], r"^sha256:[a-f0-9]{64}$"
        )
        self.assertEqual(
            self.registry.cas.get_json(outcome.outcome_digest),
            outcome.payload,
        )
        repeated = reconciler.reconcile(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.assertEqual(repeated.outcome_digest, outcome.outcome_digest)

    def test_browser_success_fetches_exact_product_artifact_and_verifies_digest(
        self,
    ) -> None:
        apply_reconciler, _ = self.reconciler()
        apply_reconciler.reconcile(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="browser-evidence",
            run_id=202,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        browser_stage = self.verified.payload["workflowStages"][1]
        self.run["id"] = 202
        self.run["path"] = browser_stage["workflowPath"]
        product_name = "faz22-6-view-only-viewer-browser-evidence-202"
        product_archive = b"independently-downloaded-browser-product-artifact"
        browser_evidence = copy.deepcopy(self.evidence)
        browser_evidence.update(
            {
                "stage": "browser-evidence",
                "runId": 202,
                "workflowBlobSha256": browser_stage["workflowBlobSha256"],
                "productArtifactId": 707,
                "productArtifactName": product_name,
                "productArtifactDigest": (
                    f"sha256:{hashlib.sha256(product_archive).hexdigest()}"
                ),
                "watchdogExpiresAt": None,
            }
        )
        reconciler, source = self.reconciler(
            evidence=browser_evidence,
            product_archives={product_name: (707, product_archive)},
        )
        outcome = reconciler.reconcile(
            request_id=self.verified.request_id,
            stage="browser-evidence",
        )
        self.assertEqual(outcome.target_state, "Succeeded")
        self.assertEqual(source.calls[-1]["artifact_name"], product_name)
        self.assertEqual(source.calls[-1]["expected_artifact_id"], 707)

    def test_browser_success_rejects_product_artifact_id_or_digest_mismatch(
        self,
    ) -> None:
        apply_reconciler, _ = self.reconciler()
        apply_reconciler.reconcile(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="browser-evidence",
            run_id=202,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        browser_stage = self.verified.payload["workflowStages"][1]
        self.run["id"] = 202
        self.run["path"] = browser_stage["workflowPath"]
        product_name = "faz22-6-view-only-viewer-browser-evidence-202"
        browser_evidence = copy.deepcopy(self.evidence)
        browser_evidence.update(
            {
                "stage": "browser-evidence",
                "runId": 202,
                "workflowBlobSha256": browser_stage["workflowBlobSha256"],
                "productArtifactId": 707,
                "productArtifactName": product_name,
                "productArtifactDigest": "sha256:" + ("7" * 64),
                "watchdogExpiresAt": None,
            }
        )
        reconciler, _ = self.reconciler(
            evidence=browser_evidence,
            product_archives={product_name: (708, b"wrong-product")},
        )
        with self.assertRaisesRegex(
            PolicyError,
            "STAGE_PRODUCT_ARTIFACT_MISMATCH",
        ):
            reconciler.reconcile(
                request_id=self.verified.request_id,
                stage="browser-evidence",
            )

        reconciler, _ = self.reconciler(
            evidence=browser_evidence,
            product_archives={product_name: (707, b"wrong-product")},
        )
        with self.assertRaisesRegex(
            PolicyError,
            "STAGE_PRODUCT_ARTIFACT_MISMATCH",
        ):
            reconciler.reconcile(
                request_id=self.verified.request_id,
                stage="browser-evidence",
            )

    def test_rejects_wrong_run_binding_unsafe_zip_and_conclusion_confusion(
        self,
    ) -> None:
        self.run["head_sha"] = "f" * 40
        reconciler, _ = self.reconciler()
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_RUN_MISMATCH"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")
        self.run["head_sha"] = self.verified.payload["subject"]["headSha"]

        reconciler, _ = self.reconciler(filename="../cross-ai-stage-evidence.json")
        with self.assertRaisesRegex(PolicyError, "STAGE_ARTIFACT_INVALID"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")

        self.run["conclusion"] = "failure"
        reconciler, _ = self.reconciler()
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_RUN_MISMATCH"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")

    def test_success_run_rejects_failed_or_skipped_critical_step(self) -> None:
        self.jobs[0]["steps"][1]["conclusion"] = "skipped"
        reconciler, _ = self.reconciler()
        with self.assertRaisesRegex(PolicyError, "GITHUB_CRITICAL_JOB_FAILED"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")

    def test_rejects_latest_attempt_or_job_attempt_confusion(self) -> None:
        self.run["run_attempt"] = 2
        reconciler, _ = self.reconciler()
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_RUN_MISMATCH"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")

        self.run["run_attempt"] = 1
        self.jobs[0]["run_attempt"] = 2
        reconciler, _ = self.reconciler()
        with self.assertRaisesRegex(PolicyError, "GITHUB_JOBS_INVALID"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")

    def test_overdue_apply_unlocks_rollback_only_after_exact_attempt_is_terminal(
        self,
    ) -> None:
        current = self.fixture.now + timedelta(minutes=31)
        self.registry.expire_pending_stages(now=current)
        self.run["status"] = "in_progress"
        self.run["conclusion"] = None
        reconciler, _ = self.reconciler(now=current)
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_RUN_NOT_TERMINAL"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="compensating-rollback",
                run_id=202,
                run_attempt=1,
                app_rule_id=999,
                now=current,
            )

        self.run["status"] = "completed"
        self.run["conclusion"] = "success"
        reconciler, _ = self.reconciler(filename="../unsafe.json", now=current)
        with self.assertRaisesRegex(PolicyError, "STAGE_ARTIFACT_INVALID"):
            reconciler.reconcile(request_id=self.verified.request_id, stage="apply")
        self.assertEqual(
            self.registry.get_stage(self.verified.request_id, "apply").state,
            "CallbackUnknown",
        )
        rollback = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="compensating-rollback",
            run_id=202,
            run_attempt=1,
            app_rule_id=999,
            now=current,
        )
        self.assertEqual(rollback.state, "Reserved")

    def test_sweeper_reconciles_pending_stages_and_has_explicit_lifecycle(self) -> None:
        reconciler = FakeReconciler()
        sweeper = OutcomeSweeper(
            registry=FakePendingRegistry(),  # type: ignore[arg-type]
            reconciler=reconciler,  # type: ignore[arg-type]
            interval_seconds=1.0,
        )
        self.assertEqual(sweeper.run_once(), (2, 1))
        self.assertEqual(
            reconciler.calls,
            [("request-1", "apply"), ("request-2", "apply")],
        )
        sweeper.start()
        sweeper.start()
        sweeper.stop()

        stopped = OutcomeSweeper(
            registry=FakePendingRegistry(),  # type: ignore[arg-type]
            reconciler=reconciler,  # type: ignore[arg-type]
            interval_seconds=1.0,
        )
        stopped.stop()
        with self.assertRaisesRegex(PolicyError, "OUTCOME_SWEEPER_STOPPED"):
            stopped.start()


if __name__ == "__main__":
    unittest.main()
