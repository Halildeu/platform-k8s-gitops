# Discovery — Faz 21.3 V19/V20/V21 Anchor Table Drift (COMPANY → OUR_COMPANY)

**Tier**: Infrastructure / Schema-design discovery (NOT a D35-X tier).
**Date**: 2026-04-28
**Source**: Schema-service snapshot (`docs/migration/workcube-schema.json`, 3.4 MB, 1509 tables, 26240 columns, 1774 FK), per CLAUDE.md 2026-04-26 user mandate ("Workcube MSSQL kaynak şeması her zaman schema-service üzerinden alınır").
**Codex consult**: thread `019dd34e` (PARTIAL / AGREE-with-revisions, 4-PR sequence, X+Z fix strategy).
**Trigger**: User feedback during DR-6 readiness check 2026-04-28 — "company tablosu değil our_COMPANY gibi birşey olacaktı".

## Finding

V19 + V20 + V21 + V22+V23 + tables.yaml + Faz 16.2.A runbook all reference `workcube_mikrolink.COMPANY` as the company-scope anchor table. Schema-service snapshot inspection reveals this is **wrong**:

- `workcube_mikrolink.COMPANY` (80,246 rows) is a **directory of ALL companies** — customers, vendors, partners, AÇIK's own + others. It has an `OUR_COMPANY_ID` column but it's **nullable**, so it's NOT enforced as tenant-scoped.
- `workcube_mikrolink.OUR_COMPANY` (42 rows) is the **AÇIK org's tenant-scoped table**. PK `COMP_ID` (NOT NULL). Sample rows: COMP_ID=1 Mikrolink Bilişim, COMP_ID=2 Pasif Boreas, COMP_ID=3 Serban Mühendislik, +39 more.

Result: V19 `validate_scope_ref()` would accept ANY of the 80,246 directory rows as a valid company-scope, breaking tenant boundary. AÇIK's data_access scope contract was never tenant-enforced.

## Anchor table contract — corrected (Codex `019dd34e` Hybrid)

| scope_kind | Anchor table | PK / source_pk col | Tenant predicate |
|---|---|---|---|
| `company` | `OUR_COMPANY` | `COMP_ID` (int, NOT NULL) | direct (table is itself tenant-scoped) |
| `depot` (was DEPARTMENT) | `DEPARTMENT` | (PK; investigate) | `DEPARTMENT.OUR_COMPANY_ID = ?` (nullable column) |
| `branch` | `BRANCH` | (PK; investigate) | 2-hop: `BRANCH.COMPANY_ID → COMPANY.OUR_COMPANY_ID = ?` (both nullable) |
| `project` | `PRO_PROJECTS` | (PK; investigate) | `COMPANY_ID = ?` (1-hop, primary FK; +3 secondary refs CARGO/DUTY/INSURANCE not for tenant boundary) |

**Critical nuance** (Codex `019dd34e`): tenant-membership predicate is NOT just "row exists in anchor table". It requires:
- `company` → `OUR_COMPANY.COMP_ID = source_pk`
- `branch/project/depot` → predicate chain ensuring the row belongs to AÇIK's `OUR_COMPANY`

V19/V20 currently checks only **global existence** in `COMPANY` (80,246 rows). Any source_pk in the directory passes. Tenant boundary effectively absent.

## Schema-service evidence

```
$ jq -r '.tables[] | select(.name | test("our_"; "i") or test("^company$|^pro_projects$|^branch$|^department$"; "i")) | "\(.schema).\(.name)"' docs/migration/workcube-schema.json | grep workcube_mikrolink
workcube_mikrolink.BRANCH
workcube_mikrolink.COMPANY
workcube_mikrolink.DEPARTMENT
workcube_mikrolink.OUR_COMPANY              ← anchor for company scope
workcube_mikrolink.OUR_COMPANY_ASSET
workcube_mikrolink.OUR_COMPANY_BANK_RELATION
workcube_mikrolink.OUR_COMPANY_HISTORY
workcube_mikrolink.OUR_COMPANY_HOURS
workcube_mikrolink.OUR_COMPANY_INFO
workcube_mikrolink.OUR_COMPANY_POS_RELATION
workcube_mikrolink.OUR_COMPANY_TARGET
workcube_mikrolink.PRO_PROJECTS

$ # Tenant FK columns per anchor table
BRANCH:        COMPANY_ID (nullable=true) — 2-hop tenant chain
DEPARTMENT:    OUR_COMPANY_ID (nullable=true) — 1-hop direct
PRO_PROJECTS:  COMPANY_ID (nullable=true) primary; CARGO_COMPANY_ID, DUTY_COMPANY_ID, INSURANCE_COMPANY_ID (secondary, NOT tenant)
COMPANY:       COMPANY_ID (PK NOT NULL); OUR_COMPANY_ID (nullable) — tenant filter possible but unenforced
OUR_COMPANY:   COMP_ID (PK NOT NULL) — direct tenant boundary
```

