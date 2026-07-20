#!/usr/bin/env bash

# Verify that an immutable OCI digest was produced by one exact GitHub Actions
# run, signer workflow and source commit. `gh attestation verify` validates the
# GitHub/Sigstore trust root, certificate identity, transparency evidence and
# revocation state; the jq postcondition binds the signed statement to the run
# recorded by the content-addressed Faz 35 image set.
faz35_verify_image_attestation() {
  local image=$1 repository=$2 signer_workflow=$3 source_head=$4 workflow_run=$5
  local run_json='' run_url attestation_json='' subject_name subject_digest attempt

  for attempt in 1 2 3; do
    if run_json=$(gh api "repos/$repository/actions/runs/$workflow_run" \
      --jq '{databaseId:.id,headSha:.head_sha,status,conclusion,event,url:.html_url}' \
      2>/dev/null); then
      break
    fi
    sleep "$attempt"
  done
  if [ -z "$run_json" ]; then
    echo "FATAL: image workflow run could not be verified: $repository/$workflow_run" >&2
    return 1
  fi
  printf '%s' "$run_json" | jq -e \
    --argjson run "$workflow_run" --arg head "$source_head" '
      .databaseId == $run and .headSha == $head and
      .status == "completed" and .conclusion == "success" and
      (.event == "pull_request" or .event == "workflow_dispatch" or .event == "push") and
      (.url | type == "string" and length > 0)
    ' >/dev/null || {
    echo "FATAL: image workflow run is not a successful exact-source run: $repository/$workflow_run" >&2
    return 1
  }
  run_url=$(printf '%s' "$run_json" | jq -r '.url')
  subject_name=${image%@*}
  subject_digest=${image#*@sha256:}
  if [ "$subject_name" = "$image" ] ||
      ! printf '%s' "$subject_digest" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "FATAL: attestation verification requires an immutable sha256 image" >&2
    return 1
  fi

  for attempt in 1 2 3; do
    if attestation_json=$(gh attestation verify "oci://$image" \
      --repo "$repository" \
      --signer-workflow "$repository/$signer_workflow" \
      --source-digest "$source_head" \
      --deny-self-hosted-runners \
      --format json 2>/dev/null); then
      break
    fi
    sleep "$attempt"
  done
  if [ -z "$attestation_json" ]; then
    echo "FATAL: signed image provenance verification failed: $subject_name" >&2
    return 1
  fi
  printf '%s' "$attestation_json" | jq -e \
    --arg name "$subject_name" --arg digest "$subject_digest" --arg run_url "$run_url" '
      type == "array" and length > 0 and any(.[];
        .verificationResult.statement.predicateType == "https://slsa.dev/provenance/v1" and
        any(.verificationResult.statement.subject[]?;
          .name == $name and .digest.sha256 == $digest) and
        (.verificationResult.statement.predicate.runDetails.metadata.invocationId as $invocation |
          ($invocation == $run_url) or
          ($invocation | startswith($run_url + "/attempts/")))
      )
    ' >/dev/null || {
    echo "FATAL: signed provenance does not bind subject digest to the exact workflow run" >&2
    return 1
  }
}
