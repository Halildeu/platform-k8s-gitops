#!/usr/bin/env bash
# Full ATS testai runtime binding: exact GitOps revision, Argo health, current
# ReplicaSet-owned ready pods and cache-busted frontend source identity.
set -euo pipefail

KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
ARGO_CONTEXT="${ARGO_CONTEXT:-k3d-prod}"
ARGO_NAMESPACE="${ARGO_NAMESPACE:-argocd}"
ARGO_APPLICATION="${ARGO_APPLICATION:-platform-test}"
BASE_URL="${BASE_URL:-https://testai.acik.com}"
PHASE="${PHASE:-pre}"
EXPECTED_GITOPS_SHA="${EXPECTED_GITOPS_SHA:-}"
EXPECTED_FRONTEND_SHA="${EXPECTED_FRONTEND_SHA:-}"
EXPECTED_ATS_DIGEST="${EXPECTED_ATS_DIGEST:-}"
EXPECTED_PERMISSION_DIGEST="${EXPECTED_PERMISSION_DIGEST:-}"
EXPECTED_FRONTEND_DIGEST="${EXPECTED_FRONTEND_DIGEST:-}"
EVIDENCE_DIR="${EVIDENCE_DIR:-}"
REQUIRE_HEAD_SHA="${REQUIRE_HEAD_SHA:-true}"
FRONTEND_TAG="sha-${EXPECTED_FRONTEND_SHA:0:7}"

[[ "$KUBE_CONTEXT" == "k3d-test" && "$KUBE_NAMESPACE" == "platform-test" ]] || {
  echo "FATAL: only canonical test runtime is allowed" >&2
  exit 2
}
[[ "$ARGO_CONTEXT" == "k3d-prod" && "$ARGO_NAMESPACE" == "argocd" && "$ARGO_APPLICATION" == "platform-test" ]] || {
  echo "FATAL: canonical Argo application identity mismatch" >&2
  exit 2
}
[[ "$BASE_URL" == "https://testai.acik.com" && "$PHASE" =~ ^(pre|post)$ ]] || {
  echo "FATAL: test URL or verification phase invalid" >&2
  exit 2
}
[[ "$REQUIRE_HEAD_SHA" == "true" || "$REQUIRE_HEAD_SHA" == "false" ]] || {
  echo "FATAL: REQUIRE_HEAD_SHA must be true or false" >&2
  exit 2
}
[[ "$EXPECTED_GITOPS_SHA" =~ ^[0-9a-f]{40}$ && "$EXPECTED_FRONTEND_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "FATAL: exact GitOps and frontend source SHAs are required" >&2
  exit 2
}
for digest in "$EXPECTED_ATS_DIGEST" "$EXPECTED_PERMISSION_DIGEST" "$EXPECTED_FRONTEND_DIGEST"; do
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "FATAL: exact immutable runtime digests are required" >&2
    exit 2
  }
done
for cmd in curl git jq kubectl; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "FATAL: missing command: $cmd" >&2
    exit 2
  }
done

git fetch --quiet --no-tags origin main
if [[ "$REQUIRE_HEAD_SHA" == "true" ]]; then
  [[ "$(git rev-parse HEAD)" == "$EXPECTED_GITOPS_SHA" ]] || {
    echo "FATAL: checkout is not the dispatched GitOps revision" >&2
    exit 1
  }
fi
[[ "$(git rev-parse origin/main)" == "$EXPECTED_GITOPS_SHA" ]] || {
  echo "FATAL: origin/main advanced or does not contain the dispatched revision" >&2
  exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
argo_json="$tmp/argo.json"
for _ in $(seq 1 90); do
  kubectl --context="$ARGO_CONTEXT" -n "$ARGO_NAMESPACE" \
    get application "$ARGO_APPLICATION" -o json >"$argo_json"
  if jq -e --arg revision "$EXPECTED_GITOPS_SHA" '
      .status.sync.revision == $revision and
      .status.sync.status == "Synced" and
      .status.health.status == "Healthy"
    ' "$argo_json" >/dev/null; then
    break
  fi
  sleep 2
done
jq -e --arg revision "$EXPECTED_GITOPS_SHA" '
    .status.sync.revision == $revision and
    .status.sync.status == "Synced" and
    .status.health.status == "Healthy"
  ' "$argo_json" >/dev/null || {
  echo "FATAL: Argo application did not reach exact revision + Synced + Healthy" >&2
  exit 1
}

