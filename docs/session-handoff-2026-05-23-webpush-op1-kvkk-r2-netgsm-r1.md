# Session Handoff — 2026-05-23 — WebPush OP.1 + KVKK R2 closure + NetGSM R1 defer

> Format: D28 5-alan (Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk + P0)
> Önceki handoff: `docs/session-handoff-2026-05-21-m3-r2-kvkk-closure-m7-t42-foundation.md`

## 1. Bağlam

Faz 23.7 M7 WebPush aktivasyonu (OP.1) + Faz 23.2 M3 R2 KVKK closure + Faz 23.3
R1 NetGSM scope kararı. Tetik: WebPush `/settings/notifications` cold-load 401
bug'ı + kullanıcının "kalan işi tamamlayalım" + "hukuk onayları Codex
verdict'iyle" + "NetGSM sözleşme yok" kararları.

## 2. İddia (bu oturumda MERGED — 8 PR)

| PR | Repo | İçerik |
|---|---|---|
| #652 | platform-web | `unwrapRequestFetchFn` shared module — notify RTK cold-load 401 kök fix |
| #986 | platform-k8s-gitops | Frontend test overlay digest bump → `sha256:aef8169e` (#652 build) |
| #987 | platform-k8s-gitops | RB-webpush-activation §3.10/§5 — browser subscribe smoke gate ✅ |
| #989 | platform-k8s-gitops | RB-webpush-activation §3.11 — push dispatch pipeline evidence (🟡) |
| #990 | platform-k8s-gitops | OpenFGA notification-authz model extension — safe-phase (additive) |
| #991 | platform-k8s-gitops | R2 KVKK CLOSED — Codex `019e5189` final legal verdict |
| #992 | platform-k8s-gitops | R1 NetGSM secondary ⏳ DEFER — asset-preserved truth-sync |
| #993 | platform-k8s-gitops | Charter 23.6 ⏳→🟢 + 23.7 ⏳→🟡 sub-faz marker drift-fix |

Cross-AI: Codex thread `019e512f` (#652) + `019e5146` (#986/#987/#989/#990) +
`019e5189` (R2 legal verdict + #991) + `019e5195` (#992) + `019e519e` (#993).

## 3. İspatlar (live evidence)

- **WebPush subscribe akışı browser-kanıtlı**: persistent-context Playwright
  (non-incognito) — `webpush-smoke` KC SSO → `/settings/notifications` cold-load
  → `GET /preferences/me`+`/push/subscribe/me`+`/inbox/me` **200** (önceki 401
  RTK `Request`-object header-drop bug'ı #652 ile çözüldü) → "Aboneliği aç" →
  gerçek FCM endpoint (`jmt17.google.com/fcm/send/…`) → `POST /push/subscribe`
  **200** → kart "Aboneliği kapat / 1 aktif cihaz". 0 console error.
- **§3.11 push dispatch pipeline**: sentetik intent (`POST /api/v1/notify/intents`
  202, template `t1`, `channels:["push"]`) → `IntentSubmissionService` →
  `DeliveryPlanService push plan target_count=1` → `DeliveryDispatchService` →
  metric `notify_dispatch_outcome_total{channel="push"} > 0`.
- **OpenFGA model extension**: yeni model versiyonu `01KS8QE8T1EJ2DF5CRS4VV9YX1`
  yazıldı (store `01KPP0CFP4G82K42Y6NYSPT4JF`); 10 ERP type byte-identical +
  5 notification type; izole Check PASS (topic-inheritance ALLOW); runtime-
  artifact ledger entry `test=verified / prod=pending`.
- **R2 KVKK**: 6/7 K-PR MERGED; Codex `019e5189` final legal verdict AGREE =
  kabul edilen hukuk onayı (kullanıcı kararı). M3 🟢 CLOSED.

## 4. İspatlamaz (henüz kanıtlanmadı)

- **SUCCESS-status WebPush push delivery** — push intent outcome şu an
  `BLOCKED_BY_AUTHZ`. Kök neden: orchestrator `AuthzClient` →
  permission-service `/internal/authz/check` `{subscriber, can_receive,
  template}` → OpenFGA; canlı model (`01KRTJVE…`) notification type'larını
  içermiyor. Yeni model `01KS8QE8…` yazıldı ama **permission-service hâlâ eski
  model_id ile configured** — cutover yapılmadı.
- §3.11 metric gate tam ✅ değil (🟡 — pipeline + metric>0 kanıtlı, SUCCESS
  delivery cutover'a bağlı).
- OS toast / push delivery → click-to-navigate (RB §3.10 step 6-7).

## 5. Bilinen boşluk + sıradaki agent P0 aksiyon listesi

### P0 — WebPush OP.1'i tam kapatan tek adım
**OpenFGA model_id cutover** — `ERP_OPENFGA_MODEL_ID`: `01KRTJVEMAW80B2D35GN8HJDPG`
→ `01KS8QE8T1EJ2DF5CRS4VV9YX1` (Vault `kv/platform/openfga/model_id` + ESO sync +
permission-service rollout). Sonra: push delivery test tekrar → `DELIVERED` +
`notify_dispatch_outcome_total{channel="push",status="SUCCESS"}` → RB §3.11 🟡→✅.
- **Risk**: platform-geneli authz plane (ERP + notification). Safe-phase
  de-risk etti: ERP type'ları byte-identical (kanıtlı), izole Check PASS;
  rollback = model_id revert (anlık).
- **Durum**: Kullanıcı bunu AskUserQuestion'da "ayrı tut" dedi — explicit
  operator/owner go gerekiyor. spawn_task chip mevcut.
- Test tuple zaten seed'li: `template:t1#topic@notification_topic:test.webpush.delivery`
  + `notification_topic:…#can_receive@subscriber:123be09e-…`.

### P1 — operator activation (runbook hazır)
- FBL mailbox activation (IMAP creds + ConfigMap enable — RB-fbl-mailbox-activation)
- Per-template analytics DB RO role + Vault seed + ESO uncomment
- R9 D43 outage fallback drill (Slack #853 + prod #854)

### P1 — backend (non-blocking)
- K6 tenant-scoped DPO authz (JWT `allowed_orgs` + FGA `can_erasure`) — Codex
  `019e5189` non-blocking dedi; ~2h backend.

### P2 — doc reconciliation
- milestones.md M1 (23.9) — charter table "FULL CLOSURE" diyor ama charter 23.9
  section + sprint-plan T2.3 rollback-prova "not executed" diyor. Gerçek durum
  netleştirilmeli (rollback prova yapıldı mı?).
- milestones.md M6a/M6b section DoD checkbox'ları stale (sprint-plan T2.2 +
  board #758'e göre MERGED).

### External-gated (agent/operator dışı)
- R24 JetSMS Biotekno OTP allowlist provisioning (VFO kanal)
- M4 prod canary SMS — KC operator `org_id=default` claim setup
- Office 365 admin DKIM tenant enable + DNS CNAME
- R1 NetGSM secondary contract — ⏳ DEFER (kısa vadede yok; asset-preserved —
  sözleşme imzalanırsa reactivation chain risk-register R1'de dokümante)

## 6. Yeni session için ilk komut

```
cd <platform-k8s-gitops worktree>
cat docs/session-handoff-2026-05-23-webpush-op1-kvkk-r2-netgsm-r1.md
```

P0 = OpenFGA model_id cutover (owner go bekliyor); sonrası push delivery
re-smoke → RB §3.11 ✅ → WebPush OP.1 tam kapanış.
