# ADR-0043 — Meeting Intelligence LLM Layer (`meeting-ai-service`): Provider Abstraction + Citation-First Output + KVKK Data-Flow

> **Status**: ACCEPTED (2026-06-20) — Faz 24 T-C Intelligence (`platform-ai` ai#162) PR-time ADR. Cross-AI provider-distinct: Codex `019ee7c9` REVISE→**AGREE/ACCEPTED** (citation entailment + redaction scope + payload allowlist + slice-citation-from-01 + domain-level contract absorbed). PR-llm-01 implementasyonu başlayabilir. **Gerçek cloud LLM çağrısı + meeting-service'e persist/UI çıktı, ADR-0030 ACCEPTED + hukuk review öncesi YASAK** (D7 gate).
>
> **Scope**: Faz 24 Meeting Intelligence'ın **asıl değer katmanı** — transcript → LLM özet/karar/aksiyon + **kaynaklı (citation'lı) çıktı**. Yalnız LLM Intelligence katmanını (`meeting-ai-service`) kapsar; KVKK boundary [ADR-0030](0030-kvkk-meeting-intelligence-boundary.md) + host topolojisi [ADR-0031](0031-two-server-meeting-intelligence-topology.md) **bağlayıcı önkoşul**, supersede edilmez.
>
> **Owner kararı (2026-06-20)**: Provider modu = **abstraction + cloud-pilot → prod self-host** (ADR-0030 §LLM-API Option A→B; "self-host'u tek mod yapma" korunur).

---

## Context

Sektörün temel değeri (özet/karar/aksiyon) bizde **hiç yok**. 2-AI istişare (Claude + Codex `019ed1f5`): salt "toplantı özeti" bağımsız ürün olarak savunulabilir değil (Otter/Fireflies/Copilot zaten yapıyor). **Regüle sektör için ayırt edici = kaynaklı çıktı**: "AI dedi" değil **"şu cümleden (transcript segment + timestamp) çıkarıldı"** — hem differentiator hem hallucination guard hem KVKK Madde 12 hesap-verebilirlik temeli.

Bağlayıcı önkoşullar: **ADR-0031** (`meeting-ai-service` = `platform-ai` compute plane; client'lar asla doğrudan bağlanmaz; transcript Gateway → cross-server mTLS/WireGuard → platform-ai; controller=müşteri/tenant ERP-CRM alan sahibi, processor=platform-ai host operator DPA) + **ADR-0030** (LLM çıktısı = transcript-seviye koruma; LLM-input PII redaction; ses asla LLM'e gönderilmez; özet retention 1yr; pilot ADR ACCEPTED + hukuk öncesi YASAK). Belirli bir ERP/CRM markası yalnız pilot/adaptör örneği olabilir; core Meeting Intelligence kontratı ERP/CRM-agnostic kalır.

---

## Decision

### D1 — Katman: `meeting-ai-service` (platform-ai, Python)
Ayrı servis. Girdi yalnız **final transcript segment'leri** (`meeting_id` scope'lu, `transcriptVersionId` pinli); ses asla. Çıktı `meeting-service`'e (özet/karar/aksiyon entity, ADR-0030 retention 1yr). Cross-server transit ADR-0031 clause'una tabi.

### D2 — LLM Provider Abstraction (**domain-level** port)
**Chat-seviye değil** — domain-level: `LlmProvider.generateMeetingIntelligence(input) -> LlmResult{summary, decisions[], actions[], citations[]}`. Sağlayıcı mesaj formatı / tool şeması / safety-refusal modeli **core'a sızmaz**. İki adapter da first-class (self-host tek mod DEĞİL):
- **`cloud` (pilot)**: managed API (default Claude). Girdi = transcript-only + PII-redacted; ses YOK. Madde 9 → D3.
- **`local runtime` (production hedef)**: platform-ai GPU. **Ollama hard-code DEĞİL** — "local runtime adapter" (ilk impl Ollama+Llama; vLLM/llama.cpp/OpenAI-compatible local endpoint'e açık). ADR-0031 D4 self-host-GPU ile uyumlu.

Zorunlu:
- **Capability metadata**: `contextWindow, maxOutputTokens, supportsJsonSchema, supportsConstrainedDecoding, supportsStreaming, modelVersion, region, retentionMode, cost, latency` — core bunlara göre davranır (örn. schema-enforce zayıfsa repair-or-reject).
- **JSON-schema enforce**: cloud = native; local = constrained-decoding/grammar VEYA strict-parser + **fail-closed repair** (geçmezse reject).
- **Long-meeting context**: self-host'ta daha erken patlar → **chunking/hierarchical summarization + citation-preservation** stratejisi; segment/citation kontratı **provider-bağımsız** (model token offset'lerine güvenilmez).
- **Golden contract tests**: iki adapter aynı `LlmResult` invariant'larını koşar — %100 cited, same-meeting citations, quote-hash match, raw-PII-leak yok, deterministic-enough envelope.

