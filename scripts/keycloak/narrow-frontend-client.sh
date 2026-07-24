#!/usr/bin/env bash
#
# narrow-frontend-client.sh — Faz 22 Sec A3 (board #2476): frontend public client
# redirectUri + webOrigins narrowing.
#
# Codex thread 019f69f6 slice sırası A1→A2a→A2b→A2c→A3→B. Bu script A3'ü
# client-level, idempotent desired-state, drift-detect ve fail-closed ile converge
# eder — `harden-realm-security.sh` (realm-level) DEĞİL; client lifecycle/rollback
# semantiği realm'den farklı (runbook + setup-smoke-client.sh dersleri).
#
# ── Sorun (canlı kcadm, 2026-07-23) ──
#   frontend.webOrigins   = ["+", "https://testai.acik.com", "http://localhost:3000"]
#     → "+" = "tüm redirectUri origin'lerini CORS'a ekle" — açık CORS yüzeyi.
#   frontend.redirectUris = ["https://testai.acik.com/*", "http://localhost:3000/*"]
#     → dev localhost prod public client'ında; "localhost prod'a sızabilir" (#2476).
#
# ── Desired-state (A3) ──
#   frontend (mutate, field-level -s; diğer alanlara DOKUNMA — A2c/standardFlow ayrı):
#     webOrigins   = ["https://testai.acik.com"]          # "+" ve localhost çıkar
#     redirectUris = ["https://testai.acik.com/*"]        # localhost çıkar; "/*" SPA
#                    # keycloak-js window.location redirect → route-based; "/*" SPA
#                    # gereği origin-locked korunur (sabit-callback SPA'yı kırar).
#   frontend-local (create; dev-only convenience, localhost'u prod client'tan ayır):
#     publicClient=true standardFlowEnabled=true directAccessGrantsEnabled=false
#     implicitFlowEnabled=false serviceAccountsEnabled=false
#     redirectUris=["http://localhost:3000/*"] webOrigins=["http://localhost:3000"]
#     # Dev'de `VITE_KEYCLOAK_CLIENT_ID=frontend-local` (platform-web dev .env);
#     # prod build etkilenmez (VITE_KEYCLOAK_CLIENT_ID=frontend sabit).
#
# ── Modes ──
#   --check   read-only: frontend narrowing converged mi + frontend-local var mı.
#             exit 0 = converged, 2 = drift.
#   --apply   frontend field-level narrow (-s) + frontend-local create/converge.
#
# ── Realm → container HARD-BIND ──
#   platform-test → platform-kc-test  (agent-otonom, pre-prod)
#   serban        → platform-kc-prod  (CONFIRM_PROD_NARROW=serban intent-gate)
#
# ── Exit codes ── 0 OK · 1 ERROR · 2 DRIFT(--check) · 3 POSTCONDITION
#
# HARD RULE: KC admin password `kcadm config credentials --password` sınırlaması
# nedeniyle kısa süre process argv'de bulunur (A1/A2a script'leriyle aynı) →
# `set -x`, process-dump YASAK. Idempotent. Realm YARATMAZ. Operator login-cred'e
# dokunmaz. frontend client'ı SİLMEZ; yalnız iki alanı (-s) daraltır.
#
set -euo pipefail
umask 077

MODE="${1:---check}"
REALM="${REALM:-platform-test}"

case "$REALM" in
  platform-test)
    KC_CONTAINER="platform-kc-test" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; REALM="serban"
    if [ "${CONFIRM_PROD_NARROW:-}" != "serban" ]; then
      echo "ERROR: prod realm için CONFIRM_PROD_NARROW=serban gerekli (intent-gate;" >&2
      echo "       gerçek owner onayı dış workflow/board kaydında)" >&2
      exit 1
    fi ;;
  *) echo "ERROR: bilinmeyen realm '$REALM'" >&2; exit 1 ;;
esac

# Kaza-guard: realm→target HARD; *_OVERRIDE fail-closed (setup-smoke-client dersi)
# shellcheck disable=SC2043  # tek var; setup-smoke-client pattern (gelecek-genişletilebilir)
for _v in KC_CONTAINER; do
  eval "_env_val=\${${_v}_OVERRIDE:-}"
  [ -z "${_env_val:-}" ] || {
    echo "ERROR: ${_v}_OVERRIDE desteklenmiyor — realm→target hard-bind" >&2; exit 1; }
done

FRONTEND_ORIGIN="https://testai.acik.com"
DEV_ORIGIN="http://localhost:3000"

# Desired (A3) — frontend narrow + frontend-local dev
FE_WEBORIGINS_JSON="[\"$FRONTEND_ORIGIN\"]"
FE_REDIRECTS_JSON="[\"$FRONTEND_ORIGIN/*\"]"

FRONTEND_LOCAL_JSON=$(cat <<JSON
{
  "clientId": "frontend-local",
  "name": "Frontend dev-local (Faz 22 Sec A3)",
  "description": "Dev localhost:3000 client — prod frontend client'ından ayrı. board #2476.",
  "protocol": "openid-connect",
  "publicClient": true,
  "standardFlowEnabled": true,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": false,
  "fullScopeAllowed": false,
  "redirectUris": ["$DEV_ORIGIN/*"],
  "webOrigins": ["$DEV_ORIGIN"],
  "enabled": true
}
JSON
)

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"

login() {
  local pass
  pass=$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null | tr -d '\n')
  [ -n "$pass" ] || { echo "ERROR: KC admin password boş" >&2; exit 1; }
  $KC config credentials --server http://localhost:8080 --realm master \
    --user admin --password "$pass" >/dev/null 2>&1 \
    || { echo "ERROR: master login başarısız" >&2; exit 1; }
  unset pass
}

