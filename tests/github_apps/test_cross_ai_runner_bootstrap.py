from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.bootstrap import (
    RunnerBootstrapAuthorizer,
    RunnerBootstrapRequest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.evaluator import DeploymentEvaluator
from scripts.github_apps.cross_ai_deployment_policy.github import GitHubIntentRef
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


REQUEST_ID = "30000000-0000-4000-8000-000000000001"
HEAD = "0123456789abcdef0123456789abcdef01234567"
REPOSITORY = "Halildeu/platform-k8s-gitops"
ENVIRONMENT = "faz22-view-only-pilot"
WORKFLOW = ".github/workflows/apply-view-only-viewer-pilot-protected.yml"
LABELS = ["self-hosted", "staging-sw", "testai-deploy"]
CREDENTIAL = b"B" * 64


def policy_payload() -> dict[str, object]:
    stages = []
    for stage, workflow in (
        ("apply", WORKFLOW),
        (
            "browser-evidence",
            ".github/workflows/faz22-6-view-only-viewer-browser-evidence-protected.yml",
        ),
        (
            "compensating-rollback",
            ".github/workflows/rollback-view-only-viewer-pilot-protected.yml",
        ),
    ):
        stages.append(
            {
                "stage": stage,
                "workflowPath": workflow,
                "requiredRunsOnLabels": LABELS,
                "requireRunnerGroup": False,
            }
        )
    return {
        "schemaVersion": "acik.cross-ai-deployment-policy.v1",
        "policyId": "faz22-cross-ai-v1",
        "phase": "dual-gate",
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
        "workflowStages": stages,
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
        self.ref = GitHubIntentRef(
            ref_object_id="a" * 40, head_sha=HEAD, annotated=False
        )
        self.runner_name = "testai-deploy-runner"
        self.job_runner_id = 98765

    def intent_ref(self, installation_id: int, repository: str, request_id: str):
        return self.ref

    def repository_runners(self, installation_id: int, repository: str):
        return (
            {
                "id": 98765,
                "name": self.runner_name,
                "status": "online",
                "busy": True,
                "labels": [{"name": label, "type": "custom"} for label in LABELS],
            },
        )

    def workflow_run_attempt(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ):
        return {
            "id": run_id,
            "run_attempt": run_attempt,
            "event": "workflow_dispatch",
            "head_sha": HEAD,
            "head_branch": f"cross-ai-intent/{REQUEST_ID}",
            "path": WORKFLOW,
            "status": "in_progress",
            "repository": {"id": 123456789, "full_name": REPOSITORY},
            "head_repository": {"id": 123456789, "full_name": REPOSITORY},
        }

    def workflow_jobs(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ):
        return (
            {
                "id": 8080,
                "run_attempt": run_attempt,
                "status": "in_progress",
                "runner_id": self.job_runner_id,
                "runner_name": self.runner_name,
                "labels": LABELS,
            },
        )


class FakeOIDCVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def verify(self, token: str, **kwargs: object) -> dict[str, object]:
        if token != "signed-github-oidc-token":
            raise PolicyError("BOOTSTRAP_OIDC_SIGNATURE_INVALID", "invalid test OIDC")
        self.calls.append((token, kwargs))
        return {"jti": "test-oidc-jti-0001"}


class RunnerBootstrapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        policy_file = root / "policy.json"
        policy_file.write_text(json.dumps(policy_payload()), encoding="utf-8")
        self.policy = load_policy(policy_file)
        self.factory = FixtureFactory()
        self.fixture = self.factory.build(
            policy_digest=self.policy.digest,
            bootstrap_credential=CREDENTIAL,
            stage_overrides={
                "apply": {
                    "workflowPath": WORKFLOW,
                    "runsOnLabels": LABELS,
                    "runnerAttestationClass": "acik-testai-deploy-v1",
                },
                "browser-evidence": {
                    "workflowPath": policy_payload()["workflowStages"][1][
                        "workflowPath"
                    ],
                },
                "compensating-rollback": {
                    "workflowPath": policy_payload()["workflowStages"][2][
                        "workflowPath"
                    ],
                    "runsOnLabels": LABELS,
                    "runnerAttestationClass": "acik-testai-deploy-v1",
                },
            },
        )
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
            expected_policy_sha256=self.policy.digest,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.registry = IntentRegistry(
            root / "registry.sqlite3", ContentAddressedStore(root / "cas")
        )
        self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=self.fixture.now,
        )
        self.registry.finalize_ref(
            request_id=REQUEST_ID,
            ref_object_id="a" * 40,
            resolved_head_sha=HEAD,
            finalized_at=self.fixture.now,
        )
        self.registry.reserve_stage(
            request_id=REQUEST_ID,
            stage="apply",
            run_id=999001,
            run_attempt=1,
            app_rule_id=555,
            now=self.fixture.now,
        )
        self.registry.transition_stage(
            request_id=REQUEST_ID,
            stage="apply",
            to_state="ApprovedPendingOutcome",
            reason_code="CALLBACK_ACCEPTED_204",
            recorded_at=self.fixture.now,
        )
        self.github = FakeGitHub()
        self.revocations = self.fixture.revocations_envelope
        self.current = self.fixture.now + timedelta(seconds=30)
        self.evaluator = DeploymentEvaluator(
            policy=self.policy,
            registry=self.registry,
            github=self.github,  # type: ignore[arg-type]
            trust_root=self.fixture.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_loader=lambda: self.revocations,
            mode="enforce",
            now=lambda: self.current,
        )
        self.authorizer = RunnerBootstrapAuthorizer(
            evaluator=self.evaluator,
            installation_id=2222,
            oidc_verifier=FakeOIDCVerifier(),  # type: ignore[arg-type]
            now=lambda: self.current,
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    @staticmethod
    def request(**overrides: object) -> RunnerBootstrapRequest:
        value: dict[str, object] = {
            "requestId": REQUEST_ID,
            "stage": "apply",
            "runId": 999001,
            "runAttempt": 1,
            "intentRef": f"refs/tags/cross-ai-intent/{REQUEST_ID}",
            "headSha": HEAD,
            "workflowPath": WORKFLOW,
            "runnerName": "testai-deploy-runner",
        }
        value.update(overrides)
        return RunnerBootstrapRequest.parse(value)

    def test_returns_exact_signed_bundle_once_after_fresh_approval(self) -> None:
        response = self.authorizer.authorize(
            request=self.request(),
            credential=CREDENTIAL,
            oidc_token="signed-github-oidc-token",
        )
        self.assertEqual(response["bundleSha256"], self.verified.bundle_digest)
        self.assertEqual(response["bundleEnvelope"], self.fixture.bundle_envelope)
        self.assertIsNone(response["priorStageOutcome"])
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_ALREADY_CONSUMED"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )

    def test_rejects_invalid_github_oidc_before_static_credential(self) -> None:
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_SIGNATURE_INVALID"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="attacker-token",
            )

    def test_rejects_short_static_credential_and_boolean_run_identity(self) -> None:
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_CREDENTIAL_INVALID"):
            self.authorizer.authorize(
                request=self.request(),
                credential=b"x" * 63,
                oidc_token="signed-github-oidc-token",
            )
        for field in ("runId", "runAttempt"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_REQUEST_INVALID"):
                    self.request(**{field: True})

    def test_rejects_wrong_credential_runner_ref_stage_and_window(self) -> None:
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_CREDENTIAL_MISMATCH"):
            self.authorizer.authorize(
                request=self.request(),
                credential=b"z" * len(CREDENTIAL),
                oidc_token="signed-github-oidc-token",
            )
        self.github.runner_name = "unadmitted-runner"
        with self.assertRaisesRegex(PolicyError, "RUNNER_ADMISSION_LEASE_DRIFT"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )
        self.github.runner_name = "testai-deploy-runner"
        self.github.job_runner_id = 12345
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_RUNNER_NOT_ADMITTED"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )
        self.github.job_runner_id = 98765
        self.github.ref = GitHubIntentRef(
            ref_object_id="b" * 40, head_sha=HEAD, annotated=False
        )
        with self.assertRaisesRegex(PolicyError, "INTENT_REF_MOVED"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )
        self.github.ref = GitHubIntentRef(
            ref_object_id="a" * 40, head_sha=HEAD, annotated=False
        )
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_STAGE_MISMATCH"):
            self.authorizer.authorize(
                request=self.request(stage="browser-evidence", workflowPath=WORKFLOW),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )
        self.current = self.fixture.now + timedelta(minutes=3)
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_WINDOW_EXPIRED"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )

    def test_reloads_revocations_before_serving_bundle(self) -> None:
        self.revocations = self.factory.revocations(
            [
                {
                    "type": "runner-lease",
                    "id": "35000000-0000-4000-8000-000000000001",
                    "effectiveAt": "2026-07-16T20:30:01Z",
                    "reasonCode": "RUNNER_QUARANTINED",
                }
            ]
        )
        with self.assertRaisesRegex(PolicyError, "EVIDENCE_REVOKED"):
            self.authorizer.authorize(
                request=self.request(),
                credential=CREDENTIAL,
                oidc_token="signed-github-oidc-token",
            )


if __name__ == "__main__":
    unittest.main()
