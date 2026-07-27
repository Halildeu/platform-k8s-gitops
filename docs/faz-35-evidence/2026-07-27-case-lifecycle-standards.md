# Faz 35 Etik Speak — Dava yaşam döngüsü, standart hizalaması (2026-07-27)

> **Amaç:** İhbar yaşam döngüsünü AB 2019/1937 + ISO 37002 ile hizalamak ve bunu canlıda ölçmek. ES-301A (veri modeli + geçiş makinesi) ve ES-301B (kapanışın ihbarcıya ulaşması).

## Başlangıç ölçümü — döngü hiç sonuçlanmamıştı

k3d-test, `ethics_service` şeması, 2026-07-27:

```
IN_REVIEW | 29
NEW       | 131
```

160 dava, **sıfır kapanış**. En eski açık dava 6 günlük.

`ethics_cases` kolonları tam olarak şunlardı:

```
id, org_id, product_id, status, assigned_to, version, created_at, updated_at
```

## Standarda karşı boşluk

| ISO 37002 aşaması | Standart gereği | Bulunan |
|---|---|---|
| Receive | güvenli kanal, anonim seçenek, kayıt | ✅ canlı |
| **Acknowledge** | **7 gün** içinde alındı teyidi (m.9/1-b) | ❌ `acknowledged_at` kolonu yok |
| Assess / Address | ön değerlendirme ile soruşturmanın ayrılması | ⚠️ `IN_REVIEW` ikisini tek kelimeye indiriyor |
| **Conclude** | sonuç kaydı + geri bildirim **≤3 ay** (m.9/1-f) | ❌ `outcome` yok, `closed_at` yok |
| Record-keeping | m.18 kayıt | ✅ WORM + audit outbox |

Geçiş kuralı da yoktu: `case_handler` yetkisi olan biri `CLOSED → NEW` dahil herhangi bir duruma atlayabiliyordu — soruşturulmuş ve sonuçlanmış bir dosya, hiç dokunulmamış gibi görünür hale geliyordu.

## Yapılan

| PR | ne |
|---|---|
| platform-backend#950 | statü sözlüğü + geçiş makinesi + `acknowledged_at` / `outcome` / `closed_at` + backfill |
| platform-backend#952 | V9 sıralama düzeltmesi + göç-öncesi-veri testi |
| platform-backend#954 | kapanış ihbarcıya ulaşmadan tamamlanmıyor |
| platform-web#1028 | panel: yasak geçiş düğmesi yok, kapanış sonuç istiyor, 7 gün sayacı |
| platform-web#1029 | panel: ihbarcıya iletilecek kapanış metni |
| platform-k8s-gitops#2973, #2977 | promosyon |

### Sözlük ve geçişler

`status ∈ {NEW, ASSESSING, INVESTIGATING, CLOSED}`. İleri yönlü; tek geri yol `CLOSED → ASSESSING` ve gerekçe zorunlu. `CLOSED → NEW` yok.

`outcome ∈ {SUBSTANTIATED, PARTIALLY_SUBSTANTIATED, UNSUBSTANTIATED, OUT_OF_SCOPE, REFERRED, WITHDRAWN}` — yalnız `CLOSED`'da ve orada zorunlu, DB kısıtı ve uygulama katmanı birlikte.

### Teyit bir alan değil, bir eylem

`acknowledged_at` API'den yazılamıyor. İhbarcının gördüğü ilk personel mesajı gönderildiğinde sistem damgalıyor — kapanış mesajı dahil. Ayrıca set edilebilen bir alan olsaydı, servis m.9/1-b'ye uyduğunu raporlarken ihbarcı hiçbir şey duymamış olabilirdi.

### İhbarcı sözleşmesi değişmedi

`ASSESSING` ve `INVESTIGATING` dışarıdan ikisi de `IN_REVIEW`. İç sözlük genişledi; ihbarcının gördüğü `NEW | IN_REVIEW | CLOSED` sabit kaldı. Sözleşme testi bunu **tüm sözlük üzerinde** doğruluyor, projeksiyon yazıldığında var olan statüler üzerinde değil.

## Canlı kabul

`ethics-service` `sha256:065b200a…` (backend `0d9d83bf`), yönetici `sha256:fdad0d78…` (web `639b6983`).

### Migration 160 gerçek satıra ulaştı

