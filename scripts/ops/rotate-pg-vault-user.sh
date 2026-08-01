#!/usr/bin/env bash
# scripts/ops/rotate-pg-vault-user.sh
#
# PR-S1 (PERF-INIT-V2): PG user password rotation runbook tooling.
#
# Vault canonical password -> shared-user precheck -> PG ALTER USER ->
# ESO force-sync + K8s Secret value compare -> rollout restart -> pod
# Ready + /actuator/health/readiness body check (DB indicator UP).
#
# Usage:
#   rotate-pg-vault-user.sh <service> [--cluster k3d-test|k3d-prod] [--dry-run]
#
# Examples:
#   rotate-pg-vault-user.sh report-service
#   rotate-pg-vault-user.sh permission-service --cluster k3d-test
#
# Companion: docs/RB-pg-vault-secret-parity.md
#            docs/policy/alphanumeric-password-policy.md
#            scripts/ops/kc-bootstrap-admin-recovery.sh

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_NAME
readonly AUDIT_LOG="${HOME}/.claude/logs/pg-vault-rotation.log"
mkdir -p "$(dirname "${AUDIT_LOG}")"

# Acceptance gate strictness (default: strict; set to 1 to allow degraded
# acceptance when /actuator/health/readiness has no DB indicator).
ALLOW_READY_ONLY="${ALLOW_READY_ONLY:-0}"

log() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '[%s] [%s] %s\n' "${ts}" "${SCRIPT_NAME}" "$*" | tee -a "${AUDIT_LOG}"
}

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} <service> [options]

Arguments:
  service            Vault path tail under kv/platform/<service>

Options:
  --cluster CTX            Kubernetes context (default: k3d-test)
  --namespace NS           Namespace (default: platform-<env>)
  --dry-run                Print actions but do not execute mutations
  --allow-ready-only       Allow acceptance when /actuator/health/readiness has
                           no DB indicator (pod Ready=True only). Default off
                           (strict mode: DB indicator UP required).
  --help                   This help

Environment:
  VAULT_TOKEN        Required. Default: /srv/platform/secrets/backup-auth/vault-init-<env>.json
  PG_CONTAINER       Default: platform-pg-<env>
  VAULT_CONTAINER    Default: platform-vault-<env>

Exit codes:
  0   success
  1   invalid usage
  2   pre-flight failure
  3   alphanumeric / length policy violation
  4   shared-user parity mismatch (multiple Vault paths, different passwords)
  5   smoke failure (pod auth or health/readiness DB UP)
EOF
}

# --- Argument parsing -------------------------------------------------------

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

SERVICE=""
CLUSTER_CTX="k3d-test"
NAMESPACE=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster)
      CLUSTER_CTX="$2"
      shift 2
      ;;
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --allow-ready-only)
      ALLOW_READY_ONLY=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      if [[ -z "${SERVICE}" ]]; then
        SERVICE="$1"
      else
        echo "Unexpected positional argument: $1" >&2
        usage
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "${SERVICE}" ]]; then
  usage
  exit 1
fi

if [[ "${CLUSTER_CTX}" == "k3d-test" ]]; then
  ENV_NAME="test"
elif [[ "${CLUSTER_CTX}" == "k3d-prod" ]]; then
  ENV_NAME="prod"
else
  echo "Unsupported cluster context: ${CLUSTER_CTX}" >&2
  exit 1
fi

NAMESPACE="${NAMESPACE:-platform-${ENV_NAME}}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-${ENV_NAME}}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-${ENV_NAME}}"

# --- Vault token lookup -----------------------------------------------------

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  # Host 53->15: the init files moved to /srv/platform/secrets/ and
  # ~/bootstrap-drill/ no longer exists on the host. Canonical location first,
  # legacy second, so an older restore still resolves.
  VAULT_INIT_FILE="/srv/platform/secrets/backup-auth/vault-init-${ENV_NAME}.json"
  [[ -r "${VAULT_INIT_FILE}" ]] \
    || VAULT_INIT_FILE="${HOME}/bootstrap-drill/vault-init-${ENV_NAME}.json"
  if [[ ! -r "${VAULT_INIT_FILE}" ]]; then
    log "FATAL: VAULT_TOKEN unset and ${VAULT_INIT_FILE} not readable"
    exit 2
  fi
  VAULT_TOKEN="$(jq -r '.root_token' "${VAULT_INIT_FILE}")"
  if [[ -z "${VAULT_TOKEN}" || "${VAULT_TOKEN}" == "null" ]]; then
    log "FATAL: could not extract root_token from ${VAULT_INIT_FILE}"
    exit 2
  fi
fi
export VAULT_TOKEN

