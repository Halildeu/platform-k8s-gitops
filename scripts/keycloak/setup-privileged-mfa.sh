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
#   2. `requires-mfa` COMPOSITE OLARAK HİÇBİR role eklenmez. Adı geçen insanlara
#      (`DIRECT_MFA_USERS`) DOĞRUDAN atanır; otomasyon personaları hiç almaz.
#      `--check` ayrıcalıklı rol taşıyıp listede olmayan insan-görünümlü kimlikleri
#      raporlar, ama otomatik EKLEMEZ.
#   3. `browser` flow → `browser-privileged-mfa` kopyası (default `browser` KORUNUR →
#      anında rollback: browserFlow=browser).
#   4. Kopyanın `forms` subflow'una `privileged-force-otp` (CONDITIONAL) subflow:
#        Condition - user role (config condUserRole=requires-mfa, negate=false) REQUIRED
#        OTP Form REQUIRED   ← OTP'si yoksa CONFIGURE_TOTP required-action tetikler
#   4b. (gitops#3212) `sms-otp` provider JAR'ı deploy edilmişse aynı CONDITIONAL
#       subflow içinde, condition ile KARDEŞ olarak:
#         OTP Form ALTERNATIVE (varsayılan, daha güçlü)
#         SMS OTP  ALTERNATIVE ("Try another way" ile opt-in; config yalnız
#                               iki URL — auth-token-url + notify-intent-url)
#       DÜZ şekil zorunlu: ALTERNATIVE'leri iç içe REQUIRED bir alt-subflow'a
#       koymak ölçüldü (2026-07-31) ve authenticator'a hiç ulaşmadı; KC'nin
#       kendi "Browser - Conditional 2FA" subflow'u da düzdür.
#       Provider yoksa blok no-op (prod bugün): OTP Form REQUIRED kalır.
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

# ── Privileged roles: DISCOVERY ONLY, never composite parents ──
# These are the roles that define privilege. The marker is NOT composited into them.
# Measured 2026-07-27 on platform-test -- their 34 holders are:
#     4 humans, 4 ambiguous automation identities, 26 synthetic personas.
# 30 of 34 are automation. A script cannot complete a TOTP enrollment, so compositing the
# marker into these roles would force TOTP on every ENDPOINT_ADMIN smoke persona, every
# AG-0xx acceptance persona and every remote-bridge operator identity the moment the flow
# is bound. Composite delivery also flipped `ethics-manager.composite` to true and broke
# four checks in the Faz 35 chain, and it hid blast radius: `roles/requires-mfa/users`
# returns only DIRECT assignments, so it read 0 while 34 users effectively held the role.
PRIVILEGED_ROLES="ENDPOINT_ADMIN MEETING_ADMIN TRANSCRIPT_ADMIN ethics-manager remote-bridge-approver remote-bridge-operator"
# The marker goes to named humans, explicitly. Not a heuristic: a rule that guesses who
# needs a second factor is the wrong thing to put in a security script. `--check` reports
# any privileged-role holder missing from this list, so a new human admin cannot silently
# escape MFA -- the list is authoritative but its drift is visible.
DIRECT_MFA_USERS="${DIRECT_MFA_USERS:-admin@example.com etik-staff@acik.com halil.kocoglu@serban.com.tr zeynep.akkilic@serban.com.tr}"
# Identities that must NEVER receive the marker, whatever roles they hold. Automation.
AUTOMATION_MARKERS="${AUTOMATION_MARKERS:-persona -test smoke canary ag0 c5persona rb- codex -lock- recorder .invalid @test. @synthetic. localtest.me test.local}"
MFA_ROLE="requires-mfa"
NEW_FLOW="browser-privileged-mfa"
SUB_ALIAS="privileged-force-otp"
# ── gitops#3212 SMS lane ──
# When the keycloak-sms-otp-authenticator providers JAR is deployed, the
# second factor becomes a FLAT pair of ALTERNATIVEs beside the condition:
#   privileged-force-otp (CONDITIONAL)
#     ├─ Condition - user role (REQUIRED)
#     ├─ OTP Form (ALTERNATIVE)   ← default, stronger
#     └─ SMS OTP  (ALTERNATIVE)   ← opt-in via "Try another way"
# METHODS_ALIAS below is kept ONLY to detect and remove the earlier nested
# shape, which never reached the authenticator (measured 2026-07-31).
# Capability-gated: everything below keys off the sms-otp provider being
# REGISTERED in this KC instance. Without the JAR (prod today) the legacy
# direct-OTP shape stays converged and the script remains inert for SMS —
# no half-built flow can strand a login.
METHODS_ALIAS="privileged-2fa-methods"
SMS_PROVIDER_ID="sms-otp"
SMS_DISPLAY="SMS OTP (notify pipeline)"
SMS_CONFIG_ALIAS="sms-otp-notify-lane"
# Deployment-specific SPI config (only the two URLs — every other knob has a
# contract default inside the SPI). Test defaults point at the NodePort lane
# (activation/keycloak-sms-otp); any other realm must provide both via env
# or the SMS wiring is skipped with a warning.
if [ "$REALM" = "platform-test" ]; then
  SMS_AUTH_TOKEN_URL="${SMS_AUTH_TOKEN_URL:-http://k3d-test-server-0:31088/oauth2/token}"
  SMS_NOTIFY_INTENT_URL="${SMS_NOTIFY_INTENT_URL:-http://k3d-test-server-0:31089/api/v1/internal/notify/intents}"
