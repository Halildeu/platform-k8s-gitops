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
2. Direct Codex review has a valid `AGREE` receipt bound to the current exact
   head, live-refreshed base ref/base-tip, recomputed merge-base and canonical
   scope hash. After a `REVISE`, all of these values are derived again from the
   post-fix commit; an older receipt is invalid. A usage-limit error remains
   `tracked_pending` and does not authorize merge/deploy. #2688, Faz 22.6 and
   their handoffs are not Faz 35 activation dependencies. This is the newer,
   binding product-owner decision; until #2688 reaches `main`, stale
   Claude-first repository text is not applied to Faz 35 and no Claude receipt
   is requested. Test/CI/live evidence and real human or production gates remain
   independent and cannot be replaced by this review.
3. Backend, public-web and the dedicated `platform-web-etik-speak-manager`
   workflows published immutable image digests from their exact source heads.
   The shared `platform-web-frontend-testai` digest remains unchanged.
4. The public image pinned-container smoke proves `/healthz`, CSP,
   `Referrer-Policy: no-referrer`, and `Cache-Control: no-store`.
5. The GitOps activation overlay contains no all-zero digest and renders with
   no `OVERLAY_MUST_OVERRIDE` value; the same overlay pins the dedicated
   manager image while the root shared frontend stays on its prior reviewed
   digest. `PENDING_FAZ35_*` values are allowed
   only in the provisioning-stage review and block activation preflight.

## Gate 2: test product-cell provisioning

Run on `staging-sw` from the reviewed GitOps checkout. The scripts are
test-only and fail closed if pointed at other containers, namespace, or
context.

First run the read-only preflight from the reviewed local checkout:

```bash
PREFLIGHT_STAGE=foundation ./scripts/faz35/preflight-test-activation.sh
```

It binds the current host-container IPs to the Kubernetes Endpoints and the
reviewed NetworkPolicy, verifies ESO/OpenFGA availability, checks the external
Sectigo wildcard TLS path for both public hosts, renders the immutable
activation, and reports whether the root overlay/live resource set is still
inactive. It also requires object-count quota for the six-pod rollout peak of
the three deployments plus a bounded repair reserve; an exact-fit quota is
rejected because it would block rollback or recovery resources. The test overlay raises only the
test object ceilings to `services=40`, `secrets=44`, `pods=34`, and
`configmaps=35`; production quota is unchanged. The cluster TLS Secret may be
absent because TLS terminates at the
canonical host edge; `docs/S5-cert-renewal-runbook.md` defines it as optional
when cluster TLS termination is not used. A valid edge certificate and
authoritative public request remain mandatory.

The public production-named hosts remain protected by a dedicated synthetic
test Basic Auth gate until the separate production/legal change. ingress-nginx
consumes that credential and removes `Authorization` before proxying the public
API, then overwrites `X-Etik-Speak-Transport: https`. The ethics backend rejects
public mutations without that exact transport proof, and its NetworkPolicy
admits only the ingress namespace. This prevents uninvited real reports while
preserving the application's bearer/cookie credential-confusion boundary.

```bash
./scripts/faz35/provision-test-pg-vault.sh
./scripts/faz35/provision-test-keycloak.sh
docker exec platform-kc-test cat /run/secrets/kc_admin_password | \
  ./scripts/faz24/repair-d35-permission-writer-credential.sh \
    --keycloak-admin-password-stdin --pre-identity-credential-only
docker exec platform-kc-test cat /run/secrets/kc_admin_password | \
  ./scripts/faz35/reconcile-test-permission-writer-identity.sh \
    --keycloak-admin-password-stdin
./scripts/faz35/provision-test-ethic-entitlement.sh
```

The credential-only repair first proves or rotates the exact writer login while
accepting only its known pre-reconciliation identity (`1204`) or dedicated
identity (`12`); it does not use that identity to mutate permission state. The
identity reconciliation then binds the writer to local synthetic user `12`,
preserves historical user `1204`, grants only `ACCESS=MANAGE`, and proves the
fresh-token exact projection before the entitlement provisioner runs. Both
scripts disable tracing and validate the TEST Keycloak container, loopback port
and issuer before reading the admin secret through their explicit stdin
contract.