verify_deployment() {
  local deployment="$1" container="$2" selector="$3" expected_image="$4"
  local deployment_json="$tmp/${deployment}-deployment.json"
  local replica_sets_json="$tmp/${deployment}-replicasets.json"
  local pods_json="$tmp/${deployment}-pods.json"
  local deployment_uid replicas replica_set_uid digest desired

  kubectl --context="$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" rollout status \
    "deployment/$deployment" --timeout=180s
  kubectl --context="$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get deployment \
    "$deployment" -o json >"$deployment_json"
  jq -e --arg container "$container" --arg expected "$expected_image" '
      .metadata.deletionTimestamp == null and
      .status.observedGeneration == .metadata.generation and
      .spec.replicas > 0 and
      .status.updatedReplicas == .spec.replicas and
      .status.readyReplicas == .spec.replicas and
      .status.availableReplicas == .spec.replicas and
      ([.spec.template.spec.containers[] | select(.name == $container) | .image] == [$expected])
    ' "$deployment_json" >/dev/null || {
    echo "FATAL: deployment $deployment desired/ready state mismatch" >&2
    exit 1
  }
  deployment_uid="$(jq -r '.metadata.uid' "$deployment_json")"
  replicas="$(jq -r '.spec.replicas' "$deployment_json")"
  desired="$(jq -r --arg container "$container" '.spec.template.spec.containers[] | select(.name == $container) | .image' "$deployment_json")"
  digest="${desired##*@}"

  kubectl --context="$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get replicasets \
    -l "$selector" -o json >"$replica_sets_json"
  replica_set_uid="$(jq -er --arg deployment_uid "$deployment_uid" '
      [.items[] |
        select(any(.metadata.ownerReferences[]?; .uid == $deployment_uid and .kind == "Deployment")) |
        select((.spec.replicas // 0) > 0)] as $active |
      if ($active | length) == 1 then $active[0].metadata.uid else empty end
    ' "$replica_sets_json")" || {
    echo "FATAL: deployment $deployment does not have one exact active ReplicaSet" >&2
    exit 1
  }

  kubectl --context="$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get pods \
    -l "$selector" -o json >"$pods_json"
  jq -e \
    --arg replica_set_uid "$replica_set_uid" \
    --arg container "$container" \
    --arg digest "$digest" \
    --argjson replicas "$replicas" '
      [.items[] | select(.metadata.deletionTimestamp == null)] as $live |
      ($live | length) == $replicas and
      ($live | all(
        .status.phase == "Running" and
        any(.metadata.ownerReferences[]?; .uid == $replica_set_uid and .kind == "ReplicaSet") and
        ([.status.containerStatuses[]? | select(.name == $container)] | length) == 1 and
        ([.status.containerStatuses[]? | select(.name == $container)] | all(
          .ready == true and (.imageID | endswith("@" + $digest))
        ))
      ))
    ' "$pods_json" >/dev/null || {
    echo "FATAL: deployment $deployment current ReplicaSet pod/imageID set mismatch" >&2
    exit 1
  }
}

verify_deployment \
  ats-interview-evidence app-boot app=ats-interview-evidence \
  "ghcr.io/halildeu/ats-app-boot@$EXPECTED_ATS_DIGEST"
verify_deployment \
  permission-service permission-service app.kubernetes.io/name=permission-service \
  "ghcr.io/halildeu/platform-backend-permission-service@$EXPECTED_PERMISSION_DIGEST"
verify_deployment \
  frontend frontend app.kubernetes.io/name=frontend \
  "ghcr.io/halildeu/platform-web-frontend-testai:$FRONTEND_TAG@$EXPECTED_FRONTEND_DIGEST"

build_info="$tmp/build-info.json"
nonce="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-${PHASE}-$(date +%s%N)"
curl -fsS --connect-timeout 10 --max-time 30 \
  -H 'Cache-Control: no-cache' -H 'Pragma: no-cache' \
  "$BASE_URL/build-info.json?fullats_run=$nonce" >"$build_info"
jq -e --arg sha "$EXPECTED_FRONTEND_SHA" '.sha == $sha' "$build_info" >/dev/null || {
  echo "FATAL: cache-busted frontend build-info source mismatch" >&2
  exit 1
}

if [[ -n "$EVIDENCE_DIR" ]]; then
  mkdir -p "$EVIDENCE_DIR"
  jq -n \
    --arg phase "$PHASE" \
    --arg gitopsRevision "$EXPECTED_GITOPS_SHA" \
    --arg frontendSourceCommit "$EXPECTED_FRONTEND_SHA" \
    --arg atsDigest "$EXPECTED_ATS_DIGEST" \
    --arg permissionDigest "$EXPECTED_PERMISSION_DIGEST" \
    --arg frontendDigest "$EXPECTED_FRONTEND_DIGEST" \
    '{
      schemaVersion:"fullats-live-runtime/v1",
      environment:"testai.acik.com",
      phase:$phase,
      gitopsRevision:$gitopsRevision,
      argo:{application:"platform-test",sync:"Synced",health:"Healthy"},
      frontendSourceCommit:$frontendSourceCommit,
      runtime:{atsDigest:$atsDigest,permissionDigest:$permissionDigest,frontendDigest:$frontendDigest},
      authority:"exact desired image plus current ReplicaSet-owned ready pod imageID",
      result:"PASS"
    }' >"$EVIDENCE_DIR/runtime-$PHASE.json"
fi

echo "PASS Full ATS runtime phase=$PHASE revision=$EXPECTED_GITOPS_SHA"
