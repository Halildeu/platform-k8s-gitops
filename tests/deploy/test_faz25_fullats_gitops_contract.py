from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import textwrap
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
        cls.ats_config = (
            ROOT / "kustomize/base/apps/ats-interview-evidence/configmap.yaml"
        ).read_text()
        cls.ats_config_sha256 = hashlib.sha256(
            (
                ROOT / "kustomize/base/apps/ats-interview-evidence/configmap.yaml"
            ).read_bytes()
        ).hexdigest()
        cls.ats_deployment = (
            ROOT / "kustomize/base/apps/ats-interview-evidence/deployment.yaml"
        ).read_text()
        cls.ats_netpol = (
            ROOT
            / "kustomize/overlays/test/activation/ats-interview-evidence/netpol.yaml"
        ).read_text()
        cls.test_root = (ROOT / "kustomize/overlays/test/kustomization.yaml").read_text()
        cls.frontend_pin = json.loads(
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts/automation/test-overlay-frontend-image.py"),
                    "inspect",
                    "--kustomization",
                    str(ROOT / "kustomize/overlays/test/kustomization.yaml"),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        cls.test_frontend_nginx = (
            ROOT / "kustomize/overlays/test/frontend-nginx-default.conf"
        ).read_text()
        cls.promotion_state = (
            ROOT / "kustomize/overlays/test/fullats-promotion-state.txt"
        ).read_text().strip()
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
        cls.rendered_test_root = subprocess.run(
            ["kustomize", "build", str(ROOT / "kustomize/overlays/test")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        cls.keycloak = (ROOT / "scripts/ats/provision-test-keycloak.sh").read_text()
        cls.fullats_smoke = (ROOT / "scripts/ats/fullats-application-smoke.sh").read_text()
        cls.fullats_browser = (
            ROOT / "scripts/ats/fullats-live-browser-acceptance.cjs"
        ).read_text()
        cls.fullats_browser_shell = (
            ROOT / "scripts/ats/fullats-live-browser-acceptance.sh"
        ).read_text()
        cls.fullats_browser_workflow = (
            ROOT / ".github/workflows/faz25-fullats-live-browser-acceptance.yml"
        ).read_text()
        cls.fullats_runtime = (
            ROOT / "scripts/ats/verify-fullats-live-runtime.sh"
        ).read_text()
        cls.testai_reconcile = (
            ROOT / "scripts/deploy/reconcile-testai-backend-sequential.sh"
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
        cls.rollback_script = (
            ROOT / "scripts/ats/open-fullats-test-rollback-pr.sh"
        ).read_text()
        cls.pinned_gh_installer = (
            ROOT / "scripts/ats/install-pinned-gh-cli.sh"
        ).read_text()
        cls.pinned_kustomize_installer = (
            ROOT / "scripts/ats/install-pinned-kustomize.sh"
        ).read_text()
        cls.rollback_content_verifier = (
            ROOT / "scripts/ats/verify-fullats-test-rollback-content.sh"
        ).read_text()
        cls.cross_ai_workflow = (
            ROOT / ".github/workflows/gate-cross-ai-audit.yml"
        ).read_text()
        cls.cross_ai_audit = (ROOT / "scripts/ci/pr-cross-ai-audit.mjs").read_text()
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

    def test_recruiter_authz_uses_canonical_internal_projection_with_narrow_network_path(self):
        self.assertIn(
            'ATS_AUTHORIZATION_PLATFORM_BASE_URL: "http://api-gateway:8080"',
            self.ats_config,
        )
        self.assertIn(
            "name: api-gateway-authz-from-ats-interview-evidence",
            self.ats_netpol,
        )
        self.assertIn("app: ats-interview-evidence", self.ats_netpol)
        self.assertIn("app.kubernetes.io/name: api-gateway", self.ats_netpol)
        self.assertIn("port: 8080", self.ats_netpol)
        self.assertIn(
            "ATS_AUTHORIZATION_PLATFORM_BASE_URL: http://api-gateway:8080",
            self.rendered_test_root,
        )
        self.assertEqual(
            self.rendered_test_root.count(
                "name: api-gateway-authz-from-ats-interview-evidence"
            ),
            1,
        )

    def test_ats_configmap_bytes_are_bound_to_pod_template_rollout(self):
        annotation = (
            'fullats.acik.com/configmap-sha256: "'
            f'{self.ats_config_sha256}"'
        )
        self.assertIn(annotation, self.ats_deployment)
        rendered_annotation = re.search(
            r"(?m)^\s*fullats\.acik\.com/configmap-sha256:\s*\"?"
            r"([0-9a-f]{64})\"?\s*$",
            self.rendered_test_root,
        )
        self.assertIsNotNone(rendered_annotation)
        self.assertEqual(rendered_annotation.group(1), self.ats_config_sha256)

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
        self.assertIn(
            "FULLATS_PUBLIC_TENANT_ID='00000000-0000-0000-0000-000000000001'",
            self.keycloak,
        )
        self.assertIn(
            'set_tenant "$ADMIN_UID" "$FULLATS_PUBLIC_TENANT_ID"',
            self.keycloak,
        )
        self.assertIn(
            'assert_tenant_exact "$ADMIN_UID" fullats-admin "$FULLATS_PUBLIC_TENANT_ID"',
            self.keycloak,
        )
        self.assertNotIn('set_tenant "$ADMIN_UID" t-platform-test', self.keycloak)
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
            "const interviewStep = currentStatusHeading('Mülakat planlaması')"
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
            "getByRole('status').filter({ hasText: terminalStatusText })",
            self.fullats_browser,
        )
        self.assertIn(
            "'Durum güncellendi: Mülakat planlaması bekliyor.'",
            self.fullats_browser,
        )
        self.assertIn(
            "(await terminalStatus.textContent())?.trim() !== terminalStatusText",
            self.fullats_browser,
        )
        self.assertIn(
            "await assertNoHorizontalOverflow(recruiterPage, "
            "'recruiter-workspace-terminal-desktop')",
            self.fullats_browser,
        )

    def test_fullats_edit_is_visible_in_preview_and_public_product_surfaces(self):
        update_contract = self.fullats_browser.index(
            "updatedJob.summary !== editedJobSummary"
        )
        preview_contract = self.fullats_browser.index(
            "jobPreview.getByText(editedJobSummary, { exact: true })"
        )
        public_contract = self.fullats_browser.index(
            "candidatePage.getByText(editedJobSummary, { exact: true })"
        )
        self.assertLess(update_contract, preview_contract)
        self.assertLess(preview_contract, public_contract)

    def test_fullats_rollback_is_bound_to_reviewed_tree_and_trusted_content_attestation(self):
        for required in (
            'require_exact_body_line "Consultation commit: $promotion_head"',
            'require_exact_body_line "Consultation mode: dual"',
            'require_exact_body_line "Verdict: AGREE"',
            "promotion consultation reason is missing or too short",
            "exact $receipt_label binding is missing or invalid",
            "MiniMax receipt is forbidden by forward policy",
            '"$promotion_merge_tree" == "$promotion_head_tree"',
        ):
            self.assertIn(required, self.rollback_script)
        for required in (
            '"$(git rev-parse "$PR_HEAD_SHA^")" == "$PR_BASE_SHA"',
            '"$promotion_merge_tree" == "$promotion_head_tree"',
            '"$(git rev-parse "$PROMOTION_BASE_SHA:$test_root")"',
            '"$(git show "$PR_HEAD_SHA:$state_marker")" == "ROLLED_BACK"',
            'fullats-rollback-content-attestation/v1',
        ):
            self.assertIn(required, self.rollback_content_verifier)
        self.assertIn(
            "run: bash scripts/ats/verify-fullats-test-rollback-content.sh",
            self.cross_ai_workflow,
        )
        self.assertIn(
            "ref: ${{ github.event.pull_request.base.sha }}",
            self.cross_ai_workflow,
        )
        self.assertNotIn(
            "ref: ${{ github.event.pull_request.base.ref }}",
            self.cross_ai_workflow,
        )
        verifier_step = self.cross_ai_workflow.index(
            "Verify exact Full ATS rollback content from trusted base"
        )
        scope_step = self.cross_ai_workflow.index(
            "Derive trusted merge-base and scope digest"
        )
        self.assertLess(verifier_step, scope_step)
        self.assertIn(
            'git fetch --no-tags origin "pull/${PR_NUMBER}/head"',
            self.rollback_content_verifier,
        )
        self.assertIn(
            "--automation-content-attestation-file",
            self.cross_ai_workflow,
        )
        self.assertIn(
            "${{ runner.temp }}/fullats-rollback-content-attestation-${{ github.run_id }}-${{ github.run_attempt }}.json",
            self.cross_ai_workflow,
        )

    def test_fullats_rollback_content_verifier_executes_fail_closed_with_mocked_git_and_github(self):
        promotion_base = "aa93f4743dc8254ce8e22a0317f92db1f5819268"
        pr_base = "1" * 40
        pr_head = "2" * 40
        promotion_head = "3" * 40
        promotion_scope = "4" * 64
        tree = "5" * 40
        branch = "auto-fullats-rollback/faz25-fullats-123-1"
        fake_git = r"""
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-c" ]]; then shift 2; fi
command="${1:-}"
shift || true
printf 'git command=%s args=%s tamper=%s\n' "$command" "$*" "${FAKE_TAMPER:-unset}" >>"$FAKE_TRACE"
case "$command" in
  fetch)
    [[ "$*" == "--no-tags origin pull/2636/head" ]]
    ;;
  rev-list)
    target="${*: -1}"
    if [[ "$target" == "$PR_HEAD_SHA" ]]; then
      printf '%s %s\n' "$PR_HEAD_SHA" "$PR_BASE_SHA"
    elif [[ "$target" == "$PR_BASE_SHA" ]]; then
      printf '%s %s\n' "$PR_BASE_SHA" "$PROMOTION_BASE_SHA"
    else
      exit 91
    fi
    ;;
  rev-parse)
    target="${1:-}"
    if [[ "$target" == "FETCH_HEAD" ]]; then
      printf '%s\n' "$PR_HEAD_SHA"
    elif [[ "$target" == "$PR_HEAD_SHA^" ]]; then
      printf '%s\n' "$PR_BASE_SHA"
    elif [[ "$target" == "$PR_BASE_SHA^" ]]; then
      printf '%s\n' "$PROMOTION_BASE_SHA"
    elif [[ "$target" == "$PROMOTION_BASE_SHA:"* ]]; then
      printf '%040d\n' 7
    elif [[ "$target" == "$PR_HEAD_SHA:"* ]]; then
      if [[ "${FAKE_TAMPER:-0}" == "1" && "$target" == *"kustomization.yaml" ]]; then
        printf '%040d\n' 8
      else
        printf '%040d\n' 7
      fi
    else
      exit 92
    fi
    ;;
  diff)
    if [[ " $* " == *" --name-only "* ]]; then
      printf '%s\n' \
        'kustomize/overlays/test/fullats-promotion-state.txt' \
        'kustomize/overlays/test/kustomization.yaml'
    else
      printf 'mock-binary-diff\n'
    fi
    ;;
  show)
    [[ "${1:-}" == "$PR_HEAD_SHA:kustomize/overlays/test/fullats-promotion-state.txt" ]]
    printf 'ROLLED_BACK\n'
    ;;
  *) exit 93 ;;
esac
"""
        fake_gh = r"""
#!/usr/bin/env bash
set -euo pipefail
printf 'gh args=%s tree_mismatch=%s\n' "$*" "${FAKE_TREE_MISMATCH:-unset}" >>"$FAKE_TRACE"
if [[ "$*" == *"/pulls/2636"* ]]; then
  body="$(printf '%s\n' \
    "Consultation base: $PROMOTION_BASE_SHA" \
    "Consultation commit: $PROMOTION_HEAD_SHA" \
    "Consultation scope: $PROMOTION_SCOPE_SHA256" \
    "Consultation mode: dual" \
    "Consultation reason: Protected rollback enforcement requires two independent provider reviews." \
    "Risk trigger: security-authz: Trusted rollback exemption changes the protected review boundary." \
    "Verdict: AGREE" \
    "Claude receipt: provider=anthropic; head=$PROMOTION_HEAD_SHA; scope=$PROMOTION_SCOPE_SHA256; verdict=AGREE; ref=https://api.github.com/example; sha256=$(printf '%064d' 6)" \
    "Codex receipt: provider=openai; head=$PROMOTION_HEAD_SHA; scope=$PROMOTION_SCOPE_SHA256; verdict=AGREE; ref=https://api.github.com/example; sha256=$(printf '%064d' 7)")"
  jq -n \
    --arg merge "$PR_BASE_SHA" \
    --arg head "$PROMOTION_HEAD_SHA" \
    --arg body "$body" \
    '{merged_at:"2026-07-18T00:00:00Z",merge_commit_sha:$merge,head:{sha:$head},body:$body}'
elif [[ "$*" == *"/git/commits/$PROMOTION_HEAD_SHA"* ]]; then
  if [[ "${FAKE_TREE_MISMATCH:-0}" == "1" ]]; then printf '%040d\n' 6; else printf '%s\n' "$PROMOTION_TREE_SHA"; fi
elif [[ "$*" == *"/git/commits/$PR_BASE_SHA"* ]]; then
  printf '%s\n' "$PROMOTION_TREE_SHA"
else
  exit 94
fi
"""
        for tamper, tree_mismatch, expected_rc in (
            (False, False, 0),
            (True, False, 1),
            (False, True, 1),
        ):
            with self.subTest(tamper=tamper, tree_mismatch=tree_mismatch):
                with tempfile.TemporaryDirectory() as temp:
                    fake_bin = Path(temp) / "bin"
                    fake_bin.mkdir()
                    git_path = fake_bin / "git"
                    gh_path = fake_bin / "gh"
                    git_path.write_text(textwrap.dedent(fake_git).lstrip())
                    gh_path.write_text(textwrap.dedent(fake_gh).lstrip())
                    git_path.chmod(0o755)
                    gh_path.chmod(0o755)
                    output = Path(temp) / "attestation.json"
                    trace = Path(temp) / "trace.log"
                    env = {
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "GH_REPO": "Halildeu/platform-k8s-gitops",
                        "PROMOTION_PR": "2636",
                        "PR_NUMBER": "2636",
                        "PR_HEAD_REF": branch,
                        "PR_HEAD_SHA": pr_head,
                        "PR_BASE_SHA": pr_base,
                        "ATTESTATION_OUTPUT": str(output),
                        "PROMOTION_BASE_SHA": promotion_base,
                        "PROMOTION_HEAD_SHA": promotion_head,
                        "PROMOTION_SCOPE_SHA256": promotion_scope,
                        "PROMOTION_TREE_SHA": tree,
                        "FAKE_TAMPER": "1" if tamper else "0",
                        "FAKE_TREE_MISMATCH": "1" if tree_mismatch else "0",
                        "FAKE_TRACE": str(trace),
                    }
                    completed = subprocess.run(
                        ["bash", str(ROOT / "scripts/ats/verify-fullats-test-rollback-content.sh")],
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    if expected_rc == 0:
                        self.assertEqual(completed.returncode, 0, completed.stderr)
                        attestation = json.loads(output.read_text())
                        self.assertTrue(attestation["valid"])
                        self.assertEqual(attestation["base_sha"], pr_base)
                        self.assertEqual(attestation["head_sha"], pr_head)
                        self.assertEqual(attestation["promotion_head_sha"], promotion_head)
                        self.assertEqual(attestation["promotion_scope_sha256"], promotion_scope)
                    else:
                        self.assertNotEqual(
                            completed.returncode,
                            0,
                            trace.read_text() if trace.exists() else completed.stderr,
                        )
                        self.assertFalse(output.exists())

    def test_fullats_browser_covers_real_job_lifecycle_and_fail_closed_intake(self):
        ordered_steps = [
            "getByRole('button', { name: 'Yeni ilan oluştur' })",
            "getByRole('button', { name: 'Taslak oluştur' })",
            "getByRole('button', { name: 'Değişiklikleri kaydet' })",
            "getByRole('button', { name: 'Önizle' })",
            "getByRole('button', { name: 'Yayınla' })",
            "getByRole('link', { name: 'Başvuru formuna geç' })",
            "locator('#resume-import-notice')",
            "getByTestId('candidate-resume').setInputFiles",
            "getByRole('button', { name: 'Güvenli önerileri kabul et' })",
            "getByRole('button', { name: 'Deneyim bilgilerime devam et' })",
            "getByRole('button', { name: 'Başvuruyu kontrol et' })",
            "getByTestId('create-application-receipt')",
            "getByRole('button', { name: 'İnsan incelemesini başlat' })",
            "getByRole('button', { name: 'Yapılandırılmış değerlendirme yap' })",
            "getByRole('button', { name: 'Immutable değerlendirmeyi kaydet' })",
            "getByRole('button', { name: 'Mülakat planlamasına al' })",
            "getByRole('button', { name: 'Duraklat' })",
            "assertNewApplicationRejected(publicStatePage, publicApplicationApiPath, 'PAUSED')",
            "getByRole('button', { name: 'Yayınla' })",
            "getByRole('button', { name: 'İlanı kapat' })",
            "assertNewApplicationRejected(publicStatePage, publicApplicationApiPath, 'CLOSED')",
        ]
        cursor = -1
        for step in ordered_steps:
            cursor = self.fullats_browser.index(step, cursor + 1)
        self.assertIn("jobTransitions.length !== 4", self.fullats_browser)
        self.assertIn("rejectedApplications.length !== 2", self.fullats_browser)
        self.assertIn("jobIdSha256: sha256(jobId)", self.fullats_browser)
        self.assertIn("jobSlugSha256: sha256(jobSlug)", self.fullats_browser)
        self.assertIn("finalJobState: 'CLOSED'", self.fullats_browser)
        self.assertIn("getByTestId('candidate-resume').setInputFiles", self.fullats_browser)
        self.assertIn("await resumeImportNotice.check()", self.fullats_browser)
        self.assertIn("importedFieldCount < 2", self.fullats_browser)
        self.assertIn("await fillIfEmpty('candidate-phone'", self.fullats_browser)
        self.assertIn("'candidate-summary'", self.fullats_browser)
        self.assertIn("buildSyntheticResumePdf", self.fullats_browser)
        self.assertIn("candidate-imports-real-pdf-locally", self.fullats_browser)
        self.assertIn("candidate-edits-pdf-autofilled-field", self.fullats_browser)
        self.assertIn("candidate submission field boundary mismatch", self.fullats_browser)
        self.assertNotIn("getByText('Şimdi')", self.fullats_browser)
        self.assertIn(
            "getByText('Güncel durum', { exact: true }).locator('..')",
            self.fullats_browser,
        )
        self.assertIn("currentStatusHeading('Başvuru alındı')", self.fullats_browser)
        self.assertIn("currentStatusHeading('İnsan incelemesinde')", self.fullats_browser)
        self.assertIn("currentStatusHeading('Mülakat planlaması')", self.fullats_browser)
        self.assertIn(
            "candidate submission is not bound to the confirmed resume draft",
            self.fullats_browser,
        )
        self.assertIn("submittedPayload.resumeDraftVersion < 0", self.fullats_browser)
        self.assertIn("structured recruiter evaluation HTTP", self.fullats_browser)
        self.assertIn(
            "['recruiter', 'POST', `/api/ats/v1/recruiter/applications/"
            "${publicRef}/evaluations`, 201]",
            self.fullats_browser,
        )
        self.assertIn(
            "['negative-probe', 'GET', '/api/ats/v1/recruiter/applications', 401]",
            self.fullats_browser,
        )
        self.assertIn("anonymousRecruiterStatus !== 401", self.fullats_browser)
        self.assertIn("credentials: 'omit'", self.fullats_browser)
        self.assertNotIn("getByTestId('fill-synthetic-resume').click()", self.fullats_browser)
        self.assertIn("attachNetworkEvidence(publicStatePage, 'negative-probe')", self.fullats_browser)
        self.assertIn("entry.persona === 'negative-probe'", self.fullats_browser)
        self.assertIn("result.error !== 'NOT_FOUND'", self.fullats_browser)
        self.assertNotIn("/jobs/urun-yoneticisi/apply", self.fullats_browser)

    def test_fullats_recruiter_setup_is_least_privilege_and_action_explicit(self):
        for permission in (
            '{type:"MODULE",key:$interview_key,grant:"VIEW"}',
            '{type:"MODULE",key:$ats_key,grant:"VIEW"}',
            '{type:"ACTION",key:$job_action,grant:"ALLOW"}',
            '{type:"ACTION",key:$application_action,grant:"ALLOW"}',
        ):
            self.assertIn(permission, self.fullats_browser_shell)
        self.assertIn("(.superAdmin == false)", self.fullats_browser_shell)
        self.assertIn('GET "/api/v1/roles/$ROLE_ID/granules"', self.fullats_browser_shell)
        self.assertIn("target recruiter role exact four-granule snapshot mismatch", self.fullats_browser_shell)
        self.assertIn(
            'POST "/api/v1/authz/users/$RECRUITER_USER_ID/assignments"',
            self.fullats_browser_shell,
        )
        self.assertIn(
            'GET "/api/v1/authz/users/$RECRUITER_USER_ID/roles"',
            self.fullats_browser_shell,
        )
        self.assertIn("recruiter active product role set is not exact", self.fullats_browser_shell)
        self.assertIn('(.roles // []) == [$role_name]', self.fullats_browser_shell)
        self.assertIn('(.reports // {}) == {}', self.fullats_browser_shell)
        self.assertIn(
            'GET "/api/v1/roles/$ROLE_ID/members"',
            self.fullats_browser_shell,
        )
        self.assertIn(
            "target recruiter exact role membership snapshot mismatch",
            self.fullats_browser_shell,
        )
        self.assertIn(
            "[.[] | select(.userId == $recruiter_user_id)] | length == 1",
            self.fullats_browser_shell,
        )
        self.assertNotIn(
            "length == 1 and .[0].userId",
            self.fullats_browser_shell,
        )
        self.assertNotIn("def module_allowed", self.fullats_browser_shell)
        self.assertNotIn("def action_allowed", self.fullats_browser_shell)
        self.assertNotIn('{type:"MODULE",key:$ats_key,grant:"MANAGE"}', self.fullats_browser_shell)

    def test_fullats_live_browser_is_bound_to_three_exact_runtime_artifacts(self):
        expected = {
            "ats": "sha256:8897132f1ac49f2154c7cf07f461a3a3e478b2800cd640b6df057843056d335e",
            "permission": "sha256:264901f4a11ea00d2f27fd56bb31bd35536394eb0ae2c83d992763a0b4d3bb02",
            "frontend": self.frontend_pin["digest"],
        }
        self.assertIn(f"EXPECTED_ATS_DIGEST: {expected['ats']}", self.fullats_browser_workflow)
        self.assertIn(
            f"EXPECTED_PERMISSION_DIGEST: {expected['permission']}",
            self.fullats_browser_workflow,
        )
        self.assertNotRegex(
            self.fullats_browser_workflow,
            r"(?m)^\s+EXPECTED_FRONTEND_(?:DIGEST|SHA):\s+(?:sha256:)?[a-f0-9]{40,64}$",
        )
        self.assertIn(
            "Bind frontend runtime to canonical test overlay",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            "python3 scripts/automation/test-overlay-frontend-image.py inspect",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            'echo "EXPECTED_FRONTEND_SHA=$source_sha"',
            self.fullats_browser_workflow,
        )
        self.assertIn(
            'echo "EXPECTED_FRONTEND_DIGEST=$digest"',
            self.fullats_browser_workflow,
        )
        checkout = self.fullats_browser_workflow.index(
            "Checkout canonical acceptance scripts"
        )
        bind = self.fullats_browser_workflow.index(
            "Bind frontend runtime to canonical test overlay"
        )
        convergence = self.fullats_browser_workflow.index(
            "Wait for exact GitOps auto-sync convergence"
        )
        self.assertLess(checkout, bind)
        self.assertLess(bind, convergence)
        self.assertIn(
            'echo "- frontend source: ${FRONTEND_SOURCE_URL}"',
            self.fullats_browser_workflow,
        )
        self.assertIn(
            'echo "- frontend immutable digest: ${EXPECTED_FRONTEND_DIGEST}"',
            self.fullats_browser_workflow,
        )
        self.assertIn("body.sha !== expectedFrontendSha", self.fullats_browser)
        self.assertIn("fetchBuildInfo('pre')", self.fullats_browser)
        self.assertIn("fetchBuildInfo('post')", self.fullats_browser)
        self.assertIn("cache: 'no-store'", self.fullats_browser)
        self.assertIn('-e EXPECTED_FRONTEND_SHA="$EXPECTED_FRONTEND_SHA"', self.fullats_browser_shell)
        self.assertIn("scripts/ats/verify-fullats-live-runtime.sh", self.fullats_browser_workflow)
        self.assertIn(
            "permission-service permission-service app.kubernetes.io/name=permission-service",
            self.fullats_runtime,
        )
        self.assertIn(
            "frontend frontend app.kubernetes.io/name=frontend",
            self.fullats_runtime,
        )
        self.assertIn(
            'test("^[a-f0-9]{40}$")',
            self.fullats_runtime,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$EXPECTED_GITOPS_SHA" "$observed_argo_revision"',
            self.fullats_runtime,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$observed_argo_revision" "$observed_main_revision"',
            self.fullats_runtime,
        )
        self.assertIn(
            'revisionRelationship:"dispatched-equals-or-ancestor-of-observed"',
            self.fullats_runtime,
        )
        self.assertNotIn(
            '"$(git rev-parse origin/main)" == "$EXPECTED_GITOPS_SHA"',
            self.fullats_runtime,
        )
        self.assertIn('.status.sync.status == "Synced"', self.fullats_runtime)
        self.assertIn('.status.health.status == "Healthy"', self.fullats_runtime)
        self.assertIn("origin/main", self.fullats_runtime)
        self.assertIn("replica_set_uid", self.fullats_runtime)
        self.assertIn(".imageID | endswith", self.fullats_runtime)
        self.assertIn("Cache-Control: no-cache", self.fullats_runtime)
        self.assertIn("PHASE: pre", self.fullats_browser_workflow)
        self.assertIn("PHASE: post", self.fullats_browser_workflow)
        self.assertIn(
            'echo "effective_gitops_sha=$effective_revision" >> "$GITHUB_OUTPUT"',
            self.fullats_browser_workflow,
        )
        self.assertEqual(
            2,
            self.fullats_browser_workflow.count(
                "EXPECTED_GITOPS_SHA: ${{ steps.convergence.outputs.effective_gitops_sha }}"
            ),
        )
        self.assertIn(
            'git checkout --detach "$effective_revision"',
            self.fullats_browser_workflow,
        )
        self.assertIn(
            '.effectiveRevision == .observedRevision',
            self.fullats_browser_workflow,
        )
        for acceptance_path in (
            ".github/workflows/faz25-fullats-live-browser-acceptance.yml",
            "scripts/ats/verify-fullats-live-runtime.sh",
            "scripts/ats/fullats-live-browser-acceptance.sh",
            "scripts/ats/fullats-live-browser-acceptance.cjs",
            "scripts/ats/d29-smoke.sh",
        ):
            self.assertIn(acceptance_path, self.testai_reconcile)
        self.assertNotIn("id: d29", self.fullats_browser_workflow)
        self.assertNotIn("bash scripts/ats/d29-smoke.sh", self.fullats_browser_workflow)
        self.assertIn(
            "customer-slice D29: exact runtime + real browser function",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            "meeting/STT model-governance matrix: separate product slice",
            self.fullats_browser_workflow,
        )
        self.assertNotRegex(self.d29, r"curl\s+-[^\n]*k")
        self.assertIn("capturedNetworkFields", self.fullats_browser)
        self.assertIn("redacted.replaceAll(value, marker)", self.fullats_browser)
        self.assertNotIn("containsRawCandidateAccessToken", self.fullats_browser)
        self.assertNotIn("containsRawPasswordOrJwt", self.fullats_browser)

    def test_candidate_pdf_worker_has_test_only_javascript_mime_runtime_config(self):
        self.assertIn("behavior: replace", self.test_root)
        self.assertIn(
            "default.conf=frontend-nginx-default.conf",
            self.test_root,
        )
        self.assertIn(r"location ~* \.mjs$", self.test_frontend_nginx)
        self.assertIn(
            "default_type application/javascript;",
            self.test_frontend_nginx,
        )
        self.assertIn(
            "default_type application/javascript;",
            self.rendered_test_root,
        )

    def test_frontend_promotion_consumers_use_canonical_overlay_pin(self):
        source_sha = self.frontend_pin["source_sha"]
        tag = self.frontend_pin["tag"]
        digest = self.frontend_pin["digest"]

        self.assertRegex(source_sha, r"^[a-f0-9]{40}$")
        self.assertEqual(tag, f"sha-{source_sha[:7]}")
        self.assertRegex(digest, r"^sha256:[a-f0-9]{64}$")
        for exact in (
            f"sourceRevision: {source_sha}",
            f"newTag: {tag}",
            f"digest: {digest}",
        ):
            self.assertIn(exact, self.test_root)

        self.assertIn(
            "Current machine-readable authority is the sourceRevision/newTag/digest",
            self.test_root,
        )
        self.assertIn(
            "test-overlay-frontend-image.py inspect",
            self.fullats_browser_workflow,
        )
        self.assertNotIn(f'FRONTEND_NEW="{digest}"', self.rollback_script)
        self.assertNotIn(
            f"EXPECTED_FRONTEND_DIGEST: {digest}",
            self.fullats_browser_workflow,
        )

    def test_fullats_live_failure_opens_exact_atomic_gitops_rollback(self):
        self.assertIn("timeout-minutes: 90", self.fullats_browser_workflow)
        self.assertIn("id: preflight", self.fullats_browser_workflow)
        self.assertIn("id: runtime", self.fullats_browser_workflow)
        self.assertIn("id: browser", self.fullats_browser_workflow)
        self.assertNotIn("id: d29", self.fullats_browser_workflow)
        self.assertIn("id: final-runtime", self.fullats_browser_workflow)
        self.assertIn("id: convergence", self.fullats_browser_workflow)
        self.assertIn("FULL_SYNC_TIMEOUT=900", self.fullats_browser_workflow)
        self.assertIn(
            "scripts/deploy/reconcile-testai-backend-sequential.sh",
            self.fullats_browser_workflow,
        )
        self.assertIn("steps.convergence.outcome == 'failure'", self.fullats_browser_workflow)
        self.assertIn(
            "steps.browser.outcome == 'failure' || steps.final-runtime.outcome == 'failure'",
            self.fullats_browser_workflow,
        )
        self.assertNotIn("steps.d29.outcome", self.fullats_browser_workflow)
        self.assertIn("steps.rollback-checkout.outcome == 'success'", self.fullats_browser_workflow)
        self.assertIn("install-pinned-gh-cli.sh", self.fullats_browser_workflow)
        self.assertIn("steps.rollback-gh.outcome == 'success'", self.fullats_browser_workflow)
        self.assertIn("install-pinned-kustomize.sh", self.fullats_browser_workflow)
        self.assertIn(
            "steps.rollback-kustomize.outcome == 'success'",
            self.fullats_browser_workflow,
        )
        self.assertIn("open-fullats-test-rollback-pr.sh", self.fullats_browser_workflow)
        self.assertIn('PROMOTION_PR: "2636"', self.fullats_browser_workflow)
        self.assertIn('[[ "$(git rev-parse origin/main)" == "$FAILED_SHA" ]]', self.rollback_script)
        self.assertIn('[[ "$merge_sha" == "$FAILED_SHA" ]]', self.rollback_script)
        self.assertIn(
            "acceptance did not run on the exact reviewed promotion merge",
            self.rollback_script,
        )
        self.assertIn(
            'echo "[fullats-rollback] missing command: $command"',
            self.rollback_script,
        )
        self.assertIn("awk gh git grep jq kustomize python3", self.rollback_script)
        self.assertNotIn("python3 rg", self.rollback_script)
        self.assertNotIn("rg -F", self.rollback_script)
        self.assertIn('grep -Fxq -- "ROLLED_BACK"', self.rollback_script)
        self.assertIn(
            'branch="auto-fullats-rollback/faz25-fullats-${RUN_ID}-${RUN_ATTEMPT}"',
            self.rollback_script,
        )
        self.assertIn('parent_count="$(git rev-list --parents -n 1 "$merge_sha"', self.rollback_script)
        self.assertIn('"$(git rev-parse "$merge_sha^")" != "$PROMOTION_BASE_SHA"', self.rollback_script)
        self.assertIn('git show "$PROMOTION_BASE_SHA:$test_root"', self.rollback_script)
        self.assertIn("printf 'ROLLED_BACK\\n'", self.rollback_script)
        self.assertIn("changed-file set escaped two-file contract", self.rollback_script)
        for digest in (
            "sha256:8897132f1ac49f2154c7cf07f461a3a3e478b2800cd640b6df057843056d335e",
            "sha256:264901f4a11ea00d2f27fd56bb31bd35536394eb0ae2c83d992763a0b4d3bb02",
            "sha256:f23165a53eed9778213ae8af6b1211d3e972e124a03d87fe678a20e97f6fe8b0",
            "sha256:46a55e1664552d7f8a35c15bdd14ff4a21b9a40bc6d10324aa779e61be036402",
        ):
            self.assertIn(digest, self.rollback_script)
        self.assertIn("kustomize build kustomize/overlays/test", self.rollback_script)
        self.assertIn('--required --watch --fail-fast', self.rollback_script)
        self.assertIn('--squash --match-head-commit "$rollback_head"', self.rollback_script)
        self.assertNotIn(
            'gh pr merge "$pr_url" --repo "$GH_REPO" --admin',
            self.rollback_script,
        )
        self.assertIn("permission-contents: write", self.fullats_browser_workflow)
        self.assertIn("permission-pull-requests: write", self.fullats_browser_workflow)
        self.assertIn("'auto-fullats-rollback/'", self.cross_ai_audit)
        self.assertIn("fullats-promotion-state", self.cross_ai_audit)
        self.assertIn(
            "Automation source: .github/workflows/faz25-fullats-live-browser-acceptance.yml",
            self.rollback_script,
        )
        self.assertIn("## Boundary declaration (ADR-0011 §2.3)", self.rollback_script)
        self.assertIn("- [x] state-mutation (test cluster)", self.rollback_script)
        self.assertIn("reviewed-base frontend", self.rollback_script)
        self.assertNotIn("önceki kanıtlı", self.rollback_script)
        self.assertIn(
            "scripts/deploy/reconcile-testai-backend-sequential.sh",
            self.rollback_script,
        )
        self.assertIn('REVISION="$rollback_merge_sha"', self.rollback_script)
        self.assertIn("FULL_SYNC_TIMEOUT=600", self.rollback_script)
        self.assertIn(
            'EXPECTED_GITOPS_SHA="$rollback_merge_sha"',
            self.rollback_script,
        )
        self.assertIn(
            'EXPECTED_FRONTEND_SHA="$FRONTEND_OLD_SHA"',
            self.rollback_script,
        )
        self.assertIn(
            "bash scripts/ats/verify-fullats-live-runtime.sh",
            self.rollback_script,
        )
        self.assertIn("REQUIRE_HEAD_SHA=false", self.rollback_script)
        self.assertIn("fullats_run=$nonce", self.fullats_runtime)
        self.assertIn("ready_pod_image_ids_exact: true", self.rollback_script)
        self.assertIn(
            'ATS_EXPECTED_DIGEST="$ATS_CURRENT" bash scripts/ats/d29-smoke.sh',
            self.rollback_script,
        )
        self.assertIn("faz25-fullats-post-rollback-runtime/v1", self.rollback_script)
        self.assertIn("fullats-rollback-evidence-", self.fullats_browser_workflow)
        self.assertIn(
            "Require compensating rollback completion after acceptance failure",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            "protected compensating rollback did not complete",
            self.fullats_browser_workflow,
        )
        self.assertIn("steps.rollback.outcome != 'success'", self.fullats_browser_workflow)
        self.assertIn("frontend-only compensator", self.runbook)

    def test_fullats_rollback_installs_checksum_pinned_runner_local_github_cli(self):
        self.assertIn('VERSION="2.96.0"', self.pinned_gh_installer)
        self.assertIn(
            'expected_sha="83d5c2ccad5498f58bf6368acb1ab32588cf43ab3a4b1c301bf36328b1c8bd60"',
            self.pinned_gh_installer,
        )
        self.assertIn(
            'expected_sha="06f86ec7103d41993b76cd78072f43595c34aaa56506d971d9860e67140bf909"',
            self.pinned_gh_installer,
        )
        self.assertIn("--retry-all-errors", self.pinned_gh_installer)
        self.assertIn('[[ "$actual_sha" == "$expected_sha" ]]', self.pinned_gh_installer)
        self.assertIn('[[ "$(uname -s)" == "Linux" ]]', self.pinned_gh_installer)
        self.assertIn('printf \'%s\\n\' "$bin_dir" >>"$GITHUB_PATH"', self.pinned_gh_installer)
        self.assertNotIn("sudo", self.pinned_gh_installer)

    def test_fullats_rollback_installs_checksum_pinned_runner_local_kustomize(self):
        self.assertIn('VERSION="5.8.1"', self.pinned_kustomize_installer)
        self.assertIn(
            'expected_sha="029a7f0f4e1932c52a0476cf02a0fd855c0bb85694b82c338fc648dcb53a819d"',
            self.pinned_kustomize_installer,
        )
        self.assertIn(
            'expected_sha="0953ea3e476f66d6ddfcd911d750f5167b9365aa9491b2326398e289fef2c142"',
            self.pinned_kustomize_installer,
        )
        self.assertIn("--retry-all-errors", self.pinned_kustomize_installer)
        self.assertIn(
            '[[ "$actual_sha" == "$expected_sha" ]]',
            self.pinned_kustomize_installer,
        )
        self.assertIn(
            '[[ "$(uname -s)" == "Linux" ]]',
            self.pinned_kustomize_installer,
        )
        self.assertIn(
            'printf \'%s\\n\' "$bin_dir" >>"$GITHUB_PATH"',
            self.pinned_kustomize_installer,
        )
        self.assertNotIn("sudo", self.pinned_kustomize_installer)

    def test_fullats_promotion_or_rollback_state_binds_exact_frontend_and_current_backends(self):
        self.assertIn(self.promotion_state, {"PROMOTED", "ROLLED_BACK"})
        current_ats = "sha256:8897132f1ac49f2154c7cf07f461a3a3e478b2800cd640b6df057843056d335e"
        # #2555 Slice B (2026-07-20) - bumped from sha256:55f2f2f2 to sha256:a23c72fa
        # (sha-4a0dc67, platform-backend PR #896). AccessScopeService.grant()
        # widens the P0001 handler; POST /access/scope 500->400. Faz 25 ATS
        # promotion state is invariant under this backend-only behavior change
        # (no ATS DTO / catalog / recruiter-scope contract touched).
        # #2555 chain progression: Slice B → Slice C → Slice E (2026-07-20/21).
        # Slice B (sha256:a23c72fa…) → Slice C (sha256:32e7e2b5…, @RequestParam bind
        # failures 500→400) → Slice E (sha256:f93e800d…, HandlerMethodValidation
        # Exception systemic + HttpMessageNotReadable D-parity). Backend-only
        # behaviour changes; Faz 25 ATS promotion state is invariant under this
        # chain (no ATS DTO / catalog / recruiter-scope contract touched).
        # 2026-07-21: board #907 wire step (PR platform-backend#909, foundation #851)
        # bumps permission-service to sha-e9018ce (sha256:096ed22f…). /authz/me now
        # flows through common-auth/identity/AuthenticatedPrincipalResolver; body
        # shape unchanged, runtime behaviour unchanged for RESOLVED path today.
        # Faz 25 ATS promotion state remains invariant (no ATS DTO / catalog /
        # recruiter-scope contract touched).
        # 2026-07-30: board #3198 / platform-backend#1028 bumps permission-service
        # to sha-77f6e8f (sha256:264901f4…). The transaction boundary fix prevents
        # /authz/me from holding a DB connection across identity/OpenFGA calls;
        # the response and fail-closed authority contracts remain unchanged.
        current_permission = "sha256:264901f4a11ea00d2f27fd56bb31bd35536394eb0ae2c83d992763a0b4d3bb02"
        promoted = {
            "frontend": self.frontend_pin["digest"],
            "tag": self.frontend_pin["tag"],
        }
        rolled_back = {
            "frontend": "sha256:46a55e1664552d7f8a35c15bdd14ff4a21b9a40bc6d10324aa779e61be036402",
            "tag": "sha-eee1310",
        }
        expected = promoted if self.promotion_state == "PROMOTED" else rolled_back
        self.assertIn(current_ats, self.activation)
        self.assertIn(current_permission, self.test_root)
        self.assertIn(expected["frontend"], self.test_root)
        self.assertIn(
            f"image: ghcr.io/halildeu/ats-app-boot@{current_ats}",
            self.rendered_test_root,
        )
        self.assertIn(
            "image: ghcr.io/halildeu/platform-backend-permission-service@"
            f"{current_permission}",
            self.rendered_test_root,
        )
        self.assertIn(
            "image: ghcr.io/halildeu/platform-web-frontend-testai:"
            f"{expected['tag']}@{expected['frontend']}",
            self.rendered_test_root,
        )
        other = rolled_back if self.promotion_state == "PROMOTED" else promoted
        self.assertNotIn(
            "image: ghcr.io/halildeu/platform-web-frontend-testai:"
            f"{other['tag']}@{other['frontend']}",
            self.rendered_test_root,
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

    def test_flyway_v16_migrator_role_is_admin_preprovisioned(self):
        """V16 ats_migrator'i IF NOT EXISTS ile kullanir; runtime CREATEROLE almadigi
        icin rol admin duzleminde on-provision edilmezse app hic boot etmez
        (2026-07-24 canli: 'permission denied to create role' -> CrashLoopBackOff)."""
        self.assertIn("CREATE ROLE ats_migrator", self.pg_bootstrap)
        self.assertIn("GRANT ats_migrator TO ats_app", self.pg_bootstrap)
        # Rol, governance_writer ile ayni least-privilege setinde olusturulur.
        migrator_at = self.pg_bootstrap.index("CREATE ROLE ats_migrator")
        attrs_at = self.pg_bootstrap.index(
            "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
            migrator_at,
        )
        self.assertLess(migrator_at, attrs_at)
        # Guvensiz attribute tasiyan mevcut rol fail-closed reddedilir.
        self.assertIn("ats_migrator guvensiz role attribute tasiyor", self.pg_bootstrap)
        # Assert, Vault/parola islemlerinden ONCE calisir (roles-only kurtarma yolu).
        self.assertIn("FATAL: ats_migrator NOLOGIN/least-privilege assert basarisiz", self.pg_bootstrap)
        self.assertLess(
            self.pg_bootstrap.index("PG: ats_migrator NOLOGIN role OK"),
            self.pg_bootstrap.index("PW=$(openssl rand"),
        )
        # ats_app'a CREATEROLE verilmesi hala yasak.
        self.assertNotRegex(self.pg_bootstrap, r"ALTER\s+ROLE\s+ats_app[^\n;]*CREATEROLE")

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
        self.assertIn("[self-hosted, aiserver, testai-deploy]", self.recovery_workflow)
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
        self.assertIn("Faz 25 #2526 ilk müşteri yüzeyi backend pini", self.runbook)
        self.assertIn("ATS exact main `29a8abb`", self.runbook)
        self.assertIn("Canlı D29 ve uçtan uca aday/İK kanıtı", self.runbook)
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

    def test_consultation_defaults_to_none_then_flexible_provider_and_max_two(self):
        # User 2026-07-20 flexibility: provider list is now {Claude, Codex,
        # MiniMax, GLM}, model choice is free within any provider, no specific
        # model slug is locked, MiniMax is re-admitted as a valid reviewer.
        # Fixed HARD RULES stay: provider-distinct, Cursor forbidden,
        # AI-app-window forbidden, tracked_pending on quota/auth/empty output.
        rule = "Durumsal Cross-AI istişare — varsayılan az kanal + sağlayıcı/model esnek"
        self.assertIn(rule, self.agents)
        self.assertIn("`Consultation mode: none`", self.agents)
        # Modes are still declared, but not gated to a specific model slug.
        self.assertIn("`single`", self.agents)
        self.assertIn("`dual`", self.agents)
        self.assertIn("toplam iki kanal aşılmaz", self.agents)
        # Flexibility markers.
        self.assertIn("Claude (Anthropic), Codex (OpenAI), MiniMax veya GLM", self.agents)
        self.assertIn("spesifik model kilidi yoktur", self.agents)
        self.assertIn("MiniMax ve GLM `single`/`dual` reviewer olarak kabul edilir", self.agents)
        # Preserved HARD RULES.
        self.assertIn("Cursor ve AI uygulama pencereleri istişare yolu değildir", self.agents)
        self.assertIn("consultation governance dosyası", self.agents)
        self.assertIn("audit/evidence enforcement kodunun kendisi `dual` ister", self.agents)
        # Canonical rule set updates. Short keyphrases only (multi-line safe).
        self.assertIn("provider-distinct", self.context_rules)
        self.assertIn("`dual` gerekir", self.context_rules)
        self.assertIn("Claude (Anthropic)", self.context_rules)
        self.assertIn("Codex (OpenAI)", self.context_rules)
        self.assertIn("MiniMax", self.context_rules)
        self.assertIn("GLM (Z.ai)", self.context_rules)
        self.assertIn("model seçimi", self.context_rules.lower())
        self.assertIn("esnektir", self.context_rules)
        self.assertIn("model kilidi yoktur", self.context_rules)
        self.assertIn("`other` bu iki modda", self.context_rules)
        self.assertIn("non-authoritative direction exploration", self.context_rules)
        self.assertIn("tracked_pending", self.context_rules)
        self.assertNotIn(
            "Cursor CLI (öncelikli ilave adversarial-review kanalı)", self.agents
        )
        self.assertIn(
            "## 11. Durumsal Cross-AI İstişare — Varsayılan Az Kanal + Sağlayıcı/Model Esnek",
            self.context_rules,
        )
        self.assertIn("**`none` — varsayılan:**", self.context_rules)
        self.assertIn("**`single` — gerçekten ikinci görüş gerektiğinde:**", self.context_rules)
        self.assertIn("**`dual` — istisnai yüksek risk:**", self.context_rules)
        self.assertIn(
            "İstişare bir teslimat ritüeli değil, yalnız karar",
            self.context_rules,
        )
        self.assertIn("Cursor CLI/MCP/model/harness", self.context_rules)
        self.assertIn("irreversible-production", self.context_rules)
        self.assertIn("Path/branch sınıflandırıcısı", self.context_rules)
        self.assertIn("`none` receipt", self.context_rules)
        self.assertIn("`dual` yayın sırası zorunlu değildir", self.context_rules)

if __name__ == "__main__":
    unittest.main()
