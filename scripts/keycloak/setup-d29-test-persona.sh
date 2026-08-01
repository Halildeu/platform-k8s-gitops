#!/usr/bin/env bash
#
# setup-d29-test-persona.sh — board #819. Idempotent D29 test persona apply.
#
# Codex design consensus: thread 019e4012.
# Runbook: docs/operations/RUNBOOKS/RB-keycloak-d29-test-persona.md
#
# Creates/converges a disposable, least-privilege NORMAL Keycloak user in the
# platform-test realm — a stable, non-interactive credential for D29 smoke /
# #754 M2, replacing the ad-hoc master-admin password-reset. The persona
# authenticates via the EXISTING `smoke-client` confidential client (password
# grant) and yields a normal-user JWT.
#
# SCOPE — what this deliberately does NOT do:
#   - Does NOT create a Keycloak client (reuses existing `smoke-client`).
#   - Does NOT write Vault. The generated password lands in SECRET_OUT; the
#     operator runs `vault kv put` (mirrors setup-impersonation-broker.sh;
#     ADR-0010 §2.5 — credential issuance is operator-gated).
#   - Does NOT grant realm-admin / admin roles — the persona is a plain normal
#     user (realm default roles only; least-privilege).
#   - Does NOT seed D29 DATA authorization. This formalizes the AUTHENTICATION
#     credential only. D29 data allow/deny (OpenFGA explicit-scope, e.g.
#     PROJECT:1204) is a SEPARATE step — see docs/handoff-smoke-client-keycloak.md.
#   - Does NOT touch the operator's own login user (`halildeu`, formerly
#     admin@example.com) — see the OPERATOR_LOGINS/OPERATOR_EMAILS guard below.
#
# Idempotency: on create, a password is generated → SECRET_OUT. On re-run with
# the persona already present, only attributes converge — the password is NOT
# reset (avoids Keycloak<->Vault drift). Password rotation is explicit:
# ROTATE_D29_TEST_PERSONA_PASSWORD=1.
#
# Usage:
#   # Apply — create persona if missing, converge attributes if present.
#   bash scripts/keycloak/setup-d29-test-persona.sh
#
#   # Rotate the persona password (explicit — re-writes SECRET_OUT).
#   ROTATE_D29_TEST_PERSONA_PASSWORD=1 bash scripts/keycloak/setup-d29-test-persona.sh
#
#   # Verify-only — read-back assertions, no mutation.
#   VERIFY_ONLY=1 bash scripts/keycloak/setup-d29-test-persona.sh
#
# Env:
#   REALM             platform-test (default; test-only — persona is a D29 artifact)
#   PERSONA_USERNAME  d29-test-persona (default)
#   PERSONA_EMAIL     d29-test-persona@testai.acik.com (default)
#   SECRET_OUT        /tmp/d29-test-persona-secret.txt (default; umask 077,
#                     operator-only — the generated password lands here on
#                     create/rotate for the operator's `vault kv put`)
#   ROTATE_D29_TEST_PERSONA_PASSWORD  1 → rotate the password even if the
#                     persona already exists
#   VERIFY_ONLY       1 → read-back assertions only, no mutation
#
# Exit codes:
#   0  PASS — desired state + verify OK
#   1  ERROR — input / login / unexpected state
#   3  VERIFY_FAILED — apply ran (or VERIFY_ONLY) but read-back assertion failed
#
# HARD RULE: the persona password is NEVER written to stdout / logs — only to
# SECRET_OUT (umask 077). Idempotent — re-run safe. Operator credentials
# (`halildeu`) untouched.
#
set -euo pipefail

REALM="${REALM:-platform-test}"
PERSONA_USERNAME="${PERSONA_USERNAME:-d29-test-persona}"
PERSONA_EMAIL="${PERSONA_EMAIL:-d29-test-persona@testai.acik.com}"
SECRET_OUT="${SECRET_OUT:-/tmp/d29-test-persona-secret.txt}"
ROTATE="${ROTATE_D29_TEST_PERSONA_PASSWORD:-0}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"
VAULT_PATH="kv/platform/keycloak/d29-test-persona"

