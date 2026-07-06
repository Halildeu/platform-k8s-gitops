# Faz 22 endpoint-admin OpenFGA ESO migration evidence (2026-06-07)

Tracked by: platform-k8s-gitops#1267

## Summary

endpoint-admin no longer carries OpenFGA store/model identifiers as ConfigMap
pins. The service now follows the shared runtime-artifact selector already used
by permission-service/report-service/variant-service:

- Vault path: `kv/platform/openfga`
- Secret keys: `ERP_OPENFGA_STORE_ID`, `ERP_OPENFGA_MODEL_ID`
- Consuming Secret: `endpoint-admin-service-secrets`
- Runtime selector ledger:
  `runtime-artifacts/openfga-model/a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c.json`

This removes the stale test overlay model pin
`01KRTJVEMAW80B2D35GN8HJDPG` and moves endpoint-admin to the shared test model
selector (`01KS8QE8T1EJ2DF5CRS4VV9YX1` in the current runtime-artifact ledger).

## Source proof

Changed desired-state files:

- `kustomize/base/apps/endpoint-admin-service/configmap.yaml`
  - keeps `ERP_OPENFGA_ENABLED=true`
  - keeps `ERP_OPENFGA_API_URL=http://openfga:8080`
  - removes ConfigMap-carried `ERP_OPENFGA_STORE_ID` / `ERP_OPENFGA_MODEL_ID`
- `kustomize/overlays/test/eso/endpoint-admin/externalsecret.yaml`
  - adds `ERP_OPENFGA_STORE_ID <- kv/platform/openfga#store_id`
  - adds `ERP_OPENFGA_MODEL_ID <- kv/platform/openfga#model_id`
- `kustomize/overlays/prod/eso/endpoint-admin/externalsecret.yaml`
  - same selector pattern, with prod-specific Vault values expected
- `kustomize/overlays/test/kustomization.yaml`
  - removes the endpoint-admin ConfigMap patch to `01KRTJVEMAW80B2D35GN8HJDPG`
- `kustomize/overlays/prod/kustomization.yaml`
  - removes hard-coded endpoint-admin ConfigMap store/model IDs

The Deployment already lists `secretRef: endpoint-admin-service-secrets` after
the ConfigMap in `envFrom`, so the ESO-managed Secret is the source for the
runtime IDs.

## Compatibility proof

The shared test OpenFGA model `01KS8QE8T1EJ2DF5CRS4VV9YX1` is the promoted
runtime artifact for `kv/platform/openfga#model_id`. It is a superset of the
previous endpoint-admin pinned model for the ERP/module type surface: the
endpoint-admin gate checks `user:<id> can_manage module:endpoint-admin`, which
continues to use the same OpenFGA store and tuple namespace.

Prior live evidence already recorded endpoint-admin module allow/deny under the
shared model:

- `docs/faz-22-evidence/2026-05-24-allow-path-browser-smoke.md`
- `docs/faz-22-evidence/2026-05-24-be017-dual-control-matrix.md`
- `docs/state/current-state.md` live delta rows for `user:9999 can_manage module:endpoint-admin`

This PR does not introduce a direct OpenFGA tuple write path. Tuple changes
remain governed by permission-service / approved bootstrap discipline.

## Runtime verification path

After GitOps reconcile, verify the test cluster without exposing secret values:

```bash
kubectl --context k3d-test -n platform-test get externalsecret endpoint-admin-service-secrets
kubectl --context k3d-test -n platform-test get secret endpoint-admin-service-secrets \
  -o jsonpath='{.data.ERP_OPENFGA_MODEL_ID}' | base64 -d
kubectl --context k3d-test -n platform-test rollout status deploy/endpoint-admin-service --timeout=180s
kubectl --context k3d-test -n platform-test exec deploy/endpoint-admin-service -- printenv \
  | grep '^ERP_OPENFGA_\\(ENABLED\\|API_URL\\|STORE_ID\\|MODEL_ID\\)='
```

Expected model in test: `01KS8QE8T1EJ2DF5CRS4VV9YX1`.

Then run an endpoint-admin persona smoke that checks:

- allow: `user:<admin-id> can_manage module:endpoint-admin`
- deny: no-tuple user cannot manage `module:endpoint-admin`

## Boundary

This is a GitOps desired-state and runtime selector provenance change. It does
not prove domain pilot readiness, 24h soak, SMB/file actions, or software
install/uninstall E2E.
