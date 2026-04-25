# SPEC – Specification / Kontrat Şablonu

ID: SPEC-XXXX-<slug>  
Status: Draft | In Progress | Done  
Owner: <isim|@team/...>  
Upstream: PB-XXXX, PRD-XXXX, BM-XXXX, BENCH-XXXX, TRACE-XXXX (varsa)  
Downstream: STORY-XXXX, ADR-XXXX, INTERFACE-CONTRACT-XXX, RB-XXX (varsa)

Not: Aşağıdaki numaralı H2 başlıkları (1–5) **zorunludur**. Bu doküman:
- “ne / hangi sınırlar / hangi kontrat” SSOT’tur,
- “nasıl implement edilecek” detaylarını (dosya yolu + değişiklik) **Tech-Design**’a,
- test senaryolarını **AC/TP** dokümanlarına bırakır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Bu SPEC’in SSOT olarak tanımladığı konu (1–3 madde).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- In-scope: hangi alt akışlar/entitiler/kontrat yüzeyi.
- Out-of-scope: (varsa) özellikle yapılmayacaklar / dışarıda bırakılanlar.

-------------------------------------------------------------------------------
3. KONTRAT (SSOT)
-------------------------------------------------------------------------------

### Kaynaklar / Trace (varsa)

- PB / PRD / BM / BENCH / TRACE referansları.

### Platform Dependencies (None dahil)

- Bu kontratın çalışması için gereken shared capability’ler (örn. `SPEC-0014`).

### Domain / Policy Kontratı (MVP)

- Domain sınırları, minimum entity alanları, state/flow, policy knobs.

### Güvenlik / Yetki (Need-to-know)

- AuthN/AuthZ beklentileri ve erişim sınırları.

### Audit / Evidence / Telemetry (Minimum)

- “Kim ne yaptı / kim neyi görüntüledi” ve minimum metrik/log seti.

### Failure Modes / Anti-patterns

- Top failure modes ve yapılmaması gerekenler.

-------------------------------------------------------------------------------
4. GOVERNANCE (DEĞİŞİKLİK POLİTİKASI)
-------------------------------------------------------------------------------

- Kontrat değişikliği sınıfları: breaking / non-breaking.
- Versiyonlama kuralı: breaking değişiklik → yeni `SPEC-XXXX`.
- Bu SPEC’in “kilitli SSOT” olup olmadığı ve değişiklik prosedürü.

-------------------------------------------------------------------------------
5. LİNKLER
-------------------------------------------------------------------------------

- İlgili dokümanlar (repo içi path).
