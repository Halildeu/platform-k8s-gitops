# Faz 24 — Meeting Intelligence / STT Platform Canonical Plan

> **Status**: ACTIVE (2026-06-02, 3-AI mutabakat sonrası sabit)
>
> **Mutabakat trail**: Claude (Anthropic) + Codex `019e879c` (OpenAI, AGREE final) + Mavis `mvs_c922505d66a94a45b031feb3489f9488` msg `78` (MiniMax, AGREE).
>
> **2026-06-25 truth refresh**: Faz 24 bağımsız ürün olarak konumlanır; Workcube/ERP entegrasyonu ürün bağımlılığı değildir. Sektör-standardı yol haritası §11'e eklendi ve mevcut runtime truth'a göre sınırlandı: recorder OpenFGA selector + edge lifecycle evidence accepted; #187 direct-STT transcript routing source/deploy scope accepted on testai; WG-B+ I6 pod-CIDR-to-WireGuard MASQ evidence accepted; #188 compute-plane audit verifier/runbook packaged but live smoke evidence open; #198 Denetim app-mTLS, desktop mic/loopback ve WG-B+ I3 management-audit gate hâlâ ayrı kanıt ister.

---

## 1. Vizyon

Bağımsız toplantı zekâsı platformu. Workcube/ERP bu plan için ürün bağımlılığı değil; eski entegrasyon bağlamı ve olası connector yüzeyidir. Telefon / masaüstü / Teams ses kaynaklarından:

- Canlı geçici transkript (2-8 sn gecikme)
- Kesinleşmiş transkript (10-20 sn bağlamlı)
- Konuşmacı ayrımı (diarization)
- Özet + karar + aksiyon LLM çıkarımı
- KVKK uyumlu retention + audit + consent

üretir. **STT compute worker yapısı** (`platform-ai`) Spring Boot orchestration arkasında konumlanır — mobile/web/desktop hiçbir zaman doğrudan Python servisine bağlanmaz.

## 2. Repo + Host Topology

> **Karar**: Faz 24 **iki-sunucu (two-server) topolojisi** — ADR-0031 (2026-06-03). `platform-ai` ayrı dedicated host'ta; diğer tüm `platform-*` servisleri staging-sw'da; mobile/desktop client kullanıcı cihazlarında.

| Repo | Rol | Host | Durum |
|---|---|---|---|
| `platform-ai` | Python STT/diarization/meeting-ai (FastAPI + faster-whisper + pyannote + LLM) | **Dedicated host (yeni)** — k3s ai-test → ai-prod; ArgoCD remote register | 🟢 live-stt-service PoC + Redis consumer source/live chain var; direct-STT transcript routing source/deploy slice `platform-ai#187` accepted; compute-plane audit smoke `platform-ai#188` altında ayrı acceptance ister |
| `platform-backend` | Spring Boot — `audio-gateway-service` (WebFlux) + `meeting-service` + `transcript-service` + `audit-event-consumer-service` | **staging-sw** k3d-test/k3d-prod | 🟢 k3d-test foundation + recorder edge lifecycle + #187 13-service transcript runtime deploy kanıtlı; external meeting-admin gateway audience, #198 app-mTLS, direct-STT e2e ve desktop mic/loopback ayrı gate |
| `platform-web` | React + Single-SPA — `mfe-meeting` MFE | **staging-sw** (frontend serve) | ⏳ planning (Faz 24.6) |
| `platform-mobile` | **React Native + Expo** + TypeScript — iOS + Android mobile client | **Kullanıcı cihazı** (App Store / Google Play distribution) | 🟢 **scaffold LIVE 2026-06-02** (commits `a774412`+`3a609a8`) |
| `platform-desktop` | **Electron + React** + TypeScript — macOS + Windows + Linux desktop client | **Kullanıcı cihazı** (electron-updater + signed installer) | 🟢 scaffold + recorder contract source chain var; gerçek mic/loopback smoke ayrı kanıt ister |
| `platform-k8s-gitops` | Kustomize + ArgoCD GitOps + ADR-0030 + ADR-0031 + observability skeleton + WG-B+ evidence packaging | **staging-sw** ArgoCD hub + platform-ai k3s remote cluster | 🟢 runtime desired-state + I6 MASQ evidence accepted (`#1867` Done); I3 management-audit package lane main'de ama `#1864` `Needs Verify` |

### 2.1 Current Runtime Boundary (2026-06-25)

