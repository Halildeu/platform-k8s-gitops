#!/usr/bin/env bash
set -euo pipefail

VAULT_INIT_FILE_DEFAULT="/srv/platform/secrets/backup-auth/vault-init-test.json"
# Host 53->15 tasinmasinda dosya yol DEGISTIRDI (silinmedi): eski konum
# ~/bootstrap-drill, yenisi /srv/platform/secrets/backup-auth (ACL ile
# script kullanicisina r--). Ikisini sirayla dene; ilk okunabilir kazanir.
[ -r "$VAULT_INIT_FILE_DEFAULT" ] || VAULT_INIT_FILE_DEFAULT="$HOME/bootstrap-drill/vault-init-test.json"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-$VAULT_INIT_FILE_DEFAULT}"

# Faz 22 #676 — endpoint-admin domain ops broker smoke.
#
# This self-hosted runner smoke proves the product-channel broker path without
# running raw remote shell on a Windows target. It intentionally expects the
# current pilot connector to fail closed as "connector-unavailable"; the pass
# condition is durable request state + redacted audit/result persistence.
#
# Secret hygiene:
# - never echo bearer tokens, Keycloak passwords, DB passwords, or raw
#   credentialRef values;
# - temp files are chmod 0600 and deleted by trap;
# - the emitted report contains only redacted status, hash prefixes, and
#   non-secret identifiers.

CTX="${CTX:-k3d-test}"
NS="${NS:-platform-test}"
DEPLOY="${DEPLOY:-endpoint-admin-service}"
CM="${CM:-endpoint-admin-service-config}"
API_BASE="${API_BASE:-https://testai.acik.com/api/v1/endpoint-admin}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
PERSONA_USERNAME="${PERSONA_USERNAME:-c5persona-admin-9001}"
TARGET_HOSTNAME="${TARGET_HOSTNAME:-ERP-MOBIL}"
OPERATION="${OPERATION:-CERT_AUTOENROLL_PULSE}"
TTL_SECONDS="${TTL_SECONDS:-300}"
CREDENTIAL_REF="${CREDENTIAL_REF:-delegated-worker:domain-ops/pilot}"
REPORT_PATH="${REPORT_PATH:-}"
EXPECTED_DOMAIN_OPS_FLAG="${EXPECTED_DOMAIN_OPS_FLAG:-true}"
EXPECTED_ROLLOUT_ANNOTATION="${EXPECTED_ROLLOUT_ANNOTATION:-2026-06-17-676}"
CONTRACT="${CONTRACT:-agent-198:max-permit-ttl-15m,mtls-only,no-raw-shell,credential-ref-only}"

TMP_DIR="$(mktemp -d)"
# Armed here, immediately after the temp dir exists, because a trap installed
# dozens of lines later leaves the KC admin password and admin JWT on disk
# whenever the script dies in between (measured 2026-07-31: three such
# directories were still present on the test host, dated 27-30 July).
# The body dispatches at FIRE time: once the full `cleanup` is defined it
# runs; before that — an early --help or validation exit — it still removes
# the temp dir instead of dying with "cleanup: command not found".
trap 'if declare -F cleanup >/dev/null 2>&1; then cleanup; else rm -rf "${TMP_DIR:-}"; fi' EXIT
RUNTIME_FILE="$TMP_DIR/runtime.json"
JWT_CLAIMS_FILE="$TMP_DIR/jwt-claims.json"
API_RESPONSE_FILE="$TMP_DIR/domain-ops-response.json"
API_RESPONSE_REDACTED_FILE="$TMP_DIR/domain-ops-response-redacted.json"
DB_REPORT_FILE="$TMP_DIR/db-report.json"
DEVICE_LIST_FILE="$TMP_DIR/devices.json"
REQUEST_FILE="$TMP_DIR/domain-ops-request.json"
AUTH_HEADER_FILE="$TMP_DIR/auth-header.txt"
KC_ADMIN_PASS_FILE="$TMP_DIR/kc-admin-password.txt"
KC_SOURCE_DIAG_FILE="$TMP_DIR/keycloak-source-diagnostics.json"
PERSONA_PASS_FILE="$TMP_DIR/persona-password.txt"
PERSONA_ROTATE_PASS_FILE="$TMP_DIR/persona-rotate-password.txt"
SMOKE_CLIENT_SECRET_FILE="$TMP_DIR/smoke-client-secret.txt"
RESET_BODY_FILE="$TMP_DIR/reset-password.json"
ROTATE_BODY_FILE="$TMP_DIR/rotate-password.json"
SQL_FILE="$TMP_DIR/domain-ops-smoke.sql"
PGPASS_FILE="$TMP_DIR/pgpass"
PORT_FORWARD_LOG="$TMP_DIR/postgres-port-forward.log"
K8S_PSQL_LOG="$TMP_DIR/kubernetes-psql.log"

KC_ADMIN_TOKEN=""
PERSONA_ID=""
OPERATION_ID=""
HTTP_STATUS=""
DEVICE_ID=""
PF_PID=""
K8S_PSQL_POD_NAME=""

