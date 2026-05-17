#!/usr/bin/env bash
#
# setup-m365-broker.sh — ADR-0021 Microsoft 365 SSO broker apply.
#
# Codex architecture consensus: thread 019e365b.
# Runbook: docs/operations/RUNBOOKS/RB-m365-sso-broker.md
#
# Keycloak `serban`/`platform-test` realm'ine Microsoft Entra ID OIDC
# identity provider'ı (alias `microsoft`) idempotent desired-state apply
# eder: IdP + claim mapper'lar (tid/oid) + v1 link-only first-broker-login
# flow. v1 = link-only — federe giriş yalnız MEVCUT kullanıcıya bağlanır
# (auto-create yok; SPI yok). ADR-0021 D4.
#
# Usage:
#   # Test realm (default)
#   M365_CONFIG=scripts/keycloak/m365-broker-config.json \
#   M365_CLIENT_SECRET="$(vault kv get -field=client_secret kv/platform/keycloak-m365-broker)" \
#     bash scripts/keycloak/setup-m365-broker.sh
#
#   # Prod realm — explicit confirmation gate
#   CONFIRM_PROD_M365_BROKER=serban REALM=serban \
#   M365_CONFIG=scripts/keycloak/m365-broker-config.json \
#   M365_CLIENT_SECRET="$(vault kv get -field=client_secret kv/platform/keycloak-m365-broker)" \
#     bash scripts/keycloak/setup-m365-broker.sh
#
#   # Verify-only (no mutation)
#   VERIFY_ONLY=1 bash scripts/keycloak/setup-m365-broker.sh
#
# Exit codes:
#   0  PASS — desired state + verify OK
#   1  ERROR — input / login / config
#   3  VERIFY_FAILED — apply ran but read-back assertion failed
#
# HARD RULE: client secret stdout'a/log'a YAZILMAZ (yalnız kcadm argv +
# IdP config). Idempotent — re-run safe. Operator credentials'a dokunmaz.
#
set -euo pipefail

REALM="${REALM:-platform-test}"
M365_CONFIG="${M365_CONFIG:-scripts/keycloak/m365-broker-config.json}"
M365_CLIENT_SECRET="${M365_CLIENT_SECRET:-}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"

ALIAS="microsoft"
FBL_FLOW="first broker login m365 link-only"

# Entra multi-tenant /organizations/ endpoints (ADR-0021 — work/school accounts)
AUTH_URL="https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
TOKEN_URL="https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
JWKS_URL="https://login.microsoftonline.com/organizations/discovery/v2.0/keys"
USERINFO_URL="https://graph.microsoft.com/oidc/userinfo"

# ─── Pre-flight: realm → container ─────────────────────────────────────────
case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; ENV="test" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; ENV="prod"; REALM="serban"
    if [ "${CONFIRM_PROD_M365_BROKER:-}" != "serban" ]; then
      echo "ERROR: prod realm requires CONFIRM_PROD_M365_BROKER=serban env" >&2
      exit 1
    fi
    ;;
  *) echo "ERROR: unknown realm '$REALM' (expected: platform-test, serban)" >&2; exit 1 ;;
esac

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"
ADMIN_PASS_FILE="host-compose/keycloak/${ENV}/secrets/kc_admin_password.txt"

# ─── Pre-flight: config + secret ───────────────────────────────────────────
if [ ! -f "$M365_CONFIG" ]; then
  echo "ERROR: config not found: $M365_CONFIG" >&2
  echo "       m365-broker-config-form.html ile üret (RB-m365-sso-broker.md Adım 2)" >&2
  exit 1
fi

CLIENT_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["entra"]["client_id"])' "$M365_CONFIG" 2>/dev/null || echo "")
SCOPES=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["entra"].get("default_scopes","openid profile email"))' "$M365_CONFIG" 2>/dev/null || echo "openid profile email")
DISPLAY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["broker"].get("display_name","Microsoft 365"))' "$M365_CONFIG" 2>/dev/null || echo "Microsoft 365")
TENANTS=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(",".join(t["tid"] for t in d.get("allowed_tenants",[])))' "$M365_CONFIG" 2>/dev/null || echo "")

