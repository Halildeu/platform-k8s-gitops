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
        cls.overlay = (ROOT / "kustomize/overlays/test/kustomization.yaml").read_text()
        cls.preflight = (
            ROOT / "scripts/deploy/preflight-testai-frontend-rollout.sh"
        ).read_text()
        cls.image_availability = (
            ROOT / "scripts/deploy/check-testai-frontend-image-availability.sh"
        ).read_text()
        cls.runtime_verifier = (
            ROOT / "scripts/deploy/verify-testai-frontend-runtime.sh"
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
        self.assertIn(
            'BRANCH="auto-test-frontend/testai-${SHORT_SHA}-${RUN_ID}-${RUN_ATTEMPT}"',
            self.sync,
        )

    def test_promotion_branch_is_append_only_under_rulesets(self):
        self.assertIn("RUN_ATTEMPT", self.promote)
        self.assertIn('git push origin "HEAD:${BRANCH}"', self.sync)
        self.assertNotIn("git push --force", self.sync)

    def test_pr_body_markdown_cannot_execute_shell_commands(self):
        # Markdown backticks inside an unquoted heredoc are command
        # substitutions. The generated-by line then recursively executes the
        # sync script. Pin the quoted-template boundary that prevents it.
        self.assertIn("BODY=$(cat <<'EOF'", self.sync)
        self.assertIn("BODY=${BODY//__SOURCE_SHA__/$SHA}", self.sync)
        self.assertNotIn("BODY=$(cat <<EOF", self.sync)

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
        self.assertIn("frontend image/rollout contract", self.verify)

    def test_cluster_and_public_verification_keep_explicit_trust_boundaries(self):
        self.assertIn("runs-on: [self-hosted, aiserver, testai-deploy]", self.verify)
        self.assertNotIn("runs-on: ubuntu-24.04", self.verify)
        self.assertIn("--cluster-only", self.verify)
        self.assertNotIn("--public-only", self.verify)
        self.assertIn("--public-only", self.runtime_verifier)
        self.assertIn(
            "public WG/corporate browser route: separate acceptance gate",
            self.verify,
        )
        self.assertIn(
            "cluster-only and public-only are mutually exclusive",
            self.runtime_verifier,
        )
        self.assertIn("--connect-timeout 10 --max-time 30", self.runtime_verifier)

    def test_live_quota_preflight_runs_immediately_before_argocd(self):
        preflight = "bash scripts/deploy/preflight-testai-frontend-rollout.sh"
        sync = "bash scripts/faz22/sync-platform-test-gitops.sh"
        self.assertIn(preflight, self.verify)
        self.assertLess(self.verify.index(preflight), self.verify.index(sync))
        between = self.verify[self.verify.index(preflight) : self.verify.index(sync)]
        self.assertNotRegex(
            between, r"kubectl\s+(apply|patch|edit|replace|set\s+image)"
        )

    def test_image_availability_preflight_runs_before_argocd_mutation(self):
        """gitops#2885: kota headroom'u yetmez — imaj çekilebilir olmalı.

        Node cache MISS + registry erişilemez ise ArgoCD mutasyonu
        ImagePullBackOff üretir; eski pod cache'ten ayakta kaldığı için hata
        SESSİZ geçer (PR yeşil, merge OK, kullanıcı eski UI'ı görür).
        """
        checker = "check-testai-frontend-image-availability.sh"
        self.assertIn(checker, self.preflight)
        # Argo mutasyonundan önce: preflight zincirinin içinde, sync'ten önce koşar.
        preflight_call = "bash scripts/deploy/preflight-testai-frontend-rollout.sh"
        sync = "bash scripts/faz22/sync-platform-test-gitops.sh"
        self.assertLess(self.verify.index(preflight_call), self.verify.index(sync))
        # Headroom hesabından ÖNCE — pahalı kontrolden önce fail-closed.
        self.assertLess(
            self.preflight.index(checker),
            self.preflight.index("check-testai-frontend-rollout-headroom.py"),
        )
        # Digest-pin zorunlu; tag-only pin reddedilir (D30 immutable artifact).
        self.assertIn("is not digest-pinned", self.image_availability)
        # İki yol da başarısızsa fail-closed (exit 1), sessiz geçiş yok.
        self.assertIn("NOT retrievable", self.image_availability)
        self.assertRegex(self.image_availability, r"exit 1\s*$")
        # Credential asla loglanmaz.
        self.assertNotRegex(self.image_availability, r"echo[^\n]*\$\{?basic_auth")
        self.assertNotRegex(self.image_availability, r"echo[^\n]*\$\{?token")
        self.assertIn('basic_auth=""', self.image_availability)
        self.assertIn('token=""', self.image_availability)

    def test_test_frontend_rollout_keeps_the_ready_pod(self):
        frontend_patch = re.search(
            r"name: frontend\n\s+patch: \|-\n(?P<body>.*?)(?=\n\s+# 2026-04-29)",
            self.overlay,
            re.DOTALL,
        )
        self.assertIsNotNone(frontend_patch)
        body = frontend_patch.group("body")
        self.assertRegex(body, r"maxSurge\n\s+value: 1")
        self.assertRegex(body, r"maxUnavailable\n\s+value: 0")
        self.assertRegex(body, r"progressDeadlineSeconds\n\s+value: 300")

    def test_new_actions_are_pinned_by_full_commit_sha(self):
        self.assertNotRegex(self.promote, r"uses:\s+[^\s]+@v\d+")
        self.assertNotRegex(self.verify, r"uses:\s+[^\s]+@v\d+")


if __name__ == "__main__":
    unittest.main()
