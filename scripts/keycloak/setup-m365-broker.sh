#!/usr/bin/env bash
#
# setup-m365-broker.sh — ADR-0021 Microsoft 365 SSO broker apply (v2 auto-provision).
#
# Codex architecture consensus: thread 019e365b (v1 link-only), 019e3b72 (v2).
# Runbook: docs/operations/RUNBOOKS/RB-m365-sso-broker.md
#
# Keycloak `serban`/`platform-test` realm'ine Microsoft Entra ID OIDC identity
# provider'ı (alias `microsoft`) idempotent desired-state apply eder:
#   - single-tenant Entra OIDC IdP (tenant hard-gate)
#   - claim mapper'lar (tid → entra_tid, oid → entra_oid)
#   - hardcoded default-role mapper (yeni kullanıcı → `viewer` salt-okunur)
#   - v2 auto-provision first-broker-login flow
#
# v2 = AUTO-PROVISION (ADR-0021 D4 v2): izinli Entra tenant'ından M365 ile giren
# çalışana eşleşen platform hesabı YOKSA otomatik açılır; eşleşen hesap VARSA
# link akışı (re-authentication) çalışır. Tenant hard-gate: IdP endpoint'leri
# tek-tenant (`/{tid}/`) — başka tenant Microsoft tarafında durur, Keycloak'a
# hiç ulaşmaz. Yeni kullanıcı varsayılan `viewer` (salt-okunur) realm rolü alır;
# yetki yükseltme admin kararıdır.
#
# NOT (kapsam): bu script Keycloak katmanını kurar — kullanıcının platforma
# GİRMESİNİ sağlar. Uygulama veri-görünürlüğü (OpenFGA explicit-scope) ayrı bir
# katmandır; auto-provision edilen kullanıcının veri görüp görmediği browser
# smoke'ta (`/api/v1/authz/me` + salt-okunur route) doğrulanır.
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
#   # Eski v1 link-only flow'u da sil (opsiyonel). PROD'da rollback için
#   # varsayılan KORUNUR (Codex 019e3b72); yalnız stabilizasyon sonrası ayrı
#   # run ile, IdP yeni flow'a bağlandığı doğrulandıktan sonra silinir.
#   CLEANUP_OLD_M365_LINK_ONLY_FLOW=1 bash scripts/keycloak/setup-m365-broker.sh
#
# Exit codes:
#   0  PASS — desired state + verify OK
#   1  ERROR — input / login / config
#   3  VERIFY_FAILED — apply ran but read-back assertion failed
#
# HARD RULE: client secret stdout'a/log'a YAZILMAZ (yalnız kcadm argv + IdP
# config). Idempotent — re-run safe. Operator credentials'a dokunmaz.
#
set -euo pipefail

REALM="${REALM:-platform-test}"
M365_CONFIG="${M365_CONFIG:-scripts/keycloak/m365-broker-config.json}"
M365_CLIENT_SECRET="${M365_CLIENT_SECRET:-}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"
CLEANUP_OLD="${CLEANUP_OLD_M365_LINK_ONLY_FLOW:-0}"

ALIAS="microsoft"
# v2 auto-provision flow (v1 link-only flow'undan ayrı isim — rollback için
# eski flow korunabilsin; Codex 019e3b72).
FBL_FLOW="first broker login m365 auto-provision"
OLD_FBL_FLOW="first broker login m365 link-only"
# kcadm path segments must URL-encode spaces (KC 26 kcadm rejects raw spaces).
FBL_FLOW_ENC="${FBL_FLOW// /%20}"
# Yeni kullanıcıya verilecek varsayılan realm rolü (salt-okunur, least-privilege).
DEFAULT_ROLE="viewer"
ROLE_MAPPER_NAME="default-role-${DEFAULT_ROLE}"

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

# ─── Pre-flight: config + secret + tenant hard-gate ────────────────────────
if [ ! -f "$M365_CONFIG" ]; then
  echo "ERROR: config not found: $M365_CONFIG" >&2
  echo "       m365-broker-config-form.html ile üret (RB-m365-sso-broker.md Adım 2)" >&2
  exit 1
fi

CLIENT_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["entra"]["client_id"])' "$M365_CONFIG" 2>/dev/null || echo "")
SCOPES=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["entra"].get("default_scopes","openid profile email"))' "$M365_CONFIG" 2>/dev/null || echo "openid profile email")
DISPLAY=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["broker"].get("display_name","Microsoft 365"))' "$M365_CONFIG" 2>/dev/null || echo "Microsoft 365")

# v2 tenant hard-gate: tam olarak 1 izinli tenant beklenir (Codex 019e3b72).
# Tek-tenant endpoint'le auto-create güvenli açılır — başka tenant Microsoft
# tarafında durur. Birden çok tenant gerekirse ayrı IdP alias tasarımı gerek.
TENANT_COUNT=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("allowed_tenants",[])))' "$M365_CONFIG" 2>/dev/null || echo "0")
if [ "$TENANT_COUNT" != "1" ]; then
  echo "ERROR: v2 auto-provision tam olarak 1 allowed_tenants kaydı gerektirir (got: $TENANT_COUNT)" >&2
  echo "       Çok-tenant senaryosu için tenant başına ayrı IdP alias tasarımı gerekir." >&2
  exit 1
