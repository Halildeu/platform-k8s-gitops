# RUNBOOK – Çalışma Kılavuzu Şablonu

ID: RB-<servis>  
Service: <servis-adı>  
Status: Draft | Verified | In-Use  
Owner: <isim>

Not: Aşağıdaki başlıklar ve sıralama **zorunludur**. Yeni bir runbook
yazılırken bu H2 başlıkları ve numaraları bire bir korunmalı; agent sadece bu
başlıkların altını doldurabilir. Özellikle:
- `4. GÖZLEMLEME / LOG / METRİKLER`
- `5. ARIZA DURUMLARI VE ADIMLAR`
- `7. LİNKLER (İSTEĞE BAĞLI)`
bölümleri **boş bırakılmamalıdır**; her runbook log/metric referanslarını, en az
bir arıza senaryosunu ve ilgili doküman linklerini içermelidir.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Servisin nasıl işletileceğini tarif etmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Hangi servis/uygulama için geçerli?
- Ortamlar (prod/stage/test vb.) ve sorumlu ekip(ler).
- İlgili SLO/SLA’ların kısa özeti (detay için SLO-SLA.md’ye referans verilebilir).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Nasıl start edilir?
- Nasıl restart edilir?
- Durdurma / bakım moduna alma adımları.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Hangi log index’lerine bakılır? (örn. `logs-<servis>-*`)
- Hangi dashboard / metrik panelleri kullanılır? (örn. Grafana panosu adı).
- Temel health check ve kritik metrikler (örn. error rate, latency, availability).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – adım adım çözüm (Given/When/Then benzeri kısa tanım + operasyon adımları).
- [ ] Arıza senaryosu 2 – adım adım çözüm.
- Gerekirse ek senaryolar aynı formatta eklenir.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Operasyonel olarak en kritik notlar.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- TECH-DESIGN: docs/02-architecture/services/<servis>/TECH-DESIGN-*.md
- STORY: docs/03-delivery/STORIES/STORY-XXX-*.md
- ACCEPTANCE: docs/03-delivery/ACCEPTANCE/AC-XXX-*.md
- SLO/SLA: docs/04-operations/SLO-SLA.md
- Monitoring: docs/04-operations/MONITORING/…
- Legacy runbook veya ek referanslar (varsa).
