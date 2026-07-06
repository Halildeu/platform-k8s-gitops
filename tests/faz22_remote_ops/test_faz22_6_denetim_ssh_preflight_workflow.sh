#!/usr/bin/env bash
# Regression guard for the #1580 Denetim SSH/GUI preflight.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-denetim-ssh-preflight.sh"
WORKFLOW="$ROOT/.github/workflows/faz22-6-denetim-ssh-preflight.yml"

[ -f "$SCRIPT" ] || { echo "missing script: $SCRIPT" >&2; exit 1; }
[ -f "$WORKFLOW" ] || { echo "missing workflow: $WORKFLOW" >&2; exit 1; }

bash -n "$SCRIPT"

help_out="$("$SCRIPT" --help)"
grep -q 'Checks SSH public-key auth and optional active Windows GUI state only' < <(tr '\n' ' ' <<<"$help_out")
grep -q 'not start VIEW_ONLY' <<<"$help_out"

workflow_text="$(cat "$WORKFLOW")"

grep -q 'RUN_FAZ22_6_DENETIM_SSH_PREFLIGHT' <<<"$workflow_text"
grep -q 'runs-on: \[self-hosted, staging-sw, testai-deploy\]' <<<"$workflow_text"
grep -q 'contents: read' <<<"$workflow_text"
grep -q 'issues: write' <<<"$workflow_text"
grep -q 'svc-denetim-agent@10.99.0.2' <<<"$workflow_text"
grep -q 'DEFAULT_DENETIM_SSH_CONFIG="${DEFAULT_DENETIM_SSH_CONFIG:-/home/runner/faz22-6-denetim-ssh/config}"' <<<"$workflow_text"
grep -q 'Upload redacted preflight bundle' <<<"$workflow_text"
grep -q 'does not start VIEW_ONLY' <<<"$workflow_text"
grep -q 'does not write the #1580 engineering marker' <<<"$workflow_text"
grep -q 'does not assert KVKK/DPIA legal signoff' <<<"$workflow_text"

if grep -q 'continue-on-error: true' <<<"$workflow_text"; then
  echo "preflight workflow must not use continue-on-error" >&2
  exit 1
fi

grep -q 'DEFAULT_DENETIM_SSH_IDENTITY="${REPO_ROOT}/../.faz24-i3-ssh/faz24-i3-denetim_ed25519"' "$SCRIPT"
grep -q 'DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-svc-denetim-agent@10.99.0.2}"' "$SCRIPT"
grep -q 'rawGuiOutputRetained: false' "$SCRIPT"
grep -q 'privateKeyLogged: false' "$SCRIPT"
grep -q 'rawSecretLogged: false' "$SCRIPT"
grep -q 'denetim-ssh-key-not-readable' "$SCRIPT"
grep -q 'ssh-auth-publickey' "$SCRIPT"
grep -q 'denetim-gui-session-not-active' "$SCRIPT"
grep -q 'raw_gui_output_retained=false' "$SCRIPT"

if grep -Eq 'cat .*query-user|cat .*qwinsta|Authorization: Bearer|echo .*TOKEN|cat .*TOKEN|PRIVATE KEY' "$SCRIPT" "$WORKFLOW"; then
  echo "preflight must not print raw GUI output, tokens, or private key material" >&2
  exit 1
fi

echo "ok"
