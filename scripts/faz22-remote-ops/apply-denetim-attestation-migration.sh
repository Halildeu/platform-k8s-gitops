#!/usr/bin/env bash
# Rollout/acceptance adapter for the bounded Denetim attestation/KID migration.
# The permanent AnyDesk-like product runtime remains the provider-neutral
# endpoint-agent <-> broker contract; it must not depend on this script, any
# named SSH management host, or GitHub Actions. This adapter accepts the
# migration only after a
# transaction-bound attended product command produces a session-scoped broker
# trust refresh. Any post-mutation failure triggers hash-verified rollback.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PATCH_SCRIPT="${PATCH_SCRIPT:-${SCRIPT_DIR}/denetim-device-key-view-only-env-patch.ps1}"
EXPECTED_STAGING_HOST="${EXPECTED_STAGING_HOST:-aiserver}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
NAMESPACE="${NAMESPACE:-platform-test}"
BROKER_DEPLOYMENT="${BROKER_DEPLOYMENT:-endpoint-admin-remote-bridge-device-key}"
DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-denetim-pc}"
DENETIM_SSH_CONFIG="${DENETIM_SSH_CONFIG:-/home/aiadmin/.ssh/config}"
REMOTE_PATCH_SCRIPT=""
PATCH_SCRIPT_SHA256=""

# The release policy is the only release identity authority. The endpoint
# patch receives a transaction-scoped snapshot; it contains no independently
# maintained release tag or digest defaults.
# Resolved from this committed script directory.
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "denetim-attestation-migration: missing command: $1" >&2
    exit 2
  }
}

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    shasum -a 256 "$path" | awk '{print $1}'
  fi
}

encode_powershell() {
  iconv -f UTF-8 -t UTF-16LE | base64 -w0
}

run_denetimepc_powershell() {
  local body="$1" encoded
  encoded="$(printf '%s' "$body" | encode_powershell)"
  ssh -F "$DENETIM_SSH_CONFIG" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 \
    "$DENETIM_SSH_TARGET" \
    "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand '$encoded'"
}

verified_patch_body() {
  local arguments="$1"
  printf "\$p='%s'; \$expected='%s'; if (-not (Test-Path -LiteralPath \$p -PathType Leaf)) { throw 'transaction patch script is absent' }; \$actual=(Get-FileHash -LiteralPath \$p -Algorithm SHA256).Hash.ToLowerInvariant(); if (\$actual -ne \$expected) { throw 'transaction patch script SHA256 mismatch' }; & \$p %s" \
    "$REMOTE_PATCH_SCRIPT" "$PATCH_SCRIPT_SHA256" "$arguments"
}

powershell_single_quote() {
  printf '%s' "$1" | sed "s/'/''/g"
}

release_policy_patch_arguments() {
  validate_release_policy_bindings
  printf -- "-ExpectedReleaseTag '%s' -ReleaseManifestBaseUrl '%s' -ReleaseAssetBaseUrl '%s' -ExpectedReleaseManifestSha256 '%s' -ExpectedBinarySha256 '%s' -ExpectedArtifactHostDigest '%s' -ExpectedArtifactHostImageRef '%s'" \
    "$(powershell_single_quote "$EXPECTED_AGENT_TAG")" \
    "$(powershell_single_quote "$GITHUB_RELEASE_BASE_URL")" \
    "$(powershell_single_quote "$ARTIFACT_RELEASE_BASE_URL")" \
    "$(powershell_single_quote "$EXPECTED_RELEASE_MANIFEST_SHA256")" \
    "$(powershell_single_quote "$EXPECTED_AGENT_SHA256")" \
    "$(powershell_single_quote "$EXPECTED_ARTIFACT_HOST_DIGEST")" \
    "$(powershell_single_quote "$EXPECTED_ARTIFACT_HOST_IMAGE_REF")"
}

validate_release_policy_snapshot() {
  local variable_name="$1" filter="$2" expected_value actual_value
  expected_value="$(jq -er "$filter" "$ENDPOINT_AGENT_RELEASE_POLICY_PATH")"
  actual_value="${!variable_name:-}"
  [ "$actual_value" = "$expected_value" ] || {
    echo "denetim-attestation-migration: release policy override rejected: $variable_name" >&2
    exit 2
  }
}

