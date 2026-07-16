#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-collector-diagnostic.sh"
SMOKE="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
ALLOWLIST="$ROOT/config/faz22-6-viewer-collector-diagnostic-allowlist.v1.json"
BROWSER_ALLOWLIST="$ROOT/config/faz22-6-viewer-browser-diagnostic-codes.v1.json"
BROWSER_SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/summary.json" <<'JSON'
{
  "status": "no-go",
  "reason": "open-session-device-not-connected-timeout",
  "consentWait": "missing",
  "http": {"open": "404", "operation": ""},
  "deviceId": "must-not-be-copied"
}
JSON
printf '%s\n' '{}' > "$TMP/operation.json"

bash "$SCRIPT" "$TMP/summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/out"
jq -e '
  .status == "no-go"
  and .schemaVersion == "faz22.6.viewOnlyViewerCollectorDiagnostic.v3"
  and .failureReasonCode == "open-session-device-not-connected-timeout"
  and .browserFailureCode == null
  and .openSessionHttp == "404"
  and .operationHttp == null
  and .operationKind == null
  and .transportPushed == false
  and (has("deviceId") | not)
' "$TMP/out/collector-diagnostic.json" >/dev/null
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$TMP/out" && sha256sum -c SHA256SUMS)
else
  (cd "$TMP/out" && shasum -a 256 -c SHA256SUMS)
fi

printf '%s\n' '{malformed' > "$TMP/malformed.json"
bash "$SCRIPT" "$TMP/malformed.json" "$TMP/missing.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/fallback"
jq -e '.status == "collector-did-not-write-summary"' \
  "$TMP/fallback/collector-diagnostic.json" >/dev/null

cat > "$TMP/identity-reason.json" <<'JSON'
{
  "status": "SRB-AIDENETIMPC",
  "reason": "423b6fc3-7497-4083-bd2f-5e2fe543bfe9",
  "http": {"open": 404, "operation": 700}
}
JSON
cat > "$TMP/deny.json" <<'JSON'
{
  "kind": "DENY",
  "transportPushed": false,
  "deny": {"reason": "policy:CRYPTO_IDENTITY", "policyGate": "CRYPTO_IDENTITY", "policyDetail": "no-active-enrolled-connected-peer"}
}
JSON
bash "$SCRIPT" "$TMP/identity-reason.json" "$TMP/deny.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/redacted"
jq -e '
  .status == "collector-no-go"
  and .failureReasonCode == "collector-no-go-unspecified"
  and .openSessionHttp == "404"
  and .operationHttp == null
  and .operationKind == "DENY"
  and .deny.reason == "policy:CRYPTO_IDENTITY"
  and .deny.policyGate == "CRYPTO_IDENTITY"
  and .deny.policyDetail == "no-active-enrolled-connected-peer"
' "$TMP/redacted/collector-diagnostic.json" >/dev/null
if grep -Eq 'SRB-AIDENETIMPC|423b6fc3-7497-4083-bd2f-5e2fe543bfe9' \
    "$TMP/redacted/collector-diagnostic.json"; then
  echo "identity-bearing diagnostic value was not redacted" >&2
  exit 1
fi

cat > "$TMP/identity-deny.json" <<'JSON'
{
  "kind": "DENY",
  "transportPushed": false,
  "deny": {
    "reason": "423b6fc3-7497-4083-bd2f-5e2fe543bfe9",
    "policyGate": "DEVICE_ID",
    "policyDetail": "423b6fc3-7497-4083-bd2f-5e2fe543bfe9"
  }
}
JSON
bash "$SCRIPT" "$TMP/summary.json" "$TMP/identity-deny.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/deny-redacted"
jq -e '.deny == {reason:"denied", policyGate:null, policyDetail:null}' \
  "$TMP/deny-redacted/collector-diagnostic.json" >/dev/null
if grep -Fq '423b6fc3-7497-4083-bd2f-5e2fe543bfe9' \
    "$TMP/deny-redacted/collector-diagnostic.json"; then
  echo "identity-bearing deny value was not redacted" >&2
  exit 1
fi

cat > "$TMP/browser-summary.json" <<'JSON'
{
  "status": "no-go",
  "reason": "browser-product-evidence-failed",
  "consentWait": "granted",
  "http": {"open": "200", "operation": "200"}
}
JSON
cat > "$TMP/browser-diagnostic.json" <<'JSON'
{
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v1",
  "sourceRevision": "70d8286163651805cd5ebd537d3836d02fb1692d",
  "failureCode": "browser-metadata-not-trusted"
}
JSON
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser" "$TMP/browser-diagnostic.json"
jq -e '
  .failureReasonCode == "browser-product-evidence-failed"
  and .browserFailureCode == "browser-metadata-not-trusted"
  and .consentWait == "granted"
