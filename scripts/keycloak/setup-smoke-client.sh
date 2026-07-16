#!/usr/bin/env bash
#
# setup-smoke-client.sh — Faz 22 Sec A2: confidential `smoke-client` (board #2476).
#
# Codex (OpenAI) thread 019f69f6 REVISE-absorbed. Amaç: TEST smoke/runbook'ların
# `client_id=frontend` (public + ROPC) yerine kullanacağı **dedicated confidential
# ROPC client**'ı idempotent desired-state ile kur. Böylece A2c'de public
# `frontend` client'ında `directAccessGrantsEnabled=false` yapılabilir.
#
# handoff-smoke-client-keycloak.md (2026-04-19) spec'ini gerçekleştirir; hedefi
# platform-ssot'tu → ssot DEPRECATED olunca hiç oluşturulmadı. `serviceAccountsEnabled`
# handoff'ta true'ydu → Codex REVISE ile FALSE (client_credentials kullanılmıyor;
# gereksiz ikinci grant yüzeyi).
#
# ── Desired-state (Codex confidential spec) ──
#   publicClient=false · clientAuthenticatorType=client-secret
#   standardFlowEnabled=false · implicitFlowEnabled=false
#   directAccessGrantsEnabled=true (ROPC — smoke user password grant)
#   serviceAccountsEnabled=false · fullScopeAllowed=false
#   redirectUris=[] · webOrigins=[]
#
# ── Secret (Codex): Vault EVET, ESO HAYIR (K8s consumer yok) ──
#   Client secret KC'de üretilir → Vault kv/platform/keycloak/smoke-client.
#   Normal --apply secret'ı SESSİZCE ROTATE ETMEZ: Vault↔KC uyuşmazsa fail-closed;
#   rotation yalnız explicit --rotate-secret ile.
#
# ── Modes ──
#   --check           read-only: client var mı + shape converged mi + secret parity.
#                     exit 0 = converged, 2 = drift.
#   --apply           client create/converge (shape) + secret ilk seed / parity-check.
#   --rotate-secret   KC secret regenerate → Vault put (explicit; idempotent değil).
#
# ── Realm → container ──
#   platform-test → platform-kc-test  + vault platform-vault-test  (agent-otonom)
#   serban        → platform-kc-prod  + vault platform-vault-prod  (CONFIRM_PROD_SMOKE_CLIENT=serban)
#
# ── Exit codes ──
#   0 OK · 1 ERROR (input/login/guard/vault) · 2 DRIFT(--check) · 3 POSTCONDITION
#
# HARD RULE (tam nitelikli — Codex 019f6b1d P2): client secret ve Vault token
# stdout/log'a YAZILMAZ ve **argv'ye konmaz** (setup-m365-broker.sh pattern'i:
# container-içi unique temp umask 077 + `sh -s` stdin script). İSTİSNA: Keycloak
# admin password, `kcadm config credentials --password` sınırlaması nedeniyle kısa
# süre process argv'de bulunur (A1 script'iyle aynı) → `set -x`, process-dump ve
# komut-satırı gözlemi YASAK. Idempotent. Operator login-cred'e dokunmaz.
# Realm YARATMAZ. Vault hedefi realm'e HARD-BIND (env override yok).
#
set -euo pipefail
umask 077

MODE="${1:---check}"
REALM="${REALM:-platform-test}"
CLIENT_ID="smoke-client"

