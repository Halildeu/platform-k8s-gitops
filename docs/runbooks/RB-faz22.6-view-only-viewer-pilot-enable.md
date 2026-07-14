# RB — Faz 22.6 VIEW_ONLY Operator Viewer Pilot Enable

> **Status**: OPERATIONAL enable and product-acceptance runbook for
> `platform-k8s-gitops#2373`. The narrow #1580 broker-received engineering gate
> is accepted; it proved 122 real PNG frames at the broker, but explicitly did
> not prove viewer delivery or browser rendering. This runbook owns that
> separate, disabled-by-default, bounded 1-person product pilot.
>
> It does not reopen #1580 or weaken the official `F22_6_COMPLETION=pass` result.
> Product acceptance requires the separate
> **`F22_6_VIEW_ONLY_VIEWER_PRODUCT_ACCEPTANCE: v2`** provenance-bound verifier result in §5.
> Legal basis, notice/consent wording, retention governance and DPO approval stay
> separately tracked by #2374; a product verifier cannot manufacture legal acceptance.

## 1. What is already built (disabled-by-default)

The end-to-end VIEW_ONLY chain is merged and inert until the flag in §3 is set:

| Layer | Where | Merged |
|---|---|---|
| Agent screen capture (banner/indicator/primary-parity/fail-closed/PID-anti-spoof) | platform-agent | #240–#245 (VM-live-proven) |
| Broker recording-OFF fan-out (latest-wins, 1:1, incarnation-bound authz) | platform-backend `…/bridge/server/viewonly` | #770 (2026-06-28) |
| Operator SSE controller (`/internal/remote-bridge/operator/sessions/{id}/view`) | platform-backend | #778 (2026-06-29) |
| Web MFE viewer + fail-closed trusted metadata/evidence telemetry (`/endpoint-admin/remote-access/sessions/:sessionId/view`) | platform-web `apps/mfe-endpoint-admin` | #847 + #910 (2026-07-14) |
| Fail-closed hash-chain audit (`REMOTE_SUPPORT_SCREEN_OBSERVATION` START/STOP) | platform-backend | #780 (2026-06-29) |

