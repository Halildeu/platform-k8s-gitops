#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 / platform-k8s-gitops#1768 AgentPC2 first-install evidence verifier.
#
# This verifier consumes endpoint-local evidence produced by
# agentpc2-first-install-bootstrap.ps1. It does not run endpoint commands, open
# remote sessions, or claim platform-agent#208 acceptance. A passing result only
# proves the approved first-install seed produced the expected service/config
# state needed before the product-channel #208 acceptance workflow is rerun.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

EVIDENCE_DIR="${EVIDENCE_DIR:-}"
SUMMARY_FILE="${SUMMARY_FILE:-}"
OUTPUT_FILE="${OUTPUT_FILE:-}"

EXPECTED_SCHEMA="${EXPECTED_SCHEMA:-faz22.1768.agentpc2-first-install-bootstrap.endpoint.v1}"
EXPECTED_STATUS="${EXPECTED_STATUS:-installed-service-running}"
EXPECTED_HOSTNAME="${EXPECTED_HOSTNAME:-AgentPc2}"
EXPECTED_TARGET_VERSION="${EXPECTED_TARGET_VERSION:-$EXPECTED_AGENT_VERSION}"
EXPECTED_AUTHENTICODE_STATUS="${EXPECTED_AUTHENTICODE_STATUS:-Valid}"
EXPECTED_AUTO_ENROLL_API_URL="${EXPECTED_AUTO_ENROLL_API_URL:-https://mtls.testai.acik.com/api/v1/endpoint-agent}"
EXPECTED_AUTO_ENROLL_SAN_PREFIX="${EXPECTED_AUTO_ENROLL_SAN_PREFIX:-adcomputer:}"
EXPECTED_REMOTE_BRIDGE_BROKER_ADDR="${EXPECTED_REMOTE_BRIDGE_BROKER_ADDR:-remote-bridge-mtls.testai.acik.com:443}"
EXPECTED_REMOTE_BRIDGE_TLS_SERVER_NAME="${EXPECTED_REMOTE_BRIDGE_TLS_SERVER_NAME:-remote-bridge-mtls.testai.acik.com}"
EXPECTED_REMOTE_BRIDGE_PERMIT_KID="${EXPECTED_REMOTE_BRIDGE_PERMIT_KID:-rb-test-denetim-20260617-01}"
EXPECTED_REMOTE_BRIDGE_PERMIT_PUBLIC_KEY_SHA256="${EXPECTED_REMOTE_BRIDGE_PERMIT_PUBLIC_KEY_SHA256:-0a92abcd8f84619fb8f14f530beb94cbdc4e0981c9eb14a4756bdc85175a1110}"
EXPECTED_ADCOMPUTER_GUID="${EXPECTED_ADCOMPUTER_GUID:-fa2d1ad6-a0a8-4101-ab77-9f2a0b25742a}"

CHECKS='[]'
FINDINGS='[]'

usage() {
  cat <<'EOF'
Usage:
  agentpc2-first-install-bootstrap-evidence-verify.sh --evidence-dir <dir> [--summary-file <file>] [--output-file <file>]

Environment overrides are supported for EXPECTED_* values.
EOF
}

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 2
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

json_bool() {
  if [[ "$1" == "true" ]]; then
    printf true
  else
    printf false
  fi
}

add_check() {
  local name="$1" ok="$2" detail="${3:-}"
  CHECKS="$(jq -cn \
    --argjson arr "$CHECKS" \
    --arg name "$name" \
    --arg detail "$detail" \
    --argjson ok "$(json_bool "$ok")" \
    '$arr + [{name:$name, ok:$ok, detail:$detail}]')"
}

add_finding() {
  local severity="$1" code="$2" message="$3"
  FINDINGS="$(jq -cn \
    --argjson arr "$FINDINGS" \
    --arg severity "$severity" \
    --arg code "$code" \
    --arg message "$message" \
    '$arr + [{severity:$severity, code:$code, message:$message}]')"
}

canonical_dir() {
  local path="$1"
  (cd "$path" 2>/dev/null && pwd -P) || return 1
}

file_sha256() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print tolower($1)}'
  else
    shasum -a 256 "$path" | awk '{print tolower($1)}'
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --evidence-dir)
        EVIDENCE_DIR="${2:-}"
        shift 2
        ;;
      --summary-file)
        SUMMARY_FILE="${2:-}"
        shift 2
        ;;
      --output-file)
        OUTPUT_FILE="${2:-}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
  done
}

