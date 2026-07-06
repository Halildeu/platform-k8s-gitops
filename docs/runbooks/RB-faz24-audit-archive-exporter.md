# RB — audit-archive-exporter + retention alerts (Faz 24 PR-obs-02, gitops#1656)

> Companion to [RB-faz24-minio-audit-archive.md](RB-faz24-minio-audit-archive.md)
> (worker storage) and ADR-0042 §4 (observability). Issue gitops#1656; Codex
> plan-time consult `019ed602` (REVISE→AGREE). Cross-AI review thread recorded in
> the PR Cross-AI block.
>
> **Why this exists:** `audit-retention-worker` is a run-once daily CronJob, so its
> in-process Micrometer counters are EPHEMERAL — Prometheus can't scrape a ~30s
> job. `audit-archive-exporter` (prometheus-community `postgres_exporter`, custom
> queries, default collectors disabled) turns the **durable** `audit_archive.*` DB
> state into scrapeable gauges; the `audit-retention-worker` PrometheusRule alerts
> on those + on kube-state-metrics Job/CronJob lifecycle.

## Architecture (test plane)

```
audit-retention-worker CronJob (03:00) ──writes──▶ audit_archive.{cursor,ledger,tenant_anchor}
                                                     (host-compose Postgres, DB audit_event)
                                                            │ SELECT (read-only role)
audit-archive-exporter (k3d-test, part-of=platform) ──┘  postgres:5432  (Endpoints 172.19.0.6)
   │ :9187 /metrics  (custom queries: audit_archive_state_* + audit_archive_ledger_*)
   ▼ ServiceMonitor (monitoring ns scrape)
Prometheus ──▶ PrometheusRule audit-retention-worker (lag / job-failed / cronjob / ledger / exporter health)
            └▶ alertmanager-bridge → GitHub issue
```

- Pod label `app.kubernetes.io/part-of=platform` (redis-streams-exporter parity) →
  inherits the shared `allow-egress-host-bridge` (PG reachable) + `allow-monitoring-scrape`
  (port 9187 added). It only ever connects to the host Postgres; the DB blast radius is
  bounded at the **role layer** (dedicated read-only `audit_archive_exporter`), not the
  network layer. (`part-of=audit-archive` would give tighter egress but is incompatible
  with the PR-time drift Check 5, which only scopes `part-of=platform` Deployments — a
  catalog-enabled Deployment must be platform-scoped; Codex `019ed602`.)
- Metrics are derived from DB state, so they survive the CronJob exiting. They are
  named distinctly from the worker's in-process `audit_archive_*` counters
  (namespaced `audit_archive_state_*` / `audit_archive_ledger_*`).

## Activation gate (operator — the ONE prerequisite to go live)

