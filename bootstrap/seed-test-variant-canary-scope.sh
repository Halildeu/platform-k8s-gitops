#!/usr/bin/env bash
# DEPRECATED — DEAD CODE. Fail-closed since board #2534 (Faz 22, 2026-07-22).
#
# ## Why this cannot work
#
# This helper seeds permission_db `public.scopes` + `public.user_permission_scope`.
# Those tables are NOT read on any live cluster:
#
#   1. `kustomize/base/apps/permission-service/configmap.yaml:51` sets
#      ERP_OPENFGA_ENABLED: "true".
#   2. That wires the `openFgaScopeReader` bean
#      (`OpenFgaAuthzConfig`, @ConditionalOnProperty erp.openfga.enabled).
#   3. `AuthorizationQueryService.getUserScopeSummary()` early-returns inside
#      `if (openFgaScopeReader != null) { ... return groupedByType; }` — the
#      `userPermissionScopeRepository` branch below it is UNREACHABLE.
#
# So the seed reported success, the rows landed in Postgres, and
# `/authz/me.allowedScopes` stayed empty. A tool that prints OK while changing
# nothing observable is worse than no tool: it consumed debugging time and
# produced false "scope granted" claims in acceptance notes.
#
# Two further defects, independent of the above:
#   * USER_ID defaults to the platform NUMERIC id (2) while the live subject is
#     a Keycloak UUID — the two identity spaces are not interchangeable (#2530).
#   * The closing instructions tell the operator to `kubectl rollout restart`
#     a Deployment on the shared k3d-test cluster, which ADR-0023 forbids
#     (imperative mutation of GitOps-owned desired state; it also disrupts other
#     sessions sharing the cluster).
#
# ## What to use instead
#
# Grant a data-access scope through the PRODUCT path, which writes the
# ADR-0008 canonical tuple and is the same path a real admin uses:
#
#     POST /api/v1/access/scope
#     {"userId":"<kc-uuid>","orgId":1,"scopeKind":"PROJECT",
#      "scopeRef":"[\"1204\"]","grantedBy":"<kc-uuid>"}
#
# `scopeRef` is a JSON ARRAY STRING; a bare "1204" is rejected 400
# ScopeReferenceInvalid (#2555 Slice B). A ready-made idempotent wrapper with
# --check / --apply / --dispose lives at:
#
#     scripts/acceptance/grant-data-access-scope.sh
#
# Direct DB or direct OpenFGA seeding does NOT count as evidence that the
# supported product path works (#2534 decision). Acceptance must traverse the
# product API.
#
# ## Status
#
# Retained (not deleted) so the runbooks and evidence notes that cite this path
# still resolve to an explanation rather than a 404. The original body is kept
# verbatim below the guard for audit; it is unreachable.

set -euo pipefail

cat >&2 <<'DEPRECATION'
[seed-test-variant-canary-scope] REFUSING TO RUN — this helper is dead code.

  It writes permission_db public.scopes / public.user_permission_scope, but
  ERP_OPENFGA_ENABLED=true on every live overlay, so
  AuthorizationQueryService.getUserScopeSummary() reads OpenFGA and never
  reaches the DB branch. The seed would report success and change nothing
  observable.

  Use the product path instead:
      scripts/acceptance/grant-data-access-scope.sh --apply ...
  which calls POST /api/v1/access/scope.

  Details + proof chain: board #2534, and the header of this file.
DEPRECATION
exit 2

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT-ONLY: original implementation, unreachable. Do not re-enable without
# first proving the DB branch is read (it is not — see header).
# ─────────────────────────────────────────────────────────────────────────────
if false; then
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-platform-pg-test}"
DB_NAME="${DB_NAME:-permission_db}"
DB_USER="${DB_USER:-platform}"
SCOPE_TYPE="${SCOPE_TYPE:-PROJECT}"
GRID_REF_ID="${GRID_REF_ID:-1204}"
USER_ID="${USER_ID:-2}"
PERMISSION_CODE="${PERMISSION_CODE:-VARIANTS_READ}"
DESCRIPTION="${DESCRIPTION:-codex synthetic allow scope}"

if [[ "${SCOPE_TYPE}" != "PROJECT" ]]; then
  echo "ERROR: Bu helper yalnız PROJECT scope seed'i için tasarlandı."
  echo "Verilen SCOPE_TYPE='${SCOPE_TYPE}'"
  exit 1
fi

