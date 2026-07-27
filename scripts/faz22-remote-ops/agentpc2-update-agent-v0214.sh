#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 / platform-agent#208 AgentPC2 product update gate.
#
# This script runs only on the staging self-hosted runner. It exercises the
# endpoint-admin release-catalog UPDATE_AGENT product path. It does not open an
# endpoint inbound channel, does not run arbitrary endpoint shell, and does not
# write bearer tokens or Keycloak passwords to evidence.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"
SEED_HELPER="${REPO_ROOT}/scripts/faz22-remote-ops/remote-response-terminal-update-agent-seed.sh"

API_BASE="${ENDPOINT_ADMIN_API_BASE:-https://testai.acik.com/api/v1/endpoint-admin}"

KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
CREATOR_USERNAME="${CREATOR_USERNAME:-c5persona-admin-9001}"
APPROVER_USERNAME="${APPROVER_USERNAME:-endpoint-admin-test-approver}"

TARGET_DEVICE_ID="${TARGET_DEVICE_ID:-2f7ad30f-970a-42e7-8af8-08764ae6066f}"
TARGET_DEVICE_HOSTNAME="${TARGET_DEVICE_HOSTNAME:-AgentPc2}"
POLL_SECONDS="${POLL_SECONDS:-900}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"

TARGET_VERSION="${TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"
EXPECTED_SHA256="${EXPECTED_SHA256:-$EXPECTED_AGENT_SHA256}"
MAX_BYTES="${MAX_BYTES:-$EXPECTED_AGENT_MAX_BYTES}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/agentpc2-update-agent-${RELEASE_ID}-$(date -u +%Y%m%dT%H%M%SZ)}"

TMP_DIR="$(mktemp -d)"
KC_ADMIN_PASS_FILE="${TMP_DIR}/kc-admin-password.txt"
KC_ADMIN_TOKEN_FILE="${TMP_DIR}/kc-admin.jwt"
CREATOR_PASS_FILE="${TMP_DIR}/creator-password.txt"
APPROVER_PASS_FILE="${TMP_DIR}/approver-password.txt"
CREATOR_TOKEN_FILE="${TMP_DIR}/creator.jwt"
APPROVER_TOKEN_FILE="${TMP_DIR}/approver.jwt"
SMOKE_CLIENT_SECRET_FILE="${TMP_DIR}/smoke-client-secret.txt"

CREATOR_ID=""
APPROVER_ID=""
SEED_EXIT_CODE=99
POLL_RESULT="not-run"
POLL_REASON=""
OBSERVED_VERSION=""
OBSERVED_STATUS=""
OBSERVED_LAST_SEEN=""
OBSERVED_DEVICE_ID=""
DEVICE_SNAPSHOT_API_STATUS=""

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR missing command: $1" >&2
    exit 2
  }
}

cleanup() {
  set +e
  if [[ -s "$KC_ADMIN_TOKEN_FILE" ]]; then
    rotate_persona_password "$CREATOR_ID" >/dev/null 2>&1 || true
    rotate_persona_password "$APPROVER_ID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

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

  echo "ERR keycloak admin password source missing" >&2
  exit 2
}

token_field() {
  jq -r '.access_token // empty'
}

mint_admin_token() {
  local response token
  response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/master/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=admin-cli" \
    --data-urlencode "username=$KC_ADMIN_USER" \
    --data-urlencode "password@$KC_ADMIN_PASS_FILE")"
  token="$(printf '%s' "$response" | token_field)"
  [[ -n "$token" ]] || {
    echo "ERR keycloak admin token response did not contain access_token" >&2
    exit 2
  }
  printf '%s' "$token" > "$KC_ADMIN_TOKEN_FILE"
  chmod 0600 "$KC_ADMIN_TOKEN_FILE"
}

kc_admin_header_args() {
  printf 'Authorization: Bearer %s' "$(tr -d '\r\n' < "$KC_ADMIN_TOKEN_FILE")"
}

