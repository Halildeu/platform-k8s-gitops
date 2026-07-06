# RB-faz-21-pre-migration-audit

**Faz 23 M8 PR-3 A operator runbook — Faz 21.0 pre-migration audit + R10 4-invariant smoke harness.**

> Canonical scope authority: [docs/faz-21/charter.md](../../faz-21/charter.md) §4.3 acceptance evidence + ADR-0032 §4.2 migration gates.
> Codex strategic verdict: thread `019e8c24` plan-time AGREE order D→B→A→C (PR-3 A = third in sprint).
> Sister PR: PR-4 C will wrap this runbook + scripts under a single operator entry point (Codex order C).

---

## 1. Bağlam

Faz 21 (multi-tenant migration) sub-faz 21.0 = "Pre-Migration Audit". DoD (charter §5.1):

- Audit script produces evidence on prod-shaped snapshot
- 4 R10 invariants tested green (`r10-invariant-checks.sh` verdict `MOSTLY_CLEAN_INV4_VERIFIED` only — requires `--inv4-verified` flag after operator manual cross-check)
- Orphan/mixed row count == 0 on snapshot

This runbook is the operator entry point. Two scripts (canonical verdicts:
`MOSTLY_CLEAN_INV4_VERIFIED` / `MANUAL_PENDING` / `INVARIANT_VIOLATION` /
`ADVISORY_INVESTIGATION` / `OBSERVATION_INSUFFICIENT`):

- `docs/scripts/faz-21/pre-migration-audit.sh` — READ-ONLY PG snapshot audit; emits canonical JSON predicate file
- `docs/scripts/faz-21/r10-invariant-checks.sh` — wraps the audit JSON + rolls per-invariant verdict + composite (`--inv4-verified` flag required for `MOSTLY_CLEAN_INV4_VERIFIED` exit 0)

Plus three anti-pattern guards (Codex `019e8c24` + `019e8c3e` enforced):

1. **READ-ONLY** — no UPDATE/INSERT/DELETE on production
2. **No raw tenant/PII in evidence** — counts + sample IDs only; redacted
3. **No backdated evidence** — both PG `now()` + workstation clock recorded in JSON

---

## 2. Pre-execution checklist

- [ ] PG snapshot accessible (read-only PG role with SELECT-only grants)
- [ ] Snapshot is prod-shaped (`platform` schema, recent restore)
- [ ] `jq`, `bash`, `psql`, `awk` available
- [ ] Password file readable (`chmod 0400`)
- [ ] Output directory writable
- [ ] Charter + ADR-0032 reviewed (§4.1, §4.3)

> **Anti-pattern**: don't run on **live production** with write privileges. Use a snapshot restore in an isolated environment. If snapshot unavailable, use read-only PG role with explicit `GRANT SELECT ON ALL TABLES IN SCHEMA platform TO audit_ro` only.

---

## 3. Run

### 3.1 Single-command wrapper (Codex order C — PR-4 C entry point)

The recommended operator entry point is `audit-and-check.sh`, which
runs both PR-3 A scripts in sequence and emits a summary JSON:

```
chmod 0400 ~/.faz21-audit.pw  # MANDATORY — pre-migration-audit.sh rejects other modes

# Step 1 — initial audit + checks (Inv-4 NOT verified yet)
./docs/scripts/faz-21/audit-and-check.sh \
  --pg-host 127.0.0.1 \
  --pg-port 15432 \
  --pg-user audit_ro \
  --pg-database platform \
  --pg-password-file ~/.faz21-audit.pw \
  --schema-prefix notify,endpoint_admin_service \
  --out-dir /tmp/faz-21

# Operator performs Inv-4 manual cross-check against platform-ai repo (§4.4)
# ...

# Step 2 — re-run with --inv4-verified flag
./docs/scripts/faz-21/audit-and-check.sh \
  --pg-host 127.0.0.1 \
  --pg-port 15432 \
  --pg-user audit_ro \
  --pg-database platform \
  --pg-password-file ~/.faz21-audit.pw \
  --schema-prefix notify,endpoint_admin_service \
  --out-dir /tmp/faz-21 \
  --inv4-verified \
  --inv4-evidence ~/inv4-checklist.md
```

