# ADR-0030 — KVKK Boundary for Meeting Intelligence (PLACEHOLDER DRAFT)

> **Status**: PLACEHOLDER (2026-06-02). 3-AI mutabakat ile Adım 0 kapısı olarak açıldı; gerçek pilot ses/transcript akışı öncesi tam ADR (status: ACCEPTED) doldurulacak.
>
> **Mutabakat trail**: Claude (Anthropic) + Codex `019e879c` (OpenAI) AGREE final + Mavis `mvs_c922505d66a94a45b031feb3489f9488` msg `78` (MiniMax) AGREE.

---

## Context

Faz 24 Meeting Intelligence platformu (`platform-ai` Python STT + `audio-gateway-service`/`meeting-service`/`transcript-service` Spring Boot + `mfe-meeting` MFE + React Native mobile) **ses kaydı ve transcript** işleyecektir. KVKK çerçevesinde:

- **Ses kaydı** = kişisel veri (Madde 3 + Madde 6 işleme şartları)
- **Transcript** = aynı kişisel veriyi metin haline dönüştürür, **dolaşıma daha açıktır** (kopyala-yapıştır, e-posta, rapor)
- **Özel nitelikli veri riski** (Madde 6 — sağlık/inanç/cinsel hayat içeriği toplantıda geçebilir → işleme şartı sıkılaşır)
- **Yurt dışına aktarma** (OpenAI/Anthropic LLM API → meeting özet/karar çıkarımı) Madde 9 kapsamında

Mavis MiniMax kritik notu (2026-06-02): **"Ses kaydı kadar transcript koruma kritik — son kullanıcıyı korumak için hem ses hem metin aynı KVKK kapsamına girmeli."**

## Decision (placeholder — pilot öncesi ACCEPTED'a alınacak)

### Scope

| Veri Sınıfı | Koruma Seviyesi |
|---|---|
| Ses kaydı (raw audio) | Encryption at rest (MinIO SSE-S3 + Vault KMS) + access RBAC + retention TTL + audit log per access |
| Transcript (final text) | Aynı kapsam **+ ek**: kim okuyabilir matrix (participant / company IT admin / report viewer), export sınırı, redaction policy, copy-paste prevention (UI), watermark (ileri) |
| Voiceprint / diarization speaker embedding | İlk fazda **YOK** — özel nitelikli biometric data; Faz 24.8 ADR ayrı karar |
| Özet / karar / aksiyon (LLM çıktısı) | Transcript ile aynı; LLM input PII redaction (isim, telefon, IBAN) review öncesi |
| Audit event (kim erişti, ne zaman) | Permanent retention — KVKK Madde 12 hesap verebilirlik |

### Roles & Rights (taslak — pilot öncesi netleşir)

| Rol | Erişim |
|---|---|
| Meeting owner | Full read + delete + share grant |
| Meeting participant | Full read (kendi katıldıkları toplantı) + öz transcript indir |
| Company IT admin | Audit metadata erişim + **transcript içerik erişim KISITLI** (rıza gerek veya legal hold) |
| Report viewer (3rd-party UI) | Yalnız onaylı redacted özet — full transcript YOK |
| Service account (STT/LLM pipeline) | İşleme süresi boyunca encrypted access; idempotent + audit-trail |

### Retention

| Veri | Süre | Silme |
|---|---|---|
| Raw audio | 30 gün default (configurable per meeting) | Soft delete + 7 gün grace + hard delete + audit |
| Transcript | 90 gün default | Aynı pattern |
| Özet/karar/aksiyon | 1 yıl (rapor değeri) | Owner explicit silme |
| Audit log | 7 yıl (KVKK Madde 12) | Immutable |

### Consent Flow

- **Meeting başlatırken** explicit consent (UI modal — "Bu toplantı kayıt + transcribe edilecek")
- **Katılımcı bildirimi** (mobile push + email — Faz 23 notification reuse)
- **Opt-out** her zaman mümkün (yeni katılımcı eklenince re-prompt)
- **Voiceprint opt-in** ileri faz için ayrı consent

### LLM API (yurt dışı aktarma — Madde 9)

- **Option A** (PoC): OpenAI/Anthropic API ile özet/aksiyon çıkarımı → ses dosyası **gönderilmez**, sadece transcript + redacted version
- **Option B** (production): Self-host LLM (Ollama + Llama 3.3) → veri ülke içi kalır
- **Karar**: WER PoC sonrası + maliyet analizi + kullanıcı tercihi (pilot öncesi)

### Future Multi-tenant Readiness (Mavis önerisi)

- TenantId metadata Gateway Contract 1.0'da reserved field
- Faz 24.1 MVP tek müşteri (Workcube içi) OK
- Multi-tenant onboarding'de retroactive eklemek YASAK — placeholder şimdi

## Status & Open Questions (pilot öncesi cevap)

