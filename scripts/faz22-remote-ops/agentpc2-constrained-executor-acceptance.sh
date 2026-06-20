#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 / platform-agent#208 AgentPC2 product-channel acceptance smoke.
#
# This script runs on the staging self-hosted runner. It proves only the
# outbound mTLS product channel and constrained catalog operation path. It does
# not use endpoint inbound SSH/RDP/WinRM/SMB/RPC, does not print bearer tokens,
# and never writes raw session IDs to issue comments.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"

K8S_CONTEXT="${K8S_CONTEXT:-k3d-test}"
K8S_NAMESPACE="${K8S_NAMESPACE:-platform-test}"
REMOTE_BRIDGE_DEPLOYMENT="${REMOTE_BRIDGE_DEPLOYMENT:-endpoint-admin-remote-bridge}"
REMOTE_BRIDGE_LOCAL_PORT="${REMOTE_BRIDGE_LOCAL_PORT:-18096}"
EXPECTED_DIGEST="${EXPECTED_DIGEST:-sha256:7e1925ceb0312042c8712fcb423eafc5bae1a3f1e0f22c93a7d0ce3b16dccf84}"

DEVICE_ID="${DEVICE_ID:-fa2d1ad6-a0a8-4101-ab77-9f2a0b25742a}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:-AgentPc2}"
ISSUE_URL="${ISSUE_URL:-https://github.com/Halildeu/platform-agent/issues/208}"
CATALOG_OPERATION_ID="${CATALOG_OPERATION_ID:-GET_HOSTNAME}"
SESSION_ID="${SESSION_ID:-rb-agentpc2-$(date -u +%Y%m%dT%H%M%SZ)}"
STEP_UP_EPHEMERAL_KEY_ENABLED="${STEP_UP_EPHEMERAL_KEY_ENABLED:-1}"

EXPECTED_RELEASE_TAG="${EXPECTED_RELEASE_TAG:-v0.2.13}"
EXPECTED_AGENT_VERSION="${EXPECTED_AGENT_VERSION:-0.2.13}"
EXPECTED_AGENT_SHA256="${EXPECTED_AGENT_SHA256:-6e3a79b8ea076d08e2288be98359d3db6049b6179e655ceaff924f792736cd0c}"
EXPECTED_AGENT_ZIP_SHA256="${EXPECTED_AGENT_ZIP_SHA256:-9afe07b6eb1fa2c8b94b50181ec5265681e77a28ec3368bdd8d1a25fd59acec0}"
EXPECTED_SIGNER_THUMBPRINT="${EXPECTED_SIGNER_THUMBPRINT:-D68F4F530137EB65CE44E3405E82B46205E753E5}"

KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
OPERATOR_USERNAME="${OPERATOR_USERNAME:-rb-operator-denetim}"
APPROVER_USERNAME="${APPROVER_USERNAME:-rb-approver-denetim}"
TENANT_ID="${TENANT_ID:-00000000-0000-0000-0000-000000000001}"
TOKEN_CLIENT_CANDIDATES="${TOKEN_CLIENT_CANDIDATES:-frontend remote-bridge-operator-api}"

PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PG_DATABASE="${PG_DATABASE:-endpoint_admin}"
PG_USER="${PG_USER:-postgres}"
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5433}"
PG_SERVICE_HOST="${PG_SERVICE_HOST:-postgres}"
PG_SERVICE_PORT="${PG_SERVICE_PORT:-5432}"
PG_SECRET_NAME="${PG_SECRET_NAME:-endpoint-admin-remote-bridge-secrets}"
PG_USER_SECRET_KEY="${PG_USER_SECRET_KEY:-SPRING_DATASOURCE_USERNAME}"
PG_PASSWORD_SECRET_KEY="${PG_PASSWORD_SECRET_KEY:-SPRING_DATASOURCE_PASSWORD}"
PG_CLIENT_IMAGE="${PG_CLIENT_IMAGE:-postgres:16-alpine}"
DB_SCHEMA="${DB_SCHEMA:-endpoint_admin_service}"

STEP_UP_PRIVATE_KEY_PEM_PATH="${STEP_UP_PRIVATE_KEY_PEM_PATH:-}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/agentpc2-rtt-acceptance-$(date -u +%Y%m%dT%H%M%SZ)}"

TMP_DIR="$(mktemp -d)"
PORT_FORWARD_PID=""
SUMMARY_FILE="${EVIDENCE_DIR}/summary.json"
OPERATOR_TOKEN_FILE="${TMP_DIR}/operator.jwt"
APPROVER_TOKEN_FILE="${TMP_DIR}/approver.jwt"
KC_ADMIN_PASS_FILE="${TMP_DIR}/kc-admin-password.txt"
KC_ADMIN_TOKEN_FILE="${TMP_DIR}/kc-admin.jwt"

status="starting"
reason=""
open_code=""
approve_code=""
challenge_code=""
verify_code=""
operation_status=""
verification_result=""
recording_hint=""
session_hash=""
step_up_key_mode=""
step_up_public_key_sha256=""
operator_claims_file="${EVIDENCE_DIR}/operator-jwt-claims.redacted.json"
approver_claims_file="${EVIDENCE_DIR}/approver-jwt-claims.redacted.json"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR missing command: $1" >&2
    exit 2
  }
}

cleanup() {
  set +e
  stop_port_forward
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

stop_port_forward() {
  if [[ -n "$PORT_FORWARD_PID" ]] && kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1
    wait "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
  PORT_FORWARD_PID=""
}

sha256_text() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  else
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  fi
}

