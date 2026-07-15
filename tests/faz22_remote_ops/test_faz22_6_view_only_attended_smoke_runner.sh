#!/usr/bin/env bash
# Regression guard for the #1580 attended VIEW_ONLY product-smoke runner.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-attended-smoke.yml"
BROWSER_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-browser-evidence.yml"

[ -f "$SCRIPT" ] || { echo "missing script: $SCRIPT" >&2; exit 1; }
[ -f "$WORKFLOW" ] || { echo "missing workflow: $WORKFLOW" >&2; exit 1; }
[ -f "$BROWSER_WORKFLOW" ] || { echo "missing workflow: $BROWSER_WORKFLOW" >&2; exit 1; }

bash -n "$SCRIPT"

# Invoke through bash explicitly. macOS provenance/endpoint controls can kill a
# directly executed worktree script before its shebang runs, which is unrelated
# to the Linux self-hosted runner contract this regression guard validates.
help_out="$(bash "$SCRIPT" --help)"
grep -Fq 'redacted evidence bundle' <<<"$help_out"
grep -Fq 'EVIDENCE_URL=https://' <<<"$help_out"
grep -Fq 'write #1580' <<<"$help_out"

workflow_text="$(cat "$WORKFLOW")"
browser_workflow_text="$(cat "$BROWSER_WORKFLOW")"

grep -q 'RUN_FAZ22_6_VIEW_ONLY_ATTENDED_SMOKE' <<<"$workflow_text"
grep -q 'empty derives from rendered overlay SSOT' <<<"$workflow_text"
grep -q 'runs-on: \[self-hosted, staging-sw, testai-deploy\]' <<<"$workflow_text"
grep -q 'contents: read' <<<"$workflow_text"
grep -q 'issues: write' <<<"$workflow_text"
grep -Fq "KC_TEST_ADMIN_PASSWORD: \${{ secrets.KC_TEST_ADMIN_PASSWORD }}" <<<"$workflow_text"
grep -Fq 'EMIT_GITHUB_MASK_COMMANDS: "1"' <<<"$workflow_text"
# shellcheck disable=SC2016 # Assert the workflow's literal shell expression.
grep -q 'DEFAULT_DENETIM_SSH_CONFIG="${DEFAULT_DENETIM_SSH_CONFIG:-/home/runner/faz22-6-denetim-ssh/config}"' <<<"$workflow_text"
grep -q 'ADD_TO_PROJECT_PAT || github.token' <<<"$workflow_text"
grep -Fq "[[ \"\$line\" == ::add-mask::* ]]" <<<"$workflow_text"
grep -Fq "tee -a \"\${EVIDENCE_DIR}/workflow-smoke.log\"" <<<"$workflow_text"
grep -q 'Upload redacted evidence bundle' <<<"$workflow_text"
grep -q 'does not write the #1580 acceptance marker' <<<"$workflow_text"
grep -q 'does not assert KVKK/DPIA legal signoff' <<<"$workflow_text"
grep -q 'Stage redacted collector diagnostic' <<<"$browser_workflow_text"
grep -q 'Upload redacted collector diagnostic' <<<"$browser_workflow_text"
# shellcheck disable=SC2016 # Assert the workflow expression literally.
if [[ "$(grep -A3 'name: Stage redacted collector diagnostic' "$BROWSER_WORKFLOW" \
    | grep -Fc 'if: ${{ always() }}')" != "1" ]]; then
  echo "browser collector diagnostic staging must run under always()" >&2
  exit 1
fi
# shellcheck disable=SC2016 # Assert the workflow expression literally.
if [[ "$(grep -A2 'name: Upload redacted collector diagnostic' "$BROWSER_WORKFLOW" \
    | grep -Fc "if: \${{ always() && steps.stage-diagnostic.outcome == 'success' }}")" != "1" ]]; then
  echo "browser collector diagnostic upload must require successful redaction validation" >&2
  exit 1
fi
# shellcheck disable=SC2016 # Assert the workflow shell variables literally.
grep -Fq -- '--slurpfile operation "$operation_path"' <<<"$browser_workflow_text"
# shellcheck disable=SC2016 # Assert the forbidden workflow pattern literally.
if grep -Fq -- '--argjson operation "$operation"' <<<"$browser_workflow_text"; then
  echo "browser collector diagnostic must not expose raw operation response in process arguments" >&2
  exit 1