The wrapper produces three artifacts under `--out-dir`:
- `pre-migration-audit.json` — predicate evidence (schema v2)
- `r10-invariant-checks.json` — composite invariant verdict (schema v2)
- `summary.json` — combined snapshot with both verdicts + composite

### 3.2 Step-by-step (direct invocation, advanced)

If finer control is needed, the two underlying scripts can be invoked
directly:

```
./docs/scripts/faz-21/pre-migration-audit.sh \
  --pg-host 127.0.0.1 \
  --pg-port 15432 \
  --pg-user audit_ro \
  --pg-password-file ~/.faz21-audit.pw \
  --pg-database platform \
  --schema-prefix notify,endpoint_admin_service,public \
  --out /tmp/faz-21-audit.json

# After completing Inv-4 manual cross-check (see §4.4):
./docs/scripts/faz-21/r10-invariant-checks.sh \
  --audit-json /tmp/faz-21-audit.json \
  --inv4-evidence "<path-to-platform-ai-checklist-evidence.md>" \
  --inv4-verified \
  --out /tmp/faz-21-r10-checks.json
```

Exit codes:

| Script | Exit | Meaning |
|---|---|---|
| pre-migration-audit.sh | 0 | All discoverable invariants CLEAN |
| pre-migration-audit.sh | 1 | INVARIANT_VIOLATION |
| pre-migration-audit.sh | 2 | OBSERVATION_INSUFFICIENT (PG unreachable, schemas missing, password file mode invalid, jq/psql/awk missing) |
| r10-invariant-checks.sh | 0 | MOSTLY_CLEAN_INV4_VERIFIED (Inv-1/2/3 CLEAN + Inv-4 `--inv4-verified` flag present) |
| r10-invariant-checks.sh | 1 | INVARIANT_VIOLATION or ADVISORY_INVESTIGATION |
| r10-invariant-checks.sh | 2 | MANUAL_PENDING (Inv-4 not verified) or OBSERVATION_INSUFFICIENT |

> **Codex iter-1 P0/inv4Gate absorb**: `r10-invariant-checks.sh` exit 0 ONLY when `--inv4-verified` is explicitly passed. Without it, verdict is `MANUAL_PENDING` (exit 2) even if Inv-1/2/3 are CLEAN. Prevents operator/automation from claiming DoD met while Inv-4 AI boundary checklist remains open.

---

## 4. Verdict interpretation

### 4.1 `MOSTLY_CLEAN_INV4_VERIFIED` (exit 0) — ONLY with `--inv4-verified`

Inv-1 (request context), Inv-2 (persistence), Inv-3 (side-effect isolation) green AND operator explicitly passed `--inv4-verified` flag to `r10-invariant-checks.sh`. The flag attests the operator has performed the Inv-4 manual cross-check against `platform-ai` repo (vector index keys, prompt context selector, embedding cache, inference audit label).

Optional: pass `--inv4-evidence <path-to-checklist.md>` to embed the manual cross-check evidence reference in the output JSON.

Next: commit evidence + advance to Faz 21.1.

### 4.1b `MANUAL_PENDING` (exit 2)

Inv-1/2/3 may be CLEAN but `--inv4-verified` flag NOT passed. Operator must perform the Inv-4 manual cross-check and re-run with `--inv4-verified`. Anti-pattern guard (Codex iter-1 P0): operator/automation MUST NOT claim DoD met without explicit Inv-4 attestation.

### 4.2 `INVARIANT_VIOLATION` (exit 1)

One or more invariants failed on snapshot:

- **Inv-2 violation** = `total_null_org_id_rows > 0` — pre-migration backfill required; identify orphan rows + author per-table backfill SQL.
- **Inv-3 violation** = `callback_correlation_orphan_count > 0` — callback handler not paired with `org_id`; backend code fix required (charter §4.1 Inv-3 forbidden pattern: `WHERE provider_message_id = ?` without tenant predicate).

Next: open issue + backend PR; re-run audit after fix.

### 4.3 `ADVISORY_INVESTIGATION` (exit 1)

Inv-1 advisory threshold exceeded (request log entries missing `org_id` over sample window). Operator investigates AuthN/AuthZ filter gap; may be acceptable for legacy or operator paths, but document explicitly.

### 4.4 `OBSERVATION_INSUFFICIENT` (exit 2)

PG unreachable / schema missing / audit JSON unreadable. Fix observation surface before drawing any conclusion.

---

## 5. Evidence commit

After CLEAN verdict, copy the JSON output to canonical location + commit:

```
docs/faz-23-evidence/$(date -u +%Y-%m-%d)-r10-invariant-evidence.md
```

Use the template `docs/faz-23-evidence/TEMPLATE-r10-invariant-evidence.md` (sister artifact in this PR).

Required evidence content:
- PG snapshot context (date, host redacted, restore source)
- Verdict + composite predicate values
- Inv-4 manual cross-check completion notes
- Anti-pattern guard checklist
- Charter §4.1 + §4.3 reference link

---

## 6. Failure-mode triage

| Symptom | Likely cause | Remediation |
|---|---|---|
| PG probe failed | Wrong host/port/credentials; network policy block | Verify `psql -c "SELECT 1"` manually; restore snapshot to test env |
| Inv-2 violation on `notify_outbox` | Backfill not applied; service insert without `org_id` | Service code review (DTO mapper); per-tenant backfill SQL |
| Inv-3 callback violation | Webhook handler ignoring tenant context | Backend PR; charter forbidden pattern enforcement test |
| Inv-1 advisory over threshold | Legacy AuthN bypass / operator path | Operator audit + AuthN filter review |
| Audit JSON empty predicates | Schema name mismatch (notify_* tables in different schema) | Verify schema in `--pg-database` flag; multi-schema run separately |

---

## 7. Anti-pattern reminders (KALICI)

| Yapma | Sebep |
|---|---|
| Run against live production with write privileges | Audit is READ-ONLY; charter §4 + anti-pattern guard #1 |
| Skip Inv-4 manual cross-check and claim "MOSTLY_CLEAN" alone | Inv-4 is a real invariant; AI boundary leak is a real attack surface (charter §4.1) |
| Backdate evidence timestamp | Anti-pattern guard #3; PG time + workstation time both recorded |
| Paste raw tenant identifiers / PII in evidence | Anti-pattern guard #2; counts + sample IDs only, redaction enforced |
| Auto-advance to Faz 21.1 without acceptance | Sub-faz DoD must close (charter §5.1) |
| Re-run audit on same snapshot without snapshot refresh | Stale verdict; refresh snapshot before each run |
| Use `--admin` or service account with INSERT/UPDATE on prod | Anti-pattern; READ-ONLY guard |

---

## 8. Bağlantı

- Plan: `docs/faz-21/charter.md` §4.3 + §5.1 (canonical scope + DoD)
- Sister doc: `docs/adr/0032-faz-21-tenant-model.md` (canonical decisions)
- Sister script: `docs/scripts/faz-21/pre-migration-audit.sh` + `r10-invariant-checks.sh`
- Predecessor: M7 30-day stable observation harness (Faz 23 M8 PR-1 D MERGED PR #1234)
- Charter PR: Faz 23 M8 PR-2 B MERGED PR #1235
- Codex thread audit: `019e8c24` plan-time AGREE order D→B→A→C; `019e8c3e` charter strategic GO + iter-2 AGREE
- Next: PR-4 C will wrap this runbook + scripts under operator-safe one-command entry