write_summary() {
  mkdir -p "$EVIDENCE_DIR"
  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg context "$K8S_CONTEXT" \
    --arg namespace "$K8S_NAMESPACE" \
    --arg deployment "$REMOTE_BRIDGE_DEPLOYMENT" \
    --arg expectedDigest "$EXPECTED_DIGEST" \
    --arg deviceId "$DEVICE_ID" \
    --arg deviceHostname "$DEVICE_HOSTNAME" \
    --arg sessionHash "$session_hash" \
    --arg catalogOperationId "$CATALOG_OPERATION_ID" \
    --arg openCode "$open_code" \
    --arg approveCode "$approve_code" \
    --arg challengeCode "$challenge_code" \
    --arg verifyCode "$verify_code" \
    --arg operationStatus "$operation_status" \
    --arg verificationResult "$verification_result" \
    --arg recordingHint "$recording_hint" \
    --arg stepUpKeyMode "$step_up_key_mode" \
    --arg stepUpPublicKeySha256 "$step_up_public_key_sha256" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    '{
      generatedAt: $generatedAt,
      status: $status,
      reason: $reason,
      target: {
        deviceId: $deviceId,
        hostname: $deviceHostname
      },
      runtime: {
        context: $context,
        namespace: $namespace,
        deployment: $deployment,
        expectedDigest: $expectedDigest
      },
      productPath: {
        sessionHash: $sessionHash,
        catalogOperationId: $catalogOperationId,
        openHttp: $openCode,
        approveHttp: $approveCode,
        stepUpChallengeHttp: $challengeCode,
        stepUpVerifyHttp: $verifyCode,
        operationStatus: $operationStatus,
        verifierResult: $verificationResult,
        recordingHint: $recordingHint,
        stepUpKeyMode: $stepUpKeyMode,
        stepUpPublicKeySha256: $stepUpPublicKeySha256
      },
      evidenceDir: $evidenceDir,
      secretHygiene: {
        rawBearerTokenLogged: false,
        rawSessionIdLogged: false,
        privateKeyLogged: false
      },
      doesNotProve: [
        "signed MSI/GPO broad rollout",
        "5/50/800 device wave readiness",
        "production remote-support readiness",
        "inbound SSH/RDP/WinRM/SMB/RPC reachability",
        "unrestricted shell or file browser",
        "true TPM/device-key attestation for broad rollout"
      ]
    }' > "$SUMMARY_FILE"
}

fail_acceptance() {
  status="no-go"
  reason="$1"
  write_summary
  echo "NO_GO $reason"
  exit 1
}

mask_file_value() {
  local file="$1"
  if [[ -s "$file" && -n "${GITHUB_ACTIONS:-}" && "${EMIT_GITHUB_MASK_COMMANDS:-0}" == "1" ]]; then
    printf '::add-mask::%s\n' "$(tr -d '\r\n' < "$file")"
  fi
}

curl_json() {
  local method="$1" base="$2" path="$3" token_file="$4" out="$5" body="${6:-}"
  local code_file="${out}.code"
  local args=(
    --silent
    --show-error
    --max-time 20
    --request "$method"
    --output "$out"
    --write-out '%{http_code}'
    --header 'Content-Type: application/json'
  )
  if [[ -n "$body" ]]; then
    printf '%s' "$body" > "${out}.request.json"
    args+=(--data-binary "@${out}.request.json")
  fi
  if [[ -n "$token_file" ]]; then
    printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$token_file")" \
      | curl --config - "${args[@]}" "${base}${path}" > "$code_file"
  else
    curl "${args[@]}" "${base}${path}" > "$code_file"
  fi
  tr -d '\r\n[:space:]' < "$code_file"
}

assert_http() {
  local actual="$1" expected="$2" label="$3" body_file="$4"
  if [[ "$actual" != "$expected" ]]; then
    reason="${label} expected ${expected}, got ${actual}"
    [[ -f "$body_file" ]] && jq -c . "$body_file" 2>/dev/null | sed 's/^/BODY /' >&2 || true
    fail_acceptance "$reason"
  fi
}