if [ -z "$CLIENT_ID" ]; then
  echo "ERROR: config'ten entra.client_id okunamadı: $M365_CONFIG" >&2
  exit 1
fi
if [ "$VERIFY_ONLY" != "1" ] && [ -z "$M365_CLIENT_SECRET" ]; then
  echo "ERROR: M365_CLIENT_SECRET env required for apply" >&2
  echo "       vault kv get -field=client_secret kv/platform/keycloak-m365-broker" >&2
  exit 1
fi

echo "=== M365 broker apply — realm=$REALM container=$KC_CONTAINER ==="
echo "  client_id:       $CLIENT_ID"
echo "  allowed tenants: ${TENANTS:-<none>}  (v1 link-only — audit; v2 SPI hard-gate)"

# ─── 1. Login (master realm) ───────────────────────────────────────────────
echo ""
echo "=== Step 1/5: Login ==="
read_admin_password() {
  if [ -f "$ADMIN_PASS_FILE" ]; then
    sudo cat "$ADMIN_PASS_FILE" | tr -d '\n'; return
  fi
  docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null | tr -d '\n'
}
ADMIN_PASS=$(read_admin_password)
[ -n "$ADMIN_PASS" ] || { echo "ERROR: KC admin password resolved empty" >&2; exit 1; }
$KC config credentials --server http://localhost:8080 --realm master \
  --user admin --password "$ADMIN_PASS" >/dev/null 2>&1 \
  || { echo "ERROR: master realm login failed" >&2; exit 1; }
unset ADMIN_PASS
echo "✓ Logged in (realm: $REALM)"

