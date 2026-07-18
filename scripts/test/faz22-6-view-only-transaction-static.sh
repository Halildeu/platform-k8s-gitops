#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-transaction.yml"
LEGACY_WORKFLOW="$ROOT/.github/workflows/apply-view-only-viewer-pilot-enable.yml"
CONTROLLER="$ROOT/scripts/faz22-remote-ops/view-only-transaction-controller.sh"
STATE_HELPER="$ROOT/scripts/faz22-remote-ops/view_only_transaction_state.py"
BROWSER_EVIDENCE="$ROOT/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
ATTENDED_SMOKE="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
SCHEMA="$ROOT/schema/faz22-6-view-only-transaction-state-v1.schema.json"
WATCHDOG="$ROOT/scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"

for path in "$WORKFLOW" "$LEGACY_WORKFLOW" "$CONTROLLER" "$STATE_HELPER" "$BROWSER_EVIDENCE" "$ATTENDED_SMOKE" "$SCHEMA" "$WATCHDOG"; do
  test -s "$path" || { echo "missing VIEW_ONLY transaction file: $path" >&2; exit 1; }
done

bash -n "$CONTROLLER"
python3 -m json.tool "$SCHEMA" >/dev/null

require() {
  grep -Fq -- "$1" "$2" || {
    echo "missing transaction contract in $2: $1" >&2
    exit 1
  }
}

require 'group: endpoint-admin-remote-bridge-activation' "$WORKFLOW"
require 'group: endpoint-admin-remote-bridge-activation' "$LEGACY_WORKFLOW"
require 'cancel-in-progress: false' "$WORKFLOW"
require 'cancel-in-progress: false' "$LEGACY_WORKFLOW"
# shellcheck disable=SC2016 # Exact GitHub expression is intentionally literal.
require 'if: ${{ !inputs.preflight_only }}' "$WORKFLOW"
require 'name: Verify immutable preflight before any protected decision' "$WORKFLOW"
require 'name: One protected decision, attended evidence and automatic cleanup' "$WORKFLOW"
require 'name: Upload diagnostics before compensating rollback' "$WORKFLOW"
require 'name: Run hash-bound compensating rollback' "$WORKFLOW"
require 'REQUIRE_ACTIVE_GUI: "1"' "$WORKFLOW"
require 'pilotAutoConsent:false' "$WORKFLOW"
require 'screenContentPersisted:false' "$WORKFLOW"
require 'view_only_transaction_state.py transition' "$WORKFLOW"
require 'state-before-rollback.json' "$WORKFLOW"
require 'transaction-failed-clean' "$WORKFLOW"
require 'build-view-only-viewer-collector-diagnostic.sh' "$WORKFLOW"
require 'PREFLIGHT_ARTIFACT_DIR' "$WORKFLOW"
require 'Prepare empty immutable preflight download directory' "$WORKFLOW"
require 'collector-diagnostic.SHA256SUMS' "$WORKFLOW"
require 'Capture every post-authorization failure without skipping cleanup' "$WORKFLOW"
# shellcheck disable=SC2016 # Workflow variables must be matched literally.
require '[ "$PILOT_DEVICE_SHA256" = "$EXPECTED_ENDPOINT_ID_SHA256" ]' "$WORKFLOW"
require 'runs-on: ubuntu-24.04' "$WORKFLOW"
require 'KUBECONFIG: /dev/null' "$WORKFLOW"
require 'cleanup_headroom=900' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact workflow shell expression is intentionally literal.
require 'watchdog_expires_epoch="$(( now_epoch + required ))"' "$WORKFLOW"
require 'TRANSACTION_SCOPED_PERSONAS: "1"' "$WORKFLOW"
require 'keycloak-persona-cleanup.json' "$WORKFLOW"
require 'keycloak-persona-reconciliation.json' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact GitHub expressions are intentionally literal.
require 'OPERATOR_USERNAME: faz226-op-${{ github.run_id }}-${{ github.run_attempt }}' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact GitHub expressions are intentionally literal.
require 'APPROVER_USERNAME: faz226-approver-${{ github.run_id }}-${{ github.run_attempt }}' "$WORKFLOW"
require 'Bind successful artifact upload to transaction ledger' "$WORKFLOW"
require "steps.authorization.outcome == 'success'" "$WORKFLOW"
require '.state == "FAILURE_CAPTURED" or .state == "ARTIFACTS_STAGE_FAILED"' "$WORKFLOW"
require 'ARTIFACTS_STAGE_FAILED' "$WORKFLOW"
require 'Securely remove preflight runner evidence' "$WORKFLOW"
require 'Securely remove transaction runner evidence' "$WORKFLOW"
require 'authorization-failed-before-mutation' "$WORKFLOW"
require 'name: Revalidate live target after approval and before first viewer mutation' "$WORKFLOW"
require 'view-only-transaction-controller.sh revalidate' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact jq/GitHub expressions are intentionally literal.
require '.binding.operatorSha256 == $authorization[0].operatorSha256' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact jq/GitHub expressions are intentionally literal.
require '.binding.deviceSha256 == $authorization[0].deviceSha256' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact jq/GitHub expressions are intentionally literal.
require 'name: ${{ needs.preflight.outputs.preflight_artifact_name }}' "$WORKFLOW"
require 'EXPECTED_PREFLIGHT_RUN_ATTEMPT' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact jq/GitHub expressions are intentionally literal.
require '.payload.minimumAcceptedRenderAckCount == $pilotSeconds' "$WORKFLOW"
require '.payload.renderAckSampleSpanMillis >= .payload.minimumRenderAckSampleSpanMillis' "$WORKFLOW"
# shellcheck disable=SC2016 # Exact jq expression is intentionally literal.
require '.payload.renderAckWindowDurationMillis >= ($pilotSeconds * 1000)' "$WORKFLOW"
require '.payload.renderAckWindowStartGapMillis <= .payload.maximumAllowedRenderAckGapMillis' "$WORKFLOW"
require '.payload.renderAckWindowEndGapMillis <= .payload.maximumAllowedRenderAckGapMillis' "$WORKFLOW"

