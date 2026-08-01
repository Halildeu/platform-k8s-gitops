#!/usr/bin/env bash
# Regression guard for the #1580 attended VIEW_ONLY product-smoke runner.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-attended-smoke.yml"
BROWSER_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-browser-evidence.yml"
DIAGNOSTIC_SCRIPT="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-collector-diagnostic.sh"
TARGET_PREFLIGHT_SCRIPT="$ROOT/scripts/faz22-remote-ops/verify-view-only-viewer-target.sh"
DIAGNOSTIC_ALLOWLIST="$ROOT/config/faz22-6-viewer-collector-diagnostic-allowlist.v1.json"
BROWSER_DIAGNOSTIC_ALLOWLIST="$ROOT/config/faz22-6-viewer-browser-diagnostic-codes.v1.json"
BROWSER_DIAGNOSTIC_READER="$ROOT/scripts/faz22-remote-ops/read-view-only-viewer-browser-diagnostic.sh"

[ -f "$SCRIPT" ] || { echo "missing script: $SCRIPT" >&2; exit 1; }
[ -f "$WORKFLOW" ] || { echo "missing workflow: $WORKFLOW" >&2; exit 1; }
[ -f "$BROWSER_WORKFLOW" ] || { echo "missing workflow: $BROWSER_WORKFLOW" >&2; exit 1; }
[ -f "$DIAGNOSTIC_SCRIPT" ] || { echo "missing script: $DIAGNOSTIC_SCRIPT" >&2; exit 1; }
[ -f "$TARGET_PREFLIGHT_SCRIPT" ] || { echo "missing script: $TARGET_PREFLIGHT_SCRIPT" >&2; exit 1; }
[ -f "$DIAGNOSTIC_ALLOWLIST" ] || { echo "missing config: $DIAGNOSTIC_ALLOWLIST" >&2; exit 1; }
[ -f "$BROWSER_DIAGNOSTIC_ALLOWLIST" ] || { echo "missing config: $BROWSER_DIAGNOSTIC_ALLOWLIST" >&2; exit 1; }
[ -f "$BROWSER_DIAGNOSTIC_READER" ] || { echo "missing script: $BROWSER_DIAGNOSTIC_READER" >&2; exit 1; }

bash -n "$SCRIPT"
bash -n "$DIAGNOSTIC_SCRIPT"
bash -n "$TARGET_PREFLIGHT_SCRIPT"
bash -n "$BROWSER_DIAGNOSTIC_READER"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
diagnostic_source='70d8286163651805cd5ebd537d3836d02fb1692d'
cat > "$TMP/strict-browser-diagnostic.json" <<JSON
{
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v4",
  "sourceRevision": "$diagnostic_source",
  "failureCode": "browser-binding-invalid",
  "ackTelemetry": null,
  "consoleTelemetry": null,
  "replayHttpStatus": null
}
JSON
[[ "$(bash "$BROWSER_DIAGNOSTIC_READER" \
  "$TMP/strict-browser-diagnostic.json" "$diagnostic_source")" == "browser-binding-invalid" ]]

jq '.failureCode = "browser-replay-not-rejected" | .replayHttpStatus = 405' \
  "$TMP/strict-browser-diagnostic.json" > "$TMP/strict-browser-replay-diagnostic.json"
[[ "$(bash "$BROWSER_DIAGNOSTIC_READER" \
  "$TMP/strict-browser-replay-diagnostic.json" "$diagnostic_source")" == "browser-replay-not-rejected" ]]

jq '.replayHttpStatus = 404' "$TMP/strict-browser-replay-diagnostic.json" \
  > "$TMP/strict-browser-replay-impossible.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-replay-impossible.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted replay-not-rejected with HTTP 404" >&2
  exit 1
fi

jq '.replayHttpStatus = 404' "$TMP/strict-browser-diagnostic.json" \
  > "$TMP/strict-browser-diagnostic-mismatched-fields.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic-mismatched-fields.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted replay status for a non-replay failure" >&2
  exit 1
fi

if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic.json" aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted the wrong source revision" >&2
  exit 1
fi