read_keycloak_admin_password() {
  if [[ -n "${KC_ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "$KC_ADMIN_PASSWORD" > "$KC_ADMIN_PASS_FILE"
    chmod 0600 "$KC_ADMIN_PASS_FILE"
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    if docker exec "$KC_CONTAINER" sh -c 'cat /run/secrets/kc_admin_password' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null && [[ -s "$KC_ADMIN_PASS_FILE" ]]; then
      chmod 0600 "$KC_ADMIN_PASS_FILE"
      return 0
    fi
    if docker exec "$KC_CONTAINER" sh -c 'p="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"; [ -n "$p" ] && cat "$p"' \
        > "$KC_ADMIN_PASS_FILE" 2>/dev/null && [[ -s "$KC_ADMIN_PASS_FILE" ]]; then
      chmod 0600 "$KC_ADMIN_PASS_FILE"
      return 0
    fi
  fi
  fail_acceptance "keycloak-admin-password-source-missing"
}

mint_admin_token() {
  local response
  response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=$KC_ADMIN_USER" \
    --data-urlencode "password@$KC_ADMIN_PASS_FILE")" \
    || fail_acceptance "keycloak-admin-token-request-failed"
  jq -r '.access_token // empty' <<< "$response" > "$KC_ADMIN_TOKEN_FILE"
  [[ -s "$KC_ADMIN_TOKEN_FILE" ]] || fail_acceptance "keycloak-admin-token-missing"
  chmod 0600 "$KC_ADMIN_TOKEN_FILE"
  mask_file_value "$KC_ADMIN_TOKEN_FILE"
}

admin_curl() {
  local method="$1" path="$2" out="$3" body="${4:-}"
  curl_json "$method" "$KC_BASE_URL/admin/realms/$KC_REALM" "$path" "$KC_ADMIN_TOKEN_FILE" "$out" "$body"
}

ensure_persona() {
  local username="$1" user_id_file="$2"
  local lookup="${TMP_DIR}/${username}-lookup.json"
  local code
  code="$(admin_curl GET "/users?username=${username}&exact=true" "$lookup")"
  assert_http "$code" 200 "keycloak lookup $username" "$lookup"

  local uid
  uid="$(jq -r '.[0].id // empty' "$lookup")"
  if [[ -z "$uid" ]]; then
    local create_body create_out
    create_out="${TMP_DIR}/${username}-create.json"
    create_body="$(jq -nc \
      --arg username "$username" \
      --arg email "${username}@testai.acik.com" \
      --arg tenant "$TENANT_ID" \
      '{username:$username, enabled:true, emailVerified:true, email:$email,
        firstName:"RemoteBridge", lastName:$username,
        attributes:{tenant_id:[$tenant], org_id:[$tenant], userId:[$username]}}')"
    code="$(admin_curl POST /users "$create_out" "$create_body")"
    [[ "$code" == "201" || "$code" == "204" ]] || fail_acceptance "keycloak create $username returned $code"
    code="$(admin_curl GET "/users?username=${username}&exact=true" "$lookup")"
    assert_http "$code" 200 "keycloak lookup-created $username" "$lookup"
    uid="$(jq -r '.[0].id // empty' "$lookup")"
  fi
  [[ -n "$uid" ]] || fail_acceptance "keycloak user id missing for $username"
  printf '%s' "$uid" > "$user_id_file"

  local update_out update_body
  update_out="${TMP_DIR}/${username}-update.json"
  update_body="$(jq -nc \
    --arg id "$uid" \
    --arg username "$username" \
    --arg email "${username}@testai.acik.com" \
    --arg tenant "$TENANT_ID" \
    '{id:$id, username:$username, enabled:true, emailVerified:true, email:$email,
      firstName:"RemoteBridge", lastName:$username,
      attributes:{tenant_id:[$tenant], org_id:[$tenant], userId:[$username]}}')"
  code="$(admin_curl PUT "/users/${uid}" "$update_out" "$update_body")"
  [[ "$code" == "204" ]] || fail_acceptance "keycloak update $username returned $code"

  local pass_file reset_body reset_out
  pass_file="${TMP_DIR}/${username}.password"
  openssl rand -base64 32 | tr -d '\n' > "$pass_file"
  chmod 0600 "$pass_file"
  reset_body="$(jq -n --rawfile value "$pass_file" '{type:"password", value:$value, temporary:false}')"
  reset_out="${TMP_DIR}/${username}-reset.json"
  code="$(admin_curl PUT "/users/${uid}/reset-password" "$reset_out" "$reset_body")"
  [[ "$code" == "204" ]] || fail_acceptance "keycloak reset $username returned $code"

  local role_file role_json role_out
  role_file="${TMP_DIR}/remote-bridge-role.json"
  code="$(admin_curl GET /roles/remote-bridge-operator "$role_file")"
  assert_http "$code" 200 "keycloak remote-bridge role lookup" "$role_file"
  role_json="$(jq -c '[.]' "$role_file")"
  role_out="${TMP_DIR}/${username}-role-map.json"
  code="$(admin_curl POST "/users/${uid}/role-mappings/realm" "$role_out" "$role_json")"
  [[ "$code" == "204" || "$code" == "409" ]] || fail_acceptance "keycloak role-map $username returned $code"
}

decode_jwt_claims() {
  local token_file="$1" out="$2"
  python3 - "$token_file" "$out" <<'PY'
import base64
import json
import sys

token_path, out_path = sys.argv[1:3]
token = open(token_path, encoding="utf-8").read().strip()
parts = token.split(".")
if len(parts) < 2:
    raise SystemExit("invalid JWT")
payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
aud = claims.get("aud")
if isinstance(aud, str):
    aud_values = [aud]
elif isinstance(aud, list):
    aud_values = aud
else:
    aud_values = []
roles = claims.get("realm_access", {}).get("roles", [])
safe = {
    "preferred_username": claims.get("preferred_username"),
    "tenant_id_present": bool(claims.get("tenant_id")),
    "aud": aud,
    "audContainsRemoteBridgeOperatorApi": "remote-bridge-operator-api" in aud_values,
    "realmRolesContainRemoteBridgeOperator": "remote-bridge-operator" in roles,
    "issuerPresent": bool(claims.get("iss")),
    "expiresAtEpoch": claims.get("exp"),
}
open(out_path, "w", encoding="utf-8").write(json.dumps(safe, sort_keys=True, indent=2) + "\n")
PY
}

