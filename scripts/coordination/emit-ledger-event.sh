#!/usr/bin/env bash
# Emit one Coordination Ledger event through materialized comment + remote CAS.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MATERIALIZER="$REPO_ROOT/scripts/coordination/materialize-ledger-comment.py"
BRANCH_WRITER="$REPO_ROOT/scripts/coordination/append-ledger-branch.sh"

REMOTE="origin"
LEDGER_BRANCH="coordination-ledger"
LEDGER_PATH="coordination-ledger/events.jsonl"
COMMIT_TITLE="coordination ledger append"
COMMIT_MESSAGE=""
VERIFICATION_MODE="normal"
REPO=""
ISSUE=""
EVENT_UUID=""
EVENT_TYPE=""
WRITER_ROLE=""
COMMITTED_AT=""
EXPECT_PREVIOUS_HASH=""
PAYLOAD_JSON=""
PAYLOAD_FILE=""
METADATA_JSON=""
METADATA_FILE=""
COMMENT_JSON=""
POST_COMMENT="false"

die() {
  printf 'emit-ledger-event: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat >&2 <<'USAGE'
Usage:
  scripts/coordination/emit-ledger-event.sh [options]

Required:
  --repo <owner/repo>
  --issue <number>
  --expect-previous-hash <GENESIS|sha256:...>
  --event-type <type>
  --writer-role <role>
  (--payload-json <json> | --payload-file <path>)
  (--post-comment | --comment-json <path>)

Options:
  --remote <name-or-url>       Git remote name or URL (default: origin)
  --branch <branch>            Ledger branch name (default: coordination-ledger)
  --ledger-path <path>         JSONL path inside ledger branch (default: coordination-ledger/events.jsonl)
  --commit-title <title>       Commit title for the ledger append
  --commit-message <message>   Optional commit body
  --event-uuid <uuid>          Event UUID; generated when omitted
  --committed-at <UTC-Z>       Event timestamp; generated when omitted
  --metadata-json <json>       Optional metadata JSON object
  --metadata-file <path>       Optional metadata JSON object file
  --verification-mode <mode>   normal|degraded|recovery (default: normal)
  --materializer <path>        Override materialized comment helper
  --branch-writer <path>       Override remote branch CAS writer

Safety:
  The helper creates or verifies the materialized comment, then appends the
  event with remote branch CAS. It does not mutate issue bodies, Project fields,
  or PR bodies. If CAS fails after --post-comment, the comment is only an orphan
  candidate and must not be treated as authority without a ledger event.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --issue)
      ISSUE="${2:-}"
      shift 2
      ;;
    --remote)
      REMOTE="${2:-}"
      shift 2
      ;;
    --branch)
      LEDGER_BRANCH="${2:-}"
      shift 2
      ;;
    --ledger-path)
      LEDGER_PATH="${2:-}"
      shift 2
      ;;
    --commit-title)
      COMMIT_TITLE="${2:-}"
      shift 2
      ;;
    --commit-message)
      COMMIT_MESSAGE="${2:-}"
      shift 2
      ;;
    --event-uuid)
      EVENT_UUID="${2:-}"
      shift 2
      ;;
    --committed-at)
      COMMITTED_AT="${2:-}"
      shift 2
      ;;
    --expect-previous-hash)
      EXPECT_PREVIOUS_HASH="${2:-}"
      shift 2
      ;;
    --event-type)
      EVENT_TYPE="${2:-}"
      shift 2
      ;;
    --writer-role)
      WRITER_ROLE="${2:-}"
      shift 2
      ;;
    --payload-json)
      [ -z "$PAYLOAD_FILE" ] || die "pass either --payload-json or --payload-file, not both"
      PAYLOAD_JSON="${2:-}"
      shift 2
      ;;
    --payload-file)
      [ -z "$PAYLOAD_JSON" ] || die "pass either --payload-json or --payload-file, not both"
      PAYLOAD_FILE="${2:-}"
      shift 2
      ;;
    --metadata-json)
      [ -z "$METADATA_FILE" ] || die "pass either --metadata-json or --metadata-file, not both"
      METADATA_JSON="${2:-}"
      shift 2
      ;;
    --metadata-file)
      [ -z "$METADATA_JSON" ] || die "pass either --metadata-json or --metadata-file, not both"
      METADATA_FILE="${2:-}"
      shift 2
      ;;
    --comment-json)
      [ "$POST_COMMENT" = "false" ] || die "pass exactly one of --post-comment or --comment-json"
      COMMENT_JSON="${2:-}"
      shift 2
      ;;
    --post-comment)
      [ -z "$COMMENT_JSON" ] || die "pass exactly one of --post-comment or --comment-json"
      POST_COMMENT="true"
      shift
      ;;
    --verification-mode)
      VERIFICATION_MODE="${2:-}"
      shift 2
      ;;
    --materializer)
      MATERIALIZER="${2:-}"
      shift 2
      ;;
    --branch-writer)
      BRANCH_WRITER="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$REPO" ] || die "--repo is required"
[ -n "$ISSUE" ] || die "--issue is required"
[ -n "$EXPECT_PREVIOUS_HASH" ] || die "--expect-previous-hash is required"
[ -n "$EVENT_TYPE" ] || die "--event-type is required"
[ -n "$WRITER_ROLE" ] || die "--writer-role is required"
[ -n "$PAYLOAD_JSON" ] || [ -n "$PAYLOAD_FILE" ] || die "--payload-json or --payload-file is required"
if [ "$POST_COMMENT" = "true" ] && [ -n "$COMMENT_JSON" ]; then
  die "pass exactly one of --post-comment or --comment-json"
