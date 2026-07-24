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
#   3. Catalog JWT service issuer/JWKS pair present and environment-correct +
#      user-service SERVICE_AUTH_* invariants (Codex 019e1e0f Session 47
#      stabilization follow-up — prevents kcSubject leak recurrence by
#      pinning auth-service-issued service-token verifier endpoints).
#   4. Service catalog parity — both env overlays should declare same service
#      set OR allowlist mismatch in services.yaml (deferred when allowlist
#      file doesn't exist yet)
#   5. Deployment template + probe contract gate (Codex 019e2319 iter-3 AGREE):
#      Spring-actuator backend services must carry startupProbe +
#      /actuator/health/{liveness,readiness} probes; nginx/openfga http-healthz;
#      others exempt. Catches the endpoint-admin /healthz/* skeleton-era drift
#      that caused 16h silent CrashLoopBackOff (2026-05-13).
#
# Exit:
#   0 — clean (PR is mergeable)
#   1 — drift detected (PR should be blocked)

set -uo pipefail

ENV="${1:-prod}"
REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CATALOG_CONTRACT_PYTHON="${CATALOG_CONTRACT_PYTHON:-python3}"
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
[[ ! -d "$OVERLAY" ]] && { echo "ERR: overlay not found: $OVERLAY"; exit 1; }

cd "$REPO_ROOT" || exit 1

EXIT_CODE=0
RENDER=$(kubectl kustomize "$OVERLAY" 2>/dev/null) || {
  echo "[FAIL] kustomize render: $OVERLAY"
  exit 1
}

# Check 1: every first-party GHCR image plus catalog-required image must be pinned.
# Explicit catalog exceptions are environment-scoped legacy debt; Faz 35 uses
# one only to keep the pre-existing PROD OpenFGA desired-state unchanged.
echo "=== Check 1: image digest pin (no moving tags) ==="
moving_tags=$(echo "$RENDER" | grep -E '^[[:space:]]*image:[[:space:]]*ghcr\.io/' | grep -v '@sha256:' || true)
if [[ -n "$moving_tags" ]]; then
  echo "[FAIL] Non-digest image refs found:"
  echo "$moving_tags"
  EXIT_CODE=1
else
  echo "[OK]  All rendered GHCR image refs are @sha256: pinned"
fi

