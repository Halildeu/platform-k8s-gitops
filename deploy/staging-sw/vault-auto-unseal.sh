#!/bin/bash
# Vault auto-unseal — runs after vault container starts.
#
# Source-of-truth: platform-k8s-gitops/deploy/staging-sw/vault-auto-unseal.sh
# Runtime path (staging-sw): /home/halil/platform/scripts/vault-auto-unseal.sh
#                             (symlink to this file via the host clone at
#                              /home/halil/platform-k8s-gitops/)
# Invoked by: cron @reboot (see ../README.md for the two-line contract).
#
# Preflight (added 2026-07-06 after state/vault stale-swapped-init incident):
#   Before feeding any shard, the script asserts that the key SOURCE share-count
#   matches the LIVE vault Total Shares (`vault status -format=json | .n`).
#   Mismatch -> refuse to feed and exit 1 (was: always exit 0 -> silent-fail).
#
# Env knobs:
#   VAULT_CONTAINER (REQUIRED)  container running vault
#                               (e.g. platform-vault-test, platform-vault-prod).
#                               The stale default `platform-vault-1` was removed
#                               2026-07-06 during host-deploy consolidation —
#                               empty invocation now fails loud instead of
#                               silently trying a container that doesn't exist.
#   KEYS_DIR        (default: /home/halil/platform/state/vault) bare-key dir
#   INIT_FILE       (optional)  path to a canonical vault-init-*.json to source
#                               shards from (canonical:
#                               ~/bootstrap-drill/vault-init-{test,prod}.json).
#                               When set, shards come from .unseal_keys_b64;
#                               KEYS_DIR is ignored.

VAULT_CONTAINER="${VAULT_CONTAINER:?VAULT_CONTAINER env var required (e.g. platform-vault-test or platform-vault-prod)}"
KEYS_DIR="${KEYS_DIR:-/home/halil/platform/state/vault}"
INIT_FILE="${INIT_FILE:-}"

log() { echo "[$(date)] vault-auto-unseal: $*"; }

log "starting... container=$VAULT_CONTAINER init_file=${INIT_FILE:-<bare-keys>} keys_dir=$KEYS_DIR"

# Wait for vault container (max 60s)
for i in $(seq 1 20); do
  docker exec "$VAULT_CONTAINER" vault status >/dev/null 2>&1
  rc=$?
  [ "$rc" -eq 0 ] && { log "already unsealed"; exit 0; }
  [ "$rc" -eq 2 ] && break  # sealed but running
  sleep 3
done

# --- Preflight: share-count match ------------------------------------------
status_json="$(docker exec "$VAULT_CONTAINER" vault status -format=json 2>/dev/null)"
live_total="$(echo "$status_json" | jq -r '.n // empty' 2>/dev/null)"
if [ -z "$live_total" ]; then
  log "PREFLIGHT FAIL: cannot read live Total Shares from '$VAULT_CONTAINER' (container up? vault reachable?); refusing to feed"
  exit 1
fi

if [ -n "$INIT_FILE" ]; then
  if [ ! -r "$INIT_FILE" ]; then
    log "PREFLIGHT FAIL: INIT_FILE '$INIT_FILE' not readable; refusing to feed"
    exit 1
  fi
  src_count="$(jq -r '.unseal_keys_b64 | length' "$INIT_FILE" 2>/dev/null)"
  src_desc="INIT_FILE=$INIT_FILE"
else
  src_count="$(ls -1 "${KEYS_DIR}"/vault-unseal-key-* 2>/dev/null | wc -l | tr -d ' ')"
  src_desc="bare-keys in $KEYS_DIR (vault-unseal-key-*)"
fi

if [ -z "$src_count" ] || [ "$src_count" -eq 0 ] 2>/dev/null; then
  log "PREFLIGHT FAIL: no shards found in source ($src_desc); refusing to feed"
  exit 1
fi

if [ "$src_count" != "$live_total" ]; then
  log "PREFLIGHT FAIL: share-count mismatch — source=$src_count ($src_desc) vs live Total Shares=$live_total; refusing to feed."
  log "  Canonical init files: ~/bootstrap-drill/vault-init-test.json (3/2) or vault-init-prod.json (5/3)."
  log "  See /home/halil/platform/state/vault/README.md for the 2026-07-06 stale-swapped incident."
  exit 1
fi
log "preflight OK: source share-count $src_count == live Total Shares $live_total"

# --- Unseal ----------------------------------------------------------------
log "unsealing..."
if [ -n "$INIT_FILE" ]; then
  # Feed shards from JSON init file.
  jq -r '.unseal_keys_b64[]' "$INIT_FILE" | while read -r key; do
    [ -n "$key" ] || continue
    docker exec "$VAULT_CONTAINER" vault operator unseal "$key" >/dev/null 2>&1 || true
  done
else
  for key_file in "${KEYS_DIR}"/vault-unseal-key-*; do
    [ -f "$key_file" ] || continue
    docker exec "$VAULT_CONTAINER" vault operator unseal "$(cat "$key_file" | tr -d '[:space:]')" >/dev/null 2>&1 || true
  done
fi

docker exec "$VAULT_CONTAINER" vault status >/dev/null 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
  log "SUCCESS"
  exit 0
else
  log "FAILED (rc=$rc)"
  # Preflight passed but unseal still failed -> propagate non-zero so the caller can react.
  exit "$rc"
fi
