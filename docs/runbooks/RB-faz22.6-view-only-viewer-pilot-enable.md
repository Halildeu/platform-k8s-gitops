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
is itself part of the owner-approved change (§3 step 3) — and it must use a
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
- [ ] **Owner sign-off to expose `8096`** (step 3 opens an HTTP listener that is
      deliberately closed today — a security-boundary decision, not a default).
- [ ] A single **pilot device** identified + consenting (attended).

## 3. Enable steps (TEST/pilot env; each: command → expected → fail signal)

> Credential/security mutations are TEST-autonomous / PROD-owner-gated. Run in the
> pilot (test) env, against the **`endpoint-admin-remote-bridge`** Deployment only.

1. **Pin the pilot to png-only** (defense-in-depth; slice-1 default stays
   `png|jpeg|webp` by design — narrowing it is a pilot choice, not a code change).
   Add to ConfigMap `endpoint-admin-remote-bridge-config`
   (`overlays/test/activation/endpoint-admin-remote-bridge/configmap-activation-patch.yaml`):
   ```yaml
   REMOTE_BRIDGE_VIEW_ONLY_ALLOWED_FRAME_CONTENT_TYPES: "image/png"
   ```
   - Expected: `LiveOnlyViewDataPlaneHandler` drops any non-png frame.
   - Fail signal: jpeg/webp frames still fan out → ConfigMap not re-read (the
     rolling restart in step 4 is required for `envFrom`).

2. **Turn the viewer controller ON** (the operator REST surface is already
   `REMOTE_BRIDGE_OPERATOR_REST_ENABLED=true`; the viewer controller is gated
   separately by `@ConditionalOnProperty`). Add:
   ```yaml
   REMOTE_BRIDGE_VIEWER_ENABLED: "true"
   ```
   Keep `REMOTE_BRIDGE_ENABLED=true` (set by `patch-activate.yaml`).
   - Expected: after restart the `RemoteBridgeViewerController` bean is present.
   - Fail signal: context-load error referencing `RemoteBridgeViewerAuditService`
     / `EndpointAuditService` → bean wiring (audit service is `@Service`, so this
     should not happen post-#780).

3. **Expose HTTP `8096` for the viewer path only** (owner-approved
   security-boundary change — see §1.1). Four coordinated, scoped edits:
   - **Deployment** `endpoint-admin-remote-bridge` (`patch-activate.yaml` ports
     patch): add the http containerPort —
     ```yaml
     ports:
       - name: http
         containerPort: 8096
         protocol: TCP
     ```
   - **A NEW dedicated `ClusterIP` Service** (do NOT touch the NodePort
     `service-patch.yaml`; add a new manifest, e.g. `viewer-clusterip-service.yaml`,
     to the activation kustomization):
     ```yaml
     apiVersion: v1
     kind: Service
     metadata:
       name: endpoint-admin-remote-bridge-viewer
     spec:
       type: ClusterIP          # NEVER NodePort — keeps 8096 off every node IP
       selector:
         app.kubernetes.io/name: endpoint-admin-remote-bridge
       ports:
         - name: http
           port: 8096
           targetPort: http
     ```
   - **NetworkPolicy** (`netpol.yaml`): add an ingress rule allowing `8096`
     **from the api-gateway pods ONLY** (a narrow `podSelector`
     `app.kubernetes.io/name: api-gateway`, not `part-of=platform`, and not the
     agent/orchestrator/edge sources that may reach 9444).
   - **api-gateway route** (`kustomize/base/apps/api-gateway/configmap.yaml` or the
     test overlay route layer): add a route that is evaluated **before** the
     catch-all `SPRING_CLOUD_GATEWAY_ROUTES_24_*`
     (`Path=/api/v1/endpoint-admin/**` → `endpoint-admin-service:8096`, which
     rewrites to `/api/v1/admin/...` and would otherwise swallow the viewer path).
     Ordering here is by route `order` then load order — set an explicit lower
     `order` so it cannot regress when indices are renumbered:
     ```yaml
     SPRING_CLOUD_GATEWAY_ROUTES_28_ID: "remote-bridge-viewer-route"
     SPRING_CLOUD_GATEWAY_ROUTES_28_URI: "http://endpoint-admin-remote-bridge-viewer:8096"
     SPRING_CLOUD_GATEWAY_ROUTES_28_ORDER: "-10"   # < route 24 (default order 0) → wins
     SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_0: "Path=/api/v1/endpoint-admin/remote-access/sessions/*/view"
     SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_1: "Method=GET"
     SPRING_CLOUD_GATEWAY_ROUTES_28_FILTERS_0: "RewritePath=/api/v1/endpoint-admin/remote-access/sessions/(?<sid>[^/]+)/view, /internal/remote-bridge/operator/sessions/${sid}/view"
     ```
     Preserve the `?streamId=` query string (Spring Cloud Gateway forwards it by
     default) and forward `Authorization`; disable response buffering for this
     route (SSE). **Surface note:** `api-gateway-config` is **not** part of the
     remote-bridge activation overlay — it lives in the api-gateway config surface
     (`overlays/test`) and is read by `deploy/api-gateway` via `envFrom`, so the
     route only goes live after a **separate api-gateway apply + restart**
     (step 4b). Keep this route change owner-gated: apply it deliberately at enable
     and withdraw it at Mode B rollback (§6) — do not leave it as an always-on
     default ahead of the owner decision.
   - **Build sanity (no apply):**
     ```bash
     kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge
     ```
     Rendered proof MUST show: a `ClusterIP` Service for 8096 (no NodePort
     allocated for 8096), the 9444 NodePort preserved, and the netpol 8096 allow
     scoped to `app.kubernetes.io/name: api-gateway` only.
   - Expected: `curl -N -H "Authorization: Bearer <op-jwt>"` against the public
     view URL reaches the **bridge viewer** service (401/404 from the SERVICE, not
     a gateway 404/502) and frames stream incrementally (not batched).
   - Fail signal: gateway 404 (route ordered after the catch-all → hit the primary
     service) / 502 (8096 ClusterIP/netpol wrong) / batched frames (buffering on).

4a. **Roll the bridge** to pick up the ConfigMap + ports:
   ```bash
   kubectl --context k3d-test -n platform-test apply -k \
     kustomize/overlays/test/activation/endpoint-admin-remote-bridge
   kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge
   kubectl --context k3d-test -n platform-test rollout status  deploy/endpoint-admin-remote-bridge --timeout=180s
   ```
   - Expected: pod Ready (probes on `8081`); broker still bound on 9444.
   - Fail signal: not-Ready → control #11 fail-closed (missing signer/cert/ACL
     secret) or the step-2 context-load error.

