# Adım 13 SEAL — DBA + PO Sign-off Packet

> Plan §7 Adım 13 sign-off paketi. DBA + Product Owner için tek sayfa.
> Reference runbook: [adim-13-faz-16-1-annex-2a-seal.md](./adim-13-faz-16-1-annex-2a-seal.md)

## SEAL Gate Critical Path

| Adım | Sorumlu | Status | Effort |
|---|---|---|---|
| A. 8 sourceQuery DBA review | DBA | ❌ | 2-4 saat |
| B. 31 migration_action_default karar | DBA + PO | ❌ | 1-2 saat |
| C. Float semantic_class double-sign-off | DBA + PO | ❌ | 30-60 dk |
| D. Timezone ERP DBA approval | ERP DBA | ❌ | 30 dk |
| E. ADR-0005 §6 amendment | Claude + Codex | ⏳ template hazır | 30 dk |
| F. Annex 2A status flip + PR | Operator | ❌ | 15 dk |

---

## A. 8 SourceQuery DBA Review Checklist

**Her bir report için DBA bakar:**

| Check | Detay |
|---|---|
| ☐ Table references | `workcube-schema.json` snapshot'ta mı? UNKNOWN_AT_PARSE yok mu? |
| ☐ Column references | Type-aware (nvarchar AVG yok, vb.)? |
| ☐ JOIN cardinality | Sane partition (yearly schema)? |
| ☐ rowFilter | Cross-tenant isolation aktif mı? |
| ☐ Parametric schema | `workcube_mikrolink_<year>_<tenant>` resolver doğru mu? |
| ☐ NOLOCK hint | Production read-only OK mi? |

### Per-Report Review Slots

| # | Report Key | SQL Query Location | DBA Sign | Note |
|---|---|---|---|---|
| 1 | `fin-cari-islemler` | `platform-backend/report-service/src/main/resources/reports/fin-cari-islemler.json` | ☐ | |
| 2 | `fin-fatura-satirlari` | `.../fin-fatura-satirlari.json` | ☐ | |
| 3 | `fin-kaynak-eslesme` | `.../fin-kaynak-eslesme.json` | ☐ | |
| 4 | `fin-masraf-detay` | `.../fin-masraf-detay.json` | ☐ | |
| 5 | `fin-muhasebe-detay` | `.../fin-muhasebe-detay.json` | ☐ | |
| 6 | `fin-stok-fis-detay` | `.../fin-stok-fis-detay.json` | ☐ | |
| 7 | `fin-tutar-mutabakat` | `.../fin-tutar-mutabakat.json` | ☐ | |
| 8 | `hr-compensation-detay` | `.../hr-compensation-detay.json` | ☐ | |

### Validation Komutu (DBA için)

```bash
# Her report için sourceQuery'yi extract:
cat platform-backend/report-service/src/main/resources/reports/<key>.json | jq -r '.sourceQuery'

# workcube-schema.json ile cross-check:
python3 -c "
import json
with open('docs/migration/workcube-schema.json') as f:
    schema = json.load(f)
# tablo + kolon validation kodu
"
```

### Validation Onayı

DBA onayı sonrası:
```bash
yq -i '.reports[] | select(.report == \"<key>\") | .manually_validated = true' \
  docs/migration/report-source-annex.yaml
```

---

## B. 31 migration_action_default Karar Matrisi

Her report için 3 seçenekten biri:
- `migrate`: PG'ye taşınacak (Faz 17+ Workcube decommission)
- `exclude`: PG'ye taşınmaz (deprecated/legacy)
- `keep_workcube`: Workcube'da kalır (read-only bridge sürekli)

### Karar Matrisi (DBA + PO)

| # | Report Group | Karar | Sebep |
|---|---|---|---|
| FIN | 17 finans raporu | ☐ migrate / ☐ exclude / ☐ keep_workcube | |
| HR | 9 İK raporu | ☐ migrate / ☐ exclude / ☐ keep_workcube | |
| SALES | 2 satış raporu | ☐ migrate / ☐ exclude / ☐ keep_workcube | |
| DASHBOARD | 12 dashboard | Dashboard'lar zaten PG (etkilenmez) | - |

### Bulk Update Komutu

```bash
# Tüm finans için migrate (örnek):
for report in $(yq '.reports[] | select(.category == "Finans") | .report' docs/migration/report-source-annex.yaml); do
  yq -i ".reports[] | select(.report == \"${report}\") | .migration_action_default = \"migrate\"" \
    docs/migration/report-source-annex.yaml
done
```

---

## C. Float semantic_class Double-Sign-off

Workcube schema'da nümerik/decimal kolonlar için semantic class:

| Class | Anlam | Örnek Kolonlar |
|---|---|---|
| `analytical` | KPI/aggregation; analitik tolerans | M1..M12 (employee salary monthly) |
| `currency` | TL/USD; banking-grade precision | ACCOUNT_ROW.NET_AMOUNT, INVOICE.TOTAL |
| `counter` | Sayım/quantity; integer semantic | EMPLOYEE_COUNT, ITEM_QTY |

### Sign-off Tablosu

