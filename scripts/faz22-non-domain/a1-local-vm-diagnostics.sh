#!/usr/bin/env bash
# shellcheck disable=SC2016
# Faz 22.2.A / #1044 — local Parallels A1 read-only diagnostics helper.
#
# Purpose:
#   Collect repeatable, sanitized, per-VM local Windows evidence after the
#   operator has prepared HALILKOOLUB735 and the two additional local Parallels
#   devices. This helper is read-only: it does not stop/suspend/clone VMs, does
#   not install/uninstall software, does not dispatch backend commands, does not
#   mutate accounts, and does not read credential file contents.
#
# Usage:
#   bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh
#   bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh --dry-run
#   bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
#     --vm "Windows 11" \
#     --vm "NONDOMAIN-W11-LAB-01" \
#     --vm "NONDOMAIN-W11-LAB-02"
#   bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
#     --include-winget-egress \
#     --section-timeout-seconds 120 \
#     --vm "Windows 11"

set -euo pipefail

VMS=("Windows 11")
OUT_DIR=""
DRY_RUN=0
INCLUDE_WINGET_EGRESS=0
SECTION_TIMEOUT_SECONDS=45

usage() {
  sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log() {
  printf '[faz22-a1-local-vm-diagnostics] %s\n' "$*"
}

die() {
  printf '[faz22-a1-local-vm-diagnostics] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

safe_vm_ref() {
  [ -n "$1" ] || return 1
  case "$1" in
    *$'\n'*|*$'\r'*|*$'\t'*)
      return 1
      ;;
  esac
  return 0
}

safe_path_component() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9_.-' '_'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage 0
      ;;
    --vm)
      [ -n "${2:-}" ] || die "--vm requires a VM name"
      safe_vm_ref "$2" || die "--vm contains unsafe whitespace/control characters"
      if [ "${#VMS[@]}" -eq 1 ] && [ "${VMS[0]}" = "Windows 11" ]; then
        VMS=()
      fi
      VMS+=("$2")
      shift 2
      ;;
    --output-dir)
      OUT_DIR="${2:-}"
      [ -n "$OUT_DIR" ] || die "--output-dir requires a path"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --include-winget-egress)
      INCLUDE_WINGET_EGRESS=1
      shift
      ;;
    --section-timeout-seconds)
      SECTION_TIMEOUT_SECONDS="${2:-}"
      [[ "$SECTION_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--section-timeout-seconds must be an integer"
      [ "$SECTION_TIMEOUT_SECONDS" -gt 0 ] || die "--section-timeout-seconds must be > 0"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown flag: $1"
      ;;
    *)
      die "unexpected positional argument: $1"
      ;;
  esac
done

[ "${#VMS[@]}" -gt 0 ] || die "at least one --vm is required"

require_cmd prlctl
require_cmd iconv
require_cmd base64
require_cmd date
require_cmd mkdir
require_cmd grep
require_cmd sed
require_cmd rm
require_cmd sleep
require_cmd kill

if [ -z "$OUT_DIR" ]; then
  OUT_DIR="/tmp/faz22-a1-local-vm-diagnostics-$(date -u +%Y%m%dT%H%M%SZ)"
fi

log "output_dir=$OUT_DIR"
log "vm_count=${#VMS[@]}"
log "mode=$([ "$DRY_RUN" -eq 1 ] && printf 'dry-run' || printf 'execute-read-only')"
log "include_winget_egress=$INCLUDE_WINGET_EGRESS"
log "section_timeout_seconds=$SECTION_TIMEOUT_SECONDS"

for vm in "${VMS[@]}"; do
  safe_vm_ref "$vm" || die "unsafe VM name: $vm"
  status="$(prlctl status "$vm" 2>&1 || true)"
  log "vm=$vm status=$status"
  if ! printf '%s\n' "$status" | grep -qi 'running'; then
    die "VM must be running for read-only diagnostics: $vm"
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  log "dry-run complete; no guest commands executed"
  exit 0
fi

redact_output() {
  sed -E \
    -e 's/(eyJ[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{10,})/<jwt-redacted>/g' \
    -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\\/=-]+/\\1<redacted>/Ig' \
    -e 's/(Authorization:[[:space:]]*)[^[:space:]]+/\\1<redacted>/Ig' \
    -e 's/(credential=)[^,;[:space:]]+/\\1<redacted>/Ig' \
    -e 's/(token|secret|password|clientSecret|accessToken|refreshToken)[[:space:]]*[:=][^,}\\r\\n]+/\\1=<redacted>/Ig' \
    -e 's/S-1-5-21-[0-9-]+/S-1-5-21-***/g' \
    -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}/<email-redacted>/g' \
    -e 's/C:\\\\Users\\\\[^\\\\\\r\\n"]+/C:\\\\Users\\\\<user-redacted>/g' \
    -e 's/"username":"[^"]+"/"username":"<user-redacted>"/g' \
    -e 's/"userName":"[^"]+"/"userName":"<user-redacted>"/g' \
    -e 's/\\r$//'
}

