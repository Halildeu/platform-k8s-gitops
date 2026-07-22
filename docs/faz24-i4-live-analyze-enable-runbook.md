# RB Faz 24 I4 - audio-gateway live-analyze test enable + rollback

**Owner**: platform-ops (`k3d-test` only)
**Prerequisite**: the governed meeting-ai exact-SHA rollout and direct relay
smoke must pass before this desired-state is merged.
**Blast radius**: `audio-gateway` in `platform-test`; egress is limited to
`10.99.0.2/32` TCP `8300`. Production is excluded and remains a separate D30
owner gate.
**Reversible**: yes - revert the exact merged PR and let ArgoCD reconcile.

This runbook keeps three different proofs separate:

1. **Direct relay**: GPU-host `/analyze/live` publish -> SSE.
2. **Cluster bridge**: the same relay through the selectorless Service from the
   actual audio-gateway network identity.
3. **Gateway-triggered path**: real desktop transcript segments ->
   audio-gateway segment window -> meeting-ai -> SSE.

Only the third proof exercises the feature enabled by this change.

---

## GitOps ordering

The test ConfigMap and narrow NetworkPolicy carry ArgoCD sync wave `17`.
`Deployment/audio-gateway` carries wave `18`. The target URL and TCP `8300`
policy are therefore reconciled before a new process starts with the enabled
flag. This is a post-sync acceptance model; it is not a pre-enable pod
reachability proof.

The application is fail-contained when meeting-ai is unavailable: STT delivery
continues while the live-analysis attempt records an error counter. A failed
post-sync gate still requires immediate rollback to avoid repeated failed
publishes.

---

## Pre-merge remote runtime gate

Run on `staging-sw`, where the WireGuard route and repository checkout are
available. Do not put tokens or transcript content in command output.

```bash
cd /path/to/platform-k8s-gitops

# A waiting protected-environment job is not deployment evidence.
gh run view <gpu-rollout-run-id> --json status,conclusion,jobs,url

# Direct GPU-host health and direct publish -> SSE relay proof.
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -m 5 \
  http://10.99.0.2:8300/health
MEETING_AI_URL=http://10.99.0.2:8300 \
  scripts/faz24/live-analyze-sse-smoke.sh
```

Expected: health `200`, smoke exit `0`, and rollout evidence naming the expected
immutable revision. This proves direct relay only; it does not prove the
cluster bridge or audio-gateway trigger.

---

## Enable through GitOps

Do not run `kubectl apply`, `kubectl patch`, `kubectl set env`, or an imperative
rollout restart against the shared test workload.

1. Verify the PR exact head, CI, render guard, and independent review.
2. Merge only after the pre-merge remote runtime gate passes.
3. Let the `platform-test` ArgoCD Application reconcile `main`.
4. Observe wave `17` resources before the wave `18` Deployment rollout.

```bash
CTX=k3d-test
NS=platform-test

ARGO_STATE="$(kubectl --context "$CTX" -n argocd get application platform-test \
  -o jsonpath='{.status.sync.status}{"|"}{.status.health.status}')"
test "$ARGO_STATE" = "Synced|Healthy" || {
  printf 'FAIL Argo state=%s expected=Synced|Healthy\n' "$ARGO_STATE" >&2
  exit 1
}
kubectl --context "$CTX" -n "$NS" rollout status deploy/audio-gateway \
  --timeout=180s
```

Argo `Synced` and rollout success are **Up** evidence only. Continue with every
post-sync gate before requesting attended product acceptance.

---

## Post-sync gate A - desired-state and pod identity

