# RB Faz 24 İ4 — audio-gateway live-analyze enable + rollback

**Owner**: platform-ops (test) / D30-atomic (prod)
**Prerequisite**: meeting-ai runtime reachable on the target cluster (see
`docs/faz24-meeting-ai-host-deploy-runbook.md`)
**Blast radius**: single service (audio-gateway); no cross-service secrets;
test-only egress is limited to `10.99.0.2/32` TCP `8300`.
**Reversible**: yes — flip enabled back to `false` + rollout restart.

---

## When to run

- **Trigger**: platform-backend#902 (İ4 aggregator code) is merged AND the
  matching digest is pinned in the target overlay (test: gitops#2730 landed
  `sha-494e4f4`; prod: awaits its own bump) AND meeting-ai is reachable
  from the audio-gateway pod on the configured base URL.
- **NOT before** meeting-ai is up — the trigger fires per every Nth transcript
  and each failed POST costs one metric increment + one WARN log. Enabling
  against a down meeting-ai will not break the STT path (fail-closed
  design) but will spam alerts.

---

## Preflight (all must be true)

```bash
CTX=k3d-test        # or k3d-prod, once its own bump lands
NS=platform-test    # or platform-prod

# 1. Audio-gw pod is on the code that has the trigger.
kubectl --context $CTX -n $NS get pod -l app.kubernetes.io/name=audio-gateway \
  -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'
# → expect ghcr.io/…/audio-gateway-service@sha256:db1bdb6f…  (sha-494e4f4)

# 2. Env vars are visible to the pod (baseline gitops#2728 pins them off).
kubectl --context $CTX -n $NS exec deploy/audio-gateway -- \
  env | grep AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE
# → 4 keys; ENABLED=false, BASE_URL=""

# 3. Target meeting-ai is reachable from the actual audio-gateway network identity.
kubectl --context $CTX -n $NS exec deploy/audio-gateway -- \
  curl -sS -o /dev/null -w 'HTTP %{http_code}\n' \
    -m 5 http://meeting-ai-service:8080/health
# → expect HTTP 200 (or HTTP 401 if auth-required — a routable-but-guarded
#   endpoint is still preflight-passing; a connect/timeout error is NOT)
```

Preflight failure → STOP. Fix reachability before flipping the flag.

---

## Enable

Use the shared kustomize patch — DO NOT `kubectl set env` a ConfigMap
directly (drifts from git; next `apply -k` overwrites it).

```bash
# 1. Patch the overlay
cd platform-k8s-gitops
git checkout -b enable/faz24-i4-audio-gw-live-analyze-<env>-<yyyymmdd>
# Edit kustomize/overlays/<env>/kustomization.yaml — add a patch that
# `op: replace` /data/AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED → "true"
# and /data/AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL → the reachable
# meeting-ai URL (e.g. "http://meeting-ai-service:8080").
# Follow the pattern already used for AUDIO_GATEWAY_DIRECT_STT_STREAMING_ENABLED
# (test overlay kustomization.yaml — grep for STREAMING_ENABLED to see the
# in-place patch shape).

# 2. Commit + PR + merge as usual (Boundary declaration: state-mutation)

# 3. Apply
kubectl --context $CTX -n $NS apply -k kustomize/overlays/<env>

# 4. Rollout restart so envFrom picks up the new ConfigMap
kubectl --context $CTX -n $NS rollout restart deploy/audio-gateway
kubectl --context $CTX -n $NS rollout status  deploy/audio-gateway --timeout=180s
```

---

## Verify (all must pass)

```bash
# A. Config actually landed in the pod
kubectl --context $CTX -n $NS exec deploy/audio-gateway -- \
  env | grep -E 'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_(ENABLED|BASE_URL)='
# → ENABLED=true; BASE_URL matches the overlay patch

# B. Micrometer counters are registered (means the bean wired)
kubectl --context $CTX -n $NS exec deploy/audio-gateway -- \
  curl -sS localhost:8080/actuator/prometheus \
  | grep -E '^audio_gw_live_analyze_(publish|drop)_total'
# → 4 series present (publish_total, publish_success_total,
#   publish_error_total, drop_total). Values may all be 0 until traffic.

# C. End-to-end smoke — run the İ5 script against the SAME meeting-ai URL
#    audio-gateway now uses.
MEETING_AI_URL=http://meeting-ai-service:8080 \
  scripts/faz24/live-analyze-sse-smoke.sh
# → PASS: SSE delivered an event: analysis frame with is_partial=true
```

If (A) or (B) fails, treat as an incident and roll back. If (C) fails but
(A)+(B) pass, meeting-ai itself is degraded — leave audio-gw enabled and
investigate meeting-ai independently.

---

## Rollback

```bash
# Fastest: revert the enable PR + apply
git revert <enable-commit-sha>
git push
kubectl --context $CTX -n $NS apply -k kustomize/overlays/<env>
kubectl --context $CTX -n $NS rollout restart deploy/audio-gateway
```

Env-flip is idempotent — restart is required so the pod re-reads the
ConfigMap (envFrom does not hot-reload).

---

## Known-good defaults

| Key | Default | Notes |
|---|---|---|
| `ENABLED` | `true` (after flip) | The gate. |
| `BASE_URL` | `http://meeting-ai-service:8080` (test) | No trailing slash. |
| `SEGMENT_WINDOW` | `5` | Nth transcript flushes. Bigger = fewer POSTs, coarser live view. |
| `TIMEOUT_MS` | `5000` | WebClient connect + response cap. |

---

## Guarantees the code makes (do NOT try to re-verify by breaking things
in prod)

- **Broken meeting-ai** never fails the STT forwarding path. Publish
  errors increment `audio_gw_live_analyze_publish_error_total` and are
  logged with safe fields only (no transcript text).
- **PII discipline** — transcript text IS the POST body (meeting-ai's
  redactor applies KVKK PII guard before the LLM), but audio-gateway
  logs the failure class + meeting_id length + sequence, never the text.

Ref: platform-backend#902 (İ4 code), gitops#2728 (env baseline),
     gitops#2730 (digest bump), platform-ai#270 (SSE relay hub).