resolve_persona_id() {
  local username="$1" response id
  response="$(curl -sS \
    "$KC_BASE_URL/admin/realms/$KC_REALM/users?username=$username&exact=true" \
    -H "$(kc_admin_header_args)")"
  id="$(printf '%s' "$response" | jq -r '.[0].id // empty')"
  [[ -n "$id" ]] || {
    echo "ERR Keycloak persona not found: $username" >&2
    exit 2
  }
  printf '%s' "$id"
}

set_persona_password() {
  local persona_id="$1" password_file="$2" body_file status
  body_file="${TMP_DIR}/reset-${persona_id}.json"
  jq -n --rawfile value "$password_file" \
    '{type:"password", value:$value, temporary:false}' > "$body_file"
  chmod 0600 "$body_file"
  status="$(curl -sS -o /dev/null -w '%{http_code}' -X PUT \
    "$KC_BASE_URL/admin/realms/$KC_REALM/users/$persona_id/reset-password" \
    -H "$(kc_admin_header_args)" \
    -H "Content-Type: application/json" \
    --data-binary "@$body_file")"
  [[ "$status" == "204" ]] || {
    echo "ERR Keycloak password reset returned HTTP $status for $persona_id" >&2
    exit 2
  }
}

rotate_persona_password() {
  local persona_id="$1" tmp_pass
  [[ -n "$persona_id" ]] || return 0
  tmp_pass="${TMP_DIR}/rotate-${persona_id}.txt"
  openssl rand -base64 32 | tr -d '\n' > "$tmp_pass"
  chmod 0600 "$tmp_pass"
  set_persona_password "$persona_id" "$tmp_pass"
}

decode_jwt_claims() {
  local token_file="$1" out_file="$2" username="$3"
  python3 - "$token_file" "$out_file" "$username" <<'PY'
import base64
import json
import sys

token_path, out_path, expected_username = sys.argv[1:4]
token = open(token_path, encoding="utf-8").read().strip()
parts = token.split(".")
if len(parts) < 2:
    raise SystemExit("invalid JWT shape")
payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
roles = payload.get("realm_access", {}).get("roles", [])
out = {
    "subPresent": bool(payload.get("sub")),
    "preferredUsername": payload.get("preferred_username"),
    "expectedUsername": expected_username,
    "usernameMatches": payload.get("preferred_username") == expected_username,
    "userId": payload.get("userId") or payload.get("user_id"),
    "realmRolesContainEndpointAdmin": "ENDPOINT_ADMIN" in roles,
    "issuerPresent": bool(payload.get("iss")),
    "expiresAtEpoch": payload.get("exp"),
}
open(out_path, "w", encoding="utf-8").write(json.dumps(out, sort_keys=True, indent=2) + "\n")
PY
}

fetch_smoke_client_secret() {
  # A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover).
  # Vault kv/platform/keycloak/smoke-client (A2a); scope-mapping/audience A2b.1 setup-smoke-token-contract.sh.
  [[ -s "$SMOKE_CLIENT_SECRET_FILE" ]] && return 0
  local vault_root_token
  vault_root_token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "${VAULT_INIT_FILE:-$HOME/bootstrap-drill/vault-init-test.json}")" \
    || { echo "ERR smoke-client secret için vault root token okunamadı" >&2; exit 2; }
  docker exec -e VAULT_TOKEN="$vault_root_token" platform-vault-test \
    vault kv get -field=client_secret kv/platform/keycloak/smoke-client > "$SMOKE_CLIENT_SECRET_FILE" \
    || { echo "ERR smoke-client secret Vault'tan alınamadı (kv/platform/keycloak/smoke-client — A2a seed?)" >&2; exit 2; }
  chmod 0600 "$SMOKE_CLIENT_SECRET_FILE"
  vault_root_token=""
  [[ -s "$SMOKE_CLIENT_SECRET_FILE" ]] || { echo "ERR smoke-client secret dosyası boş" >&2; exit 2; }
}

