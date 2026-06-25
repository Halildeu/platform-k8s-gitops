#!/usr/bin/env bash
# Offline regression test for the Faz 22.6 release-train graduation/hygiene
# evaluator (release_train_verdict) in faz22-6-release-lineage-audit.sh.
#
# The function is pure (no gh/curl/ssh/kubectl), so each fixture is fed a
# release-list JSON directly and we assert the emitted check lines, the machine
# RELEASE_TRAIN_VERDICT line, and the return code.
#
# Context (#1939): platform-agent graduated to a clean signed v0.3 lineage.
# Latest stable is v0.3.3; v0.2.13..v0.2.28 are the frozen rapid train, all
# published BEFORE the v0.3.0 boundary (2026-06-24T09:04:29Z). The stale
# v0.2.28 exact-pin + crude v0.2.x count produced FALSE blocked/needs_hygiene.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Pin policy-derived inputs so the test is deterministic regardless of future
# SSOT edits (the SSOT shape itself is gated by check-endpoint-agent-release-policy.sh).
export AGENT_RELEASE_TRUSTED_SERIES_REGEX='^v0\.3\.'
export AGENT_RELEASE_SERIES_LABEL='v0.3'
export AGENT_RELEASE_FROZEN_MINOR='v0.2'
export AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT='2026-06-24T09:04:29Z'
export AGENT_RELEASE_ACTIVE_SERIES_DENSE_THRESHOLD='8'

# Prevent main() from auto-running on source (guard already in the script).
export F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/release-train-verdict.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# run_fixture <name> <expected-rc> <expected-verdict> <releases-json>
# Captures stdout to <tmp_dir>/<name>.out and asserts the verdict + rc, then
# returns the output path for additional per-fixture line assertions.
run_fixture() {
  local name="$1" expected_rc="$2" expected_verdict="$3" json="$4"
  local out="$tmp_dir/$name.out" rc
  set +e
  release_train_verdict "$json" >"$out" 2>&1
  rc="$?"
  set -e
  [ "$rc" = "$expected_rc" ] || fail "$name: expected rc=$expected_rc got rc=$rc; output:
$(cat "$out")"
  grep -q "^RELEASE_TRAIN_VERDICT=$expected_verdict\$" "$out" \
    || fail "$name: expected RELEASE_TRAIN_VERDICT=$expected_verdict; output:
$(cat "$out")"
  printf '%s' "$out"
}

# ---------------------------------------------------------------------------
# (a) latest=v0.3.3 stable + window has v0.2.13..v0.2.28 all BEFORE boundary
#     -> pass (no waiver findings). This is the live state the fix unblocks.
# ---------------------------------------------------------------------------
fixture_a='[
  {"tagName":"v0.3.3","isLatest":true,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-25T08:25:09Z"},
  {"tagName":"v0.3.2","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-25T07:22:50Z"},
  {"tagName":"v0.3.1","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-24T13:12:26Z"},
  {"tagName":"v0.3.0","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-24T09:04:29Z"},
  {"tagName":"v0.2.28","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-22T15:06:23Z"},
  {"tagName":"v0.2.13","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-19T21:31:56Z"}
]'
out_a="$(run_fixture 'a-pass' 0 pass "$fixture_a")"
grep -q '^GITHUB_RELEASE_TRAIN_SERIES=pass latest_stable=v0.3.3 ' "$out_a" \
  || fail "a-pass: expected GITHUB_RELEASE_TRAIN_SERIES=pass latest_stable=v0.3.3"
grep -q '^GITHUB_RELEASE_FROZEN_SERIES_REGRESSION=pass .*count=0' "$out_a" \
  || fail "a-pass: expected zero frozen-series regression"
grep -q '^GITHUB_RELEASE_ACTIVE_SERIES_DENSE=pass .*active_count=4 ' "$out_a" \
  || fail "a-pass: expected active_count=4 below dense threshold"
grep -q '^RELEASE_TRAIN_WAIVER_FINDINGS=$' "$out_a" \
  || fail "a-pass: expected empty waiver findings"

# ---------------------------------------------------------------------------
# (b) latest-stable still v0.3.3 BUT a v0.2.29 published AFTER the boundary
#     (yet before v0.3.3) -> needs_hygiene (frozen-series regression). The
#     v0.2.29 publishedAt sits between the v0.3.0 boundary and v0.3.3 so the
#     trusted series is still the newest stable -> NOT blocked, only hygiene.
# ---------------------------------------------------------------------------
fixture_b='[
  {"tagName":"v0.3.3","isLatest":true,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-25T08:25:09Z"},
  {"tagName":"v0.3.0","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-24T09:04:29Z"},
  {"tagName":"v0.2.29","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-24T10:30:00Z"},
  {"tagName":"v0.2.28","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-22T15:06:23Z"}
]'
out_b="$(run_fixture 'b-regression' 0 needs_hygiene "$fixture_b")"
grep -q '^GITHUB_RELEASE_TRAIN_SERIES=pass latest_stable=v0.3.3 ' "$out_b" \
  || fail "b-regression: latest-stable should remain v0.3.3 (trusted), not block"
grep -q '^GITHUB_RELEASE_FROZEN_SERIES_REGRESSION=needs_hygiene .*count=1' "$out_b" \
  || fail "b-regression: expected exactly one frozen-series regression after boundary"
grep -q '^RELEASE_TRAIN_WAIVER_FINDINGS=.*GITHUB_RELEASE_FROZEN_SERIES_REGRESSION' "$out_b" \
  || fail "b-regression: regression finding must be waiver-eligible"

