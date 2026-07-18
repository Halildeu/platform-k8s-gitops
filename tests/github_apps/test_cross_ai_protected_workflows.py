from __future__ import annotations

import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.workflow import inspect_workflow


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/github-apps/cross-ai-deployment-policy.example.json"
ACTION_COMMIT = "bfb2a880f4fc26c727a02fda8ad5643cc03412d6"
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
        self.assertIn('gateway route index 28 is not clean', script)
        self.assertIn('watchdog expiry differs from signed grant', script)
        self.assertIn('apply failure compensation verified', script)
        self.assertGreaterEqual(script.count('verify_watchdog_active'), 4)
        self.assertIn('(.status.active // 0) == 1', script)
        self.assertIn('(.status.failed // 0) == 0', script)
        self.assertIn('.status.phase == "Running"', script)
        self.assertIn('.type == "Ready" and .status == "True"', script)
        self.assertIn('.state.running.startedAt | type == "string"', script)
        self.assertIn('auth can-i $permission', script)
        self.assertIn('get rolebinding faz22-view-only-pilot-watchdog -o json', script)
        self.assertIn(
            'get networkpolicy allow-faz22-view-only-watchdog-kubernetes-api -o json',
            script,
        )
        self.assertLess(
            script.index('"networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api"'),
            script.index('delete job/faz22-view-only-pilot-watchdog'),
        )

    def test_watchdog_readiness_proves_live_api_access(self) -> None:
        template = (
            ROOT
            / "scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("readinessProbe:", template)
        self.assertIn("kubernetes.default.svc/api/v1/namespaces/", template)
        self.assertIn("configmaps/api-gateway-config", template)
        self.assertIn('Authorization: Bearer $token', template)

    def test_canonical_outcome_is_last_fallible_action_step(self) -> None:
        actions = {
            "protected-apply": "apply",
            "protected-browser-evidence": "browser",
            "protected-rollback": "rollback",
        }
        for directory, label in actions.items():
            raw = (ROOT / ".github/actions" / directory / "action.yml").read_text(
                encoding="utf-8"
            )
            upload = f"Upload canonical {label} outcome evidence"
            self.assertIn("id: cleanup", raw)
            self.assertLess(raw.index("id: cleanup"), raw.index(upload))
            self.assertNotIn("Remove private bootstrap response", raw[raw.index(upload) :])
            self.assertIn("steps.cleanup.outcome == 'success'", raw)

        browser = (
            ROOT / ".github/actions/protected-browser-evidence/action.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("id: product_evidence", browser)
        self.assertIn("steps.product_evidence.outcome == 'success'", browser)


if __name__ == "__main__":
    unittest.main()