jq_get() {
  local filter="$1"
  jq -r "$filter" "$SUMMARY_FILE"
}

assert_json_eq() {
  local check="$1" filter="$2" expected="$3" actual
  actual="$(jq_get "$filter")"
  if [[ "$actual" == "$expected" ]]; then
    add_check "$check" true "$actual"
  else
    add_check "$check" false "expected=${expected} actual=${actual}"
    add_finding error "$check" "Expected ${expected}, got ${actual}."
  fi
}

assert_json_eq_ci() {
  local check="$1" filter="$2" expected="$3" actual
  actual="$(jq_get "$filter")"
  if [[ "$(lower "$actual")" == "$(lower "$expected")" ]]; then
    add_check "$check" true "$actual"
  else
    add_check "$check" false "expected=${expected} actual=${actual}"
    add_finding error "$check" "Expected ${expected}, got ${actual}."
  fi
}

check_required_files() {
  local rel
  for rel in \
    agentpc2-first-install-bootstrap-summary.json \
    agentpc2-first-install-bootstrap-transcript.log \
    endpoint-agent-log-tail.txt \
    endpoint-agent-remote-bridge-signals.txt
  do
    if [[ -f "${EVIDENCE_DIR}/${rel}" ]]; then
      add_check "file:${rel}" true "$(file_sha256 "${EVIDENCE_DIR}/${rel}")"
    else
      add_check "file:${rel}" false "missing"
      add_finding error "missing-file" "Required endpoint evidence file is missing: ${rel}."
    fi
  done
}

check_service() {
  local state start_mode start_name
  state="$(jq_get 'if (.service|type)=="array" then (.service[0].State // .service[0].state // "") else (.service.State // .service.state // "") end')"
  start_mode="$(jq_get 'if (.service|type)=="array" then (.service[0].StartMode // .service[0].startMode // "") else (.service.StartMode // .service.startMode // "") end')"
  start_name="$(jq_get 'if (.service|type)=="array" then (.service[0].StartName // .service[0].startName // "") else (.service.StartName // .service.startName // "") end')"

  if [[ "$state" == "Running" ]]; then
    add_check service-running true "$state"
  else
    add_check service-running false "$state"
    add_finding error service-not-running "EndpointAgent service is not Running."
  fi

  if [[ "$start_mode" == "Auto" || "$start_mode" == "Automatic" ]]; then
    add_check service-start-mode true "$start_mode"
  else
    add_check service-start-mode false "$start_mode"
    add_finding error service-start-mode "EndpointAgent StartMode is not Auto/Automatic."
  fi

  if [[ "$start_name" == "LocalSystem" || "$start_name" == "NT AUTHORITY\\LocalSystem" ]]; then
    add_check service-start-name true "$start_name"
  else
    add_check service-start-name false "$start_name"
    add_finding error service-start-name "EndpointAgent StartName is not LocalSystem."
  fi
}

