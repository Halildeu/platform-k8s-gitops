# Runbook — Faz G D30 Cutover Communication Templates

> **Belge kodu**: `RB-faz-g-cutover-comms-templates`
> **Tarih**: 2026-05-15
> **Sahip**: Halil (owner) — comms execute authority
> **Sprint**: V2.1 9/9 closure → Faz G cutover prep
> **Codex strategic consult**: thread `019e2cbf` HIGH gap #3 absorb — "Comms templates eksik. T-7d, T-1d, T-1h, T+0, T+5m, T+1h, T+24h, rollback, T+72h timing için hazır metinler sınırlı"
> **Prerequisites**: D30 cutover runbook (PR #687) + Post-cutover validation playbook (PR #692)

---

## 1. Bağlam — Pre-prod Context

Bu repo pre-production setup. External end-user yok; internal stakeholder set sınırlı. Comms templates bu context'i yansıtır:

- **Pre-prod**: Halil (owner) + agent + (varsa) küçük internal ekip
- **Production go-live sonrası**: stakeholder genişler — V3 scope

Pre-prod context'te bile comms templates **disiplin** sağlar (forensic audit trail + decision documentation).

---

## 2. Stakeholder Audience Categories

| Code | Audience | Channel | Pre-prod | Production V3 |
|---|---|---|---|---|
| **INT-OWN** | Owner (Halil) | Self-log | ✓ Always | ✓ |
| **INT-OPS** | Platform ops (eğer atanmışsa) | Slack/Teams/PagerDuty | 🟡 If applicable | ✓ |
| **INT-DEV** | Backend/frontend dev | GitHub Issues | 🟡 If applicable | ✓ |
| **INT-BIZ** | Business owner (reporting/auth) | Email | 🟡 If applicable | ✓ |
| **INT-SEC** | Security/compliance | Email | 🟡 If applicable | ✓ |
| **EXT-CUS** | External customers | Email + status page | ❌ N/A pre-prod | ✓ |
| **EXT-VEN** | Vendors (Keycloak, etc.) | Support ticket | ❌ N/A | 🟡 If issue |

**Pre-prod default**: INT-OWN only. Diğerleri kullanıcı durumunda atanır.

---

## 3. Comms Timing Chain

### 3.1 T-7d — Cutover Announce

**Trigger**: Cutover window confirmed (O4 decision).

**Audience**: INT-OWN + INT-OPS (varsa) + INT-DEV (varsa)

**Template**:

```
Subject: [Cutover Announce] D30 Atomic Cutover Scheduled — <DATE> <TIME UTC>

V2.1 prod-readiness sub-wave 9/9 DONE 2026-05-15. Faz G freeze gate
unlocked. D30 atomic cutover scheduled.

## Cutover Details

- Date: <YYYY-MM-DD>
- Time: <HH:MM UTC> / <HH:MM Türkiye saati>
- Window: 4h (cutover + initial monitoring)
- T+72h warm rollback window: staging-sw compose frozen

## What Changes

- Edge proxy L4 atomic switch: compose → k8s
- Primary endpoint: https://ai.acik.com (k8s-served)
- Rollback target: staging-sw compose (frozen + ayakta 72h)

## What You Should Do

- Review: docs/runbooks/RB-faz-g-d30-atomic-cutover.md
- T-1d reminder will follow
- T-1h pre-cutover smoke notification
- If you are on-call: PagerDuty/equivalent setup ready

## Rollback Authority

Owner (Halil) holds final rollback decision authority. Triggers:
- p95 latency +X%
- Error rate >2% sustained 10dk
- Pod crashloop 3+ in 10dk
- Alert flood >10 alerts 5dk window
- Manual owner declaration

## Comms Plan

- T-1d: Final reminder
- T-1h: Pre-cutover smoke
- T+0: Cutover started
- T+5m: Initial verify
- T+1h: Stable confirm
- T+24h: Day-1 summary
- T+72h: Decommission decision

References:
- D30 cutover runbook: docs/runbooks/RB-faz-g-d30-atomic-cutover.md
- Post-cutover validation: docs/runbooks/RB-faz-g-post-cutover-validation-playbook.md
- Faz G transition plan: docs/operations/V2.1-faz-g-prod-cutover-transition-plan.md

Halil
```

### 3.2 T-1d — Final Reminder

**Audience**: Same as T-7d

**Template**:

```
Subject: [Cutover Reminder] D30 Atomic Cutover Tomorrow — <DATE> <TIME UTC>

Reminder: D30 atomic cutover tomorrow.

## Time

<DATE> <TIME UTC> / <TIME Türkiye saati>

## Final Checks (Pre-Cutover Day-1 Verify)

- [ ] Compose state healthy: 10+ container UP
- [ ] Backup chain fresh: PG hourly + Vault daily + KC weekly
- [ ] ABM-1 recent fire PASS (≤24h ago)
- [ ] No active GitHub Issues alertmanager-P0/P1 open
- [ ] On-call rotation confirmed (PagerDuty primary)
- [ ] Comms channel verified (Slack/Teams/PagerDuty)

## On-Call Standby

Primary: Halil (telefon/WhatsApp out-of-band ready)
Secondary: <TBD if applicable>
Response expectation: 5-10dk

## Tomorrow's Plan

T-1h: Smoke notification (7-item PASS list verify)
T-0: Cutover started (edge proxy L4 atomic switch)
T+5m → T+72h: Validation playbook checkpoint chain

Halil
```

### 3.3 T-1h — Pre-Cutover Smoke

**Audience**: INT-OWN + INT-OPS

**Template**:

```
Subject: [Pre-Cutover Smoke] T-1h GO/NO-GO Check — D30 Cutover

T-1h pre-cutover smoke active. GO/NO-GO decision in 60 minutes.

## 7-Item PASS List

- [ ] Compose backend /health HTTP 200
- [ ] K8s api-gateway /health HTTP 200
- [ ] ABM-1 last-fire ≤6h ago, result=PASS, failures=0
- [ ] Backup freshness (PG + Vault + KC) all green
- [ ] Vault snapshot ≤24h available
- [ ] No active alerts in alertmanager-bridge
- [ ] No active GitHub Issues alertmanager-P0 open

## GO/NO-GO Decision (T-0)

- All 7 items GREEN → GO (proceed to atomic cutover)
- Any item RED → NO-GO (owner explicit decision: postpone OR fix-and-proceed)

## On-Call Status

Primary: Halil — active standby
Secondary: <TBD if applicable> — active standby

## Action Required

If you are on the comms list, confirm receipt + readiness within 30dk.

Halil
```

### 3.4 T+0 — Cutover Started

**Audience**: All comms list

**Template**:

```
Subject: [Cutover Started] D30 Atomic Cutover Executing — <TIMESTAMP UTC>

Edge proxy L4 atomic switch executed at <TIMESTAMP UTC>.

## Status

- Switch: compose → k8s (≤30s atomic)
- Primary endpoint: https://ai.acik.com → k8s-served
- Initial smoke: in progress

## Next Updates

- T+5m: Initial verify result
- T+1h: Stabilization confirm

## Rollback Posture

- Compose frozen + ayakta (72h warm window)
- Edge proxy nginx pre-cutover backup at /etc/nginx/sites-enabled/ai.acik.com.pre-cutover-backup
- Rollback command chain ready (D30 cutover runbook §9)

## On-Call Active

Primary: Halil
Secondary: <TBD if applicable>

Halil
```

### 3.5 T+5m — Initial Verify

**Audience**: All comms list

**Template (GO scenario)**:

```
Subject: [T+5m Initial Verify] GO — Cutover Stable, Continuing Monitoring

T+5m initial verify complete. **GO** decision.

## Verify Result

- [x] Edge proxy L4 switch verified (HTTP 200 from k8s)
- [x] 4-route browser smoke PASS (perf-test + d35-admin personas)
- [x] No new alerts in alertmanager-bridge
- [x] Pod state stable (no Pending/CrashLoopBackOff)
- [x] No rollback trigger criteria met

## Metrics (T+5m snapshot)

- Latency p95: <VALUE>ms (vs pre-cutover baseline <BASELINE>ms)
- Error rate: <VALUE>% (target <1%)
- ABM-1 federation smoke: <PASS/FAIL/uninitialised>

## Next Checkpoint

T+1h stabilization. Continued monitoring active.

Halil
```

**Template (NO-GO / Rollback scenario)**:

```
Subject: [T+5m ROLLBACK] D30 Cutover Rolled Back — <TIMESTAMP UTC>

T+5m verify detected rollback trigger. Rollback executed.

## Rollback Trigger

<Specific trigger from §4 criteria — e.g. "Error rate 4.2% sustained 5dk">

## Rollback Status

- Edge proxy L4 switch reverted: k8s → compose
- Primary endpoint: https://ai.acik.com → compose-served (pre-cutover state)
- Verify: HTTP 200 from compose backend

## K8s Side

- Pods not destroyed; remain for investigation
- Post-mortem capture: kubectl logs + events

## Communication

- All cutover comms recipients notified
- Investigation underway
- Next attempt: TBD post-RCA

Halil
```

### 3.6 T+1h — Stable Confirm

**Audience**: All comms list

**Template**:

```
Subject: [T+1h Stable] D30 Cutover 1-Hour Stable — Continuing T+24h Watch

T+1h stabilization checkpoint. **GO** continuing.

## Validation Playbook Result

- [x] Flow A: Anonymous /login navigation PASS
- [x] Flow B: d35-admin login standardFlow PASS
- [x] Flow C: 4-route render PASS
- [x] Flow D: Auth refresh PASS
- [x] Metrics within ±10% pre-cutover baseline

## ABM-1

Federation smoke last-fire: <TIMESTAMP UTC>, result=PASS, failures=0

## Next Checkpoint

T+4h Türkiye iş saati başlangıcı (real-traffic window)

Halil
```

### 3.7 T+4h — Business Hours Check

**Audience**: All comms list + INT-BIZ (varsa)

**Template**:

```
Subject: [T+4h Business Hours] D30 Cutover 4-Hour Stable

T+4h checkpoint. Türkiye iş saati başlangıcı window.

## Status

- All validation playbook flows PASS sustained 4h
- ABM-1 chain 1 natural fire post-cutover PASS
- No regression vs pre-cutover baseline

## Next Checkpoint

T+24h first day complete (Flow E full session lifecycle test)

Halil
```

### 3.8 T+24h — Day-1 Summary

**Audience**: All comms list + INT-BIZ

**Template**:

```
Subject: [T+24h Day-1] D30 Cutover First Day Stable Complete

T+24h checkpoint. First day post-cutover complete.

## Day-1 Result

- Validation playbook all 5 flows PASS (A, B, C, D, E)
- ABM-1 4 natural fire (06/12/18/00 UTC) all PASS
- Compose containers still ayakta (warm rollback window)
- Backup chain still fresh
- No GitHub Issues alertmanager-P0/P1 opened

## Metrics 24h Summary

- p95 latency: <STABLE/REGRESSED>
- Error rate: <VALUE>% (target <1%)
- CLS p75: <VALUE> (acknowledged baseline 0.36; V3 backlog)

## Next Checkpoint

T+72h final stabilization → compose decommission GO/NO-GO

Halil
```

### 3.9 T+72h — Decommission Decision

**Audience**: All comms list

**Template (GO scenario)**:

```
Subject: [T+72h Decommission GO] D30 Cutover 72h Stable — Compose Decommission

T+72h final stabilization checkpoint. **GO** decommission.

## 72h Result

- All validation playbook flows PASS sustained 72h
- ABM-1 12-fire natural cron chain (every 6h × 72h = 12 fires) all PASS
- No regression in 72h window
- RUM/field telemetry within acceptance threshold

## Decommission Plan

- Compose containers stop (no remove — 7-day grace period)
- Day 79+ docker rm + final retire
- staging-sw compose state archive for forensic

## V3 Backlog Activation

- #1 GHA→testai connectivity now active
- #2 fin-muhasebe-detay dynamic seed
- #3 M2a1 baseline hard-flip (post-72h safe activation window opens)
- #4 Real-traffic 24-72h RUM continuous

Halil
```

### 3.10 Rollback (Emergency) — Any Time T+X

**Audience**: All comms list

**Template**:

```
Subject: [ROLLBACK EXECUTED] D30 Cutover Rolled Back — <TIMESTAMP UTC>

Rollback executed at <TIMESTAMP UTC>.

## Trigger

<Specific category and detail — §4 criteria>:
- [ ] §4.1 Latency/Error rate
- [ ] §4.2 Operational (health, crashloop, ABM-1 FAIL)
- [ ] §4.3 Sustained (alert flood, scrape lag)
- [ ] §4.4 Manual owner declaration

Details: <specific metric/incident>

## Rollback Status

- Edge proxy L4 switch reverted: k8s → compose
- Verify: HTTP 200 from compose backend
- Time-to-rollback: <X> seconds

## Investigation

- K8s pods preserved (no destruction)
- Logs collected
- Post-mortem ETA: <X> hours

## Next Attempt

- RCA completion: TBD
- Fix iteration: TBD
- Next cutover attempt: TBD post-RCA + fix verify

Halil
```

---

## 4. Comms Channel Setup

### 4.1 Pre-prod minimum

- **Email**: Owner (Halil) + (varsa) atanmış ekip
- **Slack/Teams**: Eğer kullanılıyorsa internal channel
- **GitHub Issues**: alertmanager-bridge already creates issues (alertmanager-P0/P1/P2 + warning/critical/info labels)
- **PagerDuty veya equivalent**: If on-call rotation setup

### 4.2 Production V3 expansion

- **Status page**: External-facing (V3 scope)
- **Customer email lists**: External customers (V3)
- **Vendor support tickets**: Keycloak/Vault/etc. issue tracking

---

## 5. Forensic Audit Trail

Her comms event için:

1. **Timestamp**: UTC + Türkiye saati
2. **Audience list**: Kim alındı
3. **Channel**: Slack/email/PagerDuty
4. **Confirm receipts**: Kim onayladı (timestamp)
5. **Action items**: Recipient'lardan beklenen aksiyon

Archive: cutover post-mortem dosyasında full chain reproduce.

---

## 6. Codex Gap Coverage

| Gap | Status |
|---|---|
| #1 Post-cutover validation playbook | ✅ PR #692 |
| #2 Incident command / rollback authority | 🟡 §3 her template'te belirtildi (V3 production expand) |
| #3 Comms templates | ✅ **BU PR** |
| #4 RUM/field telemetry acceptance | 🟡 PR #692 §4 + V3 dashboard setup |
| #5 Rollback dry-run proof | 🟡 separate PR (next chunk) |
| #6 Docs truth refresh | 🟡 separate PR |

---

## 7. HARD RULE Compliance

- ✅ Pre-Production Full Authority: agent autonomous template prep
- ✅ Continuous Autonomous Mode: cutover prep zinciri devam
- ✅ No Closure Language: comms = checkpoint communication, not closure declaration
- ✅ Cross-AI Peer Review: Codex `019e2cbf` strategic gap #3 absorb
- ✅ No Fake Work: real comms timing + audience + content (not placeholder)

---

## 8. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2cbf-2731-7653-8b4a-d8844179801b
Verdict:          AGREE (strategic gap #3 absorb — V2.1 closure R8 inherited)
Same-provider exception: N/A
Verdict reason:   Codex strategic consult `019e2cbf` gap #3 "comms templates eksik. T-7d, T-1d, T-1h, T+0, T+5m, T+1h, T+24h, rollback, T+72h timing için hazır metinler sınırlı" tespit edildi. Bu runbook 10 timing × audience × template + comms channel setup + forensic audit trail. Yeni implementation YOK; D30 cutover runbook (PR #687) + post-cutover validation playbook (PR #692) ile complement.
