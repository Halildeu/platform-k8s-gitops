#!/usr/bin/env bash
#
# Faz 35 ES-2 — why can this person not open Etik Speak? (#970)
#
# Authorizing one real handler takes six steps across three systems. Miss one and the only
# symptom is a 403 that names nothing: the entitlement check collapses every failure into
# the same denial. platform-backend#1001 made the service log which link is missing; this
# script answers the same question from the outside, before anyone has to read pod logs.
#
# READ-ONLY BY DESIGN. It writes nothing, anywhere. A script that grants ethics-manager
# authority over whistleblowing cases is a different object with a different review bar, and
# conflating "tell me what is missing" with "go fix it" is how a diagnostic becomes the thing
# that silently authorizes the wrong person.
#
# The numeric id is resolved from users_db and ONLY users_db. permission_db carries a table
# of the same name whose ids mean different people — that collision is what handed a real
# account eighteen roles nobody granted it (#971). Looking there is the bug, not a fallback.
#
# Usage:
#   scripts/faz35/diagnose-ethic-entitlement.sh <email>
#
# Exit: 0 every link present · 1 at least one missing · 2 could not determine
set -uo pipefail

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
  echo "kullanim: $0 <email>" >&2
  exit 2
fi

PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
KUBE_CTX="${KUBE_CTX:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
PERMISSION_ROLE="${PERMISSION_ROLE:-ETIK_SPEAK_MANAGER}"
ETHICS_ORG="${ETHICS_ORG:-00000000-0000-0000-0000-000000000001}"

missing=0
undetermined=0

# `ok`/`gap` differ in more than colour: a gap is a provisioning step somebody skipped and is
# fixable from the remediation line; `undetermined` means this script could not see, which is
# not the same as absent and must never be reported as one.
ok()   { printf '  \033[32m✓\033[0m %-34s %s\n' "$1" "${2:-}"; }
gap()  { printf '  \033[31m✗\033[0m %-34s %s\n' "$1" "${2:-}"; missing=$((missing + 1)); }
huh()  { printf '  \033[33m?\033[0m %-34s %s\n' "$1" "${2:-}"; undetermined=$((undetermined + 1)); }
note() { printf '      %s\n' "$1"; }

psql_q() { docker exec "$PG_CONTAINER" psql -U postgres -d "$1" -t -A -c "$2" 2>/dev/null; }

printf '\nEtik Speak yetki zinciri — %s\n\n' "$EMAIL"

# ── 1. Canonical identity ────────────────────────────────────────────────────────────────
# Everything downstream is keyed on this number, so a wrong answer here makes every later
# check meaningless rather than merely wrong.
USER_ID=$(psql_q users_db "select id from users where lower(email)=lower('$EMAIL')")
if [ -z "$USER_ID" ]; then
  gap "kanonik kimlik (users_db)" "kayit yok"
  note "Bu kisi urun dizininde yok; sonraki adimlarin dayanacagi bir id de yok."
  printf '\nSonuc: zincir baslamadan kesiliyor.\n\n'
  exit 1
fi
ok "kanonik kimlik (users_db)" "id=$USER_ID"

# The collision that made this script necessary. Reported, never used.
SHADOW=$(psql_q permission_db "select email from users where id=$USER_ID")
if [ -n "$SHADOW" ] && [ "$(printf '%s' "$SHADOW" | tr 'A-Z' 'a-z')" != "$(printf '%s' "$EMAIL" | tr 'A-Z' 'a-z')" ]; then
  huh "kimlik uzayi cakismasi" "permission_db.users[$USER_ID] = $SHADOW"
  note "Ayni sayi orada baska birine ait. Bu id ile rol veren her arac yanlis kisiye verir (#971)."
fi

