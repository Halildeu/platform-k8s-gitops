#!/usr/bin/env bash
#
# setup-user-profile-phone-attribute.sh — gitops#3212 / #3211: declare
# `phoneNumber` as a MANAGED user-profile attribute.
#
# Why this exists (measured 2026-07-31, platform-test): Keycloak 26 ships a
# declarative User Profile, and this realm has `unmanagedAttributePolicy`
# unset — i.e. unmanaged attributes are DISABLED. Writing `phoneNumber`
# through the admin API therefore succeeded with 2xx and stored NOTHING
# (`attributes: null` on read-back). Downstream that surfaced as:
#   * the SMS-OTP authenticator reporting "not configured for this user"
#     (no phone), leaving the requires-mfa ALTERNATIVE group with no usable
#     method, which Keycloak reports as AuthenticationFlowException and the
#     login page renders as the misleading "Invalid username or password";
#   * the panel MFA section (gitops#3211) silently failing to save a phone.
# Declaring the attribute — rather than switching the realm to ENABLED for
# all unmanaged attributes — is the narrow fix: exactly one new attribute,
# with an E.164 validator matching the notify RecipientRef contract, and
# admin-only edit rights (a user must not be able to move their own second
# factor to a new number; that is the SIM-swap self-service hole).
#
# Idempotent: adds or converges the single attribute, leaves every other
# attribute in the profile untouched. TEST-scoped, prod owner-gated.
#
set -euo pipefail
umask 077

REALM="${REALM:-platform-test}"
case "$REALM" in
  platform-test) KC="platform-kc-test"; KC_PORT="8082" ;;
  *) echo "ERROR: bu script yalnız platform-test için (prod owner-gated)" >&2; exit 1 ;;
esac
ATTR="${PHONE_ATTRIBUTE:-phoneNumber}"
API="http://127.0.0.1:${KC_PORT}/admin/realms/${REALM}"
MODE="${1:---apply}"
case "$MODE" in
  --apply|--check) ;;
  *) echo "ERROR: bilinmeyen mod '$MODE' (--apply|--check)" >&2; exit 1 ;;
esac

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' yok" >&2; exit 1; }; }
need curl; need jq

# ── Credential-safe admin channel (Codex 019fb687 P1) ──────────────────
# Neither the admin password nor the bearer token may appear in host argv:
# a local process reading /proc/<pid>/cmdline would otherwise see them.
#   * the password is streamed straight out of the container's secret file
#     into curl's STDIN (`--data @-`) — it never lands in a shell variable
#     and never crosses an argv boundary (the KC image has no curl of its
#     own, so the request is made host-side over the loopback port);
#   * the bearer header lives in a mode-0600 curl config file consumed with
#     `--config`, so it never appears as a `-H` argument either.
HDR_FILE="$(mktemp)"; chmod 600 "$HDR_FILE"
cleanup_hdr() { rm -f -- "$HDR_FILE"; }
trap cleanup_hdr EXIT

ADMIN_USER=$(sudo docker exec "$KC" sh -lc 'printf %s "$KEYCLOAK_ADMIN"')
TOKEN=$( { printf 'grant_type=password&client_id=admin-cli&username=%s&password=' \
             "$(printf %s "$ADMIN_USER" | jq -sRr @uri)"
           sudo docker exec "$KC" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' \
             | tr -d '\n' | jq -sRr @uri
         } | curl -sS --data @- "http://127.0.0.1:${KC_PORT}/realms/master/protocol/openid-connect/token" \
           | jq -r '.access_token // empty')
[ -n "$TOKEN" ] || { echo "ERROR: admin token alınamadı" >&2; exit 1; }
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > "$HDR_FILE"
unset TOKEN
CT="Content-Type: application/json"
q() { curl -sS --fail-with-body --config "$HDR_FILE" "$@"; }

DESIRED=$(jq -n --arg n "$ATTR" '{
  name: $n,
  displayName: "Telefon (E.164)",
  multivalued: false,
  # view includes "user": the SMS authenticator reads the phone in the USER
  # context during login, and an admin-only VIEW makes getFirstAttribute
  # return nothing there — the factor then reports "not configured" and the
  # ALTERNATIVE group dies (measured 2026-07-31). EDIT stays admin-only:
  # that is the SIM-swap self-service hole, and it stays shut.
  permissions: { view: ["admin", "user"], edit: ["admin"] },
  validations: {
    pattern: {
      # jq string escape: "\\+" yields a single backslash + plus, i.e. the
      # regex \+ (escaped literal plus). Writing "\\\\+" here would store a
      # regex matching a literal BACKSLASH and reject every real number.
      pattern: "^\\+[1-9][0-9]{7,14}$",
      "error-message": "Telefon E.164 biçiminde olmalı (+ ve 8-15 rakam)"
    }
  },
  annotations: {}
  # `required` is deliberately absent: the attribute is optional, and
  # Keycloak omits the key entirely in its response — sending `required:
  # null` would make every exact comparison below report false drift.
}')

