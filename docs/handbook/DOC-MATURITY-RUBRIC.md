# DOC-MATURITY-RUBRIC – Doküman Olgunluk Rubric’i (M1/M2/M3)

Bu doküman, `PROJECT-FLOW.tsv` içindeki `M_STORY / M_AC / M_TP` alanlarının ne anlama geldiğini
ve bu olgunlukların **nasıl “proxy” kriterlerle** değerlendirileceğini tanımlar.

Notlar:
- Bu bir **semantik puanlama / içerik skoru** değildir.
- Amaç: dokümanların **denetlenebilir ve otomasyona uygun** bir minimum olgunluğa sahip olmasını sağlamak.
- v0.1’de rubric checker **non-blocking** çalışır (raporlar, CI’yı kırmaz).

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- “Olgunluk” seviyelerini (M1/M2/M3) doküman tipine göre **ortak bir sözleşme** olarak tanımlamak.
- `docflow_next` otomasyonunun seviye tavanını (`maxAllowedM=min(M_STORY,M_AC,M_TP)`) doğru yorumlamasını sağlamak.
- “Declared (Flow) vs Detected (Proxy)” farklarını görünür kılmak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Delivery:
  - Story: `docs/03-delivery/STORIES/STORY-*.md`
  - Acceptance: `docs/03-delivery/ACCEPTANCE/AC-*.md`
  - Test Plan: `docs/03-delivery/TEST-PLANS/TP-*.md`
- Operations:
  - Runbook: `docs/04-operations/RUNBOOKS/RB-*.md`

-------------------------------------------------------------------------------
3. KAVRAMLAR
-------------------------------------------------------------------------------

- **Declared maturity (Flow):** `PROJECT-FLOW.tsv` satırındaki `M_STORY/M_AC/M_TP` değerleri.
- **Detected maturity (Proxy):** `scripts/check_doc_maturity_rubric.py` tarafından, doküman içeriğinden
  heuristik olarak çıkarılan seviye.
- **Proxy kriter:** makinece ölçülebilen (başlık, checklist sayısı, belirli bölüm doluluğu gibi) sinyaller.

-------------------------------------------------------------------------------
4. RUBRIC (M1/M2/M3)
-------------------------------------------------------------------------------

Bu rubric “minimum olgunluk” içindir. Bir dokümanın yüksek kalite olması için yeterli değildir; sadece
olgunluğun **deterministik** ve **denetlenebilir** olmasını hedefler.

### 4.1 STORY (M_STORY)

M1 (kontrat hazır)
- [ ] `ID:` meta var ve dosya adıyla uyumlu (stem prefix).
- [ ] Zorunlu başlıklar var: Amaç / Tanım / Kapsam / Acceptance / Bağımlılıklar / Özet.
- [ ] En az: Amaç + Tanım + Acceptance bölümleri boş değil.

M2 (test edilebilirlik proxy)
- [ ] M1.
- [ ] Acceptance kriterleri checklist’i en az 2 madde.
- [ ] Kapsam/Sınırlar bölümünde “dahil/kapsam dışı” gibi sınırlar yazılmış.
- [ ] Bağımlılıklar bölümünde en az 1 somut referans var (STORY/PRD/SPEC/ADR/RB veya docs path).

M3 (operate-ready proxy)
- [ ] M2.
- [ ] “Linkler” bölümünde ilgili AC/TP ve (varsa) Runbook referansı var.
- [ ] Risk/varsayım notları (proxy): dokümanda “risk/varsayım” benzeri notlar var.

### 4.2 ACCEPTANCE (M_AC)

M1 (kabul kriterleri hazır)
- [ ] `ID:` meta var ve `Story:` referansı mevcut.
- [ ] Given/When/Then senaryoları bölümü var ve en az 1 senaryo checklist maddesi var.

M2 (kanıtlanabilirlik proxy)
- [ ] M1.
- [ ] En az 2 senaryo checklist maddesi.
- [ ] En az 1 “Kanıt/Evidence” referansı (path/komut/runbook) mevcut.

M3 (ops + edge-case proxy)
- [ ] M2.
- [ ] En az 1 negatif/edge-case senaryosu (proxy: “negatif/hatalı/invalid” gibi).
- [ ] Operations/Runbook referansı mevcut.

### 4.3 TEST-PLAN (M_TP)

M1 (test planı hazır)
- [ ] `ID:` meta var ve `Story:` referansı mevcut.
- [ ] Test senaryoları özeti bölümü var ve en az 2 checklist maddesi var.

M2 (kapsam/çevre proxy)
- [ ] M1.
- [ ] En az 3 senaryo checklist maddesi.
- [ ] En az 1 negatif test maddesi (proxy: “negatif/hatalı/invalid”).
- [ ] “Çevre ve Araçlar” bölümü boş değil.

M3 (release/operate proxy)
- [ ] M2.
- [ ] Post-deploy doğrulama komutları var (smoke/healthcheck vb).
- [ ] Rollback adımı veya referansı var.

### 4.4 RUNBOOK (RB)

M1 (runbook temel)
- [ ] `ID:` meta var ve servis adı belirtilmiş.
- [ ] Başlatma/Durdurma adımları var.

M2 (gözlem + arıza adımları)
- [ ] M1.
- [ ] “Gözlemleme / Log / Metrikler” bölümü dolu.
- [ ] “Arıza Durumları ve Adımlar” bölümünde en az 1 checklist senaryosu var.

M3 (operasyon olgunluğu)
- [ ] M2.
- [ ] En az 2 arıza senaryosu.
- [ ] Linkler bölümünde ilgili Story/AC/Tech-Design/SLO gibi referanslar var.

-------------------------------------------------------------------------------
5. DETECTED M vs DECLARED M (PROJECT-FLOW)
-------------------------------------------------------------------------------

`PROJECT-FLOW.tsv` içindeki `M_STORY/M_AC/M_TP` değerleri “Declared” (beyan) seviyesidir.
`check_doc_maturity_rubric` ise dosya içeriğinden “Detected” (proxy) seviyeyi çıkarır.

v0.1’de mismatch’ler:
- CI’yı kırmaz (non-blocking).
- Raporlanır (uyumsuzluk görünür olur).

-------------------------------------------------------------------------------
6. CHECKER (NON-BLOCKING) KULLANIMI
-------------------------------------------------------------------------------

- Rapor:
  - `python3 scripts/check_doc_maturity_rubric.py --flow-path docs/03-delivery/PROJECT-FLOW.tsv`
- JSON çıktı (opsiyonel):
  - `python3 scripts/check_doc_maturity_rubric.py --flow-path docs/03-delivery/PROJECT-FLOW.tsv --json-out artifacts/doc-maturity/report.json`

-------------------------------------------------------------------------------
7. SINIRLAR
-------------------------------------------------------------------------------

- Bu rubric semantik kalite/derinlik ölçmez; yalnızca proxy kriter üretir.
- Bazı Story’ler için Runbook/rollback/post-deploy doğrulama gerekmeyebilir; bu durumda M3 hedefi “opsiyonel” olabilir.

