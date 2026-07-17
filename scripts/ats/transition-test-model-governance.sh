#!/usr/bin/env bash
# Faz 25 #2526: test-only owner-delegated model-governance check/append.
#
# The PostgreSQL login is short-lived and has no admin attributes. Its random
# password is sent only through process stdin and never enters script-owned
# argv, environment, CI output, shell history, Vault, Kubernetes Secret, or a
# repository file. PostgreSQL server-side statement logging is an external
# operator setting and must not log DDL for this test database.
set -euo pipefail
umask 077

MODE=""
IMAGE_REF=""
CONFIRM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      [[ -z "$MODE" && $# -ge 2 ]] || { echo "usage: $0 --mode check|append --image-ref IMAGE@DIGEST --confirm LITERAL" >&2; exit 2; }
      MODE=$2
      shift 2
      ;;
    --image-ref)
      [[ -z "$IMAGE_REF" && $# -ge 2 ]] || { echo "usage: $0 --mode check|append --image-ref IMAGE@DIGEST --confirm LITERAL" >&2; exit 2; }
      IMAGE_REF=$2
      shift 2
      ;;
    --confirm)
      [[ -z "$CONFIRM" && $# -ge 2 ]] || { echo "usage: $0 --mode check|append --image-ref IMAGE@DIGEST --confirm LITERAL" >&2; exit 2; }
      CONFIRM=$2
      shift 2
      ;;
    *)
      echo "usage: $0 --mode check|append --image-ref IMAGE@DIGEST --confirm LITERAL" >&2
      exit 2
      ;;
  esac
done

case "$MODE" in
  check) EXPECTED_CONFIRM="CHECK_FAZ25_TEST_MODEL_GOVERNANCE" ;;
  append) EXPECTED_CONFIRM="APPEND_FAZ25_TEST_MODEL_GOVERNANCE" ;;
  *) echo "FATAL: mode must be check or append" >&2; exit 2 ;;
esac
[[ "$CONFIRM" == "$EXPECTED_CONFIRM" ]] || {
  echo "FATAL: exact confirmation literal required for mode=$MODE" >&2
  exit 2
}
[[ "$IMAGE_REF" =~ ^ghcr\.io/halildeu/ats-app-boot@sha256:[0-9a-f]{64}$ ]] || {
  echo "FATAL: immutable ATS image@sha256 ref required" >&2
  exit 2
}
for required in cut docker flock grep head kubectl openssl python3 sleep timeout; do
  command -v "$required" >/dev/null || { echo "FATAL: required command missing: $required" >&2; exit 1; }
done

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ACTIVATION_FILE="$REPO_ROOT/kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml"
CANONICAL_DIGEST=$(python3 - "$ACTIVATION_FILE" <<'PY'
import re
import sys
from pathlib import Path

lines = Path(sys.argv[1]).read_text().splitlines()
matches = []
for index, line in enumerate(lines):
    if re.fullmatch(r"\s*-\s+name:\s*ghcr\.io/halildeu/ats-app-boot\s*", line):
        for candidate in lines[index + 1:index + 5]:
            digest = re.fullmatch(r"\s+digest:\s*(sha256:[0-9a-f]{64})\s*", candidate)
            if digest:
                matches.append(digest.group(1))
                break
if len(matches) != 1:
    raise SystemExit("canonical ATS digest could not be resolved exactly once")
print(matches[0])
PY
)
[[ "$IMAGE_REF" == "ghcr.io/halildeu/ats-app-boot@${CANONICAL_DIGEST}" ]] || {
  echo "FATAL: operator image does not equal the canonical activation digest" >&2
  exit 1
}

ENDPOINT_REF="faz24-stt-prod"
APPROVAL_REF="mapr_549a8e22a2c6f3c445be3e2405262bba5b80a78d72047fd95fa03deaa66a732d"

assert_live_gitops_binding() {
  local live_image live_config_binding
  live_image=$(kubectl --context k3d-test -n platform-test get deployment ats-interview-evidence \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="app-boot")].image}')
  [[ "$live_image" == "$IMAGE_REF" ]] || {
    echo "FATAL: operator image does not equal the live GitOps deployment image" >&2
    return 1
  }
  live_config_binding=$(kubectl --context k3d-test -n platform-test \
    get configmap ats-interview-evidence-config \
    -o jsonpath='{.data.ATS_AI_ENDPOINT_REF}{"|"}{.data.ATS_AI_APPROVAL_TRANSCRIBE_REF}')
  [[ "$live_config_binding" == "${ENDPOINT_REF}|${APPROVAL_REF}" ]] || {
    echo "FATAL: live GitOps endpoint/approval binding does not equal the fixed transition" >&2
    return 1
  }
}