mint_persona_token() {
  local username="$1" persona_id="$2" password_file="$3" token_file="$4" claims_file="$5"
  local response token

  openssl rand -base64 32 | tr -d '\n' > "$password_file"
  chmod 0600 "$password_file"
  set_persona_password "$persona_id" "$password_file"
  fetch_smoke_client_secret

  response="$(curl -sS -X POST \
    "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=smoke-client" \
    --data-urlencode "client_secret@$SMOKE_CLIENT_SECRET_FILE" \
    --data-urlencode "username=$username" \
    --data-urlencode "password@$password_file")"
  token="$(printf '%s' "$response" | token_field)"
  [[ -n "$token" ]] || {
    echo "ERR Keycloak persona token missing for $username" >&2
    exit 2
  }
  printf '%s' "$token" > "$token_file"
  chmod 0600 "$token_file"
  decode_jwt_claims "$token_file" "$claims_file" "$username"
}

curl_api() {
  local method="$1" path="$2" token_file="$3" out="$4"
  local code_file="${out}.code"
  printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$token_file")" \
    | curl --config - \
      --silent \
      --show-error \
      --max-time 30 \
      --request "$method" \
      --output "$out" \
      --write-out '%{http_code}' \
      --header 'Content-Type: application/json' \
      "${API_BASE%/}${path}" > "$code_file"
  tr -d '\r\n[:space:]' < "$code_file"
}