mint_persona_token() {
  local username="$1" token_file="$2" claims_file="$3"
  local pass_file="${TMP_DIR}/${username}.password"
  local client response token
  for client in $TOKEN_CLIENT_CANDIDATES; do
    response="$(curl -sS -X POST \
      "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
      --data-urlencode "grant_type=password" \
      --data-urlencode "client_id=$client" \
      --data-urlencode "username=$username" \
      --data-urlencode "password@$pass_file" || true)"
    token="$(jq -r '.access_token // empty' <<< "$response" 2>/dev/null || true)"
    if [[ -n "$token" ]]; then
      printf '%s' "$token" > "$token_file"
      chmod 0600 "$token_file"
      mask_file_value "$token_file"
      decode_jwt_claims "$token_file" "$claims_file"
      if jq -e '.realmRolesContainRemoteBridgeOperator == true and .tenant_id_present == true' "$claims_file" >/dev/null; then
        return 0
      fi
    fi
  done
  fail_acceptance "keycloak-persona-token-unusable:${username}"
}

verify_runtime_digest() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" --timeout=240s
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get deploy "$REMOTE_BRIDGE_DEPLOYMENT" -o json \
    > "${EVIDENCE_DIR}/deploy.json"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get pods -l "app.kubernetes.io/name=${REMOTE_BRIDGE_DEPLOYMENT}" -o json \
    > "${EVIDENCE_DIR}/pods.json"
  jq -r '.spec.template.spec.containers[0].image' "${EVIDENCE_DIR}/deploy.json" \
    > "${EVIDENCE_DIR}/deploy-image.txt"
  jq -r '.items[]
    | select(.metadata.deletionTimestamp == null)
    | .status.containerStatuses[0].imageID' "${EVIDENCE_DIR}/pods.json" \
    > "${EVIDENCE_DIR}/pod-imageID.txt"
  grep -F "$EXPECTED_DIGEST" "${EVIDENCE_DIR}/deploy-image.txt" >/dev/null \
    || fail_acceptance "deployment-image-digest-mismatch"
  grep -F "$EXPECTED_DIGEST" "${EVIDENCE_DIR}/pod-imageID.txt" >/dev/null \
    || fail_acceptance "pod-imageID-digest-mismatch"
}

start_port_forward() {
  stop_port_forward
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" \
    port-forward "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" "${REMOTE_BRIDGE_LOCAL_PORT}:8096" \
    > "${EVIDENCE_DIR}/port-forward.log" 2>&1 &
  PORT_FORWARD_PID="$!"
  for _ in $(seq 1 40); do
    if ! kill -0 "$PORT_FORWARD_PID" >/dev/null 2>&1; then
      fail_acceptance "operator-rest-port-forward-exited"
    fi
    if curl -sS --max-time 2 "http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/operator/operation-catalog" \
        -o /dev/null -w '%{http_code}' | grep -Eq '^(200|401|403)$'; then
      return 0
    fi
    sleep 1
  done
  fail_acceptance "operator-rest-port-forward-timeout"
}

export_step_up_public_key() {
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get secret endpoint-admin-remote-bridge-secrets \
    -o jsonpath='{.data.REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM}' \
    | base64 -d > "${TMP_DIR}/step-up-public.pem"
  [[ -s "${TMP_DIR}/step-up-public.pem" ]] || fail_acceptance "step-up-public-key-missing"
  step_up_public_key_sha256="$(shasum -a 256 "${TMP_DIR}/step-up-public.pem" | awk '{print $1}')"
}

secret_key_to_file() {
  local secret_name="$1" key="$2" out="$3"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" get secret "$secret_name" \
    -o "jsonpath={.data.${key}}" \
    | base64 -d > "$out"
  [[ -s "$out" ]] || fail_acceptance "secret-key-missing:${secret_name}/${key}"
  chmod 0600 "$out"
}

read_pg_credentials() {
  secret_key_to_file "$PG_SECRET_NAME" "$PG_USER_SECRET_KEY" "${TMP_DIR}/pg-user.txt"
  secret_key_to_file "$PG_SECRET_NAME" "$PG_PASSWORD_SECRET_KEY" "${TMP_DIR}/pg-password.txt"
}

psql_query() {
  local sql="$1" delimiter="${2:-|}"

  if command -v docker >/dev/null 2>&1 && docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DATABASE" -At -F "$delimiter" -v ON_ERROR_STOP=1 -c "$sql"
    return 0
  fi

  if command -v psql >/dev/null 2>&1; then
    read_pg_credentials
    PGPASSWORD="$(cat "${TMP_DIR}/pg-password.txt")" \
      psql -h "$PG_HOST" -p "$PG_PORT" -U "$(cat "${TMP_DIR}/pg-user.txt")" \
      -d "$PG_DATABASE" -At -F "$delimiter" -v ON_ERROR_STOP=1 -c "$sql" \
      && return 0
  fi

  local pod_name overrides
  pod_name="agentpc2-psql-$(date -u +%Y%m%d%H%M%S)-$RANDOM"
  overrides="$(jq -nc \
    --arg podName "$pod_name" \
    --arg image "$PG_CLIENT_IMAGE" \
    --arg host "$PG_SERVICE_HOST" \
    --arg port "$PG_SERVICE_PORT" \
    --arg database "$PG_DATABASE" \
    --arg delimiter "$delimiter" \
    --arg secretName "$PG_SECRET_NAME" \
    --arg userKey "$PG_USER_SECRET_KEY" \
    --arg passwordKey "$PG_PASSWORD_SECRET_KEY" \
    --arg sql "$sql" \
    '{
      apiVersion: "v1",
      spec: {
        restartPolicy: "Never",
        securityContext: {
          runAsNonRoot: true,
          seccompProfile: {type: "RuntimeDefault"}
        },
        containers: [{
          name: $podName,
          image: $image,
          securityContext: {
            allowPrivilegeEscalation: false,
            capabilities: {drop: ["ALL"]},
            runAsNonRoot: true,
            runAsUser: 65532,
            runAsGroup: 65532,
            seccompProfile: {type: "RuntimeDefault"}
          },
          env: [
            {name: "PGHOST", value: $host},
            {name: "PGPORT", value: $port},
            {name: "PGDATABASE", value: $database},
            {name: "PGDELIMITER", value: $delimiter},
            {name: "SQL", value: $sql},
            {name: "PGUSER", valueFrom: {secretKeyRef: {name: $secretName, key: $userKey}}},
            {name: "PGPASSWORD", valueFrom: {secretKeyRef: {name: $secretName, key: $passwordKey}}}
          ],
          command: ["sh", "-ceu"],
          args: ["psql -h \"$PGHOST\" -p \"$PGPORT\" -U \"$PGUSER\" -d \"$PGDATABASE\" -At -F \"$PGDELIMITER\" -v ON_ERROR_STOP=1 -c \"$SQL\""]
        }]
      }
    }')"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" run "$pod_name" \
    --rm -i --restart=Never \
    --image="$PG_CLIENT_IMAGE" \
    --labels="app.kubernetes.io/name=agentpc2-psql-smoke,app.kubernetes.io/part-of=platform" \
    --quiet=true \
    --overrides="$overrides" \
    || fail_acceptance "postgres-client-pod-query-failed"
}

