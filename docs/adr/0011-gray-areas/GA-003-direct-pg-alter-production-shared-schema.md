# GA-003 — Direct PG ALTER on production-shared schema

## Class

`state-mutation (production)` veya — ADR-0011 §2.3 + bypass niteliğine göre — **always-blocked** (production schema bypass migration discipline).

## Sandbox behavior

`blocked-as-expected` — Session 32'de sandbox bu pattern'i doğru blokladı. Codex `019dd333` retrospective: "Sandbox correctly blocked 3 categories: Vault state-file reads (even on test), hot-patch DB function bypassing migration, prod credential reads."

ADR-0011 §1 listesinde yer alıyor; sandbox'un doğru karar verdiği emsal pattern.

## Decision

**Agent için yasak.** Test cluster'da bile hot-patch `psql` heredoc ile migration bypass normal route değil; migration PR + CI + controlled apply pattern kullanılmalı.

Production veya production-shared schema (`reports_db.data_access`, `reports_db.workcube_mikrolink`, `auth_db.public`, vs):
- `ALTER TABLE` direct → migration bypass
- `DROP FUNCTION/TABLE` direct → schema drift
- `CREATE OR REPLACE FUNCTION` direct → bypasses Flyway version tracking

Test cluster'da bile aynı kalıp (`docker exec platform-pg-test psql ... -c "ALTER ..."`) Codex retrospective ile yasak — drift ve "test-only" hot-patch'lerin prod'a sızma riski.

## Agent allowed

- Read-only `psql` query (information_schema, pg_catalog, custom views)
- Migration SQL **dosyası yazmak** (`sql/migration/V<N>__<name>.sql`) — PR + CI flow
- `kubectl kustomize ...` ile manifest validate
- DD-1..DD-4 drift detection guard çalıştırma (read-only static analysis)
- Operator-provided psql output redacted parse

## Agent blocked

- `psql -c "ALTER TABLE ..."` (her cluster'da)
- `psql -c "DROP ..."` (her cluster'da)
- `psql -c "CREATE OR REPLACE FUNCTION ..."` migration bypass
- `\copy` veya `COPY FROM` data import (state mutation)
- `pg_restore` / `pg_dump` ile state mutate (read-only dump OK; restore yasak)
- Prod cluster'da herhangi bir DML/DDL (read-only INSERT/UPDATE/DELETE/TRUNCATE)

## User path

1. **Migration PR** açıl (Flyway V<N> file)
2. Codex consensus + plan-time review
3. CI: data-access-migrations.yml ve drift detection lane'leri PASS
4. Selective apply pattern (CLAUDE.md "Selective Apply (D17 koruma)" — tek dosya apply, full overlay değil)
5. Rolling restart eğer Java service schema-aware
6. Drift evidence: DD-3 actual snapshot refresh post-migration

Production cluster için ek:
- Dual-clearance approval (operator + user)
- Cutover runbook
- Backup/snapshot pre-apply
- Rollback plan

## BG-1 mapping

Test cluster migration PR'ı:
- [x] state-mutation (test cluster)
- BG-1: state-mutation (test cluster) user-approval gerekmez (Codex consensus + Kural #7 yetki)

Production migration PR'ı:
- [x] state-mutation (production)
- [x] user-approval-required label
- User-approval evidence link zorunlu

Direct ALTER bypass denemesi (yasak):
- Hiçbir BG-1 kombinasyonu meşrulaştırmaz; pattern always-blocked.

## References

- ADR-0011 §1 Context (gray-area #3: "Direct PG ALTER on production-shared schema (sandbox blocked correctly)")
- ADR-0011 §2.3 (boundary class)
- ADR-0010 §2.5 (Operator/agent authority — production state mutations)
- CLAUDE.md HARD RULE #7 (SSH+sudo+kubectl agent yetkisi — sınırları)
- CLAUDE.md HARD RULE #6 (Production destructive — explicit user approval)
- Migration discipline: V25/V26 Flyway pattern (Faz 21.3 V25 hybrid contract — PR #213 + #216)
- DD-1..DD-3 drift detection: post-migration verification layer
- Codex thread `019dd333` Session 32 retrospective (sandbox correct-blocking emsali)
- Codex thread `019dd409` BG-2 always-blocked direktifi