# ── 2. Permission role assignment ────────────────────────────────────────────────────────
ASSIGNED=$(psql_q permission_db "
  select count(*) from user_role_assignments a join roles r on r.id=a.role_id
  where a.user_id=$USER_ID and r.name='$PERMISSION_ROLE' and a.active")
if [ "${ASSIGNED:-0}" -ge 1 ]; then
  ok "$PERMISSION_ROLE rolu" "atanmis"
else
  gap "$PERMISSION_ROLE rolu" "atama yok"
  note "Servis bunu ROLE_MISSING olarak loglar."
fi

# ── 3. Keycloak subject + org alignment ──────────────────────────────────────────────────
KC_SUB=$(psql_q keycloak "select id from user_entity where lower(email)=lower('$EMAIL')")
if [ -z "$KC_SUB" ]; then
  gap "Keycloak hesabi" "yok"
else
  ok "Keycloak hesabi" "sub=${KC_SUB:0:8}…"
  KC_ORG=$(psql_q keycloak "
    select ua.value from user_attribute ua where ua.user_id='$KC_SUB' and ua.name='org_id'")
  if [ -z "$KC_ORG" ]; then
    gap "org_id ozniteligi" "yok"
  elif [ "$KC_ORG" != "$ETHICS_ORG" ]; then
    gap "org_id ozniteligi" "$KC_ORG"
    note "Etik urununun org'u $ETHICS_ORG; bu kisi baska bir org'un vakalarini gorur."
  else
    ok "org_id ozniteligi" "$KC_ORG"
  fi
  # Absent is fine. permission-service resolves the numeric id from the email
  # (`/api/users/by-email/`), not from this attribute — `ethics-manager-test` carries no
  # `userId` and works. Present-but-wrong is a different matter: it is the shape that
  # produces IDENTITY_MISMATCH, so only that is reported as a gap.
  #
  # The first draft of this script called "absent" a gap. Running it against a persona known
  # to work is what caught it; shipping it would have sent the next person chasing a
  # non-problem, which is the exact failure this tool exists to end.
  KC_UID=$(psql_q keycloak "
    select ua.value from user_attribute ua where ua.user_id='$KC_SUB' and ua.name='userId'")
  if [ -z "$KC_UID" ]; then
    ok "userId ozniteligi" "yok (gerekli degil — kimlik e-postadan cozuluyor)"
  elif [ "$KC_UID" != "$USER_ID" ]; then
    gap "userId ozniteligi" "$KC_UID (kanonik: $USER_ID)"
    note "Servis bunu IDENTITY_MISMATCH olarak reddeder; ya duzeltilmeli ya kaldirilmali."
  else
    ok "userId ozniteligi" "$KC_UID"
  fi
fi

# ── 4-5. OpenFGA relations ───────────────────────────────────────────────────────────────
# Reported rather than probed: the store/model ids are deployment inputs this script does not
# own, and guessing them would produce a confident wrong answer. Naming the exact tuples is
# what the operator needs; asserting they are absent without looking would not be true.
printf '\n  OpenFGA baglari (bu betik yazmaz ve store kimliklerini varsaymaz):\n'
note "permission store : user:$USER_ID  can_manage  module:ETHIC"
if [ -n "${KC_SUB:-}" ]; then
  note "ethics store     : user:$KC_SUB  handler  ethics_product:$ETHICS_ORG"
  note "ethics store     : user:$KC_SUB  triager  ethics_product:$ETHICS_ORG"
fi
note "kontrol: scripts/faz35/verify-test-openfga-authz.sh <store-id> <model-id>"

# ── Sonuç ────────────────────────────────────────────────────────────────────────────────
printf '\n'
if [ "$missing" -eq 0 ] && [ "$undetermined" -eq 0 ]; then
  printf 'Sonuc: gorulen tum halkalar yerinde. Hala 403 aliniyorsa OpenFGA baglarini kontrol edin.\n\n'
  exit 0
fi
if [ "$missing" -eq 0 ]; then
  printf 'Sonuc: eksik halka yok, ancak %d nokta belirlenemedi.\n\n' "$undetermined"
  exit 2
fi
printf 'Sonuc: %d eksik halka. Yukarida adlariyla isaretli.\n\n' "$missing"
exit 1