validate_release_policy_bindings() {
  validate_release_policy_snapshot EXPECTED_AGENT_TAG '.current_bounded_pilot.release_tag'
  validate_release_policy_snapshot GITHUB_RELEASE_BASE_URL '.current_bounded_pilot.github_release_base_url'
  validate_release_policy_snapshot ARTIFACT_RELEASE_BASE_URL '.current_bounded_pilot.artifact_release_base_url'
  validate_release_policy_snapshot EXPECTED_RELEASE_MANIFEST_SHA256 '.current_bounded_pilot.release_manifest_sha256'
  validate_release_policy_snapshot EXPECTED_AGENT_SHA256 '.current_bounded_pilot.endpoint_agent_sha256'
  validate_release_policy_snapshot EXPECTED_ARTIFACT_HOST_DIGEST '.current_bounded_pilot.artifact_host_digest'
  validate_release_policy_snapshot EXPECTED_ARTIFACT_HOST_IMAGE_REF '.current_bounded_pilot.artifact_host_image_ref'
}

validate_mask_rect_bps() {
  local value="${DLP_MASK_RECT_BPS:-}" x y width height
  [[ "$value" =~ ^[0-9]{1,5},[0-9]{1,5},[0-9]{1,5},[0-9]{1,5}$ ]] || {
    echo "denetim-attestation-migration: DLP_MASK_RECT_BPS must be canonical x,y,width,height" >&2
    return 2
  }
  IFS=',' read -r x y width height <<<"$value"
  x=$((10#$x)); y=$((10#$y)); width=$((10#$width)); height=$((10#$height))
  (( x <= 10000 && y <= 10000 && width > 0 && height > 0 \
     && x + width <= 10000 && y + height <= 10000 )) || {
    echo "denetim-attestation-migration: DLP_MASK_RECT_BPS is empty or outside the primary monitor" >&2
    return 2
  }
}

remove_remote_patch_best_effort() {
  [[ -n "$REMOTE_PATCH_SCRIPT" ]] || return 0
  if ! run_denetimepc_powershell "Remove-Item -LiteralPath '${REMOTE_PATCH_SCRIPT}' -Force -ErrorAction SilentlyContinue" \
    >/dev/null 2>&1; then
    echo "denetim-attestation-migration: WARN transaction-specific remote patch cleanup could not be verified" >&2
  fi
}

validate_inputs() {
  local host_short current_context
  host_short="$(hostname -s)"
  [[ "$host_short" == "$EXPECTED_STAGING_HOST" ]] || {
    echo "denetim-attestation-migration: must run on $EXPECTED_STAGING_HOST; got $host_short" >&2
    exit 2
  }
  [[ -f "$PATCH_SCRIPT" ]] || {
    echo "denetim-attestation-migration: patch script is absent" >&2
    exit 2
  }
  validate_mask_rect_bps
  if ! current_context="$(kubectl config current-context 2>/dev/null)"; then
    current_context=""
  fi
  [[ "$current_context" == "$KUBE_CONTEXT" ]] || {
    echo "denetim-attestation-migration: current kubectl context must be $KUBE_CONTEXT; got $current_context" >&2
    exit 2
  }
  kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get deployment "$BROKER_DEPLOYMENT" >/dev/null
  ssh -F "$DENETIM_SSH_CONFIG" -G "$DENETIM_SSH_TARGET" >/dev/null
}

validate_product_evidence() {
  local evidence_dir="$1" expected_session_id="$2" proof_start_marker="$3" proof_line expected_session_sha256
  [[ -n "$evidence_dir" && -d "$evidence_dir" ]] || {
    echo "denetim-attestation-migration: product evidence directory is absent" >&2
    return 1
  }
  [[ -f "$proof_start_marker" ]] || {
    echo "denetim-attestation-migration: transaction proof start marker is absent" >&2
    return 1
  }
  for required in browser.json summary.json open-session.body endpoint-agent-relevant.log broker-relevant.log; do
    [[ -s "$evidence_dir/$required" ]] || {
      echo "denetim-attestation-migration: required product evidence is absent: $required" >&2
      return 1
    }
    [[ "$evidence_dir/$required" -nt "$proof_start_marker" ]] || {
      echo "denetim-attestation-migration: product evidence predates this transaction command: $required" >&2
      return 1
    }
  done
  jq -e --arg session "$expected_session_id" '
    .status == "accepted-candidate"
    and .sessionId == $session
    and .consentWait == "granted"
    and (.brokerSignals | index("CONSENT_GRANTED") != null)
    and (.brokerSignals | index("CONSENT_DENIED") == null)
  ' "$evidence_dir/summary.json" >/dev/null || {
    echo "denetim-attestation-migration: smoke summary is not transaction-bound accepted evidence" >&2
    return 1
  }
  jq -e '.consentPromptSent == true' "$evidence_dir/open-session.body" >/dev/null || {
    echo "denetim-attestation-migration: attended consent prompt evidence is absent" >&2
    return 1
  }
  expected_session_sha256="sha256:$(printf '%s' "$expected_session_id" | sha256_text)"
  jq -e --arg sessionSha256 "$expected_session_sha256" '
    .schemaVersion == "faz22.6.viewOnlyViewerProductChildEvidence.v2"
    and .evidenceType == "browser"
    and (.sourceRevision == env.SOURCE_REVISION)
    and .producer.kind == "browser-harness"
    and .producer.toolVersion == "v3-ack-drain"
    and .payload.ackDrainCompleted == true
    and .payload.ackDrainCutoffAt == .payload.pilotEndedAt
    and (.payload.ackDrainNonceSha256 | test("^sha256:[a-f0-9]{64}$"))
    and (.payload.ackDrainClosureKind == "none"
      or .payload.ackDrainClosureKind == "stream-ended-after-drain")
    and .payload.renderAckRejectedCount == 0
    and .payload.renderAckPendingCount == 0
    and .binding.sessionSha256 == $sessionSha256
    and .payload.renderAckAcceptedCount >= 100
    and .payload.renderAckAcceptedCount == .payload.renderAckAttemptedCount
  ' "$evidence_dir/browser.json" >/dev/null || {
    echo "denetim-attestation-migration: browser render ACK evidence is below the acceptance contract" >&2
    return 1
  }
  grep -F "session=\"$expected_session_id\"" "$evidence_dir/endpoint-agent-relevant.log" \
    | grep -F 'granted=true' >/dev/null || {
      echo "denetim-attestation-migration: endpoint attended-consent evidence is absent" >&2
      return 1
    }
  proof_line="$(grep -F "session=${expected_session_id} " "$evidence_dir/broker-relevant.log" \
    | grep -F 'CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true' \
    | tail -1 || true)"
  [[ -n "$proof_line" ]] || {
    echo "denetim-attestation-migration: transaction-bound broker trust refresh is absent from captured product evidence" >&2
    return 1
  }
  printf '%s' "$proof_line"
}