jq '.schemaVersion = "faz22.6.viewOnlyViewerBrowserDiagnostic.v2"' \
  "$TMP/strict-browser-diagnostic.json" > "$TMP/strict-browser-diagnostic-old-schema.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic-old-schema.json" "$diagnostic_source" \
    >"$TMP/old-schema.out" 2>"$TMP/old-schema.err"; then
  echo "browser diagnostic reader accepted the old schema" >&2
  exit 1
fi
grep -Fxq 'browser-diagnostic-schema-mismatch' "$TMP/old-schema.err"

cat > "$TMP/strict-browser-console-diagnostic.json" <<JSON
{
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v4",
  "sourceRevision": "$diagnostic_source",
  "failureCode": "browser-console-error",
  "ackTelemetry": null,
  "consoleTelemetry": {
    "count": 1,
    "entries": [{
      "category": "http-4xx",
      "kind": "console-error",
      "locationClass": "viewer-api",
      "locationSha256": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "messageSha256": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }],
    "truncatedCount": 0
  },
  "replayHttpStatus": null
}
JSON
[[ "$(bash "$BROWSER_DIAGNOSTIC_READER" \
  "$TMP/strict-browser-console-diagnostic.json" "$diagnostic_source")" == "browser-console-error" ]]

jq '.consoleTelemetry.count = 2' "$TMP/strict-browser-console-diagnostic.json" \
  > "$TMP/strict-browser-console-diagnostic-invalid.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-console-diagnostic-invalid.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted inconsistent console telemetry" >&2
  exit 1
fi

jq '.failureCode = "browser-not-allowlisted"' "$TMP/strict-browser-diagnostic.json" \
  > "$TMP/strict-browser-diagnostic-unknown.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic-unknown.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted an unknown failure code" >&2
  exit 1
fi

jq '.unexpected = "must-fail-closed"' "$TMP/strict-browser-diagnostic.json" \
  > "$TMP/strict-browser-diagnostic-extra.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic-extra.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted an extended schema" >&2
  exit 1
fi

jq '.replayHttpStatus = 99' "$TMP/strict-browser-diagnostic.json" \
  > "$TMP/strict-browser-diagnostic-invalid-status.json"
if bash "$BROWSER_DIAGNOSTIC_READER" \
    "$TMP/strict-browser-diagnostic-invalid-status.json" "$diagnostic_source" >/dev/null 2>&1; then
  echo "browser diagnostic reader accepted an out-of-range replay status" >&2
  exit 1
fi

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
grep -q 'runs-on: \[self-hosted, aiserver, testai-deploy\]' <<<"$workflow_text"
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
grep -q 'name: Resolve immutable protected activation head' <<<"$browser_workflow_text"
grep -q 'git merge-base --is-ancestor "$activation_head_sha" "$GITHUB_SHA"' <<<"$browser_workflow_text"
grep -q 'activation run must predate the evidence run' <<<"$browser_workflow_text"
grep -q 'name: Verify attended endpoint target before approval' <<<"$browser_workflow_text"
grep -q 'needs: activation_head' <<<"$browser_workflow_text"
grep -q 'needs: \[activation_head, target-preflight\]' <<<"$browser_workflow_text"
grep -q 'needs: \[activation_head, target-preflight, product-auth-preflight\]' <<<"$browser_workflow_text"
grep -q 'verify-view-only-viewer-target.sh' <<<"$browser_workflow_text"
grep -q 'name: Re-verify live target after protected approval' <<<"$browser_workflow_text"
# The bootstrap job verifies that the successful protected activation head is
# an ancestor of main. Every producer/reader then checks out and binds evidence
# to that same immutable activation revision even when main advances during a
# human approval wait.
[[ "$(grep -Fc 'uses: actions/checkout@' <<<"$browser_workflow_text")" == "4" ]]
[[ "$(grep -Fc 'ref: ${{ needs.activation_head.outputs.activation_head_sha }}' <<<"$browser_workflow_text")" == "3" ]]
[[ "$(grep -Fc 'SOURCE_REVISION: ${{ needs.activation_head.outputs.activation_head_sha }}' <<<"$browser_workflow_text")" == "3" ]]
[[ "$(grep -Fc -- '--expected-head-sha "$ACTIVATION_HEAD_SHA"' <<<"$browser_workflow_text")" == "1" ]]
if grep -Fq 'SOURCE_REVISION: ${{ github.sha }}' <<<"$browser_workflow_text" \
  || grep -Fq -- '--expected-head-sha "$GITHUB_SHA"' <<<"$browser_workflow_text"; then
  echo "browser evidence must bind to the verified activation head, not moving main" >&2
  exit 1
