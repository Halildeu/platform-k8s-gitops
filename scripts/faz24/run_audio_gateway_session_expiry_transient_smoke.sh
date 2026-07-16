#!/usr/bin/env bash
# ADR-0022/0023 transient runtime proof for platform-backend#841.
set -Eeuo pipefail
umask 077

KUBECTL_CONTEXT="${KUBECTL_CONTEXT:-k3d-test}"
NAMESPACE="${NAMESPACE:-platform-test}"
SOURCE_DEPLOYMENT="${SOURCE_DEPLOYMENT:-audio-gateway}"
EXPECTED_IMAGE="${EXPECTED_IMAGE:-}"
TRANSIENT_TTL_SECONDS="${TRANSIENT_TTL_SECONDS:-900}"
OUT_DIR="${OUT_DIR:-/tmp/faz24-audio-gateway-session-expiry}"
RUN_ID_RAW="${GITHUB_RUN_ID:-$(date -u +%y%m%d%H%M%S)}-${GITHUB_RUN_ATTEMPT:-1}-${RANDOM}-${RANDOM}"
RUN_ID="$(printf '%s' "${RUN_ID_RAW}" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-32)"
JOB_NAME="ag-expiry-${RUN_ID}"
NETPOL_NAME="${JOB_NAME}-stt"
PORT_FORWARD_LOG=""
PORT_FORWARD_PID=""
APP_PORT=""
METRICS_PORT=""
CLEANUP_DONE="false"

if [[ -z "${EXPECTED_IMAGE}" || "${EXPECTED_IMAGE}" != *@sha256:* ]]; then
  echo "ERROR: EXPECTED_IMAGE must be an immutable image@sha256 reference" >&2
  exit 2
fi
if [[ "${KUBECTL_CONTEXT}" != "k3d-test" || "${NAMESPACE}" != "platform-test" ]]; then
  echo "ERROR: this smoke is restricted to k3d-test/platform-test" >&2
  exit 2
fi
if [[ ! "${TRANSIENT_TTL_SECONDS}" =~ ^[0-9]+$ \
    || "${TRANSIENT_TTL_SECONDS}" -lt 120 \
    || "${TRANSIENT_TTL_SECONDS}" -gt 1800 ]]; then
  echo "ERROR: TRANSIENT_TTL_SECONDS must be between 120 and 1800" >&2
  exit 2
fi

mkdir -p "${OUT_DIR}"
PORT_FORWARD_LOG="$(mktemp "${OUT_DIR}/port-forward.XXXXXX.log")"

cleanup_resources() {
  if [[ "${CLEANUP_DONE}" == "true" ]]; then
    return 0
  fi
  local cleanup_rc=0
  local found=""
  if [[ -n "${PORT_FORWARD_PID}" ]]; then
    kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    wait "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    PORT_FORWARD_PID=""
  fi
  kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
    delete job "${JOB_NAME}" --ignore-not-found --cascade=foreground \
    --wait=true --timeout=60s >/dev/null 2>&1 || cleanup_rc=1
  kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
    delete networkpolicy "${NETPOL_NAME}" --ignore-not-found \
    --wait=true --timeout=30s >/dev/null 2>&1 || cleanup_rc=1

  if ! found="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
      get job "${JOB_NAME}" --ignore-not-found -o name 2>/dev/null)" \
      || [[ -n "${found}" ]]; then
    cleanup_rc=1
  fi
  if ! found="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
      get networkpolicy "${NETPOL_NAME}" --ignore-not-found -o name 2>/dev/null)" \
      || [[ -n "${found}" ]]; then
    cleanup_rc=1
  fi

  rm -f "${PORT_FORWARD_LOG}"
  if [[ "${cleanup_rc}" == "0" ]]; then
    CLEANUP_DONE="true"
  fi
  return "${cleanup_rc}"
}

cleanup() {
  local rc="$?"
  local cleanup_ok="false"
  local attempt
  trap - EXIT INT TERM
  set +e
  for attempt in 1 2 3; do
    if cleanup_resources; then
      cleanup_ok="true"
      break
    fi
    sleep "${attempt}"
  done
  if [[ "${cleanup_ok}" != "true" ]]; then
    echo "ERROR: transient smoke cleanup could not be verified" >&2
    if [[ "${rc}" == "0" ]]; then
      rc=1
    fi
  fi
  exit "${rc}"
}
trap cleanup EXIT INT TERM

