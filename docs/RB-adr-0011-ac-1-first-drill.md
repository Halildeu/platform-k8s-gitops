# RB ADR-0011 AC-1 — First Drill Execution Runbook

> **Tetikleyici**: ADR-0011 §2.2 audit cadence — first quarterly drill execution.
> **Authority**: **Operator-driven** (Codex `019dd409` AC-1 boundary). Agent scaffold + template; operator runs drill + commits evidence.
> **Codex consensus**: thread `019dd409` AC-1 PARTIAL/AGREE (scaffold önce, drill execution sonra).

## Amaç

Session 32'de eklenen Vault DR runbook'ları (PR #202 test rekey + PR #203 prod inventory) ile DR-3..DR-9 contract'ı **kağıt üstünde** mevcut; canlı verify edilmedi. AC-1 first drill bu boşluğu kapatır:

- DR-5 (test vault DR rekey) → operator runs PR #202 runbook + AC-1 evidence template ile capture
- DR-9 (prod read-only inventory) → operator runs PR #203 runbook + AC-1 evidence template ile capture
- D35-2-full canlı verify (sınırlı — already PR #225 done — example pattern reference)

İlk drill quarter (Q2 2026) için scope: **test vault DR rekey** (PR #202 wrapping). Production drill (DR-8/DR-9) ayrı dual-clearance + user-approval gerekli.

## Prereq

- [ ] PR #202 (`docs/RB-vault-test-dr-rekey.md`) gözden geçirildi
- [ ] AC-1 evidence template (`docs/faz-21-3-evidence/ac-1-drill-evidence-template.md`) açık
- [ ] Vault test admin token (operator local shell — ADR-0011 §2.3 credential-read boundary; agent transcript'inde literal görmez)
- [ ] Drill scheduling karar verildi (Codex consensus + user approval — quarterly cron veya ad-hoc)

## Drill type sırası (önerilen)

### Phase 1 — `vault-test-dr-rekey` (DR-5 unblocker)

**Authority**: operator only. User-approval per ADR-0010 §2.5 even on test vault (Codex 019dd333 retrospective: "auto-mode sandbox correctly enforced ADR-0010 §2.5 user-approval gate on Vault credential operations even on test vault").

**Steps** (PR #202 runbook from):

1. Operator runs `docs/RB-vault-test-dr-rekey.md` Step 1-N
2. Each step output kaydedilir (clipboard, log file, screenshot)
3. Drill execution **timestamp + verdict** AC-1 template'ine yazılır

**Evidence file**: `docs/faz-21-3-evidence/<YYYY-MM-DD>-ac-1-drill-vault-test-dr-rekey-<run-id>.md`

**Outputs to capture**:
- Vault status pre-rekey (`vault status`)
- Rekey operation logs (audit log entries)
- Vault status post-rekey (new keys + threshold)
- ESO force-sync verification (downstream services pickup)

### Phase 2 — `vault-prod-dr-inventory` (DR-9 unblocker, **deferred**)

**Authority**: operator + user **dual-clearance** (CLAUDE.md HARD RULE #6 prod cutover bekliyor).
**Status**: defer to Q3 veya production cutover decision sonrası.

**Steps**: PR #203 runbook + AC-1 evidence template adapt.

### Phase 3 — `dr-6-readiness` (refresh DR-6 evidence)

**Authority**: operator only.
**Status**: PR #211 etl-worker env multi-prefix + DR-6 readiness evidence (`docs/faz-21-3-evidence/2026-04-28-dr-6-readiness-check.md`) zaten Session 32'de yapıldı. AC-1 quarterly cadence için her 3 ay'da bir tekrar (re-verify connectivity).

## AC-1 evidence file lifecycle

1. Operator drill koşar → PASS/FAIL veridkt
2. Operator AC-1 evidence template'i doldurur (`docs/faz-21-3-evidence/<YYYY-MM-DD>-ac-1-drill-<type>-<run-id>.md`)
3. Operator credential redact eder (Vault token, password literal'ları transcript'te olmamalı)
4. Operator PR aç (`ops/ac-1-drill-<type>-<date>` branch); CI green; merge
5. ADR-0011 audit cadence kayıtları sürdürülür: bir sonraki drill scheduling

## CI validation

AC-1 evidence file'ları için minimum CI gate (post-merge governance — BG-1'in bir parçası olabilir):

- File path pattern: `docs/faz-21-3-evidence/<date>-ac-1-drill-*.md`
- Front-matter required fields (Drill type, Date, Operator, Verdict)
- Boundary declaration block (ADR-0011 §2.3) populated

## Boundary declaration (ADR-0011 §2.3)

AC-1 drill execution PR'larında tipik:

```markdown
- [x] credential-read (operator drill sırasında Vault token/key okur — local shell)
- [x] state-mutation (test cluster) (rekey operation test vault state'i değiştirir)
- [ ] credential-write (rekey new keys threshold üretir; "write" yerine "rotate" — sınıf tartışmaya açık)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] none of the above
```

User-approval evidence: link to user message authorizing drill execution.

## Cleanup

Drill sonrası:
- Vault audit log entries archive
- Drill credential cache (varsa) güvenli sil (operator local shell)
- Evidence file final formatted + commit

## Roadmap

- AC-1 first drill (Q2 2026): vault-test-dr-rekey (this scaffold target)
- AC-2 quarterly cadence: ardarda drill executions; runbook adapt
- AC-N: incident response drill, ETL refresh drill, schema-service snapshot validation drill

## References

- ADR-0011 §2.2 (Audit cadence — drill evidence template requirement)
- ADR-0011 §2.3 (Boundary declaration)
- ADR-0010 §2.5 (Operator/agent authority — drill execution boundary)
- DR runbooks (PR #202 + #203):
  - `docs/RB-vault-test-dr-rekey.md`
  - `docs/RB-vault-prod-dr-inventory.md`
- DR-6 readiness pattern: `docs/faz-21-3-evidence/2026-04-28-dr-6-readiness-check.md`
- AC-1 evidence template: `docs/faz-21-3-evidence/ac-1-drill-evidence-template.md`
- Codex thread `019dd409` AC-1 scaffold strategy
- Codex thread `019dd333` Session 32 retrospective (drill discipline)