The Keycloak script prints a non-secret `ETHICS_STAFF_SUBJECT=<uuid>` line and
stores the dedicated allow, wrong-org and OpenFGA-denied synthetic persona
passwords in the chmod-600 paths reported by the script. The PG/Vault script
prints only the public-gate username, its chmod-600 local password-file path,
and the dedicated Etik Speak Vault AppRole's non-secret role ID. It creates a
namespaced Kubernetes secret for that AppRole; the role can read only
`kv/platform/etik-speak` and cannot use the broad shared ClusterSecretStore.
The entitlement script uses the existing test permission-writer credential only
from its Vault document and writes through permission-service's canonical
role/granule/member APIs. It creates or reconciles the dedicated
`ETIK_SPEAK_MANAGER` role to exactly `MODULE:ETHIC:MANAGE` and assigns all three
synthetic manager personas. It then proves the same narrow `/authz/me`
prerequisite for each; tenant isolation and explicit deny are exercised only at
the downstream org/OpenFGA layer. Raw credentials, bearer
tokens, email and numeric user IDs remain in mode-600 temporary files and are
never emitted.
Every password file must be regular, non-symlink, owned by the invoking user
and inaccessible to group/other users. Do not paste a password or AppRole
secret ID into chat, GitHub, logs, shell argv, or an evidence document.

Use the printed subject to promote the isolated OpenFGA model and seed only the
allow-persona product relations:

```bash
STAFF_SUBJECT='<allow-uuid-from-keycloak-step>' \
WRONG_ORG_SUBJECT='<wrong-org-uuid-from-keycloak-step>' \
DENIED_SUBJECT='<denied-uuid-from-keycloak-step>' \
  ./scripts/faz35/provision-test-openfga.sh
```

The OpenFGA provisioner does not trust these caller-supplied UUIDs by format.
Immediately before its first OpenFGA write it reauthenticates all three fixed
synthetic users from their mode-600 password files against the exact loopback
`platform-kc-test` issuer, then requires the token subject, username and org to
match the corresponding allow, wrong-org and denied binding. Swapped or stale
UUIDs therefore fail before any tuple is written.

Expected non-secret results:

- PostgreSQL role `ethics_app`: LOGIN and no admin attributes;
- database `ethics`, owned by `ethics_app`;
- rerunning the PG/Vault provisioner reuses the existing Vault-managed DB
  password instead of rotating it underneath an active ESO/workload;
- Vault `kv/platform/etik-speak`: public edge htpasswd hash, while the raw gate
  password remains only in the reported host-local file;
- a dedicated `etik-speak-eso-test` read-only Vault policy/AppRole and
  `platform-test/etik-speak-vault-approle` Kubernetes Secret;
- Keycloak access token contract: `aud` includes `ethics-manager`, `scope`
  includes `ethics:case:manage`, the realm role includes `ethics-manager`, and
  `org_id` matches the persona's test tenant;
- permission-service `/authz/me` returns the same exact `ETHIC=MANAGE` and no
  other authority for all three synthetic managers, so wrong-org and denied
  requests reach the tenant/OpenFGA checks instead of stopping at suite 403;
- OpenFGA checks return allow for product `case_viewer`, `case_triager`, and
  `case_handler` for the synthetic manager subject.

The provisioners print three non-secret bindings:

- `ETHICS_VAULT_ROLE_ID`;
- `ETHICS_OPENFGA_STORE_ID`;
- `ETHICS_OPENFGA_MODEL_ID`.

Create a new GitOps commit that replaces the three `PENDING_FAZ35_*` values in
`secretstore.yaml` and `ethics-service-config.yaml`. Update the OpenFGA runtime
ledger with the actual test store/model ID, canonical digest and evidence.
Then derive a new exact head/base-tip/merge-base/canonical scope and obtain a
fresh direct-Codex `AGREE`; the provisioning-stage receipt cannot authorize
activation. Finally run the full read-only preflight:

```bash
./scripts/faz35/preflight-test-activation.sh
```

Vault root tokens, DB passwords, Keycloak automation credentials and the
synthetic manager password travel over stdin to their short-lived container
processes. They must not be moved into `docker exec -e NAME=value`, shell argv,
GitHub evidence, or command tracing during activation.

## Gate 3: desired-state activation

In the GitOps PR:

1. Verify backend and public digests in
   `kustomize/overlays/test/activation/etik-speak/kustomization.yaml` against
   their exact reviewed source heads.
