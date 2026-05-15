# Migration Action Matrix — Agent Proposal (2026-05-15)

> **Proposal-only.** Sign-off için **DBA + PO**. Imzalar gelene kadar Annex 2A `migration_action_default` alanı `pending_annex` kalır.

## Faz 17 niyet

> Workcube decommission. Tüm reporting yükü `report-service` üzerinden Postgres'e migrate edilecek.

**Default proposal**: `migrate` (31/31). İstisna eklenmesi gerekirse DBA/PO bu satırı `exclude` veya `keep_workcube` olarak değiştirir + gerekçe yazar.

## 31 report karar matrisi

| # | Report | Category | Agent Proposal | DBA / PO Decision | Rationale (eğer agent != karar) |
|---|---|---|---|---|---|
| 1 | fin-alacak-yaslandirma | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 2 | fin-banka-hareketleri | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 3 | fin-borc-yaslandirma | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 4 | fin-butce-gerceklesen | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 5 | fin-cari-hareketler | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 6 | fin-cari-islemler | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated) |
| 7 | fin-cari-mutabakat | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 8 | fin-cek-senet | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 9 | fin-cek-vade-takip | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 10 | fin-fatura-satirlari | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated) |
| 11 | fin-faturalar | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 12 | fin-gerceklesen-maliyet | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 13 | fin-kasa-hareketleri | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 14 | fin-kaynak-eslesme | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated) |
| 15 | fin-masraf-detay | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated) |
| 16 | fin-muhasebe-detay | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated, 12 tablo) |
| 17 | fin-muhasebe-fisleri | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 18 | fin-nakit-akis-ozet | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 19 | fin-stok-fis-detay | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated) |
| 20 | fin-tutar-mutabakat | Finans | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated, 7 tablo) |
| 21 | hr-bordro-detay | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 22 | hr-compensation-detay | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | sourceQuery (DBA validated, 9 canonical) |
| 23 | hr-egitim-katilim | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 24 | hr-giris-cikis | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 25 | hr-izin-raporu | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 26 | hr-maas-gecmisi | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 27 | hr-maas-raporu | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 28 | hr-personel-listesi | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 29 | hr-puantaj | İnsan Kaynakları | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 30 | satis-ozet | Satış | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |
| 31 | stok-durum | Satış | `migrate` | ☐ approve · ☐ exclude · ☐ keep_workcube | |

## Karar enum tanımları

| Değer | Anlam |
|---|---|
| `migrate` | Faz 17 default. Postgres'e migrate edilecek, Workcube'dan kesilecek. |
| `exclude` | Legacy/deprecated. Migration scope dışında, deprecate edilecek. |
| `keep_workcube` | Cross-tenant master ref. Workcube'da kalmaya devam edecek (örn. company-level shared catalog). |

## Acceptance kriterleri

- 31/31 satırda **bir** checkbox seçili
- `approve` dışında karar → "Rationale" sütununda **gerekçe yazılı**
- DBA + PO imzaları aşağıda (electronic OK, commit author trail audit yeterli)

## Sign-off

```
DBA       : __________________________________________  Tarih: __________
PO        : __________________________________________  Tarih: __________
```

İmzalar geldikten sonra agent SEAL flip PR'ında `migration_action_default` alanını her satır için canonical karara çevirir.
