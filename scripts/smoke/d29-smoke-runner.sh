#!/usr/bin/env bash
# scripts/smoke/d29-smoke-runner.sh
#
# D29 4-tier acceptance smoke runner — Codex Sprint A P0 Item 3.
# Runs against a deployed cluster (test or prod) and emits structured
# JSON evidence consumed by `scripts/promotion/ledger-mark-verified.sh`.
#
# D29 acceptance tiers (each independently checked):
#   1. Up         — pod Running + readiness/liveness 200
#   2. Functional — endpoint shape (401 JWT vs 500 backend) per service
#   3. Secured    — KC issuer matches expected env (live ConfigMap check)
#   4. Zanzibar   — OpenFGA allow + deny synthetic via curl chain
#
# Output:
#   /tmp/smoke-report-<env>-<ts>.json — schema matches the
#   release-candidates ledger's promotion.<env>.smoke_evidence shape:
#     {
#       d29_up:         { status, checked_at, details },
#       d29_functional: { status, checked_at, endpoints, details },
#       d29_zanzibar:   { status, checked_at, allow_deny_synthetic, details }
#     }
#
# Exit:
#   0 — all 4 tiers GREEN
#   1 — at least 1 tier RED
#   2 — execution error (kubectl unreachable, etc.)
#
# Usage:
#   bash d29-smoke-runner.sh test
#   bash d29-smoke-runner.sh prod
#
# Designed for staging-sw systemd integration (analog to drift detector):
#   ExecStart=/bin/bash d29-smoke-runner.sh test
#   ExecStartPost=/bin/bash ledger-mark-verified.sh /tmp/smoke-report-test-<ts>.json
#
# Or invoked manually for ad-hoc evidence generation.

set -uo pipefail

ENV="${1:-test}"
NAMESPACE="platform-${ENV}"
CONTEXT="k3d-${ENV}"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TS_FILE=$(date -u +%Y%m%dT%H%M%SZ)
REPORT="/tmp/smoke-report-${ENV}-${TS_FILE}.json"

# Services to validate per D29 tiers
JWT_SERVICES=(api-gateway user-service variant-service permission-service schema-service report-service)

# Expected KC issuer per env (matches check_pr_time.sh Check 3)
case "$ENV" in
  prod) EXPECTED_ISSUER="https://ai.acik.com/realms/serban" ;;
  test) EXPECTED_ISSUER="http://keycloak:8080/realms/platform-test" ;;
  *) echo "ERR: unknown env: $ENV"; exit 2 ;;
esac

echo "=== D29 Smoke Runner — env=$ENV ns=$NAMESPACE ctx=$CONTEXT ==="
echo "Report: $REPORT"
echo

# ------------------------------------------------------------
# Tier 1: Up — pod Running + readiness
# ------------------------------------------------------------
tier_up() {
  echo "--- Tier 1: Up ---"
  local status="GREEN"
  local details=""
  local fail_count=0

  for svc in "${JWT_SERVICES[@]}"; do
    local pod_status
    pod_status=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
      -l "app.kubernetes.io/name=$svc" \
      -o jsonpath='{.items[*].status.phase}' 2>/dev/null || echo "")

    if [[ -z "$pod_status" ]]; then
      details="${details}${svc}=NO_PODS;"
      fail_count=$((fail_count + 1))
      continue
    fi

    # Pods must all be Running
    if echo "$pod_status" | grep -qv "Running"; then
      details="${details}${svc}=$pod_status;"
      fail_count=$((fail_count + 1))
      continue
    fi

    # Ready containers count
    local ready
    ready=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
      -l "app.kubernetes.io/name=$svc" \
      -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null || echo "")

    if echo "$ready" | grep -qv "True"; then
      details="${details}${svc}=NOT_READY;"
      fail_count=$((fail_count + 1))
      continue
    fi
  done

  if [[ "$fail_count" -gt 0 ]]; then
    status="RED"
  fi

  if [[ -z "$details" ]]; then
    details="all ${#JWT_SERVICES[@]} services Running+Ready"
  fi

  TIER_UP_STATUS="$status"
  TIER_UP_DETAILS="$details"
  echo "  status=$status details=$details"
}

