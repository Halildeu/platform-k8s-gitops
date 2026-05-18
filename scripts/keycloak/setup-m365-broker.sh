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
# kcadm path segments must URL-encode spaces (KC 26 kcadm rejects raw spaces).
FBL_FLOW_ENC="${FBL_FLOW// /%20}"

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
# ADR-0021 D4 link-only (Codex 019e3796):
#   - idp-create-user-if-unique       DISABLED → federe auto-create yok
#   - idp-detect-existing-broker-user REQUIRED → mevcut kullanıcı tespiti
#       (create-if-unique disable edilince built-in flow'un tespit adımı da
#        kapanır; ayrı detect authenticator şart — yoksa eşleşen kullanıcı
#        bulunamaz, flow AuthenticationFlowException ile düşer)
#   - Handle Existing Account         REQUIRED, detect ondan ÖNCE çalışır
#   - idp-email-verification          DISABLED → re-authentication ile doğrula
echo ""
echo "=== Step 2/5: Link-only first-broker-login flow ==="
FLOW_EXISTS=$($KC get authentication/flows -r "$REALM" 2>/dev/null \
  | python3 -c 'import json,sys; print("yes" if any(f.get("alias")==sys.argv[1] for f in json.load(sys.stdin)) else "no")' "$FBL_FLOW" 2>/dev/null || echo "no")

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ "$FLOW_EXISTS" = "no" ]; then
    $KC create "authentication/flows/first%20broker%20login/copy" -r "$REALM" \
      -s "newName=$FBL_FLOW" >/dev/null 2>&1 \
      || { echo "ERROR: first-broker-login flow copy failed" >&2; exit 1; }
    echo "✓ Flow copied: $FBL_FLOW"
  else
    echo "✓ Flow exists: $FBL_FLOW"
  fi
  # Link-only + SMTP-bağımsız — şu execution'lar DISABLED:
  #   idp-create-user-if-unique → eşleşmeyen federe kullanıcı oluşturulmaz
  #   idp-email-verification    → linking email-verify yerine re-authentication
  #     ile yapılır (realm SMTP'siz olabilir; kullanıcı mevcut hesap parolasıyla
  #     doğrular — kör email-link değil; Codex 019e365b).
  for PROV in idp-create-user-if-unique idp-email-verification; do
    EXEC_ID=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$PROV" 2>/dev/null || echo "")
    if [ -n "$EXEC_ID" ]; then
      $KC update "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" \
        -b "{\"id\":\"$EXEC_ID\",\"requirement\":\"DISABLED\"}" >/dev/null 2>&1 \
        || { echo "ERROR: $PROV disable failed" >&2; exit 1; }
      echo "✓ '$PROV' → DISABLED"
    else
      echo "ERROR: '$PROV' execution flow'da bulunamadı — link-only invariant" >&2
      echo "       kurulamaz (KC 26 flow yapısı farklı olabilir; manuel inceleme)" >&2
      exit 1
    fi
  done

  # ── Mevcut-kullanıcı tespiti — idp-detect-existing-broker-user (Codex 019e3796)
  # idp-create-user-if-unique DISABLED edilince built-in flow'un tespit adımı da
  # kapanır → EXISTING_USER_INFO set edilmez → idp-confirm-link "No duplication
  # detected" der, flow düşer. Çözüm: detect authenticator'ı "User creation or
  # linking" subflow'una REQUIRED ekle; "Handle Existing Account" REQUIRED yap;
  # detect ondan önce çalışsın.
  # NOT: `authentication/flows` yalnız TOP-LEVEL flow listeler — subflow alias'ı
  # oradan map edilemez; subflow execution'ının displayName'i = subflow alias.
  UCL_ALIAS=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("authenticationFlow") and "User creation or linking" in (x.get("displayName") or "")]; print(m[0]["displayName"] if m else "")' 2>/dev/null || echo "")
  [ -n "$UCL_ALIAS" ] || { echo "ERROR: 'User creation or linking' subflow bulunamadı" >&2; exit 1; }
  UCL_ENC="${UCL_ALIAS// /%20}"

  DETECT_ID=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")=="idp-detect-existing-broker-user"]; print(m[0]["id"] if m else "")' 2>/dev/null || echo "")
  if [ -z "$DETECT_ID" ]; then
    $KC create "authentication/flows/$UCL_ENC/executions/execution" -r "$REALM" \
      -s provider=idp-detect-existing-broker-user >/dev/null 2>&1 \
      || { echo "ERROR: idp-detect-existing-broker-user eklenemedi" >&2; exit 1; }
    DETECT_ID=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")=="idp-detect-existing-broker-user"]; print(m[0]["id"] if m else "")' 2>/dev/null || echo "")
    echo "✓ 'idp-detect-existing-broker-user' eklendi"
  else
    echo "✓ 'idp-detect-existing-broker-user' mevcut"
  fi
  [ -n "$DETECT_ID" ] || { echo "ERROR: detect execution id alınamadı" >&2; exit 1; }
  $KC update "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" \
    -b "{\"id\":\"$DETECT_ID\",\"requirement\":\"REQUIRED\"}" >/dev/null 2>&1 \
    || { echo "ERROR: detect REQUIRED set edilemedi" >&2; exit 1; }
  echo "✓ 'idp-detect-existing-broker-user' → REQUIRED"

  HANDLE_ID=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("authenticationFlow") and "Handle Existing Account" in (x.get("displayName") or "")]; print(m[0]["id"] if m else "")' 2>/dev/null || echo "")
  [ -n "$HANDLE_ID" ] || { echo "ERROR: 'Handle Existing Account' subflow bulunamadı" >&2; exit 1; }
  $KC update "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" \
    -b "{\"id\":\"$HANDLE_ID\",\"requirement\":\"REQUIRED\"}" >/dev/null 2>&1 \
    || { echo "ERROR: 'Handle Existing Account' REQUIRED set edilemedi" >&2; exit 1; }
  echo "✓ 'Handle Existing Account' → REQUIRED"

  # detect, "Handle Existing Account"tan ÖNCE çalışmalı (priority raise loop)
  for _ in 1 2 3 4 5 6; do
    DI=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("providerId")=="idp-detect-existing-broker-user"]; print(m[0]["index"] if m else 999)' 2>/dev/null || echo 999)
    HI=$($KC get "authentication/flows/$FBL_FLOW_ENC/executions" -r "$REALM" 2>/dev/null \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("authenticationFlow") and "Handle Existing Account" in (x.get("displayName") or "")]; print(m[0]["index"] if m else -1)' 2>/dev/null || echo -1)
    [ "$DI" -lt "$HI" ] && break
    $KC create "authentication/executions/$DETECT_ID/raise-priority" -r "$REALM" >/dev/null 2>&1 \
      || { echo "ERROR: detect priority raise failed" >&2; exit 1; }
  done
  [ "$DI" -lt "$HI" ] \
    || { echo "ERROR: detect, 'Handle Existing Account' önüne alınamadı (index $DI >= $HI)" >&2; exit 1; }
  echo "✓ detect → 'Handle Existing Account' önünde (priority OK)"
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
  trap 'rm -f "$IDP_JSON_HOST" "${UP_HOST:-}"; docker exec "$KC_CONTAINER" rm -f "$IDP_JSON_CTR" "${UP_CTR:-}" >/dev/null 2>&1 || true' EXIT

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
    # prompt=select_account: Microsoft her giriste hesap secici gosterir —
    # kullanici dogru M365 hesabini secebilir / "use another account" yapabilir.
    # Olmadan, tarayicida acik MS hesabi otomatik kullanilir (hesap degistirilemez).
    "prompt": "select_account",
  },
}
json.dump(idp, open(sys.argv[1], "w"))
PYEOF

  # Host temp dosyası 0600 kalır (clientSecret içerir). Container-içi kopya
  # docker exec -i ile keycloak uid'i altında, umask 077 ile oluşturulur —
  # kcadm okur, host'ta world-readable secret penceresi yok (Codex 019e365b).
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
fi