mask() {
  local s="$1"
  local len=${#s}
  if [[ ${len} -le 6 ]]; then
    printf '****'
  else
    printf '%s****%s' "${s:0:4}" "${s:$((len-2))}"
  fi
}

# Hash a string (sha256) for parity comparison without leaking value
hash_value() {
  printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
}

# Fetch a Vault path's username + password (returns "user:pass" on stdout)
fetch_vault_creds() {
  local path="$1"
  local data
  data="$(docker exec -e VAULT_TOKEN "${VAULT_CONTAINER}" \
    vault kv get -mount=kv -format=json "${path}" 2>/dev/null || echo '{}')"
  local u p
  u="$(echo "${data}" | jq -r '.data.data.db_username // .data.data.username // empty')"
  p="$(echo "${data}" | jq -r '.data.data.db_password // .data.data.password // empty')"
  printf '%s:%s' "${u}" "${p}"
}

# --- Step 1: fetch canonical credentials from Vault -------------------------

log "Service=${SERVICE} cluster=${CLUSTER_CTX} ns=${NAMESPACE} dry-run=${DRY_RUN}"

VAULT_PATH="platform/${SERVICE}"
log "Step 1/8 — fetching canonical credentials from Vault (kv/${VAULT_PATH})"

CREDS="$(fetch_vault_creds "${VAULT_PATH}")"
PG_USER="${CREDS%%:*}"
PG_PASSWORD="${CREDS#*:}"

if [[ -z "${PG_USER}" || -z "${PG_PASSWORD}" ]]; then
  log "FATAL: missing db_username/db_password at kv/${VAULT_PATH}"
  exit 2
fi
log "  -> user='${PG_USER}' password='$(mask "${PG_PASSWORD}")' (len=${#PG_PASSWORD})"

# --- Step 2: alphanumeric + length policy enforcement -----------------------

log "Step 2/8 — alphanumeric + minimum-length policy check"

if [[ ! "${PG_PASSWORD}" =~ ^[A-Za-z0-9]+$ ]]; then
  log "FATAL: Vault password for ${SERVICE} contains non-alphanumeric chars"
  log "       Policy: docs/policy/alphanumeric-password-policy.md"
  exit 3
fi

if [[ ${#PG_PASSWORD} -lt 24 ]]; then
  log "FATAL: Vault password for ${SERVICE} is ${#PG_PASSWORD} chars (<24 minimum)"
  log "       Policy: docs/policy/alphanumeric-password-policy.md"
  exit 3
fi

# PG SQL identifier safety — username must match standard identifier pattern
if [[ ! "${PG_USER}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  log "FATAL: PG_USER '${PG_USER}' is not a safe SQL identifier (^[A-Za-z_][A-Za-z0-9_]*$)"
  exit 3
fi

log "  -> policy OK (alphanumeric, len=${#PG_PASSWORD} >= 24, identifier-safe)"

# --- Step 3: shared-user parity precheck ------------------------------------

# Some platform services share the same PG user (e.g. `platform` user used by
# permission/variant/core-data/etc.). If two Vault paths declare the same
# username with DIFFERENT passwords, sequential rotation breaks every other
# service. Detect that BEFORE issuing ALTER USER.
log "Step 3/8 — shared-user parity precheck across all kv/platform/* paths"

ALL_SERVICES="$(docker exec -e VAULT_TOKEN "${VAULT_CONTAINER}" \
  vault kv list -format=json kv/platform 2>/dev/null \
  | jq -r '.[]' 2>/dev/null || echo "")"

OUR_HASH="$(hash_value "${PG_PASSWORD}")"
MISMATCH=0
MISMATCH_LIST=""

while IFS= read -r svc; do
  [[ -z "${svc}" ]] && continue
  [[ "${svc}" == "${SERVICE}" ]] && continue
  # Skip non-service paths (subdirectories like notify/ or keycloak/)
  if [[ "${svc}" == */ ]]; then
    continue
  fi

  CREDS_OTHER="$(fetch_vault_creds "platform/${svc}")"
  OTHER_USER="${CREDS_OTHER%%:*}"
  OTHER_PASS="${CREDS_OTHER#*:}"

  if [[ -z "${OTHER_USER}" || -z "${OTHER_PASS}" ]]; then
    continue
  fi

  if [[ "${OTHER_USER}" == "${PG_USER}" ]]; then
    OTHER_HASH="$(hash_value "${OTHER_PASS}")"
    if [[ "${OTHER_HASH}" != "${OUR_HASH}" ]]; then
      MISMATCH=1
      MISMATCH_LIST+="    - kv/platform/${svc} (hash=${OTHER_HASH:0:12}...)\n"
    fi
  fi
done <<< "${ALL_SERVICES}"

if [[ ${MISMATCH} -eq 1 ]]; then
  log "FATAL: shared-user parity violation for PG user '${PG_USER}'"
  log "       This Vault path (kv/${VAULT_PATH}) hash=${OUR_HASH:0:12}..."
  log "       Conflicting paths with SAME username but DIFFERENT password:"
  printf '%b' "${MISMATCH_LIST}" | tee -a "${AUDIT_LOG}"
  log "       Action: reconcile Vault paths to single canonical, then re-run."
  log "       Helper: docs/RB-pg-vault-secret-parity.md §3 'shared user reconciliation'"
  exit 4
fi
log "  -> shared-user parity OK (no conflicting Vault paths for user '${PG_USER}')"

# --- Step 4: PG ALTER USER (literal password via stdin) ---------------------

log "Step 4/8 — ALTER USER ${PG_USER} on ${PG_CONTAINER}"

# stdin pipe avoids the 2026-05-10 bash-quoting bug (where `'$VAULT_PW'`
# literal reached PG). printf is more deterministic than echo for arbitrary
# bytes (though alphanumeric password is safe with echo too).
ALTER_SQL="ALTER USER ${PG_USER} WITH PASSWORD '${PG_PASSWORD}';"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "DRY-RUN: would execute ALTER USER (password masked)"
else
  if printf '%s\n' "${ALTER_SQL}" | docker exec -i "${PG_CONTAINER}" \
        psql -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null 2>&1; then
    log "  -> ALTER USER succeeded"
  else
    log "FATAL: ALTER USER failed (see PG container logs)"
    exit 5
  fi
fi

# --- Step 5: ESO force-sync + K8s Secret value compare ---------------------

log "Step 5/8 — ESO force-sync + K8s Secret value parity check"

ES_NAME="${SERVICE}-secrets"

if kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
     get externalsecret "${ES_NAME}" >/dev/null 2>&1; then

  # Helper: read the password field from the K8s Secret and return its
  # sha256 hash (empty string if not present).
  read_secret_hash() {
    local sec_pw sec_hash
    sec_pw="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
      get secret "${ES_NAME}" -o json 2>/dev/null \
      | jq -r '.data | (.SPRING_DATASOURCE_PASSWORD // .DB_PASSWORD // .password // empty)' \
      | base64 -d 2>/dev/null || echo "")"
    if [[ -z "${sec_pw}" ]]; then
      echo ""
      return
    fi
    sec_hash="$(hash_value "${sec_pw}")"
    echo "${sec_hash}"
  }

  # Capture pre-state for audit.
  PRE_RV="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
    get secret "${ES_NAME}" -o jsonpath='{.metadata.resourceVersion}' 2>/dev/null || echo "0")"

  SECRET_OK=0

  # Idempotency check — if Secret already matches Vault canonical, no-op.
  PRE_HASH="$(read_secret_hash)"
  if [[ -n "${PRE_HASH}" && "${PRE_HASH}" == "${OUR_HASH}" ]]; then
    log "  -> Secret already in parity with Vault canonical (hash=${PRE_HASH:0:16}...); no annotation needed"
    SECRET_OK=1
  fi

  if [[ ${SECRET_OK} -ne 1 ]]; then
    if [[ ${DRY_RUN} -eq 0 ]]; then
      kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
        annotate externalsecret "${ES_NAME}" \
        "force-sync=$(date +%s)" --overwrite >/dev/null
    fi

    # Wait up to 30s for the Secret's password hash to converge on the
    # Vault canonical. The resourceVersion bump is logged as audit but
    # is NOT the acceptance gate (ESO may no-op write if value already
    # matched; the hash comparison is authoritative).
    local_deadline=$(($(date +%s) + 30))
    while [[ $(date +%s) -lt ${local_deadline} ]]; do
      CUR_HASH="$(read_secret_hash)"
      if [[ "${CUR_HASH}" == "${OUR_HASH}" ]]; then
        CUR_RV="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
          get secret "${ES_NAME}" -o jsonpath='{.metadata.resourceVersion}' 2>/dev/null || echo "0")"
        log "  -> Secret hash matches Vault canonical (resourceVersion ${PRE_RV} -> ${CUR_RV})"
        SECRET_OK=1
        break
      fi
      sleep 2
    done
  fi

  if [[ ${SECRET_OK} -ne 1 && ${DRY_RUN} -eq 0 ]]; then
    log "FATAL: K8s Secret did not reach parity with Vault within 30s"
    log "       pre_rv=${PRE_RV} cur_rv=${CUR_RV:-unknown}"
    log "       Vault canonical hash=${OUR_HASH:0:16}... but Secret value differs"
    log "       ExternalSecret '${ES_NAME}' exists — parity is mandatory."
    log "       Inspect: kubectl describe externalsecret ${ES_NAME} -n ${NAMESPACE}"
    exit 5
  fi
else
  log "  -> no externalsecret/${ES_NAME} (service uses direct Secret); skipping ESO parity check"
fi

# --- Step 6: rollout restart -----------------------------------------------

log "Step 6/8 — rollout restart deploy/${SERVICE}"

if kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
     get deploy "${SERVICE}" >/dev/null 2>&1; then

  if [[ ${DRY_RUN} -eq 0 ]]; then
    kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
      rollout restart deploy/"${SERVICE}" >/dev/null

    if ! kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
            rollout status deploy/"${SERVICE}" --timeout=240s; then
      log "FATAL: rollout did not complete within 240s"
      exit 5
    fi
  else
    log "DRY-RUN: would rollout restart deploy/${SERVICE}"
  fi
else
  log "FATAL: deploy/${SERVICE} not found in ${NAMESPACE}"
  exit 5
fi

# --- Step 7: pod-network DB indicator smoke (NOT 127.0.0.1=trust) ----------

log "Step 7/8 — pod /actuator/health/readiness DB indicator check"

if [[ ${DRY_RUN} -eq 0 ]]; then
  POD_NAME="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
    get pod -l app.kubernetes.io/name="${SERVICE}" \
    --field-selector status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")"

  if [[ -z "${POD_NAME}" ]]; then
    log "FATAL: no running pod for ${SERVICE} after rollout"
    exit 5
  fi

  if ! kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
          wait --for=condition=Ready "pod/${POD_NAME}" --timeout=60s >/dev/null 2>&1; then
    log "FATAL: pod/${POD_NAME} not Ready within 60s"
    log "       Inspect: kubectl logs ${POD_NAME} --tail=50"
    exit 5
  fi

  # Hit /actuator/health/readiness inside the pod (management port 8081).
  # The default Spring Boot 3 readiness group does NOT include DB by default,
  # but our backend services explicitly opt in via
  # `management.endpoint.health.group.readiness.include=db,readinessState`.
  # If a service doesn't have that config, this smoke degrades to pod Ready
  # (still a strong signal because Hikari startup would have failed).
  HEALTH_BODY="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
    exec "${POD_NAME}" -- \
    sh -c 'wget -qO- http://127.0.0.1:8081/actuator/health/readiness 2>/dev/null || curl -sS --fail-with-body http://127.0.0.1:8081/actuator/health/readiness 2>/dev/null' \
    2>/dev/null || echo '{}')"

  STATUS="$(echo "${HEALTH_BODY}" | jq -r '.status // "UNKNOWN"' 2>/dev/null || echo "PARSE_ERR")"

  if [[ "${STATUS}" == "UP" ]]; then
    DB_STATUS="$(echo "${HEALTH_BODY}" | jq -r '.components.db.status // .components.dataSource.status // "ABSENT"' 2>/dev/null || echo "ABSENT")"
    if [[ "${DB_STATUS}" == "UP" ]]; then
      log "  -> /actuator/health/readiness UP, db=UP (DB auth proven)"
    elif [[ "${DB_STATUS}" == "ABSENT" ]]; then
      # Spring Boot default readiness group does NOT include db; service
      # must opt in via `management.endpoint.health.group.readiness.include=db`.
      # If absent, we cannot prove DB auth via the readiness endpoint.
      if [[ ${ALLOW_READY_ONLY} -eq 1 ]]; then
        log "WARN: db indicator ABSENT; --allow-ready-only override active (DB auth NOT proven, pod Ready=True only)"
        log "      Action: add 'management.endpoint.health.group.readiness.include=db' to ${SERVICE} config to enable strict gate"
      else
        log "FATAL: db indicator ABSENT in /actuator/health/readiness body"
        log "       This means readiness group does not include the DB contributor;"
        log "       pod Ready=True alone is NOT proof that DB auth works."
        log "       Fix: add 'management.endpoint.health.group.readiness.include=db' to service config."
        log "       Or override: re-run with --allow-ready-only (degraded acceptance)."
        log "       Body: ${HEALTH_BODY}"
        exit 5
      fi
    else
      log "FATAL: readiness UP but db indicator=${DB_STATUS}"
      log "       Body: ${HEALTH_BODY}"
      exit 5
    fi
  elif [[ "${STATUS}" == "UNKNOWN" || "${STATUS}" == "PARSE_ERR" ]]; then
    if [[ ${ALLOW_READY_ONLY} -eq 1 ]]; then
      log "WARN: readiness endpoint unreachable; --allow-ready-only override active"
    else
      log "FATAL: /actuator/health/readiness unreachable inside pod"
      log "       Body: ${HEALTH_BODY}"
      log "       Override: --allow-ready-only flag (degraded acceptance)"
      exit 5
    fi
  else
    log "FATAL: /actuator/health/readiness status=${STATUS}"
    log "       Body: ${HEALTH_BODY}"
    exit 5
  fi
fi

log "Step 8/8 — DONE — rotation for ${SERVICE} on ${CLUSTER_CTX} completed"
exit 0
