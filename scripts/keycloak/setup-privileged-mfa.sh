#!/usr/bin/env bash
#
# setup-privileged-mfa.sh — Faz 22 Sec B (board #2476): privileged roller için
# browser login'de zorunlu OTP (conditional MFA).
#
# Codex thread 019f69f6 slice sırası ...→A3→B. Idempotent desired-state,
# drift-detect, fail-closed. **realm-bind (aktivasyon) owner-gated** — kullanıcı
# login davranışını değiştirir (privileged hesaplar OTP kurmaya zorlanır), o yüzden
# ayrı `--activate` + CONFIRM gerekir (A2c pattern'i: agent hazırlar, owner flip).
#
# ── Neden host-curl (kcadm değil) ──
#   Kopyalanan browser flow'un subflow alias'ları boşluk içerir ("browser-
#   privileged-mfa forms"); kcadm URL path'te boşluğu ENCODE ETMEZ ("Illegal
#   character in path") → subflow'a execution eklenemez. curl + %20 ile aşılır.
#   Token kcadm config'ten alınır (kcadm login zaten çalışır); host curl 8082/8081.
#
# ── Why `ethics-manager` is NOT a composite target (2026-07-27) ──
#   Compositing `requires-mfa` into `ethics-manager` set that role's `.composite` to true.
#   Faz 35 pins the opposite: `provision-test-keycloak.sh` asserts
#   `.composite == false` for it (lines 184 and 344) and then asserts exact effective-role
#   and token-role allowlists that do not contain `requires-mfa`. Measured 2026-07-27:
#   four checks failed across two scripts, and `provision-test-openfga.sh` failed its
#   exact-set token pin for the same reason. The ETHICS provisioning chain was broken by
#   this script.
#
#   The deeper reason is granularity, not just a contract clash. `ethics-manager` is held
#   by 3 humans AND 4 synthetic automation personas (`*.invalid` emails). A script cannot
#   complete a TOTP enrollment, so a role shared by automation is the wrong place to hang
#   an interactive second-factor requirement. Humans get the marker directly; personas do
#   not get it at all.
#
#   Composite delivery also hides blast radius: `roles/requires-mfa/users` returns only
#   DIRECT assignments, so it read 0 while 34 users effectively held the role. Direct
#   assignment makes the same query truthful.
#
# ── Desired-state (B) ──
#   1. realm rolü `requires-mfa` (marker).
#   2. Privileged roller (ENDPOINT_ADMIN MEETING_ADMIN TRANSCRIPT_ADMIN
#      remote-bridge-approver remote-bridge-operator) → `requires-mfa` COMPOSITE child.
#      `ethics-manager` HARIÇ (yukarıdaki nota bak) → insan sahipleri `DIRECT_MFA_USERS`
#      ile DOĞRUDAN atama alır; sentetik personalar hiç almaz.
#   3. `browser` flow → `browser-privileged-mfa` kopyası (default `browser` KORUNUR →
#      anında rollback: browserFlow=browser).
#   4. Kopyanın `forms` subflow'una `privileged-force-otp` (CONDITIONAL) subflow:
#        Condition - user role (config condUserRole=requires-mfa, negate=false) REQUIRED
#        OTP Form REQUIRED   ← OTP'si yoksa CONFIGURE_TOTP required-action tetikler
#   5. (--activate) realm browserFlow → browser-privileged-mfa.
#
# ── Modes ──
#   --check       read-only: rol+composite+flow+subflow converged mi. exit 0/2.
#   --apply       1-4'ü idempotent kur (realm-bind HARİÇ; flow inert kalır).
#   --activate    realm browserFlow → browser-privileged-mfa (CONFIRM_MFA_ACTIVATE
#                 =<realm> zorunlu; login davranışı değişir — owner-gated).
#   --deactivate  realm browserFlow → browser (rollback; her zaman güvenli).
#
# ── Realm → KC (host port) HARD-BIND ──
#   platform-test → platform-kc-test (127.0.0.1:8082)   agent-otonom
#   serban        → platform-kc-prod (127.0.0.1:8081)   CONFIRM_PROD_MFA=serban
#
# ── Exit codes ── 0 OK · 1 ERROR · 2 DRIFT(--check) · 3 POSTCONDITION
#
# HARD RULE: admin password kcadm `config credentials --password` sırasında kısa
# süre argv'de (A1/A2a/A3 ile aynı); `set -x`/process-dump YASAK. Admin bearer
# token host bash değişkeninde (curl -H argv'de kısa süre, host-local test).
# Idempotent. Realm YARATMAZ. Kullanıcı login-cred'ine dokunmaz.
#
set -euo pipefail
umask 077

