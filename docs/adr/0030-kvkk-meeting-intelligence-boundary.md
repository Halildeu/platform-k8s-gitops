# ADR-0030 — KVKK Boundary for Meeting Intelligence

> **Status**: ENGINEERING ACCEPTED / LEGAL TRACK PARALLEL (2026-06-27). 2026-06-02 placeholder 3-AI mutabakat ile Adım 0 kapısı olarak açıldı; 2026-06-27 owner kararıyla KVKK/VERBIS/hukuk owner acceptance mühendislik completion blocker'ı olmaktan çıkarıldı. Legal/VERBIS owner track'i paralel yürür; bu ADR legal acceptance, VERBIS güncelliği veya production legal go iddiası değildir.
>
> **Mutabakat trail**: Claude (Anthropic) + Codex `019e879c` (OpenAI) AGREE final + Mavis `mvs_c922505d66a94a45b031feb3489f9488` msg `78` (MiniMax) AGREE. 2026-06-27 Claude adversarial review: legal track engineering'den ayrılabilir; P0 riskleri önlemek için retention default `UNSET/refuse-to-store`, consent default required, deletion pipeline default enabled, legal acceptance overclaim forbidden.

---

## Context

Faz 24 Meeting Intelligence platformu (`platform-ai` Python STT + `audio-gateway-service`/`meeting-service`/`transcript-service` Spring Boot + `mfe-meeting` MFE + React Native mobile) **ses kaydı ve transcript** işleyecektir. KVKK çerçevesinde:

- **Ses kaydı** = kişisel veri (Madde 3 + Madde 6 işleme şartları)
- **Transcript** = aynı kişisel veriyi metin haline dönüştürür, **dolaşıma daha açıktır** (kopyala-yapıştır, e-posta, rapor)
- **Özel nitelikli veri riski** (Madde 6 — sağlık/inanç/cinsel hayat içeriği toplantıda geçebilir → işleme şartı sıkılaşır)
- **Yurt dışına aktarma** (OpenAI/Anthropic LLM API → meeting özet/karar çıkarımı) Madde 9 kapsamında

Mavis MiniMax kritik notu (2026-06-02): **"Ses kaydı kadar transcript koruma kritik — son kullanıcıyı korumak için hem ses hem metin aynı KVKK kapsamına girmeli."**

## Decision

### Engineering / Legal Separation

1. KVKK/VERBIS/hukuk owner acceptance, owner bildirimi kayda alındıktan sonra
   Faz 24 mühendislik completion blocker'ı değildir.
2. Mühendislik, legal karar verilmiş gibi ürün kontrollerini uygular ama legal
   acceptance, VERBIS güncelliği, DPA veya production legal go iddia etmez.
3. Retention/silme süreleri owner-supplied parametredir. Kod, manifest, gate ve
   evidence sabit süreyi acceptance blocker olarak kullanmaz; owner değer
   verdiğinde config ile uygulanır.
4. Güvenli default fail-closed'dur: durable storage için retention parametresi
   yoksa ilgili path refuse-to-store davranır; consent default required,
   deletion pipeline default enabled kalır.
5. G-COMP engineering gate; consent, parametric retention controls, legal-hold,
   access audit, deletion/export, owner legal-track notification, redaction ve
   runbook evidence doğrular. Hukuki yeterlilik/veri sorumlusu sicil kararını
   doğrulamaz.
6. Bu boundary'yi etkileyen yeni mimari kararlar (veri akışı, recording modu,
   retention/deletion semantics, consent default'u, legal/engineering ayrımı)
   provider-distinct cross-AI istişareden geçer ve ADR'ye bağlanmadan canonical
   kural sayılmaz.