2. Pin the exact reviewed `platform-web-etik-speak-manager` digest in the Faz 35
   activation overlay and verify the shared `platform-web-frontend-testai`
   digest did not change.
3. Add `activation/etik-speak` to the root test overlay resources.
4. Render the root test overlay and run the repository CI gates.
5. Merge only after the exact-head review receipt and normal CI are valid.
6. Let ArgoCD reconcile; do not apply the activation directory selectively.

### Fail-closed TEST deactivation and rollback

`platform-test` intentionally uses `prune: false`. Removing
`activation/etik-speak` from the root overlay therefore is **not** a rollback:
the last-applied Deployments and Ingresses would remain live but unmanaged.

Rollback uses a reviewed GitOps fix-forward commit instead:

1. Replace the root resource `activation/etik-speak` with
   `deactivation/etik-speak`; restore a prior reviewed dedicated manager digest
   in the same commit only when manager artifact rollback is required.
2. Render the root TEST overlay, run normal CI, derive a fresh exact scope and
   obtain the required exact-head review before merge.
3. Let normal ArgoCD self-heal update the same object identities. The
   deactivation overlay retains every object under GitOps ownership, sets all three
   product Deployments to `replicas: 0`, and replaces all public/staff Ingress
   hosts with DNS-reserved `.invalid` names. It does not depend on pruning.
4. Verify desired/live replicas are zero, `etik.acik.com`, `speakup.acik.com`
   and the `testai.acik.com` staff API no longer match a Faz 35 Ingress, and
   record the ArgoCD revision. Cleanup/deletion, if later desired, is a separate
   controlled change after this fail-closed tombstone is live.

Never roll back by only deleting the root resource line, and never use direct
`kubectl patch`, `set image`, `edit` or workload apply for deactivation.

After reconciliation, verify ExternalSecret and immutable image identity:

```bash
kubectl --context k3d-test -n platform-test get externalsecret \
  ethics-service-secrets etik-speak-public-gate
kubectl --context k3d-test -n platform-test get deploy \
  ethics-service etik-speak-public etik-speak-manager
kubectl --context k3d-test -n platform-test get pods \
  -l app.kubernetes.io/part-of=etik-speak \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
```

Also record the dedicated manager deployment image identity. A healthy shared
suite shell is not Etik Speak manager acceptance:

```bash
kubectl --context k3d-test -n platform-test get pods \
  -l app.kubernetes.io/name=etik-speak-manager \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
kubectl --context k3d-test -n platform-test exec deploy/etik-speak-manager -- \
  sha256sum /usr/share/nginx/html/ethic/index.html
```

Backend, public UI and manager pod `imageID` values must match the reviewed
digests, and the manager entrypoint hash must be recorded against the same immutable
image. `Up` alone is not functional acceptance.

The ES-1 manager is intentionally an isolated SPA, not the shared suite shell.
Its trusted source workflow must bind the exact source head and image digest
while passing the Keycloak check-sso/PKCE smoke and the source tests that require
the audience + scope + realm-role triple, reject caller-supplied Cookie/Bearer
headers and unmount protected content on logout, refresh error or API `401/403`.
GitOps preflight verifies that source/workflow/SLSA binding; Gate 4 then proves
the same boundary against the running TEST environment, including wrong-org and
OpenFGA-denied personas. Neither source tests nor attestation replace Gate 4.

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
6. Prove missing Basic Auth denial, Basic Auth stripping at the backend,
   cross-host mailbox login denial, public suite-cookie confusion denial,
   wrong-org staff isolation, live OpenFGA allow/deny plus source-level outage
   fail-closed behavior, stale `If-Match` `412`, same-payload replay and
   different-payload idempotency conflict. Both hosts must emit one-year HSTS.

The canonical browser driver lives in `platform-web` and reads both synthetic
gate passwords only from host-local chmod-600 files. It validates regular-file,
non-symlink, owner and mode boundaries before reading them. It disables trace,
video and screenshots so a receipt/access secret cannot enter CI artifacts:

```bash
ETIK_MANAGER_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-test.password \
ETIK_WRONG_ORG_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-wrong-org-test.password \
ETIK_DENIED_PASSWORD_FILE=/home/halil/bootstrap-drill/ethics-manager-denied-test.password \
ETIK_PUBLIC_GATE_PASSWORD_FILE=/home/halil/bootstrap-drill/etik-speak-public-gate.password \
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
