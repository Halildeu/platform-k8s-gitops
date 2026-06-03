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

### Mobile + Desktop Client Boundary (Codex `019e89fb` placeholder)

Mobile (`platform-mobile`) ve Desktop (`platform-desktop`) client'ları M6 Integration scope'unda — production deployment öncesi M7 ACCEPTED gate'de detay clause:

| Konu | Sorumluluk | Mobile Detay | Desktop Detay |
|---|---|---|---|
| **Audio capture consent UI** | Client | Just-in-time `Audio.requestPermissionsAsync` + Türkçe KVKK rationale + Settings deep link | Pre-meeting consent modal + macOS TCC + Windows Microphone permission |
| **Local cache/recording retention** | Client | `expo-sqlite` encrypted chunk buffer + TTL auto-purge (default 24h) + opt-in lokal kayıt | Lokal disk cache **YASAK default** (memory-only) + opt-in encrypted storage |
| **OS permission boundary** | Client | iOS `UIBackgroundModes=audio` only when capturing + Android FOREGROUND_SERVICE_MICROPHONE + user-visible indicator | macOS hardened runtime entitlements + Windows manifest declarations + tray icon visibility |
| **Offline transcript/artifact handling** | Client | WebSocket drop → SQLite buffer + reconnect flush + idempotency key (sessionId+chunkSeq) | Memory buffer + reconnect flush; opt-in disk persistence |
| **Background capture user-visible** | Client + Server audit | Persistent notification (Android foreground service) + system tray icon | macOS menu bar indicator + Windows system tray + "Recording" pill |
| **Transcript copy/share** | Client | Clipboard copy + share sheet → audit event emit | Native menu Copy/Share + audit event emit |
| **Crash report PII filter** | Client (Sentry-style) | Stack trace only; no transcript text + no audio path | Same; plus auto-redact local file paths from crash dumps |
| **OTA update integrity** | Client | EAS Update + signed manifest (Expo CodeSigning) + version policy | electron-updater + SHA + signature verify + staged rollout |
| **Biometric auth (opsiyonel)** | Client | `expo-local-authentication` Face ID + Touch ID + Android biometric | Touch ID (macOS) + Windows Hello |

**Production gate (M7)**: Bu tablo hukuk review ile detaylanır + ADR ACCEPTED durumuna gelir. Pilot kullanıcı kaydı **bu detaylanma öncesi YASAK**.

### Cross-Server STT Transit Boundary (ADR-0031 `019e8c09` absorb — 2026-06-03)

> **Bağlam**: ADR-0031 Two-Server Topology kararı (`platform-ai` ayrı dedicated host + diğer `platform-*` staging-sw'da) ile audio chunk + transcript Gateway (staging-sw) → STT (platform-ai) **cross-server hop** yapar. KVKK Madde 6/9 hassas veri sınır içi transit; private LAN **yetmez** (Codex iter-1 net). Bu clause ADR-0031'le canonical referans alır.

| Konu | Kural | Mekanizma |
|---|---|---|
| **Cross-server kanal** | mTLS / WireGuard / Vault PKI / SPIFFE workload identity ZORUNLU | MVP: WireGuard host-to-host + TLS service auth (TLS-pinned); Production: mTLS Vault PKI cert auth / SPIFFE workload identity. Private LAN sadece synthetic/public fixture PoC için geçici (gerçek meeting audio YASAK). |
| **Tenant / correlation propagation** | Gateway-derived headers cross-server'da korunur | `X-Correlation-Id`, `X-Meeting-Id`, `X-Session-Id`, `X-Device-Id`, `X-Tenant-Id` (JWT-derived), `X-User-Id` (JWT-derived), `language`, `audio_metadata`. Client-trusted ID YASAK. |
| **Audit event** | Cross-server hop'unda audit emit | `audio_chunk_forwarded_to_platform_ai` event per chunk veya batch (Gateway emit) + `audio_chunk_received_from_gateway` event (STT emit). Correlation ID ile join. |
| **Redis transient/bounded policy** | Bounded queue, persistence OFF, kısa TTL | Redis staging-sw'da; persistence (RDB/AOF) **kapalı**; max memory bounded; backlog threshold aşınca 429/503 fail-fast (admission reject); raw audio "durable storage" gibi davranmaz. |
| **platform-ai host access boundary** | SSH + Vault credentials + audit trail zorunlu | SSH key Vault rotation (ADR-0010 pattern); host root access break-glass operator-only; her erişim audit log (immutable 7yr); platform-ai host'a doğrudan client connection YASAK. |
| **Log redaction cross-server** | Transcript text + audio path payload'a düşmez | Structured log redaction filter (correlation ID + metadata OK; text + filename + speaker ID **redacted** veya hash); `kvkk_pii_redaction_total` metric. |
| **Failure / backlog behavior** | Silent drop YASAK; fail-fast + alert | platform-ai unreachable → Gateway 503 fail-fast; Redis TTL drain (kısa süre tolerate); admission control reject + Prometheus alert + audit event `cross_server_transit_failure`. |
| **No direct client-to-STT rule** | Mobile/desktop/web Gateway zorunlu | Network policy: platform-ai ingress sadece staging-sw Gateway source IP'sinden allow; başka source drop + audit. |
| **Backup / cache retention cross-server** | HF model cache + transcript cache + audio cache TTL | HF model cache platform-ai disk'inde (24h+ kabul; model warm-load avantajı); transcript cache memory-only (no persistence); audio cache **YOK** (transient stream-through). |
| **Legal controller-processor boundary** | Workcube = controller; platform-ai host operator = processor | KVKK Madde 11 sözleşme: DPA (Data Processing Agreement) imzalı; subprocessor list (Vault PKI provider, GPU cloud) dokümante; cross-border transit (LLM API) ADR-0030 §LLM API option A/B karar dahil. |

**Production gate (M7) ek madde**: Bu cross-server transit clause hukuk review ile detaylanır + ADR ACCEPTED durumuna gelir. Pilot kullanıcı kaydı **bu detaylanma öncesi YASAK**.

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
