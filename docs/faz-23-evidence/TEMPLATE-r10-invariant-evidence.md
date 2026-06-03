# R10 Invariant Evidence — TEMPLATE

> **Copy this template to `docs/faz-23-evidence/YYYY-MM-DD-r10-invariant-evidence.md`** when running pre-migration audit + R10 invariant smoke.
>
> Authority: Faz 23 M8 PR-3 A (Codex `019e8c24` order D→B→A→C, multi-PR sequenced). Scope: `docs/faz-21/charter.md` §4.3 acceptance evidence + §5.1 Faz 21.0 sub-faz DoD.

---

## Context

- Generated UTC: `<YYYY-MM-DDTHH:MM:SSZ>`
- PG snapshot host (redacted): `<snapshot-host>`
- PG snapshot source: `<prod-restore-date | live-replica | other>`
- Workstation context: `<operator + workstation hostname redacted>`
- Predecessor evidence: `<link-to-prior-snapshot-evidence-if-applicable>`

## Verdict (composite)

| Script | Verdict | Exit |
|---|---|---|
| `pre-migration-audit.sh` | `CLEAN / INVARIANT_VIOLATION / OBSERVATION_INSUFFICIENT` | `0/1/2` |
| `r10-invariant-checks.sh` | `MOSTLY_CLEAN_INV4_MANUAL / INVARIANT_VIOLATION / ADVISORY_INVESTIGATION / MIXED` | `0/1/2` |

## Inv-1 (tenant context)

- Request missing `org_id` over 24h: `<value>`
- Advisory threshold: `<value>`
- Status: `CLEAN / ADVISORY_OVER_THRESHOLD / ADVISORY_ABSENT`
- Notes: `<operator investigation if status != CLEAN>`

## Inv-2 (persistence)

Per-table NULL `org_id` count:

| Table | NULL count |
|---|---|
| notify_intent | `<value>` |
| notify_dispatch | `<value>` |
| notify_delivery | `<value>` |
| notify_outbox | `<value>` |
| notify_audit | `<value>` |
| endpoint_device | `<value>` |
| endpoint_software_inventory | `<value>` |
| endpoint_outdated_software | `<value>` |

- Total NULL rows: `<value>`
- Status: `CLEAN / VIOLATION`
- Notes: `<per-table backfill plan if VIOLATION>`

## Inv-3 (side-effect isolation)

- Callback correlation orphan count (`provider_message_id NOT NULL AND org_id IS NULL` in notify_delivery): `<value>`
- Provider distinct count: `<value>`
- Status: `CLEAN / VIOLATION / ADVISORY_ABSENT`
- Notes: `<callback handler review notes; cross-check Vault path canonical>`

## Inv-4 (AI boundary) — manual cross-check

| Checklist item | Status | Notes |
|---|---|---|
| `platform-ai` vector index keys carry tenant partition prefix | `<verified / TODO / NOT_APPLICABLE>` | `<repo + path reference>` |
| Prompt context selector applies tenant filter before retrieval | `<verified / TODO / NOT_APPLICABLE>` | `<path reference>` |
| Embedding cache key includes `org_id` | `<verified / TODO / NOT_APPLICABLE>` | `<path reference>` |
| Inference audit emits `tenant=<org_id>` label | `<verified / TODO / NOT_APPLICABLE>` | `<path reference>` |

> Inv-4 is by design **manual cross-check** — the audit harness emits the checklist but cannot probe `platform-ai` repo from this gitops surface. Operator MUST close this checklist before claiming Faz 21.0 DoD.

## Anti-pattern guards (verified)

- [ ] Audit ran READ-ONLY on production
- [ ] No raw tenant/PII in this evidence document
- [ ] Workstation `date -u` + PG `now()` both recorded
- [ ] Snapshot refresh confirmed for this run
- [ ] Charter §4.1 + §4.3 reviewed before commit

## References

- [docs/faz-21/charter.md §4](../faz-21/charter.md) — R10 invariant set + forbidden patterns + acceptance scope
- [docs/adr/0032-faz-21-tenant-model.md](../adr/0032-faz-21-tenant-model.md) — canonical tenant model v1
- [docs/operations/RUNBOOKS/RB-faz-21-pre-migration-audit.md](../operations/RUNBOOKS/RB-faz-21-pre-migration-audit.md) — operator entry point
- [Faz 23 M8 board #760](https://github.com/Halildeu/platform-k8s-gitops/issues/760)
- Codex thread audit: `019e8c24` (sprint plan) + `019e8c3e` (charter strategic)
