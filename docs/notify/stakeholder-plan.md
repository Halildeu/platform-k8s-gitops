# Notification Platform — Stakeholder Communication Plan

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)

Bu doküman **kim, ne zaman, ne kanaldan, hangi format** ile bilgilendirilir? agent ↔ user iletişim disiplinini kayıt eder.

---

## Stakeholders

| Stakeholder | Role | Interest | Authority | Update Channel |
|---|---|---|---|---|
| **Kullanıcı (Halil)** | Owner / Operator | Strategic direction, full visibility | Decisions on scope, deferral, risk tolerance | Chat (continuous), per-PR notification, weekly summary |
| **Claude (this agent)** | Implementation | Execution discipline, doc-drift control | Tactical decisions per Codex consensus | Self-update (todos, current-state.md) |
| **Codex** | Peer reviewer | Cross-AI verdict on PR + strategic | Veto on AGREE/REVISE | Codex thread MCP |
| **legal** | KVKK compliance | Erasure + retention + IYS | Block 23.2.B and 23.3 commercial SMS until reviewed | Async review (PR #130 KVKK pattern) |
| **ops** | Cluster operator | Vault rotation, drill execution | Browser SSO, drill scheduling | SSH + Slack #ops |
| **Faz 22.2 endpoint-admin agent** | External dep | FCM/APNS coupling | Provides Lab tier readiness signal | Cross-faz coordination (TBD) |

---

## Communication Cadence

### Continuous (per-action)

**Trigger**: Every PR creation / merge / cluster apply / risk identified
**Channel**: Chat thread (this conversation)
**Format**:
- 1-line summary
- PR URL + status
- Live evidence (cluster state, log line, metric query)
- Next action proposed

**Owner**: agent

### Daily / Per-Session

**Trigger**: Each Claude session block end
**Channel**: TodoWrite + chat summary
**Format**:
- Done count (PR merged, tests passed, evidence collected)
- Pending count (todos with priority)
- Blockers (R-N risk register reference)

**Owner**: agent

### Weekly Summary

**Trigger**: Weekly cadence (e.g., every Friday)
**Channel**: Chat summary message + optional handoff doc commit
**Format**:
```
## Faz 23 Weekly Summary — YYYY-MM-DD

### Done this week
- PR #N: <title> — sub-faz X.Y, must-have #N
- Risk R-N: closed/mitigated
- Milestone M-N: state change

### In progress
- T-N.M: <task name>, owner, ETA
- Blocker: <description>

### Risks updated
- R-N: status change reason

### Next week priority
- M-N target date approaching
- T-N.M start

### Stakeholder asks
- legal review needed for X
- ops drill scheduled for Y
- user manual action: Z
```

**Owner**: agent (auto-generated from sprint-plan + milestones + risk-register)

### Per-Milestone

**Trigger**: M-N milestone closure or slip
**Channel**: Chat notification + milestone tracker update + handoff doc
**Format**: Detailed evidence + DoD checklist + risk closure log

**Owner**: agent

### Per-Incident

**Trigger**: Production issue detected (Alertmanager firing, browser console error, post-deploy regression)
**Channel**: Immediate chat alert + incident response runbook execution
**Format**:
```
## INCIDENT — YYYY-MM-DD HH:MMZ

**Severity**: critical / high / medium / low
**Affected**: cluster + service + user impact
**Detection**: alert / observation / report
**Initial state**: <pod/metric/log evidence>
**Action taken**: <rollback / mitigation>
**Status**: investigating / mitigated / resolved
**Post-incident**: retrospective scheduled YYYY-MM-DD
```

**Owner**: agent (initial) + ops (escalation if needed)

### Per-Cutover

**Trigger**: Sub-faz prod cutover (e.g., M1 23.9 closure, future M3 23.2 closure)
**Channel**: Pre-cutover plan + cutover live + post-cutover evidence
**Format**: 3-stage:
1. **Pre-cutover** (T-1 day): plan summary + risk review + go/no-go
2. **Cutover live** (T0): apply log + smoke verify + browser console kanıt
3. **Post-cutover** (T+24h, T+72h): observation evidence + rollback decision

**Owner**: agent (pre + cutover) + ops (post-observation)

### Quarterly Review (when applicable)

**Trigger**: Quarterly cadence post-v1 stable
**Channel**: Comprehensive review doc + Codex strategic retrospective
**Format**:
- Roadmap progress vs original 14-18 hafta estimate
- Risk register evolution
- Test strategy adherence
- Stakeholder feedback
- Next quarter planning

**Owner**: agent + Codex strategic consultation

---

## Communication Patterns by Audience

### To User (continuous default audience)

- **Tone**: Türkçe (HARD RULE), kanıt-bazlı, doc reference'larla
- **Detail level**: high — every PR + evidence + risk update visible
- **Approval flow**: AskUserQuestion for irreversible / strategic / multi-tenant decisions
- **Avoid**: jargon dump without context, surprise scope changes, fake-work claims

### To Codex (peer review)

- **Tone**: structured peer review request — context + diff + critique scope
- **Detail level**: high — full PR diff + branch HEAD + previous iter findings
- **Format**: AGREE/PARTIAL/REVISE/RED verdict + specific findings
- **Cadence**: per-PR (HARD RULE cross-AI peer review)

### To Legal (KVKK review)

- **Tone**: formal, requirement traceability
- **Detail level**: high on legal items — KVKK Art reference, scope boundary, PII handling
- **Format**: PR + runbook + evidence package
- **Cadence**: pre-merge for any KVKK-touching code (23.2.B, 23.3 commercial SMS)
- **Authority**: legal can BLOCK merge until reviewed

### To Ops (cluster + Vault + drill)

- **Tone**: operational, runbook-driven
- **Detail level**: actionable steps + rollback path
- **Format**: SSH commands + kubectl one-liners + Slack #ops messages
- **Cadence**: per-cutover + per-drill + per-rotation

---

## Key Messages by Phase

### Pre-Sub-faz Start

"Sub-faz X.Y başlıyor — Tier T-N kapsamında. Tasks T-N.1..N.M, estimation Xh. Risk R-N gates: <list>. Beklenen closure: M-N (date). Codex strategic retrospective kontrolü ile."

### During Sub-faz

"Task T-N.M done — PR #N merged. Codex iter-X AGREE. Cluster apply LIVE. Evidence: <link>. Next: T-N.(M+1)."

### Post-Sub-faz Closure

"Sub-faz X.Y closed — milestone M-N achieved. DoD checklist 🟢 (X/X). Charter marker ⏳ → 🟢. Risk R-N closed. Next critical path: M-(N+1)."

### Risk Materialized

"Risk R-N materialized — <description>. Mitigation activated: <plan>. Impact: <bounded>. Recovery ETA: <date>. No blocking effect on critical path." OR "BLOCKING — sub-faz X.Y deferred until <condition>."

### Approval Needed

"Approval needed: <decision> — Options A/B/C with trade-offs. Preferred: <option> per Codex consensus + risk profile. Awaiting your decision before proceeding."

---

## Anti-Patterns (Avoid)

- **Closure language without evidence**: "Tüm işler tamamlandı" without DoD checklist
- **Improvise naming**: "Step A/B/C" without canonical sub-faz cross-reference
- **Surprise scope expansion**: adding features mid-sprint without milestone update
- **Sandbagged estimates**: padding hours; must reflect Codex iter overhead realistically
- **Burying blockers**: must surface R-N risks immediately in next chat update
- **Single-channel updates**: critical decisions need both chat + doc commit (charter / milestone / risk-register)

---

## Last Update: 2026-05-09 (Session 39)

**Active comms cadence**:
- Continuous (per-PR): ✅ active
- Daily/per-session summary: ✅ active (TodoWrite + chat)
- Weekly summary: 🔴 first one due 2026-05-16
- Per-milestone: 🟡 M1 closure 2026-05-12 will trigger first
- Per-incident: 🟢 protocol defined, no incidents this session
- Per-cutover: 🟢 23.9 cutover 2026-05-08 followed pattern
- Quarterly review: ⏳ post-M7 v1 stable
