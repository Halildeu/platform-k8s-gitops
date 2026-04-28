# ADR-0011 Gray-Area Decision Records

> **Index of normative gray-area resolutions per ADR-0011 §1 Context.**
> See playbook: [docs/RB-adr-0011-bg-2-sandbox-blocking-playbook.md](../../RB-adr-0011-bg-2-sandbox-blocking-playbook.md)

## Catalog

| ID | Topic | Class | Sandbox behavior | Decision summary |
|---|---|---|---|---|
| [GA-001](./GA-001-vault-generate-root-container-cli.md) | Vault generate-root via container CLI | `credential-write` | `sandbox-gap` | Agent yasak; container/CLI bypass'ı sonucu değiştirmez |
| [GA-002](./GA-002-eso-approle-reads.md) | ESO AppRole reads | split (`credential-read`/`credential-write`) | `sandbox-gap` (partial) | role_id metadata; secret_id agent için yasak |
| [GA-003](./GA-003-direct-pg-alter-production-shared-schema.md) | Direct PG ALTER on production-shared schema | `state-mutation (production)` veya always-blocked | `blocked-as-expected` | Migration PR + CI + controlled apply pattern |

## How to add a new gray-area

1. Stop session activity in the gray area
2. Codex consensus thread — "Bu işlem agent-actionable mı?"
3. Open PR `chore/adr-0011-ga-NNN-<short-name>`
4. Create `GA-NNN-<short-name>.md` here using existing record format
5. Update this index table
6. Update playbook examples table if applicable
7. Codex AGREE post-impl review

## Decision record format

Each `GA-NNN-*.md` file follows:

```markdown
# GA-NNN — <Topic>

## Class
<credential-read | credential-write | state-mutation (test) | state-mutation (production) | boundary-cross | other>

## Sandbox behavior
<blocked-as-expected | sandbox-gap | over-blocked>

## Decision
<normative agent rule>

## Agent allowed
- <bullet list>

## Agent blocked
- <bullet list>

## User path
- <how to proceed when agent is blocked>

## BG-1 mapping
<which boundary class checkbox + label requirement>

## References
- <ADR-0011 §X.Y>
- <session/PR references>
```

## Authority chain

ADR-0011 §1 → BG-2 playbook (this directory) → BG-1 PR-level enforcement (per-PR boundary declaration gate) → ADR-0010 §2.5 user-approval matrix.
