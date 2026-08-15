#!/usr/bin/env bash
#
# setup-impersonation-broker.sh — User Impersonation v1 PR-A apply script.
#
# Codex thread: 019e0dfb-7230-7f43-80c4-dd03e36a2f70
#   - iter-3 PARTIAL → ready_for_pr_a: true
#   - iter-4 REVISE → 4 P0/P1 fix absorb (secret handoff, fail-fast policy,
#     desired-state idempotency, machine-readable verify assertion)
#
# Spec: platform-backend docs/plans/2026-05-user-impersonation-v1-spec.md
# Spike-1: platform-backend docs/spikes/2026-05-impersonation-token-exchange-spike.md
#
# Idempotent kcadm.sh script — desired-state apply (NOT skip-if-exists):
# fresh create OR existing client config update; fail-fast on policy errors;
# machine-readable verify output; secret handoff via SECRET_OUT temp file
# (umask 077, operator-only readable).
#
# Usage:
#   # Test realm (default)
#   SECRET_OUT=/tmp/impersonation-broker-secret.txt \
#     ./setup-impersonation-broker.sh
#
#   # Prod realm — explicit confirmation gate (Codex iter-4 §5)
#   CONFIRM_PROD_IMPERSONATION_BROKER=serban \
#   REALM=serban CLIENT_AUDIENCE=frontend \
#   SECRET_OUT=/tmp/impersonation-broker-secret-prod.txt \
#     ./setup-impersonation-broker.sh
#
#   # Verify-only (re-check existing apply state, no mutations)
#   VERIFY_ONLY=1 ./setup-impersonation-broker.sh
#
# Exit codes:
#   0   PASS — desired state achieved + verify assertions OK
#   1   ERROR — login/lookup/missing input
#   2   MANUAL_POLICY_REQUIRED — fine-grained authz REST shape mismatch;
#       operator console manual fallback needed (KC console: Clients →
#       audience → Permissions → Token Exchange → policy attach), then
#       re-run with VERIFY_ONLY=1.
#   3   VERIFY_FAILED — apply ran but read-back assertions failed.
#
# HARD RULE compliance:
#   - No raw secret/token in stdout (secret only in SECRET_OUT file)
#   - Operator user credentials untouched
#   - Idempotent → re-run safe; existing client converged to desired state
#   - argv leak note: kcadm config + create commands carry password/secret
#     in process argv (visible to root via /proc); trusted host only.
#
set -euo pipefail

REALM="${REALM:-platform-test}"
CLIENT_ID="impersonation-broker"
CLIENT_AUDIENCE="${CLIENT_AUDIENCE:-frontend}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"
SECRET_OUT="${SECRET_OUT:-}"

# ─── Pre-flight ────────────────────────────────────────────────────────────
case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; ENV="test" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; ENV="prod"
    if [ "${CONFIRM_PROD_IMPERSONATION_BROKER:-}" != "serban" ]; then
      echo "ERROR: prod realm requires explicit CONFIRM_PROD_IMPERSONATION_BROKER=serban env" >&2
      echo "       (Codex iter-4 §5 prod confirmation gate)" >&2
      exit 1
    fi
    ;;
  *) echo "ERROR: unknown realm '$REALM' (expected: platform-test, serban)" >&2; exit 1 ;;
esac

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"
ADMIN_PASS_FILE="/home/halil/platform-k8s-gitops/host-compose/keycloak/${ENV}/secrets/kc_admin_password.txt"

read_admin_password() {
  if [ -f "$ADMIN_PASS_FILE" ]; then
    sudo cat "$ADMIN_PASS_FILE" | tr -d '\n'
    return
  fi

  # Newer host-compose uses Docker secrets exposed only inside the KC
  # container. VERIFY_ONLY needs the same fallback; otherwise prod verification
  # can fail even while the live container has a valid admin password file.
  docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null | tr -d '\n'
}

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ ! -f "$ADMIN_PASS_FILE" ] \
      && ! docker exec "$KC_CONTAINER" sh -lc 'test -r "$KEYCLOAK_ADMIN_PASSWORD_FILE"' >/dev/null 2>&1; then
    echo "ERROR: KC admin password not found in host file or container secret" >&2
    echo "       Host file checked: $ADMIN_PASS_FILE" >&2
    echo "       Container env checked: KEYCLOAK_ADMIN_PASSWORD_FILE" >&2
    exit 1
  fi
  if [ -z "$SECRET_OUT" ]; then
    echo "ERROR: SECRET_OUT env required for apply (Codex iter-4 P0-1)" >&2
    echo "       Suggestion: SECRET_OUT=/tmp/impersonation-broker-secret.txt" >&2
    exit 1
  fi
