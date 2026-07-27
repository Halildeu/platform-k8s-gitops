# Budget Control — TEST activation and acceptance

## Product boundary

`budget-service` is an independently deployable Budget and Cost Control
product service. It owns its PostgreSQL data and lifecycle:

- budget plans, versions and lines;
- maker-checker submission and approval;
- actual allocations, commitments and forecasts;
- reconciliation and append-only audit events.

The thin reporting workspace is only a client. It is not the product's data
authority. Workcube MSSQL and SMB are source systems and remain read-only; this
workload receives no Workcube or SMB credential and cannot use the dedicated
MSSQL NetworkPolicy assigned to `report-service` and `schema-service`.

Production is deferred. This runbook applies only to `k3d-test` /
`platform-test`.

## Immutable artifacts

| Workload | Source commit | Immutable image |
|---|---|---|
| `budget-service` | `platform-backend@91520bca5775588f897227b90354c72cc0173512` | `ghcr.io/halildeu/platform-backend-budget-service@sha256:ee667af00d7e326e0d0b771c09f4cc0efb8696ff27dbac8b367d06862b2d3dbe` |
| `api-gateway` | `platform-backend@91520bca5775588f897227b90354c72cc0173512` | `ghcr.io/halildeu/platform-backend-api-gateway@sha256:244fff32b9e244dc6018c9db4b77cc3bca212216604675898074b9034a904599` |
| `frontend` | `platform-web@09dfa606268b7aebd318658d3c83177a3e4db419` | `ghcr.io/halildeu/platform-web-frontend-testai@sha256:8efd33406ae98196e92ef9cfcf7cf15d8e8475cdd2be62839253f44660fa4a52` |

All three digests must be pulled successfully by the target TEST node before
promotion. A successful CI push alone is insufficient.

## PostgreSQL and Vault provisioning

The application role must be:

```text
budget_service
LOGIN
NOSUPERUSER
NOBYPASSRLS
NOCREATEDB
NOCREATEROLE
NOREPLICATION
```

The `budget` database is owned by this role so Flyway can create and evolve the
`budget_service` schema. The application additionally refuses to start if its
runtime role is superuser or has `BYPASSRLS`.

After this GitOps change is merged, reconcile the reviewed TEST Vault policy
from the canonical checkout and mint a short-lived writer credential:

```bash
scripts/ops/vault-policy-reconcile.sh \
  --emit-seed-secret-id platform-bootstrap-writer-test
```

Generate a new random database password in the operator shell. Pass it to both
PostgreSQL and `scripts/ops/platform-ops-vault-patch.sh` through standard input;
never put the value in argv, shell history, GitHub, a log, or this runbook.
The Vault target is:

```text
kv/platform/budget-service
  db_username
  db_password
```

The writer wrapper invocation uses `--service budget-service` and two
`--field-from-stdin` inputs. Destroy the short-lived secret-id file after the
single seed operation. Do not use a Vault root token when the reconciler and
bootstrap-writer path are available.

Required read-back:

1. PostgreSQL role flags exactly match the restrictions above.
2. Vault reports both field names present without printing either value.
3. Authentication to database `budget` using the Vault-delivered identity
   returns `current_user=budget_service`.
4. `ExternalSecret/budget-service-secrets` is `Ready=True` and owns the
   resulting Kubernetes Secret.

## GitOps rollout

The shared TEST workload is changed only through
`kustomize/overlays/test`; no `kubectl set image`, `patch`, or `edit` is used.
ArgoCD must reconcile the saved merge commit.

Verify:

1. `Deployment/budget-service` is `Available=True`.
2. Pod `imageID` equals the budget digest in the table.
3. API gateway pod `imageID` equals the gateway digest in the table.
4. Frontend pod `imageID` equals the frontend digest in the table.
5. `/actuator/health/readiness` is healthy through the intended internal hop.
6. An unauthenticated `/api/v1/budgets` request is rejected.
7. An authenticated user without the requested company claim is rejected.
8. Company `35`, fiscal year `2026`: planner creates and submits a draft;
   a different authorized person approves it; PostgreSQL read-back shows the
   approved version and a subsequent edit returns conflict.
9. From a pod selected as `budget-service`, connections to the Workcube MSSQL
   address on `1433` and the ERP SMB address on `445` fail, while PostgreSQL
   `5432` succeeds.

## Rollback

Rollback reverts only the TEST desired-state image/resource changes to the
previous Git commit and lets ArgoCD reconcile. Do not drop the `budget`
database, revoke the Vault version, or delete approved budget records as part
of application rollback. Database state remains for diagnosis and forward
repair.

## AI cost coding follow-up

No additional UI is required for the first AI-assisted slice. The operator
gives Codex a bounded batch instruction; Codex reads only authorized source
records and submits proposal rows to `budget-service`.

The future contract is proposal-only:

- source identity, natural source reference and batch id;
- proposed cost/budget code, confidence and rationale;
- model id/version and prompt hash;
- idempotency key and triggering human identity;
- `PROPOSED`, `APPROVED`, `REJECTED`, `REVOKED` lifecycle.

The triggering person cannot approve the batch. AI is never an approver.
Before approval, a batch can be revoked as a whole. After approval, corrections
use compensating entries; hard deletion is not a financial rollback. Workcube
MSSQL and SMB writeback, autonomous approval, real-time CDC, model fine-tuning
and a large new frontend are explicitly outside this first slice.
