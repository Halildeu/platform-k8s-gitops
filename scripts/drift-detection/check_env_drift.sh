#!/usr/bin/env bash
# scripts/drift-detection/check_env_drift.sh
#
# ADR-0023 Guardrail PR-4 (renamed from check_prod_drift.sh on 2026-05-20).
# Codex AGREE chain:
#   - Session 37 (2026-05-04) — D30 No-Go drift detection MVP (original).
#   - Session 50 (2026-05-20) — PR-4 plan iter-2 AGREE 019e44b9 (env ArgoCD
#     hub split + 5-state machine + exit-code precedence fix + self-hosted
#     runtime workflow).
#
# Compares cluster live state ↔ gitops desired-state ↔ GHCR manifest
# existence ↔ critical ConfigMap envs ↔ ResourceQuota headroom ↔ deployment
# template/probe contract for BOTH test+prod overlays. Single script,
# ENV={test,prod} argument.
#
# Truth hierarchy (per docs/context-priority-rules.md):
#   1. Live evidence (THIS script — runtime kanıt)
#   2. current-state markdown
#   3. ADR
#   4. PLAN
# Live cluster is EVIDENCE not source-of-truth; SSOT is origin/main GitOps yaml.
# When live ≠ git → drift incident, NOT successful deploy.
#
# Usage:
#   check_env_drift.sh [prod|test] [--report-path PATH]
#
# Output: ${REPORT_PATH override:-/tmp/drift-report-<env>-<ts>.json}.
#
# Schedule (post-PR-4):
#   .github/workflows/gate-env-drift.yml — daily 06:15 UTC + workflow_dispatch
#   on self-hosted staging-sw runner. Legacy systemd timer (5min prod / 15min
#   test) kept for redundancy.
#
# Exit code precedence (high → low):
#   3   exec error (kubectl/git unreachable)
#   1   P1 drift (digest/config mismatch — operator action required)
#   2   P2 drift (app missing, lag, headroom warning)
#   0   clean
# Note: P3 findings are informational only and DO NOT bump exit code; they
# emit ::notice:: lines for run-log visibility.
#
# Alarm classes:
#   P1: prod git/live digest mismatch, GHCR manifest unknown,
#       ESO SecretSyncedError, ConfigMap issuer parity break,
#       prod ArgoCD Application missing (control plane gap),
#       prod ArgoCD sync drift / health degraded
#   P2: test git/live drift, prod promotion lag >7d, quota headroom
#       < one surge pod, test ArgoCD Application missing (root reconcile gap),
#       ArgoCD condition unknown/unclassified
#   P3: test ArgoCD destination not registered yet (cluster-add pending),
#       stale docs/current-state, smoke creds missing
#
# Contexts (Codex 019e44b9 iter-1 must_fix #1):
#   - Live workload context: k3d-${ENV} (test or prod cluster)
#   - ArgoCD hub context:    ${ARGOCD_CONTEXT:-k3d-prod} (single hub manages
#                            BOTH platform-prod + platform-test Applications)
#   - ArgoCD namespace:      ${ARGOCD_NAMESPACE:-argocd}
#
# Dependencies: kubectl, git, jq, bash 4+. Designed for staging-sw host where
# both clusters are reachable.

set -uo pipefail

# ---- Argument parsing -------------------------------------------------------
ENV=""
REPORT_PATH_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --report-path)
      REPORT_PATH_OVERRIDE="${2:-}"
      shift 2
      ;;
    --report-path=*)
      REPORT_PATH_OVERRIDE="${1#*=}"
      shift
      ;;
    prod|test)
      ENV="$1"
      shift
      ;;
    -h|--help)
      sed -n '2,60p' "$0"
      exit 0
      ;;
    *)
      echo "ERR: unknown arg: $1" >&2
      echo "Usage: $0 [prod|test] [--report-path PATH]" >&2
      exit 3
      ;;
  esac
done
ENV="${ENV:-prod}"
CONTEXT="k3d-${ENV}"
NAMESPACE="platform-${ENV}"

# ArgoCD hub context — single ArgoCD hub on k3d-prod manages BOTH
# platform-prod + platform-test Applications (Codex 019e44b9 iter-1 must_fix #1).
ARGOCD_CONTEXT="${ARGOCD_CONTEXT:-k3d-prod}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"

