#!/usr/bin/env bash
set -euo pipefail

# Apply and verify the Faz 22.6 remote-bridge ESO policy slice on the test
# Vault. The admin token is intentionally read from VAULT_TOKEN only; do not
# pass it as a command-line argument because argv leaks into shell/process logs.

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8301}"
VAULT_POLICY_NAME="${VAULT_POLICY_NAME:-eso-runtime}"
POLICY_FILE="${POLICY_FILE:-bootstrap/vault-policies/common/eso-runtime.hcl}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
ESO_NAMESPACE="${ESO_NAMESPACE:-external-secrets}"
CLUSTER_SECRET_STORE="${CLUSTER_SECRET_STORE:-vault-platform-gitops}"
ESO_SECRET_NAME="${ESO_SECRET_NAME:-vault-approle-secret}"
REMOTE_BRIDGE_VAULT_PATH="${REMOTE_BRIDGE_VAULT_PATH:-kv/data/platform/endpoint-admin-remote-bridge}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"

EXTERNAL_SECRETS=(
  endpoint-admin-remote-bridge-secrets
  endpoint-admin-remote-bridge-tls
  endpoint-admin-remote-bridge-signer
)

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

json_escape_file() {
  jq -Rs . < "$1"
}

vault_json() {
  local method="$1" path="$2" data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -sfS \
      -X "$method" \
      -H "X-Vault-Token: ${VAULT_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "$data" \
      "${VAULT_ADDR}/v1/${path}"
  else
    curl -sfS \
      -X "$method" \
      -H "X-Vault-Token: ${VAULT_TOKEN}" \
      "${VAULT_ADDR}/v1/${path}"
  fi
}

eso_login_token() {
  local role_id secret_id
  role_id="$(kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
    get clustersecretstore "$CLUSTER_SECRET_STORE" \
    -o jsonpath='{.spec.provider.vault.auth.appRole.roleId}')"
  secret_id="$(kubectl --context "$KUBE_CONTEXT" -n "$ESO_NAMESPACE" \
    get secret "$ESO_SECRET_NAME" \
    -o jsonpath='{.data.secret-id}' | base64 -d)"

  curl -sfS \
    -X POST \
    -H "Content-Type: application/json" \
    --data "$(jq -nc --arg role_id "$role_id" --arg secret_id "$secret_id" \
      '{role_id:$role_id, secret_id:$secret_id}')" \
    "${VAULT_ADDR}/v1/auth/approle/login" \
    | jq -r '.auth.client_token'
}

capabilities_for() {
  local token="$1" path="$2"
  curl -sfS \
    -X POST \
    -H "X-Vault-Token: ${token}" \
    -H "Content-Type: application/json" \
    --data "$(jq -nc --arg path "$path" '{paths:[$path]}')" \
    "${VAULT_ADDR}/v1/sys/capabilities-self" \
    | jq -r '.capabilities | join(",")'
}

ready_condition() {
  local name="$1"
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
    get externalsecret "$name" \
    -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}:{.reason}{end}' \
    2>/dev/null || true
}

force_external_secret_refresh() {
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  for name in "${EXTERNAL_SECRETS[@]}"; do
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
      annotate externalsecret "$name" "force-sync=${ts}" --overwrite >/dev/null
  done
}

wait_external_secrets_ready() {
  local deadline now all_ready name condition
  deadline=$(( $(date -u +%s) + READY_TIMEOUT_SECONDS ))

  while true; do
    all_ready=1
    for name in "${EXTERNAL_SECRETS[@]}"; do
      condition="$(ready_condition "$name")"
      printf 'ExternalSecret %s %s\n' "$name" "${condition:-no-ready-condition}"
      if [[ "$condition" != True:* ]]; then
        all_ready=0
      fi
    done

    if [[ "$all_ready" -eq 1 ]]; then
      return 0
    fi

    now="$(date -u +%s)"
    if (( now >= deadline )); then
      return 1
    fi
    sleep 10
  done
}

main() {
  local admin_caps payload eso_token eso_caps

  need_cmd curl
  need_cmd jq
  need_cmd kubectl

  [[ -n "${VAULT_TOKEN:-}" ]] || die "VAULT_TOKEN env var is required; do not pass tokens as argv"
  [[ -f "$POLICY_FILE" ]] || die "policy file not found: $POLICY_FILE"

  printf '=== Vault admin token capability precheck ===\n'
  vault_json GET auth/token/lookup-self >/dev/null \
    || die "VAULT_TOKEN lookup failed against ${VAULT_ADDR}"

  admin_caps="$(capabilities_for "$VAULT_TOKEN" "sys/policies/acl/${VAULT_POLICY_NAME}")"
  printf 'admin_caps sys/policies/acl/%s = %s\n' "$VAULT_POLICY_NAME" "$admin_caps"
  case ",$admin_caps," in
    *,root,*|*,sudo,*|*,create,*|*,update,*) ;;
    *) die "VAULT_TOKEN lacks policy write capability for ${VAULT_POLICY_NAME}" ;;
  esac

  printf '\n=== Apply policy source ===\n'
  payload="$(jq -nc --argjson policy "$(json_escape_file "$POLICY_FILE")" '{policy:$policy}')"
  vault_json PUT "sys/policies/acl/${VAULT_POLICY_NAME}" "$payload" >/dev/null
  printf 'policy_applied name=%s file=%s\n' "$VAULT_POLICY_NAME" "$POLICY_FILE"

  printf '\n=== ESO AppRole capability check ===\n'
  eso_token="$(eso_login_token)"
  eso_caps="$(capabilities_for "$eso_token" "$REMOTE_BRIDGE_VAULT_PATH")"
  printf 'eso_caps %s = %s\n' "$REMOTE_BRIDGE_VAULT_PATH" "$eso_caps"
  case ",$eso_caps," in
    *,read,*) ;;
    *) die "ESO AppRole still lacks read on ${REMOTE_BRIDGE_VAULT_PATH}" ;;
  esac

  printf '\n=== Force ExternalSecret refresh ===\n'
  force_external_secret_refresh
  if wait_external_secrets_ready; then
    printf '\nREMOTE_BRIDGE_ESO_POLICY_STATUS=ready\n'
  else
    printf '\nREMOTE_BRIDGE_ESO_POLICY_STATUS=not-ready\n'
    exit 2
  fi
}

main "$@"