image_contract_rc=0
image_contract_output=$(echo "$RENDER" | PYTHONPATH="$REPO_ROOT/scripts/drift_detection" \
  "$CATALOG_CONTRACT_PYTHON" -c '
import sys, yaml
from lib.catalog_runtime_contracts import image_contract_findings
from lib.services_catalog import ServicesCatalog

catalog = ServicesCatalog.from_yaml(sys.argv[2])
for finding in image_contract_findings(yaml.safe_load_all(sys.stdin), catalog, sys.argv[1]):
    print(f"[FAIL] {finding.message}")
' "$ENV" "$REPO_ROOT/docs/operations/services.yaml" 2>&1) || image_contract_rc=$?
if [[ $image_contract_rc -ne 0 ]]; then
  echo "[FAIL] image_contract_exec_error: catalog image contract could not execute (rc=$image_contract_rc)"
  echo "$image_contract_output"
  EXIT_CODE=1
elif [[ -n "$image_contract_output" ]]; then
  echo "$image_contract_output"
  EXIT_CODE=1
else
  echo "[OK]  Catalog workloads have one immutable primary image"
fi

# Check 2: GHCR manifest existence — real verification via OCI registry API
# (Codex Sprint A P0 Item 4 hardening — was deferred when CI auth wasn't
# yet configured; now uses GITHUB_TOKEN bearer flow to HEAD each manifest)
echo
echo "=== Check 2: GHCR manifest existence ==="
VERIFIER="$REPO_ROOT/scripts/drift-detection/verify_ghcr_manifests.py"
if [[ -x "$VERIFIER" ]]; then
  # Preserve the established non-strict compatibility scan for pre-existing
  # legacy packages whose package-level App grants are not yet reconciled.
  # Network/invocation failure still blocks. New Faz 35 artifacts are checked
  # separately and strictly below.
  check2_output=$(echo "$RENDER" | GHCR_STRICT=false python3 "$VERIFIER" 2>&1)
  check2_rc=$?
  echo "$check2_output"
  if [[ $check2_rc -ne 0 ]]; then
    echo "[FAIL] GHCR verification did not prove every rendered digest (rc=$check2_rc)"
    EXIT_CODE=1
  fi
else
  echo "[FAIL] GHCR verifier missing or not executable: $VERIFIER"
  EXIT_CODE=1
fi

# TEST is authoritative before PROD. Prove every artifact from the exact,
# content-addressed Faz 35 image-set with strict auth/missing/network semantics;
# legacy package access debt cannot dilute this product-slice gate.
if [[ "$ENV" == test ]]; then
  echo
  echo "=== Check 2b: Faz 35 exact image-set existence (strict) ==="
  IMAGE_SET_DIR="$REPO_ROOT/docs/faz-35-evidence/image-set"
  image_set_count=$(find "$IMAGE_SET_DIR" -maxdepth 1 -type f -name '*.json' -print | \
    wc -l | tr -d ' ')
  if [[ "$image_set_count" -ne 1 ]]; then
    echo "[FAIL] expected exactly one content-addressed Faz 35 image-set"
    EXIT_CODE=1
  else
    IMAGE_SET=$(find "$IMAGE_SET_DIR" -maxdepth 1 -type f -name '*.json' -print)
    image_set_name=$(basename "$IMAGE_SET" .json)
    image_set_sha=$(jq -cS . "$IMAGE_SET" | shasum -a 256 | awk '{print $1}')
    faz35_image_count=$(jq -r '.images | length' "$IMAGE_SET")
    faz35_refs=$(jq -r '
      .images[]
      | select(.repository | startswith("ghcr.io/"))
      | "image: \(.repository)@\(.digest)"
    ' "$IMAGE_SET")
    faz35_ref_count=$(printf '%s\n' "$faz35_refs" | sed '/^$/d' | wc -l | tr -d ' ')
    faz35_scanner_valid=$(jq -r '
      if (
        .images.clamav_scanner.repository == "docker.io/clamav/clamav" and
        (.images.clamav_scanner.digest | test("^sha256:[0-9a-f]{64}$")) and
        .images.clamav_scanner.platform == "linux/amd64" and
        .images.clamav_scanner.supply_chain == "digest-pinned-upstream-runtime-verified"
      ) then "true" else "false" end
    ' "$IMAGE_SET")
    if [[ ! "$image_set_name" =~ ^[0-9a-f]{64}$ ]] || \
       [[ "$image_set_sha" != "$image_set_name" ]] || \
       [[ "$faz35_image_count" -ne 4 ]] || \
       [[ "$faz35_ref_count" -ne 3 ]] || \
       [[ "$faz35_scanner_valid" != true ]]; then
      echo "[FAIL] Faz 35 image-set content address or exact cardinality is invalid"
      EXIT_CODE=1
    else
      check2b_output=$(printf '%s\n' "$faz35_refs" | \
        GHCR_STRICT=true python3 "$VERIFIER" 2>&1)
      check2b_rc=$?
      echo "$check2b_output"
      if [[ $check2b_rc -ne 0 ]]; then
        echo "[FAIL] Faz 35 exact image-set was not fully proven (rc=$check2b_rc)"
        EXIT_CODE=1
      else
        echo "[OK]  Faz 35 exact image-set: 3/3 GHCR manifests verified; 1/1 upstream scanner digest contract verified"
      fi
    fi
  fi
fi

# Check 3: ConfigMap invariants for JWT-validating services
# (Codex AGREE retrospective tur — hardening per item "ConfigMap Invariant"):
#   - A supported KEYCLOAK_* or SECURITY_JWT_* issuer/JWKS pair must be present
#   - OVERLAY_MUST_OVERRIDE placeholder must NOT leak into rendered overlay
#   - Issuer must match expected per environment:
#       test  → https://testai.acik.com/realms/platform-test  (or internal http://keycloak:8080/realms/platform-test)
#       prod  → https://ai.acik.com/realms/serban
#   - JWKS path must end with /protocol/openid-connect/certs
echo
echo "=== Check 3: ConfigMap invariants (Codex hardening) ==="
check3_output=$(echo "$RENDER" | python3 -c "
import sys, yaml, re
sys.path.insert(0, '$REPO_ROOT/scripts/drift_detection')
from lib.catalog_runtime_contracts import jwt_config_findings
from lib.services_catalog import ServicesCatalog

ENV = '$ENV'
docs = list(yaml.safe_load_all(sys.stdin))
catalog = ServicesCatalog.from_yaml('$REPO_ROOT/docs/operations/services.yaml')
jwt_findings = jwt_config_findings(docs, catalog, ENV)
fail_count = len(jwt_findings)
for finding in jwt_findings:
    print(f'[FAIL] {finding.message}')
if not jwt_findings:
    print('[OK]  catalog JWT issuer/JWKS invariants satisfied')

# Codex 019e1e0f follow-up — Session 47 stabilization invariant.
# user-service's ServiceTokenAuthenticationFilter uses a SEPARATE
# property chain (security.service-auth.*) from the OIDC JWT decoder
# (security.oauth2.resourceserver.jwt.*). The application.properties
# defaults hardcode unreachable localhost:8081/realms/serban — if
# a future refactor drops the env override in user-service-config,
# Session 47 drift recurs silently (internal service-token endpoint
# 401s, kcSubject leaks back to public DTOs).
#
# Service tokens are minted by auth-service ServiceTokenProvider
# (iss=auth-service, signed with auth-service RSA key, JWKS at
# /oauth2/jwks). Values are environment-agnostic — same in test/prod.
SERVICE_AUTH_EXPECTED_ISSUER = 'auth-service'
SERVICE_AUTH_EXPECTED_JWKS = 'http://auth-service:8088/oauth2/jwks'
SERVICE_AUTH_FORBIDDEN_SUBSTRINGS = ['localhost:8081', 'keycloak:8080', '/realms/']

user_svc_cm = next(
    (d for d in docs
     if isinstance(d, dict) and d.get('kind') == 'ConfigMap'
     and d.get('metadata', {}).get('name') == 'user-service-config'),
    None,
)
if user_svc_cm is not None:
    data = user_svc_cm.get('data') or {}
    sa_issuer = data.get('SERVICE_AUTH_ISSUER', '')
    sa_jwks = data.get('SERVICE_AUTH_JWK_SET_URI', '')

    if not sa_issuer:
        print(f'[FAIL] user-service SERVICE_AUTH_ISSUER missing (Session 47 drift recurrence)')
        fail_count += 1
    elif sa_issuer != SERVICE_AUTH_EXPECTED_ISSUER:
        print(f'[FAIL] user-service SERVICE_AUTH_ISSUER={sa_issuer!r} must equal {SERVICE_AUTH_EXPECTED_ISSUER!r}')
        fail_count += 1
    else:
        for forbidden in SERVICE_AUTH_FORBIDDEN_SUBSTRINGS:
            if forbidden in sa_issuer:
                print(f'[FAIL] user-service SERVICE_AUTH_ISSUER contains forbidden substring {forbidden!r}')
                fail_count += 1
                break

    if not sa_jwks:
        print(f'[FAIL] user-service SERVICE_AUTH_JWK_SET_URI missing (Session 47 drift recurrence)')
        fail_count += 1
    elif sa_jwks != SERVICE_AUTH_EXPECTED_JWKS:
        print(f'[FAIL] user-service SERVICE_AUTH_JWK_SET_URI={sa_jwks!r} must equal {SERVICE_AUTH_EXPECTED_JWKS!r}')
        fail_count += 1
    else:
        for forbidden in SERVICE_AUTH_FORBIDDEN_SUBSTRINGS:
            if forbidden in sa_jwks:
                print(f'[FAIL] user-service SERVICE_AUTH_JWK_SET_URI contains forbidden substring {forbidden!r}')
                fail_count += 1
                break

    if data.get('SERVICE_AUTH_ISSUER') == SERVICE_AUTH_EXPECTED_ISSUER \
            and data.get('SERVICE_AUTH_JWK_SET_URI') == SERVICE_AUTH_EXPECTED_JWKS:
        print(f'[OK]  user-service SERVICE_AUTH_* invariant satisfied')

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

# Check 5: Deployment template + probe contract drift gate
# (Codex 019e2319 iter-3 AGREE — Deployment Contract Drift Gate PR-1)
echo
echo "=== Check 5: Deployment template + probe contract drift ==="
CONTRACT_CLI="$REPO_ROOT/scripts/drift_detection/check_deployment_contracts.py"
if [[ -x "$CONTRACT_CLI" ]]; then
  check5_output=$(python3 "$CONTRACT_CLI" \
    --mode pr-time \
    --env "$ENV" \
    --render-source "$OVERLAY" \
    --catalog "$CATALOG" \
    --output text 2>&1)
  check5_rc=$?
  echo "$check5_output"
  # Codex 019e2327 review #1 — fail-closed semantics. Anything non-zero blocks
  # the PR; warn-on-2 / silent-on-3 disabled.
  if [[ $check5_rc -ne 0 ]]; then
    echo "[FAIL] check_deployment_contracts CLI returned rc=$check5_rc — blocking PR"
    EXIT_CODE=1
  fi
else
  # Gate cannot run = gate broken = fail-closed.
  echo "[FAIL] $CONTRACT_CLI missing or not executable — contract gate cannot run"
  EXIT_CODE=1
fi

echo
echo "=== Summary ==="
echo "exit_code=$EXIT_CODE"
exit $EXIT_CODE
