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
