#!/usr/bin/env bash
# Faz 22.2.A / #1044 — local Parallels A1 linked-clone batch helper.
#
# Purpose:
#   Prepare the two additional A1 workgroup/standalone Windows lab devices
#   needed by #1044 without guessing or mutating the running parent VM.
#
# Safety contract:
#   - Default is dry-run.
#   - This script NEVER stops/suspends the parent VM.
#   - This script NEVER deletes/unregisters VMs.
#   - In --execute mode, parent VM must already be stopped/suspended; if it is
#     running/busy, the script fails closed and prints the maintenance-window
#     action for the operator.
#   - A linked clone is only a device candidate. It becomes evidence only after
#     unique hostname, fresh enrollment, A1 classification, non-destructive
#     command smoke, and soak evidence.
#
# Usage:
#   bash scripts/faz22-non-domain/a1-linked-clone-batch.sh
#   bash scripts/faz22-non-domain/a1-linked-clone-batch.sh --execute
#   bash scripts/faz22-non-domain/a1-linked-clone-batch.sh \
#     --parent "Windows 11" \
#     --clone NONDOMAIN-W11-LAB-01 \
#     --clone NONDOMAIN-W11-LAB-02 \
#     --execute

set -euo pipefail

PARENT_VM="Windows 11"
CLONES=("NONDOMAIN-W11-LAB-01" "NONDOMAIN-W11-LAB-02")
EXECUTE=0
MIN_FREE_GIB=10

usage() {
  sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log() {
  printf '[faz22-a1-linked-clone] %s\n' "$*"
}

die() {
  printf '[faz22-a1-linked-clone] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage 0
      ;;
    --parent)
      PARENT_VM="${2:-}"
      [ -n "$PARENT_VM" ] || die "--parent requires a non-empty VM name"
      shift 2
      ;;
    --clone)
      [ -n "${2:-}" ] || die "--clone requires a non-empty VM name"
      if [ "${#CLONES[@]}" -eq 2 ] && [ "${CLONES[0]}" = "NONDOMAIN-W11-LAB-01" ] && [ "${CLONES[1]}" = "NONDOMAIN-W11-LAB-02" ]; then
        CLONES=()
      fi
      CLONES+=("$2")
      shift 2
      ;;
    --execute)
      EXECUTE=1
      shift
      ;;
    --dry-run)
      EXECUTE=0
      shift
      ;;
    --min-free-gib)
      MIN_FREE_GIB="${2:-}"
      [[ "$MIN_FREE_GIB" =~ ^[0-9]+$ ]] || die "--min-free-gib must be an integer"
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

[ "${#CLONES[@]}" -gt 0 ] || die "at least one --clone name is required"

require_cmd prlctl
require_cmd awk
require_cmd df
require_cmd du

vm_exists() {
  prlctl status "$1" >/dev/null 2>&1
}

vm_status() {
  prlctl status "$1" 2>/dev/null | awk '{print $NF}' | tail -1
}

parent_home() {
  prlctl list -i "$PARENT_VM" | awk -F': ' '/^Home: / { print $2; exit }'
}

free_gib_data_volume() {
  df -k /System/Volumes/Data | awk 'NR==2 { printf "%.0f", $4 / 1024 / 1024 }'
}

snapshot_count() {
  prlctl snapshot-list "$PARENT_VM" | awk 'NR > 1 && NF > 0 { count++ } END { print count + 0 }'
}

print_summary() {
  local home="$1"
  local free_gib="$2"
  local status="$3"
  local snaps="$4"

  log "parent_vm=$PARENT_VM"
  log "parent_status=$status"
  log "parent_home=$home"
  if [ -d "$home" ]; then
    log "parent_size=$(du -sh "$home" | awk '{print $1}')"
  else
    log "parent_size=unknown (home path not found)"
  fi
  log "host_free_gib=$free_gib"
  log "snapshot_count=$snaps"
  log "mode=$([ "$EXECUTE" -eq 1 ] && printf execute || printf dry-run)"
  log "clone_names=${CLONES[*]}"
}

log "preflight start"
vm_exists "$PARENT_VM" || die "parent VM not found: $PARENT_VM"

PARENT_STATUS="$(vm_status "$PARENT_VM")"
PARENT_HOME="$(parent_home)"
FREE_GIB="$(free_gib_data_volume)"
SNAPSHOTS="$(snapshot_count)"

print_summary "$PARENT_HOME" "$FREE_GIB" "$PARENT_STATUS" "$SNAPSHOTS"

if [ "$FREE_GIB" -lt "$MIN_FREE_GIB" ]; then
  die "host free space ${FREE_GIB}GiB is below minimum ${MIN_FREE_GIB}GiB for linked-clone batch"
fi

for clone in "${CLONES[@]}"; do
  case "$clone" in
    *$'\n'*|*"	"*|"")
      die "invalid clone name: $clone"
      ;;
  esac
  if vm_exists "$clone"; then
    die "clone target already exists: $clone"
  fi
done

if [ "$PARENT_STATUS" = "running" ]; then
  log "parent VM is running; linked clone creation requires a maintenance window"
  log "operator action: gracefully stop or suspend '$PARENT_VM' from Parallels GUI, then rerun with --execute"
  if [ "$EXECUTE" -eq 1 ]; then
    die "refusing to clone while parent VM is running"
  fi
fi

if [ "$EXECUTE" -eq 0 ]; then
  log "dry-run complete; no VM, snapshot, or disk mutation performed"
  exit 0
fi

if [ "$PARENT_STATUS" = "running" ]; then
  die "internal guard: parent running reached execute path"
fi

for clone in "${CLONES[@]}"; do
  log "creating linked clone: parent='$PARENT_VM' clone='$clone'"
  prlctl clone "$PARENT_VM" --linked --name "$clone"
done

log "post-create VM list:"
prlctl list -a
log "linked-clone batch created; personalize each clone before treating it as evidence"
