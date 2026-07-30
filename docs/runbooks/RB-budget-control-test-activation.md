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

## Machine-enforced source boundary

The namespace baseline already supplies the policies; adding another
service-local allow policy would not narrow them because Kubernetes
NetworkPolicy rules are additive. The effective TEST boundary is:

- `default-deny-egress` selects every pod;
- `allow-egress-dns` selects `app.kubernetes.io/part-of=platform` and permits
  only TCP/UDP `53` to kube-dns;
- `allow-egress-host-bridge` selects the same label and permits the runtime
  dependency ports, including PostgreSQL `5432`, but not MSSQL `1433` or SMB
  `445`;
- `allow-egress-workcube-mssql` permits `10.9.193.201:1433` only when
  `app.kubernetes.io/name` is `report-service` or `schema-service`.

`budget-service` carries `app.kubernetes.io/part-of=platform` so it can resolve
DNS and reach PostgreSQL, but its name is deliberately absent from the
Workcube policy. Its ConfigMap contains no MSSQL/SMB address and its
ExternalSecret can materialize only the two PostgreSQL login fields.

`tests/governance/test_budget_service_source_boundary.py` fails if any of
these selectors, ports, source credentials, or TEST-only placement drift. The
runtime negative probe in the acceptance steps remains mandatory because a
rendered policy is not proof of CNI enforcement.

## Immutable artifacts

| Workload | Source commit | Immutable image |
|---|---|---|
| `budget-service` | `platform-backend@a7f03762f22c214ff9ce3f7535c10e32520c7c0e` | `ghcr.io/halildeu/platform-backend-budget-service@sha256:5b992fb8a30cb44085d4da3de5fc33222bbf8efd8e5f92870b3d40c2375cccdc` |
| `report-service` | `platform-backend@3de6e35998f0bfe46413886447c7284ae2c34093` | `ghcr.io/halildeu/platform-backend-report-service@sha256:ba5621b79cfe899353101018691d66a4b5992a8ea0c2c775c199119bec8c166b` |
| `api-gateway` | `platform-backend@91520bca5775588f897227b90354c72cc0173512` | `ghcr.io/halildeu/platform-backend-api-gateway@sha256:244fff32b9e244dc6018c9db4b77cc3bca212216604675898074b9034a904599` |
| `frontend` | `platform-web@6664b3a9c8a7f3bae1202f1b98b7395a5eb07d15` | `ghcr.io/halildeu/platform-web-frontend-testai@sha256:d6ddbeead2bf1a58951495133ba1df822a16eef10c603ee058ab82533abe75a1` |

All four listed digests must be pulled successfully by the target TEST node before
promotion. A successful CI push alone is insufficient.

Latest accepted full-stack TEST baseline:

- GitOps merge: `9a5387615068863fe07b13e98a348c6f73babe33`;
- ArgoCD read-back: `Synced`, `Healthy`, operation `Succeeded`;
- the budget, report and gateway Deployments: `1/1 Ready`;
- each live backend pod `imageID`: exact corresponding backend digest from
  this table.

Latest accepted frontend grid follow-up:

- source: `platform-web@6664b3a9c8a7f3bae1202f1b98b7395a5eb07d15`;
- GitOps merge: `ac1457af85decf57c4fd1896725b70e22b295cfc`;
- `Deployment/frontend`: rollout complete, `1/1 Ready`, pod `imageID` exact
  frontend digest from this table;
- public `build-info.json`: exact full source SHA and image tag
  `sha-6664b3a`;
- browser acceptance: company `35`, project `44200`, stored PostgreSQL
  snapshot, shared Reporting grid and source-trace drawer passed;
- application-wide Argo status remains `OutOfSync / Degraded` because
  `meeting-service` is Degraded and `transcript-service` is OutOfSync. This
  unrelated residual is not a green full-application acceptance claim.

## TEST OAuth activation

Project actuals is a two-key authorization path. A token scope alone is not
authorization:

- read endpoints require both `budget:read` and realm role
  `budget-planner`;
- binding creation and source refresh require both `budget:write` and
  `budget-planner`;
- `budget:approve` and `budget-approver` are not granted to the planner
  persona.

The `frontend` client keeps `budget:read` and `budget:write` as optional client
scopes. The exact budget route requests them during a fresh Keycloak login;
they are not default scopes for every frontend user.

After the role-gated `budget-service` digest above is live, reconcile only the
TEST persona with the reviewed helper:

```bash
scripts/budget/provision-test-keycloak.sh --check
scripts/budget/provision-test-keycloak.sh --apply
scripts/budget/provision-test-keycloak.sh --check
```

The expected read-back is `budget-planner`, `budget:read` and `budget:write`
present; `budget:approve` absent; both budget scopes optional rather than
default. If acceptance must be rolled back, run the helper with `--rollback`;
it removes the persona role and optional client bindings but leaves inert
realm objects for audit. Never apply this helper before the backend role gate
is live.

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

The application source at
`platform-backend@91520bca:budget-service/src/main/resources/application.yml`
binds these exact environment names: `BUDGET_DB_URL`,
`BUDGET_DB_USERNAME`, `BUDGET_DB_PASSWORD`, and `BUDGET_DB_SCHEMA`.

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
10. As `admin@example.com`, company `35` and Workcube project `44200` can be
    selected by name/code. If no binding exists, the planner creates it and
    runs the first read-only sync for the selected date window.
