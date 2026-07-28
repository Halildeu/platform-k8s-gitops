#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/github-read-api.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"

cat >"$fake_bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
config="$(cat)"
printf '%s\n' "$*" >>"$FAKE_CURL_ARGS_LOG"
printf '%s\n--call--\n' "$config" >>"$FAKE_CURL_CONFIG_LOG"
url="${!#}"
case "$url" in
  */repos/Halildeu/platform-backend/issues/548)
    printf '%s\n' '{"state":"closed","body":"marker","title":"B1.4","html_url":"https://github.com/Halildeu/platform-backend/issues/548"}'
    ;;
  *'/repos/Halildeu/platform-agent/releases?per_page=2')
    printf '%s\n' '[{"id":311,"tag_name":"v0.3.11","draft":false,"prerelease":false,"immutable":true,"published_at":"2026-07-03T13:46:11Z","name":"v0.3.11"},{"id":310,"tag_name":"v0.3.10","draft":false,"prerelease":false,"immutable":true,"published_at":"2026-07-03T12:00:00Z","name":"v0.3.10"}]'
    ;;
  */repos/Halildeu/platform-agent/releases/latest)
    latest_call=0
    if [ -f "$FAKE_LATEST_CALL_FILE" ]; then
      latest_call="$(cat "$FAKE_LATEST_CALL_FILE")"
    fi
    latest_call=$((latest_call + 1))
    printf '%s' "$latest_call" >"$FAKE_LATEST_CALL_FILE"
    if [ "${FAKE_RELEASE_MODE:-stable}" = "race-once" ] && [ "$latest_call" = "1" ]; then
      printf '%s\n' '{"id":310,"tag_name":"v0.3.10"}'
    else
      printf '%s\n' '{"id":311,"tag_name":"v0.3.11"}'
    fi
    ;;
  */repos/Halildeu/platform-agent/git/ref/tags/v0.3.11)
    printf '%s\n' '{"object":{"type":"tag","sha":"tag-object-sha"}}'
    ;;
  */repos/Halildeu/platform-agent/git/tags/tag-object-sha)
    printf '%s\n' '{"object":{"type":"commit","sha":"commit-sha"}}'
    ;;
  *)
    printf 'unexpected fake curl URL: %s\n' "$url" >&2
    exit 22
    ;;
esac
SH
chmod +x "$fake_bin/curl"

cat >"$fake_bin/gh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "auth" ] && [ "${2:-}" = "status" ]; then
  [ "${FAKE_GH_AUTH:-fail}" = "pass" ]
  exit
fi
printf 'unexpected fake gh invocation: %s\n' "$*" >&2
exit 2
SH
chmod +x "$fake_bin/gh"

export PATH="$fake_bin:$PATH"
export GITHUB_READ_API_BACKEND=curl
export GITHUB_READ_API_URL=https://api.github.test
export GITHUB_API_URL=https://api.github.test
export GH_TOKEN=unit-test-token-not-a-secret
export FAKE_CURL_ARGS_LOG="$tmp_dir/curl-args.log"
export FAKE_CURL_CONFIG_LOG="$tmp_dir/curl-config.log"
export FAKE_LATEST_CALL_FILE="$tmp_dir/latest-call"

# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/lib-github-read-api.sh"

[ "$(github_read_api_backend)" = "curl" ]
github_read_api_preflight

issue_json="$(github_read_issue_json Halildeu/platform-backend 548 state,body,title,url)"
jq -e '
  .state == "CLOSED"
  and .body == "marker"
  and .title == "B1.4"
  and .url == "https://github.com/Halildeu/platform-backend/issues/548"
' <<<"$issue_json" >/dev/null

releases_json="$(github_read_releases_json Halildeu/platform-agent 2)"
jq -e '
  length == 2
  and .[0].tagName == "v0.3.11"
  and .[0].isLatest == true
  and .[0].isImmutable == true
  and .[1].isLatest == false
' <<<"$releases_json" >/dev/null
[ "$(cat "$FAKE_LATEST_CALL_FILE")" = "2" ]