**D6 trigger list (self-attestation'a bırakılmaz):** Aşağıdaki yüzeylerden
birini değiştiren PR/ops kararı D6 kapsamındadır: `ADR-0030`, `ADR-0031`,
`ADR-0043`, bu Faz 24 planının KVKK/G-COMP/data-flow bölümleri,
`verify_gcomp_compliance_gate_evidence.py`, `RB-faz24-gcomp-compliance-gate.md`,
G-COMP evidence schema/fixture'ları, `rawAudioRetentionDays`,
`transcriptRetentionDays`, `derivedArtifactRetentionDays`,
`auditRetentionDays`, `retentionDefaultsFailClosed`,
`consentDefaultRequired`, `deletionPipelineDefaultEnabled`, recording mode
anahtarları, raw-audio/transcript/LLM route veya storage boundary'si. Kapsam
belirsizse D6 tetiklenmiş kabul edilir ve cross-AI + ADR yolu izlenir.

### Scope

| Veri Sınıfı | Koruma Seviyesi |
|---|---|
| Ses kaydı (raw audio) | Encryption at rest (MinIO SSE-S3 + Vault KMS) + access RBAC + retention TTL + audit log per access |
| Transcript (final text) | Aynı kapsam **+ ek**: kim okuyabilir matrix (participant / company IT admin / report viewer), export sınırı, redaction policy, copy-paste prevention (UI), watermark (ileri) |
| Voiceprint / diarization speaker embedding | İlk fazda **YOK** — özel nitelikli biometric data; Faz 24.8 ADR ayrı karar |
| Özet / karar / aksiyon (LLM çıktısı) | Transcript ile aynı; LLM input PII redaction (isim, telefon, IBAN) review öncesi |
| Audit event (kim erişti, ne zaman) | Permanent retention — KVKK Madde 12 hesap verebilirlik |

### Roles & Rights

| Rol | Erişim |
|---|---|
| Meeting owner | Full read + delete + share grant |
| Meeting participant | Full read (kendi katıldıkları toplantı) + öz transcript indir |
| Company IT admin | Audit metadata erişim + **transcript içerik erişim KISITLI** (rıza gerek veya legal hold) |
| Report viewer (3rd-party UI) | Yalnız onaylı redacted özet — full transcript YOK |
| Service account (STT/LLM pipeline) | İşleme süresi boyunca encrypted access; idempotent + audit-trail |

### Retention Parameters

Süreler owner/legal track tarafından sağlanan parametrelerdir. Aşağıdaki tablo
engineering kontrolünün şeklini bağlar; sayısal değerler acceptance blocker
değil, owner config'i geldiğinde uygulanacak parametrelerdir.

| Veri | Parametre | Silme |
|---|---|---|
| Raw audio | `raw_audio_retention_days` owner-supplied; unset ise durable raw-audio storage refuse-to-store | Soft delete + owner-supplied grace + hard delete + audit |
| Transcript | `transcript_retention_days` owner-supplied; unset ise durable transcript storage refuse-to-store | Aynı pattern |
| Özet/karar/aksiyon | `derived_artifact_retention_days` owner-supplied; unset ise export/share sınırlı | Owner explicit silme + TTL worker |
| Audit log | `audit_retention_days` owner-supplied; immutable append-only; unset ise deletion policy legal track pending olarak raporlanır | Immutable / legal hold aware |

#### Effective Retention Value Provenance

Owner duration value'ları yoksa bu legal/owner track pending olarak kalır ve
mühendislik ancak fail-closed unset/default davranışıyla ilerler: durable
raw-audio/transcript storage açılmaz veya ilgili path refuse-to-store kalır.
Bu durum tek başına G-COMP mühendislik blocker'ı değildir.

Owner duration value'ları evidence'e girdiğinde artık örnek/runbook değeri
değil, uygulanmış konfigürasyon olarak kanıtlanır. G-COMP evidence bu durumda:

- bounded `ownerDecisionRef` taşır (`github://`, `github-actions://`,
  `artifact://`, `operator://`, `protected://`, `legal://`, `dpo://`);
  `runbook://` örnekleri owner kararı sayılmaz
- `appliedAsConfig=true` ile değerin config olarak uygulandığını gösterir
- `hardcodedInCode=false` ile kod/manifest/fixture sabiti olmadığını gösterir
- supplied gün değerlerini pozitif bounded integer olarak verir

`hardcodedInCode=true` fail'dir. Owner provenance, config application veya
bounded gün değeri eksikse sonuç blocked kalır; legal acceptance veya
production legal go iddia edilmez.

Verifier status ayrımı kasıtlıdır: `hardcodedInCode=true` hard failure
üretir; ownerDecisionRef, applied-as-config, explicit `hardcodedInCode=false`
veya bounded gün değeri eksik/geçersizse evidence blocked kalır.

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
- Faz 24.1 MVP tek müşteri/pilot olabilir; ürün kontratı ERP/CRM markasına bağlı değildir
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

**M7 engineering gate**: Bu tablo G-COMP evidence içinde machine-checkable
kontrollerle doğrulanır. Hukuk review/VERBIS owner track'i paraleldir ve
mühendislik blocker'ı değildir; pilot/user-facing legal go owner/legal artifact
ile ayrıca kanıtlanmadan legal acceptance iddiası kurulmaz.

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
| **Backup / cache retention cross-server** | Cache süreleri owner-supplied parametre veya ephemeral default olur | HF model cache platform-ai disk'inde yalnız model warm-load için; transcript cache memory-only (no persistence); audio cache **YOK** (transient stream-through). Kalıcı cache retention değeri owner config'i olmadan açılmaz. |
| **Legal controller-processor boundary** | Müşteri/tenant ERP-CRM alan sahibi = controller; platform-ai host operator = processor adayı | DPA/subprocessor/cross-border kararları owner/legal track'indedir. Mühendislik bu sınırı config/audit/redaction/host-access kontrolleriyle destekler ama DPA imzalı veya legal accepted iddiası yapmaz. Belirli ERP/CRM markası yalnız pilot/adaptör örneğidir; core ürün sözleşmesi vendor-specific değildir. |

**M7 engineering ek madde**: Cross-server transit için WireGuard/mTLS, tenant
propagation, bounded Redis, redaction ve audit evidence gerekir. Hukuk review
ve DPA owner/legal track'te paralel izlenir; bu eksikse production legal go
iddia edilmez ama mühendislik kontrolleri ilerlemeye devam eder.

## Parallel Legal Track (owner/legal; engineering blocker değil)

- [ ] Hukuk danışmanı review (Türk KVKK uzmanı)
- [ ] VERBIS bildirimi/güncellemesi gerek mi (veri sorumlusu sicili)?
- [ ] Sınır ötesi aktarma için aydınlatma metni (LLM API kullanımında)
- [ ] Çalışan toplantısı / müşteri toplantısı / iç eğitim ayrı kategori mi?
- [ ] Türkiye dışı kullanıcı için GDPR paralel uyum
- [x] Owner bildirimi kayda alındı: kullanıcı 2026-06-27 "ben owner'a bildirdim" kararını verdi; engineering gate bu bildirimden sonra legal acceptance beklemez.

## Mavis Adversarial Vurgu (msg `74`/`78` absorb)

Mavis MiniMax review'ında öne çıkan eklenti soru/karar tablosu (legal/owner
track cevapları paralel; engineering gate için blocker değil):