fi
TENANT_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["allowed_tenants"][0]["tid"])' "$M365_CONFIG" 2>/dev/null || echo "")
if ! echo "$TENANT_ID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'; then
  echo "ERROR: allowed_tenants[0].tid GUID formatında değil: '$TENANT_ID'" >&2
  exit 1
fi

# Single-tenant Entra OIDC endpoints (v2 hard-gate — Codex 019e3b72).
AUTH_URL="https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/authorize"
TOKEN_URL="https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token"
JWKS_URL="https://login.microsoftonline.com/${TENANT_ID}/discovery/v2.0/keys"
ISSUER="https://login.microsoftonline.com/${TENANT_ID}/v2.0"
USERINFO_URL="https://graph.microsoft.com/oidc/userinfo"

if [ -z "$CLIENT_ID" ]; then
  echo "ERROR: config'ten entra.client_id okunamadı: $M365_CONFIG" >&2
  exit 1
fi
if [ "$VERIFY_ONLY" != "1" ] && [ -z "$M365_CLIENT_SECRET" ]; then
  echo "ERROR: M365_CLIENT_SECRET env required for apply" >&2
  echo "       vault kv get -field=client_secret kv/platform/keycloak-m365-broker" >&2
  exit 1
fi

echo "=== M365 broker apply (v2 auto-provision) — realm=$REALM container=$KC_CONTAINER ==="
echo "  client_id:      $CLIENT_ID"
echo "  allowed tenant: $TENANT_ID  (single-tenant hard-gate — /{tid}/ endpoints)"
echo "  default role:   $DEFAULT_ROLE  (yeni kullanıcı — least-privilege)"

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

# ─── 2. Auto-provision first-broker-login flow ─────────────────────────────
# ADR-0021 D4 v2 (Codex 019e3b72):
#   v2 flow = built-in "first broker login" kopyası, STOCK haliyle bırakılır:
#     - Create User If Unique  ALTERNATIVE → eşleşmeyen federe kullanıcı OTOMATİK
#         oluşturulur; eşleşen varsa EXISTING_USER_INFO set edilir, "Handle
#         Existing Account"a devreder (built-in detection — ayrı detect YOK).
#     - Handle Existing Account ALTERNATIVE → yalnız duplicate bulununca çalışır.
#     - idp-detect-existing-broker-user → flow'da BULUNMAZ (create-if-unique
#         zaten detection yapar; ayrı REQUIRED detect yeni-kullanıcı branch'ini
#         kırar — Codex 019e3b72).
#   Tek customization: idp-email-verification DISABLED (realm SMTP-bağımsız;
#     existing-account linking re-authentication ile doğrulanır).
echo ""
echo "=== Step 2/5: Auto-provision first-broker-login flow ==="
FLOW_EXISTS=$($KC get authentication/flows -r "$REALM" 2>/dev/null \
  | python3 -c 'import json,sys; print("yes" if any(f.get("alias")==sys.argv[1] for f in json.load(sys.stdin)) else "no")' "$FBL_FLOW" 2>/dev/null || echo "no")

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ "$FLOW_EXISTS" = "no" ]; then
    $KC create "authentication/flows/first%20broker%20login/copy" -r "$REALM" \
      -s "newName=$FBL_FLOW" >/dev/null 2>&1 \
      || { echo "ERROR: first-broker-login flow copy failed" >&2; exit 1; }
    echo "✓ Flow copied (stock built-in): $FBL_FLOW"
  else
    echo "✓ Flow exists: $FBL_FLOW"
  fi

  # update_exec_req_by_provider <providerId> <requirement> <missing-mode>
  #   missing-mode = "error" → execution yoksa hata; "skip" → no-op.
  update_exec_req_by_provider() {
    local prov="$1" req="$2" missing="${3:-error}" eid
    eid=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$prov" 2>/dev/null || echo "")
    if [ -z "$eid" ]; then
      if [ "$missing" = "skip" ]; then
        echo "  · '$prov' flow'da yok — skip (beklenen)"
        return 0
      fi
      echo "ERROR: '$prov' execution flow'da bulunamadı" >&2
      exit 1
    fi
    $KC update "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" \
      -b "{\"id\":\"$eid\",\"requirement\":\"$req\"}" >/dev/null 2>&1 \
      || { echo "ERROR: '$prov' → $req set edilemedi" >&2; exit 1; }
    echo "✓ '$prov' → $req"
  }

  # update_subflow_req <displayName-substring> <requirement>
  update_subflow_req() {
    local name="$1" req="$2" sid
    sid=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("authenticationFlow") and sys.argv[1] in (x.get("displayName") or "")]; print(m[0]["id"] if m else "")' "$name" 2>/dev/null || echo "")
    [ -n "$sid" ] || { echo "ERROR: '$name' subflow bulunamadı" >&2; exit 1; }
    $KC update "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" \
      -b "{\"id\":\"$sid\",\"requirement\":\"$req\"}" >/dev/null 2>&1 \
      || { echo "ERROR: '$name' subflow → $req set edilemedi" >&2; exit 1; }
    echo "✓ subflow '$name' → $req"
  }

  # Stock auto-provision shape'e converge (idempotent — drift guard):
  #   create-if-unique ALTERNATIVE, Handle Existing Account ALTERNATIVE,
  #   email-verification DISABLED. Eski link-only run kalıntısı varsa
  #   idp-detect-existing-broker-user DISABLED'a çekilir (Codex: REQUIRED kalırsa
  #   yeni-kullanıcı branch'i kırılır).
  update_exec_req_by_provider idp-create-user-if-unique ALTERNATIVE error
  update_exec_req_by_provider idp-email-verification    DISABLED    error
  update_exec_req_by_provider idp-detect-existing-broker-user DISABLED skip
  update_subflow_req "Handle Existing Account" ALTERNATIVE
