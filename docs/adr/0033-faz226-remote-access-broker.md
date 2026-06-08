# ADR-0033 — Faz 22.6 Remote Access Broker

> **Status**: PROPOSED / **BLOCKED** — runtime iki kapıya bağlı:
> 1. [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) Sensitive Endpoint Ops Governance Gate (owner/DPO/legal acceptance)
> 2. ADR-0012-EA §0 governance-drift reconciliation (extended D35-EA ladder + DD-EA-8 canonical olmadan runtime yok)
>
> **Tarih**: 2026-06-09 · **İlişkili**: platform-backend #524 (broker ADR/state machine), #510 (22.6 umbrella), platform-agent #116 (tunnel spike), ADR-0012-EA, ADR-0029 (mTLS/edge), [docs/faz-22-remote-access-bridge-plan.md](../faz-22-remote-access-bridge-plan.md)
> **Cross-AI consensus**: Implementer Claude (Opus 4.8) / Reviewer Codex (OpenAI) — thread `019ea961-561d-73a3-acf8-ad9f02a317b6`, **REVISE → REVISE → AGREE** (plan + execution).

Bu ADR, Faz 22.6 Remote Access Bridge'in **broker servisi**ni (transport, oturum
durum makinesi, yetkilendirme, audit, izolasyon, KVKK) sektör standartlarında
(NIST SP 800-53 AC-17/AC-12/AU-10, NIST 800-207 zero-trust, PAM/PASM session
brokering, SPIFFE/SVID, ISO 27001, SOC2) tanımlar. **Hiçbir LIVE iddiası
içermez**; planning/governance artifact'ıdır.

---

## Bağlam

Faz 22.6, managed Windows endpoint'lere **interaktif uzaktan destek** verir. Bu,
endpoint programının (Endpoint-Enes) **en yüksek blast-radius** kabiliyetidir:
uninstall + tamper + password-reset + arbitrary-exec'i **canlı + interaktif**
kapsar. Tehdit modelinin tek cümlesi: **broker compromise = fleet remote-control
attempt.** Bu yüzden mimari, control-plane'i data-plane'den ayırır ve broker'ı
yetki üretemeyen bir doğrulayıcı/relay'e indirger.

22.5 yazılım yönetimi **HTTP command-poll** modelini kullanır; 22.6 bunu
**replace etmez** — yalnız oturum rendezvous sinyali için kullanır.

---

## Karar (PROPOSED)

### 1. Transport — outbound-only WebSocket-over-TLS + rendezvous via 22.5 poll

- Endpoint **inbound port açmaz**. Agent broker'a **dışarı doğru** bağlanır
  (WebSocket-over-TLS; gRPC-stream alternatifi §Alternatifler'de reddedildi —
  bkz. neden WS).
- **Rendezvous:** Agent oturum grant'ini önceden bilmez. Control-plane approved
  grant üretir; agent mevcut **22.5 poll/heartbeat** üzerinden session-invite
  metadata (session_id, TTL, device binding, capability tier, recording-required)
  alır; sonra broker'a outbound bağlanıp short-TTL signed grant sunar.
- **NIST AC-17** (Remote Access): outbound-only + brokered + approval-gated.

### 2. Control-plane / data-plane ayrımı (en kritik karar)

| Düzlem | Servis | Yetki |
|---|---|---|
| **Control plane** | `endpoint-admin-service` + `permission-service` | session request, approval (dual-control), grant **mint**, OpenFGA (validated writer), `remote_sessions` state machine, audit |
| **Data plane** | **`remote-access-broker`** (YENİ servis) | signed-grant **verify** + tunnel **relay** — capability mint YOK, token mint YOK, approval YOK, **OpenFGA writer credential YOK** |

- Broker tüm authz'i **control-plane introspection endpoint**inden alır (session
  state, revocation, device binding). **OpenFGA'ya doğrudan erişimi yoktur**
  (DD-EA-2 validated-writer disiplini korunur).
