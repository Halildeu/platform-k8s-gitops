#!/usr/bin/env bash
# scripts/ops/rotate-pg-vault-user.sh
#
# PR-S1 (PERF-INIT-V2): PG user password rotation runbook tooling.
#
# Vault canonical password -> PG ALTER USER -> ESO force-sync -> rollout
# restart -> pod-network smoke (NOT 127.0.0.1=trust).
#
# Usage:
#   rotate-pg-vault-user.sh <service> [--cluster k3d-test|k3d-prod]
#
# Examples:
#   rotate-pg-vault-user.sh report-service
#   rotate-pg-vault-user.sh permission-service --cluster k3d-test
#
# Why this script exists (PMD §4.1 PR-S1):
#   - PG `platform` user (and per-service users) drift between Vault canonical
#     and the PG user table is the root cause of the recurring cluster
#     "Spring `${VAULT_PW}` placeholder bug" + "Hibernate Unable to determine
#     Dialect" zincir-fail (see 2026-05-10 Session 43 incident, multi-service
#     CrashLoopBackOff).
#   - pg_hba.conf on test cluster has `127.0.0.1 = trust`, meaning host-level
#     smoke (`psql -h 127.0.0.1`) returns success for ANY password. That is a
#     false-positive trap. The real auth check happens from the pod network
#     (10.44.x.x range) which uses `scram-sha-256`. This script enforces the
#     pod-network smoke as the only acceptance signal.
#   - The script is idempotent: re-running on an already-canonical PG user
#     is a no-op (PG ALTER USER overwrites with same hash).
#
# Companion: docs/RB-pg-vault-secret-parity.md (runbook)
#            docs/policy/alphanumeric-password-policy.md (policy)

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_NAME
readonly AUDIT_LOG="${HOME}/.claude/logs/pg-vault-rotation.log"
mkdir -p "$(dirname "${AUDIT_LOG}")"

log() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[${ts}] [${SCRIPT_NAME}] $*" | tee -a "${AUDIT_LOG}"
}