fi

# ─── 0. KC features pre-flight (Codex iter-8 absorb: exact v1 + grep -F) ───
# Spike-2 sirasinda PR-A apply edildi ama KC_FEATURES'da `authorization` ve
# `admin-fine-grained-authz:v1` eksikti -> Step 4 management/permissions
# endpoint "Feature not enabled" verdi. Bu fail-fast guard:
#
# Codex iter-8 P1-2 absorb: substring match yerine `grep -F` fixed-string +
# `admin-fine-grained-authz:v1` exact (v2 default'u substring match'i bypass
# ediyordu, REST shape uyumsuzlugu reproduce edilebilirdi).
echo "=== Step 0/7: KC features pre-flight check ==="
KC_SHOW_CONFIG=$(docker exec "$KC_CONTAINER" /opt/keycloak/bin/kc.sh show-config 2>&1 || echo "")

require_feature() {
  local feature="$1"
  if ! printf '%s\n' "$KC_SHOW_CONFIG" | grep -Fq "$feature"; then
    MISSING_FEATURES="$MISSING_FEATURES $feature"
  fi
}

MISSING_FEATURES=""
require_feature "token-exchange"
require_feature "admin-fine-grained-authz:v1"
require_feature "authorization"

if [ -n "$MISSING_FEATURES" ]; then
  echo "ERROR: KC_FEATURES missing required features:$MISSING_FEATURES" >&2
  echo "       Required (exact): token-exchange, admin-fine-grained-authz:v1, authorization" >&2
  echo "       Update host-compose/keycloak/${ENV}/docker-compose.yml KC_FEATURES env" >&2
  echo "       Then restart: docker compose up -d --force-recreate keycloak" >&2
  echo ""
  echo "       Current KC features (last 20 lines for debug):" >&2
  printf '%s\n' "$KC_SHOW_CONFIG" | grep -iE 'feature|preview' | tail -20 >&2
  exit 1
fi
echo "✓ Required features active: token-exchange, admin-fine-grained-authz:v1, authorization"

# ─── 1. Login (master realm) ───────────────────────────────────────────────
echo ""
echo "=== Step 1/7: Login to Keycloak master realm ==="
ADMIN_PASS=$(read_admin_password)
[ -n "$ADMIN_PASS" ] || { echo "ERROR: resolved KC admin password is empty" >&2; exit 1; }
$KC config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user admin \
  --password "$ADMIN_PASS" >/dev/null 2>&1 || {
    echo "ERROR: master realm login failed" >&2
    exit 1
}
unset ADMIN_PASS  # remove from script env (still in argv from kcadm config)
echo "✓ Logged in (target realm: $REALM)"