# ---- REPO_ROOT discovery ----------------------------------------------------
# Priority:
#   1. PLATFORM_GITOPS_REPO env var (systemd unit + CI explicit)
#   2. ../.. relative to script (when invoked from repo)
#   3. /home/halil/platform/platform-k8s-gitops fallback (staging-sw default)
REPO_ROOT="${PLATFORM_GITOPS_REPO:-}"
if [[ -z "$REPO_ROOT" ]]; then
  candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)"
  if [[ -d "$candidate/kustomize/overlays/${ENV}" ]]; then
    REPO_ROOT="$candidate"
  elif [[ -d "/home/halil/platform/platform-k8s-gitops/kustomize/overlays/${ENV}" ]]; then
    REPO_ROOT="/home/halil/platform/platform-k8s-gitops"
  fi
fi
[[ -z "$REPO_ROOT" || ! -d "$REPO_ROOT/kustomize/overlays/${ENV}" ]] && {
  echo "ERR: cannot find gitops repo (set PLATFORM_GITOPS_REPO or run from repo)"
  exit 3
}
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
cd "$REPO_ROOT" || exit 3

TS=$(date -u +%Y%m%dT%H%M%SZ)
REPORT="${REPORT_PATH_OVERRIDE:-/tmp/drift-report-${ENV}-${TS}.json}"

# ---- Exit precedence flags --------------------------------------------------
# Replaces numeric-max bump_exit() (Codex 019e44b9 iter-1 must_fix #3):
# previously a later P2 finding could overwrite a prior P1 (2 > 1). Now we
# track independent flags and compute final EXIT_CODE deterministically.
HAS_EXEC_ERROR=0
HAS_P1=0
HAS_P2=0
mark_exec_error() { HAS_EXEC_ERROR=1; }
mark_p1()         { HAS_P1=1; }
mark_p2()         { HAS_P2=1; }

# ---- Finding helpers --------------------------------------------------------
declare -a FINDINGS=()
add_finding() {
  local class="$1"      # P1/P2/P3 or OK
  local kind="$2"
  local msg="$3"
  local details="${4:-}"
  FINDINGS+=("$(jq -nc --arg c "$class" --arg k "$kind" --arg m "$msg" --arg d "$details" \
    '{class:$c, kind:$k, message:$m, details:$d}')")
  if [[ "$class" == "P3" ]]; then
    # GitHub Actions surfaces ::notice:: in the run summary; harmless in
    # non-Actions contexts (Codex 019e44b9 iter-2 should_fix #2).
    echo "::notice title=drift-${ENV} P3 ${kind}::${msg}"
  fi
}

# Legacy bump_exit shim — kept so any commit that forgets the new flags still
# compiles. Maps to the new mark_*() flags.
# shellcheck disable=SC2329  # intentionally unused; backward-compat shim
bump_exit() {
  case "${1:-}" in
    3) mark_exec_error ;;
    1) mark_p1 ;;
    2) mark_p2 ;;
  esac
}

# ---- 1. ArgoCD Application sync state (5-state machine, post-PR-2) ----------
# Both platform-prod and platform-test Applications live in the single ArgoCD
# hub on k3d-prod. We query the hub (ARGOCD_CONTEXT) for the Application named
# platform-${ENV}.
#
# State A — Application missing (env-bazlı severity, Codex iter-2 must_fix #2):
#   ENV=prod → P1 argocd_app_missing (control plane gap)
#   ENV=test → P2 argocd_app_missing (root reconcile gap after PR-2)
# State B — Application exists, destination not registered (operator cluster-add
#   pending; condition/message match): P3 argocd_destination_pending.
# State C — Application exists, Synced/Healthy: OK.
# State D — Application exists, sync ≠ Synced OR health ≠ Healthy (not B): P1.
# State E — Application exists, unknown/unclassified condition: P2.
APP_JSON=$(kubectl --context "$ARGOCD_CONTEXT" -n "$ARGOCD_NAMESPACE" \
  get application "platform-${ENV}" -o json 2>/dev/null || echo "")