assert_live_gitops_binding

LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/ats-model-governance-test-${UID}.lock"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "FATAL: another model-governance transition is active" >&2; exit 1; }

PG_CONTAINER="platform-pg-test"
DB_URL="jdbc:postgresql://127.0.0.1:5432/ats"
TRANSITION_ID="mgt_25260000-0000-4000-8000-000000000001"
ACTOR_REF="cross-ai/faz25/2526"
OPERATOR_ROLE="ats_governance_op_$(openssl rand -hex 8)"
OPERATOR_PASSWORD="$(openssl rand -hex 32)"
OPERATOR_CONTAINER="${OPERATOR_ROLE//_/-}"
ROLE_CREATED=false
TMP_DIR=$(mktemp -d)
ATS_APP_STATE_BEFORE=""
WRITER_STATE_BEFORE=""

read_writer_state() {
  docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d postgres -c \
    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ats_governance_writer'"
}

read_ats_app_state() {
  docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d postgres -c \
    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ats_app'"
}

drop_operator_role() {
  local attempt
  for attempt in 1 2 3; do
    docker rm -f "$OPERATOR_CONTAINER" >/dev/null 2>&1 || true
    if docker exec -i "$PG_CONTAINER" psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres >/dev/null <<SQL
BEGIN;
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = '${OPERATOR_ROLE}' AND pid <> pg_backend_pid();
REVOKE ats_governance_writer FROM "${OPERATOR_ROLE}";
DROP ROLE "${OPERATOR_ROLE}";
COMMIT;
SQL
    then
      ROLE_CREATED=false
      return 0
    fi
    sleep "$attempt"
  done
  return 1
}

cleanup() {
  local result=$?
  trap - EXIT
  trap '' HUP INT TERM
  if [[ "$ROLE_CREATED" == true ]]; then
    if ! drop_operator_role; then
      echo "FATAL: ephemeral governance operator role cleanup failed after retries; orphan=${OPERATOR_ROLE}" >&2
      [[ $result -ne 0 ]] || result=1
    fi
  fi
  if [[ -n "$ATS_APP_STATE_BEFORE" && "$(read_ats_app_state)" != "$ATS_APP_STATE_BEFORE" ]]; then
    echo "FATAL: ats_app role drift detected across governance operation" >&2
    [[ $result -ne 0 ]] || result=1
  fi
  if [[ -n "$WRITER_STATE_BEFORE" && "$(read_writer_state)" != "$WRITER_STATE_BEFORE" ]]; then
    echo "FATAL: ats_governance_writer role drift detected across governance operation" >&2
    [[ $result -ne 0 ]] || result=1
  fi
  OPERATOR_PASSWORD=""
  unset OPERATOR_PASSWORD
  rm -rf "$TMP_DIR"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

[[ "$(docker inspect --format '{{.State.Running}}' "$PG_CONTAINER")" == "true" ]] || {
  echo "FATAL: test PostgreSQL container is not running" >&2
  exit 1
}
WRITER_STATE_BEFORE=$(read_writer_state)
[[ "$WRITER_STATE_BEFORE" == "f|f|f|f|f|f" ]] || {
  echo "FATAL: ats_governance_writer is missing or has unsafe attributes" >&2
  exit 1
}
ATS_APP_STATE_BEFORE=$(read_ats_app_state)
[[ "$ATS_APP_STATE_BEFORE" == "t|f|f|f|f|f" ]] || {
  echo "FATAL: ats_app is missing or has unsafe attributes" >&2
  exit 1
}
ORPHAN_COUNT=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -d postgres -c \
  "SELECT count(*) FROM pg_roles WHERE rolname ~ '^ats_governance_op_[0-9a-f]{16}$'")
[[ "$ORPHAN_COUNT" == "0" ]] || {
  echo "FATAL: stale ephemeral governance operator role requires reconciliation; count=${ORPHAN_COUNT}" >&2
  exit 1
}
SERVER_STATEMENT_LOGGING=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d postgres -c \
  "SELECT current_setting('log_statement'),current_setting('log_min_duration_statement'),COALESCE(current_setting('pgaudit.log',true),'')")
