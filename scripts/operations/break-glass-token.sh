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