MODE="${1:---check}"
REALM="${REALM:-platform-test}"

case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; KC_PORT="8082" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; KC_PORT="8081"; REALM="serban"
    if [ "${CONFIRM_PROD_MFA:-}" != "serban" ]; then
      echo "ERROR: prod realm için CONFIRM_PROD_MFA=serban gerekli (intent-gate)" >&2; exit 1
    fi ;;
  *) echo "ERROR: bilinmeyen realm '$REALM'" >&2; exit 1 ;;
esac

# `ethics-manager` DELIBERATELY not here -- see the header note. Compositing into it
# made it composite=true, which broke four separate checks in the Faz 35 ETHICS chain,
# and its holders include synthetic automation personas that cannot complete a TOTP flow.
PRIV_ROLES="ENDPOINT_ADMIN MEETING_ADMIN TRANSCRIPT_ADMIN remote-bridge-approver remote-bridge-operator"
# Roles whose SHAPE is pinned by another subsystem. Compositing into one of these changes
# `.composite` from false to true and breaks that subsystem's contract, so it is refused
# rather than warned about. Grep for `composite == false` to find new entries.
SHAPE_PINNED_ROLES="ethics-manager"
# Human holders of a shape-pinned privileged role get the marker DIRECTLY, so MFA intent
# survives without mutating the role. Automation personas are deliberately excluded.
DIRECT_MFA_USERS="${DIRECT_MFA_USERS:-admin@example.com etik-staff@acik.com halil.kocoglu@serban.com.tr}"
MFA_ROLE="requires-mfa"
NEW_FLOW="browser-privileged-mfa"
SUB_ALIAS="privileged-force-otp"
API="http://127.0.0.1:${KC_PORT}/admin/realms/${REALM}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' host'ta yok" >&2; exit 1; }; }
need curl; need jq

# Admin token — kcadm login (argv-safe password: container-içi cat) → config token
get_token() {
  sudo docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master \
    --user "$(sudo docker exec "$KC_CONTAINER" sh -lc 'printf %s "$KEYCLOAK_ADMIN"')" \
    --password "$(sudo docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"')" \
    >/dev/null 2>&1 || { echo "ERROR: kcadm master login" >&2; exit 1; }
  local t
  t=$(sudo docker exec "$KC_CONTAINER" sh -lc 'cat ~/.keycloak/kcadm.config 2>/dev/null || cat /opt/keycloak/.keycloak/kcadm.config 2>/dev/null' \
      | jq -r '.endpoints[]|.[].token // empty' | head -1)
  [ -n "$t" ] || { echo "ERROR: token çözülemedi" >&2; exit 1; }
  printf '%s' "$t"
}

TOKEN=""; AUTH=""; CT="Content-Type: application/json"
auth_init() { TOKEN="$(get_token)"; AUTH="Authorization: Bearer $TOKEN"; }
q() { curl -s -H "$AUTH" "$@"; }  # authenticated curl

guard_realm() {
  local got; got=$(q "$API" | jq -r '.realm // empty')
  [ "$got" = "$REALM" ] || { echo "ERROR: realm guard fail ('$got'≠'$REALM')" >&2; exit 1; }
}

role_exists() { q "$API/roles/$1" | jq -e '.name?' >/dev/null 2>&1; }
composite_has_mfa() { q "$API/roles/$1/composites" | jq -e --arg m "$MFA_ROLE" '.[]?|select(.name==$m)' >/dev/null 2>&1; }
flow_exists() { q "$API/authentication/flows" | jq -e --arg f "$NEW_FLOW" '.[]?|select(.alias==$f)' >/dev/null 2>&1; }
subflow_ready() {
  # privileged-force-otp CONDITIONAL + Condition-user-role REQUIRED + OTP Form REQUIRED
  local ex; ex=$(q "$API/authentication/flows/$NEW_FLOW/executions")
  echo "$ex" | jq -e '[.[]|select(.displayName=="privileged-force-otp" and .requirement=="CONDITIONAL")]|length==1' >/dev/null 2>&1 \
    && echo "$ex" | jq -e '[.[]|select(.displayName=="Condition - user role" and .level==2 and .requirement=="REQUIRED")]|length>=1' >/dev/null 2>&1 \
    && echo "$ex" | jq -e '[.[]|select(.displayName=="OTP Form" and .level==2 and .requirement=="REQUIRED")]|length>=1' >/dev/null 2>&1
}

