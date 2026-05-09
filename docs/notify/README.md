# Notification Platform Documentation Index

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **Faz**: 23 (Charter → Prod cutover → v1 → v2)

Bu dizin **Faz 23 notification orchestration** için canonical doküman setidir. Project management mantığında — **takip edilebilir, kanıt-bazlı, risk-yönetimli, test-stratejili** — yol haritası + günlük operasyon kayıtları içerir.

---

## 📚 Doküman Hiyerarşisi

### 1. Strategic / Architecture (yön + karar)

| Doküman | Path | Amaç |
|---|---|---|
| **ADR-0013** | [`../adr/0013-notification-orchestration.md`](../adr/0013-notification-orchestration.md) | Architecture decision record + D38-D47 atomic kararlar + 8 OQ |
| **PLAN.md** | [`../../PLAN.md`](../../PLAN.md) | Master roadmap + Faz A-I + Faz 23 entry + Decision Register Status |
| **Charter** | [`../runbooks/RB-faz-23-charter.md`](../runbooks/RB-faz-23-charter.md) | Sub-faz roadmap (23.0-23.X) + kabul kriteri + bağımlılık + canonical status authority |

### 2. Specification (ne yapılır)

| Doküman | Path | Amaç |
|---|---|---|
| **Event contract** | [event-contract.md](event-contract.md) | Intent JSON schema + PG schema + REST API + PII redaction + outage fallback |
| **Feature matrix** | [feature-matrix.md](feature-matrix.md) | 16 kategori × ~140 özellik canlı tracker (☐/🟡/🟢) + tier (Kernel/MVP-dar/MVP-geniş/v1/v2) |
| **Must-have checklist** | [must-have-checklist.md](must-have-checklist.md) | 10 must-have çizgisi + kabul kriteri + evidence path |

### 3. Project Management (nasıl yönetilir)

| Doküman | Path | Amaç |
|---|---|---|
| **Risk register** | [risk-register.md](risk-register.md) | 20 active risk + probability × impact + mitigation + owner |
| **Test strategy** | [test-strategy.md](test-strategy.md) | Per sub-faz test coverage + 5 test types (unit/integration/E2E/manual/regression) + evidence |
| **Sprint plan** | [sprint-plan.md](sprint-plan.md) | Task-level breakdown + estimation + ownership + Tier T1-T5 (~280h v1) |
| **Milestones** | [milestones.md](milestones.md) | M0-M9 + DoD checklist + critical path + slip detection |
| **Dependency graph** | [dependency-graph.md](dependency-graph.md) | Task-level dependency + critical path + parallel tracks |
| **Stakeholder plan** | [stakeholder-plan.md](stakeholder-plan.md) | Communication cadence + audience patterns + anti-patterns |

### 4. Operational (nasıl koşulur)

| Doküman | Path | Amaç |
|---|---|---|
| **Vault paths runbook** | [`../runbooks/RB-faz-23-2-notify-vault-paths.md`](../runbooks/RB-faz-23-2-notify-vault-paths.md) | ESO ExternalSecret operator setup + key rotation + audit |
| **KVKK erasure runbook** | [`../runbooks/RB-notify-kvkk-erasure.md`](../runbooks/RB-notify-kvkk-erasure.md) | KVKK Art.11 erasure + Art.13 right-to-information |
| **Strict subscriberId cutover** | [`../operations/RUNBOOKS/RB-notify-strict-subscriberid-cutover.md`](../operations/RUNBOOKS/RB-notify-strict-subscriberid-cutover.md) | F1-F6 strict identity flip + storm response + rollback |
| **Audit retention preflight** | [`../../scripts/operations/notify-audit-retention-preflight.sh`](../../scripts/operations/notify-audit-retention-preflight.sh) | 7-section read-only inventory + DECISION GATE for C.2 |

### 5. Live Truth (gerçek durum)

| Doküman | Path | Amaç |
|---|---|---|
| **current-state.md** | [`../state/current-state.md`](../state/current-state.md) | Live runtime truth (cluster state, post-deploy evidence) |
| **session-handoff** | `../session-handoff-YYYY-MM-DD.md` | Per-session handoff doc (5-alan format) |

---

## 🎯 Quick Status (2026-05-09 Session 39)