fi
if [ "$POST_COMMENT" = "false" ] && [ -z "$COMMENT_JSON" ]; then
  die "pass exactly one of --post-comment or --comment-json"
fi

case "$VERIFICATION_MODE" in
  normal|degraded|recovery)
    ;;
  *)
    die "--verification-mode must be normal, degraded, or recovery"
    ;;
esac

if [ -z "$EVENT_UUID" ]; then
  EVENT_UUID="$(python3 - <<'PY'
import uuid

print(uuid.uuid4())
PY
)"
fi

if [ -z "$COMMITTED_AT" ]; then
  COMMITTED_AT="$(python3 - <<'PY'
from datetime import datetime, timezone

print(datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
PY
)"
fi

payload_hash="$(python3 - "$PAYLOAD_JSON" "$PAYLOAD_FILE" <<'PY'
from pathlib import Path
import hashlib
import json
import sys

raw, path = sys.argv[1], sys.argv[2]
if path:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
else:
    data = json.loads(raw)
if not isinstance(data, dict):
    raise SystemExit("payload must be a JSON object")
body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
print("sha256:" + hashlib.sha256(body).hexdigest())
PY
)" || die "failed to compute payload hash"

work="$(mktemp -d -t coordination-ledger-emit.XXXXXX)"
cleanup() {
  rm -rf "$work"
}
trap cleanup EXIT

binding_file="$work/comment-binding.json"
append_err="$work/append.err"

materializer_args=(
  --repo "$REPO"
  --issue "$ISSUE"
  --event-uuid "$EVENT_UUID"
  --event-type "$EVENT_TYPE"
  --writer-role "$WRITER_ROLE"
  --payload-hash "$payload_hash"
  --verification-mode "$VERIFICATION_MODE"
  --committed-at "$COMMITTED_AT"
)

if [ "$POST_COMMENT" = "true" ]; then
  comment_mode="post"
  binding_json="$(python3 "$MATERIALIZER" post "${materializer_args[@]}")"
else
  comment_mode="fixture"
  binding_json="$(python3 "$MATERIALIZER" verify "${materializer_args[@]}" --comment-json "$COMMENT_JSON")"
fi
printf '%s\n' "$binding_json" >"$binding_file"

append_args=(
  --expect-previous-hash "$EXPECT_PREVIOUS_HASH"
  --event-uuid "$EVENT_UUID"
  --event-type "$EVENT_TYPE"
  --writer-role "$WRITER_ROLE"
  --committed-at "$COMMITTED_AT"
  --comment-binding-file "$binding_file"
)

if [ -n "$PAYLOAD_JSON" ]; then
  append_args+=(--payload-json "$PAYLOAD_JSON")
else
  append_args+=(--payload-file "$PAYLOAD_FILE")
fi

if [ -n "$METADATA_JSON" ]; then
  append_args+=(--metadata-json "$METADATA_JSON")
elif [ -n "$METADATA_FILE" ]; then
  append_args+=(--metadata-file "$METADATA_FILE")
fi

branch_cmd=(
  bash "$BRANCH_WRITER"
  --remote "$REMOTE"
  --branch "$LEDGER_BRANCH"
  --ledger-path "$LEDGER_PATH"
  --commit-title "$COMMIT_TITLE"
)
if [ -n "$COMMIT_MESSAGE" ]; then
  branch_cmd+=(--commit-message "$COMMIT_MESSAGE")
fi
branch_cmd+=(-- "${append_args[@]}")

set +e
append_json="$("${branch_cmd[@]}" 2>"$append_err")"
append_rc=$?
set -e

if [ "$append_rc" -ne 0 ]; then
  python3 - "$append_rc" "$binding_file" "$append_err" "$comment_mode" <<'PY' >&2
from pathlib import Path
import json
import sys

rc = int(sys.argv[1])
binding = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
error = Path(sys.argv[3]).read_text(encoding="utf-8").strip()
comment_mode = sys.argv[4]
print(
    json.dumps(
        {
            "status": "ledger_append_failed_no_post_cas_mirrors",
            "exit_code": rc,
            "error": error,
            "comment_mode": comment_mode,
            "candidate_comment_binding": binding,
            "issue_project_pr_mirrors_mutated": False,
            "candidate_comment_authoritative": False,
        },
        sort_keys=True,
    )
)
PY
  exit "$append_rc"
fi

python3 - "$binding_file" "$append_json" "$REPO" "$ISSUE" "$EVENT_UUID" "$EVENT_TYPE" "$WRITER_ROLE" "$COMMITTED_AT" "$comment_mode" <<'PY'
from pathlib import Path
import json
import sys

binding = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
append = json.loads(sys.argv[2])
print(
    json.dumps(
        {
            "status": "ledger_event_emitted_after_remote_cas",
            "repository": sys.argv[3],
            "issue": int(sys.argv[4]),
            "event_uuid": sys.argv[5],
            "event_type": sys.argv[6],
            "writer_role": sys.argv[7],
            "committed_at": sys.argv[8],
            "comment_mode": sys.argv[9],
            "comment_binding": binding,
            "branch_append": append,
            "issue_project_pr_mirrors_mutated": False,
        },
        sort_keys=True,
    )
)
PY
