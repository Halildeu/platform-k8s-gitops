#!/usr/bin/env bash
# Static and smoke guards for the artifact-only Faz 22.6 acceptance package workflows.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
B1_WORKFLOW="$ROOT/.github/workflows/faz22-6-b1-4-acceptance-package.yml"
VIEW_ONLY_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-engineering-evidence-package.yml"
B1_HELPER="$ROOT/scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh"
VIEW_ONLY_HELPER="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh"
VIEWER_PRODUCT_VERIFIER="$ROOT/scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
VIEWER_PRODUCT_ASSEMBLER="$ROOT/scripts/faz22-remote-ops/assemble-view-only-viewer-product-evidence.py"
VIEWER_PRODUCT_VERIFY_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-product-evidence-verify.yml"
VIEWER_PRODUCT_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-product-evidence.yml"
VIEWER_BROWSER_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-browser-evidence.yml"
VIEWER_BROWSER_EVIDENCE="$ROOT/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
VIEWER_OPERATOR_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-operator-evidence.yml"
VIEWER_OPERATOR_PRODUCER="$ROOT/scripts/faz22-remote-ops/produce-view-only-viewer-operator-evidence.py"
VIEWER_D30_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-d30-evidence.yml"
VIEWER_D30_PRODUCER="$ROOT/scripts/faz22-remote-ops/produce-view-only-viewer-d30-evidence.py"
VIEWER_BROKER_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-broker-evidence.yml"
VIEWER_BROKER_PRODUCER="$ROOT/scripts/faz22-remote-ops/produce-view-only-viewer-broker-evidence.py"
VIEWER_AUDIT_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-audit-evidence.yml"
VIEWER_AUDIT_PRODUCER="$ROOT/scripts/faz22-remote-ops/produce-view-only-viewer-audit-evidence.py"
VIEWER_AUDIT_BUILDER="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-audit-summary.py"
VIEWER_MATRIX_COLLECTOR_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-matrix-collector.yml"
VIEWER_NEGATIVE_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-negative-evidence.yml"
VIEWER_NEGATIVE_COLLECTOR="$ROOT/scripts/faz22-remote-ops/collect-view-only-viewer-negative-matrix.sh"
VIEWER_TERMINATION_COLLECTOR_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-termination-collector.yml"
VIEWER_TERMINATION_WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-termination-evidence.yml"
VIEWER_TERMINATION_COLLECTOR="$ROOT/scripts/faz22-remote-ops/collect-view-only-viewer-termination-case.sh"
VIEWER_TERMINATION_AUDIT="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-termination-audit.py"
VIEWER_MATRIX_PRODUCER="$ROOT/scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py"
VIEWER_SOURCE_COMMON="$ROOT/scripts/faz22-remote-ops/view_only_viewer_source_common.py"
VIEWER_FRAME_FLOW_BUILDER="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-frame-flow-summary.py"
VIEWER_PRODUCT_ROOT_SCHEMA="$ROOT/schema/faz22-6-view-only-viewer-product-evidence-root-v2.schema.json"
VIEWER_PRODUCT_CHILD_SCHEMA="$ROOT/schema/faz22-6-view-only-viewer-product-evidence-child-v2.schema.json"
VIEWER_APPLY_WORKFLOW="$ROOT/.github/workflows/apply-view-only-viewer-pilot-enable.yml"
VIEWER_AUDIT_DB_ROLE_RECONCILER="$ROOT/scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh"
VIEWER_ROLLBACK_CONFIG="$ROOT/scripts/faz22-remote-ops/rollback-view-only-viewer-pilot-config.sh"
VIEWER_WATCHDOG="$ROOT/scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"
VIEWER_AUTH_BUILDER="$ROOT/scripts/faz22-remote-ops/build-view-only-pilot-owner-authorization.py"
VIEWER_AUTH_VERIFIER="$ROOT/scripts/faz22-remote-ops/verify-view-only-pilot-authorization-receipt.py"
VIEWER_AUTH_COMMON="$ROOT/scripts/faz22-remote-ops/view_only_pilot_authorization_common.py"
VIEWER_EXACT_ZIP="$ROOT/scripts/faz22-remote-ops/extract-exact-zip.py"
VIEWER_OWNER_POLICY="$ROOT/config/faz22-6-view-only-pilot-owner-policy.v1.json"
VIEWER_REVOCATIONS="$ROOT/config/faz22-6-view-only-pilot-authorization-revocations.v1.json"
VIEWER_DEVICE_KEY_CONFIG="$ROOT/kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key/configmap-device-key-patch.yaml"
VIEWER_CONFIG_PATCH="$ROOT/kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer/configmap-viewer-patch.yaml"
VIEWER_ARGO_APPLICATION="$ROOT/argocd/applications/platform-test.yaml"