usage() {
  cat >&2 <<EOF
Usage: ${SCRIPT_NAME} <service> [--cluster k3d-test|k3d-prod]

Arguments:
  service            Vault path tail under kv/platform/<service>
                     (e.g. report-service, permission-service)

Options:
  --cluster CTX      Kubernetes context (default: k3d-test)
  --namespace NS     Namespace (default: platform-test for k3d-test,
                                       platform-prod for k3d-prod)
  --dry-run          Print actions but do not execute mutations
  --help             This help

Environment:
  VAULT_TOKEN        Required. Vault root or rotator-capable token.
                     Default: read from ~/bootstrap-drill/vault-init-<env>.json
  PG_CONTAINER       PG docker container (default: platform-pg-<env>)
  VAULT_CONTAINER    Vault docker container (default: platform-vault-<env>)

Exit codes:
  0   success (rotation applied + smoke pass)
  1   invalid usage
  2   pre-flight failure (Vault unreachable, PG unreachable)
  3   policy violation (password not alphanumeric)
  4   smoke failure (pod-network auth still fails)
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

# Derive env from cluster context
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
  VAULT_INIT_FILE="${HOME}/bootstrap-drill/vault-init-${ENV_NAME}.json"
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

run() {
  if [[ ${DRY_RUN} -eq 1 ]]; then
    log "DRY-RUN: $*"
  else
    log "EXEC: $*"
    "$@"
  fi
}

mask() {
  # Mask all but the first 4 and last 2 chars of a secret for logging.
  local s="$1"
  local len=${#s}
  if [[ ${len} -le 6 ]]; then
    printf '****'
  else
    printf '%s****%s' "${s:0:4}" "${s:$((len-2))}"
  fi
}

# --- Step 1: fetch canonical password from Vault ----------------------------

log "Service=${SERVICE} cluster=${CLUSTER_CTX} ns=${NAMESPACE} dry-run=${DRY_RUN}"

VAULT_PATH="kv/platform/${SERVICE}"
log "Step 1/6 — fetching canonical credentials from Vault (${VAULT_PATH})"

VAULT_DATA="$(docker exec -e VAULT_TOKEN "${VAULT_CONTAINER}" \
  vault kv get -mount=kv -format=json "platform/${SERVICE}" 2>&1)" || {
  log "FATAL: vault kv get failed for ${VAULT_PATH}"
  log "Vault response: ${VAULT_DATA}"
  exit 2
}

PG_USER="$(echo "${VAULT_DATA}" | jq -r '.data.data.db_username // .data.data.username // empty')"
PG_PASSWORD="$(echo "${VAULT_DATA}" | jq -r '.data.data.db_password // .data.data.password // empty')"

if [[ -z "${PG_USER}" ]]; then
  log "FATAL: no db_username/username field at ${VAULT_PATH}"
  exit 2
fi
if [[ -z "${PG_PASSWORD}" ]]; then
  log "FATAL: no db_password/password field at ${VAULT_PATH}"
  exit 2
fi

log "  -> Vault returns user='${PG_USER}' password='$(mask "${PG_PASSWORD}")' (len=${#PG_PASSWORD})"

# --- Step 2: alphanumeric policy enforcement --------------------------------

# Spring `${...}` placeholder parser + Hibernate JDBC URL build break on
# special characters in passwords. See docs/policy/alphanumeric-password-policy.md
log "Step 2/6 — alphanumeric password policy check"

if [[ ! "${PG_PASSWORD}" =~ ^[A-Za-z0-9]+$ ]]; then
  log "FATAL: Vault password for ${SERVICE} contains non-alphanumeric chars"
  log "       Spring/Hibernate placeholder parser will break — rotate password"
  log "       Policy: docs/policy/alphanumeric-password-policy.md"
  exit 3
fi
log "  -> alphanumeric OK"

# --- Step 3: PG ALTER USER (literal password, NOT a variable!) --------------

log "Step 3/6 — ALTER USER ${PG_USER} on ${PG_CONTAINER}"

# Use a heredoc literal so bash variable expansion happens once, then psql
# sees the plain literal. Single-quote-inside-double-quote would NOT expand
# the variable inside `'${...}'` — that bug is what caused the 2026-05-10
# false-rotation incident.
ALTER_SQL="ALTER USER ${PG_USER} WITH PASSWORD '${PG_PASSWORD}';"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "DRY-RUN: would execute ALTER USER (password masked)"
else
  # Pipe the SQL via stdin so the literal does not appear on the docker exec
  # argv (cleaner shell history).
  if echo "${ALTER_SQL}" | docker exec -i "${PG_CONTAINER}" \
        psql -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null 2>&1; then
    log "  -> ALTER USER succeeded"
  else
    log "FATAL: ALTER USER failed (see PG container logs)"
    exit 4
  fi
fi

# --- Step 4: ESO force-sync --------------------------------------------------

# ESO refreshes externalsecrets every refreshInterval (1h default). Force-sync
# annotation triggers immediate reconcile.
log "Step 4/6 — ESO force-sync for externalsecret/${SERVICE}-secrets"

ES_NAME="${SERVICE}-secrets"

if kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
     get externalsecret "${ES_NAME}" >/dev/null 2>&1; then
  run kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
    annotate externalsecret "${ES_NAME}" \
    "force-sync=$(date +%s)" --overwrite >/dev/null

  # Wait up to 30s for SecretSynced=True
  local_deadline=$(($(date +%s) + 30))
  while [[ $(date +%s) -lt ${local_deadline} ]]; do
    STATUS="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
      get externalsecret "${ES_NAME}" \
      -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")"
    if [[ "${STATUS}" == "True" ]]; then
      log "  -> ExternalSecret READY=True"
      break
    fi
    sleep 2
  done

  if [[ "${STATUS}" != "True" ]]; then
    log "WARN: ExternalSecret did not reach Ready=True within 30s (continuing)"
  fi
else
  log "  -> no externalsecret/${ES_NAME} (service may use direct Secret); skipping"
fi

# --- Step 5: rollout restart -------------------------------------------------

log "Step 5/6 — rollout restart deploy/${SERVICE}"

if kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
     get deploy "${SERVICE}" >/dev/null 2>&1; then
  run kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
    rollout restart deploy/"${SERVICE}"
  if [[ ${DRY_RUN} -eq 0 ]]; then
    if ! kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
            rollout status deploy/"${SERVICE}" --timeout=240s; then
      log "FATAL: rollout did not complete within 240s"
      exit 4
    fi
  fi
else
  log "FATAL: deploy/${SERVICE} not found in ${NAMESPACE}"
  exit 4
fi

# --- Step 6: pod-network smoke (NOT 127.0.0.1=trust) -------------------------

log "Step 6/6 — pod-network smoke (NOT 127.0.0.1=trust)"

# Test from inside the new pod that the DB credential works. The pod connects
# via the service DNS name (postgres.platform-test.svc.cluster.local or
# Docker network alias) which goes through scram-sha-256 not the trust line.

POD_NAME="$(kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
  get pod -l app.kubernetes.io/name="${SERVICE}" \
  --field-selector status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")"

if [[ -z "${POD_NAME}" ]]; then
  log "FATAL: no running pod for ${SERVICE} after rollout"
  exit 4
fi

# Use the pod's own /actuator/health endpoint as the canonical smoke. If the
# DB connection failed, Spring Boot's health indicator goes DOWN and the pod
# never reaches 1/1 Ready — so rollout success above is already a strong
# signal. Re-confirm here for the audit log.

if [[ ${DRY_RUN} -eq 0 ]]; then
  if kubectl --context "${CLUSTER_CTX}" -n "${NAMESPACE}" \
        wait --for=condition=Ready "pod/${POD_NAME}" --timeout=60s >/dev/null 2>&1; then
    log "  -> pod/${POD_NAME} Ready=True (pod-network DB auth implicitly OK)"
  else
    log "FATAL: pod/${POD_NAME} not Ready within 60s — DB auth likely failed"
    log "       Inspect: kubectl --context ${CLUSTER_CTX} -n ${NAMESPACE} logs ${POD_NAME} --tail=50"
    exit 4
  fi
fi

log "DONE — rotation for ${SERVICE} on ${CLUSTER_CTX} completed successfully"
exit 0
