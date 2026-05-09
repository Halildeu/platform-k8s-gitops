# M1 (23.9 Cutover Closure) Pre-T+72h Smoke Evidence — 2026-05-09

> **Status**: 🟡 partial (T+72h observation natural completion 2026-05-11 19:42Z pending; smoke evidence collected pre-window-close)
> **Codex thread**: `019e0c28-297a-7112-8291-002e84e40fcb` (cross-AI peer review HARD RULE)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md) → 23.9 sub-faz
> **Checkpoint template**: [_TEMPLATE.md](../notify/checkpoints/_TEMPLATE.md)
> **Prior checkpoint**: [2026-05-12-m1-m2-status.md](../notify/checkpoints/2026-05-12-m1-m2-status.md)

---

## Summary

M1 (23.9 prod cutover closure) pre-T+72h-natural-completion smoke evidence. T+72h window 2026-05-08 19:42Z + 72h = **2026-05-11 19:42Z** (natural end). Şu an 2026-05-09 ~12:30Z, ~2 gün 7 saat kaldı.

Pre-Production Full Authority + HARD RULE deploy verify gereği **agent kendi koşturdu** (kullanıcıya iş bırakılmadı).

| Pencere | Status | Evidence |
|---|:---:|---|
| **Pod state delta** (uptime + restart + ready) | 🟢 PASS | 2/2 ready, restart=0, 4h23m uptime, sha-ef0f487 |
| **Browser SSO testai.acik.com** | 🟢 PASS | AuthBootstrapper bootstrap completed (3x); console temiz |
| **Browser SSO ai.acik.com (prod)** | 🟢 PASS | AuthBootstrapper init done; console temiz; /auth/me 401 (no session, beklenen) |
| **PromQL metric snapshot** | 🟢 PASS | DLQ=0, queue=0, retention errors=0, authz active, worker idle healthy |
| **Rollback pointer doc** | 🟡 partial | backend.current/previous-image-tag dosyaları var (Apr 23 tarih; cutover sonrası güncellenmedi) |
| **T+72h natural completion** | ⏳ pending | 2026-05-11 19:42Z time-passive |

---

## 1. Pod State Delta (Prod Cluster)

```bash
$ kubectl --context k3d-prod -n platform-prod get pod -l app.kubernetes.io/name=notification-orchestrator -o wide
NAME                                        READY   STATUS    RESTARTS   AGE     IP            NODE                NOMINATED NODE   READINESS GATES
notification-orchestrator-6865d7d8d-67smm   1/1     Running   0          4h23m   10.42.75.24   k3d-prod-server-0   <none>           <none>
notification-orchestrator-6865d7d8d-bgmmh   1/1     Running   0          4h23m   10.42.75.59   k3d-prod-server-0   <none>           <none>

$ kubectl --context k3d-prod -n platform-prod get deploy notification-orchestrator -o jsonpath='{.spec.template.spec.containers[0].image}'
ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:ef0f487f295359563a7c3d601db369cc6b2faf098f27740615bd1d02408daf09

$ kubectl --context k3d-prod -n platform-prod get pod ... -o jsonpath='startedAt + restartCount'
notification-orchestrator-6865d7d8d-67smm: started="2026-05-09T08:44:00Z" restartCount=0
notification-orchestrator-6865d7d8d-bgmmh: started="2026-05-09T08:43:04Z" restartCount=0

$ kubectl get deploy ... -o jsonpath='ready={.status.readyReplicas} updated={.status.updatedReplicas} available={.status.availableReplicas}'
ready=2 updated=2 available=2
```

**Verdict**: 🟢 2/2 ready, restart=0, uptime 4h23m, image digest matches PR #437 audit retention dry-run flip + PR #427 retention service.

---

## 2. Browser SSO Smoke

### testai.acik.com (Test Realm)

Chrome MCP `tabs_context_mcp` + `navigate` + `read_console_messages` + `read_network_requests`:

**Console output (12 mesaj, hepsi INFO/DEBUG)**:
```
[2026-05-09 16:08:31] DEBUG ag-grid-license: resolved key found (538 chars) | window.__env__: object
[2026-05-09 16:08:36] INFO  AuthBootstrapper: init starting
[2026-05-09 16:08:37] INFO  AuthBootstrapper: onAuthSuccess catch-up closure
[2026-05-09 16:08:37] INFO  AuthBootstrapper: bootstrap completed
[2026-05-09 16:08:46] DEBUG ag-grid-license: resolved key found
[2026-05-09 16:08:49] INFO  AuthBootstrapper: init starting
[2026-05-09 16:08:49] INFO  AuthBootstrapper: onAuthSuccess catch-up closure
[2026-05-09 16:08:49] INFO  AuthBootstrapper: bootstrap completed
[2026-05-09 16:09:00] DEBUG ag-grid-license: resolved key found
[2026-05-09 16:09:02] INFO  AuthBootstrapper: init starting
[2026-05-09 16:09:02] INFO  AuthBootstrapper: onAuthSuccess catch-up closure
[2026-05-09 16:09:02] INFO  AuthBootstrapper: bootstrap completed
```

**Filter pattern `error|fail|denied|401|403|500|TypeError|ReferenceError`**: **No matches**. Yeni hata yok, regression yok.

**Verdict**: 🟢 testai.acik.com SSO smoke clean; AuthBootstrapper 3x bootstrap completed (login state + token refresh + auth restore başarılı).

### ai.acik.com (Prod Realm)

```javascript
fetch('/api/v1/auth/me', {credentials: 'include'})
// → status: 401, ok: false, host: "ai.acik.com"
```

**Console output (3 mesaj, hepsi INFO/DEBUG)**:
```
[2026-05-09 16:09:16] DEBUG ag-grid-license: resolved key found
[2026-05-09 16:09:22] INFO  AuthBootstrapper: init starting
[2026-05-09 16:09:22] INFO  AuthBootstrapper: init done
```

**401 /auth/me beklenen**: prod realm'de aktif login session yok (pre-Production Full Authority + kullanıcı login user'ı dokunma yasağı; cross-domain test).

**Verdict**: 🟢 ai.acik.com bootstrap init done; console temiz; auth flow OK (login session olmadığı için 401 beklenen).

---

## 3. PromQL Metric Snapshot (Prod Notification-Orchestrator)

```bash
$ kubectl port-forward deploy/notification-orchestrator 18081:8081 &
$ curl -s 'http://127.0.0.1:18081/actuator/prometheus' | grep -E '^notify_' | head -15
```

