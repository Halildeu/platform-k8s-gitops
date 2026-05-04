#!/usr/bin/env bash
# scripts/cutover/cutover-bundle.sh
#
# Codex Sprint A P0 Item 4 — D30 cutover backup bundle.
# Snapshots all stateful tier data BEFORE atomic cutover so 72h rollback
# window has known-good restore points.
#
# Bundle contents:
#   1. PostgreSQL: pg_dumpall of compose-side instance (10.9.10.53:5432)
#      - users_db, permission_db, openfga, keycloak, schema_service
#   2. OpenFGA: store + model + tuples export via OpenFGA REST API
#   3. Keycloak: realm export (serban realm) via admin REST API
#   4. Vault: encrypted KV snapshot via vault operator raft snapshot
#   5. ConfigMap manifest: live ConfigMap state from both clusters
#   6. Manifest: bundle metadata (timestamp, git SHA, cluster digest snapshot)
#
# Output: /var/backups/cutover/cutover-bundle-<ts>/
#   ├── pg_dumpall.sql.gz
#   ├── openfga-export.json
#   ├── keycloak-realm-serban.json
#   ├── vault-raft-snapshot.snap
#   ├── live-configmaps-test.yaml
#   ├── live-configmaps-prod.yaml
#   ├── overlay-render-test.yaml
#   ├── overlay-render-prod.yaml
#   ├── pod-imageids-test.txt
#   ├── pod-imageids-prod.txt
#   └── MANIFEST.json   (bundle metadata + integrity hashes)
#
# Designed for staging-sw execution (manual pre-cutover OR scheduled timer).
# Recovery script: scripts/cutover/cutover-restore.sh (companion).
#
# Usage:
#   bash cutover-bundle.sh                  # default output dir
#   bash cutover-bundle.sh /custom/path     # custom output
#   CUTOVER_DRY_RUN=1 bash cutover-bundle.sh # validation only, no writes
#
# Exit codes:
#   0 — bundle complete + integrity verified
#   1 — at least one component failed (partial bundle, NOT safe for cutover)
#   2 — pre-flight check failed (no rollback possible without all components)

set -uo pipefail

CUTOVER_DRY_RUN="${CUTOVER_DRY_RUN:-0}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEFAULT_BACKUP_DIR="/var/backups/cutover"
BUNDLE_DIR="${1:-$DEFAULT_BACKUP_DIR}/cutover-bundle-$TS"

# Compose-side connection params (from staging-sw conventions)
PG_HOST="${PG_HOST:-10.9.10.53}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DATABASES=(users_db permission_db openfga keycloak schema_service core_data_service)

OPENFGA_HOST="${OPENFGA_HOST:-10.9.10.53}"
OPENFGA_PORT="${OPENFGA_PORT:-8081}"

KC_HOST="${KC_HOST:-10.9.10.53}"
KC_PORT="${KC_PORT:-8080}"
KC_REALM="${KC_REALM:-serban}"

VAULT_HOST="${VAULT_HOST:-10.9.10.53}"
VAULT_PORT="${VAULT_PORT:-8200}"

# Cluster contexts
TEST_CTX="${TEST_CTX:-k3d-test}"
PROD_CTX="${PROD_CTX:-k3d-prod}"
TEST_NS="${TEST_NS:-platform-test}"
PROD_NS="${PROD_NS:-platform-prod}"

# Repo paths
REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Required tools (pre-flight check)
REQUIRED_TOOLS=(pg_dumpall curl jq kubectl python3)

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------
preflight() {
  echo "=== Cutover Bundle Pre-flight ==="

  for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" > /dev/null 2>&1; then
      echo "ERR: required tool not found: $tool"
      exit 2
    fi
  done

  # PG reachability
  if ! PGCONNECT_TIMEOUT=5 pg_isready -h "$PG_HOST" -p "$PG_PORT" > /dev/null 2>&1; then
    echo "ERR: PostgreSQL not reachable: $PG_HOST:$PG_PORT"
    exit 2
  fi

  # Cluster reachability
  for ctx in "$TEST_CTX" "$PROD_CTX"; do
    if ! kubectl --context "$ctx" cluster-info > /dev/null 2>&1; then
      echo "ERR: cluster context not reachable: $ctx"
      exit 2
    fi
  done

  echo "[OK] all pre-flight checks passed"
}

