#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
SUPERVISOR="$ROOT/scripts/faz22-remote-ops/run-view-only-same-job-supervisor.sh"
tmpdir="$(mktemp -d /tmp/faz22-supervisor-test.XXXXXX)"
trap 'rm -rf -- "$tmpdir"' EXIT

cat > "$tmpdir/guard" <<'GUARD'
#!/usr/bin/env bash
set -euo pipefail
printf 'guard\n' >> "$TEST_EVENTS"
GUARD
cat > "$tmpdir/child" <<'CHILD'
#!/usr/bin/env bash
set -euo pipefail
count=0
[ ! -s "$TEST_COUNT" ] || count="$(cat "$TEST_COUNT")"
count=$((count + 1))
printf '%s' "$count" > "$TEST_COUNT"
printf 'child-%s\n' "$count" >> "$TEST_EVENTS"
[ "$count" -ge "${TEST_SUCCESS_AT:-3}" ]
CHILD
chmod 700 "$tmpdir/guard" "$tmpdir/child"

export GITHUB_RUN_ID=123456
export GITHUB_RUN_ATTEMPT=1
export TEST_COUNT="$tmpdir/count"
export TEST_EVENTS="$tmpdir/events"
export TEST_SUCCESS_AT=3

# Avoid real sleeps while preserving the exact supervisor backoff arguments.
mkdir "$tmpdir/bin"
cat > "$tmpdir/bin/sleep" <<'SLEEP'
#!/usr/bin/env bash
set -euo pipefail
printf 'sleep-%s\n' "$1" >> "$TEST_EVENTS"
SLEEP
chmod 700 "$tmpdir/bin/sleep"
PATH="$tmpdir/bin:$PATH" "$SUPERVISOR" \
  --phase pre-consent-revalidation \
  --state-file "$tmpdir/state.json" \
  --resume-guard "$tmpdir/guard" \
  -- "$tmpdir/child"

diff -u <(printf '%s\n' child-1 guard sleep-5 child-2 guard sleep-15 child-3) "$TEST_EVENTS"
jq -e '.childAttempts == 3 and .resumeGuardChecks == 2 and .completed == true and .consentStarted == false' \
  "$tmpdir/state.json" >/dev/null
[ "$(stat -f '%Lp' "$tmpdir/state.json" 2>/dev/null || stat -c '%a' "$tmpdir/state.json")" = 600 ]

rm -f "$TEST_COUNT" "$TEST_EVENTS" "$tmpdir/state-deny.json"
export TEST_SUCCESS_AT=4
if PATH="$tmpdir/bin:$PATH" "$SUPERVISOR" \
  --phase pre-consent-revalidation \
  --state-file "$tmpdir/state-deny.json" \
  --resume-guard "$tmpdir/guard" \
  -- "$tmpdir/child"; then
  echo "supervisor exceeded two restarts" >&2
  exit 1
fi
[ "$(cat "$TEST_COUNT")" = 3 ]

if "$SUPERVISOR" --phase consent-pending --state-file "$tmpdir/post-consent.json" \
  --resume-guard "$tmpdir/guard" -- /usr/bin/true; then
  echo "post-consent resume was accepted" >&2
  exit 1
fi

GITHUB_RUN_ATTEMPT=2
export GITHUB_RUN_ATTEMPT
if "$SUPERVISOR" --phase pre-consent-revalidation --state-file "$tmpdir/rerun.json" \
  --resume-guard "$tmpdir/guard" -- /usr/bin/true; then
  echo "workflow rerun was accepted" >&2
  exit 1
fi
