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
#   0 — all 4 tiers GREEN (eligible for ledger D29-verified promotion)
#   1 — at least 1 tier RED
#   2 — execution error (kubectl unreachable, etc.)
#   3 — incomplete: a tier SKIP/AMBER, no RED (e.g. Zanzibar store_id
#       unresolved) — NOT eligible for ledger D29-verified promotion
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

# Services validated per D29 tier — covers every backend service subject to
# prod promotion (not only JWT-decoding services), so a prod-realign PR's full
# digest set has per-service D29 evidence rather than a representative subset.
D29_SERVICES=(api-gateway user-service variant-service permission-service schema-service report-service auth-service core-data-service notification-orchestrator)

discover_optional_d29_services() {
  # endpoint-admin-service is an optional workload across environments and
  # rollout moments. Include it when the Deployment exists in the target
  # cluster instead of hardcoding it into every env and breaking smoke while
  # the service is intentionally dark.
  if kubectl --context "$CONTEXT" -n "$NAMESPACE" get deploy endpoint-admin-service >/dev/null 2>&1; then
    D29_SERVICES+=(endpoint-admin-service)
  fi
}

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

  for svc in "${D29_SERVICES[@]}"; do
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
    details="all ${#D29_SERVICES[@]} services Running+Ready"
  fi

  TIER_UP_STATUS="$status"
  TIER_UP_DETAILS="$details"
  echo "  status=$status details=$details"
}

# ------------------------------------------------------------
# Tier 2: Functional — endpoint shape (401 JWT required)
#
# probe_functional_endpoint port-forwards one service and classifies the
# outcome into a 3-state verdict (Codex 019e3a17 — Tier-2 network-path fix):
#   OK    — endpoint answered 200/401/403 (auth chain intact)
#   RED   — wiring/build broken: service exposes no "http"-named port, has no
#           ready endpoint, or the tunnel bound but the endpoint returned a
#           5xx / 000 / otherwise-unexpected status
#   AMBER — the port-forward tunnel itself never bound (local port collision,
#           transient apiserver) — inconclusive, NOT evidence the build is bad
#
# Why a named port: every JWT service exposes its HTTP port under a distinct
# number (api-gateway 8080, user-service 8089, permission-service 8090, ...)
# but all under a port named "http"; the old hard-coded "$port:80" matched no
# service, so Tier 2 was RED on every run. Why 3-state: AMBER (vs RED) lets a
# transient tunnel-setup failure roll up to exit 3 "incomplete/retry" instead
# of exit 1 "build is RED" — but once the tunnel is up, any bad answer is RED.
# ------------------------------------------------------------
probe_functional_endpoint() {
  local svc="$1" svc_ep="$2"

  # Wiring pre-check 1 — service must expose a port named "http". Caught here
  # deterministically (RED) rather than surfacing as a port-forward error.
  local http_named
  http_named=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get svc "$svc" \
    -o 'jsonpath={.spec.ports[?(@.name=="http")].name}' 2>/dev/null || echo "")
  if [[ "$http_named" != "http" ]]; then
    echo "RED|no http-named service port"
    return
  fi

  # Wiring pre-check 2 — service must have at least one READY endpoint. Tier 1
  # already checks pod Ready; an empty ready-endpoint set while Tier 1 is
  # GREEN means selector/endpoint drift — a genuine wiring RED, not transient.
  local ep_ips
  ep_ips=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get endpoints "$svc" \
    -o 'jsonpath={.subsets[*].addresses[*].ip}' 2>/dev/null || echo "")
  if [[ -z "$ep_ips" ]]; then
    echo "RED|service has no ready endpoints"
    return
  fi

  # Port-forward via the named "http" port; capture output for classification.
  local port pf_log pf_pid
  port=$((20000 + RANDOM % 10000))
  pf_log=$(mktemp "/tmp/d29-pf-${svc}-XXXXXX")
  kubectl --context "$CONTEXT" -n "$NAMESPACE" port-forward "svc/$svc" "$port:http" \
    > "$pf_log" 2>&1 &
  pf_pid=$!

  # Poll up to ~8s for the tunnel listener to bind ("Forwarding from ...").
  local tunnel="down" i
  for ((i = 0; i < 40; i++)); do
    if grep -q "Forwarding from" "$pf_log" 2>/dev/null; then
      tunnel="up"
      break
    fi
    kill -0 "$pf_pid" 2>/dev/null || break   # port-forward exited before bind
    sleep 0.2
  done

  local verdict
  if [[ "$tunnel" != "up" ]]; then
    # Tunnel never bound — mechanism failure, inconclusive (AMBER, not RED).
    if grep -qi "address already in use" "$pf_log" 2>/dev/null; then
      verdict="AMBER|local port collision - listener bind failed"
    else
      verdict="AMBER|port-forward tunnel did not establish - transient"
    fi
    echo "  [pf $svc] $(tr -d '\r\n' < "$pf_log" | tail -c 200)" >&2
  else
    # Tunnel is up — any non-(200/401/403) answer is now a genuine RED.
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' \
      --connect-timeout 5 --max-time 10 \
      "http://127.0.0.1:$port$svc_ep" 2>/dev/null || true)
    code="${code:-000}"
    case "$code" in
      200|401|403) verdict="OK|$code" ;;
      *)           verdict="RED|tunnel up, endpoint returned $code" ;;
    esac
  fi

  kill "$pf_pid" 2>/dev/null || true
  wait "$pf_pid" 2>/dev/null || true
  rm -f "$pf_log"
  echo "$verdict"
}