- `meeting-service`, `transcript-service`, `audit-event-consumer-service`, `audio-gateway` ve Redis Streams foundation k3d-test hattında kanıtlıdır; #187 direct-STT transcript routing source/deploy slice 13-service digest/readiness/stability run ile kabul edildi. Bu, production veya direct-STT e2e readiness iddiası değildir.
- OpenFGA runtime selector `meeting` / `transcript` model gap'i `01KVXG15ETYAHMHANFD0E5CVK8` ile aşıldı; recorder edge lifecycle smoke `testai.acik.com/api/v1/audio-gateway` üzerinde consent/session/chunk/finish seviyesinde kanıtlandı.
- External `POST https://testai.acik.com/api/v1/admin/meetings` hâlâ `platform-desktop` token audience sınırı nedeniyle ayrı gateway-contract takip ister; mevcut recorder meeting fixture hop'u cluster-internal meeting-service üzerinden yapılmıştır.
- `audio-gateway` şu anda Redis dispatcher modunda; #188 same-session `CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit verifier/runbook packaged olsa da live audit smoke, Denetim #198 app-mTLS, direct-STT `/transcribe` e2e ve desktop mic/loopback kanıtı ayrı kapıdır.
- WG-B+ I6 cross-server MASQ evidence accepted only for pod-CIDR-to-WireGuard transit. WG-B+ I3 management audit (`#1864`), Denetim I7 app-mTLS (`platform-ai#198`), #188 compute-plane audit, and #182 direct audio e2e remain separate gates; broad Faz 24 readiness olarak konuşulmaz.

## 3. 3-AI Mutabakat Noktaları (her biri 3 AI tarafından onaylı)

### 1. STT compute worker ≠ ürün API'si

`live-stt-service` iç compute worker'dır; mobile/web hiçbir zaman doğrudan `platform-ai`'a bağlanmaz.

**Neden**: Auth / tenant / audit / permission / KVKK pattern'leri Spring Boot Gateway'de tutulur. `live-stt`'ye client WebSocket koymak = yanlış ownership boundary + deprecation borcu.

### 2. Audio Gateway Contract 1.0 ÖNCE kilitlenir

PR-stt-02 ve PR-gw-01 **eş zamanlı yapılmaz**. Önce Gateway Contract 1.0 freeze, sonra STT entegre.

**Neden**: Contract drift riski — STT iki yere bağlı (kendi `/transcribe` + Gateway şekli), drift sessizce yanlış kontrat üretir.

### 3. Observability GOP başı

Correlation id + redacted structured log + audit event boundary + metric isimleri Gateway Contract ile **birlikte** tanımlanır — sonraki PR'a ertelenmez.

**Neden**: KVKK çerçevesinde audit trail PR-stt-02'den itibaren işlemeli. "Dashboard sonra" diyebilirsin ama "correlation id sonra" diyemezsin.

### 4. KVKK ADR placeholder ŞART

Ayrı `ADR-0030 KVKK boundary for Meeting Intelligence` placeholder — retention, consent, deletion, access boundary, audit sorumluluğu.

**Neden**: Ses + transcript = KVKK Madde 6/9 hassas/özel kategori veri. Sonradan ekleme = compliance riski.

### 5. Transcript ≥ Ses (KVKK ek)

KVKK ADR'ye transcript için **ayrı boyut**: kim okuyabilir (participant / company IT admin / rapor), export sınırı, katılımcı consent ↔ şirket IT access sınırı.

**Neden**: Transcript metin halinde dolaşıma daha açık (kopyala-yapıştır, e-posta, rapor) — ses kaydı kadar koruma kritik.

### 6. `language` ZORUNLU başlangıçtan (ISO 639-1)

Gateway Contract 1.0'da `language` required field; `tr` sadece local/dev default. Product API explicit gönderir.

**Neden**: Bağımsız ürün müşteri çeşitliliği multi-dil destek gerektirir. Sonradan eklemek = breaking change retroaktif.

### 7. Worker isolation = b + d kombinasyonu

- **b**: STT tarafında supervised subprocess (multiprocessing.Process); timeout = process kill semantic + temiz worker re-start
- **d**: Gateway + Redis bounded queue + admission control + hızlı reject

**Neden**: `asyncio.wait_for` yalnızca HTTP client'a cevap; worker thread arka planda CPU+model lock tutmaya devam edebilir. `ProcessPoolExecutor` `future.cancel()` çalışan native inference'ı öldürmez.

### 8. WER PoC = Common Voice TR + gerçek pilot meeting (triangulate)

Sentetik TTS yalnızca pipeline smoke/CI (WER claim için kullanılmaz).

**Neden**: Sentetik "okuma" sesi meeting domain'i (overlap, duraksama, aksan, arka plan) yansıtmaz.

### 9. Two-host resource pressure acceptance gate (ADR-0031 update 2026-06-03)

PR-stt-02 e2e öncesi **iki host için ayrı baseline** (Codex `019e8c09` iter-2 absorb):

