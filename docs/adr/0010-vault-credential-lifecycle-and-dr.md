# ADR-0010 — Vault Credential Lifecycle, DR Boundary, and Operator/Agent Authority

**Status**: Accepted — 2026-04-28
**Supersedes**: D-009 (initial Vault + ESO setup; this ADR refines the secret-write + DR axis)
**Codex consensus**: thread `019dd2c9` (xhigh effort architecture review)
**Related**: ADR-0002 (single-host dual-cluster), ADR-0009 (D35 canlı scoped E2E gate)
**Drives**: PR sequence DR-1 → DR-9 (this PR is DR-1)

---

## 1. Context

The platform's `runtime desired-state` axis is GitOps-disciplined: kustomize overlays, ESO, ArgoCD-style sync semantics. The `privileged bootstrap / secret write / recovery / real-data anchor` axis, however, is still anchored on individual operator moments:

- **Vault root token regen** is required to write a single new key under `kv/platform/<service>`.
- **Vault DR keyset dump** is one-shot; rekey events do not auto-update `/home/halil/platform/state/vault/vault-unseal-key-*` files. As of 2026-04-28, the test vault keyset is partially stale (KEY1 valid, KEY2 + KEY3 fail decrypt) → DR is not currently feasible without external admin intervention.
- **D35 first evidence** (ADR-0009) requires real Workcube ETL data (`workcube_mikrolink.company.source_pk`); without ETL load, no canlı evidence is possible.
- **SoD remediation** (Faz 21.3 PR #194) lands the `permission_reports_writer` Postgres role, but populating the dedicated Vault credentials still requires root token regen → blocked by the stale keyset.

These three blockers are not independent. They converge on the same systemic cause:

> **Long-term root cause**: critical-path operations on the privileged side of the platform (Vault credential write, DR recoverability, Workcube data anchor) are not contracts — they are ad-hoc operator actions reproducible only when a specific human remembers the exact sequence at the exact moment. This breaks the GitOps invariant for the privileged axis.

ADR-0010 captures the long-term architecture for restoring deterministic contracts to this axis.

## 2. Decision

We adopt a **layered credential lifecycle** + **drill-driven DR contract** + **explicit operator/agent authority matrix**:

### 2.1 Vault credential lifecycle (Codex `019dd2c9` recommendation **A + Q/R**)

- **`eso-runtime`** AppRole stays read-only on `kv/data/platform/*`. Runtime services consume secrets via this role. Read-only is enforced by policy.
- **`platform-bootstrap-writer`** AppRole (NEW) handles all secret-write operations (initial population, rotation, dedicated-role onboarding). Capabilities scoped: `create`, `update`, `read` on `kv/data/platform/<service>` only. Explicit denials: `delete`, `sudo`, `sys/*`, auth mount admin, policy write, root-equivalent paths.
- **Root token** is reserved for Vault admin operations only: init, rekey, auth mount, policy write, audit enable, snapshot restore. App credential populate **MUST NOT** require root token from this point onward.
- **Wrapper convention** (Codex `019dd2c9` recommendation **R**): a `platform-ops vault-patch <service> <field-set>` wrapper / runbook layer above the bootstrap-writer AppRole. Responsibilities:
  - `capabilities-self` check before write (fail-fast)
  - KV v2 merge/patch (preserve existing keys)
  - Stdout sanitization (no plaintext credential leakage)
  - Audit metadata + correlation ID
  - Token environment cleanup on exit
- **SecretID lifecycle**: short-lived (TTL 30-60 min), low `secret_id_num_uses`, separate roles for prod vs test, **never committed to Git**.

### 2.2 DR contract (Codex `019dd2c9` recommendation **C**)

- **Recovery bundle** structure (versioned + drilled):
  - Raft snapshot
  - Unseal/recovery shares escrow status (current keyset checksum, off-host copy provenance)
  - Auth mounts + policies + AppRole role-id inventory
  - KV path inventory + last-modified timestamps
  - Drill evidence (date, outcome, rollback verification)
- **Drill cadence**: monthly for the first two months after this ADR lands, quarterly thereafter.
- **Drill scope**: synthetic seal+unseal + root-regen attempt + token revoke + key checksum verify. NO production secret modification during drill.
- **Drift detection**: drill failure → P1 incident, blocker on prod secret writes until resolved.
- **Cross-cluster scope**: separate DR contracts for test and prod vault. Test verification does NOT imply prod readiness.

### 2.3 D35 evidence ladder (Codex `019dd2c9` recommendation **X + Y**)

ADR-0009 D35 bar **is NOT downgraded**. D35 stays "canlı scoped E2E with real source_pk". Below it sits a ladder of stratified evidence:

| Tier | Name | Captures | Synthetic data tolerance |
|---|---|---|---|
| **D35-0** | Runtime preflight | Image digest, env vars, HikariPool startup, outbox poller scheduler, schema present | None (live cluster only) |
| **D35-1** | Scope anchor prereq | Real Workcube COMPANY row loaded into `workcube_mikrolink.company` via `etl_worker`; reconcile + audit row produced | None — must be real Workcube data |
| **D35-2** | Scoped grant/revoke E2E | ADR-0009 Step 9.4-9.11 with real `source_pk`; outbox PROCESSED + OpenFGA allow→deny chain | None |
| **D35-3** | Product path | UI panel + real user persona; covers product behavior beyond REST-only | None — real user identity context |

**D35-2 = "D35 first evidence"** per ADR-0009. The PR #192 outbox preflight is **D35-0**, not D35.

**Stub data on canlı `workcube_mikrolink.company` is forbidden** (Kural #9 + 2026-04-26 user mandate). Stubs may exist only in ephemeral CI fixtures with the explicit `D29-integration-smoke` tag.

### 2.4 Scope Anchor ETL (Codex `019dd2c9` recommendation **Y**)

A NEW narrow profile alongside the deferred Faz 16.2.P (parametric ETL):

- **Faz 16.2.A — Scope Anchor Load** (NEW phase, separate from 16.2.P)
- Scope: minimum 1 real Workcube `COMPANY` row → `workcube_mikrolink.company`. Subsequent phases extend to `PRO_PROJECTS`, `BRANCH`, `DEPARTMENT` only when a corresponding D35 scope_kind needs evidence.
- Implementation: existing `etl_worker` with a tightened profile (single table + small batch + audit-mandatory + reconcile-mandatory). NOT a new ETL stack.
- `schema-service` `/api/v1/schema/snapshot` is NOT a row-mover; it is for shape verification only.
- Output contract: `migration_audit.migration_runs` row, `loaded_rows >= 1`, `rejected_rows = 0`, `workcube_mikrolink.company.source_pk` example, `data_access.organization_company` mapping evidence.

### 2.5 Operator/Agent authority matrix

Codex `019dd2c9` resolves the gray area in Kural #7 + #9.

**User approval REQUIRED for**:
- Prod Vault rekey, seal/unseal drill, restart, root token generate, admin token usage
- Test Vault re-init/reseed (any operation that mutates current Vault state)
- Credential sharing or new credential issuance into Git/agent context
- External secret manager migrations (cloud KMS, AWS Secrets Manager, etc.)
- D35 semantic adjustments (e.g., re-tagging or downgrading)
- First canlı Workcube ETL row movement (existing runbook policy)

**Codex consensus SUFFICIENT for** (no user re-approval):
- ADR drafts (this ADR, future related ADRs)
- Vault policy HCL files
- Runbook documents
- Evidence taxonomy + schemas
- Wrapper script designs
- Read-only Vault inventory + `capabilities-self` verification on test
- Bootstrap-writer **test policy** application (test environment only) + negative capability tests
- D35 ladder documentation
- Scope Anchor ETL **code/runbook** preparation (the canlı run itself is operator-gated above)

## 3. Consequences

### Positive

- Root token leaves the app-secret-populate hot path; Vault admin operations become break-glass-only.
- Stale keyset detected early via drill, not via incident.
- D35 evidence stratified honestly: reviewers know exactly what was proven.
- SoD remediation no longer hits the same root-regeneration wall.
- Faz 16.2.P deferral is preserved; Faz 16.2.A is a strict subset narrowed to D35 prereq.

### Negative / Trade-offs

- `platform-bootstrap-writer` is a new privileged surface. Mitigated by: TTL constraint, path allowlist, `delete` denial, wrapper layer, audit log requirements, prod/test role separation.
- Scope Anchor ETL adds a small narrow phase to the Faz 16 family. Mitigated by: explicit naming as "anchor" (NOT parametric), scope-bounded entry criteria.
- Self-hosted Vault operational burden does not vanish; it becomes manageable + drillable.
- Evidence taxonomy adds review cognitive load. Mitigated by: every PR description must declare which D35 tier(s) it advances or affects.

### What was rejected

- **Codex `019dd2c9` recommendation B** (sealed-secrets / SOPS as Vault state SoT): inverts D9/Vault SSOT decision; controller private key DR becomes a new root-of-trust problem.
- **Codex `019dd2c9` recommendation D** (external secrets manager, e.g., AWS Secrets Manager): too large a yön change for current 6-month horizon; introduces cloud IAM dependency. May be revisited if RPO/RTO tightens.
- **D35 downgrade to "integration smoke"**: violates ADR-0009 + Kural #9. D35 stays as defined.

## 4. PR sequence (drives this ADR forward)

| # | Name | Scope | User-approval? |
|---|---|---|---|
| **DR-1** | this PR | ADR-0010 + current-state DR drift note + bootstrap-writer skeleton | No (Codex consensus) |
| DR-2 | Vault policy split | `bootstrap/vault-policies/common/bootstrap-writer.hcl` (full policy) + apply runbook + capabilities-self test scaffold | No (test-only) |
| DR-3 | platform-ops wrapper | KV v2 patch wrapper script (no root token) + integration with bootstrap-writer | No (script only, not run) |
| DR-4 | SoD unblock test | Apply bootstrap-writer to test Vault, run `reports_db_*` populate, capture D35-0' evidence with caveat removed | **YES** — test Vault state mutation |
| DR-5 | D35 ladder | ADR-0009 transition map + D35-0/1/2/3 evidence taxonomy + per-PR declaration template | No (docs) |
| DR-6 | Scope anchor ETL | `etl_worker` narrow profile + runbook for Faz 16.2.A | No (code only) |
| DR-7 | D35-2 first real | Step 9.4-9.11 with real `source_pk` on test cluster | **YES** — first canlı Workcube row |
| DR-8 | Prod prep | Prod Vault DR inventory + recovery bundle + drill evidence | **YES** — prod read-only verify only |
| DR-9 | Prod promotion gate | Bootstrap-writer prod policy + per-service population path | **YES** — prod write/rotation |

## 5. Verification

This ADR's correctness is verified by:
- Each PR in the sequence cites this ADR
- D35 evidence files declare their tier (D35-0/1/2/3) per the matrix in §2.3
- Vault drill cadence cron present in repo (`docs/RB-vault-ops-host-cron.md` extension)
- ESO runtime role's `capabilities-self` output unchanged (read-only invariant preserved)
- Prod Vault state is never modified without §2.5 user-approval criteria met

## 6. References

- ADR-0002 (single-host dual-cluster — defines stateful tier in compose)
- ADR-0009 (D35 canlı scoped E2E — D35 contract this ADR ladders below)
- D-009 (initial Vault + ESO setup, this ADR refines)
- Codex thread `019dd2c9` (xhigh effort architecture review, this ADR's primary input)
- Codex thread `019dd2af` (per-grant SoD review for `permission_reports_writer`)
- PR #192 evidence `docs/faz-21-3-evidence/2026-04-28-outbox-isolated-preflight.md` (= D35-0 example)
- 2026-04-26 user mandate ("Workcube MSSQL kaynak şeması her zaman schema-service üzerinden alınır. Agent sentetik tablo/kolon/FK üretmemeli")
- Kural #7 (SSH+sudo+kubectl authority), Kural #8 (continuous + Codex authority), Kural #9 (no fake/cosmetic work)