# ─── 2. Link-only first-broker-login flow ──────────────────────────────────
# ADR-0021 D4: built-in "first broker login" kopyalanır, "Create User If
# Unique" execution DISABLED → eşleşmeyen federe kullanıcı oluşturulmaz.
echo ""
echo "=== Step 2/5: Link-only first-broker-login flow ==="
FLOW_EXISTS=$($KC get authentication/flows -r "$REALM" 2>/dev/null \
  | python3 -c 'import json,sys; print("yes" if any(f.get("alias")==sys.argv[1] for f in json.load(sys.stdin)) else "no")' "$FBL_FLOW" 2>/dev/null || echo "no")

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ "$FLOW_EXISTS" = "no" ]; then
    $KC create "authentication/flows/first broker login/copy" -r "$REALM" \
      -s "newName=$FBL_FLOW" >/dev/null 2>&1 \
      || { echo "ERROR: first-broker-login flow copy failed" >&2; exit 1; }
    echo "✓ Flow copied: $FBL_FLOW"
  else
    echo "✓ Flow exists: $FBL_FLOW"
  fi
  # "Create User If Unique" execution → DISABLED (link-only)
  CUIU_ID=$($KC get "authentication/flows/$FBL_FLOW/executions" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")=="idp-create-user-if-unique"]; print(m[0]["id"] if m else "")' 2>/dev/null || echo "")
  if [ -n "$CUIU_ID" ]; then
    $KC update "authentication/flows/$FBL_FLOW/executions" -r "$REALM" \
      -b "{\"id\":\"$CUIU_ID\",\"requirement\":\"DISABLED\"}" >/dev/null 2>&1 \
      || { echo "ERROR: Create-User-If-Unique disable failed" >&2; exit 1; }
    echo "✓ 'Create User If Unique' → DISABLED (link-only)"
  else
    echo "WARN: 'idp-create-user-if-unique' execution bulunamadı — test apply'da doğrula" >&2
  fi
fi

# ─── 3. Identity provider (desired-state create/update) ────────────────────
echo ""
echo "=== Step 3/5: Microsoft Entra OIDC identity provider ==="
IDP_EXISTS=$($KC get "identity-provider/instances/$ALIAS" -r "$REALM" --fields alias 2>/dev/null \
  | python3 -c 'import json,sys
try: print("yes" if json.load(sys.stdin).get("alias") else "no")
except Exception: print("no")' 2>/dev/null || echo "no")

if [ "$VERIFY_ONLY" != "1" ]; then
  IDP_JSON_HOST="$(mktemp /tmp/_m365_idp.XXXXXX.json)"
  IDP_JSON_CTR="/tmp/m365-idp-$$.json"
  trap 'rm -f "$IDP_JSON_HOST"; docker exec "$KC_CONTAINER" rm -f "$IDP_JSON_CTR" >/dev/null 2>&1 || true' EXIT

  # Tüm değerler env üzerinden geçer (quoted heredoc — shell interpolation
  # yok). clientSecret IdP config'ine girer; stdout'a/log'a yazılmaz.
  # multi-tenant: issuer per-tenant değişir → sabit issuer set edilmez
  # (signature JWKS ile doğrulanır; tid allowlist v2 SPI hard-gate).
  export M365_ALIAS="$ALIAS" M365_DISPLAY="$DISPLAY" M365_CLIENT_ID="$CLIENT_ID" \
         M365_SCOPES="$SCOPES" M365_FBL_FLOW="$FBL_FLOW" \
         M365_AUTH_URL="$AUTH_URL" M365_TOKEN_URL="$TOKEN_URL" \
         M365_JWKS_URL="$JWKS_URL" M365_USERINFO_URL="$USERINFO_URL"
  python3 - "$IDP_JSON_HOST" <<'PYEOF'
import json, os, sys
idp = {
  "alias": os.environ["M365_ALIAS"],
  "displayName": os.environ["M365_DISPLAY"],
  "providerId": "oidc",
  "enabled": True,
  "trustEmail": False,
  "storeToken": False,
  "linkOnly": False,
  "firstBrokerLoginFlowAlias": os.environ["M365_FBL_FLOW"],
  "config": {
    "clientId": os.environ["M365_CLIENT_ID"],
    "clientSecret": os.environ.get("M365_CLIENT_SECRET", ""),
    "clientAuthMethod": "client_secret_post",
    "authorizationUrl": os.environ["M365_AUTH_URL"],
    "tokenUrl": os.environ["M365_TOKEN_URL"],
    "jwksUrl": os.environ["M365_JWKS_URL"],
    "userInfoUrl": os.environ["M365_USERINFO_URL"],
    "useJwksUrl": "true",
    "validateSignature": "true",
    "defaultScope": os.environ["M365_SCOPES"],
    "syncMode": "IMPORT",
    "pkceEnabled": "true",
    "pkceMethod": "S256",
  },
}
json.dump(idp, open(sys.argv[1], "w"))
PYEOF

  docker cp "$IDP_JSON_HOST" "$KC_CONTAINER:$IDP_JSON_CTR" >/dev/null 2>&1 \
    || { echo "ERROR: docker cp IdP JSON failed" >&2; exit 1; }

  if [ "$IDP_EXISTS" = "yes" ]; then
    $KC update "identity-provider/instances/$ALIAS" -r "$REALM" -f "$IDP_JSON_CTR" >/dev/null 2>&1 \
      || { echo "ERROR: IdP update failed" >&2; exit 1; }
    echo "✓ IdP '$ALIAS' updated (converged to desired state)"
  else
    $KC create "identity-provider/instances" -r "$REALM" -f "$IDP_JSON_CTR" >/dev/null 2>&1 \
      || { echo "ERROR: IdP create failed" >&2; exit 1; }
    echo "✓ IdP '$ALIAS' created"
  fi
fi

# ─── 4. Claim mappers (tid → entra_tid, oid → entra_oid) ───────────────────
echo ""
echo "=== Step 4/5: Claim mappers ==="
upsert_attr_mapper() {
  local name="$1" claim="$2" attr="$3"
  [ "$VERIFY_ONLY" = "1" ] && return 0
  local existing
  existing=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("name")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$name" 2>/dev/null || echo "")
  local mh mc
  mh="$(mktemp /tmp/_m365_map.XXXXXX.json)"
  mc="/tmp/m365-map-$$-${name}.json"
  python3 - "$mh" "$name" "$claim" "$attr" <<'PYEOF'
import json, sys
_, path, name, claim, attr = sys.argv
m = {
  "name": name,
  "identityProviderAlias": "microsoft",
  "identityProviderMapper": "oidc-user-attribute-idp-mapper",
  "config": {
    "syncMode": "INHERIT",
    "claim": claim,
    "user.attribute": attr
  }
}
json.dump(m, open(path, "w"))
PYEOF
  docker cp "$mh" "$KC_CONTAINER:$mc" >/dev/null 2>&1 \
    || { echo "ERROR: docker cp mapper $name failed" >&2; rm -f "$mh"; exit 1; }
  if [ -n "$existing" ]; then
    $KC update "identity-provider/instances/$ALIAS/mappers/$existing" -r "$REALM" -f "$mc" >/dev/null 2>&1 \
      || { echo "ERROR: mapper $name update failed" >&2; rm -f "$mh"; exit 1; }
    echo "  ✓ mapper '$name' converged ($claim → $attr)"
  else
    $KC create "identity-provider/instances/$ALIAS/mappers" -r "$REALM" -f "$mc" >/dev/null 2>&1 \
      || { echo "ERROR: mapper $name create failed" >&2; rm -f "$mh"; exit 1; }
    echo "  ✓ mapper '$name' created ($claim → $attr)"
  fi
  rm -f "$mh"
  docker exec "$KC_CONTAINER" rm -f "$mc" >/dev/null 2>&1 || true
}
upsert_attr_mapper "entra-tid" "tid" "entra_tid"
upsert_attr_mapper "entra-oid" "oid" "entra_oid"

# ─── 5. Verify (read-back assertions) ──────────────────────────────────────
echo ""
echo "=== Step 5/5: Verify ==="
IDP_VERIFY=$($KC get "identity-provider/instances/$ALIAS" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json, sys
try:
    idp = json.load(sys.stdin)
except Exception:
    print("FAIL: IdP not found"); sys.exit()
cfg = idp.get("config", {})
checks = {
    "providerId_oidc": idp.get("providerId") == "oidc",
    "enabled": idp.get("enabled") in (True, "true"),
    "link_only_flow": idp.get("firstBrokerLoginFlowAlias") == "first broker login m365 link-only",
    "client_id_set": bool(cfg.get("clientId")),
    "jwks_url_set": bool(cfg.get("jwksUrl")),
    "validate_signature": cfg.get("validateSignature") == "true",
}
for k, v in checks.items():
    print(f"  {k}={v}")
print("FAIL" if [k for k, v in checks.items() if not v] else "PASS")
' 2>/dev/null || echo "FAIL: verify error")
echo "$IDP_VERIFY"
echo "$IDP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: IdP verify FAILED" >&2; exit 3; }

MAP_COUNT=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); n={x.get("name") for x in d}; print(len(n & {"entra-tid","entra-oid"}))' 2>/dev/null || echo "0")
echo "  mappers (entra-tid,entra-oid): $MAP_COUNT/2"
[ "$MAP_COUNT" = "2" ] || { echo "ERROR: mapper verify FAILED" >&2; exit 3; }

echo ""
echo "=== M365 broker apply — PASS (realm=$REALM) ==="
echo "Next: browser smoke — RB-m365-sso-broker.md Adım 5 (test) / Adım 6 (prod)"
exit 0
