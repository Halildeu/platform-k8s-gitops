#!/usr/bin/env bash
# Provision or rotate the dedicated Vault AppRole used by Graph mailbox helpers.
#
# This is an explicit operator/bootstrap action. It uses the Vault root token only
# in the remote shell, never emits it, and never installs it for routine helpers.
# Routine graph-mail-list/send calls authenticate with the generated AppRole files.

set -euo pipefail

SSH_HOST="${GRAPH_MAIL_VAULT_SSH_HOST:-aiadmin@aiserver}"
VAULT_CONTAINER="${GRAPH_MAIL_VAULT_CONTAINER:-platform-vault-prod}"
VAULT_ADDR="${GRAPH_MAIL_VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_INIT_FILE="${GRAPH_MAIL_VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-prod.json}"
APPROLE_DIR="${GRAPH_MAIL_VAULT_APPROLE_DIR:-/srv/platform/secrets/graph-mail-vault}"
POLICY_NAME="graph-mail-ops-ro"
ROLE_NAME="graph-mail-ops"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
POLICY_FILE="${REPO_ROOT}/config/vault/policies/graph-mail-ops-ro.hcl"

usage() {
    cat <<'EOF'
Usage: provision-graph-mail-vault-approle.sh [--ssh-host HOST]

Creates or rotates the dedicated graph-mail-ops AppRole on the production Vault.
The role is restricted to the Docker bridge source /32 and the exact
kv/data/platform/graph read path. Existing AppRole secret-id accessors are revoked
only after the new credential passes positive and negative authorization tests.

No root token, AppRole role-id, secret-id, Vault token, or Graph credential is output.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ ! -f "$POLICY_FILE" ]]; then
    echo "ERROR: policy file missing: $POLICY_FILE" >&2
    exit 1
fi

POLICY_B64=$(base64 < "$POLICY_FILE" | tr -d '\n')

ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_CONTAINER='${VAULT_CONTAINER}' VAULT_ADDR='${VAULT_ADDR}' VAULT_INIT_FILE='${VAULT_INIT_FILE}' APPROLE_DIR='${APPROLE_DIR}' POLICY_NAME='${POLICY_NAME}' ROLE_NAME='${ROLE_NAME}' POLICY_B64='${POLICY_B64}' bash -s" <<'EOSSH'
set -euo pipefail
umask 077

TMP_DIR=$(mktemp -d)
ROOT_TOKEN=""
APPROLE_TOKEN=""
NEW_SECRET_ID=""

cleanup() {
    local cleanup_rc=$?
    if [[ -n "$APPROLE_TOKEN" ]]; then
        printf 'header = "X-Vault-Token: %s"\n' "$APPROLE_TOKEN" |
            curl --config - -sS -o /dev/null -X POST \
                "${VAULT_ADDR}/v1/auth/token/revoke-self" || true
    fi
    rm -rf "$TMP_DIR"
    unset ROOT_TOKEN APPROLE_TOKEN NEW_SECRET_ID ROLE_ID
    exit "$cleanup_rc"
}
trap cleanup EXIT

ROOT_TOKEN=$(sudo -n jq -er '.root_token | select(type == "string" and length > 0)' \
    "$VAULT_INIT_FILE" 2>/dev/null) || {
    echo "ERROR: Vault bootstrap credential is unavailable" >&2
    exit 2
}