tier_functional() {
  echo "--- Tier 2: Functional ---"
  local details="" red_count=0 amber_count=0
  local checked_endpoints=()

  for svc in "${D29_SERVICES[@]}"; do
    local svc_ep
    case "$svc" in
      api-gateway) svc_ep="/actuator/health" ;;
      user-service) svc_ep="/api/v1/users" ;;
      variant-service) svc_ep="/api/v1/variants" ;;
      permission-service) svc_ep="/api/v1/permissions" ;;
      # schema-service Tier-2 endpoint: /api/v1/schema/schemas — JWT-gated,
      # returns 401 unauthenticated in <10ms (live-probed k3d-test 2026-05-19).
      # Was /api/v1/schema/snapshot, a wrong probe on two counts: (1) it is
      # permitAll, so an unauthenticated request gets 200 and the JWT auth
      # chain Tier 2 exists to verify is never exercised; (2) a cold-cache
      # call builds the full workcube_mikrolink snapshot (~1500 tables,
      # multi-MB) and takes >25s, exceeding curl --max-time 10 → 000 →
      # false-RED. /schemas is a light, auth-gated list endpoint — a true
      # "401 JWT shape" probe, cache-warmth independent.
      schema-service) svc_ep="/api/v1/schema/schemas" ;;
      report-service) svc_ep="/api/v1/reports" ;;
      auth-service) svc_ep="/api/v1/impersonation/sessions" ;;
      core-data-service) svc_ep="/api/v1/companies" ;;
      notification-orchestrator) svc_ep="/api/v1/notify/inbox/me" ;;
      endpoint-admin-service) svc_ep="/api/v1/admin/endpoint-devices" ;;
      *) continue ;;
    esac
    checked_endpoints+=("$svc_ep")

    local probe verdict detail
    probe=$(probe_functional_endpoint "$svc" "$svc_ep")
    verdict="${probe%%|*}"
    detail="${probe#*|}"
    case "$verdict" in
      OK)
        : # auth chain intact
        ;;
      AMBER)
        details="${details}${svc}@${svc_ep}=AMBER(${detail});"
        amber_count=$((amber_count + 1))
        ;;
      *) # RED — and any unexpected verdict, fail closed
        details="${details}${svc}@${svc_ep}=RED(${detail});"
        red_count=$((red_count + 1))
        ;;
    esac
  done

  # RED outranks AMBER: a 5xx/wiring failure is a build-RED; a pure
  # tunnel-setup failure with no RED is inconclusive (AMBER → exit 3 retry).
  local status="GREEN"
  if [[ "$red_count" -gt 0 ]]; then
    status="RED"
  elif [[ "$amber_count" -gt 0 ]]; then
    status="AMBER"
  fi

  if [[ -z "$details" ]]; then
    details="all ${#D29_SERVICES[@]} endpoints returned 200/401/403 (auth chain intact)"
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

  for svc in "${D29_SERVICES[@]}"; do
    local cm_issuer
    cm_issuer=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get cm "${svc}-config" \
      -o jsonpath='{.data.KEYCLOAK_ISSUER_URI}' 2>/dev/null || echo "")

    # Fallback: services that carry the issuer under SECURITY_JWT_ISSUER
    # (notification-orchestrator convention) rather than KEYCLOAK_ISSUER_URI.
    if [[ -z "$cm_issuer" ]]; then
      cm_issuer=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get cm "${svc}-config" \
        -o jsonpath='{.data.SECURITY_JWT_ISSUER}' 2>/dev/null || echo "")
    fi

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
    details="all ${#D29_SERVICES[@]} services have correct KC issuer for $ENV"
  fi

  TIER_SECURED_STATUS="$status"
  TIER_SECURED_DETAILS="$details"
  echo "  status=$status details=$details"
}