# shellcheck disable=SC2016 # The workflow variable name must be matched literally.
if grep -Eq '^[[:space:]]+"?\$EVIDENCE_DIR/summary\.json"?[[:space:]]*\\$' "$WORKFLOW"; then
  echo "raw collector summary must not be staged as an artifact" >&2
  exit 1
fi

environment_count="$(grep -Ec '^[[:space:]]{4}environment:$' "$WORKFLOW")"
test "$environment_count" = "1" || {
  echo "VIEW_ONLY transaction must contain exactly one protected Environment job; got $environment_count" >&2
  exit 1
}

preflight_line="$(grep -n '^  preflight:$' "$WORKFLOW" | cut -d: -f1)"
transaction_line="$(grep -n '^  transaction:$' "$WORKFLOW" | cut -d: -f1)"
upload_line="$(grep -n 'name: Upload diagnostics before compensating rollback' "$WORKFLOW" | cut -d: -f1)"
upload_binding_line="$(grep -n 'name: Bind successful artifact upload to transaction ledger' "$WORKFLOW" | cut -d: -f1)"
rollback_line="$(grep -n 'name: Run hash-bound compensating rollback' "$WORKFLOW" | cut -d: -f1)"
test "$preflight_line" -lt "$transaction_line"

preflight_block="$(mktemp /tmp/faz22-view-only-preflight-block.XXXXXX)"
sed -n "${preflight_line},$((transaction_line - 1))p" "$WORKFLOW" > "$preflight_block"
if grep -Eq 'self-hosted|staging-sw|testai-deploy|KC_TEST_ADMIN_PASSWORD|actions/setup-node|playwright|attended-smoke|AUTH_ROUTE_PREFLIGHT_ONLY' "$preflight_block"; then
  rm -f "$preflight_block"
  echo "unprotected preflight must not receive browser or Keycloak mutation authority" >&2
  exit 1