fi
grep -Fq "grep -Eiq 'bearer|BEGIN .*PRIVATE KEY" <<<"$browser_workflow_text"
grep -q 'faz22.6.viewOnlyViewerCollectorDiagnostic.v1' <<<"$browser_workflow_text"
grep -q 'sessionId|deviceId|operatorId|decisionId|operationId|canonicalPayload' <<<"$browser_workflow_text"
diagnostic_step="$(sed -n \
  '/^      - name: Stage redacted collector diagnostic$/,/^      - name: Upload redacted collector diagnostic$/p' \
  "$BROWSER_WORKFLOW")"
if grep -Eq '\.permit|\.sessionId|\.deviceId|\.operatorId|\.decisionId|\.operationId|\.canonicalPayload' \
    <<<"$diagnostic_step"; then
  echo "redacted browser diagnostic must not select permit or raw identity fields" >&2
  exit 1
fi
if grep -q 'continue-on-error: true' <<<"$workflow_text"; then
  echo "workflow must not use continue-on-error for the smoke step" >&2
  exit 1
fi

if grep -Eq 'cat .*\\.jwt|sed -n .*jwt|echo .*TOKEN|Authorization: Bearer \\$\\{' "$WORKFLOW"; then
  echo "workflow appears to print token material" >&2
  exit 1
fi

grep -q 'endpoint-agent-relevant.log' "$SCRIPT"
grep -q 'broker-relevant.log' "$SCRIPT"
grep -q 'recording.tsv' "$SCRIPT"
grep -q 'summary.json' "$SCRIPT"
grep -q 'SHA256SUMS' "$SCRIPT"
grep -q '! -name workflow-smoke.log' "$SCRIPT"
grep -q 'lib-remote-bridge-digest.sh' "$SCRIPT"
grep -q 'rbd_expected_digest' "$SCRIPT"
grep -q 'expected-digest-derive-overlay-drift' "$SCRIPT"
grep -q 'capabilities:\["VIEW_ONLY"\]' "$SCRIPT"
grep -q 'operation:"SCREEN_VIEW"' "$SCRIPT"
grep -q 'capabilities:\["FULL_RDP"\]' "$SCRIPT"
grep -q 'consent-not-granted' "$SCRIPT"
grep -q 'endpoint-agent-consent-log-missing' "$SCRIPT"
grep -q 'screen-view-operation-not-permit' "$SCRIPT"
grep -q 'OPERATION_DIAGNOSTIC' "$SCRIPT"
grep -q 'operationDeny' "$SCRIPT"
grep -q 'auto_finalize_if_requested' "$SCRIPT"
grep -q "DEFAULT_DENETIM_SSH_IDENTITY=\"\${REPO_ROOT}/../.faz24-i3-ssh/faz24-i3-denetim_ed25519\"" "$SCRIPT"
grep -q "DENETIM_SSH_TARGET=\"\${DENETIM_SSH_TARGET:-svc-denetim-agent@10.99.0.2}\"" "$SCRIPT"
grep -q "DENETIM_SSH_OPTS=\"\${DENETIM_SSH_OPTS:--i \${DEFAULT_DENETIM_SSH_IDENTITY} -o IdentitiesOnly=yes}\"" "$SCRIPT"
grep -q 'denetim-ssh-key-not-readable' "$SCRIPT"
grep -q "DEFAULT_DENETIM_SSH_CONFIG=\"\${DEFAULT_DENETIM_SSH_CONFIG:-/home/halil/.ssh/config}\"" "$SCRIPT"
grep -q "ssh \"\${opts\\[@\\]}\" -G \"\$DENETIM_SSH_TARGET\"" "$SCRIPT"
grep -q 'denetim-ssh-alias-missing-identity' "$SCRIPT"
grep -q "WHERE chain_id = :'sid'" "$SCRIPT"
grep -q -- "-v \"sid=\${SESSION_ID}\"" "$SCRIPT"

if grep -Fq '54f56a2f38a769a5dd739b40c66aabe244c2a887852f464cf9fce6eea2c234c5' "$SCRIPT" "$WORKFLOW"; then
  echo "script/workflow must derive the remote-bridge expected digest from the overlay SSOT, not hardcode the stale 54f digest" >&2
  exit 1
fi

if grep -q 'ssh .* -L' "$SCRIPT" || grep -q 'nc -l' "$SCRIPT"; then
  echo "script must not create endpoint inbound tunnels/listeners" >&2
  exit 1
fi

echo "ok"