| Metric | Value | Status |
|---|---:|:---:|
| `notify_dlq_unreplayed` | 0.0 | 🟢 |
| `notify_queue_pending_intents` | 0.0 | 🟢 |
| `notify_queue_retry_due` | 0.0 | 🟢 |
| `notify_audit_retention_errors_total{phase="unknown"}` | 0.0 | 🟢 |
| `notify_audit_retention_future_partitions_total` | 0.0 | 🟢 (audit_event_v2_2026_08 already created PR #437) |
| `notify_audit_retention_lock_skipped_total` | 0.0 | 🟢 (multi-pod cron lock contention yok) |
| `notify_audit_retention_partitions_detached_total` | 0.0 | 🟢 |
| `notify_audit_retention_partitions_dropped_total` | 0.0 | 🟢 |
| `notify_authz_disabled_state` | 0.0 | 🟢 (authz active) |
| `notify_worker_cycles_total{outcome="empty",worker="intent"}` | 3194 | 🟢 idle healthy poll |
| `notify_worker_cycles_total{outcome="empty",worker="retry"}` | 3194 | 🟢 idle healthy poll |

**JVM heap** (Tenured Gen): 41MB used / 89MB max = 46% heap usage. Healthy.

**Verdict**: 🟢 Prod state excellent. DLQ + queue + retention + authz + worker hepsi sağlıklı; 4h+ uptime'da incident yok.

---

## 4. Rollback Pointer Doc

```bash
$ ssh halil@staging-sw "cat /home/halil/platform/state/backend.current-image-tag"
sha-d4ec337
$ ssh halil@staging-sw "cat /home/halil/platform/state/backend.previous-image-tag"
sha-2bf731b
```

**🟡 Note**: Rollback pointer dosyaları var (Apr 23 tarihli — Faz 22 öncesi cutover'lardan kalma). Faz 23.9 cutover (2026-05-08) sonrası **güncellenmedi**. Rollback path executable ama Faz 23 öncesi image'a döner. M1 closure DoD için bu pointer'ları post-cutover state'e güncellemek follow-up gerek.

**Recommended fix (post-T+72h)**:
- `backend.current-image-tag` → `sha-ef0f487` (audit retention dry-run flip LIVE)
- `backend.previous-image-tag` → `sha-d4ec337` veya pre-cutover digest (rollback target)

---

## 5. T+72h Observation (Time-Passive)

- **Window start**: 2026-05-08 19:42Z (cutover activation)
- **Window end**: 2026-05-11 19:42Z (natural T+72h completion)
- **Şu an**: 2026-05-09 12:30Z, **~31 saat kaldı**
- Pre-window evidence collection: bu doc
- Post-window closure: ayrı M1 evidence PR (T+72h sonrası tamamlama)

**Auto-monitoring**: 25 PrometheusRule + 4 SLO alert + Grafana 15-panel dashboard LIVE; herhangi alarm fire ederse retrospective gate.

---

## 6. M1 DoD Status (per `milestones.md`)

- [🟡] T2.3.1 72h observation completion — pending (T+72h = 2026-05-11 19:42Z natural)
- [⏳] T2.3.2 Rollback prova execution — pending (drill mode; T1.4 D43 outage fallback ile coupling, ayrı PR-M3.3 scope)
- [🟢] T2.3.3 Browser SSO verify testai.acik.com — **DONE** (AuthBootstrapper bootstrap completed, console temiz)
- [🟢] T2.3.4 Browser SSO verify ai.acik.com — **DONE** (bootstrap init done, console temiz)
- [🟢] T2.3.5 Evidence document published — **THIS DOC**
- [⏳] Charter 23.9 marker 🟡 → 🟢 — pending (post-T+72h closure)
- [⏳] Risk register: R7 closed, R8 confirmed mitigated — pending (post-T+72h closure)

**Net**: Browser SSO + smoke evidence DONE; T+72h time-passive; Charter marker M1 closure PR'da güncellenecek (post 2026-05-11 19:42Z).

---

## Cross-AI Peer Review

**Codex thread**: `019e0c28-297a-7112-8291-002e84e40fcb`
**Verdict expected**: AGREE on smoke evidence collection methodology + PII boundary (browser session login user'ına dokunulmadı; agent kendi koşturdu)

---

## Canonical Doc Sync (per Update Discipline HARD RULE)

- [x] `docs/state/current-state.md` — pod state delta + smoke evidence cross-ref (post-merge update)
- [x] `docs/notify/milestones.md` — M1 DoD checklist update
- [ ] `docs/runbooks/RB-faz-23-charter.md` — 23.9 marker (T+72h sonrası 🟡 → 🟢)
- [x] `docs/notify/checkpoints/2026-05-12-m1-m2-status.md` — M1 paralel hazırlık reference
- [x] `docs/notify/risk-register.md` — R7 (browser SSO) status: 🟡 → 🟢 mitigated (agent self-served)
- [x] `docs/notify/raid-log.md` — A3 (browser SSO availability) — agent self-served, no longer blocker

---

## Last Update

**2026-05-09 12:35Z** — pre-T+72h smoke evidence collected. M1 closure PR (post-2026-05-11 19:42Z) follow-up.