# ─── Pre-flight: realm → container (test-only) ─────────────────────────────
# The D29 test persona is a test-cluster smoke artifact. There is deliberately
# NO prod path — the prod (serban) realm uses real users, never a smoke persona.
case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; ENV="test" ;;
  *) echo "ERROR: realm '$REALM' not allowed — D29 test persona is platform-test only" >&2; exit 1 ;;
esac

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"
ADMIN_PASS_FILE="host-compose/keycloak/${ENV}/secrets/kc_admin_password.txt"

# Guard: never collide with the operator's own login user — username AND
# email, case-insensitive (Codex 019e4012 review).
#
# The lists carry CURRENT and HISTORICAL identities deliberately. The operator's
# username was renamed admin@example.com → halildeu on 2026-08-01 (the address
# had already moved to halildeu@gmail.com). A guard pinned to one literal stops
# guarding the moment the account is renamed, and it fails OPEN: this script
# would then converge the operator's own login user instead of refusing. Keeping
# the retired values costs nothing — no persona may legitimately claim them.
OPERATOR_LOGINS="${OPERATOR_LOGINS:-admin halildeu admin@example.com halildeu@gmail.com}"
OPERATOR_EMAILS="${OPERATOR_EMAILS:-admin@example.com halildeu@gmail.com}"

is_operator_identity() {  # $1 = lowercased needle; $2.. = candidate list
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [ "$needle" = "$(printf '%s' "$item" | tr '[:upper:]' '[:lower:]')" ] && return 0
  done
  return 1
}

PERSONA_USERNAME_LC=$(printf '%s' "$PERSONA_USERNAME" | tr '[:upper:]' '[:lower:]')
PERSONA_EMAIL_LC=$(printf '%s' "$PERSONA_EMAIL" | tr '[:upper:]' '[:lower:]')
# shellcheck disable=SC2086  # unquoted: the space-separated list IS the contract
if is_operator_identity "$PERSONA_USERNAME_LC" $OPERATOR_LOGINS; then
  echo "ERROR: refusing — PERSONA_USERNAME '$PERSONA_USERNAME' is the operator login user" >&2
  exit 1
fi
# shellcheck disable=SC2086
if is_operator_identity "$PERSONA_EMAIL_LC" $OPERATOR_EMAILS; then
  echo "ERROR: refusing — PERSONA_EMAIL '$PERSONA_EMAIL' is the operator login email" >&2
  exit 1
fi

echo "=== D29 test persona apply — realm=$REALM container=$KC_CONTAINER ==="
echo "  persona:    $PERSONA_USERNAME <$PERSONA_EMAIL>"
echo "  vault path: $VAULT_PATH  (operator seeds from SECRET_OUT — not written here)"
echo "  mode:       VERIFY_ONLY=$VERIFY_ONLY ROTATE=$ROTATE"

# ─── Step 1/4: Login (master realm) ────────────────────────────────────────
echo ""
echo "=== Step 1/4: Login ==="
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

