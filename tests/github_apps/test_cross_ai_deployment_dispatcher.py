from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.dispatcher import (
    IntentDispatchOrchestrator,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import (
    DispatchResult,
    GitHubIntentRef,
)
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class FakeDispatchGitHub:
    def __init__(self, *, result: DispatchResult) -> None:
        self.result = result
        self.create_calls = 0
        self.dispatch_calls = 0
        self.runs: tuple[dict, ...] = ()
        self.live_ref: GitHubIntentRef | None = None
        self.inputs: dict | None = None

    def create_intent_ref(
        self,
        *,
        installation_id: int,
        repository: str,
        request_id: str,
        head_sha: str,
    ) -> GitHubIntentRef:
        self.create_calls += 1
        self.live_ref = GitHubIntentRef(head_sha, head_sha, False)
        return self.live_ref

    def dispatch_workflow(
        self,
        *,
        installation_id: int,
        repository: str,
        workflow_path: str,
        request_id: str,
        inputs: dict | None = None,
    ) -> DispatchResult:
        self.dispatch_calls += 1
        self.inputs = inputs
        return self.result

    def workflow_runs_for_dispatch(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        intent_branch: str,
        created_from: str,
        created_to: str,
    ) -> tuple[dict, ...]:
        return self.runs

    def intent_ref(
        self,
        installation_id: int,
        repository: str,
        request_id: str,
    ) -> GitHubIntentRef:
        assert self.live_ref is not None
        return self.live_ref


class IntentDispatchOrchestratorTest(unittest.TestCase):
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
        self.now = self.fixture.now

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def orchestrator(self, github: FakeDispatchGitHub) -> IntentDispatchOrchestrator:
        return IntentDispatchOrchestrator(
            registry=self.registry,
            dispatcher=github,
            reader=github,
            installation_id=2222,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            verify_envelope=lambda envelope: EvidenceVerifier(
                trust_root=self.fixture.trust_root,
                revocations_envelope=self.fixture.revocations_envelope,
                now=self.now,
            ).verify_bundle(envelope),
            now=lambda: self.now,
        )

    def test_accepted_dispatch_is_not_posted_twice_after_restart(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        orchestrator = self.orchestrator(github)
        first = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.assertEqual(first.state, "Sending")
        self.now += timedelta(seconds=30)
        second = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.assertEqual(second.state, "Sending")
        self.assertEqual(github.dispatch_calls, 1)
        self.assertEqual(github.create_calls, 2)

    def test_crash_after_durable_claim_never_reposts(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=self.now,
        )
        ref = github.create_intent_ref(
            installation_id=2222,
            repository=self.verified.payload["subject"]["repository"],
            request_id=self.verified.request_id,
            head_sha=self.verified.payload["subject"]["headSha"],
        )
        self.registry.finalize_ref(
            request_id=self.verified.request_id,
            ref_object_id=ref.ref_object_id,
            resolved_head_sha=ref.head_sha,
            finalized_at=self.now,
        )
        self.registry.queue_dispatch(
            request_id=self.verified.request_id,
            stage="apply",
            installation_id=2222,
            repository=self.verified.payload["subject"]["repository"],
            queued_at=self.now,
        )
        self.registry.claim_dispatch(
            request_id=self.verified.request_id,
            stage="apply",
            claimed_at=self.now,
        )
        restarted = self.orchestrator(github).dispatch_stage(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.assertEqual(restarted.state, "Sending")
        self.assertEqual(github.dispatch_calls, 0)

    def test_later_stage_operation_rechecks_current_revocations(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        orchestrator = self.orchestrator(github)
        orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.fixture.revocations_envelope = self.factory.revocations(
            [
                {
                    "type": "bundle",
                    "id": self.verified.bundle_id,
                    "effectiveAt": "2026-07-16T20:20:00Z",
                    "reasonCode": "COMPROMISE",
                }
            ]
        )
        with self.assertRaisesRegex(PolicyError, "EVIDENCE_REVOKED"):
            orchestrator.dispatch_stage(
                request_id=self.verified.request_id,
                stage="apply",
            )
        self.assertEqual(github.dispatch_calls, 1)

    def test_ambiguous_dispatch_requires_one_exact_live_run(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(
                False,
                True,
                503,
                "DISPATCH_HTTP_AMBIGUOUS",
            )
        )
        orchestrator = self.orchestrator(github)
        job = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.assertEqual(job.state, "Uncertain")
        subject = self.verified.payload["subject"]
        actor_id = self.verified.payload["grant"]["triggeringActorId"]
        run = {
            "id": 77,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "head_branch": subject["intentRef"].removeprefix("refs/tags/"),
            "head_sha": subject["headSha"],
            "path": job.workflow_path,
            "created_at": self.fixture.now.isoformat().replace("+00:00", "Z"),
            "triggering_actor": {"id": actor_id},
            "repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
            "head_repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
        }
        github.runs = (run,)
        reconciled = orchestrator.reconcile_dispatch(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.assertEqual(reconciled.state, "Accepted")
        self.assertEqual(reconciled.run_id, 77)

    def test_duplicate_matching_runs_remain_fail_closed(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(False, True, None, "DISPATCH_TRANSPORT_AMBIGUOUS")
        )
        orchestrator = self.orchestrator(github)
        job = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        subject = self.verified.payload["subject"]
        base = {
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "head_branch": subject["intentRef"].removeprefix("refs/tags/"),
            "head_sha": subject["headSha"],
            "path": job.workflow_path,
            "created_at": self.fixture.now.isoformat().replace("+00:00", "Z"),
            "triggering_actor": {
                "id": self.verified.payload["grant"]["triggeringActorId"]
            },
            "repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
            "head_repository": {
                "id": subject["repositoryId"],
                "full_name": subject["repository"],
            },
        }
        github.runs = ({**base, "id": 77}, {**base, "id": 78})
        with self.assertRaisesRegex(PolicyError, "DISPATCH_RECONCILIATION_AMBIGUOUS"):
            orchestrator.reconcile_dispatch(
                request_id=self.verified.request_id,
                stage="apply",
            )
        self.assertEqual(
            self.registry.get_dispatch(self.verified.request_id, "apply").state,
            "Uncertain",
        )
        self.assertEqual(github.dispatch_calls, 1)

    def test_zero_candidates_stay_non_approving_then_become_uncertain(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        orchestrator = self.orchestrator(github)
        job = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.assertEqual(job.state, "Sending")
        self.assertEqual(
            orchestrator.reconcile_dispatch(
                request_id=self.verified.request_id,
                stage="apply",
            ).state,
            "Sending",
        )
        self.now += timedelta(minutes=11)
        self.assertEqual(
            orchestrator.reconcile_dispatch(
                request_id=self.verified.request_id,
                stage="apply",
            ).state,
            "Uncertain",
        )

    def test_preexisting_run_is_never_accepted_before_delayed_real_run(self) -> None:
        github = FakeDispatchGitHub(
            result=DispatchResult(False, True, 503, "DISPATCH_HTTP_AMBIGUOUS")
        )
        subject = self.verified.payload["subject"]
        actor_id = self.verified.payload["grant"]["triggeringActorId"]

        def run(run_id: int) -> dict:
            return {
                "id": run_id,
                "run_attempt": 1,
                "event": "workflow_dispatch",
                "head_branch": subject["intentRef"].removeprefix("refs/tags/"),
                "head_sha": subject["headSha"],
                "path": self.verified.payload["workflowStages"][0]["workflowPath"],
                "created_at": self.fixture.now.isoformat().replace("+00:00", "Z"),
                "triggering_actor": {"id": actor_id},
                "repository": {
                    "id": subject["repositoryId"],
                    "full_name": subject["repository"],
                },
                "head_repository": {
                    "id": subject["repositoryId"],
                    "full_name": subject["repository"],
                },
            }

        github.runs = (run(77),)
        orchestrator = self.orchestrator(github)
        job = orchestrator.register_and_dispatch_apply(
            envelope=self.fixture.bundle_envelope,
        )
        self.assertEqual(job.pre_dispatch_run_id_watermark, 77)
        self.assertEqual(job.state, "Uncertain")
        self.assertEqual(
            orchestrator.reconcile_dispatch(
                request_id=self.verified.request_id,
                stage="apply",
            ).state,
            "Uncertain",
        )
        github.runs = (run(77), run(78))
        accepted = orchestrator.reconcile_dispatch(
            request_id=self.verified.request_id,
            stage="apply",
        )
        self.assertEqual(accepted.state, "Accepted")
        self.assertEqual(accepted.run_id, 78)

    def test_v3_transaction_inputs_are_subject_bound_and_never_reposted(self) -> None:
        factory = FixtureFactory("v3")
        fixture = factory.build()
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        orchestrator = IntentDispatchOrchestrator(
            registry=self.registry,
            dispatcher=github,
            reader=github,
            installation_id=2222,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            verify_envelope=lambda envelope: EvidenceVerifier(
                trust_root=fixture.trust_root,
                revocations_envelope=fixture.revocations_envelope,
                now=fixture.now,
                expected_bundle_contract="v3",
            ).verify_bundle(envelope),
            now=lambda: fixture.now,
        )
        values = {
            "confirm": "RUN_FAZ22_6_VIEW_ONLY_TRANSACTION",
            "device_id": factory.TRANSACTION_DEVICE_ID,
            "device_hostname": factory.TRANSACTION_DEVICE_HOSTNAME,
            "pilot_seconds": 300,
            "mask_rect_bps": factory.TRANSACTION_MASK_RECT_BPS,
            "preflight_only": False,
        }
        first = orchestrator.register_and_dispatch_transaction(
            envelope=fixture.bundle_envelope,
            transaction_inputs=values,
        )
        second = orchestrator.register_and_dispatch_transaction(
            envelope=fixture.bundle_envelope,
            transaction_inputs=values,
        )
        self.assertEqual((first.state, second.state), ("Sending", "Sending"))
        self.assertEqual(github.dispatch_calls, 1)
        self.assertEqual(github.inputs["pilot_seconds"], "300")
        self.assertIs(github.inputs["preflight_only"], False)

    def test_v3_transaction_input_tamper_is_denied_before_registration(self) -> None:
        factory = FixtureFactory("v3")
        fixture = factory.build()
        github = FakeDispatchGitHub(
            result=DispatchResult(True, False, 204, "DISPATCH_ACCEPTED_204")
        )
        orchestrator = IntentDispatchOrchestrator(
            registry=self.registry,
            dispatcher=github,
            reader=github,
            installation_id=2222,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            verify_envelope=lambda envelope: EvidenceVerifier(
                trust_root=fixture.trust_root,
                revocations_envelope=fixture.revocations_envelope,
                now=fixture.now,
                expected_bundle_contract="v3",
            ).verify_bundle(envelope),
            now=lambda: fixture.now,
        )
        with self.assertRaisesRegex(PolicyError, "TRANSACTION_INPUT_BINDING_MISMATCH"):
            orchestrator.register_and_dispatch_transaction(
                envelope=fixture.bundle_envelope,
                transaction_inputs={
                    "confirm": "RUN_FAZ22_6_VIEW_ONLY_TRANSACTION",
                    "device_id": factory.TRANSACTION_DEVICE_ID,
                    "device_hostname": "wrong-host",
                    "pilot_seconds": 300,
                    "mask_rect_bps": factory.TRANSACTION_MASK_RECT_BPS,
                    "preflight_only": False,
                },
            )
        with self.assertRaisesRegex(PolicyError, "TRANSACTION_INPUTS_INVALID"):
            orchestrator.register_and_dispatch_transaction(
                envelope=fixture.bundle_envelope,
                transaction_inputs={
                    "confirm": "RUN_FAZ22_6_VIEW_ONLY_TRANSACTION",
                    "device_id": factory.TRANSACTION_DEVICE_ID,
                    "device_hostname": factory.TRANSACTION_DEVICE_HOSTNAME,
                    "pilot_seconds": 300,
                    "mask_rect_bps": "9000,9000,2000,2000",
                    "preflight_only": False,
                },
            )
        self.assertEqual(github.create_calls, 0)
        self.assertEqual(github.dispatch_calls, 0)


if __name__ == "__main__":
    unittest.main()
