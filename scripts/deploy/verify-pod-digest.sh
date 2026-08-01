#!/usr/bin/env bash
# Shared digest verification helper for deploy workflows
# (testai backend/frontend + prod backend/frontend).
#
# Codex 019de00f PARTIAL #1 + sprint "Prod post-cutover compliance" PR-1:
# Multi-replica güvenli pod imageID === expected digest doğrulama.
# Eski tek-pod (items[0]) pattern prod replicas=2 için yetersiz; rolling
# update sırasında eski (Terminating) + yeni (Ready) pod aynı anda label
# match edebilir; eski ReplicaSet pod sızıntısı yakalanmalı.
#
# Davranış (full-replica strict mode):
#   - kubectl get pod -l <selector> --field-selector=status.phase=Running
#   - jq ile non-terminating pod'ları topla (deletionTimestamp == null)
#   - Pod sayısı >= 1 olmalı (boş = fail)
#   - HER non-terminating pod'un imageID normalized digest'i ===
#     expected digest olmalı; tek bir mismatch = fail
#   - Eski ReplicaSet pod sızıntısı bu kontrolü kıracaktır (intended)
#
# Davranış (newest-only legacy mode, --newest-only flag ile):
#   - Sadece en yeni non-terminating Running pod doğrulanır
#   - Tek-replica ortamlar (testai) için backward-compat
#
# Kullanım:
#   verify-pod-digest.sh \
#     --context k3d-prod \
#     --namespace platform-prod \
#     --selector "app.kubernetes.io/name=auth-service" \
#     --expected-digest "sha256:abc...64hex" \
#     [--newest-only]
#
# Exit codes:
#   0 = tüm pod'lar (veya newest-only modda en yeni) digest match
#   1 = pod yok / digest mismatch / format invalid

set -euo pipefail

CONTEXT=""
NAMESPACE=""
SELECTOR=""
EXPECTED_DIGEST=""
EXPECTED_REPOSITORY=""
CRI_NODE_CONTAINER=""
NEWEST_ONLY="false"
CRI_IMAGES_JSON=""

usage() {
  cat <<EOF
Usage: verify-pod-digest.sh \\
  --context <kube-context> \\
  --namespace <ns> \\
  --selector <label-selector> \\
  --expected-digest <sha256:...> \\
  [--expected-repository <registry/repository> \\
   --cri-node-container <container>] \\
  [--newest-only]

Multi-replica strict mode (default): all non-terminating Running pods
matching selector must have imageID == expected-digest.

Newest-only mode (--newest-only): only the newest non-terminating Running
pod is verified (legacy testai single-replica behavior).

CRI alias mode is opt-in and requires both --expected-repository and
--cri-node-container. A mismatching pod imageID is accepted only when exactly
one CRI image record contains both that exact imageID reference and the
canonical expected repository@digest reference.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --context)         CONTEXT="$2"; shift 2 ;;
    --namespace)       NAMESPACE="$2"; shift 2 ;;
    --selector)        SELECTOR="$2"; shift 2 ;;
    --expected-digest) EXPECTED_DIGEST="$2"; shift 2 ;;
    --expected-repository) EXPECTED_REPOSITORY="$2"; shift 2 ;;
    --cri-node-container) CRI_NODE_CONTAINER="$2"; shift 2 ;;
    --newest-only)     NEWEST_ONLY="true"; shift ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "::error::Unknown arg: $1"; usage; exit 1 ;;
  esac
done

if [ -z "${CONTEXT}" ] || [ -z "${NAMESPACE}" ] || [ -z "${SELECTOR}" ] || [ -z "${EXPECTED_DIGEST}" ]; then
  echo "::error::Missing required args"
  usage
  exit 1
fi