future_date_utc() {
  local days="$1"
  if date -u -d "+$days days" +%F >/dev/null 2>&1; then
    date -u -d "+$days days" +%F
    return
  fi
  case "$days" in
    -*) date -u -v"${days}"d +%F ;;
    *) date -u -v+"$days"d +%F ;;
  esac
}

require_file() {
  local path="$1"
  [ -f "$path" ] || {
    echo "missing required file: $path" >&2
    exit 1
  }
}

require_grep() {
  local pattern="$1" path="$2"
  grep -Fq -- "$pattern" "$path" || {
    echo "missing expected pattern in $path: $pattern" >&2
    exit 1
  }
}

verify_viewer_resource_normalizer() {
  local filter normalized
  filter='{apiVersion:"v1", kind:"List", items:[.[]
    | if (.kind == "List" and (.items | type) == "array")
      then .items[]
      else .
      end]}'

  normalized="$({
    printf '%s\n' '{"apiVersion":"v1","kind":"Service","metadata":{"name":"viewer"}}'
    printf '%s\n' '{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"bridge"}}'
  } | jq -cs "$filter")"
  jq -e '
    .apiVersion == "v1" and .kind == "List" and (.items | length) == 2
    and [.items[].kind] == ["Service", "Deployment"]
  ' <<<"$normalized" >/dev/null

  normalized="$(printf '%s\n' \
    '{"apiVersion":"v1","kind":"List","items":[{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"viewer-config"}}]}' \
    | jq -cs "$filter")"
  jq -e '
    .apiVersion == "v1" and .kind == "List" and (.items | length) == 1
    and .items[0].kind == "ConfigMap"
    and .items[0].metadata.name == "viewer-config"
  ' <<<"$normalized" >/dev/null
}

for path in "$B1_WORKFLOW" "$VIEW_ONLY_WORKFLOW" "$B1_HELPER" "$VIEW_ONLY_HELPER" \
  "$VIEWER_PRODUCT_VERIFIER" "$VIEWER_PRODUCT_ASSEMBLER" \
  "$VIEWER_PRODUCT_VERIFY_WORKFLOW" "$VIEWER_PRODUCT_WORKFLOW" "$VIEWER_BROWSER_WORKFLOW" \
  "$VIEWER_BROWSER_EVIDENCE" \
  "$VIEWER_OPERATOR_WORKFLOW" "$VIEWER_OPERATOR_PRODUCER" \
  "$VIEWER_D30_WORKFLOW" "$VIEWER_D30_PRODUCER" "$VIEWER_SOURCE_COMMON" "$VIEWER_FRAME_FLOW_BUILDER" \
  "$VIEWER_BROKER_WORKFLOW" "$VIEWER_BROKER_PRODUCER" \
  "$VIEWER_AUDIT_WORKFLOW" "$VIEWER_AUDIT_PRODUCER" "$VIEWER_AUDIT_BUILDER" \
  "$VIEWER_MATRIX_COLLECTOR_WORKFLOW" "$VIEWER_NEGATIVE_WORKFLOW" \
  "$VIEWER_NEGATIVE_COLLECTOR" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW" \
  "$VIEWER_TERMINATION_WORKFLOW" "$VIEWER_TERMINATION_COLLECTOR" \
  "$VIEWER_TERMINATION_AUDIT" "$VIEWER_MATRIX_PRODUCER" \
  "$VIEWER_PRODUCT_ROOT_SCHEMA" "$VIEWER_PRODUCT_CHILD_SCHEMA" \
  "$VIEWER_APPLY_WORKFLOW" "$VIEWER_ROLLBACK_CONFIG" "$VIEWER_WATCHDOG" \
  "$VIEWER_AUTH_BUILDER" "$VIEWER_AUTH_VERIFIER" "$VIEWER_AUTH_COMMON" \
  "$VIEWER_EXACT_ZIP" \
  "$VIEWER_OWNER_POLICY" "$VIEWER_REVOCATIONS" "$VIEWER_DEVICE_KEY_CONFIG" \
  "$VIEWER_CONFIG_PATCH" "$VIEWER_ARGO_APPLICATION"; do
  require_file "$path"
done

bash -n "$B1_HELPER" "$VIEW_ONLY_HELPER" "$VIEWER_NEGATIVE_COLLECTOR" \
  "$VIEWER_TERMINATION_COLLECTOR" "$VIEWER_ROLLBACK_CONFIG"
python3 -m py_compile "$VIEWER_PRODUCT_VERIFIER" "$VIEWER_PRODUCT_ASSEMBLER" \
  "$VIEWER_OPERATOR_PRODUCER" "$VIEWER_D30_PRODUCER" \
  "$VIEWER_BROKER_PRODUCER" "$VIEWER_AUDIT_PRODUCER" "$VIEWER_AUDIT_BUILDER" \
  "$VIEWER_MATRIX_PRODUCER" "$VIEWER_TERMINATION_AUDIT" \
  "$VIEWER_SOURCE_COMMON" "$VIEWER_FRAME_FLOW_BUILDER" \
  "$VIEWER_AUTH_BUILDER" "$VIEWER_AUTH_VERIFIER" "$VIEWER_AUTH_COMMON"
