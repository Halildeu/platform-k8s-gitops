#!/usr/bin/env bash
# Regression guard for the #1580 attended VIEW_ONLY product-smoke runner.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-attended-smoke.yml"

[ -f "$SCRIPT" ] || { echo "missing script: $SCRIPT" >&2; exit 1; }
[ -f "$WORKFLOW" ] || { echo "missing workflow: $WORKFLOW" >&2; exit 1; }

bash -n "$SCRIPT"

help_out="$("$SCRIPT" --help)"
grep -Fq 'redacted evidence bundle' <<<"$help_out"
grep -Fq 'EVIDENCE_URL=https://' <<<"$help_out"
grep -Fq 'write #1580' <<<"$help_out"

workflow_text="$(cat "$WORKFLOW")"

grep -q 'RUN_FAZ22_6_VIEW_ONLY_ATTENDED_SMOKE' <<<"$workflow_text"
grep -q 'runs-on: \[self-hosted, staging-sw, testai-deploy\]' <<<"$workflow_text"
grep -q 'contents: read' <<<"$workflow_text"
grep -q 'issues: write' <<<"$workflow_text"
grep -Fq "KC_TEST_ADMIN_PASSWORD: \${{ secrets.KC_TEST_ADMIN_PASSWORD }}" <<<"$workflow_text"
grep -Fq 'EMIT_GITHUB_MASK_COMMANDS: "1"' <<<"$workflow_text"
grep -q 'ADD_TO_PROJECT_PAT || github.token' <<<"$workflow_text"
grep -Fq "[[ \"\$line\" == ::add-mask::* ]]" <<<"$workflow_text"
grep -Fq "tee -a \"\${EVIDENCE_DIR}/workflow-smoke.log\"" <<<"$workflow_text"
grep -q 'Upload redacted evidence bundle' <<<"$workflow_text"
grep -q 'does not write the #1580 acceptance marker' <<<"$workflow_text"
grep -q 'does not assert KVKK/DPIA legal signoff' <<<"$workflow_text"
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
grep -q 'capabilities:\["VIEW_ONLY"\]' "$SCRIPT"
grep -q 'operation:"SCREEN_VIEW"' "$SCRIPT"
grep -q 'capabilities:\["FULL_RDP"\]' "$SCRIPT"
grep -q 'consent-not-granted' "$SCRIPT"
grep -q 'endpoint-agent-consent-log-missing' "$SCRIPT"
grep -q 'screen-view-operation-not-permit' "$SCRIPT"
grep -q 'auto_finalize_if_requested' "$SCRIPT"
grep -q "WHERE chain_id = :'sid'" "$SCRIPT"
grep -q -- "-v \"sid=\${SESSION_ID}\"" "$SCRIPT"

if grep -q 'ssh .* -L' "$SCRIPT" || grep -q 'nc -l' "$SCRIPT"; then
  echo "script must not create endpoint inbound tunnels/listeners" >&2
  exit 1
fi

echo "ok"