11. The AG Grid shows the stored PostgreSQL snapshot with posting date,
    account, amount, cost treatment, source document type/number, resolution
    status, journal card/row and source action identifiers. Unresolved source
    documents remain unresolved; the UI does not invent a document link.
12. After a browser reload, selecting the same company, project and date
    window and using `Gerçekleşeni göster` returns the same snapshot row count,
    total and last successful sync timestamp without a new sync request.

## Accepted TEST evidence — company 35 / project 44200

The 2026-07-28 attended browser acceptance used `admin@example.com` and the
route-scoped planner contract. The token projection contained
`budget:read`, `budget:write` and `budget-planner`; it did not contain
`budget:approve` or `budget-approver`. No OpenFGA tuple was changed.

Observed customer journey:

1. Company and project selectors were alphabetic; `Serban Construction`
   (company `35`) and `IDC1` (external project `44200`) were selected by their
   visible names and code.
2. The missing binding state returned the intended `404` UI rather than a
   masked `403`. The planner created the binding and started the first sync.
3. The read-only source run read `7,842` rows, updated `7,842` snapshot rows,
   invalidated `0`, retained `7,839` active rows and returned reconciliation
   `MATCHED`.
4. The Budget AG Grid rendered source classifications including invoice, bank,
   expense and unresolved/other records. The full accounting detail surface
   returned all `7,842` rows.
5. Double-clicking a row opened the source-chain drawer. It exposed the
   accounting-row, journal-card and natural source-reference chain plus
   optional order/invoice/transfer identifiers without inventing missing
   relationships.
6. After a full navigation reload, `Gerçekleşeni göster` issued only the
   binding, summary and actuals read requests. It returned the same row count,
   accounting total, last-sync timestamp and `MATCHED` result without invoking
   a sync endpoint.

Do not store raw document descriptions, counterparties, document numbers or
other live accounting PII in acceptance evidence. Counts, status, artifact
identity and relationship classifications are sufficient.

This evidence accepts the actuals snapshot and source-trace slice. It does not
accept cost-rule classification, AI coding, plan budget, maker-checker approval
or production rollout. At this observation all `7,839` active rows remained in
the review bucket with zero classified cost.

## Accepted TEST follow-up — shared Reporting grid

The 2026-07-30 browser follow-up reused the stored company `35` / project
`44200` PostgreSQL snapshot and did not invoke an ERP refresh.

1. The actuals table uses the shared `EntityGridTemplate` with stable grid id
   `reports.budget-project-actuals`.
2. The standard quick search, grouping, advanced filter, filter reset, saved
   variants, fullscreen, Excel/CSV export and shared pagination controls were
   present.
3. The grid resolved to `data-access-state=full`; the grid root, quick search
   and standard toolbar controls all had computed opacity `1`.
4. Quick search reduced the bounded `2,000`-row view to `246` matching rows;
   filter reset restored the `2,000`-row view.
5. A row opened the Accounting, Cost classification and Source document trace
   sections. Raw document numbers, counterparties and transaction identifiers
   were excluded from recorded evidence.
6. A browser reload and repeat company/project selection returned the same
   `7,842` total and `7,839` active-row snapshot without a new sync request.
7. The standard grid is not an edit surface: no editable column or cell editor
   is configured. Removing the presentation-only `readonly` opacity state does
   not grant a backend, ERP or authorization write capability.

Artifact and acceptance references:

| Evidence | Result |
|---|---|
| platform-web PRs | `#1087`, `#1088` |
| frontend source and TEST digest | `6664b3a9c8a7f3bae1202f1b98b7395a5eb07d15` / `sha256:d6ddbeead2bf1a58951495133ba1df822a16eef10c603ee058ab82533abe75a1` |
| image build | platform-web run `30533252683` |
| TEST desired state | GitOps PR `#3192`, merge `ac1457af85decf57c4fd1896725b70e22b295cfc` |
| exact frontend runtime | rollout run `30533724383`: Deployment and pod digest pass |
| browser journey | shared grid, search/reset, source drawer and reload persistence pass |
| first residual gate | overall Argo application `OutOfSync / Degraded` on non-frontend `meeting-service` and `transcript-service` |

`platform-web#1046`, `#3007` and parent `#3005` remain open / In Progress until
their broader acceptance is deliberately reconciled. No production promotion
is implied by this TEST follow-up.

Before rollout, read the live `platform-quota` again. The 2026-07-27
preflight showed `limits.cpu=13350m/16`, `requests.memory=6960Mi/12Gi`,
`pods=26/34`, `services=33/40`, `secrets=36/44`, and
`configmaps=28/35`; this is enough for the declared `500m` CPU limit and
`192Mi` memory request, but it is a point-in-time observation rather than a
future reservation.

The first slice exposes the standard Prometheus actuator endpoint but does not
add a ServiceMonitor. Alerting and a product-specific operational dashboard
are an explicit post-acceptance observability slice; health/readiness and the
customer journey are not allowed to depend on that follow-up.

The gateway image contains the budget route. Do not promote that gateway
digest to PROD while the PROD budget upstream remains deferred. A future PROD
promotion must add the upstream and route atomically or use a gateway artifact
without the route.

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

The current frontend artifact is the thin `mfe-reporting` workspace from
`platform-web@09dfa606`; it does not make the browser the budget data
authority. AI proposal review reuses this workspace or an operator/API flow;
it does not authorize a new standalone frontend in this slice.

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