fi

# ── Opsiyonel: eski v1 link-only flow cleanup ─────────────────────────────
# PROD'da varsayılan KORUNUR (rollback: IdP'yi eski flow'a geri bağla).
# CLEANUP_OLD_M365_LINK_ONLY_FLOW=1 ile, IdP yeni flow'a bağlandığı
# doğrulandıktan SONRA silinir (Step 3 sonrası).

# ─── 3. Identity provider (single-tenant, desired-state) ───────────────────
echo ""
echo "=== Step 3/5: Microsoft Entra OIDC identity provider (single-tenant) ==="
IDP_EXISTS=$($KC get "identity-provider/instances/$ALIAS" -r "$REALM" --fields alias 2>/dev/null \
  | python3 -c 'import json,sys
try: print("yes" if json.load(sys.stdin).get("alias") else "no")
except Exception: print("no")' 2>/dev/null || echo "no")

if [ "$VERIFY_ONLY" != "1" ]; then
  IDP_JSON_HOST="$(mktemp /tmp/_m365_idp.XXXXXX.json)"
  IDP_JSON_CTR="/tmp/m365-idp-$$.json"
  trap 'rm -f "$IDP_JSON_HOST" "${UP_HOST:-}"; docker exec "$KC_CONTAINER" rm -f "$IDP_JSON_CTR" "${UP_CTR:-}" >/dev/null 2>&1 || true' EXIT

  # Tüm değerler env üzerinden geçer (quoted heredoc — shell interpolation yok).
  # clientSecret IdP config'ine girer; stdout'a/log'a yazılmaz.
  # v2: single-tenant → issuer sabit, validate edilebilir; trustEmail=true →
  # Entra (authoritative) email'iyle auto-created kullanıcı emailVerified gelir.
  export M365_ALIAS="$ALIAS" M365_DISPLAY="$DISPLAY" M365_CLIENT_ID="$CLIENT_ID" \
         M365_SCOPES="$SCOPES" M365_FBL_FLOW="$FBL_FLOW" \
         M365_AUTH_URL="$AUTH_URL" M365_TOKEN_URL="$TOKEN_URL" \
         M365_JWKS_URL="$JWKS_URL" M365_USERINFO_URL="$USERINFO_URL" \
         M365_ISSUER="$ISSUER"
  python3 - "$IDP_JSON_HOST" <<'PYEOF'
import json, os, sys
idp = {
  "alias": os.environ["M365_ALIAS"],
  "displayName": os.environ["M365_DISPLAY"],
  "providerId": "oidc",
  "enabled": True,
  # v2: Entra (single-tenant) email'i authoritative — auto-created kullanıcı
  # emailVerified=true gelir (Codex 019e3b72).
  "trustEmail": True,
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
    # Single-tenant issuer — JWKS signature'a ek olarak issuer doğrulaması
    # (defense-in-depth, Codex 019e3b72).
    "issuer": os.environ["M365_ISSUER"],
    "useJwksUrl": "true",
    "validateSignature": "true",
    "defaultScope": os.environ["M365_SCOPES"],
    "syncMode": "IMPORT",
    "pkceEnabled": "true",
    "pkceMethod": "S256",
    # prompt=select_account: Microsoft her giriste hesap secici gosterir.
    "prompt": "select_account",
  },
}
json.dump(idp, open(sys.argv[1], "w"))
PYEOF

  # Host temp 0600 kalır (clientSecret içerir). Container-içi kopya keycloak
  # uid'i altında umask 077 ile — kcadm okur, world-readable secret penceresi yok.
  docker exec -i "$KC_CONTAINER" sh -lc "umask 077; cat > '$IDP_JSON_CTR'" < "$IDP_JSON_HOST" \
    || { echo "ERROR: IdP JSON container'a yazılamadı" >&2; exit 1; }

  if [ "$IDP_EXISTS" = "yes" ]; then
    $KC update "identity-provider/instances/$ALIAS" -r "$REALM" -f "$IDP_JSON_CTR" 2>&1 \
      || { echo "ERROR: IdP update failed" >&2; exit 1; }
    echo "✓ IdP '$ALIAS' updated (converged to desired state)"
  else
    $KC create "identity-provider/instances" -r "$REALM" -f "$IDP_JSON_CTR" 2>&1 \
      || { echo "ERROR: IdP create failed" >&2; exit 1; }
    echo "✓ IdP '$ALIAS' created"
  fi

  # IdP yeni flow'a bağlandı — şimdi (istenirse) eski link-only flow silinebilir.
  if [ "$CLEANUP_OLD" = "1" ]; then
    BOUND_FLOW=$($KC get "identity-provider/instances/$ALIAS" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("firstBrokerLoginFlowAlias",""))' 2>/dev/null || echo "")
    if [ "$BOUND_FLOW" = "$FBL_FLOW" ]; then
      OLD_FLOW_ID=$($KC get authentication/flows -r "$REALM" 2>/dev/null \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[f for f in d if f.get("alias")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$OLD_FBL_FLOW" 2>/dev/null || echo "")
      if [ -n "$OLD_FLOW_ID" ]; then
        $KC delete "authentication/flows/$OLD_FLOW_ID" -r "$REALM" >/dev/null 2>&1 \
          || { echo "ERROR: eski flow '$OLD_FBL_FLOW' silinemedi" >&2; exit 1; }
        echo "✓ Eski flow silindi: $OLD_FBL_FLOW"
      else
        echo "  · Eski flow '$OLD_FBL_FLOW' zaten yok"
      fi
    else
      echo "ERROR: IdP beklenen flow'a bağlı değil ('$BOUND_FLOW') — cleanup iptal" >&2
      exit 1
    fi
  fi
fi

# ─── 4. Mappers: claim (tid/oid) + hardcoded default role ──────────────────
echo ""
echo "=== Step 4/5: Claim mappers + default-role mapper + user-profile ==="

# update path PUT body'sinde 'id' bekler — id'siz body re-apply'da "update
# failed" verir (idempotency). create path'te id konmaz.
upsert_idp_mapper() {
  # upsert_idp_mapper <name> <mapperType> <config-json>
  local name="$1" mtype="$2" cfg="$3"
  [ "$VERIFY_ONLY" = "1" ] && return 0
  local existing mh mc
  existing=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("name")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$name" 2>/dev/null || echo "")
  mh="$(mktemp /tmp/_m365_map.XXXXXX.json)"
  mc="/tmp/m365-map-$$-${name}.json"
  M365_MAP_NAME="$name" M365_MAP_TYPE="$mtype" M365_MAP_CFG="$cfg" M365_MAP_ID="$existing" \
    python3 - "$mh" <<'PYEOF'
import json, os, sys
m = {
  "name": os.environ["M365_MAP_NAME"],
  "identityProviderAlias": "microsoft",
  "identityProviderMapper": os.environ["M365_MAP_TYPE"],
  "config": json.loads(os.environ["M365_MAP_CFG"]),
}
existing = os.environ.get("M365_MAP_ID", "")
if existing:
  m["id"] = existing
json.dump(m, open(sys.argv[1], "w"))
PYEOF
  docker exec -i "$KC_CONTAINER" sh -lc "umask 077; cat > '$mc'" < "$mh" \
    || { echo "ERROR: mapper $name container'a yazılamadı" >&2; rm -f "$mh"; exit 1; }
  if [ -n "$existing" ]; then
    $KC update "identity-provider/instances/$ALIAS/mappers/$existing" -r "$REALM" -f "$mc" >/dev/null 2>&1 \
      || { echo "ERROR: mapper $name update failed" >&2; rm -f "$mh"; exit 1; }
    echo "  ✓ mapper '$name' converged"
  else
    $KC create "identity-provider/instances/$ALIAS/mappers" -r "$REALM" -f "$mc" >/dev/null 2>&1 \
      || { echo "ERROR: mapper $name create failed" >&2; rm -f "$mh"; exit 1; }
    echo "  ✓ mapper '$name' created"
  fi
  rm -f "$mh"
  docker exec "$KC_CONTAINER" rm -f "$mc" >/dev/null 2>&1 || true
}

# Claim mapper'lar: tid/oid → user attribute. FORCE — tid/oid immutable/audit
# nitelikli, her federe giriş yeniden yazar (Codex 019e365b P2).
upsert_idp_mapper "entra-tid" "oidc-user-attribute-idp-mapper" \
  '{"syncMode":"FORCE","claim":"tid","user.attribute":"entra_tid"}'
upsert_idp_mapper "entra-oid" "oidc-user-attribute-idp-mapper" \
  '{"syncMode":"FORCE","claim":"oid","user.attribute":"entra_oid"}'

# Hardcoded default-role mapper — yeni (auto-provision) kullanıcıya `viewer`
# realm rolü. syncMode=IMPORT: rol ilk provision/link'te verilir, admin sonradan
# kaldırırsa her login'de geri basılmaz (revocation semantics korunur — Codex
# 019e3b72). default-roles-serban'a DOKUNULMAZ — M365-targeted kalır.
if [ "$VERIFY_ONLY" != "1" ]; then
  ROLE_EXISTS=$($KC get "roles/$DEFAULT_ROLE" -r "$REALM" --fields name 2>/dev/null \
    | python3 -c 'import json,sys
try: print("yes" if json.load(sys.stdin).get("name") else "no")
except Exception: print("no")' 2>/dev/null || echo "no")
  [ "$ROLE_EXISTS" = "yes" ] \
    || { echo "ERROR: realm rolü '$DEFAULT_ROLE' yok — hardcoded-role mapper kurulamaz" >&2; exit 1; }
fi
upsert_idp_mapper "$ROLE_MAPPER_NAME" "oidc-hardcoded-role-idp-mapper" \
  "{\"syncMode\":\"IMPORT\",\"role\":\"$DEFAULT_ROLE\"}"

# ── User-profile attribute deklarasyonu (KC 26 Declarative User Profile) ───
# unmanagedAttributePolicy DISABLED iken deklare edilmemiş attribute sessizce
# düşer → entra_tid/entra_oid mapper yazımları kalıcı olmaz. Append-only.
if [ "$VERIFY_ONLY" != "1" ]; then
  UP_HOST="$(mktemp /tmp/_m365_up.XXXXXX.json)"
  UP_CTR="/tmp/m365-up-$$.json"
  $KC get users/profile -r "$REALM" > "$UP_HOST" 2>/dev/null || true
  [ -s "$UP_HOST" ] || { echo "ERROR: users/profile okunamadı" >&2; rm -f "$UP_HOST"; exit 1; }
  UP_CHANGED=$(python3 - "$UP_HOST" <<'UPEOF'
import json, sys
path = sys.argv[1]
prof = json.load(open(path))
attrs = prof.setdefault("attributes", [])
have = {a.get("name") for a in attrs}
added = []
for name, disp in (("entra_tid", "Entra Tenant ID"), ("entra_oid", "Entra Object ID")):
    if name not in have:
        attrs.append({"name": name, "displayName": disp,
                      "permissions": {"view": ["admin"], "edit": ["admin"]},
                      "multivalued": False})
        added.append(name)
json.dump(prof, open(path, "w"))
print(",".join(added))
UPEOF
)
  if [ -n "$UP_CHANGED" ]; then
    docker exec -i "$KC_CONTAINER" sh -lc "umask 077; cat > '$UP_CTR'" < "$UP_HOST" \
      || { echo "ERROR: user-profile JSON container'a yazılamadı" >&2; rm -f "$UP_HOST"; exit 1; }
    $KC update users/profile -r "$REALM" -f "$UP_CTR" >/dev/null 2>&1 \
      || { echo "ERROR: user-profile güncellenemedi" >&2; rm -f "$UP_HOST"; \
           docker exec "$KC_CONTAINER" rm -f "$UP_CTR" >/dev/null 2>&1 || true; exit 1; }
    echo "  ✓ user-profile: $UP_CHANGED deklare edildi"
    docker exec "$KC_CONTAINER" rm -f "$UP_CTR" >/dev/null 2>&1 || true
  else
    echo "  ✓ user-profile: entra_tid + entra_oid zaten deklare"
  fi
  rm -f "$UP_HOST"
fi

# ─── 4b. Client token mapper: entra_tid user-attr → token claim ────────────
# DURABILITY FIX (Codex thread 019ef32b, Option A). Steps above only write the
# entra_tid USER ATTRIBUTE (IdP mapper) and declare it in the user profile —
# but NO client protocol mapper surfaces it INTO the issued token. The backend
# M365 auto-provision gate (requireCurrentUser → JwtAutoProvisionGate) REQUIRES
# an `entra_tid` token claim as its M365 marker; without this mapper every M365
# login is denied `missing-entra-tid` and auto-provision never works for anyone
# (the live bug, hotfixed by a direct DB insert this step now makes durable
# across a KC re-bootstrap). Mirrors that proven mapper exactly:
# oidc-usermodel-attribute-mapper on the SPA realm client, entra_tid →
# claim.name=entra_tid (access+id+userinfo). Idempotent by name; fail-CLOSED if
# a FOREIGN mapper already emits the entra_tid claim — directly OR via a default
# client scope — to avoid a duplicate-claim conflict (Codex 019ef32b (b)).
TOKEN_CLIENT_ID="${TOKEN_CLIENT_ID:-frontend}"
ENTRA_TID_MAPPER="entra-tid"
echo ""
echo "=== Step 4b: Client token mapper ('$ENTRA_TID_MAPPER' on client '$TOKEN_CLIENT_ID') ==="

# Resolve the realm client (exactly one) that mints SPA / user-service tokens,
# via JSON parse (repo pattern; avoids any CSV-header ambiguity across kcadm
# versions — Codex 019ef32b). Resolved ALWAYS (also under VERIFY_ONLY=1, since
# the Step 5 read-back needs it). Read failure → fail-closed.
if ! FE_CLIENTS_JSON=$($KC get clients -r "$REALM" -q "clientId=$TOKEN_CLIENT_ID" --fields id 2>/dev/null); then
  echo "ERROR: token client lookup ('$TOKEN_CLIENT_ID') kcadm okuması başarısız" >&2
  exit 1
fi
FE_CLIENT_ID=$(printf '%s' "$FE_CLIENTS_JSON" | python3 -c '
import json, sys
try:
    arr = json.load(sys.stdin)
except Exception:
    arr = []
ids = [c.get("id") for c in arr if c.get("id")] if isinstance(arr, list) else []
print(ids[0] if len(ids) == 1 else "")
' 2>/dev/null || echo "")
if [ -z "$FE_CLIENT_ID" ]; then
  echo "ERROR: token client '$TOKEN_CLIENT_ID' bu realm'de tek eşleşme değil." >&2
  echo "       SPA token client adı farklıysa TOKEN_CLIENT_ID env ile verin." >&2
  exit 1
fi
echo "  · token client internal id: $FE_CLIENT_ID"

# Shared helper: print the client's EFFECTIVE entra_tid claim surface as a JSON
# object {"direct":[...],"scoped":[...]} — direct protocol mappers PLUS every
# default-client-scope's mappers. FAIL-CLOSED: any kcadm read error prints an
# ERR_* token (never a fake-empty result) so the duplicate/collision guard
# cannot be silently disabled by an API hiccup (Codex 019ef32b (3)). Callers
# MUST treat an ERR_* line as fatal.
collect_entra_tid_surface() {
  local fe_id="$1" direct scopes_json sids sid sm agg
  if ! direct=$($KC get "clients/$fe_id/protocol-mappers/models" -r "$REALM" 2>/dev/null); then
    echo "ERR_READ_DIRECT"; return 0
  fi
  if ! scopes_json=$($KC get "clients/$fe_id/default-client-scopes" -r "$REALM" 2>/dev/null); then
    echo "ERR_READ_DEFAULT_SCOPES"; return 0
  fi
  sids=$(printf '%s' "$scopes_json" | python3 -c '
import json, sys
try:
    arr = json.load(sys.stdin)
except Exception:
    arr = []
[print(s["id"]) for s in (arr if isinstance(arr, list) else []) if s.get("id")]
' 2>/dev/null || echo "")
  agg="$(mktemp /tmp/_m365_surf.XXXXXX.json)"; echo "[]" > "$agg"
  for sid in $sids; do
    if ! sm=$($KC get "client-scopes/$sid/protocol-mappers/models" -r "$REALM" 2>/dev/null); then
      rm -f "$agg"; echo "ERR_READ_SCOPE_MAPPERS"; return 0
    fi
    M365_AGG="$(cat "$agg")" M365_SM="$sm" python3 - "$agg" <<'AGGEOF'
import json, os, sys
try: agg = json.loads(os.environ.get("M365_AGG") or "[]")
except Exception: agg = []
try: sm = json.loads(os.environ.get("M365_SM") or "[]")
except Exception: sm = []
if not isinstance(agg, list): agg = []
if isinstance(sm, list): agg.extend(sm)
json.dump(agg, open(sys.argv[1], "w"))
AGGEOF
  done
  M365_DIRECT="$direct" M365_SCOPED="$(cat "$agg")" python3 -c '
import json, os
def load(e):
    try:
        v = json.loads(os.environ.get(e) or "[]"); return v if isinstance(v, list) else []
    except Exception:
        return []
print(json.dumps({"direct": load("M365_DIRECT"), "scoped": load("M365_SCOPED")}))
' 2>/dev/null || echo "ERR_SURFACE_BUILD"
  rm -f "$agg"
}

if [ "$VERIFY_ONLY" != "1" ]; then
  # Build the EFFECTIVE entra_tid surface (direct + default scopes), fail-closed.
  SURFACE=$(collect_entra_tid_surface "$FE_CLIENT_ID")
  case "$SURFACE" in
    ERR_*)
      echo "ERROR: entra_tid surface read failed ($SURFACE) — fail-closed, mapper kararı verilmiyor" >&2
      exit 1
      ;;
  esac
  # Decision: CREATE | UPDATE:<id> | NOOP | FAIL:<reason>.
  # OWNERSHIP = ANY mapper whose config.claim.name == entra_tid, regardless of
  # protocolMapper type (Codex 019ef32b (1) — a hardcoded-claim or script mapper
  # emitting entra_tid must also count). A scoped owner, OR a direct owner not
  # named '$ENTRA_TID_MAPPER', is FOREIGN → fail-closed (avoid duplicate claim).
  # The expected mapper is validated separately for protocolMapper + 7-key cfg.
  DECISION=$(M365_SURFACE="$SURFACE" M365_NAME="$ENTRA_TID_MAPPER" python3 -c '
import json, os
name = os.environ["M365_NAME"]
CLAIM = "entra_tid"
try:
    surf = json.loads(os.environ.get("M365_SURFACE") or "{}")
    if not isinstance(surf, dict): surf = {}
except Exception:
    surf = {}
direct = surf.get("direct") or []
scoped = surf.get("scoped") or []
def owns(m):
    return (m.get("config") or {}).get("claim.name") == CLAIM
want = {"user.attribute": "entra_tid", "claim.name": "entra_tid", "jsonType.label": "String",
        "access.token.claim": "true", "id.token.claim": "true",
        "userinfo.token.claim": "true", "multivalued": "false"}
foreign = [m for m in direct if owns(m) and m.get("name") != name] + [m for m in scoped if owns(m)]
mine = [m for m in direct if m.get("name") == name]
if foreign:
    print("FAIL:foreign mapper(s) already emit entra_tid: " + ", ".join(str(m.get("name")) for m in foreign))
elif len(mine) > 1:
    print("FAIL:multiple direct mappers named " + name)
elif mine:
    m = mine[0]; cfg = m.get("config") or {}
    correct = (m.get("protocolMapper") == "oidc-usermodel-attribute-mapper"
               and all(str(cfg.get(k)) == v for k, v in want.items()))
    print("NOOP" if correct else "UPDATE:" + str(m.get("id")))
else:
    print("CREATE")
' 2>/dev/null || echo "FAIL:decision script error")

  case "$DECISION" in
    FAIL:*)
      echo "ERROR: entra_tid client-mapper guard: ${DECISION#FAIL:}" >&2
      exit 1
      ;;
    NOOP)
      echo "  ✓ client mapper '$ENTRA_TID_MAPPER' zaten doğru (no-op)"
      ;;
    CREATE|UPDATE:*)
      CM_ID=""
      if [ "${DECISION%%:*}" = "UPDATE" ]; then CM_ID="${DECISION#UPDATE:}"; fi
      CM_HOST="$(mktemp /tmp/_m365_cm.XXXXXX.json)"
      CM_CTR="/tmp/m365-cm-$$.json"
      M365_CM_NAME="$ENTRA_TID_MAPPER" M365_CM_ID="$CM_ID" python3 - "$CM_HOST" <<'CMEOF'
import json, os, sys
m = {
    "name": os.environ["M365_CM_NAME"],
    "protocol": "openid-connect",
    "protocolMapper": "oidc-usermodel-attribute-mapper",
    "config": {
        "user.attribute": "entra_tid",
        "claim.name": "entra_tid",
        "jsonType.label": "String",
        "access.token.claim": "true",
        "id.token.claim": "true",
        "userinfo.token.claim": "true",
        "multivalued": "false",
    },
}
mid = os.environ.get("M365_CM_ID", "")
if mid:
    m["id"] = mid
json.dump(m, open(sys.argv[1], "w"))
CMEOF
      docker exec -i "$KC_CONTAINER" sh -lc "umask 077; cat > '$CM_CTR'" < "$CM_HOST" \
        || { echo "ERROR: client mapper container'a yazılamadı" >&2; rm -f "$CM_HOST"; exit 1; }
      if [ -n "$CM_ID" ]; then
        $KC update "clients/$FE_CLIENT_ID/protocol-mappers/models/$CM_ID" -r "$REALM" -f "$CM_CTR" >/dev/null 2>&1 \
          || { echo "ERROR: client mapper update failed" >&2; rm -f "$CM_HOST"; exit 1; }
        echo "  ✓ client mapper '$ENTRA_TID_MAPPER' converged (update)"
      else
        $KC create "clients/$FE_CLIENT_ID/protocol-mappers/models" -r "$REALM" -f "$CM_CTR" >/dev/null 2>&1 \
          || { echo "ERROR: client mapper create failed" >&2; rm -f "$CM_HOST"; exit 1; }
        echo "  ✓ client mapper '$ENTRA_TID_MAPPER' created"
      fi
      rm -f "$CM_HOST"
      docker exec "$KC_CONTAINER" rm -f "$CM_CTR" >/dev/null 2>&1 || true
      ;;
    *)
      echo "ERROR: beklenmeyen client-mapper kararı: '$DECISION'" >&2
      exit 1
      ;;
  esac
fi

# ─── 5. Verify (read-back assertions) ──────────────────────────────────────
echo ""
echo "=== Step 5/5: Verify ==="
# IdP: single-tenant endpoints + issuer + trustEmail + auto-provision flow bind.
IDP_VERIFY=$($KC get "identity-provider/instances/$ALIAS" -r "$REALM" 2>/dev/null \
  | M365_EXP_ISSUER="$ISSUER" M365_EXP_TENANT="$TENANT_ID" M365_EXP_FLOW="$FBL_FLOW" python3 -c '
import json, os, sys
try:
    idp = json.load(sys.stdin)
except Exception:
    print("FAIL: IdP not found"); sys.exit()
cfg = idp.get("config", {})
tid = os.environ["M365_EXP_TENANT"]
urls = [cfg.get("authorizationUrl",""), cfg.get("tokenUrl",""),
        cfg.get("jwksUrl",""), cfg.get("issuer","")]
checks = {
    "providerId_oidc": idp.get("providerId") == "oidc",
    "enabled": idp.get("enabled") in (True, "true"),
    "trustEmail_true": idp.get("trustEmail") in (True, "true"),
    "auto_provision_flow": idp.get("firstBrokerLoginFlowAlias") == os.environ["M365_EXP_FLOW"],
    "client_id_set": bool(cfg.get("clientId")),
    "jwks_url_set": bool(cfg.get("jwksUrl")),
    "validate_signature": cfg.get("validateSignature") == "true",
    "prompt_select_account": cfg.get("prompt") == "select_account",
    "syncMode_import": cfg.get("syncMode") == "IMPORT",
    "issuer_single_tenant": cfg.get("issuer") == os.environ["M365_EXP_ISSUER"],
    "endpoints_tenant_scoped": all(tid in u for u in urls[:3]),
    "no_organizations_endpoint": not any("/organizations/" in u for u in urls),
}
for k, v in checks.items():
    print(f"  {k}={v}")
print("FAIL" if [k for k, v in checks.items() if not v] else "PASS")
' 2>/dev/null || echo "FAIL: verify error")
echo "$IDP_VERIFY"
echo "$IDP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: IdP verify FAILED" >&2; exit 3; }

# Mapper'lar: entra-tid/oid (FORCE) + default-role (IMPORT, role=viewer).
MAP_VERIFY=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
  | M365_EXP_ROLEMAP="$ROLE_MAPPER_NAME" M365_EXP_ROLE="$DEFAULT_ROLE" python3 -c '
import json, os, sys
d = json.load(sys.stdin)
ok = True
rolemap = os.environ["M365_EXP_ROLEMAP"]
exprole = os.environ["M365_EXP_ROLE"]
def find(name):
    m = [x for x in d if x.get("name") == name]
    return m[0] if m else None
for name in ("entra-tid", "entra-oid"):
    m = find(name)
    if not m:
        print(f"  mapper {name}=MISSING"); ok = False; continue
    sm = m.get("config", {}).get("syncMode")
    print(f"  mapper {name} syncMode={sm}")
    if sm != "FORCE":
        ok = False
rm = find(rolemap)
if not rm:
    print(f"  mapper {rolemap}=MISSING"); ok = False
else:
    cfg = rm.get("config", {})
    mt = rm.get("identityProviderMapper")
    role = cfg.get("role")
    sm = cfg.get("syncMode")
    print(f"  mapper {rolemap} type={mt} role={role} syncMode={sm}")
    if mt != "oidc-hardcoded-role-idp-mapper": ok = False
    if role != exprole: ok = False
    if sm != "IMPORT": ok = False
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: mapper verify error")
echo "$MAP_VERIFY"
echo "$MAP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: mapper verify FAILED" >&2; exit 3; }

