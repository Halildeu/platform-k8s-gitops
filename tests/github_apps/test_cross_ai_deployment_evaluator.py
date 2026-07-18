from __future__ import annotations

import copy
from dataclasses import replace
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.evaluator import DeploymentEvaluator
from scripts.github_apps.cross_ai_deployment_policy.github import GitHubIntentRef
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.webhook import (
    DeploymentProtectionRequest,
)
from scripts.github_apps.cross_ai_deployment_policy.workflow import inspect_workflow
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


HEAD = "0123456789abcdef0123456789abcdef01234567"
REQUEST_ID = "30000000-0000-4000-8000-000000000001"
REPOSITORY = "Halildeu/platform-k8s-gitops"
ENVIRONMENT = "faz22-view-only-pilot"
NOW = datetime(2026, 7, 16, 20, 30, tzinfo=timezone.utc)
WORKFLOW = f"""
name: protected apply
on:
  workflow_dispatch:
permissions:
  contents: read
  id-token: write
concurrency:
  group: faz22-view-only-protected-lanes
  cancel-in-progress: false
jobs:
  apply:
    environment: {ENVIRONMENT}
    runs-on: [self-hosted, staging-sw, testai-deploy]
    steps:
      - uses: actions/checkout@{'1' * 40}
      - name: Verify signed runner bootstrap
        uses: Halildeu/platform-k8s-gitops/.github/actions/protected-bootstrap@{'1' * 40}
        env:
          CROSS_AI_BOOTSTRAP_TOKEN: ${{{{ secrets.CROSS_AI_BOOTSTRAP_TOKEN }}}}
          CROSS_AI_ENDPOINT_ID: ${{{{ secrets.CROSS_AI_ENDPOINT_ID }}}}
          CROSS_AI_OPERATOR_ID: ${{{{ secrets.CROSS_AI_OPERATOR_ID }}}}
          CROSS_AI_BOOTSTRAP_URL: https://testai.acik.com/v1/runner-bootstrap
          CROSS_AI_BOOTSTRAP_OUTPUT: ${{{{ runner.temp }}}}/cross-ai-bootstrap.json
        with:
          stage: apply
          workflow-path: .github/workflows/apply-view-only-viewer-pilot-protected.yml
          expected-trust-root-sha256: sha256:{'2' * 64}
      - name: Execute reviewed stage
        uses: Halildeu/platform-k8s-gitops/.github/actions/protected-apply@{'1' * 40}
        env:
          CROSS_AI_BOOTSTRAP_FILE: ${{{{ runner.temp }}}}/cross-ai-bootstrap.json
""".encode()


def policy_payload() -> dict[str, object]:
    return {
        "schemaVersion": "acik.cross-ai-deployment-policy.v1",
        "policyId": "faz22-cross-ai-v1",
        "phase": "dual-gate",
        "machineOnlyEnabled": False,
        "repositoryId": 123456789,
        "repository": REPOSITORY,
        "environment": ENVIRONMENT,
        "allowedApiOrigins": ["https://api.github.com"],
        "runnerBootstrapUrl": "https://testai.acik.com/v1/runner-bootstrap",
        "allowedInstallationIds": [2222],
        "allowedDispatcherInstallationIds": [3333],
        "allowedDispatcherActorIds": [424242],
        "allowedDeploymentClasses": ["reversible-test"],
        "maxGrantTtlMinutes": 120,
        "requiredCustomRuleAppIds": [555],
        "workflowStages": [
            {
                "stage": "apply",
                "workflowPath": ".github/workflows/apply-view-only-viewer-pilot-protected.yml",
                "requiredRunsOnLabels": [
                    "self-hosted",
                    "staging-sw",
                    "testai-deploy",
                ],
                "requireRunnerGroup": False,
            },
            {
                "stage": "browser-evidence",
                "workflowPath": ".github/workflows/faz22-6-view-only-viewer-browser-evidence-protected.yml",
                "requiredRunsOnLabels": ["self-hosted", "staging-sw", "testai-deploy"],
                "requireRunnerGroup": False,
            },
            {
                "stage": "compensating-rollback",
                "workflowPath": ".github/workflows/rollback-view-only-viewer-pilot-protected.yml",
                "requiredRunsOnLabels": [
                    "self-hosted",
                    "staging-sw",
                    "testai-deploy",
                ],
                "requireRunnerGroup": False,
            },
        ],
        "humanRequiredClasses": [
            "attended-consent",
            "legal-dpo",
            "named-authority",
            "production-secret-owner",
            "irreversible-production",
            "production",
            "break-glass",
        ],
    }


