# RB Faz 22.6 — CONSTRAINED_PTY pilot LIVE activation (turnkey owner/operator guide)

> **Status**: BUILD-COMPLETE + DISABLED-BY-DEFAULT → bu runbook **LIVE aktivasyonun turnkey rehberi**dir.
> Agent + broker CONSTRAINED_PTY zinciri kod-tam ve merged (aşağıdaki §2); hiçbir kod kalmadı. LIVE
> aktivasyon **owner-gated** (ADR-0034 §13/D10 + ADR-0040 §9) — bu runbook owner/operator'ın atması gereken
> adımları (config flag flip + deploy + acceptance) push-button hale getirir, **agent bunları otomatik
> ÇALIŞTIRMAZ** (KVKK imzası + fiziksel PC + attended koşu + gerçek trust root'lar yapısal owner sorumluluğu).
> **Scope sınırı**: bu, command-execution (uzaktan komut) pilot'unun aktivasyonudur — VIEW_ONLY'den daha
> yüksek riskli; §3 owner-gate'leri ZORUNLU, atlanamaz. "prod-wide rollout-ready" iddiası YOK; tek pilot.
> **Tracked by**: #1588 (CONSTRAINED_PTY broker/agent track) + #1580 (22.6 parent).
> **Decided by**: ADR-0034 (D8 pilot capabilities) §13 (engineering gate lifted; LIVE = §11/D10) + ADR-0038
> (transport) + ADR-0040 §9 (break-glass/owner sign-off). Codex thread `019ecd07` (command-transport).

---

## 1. Amaç

CONSTRAINED_PTY = ADR-0034 D8'in iki pilot capability'sinden biri (diğeri VIEW_ONLY): operatörün, owner-imzalı
+ agent-tarafı imza-doğrulanmış + allowlist'li **tek bir read-only komutu** uzak endpoint'te çalıştırıp
çıktısını görmesi. Tüm yol **disabled-by-default** build edildi; bu runbook owner/operator'ın LIVE pilot için
attığı adımları tanımlar. Hiçbir adım son kullanıcıya iş bırakmaz **agent tarafından** — ama LIVE'ın kendisi
(yasal imza, fiziksel donanım, attended insan koşusu, gerçek kripto trust root'ları) yapısal olarak owner'ın.

## 2. BUILD durumu — neyin HAZIR olduğu (kod kalmadı)

| Katman | PR | Ne |
|---|---|---|
| agent verify+canonical | #184 | OperationPermit ECDSA P-256 verify + CanonicalCommand (cross-language vector #667) |
| agent gate | #185 | Authorize: verify→capability→command-hash→seq replay-guard, fail-closed |
| agent plan/cmdline | #186 | BuildExecPlan + read-only System32 allowlist + no-shell quoter |
| agent ConPTY | #187 | RunConPTY (pseudo-console, output cap 8 MiB, kill-safe) |
| agent executor | #188 | gated Executor (verify→plan→ConPTY) |
| agent streamer | #189 | OutputStreamer (ConPTY output → DataFrame chunks + terminal EndStream) |
| agent handler | #190 | PtyOperationHandler (executor + streamer composition) |
| backend wire spec | #668 | `OperationDispatch{permit, command_line}` shadow-spec (B2) |
| backend proto+adapter | #669 | proto msg + Envelope oneof 21 + strict adapter decode/encode |
| backend broker push | #670 | RemoteBridgeOperatorService PERMIT → `sendOperationDispatch(permit, command)` |
| agent proto re-vendor | #191 | vendored proto + pb regen + descriptor-guard |
| agent harness dispatch | #192 | inbound operation_dispatch → PtyOperationHandler → per-op DATA stream |
| CI hardening | #671 | report-service MSSQL image pre-pull (unrelated flake fix) |

**Mekanizma**: operatör OperationRequest (komut) → broker policy ALLOW + permit mint (ECDSA imza, command-hash)
→ `OperationDispatch{permit, command}` CONTROL push → agent decode (fail-closed) → re-hash(command)==command_hash
→ gate (capability/seq) → allowlist → ConPTY exec → çıktı per-operation DATA stream + terminal EndStream →
operatör görür. **Komut imzalı-permit'in hash'iyle bağlı; asla raw-trust yok.** Hepsi disabled-by-default.

## 3. OWNER-GATED prerequisites (insan — herhangi bir flag flip'ten ÖNCE; agent yapamaz)

Aşağıdakiler **yapısal owner sorumluluğu**; mock'lanamaz (No-Fake-Work + KVKK/güvenlik ihlali):

1. **ADR-0034 §11/D10 LIVE-pilot owner sign-off** — §13 engineering gate LIFTED (disabled-by-default BUILD
   serbest), ama LIVE session §11/D10 owner imzası ister.
2. **4-rol KVKK pilot onayı** (İK / Hukuk / IT-Security / DPO). VIEW_ONLY için imzalı (#1444); CONSTRAINED_PTY
   **komut-çalıştırma** daha yüksek riskli → bu capability için ayrı/teyitli onay gerek (amaç-beyan: read-only
   tanı komutları; allowlist System32; audit 7yıl). ADR-0040 §9 break-glass/owner sign-off rollup.
3. **Fiziksel IT-owned pilot PC + named roster + attended-run taahhüdü** — unattended LIVE YASAK; her session
   bir operatör + endpoint kullanıcısı consent'i (D7) ile.
4. **Gerçek trust root'ları** (broker yalnız gerçek trust'la PERMIT eder; placeholder ile DENY):
   - device-PKI (B1.4d): `CertTrustEvaluator` trust-anchor + issuer-pin + (opsiyonel) attestation policy.
   - operatör step-up (D, FIDO2): gerçek WebAuthn RP + operator authenticator (IdP).

## 4. Infra aktivasyon (operator, D29-EA broker)

> Tümü **selective + auditable**; secret'lar Vault'tan ESO ile (stdin-pipe, local env'a token YOK — D43 pattern).

1. **Vault seed** (`kv/platform/endpoint-admin` veya broker path):
   - `remote-bridge.permit.signing-key-pem-path` ← PKCS#8 EC P-256 **broker-private** permit-signing key; agent
     bunun **public** karşılığını pin'ler (`kid` ile). `remote-bridge.permit.kid` ← key id.
   - `remote-bridge.recording.anchor-key.path` (+`.algorithm`) ← WORM recording anchor key (permit key'den AYRI;
     ayrı rotation/blast-radius — slice-3c kararı).
   - `remote-bridge.tls.{cert-chain-pem-path, private-key-pem-path, client-ca-pem-path}` ← broker mTLS triple
     (device CA). Enabled broker mTLS-only (clientAuth=REQUIRE); eksik/garbage PEM → bind'den ÖNCE fail-closed.
   - Operatör JWT/Keycloak: `remote-bridge.operator-auth.type=JWT_BEARER` + JWKS/issuer/audience (bridge-audience)
     + operator-role (`realm_access.roles`). (Tam flag seti = `RemoteBridgeServerProperties` +
     `RemoteBridgeApprovalProperties` + operator-auth/owner-grant/duress config sınıfları — drift için onlara bak.)
2. **Keycloak**: operatör client + bridge-audience operator-role mapper.
3. **gitops overlay** (`kustomize/base/apps/endpoint-admin-service/` + pilot overlay): broker env'ine
   `remote-bridge.enabled=true` + `bind-host` (non-loopback; `allow-insecure-plaintext=false`) + TLS triple
   pathleri + `remote-bridge.operator-rest.enabled=true` + `remote-bridge.approval-rest.enabled=true` +
   `operator-auth.type=JWT_BEARER` + `owner-grant.gate-type=APPROVAL_BACKED_IN_MEMORY` (veya durable store) +
   `duress.source-type` + `step-up.expected-origin`/`.rp-id`. **ESO Ready=True doğrula** (her required key dolu;
   eksik key → Ready=False chain). D29-EA pilot cluster'a deploy.
4. **L4 TLS-passthrough edge**: broker gRPC portu için (SNI passthrough; broker mTLS termine eder).

## 5. Agent aktivasyon (operator, pilot PC'de)

1. `ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED=true` + broker address (harness outbound-only dial eder; device-id
   provider enrolled cihaz id'sini döndürmeli — kimliksiz dial YOK).
2. **`Config.PTYDispatcher` wiring** (LIVE build/config): agent main'i bugün bunu **nil bırakır
   (disabled-by-default → operation_dispatch defect-close)**; LIVE için bir gerçek `*ptyexec.PtyOperationHandler`
   set edilir — `operation.Verifier` (broker permit **public** key + `kid`, §4.1) + `ptyexec` allowlist
   (`DefaultAllowlist` read-only System32) + ConPTY üzerinden kurulur. mTLS leaf (device cert) gerçek.

## 6. Acceptance gate'leri (D29-EA, CONSTRAINED_PTY-özel — her biri AYRI kanıt)

- **Up**: broker pod Running + TCP reachable; agent CONTROL stream + AgentHello bağlanır (harness Counters
  `connects>=1`, `healthy>=1` heartbeat sonrası).
- **Functional**: operatör bir CONSTRAINED_PTY OperationRequest (`hostname`) submit eder → broker (gerçek
  trust + onaylı owner-grant) PERMIT → OperationDispatch push → agent re-hash==command_hash + gate + allowlist
  geçer → ConPTY çalışır → çıktı DATA stream'de + terminal EndStream → operatör `hostname` çıktısını görür.
  (Browser/console kanıtı zorunlu — HARD RULE "Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi".)
- **Secured** (her biri ayrı negative kanıt): allowlist-dışı komut → gate/allowlist deny, **spawn YOK**;
  expired/tampered permit → reject; forged command (hash mismatch) → reject (`operation-dispatch-failed`
  CONTROL ErrorFrame, DATA'da oracle YOK); cross-language permit verify byte-exact (vector #184/#667); KILL
  envelope sub-second session terminate (DATA backpressure'a takılmaz); disabled→enabled transition: dispatcher
  nil iken operation_dispatch defect-close, set iken çalışır.
  - **one-dispatch-per-operation (replay guard)**: aynı `operationId` (aynı `seq`) ile permit'i TEKRAR push et →
    **ikinci çalıştırma YOK** (gate seq monotonic replay-guard); deterministik/karşılaştırmalı kanıt (ilk
    dispatch çıktı üretir, tekrar reddedilir). Bu, pilot'ta single-use davranışının açık kanıtıdır.

## 7. Kill-switch / rollback (anında, owner/operator)

- **Disable**: broker `remote-bridge.enabled=false` (overlay flip + redeploy) → DEFAULT context'te ZERO
  remote-bridge bean. **Doğrula (varsayma)**: pod readiness Up + broker gRPC portu artık dinlemiyor +
  `actuator`/startup-log'da remote-bridge bean/lifecycle YOK (enabled-config-validate izleri yok). Agent:
  `ENDPOINT_AGENT_REMOTE_BRIDGE_ENABLED` unset / `PTYDispatcher` nil → harness idle, inbound operation_dispatch
  defect-close (log'da "unsupported-payload-in-idle" + stream close). İkisi de fail-closed.
- **Active session kill**: broker `ControlStreamRegistry.killPeer` → `Envelope.kill` (transport-kill sentinel)
  CONTROL'de → agent sub-second obeyKill + stream terminate; in-flight ConPTY ctx-cancel ile teardown.

## 8. Referanslar

- PR'lar: agent #184–#192, backend #668/#669/#670, CI #671 (hepsi Codex `019ecd07` AGREE + forensic-tagged).
- Wire: `endpoint-admin-service/docs/remote-bridge-wire-contract.md` (`OperationDispatch` §) — backend-owned SoT.
- ADR-0034 (D8 pilot) §13/§11/D10 · ADR-0038 (transport) · ADR-0040 §9 (owner sign-off).
- Sibling runbooks: `RB-faz22-endpoint-pilot-it-owned.md`, `RB-faz22-non-domain-windows-pilot.md`.
- Config SoT (drift guard): `RemoteBridgeServerProperties` + `RemoteBridgeApprovalProperties` + operator-auth /
  owner-grant / duress / step-up config sınıfları (exact kebab-case key'ler için bunlara bak; bu runbook
  prefix + anlamı verir).