# ── realm → (KC, Vault, init-file, path) HARD-BIND ─────────────────────────
# Codex 019f6b1d must-fix 1: bunlar env ile override EDİLEMEZ. Aksi hâlde
#   REALM=platform-test VAULT_CONTAINER=platform-vault-prod ... --apply
# çağrısı KC'yi TEST'te mutate ederken secret'ı PROD Vault'a yazar ve prod
# intent-gate (yalnız REALM=serban dalında) HİÇ aranmaz. Multi-session ortamda
# dışarıda kalmış bir VAULT_CONTAINER env'i bunu kazara tetikleyebilir.
VAULT_PATH="kv/platform/keycloak/smoke-client"
case "$REALM" in
  platform-test)
    KC_CONTAINER="platform-kc-test"; ENV="test"
    VAULT_CONTAINER="platform-vault-test"
    VAULT_INIT_FILE="$HOME/bootstrap-drill/vault-init-test.json" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; ENV="prod"; REALM="serban"
    VAULT_CONTAINER="platform-vault-prod"
    VAULT_INIT_FILE="$HOME/bootstrap-drill/vault-init-prod.json"
    if [ "${CONFIRM_PROD_SMOKE_CLIENT:-}" != "serban" ]; then
      echo "ERROR: prod realm için CONFIRM_PROD_SMOKE_CLIENT=serban gerekli (intent-gate;" >&2
      echo "       gerçek owner onayı dış workflow/board kaydında)" >&2
      exit 1
    fi ;;
  *) echo "ERROR: bilinmeyen realm '$REALM'" >&2; exit 1 ;;
esac

# Kaza-guard (Codex P3 doğruluk): realm targets HARD ASSIGNMENT ile sabittir → legacy
# target env değerleri (VAULT_CONTAINER vb.) etkisizdir (üzerine yazılır). Desteklenmeyen
# explicit `*_OVERRIDE` denemeleri ise ayrıca fail-closed reddedilir.
for _v in VAULT_CONTAINER VAULT_INIT_FILE VAULT_PATH KC_CONTAINER; do
  eval "_env_val=\${${_v}_OVERRIDE:-}"
  [ -z "${_env_val:-}" ] || {
    echo "ERROR: ${_v}_OVERRIDE desteklenmiyor — realm→target eşlemesi hard-bind'dir" >&2
    exit 1
  }
done

# Resolved target'ı yazdır (hiçbiri secret değil) — operatör yanlış hedefi erken görür.
echo "  resolved: realm=$REALM kc=$KC_CONTAINER vault=$VAULT_CONTAINER path=$VAULT_PATH"

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"

# ─── confidential desired-state (Codex spec) ───────────────────────────────
CLIENT_DESIRED_JSON=$(cat <<'JSON'
{
  "clientId": "smoke-client",
  "name": "Smoke/runbook confidential ROPC client (Faz 22 Sec A2)",
  "description": "TEST smoke ROPC — frontend public client ROPC yerine. board #2476.",
  "protocol": "openid-connect",
  "publicClient": false,
  "clientAuthenticatorType": "client-secret",
  "standardFlowEnabled": false,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": true,
  "serviceAccountsEnabled": false,
  "fullScopeAllowed": false,
  "redirectUris": [],
  "webOrigins": [],
  "enabled": true
}
JSON
)

# ─── KC login ──────────────────────────────────────────────────────────────
login() {
  local pass
  pass=$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null | tr -d '\n')
  [ -n "$pass" ] || { echo "ERROR: KC admin password boş çözüldü" >&2; exit 1; }
  $KC config credentials --server http://localhost:8080 --realm master \
    --user admin --password "$pass" >/dev/null 2>&1 \
    || { echo "ERROR: master realm login başarısız" >&2; exit 1; }
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

client_uuid() {
  $KC get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id 2>/dev/null \
    | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d[0]["id"] if d else "")
except Exception: print("")' 2>/dev/null || echo ""
}

# ─── Vault helper — token/secret ARGV'ye girmez (stdin script) ─────────────
vault_token() {
  local rt
  [ -f "$VAULT_INIT_FILE" ] || { echo "ERROR: vault init dosyası yok: $VAULT_INIT_FILE" >&2; return 1; }
  rt=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("root_token",""))' "$VAULT_INIT_FILE" 2>/dev/null || echo "")
  [ -n "$rt" ] || { echo "ERROR: vault root_token okunamadı" >&2; return 1; }
  printf '%s' "$rt"
}

