# RB — Faz 22.6 VIEW_ONLY Operator Viewer Pilot Enable

> **Status**: OPERATIONAL enable runbook for `platform-k8s-gitops#1580`. The
> VIEW_ONLY operator screen-observation viewer is **engineering-COMPLETE +
> disabled-by-default** (see §1; the chain merged 2026-06-28/29). This runbook is
> the owner/ops sequence to turn the bounded 1-person pilot ON, and how to turn
> it OFF instantly.
>
> It does **not** by itself close `#1580`. Acceptance is the ADR-0044 split gate
> in [RB-faz22.6-autonomous-completion-contract.md](./RB-faz22.6-autonomous-completion-contract.md)
> §4.2: the fail-closed **`F22_6_VIEW_ONLY_ENGINEERING: v2`** (`GATE_VIEW_ONLY_ENGINEERING`)
> plus the tracked/non-blocking **`F22_6_VIEW_ONLY_KVKK: v1`** (`GATE_VIEW_ONLY_KVKK`).
> The old bundled `F22_6_VIEW_ONLY_ACCEPTANCE` marker is **refused**
> (`legacy_bundled_marker_detected`) — do not post it. This runbook produces the
> live state that §4.2 then certifies.

## 1. What is already built (disabled-by-default)

The end-to-end VIEW_ONLY chain is merged and inert until the flag in §3 is set:

| Layer | Where | Merged |
|---|---|---|
| Agent screen capture (banner/indicator/primary-parity/fail-closed/PID-anti-spoof) | platform-agent | #240–#245 (VM-live-proven) |
| Broker recording-OFF fan-out (latest-wins, 1:1, incarnation-bound authz) | platform-backend `…/bridge/server/viewonly` | #770 (2026-06-28) |
| Operator SSE controller (`/internal/remote-bridge/operator/sessions/{id}/view`) | platform-backend | #778 (2026-06-29) |
| Web MFE viewer (`/endpoint-admin/remote-access/sessions/:sessionId/view`) | platform-web `apps/mfe-endpoint-admin` | #847 (2026-06-29) |
| Fail-closed hash-chain audit (`REMOTE_SUPPORT_SCREEN_OBSERVATION` START/STOP) | platform-backend | #780 (2026-06-29) |

