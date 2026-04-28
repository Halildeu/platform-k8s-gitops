# D35-0 — Outbox Isolated Preflight (Faz 21.3)

**Tier**: D35-0 (Runtime Preflight — regression-detect baseline)
**Date**: 2026-04-28
**Cluster**: k3d-test on staging-sw (host bridge 172.19.0.x)
**Permission-service image digest**: sha256:b6d59f0ab5d1791289544b530130d60493f503529c4fdb9515efb0bf8c0ca3fb
**Codex threads**: `019dd2a2` (β verdict — synthetic seed forbidden) + `019dd2c9` (xhigh — D35 ladder retroactive classification)
**Operator**: agent (kubernetes6 session, Kural #7 SSH+sudo+kubectl authority)

**Tier classification (retroactive per ADR-0010 §2.3)**: This file was originally
authored before ADR-0010 introduced the D35 evidence ladder. Per ADR-0010 §2.3
+ ADR-0009 § "D35 Evidence Ladder", this evidence is correctly classified as
**D35-0 Runtime Preflight** — proves the runtime infrastructure is alive
(image digest, env, HikariPool-2 startup, OutboxPoller scheduler, V22+V23
schema present, outbox empty), but does NOT prove D35-2 (= "D35 first
evidence" — full eventual-consistency POST→outbox→FGA chain with real
Workcube data).

**Scope**: Permission-service runtime prereq's for the V22+V23 outbox eventual-consistency
flow — image digest match, ESO/Vault credential delivery, secondary datasource bootstrap,
outbox poller scheduling. **Does NOT** cover D35-2 (= "D35 first evidence" canlı scoped E2E
proof per ADR-0009) — that remains an OPEN BLOCKER until ETL load populates
`workcube_mikrolink.company` with real Workcube source_pk values (D35-1 prereq).

## Why this is preflight, not D35

Per Kural #9 (no fake/cosmetic work) + 2026-04-26 user mandate ("Workcube MSSQL kaynak
şeması her zaman schema-service üzerinden alınır. Agent sentetik tablo/kolon/FK
üretmemeli"), seeding a stub `workcube_mikrolink.company` row to unblock
`validate_scope_ref()` would cross the synthetic-fixture line and falsify the D35
"canlı scoped evidence" claim (Codex `019dd2a2` rationale).

The 11-step D35 sequence (PR #189 runbook Step 9) requires Step 9.4 to insert a real
scope row with `SCOPE_REF='["1001"]'` referencing real Workcube company source_pk=1001;
without ETL load, that data is absent and any synthetic seed is fake work.

**This preflight captures only what CAN be evidenced without ETL data**: the runtime
infrastructure. It is the highest fidelity proof currently obtainable on staging-sw.

## Step 9.1 — Image digest match

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'"
```

```text
pod=permission-service-6566657d6c-jf86l
imageID=ghcr.io/halildeu/platform-backend-permission-service@sha256:b6d59f0ab5d1791289544b530130d60493f503529c4fdb9515efb0bf8c0ca3fb
expected=ghcr.io/halildeu/platform-backend-permission-service@sha256:b6d59f0ab5d1791289544b530130d60493f503529c4fdb9515efb0bf8c0ca3fb
MATCH
```

**Verdict**: PASS — running pod is the PR-G follow-up image (sha-4f408f4) per
gitops PR #190 pin.

## Step 9.2 — REPORTS_DB env evidence (test overlay shared-cred caveat)

```bash
kubectl --context k3d-test -n platform-test exec deploy/permission-service -- env \
  | grep -E 'REPORTS_DB_(ENABLED|URL|USERNAME|PASSWORD|POOL_)|ERP_OPENFGA_ENABLED'
```

```text
REPORTS_DB_USERNAME=platform
REPORTS_DB_PASSWORD=<REDACTED, length=44>
REPORTS_DB_ENABLED=true
ERP_OPENFGA_ENABLED=true
REPORTS_DB_POOL_MIN=1
REPORTS_DB_POOL_MAX=5
REPORTS_DB_URL=jdbc:postgresql://postgres:5432/reports_db
```

**Caveat — shared credentials**: per Codex `019dd296` verdict B + PR #191, the test
overlay aliases `REPORTS_DB_USERNAME`/`PASSWORD` onto the existing Vault `db_username`/
`db_password` keys (the `platform` owner role) because Vault `kv/platform/permission-service`
does not yet have dedicated `reports_db_username`/`reports_db_password` properties. This
is **NOT least-privilege proof**. Follow-up: dedicated `reports_db` role with read +
DML on `data_access.scope`/`scope_outbox` only, Vault populate, revert PR #191 patch.

**Verdict**: PASS — all 7 expected env vars present, ESO/Vault delivery contract
preserved.

## Step 9.3 — HikariPool-2 + reportsDb persistence unit + outbox scheduler

### HikariPool-2 startup (logs)

```text
2026-04-28 05:51:47.654Z INFO HikariDataSource HikariPool-1 - Starting...
2026-04-28 05:51:48.650Z INFO HikariDataSource HikariPool-1 - Start completed.
2026-04-28 05:51:57.037Z INFO LogHelper           HHH000204: Processing PersistenceUnitInfo [name: reportsDb]
2026-04-28 05:51:57.054Z INFO HikariDataSource HikariPool-2 - Starting...
2026-04-28 05:51:57.262Z INFO HikariDataSource HikariPool-2 - Start completed.
2026-04-28 05:51:57.784Z INFO LocalContainerEntityManagerFactoryBean Initialized JPA EntityManagerFactory for persistence unit 'reportsDb'
2026-04-28 05:52:13.740Z INFO PermissionServiceApplication Started PermissionServiceApplication in 42.195 seconds
```

### Outbox poller activity (prometheus metrics @ T+85s after start)

```text
# Primary outbox poller (data_access.scope_outbox, V22+V23):
tasks_scheduled_execution_seconds_count{
  code_function="pollAndProcess",
  code_namespace="com.example.permission.dataaccess.OutboxPoller",
  outcome="SUCCESS"
} 17

# Repository invocations from this poller:
spring_data_repository_invocations_seconds_count{
  method="claimBatch", repository="DataAccessScopeOutboxRepository", state="SUCCESS"
} 17
spring_data_repository_invocations_seconds_count{
  method="recoverStuckRows", repository="DataAccessScopeOutboxRepository", state="SUCCESS"
} 17

# Secondary tuple-sync outbox poller (different cadence):
tasks_scheduled_execution_seconds_count{
  code_function="pollAndProcess",
  code_namespace="com.example.permission.outbox.TupleSyncOutboxPoller",
  outcome="SUCCESS"
} 3

# Zero exception/error counters across all poller invocations.
```

### Pod readiness

```text
pod permission-service-6566657d6c-jf86l: Running ready=True containersReady=True
```

**Verdict**: PASS —
- Both Hikari pools started, primary (auth_db) + secondary (reports_db).
- `reportsDb` persistence unit fully initialized (no Hibernate validate failures —
  V19+V20+V21+V22+V23 schema present in target DB).
- Outbox poller alive: 17 successful poll cycles in ~85s (5s scheduling interval),
  `claimBatch` + `recoverStuckRows` both succeeding against the empty outbox.
- Tuple-sync outbox poller (legacy single-tuple lane) also active.

## Reports DB schema state (V22+V23 contract)

```text
data_access.scope_outbox columns (V22 + V23 typed):
  id BIGSERIAL PK
  scope_id BIGINT NOT NULL FK→data_access.scope(id) ON DELETE CASCADE
  action TEXT NOT NULL CHECK ∈ {GRANT, REVOKE}
  payload JSONB NOT NULL
  status TEXT NOT NULL CHECK ∈ {PENDING, PROCESSING, PROCESSED, FAILED} DEFAULT 'PENDING'
  attempt_count INT NOT NULL DEFAULT 0
  last_error TEXT
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()
  locked_by TEXT
  locked_until TIMESTAMPTZ
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  processed_at TIMESTAMPTZ
  tuple_user TEXT NOT NULL          [V23]
  tuple_relation TEXT NOT NULL      [V23]
  tuple_object TEXT NOT NULL        [V23]

Indexes:
  idx_scope_outbox_claim        (status, next_attempt_at) WHERE status='PENDING'
  idx_scope_outbox_failed       (created_at) WHERE status='FAILED'
  idx_scope_outbox_recovery     (locked_until) WHERE status='PROCESSING'
  idx_scope_outbox_scope_id     (scope_id)
  idx_scope_outbox_tuple_ordering (tuple_user, tuple_relation, tuple_object, id)
                                 WHERE status ∈ {PENDING, PROCESSING}   [V23]

Old V22 idx_scope_outbox_scope_ordering: ABSENT (V23 dropped — confirmed PR-G correct)
```

**Verdict**: PASS — schema matches V22+V23 expected shape exactly.

## Reports DB row state

```text
organization                     | 1 row (AÇIK active, V19 seed)
organization_company             | 0 rows  (CROSS JOIN with empty workcube_mikrolink.company)
data_access.scope                | 0 rows
data_access.scope_outbox         | 0 rows
workcube_mikrolink.company (FYI) | 0 rows  ← BLOCKER for D35 Step 9.4-9.10
```

## D35 first evidence — OPEN BLOCKER

D35 canlı scoped E2E evidence (PR #189 runbook Step 9.4 through 9.11) requires:

- Real `workcube_mikrolink.company` row(s) for `validate_scope_ref()` trigger to pass
- A real `organization_company` mapping AÇIK → real source_pk (not the canonical
  `["1001"]` fixture used in the runbook example unless `1001` is a real Workcube ID)
- An admin user with `module:ACCESS#can_manage` OpenFGA tuple seeded
- A non-admin user UID for the deny assertion (Step 9.9)

These prerequisites depend on Faz 16.2.P (parametric ETL) or operator-driven minimum
real-data load via the etl-worker pipeline. Until that lands, D35 first evidence
**stays OPEN BLOCKER**.

**Operator instruction set** (when prereq met):

1. ETL load → reports_db `workcube_mikrolink.company` has at least 1 real row.
2. Re-seed `data_access.organization_company` (V19 seed re-run, or manual INSERT)
   to populate the AÇIK → source_pk(s) mapping.
3. Run PR #189 runbook Step 9.4 through 9.11 with real source_pk values.
4. Capture as a separate evidence file under `docs/faz-21-3-evidence/`.
5. Update ADR-0009 D35 status from "OPEN BLOCKER" to first evidence reference.

## Artifacts referenced

- PR #186 (V21 JSON parse fix), PR #187 (V22 outbox table), PR #188 (V23 typed columns)
- PR #189 (D35 runbook + ADR-0009 update)
- PR #190 (PR-G follow-up digest pin: `sha-4f408f4` /
  `sha256:b6d59f0ab5d1791289544b530130d60493f503529c4fdb9515efb0bf8c0ca3fb`)
- PR #191 (test overlay shared-cred patch + REPORTS_DB_ENABLED=true)
- platform-backend PR #16 (PR-G follow-up — outbox poller + AccessScopeService refactor)
- Codex threads: `019dd0e0` (V23 design), `019dd296` (verdict B shared-cred),
  `019dd2a2` (verdict β D35 deferral)

## Verdict — overall

**Faz 21.3 outbox runtime: GREEN at infrastructure level.**

- ✓ Image digest pinned + running (Step 9.1)
- ✓ ESO/Vault credential delivery + REPORTS_DB_* + ERP_OPENFGA_ENABLED env (Step 9.2)
- ✓ HikariPool-2 + reportsDb persistence unit + outbox poller alive (Step 9.3)
- ✓ V22+V23 schema applied + tuple-key ordering index correct
- ✗ Step 9.4-9.11 (eventual-consistency, allow/deny, revoke, FAILED count) — **DEFERRED
  pending ETL load**

**Completed**: 2026-04-28T06:00:00Z (UTC)
