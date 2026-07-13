#!/usr/bin/env bash
# Portable, read-only GitHub API access for Faz 22.6 audits.
#
# Developer shells may use gh. Minimal self-hosted runners can use curl+jq
# without installing mutable host packages. Tokens are passed to curl through
# stdin config so they do not appear in process arguments.

GITHUB_READ_API_BACKEND="${GITHUB_READ_API_BACKEND:-auto}"
GITHUB_READ_API_URL="${GITHUB_READ_API_URL:-${GITHUB_API_URL:-https://api.github.com}}"
GITHUB_READ_API_TRUSTED_URL="${GITHUB_API_URL:-https://api.github.com}"
GITHUB_READ_API_VERSION="${GITHUB_READ_API_VERSION:-2022-11-28}"
GITHUB_READ_API_CONNECT_TIMEOUT="${GITHUB_READ_API_CONNECT_TIMEOUT:-5}"
GITHUB_READ_API_MAX_TIME="${GITHUB_READ_API_MAX_TIME:-30}"
GITHUB_READ_API_RETRIES="${GITHUB_READ_API_RETRIES:-2}"

github_read_api_backend() {
  case "$GITHUB_READ_API_BACKEND" in
    auto)
      if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        printf 'gh'
      elif command -v curl >/dev/null 2>&1; then
        printf 'curl'
      else
        return 1
      fi
      ;;
    gh)
      command -v gh >/dev/null 2>&1 || return 1
      gh auth status >/dev/null 2>&1 || return 1
      printf 'gh'
      ;;
    curl)
      command -v curl >/dev/null 2>&1 || return 1
      printf 'curl'
      ;;
    *) return 1 ;;
  esac
}

github_read_api_preflight() {
  command -v jq >/dev/null 2>&1 || return 1
  github_read_api_backend >/dev/null
}

github_read_validate_repo() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
}

github_read_validate_number() {
  printf '%s' "$1" | grep -Eq '^[1-9][0-9]*$'
}

github_read_validate_api_path() {
  local path="$1" route query segment
  case "$path" in
    ''|*$'\n'*|*$'\r'*|*' '*|*'%'*|*'..'*|/*|*://*|*'//'*) return 1 ;;
  esac
  printf '%s' "$path" | grep -Eq '^[A-Za-z0-9_./?=&:+-]+$' || return 1

  route="${path%%\?*}"
  query=''
  if [ "$route" != "$path" ]; then
    query="${path#*\?}"
    case "$query" in
      ''|*'?'*) return 1 ;;
    esac
    printf '%s' "$query" | grep -Eq '^[A-Za-z0-9_.:+-]+=[A-Za-z0-9_.:+-]+(&[A-Za-z0-9_.:+-]+=[A-Za-z0-9_.:+-]+)*$' || return 1
  fi

  case "$route" in
    ''|*/|./*|*/./*|*/.) return 1 ;;
  esac
  while IFS= read -r segment; do
    case "$segment" in
      ''|.|..) return 1 ;;
    esac
  done < <(printf '%s' "$route" | tr '/' '\n')
}

github_read_normalize_api_url() {
  local url="${1%/}"
  case "$url" in
    https://*) ;;
    *) return 1 ;;
  esac
  case "$url" in
    *$'\n'*|*$'\r'*|*' '*|*'@'*|*'?'*|*'#'*|*'..'*) return 1 ;;
  esac
  printf '%s' "$url" | grep -Eq '^https://[A-Za-z0-9.-]+(:[1-9][0-9]{0,4})?(/[A-Za-z0-9._/-]+)?$' || return 1
  printf '%s' "$url"
}