VAULT_GATEWAY=$(
    docker inspect "$VAULT_CONTAINER" |
        jq -r '.[0].NetworkSettings.Networks
            | to_entries
            | map(.value.Gateway)
            | map(select(type == "string" and length > 0))
            | first // empty'
)
if [[ ! "$VAULT_GATEWAY" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "ERROR: unable to derive the Vault container bridge gateway" >&2
    exit 2
fi
BOUND_CIDR="${VAULT_GATEWAY}/32"

root_request() {
    local method="$1"
    local path="$2"
    local data_file="${3:-}"
    local output_file="$4"
    local args=(-sS -o "$output_file" -w '%{http_code}' -X "$method")

    if [[ -n "$data_file" ]]; then
        args+=(-H "Content-Type: application/json" --data-binary "@${data_file}")
    fi
    printf 'header = "X-Vault-Token: %s"\n' "$ROOT_TOKEN" |
        curl --config - "${args[@]}" "${VAULT_ADDR}${path}"
}

approle_request() {
    local token="$1"
    local method="$2"
    local path="$3"
    local output_file="$4"
    printf 'header = "X-Vault-Token: %s"\n' "$token" |
        curl --config - -sS -o "$output_file" -w '%{http_code}' \
            -X "$method" "${VAULT_ADDR}${path}"
}

require_status() {
    local actual="$1"
    local expected="$2"
    local operation="$3"
    if [[ "$actual" != "$expected" ]]; then
        echo "ERROR: ${operation} returned HTTP ${actual}, expected ${expected}" >&2
        exit 2
    fi
}

POLICY_TEXT=$(printf '%s' "$POLICY_B64" | base64 -d)
jq -n --arg policy "$POLICY_TEXT" '{policy: $policy}' > "$TMP_DIR/policy.json"
STATUS=$(root_request PUT "/v1/sys/policies/acl/${POLICY_NAME}" \
    "$TMP_DIR/policy.json" "$TMP_DIR/policy-response.json")
require_status "$STATUS" "204" "policy write"

jq -n \
    --arg policy "$POLICY_NAME" \
    --arg cidr "$BOUND_CIDR" \
    '{
        bind_secret_id: true,
        secret_id_bound_cidrs: [$cidr],
        secret_id_num_uses: 0,
        secret_id_ttl: "768h",
        token_bound_cidrs: [$cidr],
        token_max_ttl: "30m",
        token_no_default_policy: true,
        token_num_uses: 3,
        token_policies: [$policy],
        token_ttl: "15m",
        token_type: "service"
    }' > "$TMP_DIR/role.json"
STATUS=$(root_request POST "/v1/auth/approle/role/${ROLE_NAME}" \
    "$TMP_DIR/role.json" "$TMP_DIR/role-response.json")
require_status "$STATUS" "204" "AppRole write"

# Capture only pre-existing accessors; they are destroyed after the new credential passes.
STATUS=$(root_request LIST "/v1/auth/approle/role/${ROLE_NAME}/secret-id" \
    "" "$TMP_DIR/old-accessors.json")
if [[ "$STATUS" != "200" && "$STATUS" != "404" ]]; then
    echo "ERROR: old secret-id accessor list returned HTTP ${STATUS}" >&2
    exit 2
fi

STATUS=$(root_request GET "/v1/auth/approle/role/${ROLE_NAME}/role-id" \
    "" "$TMP_DIR/role-id.json")
require_status "$STATUS" "200" "role-id read"
ROLE_ID=$(jq -er '.data.role_id | select(type == "string" and length > 0)' \
    "$TMP_DIR/role-id.json")

printf '{}' > "$TMP_DIR/empty.json"
STATUS=$(root_request POST "/v1/auth/approle/role/${ROLE_NAME}/secret-id" \
    "$TMP_DIR/empty.json" "$TMP_DIR/new-secret.json")
require_status "$STATUS" "200" "secret-id create"
NEW_SECRET_ID=$(jq -er '.data.secret_id | select(type == "string" and length > 0)' \
    "$TMP_DIR/new-secret.json")

jq -n --arg role_id "$ROLE_ID" --arg secret_id "$NEW_SECRET_ID" \
    '{role_id: $role_id, secret_id: $secret_id}' > "$TMP_DIR/login.json"
STATUS=$(curl -sS -o "$TMP_DIR/login-response.json" -w '%{http_code}' \
    -X POST -H "Content-Type: application/json" \
    --data-binary "@$TMP_DIR/login.json" \
    "${VAULT_ADDR}/v1/auth/approle/login")
require_status "$STATUS" "200" "AppRole login"

APPROLE_TOKEN=$(jq -er '.auth.client_token | select(type == "string" and length > 0)' \
    "$TMP_DIR/login-response.json")
LEASE_DURATION=$(jq -er '.auth.lease_duration' "$TMP_DIR/login-response.json")
POLICY_MATCH=$(jq -r --arg expected "$POLICY_NAME" \
    '((.auth.policies // []) == [$expected])
     and ((.auth.token_policies // []) == [$expected])' \
    "$TMP_DIR/login-response.json")
if [[ "$POLICY_MATCH" != "true" || ! "$LEASE_DURATION" =~ ^[0-9]+$ || \
      "$LEASE_DURATION" -lt 1 || "$LEASE_DURATION" -gt 1800 ]]; then
    echo "ERROR: AppRole login response violates policy or TTL contract" >&2
    exit 2
fi

STATUS=$(approle_request "$APPROLE_TOKEN" GET \
    "/v1/kv/data/platform/graph" "$TMP_DIR/graph.json")
require_status "$STATUS" "200" "allowed Graph KV read"
KEY_CONTRACT=$(jq -r '
    (.data.data // {}) as $d
    | (($d.graph_client_id // $d.client_id // "") | length > 0)
      and (($d.graph_client_secret // $d.client_secret // "") | length > 0)
      and (($d.graph_tenant_id // $d.tenant_id // "") | length > 0)
' "$TMP_DIR/graph.json")
if [[ "$KEY_CONTRACT" != "true" ]]; then
    echo "ERROR: Graph KV path is readable but required keys are absent" >&2
    exit 2
fi

STATUS=$(approle_request "$APPROLE_TOKEN" GET \
    "/v1/kv/data/platform/not-graph" "$TMP_DIR/denied-path.json")
require_status "$STATUS" "403" "out-of-scope KV read"

# Revoke the first validation token before a second login tests LIST denial.
printf 'header = "X-Vault-Token: %s"\n' "$APPROLE_TOKEN" |
    curl --config - -sS -o /dev/null -X POST \
        "${VAULT_ADDR}/v1/auth/token/revoke-self"
APPROLE_TOKEN=""

STATUS=$(curl -sS -o "$TMP_DIR/login-response-2.json" -w '%{http_code}' \
    -X POST -H "Content-Type: application/json" \
    --data-binary "@$TMP_DIR/login.json" \
    "${VAULT_ADDR}/v1/auth/approle/login")
require_status "$STATUS" "200" "second AppRole login"
APPROLE_TOKEN=$(jq -er '.auth.client_token | select(type == "string" and length > 0)' \
    "$TMP_DIR/login-response-2.json")

STATUS=$(approle_request "$APPROLE_TOKEN" LIST \
    "/v1/kv/metadata/platform" "$TMP_DIR/denied-list.json")
require_status "$STATUS" "403" "out-of-scope KV list"

sudo -n install -d -m 0700 -o root -g root "$APPROLE_DIR"
printf '%s\n' "$ROLE_ID" | sudo -n tee "${APPROLE_DIR}/role-id.new" >/dev/null
printf '%s\n' "$NEW_SECRET_ID" | sudo -n tee "${APPROLE_DIR}/secret-id.new" >/dev/null
sudo -n chown root:root "${APPROLE_DIR}/role-id.new" "${APPROLE_DIR}/secret-id.new"
sudo -n chmod 0400 "${APPROLE_DIR}/role-id.new" "${APPROLE_DIR}/secret-id.new"
sudo -n mv "${APPROLE_DIR}/role-id.new" "${APPROLE_DIR}/role-id"
sudo -n mv "${APPROLE_DIR}/secret-id.new" "${APPROLE_DIR}/secret-id"

if [[ "$STATUS" == "403" ]]; then
    while IFS= read -r accessor; do
        [[ -n "$accessor" ]] || continue
        jq -n --arg accessor "$accessor" '{secret_id_accessor: $accessor}' \
            > "$TMP_DIR/destroy-accessor.json"
        DESTROY_STATUS=$(root_request POST \
            "/v1/auth/approle/role/${ROLE_NAME}/secret-id-accessor/destroy" \
            "$TMP_DIR/destroy-accessor.json" "$TMP_DIR/destroy-response.json")
        require_status "$DESTROY_STATUS" "204" "old secret-id accessor destroy"
    done < <(jq -r '.data.keys[]? // empty' "$TMP_DIR/old-accessors.json")
fi

FILE_CONTRACT=$(
    sudo -n stat -c '%a:%U:%G' \
        "${APPROLE_DIR}/role-id" "${APPROLE_DIR}/secret-id" |
        sort -u
)
if [[ "$FILE_CONTRACT" != "400:root:root" ]]; then
    echo "ERROR: AppRole bootstrap files do not satisfy 0400 root:root" >&2
    exit 2
fi

jq -n \
    --arg role "$ROLE_NAME" \
    --arg policy "$POLICY_NAME" \
    --arg bound_cidr "$BOUND_CIDR" \
    --argjson token_ttl "$LEASE_DURATION" \
    --arg files "$FILE_CONTRACT" \
    '{
        status: "provisioned_and_verified",
        role: $role,
        policy: $policy,
        bound_cidr: $bound_cidr,
        token_ttl_seconds: $token_ttl,
        token_num_uses: 3,
        default_policy: false,
        allowed_path: "kv/data/platform/graph",
        denied_other_path: true,
        denied_list: true,
        bootstrap_files: $files
    }'
EOSSH
