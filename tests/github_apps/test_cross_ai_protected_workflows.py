from __future__ import annotations

import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.workflow import inspect_workflow


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/github-apps/cross-ai-deployment-policy.example.json"
ACTION_COMMIT = "ac69b07503755f56ef4f683ca331863bd5e9c6f0"
ZERO_TRUST_PIN = "sha256:" + ("0" * 64)


class ProtectedWorkflowSourceContractTest(unittest.TestCase):
    def test_all_signed_stage_paths_are_no_input_and_statically_reproducible(self) -> None:
        policy = load_policy(POLICY)
        inspections = []
        for stage in policy.stages.values():
            path = ROOT / stage.workflow_path
            raw = path.read_bytes()
            inspection = inspect_workflow(
                raw,
                stage_policy=stage,
                environment=policy.environment,
                expected_bootstrap_url=policy.runner_bootstrap_url,
            )
            inspections.append(inspection)
            self.assertIn(f"@{ACTION_COMMIT}", raw.decode("utf-8"))
            self.assertIn(ZERO_TRUST_PIN, raw.decode("utf-8"))
        self.assertEqual(
            len({item.concurrency_group_sha256 for item in inspections}),
            1,
        )

    def test_release_artifacts_are_absent_until_owner_transit_bootstrap(self) -> None:
        for name in (
            "cross-ai-deployment-policy.json",
            "cross-ai-deployment-trust-root.json",
            "cross-ai-deployment-revocations.json",
        ):
            self.assertFalse(
                (ROOT / "config/github-apps" / name).exists(),
                f"{name} must enter through the separate trust-root release",
            )

    def test_stage_runner_opens_bootstrap_as_private_owned_regular_file(self) -> None:
        script = (
            ROOT
            / "scripts/faz22-remote-ops/run-cross-ai-protected-view-only-stage.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('flags |= os.O_NOFOLLOW', script)
        self.assertIn('metadata.st_uid != os.getuid()', script)
        self.assertIn('stat.S_IMODE(metadata.st_mode) != 0o600', script)


if __name__ == "__main__":
    unittest.main()