fi
# VIEWER_URL is assembled inside the trusted runner from a fixed test origin;
# workflow inputs cannot provide an alternate origin, path, or query key.
grep -Fq 'VIEWER_PRODUCT_BASE_URL: https://testai.acik.com' <<<"$browser_workflow_text"
grep -Fq 'VIEWER_URL="${VIEWER_PRODUCT_BASE_URL}/endpoint-admin/remote-access/sessions/${SESSION_ID}/view?streamId=${OPERATION_ID}"' "$SCRIPT"
# A k3d import can expose a local imageID digest while the same CRI content
# record also carries the canonical GHCR repository digest. The attended D30
# gate may accept that case only for the fixed frontend repository, after a
# unique same-record binding; every missing or ambiguous proof stays fatal.
grep -Fq 'faz22.6-viewer-d30-raw-v2' "$SCRIPT"
grep -Fq '[[ "$component" == "web" ]] || fail_smoke "d30-${component}-digest-mismatch"' "$SCRIPT"
grep -Fq 'FRONTEND_REPOSITORY:-ghcr.io/halildeu/platform-web-frontend-testai' "$SCRIPT"
grep -Fq 'select((.repoDigests // []) | index($actual) != null)' "$SCRIPT"
grep -Fq 'select((.repoDigests // []) | index($expected) != null)' "$SCRIPT"
grep -Fq 'd30-web-cri-alias-not-unique' "$SCRIPT"
grep -Fq 'd30-web-cri-alias-content-id-invalid' "$SCRIPT"
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
grep -Fq 'build-view-only-viewer-collector-diagnostic.sh' <<<"$browser_workflow_text"
# shellcheck disable=SC2016 # Assert the forbidden workflow pattern literally.
if grep -Fq -- '--argjson operation "$operation"' <<<"$browser_workflow_text"; then
  echo "browser collector diagnostic must not expose raw operation response in process arguments" >&2
  exit 1
fi
grep -q 'faz22.6.viewOnlyViewerCollectorDiagnostic.v6' "$DIAGNOSTIC_SCRIPT"
grep -q 'failureReasonCode' "$DIAGNOSTIC_SCRIPT"
grep -q 'browserFailureCode' "$DIAGNOSTIC_SCRIPT"
grep -q 'openSessionHttp' "$DIAGNOSTIC_SCRIPT"
grep -q 'open-session-http-404-expected-200' "$DIAGNOSTIC_SCRIPT"
# shellcheck disable=SC2016 # Assert the workflow's literal jq expression.
if grep -Fq 'failureReason:($summary.reason' "$DIAGNOSTIC_SCRIPT"; then
  echo "browser collector diagnostic must not copy free-form failure reason text" >&2
  exit 1
fi
grep -q 'sessionId|deviceId|operatorId|decisionId|operationId|canonicalPayload' "$DIAGNOSTIC_SCRIPT"
grep -q 'BROWSER_DIAGNOSTIC_OUTPUT:' <<<"$browser_workflow_text"
grep -Fq 'BROWSER_DIAGNOSTIC_OUTPUT="${EVIDENCE_DIR}/browser-diagnostic.json"' "$SCRIPT"
grep -Fq 'BROWSER_DIAGNOSTIC_READER="${SCRIPT_DIR}/read-view-only-viewer-browser-diagnostic.sh"' "$SCRIPT"
grep -Fq "printf 'BROWSER_NO_GO code=%s\\n'" "$SCRIPT"
grep -Fq 'every browser failure remains fatal' "$SCRIPT"
diagnostic_step="$(sed -n \
  '/^      - name: Stage redacted collector diagnostic$/,/^      - name: Upload redacted collector diagnostic$/p' \
  "$BROWSER_WORKFLOW")"
grep -q 'browser-diagnostic.json' <<<"$diagnostic_step"
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
grep -Fq 'PG_SECRET_NAME="${PG_SECRET_NAME:-endpoint-admin-remote-bridge-secrets-device-key}"' "$SCRIPT"
[[ "$(grep -Fc 'get secret "$PG_SECRET_NAME"' "$SCRIPT")" == "3" ]]
if grep -Fq 'get secret endpoint-admin-remote-bridge-secrets \' "$SCRIPT"; then
  echo "attended smoke must not read the removed legacy broker secret" >&2
  exit 1
