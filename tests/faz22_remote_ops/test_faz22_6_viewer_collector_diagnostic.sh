#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/build-view-only-viewer-collector-diagnostic.sh"
SMOKE="$ROOT/scripts/faz22-remote-ops/faz22-6-view-only-attended-smoke.sh"
ALLOWLIST="$ROOT/config/faz22-6-viewer-collector-diagnostic-allowlist.v1.json"
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
  and .failureReasonCode == "open-session-device-not-connected-timeout"
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
