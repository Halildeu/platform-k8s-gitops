#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 --phase <pre-consent-phase> --state-file <path> --resume-guard <executable> -- command [args...]" >&2
  exit 2
}

phase=""
state_file=""
resume_guard=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --phase) [ "$#" -ge 2 ] || usage; phase="$2"; shift 2 ;;
    --state-file) [ "$#" -ge 2 ] || usage; state_file="$2"; shift 2 ;;
    --resume-guard) [ "$#" -ge 2 ] || usage; resume_guard="$2"; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

[ -n "$phase" ] && [ -n "$state_file" ] && [ -n "$resume_guard" ] && [ "$#" -gt 0 ] || usage
case "$phase" in
  pre-consent-revalidation|pre-consent-activation) ;;
  *) echo "unsupported or post-consent phase: $phase" >&2; exit 2 ;;
esac
[ -x "$resume_guard" ] || { echo "resume guard is not executable" >&2; exit 2; }

run_id="${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
run_attempt="${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
[ "$run_attempt" = "1" ] || { echo "workflow rerun is not resumable" >&2; exit 2; }

install -d -m 0700 "$(dirname "$state_file")"
if [ -e "$state_file" ]; then
  [ ! -L "$state_file" ] || { echo "supervisor state must not be a symlink" >&2; exit 2; }
  [ "$(stat -f '%Lp' "$state_file" 2>/dev/null || stat -c '%a' "$state_file")" = "600" ] \
    || { echo "supervisor state must be mode 0600" >&2; exit 2; }
  jq -e --arg phase "$phase" --arg runId "$run_id" --arg runAttempt "$run_attempt" '
    .schemaVersion == "faz22.6.viewOnlySameJobSupervisor.v1"
    and .phase == $phase and .runId == $runId and .runAttempt == $runAttempt
    and .consentStarted == false and .completed == false
  ' "$state_file" >/dev/null
else
  tmp="$(mktemp "$(dirname "$state_file")/.supervisor.XXXXXX")"
  chmod 600 "$tmp"
  jq -S -n --arg phase "$phase" --arg runId "$run_id" --arg runAttempt "$run_attempt" '
    {
      schemaVersion:"faz22.6.viewOnlySameJobSupervisor.v1",
      phase:$phase,
      runId:$runId,
      runAttempt:$runAttempt,
      childAttempts:0,
      resumeGuardChecks:0,
      consentStarted:false,
      completed:false
    }
  ' > "$tmp"
  mv -f "$tmp" "$state_file"
fi

backoffs=(5 15)
max_restarts=2
child_attempt=0
while :; do
  child_attempt=$((child_attempt + 1))
  tmp="$(mktemp "$(dirname "$state_file")/.supervisor.XXXXXX")"
  chmod 600 "$tmp"
  jq -S --argjson attempt "$child_attempt" '.childAttempts = $attempt' "$state_file" > "$tmp"
  mv -f "$tmp" "$state_file"

  set +e
  "$@"
  child_rc=$?
  set -e
  if [ "$child_rc" -eq 0 ]; then
    tmp="$(mktemp "$(dirname "$state_file")/.supervisor.XXXXXX")"
    chmod 600 "$tmp"
    jq -S '.completed = true' "$state_file" > "$tmp"
    mv -f "$tmp" "$state_file"
    exit 0
  fi

  restart_index=$((child_attempt - 1))
  if [ "$restart_index" -ge "$max_restarts" ]; then
    exit "$child_rc"
  fi

  [ "${GITHUB_RUN_ID:-}" = "$run_id" ] && [ "${GITHUB_RUN_ATTEMPT:-}" = "$run_attempt" ] \
    || { echo "GitHub job identity changed; resume denied" >&2; exit 1; }
  "$resume_guard" --phase "$phase" --failed-attempt "$child_attempt" --state-file "$state_file"
  tmp="$(mktemp "$(dirname "$state_file")/.supervisor.XXXXXX")"
  chmod 600 "$tmp"
  jq -S '.resumeGuardChecks += 1' "$state_file" > "$tmp"
  mv -f "$tmp" "$state_file"
  sleep "${backoffs[$restart_index]}"
done