# ─── 4. Claim mappers (tid → entra_tid, oid → entra_oid) ───────────────────
echo ""
echo "=== Step 4/5: Claim mappers + user-profile attributes ==="
upsert_attr_mapper() {
  local name="$1" claim="$2" attr="$3"
  [ "$VERIFY_ONLY" = "1" ] && return 0
  local existing
  existing=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("name")==sys.argv[1]]; print(m[0]["id"] if m else "")' "$name" 2>/dev/null || echo "")
  local mh mc
  mh="$(mktemp /tmp/_m365_map.XXXXXX.json)"
  mc="/tmp/m365-map-$$-${name}.json"
  python3 - "$mh" "$name" "$claim" "$attr" "$existing" <<'PYEOF'
import json, sys
_, path, name, claim, attr, existing = sys.argv
m = {
  "name": name,
  "identityProviderAlias": "microsoft",
  "identityProviderMapper": "oidc-user-attribute-idp-mapper",
  "config": {
    # FORCE: her federe giriş attribute'u yeniden yazar; link-only v1'de
    # kullanıcı zaten mevcut, IMPORT semantiği tetiklenmez (Codex 019e365b P2).
    "syncMode": "FORCE",
    "claim": claim,
    "user.attribute": attr
  }
}
# Update path'inde (mapper mevcut) Keycloak PUT body'sinde 'id' bekler —
# id'siz body re-apply'da "update failed" verir (idempotency bug fix).
if existing:
  m["id"] = existing