- Broker compromise senaryosunda saldırgan **yeni capability/grant üretemez**;
  yalnız mevcut, kısa-TTL, doğrulanmış oturumları relay edebilir → blast radius
  minimize.

### 3. Session state machine — DB canonical (OpenFGA tuple churn YOK)

`remote_sessions` tablosu **canonical state machine**:
```
REQUESTED → APPROVED → TOKEN_ISSUED → CONNECTED → CONTROL_GRANTED → ENDED
                                   ↘ (herhangi adımda) → ABORTED
```
- Her transition **imzalı audit event** üretir: `actor ≠ approver`, tenant anchor
  `OUR_COMPANY:<tenant_id>` (literal), device binding, capability_tier,
  recording_required.
- **OpenFGA yalnız statik perm'ler** tutar (device / tenant / admin /
  capability); ephemeral oturum state'i tuple'a yazılmaz.
- **Singleton:** `UNIQUE(device_id) WHERE state ∈ {APPROVED..CONTROL_GRANTED}`.
  Orphan reaper: 90s heartbeat yoksa → `ABORTED` (agent crash güvenliği).

### 4. Token / grant model (sıkı TTL — R5)

| Token sınıfı | TTL | Bağ |
|---|---|---|
| **Session connect-grant** | **5 dk default (≤15 dk)**, **single-use** | actor + device + capability + recording-bound |
| **Active-session lease** | kısa, control-plane introspection ile refresh | revocation **time-to-kill ≤30s** (NIST **AC-12**) |
| **Absolute session max-duration** | **30 dk default (≤60 dk)**; break-glass daha kısa/explicit | policy field |
| Non-session service/auto-enroll token | ≤24h (ADR-0029) — **22.6 remote token'ı DEĞİL** | cert-bound |

- Grant **SPIFFE/SVID benzeri**: device-cert-bound, capability-bound,
  **reconnect yalnız TTL içinde + aynı device binding** ile.

### 5. Capability tier'leri (extended D35-EA binding) + recording modality

| Capability | Tier (ADR-0012-EA extended) | Recording |
|---|---|---|
| Constrained-command-allowlist | **4-E** (controlled sub-mode) | command transcript + stdout/stderr **redaction** + hash-chain (**no video/screen recording**, ama transcript evidence **zorunlu**) |
| Full PTY / interactive PowerShell | **4-F-PTY** (DEFAULT RED, attended, M-of-N, cooldown, max-duration) | **full terminal-I/O recording MANDATORY** (tty/asciicast-style immutable transcript — video değil) |
| Screen view / control / RDP relay | **4-F-REMOTE-CONTROL** (en sıkı, last/RED) | **video/screen recording MANDATORY** + input-event metadata + dropped-frame/recording-lag evidence |
| Unattended | **4-F break-glass** | pilotta KAPALI; explicit break-glass policy objesi |

- **Recording backend unavailable ⇒ 4-F token mint FAIL-CLOSED** (no recording =
  no 4-F session). 4-E transcript fail-closed değil ama transcript zorunlu.
- Clipboard / drive / printer redirection + file-transfer = **ayrı RED
  capability** (4-F-REMOTE-CONTROL içinde default kapalı).

### 6. G7 broker isolation + G9 edge passthrough

**G7 ingress inversion:** broker internet-reachable ingress = mevcut "dış internet
yalnız update channel" modelinin öngörmediği yüzey. Broker **YENİ izole servis**:
ayrı ServiceAccount + RBAC (least-priv) + **NetworkPolicy** (ingress yalnız
edge'den; egress yalnız control-plane introspection + audit + Vault — **doğrudan
OpenFGA egress YOK**) + ResourceQuota (HPA yok, PLAN.md D21) + ESO path
`kv/platform/remote-access-broker/*` + DB role (least-priv, `remote_sessions`) +
ArgoCD app.