| Konu | Soru | Karar |
|---|---|---|
| Hukuka uygunluk dayanağı (Madde 5/6/9) | Açık rıza mı, sözleşme mi, meşru menfaat mi? | Owner/legal track; engineering blocker değil |
| Saklama süresi otomatik silme | Soft delete + hard delete TTL configurable | Owner-supplied parametre; unset ise durable storage fail-closed |
| Üçüncü taraf model paylaşım | OpenAI/Anthropic Whisper API → KVKK Madde 8/9 uyumu | LLM API §Option A/B owner/legal track; engineering redaction/overclaim guard uygular |
| Erişim kontrolü (RBAC + Zanzibar) | Kim okuyabilir, role-based mi? | Tablo §Roles & Rights |
| Silme talebi (Madde 11/13) | Kullanıcı transcript sildirmek isterse iş akışı? | TBD — Faz 24.7'de operator UI |
| Veri minimizasyonu | Ses dosyası saklansın mı yoksa sadece transcript yeterli mi? | Default durable raw-audio storage kapalı / parametre unset; owner config gelince policy uygulanır |
| Transcript okuma yetkisi (participant vs IT admin) | Çalışan mahremiyeti vs şirket güvenliği KVKK Madde 6/9 dayanağı | Tablo §Roles & Rights — IT admin KISITLI; içerik erişim consent/legal hold gerek |
| Meeting katılımcı consent | Katılımcı KVKK Madde 15/16 bilgi talep edebilir | §Consent Flow — explicit consent modal + opt-out |
| Şirket IT admin access sınırı | Tüm transcript erişim hukuki dayanağı? | Default: audit metadata YES, içerik HAYIR (consent/legal hold gerek) |
| Multi-tenant tenant isolation | Bir müşterinin verisi diğerine sızmamalı (Madde 12/32) | §Future Multi-tenant Readiness — tenantId reserved field |

## Engineering G-COMP Gate

