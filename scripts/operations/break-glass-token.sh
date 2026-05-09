#!/usr/bin/env bash
# scripts/operations/break-glass-token.sh
#
# Codex Sprint C pre-cutover RBAC — issue audited TTL token for the
# ops-break-glass ServiceAccount.
#
# Usage:
#   bash break-glass-token.sh "<reason>"
#   bash break-glass-token.sh "fixing schema-service ImagePullBackOff for D30 cutover"
#
# Effect:
#   1. Validate reason (mandatory; cannot be empty)
#   2. kubectl create token ops-break-glass --duration=1h
#   3. Write audit log entry to /var/log/break-glass-audit.log (append-only)
#   4. Open GitHub issue for governance trail (auto-deduplicated by reason)
#   5. Output kubeconfig with the TTL token + reminder banner
#
# Reconciliation:
#   Operator MUST open a reconciliation PR within 30min of any state change.
#   Template: .github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md
#
# Audit log location:
#   /var/log/break-glass-audit.log (root:root 644)
#   First-run creates with sudo; subsequent runs append (operator group write OK)
#
# Exit:
#   0 — token issued + audit logged
#   1 — argument validation failed
#   2 — token issuance failed (kubectl error, missing SA)

set -uo pipefail

REASON="${1:-}"
NS="${BREAK_GLASS_NS:-kube-system}"
SA="${BREAK_GLASS_SA:-ops-break-glass}"
DURATION="${BREAK_GLASS_DURATION:-1h}"
AUDIT_LOG="${BREAK_GLASS_AUDIT_LOG:-/var/log/break-glass-audit.log}"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
KUBECONFIG_OUT="/tmp/kubeconfig-break-glass-$$"

# Faz 23.2.D T1.4 PR-3 — D43 Outage Fallback Bypass (Codex 019e0dea iter-2 + iter-3 absorb).
#
# Dual-channel break-glass audit:
#   Primary path: GitHub Issues + local audit log (mevcut, governance trail)
#   Fallback path: Alertmanager direct webhook (orchestrator down VEYA gh fail)
#
# Codex iter-2 absorb:
#   - Token kesinlikle log/PR/message'a YAZILMAZ (no-token-log HARD RULE)
#   - Sadece BreakGlassUsed event'i fallback'e gider (rare event, audit anlamlı)
#   - "Tüm critical audit fallback" YASAK (outage gürültü + classification riski)
#   - Recovery sonrası OUTAGE_FALLBACK_USED audit best-effort post-recovery
#     (bash script'i hayatta tutmaz; ayrı cleanup runbook adımı PR-4'te belge)
#
# Codex iter-3 absorb (PR-2 uyumlu):
#   - severity=critical (Alertmanager routing convention; drift_class N/A burda)
#   - Stable dedupe_key (sha256(env+SA+ctx+title) — token DEĞİL)
#   - sha256sum primary, shasum fallback
#   - Cluster-internal URL only (public exposure açılmaz)
#
# Healthcheck guard: orchestrator reachable mi?
#   curl -sf --max-time 5 $NOTIFY_ORCH_HEALTH_URL
#   → fail (5xx/timeout/connection refused): outage detected → Alertmanager fallback
#   → 200 OK: orchestrator up; sadece audit publish (gelecek backend PR'a kalır)
NOTIFY_ORCH_HEALTH_URL="${NOTIFY_ORCH_HEALTH_URL:-http://notification-orchestrator.platform-test.svc.cluster.local:8089/actuator/health}"
ALERTMANAGER_FALLBACK_URL="${ALERTMANAGER_FALLBACK_URL:-http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts}"
ALARM_FALLBACK_ALERTMANAGER="${ALARM_FALLBACK_ALERTMANAGER:-0}"
BREAK_GLASS_FALLBACK_TIMEOUT="${BREAK_GLASS_FALLBACK_TIMEOUT:-5}"
MAX_RETRIES="${MAX_RETRIES:-3}"

# ------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------

if [[ -z "$REASON" ]]; then
  cat <<EOF
ERR: reason required.

