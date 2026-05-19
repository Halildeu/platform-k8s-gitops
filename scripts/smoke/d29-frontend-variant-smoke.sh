#!/usr/bin/env bash
# scripts/smoke/d29-frontend-variant-smoke.sh
#
# ADR-0022 — env-baked frontend prod-variant transient smoke.
#
# platform-web frontend env-baked bir Vite SPA'dir: API base URL, KC realm,
# feature-flag build-time'da bundle'a gomulur. Her commit iki artifact uretir
# (testai + prod). Test cluster testai variant'i kosar; prod variant hicbir
# yerde kosmaz -> D29 ledger akisi normal yolla uygulanamaz.
#
# Bu script prod-variant artifact'ini k3d-test'te (platform-test ns) TRANSIENT
# olarak kosturup smoke eder ve ledger-uyumlu bir JSON evidence raporu uretir.
# Yonetilen `frontend` (testai) workload'ina dokunmaz; benzersiz per-run
# label + isim kullanir; `trap` ile her cikista temizler.
#
# Tier eslemesi (ADR-0022 D3):
#   d29_up          GREEN  rollout + pod Ready + imageID digest match
#                          + /build-info.json .sha == kaynak commit SHA
#   d29_functional  GREEN  / 200 + entry asset 200 + env-baking assertion
#                          (bundle'da forbidden-host YOK, prod-host VAR)
#                          + canli ai.acik.com read-only probe (5xx/000 degil)
#   d29_zanzibar    AMBER  statik SPA, Zanzibar duzlemi yok
#                          (jwt_validates:false); allow_deny_synthetic SKIP
#
# Kullanim:
#   d29-frontend-variant-smoke.sh \
#     --image ghcr.io/halildeu/platform-web-frontend@sha256:<64hex> \
#     --git-sha <40-hex source commit SHA> \
#     [--context k3d-test] [--namespace platform-test] \
#     [--expected-host ai.acik.com] \
#     [--forbidden-hosts testai.acik.com,localhost:8080] \
#     [--prod-probe-base https://ai.acik.com] [--prod-realm serban] \
#     [--pull-secret ghcr-pull] [--report <path>] [--issue 820] \
#     [--pf-port 18080] [--keep]
#
# Exit:
#   0  d29_up GREEN + d29_functional GREEN (promotion-eligible; d29_zanzibar
#      AMBER beklenen)
#   1  en az bir tier RED
#   2  execution error (cluster unreachable / apply fail / preflight fail)

set -uo pipefail

# --- defaults ---
IMAGE=""
GIT_SHA=""
CONTEXT="k3d-test"
NAMESPACE="platform-test"
EXPECTED_HOST="ai.acik.com"
FORBIDDEN_HOSTS="testai.acik.com,localhost:8080"
PROD_PROBE_BASE="https://ai.acik.com"
PROD_REALM="serban"
PULL_SECRET="ghcr-pull"
REPORT=""
ISSUE="820"
KEEP="false"
ROLLOUT_TIMEOUT="180s"
PF_PORT="18080"

usage() { sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --image)           IMAGE="$2"; shift 2 ;;
    --git-sha)         GIT_SHA="$2"; shift 2 ;;
    --context)         CONTEXT="$2"; shift 2 ;;
    --namespace)       NAMESPACE="$2"; shift 2 ;;
    --expected-host)   EXPECTED_HOST="$2"; shift 2 ;;
    --forbidden-hosts) FORBIDDEN_HOSTS="$2"; shift 2 ;;
    --prod-probe-base) PROD_PROBE_BASE="$2"; shift 2 ;;
    --prod-realm)      PROD_REALM="$2"; shift 2 ;;
    --pull-secret)     PULL_SECRET="$2"; shift 2 ;;
    --report)          REPORT="$2"; shift 2 ;;
    --issue)           ISSUE="$2"; shift 2 ;;
    --pf-port)         PF_PORT="$2"; shift 2 ;;
    --keep)            KEEP="true"; shift ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "ERR: unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

[ -n "$IMAGE" ]   || { echo "ERR: --image required" >&2; exit 2; }
[ -n "$GIT_SHA" ] || { echo "ERR: --git-sha required" >&2; exit 2; }

EXPECTED_DIGEST=""
case "$IMAGE" in
  *@sha256:*) EXPECTED_DIGEST="sha256:${IMAGE##*@sha256:}" ;;