else
  SMS_AUTH_TOKEN_URL="${SMS_AUTH_TOKEN_URL:-}"
  SMS_NOTIFY_INTENT_URL="${SMS_NOTIFY_INTENT_URL:-}"
fi
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
is_automation() {
  local u="$1" m
  for m in $AUTOMATION_MARKERS; do
    case "$u" in *"$m"*) return 0 ;; esac
  done
  return 1
}
user_has_direct_mfa() {
  local uid
  uid=$(q "$API/users?username=$1&exact=true" | jq -r '.[0].id // empty')
  [ -n "$uid" ] || return 1
  q "$API/users/$uid/role-mappings/realm" | jq -e --arg m "$MFA_ROLE" '.[]?|select(.name==$m)' >/dev/null 2>&1
}
composite_has_mfa() { q "$API/roles/$1/composites" | jq -e --arg m "$MFA_ROLE" '.[]?|select(.name==$m)' >/dev/null 2>&1; }
flow_exists() { q "$API/authentication/flows" | jq -e --arg f "$NEW_FLOW" '.[]?|select(.alias==$f)' >/dev/null 2>&1; }
# ── Parent-aware execution helpers (gitops#3212, measured 2026-07-31) ──
# The executions endpoint returns a FLAT, ORDERED list with a `level` field
# and no parent id. Selecting by displayName+level therefore also matches
# same-named executions in OTHER subflows — the stock
# "Browser - Conditional 2FA" subflow holds its own "OTP Form" at level 2,
# and editing that one instead of ours is exactly how earlier runs produced
# a flow that looked right and still died. These helpers slice the children
# of a named subflow: the rows after it, until the next row at its level or
# shallower.
sub_children() {  # $1 = subflow displayName
  # The slice must STOP at the first row back at the subflow's own level or
  # shallower. Merely filtering `.level > lvl` keeps scanning past the end of
  # the subflow and picks up the NEXT subflow's children too — measured
  # 2026-07-31: it returned the stock "Browser - Conditional 2FA" children
  # (Condition - user configured, WebAuthn ...) alongside ours, so every
  # id resolved from it could belong to the wrong subflow.
  q "$API/authentication/flows/$NEW_FLOW/executions" | jq -c --arg s "$1" '
    . as $all
    | (([range(0; length)] | map(select($all[.].displayName == $s)))[0]) as $i
    | if $i == null then [] else
        $all[$i].level as $lvl
        | ($all[($i+1):]) as $rest
        | (([range(0; ($rest|length))] | map(select($rest[.].level <= $lvl)))[0]) as $stop
        | if $stop == null then $rest else $rest[0:$stop] end
      end'
}
child_id()  { sub_children "$1" | jq -r --arg d "$2" '[.[]|select(.displayName==$d)][0].id // empty'; }
child_pos() { sub_children "$1" | jq -r --arg d "$2" '[.[]|.displayName] | index($d) // -1'; }