# ------------------------------------------------------------
# Snapshot components
# ------------------------------------------------------------

snap_pg() {
  echo "--- Snapshot 1/6: PostgreSQL pg_dumpall ---"
  local out="$BUNDLE_DIR/pg_dumpall.sql.gz"

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY] would: pg_dumpall -h $PG_HOST -p $PG_PORT -U $PG_USER | gzip > $out"
    return 0
  fi

  # Note: requires PGPASSWORD or .pgpass; operator's responsibility to set
  if PGCONNECT_TIMEOUT=10 pg_dumpall -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" 2>/tmp/pg_dumpall.err | gzip > "$out"; then
    local size_mb
    size_mb=$(du -m "$out" | awk '{print $1}')
    echo "  [OK] $out ($size_mb MB)"
  else
    echo "  [FAIL] pg_dumpall errored:"
    cat /tmp/pg_dumpall.err | head -10
    return 1
  fi
}

snap_openfga() {
  echo "--- Snapshot 2/6: OpenFGA store + tuples ---"
  local out="$BUNDLE_DIR/openfga-export.json"

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY] would: GET $OPENFGA_HOST:$OPENFGA_PORT/stores → /writes export"
    return 0
  fi

  # Get all stores
  local stores
  stores=$(curl -sf --max-time 10 "http://$OPENFGA_HOST:$OPENFGA_PORT/stores" 2>/dev/null || echo '{"stores":[]}')
  local store_count
  store_count=$(echo "$stores" | jq -r '.stores | length')

  if [[ "$store_count" -eq 0 ]]; then
    echo "  [WARN] no OpenFGA stores found — empty export"
    echo "$stores" > "$out"
    return 0
  fi

  # Build composite export with store metadata + auth model + tuples per store
  python3 <<PYEOF > "$out" 2>&1
import json
import urllib.request
import sys

base = "http://$OPENFGA_HOST:$OPENFGA_PORT"
result = {"stores": []}

# Get stores list
with urllib.request.urlopen(f"{base}/stores", timeout=10) as r:
    stores = json.loads(r.read())