python3 -m py_compile "$VIEWER_EXACT_ZIP"
jq -e '.additionalProperties == false' "$VIEWER_PRODUCT_ROOT_SCHEMA" >/dev/null
jq -e '.additionalProperties == false and (.allOf | length) == 7' "$VIEWER_PRODUCT_CHILD_SCHEMA" >/dev/null

require_grep "permissions:" "$B1_WORKFLOW"
require_grep "contents: read" "$B1_WORKFLOW"
require_grep "workflow_dispatch:" "$B1_WORKFLOW"
require_grep "PREPARE_FAZ22_6_B1_4_ACCEPTANCE_PACKAGE" "$B1_WORKFLOW"
require_grep "ACK_REAL_HARDWARE_ATTESTATION_EVIDENCE_EXISTS" "$B1_WORKFLOW"
require_grep "ACK_BOUNDED_RISK_OWNER_ACCEPTED" "$B1_WORKFLOW"
require_grep "scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh" "$B1_WORKFLOW"
require_grep "actions/upload-artifact@v4" "$B1_WORKFLOW"
require_grep "writes_github_issues: false" "$B1_WORKFLOW"
require_grep "contains_secrets: false" "$B1_WORKFLOW"

require_grep "permissions:" "$VIEW_ONLY_WORKFLOW"
require_grep "contents: read" "$VIEW_ONLY_WORKFLOW"
require_grep "workflow_dispatch:" "$VIEW_ONLY_WORKFLOW"
require_grep "PREPARE_FAZ22_6_VIEW_ONLY_ENGINEERING_EVIDENCE_PACKAGE" "$VIEW_ONLY_WORKFLOW"
require_grep "ACK_VIEW_ONLY_ENGINEERING_CONTROLS_VERIFIED" "$VIEW_ONLY_WORKFLOW"
require_grep "scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh" "$VIEW_ONLY_WORKFLOW"
require_grep "--recording-mode disabled" "$VIEW_ONLY_WORKFLOW"
require_grep 'canonical_manifest="$(jq -cS . "$manifest")"' "$VIEW_ONLY_WORKFLOW"
require_grep 'manifest_sha="$(printf' "$VIEW_ONLY_WORKFLOW"
require_grep "actions/upload-artifact@v4" "$VIEW_ONLY_WORKFLOW"
require_grep "writes_github_issues: false" "$VIEW_ONLY_WORKFLOW"
require_grep "contains_secrets: false" "$VIEW_ONLY_WORKFLOW"

require_grep "actions: read" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"
require_grep "VERIFY_FAZ22_6_VIEW_ONLY_VIEWER_PRODUCT_EVIDENCE" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"
require_grep "--run-id" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"
require_grep "--marker-out" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"
require_grep "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"
require_grep "renderLossRate <= 0.05" "$VIEWER_PRODUCT_VERIFY_WORKFLOW"

require_grep "actions: read" "$VIEWER_PRODUCT_WORKFLOW"
require_grep "ASSEMBLE_FAZ22_6_VIEW_ONLY_VIEWER_PRODUCT_EVIDENCE" "$VIEWER_PRODUCT_WORKFLOW"
require_grep "assemble-view-only-viewer-product-evidence.py" "$VIEWER_PRODUCT_WORKFLOW"
require_grep "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" "$VIEWER_PRODUCT_WORKFLOW"

require_grep "name: faz22-view-only-pilot" "$VIEWER_BROWSER_WORKFLOW"
require_grep "activation_run_id" "$VIEWER_BROWSER_WORKFLOW"
require_grep "protected-authorization.json" "$VIEWER_BROWSER_WORKFLOW"
require_grep "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6" "$VIEWER_BROWSER_WORKFLOW"
require_grep 'const VIEWER_INPUT_CONTROL_SELECTOR = [' "$VIEWER_BROWSER_EVIDENCE"
require_grep "'iframe'," "$VIEWER_BROWSER_EVIDENCE"
require_grep "'[contenteditable]:not([contenteditable=\"false\"])'," "$VIEWER_BROWSER_EVIDENCE"
require_grep 'root.locator(VIEWER_INPUT_CONTROL_SELECTOR).count()' "$VIEWER_BROWSER_EVIDENCE"
require_grep 'root.getByRole('\''button'\'').count()' "$VIEWER_BROWSER_EVIDENCE"
require_grep 'root.getByTestId('\''remote-view-stop'\'').count()' "$VIEWER_BROWSER_EVIDENCE"
require_grep 'interactive !== 0 || buttons !== 1 || stopButtons !== 1' "$VIEWER_BROWSER_EVIDENCE"
if grep -Fq 'page.locator(VIEWER_INPUT_CONTROL_SELECTOR)' "$VIEWER_BROWSER_EVIDENCE" \
  || grep -Fq "page.getByRole('button').count()" "$VIEWER_BROWSER_EVIDENCE" \
  || grep -Fq "page.getByTestId('remote-view-stop').count()" "$VIEWER_BROWSER_EVIDENCE"; then
  echo "VIEW_ONLY input isolation must be measured inside the viewer root, not the product shell" >&2
  exit 1
