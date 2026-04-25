# PRD – Ürün Gereksinim Dokümanı Şablonu

ID: PRD-XXX-<feature>

Not: Aşağıdaki başlıklar ve sıralama **zorunludur**. Yeni bir PRD yazılırken bu
H2 başlıkları ve numaraları bire bir korunmalı; agent sadece bu başlıkların
altını doldurabilir.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Feature/ürünün amacı ve iş hedefi.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Dahil olan akışlar, kullanıcı tipleri, servisler.

-------------------------------------------------------------------------------
3. KULLANICI SENARYOLARI
-------------------------------------------------------------------------------

- Senaryo 1
- Senaryo 2

-------------------------------------------------------------------------------
4. DAVRANIŞ / GEREKSİNİMLER
-------------------------------------------------------------------------------

- Fonksiyonel gereksinimler
- Non-functional gereksinimler

-------------------------------------------------------------------------------
5. NON-GOALS (KAPSAM DIŞI)
-------------------------------------------------------------------------------

- Bu release’te özellikle yapılmayacaklar.

-------------------------------------------------------------------------------
6. ACCEPTANCE KRİTERLERİ ÖZETİ
-------------------------------------------------------------------------------

- PRD ile uyumlu yüksek seviye kriterler.

-------------------------------------------------------------------------------
7. RİSKLER / BAĞIMLILIKLAR
-------------------------------------------------------------------------------

- Diğer sistemlere/ekiplere bağımlılıklar, riskler.

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

- Feature’ın 2–3 maddelik özeti.

-------------------------------------------------------------------------------
9. LİNKLER / SONRAKİ ADIMLAR
-------------------------------------------------------------------------------

- İlgili PB / STORY / ACCEPTANCE / TEST PLAN / API dokümanları (varsa).

-------------------------------------------------------------------------------
10. DELIVERY ITEMS (SSOT)
-------------------------------------------------------------------------------

Bu bölüm **ürün odaklı** delivery breakdown için deterministik SSOT’tur.
Generator bu JSON’u okuyarak:
- Default: `1 delivery_item -> 1 STORY` (vertical slice)
- Yalnız `split_by=stream` verilirse: `streams` başına STORY üretir.

Kurallar:
- `slug` kebab-case olmalı (dosya slug’ı olarak kullanılır).
- `optional_docs` yalnız ihtiyaç olduğunda eklenir (tahmin yok). `ADR` istenirse ADR ID otomatik seçilir.

```json
{
  "ssot": "PRD_DELIVERY_ITEMS_V1",
  "delivery_items": [
    {
      "id": "DI-0001",
      "title": "Örnek vertical slice",
      "slug": "example-slice",
      "split_by": "none",
      "streams": [],
      "services": [],
      "story_id": null,
      "story_ids": null,
      "spec": null,
      "risk_level": "medium",
      "optional_docs": []
    }
  ]
}
```