fi
rm -f "$preflight_block"
test "$upload_line" -lt "$rollback_line" || {
  echo "diagnostic artifact upload must precede compensating rollback" >&2
  exit 1
}
test "$upload_line" -lt "$upload_binding_line" && test "$upload_binding_line" -lt "$rollback_line" || {
  echo "artifact upload must be bound to state before compensating rollback" >&2
  exit 1
}

if grep -Eq 'uses: .*apply-view-only-viewer-pilot-(enable|protected)|uses: .*browser-evidence-protected' "$WORKFLOW"; then
  echo "single-run transaction must not dispatch either split protected workflow" >&2
  exit 1
fi

require 'preflight) preflight ;;' "$CONTROLLER"
require 'revalidate) revalidate ;;' "$CONTROLLER"
require 'activate) activate ;;' "$CONTROLLER"
require 'rollback) rollback ;;' "$CONTROLLER"
require 'reclaim-stale) reclaim_stale_watchdog ;;' "$CONTROLLER"
require 'cleanup-owned-watchdog) cleanup_owned_watchdog ;;' "$CONTROLLER"
require 'retire-watchdog-after-clean-surface) retire_watchdog_after_clean_surface ;;' "$CONTROLLER"
require 'verify-clean) verify_clean ;;' "$CONTROLLER"
require 'prior-watchdog-active' "$CONTROLLER"
require 'rollback-ownership-mismatch' "$CONTROLLER"
require 'live-image-digest-mismatch' "$CONTROLLER"
require 'job/faz22-view-only-pilot-watchdog' "$CONTROLLER"
require 'WATCHDOG_CLEANUP_HEADROOM_SECONDS=900' "$CONTROLLER"
require 'WATCHDOG_ACTIVATION_DRIFT_BUDGET_SECONDS=300' "$CONTROLLER"
require 'cleanup-local) cleanup_local ;;' "$CONTROLLER"
require 'verify_watchdog_ownership require-all' "$CONTROLLER"
require 'inspect_stale_watchdog' "$CONTROLLER"
require 'staleWatchdogReclaimed' "$CONTROLLER"
require 'validate_mask_rect_bps' "$CONTROLLER"

exercise_mask_rect_validation() {
  local value DLP_MASK_RECT_BPS
  # shellcheck source=scripts/faz22-remote-ops/view-only-transaction-controller.sh
  source "$CONTROLLER"
  for value in 0,0,10000,10000 7500,7500,2500,2500 0,0,1,1; do
    DLP_MASK_RECT_BPS="$value"
    validate_mask_rect_bps >/dev/null
  done
  for value in 0,0,0,1 0,0,1,0 10001,0,1,1 0,10001,1,1 9999,0,2,1 0,9999,1,2 bad; do
    DLP_MASK_RECT_BPS="$value"
    if validate_mask_rect_bps >/dev/null 2>&1; then
      echo "invalid mask geometry passed: $value" >&2
      exit 1
    fi
  done
}

exercise_mask_rect_validation

preflight_function="$(mktemp /tmp/faz22-view-only-preflight-function.XXXXXX)"
sed -n '/^preflight() {/,/^revalidate() {/p' "$CONTROLLER" > "$preflight_function"
require 'render_static_and_guard' "$preflight_function"
require 'github-hosted-unprivileged-static' "$preflight_function"
if grep -Eq 'inspect_stale_watchdog|verify_surface_clean|reclaim_stale_watchdog|docker|current-context|dry-run=server|/home/.ssh' "$preflight_function"; then
  rm -f "$preflight_function"
  echo "unprotected preflight acquired a live or runner-local capability" >&2
  exit 1
fi
rm -f "$preflight_function"