check_service_environment() {
  local env_ok sensitive_ok
  env_ok="$(jq -r \
    --arg broker "$EXPECTED_REMOTE_BRIDGE_BROKER_ADDR" \
    --arg tls "$EXPECTED_REMOTE_BRIDGE_TLS_SERVER_NAME" \
    '
      def env_value($k): (.redactedServiceEnvironment // [] | map(select(.Key == $k)) | .[0].Value // "");
      (
        (env_value("ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED") | ascii_downcase) == "true"
        and env_value("ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR") == $broker
        and env_value("ENDPOINT_AGENT_REMOTE_BRIDGE_TLS_SERVER_NAME") == $tls
        and (env_value("ENDPOINT_AGENT_REMOTE_BRIDGE_OPERATIONS_ENABLED") | ascii_downcase) == "true"
      )
    ' "$SUMMARY_FILE")"

  if [[ "$env_ok" == "true" ]]; then
    add_check service-env-remote-bridge true "required remote bridge env present"
  else
    add_check service-env-remote-bridge false "missing or mismatched remote bridge env"
    add_finding error service-env-remote-bridge "Required EndpointAgent remote bridge service environment values are missing or mismatched."
  fi

  sensitive_ok="$(jq -r '
    [
      (.redactedServiceEnvironment // [])[]
      | select(.Key | test("TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL"; "i"))
      | select(.Value != "<redacted>")
    ] | length == 0
  ' "$SUMMARY_FILE")"

  if [[ "$sensitive_ok" == "true" ]]; then
    add_check service-env-redaction true "sensitive-looking keys redacted"
  else
    add_check service-env-redaction false "unredacted sensitive-looking service env"
    add_finding error service-env-redaction "Service environment contains an unredacted sensitive-looking value."
  fi
}

check_client_auth_cert() {
  local ok
  ok="$(jq -r --arg guid "$EXPECTED_ADCOMPUTER_GUID" '
    [
      (.clientAuthCerts // [])[]
      | select((.HasPrivateKey == true) or (.HasPrivateKey == "True"))
      | select((.Issuer // "") | test("Acik-Endpoint-CA"))
      | select((.SAN // "") | ascii_downcase | contains("adcomputer:" + ($guid | ascii_downcase)))
    ] | length > 0
  ' "$SUMMARY_FILE")"

  if [[ "$ok" == "true" ]]; then
    add_check client-auth-adcomputer-cert true "$EXPECTED_ADCOMPUTER_GUID"
  else
    add_check client-auth-adcomputer-cert false "missing private-key client cert with expected adcomputer SAN"
    add_finding error client-auth-adcomputer-cert "No private-key client-auth cert from Acik-Endpoint-CA contains expected adcomputer SAN."
  fi
}

check_secret_scan() {
  local scan hits_file
  hits_file="$(mktemp)"
  set +e
  grep -RInE \
    'BEGIN [A-Z ]*PRIVATE KEY|Authorization:[[:space:]]*Bearer[[:space:]][A-Za-z0-9_.-]+|access[_-]?token[[:space:]]*[:=]|refresh[_-]?token[[:space:]]*[:=]|client[_-]?secret[[:space:]]*[:=]|KC_ADMIN_PASSWORD|ENDPOINT_AGENT_ENROLLMENT_TOKEN|password[[:space:]]*[:=][[:space:]]*[^<[:space:]]' \
    "$EVIDENCE_DIR" > "$hits_file" 2>/dev/null
  scan="$?"
  set -e

  if [[ "$scan" == "0" ]]; then
    add_check secret-scan false "$(tr '\n' ';' < "$hits_file" | cut -c 1-500)"
    add_finding error secret-scan "Potential secret material found in endpoint evidence."
  else
    add_check secret-scan true "no private key/bearer/token/password patterns"
  fi
  rm -f "$hits_file"
}

write_summary() {
  local generated_at status accepted reason
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  accepted="$(jq -r '[.[] | select(.ok == false)] | length == 0' <<<"$CHECKS")"
  if [[ "$accepted" == "true" ]]; then
    status="accepted-bootstrap-evidence"
    reason="endpoint-local-bootstrap-evidence-valid"
  else
    status="rejected-bootstrap-evidence"
    reason="endpoint-local-bootstrap-evidence-invalid"
  fi

  jq -n \
    --arg schema "faz22.1768.agentpc2-first-install-bootstrap.ingest.v1" \
    --arg generatedAt "$generated_at" \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg evidenceDir "$EVIDENCE_DIR" \
    --arg summaryFile "$SUMMARY_FILE" \
    --arg targetHostname "$EXPECTED_HOSTNAME" \
    --arg releaseId "$EXPECTED_RELEASE_ID" \
    --arg targetVersion "$EXPECTED_TARGET_VERSION" \
    --arg brokerAddr "$EXPECTED_REMOTE_BRIDGE_BROKER_ADDR" \
    --arg tlsServerName "$EXPECTED_REMOTE_BRIDGE_TLS_SERVER_NAME" \
    --arg permitKeyId "$EXPECTED_REMOTE_BRIDGE_PERMIT_KID" \
    --argjson checks "$CHECKS" \
    --argjson findings "$FINDINGS" \
    '{
      schema:$schema,
      generatedAt:$generatedAt,
      status:$status,
      reason:$reason,
      evidence:{dir:$evidenceDir, summary:$summaryFile},
      expected:{
        hostname:$targetHostname,
        releaseId:$releaseId,
        targetVersion:$targetVersion,
        remoteBridge:{brokerAddr:$brokerAddr, tlsServerName:$tlsServerName, permitKeyId:$permitKeyId}
      },
      checks:$checks,
      findings:$findings,
      boundary:{
        proves:[
          "AgentPC2 endpoint-local first-install evidence passed verifier checks",
          "Expected " + $releaseId + " binary/install/signer metadata is present in endpoint evidence",
          "EndpointAgent service is running with outbound 443/SNI remote bridge configuration",
          "Private-key client-auth certificate with expected adcomputer SAN is present"
        ],
        doesNotProve:[
          "platform-agent#208 constrained operation acceptance",
          "HELLO/permit/constrained-operation/negative/audit product-channel success",
          "broad GPO/MSI rollout",
          "production/domain-wide support readiness",
          "TPM/device-key hardware attestation"
        ]
      }
    }' > "$OUTPUT_FILE"

  jq . "$OUTPUT_FILE"

  if [[ "$accepted" != "true" ]]; then
    exit 1
  fi
}

main() {
  parse_args "$@"
  need_cmd jq
  need_cmd grep

  [[ -n "$EVIDENCE_DIR" ]] || die "--evidence-dir is required"
  [[ -d "$EVIDENCE_DIR" ]] || die "evidence directory not found: $EVIDENCE_DIR"
  EVIDENCE_DIR="$(canonical_dir "$EVIDENCE_DIR")" || die "cannot resolve evidence directory"

  if [[ -z "$SUMMARY_FILE" ]]; then
    SUMMARY_FILE="${EVIDENCE_DIR}/agentpc2-first-install-bootstrap-summary.json"
  fi
  [[ -f "$SUMMARY_FILE" ]] || die "summary file not found: $SUMMARY_FILE"

  if [[ -z "$OUTPUT_FILE" ]]; then
    OUTPUT_FILE="${EVIDENCE_DIR}/bootstrap-evidence-verifier-summary.json"
  fi

  check_required_files
  assert_json_eq schema '.schema // ""' "$EXPECTED_SCHEMA"
  assert_json_eq status '.status // ""' "$EXPECTED_STATUS"
  assert_json_eq_ci hostname '.computerName // ""' "$EXPECTED_HOSTNAME"
  assert_json_eq release-id '.release.id // ""' "$EXPECTED_RELEASE_ID"
  assert_json_eq target-version '.release.targetVersion // ""' "$EXPECTED_TARGET_VERSION"
  assert_json_eq_ci binary-sha256 '.release.binarySha256 // ""' "$EXPECTED_AGENT_SHA256"
  assert_json_eq_ci install-ps1-sha256 '.release.installPs1Sha256 // ""' "$EXPECTED_INSTALL_PS1_SHA256"
  assert_json_eq_ci signer-thumbprint '.release.signerThumbprint // ""' "$EXPECTED_SIGNER_THUMBPRINT"
  assert_json_eq signing-tier '.release.signingTier // ""' "$EXPECTED_SIGNING_TIER"
  assert_json_eq authenticode-status '.release.authenticodeStatus // ""' "$EXPECTED_AUTHENTICODE_STATUS"
  assert_json_eq auto-enroll-api '.autoEnroll.apiUrl // ""' "$EXPECTED_AUTO_ENROLL_API_URL"
  assert_json_eq auto-enroll-san-prefix '.autoEnroll.certSANURIPrefix // ""' "$EXPECTED_AUTO_ENROLL_SAN_PREFIX"
  assert_json_eq remote-bridge-broker '.remoteBridge.brokerAddr // ""' "$EXPECTED_REMOTE_BRIDGE_BROKER_ADDR"
  assert_json_eq remote-bridge-tls '.remoteBridge.tlsServerName // ""' "$EXPECTED_REMOTE_BRIDGE_TLS_SERVER_NAME"
  assert_json_eq remote-bridge-ops '.remoteBridge.operationsEnabled | tostring' "true"
  assert_json_eq remote-bridge-permit-kid '.remoteBridge.permitKeyId // ""' "$EXPECTED_REMOTE_BRIDGE_PERMIT_KID"
  assert_json_eq_ci remote-bridge-permit-key-sha '.remoteBridge.permitBrokerPublicKeySha256 // ""' "$EXPECTED_REMOTE_BRIDGE_PERMIT_PUBLIC_KEY_SHA256"

  check_service
  check_service_environment
  check_client_auth_cert
  check_secret_scan
  write_summary
}

main "$@"
