# OWNER APPROVAL — Faz 22.6 #2373 VIEW_ONLY viewer product pilot overlay

> ⚠️ This overlay is **owner-gated** and **NOT** referenced by the Argo root
> (`kustomize/overlays/test/kustomization.yaml`). Applying it is a deliberate
> operator action during a bounded VIEW_ONLY pilot enable window. It does **not**
> by itself close `platform-k8s-gitops#2373` — acceptance is the separate
> `F22_6_VIEW_ONLY_VIEWER_PRODUCT_ACCEPTANCE: v2` provenance-bound product evidence gate.

## What this overlay does

Superset of `../endpoint-admin-remote-bridge-device-key-live` (the public 443 SNI
broker activation) **plus** the
bridge-side VIEW_ONLY operator-viewer HTTP exposure:

| Surface | Manifest | Effect |
|---|---|---|
| Viewer controller ON + png pin | `configmap-viewer-patch.yaml` | `REMOTE_BRIDGE_VIEWER_ENABLED=true` + `REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES=image/png` |
| http containerPort 8096 | `deployment-http-port-patch.yaml` | advertises 8096 (base advertises only 9444+8081) |
| Dedicated ClusterIP 8096 | `viewer-clusterip-service.yaml` | `endpoint-admin-remote-bridge-viewer` ClusterIP — **never NodePort** |
| Ingress 8096 (bridge ← api-gateway) | `viewer-from-api-gateway-netpol.yaml` | additive NetworkPolicy, narrow `app.kubernetes.io/name: api-gateway` podSelector |
| Egress 8096 (api-gateway → bridge) | `viewer-api-gateway-egress-netpol.yaml` | additive NetworkPolicy — REQUIRED companion (ns default-denies egress; intra-ns allow is `part-of=platform`→`platform` only, bridge is `part-of=remote-bridge-device-key`) |

It does **not** include the api-gateway route (route 28 must merge into the single
existing `api-gateway-config` ConfigMap; it stays a runtime `kubectl patch` per the
runbook §3 step 4b to avoid clobbering the overlay's `KEYCLOAK_*` values). It does
**not** change the 9444 NodePort Service, any prod overlay, or the Argo root.

## Gate — owner confirms ALL before apply

- [ ] KVKK DPIA + attended pilot sign-off (`F22_6_VIEW_ONLY_KVKK: v1`) is dual-human signed and verifies against the canonical policy.
- [ ] Protected Environment `faz22-view-only-pilot` approval is granted for this run.
- [ ] Protected one-person operator and consenting pilot-device hashes are present, distinct and unexpired.
- [ ] Owner sign-off to expose 8096 is represented by the protected Environment approval.

## Apply (bounded pilot, test env)

Use `.github/workflows/apply-view-only-viewer-pilot-enable.yml` with
`action=apply` and a 5-120 minute TTL. Direct `kubectl apply -k` is break-glass
only because it omits the signed-marker verifier, protected authorization receipt,
absolute-expiry watchdog and automatic compensating rollback.

Then wire the api-gateway route (runtime patch) per
`docs/runbooks/RB-faz22.6-view-only-viewer-pilot-enable.md` §3 step 4b, and verify
per §4 (Up / Functional 401-404-409 / 8096 negative reachability / executable audit
fail-closed drill).

## Rollback

- **Kill viewer now:** set `REMOTE_BRIDGE_VIEWER_ENABLED=false` (keep
  `REMOTE_BRIDGE_ENABLED=true`) + `rollout restart deploy/endpoint-admin-remote-bridge-device-key`.
- **Restore closed HTTP surface:** withdraw the api-gateway route 28 patch +
  `rollout restart deploy/api-gateway`. Then delete the **three viewer-only
  resources by name** (NEVER `kubectl delete -k` this overlay — it is a SUPERSET of
  the broker activation, so `delete -k` would tear down the broker too):
  ```bash
  kubectl --context k3d-test -n platform-test delete service endpoint-admin-remote-bridge-viewer
  kubectl --context k3d-test -n platform-test delete networkpolicy eab-bridge-viewer-allow-ingress-8096-from-api-gateway
  kubectl --context k3d-test -n platform-test delete networkpolicy eab-api-gateway-allow-egress-8096-to-bridge-viewer
  ```
  Then re-apply the **broker-only** overlay (`apply -k .../endpoint-admin-remote-bridge-device-key-live`)
  to revert the 8096 containerPort + viewer ConfigMap flags (3-way merge drops
  them) + `rollout restart deploy/endpoint-admin-remote-bridge-device-key`. Re-prove: 8096 not
  published, no api-gateway↔8096 allow (both directions), 9444 NodePort intact. The
  broker (9444) + agent stream always survive (`REMOTE_BRIDGE_ENABLED` stays true).

## Boundary

- Test overlay only; no prod overlay change.
- Not in the Argo root → no reconcile can auto-expose the viewer.
- Recording-OFF (ADR-0044): nothing is persisted; no data to purge on rollback.
- The apply authorization receipt is not sufficient product evidence. The v2
  product verifier must independently re-fetch and bind its run/artifact/digest
  to the operator child and the browser session hashes.
- As of 2026-07-14, the canonical approver policy, protected Environment and
  live seven-source product evidence are absent. Keep the overlay inert until
  those human-governed and runtime gates exist.