4b. **Apply the api-gateway route + reload api-gateway** (separate surface — the
   route is `envFrom` config, so the bridge restart in 4a does NOT pick it up).
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
  - api-gateway pod → 8096 **allowed** (the only permitted source).
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
  in the old pod). Then delete the `endpoint-admin-remote-bridge-viewer` ClusterIP
  Service, remove the 8096 netpol allow, and remove the `8096` containerPort
  (`rollout restart deploy/endpoint-admin-remote-bridge`).
- Re-render + prove the §1.1 default posture is restored: route 28 gone from the
  api-gateway env, 8096 not published, no api-gateway→8096 allow, 9444 NodePort
  intact; the public view URL no longer reaches the bridge; re-run the §4
  negative-reachability checks (all 8096 origins denied).
- No data to purge: recording-OFF means nothing was persisted.

## 7. References

- Engineering: platform-backend #770/#778/#780, platform-web #847, platform-agent #240–#245.
- Acceptance contract: [RB-faz22.6-autonomous-completion-contract.md](./RB-faz22.6-autonomous-completion-contract.md) §4.2 (`F22_6_VIEW_ONLY_ENGINEERING: v2` + `F22_6_VIEW_ONLY_KVKK: v1`).
- Audit enforcement: `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (`check_view_only_engineering_gate`, legacy fail-safe).
- Activation overlay: [`kustomize/overlays/test/activation/endpoint-admin-remote-bridge`](../../kustomize/overlays/test/activation/endpoint-admin-remote-bridge/) (`OWNER-APPROVAL.md`, control #5/#6/#11).
- ADRs: ADR-0034 §13 / D10 (owner-gated operator fan-out), ADR-0044 (recording-OFF + KVKK non-blocking split).
- Board: `platform-k8s-gitops#1580`.