node --input-type=module - "$BROWSER_EVIDENCE" <<'NODE'
import { pathToFileURL } from 'node:url';

const {
  maximumRenderAckGapMillis,
  maximumRenderAckWindowGapMillis,
  minimumAcceptedRenderAcks,
  minimumRenderAckSampleSpanMillis,
} =
  await import(pathToFileURL(process.argv[2]).href);
const cases = new Map([[300, 300], [600, 600], [900, 900], [1200, 1200], [1800, 1800]]);
for (const [pilotSeconds, expected] of cases) {
  const actual = minimumAcceptedRenderAcks(pilotSeconds);
  if (actual !== expected) throw new Error(`minimumAcceptedRenderAcks(${pilotSeconds})=${actual}, expected ${expected}`);
  const span = minimumRenderAckSampleSpanMillis(pilotSeconds);
  const expectedSpan = (pilotSeconds - 15) * 1_000;
  if (span !== expectedSpan) throw new Error(`minimumRenderAckSampleSpanMillis(${pilotSeconds})=${span}, expected ${expectedSpan}`);
}
for (const invalid of [299, 1801, 300.5, Number.NaN]) {
  let rejected = false;
  try { minimumAcceptedRenderAcks(invalid); } catch { rejected = true; }
  if (!rejected) throw new Error(`invalid pilotSeconds accepted: ${invalid}`);
}
const continuous = Array.from({ length: 300 }, (_, index) => ({
  sampledAtMonotonicMillis: index * 1_000,
}));
if (maximumRenderAckGapMillis(continuous) !== 1_000) {
  throw new Error('continuous ACK samples produced the wrong maximum gap');
}
const exactPilotWindow = continuous.map((sample) => ({
  sampledAtMonotonicMillis: sample.sampledAtMonotonicMillis + 1_000,
}));
if (maximumRenderAckWindowGapMillis(exactPilotWindow, 0, 300_000) !== 1_000) {
  throw new Error('continuous ACK window produced the wrong boundary-aware maximum gap');
}
const prehistoryAndPilot = [
  ...Array.from({ length: 20 }, (_, index) => ({ sampledAtMonotonicMillis: -20_000 + index * 1_000 })),
  ...exactPilotWindow,
];
const filteredPilot = prehistoryAndPilot.filter(
  (sample) => sample.sampledAtMonotonicMillis >= 0 && sample.sampledAtMonotonicMillis <= 300_000,
);
if (maximumRenderAckWindowGapMillis(filteredPilot, 0, 300_000) !== 1_000) {
  throw new Error('pre-pilot ACK history contaminated the exact pilot window');
}
const initialFreeze = exactPilotWindow.filter((sample) => sample.sampledAtMonotonicMillis >= 20_000);
if (maximumRenderAckWindowGapMillis(initialFreeze, 0, 300_000) <= 15_000) {
  throw new Error('initial ACK freeze bypassed the pilot-window boundary guard');
}
const terminalFreeze = exactPilotWindow.filter((sample) => sample.sampledAtMonotonicMillis <= 280_000);
if (maximumRenderAckWindowGapMillis(terminalFreeze, 0, 300_000) <= 15_000) {
  throw new Error('terminal ACK freeze bypassed the pilot-window boundary guard');
}
const burstThenFreeze = [
  ...Array.from({ length: 150 }, (_, index) => ({ sampledAtMonotonicMillis: index * 100 })),
  ...Array.from({ length: 150 }, (_, index) => ({ sampledAtMonotonicMillis: 285_000 + index * 100 })),
];
if (maximumRenderAckGapMillis(burstThenFreeze) <= 15_000) {
  throw new Error('burst-then-freeze ACK samples bypassed the maximum-gap guard');
}
NODE