[[ "$SERVER_STATEMENT_LOGGING" == "none|-1|" || "$SERVER_STATEMENT_LOGGING" == "none|-1|none" ]] || {
  echo "FATAL: PostgreSQL statement logging could retain the ephemeral operator DDL" >&2
  exit 1
}
MIGRATION_STATE=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d ats -c \
  "SELECT version,success FROM flyway_schema_history WHERE version='6'")
[[ "$MIGRATION_STATE" == "6|t" ]] || {
  echo "FATAL: Flyway V6 writer schema grant is not successful" >&2
  exit 1
}
LEDGER_POSITION_BEFORE=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d ats -c \
  "SELECT count(*),COALESCE(max(sequence),-1) FROM model_governance_ledger")
[[ "$LEDGER_POSITION_BEFORE" == "0|-1" || "$LEDGER_POSITION_BEFORE" == "1|0" ]] || {
  echo "FATAL: unexpected model-governance ledger position for the fixed initial transition" >&2
  exit 1
}
if [[ "$LEDGER_POSITION_BEFORE" == "1|0" ]]; then
  FIXED_ROW_COUNT=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -d ats -c \
    "SELECT count(*) FROM model_governance_ledger WHERE sequence=0 AND transition_id='${TRANSITION_ID}' AND approval_ref='${APPROVAL_REF}' AND capability='TRANSCRIBE' AND from_status='UNINITIALIZED' AND to_status='APPROVED' AND actor_ref='${ACTOR_REF}' AND reason_code='INITIAL_APPROVAL' AND previous_hash=repeat('0',64) AND entry_hash ~ '^[0-9a-f]{64}$'")
  [[ "$FIXED_ROW_COUNT" == "1" ]] || {
    echo "FATAL: existing governance row is not the fixed initial transition" >&2
    exit 1
  }
fi

docker pull "$IMAGE_REF" >/dev/null
docker image inspect "$IMAGE_REF" >/dev/null

# Password is hexadecimal and the role name is generated from a fixed prefix +
# hexadecimal suffix. The SQL travels on stdin; neither value enters argv/env.
# Re-assert the GitOps triple binding immediately before the first mutation.
assert_live_gitops_binding
docker exec -i "$PG_CONTAINER" psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres >/dev/null <<SQL
BEGIN;
SET LOCAL log_min_error_statement = 'PANIC';
CREATE ROLE "${OPERATOR_ROLE}" LOGIN PASSWORD '${OPERATOR_PASSWORD}'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT ats_governance_writer TO "${OPERATOR_ROLE}";
COMMIT;
SQL
ROLE_CREATED=true

SESSION_STATE=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d postgres -c \
  "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,pg_has_role('${OPERATOR_ROLE}','ats_governance_writer','member') FROM pg_roles WHERE rolname='${OPERATOR_ROLE}'")
[[ "$SESSION_STATE" == "t|f|f|f|f|f|t" ]] || {
  echo "FATAL: ephemeral operator role boundary assertion failed" >&2
  exit 1
}

run_cli() {
  local cli_mode=$1
  local cli_confirm=$2
  local output_file=$3
  local error_file=$4
  local safe_code
  local -a cli_args=(
    model-governance-transition
    "--mode=${cli_mode}"
    "--approval-ref=${APPROVAL_REF}"
    "--capability=TRANSCRIBE"
    "--expected-from=UNINITIALIZED"
    "--to-status=APPROVED"
    "--actor-ref=${ACTOR_REF}"
    "--reason=INITIAL_APPROVAL"
    "--transition-id=${TRANSITION_ID}"
    "--confirm=${cli_confirm}"
  )

  [[ "$(read_writer_state)" == "$WRITER_STATE_BEFORE" ]] || {
    echo "FATAL: writer role drift detected before CLI invocation" >&2
    return 1
  }
  [[ "$(read_ats_app_state)" == "$ATS_APP_STATE_BEFORE" ]] || {
    echo "FATAL: ats_app role drift detected before CLI invocation" >&2
    return 1
  }
  assert_live_gitops_binding || return 1

  # printf is a bash builtin. The credential envelope flows directly to the
  # pinned container stdin; the password never becomes a child-process arg.
  if ! printf '{"jdbcUrl":"%s","username":"%s","password":"%s","sslMode":"disable"}' \
      "$DB_URL" "$OPERATOR_ROLE" "$OPERATOR_PASSWORD" \
    | timeout --signal=TERM --kill-after=10s 120s docker run --rm -i --pull=never \
        --name "$OPERATOR_CONTAINER" \
        --network "container:${PG_CONTAINER}" \
        --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
        --cap-drop=ALL --security-opt no-new-privileges:true \
        --memory=768m --cpus=1 --pids-limit=256 \
        "$IMAGE_REF" "${cli_args[@]}" >"$output_file" 2>"$error_file"; then
    safe_code=$(grep -Eo 'code=[A-Z0-9_]{1,80}' "$error_file" | head -n 1 || true)
    echo "FATAL: model-governance CLI rejected mode=$cli_mode ${safe_code:-code=UNKNOWN}" >&2
    return 1
  fi
}