for command in kubectl jq curl python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "ERROR: required command missing: ${command}" >&2
    exit 2
  }
done

SOURCE_IMAGE="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get deployment "${SOURCE_DEPLOYMENT}" \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="audio-gateway")].image}')"
if [[ "${SOURCE_IMAGE}" != "${EXPECTED_IMAGE}" ]]; then
  echo "ERROR: live source image does not match EXPECTED_IMAGE" >&2
  exit 1
fi

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get deployment "${SOURCE_DEPLOYMENT}" -o json \
  | jq \
      --arg name "${JOB_NAME}" \
      --arg run "${RUN_ID}" \
      --arg image "${EXPECTED_IMAGE}" \
      --argjson ttl "${TRANSIENT_TTL_SECONDS}" '
      {
        apiVersion: "batch/v1",
        kind: "Job",
        metadata: {
          name: $name,
          namespace: "platform-test",
          labels: {
            "app.kubernetes.io/name": $name,
            "app.kubernetes.io/component": "runtime-evidence",
            "app.kubernetes.io/part-of": "platform",
            "evidence.platform/transient-smoke": "audio-gateway-session-expiry",
            "evidence.platform/smoke-run": $run
          }
        },
        spec: {
          backoffLimit: 0,
          activeDeadlineSeconds: $ttl,
          ttlSecondsAfterFinished: 60,
          template: .spec.template
        }
      }
      | .spec.template.metadata.labels = {
          "app.kubernetes.io/name": $name,
          "app.kubernetes.io/component": "runtime-evidence",
          "app.kubernetes.io/part-of": "platform",
          "evidence.platform/transient-smoke": "audio-gateway-session-expiry",
          "evidence.platform/smoke-run": $run
        }
      | .spec.template.metadata.annotations = {
          "evidence.platform/ttl-seconds": ($ttl | tostring),
          "evidence.platform/source-deployment": "audio-gateway"
        }
      | .spec.template.spec.restartPolicy = "Never"
      | .spec.template.spec.containers |= map(
          if .name == "audio-gateway" then
            .envFrom = ((.envFrom // []) | map(select(
              .secretRef.name != "audio-gateway-secrets"
            )))
          else . end
        )
      | .spec.template.spec.containers |= map(
          if .name == "audio-gateway" then
            .image = $image
            | .env = (((.env // []) | map(select(
                .name != "AUDIO_GATEWAY_MAX_SESSION_MINUTES"
                and .name != "AUDIO_GATEWAY_SESSION_EXPIRY_SWEEP_MS"
                and .name != "AUDIO_GATEWAY_BOUNDS_MAX_ACTIVE_SESSIONS"
                and .name != "AUDIO_GATEWAY_DIRECT_STT_AGGREGATION_MAX_BUFFERED_SESSIONS"
                and .name != "AUDIO_GATEWAY_DISPATCHER_MODE"
                and .name != "AUDIO_GATEWAY_AUDIT_REDIS_ENABLED"
                and .name != "AUDIO_GATEWAY_HEALTH_REDIS_ENABLED"
                and .name != "AUDIO_GATEWAY_DIRECT_STT_TRANSCRIPT_RESULT_STREAM_ENABLED"
              ))) + [
                {name: "AUDIO_GATEWAY_MAX_SESSION_MINUTES", value: "1"},
                {name: "AUDIO_GATEWAY_SESSION_EXPIRY_SWEEP_MS", value: "1000"},
                {name: "AUDIO_GATEWAY_BOUNDS_MAX_ACTIVE_SESSIONS", value: "1"},
                {name: "AUDIO_GATEWAY_DIRECT_STT_AGGREGATION_MAX_BUFFERED_SESSIONS", value: "1"},
                {name: "AUDIO_GATEWAY_DISPATCHER_MODE", value: "noop"},
                {name: "AUDIO_GATEWAY_AUDIT_REDIS_ENABLED", value: "false"},
                {name: "AUDIO_GATEWAY_HEALTH_REDIS_ENABLED", value: "false"},
                {name: "AUDIO_GATEWAY_DIRECT_STT_TRANSCRIPT_RESULT_STREAM_ENABLED", value: "false"}
              ])
          else . end
        )' \
  | kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" apply -f - >/dev/null

