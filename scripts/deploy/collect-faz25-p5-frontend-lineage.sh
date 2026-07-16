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
EXPECTED_BUILD_ARTIFACT_ID="${EXPECTED_BUILD_ARTIFACT_ID:-8364186187}"
EXPECTED_BUILD_ARTIFACT_NAME="${EXPECTED_BUILD_ARTIFACT_NAME:-Halildeu~platform-web~TJ1D9C.dockerbuild}"
EXPECTED_BUILD_ARTIFACT_DIGEST="${EXPECTED_BUILD_ARTIFACT_DIGEST:-sha256:45721d20a3809bf1443f79d291cca99687b40a28dd94c5a8f804fa92aa81aebb}"
EXPECTED_BUILD_ARTIFACT_SIZE="${EXPECTED_BUILD_ARTIFACT_SIZE:-109981}"
EXPECTED_CLUSTER_SERVER_SHA256="${EXPECTED_CLUSTER_SERVER_SHA256:?EXPECTED_CLUSTER_SERVER_SHA256 is required}"
EXPECTED_CLUSTER_CA_SHA256="${EXPECTED_CLUSTER_CA_SHA256:?EXPECTED_CLUSTER_CA_SHA256 is required}"
EXPECTED_KUBE_SYSTEM_UID="${EXPECTED_KUBE_SYSTEM_UID:?EXPECTED_KUBE_SYSTEM_UID is required}"
EXPECTED_BROWSER_PROBE_ID="${EXPECTED_BROWSER_PROBE_ID:-}"
EXPECTED_BROWSER_REPORT_PATH="${EXPECTED_BROWSER_REPORT_PATH:-}"
WORKFLOW_STARTED_AT="${WORKFLOW_STARTED_AT:-}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
CURL_BIN="${CURL_BIN:-curl}"
ROUTE_VALIDATOR="${ROUTE_VALIDATOR:-scripts/deploy/verify-faz25-p5-frontend-routes.py}"

fail_closed() {
  echo "Frontend lineage collection failed closed" >&2
  exit 1
}

