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
        cls.runtime = (
            ROOT / "scripts/deploy/verify-testai-backend-runtime.sh"
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

    def test_verification_is_sequential_argocd_only(self):
        self.assertIn("reconcile-testai-backend-sequential.sh", self.verify)
        self.assertIn("--resource \"apps:Deployment:${deployment}\"", self.reconcile)
        self.assertIn("--apply-out-of-sync-only", self.reconcile)
        self.assertIn('--revision "$REVISION"', self.reconcile)
        self.assertIn('app wait "$APP"', self.reconcile)
        self.assertIn('observed_revision" == "$REVISION"', self.reconcile)
        self.assertIn("verify-testai-backend-runtime.sh", self.verify)
        self.assertIn("verify-pod-digest.sh", self.runtime)

    def test_new_actions_are_pinned_by_full_commit_sha(self):
        self.assertNotRegex(self.promote, r"uses:\s+[^\s]+@v\d+")
        self.assertNotRegex(self.verify, r"uses:\s+[^\s]+@v\d+")


if __name__ == "__main__":
    unittest.main()