> Shared `platform-pg-test` — same gate class as the worker D-slice (#1655). Until
> this is done, `pg_up=0` / `AuditArchiveExporterDBUnreachable` is **EXPECTED**, not
> a regression. The `audit_archive.*` tables exist only after the worker's first
> Flyway run, so until then the exporter's custom queries error (metrics absent) —
> the `ALTER DEFAULT PRIVILEGES` below makes the SELECT grant cover those future
> tables. Run order does not matter; the grants are empty-safe + future-safe.

### 1. Dedicated read-only DB role + least-privilege grants

> Run as a Postgres superuser on the host. Password generated locally
> (alphanumeric — no URL-encoding surprises in the exporter DSN); **never echoed**.

```bash
ssh halil@staging-sw '
PW=$(LC_ALL=C tr -dc "A-Za-z0-9" </dev/urandom | head -c 32)
docker exec -i -e PW="$PW" platform-pg-test psql -U postgres -d audit_event -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '\''audit_archive_exporter'\'') THEN
    CREATE ROLE audit_archive_exporter LOGIN;
  END IF;
END \$\$;
ALTER ROLE audit_archive_exporter WITH PASSWORD '\''$PW'\'';
GRANT USAGE ON SCHEMA audit_event, audit_archive TO audit_archive_exporter;
GRANT SELECT ON audit_event.audit_event TO audit_archive_exporter;
GRANT SELECT ON ALL TABLES IN SCHEMA audit_archive TO audit_archive_exporter;            -- existing (empty-safe)
ALTER DEFAULT PRIVILEGES FOR ROLE audit_retention_worker IN SCHEMA audit_archive
  GRANT SELECT ON TABLES TO audit_archive_exporter;                                       -- future worker-created tables
SQL
# 2. Vault seed (stdin/env; values redacted from stdout)
VT=$(jq -r .root_token ~/bootstrap-drill/vault-init-test.json)
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" -e U="audit_archive_exporter" -e PW="$PW" platform-vault-test \
  sh -c '\''vault kv put kv/platform/audit-archive-exporter db_username="$U" db_password="$PW"'\''
echo "seeded audit_archive_exporter (pw_len=${#PW})"   # value redacted
'
```

> NOTE: `audit_archive.*` is OWNED by `audit_retention_worker`, so the
> `ALTER DEFAULT PRIVILEGES FOR ROLE audit_retention_worker` clause is what makes
> the worker's *future* Flyway-created tables SELECT-able by the exporter. If the
> worker role name differs, adjust accordingly.

### 3. gitops apply (selective)

```bash
kubectl --context k3d-test apply -k kustomize/overlays/test/eso          # audit-archive-exporter-secrets (ESO)
kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test   # exporter Deploy/Svc/CM + SM + NetPol
kubectl --context k3d-prod apply -k kustomize/base/monitoring            # PrometheusRule (inert in prod; whichever cluster scrapes)
kubectl --context k3d-test -n platform-test rollout status deploy/audit-archive-exporter --timeout=120s
```

## D29 smoke (Up / Functional / Secured)

```bash
# Up — pod Running + scrape target healthy
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=audit-archive-exporter -o wide
#   PromQL: up{job="audit-archive-exporter"} == 1

# Functional — DB reachable + custom metrics present (after worker first Flyway)
kubectl --context k3d-test -n platform-test exec deploy/audit-archive-exporter -- \
  wget -qO- http://localhost:9187/metrics | grep -E '^pg_up|^audit_archive_state_|^audit_archive_ledger_'
#   Expect: pg_up 1, audit_archive_state_cursor_seq, audit_archive_state_lag_seconds,
#           audit_archive_state_hot_window_seconds 7776000, audit_archive_ledger_segment_count, ...

# Secured — the boundary is the dedicated READ-ONLY DB role + monitoring-only scrape
# ingress (network egress is the shared platform posture, NOT the boundary). Post-
# activation, confirm the role is SELECT-only — a write MUST be denied:
ssh halil@staging-sw 'docker exec -i platform-pg-test psql -U audit_archive_exporter -d audit_event \
  -c "INSERT INTO audit_archive.audit_archive_cursor VALUES (0, now());"'   # expect: ERROR: permission denied
#   Scrape ingress: allow-monitoring-scrape opens :9187 only from the monitoring namespace.
```

## Alert response

| Alert | Severity | First action |
|---|---|---|
| `AuditArchiveRetentionLagHigh` (>26h) | warning | Did 03:00 run happen? `kubectl -n platform-test get jobs -l app.kubernetes.io/name=audit-retention-worker`; check the latest Job's logs. |
| `AuditArchiveRetentionLagCritical` (>50h) | critical | 2+ windows missed. Worker fail-closed (chain-break/anomaly) or not running — inspect Job logs; data accumulating un-archived (WORM SLA risk). |
| `AuditRetentionWorkerJobFailed` | critical | Fail-closed: cursor frozen, no archive written. `kubectl -n platform-test logs job/<name>` — chain-break tenant? S3 anomaly? DB? Fix root cause; the next schedule retries. |
| `AuditRetentionCronJobNotScheduling` (>26h) | warning | `kubectl -n platform-test get cronjob audit-retention-worker` — suspended, or schedule stopped after ≥1 prior run? (a deleted/never-scheduled CronJob does NOT fire this — absent-free; GitOps/ArgoCD drift catches deletion.) |
| `AuditArchiveLedgerUnverified` (>0) | critical | NOT a normal chain-break (that leaves no ledger row). DB invariant violation / tampering / regression — inspect the ledger row + its S3 object-version. |
| `AuditArchiveExporterDown` | warning | Metrics endpoint unreachable — visibility loss, not data loss. Check the exporter pod. |
| `AuditArchiveExporterDBUnreachable` (`pg_up=0`) | warning | EXPECTED before the activation gate above. After seed: check the role/password (Vault `kv/platform/audit-archive-exporter`), ESO sync, and the NetPol→PG path. |
| `AuditArchiveExporterScrapeError` (`pg_exporter_last_scrape_error!=0`) | warning | Connected but a custom query errored (audit_archive_* series missing → lag/ledger blind). EXPECTED before the grant + worker first-Flyway complete. After activation: a grant/schema/query error — check the role's SELECT on audit_event.audit_event + audit_archive.* and that the worker's Flyway ran. |

## Rollback

- The exporter + rule are additive + test-only; rollback = revert the PR (the
  `audit_archive_*` series + `up{job="audit-archive-exporter"}` simply disappear →
  every alert goes inert; `absent()` is intentionally NOT used so nothing fires).
- Do NOT scale the exporter to 0 (HARD RULE: test scale-to-zero YASAK). To stop
  scraping without a revert, delete the ServiceMonitor only.
- To revoke DB access: `DROP ROLE audit_archive_exporter;` (after removing the
  Deployment) + `vault kv delete kv/platform/audit-archive-exporter`.

## References

- ADR-0042 §4 (observability), §D4.2 (contiguous-prefix cursor), §D4.3 (cursor updated_at semantics).
- Worker: kustomize/base/apps/audit-retention-worker/ (#1250-D, #1655).
- Exporter: kustomize/base/apps/audit-archive-exporter/ + overlays/test/eso/audit-archive-exporter/ (part-of=platform → shared allow-egress-host-bridge + allow-monitoring-scrape:9187).
- Rule: kustomize/base/monitoring/audit-retention-worker-rule.yaml.
- Precedent: redis-streams-exporter (gitops#1247) + stt-pipeline-rule.yaml (absent()-free discipline).