run_cli check CHECK_MODEL_GOVERNANCE_TRANSITION "$TMP_DIR/check-before.out" "$TMP_DIR/check-before.err"
if ! grep -Eq \
  "^MODEL_GOVERNANCE_CHECK:v1 outcome=OK approvalRef=${APPROVAL_REF} capability=TRANSCRIBE current=(UNINITIALIZED idempotent=false|APPROVED idempotent=true)$" \
  "$TMP_DIR/check-before.out"; then
  echo "FATAL: pre-append check output did not match the closed contract" >&2
  exit 1
fi

if [[ "$MODE" == check ]]; then
  LEDGER_POSITION_AFTER=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d ats -c \
    "SELECT count(*),COALESCE(max(sequence),-1) FROM model_governance_ledger")
  [[ "$LEDGER_POSITION_AFTER" == "$LEDGER_POSITION_BEFORE" ]] || {
    echo "FATAL: check mode changed the append-only ledger position" >&2
    exit 1
  }
  CURRENT_STATE=$(grep -Eo 'current=(UNINITIALIZED|APPROVED) idempotent=(false|true)' "$TMP_DIR/check-before.out")
  echo "PASS model-governance test check ${CURRENT_STATE} (no WORM mutation)"
  exit 0
fi

run_cli append APPEND_MODEL_GOVERNANCE_TRANSITION "$TMP_DIR/append.out" "$TMP_DIR/append.err"
if ! grep -Eq \
  "^MODEL_GOVERNANCE_APPEND:v1 outcome=OK transitionId=${TRANSITION_ID} approvalRef=${APPROVAL_REF} capability=TRANSCRIBE sequence=[0-9]+ entryHash=[0-9a-f]{64} idempotent=(false|true)$" \
  "$TMP_DIR/append.out"; then
  echo "FATAL: append output did not match the closed contract" >&2
  exit 1
fi

run_cli check CHECK_MODEL_GOVERNANCE_TRANSITION "$TMP_DIR/check-after.out" "$TMP_DIR/check-after.err"
grep -Eq \
  "^MODEL_GOVERNANCE_CHECK:v1 outcome=OK approvalRef=${APPROVAL_REF} capability=TRANSCRIBE current=APPROVED idempotent=true$" \
  "$TMP_DIR/check-after.out" || {
    echo "FATAL: post-append WORM projection verification failed" >&2
    exit 1
  }

IDEMPOTENCY=$(grep -Eo 'idempotent=(false|true)$' "$TMP_DIR/append.out")
APPEND_SEQUENCE=$(grep -Eo 'sequence=[0-9]+' "$TMP_DIR/append.out" | cut -d= -f2)
APPEND_HASH=$(grep -Eo 'entryHash=[0-9a-f]{64}' "$TMP_DIR/append.out" | cut -d= -f2)
[[ "$APPEND_SEQUENCE" == "0" && "$APPEND_HASH" =~ ^[0-9a-f]{64}$ ]] || {
  echo "FATAL: initial governance transition sequence/hash evidence mismatch" >&2
  exit 1
}
GENESIS_HASH=$(printf '0%.0s' {1..64})
LEDGER_STATE=$(docker exec "$PG_CONTAINER" psql -X -U postgres -At -F '|' -d ats -c \
  "SELECT sequence,from_status,to_status,actor_ref,reason_code,entry_hash,previous_hash FROM model_governance_ledger WHERE transition_id='${TRANSITION_ID}' AND approval_ref='${APPROVAL_REF}' AND capability='TRANSCRIBE'")
[[ "$LEDGER_STATE" == "0|UNINITIALIZED|APPROVED|${ACTOR_REF}|INITIAL_APPROVAL|${APPEND_HASH}|${GENESIS_HASH}" ]] || {
  echo "FATAL: full content-addressed model-governance ledger identity mismatch" >&2
  exit 1
}
echo "PASS model-governance test append APPROVED ${IDEMPOTENCY}; fixed transition identity verified"
