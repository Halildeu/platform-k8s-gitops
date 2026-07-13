#!/usr/bin/env bash
# Faz 24 test-only Meeting owner tuple migration.
#
# Reconciles owner tuples from the tenant-scoped Meeting database to the
# stable OIDC subject stored in created_by_subject. A subject is eligible only
# when it exactly matches a current user id in the selected Keycloak realm.
# Raw meeting/user identifiers stay in mode-0600 temporary/rollback files and
# are never printed. Production and non-test targets are refused.
#
# Modes:
#   plan      read-only candidate inventory (default)
#   apply     write missing stable-sub owner tuples, then verify
#   verify    verify exact tuples and a synthetic negative can_record check
#   rollback  delete only tuples recorded as newly written by an apply run
#
# Required:
#   TENANT_ID=<canonical tenant UUID>
#
# Apply example (run from the claimed #2360 worktree):
#   BOARD_SESSION_ID=... TENANT_ID=... TARGET_MEETING_ID=... \
#   MODE=apply CONFIRM_TEST_MUTATION=YES \
#   ROLLBACK_FILE="$HOME/.local/state/platform/faz24-owner-backfill.tsv" \
#     scripts/faz24/backfill-meeting-owner-stable-sub.sh
set -euo pipefail

err()  { printf '[error] %s\n' "$*" >&2; }
info() { printf '[info] %s\n' "$*"; }
die()  { err "$*"; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require ssh
require jq
require awk
require sort
require shasum
require grep
require cp
require uniq

MODE="${MODE:-plan}"
ISSUE="${ISSUE:-2360}"
SSH_TARGET="${SSH_TARGET:-halil@staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
POD_DEPLOY="${POD_DEPLOY:-deploy/meeting-service}"
OPENFGA_BASE="${OPENFGA_BASE:-http://openfga:8080}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-platform-test}"
TENANT_ID="${TENANT_ID:-}"
TARGET_MEETING_ID="${TARGET_MEETING_ID:-}"
ROLLBACK_FILE="${ROLLBACK_FILE:-}"
ROLLBACK_SHA256="${ROLLBACK_SHA256:-}"
CONFIRM_TEST_MUTATION="${CONFIRM_TEST_MUTATION:-NO}"
ACK_UNMATCHED_SUBJECTS="${ACK_UNMATCHED_SUBJECTS:-NO}"

uuid_re='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
[[ "$TENANT_ID" =~ $uuid_re ]] || die "TENANT_ID must be a UUID"
if [ -n "$TARGET_MEETING_ID" ]; then
  [[ "$TARGET_MEETING_ID" =~ $uuid_re ]] || die "TARGET_MEETING_ID must be a UUID"
fi

case "$MODE" in
  plan|apply|verify|rollback) : ;;
  *) die "MODE must be plan, apply, verify, or rollback" ;;
esac

[ "$KUBE_CONTEXT" = "k3d-test" ] || die "test-only guard: KUBE_CONTEXT must be k3d-test"
[ "$KUBE_NS" = "platform-test" ] || die "test-only guard: KUBE_NS must be platform-test"
[ "$PG_CONTAINER" = "platform-pg-test" ] || die "test-only guard: PG_CONTAINER must be platform-pg-test"
[ "$KEYCLOAK_REALM" = "platform-test" ] || die "test-only guard: KEYCLOAK_REALM must be platform-test"
[ "$OPENFGA_BASE" = "http://openfga:8080" ] || die "test-only guard: OPENFGA_BASE must be http://openfga:8080"
[ "$ISSUE" = "2360" ] || die "mutation authority guard: ISSUE must be 2360"
[[ "$SSH_TARGET" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$ ]] || die "unsafe SSH_TARGET"
case "$POD_DEPLOY" in
  deploy/meeting-service) : ;;
  *) die "test-only guard: POD_DEPLOY must be deploy/meeting-service" ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$REPO_ROOT" ] || die "run from a platform-k8s-gitops worktree"

