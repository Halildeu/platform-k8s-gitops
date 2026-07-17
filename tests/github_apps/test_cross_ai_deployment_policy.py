from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from tests.github_apps.test_cross_ai_deployment_evaluator import policy_payload


class DeploymentPolicyTest(unittest.TestCase):
    def test_loads_strict_policy_with_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy_payload()), encoding="utf-8")
            policy = load_policy(path)
            self.assertEqual(policy.repository, "Halildeu/platform-k8s-gitops")
            self.assertRegex(policy.digest, r"^sha256:[a-f0-9]{64}$")

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