class FakeGitHub:
    def __init__(self) -> None:
        self.repository_value = {
            "id": 123456789,
            "full_name": REPOSITORY,
            "fork": False,
        }
        self.run_value = {
            "id": 987654321,
            "event": "workflow_dispatch",
            "head_sha": HEAD,
            "head_branch": f"cross-ai-intent/{REQUEST_ID}",
            "repository": {"id": 123456789, "full_name": REPOSITORY},
            "head_repository": {"id": 123456789, "full_name": REPOSITORY},
            "triggering_actor": {"id": 424242, "login": "platform-automation[bot]"},
            "run_attempt": 1,
            "status": "queued",
            "path": ".github/workflows/apply-view-only-viewer-pilot-protected.yml",
            "created_at": "2026-07-16T20:02:00Z",
        }
        self.environment_value = {
            "name": ENVIRONMENT,
            "protection_rules": [
                {"id": 1, "type": "required_reviewers"},
                {"id": 2, "type": "custom", "app": {"id": 555}},
            ],
            "can_admins_bypass": False,
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        }
        self.ref_value = GitHubIntentRef(
            ref_object_id=HEAD,
            head_sha=HEAD,
            annotated=False,
        )
        self.workflow_value = WORKFLOW

    def repository(self, installation_id: int, repository: str):
        return copy.deepcopy(self.repository_value)

    def workflow_run(self, installation_id: int, repository: str, run_id: int):
        return copy.deepcopy(self.run_value)

    def intent_ref(self, installation_id: int, repository: str, request_id: str):
        return self.ref_value

    def workflow_bytes(
        self, installation_id: int, repository: str, workflow_path: str, head_sha: str
    ):
        return self.workflow_value

    def repository_runners(self, installation_id: int, repository: str):
        return (
            {
                "id": 98765,
                "name": "testai-deploy-runner",
                "status": "online",
                "busy": False,
                "labels": [
                    {"name": label, "type": "custom"}
                    for label in ("self-hosted", "staging-sw", "testai-deploy")
                ],
            },
        )

    def environment(self, installation_id: int, repository: str, environment: str):
        return copy.deepcopy(self.environment_value)


class DeploymentEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        policy_path = Path(self.directory.name) / "policy.json"
        policy_path.write_text(json.dumps(policy_payload()), encoding="utf-8")
        self.policy = load_policy(policy_path)
        apply_stage = self.policy.stages["apply"]
        inspection = inspect_workflow(
            WORKFLOW,
            stage_policy=apply_stage,
            environment=ENVIRONMENT,
            expected_bootstrap_url=self.policy.runner_bootstrap_url,
        )
        self.factory = FixtureFactory()
        self.fixture = self.factory.build(
            policy_digest=self.policy.digest,
            stage_overrides={
                "apply": {
                    "workflowBlobSha256": inspection.workflow_sha256,
                    "dependencyLockSha256": inspection.dependency_lock_sha256,
                }
            },
        )
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=NOW,
            expected_policy_sha256=self.policy.digest,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.registry = IntentRegistry(
            Path(self.directory.name) / "registry.sqlite3",
            ContentAddressedStore(Path(self.directory.name) / "cas"),
        )
        self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
        )
        self.registry.finalize_ref(
            request_id=REQUEST_ID,
            ref_object_id=HEAD,
            resolved_head_sha=HEAD,
            finalized_at=datetime(2026, 7, 16, 20, 1, tzinfo=timezone.utc),
        )
        self.registry.queue_dispatch(
            request_id=REQUEST_ID,
            stage="apply",
            installation_id=3333,
            repository=REPOSITORY,
            queued_at=datetime(2026, 7, 16, 20, 1, tzinfo=timezone.utc),
        )
        self.registry.claim_dispatch(
            request_id=REQUEST_ID,
            stage="apply",
            claimed_at=datetime(2026, 7, 16, 20, 1, tzinfo=timezone.utc),
        )
        self.registry.record_dispatch_watermark(
            request_id=REQUEST_ID,
            stage="apply",
            watermark=987654320,
            snapshot_at=datetime(2026, 7, 16, 20, 1, tzinfo=timezone.utc),
        )
        self.registry.reconcile_dispatch(
            request_id=REQUEST_ID,
            stage="apply",
            run_id=987654321,
            reconciled_at=datetime(2026, 7, 16, 20, 2, tzinfo=timezone.utc),
        )
        self.github = FakeGitHub()
        self.evaluator = DeploymentEvaluator(
            policy=self.policy,
            registry=self.registry,
            github=self.github,
            trust_root=self.fixture.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_loader=lambda: self.fixture.revocations_envelope,
            mode="enforce",
            now=lambda: NOW,
        )
        self.request = DeploymentProtectionRequest(
            delivery_id="11111111-2222-4333-8444-555555555555",
            repository_id=123456789,
            repository=REPOSITORY,
            installation_id=2222,
            environment=ENVIRONMENT,
            head_sha=HEAD,
            intent_ref=f"refs/tags/cross-ai-intent/{REQUEST_ID}",
            request_id=REQUEST_ID,
            run_id=987654321,
            callback_url=(
                f"https://api.github.com/repos/{REPOSITORY}/actions/runs/"
                "987654321/deployment_protection_rule"
            ),
            sender_id=41898282,
            payload_sha256="sha256:" + ("f" * 64),
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def assert_rejected(self, code: str) -> None:
        with self.assertRaisesRegex(PolicyError, code):
            self.evaluator.evaluate(self.request)

    def test_accepts_only_exact_signed_intent_and_live_truth(self) -> None:
        result = self.evaluator.evaluate(self.request)
        self.assertTrue(result.approval_candidate)
        self.assertEqual(result.stage, "apply")
        self.assertEqual(
            result.provider_families,
            ("anthropic", "minimax", "openai"),
        )
        self.assertEqual(result.app_rule_id, 555)

    def test_rejects_callback_without_exact_dispatch_correlation(self) -> None:
        self.registry._connection.execute(
            "UPDATE intent_dispatches SET run_id = ? WHERE request_id = ? AND stage = ?",
            (987654322, REQUEST_ID, "apply"),
        )
        self.assert_rejected("DISPATCH_CORRELATION_MISMATCH")

    def test_rejects_workflow_dependency_or_actor_drift(self) -> None:
        self.github.workflow_value = WORKFLOW.replace(
            b"protected-apply", b"protected-other"
        )
        self.assert_rejected("INTENT_REF_OR_DEPENDENCY_LOCK_MISMATCH")
        self.github.workflow_value = WORKFLOW
        self.github.run_value["triggering_actor"] = {"id": 999999}
        self.assert_rejected("RUN_ACTOR_MISMATCH")

    def test_rejects_workflow_concurrency_group_drift(self) -> None:
        self.github.workflow_value = WORKFLOW.replace(
            b"faz22-view-only-protected-lanes",
            b"faz22-view-only-protected-lanes-forked",
        )
        self.assert_rejected("INTENT_REF_OR_DEPENDENCY_LOCK_MISMATCH")

    def test_rejects_environment_rule_drift_and_moved_ref(self) -> None:
        self.github.environment_value["protection_rules"].append(
            {"id": 3, "type": "custom", "app": {"id": 777}}
        )
        self.assert_rejected("ENVIRONMENT_CUSTOM_RULE_DRIFT")
        self.github.environment_value = FakeGitHub().environment_value
        self.github.ref_value = GitHubIntentRef("a" * 40, HEAD, True)
        self.assert_rejected("INTENT_REF_MOVED")

    def test_rejects_unverified_admin_bypass_and_observe_policy_enforcement(
        self,
    ) -> None:
        self.github.environment_value.pop("can_admins_bypass")
        self.assert_rejected("ENVIRONMENT_ADMIN_BYPASS_UNVERIFIED")
        payload = policy_payload()
        payload["phase"] = "observe"
        path = Path(self.directory.name) / "observe-policy.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(PolicyError, "ENFORCE_PHASE_INVALID"):
            DeploymentEvaluator(
                policy=load_policy(path),
                registry=self.registry,
                github=self.github,
                trust_root=self.fixture.trust_root,
                expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
                revocations_loader=lambda: self.fixture.revocations_envelope,
                mode="enforce",
                now=lambda: NOW,
            )

    def test_enforcement_rejects_zero_trust_pin_and_placeholder_authority_ids(
        self,
    ) -> None:
        with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_PIN_SENTINEL"):
            DeploymentEvaluator(
                policy=self.policy,
                registry=self.registry,
                github=self.github,
                trust_root=self.fixture.trust_root,
                expected_trust_root_sha256="sha256:" + ("0" * 64),
                revocations_loader=lambda: self.fixture.revocations_envelope,
                mode="enforce",
                now=lambda: NOW,
            )
        with self.assertRaisesRegex(PolicyError, "POLICY_AUTHORITY_SENTINEL"):
            DeploymentEvaluator(
                policy=replace(
                    self.policy,
                    required_custom_rule_app_ids=frozenset({900000001}),
                ),
                registry=self.registry,
                github=self.github,
                trust_root=self.fixture.trust_root,
                expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
                revocations_loader=lambda: self.fixture.revocations_envelope,
                mode="enforce",
                now=lambda: NOW,
            )

    def test_machine_only_kill_switch_and_launch_attestation_are_fail_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(PolicyError, "MACHINE_ONLY_DISABLED"):
            DeploymentEvaluator(
                policy=replace(self.policy, phase="machine-only-nonprod"),
                registry=self.registry,
                github=self.github,
                trust_root=self.fixture.trust_root,
                expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
                revocations_loader=lambda: self.fixture.revocations_envelope,
                mode="enforce",
                now=lambda: NOW,
            )
        evaluator = DeploymentEvaluator(
            policy=replace(
                self.policy,
                phase="machine-only-nonprod",
                machine_only_enabled=True,
            ),
            registry=self.registry,
            github=self.github,
            trust_root=self.fixture.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_loader=lambda: self.fixture.revocations_envelope,
            mode="enforce",
            now=lambda: NOW,
        )
        with self.assertRaisesRegex(PolicyError, "MACHINE_ONLY_IDENTITY_UNTRUSTED"):
            evaluator.evaluate(self.request)

    def test_reloads_revocations_for_every_decision(self) -> None:
        self.evaluator.evaluate(self.request)
        self.fixture.revocations_envelope = self.factory.revocations(
            [
                {
                    "type": "bundle",
                    "id": "70000000-0000-4000-8000-000000000001",
                    "effectiveAt": "2026-07-16T20:20:00Z",
                    "reasonCode": "COMPROMISE",
                }
            ]
        )
        self.assert_rejected("EVIDENCE_REVOKED")

    def test_rejects_wrong_event_fork_and_dispatch_window(self) -> None:
        self.github.run_value["event"] = "push"
        self.assert_rejected("RUN_EVENT_MISMATCH")
        self.github.run_value = FakeGitHub().run_value
        self.github.repository_value["fork"] = True
        self.assert_rejected("GITHUB_REPOSITORY_MISMATCH")
        self.github.repository_value = FakeGitHub().repository_value
        self.github.run_value["created_at"] = "2026-07-16T20:20:00Z"
        self.assert_rejected("RUN_DISPATCH_WINDOW_INVALID")


if __name__ == "__main__":
    unittest.main()
