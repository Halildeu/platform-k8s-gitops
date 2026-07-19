# Faz 35 Etik Speak test activation runbook

## Scope and authority

This runbook activates only the synthetic `platform-test` product cell:

- reporter UI: `etik.acik.com` and `speakup.acik.com`, same immutable digest;
- staff UI: `https://testai.acik.com/ethic`;
- public/staff API: dedicated `ethics-service` routes;
- tenant: `00000000-0000-0000-0000-000000000001`.

It does not authorize production DNS, production secrets, `ai.acik.com`
activation, real reporter PII, or a destructive database operation. Workload
activation is GitOps-only through `kustomize/overlays/test`; direct
`kubectl patch`, `set image`, or `edit` is forbidden.

## Gate 1: source and artifact evidence

Before provisioning or root-overlay activation, record all of the following:

1. Backend and web source PR checks are green.
2. Direct Codex exact-head review has a valid `AGREE` receipt. A usage-limit
   error remains `tracked_pending` and does not authorize merge/deploy.
3. Backend, public-web and `platform-web-frontend-testai` workflows published
   immutable image digests from their exact source heads.
4. The public image pinned-container smoke proves `/healthz`, CSP,
   `Referrer-Policy: no-referrer`, and `Cache-Control: no-store`.
5. The GitOps activation overlay contains no all-zero digest and renders with
   no `OVERLAY_MUST_OVERRIDE` value; the root test overlay separately pins the
   exact manager/testai frontend digest.

## Gate 2: test product-cell provisioning

Run on `staging-sw` from the reviewed GitOps checkout. The scripts are
test-only and fail closed if pointed at other containers, namespace, or
context.

First run the read-only preflight from the reviewed local checkout:

```bash
./scripts/faz35/preflight-test-activation.sh
```

It binds the current host-container IPs to the Kubernetes Endpoints and the
reviewed NetworkPolicy, verifies ESO/OpenFGA availability, checks the external
Sectigo wildcard TLS path for both public hosts, renders the immutable
activation, and reports whether the root overlay/live resource set is still
inactive. The cluster TLS Secret may be absent because TLS terminates at the
canonical host edge; `docs/S5-cert-renewal-runbook.md` defines it as optional
when cluster TLS termination is not used. A valid edge certificate and
authoritative public request remain mandatory.

```bash
./scripts/faz35/provision-test-pg-vault.sh
./scripts/faz35/provision-test-keycloak.sh
```

The Keycloak script prints a non-secret `ETHICS_STAFF_SUBJECT=<uuid>` line and
stores the dedicated synthetic persona password in the chmod-600 path reported
by the script. Do not paste that password into chat, GitHub, logs, shell argv,
or an evidence document.

Use the printed subject to promote the isolated OpenFGA model, seed only the
test staff product relations, and patch the existing Vault selector fields:

```bash
STAFF_SUBJECT='<uuid-from-keycloak-step>' \
  ./scripts/faz35/provision-test-openfga.sh
```

Expected non-secret results:

- PostgreSQL role `ethics_app`: LOGIN and no admin attributes;
- database `ethics`, owned by `ethics_app`;
- rerunning the PG/Vault provisioner reuses the existing Vault-managed DB
  password instead of rotating it underneath an active ESO/workload;
- Vault `kv/platform/etik-speak`: DB keys plus OpenFGA store/model selectors;
- Keycloak access token contract: `aud` includes `ethics-manager`, `scope`
  includes `ethics:case:manage`, and `org_id` is the canonical test UUID;
- OpenFGA checks return allow for product `case_viewer`, `case_triager`, and
  `case_handler` for the synthetic manager subject.

Vault root tokens, DB passwords, Keycloak automation credentials and the
synthetic manager password travel over stdin to their short-lived container
processes. They must not be moved into `docker exec -e NAME=value`, shell argv,
GitHub evidence, or command tracing during activation.

## Gate 3: desired-state activation

In the GitOps PR:

1. Verify backend and public digests in
   `kustomize/overlays/test/activation/etik-speak/kustomization.yaml` against
   their exact reviewed source heads.
2. Pin the exact reviewed `platform-web-frontend-testai` digest in the root
   test overlay so `/ethic` contains ES-204; a public image does not prove this.
3. Add `activation/etik-speak` to the root test overlay resources.
4. Render the root test overlay and run the repository CI gates.
5. Merge only after the exact-head review receipt and normal CI are valid.
6. Let ArgoCD reconcile; do not apply the activation directory selectively.

After reconciliation, verify ExternalSecret and immutable image identity:

```bash
kubectl --context k3d-test -n platform-test get externalsecret ethics-service-secrets
kubectl --context k3d-test -n platform-test get deploy ethics-service etik-speak-public
kubectl --context k3d-test -n platform-test get pods \
  -l app.kubernetes.io/part-of=etik-speak \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
```

The two pod `imageID` values must match the reviewed digests. `Up` alone is not
functional acceptance.

## Gate 4: customer closed-loop acceptance

Use only synthetic content.

1. Open `https://etik.acik.com`, submit an anonymous report, and save the
   receipt/access secret before navigating away.
2. Repeat the public artifact/header check on `https://speakup.acik.com`; both
   hosts must serve the same bytes and image digest.
3. Sign in to `https://testai.acik.com/ethic` with the dedicated synthetic
   manager; confirm the new case is visible.
4. Add an internal note and a reporter-visible reply. The internal note must
   never appear in the reporter mailbox.
5. Reopen the mailbox on the original public host, read the staff reply, send a
   reporter reply, then log out and prove the expired host-only cookie no longer
   authorizes reads.
6. Prove cross-host mailbox login denial, public bearer/cookie credential
   confusion denial, wrong-org staff isolation, OpenFGA deny/outage behavior,
   stale `If-Match` `412`, and retry idempotency.

The canonical browser driver lives in `platform-web` and reads the synthetic
manager password only from a host-local chmod-600 file. It disables trace,
video and screenshots so a receipt/access secret cannot enter CI artifacts:

```bash
ETIK_MANAGER_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-test.password \
  pnpm test:e2e:etik-speak-runtime
```

Acceptance evidence is the running environment, the target reporter/staff
personas, the completed durable round trip, and the next actor reading the same
result. Source merge, CI, images, manifests, or screenshots alone are not
customer delivery.

## Rollback

Rollback is a reviewed GitOps revert to the previous immutable digests and/or
removal of the test activation resource. The database migration is additive;
do not drop the `ethics` database, schema, receipt grants, messages, or audit
outbox during rollback. OpenFGA model versions remain append-only. Production
workloads are not stopped by this runbook.