# ---------------------------------------------------------------------------
# (c1) GitHub "latest" pointer is a prerelease but latest-STABLE is v0.3.3
#      (trusted) -> needs_hygiene (pointer), NOT blocked.
# ---------------------------------------------------------------------------
fixture_c1='[
  {"tagName":"v0.3.4-rc.1","isLatest":true,"isDraft":false,"isPrerelease":true,"publishedAt":"2026-06-26T00:00:00Z"},
  {"tagName":"v0.3.3","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-25T08:25:09Z"}
]'
out_c1="$(run_fixture 'c1-pointer-prerelease' 0 needs_hygiene "$fixture_c1")"
grep -q '^GITHUB_RELEASE_TRAIN_SERIES=pass latest_stable=v0.3.3 ' "$out_c1" \
  || fail "c1: prerelease pointer must not block a trusted latest-stable"
grep -q '^GITHUB_RELEASE_LATEST_POINTER=needs_hygiene pointer_kind=prerelease' "$out_c1" \
  || fail "c1: prerelease pointer must be flagged as hygiene"

# ---------------------------------------------------------------------------
# (c2) latest-stable is v0.2.x (wrong series, no v0.3 stable) -> blocked_series.
# ---------------------------------------------------------------------------
fixture_c2='[
  {"tagName":"v0.2.28","isLatest":true,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-22T15:06:23Z"},
  {"tagName":"v0.2.27","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-22T13:57:53Z"}
]'
out_c2="$(run_fixture 'c2-wrong-series' 1 blocked_series "$fixture_c2")"
grep -q '^GITHUB_RELEASE_TRAIN_SERIES=blocked latest_stable=v0.2.28 ' "$out_c2" \
  || fail "c2: latest-stable on frozen series must block"

# ---------------------------------------------------------------------------
# (c3) only prerelease/draft, no stable release at all -> blocked_empty.
# ---------------------------------------------------------------------------
fixture_c3='[
  {"tagName":"v0.3.4-rc.1","isLatest":true,"isDraft":false,"isPrerelease":true,"publishedAt":"2026-06-26T00:00:00Z"},
  {"tagName":"v0.3.5-draft","isLatest":false,"isDraft":true,"isPrerelease":false,"publishedAt":"2026-06-27T00:00:00Z"}
]'
out_c3="$(run_fixture 'c3-no-stable' 1 blocked_empty "$fixture_c3")"
grep -q '^GITHUB_RELEASE_LATEST_STABLE=blocked reason=no-stable-release$' "$out_c3" \
  || fail "c3: no stable release must block_empty"

# ---------------------------------------------------------------------------
# (d) exactly 8 v0.3.x in the window (== active_series_dense_threshold) ->
#     needs_hygiene (active-series dense, waiver/audit). Locks the >= boundary.
# ---------------------------------------------------------------------------
fixture_d="$(jq -nc '
  [ range(0;8)
    | { tagName: ("v0.3." + (.|tostring)),
        isLatest: (. == 7),
        isDraft: false,
        isPrerelease: false,
        publishedAt: ("2026-06-2" + (.|tostring) + "T00:00:00Z") } ]')"
out_d="$(run_fixture 'd-dense' 0 needs_hygiene "$fixture_d")"
grep -q '^GITHUB_RELEASE_ACTIVE_SERIES_DENSE=needs_hygiene .*active_count=8 threshold=8 reason=active-series-dense-requires-lineage-audit-or-waiver' "$out_d" \
  || fail "d-dense: active_count==threshold(8) must be needs_hygiene (>=)"
grep -q '^RELEASE_TRAIN_WAIVER_FINDINGS=.*GITHUB_RELEASE_ACTIVE_SERIES_DENSE' "$out_d" \
  || fail "d-dense: dense finding must be waiver-eligible"

# ---------------------------------------------------------------------------
# (e) FUTURE graduation: trusted series ^v0\.4\., frozen minor v0.3, a v0.3.9
#     published AFTER a v0.4 boundary -> needs_hygiene. This proves the
#     frozen-series regex is SSOT-DERIVED from AGENT_RELEASE_FROZEN_MINOR, not
#     hardcoded to v0.2 (#1939 post-impl Codex REVISE 019efe62). With the old
#     hardcoded ^v0\.2\. this returned a FALSE pass (count=0).
# ---------------------------------------------------------------------------
fixture_e='[
  {"tagName":"v0.4.1","isLatest":true,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-07-02T00:00:00Z"},
  {"tagName":"v0.4.0","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-07-01T00:00:00Z"},
  {"tagName":"v0.3.9","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-07-01T10:30:00Z"},
  {"tagName":"v0.3.0","isLatest":false,"isDraft":false,"isPrerelease":false,"publishedAt":"2026-06-24T09:04:29Z"}
]'
out_e="$(
  export AGENT_RELEASE_TRUSTED_SERIES_REGEX='^v0\.4\.'
  export AGENT_RELEASE_SERIES_LABEL='v0.4'
  export AGENT_RELEASE_FROZEN_MINOR='v0.3'
  export AGENT_RELEASE_TRUSTED_LINEAGE_STARTED_AT='2026-07-01T00:00:00Z'
  run_fixture 'e-frozen-derived' 0 needs_hygiene "$fixture_e"
)"
grep -q '^GITHUB_RELEASE_TRAIN_SERIES=pass latest_stable=v0.4.1 ' "$out_e" \
  || fail "e: latest-stable v0.4.1 on trusted ^v0\\.4\\. must pass series"
grep -q '^GITHUB_RELEASE_FROZEN_SERIES_REGRESSION=needs_hygiene frozen_series=v0.3 count=1' "$out_e" \
  || fail "e: frozen regex must derive from AGENT_RELEASE_FROZEN_MINOR (v0.3.9 after v0.4 boundary counted, NOT hardcoded v0.2)"

echo "release-train-verdict-ok"