# vault_get_secret — Vault'taki client_secret (yoksa boş). Değer STDOUT'a döner;
# çağıran onu ekrana BASMAZ (yalnız karşılaştırma için).
vault_get_secret() {
  local rt out; rt="$(vault_token)" || return 1
  out=$({ printf 'export VAULT_TOKEN=%q\n' "$rt"
          printf 'vault kv get -field=client_secret %q 2>/dev/null\n' "$VAULT_PATH"
        } | docker exec -i -e VAULT_ADDR=http://localhost:8200 "$VAULT_CONTAINER" sh -s 2>/dev/null || true)
  printf '%s' "$out"
}

# vault_put_secret <secret> — setup-m365 pattern: container-içi temp (umask 077)
# JSON + `vault kv put @file`; secret argv'de görünmez.
# Codex 019f6b1d must-fix 3: temp dosya UNIQUE (container-side mktemp) — sabit ad
# multi-session'da iki koşumun secret'ını karıştırabilirdi (A'nın secret'ı B'nin
# path'ine yazılabilir). P2: JSON escaping python ile (secret'ta " veya \ olursa
# naive printf JSON'u bozardı).
vault_put_secret() {
  local secret="$1" rt tmp; rt="$(vault_token)" || return 1
  tmp="$(docker exec "$VAULT_CONTAINER" sh -c 'umask 077; mktemp /tmp/.smoke-secret.XXXXXX.json' 2>/dev/null)" \
    || { echo "ERROR: container temp oluşturulamadı" >&2; return 1; }
  [ -n "$tmp" ] || { echo "ERROR: container temp adı boş" >&2; return 1; }
  # cleanup her yolda (success + failure)
  _cleanup_tmp() { docker exec "$VAULT_CONTAINER" rm -f "$tmp" > /dev/null 2>&1 || true; }

  SMOKE_SECRET="$secret" python3 -c 'import json,os,sys; sys.stdout.write(json.dumps({"client_secret": os.environ["SMOKE_SECRET"]}))' \
    | docker exec -i "$VAULT_CONTAINER" sh -c "umask 077; cat > '$tmp'" \
    || { echo "ERROR: secret container'a yazılamadı" >&2; _cleanup_tmp; return 1; }

  # Codex 019f6b1d: `set -euo pipefail` altında pipeline fail ederse `local rc=$?`
  # satırına HİÇ ULAŞILMAZ (errexit function'ı sonlandırır) → cleanup atlanır ve
  # secret-bearing temp container'da KALIR. `if` condition'daki komut errexit
  # tetiklemez → cleanup garanti. (`if ! pipeline` KULLANMA: `!` status'u ters
  # çevirir, blok içindeki $? gerçek failure code'u olmaz.)
  local rc
  if { printf 'export VAULT_TOKEN=%q\n' "$rt"
       printf 'vault kv put %q @%q >/dev/null\n' "$VAULT_PATH" "$tmp"
     } | docker exec -i -e VAULT_ADDR=http://localhost:8200 "$VAULT_CONTAINER" sh -s > /dev/null 2>&1; then
    rc=0
  else
    rc=$?
  fi
  _cleanup_tmp
  unset -f _cleanup_tmp
  [ "$rc" -eq 0 ] || { echo "ERROR: vault kv put başarısız ($VAULT_PATH)" >&2; return 1; }
}

kc_client_secret() {  # $1 = uuid
  $KC get "clients/$1/client-secret" -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("value",""))
except Exception: print("")' 2>/dev/null || echo ""
}