' "$TMP/browser/collector-diagnostic.json" >/dev/null

jq '.failureCode = "sessionId=must-not-pass"' "$TMP/browser-diagnostic.json" \
  > "$TMP/browser-diagnostic-unknown.json"
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-unknown" \
  "$TMP/browser-diagnostic-unknown.json"
jq -e '.browserFailureCode == "browser-unclassified-failure"' \
  "$TMP/browser-unknown/collector-diagnostic.json" >/dev/null
if grep -Fq 'sessionId=must-not-pass' "$TMP/browser-unknown/collector-diagnostic.json"; then
  echo "unknown browser failure value was not redacted" >&2
  exit 1
fi

jq '.sourceRevision = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"' "$TMP/browser-diagnostic.json" \
  > "$TMP/browser-diagnostic-wrong-source.json"
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-wrong-source" \
  "$TMP/browser-diagnostic-wrong-source.json"
jq -e '.browserFailureCode == "browser-unclassified-failure"' \
  "$TMP/browser-wrong-source/collector-diagnostic.json" >/dev/null

bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-missing"
jq -e '.browserFailureCode == "browser-unclassified-failure"' \
  "$TMP/browser-missing/collector-diagnostic.json" >/dev/null

printf '%s\n' 'not-used-before-binding-validation' > "$TMP/operator-password.txt"
if VIEWER_URL='https://testai.acik.com/endpoint-admin/remote-access/sessions/test-session/view?streamId=test-stream' \
    BROWSER_OPERATOR_USERNAME='rb-operator-test' \
    BROWSER_OPERATOR_PASSWORD_FILE="$TMP/operator-password.txt" \
    EVIDENCE_OUTPUT="$TMP/browser-evidence.json" \
    BROWSER_DIAGNOSTIC_OUTPUT="$TMP/browser-script-diagnostic.json" \
    SOURCE_REVISION=70d8286163651805cd5ebd537d3836d02fb1692d \
    DLP_MASK_RECT_BPS=7500,7500,2500,2500 \
    EVIDENCE_BINDING_JSON='{}' \
    PILOT_SECONDS=300 \
    node "$BROWSER_SCRIPT" >"$TMP/browser-script.out" 2>"$TMP/browser-script.err"; then
  echo "invalid browser binding unexpectedly passed" >&2
  exit 1
fi
jq -e '
  .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v1"
  and .sourceRevision == "70d8286163651805cd5ebd537d3836d02fb1692d"
  and .failureCode == "browser-binding-invalid"
' "$TMP/browser-script-diagnostic.json" >/dev/null
grep -Fxq 'browser_evidence=fail code=browser-binding-invalid' "$TMP/browser-script.err"

node --input-type=module - "$BROWSER_SCRIPT" "$BROWSER_ALLOWLIST" <<'NODE'
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const browserScript = process.argv[2];
const allowlistPath = process.argv[3];
const { BROWSER_FAILURE_CODES } = await import(pathToFileURL(browserScript));
const allowlist = JSON.parse(readFileSync(allowlistPath, 'utf8'));
assert.deepEqual([...BROWSER_FAILURE_CODES].sort(), [...allowlist.failureCodes].sort());
NODE

if grep -Fq "localStorage.setItem('token'" "$BROWSER_SCRIPT"; then
  echo "browser evidence must not inject a bearer into localStorage" >&2
  exit 1
fi
if grep -Fq 'OPERATOR_TOKEN_FILE' "$BROWSER_SCRIPT"; then
  echo "browser evidence must use the product login journey, not the broker token file" >&2
  exit 1
fi

while IFS= read -r static_reason; do
  jq -e --arg reason "$static_reason" \
    '.collectorFailureReasonCodes | index($reason) != null' "$ALLOWLIST" >/dev/null || {
      echo "static collector reason missing from diagnostic allowlist: $static_reason" >&2
      exit 1
    }
done < <(
  grep -Eo 'fail_smoke "[^"]+"' "$SMOKE" \
    | sed -E 's/^fail_smoke "//; s/"$//' \
    | grep -E '^[A-Za-z][A-Za-z0-9-]*$' \
    | LC_ALL=C sort -u
)

if bash "$SCRIPT" "$TMP/summary.json" "$TMP/operation.json" invalid-sha "$TMP/invalid" \
    >"$TMP/revision.out" 2>"$TMP/revision.err"; then
  echo "invalid source revision unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'source-revision-invalid' "$TMP/revision.err"

echo ok