exercise_keycloak_persona_cleanup() (
  local mode="$1" expected_result="$2" test_root source_tmp
  test_root="$(mktemp -d /tmp/faz22-view-only-persona-cleanup.XXXXXX)"
  # shellcheck source=scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh
  source "$ATTENDED_SMOKE"
  source_tmp="$TMP_DIR"
  trap 'rm -rf "$test_root" "$source_tmp"' EXIT
  EVIDENCE_DIR="$test_root/evidence"
  KC_ADMIN_TOKEN_FILE="$test_root/admin.jwt"
  TMP_DIR="$test_root/tmp"
  TRANSACTION_SCOPED_PERSONAS=1
  install -d -m 0700 "$EVIDENCE_DIR" "$TMP_DIR"
  printf 'masked-test-token' > "$KC_ADMIN_TOKEN_FILE"
  TEMP_PERSONA_IDS=(uid-1 uid-2)
  admin_curl() {
    local _method="$1" _path="$2" out="$3"
    : > "$out"
    if [[ "$mode" == success ]]; then printf '204'; else printf '500'; fi
  }
  if [[ "$expected_result" == success ]]; then
    delete_temporary_personas
    jq -e '.transactionScoped == true and .requested == 2 and .deleted == 2 and .failed == 0 and .verdict == "PASS"' \
      "$EVIDENCE_DIR/keycloak-persona-cleanup.json" >/dev/null
  else
    if delete_temporary_personas; then
      echo "Keycloak persona cleanup failure case unexpectedly passed" >&2
      exit 1
    fi
    jq -e '.transactionScoped == true and .requested == 2 and .deleted == 0 and .failed == 2 and .verdict == "FAIL"' \
      "$EVIDENCE_DIR/keycloak-persona-cleanup.json" >/dev/null
  fi
)

exercise_keycloak_persona_cleanup success success
exercise_keycloak_persona_cleanup failure failure

