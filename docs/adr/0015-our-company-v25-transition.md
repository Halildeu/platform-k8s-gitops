# ADR-0015 — OUR_COMPANY Anchor Table + V25 Transition

> **Status**: Accepted (post-fact, 2026-05-14) | **Owner**: Platform-Eng | **Plan ref**: `docs/plan-reporting-refactor-2026-05-14.md` §7 Adım 7
> **Supersedes**: pre-V25 `COMPANY` directory-based tenant anchor pattern
> **Related**: ADR-0008 Multi-Org Explicit-Scope Zanzibar | Codex thread `019dd34e` (V25 hybrid + REVISE-with-revisions absorb) | V25/V26 Flyway migrations

---

## 1. Context

Pre-V25 platform-backend tenant boundary anchor table was `COMPANY` (Workcube `workcube_mikrolink.dbo.COMPANY` directory): ~80k row global company catalog used for both display lookup AND tenant boundary identification. OpenFGA tuple format: `company:wc-company-<COMP_ID>`.

**Problem identified (Codex `019dd34e` Session 32 discovery, 2026-04-28)**: `COMPANY` is a **directory** of all companies known to Workcube installations — not a tenant boundary. Single-tenant deployment (this platform's pre-prod state) needs a separate `OUR_COMPANY` table identifying which company IDs the deployment is authoritative for.

Symptoms:
- `permission-service` PR-G follow-up `sha-4f408f4` carried `company:wc-company-1001` tuple references that conflicted with single-tenant deployment scope
- D35-2-limited evidence (PR #218) revealed `expectedSourceTable(COMPANY)` semantic mismatch — V25 should map to `OUR_COMPANY` for tenant boundary, `COMPANY` for display
- FGA namespace drift: `wc-company-` prefix in 6 finance reports' tenant predicates

## 2. Decision

Introduce `OUR_COMPANY` anchor table (~42 rows, explicit tenant boundary) and split semantic responsibility:

| Concern | Pre-V25 | Post-V25 |
|---|---|---|
| Tenant boundary identification | `COMPANY` directory (80k rows) | **`OUR_COMPANY`** (42 rows, this deployment) |
| Display lookup (company name → label) | `COMPANY` | `COMPANY` (preserved) |
| OpenFGA namespace prefix | `wc-company-<id>` | **`wc-our-company-<id>`** |
| Tenant predicate signature | `(org_id INT)` | `(org_id BIGINT)` (signature widen for future tenant scaling) |
| RLS scope source | `COMPANY` row filter | **`OUR_COMPANY` row filter** |

### V25 Migration (Flyway V25/V26)

- `V25__our_company_anchor.sql`: CREATE `OUR_COMPANY` table + populate with this deployment's owned company IDs + tenant predicate `(org_id BIGINT)` signature widen
- `V26__source_pk_dual_format.sql`: Source PK dual-format (ETL JSON canonical vs jsonb extraction) — outbox payload `tuple={user, relation, objectType, objectId}` with `wc-our-company-` namespace
- Backend code (`platform-backend#17` sha-`943bd5f`): `expectedSourceTable(COMPANY)→OUR_COMPANY` + encoder `COMPANY case wc-our-company-<COMP_ID>`

### Cross-Cutting Code Changes (V25 Transition)

| Component | Change |
|---|---|
| `permission-service` | `wc-company-` → `wc-our-company-` OpenFGA tuple namespace (PR-G follow-up sha-`4f408f4` → `943bd5f`) |
| `report-service` | `RowFilterInjector` tenant column allowlist references `OUR_COMPANY` for scoped reports |
| `OpenFGA model contract` | `organization:default | admin | user:1201` (super-admin) + `company:wc-our-company-<id> | viewer | user:<numericId>` (scoped) |
| Fixtures (Testcontainers + 11-step runbook) | V90 fixture rewritten with `OUR_COMPANY` anchor; 5 unit-test files retargeted; 3 new V25/V26 contract tests; V25/V26 SQL copied to test classpath |

## 3. Consequences

### Positive

- **Tenant boundary explicit**: deployment-scope (42 OUR_COMPANY rows) clearly separated from world-scope (80k COMPANY directory). No accidental cross-tenant data exposure via display-lookup path.
- **OpenFGA contract aligned**: `wc-our-company-<id>` namespace eliminates ambiguity in scoped permission tuples (super-admin `organization:default | admin` vs scoped `company:wc-our-company-<id> | viewer`).
- **D35-2 ladder unblocked**: post-V25 evidence (`platform-k8s-gitops#218` D35-2-limited canlı kanıt; PR #225 D35-2-full REST flow) verified live on staging-sw `k3d-test` 2026-04-28.
- **Future tenant scaling**: `BIGINT` org_id signature widen accommodates ≥4-billion-row scaling without later migration overhead.
- **Drift detection coverage**: ADR-0011 DD-1 V25/V26 anchor migration check guards against regression.

### Negative

- **Backward compatibility break (intentional)**: pre-V25 OpenFGA tuples (`wc-company-`) NOT auto-migrated; existing test fixtures + integration tests required full V90 fixture rewrite.
- **Documentation lag**: this ADR is post-fact (V25 transition implemented 2026-04-28; ADR drafted 2026-05-14, plan §7 Adım 7). Pre-migration kontrat eksik bırakıldı; gelecek transition'larda ADR-first pattern uygulanmalı.
- **Two-table semantic**: developer must explicitly choose `OUR_COMPANY` (tenant boundary) vs `COMPANY` (display) per query. Mistake = either data leak (`COMPANY` for tenant scope = 80k overshare) or display-name miss (`OUR_COMPANY` for label = limited to 42 rows).

### Neutral

- ETL pipeline (`etl-worker`) continues mirroring both `COMPANY` (display) and `OUR_COMPANY` (anchor) tables. Allowlist (`docs/migration/mssql-inventory.md`) explicitly lists both.

## 4. Drift Detection (ADR-0011 DD-1)

`scripts/drift_detection/check_v25_anchor.py` (build-time gate) validates:

- `V25__our_company_anchor.sql` present in `report-service/src/main/resources/db/migration/`
- Tenant predicate signature `(org_id BIGINT)` matches V25 spec
- OpenFGA fixture (`fga/seed.json` or equivalent) uses `wc-our-company-` prefix
- Report registry sourceQuery hardcodes scanned for `wc-company-` (legacy) — present → FAIL

## 5. Migration Chain Reference

V16 → V17 → V19 → V20 → V21 → V22 → V23 → **V25 OUR_COMPANY anchor** → **V26 source_pk dual-format**

V25/V26 Flyway migrations live in `platform-backend/report-service/src/main/resources/db/migration/`. Cross-service contract:

| Service | V25 Migration Step |
|---|---|
| permission-service | OpenFGA tuple writer encoder update (`wc-company-` → `wc-our-company-`) |
| report-service | `OUR_COMPANY` anchor + `RowFilterInjector` references + `RC003HardcodedSchemaForbidden` regex catches `wc-company-` legacy |
| etl-worker | ETL allowlist explicitly tracks both tables |
| schema-service | Snapshot includes both `COMPANY` and `OUR_COMPANY` (47-column schema doc) |

## 6. Codex Thread Reference

- **Discovery**: `019dd34e` Session 32 (2026-04-28) — V25 hybrid plan; PARTIAL/AGREE-with-revisions
- **Decision artifact**: PR sequence #212 (V25 discovery) + #213 (V25 SQL) + #214 (ETL manifest) + #215 (ADR docs) + #216 (V26 dual-format)
- **D35-2 first canlı evidence**: PR #218 (2026-04-28 11/11 canonical steps PASS)
- **D35-2-full**: PR #225 (REST controller layer V25-aligned eventual-consistency canlı yakalandı)
- **This ADR post-fact**: plan `docs/plan-reporting-refactor-2026-05-14.md` §7 Adım 7

## 7. Open Items

- **V25 transition map pre-fact ADR**: lessons-learned: future schema migrations should produce ADR FIRST (plan-time), implementation SECOND. This pattern superseded as of 2026-05-14 plan §3 (Mimari Prensipleri).
- **Documentation gap closure**: this ADR closes 2-week documentation lag (V25 implemented 2026-04-28; ADR 2026-05-14).
- **No new code change required**: V25 + V26 migrations already merged and live on staging-sw `k3d-test` + `k3d-prod` since 2026-04-30 production cutover (Session 36).

---

**Status**: Accepted post-fact. Plan §7 Adım 7 closure artifact.
