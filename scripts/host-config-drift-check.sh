#!/usr/bin/env bash
# Host config drift check — is what git says actually what the host runs?
#
# Files under host-compose/ have no reconciler; they are deployed by hand. This
# script compares each canonical file against its live counterpart (see
# host-compose/deployed-paths.manifest) and exits non-zero when they differ.
#
# Runs on the staging-sw self-hosted runner, where the live paths are local.
# Read-only: it never writes to a live path.
#
# Exit codes: 0 = every pair in sync · 1 = drift or missing live file
#
# Faz 24 Bulgu 3-E: PR #2711 merged the audio-gateway WebSocket Upgrade fix into
# host-compose/web-nginx/default.conf, but the host was never updated. Git and
# CI both showed "fixed" while the live edge kept dropping the header. This
# check makes that gap visible instead of silent.

set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MANIFEST="${MANIFEST:-$REPO_ROOT/host-compose/deployed-paths.manifest}"

drift=0
checked=0
missing=0

if [ ! -f "$MANIFEST" ]; then
  printf 'FAIL: manifest not found: %s\n' "$MANIFEST" >&2
  exit 1
fi

printf '=== host config drift check ===\n'
printf 'manifest: %s\n\n' "$MANIFEST"

while IFS=$'\t' read -r canonical live; do
  # Skip comments and blank lines.
  case "${canonical// /}" in ''|\#*) continue ;; esac
  [ -n "${live:-}" ] || {
    printf 'FAIL: manifest line missing live path for %s\n' "$canonical" >&2
    drift=1
    continue
  }

  canonical_abs="$REPO_ROOT/$canonical"
  checked=$((checked + 1))

  if [ ! -f "$canonical_abs" ]; then
    printf 'FAIL  %s\n      canonical file missing in repo\n' "$canonical" >&2
    drift=1
    continue
  fi

  if [ ! -f "$live" ]; then
    # Not drift in the "diverged" sense, but the deploy target is absent, which
    # is just as broken and must not pass silently.
    printf 'FAIL  %s\n      live file not found: %s\n' "$canonical" "$live" >&2
    missing=$((missing + 1))
    drift=1
    continue
  fi

  if diff -q "$canonical_abs" "$live" >/dev/null 2>&1; then
    printf 'OK    %s\n' "$canonical"
  else
    added=$(diff "$canonical_abs" "$live" | grep -c '^>' || true)
    removed=$(diff "$canonical_abs" "$live" | grep -c '^<' || true)
    printf 'DRIFT %s\n      live: %s\n      %s line(s) only in git, %s line(s) only on host\n' \
      "$canonical" "$live" "$removed" "$added" >&2
    printf '      --- unified diff (git → live) ---\n' >&2
    diff -u "$canonical_abs" "$live" | sed 's/^/      /' >&2
    drift=1
  fi
done < "$MANIFEST"

printf '\n=== summary ===\n'
printf 'checked: %s\n' "$checked"

if [ "$drift" -eq 0 ]; then
  printf 'result:  IN SYNC — every canonical file matches what the host runs\n'
  exit 0
fi

printf 'result:  DRIFT DETECTED\n' >&2
printf '\nTo reconcile, decide which side is right:\n' >&2
printf '  git is right  → scp <canonical> staging-sw:<live path>, then reload the service\n' >&2
printf '  host is right → copy the live file back into the repo and open a PR\n' >&2
printf '\nNever assume a merged PR reached the host; that assumption is Bulgu 3-E.\n' >&2
exit 1
