# DR-6 Readiness Check — Faz 16.2.A Pre-flight (NOT D35-1)

**Tier**: NOT a D35-X tier; pre-flight readiness for DR-6 runbook execution.
**Date**: 2026-04-28
**Cluster**: staging-sw (host bridge platform-test-net)
**Image**: `etl-worker:dr-6-readiness` built locally (Dockerfile fix at `cdcc7f8`)
**Codex thread**: `019dd2c9` (xhigh effort architecture)
**Operator**: agent (kubernetes6 session, Kural #7 SSH+sudo+kubectl + Codex consensus authority)

## Purpose

`docs/RB-faz-16-2-A-scope-anchor-load.md` Step 0 + Step 1 are read-only/dry-run; Step 2 is the live-load user-approval gate. This file captures readiness — what works without operator approval, what does NOT, and what user action unblocks the live run.

## What this is

- **Pre-flight verification** of the Faz 16.2.A scope anchor load runbook.
- Validates the etl_worker stack can build and parse manifests on staging-sw.
- Surfaces Workcube MSSQL credential issue as a blocker BEFORE asking the user for the live-load approval (so the user has full context).

## What this is NOT

- D35-1 evidence (those captures require live load + reconcile, both behind user-approval gate).
- A D35-anything evidence; this is pre-flight readiness for DR-6 runbook.

## Step 0 — Manifest validation (PASS)

```bash
docker run --rm \
  -v /home/halil/platform-k8s-gitops/scripts/migration/etl_worker/config:/app/config:ro \
  etl-worker:dr-6-readiness validate-manifest
```

**Result**:
```text
{"path": "config/tables.yaml", "table_count": 4, "event": "manifest.loaded", "level": "info", "timestamp": "2026-04-28T07:02:00.423349Z"}
✓ Manifest valid (4 tables, syntax OK)
```

4 tables defined: COMPANY, BRANCH, PRO_PROJECTS, DEPARTMENT — exactly the 4 anchor tables required by `validate_scope_ref()` for the 4 D35 scope_kinds (company / branch / project / depot→DEPARTMENT). Idempotency keys + columns subset present.

**Verdict**: PASS — manifest is structurally ready.

## Step 1 — MSSQL inspect-source (FAIL)

```bash
docker run --rm --network platform-test-net \
  -v /home/halil/platform-k8s-gitops/scripts/migration/etl_worker/config:/app/config:ro \
  --env-file /home/halil/platform/env/backend.env \
  etl-worker:dr-6-readiness inspect-source --tables COMPANY
```

**Result**:
```text
{"tables": "COMPANY", "event": "inspect.start", "level": "info", "timestamp": "2026-04-28T07:02:08.103259Z"}
FAIL: MSSQL connection error: ('28000', "[28000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Login failed for user 'AlUser_App'. (18456) (SQLDriverConnect)")
```

**Diagnosis**: The MSSQL user `AlUser_App` from `backend.env` is rejected by Workcube MSSQL with SQL Server error 18456 (login failed). Possible causes:

1. Password rotated on Workcube side without backend.env update.
2. User account locked or disabled on Workcube side.
3. Network reach is fine (proxy 172.19.0.8:11433 alive; the error came from the SQL Server itself, not connection-refused) — credential issue specifically.

**Operator action required**: refresh MSSQL credentials in `backend.env` (and re-sync to Vault for the running services per the existing Faz 19.MSSQL operator runbook), OR confirm `AlUser_App` is still the intended ETL user and obtain working password.

**Verdict**: FAIL — user-side credential refresh blocks the runbook.

## Build pipeline status

- **Dockerfile fix landed in this PR**: `scripts/migration/etl_worker/Dockerfile` updated to use `[signed-by=...]` apt-source format compatible with Debian 12 Bookworm/Trixie sqv-based signature verification. Pre-fix attempt failed with `Failed to parse keyring 'microsoft-prod.gpg': No such file or directory` at apt-get update.
- **Build now works**: `docker build -t etl-worker:dr-6-readiness .` → `Successfully built 651b8cb61ff6`.
- **Image runs**: `docker run --rm etl-worker:dr-6-readiness --help` → 6 commands listed (inspect-source, reconcile, rejects, run, status, validate-manifest).

## What unblocks DR-6 Step 2

1. **MSSQL credential refresh** (operator side): rotate `AlUser_App` password on Workcube side, update `/home/halil/platform/env/backend.env`, restart any running services that consume it (per existing Faz 19.MSSQL practice). OR confirm a different ETL user.
2. **Re-run** `docker run --rm ... inspect-source --tables COMPANY` → expect row count > 0 from Workcube source.
3. **Then**: `docker run --rm ... run --mode initial --tables COMPANY --limit 1` (= DR-6 runbook Step 2, user-approval gate per ADR-0010 §2.5).

## D35 ladder declaration

This evidence file is **pre-flight readiness for DR-6**, not a D35-X tier capture. It does NOT advance any D35 tier. It surfaces the prereq state for the user to make the Step 2 approval decision.

- [ ] D35-0 — runtime preflight: not touched
- [ ] D35-1 — scope anchor prereq: blocked by MSSQL credential refresh (this readiness check)
- [ ] D35-2 — scoped grant/revoke E2E: depends on D35-1
- [ ] D35-3 — product path: depends on D35-2

## References

- DR-6 PR: #200 (`docs/RB-faz-16-2-A-scope-anchor-load.md`, MERGED `fed95c92`)
- ADR-0010 §2.4 (Faz 16.2.A authority), §2.5 (operator-approval matrix)
- Codex thread `019dd2c9`
- Existing Faz 19.MSSQL operator runbook (for credential refresh pattern)

## Verdict

**Pre-flight verdict**: READINESS PARTIAL.

- Build pipeline: ✓ READY (Dockerfile fix landed)
- Manifest: ✓ READY (4 anchor tables, syntax valid)
- MSSQL connectivity: ✗ BLOCKED (credential refresh required, operator side)

Once MSSQL credentials refreshed → DR-6 runbook Step 2 ready for user-approval.

Completed: 2026-04-28T07:05:00Z