```bash
EXPECTED_IMAGE="$(kustomize build kustomize/overlays/test | python3 -c '
import sys, yaml
docs = yaml.safe_load_all(sys.stdin)
matches = [c["image"] for d in docs if isinstance(d, dict)
           and d.get("kind") == "Deployment"
           and d.get("metadata", {}).get("name") == "audio-gateway"
           for c in d["spec"]["template"]["spec"]["containers"]
           if c.get("name") == "audio-gateway"]
if len(matches) != 1:
    raise SystemExit(f"expected one rendered audio-gateway image, found {len(matches)}")
print(matches[0])')"
EXPECTED_DIGEST="${EXPECTED_IMAGE##*@}"
[[ "$EXPECTED_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1

LIVE_DEPLOY_IMAGE="$(kubectl --context "$CTX" -n "$NS" \
  get deploy audio-gateway \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="audio-gateway")].image}')"
test "$LIVE_DEPLOY_IMAGE" = "$EXPECTED_IMAGE"

scripts/deploy/verify-pod-digest.sh \
  --context "$CTX" \
  --namespace "$NS" \
  --selector 'app.kubernetes.io/name=audio-gateway' \
  --expected-digest "$EXPECTED_DIGEST"

PODS_JSON="$(kubectl --context "$CTX" -n "$NS" get pod \
  -l app.kubernetes.io/name=audio-gateway \
  --field-selector=status.phase=Running -o json)"
test "$(printf '%s' "$PODS_JSON" | jq \
  '[.items[] | select(.metadata.deletionTimestamp == null)] | length')" -eq 1
POD="$(printf '%s' "$PODS_JSON" | jq -er \
  '.items[] | select(.metadata.deletionTimestamp == null) | .metadata.name')"

test "$(kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
  printenv AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED)" = "true"
test "$(kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
  printenv AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL)" \
  = "http://meeting-ai-service:8080"

kubectl --context "$CTX" -n "$NS" get networkpolicy \
  allow-audio-gateway-egress-live-stt-mtls -o json | jq -e '
    .spec == {
      podSelector: {matchLabels: {"app.kubernetes.io/name": "audio-gateway"}},
      policyTypes: ["Egress"],
      egress: [{
        to: [{ipBlock: {cidr: "10.99.0.2/32"}}],
        ports: [
          {protocol: "TCP", port: 8243},
          {protocol: "TCP", port: 8300}
        ]
      }]
    }' >/dev/null
```

Expected: immutable audio-gateway image ID, `ENABLED=true`, canonical bridge
URL, and only the test `/32` TCP `8243` + `8300` egress contract.

---

## Post-sync gate B - bridge relay from the real network identity

The current live image contains `/usr/bin/bash` and `/usr/bin/curl`; verify
those tools again. Stream the existing smoke into the actual pod so the probe
is subject to the same NetworkPolicies as audio-gateway.

```bash
kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
  sh -c 'command -v bash && command -v curl'

kubectl --context "$CTX" -n "$NS" exec -i "$POD" -- \
  env MEETING_AI_URL=http://meeting-ai-service:8080 \
      TMPDIR=/tmp TIMEOUT_SEC=15 bash -s \
  < scripts/faz24/live-analyze-sse-smoke.sh
```

Expected: smoke exit `0`. This proves the selectorless Service, Endpoints,
NetworkPolicy, meeting-ai publish, and SSE relay. It still bypasses the
audio-gateway segment-window trigger and is not gateway functional acceptance.

---

## Post-sync gate C - exact metrics

```bash
METRICS="$(kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
  curl -fsS http://localhost:8081/actuator/prometheus)"

for metric in \
  audio_gw_live_analyze_publish_total \
  audio_gw_live_analyze_publish_success_total \
  audio_gw_live_analyze_publish_error_total \
  audio_gw_live_analyze_drop_total
do
  count="$(printf '%s\n' "$METRICS" \
    | grep -Ec "^${metric}(\\{|[[:space:]]|$)" || true)"
  test "$count" -eq 1 || {
    printf 'FAIL metric=%s matches=%s\n' "$metric" "$count" >&2
    exit 1
  }
done
```

This proves registration of exactly four expected series. It does not prove a
successful publish until the counters move under real gateway input.

---

## Post-sync gate D - gateway-triggered attended acceptance

Use a fresh packaged-desktop meeting ID. Subscribe before recording, then
produce at least five final transcript segments so the configured segment
window flushes. Do not persist or attach raw SSE/transcript payloads to
evidence.

Terminal 1:

