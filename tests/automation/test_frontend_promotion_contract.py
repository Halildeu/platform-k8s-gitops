from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FrontendPromotionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.promote = (ROOT / ".github/workflows/deploy-testai.yml").read_text()
        cls.verify = (
            ROOT / ".github/workflows/verify-testai-frontend-rollout.yml"
        ).read_text()
        cls.sync = (
            ROOT / "scripts/automation/sync-test-overlay-frontend.sh"
        ).read_text()
        cls.diff_guard = (
            ROOT / "scripts/automation/validate-test-overlay-frontend-diff.sh"
        ).read_text()

    def test_dispatch_path_has_no_direct_workload_mutation(self):
        forbidden = re.compile(r"kubectl\s+(set\s+image|patch|edit)")
        self.assertIsNone(forbidden.search(self.promote))
        self.assertIsNone(forbidden.search(self.verify))

    def test_promotion_requires_app_identity_and_reviewable_pr(self):
        self.assertIn("AUTOMATION_APP_ID", self.promote)
        self.assertIn(
            "actions/create-github-app-token@d72941d797fd3113feb6b93fd0dec494b13a2547",
            self.promote,
        )
        self.assertIn("sync-test-overlay-frontend.sh", self.promote)
        self.assertIn("validate-test-overlay-frontend-diff.sh", self.sync)
        self.assertIn("gh pr create", self.sync)
        self.assertIn('BRANCH="auto-test-frontend/testai"', self.sync)

    def test_promotion_and_verification_share_serial_concurrency(self):
        marker = "group: testai-frontend-promotion"
        self.assertIn(marker, self.promote)
        self.assertIn(marker, self.verify)
        self.assertIn("cancel-in-progress: false", self.promote)
        self.assertIn("cancel-in-progress: false", self.verify)

    def test_verification_is_gitops_only_and_exact_lineage_aware(self):
        self.assertIn("sync-platform-test-gitops.sh", self.verify)
        self.assertIn('ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK: "false"', self.verify)
        self.assertIn("verify-testai-frontend-runtime.sh", self.verify)
        self.assertIn("--expected-sha", self.verify)
        self.assertIn("sourceRevision", self.verify)

    def test_new_actions_are_pinned_by_full_commit_sha(self):
        self.assertNotRegex(self.promote, r"uses:\s+[^\s]+@v\d+")
        self.assertNotRegex(self.verify, r"uses:\s+[^\s]+@v\d+")


if __name__ == "__main__":
    unittest.main()