# ------------------------------------------------------------
# OpenFGA store_id resolver — Codex 019e39ea (PR-4A)
# Canonical key is ERP_OPENFGA_STORE_ID. The permission-service ConfigMap
# holds an empty stub; the real value is delivered by the
# permission-service-secrets Secret (ESO from Vault kv/platform/openfga) and
# wins at runtime via envFrom ordering. Resolver echoes "<store_id>|<source>"
# ("|unresolved" when not found). Chain:
#   1. D29_OPENFGA_STORE_ID env override
#   2. permission-service-secrets   ERP_OPENFGA_STORE_ID
#   3. permission-service-config    ERP_OPENFGA_STORE_ID  (stub-empty in live)
#   4. legacy OPENFGA_STORE_ID      (secret then configmap — old-deploy compat)
#   5. pod runtime env via exec — only if D29_STORE_ID_SOURCE=pod-env (opt-in;
#      kubectl exec is a broad RBAC surface, kept off the default path)
#   6. none → empty id (caller SKIPs Zanzibar, non-GREEN)
# ------------------------------------------------------------
resolve_store_id() {
  local sid="" key

  # 1. explicit env override
  if [[ -n "${D29_OPENFGA_STORE_ID:-}" ]]; then
    printf '%s|env:D29_OPENFGA_STORE_ID\n' "${D29_OPENFGA_STORE_ID}"
    return
  fi

  # 2-4. Canonical key first across BOTH sources, then legacy key — so a
  # populated canonical ConfigMap outranks a stale legacy Secret (Codex
  # 019e39ea: canonical-before-legacy contract holds across sources).
  for key in ERP_OPENFGA_STORE_ID OPENFGA_STORE_ID; do
    # Secret — the real value (ESO from Vault kv/platform/openfga)
    sid=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret permission-service-secrets \
      -o "jsonpath={.data.$key}" 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [[ -n "$sid" ]]; then
      printf '%s|secret/permission-service-secrets:%s\n' "$sid" "$key"
      return
    fi
    # ConfigMap — stub-empty in live, kept for old-deploy compat
    sid=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get cm permission-service-config \
      -o "jsonpath={.data.$key}" 2>/dev/null || echo "")
    if [[ -n "$sid" ]]; then
      printf '%s|configmap/permission-service-config:%s\n' "$sid" "$key"
      return
    fi
  done

  # 5. pod runtime env — opt-in only (kubectl exec is broad RBAC)
  if [[ "${D29_STORE_ID_SOURCE:-}" == "pod-env" ]]; then
    local pod
    pod=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pod \
      -l app.kubernetes.io/name=permission-service \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [[ -n "$pod" ]]; then
      sid=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "$pod" -- \
        printenv ERP_OPENFGA_STORE_ID 2>/dev/null || echo "")
      if [[ -n "$sid" ]]; then
        printf '%s|pod-env:%s:ERP_OPENFGA_STORE_ID\n' "$sid" "$pod"
        return
      fi
    fi
  fi

  # 6. not found
  printf '|unresolved\n'
}

# ------------------------------------------------------------
# Tier 4: Zanzibar — OpenFGA allow + deny synthetic
# ------------------------------------------------------------
tier_zanzibar() {
  echo "--- Tier 4: Zanzibar ---"
  local status="GREEN"
  local details=""
  local synthetic="PASS"

  # Resolve OpenFGA store_id (resolver chain — see resolve_store_id above)
  local store_id store_id_source resolved
  resolved=$(resolve_store_id)
  store_id="${resolved%%|*}"
  store_id_source="${resolved#*|}"

  if [[ -z "$store_id" ]]; then
    TIER_ZANZIBAR_STATUS="SKIP"
    TIER_ZANZIBAR_SYNTHETIC="SKIP"
    TIER_ZANZIBAR_DETAILS="store_id unresolved (tried D29_OPENFGA_STORE_ID env / permission-service-secrets / permission-service-config, ERP_ + legacy keys) — Zanzibar SKIP, non-GREEN; NOT eligible for ledger D29-verified"
    echo "  status=SKIP (store_id unresolved)"
    return
  fi
  echo "  store_id resolved via ${store_id_source}"

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
    details="store_id_source=${store_id_source}; user:1204 admin=allow OK, user:9999999 admin=deny OK"
  elif [[ "$allow_result" == "error" || "$deny_result" == "error" ]]; then
    status="AMBER"
    synthetic="SKIP"
    details="store_id_source=${store_id_source}; OpenFGA check API returned error (allow=$allow_result deny=$deny_result) — store may need rebootstrap"
  else
    status="RED"
    synthetic="FAIL"
    details="store_id_source=${store_id_source}; allow_expected=true_got=$allow_result, deny_expected=false_got=$deny_result"
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

discover_optional_d29_services

tier_up
tier_functional
tier_secured
tier_zanzibar

# ------------------------------------------------------------
# Combine results into Tier 3 in ledger schema (collapses Secured into d29_up details)
# Schema: d29_up, d29_functional, d29_zanzibar (3 fields, Secured rolls into Up)
# ------------------------------------------------------------
# Compute overall exit code (Codex 019e39ea — PR-4A):
#   0 — every tier GREEN (eligible for ledger D29-verified promotion)
#   1 — at least 1 tier RED
#   3 — incomplete: a tier SKIP/AMBER, no RED (e.g. Zanzibar store_id
#       unresolved). A non-GREEN tier must never be carried into the ledger
#       as D29-verified; RED (1) always outranks incomplete (3).
OVERALL_RC=0
for s in "$TIER_UP_STATUS" "$TIER_FN_STATUS" "$TIER_SECURED_STATUS" "$TIER_ZANZIBAR_STATUS"; do
  case "$s" in
    RED)   OVERALL_RC=1 ;;
    GREEN) : ;;
    *)     [[ "$OVERALL_RC" -eq 0 ]] && OVERALL_RC=3 ;;
  esac
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
