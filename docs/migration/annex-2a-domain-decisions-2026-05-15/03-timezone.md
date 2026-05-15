# Timezone — Agent Proposal (2026-05-15)

> **Proposal-only.** Sign-off için **ERP DBA yazılı onay** (`mssql-pg-data-contract.md` §493 acceptance criterion). Imzalar gelene kadar Annex 2A timezone alanı belirsiz kalır.

## Bağlam

Workcube MSSQL canonical schema'sında datetime kolonları için **timezone semantik belirsizliği** var. ERP işletmecisi (DBA) MSSQL `datetime2` kolonlarının hangi timezone'da yazıldığını bilmeli:

- **UTC** (server timezone'dan bağımsız ISO storage)
- **Europe/Istanbul** (Türkiye yerel saati, DST davranışı tarihçe + bugün farklı)
- **Hybrid** (bazı kolon UTC, bazı yerel — risky)

Postgres tarafında `report-service` migration'da `timestamptz` kullanır (PostgreSQL native UTC + tz metadata). Workcube tarafından gelen `datetime2` → PG `timestamptz` conversion sırasında kaynak tz **kesin bilinmeli**, aksi halde `±3 saat drift` veya `2016 Türkiye DST iptal` artifact'leri ortaya çıkar.

## 17 unique datetime kolon (31 raporda)

| Column | Reports | Heuristik Anlam | ERP DBA Karar |
|---|---|---|---|
| `RECORD_DATE` | 12 | Kayıt tarihi (audit log) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `ACTION_DATE` | 9 | İşlem tarihi (transaction) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `INVOICE_DATE` | 4 | Fatura tarihi (regülatör) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `DUE_DATE` | 3 | Vade tarihi (regülatör) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `START_DATE` | 3 | Başlangıç (kontrat/dönem) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `END_DATE` | 3 | Bitiş (kontrat/dönem) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `WORK_DATE` | 2 | Çalışma günü (puantaj) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `LEAVE_START` | 2 | İzin başlangıç | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `LEAVE_END` | 2 | İzin bitiş | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `CHEQUE_DATE` | 2 | Çek tarihi | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `EXPENSE_DATE` | 2 | Masraf tarihi | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `BANK_ACTION_DATE` | 2 | Banka işlem tarihi | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `STOCK_FIS_DATE` | 1 | Stok fişi tarihi | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `IN_DATETIME` | 1 | Giriş zamanı (PDKS) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `OUT_DATETIME` | 1 | Çıkış zamanı (PDKS) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `HIRE_DATE` | 1 | İşe alım tarihi | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |
| `TERMINATION_DATE` | 1 | Çıkış tarihi (HR) | ☐ UTC · ☐ Europe/Istanbul · ☐ Hybrid |

## Agent Proposal — `Europe/Istanbul` global

Workcube ERP yerel kurum sistemi olduğu için **default proposal**: tüm 17 kolon `Europe/Istanbul`.

Ek tartışma noktaları (ERP DBA değerlendirir):

1. **DST handling**: Türkiye 2016'da DST'yi kaldırdı (kalıcı UTC+3). Pre-2016 tarihler için DST handling gerekiyor mu?
   - Agent öneri: `dst_aware = true` pre-2016, `dst_aware = false` post-2016
   - ERP DBA karar: ☐ approve · ☐ alternative

2. **Cross-tenant master ref tarihleri** (örn. SETUP_DOCUMENT_TYPE.CREATED_AT): bu tablolar tüm tenant'lar arası paylaşılır; yine `Europe/Istanbul` mı yoksa `UTC` mi? Database server timezone canonical mı?
   - Agent öneri: master tablolar da `Europe/Istanbul` (sunucu zaten Istanbul TZ)
   - ERP DBA karar: ☐ approve · ☐ alternative

3. **PDKS giriş-çıkış (`IN_DATETIME`, `OUT_DATETIME`)**: vardiya raporları için kritik. Server time recorded yes/no?
   - Agent öneri: client side recorded → `Europe/Istanbul`
   - ERP DBA karar: ☐ approve · ☐ alternative

4. **Per-column istisna**: yukarıdaki 17 kolondan herhangi biri UTC veya farklı bir tz kullanıyor mu?
   - Liste: __________________________________________________

## Acceptance kriterleri

- 17/17 satırda **bir** tz seçili
- DST handling kararı belirlenmiş (DST aware vs flat UTC+3)
- Per-column istisnalar listelenmiş (boş kabul edilebilir)
- ERP DBA imzası aşağıda

## Sign-off

```
ERP DBA          : __________________________________________  Tarih: __________
```

Imzalar geldikten sonra agent SEAL flip PR'ında `_meta.timezone_signoff: { policy: <decision>, signed_by: <name>, signed_at: <date> }` alanını ekler.
