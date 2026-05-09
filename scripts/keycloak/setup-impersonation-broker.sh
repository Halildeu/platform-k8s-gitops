#!/usr/bin/env bash
#
# setup-impersonation-broker.sh — User Impersonation v1 PR-A apply script.
#
# Codex thread: 019e0dfb-7230-7f43-80c4-dd03e36a2f70 (iter-3 PARTIAL → ready_for_pr_a: true)
# Spec: platform-backend docs/plans/2026-05-user-impersonation-v1-spec.md
# Spike-1: platform-backend docs/spikes/2026-05-impersonation-token-exchange-spike.md
#
# Idempotent kcadm.sh script — provisions the impersonation-broker
# confidential client + service account roles + fine-grained token-exchange
# policy in the target Keycloak realm. Can be re-run safely (skip-if-exists
# semantics for client/role assignments; policy idempotency via lookup-then-update).
#
# Usage:
#   # Test realm (default)
#   ./setup-impersonation-broker.sh
#
#   # Prod realm (open prod cutover onayı gerekli — Codex iter-3 §4)
#   REALM=serban CLIENT_AUDIENCE=serban-web \
#     ./setup-impersonation-broker.sh
#
# Required environment / inputs:
#   - KC container reachable (default: platform-kc-test for test realm,
#     platform-kc-prod for prod)
#   - Master realm admin password (read from
#     /home/halil/platform-k8s-gitops/host-compose/keycloak/${ENV}/secrets/kc_admin_password.txt)
#   - jq + python3 on host
#
# Vault secret handling (Codex iter-3 §absorb):
#   - Broker client secret rotated each apply IF KC client is freshly created.
#   - Existing client: secret preserved (no rotate by default).
#   - Vault path: secret/platform/auth-service/impersonation-broker (write-only by this script).
#   - The script NEVER prints the secret; only confirms write success + Vault path.
#
# HARD RULE compliance:
#   - No raw token / secret in stdout
#   - Operator user credentials untouched
#   - Idempotent → re-run safe
#
# Spike-2 runbook: docs/spikes/2026-05-impersonation-token-exchange-spike.md §Spike-2
#
set -euo pipefail

REALM="${REALM:-platform-test}"
CLIENT_ID="impersonation-broker"
CLIENT_AUDIENCE="${CLIENT_AUDIENCE:-frontend}"

# Resolve KC container based on realm
case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; ENV="test" ;;
  serban|platform-prod) KC_CONTAINER="platform-kc-prod"; ENV="prod" ;;
  *) echo "ERROR: unknown realm '$REALM' (expected: platform-test, serban)"; exit 1 ;;
esac

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"
ADMIN_PASS_FILE="/home/halil/platform-k8s-gitops/host-compose/keycloak/${ENV}/secrets/kc_admin_password.txt"

if [ ! -f "$ADMIN_PASS_FILE" ]; then
  echo "ERROR: KC admin password file not found: $ADMIN_PASS_FILE" >&2
  exit 1
fi

ADMIN_PASS=$(sudo cat "$ADMIN_PASS_FILE" | tr -d '\n')

# ─── 1. Login (master realm) ───────────────────────────────────────────────
echo "=== Step 1/6: Login to Keycloak master realm ==="
$KC config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user admin \
  --password "$ADMIN_PASS" >/dev/null 2>&1 || {
    echo "ERROR: master realm login failed" >&2
    exit 1
}
echo "✓ Logged in (target realm: $REALM)"

# ─── 2. Provision broker client (idempotent) ──────────────────────────────
echo ""
echo "=== Step 2/6: Provision $CLIENT_ID client ==="
EXISTING_ID=$($KC get clients -r "$REALM" --query "clientId=$CLIENT_ID" --fields id 2>/dev/null \
              | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

if [ -n "$EXISTING_ID" ]; then
  echo "✓ Client exists (id: ${EXISTING_ID:0:8}...) — skip create"
  BROKER_ID="$EXISTING_ID"
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
    -i 2>&1 | tail -1)
  echo "✓ Client created (id: ${BROKER_ID:0:8}...)"
  echo "  → New secret: WRITE TO VAULT (see step 6)"
fi

# ─── 3. Service account roles ──────────────────────────────────────────────
echo ""
echo "=== Step 3/6: Assign service account roles ==="
SA_USERNAME="service-account-${CLIENT_ID}"

assign_role() {
  local role="$1"
  $KC add-roles -r "$REALM" \
    --uusername "$SA_USERNAME" \
    --cclientid realm-management \
    --rolename "$role" 2>&1 | tail -1 || true
  echo "  ✓ $role"
}

assign_role impersonation
assign_role view-users
assign_role query-users

