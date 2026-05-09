# Checkpoint Template — Faz 23 Milestone Status

> Bu template her milestone target tarihinde (M1/M2/M3/M4/M5/M6a/M6b/M7/M8/M9) **immediate checkpoint** dosyası oluşturmak için kullanılır. Codex `019e0c28` F5 absorb (weekly summary 2026-05-16'dan önce M1+M2 2026-05-12 için checkpoint şart).

> **Naming**: `YYYY-MM-DD-mN-status.md` (ör. `2026-05-12-m1-m2-status.md`).

---

## Checkpoint — M[N] [Milestone Name] — YYYY-MM-DD HH:MMZ

**Trigger**: Milestone target date veya 7+ gün slip

### Definition of Done — Status

[Per-milestone DoD checklist'ini milestones.md'den kopyala, her satırı 🟢/🟡/🔴 işaretle]

- [ ] DoD item 1 — 🟢/🟡/🔴 evidence path veya pending sebep
- [ ] DoD item 2 — ...
- [ ] DoD item N — ...

### Charter Marker Update

| Sub-Faz | Önceki | Şimdi | Evidence |
|---|:---:|:---:|---|
| 23.X | 🟡 | 🟢 / 🟡 / ⏳ | `path/to/evidence.md` |

### Risk Register Delta

| Risk ID | Önceki Status | Şimdi | Sebep |
|---|:---:|:---:|---|
| R-N | 🟡 Active | 🟢 Mitigated / 🔴 Pending | Closure evidence veya escalation |

### Sprint Plan Task Status

| Task ID | Önceki | Şimdi | Effort actual vs est |
|---|:---:|:---:|---|
| T-N.M | 🔴 | 🟢 | est Xh / actual Yh |

### Slip Detection

- [ ] On track (no slip)
- [ ] Minor slip (≤7 gün) — adjusted target: YYYY-MM-DD
- [ ] Major slip (>7 gün) — Codex strategic retrospective triggered: thread `0190xxxx`
- [ ] Critical slip (>14 gün) — stakeholder notification + scope re-baseline

### Risk Materialized → Issue Transition

[RAID log §I'a yeni issue eklendi mi?]

- I-N: [issue özet] — owner, severity, mitigation in progress

### Stakeholder Notification

- [ ] User notified (chat update)
- [ ] Codex peer review triggered (eğer scope değişimi varsa)
- [ ] Legal notified (KVKK gate ise)
- [ ] Ops notified (drill/cutover gate ise)

### Next Action (Critical Path)

- M[N+1] [next milestone] target: YYYY-MM-DD
- Blocker: [if any]
- Owner: dev / ops / legal / agent / user

### Codex Cross-AI Review

- Thread reference: `019xxxxx`
- Verdict: AGREE / PARTIAL / REVISE / RED
- Iter count: N

### Evidence Links

- Cluster state: `kubectl get pod ...` output
- Smoke endpoint: `curl -s ...` response
- Browser console (HARD RULE deploy verify): screenshot path veya MCP tab snapshot
- Test execution log: pytest/Maven output reference

### Last Update

YYYY-MM-DD HH:MMZ
