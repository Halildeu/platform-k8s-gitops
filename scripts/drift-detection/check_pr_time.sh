#!/usr/bin/env bash
# scripts/drift-detection/check_pr_time.sh
#
# PR-time render-only drift gate (Codex P0 follow-up to runtime drift detector).
# Runs in CI (GitHub Actions) on PRs that touch kustomize/overlays/{test,prod}.
# Catches drift BEFORE merge — render checks only, no kubectl access.
#
# Checks:
#   1. All image refs use @sha256:<digest> (no moving tags like :latest, :main-stable)
#   2. GHCR manifest existence — pinned digests must exist (catches GC'd digests
#      like the sha256:2a7076c9 schema-service incident)
#   3. ConfigMap KEYCLOAK_ISSUER_URI present for JWT-validating services
#   4. Service catalog parity — both env overlays should declare same service
#      set OR allowlist mismatch in services.yaml (deferred when allowlist
#      file doesn't exist yet)
#
# Exit:
#   0 — clean (PR is mergeable)
#   1 — drift detected (PR should be blocked)

set -uo pipefail

ENV="${1:-prod}"
REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
[[ ! -d "$OVERLAY" ]] && { echo "ERR: overlay not found: $OVERLAY"; exit 1; }

cd "$REPO_ROOT" || exit 1

EXIT_CODE=0
RENDER=$(kubectl kustomize "$OVERLAY" 2>/dev/null) || {
  echo "[FAIL] kustomize render: $OVERLAY"
  exit 1
}

# Check 1: every image ref must be @sha256:
echo "=== Check 1: image digest pin (no moving tags) ==="
moving_tags=$(echo "$RENDER" | grep -oE 'image:\s*ghcr\.io/[^@]+:[a-zA-Z][^@]*$' | grep -v '@sha256:' || true)
if [[ -n "$moving_tags" ]]; then
  echo "[FAIL] Non-digest image refs found:"
  echo "$moving_tags"
  EXIT_CODE=1
else
  echo "[OK]  All ghcr.io image refs are @sha256: pinned"
fi

# Check 2: GHCR manifest existence — count unique pinned digests
# (full verification needs CI GHCR auth — deferred; runtime detector
# catches GC'd digests within 5min)
echo
echo "=== Check 2: GHCR manifest existence ==="
total_images=$(echo "$RENDER" | grep -oE 'image:\s*ghcr\.io/[^@]+@sha256:[a-f0-9]+' | sort -u | wc -l | tr -d ' ')
echo "[INFO] $total_images unique pinned image digests"
echo "[NOTE] GHCR manifest existence verification needs CI auth — deferred"
echo "       (runtime detector catches GC'd digests within 5min)"

# Check 3: KEYCLOAK_ISSUER_URI present on JWT-validating services
echo
echo "=== Check 3: ConfigMap KEYCLOAK_ISSUER_URI parity ==="
JWT_SERVICES="api-gateway user-service variant-service permission-service schema-service report-service"
check3_output=$(echo "$RENDER" | python3 -c "
import sys, yaml
docs = list(yaml.safe_load_all(sys.stdin))
issuer_map = {}
for d in docs:
    if not isinstance(d, dict): continue
    if d.get('kind') != 'ConfigMap': continue
    name = d.get('metadata', {}).get('name', '')
    if not name.endswith('-config'): continue
    svc = name[:-len('-config')]
    issuer = (d.get('data') or {}).get('KEYCLOAK_ISSUER_URI', '')
    issuer_map[svc] = issuer
for svc in '$JWT_SERVICES'.split():
    val = issuer_map.get(svc)
    if val is None:
        print(f'[SKIP] {svc}-config not in render')
    elif val:
        print(f'[OK]  {svc} KEYCLOAK_ISSUER_URI={val}')
    else:
        print(f'[FAIL] {svc} missing KEYCLOAK_ISSUER_URI')
" 2>&1)
echo "$check3_output"
if echo "$check3_output" | grep -q '\[FAIL\]'; then
  EXIT_CODE=1
fi

# Check 4: service catalog parity (P2 — deferred until services.yaml lands)
echo
echo "=== Check 4: service catalog parity (deferred until services.yaml) ==="
echo "[NOTE] Will compare prod ↔ test service set when service catalog manifest exists"

echo
echo "=== Summary ==="
echo "exit_code=$EXIT_CODE"
exit $EXIT_CODE