exercise_keycloak_persona_reconciliation() (
  local mode="$1" test_root source_tmp now_epoch
  test_root="$(mktemp -d /tmp/faz22-view-only-persona-reconcile.XXXXXX)"
  # shellcheck source=scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh
  source "$ATTENDED_SMOKE"
  source_tmp="$TMP_DIR"
  trap 'rm -rf "$test_root" "$source_tmp"' EXIT
  EVIDENCE_DIR="$test_root/evidence"
  TMP_DIR="$test_root/tmp"
  install -d -m 0700 "$EVIDENCE_DIR" "$TMP_DIR"
  now_epoch="$(date -u +%s)"
  admin_curl() {
    local method="$1" path="$2" out="$3"
    case "$method:$path" in
      GET:/users*)
        if [[ "$mode" == malformed ]]; then
          jq -n '[{
            id:"bad-id", username:"faz226-op-100-1",
            attributes:{
              faz22_6_transaction_scoped:["true"],
              faz22_6_transaction_expires_epoch:["not-an-epoch"]
            }
          }]' > "$out"
        else
          jq -n --arg expired "$((now_epoch - 1))" --arg future "$((now_epoch + 600))" '[
            {id:"expired-op", username:"faz226-op-100-1", attributes:{faz22_6_transaction_scoped:["true"], faz22_6_transaction_expires_epoch:[$expired]}},
            {id:"expired-approver", username:"faz226-approver-100-1", attributes:{faz22_6_transaction_scoped:["true"], faz22_6_transaction_expires_epoch:[$expired]}},
            {id:"future-op", username:"faz226-op-101-1", attributes:{faz22_6_transaction_scoped:["true"], faz22_6_transaction_expires_epoch:[$future]}},
            {id:"unowned", username:"faz226-op-99-1", attributes:{}},
            {id:"unrelated", username:"other-user", attributes:{faz22_6_transaction_scoped:["true"], faz22_6_transaction_expires_epoch:[$expired]}}
          ]' > "$out"
        fi
        printf '200'
        ;;
      DELETE:/users/*)
        : > "$out"
        printf '204'
        ;;
      *) return 2 ;;
    esac
  }
  if [[ "$mode" == malformed ]]; then
    if reconcile_expired_transaction_personas >/dev/null 2>&1; then
      echo "malformed owned persona expiry unexpectedly reconciled" >&2
      exit 1
    fi
  else
    reconcile_expired_transaction_personas
    jq -e '
      .requested == 2 and .deleted == 2 and .failed == 0
      and .rawUserIdIncluded == false and .rawCredentialIncluded == false
      and .verdict == "PASS"
    ' "$EVIDENCE_DIR/keycloak-persona-reconciliation.json" >/dev/null
  fi
)

exercise_keycloak_persona_reconciliation success
exercise_keycloak_persona_reconciliation malformed

exercise_stale_watchdog() (
  local mode="$1" expected_result="$2"
  local mock_root
  mock_root="$(mktemp -d /tmp/faz22-view-only-watchdog-mock.XXXXXX)"
  trap 'rm -rf "$mock_root"' EXIT
  : > "$mock_root/deleted"

  # shellcheck source=scripts/faz22-remote-ops/view-only-transaction-controller.sh
  source "$CONTROLLER"
  kubectl() {
    local verb="" kind="" name="" resource="" token ignore_not_found=0 previous=""
    for token in "$@"; do
      [[ "$token" == "--ignore-not-found" ]] && ignore_not_found=1
      if [[ -z "$verb" && ( "$token" == get || "$token" == delete ) ]]; then
        verb="$token"
        previous="$token"
        continue
      fi
      if [[ -n "$verb" && -z "$kind" && "$previous" == "$verb" ]]; then
        kind="$token"
        previous="$token"
        continue
      fi
      if [[ -n "$kind" && -z "$name" && ( "$kind" == configmap || "$kind" == service || "$kind" == networkpolicy ) ]]; then
        name="$token"
      fi
      previous="$token"
    done
    resource="$kind"
    [[ -z "$name" ]] || resource="$kind/$name"

    if [[ "$verb" == delete ]]; then
      printf '%s\n' "$resource" >> "$mock_root/deleted"
      return 0
    fi
    if grep -Fxq "$resource" "$mock_root/deleted"; then
      (( ignore_not_found == 1 )) && return 0
      return 1
    fi
    case "$resource" in
      service/endpoint-admin-remote-bridge-viewer|\
      networkpolicy/eab-bridge-viewer-allow-ingress-8096-from-api-gateway|\
      networkpolicy/eab-api-gateway-allow-egress-8096-to-bridge-viewer)
        return 1
        ;;
      configmap/api-gateway-config|configmap/endpoint-admin-remote-bridge-config-device-key)
        printf '{"data":{}}\n'
        ;;
      job/faz22-view-only-pilot-watchdog)
        if [[ "$mode" == active ]]; then
          printf '{"metadata":{"annotations":{"faz22.6.acik.com/authorization-sha256":"sha256:%064d"}},"status":{"active":1}}\n' 0
        else
          printf '{"metadata":{"annotations":{"faz22.6.acik.com/authorization-sha256":"sha256:%064d"}},"status":{"active":0,"succeeded":1}}\n' 0
        fi
        ;;
      role/faz22-view-only-pilot-watchdog)
        if [[ "$mode" == diverged ]]; then
          printf '{"metadata":{"annotations":{"faz22.6.acik.com/authorization-sha256":"sha256:%064d"}}}\n' 1
        else
          printf '{"metadata":{"annotations":{"faz22.6.acik.com/authorization-sha256":"sha256:%064d"}}}\n' 0
        fi
        ;;
      rolebinding/faz22-view-only-pilot-watchdog|\
      serviceaccount/faz22-view-only-pilot-watchdog|\
      networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api)
        printf '{"metadata":{"annotations":{"faz22.6.acik.com/authorization-sha256":"sha256:%064d"}}}\n' 0
        ;;
      *)
        echo "unexpected mock kubectl resource: $resource" >&2
        return 2
        ;;
    esac
  }

  if [[ "$expected_result" == success ]]; then
    inspect_stale_watchdog
    test "$STALE_WATCHDOG_FOUND" = 1
    test ! -s "$mock_root/deleted"
    reclaim_stale_watchdog
    test "$STALE_WATCHDOG_RECLAIMED" = 1
    test "$(sort -u "$mock_root/deleted" | wc -l | tr -d ' ')" = 5
  else
    if reclaim_stale_watchdog >/dev/null 2>&1; then
      echo "stale watchdog $mode case unexpectedly reclaimed" >&2
      exit 1
    fi
    test ! -s "$mock_root/deleted"
  fi
)

exercise_stale_watchdog terminal success
exercise_stale_watchdog active failure
exercise_stale_watchdog diverged failure

require '"additionalProperties": false' "$SCHEMA"
require '"FAILURE_CAPTURED"' "$SCHEMA"
require '"LIVE_REVALIDATED"' "$SCHEMA"
require '"ARTIFACTS_STAGE_FAILED"' "$SCHEMA"
require '"ARTIFACTS_STAGED"' "$SCHEMA"
require '"ROLLBACK_PENDING"' "$SCHEMA"
require '"FAILED_CLEAN"' "$SCHEMA"

authorization_annotation_count="$(grep -Fc 'faz22.6.acik.com/authorization-sha256: "__AUTHORIZATION_SHA256__"' "$WATCHDOG")"
test "$authorization_annotation_count" = 5 || {
  echo "every watchdog resource must carry the authorization ownership digest" >&2
  exit 1
}
require '"REMOTE_BRIDGE_VIEWER_ENABLED":null' "$WATCHDOG"
if grep -Fq '"REMOTE_BRIDGE_VIEWER_ENABLED":"false"' "$WATCHDOG"; then
  echo "watchdog rollback must remove the viewer key instead of writing a disabled residue" >&2
  exit 1
fi
require 'view-only-transaction-controller.sh reclaim-stale' "$LEGACY_WORKFLOW"
require 'view-only-transaction-controller.sh verify-clean' "$LEGACY_WORKFLOW"
require 'view-only-transaction-controller.sh cleanup-owned-watchdog' "$LEGACY_WORKFLOW"
require 'view-only-transaction-controller.sh retire-watchdog-after-clean-surface' "$LEGACY_WORKFLOW"
if grep -Fq 'delete job faz22-view-only-pilot-watchdog' "$LEGACY_WORKFLOW"; then
  echo "legacy workflow must not bypass watchdog ownership checks" >&2
  exit 1
fi

cleanup_run_id="$(date -u +%s)$$"
cleanup_attempt=91
cleanup_dir="/tmp/faz22-view-only-transaction-${cleanup_run_id}-${cleanup_attempt}"
install -d -m 0700 "$cleanup_dir/nested"
touch "$cleanup_dir/nested/evidence.json"
ln -s /etc/passwd "$cleanup_dir/nested/external-link"
GITHUB_RUN_ID="$cleanup_run_id" GITHUB_RUN_ATTEMPT="$cleanup_attempt" \
  VIEW_ONLY_TRANSACTION_WORK_DIR="$cleanup_dir" bash "$CONTROLLER" cleanup-local
test ! -e "$cleanup_dir"
test -s /etc/passwd
if GITHUB_RUN_ID="$cleanup_run_id" GITHUB_RUN_ATTEMPT="$cleanup_attempt" \
  VIEW_ONLY_TRANSACTION_WORK_DIR=/tmp/not-the-transaction bash "$CONTROLLER" cleanup-local \
  >/dev/null 2>&1; then
  echo "cleanup-local accepted an unexpected directory" >&2
  exit 1
fi

python3 -m unittest tests.faz22_remote_ops.test_view_only_transaction_state -v
echo "faz22-6-view-only-transaction-static-ok"
