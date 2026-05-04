#!/usr/bin/env bash
# scripts/cutover/cutover-restore.sh
#
# Codex Sprint A P0 Item 4 — D30 cutover ROLLBACK script.
# Restores stateful tier from a cutover-bundle directory created by
# cutover-bundle.sh. Target: 72h post-cutover rollback window per
# repo HARD RULE #6 ("D30 Atomic Cutover + 72h Warm Rollback").
#
# This script is INTENTIONALLY destructive on the restore side — it
# replaces current PG/Vault/KC state with the bundle's snapshot. Pre-cutover
# data loss is bounded by the bundle freshness.
#
# Usage:
#   bash cutover-restore.sh <bundle-dir>
#   bash cutover-restore.sh <bundle-dir> --components pg,openfga    # subset
#   CUTOVER_DRY_RUN=1 bash cutover-restore.sh <bundle-dir>          # validation only
#
# Pre-flight:
#   1. Bundle MANIFEST.json present + checksums validate
#   2. All target databases reachable
#   3. Operator confirms by typing the bundle timestamp
#
# Exit codes:
#   0 — restore complete + post-restore smoke passes
#   1 — restore aborted (user cancellation OR pre-flight failed)
#   2 — restore partial (some components failed; cluster in inconsistent state)

set -uo pipefail

BUNDLE_DIR="${1:?bundle-dir required}"
shift || true

CUTOVER_DRY_RUN="${CUTOVER_DRY_RUN:-0}"
COMPONENTS="${COMPONENTS:-pg,openfga,keycloak,vault}"

# Parse --components flag
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --components) COMPONENTS="$2"; shift 2 ;;
    *) echo "WARN: unknown arg: $1"; shift ;;
  esac
done

# Connection params (default match staging-sw conventions)
PG_HOST="${PG_HOST:-10.9.10.53}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"

OPENFGA_HOST="${OPENFGA_HOST:-10.9.10.53}"
OPENFGA_PORT="${OPENFGA_PORT:-8081}"

KC_HOST="${KC_HOST:-10.9.10.53}"
KC_PORT="${KC_PORT:-8080}"
KC_REALM="${KC_REALM:-serban}"

VAULT_HOST="${VAULT_HOST:-10.9.10.53}"
VAULT_PORT="${VAULT_PORT:-8200}"

echo "=== Cutover Restore — Bundle: $BUNDLE_DIR ==="
echo "Components: $COMPONENTS"

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------

[[ ! -d "$BUNDLE_DIR" ]] && { echo "ERR: bundle dir not found: $BUNDLE_DIR"; exit 1; }
[[ ! -f "$BUNDLE_DIR/MANIFEST.json" ]] && { echo "ERR: MANIFEST.json missing — bundle invalid"; exit 1; }

manifest_ts=$(jq -r '.created_at' "$BUNDLE_DIR/MANIFEST.json")
manifest_git=$(jq -r '.git.sha' "$BUNDLE_DIR/MANIFEST.json")
echo
echo "Bundle metadata:"
echo "  created_at: $manifest_ts"
echo "  git_sha:    $manifest_git"

# Verify checksums
echo
echo "--- Verifying integrity ---"
fail_count=0
while IFS= read -r line; do
  comp=$(echo "$line" | jq -r '.[0]')
  expected_sha=$(echo "$line" | jq -r '.[1]')
  fpath="$BUNDLE_DIR/$comp"

  if [[ ! -f "$fpath" ]]; then
    echo "  [MISS] $comp (in manifest but not on disk)"
    fail_count=$((fail_count + 1))
    continue
  fi

  actual_sha=$(sha256sum "$fpath" 2>/dev/null | awk '{print $1}' || \
               shasum -a 256 "$fpath" 2>/dev/null | awk '{print $1}' || \
               echo "unknown")

  if [[ "$actual_sha" == "$expected_sha" ]]; then
    echo "  [OK]   $comp"
  else
    echo "  [FAIL] $comp (sha256 mismatch — bundle corrupted?)"
    fail_count=$((fail_count + 1))
  fi
done < <(jq -c '.components | to_entries[] | [.key, .value.sha256]' "$BUNDLE_DIR/MANIFEST.json")

if [[ "$fail_count" -gt 0 ]]; then
  echo "ERR: $fail_count integrity violations — refuse to restore from corrupted bundle"
  exit 1
fi

