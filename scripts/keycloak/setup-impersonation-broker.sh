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
#   REALM=serban CLIENT_AUDIENCE=serban-web \
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

if [ "$VERIFY_ONLY" != "1" ]; then
  if [ ! -f "$ADMIN_PASS_FILE" ]; then
    echo "ERROR: KC admin password file not found: $ADMIN_PASS_FILE" >&2
    exit 1
  fi
  if [ -z "$SECRET_OUT" ]; then
    echo "ERROR: SECRET_OUT env required for apply (Codex iter-4 P0-1)" >&2
    echo "       Suggestion: SECRET_OUT=/tmp/impersonation-broker-secret.txt" >&2
    exit 1
  fi
fi

# ─── 0. KC features pre-flight (Codex 019e0dfb iter-7 absorb) ──────────────
# Spike-2 sirasinda PR-A apply edildi ama KC_FEATURES'da `authorization` ve
# `admin-fine-grained-authz:v1` eksikti -> Step 4 management/permissions
# endpoint "Feature not enabled" verdi. Kullanici PR #465 ile bu features
# eklendi. Bu fail-fast guard rai:
echo "=== Step 0/7: KC features pre-flight check ==="
KC_FEATURES_RUNTIME=$(docker exec "$KC_CONTAINER" /opt/keycloak/bin/kc.sh show-config 2>&1 \
                     | grep -E '^\s*kc.features\s*=' | head -1 || echo "")
MISSING_FEATURES=""
for required in "token-exchange" "admin-fine-grained-authz" "authorization"; do
  if ! echo "$KC_FEATURES_RUNTIME" | grep -q "$required"; then
    MISSING_FEATURES="$MISSING_FEATURES $required"
  fi
done
if [ -n "$MISSING_FEATURES" ]; then
  echo "ERROR: KC_FEATURES missing required features:$MISSING_FEATURES" >&2
  echo "       Required: token-exchange, admin-fine-grained-authz:v1, authorization" >&2
  echo "       Update host-compose/keycloak/${ENV}/docker-compose.yml KC_FEATURES env" >&2
  echo "       Then restart: docker compose up -d --force-recreate keycloak" >&2
  exit 1
fi
echo "✓ Required features active: token-exchange, admin-fine-grained-authz, authorization"

# ─── 1. Login (master realm) ───────────────────────────────────────────────
echo ""
echo "=== Step 1/7: Login to Keycloak master realm ==="
ADMIN_PASS=$(sudo cat "$ADMIN_PASS_FILE" | tr -d '\n')
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
  # Codex 019e0dfb iter-7 absorb (Spike-2 manual patch): kcadm 26.x'te
  # `-s "policies=[...]"` form "unknown_error" donuyor (array-of-strings
  # serializer broken). `-f JSON` form file-based PUT calisir.
  TE_PERM_NAME=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" 2>/dev/null \
                 | python3 -c 'import json,sys;print(json.load(sys.stdin).get("name",""))' 2>/dev/null || echo "")
  ATTACH_JSON_HOST="/tmp/_imperson_attach_${TE_PERM_ID}.json"
  ATTACH_JSON_CONTAINER="/tmp/imperson-attach.json"
  cat > "$ATTACH_JSON_HOST" <<EOF
{
  "id": "$TE_PERM_ID",
  "name": "$TE_PERM_NAME",
  "type": "scope",
  "logic": "POSITIVE",
  "decisionStrategy": "UNANIMOUS",
  "policies": ["$POLICY_ID"]
}
EOF
  docker cp "$ATTACH_JSON_HOST" "$KC_CONTAINER:$ATTACH_JSON_CONTAINER" >/dev/null 2>&1 \
    || { echo "ERROR: docker cp policy attach JSON failed" >&2; rm -f "$ATTACH_JSON_HOST"; exit 2; }

  ATTACH_OUT=$($KC update "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" \
    -f "$ATTACH_JSON_CONTAINER" 2>&1 || true)
  rm -f "$ATTACH_JSON_HOST"
  docker exec "$KC_CONTAINER" rm -f "$ATTACH_JSON_CONTAINER" 2>/dev/null || true

  if echo "$ATTACH_OUT" | grep -qiE "(error|fail|exception)"; then
    echo "ERROR: policy attach (-f JSON form) failed: $ATTACH_OUT" >&2
    exit 2
  fi
  echo "✓ Policy attached to token-exchange permission (via -f JSON form)"
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
    print(f"  {r}={\"present\" if r in roles else \"MISSING\"}")
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
print(f"  permission_name: {p.get(\"name\")}")
print(f"  permission_id: {p.get(\"id\",\"\")[:8]}...")
print(f"  decision_strategy: {p.get(\"decisionStrategy\")}")
print(f"  policy_count: {len(p.get(\"policies\",[]))}")
'  )
echo "$PERM_DETAIL"

# Get policies on permission
POLICIES_ON_PERM=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID/associatedPolicies" -r "$REALM" 2>/dev/null \
  | python3 -c '
import json,sys
ps = json.load(sys.stdin)
names = [p.get("name") for p in ps]
print(f"  attached_policies: {names}")
print("PASS" if "impersonation-broker-only" in names else "FAIL")
'  )
echo "$POLICIES_ON_PERM"
echo "$POLICIES_ON_PERM" | tail -1 | grep -q "^PASS$" || {
  echo "ERROR: policy 'impersonation-broker-only' NOT attached to token-exchange permission" >&2
  echo "       Manual console fallback may be needed; re-run with VERIFY_ONLY=1" >&2
  exit 3
}

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

# ─── 6. Impersonator role grant (Codex 019e0dfb iter-7 absorb) ───────────
# Spike-2 sirasinda token exchange "subject not allowed to impersonate"
# verdi cunku subject token sahibi user'da realm-management/impersonation
# role yoktu. Her impersonator persona'ya bu role atanmali.
#
# IMPERSONATOR_USERNAMES: virgul ile ayrilmis liste, yoksa skip (operator
# manuel atayacak, audit doc icin uyari verir).
#
echo ""
echo "=== Step 6/7: Impersonator role grant ==="
if [ "$VERIFY_ONLY" = "1" ]; then
  echo "(verify-only mode — skipping role grant)"
elif [ -n "${IMPERSONATOR_USERNAMES:-}" ]; then
  IFS=',' read -ra USERS <<<"$IMPERSONATOR_USERNAMES"
  for U in "${USERS[@]}"; do
    U_TRIM=$(echo "$U" | xargs)
    [ -z "$U_TRIM" ] && continue
    OUT=$($KC add-roles -r "$REALM" --uusername "$U_TRIM" \
            --cclientid realm-management --rolename impersonation 2>&1 || true)
    if echo "$OUT" | grep -qiE "(already|conflict|409)"; then
      echo "  ✓ $U_TRIM (already has impersonation)"
    elif [ -z "$OUT" ] || echo "$OUT" | grep -q "^$"; then
      echo "  ✓ $U_TRIM (impersonation granted)"
    else
      echo "  ✗ $U_TRIM: $OUT" >&2
    fi
  done
else
  echo "(IMPERSONATOR_USERNAMES env unset — operator manuel role grant gerek)"
  echo "  Per impersonator user manual:"
  echo "    docker exec $KC_CONTAINER /opt/keycloak/bin/kcadm.sh add-roles \\"
  echo "      -r $REALM --uusername <USERNAME> \\"
  echo "      --cclientid realm-management --rolename impersonation"
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