run_guest_ps() {
  local vm="$1"
  local out_file="$2"
  local section="$3"
  local timeout="$4"
  local ps_body="$5"
  local encoded raw_file child_pid elapsed rc wrapped_ps

  raw_file="${out_file}.${section}.raw"
  wrapped_ps='
$ProgressPreference = "SilentlyContinue"
$WarningPreference = "Continue"
'
  wrapped_ps="${wrapped_ps}${ps_body}"
  encoded="$(printf '%s' "$wrapped_ps" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')"

  {
    printf '\n=== %s ===\n' "$section"
  } >>"$out_file"

  prlctl exec "$vm" powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand "$encoded" >"$raw_file" 2>&1 &
  child_pid=$!
  elapsed=0
  while kill -0 "$child_pid" >/dev/null 2>&1; do
    if [ "$elapsed" -ge "$timeout" ]; then
      kill "$child_pid" >/dev/null 2>&1 || true
      sleep 2
      kill -9 "$child_pid" >/dev/null 2>&1 || true
      {
        printf 'TIMEOUT section=%s timeout_seconds=%s raw_output_path=%s\n' "$section" "$timeout" "$raw_file"
      } >>"$out_file"
      return 124
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if wait "$child_pid"; then
    rc=0
  else
    rc=$?
  fi

  redact_output <"$raw_file" >>"$out_file"
  printf 'PRLCTL_EXIT=%s\n' "$rc" >>"$out_file"
  rm -f "$raw_file"
}

scan_output() {
  local out_file="$1"
  if grep -Ei '(eyJ[A-Za-z0-9_-]{20,}\.|Bearer[[:space:]]+[^<]|Authorization:[[:space:]]*[^<]|credential=[^<]|(token|secret|password)[[:space:]]*[:=][^<])' "$out_file" >/dev/null; then
    die "potential secret-like output detected in $out_file; review and redact before use"
  fi
}

for vm in "${VMS[@]}"; do
  safe_vm="$(safe_path_component "$vm")"
  vm_dir="$OUT_DIR/$safe_vm"
  mkdir -p "$vm_dir"
  out_file="$vm_dir/read-only-diagnostics.txt"
  : >"$out_file"
  log "collecting vm=$vm out=$out_file"

  run_guest_ps "$vm" "$out_file" "timestamp-host-computer" "$SECTION_TIMEOUT_SECONDS" '
$ErrorActionPreference = "Continue"
Get-Date -Format o
hostname
Get-CimInstance Win32_ComputerSystem | Select-Object Name,PartOfDomain,Domain,Workgroup | Format-List | Out-String
'

  run_guest_ps "$vm" "$out_file" "dsregcmd" "$SECTION_TIMEOUT_SECONDS" '
$ErrorActionPreference = "Continue"
try {
  dsregcmd /status | Select-String -Pattern "AzureAdJoined|EnterpriseJoined|DomainJoined|DeviceName|TenantName|WorkplaceJoined"
} catch {
  Write-Output ("dsregcmd failed: " + $_.Exception.Message)
}
'

  run_guest_ps "$vm" "$out_file" "backend-reachability" "$SECTION_TIMEOUT_SECONDS" '
$ErrorActionPreference = "Continue"
try {
  $ok = Test-NetConnection testai.acik.com -Port 443 -InformationLevel Quiet
  Write-Output ("testai.acik.com:443 reachable=" + $ok)
} catch {
  Write-Output ("reachability failed: " + $_.Exception.Message)
}
'

  run_guest_ps "$vm" "$out_file" "service-process-version" "$SECTION_TIMEOUT_SECONDS" '
$ErrorActionPreference = "Continue"
$exe = "C:\Program Files\EndpointAgent\endpoint-agent.exe"
Get-Service EndpointAgent -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | Format-List | Out-String
Get-Process endpoint-agent -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime,WorkingSet64,Path | Format-List | Out-String
if (Test-Path $exe) { & $exe --version } else { Write-Output "endpoint-agent.exe not found" }
'

  for diag in identity winget software hardware services local-users; do
    run_guest_ps "$vm" "$out_file" "diagnose-$diag" "$SECTION_TIMEOUT_SECONDS" "
\$ErrorActionPreference = \"Continue\"
\$exe = \"C:\\Program Files\\EndpointAgent\\endpoint-agent.exe\"
if (Test-Path \$exe) {
  & \$exe diagnose $diag
  Write-Output (\"EXIT=\" + \$LASTEXITCODE)
} else {
  Write-Output \"endpoint-agent.exe not found\"
  Write-Output \"EXIT=127\"
}
"
  done

  if [ "$INCLUDE_WINGET_EGRESS" -eq 1 ]; then
    run_guest_ps "$vm" "$out_file" "diagnose-winget-egress" "$SECTION_TIMEOUT_SECONDS" '
$ErrorActionPreference = "Continue"
$exe = "C:\Program Files\EndpointAgent\endpoint-agent.exe"
if (Test-Path $exe) {
  & $exe diagnose winget-egress
  Write-Output ("EXIT=" + $LASTEXITCODE)
} else {
  Write-Output "endpoint-agent.exe not found"
  Write-Output "EXIT=127"
}
'
  else
    {
      printf '\n=== diagnose-winget-egress ===\n'
      printf 'SKIPPED_BY_DEFAULT use --include-winget-egress to run network/package source probe\n'
      printf 'EXIT=0\n'
    } >>"$out_file"
  fi

  scan_output "$out_file"
  log "wrote $out_file"
done

log "complete"