esac

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_ID="$(date -u +%Y%m%d%H%M%S)-$$"
NAME="fe-variant-smoke-${RUN_ID}"
REPORT="${REPORT:-/tmp/${NAME}.json}"
BUNDLE_FILE="/tmp/${NAME}-bundle.txt"
PF_LOG="/tmp/${NAME}-pf.log"
PF_PID=""

log() { echo "[d29-fe-smoke] $*" >&2; }

cleanup() {
  [ -n "$PF_PID" ] && kill "$PF_PID" >/dev/null 2>&1
  if [ "$KEEP" = "true" ]; then
    log "--keep set — transient resources retained (smoke-run=${RUN_ID})"
  else
    kubectl --context "$CONTEXT" -n "$NAMESPACE" delete deploy,svc \
      -l "evidence.platform/smoke-run=${RUN_ID}" --ignore-not-found --wait=false \
      >/dev/null 2>&1
    log "transient resources deleted (smoke-run=${RUN_ID})"
  fi
  rm -f "$BUNDLE_FILE" "$PF_LOG" >/dev/null 2>&1
  return 0
}
trap cleanup EXIT

# --- preflight ---
log "preflight: context=$CONTEXT ns=$NAMESPACE image=$IMAGE"
kubectl --context "$CONTEXT" -n "$NAMESPACE" get ns "$NAMESPACE" >/dev/null 2>&1 \
  || { echo "ERR: namespace $NAMESPACE not reachable on context $CONTEXT" >&2; exit 2; }
kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$PULL_SECRET" >/dev/null 2>&1 \
  || { echo "ERR: imagePullSecret '$PULL_SECRET' not found in $NAMESPACE" >&2; exit 2; }

# --- apply transient manifest ---
log "applying transient Deployment+Service $NAME"
if ! cat <<YAML | kubectl --context "$CONTEXT" -n "$NAMESPACE" apply -f - >/dev/null 2>&1
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${NAME}
  labels:
    evidence.platform/transient-smoke: frontend-prod-variant
    evidence.platform/smoke-run: "${RUN_ID}"
    evidence.platform/issue: "${ISSUE}"
spec:
  replicas: 1
  progressDeadlineSeconds: 150
  selector:
    matchLabels:
      evidence.platform/smoke-run: "${RUN_ID}"
  template:
    metadata:
      labels:
        evidence.platform/transient-smoke: frontend-prod-variant
        evidence.platform/smoke-run: "${RUN_ID}"
        evidence.platform/issue: "${ISSUE}"
    spec:
      automountServiceAccountToken: false
      imagePullSecrets:
        - name: ${PULL_SECRET}
      securityContext:
        runAsNonRoot: true
        runAsUser: 101
        runAsGroup: 101
        fsGroup: 101
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: frontend
          image: ${IMAGE}
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
          resources:
            requests:
              memory: "32Mi"
              cpu: "10m"
            limits:
              memory: "128Mi"
              cpu: "200m"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: cache
              mountPath: /var/cache/nginx
            - name: run
              mountPath: /var/run
      volumes:
        - name: tmp
          emptyDir: {}
        - name: cache
          emptyDir: {}
        - name: run
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: ${NAME}
  labels:
    evidence.platform/transient-smoke: frontend-prod-variant
    evidence.platform/smoke-run: "${RUN_ID}"
spec:
  type: ClusterIP
  selector:
    evidence.platform/smoke-run: "${RUN_ID}"
  ports:
    - name: http
      port: 80
      targetPort: http
YAML
then
  echo "ERR: kubectl apply failed for transient manifest" >&2
  exit 2
fi

# ============ Tier d29_up ============
UP_STATUS="RED"
ROLLOUT_OK="false"
log "waiting rollout (timeout ${ROLLOUT_TIMEOUT})"
if kubectl --context "$CONTEXT" -n "$NAMESPACE" rollout status "deploy/${NAME}" \
     --timeout="$ROLLOUT_TIMEOUT" >/dev/null 2>&1; then
  ROLLOUT_OK="true"
fi

POD="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
  -l "evidence.platform/smoke-run=${RUN_ID}" --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"

READY=""
IMAGE_ID=""
RESOLVED_DIGEST=""
if [ -n "$POD" ]; then
  READY="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod "$POD" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)"
  IMAGE_ID="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod "$POD" \
    -o jsonpath='{.status.containerStatuses[0].imageID}' 2>/dev/null || true)"
  RESOLVED_DIGEST="$(printf '%s' "$IMAGE_ID" | sed -E 's|^.*@(sha256:[a-f0-9]{64})$|\1|')"
fi

