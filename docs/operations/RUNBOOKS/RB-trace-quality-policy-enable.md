# RB-trace-quality-policy-enable – Trace Quality Hard Gate Enable (Policy Flip)

ID: RB-trace-quality-policy-enable  
Service: docs-ci  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Trace kalite eşiğini (refined ratio) CI’da **hard gate** (blocking) haline getirmeyi
kod değişikliği yapmadan, yalnızca policy SSOT üzerinden yönetmek.

Bu runbook’un hedefi: “2 hafta sonra enable yapmayı unutmayalım” sorununu sıfırlamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Policy SSOT: `docs-ssot/03-delivery/SPECS/trace-quality-policy.v1.json`
- Checker: `scripts/check_trace_quality.py` (policy-aware)
- Policy schema checker: `scripts/check_trace_quality_policy.py`
- CI gate: `.github/workflows/doc-qa.yml` içinde çalışır.

Not:
- `enabled=false` iken raporlayıcıdır (non-blocking).
- `enabled=true` iken eşikler sağlanmazsa CI FAIL eder (blocking).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 Enable (Hard Gate Aç)

1) Policy dosyasını aç: `docs-ssot/03-delivery/SPECS/trace-quality-policy.v1.json`
2) `enabled: true` yap.
3) (Opsiyonel) `min_refined_ratio` değerini güncelle.
4) PR aç ve CI doc-qa sonucunu kontrol et.

### 3.2 Disable (Hard Gate Kapat)

1) Aynı dosyada `enabled: false` yap.
2) PR aç ve CI PASS olmalı.

### 3.3 Rollout Stratejisi (Önerilen)

Aşamalı geçiş (öneri):
- Hafta 0–2: `enabled=false` (sadece rapor)
- Hafta 2: `enabled=true` + düşük eşik (örn. %20)
- Hafta 4: eşiği artır (örn. %35)
- Hafta 6+: eşiği artır (örn. %50+)

Kural:
- Eşik artırımı bir sprint hedefi gibi ele alınır.
- Eşik artarsa, “refined mapping” backlog’u aynı sprintte planlanır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- CI “Step Summary”:
  - `Trace Quality Report` başlığında refined oranı ve per-trace dağılım görünür.
- PR checks:
  - `doc-qa` çalışır; `enabled=true` ise eşik altı durumlarda FAIL beklenir.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

| Durum | Belirti | Neden | Çözüm |
|---|---|---|---|
| CI FAIL (refined_ratio düşük) | `check_trace_quality` FAIL | mapping_quality düşük | TRACE satırlarında coarse→refined dönüşümü planla |
| mapping_quality kolonu eksik | raporda uyarı veya enabled=true iken FAIL | eski trace | TRACE header migrate et |
| Policy schema FAIL | `check_trace_quality_policy` FAIL | JSON bozuk | JSON’ı schema-lite kurala göre düzelt |

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

Hard gate açma/kapatma yalnızca policy flip ile yapılır:
- `enabled: true/false`
- `min_refined_ratio` kademeli artırılır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Policy: `docs-ssot/03-delivery/SPECS/trace-quality-policy.v1.json`
- Checker: `scripts/check_trace_quality.py`
- Policy checker: `scripts/check_trace_quality_policy.py`
- CI: `.github/workflows/doc-qa.yml`