report() {  # DRIFT counter
  local d=0
  role_exists "$MFA_ROLE" && echo "  role $MFA_ROLE: OK" || { echo "  role $MFA_ROLE: MISSING"; d=$((d+1)); }
  for r in $PRIV_ROLES; do
    if role_exists "$r"; then
      composite_has_mfa "$r" && echo "  composite $r→$MFA_ROLE: OK" || { echo "  composite $r→$MFA_ROLE: MISSING"; d=$((d+1)); }
    else echo "  role $r: absent (skip)"; fi
  done
  flow_exists && echo "  flow $NEW_FLOW: OK" || { echo "  flow $NEW_FLOW: MISSING"; d=$((d+1)); }
  if flow_exists; then
    subflow_ready && echo "  subflow $SUB_ALIAS (CONDITIONAL+role+OTP): OK" || { echo "  subflow $SUB_ALIAS: INCOMPLETE"; d=$((d+1)); }
  fi
  local bf; bf=$(q "$API" | jq -r '.browserFlow')
  echo "  realm browserFlow: $bf $([ "$bf" = "$NEW_FLOW" ] && echo '(ACTIVE)' || echo '(inert — --activate ile owner flip)')"
  DRIFT="$d"
}

apply_all() {
  # 1) requires-mfa rol
  role_exists "$MFA_ROLE" || q -X POST "$API/roles" -H "$CT" \
    -d "{\"name\":\"$MFA_ROLE\",\"description\":\"Marker: privileged roles composite this to force browser OTP (Faz 22 Sec B)\"}" >/dev/null
  # 2) composite -- only into roles whose shape nobody else pins
  local rid rn
  rid=$(q "$API/roles/$MFA_ROLE" | jq -r '.id'); rn=$(q "$API/roles/$MFA_ROLE" | jq -r '.name')
  for r in $PRIV_ROLES; do
    for pinned in $SHAPE_PINNED_ROLES; do
      [ "$r" = "$pinned" ] && { echo "ERROR: $r sekil-pinli bir rol; composite YAZILMAZ" >&2; exit 1; }
    done
    role_exists "$r" || { echo "  uyarı: rol $r yok, composite atlandı"; continue; }
    composite_has_mfa "$r" && continue
    q -X POST "$API/roles/$r/composites" -H "$CT" -d "[{\"id\":\"$rid\",\"name\":\"$rn\"}]" >/dev/null
  done
  # 2b) reconcile: remove the marker from shape-pinned roles it should never have entered
  for r in $SHAPE_PINNED_ROLES; do
    role_exists "$r" || continue
    composite_has_mfa "$r" || continue
    q -X DELETE "$API/roles/$r/composites" -H "$CT" -d "[{\"id\":\"$rid\",\"name\":\"$rn\"}]" >/dev/null
    echo "  reconcile: $MFA_ROLE, $r composite'inden cikarildi (sekil sozlesmesi geri geldi)"
    echo "  SONRAKI ADIM: provision-test-openfga.sh rol pini artik [\"ethics-manager\"] olmali"
  done
  # 2c) shape-pinned roles carry MFA intent through DIRECT user assignment instead
  for u in $DIRECT_MFA_USERS; do
    q "$API/users?username=$u&exact=true" | jq -e '.[0].id' >/dev/null 2>&1 || {
      echo "  uyarı: kullanıcı $u yok, doğrudan atama atlandı"; continue; }
    local uid; uid=$(q "$API/users?username=$u&exact=true" | jq -r '.[0].id')
    q "$API/users/$uid/role-mappings/realm" | jq -e --arg m "$MFA_ROLE" '.[]?|select(.name==$m)' >/dev/null 2>&1 && continue
    q -X POST "$API/users/$uid/role-mappings/realm" -H "$CT" -d "[{\"id\":\"$rid\",\"name\":\"$rn\"}]" >/dev/null
    echo "  $MFA_ROLE -> $u (dogrudan)"
  done
  # 3) flow copy
  flow_exists || q -X POST "$API/authentication/flows/browser/copy" -H "$CT" -d "{\"newName\":\"$NEW_FLOW\"}" >/dev/null
  # 4) subflow + authenticators (idempotent)
  if ! q "$API/authentication/flows/$NEW_FLOW/executions" | jq -e --arg s "$SUB_ALIAS" '.[]?|select(.displayName==$s)' >/dev/null 2>&1; then
    q -X POST "$API/authentication/flows/${NEW_FLOW}%20forms/executions/flow" -H "$CT" -d "{\"alias\":\"$SUB_ALIAS\",\"type\":\"basic-flow\"}" >/dev/null
    q -X POST "$API/authentication/flows/${SUB_ALIAS}/executions/execution" -H "$CT" -d '{"provider":"conditional-user-role"}' >/dev/null
    q -X POST "$API/authentication/flows/${SUB_ALIAS}/executions/execution" -H "$CT" -d '{"provider":"auth-otp-form"}' >/dev/null
  fi
  # requirement + config (idempotent — her apply'da set)
  local J SUB ROLE OTP
  J=$(q "$API/authentication/flows/$NEW_FLOW/executions")
  SUB=$(echo "$J" | jq -r --arg s "$SUB_ALIAS" '.[]|select(.displayName==$s).id')
  ROLE=$(echo "$J" | jq -r '.[]|select(.displayName=="Condition - user role" and .level==2).id')
  OTP=$(echo "$J" | jq -r '[.[]|select(.displayName=="OTP Form" and .level==2)][-1].id')
  for pair in "$SUB:CONDITIONAL" "$ROLE:REQUIRED" "$OTP:REQUIRED"; do
    q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"${pair%%:*}\",\"requirement\":\"${pair##*:}\"}" >/dev/null
  done
  q "$API/authentication/executions/$ROLE" | jq -e '.authenticatorConfig' >/dev/null 2>&1 || \
    q -X POST "$API/authentication/executions/$ROLE/config" -H "$CT" \
      -d "{\"alias\":\"privileged-role-requires-mfa\",\"config\":{\"condUserRole\":\"$MFA_ROLE\",\"negate\":\"false\"}}" >/dev/null
}

