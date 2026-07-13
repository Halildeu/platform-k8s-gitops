#!/usr/bin/env bash
set -euo pipefail

# Read-only post-reconcile acceptance for the canonical platform-test backend.

TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
TESTAI_URL="${TESTAI_URL:-https://testai.acik.com}"
REVISION="${REVISION:-${GITHUB_SHA:-}}"
DIGEST_MAP="${DIGEST_MAP:-}"
REPORT_PATH="${REPORT_PATH:-}"
CURRENT_GATE="preflight"
VERDICT="FAIL"
AUTH_GATE="skipped-no-credentials"
NORMALIZED_DIGEST_MAP='{}'

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

assert_current_main_revision() {
  local latest_main

  git fetch origin main --depth=1 --quiet
  latest_main=$(git rev-parse FETCH_HEAD)
  [[ "$latest_main" == "$REVISION" ]] || {
    echo "FAIL: runtime verification revision $REVISION was superseded by main $latest_main" >&2
    return 1
  }
}

# Invoked indirectly by the EXIT trap below.
# shellcheck disable=SC2329
write_report() {
  [[ -n "$REPORT_PATH" ]] || return 0
  local expected_digests='{}'
  local report_tmp="${REPORT_PATH}.tmp"

  expected_digests=$(jq -c . <<< "$NORMALIZED_DIGEST_MAP" 2>/dev/null) || expected_digests='{}'
  mkdir -p "$(dirname "$REPORT_PATH")" || return 0
  jq -n \
    --arg verdict "$VERDICT" \
    --arg failed_or_last_gate "$CURRENT_GATE" \
    --arg auth_gate "$AUTH_GATE" \
    --arg testai_url "$TESTAI_URL" \
    --argjson expected_digests "$expected_digests" \
    '{
      schemaVersion: "testai-backend-runtime-verification-v1",
      verdict: $verdict,
      failedOrLastGate: $failed_or_last_gate,
      authGate: $auth_gate,
      publicEntry: $testai_url,
      verificationMode: "read-only-runtime-evidence",
      verifierMutationPerformed: false,
      expectedDigests: $expected_digests
    }' > "$report_tmp" || {
      echo "WARN: failed to render backend runtime report" >&2
      rm -f "$report_tmp"
      return 0
    }
  if ! mv "$report_tmp" "$REPORT_PATH"; then
    echo "WARN: failed to publish backend runtime report to $REPORT_PATH" >&2
    rm -f "$report_tmp"
  fi
  return 0
}
trap 'write_report || true' EXIT

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

CURRENT_GATE="main-revision-fence-before-runtime"
assert_current_main_revision

CURRENT_GATE="exact-pod-imageid"
for spec in "${SERVICE_SPECS[@]}"; do
  IFS='|' read -r service selector <<< "$spec"
  digest=$(jq -r --arg service "$service" '.[$service] // empty' \
    <<< "$NORMALIZED_DIGEST_MAP")
  bash scripts/deploy/verify-pod-digest.sh \
    --context "$TEST_CONTEXT" \
    --namespace "$TEST_NAMESPACE" \
    --selector "app.kubernetes.io/name=${selector}" \
    --expected-digest "$digest"
done

CURRENT_GATE="public-edge"
status=$(curl -sko /dev/null -w '%{http_code}' "${TESTAI_URL}/api/users/all")
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
    curl -sko /dev/null -w '%{http_code}' \
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
if [[ -n "${SMOKE_AUTH_USERNAME:-}" && -n "${SMOKE_AUTH_PASSWORD:-}" ]]; then
  # Keep username/password out of argv and logs. Python reads the inherited
  # environment and writes only an URL-encoded request body to curl stdin.
  token=$(python3 - <<'PY' \
    | curl -sk -X POST \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-binary @- \
        "${TESTAI_URL}/realms/platform-test/protocol/openid-connect/token" \
    | jq -r '.access_token // empty'
import os
import urllib.parse

print(urllib.parse.urlencode({
    "grant_type": "password",
    "client_id": "frontend",
    "username": os.environ["SMOKE_AUTH_USERNAME"],
    "password": os.environ["SMOKE_AUTH_PASSWORD"],
}))
PY
  )
  [[ -n "$token" ]] || {
    echo "FAIL: JWT smoke token fetch failed" >&2
    exit 1
  }
  status=$(curl -sko /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${token}" \
    "${TESTAI_URL}/api/users/all?page=1&pageSize=1")
  unset token
  [[ "$status" == "200" ]] || {
    echo "FAIL: authenticated /api/users/all returned $status" >&2
    exit 1
  }
  AUTH_GATE="pass"
  echo "PASS: JWT auth flow"
else
  echo "NOTICE: JWT auth flow skipped; SMOKE_AUTH_* credentials are absent"
fi

CURRENT_GATE="main-revision-fence-after-runtime"
assert_current_main_revision
CURRENT_GATE="complete"
VERDICT="PASS"
echo "PASS: backend runtime digest, edge, readiness and stability gates"