### Sub-Faz Status
- 🟢 **23.0** Charter (done)
- 🟡 **23.1** Kernel partial (D29-Functional evidence pending)
- 🟡 **23.2** MVP-dar partial (3/8 — Session 39 hardening only; 6 pending)
- ⏳ **23.3** SMS NetGSM (pending)
- 🟡 **23.4** v1 DLR + In-app UI partial (UI LIVE; SMS DLR pending)
- ⏳ **23.5** Preference UI (pending)
- ⏳ **23.6** Teams + Slack threading (pending)
- ⏳ **23.7** Push FCM/APNS (pending)
- 🟡 **23.8** Analytics + bounce loop partial (alerts LIVE; Tempo/bounce pending)
- 🟡 **23.9** Prod cutover partial (LIVE; 72h observation T+72h=2026-05-11 + rollback prova + browser SSO pending)
- ⏳ **23.X** v2 (deferred)

### Must-Have Status
- 🟢 7/10 fully done (#1-#6, #9)
- 🟡 2 partial (#7 retention LIVE + erasure pending; #10 observability LIVE + D43 pending)
- ⏳ 1 pending (#8 preference + critical bypass)
- **~80% must-have coverage** (NOT production-ready guarantee)

### Active Risks
- 🟡 R1 NetGSM provider contract delay (23.3 blocker)
- 🟡 R2 KVKK erasure legal review (23.2.B blocker)
- 🟡 R3 DKIM/SPF/DMARC prod activation
- 🔴 R9 D43 outage fallback drill pending
- 🔴 R10 Multi-tenant migration data drift (DEFER Faz 21)

### Next Critical Milestone
**M1**: 23.9 Cutover Closure (target 2026-05-12)
- T2.3.1 72h observation completion (T+72h = 2026-05-11 19:42Z)
- T2.3.2 Rollback prova execution
- T2.3.3-4 Browser SSO verify (testai + ai.acik.com)

---

## 🔄 Update Discipline

**HARD RULE — every PR**:
1. Charter sub-faz marker güncellenir (eğer status değiştiyse)
2. must-have-checklist criteria 🟢 işaretlenir (kabul kriteri kapanırsa)
3. feature-matrix marker güncellenir (özellik LIVE oldu)
4. risk-register: yeni risk eklenir veya status update
5. sprint-plan: task 🔴 → 🟡 → 🟢 ilerletilir
6. milestones.md: M-N DoD checklist update
7. current-state.md: live evidence delta
8. PLAN.md D-karar status sync (gerekirse)

Inline doc update; dedicated doc-only PR yalnız retroaktif alignment veya taxonomy değişikliği için.

**Codex peer review HARD RULE**: Her PR cross-AI review (Code Claude → Codex AGREE/REVISE/RED).

**Mark discipline**: Sub-faz `🟢 done` ancak ALL kabul kriteri 🟢 olduğunda işaretlenir. Substantial+missing = 🟡 partial.

---

## 📅 Sprint Cadence

- **Daily**: TodoWrite update + chat summary
- **Weekly**: stakeholder-plan format weekly summary
- **Per-PR**: continuous chat update
- **Per-milestone**: detailed evidence + risk closure log
- **Per-incident**: immediate alert + retrospective
- **Quarterly**: comprehensive review + Codex strategic retrospective

---

## 🤝 Cross-AI Peer Review (HARD RULE)

Her implementation PR için:
- Code Claude yazıyorsa → Codex review approves
- Code Codex yazıyorsa → Claude review approves
- AGREE → admin merge meşru sayılır
- REVISE → fix iter
- RED → kullanıcıya rapor

Codex thread chain referansları her PR'da audit trail için kayıt.

---

## 🚀 Project Management Readiness

Bu doküman seti şunları sağlar:

✅ **Trackable plan** — feature-matrix + must-have-checklist + sprint-plan
✅ **Completed marked** — Sub-Faz Tablosu + must-have-checklist [x] + status emoji
✅ **Completion criteria** — kabul kriteri tabloları + DoD per milestone
✅ **Risk management** — 20 risk register + probability × impact + mitigation
✅ **Test planning** — 5 test types + per-sub-faz coverage + evidence path
✅ **Sprint estimation** — task-level hours + tier breakdown + velocity baseline
✅ **Milestone tracking** — M0-M9 + critical path + slip detection
✅ **Dependency graph** — task-level + parallel tracks + bottleneck identification
✅ **Stakeholder communication** — cadence + audience patterns + cross-AI peer review
✅ **Decision register status** — D38-D48 status sync to live state

**Now we are PM-ready.** Next step: any sub-faz closure work follows this canonical doc set; doc updates inline per PR; weekly summary + per-milestone evidence; risk register reviewed weekly.