JOB_UID="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get job "${JOB_NAME}" -o jsonpath='{.metadata.uid}')"
jq -n \
  --arg name "${NETPOL_NAME}" \
  --arg job "${JOB_NAME}" \
  --arg uid "${JOB_UID}" \
  --arg app "${JOB_NAME}" \
  --arg run "${RUN_ID}" '
  {
    apiVersion: "networking.k8s.io/v1",
    kind: "NetworkPolicy",
    metadata: {
      name: $name,
      namespace: "platform-test",
      labels: {
        "app.kubernetes.io/component": "runtime-evidence",
        "app.kubernetes.io/part-of": "platform",
        "evidence.platform/transient-smoke": "audio-gateway-session-expiry",
        "evidence.platform/smoke-run": $run
      },
      ownerReferences: [{
        apiVersion: "batch/v1",
        kind: "Job",
        name: $job,
        uid: $uid,
        controller: true,
        blockOwnerDeletion: false
      }]
    },
    spec: {
      # Additive with the base part-of=platform DNS, intra-namespace and host
      # bridge policies; this rule only adds the test WireGuard STT endpoint.
      podSelector: {matchLabels: {"app.kubernetes.io/name": $app}},
      policyTypes: ["Egress"],
      egress: [{
        to: [{ipBlock: {cidr: "10.99.0.2/32"}}],
        ports: [{protocol: "TCP", port: 8243}]
      }]
    }
  }' \
  | kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" apply -f - >/dev/null

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" wait \
  --for=condition=Ready pod \
  -l "evidence.platform/smoke-run=${RUN_ID}" \
  --timeout=180s >/dev/null

POD_NAME="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get pod -l "evidence.platform/smoke-run=${RUN_ID}" \
  -o jsonpath='{.items[0].metadata.name}')"
POD_UID="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get pod "${POD_NAME}" -o jsonpath='{.metadata.uid}')"
POD_IMAGE_ID="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get pod "${POD_NAME}" \
  -o jsonpath='{.status.containerStatuses[?(@.name=="audio-gateway")].imageID}')"
EXPECTED_DIGEST="${EXPECTED_IMAGE##*@}"
POD_IMAGE_DIGEST="${POD_IMAGE_ID##*@}"
if [[ "${POD_IMAGE_DIGEST}" != "${EXPECTED_DIGEST}" ]]; then
  echo "ERROR: transient pod imageID does not match EXPECTED_IMAGE" >&2
  exit 1
fi

kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" port-forward \
  --address 127.0.0.1 "pod/${POD_NAME}" ":8210" ":8081" \
  >"${PORT_FORWARD_LOG}" 2>&1 &
PORT_FORWARD_PID="$!"

for _ in {1..30}; do
  if ! kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1; then
    echo "ERROR: kubectl port-forward exited before port allocation" >&2
    exit 1
  fi
  APP_PORT="$(sed -nE 's/^Forwarding from 127\.0\.0\.1:([0-9]+) -> 8210$/\1/p' \
    "${PORT_FORWARD_LOG}" | head -n1)"
  METRICS_PORT="$(sed -nE 's/^Forwarding from 127\.0\.0\.1:([0-9]+) -> 8081$/\1/p' \
    "${PORT_FORWARD_LOG}" | head -n1)"
  if [[ -n "${APP_PORT}" && -n "${METRICS_PORT}" ]]; then
    break
  fi
  sleep 1
done
if [[ -z "${APP_PORT}" || -z "${METRICS_PORT}" ]]; then
  echo "ERROR: kubectl port-forward did not allocate both loopback ports" >&2
  exit 1
fi

for _ in {1..30}; do
  if ! kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1; then
    echo "ERROR: kubectl port-forward exited before readiness" >&2
    exit 1
  fi
  if curl --silent --show-error --fail \
    "http://127.0.0.1:${METRICS_PORT}/actuator/health/readiness" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl --silent --show-error --fail \
  "http://127.0.0.1:${METRICS_PORT}/actuator/health/readiness" >/dev/null
kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1 \
  || { echo "ERROR: kubectl port-forward exited after readiness" >&2; exit 1; }

