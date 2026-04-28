# AC-1 Drill Evidence — `<DRILL_TYPE>` `<DATE>`

> **Template — kopyala, doldur, `docs/faz-21-3-evidence/<YYYY-MM-DD>-ac-1-drill-<drill-type>-<run-id>.md` adıyla kaydet.**
>
> **AC-1 (ADR-0011 §2.2)**: drill execution evidence — operator-driven runbook execution sonrası kanıt belgesi. Codex `019dd409` AC-1 scaffold pattern (DD-3 benzeri operator-loop).
>
> Drill types (currently in scope):
> - `vault-test-dr-rekey` — Vault DR rekey on test cluster (uses `docs/RB-vault-test-dr-rekey.md` from Session 32 PR #202)
> - `vault-prod-dr-inventory` — Vault DR readiness inventory on prod (uses `docs/RB-vault-prod-dr-inventory.md` from Session 32 PR #203)
> - `dr-6-readiness` — DR-6 connectivity check (extends `docs/faz-21-3-evidence/2026-04-28-dr-6-readiness-check.md` pattern)

## Front-matter

**Drill type**: `<vault-test-dr-rekey | vault-prod-dr-inventory | dr-6-readiness | other>`
**Date**: `<UTC ISO date>`
**Cluster**: `<k3d-test on staging-sw | k3d-prod on staging-sw | n/a (vault host)>`
**Run ID**: `<unique drill identifier — e.g., drill-2026-Q2-vault-test-dr>`
**Operator**: `<operator name + role>` (drill execution **operator authority** — ADR-0010 §2.5 + ADR-0011 §2.3 boundary)
**Codex thread**: `<thread-id if applicable>` or `n/a`
**Runbook reference**: `<docs/RB-... markdown file referenced>`

## What this drill proves

(1-2 paragraf) Bu drill execution'ın **canlı** doğruladığı kontrat:
- Hangi DR/AC kapsam ölçümü yapıldı (örn. "RTO ≤4h test verify", "credential rekey clean", "snapshot consistency under load")
- Hangi runbook adımları koşuldu, hangi verdict alındı
- Hangi evidence kaynağı kalıcı kaydedildi (logs, artifacts, screenshots)

## What this drill does NOT cover

- (örn. "production cluster drill ayrı belge — bu test cluster only")
- (örn. "destructive recovery test deferred — this is read-only check")
- (production destructive drill için: dual-clearance approval gerek; user authority + Codex consensus)

## Prereq

- [ ] Operator `kubectl --context <ctx>` erişimi
- [ ] Vault token (operator local shell — ADR-0011 credential-read boundary)
- [ ] Runbook `<docs/RB-...>` Step 1-N gözden geçirildi
- [ ] (Drill specific) e.g., snapshot baseline mevcut, ESO sync test edilebilir, vault unseal keys cached

## Drill execution log

> Her step için: timestamp + komut + beklenen + actual + PASS/FAIL.

### Step 1 — `<short description>`

**Komut**:
```bash
<exact command operator ran>
```

**Beklenen**: `<expected output / state>`

**Actual**:
```text
<paste actual output, redact credentials>
```

**Verdict**: `PASS | FAIL | PARTIAL`

### Step 2 — ...

(repeat for each runbook step)

## Final verdict

**Drill verdict**: `PASS | FAIL | PARTIAL`

| Step | Verdict | Note |
|---|---|---|
| 1 | ✓/✗ | <brief> |
| 2 | ✓/✗ | <brief> |
| ... |  |  |

**Failure modes** (varsa): list each failed step + root cause + remediation
**Limitations** (varsa): cover dışı kalan iş + niye
**Rollback** (yapıldıysa): rollback steps + state recovered

## D35 / DR / AC ladder impact

- (örn. "DR-5 unblocker: PR #202 runbook canlı verify + evidence")
- (örn. "AC-1 first drill execution complete; AC-N next quarterly drill scheduled <date>")

## Operator log

```text
<UTC timestamp> — operator action 1
<UTC timestamp> — observation
<UTC timestamp> — runbook step 2
<UTC timestamp> — verdict captured
```

## Artifacts

- `<runbook .md>` — original runbook used
- `<command outputs / logs>` — anonymized
- `<screenshots / video links>` — operator's secure storage
- `<vault audit log entries>` — if drill touched Vault, audit log evidence

## Boundary declaration (ADR-0011 §2.3)

This drill execution included:
- [ ] credential-read (drill operator read Vault tokens / secrets — local shell only)
- [ ] credential-write (drill operator wrote new secrets / rotated keys)
- [ ] state-mutation (test cluster) — drill mutated test state
- [ ] state-mutation (production) — drill mutated prod state (dual-clearance approval evidenced)
- [ ] boundary-cross (drill touched another repo)
- [ ] none of the above (read-only check, no mutation)

User-approval evidence: `<link to user approval message in chat / PR review>` or `N/A` (if `none of the above`)

## References

- ADR-0011 §2.2 (Audit cadence — drill evidence template requirement)
- ADR-0011 §2.3 (Boundary declaration matrix)
- ADR-0010 §2.5 (Operator/agent authority — drill execution operator-only)
- Codex thread `<thread-id>` (drill scheduling/strategy)
- Originating runbook: `<docs/RB-...>`

Completed: `<UTC ISO timestamp>`
