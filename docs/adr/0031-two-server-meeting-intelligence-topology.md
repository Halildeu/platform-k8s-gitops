# ADR-0031 — Two-Server Meeting Intelligence Topology (platform-ai Compute Plane + staging-sw Orchestration Plane)

> **Status**: ACCEPTED (2026-06-03) — Codex `019e8c09` iter-1+iter-2+iter-3 REVISE absorb + iter-4 **AGREE final** (Plan Consensus Autonomy + HARD RULE Cross-AI Peer Review provider seviyesinde Anthropic + OpenAI).
>
> **Scope**: Faz 24 Meeting Intelligence için fiziksel host topolojisi, network/secret cross-server boundary, deployment çatısı. ADR-0002 (single-host dual-cluster, Faz 1-23 core platform) **supersede edilmez**; bu karar Faz 24 `platform-ai` compute plane için **scoped forward-extension**'dur.
>
> **Cross-AI trail**: Claude (Anthropic) + Codex `019e8c09` (OpenAI) iter-1 REVISE → iter-2 REVISE → iter-3 REVISE → iter-4 **AGREE final** ("Iter-4 source-side review'da merge blocker bulmadım"). Mavis (MiniMax) post-availability absorb/comment **non-blocking** (HARD RULE Cross-AI Peer Review provider seviyesinde Anthropic + OpenAI yeterli; Mavis kanıt/koordinasyon trail değeri var ama bu karar için hard gate değil — kullanıcı explicit 3-provider gate'e escalate ederse blocker olur).

---

## Context

Kullanıcı 2026-06-03 itibarıyla Faz 24 mimari kararını netleştirdi:

> "burda en önemli konulardan biri platform-ai ayrı sunucuda diğerleri hepsi aynı sunucuda"

Yorum:

- `platform-ai` (Python STT/diarization/meeting-ai compute) → **AYRI fiziksel sunucu** (dedicated, ileride GPU host olacak)
- `platform-backend` (audio-gateway-service + meeting-service + transcript-service + Faz 22-23 notify/report) → **staging-sw** (mevcut single-host)
- `platform-web` mfe-meeting → staging-sw (frontend serve)
- `platform-mobile` + `platform-desktop` → kullanıcı cihazları (ayrı; client-side)
- `platform-k8s-gitops` → manifest + ArgoCD (mevcut ADR-0002 ile uyumlu)

Mevcut Faz 24 plan (`docs/faz-24-meeting-intelligence-plan.md` §7/§9) **single-host (staging-sw)** varsayımıyla yazılmış:

- §7 staging-sw 23 GiB RAM / 6.2 GiB available + GPU YOK + Faz 22-23 paralel workload
- §9 acceptance gate Resource-pressure-safe: `free -m available > 2 GiB` (tek host gate)

Bu varsayım yeni karar ile **stale**. Codex `019e8c09` iter-1 RED değil ama: *"dokümanlar revize edilmeden PR-gw-01 / PR-stt-02 execution'a geçilmemeli"*. Bu ADR + ilgili plan/ADR/issue update'leri **gerçek meeting audio ile PR-stt-02 e2e öncesi blocker**.

## Decision

### D1 — Fiziksel host boundary

| Plane | Host | Workload | Sahip |
|---|---|---|---|
| **Orchestration plane** | staging-sw (mevcut 23 GiB RAM) | `audio-gateway-service`, `meeting-service`, `transcript-service`, `notification`, `report-service`, Faz 22-23 workloads, Redis, Vault, ArgoCD hub, host nginx edge | Spring Boot + Java ekosistem |
| **Compute plane** | **platform-ai** (yeni dedicated server) | `live-stt-service`, `diarization-service` (ileri faz), `meeting-ai-service` (LLM özet/karar/aksiyon), worker subprocess pool | Python + faster-whisper + pyannote + LLM client |
| **Client plane** | Kullanıcı cihazları | platform-mobile (iOS/Android) + platform-desktop (macOS/Win/Linux) | RN/Expo + Electron |

Client'lar **hiçbir zaman** doğrudan `platform-ai`'a bağlanmaz (mevcut 3-AI mutabakat noktası #1 korunur). Bağlantı tüm zaman `audio-gateway-service` üzerinden (staging-sw → cross-server → platform-ai).

### D2 — Network topology (Gateway ↔ STT cross-server)

```
[client/mobile/desktop/web]
         │  Authorization: Bearer <jwt>
         ▼
[host nginx edge — staging-sw]
         │  TLS terminate
         ▼
[audio-gateway-service — staging-sw]
   │  JWT validate + tenant/correlation derive
   │  admission control + audio format whitelist
   │  fail-fast 401/415/503
   ▼
[Redis bounded queue — staging-sw]  ← transient, bounded, persistence OFF, TTL kısa
   │  audio chunk push (binary blob + metadata)
   │  Gateway owns queue lifecycle (admission, rate limit, tenant fairness)
   ▼  PULL/CONSUME (cross-server)
[live-stt-service — platform-ai server]
   │  mTLS / WireGuard cross-server kanal
   │  Vault PKI cert veya SPIFFE workload identity
   │  worker subprocess pool (PR-stt-03)
   ▼
   transcript payload + meta → callback Gateway (staging-sw) → transcript-service persist
```

**Redis konumu**: **staging-sw** (Codex iter-1 AGREE). Sebep:
- Admission control + tenant rate limit + fail-fast Gateway ownership'i (auth/audit/policy boundary)
- Bounded queue **transient** (durable storage gibi davranmamalı): kısa TTL, bounded memory, persistence kapalı, backlog threshold aşınca 429/503 fail-fast
- Raw audio backlog "kalıcı" değil — STT consume edemezse fail-fast (Gateway 503 → client retry)

**Cross-server kanal**: Private LAN **yetmez** (Codex iter-1 net). Ses + transcript = KVKK hassas transit. Zorunlu:

- **MVP**: WireGuard host-to-host + TLS service auth (TLS-pinned)
- **Production**: mTLS / Vault PKI cert auth / SPIFFE-benzeri workload identity
- Synthetic/public fixture PoC için private LAN **geçici** kabul edilebilir (PR-stt-02 fixture testi); gerçek meeting audio için kabul edilmez

**Forward header set** (Gateway-derived, client-trusted DEĞİL — mevcut Project #4 Issue #6 ile uyumlu):

- `X-Correlation-Id` (required)
- `X-Meeting-Id` (required)
- `X-Session-Id` (required)
- `X-Device-Id` (required)
- `X-Tenant-Id` (JWT-derived)
- `X-User-Id` (JWT-derived)
- `language` (ISO 639-1)
- `audio_metadata` (format, sampleRateHz, channels, chunkSeq, chunkStartedAtMs)

### D3 — Resource pressure gate split (Faz 24 plan §9 Resource-pressure-safe revize)

Mevcut tek gate `free -m available > 2 GiB` (staging-sw için) yetmez. **Codex iter-1 absorb — iki ayrı gate**:

#### Gate A — staging-sw orchestration plane

| Metric | Threshold | Komut/Probe |
|---|---|---|
| `free -m` available | > 2 GiB | `free -m \| awk '/Mem/ {print $7}'` |
| Pod RAM headroom (audio-gateway, meeting-service, transcript-service) | < 70% requests | `kubectl top pod -l app=<svc>` |
| Pod CPU p95 (5dk pencere) | < 80% limit | `kubectl top pod` |
| Ingress p95 latency | < 200 ms | Prometheus `nginx_ingress_request_duration_seconds` |
| Redis Streams depth (per partition) | < MAXLEN threshold (bounded) | `redis-cli XLEN audio:chunks:p<NN>` (32 partition `p00..p31`) — **primitive Streams + consumer group `live-stt-v1`** (Codex `019e8c09` iter-2 + `019e97bb` iter-1 confirm: chunk ordering + consumer lag + idempotency (sessionId, chunkSeq) Streams ile temiz; List primitive YASAK); contract canonical: PR-gw-01C platform-backend producer + PR-stt-03 platform-ai consumer (scope genişledi — bkz Faz 24 plan §5 + PR-gw-01C #106 issue) |
| OOM/restart count (24h) | 0 | `kubectl get pod -l app=<svc> -o jsonpath` |
| Faz 22-23 paralel CPU pressure | normal (load average < CPU count) | `uptime` |

#### Gate B — platform-ai compute plane (yeni)

| Metric | Threshold | Komut/Probe |
|---|---|---|
| Model warm-load sonrası RAM | < 70% total | `free -m` (platform-ai host) |
| Worker subprocess count | konfigurasyona uyumlu | `ps -ef \| grep live-stt-worker` |
| GPU VRAM headroom (varsa) | > 2 GiB free | `nvidia-smi --query-gpu=memory.free --format=csv` |
| GPU driver/runtime readiness | OK | `nvidia-smi` + `nvidia-container-cli info` |
| Inference p95 latency (1 session) | < 5 sn (PoC), < 2 sn (MVP) | Prometheus `stt_transcribe_duration_seconds` |
| Queue consume lag | < 5 sn | Redis stream consumer offset diff |
| Process kill/restart davranışı (subprocess timeout) | clean exit + worker re-spawn | `journalctl -u live-stt-worker` |
| Disk/cache kullanımı (HF cache) | < 80% partition | `df -h ~/.cache/huggingface` |

#### Issue #19 re-scope

Mevcut Issue #19 (platform-ai repo): "staging resource pressure baseline" — single-host varsayımı.

**Re-scope**: **"Faz 24 two-host resource baseline: staging-sw orchestration + platform-ai STT compute"**

Acceptance maddeleri:
- [ ] Gate A baseline ölçüm (staging-sw)
- [ ] Gate B baseline ölçüm (platform-ai)
- [ ] platform-ai-down failure drill (Gateway 503 + Redis backlog davranışı)
- [ ] Redis backlog threshold / admission behavior verify
- [x] Plan §7/§9 truth update (✓ gitops PR #1233 MERGED 2026-06-03; canonical sync iter gitops PR #1289 2026-06-05)
- [ ] Evidence path linkleri (Prometheus snapshot + free/top output)

### D4 — GPU stratejisi netleşme

Mevcut plan §7 MVP "Cloud GPU bridge (Lambda Labs / Vast.ai)" varsayımı **stale**. İki-sunucu topolojisi ile:

- **platform-ai server kendi GPU bulundurabilir** (kontrol edilebilir, vendor lock-in yok, KVKK sınır içi)
- staging-sw GPU upgrade gereksiz (Spring Boot orchestration → CPU yeterli)
- "Cloud GPU bridge" tahmininden **"self-host GPU on platform-ai dedicated server"** stratejisine kayma
- PoC (Faz 24.0-24.6) CPU-only Whisper medium int8 (platform-ai kendi CPU/RAM)
- MVP (Faz 24.7+) platform-ai GPU upgrade (örn. RTX 4070 12 GB VRAM) veya dedicated GPU node-pool
- Karar PR-gpu-01'de mühürlenir (WER + latency + cost data-driven karar)

### D5 — Deployment topology

Codex iter-1 4 opsiyon değerlendirdi:

| Opsiyon | Codex Verdict | Sebep |
|---|---|---|
| (a) Aynı k3d cluster farklı node | **RED** | k3d multi-node fiziksel hostlar arası doğal değil; failure/ops boundary bulanık |
| (b) Ayrı k3s cluster (k3d **değil**) | **AGREE** ✅ | GPU host'ta Docker-in-Docker/k3d plumbing yok; lightweight k3s AI cluster doğal |
| (c) Docker Compose standalone | PARTIAL | PoC OK; product/GitOps truth için zayıf |
| (d) systemd unit standalone | PARTIAL | Düşük overhead; ArgoCD/ESO/observability/discovery dışına taşar |

**Karar**: **(b) Ayrı k3s cluster** — platform-ai host'unda lightweight k3s (k3d **değil**, fiziksel host için doğru tool).

- platform-ai host: `ai-test` (PoC) → ileride `ai-prod` (production)
- ArgoCD hub staging-sw'da: platform-ai k3s'i **remote cluster** olarak register
- Başlangıçta sadece `ai-test`; prod claim için ayrı `ai-prod` boundary + ayrı secret role + ayrı evidence

#### D5 Amendment — PoC fiili deploy modeli: Windows host + Scheduled Tasks (2026-06-11)

Fiili durum D5'in (d)-benzeri bir varyantına evrildi ve **PoC dönemi için
resmi kabul edilir**: GPU host **Windows** (RTX 4070) — k3s Linux gerektirir;
PoC pragmatizmi `deploy/gpu-host/install.ps1` (platform-ai repo) ile
**Windows Scheduled Tasks** modeline gitti:

- `platform-ai-live-stt` (:8200) + `platform-ai-meeting-ai` (:8300), SYSTEM
  hesabı, boot'ta otomatik başlama + çökmede ~1 dk içinde restart
- Deploy = `git pull` + `Restart-ScheduledTask` (manuel; immutable artifact
  YOK — D30 disiplini bu hat için askıda)
- Dış erişim: Cloudflare quick tunnel (IPv4 origin); cross-server chunk
  hattı Redis Streams üzerinden (staging-sw — gitops#1447 zinciri)
- Canlı kanıt: Aşama-1 browser smoke 6/6 PASS + kalıcı GPU prod deploy
  (platform-ai #134-#145; go-live-signoff G2)

**Sınırlar (amendment'ın kapsamı)**:
1. Bu kabul **PoC/Faz 24 MVP dönemi** içindir — production go-live (#59 D30
   cutover) öncesi şu üçünden biri seçilip mühürlenir: (i) k3s'e geçiş
   (orijinal D5-b; GPU host'a Linux veya ikinci Linux host), (ii) Windows
   modeli production-grade sertleştirme (immutable artifact + signed release
   + otomatik rollback + drift detection), (iii) hibrit (compute Windows'ta
   kalır, orchestration k8s'te proxy/health-bridge). Karar ayrı ADR/amendment.
2. ArgoCD remote-register + Vault AppRole `ai-runtime-test` (D6) bu modelde
   ertelenir — ESO yerine env/host secret yönetimi (KVKK sınırları D7/ADR-0030
   ile korunur; loglar transcript-free).
3. GitOps truth: platform-ai servis sürümleri bu dönemde git SHA üzerinden
   izlenir (`git pull` anındaki main); release tag disiplini önerilir.

Cross-AI not: D5-b kararının orijinal gerekçesi (Codex `019e8c09`) Linux host
varsayımına dayanıyordu; Windows GPU host gerçeği o varsayımı geçersiz kıldı.
Bu amendment fiili durumu mühürler ve production seçimini açık bırakır
(go-live-signoff G11 maddesi).

### D6 — Vault secret rotation cross-server

Vault staging-sw'da kalır. platform-ai host Vault'a **WireGuard/VPN + TLS-pinned remote API** ile erişir.

**Auth method** (Codex iter-1 nüans):

- **AppRole** (mevcut ADR-0010 `eso-runtime` read-only pattern reuse) — **birinci tercih**
  - `ai-runtime-test` / `ai-runtime-prod` env-scoped role
  - Read-only policy (yalnız STT'nin ihtiyaç duyduğu secret path)
  - Kısa SecretID rotation, no-root-token, no-secret-log, accessor-only audit
  - Mevcut governance pattern ile uyumlu
- **Vault Kubernetes auth (projected ServiceAccount token)** veya **JWT/OIDC** — **ikinci tercih**
  - Sadece **gerçek workload identity** (bound issuer/audience/subject/namespace/serviceAccount + kısa TTL) ise
  - "Bir yere yazılmış uzun ömürlü JWT dosyası" YASAK
  - k3s ai-cluster'da ServiceAccount token projected mount → bound audience → Vault JWT auth role
- **Cert auth** — alternatif (Vault PKI ile workload cert)

Karar (MVP): **AppRole `ai-runtime-test`/`ai-runtime-prod` role** + ESO sidecar ya da Vault Agent injection. Production cutover'a kadar k3s workload identity pattern (Kubernetes auth method) **değerlendirilir**, AppRole'dan geçiş ayrı ADR ile.

### D7 — KVKK ADR-0030 bağlantısı (yeni section talep)

ADR-0030 KVKK Meeting Intelligence Boundary'de cross-server hop eksikti. Bu ADR ile ADR-0030'a aşağıdaki section **eklendi** (gitops PR #1207 + #1233 MERGED 2026-06-03):

**"Cross-Server STT Transit Boundary"** — içerik:

- Gateway staging-sw → platform-ai raw audio chunk flow boundary
- mTLS / WireGuard / Vault PKI / SPIFFE workload identity zorunlu (private LAN yetmez)
- Tenant / correlation / session propagation (X-* headers, JWT-derived)
- Audit event: `audio_chunk_forwarded_to_platform_ai` emit (per chunk veya batch)
- Redis transient/bounded policy (TTL, persistence OFF, backlog fail-fast)
- platform-ai host access boundary (SSH + Vault credentials + audit)
- Log redaction cross-server (transcript text / audio path payload'a düşmez)
- Failure/backlog behavior (Gateway 503 + Redis fail-fast, no silent drop)
- No direct client-to-STT rule (mobile/desktop/web Gateway zorunlu)
- Backup/cache retention (HF model cache, transcript cache, audio cache TTL)
- Legal controller-processor boundary (müşteri/tenant ERP-CRM alan sahibi = controller; platform-ai host operator = processor; DPA gerek; belirli ERP/CRM markası yalnız pilot/adaptör örneği)

### D8 — Cross-server failure modes

| Senaryo | Davranış |
|---|---|
| platform-ai host network unreachable | Gateway 503 fail-fast + Redis queue backlog kısa süre tolerate, threshold sonra admission reject |
| platform-ai host crash | Gateway 503 + circuit breaker + alert; Redis queue drain (transient TTL nedeniyle veri kaybı kabul — KVKK sınır içi) |
| Cross-server mTLS cert expire | Gateway → STT TLS handshake fail → fail-fast 503; Vault PKI auto-rotate alert |
| Vault staging-sw unreachable (platform-ai açısından) | STT mevcut secret cache ile TTL kadar devam + alert; TTL sonra crash; circuit breaker |
| Redis staging-sw unreachable (STT açısından) | STT consume fail + alert; Gateway admission control reject (Redis push fail = 503) |
| WireGuard tunnel down | Network unreachable senaryosuyla aynı + alert |
| LAN packet loss (cross-server jitter) | Audio chunk retry + idempotency (chunkSeq) + transcript ordering guarantee |

## Cross-AI Mutabakat Trail

| Soru | Codex `019e8c09` iter-1→iter-4 AGREE final | Claude | Mavis msg `78` AGREE final 2026-06-03 |
|---|---|---|---|
| Redis konumu | staging-sw ✅ | AGREE | AGREE ✅ |
| Cross-server kanal | WireGuard + mTLS/PKI ✅ | AGREE | AGREE ✅ |
| Resource gate ayrımı (A + B) | AGREE ✅ | AGREE | AGREE ✅ |
| Deployment topology | (b) ayrı k3s ✅ | AGREE | AGREE ✅ |
| KVKK ADR-0030 section | yeni "Cross-Server STT Transit Boundary" ✅ | AGREE | AGREE ✅ |
| Vault auth method | AppRole birinci tercih ✅, JWT ikinci | AGREE | AGREE ✅ |
| ADR-0031 yeni mi | yeni ADR-0031 ✅ | AGREE | AGREE ✅ |

## ADR-0002 İlişkisi

ADR-0002 (single-host dual-cluster k3d-test + k3d-prod, Faz 1-23 core platform) **supersede edilmez**. Bu ADR onu Faz 24 `platform-ai` compute plane için **scoped genişletir**:

- ADR-0002 core platform (Spring Boot + web + secret + monitoring) staging-sw'da devam eder
- ADR-0031 Faz 24 STT compute platform-ai dedicated host'ta paralel çalışır
- Cross-server boundary bu ADR'de mühürlenir; core platform'un kendi state'i etkilenmez

## Production Çıkış Kapısı (Gate)

Bu ADR'nin production'a katkı verdiği maddeler, **Faz 24 servisleri production'a çıkmaz** şu maddeler tamamlanana kadar:

- [ ] platform-ai dedicated host provisioned + k3s ai-test cluster LIVE
- [ ] ArgoCD remote cluster register edildi (platform-ai k3s)
- [ ] WireGuard tunnel + mTLS PKI cert auth LIVE + cert rotation drill geçti
- [ ] Vault AppRole `ai-runtime-test` role + ESO/Vault Agent injection LIVE
- [ ] staging-sw Redis Streams `audio:chunks:p00..p31` 32 partition + consumer group `live-stt-v1` + persistence-off + MAXLEN + maxmemory-policy noeviction backlog threshold doğrulandı (D3 + PR-gw-01C contract dependency)
- [ ] Gate A (staging-sw) baseline + Gate B (platform-ai) baseline ölçüm dokümante
- [ ] Failure drill: platform-ai-down + Redis backlog + Vault unreachable senaryoları (D8 + plan §3 mutabakat #9)
- [x] ADR-0030 §"Cross-Server STT Transit Boundary" eklendi (✓ gitops PR #1207 MERGED 2026-06-03)
- [ ] Issue #19 re-scope edildi + Gate A/B acceptance verify
- [x] Cross-AI peer review canonical (✓ Codex `019e8c09` iter-1+iter-2+iter-3 REVISE absorb + iter-4 AGREE final 2026-06-03 ADR baseline; ✓ Codex `019e97bb`+`019e97c3`+`019e97cc`+`019e97d2` iter-1/2/3/4 REVISE absorb → iter-5 AGREE final plan canonical sync 2026-06-05; ✓ Mavis msg `78` AGREE; HARD RULE Anthropic + OpenAI provider isolation satisfied)

## References

- ADR-0002 (single-host dual-cluster — core platform Faz 1-23 baseline)
- ADR-0010 (Vault credential lifecycle — `eso-runtime` AppRole pattern reuse)
- ADR-0030 (KVKK Meeting Intelligence Boundary — §"Cross-Server STT Transit Boundary" eklendi gitops PR #1207 2026-06-03)
- `docs/faz-24-meeting-intelligence-plan.md` §7 Donanım + §9 Acceptance Gates (gitops PR #1233 2026-06-03 ACCEPTED)
- Codex threads:
  - `019e879c` (Faz 24 plan iter-3 AGREE — single-host varsayımıyla)
  - `019e8c09` (bu ADR iter-1 REVISE absorb)
- Global HARD RULE:
  - Cross-AI Peer Review (provider seviyesinde Anthropic + OpenAI)
  - Plan Consensus Autonomy (Codex AGREE → impl)
  - Mavis CLI (multi-session koordinasyon)
  - Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi (browser smoke Gate)
  - No Fake Work (doğrulanmamış adım sayılmaz)
  - Uzun Vadeli Kalıcı Çözüm Tercih Edilir (cross-server boundary kalıcı tasarım)

## Historical acceptance path (2026-06-03 closed)

1. ✓ Codex `019e8c09` iter-1/2/3 REVISE absorb + iter-4 AGREE final — bu ADR + plan §7/§9 + ADR-0030 §"Cross-Server STT Transit Boundary" + Issue #19 re-scope
2. ✓ Mavis msg paralel mutabakat (msg `78` AGREE)
3. ✓ Plan §7/§9 + ADR-0030 update + Issue #19 update (gitops PR #1207 + #1233)
4. ✓ PR açıldı → cross-AI AGREE → merge (gitops PR #1233 MERGED 2026-06-03)
5. ✓ ADR-0031 ACCEPTED (gitops PR #1233 squash merge ile aktif — Status: ACCEPTED line 3)
6. ✓ PR-gw-01A/B-core/B3 MERGED 2026-06-03 (platform-backend #390+#403+#421); plan canonical sync 2026-06-05 (gitops PR #1289 Codex thread chain `019e97bb`→`019e97c3`→`019e97cc`→`019e97d2` iter-1/2/3/4 REVISE absorb → iter-5 AGREE final)

## Sonraki adımlar (downstream)

- PR-gw-01C platform-backend impl (Redis Streams cross-server dispatcher producer; contract canonical D2 + D3 + D8)
- staging-sw Redis Streams runtime setup runbook (`docs/runbooks/redis-streams-staging-sw.md`)
- PR-stt-03 platform-ai impl (subprocess worker + Redis Streams consumer scope genişledi)
- Issue #19 Gate A + Gate B baseline ölçüm verify
- platform-ai dedicated host provision + k3s ai-test cluster + WireGuard + mTLS + Vault AppRole (operator action)