# ─── 2. Provision broker client — DESIRED STATE (Codex iter-4 P1-1) ──────
if [ "$VERIFY_ONLY" = "1" ]; then
  echo ""
  echo "=== Step 2/7: VERIFY_ONLY — read existing client ==="
  EXISTING_ID=$($KC get clients -r "$REALM" --query "clientId=$CLIENT_ID" --fields id 2>/dev/null \
                | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")
  if [ -z "$EXISTING_ID" ]; then
    echo "ERROR: client $CLIENT_ID not found in $REALM (verify-only mode requires prior apply)" >&2
    exit 1
  fi
  BROKER_ID="$EXISTING_ID"
  echo "✓ Existing client: ${BROKER_ID:0:8}..."
else
  echo ""
  echo "=== Step 2/7: Apply desired state for $CLIENT_ID client ==="
  EXISTING_ID=$($KC get clients -r "$REALM" --query "clientId=$CLIENT_ID" --fields id 2>/dev/null \
                | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

  if [ -n "$EXISTING_ID" ]; then
    BROKER_ID="$EXISTING_ID"
    echo "✓ Client exists (id: ${BROKER_ID:0:8}...) — converging to desired state"
    # Codex iter-4 P1-1: existing client desired-state enforce
    $KC update "clients/$BROKER_ID" -r "$REALM" \
      -s clientAuthenticatorType=client-secret \
      -s serviceAccountsEnabled=true \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false \
      -s publicClient=false \
      -s 'attributes."token.exchange.permission.enabled"=true' \
      || { echo "ERROR: client desired-state update failed" >&2; exit 1; }
    echo "  ✓ Converged: confidential, service-account, no direct/implicit/standard, token-exchange enabled"
    echo "  → Existing secret preserved (rotate via separate runbook if needed)"
  else
    GENERATED_SECRET=$(openssl rand -base64 32)
    BROKER_ID=$($KC create clients -r "$REALM" \
      -s "clientId=$CLIENT_ID" \
      -s clientAuthenticatorType=client-secret \
      -s "secret=$GENERATED_SECRET" \
      -s serviceAccountsEnabled=true \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false \
      -s publicClient=false \
      -s 'attributes."token.exchange.permission.enabled"=true' \
      -i 2>&1 | tail -1) || { echo "ERROR: client create failed" >&2; exit 1; }
    echo "✓ Client created (id: ${BROKER_ID:0:8}...)"

    # Codex iter-4 P0-1: secret handoff via umask 077 file (NOT stdout)
    umask 077
    printf '%s' "$GENERATED_SECRET" > "$SECRET_OUT"
    unset GENERATED_SECRET
    echo "✓ Secret written to: $SECRET_OUT (operator-only readable, mode 0600)"
    echo "  → Operator: vault kv put secret/platform/auth-service/impersonation-broker \\"
    echo "        client_id=$CLIENT_ID \\"
    echo "        client_secret=\"\$(sudo cat $SECRET_OUT)\""
    echo "  → After Vault write: shred -u $SECRET_OUT"
  fi
fi

# ─── 3. Service account roles (idempotent — re-assignment OK) ────────────
echo ""
echo "=== Step 3/7: Assign service account roles ==="
SA_USERNAME="service-account-${CLIENT_ID}"

# Track role assignment failures (Codex iter-4 P0-2: fail-fast)
ROLES_FAIL=0
assign_role() {
  local role="$1"
  local out
  out=$($KC add-roles -r "$REALM" \
    --uusername "$SA_USERNAME" \
    --cclientid realm-management \
    --rolename "$role" 2>&1 || true)
  # "already" patterns (kcadm idempotent re-assignment OK)
  if echo "$out" | grep -qiE "(already|conflict|409)"; then
    echo "  ✓ $role (already assigned)"
  elif [ -z "$out" ] || echo "$out" | grep -q "^$"; then
    echo "  ✓ $role"
  else
    echo "  ✗ $role: $out" >&2
    ROLES_FAIL=$((ROLES_FAIL + 1))
  fi
}

if [ "$VERIFY_ONLY" != "1" ]; then
  assign_role impersonation
  assign_role view-users
  assign_role query-users
  if [ "$ROLES_FAIL" -gt 0 ]; then
    echo "ERROR: $ROLES_FAIL role assignment(s) failed (Codex iter-4 P0-2 fail-fast)" >&2
    exit 1
  fi
fi

# ─── 4. Fine-grained token-exchange permission (Codex iter-4 P0-2 fail-fast) ─
echo ""
echo "=== Step 4/7: Fine-grained authz on $CLIENT_AUDIENCE client ==="
AUDIENCE_ID=$($KC get clients -r "$REALM" --query "clientId=$CLIENT_AUDIENCE" --fields id 2>/dev/null \
              | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

if [ -z "$AUDIENCE_ID" ]; then
  echo "ERROR: audience client '$CLIENT_AUDIENCE' not found in $REALM" >&2
  exit 1
fi

# Auth-service's ImpersonationController requires a numeric `userId` JWT
# claim. Prod frontend tokens previously carried only `uid`; start-session
# failed with ADMIN_IDENTITY_MISSING until this mapper was added live.
# Keep it on the same audience client used by the broker exchange flow.
USERID_MAPPER_ID=$($KC get "clients/$AUDIENCE_ID/protocol-mappers/models" -r "$REALM" 2>/dev/null \
                 | python3 -c 'import json,sys; d=json.load(sys.stdin); m=[x for x in d if x.get("name")=="userId-claim"]; print(m[0].get("id","") if m else "")' 2>/dev/null || echo "")

if [ "$VERIFY_ONLY" != "1" ]; then
  USERID_MAPPER_HOST="$(mktemp "/tmp/_imperson_userid_mapper_${AUDIENCE_ID}.XXXXXX.json")"
  USERID_MAPPER_CONTAINER="/tmp/imperson-userid-mapper-${AUDIENCE_ID}-$$.json"
  cat > "$USERID_MAPPER_HOST" <<'JSON'
{
  "name": "userId-claim",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "consentRequired": false,
  "config": {
    "user.attribute": "userId",
    "claim.name": "userId",
    "jsonType.label": "long",
    "id.token.claim": "true",
    "access.token.claim": "true",
    "userinfo.token.claim": "true",
    "multivalued": "false"
  }
}
JSON
  # `docker cp` into a running container whose /tmp is a tmpfs mount silently
  # lands the file in the underlying image layer, not the tmpfs the KC process
  # sees — kcadm then reports "File not found". Pipe through the container's own
  # shell so the write happens inside the same mount namespace kcadm reads from.
  docker exec -i "$KC_CONTAINER" sh -c "cat > '$USERID_MAPPER_CONTAINER'" < "$USERID_MAPPER_HOST" \
    || { echo "ERROR: userId mapper JSON write into container failed" >&2; rm -f "$USERID_MAPPER_HOST"; exit 1; }
  if [ -n "$USERID_MAPPER_ID" ]; then
    $KC update "clients/$AUDIENCE_ID/protocol-mappers/models/$USERID_MAPPER_ID" -r "$REALM" \
      -f "$USERID_MAPPER_CONTAINER" >/dev/null \
      || { echo "ERROR: userId mapper update failed" >&2; rm -f "$USERID_MAPPER_HOST"; exit 1; }
    echo "✓ userId-claim mapper exists — converged to desired state"
  else
    $KC create "clients/$AUDIENCE_ID/protocol-mappers/models" -r "$REALM" \
      -f "$USERID_MAPPER_CONTAINER" >/dev/null \
      || { echo "ERROR: userId mapper create failed" >&2; rm -f "$USERID_MAPPER_HOST"; exit 1; }
    echo "✓ userId-claim mapper created on $CLIENT_AUDIENCE"
  fi
  rm -f "$USERID_MAPPER_HOST"
  docker exec "$KC_CONTAINER" rm -f "$USERID_MAPPER_CONTAINER" >/dev/null 2>&1 || true
fi

USERID_MAPPER_VERIFY=$($KC get "clients/$AUDIENCE_ID/protocol-mappers/models" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json,sys
d=json.load(sys.stdin)
matches=[
  x for x in d
  if x.get("name")=="userId-claim"
  and x.get("protocolMapper")=="oidc-usermodel-attribute-mapper"
  and x.get("config",{}).get("user.attribute")=="userId"
  and x.get("config",{}).get("claim.name")=="userId"
  and x.get("config",{}).get("access.token.claim")=="true"
]
print(len(matches))
' 2>/dev/null || echo "0")
[ "$USERID_MAPPER_VERIFY" -ge 1 ] || { echo "ERROR: userId-claim mapper verify FAIL" >&2; exit 3; }
echo "✓ userId-claim mapper verify PASS"

if [ "$VERIFY_ONLY" != "1" ]; then
  # Codex iter-4 P0-2: explicit error capture
  PERMS_OUT=$($KC update "clients/$AUDIENCE_ID/management/permissions" -r "$REALM" \
    -s 'enabled=true' 2>&1 || true)
  if echo "$PERMS_OUT" | grep -qiE "(error|fail|exception|404|405)"; then
    echo "ERROR: management permissions enable failed: $PERMS_OUT" >&2
    echo "       Likely Keycloak 26.x REST shape mismatch — manual console fallback:" >&2
    echo "       KC console → Clients → $CLIENT_AUDIENCE → Permissions tab → Enable" >&2
    exit 2
  fi
  echo "✓ Management permissions enabled on $CLIENT_AUDIENCE"
fi

# Get token-exchange scope permission ID (verify step)
TE_PERM_ID=$($KC get "clients/$AUDIENCE_ID/management/permissions" -r "$REALM" 2>/dev/null \
             | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("scopePermissions",{}).get("token-exchange","") or "")' 2>/dev/null || echo "")

if [ -z "$TE_PERM_ID" ]; then
  echo "ERROR: token-exchange scope permission ID not found (Codex iter-4 P0-2)" >&2
  echo "       Manual console fallback required:" >&2
  echo "       KC console → Clients → $CLIENT_AUDIENCE → Permissions → Token Exchange → enable + create policy" >&2
  echo "       Then re-run: VERIFY_ONLY=1 $0" >&2
  exit 2
fi
echo "✓ token-exchange permission id: ${TE_PERM_ID:0:8}..."

REALM_MGMT_ID=$($KC get clients -r "$REALM" --query 'clientId=realm-management' --fields id 2>/dev/null \
                | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])' 2>/dev/null || echo "")
if [ -z "$REALM_MGMT_ID" ]; then
  echo "ERROR: realm-management client not found" >&2
  exit 1
fi

POLICY_NAME="impersonation-broker-only"
CUSTOM_TE_PERMISSION_NAME="impersonation-broker-token-exchange"

EXISTING_POLICY=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/policy" -r "$REALM" \
                  --query "name=$POLICY_NAME" --fields id 2>/dev/null \
                  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ -z "$EXISTING_POLICY" ]; then
    POLICY_OUT=$($KC create "clients/$REALM_MGMT_ID/authz/resource-server/policy/client" -r "$REALM" \
      -s "name=$POLICY_NAME" \
      -s 'description=Codex 019e0dfb iter-3: only impersonation-broker can exchange tokens' \
      -s "clients=[\"$BROKER_ID\"]" \
      -i 2>&1 || true)
    if echo "$POLICY_OUT" | grep -qiE "(error|fail|exception)"; then
      echo "ERROR: policy create failed: $POLICY_OUT" >&2
      exit 2
    fi
    POLICY_ID=$(echo "$POLICY_OUT" | tail -1)
    echo "✓ Client policy created: $POLICY_NAME (id: ${POLICY_ID:0:8}...)"
  else
    POLICY_ID="$EXISTING_POLICY"
    # Codex iter-4 P1-1: converge existing policy to desired state
    $KC update "clients/$REALM_MGMT_ID/authz/resource-server/policy/client/$POLICY_ID" -r "$REALM" \
      -s "clients=[\"$BROKER_ID\"]" 2>&1 | tail -1 || true
    echo "✓ Client policy exists: $POLICY_NAME — converged to desired state"
  fi

  # Attach policy to token-exchange permission (fail-fast)
  # Codex iter-7 absorb (Spike-2 manual patch): kcadm 26.x'te
  # `-s "policies=[...]"` form "unknown_error" donuyor (array-of-strings
  # serializer broken). `-f JSON` form file-based PUT calisir.
  #
  # Codex iter-8 P2 absorb: paralel apply race-safe — mktemp + PID suffix
  # container path, trap ile guarantee cleanup. Mevcut permission JSON'u
  # fetch et + sadece policies field overwrite (ileride KC scopes/resources
  # alani eklerse forward-compat).
  PERM_FETCH_HOST="$(mktemp "/tmp/_imperson_perm_${TE_PERM_ID}.XXXXXX.json")"
  ATTACH_JSON_HOST="$(mktemp "/tmp/_imperson_attach_${TE_PERM_ID}.XXXXXX.json")"
  ATTACH_JSON_CONTAINER="/tmp/imperson-attach-${TE_PERM_ID}-$$.json"
  trap 'rm -f "$PERM_FETCH_HOST" "$ATTACH_JSON_HOST"; docker exec "$KC_CONTAINER" rm -f "$ATTACH_JSON_CONTAINER" >/dev/null 2>&1 || true' EXIT

  $KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" \
     > "$PERM_FETCH_HOST" 2>/dev/null \
     || { echo "ERROR: failed to fetch existing permission JSON" >&2; exit 2; }

  python3 - "$PERM_FETCH_HOST" "$POLICY_ID" "$ATTACH_JSON_HOST" <<'PYEOF'
import json, sys
fetch_path, policy_id, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(fetch_path) as f:
    perm = json.load(f)
perm["policies"] = [policy_id]
with open(out_path, "w") as f:
    json.dump(perm, f)
PYEOF

  # See userId-mapper note above: tmpfs /tmp makes `docker cp` unreliable on the
  # migrated host. Write through the container shell instead.
  docker exec -i "$KC_CONTAINER" sh -c "cat > '$ATTACH_JSON_CONTAINER'" < "$ATTACH_JSON_HOST" \
    || { echo "ERROR: policy attach JSON write into container failed" >&2; exit 2; }

  ATTACH_OUT=$($KC update "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" \
    -f "$ATTACH_JSON_CONTAINER" 2>&1 || true)

  if echo "$ATTACH_OUT" | grep -qiE "(error|fail|exception)"; then
    echo "ERROR: policy attach (-f JSON form) failed: $ATTACH_OUT" >&2
    exit 2
  fi
  echo "✓ Policy attached to token-exchange permission (via -f JSON form, race-safe)"

  # Keycloak 26.x can accept the PUT above but leave the generated management
  # permission without associated policies. Keep the generated permission intact
  # and add an explicit scope permission for the same client resource/scope.
  BUILTIN_ATTACHED=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID/associatedPolicies" -r "$REALM" 2>/dev/null \
    | python3 -c '
import json,sys
ps=json.load(sys.stdin)
print("yes" if any(p.get("name")=="impersonation-broker-only" for p in ps) else "no")
' 2>/dev/null || echo "no")

  if [ "$BUILTIN_ATTACHED" != "yes" ]; then
    CUSTOM_TE_PERMISSION_ID=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission" -r "$REALM" \
      --query "name=$CUSTOM_TE_PERMISSION_NAME" --fields id 2>/dev/null \
      | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

    if [ -z "$CUSTOM_TE_PERMISSION_ID" ]; then
      RESOURCE_NAME="client.resource.$AUDIENCE_ID"
      CUSTOM_OUT=$($KC create "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope" -r "$REALM" \
        -s "name=$CUSTOM_TE_PERMISSION_NAME" \
        -s "description=Allow impersonation-broker to token-exchange for $CLIENT_AUDIENCE" \
        -s "resources=[\"$RESOURCE_NAME\"]" \
        -s 'scopes=["token-exchange"]' \
        -s "policies=[\"$POLICY_NAME\"]" \
        -s decisionStrategy=UNANIMOUS \
        -s logic=POSITIVE \
        -i 2>&1 || true)
      if echo "$CUSTOM_OUT" | grep -qiE "(error|fail|exception)"; then
        echo "ERROR: custom token-exchange permission create failed: $CUSTOM_OUT" >&2
        exit 2
      fi
      echo "✓ Custom token-exchange permission created: $CUSTOM_TE_PERMISSION_NAME"
    else
      echo "✓ Custom token-exchange permission exists: $CUSTOM_TE_PERMISSION_NAME"
    fi
  fi
else
  POLICY_ID="$EXISTING_POLICY"
fi

# ─── 5. Verify provisioning (Codex iter-4 P1-2: fail-fast assertions) ────
echo ""
echo "=== Step 5/7: Verify (machine-readable assertions) ==="

# Assertion 1: client config
CLIENT_VERIFY=$($KC get "clients/$BROKER_ID" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json,sys
c = json.load(sys.stdin)
attrs = c.get("attributes", {})
checks = {
    "publicClient_false": c.get("publicClient") == False,
    "serviceAccount_enabled": c.get("serviceAccountsEnabled") == True,
    "standard_flow_off": c.get("standardFlowEnabled") == False,
    "direct_grants_off": c.get("directAccessGrantsEnabled") == False,
    "token_exchange_attr": attrs.get("token.exchange.permission.enabled") == "true",
}
fails = [k for k,v in checks.items() if not v]
for k,v in checks.items():
    print(f"  {k}={v}")
print("FAIL" if fails else "PASS")
')
echo "$CLIENT_VERIFY"
echo "$CLIENT_VERIFY" | tail -1 | grep -q "^PASS$" || { echo "ERROR: client verify FAIL" >&2; exit 3; }

# Assertion 2: service account roles
echo ""
echo "Service account effective roles (realm-management):"
ROLES_VERIFY=$($KC get-roles -r "$REALM" --uusername "$SA_USERNAME" --cclientid realm-management --effective 2>/dev/null \
  | python3 -c '
import json,sys
roles = {r["name"] for r in json.load(sys.stdin)}
required = {"impersonation","view-users","query-users"}
missing = required - roles
for r in required:
    state = "present" if r in roles else "MISSING"
    print(f"  {r}={state}")
print("FAIL" if missing else "PASS")
')
echo "$ROLES_VERIFY"
echo "$ROLES_VERIFY" | tail -1 | grep -q "^PASS$" || { echo "ERROR: roles verify FAIL" >&2; exit 3; }

# Assertion 3: policy attached to token-exchange permission (Codex iter-4 P1-2 critical)
echo ""
echo "Policy attachment verify (Codex iter-4 P1-2):"
PERM_DETAIL=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json,sys
p = json.load(sys.stdin)
name = p.get("name")
pid = p.get("id","")
ds = p.get("decisionStrategy")
pc = len(p.get("policies",[]))
print(f"  permission_name: {name}")
print(f"  permission_id: {pid[:8]}...")
print(f"  decision_strategy: {ds}")
print(f"  policy_count: {pc}")
'  )
echo "$PERM_DETAIL"

# Get policies on permission
POLICIES_ON_GENERATED_PERM=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID/associatedPolicies" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json,sys
ps = json.load(sys.stdin)
names = [p.get("name") for p in ps]
print(f"  generated_permission_attached_policies: {names}")
print("PASS" if "impersonation-broker-only" in names else "FAIL")
'  )
echo "$POLICIES_ON_GENERATED_PERM"

CUSTOM_TE_PERMISSION_ID=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission" -r "$REALM" \
  --query "name=$CUSTOM_TE_PERMISSION_NAME" --fields id 2>/dev/null \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

CUSTOM_POLICY_VERIFY="FAIL"
if [ -n "$CUSTOM_TE_PERMISSION_ID" ]; then
  CUSTOM_POLICY_VERIFY=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$CUSTOM_TE_PERMISSION_ID/associatedPolicies" -r "$REALM" 2>/dev/null \
    | python3 -c '
import json,sys
ps = json.load(sys.stdin)
names = [p.get("name") for p in ps]
print(f"  custom_permission_attached_policies: {names}")
print("PASS" if "impersonation-broker-only" in names else "FAIL")
'  )
  echo "$CUSTOM_POLICY_VERIFY"
fi

if ! echo "$POLICIES_ON_GENERATED_PERM" | tail -1 | grep -q "^PASS$" \
   && ! echo "$CUSTOM_POLICY_VERIFY" | tail -1 | grep -q "^PASS$"; then
  echo "ERROR: policy 'impersonation-broker-only' NOT attached to generated or custom token-exchange permission" >&2
  echo "       Manual console fallback may be needed; re-run with VERIFY_ONLY=1" >&2
  exit 3
fi

# Assertion 4: policy clients list contains broker
POLICY_CLIENTS=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/policy/client/$POLICY_ID" -r "$REALM" 2>/dev/null \
  | python3 -c "
import json,sys
p = json.load(sys.stdin)
clients = p.get('config',{}).get('clients','') or p.get('clients','[]')
broker_id='$BROKER_ID'
print(f'  policy_clients={clients}')
print('PASS' if broker_id in str(clients) else 'FAIL')
")
echo "$POLICY_CLIENTS"
echo "$POLICY_CLIENTS" | tail -1 | grep -q "^PASS$" || { echo "ERROR: broker not in policy clients" >&2; exit 3; }

# ─── 6. Impersonator role grant (Codex iter-7+8 absorb) ────────────────────
# Spike-2 sirasinda token exchange "subject not allowed to impersonate"
# verdi cunku subject token sahibi user'da realm-management/impersonation
# role yoktu. Her impersonator persona'ya bu role atanmali.
#
# Codex iter-8 P1-1 absorb (strict model):
#  - apply mode: IMPERSONATOR_USERNAMES env ZORUNLU; unset ise exit 1
#  - per-user: lookup -> enabled check -> grant -> read-back verify
#  - GRANT_FAIL counter > 0 -> exit 1 (fail-fast)
#  - missing user / disabled user / partial match -> fail
#
echo ""
echo "=== Step 6/7: Impersonator role grant ==="
if [ "$VERIFY_ONLY" = "1" ]; then
  echo "(verify-only mode — skipping role grant)"
elif [ -z "${IMPERSONATOR_USERNAMES:-}" ]; then
  echo "ERROR: IMPERSONATOR_USERNAMES env REQUIRED (apply mode, Codex iter-8 strict)" >&2
  echo "       Format: IMPERSONATOR_USERNAMES=user1@x.com,user2@x.com" >&2
  echo "       Reason: token exchange icin subject user'da realm-management/impersonation" >&2
  echo "       role olmali; aksi takdirde 'subject not allowed to impersonate' donulur." >&2
  echo "" >&2
  echo "       Tek user manual:" >&2
  echo "         docker exec $KC_CONTAINER /opt/keycloak/bin/kcadm.sh add-roles \\" >&2
  echo "           -r $REALM --uusername <USERNAME> \\" >&2
  echo "           --cclientid realm-management --rolename impersonation" >&2
  exit 1
else
  GRANT_FAIL=0
  IFS=',' read -ra USERS <<<"$IMPERSONATOR_USERNAMES"
  for U in "${USERS[@]}"; do
    U_TRIM=$(echo "$U" | xargs)
    [ -z "$U_TRIM" ] && continue

    # Step a: exact username lookup (avoid partial/ambiguous match)
    # Codex iter-9 P1 absorb (revised): heredoc + pipe stdin race vardı;
    # `-c '...'` inline + argv ile geç (deterministic).
    USER_INFO=$($KC get users -r "$REALM" --query "username=$U_TRIM" --query exact=true \
                  --fields id,username,enabled 2>/dev/null \
                  | python3 -c '
import json, sys
exact = sys.argv[1]
d = json.load(sys.stdin)
m = [u for u in d if u.get("username") == exact]
if not m:
    print("MISSING")
elif not m[0].get("enabled"):
    print("DISABLED")
else:
    print("OK:" + m[0]["id"])
' "$U_TRIM" 2>/dev/null) || USER_INFO="LOOKUP_FAIL"

    case "$USER_INFO" in
      MISSING)
        echo "  ✗ $U_TRIM: user not found in realm $REALM" >&2
        GRANT_FAIL=$((GRANT_FAIL + 1))
        continue
        ;;
      DISABLED)
        echo "  ✗ $U_TRIM: user disabled (enabled=false)" >&2
        GRANT_FAIL=$((GRANT_FAIL + 1))
        continue
        ;;
      LOOKUP_FAIL)
        echo "  ✗ $U_TRIM: kcadm get users lookup failed" >&2
        GRANT_FAIL=$((GRANT_FAIL + 1))
        continue
        ;;
    esac

    # Step b: idempotent grant
    OUT=$($KC add-roles -r "$REALM" --uusername "$U_TRIM" \
            --cclientid realm-management --rolename impersonation 2>&1 || true)
    if echo "$OUT" | grep -qiE "(error|fail|exception)" \
       && ! echo "$OUT" | grep -qiE "(already|conflict|409)"; then
      echo "  ✗ $U_TRIM: grant error: $OUT" >&2
      GRANT_FAIL=$((GRANT_FAIL + 1))
      continue
    fi

    # Step c: read-back verify (effective roles must contain impersonation)
    HAS_ROLE=$($KC get-roles -r "$REALM" --uusername "$U_TRIM" \
                 --cclientid realm-management --effective 2>/dev/null \
                 | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("yes" if any(r.get("name")=="impersonation" for r in d) else "no")
' 2>/dev/null || echo "no")

    if [ "$HAS_ROLE" = "yes" ]; then
      echo "  ✓ $U_TRIM (impersonation role verified)"
    else
      echo "  ✗ $U_TRIM: role read-back FAILED (grant did not take effect)" >&2
      GRANT_FAIL=$((GRANT_FAIL + 1))
    fi
  done

  if [ "$GRANT_FAIL" -gt 0 ]; then
    echo "ERROR: $GRANT_FAIL impersonator grant(s) failed (Codex iter-8 P1-1 fail-fast)" >&2
    exit 1
  fi
fi

# ─── 7. Vault secret handoff ──────────────────────────────────────────────
echo ""
echo "=== Step 7/7: Vault secret handoff ==="
if [ "$VERIFY_ONLY" = "1" ]; then
  echo "(verify-only mode — no secret handoff)"
elif [ -n "${SECRET_OUT:-}" ] && [ -f "$SECRET_OUT" ]; then
  echo "Secret file: $SECRET_OUT (mode: $(stat -c '%a' "$SECRET_OUT" 2>/dev/null || stat -f '%Lp' "$SECRET_OUT" 2>/dev/null))"
  echo ""
  echo "Operator next step (write to Vault):"
  echo "  vault kv put secret/platform/auth-service/impersonation-broker \\"
  echo "    client_id=$CLIENT_ID \\"
  echo "    client_secret=\"\$(sudo cat $SECRET_OUT)\""
  echo ""
  echo "After Vault write, shred local file:"
  echo "  shred -u $SECRET_OUT"
else
  echo "(existing client — secret preserved; no handoff required)"
fi

echo ""
echo "=== Apply complete — PASS ==="
echo "Next: Spike-2 runbook (platform-backend docs/spikes/2026-05-impersonation-token-exchange-spike.md §Spike-2)"
exit 0
