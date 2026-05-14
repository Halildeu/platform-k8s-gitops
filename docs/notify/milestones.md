# Notification Platform — Milestone Tracker

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Sprint plan**: [sprint-plan.md](sprint-plan.md)
> **Risk register**: [risk-register.md](risk-register.md)

Bu doküman **target dates + critical path + go/no-go gates** sağlar. Milestone slip görünürlüğü + dependency chain visualization.

---

## Milestone Roadmap

### M0 — Faz 23.0 Charter (✅ done 2026-05-05)

- 5 artifact merged (ADR-0013 + event-contract + feature-matrix + must-have-checklist + RB-faz-23-charter)
- PLAN.md Faz 23 entry + D38-D47
- 2026-05-09 Session 39 truth alignment PR #439

### M1 — 23.9 Cutover Closure (🟡 in progress, target 2026-05-12)

**Definition of Done**:
- [ ] T2.3.1 72h observation completion (T+72h = 2026-05-11 19:42Z natural)
- [ ] T2.3.2 Rollback prova execution (drill mode)
- [ ] T2.3.3 Browser SSO verify testai.acik.com
- [ ] T2.3.4 Browser SSO verify ai.acik.com
- [ ] T2.3.5 Evidence document published
- [ ] Charter 23.9 marker 🟡 → 🟢
- [ ] Risk register: R7 closed, R8 confirmed mitigated

**Blockers**: R7 (browser verify user availability)
**Owner**: ops + user
**Dependencies**: T2.3 task chain

### M2 — 23.1 D29-NOTIFY-Functional Evidence (🔴 target 2026-05-12)

**Definition of Done**:
- [ ] T2.1.1 Email D29-Functional (Mailpit screenshot + delivery row INSERT)
- [ ] T2.1.2 Slack D29-Functional (test channel screenshot + delivery row)
- [ ] T2.1.3 Webhook D29-Functional (HMAC trace + delivery row)
- [ ] OpenFGA allow + deny case verified per channel (D29-Authorized)
- [ ] Evidence document `docs/faz-23-evidence/2026-05-12-23-1-d29-functional.md`
- [ ] Charter 23.1 marker 🟡 → 🟢

**Blockers**: None (operator/agent action)
**Owner**: ops
**Dependencies**: M1 (cluster stable)

### M3 — 23.2 Production MVP Dar Closure (🟡 ALMOST CLOSED — 2026-05-14 audit)

**Status update 2026-05-14 (Session 49)**: 7/8 task done. Tek blocker R2 KVKK legal review (external dependency).