DIGEST_VERDICT="n/a"
if [ -n "$EXPECTED_DIGEST" ]; then
  if [ "$RESOLVED_DIGEST" = "$EXPECTED_DIGEST" ]; then
    DIGEST_VERDICT="match"
  else
    DIGEST_VERDICT="MISMATCH(expected=${EXPECTED_DIGEST} actual=${RESOLVED_DIGEST:-none})"
  fi
fi

# --- port-forward for HTTP tiers ---
PF_UP="false"
kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward "svc/${NAME}" \
  "${PF_PORT}:80" >"$PF_LOG" 2>&1 &
PF_PID=$!
for ((i=1; i<=20; i++)); do
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:${PF_PORT}/" 2>/dev/null; then
    PF_UP="true"; break
  fi
  sleep 1
done

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 12 "$1" 2>/dev/null || echo "000"; }
http_body() { curl -s --max-time 12 "$1" 2>/dev/null || true; }

# --- /build-info.json .sha (part of d29_up) ---
BUILDINFO_SHA=""
SHA_VERDICT="unknown"
if [ "$PF_UP" = "true" ]; then
  BUILDINFO="$(http_body "http://127.0.0.1:${PF_PORT}/build-info.json")"
  BUILDINFO_SHA="$(printf '%s' "$BUILDINFO" | jq -r '.sha // empty' 2>/dev/null || true)"
  if [ -n "$BUILDINFO_SHA" ]; then
    case "$GIT_SHA" in
      "$BUILDINFO_SHA"*) SHA_VERDICT="match" ;;
      *) case "$BUILDINFO_SHA" in
           "$GIT_SHA"*) SHA_VERDICT="match" ;;
           *) SHA_VERDICT="MISMATCH(buildinfo=${BUILDINFO_SHA} expected=${GIT_SHA})" ;;
         esac ;;
    esac
  else
    SHA_VERDICT="MISSING(/build-info.json .sha empty)"
  fi
fi

if [ "$ROLLOUT_OK" = "true" ] && [ "$READY" = "True" ] \
   && { [ "$DIGEST_VERDICT" = "match" ] || [ "$DIGEST_VERDICT" = "n/a" ]; } \
   && [ "$SHA_VERDICT" = "match" ]; then
  UP_STATUS="GREEN"
fi
UP_DETAILS="rollout=${ROLLOUT_OK} pod=${POD:-none} ready=${READY:-none} digest=${DIGEST_VERDICT} build_info_sha=${SHA_VERDICT}"
log "d29_up: $UP_STATUS — $UP_DETAILS"

# ============ Tier d29_functional ============
FN_STATUS="RED"
FN_DETAILS=""
ROOT_CODE="000"; ENTRY_PATH=""; ENTRY_CODE="000"
FORBIDDEN_HIT=""; REQUIRED_OK="false"
PROBE_ROOT="000"; PROBE_OIDC="000"

if [ "$PF_UP" != "true" ]; then
  FN_DETAILS="port-forward tunnel did not bind on 127.0.0.1:${PF_PORT}"
