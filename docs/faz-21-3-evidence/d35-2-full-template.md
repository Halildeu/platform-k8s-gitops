# D35-2-full — Scoped Grant/Revoke E2E via REST (V25 OUR_COMPANY anchor)

> **Template — kopyala, doldur, `docs/faz-21-3-evidence/<YYYY-MM-DD>-d35-2-full-<run-id>.md` adıyla kaydet.**
>
> Tier semantik: `D35-2-limited` (manuel SQL bypass — PR #218) → `D35-2-full` (REST controller → service → DB → outbox → OpenFGA tam zincir). V25 alignment merge (`platform-backend#17`, `platform-k8s-gitops#221`) sonrası reachable.
>
> Codex thread `019dd409` PARTIAL/AGREE-with-revisions: D35-2-full ayrı tier olarak korunur (D35-3 UI fail olursa REST PASS kanıtı bağımsız durur).

**Tier**: D35-2-full
**Date**: <YYYY-MM-DD UTC>
**Cluster**: k3d-test on staging-sw
**Permission-service image digest**: `sha256:219b053777478fa048fbe04b4f990f477a1091d2e2a49c0691e18c340a5c9406` (sha-943bd5f, V25 alignment)
**Codex thread**: `019dd409` (D35-3 prereq strategy) + `019dd34e` (V25 hybrid contract)
**Operator**: <agent-name veya operatör adı; D35-2/D35-3 operatör authority gerektirir per ADR-0010 §2.5>
**Migration chain applied**: V16 → V17 → V19 → V20 → V21 → V22 → V23 → V25 → V26
**Upstream evidence**:
- `docs/faz-21-3-evidence/2026-04-28-d35-1-scope-anchor-load-d93e9917.md` (D35-1 PASS)
- `docs/faz-21-3-evidence/2026-04-28-d35-2-first-canli-eventual-consistency.md` (D35-2-limited PASS — REST bypass)

## What this evidence proves

**REST flow eventual-consistency tam zinciri (V25-aligned, staging-sw canlı)**:

1. Keycloak admin JWT → `Authorization: Bearer` ile `POST /api/v1/access/scope`
2. Controller → AccessScopeService.grant → V25 trigger PASS (scope_kind=company + scope_source_table=OUR_COMPANY)
3. `data_access.scope` row (V25 contract: scope_ref=`["1"]`, source_table=`OUR_COMPANY`)
4. Aynı TX içinde `data_access.scope_outbox` row PENDING (V23 typed columns)
5. OutboxPoller PENDING → PROCESSED (≤8s, attempt=1, last_error=NULL)
6. OpenFGA `/check` ALLOW: `company:wc-our-company-1` (V25 namespace) için granted user
7. OpenFGA `/check` DENY: aynı obje, başka user (D29 third-level synthetic deny)
8. `DELETE /api/v1/access/scope/{id}` → REVOKE outbox PROCESSED
9. Originally-granted user `/check` → DENY (allow → deny FLIP)
10. 10-dakikalık pencerede 0 FAILED outbox row

D35-2-limited'in **manual SQL INSERT bypass** caveat'ı kalkar; controller layer + service + encoder zinciri V25 contract altında canlı doğrulanır.

## What this does NOT cover

- **D35-3 ürün-path UI persona kanıtı**: bu evidence backend REST'i; D35-3 mfe-access UI ekranlarından aynı zinciri yürütür.
- **Production cluster (k3d-prod)**: bu evidence test cluster only; prod cutover D30 atomic karar bekliyor (CLAUDE.md HARD RULE #6).

## Prereq'ler (bu run'dan ÖNCE doğrulanmış olmalı)

- [ ] **Permission-service digest match**: pod imageID == `sha256:219b053777478fa048fbe04b4f990f477a1091d2e2a49c0691e18c340a5c9406`
- [ ] **Hibernate validate V25/V26 schema PASS** (boot log: `Initialized JPA EntityManagerFactory for persistence unit 'reportsDb'`)
- [ ] **`module:ACCESS#can_manage` tuple seed** (admin UID için): `docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md` runbook'u koştu, `/check allowed=true` doğrulandı
- [ ] **Keycloak admin user + JWT**: `docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md` runbook'u ile JWT alındı, env'e konuldu (`JWT_ADMIN`)
- [ ] **`workcube_mikrolink.our_company`** + **`data_access.organization_company`** seeded (D35-1 PASS sonrası canlı)

## Setup (operatör tek seferlik)

```bash
RUN_ID="d35-2-full-$(date +%Y%m%d-%H%M)"
USER_UID_GRANTED="<receive-scope user UUID>"
USER_UID_DENIED="<negative-assertion user UUID>"
ORG_ID=1                        # AÇIK
SCOPE_KIND="COMPANY"             # case-insensitive at controller; ScopeKind.COMPANY enum
SCOPE_REF='["1"]'                # V25 canonical: OUR_COMPANY.COMP_ID=1
EXPECTED_TUPLE_OBJECT="company:wc-our-company-1"
GRANT_USER="user:${USER_UID_GRANTED}"
JWT_ADMIN="<from RB-faz-21-3-d35-3-keycloak-admin-jwt.md>"
API_BASE="https://testai.acik.com"

# OpenFGA store/model
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

mkdir -p docs/faz-21-3-evidence
EVIDENCE="docs/faz-21-3-evidence/2026-XX-XX-d35-2-full-${RUN_ID}.md"
echo "# D35-2-full evidence — ${RUN_ID}" > ${EVIDENCE}
echo "Started: $(date -Iseconds)" >> ${EVIDENCE}
```

## Step 9.1 — Image digest match

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'"
```

**Operator gate**: `sha256:219b053777478fa048fbe04b4f990f477a1091d2e2a49c0691e18c340a5c9406` ile birebir.

## Step 9.2 — REPORTS_DB_ENABLED + ERP_OPENFGA_ENABLED env

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/permission-service -- env | \
  grep -E 'REPORTS_DB_(ENABLED|URL|USERNAME)|ERP_OPENFGA_ENABLED'"
```

**Gate**: `REPORTS_DB_ENABLED=true`, `ERP_OPENFGA_ENABLED=true`, URL/USERNAME populated (PASSWORD redact edilir).

## Step 9.3 — HikariPool-2 + OutboxPoller boot

```bash
ssh halil@staging-sw "POD=\$(kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].metadata.name}') && \
  kubectl --context k3d-test -n platform-test logs \$POD --tail=200 | \
  grep -E 'HikariPool-(1|2) - Start completed|EntityManagerFactory.*reportsDb|Started PermissionService'"
```

**Gate**: `HikariPool-2 - Start completed.` + `Initialized JPA EntityManagerFactory for persistence unit 'reportsDb'` + `Started PermissionServiceApplication`.

## Step 9.4 — POST /api/v1/access/scope → 201

```bash
GRANT_RESPONSE=$(curl -s -X POST "${API_BASE}/api/v1/access/scope" \
  -H "Authorization: Bearer ${JWT_ADMIN}" \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "userId": "${USER_UID_GRANTED}",
  "orgId": ${ORG_ID},
  "scopeKind": "${SCOPE_KIND}",
  "scopeRef": "${SCOPE_REF}"
}
EOF
)
echo "${GRANT_RESPONSE}" | tee -a "${EVIDENCE}"

SCOPE_ID=$(echo "${GRANT_RESPONSE}" | jq -r .scopeId)
OUTBOX_ID=$(echo "${GRANT_RESPONSE}" | jq -r .outboxId)
INITIAL_SYNC=$(echo "${GRANT_RESPONSE}" | jq -r .tupleSyncStatus)
OPENFGA_OBJ_ID=$(echo "${GRANT_RESPONSE}" | jq -r .openFgaObjectId)
echo "scope_id=${SCOPE_ID} outbox_id=${OUTBOX_ID} initial=${INITIAL_SYNC} fga_obj_id=${OPENFGA_OBJ_ID}" | tee -a "${EVIDENCE}"
```

**Gate**:
- HTTP 201
- `scopeId` numeric, `outboxId` numeric
- `tupleSyncStatus="PENDING"`, `processedAt=null`
- `openFgaObjectId="wc-our-company-1"` (V25 namespace, kritik V19→V25 drift testi)
- `openFgaObjectType="company"`

## Step 9.5 — `data_access.scope` row visible (V25 contract)

```bash
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, user_id, org_id, scope_kind, scope_source_table, scope_ref, granted_at, revoked_at \
    FROM data_access.scope WHERE id = ${SCOPE_ID};\"" | tee -a "${EVIDENCE}"
```

**Gate**:
- 1 row, `revoked_at=NULL`
- `scope_kind=company`
- `scope_source_table=OUR_COMPANY` (V25 contract — `COMPANY` görürsen drift, V25 CHECK rejected etmemiş demek)
- `scope_ref='["1"]'` (canonical JSON)

## Step 9.6 — `data_access.scope_outbox` PENDING (V23 typed columns + V25 namespace)

```bash
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, scope_id, action, status, attempt_count, \
           tuple_user, tuple_relation, tuple_object, \
           next_attempt_at, locked_by, locked_until, processed_at, last_error \
    FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};\"" | tee -a "${EVIDENCE}"
```

**Gate**:
- `status` PENDING (veya PROCESSING/PROCESSED — poller çabuksa)
- `tuple_user='user:${USER_UID_GRANTED}'`
- `tuple_relation='viewer'`
- `tuple_object='company:wc-our-company-1'` (V25 namespace; `wc-company-1001` görürsen encoder drift = ŞIDDETLI bug)
- `last_error=NULL`

## Step 9.7 — Outbox PROCESSED (eventual consistency assertion ≤8s)

```bash
for i in $(seq 1 4); do
  STATUS=$(ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -t -c \
    \"SELECT status FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};\"" | xargs)
  echo "  attempt ${i}: status=${STATUS}" | tee -a "${EVIDENCE}"
  if [ "${STATUS}" = "PROCESSED" ]; then break; fi
  sleep 5
done

ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, status, processed_at, attempt_count \
    FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};\"" | tee -a "${EVIDENCE}"
```

**Gate**: status=`PROCESSED`, processed_at non-null, attempt_count≥1, ≤30s wall-clock.

## Step 9.8 — OpenFGA /check ALLOW (granted user, V25 obje)

```bash
curl -sf -X POST "http://${OPENFGA_URL}/stores/${STORE_ID}/check" \
  -H 'Content-Type: application/json' \
  -d "{
    \"authorization_model_id\": \"${MODEL_ID}\",
    \"tuple_key\": {
      \"user\": \"${GRANT_USER}\",
      \"relation\": \"viewer\",
      \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
    }
  }" | tee -a "${EVIDENCE}"
```

**Gate**: `{"allowed": true, "resolution": ""}`.

## Step 9.9 — OpenFGA /check DENY (negative user)

```bash
curl -sf -X POST "http://${OPENFGA_URL}/stores/${STORE_ID}/check" \
  -H 'Content-Type: application/json' \
  -d "{
    \"authorization_model_id\": \"${MODEL_ID}\",
    \"tuple_key\": {
      \"user\": \"user:${USER_UID_DENIED}\",
      \"relation\": \"viewer\",
      \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
    }
  }" | tee -a "${EVIDENCE}"
```

**Gate**: `{"allowed": false}`.

## Step 9.10 — REVOKE → allow→deny FLIP

```bash
HTTP_CODE=$(curl -s -X DELETE "${API_BASE}/api/v1/access/scope/${SCOPE_ID}" \
  -H "Authorization: Bearer ${JWT_ADMIN}" \
  -w '%{http_code}\n' -o /dev/null)
echo "DELETE response: ${HTTP_CODE}" | tee -a "${EVIDENCE}"

# REVOKE outbox visible
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, scope_id, action, status, tuple_user, tuple_object \
    FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} ORDER BY id;\"" | tee -a "${EVIDENCE}"

# Wait REVOKE PROCESSED
for i in $(seq 1 4); do
  STATUS=$(ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -t -c \
    \"SELECT status FROM data_access.scope_outbox \
       WHERE scope_id = ${SCOPE_ID} AND action='REVOKE' \
       ORDER BY id DESC LIMIT 1;\"" | xargs)
  echo "  revoke poll ${i}: status=${STATUS}" | tee -a "${EVIDENCE}"
  if [ "${STATUS}" = "PROCESSED" ]; then break; fi
  sleep 5
done

# Allow flip
curl -sf -X POST "http://${OPENFGA_URL}/stores/${STORE_ID}/check" \
  -H 'Content-Type: application/json' \
  -d "{
    \"authorization_model_id\": \"${MODEL_ID}\",
    \"tuple_key\": {
      \"user\": \"${GRANT_USER}\",
      \"relation\": \"viewer\",
      \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
    }
  }" | tee -a "${EVIDENCE}"
```

**Gate**:
- HTTP 204 from DELETE
- 2 outbox rows: GRANT (PROCESSED) + REVOKE (eventual PROCESSED)
- Originally-granted user **`{"allowed": false}`** (FLIP confirmed)

## Step 9.11 — Zero FAILED rows (10-min window)

```bash
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT count(*) AS failed_count \
    FROM data_access.scope_outbox \
    WHERE status = 'FAILED' AND created_at >= now() - INTERVAL '10 minutes';\"" | tee -a "${EVIDENCE}"
```

**Gate**: `failed_count: 0`.

## Per ADR-0009 11-step canonical sequence

| Step | Açıklama | Status |
|------|----------|--------|
| 1 | Image digest match (`sha256:219b05...`) | ✓/✗ |
| 2 | REPORTS_DB_ENABLED + datasource env | ✓/✗ |
| 3 | HikariPool-2 + OutboxPoller boot | ✓/✗ |
| 4 | POST grant → 201 + scopeId + outboxId + V25 obje (`wc-our-company-1`) | ✓/✗ |
| 5 | data_access.scope row (V25 contract: `OUR_COMPANY`/`["1"]`) | ✓/✗ |
| 6 | scope_outbox PENDING + V23 typed columns + V25 tuple | ✓/✗ |
| 7 | Outbox PROCESSED ≤8s | ✓/✗ |
| 8 | OpenFGA /check ALLOW granted user | ✓/✗ |
| 9 | OpenFGA /check DENY negative user | ✓/✗ |
| 10 | REVOKE → allow→deny FLIP | ✓/✗ |
| 11 | 0 FAILED rows | ✓/✗ |

## Verdict

**Tier verdict**: PASS | FAIL | PARTIAL

**Failure modes** (eğer var): step + sebep

**Limitations**: D35-3 ürün-path (UI persona) bu kanıtta YOK. mfe-access ekran flow'u D35-3 ayrı kanıt dosyasına gider.

**Next**:
- D35-2-full PASS → D35-3 UI persona evidence (`d35-3-product-path-template.md` üzerinden)
- D35 ladder kapsamı: 4/4 tier kapanır → Faz 21.3 D35 ladder closure

Completed: <UTC ISO timestamp>

## References

- ADR-0008 § "Object id encoding" (V25 transition map: `wc-company-` → `wc-our-company-`)
- ADR-0009 § D35 Evidence Ladder
- ADR-0010 §2.3 (D35 ladder authority), §2.5 (operator/agent matrix)
- ADR-0011 §2.3 (cross-repo boundary)
- D35-2-limited (manuel SQL bypass; supersededed by this tier): `docs/faz-21-3-evidence/2026-04-28-d35-2-first-canli-eventual-consistency.md`
- D35-3 product path template: `docs/faz-21-3-evidence/d35-3-product-path-template.md`
- Prereq runbooks:
  - `docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md` (module:ACCESS seed)
  - `docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md` (operatör auth)
- REST runner script: `scripts/d35-3/rest-grant-runner.sh`
- Codex threads: `019dd34e` (V25 hybrid), `019dd3dc` (Option B' AGREE), `019dd409` (D35-3 prereq strategy)
