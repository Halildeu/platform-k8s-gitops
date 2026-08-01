#!/usr/bin/env bash
set -euo pipefail

# Read-only post-reconcile acceptance for the canonical platform-test backend.

TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
TESTAI_URL="${TESTAI_URL:-https://testai.acik.com}"
CRI_NODE_CONTAINER="${BACKEND_CRI_NODE_CONTAINER:-k3d-test-server-0}"
REVISION="${REVISION:-${GITHUB_SHA:-}}"
DIGEST_MAP="${DIGEST_MAP:-}"
REPORT_PATH="${REPORT_PATH:-}"
CURRENT_GATE="preflight"
VERDICT="FAIL"
AUTH_GATE="required-p5-view-persona"
NORMALIZED_DIGEST_MAP='{}'
MAP_FENCE_BEFORE_PASSED=false
MAP_FENCE_AFTER_PASSED=false

SERVICE_SPECS=(
  "auth-service|auth-service"
  "permission-service|permission-service"
  "user-service|user-service"
  "variant-service|variant-service"
  "core-data-service|core-data-service"
  "report-service|report-service"
  "schema-service|schema-service"
  "endpoint-admin-service|endpoint-admin-service"
  "audio-gateway-service|audio-gateway"
  "meeting-service|meeting-service"
  "transcript-service|transcript-service"
  "audit-event-consumer-service|audit-event-consumer-service"
  "api-gateway|api-gateway"
)

assert_current_backend_map() {
  local latest_main latest_file latest_map

  git fetch origin main --depth=1 --quiet
  latest_main=$(git rev-parse FETCH_HEAD)
  latest_file=$(mktemp "${TMPDIR:-/tmp}/testai-backend-overlay-latest.XXXXXX")
  if ! git show "${latest_main}:kustomize/overlays/test/kustomization.yaml" > "$latest_file"; then
    rm -f "$latest_file"
    echo "FAIL: unable to inspect the latest main backend map" >&2
    return 1
  fi
  if ! latest_map=$(python3 scripts/automation/backend-testai-digest-contract.py inspect \
    --kustomization "$latest_file"); then
    rm -f "$latest_file"
    echo "FAIL: latest main backend map is invalid" >&2
    return 1
  fi
  rm -f "$latest_file"
  [[ "$latest_map" == "$NORMALIZED_DIGEST_MAP" ]] || {
    echo "FAIL: runtime backend map was superseded on main" >&2
    return 1
  }
  git diff --quiet "$REVISION" "$latest_main" -- \
    docs/operations/services.yaml \
    .github/workflows/deploy-backend-testai.yml \
    .github/workflows/verify-testai-backend-rollout.yml \
    argocd/applications/platform-test.yaml \
    scripts/automation/backend-testai-digest-contract.py \
    scripts/automation/sync-test-overlay.sh \
    scripts/automation/apply-test-overlay-digests.py \
    scripts/deploy/reconcile-testai-backend-sequential.sh \
    scripts/deploy/ensure-argocd-cli.sh \
    scripts/deploy/verify-testai-backend-runtime.sh \
    scripts/deploy/verify-pod-digest.sh \
    scripts/deploy/gate-stability-window.sh || {
      echo "FAIL: runtime verifier contract was superseded on main" >&2
      return 1
    }
}

write_report() {
  [[ -n "$REPORT_PATH" ]] || return 1
  local expected_digests='{}'
  local report_tmp="${REPORT_PATH}.tmp"

  if ! expected_digests=$(jq -ce 'select(type == "object")' \
    <<< "$NORMALIZED_DIGEST_MAP" 2>/dev/null) || [[ -z "$expected_digests" ]]; then
    expected_digests='{}'
  fi
  mkdir -p "$(dirname "$REPORT_PATH")" || return 1
  umask 077
  rm -f "$report_tmp"
  jq -n \
    --arg verdict "$VERDICT" \
    --arg failed_or_last_gate "$CURRENT_GATE" \
    --arg auth_gate "$AUTH_GATE" \
    --arg testai_url "$TESTAI_URL" \
    --argjson map_fence_before_passed "$MAP_FENCE_BEFORE_PASSED" \
    --argjson map_fence_after_passed "$MAP_FENCE_AFTER_PASSED" \
    --argjson expected_digests "$expected_digests" \
    '{
      schemaVersion: "testai-backend-runtime-verification-v1",
      verdict: $verdict,
      failedOrLastGate: $failed_or_last_gate,
      authGate: $auth_gate,
      publicEntry: $testai_url,
      verificationMode: "read-only-runtime-evidence",
      verifierMutationPerformed: false,
      mapFenceBeforePassed: $map_fence_before_passed,
      mapFenceAfterPassed: $map_fence_after_passed,
      expectedDigests: $expected_digests
    }' > "$report_tmp" || {
      rm -f "$report_tmp"
      return 1
    }
  chmod 0600 "$report_tmp" || {
    rm -f "$report_tmp"
    return 1
  }
  mv "$report_tmp" "$REPORT_PATH" || {
    rm -f "$report_tmp"
    return 1
  }
  [[ -s "$REPORT_PATH" ]]
}

