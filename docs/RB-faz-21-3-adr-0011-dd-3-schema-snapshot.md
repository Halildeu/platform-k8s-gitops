# RB ADR-0011 DD-3 — `reports_db.workcube_mikrolink.*` Actual Schema Snapshot Export

> **Tetikleyici**: Quarterly schema snapshot drift detection (ADR-0011 §2.1.1.3) veya ETL/migration sonrası ad-hoc verify.
> **Authority**: **Operatör** (read-only psql via kubectl exec — credential boundary; agent transcript'inde `REPORTS_DB_PASSWORD` literal görmez).
> **Codex thread**: `019dd409` B-prime AGREE — DD-3 operator-loop, agent scaffold + script + workflow.

## Neden gerekli

DD-1 (anchor + V25/V26 contract) + DD-2 (ETL canonical JSON contract) **plan-time** drift'leri yakalar (commit-edilmiş source dosyalarda).

DD-3 ise **canlı reports_db** ile committed `workcube-schema.json` baseline arasındaki **runtime drift**'i yakalar:
- ETL run sonrası tablo eklendi/eksildi
- Manual ALTER TABLE (off-migration) yapıldı
- Lineage column drop oldu (V17 sentinel cleanup eksik)
- Schema-service snapshot'ı stale kaldı (Workcube source değişti, baseline güncellenmedi)

Quarterly cadence: ETL slow-changing source; her sprint export'a gerek yok. Ama 3-4 ay'da bir refresh + diff zorunlu.

## Boundary

**Operatör-only**:
- `kubectl --context k3d-test exec` — read-only şart, hiçbir mutation
- Vault'tan REPORTS_DB credentials okuma (kullanıcı adımı; agent transcript'inde literal görmez)
- Output JSON artifact'ı PR olarak commit (agent yapamaz, kullanıcı operator)

**Agent-yapılabilir** (PR review + diff):
- Commit edilen artifact'ı CI'da `check_drift_reports_db_snapshot.py` ile validate
- Diff vs source `workcube-schema.json` baseline
- Drift varsa hard-fail; pending state → graceful warn

## Prereq

- [ ] Vault `kv/platform/permission-service` (veya benzer) → REPORTS_DB_USERNAME + REPORTS_DB_PASSWORD okunabiliyor
- [ ] `kubectl --context k3d-test` erişimi
- [ ] `docker exec platform-pg-test` veya in-cluster PG bağlantısı

## Step 1 — Source snapshot SHA256 hesapla

Artifact içine `source_snapshot_sha256` field eklenir; CI bu hash'i baseline file'ın SHA256'sıyla karşılaştırır. Drift varsa fail.

```bash
# Operator shell
cd /home/halil/platform-k8s-gitops
SOURCE_SHA=$(sha256sum docs/migration/workcube-schema.json | cut -d' ' -f1)
echo "source SHA256: $SOURCE_SHA"
```

## Step 2 — Export PG actual schema

```bash
# Operator runs — REPORTS_DB_PASSWORD env is shell-local, agent görmüyor
export PGPASSWORD=$(vault kv get -field=db_password kv/platform/permission-service 2>/dev/null \
  || cat /path/to/local/secret)  # operator's local credential source

# Run export SQL via in-cluster psql proxy or direct compose container
docker exec -i platform-pg-test psql \
  -U platform -d reports_db -At \
  -v source_sha256="$SOURCE_SHA" \
  -v generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -f - \
  < scripts/drift_detection/export_reports_db_schema.sql \
  > /tmp/reports-db-actual-schema.json

# Doğrula JSON valid
jq '.generated_at, .source_snapshot_sha256, (.tables | keys | length)' /tmp/reports-db-actual-schema.json
```

Beklenen çıktı:
```
"2026-04-28T16:45:00Z"
"<source_sha256 hex>"
~50  # ETL-managed table sayısı (tables.yaml'a göre değişir)
```

## Step 3 — Pretty-print + commit

```bash
# Pretty print + sort keys for stable diff
jq -S '.' /tmp/reports-db-actual-schema.json > docs/migration/reports-db-workcube-actual-schema.json

# Verify CI script PASS
python3 scripts/drift_detection/check_drift_reports_db_snapshot.py --verbose

# PR oluştur
git checkout -b ops/dd-3-actual-schema-$(date +%Y%m%d)
git add docs/migration/reports-db-workcube-actual-schema.json
git commit -m "ops(adr-0011-dd-3): refresh reports_db actual schema snapshot ($(date +%Y-%m-%d))"
git push -u origin ops/dd-3-actual-schema-$(date +%Y%m%d)
gh pr create --title "ops(adr-0011-dd-3): refresh reports_db actual schema snapshot $(date +%Y-%m-%d)" \
  --body "Quarterly DD-3 artifact refresh per ADR-0011 §2.1.1.3 + Codex 019dd409 B-prime operator-loop."
```

## Step 4 — CI validation

PR'da `ADR-0011 DD-3 schema-service snapshot` workflow lane'i şu check'leri koşar:

1. `actual_artifact_present` — dosya var mı?
2. `actual_artifact_freshness` — ≤120 days
3. `actual_artifact_source_hash_match` — `source_snapshot_sha256` field current `workcube-schema.json` SHA'sına eşit
4. `etl_managed_tables_in_source` — `tables.yaml` ETL-managed entry'leri source snapshot'ta var
5. `etl_managed_tables_in_actual` — aynı entry'ler PG actual snapshot'ta var
6. `pg_lineage_columns_present` — her ETL tablo'da V17 lineage cols (`source_schema, source_table, source_pk, content_hash`)

Drift varsa CI red. Hard-fail. Graceful pending state sadece artifact yoksa (operator henüz refresh etmediyse).

## Cleanup (opsiyonel)

Eski actual artifact'ları arşivleyebilirsin:
```bash
mkdir -p docs/migration/archive
mv docs/migration/reports-db-workcube-actual-schema-2026-Q1.json docs/migration/archive/
```

Veya tek dosya rotated yaklaşım — artifact dosyası tek isimli, son refresh tarihini `generated_at` field'ı ile takip edilir.

## Boundary declaration (ADR-0011 §2.3)

DD-3 artifact refresh PR'larında:

```markdown
- [x] credential-read (operatör Vault'tan REPORTS_DB_PASSWORD okur — local shell, no transcript)
- [ ] credential-write
- [ ] state-mutation (test cluster) — read-only psql query
- [ ] state-mutation (production)
- [x] boundary-cross (gitops repo'ya canlı cluster artifact commit)
- [ ] none of the above
```

## References

- ADR-0011 §2.1.1.3 (schema-service snapshot diff cron)
- ADR-0011 §2.3 (boundary class — operator credential-read)
- DD-1 PR #228 + DD-2 PR #229 (companion plan-time guards)
- Codex thread `019dd409` B-prime (DD-3 operator-loop strategy)
- Source snapshot: `docs/migration/workcube-schema.json` (3.4 MB, 1509 tables)
- ETL allowlist: `scripts/migration/etl_worker/config/tables.yaml` (anchor + parametric entries)
- V17 lineage migration: `sql/migration/V17__etl_lineage_columns.sql`