**Definition of Done** (must-have #6 + #7 + #8 + #9 + #10 fully closed):
- [x] T1.1 23.2.A Preference API + critical bypass merged + LIVE — Session 41 acceptance evidence
- [~] T1.2 23.2.B KVKK erasure + right-to-information merged + LIVE — **subscriber self-service LIVE**; admin erasure source-ready, R2 legal review external pending
- [x] T1.3 23.2.C Provider config rollback merged — platform-backend PR #140 MERGED (2026-05-10, R12 mitigated FULL ACCEPTANCE evidence)
- [x] T1.4 23.2.D Outage fallback bypass D43 merged + drill executed — first controlled drill 2026-05-10 (R9 mitigated)
- [x] T1.5 23.2.E Data classification policy merged — 2026-05-10 LIVE acceptance
- [x] T1.6 23.2.F Abuse prevention guards merged — Session 41 FULL ACCEPTANCE (R13+R19 mitigated)
- [~] All Faz 23.2 kabul kriteri 🟡 (7/8 done, 1 external blocker)
- [ ] Charter 23.2 marker 🟡 → 🟢 — R2 closure sonrası
- [~] Risk register: R2 active (KVKK legal review), R9 🟢 mitigated, R12 🟢 mitigated, R13 🟢 mitigated, R19 🟢 mitigated

**Remaining blocker**: R2 (KVKK legal review external) — admin erasure compliance attestation. ETA 2026-05-25.
**Owner**: legal (R2 closure)
**Dependencies**: M1 (cluster stable) — done

### M4 — 23.3 SMS NetGSM Activation (🔴 target 2026-06-22)

**Definition of Done**:
- [ ] T3.1.1 NetGSM provider contract signed + sandbox account active
- [ ] T3.1.3-T3.1.7 SMS adapter + DLR callback LIVE
- [ ] T3.1.8 4 workflow live test passed (admin invite, password reset, drift alarm, break-glass)
- [ ] D29-NOTIFY 3-katman SMS evidence
- [ ] Charter 23.3 marker ⏳ → 🟢
- [ ] Risk register: R1 closed

**Blockers**: R1 (NetGSM contract delay)
**Owner**: ops + dev + legal (contract)
**Dependencies**: M3 (23.2 stable)

### M5 — 23.5 Preference UI (🔴 target 2026-06-29)

**Definition of Done**:
- [ ] T3.2 mfe-host preference settings page LIVE
- [ ] Per-channel + per-topic + quiet hours + frequency limit + unsubscribe one-click UI
- [ ] D29-NOTIFY UI flow evidence
- [ ] Charter 23.5 marker ⏳ → 🟢

**Blockers**: T1.1 backend dependency
**Owner**: dev (frontend)
**Dependencies**: T1.1 (preference API), M3

### M6 — 23.4 Closure (🟡 split into M6a + M6b — Codex iter-2 absorb)

> **Split rationale (2026-05-09)**: 23.4 closure iki bağımsız part'a bölündü; M6a (archive + history filter) M3 ile paralel, M6b (SMS DLR UI) M4 sonrası gate'lidir.

#### M6a — 23.4 Archive + History (🟡 target 2026-06-15, parallel with M3)

**Definition of Done**:
- [ ] T2.2.1 Archive UI button
- [ ] T2.2.2-3 30d notification history filter (FE + BE)
- [ ] T2.2.4 Integration test (archive + history)
- [ ] Charter 23.4 marker (archive/history portion) 🟡 → 🟢

**Blockers**: None (parallel with M3)
**Owner**: dev (frontend + backend)
**Dependencies**: M1 stable (cluster + auth)

#### M6b — 23.4 SMS DLR UI (🔴 target post-M4, ~2026-06-29)

**Definition of Done**:
- [ ] FE inbox SMS DLR badge (status: sent/delivered/failed)
- [ ] T3.1.7 DLR callback endpoint LIVE (M4 dep)
- [ ] Charter 23.4 marker (SMS DLR portion) ⏳ → 🟢
- [ ] Charter 23.4 fully 🟢 only when both M6a + M6b done

**Blockers**: M4 (SMS NetGSM + DLR callback)
**Owner**: dev (frontend)

### M7 — v1 Closure (🔴 target 2026-08-15)

**Definition of Done**:
- [ ] T4.1 23.6 Teams + Slack threading LIVE
- [ ] T4.2 23.7 Push (FCM + APNS + Web Push) LIVE
- [ ] T4.3 23.8 Tempo + bounce loop + per-tenant Grafana LIVE
- [ ] All v1 sub-faz kabul kriteri 🟢 (23.6, 23.7, 23.8)
- [ ] Charter markers all updated
- [ ] Risk register: R11, R16 closed

**Blockers**: M5 done + M6a/M6b done (split closure) — M3 + M4 zaten önceki kapı
**Owner**: dev + ops + gitops

### M8 — Multi-tenant Trigger Gate (🔴 target 2026-09-01)

**Definition of Done** (Faz 21 multi-tenant öncesi):
- [ ] M7 v1 stable (≥30 day in production)
- [ ] R10 (multi-tenant migration risk) mitigation plan ready
- [ ] Pre-migration audit + dry-run + per-tenant isolation test
- [ ] Faz 21 charter draft

**Blockers**: M7 v1 stable + R10 mitigation
**Owner**: dev + arch (Codex strategic consultation)

### M9 — Faz 23.X v2 Trigger (🔴 deferred — gerekçe çıkarsa)

**Definition of Done**:
- v1 stable + müşteri/ops gerekçesi açık
- Codex strategic retrospective verdict
- 8-12 hafta planning

**Trigger condition**: Customer or ops requirement clearly identified.

---

## Critical Path Visualization

```
                             ┌─── M2 (D29 evidence)  ─── parallel
                             │
M0 ──▶ M1 ───────────────────┼──▶ M3 ─────▶ M4 ──┬──▶ M6b ──┐
(charter)  (cutover)         │   (23.2)   (SMS)  │  (DLR UI)│
                             │     │             ▼          │
                             │     ▼          M5 (UI)       ▼
                             │   Risk gates:                M7 ──▶ M8 ──▶ M9
                             │   R2 KVKK, R9 D43            (v1)  (mt)  (v2)
                             │   R13 abuse, R19 storm
                             │
                             └─── M6a (archive/history) ─── parallel with M3
```

**Critical path** (longest dependent chain):
**M0 → M1 → M3 → M4 → M5 → M7 → M8**

**Parallel tracks**:
- M2 (D29 evidence) parallel with M1 closure
- M6a (23.4 archive/history) parallel with M3 (23.2)
- M6b (23.4 SMS DLR UI) gated by M4 (post-SMS); not on critical path
- M5 (Preference UI) blocked by M3 backend (T1.1)
- M7 v1 sub-faz tracks (23.6/23.7/23.8) parallel after M5 unblocked

---

## Slip Detection

**Weekly review**:
- Compare actual vs target date
- Update milestone status
- If >7 day slip: trigger Codex strategic retrospective
- If >14 day slip: stakeholder notification + scope re-baseline

**Sub-faz acceptance gate**: NO milestone marked 🟢 unless ALL DoD items 🟢.

---

## Status Legend

- 🟢 **Done**: ALL DoD items closed; evidence path filled
- 🟡 **In Progress**: substantial work done, some DoD items pending
- 🔴 **Pending**: not started or blocked
- 🚧 **Blocked**: external dependency unmet (R1, R7 etc)

---

## Last Update: 2026-05-09 (Session 39)

Current state:
- M0 🟢 (charter + truth alignment)
- M1 🟡 (cutover LIVE, 72h observation in progress, T2.3 chain pending)
- M2 🔴 (T2.1 D29 evidence pending)
- M3-M9 🔴 (pending)

Total v1 progress: 1/8 milestones (M0 done) = **12.5% milestone-level**.
Total Faz 23 progress: 1/9 (incl. M9 v2 deferred) = **11%**.
Combined with sub-faz partial credit: ~30% v1 scope (per charter snapshot).