rollback_armed=0
rollback_environment_backup=""
transaction_id=""
product_proof_verified=0

rollback_on_failure() {
  local original_rc=$?
  trap - EXIT
  if (( rollback_armed == 1 )); then
    local inspect_body inspect_output inspect_rc rollback_body rollback_output rollback_rc
    local release_body release_output release_rc
    if (( product_proof_verified == 1 )); then
      release_body="$(verified_patch_body "-Action ReleaseLock -TransactionId '${transaction_id}' -Confirm:\$false")"
      set +e
      release_output="$(run_denetimepc_powershell "$release_body" 2>&1)"
      release_rc=$?
      set -e
      if (( release_rc == 0 )) &&
        grep -Eq '^status=transaction-lock-(released|already-released)$' \
          <<<"$(tr -d '\r' <<<"$release_output")"; then
        remove_remote_patch_best_effort
        echo "status=transaction-bound-product-attestation-verified-after-release-reconciliation"
        exit 0
      fi
      echo "denetim-attestation-migration: CRITICAL product proof passed but accepted lock release could not be reconciled" >&2
      exit 1
    fi
    inspect_body="$(verified_patch_body "-Action Inspect -TransactionId '${transaction_id}' -Confirm:\$false")"
    set +e
    inspect_output="$(run_denetimepc_powershell "$inspect_body" 2>&1)"
    inspect_rc=$?
    set -e
    if (( inspect_rc != 0 )) ||
      ! grep -Fq 'status=transaction-state-observed' <<<"$inspect_output"; then
      echo "denetim-attestation-migration: CRITICAL could not serialize with Apply and inspect the transaction state; deadline recovery remains armed" >&2
      exit 1
    fi
    if grep -Fq 'backupPresent=false' <<<"$inspect_output"; then
      if ! grep -Fq 'lockState=absent' <<<"$inspect_output" ||
        ! grep -Eq '^markerState=(absent|foreign)$' <<<"$(tr -d '\r' <<<"$inspect_output")" ||
        ! grep -Fq 'summaryState=absent' <<<"$inspect_output"; then
        echo "denetim-attestation-migration: CRITICAL transaction has partial state without a rollback backup; deadline recovery remains armed" >&2
        exit 1
      fi
      remove_remote_patch_best_effort
      echo "denetim-attestation-migration: serialized inspection proved that the mutation boundary was not crossed" >&2
      exit "$original_rc"
    fi
    grep -Fq 'backupPresent=true' <<<"$inspect_output" || {
      echo "denetim-attestation-migration: CRITICAL transaction inspection returned an invalid backup state" >&2
      exit 1
    }

    echo "denetim-attestation-migration: session-bound product proof absent; restoring protected pre-mutation service environment" >&2
    rollback_body="$(verified_patch_body "-Action Rollback -TransactionId '${transaction_id}' -RollbackEnvironmentBackup '${rollback_environment_backup}' -Confirm:\$false")"
    set +e
    rollback_output="$(run_denetimepc_powershell "$rollback_body" 2>&1)"
    rollback_rc=$?
    set -e
    printf '%s\n' "$rollback_output" | grep -E '^(status|restoredServiceEnvironmentSha256)=' || true
    if (( rollback_rc != 0 )) || ! grep -Fq 'status=rollback-restored-service-running' <<<"$rollback_output"; then
      echo "denetim-attestation-migration: CRITICAL verified rollback failed; inspect Denetim PC protected local evidence" >&2
      exit 1
    fi
    remove_remote_patch_best_effort
    echo "denetim-attestation-migration: rollback restored and hash-verified" >&2
  fi
  exit "$original_rc"
}