fi
if grep -Fq 'faz22-6-view-only-viewer-browser-collector-' "$VIEWER_BROWSER_WORKFLOW" \
  || grep -Eq 'path:.*faz22-viewer-browser-collector/?$' "$VIEWER_BROWSER_WORKFLOW"; then
  echo "raw VIEW_ONLY collector must never be uploaded as a GitHub artifact" >&2
  exit 1
fi
require_grep 'faz22-6-view-only-viewer-runtime-snapshots-${{ github.run_id }}' "$VIEWER_BROWSER_WORKFLOW"
require_grep "metrics-before.prom metrics-after.prom d30-snapshot.json frame-flow-summary.json audit-summary.json" "$VIEWER_BROWSER_WORKFLOW"
require_grep "sha256sum -c SHA256SUMS" "$VIEWER_BROWSER_WORKFLOW"
require_grep 'CONSENT_WAIT_SECONDS: "240"' "$VIEWER_BROWSER_WORKFLOW"
# shellcheck disable=SC2016 # Assert the workflow's literal headroom expression.
require_grep 'required="$(( PILOT_SECONDS + CONSENT_WAIT_SECONDS + OPEN_SESSION_DEVICE_READY_SECONDS + 120 ))"' \
  "$VIEWER_BROWSER_WORKFLOW"
require_grep 'OPEN_SESSION_DEVICE_READY_SECONDS: "180"' "$VIEWER_BROWSER_WORKFLOW"
python3 - "$VIEWER_DEVICE_KEY_CONFIG" "$VIEWER_CONFIG_PATCH" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
viewer_path = pathlib.Path(sys.argv[2])
viewer_text = viewer_path.read_text(encoding="utf-8")
prompt_matches = re.findall(
    r'(?m)^  REMOTE_BRIDGE_CONSENT_PROMPT_TTL_MILLIS: "([0-9]+)"$', text
)
permit_matches = re.findall(
    r'(?m)^  REMOTE_BRIDGE_BROKER_PERMIT_TTL_MILLIS: "([0-9]+)"$', text
)
view_only_permit_matches = re.findall(
    r'(?m)^  REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS: "([0-9]+)"$',
    viewer_text,
)
if prompt_matches != ["240000"]:
    raise SystemExit(
        f"test-only attended consent prompt TTL must occur exactly once as 240000ms: {path}"
    )
if int(prompt_matches[0]) > 300000:
    raise SystemExit(f"attended consent prompt TTL exceeds the 300000ms ceiling: {path}")
if permit_matches != ["60000"]:
    raise SystemExit(
        f"constrained PTY permit TTL must remain exactly 60000ms: {path}"
    )
if view_only_permit_matches != ["600000"]:
    raise SystemExit(
        f"owner-gated VIEW_ONLY permit TTL must occur exactly once as 600000ms: {viewer_path}"
    )
PY
require_grep 'REMOTE_BRIDGE_CONSENT_PROMPT_TTL_MILLIS: "240000"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'REMOTE_BRIDGE_BROKER_PERMIT_TTL_MILLIS: "60000"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS: "600000"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'printenv REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS' "$VIEWER_APPLY_WORKFLOW"
require_grep 'broker runtime did not load the owner-gated 600000ms VIEW_ONLY permit TTL' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep "attended consent pilot TTL leaked into the synced test Argo root" "$VIEWER_APPLY_WORKFLOW"
require_file "$VIEWER_AUDIT_DB_ROLE_RECONCILER"
bash -n "$VIEWER_AUDIT_DB_ROLE_RECONCILER"
require_grep "reconcile-viewer-audit-db-role.sh apply" "$VIEWER_APPLY_WORKFLOW"
require_grep "VIEWER_AUDIT_DB_ROLE_CONFIRM: RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE" \
  "$VIEWER_APPLY_WORKFLOW"
require_grep "Verify least-privilege VIEW_ONLY audit DB role before approval" \
  "$VIEWER_BROWSER_WORKFLOW"
require_grep "Re-verify VIEW_ONLY audit DB role after protected approval" \
  "$VIEWER_BROWSER_WORKFLOW"