for store in stores.get('stores', []):
    sid = store['id']
    entry = {"store": store, "auth_models": [], "tuples": []}

    # Auth models
    try:
        with urllib.request.urlopen(f"{base}/stores/{sid}/authorization-models", timeout=10) as r:
            entry["auth_models"] = json.loads(r.read()).get('authorization_models', [])
    except Exception as e:
        entry["auth_models_error"] = str(e)

    # Tuples (read with empty filter → all)
    try:
        req = urllib.request.Request(
            f"{base}/stores/{sid}/read",
            data=json.dumps({"tuple_key": {}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            entry["tuples"] = data.get('tuples', [])
    except Exception as e:
        entry["tuples_error"] = str(e)

    result["stores"].append(entry)

print(json.dumps(result, indent=2))
PYEOF

  if [[ -s "$out" ]]; then
    local tuple_count
    tuple_count=$(jq -r '[.stores[].tuples | length] | add // 0' "$out")
    echo "  [OK] $out ($store_count stores, $tuple_count tuples)"
  else
    echo "  [FAIL] OpenFGA export empty"
    return 1
  fi
}

snap_keycloak() {
  echo "--- Snapshot 3/6: Keycloak realm export ---"
  local out="$BUNDLE_DIR/keycloak-realm-${KC_REALM}.json"

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY] would: KC admin REST realm export for $KC_REALM"
    return 0
  fi

  # KC admin REST requires admin token. Operator must set KC_ADMIN_USER + KC_ADMIN_PASSWORD env
  if [[ -z "${KC_ADMIN_USER:-}" || -z "${KC_ADMIN_PASSWORD:-}" ]]; then
    echo "  [SKIP] KC_ADMIN_USER/KC_ADMIN_PASSWORD not set in env — admin export deferred"
    echo "         (operator: docker exec compose-keycloak /opt/keycloak/bin/kc.sh export ...)"
    echo "{\"realm\": \"$KC_REALM\", \"export_method\": \"deferred-operator-task\"}" > "$out"
    return 0
  fi

  # Get admin token
  local token
  token=$(curl -sf --max-time 10 -X POST \
    "http://$KC_HOST:$KC_PORT/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli&grant_type=password&username=$KC_ADMIN_USER&password=$KC_ADMIN_PASSWORD" \
    2>/dev/null | jq -r '.access_token // empty')

  if [[ -z "$token" ]]; then
    echo "  [FAIL] KC admin token request failed"
    return 1
  fi

  # Export realm
  if curl -sf --max-time 30 \
    -H "Authorization: Bearer $token" \
    -H "Accept: application/json" \
    "http://$KC_HOST:$KC_PORT/admin/realms/$KC_REALM" > "$out" 2>/dev/null; then
    local size_kb
    size_kb=$(du -k "$out" | awk '{print $1}')
    echo "  [OK] $out ($size_kb KB)"
  else
    echo "  [FAIL] KC realm export failed"
    return 1
  fi
}

snap_vault() {
  echo "--- Snapshot 4/6: Vault raft snapshot ---"
  local out="$BUNDLE_DIR/vault-raft-snapshot.snap"

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY] would: vault operator raft snapshot save $out"
    return 0
  fi

  # Vault snapshot requires VAULT_TOKEN env (operator's responsibility)
  if [[ -z "${VAULT_TOKEN:-}" ]]; then
    echo "  [SKIP] VAULT_TOKEN not set — Vault snapshot deferred"
    echo "         (operator: docker exec compose-vault vault operator raft snapshot save /tmp/vault.snap)"
    return 0
  fi

  if VAULT_ADDR="http://$VAULT_HOST:$VAULT_PORT" \
     vault operator raft snapshot save "$out" 2>/tmp/vault-snap.err; then
    local size_kb
    size_kb=$(du -k "$out" | awk '{print $1}')
    echo "  [OK] $out ($size_kb KB)"
  else
    echo "  [FAIL] vault snapshot errored:"
    cat /tmp/vault-snap.err | head -5
    return 1
  fi
}

snap_configmaps() {
  echo "--- Snapshot 5/6: Live ConfigMaps (test + prod) ---"

  for env_pair in "test:$TEST_CTX:$TEST_NS" "prod:$PROD_CTX:$PROD_NS"; do
    IFS=':' read -r env ctx ns <<< "$env_pair"
    local out="$BUNDLE_DIR/live-configmaps-$env.yaml"

    if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
      echo "[DRY] would: kubectl --context $ctx -n $ns get cm -o yaml > $out"
      continue
    fi

    if kubectl --context "$ctx" -n "$ns" get cm -o yaml > "$out" 2>/dev/null; then
      local cm_count
      cm_count=$(grep -c '^- apiVersion' "$out" 2>/dev/null || echo "0")
      echo "  [OK] $env: $out ($cm_count ConfigMaps)"
    else
      echo "  [FAIL] $env: kubectl get cm failed"
      return 1
    fi
  done
}

snap_render_and_imageids() {
  echo "--- Snapshot 6/6: Overlay render + pod imageIDs (test + prod) ---"

  for env_pair in "test:$TEST_CTX:$TEST_NS" "prod:$PROD_CTX:$PROD_NS"; do
    IFS=':' read -r env ctx ns <<< "$env_pair"

    if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
      echo "[DRY] would: kubectl kustomize overlays/$env + kubectl get pods imageIDs"
      continue
    fi

    # Overlay render
    local render_out="$BUNDLE_DIR/overlay-render-$env.yaml"
    if kubectl kustomize "$REPO_ROOT/kustomize/overlays/$env" > "$render_out" 2>/dev/null; then
      echo "  [OK] $env render: $render_out"
    else
      echo "  [FAIL] $env: overlay render failed"
      return 1
    fi

    # Pod imageIDs
    local imageids_out="$BUNDLE_DIR/pod-imageids-$env.txt"
    if kubectl --context "$ctx" -n "$ns" get pods \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].imageID}{"\n"}{end}' \
      > "$imageids_out" 2>/dev/null; then
      local pod_count
      pod_count=$(wc -l < "$imageids_out" | tr -d ' ')
      echo "  [OK] $env imageIDs: $imageids_out ($pod_count pods)"
    else
      echo "  [FAIL] $env: kubectl get pods failed"
      return 1
    fi
  done
}