ARGOCD_STATE="ERR"
ARGOCD_CONDITION_BLOB="[]"
if [[ -n "$APP_JSON" ]] && echo "$APP_JSON" | jq -e '.status' >/dev/null 2>&1; then
  ARGOCD_STATE=$(echo "$APP_JSON" | jq -r \
    '"\(.status.sync.status // "Unknown")/\(.status.health.status // "Unknown")/\(.status.sync.revision // "")"')
  ARGOCD_CONDITION_BLOB=$(echo "$APP_JSON" | jq -c '.status.conditions // []')
fi

if [[ "$ARGOCD_STATE" == "ERR" ]]; then
  # State A — Application missing or hub unreachable
  if [[ "$ENV" == "prod" ]]; then
    add_finding P1 argocd_app_missing \
      "platform-prod Application missing from ${ARGOCD_CONTEXT}/${ARGOCD_NAMESPACE} hub — control plane gap (root.yaml reconcile or manifest deletion)"
    mark_p1
  else
    add_finding P2 argocd_app_missing \
      "platform-${ENV} Application missing from ${ARGOCD_CONTEXT}/${ARGOCD_NAMESPACE} hub — root reconcile gap (PR-2 manifest should be active)"
    mark_p2
  fi
else
  # Application exists. Detect State B (destination unregistered) via
  # status.conditions[].message OR status.operationState.message.
  IS_DEST_PENDING=0
  if [[ "$ARGOCD_CONDITION_BLOB" != "[]" ]]; then
    DEST_MATCH=$(echo "$ARGOCD_CONDITION_BLOB" | jq -r '
      [.[].message // ""]
      | map(select(test("cluster.*not.*registered|cluster.*secret.*missing|unknown.*cluster|destination.*not.*found"; "i")))
      | length' 2>/dev/null || echo "0")
    [[ "${DEST_MATCH:-0}" -gt 0 ]] && IS_DEST_PENDING=1
  fi
  if [[ "$IS_DEST_PENDING" -eq 0 ]]; then
    OPSTATE_MSG=$(echo "$APP_JSON" | jq -r '.status.operationState.message // ""' 2>/dev/null || echo "")
    if echo "$OPSTATE_MSG" | grep -qiE "cluster.*not.*registered|cluster.*secret.*missing|unknown.*cluster|destination.*not.*found"; then
      IS_DEST_PENDING=1
    fi
  fi

  if [[ "$IS_DEST_PENDING" -eq 1 && "$ENV" != "prod" ]]; then
    # State B — destination unregistered (test only; prod cluster always registered)
    add_finding P3 argocd_destination_pending \
      "platform-${ENV} Application destination not registered yet — operator action: 'argocd cluster add k3d-test --name test-cluster --upsert --yes' (RB-argocd-register-test-cluster.md)" \
      "$ARGOCD_CONDITION_BLOB"
    # P3: no exit bump
  elif [[ "$ARGOCD_STATE" == "Synced/Healthy"* ]]; then
    # State C — happy path
    add_finding OK argocd "ArgoCD platform-${ENV} $ARGOCD_STATE"
  elif echo "$ARGOCD_STATE" | grep -qE "^(Synced|OutOfSync)/(Healthy|Degraded|Progressing|Suspended|Missing)/"; then
    # State D — known sync/health enum but drifted (not Synced/Healthy)
    add_finding P1 argocd_drift "ArgoCD platform-${ENV} not Synced/Healthy" "$ARGOCD_STATE"
    mark_p1
  else
    # State E — unknown/unclassified state string
    add_finding P2 argocd_state_unknown \
      "ArgoCD platform-${ENV} unclassified state '$ARGOCD_STATE' — manual triage" \
      "$ARGOCD_CONDITION_BLOB"
    mark_p2
  fi
fi

# ---- 2. Image digest parity — kustomize render vs live pod imageID ---------
RENDER=$(kubectl kustomize "$OVERLAY" 2>/dev/null) || {
  add_finding P1 kustomize_render_fail "kustomize build $OVERLAY failed"
  mark_p1
}

declare -A YAML_DIGESTS
while IFS=$'\t' read -r svc digest; do
  [[ -n "$svc" && -n "$digest" ]] && YAML_DIGESTS["$svc"]="$digest"
done < <(echo "$RENDER" | awk '
  /name: (auth-service|api-gateway|user-service|variant-service|core-data-service|report-service|schema-service|permission-service|frontend|endpoint-admin-service|openfga|workcube-mssql-bridge)$/ {
    svc=$2
    next
  }
  /image:.*@sha256:/ {
    n=split($2, p, "@")
    if (n==2 && svc!="") {
      img_path=p[1]
      digest=p[2]
      # match by image short name suffix
      n2=split(img_path, q, "/")
      img_short=q[n2]
      sub(/^platform-(backend|web)-/, "", img_short)
      sub(/-testai$/, "", img_short)
      printf "%s\t%s\n", img_short, digest
    }
    svc=""
  }
')

# Live pod imageIDs
declare -A POD_DIGESTS
while IFS=$'\t' read -r svc imgid; do
  if [[ -n "$svc" && -n "$imgid" ]]; then
    digest=${imgid##*@}
    POD_DIGESTS["$svc"]="$digest"
  fi
done < <(kubectl --context "$CONTEXT" -n "$NAMESPACE" get pods \
  -o jsonpath='{range .items[*]}{.metadata.labels.app\.kubernetes\.io/name}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}' 2>/dev/null \
  | sort -u | grep -v '^$')

# Compare — toggle +u for array iteration (empty assoc array safe)
set +u
for svc in "${!YAML_DIGESTS[@]}"; do
  yaml_d="${YAML_DIGESTS[$svc]}"
  pod_d="${POD_DIGESTS[$svc]:-MISSING}"
  if [[ "$pod_d" == "MISSING" ]]; then
    add_finding P2 service_missing "Service $svc in yaml but no live pods"
    mark_p2
  elif [[ "$pod_d" != "$yaml_d" ]]; then
    add_finding P1 digest_drift "$svc: yaml=$yaml_d pod=$pod_d"
    mark_p1
  fi
done

# Services in cluster but not in yaml (e.g. endpoint-admin-service test only)
for svc in "${!POD_DIGESTS[@]}"; do
  if [[ -z "${YAML_DIGESTS[$svc]:-}" ]]; then
    add_finding P2 service_unmanaged "Live service $svc has no yaml entry (gitops untracked)"
    mark_p2
  fi
done
set -u

# ---- 3. ConfigMap KC issuer parity (services that validate JWT) -------------
JWT_SERVICES=(api-gateway user-service variant-service permission-service schema-service report-service)
for svc in "${JWT_SERVICES[@]}"; do
  iss=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get configmap "${svc}-config" \
    -o jsonpath='{.data.KEYCLOAK_ISSUER_URI}' 2>/dev/null || echo "")
  if [[ -z "$iss" ]]; then
    add_finding P1 configmap_kc_missing "$svc: KEYCLOAK_ISSUER_URI not set"
    mark_p1
  fi
done

# ---- 4. ResourceQuota headroom (P2 if surge pod won't fit) ------------------
QUOTA_RAW=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get resourcequota platform-quota \
  -o jsonpath='{.status.used.limits\.cpu}/{.status.hard.limits\.cpu}' 2>/dev/null || echo "")
if [[ -n "$QUOTA_RAW" ]]; then
  used_cpu=$(echo "$QUOTA_RAW" | cut -d/ -f1 | sed 's/m$//')
  hard_cpu=$(echo "$QUOTA_RAW" | cut -d/ -f2)
  # Convert hard to millicores if no unit
  [[ "$hard_cpu" =~ ^[0-9]+$ ]] && hard_cpu=$((hard_cpu * 1000))
  hard_cpu=${hard_cpu%m}
  margin=$((hard_cpu - used_cpu))
  pct=$((used_cpu * 100 / hard_cpu))
  if [[ $margin -lt 1000 ]]; then
    add_finding P2 quota_headroom_tight "limits.cpu used=${used_cpu}m hard=${hard_cpu}m (${pct}%) — surge pod may not fit"
    mark_p2
  fi
fi

# ---- 5. Deployment template + probe contract drift (Codex 019e2319 AGREE) ---
# Single Python CLI captures both semantic template diff + RS-split detection.
# Catches the endpoint-admin /healthz/* probe drift that produced a 16h silent
# CrashLoopBackOff on 2026-05-13 (apply-gap class drift).
CONTRACT_CLI="$REPO_ROOT/scripts/drift_detection/check_deployment_contracts.py"
if [[ -x "$CONTRACT_CLI" ]]; then
  CONTRACT_JSON=$(python3 "$CONTRACT_CLI" \
    --mode runtime \
    --env "$ENV" \
    --render-source "$OVERLAY" \
    --live-context "$CONTEXT" \
    --live-namespace "$NAMESPACE" \
    --catalog "$REPO_ROOT/docs/operations/services.yaml" \
    --output json 2>/dev/null)
  contract_rc=$?
  # Codex 019e2327 review #1 — fail-closed semantics. Exec error (rc=3) emits
  # a P1 finding; we do NOT silently treat it as "no drift".
  if [[ $contract_rc -eq 3 ]]; then
    add_finding P1 contract_gate_exec_error "check_deployment_contracts CLI exec failure (kubectl/render unreachable)" "rc=$contract_rc"
    mark_exec_error
  elif [[ -n "$CONTRACT_JSON" ]]; then
    # Merge contract findings into the existing FINDINGS array.
    while IFS= read -r entry; do
      [[ -z "$entry" ]] && continue
      FINDINGS+=("$entry")
      cls=$(echo "$entry" | jq -r '.class')
      case "$cls" in
        P1) mark_p1 ;;
        P2) mark_p2 ;;
      esac
    done < <(echo "$CONTRACT_JSON" | jq -c '.findings[]?' 2>/dev/null)
  fi