PROFILE=$(q "$API/users/profile")
CURRENT=$(echo "$PROFILE" | jq --arg n "$ATTR" '[.attributes[] | select(.name == $n)][0] // empty')

if [ -n "$CURRENT" ] && [ "$(echo "$CURRENT" | jq -S -c .)" = "$(echo "$DESIRED" | jq -S -c .)" ]; then
  echo "CONVERGED: $ATTR user-profile attribute zaten istenen şekilde"
  exit 0
fi

if [ "$MODE" = "--check" ]; then
  echo "DRIFT: $ATTR attribute eksik veya farklı — --apply gerekli"
  exit 2
fi

UPDATED=$(echo "$PROFILE" | jq --arg n "$ATTR" --argjson d "$DESIRED" \
  '.attributes = ([.attributes[] | select(.name != $n)] + [$d])')
printf '%s' "$UPDATED" | q -X PUT "$API/users/profile" -H "$CT" -d @- >/dev/null

# Post-condition 1: the declaration is readable.
BACK=$(q "$API/users/profile" | jq --arg n "$ATTR" '[.attributes[] | select(.name == $n)][0] // empty')
[ -n "$BACK" ] || { echo "ERROR: attribute PUT sonrası okunamadı" >&2; exit 3; }
# Presence is not convergence: the admin-only permissions and the E.164
# validator are the two security properties this script exists to install,
# so the stored declaration must match DESIRED exactly, not merely exist.
[ "$(echo "$BACK" | jq -S -c .)" = "$(echo "$DESIRED" | jq -S -c .)" ] \
  || { echo "ERROR: stored declaration DESIRED ile birebir değil" >&2
       echo "$BACK" | jq -S -c . >&2; exit 3; }

# Post-condition 2 (the one that actually matters): a real write must
# SURVIVE a read-back. The whole reason this script exists is that the
# previous state accepted the write with 2xx and stored nothing, so
# "declaration present" is not evidence — a round-trip is. Uses a throwaway
# probe user, deleted immediately afterwards.
PROBE="userprofile-phone-probe-$$@synthetic.local"
PROBE_PHONE="+905000000001"
# The trap is armed BEFORE the user exists and resolves the id itself, so
# a failure anywhere between create and delete — including a lookup that
# returns an empty list — still removes the probe user (Codex P2).
cleanup_probe() {
  # Fail-safe by construction: errexit is off inside the trap and every
  # step is guarded, because the LAST thing this function does — deleting
  # the file holding the realm-admin bearer token — must run even when the
  # probe-user cleanup itself fails (Codex 019fb687).
  set +e
  local pid=""
  pid=$(curl -s --config "$HDR_FILE" "$API/users?username=$PROBE&exact=true" 2>/dev/null | jq -r '.[0].id // empty' 2>/dev/null)
  if [ -n "$pid" ]; then
    curl -s -X DELETE --config "$HDR_FILE" "$API/users/$pid" >/dev/null 2>&1 || true
  fi
  rm -f -- "$HDR_FILE"
}
trap cleanup_probe EXIT
q -X POST "$API/users" -H "$CT" -d "{\"username\":\"$PROBE\",\"enabled\":false,\"attributes\":{\"$ATTR\":[\"$PROBE_PHONE\"]}}" >/dev/null
PUID=$(q "$API/users?username=$PROBE&exact=true" | jq -r '.[0].id // empty')
[ -n "$PUID" ] || { echo "ERROR: probe kullanıcı id'si çözülemedi" >&2; exit 3; }
STORED=$(q "$API/users/$PUID" | jq -r --arg n "$ATTR" '.attributes[$n][0] // empty')
q -X DELETE "$API/users/$PUID" >/dev/null
trap cleanup_hdr EXIT
[ "$STORED" = "$PROBE_PHONE" ] \
  || { echo "ERROR: round-trip FAILED — yazılan '$PROBE_PHONE', okunan '$STORED'" >&2; exit 3; }

echo "APPLIED: $ATTR managed attribute (admin-only edit, E.164 validator)"
echo "ROUND-TRIP-OK: yazılan telefon geri okundu"
echo "$BACK" | jq -c '{name, permissions, validations}'