```
$ # Live MSSQL row counts (NTLM via etl-worker, 2026-04-28)
workcube_mikrolink.COMPANY     = 80,246 rows (directory)
workcube_mikrolink.OUR_COMPANY = 42 rows (AÇIK tenant scope)
```

## Why V19/V20/V21 plan-time review didn't catch this

Codex threads:
- `019dc8b4` (V19/V20 design) — focused on schema placement, CHECK constraints, trigger guard, UPDATE-smuggling, partial-unique re-grant, depot decision (DEPARTMENT vs DEPOT)
- `019dcfb0` (V21 JSON parse) — focused on encoder ↔ trigger contract mismatch
- `019dd0e0` (V22+V23 outbox) — focused on transactional outbox + CAS fence + tuple-key ordering

None of these threads had access to live Workcube schema source convention. The assumption "company scope_kind ↔ COMPANY table" was unchallenged at plan-time. Codex `019dd34e` retrospective: "Onay, canlı Workcube row semantics bilinmeden COMPANY'nin 'anchor' olduğu varsayımı üstünden verilmiş. Source schema convention ve live row-count anlamı plan-time'da eksik kalmış."

This is a **planning gap**, not informed approval reversal. V19/V20/V21 are technically correct under their stated assumption; the assumption was wrong. Lesson logged: schema-service snapshot SHOULD be cross-referenced for any data_access scope-kind anchor decisions in future ADRs.

## Live state when this was found