fi
# Persona token validation must consume the exact immutable ID file produced by
# ensure_persona. Deriving a different filename from the username silently
# rejects otherwise-valid JWT subjects before the attended approval gate.
grep -Fq 'local username="$1" user_id_file="$2" token_file="$3" claims_file="$4"' "$SCRIPT"
grep -Fq 'expected_subject_sha="sha256:$(sha256_text "$(cat "$user_id_file")")"' "$SCRIPT"
grep -Fq 'mint_persona_token "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id"' "$SCRIPT"
grep -Fq 'mint_persona_token "$APPROVER_USERNAME" "${TMP_DIR}/approver.id"' "$SCRIPT"
grep -Fq 'mint_persona_token "$matrix_wrong_role_user" "${TMP_DIR}/matrix-wrong-role.id"' "$SCRIPT"
grep -Fq 'mint_persona_token "$matrix_wrong_tenant_user" "${TMP_DIR}/matrix-wrong-tenant.id"' "$SCRIPT"
if grep -Fq 'cat "${TMP_DIR}/${username}.id"' "$SCRIPT"; then
  echo "persona token validation must not derive an unrelated user ID filename" >&2
  exit 1
fi
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
grep -q 'open_session_after_agent_reconnect' "$SCRIPT"
grep -Fq 'OPEN_SESSION_DEVICE_READY_SECONDS: "180"' <<<"$browser_workflow_text"
grep -Fq 'OPEN_SESSION_DEVICE_READY_INTERVAL_SECONDS: "5"' <<<"$browser_workflow_text"
grep -Fq 'if (( SECONDS >= deadline ))' "$SCRIPT"
grep -Fq 'fail_smoke "open-session-device-not-connected-timeout"' "$SCRIPT"
grep -Fq 'fail_smoke "open-session-transport-failure"' "$SCRIPT"
retry_function="$(sed -n \
  '/^open_session_after_agent_reconnect() {$/,/^}$/p' "$SCRIPT")"
grep -Fq '404)' <<<"$retry_function"
# shellcheck disable=SC2016 # Assert the helper's literal shell expression.
grep -Fq 'assert_http "$open_code" 200 "open-session"' <<<"$retry_function"
if grep -Eq '000\)|5[0-9][0-9]\)' <<<"$retry_function"; then
  echo "open-session readiness must retry only the side-effect-free 404 response" >&2
  exit 1
fi
grep -q 'OPERATION_DIAGNOSTIC' "$SCRIPT"
grep -q 'operationDeny' "$SCRIPT"
grep -q 'auto_finalize_if_requested' "$SCRIPT"
grep -q "DEFAULT_DENETIM_SSH_IDENTITY=\"\${REPO_ROOT}/../.faz24-i3-ssh/faz24-i3-denetim_ed25519\"" "$SCRIPT"
grep -q "DENETIM_SSH_TARGET=\"\${DENETIM_SSH_TARGET:-svc-denetim-agent@10.99.0.2}\"" "$SCRIPT"
grep -q "DENETIM_SSH_OPTS=\"\${DENETIM_SSH_OPTS:--i \${DEFAULT_DENETIM_SSH_IDENTITY} -o IdentitiesOnly=yes}\"" "$SCRIPT"
grep -q 'denetim-ssh-key-not-readable' "$SCRIPT"
grep -q "DEFAULT_DENETIM_SSH_CONFIG=\"\${DEFAULT_DENETIM_SSH_CONFIG:-/home/aiadmin/.ssh/config}\"" "$SCRIPT"
grep -q "EXPECTED_DENETIM_SSH_HOSTNAME=\"\${EXPECTED_DENETIM_SSH_HOSTNAME:-10.9.161.202}\"" "$SCRIPT"
grep -q "ssh \"\${opts\\[@\\]}\" -G \"\$DENETIM_SSH_TARGET\"" "$SCRIPT"
grep -q 'EXPECTED_DENETIM_SSH_HOSTNAME: 10.9.161.202' "$BROWSER_WORKFLOW"
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
