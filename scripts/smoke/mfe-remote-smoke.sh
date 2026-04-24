#!/usr/bin/env bash
# MFE Remote Smoke Test — Module Federation remote discoverability kontrolü
#
# Amaç: platform-web frontend image'ında 7 MFE remote'un hepsinin
# remoteEntry.js erişilebilir olduğunu doğrular. 2026-04-25 schema-explorer
# regression'ı benzer hataları önceden yakalar.
#
# Kullanım:
#   bash scripts/smoke/mfe-remote-smoke.sh [test|prod|both]
#
# Exit codes:
#   0 — tüm 7 MFE remote OK
#   1 — en az 1 remote 404/5xx
#
# CI workflow: .github/workflows/ci-live-smoke.yml (workflow_dispatch)

set -euo pipefail

TARGET="${1:-both}"

MFE_REMOTES=(
  "access"
  "audit"
  "reporting"
  "users"
  "schema-explorer"
  "suggestions"
  "ethic"
)

check_host() {
  local host="$1"
  local label="$2"
  local fail=0
  local total=${#MFE_REMOTES[@]}

  echo "=== ${label} (${host}) ==="

  # Shell root
  local root_status
  root_status=$(curl -sS -o /dev/null -w '%{http_code}' -k "https://${host}/")
  echo "  shell /                         → ${root_status}"
  [[ "${root_status}" != "200" ]] && { fail=$((fail + 1)); echo "  FAIL shell root"; }

  # Shell remoteEntry.js
  local shell_status
  shell_status=$(curl -sS -o /dev/null -w '%{http_code}' -k "https://${host}/remoteEntry.js")
  echo "  shell /remoteEntry.js           → ${shell_status}"
  [[ "${shell_status}" != "200" ]] && { fail=$((fail + 1)); echo "  FAIL shell remoteEntry.js"; }

  # 7 MFE remoteEntry.js
  for slug in "${MFE_REMOTES[@]}"; do
    local status
    status=$(curl -sS -o /dev/null -w '%{http_code}' -k "https://${host}/remotes/${slug}/remoteEntry.js")
    printf "  /remotes/%-18s → %s\n" "${slug}/remoteEntry.js" "${status}"
    [[ "${status}" != "200" ]] && fail=$((fail + 1))
  done

  # Admin route (shell render)
  for slug in "${MFE_REMOTES[@]}"; do
    local admin_status
    admin_status=$(curl -sS -o /dev/null -w '%{http_code}' -k "https://${host}/admin/${slug}")
    printf "  /admin/%-18s → %s\n" "${slug}" "${admin_status}"
    [[ "${admin_status}" != "200" ]] && fail=$((fail + 1))
  done

  echo "  Result: ${fail} fail / $((total * 2 + 2)) checks"
  return ${fail}
}

failures=0

if [[ "${TARGET}" == "test" ]] || [[ "${TARGET}" == "both" ]]; then
  check_host "testai.acik.com" "TEST" || failures=$((failures + $?))
fi

if [[ "${TARGET}" == "prod" ]] || [[ "${TARGET}" == "both" ]]; then
  check_host "ai.acik.com" "PROD" || failures=$((failures + $?))
fi

echo ""
if [[ ${failures} -eq 0 ]]; then
  echo "=== MFE REMOTE SMOKE PASS — 7 MFE + shell reachable ==="
  exit 0
else
  echo "=== MFE REMOTE SMOKE FAIL (${failures} endpoint) ==="
  exit 1
fi
