#!/usr/bin/env bash
set -euo pipefail

# Faz 22.6.3 Remote Response Terminal recording export helper.
#
# This script is read-only. It exports the durable WORM recording metadata for
# one remote-response session into a verifier-friendly JSONL bundle. It never
# dispatches operations, opens sessions, mutates Kubernetes/GitOps state, or
# writes to the endpoint-admin database. The WORM table stores content hashes,
# not raw output payloads; this helper preserves that privacy boundary.

SESSION_ID="${SESSION_ID:-${CHAIN_ID:-}}"
DB_SCHEMA="${DB_SCHEMA:-endpoint_admin_service}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/remote-response-terminal-recording-$(date -u +%Y%m%dT%H%M%SZ)}"

SOURCE_RECORDING_ROWS_FILE="${SOURCE_RECORDING_ROWS_FILE:-}"

DATABASE_URL="${DATABASE_URL:-${PGDATABASE_URL:-}}"
STAGING_SSH_TARGET="${STAGING_SSH_TARGET:-}"
SSH_CONNECT_TIMEOUT_SECONDS="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PG_DATABASE="${PG_DATABASE:-endpoint_admin}"
PG_USER="${PG_USER:-postgres}"

RECORDING_JSONL_FILE="${RECORDING_JSONL_FILE:-${EVIDENCE_DIR}/session-recording.jsonl}"
RECORDING_SUMMARY_FILE="${RECORDING_SUMMARY_FILE:-${EVIDENCE_DIR}/recording-summary.json}"
RUN_VERIFIER="${RUN_VERIFIER:-0}"
REQUIRE_ACCEPTED="${REQUIRE_ACCEPTED:-0}"
REQUIRE_FULL_MATRIX="${REQUIRE_FULL_MATRIX:-0}"