**G9 edge — D18 host-TLS-termination'a scoped exception:** Repo geneli edge
kararı host-nginx TLS termination + cluster HTTP'dir (D18). 22.6 için, **yalnız
`endpoint-agent-mtls.*` + remote-broker hostname'leri** için host nginx
**SNI/stream passthrough** yapar; **broker TLS/mTLS terminate eder**.
- Source-identity güvenlik boundary'si **client certificate + signed grant +
  backend-derived device/tenant binding**'dir — **IP değil**, trusted
  `X-Client-Cert` header **değil** (header-trust modeli reddedildi/deferred).
- NetPol source-IP / pod-source yalnız **network allowlist**'tir, authz identity
  değildir.
- ADR-0029 cert-bound model + #1359 edge mTLS kontratına bağlı.

### 7. Audit + non-repudiation

- **Append-only** `remote_session_audit`; **BE-016 hash-chain** pattern
  (`prev_event_hash`, SHA256) — **NIST AU-10** non-repudiation + **AU-3** content.
- Alanlar: actor, approver, device, tenant, reason, scope, capability_tier,
  session_id, start/end, result, evidence_links, abort_reason.
- Audit/recording **ayrı forensic store** (PLAN.md D10: Loki 7d / Tempo 48h
  yetersiz); kendi retention'ı (§11).

### 8. DD-EA-8 Remote Session Governance Guard + live-evidence gate

- **DD-EA-8** (ADR-0012-EA §0 ile eklenen, PROPOSED): CI gate — capability →
  approved-tier map; 4-F için recording-required enforce; unattended yalnız
  break-glass policy objesiyle; **disabled feature advertise edilemez** (AG-013
  precedent).
- **D35-EA-4-F live-evidence gate** (runtime, migration sonrası): stale-token
  reject / same-user-approval reject / tenant-mismatch reject /
  disabled-capability-not-advertised / no-recording-4-F deny / no-cert-edge
  reject / orphan-session cleanup / duration timeout / **reconnect yalnız TTL +
  same device binding**.

### 9. Dual-control + anti-coercion

- Maker ≠ Checker (4-A ve üstü). Signed approval payload (command_digest +
  device_id + TTL, immutable). Timeout + cooldown + post-action audit.
