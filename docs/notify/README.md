# Notification Platform Documentation Index

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **Faz**: 23 (Charter → Prod cutover → v1 → v2)

Bu dizin **Faz 23 notification orchestration** için canonical doküman setidir. Project management mantığında — **takip edilebilir, kanıt-bazlı, risk-yönetimli, test-stratejili** — yol haritası + günlük operasyon kayıtları içerir.

---

## GitHub Project Board (Faz 2 migration — 2026-05-17)

Aktif Faz 23 durum takibi **[platform Roadmap board](https://github.com/users/Halildeu/projects/2)** üzerinde — `Faz` alanı `Faz 23` view. 28 item migrate edildi: 1 umbrella (#751) + 10 milestone (#752-761) + 12 açık risk (#762-773) + 4 aktif RAID issue (#774-777) + 1 must-have gate (#778). Faz 23 ~Session 49'dan (2026-05-14) beri dormant.

**Source-of-truth boundary** (Codex `019e361d` AGREE):

- **Board canonical** — aktif iş, açık risk, açık issue, milestone/gate durumu. Board `Status` alanı aktif-iş ilerlemesinin canonical kaydı.
- **Docs canonical** — spec (event-contract), kabul kriteri, evidence ledger, deferred inventory (feature-matrix 178 satır, sprint-plan tier T2-T5), DoD detayı, mitigated/closed risk arşivi.
- Bir item için status hem board'da hem doc'ta **bağımsız yürütülmez** — board issue canonical; doc satırı `board: #N`, board issue body'si `source-doc:` backlink taşır.
- `needs-verification` label'lı item `Done / Mitigated / Closed / Accepted` statüsüne **taşınamaz** (governance rule).
- `source-ready / desired-state / live-deployed / accepted` ayrı katmanlardır; board `Status=Done` yalnız **accepted/live** demektir — source-ready değil.

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
| **Feature matrix** | [feature-matrix.md](feature-matrix.md) | 16 kategori × ~178 özellik canlı tracker (☐/🟡/🟢) + tier (Kernel/MVP-dar/MVP-geniş/v1/v2) |
| **Must-have checklist** | [must-have-checklist.md](must-have-checklist.md) | 10 must-have çizgisi + kabul kriteri + evidence path |

### 3. Project Management (nasıl yönetilir)

| Doküman | Path | Amaç |
|---|---|---|
| **Risk register** | [risk-register.md](risk-register.md) | 22 active risk (R1-R22; R21 provider rate-limit + R22 GHCR outage Codex iter-2 absorb) + probability × impact + mitigation + owner |
| **RAID log** | [raid-log.md](raid-log.md) | Risk dışı **assumption + issue + dependency** ayrı boyut (10 + 5 + 10); Codex `019e0c28` F5 absorb |
| **Checkpoint template** | [checkpoints/_TEMPLATE.md](checkpoints/_TEMPLATE.md) | Per-milestone immediate checkpoint pattern (weekly summary öncesi gate) — placeholder M1+M2: [2026-05-12-m1-m2-status.md](checkpoints/2026-05-12-m1-m2-status.md) |
| **Test strategy** | [test-strategy.md](test-strategy.md) | Per sub-faz test coverage + 5 test types (unit/integration/E2E/manual/regression) + evidence |
| **Sprint plan** | [sprint-plan.md](sprint-plan.md) | Task-level breakdown + estimation + ownership + Tier T1-T5 (~232-235h v1 residual; M3 stale audit 2026-05-09 re-baseline; ~280h historical baseline superseded) |
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
- 🟡 **23.2** MVP-dar partial (Session 39 hardening 5/8 LIVE; Session 41 re-baseline 2026-05-09 19:50Z — backend source-ready 12/12 + live-deployed 9/12 + acceptance 0/12 + blocked 2/12; T1.6 abuse guards LIVE + T1.4 D43 4-PR source-ready; ~17-22h residual; drill execution + acceptance gate operator action; R13 + R19 mitigated)
- ⏳ **23.3** SMS NetGSM (pending)
- 🟡 **23.4** v1 DLR + In-app UI partial (UI LIVE; SMS DLR pending)
- ⏳ **23.5** Preference UI (pending)
- ⏳ **23.6** Teams + Slack threading (pending)
- ⏳ **23.7** Push FCM/APNS (pending)
- 🟡 **23.8** Analytics + bounce loop partial (alerts LIVE; Tempo/bounce pending)
- 🟡 **23.9** Prod cutover partial (LIVE; 72h observation T+72h=2026-05-11 + rollback prova + browser SSO pending)
- ⏳ **23.X** v2 (deferred)

### Must-Have Status (M3 stale audit 2026-05-09 5-state matrix re-baseline)
- 🟢 7/10 fully done (#1, #2, #3, #4, #5, #6, #9)
- 🟡 3 partial (#7 retention LIVE + admin erasure source-ready/R2 legal/subscriber endpoint pending; #8 ⏳→🟡 demote source-ready + RAID I6 acceptance gate; #10 observability LIVE + D43 pending)
- ⏳ 0 pending
- **~85% must-have coverage** (7×1.0 + 3×0.5 = 8.5/10; partial weight 0.5 semantik, source-ready bias var; NOT production-ready guarantee)

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

**HARD RULE — board canonical (Faz 2/3 migration, 2026-05-17 sonrası)**:

- Aktif Faz 23 durum değişimi → ilgili **board issue** güncellenir (`Status` / `Kind` / alanlar). Aynı durumu doc'a paralel yazmak YASAK — drift kaynağı.
- PR yalnız **değişen canonical yüzeyi** günceller: kod/runtime değişimi → board issue + `current-state.md`; spec / kabul kriteri / evidence → ilgili doc.
- Yeni risk veya issue → board'da issue açılır + ilgili doc'a satır + **iki yönlü backlink** (`board: #N` doc'ta ↔ `source-doc:` issue body'sinde).
- feature-matrix: aktifleşen özellik board'da issue alır (`tracked by #N`); row marker tek başına progress değildir.
- `needs-verification` label'lı item closure statüsüne taşınamaz; `source-ready ≠ live-deployed ≠ accepted` ayrımı korunur.

> Eski "her PR 8 dokümanı günceller" kuralı **superseded** — board'a göç öncesi disiplindi ve çoklu-yüzey güncelleme drift'in kaynağıydı (Codex `019e361d`).

**Codex peer review HARD RULE**: Her implementation PR cross-AI review — implementer ≠ reviewer (farklı sağlayıcı: Claude ↔ Codex).

**Mark discipline**: Board `Status=Done` ancak ALL kabul kriteri accepted/live olduğunda. Substantial + missing = `In Progress`. `needs-verification` varken closure YASAK.

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
✅ **Risk management** — 22 risk register + probability × impact + mitigation
✅ **Test planning** — 5 test types + per-sub-faz coverage + evidence path
✅ **Sprint estimation** — task-level hours + tier breakdown + velocity baseline
✅ **Milestone tracking** — M0-M9 + critical path + slip detection
✅ **Dependency graph** — task-level + parallel tracks + bottleneck identification
✅ **Stakeholder communication** — cadence + audience patterns + cross-AI peer review
✅ **Decision register status** — D38-D48 status sync to live state

**PM artifact baseline present** (10 capability tracker + risk + test + sprint + milestones + deps + stakeholders + decision register sync + update discipline). Production-ready guarantee değil; ~30% v1 scope coverage (literal feature) + 7/10 must-have done + 3 partial source-ready bias = ~85% must-have coverage halinde **PM-ready execution discipline** kurulmuştur (M3 stale audit 2026-05-09 re-baseline per `docs/notify/m3-stale-audit-2026-05-09.md`). Next step: any sub-faz closure work follows this canonical doc set; doc updates inline per PR; weekly summary + per-milestone evidence; risk register reviewed weekly.

> **Honesty disclaimer (Codex iter-2 absorb 2026-05-09)**: "Now we are PM-ready" overclaim'inden kaçınılmıştır. Yapısal PM capability'leri tamamlandı, ancak feature marker pass deferred (~178 row literal sweep follow-up) + cross-doc consistency sweep (Codex iter-1/2 absorb) + KVKK erasure sub-faz authority alignment = dokümantasyon kalitesi iyileştirme süreci aktif.
