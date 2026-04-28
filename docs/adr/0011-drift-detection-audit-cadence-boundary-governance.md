# ADR-0011 — Plan-Time Drift Detection + Audit Cadence + Agent/Operator Boundary Governance

**Status**: Accepted — 2026-04-28
**Codex consensus**: thread `019dd3bd` (xhigh effort retrospective + ADR-0011 candidate review)
**Related**: ADR-0010 (Vault Credential Lifecycle + DR + Operator/Agent Authority — this ADR is the second governance layer on top), ADR-0009 (D35 ladder), ADR-0008 (multi-org explicit-scope)
**Drives**: PR sequence DD-1 → DD-N (drift detection) + AC-1 → AC-N (audit cadence) + BG-1 → BG-N (boundary governance)

---

## 1. Context

Session 32 closed with **31 PRs landed** (#194-#218) + full D35 ladder closure through D35-2 ("D35 first canlı evidence" per ADR-0009). Across this session, **4 separate drift events** were discovered during live-load testing rather than at plan-time review:

1. **V19/V20/V21 anchor table drift** (Workcube `COMPANY` 80,246-row directory used as anchor instead of `OUR_COMPANY` 42-row tenant boundary). Codex `019dd34e` retrospective: "planning gap; source schema convention not cross-referenced at plan-time."
2. **V25 jsonb extraction format drift** vs ETL `make_source_pk` canonical JSON (`["1"]` vs extracted `"1"`). Discovered DURING D35-1 live INSERT after V25 applied.
3. **etl-worker env prefix drift** (backend.env `REPORT_MSSQL_*` vs etl-worker config.py `MSSQL_*`). Discovered during DR-6 readiness check; blocked Step 2 until PR #211 fixed.
4. **Dockerfile signing convention drift** (Microsoft msodbcsql18 keyring `[signed-by=...]` apt format change for Debian 12 sqv-based verification). Discovered during DR-6 image build.

These discoveries cost **~6 hot-fix iterations** across the session block (V25 alone needed 3 iter pre-CI-green). Codex `019dd333` retrospective explicitly flagged: "live-governance + CI self-hosting → 10-12 PR sonrası state refresh ve retrospective checkpoint daha sağlıklı."

Beyond drift, the session also evidenced the operator/agent authority pattern Live-tested:

- **Sandbox correctly blocked** 3 categories: Vault state-file reads (even on test), hot-patch DB function bypassing migration, prod credential reads.
- **Agent autonomy worked** in 2 categories per Kural #7+#8: SSH+sudo+kubectl operations on test, Codex consensus drives implementation.
- **Gray areas persist**: Vault `generate-root` via container CLI (sandbox didn't block, agent attempted, key drift evident); ESO AppRole reads (sandbox didn't block, role-id may be public-ish but secret-id should not be); direct PG ALTER on production-shared schema (sandbox blocked correctly).

ADR-0010 §2.5 captured the user-approval matrix for Vault credential operations. ADR-0011 extends this to a **3-axis governance layer** addressing drift, audit, and boundary as a unified contract.

## 2. Decision

We adopt three coordinated governance mechanisms, each MUST-have, none redundant with ADR-0010:

### 2.1 Plan-time drift detection automation (axis A)

ADR-0011 mandates contract-level guards that catch drift at plan-time + CI-time, not at live-load test:

#### 2.1.1 Anchor table / Workcube schema verification

CI cron job (workflow_dispatch + weekly Mon 03:30 UTC) verifying:

- `data_access.scope` CHECK constraint `scope_kind_source_table_consistent` matches Codex `019dd34e` hybrid contract (company → OUR_COMPANY, project → PRO_PROJECTS, branch → BRANCH, depot → DEPARTMENT). Diff vs ADR-0008 § Object id encoding table.
- `validate_scope_ref()` function body references `workcube_mikrolink.our_company` (not `workcube_mikrolink.company`) for company branch.
- `data_access.organization_company` `source_table` default + CHECK = `'OUR_COMPANY'`.
- `docs/migration/workcube-schema.json` snapshot includes 4 anchor tables (OUR_COMPANY + COMPANY + BRANCH + DEPARTMENT + PRO_PROJECTS as tenant boundary references).

Failure → CI red → blocks merge of any data_access schema change PR.

#### 2.1.2 ETL ↔ DB format contract verification

`scripts/migration/etl_worker/etl_worker/transform.py:make_source_pk` canonical JSON form vs `validate_scope_ref()` extraction logic must be compatible. CI gate:

- Parses `make_source_pk` for the JSON dumps format.
- Parses V19/V20/V21/V25/V26 SQL function bodies for `jsonb->>0` extraction or direct compare.
- Verifies dual-format tolerance (V26 contract: OR predicate with `oc.source_pk = v_pk OR oc.source_pk = p_ref`).

Failure → drift surfaced before live-load test.

#### 2.1.3 Schema-service snapshot diff vs reports_db actual schema

Quarterly cron job (Mon 03:30 UTC, 1st Mon of quarter):

- Compares `docs/migration/workcube-schema.json` snapshot vs `reports_db.workcube_mikrolink.*` columns + FK constraints.
- Diff > N columns → P2 alert; diff = 0 (green) silent.
- Excludes intentional schema-service-not-yet-tracked tables (parametric, deferred per Faz 16.2.P).

Failure mode: schema-service snapshot stale → next ADR-0008 anchor decision uses outdated reference.

#### 2.1.4 Env-prefix + container compatibility verification

Pre-merge gate on PR touching `scripts/migration/etl_worker/etl_worker/config.py` or `host-compose/**/backend.env`-like files:

- Static analysis: env var prefixes used in code vs documented in operator runbooks.
- Multi-prefix fallback present (per PR #211 pattern).
- requires-python compatibility: pyproject vs container Python (Mac dev-pg vs platform-pg-test container 3.10 vs 3.12).
- Dockerfile keyring/apt source format (Debian 12 sqv-compatible) — lint-ish check.

These four sub-mechanisms combine into a `gate-drift-detection.yml` CI workflow + `scripts/check_drift_*.py` helpers.

### 2.2 Audit cadence (axis B)

ADR-0010 §2.2 defined Vault DR drill cadence ("ilk iki ay monthly, sonra quarterly"). ADR-0011 operationalizes:

#### 2.2.1 First drill schedule

- Test vault first drill: within 30 days of ADR-0011 acceptance (operator-driven via PR #202 runbook).
- Prod vault first drill: only after test vault drill PASS + DR keyset re-verified (PR #203 runbook).
- Subsequent drills: monthly for first 2 months, quarterly thereafter.

#### 2.2.2 Drill failure → P1 incident workflow

- Drill failure (any of: unseal threshold not met, root regen failed, KV path inventory mismatch, audit backend absent) = P1 incident.
- Block prod credential writes until resolved.
- Postmortem requirement: `docs/state/vault-drill-<YYYY-Q>-postmortem.md` with root cause + remediation + re-drill schedule.

#### 2.2.3 Drill evidence format

Per-quarter evidence file: `docs/state/vault-drill-<YYYY-Q>.md` with:

- Test vault status (sealed/init/threshold/total-shares)
- Unseal key validity (which keys passed Progress check; cancel-before-complete proof)
- ESO approle capabilities-self diff vs eso-runtime policy
- KV path version inventory + last-modified timestamps
- Audit backend status (file or other)
- Recovery bundle freshness (raft snapshot age + key checksums)
- Drill verdict + next drill date
- Comparison vs previous quarter (stale increase counter)

#### 2.2.4 Test/prod separation

Per ADR-0010 §2.5: drill on test does NOT imply prod readiness. Prod drill = separate user-approval + separate evidence file. Codex `019dd3bd`: "prod/test ayrı DR contract" preserved.

### 2.3 Agent/operator boundary governance (axis C)

ADR-0010 §2.5 defined the user-approval matrix. ADR-0011 formalizes the **action taxonomy** that determines which side any new operation falls on:

#### 2.3.1 Action taxonomy (4 classes)

| Class | Definition | Default authority |
|---|---|---|
| **credential-read** | Read of credential material (Vault state files, secret-id values, root tokens, kv data fields) | User-approval REQUIRED. Sandbox MUST block agent. |
| **credential-write** | Write/rotate of credential material (Vault kv patch, AppRole secret-id rotation, root regen) | User-approval REQUIRED. Sandbox MUST block agent. May be wrapped via DR-3 platform-ops-vault-patch (per ADR-0010 §2.1) which itself uses bootstrap-writer AppRole — wrapper invocation is bootstrap-only, NOT runtime credential-write. |
| **state-mutation** | DDL on shared/production DB, prod kustomize apply, prod image rotation, prod K8s service mutation | User-approval REQUIRED for prod. Test = Codex consensus + Kural #7. Hot-patch via psql heredoc bypassing migration path = always blocked. |
| **boundary-cross** | Cross-repo writes, cloud IAM operations, external secret manager migrations | User-approval REQUIRED. Sandbox blocks unless explicit `bypassPermissions` workflow defined. |

Operations not in these classes (read-only inventory, runbook drafting, ADR docs, CI script port, evidence file capture) = Codex consensus sufficient.

#### 2.3.2 Per-PR boundary declaration

Following PR #199's D35 ladder template pattern, each PR description MUST include:

```markdown
## Boundary declaration (ADR-0011 §2.3)

This PR includes (multi-select):
- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] none of the above (Codex consensus only)

If any class checked: explicit operator step + user-approval evidence link.
```

#### 2.3.3 Sandbox-blocking pattern formalization

Sandbox blocking events are **expected behavior, not failures**. When sandbox blocks an action:

1. Agent stops, captures the attempt in current-state or evidence file.
2. Delivers user-driven runbook for the blocked action.
3. Per-PR description includes: "Sandbox blocked X — user runbook at `docs/RB-<X>.md`."

Bypassing sandbox via `dangerouslyDisableSandbox` or `bash -c` workaround = **anti-pattern**. Codex consensus does NOT override sandbox; they are independent governance layers.

#### 2.3.4 Agent gray area resolution

The 3 gray areas observed in Session 32:

- **Vault generate-root via container CLI**: now classified `credential-write` (creates token; sandbox MUST block; user-driven only).
- **ESO AppRole reads**: split — `role_id` is metadata (read OK, semi-public via ClusterSecretStore CRD); `secret_id` is credential material (sandbox MUST block agent reads if not explicitly authorized for test-cluster wrapper invocation).
- **Direct prod PG ALTER**: `state-mutation (production)` (always user-approval).

## 3. Consequences

### 3.1 Positive

- 4 drift events in Session 32 → none should recur because plan-time CI guards catch them.
- Vault DR drill cadence prevents stale-keyset surprise (test vault keyset stale was found by D35-2 unblock attempt; ADR-0011 §2.2 surfaces this proactively).
- Boundary taxonomy reduces gray-area ambiguity for future agent sessions.
- ADR-0010 §2.5 + ADR-0011 §2.3 = layered governance (high-level + tactical taxonomy).
- Per-PR boundary declaration creates audit trail without manual tracking.

### 3.2 Negative / Trade-offs

- **CI overhead**: 4 new drift-detection workflows + 1 cron job. Mitigated by path-filter triggers + skip-on-no-relevant-files semantics.
- **Drill burden**: monthly initial cadence is operator-time-expensive. Mitigated by clear evidence template + operator-runbook automation.
- **Boundary taxonomy maintenance**: future operations may not fit cleanly into 4 classes. Mitigated by ADR-0011 amendment process (add class + decision rule).
- **Per-PR declaration cost**: ~5 minutes added to each PR description. Acceptable; matches ADR-0010 §2.3 D35 ladder declaration cost.

### 3.3 Rejected alternatives

- **Big-bang single ADR covering A/B/C/D/E**: Codex `019dd3bd` rejected — D and E are downstream consumers (ci/ port deferral status + D35-3 product path), not governance decisions. ADR-0011 stays narrow.
- **Defer to D35-3**: rejected — Codex `019dd333` 10-12 PR threshold passed (31 PRs); waiting for D35-3 carries Session 32 drift forward into product-path work.
- **External CI service** (e.g., Renovate, Dependabot for cross-repo drift): rejected as out-of-scope; ADR-0011 focuses on within-repo + cross-repo schema-service-driven drift.
- **Agent self-policing instead of sandbox**: rejected — Codex `019dd333` explicitly noted sandbox + ADR + Codex consensus three-layer enforcement is sufficient AND non-redundant.

## 4. PR sequence (drives this ADR forward)

| # | Class | Scope | Authority |
|---|---|---|---|
| **DD-0** (this PR) | governance docs | ADR-0011 + state refresh | Codex consensus |
| DD-1 | A | `gate-drift-detection.yml` workflow + `scripts/check_drift_anchor_table.py` (anchor + V25/V26 contract guards) | Codex consensus |
| DD-2 | A | `scripts/check_drift_etl_make_source_pk.py` (transform.py vs SQL extraction format) | Codex consensus |
| DD-3 | A | quarterly cron `gate-drift-schema-service-snapshot.yml` (snapshot diff vs reports_db actual) | Codex consensus (read-only) |
| DD-4 | A | env-prefix + Python compat + Dockerfile keyring lint | Codex consensus |
| AC-1 | B | drill evidence template + first-drill runbook (operator runs PR #202 steps + commits evidence) | **User-approval** for drill execution |
| BG-1 | C | per-PR boundary declaration template + check_pr_description CI gate | Codex consensus |
| BG-2 | C | sandbox-blocking pattern playbook + 3 gray-area resolution docs | Codex consensus |

D + E (ci/ port resume + D35-3 product path) referenced as PLAN.md / current-state.md tracker entries; not ADR-0011 PRs.

## 5. Approval matrix (ADR-0011 §2.3 quick reference)

Combined with ADR-0010 §2.5:

| Operation | Class | ADR-0010 §2.5 | ADR-0011 §2.3 | Result |
|---|---|---|---|---|
| Vault root regen (test) | credential-write | YES | YES | User-approval |
| Vault root regen (prod) | credential-write | YES | YES | User-approval (extra: prod drill prereq) |
| `vault kv patch` via bootstrap-writer wrapper | (wrapper) | NO (DR-3 §2.1 already abstracted) | wrapper invocation = NOT credential-write | Codex consensus + Kural #7 |
| ALTER FUNCTION on prod-shared schema bypassing migration | state-mutation (prod) | YES | YES | Sandbox MUST block + User-approval |
| ALTER FUNCTION via approved migration on test | state-mutation (test) | NO (test) | NO (test path approved) | Codex consensus + Kural #7 |
| Codex iter (read-only thread) | none | NO | NO | Auto |
| Cross-repo write (platform-backend, platform-web) | boundary-cross | YES | YES | Sandbox blocks + User-approval |

## 6. Verification

This ADR's correctness is verified by:

- Each downstream PR (DD-1..AC-1..BG-2) cites ADR-0011 §X.Y in commit + PR description.
- Each PR includes the §2.3.2 Boundary declaration block.
- New CI gates pass green on this ADR's own PR (only ADR doc; no code mutation).
- Codex `019dd3bd` strategic recommendations reflected in §2 decisions (1:1 mapping).

## 7. Closure criteria (when ADR-0011 governance complete)

- DD-1..DD-4 + AC-1 + BG-1+BG-2 all merged.
- First Vault DR drill executed (test) + evidence file committed.
- 90 days of drift-free CI runs (no new live-load drift events).
- Codex retrospective review thread iter (post-90-day) opens decision for ADR-0011 amendments or sunset.

## 8. References

- Codex thread `019dd3bd` (xhigh effort retrospective + ADR-0011 candidate review)
- Codex thread `019dd333` (Session 32 mid retrospective; 10-12 PR threshold)
- Codex thread `019dd34e` (OUR_COMPANY drift fix sequence + planning-gap acknowledgement)
- ADR-0010 §2.2 (DR contract), §2.5 (operator/agent authority)
- ADR-0009 § D35 Evidence Ladder
- ADR-0008 § Object id encoding (V25 transition map)
- 31 PR landed Session 32 (#194-#218): see `docs/state/current-state.md` Session 32 FINAL Live Delta
- Drift evidence: PR #211 (env prefix), PR #212-#216 (OUR_COMPANY), PR #201 (Dockerfile keyring)
- Sandbox-blocked attempts: hot-patch validate_scope_ref (logged in this session retrospective + PR #216)
- Vault state files: `/home/halil/platform/state/vault/vault-init*.json`, `vault-unseal-key-{1,2,3}` (test vault stale; prod un-verified per ADR-0010 §2.5)