for workflow in "$VIEWER_BROWSER_WORKFLOW" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW" \
  "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"; do
  python3 - "$workflow" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
profile = re.compile(
    r"(?m)^(?P<indent>[ ]+)DENETIM_SSH_TARGET: denetim-pc\n"
    r"(?P=indent)DEFAULT_DENETIM_SSH_CONFIG: /home/aiadmin/\.ssh/config\n"
    r"(?P=indent)DENETIM_SSH_OPTS: __SSH_CONFIG__$"
)
matches = profile.findall(text)
if len(matches) != 1:
    raise SystemExit(
        f"VIEW_ONLY collector must contain exactly one adjacent canonical Denetim SSH env profile: {path}"
    )
if "DENETIM_SSH_TARGET: svc-denetim-agent@10.99.0.2" in text:
    raise SystemExit(
        f"VIEW_ONLY collector must not restore the non-functional least-privilege target: {path}"
    )
PY

  require_grep "source scripts/faz22-remote-ops/lib-github-read-api.sh" "$workflow"
  require_grep "github_read_api_preflight" "$workflow"
  if grep -Eq '^[[:space:]]*gh api ' "$workflow"; then
    echo "protected VIEW_ONLY collector must not require gh on the minimal runner: $workflow" >&2
    exit 1
  fi
  require_grep "scripts/faz22-remote-ops/extract-exact-zip.py" "$workflow"
  if grep -Eq '^[[:space:]]*unzip ' "$workflow"; then
    echo "protected VIEW_ONLY collector must not require unzip on the minimal runner: $workflow" >&2
    exit 1
  fi
done

require_grep "actions: read" "$VIEWER_OPERATOR_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_OPERATOR_EVIDENCE" "$VIEWER_OPERATOR_WORKFLOW"
require_grep "produce-view-only-viewer-operator-evidence.py" "$VIEWER_OPERATOR_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-operator-evidence-${{ github.run_id }}' "$VIEWER_OPERATOR_WORKFLOW"

require_grep "actions: read" "$VIEWER_D30_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_D30_EVIDENCE" "$VIEWER_D30_WORKFLOW"
require_grep "produce-view-only-viewer-d30-evidence.py" "$VIEWER_D30_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-d30-evidence-${{ github.run_id }}' "$VIEWER_D30_WORKFLOW"

require_grep "actions: read" "$VIEWER_BROKER_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_BROKER_EVIDENCE" "$VIEWER_BROKER_WORKFLOW"
require_grep "produce-view-only-viewer-broker-evidence.py" "$VIEWER_BROKER_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-broker-evidence-${{ github.run_id }}' "$VIEWER_BROKER_WORKFLOW"

require_grep "actions: read" "$VIEWER_AUDIT_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_AUDIT_EVIDENCE" "$VIEWER_AUDIT_WORKFLOW"
require_grep "produce-view-only-viewer-audit-evidence.py" "$VIEWER_AUDIT_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-audit-evidence-${{ github.run_id }}' "$VIEWER_AUDIT_WORKFLOW"

require_grep "actions: read" "$VIEWER_NEGATIVE_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_NEGATIVE_EVIDENCE" "$VIEWER_NEGATIVE_WORKFLOW"
require_grep "produce-view-only-viewer-matrix-evidence.py" "$VIEWER_NEGATIVE_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-negative-evidence-${{ github.run_id }}' "$VIEWER_NEGATIVE_WORKFLOW"
require_grep "environment:" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "name: faz22-view-only-pilot" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "browser_run_id" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "faz22-6-view-only-viewer-browser-evidence.yml" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "MATRIX_ROOT_BINDING_FILE" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "collect-view-only-viewer-negative-matrix.sh" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6" \
  "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" \
  "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-matrix-collector-negative-${{ github.run_id }}' \
  "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
require_grep "raw_screen_persisted=false" "$VIEWER_NEGATIVE_COLLECTOR"
require_grep "Remove transient protected runner material" "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"
if grep -Eq '^[[:space:]]+[A-Za-z-]+:[[:space:]]+write([[:space:]]|$)' \
  "$VIEWER_MATRIX_COLLECTOR_WORKFLOW"; then
  echo "matrix collector workflow must not have GitHub write permissions" >&2
  exit 1
fi

require_grep "actions: read" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "environment:" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "name: faz22-view-only-pilot" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "collect-view-only-viewer-termination-case.sh" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6" \
  "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" \
  "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-termination-collector-${{ inputs.case_name }}-${{ github.run_id }}' \
  "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "timeout-minutes: 30" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep 'case_name:' "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "retention-days: 2" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
require_grep "raw_screen_persisted=false" "$VIEWER_TERMINATION_COLLECTOR"
require_grep "Remove transient protected runner material" "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"
if grep -Eq '^[[:space:]]+[A-Za-z-]+:[[:space:]]+write([[:space:]]|$)' \
  "$VIEWER_TERMINATION_COLLECTOR_WORKFLOW"; then
  echo "termination collector workflow must not have GitHub write permissions" >&2
  exit 1