- `data_access.scope` rows: 0 (no scopes inserted yet — D35-2 evidence not run)
- `data_access.organization_company` rows: 0 (V19 seed CROSS JOIN matched nothing — `workcube_mikrolink.company` was empty in reports_db)
- `workcube_mikrolink.company` rows in reports_db: 0 (ETL not loaded)
- DR-6 Step 1 readiness check: PASS via `OUR_COMPANY` discovery + `--env-file backend.env` + multi-prefix env fallback (PR #211)

**No data corruption** — drift caught BEFORE any scope row was inserted, BEFORE D35-1 ETL load to reports_db. Fix-forward is clean.

## Remediation plan (Codex `019dd34e` AGREE-with-revisions, 4-PR sequence)

### PR-1 (this PR) — Discovery + drift note

- This file documents the finding.
- `current-state.md` updated with "D35-1 anchor drift" note (separate hunk in this PR).
- No code changes; pure documentation truth-closure.

### PR-2 — V25 migration + SQL tests + ops grant

- `sql/migration/V25__data_access_tenant_anchor_fix.sql`:
  * `data_access.scope_kind_source_table_consistent` CHECK update:
    - `company` ↔ `OUR_COMPANY` (was `COMPANY`)
    - `depot` ↔ `DEPARTMENT` (unchanged)
    - `branch` ↔ `BRANCH` (unchanged but predicate semantic changes)
    - `project` ↔ `PRO_PROJECTS` (unchanged but predicate semantic changes)
  * `validate_scope_ref()` CREATE OR REPLACE with tenant-aware predicates:
    - company branch → `EXISTS (SELECT 1 FROM workcube_mikrolink.our_company WHERE comp_id = (p_ref::jsonb->>0)::int)`
    - depot branch → tenant predicate via `workcube_mikrolink.department.our_company_id`
    - branch branch → 2-hop predicate via COMPANY join
    - project branch → `workcube_mikrolink.pro_projects.company_id` 1-hop
  * `data_access.organization_company` truncate (currently 0 rows; safe) + comment update
- `sql/migration/tests/test_v19_v20_data_access.sql` extension:
  * Tests for OUR_COMPANY existence anchor + tenant-membership predicates
  * Negative tests: directory COMPANY row exists but OUR_COMPANY mapping absent → reject
- `sql/ops/01_reports_db_permission_role.sql` extension:
  * `GRANT SELECT ON workcube_mikrolink.our_company TO permission_reports_writer;`
  * Existing COMPANY/BRANCH/DEPARTMENT/PRO_PROJECTS SELECT grants kept (financial reports + multi-hop predicates need them)
- `docs/RB-vault-bootstrap-writer-apply.md` smoke updates if needed.

### PR-3 — ETL manifest + Faz 16.2.A runbook revize

- `scripts/migration/etl_worker/config/tables.yaml`: add `OUR_COMPANY` entry (PK = COMP_ID, idempotency_key = [COMP_ID]).
- `docs/RB-faz-16-2-A-scope-anchor-load.md`: replace `--tables COMPANY` with `--tables OUR_COMPANY` (and consider all-42-rows full load instead of `--limit 1`, since 42 << minimum-fixture threshold).
- D35-1 evidence template note: anchor row provenance now `OUR_COMPANY.COMP_ID`, NOT `COMPANY.COMPANY_ID`.

### PR-4 — ADR-0008 + ADR-0009 + D35 ladder + PLAN.md update

- `docs/adr/0008-multi-org-explicit-scope-zanzibar.md`: explicit "anchor table is `OUR_COMPANY`, NOT `COMPANY`" addendum.
- `docs/adr/0009-canli-scoped-e2e-gate.md` D35 ladder section: D35-1 capture format updated; expected source_pk = `OUR_COMPANY.COMP_ID`.
- Object id encoding decision: prefer `company:wc-our-company-<COMP_ID>` over `company:wc-company-<id>` (Codex `019dd34e` recommendation: less misleading).
- `PLAN.md` Faz 21.3 + Faz 16.2.A entries updated.

### Operator sequence

After PR-1..PR-4 merged:
1. Apply V25 (`sql/migration/V25__...sql`) to reports_db (operator-driven — Flyway disabled per test overlay).
2. Re-run Faz 16.2.A runbook with corrected `OUR_COMPANY --limit 1` (or all-42 load).
3. Capture D35-1 evidence with proper anchor.
4. Then DR-7 D35-2 first canlı evidence with real `OUR_COMPANY.COMP_ID` as scope_ref.

## D35 ladder declaration

This PR (advances | affects | does NOT touch) the following D35 tier(s):

- [x] D35-0 — Runtime preflight: not directly advanced, but PR-2 (V25) will require new preflight evidence after applied
- [x] D35-1 — Scope anchor prereq: **affects** (anchor table contract corrected; D35-1 evidence template format change in PR-4)
- [x] D35-2 — Scoped grant/revoke E2E: **affects** (scope_ref semantic change: `OUR_COMPANY.COMP_ID` vs old `COMPANY.COMPANY_ID`; PR-4 transition map)
- [x] D35-3 — Product path: **affects** (UI must use OUR_COMPANY for tenant-scoped picker)

This PR creates this discovery evidence file but no D35-X tier evidence yet.

## References

- Schema-service snapshot: `docs/migration/workcube-schema.json` (canonical Workcube source of truth)
- CLAUDE.md 2026-04-26 user mandate: "Workcube MSSQL kaynak şeması her zaman schema-service üzerinden alınır. Agent sentetik tablo/kolon/FK üretmemeli — gerçek snapshot mevcuttur."
- Codex thread `019dd34e` (PARTIAL/AGREE-with-revisions, this discovery's response)
- V19 (PR #186), V20 (PR #164), V21 (PR #186), V22 (PR #187), V23 (PR #188)
- DR-6 readiness PR #211 (multi-prefix env fix that surfaced this)
- ADR-0008 (multi-org explicit-scope), ADR-0009 (D35 canlı E2E gate), ADR-0010 §2.3 (D35 ladder)
- User feedback 2026-04-28: "company tablosu değil our_COMPANY gibi birşey olacaktı" + "bizim şema gezginide bunlar mevcut"