main() {
  (( $# > 0 )) || {
    echo "denetim-attestation-migration: a transaction-bound attended product proof command is required" >&2
    exit 2
  }
  need_cmd ssh
  need_cmd scp
  need_cmd kubectl
  need_cmd iconv
  need_cmd base64
  need_cmd awk
  need_cmd grep
  need_cmd jq
  need_cmd sed
  need_cmd rm
  need_cmd sleep
  validate_inputs

  local session_id session_binding_sha256 apply_body apply_output evidence_summary summary_hash_output remote_scp_path release_policy_arguments mask_policy_arguments
  if [[ -n "${TRANSACTION_ID_OVERRIDE:-}" ]]; then
    [[ "${ALLOW_TEST_TRANSACTION_ID_OVERRIDE:-0}" == "1" ]] || {
      echo "denetim-attestation-migration: TRANSACTION_ID_OVERRIDE is test-only and requires ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1" >&2
      exit 2
    }
    transaction_id="$TRANSACTION_ID_OVERRIDE"
  else
    [[ -r /proc/sys/kernel/random/uuid ]] || {
      echo "denetim-attestation-migration: kernel UUID source is unavailable" >&2
      exit 2
    }
    transaction_id="$(tr -d '-' </proc/sys/kernel/random/uuid)"
  fi
  [[ "$transaction_id" =~ ^[a-f0-9]{32}$ ]] || {
    echo "denetim-attestation-migration: generated transaction ID is invalid" >&2
    exit 2
  }
  PATCH_SCRIPT_SHA256="$(sha256_file "$PATCH_SCRIPT")"
  [[ "$PATCH_SCRIPT_SHA256" =~ ^[a-f0-9]{64}$ ]] || {
    echo "denetim-attestation-migration: local patch script SHA256 is invalid" >&2
    exit 2
  }
  REMOTE_PATCH_SCRIPT="C:\\Temp\\denetim-device-key-view-only-env-patch-${transaction_id}.ps1"
  remote_scp_path="C:/Temp/denetim-device-key-view-only-env-patch-${transaction_id}.ps1"
  scp -F "$DENETIM_SSH_CONFIG" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 \
    "$PATCH_SCRIPT" "${DENETIM_SSH_TARGET}:${remote_scp_path}" >/dev/null

  rollback_environment_backup="C:\\ProgramData\\EndpointAgent\\rollout-evidence\\denetim-device-key-view-only-${transaction_id}\\EndpointAgent-environment-before.json"
  session_id="rb-viewonly-attended-${transaction_id}"
  session_binding_sha256="sha256:$(printf '%s' "$session_id" | sha256_text)"
  release_policy_arguments="$(release_policy_patch_arguments)"
  mask_policy_arguments="-ExpectedViewOnlyMaskRectBps '$(powershell_single_quote "$DLP_MASK_RECT_BPS")'"
  apply_body="$(verified_patch_body "-Action Apply -TransactionId '${transaction_id}' ${release_policy_arguments} ${mask_policy_arguments} -Confirm:\$false")"
  rollback_armed=1
  trap rollback_on_failure EXIT
  apply_output="$(run_denetimepc_powershell "$apply_body")"
  printf '%s\n' "$apply_output" | grep -E '^(status|evidence)='
  grep -Fq 'status=configuration-written-service-running-awaiting-broker-proof' <<<"$apply_output" || {
    echo "denetim-attestation-migration: endpoint apply did not return the bounded success status" >&2
    exit 1
  }

  evidence_summary="$(sed -n 's/^evidence=//p' <<<"$apply_output" | tail -1 | tr -d '\r')"
  [[ "$evidence_summary" == "C:\\ProgramData\\EndpointAgent\\rollout-evidence\\denetim-device-key-view-only-${transaction_id}\\summary.json" ]] || {
    echo "denetim-attestation-migration: endpoint evidence path is outside the canonical protected root" >&2
    exit 1
  }

  local summary_hash_body
  summary_hash_body="\$p='${evidence_summary}'; \$h=(Get-FileHash -LiteralPath \$p -Algorithm SHA256).Hash.ToLowerInvariant(); Write-Output ('summarySha256=' + \$h)"
  summary_hash_output="$(run_denetimepc_powershell "$summary_hash_body")"
  grep -Eq '^summarySha256=[a-f0-9]{64}$' <<<"$(tr -d '\r' <<<"$summary_hash_output")" || {
    echo "denetim-attestation-migration: endpoint summary digest could not be verified" >&2
    exit 1
  }
  printf '%s\n' "$summary_hash_output" | tr -d '\r'

  [[ -n "${EVIDENCE_DIR:-}" && -d "$EVIDENCE_DIR" ]] || {
    echo "denetim-attestation-migration: EVIDENCE_DIR must exist before the product proof command" >&2
    exit 2
  }
  local proof_start_marker
  for required in browser.json summary.json open-session.body endpoint-agent-relevant.log broker-relevant.log; do
    rm -f "$EVIDENCE_DIR/$required"
  done
  proof_start_marker="$EVIDENCE_DIR/.transaction-proof-start-${transaction_id}"
  : >"$proof_start_marker"
  # Separate marker/evidence mtimes even on one-second-resolution filesystems.
  sleep 2
  SESSION_ID="$session_id" SESSION_SHA256="$session_binding_sha256" "$@"
  local proof_line
  proof_line="$(validate_product_evidence "$EVIDENCE_DIR" "$session_id" "$proof_start_marker")"
  [[ -n "$proof_line" ]] || {
    echo "denetim-attestation-migration: broker proof line is empty after evidence validation" >&2
    exit 1
  }
  rm -f "$proof_start_marker"
  product_proof_verified=1

  local proof_sha256 transaction_proof_sha256 session_sha256 release_body release_output
  proof_sha256="$(printf '%s' "$proof_line" | sha256_text)"
  transaction_proof_sha256="$(printf '%s\n%s' "$transaction_id" "$proof_line" | sha256_text)"
  session_sha256="$(printf '%s' "$session_id" | sha256_text)"
  release_body="$(verified_patch_body "-Action ReleaseLock -TransactionId '${transaction_id}' -Confirm:\$false")"
  release_output="$(run_denetimepc_powershell "$release_body")"
  grep -Eq '^status=transaction-lock-(released|already-released)$' <<<"$(tr -d '\r' <<<"$release_output")" || {
    echo "denetim-attestation-migration: transaction proof passed but lock release was not verified" >&2
    exit 1
  }
  rollback_armed=0
  trap - EXIT
  remove_remote_patch_best_effort
  echo "status=transaction-bound-product-attestation-verified"
  echo "brokerProofLineSha256=$proof_sha256"
  echo "transactionBrokerProofSha256=$transaction_proof_sha256"
  echo "sessionSha256=$session_sha256"
  echo "rollbackMaterial=retained-locally-non-shareable-cleanup-scheduled"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
