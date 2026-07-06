# Faz 22 #1267 endpoint-admin OpenFGA runtime selector evidence

**Date**: 2026-06-07

**Scope**: endpoint-admin OpenFGA model/store selector migration runtime proof on
`platform-test`.

**Related issues**:

- platform-k8s-gitops#1267
- platform-k8s-gitops#1331

**Related PR chain**:

- platform-k8s-gitops#1330
- platform-k8s-gitops#1332
- platform-k8s-gitops#1333
- platform-k8s-gitops#1334
- platform-k8s-gitops#1335
- platform-k8s-gitops#1336
- platform-k8s-gitops#1337
- platform-k8s-gitops#1338
- platform-k8s-gitops#1339

## Workflow

`Faz 22 — platform-test GitOps sync + endpoint-admin OpenFGA verify`

- Run: https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27096356021
- Head branch: `main`
- Head SHA: `513e238bc5498f20e2c9a6e875122b393cae4a98`
- Conclusion: `success`
- Updated at: `2026-06-07T15:13:24Z`

## Sync report

```json
{
  "verdict": "PASS",
  "reason": "ArgoCD core unavailable; selected endpoint-admin resources reconciled from kustomize/overlays/test",
  "app": "platform-test",
  "argocd_context": "k3d-prod",
  "argocd_namespace": "argocd",
  "sync_mode": "kubectl-overlay-selected-resources",
  "requested_revision": "513e238bc5498f20e2c9a6e875122b393cae4a98",
  "observed_revision": "",
  "sync_status": "Unknown",
  "health_status": "Unknown"
}
```

## Runtime selector report

```json
{
  "verdict": "PASS",
  "reason": "endpoint-admin OpenFGA runtime selector resolves through ESO-managed kv/platform/openfga",
  "context": "k3d-test",
  "namespace": "platform-test",
  "deployment": "endpoint-admin-service",
  "configmap": "endpoint-admin-service-config",
  "externalsecret": "endpoint-admin-service-secrets",
  "secret": "endpoint-admin-service-secrets",
  "expected_model_id": "01KS8QE8T1EJ2DF5CRS4VV9YX1",
  "expected_store_id": "01KPP0CFP4G82K42Y6NYSPT4JF",
  "observed_model_id": "01KS8QE8T1EJ2DF5CRS4VV9YX1",
  "observed_store_id": "01KPP0CFP4G82K42Y6NYSPT4JF",
  "pod_model_id": "01KS8QE8T1EJ2DF5CRS4VV9YX1",
  "pod_store_id": "01KPP0CFP4G82K42Y6NYSPT4JF"
}
```

## Boundary

- This proves the endpoint-admin OpenFGA runtime selector path after GitOps
  reconcile.
- The workflow used selected resources rendered from the GitOps overlays because
  ArgoCD core was unavailable on the runner.
- This is not a direct `kubectl set image`, workload edit, or unmanaged patch
  path.
- This does not satisfy the user-owned #1044 two-device observation roll-up,
  `acik.local` IT pilot, domain-wide rollout, 24h soak, or a new persona
  allow/deny smoke.