# Auto-provision flow invariant — create-if-unique ALTERNATIVE (auto-create
# açık), email-verification DISABLED, Handle Existing Account ALTERNATIVE,
# idp-detect-existing-broker-user REQUIRED DEĞİL (yoksa PASS, varsa DISABLED).
FLOW_VERIFY=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
ok = True
def prov(p):
    m = [x for x in d if x.get("providerId") == p]
    return m[0] if m else None
def sub(name):
    m = [x for x in d if x.get("authenticationFlow") and name in (x.get("displayName") or "")]
    return m[0] if m else None
cui = prov("idp-create-user-if-unique")
r = cui.get("requirement") if cui else "MISSING"
print(f"  exec idp-create-user-if-unique={r}")
if r != "ALTERNATIVE":
    ok = False
ev = prov("idp-email-verification")
r = ev.get("requirement") if ev else "MISSING"
print(f"  exec idp-email-verification={r}")
if r != "DISABLED":
    ok = False
det = prov("idp-detect-existing-broker-user")
dr = det.get("requirement") if det else "ABSENT"
print(f"  exec idp-detect-existing-broker-user={dr}")
if dr not in ("ABSENT", "DISABLED"):
    ok = False
hea = sub("Handle Existing Account")
hr = hea.get("requirement") if hea else "MISSING"
print(f"  subflow Handle-Existing-Account={hr}")
if hr != "ALTERNATIVE":
    ok = False
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: flow verify error")
echo "$FLOW_VERIFY"
echo "$FLOW_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: auto-provision flow verify FAILED — flow yapısı hatalı" >&2; exit 3; }