github_read_curl_get() {
  local path="$1" token="${GH_TOKEN:-${GITHUB_TOKEN:-}}" api_url trusted_url
  github_read_validate_api_path "$path" || return 2
  api_url="$(github_read_normalize_api_url "$GITHUB_READ_API_URL")" || return 2
  trusted_url="$(github_read_normalize_api_url "$GITHUB_READ_API_TRUSTED_URL")" || return 2
  [ "$api_url" = "$trusted_url" ] || return 2
  if [ -n "$token" ] && ! [[ "$token" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    return 2
  fi

  {
    printf 'silent\n'
    printf 'show-error\n'
    printf 'fail\n'
    printf 'location\n'
    printf 'connect-timeout = %s\n' "$GITHUB_READ_API_CONNECT_TIMEOUT"
    printf 'max-time = %s\n' "$GITHUB_READ_API_MAX_TIME"
    printf 'retry = %s\n' "$GITHUB_READ_API_RETRIES"
    printf 'retry-delay = 1\n'
    printf 'retry-all-errors\n'
    printf 'header = "Accept: application/vnd.github+json"\n'
    printf 'header = "X-GitHub-Api-Version: %s"\n' "$GITHUB_READ_API_VERSION"
    printf 'header = "User-Agent: platform-k8s-gitops-faz22.6-audit"\n'
    if [ -n "$token" ]; then
      printf 'header = "Authorization: Bearer %s"\n' "$token"
    fi
  } | curl --config - "$api_url/$path"
}

github_read_api() {
  local path="$1" backend
  backend="$(github_read_api_backend)" || return 2
  github_read_validate_api_path "$path" || return 2
  case "$backend" in
    gh) gh api "$path" ;;
    curl) github_read_curl_get "$path" ;;
    *) return 2 ;;
  esac
}

github_read_issue_json() {
  local repo="$1" number="$2" fields="${3:-state,body,title,url}" backend
  github_read_validate_repo "$repo" || return 2
  github_read_validate_number "$number" || return 2
  case "$fields" in
    state,body,title|state,body,title,url) ;;
    *) return 2 ;;
  esac
  backend="$(github_read_api_backend)" || return 2
  case "$backend" in
    gh)
      gh issue view "$number" -R "$repo" --json "$fields"
      ;;
    curl)
      if [ "$fields" = "state,body,title,url" ]; then
        github_read_curl_get "repos/${repo}/issues/${number}" \
          | jq -c '{state: ((.state // "") | ascii_upcase), body: (.body // ""), title: (.title // ""), url: (.html_url // "")}'
      else
        github_read_curl_get "repos/${repo}/issues/${number}" \
          | jq -c '{state: ((.state // "") | ascii_upcase), body: (.body // ""), title: (.title // "")}'
      fi
      ;;
    *) return 2 ;;
  esac
}

github_read_releases_json() {
  local repo="$1" limit="$2" backend releases latest_before latest_after
  local latest_before_id latest_after_id attempt
  github_read_validate_repo "$repo" || return 2
  printf '%s' "$limit" | grep -Eq '^[1-9][0-9]{0,2}$' || return 2
  [ "$limit" -le 100 ] || return 2
  backend="$(github_read_api_backend)" || return 2
  case "$backend" in
    gh)
      gh release list -R "$repo" --limit "$limit" \
        --json tagName,isLatest,isDraft,isPrerelease,isImmutable,publishedAt,name
      ;;
    curl)
      attempt=0
      while [ "$attempt" -lt 3 ]; do
        attempt=$((attempt + 1))
        latest_before="$(github_read_curl_get "repos/${repo}/releases/latest")" || return 1
        latest_before_id="$(printf '%s\n' "$latest_before" | jq -er '.id | tostring')" || return 1
        releases="$(github_read_curl_get "repos/${repo}/releases?per_page=${limit}")" || return 1
        latest_after="$(github_read_curl_get "repos/${repo}/releases/latest")" || return 1
        latest_after_id="$(printf '%s\n' "$latest_after" | jq -er '.id | tostring')" || return 1

        if [ "$latest_before_id" = "$latest_after_id" ] \
          && printf '%s\n' "$releases" | jq -e --arg latest_id "$latest_after_id" \
            'any(.[]; ((.id // "") | tostring) == $latest_id)' >/dev/null; then
          printf '%s\n' "$releases" | jq -c --arg latest_id "$latest_after_id" '[.[] | {
            tagName: (.tag_name // ""),
            isLatest: (((.id // "") | tostring) == $latest_id),
            isDraft: (.draft // false),
            isPrerelease: (.prerelease // false),
            isImmutable: (if (.immutable | type) == "boolean" then .immutable else false end),
            publishedAt: (.published_at // ""),
            name: (.name // "")
          }]'
          return
        fi
      done
      return 1
      ;;
    *) return 2 ;;
  esac
}
