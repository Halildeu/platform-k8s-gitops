# STORY – Story Şablonu

ID: STORY-XXXX-<slug>  
Epic: EPIC-XXX  
Status: Planned | In-Progress | Done  
Owner: <isim>  
Risk_Level: low|medium|high  
Upstream: PB-XXXX, PRD-XXXX  
Downstream: AC-XXXX, TP-XXXX, ADR-XXXX, RB-<servis>

Not: Aşağıdaki başlıklar ve sıralama **zorunludur**. Yeni bir Story yazılırken
bu H2 başlıkları ve numaraları bire bir korunmalı; agent sadece bu başlıkların
altını doldurabilir.

Kural:
- `AC-XXXX` ve `TP-XXXX` numarası, `STORY-XXXX` ile aynı olmalıdır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- İş hedefi ve beklenen çıktılar.

-------------------------------------------------------------------------------
2. TANIM
-------------------------------------------------------------------------------

- Kısa story tanımı (rol/istek/fayda):
  - Bir <rol> olarak, <istek> istiyorum; böylece <fayda>.

-------------------------------------------------------------------------------
3. KAPSAM VE SINIRLAR
-------------------------------------------------------------------------------

- Neler dahil, neler kapsam dışı?

-------------------------------------------------------------------------------
4. ACCEPTANCE KRİTERLERİ
-------------------------------------------------------------------------------

- [ ] Given ..., When ..., Then ...  
- [ ] Given ..., When ..., Then ...

-------------------------------------------------------------------------------
5. BAĞIMLILIKLAR
-------------------------------------------------------------------------------

-.RELATED PRD, TECH-DESIGN, diğer story’ler.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Story’nin 2–3 maddelik özeti.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Story: docs/03-delivery/STORIES/STORY-XXX-*.md
- Acceptance: docs/03-delivery/ACCEPTANCE/AC-XXX-*.md
- Test Plan: docs/03-delivery/TEST-PLANS/TP-XXX-*.md
- ADR: docs/02-architecture/services/<servis>/ADR/ADR-XXX-*.md
