# Faz 24 — Meeting Intelligence / STT Platform Canonical Plan

> **Status**: ACTIVE (2026-06-02, 3-AI mutabakat sonrası sabit)
>
> **Mutabakat trail**: Claude (Anthropic) + Codex `019e879c` (OpenAI, AGREE final) + Mavis `mvs_c922505d66a94a45b031feb3489f9488` msg `78` (MiniMax, AGREE).

---

## 1. Vizyon

Workcube ERP'ye entegre toplantı zekâsı platformu. Telefon / masaüstü / Teams ses kaynaklarından:

- Canlı geçici transkript (2-8 sn gecikme)
- Kesinleşmiş transkript (10-20 sn bağlamlı)
- Konuşmacı ayrımı (diarization)
- Özet + karar + aksiyon LLM çıkarımı
- KVKK uyumlu retention + audit + consent

üretir. **STT compute worker yapısı** (`platform-ai`) Spring Boot orchestration arkasında konumlanır — mobile/web hiçbir zaman doğrudan Python servisine bağlanmaz.

## 2. Repo Topology

| Repo | Rol | Durum |
|---|---|---|
| `platform-ai` | Python STT/diarization/meeting-ai (FastAPI + faster-whisper + pyannote + LLM) | 🟢 live-stt-service PoC iskelet LIVE (PR #1 MERGED `4088d9a`) + correlation_id + Prometheus metrics LIVE |
| `platform-backend` | Spring Boot — `audio-gateway-service` (WebFlux) + `meeting-service` + `transcript-service` | 🟢 audio-gateway-service LIVE main'de (commit `6fa713b5`); meeting/transcript planlı (M6) |
| `platform-web` | React + Single-SPA — `mfe-meeting` MFE | ⏳ planning (M6) |
| `platform-mobile` | **React Native + Expo** + TypeScript — iOS + Android mobile client | 🟢 **YENI scaffold LIVE 2026-06-02** (commits `a774412` + `3a609a8`) — Expo SDK 52 + RN 0.76 + expo-audio + expo-auth-session + EAS Build + 10 slice issue (#85-94) |
| `platform-desktop` | **Electron + React** + TypeScript — macOS + Windows + Linux desktop client | 🟢 **YENI scaffold LIVE 2026-06-02** (commit `a245578`) — Electron 33 + React 19 + Vite 6 + electron-builder cross-platform + 10 slice issue (#75-84) |
| `platform-k8s-gitops` | Kustomize + ArgoCD GitOps + ADR-0030 + observability skeleton | 🟢 charter LIVE (PR #1207 MERGED) + bu doküman güncelle |

## 3. 3-AI Mutabakat Noktaları (her biri 3 AI tarafından onaylı)

### 1. STT compute worker ≠ ürün API'si

`live-stt-service` iç compute worker'dır; mobile/web hiçbir zaman doğrudan `platform-ai`'a bağlanmaz.

**Neden**: Auth / tenant / audit / permission / KVKK pattern'leri Spring Boot Gateway'de (Workcube ERP konvansiyonu). `live-stt`'ye client WebSocket koymak = yanlış ownership boundary + deprecation borcu.

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

**Neden**: Workcube müşteri çeşitliliği multi-dil destek gerektirir. Sonradan eklemek = breaking change retroaktif.

### 7. Worker isolation = b + d kombinasyonu

- **b**: STT tarafında supervised subprocess (multiprocessing.Process); timeout = process kill semantic + temiz worker re-start
- **d**: Gateway + Redis bounded queue + admission control + hızlı reject

**Neden**: `asyncio.wait_for` yalnızca HTTP client'a cevap; worker thread arka planda CPU+model lock tutmaya devam edebilir. `ProcessPoolExecutor` `future.cancel()` çalışan native inference'ı öldürmez.

### 8. WER PoC = Common Voice TR + gerçek pilot meeting (triangulate)

Sentetik TTS yalnızca pipeline smoke/CI (WER claim için kullanılmaz).

**Neden**: Sentetik "okuma" sesi meeting domain'i (overlap, duraksama, aksan, arka plan) yansıtmaz.

### 9. Staging resource pressure acceptance gate

PR-stt-02 e2e öncesi `free -m` + `kubectl top` baseline + Faz 22-23 paralel çakışma notu.

**Neden**: staging-sw 23 GiB RAM / 6.2 GiB available + GPU yok. Faz 22.5 PR-D2.5 + Faz 23 notify + STT PoC aynı host. Sessiz capacity exhaustion = belirsiz fail.

### 10. Multi-tenant readiness placeholder

Faz 24.1 MVP tek müşteri OK, ama ADR-0030'da "future multi-tenant readiness" placeholder — tenantId metadata + auth token validation Gateway seviyesinde.

**Neden**: Workcube dışı müşteri girişi geldiğinde retroactively eklemek pahalı.

---

## 4. 3 RED (yapılmayacak — Codex + Mavis ortak)

1. ❌ **Gateway contract kilitlenmeden** mobile/Web veya STT WebSocket contract yazılması
2. ❌ **KVKK ADR olmadan** gerçek Workcube meeting kaydı kullanılması
3. ❌ **Synthetic WER ile** model kararı kapatılması

---

## 5. Faz 24 Akış (3-AI sabit)

```
Adım 0  (BU PR)
   ├─ ADR-0030 KVKK Meeting Intelligence boundary (placeholder)
   ├─ Observability/Audit GOP skeleton (correlation id + log + metric + audit event contract)
   └─ PLAN.md Faz 24 satırı + canonical plan (bu doküman)
        ↓
PR-gw-01  Audio Gateway Contract 1.0 freeze (platform-backend)
   fields: language (ISO 639-1) + correlation_id + meeting_id + session_id + tenant_id + user_id + auth + audio chunk metadata + admission contract
        ↓
PR-stt-02  real audio + Docker e2e + resource pressure baseline (platform-ai)
   Gateway contract uyumlu language/correlation metadata; staging top + free -m baseline; Türkçe wav fixture (Common Voice TR sample veya privacy-safe TTS)
        ↓
PR-stt-03  supervised subprocess worker + hard timeout kill (platform-ai)
        ↓
PR-queue-01  bounded Redis admission + Gateway → STT producer/consumer
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
| platform-k8s-gitops (Adım 0) | ADR-0030 + obs skeleton + PLAN.md | yok (BU PR) |
| platform-backend | PR-gw-01 Gateway Contract 1.0 | Adım 0 MERGED |
| platform-ai | PR-stt-02 real audio + container e2e | PR-gw-01 MERGED |
| platform-ai | PR-stt-03 subprocess isolation | PR-stt-02 MERGED |
| platform-k8s-gitops | Kustomize base/apps/{audio-gateway,live-stt} + overlay | PR-gw-01 + PR-stt-03 source-merged |
| platform-backend | PR-queue-01 Redis producer/consumer | PR-stt-03 MERGED |
| platform-k8s-gitops | helm-values/redis + ESO | paralel PR-queue-01 |
| platform-k8s-gitops | PR-obs-01 dashboard + alertmanager rules | PR-queue-01 MERGED |
| platform-ai | PR-wer-01 WER raporu | PR-stt-03 MERGED + pilot meeting kaydı |
| platform-ai | PR-final-stt-01 | WER raporu çıktısına göre |
| platform-ai | PR-gpu-01 | donanım + ölçüm sonrası |
| **platform-mobile** | **scaffold LIVE + 10 slice (#85-94)** | PR-gw-01 + PR-queue-01 LIVE testai | 🟢 **scaffold LIVE 2026-06-02** (`a774412`+`3a609a8`) |
| **platform-desktop** | **scaffold LIVE + 10 slice (#75-84)** | PR-gw-01 + PR-queue-01 LIVE testai | 🟢 **scaffold LIVE 2026-06-02** (`a245578`) |
| platform-web | mfe-meeting MFE | PR-gw-01 + PR-queue-01 LIVE testai | ⏳ M6 |
| platform-backend | meeting-service + transcript-service | PR-gw-01 paralel | ⏳ M6 |
| platform-backend | Faz 23 notification entegre (meeting events) | M6 ortası | ⏳ M6 |
| platform-backend | report-service weekly-meeting-summary | M6 sonu | ⏳ M6 |

## 7. Donanım & Resource Stratejisi

### Mevcut

- **staging-sw**: 23 GiB RAM, 6.2 GiB available, GPU **YOK**
- Faz 22-23 paralel workload (Faz 22.5 PR-D2.5 + Faz 23 notify) aynı host

### PoC Aşaması (Faz 24.0-24.6)

- CPU-only Whisper `medium int8` (~1.5 GB model)
- Tek worker, çoklu request threadpool serial (b+d isolation)
- Staging resource pressure gate her e2e öncesi: `free -m` available > 2 GiB minimum

### MVP Aşaması (Faz 24.7-24.9)

- Cloud GPU bridge (Lambda Labs / Vast.ai saatlik) ile WER PoC
- Maliyet ölçüm + production karar (self-host vs SaaS)

### Production Aşaması

- Karar: staging-sw donanım upgrade (RTX 4070 12 GB VRAM) **veya** k3d-prod node-pool ile dedicated GPU node **veya** cloud GPU node-pool
- WER + latency + cost data-driven karar

## 8. Risk Matrix (3-AI mutabakat sonrası)

| Risk | Önlem | Sahibi |
|---|---|---|
| Gateway contract drift (STT iki yere bağlı) | Contract 1.0 freeze ÖNCE; ayrıca contract test (consumer-driven) | PR-gw-01 |
| Worker thread leak (asyncio.wait_for) | Subprocess + hard kill semantic (PR-stt-03) | platform-ai |
| KVKK compliance (ses+transcript hassas) | ADR-0030 placeholder + hukuk review pilot öncesi | Adım 0 + ek tur |
| Staging resource exhaustion (Faz 22-23 paralel) | Acceptance gate `free -m`/`kubectl top` baseline | her PR-stt-* |
| Türkçe doğruluk düşük kalır | Common Voice TR + pilot meeting WER triangulate (sentetik yok) | PR-wer-01 |
| Model kararı erken kilitlenir | `large-v3-turbo` varsayım yok; WER sonrası karar | PR-final-stt-01 |
| GPU yatırım atıl kalır | PoC CPU önce → ölç → GPU karar (Adım 24.7+) | PR-gpu-01 |
| Multi-tenant retroactive zorluk | ADR placeholder + tenantId reserved field şimdi | ADR-0030 |
| LLM API yurt dışı veri akışı | Option A (transcript only, no audio) → Option B (self-host) karar | pilot öncesi |
| Mobile RN/Expo test harness yetersiz | Detox e2e + Expo dev preview (browser MCP mobile için yetmez) | Faz 24.5 |

## 9. Acceptance Gates (D29 paralel)

| Layer | Gate |
|---|---|
| **Up** | Pod Running + TCP reachable + `/health` 200 |
| **Functional** | `POST /transcribe` real audio fixture ile 200 + non-empty text + meta complete |
| **KVKK-safe** | Audit event emit + log redaction verify + access RBAC enforce + retention policy applied |
| **Resource-pressure-safe** | `free -m` available > 2 GiB + `kubectl top` Faz 22-23 paralel uyumlu |
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

## References

- Codex thread: `019e879c-c51e-7691-8f16-69c781fb787e` (plan-time + iter-3 AGREE final)
- Codex thread: `019e877b-bd31-72f3-b86a-229f933e51cb` (live-stt PR #1 review AGREE)
- Mavis msgs: `74` (PARTIAL), `76` (absorb wait), `78` (AGREE final)
- ADR-0030 KVKK Meeting Intelligence Boundary (placeholder)
- Observability skeleton: `docs/observability-skeleton-meeting-intelligence.md`
- platform-ai PR #1 MERGED `4088d9a` — live-stt-service PoC iskelet
- Global HARD RULE: Cross-AI Peer Review provider seviyesinde + Plan Consensus Autonomy + No Fake Work + Türkçe cevap
