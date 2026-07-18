#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-collector-diagnostic.sh"
SMOKE="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
ALLOWLIST="$ROOT/config/faz22-6-viewer-collector-diagnostic-allowlist.v1.json"
BROWSER_ALLOWLIST="$ROOT/config/faz22-6-viewer-browser-diagnostic-codes.v1.json"
BROWSER_SCRIPT="$ROOT/scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs"
WORKFLOW="$ROOT/.github/workflows/faz22-6-view-only-viewer-browser-evidence.yml"
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
  and .schemaVersion == "faz22.6.viewOnlyViewerCollectorDiagnostic.v5"
  and .failureReasonCode == "open-session-device-not-connected-timeout"
  and .browserFailureCode == null
  and .browserReplayHttpStatus == null
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
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v3",
  "sourceRevision": "70d8286163651805cd5ebd537d3836d02fb1692d",
  "failureCode": "browser-ack-count-diverged",
  "ackTelemetry": {
    "attempted": 705,
    "accepted": 704,
    "rejected": 0,
    "pending": 0,
    "acceptedSamples": 704,
    "lastAcceptedSeq": 731
  },
  "replayHttpStatus": null
}
JSON
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser" "$TMP/browser-diagnostic.json"
jq -e '
  .failureReasonCode == "browser-product-evidence-failed"
  and .browserFailureCode == "browser-ack-count-diverged"
  and .browserReplayHttpStatus == null
  and .browserAckTelemetry == {
    attempted:705,
    accepted:704,
    rejected:0,
    pending:0,
    acceptedSamples:704,
    lastAcceptedSeq:731
  }
  and .consentWait == "granted"
' "$TMP/browser/collector-diagnostic.json" >/dev/null

cat > "$TMP/browser-diagnostic-all-rejected.json" <<'JSON'
{
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v3",
  "sourceRevision": "70d8286163651805cd5ebd537d3836d02fb1692d",
  "failureCode": "browser-ack-rejected",
  "ackTelemetry": {
    "attempted": 1,
    "accepted": 0,
    "rejected": 1,
    "pending": 0,
    "acceptedSamples": 0,
    "lastAcceptedSeq": null
  },
  "replayHttpStatus": null
}
JSON
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-all-rejected" \
  "$TMP/browser-diagnostic-all-rejected.json"
jq -e '
  .browserFailureCode == "browser-ack-rejected"
  and .browserAckTelemetry == {
    attempted:1,
    accepted:0,
    rejected:1,
    pending:0,
    acceptedSamples:0,
    lastAcceptedSeq:null
  }
' "$TMP/browser-all-rejected/collector-diagnostic.json" >/dev/null

cat > "$TMP/browser-diagnostic-replay.json" <<'JSON'
{
  "schemaVersion": "faz22.6.viewOnlyViewerBrowserDiagnostic.v3",
  "sourceRevision": "70d8286163651805cd5ebd537d3836d02fb1692d",
  "failureCode": "browser-replay-not-rejected",
  "ackTelemetry": null,
  "replayHttpStatus": 405
}
JSON
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-replay" \
  "$TMP/browser-diagnostic-replay.json"
jq -e '
  .browserFailureCode == "browser-replay-not-rejected"
  and .browserAckTelemetry == null
  and .browserReplayHttpStatus == "405"
' "$TMP/browser-replay/collector-diagnostic.json" >/dev/null

jq '.failureCode = "browser-ack-count-diverged"' "$TMP/browser-diagnostic-replay.json" \
  > "$TMP/browser-diagnostic-mismatched-fields.json"
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-mismatched-fields" \
  "$TMP/browser-diagnostic-mismatched-fields.json"
jq -e '
  .browserFailureCode == "browser-unclassified-failure"
  and .browserAckTelemetry == null
  and .browserReplayHttpStatus == null
' "$TMP/browser-mismatched-fields/collector-diagnostic.json" >/dev/null

jq '.replayHttpStatus = 99' "$TMP/browser-diagnostic-replay.json" \
  > "$TMP/browser-diagnostic-replay-invalid-status.json"
bash "$SCRIPT" "$TMP/browser-summary.json" "$TMP/operation.json" \
  70d8286163651805cd5ebd537d3836d02fb1692d "$TMP/browser-replay-invalid-status" \
  "$TMP/browser-diagnostic-replay-invalid-status.json"