# User-profile entra_tid/entra_oid deklarasyon read-back.
UP_VERIFY=$($KC get users/profile -r "$REALM" 2>/dev/null \
  | python3 -c '
import json, sys
try:
    prof = json.load(sys.stdin)
except Exception:
    print("FAIL: users/profile okunamadı"); sys.exit()
names = {a.get("name") for a in prof.get("attributes", [])}
ok = True
for n in ("entra_tid", "entra_oid"):
    present = n in names
    print(f"  user-profile attr {n}={present}")
    if not present:
        ok = False
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: user-profile verify error")
echo "$UP_VERIFY"
echo "$UP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: user-profile verify FAILED" >&2; exit 3; }

# Client token mapper read-back: EXACTLY ONE EFFECTIVE entra_tid claim emitter
# on the token client — direct mappers PLUS default-client-scope mappers
# combined (Codex 019ef32b (2)/(d)) — and that one is the DIRECT
# '$ENTRA_TID_MAPPER' (oidc-usermodel-attribute-mapper) with the full 7-key
# config; zero scoped emitters. Reuses the same fail-closed surface collector
# as the apply path so a default-scope drift can't slip past a verify-only run.
# Structural gate only — issued-token decode after a fresh M365 login is the
# acceptance smoke (RB-m365-sso-broker.md), since an existing session token
# won't carry the new claim until refreshed.
CM_SURFACE=$(collect_entra_tid_surface "$FE_CLIENT_ID")
case "$CM_SURFACE" in
  ERR_*)
    echo "ERROR: client token mapper verify — surface read failed ($CM_SURFACE)" >&2
    exit 3
    ;;