json.dump(m, open(path, "w"))
PYEOF
  # Container-içi kopya keycloak uid'i altında, umask 077 ile (IdP ile aynı
  # pattern — host temp 0600 kalır; tutarlılık, Codex 019e365b).
  docker exec -i "$KC_CONTAINER" sh -lc "umask 077; cat > '$mc'" < "$mh" \
    || { echo "ERROR: mapper $name container'a yazılamadı" >&2; rm -f "$mh"; exit 1; }
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

# ── User-profile attribute deklarasyonu (Codex 019e3796 / smoke bulgusu) ──
# Keycloak 26 Declarative User Profile, unmanagedAttributePolicy DISABLED iken
# deklare edilmemiş attribute'ları sessizce düşürür → yukarıdaki mapper'ların
# entra_tid/entra_oid yazımları kalıcı olmaz. Attribute'lar profile'a deklare
# edilir — mevcut profil korunur, yalnız eksik olan(lar) append edilir.
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
    "prompt_select_account": cfg.get("prompt") == "select_account",
}
for k, v in checks.items():
    print(f"  {k}={v}")
print("FAIL" if [k for k, v in checks.items() if not v] else "PASS")
' 2>/dev/null || echo "FAIL: verify error")
echo "$IDP_VERIFY"
echo "$IDP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: IdP verify FAILED" >&2; exit 3; }

MAP_VERIFY=$($KC get "identity-provider/instances/$ALIAS/mappers" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
ok = True
for name in ("entra-tid", "entra-oid"):
    m = [x for x in d if x.get("name") == name]
    if not m:
        print(f"  mapper {name}=MISSING"); ok = False; continue
    sm = m[0].get("config", {}).get("syncMode")
    print(f"  mapper {name} syncMode={sm}")
    if sm != "FORCE":
        ok = False
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: mapper verify error")
echo "$MAP_VERIFY"
echo "$MAP_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: mapper verify FAILED (presence / syncMode != FORCE)" >&2; exit 3; }

# Link-only invariant — first-broker-login flow yapısı read-back (Codex
# 019e365b P1 + 019e3796). Bu scriptin ana güvenlik kontratı; create-if-unique
# /email-verification DISABLED + detect REQUIRED (Handle'dan önce) + Handle/
# confirm-link/username-password-form REQUIRED doğrulanmadan PASS verilmez.
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
for p in ("idp-create-user-if-unique", "idp-email-verification"):
    e = prov(p); r = e.get("requirement") if e else "MISSING"
    print(f"  exec {p}={r}")
    if r != "DISABLED":
        ok = False
for p in ("idp-detect-existing-broker-user", "idp-confirm-link", "idp-username-password-form"):
    e = prov(p); r = e.get("requirement") if e else "MISSING"
    print(f"  exec {p}={r}")
    if r != "REQUIRED":
        ok = False
hea = sub("Handle Existing Account")
hr = hea.get("requirement") if hea else "MISSING"
print(f"  subflow Handle-Existing-Account={hr}")
if hr != "REQUIRED":
    ok = False
det = prov("idp-detect-existing-broker-user")
if det and hea:
    di = det.get("index", 999); hi = hea.get("index", -1)
    print(f"  detect.index={di} handle.index={hi}")
    if not (di < hi):
        ok = False
else:
    ok = False
print("PASS" if ok else "FAIL")
' 2>/dev/null || echo "FAIL: flow verify error")
echo "$FLOW_VERIFY"
echo "$FLOW_VERIFY" | tail -1 | grep -q "^PASS$" \
  || { echo "ERROR: link-only flow verify FAILED — flow yapısı hatalı" >&2; exit 3; }

# User-profile entra_tid/entra_oid deklarasyon read-back (Codex 019e3796 /
# smoke bulgusu — KC 26 declarative profile deklare edilmemiş attribute düşürür).
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
  || { echo "ERROR: user-profile verify FAILED — entra_tid/entra_oid deklare değil" >&2; exit 3; }

echo ""
echo "=== M365 broker apply — PASS (realm=$REALM) ==="
echo "Next: browser smoke — RB-m365-sso-broker.md Adım 5 (test) / Adım 6 (prod)"
exit 0