# Drive an execution to the FIRST position among its siblings. Keycloak
# appends new executions with a priority that does not reliably land after
# existing ones, so desired order must be enforced, not assumed.
raise_to_front() {  # $1 = subflow displayName, $2 = child displayName
  local id pos i
  id=$(child_id "$1" "$2"); [ -n "$id" ] || return 0
  for i in 1 2 3 4 5 6 7 8; do
    pos=$(child_pos "$1" "$2")
    [ "$pos" = "0" ] && return 0
    [ "$pos" = "-1" ] && return 1
    q -X POST "$API/authentication/executions/$id/raise-priority" >/dev/null
  done
  return 1
}

sms_provider_available() {
  q "$API/authentication/authenticator-providers" \
    | jq -e --arg p "$SMS_PROVIDER_ID" '.[]?|select(.id==$p)' >/dev/null 2>&1
}
sms_urls_provided() { [ -n "$SMS_AUTH_TOKEN_URL" ] && [ -n "$SMS_NOTIFY_INTENT_URL" ]; }
subflow_ready() {
  # Parent-aware, order-aware. Two accepted shapes under privileged-force-otp
  # (CONDITIONAL), both FLAT — condition and the factors are SIBLINGS, like
  # Keycloak's own "Browser - Conditional 2FA":
  #   legacy (no sms provider): Condition REQUIRED, OTP Form REQUIRED
  #   target (sms provider):    Condition REQUIRED, OTP Form ALTERNATIVE,
  #                             SMS OTP ALTERNATIVE (+ its URL config)
  # Enforced beyond membership: the condition must be the FIRST child (a
  # condition evaluated after a factor is meaningless), and at the forms
  # level Username Password Form must precede the conditional subflow (with
  # no user yet, the role condition cannot evaluate and the whole login dies
  # with AuthenticationFlowException).
  local ex kids
  ex=$(q "$API/authentication/flows/$NEW_FLOW/executions")
  echo "$ex" | jq -e --arg s "$SUB_ALIAS" '[.[]|select(.displayName==$s and .requirement=="CONDITIONAL")]|length==1' >/dev/null 2>&1 || return 1
  # forms-level order: Username Password Form before the conditional subflow
  echo "$ex" | jq -e --arg s "$SUB_ALIAS" '
    ([.[]|select(.displayName=="Username Password Form" and .level==1)][0].index) as $u
    | ([.[]|select(.displayName==$s and .level==1)][0].index) as $c
    | ($u != null and $c != null and $u < $c)' >/dev/null 2>&1 || return 1
  # a nested methods subflow is drift in BOTH shapes
  echo "$ex" | jq -e --arg m "$METHODS_ALIAS" '[.[]|select(.displayName==$m)]|length==0' >/dev/null 2>&1 || return 1

  kids=$(sub_children "$SUB_ALIAS")
  # Membership + requirement are enforced; ORDER among these siblings is not
  # (KC's priority swap is a no-op for them and conditional executions are
  # evaluated first anyway). The forms-level order above IS enforced, because
  # there a factor placed before Username Password Form genuinely kills the
  # login: the role condition cannot evaluate without a user.
  echo "$kids" | jq -e '[.[]|select(.displayName=="Condition - user role" and .requirement=="REQUIRED")]|length==1' >/dev/null 2>&1 || return 1

  if sms_provider_available && sms_urls_provided; then
    echo "$kids" | jq -e '[.[]|select(.displayName=="OTP Form" and .requirement=="ALTERNATIVE")]|length==1' >/dev/null 2>&1 \
      && echo "$kids" | jq -e --arg s "$SMS_DISPLAY" '[.[]|select(.displayName==$s and .requirement=="ALTERNATIVE")]|length==1' >/dev/null 2>&1 \
      && { local sid cid cfg
           sid=$(child_id "$SUB_ALIAS" "$SMS_DISPLAY")
           cid=$(q "$API/authentication/executions/$sid" | jq -r '.authenticatorConfig // empty')
           [ -n "$cid" ] || return 1
           cfg=$(q "$API/authentication/config/$cid")
           [ "$(echo "$cfg" | jq -r '.config["auth-token-url"] // empty')" = "$SMS_AUTH_TOKEN_URL" ] \
             && [ "$(echo "$cfg" | jq -r '.config["notify-intent-url"] // empty')" = "$SMS_NOTIFY_INTENT_URL" ]; }
  else
    echo "$kids" | jq -e '[.[]|select(.displayName=="OTP Form" and .requirement=="REQUIRED")]|length==1' >/dev/null 2>&1 \
      && echo "$kids" | jq -e --arg s "$SMS_DISPLAY" '[.[]|select(.displayName==$s)]|length==0' >/dev/null 2>&1
  fi
}