if [ "$MODE" = "apply" ] || [ "$MODE" = "rollback" ]; then
  [ "$CONFIRM_TEST_MUTATION" = "YES" ] || die "mutation requires CONFIRM_TEST_MUTATION=YES"
  [ -n "${BOARD_SESSION_ID:-}" ] || die "mutation requires BOARD_SESSION_ID"
  bash "$REPO_ROOT/scripts/board/require-claim.sh" "$ISSUE"
  [ -n "$ROLLBACK_FILE" ] || die "mutation requires an explicit ROLLBACK_FILE outside the repository"
  case "$ROLLBACK_FILE" in
    "$REPO_ROOT"/*) die "ROLLBACK_FILE must not be stored in the repository" ;;
  esac
fi

for value in "$PG_CONTAINER" "$KEYCLOAK_REALM" "$KUBE_CONTEXT" "$KUBE_NS"; do
  [[ "$value" =~ ^[A-Za-z0-9_.-]+$ ]] || die "unsafe configuration value"
done

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/faz24-owner-backfill.XXXXXX")"
chmod 700 "$tmp_dir"
trap 'rm -rf "$tmp_dir"' EXIT
meetings_file="$tmp_dir/meetings.tsv"
keycloak_file="$tmp_dir/keycloak-users.txt"
eligible_file="$tmp_dir/eligible.tsv"
unmatched_file="$tmp_dir/unmatched.tsv"
touch "$meetings_file" "$keycloak_file" "$eligible_file" "$unmatched_file"
chmod 600 "$meetings_file" "$keycloak_file" "$eligible_file" "$unmatched_file"

remote_psql() {
  local database="$1" sql="$2" quoted_sql
  printf -v quoted_sql '%q' "$sql"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_TARGET" \
    "docker exec '$PG_CONTAINER' psql -U postgres -d '$database' -Atqc $quoted_sql"
}

if [ "$MODE" != "rollback" ]; then
  info "preflight: test database availability"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_TARGET" \
    "docker inspect '$PG_CONTAINER' >/dev/null"
fi

SID=""
MID=""
if [ "$MODE" != "plan" ]; then
  info "preflight: test cluster and service availability"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_TARGET" \
    "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NS' get '$POD_DEPLOY' >/dev/null"
  SID="$(ssh -o BatchMode=yes "$SSH_TARGET" \
    "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NS' exec '$POD_DEPLOY' -- printenv ERP_OPENFGA_STORE_ID" 2>/dev/null | tr -d '\r')"
  MID="$(ssh -o BatchMode=yes "$SSH_TARGET" \
    "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NS' exec '$POD_DEPLOY' -- printenv ERP_OPENFGA_MODEL_ID" 2>/dev/null | tr -d '\r')"
  [ -n "$SID" ] && [ -n "$MID" ] || die "OpenFGA store/model id is absent from meeting-service runtime"
  [[ "$SID" =~ ^[A-Za-z0-9_-]+$ ]] || die "unsafe OpenFGA store id"
  [[ "$MID" =~ ^[A-Za-z0-9_-]+$ ]] || die "unsafe OpenFGA model id"
fi

pod_post() {
  local endpoint="$1"
  ssh -o BatchMode=yes "$SSH_TARGET" \
    "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NS' exec -i '$POD_DEPLOY' -- curl -sS -w '\n%{http_code}' -X POST '${OPENFGA_BASE}/stores/${SID}/${endpoint}' -H 'Content-Type: application/json' -d @-"
}

tuple_payload() {
  local operation="$1" subject="$2" meeting_id="$3"
  jq -nc --arg mid "$MID" --arg u "user:$subject" --arg o "meeting:$meeting_id" --arg op "$operation" '
    if $op == "write" then
      {authorization_model_id:$mid, writes:{tuple_keys:[{user:$u, relation:"owner", object:$o}]}}
    else
      {authorization_model_id:$mid, deletes:{tuple_keys:[{user:$u, relation:"owner", object:$o}]}}
    end'
}

read_tuple_exists() {
  local subject="$1" meeting_id="$2" payload out code body count
  payload="$(jq -nc --arg mid "$MID" --arg u "user:$subject" --arg o "meeting:$meeting_id" \
    '{authorization_model_id:$mid, tuple_key:{user:$u, relation:"owner", object:$o}}')"
  out="$(printf '%s' "$payload" | pod_post read)"
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  [ "$code" = "200" ] || return 2
  count="$(printf '%s' "$body" | jq -er '
    if ((.tuples // null) | type) == "array" then (.tuples | length)
    else error("invalid OpenFGA read response") end' 2>/dev/null)" || return 2
  [ "$count" -gt 0 ]
}

delete_tuple_verified() {
  local subject="$1" meeting_id="$2" context="$3" out code body status read_rc
  out="$(tuple_payload delete "$subject" "$meeting_id" | pod_post write)"
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  case "$code" in
    200|201) status="removed" ;;
    400|409)
      if printf '%s' "$body" | grep -Eqi 'not[ _-]?found|does not exist|cannot delete.*tuple'; then
        status="already_absent"
      else
        die "tuple delete failed at $context (HTTP $code; response redacted)"
      fi
      ;;
    *) die "tuple delete failed at $context (HTTP $code; response redacted)" ;;
  esac

  if read_tuple_exists "$subject" "$meeting_id"; then
    die "tuple delete verification failed at $context (tuple still present)"
  else
    read_rc=$?
    [ "$read_rc" -eq 1 ] || die "tuple delete verification failed at $context (read error)"
  fi
  printf '%s\n' "$status"
}

verify_negative() {
  local meeting_id="$1" payload out code body allowed
  payload="$(jq -nc --arg mid "$MID" --arg o "meeting:$meeting_id" \
    '{authorization_model_id:$mid, tuple_key:{user:"user:00000000-0000-0000-0000-000000000000", relation:"can_record", object:$o}}')"
  out="$(printf '%s' "$payload" | pod_post check)"
  code="${out##*$'\n'}"
  body="${out%$'\n'*}"
  [ "$code" = "200" ] || return 2
  allowed="$(printf '%s' "$body" | jq -er \
    'if (.allowed | type) == "boolean" then (.allowed | tostring) else error("allowed must be boolean") end' \
    2>/dev/null)" || return 2
  [ "$allowed" = "false" ]
}

emit_summary() {
  local written="${1:-0}" existed="${2:-0}" verified="${3:-0}" removed="${4:-0}"
  jq -n \
    --arg mode "$MODE" \
    --arg tenantHash "$(printf '%s' "$TENANT_ID" | shasum -a 256 | cut -c1-12)" \
    --arg targetScoped "$([ -n "$TARGET_MEETING_ID" ] && echo true || echo false)" \
    --arg candidateDigest "$candidate_digest" \
    --argjson meetingRows "$meeting_count" \
    --argjson eligible "$eligible_count" \
    --argjson unmatched "$unmatched_count" \
    --argjson written "$written" \
    --argjson existed "$existed" \
    --argjson verified "$verified" \
    --argjson removed "$removed" \
    '{mode:$mode, environment:"platform-test", tenantHash:$tenantHash,
      targetMeetingScoped:($targetScoped == "true"), candidateDigest:$candidateDigest,
      meetingRows:$meetingRows, eligibleExactRealmSubjects:$eligible,
      quarantinedUnmatchedSubjects:$unmatched, newlyWritten:$written,
      alreadyPresent:$existed, verifiedExactTuples:$verified, rolledBack:$removed}'
}

if [ "$MODE" = "rollback" ]; then
  [ -f "$ROLLBACK_FILE" ] || die "ROLLBACK_FILE not found"
  [ ! -L "$ROLLBACK_FILE" ] || die "ROLLBACK_FILE must not be a symlink"
  [[ "$ROLLBACK_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] || die "rollback requires ROLLBACK_SHA256 from apply evidence"
  chmod 600 "$ROLLBACK_FILE"
  manifest_snapshot="$tmp_dir/rollback-manifest.tsv"
  cp "$ROLLBACK_FILE" "$manifest_snapshot"
  chmod 600 "$manifest_snapshot"
  actual_rollback_digest="$(shasum -a 256 "$manifest_snapshot" | awk '{print $1}')"
  expected_rollback_digest="$(printf '%s' "$ROLLBACK_SHA256" | tr '[:upper:]' '[:lower:]')"
  [ "$expected_rollback_digest" = "$actual_rollback_digest" ] || die "rollback manifest SHA-256 mismatch"
  duplicate_count="$(LC_ALL=C sort "$manifest_snapshot" | uniq -d | awk 'END { print NR + 0 }')"
  [ "$duplicate_count" -eq 0 ] || die "rollback manifest contains duplicate entries"
  meeting_count=0
  eligible_count="$(awk -F '\t' 'NF { count++ } END { print count + 0 }' "$manifest_snapshot")"
  unmatched_count=0
  [ "$eligible_count" -gt 0 ] || die "rollback manifest is empty"
  candidate_digest="$actual_rollback_digest"
  removed=0
  already_absent=0
  index=0
  while IFS=$'\t' read -r meeting_id subject manifest_tenant manifest_sid manifest_mid extra <&3; do
    [ -n "$meeting_id" ] || continue
    index=$((index + 1))
    [ -z "${extra:-}" ] || die "rollback manifest contains unexpected columns at entry $index"
    [[ "$meeting_id" =~ $uuid_re ]] || die "rollback manifest contains an invalid meeting id at entry $index"
    [[ "$subject" =~ $uuid_re ]] || die "rollback manifest contains an invalid subject at entry $index"
    [[ "$manifest_tenant" =~ $uuid_re ]] || die "rollback manifest contains an invalid tenant at entry $index"
    [ "$manifest_tenant" = "$TENANT_ID" ] || die "rollback manifest tenant mismatch at entry $index"
    [ "$manifest_sid" = "$SID" ] || die "rollback manifest OpenFGA store mismatch at entry $index"
    [ "$manifest_mid" = "$MID" ] || die "rollback manifest OpenFGA model mismatch at entry $index"

    delete_status="$(delete_tuple_verified "$subject" "$meeting_id" "rollback entry $index")"
    case "$delete_status" in
      removed) removed=$((removed + 1)) ;;
      already_absent) already_absent=$((already_absent + 1)) ;;
      *) die "unexpected tuple delete status at rollback entry $index" ;;
    esac
  done 3<"$manifest_snapshot"
  info "rollback verification: removed=$removed alreadyAbsent=$already_absent"
  emit_summary 0 "$already_absent" 0 "$removed"
  exit 0
fi

meeting_filter="tenant_id = '${TENANT_ID}' AND created_by_subject IS NOT NULL AND btrim(created_by_subject) <> ''"
if [ -n "$TARGET_MEETING_ID" ]; then
  meeting_filter="$meeting_filter AND id = '${TARGET_MEETING_ID}'"
fi
meeting_sql="SELECT id::text || chr(9) || created_by_subject FROM meeting_service.meetings WHERE $meeting_filter ORDER BY id"
keycloak_sql="SELECT u.id FROM user_entity u JOIN realm r ON r.id = u.realm_id WHERE r.name = '${KEYCLOAK_REALM}' ORDER BY u.id"

remote_psql meeting "$meeting_sql" >"$meetings_file"
remote_psql keycloak "$keycloak_sql" >"$keycloak_file"
LC_ALL=C sort -u "$keycloak_file" -o "$keycloak_file"

awk -F '\t' -v eligible="$eligible_file" -v unmatched="$unmatched_file" '
  NR == FNR { current[$1] = 1; next }
  ($2 in current) { print $0 > eligible; next }
  { print $0 > unmatched }
' "$keycloak_file" "$meetings_file"

meeting_count="$(wc -l <"$meetings_file" | tr -d ' ')"
eligible_count="$(wc -l <"$eligible_file" | tr -d ' ')"
unmatched_count="$(wc -l <"$unmatched_file" | tr -d ' ')"
candidate_digest="$(shasum -a 256 "$eligible_file" | awk '{print $1}')"

[ "$meeting_count" -gt 0 ] || die "no tenant-scoped Meeting rows matched"
[ "$eligible_count" -gt 0 ] || die "no Meeting subject exactly matched a current Keycloak realm user id"

if [ "$MODE" = "apply" ] && [ "$unmatched_count" -gt 0 ] && [ "$ACK_UNMATCHED_SUBJECTS" != "YES" ]; then
  die "apply refused: unmatched subjects exist; inspect plan evidence and set ACK_UNMATCHED_SUBJECTS=YES to quarantine them explicitly"
fi

if [ "$MODE" = "plan" ]; then
  emit_summary
  exit 0
fi

if [ "$MODE" = "apply" ]; then
  mkdir -p "$(dirname "$ROLLBACK_FILE")"
  [ ! -e "$ROLLBACK_FILE" ] || die "ROLLBACK_FILE already exists; preserve it or choose a new path"
  (umask 077; set -o noclobber; : >"$ROLLBACK_FILE") 2>/dev/null || \
    die "ROLLBACK_FILE could not be created exclusively"
  chmod 600 "$ROLLBACK_FILE"
  written=0
  existed=0
  index=0
  while IFS=$'\t' read -r meeting_id subject extra <&3; do
    [ -n "$meeting_id" ] || continue
    index=$((index + 1))
    [ -z "${extra:-}" ] || die "candidate contains unexpected columns at index $index"
    [[ "$meeting_id" =~ $uuid_re ]] || die "candidate contains invalid meeting id at index $index"
    [[ "$subject" =~ $uuid_re ]] || die "candidate contains invalid stable subject at index $index"
    if read_tuple_exists "$subject" "$meeting_id"; then
      existed=$((existed + 1))
      continue
    else
      read_rc=$?
      [ "$read_rc" -eq 1 ] || die "pre-write tuple read failed at candidate $index"
    fi
    out="$(tuple_payload write "$subject" "$meeting_id" | pod_post write)"
    code="${out##*$'\n'}"
    body="${out%$'\n'*}"
    case "$code" in
      200|201)
        if ! printf '%s\t%s\t%s\t%s\t%s\n' "$meeting_id" "$subject" "$TENANT_ID" "$SID" "$MID" >>"$ROLLBACK_FILE"; then
          delete_tuple_verified "$subject" "$meeting_id" "manifest compensation candidate $index" >/dev/null
          die "rollback manifest append failed at candidate $index; compensating delete verified"
        fi
        written=$((written + 1))
        ;;
      400|409)
        if printf '%s' "$body" | grep -qi 'already exist' && read_tuple_exists "$subject" "$meeting_id"; then
          existed=$((existed + 1))
        else
          die "tuple write failed at candidate $index (HTTP $code; response redacted)"
        fi
        ;;
      *) die "tuple write failed at candidate $index (HTTP $code; response redacted)" ;;
    esac
  done 3<"$eligible_file"

  [ $((written + existed)) -eq "$eligible_count" ] || \
    die "apply invariant failed: written plus already-present does not match eligible count"

  rollback_digest="$(shasum -a 256 "$ROLLBACK_FILE" | awk '{print $1}')"
  info "rollback manifest: path=$ROLLBACK_FILE sha256=$rollback_digest entries=$written"
fi

verified=0
index=0
first_meeting=""
while IFS=$'\t' read -r meeting_id subject extra <&3; do
  [ -n "$meeting_id" ] || continue
  index=$((index + 1))
  [ -z "${extra:-}" ] || die "candidate contains unexpected columns at index $index"
  [[ "$meeting_id" =~ $uuid_re ]] || die "candidate contains invalid meeting id at index $index"
  [[ "$subject" =~ $uuid_re ]] || die "candidate contains invalid stable subject at index $index"
  [ -n "$first_meeting" ] || first_meeting="$meeting_id"
  if read_tuple_exists "$subject" "$meeting_id"; then
    verified=$((verified + 1))
  else
    die "exact owner tuple verification failed at candidate $index (identifiers redacted)"
  fi
done 3<"$eligible_file"

[ "$verified" -eq "$eligible_count" ] || die "verified tuple count does not match eligible count"
verify_negative "$first_meeting" || die "synthetic negative can_record check failed"

emit_summary "${written:-0}" "${existed:-0}" "$verified" 0