- **Anti-coercion invariant:** approver'lar **insan** olmalı (service-account
  approver YOK), **role-distinct**, ve **asla requesting operator** — break-glass
  dahil (break-glass requester'ı self-elevate edemez). SOC2 **CC6.1** separation
  of duties.

### 10. DoS / rate-limit / capacity + global kill-switch

- **Capacity (no-HPA, D21):** static replicas + fd limit + **broker max-sessions**
  bütçesi; per-tenant + per-device session cap; connection rate-limit;
  WS-flood/slow-loris edge mitigation; max-sessions aşımı → **reject** (queue
  yok); threshold alert. OWASP **API4:2023** unrestricted resource consumption.
- **Global kill-switch:** fleet-wide "tüm remote session'ları disable et" feature
  flag + acil runbook (revoke all grants + close all sessions + agent-side
  disable). #1 risk (broker compromise) için zorunlu.

### 11. KVKK / G8 Privacy/Legal gate

- **D29 üç katmanı değişmez** (Up/Functional/Secured); G8 **ayrı P0 boyut**, 4.
  pillar DEĞİL.
- **Legal basis kilitlenmez:** candidate **KVKK m.5/2-f** (meşru menfaat, attended
  IT support); recording m.6 açık rıza VEYA m.5/2-f + balancing test
  gerektirebilir — **DPO karar verir**.
- Endpoint-side: attended consent UI + operator identity display + recording
  notice + **local abort button**.
- **Session-recording data category** `docs/22-2-kvkk-data-inventory.md`'ye
  eklenir (high-sensitivity, olası üçüncü-taraf PII) — DPIA + VERBİS + retention
  (recording 90d-raw→crypto-erase, transcript 90d, access-audited; DPO-confirm).
- **Recording access-control:** least-priv viewer + per-view audit; data-subject
  kendi recording'ine erişim **DPO/redaction-mediated** (raw self-service değil);
  third-party PII için redaction-on-playback (ISO **A.5.34**).

### 12. Failure modes + abort + revocation propagation

- **9 abort trigger:** user objection (≤5s graceful), network anomaly, scope
  expansion, EDR block, data-volume, audit failure, **approver revocation
  (≤10s graceful save)**, TTL expiry, device offline.
- **Revocation propagation ≤30s** (introspection poll); mid-session CRL/OCSP
  revocation → abort (NIST AC-12).
- **Recording backend down → 4-F fail-closed.**

---

## Sonuçlar

**Olumlu:** broker compromise blast radius minimize; mevcut governance (D29, G7,
DD-EA, validated-writer) korunur; sektör standardı PAM/zero-trust hizası; KVKK
gate explicit.

**Maliyet:** yeni servis (broker) + yeni edge passthrough exception + recording
forensic store + DPO/legal sign-off bağımlılığı; runtime #1388 + §0 reconciliation
olmadan açılamaz.

---

## Alternatifler (reddedildi)

- **gRPC-stream tek kanal:** 22.5 poll plane'i streaming'e çevirmek — non-goal;
  WS-over-TLS daha basit edge + reconnect semantiği.
- **Broker'ın OpenFGA'ya doğrudan yazması/okuması:** DD-EA-2 ihlali + blast
  radius artışı → reddedildi (introspection-only).
- **Edge-terminated TLS + `X-Client-Cert` header:** header-trust spoofing riski;
  cert-bound device binding bozulur → reddedildi (passthrough seçildi).
- **Session state OpenFGA tuple'da:** ephemeral churn shared store'u riske atar →
  DB state machine canonical.
- **Tek unified legal basis erken seal:** KVKK m.5/2-f'i tek başına kilitlemek →
  reddedildi (DPO karar verir).

---

## Standards

NIST SP 800-53 **AC-17** (remote access), **AC-12** (session termination),
**AC-2(11)/AC-6** (emergency/least-priv), **AU-3/AU-10** (audit/non-repudiation);
NIST **800-207** zero-trust; **SPIFFE/SVID** (cert-bound short-lived identity);
**ISO/IEC 27001:2022** A.5.15/A.5.16/A.5.18/A.5.23/A.5.34; **SOC2** CC6.1/CC7.2;
**OWASP API4:2023**; **KVKK** m.5/6/7/11 + **GDPR** Art.5/6/17/32.

## Bağımlılıklar + blocker

- **BLOCKER:** #1388 acceptance + ADR-0012-EA §0 reconciliation (extended ladder
  + DD-EA-8 canonical).
- **#1359** edge mTLS / DNS (necessary-but-not-sufficient); non-domain (22.2.A)
  için ayrı device-cert kontratı.
- **BE-016** audit hash-chain (reuse); **BE-019** KVKK enforcement; 22.8 ile
  **unified evidence-storage-contract v0**.
- Agent concurrency kontratı (22.5 poll + 22.6 tunnel).

## Cross-AI Consensus Log

| Tur | Reviewer | Verdict | Absorbe |
|---|---|---|---|
| plan iter-1/2 | Codex `019ea961` | REVISE→AGREE | drift keşfi, control/data ayrımı, 4-F, DD-EA-8, G8 |
| exec iter-1 | Codex `019ea961` | REVISE | numbering çakışması, recording fail-mode, retention drift, DoS/kill-switch, break-glass schema, edge passthrough |
| exec iter-2 | Codex `019ea961` | **AGREE** (3 write-guard) | TTL sıkı (5-15dk grant), 4-F-PTY=terminal-I/O (video değil)/RDP=video, system_format=4-B-WIPE, DD-EA-3/4 update-channel sub-req (cosign=container / Authenticode=Windows), G9=D18 scoped exception, D35-EA-3 limiting clause |
