from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BackendPromotionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.promote = (ROOT / ".github/workflows/deploy-backend-testai.yml").read_text()
        cls.verify = (
            ROOT / ".github/workflows/verify-testai-backend-rollout.yml"
        ).read_text()
        cls.sync = (ROOT / "scripts/automation/sync-test-overlay.sh").read_text()
        cls.reconcile = (
            ROOT / "scripts/deploy/reconcile-testai-backend-sequential.sh"
        ).read_text()
        cls.bootstrap = (
            ROOT / "scripts/deploy/ensure-argocd-cli.sh"
        ).read_text()
        cls.runtime = (
            ROOT / "scripts/deploy/verify-testai-backend-runtime.sh"
        ).read_text()
        cls.overlay = (
            ROOT / "kustomize/overlays/test/kustomization.yaml"
        ).read_text()
        cls.application = (
            ROOT / "argocd/applications/platform-test.yaml"
        ).read_text()

    def test_dispatch_path_has_no_direct_workload_mutation(self):
        forbidden = re.compile(r"kubectl\s+(set\s+image|patch|edit)")
        for source in (
            self.promote,
            self.verify,
            self.reconcile,
            self.runtime,
        ):
            self.assertIsNone(forbidden.search(source))

    def test_promotion_is_full_map_app_identity_and_reviewable_pr(self):
        self.assertIn("backend-testai-digest-contract.py normalize", self.promote)
        self.assertIn("AUTOMATION_APP_ID", self.promote)
        self.assertIn(
            "actions/create-github-app-token@d72941d797fd3113feb6b93fd0dec494b13a2547",
            self.promote,
        )
        self.assertIn("sync-test-overlay.sh", self.promote)
        self.assertIn("gh pr create", self.sync)
        self.assertIn('BRANCH="auto-test-overlay/backend-testai"', self.sync)
        self.assertIn("before runtime mutation", self.sync)

    def test_promotion_and_verification_share_serial_concurrency(self):
        marker = "group: testai-backend-promotion"
        self.assertIn(marker, self.promote)
        self.assertIn(marker, self.verify)
        self.assertIn("cancel-in-progress: false", self.promote)
        self.assertIn("cancel-in-progress: false", self.verify)

    def test_verification_observes_argocd_auto_sync_without_mutation(self):
        self.assertIn("reconcile-testai-backend-sequential.sh", self.verify)
        self.assertNotRegex(self.reconcile, r"\bapp\s+sync\b")
        self.assertNotIn("--resource", self.reconcile)
        self.assertNotIn("--apply-out-of-sync-only", self.reconcile)
        self.assertIn("argocd-auto-sync-waves", self.reconcile)
        self.assertIn("read-only-exact-convergence", self.reconcile)
        self.assertIn('observed_revision" == "$REVISION"', self.reconcile)
        self.assertIn('REQUIRED_STABLE_POLLS="${REQUIRED_STABLE_POLLS:-2}"', self.reconcile)
        self.assertIn("git fetch origin main --depth=1 --quiet", self.reconcile)
        self.assertIn('OUT_OF_SYNC_GRACE="${OUT_OF_SYNC_GRACE:-60}"', self.reconcile)
        self.assertIn('REQUIRED_DRIFT_POLLS="${REQUIRED_DRIFT_POLLS:-3}"', self.reconcile)
        self.assertIn('HARD_REFRESH_INTERVAL="${HARD_REFRESH_INTERVAL:-60}"', self.reconcile)
        self.assertEqual(
            1,
            self.reconcile.count('app get "$APP" --hard-refresh -o json'),
        )
        self.assertIn('app get "$APP" -o json', self.reconcile)
        self.assertIn("drift_polls >= REQUIRED_DRIFT_POLLS", self.reconcile)
        self.assertIn('CURRENT_PHASE="argocd-resource-drift"', self.reconcile)
        self.assertIn("outOfSyncResources", self.reconcile)
        self.assertIn("resource-identifiers-only-no-manifest-diff", self.reconcile)
        self.assertIn('select(.status == "OutOfSync")', self.reconcile)
        self.assertIn("[redacted-sensitive-resource-name]", self.reconcile)
        self.assertIn('CURRENT_PHASE="argocd-status-read"', self.reconcile)
        self.assertNotIn("app diff", self.reconcile)
        self.assertIn("verify-testai-backend-runtime.sh", self.verify)
        self.assertIn("verify-pod-digest.sh", self.runtime)

    def test_platform_test_application_keeps_main_auto_sync_authority(self):
        self.assertRegex(self.application, r"(?m)^\s+targetRevision: main$")
        self.assertRegex(self.application, r"(?m)^\s+automated:$")
        self.assertRegex(self.application, r"(?m)^\s+selfHeal: true$")
        self.assertNotIn("SkipHooks=true", self.application)

    def test_backend_sync_waves_are_complete_unique_and_dependency_ordered(self):
        wave_patches = re.findall(
            r"- target:\n"
            r"\s+kind: Deployment\n"
            r"\s+name: ([a-z0-9-]+)\n"
            r"\s+patch: \|-\n"
            r"\s+apiVersion: apps/v1\n"
            r"\s+kind: Deployment\n"
            r"\s+metadata:\n"
            r"\s+name: [a-z0-9-]+\n"
            r"\s+annotations:\n"
            r"\s+argocd\.argoproj\.io/sync-wave: \"([0-9]+)\"",
            self.overlay,
        )
        expected = {
            "auth-service": "10",
            "permission-service": "11",
            "user-service": "12",
            "variant-service": "13",
            "core-data-service": "14",
            "report-service": "15",
            "schema-service": "16",
            "endpoint-admin-service": "17",
            "audio-gateway": "18",
            "meeting-service": "19",
            "transcript-service": "20",
            "audit-event-consumer-service": "21",
            "api-gateway": "22",
        }
        self.assertEqual(expected, dict(wave_patches))
        self.assertEqual(len(expected), len({wave for _, wave in wave_patches}))
        self.assertEqual("22", dict(wave_patches)["api-gateway"])

    def test_ci_checks_the_rendered_wave_contract(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("verify-backend-sync-wave-render.py /tmp/test.yaml", ci)

    def test_argocd_cli_bootstrap_is_version_and_checksum_pinned(self):
        self.assertIn('EXPECTED_VERSION="v2.13.1"', self.bootstrap)
        self.assertIn(
            "8e436f0429d2a88b3181d2cfc460c034070e0ee1c665467271e5d75eb4d55f7f",
            self.bootstrap,
        )
        self.assertIn("actual_sha256", self.bootstrap)
        self.assertIn("--proto '=https'", self.bootstrap)
        self.assertIn("--tlsv1.2", self.bootstrap)
        self.assertIn("ensure-argocd-cli.sh", self.reconcile)

    def test_new_actions_are_pinned_by_full_commit_sha(self):
        self.assertNotRegex(self.promote, r"uses:\s+[^\s]+@v\d+")
        self.assertNotRegex(self.verify, r"uses:\s+[^\s]+@v\d+")


if __name__ == "__main__":
    unittest.main()