fi

require_grep "actions: read" "$VIEWER_TERMINATION_WORKFLOW"
require_grep "PRODUCE_FAZ22_6_VIEW_ONLY_VIEWER_TERMINATION_EVIDENCE" \
  "$VIEWER_TERMINATION_WORKFLOW"
require_grep "local_abort_run_id" "$VIEWER_TERMINATION_WORKFLOW"
require_grep "indicator_loss_run_id" "$VIEWER_TERMINATION_WORKFLOW"
require_grep '--termination-case-run' "$VIEWER_TERMINATION_WORKFLOW"
require_grep "produce-view-only-viewer-matrix-evidence.py" "$VIEWER_TERMINATION_WORKFLOW"
require_grep 'faz22-6-view-only-viewer-termination-evidence-${{ github.run_id }}' \
  "$VIEWER_TERMINATION_WORKFLOW"

require_grep "environment:" "$VIEWER_APPLY_WORKFLOW"
require_grep "name: faz22-view-only-pilot" "$VIEWER_APPLY_WORKFLOW"
require_grep "build-view-only-pilot-owner-authorization.py" "$VIEWER_APPLY_WORKFLOW"
require_grep "verify-view-only-pilot-authorization-receipt.py" "$VIEWER_APPLY_WORKFLOW"
require_grep "--triggering-actor" "$VIEWER_APPLY_WORKFLOW"
require_grep "VIEW_ONLY_PILOT_OPERATOR_SHA256" "$VIEWER_APPLY_WORKFLOW"
require_grep "VIEW_ONLY_PILOT_DEVICE_SHA256" "$VIEWER_APPLY_WORKFLOW"
require_grep "authorization_ttl_minutes=120" "$VIEWER_APPLY_WORKFLOW"
require_grep 'authorization_expires_epoch="$((issued_epoch + authorization_ttl_minutes * 60))"' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep 'date -u -d "@$authorization_expires_epoch" +%Y-%m-%dT%H:%M:%SZ' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep '--expires-at "$authorization_expires_at"' "$VIEWER_APPLY_WORKFLOW"
if grep -Fq 'VIEW_ONLY_PILOT_AUTHORIZATION_EXPIRES_AT' "$VIEWER_APPLY_WORKFLOW"; then
  echo "viewer apply workflow must not consume a pre-approval absolute expiry secret" >&2
  exit 1
fi
require_grep 'sha256sum -c SHA256SUMS' "$VIEWER_APPLY_WORKFLOW"
require_grep 'rm -f "$out/owner-comment.json" "$out/advisory-comment.json"' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep 'legalClearanceClaimed' "$VIEWER_AUTH_BUILDER"
require_grep 'providerCryptographicAttestation' "$VIEWER_AUTH_BUILDER"
require_grep 'canonical_receipt_bytes' "$VIEWER_AUTH_COMMON"
require_grep 'canonical_receipt_bytes' "$VIEWER_AUTH_BUILDER"
require_grep 'action=rollback' "$VIEWER_OWNER_POLICY"
require_grep '"revokedAuthorizationSha256": []' "$VIEWER_REVOCATIONS"
require_grep "pilot_ttl_minutes must be between 5 and 120" "$VIEWER_APPLY_WORKFLOW"
require_grep 'now_epoch="$(date -u +%s)"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'requested_expires_epoch="$(( now_epoch + PILOT_TTL_MINUTES * 60 ))"' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep 'expires_epoch="$requested_expires_epoch"' "$VIEWER_APPLY_WORKFLOW"
require_grep '[ "$AUTHORIZATION_EXPIRES_EPOCH" -gt "$now_epoch" ]' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep 'if [ "$expires_epoch" -gt "$AUTHORIZATION_EXPIRES_EPOCH" ]; then' \
  "$VIEWER_APPLY_WORKFLOW"
require_grep 'expires_epoch="$AUTHORIZATION_EXPIRES_EPOCH"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'active_deadline="$(( expires_epoch - now_epoch + 600 ))"' \
  "$VIEWER_APPLY_WORKFLOW"
if grep -Fq 'expires_epoch="$(( $(date -u +%s) + PILOT_TTL_MINUTES * 60 ))"' \
  "$VIEWER_APPLY_WORKFLOW"; then
  echo "viewer watchdog must not start a new full TTL beyond authorization issuance" >&2
  exit 1