# Preserve the verifier's original result, but never allow a successful
# runtime verification to outlive missing or unpublishable evidence.
# shellcheck disable=SC2329
finalize_report() {
  local original_status=$?
  trap - EXIT
  if ! write_report; then
    echo "FAIL: backend runtime evidence report could not be published" >&2
    if (( original_status == 0 )); then
      original_status=1
    fi
  fi
  exit "$original_status"
}
trap finalize_report EXIT

for command in git kubectl jq python3 curl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FAIL: required command not found: $command" >&2
    exit 1
  }
done
[[ -n "$DIGEST_MAP" ]] || {
  echo "FAIL: DIGEST_MAP is required" >&2
  exit 1
}
[[ "$REVISION" =~ ^[a-f0-9]{40}$ ]] || {
  echo "FAIL: REVISION must be a 40-character lowercase git SHA" >&2
  exit 1
}
NORMALIZED_DIGEST_MAP=$(printf '%s' "$DIGEST_MAP" \
  | python3 scripts/automation/backend-testai-digest-contract.py normalize)

CURRENT_GATE="backend-map-fence-before-runtime"
assert_current_backend_map
MAP_FENCE_BEFORE_PASSED=true

CURRENT_GATE="exact-pod-imageid"
for spec in "${SERVICE_SPECS[@]}"; do
  IFS='|' read -r service selector <<< "$spec"
  digest=$(jq -r --arg service "$service" '.[$service] // empty' \
    <<< "$NORMALIZED_DIGEST_MAP")
  bash scripts/deploy/verify-pod-digest.sh \
    --context "$TEST_CONTEXT" \
    --namespace "$TEST_NAMESPACE" \
    --selector "app.kubernetes.io/name=${selector}" \
    --expected-digest "$digest" \
    --expected-repository "ghcr.io/halildeu/platform-backend-${service}" \
    --cri-node-container "$CRI_NODE_CONTAINER"
done

CURRENT_GATE="public-edge"
status=$(curl --proto '=https' --tlsv1.2 --max-time 20 -sS \
  -o /dev/null -w '%{http_code}' "${TESTAI_URL}/api/users/all")
case "$status" in
  200|401|403)
    echo "PASS: api-gateway public edge chain alive (HTTP $status)"
    ;;
  *)
    echo "FAIL: api-gateway public edge returned $status; expected 200/401/403" >&2
    exit 1
    ;;
esac

