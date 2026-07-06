#!/usr/bin/env bash
# DEPRECATED — renamed to check_env_drift.sh (ADR-0023 Guardrail PR-4, 2026-05-20).
#
# This stub forwards to the new name with prod-default arg for backward
# compatibility with installed systemd timers + external callers. Will be
# removed after 2026-06-20 (one release cycle).
#
# To migrate: replace `check_prod_drift.sh [args]` with
# `check_env_drift.sh prod [args]` (or `test [args]` for test cluster).

echo "[DEPRECATED] check_prod_drift.sh — use check_env_drift.sh instead (ADR-0023 PR-4); removal: 2026-06-20" >&2

if [[ $# -eq 0 ]]; then
  set -- prod
fi

exec "$(dirname "$0")/check_env_drift.sh" "$@"