# ─── Step 2/4: Resolve persona ─────────────────────────────────────────────
echo ""
echo "=== Step 2/4: Resolve persona ==="
USER_JSON=$($KC get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true 2>/dev/null || echo "[]")
USER_ID=$(printf '%s' "$USER_JSON" \
  | python3 -c 'import json,sys
u=json.load(sys.stdin)
print(u[0]["id"] if u else "")' 2>/dev/null || echo "")

if [ -n "$USER_ID" ]; then
  echo "✓ persona exists — id=$USER_ID"
else
  echo "  persona not found"
  if [ "$VERIFY_ONLY" = "1" ]; then
    echo ""
    echo "=== D29 test persona: VERIFY_FAILED — persona '$PERSONA_USERNAME' does not exist ==="
    exit 3
  fi
fi

# ─── Step 3/4: Apply (create-or-converge; password create/rotate only) ─────
echo ""
echo "=== Step 3/4: Apply ==="
NEED_PASSWORD=0
if [ "$VERIFY_ONLY" = "1" ]; then
  echo "  VERIFY_ONLY=1 — skipping mutation"
elif [ -z "$USER_ID" ]; then
  $KC create users -r "$REALM" \
    -s "username=$PERSONA_USERNAME" \
    -s "email=$PERSONA_EMAIL" \
    -s "firstName=D29" \
    -s "lastName=Smoke Persona" \
    -s 'enabled=true' \
    -s 'emailVerified=true' >/dev/null 2>&1 \
    || { echo "ERROR: create persona failed" >&2; exit 1; }
  USER_ID=$($KC get users -r "$REALM" -q "username=$PERSONA_USERNAME" -q exact=true 2>/dev/null \
    | python3 -c 'import json,sys
u=json.load(sys.stdin)
print(u[0]["id"] if u else "")' 2>/dev/null || echo "")
  [ -n "$USER_ID" ] || { echo "ERROR: created persona not resolvable" >&2; exit 1; }
  echo "✓ created persona — id=$USER_ID"
  NEED_PASSWORD=1
else
  $KC update "users/$USER_ID" -r "$REALM" \
    -s "email=$PERSONA_EMAIL" -s 'enabled=true' -s 'emailVerified=true' >/dev/null 2>&1 \
    || { echo "ERROR: converge persona attributes failed" >&2; exit 1; }
  echo "✓ converged persona attributes — id=$USER_ID (password unchanged)"
  if [ "$ROTATE" = "1" ]; then
    NEED_PASSWORD=1
    echo "  ROTATE_D29_TEST_PERSONA_PASSWORD=1 — password will be rotated"
  fi
fi

if [ "$VERIFY_ONLY" != "1" ] && [ "$NEED_PASSWORD" = "1" ]; then
  # Preflight SECRET_OUT writability BEFORE set-password — never change the
  # live Keycloak password without a place to record it (Codex 019e4012).
  SECRET_DIR=$(dirname "$SECRET_OUT")
  if [ ! -d "$SECRET_DIR" ] || [ ! -w "$SECRET_DIR" ]; then
    echo "ERROR: SECRET_OUT dir not writable ($SECRET_DIR) — aborting before set-password" >&2
    exit 1
  fi
  if [ -e "$SECRET_OUT" ] && [ ! -w "$SECRET_OUT" ]; then
    echo "ERROR: SECRET_OUT exists but is not writable ($SECRET_OUT) — aborting before set-password" >&2
    exit 1
  fi
  PERSONA_PASS=$(openssl rand -base64 30 | tr -dc 'A-Za-z0-9' | head -c 32)
  [ "${#PERSONA_PASS}" -ge 24 ] || { echo "ERROR: password generation failed" >&2; exit 1; }
  $KC set-password -r "$REALM" --userid "$USER_ID" --new-password "$PERSONA_PASS" >/dev/null 2>&1 \
    || { echo "ERROR: set-password failed" >&2; exit 1; }
  # SECRET_OUT — operator-only readable; password is NEVER echoed to stdout/log.
  # Atomic 0600 temp-file write: shell redirection PRESERVES an existing file's
  # mode, so a pre-existing loose-mode SECRET_OUT would keep its mode. Create a
  # fresh 0600 temp file in the same dir and mv it into place (Codex 019e4012)
  # — guarantees operator-only mode even if SECRET_OUT already existed.
  SECRET_TMP=$(mktemp "${SECRET_OUT}.XXXXXX") \
    || { echo "ERROR: could not create SECRET_OUT temp file" >&2; exit 1; }
  chmod 600 "$SECRET_TMP"
  cat > "$SECRET_TMP" <<SECRET
# D29 test persona credential — board #819 (setup-d29-test-persona.sh).
# Operator: seed Vault, then shred this file.
#   vault kv put $VAULT_PATH \\
#     username=$PERSONA_USERNAME email=$PERSONA_EMAIL keycloak_user_id=$USER_ID \\
#     password='<the password value below>'
#   shred -u $SECRET_OUT   # or: rm -P $SECRET_OUT
# keycloak_user_id = Keycloak user UUID — NOT the platform numeric user_id
# used by D29 OpenFGA scope seeds (that is resolved backend-side, separately).
username=$PERSONA_USERNAME
email=$PERSONA_EMAIL
keycloak_user_id=$USER_ID
password=$PERSONA_PASS
SECRET
  mv -f "$SECRET_TMP" "$SECRET_OUT"
  chmod 600 "$SECRET_OUT"
  unset PERSONA_PASS
  echo "✓ password set — written to $SECRET_OUT (umask 077; operator seeds Vault + shreds)"
fi

# ─── Step 4/4: Verify (read-back + least-privilege assertion) ──────────────
echo ""
echo "=== Step 4/4: Verify ==="
VERIFY_FAIL=0
V_JSON=$($KC get "users/$USER_ID" -r "$REALM" 2>/dev/null || echo "{}")
V_ENABLED=$(printf '%s' "$V_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("enabled"))' 2>/dev/null || echo "")
V_EMAILVERIFIED=$(printf '%s' "$V_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("emailVerified"))' 2>/dev/null || echo "")
if [ "$V_ENABLED" != "True" ]; then
  echo "✗ enabled=$V_ENABLED (expected True)"; VERIFY_FAIL=1
fi
if [ "$V_EMAILVERIFIED" != "True" ]; then
  echo "✗ emailVerified=$V_EMAILVERIFIED (expected True)"; VERIFY_FAIL=1
fi

# Least-privilege: assert NO privileged role — realm roles AND client role
# mappings (e.g. realm-management/manage-users). Contract: realm default
# roles only, no explicit role assignment (Codex 019e4012 review).
ALL_MAPPINGS=$($KC get "users/$USER_ID/role-mappings" -r "$REALM" 2>/dev/null || echo "{}")
REALM_ROLES=$(printf '%s' "$ALL_MAPPINGS" | python3 -c 'import json,sys
m=json.load(sys.stdin)
print(",".join(r.get("name","") for r in m.get("realmMappings",[])))' 2>/dev/null || echo "")
CLIENT_ROLES=$(printf '%s' "$ALL_MAPPINGS" | python3 -c 'import json,sys
m=json.load(sys.stdin)
out=[]
for c,info in (m.get("clientMappings") or {}).items():
    out += [c+"/"+r.get("name","") for r in info.get("mappings",[])]
print(",".join(out))' 2>/dev/null || echo "")
LP_OK=1
case ",$REALM_ROLES," in
  *,admin,*|*,realm-admin,*|*,create-realm,*)
    echo "✗ persona carries a privileged realm role: $REALM_ROLES"; VERIFY_FAIL=1; LP_OK=0 ;;
esac
if [ -n "$CLIENT_ROLES" ]; then
  echo "✗ persona carries direct client role mapping(s) — contract is realm default roles only: $CLIENT_ROLES"
  VERIFY_FAIL=1; LP_OK=0
fi
if [ "$LP_OK" = "1" ]; then
  echo "✓ least-privilege — no privileged realm role, no direct client role mappings (realm roles: ${REALM_ROLES:-<none>})"
fi

if [ "$VERIFY_FAIL" = "1" ]; then
  echo ""
  echo "=== D29 test persona: VERIFY_FAILED — realm=$REALM user=$PERSONA_USERNAME ==="
  exit 3
fi
echo "✓ persona enabled + emailVerified + least-privilege"

echo ""
echo "=== D29 test persona: PASS — realm=$REALM user=$PERSONA_USERNAME id=$USER_ID ==="
if [ "$VERIFY_ONLY" = "1" ]; then
  echo "(VERIFY_ONLY — no mutation performed)"
fi
exit 0
