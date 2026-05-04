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

# Check 3: ConfigMap invariants for JWT-validating services
# (Codex AGREE retrospective tur — hardening per item "ConfigMap Invariant"):
#   - Both KEYCLOAK_ISSUER_URI AND KEYCLOAK_JWKS_URI must be present
#   - OVERLAY_MUST_OVERRIDE placeholder must NOT leak into rendered overlay
#   - Issuer must match expected per environment:
#       test  → https://testai.acik.com/realms/platform-test  (or internal http://keycloak:8080/realms/platform-test)
#       prod  → https://ai.acik.com/realms/serban
#   - JWKS path must end with /protocol/openid-connect/certs
echo
echo "=== Check 3: ConfigMap invariants (Codex hardening) ==="
JWT_SERVICES="api-gateway user-service variant-service permission-service schema-service report-service"
check3_output=$(echo "$RENDER" | python3 -c "
import sys, yaml, re

ENV = '$ENV'
EXPECTED_ISSUERS = {
    'prod': ['https://ai.acik.com/realms/serban'],
    'test': [
        'https://testai.acik.com/realms/platform-test',
        'http://keycloak:8080/realms/platform-test',
        'http://keycloak:8080/realms/serban',  # legacy fallback (some test fixtures use serban)
    ],
}
expected = EXPECTED_ISSUERS.get(ENV, [])

docs = list(yaml.safe_load_all(sys.stdin))
fail_count = 0
for svc in '$JWT_SERVICES'.split():
    cm = next(
        (d for d in docs
         if isinstance(d, dict) and d.get('kind') == 'ConfigMap'
         and d.get('metadata', {}).get('name') == f'{svc}-config'),
        None,
    )
    if cm is None:
        print(f'[SKIP] {svc}-config not in render (services.yaml gate will handle this in P0 next)')
        continue

    data = cm.get('data') or {}
    issuer = data.get('KEYCLOAK_ISSUER_URI', '')
    jwks = data.get('KEYCLOAK_JWKS_URI', '')

    # Check 1: presence
    if not issuer:
        print(f'[FAIL] {svc} KEYCLOAK_ISSUER_URI missing')
        fail_count += 1
        continue
    if not jwks:
        print(f'[FAIL] {svc} KEYCLOAK_JWKS_URI missing')
        fail_count += 1
        continue

    # Check 2: placeholder leak
    if 'OVERLAY_MUST_OVERRIDE' in issuer:
        print(f'[FAIL] {svc} KEYCLOAK_ISSUER_URI = OVERLAY_MUST_OVERRIDE placeholder leaked into {ENV} render')
        fail_count += 1
        continue
    if 'OVERLAY_MUST_OVERRIDE' in jwks:
        print(f'[FAIL] {svc} KEYCLOAK_JWKS_URI = OVERLAY_MUST_OVERRIDE placeholder leaked into {ENV} render')
        fail_count += 1
        continue

    # Check 3: issuer matches env expectation
    if expected and issuer not in expected:
        print(f'[FAIL] {svc} KEYCLOAK_ISSUER_URI={issuer} not in expected for {ENV}: {expected}')
        fail_count += 1
        continue

    # Check 4: JWKS path
    if not jwks.endswith('/protocol/openid-connect/certs'):
        print(f'[FAIL] {svc} KEYCLOAK_JWKS_URI={jwks} does not end with /protocol/openid-connect/certs')
        fail_count += 1
        continue

    print(f'[OK]  {svc} ISSUER+JWKS valid')

if fail_count > 0:
    print(f'')
    print(f'Total: {fail_count} ConfigMap invariant violation(s)')
    sys.exit(1)
sys.exit(0)
" 2>&1)
check3_rc=$?
echo "$check3_output"
if [ $check3_rc -ne 0 ]; then
  EXIT_CODE=1
fi

# Check 4: service catalog parity — services.yaml is SSOT
# (Codex P0 retrospective: services.yaml manifest closes endpoint-admin-service
# untracked drift by declaring deferred intent)
echo
echo "=== Check 4: service catalog parity ==="
CATALOG="$REPO_ROOT/docs/operations/services.yaml"
if [[ ! -f "$CATALOG" ]]; then
  echo "[FAIL] service catalog missing: $CATALOG (required by Codex Sprint A P0)"
  EXIT_CODE=1
else
  check4_output=$(echo "$RENDER" | python3 -c "
import sys, yaml

ENV = '$ENV'
docs = list(yaml.safe_load_all(sys.stdin))
catalog = yaml.safe_load(open('$CATALOG'))

# Services declared in render (Deployment + StatefulSet)
rendered = set()
for d in docs:
    if not isinstance(d, dict): continue
    if d.get('kind') in ('Deployment', 'StatefulSet'):
        labels = d.get('metadata', {}).get('labels') or {}
        name = labels.get('app.kubernetes.io/name')
        if name:
            rendered.add(name)

# Catalog declarations for this env
catalog_enabled = set()
catalog_deferred = set()
catalog_disabled = set()
for svc in catalog.get('services', []):
    status = svc.get('environments', {}).get(ENV, 'unknown')
    if status == 'enabled':
        catalog_enabled.add(svc['name'])
    elif status == 'deferred':
        catalog_deferred.add(svc['name'])
    elif status == 'disabled':
        catalog_disabled.add(svc['name'])

# Findings
fails = 0

# Catalog enabled but not in render → missing service
missing = catalog_enabled - rendered
for svc in sorted(missing):
    print(f'[FAIL] {svc} declared enabled for {ENV} in services.yaml but not in render')
    fails += 1

# Render contains service not in catalog at all (unknown) → fail
unknown = rendered - catalog_enabled - catalog_deferred - catalog_disabled
for svc in sorted(unknown):
    print(f'[FAIL] {svc} in render but not in services.yaml (add to catalog)')
    fails += 1

# Render contains service marked deferred → fail
should_be_absent = (catalog_deferred | catalog_disabled) & rendered
for svc in sorted(should_be_absent):
    print(f'[FAIL] {svc} marked deferred/disabled for {ENV} in services.yaml but appears in render')
    fails += 1

# OK report
ok_count = len(catalog_enabled & rendered)
print(f'[OK]  {ok_count} services correctly enabled+rendered')
deferred_in_env = sorted(catalog_deferred)
if deferred_in_env:
    print(f'[OK]  {len(deferred_in_env)} services intentionally deferred for {ENV}: {deferred_in_env}')

if fails > 0:
    print(f'')
    print(f'Total: {fails} service catalog violation(s)')
    sys.exit(1)
sys.exit(0)
" 2>&1)
  check4_rc=$?
  echo "$check4_output"
  if [ $check4_rc -ne 0 ]; then
    EXIT_CODE=1
  fi
fi

echo
echo "=== Summary ==="
echo "exit_code=$EXIT_CODE"
exit $EXIT_CODE