report() {  # DRIFT counter
  local d=0
  role_exists "$MFA_ROLE" && echo "  role $MFA_ROLE: OK" || { echo "  role $MFA_ROLE: MISSING"; d=$((d+1)); }
  for r in $PRIVILEGED_ROLES; do
    if role_exists "$r"; then
      # Inverted on purpose: the marker being present as a composite child IS the drift.
      if composite_has_mfa "$r"; then
        echo "  composite $r→$MFA_ROLE: PRESENT (drift — must be removed, see header)"; d=$((d+1))
      else
        echo "  composite $r→$MFA_ROLE: absent OK"
      fi
    else echo "  role $r: absent (skip)"; fi
  done
  flow_exists && echo "  flow $NEW_FLOW: OK" || { echo "  flow $NEW_FLOW: MISSING"; d=$((d+1)); }
  if sms_provider_available; then
    if sms_urls_provided; then echo "  sms lane: provider kayıtlı + URL'ler set (hedef: OTP|SMS alternatif çifti)"
    else echo "  sms lane: provider kayıtlı ama SMS_AUTH_TOKEN_URL/SMS_NOTIFY_INTENT_URL boş — wiring atlanır (bu realm için env ver)"; fi
  else
    echo "  sms lane: sms-otp provider yok (providers JAR deploy edilmemiş) — legacy inline-OTP şekli geçerli"
  fi
  if flow_exists; then
    subflow_ready && echo "  subflow $SUB_ALIAS (CONDITIONAL+role+2FA şekli): OK" || { echo "  subflow $SUB_ALIAS: INCOMPLETE"; d=$((d+1)); }
  fi
  local bf; bf=$(q "$API" | jq -r '.browserFlow')
  echo "  realm browserFlow: $bf $([ "$bf" = "$NEW_FLOW" ] && echo '(ACTIVE)' || echo '(inert — --activate ile owner flip)')"
  for u in $DIRECT_MFA_USERS; do
    if user_has_direct_mfa "$u"; then echo "  direct $u→$MFA_ROLE: OK"
    else echo "  direct $u→$MFA_ROLE: MISSING"; d=$((d+1)); fi
  done
  # Visibility, not enforcement: a human holding a privileged role but absent from
  # DIRECT_MFA_USERS would silently escape MFA. Reported, not auto-added -- deciding that
  # someone is a person is not a call this script should make on its own.
  local uncovered; uncovered=""
  for r in $PRIVILEGED_ROLES; do
    role_exists "$r" || continue
    while IFS= read -r holder; do
      [ -n "$holder" ] || continue
      is_automation "$holder" && continue
      case " $DIRECT_MFA_USERS " in *" $holder "*) continue ;; esac
      case " $uncovered " in *" $holder "*) continue ;; esac
      uncovered="$uncovered $holder"
    done <<EOF
$(q "$API/roles/$r/users" | jq -r '.[]?.username // empty')
EOF
  done
  # Suppression must be auditable too: a marker that accidentally matches a person would
  # hide them from the warning above. Print what was treated as automation and why.
  local suppressed=""
  for r in $PRIVILEGED_ROLES; do
    role_exists "$r" || continue
    while IFS= read -r holder; do
      [ -n "$holder" ] || continue
      is_automation "$holder" || continue
      case " $suppressed " in *" $holder "*) continue ;; esac
      suppressed="$suppressed $holder"
    done <<EOF
$(q "$API/roles/$r/users" | jq -r '.[]?.username // empty')
EOF
  done
  if [ -n "$suppressed" ]; then
    local n; n=$(printf '%s\n' $suppressed | wc -l | tr -d ' ')
    echo "  otomasyon sayılıp MFA dışı bırakılan: $n kimlik"
    for h in $suppressed; do
      for m in $AUTOMATION_MARKERS; do
        case "$h" in *"$m"*) echo "    - $h  (marker: $m)"; break ;; esac
      done
    done
  fi
  if [ -n "$uncovered" ]; then
    echo "  UYARI: ayrıcalıklı rol taşıyan ve otomasyon görünmeyen, DIRECT_MFA_USERS'ta OLMAYAN kimlikler:"
    for h in $uncovered; do echo "    - $h"; done
    echo "    (insan ise DIRECT_MFA_USERS'a ekle; otomasyon ise AUTOMATION_MARKERS'a bir işaret ekle)"
  fi
  DRIFT="$d"
}

