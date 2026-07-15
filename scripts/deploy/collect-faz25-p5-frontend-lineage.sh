#!/usr/bin/env bash
# Faz 25 P5 — content-addressed frontend lineage collector.
#
# Read-only. It binds the canonical test cluster Deployment to its active
# ReplicaSet, Ready Pods and immutable imageID, then emits resource identifiers
# only. No Secret, token, manifest body or environment credential is printed.

set -euo pipefail

REPORT_PATH="${REPORT_PATH:?REPORT_PATH is required}"
PHASE="${PHASE:?PHASE is required (pre or post)}"
EXPECTED_CONTEXT="${EXPECTED_CONTEXT:-k3d-test}"
NAMESPACE="${NAMESPACE:-platform-test}"
DEPLOYMENT="${DEPLOYMENT:-frontend}"
CONTAINER="${CONTAINER:-frontend}"
EXPECTED_SOURCE_SHA="${EXPECTED_SOURCE_SHA:?EXPECTED_SOURCE_SHA is required}"
EXPECTED_IMAGE_DIGEST="${EXPECTED_IMAGE_DIGEST:?EXPECTED_IMAGE_DIGEST is required}"
EXPECTED_BUILD_RUN_ID="${EXPECTED_BUILD_RUN_ID:?EXPECTED_BUILD_RUN_ID is required}"
EXPECTED_CLUSTER_SERVER_SHA256="${EXPECTED_CLUSTER_SERVER_SHA256:?EXPECTED_CLUSTER_SERVER_SHA256 is required}"
EXPECTED_CLUSTER_CA_SHA256="${EXPECTED_CLUSTER_CA_SHA256:?EXPECTED_CLUSTER_CA_SHA256 is required}"
EXPECTED_KUBE_SYSTEM_UID="${EXPECTED_KUBE_SYSTEM_UID:?EXPECTED_KUBE_SYSTEM_UID is required}"
BUILD_PROVENANCE_RECEIPT_PATH="${BUILD_PROVENANCE_RECEIPT_PATH:-tests/smoke/faz25-p5-build-provenance-receipt.json}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
CURL_BIN="${CURL_BIN:-curl}"

fail_closed() {
  echo "Frontend lineage collection failed closed" >&2
  exit 1
}