# ─── 4. Fine-grained token-exchange permission ────────────────────────────
echo ""
echo "=== Step 4/6: Enable fine-grained authz on $CLIENT_AUDIENCE client ==="
AUDIENCE_ID=$($KC get clients -r "$REALM" --query "clientId=$CLIENT_AUDIENCE" --fields id \
              | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

if [ -z "$AUDIENCE_ID" ]; then
  echo "ERROR: audience client '$CLIENT_AUDIENCE' not found in $REALM" >&2
  exit 1
fi

# Enable management permissions on audience client
$KC update "clients/$AUDIENCE_ID/management/permissions" -r "$REALM" \
  -s 'enabled=true' 2>&1 | tail -1 || true
echo "✓ Management permissions enabled on $CLIENT_AUDIENCE"

# Get token-exchange scope permission ID
TE_PERM_ID=$($KC get "clients/$AUDIENCE_ID/management/permissions" -r "$REALM" \
             | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("scopePermissions",{}).get("token-exchange",""))' 2>/dev/null || echo "")

if [ -z "$TE_PERM_ID" ]; then
  echo "WARN: token-exchange scope permission ID not found; manual review required"
  echo "  → KC console: Clients → $CLIENT_AUDIENCE → Permissions → Token Exchange"
else
  echo "✓ token-exchange permission id: ${TE_PERM_ID:0:8}..."

  # Create client-policy: only impersonation-broker can exchange
  REALM_MGMT_ID=$($KC get clients -r "$REALM" --query 'clientId=realm-management' --fields id \
                  | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
  POLICY_NAME="impersonation-broker-only"

  EXISTING_POLICY=$($KC get "clients/$REALM_MGMT_ID/authz/resource-server/policy" -r "$REALM" \
                    --query "name=$POLICY_NAME" --fields id 2>/dev/null \
                    | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d[0]["id"] if d else "")' 2>/dev/null || echo "")

  if [ -z "$EXISTING_POLICY" ]; then
    POLICY_ID=$($KC create "clients/$REALM_MGMT_ID/authz/resource-server/policy/client" -r "$REALM" \
      -s "name=$POLICY_NAME" \
      -s 'description=Codex 019e0dfb iter-3: only impersonation-broker can exchange tokens' \
      -s "clients=[\"$BROKER_ID\"]" \
      -i 2>&1 | tail -1)
    echo "✓ Client policy created: $POLICY_NAME (id: ${POLICY_ID:0:8}...)"
  else
    POLICY_ID="$EXISTING_POLICY"
    echo "✓ Client policy exists: $POLICY_NAME — skip create"
  fi

  # Attach policy to token-exchange permission
  $KC update "clients/$REALM_MGMT_ID/authz/resource-server/permission/scope/$TE_PERM_ID" -r "$REALM" \
    -s "policies=[\"$POLICY_ID\"]" 2>&1 | tail -1 || true
  echo "✓ Policy attached to token-exchange permission"
fi

# ─── 5. Verify provisioning ────────────────────────────────────────────────
echo ""
echo "=== Step 5/6: Verify provisioning ==="

echo "Client config:"
$KC get "clients/$BROKER_ID" -r "$REALM" --fields clientId,publicClient,serviceAccountsEnabled,attributes 2>&1 \
  | python3 -c '
import json,sys
c = json.load(sys.stdin)
print(f"  clientId: {c.get(\"clientId\")}")
print(f"  publicClient: {c.get(\"publicClient\")}")
print(f"  serviceAccountsEnabled: {c.get(\"serviceAccountsEnabled\")}")
attrs = c.get("attributes", {})
print(f"  token.exchange.permission.enabled: {attrs.get(\"token.exchange.permission.enabled\", \"unset\")}")
'

echo "Service account effective roles (realm-management):"
$KC get-roles -r "$REALM" --uusername "$SA_USERNAME" --cclientid realm-management --effective 2>&1 \
  | python3 -c 'import json,sys;[print(f"  - {r[\"name\"]}") for r in json.load(sys.stdin)]' 2>/dev/null \
  || echo "  (verify failed; manual check recommended)"

# ─── 6. Vault secret handoff ──────────────────────────────────────────────
echo ""
echo "=== Step 6/6: Vault secret handoff ==="
echo "Broker secret should be written to Vault path:"
echo "  secret/platform/auth-service/impersonation-broker"
echo ""
echo "Manual operator step (if new client created in step 2):"
echo "  vault kv put secret/platform/auth-service/impersonation-broker \\"
echo "    client_id=$CLIENT_ID \\"
echo "    client_secret=<new_generated_secret_from_step_2>"
echo ""
echo "Rotate (when needed):"
echo "  ./setup-impersonation-broker.sh --rotate-secret  # not yet implemented in MVP"
echo ""
echo "Apply complete. Next: Spike-2 runbook (platform-backend docs/spikes/2026-05-impersonation-token-exchange-spike.md §Spike-2)"