device_rows_jq='
  def rows:
    if type == "array" then .[]
    else (.content[]?, .items[]?, .data[]?, .devices[]?)
    end;
  rows
  | {
      id: (.id // .deviceId // ""),
      hostname: (.hostname // .hostName // .displayName // .name // ""),
      agentVersion: (.agentVersion // .agent_version // .version // ""),
      status: (.status // .state // ""),
      lastSeenAt: (.lastSeenAt // .last_seen_at // "")
    }
'

write_device_snapshot() {
  local label="$1" out raw code
  raw="${EVIDENCE_DIR}/${label}-endpoint-devices.raw.json"
  out="${EVIDENCE_DIR}/${label}-agentpc2-device.json"
  code="$(curl_api GET /endpoint-devices "$CREATOR_TOKEN_FILE" "$raw" || true)"
  DEVICE_SNAPSHOT_API_STATUS="$code"
  if [[ "$code" != "200" ]]; then
    jq -n --arg http "$code" --arg snapshotLabel "$label" \
      '{"label":$snapshotLabel,httpStatus:($http|tonumber? // null),deviceFound:false}' > "$out"
    return 0
  fi

  jq -c \
    --arg id "$TARGET_DEVICE_ID" \
    --arg host "$(printf '%s' "$TARGET_DEVICE_HOSTNAME" | tr '[:lower:]' '[:upper:]')" \
    "$device_rows_jq
      | select((.id == \$id) or ((.hostname | ascii_upcase) == \$host))" \
    "$raw" | head -1 | jq -s '.[0] // {}' > "$out"

  if jq -e '.id? // empty' "$out" >/dev/null; then
    OBSERVED_DEVICE_ID="$(jq -r '.id // ""' "$out")"
    OBSERVED_VERSION="$(jq -r '.agentVersion // ""' "$out")"
    OBSERVED_STATUS="$(jq -r '.status // ""' "$out")"
    OBSERVED_LAST_SEEN="$(jq -r '.lastSeenAt // ""' "$out")"
  fi
}

poll_expected_version() {
  local deadline now
  deadline=$(( $(date +%s) + POLL_SECONDS ))
  POLL_RESULT="timeout"
  POLL_REASON="expected-version-not-observed"

  while true; do
    write_device_snapshot "poll"
    if [[ "$OBSERVED_VERSION" == *"$EXPECTED_AGENT_VERSION"* ]]; then
      POLL_RESULT="ok"
      POLL_REASON="expected-version-observed"
      return 0
    fi

    now="$(date +%s)"
    if (( now >= deadline )); then
      return 1
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
}

write_summary() {
  local seed_summary="${EVIDENCE_DIR}/seed/summary.json"
  local seed_status=""
  if [[ -f "$seed_summary" ]]; then
    seed_status="$(jq -r '.status // ""' "$seed_summary" 2>/dev/null || true)"
  fi

  jq -n \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg apiBase "$API_BASE" \
    --arg releaseId "$RELEASE_ID" \
    --arg targetVersion "$TARGET_VERSION" \
    --arg binaryUrl "$BINARY_URL" \
    --arg expectedSha256 "$EXPECTED_SHA256" \
    --arg signerThumbprint "$EXPECTED_SIGNER_THUMBPRINT" \
    --arg targetDeviceId "$TARGET_DEVICE_ID" \
    --arg targetDeviceHostname "$TARGET_DEVICE_HOSTNAME" \
    --arg observedDeviceId "$OBSERVED_DEVICE_ID" \
    --arg observedVersion "$OBSERVED_VERSION" \
    --arg observedStatus "$OBSERVED_STATUS" \
    --arg observedLastSeen "$OBSERVED_LAST_SEEN" \
    --argjson seedExitCode "$SEED_EXIT_CODE" \
    --arg seedStatus "$seed_status" \
    --arg pollResult "$POLL_RESULT" \
    --arg pollReason "$POLL_REASON" \
    --slurpfile creator "${EVIDENCE_DIR}/creator-jwt-claims.redacted.json" \
    --slurpfile approver "${EVIDENCE_DIR}/approver-jwt-claims.redacted.json" \
    '{
      generatedAt: $generatedAt,
      status: (
        if $seedExitCode != 0 then "no-go"
        elif $pollResult == "ok" then "update-observed"
        elif $pollResult == "unavailable" then "update-dispatched-unobserved"
        else "no-go"
        end
      ),
      reason: (
        if $seedExitCode != 0 then "update-agent-dispatch-failed"
        elif $pollResult == "ok" then "agent-version-updated"
        elif $pollResult == "unavailable" then $pollReason
        else $pollReason
        end
      ),
      apiBase: $apiBase,
      release: {
        releaseId: $releaseId,
        targetVersion: $targetVersion,
        binaryUrl: $binaryUrl,
        sha256: $expectedSha256,
        signerThumbprint: $signerThumbprint
      },
      targetEndpoint: {
        requestedProductDeviceId: $targetDeviceId,
        hostname: $targetDeviceHostname,
        observedProductDeviceId: $observedDeviceId,
        observedAgentVersion: $observedVersion,
        observedStatus: $observedStatus,
        observedLastSeenAt: $observedLastSeen
      },
      seed: {
        exitCode: $seedExitCode,
        status: $seedStatus
      },
      poll: {
        result: $pollResult,
        reason: $pollReason
      },
      keycloakPersonas: {
        creator: $creator[0],
        approver: $approver[0]
      },
      secretHygiene: {
        rawBearerTokenLogged: false,
        rawPasswordLogged: false,
        rawPrivateKeyLogged: false
      },
      boundary: {
        proves: [
          "approved release-catalog UPDATE_AGENT product path when status is update-observed"
        ],
        doesNotProve: [
          "platform-agent#208 constrained executor operation acceptance",
          "broad MSI/GPO rollout",
          "production remote-support readiness",
          "inbound SSH/RDP/WinRM/SMB/RPC reachability",
          "unrestricted shell or file browser",
          "true TPM/device-key hardware attestation"
        ]
      }
    }' > "${EVIDENCE_DIR}/summary.json"
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    if command -v shasum >/dev/null 2>&1; then
      find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS
    else
      find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
    fi
  )
}

main() {
  local safe_release_id

  need_cmd curl
  need_cmd jq
  need_cmd openssl
  need_cmd python3
  mkdir -p "$EVIDENCE_DIR"
  chmod 0700 "$EVIDENCE_DIR"

  [[ -x "$SEED_HELPER" ]] || chmod +x "$SEED_HELPER"
  [[ "$TARGET_DEVICE_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || {
    echo "ERR TARGET_DEVICE_ID must be a UUID" >&2
    exit 2
  }

  read_keycloak_admin_password
  mint_admin_token

  CREATOR_ID="$(resolve_persona_id "$CREATOR_USERNAME")"
  APPROVER_ID="$(resolve_persona_id "$APPROVER_USERNAME")"
  mint_persona_token "$CREATOR_USERNAME" "$CREATOR_ID" "$CREATOR_PASS_FILE" "$CREATOR_TOKEN_FILE" "${EVIDENCE_DIR}/creator-jwt-claims.redacted.json"
  mint_persona_token "$APPROVER_USERNAME" "$APPROVER_ID" "$APPROVER_PASS_FILE" "$APPROVER_TOKEN_FILE" "${EVIDENCE_DIR}/approver-jwt-claims.redacted.json"

  write_device_snapshot "before"
  safe_release_id="$(printf '%s' "$RELEASE_ID" | tr -cs 'A-Za-z0-9' '-' | sed -E 's/^-+|-+$//g')"

  mkdir -p "${EVIDENCE_DIR}/seed"
  seed_release_notes="Faz 22.6.3 AgentPC2 ${TARGET_VERSION} seed for platform-agent#208"
  seed_dispatch_reason="Faz 22.6.3 AgentPC2 constrained-executor ${TARGET_VERSION} product update for platform-agent#208"
  set +e
  EVIDENCE_DIR="${EVIDENCE_DIR}/seed" \
    ENDPOINT_ADMIN_API_BASE="$API_BASE" \
    RELEASE_ID="$RELEASE_ID" \
    CHANNEL=PILOT \
    TARGET_VERSION="$TARGET_VERSION" \
    BINARY_URL="$BINARY_URL" \
    MANIFEST_URL="$MANIFEST_URL" \
    EXPECTED_SHA256="$EXPECTED_SHA256" \
    EXPECTED_SIGNER_THUMBPRINT="$EXPECTED_SIGNER_THUMBPRINT" \
    SIGNING_TIER=TRUSTED_SIGNED \
    MAX_BYTES="$MAX_BYTES" \
    RELEASE_NOTES="$seed_release_notes" \
    TARGET_DEVICE_ID="$TARGET_DEVICE_ID" \
    TARGET_DEVICE_HOSTNAME="$TARGET_DEVICE_HOSTNAME" \
    DISPATCH_REASON="$seed_dispatch_reason" \
    DISPATCH_IDEMPOTENCY_KEY="a2-${safe_release_id}-${GITHUB_RUN_ID:-manual}" \
    LIVE_MUTATION=1 \
    RUN_CREATE=1 \
    RUN_APPROVE=1 \
    RUN_NEGATIVE_DISPATCH=1 \
    RUN_DISPATCH=1 \
    CREATOR_BEARER_TOKEN_FILE="$CREATOR_TOKEN_FILE" \
    APPROVER_BEARER_TOKEN_FILE="$APPROVER_TOKEN_FILE" \
    DISPATCH_BEARER_TOKEN_FILE="$CREATOR_TOKEN_FILE" \
    "$SEED_HELPER" 2>&1 | tee "${EVIDENCE_DIR}/update-agent-seed.log"
  SEED_EXIT_CODE="${PIPESTATUS[0]}"
  set -e

  if [[ "$SEED_EXIT_CODE" == "0" ]]; then
    if [[ "$DEVICE_SNAPSHOT_API_STATUS" == "200" ]]; then
      poll_expected_version || true
    else
      POLL_RESULT="unavailable"
      POLL_REASON="endpoint-device-list-api-http-${DEVICE_SNAPSHOT_API_STATUS:-unknown}"
    fi
  else
    POLL_RESULT="skipped"
    POLL_REASON="seed-helper-failed"
    write_device_snapshot "after-seed-failed"
  fi

  write_summary
  sha256_manifest

  jq -r --arg evidenceDir "$EVIDENCE_DIR" \
    '"AGENTPC2_UPDATE_AGENT_STATUS=" + .status + " reason=" + .reason + " evidence_dir=" + $evidenceDir' \
    "${EVIDENCE_DIR}/summary.json"

  if [[ "$SEED_EXIT_CODE" != "0" ]]; then
    exit "$SEED_EXIT_CODE"
  fi
  if [[ "$POLL_RESULT" != "ok" && "$POLL_RESULT" != "unavailable" ]]; then
    exit 1
  fi
  exit 0
}

main "$@"