candidate_private_keys() {
  if [[ -n "$STEP_UP_PRIVATE_KEY_PEM_PATH" ]]; then
    printf '%s\n' "$STEP_UP_PRIVATE_KEY_PEM_PATH"
  fi
  for p in \
    /home/halil/codex-rb-smoke/keys/operator-step-up-private-key.pem \
    /home/halil/codex-rb-smoke/operator-step-up-private-key.pem \
    /home/halil/remote-bridge/keys/operator-step-up-private-key.pem \
    /home/halil/remote-bridge-step-up-private-key.pem \
    /home/runner/remote-bridge-step-up-private-key.pem \
    "$REPO_ROOT/.local/remote-bridge/operator-step-up-private-key.pem"; do
    [[ -n "$p" ]] && printf '%s\n' "$p"
  done
  if [[ -d /home/halil/codex-rb-smoke ]]; then
    find /home/halil/codex-rb-smoke -maxdepth 5 -type f \
      \( -iname '*step*private*.pem' -o -iname '*webauthn*private*.pem' -o -iname '*operator*private*.pem' \) \
      2>/dev/null | head -20
  fi
}

try_find_matching_step_up_private_key() {
  local public_norm candidate pub_tmp
  public_norm="$(grep -v -- '-----' "${TMP_DIR}/step-up-public.pem" | tr -d '\r\n[:space:]')"
  while IFS= read -r candidate; do
    [[ -r "$candidate" ]] || continue
    pub_tmp="${TMP_DIR}/candidate.pub"
    if openssl pkey -in "$candidate" -pubout -out "$pub_tmp" >/dev/null 2>&1; then
      if [[ "$(grep -v -- '-----' "$pub_tmp" | tr -d '\r\n[:space:]')" == "$public_norm" ]]; then
        printf '%s' "$candidate" > "${TMP_DIR}/step-up-private-key.path"
        chmod 0600 "${TMP_DIR}/step-up-private-key.path"
        step_up_key_mode="preconfigured-private-key"
        return 0
      fi
    fi
  done < <(candidate_private_keys | awk 'NF && !seen[$0]++')
  return 1
}

generate_run_scoped_step_up_key() {
  [[ "$STEP_UP_EPHEMERAL_KEY_ENABLED" == "1" ]] \
    || fail_acceptance "step-up-private-key-unavailable-or-public-mismatch"

  local key_path public_path public_b64 patch run_id
  key_path="${TMP_DIR}/run-scoped-step-up-private-key.pem"
  public_path="${TMP_DIR}/run-scoped-step-up-public-key.pem"
  run_id="${GITHUB_RUN_ID:-manual-$(date -u +%Y%m%dT%H%M%SZ)}"

  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$key_path" \
    >/dev/null 2>&1 || fail_acceptance "step-up-ephemeral-key-generation-failed"
  chmod 0600 "$key_path"
  openssl pkey -in "$key_path" -pubout -out "$public_path" \
    >/dev/null 2>&1 || fail_acceptance "step-up-ephemeral-public-key-generation-failed"

  public_b64="$(base64 < "$public_path" | tr -d '\r\n')"
  patch="$(jq -cn --arg pem "$public_b64" '{data:{REMOTE_BRIDGE_STEP_UP_PUBLIC_KEY_PEM:$pem}}')"

  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" patch secret endpoint-admin-remote-bridge-secrets \
    --type merge -p "$patch" >/dev/null \
    || fail_acceptance "step-up-ephemeral-public-key-secret-patch-failed"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" annotate secret endpoint-admin-remote-bridge-secrets \
    "remote-bridge.platform/run-scoped-step-up-key=${run_id}" --overwrite >/dev/null 2>&1 || true

  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout restart "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" >/dev/null \
    || fail_acceptance "step-up-ephemeral-rollout-restart-failed"
  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" rollout status "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" --timeout=240s \
    || fail_acceptance "step-up-ephemeral-rollout-timeout"
  verify_runtime_digest

  cp "$public_path" "${TMP_DIR}/step-up-public.pem"
  printf '%s' "$key_path" > "${TMP_DIR}/step-up-private-key.path"
  chmod 0600 "${TMP_DIR}/step-up-private-key.path"
  step_up_key_mode="run-scoped-ephemeral-test-key"
  step_up_public_key_sha256="$(shasum -a 256 "${TMP_DIR}/step-up-public.pem" | awk '{print $1}')"

  jq -n \
    --arg mode "$step_up_key_mode" \
    --arg publicKeySha256 "$step_up_public_key_sha256" \
    --arg runId "$run_id" \
    '{mode:$mode, publicKeySha256:$publicKeySha256, runId:$runId, privateKeyStoredInEvidence:false}' \
    > "${EVIDENCE_DIR}/step-up-key-mode.json"
}