```bash
MEETING_ID=<fresh-meeting-uuid>
kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
  sh -c "curl -fsS --no-buffer --max-time 180 \
    http://meeting-ai-service:8080/analyze/live/stream/$MEETING_ID \
    | grep -m1 -q '^event: analysis$'"
```

Terminal 2, before recording:

```bash
metric_value() {
  kubectl --context "$CTX" -n "$NS" exec "$POD" -- \
    curl -fsS http://localhost:8081/actuator/prometheus \
    | awk -v name="$1" '$1 == name {print $2; exit}'
}

BEFORE_TOTAL="$(metric_value audio_gw_live_analyze_publish_total)"
BEFORE_SUCCESS="$(metric_value audio_gw_live_analyze_publish_success_total)"
BEFORE_ERROR="$(metric_value audio_gw_live_analyze_publish_error_total)"
```

Start the packaged desktop recording for `MEETING_ID`, speak until at least
five final transcript segments are visible, and stop normally. Then:

```bash
AFTER_TOTAL="$(metric_value audio_gw_live_analyze_publish_total)"
AFTER_SUCCESS="$(metric_value audio_gw_live_analyze_publish_success_total)"
AFTER_ERROR="$(metric_value audio_gw_live_analyze_publish_error_total)"

awk -v before="$BEFORE_TOTAL" -v after="$AFTER_TOTAL" \
  'BEGIN { exit !(after > before) }'
awk -v before="$BEFORE_SUCCESS" -v after="$AFTER_SUCCESS" \
  'BEGIN { exit !(after > before) }'
test "$AFTER_ERROR" = "$BEFORE_ERROR"
```

Acceptance requires all of these together for the same meeting ID:

- Terminal 1 exits `0` after an SSE `analysis` event.
- publish total and success counters increase.
- publish error does not increase.
- packaged desktop continues its live transcript path without a new recording
  failure.

If any gate fails, do not classify it as meeting-ai-only. Roll back and
diagnose the exact failed hop.

---

## Rollback

Revert the exact merged/squash commit for this PR; do not revert one branch
commit independently. Submit and merge the rollback through GitOps.

```bash
git switch main
git pull --ff-only
: "${LANDED_SHA:?set LANDED_SHA to this PR's exact origin/main landed SHA}"
git merge-base --is-ancestor "$LANDED_SHA" origin/main
ROLLBACK_BRANCH="rollback/faz24-live-analyze-$(date -u +%Y%m%dT%H%M%SZ)"
git switch -c "$ROLLBACK_BRANCH"

PARENT_COUNT="$(git rev-list --parents -n 1 "$LANDED_SHA" | awk '{print NF - 1}')"
case "$PARENT_COUNT" in
  1) git revert "$LANDED_SHA" ;;
  2) git revert -m 1 "$LANDED_SHA" ;;
  *) printf 'Unsupported parent count: %s\n' "$PARENT_COUNT" >&2; exit 1 ;;
esac

git push -u origin HEAD
# Open and merge the rollback PR under repository gates.
```

`LANDED_SHA` is the commit created on `origin/main` by merging this PR, not one
of the branch review heads. The parent-count branch supports both squash and
two-parent GitHub merge commits without guessing the mainline parent.

The revert must restore all four desired-state properties together:

- live-analysis flag `false`;
- base URL empty;
- live-analysis pod-template revision removed/changed, causing a rollout;
- TCP `8300` removed while existing TCP `8243` direct-STT egress remains.

After ArgoCD reconciles the rollback, verify:

```bash
kubectl --context k3d-test -n platform-test rollout status \
  deploy/audio-gateway --timeout=180s
kubectl --context k3d-test -n platform-test exec deploy/audio-gateway -- env \
  | grep AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE
kubectl --context k3d-test -n platform-test get networkpolicy \
  allow-audio-gateway-egress-live-stt-mtls -o yaml \
  | grep -q 'port: 8300' && exit 1 || true
```

Expected: `ENABLED=false`, URL empty, rollout on the reverted pod template, and
no TCP `8300` in the live policy. Production is not part of this runbook.

Ref: platform-backend#902, gitops#2728/#2730, platform-ai#244/#270.
