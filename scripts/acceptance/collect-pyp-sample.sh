#!/usr/bin/env bash
# PYP actuals provider live sample collector (gitops#3496).
#
# Pages the deployed pyp-actuals provider through the public edge with the
# synthetic planner token (kv/platform/smoke-budget, host-side only) and
# writes the rows as JSONL + a dimension-source summary into EVIDENCE_DIR.
# Read-only; the sample is the acceptance evidence for resolution changes
# (e.g. the B.1 invoice-uniform rollout) and feeds the PYP breakdown report.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
FISCAL_YEAR="${FISCAL_YEAR:-2026}"
PAGES="${PAGES:-5}"
PAGE_LIMIT="${PAGE_LIMIT:-2000}"
EVIDENCE_DIR="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"

mkdir -p "$EVIDENCE_DIR"
[[ -r "$VAULT_INIT_JSON" ]] || { echo "FATAL: vault init file unreadable" >&2; exit 1; }

vault_field() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_JSON" |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field="$1" kv/platform/smoke-budget
    ' sh "$1"
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
chmod 700 "$TMP_DIR"
vault_field client_secret > "$TMP_DIR/cs"
vault_field persona_password > "$TMP_DIR/pw"

TOKEN_JSON="$TMP_DIR/token.json"
curl -sS --max-time 20 -o "$TOKEN_JSON" -X POST \
  "$BASE_URL/realms/platform-test/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=smoke-budget-v1 \
  --data-urlencode "client_secret@$TMP_DIR/cs" \
  -d username=budget-smoke-planner \
  --data-urlencode "password@$TMP_DIR/pw" \
  -d "scope=openid budget:read budget:write"
jq -er '.access_token | strings | length > 0' "$TOKEN_JSON" >/dev/null \
  || { echo "FATAL: planner token mint failed" >&2; exit 1; }
AUTH_CONFIG="$TMP_DIR/auth.curl"
jq -r '"header \"Authorization: Bearer \(.access_token)\""' "$TOKEN_JSON" > "$AUTH_CONFIG"
printf 'header "X-Company-Id: 1"\n' >> "$AUTH_CONFIG"
chmod 600 "$AUTH_CONFIG"

OUT="$EVIDENCE_DIR/pyp-sample.jsonl"
: > "$OUT"
CURSOR=""
for _ in $(seq 1 "$PAGES"); do
  URL="$BASE_URL/api/v1/reports/pyp-actuals/provider?fiscalYear=$FISCAL_YEAR&limit=$PAGE_LIMIT"
  [[ -n "$CURSOR" ]] && URL="$URL&cursor=$CURSOR"
  PAGE="$TMP_DIR/page.json"
  curl -sS --max-time 180 -o "$PAGE" --config "$AUTH_CONFIG" "$URL"
  jq -ec '.rows[]' "$PAGE" >> "$OUT"
  CURSOR="$(jq -r '.nextCursor // empty' "$PAGE")"
  [[ -n "$CURSOR" ]] || break
done

python3 - "$OUT" > "$EVIDENCE_DIR/pyp-summary.json" <<'PY'
import json, sys
from collections import Counter
rows = [json.loads(line) for line in open(sys.argv[1])]
invoices = [r for r in rows if r.get("documentType") == "INVOICE"]
print(json.dumps({
    "rows": len(rows),
    "dimensionSource": dict(Counter(r.get("dimensionSource") for r in rows)),
    "documentType": dict(Counter(r.get("documentType") for r in rows)),
    "invoiceRows": len(invoices),
    "invoiceLabeled": sum(1 for r in invoices if r.get("expenseItemId")),
    "invoiceWithOrder": sum(1 for r in invoices if r.get("orderId")),
    "invoiceWithProgress": sum(1 for r in invoices if r.get("progressId")),
    "actionDateRange": [min(r["actionDate"] for r in rows),
                        max(r["actionDate"] for r in rows)] if rows else None,
}, ensure_ascii=False, indent=2))
PY

echo "OK: $(wc -l < "$OUT") satır -> $OUT"
cat "$EVIDENCE_DIR/pyp-summary.json"