Invariants baked in: recording-OFF (ADR-0044), attended, 1:1 (`maxViewersPerSession=1`),
observation-only (no input/clipboard/file channel), no-oracle 404 authz, metadata-only audit,
**no observation without a committed `VIEW_START`** (#780 fail-closed gate).

The #2373 extension adds an opaque per-subscription `viewerId`, broker
observation/send timestamps and a bearer-authenticated `POST` acknowledgement
after the browser image render path. The acknowledgement contains only
`{viewerId, frameSeq}`. It carries no screen bytes and cannot dispatch an
operation to the endpoint.

### 1.1 Topology — which Deployment serves the viewer (READ FIRST)

The viewer is **not** served by the primary `endpoint-admin-service`. The broker
fan-out registry (#770) is in-process; the operator SSE controller (#778)
subscribes to that same in-JVM registry, so both live on the **isolated broker
Deployment** that owns the public 443 SNI product route, activated by
[`kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live`](../../kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live/):

- Deployment: `endpoint-admin-remote-bridge-device-key` (same image as endpoint-admin-service, `REMOTE_BRIDGE_ENABLED=true`, replicas=1).
- Config: ConfigMap `endpoint-admin-remote-bridge-config-device-key`.
- Public agent route: `remote-bridge-mtls.testai.acik.com:443` ->
  `endpoint-admin-remote-bridge-device-key:9444`. The viewer Service MUST select
  this exact Deployment because fan-out state is in-process and cannot cross to
  the legacy broker pod.
- The primary `endpoint-admin-service` keeps the bridge **OFF**; it never gets `remote-bridge.viewer.enabled`.

**Port reality (`base/apps/endpoint-admin-remote-bridge`, control #5):** the bridge
pod advertises container ports `9444` (bridge) + `8081` (management/probes). HTTP
`8096` — where the operator SSE controller listens (`SERVER_PORT=8096`) — **is
bound in-pod but NOT declared as a containerPort, NOT published by the Service,
and is denied by the activation netpol** (`netpol.yaml` adds no `8096` allow; the
`9444` ingress rule is explicitly "Never api-gateway"). The activation
`service-patch.yaml` makes the Service a **`NodePort`** publishing only `9444`
(nodePort 31945, L4 fallback). Therefore exposing the operator viewer over `8096`
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
      still does not start without the owner/DPO sign-off. The apply workflow
      fetches the single `F22_6_VIEW_ONLY_KVKK: v1` marker from #2374 and
      re-verifies both Ed25519 signatures against the canonical reviewed policy;
      a typed acknowledgement cannot substitute for it.
- [ ] **1-person roster** fixed: exactly one authorized operator `(tenantId, subject)`.
- [ ] **Owner sign-off to expose `8096`** (the §3 step 1 viewer overlay opens an
      HTTP listener that is deliberately closed today — a security-boundary
      decision, not a default).
- [ ] A single **pilot device** identified + consenting (attended).
- [ ] GitHub Environment `faz22-view-only-pilot` has a required human reviewer
      and the three protected values `VIEW_ONLY_PILOT_OPERATOR_SHA256`,
      `VIEW_ONLY_PILOT_DEVICE_SHA256`, and
      `VIEW_ONLY_PILOT_AUTHORIZATION_EXPIRES_AT`. The first two are distinct
      `sha256:<64hex>` opaque bindings; raw identity/device values do not enter
      workflow inputs or logs.

## 3. Enable steps (TEST/pilot env; each: command → expected → fail signal)

> Credential/security mutations are TEST-autonomous / PROD-owner-gated. Run in the
> pilot (test) env, against the **`endpoint-admin-remote-bridge-device-key`** Deployment only.

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
  -f pilot_ttl_minutes=120
```

The `apply` run waits for the protected Environment reviewer, verifies the signed
#2374 marker and emits a content-addressed protected-authorization receipt before
the deployment job can start. The workflow then installs a cluster-side
absolute-expiry watchdog **before** exposure, applies the bridge-side viewer
overlay, patches only route-28 keys
into the live `api-gateway-config`, restarts the bridge and gateway, and verifies:
ClusterIP/no-NodePort, `REMOTE_BRIDGE_ENABLED=true`, viewer ConfigMap flags,
gateway route binding, and absence of `OVERLAY_MUST_OVERRIDE` in the gateway's
Keycloak environment. It does not mint the §4.2 marker and does not prove the
product-channel VIEW_ONLY session by itself. The TTL starts when the watchdog is
installed, so setup time reduces the usable pilot window rather than extending
the security window. Allowed TTL is 5-120 minutes. The longer window exists only
to collect the isolated negative and five termination cases under one
content-addressed protected authorization. The requested watchdog expiry must
not exceed the signed protected-authorization `expiresAt`; otherwise activation
fails closed before exposing the viewer. The watchdog has narrow RBAC:
it can disable only the viewer flag/route, delete only the three viewer-only
network resources, and restart only the bridge/gateway Deployments. It cannot
disable or mutate the 9444 broker Service. If the Actions runner dies, the
cluster-side Job still closes the surface at the absolute expiry. A normal apply
failure also triggers immediate compensating rollback.

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
     kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge-device-key
     kubectl --context k3d-test -n platform-test rollout status deploy/endpoint-admin-remote-bridge-device-key --timeout=180s
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
       "SPRING_CLOUD_GATEWAY_ROUTES_28_PREDICATES_1": "Method=GET,POST",
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
- **Functional**: `GET` opens the one-way SSE stream and `POST` acknowledges
  metadata-only browser rendering on the same path. With NO token → `401`; with a token for a
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
     `VIEW_STOP` (with `framesDelivered` and `framesRenderAcknowledged`) on stream end.
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

## 5. #2373 product acceptance (separate from #1580 completion)

The test-pilot thresholds are fixed before the run:

| Signal | Bounded test-pilot threshold |
|---|---|
| First browser-render acknowledgement | `<= 5000 ms` from broker observation |
| Steady frame age | p95 `<= 2000 ms`, exactly one sample per rendered ACK and at least 100 rendered samples |
| Broker-to-viewer drop rate | `<= 20%` |
| Viewer-delivered to browser-rendered loss | `<= 5%` |
| Reconnects | `<= 1` during the evidence window |
| Backpressure | `latest-wins-single-slot`, max pending frame `1` |
| Soak | `300-1800 s`, derived from bound start/end timestamps (not a caller-authored duration) |

The producer workflow creates one redacted artifact matching
`faz22.6.viewOnlyViewerProductEvidence.v2`. The root and every child are strict
JSON Schema objects with `additionalProperties:false`. The artifact must contain
exactly seven source-specific child records: browser, broker metrics, hash-chain
audit, D30, negative matrix, termination matrix and protected operator
authorization. It must correlate:

1. `CAPTURED`, `BROKER_RECEIVED`, `VIEWER_DELIVERED`, `VIEWER_RENDERED` counts.
2. Browser screenshot hash, independent non-blank pixel check, DOM-observed accepted render-ack count and clean console.
3. No-auth/wrong-role/wrong-tenant/wrong-device/expired/revoked/replay/
   over-concurrency/disconnected-viewer negative matrix.
4. Local abort, revoke, TTL, heartbeat loss, consent withdrawal and indicator-loss termination.
5. Delivered-path DLP proof by hash only, recording-off zero persistence, and no input channels.
6. Backend + web desired digest equals live pod `imageID` digest (D30).
7. Broker Prometheus window deltas independently match delivered/rendered counts.
8. Hash-chain `VIEW_START` is committed before first delivery; `VIEW_STOP` counts and snapshot hash match delivered/rendered counts.

Every child carries the root opaque session/tenant/operator/device hash binding,
source revision and run-window timestamp. Each matrix case repeats the authorized
tenant/operator binding; termination cases and ordinary negative cases retain the
authorized device binding. In a negative snapshot, `binding` is the protected
resource/target session binding; `request.subjectSha256`, `request.tenantSha256`
and `request.rolePresent` independently describe the actual caller JWT. Ordinary
negative cases must retain the root target session exactly, while the
`wrongDevice` operator-session-open probe must use
a distinct attempted session and a different device hash, proving the resolver
denial instead of relabelling a viewer stream miss. Each request is additionally
bound to a closed path template and request-body SHA-256 (null only for bodyless
GET), and its request timestamps must fall inside the before/after metric sample
window. The root content-addresses each child;
the assembler and independent verifier fetch each child from a distinct,
source-specific successful workflow run and exact GitHub artifact. They verify
workflow identity/conclusion/head SHA, artifact ID/name/run binding, recompute
every downloaded ZIP SHA-256 against GitHub artifact metadata, reject unsafe ZIP
entries, and require the aggregated child bytes to equal the source artifact
bytes exactly. The operator child additionally binds the successful protected
apply workflow, authorization artifact ID/digest, receipt digest and KVKK marker
digest. The independent verifier re-downloads that activation artifact, checks
its exact file envelope and `SHA256SUMS`, and matches the authorized operator and
device hashes to the browser session binding. A local file path, syntax-only URL,
nonexistent run/artifact or hash-shaped placeholder is not accepted.

Negative and termination source artifacts additionally carry one strict case
attestation per case and one canonical, newline-terminated observation in
`observations/<type>.jsonl`. The verifier digests the exact JSONL line bytes and
requires equality with the attestation before checking the real request
channel/status, zero post-deny or post-termination frame delivery, agent-deny
code for expired/replayed permits, response byte length/SHA-256, viewer-reject
counter movement for viewer-channel denials, and terminal viewer/broker/agent
signals. The negative observation names its real source explicitly: viewer HTTP
plus metric probe; tenant/device resolver-backed operator session-open probe for
`wrongDevice`; or agent-error-ledger plus the acceptance-only HTTP probe. The
viewer endpoint has no caller-supplied device field, so a random viewer stream
ID must not be relabelled as wrong-device evidence. Every negative request also
binds redacted subject and tenant digests plus role presence from the actual JWT
claims. `noAuth` requires null identities, `wrongRole` a distinct subject in the
authorized tenant without the operator role, and `wrongTenant` a distinct subject
and tenant with the operator role; labels alone are not accepted as identity proof.
The protected collector creates run-scoped temporary Keycloak personas for
`wrongRole` and `wrongTenant`, verifies their effective JWT claims, and deletes
them during cleanup; a non-`204/404` deletion result is surfaced as an operator
warning rather than silently ignored.
The disconnected-viewer SSE body is consumed through a FIFO by a streaming
hasher. Only length and SHA-256 are recorded; the protected workflow stages an
exact two-file JSON/JSONL envelope, and raw screen/frame bytes are never uploaded.
Termination artifacts also carry canonical `audit/termination.jsonl` records;
each line is digest-bound to its case and must prove a real hash-chained
`VIEW_STOP` through the tenant audit-chain builder. Negative authentication and
authorization failures do not fabricate a tenant audit identity or a
`VIEWER_DENY` event that the product does not emit. Their protected producer
artifact and exact runtime observation are the evidence. A standalone
hash-shaped `runtimeSnapshotSha256` or `viewStopAuditSha256` value is rejected
when the corresponding bytes are absent.

### 5.1 Implementation and live-acceptance boundary

| Source | Producer status | Live evidence status |
|---|---|---|
| Browser render/ACK | Canonical protected workflow implemented | Not run; requires merged GitOps workflow, deployed #910 web digest, signed #2374 marker/policy, protected Environment and active bounded surface |
| Broker Prometheus | Independent source producer implemented | Live source run absent |
| Hash-chain audit | Independent source producer implemented | Live source run absent |
| D30 backend + web | Independent source producer implemented | Live source run absent |
| Negative matrix | Protected collector + exact-artifact producer + strict verifier implemented and source-ready | Live protected source run absent |
| Termination matrix | Contract hardened; source audit found real product gaps tracked by backend `#830` and agent `#262`; collector intentionally not fabricated | Product fixes and live source run absent |
| Protected operator | Activation provenance verifier and source producer implemented | Live authorization artifact absent |

The seven-source assembler and independent verifier are implemented, but they
cannot manufacture a missing source artifact. `#2373` therefore stays open until
all seven source workflows have successful, same-revision, same-authorization
runs inside the bounded matrix window (with distinct isolated sessions for each
termination case) and the independent verifier emits the content-addressed v2 marker. The canonical
approver policy file and protected GitHub Environment are intentionally not
invented by an agent; their absence keeps live activation fail-closed.

Negative evidence must be produced fresh against the current contract. A token
missing the required operator role is rejected as unauthenticated (`401`);
expired and replayed signed permits are exercised through the non-prod,
acceptance-only agent-permit probe (`POST`, `422` only after a real agent deny),
not relabelled as viewer-channel `GET` requests. Evidence generated with the
older wrong-role `404` or expired/replay viewer-`GET` model is incompatible and
must not be migrated or reused.

Never place a bearer token, cookie, frame bytes, base64 image, raw screen content,
raw session/operator/device identity, private endpoint or credential in the
artifact. Verify a completed producer run with the independent workflow:

```bash
gh workflow run faz22-6-view-only-viewer-product-evidence-verify.yml \
  --ref main \
  -f producer_run_id=<COMPLETED_PRODUCER_RUN_ID> \
  -f confirm=VERIFY_FAZ22_6_VIEW_ONLY_VIEWER_PRODUCT_EVIDENCE
```

Only `status=pass` together with marker
`F22_6_VIEW_ONLY_VIEWER_PRODUCT_ACCEPTANCE: v2` is #2373 product acceptance.
The marker binds the producer run/attempt/head SHA, GitHub artifact ID/digest,
canonical evidence-root digest, opaque same-session binding, pilot window and
verification expiry. It is not a constant marker and expires after at most 24h.
It is explicitly bounded to test, recording-off and one viewer. Production,
broad rollout, multi-viewer fanout and #2374 legal acceptance remain false.

## 6. Rollback — two modes (broker always survives)

This is a feature flag, not a D30 cutover. **Both modes keep
`REMOTE_BRIDGE_ENABLED=true`** — never disable the whole bridge (that would kill
the broker fan-out and the agent stream, not just the viewer).

**Mode A — kill the viewer NOW** (viewer bug / stop observation immediately):
```bash
# set REMOTE_BRIDGE_VIEWER_ENABLED=false in the activation ConfigMap, then:
kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge-device-key
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
    kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live
  kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-remote-bridge-device-key
  ```
- Re-render + prove the §1.1 default posture is restored: route 28 gone from the
  api-gateway env, 8096 not published, no api-gateway→8096 allow, 9444 NodePort
  intact; the public view URL no longer reaches the bridge; re-run the §4
  negative-reachability checks (all 8096 origins denied). `REMOTE_BRIDGE_ENABLED`
  stays true throughout — the broker + agent stream never go down.
- No data to purge: recording-OFF means nothing was persisted.

## 7. References

- Engineering: platform-backend #770/#778/#780, platform-web #847, platform-agent #240–#245.
- Product acceptance follow-up: platform-k8s-gitops #2373; legal follow-up #2374.
- Narrow completion contract: [RB-faz22.6-autonomous-completion-contract.md](./RB-faz22.6-autonomous-completion-contract.md) §4.2 (historical #1580 engineering/KVKK split; already accepted for `F22_6_COMPLETION`).
- Audit enforcement: `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (`check_view_only_engineering_gate`, legacy fail-safe).
- Activation overlay: [`kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live`](../../kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key-live/) plus the owner-gated viewer superset (`OWNER-APPROVAL.md`, control #5/#6/#11).
- ADRs: ADR-0034 §13 / D10 (owner-gated operator fan-out), ADR-0044 (recording-OFF + KVKK non-blocking split).
- Product evidence verifier: `scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py`.
