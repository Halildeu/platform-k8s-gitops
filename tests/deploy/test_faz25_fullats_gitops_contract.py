from __future__ import annotations

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
        cls.test_root = (ROOT / "kustomize/overlays/test/kustomization.yaml").read_text()
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
        cls.rollback_content_verifier = (
            ROOT / "scripts/ats/verify-fullats-test-rollback-content.sh"
        ).read_text()
        cls.cross_ai_workflow = (
            ROOT / ".github/workflows/gate-cross-ai-audit.yml"
        ).read_text()
        cls.cross_ai_audit = (ROOT / "scripts/ci/pr-cross-ai-audit.mjs").read_text()
        cls.agents = (ROOT / "AGENTS.md").read_text()
        cls.context_rules = (ROOT / "docs/context-priority-rules.md").read_text()
        cls.minimax_wrapper = (ROOT / "scripts/ai/minimax_m3_review.py").read_text()

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
            "Codex implementer cannot use Codex as dual secondary",
            '"$promotion_merge_tree" == "$promotion_head_tree"',
        ):
            self.assertIn(required, self.rollback_script)
        for required in (
            '"$(git rev-parse "$PR_HEAD_SHA^")" == "$PR_BASE_SHA"',
            '"$promotion_merge_tree" == "$promotion_head_tree"',
            '"$(git rev-parse "$PROMOTION_BASE_SHA:$restored_path")"',
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

    def test_fullats_rollback_content_verifier_executes_fail_closed_with_mocked_git_and_github(self):
        promotion_base = "fc5f2735a49977d79b82e9d36d71642e54e67023"
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
    [[ "$*" == "--no-tags origin pull/2617/head" ]]
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
        'kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml' \
        'kustomize/overlays/test/fullats-promotion-state.txt' \
        'kustomize/overlays/test/kustomization.yaml' \
        'scripts/ats/d29-smoke.sh'
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
if [[ "$*" == *"/pulls/2617"* ]]; then
  body="$(printf '%s\n' \
    "Consultation base: $PROMOTION_BASE_SHA" \
    "Consultation commit: $PROMOTION_HEAD_SHA" \
    "Consultation scope: $PROMOTION_SCOPE_SHA256" \
    "Consultation mode: dual" \
    "Consultation reason: Protected rollback enforcement requires two independent provider reviews." \
    "Risk trigger: security-authz: Trusted rollback exemption changes the protected review boundary." \
    "Verdict: AGREE" \
    "Claude receipt: provider=anthropic; head=$PROMOTION_HEAD_SHA; scope=$PROMOTION_SCOPE_SHA256; verdict=AGREE; ref=https://api.github.com/example; sha256=$(printf '%064d' 6)" \
    "MiniMax receipt: provider=minimax; head=$PROMOTION_HEAD_SHA; scope=$PROMOTION_SCOPE_SHA256; verdict=AGREE; ref=https://api.github.com/example; sha256=$(printf '%064d' 7)")"
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
                        "PROMOTION_PR": "2617",
                        "PR_NUMBER": "2617",
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
            "getByTestId('create-application-receipt')",
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
        self.assertIn("buildSyntheticResumePdf", self.fullats_browser)
        self.assertIn("candidate-imports-real-pdf-locally", self.fullats_browser)
        self.assertIn("candidate-edits-pdf-autofilled-field", self.fullats_browser)
        self.assertIn("candidate submission field boundary mismatch", self.fullats_browser)
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
            "recruiter role exact member snapshot mismatch",
            self.fullats_browser_shell,
        )
        self.assertIn("length == 1 and .[0].userId", self.fullats_browser_shell)
        self.assertNotIn("def module_allowed", self.fullats_browser_shell)
        self.assertNotIn("def action_allowed", self.fullats_browser_shell)
        self.assertNotIn('{type:"MODULE",key:$ats_key,grant:"MANAGE"}', self.fullats_browser_shell)

    def test_fullats_live_browser_is_bound_to_three_exact_runtime_artifacts(self):
        expected = {
            "ats": "sha256:8812ab4eed4881c24e8a8cc7129648d201e064f032dced571d9a56916ad66a11",
            "permission": "sha256:55f2f2f2d1edb3aa67c663c1411b0cc21ab1818d10b4d8d70a5beeeb32ade13d",
            "frontend": "sha256:f23165a53eed9778213ae8af6b1211d3e972e124a03d87fe678a20e97f6fe8b0",
        }
        self.assertIn(f"EXPECTED_ATS_DIGEST: {expected['ats']}", self.fullats_browser_workflow)
        self.assertIn(
            f"EXPECTED_PERMISSION_DIGEST: {expected['permission']}",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            f"EXPECTED_FRONTEND_DIGEST: {expected['frontend']}",
            self.fullats_browser_workflow,
        )
        self.assertIn(
            "EXPECTED_FRONTEND_SHA: 9f82edb249bcc4de3d83ce59a3800d835e88f410",
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
        self.assertIn(".status.sync.revision == $revision", self.fullats_runtime)
        self.assertIn('.status.sync.status == "Synced"', self.fullats_runtime)
        self.assertIn('.status.health.status == "Healthy"', self.fullats_runtime)
        self.assertIn("origin/main", self.fullats_runtime)
        self.assertIn("replica_set_uid", self.fullats_runtime)
        self.assertIn(".imageID | endswith", self.fullats_runtime)
        self.assertIn("Cache-Control: no-cache", self.fullats_runtime)
        self.assertIn("PHASE: pre", self.fullats_browser_workflow)
        self.assertIn("PHASE: post", self.fullats_browser_workflow)
        self.assertIn("id: d29", self.fullats_browser_workflow)
        self.assertIn("bash scripts/ats/d29-smoke.sh", self.fullats_browser_workflow)
        self.assertNotRegex(self.d29, r"curl\s+-[^\n]*k")
        self.assertIn("capturedNetworkFields", self.fullats_browser)
        self.assertIn("redacted.replaceAll(value, marker)", self.fullats_browser)
        self.assertNotIn("containsRawCandidateAccessToken", self.fullats_browser)
        self.assertNotIn("containsRawPasswordOrJwt", self.fullats_browser)

    def test_fullats_live_failure_opens_exact_atomic_gitops_rollback(self):
        self.assertIn("timeout-minutes: 60", self.fullats_browser_workflow)
        self.assertIn("id: preflight", self.fullats_browser_workflow)
        self.assertIn("id: runtime", self.fullats_browser_workflow)
        self.assertIn("id: browser", self.fullats_browser_workflow)
        self.assertIn("id: d29", self.fullats_browser_workflow)
        self.assertIn("id: final-runtime", self.fullats_browser_workflow)
        self.assertIn(
            "steps.d29.outcome == 'failure' || steps.final-runtime.outcome == 'failure'",
            self.fullats_browser_workflow,
        )
        self.assertIn("steps.rollback-checkout.outcome == 'success'", self.fullats_browser_workflow)
        self.assertIn("open-fullats-test-rollback-pr.sh", self.fullats_browser_workflow)
        self.assertIn('PROMOTION_PR: "2617"', self.fullats_browser_workflow)
        self.assertIn('[[ "$FAILED_SHA" == "$merge_sha" ]]', self.rollback_script)
        self.assertIn('[[ "$(git rev-parse origin/main)" == "$FAILED_SHA" ]]', self.rollback_script)
        self.assertIn(
            'branch="auto-fullats-rollback/faz25-fullats-${RUN_ID}-${RUN_ATTEMPT}"',
            self.rollback_script,
        )
        self.assertIn('git show "$PROMOTION_BASE_SHA:$activation"', self.rollback_script)
        self.assertIn('parent_count="$(git rev-list --parents -n 1 "$merge_sha"', self.rollback_script)
        self.assertIn('"$(git rev-parse "$merge_sha^")" != "$PROMOTION_BASE_SHA"', self.rollback_script)
        self.assertIn('git show "$PROMOTION_BASE_SHA:$test_root"', self.rollback_script)
        self.assertIn('git show "$PROMOTION_BASE_SHA:$smoke"', self.rollback_script)
        self.assertIn("printf 'ROLLED_BACK\\n'", self.rollback_script)
        self.assertIn("changed-file set escaped four-file contract", self.rollback_script)
        for digest in (
            "sha256:dce33483d78ffed43e665a8a1c960e6fc3c2fc11ad3a9028a95593a9f5572515",
            "sha256:3a202b36843676768dc74bbacc22328ecfba2de43b7383b9aa401e6e139a5256",
            "sha256:28da39d9402a27d825d637e65e409ecf601cbfd22540add04ce5a3b9bf566b2d",
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
        self.assertIn("reviewed-base artifact", self.rollback_script)
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
            'EXPECTED_FRONTEND_SHA="653752b7bcfb8343b3af0845499a749c4655052c"',
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
            'ATS_EXPECTED_DIGEST="$ATS_OLD" bash "$smoke"',
            self.rollback_script,
        )
        self.assertIn("faz25-fullats-post-rollback-runtime/v1", self.rollback_script)
        self.assertIn("fullats-rollback-evidence-", self.fullats_browser_workflow)
        self.assertIn("üç-artifact compensator", self.runbook)

    def test_fullats_promotion_or_rollback_state_binds_one_exact_artifact_set(self):
        self.assertIn(self.promotion_state, {"PROMOTED", "ROLLED_BACK"})
        promoted = {
            "ats": "sha256:8812ab4eed4881c24e8a8cc7129648d201e064f032dced571d9a56916ad66a11",
            "permission": "sha256:55f2f2f2d1edb3aa67c663c1411b0cc21ab1818d10b4d8d70a5beeeb32ade13d",
            "frontend": "sha256:f23165a53eed9778213ae8af6b1211d3e972e124a03d87fe678a20e97f6fe8b0",
            "tag": "sha-9f82edb",
        }
        rolled_back = {
            "ats": "sha256:dce33483d78ffed43e665a8a1c960e6fc3c2fc11ad3a9028a95593a9f5572515",
            "permission": "sha256:3a202b36843676768dc74bbacc22328ecfba2de43b7383b9aa401e6e139a5256",
            "frontend": "sha256:28da39d9402a27d825d637e65e409ecf601cbfd22540add04ce5a3b9bf566b2d",
            "tag": "sha-653752b",
        }
        expected = promoted if self.promotion_state == "PROMOTED" else rolled_back
        self.assertIn(expected["ats"], self.activation)
        self.assertIn(expected["permission"], self.test_root)
        self.assertIn(expected["frontend"], self.test_root)
        self.assertIn(
            f"image: ghcr.io/halildeu/ats-app-boot@{expected['ats']}",
            self.rendered_test_root,
        )
        self.assertIn(
            "image: ghcr.io/halildeu/platform-backend-permission-service@"
            f"{expected['permission']}",
            self.rendered_test_root,
        )
        self.assertIn(
            "image: ghcr.io/halildeu/platform-web-frontend-testai:"
            f"{expected['tag']}@{expected['frontend']}",
            self.rendered_test_root,
        )
        other = rolled_back if self.promotion_state == "PROMOTED" else promoted
        self.assertNotIn(
            f"image: ghcr.io/halildeu/ats-app-boot@{other['ats']}",
            self.rendered_test_root,
        )
        self.assertNotIn(
            "image: ghcr.io/halildeu/platform-backend-permission-service@"
            f"{other['permission']}",
            self.rendered_test_root,
        )
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
        self.assertIn("Faz 25 #2615 branch-acceptance pini", self.runbook)
        self.assertIn("ATS #183 exact head `f4d2b4f`", self.runbook)
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
        rule = "Durumsal Cross-AI istişare — varsayılan az kanal"
        self.assertIn(rule, self.agents)
        self.assertIn("`Consultation mode: none`", self.agents)
        self.assertIn("(`single`)", self.agents)
        self.assertIn("(`dual`)", self.agents)
        self.assertIn("`claude-opus-4-8`", self.agents)
        self.assertIn("`minimax/MiniMax-M3`", self.agents)
        self.assertIn("`gpt-5.6-sol`", self.agents)
        self.assertIn("toplam iki kanal aşılmaz", self.agents)
        self.assertIn("mümkünse paralel", self.agents)
        self.assertIn("Cursor ve AI uygulama pencereleri istişare yolu değildir", self.agents)
        self.assertIn("consultation governance dosyası", self.agents)
        self.assertIn("audit/evidence enforcement kodunun kendisi `dual` ister", self.agents)
        self.assertIn("Claude implementer kendi receipt'ini", self.agents)
        self.assertIn("provider-distinct ikinci kanal ile `dual` gerekir", self.context_rules)
        self.assertIn("İkincil kanal implementer sağlayıcısıyla da aynı olamaz", self.context_rules)
        self.assertIn("`other` bu iki modda", self.context_rules)
        self.assertIn("P1 is only a concrete merge-blocking", self.minimax_wrapper)
        self.assertIn("otherwise use AGREE even when P2 has suggestions", self.minimax_wrapper)
        self.assertNotIn(
            "Cursor CLI (öncelikli ilave adversarial-review kanalı)", self.agents
        )
        self.assertIn(
            "## 11. Durumsal Cross-AI İstişare — Varsayılan Az Kanal",
            self.context_rules,
        )
        self.assertIn("**`none` — varsayılan:**", self.context_rules)
        self.assertIn("**`single` — gerçekten ikinci görüş gerektiğinde:**", self.context_rules)
        self.assertIn("**`dual` — istisnai yüksek risk:**", self.context_rules)
        self.assertIn("**`claude-opus-4-8`**", self.context_rules)
        self.assertIn("**`minimax/MiniMax-M3`**", self.context_rules)
        self.assertIn("**`gpt-5.6-sol`**", self.context_rules)
        self.assertIn(
            "İstişare bir teslimat ritüeli değil, yalnız karar",
            self.context_rules,
        )
        self.assertIn("JSON `modelUsage`", self.context_rules)
        self.assertIn("Tek ve birincil kanal", self.context_rules)
        self.assertIn("Cursor CLI/MCP/model/harness", self.context_rules)
        self.assertIn("AI uygulama pencereleri istişare kanalı değildir", self.context_rules)
        self.assertIn("irreversible-production", self.context_rules)
        self.assertIn("Path/branch sınıflandırıcısı", self.context_rules)
        self.assertIn("`none` receipt", self.context_rules)
        self.assertIn("`dual` yayın sırası zorunlu değildir", self.context_rules)

if __name__ == "__main__":
    unittest.main()