- **Gate A — staging-sw orchestration plane**: `free -m` + `kubectl top` baseline + Faz 22-23 paralel çakışma notu (audio-gateway-service + meeting-service + transcript-service + Faz 22.5 PR-D2.5 + Faz 23 notify aynı host)
- **Gate B — platform-ai compute plane**: Model warm-load sonrası RAM/CPU/GPU baseline + worker count + inference p95 + queue consume lag (live-stt-service dedicated host'ta — Faz 22-23 ile yarışmaz)

**Neden**: staging-sw 23 GiB RAM / 6.2 GiB available + Faz 22-23 paralel = Gate A sıkı. platform-ai dedicated host kendi resource bütçesi var (Gate B); sessiz capacity exhaustion riski iki host için ayrı doğrulanır.

### 10. Multi-tenant readiness placeholder

Faz 24.1 MVP tek müşteri OK, ama ADR-0030'da "future multi-tenant readiness" placeholder — tenantId metadata + auth token validation Gateway seviyesinde.

**Neden**: Yeni müşteri/tenant girişi geldiğinde retroactively eklemek pahalı.

---

## 4. 3 RED (yapılmayacak — Codex + Mavis ortak)

1. ❌ **Gateway contract kilitlenmeden** mobile/Web veya STT WebSocket contract yazılması
2. ❌ **KVKK ADR olmadan** gerçek müşteri meeting kaydı kullanılması
3. ❌ **Synthetic WER ile** model kararı kapatılması

---

## 5. Faz 24 Akış (3-AI sabit + ADR-0031 two-server topology)

> **Not (2026-06-05 Codex `019e97bb` REVISE absorb)**: §5 akış diyagramı **backend/STT critical path** sırasını gösterir (Adım 0 → PR-gw-01 → PR-stt-02 → PR-stt-03 → PR-gw-01C → PR-obs-01 → PR-wer-01 → PR-final-stt-01 → PR-gpu-01). Client plane işleri (Mobile = Faz 24.11, MFE = Faz 24.12, Desktop = Faz 24.13) PR-gw-01C LIVE testai sonrası **paralel cross-repo lane** olarak §6 cross-repo bağımlılık tablosunda izlenir; STT worker sırasının parçası değildir.

```
Adım 0  (gitops PR #1207 + #1233 MERGED 2026-06-03)
   ├─ ADR-0030 KVKK Meeting Intelligence boundary (placeholder + §"Cross-Server STT Transit Boundary" 2026-06-03)
   ├─ ADR-0031 Two-Server Topology — platform-ai compute plane + staging-sw orchestration plane (ACCEPTED 2026-06-03; gitops PR #1233 MERGED)
   ├─ Observability/Audit GOP skeleton (correlation id + log + metric + audit event contract)
   └─ PLAN.md Faz 24 satırı + canonical plan (bu doküman)
        ↓
ADR-0031 ACCEPTED + cross-server contract field/admission semantics canonical (blocker — PR-gw-01 öncesi; Codex `019e8c09` iter-2 absorb)
        ↓
PR-gw-01  Audio Gateway Contract 1.0 freeze (platform-backend) — source-level contract; physical host gerek YOK
   fields: language (ISO 639-1) + correlation_id + meeting_id + session_id + tenant_id + user_id + auth + audio chunk metadata + admission contract + cross-server contract field/admission semantics (ADR-0031 §D2)
        ↓
platform-ai dedicated host provision + k3s ai-test cluster + ArgoCD remote register + Vault AppRole `ai-runtime-test` + WireGuard tunnel + mTLS PKI + Redis Streams bounded setup (blocker — gerçek meeting audio cross-server e2e için PR-stt-02 live veya PR-gw-01C öncesi; synthetic/local Docker e2e için PoC fixture istisnası açık)
        ↓
PR-stt-02  real audio + Docker e2e + Gate A/B baseline (platform-ai)
   Gateway contract uyumlu language/correlation metadata; Gate A staging-sw + Gate B platform-ai baseline; Türkçe wav fixture (Common Voice TR sample veya privacy-safe TTS); synthetic/local Docker e2e için cross-server security gate istisnası açık (private LAN fixture); gerçek meeting audio için cross-server mTLS/WireGuard ZORUNLU
        ↓
PR-stt-03  supervised subprocess worker + hard timeout kill (platform-ai)
        ↓
PR-gw-01C  audio-gateway-service Redis Streams cross-server dispatcher producer (ADR-0031 D2 cross-server network topology + D8 failure modes + plan §3 mutabakat #9) — eski PR-queue-01 scope dağıtıldı: session lifecycle + bounded in-memory registry/idempotency replay PR-gw-01A'da (`bounds.max-active-sessions: 1000` + `idempotency.replay-cache-size: 4096`; `admission-queue-capacity` property tanımlı ama şu an unused — future use için reserve), REST chunk admission PR-gw-01B-core'da, dispatcher backpressure 429/503 + Retry-After PR-gw-01B3'te (DispatchOutcome.QueueFull/Unavailable; registry mutation sadece Accepted'da), Redis Streams producer PR-gw-01C'de (`audio:chunks:p00..p31` stream keys, consumer group `live-stt-v1`, XADD per chunk, idempotency `(sessionId, chunkSeq)`), live-stt consumer ownership PR-stt-03'te (subprocess worker + Redis Streams reader — PR-stt-03 scope genişledi; ayrıca PR-stt-04 ayrı issue gerekirse ileride karar)
        ↓
PR-obs-01  Grafana/Prometheus dashboard genişletme (skeleton zaten Adım 0'da)
        ↓
PR-wer-01  Common Voice TR + gerçek pilot meeting WER raporu (ADR girdisi)
        ↓
PR-final-stt-01  final-stt-service (WER sonucuna göre model kararı; `large-v3-turbo` varsayım YOK)
        ↓
PR-gpu-01  GPU Dockerfile variant (donanım + ölçüm sonrası)
```

## 6. Cross-Repo Bağımlılık Sırası

| Repo | İş | Bağımlı |
|---|---|---|
| platform-k8s-gitops (Adım 0) | ADR-0030 + ADR-0031 + obs skeleton + PLAN.md | yok (gitops PR #1207 + #1233 MERGED 2026-06-03) |
| platform-backend | PR-gw-01 Gateway Contract 1.0 freeze (source-level contract, physical host gerek YOK) | Adım 0 MERGED + ADR-0031 ACCEPTED + cross-server contract field/admission semantics canonical |
| **platform-k8s-gitops + ops** | **platform-ai dedicated host provision + k3s ai-test cluster + ArgoCD remote register + Vault AppRole `ai-runtime-test` + WireGuard tunnel + mTLS PKI cert auth** | ADR-0031 ACCEPTED; gerçek meeting audio cross-server e2e (PR-stt-02 live veya PR-gw-01C) öncesi blocker; synthetic/local Docker e2e için istisna |
| **platform-k8s-gitops + ops** | **staging-sw Redis Streams runtime setup/runbook**: streams `audio:chunks:p00..p31` (32 partition), consumer group `live-stt-v1`, persistence OFF (`appendonly no` + `save ""`); MAXLEN per stream + XADD `~` trim semantic; maxmemory + `maxmemory-policy: noeviction` (backlog fail-fast); TTL kısa; ACL/TLS/WireGuard reachability cross-server; Vault `kv/platform-ai/redis/*` secret delivery (ESO); XLEN/lag metrics Prometheus; init + reconcile runbook `docs/runbooks/redis-streams-staging-sw.md` ✅ (gitops#1447) — **LIVE 2026-06-11**: host-compose 172.19.0.250 + D29 tam yeşil (platform-ai#151) | ADR-0031 D2 + D3 + D8 ACCEPTED + PR-gw-01C contract MERGED ✅ |
| platform-ai | PR-stt-02 real audio + container e2e | PR-gw-01 MERGED |
| platform-ai | PR-stt-03 subprocess isolation | PR-stt-02 MERGED |
| platform-k8s-gitops | Kustomize base/apps/{audio-gateway,live-stt} + overlay | PR-gw-01 + PR-stt-03 source-merged |
| platform-backend | PR-gw-01C Redis Streams cross-server producer (eski PR-queue-01 absorbe) | PR-stt-03 MERGED |
| platform-k8s-gitops | PR-obs-01 dashboard + alertmanager rules (audio-gateway Prometheus + Redis Streams XLEN/lag + consumer group offsets) | PR-gw-01C MERGED + staging-sw Redis Streams setup LIVE |
| platform-ai | PR-wer-01 WER raporu | PR-stt-03 MERGED + pilot meeting kaydı |
| platform-ai | PR-final-stt-01 | WER raporu çıktısına göre |
| platform-ai | PR-gpu-01 | donanım + ölçüm sonrası |
| **platform-mobile** | **PR-mobile-01..10** (Faz 24.11 — board canonical) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| **platform-desktop** | **PR-desktop-01..10** (Faz 24.13 — board canonical 2026-06-05; client plane simetri Mobile/MFE ile) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| platform-web | mfe-meeting MFE (Faz 24.12) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| platform-backend | meeting-service + transcript-service | PR-gw-01 ile paralel veya hemen sonra |
| platform-backend | Faz 23 notification entegre (meeting events) | M6 ortası |
| platform-backend | report-service weekly-meeting-summary | M6 sonu |

## 7. Donanım & Resource Stratejisi (2026-06-03 — ADR-0031 two-server topology)

> **Mimari karar**: Faz 24 **iki-sunucu topolojisi** ile çalışır (ADR-0031 — Codex `019e8c09` iter-1 REVISE absorb). `platform-ai` ayrı dedicated host'ta; diğer tüm `platform-*` servisleri staging-sw'da.

### İki-sunucu boundary

| Plane | Host | Workload | Sahip |
|---|---|---|---|
| **Orchestration plane** | staging-sw (23 GiB RAM, GPU YOK) | `audio-gateway-service`, `meeting-service`, `transcript-service`, `notification`, `report-service`, Faz 22-23 workloads, Redis bounded queue, Vault, ArgoCD hub, host nginx edge | Spring Boot + Java ekosistem |
| **Compute plane** | **platform-ai** (yeni dedicated server — MVP'de GPU upgrade) | `live-stt-service`, `diarization-service` (ileri faz), `meeting-ai-service` (LLM özet/karar/aksiyon), worker subprocess pool | Python + faster-whisper + pyannote + LLM client |
| **Client plane** | Kullanıcı cihazları | platform-mobile (iOS/Android) + platform-desktop (macOS/Win/Linux) + platform-web (browser) | RN/Expo + Electron + React |

Mobile/desktop/web client'lar **hiçbir zaman** doğrudan `platform-ai`'a bağlanmaz (3-AI mutabakat noktası #1 korunur). Bağlantı her zaman `audio-gateway-service` üzerinden (staging-sw → cross-server hop → platform-ai).

### Network topology (Gateway ↔ STT cross-server)

- **Redis bounded queue**: **staging-sw** (admission/rate-limit/tenant fairness Gateway boundary ownership). Transient, bounded memory, persistence **OFF**, kısa TTL, backlog threshold aşınca 429/503 fail-fast.
- **Cross-server kanal**: **WireGuard host-to-host + TLS service auth** (MVP); **mTLS / Vault PKI / SPIFFE workload identity** (production). Private LAN **yetmez** (KVKK transit hassasiyet — Codex iter-1 net).
- **STT pull model**: live-stt-service Redis'ten chunk consume eder; Gateway push (admission control sahibi).
- **Failure mode**: platform-ai unreachable → Gateway 503 fail-fast + Redis backlog kısa süre tolerate; threshold sonra admission reject.

### Resource pressure ayrımı (acceptance gate §9 ile uyumlu)

- **Gate A — staging-sw orchestration plane**: `free -m available > 2 GiB`, `kubectl top` (audio-gateway + meeting + transcript + Faz 22-23 paralel), Redis queue depth bounded, OOM/restart count 0.
- **Gate B — platform-ai compute plane**: Model warm-load sonrası RAM < %70, worker count config-aligned, GPU VRAM headroom > 2 GiB (varsa), inference p95 < 5s (PoC) / < 2s (MVP), queue consume lag < 5s.

### PoC Aşaması (Faz 24.0-24.6)

- CPU-only Whisper `medium int8` (~1.5 GB model) — **platform-ai server kendi CPU/RAM** (staging-sw Faz 22-23 ile yarışmaz)
- Tek worker, çoklu request threadpool serial (b+d isolation)
- Gate A + Gate B her e2e öncesi ölçüm dokümante

### MVP Aşaması (Faz 24.7-24.9)

- **platform-ai server kendi GPU upgrade** (örn. RTX 4070 12 GB VRAM) — vendor lock-in yok, KVKK sınır içi
- (Mevcut "Cloud GPU bridge Lambda Labs / Vast.ai" tahmini **stale** — ADR-0031 ile kayma)
- WER PoC + maliyet ölçüm platform-ai dedicated host'ta
- Production karar (GPU upgrade vs SaaS) data-driven (WER + latency + cost)

### Production Aşaması

- platform-ai dedicated host + k3s ai-prod cluster + ArgoCD remote register
- staging-sw GPU upgrade **gereksiz** (Spring Boot orchestration → CPU yeterli)
- Karar: platform-ai donanım upgrade tier (consumer-grade RTX 4070 vs server-grade A10/A100) WER + latency + cost data-driven

## 8. Risk Matrix (3-AI mutabakat sonrası)

| Risk | Önlem | Sahibi |
|---|---|---|
| Gateway contract drift (STT iki yere bağlı) | Contract 1.0 freeze ÖNCE; ayrıca contract test (consumer-driven) | PR-gw-01 |
| Worker thread leak (asyncio.wait_for) | Subprocess + hard kill semantic (PR-stt-03) | platform-ai |
| KVKK compliance (ses+transcript hassas) | ADR-0030 placeholder + hukuk review pilot öncesi | Adım 0 + ek tur |
| **Cross-server transit ses/transcript açık** (KVKK Madde 6/9 hassas) | WireGuard + mTLS PKI ZORUNLU; private LAN yetmez; ADR-0030 §"Cross-Server STT Transit Boundary" | ADR-0031 + PR-gw-01 |
| **platform-ai host failure** (network/crash) | Gateway 503 fail-fast (`DispatchOutcome.Unavailable` + Retry-After=30) + Redis Streams MAXLEN trim drain + circuit breaker + alert | ADR-0031 D8 + PR-gw-01C contract + PR-gw-01B3 dispatcher |
| **Vault cross-server unreachable** (platform-ai → staging-sw Vault) | AppRole secret TTL cache + WireGuard tunnel health monitor + alert | ADR-0031 + ADR-0010 reuse |
| Staging resource exhaustion (Faz 22-23 paralel) | **Gate A** acceptance: `free -m`/`kubectl top` baseline staging-sw (orchestration plane) | her PR-stt-* |
| **platform-ai compute exhaustion** (model load + worker pool RAM) | **Gate B** acceptance: model warm-load + worker count + GPU VRAM (varsa) + inference p95 + queue consume lag | her PR-stt-* (Gate B yeni) |
| Türkçe doğruluk düşük kalır | Common Voice TR + pilot meeting WER triangulate (sentetik yok) | PR-wer-01 |
| Model kararı erken kilitlenir | `large-v3-turbo` varsayım yok; WER sonrası karar | PR-final-stt-01 |
| GPU yatırım atıl kalır | PoC CPU önce → ölç → GPU karar (Adım 24.7+) | PR-gpu-01 |
| Multi-tenant retroactive zorluk | ADR placeholder + tenantId reserved field şimdi | ADR-0030 |
| LLM API yurt dışı veri akışı | Option A (transcript only, no audio) → Option B (self-host) karar | pilot öncesi |
| Mobile RN/Expo test harness yetersiz | Detox e2e + Expo dev preview (browser MCP mobile için yetmez) | Faz 24.5 |

## 9. Acceptance Gates (D29 paralel — ADR-0031 two-server uyumlu)

| Layer | Gate |
|---|---|
| **Up** | Pod Running + TCP reachable + `/health` 200 (Gateway staging-sw + STT platform-ai ayrı kanıt) |
| **Functional** | `POST /transcribe` real audio fixture ile 200 + non-empty text + meta complete; cross-server WS/HTTP smoke pass |
| **KVKK-safe** | Audit event emit + log redaction verify + access RBAC enforce + retention policy applied; `audio_chunk_forwarded_to_platform_ai` audit event (ADR-0030 §"Cross-Server STT Transit Boundary") |
| **Resource-pressure-safe — Gate A (staging-sw)** | `free -m` available > 2 GiB + `kubectl top` (gateway+meeting+transcript+Faz 22-23) + Redis queue depth bounded + OOM/restart=0 |
| **Resource-pressure-safe — Gate B (platform-ai)** | Model warm-load sonrası RAM < %70 + worker count config-aligned + GPU VRAM headroom > 2 GiB (varsa) + inference p95 < 5s (PoC) + queue consume lag < 5s |
| **Cross-server transit-safe** | WireGuard tunnel UP + mTLS cert valid + Vault PKI auto-rotate alert healthy + failure drill (platform-ai down → Gateway 503 + Redis fail-fast) geçti |
| **Cross-AI peer review** | Implementer ≠ Reviewer (provider seviyesinde); thread referansı PR squash |
| **Browser smoke** | Mobile/Web kullanıcı end-to-end senaryo (Faz 24.5+ için; PoC için skip) |

## 10. Cross-AI Mutabakat Trail

| Karar | Codex `019e879c` | Mavis msg | Claude |
|---|---|---|---|
| live-stt = compute worker, ürün API değil | RED 1+2 | AGREE | AGREE |
| Gateway Contract 1.0 freeze önce | iter-3 AGREE/REVISE | msg `74` PARTIAL + msg `78` AGREE | AGREE |
| Observability GOP başı | iter-3 AGREE | msg `74` vurgu | AGREE |
| KVKK ADR placeholder şart | iter-3 AGREE | msg `74` ŞART | AGREE |
| Transcript = ses koruma kapsam | (örtük) | msg `78` C önerisi | AGREE |
| `language` ZORUNLU + Gateway Contract field | iter-3 REVISE | msg `74` C | AGREE |
| Worker isolation b + d | iter-1 critical note | msg `74` AGREE | AGREE |
| WER triangulate (Common Voice + pilot) | iter-1 H matrisi | msg `74` AGREE | AGREE |
| Staging resource pressure gate | iter-3 AGREE | msg `74` B eksik risk | AGREE |
| Multi-tenant placeholder | (örtük) | msg `78` B tek eksik | AGREE |
| **Two-server topology** (ADR-0031) | `019e8c09` iter-1+iter-2+iter-3 REVISE absorb → **iter-4 AGREE final** ("merge blocker bulmadım") | msg `78` AGREE final 2026-06-03 (ADR-0031 mutabakat closed) | AGREE (kullanıcı 2026-06-03 mimari notu) |

## 11. Sektör-Standardı Yol Haritası (bağımsız ürün)

> **Kapsam**: Faz 24 artık Workcube'e gömülü bir ERP özelliği olarak değil, Türkiye ve regüle/veri-hassas enterprise pazarına satılabilir bağımsız meeting-intelligence ürünü olarak planlanır. Rakip paritesi Otter, Fireflies, Gong, Teams Copilot ve Zoom AI Companion sınıfına göre okunur; farklılaşma ise Türkçe-first kalite, self-host/on-prem opsiyon, KVKK governance ve citation'lı intelligence kombinasyonudur.

### 11.1 Kazanma Formülü

Savunulabilir pozisyon: **Türkçe-first + on-prem/self-host + compliance-grade governance + kaynaklı intelligence**. Tek başına STT, tek başına chat/summary veya tek başına self-host yeterli değildir. Hedef wedge, yatay self-serve SaaS değil; kamu, finans, sağlık, savunma, hukuk ve yönetim kurulu gibi veri hassasiyeti yüksek enterprise segmentleridir.

Current diagnosis:

- Altyapı hattı ileri: gateway, Redis Streams, meeting/transcript/audit services, OpenFGA selector ve recorder edge lifecycle evidence var.
- Ürün-değer hattında source-side guardrail ilerledi: G-WER/DER verifier (`platform-ai#199`), G-INT verifier (`platform-ai#200`), retention readiness gate (`platform-ai#201`), Redis control-plane cleanup (`platform-ai#202`), recording/archive RED boundary (`platform-ai#203`), G-LAT/COST verifier (`platform-ai#204`), G-CAP aggregate capture gate (`scripts/faz24/verify_gcap_capture_gate_evidence.py`), G-COMP aggregate compliance gate (`scripts/faz24/verify_gcomp_compliance_gate_evidence.py`) ve G-OPS operability gate (`scripts/faz24/verify_gops_operability_gate_evidence.py`) main'de. Buna rağmen gerçek pilot WER/DER, gerçek pilot G-INT, pilot G-LAT/COST, live aggregate G-CAP evidence, VERBIS/DB cleanup evidence, live G-COMP evidence, direct-STT e2e ve desktop mic/loopback acceptance hâlâ açık.
- Acceptance dili bu ayrımı korur: infrastructure evidence, market-ready product evidence yerine geçmez.

### 11.2 Capability Tracks

| Track | Kapsam | Sektör boşluğu | Öncelik | Ana repo |
|---|---|---|:--:|---|
| **T-A Capture** | Teams/Calendar bot, Zoom/Meet bot, desktop recorder production smoke, browser upload fallback | Bot/capture yoksa ürün dosya-yükleme aracı seviyesinde kalır | P0 | backend + desktop/web/mobile |
| **T-B Quality** | Türkçe WER harness, gerçek toplantı benchmark, diarization DER, speaker→person mapping, latency/cost/throughput gate; `gwer_gate.py` + `glat_cost_gate.py` source-side gates main'de, pilot evidence bekliyor | Türkçe doğruluk, diarization ve ölçülü latency/cost rakip paritesinin temel kanıtı | P0 | `platform-ai` |
| **T-C Intelligence** | Özet, karar, aksiyon, owner/date extraction, citation/timecode, transcript Q&A; `gint_gate.py` source-side gate main'de, gerçek pilot evidence bekliyor | Asıl ürün değeri; regüle pazarda her çıkarım kaynağa bağlanmalı | P0 | `platform-ai` + backend |
| **T-D Compliance Productization** | ADR-0030 hukuk/VERBIS acceptance, consent UI, retention/legal-hold, access matrix, audit export, on-prem install pack; #156 retention gate, #185 recording/archive RED boundary ve G-COMP/G-OPS source-side verifier'ları hazır, live evidence bekler | Bu pazar için farklılaşma noktası; doküman değil ürün yüzeyi olmalı | P1 | gitops + web + backend |
| **T-E Integration Parity** | Webhook, CRM/Jira/CSV/export, notification follow-up, calendar/task sink | Diferansiyatör değil ama enterprise satışta eksiklik gibi görünür | P2 | backend + web |

Deferred by design:

- Üç client'ta erken tam parite; önce capture + desktop/web reliable path.
- Canlı altyazı latency takıntısı; önce transcript/intelligence correctness.
- GPU/model kararını WER/latency/cost ölçümü olmadan kilitlemek.
- Self-host LLM'i tek opsiyon yapmak; transcript-only özel bulut modu opsiyon olarak kalabilir.

### 11.3 Product Quality Gates

| Gate | Evidence |
|---|---|
| **G-WER/DER** | Gerçek Türkçe toplantı setinde WER ve diarization DER hedefi; `platform-ai#199` gate synthetic/Common Voice kanıtı acceptance yerine kullanmayı bloklar |
| **G-INT** | Faithfulness + action-item precision/recall + owner/date accuracy; her summary/action citation/timecode ile bağlanır; `platform-ai#200` gate synthetic/mock kanıtı pilot acceptance yerine kullanmayı bloklar |
| **G-CAP** | Teams/Calendar veya desktop recorder ile kayıt başlatma, consent alma, chunk upload, finish ve failure/retry oranı ölçülü; `scripts/faz24/verify_gcap_capture_gate_evidence.py` yalnız redacted external recorder verifier output'larından aggregate gate üretir, live pilot evidence bekler |
| **G-COMP** | Consent, retention, legal hold, access audit ve deletion/export policy canlı; KVKK hukuk/VERBIS boundary ADR-0030'da accepted; `platform-ai#201` retention gate mevcut durumda blocked döner, `platform-ai#203` raw-audio archive'i default live path'ten çıkarır; `scripts/faz24/verify_gcomp_compliance_gate_evidence.py` yalnız redacted metadata envelope'ını kabul eder ve canlı VERBIS/DB cleanup/legal/operator evidence olmadan pass üretmez |
| **G-LAT/COST** | Latency p50/p95, queue lag, cost/dakika ve GPU/CPU utilization ölçülür; `platform-ai#204` gate lab/synthetic/Common Voice performans kanıtını acceptance yerine kullanmayı bloklar; model/GPU kararı pilot ölçüme dayanır |
| **G-OPS** | On-prem install/upgrade/backup/restore/runbook kanıtı; secret delivery ve rollback path test edilir; `scripts/faz24/verify_gops_operability_gate_evidence.py` redacted metadata envelope'ını RPO/RTO/coverage eşikleriyle gate eder, live on-prem evidence bekler |

### 11.4 Aşama Sırası

```text
Aşama-2 evidence line
  Gateway + Redis + foundation services + recorder edge lifecycle evidence
  Boundary: direct-STT, compute-plane audit, desktop mic/loopback, WG-B+ I3 open; I6 MASQ accepted only for pod-CIDR-to-WG metadata evidence.

Aşama-3 Core Product Value (P0)
  T-B WER/DER + G-LAT/COST + T-C G-INT + T-A G-CAP gate infrastructure main'de; gerçek pilot kanıtı pending
  Citation'lı summary / decision / action extraction acceptance hattı hâlâ gerçek pilot kanıtı ister
  İlk gerçek toplantı e2e: capture -> transcript -> intelligence -> audit.

Aşama-4 Adoption + Compliance (P0/P1)
  T-A Teams/Calendar veya desktop recorder production-grade capture
  T-D consent / retention / legal-hold / access audit UX
  Raw-audio archive default-off; future opt-in only (platform-ai-scoped ADR-0036)
  ADR-0030 accepted + G-COMP compliance gate evidence + on-prem installation package + G-OPS operability gate evidence.

Aşama-5 Proof
  3-5 design-partner PoC
  Türkçe benchmark raporu
  Regulated-segment reference evidence.

Aşama-6 Scale + GTM
  Tek dikey wedge seçimi
  T-E integration parity
  SaaS/private-cloud/on-prem SKU paketleme.
```

### 11.5 MVP Definition

İlk satılabilir MVP: **Teams/Calendar veya desktop capture → Türkçe transcript + diarization → citation'lı özet/karar/aksiyon → admin consent/retention/access/audit → on-prem opsiyon → basit export**. Canlı altyazı, full mobile parity, multi-platform bot paritesi ve revenue-coaching dikeyleri MVP dışıdır.

### 11.6 ADR Backlog

| ADR | Konu | Tetik |
|---|---|---|
| Capture strategy | Bot vs native recorder vs desktop capture; tek güçlü initial path | T-A implementation öncesi |
| Diarization approach | pyannote/alternatif, DER ölçümü, speaker→person mapping | T-B `PR-diar-*` öncesi |
| Intelligence layer | Citation, hallucination guard, LLM routing, self-host/private-cloud sınırı | T-C `PR-llm-*` öncesi |
| ADR-0030 legal evidence package | KVKK boundary'yi hukuk/VERBIS kanıtı, consent/retention/access kararları ve audit evidence ile operasyonel acceptance'a taşıma | Gerçek customer audio/transcript PoC öncesi |
| Packaging/GTM | SaaS + on-prem lisans, regulated premium tier, backup/restore/SLA | Aşama-6 öncesi |

## References

- Codex thread: `019e879c-c51e-7691-8f16-69c781fb787e` (plan-time + iter-3 AGREE final — single-host varsayımıyla)
- Codex thread: `019e877b-bd31-72f3-b86a-229f933e51cb` (live-stt PR #1 review AGREE)
- Codex thread: `019e8c09-2cc7-7d23-a414-2c1d2950232c` (ADR-0031 two-server topology iter-1 REVISE absorb)
- Codex/Claude sector-roadmap handoff: PR #1614 historical input, refreshed on `origin/main` with 2026-06-25 runtime boundaries
- Mavis msgs: `74` (PARTIAL historical) → `76` (absorb wait historical) → `78` (AGREE final 2026-06-03 — ADR-0031 cross-AI mutabakat closed); HARD RULE Cross-AI Peer Review provider seviyesinde Anthropic + OpenAI yeterli, MiniMax non-blocking
- ADR-0030 KVKK Meeting Intelligence Boundary (placeholder + §"Cross-Server STT Transit Boundary" eklendi 2026-06-03)
- **ADR-0031 Two-Server Meeting Intelligence Topology** ACCEPTED 2026-06-03 (gitops PR #1233 MERGED — D1-D8 host boundary + network topology + resource pressure + GPU + deployment + Vault + KVKK + failure modes)
- Observability skeleton: `docs/observability-skeleton-meeting-intelligence.md`
- platform-ai PR #1 MERGED `4088d9a` — live-stt-service PoC iskelet
- platform-ai PR #199 MERGED `243de9d` — G-WER/DER gate verifier
- platform-ai PR #200 MERGED `7cc2612` — G-INT gate verifier
- platform-ai PR #201 MERGED `3549c28` — #156 retention readiness gate
- platform-ai PR #202 MERGED `74d55b6` — Redis consumer control-plane semantics
- platform-ai PR #203 MERGED `546bf13` — #185 recording/archive boundary (platform-ai-scoped ADR-0036, not gitops ADR-0036)
- platform-ai PR #204 MERGED `1c9a2cc` — G-LAT/COST gate verifier
- platform-ai Issue #19 re-scope (Faz 24 two-host resource baseline — ADR-0031 ile uyumlu)
- Global HARD RULE: Cross-AI Peer Review provider seviyesinde + Plan Consensus Autonomy + No Fake Work + Türkçe cevap + Uzun Vadeli Kalıcı Çözüm