Faz 24 mühendislik G-COMP evidence pass için şu maddeler aranır:

- [ ] Owner legal-track notification evidence kayıtlı
- [ ] Retention/silme süreleri parametric config; hardcoded duration yok
- [ ] Retention unset/default path fail-closed veya refuse-to-store
- [ ] Consent default required
- [ ] Deletion pipeline default enabled + audit
- [ ] Silme talebi iş akışı tasarlanmış + UI'da operator endpoint var
- [ ] Observability GOP başı doğrulanmış (ses/transcript log'a düşmüyor — `kvkk_pii_redaction_total` metric < threshold)
- [ ] Consent flow LIVE testai'de browser smoke ile kanıtlanmış
- [ ] Multi-tenant readiness placeholder live veya `multi_tenant_ready: false` explicit işaretli
- [ ] **Cross-Server STT Transit Boundary** WireGuard/mTLS UP + tenant propagation (X-* headers) propagating + audit event `audio_chunk_forwarded_to_platform_ai` emit verify + Redis transient/bounded policy live (persistence OFF, TTL kısa/owner-supplied, max memory bounded, backlog fail-fast) + platform-ai host access boundary (SSH + Vault credentials + audit trail) live evidence ile doğrulandı (ADR-0031 + ADR-0030 §"Cross-Server STT Transit Boundary" — Codex `019e8c09` iter-2 absorb 2026-06-03)
- [ ] Verifier/output hiçbir yerde `legalAdviceClaimed`, `legalAcceptanceClaimed`, `productionLegalGoClaimed`, `productionReady` overclaim yapmıyor

## Owner/Legal Production Go (parallel)

Bu maddeler owner/legal track'indedir. Mühendislik gate'ini bloklamaz; ancak
bu kanıtlar olmadan legal acceptance veya production legal go söylenmez:

- [ ] KVKK Madde 5/6/9 uyumlu hukuki dayanak dokümante edilmiş
- [ ] VERBIS bildirimi/güncellemesi owner/legal tarafından kararlaştırılmış
- [ ] Saklama süresi değerleri owner/legal tarafından config'e verilmiş
- [ ] Veri paylaşım limiti (üçüncü taraf model sağlayıcı dahil) kontratla sabitlenmiş
- [ ] LLM API yurt dışı aktarma için aydınlatma metni eklenmiş veya self-host karar verilmiş
- [ ] DPA/subprocessor/cross-border transit kararları owner/legal artifact ile kayıtlı

## Cross-AI Mutabakat Detayı (kritik kararlar)

| Karar | Cross-AI vote |
|---|---|
| Ses + transcript aynı KVKK kapsamında | Mavis önerisi → Claude + Codex AGREE |
| Multi-tenant placeholder şimdi | Mavis öneri → Claude + Codex AGREE |
| KVKK engineering controls ADR/GOP başı şart | Mavis + Codex + Claude AGREE; 2026-06-27 owner kararıyla legal track parallel |
| LLM API yurt dışı veri akışı için option A/B karar pilot öncesi | Codex önerisi → Claude + Mavis AGREE |
| Legal acceptance engineering blocker değil; fail-closed parametric controls şart | Kullanıcı owner kararı + Claude adversarial review 2026-06-27 |

## References

- KVKK 6698 sayılı kanun
- ADR-0013 Notification Orchestration (Faz 23 R2 KVKK CLOSED `019e5189` referansı)
- ADR-0010 Vault credential lifecycle (secret rotation pattern reuse)
- `docs/faz-24-meeting-intelligence-plan.md` (canonical Faz 24 plan)
- `platform-ai/CLAUDE.md` PII/KVKK boundary repo-specific kural
- Cross-AI threads: Codex `019e879c` + Mavis msg id `74` + `78`
- 2026-06-27 Claude CLI adversarial review (legal-track parallelism / fail-closed parameterization)

## Next

1. PR-gw-01 Gateway Contract 1.0 freeze ve sonraki Faz 24 product gates bu ADR'yi canonical referans alır
2. Mühendislik G-COMP gate'i owner legal-track notification + fail-closed parametric controls ile yürür
3. Owner/legal production go ayrı artifact ister; bu ADR tek başına legal acceptance veya VERBIS closure üretmez
4. PR-stt-02 real audio fixture seçimi **bu ADR'yle uyumlu** — privacy-safe asset stratejisi (Common Voice TR veya synthetic TTS)
