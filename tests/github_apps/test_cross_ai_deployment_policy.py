from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory
from tests.github_apps.test_cross_ai_deployment_evaluator import policy_payload


class DeploymentPolicyTest(unittest.TestCase):
    def test_loads_strict_policy_with_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy_payload()), encoding="utf-8")
            policy = load_policy(path)
            self.assertEqual(policy.repository, "Halildeu/platform-k8s-gitops")
            self.assertEqual(policy.allowed_installation_ids, frozenset({2222}))
            self.assertEqual(
                policy.allowed_dispatcher_installation_ids,
                frozenset({3333}),
            )
            self.assertRegex(policy.digest, r"^sha256:[a-f0-9]{64}$")

    def test_loads_single_transaction_v3_authority_policy(self) -> None:
        payload = {
            "schemaVersion": "acik.cross-ai-deployment-policy.v2",
            "authorityContractVersion": "v3",
            "policyId": "faz22-view-only-transaction-v2",
            "phase": "dual-gate",
            "machineOnlyEnabled": False,
            "repositoryId": 1211415632,
            "repository": "Halildeu/platform-k8s-gitops",
            "environment": "faz22-view-only-pilot",
            "allowedApiOrigins": ["https://api.github.com"],
            "allowedInstallationIds": [147158710],
            "allowedDispatcherInstallationIds": [2222],
            "allowedDispatcherActorIds": [424242],
            "allowedDeploymentClasses": ["reversible-test"],
            "maxGrantTtlMinutes": 120,
            "maxRunAttempts": 1,
            "requiredCustomRuleAppIds": [4322193],
            "preflightArtifactPrefix": "faz22-view-only-transaction-preflight",
            "workflowTransaction": {
                "stage": "transaction",
                "workflowPath": ".github/workflows/faz22-6-view-only-viewer-transaction.yml",
                "requiredPreflightRunsOnLabels": ["ubuntu-24.04"],
                "requiredRunsOnLabels": [
                    "self-hosted",
                    "staging-sw",
                    "testai-deploy",
                ],
                "requireRunnerGroup": False,
                "requiresSameRunPreflight": True,
                "requiresOneProtectedEnvironmentGate": True,
                "requiredAuthorityPaths": sorted(
                    FixtureFactory.TRANSACTION_AUTHORITY_PATHS
                ),
            },
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
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            policy = load_policy(path)
        self.assertEqual(policy.authority_contract_version, "v3")
        self.assertEqual(tuple(policy.stages), ("transaction",))
        self.assertEqual(policy.max_run_attempts, 1)
        self.assertTrue(policy.stages["transaction"].requires_same_run_preflight)
        self.assertEqual(
            policy.stages["transaction"].required_authority_paths,
            tuple(sorted(FixtureFactory.TRANSACTION_AUTHORITY_PATHS)),
        )

    def test_rejects_duplicate_json_keys_and_eroded_human_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text('{"schemaVersion":"a","schemaVersion":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(PolicyError, "JSON_DUPLICATE_KEY"):
                load_policy(path)
            payload = policy_payload()
            payload["humanRequiredClasses"] = ["production"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                PolicyError, "POLICY_SCHEMA_INVALID|POLICY_HUMAN_BOUNDARY_INVALID"
            ):
                load_policy(path)


if __name__ == "__main__":
    unittest.main()
