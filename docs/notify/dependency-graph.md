# Notification Platform — Dependency Graph

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Sprint plan**: [sprint-plan.md](sprint-plan.md)
> **Milestones**: [milestones.md](milestones.md)

Bu doküman **task-level dependency graph + critical path + parallel tracks** sağlar. Sprint plan'daki T1.x..T5.x task'larının dependency'lerini görselleştirir.

---

## Charter Sub-Faz Dependency (Existing)

```
[Faz 22.1.1b III review verdict]
       │
       ▼
   23.0 ───▶ 23.1 ───▶ 23.2 ───▶ 23.3 ───▶ 23.4 ───┬──▶ 23.5
                                                    │
                                                    ├──▶ 23.6
                                                    │
                                  [Faz 22.2] ──────▶ 23.7
                                                    │
                                                    └──▶ 23.8 ───▶ 23.9
                                                                    │
                                                                    ▼
                                                                  23.X (later)
```

**Note**: 23.0 paralel başlanabilir. 23.1 başlangıcı için 22.1.1b III review verdict zorunlu (pre-prod context'te bypass edildi 2026-05-08 user onayı).

---

## Task-Level Dependency (Tier 1: 23.2 Closure)

### T1.1 Preference API (23.2.A must-have #8)

```
T1.1.1 V9 migration
        │
        ▼
T1.1.2 Domain entity + repository
        │
        ▼
T1.1.3 REST API
       ├──▶ T1.1.4 Send pipeline check
       │            │
       │            ├──▶ T1.1.6 Quiet hours bypass
       │            │
       │            ├──▶ T1.1.7 Frequency limit bypass
       │            │
       │            └──▶ T1.1.5 Critical bypass ◀─── T1.5.2 (data classification enum + validator)
       │                              │
       │                              ▼
       │                         T1.1.9 Integration test
       │                              │
       │                              ▼
       └──▶ T1.1.8 Unsubscribe link    │
                                       ▼
                                  T1.1.10 Gitops env enable
                                       │
                                       ▼
                                  T1.1.11 Codex review + merge
                                       │
                                       ▼
                                  T1.1.12 Doc marker update
```

**Critical path**: T1.1.1 → T1.1.2 → T1.1.3 → T1.1.4 → T1.1.5 → T1.1.9 → T1.1.10 → T1.1.11 (~22h serial)
**Parallel branches**: T1.1.6, T1.1.7, T1.1.8 (~6h saved if parallelized)
**Cross-tier dep**: T1.5.2 (data classification enum + validator) blocks T1.1.5 critical bypass — T1 ve T1.5 tracks **bağımsız değil**, orchestration zorunlu

### T1.2 KVKK Erasure (23.2.B must-have #7 closure)

```
T1.2.1 DELETE /audit/me ──┐
                          │
T1.2.2 GET /audit/me  ────┤
                          │
T1.2.3 Append-only verify ┤
                          │
                          ▼
                     T1.2.4 + T1.2.5 Integration tests
                          │
                          ▼
                     T1.2.6 Runbook update
                          │
                          ▼
                     T1.2.7 Legal review (R2 mitigation)
                          │
                          ▼
                     T1.2.8 Codex review + merge
```

**Independent of T1.1** (parallel track)

### T1.3 Provider Config Rollback (23.2.C)

```
T1.3.1 V9 history table
        │
        ▼
T1.3.2 Versioning service
        │
        ▼
T1.3.3 Atomic switch + cache invalidate
        │
        ▼
T1.3.4 Integration test
        │
        ▼
T1.3.5 Runbook
        │
        ▼
T1.3.6 Codex review + merge
```

**Independent of T1.1, T1.2** (parallel track)

### T1.4 Outage Fallback Bypass D43 (23.2.D must-have #10)

```
T1.4.1 Vault fallback path ──┐
                             │
                             ▼
T1.4.2 ESO ExternalSecret    │
                             │
                             ▼
T1.4.3 Alertmanager dual-route ──┐
                                 │
T1.4.5 Drift alarm-receiver chain (parallel) ──┤
                                 │
                                 ▼
                            T1.4.6 Break-glass dual-channel
                                 │
                                 ▼
                            T1.4.7 Runbook
                                 │
                                 ▼
                            T1.4.8 Drill execution
                                 │
                                 ▼
                            T1.4.9 Codex review + merge
```

**Independent track**

### T1.5 Data Classification (23.2.E)

```
T1.5.1 V9 field migration
        │
        ▼
T1.5.2 Enum + validator
        │
        ├──▶ blocks T1.1.5 (critical bypass)
        │
        ▼
T1.5.3 Send pipeline behavior
        │
        ▼
T1.5.4 Integration test
        │
        ▼
T1.5.5 + T1.5.6 Runbook + Codex review
```

### T1.6 Abuse Guards (23.2.F)

```
T1.6.1 Rate limit per source
       ├──▶ T1.6.2 Duplicate flood
       │
       ├──▶ T1.6.3 Webhook fan-out cap
       │
       └──▶ T1.6.4 429 + audit
                  │
                  ├──▶ T1.6.5 PrometheusRule alert
                  │
                  ▼
             T1.6.6 Integration test
                  │
                  ▼
             T1.6.7 Codex review + merge
```

---

## Task-Level Dependency (Tier 2: Closure)

### T2.1 23.1 D29-Functional Evidence (parallel, no code)

```
T2.1.1 Mailpit evidence ──┐
T2.1.2 Slack evidence ────┤
T2.1.3 Webhook evidence ──┤
                          ▼
                     T2.1.4 Evidence doc
                          │
                          ▼
                     T2.1.5 Charter marker update
```

**Independent of all other tracks**

### T2.2 23.4 Closure

```
T2.2.1 FE archive button (independent) ──┐
                                          │
T2.2.2 Backend 30d filter ──┐             │
                            ▼             │
                       T2.2.3 FE 30d UI    │
                            │              │
                            ▼              │
                       T2.2.4 Integration ◀┘
                            │
                            ▼
                       T2.2.6 Codex review + merge
```

**SMS DLR portion**: deferred to M4 (T3.1.7)

### T2.3 23.9 Closure (mostly time-passive)

```
T2.3.1 72h observation (TIME-PASSIVE, T+72h = 2026-05-11)
        │
        ▼
T2.3.2 Rollback prova
        │
T2.3.3 + T2.3.4 Browser SSO verify (user, parallel) ──┐
        │                                              │
        └──────────────────────┬───────────────────────┘
                               ▼
                          T2.3.5 Evidence doc
                               │
                               ▼
                          T2.3.6 Charter marker update
```

---

## Task-Level Dependency (Tier 3: SMS + Preference UI)

### T3.1 SMS NetGSM (23.3)

```
T3.1.1 NetGSM contract (R1) ◀── BLOCKING dependency
        │
        ▼
T3.1.9 Vault SMS creds path
        │
T3.1.2 SmsProvider interface ──┐
                               ▼
T3.1.3 NetGsmClient ──┐
                      ▼
T3.1.4 GSM-7/UCS-2 + sender ID
        │
T3.1.5 İletimerkezi secondary (parallel)
        │
        ▼
T3.1.6 Provider failover
        │
T3.1.7 DLR callback endpoint
        │
        ▼
T3.1.8 4 workflow live test
        │
T3.1.10 In-app inbox API closure (independent track) ──┐
                                                        │
                                                        ▼
                                                  T3.1.11 Codex review + merge
```

### T3.2 Preference UI (23.5)

```
T3.2.1 mfe-host route + skeleton
        │  blocked by T1.1.3 (preference API)
        ▼
T3.2.2 Per-channel toggle ──┐
                            ▼
T3.2.3 Per-topic toggle ──┐
                          ▼
T3.2.4 Quiet hours editor ──┐
                            ▼
T3.2.5 Frequency limit ──┐
                         │
T3.2.6 Unsubscribe one-click (parallel) ──┐
                         │                 │
                         └──────┬──────────┘
                                ▼
                           T3.2.7 Integration test
                                │
                                ▼
                           T3.2.8 Codex review + merge
```

---

## Task-Level Dependency (Tier 4: v1)

### T4.1 Teams + Slack (23.6) — Independent
### T4.2 Push (23.7) — Faz 22.2 endpoint-admin Lab tier dep
### T4.3 Tempo + Bounce (23.8) — Independent

All three Tier 4 tracks **can run in parallel** post-T3 closure.

---

## Critical Path (End-to-End v1)

```
M0 (Charter)
  ▼
M1 (23.9 Cutover Closure)
  ▼
[Parallel: M2 (23.1 D29 evidence) + M6 (23.4 archive UI)]
  ▼
M3 (23.2 closure) ──── critical path bottleneck (~100h, multiple risks)
  ├──▶ M5 (23.5 Preference UI) ─ blocked by T1.1
  │
  ▼
M4 (23.3 SMS NetGSM) ──── R1 contract risk
  │
  ├──▶ T3.1.7 DLR callback closes M6 SMS portion
  │
  ▼
M7 (v1 closure: 23.6 + 23.7 + 23.8 parallel)
  ▼
M8 (multi-tenant trigger gate)
  ▼
M9 (v2 deferred)
```

**Critical path duration**: M0 → M3 → M4 → M7 = ~13-15 weeks (3-4 months)
**Bottleneck milestones**: M3 (~100h, 6 sub-tasks), M7 (~99h, 3 v1 sub-faz parallel)

---

## Parallel Track Opportunities

| Tracks | Reason | Saving |
|---|---|---:|
| T1.2 + T1.3 + T1.4 + T1.6 | 23.2 sub-tasks **mostly** independent (T1.1 ↔ T1.5 cross-tier dep var; T1.1.5 critical bypass T1.5.2 enum+validator'a blocked, T1.5.3 send pipeline T1.1.4'e blocked — bu iki track partial paralel only) | ~25h serial → ~12h parallel |
| T2.1 + T2.2 + T2.3 | M2/M6/M1 closure parallel | ~10h saved |
| T3.1 + T3.2 backend portion | While SMS contract pending, FE preference UI can start with T1.1.3 backend | ~10h saved |
| T4.1 + T4.2 + T4.3 | v1 sub-faz independent | ~50h saved |

**Total potential savings via parallelization**: ~100h (out of ~280h v1 total)

---

## External Dependency Tracking

| Dep | Required By | ETA | Status |
|---|---|---|:---:|
| Faz 22.1.1b III review verdict | 23.1 | bypassed pre-prod | 🟡 |
| Faz 22.2 endpoint-admin Lab tier | 23.7 | TBD | ⏳ |
| NetGSM provider sandbox account (R1) | 23.3 | 2026-05-30 target | 🟡 |
| Legal KVKK Art.11 review (R2) | 23.2.B | 2026-05-25 target | 🔴 |
| DKIM/SPF/DMARC prod domain config (R3) | 23.2 | TBD ops | 🟡 |
| Browser SSO user availability (R7) | 23.9 | per-cutover | 🟡 |

---

## Last Update: 2026-05-09 (Session 39)

**Active critical path**: M1 → M3 → M4 (with R1 + R2 risk gates)
**Next decision point**: M1 closure 2026-05-12 → trigger M3 (23.2.A..F) start