apply_all() {
  # 1) requires-mfa rol
  role_exists "$MFA_ROLE" || q -X POST "$API/roles" -H "$CT" \
    -d "{\"name\":\"$MFA_ROLE\",\"description\":\"Marker: privileged roles composite this to force browser OTP (Faz 22 Sec B)\"}" >/dev/null
  # 2) composite: never written. Remove the marker wherever a previous run put it.
  local rid rn
  rid=$(q "$API/roles/$MFA_ROLE" | jq -r '.id'); rn=$(q "$API/roles/$MFA_ROLE" | jq -r '.name')
  for r in $PRIVILEGED_ROLES; do
    role_exists "$r" || continue
    composite_has_mfa "$r" || continue
    q -X DELETE "$API/roles/$r/composites" -H "$CT" -d "[{\"id\":\"$rid\",\"name\":\"$rn\"}]" >/dev/null
    echo "  reconcile: $MFA_ROLE, $r composite'inden cikarildi"
  done
  # 2b) direct assignment to named humans -- automation identities are refused outright,
  # so a marker in DIRECT_MFA_USERS cannot accidentally arm a persona.
  for u in $DIRECT_MFA_USERS; do
    if is_automation "$u"; then
      echo "ERROR: $u otomasyon isareti tasiyor; DIRECT_MFA_USERS'a konulamaz" >&2; exit 1
    fi
    local uid; uid=$(q "$API/users?username=$u&exact=true" | jq -r '.[0].id // empty')
    [ -n "$uid" ] || { echo "  uyarı: kullanıcı $u yok, atlandı"; continue; }
    user_has_direct_mfa "$u" && continue
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
  # 4b) gitops#3212 — SMS lane, capability-gated, FLAT, and PARENT-AWARE.
  # Every lookup below goes through sub_children so it can only ever touch
  # executions inside privileged-force-otp; selecting by displayName+level
  # would also match the stock "Browser - Conditional 2FA" siblings.
  local mid
  mid=$(q "$API/authentication/flows/$NEW_FLOW/executions" \
        | jq -r --arg m "$METHODS_ALIAS" '[.[]|select(.displayName==$m)][0].id // empty')
  if [ -n "$mid" ]; then
    q -X DELETE "$API/authentication/executions/$mid" >/dev/null
    echo "  sms lane: nested $METHODS_ALIAS subflow kaldırıldı (düz şekle geçiş)"
  fi

  # OTP Form is required in BOTH shapes; the nested migration above may have
  # taken it with the subflow, so ensure it exists inside OUR subflow.
  [ -n "$(child_id "$SUB_ALIAS" "OTP Form")" ] || \
    { q -X POST "$API/authentication/flows/${SUB_ALIAS}/executions/execution" -H "$CT" -d '{"provider":"auth-otp-form"}' >/dev/null
      echo "  mfa: OTP Form eklendi"; }

  if sms_provider_available && sms_urls_provided; then
    [ -n "$(child_id "$SUB_ALIAS" "$SMS_DISPLAY")" ] || \
      { q -X POST "$API/authentication/flows/${SUB_ALIAS}/executions/execution" -H "$CT" -d "{\"provider\":\"$SMS_PROVIDER_ID\"}" >/dev/null
        echo "  sms lane: SMS OTP alternatifi eklendi"; }
  elif sms_provider_available; then
    echo "  UYARI: sms-otp provider kayıtlı ama SMS URL'leri boş — SMS lane wiring atlandı"
  else
    local sid_stale
    sid_stale=$(child_id "$SUB_ALIAS" "$SMS_DISPLAY")
    [ -z "$sid_stale" ] || { q -X DELETE "$API/authentication/executions/$sid_stale" >/dev/null
                             echo "  sms lane: provider yok — artık SMS execution kaldırıldı"; }
  fi

  # requirement + ORDER + config (idempotent — her apply'da set)
  local SUB ROLE OTP SMS2
  SUB=$(q "$API/authentication/flows/$NEW_FLOW/executions" | jq -r --arg s "$SUB_ALIAS" '[.[]|select(.displayName==$s)][0].id')
  ROLE=$(child_id "$SUB_ALIAS" "Condition - user role")
  OTP=$(child_id "$SUB_ALIAS" "OTP Form")
  [ -n "$ROLE" ] && [ -n "$OTP" ] || { echo "ERROR: privileged-force-otp içinde condition/OTP yok — apply yarım kaldı" >&2; exit 3; }
  q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"$SUB\",\"requirement\":\"CONDITIONAL\"}" >/dev/null
  q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"$ROLE\",\"requirement\":\"REQUIRED\"}" >/dev/null

  if sms_provider_available && sms_urls_provided; then
    SMS2=$(child_id "$SUB_ALIAS" "$SMS_DISPLAY")
    [ -n "$SMS2" ] || { echo "ERROR: SMS execution bulunamadı" >&2; exit 3; }
    q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"$OTP\",\"requirement\":\"ALTERNATIVE\"}" >/dev/null
    q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"$SMS2\",\"requirement\":\"ALTERNATIVE\"}" >/dev/null
    local SMSCID SMSCFG
    SMSCID=$(q "$API/authentication/executions/$SMS2" | jq -r '.authenticatorConfig // empty')
    if [ -z "$SMSCID" ]; then
      q -X POST "$API/authentication/executions/$SMS2/config" -H "$CT" \
        -d "{\"alias\":\"$SMS_CONFIG_ALIAS\",\"config\":{\"auth-token-url\":\"$SMS_AUTH_TOKEN_URL\",\"notify-intent-url\":\"$SMS_NOTIFY_INTENT_URL\"}}" >/dev/null
    else
      SMSCFG=$(q "$API/authentication/config/$SMSCID")
      if [ "$(echo "$SMSCFG" | jq -r '.config["auth-token-url"] // empty')" != "$SMS_AUTH_TOKEN_URL" ] \
         || [ "$(echo "$SMSCFG" | jq -r '.config["notify-intent-url"] // empty')" != "$SMS_NOTIFY_INTENT_URL" ]; then
        q -X PUT "$API/authentication/config/$SMSCID" -H "$CT" \
          -d "{\"id\":\"$SMSCID\",\"alias\":\"$SMS_CONFIG_ALIAS\",\"config\":{\"auth-token-url\":\"$SMS_AUTH_TOKEN_URL\",\"notify-intent-url\":\"$SMS_NOTIFY_INTENT_URL\"}}" >/dev/null
        echo "  sms lane: SPI config URL'leri desired değerlere converge edildi"
      fi
    fi
  else
    q -X PUT "$API/authentication/flows/$NEW_FLOW/executions" -H "$CT" -d "{\"id\":\"$OTP\",\"requirement\":\"REQUIRED\"}" >/dev/null
  fi

  # ORDER, enforced not assumed (measured: KC appends with a priority that
  # can land BEFORE existing siblings).
  # Best-effort only: measured 2026-07-31 on KC 26.5.5, raise-priority and
  # lower-priority are BOTH no-ops for these three siblings (they share a
  # priority value, so the swap changes nothing). Keycloak evaluates the
  # conditional executions of a CONDITIONAL subflow before its factors
  # regardless of listed order, so this is cosmetic — it must not fail the
  # apply.
  raise_to_front "$SUB_ALIAS" "Condition - user role" || \
    echo "  not: condition ilk sırada değil (KC priority takası bu kardeşlerde etkisiz; conditional değerlendirme sıradan bağımsız)"
  local i upf_idx sub_idx upf_id
  upf_id=$(q "$API/authentication/flows/$NEW_FLOW/executions" | jq -r '[.[]|select(.displayName=="Username Password Form" and .level==1)][0].id // empty')
  for i in 1 2 3 4 5 6 7 8; do
    upf_idx=$(q "$API/authentication/flows/$NEW_FLOW/executions" | jq -r '[.[]|select(.displayName=="Username Password Form" and .level==1)][0].index // empty')
    sub_idx=$(q "$API/authentication/flows/$NEW_FLOW/executions" | jq -r --arg s "$SUB_ALIAS" '[.[]|select(.displayName==$s and .level==1)][0].index // empty')
    [ -n "$upf_idx" ] && [ -n "$sub_idx" ] || break
    [ "$upf_idx" -lt "$sub_idx" ] && break
    q -X POST "$API/authentication/executions/$upf_id/raise-priority" >/dev/null
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