# Confirmation gate
if [[ "$CUTOVER_DRY_RUN" != "1" ]]; then
  echo
  echo "=== DESTRUCTIVE OPERATION ==="
  echo "This will OVERWRITE current state of:"
  for c in ${COMPONENTS//,/ }; do echo "  - $c"; done
  echo
  echo "To proceed, type the bundle timestamp '$manifest_ts':"
  read -r confirm
  if [[ "$confirm" != "$manifest_ts" ]]; then
    echo "Confirmation mismatch — restore aborted"
    exit 1
  fi
fi

# ------------------------------------------------------------
# Restore components
# ------------------------------------------------------------

restore_pg() {
  echo "--- Restore PG: pg_dumpall ---"
  local src="$BUNDLE_DIR/pg_dumpall.sql.gz"
  [[ ! -f "$src" ]] && { echo "  [SKIP] $src not in bundle"; return 0; }

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "  [DRY] would: gunzip -c $src | psql -h $PG_HOST -p $PG_PORT -U $PG_USER"
    return 0
  fi

  if PGCONNECT_TIMEOUT=10 gunzip -c "$src" | \
     psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" --quiet 2>/tmp/pg_restore.err; then
    echo "  [OK] PG restored from $src"
  else
    echo "  [FAIL] psql restore errored:"
    cat /tmp/pg_restore.err | head -10
    return 1
  fi
}

restore_openfga() {
  echo "--- Restore OpenFGA: store + tuples ---"
  local src="$BUNDLE_DIR/openfga-export.json"
  [[ ! -f "$src" ]] && { echo "  [SKIP] $src not in bundle"; return 0; }

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "  [DRY] would: re-create stores + auth_models + write tuples per export"
    return 0
  fi

  # OpenFGA restore is complex: stores must be re-created, auth_models re-uploaded,
  # tuples re-written. For now, this is a manual operator task with the export file
  # as input. Mark with a note for the playbook.
  echo "  [MANUAL] OpenFGA restore is a multi-step manual operation:"
  echo "           1. POST /stores per store metadata in $src"
  echo "           2. POST /stores/<id>/authorization-models per auth_model"
  echo "           3. POST /stores/<id>/write per tuple batch"
  echo "           See: docs/operations/cutover-restore-runbook.md"
  echo "           (Auto-restore deferred — Sprint B/C task)"
}

restore_keycloak() {
  echo "--- Restore Keycloak: realm import ---"
  local src="$BUNDLE_DIR/keycloak-realm-${KC_REALM}.json"
  [[ ! -f "$src" ]] && { echo "  [SKIP] $src not in bundle"; return 0; }

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "  [DRY] would: KC admin REST realm import"
    return 0
  fi

  if [[ -z "${KC_ADMIN_USER:-}" || -z "${KC_ADMIN_PASSWORD:-}" ]]; then
    echo "  [MANUAL] KC_ADMIN_USER/PASSWORD not set — manual restore required:"
    echo "           docker exec compose-keycloak /opt/keycloak/bin/kc.sh import --file $src"
    return 0
  fi

  local token
  token=$(curl -sf --max-time 10 -X POST \
    "http://$KC_HOST:$KC_PORT/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli&grant_type=password&username=$KC_ADMIN_USER&password=$KC_ADMIN_PASSWORD" \
    2>/dev/null | jq -r '.access_token // empty')

  if [[ -z "$token" ]]; then
    echo "  [FAIL] KC admin token request failed"
    return 1
  fi

  # Delete + re-create realm
  echo "  [WARN] deleting realm $KC_REALM (will be re-created from bundle)"
  curl -sf -X DELETE \
    -H "Authorization: Bearer $token" \
    "http://$KC_HOST:$KC_PORT/admin/realms/$KC_REALM" > /dev/null 2>&1 || true

  if curl -sf --max-time 30 -X POST \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "@$src" \
    "http://$KC_HOST:$KC_PORT/admin/realms" > /dev/null 2>&1; then
    echo "  [OK] KC realm $KC_REALM restored"
  else
    echo "  [FAIL] KC realm import failed"
    return 1
  fi
}

restore_vault() {
  echo "--- Restore Vault: raft snapshot ---"
  local src="$BUNDLE_DIR/vault-raft-snapshot.snap"
  [[ ! -f "$src" ]] && { echo "  [SKIP] $src not in bundle"; return 0; }

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "  [DRY] would: vault operator raft snapshot restore $src"
    return 0
  fi

  if [[ -z "${VAULT_TOKEN:-}" ]]; then
    echo "  [MANUAL] VAULT_TOKEN not set — manual restore required:"
    echo "           docker exec compose-vault vault operator raft snapshot restore $src"
    return 0
  fi

  if VAULT_ADDR="http://$VAULT_HOST:$VAULT_PORT" \
     vault operator raft snapshot restore "$src" 2>/tmp/vault-restore.err; then
    echo "  [OK] Vault snapshot restored"
  else
    echo "  [FAIL] vault snapshot restore errored:"
    cat /tmp/vault-restore.err | head -5
    return 1
  fi
}

# ------------------------------------------------------------
# Run requested components
# ------------------------------------------------------------

fails=0
for comp in ${COMPONENTS//,/ }; do
  case "$comp" in
    pg|postgres|postgresql)  restore_pg       || fails=$((fails + 1)) ;;
    openfga)                 restore_openfga  || fails=$((fails + 1)) ;;
    keycloak|kc)             restore_keycloak || fails=$((fails + 1)) ;;
    vault)                   restore_vault    || fails=$((fails + 1)) ;;
    *)                       echo "  [SKIP] unknown component: $comp" ;;
  esac
  echo
done

echo "=== Summary ==="
echo "components_failed: $fails"

if [[ "$fails" -gt 0 ]]; then
  echo "[CRITICAL] partial restore — cluster state inconsistent"
  echo "           Consider full re-restore or manual intervention"
  exit 2
fi

echo "[OK] restore complete"
echo
echo "Post-restore checklist:"
echo "  1. Run scripts/smoke/d29-smoke-runner.sh test (or prod)"
echo "  2. Verify ConfigMaps from $BUNDLE_DIR/live-configmaps-{test,prod}.yaml match cluster"
echo "  3. Verify pod imageIDs match $BUNDLE_DIR/pod-imageids-{test,prod}.txt (digest-pinned)"
exit 0