echo '{}' > "$RUNTIME_FILE"
echo '{}' > "$JWT_CLAIMS_FILE"
echo '{}' > "$API_RESPONSE_REDACTED_FILE"
echo '{}' > "$DB_REPORT_FILE"
echo '{}' > "$KC_SOURCE_DIAG_FILE"
chmod 0600 "$TMP_DIR"/* 2>/dev/null || true

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: required command not found: $1" >&2
    exit 2
  }
}

write_report() {
  local verdict="$1"
  local reason="$2"

  if [[ -z "$REPORT_PATH" ]]; then
    return 0
  fi

  mkdir -p "$(dirname "$REPORT_PATH")"
  jq -n \
    --arg verdict "$verdict" \
    --arg reason "$reason" \
    --arg context "$CTX" \
    --arg namespace "$NS" \
    --arg deployment "$DEPLOY" \
    --arg configmap "$CM" \
    --arg apiBase "$API_BASE" \
    --arg targetHostname "$TARGET_HOSTNAME" \
    --arg operation "$OPERATION" \
    --arg ttlSeconds "$TTL_SECONDS" \
    --arg deviceId "${DEVICE_ID:-}" \
    --arg operationId "${OPERATION_ID:-}" \
    --arg httpStatus "${HTTP_STATUS:-}" \
    --arg contract "$CONTRACT" \
    --slurpfile runtime "$RUNTIME_FILE" \
    --slurpfile jwt "$JWT_CLAIMS_FILE" \
    --slurpfile api "$API_RESPONSE_REDACTED_FILE" \
    --slurpfile db "$DB_REPORT_FILE" \
    --slurpfile kcSource "$KC_SOURCE_DIAG_FILE" \
    '{
      verdict: $verdict,
      reason: $reason,
      context: $context,
      namespace: $namespace,
      deployment: $deployment,
      configmap: $configmap,
      apiBase: $apiBase,
      targetHostname: $targetHostname,
      operation: $operation,
      ttlSeconds: ($ttlSeconds | tonumber? // 0),
      deviceId: $deviceId,
      operationId: $operationId,
      httpStatus: ($httpStatus | tonumber? // null),
      contract: $contract,
      runtime: $runtime[0],
      keycloakCredentialSource: $kcSource[0],
      jwtClaims: $jwt[0],
      apiResponse: $api[0],
      db: $db[0]
    }' > "$REPORT_PATH"
}

cleanup() {
  set +e
  if [[ -n "$PF_PID" ]]; then
    kill "$PF_PID" >/dev/null 2>&1
    wait "$PF_PID" >/dev/null 2>&1
  fi
  if [[ -n "$K8S_PSQL_POD_NAME" ]]; then
    kubectl --context "$CTX" -n "$NS" delete pod "$K8S_PSQL_POD_NAME" \
      --ignore-not-found >/dev/null 2>&1 || true
  fi
  if [[ -n "$KC_ADMIN_TOKEN" && -n "$PERSONA_ID" ]]; then
    openssl rand -base64 32 | tr -d '\n' > "$PERSONA_ROTATE_PASS_FILE" 2>/dev/null
    chmod 0600 "$PERSONA_ROTATE_PASS_FILE" 2>/dev/null
    jq -n --rawfile value "$PERSONA_ROTATE_PASS_FILE" \
      '{type:"password", value:$value, temporary:false}' > "$ROTATE_BODY_FILE" 2>/dev/null
    curl -sS -o /dev/null -X PUT \
      "$KC_BASE_URL/admin/realms/$KC_REALM/users/$PERSONA_ID/reset-password" \
      -H "Authorization: Bearer $KC_ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      --data-binary "@$ROTATE_BODY_FILE" >/dev/null 2>&1
  fi
  KC_ADMIN_TOKEN=""
  rm -rf "$TMP_DIR"
}

fail() {
  local reason="$1"
  write_report "FAIL" "$reason"
  echo "FAIL: $reason" >&2
  exit 1
}

pass() {
  local reason="$1"
  write_report "PASS" "$reason"
  echo "PASS: $reason"
}

keycloak_admin_password_candidates() {
  printf '%s\t%s\n' \
    "canonical-home-repo" "/home/halil/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "canonical-home-compose" "/home/halil/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "runner-home-compose" "$HOME/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "checkout-absolute" "$PWD/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "checkout-relative" "host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "github-work" "/home/runner/work/platform-k8s-gitops/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "github-work-underscore" "/home/runner/_work/platform-k8s-gitops/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "opt-repo" "/opt/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    "srv-repo" "/srv/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt" \
    | awk -F '\t' 'NF >= 2 && !seen[$2]++'
}

write_keycloak_source_diagnostics() {
  local selected_source="${1:-}"
  local selected_label="${2:-}"
  local candidates_file="$TMP_DIR/keycloak-source-candidates.jsonl"
  local docker_available=false
  local docker_container_found=false
  local docker_run_secret_readable=false
  local docker_env_secret_readable=false
  local docker_socket_present=false
  local docker_socket_readable=false
  local docker_socket_writable=false
  local actions_secret_present=false
  local label candidate exists readable

  : > "$candidates_file"
  while IFS=$'\t' read -r label candidate; do
    exists=false
    readable=false
    [[ -e "$candidate" ]] && exists=true
    [[ -r "$candidate" ]] && readable=true
    jq -n \
      --arg candidateLabel "$label" \
      --argjson exists "$exists" \
      --argjson readable "$readable" \
      '{"label": $candidateLabel, exists: $exists, readable: $readable}' >> "$candidates_file"
  done < <(keycloak_admin_password_candidates)

  command -v docker >/dev/null 2>&1 && docker_available=true
  [[ -e /var/run/docker.sock ]] && docker_socket_present=true
  [[ -r /var/run/docker.sock ]] && docker_socket_readable=true
  [[ -w /var/run/docker.sock ]] && docker_socket_writable=true
  [[ -n "${KC_ADMIN_PASSWORD:-}" ]] && actions_secret_present=true

  if [[ "$docker_available" == "true" ]]; then
    if docker inspect "$KC_CONTAINER" >/dev/null 2>&1; then
      docker_container_found=true
    fi
    if docker exec "$KC_CONTAINER" sh -c 'test -r /run/secrets/kc_admin_password' >/dev/null 2>&1; then
      docker_run_secret_readable=true
    fi
    if docker exec "$KC_CONTAINER" sh -c 'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && test -r "$p"' >/dev/null 2>&1; then
      docker_env_secret_readable=true
    fi
  fi

  jq -n \
    --arg selectedSource "$selected_source" \
    --arg selectedLabel "$selected_label" \
    --arg kcContainer "$KC_CONTAINER" \
    --arg kcBaseUrl "$KC_BASE_URL" \
    --arg kcRealm "$KC_REALM" \
    --argjson dockerAvailable "$docker_available" \
    --argjson dockerContainerFound "$docker_container_found" \
    --argjson dockerRunSecretReadable "$docker_run_secret_readable" \
    --argjson dockerEnvSecretReadable "$docker_env_secret_readable" \
    --argjson dockerSocketPresent "$docker_socket_present" \
    --argjson dockerSocketReadable "$docker_socket_readable" \
    --argjson dockerSocketWritable "$docker_socket_writable" \
    --argjson actionsSecretPresent "$actions_secret_present" \
    --slurpfile candidates "$candidates_file" \
    '{
      selectedSource: $selectedSource,
      selectedLabel: $selectedLabel,
      keycloak: {
        container: $kcContainer,
        baseUrl: $kcBaseUrl,
        realm: $kcRealm
      },
      docker: {
        available: $dockerAvailable,
        containerFound: $dockerContainerFound,
        runSecretReadable: $dockerRunSecretReadable,
        envSecretReadable: $dockerEnvSecretReadable,
        socketPresent: $dockerSocketPresent,
        socketReadable: $dockerSocketReadable,
        socketWritable: $dockerSocketWritable
      },
      actionsSecretPresent: $actionsSecretPresent,
      hostFileCandidates: $candidates
    }' > "$KC_SOURCE_DIAG_FILE"
  chmod 0600 "$KC_SOURCE_DIAG_FILE"
}

read_keycloak_admin_password() {
  if [[ -n "${KC_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$KC_ADMIN_PASSWORD" > "$KC_ADMIN_PASS_FILE"
    chmod 0600 "$KC_ADMIN_PASS_FILE"
    write_keycloak_source_diagnostics "actions-secret" "KC_TEST_ADMIN_PASSWORD"
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker exec "$KC_CONTAINER" sh -c 'cat /run/secrets/kc_admin_password' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null && [[ -s "$KC_ADMIN_PASS_FILE" ]]; then
      chmod 0600 "$KC_ADMIN_PASS_FILE"
      write_keycloak_source_diagnostics "docker-run-secret" "run-secret"
      return 0
    fi
    if docker exec "$KC_CONTAINER" sh -c 'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && cat "$p"' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null && [[ -s "$KC_ADMIN_PASS_FILE" ]]; then
      chmod 0600 "$KC_ADMIN_PASS_FILE"
      write_keycloak_source_diagnostics "docker-env-secret" "env-secret"
      return 0
    fi
  fi

  local label candidate
  while IFS=$'\t' read -r label candidate; do
    if [[ -r "$candidate" ]]; then
      cp "$candidate" "$KC_ADMIN_PASS_FILE"
      chmod 0600 "$KC_ADMIN_PASS_FILE"
      write_keycloak_source_diagnostics "host-file" "$label"
      return 0
    fi
  done < <(keycloak_admin_password_candidates)

  write_keycloak_source_diagnostics "" ""
  fail "Keycloak admin password source not found for test realm"
}

token_field() {
  jq -r '.access_token // empty'
}

mint_keycloak_admin_token() {
  local token_response
  token_response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=$KC_ADMIN_USER" \
    --data-urlencode "password@$KC_ADMIN_PASS_FILE")" \
    || fail "Keycloak admin token request failed"

  KC_ADMIN_TOKEN="$(printf '%s' "$token_response" | token_field)"
  [[ -n "$KC_ADMIN_TOKEN" ]] || fail "Keycloak admin token response did not contain access_token"
}

resolve_persona_id() {
  local user_response
  user_response="$(curl -sS \
    "$KC_BASE_URL/admin/realms/$KC_REALM/users?username=$PERSONA_USERNAME&exact=true" \
    -H "Authorization: Bearer $KC_ADMIN_TOKEN")" \
    || fail "Keycloak persona lookup failed"

  PERSONA_ID="$(printf '%s' "$user_response" | jq -r '.[0].id // empty')"
  [[ -n "$PERSONA_ID" ]] || fail "Keycloak persona not found: $PERSONA_USERNAME"
}

reset_persona_password() {
  openssl rand -base64 32 | tr -d '\n' > "$PERSONA_PASS_FILE"
  chmod 0600 "$PERSONA_PASS_FILE"
  jq -n --rawfile value "$PERSONA_PASS_FILE" \
    '{type:"password", value:$value, temporary:false}' > "$RESET_BODY_FILE"
  chmod 0600 "$RESET_BODY_FILE"

  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' -X PUT \
    "$KC_BASE_URL/admin/realms/$KC_REALM/users/$PERSONA_ID/reset-password" \
    -H "Authorization: Bearer $KC_ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    --data-binary "@$RESET_BODY_FILE")" \
    || fail "Keycloak persona password reset failed"
  [[ "$status" == "204" ]] || fail "Keycloak persona password reset returned HTTP $status"
}

fetch_smoke_client_secret() {
  # A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover).
  # Vault kv/platform/keycloak/smoke-client (A2a); scope-mapping + audience×6 (A2b.1 setup-smoke-token-contract.sh).
  local vault_root_token
  vault_root_token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")" \
    || fail "smoke-client secret için vault root token okunamadı"
  docker exec -e VAULT_TOKEN="$vault_root_token" platform-vault-test \
    vault kv get -field=client_secret kv/platform/keycloak/smoke-client > "$SMOKE_CLIENT_SECRET_FILE" \
    || fail "smoke-client secret Vault'tan alınamadı (kv/platform/keycloak/smoke-client — A2a seed edilmiş olmalı)"
  chmod 0600 "$SMOKE_CLIENT_SECRET_FILE"
  vault_root_token=""
  [[ -s "$SMOKE_CLIENT_SECRET_FILE" ]] || fail "smoke-client secret dosyası boş"
}

mint_persona_token() {
  fetch_smoke_client_secret
  local token_response persona_token
  token_response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=smoke-client" \
    --data-urlencode "client_secret@$SMOKE_CLIENT_SECRET_FILE" \
    --data-urlencode "username=$PERSONA_USERNAME" \
    --data-urlencode "password@$PERSONA_PASS_FILE")" \
    || fail "Keycloak persona token request failed"

  persona_token="$(printf '%s' "$token_response" | token_field)"
  [[ -n "$persona_token" ]] || fail "Keycloak persona token response did not contain access_token"
  printf 'Authorization: Bearer %s\n' "$persona_token" > "$AUTH_HEADER_FILE"
  chmod 0600 "$AUTH_HEADER_FILE"

  python3 - "$AUTH_HEADER_FILE" "$JWT_CLAIMS_FILE" <<'PY'
import base64
import json
import sys

header_path, out_path = sys.argv[1:3]
header = open(header_path, encoding="utf-8").read().strip()
token = header.removeprefix("Authorization: Bearer ").strip()
parts = token.split(".")
if len(parts) < 2:
    raise SystemExit("invalid JWT shape")
payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
realm_roles = payload.get("realm_access", {}).get("roles", [])
data = {
    "subPresent": bool(payload.get("sub")),
    "preferredUsername": payload.get("preferred_username"),
    "emailVerified": payload.get("email_verified"),
    "userId": payload.get("userId") or payload.get("user_id"),
    "realmRolesContainEndpointAdmin": "ENDPOINT_ADMIN" in realm_roles,
    "aud": payload.get("aud"),
    "issuerPresent": bool(payload.get("iss")),
    "expiresAtEpoch": payload.get("exp"),
}
open(out_path, "w", encoding="utf-8").write(json.dumps(data, sort_keys=True, indent=2) + "\n")
PY
}

verify_runtime_flag() {
  echo "== endpoint-admin runtime flag =="
  kubectl --context "$CTX" -n "$NS" get deploy "$DEPLOY" >/dev/null \
    || fail "deployment not found: $NS/$DEPLOY"
  kubectl --context "$CTX" -n "$NS" rollout status "deploy/$DEPLOY" --timeout=180s

  local cm_flag pod_env pod_flag annotation image_id
  cm_flag="$(kubectl --context "$CTX" -n "$NS" get cm "$CM" \
    -o jsonpath='{.data.ENDPOINT_ADMIN_DOMAIN_OPS_ENABLED}' 2>/dev/null || true)"
  pod_env="$(kubectl --context "$CTX" -n "$NS" exec "deploy/$DEPLOY" -- printenv)"
  pod_flag="$(printf '%s\n' "$pod_env" | sed -n 's/^ENDPOINT_ADMIN_DOMAIN_OPS_ENABLED=//p' | head -1)"
  annotation="$(kubectl --context "$CTX" -n "$NS" get deploy "$DEPLOY" \
    -o jsonpath='{.spec.template.metadata.annotations.endpoint-admin\.acik\.com/domain-ops-acceptance-rev}' 2>/dev/null || true)"
  image_id="$(kubectl --context "$CTX" -n "$NS" get pod \
    -l app.kubernetes.io/name="$DEPLOY" \
    -o jsonpath='{.items[0].status.containerStatuses[0].imageID}' 2>/dev/null || true)"

  jq -n \
    --arg configFlag "$cm_flag" \
    --arg podFlag "$pod_flag" \
    --arg rolloutAnnotation "$annotation" \
    --arg imageID "$image_id" \
    '{
      domainOpsConfigFlag: $configFlag,
      domainOpsPodFlag: $podFlag,
      rolloutAnnotation: $rolloutAnnotation,
      imageID: $imageID
    }' > "$RUNTIME_FILE"

  [[ "$cm_flag" == "$EXPECTED_DOMAIN_OPS_FLAG" ]] \
    || fail "ConfigMap ENDPOINT_ADMIN_DOMAIN_OPS_ENABLED=$cm_flag"
  [[ "$pod_flag" == "$EXPECTED_DOMAIN_OPS_FLAG" ]] \
    || fail "pod ENDPOINT_ADMIN_DOMAIN_OPS_ENABLED=$pod_flag"
  [[ "$annotation" == "$EXPECTED_ROLLOUT_ANNOTATION" ]] \
    || fail "rollout annotation mismatch: $annotation"
}

resolve_target_device() {
  echo "== endpoint-admin device lookup =="
  local status target_upper
  status="$(curl -skS -o "$DEVICE_LIST_FILE" -w '%{http_code}' \
    -H "@$AUTH_HEADER_FILE" \
    "$API_BASE/endpoint-devices")" \
    || fail "endpoint device list request failed"
  [[ "$status" == "200" ]] || fail "endpoint device list returned HTTP $status"

  target_upper="$(printf '%s' "$TARGET_HOSTNAME" | tr '[:lower:]' '[:upper:]')"
  DEVICE_ID="$(jq -r --arg target "$target_upper" '
    def rows:
      if type == "array" then .[]
      else (.content[]?, .items[]?, .data[]?, .devices[]?)
      end;
    rows
    | select(((.hostname // .hostName // .displayName // .name // "") | ascii_upcase) == $target)
    | .id
  ' "$DEVICE_LIST_FILE" | head -1)"

  [[ -n "$DEVICE_ID" && "$DEVICE_ID" != "null" ]] \
    || fail "target endpoint device not found in API list: $TARGET_HOSTNAME"
  [[ "$DEVICE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] \
    || fail "target endpoint device id is not a UUID: $DEVICE_ID"
}

create_domain_ops_request() {
  echo "== endpoint-admin domain ops request =="
  [[ "$TTL_SECONDS" =~ ^[0-9]+$ ]] || fail "TTL_SECONDS must be numeric"
  if (( TTL_SECONDS <= 0 || TTL_SECONDS > 900 )); then
    fail "TTL_SECONDS must be between 1 and 900"
  fi

  local idempotency_key reason
  idempotency_key="codex-676-${GITHUB_RUN_ID:-manual}-$(date -u +%Y%m%dT%H%M%SZ)"
  reason="Codex #676 product-channel smoke: durable domain ops broker request path without raw credentials"
  jq -n \
    --arg operation "$OPERATION" \
    --arg reason "$reason" \
    --arg idempotencyKey "$idempotency_key" \
    --arg credentialRef "$CREDENTIAL_REF" \
    --argjson ttl "$TTL_SECONDS" \
    '{
      operation: $operation,
      reason: $reason,
      ttlSeconds: $ttl,
      idempotencyKey: $idempotencyKey,
      credentialRef: $credentialRef
    }' > "$REQUEST_FILE"
  chmod 0600 "$REQUEST_FILE"

  HTTP_STATUS="$(curl -skS -o "$API_RESPONSE_FILE" -w '%{http_code}' -X POST \
    -H "@$AUTH_HEADER_FILE" \
    -H "Content-Type: application/json" \
    --data-binary "@$REQUEST_FILE" \
    "$API_BASE/endpoint-devices/$DEVICE_ID/domain-ops")" \
    || fail "domain ops POST failed"

  if [[ "$HTTP_STATUS" != "200" ]]; then
    jq -n \
      --arg httpStatus "$HTTP_STATUS" \
      '{httpStatus: ($httpStatus | tonumber? // null), responseBodyRedacted: true}' \
      > "$API_RESPONSE_REDACTED_FILE"
    fail "domain ops POST returned HTTP $HTTP_STATUS"
  fi

  OPERATION_ID="$(jq -r '.operationId // empty' "$API_RESPONSE_FILE")"
  [[ "$OPERATION_ID" =~ ^[0-9a-fA-F-]{36}$ ]] \
    || fail "domain ops response did not contain UUID operationId"

  local response_status reason_code connector_name response_ttl
  response_status="$(jq -r '.status // empty' "$API_RESPONSE_FILE")"
  reason_code="$(jq -r '.reasonCode // empty' "$API_RESPONSE_FILE")"
  connector_name="$(jq -r '.connectorName // empty' "$API_RESPONSE_FILE")"
  response_ttl="$(jq -r '.ttlSeconds // empty' "$API_RESPONSE_FILE")"

  jq '{
    operationId,
    tenantId,
    deviceId,
    operation,
    status,
    reasonCode,
    ttlSeconds,
    requestedBy,
    createdAt,
    expiresAt,
    connectorName,
    connectorAttemptId
  }' "$API_RESPONSE_FILE" > "$API_RESPONSE_REDACTED_FILE"

  [[ "$response_status" == "FAILED" ]] \
    || fail "domain ops response status was $response_status, expected FAILED"
  [[ "$reason_code" == "connector-unavailable" ]] \
    || fail "domain ops response reasonCode was $reason_code, expected connector-unavailable"
  [[ "$connector_name" == "unavailable" ]] \
    || fail "domain ops response connectorName was $connector_name, expected unavailable"
  [[ "$response_ttl" == "$TTL_SECONDS" ]] \
    || fail "domain ops response ttlSeconds was $response_ttl, expected $TTL_SECONDS"
}

parse_jdbc_url() {
  python3 - "$1" <<'PY'
import re
import sys
url = sys.argv[1]
m = re.match(r"^jdbc:postgresql://([^/:?]+)(?::([0-9]+))?/([^?]+)", url)
if not m:
    raise SystemExit("invalid jdbc postgresql url")
print("\t".join([m.group(1), m.group(2) or "5432", m.group(3)]))
PY
}

pgpass_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/:/\\:/g'
}

find_free_local_port() {
  python3 - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

resolve_postgres_runner_target() {
  local service_host="$1"
  local service_port="$2"
  local endpoint_ip endpoint_port

  endpoint_ip="$(kubectl --context "$CTX" -n "$NS" get endpoints "$service_host" \
    -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)"
  endpoint_port="$(kubectl --context "$CTX" -n "$NS" get endpoints "$service_host" \
    -o jsonpath='{.subsets[0].ports[0].port}' 2>/dev/null || true)"

  if [[ -n "$endpoint_ip" && -n "$endpoint_port" ]]; then
    printf '%s\t%s\tservice-endpoint\n' "$endpoint_ip" "$endpoint_port"
    return 0
  fi

  printf '%s\t%s\tjdbc-host\n' "$service_host" "$service_port"
}

start_postgres_port_forward() {
  local remote_port="$1"
  local local_port
  local_port="$(find_free_local_port)"
  kubectl --context "$CTX" -n "$NS" port-forward "svc/postgres" "${local_port}:${remote_port}" \
    > "$PORT_FORWARD_LOG" 2>&1 &
  PF_PID="$!"

  for _ in $(seq 1 60); do
    if (echo >"/dev/tcp/127.0.0.1/${local_port}") >/dev/null 2>&1; then
      printf '%s' "$local_port"
      return 0
    fi
    if ! kill -0 "$PF_PID" >/dev/null 2>&1; then
      fail "postgres port-forward exited before becoming ready"
    fi
    sleep 0.5
  done

  fail "postgres port-forward did not become ready"
}

run_kubernetes_psql_query() {
  local db_host="$1"
  local db_port="$2"
  local db_name="$3"
  local db_user="$4"
  local db_pass_pgpass="$5"
  local sql_file="$6"
  local output pod_name pod_overrides status

  pod_name="domain-ops-psql-${GITHUB_RUN_ID:-manual}-$$"
  pod_overrides="$(jq -cn \
    --arg name "$pod_name" \
    --arg image "postgres:16-alpine" \
    --arg pgHost "$db_host" \
    --arg pgPort "$db_port" \
    --arg pgDatabase "$db_name" \
    --arg pgUser "$db_user" \
    '{
    apiVersion: "v1",
    metadata: {
      labels: {
        "app.kubernetes.io/name": "endpoint-admin-domain-ops-smoke",
        "app.kubernetes.io/component": "ci-smoke",
        "app.kubernetes.io/part-of": "platform"
      }
    },
    spec: {
      securityContext: {
        runAsNonRoot: true,
        runAsUser: 999,
        runAsGroup: 999,
        fsGroup: 999,
        seccompProfile: {type: "RuntimeDefault"}
      },
      containers: [
        {
          name: $name,
          image: $image,
          imagePullPolicy: "IfNotPresent",
          env: [
            {name: "PGHOST", value: $pgHost},
            {name: "PGPORT", value: $pgPort},
            {name: "PGDATABASE", value: $pgDatabase},
            {name: "PGUSER", value: $pgUser},
            {name: "PGCONNECT_TIMEOUT", value: "5"}
          ],
          command: ["sleep"],
          args: ["300"],
          securityContext: {
            allowPrivilegeEscalation: false,
            capabilities: {drop: ["ALL"]},
            runAsNonRoot: true
          }
        }
      ]
    }
  }')"
  kubectl --context "$CTX" -n "$NS" delete pod "$pod_name" \
    --ignore-not-found >/dev/null 2>&1 || true

  K8S_PSQL_POD_NAME="$pod_name"

  if ! kubectl --context "$CTX" -n "$NS" run "$pod_name" \
      --restart=Never \
      --pod-running-timeout=120s \
      --image=postgres:16-alpine \
      --image-pull-policy=IfNotPresent \
      --overrides="$pod_overrides" \
      >"$K8S_PSQL_LOG" 2>&1; then
    sed 's/[[:cntrl:]]//g' "$K8S_PSQL_LOG" >&2 || true
    return 1
  fi

  if ! kubectl --context "$CTX" -n "$NS" wait "pod/$pod_name" \
      --for=condition=Ready \
      --timeout=120s \
      >>"$K8S_PSQL_LOG" 2>&1; then
    kubectl --context "$CTX" -n "$NS" describe pod "$pod_name" \
      >>"$K8S_PSQL_LOG" 2>&1 || true
    kubectl --context "$CTX" -n "$NS" logs "$pod_name" \
      >>"$K8S_PSQL_LOG" 2>&1 || true
    sed 's/[[:cntrl:]]//g' "$K8S_PSQL_LOG" >&2 || true
    return 1
  fi

  set +e
  # shellcheck disable=SC2016
  output="$(
    {
      printf '%s:%s:%s:%s:%s\n' "$db_host" "$db_port" "$db_name" "$db_user" "$db_pass_pgpass"
      cat "$sql_file"
    } | kubectl --context "$CTX" -n "$NS" exec -i "$pod_name" -- sh -c '
      set -eu
      IFS= read -r pgpass
      printf "%s\n" "$pgpass" > /tmp/pgpass
      chmod 600 /tmp/pgpass
      cat > /tmp/domain-ops-smoke.sql
      export PGPASSFILE=/tmp/pgpass
      psql -tA -v ON_ERROR_STOP=1 -f /tmp/domain-ops-smoke.sql
    ' 2>>"$K8S_PSQL_LOG"
  )"
  status=$?
  kubectl --context "$CTX" -n "$NS" delete pod "$pod_name" \
    --ignore-not-found >/dev/null 2>&1 || true
  K8S_PSQL_POD_NAME=""
  set -e

  if (( status != 0 )); then
    sed 's/[[:cntrl:]]//g' "$K8S_PSQL_LOG" >&2 || true
    return "$status"
  fi

  printf '%s\n' "$output"
}

run_psql_json_query() {
  local db_url db_user db_pass db_schema db_host db_port db_name parsed
  local psql_output local_port connect_host connect_port connect_source connect_target
  local db_pass_pgpass
  local pod_env

  pod_env="$(kubectl --context "$CTX" -n "$NS" exec "deploy/$DEPLOY" -- printenv)"
  db_url="$(printf '%s\n' "$pod_env" | sed -n 's/^SPRING_DATASOURCE_URL=//p' | head -1)"
  db_user="$(printf '%s\n' "$pod_env" | sed -n 's/^SPRING_DATASOURCE_USERNAME=//p' | head -1)"
  db_pass="$(printf '%s\n' "$pod_env" | sed -n 's/^SPRING_DATASOURCE_PASSWORD=//p' | head -1)"
  db_schema="$(printf '%s\n' "$pod_env" | sed -n 's/^ENDPOINT_ADMIN_DB_SCHEMA=//p' | head -1)"
  db_schema="${db_schema:-endpoint_admin_service}"

  [[ -n "$db_url" && -n "$db_user" && -n "$db_pass" ]] \
    || fail "endpoint-admin DB environment is incomplete"
  [[ "$db_schema" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
    || fail "endpoint-admin DB schema has invalid shape"
  [[ "$OPERATION_ID" =~ ^[0-9a-fA-F-]{36}$ ]] \
    || fail "operation id is not a UUID before DB lookup"

  parsed="$(parse_jdbc_url "$db_url")" || fail "could not parse endpoint-admin JDBC URL"
  IFS=$'\t' read -r db_host db_port db_name <<< "$parsed"
  [[ "$db_host" == "postgres" ]] \
    || fail "unexpected endpoint-admin DB host for smoke evidence query: $db_host"
  connect_target="$(resolve_postgres_runner_target "$db_host" "$db_port")"
  IFS=$'\t' read -r connect_host connect_port connect_source <<< "$connect_target"
  db_pass_pgpass="$(pgpass_escape "$db_pass")"

  cat > "$SQL_FILE" <<SQL
WITH req AS (
  SELECT *
  FROM ${db_schema}.endpoint_domain_ops_requests
  WHERE id = '${OPERATION_ID}'::uuid
),
audit AS (
  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'event_type', event_type,
        'action', action,
        'correlation_id', correlation_id,
        'status', metadata->>'status',
        'reasonCode', metadata->>'reasonCode',
        'credentialRefPresent', metadata->>'credentialRefPresent',
        'credentialRefAccepted', metadata->>'credentialRefAccepted',
        'credentialRefHashPrefix', left(coalesce(metadata->>'credentialRefHash',''),16),
        'idempotencyKeyHashPrefix', left(coalesce(metadata->>'idempotencyKeyHash',''),16),
        'maxPermitTtlSeconds', metadata->>'maxPermitTtlSeconds',
        'contract', metadata->>'contract'
      )
      ORDER BY occurred_at
    ),
    '[]'::jsonb
  ) AS events
  FROM ${db_schema}.endpoint_audit_events
  WHERE correlation_id = '${OPERATION_ID}'
)
SELECT jsonb_build_object(
  'request', jsonb_build_object(
    'id', r.id,
    'operation', r.operation,
    'state', r.state,
    'reasonCode', r.reason_code,
    'ttlSeconds', r.ttl_seconds,
    'credentialRefPresent', r.credential_ref IS NOT NULL,
    'credentialRefHashPrefix', left(coalesce(r.credential_ref_hash,''),16),
    'idempotencyKeyHashPrefix', left(coalesce(r.idempotency_key_hash,''),16),
    'connectorName', r.connector_name,
    'connectorAttemptId', r.connector_attempt_id,
    'redactedResult', r.redacted_result,
    'requestedBy', r.requested_by,
    'completedAtPresent', r.completed_at IS NOT NULL
  ),
  'auditEvents', audit.events
)::text
FROM req r
CROSS JOIN audit;
SQL
  chmod 0600 "$SQL_FILE"

  printf '%s:%s:%s:%s:%s\n' "$connect_host" "$connect_port" "$db_name" "$db_user" "$db_pass_pgpass" > "$PGPASS_FILE"
  chmod 0600 "$PGPASS_FILE"

  if command -v psql >/dev/null 2>&1; then
    psql_output="$(PGPASSFILE="$PGPASS_FILE" PGCONNECT_TIMEOUT=5 psql \
      -h "$connect_host" \
      -p "$connect_port" \
      -U "$db_user" \
      -d "$db_name" \
      -tA \
      -v ON_ERROR_STOP=1 \
      -f "$SQL_FILE")" \
      || {
        if [[ "$connect_source" == "service-endpoint" ]]; then
          fail "psql direct query failed via postgres service endpoint"
        fi
        local_port="$(start_postgres_port_forward "$db_port")"
        printf '127.0.0.1:%s:%s:%s:%s\n' "$local_port" "$db_name" "$db_user" "$db_pass_pgpass" > "$PGPASS_FILE"
        chmod 0600 "$PGPASS_FILE"
        psql_output="$(PGPASSFILE="$PGPASS_FILE" PGCONNECT_TIMEOUT=5 psql \
          -h "127.0.0.1" \
          -p "$local_port" \
          -U "$db_user" \
          -d "$db_name" \
          -tA \
          -v ON_ERROR_STOP=1 \
          -f "$SQL_FILE")" \
          || fail "psql query failed"
      }
  elif command -v docker >/dev/null 2>&1; then
    psql_output="$(docker run --rm -i \
      --network host \
      -v "$SQL_FILE:/tmp/domain-ops-smoke.sql:ro" \
      -v "$PGPASS_FILE:/tmp/pgpass:ro" \
      -e PGPASSFILE=/tmp/pgpass \
      -e PGCONNECT_TIMEOUT=5 \
      postgres:16-alpine \
      psql \
        -h "$connect_host" \
        -p "$connect_port" \
        -U "$db_user" \
        -d "$db_name" \
        -tA \
        -v ON_ERROR_STOP=1 \
        -f /tmp/domain-ops-smoke.sql)" \
      || {
        if [[ "$connect_source" == "service-endpoint" ]]; then
          fail "dockerized psql direct query failed via postgres service endpoint"
        fi
        local_port="$(start_postgres_port_forward "$db_port")"
        printf '127.0.0.1:%s:%s:%s:%s\n' "$local_port" "$db_name" "$db_user" "$db_pass_pgpass" > "$PGPASS_FILE"
        chmod 0600 "$PGPASS_FILE"
        psql_output="$(docker run --rm -i \
          --network host \
          -v "$SQL_FILE:/tmp/domain-ops-smoke.sql:ro" \
          -v "$PGPASS_FILE:/tmp/pgpass:ro" \
          -e PGPASSFILE=/tmp/pgpass \
          -e PGCONNECT_TIMEOUT=5 \
          postgres:16-alpine \
          psql \
            -h "127.0.0.1" \
            -p "$local_port" \
            -U "$db_user" \
            -d "$db_name" \
            -tA \
            -v ON_ERROR_STOP=1 \
            -f /tmp/domain-ops-smoke.sql)" \
          || fail "dockerized psql query failed"
      }
  else
    psql_output="$(run_kubernetes_psql_query "$connect_host" "$connect_port" "$db_name" "$db_user" "$db_pass_pgpass" "$SQL_FILE")" \
      || fail "kubernetes psql query failed"
  fi

  printf '%s\n' "$psql_output" \
    | jq -e . > "$DB_REPORT_FILE" \
    || fail "DB query did not return JSON for operation $OPERATION_ID"
}

verify_db_report() {
  if grep -Fq "$CREDENTIAL_REF" "$DB_REPORT_FILE" "$API_RESPONSE_REDACTED_FILE" 2>/dev/null; then
    fail "raw credentialRef leaked into redacted evidence"
  fi

  jq -e \
    --arg op "$OPERATION" \
    --argjson ttl "$TTL_SECONDS" \
    --arg contract "$CONTRACT" '
      .request.id and
      .request.operation == $op and
      .request.state == "FAILED" and
      .request.reasonCode == "connector-unavailable" and
      .request.ttlSeconds == $ttl and
      .request.credentialRefPresent == true and
      (.request.credentialRefHashPrefix | length) == 16 and
      .request.connectorName == "unavailable" and
      .request.completedAtPresent == true and
      ([.auditEvents[].event_type] | index("DOMAIN_OPS_REQUESTED")) and
      ([.auditEvents[].event_type] | index("DOMAIN_OPS_FAILED")) and
      ([.auditEvents[].contract] | all(. == $contract or . == null)) and
      ([.auditEvents[] | select(.event_type == "DOMAIN_OPS_REQUESTED") | .credentialRefAccepted] | index("true")) and
      ([.auditEvents[] | select(.event_type == "DOMAIN_OPS_FAILED") | .reasonCode] | index("connector-unavailable"))
    ' "$DB_REPORT_FILE" >/dev/null \
    || fail "DB/audit redacted evidence did not match the #676 acceptance contract"
}

need kubectl
need jq
need curl
need python3
need openssl

echo "== #676 endpoint-admin domain ops broker smoke =="
echo "context=$CTX namespace=$NS deployment=$DEPLOY target=$TARGET_HOSTNAME operation=$OPERATION"

verify_runtime_flag
read_keycloak_admin_password
mint_keycloak_admin_token
resolve_persona_id
reset_persona_password
mint_persona_token
resolve_target_device
create_domain_ops_request
run_psql_json_query
verify_db_report

pass "domain ops broker produced durable failed-closed request + redacted audit evidence"
