# D35 Evidence — Per-PR Declaration Template + File Format

> **DR-5 of ADR-0010** (`docs/adr/0010-vault-credential-lifecycle-and-dr.md` §2.3).
> **Codex consensus**: thread `019dd2c9`.
> **References**: ADR-0009 §"D35 Evidence Ladder".

This document gives every PR a deterministic place to declare its relationship to the D35 evidence ladder, plus a template every D35-X evidence file should follow.

## When PRs must declare

- **Always** include the `## D35 ladder declaration` block in PR descriptions if the change touches **any** of:
  - permission-service code or image digest
  - ETL / `etl_worker` / `data_access` schema / `workcube_mikrolink.company`
  - OpenFGA model / store / tuple writer / poller
  - `kustomize/overlays/{test,prod}/kustomization.yaml` permission-service or related
  - Vault `kv/data/platform/permission-service` keys (via DR-3 wrapper)
  - Test smoke gates (`data-access-migrations.yml`, `openfga-fixture-smoke.yml`)
- **Skip** the block only for PRs that are CLEARLY orthogonal (docs-only with no D35 relevance, unrelated workflow port, etc.). When in doubt, declare.

## PR description block (copy this)

```markdown
## D35 ladder declaration

This PR (advances | affects | does NOT touch) the following D35 tier(s):

- [ ] D35-0 — Runtime preflight (regression-detect)
- [ ] D35-1 — Scope anchor prereq (real Workcube row)
- [ ] D35-2 — Scoped grant/revoke E2E (= D35 first evidence)
- [ ] D35-3 — Product path (UI persona)

**If advances**: evidence file path + tier marker line.
**If affects**: 1-2 line explanation (e.g., "schema migration changes the
trigger contract; subsequent D35-2 evidence MUST include re-verification of
validate_scope_ref behavior").
**If does NOT touch**: no annotation needed (omit block).
```

## Evidence file format

Every D35-X evidence file under `docs/faz-21-3-evidence/` must:

1. **Filename pattern**: `<YYYY-MM-DD>-<run-id>-<tier>.md`
   - Examples:
     - `2026-04-28-outbox-isolated-preflight.md` → tier inside file (D35-0)
     - `2026-05-XX-d35-1-scope-anchor-load.md`
     - `2026-05-YY-d35-2-first-canli.md`
     - `2026-05-ZZ-d35-3-ui-persona.md`

2. **First line** must contain the tier marker:
   ```markdown
   # D35-X — <descriptive title>
   ```

3. **Mandatory front-matter block**:

```markdown
**Tier**: D35-0 | D35-1 | D35-2 | D35-3
**Date**: <UTC ISO date>
**Cluster**: k3d-test on staging-sw  (or k3d-prod for prod runs)
**Permission-service image digest**: sha256:...
**Codex thread**: <thread-id> (or "n/a")
**Operator**: <name / role>  (D35-1, D35-2, D35-3 require operator authority)

## What this evidence proves

(1-2 paragraph summary of what's covered AND what's NOT covered. Reference
ADR-0009 §"D35 Evidence Ladder" for tier definitions.)
```

4. **Tier-specific captures** (each tier has a fixed required-capture list):

### D35-0 — Runtime Preflight

Required captures:
- Image digest match (pod imageID == gitops kustomize pin)
- Pod env vars (REPORTS_DB_*, ERP_OPENFGA_ENABLED, image-related)
- Spring Boot Started log line
- HikariPool-1 + HikariPool-2 startup logs
- OutboxPoller scheduler activity (prometheus
  `tasks_scheduled_execution_seconds_count{...OutboxPoller...outcome="SUCCESS"}` > 0)
- V22+V23 schema introspection (idx_scope_outbox_tuple_ordering present)
- reports_db row state (organization seeded, scope/scope_outbox empty)

Optional:
- Caveat block (e.g., shared-cred test patch is in effect — note the
  PR # that introduced the deviation from base contract)

### D35-1 — Scope Anchor Prereq

Required captures:
- Faz 16.2.A `etl_worker` runbook executed
- `workcube_mikrolink.company` row count (>= 1) with at least 1 real
  source_pk shown
- `migration_audit.migration_runs` row visible with mode + status + counts
- Reconcile evidence (rejected_rows = 0)
- `data_access.organization_company` mapping for AÇIK org → real source_pk

### D35-2 — Scoped Grant/Revoke E2E (= D35 first evidence)

Required captures:
- Steps 9.1-9.11 from `docs/openfga-multi-org-rollout.md` ALL passing
- REST POST → 201 + scopeId + outboxId + initial tupleSyncStatus
- PG `data_access.scope` row visible (scope_ref JSON canonical)
- Outbox PENDING row with V23 typed columns populated
- Outbox row reaches PROCESSED within 30s
- OpenFGA /check {"allowed": true} for granted user
- OpenFGA /check {"allowed": false} for non-granted user
- DELETE → 204 + REVOKE outbox row PROCESSED
- Originally-granted user /check now {"allowed": false}
- count(*) FROM scope_outbox WHERE status='FAILED' AND created_at >= now() - 10min == 0

### D35-3 — Product Path

Required captures:
- UI flow screenshot or video (link in evidence file)
- User persona identity (who, what role, what realm)
- UI scope-grant action → backend log correlation
- UI revoke action → backend log correlation
- Browser network log for the relevant scope-grant API calls
- mfe-access version + build info
- Backend log correlation IDs for the actions

5. **Final verdict block**:

```markdown
## Verdict

**Tier verdict**: PASS | FAIL | PARTIAL

**Failure modes** (if any): list each step that failed + reason
**Limitations** (if any): things this evidence doesn't prove
**Next**: what tier(s) come next + dependencies

Completed: <UTC ISO timestamp>
```

## Linking evidence to PRs

When a PR creates an evidence file:
- Reference the PR # in the evidence file's references block
- Reference the evidence file path + tier in the PR description's `D35 ladder declaration` block

When a PR affects D35 prereq's without creating evidence:
- Note the affect-only relationship; downstream evidence PRs will reference back
- DO NOT skip the declaration block — write "affects D35-X" with explanation

## Validation

- File path exists in `docs/faz-21-3-evidence/`
- First line is `# D35-X — ...`
- Tier in front-matter matches first line
- Required captures (per tier) all present (CI gate could enforce — see DR-6+ follow-up)

## Examples

| Evidence file | Tier | Notes |
|---|---|---|
| `docs/faz-21-3-evidence/2026-04-28-outbox-isolated-preflight.md` | D35-0 | Lands first regression-detect baseline; shared-cred caveat block present (subsequently retired by DR-4 SoD remediation) |

(Future evidence files added here as the ladder progresses.)

## References

- ADR-0009 (D35 canlı scoped E2E gate — original contract + ladder section)
- ADR-0010 §2.3 (Codex `019dd2c9` strategic ladder decision)
- `docs/openfga-multi-org-rollout.md` Step 9 (the canonical 11-step sequence executed at D35-2)