die() {
  printf 'ERR %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

validate_inputs() {
  [[ "$DB_SCHEMA" =~ ^[a-z_][a-z0-9_]*$ ]] \
    || die "DB_SCHEMA must be a safe PostgreSQL identifier: $DB_SCHEMA"

  if [[ -n "$SESSION_ID" && ! "$SESSION_ID" =~ ^[A-Za-z0-9_.:-]{1,128}$ ]]; then
    die "SESSION_ID/CHAIN_ID must be 1-128 chars from A-Z a-z 0-9 _ . : -"
  fi

  if [[ -z "$SOURCE_RECORDING_ROWS_FILE" && -z "$SESSION_ID" ]]; then
    die "SESSION_ID is required unless SOURCE_RECORDING_ROWS_FILE is supplied"
  fi
}

recording_sql() {
  cat <<SQL
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
FROM "${DB_SCHEMA}"."session_recording_entry"
WHERE chain_id = :'session_id'
ORDER BY seq;
SQL
}

copy_source_rows() {
  local source="$1"
  [[ -f "$source" ]] || die "SOURCE_RECORDING_ROWS_FILE not found: $source"
  cp "$source" "$RECORDING_JSONL_FILE"
}

run_local_psql() {
  need_cmd psql
  [[ -n "$DATABASE_URL" ]] || die "DATABASE_URL is required for local psql export"
  recording_sql > "${EVIDENCE_DIR}/recording-query.sql"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v "session_id=$SESSION_ID" -At \
    -f "${EVIDENCE_DIR}/recording-query.sql" \
    > "$RECORDING_JSONL_FILE"
}

run_staging_ssh_psql() {
  need_cmd ssh
  recording_sql > "${EVIDENCE_DIR}/recording-query.sql"

  local sql remote_cmd
  sql="$(cat "${EVIDENCE_DIR}/recording-query.sql")"
  remote_cmd=$(printf "docker exec %q psql -U %q -d %q -v ON_ERROR_STOP=1 -v %q -At -c %q" \
    "$PG_CONTAINER" "$PG_USER" "$PG_DATABASE" "session_id=$SESSION_ID" "$sql")

  ssh -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT_SECONDS" \
    "$STAGING_SSH_TARGET" "$remote_cmd" > "$RECORDING_JSONL_FILE"
}

normalize_jsonl() {
  local tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/rtt-recording-jsonl.XXXXXX")"
  jq -R -c '
    select(length > 0)
    | (try fromjson catch empty)
  ' "$RECORDING_JSONL_FILE" > "$tmp"
  mv "$tmp" "$RECORDING_JSONL_FILE"
}

write_summary() {
  jq -s \
    --arg generatedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg sessionId "$SESSION_ID" \
    --arg dbSchema "$DB_SCHEMA" \
    --arg sourceFile "$SOURCE_RECORDING_ROWS_FILE" \
    --arg recordingJsonl "$(basename "$RECORDING_JSONL_FILE")" \
    '{
      generatedAt: $generatedAt,
      sessionId: $sessionId,
      dbSchema: $dbSchema,
      sourceFile: $sourceFile,
      recordingJsonl: $recordingJsonl,
      rowCount: length,
      kinds: (
        [.[].kind // .source // .event // "UNKNOWN"]
        | group_by(.)
        | map({kind: .[0], count: length})
      ),
      hasPolicyEvent: any(.[]; ((.kind // .source // .event // "") | tostring) == "POLICY_EVENT"),
      hasAgentOutput: any(.[]; ((.kind // .source // .event // "") | tostring) == "AGENT_OUTPUT"),
      hasData: any(.[]; ([.. | scalars | tostring] | join(" ") | test("\\bDATA\\b"; "i"))),
      hasTerminalMarker: any(.[]; ([.. | scalars | tostring] | join(" ") | test("END[_-]?STREAM|EndStream|endStream|\\bSESSION_END\\b"; "i"))),
      contentBoundary: "session_recording_entry exports metadata content_hash values, not raw endpoint output payloads",
      acceptanceHint: (
        if length == 0 then "recording-empty"
        elif (any(.[]; ((.kind // .source // .event // "") | tostring) == "AGENT_OUTPUT") | not)
          and (any(.[]; ([.. | scalars | tostring] | join(" ") | test("\\bDATA\\b"; "i"))) | not)
          then "missing-agent-output-or-data"
        elif (any(.[]; ([.. | scalars | tostring] | join(" ") | test("END[_-]?STREAM|EndStream|endStream|\\bSESSION_END\\b"; "i"))) | not)
          then "missing-terminal-marker"
        else "verifier-ready-recording"
        end
      ),
	      doesNotProve: [
	        "raw output payload content",
	        "operator UI fan-out",
	        "endpoint is running the expected EndpointAgent version",
	        "allowed PERMIT response",
        "negative deny matrix",
        "full platform-agent#208 Done state"
      ]
    }' "$RECORDING_JSONL_FILE" > "$RECORDING_SUMMARY_FILE"
}

sha256_manifest() {
  (
    cd "$EVIDENCE_DIR"
    local hasher=() sums_file
    if command -v shasum >/dev/null 2>&1; then
      hasher=(shasum -a 256)
    elif command -v sha256sum >/dev/null 2>&1; then
      hasher=(sha256sum)
    else
      die "missing command: shasum or sha256sum"
    fi
    sums_file="$(mktemp "${TMPDIR:-/tmp}/rtt-recording-sha256.XXXXXX")"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
      | sort -z \
      | xargs -0 "${hasher[@]}" \
      > "$sums_file"
    mv "$sums_file" SHA256SUMS
  )
}

main() {
  need_cmd jq
  need_cmd cp
  need_cmd mktemp
  mkdir -p "$EVIDENCE_DIR"
  validate_inputs

  if [[ -n "$SOURCE_RECORDING_ROWS_FILE" ]]; then
    copy_source_rows "$SOURCE_RECORDING_ROWS_FILE"
  elif [[ -n "$DATABASE_URL" ]]; then
    run_local_psql
  elif [[ -n "$STAGING_SSH_TARGET" ]]; then
    run_staging_ssh_psql
  else
    die "set SOURCE_RECORDING_ROWS_FILE, DATABASE_URL, or STAGING_SSH_TARGET"
  fi

  normalize_jsonl
  write_summary
  sha256_manifest

  printf 'INFO evidence_dir=%s\n' "$EVIDENCE_DIR"
  jq -r '"RECORDING_EXPORT rows=" + (.rowCount|tostring) + " hint=" + .acceptanceHint' \
    "$RECORDING_SUMMARY_FILE"

  if [[ "$RUN_VERIFIER" == "1" ]]; then
    REQUIRE_ACCEPTED="$REQUIRE_ACCEPTED" REQUIRE_FULL_MATRIX="$REQUIRE_FULL_MATRIX" \
      scripts/faz22-remote-ops/remote-response-terminal-evidence-verify.sh "$EVIDENCE_DIR"
  fi
}

main "$@"