# shape drift raporu (desired vs current) — DRIFT_COUNT set eder
shape_drift() {  # $1 = client json
  local rep
  rep=$(printf '%s' "$1" | CLIENT_DESIRED_JSON="$CLIENT_DESIRED_JSON" python3 -c '
import json, os, sys
cur = json.load(sys.stdin)
des = json.loads(os.environ["CLIENT_DESIRED_JSON"])
keys = ["publicClient","clientAuthenticatorType","standardFlowEnabled",
        "implicitFlowEnabled","directAccessGrantsEnabled","serviceAccountsEnabled",
        "fullScopeAllowed","enabled"]
drift = 0
for k in keys:
    c = cur.get(k); d = des[k]
    m = (c == d)
    print(f"  {k}: current={json.dumps(c)} desired={json.dumps(d)} " + ("MATCH" if m else "DRIFT"))
    if not m: drift += 1
for k in ("redirectUris","webOrigins"):
    c = cur.get(k) or []
    m = (len(c) == 0)
    print(f"  {k}: current={json.dumps(c)} desired=[] " + ("MATCH" if m else "DRIFT"))
    if not m: drift += 1
print(f"DRIFT_COUNT={drift}")
') || { echo "ERROR: shape diff hata" >&2; exit 1; }
  echo "$rep" | grep -v '^DRIFT_COUNT='
  DRIFT_COUNT="$(echo "$rep" | sed -n 's/^DRIFT_COUNT=//p')"
}

# desired → kcadm -f için JSON dosyası (container-içi, umask 077)
write_desired_to_container() {  # $1 = container path, $2 = uuid (varsa id eklenir)
  local path="$1" uuid="${2:-}"
  printf '%s' "$CLIENT_DESIRED_JSON" \
    | CLIENT_UUID="$uuid" python3 -c '
import json, os, sys
d = json.load(sys.stdin)
u = os.environ.get("CLIENT_UUID", "")
if u:
    d["id"] = u          # update path PUT body id ister (setup-m365 dersi)
json.dump(d, sys.stdout)
' | docker exec -i "$KC_CONTAINER" sh -c "umask 077; cat > '$path'"
}

echo "=== setup-smoke-client $MODE (realm=$REALM, client=$CLIENT_ID, vault=$VAULT_CONTAINER) ==="
login; guard_realm
UUID="$(client_uuid)"

case "$MODE" in
  --check)
    if [ -z "$UUID" ]; then
      echo "  client '$CLIENT_ID' YOK (henüz oluşturulmadı)"
      echo "=== DRIFT: client absent (--apply ile oluştur) ==="; exit 2
    fi
    CUR="$($KC get "clients/$UUID" -r "$REALM" 2>/dev/null)"
    shape_drift "$CUR"
    # secret parity (read-only)
    kc_sec="$(kc_client_secret "$UUID")"
    vault_sec="$(vault_get_secret || echo "")"
    if [ -z "$vault_sec" ]; then
      echo "  secret: Vault'ta YOK ($VAULT_PATH) → DRIFT"
      DRIFT_COUNT=$(( ${DRIFT_COUNT:-0} + 1 ))
    elif [ "$kc_sec" = "$vault_sec" ]; then
      echo "  secret: Vault ↔ KC PARITY ✓ (değer basılmaz)"
    else
      echo "  secret: Vault ↔ KC UYUŞMUYOR → --rotate-secret gerekir (fail-closed)"
      DRIFT_COUNT=$(( ${DRIFT_COUNT:-0} + 1 ))
    fi
    echo ""
    [ "${DRIFT_COUNT:-1}" = "0" ] && { echo "=== CONVERGED ==="; exit 0; } \
      || { echo "=== DRIFT: ${DRIFT_COUNT} alan ==="; exit 2; }
    ;;

  --apply)
    CTR_JSON="/tmp/.smoke-client-$$.json"
    trap 'docker exec "$KC_CONTAINER" rm -f "$CTR_JSON" >/dev/null 2>&1 || true' EXIT

    if [ -z "$UUID" ]; then
      write_desired_to_container "$CTR_JSON" ""
      $KC create clients -r "$REALM" -f "$CTR_JSON" >/dev/null 2>&1 \
        || { echo "ERROR: client create başarısız" >&2; exit 1; }
      UUID="$(client_uuid)"
      [ -n "$UUID" ] || { echo "ERROR: create sonrası uuid çözülemedi" >&2; exit 1; }
      echo "✓ client '$CLIENT_ID' oluşturuldu (uuid=$UUID)"
    else
      write_desired_to_container "$CTR_JSON" "$UUID"
      $KC update "clients/$UUID" -r "$REALM" -f "$CTR_JSON" >/dev/null 2>&1 \
        || { echo "ERROR: client update başarısız" >&2; exit 1; }
      echo "✓ client '$CLIENT_ID' converge edildi (uuid=$UUID)"
    fi

    # ── secret: ilk seed veya parity (SESSİZ ROTATE YOK — Codex) ───────────
    kc_sec="$(kc_client_secret "$UUID")"
    [ -n "$kc_sec" ] || { echo "ERROR: KC client-secret okunamadı" >&2; exit 1; }
    vault_sec="$(vault_get_secret || echo "")"
    if [ -z "$vault_sec" ]; then
      vault_put_secret "$kc_sec" || exit 1
      echo "✓ secret Vault'a ilk kez seed edildi ($VAULT_PATH, değer basılmaz)"
    elif [ "$vault_sec" = "$kc_sec" ]; then
      echo "✓ secret Vault ↔ KC parity (dokunulmadı — idempotent)"
    else
      echo "ERROR: Vault secret ↔ KC secret UYUŞMUYOR ($VAULT_PATH)." >&2
      echo "       Normal --apply secret'ı sessizce rotate ETMEZ (fail-closed)." >&2
      echo "       Bilinçli rotation için: --rotate-secret" >&2
      exit 1
    fi
    unset kc_sec vault_sec

    # ── postcondition: read-back shape + parity ───────────────────────────
    echo "--- postcondition (read-back) ---"
    CUR="$($KC get "clients/$UUID" -r "$REALM" 2>/dev/null)"
    shape_drift "$CUR"
    kc_sec2="$(kc_client_secret "$UUID")"
    vault_sec2="$(vault_get_secret || echo "")"
    if [ -n "$vault_sec2" ] && [ "$kc_sec2" = "$vault_sec2" ]; then
      echo "  secret: Vault ↔ KC PARITY ✓"
    else
      echo "  secret: PARITY FAIL" ; DRIFT_COUNT=$(( ${DRIFT_COUNT:-0} + 1 ))
    fi
    unset kc_sec2 vault_sec2
    echo ""
    if [ "${DRIFT_COUNT:-1}" = "0" ]; then
      echo "=== APPLY PASS — smoke-client converged + secret Vault'ta ==="
      echo "Kullanım: RB-automation/smoke runbook'ları SMOKE_CLIENT_ID=smoke-client +"
      echo "          SMOKE_CLIENT_SECRET=<vault kv get -field=client_secret $VAULT_PATH>"
      exit 0
    fi
    echo "ERROR: POSTCONDITION FAILED — ${DRIFT_COUNT} alan drift" >&2
    exit 3
    ;;

  --rotate-secret)
    [ -n "$UUID" ] || { echo "ERROR: client '$CLIENT_ID' yok — önce --apply" >&2; exit 1; }
    echo "⚠️  Explicit rotation: KC secret regenerate → Vault put"
    $KC create "clients/$UUID/client-secret" -r "$REALM" >/dev/null 2>&1 \
      || { echo "ERROR: secret regenerate başarısız" >&2; exit 1; }
    new_sec="$(kc_client_secret "$UUID")"
    [ -n "$new_sec" ] || { echo "ERROR: yeni secret okunamadı" >&2; exit 1; }
    vault_put_secret "$new_sec" || exit 1
    vault_sec="$(vault_get_secret || echo "")"
    if [ "$vault_sec" = "$new_sec" ]; then
      echo "✓ ROTATE PASS — KC ↔ Vault parity (değer basılmaz)"
      unset new_sec vault_sec; exit 0
    fi
    unset new_sec vault_sec
    echo "ERROR: rotation sonrası parity FAIL" >&2; exit 3
    ;;

  *)
    echo "ERROR: bilinmeyen mode '$MODE' (--check|--apply|--rotate-secret)" >&2; exit 1 ;;
esac