CURRENT_GATE="in-cluster-readiness"
for spec in "${SERVICE_SPECS[@]}"; do
  IFS='|' read -r service selector <<< "$spec"
  pod=$(kubectl --context "$TEST_CONTEXT" get pod \
    -n "$TEST_NAMESPACE" \
    -l "app.kubernetes.io/name=${selector}" \
    --field-selector=status.phase=Running \
    -o json \
    | jq -r '.items
        | map(select(.metadata.deletionTimestamp == null))
        | sort_by(.metadata.creationTimestamp)
        | last
        | .metadata.name // empty')
  [[ -n "$pod" ]] || {
    echo "FAIL: no live pod found for $service readiness" >&2
    exit 1
  }
  status=$(kubectl --context "$TEST_CONTEXT" exec "$pod" \
    -n "$TEST_NAMESPACE" -- \
    curl -so /dev/null -w '%{http_code}' \
    http://localhost:8081/actuator/health/readiness 2>/dev/null || echo "000")
  [[ "$status" == "200" ]] || {
    echo "FAIL: $service readiness returned $status" >&2
    exit 1
  }
  echo "PASS: $service readiness 200"
done

CURRENT_GATE="stability-window"
for spec in "${SERVICE_SPECS[@]}"; do
  IFS='|' read -r _service selector <<< "$spec"
  bash scripts/deploy/gate-stability-window.sh \
    --service "$selector" \
    --context "$TEST_CONTEXT" \
    --namespace "$TEST_NAMESPACE" \
    --catalog docs/operations/services.yaml
done

CURRENT_GATE="jwt-auth-flow"
[[ "${SMOKE_AUTH_USERNAME:-}" == "p5-readiness-viewer" ]] || {
  echo "FAIL: dedicated P5 smoke username is absent or mismatched" >&2
  exit 1
}
[[ -n "${SMOKE_AUTH_PASSWORD:-}" ]] || {
  echo "FAIL: dedicated P5 smoke password is absent" >&2
  exit 1
}
[[ -n "${SMOKE_CLIENT_SECRET:-}" ]] || {
  echo "FAIL: confidential smoke-client secret is absent" >&2
  exit 1
}

# Keep username/password out of argv and logs. Python reads the inherited
# environment and writes only an URL-encoded request body to curl stdin.
token=$(
  python3 -c '
import os
import sys
import urllib.parse

sys.stdout.write(urllib.parse.urlencode({
    "grant_type": "password",
    "client_id": "smoke-client",
    "client_secret": os.environ["SMOKE_CLIENT_SECRET"],
    "username": os.environ["SMOKE_AUTH_USERNAME"],
    "password": os.environ["SMOKE_AUTH_PASSWORD"],
}))
' |
    curl -fsS -X POST \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-binary @- \
      "${TESTAI_URL}/realms/platform-test/protocol/openid-connect/token" \
    | jq -r '.access_token // empty'
)
[[ -n "$token" ]] || {
  echo "FAIL: JWT smoke token fetch failed" >&2
  exit 1
}

# Bind the returned token to the exact named persona without logging the JWT.
python3 -c '
import base64
import json
import sys

token = sys.stdin.read().strip()
parts = token.split(".")
if len(parts) != 3:
    raise SystemExit(1)
payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
raise SystemExit(0 if payload.get("preferred_username") == sys.argv[1] else 1)
' "$SMOKE_AUTH_USERNAME" <<<"$token" || {
  unset token
  echo "FAIL: JWT subject is not the dedicated P5 persona" >&2
  exit 1
}

authz_tmp=$(mktemp "${TMPDIR:-/tmp}/testai-p5-authz.XXXXXX")
chmod 0600 "$authz_tmp"
# Feed the bearer header through curl config stdin so the token never appears
# in curl argv, runner logs or the evidence report.
if ! authz_status=$(printf 'header = "Authorization: Bearer %s"\n' "$token" \
  | curl --config - -sS -o "$authz_tmp" -w '%{http_code}' \
      "${TESTAI_URL}/api/v1/authz/me"); then
  unset token
  rm -f "$authz_tmp"
  echo "FAIL: P5 authz snapshot request failed" >&2
  exit 1
fi
unset token
[[ "$authz_status" == "200" ]] || {
  rm -f "$authz_tmp"
  echo "FAIL: P5 authz snapshot did not return HTTP 200" >&2
  exit 1
}
authz_snapshot="$(<"$authz_tmp")"
rm -f "$authz_tmp"
jq -e '
  (.userId | tostring) == "6" and
  (.subscriberId | tostring) == "6" and
  .superAdmin == false and
  .roles == ["P5_READINESS_VIEWER"] and
  .modules == {"INTERVIEW_EVIDENCE": "VIEW"} and
  .allowedModules == ["INTERVIEW_EVIDENCE"] and
  .permissions == ["INTERVIEW_EVIDENCE"]
' <<<"$authz_snapshot" >/dev/null
unset authz_snapshot
AUTH_GATE="pass-p5-readiness-viewer-exact-view"
echo "PASS: JWT auth flow and exact P5 VIEW-only snapshot"

CURRENT_GATE="backend-map-fence-after-runtime"
assert_current_backend_map
MAP_FENCE_AFTER_PASSED=true
CURRENT_GATE="complete"
VERDICT="PASS"
echo "PASS: backend runtime digest, edge, readiness and stability gates"
