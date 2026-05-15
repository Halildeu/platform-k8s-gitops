# Annex 2A — Domain Decision Packet (2026-05-15)

> **Codex 019e2c59 iter-3 follow-up.** PR #680 (v2 validation) schema cross-check kapısını kapattı. Bu packet kalan 3 domain decision sign-off sheet'ini içerir — Adım 13 SEAL'in son agent-actionable kapısı.

## Status

```yaml
agent_action: proposal-only
seal_flip: NOT YET (3 sign-off pending)
canonical_yaml_changes: 0  # status, seal_state, manually_validated, migration_action_default DEĞİŞMEDİ
```

## Sheets

| # | Sheet | Signer(s) | Decision Count | Reference |
|---|---|---|---|---|
| 1 | [Migration Action Matrix](./01-migration-action-matrix.md) | DBA + PO | 31 report | Default `migrate` (Faz 17 niyet) |
| 2 | [Float Semantic Class](./02-float-semantic-class.md) | DBA + Backend Lead (çift onay) | 206 numeric kolon | `mssql-pg-data-contract.md` §471 SEAL BLOCKER |
| 3 | [Timezone](./03-timezone.md) | ERP DBA | 17 datetime kolon | `mssql-pg-data-contract.md` §493 |

## Heuristic Confidence Disclaimer

Agent **gerçek SQL DECIMAL/MONEY/FLOAT tipini doğrulamamış** — sadece UI column metadata (`type: number` / `text` / `date`) + column name pattern ile heuristic sınıflandırma. DBA gerçek SQL tipini doğrularken:

```sql
-- Schema-service ile cross-check:
GET /api/v1/schema/snapshot?schema=workcube_mikrolink
GET /api/v1/schema/snapshot?schema=workcube_mikrolink_2026_1
-- Veya direkt MSSQL:
SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'workcube_mikrolink' AND TABLE_NAME = 'ACCOUNT_CARD'
```

## SEAL Flip Sequence (sign-off sonrası)

```
1. 3 sheet'te tüm checkbox'lar dolu + imzalar mevcut
2. Agent yeni PR açar (canonical SEAL flip):
   - report-source-annex.yaml:
       _meta.status: SEALED
       _meta.seal_state: SEALED
       _meta.sealed_at: <date>
       _meta.sealed_by: <DBA name> + <PO name> + <ERP DBA name> + <backend lead name>
       _meta.migration_action_signoff: true
       _meta.float_semantic_class_signoff: true
       _meta.timezone_signoff: { policy: <decision>, signed_at: <date> }
     reports[*].migration_action_default: <her satır için DBA/PO kararı>
     reports[*].manually_validated: true  (8 sourceQuery için)
3. ADR-0005 §6 amendment merge (timezone + float policy + migration scope)
4. Adım 11.5 prod cutover unblock (REPORT_MSSQL_ENABLED=true)
```

## Cross-AI

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e2c59-1cdb-7ea3-a8e6-bf3fcabc62b2
verdict: B-prime continued (iter-3 onerisi — agent proposal sheet, operator sign-off)
flip_authority: operator only (DBA + PO + Backend Lead + ERP DBA)
```