# Strict format: ^sha256:[a-f0-9]{64}$
if ! [[ "${EXPECTED_DIGEST}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "::error::Invalid expected-digest format (must be ^sha256:[a-f0-9]{64}$): ${EXPECTED_DIGEST}"
  exit 1
fi

if [[ -n "${EXPECTED_REPOSITORY}" || -n "${CRI_NODE_CONTAINER}" ]]; then
  if [[ -z "${EXPECTED_REPOSITORY}" || -z "${CRI_NODE_CONTAINER}" ]]; then
    echo "::error::CRI alias verification requires both --expected-repository and --cri-node-container"
    exit 1
  fi
  if ! [[ "${EXPECTED_REPOSITORY}" =~ ^[a-z0-9][a-z0-9._:/-]*[a-z0-9]$ ]]; then
    echo "::error::Invalid expected repository: ${EXPECTED_REPOSITORY}"
    exit 1
  fi
fi

verify_cri_digest_alias() {
  local pod_name="$1"
  local image_id="$2"
  local normalized_digest="$3"
  local actual_ref="${image_id#docker-pullable://}"
  local expected_ref="${EXPECTED_REPOSITORY}@${EXPECTED_DIGEST}"
  local result actual_matches expected_matches record_id

  [[ -n "${EXPECTED_REPOSITORY}" && -n "${CRI_NODE_CONTAINER}" ]] || return 1
  [[ "${actual_ref}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}$ ]] || {
    echo "::error::${pod_name} pod imageID is not a canonical repository@digest reference: ${image_id}"
    return 1
  }
  [[ "${actual_ref}" == *@"${normalized_digest}" ]] || {
    echo "::error::${pod_name} normalized digest is not bound to its imageID reference"
    return 1
  }

  if [[ -z "${CRI_IMAGES_JSON}" ]]; then
    command -v docker >/dev/null 2>&1 || {
      echo "::error::docker is unavailable; CRI alias verification cannot run"
      return 1
    }
    if ! CRI_IMAGES_JSON=$(docker exec "${CRI_NODE_CONTAINER}" crictl images -o json); then
      echo "::error::CRI image inventory is unavailable from ${CRI_NODE_CONTAINER}"
      return 1
    fi
    jq -e '.images | type == "array"' <<<"${CRI_IMAGES_JSON}" >/dev/null || {
      echo "::error::CRI image inventory is malformed"
      return 1
    }
  fi

  result=$(jq -c --arg actual "${actual_ref}" --arg expected "${expected_ref}" '
    [
      .images[]
      | select((.repoDigests // []) | type == "array")
      | select((.repoDigests // []) | index($actual) != null)
    ] as $matches
    | {
        actualMatches: ($matches | length),
        expectedMatches: (
          [$matches[] | select((.repoDigests // []) | index($expected) != null)]
          | length
        ),
        recordIds: [$matches[].id]
      }
  ' <<<"${CRI_IMAGES_JSON}") || {
    echo "::error::CRI image inventory query failed"
    return 1
  }

  actual_matches=$(jq -r '.actualMatches' <<<"${result}")
  expected_matches=$(jq -r '.expectedMatches' <<<"${result}")
  record_id=$(jq -r 'if (.recordIds | length) == 1 then .recordIds[0] else "" end' <<<"${result}")

  if [[ "${actual_matches}" != "1" || "${expected_matches}" != "1" ]]; then
    echo "::error::${pod_name} CRI digest alias is not uniquely bound to the expected artifact"
    echo "  actual-ref:       ${actual_ref}"
    echo "  expected-ref:     ${expected_ref}"
    echo "  actual-matches:   ${actual_matches}"
    echo "  expected-matches: ${expected_matches}"
    return 1
  fi
  [[ "${record_id}" =~ ^sha256:[a-f0-9]{64}$ ]] || {
    echo "::error::${pod_name} CRI image record has an invalid content ID: ${record_id}"
    return 1
  }

  echo "PASS: ${pod_name} CRI image record uniquely binds runtime alias to expected digest"
  echo "  actual-ref:   ${actual_ref}"
  echo "  expected-ref: ${expected_ref}"
  echo "  record-id:    ${record_id}"
  return 0
}

# Fetch all Running, non-terminating pods matching selector
PODS_JSON=$(kubectl --context="${CONTEXT}" get pod \
  -n "${NAMESPACE}" \
  -l "${SELECTOR}" \
  --field-selector=status.phase=Running \
  -o json)

# Filter non-terminating pods (deletionTimestamp == null), sort by creationTimestamp
LIVE_PODS=$(echo "${PODS_JSON}" | jq '
  .items
  | map(select(.metadata.deletionTimestamp == null))
  | sort_by(.metadata.creationTimestamp)')

POD_COUNT=$(echo "${LIVE_PODS}" | jq 'length')

if [ "${POD_COUNT}" -eq 0 ]; then
  echo "::error::No live (Running + non-terminating) pod found for selector '${SELECTOR}' in ns '${NAMESPACE}'"
  exit 1
fi

if [ "${NEWEST_ONLY}" = "true" ]; then
  # Legacy single-pod verification (newest only)
  NEWEST=$(echo "${LIVE_PODS}" | jq '.[-1]')
  POD_NAME=$(echo "${NEWEST}" | jq -r '.metadata.name')
  IMAGE_ID=$(echo "${NEWEST}" | jq -r '.status.containerStatuses[0].imageID // empty')
  NORMALIZED=$(echo "${IMAGE_ID}" | sed -E 's|^.*@(sha256:[a-f0-9]{64})$|\1|')

  if [ -z "${NORMALIZED}" ] || ! [[ "${NORMALIZED}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "::error::${POD_NAME} pod imageID format unexpected: ${IMAGE_ID}"
    exit 1
  fi

  if [ "${NORMALIZED}" != "${EXPECTED_DIGEST}" ]; then
    if ! verify_cri_digest_alias "${POD_NAME}" "${IMAGE_ID}" "${NORMALIZED}"; then
      echo "::error::Pod imageID digest mismatch (newest-only mode)"
      echo "  pod:      ${POD_NAME}"
      echo "  expected: ${EXPECTED_DIGEST}"
      echo "  actual:   ${NORMALIZED}"
      exit 1
    fi
    exit 0
  fi

  echo "✓ ${POD_NAME} pod imageID matches: ${NORMALIZED}"
  exit 0
fi

# Default: full-replica strict mode — every non-terminating Running pod must match
MISMATCH=0
echo "Verifying ${POD_COUNT} non-terminating pod(s) for selector '${SELECTOR}'..."
for i in $(seq 0 $((POD_COUNT - 1))); do
  POD=$(echo "${LIVE_PODS}" | jq ".[${i}]")
  POD_NAME=$(echo "${POD}" | jq -r '.metadata.name')
  IMAGE_ID=$(echo "${POD}" | jq -r '.status.containerStatuses[0].imageID // empty')
  NORMALIZED=$(echo "${IMAGE_ID}" | sed -E 's|^.*@(sha256:[a-f0-9]{64})$|\1|')

  if [ -z "${NORMALIZED}" ] || ! [[ "${NORMALIZED}" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "::error::${POD_NAME} pod imageID format unexpected: ${IMAGE_ID}"
    MISMATCH=$((MISMATCH + 1))
    continue
  fi

  if [ "${NORMALIZED}" != "${EXPECTED_DIGEST}" ]; then
    if ! verify_cri_digest_alias "${POD_NAME}" "${IMAGE_ID}" "${NORMALIZED}"; then
      echo "::error::${POD_NAME} digest mismatch — expected=${EXPECTED_DIGEST} actual=${NORMALIZED}"
      MISMATCH=$((MISMATCH + 1))
    fi
  else
    echo "✓ ${POD_NAME} → ${NORMALIZED}"
  fi
done

if [ "${MISMATCH}" -gt 0 ]; then
  echo "::error::${MISMATCH}/${POD_COUNT} pod(s) failed digest verification"
  exit 1
fi

echo "✓ All ${POD_COUNT} pod(s) verified against digest=${EXPECTED_DIGEST}"
exit 0