Usage:
  bash break-glass-token.sh "<reason>"

Examples:
  break-glass-token.sh "schema-service ImagePullBackOff fix during cutover"
  break-glass-token.sh "ConfigMap KEYCLOAK_ISSUER_URI rotation prod"
  break-glass-token.sh "Calico typha cache recovery"

Reason becomes part of audit log + GitHub issue title.
EOF
  exit 1
fi

if [[ ${#REASON} -lt 15 ]]; then
  echo "ERR: reason must be at least 15 characters (current: ${#REASON})"
  echo "     Provide enough context for audit reviewer to understand intent."
  exit 1
fi

if ! command -v kubectl > /dev/null 2>&1; then
  echo "ERR: kubectl not in PATH"
  exit 2
fi

if ! kubectl -n "$NS" get sa "$SA" > /dev/null 2>&1; then
  echo "ERR: ServiceAccount $NS/$SA not found"
  echo "     Apply break-glass SA first:"
  echo "       kubectl apply -k kustomize/base/rbac/"
  exit 2
fi

# ------------------------------------------------------------
# Issue token
# ------------------------------------------------------------

echo "=== Break-glass token issuance ==="
echo "namespace: $NS"
echo "sa:        $SA"
echo "duration:  $DURATION"
echo "reason:    $REASON"
echo

# Create token (k8s 1.24+ projected token API)
TOKEN=$(kubectl create token "$SA" -n "$NS" --duration="$DURATION" 2>/tmp/token-err)
if [[ -z "$TOKEN" ]]; then
  echo "ERR: token issuance failed:"
  cat /tmp/token-err
  exit 2
fi

# Get cluster API server URL from current kubeconfig
CURRENT_CTX=$(kubectl config current-context)
CLUSTER=$(kubectl config view -o jsonpath="{.contexts[?(@.name == \"$CURRENT_CTX\")].context.cluster}")
SERVER=$(kubectl config view -o jsonpath="{.clusters[?(@.name == \"$CLUSTER\")].cluster.server}")
CA_DATA=$(kubectl config view --raw -o jsonpath="{.clusters[?(@.name == \"$CLUSTER\")].cluster.certificate-authority-data}")

# Write minimal kubeconfig with the TTL token
cat > "$KUBECONFIG_OUT" <<EOF
apiVersion: v1
kind: Config
current-context: break-glass-${CURRENT_CTX}
contexts:
- name: break-glass-${CURRENT_CTX}
  context:
    cluster: ${CLUSTER}
    user: break-glass-${SA}
    namespace: default
clusters:
- name: ${CLUSTER}
  cluster:
    server: ${SERVER}
    certificate-authority-data: ${CA_DATA}
users:
- name: break-glass-${SA}
  user:
    token: ${TOKEN}
EOF
chmod 600 "$KUBECONFIG_OUT"

# ------------------------------------------------------------
# Audit log
# ------------------------------------------------------------

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
USER_ID="${USER:-unknown}"
HOST_ID=$(hostname)

# Append to audit log (best-effort; if log dir not writable, fall back to /tmp)
LOG_LINE="$NOW | break-glass-issued | sa=$SA | ns=$NS | duration=$DURATION | requested-by=$USER_ID@$HOST_ID | context=$CURRENT_CTX | reason=$REASON"

if [[ -w "$(dirname "$AUDIT_LOG")" ]] || sudo -n true 2>/dev/null; then
  if [[ -w "$(dirname "$AUDIT_LOG")" ]]; then
    echo "$LOG_LINE" >> "$AUDIT_LOG"
  else
    echo "$LOG_LINE" | sudo tee -a "$AUDIT_LOG" > /dev/null
  fi
  echo "[audit] logged to $AUDIT_LOG"
else
  AUDIT_LOG_FALLBACK="/tmp/break-glass-audit.log"
  echo "$LOG_LINE" >> "$AUDIT_LOG_FALLBACK"
  echo "[audit] /var/log not writable — logged to fallback: $AUDIT_LOG_FALLBACK"
  echo "[audit] Operator: append this line to /var/log/break-glass-audit.log post-incident"
fi

# ------------------------------------------------------------
# GitHub issue (governance trail)
# ------------------------------------------------------------

if command -v gh > /dev/null 2>&1 && gh auth status > /dev/null 2>&1; then
  ISSUE_TITLE="[break-glass] $CURRENT_CTX: $(echo "$REASON" | head -c 60)"
  ISSUE_BODY=$(cat <<EOM
**Break-glass token issued**

- **Time**: \`$NOW\`
- **Operator**: \`$USER_ID@$HOST_ID\`
- **Cluster context**: \`$CURRENT_CTX\`
- **ServiceAccount**: \`$NS/$SA\`
- **Token TTL**: \`$DURATION\`
- **Reason**: \`$REASON\`

## Reconciliation requirement

Operator MUST open a reconciliation PR within **30 minutes** of any state mutation.

Template: \`.github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md\`

Tag this issue in the PR description.

## Audit log

\`\`\`
$LOG_LINE
\`\`\`

---

🤖 Auto-opened by scripts/operations/break-glass-token.sh (Codex Sprint C)
EOM
)
  if gh issue create --repo "$GH_REPO" \
    --title "$ISSUE_TITLE" \
    --label "ops-audit,break-glass" \
    --body "$ISSUE_BODY" 2>&1 | tail -1; then
    echo "[audit] GitHub issue opened"
  else
    echo "[WARN] GitHub issue creation failed; audit log + reconciliation PR are still required"
  fi
else
  echo "[WARN] gh CLI unavailable or not authenticated — GitHub audit trail SKIPPED"
  echo "       Operator: open issue manually in $GH_REPO with label 'ops-audit,break-glass'"
fi

# ------------------------------------------------------------
# Faz 23.2.D T1.4 PR-3 — D43 Alertmanager direct fallback (dual-channel)
#
# Codex 019e0dea iter-2 + iter-3 absorb: orchestrator down VEYA gh fail
# durumunda BreakGlassUsed event Alertmanager `/api/v2/alerts`'e direct gönderilir.
# Token KESİNLİKLE payload'a girmez (no-token-log HARD RULE).
# ------------------------------------------------------------

orchestrator_reachable() {
  # Healthcheck: 200 OK = up; 5xx/timeout/connection refused = down
  local code
  code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time "$BREAK_GLASS_FALLBACK_TIMEOUT" \
    "$NOTIFY_ORCH_HEALTH_URL" 2>/dev/null || echo "000")

  case "$code" in
    2*) return 0 ;;  # up
    *)  return 1 ;;  # down (4xx auth, 5xx, timeout, connection refused, DNS fail)
  esac
}

deliver_alertmanager_breakglass() {
  # Trigger gate: explicit toggle gerek (Codex iter-2 dar scope)
  if [[ "$ALARM_FALLBACK_ALERTMANAGER" != "1" ]]; then
    return 1
  fi

  local sig_input
  # Dedupe input: env+SA+ctx+title (TOKEN YOK — no-token-log HARD RULE)
  sig_input=$(printf '%s|%s|%s|%s' "$NS" "$SA" "$CURRENT_CTX" "${REASON:0:60}")

  # sha256 portability (Codex iter-3 #3): sha256sum primary, shasum fallback
  local sig
  if command -v sha256sum > /dev/null 2>&1; then
    sig=$(printf '%s' "$sig_input" | sha256sum | awk '{print $1}')
  elif command -v shasum > /dev/null 2>&1; then
    sig=$(printf '%s' "$sig_input" | shasum -a 256 | awk '{print $1}')
  else
    echo "  [alertmanager-fallback] ERROR: no sha256 implementation — cannot compute dedupe_key" >&2
    return 1
  fi

  # Compose Alertmanager v2 alerts payload — TOKEN ABSOLUTELY EXCLUDED
  local payload
  payload=$(jq -nc \
    --arg alertname "BreakGlassUsed" \
    --arg cluster "$CURRENT_CTX" \
    --arg severity "critical" \
    --arg sa "$SA" \
    --arg ns "$NS" \
    --arg duration "$DURATION" \
    --arg operator "$USER_ID@$HOST_ID" \
    --arg reason "$REASON" \
    --arg sig "$sig" \
    --arg ts "${NOW%Z}.000Z" \
    '[{
      labels: {
        alertname: $alertname,
        cluster: $cluster,
        severity: $severity,
        ns: $ns,
        sa: $sa,
        outage_fallback: "true",
        bypass_orchestrator: "true",
        dedupe_key: $sig
      },
      annotations: {
        summary: ("Break-glass token issued: " + $reason),
        operator: $operator,
        duration: $duration
      },
      startsAt: $ts,
      generatorURL: "https://github.com/Halildeu/platform-k8s-gitops"
    }]')

  # No-token-log guard echo (token never appears in stderr/stdout)
  echo "  [alertmanager-fallback] POST $ALERTMANAGER_FALLBACK_URL (alertname=BreakGlassUsed, dedupe_key=${sig:0:12}...)"

  # Retry with exponential backoff (4xx no-retry, 5xx/timeout retry)
  local attempt=1
  while [[ $attempt -le $MAX_RETRIES ]]; do
    local code
    code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 \
      -X POST -H "Content-Type: application/json" \
      -d "$payload" "$ALERTMANAGER_FALLBACK_URL" 2>/dev/null || echo "000")

    case "$code" in
      2*)
        echo "  [alertmanager-fallback] delivered ($code)"
        return 0
        ;;
      4*)
        echo "  [alertmanager-fallback] FAILED ($code) — non-transient, no retry"
        return 1
        ;;
      *)
        local backoff=$((2 ** attempt))
        echo "  [alertmanager-fallback] attempt $attempt/$MAX_RETRIES failed ($code): sleeping ${backoff}s"
        sleep "$backoff"
        attempt=$((attempt + 1))
        ;;
    esac
  done

  echo "  [alertmanager-fallback] exhausted $MAX_RETRIES retries"
  return 1
}

# Trigger fallback delivery — orchestrator down OR gh failed
fallback_needed=0
fallback_reason=""

if ! orchestrator_reachable; then
  fallback_needed=1
  fallback_reason="orchestrator_down"
  echo "[break-glass] notification-orchestrator unreachable ($NOTIFY_ORCH_HEALTH_URL) — outage detected"
fi

# gh fail durumu zaten yukarıda warned ediliyor; explicit takip için flag yok
# (mevcut script gh hata durumunda exit etmiyor sadece warn). Eğer GH unavailable
# (sa cli / auth fail) bile orchestrator up ise, primary audit trail orchestrator
# audit publish (gelecek backend PR'a) — şu an local audit log + Alertmanager fallback
# (toggle açıksa).

if [[ "$fallback_needed" -eq 1 ]] && [[ "$ALARM_FALLBACK_ALERTMANAGER" == "1" ]]; then
  echo "[break-glass] dual-channel fallback active (reason=$fallback_reason); BreakGlassUsed → Alertmanager direct"
  if deliver_alertmanager_breakglass; then
    echo "[break-glass] Alertmanager direct fallback delivered"
  else
    echo "[break-glass] [WARN] Alertmanager direct fallback failed — local audit log only"
    echo "[break-glass] Operator: post-recovery, write OUTAGE_FALLBACK_USED audit event"
    echo "                 (notification-orchestrator audit publish — best-effort idempotent)"
  fi
fi

# ------------------------------------------------------------
# Output
# ------------------------------------------------------------

cat <<EOF

==============================================
BREAK-GLASS TOKEN ISSUED — TTL ${DURATION}
==============================================

To use:
  export KUBECONFIG=$KUBECONFIG_OUT

  # Verify identity:
  kubectl auth whoami    # → system:serviceaccount:$NS:$SA

  # Now perform mutation, e.g.:
  kubectl --context $CURRENT_CTX -n platform-prod set image deploy/<svc> ...

When done:
  unset KUBECONFIG
  rm -f $KUBECONFIG_OUT
  # Open reconciliation PR within 30min!

Reconciliation PR template:
  .github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md

==============================================
EOF