esac
CM_VERIFY=$(M365_SURFACE="$CM_SURFACE" M365_NAME="$ENTRA_TID_MAPPER" python3 -c '
import json, os
name = os.environ["M365_NAME"]
CLAIM = "entra_tid"
try:
    surf = json.loads(os.environ.get("M365_SURFACE") or "{}")
    if not isinstance(surf, dict): surf = {}
except Exception:
    surf = {}
direct = surf.get("direct") or []
scoped = surf.get("scoped") or []
def owns(m):
    return (m.get("config") or {}).get("claim.name") == CLAIM
direct_owners = [m for m in direct if owns(m)]
scoped_owners = [m for m in scoped if owns(m)]
ok = True
print(f"  effective entra_tid emitters: direct={len(direct_owners)} scoped={len(scoped_owners)}")
if len(scoped_owners) != 0:
    ok = False
    print("  FAIL: a default client scope emits entra_tid (duplicate-claim risk)")
if len(direct_owners) != 1:
    ok = False
else:
    m = direct_owners[0]; cfg = m.get("config") or {}
    want = {"user.attribute": "entra_tid", "claim.name": "entra_tid", "jsonType.label": "String",
            "access.token.claim": "true", "id.token.claim": "true",
            "userinfo.token.claim": "true", "multivalued": "false"}
    print(f"  mapper name={m.get(\"name\")} protocolMapper={m.get(\"protocolMapper\")}")
    if m.get("name") != name:
        ok = False
    if m.get("protocolMapper") != "oidc-usermodel-attribute-mapper":
        ok = False
    for k, v in want.items():
        if str(cfg.get(k)) != v:
            ok = False
            print(f"  cfg {k}={cfg.get(k)} (want {v})")
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: client mapper verify error")
echo "$CM_VERIFY"
echo "$CM_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: client token mapper verify FAILED — entra_tid claim mapper eksik/yanlış" >&2; exit 3; }

echo ""
echo "=== M365 broker apply (v2 auto-provision) — PASS (realm=$REALM) ==="
echo "Next: browser smoke — RB-m365-sso-broker.md (yeni kullanıcı auto-create +"
echo "      /api/v1/authz/me + salt-okunur route veri-görünürlük doğrulaması)."
exit 0
