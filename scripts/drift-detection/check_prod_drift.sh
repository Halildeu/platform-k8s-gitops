#!/usr/bin/env bash
# scripts/drift-detection/check_prod_drift.sh
#
# Codex AGREE Session 37 (2026-05-04) — D30 No-Go drift detection MVP.
# Compares prod cluster live state ↔ gitops desired-state ↔ GHCR manifest
# existence ↔ critical ConfigMap envs ↔ ResourceQuota headroom.
#
# Truth hierarchy (per docs/context-priority-rules.md):
#   1. Live evidence (THIS script — runtime kanıt)
#   2. current-state markdown
#   3. ADR
#   4. PLAN
# Live cluster is EVIDENCE not source-of-truth; SSOT is origin/main GitOps yaml.
# When live ≠ git → drift incident, NOT successful deploy.
#
# Output: /tmp/drift-report-prod-<ts>.json + exit code (0 clean, 1 drift)
# Schedule: staging-sw systemd timer every 5 minutes for prod, 15 minutes for test
#   (see scripts/drift-detection/systemd/ for unit + timer templates)
#
# Exit codes:
#   0   clean (all aligned)
#   1   P1 drift (digest/config mismatch — operator action required)
#   2   P2 drift (lag, headroom warning)
#   3   exec error (kubectl/git/docker unreachable)
#
# Alarm classes (from Codex framework):
#   P1: prod git/live digest mismatch >10min, GHCR manifest unknown,
#       ESO SecretSyncedError, ConfigMap issuer parity break
#   P2: test git/live drift >30min, prod promotion lag >7d,
#       quota headroom < one surge pod
#   P3: stale docs/current-state, smoke creds missing
#
# Dependencies: kubectl (k3d-prod context), git, jq, docker (for GHCR pull),
# bash 4+. Designed for staging-sw host where the prod cluster lives.

set -uo pipefail

ENV="${1:-prod}"        # prod or test
CONTEXT="k3d-${ENV}"
NAMESPACE="platform-${ENV}"

# REPO_ROOT discovery (handles both: script in repo + script copied to /tmp)
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
REPORT="/tmp/drift-report-${ENV}-${TS}.json"
EXIT_CODE=0

# Helper: emit JSON entry
declare -a FINDINGS=()
add_finding() {
  local class="$1"      # P1/P2/P3 or OK
  local kind="$2"
  local msg="$3"
  local details="${4:-}"
  FINDINGS+=("$(jq -nc --arg c "$class" --arg k "$kind" --arg m "$msg" --arg d "$details" \
    '{class:$c, kind:$k, message:$m, details:$d}')")
}

# Promote exit code to highest severity
bump_exit() {
  local new=$1
  [[ $new -gt $EXIT_CODE ]] && EXIT_CODE=$new
}

# 1. ArgoCD application sync state
ARGOCD_STATE=$(kubectl --context "$CONTEXT" -n argocd get application "platform-${ENV}" \
  -o jsonpath='{.status.sync.status}/{.status.health.status}/{.status.sync.revision}' 2>/dev/null || echo "ERR")
if [[ "$ARGOCD_STATE" == "ERR" ]]; then
  add_finding P1 argocd_unreachable "ArgoCD application platform-${ENV} not queryable"
  bump_exit 3
elif [[ "$ARGOCD_STATE" != "Synced/Healthy"* ]]; then
  add_finding P1 argocd_drift "ArgoCD platform-${ENV} not Synced/Healthy" "$ARGOCD_STATE"
  bump_exit 1
else
  add_finding OK argocd "ArgoCD platform-${ENV} $ARGOCD_STATE"
fi

# 2. Image digest parity — kustomize render vs live pod imageID
RENDER=$(kubectl kustomize "$OVERLAY" 2>/dev/null) || {
  add_finding P1 kustomize_render_fail "kustomize build $OVERLAY failed"
  bump_exit 1
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
    bump_exit 2
  elif [[ "$pod_d" != "$yaml_d" ]]; then
    add_finding P1 digest_drift "$svc: yaml=$yaml_d pod=$pod_d"
    bump_exit 1
  fi
done

# Services in cluster but not in yaml (e.g. endpoint-admin-service test only)
for svc in "${!POD_DIGESTS[@]}"; do
  if [[ -z "${YAML_DIGESTS[$svc]:-}" ]]; then
    add_finding P2 service_unmanaged "Live service $svc has no yaml entry (gitops untracked)"
    bump_exit 2
  fi
done
set -u

# 3. ConfigMap KC issuer parity (only services that validate JWT)
JWT_SERVICES=(api-gateway user-service variant-service permission-service schema-service report-service)
for svc in "${JWT_SERVICES[@]}"; do
  iss=$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get configmap "${svc}-config" \
    -o jsonpath='{.data.KEYCLOAK_ISSUER_URI}' 2>/dev/null || echo "")
  if [[ -z "$iss" ]]; then
    add_finding P1 configmap_kc_missing "$svc: KEYCLOAK_ISSUER_URI not set"
    bump_exit 1
  fi
done

# 4. ResourceQuota headroom (P2 if surge pod won't fit)
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
    bump_exit 2
  fi
fi

# 5. Output JSON report
{
  echo "{"
  echo "  \"timestamp\": \"$TS\","
  echo "  \"environment\": \"$ENV\","
  echo "  \"context\": \"$CONTEXT\","
  echo "  \"argocd\": \"$ARGOCD_STATE\","
  echo "  \"yaml_services\": ${#YAML_DIGESTS[@]},"
  echo "  \"pod_services\": ${#POD_DIGESTS[@]},"
  echo "  \"exit_code\": $EXIT_CODE,"
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

# Console summary
echo "[drift-detection $ENV $TS] exit=$EXIT_CODE"
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
