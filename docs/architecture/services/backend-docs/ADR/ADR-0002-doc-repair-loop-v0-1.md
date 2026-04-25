# ADR-0002 – Doc-Repair Loop v0.1 (Deterministik Doküman Onarımı)

ID: ADR-0002  
Status: Proposed  
Tarih: 2025-12-24  
Sahip: Halil K.

## Context

- Repo’da dokümantasyon kalite kapısı (doc-qa) deterministik çalışır:
  - `render-flow --check` + template/ID/konum + acceptance evidence + zincir kontrolleri.
- `docflow_next` bu kontrolleri STORY bazında koşar ve özet üretir:
  - `decision`: RUN/SKIP/STOP
  - `result`: PASS/FAIL/BLOCKED
  - `blockedReason`: serbest metin (preflight + script note’ları).
- Doküman eksikliği veya küçük format hataları, geliştirme akışını gereksiz yere bloklayabilir.

Hedef: “doküman eksik/uyumsuzsa” küçük ve güvenli patch’lerle, otomatik ve deterministik şekilde
doc-qa PASS seviyesine geri dönebilen bir onarım döngüsü (Doc-Repair Loop) tanımlamak.

## Decision

- Doc-Repair Loop v0.1 tanımı:
  - “AI” serbest doküman yazarı değil; **doc-qa PASS için onarım işçisi** olarak çalışır.
  - Amaç: gate’i bypass etmek değil; gate’in beklediği minimum kontratı tamamlamak.
- Onarım tetikleyicileri iki kaynaktan okunur:
  1) `docflow_next` summary (`decision/result/blockedReason`) → kanonik reason code’a normalize edilir.
  2) doc-qa script stdout/exit-code → parse edilerek aynı reason catalogue’a bağlanır.
- Guardrail (v0.1):
  - Allowlist: öncelik `docs/**`; gerekirse `scripts/**` yalnız parse/normalize/plan üretimi için.
  - Patch-first: şablon başlık sırası, meta alanları, linkler, ID uyumu, evidence gibi küçük düzeltmeler.
  - Limitli değişiklik: büyük rewrite yok; değişiklik boyutu ve dosya sayısı üst limitlidir.
  - PASS kontratı: Doc-Repair “tamamlandı” sayılması için doc-qa PASS gerekir.

## Consequences

Artılar:
- Deterministik ve tekrarlanabilir bir “doc repair” akışı oluşur.
- Küçük doküman hataları hızlı kapanır; akışta blokaj azalır.
- Otomasyonun ürettiği reason/plan çıktıları izlenebilirliği artırır.

Eksiler / Riskler:
- `blockedReason` serbest metin olduğu için normalize katmanı doğru tasarlanmalıdır.
- v0.1’de reason coverage eksik kalabilir; zamanla genişletilmesi gerekir.
- Yanlış/eksik onarım, “PASS” yerine ek churn yaratabilir; bu yüzden allowlist + limit zorunludur.

## Linkler

- SPEC: `docs/03-delivery/SPECS/SPEC-0009-doc-repair-loop-v0-1.md`
- Reason map (SSOT): `docs-ssot/03-delivery/SPECS/doc-repair-reason-map.v0.1.json`
- Plan generator (plan-only): `scripts/doc_repair_plan.py`
- Runbook: `docs/04-operations/RUNBOOKS/RB-doc-repair-loop.md`
- Gate: `.github/workflows/doc-qa.yml`
- Engine: `scripts/docflow_next.py`