[[ "$PHASE" == "pre" || "$PHASE" == "post" ]] || fail_closed
[[ "$EXPECTED_CONTEXT" == "k3d-test" ]] || fail_closed
[[ "$EXPECTED_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail_closed
[[ "$EXPECTED_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_BUILD_RUN_ID" =~ ^[0-9]+$ ]] || fail_closed
[[ "$EXPECTED_CLUSTER_SERVER_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_CLUSTER_CA_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_KUBE_SYSTEM_UID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail_closed

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

kubectl_test() {
  "$KUBECTL_BIN" --context "$EXPECTED_CONTEXT" "$@"
}

mkdir -p "$(dirname "$REPORT_PATH")"
umask 077
rm -f "$REPORT_PATH"

context="$EXPECTED_CONTEXT"
cluster_server="$(kubectl_test config view --minify \
  -o jsonpath='{.clusters[0].cluster.server}')"
[[ -n "$cluster_server" ]] || fail_closed
cluster_server_sha256="$(sha256_text "$cluster_server")"
[[ "$cluster_server_sha256" == "$EXPECTED_CLUSTER_SERVER_SHA256" ]] || fail_closed
unset cluster_server
cluster_ca_data="$(kubectl_test config view --raw --minify \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
[[ -n "$cluster_ca_data" ]] || fail_closed
cluster_ca_sha256="$(python3 -c '
import base64
import hashlib
import sys

raw = base64.b64decode(sys.stdin.buffer.read().strip(), validate=True)
print(hashlib.sha256(raw).hexdigest())
' <<<"$cluster_ca_data")"
unset cluster_ca_data
[[ "$cluster_ca_sha256" == "$EXPECTED_CLUSTER_CA_SHA256" ]] || fail_closed
kube_system_uid="$(kubectl_test get namespace kube-system \
  -o jsonpath='{.metadata.uid}')"
[[ "$kube_system_uid" == "$EXPECTED_KUBE_SYSTEM_UID" ]] || fail_closed

build_run_url="https://github.com/Halildeu/platform-web/actions/runs/${EXPECTED_BUILD_RUN_ID}"
build_run_json="$($CURL_BIN -fsS --max-time 20 \
  "https://api.github.com/repos/Halildeu/platform-web/actions/runs/${EXPECTED_BUILD_RUN_ID}")"
jq -e \
  --arg source "$EXPECTED_SOURCE_SHA" \
  --argjson run_id "$EXPECTED_BUILD_RUN_ID" '
    .id == $run_id and
    .status == "completed" and
    .conclusion == "success" and
    .event == "push" and
    .head_branch == "main" and
    .head_sha == $source and
    .path == ".github/workflows/ci-web-image-push.yml"
  ' <<<"$build_run_json" >/dev/null || fail_closed
unset build_run_json

[[ -f "$BUILD_PROVENANCE_RECEIPT_PATH" ]] || fail_closed
build_provenance_receipt_sha256="$(sha256_file "$BUILD_PROVENANCE_RECEIPT_PATH")"
jq -e \
  --arg source "$EXPECTED_SOURCE_SHA" \
  --arg digest "$EXPECTED_IMAGE_DIGEST" \
  --arg run_id "$EXPECTED_BUILD_RUN_ID" '
    keys == [
      "artifact", "buildRunId", "imageDigest", "inspectedAt", "inspection",
      "oci", "schemaVersion", "sourceSha"
    ] and
    .schemaVersion == "faz25-p5-build-provenance-receipt-v1" and
    .sourceSha == $source and
    .imageDigest == $digest and
    .buildRunId == $run_id and
    (.artifact | keys) == ["digest", "id", "name", "sizeInBytes"] and
    .artifact.id == "8357836615" and
    .artifact.name == "Halildeu~platform-web~XWOTK5.dockerbuild" and
    .artifact.digest == "sha256:4d571d1bc48c63902a11958da33205539085f59549a810f8c827b2d9a6192a56" and
    .artifact.sizeInBytes == 108583 and
    (.oci | keys) == [
      "historyRecordDigest", "layoutManifestDigest", "slsaProvenanceDigest",
      "subjectDigest", "vcsRevision"
    ] and
    .oci.layoutManifestDigest == "sha256:ad40b72e1b01084c82fb2584c1fba1e845cfb1fd2b55c5f387788a9999ac109a" and
    .oci.historyRecordDigest == "sha256:78cd630b2f7de905cd1068429044a85c564227e8ea0934dfc0f4516d92d17f22" and
    .oci.slsaProvenanceDigest == "sha256:6fd32c43a78f33b60225b638efd1929e86f40e38f5c58707c818ff19f1fb46d2" and
    .oci.subjectDigest == $digest and
    .oci.vcsRevision == $source and
    (.inspection | keys) == [
      "artifactDigestMatchedGitHub", "ociDigestGraphVerified",
      "rawArtifactExcludedFromRepo", "rawArtifactExclusionReason",
      "slsaSubjectAndRevisionVerified"
    ] and
    .inspection.artifactDigestMatchedGitHub == true and
    .inspection.ociDigestGraphVerified == true and
    .inspection.slsaSubjectAndRevisionVerified == true and
    .inspection.rawArtifactExcludedFromRepo == true
  ' "$BUILD_PROVENANCE_RECEIPT_PATH" >/dev/null || fail_closed
build_artifact_id="$(jq -r '.artifact.id' "$BUILD_PROVENANCE_RECEIPT_PATH")"
build_artifact_name="$(jq -r '.artifact.name' "$BUILD_PROVENANCE_RECEIPT_PATH")"
build_artifact_digest="$(jq -r '.artifact.digest' "$BUILD_PROVENANCE_RECEIPT_PATH")"
build_artifact_size="$(jq -r '.artifact.sizeInBytes' "$BUILD_PROVENANCE_RECEIPT_PATH")"
slsa_provenance_digest="$(jq -r '.oci.slsaProvenanceDigest' "$BUILD_PROVENANCE_RECEIPT_PATH")"

build_artifacts_json="$($CURL_BIN -fsS --max-time 20 \
  "https://api.github.com/repos/Halildeu/platform-web/actions/runs/${EXPECTED_BUILD_RUN_ID}/artifacts?per_page=100")"
jq -e \
  --argjson artifact_id "$build_artifact_id" \
  --arg artifact_name "$build_artifact_name" \
  --arg artifact_digest "$build_artifact_digest" \
  --argjson artifact_size "$build_artifact_size" '
    [.artifacts[]
      | select(
          .id == $artifact_id and
          .name == $artifact_name and
          .digest == $artifact_digest and
          .size_in_bytes == $artifact_size and
          .expired == false
        )]
    | length == 1
  ' <<<"$build_artifacts_json" >/dev/null || fail_closed
unset build_artifacts_json

deployment_json="$(kubectl_test -n "$NAMESPACE" \
  get deployment "$DEPLOYMENT" -o json)"
deployment_uid="$(jq -r '.metadata.uid' <<<"$deployment_json")"
deployment_resource_version="$(jq -r '.metadata.resourceVersion' <<<"$deployment_json")"
deployment_generation="$(jq -r '.metadata.generation' <<<"$deployment_json")"
observed_generation="$(jq -r '.status.observedGeneration // 0' <<<"$deployment_json")"
rollout_revision="$(jq -r '.metadata.annotations["deployment.kubernetes.io/revision"] // ""' <<<"$deployment_json")"
desired_replicas="$(jq -r '.spec.replicas // 1' <<<"$deployment_json")"
available_replicas="$(jq -r '.status.availableReplicas // 0' <<<"$deployment_json")"
selector="$({
  jq -r '
    .spec.selector.matchLabels
    | to_entries
    | sort_by(.key)
    | map(.key + "=" + (.value | tostring))
    | join(",")
  ' <<<"$deployment_json"
})"
deployment_image="$(jq -r \
  --arg container "$CONTAINER" '
    [.spec.template.spec.containers[] | select(.name == $container) | .image]
    | if length == 1 then .[0] else "" end
  ' <<<"$deployment_json")"

[[ -n "$deployment_uid" && -n "$rollout_revision" && -n "$selector" ]] || fail_closed
[[ "$deployment_generation" == "$observed_generation" ]] || fail_closed
[[ "$available_replicas" == "$desired_replicas" ]] || fail_closed
[[ "$deployment_image" == *"@${EXPECTED_IMAGE_DIGEST}" ]] || fail_closed

replicasets_json="$(kubectl_test -n "$NAMESPACE" \
  get replicasets -l "$selector" -o json)"
active_replicaset_json="$(jq -c \
  --arg deployment_uid "$deployment_uid" \
  --arg container "$CONTAINER" \
  --arg digest "$EXPECTED_IMAGE_DIGEST" \
  --argjson desired "$desired_replicas" '
    [.items[]
      | select(
          ([.metadata.ownerReferences[]?
            | select(.kind == "Deployment" and .uid == $deployment_uid)] | length) == 1
        )
      | select((.spec.replicas // 0) == $desired)
      | select((.status.readyReplicas // 0) == $desired)
      | select(
          ([.spec.template.spec.containers[]
            | select(.name == $container)
            | .image
            | endswith("@" + $digest)] == [true])
        )]
    | if length == 1 then .[0] else empty end
  ' <<<"$replicasets_json")"
[[ -n "$active_replicaset_json" ]] || fail_closed
replicaset_name="$(jq -r '.metadata.name' <<<"$active_replicaset_json")"
replicaset_uid="$(jq -r '.metadata.uid' <<<"$active_replicaset_json")"
replicaset_revision="$(jq -r '.metadata.annotations["deployment.kubernetes.io/revision"] // ""' \
  <<<"$active_replicaset_json")"
[[ "$replicaset_revision" == "$rollout_revision" ]] || fail_closed

pods_json="$(kubectl_test -n "$NAMESPACE" \
  get pods -l "$selector" -o json)"
stable_pods_json="$(jq -c \
  --arg replicaset_uid "$replicaset_uid" \
  --arg container "$CONTAINER" \
  --arg digest "$EXPECTED_IMAGE_DIGEST" \
  --argjson desired "$desired_replicas" '
    [.items[]
      | select(.metadata.deletionTimestamp == null)
      | select(.status.phase == "Running")
      | select(
          ([.metadata.ownerReferences[]?
            | select(.kind == "ReplicaSet" and .uid == $replicaset_uid)] | length) == 1
        )
      | select(
          ([.status.conditions[]?
            | select(.type == "Ready" and .status == "True")] | length) == 1
        )
      | select(
          ([.status.containerStatuses[]?
            | select(
                .name == $container and
                .ready == true and
                (.imageID | endswith("@" + $digest))
              )] | length) == 1
        )]
    | if length == $desired then . else empty end
  ' <<<"$pods_json")"
[[ -n "$stable_pods_json" ]] || fail_closed

non_deleting_pod_count="$(jq '[.items[] | select(.metadata.deletionTimestamp == null)] | length' \
  <<<"$pods_json")"
[[ "$non_deleting_pod_count" == "$desired_replicas" ]] || fail_closed

pod_uids="$(jq -c '[.[].metadata.uid] | sort' <<<"$stable_pods_json")"
image_ids="$(jq -c \
  --arg container "$CONTAINER" '
    [.[].status.containerStatuses[] | select(.name == $container) | .imageID] | sort
  ' <<<"$stable_pods_json")"
observed_digests="$(jq -c '
    map(capture("(?<digest>sha256:[0-9a-f]{64})$").digest) | unique
  ' <<<"$image_ids")"
[[ "$observed_digests" == "[\"$EXPECTED_IMAGE_DIGEST\"]" ]] || fail_closed
observed_digest="$(jq -r '.[0]' <<<"$observed_digests")"

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report_tmp="${REPORT_PATH}.tmp"
rm -f "$report_tmp"
jq -n \
  --arg phase "$PHASE" \
  --arg observed_at "$observed_at" \
  --arg context "$context" \
  --arg cluster_server_sha256 "$cluster_server_sha256" \
  --arg cluster_ca_sha256 "$cluster_ca_sha256" \
  --arg kube_system_uid "$kube_system_uid" \
  --arg namespace "$NAMESPACE" \
  --arg deployment "$DEPLOYMENT" \
  --arg deployment_uid "$deployment_uid" \
  --arg deployment_resource_version "$deployment_resource_version" \
  --argjson deployment_generation "$deployment_generation" \
  --argjson observed_generation "$observed_generation" \
  --arg rollout_revision "$rollout_revision" \
  --argjson desired_replicas "$desired_replicas" \
  --arg deployment_image "$deployment_image" \
  --arg replicaset_name "$replicaset_name" \
  --arg replicaset_uid "$replicaset_uid" \
  --arg replicaset_revision "$replicaset_revision" \
  --argjson pod_uids "$pod_uids" \
  --argjson image_ids "$image_ids" \
  --arg source_sha "$EXPECTED_SOURCE_SHA" \
  --arg expected_digest "$EXPECTED_IMAGE_DIGEST" \
  --arg observed_digest "$observed_digest" \
  --arg build_run_id "$EXPECTED_BUILD_RUN_ID" \
  --arg build_run_url "$build_run_url" \
  --arg build_artifact_id "$build_artifact_id" \
  --arg build_artifact_name "$build_artifact_name" \
  --arg build_artifact_digest "$build_artifact_digest" \
  --argjson build_artifact_size "$build_artifact_size" \
  --arg build_provenance_receipt_sha256 "$build_provenance_receipt_sha256" \
  --arg slsa_provenance_digest "$slsa_provenance_digest" '
  {
    schemaVersion: "faz25-p5-frontend-lineage-v1",
    phase: $phase,
    observedAt: $observed_at,
    cluster: {
      context: $context,
      serverSha256: $cluster_server_sha256,
      caSha256: $cluster_ca_sha256,
      kubeSystemNamespaceUid: $kube_system_uid
    },
    deployment: {
      namespace: $namespace,
      name: $deployment,
      uid: $deployment_uid,
      resourceVersion: $deployment_resource_version,
      generation: $deployment_generation,
      observedGeneration: $observed_generation,
      rolloutRevision: $rollout_revision,
      desiredReplicas: $desired_replicas,
      image: $deployment_image
    },
    replicaSet: {
      name: $replicaset_name,
      uid: $replicaset_uid,
      rolloutRevision: $replicaset_revision
    },
    pods: {
      readyCount: ($pod_uids | length),
      uids: $pod_uids,
      imageIds: $image_ids
    },
    lineage: {
      sourceSha: $source_sha,
      expectedDigest: $expected_digest,
      observedDigest: $observed_digest,
      buildRunId: $build_run_id,
      buildRunUrl: $build_run_url,
      buildArtifactId: $build_artifact_id,
      buildArtifactName: $build_artifact_name,
      buildArtifactDigest: $build_artifact_digest,
      buildArtifactSizeInBytes: $build_artifact_size,
      buildProvenanceReceiptSha256: $build_provenance_receipt_sha256,
      slsaProvenanceDigest: $slsa_provenance_digest
    }
  }
  ' >"$report_tmp" || {
    rm -f "$report_tmp"
    fail_closed
  }
chmod 0600 "$report_tmp"
mv "$report_tmp" "$REPORT_PATH"