### D3 — KVKK data-flow (ADR-0030 binding; cloud-pilot Madde 9)
- **Redaction-before-LLM (FAIL-CLOSED)**: transcript LLM'e gitmeden PII redaction; başarısızsa LLM çağrısı **yapılmaz**. Kapsam (pattern + NER, genişletilmiş): isim, telefon, IBAN/banka-hesap-varyantları, email, **TCKN, adres, plaka, pasaport, vergi no, müşteri/çalışan kodu, kullanıcı adı, şirket-içi sicil**, serbest-metin "benim TC..." pattern'leri, **speaker label**. `kvkk_pii_redaction_total` metric + audit.
- **Cloud payload allowlist (yalnız bunlar gider)**: redacted segment text + **opaque segmentId**. GİTMEZ: meeting title, participant list, speaker name, email, calendar metadata, tenant/user ID, file name, raw prompt/completion log, provider telemetry.
- **Redacted ≠ anonim**: bağlamsal re-identification mümkün → cloud-pilot yüzeyi **transcript-seviye koruma altında kalır** (anonim-veri muafiyeti İDDİA EDİLMEZ).
- **Ses asla LLM'e gitmez.**
- **Prompt-injection boundary**: transcript = untrusted input → LLM tool-access YOK, transcript delimiter zorunlu, adapter secret/log/tool görmez, çıktı yalnız JSON-schema'dan geçerse kabul.
- **Provenance (audit, raw-log değil)**: `redactionPolicyVersion, promptTemplateVersion, providerModelVersion, verifierVersion, transcriptVersionId` saklanır; raw prompt/completion log'a düşmez.
- **Madde 9 transfer mekanizması (hukuk seçer, D7 gate)**: aydınlatma/rıza metni + uygun güvence yolu (standart sözleşme/taahhütname) + Kurul/VERBIS "yurt dışı aktarım" beyanı ([[project_faz24_verbis_kvkk_analizi]] §13 "Diğer:" formatı) + provider zero-retention/no-training ayarı. Self-host'a geçince bu yüzey **sıfırlanır**.

