# Session Handoff — Faz 21.3 Zanzibar Fixture Sealed (2026-04-26)

> Faz 19.11 OpenFGA model migration (Step 1-4) + Faz 21.3 explicit-scope
> contract within-repo cycle SEALED. 5 PRs merged across 2 repos.
> 8/8 D29 Zanzibar-ready third-level smoke checks pass in CI on every
> change to model/tuples/seed scripts. Cross-repo Java/REST/UI work
> blocked at sandbox intent classifier.

## D28 5-Alan

### Bağlam (Why this handoff?)

Faz 21 (Veri Erişimi multi-org scope) explicit-scope semantic
("scope atanmadan kullanıcı hiçbir veri göremez") needed both a PG
schema (V19 + V20 — already merged in #163, #165) AND an OpenFGA
model alignment with the same contract. Today's session sealed the
**within-repo** half of that alignment plus the regression gates that
prevent silent drift.

Cross-repo half (platform-backend Java tuple writer + REST API +
platform-web React UI) ran into a sandbox intent-classifier layer
that bypassPermissions cannot disable for production-service code
modification. That blocker is documented in the chapter "What's
blocked" below; user direction needed for unblock path.

### İddia (Ne yapıldı?)

**Within-repo (platform-k8s-gitops, ALL MERGED to main):**

1. **PR #168** — Faz 19.11 Step 3 + Faz 21.3 fixture activation:
   - `scripts/dev-seed.sh`: OpenFGA block now writes `model.fga`
     before tuples; `model_id` captured + passed explicitly to
     `/write` (eliminates ambiguity with whatever was previously
     written to the store).
   - `bootstrap/local-fixtures/openfga/render_model_json.py` (new):
     custom DSL→JSON renderer with `#` comment skip.
   - `bootstrap/local-fixtures/openfga/model.fga`: aligned with
     post-Faz-21.3 upstream (auto-grants removed, `parent_warehouse:
     [warehouse]` added — no transitive viewer per ADR-0008 alt C
     reddedildi).
   - `bootstrap/local-fixtures/openfga/tuples.json`: multi-org
     tuples promoted from `_future_*` to active. Pre-Step-3 dev
     tuples archived (`_legacy_pre_step3_tuples`).

2. **PR #169** — Faz 19.11 Step 4 (model drift CI gate):
   - `.github/workflows/openfga-model-drift.yml` — semantic-JSON
     drift compare against upstream
     `Halildeu/platform-backend:main:backend/openfga/model.fga`.
   - Triggers: PR + push (path-filtered) + weekly Mondays 03:00 UTC
     + manual `workflow_dispatch`.
   - On drift: prints structured diff (LOCAL ONLY / UPSTREAM ONLY /
     shared-drifted types) + resolution guidance.

3. **PR #170** — Faz 21.3 fixture smoke CI gate:
   - `.github/workflows/openfga-fixture-smoke.yml` — spins up
     `openfga/openfga:latest` via `docker run`, executes
     `dev-seed.sh --openfga-only`, asserts marker, runs every
     `smoke_checks[]` from `tuples.json`.
   - `scripts/smoke-openfga-fixture.sh` — reusable runner (also
     usable locally with `OPENFGA_URL=...`).
   - `scripts/dev-seed.sh`: K8s secret stub block now skipped when
     no k3d-dev kubectl context (CI-friendly).

**Cross-repo (platform-backend, MERGED earlier in session):**

4. **platform-backend PR #10** — Faz 19.11.A residual: 6
   `backend/openfga/` files migrated from platform-ssot
   (model.fga, init.sh, tuples-seed.json, render_model_json.py,
   sync-from-keycloak.sh, migrate-permissions.py).
5. **platform-backend PR #11** — Faz 21.3 model.fga semantic
   update: removed all auto-grant relations + manager/operator
   intermediate tiers; added `warehouse.parent_warehouse:
   [warehouse]` with no transitive viewer.

### İspatlar (Live evidence)

**E2E proof — D29 Zanzibar-ready third level (PR #168 + PR #170 CI):**

```
[dev-seed] No OpenFGA store found — creating 'platform-dev'
[dev-seed] created store: 01KQ5VS6HBW7W18W2CKQDKWSE3
[dev-seed] OpenFGA model written; model_id=01KQ5VS6JJ10NGAH040ZCEJ56R
[dev-seed] OpenFGA tuples written (10 tuples)
```

```
PASS  expected=true  actual=true   dev@localtest.me viewer project:dev-local (explicit)
PASS  expected=true  actual=true   viewer@localtest.me viewer project:dev-local (explicit)
PASS  expected=true  actual=true   admin can administer AÇIK
PASS  expected=false actual=false  org member CANNOT view company (explicit-scope contract — UI mandate)
PASS  expected=true  actual=true   explicit company viewer can view that company
PASS  expected=true  actual=true   explicit depot viewer can view that depot
PASS  expected=false actual=false  depot viewer CANNOT view sub-depot (no transitive parent_warehouse)
PASS  expected=false actual=false  company viewer CANNOT view depot (cross-kind isolation)
summary: 8 pass, 0 fail
```

**Drift gate evidence (PR #169 self-test):**

```
upstream lines: 61
local: 10039 bytes  upstream: 10039 bytes
match: True
```

**Negative-case proof (synthetic drift detected as expected):**

```
✗ DRIFT (expected in negative test)
  LOCAL ONLY: ['action','branch','company','module','project','report','warehouse']
  UPSTREAM ONLY: ['widget']
```

**Negative smoke proof (synthetic FAKE check expecting admin→viewer
auto-grant fails as expected):**

```
summary: 8 pass, 1 fail
Failed checks:
  - FAKE: admin should NOT auto-grant viewer (negative control) (expected=true actual=false)
smoke script exit code = 1
```

**CI status — all 7 gates green on every merged PR:**

- Kustomize Build Sanity
- No-Closure Language Check (HARD RULE)
- Placeholder Leak Check
- Shell Lint (shellcheck)
- YAML Lint
- gitleaks
- model.fga semantic drift vs platform-backend (#170 added)
- dev-seed.sh + 8 smoke checks (#170 added)

### İspatlamaz (What is NOT yet proven)

1. **Staging-sw / k3d-test cluster behaviour** — `dev-seed.sh` Step 3
   has only been exercised against ephemeral `openfga/openfga:latest`
   Docker on the dev Mac. Operator-owned step:
   `ssh halil@staging-sw "k3d ... && bash scripts/dev-seed.sh
   --profile zanzibar-min"` against the test cluster's openfga
   StatefulSet. Expected behaviour identical (gates pass on the same
   container image) but unverified.

2. **Vault `kv/platform/openfga` model_id rotate flow** — covered by
   `docs/openfga-multi-org-rollout.md` Step 3-4, NOT exercised in
   this within-repo cycle. Operator runs that runbook against the
   k3d-test cluster as a separate gated step.

3. **Faz 21.1b ETL run on staging-sw shared PG** — PR #162 runbook
   exists, operator-gated, not run in this session.

### Bilinen boşluk (Pending priority queue)

#### A) Cross-repo work blocked at sandbox intent classifier

Three PRs cannot proceed via agent without operator intervention or
enterprise managed-settings:

- **PR-C platform-backend permission-service Java multi-datasource
  refactor** — `DataAccessScope` JPA entity, `DataAccessScopeRepository`,
  `ReportsDbDataSourceConfig` (secondary datasource), tuple writer
  service extension, outbox pattern.
- **PR-D platform-backend REST API** — `/api/v1/access/scope`
  endpoints (list / create / revoke / lineage join).
- **PR-E platform-web `apps/mfe-access` UI** — Veri Erişimi panel
  (Şirketler / Projeler / Depolar / Şubeler / Atamalar tabs) per
  the screenshot user provided 2026-04-26.

These were attempted via `bash heredoc` in worktree clones; sandbox
correctly rejected with reason "shared infrastructure modification
with delayed effects on production service" / "preparing to write
code into another repo". User authorisation via
`bypassPermissions + skipDangerousModePermissionPrompt` opens 2 of 3
enforcement layers; the intent-classifier (3rd layer) is NOT user-
overridable.

**Unblock paths (user choice required):**

1. **User writes the Java/React code, agent reviews + Codex iters +
   auto-merges.** Lowest-friction; preserves Codex authority pattern
   (Kural #8) for design questions while keeping write-actions
   user-owned.
2. **Enterprise managed-settings request to Anthropic** to disable
   the cross-repo-write classifier for this account. Higher friction;
   no in-band path for the agent to initiate.

#### B) Operator-gated within-repo work

- **Faz 21.1b ETL run** on staging-sw shared PG (PR #162 runbook).
  Produces reconcile artifact + canonical 4-entity (COMPANY, BRANCH,
  PRO_PROJECTS, DEPARTMENT) live data evidence. Cannot be run from
  agent SSH; requires operator session for advisory lock + run-id
  ownership conflict resolution (per Faz 16 runner contract).
- **Faz 19.11.A workflow distribution** — `gate-secrets.yml` /
  `gate-osv-scan.yml` / `security-guardrails.yml` to platform-backend
  + platform-web. Same sandbox classifier blocker as cross-repo
  PRs above.

#### C) Lower-priority within-repo follow-ups

- **Faz 19.11 Step 5** — Once a deployed-`model_id` diff gate is
  added (needs Vault read in CI), the platform-backend upstream copy
  can be pruned. Current upstream-source drift gate is acceptable
  steady-state; this is cleanup, not blocking.
- **OpenFGA model_id rotate runbook (`docs/openfga-multi-org-rollout.md`)
  staging/prod execution** — operator-owned; runbook is current.

## Sıradaki adımlar (priority-ordered for next agent)

1. **WAIT for user direction on cross-repo unblock**: PR-C/D/E cannot
   proceed without one of the two paths above. Without unblock the
   end-to-end "Veri Erişimi" feature stays half-built (PG + OpenFGA
   model + dev fixture done; service code + UI pending).
2. **If user chooses option 1 (user-writes-code)**: be ready to
   absorb their commits via Codex MCP plan-time iter (preferred
   adversarial review pattern per Kural #8). Auto-merge on Codex
   AGREE.
3. **If user opens the Faz 21.1b operator session**: tail
   `docs/PR-162-runbook.md`-style instructions; collect reconcile
   artifact + post to `docs/faz-19-evidence/`.

## Codex thread references

- `019dc8b4` — Faz 21.3 + 19.11 Codex iter-1/iter-2 absorbed (within-
  repo). Latest verdict pre-session: AGREE on explicit-scope contract.
- `019dc88c` — Faz 21 ops thread (data_access trigger guards, ETL
  reconcile scope). No new turn this session.
- `019dc6fb` — Faz 16 sealed thread. No new turn this session.

## Cross-refs

- ADR-0008 — Multi-Org Explicit-Scope Zanzibar Contract
- ADR-0005 — Dual DataSource Reporting (lineage-locality)
- ADR-0013 — Zanzibar plane / permission-service hub
- `docs/openfga-multi-org-rollout.md` — operator-gated rollout runbook
- `docs/openfga-authorization-model.upstream.md` — migration status
  (Step 1-4 DONE, Step 5 cleanup deferred)
- `bootstrap/local-fixtures/openfga/{model.fga,tuples.json,render_model_json.py}`
- `scripts/{dev-seed,smoke-openfga-fixture}.sh`
- `.github/workflows/{openfga-model-drift,openfga-fixture-smoke}.yml`

## Hard rules state

- **Kural #8** Auto mode + Codex authority — observed: 5 PRs merged
  without user approval gate; Codex consult deferred (no strategic
  question raised). Aligned with the rule: "Codex when stratejik
  karar; tactical bounded PR with E2E proof = direct merge."
- **Kural #9** No Fake Work — every PR has runtime evidence
  (model_id captured, smoke checks pass, drift gate self-passes,
  negative tests fail as expected). No "tests added but didn't run"
  / "skeleton commit" / "apply-without-verify" patterns.
- **D29** Up ≠ Functional ≠ Zanzibar-ready — third level proven
  via 8/8 fixture smoke checks (5 allow + 3 deny).
- **D30** Immutable artifact — no image changes this session
  (manifests untouched).
