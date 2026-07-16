from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Faz25FullAtsGitopsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.activation = (
            ROOT
            / "kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml"
        ).read_text()
        cls.test_root = (ROOT / "kustomize/overlays/test/kustomization.yaml").read_text()
        cls.d29 = (ROOT / "scripts/ats/d29-smoke.sh").read_text()
        cls.runbook = (ROOT / "docs/RB-ats-39d-testai.md").read_text()
        cls.rendered_activation = subprocess.run(
            [
                "kustomize",
                "build",
                str(
                    ROOT
                    / "kustomize/overlays/test/activation/ats-interview-evidence"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        cls.keycloak = (ROOT / "scripts/ats/provision-test-keycloak.sh").read_text()
        cls.fullats_smoke = (ROOT / "scripts/ats/fullats-application-smoke.sh").read_text()
        cls.pg_bootstrap = (ROOT / "scripts/ats/provision-test-pg-vault.sh").read_text()
        cls.recovery_workflow = (
            ROOT / ".github/workflows/faz25-fullats-test-recovery.yml"
        ).read_text()
        cls.agents = (ROOT / "AGENTS.md").read_text()
        cls.context_rules = (ROOT / "docs/context-priority-rules.md").read_text()

    def test_d29_default_digest_matches_activated_ats_image(self):
        desired = re.search(
            r"name:\s*ghcr\.io/halildeu/ats-app-boot\s+digest:\s*(sha256:[0-9a-f]{64})",
            self.activation,
        )
        runtime = re.search(
            r'PIN="\$\{ATS_EXPECTED_DIGEST:-(sha256:[0-9a-f]{64})\}"',
            self.d29,
        )
        self.assertIsNotNone(desired)
        self.assertIsNotNone(runtime)
        self.assertEqual(desired.group(1), runtime.group(1))

        provenance = re.search(
            r"(?m)^#\s+digest\s+(sha256:[0-9a-f]{64})\s*$",
            self.activation,
        )
        self.assertIsNotNone(provenance)
        self.assertEqual(desired.group(1), provenance.group(1))

    def test_ats_activation_is_argo_root_managed_without_stub_workload(self):
        self.assertRegex(
            self.test_root,
            r"(?m)^\s*-\s+activation/ats-interview-evidence\s*$",
        )
        self.assertNotRegex(self.activation, r"(?m)^\s*-\s+ai-stub\.yaml\s*$")
        self.assertNotIn("ats-ai-stub", self.rendered_activation)

    def test_prune_false_cleanup_names_every_retired_stub_resource(self):
        for resource in (
            "deployment/ats-ai-stub",
            "service/ats-ai-stub",
            "configmap/ats-ai-stub-script",
            "networkpolicy/ats-ai-stub",
        ):
            with self.subTest(resource=resource):
                self.assertIn(resource, self.runbook)

    def test_keycloak_audience_mapper_check_materializes_before_exact_match(self):
        self.assertIn("if ! MAPPER_NAMES=$(kc get", self.keycloak)
        self.assertIn('grep -Fqx "ats-api-audience-mapper" <<<"$MAPPER_NAMES"', self.keycloak)
        self.assertNotRegex(
            self.keycloak,
            r'if\s+!\s+kc\s+get[^\n]*\|\s*grep\s+[^\n]*ats-api-audience-mapper',
        )
        self.assertIn("if ! TENANT_MAPPER_ROWS=$(kc get", self.keycloak)
        self.assertNotRegex(
            self.keycloak,
            r'TENANT_MAPPER_ID=\$\(kc\s+get[^\n]*',
        )
        self.assertNotIn(
            'kc delete "client-scopes/$AUD_SID/protocol-mappers',
            self.keycloak,
        )
        self.assertIn("tenant mapper post-update", self.keycloak)

    def test_fullats_smoke_enforces_cross_tenant_write_and_exact_counter(self):
        self.assertIn('-X PUT --data-binary @"$T/other-s1"', self.fullats_smoke)
        self.assertIn('[ "$C" = 404 ]', self.fullats_smoke)
        self.assertIn('SONUC: $N/10 PASS', self.fullats_smoke)
        self.assertIn('[ "$N" -eq 10 ]', self.fullats_smoke)
        self.assertIn("status `PUT` 404", self.runbook)
        self.assertIn("`10/10 PASS`", self.runbook)

    def test_pg_writer_role_is_admin_bootstrapped_without_runtime_createrole(self):
        self.assertIn("--roles-only", self.pg_bootstrap)
        self.assertIn("CREATE ROLE ats_governance_writer", self.pg_bootstrap)
        self.assertIn(
            "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
            self.pg_bootstrap,
        )
        self.assertLess(
            self.pg_bootstrap.index("CREATE ROLE ats_governance_writer"),
            self.pg_bootstrap.index("PW=$(openssl rand"),
        )
        self.assertNotRegex(
            self.pg_bootstrap,
            r"ALTER\s+ROLE\s+ats_app[^\n;]*CREATEROLE",
        )
        self.assertIn(
            "rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls",
            self.pg_bootstrap,
        )
        self.assertIn('"t|f|f|f|f|f"', self.pg_bootstrap)
        roles_only = self.pg_bootstrap.index('if [ "$MODE" = "--roles-only" ]')
        roles_only_assert = self.pg_bootstrap.index("assert_ats_app_role", roles_only)
        roles_only_exit = self.pg_bootstrap.index("exit 0", roles_only_assert)
        self.assertLess(roles_only_assert, roles_only_exit)
        self.assertLess(roles_only_exit, self.pg_bootstrap.index("PW=$(openssl rand"))
        self.assertLess(roles_only_exit, self.pg_bootstrap.index("VAULT_TOKEN"))
        self.assertIn("roles-only recovery OK (DB password/Vault degismedi)", self.pg_bootstrap)
        self.assertIn("guvensiz role attribute tasiyor", self.runbook)
        self.assertIn("Halildeu/ats#176", self.runbook)
        self.assertIn("test `ats` veritabanı/şema/tablolarının sahibidir", self.runbook)

    def test_fullats_recovery_uses_canonical_self_hosted_runner_without_workload_patch(self):
        self.assertIn("workflow_dispatch:", self.recovery_workflow)
        self.assertIn('"refs/heads/main"', self.recovery_workflow)
        self.assertIn("APPLY_FAZ25_FULLATS_TEST_RECOVERY", self.recovery_workflow)
        self.assertIn("[self-hosted, staging-sw, testai-deploy]", self.recovery_workflow)
        self.assertIn(
            "bash scripts/ats/provision-test-pg-vault.sh --roles-only",
            self.recovery_workflow,
        )
        self.assertIn("WHERE success = false", self.recovery_workflow)
        self.assertIn("no automatic repair", self.recovery_workflow)
        self.assertIn("CONFIRM_INPUT: ${{ inputs.confirm }}", self.recovery_workflow)
        self.assertIn('"$CONFIRM_INPUT"', self.recovery_workflow)
        self.assertNotIn('"${{ inputs.confirm }}"', self.recovery_workflow)
        self.assertIn('@.name=="app-boot"', self.recovery_workflow)
        self.assertIn('.name == "app-boot" and .ready == true', self.recovery_workflow)
        self.assertIn("$'4|t\\n5|t'", self.recovery_workflow)
        self.assertIn("bash scripts/ats/provision-test-keycloak.sh", self.recovery_workflow)
        self.assertIn("bash scripts/ats/fullats-application-smoke.sh", self.recovery_workflow)
        self.assertIn("faz25-fullats-test-recovery.yml", self.runbook)
        self.assertIn("APPLY_FAZ25_FULLATS_TEST_RECOVERY", self.runbook)
        self.assertNotRegex(
            self.recovery_workflow,
            r"kubectl\s+(?:--[^\s]+\s+)*\b(?:patch|edit|delete|rollout restart|set image)\b",
        )

        desired = re.search(
            r"name:\s*ghcr\.io/halildeu/ats-app-boot\s+digest:\s*(sha256:[0-9a-f]{64})",
            self.activation,
        )
        workflow = re.search(
            r"EXPECTED_ATS_DIGEST:\s*(sha256:[0-9a-f]{64})",
            self.recovery_workflow,
        )
        runtime = re.search(
            r'PIN="\$\{ATS_EXPECTED_DIGEST:-(sha256:[0-9a-f]{64})\}"',
            self.d29,
        )
        self.assertIsNotNone(desired)
        self.assertIsNotNone(workflow)
        self.assertIsNotNone(runtime)
        self.assertEqual(desired.group(1), workflow.group(1))
        self.assertEqual(workflow.group(1), runtime.group(1))

    def test_direct_claude_is_machine_pinned_as_first_consultation_channel(self):
        direct = "Doğrudan Claude CLI birinci istişare kanalı (KALICI)"
        cursor = "Cursor CLI (öncelikli ilave adversarial-review kanalı)"
        self.assertIn(direct, self.agents)
        self.assertIn(cursor, self.agents)
        self.assertLess(self.agents.index(direct), self.agents.index(cursor))
        self.assertIn("**Kalıcı sıra:** birinci dış istişare kanalı", self.context_rules)
        self.assertIn("Cursor CLI bundan sonra bağımsız/ilave", self.context_rules)
        self.assertNotIn("Doğrudan Claude CLI ek/fallback", self.context_rules)
        self.assertNotIn("Doğrudan Claude CLI ek/fallback", self.agents)
        self.assertNotIn("Doğrudan Claude, MiniMax M3", self.context_rules)
        self.assertIn("--model claude-opus-4-8", self.agents)
        self.assertIn("`claude-opus-4-8` dönmeden", self.context_rules)
        self.assertIn("daha düşük modele sessiz fallback yapılmaz", self.agents)

if __name__ == "__main__":
    unittest.main()