jq -e '
  .browserFailureCode == "browser-unclassified-failure"
  and .browserAckTelemetry == null
  and .browserReplayHttpStatus == null
' "$TMP/browser-replay-invalid-status/collector-diagnostic.json" >/dev/null

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
  .schemaVersion == "faz22.6.viewOnlyViewerBrowserDiagnostic.v3"
  and .sourceRevision == "70d8286163651805cd5ebd537d3836d02fb1692d"
  and .failureCode == "browser-binding-invalid"
  and .ackTelemetry == null
  and .replayHttpStatus == null
' "$TMP/browser-script-diagnostic.json" >/dev/null
grep -Fxq 'browser_evidence=fail code=browser-binding-invalid' "$TMP/browser-script.err"

node --input-type=module - "$BROWSER_SCRIPT" "$BROWSER_ALLOWLIST" <<'NODE'
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const browserScript = process.argv[2];
const allowlistPath = process.argv[3];
const {
  BROWSER_FAILURE_CODES,
  ackDiagnostic,
  classifyAckDrainSnapshot,
  classifyViewerDrainSnapshot,
  classifyPreflightApiStatus,
  deriveViewerAckUrl,
  drainAckSnapshots,
  installViewerEvidenceObserver,
} = await import(pathToFileURL(browserScript));
const allowlist = JSON.parse(readFileSync(allowlistPath, 'utf8'));
assert.deepEqual([...BROWSER_FAILURE_CODES].sort(), [...allowlist.failureCodes].sort());
assert.equal(classifyPreflightApiStatus(null), 'browser-preflight-api-response-missing');
assert.equal(classifyPreflightApiStatus(200), 'browser-preflight-api-status-unexpected-success');
assert.equal(classifyPreflightApiStatus(401), 'browser-preflight-api-status-unauthorized');
assert.equal(classifyPreflightApiStatus(403), 'browser-preflight-api-status-forbidden');
assert.equal(classifyPreflightApiStatus(404), 'browser-preflight-api-status-invalid');
assert.equal(classifyPreflightApiStatus(409), 'browser-preflight-api-status-conflict');
assert.equal(classifyPreflightApiStatus(502), 'browser-preflight-api-status-server-error');
assert.equal(
  deriveViewerAckUrl('https://testai.acik.com/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1'),
  'https://testai.acik.com/api/v1/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1',
);
assert.throws(
  () => deriveViewerAckUrl('https://testai.acik.com/api/v1/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.throws(
  () => deriveViewerAckUrl('https://testai.acik.com/endpoint-admin/remote-access/sessions/session-1/view'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.throws(
  () => deriveViewerAckUrl('http://testai.acik.com/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.throws(
  () => deriveViewerAckUrl('https://evil.example/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.throws(
  () => deriveViewerAckUrl('https://testai.acik.com/endpoint-admin/remote-access/sessions/session-1/other?streamId=stream_1'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.throws(
  () => deriveViewerAckUrl('https://testai.acik.com/endpoint-admin/remote-access/sessions/session-1/view?streamId=stream_1&extra=1'),
  /outside the bounded test VIEW_ONLY product route/,
);
assert.equal(classifyAckDrainSnapshot({ attempted: 100, accepted: 100, rejected: 0, pending: 0, lastAcceptedSeq: 120 }), 'settled');
assert.equal(classifyAckDrainSnapshot({ attempted: 101, accepted: 100, rejected: 0, pending: 1, lastAcceptedSeq: 120 }), 'pending');
assert.equal(classifyAckDrainSnapshot({ attempted: 101, accepted: 100, rejected: 0, pending: 0, lastAcceptedSeq: 120 }), 'diverged');
assert.equal(classifyAckDrainSnapshot({ attempted: 101, accepted: 100, rejected: 1, pending: 0, lastAcceptedSeq: 120 }), 'rejected');
assert.equal(classifyAckDrainSnapshot({ attempted: 1, accepted: 0, rejected: 1, pending: 0, lastAcceptedSeq: null }), 'rejected');
assert.equal(classifyAckDrainSnapshot({ attempted: 0, accepted: 0, rejected: 0, pending: 0, lastAcceptedSeq: null }), 'settled');
assert.equal(classifyAckDrainSnapshot({ attempted: 1, accepted: 0, rejected: 0, pending: 0, lastAcceptedSeq: 0 }), 'invalid');
assert.equal(classifyAckDrainSnapshot({ attempted: 1, accepted: 1, rejected: 0, pending: 0, lastAcceptedSeq: null }), 'invalid');
assert.equal(classifyAckDrainSnapshot({ attempted: 101, accepted: 100, rejected: 0, pending: 1001, lastAcceptedSeq: 120 }), 'invalid');

const settled = {
  attempted: 100,
  accepted: 100,
  rejected: 0,
  pending: 0,
  lastAcceptedSeq: 120,
  viewStatus: 'live',
  closureKind: 'none',
  draining: true,
  drainNonce: 'test-cutoff-nonce-0001',
};
assert.equal(classifyViewerDrainSnapshot(settled), 'settled');
assert.equal(classifyViewerDrainSnapshot({ ...settled, viewStatus: 'closed', closureKind: 'stream-ended-after-drain' }), 'settled');
assert.equal(classifyViewerDrainSnapshot({ ...settled, viewStatus: 'closed', closureKind: 'stream-ended-before-drain' }), 'left-live');
assert.equal(classifyViewerDrainSnapshot({ ...settled, viewStatus: 'closed', closureKind: 'local-stop' }), 'left-live');
assert.equal(classifyViewerDrainSnapshot({ ...settled, draining: false }), 'left-live');
assert.equal(classifyViewerDrainSnapshot(settled, 'different-cutoff-nonce'), 'cutoff-invalid');
assert.equal(classifyViewerDrainSnapshot({ ...settled, pending: 1, attempted: 101 }), 'pending');
assert.equal(classifyViewerDrainSnapshot({ ...settled, rejected: 1, attempted: 101 }), 'rejected');
assert.equal(classifyViewerDrainSnapshot({ ...settled, attempted: 101 }), 'diverged');

let clock = 0;
const pendingSnapshot = { ...settled, attempted: 101, pending: 1 };
const snapshots = [pendingSnapshot, settled];
const drained = await drainAckSnapshots({
  readSnapshot: async () => snapshots.shift(),
  now: () => clock,
  sleep: async (milliseconds) => { clock += milliseconds; },
  timeoutMillis: 500,
  pollMillis: 100,
  expectedNonce: 'test-cutoff-nonce-0001',
});
assert.equal(drained.state, 'settled');
assert.equal(clock, 100);

clock = 0;
const timedOut = await drainAckSnapshots({
  readSnapshot: async () => pendingSnapshot,
  now: () => clock,
  sleep: async (milliseconds) => { clock += milliseconds; },
  timeoutMillis: 250,
  pollMillis: 100,
});
assert.equal(timedOut.state, 'timeout');
assert.equal(clock, 250);
assert.deepEqual(timedOut.snapshot, pendingSnapshot);

const localStop = await drainAckSnapshots({
  readSnapshot: async () => ({ ...settled, viewStatus: 'closed', closureKind: 'local-stop' }),
  now: () => 0,
  sleep: async () => {},
  timeoutMillis: 100,
});
assert.equal(localStop.state, 'left-live');

assert.deepEqual(
  ackDiagnostic(
    { attempted: 1, accepted: 0, rejected: 1, pending: 0, lastAcceptedSeq: null },
    0,
  ),
  { attempted: 1, accepted: 0, rejected: 1, pending: 0, acceptedSamples: 0, lastAcceptedSeq: null },
);
assert.equal(
  ackDiagnostic(
    { attempted: 0, accepted: 1, rejected: 0, pending: 0, lastAcceptedSeq: 1 },
    1,
  ),
  null,
);
assert.equal(
  ackDiagnostic(
    { attempted: 1, accepted: 1, rejected: 0, pending: 0, lastAcceptedSeq: 1 },
    2,
  ),
  null,
);

function fakeTarget() {
  const attrs = new Map([['data-render-ack-accepted-count', '0']]);
  return {
    isConnected: true,
    getAttribute: (name) => attrs.has(name) ? attrs.get(name) : null,
    setAttribute: (name, value) => attrs.set(name, String(value)),
  };
}

function setupFakeObserver() {
  const callbacks = [];
  let currentTarget = fakeTarget();
  globalThis.window = {};
  globalThis.document = {
    documentElement: {},
    querySelector: () => currentTarget,
  };
  globalThis.MutationObserver = class {
    constructor(callback) { this.callback = callback; callbacks.push(callback); }
    observe() {}
    disconnect() {}
  };
  installViewerEvidenceObserver();
  return {
    callbacks,
    target: currentTarget,
    replaceTarget: () => {
      currentTarget.isConnected = false;
      currentTarget = fakeTarget();
      return currentTarget;
    },
    notify: () => callbacks.forEach((callback) => callback()),
  };
}

let fake = setupFakeObserver();
fake.target.setAttribute('data-render-ack-last-accepted-seq', '7');
fake.target.setAttribute('data-render-ack-last-accepted-observed-at', '100');
fake.target.setAttribute('data-render-ack-last-accepted-sent-at', '101');
fake.target.setAttribute('data-render-ack-accepted-count', '1');
fake.notify();
assert.equal(window.__faz226ViewerEvidence.isValid(), true);
assert.deepEqual(
  window.__faz226ViewerEvidence.samples.map(({ seq, observedAt, sentAt }) => ({ seq, observedAt, sentAt })),
  [{ seq: 7, observedAt: 100, sentAt: 101 }],
);
fake.replaceTarget();
assert.equal(window.__faz226ViewerEvidence.isValid(), false);

fake = setupFakeObserver();
fake.target.setAttribute('data-render-ack-last-accepted-seq', '8');
fake.target.setAttribute('data-render-ack-last-accepted-observed-at', '110');
fake.target.setAttribute('data-render-ack-last-accepted-sent-at', '111');
fake.target.setAttribute('data-render-ack-accepted-count', '1');
fake.notify();
fake.target.setAttribute('data-render-ack-accepted-count', '0');
fake.notify();
assert.equal(window.__faz226ViewerEvidence.isValid(), false);

fake = setupFakeObserver();
fake.target.setAttribute('data-render-ack-last-accepted-seq', '9');
fake.target.setAttribute('data-render-ack-last-accepted-observed-at', '120');
fake.target.setAttribute('data-render-ack-last-accepted-sent-at', '121');
fake.target.setAttribute('data-render-ack-accepted-count', '2');
fake.notify();
assert.equal(window.__faz226ViewerEvidence.isValid(), false);
NODE

if grep -Fq "localStorage.setItem('token'" "$BROWSER_SCRIPT"; then
  echo "browser evidence must not inject a bearer into localStorage" >&2
  exit 1
fi
if grep -Fq 'OPERATOR_TOKEN_FILE' "$BROWSER_SCRIPT"; then
  echo "browser evidence must use the product login journey, not the broker token file" >&2
  exit 1
fi

grep -Fq 'browser-auth-route-preflight-script-required' "$SMOKE" || {
  echo "auth route preflight must fail closed when the browser harness is absent" >&2
  exit 1
}
grep -Fq 'needs: [target-preflight, product-auth-preflight]' "$WORKFLOW" || {
  echo "attended browser evidence must remain blocked by both preflights" >&2
  exit 1
}
grep -Fq 'if: ${{ !inputs.preflight_only }}' "$WORKFLOW" || {
  echo "preflight-only dispatch must not request protected attended approval" >&2
  exit 1
}
product_preflight_block="$(sed -n '/^  product-auth-preflight:/,/^  browser-evidence:/p' "$WORKFLOW")"
grep -Fq "if: \${{ github.ref == 'refs/heads/main' }}" <<< "$product_preflight_block" || {
  echo "credential-bearing product preflight must be pinned to the protected main branch" >&2
  exit 1
}
grep -Fq 'KC_TEST_ADMIN_PASSWORD: ${{ secrets.KC_TEST_ADMIN_PASSWORD }}' \
    <<< "$product_preflight_block" || {
  echo "main-only product preflight must use the managed test Keycloak secret" >&2
  exit 1
}
grep -Fq 'session-side-effect-attestation.json' <<< "$product_preflight_block" || {
  echo "product preflight must publish its scoped session side-effect attestation" >&2
  exit 1
}
grep -Fq '/home/halil/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt' "$SMOKE" || {
  echo "viewer preflight must retain the canonical runner-local Keycloak credential source" >&2
  exit 1
}
grep -Fq 'keycloak_admin_password_is_valid' "$SMOKE" || {
  echo "viewer preflight must validate local Keycloak candidates before selecting one" >&2
  exit 1
}
grep -Fq 'excludes:["test Keycloak persona lifecycle"]' "$SMOKE" || {
  echo "session side-effect attestation must not overclaim Keycloak immutability" >&2
  exit 1
}

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