Invariants baked in: recording-OFF (ADR-0044), attended, 1:1 (`maxViewersPerSession=1`),
observation-only (no input/clipboard/file channel), no-oracle 404 authz, metadata-only audit,
**no observation without a committed `VIEW_START`** (#780 fail-closed gate).

### 1.1 Topology — which Deployment serves the viewer (READ FIRST)

The viewer is **not** served by the primary `endpoint-admin-service`. The broker
fan-out registry (#770) is in-process; the operator SSE controller (#778)
subscribes to that same in-JVM registry, so both live on the **isolated broker
Deployment** activated by
[`kustomize/overlays/test/activation/endpoint-admin-remote-bridge`](../../kustomize/overlays/test/activation/endpoint-admin-remote-bridge/):

- Deployment: `endpoint-admin-remote-bridge` (same image as endpoint-admin-service, `REMOTE_BRIDGE_ENABLED=true`, replicas=1).
- Config: ConfigMap `endpoint-admin-remote-bridge-config`.
- The primary `endpoint-admin-service` keeps the bridge **OFF**; it never gets `remote-bridge.viewer.enabled`.

**Port reality (`base/apps/endpoint-admin-remote-bridge`, control #5):** the bridge
pod advertises container ports `9444` (bridge) + `8081` (management/probes). HTTP
`8096` — where the operator SSE controller listens (`SERVER_PORT=8096`) — **is
bound in-pod but NOT declared as a containerPort, NOT published by the Service,
and is denied by the activation netpol** (`netpol.yaml` adds no `8096` allow; the
`9444` ingress rule is explicitly "Never api-gateway"). The activation
`service-patch.yaml` makes the Service a **`NodePort`** publishing only `9444`
(nodePort 31944, L4 fallback). Therefore exposing the operator viewer over `8096`
is itself part of the owner-approved change (§3 step 1) — and it must use a
**separate `ClusterIP` Service**, never a new port on the NodePort Service (that
would allocate a node-wide NodePort for 8096 and blow the "api-gateway only"
boundary; see OWNER-APPROVAL.md node-origin caveat).

## 2. Gate — enable ONLY when all are true

This is the owner decision. Do not flip the flag until every box holds:

- [ ] **KVKK DPIA + attended pilot sign-off** recorded for purpose
      `REMOTE_SUPPORT_SCREEN_OBSERVATION` (lawful basis, no content retention
      since recording-OFF, access limited to the roster, data-subject notice via
      the agent's visible indicator). Owner/legal-owned — never self-attested.
      Per ADR-0044 this is the **tracked, non-blocking** `F22_6_VIEW_ONLY_KVKK: v1`
      marker — it does **not** fail-close `F22_6_COMPLETION` — but a live pilot
      still does not start without the owner/DPO sign-off.
- [ ] **1-person roster** fixed: exactly one authorized operator `(tenantId, subject)`.
- [ ] **Owner sign-off to expose `8096`** (the §3 step 1 viewer overlay opens an
      HTTP listener that is deliberately closed today — a security-boundary
      decision, not a default).
- [ ] A single **pilot device** identified + consenting (attended).

## 3. Enable steps (TEST/pilot env; each: command → expected → fail signal)

> Credential/security mutations are TEST-autonomous / PROD-owner-gated. Run in the
> pilot (test) env, against the **`endpoint-admin-remote-bridge`** Deployment only.

### 3.0 Preferred path — audited workflow

Use the GitHub Actions workflow for the pilot surface whenever possible:

```bash
gh workflow run apply-view-only-viewer-pilot-enable.yml \
  --ref main \
  -f action=dry_run \
  -f confirm=DRY_RUN_VIEW_ONLY_VIEWER_PILOT_ENABLE
```

The dry-run renders the owner-gated overlay, proves the viewer surface is
ClusterIP-only, proves the overlay is not in the synced test Argo root, and runs a
server-side dry-run against `k3d-test/platform-test`.

After every §2 gate is true, use the same workflow for the live pilot enable:

```bash
gh workflow run apply-view-only-viewer-pilot-enable.yml \
  --ref main \
  -f action=apply \
  -f confirm=APPLY_VIEW_ONLY_VIEWER_PILOT_ENABLE \
  -f ack_kvkk_dpia=ACK_KVKK_DPIA_ATTENDED_PILOT_SIGNOFF_RECORDED \
  -f ack_one_person_roster=ACK_ONE_PERSON_OPERATOR_ROSTER_FIXED \
  -f ack_pilot_device_consent=ACK_CONSENTING_ATTENDED_PILOT_DEVICE \
  -f ack_8096_exposure=ACK_OWNER_8096_EXPOSURE
```

The workflow applies the bridge-side viewer overlay, patches only route-28 keys
into the live `api-gateway-config`, restarts the bridge and gateway, and verifies:
ClusterIP/no-NodePort, `REMOTE_BRIDGE_ENABLED=true`, viewer ConfigMap flags,
gateway route binding, and absence of `OVERLAY_MUST_OVERRIDE` in the gateway's
Keycloak environment. It does not mint the §4.2 marker and does not prove the
product-channel VIEW_ONLY session by itself.

Rollback is also workflow-backed and leaves the broker enabled:

```bash
gh workflow run apply-view-only-viewer-pilot-enable.yml \
  --ref main \
  -f action=rollback \
  -f confirm=ROLLBACK_VIEW_ONLY_VIEWER_PILOT_ENABLE
```

The manual steps below remain the break-glass/fallback form of the same contract.

1. **Apply the pre-staged viewer-exposure overlay** — the bridge-side enable in one
   reviewed, render-proven `apply -k`. The overlay
   `kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer` is a
   SUPERSET of the broker activation PLUS: `REMOTE_BRIDGE_VIEWER_ENABLED=true`, the
   png pilot pin (`REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES=image/png`),
   the http `containerPort: 8096`, a dedicated **`ClusterIP`** Service
   `endpoint-admin-remote-bridge-viewer` (8096, never NodePort), and an additive
   NetworkPolicy allowing 8096 ingress from `app.kubernetes.io/name: api-gateway`
   pods only. The operator REST surface is already
   `REMOTE_BRIDGE_OPERATOR_REST_ENABLED=true`; the viewer controller is gated
   separately by `@ConditionalOnProperty`. (To pin a different content-type set,
   edit the overlay's `configmap-viewer-patch.yaml` first — slice-1's default is
   `png|jpeg|webp`.) See the overlay's `OWNER-APPROVAL.md`.
   - **Build sanity (no apply):**
     ```bash
     kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer
     ```
     Rendered proof MUST show: a `ClusterIP` Service for 8096 (no NodePort for
     8096); the 9444 NodePort preserved; the **ingress** netpol 8096 allow scoped
     to `app.kubernetes.io/name: api-gateway` only AND the companion **egress**
     netpol (api-gateway → bridge:8096 — required because the ns default-denies
     egress and the bridge is `part-of=remote-bridge`, outside the standard intra-ns
     allow); the bridge deployment env
     `REMOTE_BRIDGE_ENABLED=true`; the ConfigMap `REMOTE_BRIDGE_VIEWER_ENABLED=true`
     + png allowlist; and the overlay NOT referenced by
     `overlays/test/kustomization.yaml`.
   - **Apply + roll:**
     ```bash
     kubectl --context k3d-test -n platform-test apply -k \
       kustomize/overlays/test/activation/endpoint-admin-remote-bridge-viewer
     kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge
     kubectl --context k3d-test -n platform-test rollout status  deploy/endpoint-admin-remote-bridge --timeout=180s
     ```
   - Expected: pod Ready (probes on `8081`); broker still bound on 9444; the
     `RemoteBridgeViewerController` bean present; the viewer ClusterIP resolvable.
   - Fail signal: not-Ready → control #11 fail-closed (missing signer/cert/ACL
     secret); or a context-load error referencing `RemoteBridgeViewerAuditService`
     / `EndpointAuditService` → bean wiring (audit service is `@Service`, should not
     happen post-#780).

2. **Apply the api-gateway route + reload api-gateway** (separate surface — the
   route is `envFrom` config, so the step-1 bridge restart does NOT pick it up).
   **DO NOT `apply -f kustomize/base/apps/api-gateway/configmap.yaml` directly** —
   the base ConfigMap ships `KEYCLOAK_ISSUER_URI` / `KEYCLOAK_JWKS_URI` as
   `OVERLAY_MUST_OVERRIDE` placeholders (the real values come from the
   `overlays/test` patch); a base apply overwrites the live values → gateway
   fail-closed / auth-route drift (see the configmap's own past-incident comment).
   Apply the **overlay-rendered** `api-gateway-config`, or patch **only** the
   route-28 keys into the live ConfigMap:
   ```bash
   kubectl --context k3d-test -n platform-test patch configmap api-gateway-config --type merge -p '{
     "data": {
       "SPRING_CLOUD_GATEWAY_ROUTES_28_ID": "remote-bridge-viewer-route",
       "SPRING_CLOUD_GATEWAY_ROUTES_28_URI": "http://endpoint-admin-remote-bridge-viewer:8096",
       "SPRING_CLOUD_GATEWAY_ROUTES_28_ORDER": "-10",
       "SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_0": "Path=/api/v1/endpoint-admin/remote-access/sessions/*/view",
       "SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_1": "Method=GET",
       "SPRING_CLOUD_GATEWAY_ROUTES_28_FILTERS_0": "RewritePath=/api/v1/endpoint-admin/remote-access/sessions/(?<sid>[^/]+)/view, /internal/remote-bridge/operator/sessions/${sid}/view"
     }
   }'
   kubectl --context k3d-test -n platform-test rollout restart deploy/api-gateway
   kubectl --context k3d-test -n platform-test rollout status  deploy/api-gateway --timeout=180s
   ```
   - Expected — **route bound proof** (not just pod Ready):
     ```bash
     kubectl --context k3d-test -n platform-test exec deploy/api-gateway -- \
       printenv | grep -E 'SPRING_CLOUD_GATEWAY_ROUTES_28_(ID|URI|ORDER)=|KEYCLOAK_(ISSUER_URI|JWKS_URI)='
     # route 28 → remote-bridge-viewer-route / http://endpoint-admin-remote-bridge-viewer:8096 / -10
     # KEYCLOAK_* → the platform-test values (NOT "OVERLAY_MUST_OVERRIDE")
     ```
     and the public URL reaches the **bridge viewer** (a `401/404` from the
     SERVICE, NOT a catch-all rewrite to the primary `endpoint-admin-service`).
   - Fail signal: env missing route 28 (ConfigMap not patched / pod not restarted);
     `KEYCLOAK_*` shows `OVERLAY_MUST_OVERRIDE` (a base apply clobbered the overlay
     → revert to the overlay-rendered config); or the public URL 404s via the
     catch-all (route order regressed → confirm `order=-10` rendered).

## 4. D29 verify (Up ≠ Functional ≠ Audited)

- **Up**: `endpoint-admin-remote-bridge` pod Running + Ready; the view route is
  reachable through the api-gateway (reaches the bridge viewer ClusterIP, not the
  primary service).
- **Functional**: with NO token → `401`; with a token for a
  non-owned/non-active/no-stream session → the SAME opaque `404` (no oracle); a
  2nd viewer on the same session → `409`.
- **8096 negative reachability** (the boundary, run from each origin):
  - same-ns non-api-gateway pod → 8096 connect **denied** (netpol).
  - ingress-nginx ns pod → 8096 **denied**.
  - api-gateway pod → 8096 **allowed** (the only permitted source — this validates
    BOTH the bridge ingress allow AND the api-gateway egress allow; if either is
    missing the curl hangs/`502`s, not `401`).
  - confirm `kubectl get svc endpoint-admin-remote-bridge-viewer` is `ClusterIP`
    (no `NodePort`), and the 9444 NodePort Service is unchanged.
- **Audited (the #780 gate) — executable drill**:
  1. Baseline: run one real observation; confirm a `REMOTE_SUPPORT_SCREEN_OBSERVATION`
     `VIEW_START` row exists in the tenant hash-chain BEFORE the first frame and a
     `VIEW_STOP` (with `framesDelivered`) on stream end.
  2. Fault the audit write (drill): make `recordViewStart` fail — e.g. point the
     audit datasource at an unreachable host (or revoke the audit-write grant) and
     `rollout restart`. Then attempt a view:
     ```bash
     curl -N -s -o /dev/null -w '%{http_code}\n' \
       -H "Authorization: Bearer <op-jwt>" \
       "https://testai.acik.com/api/v1/endpoint-admin/remote-access/sessions/<sid>/view?streamId=<stream>"
     ```
     - Expected: `503`, **zero frames delivered**, and a hash-chain query shows
       **no new `VIEW_START`** row for that attempt (fail-closed: no observation
       without a committed start).
     - Fail signal: any 2xx / any frame / a partial row → the #780 gate regressed.
  3. Restore the audit datasource + `rollout restart`; re-confirm baseline passes.

## 5. Acceptance (closes the §4.2 split gate, not this runbook)

Capture the [§4.2](./RB-faz22.6-autonomous-completion-contract.md)
**`F22_6_VIEW_ONLY_ENGINEERING: v2`** evidence on the real product channel:
`recording_mode=disabled` + `content_persistence=none` + `metadata_audit=active`,
live operator view of the 1 pilot device, agent-side **visible active indicator**,
**local-abort** ends the stream, `d10_fail_closed`/`dlp_mask_policy`/`active_indicator`
pass, browser smoke (first frame renders + STOP closes + NO input controls —
already browser-verified in CI for the MFE), the v2 negative matrix, and
`viewer_path_decision: fanout-proven`. Record the KVKK side as the separate,
non-blocking **`F22_6_VIEW_ONLY_KVKK: v1`** (legal/DPO allowlist only). Do **not**
post the legacy `F22_6_VIEW_ONLY_ACCEPTANCE` marker — the audit refuses it
(`legacy_bundled_marker_detected`). Only after the engineering marker passes does
`docs/state/current-state.md` move off `GATE_VIEW_ONLY_ENGINEERING=blocked`.

## 6. Rollback — two modes (broker always survives)

This is a feature flag, not a D30 cutover. **Both modes keep
`REMOTE_BRIDGE_ENABLED=true`** — never disable the whole bridge (that would kill
the broker fan-out and the agent stream, not just the viewer).

**Mode A — kill the viewer NOW** (viewer bug / stop observation immediately):
```bash
# set REMOTE_BRIDGE_VIEWER_ENABLED=false in the activation ConfigMap, then:
kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge
```
- Expected: the `@ConditionalOnProperty` controller is gone → the view route
  returns 404 at the service; any live SSE stream ends. Broker (9444) + audit stay up.

**Mode B — restore the closed HTTP surface** (security incident / enable
revocation — mandatory, not optional):
- Withdraw the api-gateway viewer route (`..._28_*`) and **`rollout restart
  deploy/api-gateway`** so the running gateway drops the route (it is `envFrom`
  config — removing it from the ConfigMap without a restart leaves the route live
  in the old pod).
- Delete the three viewer-only resources by name (they are standalone; re-applying
  the broker-only overlay does NOT remove them; NEVER `delete -k` this superset
  overlay — it would tear down the broker too):
  ```bash
  kubectl --context k3d-test -n platform-test delete service endpoint-admin-remote-bridge-viewer
  kubectl --context k3d-test -n platform-test delete networkpolicy eab-bridge-viewer-allow-ingress-8096-from-api-gateway
  kubectl --context k3d-test -n platform-test delete networkpolicy eab-api-gateway-allow-egress-8096-to-bridge-viewer
  ```
- Re-apply the **broker-only** overlay to revert the 8096 containerPort + viewer
  ConfigMap flags (3-way merge drops them), then restart:
  ```bash
  kubectl --context k3d-test -n platform-test apply -k \
    kustomize/overlays/test/activation/endpoint-admin-remote-bridge
  kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge
  ```
- Re-render + prove the §1.1 default posture is restored: route 28 gone from the
  api-gateway env, 8096 not published, no api-gateway→8096 allow, 9444 NodePort
  intact; the public view URL no longer reaches the bridge; re-run the §4
  negative-reachability checks (all 8096 origins denied). `REMOTE_BRIDGE_ENABLED`
  stays true throughout — the broker + agent stream never go down.
- No data to purge: recording-OFF means nothing was persisted.

## 7. References

- Engineering: platform-backend #770/#778/#780, platform-web #847, platform-agent #240–#245.
- Acceptance contract: [RB-faz22.6-autonomous-completion-contract.md](./RB-faz22.6-autonomous-completion-contract.md) §4.2 (`F22_6_VIEW_ONLY_ENGINEERING: v2` + `F22_6_VIEW_ONLY_KVKK: v1`).
- Audit enforcement: `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (`check_view_only_engineering_gate`, legacy fail-safe).
- Activation overlay: [`kustomize/overlays/test/activation/endpoint-admin-remote-bridge`](../../kustomize/overlays/test/activation/endpoint-admin-remote-bridge/) (`OWNER-APPROVAL.md`, control #5/#6/#11).
- ADRs: ADR-0034 §13 / D10 (owner-gated operator fan-out), ADR-0044 (recording-OFF + KVKK non-blocking split).
- Board: `platform-k8s-gitops#1580`.