| Kolon (Workcube schema) | Önerilen Class | DBA | PO |
|---|---|---|---|
| `EMPLOYEES_SALARY.M1..M12` | analytical | ☐ | ☐ |
| `EMPLOYEES_SALARY.MONEY` | currency (nvarchar→decimal cast PR #200) | ☐ | ☐ |
| `ACCOUNT_ROW.NET_AMOUNT` | currency | ☐ | ☐ |
| `INVOICE_ROW.AMOUNT` | currency | ☐ | ☐ |
| `EMPLOYEES_IN_OUT.SALARY_BRUT` | currency | ☐ | ☐ |
| (+ ek kolonlar — DBA listeden çıkaracak) | ☐ | ☐ | ☐ |

---

## D. Timezone ERP DBA Approval

Workcube datetime kolonların timezone semantiği:

| Soru | Cevap |
|---|---|
| UTC vs Europe/Istanbul | ☐ UTC / ☐ Istanbul / ☐ Hybrid |
| DST handling | ☐ Automatic / ☐ Manual override |
| `workcube-schema.json` timezone_hint field | ☐ Mevcut / ☐ Eklenecek |

### Kritik Kolonlar

- `*.RECORD_DATE` → ☐ Onaylı
- `*.UPDATE_DATE` → ☐ Onaylı
- `*.ACTION_DATE` → ☐ Onaylı
- `EMPLOYEES_IN_OUT.START_DATE / FINISH_DATE` → ☐ Onaylı

---

## E. ADR-0005 §6 Amendment Template

Annex 2A SEAL kararı sonrası `docs/adr/0005-dual-datasource-reporting.md` sonuna eklenecek:

```markdown
## §6 Faz 16.1 Annex 2A SEAL — <YYYY-MM-DD>

### Karar
Annex 2A (`docs/migration/report-source-annex.yaml`) **SEALED**:
- 32 sourceQuery + direct_source report `manually_validated: true`
- 44 (veya gerçek N) tablo authority mapping finalize
- Float semantic_class triple-sign-off complete
- Timezone ERP DBA approval complete

### Onay (Operator Action)
- DBA (Workcube): @<dba-handle>
- Product Owner: @<po-handle>
- ERP DBA (timezone): @<erp-dba-handle>
- Codex governance review: thread `019eXXXX-...`

### Etkisi
- Adım 11.5 prod cutover blocker kaldırılır (`REPORT_MSSQL_ENABLED=true`)
- Faz 17 Workcube decommission planlaması başlar
- ETL pipeline (Adım 12 etl-worker) source-of-truth contract'ı SEAL'a göre
  finalize

### Reference
- [Adım 13 runbook](../runbooks/adim-13-faz-16-1-annex-2a-seal.md)
- [SEAL DBA packet](../runbooks/adim-13-seal-dba-packet.md)
- [report-source-annex.yaml](../migration/report-source-annex.yaml)
- Codex thread `019e2a83` (plan-time istişare; agent paralel scope kararı)
```

---

## F. Annex 2A Status Flip + PR

E adımı tamamlanınca:

```bash
# Status flip:
yq -i '._meta.status = "SEALED" | ._meta.seal_state = "SEALED" | ._meta.sealed_at = now | ._meta.sealed_by = "<dba-handle>+<po-handle>"' \
  docs/migration/report-source-annex.yaml

# Commit + PR:
git checkout -b docs/faz-16-1-annex-2a-seal
git add docs/migration/report-source-annex.yaml docs/adr/0005-dual-datasource-reporting.md
git commit -m "docs(annex-2a): faz 16.1 seal — 8 pending validated, 44 tablo authority finalize"
git push -u origin docs/faz-16-1-annex-2a-seal

gh pr create --base main \
  --title "docs(annex-2a): Faz 16.1 SEAL — 8 sourceQuery validated, 44 tablo authority finalize" \
  --body "Adım 13 SEAL — Codex governance review thread <id>; cross-AI consensus."
```

Cross-AI peer review (HARD RULE): Codex governance review thread başlat. Codex AGREE sonrası squash merge.

---

## Toplam Effort

| Adım | DBA | PO | ERP DBA | Claude | Toplam (gerçek-zaman) |
|---|---:|---:|---:|---:|---:|
| A | 2-4 saat | - | - | - | 2-4 saat |
| B | 1 saat | 1 saat | - | - | 1-2 saat (paralel) |
| C | 30 dk | 30 dk | - | - | 30-60 dk (paralel) |
| D | - | - | 30 dk | - | 30 dk |
| E | - | - | - | 30 dk | 30 dk |
| F | 5 dk | 5 dk | - | 10 dk | 15 dk |
| **Toplam** | **3-4 saat** | **1.5 saat** | **30 dk** | **40 dk** | **~5-8 saat** |

**Kritik path**: A (DBA SQL review) — diğer adımlar paralel olabilir.

---

## Adım 11.5 Bağımlılığı

SEAL yeşillendiğinde Adım 11.5 prod cutover hazır:

```bash
# Önkoşul: SEAL PR merged
kubectl --context k3d-prod -n platform-prod patch configmap report-service-config \
  --type merge -p '{"data":{"REPORT_MSSQL_ENABLED":"true"}}'
kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service
```

Bu komutu agent çalıştırabilir (Pre-Production Full Authority + kullanıcı açık onay).

---

## Notlar

- DBA review olmadan annex 2A SEAL yapılamaz — agent yetkisi DIŞINDA domain knowledge
- Bu doc DBA + PO için **tek sayfa** — runbook detay için `adim-13-faz-16-1-annex-2a-seal.md`
- Codex 019e2a83 önerisi: agent operator action zincirini bekletip paralel scope (PR-D full + Adım 12) ilerletir

## Cross-AI

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e2a83-0be9-7a71-a6b1-29ad51c83603 (plan-time)
verdict: agree (DBA packet template approved)
```