```
flyway V9: success=t
yeni kolonlar: acknowledged_at, closed_at, outcome

  ASSESSING -> 29
  NEW       -> 131
  IN_REVIEW kalan (beklenen 0): 0
  teyit damgasi olan dava: 29
  ihbarci-gorunur yaniti olup teyitsiz (beklenen 0): 0
  yalniz ic notu olup teyit almis (beklenen 0): 0
```

Son iki satır backfill'i iki yönden kilitliyor.

### İhbarcı iç aşamayı görmüyor — gerçek bir alındı ile

```
personel gorur : ASSESSING
ihbarci gorur  : IN_REVIEW
```

### Teyit

```
once teyit            : YOK
ic not (HTTP 201)     -> teyit: YOK
ihbarci yaniti (201)  -> teyit: 2026-07-27 09:13:20.210562+00
denetim               : ethics.case.acknowledged
```

### Geçiş ve kapanış kuralları

| adım | sonuç |
|---|---|
| sonuçsuz kapanış | 400 `CASE_OUTCOME_REQUIRED` |
| tanımsız sonuç | 400 `CASE_OUTCOME_INVALID` |
| sonuçla kapanış | 200 — `status=CLOSED outcome=UNSUBSTANTIATED closed_at=…` |
| `CLOSED → NEW` | 409 `CASE_TRANSITION_NOT_ALLOWED` |
| gerekçesiz yeniden açma | 400 `CASE_REOPEN_REASON_REQUIRED` |
| gerekçeli yeniden açma | 200 — sonuç temizlendi, `ethics.case.reopened` denetimde |
| denetimde ham kimlik | 0 kayıt |

### Sunulan yönetici paketi

`/ethic/assets/index-nHSctZrO.js` (186 985 bayt) içeriğinden: `Değerlendirmede`, `Soruşturmada`, `Sonucu kaydet ve kapat`, `Yeniden açma gerekçesi`, `Alındı teyidi` **var**; eski `İncelemeye al` **yok**.

İhbarcı UI'ı dağıtım sonrası temiz: `GET /` + bundle + css 200, konsol hatası yok.

## Yol boyunca bulunan kusur

İlk promosyon canlıda migration hatasıyla düştü:

```
ERROR: new row for relation "ethics_cases" violates check constraint "ck_ethics_case_status"
Detail: Failing row contains (…, ASSESSING, …)   Line: 43
```

Eski kısıt backfill'in ardında düşürülüyordu; UPDATE hâlâ eski sözlüğe bağlıydı ve yazmak için var olduğu değeri yazamıyordu.

**Boş veritabanında o UPDATE hiçbir satırla eşleşmez** — kısıt hiç zorlanmaz, sıralama önem kazanmaz. 145 test, gerçek PostgreSQL koşumu dahil, hepsinin fixture'ı taze şemaydı. Veri göçü, üzerinde veri olmayan bir veritabanında başarısız olamaz.

`CaseLifecycleMigrationTest` bu kör noktayı kapatıyor: göçü V8'e kadar koşar, eski sözlükte gerçek satırlar tohumlar, sonra V9'u çalıştırır. Eski sıralamayla canlıdakinin aynısı hatayla düşer.

Kesinti olmadı (rolling update eski pod'u tuttu), kısmi göç olmadı (PG'de DDL işlemsel). `ethics-evidence-worker` 0/1'e düşmüştü, `rollout undo` ile geri getirildi ve düzeltilmiş promosyonla ileri sarıldı.

## Kanıtlamıyor

- **Yönetici panelinin etkileşimli tarayıcı doğrulaması yapılmadı.** Panel Keycloak girişi ister. Kanıtlanan: sunulan paket yeni kodu içeriyor + aynı davranış canlı API üzerinden ölçüldü. Kanıtlanmayan: düğmelerin gerçek bir oturumda tıklanması.
- 3 aylık geri bildirim penceresinin **ölçülmesi** yapılmadı — #882 (ES-301). Bu iş yalnız pencerenin iki ucunu kaydedilebilir hale getirdi.
- Prod ortamı değişmedi.

## Kalıntı

Yeniden açma gerekçesi denetim kaydına düz metin yazılıyor; o tablodaki diğer her şey sha256. Gerekçenin kaydedilmesi doğru — denetim izinin amacı bu — ama serbest metin olduğu için kişisel veri içerebilir. Tablo tek biçimli varsayılmamalı; saklama/gizlilik tarafına (platform-backend#884, gitops#2650) not düşüldü.