CHAIN_OUT_DIR="${OUT_DIR}/${RUN_ID}"
mkdir -p "${CHAIN_OUT_DIR}"
KC_REALM="platform-test" \
KC_CONTAINER="platform-kc-test" \
KC_BASE_URL="http://127.0.0.1:8082" \
KC_INTERNAL_SERVER="http://localhost:8080" \
KC_ADMIN_TRANSPORT="rest" \
CLIENT_ID="platform-desktop" \
RESOURCE_CLIENT_ID="audio-gateway-service" \
BASE_URL="https://testai.acik.com" \
EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test" \
RUN_EXTERNAL_SMOKE=0 \
RUN_SESSION_EXPIRY_SMOKE=1 \
SESSION_EXPIRY_AUDIO_BASE_URL="http://127.0.0.1:${APP_PORT}" \
SESSION_EXPIRY_METRICS_BASE_URL="http://127.0.0.1:${METRICS_PORT}" \
SESSION_EXPIRY_EXPECTED_IMAGE="${EXPECTED_IMAGE}" \
SESSION_EXPIRY_POD_UID="${POD_UID}" \
OUT_DIR="${CHAIN_OUT_DIR}" \
bash scripts/faz24/run-platform-desktop-token-evidence-chain.sh

kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1 \
  || { echo "ERROR: kubectl port-forward exited during smoke" >&2; exit 1; }
POST_POD_UID="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get pod "${POD_NAME}" -o jsonpath='{.metadata.uid}')"
POST_POD_IMAGE_ID="$(kubectl --context "${KUBECTL_CONTEXT}" -n "${NAMESPACE}" \
  get pod "${POD_NAME}" \
  -o jsonpath='{.status.containerStatuses[?(@.name=="audio-gateway")].imageID}')"
if [[ "${POST_POD_UID}" != "${POD_UID}" || "${POST_POD_IMAGE_ID##*@}" != "${EXPECTED_DIGEST}" ]]; then
  echo "ERROR: transient pod runtime binding changed during smoke" >&2
  exit 1
fi

EVIDENCE_FILE="${CHAIN_OUT_DIR}/faz24-audio-gateway-session-expiry-smoke.json"
DIAGNOSTIC_FILE="${CHAIN_OUT_DIR}/faz24-platform-desktop-token-diagnostic.json"
jq -e --arg image "${EXPECTED_IMAGE}" --arg podUid "${POD_UID}" '.status == "pass"
  and .boundaries.sessionRegistryCapacityReused == true
  and .boundaries.aggregationReservationReleased == true
  and .boundaries.negativeInvariantStable == true
  and .runtimeEvidence.image == $image
  and .runtimeEvidence.podUid == $podUid
  and .runtimeEvidence.effectiveOverrides.dispatcherMode == "noop"
  and .runtimeEvidence.effectiveOverrides.auditRedisEnabled == false
  and .runtimeEvidence.effectiveOverrides.redisHealthEnabled == false
  and .runtimeEvidence.effectiveOverrides.transcriptResultStreamEnabled == false' \
  "${EVIDENCE_FILE}" >/dev/null
jq -e '.status == "pass"
  and .cleanup.directGrantsToggled == true
  and .cleanup.directGrantsRestored == true
  and .cleanup.tempUserCreated == true
  and .cleanup.tempUserDeleted == true
  and .cleanup.tokenFileRemoved == true
  and .clientBefore.directAccessGrantsEnabled == .clientAfter.directAccessGrantsEnabled
  and (.clientBefore.protocolMappers | sort_by(.name, .protocolMapper))
      == (.clientAfter.protocolMappers | sort_by(.name, .protocolMapper))
  and .tenantAliasReconcile.credentialsMutated == false' \
  "${DIAGNOSTIC_FILE}" >/dev/null

if ! cleanup_resources; then
  echo "ERROR: transient smoke cleanup could not be verified" >&2
  exit 1
fi
trap - EXIT INT TERM

echo "status=pass"
echo "run_id=${RUN_ID}"
echo "job=${JOB_NAME}"
echo "pod=${POD_NAME}"
echo "pod_uid=${POD_UID}"
echo "image_id=${POD_IMAGE_ID}"
echo "evidence=${EVIDENCE_FILE}"
echo "diagnostic=${DIAGNOSTIC_FILE}"
