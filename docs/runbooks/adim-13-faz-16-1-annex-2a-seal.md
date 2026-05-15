# Operator Runbook: Adım 13 — Faz 16.1 annex 2A SEAL

> Plan §7 Adım 13: 44 vs 31 tablo reconciliation + ADR-0005 §6 SEAL amendment

## Status

- **Current**: `seal_state: DRAFT` ([docs/migration/report-source-annex.yaml](../migration/report-source-annex.yaml#L4))
- **Blocking**: 3 acceptance gate kriteri açık (aşağıda detay)

## SEAL Gate Kriterleri (mevcut report-source-annex.yaml `_meta.seal_gate`)

1. ❌ **All sourceQuery reports manually validated** — 24/31 done, **7 pending**:
   - `fin-cari-islemler`
   - `fin-fatura-satirlari`
   - `fin-kaynak-eslesme`
   - `fin-masraf-detay`
   - `fin-muhasebe-detay`
   - `fin-stok-fis-detay`
   - `fin-tutar-mutabakat`
   - `hr-compensation-detay` (8th — sayım listede)
2. ⏳ **Zero tables with schema='UNKNOWN_AT_PARSE'** — manuel verify gerek
3. ❌ **Zero tables with migration_action_default='pending_annex'** — 31/31 hâlâ `pending_annex`
4. ⏳ **Workcube admin resolved all parametric_schemas** — DBA review

## Operator Action Sequence

### A. SourceQuery report manual validation (8 pending)

Her bir report için:

```bash
# 1. Report JSON aç:
cat platform-backend/report-service/src/main/resources/reports/<report-key>.json | jq '.sourceQuery'

# 2. SQL query'i tek tek incele — DBA review:
#    - Table list doğru mu (Workcube schema)
#    - Column references workcube-schema.json snapshot ile match mı
#    - Cross-tenant isolation rowFilter aktif mı
#    - JOIN cardinality sane mı (yearly schema partition)

# 3. report-source-annex.yaml entry'sinde `manually_validated: false` → `true`:
yq -i '.reports[] | select(.report == "<report-key>") | .manually_validated = true' \
  docs/migration/report-source-annex.yaml
```

### B. migration_action_default finalize (31 entry)

Her bir report için DBA + product owner kararı:
- `migrate`: Bu tablo PG'ye taşınacak (Faz 17+ Workcube decommission)
- `exclude`: Bu tablo PG'ye taşınmayacak (deprecated/legacy)
- `keep_workcube`: Bu tablo Workcube'da kalacak (read-only bridge sürekli)

```bash
# Bulk update örnek:
for report in fin-* hr-*; do
  yq -i ".reports[] | select(.report == \"${report}\") | .migration_action_default = \"migrate\"" \
    docs/migration/report-source-annex.yaml
done
```

### C. Float semantic_class double-sign-off

Annex 2A'da sayısal/decimal kolonların semantic_class field'ı:
- `analytical` (KPI/aggregation; analitik tolerans)
- `currency` (TL/USD; banking-grade precision)
- `counter` (sayım/quantity; integer semantic)

DBA + Product Owner BOTH sign-off (audit trail).

### D. Timezone ERP DBA approval

ERP DBA Workcube tarafından datetime kolonlarda timezone semantic'i doğrular:
- UTC vs Europe/Istanbul vs DST handling
- workcube-schema.json `tables.*.columns[].timezone_hint` (eğer eklenmişse)

### E. ADR-0005 §6 amendment

Annex 2A SEAL kararı sonrası:

```markdown
## §6 (Yeni) Faz 16.1 Annex 2A SEAL — <YYYY-MM-DD>

### Karar
Annex 2A (`docs/migration/report-source-annex.yaml`) **SEALED**:
- 31 report manually_validated: true
- 44 tablo authority mapping finalize
- Float semantic_class triple-sign-off
- Timezone ERP DBA approval

### Onay
- DBA (Workcube): @<dba-handle>
- Product Owner: @<po-handle>
- Codex governance review thread: `019eXXXX`

### Etkisi
- Adım 11.5 prod cutover blocker kaldırılır (`REPORT_MSSQL_ENABLED=true`)
- Faz 17 Workcube decommission planlaması başlar
```

### F. Annex 2A status flip

```bash
yq -i '._meta.status = "SEALED" | ._meta.seal_state = "SEALED" | ._meta.sealed_at = now | ._meta.sealed_by = "<dba+po-handle>"' \
  docs/migration/report-source-annex.yaml
```

### G. Annex 2A commit + PR

```bash
git checkout -b docs/faz-16-1-annex-2a-seal
git add docs/migration/report-source-annex.yaml docs/adr/0005-dual-datasource-reporting.md
git commit -m "docs(annex-2a): Faz 16.1 SEAL — 31 report manually_validated, 44 tablo authority finalize"
git push -u origin docs/faz-16-1-annex-2a-seal
gh pr create --base main --title "docs(annex-2a): Faz 16.1 SEAL"
```

Cross-AI peer review (HARD RULE): Codex governance review thread (yeni thread `mcp__codex__codex` ile başlat). Codex AGREE sonrası PR merge.

## Adım 11.5 Bağımlılığı

Annex 2A SEAL gate yeşillendiğinde **Adım 11.5 prod cutover hazır**:

```bash
# Prod cluster:
kubectl --context k3d-prod -n platform-prod patch configmap report-service-config \
  --type merge -p '{"data":{"REPORT_MSSQL_ENABLED":"true"}}'
kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service
```

## Effort tahmin

- 8 sourceQuery report manual validation: **2-4 saat** (DBA review)
- 31 migration_action_default karar: **1-2 saat** (DBA + PO discussion)
- Float semantic_class sign-off: **30-60 dk**
- Timezone approval: **30 dk**
- ADR amendment + PR: **30 dk** (agent yazabilir)
- Cross-AI Codex review: **15-30 dk**
- **Toplam**: **5-8 saat** (DBA availability bağımlı)

## Notlar

- DBA review olmadan annex 2A SEAL yapılamaz — agent yetkisi dışı domain knowledge
- ADR-0005 amendment doc agent tarafından PR template'i sunulabilir, ama SEAL kararı operator onayı bekler
- Adım 11.5 cutover bağımlılık zinciri: Adım 13 SEAL → Adım 11.5 cutover → Adım 1.5 acceptance smoke

## Referans

- [docs/migration/report-source-annex.yaml](../migration/report-source-annex.yaml)
- [docs/adr/0005-dual-datasource-reporting.md](../adr/0005-dual-datasource-reporting.md) §6 (amendment slot)
- [docs/plan-reporting-refactor-2026-05-14.md](../plan-reporting-refactor-2026-05-14.md) §7 Adım 13
- Session 53/54/55 handoff doc'lar (R16 epic + R15 user-visible repair chain)