fi
require_grep "BRIDGE_DEPLOYMENT: endpoint-admin-remote-bridge-device-key" "$VIEWER_APPLY_WORKFLOW"
require_grep "BRIDGE_CONFIGMAP: endpoint-admin-remote-bridge-config-device-key" "$VIEWER_APPLY_WORKFLOW"
require_grep "endpoint-admin-remote-bridge-device-key-live" "$VIEWER_APPLY_WORKFLOW"
require_grep 'jq -s '\''{apiVersion:"v1", kind:"List", items:[.[]' "$VIEWER_APPLY_WORKFLOW"
require_grep 'if (.kind == "List" and (.items | type) == "array")' "$VIEWER_APPLY_WORKFLOW"
verify_viewer_resource_normalizer
require_grep "endpoint-admin-remote-bridge-config-device-key" "$VIEWER_WATCHDOG"
require_grep "deployments/endpoint-admin-remote-bridge-device-key" "$VIEWER_WATCHDOG"
require_grep '"REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES":null' "$VIEWER_WATCHDOG"
require_grep '"REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS":null' "$VIEWER_WATCHDOG"
require_grep "view-only-viewer-pilot-watchdog.template.yaml" "$VIEWER_APPLY_WORKFLOW"
require_grep "Compensating rollback after failed apply" "$VIEWER_APPLY_WORKFLOW"
require_grep 'apply -k "${BROKER_ONLY_OVERLAY}"' "$VIEWER_APPLY_WORKFLOW"
require_grep "GATEWAY_CONFIGMAP: api-gateway-config" "$VIEWER_APPLY_WORKFLOW"
require_grep "GATEWAY_ROUTE_PREFIX: SPRING_CLOUD_GATEWAY_ROUTES_29_" "$VIEWER_APPLY_WORKFLOW"
require_grep "SPRING_CLOUD_GATEWAY_ROUTES_28_ID=budget-service-route" "$VIEWER_APPLY_WORKFLOW"
require_grep "viewer route 29 is not clean before apply" "$VIEWER_APPLY_WORKFLOW"
for suffix in ID URI ORDER PREDICATES_0 PREDICATES_1 FILTERS_0; do
  require_grep \
    "/data/SPRING_CLOUD_GATEWAY_ROUTES_29_${suffix}" \
    "$VIEWER_ARGO_APPLICATION"
done
if grep -Fq "/data/SPRING_CLOUD_GATEWAY_ROUTES_28_" "$VIEWER_ARGO_APPLICATION"; then
  echo "GitOps-owned Budget Control route 28 must not be ignored by ArgoCD" >&2
  exit 1
fi
require_grep 's/__GATEWAY_ROUTE_PREFIX__/${GATEWAY_ROUTE_PREFIX}/g' "$VIEWER_APPLY_WORKFLOW"
require_grep "rollback-view-only-viewer-pilot-config.sh" "$VIEWER_APPLY_WORKFLOW"
require_grep '"REMOTE_BRIDGE_VIEWER_ENABLED":null' "$VIEWER_ROLLBACK_CONFIG"
require_grep '"REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES":null' "$VIEWER_ROLLBACK_CONFIG"
require_grep '"REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS":null' "$VIEWER_ROLLBACK_CONFIG"
require_grep 'GATEWAY_ROUTE_INDEX="${GATEWAY_ROUTE_INDEX:-29}"' "$VIEWER_ROLLBACK_CONFIG"
require_grep 'GATEWAY_ROUTE_PREFIX="SPRING_CLOUD_GATEWAY_ROUTES_${GATEWAY_ROUTE_INDEX}_"' "$VIEWER_ROLLBACK_CONFIG"
require_grep '($prefix + "ID"): null' "$VIEWER_ROLLBACK_CONFIG"
require_grep 'has("REMOTE_BRIDGE_VIEWER_ENABLED") | not' "$VIEWER_ROLLBACK_CONFIG"
require_grep 'has("REMOTE_BRIDGE_BROKER_VIEW_ONLY_PERMIT_TTL_MILLIS") | not' "$VIEWER_ROLLBACK_CONFIG"
if grep -Eq '(^|[[:space:]])jq([[:space:]]|$).*del[[:space:]]*\(' \
  "$VIEWER_APPLY_WORKFLOW" "$VIEWER_ROLLBACK_CONFIG"; then
  echo "viewer rollback must use merge-patch null deletion, not apply ownership" >&2
  exit 1
fi
if grep -Eq 'ACK_KVKK_DPIA|ack_kvkk_dpia|ACK_ONE_PERSON_OPERATOR|ACK_CONSENTING_ATTENDED|ACK_OWNER_8096' "$VIEWER_APPLY_WORKFLOW"; then
  echo "typed legal/operator acknowledgement remains in viewer apply workflow" >&2
  exit 1
fi
if grep -Fq -- '--verify-marker-input' "$VIEWER_APPLY_WORKFLOW"; then
  echo "signed legal-clearance verifier must not gate the bounded TEST apply path" >&2
  exit 1
fi

require_grep "activeDeadlineSeconds: __ACTIVE_DEADLINE_SECONDS__" "$VIEWER_WATCHDOG"
require_grep "faz22.6.acik.com/authorization-sha256" "$VIEWER_WATCHDOG"
require_grep "curlimages/curl:8.10.1@sha256:d9b4541e214bcd85196d6e92e2753ac6d0ea699f0af5741f8c6cccbfcf00ef4b" "$VIEWER_WATCHDOG"
require_grep "memory: 48Mi" "$VIEWER_WATCHDOG"
if grep -Eq "memory: (24|32)Mi" "$VIEWER_WATCHDOG"; then
  echo "watchdog memory request must retain headroom above the platform-test 32Mi LimitRange minimum" >&2
  exit 1
fi
require_grep 'REMOTE_BRIDGE_VIEWER_ENABLED":"false"' "$VIEWER_WATCHDOG"
require_grep '__GATEWAY_ROUTE_PREFIX__ID":null' "$VIEWER_WATCHDOG"
require_grep 'VIEWER_APPLY_ATTEMPT_MARKER: ${{ runner.temp }}/faz22-view-only-pilot-overlay-attempted' "$VIEWER_APPLY_WORKFLOW"
require_grep 'rm -f "$VIEWER_APPLY_ATTEMPT_MARKER"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'touch "$VIEWER_APPLY_ATTEMPT_MARKER"' "$VIEWER_APPLY_WORKFLOW"
require_grep 'if [ ! -e "$VIEWER_APPLY_ATTEMPT_MARKER" ]; then' "$VIEWER_APPLY_WORKFLOW"
require_grep "failed watchdog resources removed" "$VIEWER_APPLY_WORKFLOW"

for path in "$B1_WORKFLOW" "$VIEW_ONLY_WORKFLOW" "$VIEWER_PRODUCT_WORKFLOW" \
  "$VIEWER_PRODUCT_VERIFY_WORKFLOW" "$VIEWER_NEGATIVE_WORKFLOW"; do
  forbidden="$(
    grep -nE 'gh issue (edit|comment)|kubectl |secrets\.|GH_TOKEN|issues: write|pull-requests: write|contents: write' "$path" || true
  )"
  if [ -n "$forbidden" ]; then
    echo "forbidden mutating or secret-bearing pattern in $path:" >&2
    printf '%s\n' "$forbidden" >&2
    exit 1
  fi
done

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/faz22-6-acceptance-workflows.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

approved_at="$(date -u +%F)"
expires_at="$(future_date_utc 7)"

"$B1_HELPER" \
  --mode hardware \
  --marker-out "$tmp_dir/b1-4-hardware-marker.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" >/dev/null
grep -Fq "F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1" "$tmp_dir/b1-4-hardware-marker.txt"

"$B1_HELPER" \
  --mode risk \
  --marker-out "$tmp_dir/b1-4-risk-marker.txt" \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" >/dev/null
grep -Fq "F22_6_B1_4_RISK_ACCEPTANCE: v1" "$tmp_dir/b1-4-risk-marker.txt"

F22_6_ALLOW_LOCAL_EVIDENCE_URL_FOR_TESTS=1 "$VIEW_ONLY_HELPER" \
  --manifest-out "$tmp_dir/view-only-manifest.json" \
  --marker-out "$tmp_dir/view-only-marker.txt" \
  --evidence-url "file://$tmp_dir/view-only-manifest.json" \
  --pilot-device "AgentPc2" \
  --session-id "view-only-session-static-guard" \
  --recording-mode disabled \
  --d10-fail-closed pass \
  --dlp-mask-policy pass \
  --local-abort pass \
  --active-indicator pass \
  --viewer-path-decision fanout-proven \
  --owner-approved-by "Owner Example" \
  --approved-at "$approved_at" \
  --expires-at "$expires_at" >/dev/null
jq -e '.schema_version == "faz22.6-view-only-evidence-v2" and .recording_mode == "disabled"' "$tmp_dir/view-only-manifest.json" >/dev/null
grep -Fq "F22_6_VIEW_ONLY_ENGINEERING: v2" "$tmp_dir/view-only-marker.txt"

python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_product_evidence_verifier
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_product_evidence_assembler
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_operator_evidence_producer
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_d30_evidence_producer
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_frame_flow_summary
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_broker_evidence_producer
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_audit_evidence_producer
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_audit_summary
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_matrix_evidence_producer
python3 -m unittest tests.faz22_remote_ops.test_faz22_6_viewer_negative_matrix_collector

if python3 "$VIEWER_PRODUCT_VERIFIER" --run-id 1 --input "$tmp_dir/fabricated.json" \
  >/dev/null 2>&1; then
  echo "viewer product verifier must reject legacy local --input evidence" >&2
  exit 1
fi

echo "faz22-6-acceptance-package-workflows-static-ok"