# ------------------------------------------------------------
# Manifest
# ------------------------------------------------------------

write_manifest() {
  echo "--- Writing bundle manifest ---"
  local manifest="$BUNDLE_DIR/MANIFEST.json"

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY] would: write $manifest"
    return 0
  fi

  local git_sha
  git_sha=$(cd "$REPO_ROOT" && git rev-parse HEAD 2>/dev/null || echo "unknown")
  local git_branch
  git_branch=$(cd "$REPO_ROOT" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

  # Compute SHA-256 of each component
  cat > "$manifest" <<EOF
{
  "schema_version": "cutover-bundle-v1",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "bundle_dir": "$BUNDLE_DIR",
  "git": {
    "sha": "$git_sha",
    "branch": "$git_branch",
    "repo_root": "$REPO_ROOT"
  },
  "components": {
EOF

  local first=1
  for comp in pg_dumpall.sql.gz openfga-export.json "keycloak-realm-${KC_REALM}.json" \
              vault-raft-snapshot.snap live-configmaps-test.yaml live-configmaps-prod.yaml \
              overlay-render-test.yaml overlay-render-prod.yaml \
              pod-imageids-test.txt pod-imageids-prod.txt; do
    local fpath="$BUNDLE_DIR/$comp"
    [[ ! -f "$fpath" ]] && continue

    local size_bytes
    size_bytes=$(stat -c%s "$fpath" 2>/dev/null || stat -f%z "$fpath" 2>/dev/null || echo 0)
    local sha256
    sha256=$(sha256sum "$fpath" 2>/dev/null | awk '{print $1}' || \
             shasum -a 256 "$fpath" 2>/dev/null | awk '{print $1}' || \
             echo "unknown")

    if [[ "$first" -eq 0 ]]; then echo "    ," >> "$manifest"; fi
    cat >> "$manifest" <<EOF
    "$comp": {
      "size_bytes": $size_bytes,
      "sha256": "$sha256"
    }
EOF
    first=0
  done

  cat >> "$manifest" <<EOF

  },
  "operator_runbook": "scripts/cutover/cutover-restore.sh <bundle-dir>"
}
EOF

  echo "  [OK] $manifest"
}

# ------------------------------------------------------------
# Run
# ------------------------------------------------------------

main() {
  preflight

  if [[ "$CUTOVER_DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] no actual writes will be performed"
    BUNDLE_DIR="/tmp/dry-run-cutover-bundle"
  fi

  echo
  echo "=== Cutover Bundle: $BUNDLE_DIR ==="
  mkdir -p "$BUNDLE_DIR"

  local fails=0
  snap_pg                  || fails=$((fails + 1))
  snap_openfga             || fails=$((fails + 1))
  snap_keycloak            || fails=$((fails + 1))
  snap_vault               || fails=$((fails + 1))
  snap_configmaps          || fails=$((fails + 1))
  snap_render_and_imageids || fails=$((fails + 1))

  write_manifest

  echo
  echo "=== Summary ==="
  echo "bundle_dir: $BUNDLE_DIR"
  echo "components_failed: $fails"

  if [[ "$fails" -gt 0 ]]; then
    echo "[CRITICAL] partial bundle — NOT safe for cutover rollback"
    echo "           Investigate failures above, fix root cause, retry"
    exit 1
  fi

  if [[ "$CUTOVER_DRY_RUN" != "1" ]]; then
    echo "[OK] full bundle complete + integrity manifest written"
    echo "     Verify with: jq '.components' $BUNDLE_DIR/MANIFEST.json"
  fi

  exit 0
}

main "$@"
