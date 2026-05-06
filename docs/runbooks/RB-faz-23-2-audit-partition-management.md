# RB-faz-23-2-audit-partition-management

> **Faz**: 23.2 (Production MVP dar)
> **Codex thread**: `019dfae5-97e6-74c0-9b13-5a15f09f507f`

## Bağlam

`notify.audit_event` tablosu append-only RULE ile korunur (DELETE NOTHING).
Faz 23.2 PR-B-iter-1'de partition migration scope'tan çıkarıldı (V7 risk).
Bu runbook **follow-up scheduled task** kapsamında audit partition'a
geçişi belgeler.

## Phase 1 — Partition migration (follow-up commit)

V7-revised migration (audit_event_v2 cutover pattern):

1. Yeni partitioned parent yarat: `audit_event_v2 PARTITION BY RANGE (occurred_at)`
2. Composite PK (id, occurred_at) — JPA `@IdClass(AuditEventId.class)`
3. Initial partitions: current month + next 3 months
4. Default partition (catch-all) ATTACH
5. Dual-write window (audit publisher → both v1 + v2)
6. Backfill: COPY v1 → v2 chunked (10k rows/batch)
7. Validate: SELECT COUNT(*) v1 == v2
8. Cutover: rename v1 → v1_legacy, v2 → audit_event
9. Drop dual-write; legacy retain 30 day rollback window

## Phase 2 — Operator scheduled task (monthly)

```bash
# Cron: 1st of each month, 02:00 UTC
# Creates next_month + drops oldest partition (90-day retention)

PARTITION_NAME="audit_event_$(date +%Y_%m)"
NEXT_MONTH=$(date -d "+1 month" +%Y-%m-01)
NEXT_NEXT_MONTH=$(date -d "+2 month" +%Y-%m-01)

psql -c "CREATE TABLE notify.${PARTITION_NAME} PARTITION OF notify.audit_event \
  FOR VALUES FROM ('${NEXT_MONTH}') TO ('${NEXT_NEXT_MONTH}');"

# 90-day retention drop
OLD_MONTH=$(date -d "-3 months" +%Y_%m)
OLD_PARTITION="audit_event_${OLD_MONTH}"

# Optional: archive to S3/cold storage before drop
psql -c "ALTER TABLE notify.audit_event DETACH PARTITION notify.${OLD_PARTITION};"
psql -c "DROP TABLE notify.${OLD_PARTITION};"
```

## Phase 3 — Alert integration

PrometheusRule `notify.audit_partition.missing` (PR-C follow-up):
- Detect missing partition for current/next month
- Page operator if scheduled task fails

## Rollback

Phase 1 cutover fails → keep v1, drop v2, fix forward.
Phase 2 partition create fails → audit writes go to default partition; no
data loss; manual partition create + ALTER ATTACH PARTITION DEFAULT.

## Referans

- ADR-0013 D46 #7 (audit append-only)
- Codex thread: `019dfae5-97e6-74c0-9b13-5a15f09f507f`
- backend PR #67 (PR-B; payload nullable; partition deferred)