if [[ ! "${GRID_REF_ID}" =~ ^[0-9]+$ || ! "${USER_ID}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: GRID_REF_ID ve USER_ID numerik olmalı."
  echo "GRID_REF_ID='${GRID_REF_ID}' USER_ID='${USER_ID}'"
  exit 1
fi

if [[ ! "${PERMISSION_CODE}" =~ ^[A-Z0-9_]+$ ]]; then
  echo "ERROR: PERMISSION_CODE yalnız A-Z, 0-9 ve _ içerebilir."
  echo "PERMISSION_CODE='${PERMISSION_CODE}'"
  exit 1
fi

if [[ "${DESCRIPTION}" == *"'"* ]]; then
  echo "ERROR: DESCRIPTION tek tırnak içeremez."
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${DB_CONTAINER}"; then
  echo "ERROR: Beklenen container bulunamadı: ${DB_CONTAINER}"
  echo "Önce test stateful PG ayağa kaldırılmalı."
  exit 1
fi

PERMISSION_ID="$(
  docker exec "${DB_CONTAINER}" psql -At -U "${DB_USER}" -d "${DB_NAME}" \
    -c "select id from public.permissions where code='${PERMISSION_CODE}' limit 1;"
)"

if [[ -z "${PERMISSION_ID}" ]]; then
  echo "ERROR: permission_db içinde permission code bulunamadı: ${PERMISSION_CODE}"
  exit 1
fi

echo "=== Variant Canary Scope Seed ==="
echo "Container       : ${DB_CONTAINER}"
echo "DB              : ${DB_NAME}"
echo "User            : ${DB_USER}"
echo "Scope type/ref  : ${SCOPE_TYPE}/${GRID_REF_ID}"
echo "Permission code : ${PERMISSION_CODE} (id=${PERMISSION_ID})"
echo "User id         : ${USER_ID}"
echo

docker exec -i "${DB_CONTAINER}" psql -v ON_ERROR_STOP=1 -U "${DB_USER}" -d "${DB_NAME}" <<SQL
INSERT INTO public.scopes (scope_type, ref_id, description)
SELECT '${SCOPE_TYPE}', ${GRID_REF_ID}, '${DESCRIPTION}'
WHERE NOT EXISTS (
  SELECT 1
  FROM public.scopes
  WHERE scope_type='${SCOPE_TYPE}' AND ref_id=${GRID_REF_ID}
);

INSERT INTO public.user_permission_scope (user_id, permission_id, scope_id)
SELECT ${USER_ID}, ${PERMISSION_ID}, s.id
FROM public.scopes s
WHERE s.scope_type='${SCOPE_TYPE}'
  AND s.ref_id=${GRID_REF_ID}
  AND NOT EXISTS (
    SELECT 1
    FROM public.user_permission_scope ups
    WHERE ups.user_id=${USER_ID}
      AND ups.permission_id=${PERMISSION_ID}
      AND ups.scope_id=s.id
  );
SQL

echo
echo "--- Verification ---"
docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
  -c "select id, scope_type, ref_id, description from public.scopes where scope_type='${SCOPE_TYPE}' and ref_id=${GRID_REF_ID};"

docker exec "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
  -c "select ups.id, ups.user_id, p.code as permission_code, ups.scope_id from public.user_permission_scope ups join public.permissions p on p.id=ups.permission_id where ups.user_id=${USER_ID} and p.code='${PERMISSION_CODE}' order by ups.id;"

cat <<EOF

NEXT:
1. Variant authz cache'i için restart:
   kubectl --context k3d-test -n platform-test rollout restart deploy/variant-service
   kubectl --context k3d-test -n platform-test rollout status deploy/variant-service --timeout=180s

2. Internal authz doğrula:
   kubectl --context k3d-test -n platform-test exec deploy/variant-service -- \\
     sh -lc "curl -s -H 'Authorization: Bearer <TOKEN>' http://permission-service:8090/api/v1/authz/me"

3. Canonical allow smoke:
   curl -sk -H "Authorization: Bearer <TOKEN>" \\
     "https://testai.acik.com/api/v1/variants?gridId=${GRID_REF_ID}"
   # Beklenen: 200 (boş liste kabul)

4. Out-of-scope deny:
   curl -sk -H "Authorization: Bearer <TOKEN>" \\
     "https://testai.acik.com/api/v1/variants?gridId=test-grid"
   # Beklenen: 403
EOF

fi