else
  ROOT_CODE="$(http_code "http://127.0.0.1:${PF_PORT}/")"
  INDEX_HTML="$(http_body "http://127.0.0.1:${PF_PORT}/")"

  # asset js paths referenced by index.html (entry + modulepreload chunks)
  ASSET_PATHS="$(printf '%s' "$INDEX_HTML" | grep -oE '/assets/[A-Za-z0-9._/-]+\.js' | sort -u || true)"
  ENTRY_PATH="$(printf '%s\n' "$ASSET_PATHS" | grep -E '/assets/index[-.]' | head -1 || true)"
  [ -z "$ENTRY_PATH" ] && ENTRY_PATH="$(printf '%s\n' "$ASSET_PATHS" | head -1 || true)"
  [ -n "$ENTRY_PATH" ] && ENTRY_CODE="$(http_code "http://127.0.0.1:${PF_PORT}${ENTRY_PATH}")"

  # env-baking: concat index.html + all eager asset js, then string-assert
  : > "$BUNDLE_FILE"
  printf '%s\n' "$INDEX_HTML" >> "$BUNDLE_FILE"
  if [ -n "$ASSET_PATHS" ]; then
    while IFS= read -r p; do
      [ -n "$p" ] || continue
      http_body "http://127.0.0.1:${PF_PORT}${p}" >> "$BUNDLE_FILE"
      printf '\n' >> "$BUNDLE_FILE"
    done <<< "$ASSET_PATHS"
  fi

  IFS=',' read -ra FHOSTS <<< "$FORBIDDEN_HOSTS"
  for fh in "${FHOSTS[@]}"; do
    [ -n "$fh" ] || continue
    if grep -qF "$fh" "$BUNDLE_FILE" 2>/dev/null; then
      FORBIDDEN_HIT="${FORBIDDEN_HIT}${fh} "
    fi
  done

  if grep -qF "https://${EXPECTED_HOST}" "$BUNDLE_FILE" 2>/dev/null; then
    REQUIRED_OK="true"
  fi

  # live prod surface read-only probe (from host — real internet egress)
  PROBE_ROOT="$(http_code "${PROD_PROBE_BASE}/")"
  PROBE_OIDC="$(http_code "${PROD_PROBE_BASE}/realms/${PROD_REALM}/.well-known/openid-configuration")"
  PROBE_OK="true"
  case "$PROBE_ROOT" in 5??|000) PROBE_OK="false" ;; esac
  [ "$PROBE_OIDC" = "200" ] || PROBE_OK="false"

  if [ "$ROOT_CODE" = "200" ] && [ -n "$ENTRY_PATH" ] && [ "$ENTRY_CODE" = "200" ] \
     && [ -z "$FORBIDDEN_HIT" ] && [ "$REQUIRED_OK" = "true" ] && [ "$PROBE_OK" = "true" ]; then
    FN_STATUS="GREEN"
  fi
  FN_DETAILS="root=${ROOT_CODE} entry=${ENTRY_PATH:-none}:${ENTRY_CODE} env_baking[forbidden_hit='${FORBIDDEN_HIT:-none}' required_${EXPECTED_HOST}=${REQUIRED_OK}] prod_probe[root=${PROBE_ROOT} oidc_${PROD_REALM}=${PROBE_OIDC}]"
fi
log "d29_functional: $FN_STATUS — $FN_DETAILS"

# endpoints array (schema: minItems 1, each ^/)
FN_EP=("/")
[ -n "$ENTRY_PATH" ] && FN_EP+=("$ENTRY_PATH")
FN_EP+=("/build-info.json")
FN_ENDPOINTS_JSON="$(printf '%s\n' "${FN_EP[@]}" | jq -R . | jq -cs 'unique')"

# ============ Tier d29_zanzibar ============
# Static SPA — no own JWT decoder, no Zanzibar authz plane (jwt_validates:false
# per services.yaml). Honest AMBER (ADR-0022 D3). gate-evidence-check.py accepts
# GREEN|AMBER for jwt_validates:false services; SKIP *status* is NOT accepted —
# tier status is AMBER, sub-field allow_deny_synthetic is SKIP.
ZB_DETAILS="frontend is a static SPA (jwt_validates:false, services.yaml) — no own JWT decoder, no OpenFGA/Zanzibar authz plane. Zanzibar tier not-applicable; AMBER is the honest non-GREEN verdict (ADR-0022)."

# ============ report ============
EXIT_CODE=1
if [ "$UP_STATUS" = "GREEN" ] && [ "$FN_STATUS" = "GREEN" ]; then
  EXIT_CODE=0
fi

jq -n \
  --arg env "test" \
  --arg variant "frontend-prod-variant" \
  --argjson issue "${ISSUE}" \
  --arg image "$IMAGE" \
  --arg digest "${RESOLVED_DIGEST:-}" \
  --arg git_sha "$GIT_SHA" \
  --arg ts "$TS" \
  --arg run_id "$RUN_ID" \
  --argjson exit_code "$EXIT_CODE" \
  --arg up_status "$UP_STATUS" \
  --arg up_details "$UP_DETAILS" \
  --arg fn_status "$FN_STATUS" \
  --arg fn_details "$FN_DETAILS" \
  --argjson fn_endpoints "$FN_ENDPOINTS_JSON" \
  --arg zb_details "$ZB_DETAILS" \
  '{
     environment: $env, variant: $variant, issue: $issue,
     image: $image, image_digest: $digest, git_sha: $git_sha,
     timestamp: $ts, run_id: $run_id, exit_code: $exit_code,
     tiers: {
       d29_up:         { status: $up_status, checked_at: $ts, details: $up_details },
       d29_functional: { status: $fn_status, checked_at: $ts, details: $fn_details, endpoints: $fn_endpoints },
       d29_zanzibar:   { status: "AMBER", checked_at: $ts, details: $zb_details, allow_deny_synthetic: "SKIP" }
     }
   }' | tee "$REPORT"

log "report written: $REPORT"
log "verdict: d29_up=$UP_STATUS d29_functional=$FN_STATUS d29_zanzibar=AMBER exit=$EXIT_CODE"
exit "$EXIT_CODE"