guard_realm() {
  local got
  got=$($KC get "realms/$REALM" --fields realm 2>/dev/null \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("realm",""))
except Exception: print("")' 2>/dev/null || echo "")
  [ "$got" = "$REALM" ] \
    || { echo "ERROR: realm guard fail ('$got'≠'$REALM') — script realm YARATMAZ" >&2; exit 1; }
}

client_uuid() {  # $1 = clientId
  $KC get clients -r "$REALM" -q "clientId=$1" --fields id 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d[0]["id"] if d else "")
except Exception: print("")' 2>/dev/null || echo ""
}

# frontend narrowing drift — DRIFT_FE set eder
frontend_drift() {  # $1 = frontend client json
  local rep
  rep=$(printf '%s' "$1" | python3 -c '
import json, sys
cur = json.load(sys.stdin)
des_wo = ["'"$FRONTEND_ORIGIN"'"]
des_ru = ["'"$FRONTEND_ORIGIN"'/*"]
drift = 0
for k, d in (("webOrigins", des_wo), ("redirectUris", des_ru)):
    c = sorted(cur.get(k) or [])
    m = (c == sorted(d))
    print(f"  frontend.{k}: current={json.dumps(cur.get(k) or [])} desired={json.dumps(d)} " + ("MATCH" if m else "DRIFT"))
    if not m: drift += 1
print(f"DRIFT_FE={drift}")
') || { echo "ERROR: frontend diff hata" >&2; exit 1; }
  echo "$rep" | grep -v '^DRIFT_FE='
  DRIFT_FE="$(echo "$rep" | sed -n 's/^DRIFT_FE=//p')"
}

write_json_to_container() {  # $1 = container path, stdin = json
  docker exec -i "$KC_CONTAINER" sh -c "umask 077; cat > '$1'"
}

echo "=== narrow-frontend-client $MODE (realm=$REALM, kc=$KC_CONTAINER) ==="
echo "  resolved: frontend origin=$FRONTEND_ORIGIN, dev=$DEV_ORIGIN"
login; guard_realm

FE_UUID="$(client_uuid frontend)"
[ -n "$FE_UUID" ] || { echo "ERROR: 'frontend' client YOK — bu script frontend'i mutate eder, yaratmaz" >&2; exit 1; }
FL_UUID="$(client_uuid frontend-local)"

case "$MODE" in
  --check)
    CUR="$($KC get "clients/$FE_UUID" -r "$REALM" --fields webOrigins,redirectUris 2>/dev/null)"
    frontend_drift "$CUR"
    FL_STATE="present"; [ -n "$FL_UUID" ] || FL_STATE="ABSENT"
    echo "  frontend-local: $FL_STATE"
    TOTAL_DRIFT="${DRIFT_FE:-0}"
    [ -n "$FL_UUID" ] || TOTAL_DRIFT=$((TOTAL_DRIFT + 1))
    if [ "$TOTAL_DRIFT" -eq 0 ]; then
      echo "=== CONVERGED (A3 narrowing live) ==="; exit 0
    fi
    echo "=== DRIFT ($TOTAL_DRIFT) — --apply ile converge et ==="; exit 2 ;;

  --apply)
    echo "--- frontend narrow (field-level -s; diğer alanlar korunur) ---"
    $KC update "clients/$FE_UUID" -r "$REALM" \
      -s "webOrigins=$FE_WEBORIGINS_JSON" \
      -s "redirectUris=$FE_REDIRECTS_JSON" \
      || { echo "ERROR: frontend update başarısız" >&2; exit 1; }
    echo "  frontend.webOrigins → $FE_WEBORIGINS_JSON"
    echo "  frontend.redirectUris → $FE_REDIRECTS_JSON"

    echo "--- frontend-local dev client converge ---"
    if [ -z "$FL_UUID" ]; then
      printf '%s' "$FRONTEND_LOCAL_JSON" | write_json_to_container /tmp/.fe-local.json
      $KC create clients -r "$REALM" -f /tmp/.fe-local.json \
        || { docker exec "$KC_CONTAINER" rm -f /tmp/.fe-local.json 2>/dev/null || true
             echo "ERROR: frontend-local create başarısız" >&2; exit 1; }
      docker exec "$KC_CONTAINER" rm -f /tmp/.fe-local.json 2>/dev/null || true
      echo "  frontend-local CREATED"
    else
      $KC update "clients/$FL_UUID" -r "$REALM" \
        -s 'publicClient=true' -s 'standardFlowEnabled=true' \
        -s 'directAccessGrantsEnabled=false' -s 'implicitFlowEnabled=false' \
        -s 'serviceAccountsEnabled=false' \
        -s "redirectUris=[\"$DEV_ORIGIN/*\"]" -s "webOrigins=[\"$DEV_ORIGIN\"]" \
        || { echo "ERROR: frontend-local update başarısız" >&2; exit 1; }
      echo "  frontend-local CONVERGED"
    fi

    # Postcondition — re-read + drift 0 assert
    CUR="$($KC get "clients/$FE_UUID" -r "$REALM" --fields webOrigins,redirectUris 2>/dev/null)"
    frontend_drift "$CUR" >/dev/null
    FL_UUID="$(client_uuid frontend-local)"
    if [ "${DRIFT_FE:-1}" -ne 0 ] || [ -z "$FL_UUID" ]; then
      echo "ERROR: postcondition fail (drift_fe=${DRIFT_FE:-?} fl=${FL_UUID:-absent})" >&2; exit 3
    fi
    echo "=== APPLIED + verified (A3 narrowing converged) ==="; exit 0 ;;

  *) echo "ERROR: bilinmeyen mode '$MODE' (--check | --apply)" >&2; exit 1 ;;
esac