### D4 — Citation-first (differentiator + hallucination guard, FAIL-CLOSED)
Her özet cümlesi / karar / aksiyon ≥1 citation: `{transcriptVersionId, segmentId, segmentHash, charStart, charEnd, quotedSpan, quoteHash}`.
- **Generation pattern = extract-then-abstract**: önce evidence span / action candidate çıkar; özet/karar/aksiyon **yalnız bu evidence set'ten** üretilir.
- **Verifier (acceptance, fail-closed)**: (1) exact offset/hash doğrulama (`quoteHash` + `charStart/End` segment'te birebir); semantic-anchor yalnız **düşük-güven/diagnostic**, acceptance değil. (2) **Claim-evidence entailment**: cited span claim'i destekliyor mu — substring varlığı YETMEZ ("bunu konuşalım" → "X kararı alındı" reject). (3) generic/düşük-bilgi span ("tamam/evet/bakarız") tek başına decision/action citation OLAMAZ. (4) citation aynı meeting/tenant/`transcriptVersionId`'den — cross-meeting **hard reject**.
- **Guard kapsamı**: çıktı **transcript-grounded** iddiası verir, **audio-grounded değil** (STT WER ayrı gate, ai#161).
- Citation'sız veya entailment-altı çıktı **ship/persist edilmez**.

### D5 — G-INT acceptance gate (fail-closed)
Production'a ancak: (a) özet **faithfulness** ≥ hedef (citation-anchored, kaynak-dışı iddia yok), (b) action-item **precision/recall** ≥ hedef (Türkçe gerçek-toplantı eval set, ai#161 T-B ile ortak koşu), (c) **%100 çıktı citation'lı + verifier-pass**. Uncited/faithfulness-altı çıktı ship edilmez. Regression corpus.

### D6 — Slice planı (her biri kendi cross-AI; citation PR-llm-01'den zorunlu)
- **PR-llm-01**: skeleton + domain-level provider abstraction + cloud adapter + **fail-closed redaction (D3)** + structured-JSON + **mandatory citation schema + minimal exact-offset/hash verifier (D4.1)** + **uncited persistence YOK**. (Citation "stub" yalnız kapalı/internal dev fixture lane'de — meeting-service persist YOK, UI YOK, flag kapalı.)
- **PR-llm-02**: advanced hallucination guard (entailment verifier D4.2) + Türkçe gerçek-toplantı eval set + G-INT harness (D5) + threshold + regression corpus.
- **PR-llm-03**: ask-AI RAG over transcript (citation'lı cevap, ayrı retrieval/embedding abstraction).

### D7 — Pilot gate (operator + hukuk)
Gerçek cloud LLM çağrısı **yalnız** legal/cloud safeguard'ları configured ise (D3 Madde-9 transfer mekanizması + provider zero-retention). meeting-service'e persist veya user-visible hiçbir çıktı **mandatory citation + verifier olmadan** geçmez. Self-host adapter + ADR-0030 ACCEPTED + DPA/VERBIS = pilot kullanıcı kaydı gate'i (ADR-0030/0031 M7).

### D8 — Acceptance guardrails (Codex `019ee7c9` final — implementation-binding)
1. **Persistence gate**: `meeting-service`'e yalnız `verificationStatus=PASSED` çıktı yazılır; `FAILED / LOW_CONFIDENCE / DIAGNOSTIC_ONLY` hiçbir user-visible entity üretmez.
2. **Semantic-anchor diagnostic-only**: fallback'in acceptance-path'e bağlanmadığı **testle kilitlenir** (yanlışlıkla success'e düşmesin).
3. **Redaction golden test = regex + metadata-allowlist**: title/participant/speaker/email/tenant/user/file/log alanlarının cloud payload'a **girmediği** golden test zorunlu (sadece regex PII değil).
4. **Cloud real-call = D7-gated flag**: default dev/test = **fake provider veya local fixture**; gerçek provider trafiği DPA/VERBIS/legal gate atlanarak çıkamaz.
5. **Raw response saklanmaz**: `LlmResult` provider raw response tutmaz; yalnız redacted + schema-valid + verified normalized result + provenance versions.
6. **G-INT hedef sayıları PR-llm-02'de mühürlenir**: ADR'de **"target TBD ≠ production/pilot acceptance"** — hedefler sayısallaşana kadar pilot/prod kabul YOK.

---

## Consequences

**Olumlu**: kaynaklı çıktı = niş differentiator + hallucination guard + KVKK Madde 12 hesap-verebilirlik tek hamlede. Domain-level abstraction → cloud hızlı pilot, self-host'a kilitlenmeden migrate; golden contract test iki adapter'ı eşitler. Extract-then-abstract + entailment = "6 ay sonra hâlâ doğru" (substring-sham-green değil).

**Olumsuz / risk**: (a) cloud-pilot Madde 9 yüzeyi (mitigasyon: payload-allowlist + genişletilmiş redaction + redacted≠anonim + zero-retention + hukuk-seçili transfer + D7 gate; self-host'a geçince sıfır). (b) Entailment-verifier maliyeti (her item) — differentiator'ın bedeli. (c) Türkçe self-host LLM kalite/context-limit (ai#161 ortak PoC + chunking). (d) G-INT eval set (Türkçe gerçek-toplantı, Zeynep T-B ortak).

**Geri dönülemez DEĞİL**: provider config-switch; cloud→self-host migration domain-contract + provider-bağımsız citation sayesinde prompt/citation kontratını bozmaz.

---

## Cross-AI

Implementer: Claude (Anthropic). Reviewer: Codex (OpenAI) `019ee7c9` — REVISE→absorbed (citation entailment + redaction scope + payload allowlist + slice-citation-from-01 + domain-level contract + prompt-injection boundary + provenance versioning). Verdict: direction AGREE, ACCEPTED = re-review sonrası.

İlişkili: [[project_faz24_independent_product_pivot]] · [[project_faz24_verbis_kvkk_analizi]] · ADR-0030 · ADR-0031 · ai#162.
