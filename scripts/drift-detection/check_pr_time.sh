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
#   3. ConfigMap invariants:
#      - KEYCLOAK_ISSUER_URI present for JWT-validating services
#      - user-service SERVICE_AUTH_* points to auth-service, never KC/localhost
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

# Check 2: GHCR manifest existence — real verification via OCI registry API
# (Codex Sprint A P0 Item 4 hardening — was deferred when CI auth wasn't
# yet configured; now uses GITHUB_TOKEN bearer flow to HEAD each manifest)
echo
echo "=== Check 2: GHCR manifest existence ==="
VERIFIER="$REPO_ROOT/scripts/drift-detection/verify_ghcr_manifests.py"
if [[ -x "$VERIFIER" ]]; then
  check2_output=$(echo "$RENDER" | python3 "$VERIFIER" 2>&1)
  check2_rc=$?
  echo "$check2_output"
  if [[ $check2_rc -eq 1 ]]; then
    EXIT_CODE=1
  elif [[ $check2_rc -eq 2 ]]; then
    echo "[WARN] GHCR verification inconclusive (network/auth) — runtime detector remains line of defense"
  fi
else
  total_images=$(echo "$RENDER" | grep -oE 'image:\s*ghcr\.io/[^@]+@sha256:[a-f0-9]+' | sort -u | wc -l | tr -d ' ')
  echo "[INFO] $total_images unique pinned image digests (verifier missing — fallback count-only)"
fi

# Check 3: ConfigMap invariants for JWT-validating services
# (Codex AGREE retrospective tur — hardening per item "ConfigMap Invariant"):
#   - Both KEYCLOAK_ISSUER_URI AND KEYCLOAK_JWKS_URI must be present
#   - OVERLAY_MUST_OVERRIDE placeholder must NOT leak into rendered overlay
#   - Issuer must match expected per environment:
#       test  → https://testai.acik.com/realms/platform-test  (or internal http://keycloak:8080/realms/platform-test)
#       prod  → https://ai.acik.com/realms/serban
#   - JWKS path must end with /protocol/openid-connect/certs
#   - user-service SERVICE_AUTH_* must stay on the auth-service-issued-token
#     verifier contract (Session 47 recurrence guard; Codex 019e1df7 REVISE)
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

SERVICE_AUTH_EXPECTED = {
    'SERVICE_AUTH_ISSUER': 'auth-service',
    'SERVICE_AUTH_JWK_SET_URI': 'http://auth-service:8088/oauth2/jwks',
}
SERVICE_AUTH_FORBIDDEN_SUBSTRINGS = ('localhost:8081', 'keycloak:8080', '/realms/')

user_cm = next(
    (d for d in docs
     if isinstance(d, dict) and d.get('kind') == 'ConfigMap'
     and d.get('metadata', {}).get('name') == 'user-service-config'),
    None,
)
if user_cm is None:
    print(f'[FAIL] user-service-config missing in {ENV} render; cannot verify SERVICE_AUTH_* invariants')
    fail_count += 1
else:
    user_data = user_cm.get('data') or {}
    for key, expected_value in SERVICE_AUTH_EXPECTED.items():
        if key not in user_data:
            print(f'[FAIL] user-service {key} missing from user-service-config in {ENV} render')
            fail_count += 1
            continue

        value = user_data.get(key)
        if value != expected_value:
            print(f'[FAIL] user-service {key}={value!r} must equal {expected_value!r} in {ENV} render')
            fail_count += 1

        for forbidden in SERVICE_AUTH_FORBIDDEN_SUBSTRINGS:
            if forbidden in str(value):
                print(f'[FAIL] user-service {key}={value!r} contains forbidden SERVICE_AUTH drift marker {forbidden!r}')
                fail_count += 1

    if all(user_data.get(key) == expected for key, expected in SERVICE_AUTH_EXPECTED.items()):
        print('[OK]  user-service SERVICE_AUTH_* valid')

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