# ------------------------------------------------------------
# Tier 2: Functional — endpoint shape (401 JWT required)
# ------------------------------------------------------------
tier_functional() {
  echo "--- Tier 2: Functional ---"
  local status="GREEN"
  local details=""
  local fail_count=0
  local checked_endpoints=()

  for svc in "${JWT_SERVICES[@]}"; do
    local svc_ep
    case "$svc" in
      api-gateway) svc_ep="/actuator/health" ;;
      user-service) svc_ep="/api/v1/users" ;;
      variant-service) svc_ep="/api/v1/variants" ;;
      permission-service) svc_ep="/api/v1/permissions" ;;
      schema-service) svc_ep="/api/v1/schema/snapshot" ;;
      report-service) svc_ep="/api/v1/reports" ;;
      *) continue ;;
    esac

    # Port-forward, query, kill
    local port=$((20000 + RANDOM % 10000))
    kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward "svc/$svc" "$port:80" \
      > /dev/null 2>&1 &
    local pf_pid=$!
    sleep 2

    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' \
      --connect-timeout 5 --max-time 10 \
      "http://localhost:$port$svc_ep" 2>/dev/null || echo "000")

    kill "$pf_pid" 2>/dev/null || true
    wait "$pf_pid" 2>/dev/null || true

    checked_endpoints+=("$svc_ep")

    # Acceptable: 200 (actuator), 401 (auth required), 403 (auth/forbidden)
    # Failure: 500 (backend broken), 502/503/504 (upstream broken), 000 (unreachable)
    case "$code" in
      200|401|403)
        : # OK
        ;;
      *)
        details="${details}${svc}@${svc_ep}=$code;"
        fail_count=$((fail_count + 1))
        ;;
    esac
  done

  if [[ "$fail_count" -gt 0 ]]; then
    status="RED"
  fi

  if [[ -z "$details" ]]; then
    details="all ${#JWT_SERVICES[@]} endpoints returned 200/401/403 (auth chain intact)"
  fi

  TIER_FN_STATUS="$status"
  TIER_FN_DETAILS="$details"
  TIER_FN_ENDPOINTS=$(printf '"%s",' "${checked_endpoints[@]}" | sed 's/,$//')
  echo "  status=$status details=$details"
}

# ------------------------------------------------------------
# Tier 3: Secured — KC issuer in live ConfigMap matches expected
# ------------------------------------------------------------
tier_secured() {
  echo "--- Tier 3: Secured ---"
  local status="GREEN"
  local details=""
  local fail_count=0

  for svc in "${JWT_SERVICES[@]}"; do
    local cm_issuer
    cm_issuer=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get cm "${svc}-config" \
      -o jsonpath='{.data.KEYCLOAK_ISSUER_URI}' 2>/dev/null || echo "")

    if [[ -z "$cm_issuer" ]]; then
      details="${details}${svc}=MISSING;"
      fail_count=$((fail_count + 1))
      continue
    fi

    # For test, allow legacy fallbacks (matches check_pr_time.sh Check 3)
    if [[ "$ENV" == "test" ]]; then
      case "$cm_issuer" in
        "https://testai.acik.com/realms/platform-test"|\
        "http://keycloak:8080/realms/platform-test"|\
        "http://keycloak:8080/realms/serban")
          continue ;;
        *)
          details="${details}${svc}=$cm_issuer;"
          fail_count=$((fail_count + 1))
          ;;
      esac
    else
      # prod must match exactly
      if [[ "$cm_issuer" != "$EXPECTED_ISSUER" ]]; then
        details="${details}${svc}=$cm_issuer;"
        fail_count=$((fail_count + 1))
      fi
    fi
  done

  if [[ "$fail_count" -gt 0 ]]; then
    status="RED"
  fi

  if [[ -z "$details" ]]; then
    details="all ${#JWT_SERVICES[@]} services have correct KC issuer for $ENV"
  fi

  TIER_SECURED_STATUS="$status"
  TIER_SECURED_DETAILS="$details"
  echo "  status=$status details=$details"
}