else
  add_finding P1 contract_gate_missing "check_deployment_contracts CLI not executable — gate cannot run"
  mark_p1
fi

# ---- 6. Compute final exit code (deterministic precedence) ------------------
EXIT_CODE=0
EXIT_CLASS="clean"
if [[ $HAS_EXEC_ERROR -eq 1 ]]; then
  EXIT_CODE=3
  EXIT_CLASS="exec-error"
elif [[ $HAS_P1 -eq 1 ]]; then
  EXIT_CODE=1
  EXIT_CLASS="P1"
elif [[ $HAS_P2 -eq 1 ]]; then
  EXIT_CODE=2
  EXIT_CLASS="P2"
fi

# ---- 7. Output JSON report --------------------------------------------------
{
  echo "{"
  echo "  \"timestamp\": \"$TS\","
  echo "  \"mode\": \"runtime\","
  echo "  \"environment\": \"$ENV\","
  echo "  \"live_context\": \"$CONTEXT\","
  echo "  \"argocd_context\": \"$ARGOCD_CONTEXT\","
  echo "  \"argocd_app_context\": \"$ARGOCD_CONTEXT/$ARGOCD_NAMESPACE\","
  echo "  \"argocd\": \"$ARGOCD_STATE\","
  echo "  \"yaml_services\": ${#YAML_DIGESTS[@]},"
  echo "  \"pod_services\": ${#POD_DIGESTS[@]},"
  echo "  \"exit_code\": $EXIT_CODE,"
  echo "  \"exit_class\": \"$EXIT_CLASS\","
  echo "  \"findings\": ["
  if [[ ${#FINDINGS[@]} -gt 0 ]]; then
    printf '    %s' "${FINDINGS[0]}"
    for ((i=1; i<${#FINDINGS[@]}; i++)); do
      printf ',\n    %s' "${FINDINGS[$i]}"
    done
    echo
  fi
  echo "  ]"
  echo "}"
} > "$REPORT"

# ---- 8. Console summary -----------------------------------------------------
echo "[drift-detection $ENV $TS] exit=$EXIT_CODE class=$EXIT_CLASS"
echo "  yaml services: ${#YAML_DIGESTS[@]}"
echo "  pod services:  ${#POD_DIGESTS[@]}"
echo "  findings:      ${#FINDINGS[@]}"
echo "  report:        $REPORT"
if [[ ${#FINDINGS[@]} -gt 0 ]]; then
  echo "  ---"
  for f in "${FINDINGS[@]}"; do
    cls=$(echo "$f" | jq -r '.class')
    knd=$(echo "$f" | jq -r '.kind')
    msg=$(echo "$f" | jq -r '.message')
    [[ "$cls" != "OK" ]] && echo "  [$cls] $knd: $msg"
  done
fi

exit $EXIT_CODE
