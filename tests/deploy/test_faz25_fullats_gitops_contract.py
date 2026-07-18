from __future__ import annotations

import json
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
        cls.fullats_browser = (
            ROOT / "scripts/ats/fullats-live-browser-acceptance.cjs"
        ).read_text()
        cls.fullats_axe_evidence = (
            ROOT / "scripts/ats/fullats-axe-evidence.cjs"
        )
        cls.pg_bootstrap = (ROOT / "scripts/ats/provision-test-pg-vault.sh").read_text()
        cls.governance_transition_path = (
            ROOT / "scripts/ats/transition-test-model-governance.sh"
        )
        cls.governance_transition = cls.governance_transition_path.read_text()
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

    def test_model_governance_endpoint_and_approval_refs_match_all_surfaces(self):
        patterns = {
            "activation_endpoint": (
                self.activation,
                r"path: /data/ATS_AI_ENDPOINT_REF\s+value: \"([^\"]+)\"",
            ),
            "workflow_endpoint": (
                self.recovery_workflow,
                r"EXPECTED_ATS_ENDPOINT_REF: ([^\s]+)",
            ),
            "script_endpoint": (
                self.governance_transition,
                r'ENDPOINT_REF="([^"]+)"',
            ),
            "activation_approval": (
                self.activation,
                r"path: /data/ATS_AI_APPROVAL_TRANSCRIBE_REF\s+value: \"([^\"]+)\"",
            ),
            "workflow_approval": (
                self.recovery_workflow,
                r"EXPECTED_ATS_APPROVAL_REF: ([^\s]+)",
            ),
            "script_approval": (
                self.governance_transition,
                r'APPROVAL_REF="([^"]+)"',
            ),
        }
        values = {}
        for name, (text, pattern) in patterns.items():
            match = re.search(pattern, text)
            self.assertIsNotNone(match, name)
            values[name] = match.group(1)
        self.assertEqual(
            {values[name] for name in values if name.endswith("_endpoint")},
            {"faz24-stt-prod"},
        )
        self.assertEqual(
            {values[name] for name in values if name.endswith("_approval")},
            {"mapr_04cabd439b5b51992e86e215b9796f64d27b91dd951acdf542ab6635d517fc43"},
        )

    def test_ats_activation_is_argo_root_managed_without_stub_workload(self):
        self.assertRegex(
            self.test_root,
            r"(?m)^\s*-\s+activation/ats-interview-evidence\s*$",
        )
        self.assertNotRegex(self.activation, r"(?m)^\s*-\s+ai-stub\.yaml\s*$")
        self.assertNotIn("ats-ai-stub", self.rendered_activation)
        self.assertIn("ATS_AI_ENDPOINT_REF: faz24-stt-prod", self.rendered_activation)
        self.assertIn(
            "ATS_AI_APPROVAL_TRANSCRIBE_REF: "
            "mapr_04cabd439b5b51992e86e215b9796f64d27b91dd951acdf542ab6635d517fc43",
            self.rendered_activation,
        )
        self.assertNotIn("ATS_AI_ENDPOINT_REF: OVERLAY_MUST_OVERRIDE", self.rendered_activation)
        self.assertNotIn(
            "ATS_AI_APPROVAL_TRANSCRIBE_REF: OVERLAY_MUST_OVERRIDE",
            self.rendered_activation,
        )

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

    def test_keycloak_tenant_attribute_is_managed_admin_only_before_user_writes(self):
        profile_guard = self.keycloak.index(
            "ensure_tenant_user_profile_attribute\n"
        )
        first_tenant_write = self.keycloak.index('set_tenant "$ADMIN_UID"')
        self.assertLess(profile_guard, first_tenant_write)
        self.assertIn('kc get users/profile -r "$REALM"', self.keycloak)
        self.assertIn(
            "/opt/keycloak/bin/kcadm.sh update users/profile",
            self.keycloak,
        )
        self.assertIn('"permissions":{"view":["admin"],"edit":["admin"]}', self.keycloak)
        self.assertIn('"multivalued":False', self.keycloak)
        self.assertIn('if len(matches)>1:', self.keycloak)
        self.assertIn('admin_config="/tmp/kcadm-ats-profile-$$-$RANDOM.config"', self.keycloak)
        self.assertIn('profile_payload="/tmp/ats-user-profile-$$-$RANDOM.json"', self.keycloak)
        self.assertIn("umask 077", self.keycloak)
        self.assertIn('cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"', self.keycloak)
        self.assertIn('KC_CLI_PASSWORD', self.keycloak)
        self.assertIn('KC_CLI_CLIENT_SECRET', self.keycloak)
        self.assertIn('--config "$KCADM_CONFIG"', self.keycloak)
        self.assertIn('trap \'docker exec "$KC" rm -f "$admin_config"', self.keycloak)
        self.assertNotIn("admin_pass=", self.keycloak)
        self.assertNotIn("--password", self.keycloak)
        self.assertNotIn('--secret "$KCSEC"', self.keycloak)
        self.assertIn('update "users/$1" -r "$REALM" -f - --merge', self.keycloak)
        self.assertNotIn(
            '-s "attributes.ats_tenant=[\\"$2\\"]"',
            self.keycloak,
        )

    def test_fullats_smoke_enforces_cross_tenant_write_and_exact_counter(self):
        self.assertIn('-X PUT --data-binary @"$T/other-s1"', self.fullats_smoke)
        self.assertIn('[ "$C" = 404 ]', self.fullats_smoke)
        self.assertIn('SONUC: $N/10 PASS', self.fullats_smoke)
        self.assertIn('[ "$N" -eq 10 ]', self.fullats_smoke)
        self.assertIn("status `PUT` 404", self.runbook)
        self.assertIn("`10/10 PASS`", self.runbook)

    def test_fullats_browser_failure_evidence_is_actionable_and_redacted(self):
        node_script = r"""
const { compactAxeViolations } = require(process.argv[1]);
const nodes = Array.from({ length: 7 }, () => ({
  target: [
    'div#ahmet > span.candidate-ahmet.text-state-success-text.bg-state-success-bg[aria-label="Ahmet Yilmaz +905551112233 ahmet@example.test app_abcdefghijklmnopqrstuvwx"]',
  ],
  any: [{
    id: 'color-contrast',
    data: {
      fgColor: '#008c3a', bgColor: '#e7f4ed', contrastRatio: 3.85,
      expectedContrastRatio: '4.5:1', fontSize: '12px', fontWeight: '700',
      unsafe: 'Ahmet Yilmaz +905551112233 ahmet@example.test',
    },
    message: 'Ahmet Yilmaz +905551112233 ahmet@example.test',
  }],
  all: [], none: [],
  html: '<span>Ahmet Yilmaz ahmet@example.test</span>',
  failureSummary: 'Ahmet Yilmaz +905551112233 ahmet@example.test',
}));
process.stdout.write(JSON.stringify(compactAxeViolations([
  { id: 'color-contrast', impact: 'serious', nodes },
])));
"""
        completed = subprocess.run(
            ["node", "-e", node_script, str(self.fullats_axe_evidence)],
            check=True,
            capture_output=True,
            text=True,
        )
        evidence = json.loads(completed.stdout)
        serialized = completed.stdout
        self.assertEqual(evidence[0]["nodes"], 7)
        self.assertEqual(len(evidence[0]["sampledNodes"]), 5)
        self.assertEqual(evidence[0]["omittedNodes"], 2)
        self.assertIn(
            "text-state-success-text",
            evidence[0]["sampledNodes"][0]["target"][0]["classes"],
        )
        self.assertEqual(
            evidence[0]["sampledNodes"][0]["contrast"]["contrastRatio"],
            3.85,
        )
        for forbidden in (
            "Ahmet",
            "Yilmaz",
            "+905551112233",
            "ahmet@example.test",
            "app_abcdefghijklmnopqrstuvwx",
            "candidate-ahmet",
            "<span>",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("node.html", self.fullats_browser)

    def test_fullats_browser_scans_recruiter_before_and_after_terminal_transition(self):
        initial_scan = self.fullats_browser.index(
            "await assertAxeClean(recruiterPage, 'recruiter-workspace-desktop')"
        )
        terminal_response_wait = self.fullats_browser.index(
            "const terminalTransitionResponse = recruiterPage.waitForResponse("
        )
        terminal_transition_click = self.fullats_browser.index(
            "await reviewPanel.getByRole('button', "
            "{ name: 'Mülakat planlamasına al' }).click();"
        )
        terminal_response = self.fullats_browser.index(
            "const terminalResponse = await terminalTransitionResponse;"
        )
        terminal_status = self.fullats_browser.index(
            "await waitVisible(terminalStatus, 'interview pending terminal status')"
        )
        terminal_scan = self.fullats_browser.index(
            "await assertAxeClean(recruiterPage, "
            "'recruiter-workspace-terminal-desktop')"
        )
        candidate_terminal_refresh = self.fullats_browser.index(
            "const interviewStep = candidatePage.getByRole('listitem')"
        )
        self.assertLess(initial_scan, terminal_response_wait)
        self.assertLess(terminal_response_wait, terminal_transition_click)
        self.assertLess(terminal_transition_click, terminal_response)
        self.assertLess(terminal_response, terminal_status)
        self.assertLess(terminal_status, terminal_scan)
        self.assertLess(terminal_scan, candidate_terminal_refresh)
        self.assertIn(
            "relevantPath(response.url()) === "
            "`/api/ats/v1/recruiter/applications/${publicRef}/status`",
            self.fullats_browser,
        )
        self.assertIn("terminalResponse.status() !== 200", self.fullats_browser)
        self.assertIn(
            "(await terminalStatus.textContent())?.trim() !== "
            "'Mülakat planlaması bekleniyor.'",
            self.fullats_browser,
        )
        self.assertIn(
            "await assertNoHorizontalOverflow(recruiterPage, "
            "'recruiter-workspace-terminal-desktop')",
            self.fullats_browser,
        )

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

    def test_model_governance_transition_is_digest_bound_secret_safe_and_compensated(self):
        script = self.governance_transition
        self.assertTrue(self.governance_transition_path.stat().st_mode & 0o100)
        self.assertIn("canonical activation digest", script)
        self.assertIn("live GitOps deployment image", script)
        self.assertIn("ATS_AI_ENDPOINT_REF", script)
        self.assertIn("ATS_AI_APPROVAL_TRANSCRIBE_REF", script)
        self.assertIn("live GitOps endpoint/approval binding", script)
        self.assertGreaterEqual(script.count("assert_live_gitops_binding"), 4)
        self.assertIn("flock -n 9", script)
        self.assertIn("stale ephemeral governance operator role", script)
        self.assertIn("current_setting('log_statement')", script)
        self.assertIn("current_setting('log_min_duration_statement')", script)
        self.assertIn("current_setting('pgaudit.log',true)", script)
        self.assertIn("PostgreSQL statement logging could retain", script)
        self.assertIn("SET LOCAL log_min_error_statement = 'PANIC'", script)
        self.assertIn('CREATE ROLE "${OPERATOR_ROLE}" LOGIN PASSWORD', script)
        self.assertIn(
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
            script,
        )
        self.assertIn('GRANT ats_governance_writer TO "${OPERATOR_ROLE}"', script)
        self.assertIn('REVOKE ats_governance_writer FROM "${OPERATOR_ROLE}"', script)
        self.assertIn('DROP ROLE "${OPERATOR_ROLE}"', script)
        self.assertIn("for attempt in 1 2 3", script)
        self.assertIn("orphan=${OPERATOR_ROLE}", script)
        self.assertIn("trap 'exit 143' TERM", script)
        self.assertIn("trap 'exit 130' INT", script)
        self.assertIn('--network "container:${PG_CONTAINER}"', script)
        self.assertIn("--read-only", script)
        self.assertIn("--cap-drop=ALL", script)
        self.assertIn("no-new-privileges:true", script)
        self.assertIn("--pull=never", script)
        self.assertIn("printf '{\"jdbcUrl\"", script)
        self.assertNotIn("PGPASSWORD", script)
        self.assertNotRegex(script, r"(?:-e|--env)[^\n]*OPERATOR_PASSWORD")
        self.assertIn("CHECK_MODEL_GOVERNANCE_TRANSITION", script)
        self.assertIn("APPEND_MODEL_GOVERNANCE_TRANSITION", script)
        self.assertIn("mgt_25260000-0000-4000-8000-000000000002", script)
        self.assertIn("cross-ai/faz25/2526", script)
        self.assertIn("verify-model-governance-ledger.py", script)
        self.assertIn(
            "sequence,transition_id,approval_ref,capability,from_status,to_status,"
            "actor_ref,reason_code,entry_hash,previous_hash",
            script,
        )
        self.assertIn('"$APPEND_SEQUENCE" == "1"', script)
        self.assertIn('--append-sequence "$APPEND_SEQUENCE"', script)
        self.assertIn("ats_app role drift detected across governance operation", script)

    def test_fullats_recovery_uses_canonical_self_hosted_runner_without_workload_patch(self):
        self.assertIn("workflow_dispatch:", self.recovery_workflow)
        self.assertIn("Only verify exact Argo revision, image/config binding", self.recovery_workflow)
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
        self.assertIn('ARGOCD_APPLICATION: platform-test', self.recovery_workflow)
        self.assertIn('"$argo_revision" == "$GITHUB_SHA"', self.recovery_workflow)
        self.assertIn('"$ats_deployment_sync" == "Synced"', self.recovery_workflow)
        self.assertIn('"$ats_configmap_sync" == "Synced"', self.recovery_workflow)
        loop_start = self.recovery_workflow.index("for _ in $(seq 1 60); do")
        argo_read = self.recovery_workflow.index('argo_state="$(kubectl', loop_start)
        for reset in ('argo_revision=""', 'ats_deployment_sync=""', 'ats_configmap_sync=""'):
            self.assertLess(self.recovery_workflow.index(reset, loop_start), argo_read)
        self.assertIn('.group == "apps" and .kind == "Deployment"', self.recovery_workflow)
        self.assertIn('(.group // "") == "" and .kind == "ConfigMap"', self.recovery_workflow)
        self.assertNotIn('"$argo_sync" == "Synced"', self.recovery_workflow)
        self.assertIn("ATS_AI_ENDPOINT_REF", self.recovery_workflow)
        self.assertIn("ATS_AI_APPROVAL_TRANSCRIBE_REF", self.recovery_workflow)
        self.assertIn("live ConfigMap endpoint/approval refs", self.recovery_workflow)
        self.assertIn("exact ATS Deployment/ConfigMap at the workflow commit", self.recovery_workflow)
        self.assertIn('.name == "app-boot" and .ready == true', self.recovery_workflow)
        self.assertIn("ATS rollout timeout after 600s", self.recovery_workflow)
        self.assertIn('"restartCount="', self.recovery_workflow)
        self.assertIn(".state.waiting.reason", self.recovery_workflow)
        self.assertIn(".state.terminated.reason", self.recovery_workflow)
        self.assertIn(".state.terminated.exitCode", self.recovery_workflow)
        self.assertIn("involvedObject.kind=Pod", self.recovery_workflow)
        self.assertNotIn("kubectl logs", self.recovery_workflow)
        self.assertIn("$'4|t\\n5|t\\n6|t'", self.recovery_workflow)
        self.assertIn(
            "bash scripts/ats/transition-test-model-governance.sh",
            self.recovery_workflow,
        )
        self.assertIn("APPEND_FAZ25_TEST_MODEL_GOVERNANCE", self.recovery_workflow)
        self.assertIn("modelGovernanceLedgerReader(DataSource, Flyway)", self.recovery_workflow)
        roles_only = self.recovery_workflow.index(
            "bash scripts/ats/provision-test-pg-vault.sh --roles-only"
        )
        governance_append = self.recovery_workflow.index(
            "bash scripts/ats/transition-test-model-governance.sh"
        )
        ready_wait = self.recovery_workflow.index(
            "Wait for GitOps-owned ATS rollout and verify V4/V5/V6"
        )
        self.assertLess(roles_only, governance_append)
        self.assertLess(governance_append, ready_wait)
        self.assertIn("bash scripts/ats/provision-test-keycloak.sh", self.recovery_workflow)
        self.assertIn("bash scripts/ats/fullats-application-smoke.sh", self.recovery_workflow)
        self.assertIn("faz25-fullats-test-recovery.yml", self.runbook)
        self.assertIn("APPLY_FAZ25_FULLATS_TEST_RECOVERY", self.runbook)
        self.assertIn("exact workflow commit", self.runbook)
        self.assertIn("Overall Application `OutOfSync`", self.runbook)
        self.assertIn("Full acceptance sonunda overall Argo `Synced/Healthy`", self.runbook)
        self.assertIn("pod `CrashLoopBackOff` kalabilir", self.runbook)
        self.assertIn("fixed-id append'i doğrulandıktan sonra boot gate açılır", self.runbook)
        self.assertIn("Faz 25 #2526 desired pin: `f34a761`", self.runbook)
        self.assertIn("canlı D29 pending", self.runbook)
        self.assertIn("aynı exact-main koşumu yeniden dispatch etmek normal ve güvenlidir", self.runbook)
        self.assertIn("WiringConfig.flyway(DataSource)", self.runbook)
        self.assertIn("modelGovernanceLedgerReader(DataSource, Flyway)", self.runbook)
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

    def test_consultation_defaults_to_none_then_single_claude_and_max_two(self):
        rule = "Durumsal Cross-AI istişre — varsayılan az kanal"
        self.assertIn(rule, self.agents)
        self.assertIn("`Consultation mode: none`", self.agents)
        self.assertIn("(`single`)", self.agents)
        self.assertIn("(`dual`)", self.agents)
        self.assertIn("`claude-opus-4-8`", self.agents)
        self.assertIn("`minimax/MiniMax-M3`", self.agents)
        self.assertIn("`gpt-5.6-sol`", self.agents)
        self.assertIn("toplam iki kanal aşılmaz", self.agents)
        self.assertIn("mümkünse paralel", self.agents)
        self.assertIn("Cursor ve AI uygulama pencereleri istişre yolu değildir", self.agents)
        self.assertNotIn(
            "Cursor CLI (öncelikli ilave adversarial-review kanalı)", self.agents
        )
        self.assertIn(
            "## 11. Durumsal Cross-AI İstişre — Varsayılan Az Kanal",
            self.context_rules,
        )
        self.assertIn("**`none` — varsayılan:**", self.context_rules)
        self.assertIn("**`single` — gerçekten ikinci görüş gerektiğinde:**", self.context_rules)
        self.assertIn("**`dual` — istisnai yüksek risk:**", self.context_rules)
        self.assertIn("**`claude-opus-4-8`**", self.context_rules)
        self.assertIn("**`minimax/MiniMax-M3`**", self.context_rules)
        self.assertIn("**`gpt-5.6-sol`**", self.context_rules)
        self.assertIn(
            "İstişre bir teslimat ritüeli değil, yalnız karar",
            self.context_rules,
        )
        self.assertIn("JSON `modelUsage`", self.context_rules)
        self.assertIn("Cursor CLI/MCP/model/harness", self.context_rules)
        self.assertIn("AI uygulama pencereleri istişre kanalı değildir", self.context_rules)
        self.assertIn("`none` receipt", self.context_rules)
        self.assertIn("`dual` yayın sırası zorunlu değildir", self.context_rules)

if __name__ == "__main__":
    unittest.main()
