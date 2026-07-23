#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKFLOW="${ROOT}/.github/workflows/faz24-gpu-host-exact-sha-rollout.yml"
RUNNER="${ROOT}/scripts/faz24/run_gpu_host_exact_sha_rollout.py"
VERIFIER="${ROOT}/scripts/faz24/verify_gpu_host_exact_sha_rollout_evidence.py"
SCANNER="${ROOT}/scripts/faz24/scan_metadata_evidence.py"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

for file in "${WORKFLOW}" "${RUNNER}" "${VERIFIER}" "${SCANNER}"; do
  [[ -s "${file}" ]] || fail "missing GPU rollout artifact: ${file}"
done

grep -Fq 'environment: testai-product-acceptance' "${WORKFLOW}" || \
  fail 'testai environment approval gate missing'
grep -Fq 'runs-on: [self-hosted, aiserver, testai-deploy]' "${WORKFLOW}" || \
  fail 'canonical self-hosted runner labels missing'
grep -Fq "default: 'RUN_FAZ24_GPU_EXACT_SHA_ROLLOUT'" "${WORKFLOW}" || \
  fail 'explicit confirmation literal missing'
grep -Fq '^[0-9a-f]{40}$' "${WORKFLOW}" || fail 'full lowercase SHA validation missing'
grep -Fq 'merge-base --is-ancestor' "${WORKFLOW}" || fail 'main ancestry guard missing'
grep -Fq 'persist-credentials: false' "${WORKFLOW}" || fail 'checkout credential persistence guard missing'
grep -Fq 'scan_metadata_evidence.py' "${WORKFLOW}" || fail 'portable evidence scanner missing'
grep -Fq 'uses: actions/github-script@v8' "${WORKFLOW}" || \
  fail 'portable GitHub evidence publisher missing'
grep -Fq 'SSH_TARGET: denetim-pc' "${WORKFLOW}" || \
  fail 'governed Denetim operator alias missing'
grep -Fq "if [ \"\${resolved_host}\" != '10.99.0.2' ]; then" "${WORKFLOW}" || \
  fail 'Denetim operator hostname preflight missing'
grep -Fq "if [ \"\${resolved_user}\" != 'denetimpc' ]; then" "${WORKFLOW}" || \
  fail 'Denetim operator user preflight missing'
grep -Fq 'pinned Denetim host-key entry is missing' "${WORKFLOW}" || \
  fail 'known-hosts preflight diagnostic missing'
if grep -Eq '(^|[[:space:]])rg([[:space:]]|$)' "${WORKFLOW}"; then
  fail 'non-portable ripgrep runtime dependency found'
fi
if grep -Fq 'gh issue comment' "${WORKFLOW}"; then
  fail 'non-portable GitHub CLI runtime dependency found'
fi
grep -Fq 'StrictHostKeyChecking=yes' "${RUNNER}" || fail 'strict host-key verification missing'
grep -Fq 'UserKnownHostsFile=' "${RUNNER}" || fail 'explicit pinned known-hosts missing'
grep -Fq 'GlobalKnownHostsFile=/dev/null' "${RUNNER}" || fail 'global host-key bypass guard missing'
grep -Fq 'input=script' "${RUNNER}" || fail 'PowerShell stdin transport missing'
if grep -Fq '"-EncodedCommand"' "${RUNNER}"; then
  fail 'PowerShell script must not be transported in process arguments'
fi
if grep -Fq "'-File', \$UpdateScript" "${RUNNER}" || \
  grep -Fq "'-File', \$MigrationScript" "${RUNNER}"; then
  fail 'Windows PowerShell child scripts must not use -File switch binding'
fi
grep -Fq '$Command | & powershell.exe @arguments' "${RUNNER}" || \
  fail 'Windows PowerShell child stdin transport missing'
grep -Fq 'function ConvertTo-PowerShellLiteral' "${RUNNER}" || \
  fail 'Windows PowerShell child literal escaping helper missing'
grep -Fq "\$ConfirmPreference = ''None''; &" "${RUNNER}" || \
  fail 'Windows PowerShell child confirmation suppression missing'
grep -Fq 'CANONICAL_TARGET = "denetim-pc"' "${RUNNER}" || \
  fail 'canonical Denetim operator target missing'
grep -Fq "scriptPathClass = 'legacy-user-repo'" "${RUNNER}" || \
  fail 'secret-safe legacy task-action classification missing'
grep -Fq 'actionArgumentsSha256' "${RUNNER}" || \
  fail 'task-action metadata hash missing'
grep -Fq 'rollout-principal-not-admin' "${RUNNER}" || \
  fail 'remote administrator guard missing'
grep -Fq 'unexpected-rollout-identity' "${RUNNER}" || \
  fail 'remote identity guard missing'
grep -Fq "C:\\platform-ai" "${RUNNER}" || fail 'canonical GPU deploy clone missing'
grep -Fq "GIT_CONFIG_COUNT = '1'" "${RUNNER}" || \
  fail 'process-local Git config count missing'
grep -Fq "GIT_CONFIG_KEY_0 = 'safe.directory'" "${RUNNER}" || \
  fail 'process-local Git ownership trust missing'
grep -Fq "GIT_CONFIG_VALUE_0 = 'C:/platform-ai'" "${RUNNER}" || \
  fail 'process-local Git safe-directory path missing'
grep -Fq 'Invoke-UpdaterChild -WhatIfOnly' "${RUNNER}" || fail 'WhatIf preflight missing'
grep -Fq "sourceCommitVerified = \$sourceCommitVerified" "${RUNNER}" || \
  fail 'source verification must be derived from updater postconditions'
grep -Fq 'Test-WebSocketReady' "${RUNNER}" || fail 'WebSocket ready proof missing'
grep -Fq "meetingHealth.backend -eq 'ollama'" "${RUNNER}" || \
  fail 'Meeting AI Ollama acceptance guard missing'
grep -Fq "rawAudioIncluded = \$false" "${RUNNER}" || \
  fail 'raw-audio exclusion marker missing'
grep -Fq "transcriptTextIncluded = \$false" "${RUNNER}" || \
  fail 'transcript exclusion marker missing'
if grep -Eq 'StrictHostKeyChecking=no|UserKnownHostsFile=/dev/null' "${RUNNER}"; then
  fail 'SSH host-key bypass found'
fi

python3 -m unittest tests.faz24.test_gpu_host_exact_sha_rollout -v

printf '%s\n' 'PASS: Faz 24 GPU exact-SHA rollout static contract'
