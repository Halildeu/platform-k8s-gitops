#!/usr/bin/env bash
set -u

SCHEMA_VERSION="faz24.i3.runner.wg-tool.v1"
EXPECTED_CONFIRM="INSTALL_WIREGUARD_TOOLS_FOR_FAZ24_I3"
MODE="${FAZ24_I3_WG_TOOL_MODE:-verify}"
CONFIRM="${FAZ24_I3_WG_TOOL_CONFIRM:-}"
PACKAGE_MANAGER="${FAZ24_I3_WG_TOOL_PACKAGE_MANAGER:-auto}"
EVIDENCE_JSON="${FAZ24_I3_WG_TOOL_EVIDENCE_JSON:-/tmp/faz24-i3-runner-wg-tool.json}"

WG_CANDIDATES=(
  "wg"
  "/usr/bin/wg"
  "/usr/sbin/wg"
  "/usr/local/bin/wg"
  "/snap/bin/wg"
  "/opt/homebrew/bin/wg"
)

now_utc() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

json_string() {
  python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
}

run_candidate() {
  local candidate="$1"
  "$candidate" --version >/dev/null 2>&1 && return 0
  if command -v sudo >/dev/null 2>&1; then
    sudo -n "$candidate" --version >/dev/null 2>&1 && return 0
  fi
  return 1
}

probe_wg() {
  WG_FOUND=false
  WG_SELECTED=""
  WG_PROBE_EXIT_CODE=127

  local candidate
  for candidate in "${WG_CANDIDATES[@]}"; do
    if run_candidate "$candidate"; then
      WG_FOUND=true
      WG_SELECTED="$candidate"
      WG_PROBE_EXIT_CODE=0
      return 0
    fi
  done

  return 1
}

detect_package_manager() {
  if [[ "$PACKAGE_MANAGER" != "auto" ]]; then
    printf '%s\n' "$PACKAGE_MANAGER"
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' "apt-get"
  elif command -v dnf >/dev/null 2>&1; then
    printf '%s\n' "dnf"
  elif command -v yum >/dev/null 2>&1; then
    printf '%s\n' "yum"
  elif command -v zypper >/dev/null 2>&1; then
    printf '%s\n' "zypper"
  elif command -v apk >/dev/null 2>&1; then
    printf '%s\n' "apk"
  else
    printf '%s\n' "unsupported"
  fi
}

install_wireguard_tools() {
  local manager="$1"

  if ! command -v sudo >/dev/null 2>&1; then
    INSTALL_REASON="sudo-not-found"
    return 1
  fi
  if ! sudo -n true >/dev/null 2>&1; then
    INSTALL_REASON="sudo-noninteractive-unavailable"
    return 1
  fi

  case "$manager" in
    apt-get)
      sudo -n apt-get update -y
      sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends wireguard-tools
      ;;
    dnf)
      sudo -n dnf install -y wireguard-tools
      ;;
    yum)
      sudo -n yum install -y wireguard-tools
      ;;
    zypper)
      sudo -n zypper --non-interactive install wireguard-tools
      ;;
    apk)
      sudo -n apk add wireguard-tools
      ;;
    *)
      INSTALL_REASON="unsupported-package-manager"
      return 1
      ;;
  esac
}

write_evidence() {
  local status="$1"
  local reason="$2"
  local manager="$3"
  local install_attempted="$4"
  local installed="$5"
  local collected_at
  collected_at="$(now_utc)"

  mkdir -p "$(dirname "$EVIDENCE_JSON")"
  cat >"$EVIDENCE_JSON" <<EOF
{
  "schemaVersion": $(json_string "$SCHEMA_VERSION"),
  "collectedAt": $(json_string "$collected_at"),
  "mode": $(json_string "$MODE"),
  "status": $(json_string "$status"),
  "reason": $(json_string "$reason"),
  "runner": "staging-sw",
  "packageManager": $(json_string "$manager"),
  "installAttempted": $install_attempted,
  "installed": $installed,
  "wgToolFound": $WG_FOUND,
  "wgToolSelected": $(json_string "$WG_SELECTED"),
  "wgToolProbeExitCode": $WG_PROBE_EXIT_CODE,
  "rollbackHint": "If this workflow installed wireguard-tools, remove with the host package manager only after confirming no other runner job depends on wg."
}
EOF
}

main() {
  case "$MODE" in
    verify|install) ;;
    *)
      WG_FOUND=false
      WG_SELECTED=""
      WG_PROBE_EXIT_CODE=127
      write_evidence "blocked" "invalid-mode" "unknown" false false
      echo "FAZ24_I3_WG_TOOL status=blocked reason=invalid-mode mode=${MODE}"
      return 1
      ;;
  esac

  local manager install_attempted installed reason
  manager="$(detect_package_manager)"
  install_attempted=false
  installed=false
  reason=""

  if probe_wg; then
    write_evidence "pass" "wg-tool-already-available" "$manager" "$install_attempted" "$installed"
    echo "FAZ24_I3_WG_TOOL status=pass reason=wg-tool-already-available selected=${WG_SELECTED}"
    return 0
  fi

  if [[ "$MODE" == "verify" ]]; then
    write_evidence "blocked" "wg-tool-missing" "$manager" "$install_attempted" "$installed"
    echo "FAZ24_I3_WG_TOOL status=blocked reason=wg-tool-missing manager=${manager}"
    return 1
  fi

  if [[ "$CONFIRM" != "$EXPECTED_CONFIRM" ]]; then
    write_evidence "blocked" "confirm-mismatch" "$manager" "$install_attempted" "$installed"
    echo "FAZ24_I3_WG_TOOL status=blocked reason=confirm-mismatch"
    return 1
  fi

  install_attempted=true
  INSTALL_REASON=""
  if install_wireguard_tools "$manager"; then
    if probe_wg; then
      installed=true
      write_evidence "pass" "wg-tool-installed" "$manager" "$install_attempted" "$installed"
      echo "FAZ24_I3_WG_TOOL status=pass reason=wg-tool-installed selected=${WG_SELECTED}"
      return 0
    fi
    reason="install-completed-but-wg-still-missing"
  else
    reason="${INSTALL_REASON:-install-command-failed}"
  fi

  write_evidence "blocked" "$reason" "$manager" "$install_attempted" "$installed"
  echo "FAZ24_I3_WG_TOOL status=blocked reason=${reason} manager=${manager}"
  return 1
}

main "$@"