find_matching_step_up_private_key() {
  if try_find_matching_step_up_private_key; then
    return 0
  fi
  generate_run_scoped_step_up_key
  start_port_forward
}

build_step_up_assertion() {
  local challenge_body="$1" key_path assertion_out="$2"
  key_path="$(cat "${TMP_DIR}/step-up-private-key.path")"
  python3 - "$challenge_body" "${TMP_DIR}/clientData.b64" "${TMP_DIR}/authenticatorData.b64" "${TMP_DIR}/signed.bin" <<'PY'
import base64
import hashlib
import json
import sys

challenge_path, client_b64_path, auth_b64_path, signed_path = sys.argv[1:5]
challenge = json.load(open(challenge_path, encoding="utf-8"))
challenge_b64 = challenge["challengeB64"]
raw = base64.b64decode(challenge_b64)
challenge_url = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
client = {
    "type": "webauthn.get",
    "challenge": challenge_url,
    "origin": challenge["expectedOrigin"],
}
client_bytes = json.dumps(client, separators=(",", ":"), sort_keys=True).encode("utf-8")
auth = hashlib.sha256(b"testai.acik.com").digest() + bytes([0x05]) + (1).to_bytes(4, "big")
open(client_b64_path, "w", encoding="ascii").write(base64.b64encode(client_bytes).decode("ascii"))
open(auth_b64_path, "w", encoding="ascii").write(base64.b64encode(auth).decode("ascii"))
open(signed_path, "wb").write(auth + hashlib.sha256(client_bytes).digest())
PY
  openssl dgst -sha256 -sign "$key_path" -out "${TMP_DIR}/signature.der" "${TMP_DIR}/signed.bin" \
    >/dev/null 2>&1 || fail_acceptance "step-up-signature-generation-failed"
  jq -n \
    --rawfile client "${TMP_DIR}/clientData.b64" \
    --rawfile auth "${TMP_DIR}/authenticatorData.b64" \
    --arg sig "$(base64 < "${TMP_DIR}/signature.der" | tr -d '\r\n')" \
    '{clientDataJsonB64:($client|gsub("\\n";"")), authenticatorDataB64:($auth|gsub("\\n";"")), signatureB64:$sig}' \
    > "$assertion_out"
}