rm -f "$FAKE_LATEST_CALL_FILE"
export FAKE_RELEASE_MODE=race-once
race_releases_json="$(github_read_releases_json Halildeu/platform-agent 2)"
jq -e '.[0].tagName == "v0.3.11" and .[0].isLatest == true' <<<"$race_releases_json" >/dev/null
[ "$(cat "$FAKE_LATEST_CALL_FILE")" = "4" ]
unset FAKE_RELEASE_MODE

tag_ref="$(github_read_api repos/Halildeu/platform-agent/git/ref/tags/v0.3.11)"
jq -e '.object.type == "tag" and .object.sha == "tag-object-sha"' <<<"$tag_ref" >/dev/null
tag_commit="$(github_read_api repos/Halildeu/platform-agent/git/tags/tag-object-sha | jq -r '.object.sha')"
[ "$tag_commit" = "commit-sha" ]

if grep -q 'unit-test-token-not-a-secret' "$FAKE_CURL_ARGS_LOG"; then
  echo "GitHub token leaked into curl process arguments" >&2
  exit 1
fi
grep -q 'header = "Authorization: Bearer unit-test-token-not-a-secret"' "$FAKE_CURL_CONFIG_LOG"
grep -q 'header = "X-GitHub-Api-Version: 2022-11-28"' "$FAKE_CURL_CONFIG_LOG"
grep -q '^fail$' "$FAKE_CURL_CONFIG_LOG"
if grep -q '^fail-with-body$' "$FAKE_CURL_CONFIG_LOG"; then
  echo "curl backend must not forward HTTP error bodies into JSON parsers" >&2
  exit 1
fi

[ "$(GITHUB_READ_API_BACKEND=auto FAKE_GH_AUTH=fail github_read_api_backend)" = "curl" ]
[ "$(GITHUB_READ_API_BACKEND=auto FAKE_GH_AUTH=pass github_read_api_backend)" = "gh" ]

calls_before="$(wc -l <"$FAKE_CURL_ARGS_LOG" | tr -d ' ')"
set +e
GH_TOKEN=$'bad\ntoken' github_read_api repos/Halildeu/platform-agent/git/ref/tags/v0.3.11 >/dev/null 2>&1
unsafe_token_rc="$?"
github_read_api '../unsafe' >/dev/null 2>&1
unsafe_path_rc="$?"
github_read_api 'repos/Halildeu/platform-agent/%2e%2e/releases' >/dev/null 2>&1
encoded_path_rc="$?"
GITHUB_READ_API_URL=https://api.github.test.evil.example github_read_api repos/Halildeu/platform-agent/releases/latest >/dev/null 2>&1
unsafe_origin_rc="$?"
github_read_issue_json 'bad repo' 548 >/dev/null 2>&1
unsafe_repo_rc="$?"
set -e
[ "$unsafe_token_rc" = "2" ]
[ "$unsafe_path_rc" = "2" ]
[ "$encoded_path_rc" = "2" ]
[ "$unsafe_origin_rc" = "2" ]
[ "$unsafe_repo_rc" = "2" ]
calls_after="$(wc -l <"$FAKE_CURL_ARGS_LOG" | tr -d ' ')"
[ "$calls_before" = "$calls_after" ]

workflow="$ROOT/.github/workflows/faz22-6-live-audit.yml"
grep -q '^      GITHUB_READ_API_BACKEND: curl$' "$workflow"
grep -q "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10" "$workflow"
grep -q "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" "$workflow"
grep -q 'python-version: "3.12.3"' "$workflow"
grep -q 'check-latest: false' "$workflow"
grep -q 'python -m venv "$RUNNER_TEMP/faz22-audit-venv"' "$workflow"
if grep -q 'python3 -m venv "$RUNNER_TEMP/faz22-audit-venv"' "$workflow"; then
  echo "Faz 22.6 live audit still relies on the self-hosted runner system Python venv" >&2
  exit 1
fi
grep -q "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" "$workflow"
grep -q "'\^F22_6_COMPLETION=pass\$'" "$workflow"
if grep -Eq '^[[:space:]]*need gh$' \
  "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh" \
  "$ROOT/scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh"; then
  echo "Faz 22.6 audits still hard-require gh" >&2
  exit 1
fi

echo "faz22-6-github-read-api-ok"