- [ ] Hukuk danışmanı review (Türk KVKK uzmanı)
- [ ] VERBIS bildirimi gerek mi (veri sorumlusu sicili)?
- [ ] Sınır ötesi aktarma için aydınlatma metni (LLM API kullanımında)
- [ ] Çalışan toplantısı / müşteri toplantısı / iç eğitim ayrı kategori mi?
- [ ] Türkiye dışı kullanıcı (Workcube müşteri yurt dışı) için GDPR paralel uyum

## Mavis Adversarial Vurgu (msg `74`/`78` absorb)

Mavis MiniMax review'ında öne çıkan eklenti soru/karar tablosu (TBD = pilot öncesi cevap):

| Konu | Soru | Karar |
|---|---|---|
| Hukuka uygunluk dayanağı (Madde 5/6/9) | Açık rıza mı, sözleşme mi, meşru menfaat mi? | TBD |
| Saklama süresi otomatik silme | Soft delete + hard delete TTL configurable | Tablo §Retention (30/90/1yr/7yr) |
| Üçüncü taraf model paylaşım | OpenAI/Anthropic Whisper API → KVKK Madde 8/9 uyumu | LLM API §Option A/B karar pilot öncesi |
| Erişim kontrolü (RBAC + Zanzibar) | Kim okuyabilir, role-based mi? | Tablo §Roles & Rights |
| Silme talebi (Madde 11/13) | Kullanıcı transcript sildirmek isterse iş akışı? | TBD — Faz 24.7'de operator UI |
| Veri minimizasyonu | Ses dosyası saklansın mı yoksa sadece transcript yeterli mi? | Default: ses 30 gün, transcript 90 gün; configurable |
| Transcript okuma yetkisi (participant vs IT admin) | Çalışan mahremiyeti vs şirket güvenliği KVKK Madde 6/9 dayanağı | Tablo §Roles & Rights — IT admin KISITLI; içerik erişim consent/legal hold gerek |
| Meeting katılımcı consent | Katılımcı KVKK Madde 15/16 bilgi talep edebilir | §Consent Flow — explicit consent modal + opt-out |
| Şirket IT admin access sınırı | Tüm transcript erişim hukuki dayanağı? | Default: audit metadata YES, içerik HAYIR (consent/legal hold gerek) |
| Multi-tenant tenant isolation | Bir müşterinin verisi diğerine sızmamalı (Madde 12/32) | §Future Multi-tenant Readiness — tenantId reserved field |

## Production Çıkış Kapısı (Gate)

Faz 24 servisleri **production'a çıkmaz** şu maddeler tamamlanana kadar:

- [ ] KVKK Madde 6/9 uyumlu hukuki dayanak dokümante edilmiş (hukuk review imzalı)
- [ ] Saklama süresi ve otomatik silme mekanizması implement edilmiş (cron worker + audit)
- [ ] Veri paylaşım limiti (üçüncü taraf model sağlayıcı dahil) kontratla sabitlenmiş (DPA imzalı)
- [ ] Silme talebi iş akışı tasarlanmış + UI'da operator endpoint var
- [ ] Observability GOP başı doğrulanmış (ses/transcript log'a düşmüyor — `kvkk_pii_redaction_total` metric < threshold)
- [ ] Consent flow LIVE testai'de browser smoke ile kanıtlanmış
- [ ] LLM API yurt dışı aktarma için aydınlatma metni eklenmiş (Option A/B karar dokümante)
- [ ] Multi-tenant readiness placeholder live veya `multi_tenant_ready: false` explicit işaretli

## Cross-AI Mutabakat Detayı (kritik kararlar)

| Karar | Cross-AI vote |
|---|---|
| Ses + transcript aynı KVKK kapsamında | Mavis önerisi → Claude + Codex AGREE |
| Multi-tenant placeholder şimdi | Mavis öneri → Claude + Codex AGREE |
| KVKK ADR placeholder pilot öncesi şart (GOP başı) | Mavis + Codex + Claude AGREE |
| LLM API yurt dışı veri akışı için option A/B karar pilot öncesi | Codex önerisi → Claude + Mavis AGREE |

## References

- KVKK 6698 sayılı kanun
- ADR-0013 Notification Orchestration (Faz 23 R2 KVKK CLOSED `019e5189` referansı)
- ADR-0010 Vault credential lifecycle (secret rotation pattern reuse)
- `docs/faz-24-meeting-intelligence-plan.md` (canonical Faz 24 plan)
- `platform-ai/CLAUDE.md` PII/KVKK boundary repo-specific kural
- Cross-AI threads: Codex `019e879c` + Mavis msg id `74` + `78`

## Next

1. PR-gw-01 Gateway Contract 1.0 freeze öncesi bu placeholder canonical referans alır
2. Pilot ses kaydı kullanılmadan önce **bu ADR ACCEPTED'a yükselir** (hukuk review + open question'lar cevaplanır)
3. PR-stt-02 real audio fixture seçimi **bu ADR'yle uyumlu** — privacy-safe asset stratejisi (Common Voice TR veya synthetic TTS)