[[ "$PHASE" == "pre" || "$PHASE" == "post" ]] || fail_closed
[[ "$EXPECTED_CONTEXT" == "k3d-test" ]] || fail_closed
[[ "$EXPECTED_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail_closed
[[ "$EXPECTED_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_BUILD_RUN_ID" =~ ^[0-9]+$ ]] || fail_closed
[[ "$EXPECTED_BUILD_ARTIFACT_ID" =~ ^[0-9]+$ ]] || fail_closed
[[ "$EXPECTED_BUILD_ARTIFACT_NAME" == "Halildeu~platform-web~TJ1D9C.dockerbuild" ]] || fail_closed
[[ "$EXPECTED_BUILD_ARTIFACT_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_BUILD_ARTIFACT_SIZE" =~ ^[0-9]+$ ]] || fail_closed
[[ "$EXPECTED_CLUSTER_SERVER_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_CLUSTER_CA_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail_closed
[[ "$EXPECTED_KUBE_SYSTEM_UID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail_closed
if [[ "$PHASE" == "pre" ]]; then
  [[ -z "$EXPECTED_BROWSER_PROBE_ID" && -z "$EXPECTED_BROWSER_REPORT_PATH" && \
     -z "$WORKFLOW_STARTED_AT" ]] || fail_closed
else
  [[ "$EXPECTED_BROWSER_PROBE_ID" =~ ^[0-9a-f]{32}$ ]] || fail_closed
  [[ -f "$EXPECTED_BROWSER_REPORT_PATH" && ! -L "$EXPECTED_BROWSER_REPORT_PATH" ]] || fail_closed
  [[ "$WORKFLOW_STARTED_AT" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || fail_closed
fi

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

build_artifacts_json="$($CURL_BIN -fsS --max-time 20 \
  "https://api.github.com/repos/Halildeu/platform-web/actions/runs/${EXPECTED_BUILD_RUN_ID}/artifacts?per_page=100")"
jq -e \
  --argjson artifact_id "$EXPECTED_BUILD_ARTIFACT_ID" \
  --arg artifact_name "$EXPECTED_BUILD_ARTIFACT_NAME" \
  --arg artifact_digest "$EXPECTED_BUILD_ARTIFACT_DIGEST" \
  --argjson artifact_size "$EXPECTED_BUILD_ARTIFACT_SIZE" '
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
build_artifact_id="$EXPECTED_BUILD_ARTIFACT_ID"
build_artifact_name="$EXPECTED_BUILD_ARTIFACT_NAME"
build_artifact_digest="$EXPECTED_BUILD_ARTIFACT_DIGEST"
build_artifact_size="$EXPECTED_BUILD_ARTIFACT_SIZE"
unset build_artifacts_json

# Cross-repository artifact content requires a separately governed read token;
# the current protected Environment intentionally has none. Keep the public
# run/artifact metadata non-terminal. Terminal source-to-image proof below is
# the same-session HTTPS host -> Ingress -> Service -> EndpointSlice -> Ready
# Pod UID -> imageID chain, combined with the browser's exact build-info SHA.
build_artifact_evidence_class="METADATA_ONLY_NON_TERMINAL"

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

pod_build_infos_json="$({
  while IFS=$'\t' read -r pod_name pod_uid; do
    [[ -n "$pod_name" && -n "$pod_uid" ]] || fail_closed
    pod_build_info="$(kubectl_test get --raw \
      "/api/v1/namespaces/${NAMESPACE}/pods/${pod_name}:80/proxy/build-info.json")"
    jq -e --arg source "$EXPECTED_SOURCE_SHA" '
      (keys | sort) == [
        "assets", "buildTime", "image", "imageDigest", "origin", "ref",
        "remotes", "rootEntry", "rootEntrypoints", "schemaVersion", "sha",
        "shortSha"
      ] and
      .schemaVersion == "acik.platform.web-build-info/v2" and
      .sha == $source and
      .ref == "main" and
      .origin == "https://testai.acik.com" and
      .imageDigest == "" and
      (.assets | type == "array") and
      all(.assets[]; type == "string" and test("^[A-Za-z0-9._-]+\\.(js|css|map|json)$")) and
      .assets == (.assets | sort) and
      ([.assets[]] | unique | length) == (.assets | length) and
      (.rootEntrypoints | type == "array" and length >= 1) and
      all(.rootEntrypoints[];
        (keys | sort) == ["bodySha256", "path"] and
        (.path | test("^/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\\.(js|mjs)$")) and
        (.path | contains("//") | not) and
        (.path | split("/") | all(.[]; . != "." and . != "..")) and
        (.bodySha256 | test("^[0-9a-f]{64}$"))
      ) and
      ([.rootEntrypoints[].path] | unique | length) == (.rootEntrypoints | length) and
      .rootEntry == (.rootEntrypoints[0].path | split("/") | last)
    ' <<<"$pod_build_info" >/dev/null || fail_closed
    canonical_build_info="$(jq -cS . <<<"$pod_build_info")"
    printf '%s\n' "$canonical_build_info"
    unset pod_build_info canonical_build_info
  done < <(jq -r '.[] | [.metadata.name, .metadata.uid] | @tsv' <<<"$stable_pods_json")
} | jq -sc 'unique')"
[[ "$(jq 'length' <<<"$pod_build_infos_json")" == "1" ]] || fail_closed
canonical_build_info="$(jq -cS '.[0]' <<<"$pod_build_infos_json")"
root_entrypoints_json="$(jq -cS '.rootEntrypoints' <<<"$canonical_build_info")"
manifest_asset_paths_json="$(jq -cS '
  ([.assets[] | "/assets/" + .] + [.rootEntrypoints[].path]) | unique | sort
' <<<"$canonical_build_info")"
pod_build_info_hash="$(sha256_text "$canonical_build_info")"
pod_build_info_hashes_json="$(jq -cn --arg hash "$pod_build_info_hash" '[$hash]')"

browser_asset_binding='{"status":"PRE_BROWSER"}'
if [[ "$PHASE" == "post" ]]; then
  browser_paths_json="$(jq -cS '.runtime.frontendAssetPaths | sort' \
    "$EXPECTED_BROWSER_REPORT_PATH")"
  browser_assets_json="$(jq -cS '.runtime.frontendAssetResponses' \
    "$EXPECTED_BROWSER_REPORT_PATH")"
  browser_response_paths_json="$(jq -cS \
    '[.runtime.frontendAssetResponses[].path] | sort' \
    "$EXPECTED_BROWSER_REPORT_PATH")"
  [[ "$browser_paths_json" == "$browser_response_paths_json" ]] || fail_closed
  jq -e \
    --argjson manifest_paths "$manifest_asset_paths_json" \
    --argjson root_entrypoints "$root_entrypoints_json" '
    . as $browser_assets |
    type == "array" and length >= 1 and
    all($browser_assets[];
      . as $asset |
      (keys | sort) == [
        "bodySha256", "contentType", "fromServiceWorker", "path",
        "resourceType", "status"
      ] and
      (.path | test("^/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\\.(js|mjs|css)$")) and
      (.path | contains("//") | not) and
      (.path | split("/") | all(.[]; . != "." and . != "..")) and
      ($manifest_paths | index($asset.path)) != null and
      (.resourceType == "script" or .resourceType == "stylesheet") and
      .status == 200 and
      (.bodySha256 | test("^[0-9a-f]{64}$")) and
      .fromServiceWorker == false
    ) and
    ([$browser_assets[].path] | unique | length) == ($browser_assets | length) and
    all($root_entrypoints[];
      . as $root |
      any($browser_assets[];
        .path == $root.path and
        .resourceType == "script" and
        .bodySha256 == $root.bodySha256
      )
    )
  ' <<<"$browser_assets_json" >/dev/null || fail_closed
  browser_asset_evidence_sha256="$(sha256_text "$browser_assets_json")"
  browser_asset_count="$(jq 'length' <<<"$browser_assets_json")"
  pod_asset_bindings="$({
    while IFS=$'\t' read -r pod_name pod_uid; do
      [[ -n "$pod_name" && -n "$pod_uid" ]] || fail_closed
      while IFS=$'\t' read -r asset_path expected_asset_sha256; do
        [[ "$asset_path" =~ ^/([A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.(js|mjs|css)$ ]] || fail_closed
        [[ "$asset_path" != *//* ]] || fail_closed
        jq -e --arg path "$asset_path" 'index($path) != null' \
          <<<"$manifest_asset_paths_json" >/dev/null || fail_closed
        [[ "$expected_asset_sha256" =~ ^[0-9a-f]{64}$ ]] || fail_closed
        asset_body="$(mktemp "$(dirname "$REPORT_PATH")/.frontend-asset-XXXXXX")"
        if ! kubectl_test get --raw \
          "/api/v1/namespaces/${NAMESPACE}/pods/${pod_name}:80/proxy${asset_path}" \
          >"$asset_body"; then
          rm -f -- "$asset_body"
          fail_closed
        fi
        if ! observed_asset_sha256="$(sha256_file "$asset_body")"; then
          rm -f -- "$asset_body"
          fail_closed
        fi
        rm -f -- "$asset_body"
        [[ "$observed_asset_sha256" == "$expected_asset_sha256" ]] || fail_closed
        jq -cn \
          --arg pod_uid "$pod_uid" \
          --arg path "$asset_path" \
          --arg body_sha256 "$observed_asset_sha256" \
          '{podUid: $pod_uid, path: $path, bodySha256: $body_sha256}'
      done < <(jq -r '.[] | [.path, .bodySha256] | @tsv' <<<"$browser_assets_json")
    done < <(jq -r '.[] | [.metadata.name, .metadata.uid] | @tsv' <<<"$stable_pods_json")
  } | jq -sc 'sort_by(.podUid, .path)')"
  expected_pod_asset_binding_count=$((desired_replicas * browser_asset_count))
  [[ "$(jq 'length' <<<"$pod_asset_bindings")" == \
     "$expected_pod_asset_binding_count" ]] || fail_closed
  browser_asset_binding="$(jq -cn \
    --arg browser_asset_evidence_sha256 "$browser_asset_evidence_sha256" \
    --argjson asset_count "$browser_asset_count" \
    --argjson pod_count "$desired_replicas" \
    --argjson pod_asset_bindings "$pod_asset_bindings" '
      {
        status: "BOUND",
        browserAssetEvidenceSha256: $browser_asset_evidence_sha256,
        assetCount: $asset_count,
        podCount: $pod_count,
        podAssetBindings: $pod_asset_bindings
      }
    ')"
  unset browser_paths_json browser_response_paths_json browser_assets_json pod_asset_bindings
fi

ingress_json="$(kubectl_test -n "$NAMESPACE" get ingress platform -o json)"
ingress_uid="$(jq -r '.metadata.uid // ""' <<<"$ingress_json")"
jq -e '
  .metadata.name == "platform" and
  .metadata.namespace == "platform-test" and
  .spec.ingressClassName == "nginx" and
  ([.spec.tls[]?.hosts[]? | select(. == "testai.acik.com")] | length == 1) and
  ([.spec.rules[]?
    | select(.host == "testai.acik.com")
    | .http.paths[]?
    | select(
        .path == "/" and
        .pathType == "Prefix" and
        .backend.service.name == "frontend" and
        .backend.service.port.number == 80
      )]
    | length == 1)
' <<<"$ingress_json" >/dev/null || fail_closed
[[ "$ingress_uid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail_closed

all_ingresses_json="$(kubectl_test get ingress -A -o json)"
[[ -f "$ROUTE_VALIDATOR" ]] || fail_closed
matching_ingress_routes="$(python3 "$ROUTE_VALIDATOR" \
  --host testai.acik.com \
  --ingress-namespace "$NAMESPACE" \
  --ingress-name platform \
  --ingress-uid "$ingress_uid" \
  --service-name frontend \
  --service-port 80 \
  <<<"$all_ingresses_json")"
[[ -n "$matching_ingress_routes" ]] || fail_closed

service_json="$(kubectl_test -n "$NAMESPACE" get service frontend -o json)"
service_uid="$(jq -r '.metadata.uid // ""' <<<"$service_json")"
service_cluster_ip="$(jq -r '.spec.clusterIP // ""' <<<"$service_json")"
jq -e --argjson selector "$(jq -c '.spec.selector.matchLabels' <<<"$deployment_json")" '
  .metadata.name == "frontend" and
  .metadata.namespace == "platform-test" and
  .spec.type == "ClusterIP" and
  .spec.selector == $selector and
  ([.spec.ports[]?
    | select(
        .name == "http" and
        .protocol == "TCP" and
        .port == 80 and
        .targetPort == "http"
      )]
    | length == 1)
' <<<"$service_json" >/dev/null || fail_closed
[[ "$service_uid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail_closed
[[ -n "$service_cluster_ip" && "$service_cluster_ip" != "None" ]] || fail_closed

endpoint_slices_json="$(kubectl_test -n "$NAMESPACE" get endpointslices \
  -l kubernetes.io/service-name=frontend -o json)"
jq -e \
  --arg service_uid "$service_uid" \
  --argjson desired "$desired_replicas" \
  --argjson pod_uids "$pod_uids" '
    (.items | length) as $slice_count |
    $slice_count >= 1 and
    ([.items[]
      | select(
          .metadata.labels["kubernetes.io/service-name"] == "frontend" and
          ([.metadata.ownerReferences[]?
            | select(
                .kind == "Service" and
                .name == "frontend" and
                .uid == $service_uid
              )]
            | length == 1) and
          ([.ports[]?
            | select(.name == "http" and .protocol == "TCP" and .port == 80)]
            | length == 1)
        )]
      | length == $slice_count) and
    ([.items[].endpoints[]?] | length == $desired) and
    ([.items[].endpoints[]?
      | select(
          .conditions.ready == true and
          (.conditions.terminating // false) == false and
          (.addresses | length) >= 1 and
          .targetRef.kind == "Pod" and
          .targetRef.namespace == "platform-test"
        )
      | .targetRef.uid]
      | sort) == $pod_uids
  ' <<<"$endpoint_slices_json" >/dev/null || fail_closed
endpoint_slice_names="$(jq -c '[.items[].metadata.name] | sort' <<<"$endpoint_slices_json")"
endpoint_slice_uids="$(jq -c '[.items[].metadata.uid] | sort' <<<"$endpoint_slices_json")"
endpoint_pod_uids="$(jq -c '[.items[].endpoints[].targetRef.uid] | sort' \
  <<<"$endpoint_slices_json")"
pod_network_bindings="$(jq -c '
  map({
    podUid: .metadata.uid,
    addresses: ([.status.podIPs[]?.ip, .status.podIP]
      | map(select(. != null and . != ""))
      | unique
      | sort)
  })
  | sort_by(.podUid)
' <<<"$stable_pods_json")"
endpoint_network_bindings="$(jq -c '
  [.items[].endpoints[]
    | {podUid: .targetRef.uid, addresses: .addresses}]
  | sort_by(.podUid)
  | group_by(.podUid)
  | map({
      podUid: .[0].podUid,
      addresses: ([.[].addresses[]] | unique | sort)
    })
' <<<"$endpoint_slices_json")"
[[ "$pod_network_bindings" == "$endpoint_network_bindings" ]] || fail_closed
[[ "$(jq '[.[].addresses | length > 0] | all' <<<"$pod_network_bindings")" == "true" ]] || fail_closed
python3 -c '
import ipaddress
import json
import sys

for encoded_bindings in sys.argv[1:]:
    bindings = json.loads(encoded_bindings)
    for binding in bindings:
        for address in binding["addresses"]:
            ipaddress.ip_address(address)
' "$pod_network_bindings" "$endpoint_network_bindings" || fail_closed

if [[ "$PHASE" == "pre" ]]; then
  browser_request_binding='{"status":"PRE_BROWSER"}'
else
  controller_pods_json="$(kubectl_test get pods -A \
    -l 'app.kubernetes.io/name=ingress-nginx,app.kubernetes.io/component=controller' \
    -o json)"
  jq -e '
    (.items | length) as $controller_count |
    $controller_count >= 1 and
    ([.items[]
      | select(
          .metadata.deletionTimestamp == null and
          .status.phase == "Running" and
          ([.status.conditions[]?
            | select(.type == "Ready" and .status == "True")]
            | length == 1) and
          ([.status.containerStatuses[]?
            | select(.name == "controller" and .ready == true)]
            | length == 1)
        )]
      | length == $controller_count)
  ' <<<"$controller_pods_json" >/dev/null || fail_closed

  browser_ingress_matches="$({
    while IFS=$'\t' read -r controller_namespace controller_name controller_uid; do
      [[ -n "$controller_namespace" && -n "$controller_name" && -n "$controller_uid" ]] || fail_closed
      controller_logs="$(kubectl_test -n "$controller_namespace" logs "$controller_name" \
        -c controller --since-time="$WORKFLOW_STARTED_AT")"
      python3 -c '
import hashlib
import ipaddress
import json
import re
import sys

probe, namespace, name, uid, addresses_json = sys.argv[1:]
addresses = json.loads(addresses_json)
needle = f"GET /build-info.json?p5_probe={probe} "
upstream = " [platform-test-frontend-80] "
for raw_line in sys.stdin:
    line = raw_line.rstrip("\n")
    if needle not in line or upstream not in line:
        continue
    request_pattern = rf"\"GET /build-info\.json\?p5_probe={re.escape(probe)} HTTP/[0-9.]+\"\s+200\s"
    if re.search(request_pattern, line) is None:
        continue
    upstream_segment = line.split(upstream, 1)[1]
    ipv4_upstreams = re.findall(
        r"(?<![0-9])((?:[0-9]{1,3}\.){3}[0-9]{1,3}):80(?![0-9])",
        upstream_segment,
    )
    ipv6_upstreams = re.findall(r"\[([0-9A-Fa-f:]+)\]:80(?![0-9])", upstream_segment)
    observed_upstreams = ipv4_upstreams + ipv6_upstreams
    if len(observed_upstreams) != 1:
        continue
    observed_upstream = observed_upstreams[0]
    ipaddress.ip_address(observed_upstream)
    if observed_upstream not in addresses:
        continue
    if re.search(r"\s200\s+\S+\s*$", upstream_segment) is None:
        continue
    print(json.dumps({
        "controllerNamespace": namespace,
        "controllerPodName": name,
        "controllerPodUid": uid,
        "upstreamPodAddress": observed_upstream,
        "logLineSha256": hashlib.sha256(line.encode()).hexdigest(),
    }, sort_keys=True, separators=(",", ":")))
' "$EXPECTED_BROWSER_PROBE_ID" "$controller_namespace" "$controller_name" \
        "$controller_uid" "$(jq -c '[.[].addresses[]] | unique | sort' \
          <<<"$endpoint_network_bindings")" <<<"$controller_logs"
      unset controller_logs
    done < <(jq -r '.items[] | [.metadata.namespace, .metadata.name, .metadata.uid] | @tsv' \
      <<<"$controller_pods_json")
  } | jq -sc 'unique_by(.logLineSha256)')"
  [[ "$(jq 'length' <<<"$browser_ingress_matches")" == "1" ]] || fail_closed
  browser_request_binding="$(jq -c \
    --arg probe_id "$EXPECTED_BROWSER_PROBE_ID" '
      .[0] + {status: "BOUND", probeId: $probe_id}
    ' <<<"$browser_ingress_matches")"
fi

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
  --arg build_artifact_evidence_class "$build_artifact_evidence_class" \
  --arg build_attestation_status "NOT_PUBLISHED" \
  --arg build_attestation_boundary "Cross-repository artifact content is not fetched because no least-privilege token is configured; artifact metadata is non-terminal and no SLSA attestation is claimed. Terminal browser-to-image binding is the same-session Ingress, Service, EndpointSlice, Ready Pod UID and imageID chain plus exact build-info source SHA." \
  --arg ingress_uid "$ingress_uid" \
  --arg service_uid "$service_uid" \
  --arg service_cluster_ip "$service_cluster_ip" \
  --argjson endpoint_slice_names "$endpoint_slice_names" \
  --argjson endpoint_slice_uids "$endpoint_slice_uids" \
  --argjson endpoint_pod_uids "$endpoint_pod_uids" \
  --argjson endpoint_network_bindings "$endpoint_network_bindings" \
  --argjson matching_ingress_routes "$matching_ingress_routes" \
  --argjson pod_build_info_hashes "$pod_build_info_hashes_json" \
  --argjson browser_request_binding "$browser_request_binding" \
  --argjson browser_asset_binding "$browser_asset_binding" '
  {
    schemaVersion: "faz25-p5-frontend-lineage-v2",
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
      buildArtifactEvidenceClass: $build_artifact_evidence_class,
      buildAttestationStatus: $build_attestation_status,
      buildAttestationBoundary: $build_attestation_boundary
    },
    route: {
      host: "testai.acik.com",
      ingress: {
        name: "platform",
        uid: $ingress_uid,
        className: "nginx",
        path: "/",
        serviceName: "frontend",
        servicePort: 80,
        matchingRoutes: $matching_ingress_routes
      },
      service: {
        name: "frontend",
        uid: $service_uid,
        type: "ClusterIP",
        clusterIp: $service_cluster_ip,
        selector: {"app.kubernetes.io/name": "frontend"}
      },
      endpointSlices: {
        names: $endpoint_slice_names,
        uids: $endpoint_slice_uids,
        readyPodUids: $endpoint_pod_uids,
        readyPodNetworkBindings: $endpoint_network_bindings
      },
      podBuildInfoSha256s: $pod_build_info_hashes,
      browserRequestBinding: $browser_request_binding,
      browserAssetBinding: $browser_asset_binding
    }
  }
  ' >"$report_tmp" || {
    rm -f "$report_tmp"
    fail_closed
  }
chmod 0600 "$report_tmp"
mv "$report_tmp" "$REPORT_PATH"