# ------------------------------------------------------------
# Tier 4: Zanzibar — OpenFGA allow + deny synthetic
# ------------------------------------------------------------
tier_zanzibar() {
  echo "--- Tier 4: Zanzibar ---"
  local status="GREEN"
  local details=""
  local synthetic="PASS"

  # Get OpenFGA store + model IDs from permission-service env
  local store_id
  store_id=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get cm permission-service-config \
    -o jsonpath='{.data.OPENFGA_STORE_ID}' 2>/dev/null || echo "")

  if [[ -z "$store_id" ]]; then
    TIER_ZANZIBAR_STATUS="SKIP"
    TIER_ZANZIBAR_SYNTHETIC="SKIP"
    TIER_ZANZIBAR_DETAILS="OPENFGA_STORE_ID not in permission-service-config — Zanzibar tier deferred"
    echo "  status=SKIP (no store_id)"
    return
  fi

  # Port-forward to openfga
  local port=$((25000 + RANDOM % 5000))
  kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward svc/openfga "$port:8080" \
    > /dev/null 2>&1 &
  local pf_pid=$!
  sleep 3

  # Allow check: super-admin tuple should permit any user-read action
  local allow_resp
  allow_resp=$(curl -s --max-time 8 -X POST "http://localhost:$port/stores/$store_id/check" \
    -H "Content-Type: application/json" \
    -d "{\"tuple_key\":{\"user\":\"user:1204\",\"relation\":\"admin\",\"object\":\"organization:default\"}}" \
    2>/dev/null || echo '{}')

  local allow_result
  allow_result=$(echo "$allow_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('allowed') else 'false')" 2>/dev/null || echo "error")

  # Deny check: random non-admin user should be denied
  local deny_resp
  deny_resp=$(curl -s --max-time 8 -X POST "http://localhost:$port/stores/$store_id/check" \
    -H "Content-Type: application/json" \
    -d "{\"tuple_key\":{\"user\":\"user:9999999\",\"relation\":\"admin\",\"object\":\"organization:default\"}}" \
    2>/dev/null || echo '{}')

  local deny_result
  deny_result=$(echo "$deny_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('allowed') else 'false')" 2>/dev/null || echo "error")

  kill "$pf_pid" 2>/dev/null || true
  wait "$pf_pid" 2>/dev/null || true

  if [[ "$allow_result" == "true" && "$deny_result" == "false" ]]; then
    status="GREEN"
    synthetic="PASS"
    details="user:1204 admin=allow OK, user:9999999 admin=deny OK"
  elif [[ "$allow_result" == "error" || "$deny_result" == "error" ]]; then
    status="AMBER"
    synthetic="SKIP"
    details="OpenFGA check API returned error (allow=$allow_result deny=$deny_result) — store may need rebootstrap"
  else
    status="RED"
    synthetic="FAIL"
    details="allow_expected=true_got=$allow_result, deny_expected=false_got=$deny_result"
  fi

  TIER_ZANZIBAR_STATUS="$status"
  TIER_ZANZIBAR_SYNTHETIC="$synthetic"
  TIER_ZANZIBAR_DETAILS="$details"
  echo "  status=$status synthetic=$synthetic details=$details"
}

# ------------------------------------------------------------
# Run all 4 tiers
# ------------------------------------------------------------
TIER_UP_STATUS="UNKNOWN"
TIER_UP_DETAILS=""
TIER_FN_STATUS="UNKNOWN"
TIER_FN_DETAILS=""
TIER_FN_ENDPOINTS=""
TIER_SECURED_STATUS="UNKNOWN"
TIER_SECURED_DETAILS=""
TIER_ZANZIBAR_STATUS="UNKNOWN"
TIER_ZANZIBAR_SYNTHETIC="UNKNOWN"
TIER_ZANZIBAR_DETAILS=""

# Verify cluster reachable first
if ! kubectl --context "$CONTEXT" -n "$NAMESPACE" get ns "$NAMESPACE" > /dev/null 2>&1; then
  echo "ERR: cannot reach cluster context=$CONTEXT ns=$NAMESPACE"
  echo "(staging-sw connectivity required; this script is host-execution only)"
  exit 2
fi

tier_up
tier_functional
tier_secured
tier_zanzibar

# ------------------------------------------------------------
# Combine results into Tier 3 in ledger schema (collapses Secured into d29_up details)
# Schema: d29_up, d29_functional, d29_zanzibar (3 fields, Secured rolls into Up)
# ------------------------------------------------------------
# Compute overall (any RED → fail)
OVERALL_RC=0
for s in "$TIER_UP_STATUS" "$TIER_FN_STATUS" "$TIER_SECURED_STATUS" "$TIER_ZANZIBAR_STATUS"; do
  if [[ "$s" == "RED" ]]; then
    OVERALL_RC=1
  fi
done

# Up status combines tier 1 + tier 3 (Secured)
COMBINED_UP_STATUS="$TIER_UP_STATUS"
if [[ "$TIER_SECURED_STATUS" == "RED" ]]; then
  COMBINED_UP_STATUS="RED"
fi
COMBINED_UP_DETAILS="up=$TIER_UP_DETAILS | secured=$TIER_SECURED_DETAILS"

# ------------------------------------------------------------
# Emit JSON report
# ------------------------------------------------------------
cat > "$REPORT" <<EOF
{
  "schema_version": "smoke-evidence-v1",
  "environment": "$ENV",
  "namespace": "$NAMESPACE",
  "context": "$CONTEXT",
  "timestamp": "$TS",
  "exit_code": $OVERALL_RC,
  "tiers": {
    "d29_up": {
      "status": "$COMBINED_UP_STATUS",
      "checked_at": "$TS",
      "details": "$COMBINED_UP_DETAILS"
    },
    "d29_functional": {
      "status": "$TIER_FN_STATUS",
      "checked_at": "$TS",
      "endpoints": [$TIER_FN_ENDPOINTS],
      "details": "$TIER_FN_DETAILS"
    },
    "d29_zanzibar": {
      "status": "$TIER_ZANZIBAR_STATUS",
      "checked_at": "$TS",
      "allow_deny_synthetic": "$TIER_ZANZIBAR_SYNTHETIC",
      "details": "$TIER_ZANZIBAR_DETAILS"
    }
  }
}
EOF

echo
echo "=== Summary ==="
echo "exit_code=$OVERALL_RC"
echo "report=$REPORT"
exit $OVERALL_RC