echo "=== setup-privileged-mfa $MODE (realm=$REALM, kc=$KC_CONTAINER:$KC_PORT) ==="
auth_init; guard_realm

case "$MODE" in
  --check)
    report
    [ "${DRIFT:-1}" -eq 0 ] && { echo "=== CONVERGED (flow hazır; aktivasyon ayrı --activate) ==="; exit 0; }
    echo "=== DRIFT ($DRIFT) — --apply ==="; exit 2 ;;
  --apply)
    apply_all
    report
    [ "${DRIFT:-1}" -eq 0 ] || { echo "ERROR: postcondition drift=$DRIFT" >&2; exit 3; }
    echo "=== APPLIED (flow inert; login değişmedi — owner --activate ile bind) ==="; exit 0 ;;
  --activate)
    [ "${CONFIRM_MFA_ACTIVATE:-}" = "$REALM" ] || { echo "ERROR: --activate için CONFIRM_MFA_ACTIVATE=$REALM gerekli (login davranışı değişir — owner-gated)" >&2; exit 1; }
    flow_exists && subflow_ready || { echo "ERROR: flow hazır değil, önce --apply" >&2; exit 1; }
    q -X PUT "$API" -H "$CT" -d "{\"browserFlow\":\"$NEW_FLOW\"}" >/dev/null
    bf=$(q "$API" | jq -r '.browserFlow')
    [ "$bf" = "$NEW_FLOW" ] && { echo "=== ACTIVATED: realm browserFlow=$NEW_FLOW (privileged OTP zorunlu) ==="; exit 0; } || { echo "ERROR: aktivasyon doğrulanamadı" >&2; exit 3; }
    ;;
  --deactivate)
    q -X PUT "$API" -H "$CT" -d '{"browserFlow":"browser"}' >/dev/null
    echo "=== DEACTIVATED: realm browserFlow=browser (rollback) ==="; exit 0 ;;
  *) echo "ERROR: mode '$MODE' (--check|--apply|--activate|--deactivate)" >&2; exit 1 ;;
esac