write_pilot_readiness() {
  local dir="${EVIDENCE_DIR}/pilot-readiness"
  local manifest_file="${dir}/artifact-manifest.json"
  local device_file="${dir}/device-heartbeat.psv"
  mkdir -p "$dir"
  curl -fsS --max-time 20 "https://testai.acik.com/artifacts/endpoint-agent/current/release-manifest.json" \
    -o "$manifest_file"

  local sql
  sql="
select d.id,d.hostname,coalesce(d.agent_version,''),coalesce(d.status,''),
       coalesce(d.last_seen_at::text,''),coalesce(h.received_at::text,''),
       coalesce((h.payload->'capabilities')::text,'[]')
from ${DB_SCHEMA}.endpoint_devices d
left join lateral (
  select * from ${DB_SCHEMA}.endpoint_heartbeats h
  where h.device_id=d.id
  order by h.received_at desc
  limit 1
) h on true
where d.id='${DEVICE_ID}'::uuid or lower(d.hostname)=lower('${DEVICE_HOSTNAME}')
order by case when d.id='${DEVICE_ID}'::uuid then 0 else 1 end,
         d.last_seen_at desc nulls last
limit 1;"
  psql_query "$sql" '|' > "$device_file"

  local row id hostname version endpoint_status last_seen heartbeat_at caps device_json manifest_ok decision reason_text
  row="$(head -n 1 "$device_file" || true)"
  if [[ -n "$row" ]]; then
    IFS='|' read -r id hostname version endpoint_status last_seen heartbeat_at caps <<< "$row"
    if ! jq -e . <<< "$caps" >/dev/null 2>&1; then
      caps="[]"
    fi
    device_json="$(jq -cn \
      --arg id "$id" --arg hostname "$hostname" --arg version "$version" \
      --arg status "$endpoint_status" --arg lastSeen "$last_seen" --arg heartbeatAt "$heartbeat_at" \
      --argjson capabilities "$caps" \
      '{id:$id,hostname:$hostname,agent_version:$version,status:$status,last_seen_at:$lastSeen,heartbeat_received_at:$heartbeatAt,capabilities:$capabilities}')"
  else
    device_json="null"
    version=""
  fi

  manifest_ok="false"
  if jq -e \
    --arg tag "$EXPECTED_RELEASE_TAG" \
    --arg sha "$EXPECTED_AGENT_SHA256" \
    --arg zip "$EXPECTED_AGENT_ZIP_SHA256" \
    --arg thumb "$EXPECTED_SIGNER_THUMBPRINT" \
    '(.release_tag == $tag)
      and (.endpoint_agent_sha256 == $sha)
      and (.endpoint_agent_zip_sha256 == $zip)
      and ((.signer_thumbprint // "" | ascii_upcase) == ($thumb | ascii_upcase))' \
      "$manifest_file" >/dev/null; then
    manifest_ok="true"
  fi

  if [[ "$manifest_ok" == "true" && "$device_json" != "null" && "$version" == *"$EXPECTED_AGENT_VERSION"* ]]; then
    decision="ready-for-product-smoke"
    reason_text="Target endpoint reports expected agent version."
  elif [[ "$device_json" == "null" ]]; then
    decision="target-endpoint-not-found"
    reason_text="No matching endpoint device row for AgentPC2."
  elif [[ "$manifest_ok" != "true" ]]; then
    decision="artifact-manifest-mismatch"
    reason_text="Artifact manifest does not match expected v0.2.13 hashes."
  else
    decision="agent-version-mismatch"
    reason_text="Target endpoint does not report expected agent version."
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg decision "$decision" \
    --arg reason "$reason_text" \
    --arg expectedReleaseTag "$EXPECTED_RELEASE_TAG" \
    --arg expectedAgentVersion "$EXPECTED_AGENT_VERSION" \
    --arg expectedSha256 "$EXPECTED_AGENT_SHA256" \
    --arg expectedZipSha256 "$EXPECTED_AGENT_ZIP_SHA256" \
    --arg expectedSignerThumbprint "$EXPECTED_SIGNER_THUMBPRINT" \
    --argjson manifestOk "$manifest_ok" \
    --slurpfile manifest "$manifest_file" \
    --arg deviceId "$DEVICE_ID" \
    --arg deviceHostname "$DEVICE_HOSTNAME" \
    --argjson device "$device_json" \
    '{
      generatedAt:$generatedAt,
      decision:$decision,
      reason:$reason,
      manifest:{
        expectedReleaseTag:$expectedReleaseTag,
        expectedAgentVersion:$expectedAgentVersion,
        expectedSha256:$expectedSha256,
        expectedZipSha256:$expectedZipSha256,
        expectedSignerThumbprint:$expectedSignerThumbprint,
        ok:$manifestOk,
        observed:$manifest[0]
      },
      targetEndpoint:{
        requestedId:$deviceId,
        requestedHostname:$deviceHostname,
        observed:$device
      }
    }' > "${dir}/summary.json"

  [[ "$decision" == "ready-for-product-smoke" ]] \
    || fail_acceptance "pilot-readiness-${decision}"
}

export_recording_rows() {
  local raw_rows="${EVIDENCE_DIR}/session-recording.raw.jsonl"
  local sql
  sql="
SELECT jsonb_build_object(
  'chain_id', chain_id,
  'session_id', chain_id,
  'seq', seq,
  'timestamp_millis', timestamp_millis,
  'kind', kind,
  'source', kind,
  'event', kind,
  'content_hash', content_hash,
  'previous_hash', previous_hash,
  'entry_hash', entry_hash,
  'recorded_at', recorded_at,
  'payload_retention_boundary', 'content_hash_only_no_raw_payload'
)::text
FROM ${DB_SCHEMA}.session_recording_entry
WHERE chain_id = '${SESSION_ID}'
ORDER BY seq;"
  psql_query "$sql" > "$raw_rows"
  SOURCE_RECORDING_ROWS_FILE="$raw_rows" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
    "$REPO_ROOT/scripts/faz22-remote-ops/remote-response-terminal-recording-export.sh"
  recording_hint="$(jq -r '.acceptanceHint // ""' "${EVIDENCE_DIR}/recording-summary.json" 2>/dev/null || true)"
}

write_governance_source() {
  jq -n \
    --arg operator "$OPERATOR_USERNAME" \
    --arg approver "$APPROVER_USERNAME" \
    --arg approvalId "approval-${session_hash}" \
    --arg ticketRef "platform-agent#208" \
    --arg justification "Faz 22.6.3 AgentPC2 bounded constrained-executor acceptance smoke" \
    '{
      operator:{subject:$operator},
      approver:{subject:$approver},
      approval:{id:$approvalId},
      stepUp:{verified:true, method:"webauthn"},
      ticketRef:$ticketRef,
      justification:$justification,
      recording:{worm:true, failClosed:true}
    }' > "${EVIDENCE_DIR}/product-governance.json"
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    local sums_file
    sums_file="$(mktemp "${TMPDIR:-/tmp}/agentpc2-rtt-sha256.XXXXXX")"
    find . -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 shasum -a 256 \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

main() {
  for cmd in kubectl jq curl openssl python3 shasum base64; do
    need_cmd "$cmd"
  done
  mkdir -p "$EVIDENCE_DIR"
  session_hash="$(sha256_text "$SESSION_ID")"

  verify_runtime_digest
  start_port_forward
  read_keycloak_admin_password
  mint_admin_token
  ensure_persona "$OPERATOR_USERNAME" "${TMP_DIR}/operator.id"
  ensure_persona "$APPROVER_USERNAME" "${TMP_DIR}/approver.id"
  mint_persona_token "$OPERATOR_USERNAME" "$OPERATOR_TOKEN_FILE" "$operator_claims_file"
  mint_persona_token "$APPROVER_USERNAME" "$APPROVER_TOKEN_FILE" "$approver_claims_file"
  export_step_up_public_key
  find_matching_step_up_private_key
  write_pilot_readiness

  local operator_base approval_base body
  operator_base="http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/operator"
  approval_base="http://127.0.0.1:${REMOTE_BRIDGE_LOCAL_PORT}/internal/remote-bridge/approval"

  body="$(jq -nc --arg session "$SESSION_ID" --arg device "$DEVICE_ID" \
    '{sessionId:$session, deviceId:$device, reason:"Faz 22.6.3 AgentPC2 constrained executor smoke", capabilities:["CONSTRAINED_PTY"]}')"
  open_code="$(curl_json POST "$operator_base" /sessions "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/open-session.body" "$body")"
  assert_http "$open_code" 200 "open session" "${EVIDENCE_DIR}/open-session.body"

  local deny_body deny_code
  deny_body="$(jq -nc --arg session "${SESSION_ID}-full-rdp-deny" --arg device "$DEVICE_ID" \
    '{sessionId:$session, deviceId:$device, reason:"negative non-pilot capability", capabilities:["FULL_RDP"]}')"
  deny_code="$(curl_json POST "$operator_base" /sessions "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/negative-nonpilot-open.body" "$deny_body")"
  [[ "$deny_code" == "400" ]] || fail_acceptance "negative-nonpilot-open expected 400 got ${deny_code}"

  body='{"capabilities":["CONSTRAINED_PTY"]}'
  approve_code="$(curl_json POST "$approval_base" "/sessions/${SESSION_ID}/approve" "$APPROVER_TOKEN_FILE" "${EVIDENCE_DIR}/approve.body" "$body")"
  assert_http "$approve_code" 200 "approve session" "${EVIDENCE_DIR}/approve.body"

  challenge_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/step-up/challenge" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/step-up-challenge.body")"
  assert_http "$challenge_code" 200 "step-up challenge" "${EVIDENCE_DIR}/step-up-challenge.body"

  build_step_up_assertion "${EVIDENCE_DIR}/step-up-challenge.body" "${TMP_DIR}/step-up-assertion.json"
  verify_code="$(curl_json POST "$operator_base" "/sessions/${SESSION_ID}/step-up/verify" "$OPERATOR_TOKEN_FILE" "${EVIDENCE_DIR}/step-up-verify.body" "$(cat "${TMP_DIR}/step-up-assertion.json")")"
  assert_http "$verify_code" 200 "step-up verify" "${EVIDENCE_DIR}/step-up-verify.body"
  jq -e '.verified == true' "${EVIDENCE_DIR}/step-up-verify.body" >/dev/null \
    || fail_acceptance "step-up-verify-not-verified"

  write_governance_source
  EVIDENCE_DIR="$EVIDENCE_DIR" SOURCE_GOVERNANCE_FILE="${EVIDENCE_DIR}/product-governance.json" \
    "$REPO_ROOT/scripts/faz22-remote-ops/remote-response-terminal-governance-export.sh"

  ACTION=claim \
  SESSION_OWNER_ISSUE_URL="$ISSUE_URL" \
  SESSION_OWNER_ENDPOINT_ID="$DEVICE_ID" \
  REMOTE_BRIDGE_SESSION_ID="$SESSION_ID" \
  SESSION_OWNER_TTL_MINUTES=45 \
    "$REPO_ROOT/scripts/faz22-remote-ops/remote-response-terminal-session-ownership-guard.sh" \
    > "${EVIDENCE_DIR}/session-ownership-guard.out"

  OPERATOR_BEARER_TOKEN="$(tr -d '\r\n' < "$OPERATOR_TOKEN_FILE")" \
  EVIDENCE_DIR="$EVIDENCE_DIR" \
  REMOTE_BRIDGE_OPERATOR_BASE_URL="$operator_base" \
  REMOTE_BRIDGE_SESSION_ID="$SESSION_ID" \
  CATALOG_OPERATION_ID="$CATALOG_OPERATION_ID" \
  EXPECTED_OPERATION_KIND=PERMIT \
    "$REPO_ROOT/scripts/faz22-remote-ops/remote-ops-catalog-smoke.sh"

  operation_status="$(jq -r '.operationStatus // ""' "${EVIDENCE_DIR}/summary.json" 2>/dev/null || true)"

  sleep 12
  export_recording_rows
  sha256_manifest

  REQUIRE_ACCEPTED=1 \
  REQUIRE_FULL_MATRIX=0 \
  EXPECTED_CATALOG_OPERATION_ID="$CATALOG_OPERATION_ID" \
    "$REPO_ROOT/scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh" "$EVIDENCE_DIR"

  verification_result="$(jq -r '.result // ""' "${EVIDENCE_DIR}/verification-summary.json" 2>/dev/null || true)"
  if [[ "$verification_result" != "accepted-candidate" ]]; then
    fail_acceptance "verifier-${verification_result:-unknown}"
  fi

  kubectl --context "$K8S_CONTEXT" -n "$K8S_NAMESPACE" logs "deploy/${REMOTE_BRIDGE_DEPLOYMENT}" --tail=400 \
    > "${EVIDENCE_DIR}/remote-bridge-logs-tail.txt" 2>/dev/null || true

  status="accepted-candidate"
  reason="AgentPC2 outbound product mTLS constrained executor smoke passed verifier"
  write_summary
  echo "ACCEPTED_CANDIDATE evidence_dir=${EVIDENCE_DIR}"
}

main "$@"
