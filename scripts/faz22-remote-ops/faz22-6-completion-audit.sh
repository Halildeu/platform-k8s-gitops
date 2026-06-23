#!/usr/bin/env bash
# Conservative Faz 22.6 completion audit.
#
# This helper does not mutate GitHub, Kubernetes, or endpoint state. It gathers
# enough public/control-plane truth to prevent bounded pilot or source-only
# evidence from being over-reported as full Faz 22.6 completion.

set -euo pipefail

GITOPS_REPO="${GITOPS_REPO:-Halildeu/platform-k8s-gitops}"
BACKEND_REPO="${BACKEND_REPO:-Halildeu/platform-backend}"
AGENT_REPO="${AGENT_REPO:-Halildeu/platform-agent}"
WEB_REPO="${WEB_REPO:-Halildeu/platform-web}"
SSH_TARGET="${SSH_TARGET:-staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXPECTED_REMOTE_BRIDGE_DIGEST="${EXPECTED_REMOTE_BRIDGE_DIGEST:-sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c}"
EXPECTED_AGENT_LATEST_TAG="${EXPECTED_AGENT_LATEST_TAG:-v0.2.28}"
RELEASE_HYGIENE_RECENT_THRESHOLD="${RELEASE_HYGIENE_RECENT_THRESHOLD:-5}"
RELEASE_LINEAGE_WAIVER_REF="${RELEASE_LINEAGE_WAIVER_REF:-Halildeu/platform-k8s-gitops#1901}"
RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS="${RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS:-5-device,50-device,800-device,production,broad-rollout}"
EXPECTED_ARTIFACT_HOST_DIGEST="${EXPECTED_ARTIFACT_HOST_DIGEST:-sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'F22_6_AUDIT_ERROR=missing-command:%s\n' "$1"
    exit 2
  }
}

lineage_print_check() {
  local label="$1" status="$2"
  shift 2
  printf '%s=%s' "$label" "$status"
  if [ "$#" -gt 0 ]; then
    printf ' %s' "$*"
  fi
  printf '\n'
}

waiver_field() {
  # waiver_field <key> <issue-body>
  local key="$1"
  sed -n "s/^${key}:[[:space:]]*//p" | head -1
}

check_release_lineage_waiver() {
  # check_release_lineage_waiver <comma-separated-required-findings>
  local required_findings="$1"
  local ref="$RELEASE_LINEAGE_WAIVER_REF"
  local repo_ref number issue_json state body today
  local marker scope release_tag digest accepted_findings forbidden_claims owner approved_at expires_at
  local missing=()

  if [ -z "$ref" ]; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'missing' 'reason=no-waiver-ref'
    return 1
  fi

  if printf '%s' "$ref" | grep -q '^https://github.com/'; then
    repo_ref="${ref#https://github.com/}"
    repo_ref="${repo_ref%%/issues/*}"
    number="${ref##*/}"
  elif printf '%s' "$ref" | grep -q '#'; then
    repo_ref="${ref%%#*}"
    number="${ref##*#}"
  else
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=bad-ref-format"
    return 1
  fi

  if ! issue_json="$(gh issue view "$number" -R "$repo_ref" --json state,body,title 2>&1)"; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$(printf '%q' "$issue_json")"
    return 1
  fi
  state="$(printf '%s\n' "$issue_json" | jq -r '.state // ""')"
  body="$(printf '%s\n' "$issue_json" | jq -r '.body // ""')"
  if [ "$state" != "OPEN" ]; then
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref state=$state reason=issue-not-open"
    return 1
  fi

  marker="$(printf '%s\n' "$body" | waiver_field 'F22_6_RELEASE_LINEAGE_WAIVER')"
  scope="$(printf '%s\n' "$body" | waiver_field 'waiver_scope')"
  release_tag="$(printf '%s\n' "$body" | waiver_field 'release_tag')"
  digest="$(printf '%s\n' "$body" | waiver_field 'artifact_host_digest')"
  accepted_findings="$(printf '%s\n' "$body" | waiver_field 'accepted_findings')"
  forbidden_claims="$(printf '%s\n' "$body" | waiver_field 'forbidden_claims')"
  owner="$(printf '%s\n' "$body" | waiver_field 'owner_approved_by')"
  approved_at="$(printf '%s\n' "$body" | waiver_field 'approved_at')"
  expires_at="$(printf '%s\n' "$body" | waiver_field 'expires_at')"

  [ "$marker" = "v1" ] || missing+=("marker")
  [ "$scope" = "bounded-pilot-only" ] || missing+=("scope")
  [ "$release_tag" = "$EXPECTED_AGENT_TAG" ] || missing+=("release_tag")
  [ "$digest" = "$EXPECTED_ARTIFACT_HOST_DIGEST" ] || missing+=("artifact_host_digest")
  if [ -z "$owner" ] || printf '%s' "$owner" | grep -Eiq '^(tbd|none|n/a)
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json state --jq .state
}

issue_title() {
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json title --jq .title
}

pass_if_state() {
  local label="$1" repo="$2" number="$3" want="$4"
  local state title
  state="$(issue_state "$repo" "$number")"
  title="$(issue_title "$repo" "$number")"
  if [ "$state" = "$want" ]; then
    printf '%s=pass state=%s issue=%s#%s title=%q\n' "$label" "$state" "$repo" "$number" "$title"
    return 0
  fi
  printf '%s=blocked state=%s expected=%s issue=%s#%s title=%q\n' "$label" "$state" "$want" "$repo" "$number" "$title"
  return 1
}

check_remote_bridge() {
  local output digest_hits secret_hits
  if ! command -v ssh >/dev/null 2>&1; then
    printf 'REMOTE_BRIDGE_LIVE=unknown reason=missing-ssh\n'
    return 1
  fi
  # shellcheck disable=SC2029 # KUBE_CONTEXT/KUBE_NAMESPACE are intended client-side audit parameters.
  if ! output="$(ssh "$SSH_TARGET" "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get deploy endpoint-admin-service endpoint-admin-remote-bridge -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image && kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get pod -l 'app.kubernetes.io/name in (endpoint-admin-service,endpoint-admin-remote-bridge)' -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID && kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get externalsecret endpoint-admin-remote-bridge-secrets endpoint-admin-remote-bridge-signer endpoint-admin-remote-bridge-tls -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status,REASON:.status.conditions[0].reason --no-headers" 2>&1)"; then
    printf 'REMOTE_BRIDGE_LIVE=unknown reason=%q\n' "$output"
    return 1
  fi

  printf 'REMOTE_BRIDGE_LIVE_OUTPUT_BEGIN\n%s\nREMOTE_BRIDGE_LIVE_OUTPUT_END\n' "$output"
  # Pilot topology intentionally runs the primary endpoint-admin deployment and
  # the separate remote-bridge broker deployment from the same endpoint-admin
  # image. If remote-bridge becomes a separate image, split this into two
  # explicit digest expectations instead of weakening the check.
  digest_hits="$(printf '%s\n' "$output" | grep -c "@${EXPECTED_REMOTE_BRIDGE_DIGEST}" || true)"
  secret_hits="$(printf '%s\n' "$output" | grep -cE 'True.*SecretSynced' || true)"
  if [ "$digest_hits" -ge 4 ] && [ "$secret_hits" -ge 3 ]; then
    printf 'REMOTE_BRIDGE_LIVE=pass expected_digest=%s\n' "$EXPECTED_REMOTE_BRIDGE_DIGEST"
    return 0
  fi
  printf 'REMOTE_BRIDGE_LIVE=blocked expected_digest=%s digest_hits=%s secret_synced_hits=%s\n' "$EXPECTED_REMOTE_BRIDGE_DIGEST" "$digest_hits" "$secret_hits"
  return 1
}

check_release_train() {
  local releases latest count tags is_immutable
  local needs_hygiene=0
  local waiver_findings=()
  if ! releases="$(gh release list -R "$AGENT_REPO" --limit 20 \
      --json tagName,isLatest,isDraft,isPrerelease,isImmutable,publishedAt,name 2>&1)"; then
    printf 'AGENT_RELEASE_TRAIN=unknown reason=%q\n' "$releases"
    return 1
  fi
  latest="$(printf '%s\n' "$releases" \
    | jq -r '(map(select(.isLatest))[0].tagName // .[0].tagName // "unknown")')"
  count="$(printf '%s\n' "$releases" \
    | jq '[.[].tagName | select(test("^v0\\.2\\."))] | length')"
  tags="$(printf '%s\n' "$releases" | jq -r '[.[].tagName] | join(",")')"
  is_immutable="$(printf '%s\n' "$releases" | jq -r --arg tag "$EXPECTED_AGENT_LATEST_TAG" 'map(select(.tagName == $tag)) as $m | if ($m|length) > 0 then $m[0].isImmutable else false end')"
  printf 'AGENT_RELEASE_TRAIN_LATEST=%s\n' "${latest:-unknown}"
  printf 'AGENT_RELEASE_TRAIN_RECENT_V0_2_COUNT=%s\n' "$count"
  printf 'AGENT_RELEASE_TRAIN_RECENT_TAGS=%s\n' "$tags"
  if [ "${latest:-}" != "$EXPECTED_AGENT_LATEST_TAG" ]; then
    printf 'AGENT_RELEASE_TRAIN=blocked latest=%s expected_latest=%s\n' "${latest:-unknown}" "$EXPECTED_AGENT_LATEST_TAG"
    return 1
  fi

  if [ "$is_immutable" != "true" ]; then
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_IMMUTABLE')
  fi

  if [ "$count" -ge "$RELEASE_HYGIENE_RECENT_THRESHOLD" ]; then
    needs_hygiene=1
    waiver_findings+=('GITHUB_RELEASE_DENSE_TRAIN')
  fi

  if [ "$needs_hygiene" -ne 0 ]; then
    local required_findings
    required_findings="$(IFS=,; printf '%s' "${waiver_findings[*]}")"
    if check_release_lineage_waiver "$required_findings"; then
      printf 'AGENT_RELEASE_TRAIN=bounded_pilot_pass latest=%s recent_v0_2_count=%s isImmutable=%s waiver_ref=%s\n' "$latest" "$count" "$is_immutable" "$RELEASE_LINEAGE_WAIVER_REF"
      return 0
    fi
    printf 'AGENT_RELEASE_TRAIN=needs_hygiene latest=%s recent_v0_2_count=%s isImmutable=%s reason=rapid-v0.2-train-or-mutable-release-requires-lineage-waiver\n' "$latest" "$count" "$is_immutable"
    return 1
  fi

  lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'not_required' 'reason=no-release-lineage-hygiene'
  printf 'AGENT_RELEASE_TRAIN=pass latest=%s recent_v0_2_count=%s isImmutable=%s\n' "$latest" "$count" "$is_immutable"
  return 0
}

main() {
  need gh
  need grep
  need awk
  need jq
  need ssh

  local blocked=0
  local next_required=()

  printf 'F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion\n'
  printf 'F22_6_AUDIT_CONTRACT=docs/runbooks/RB-faz22.6-autonomous-completion-contract.md\n'

  pass_if_state 'GATE_22_6_1_OPERATION_CATALOG' "$BACKEND_REPO" 701 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_2_APPROVED_SCRIPT_RUNNER' "$BACKEND_REPO" 702 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_3_CONSTRAINED_EXECUTOR' "$AGENT_REPO" 208 CLOSED || blocked=1
  pass_if_state 'GATE_AGENTPC2_BOOTSTRAP' "$GITOPS_REPO" 1768 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_TERMINAL' "$WEB_REPO" 820 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_SESSION_STATE' "$WEB_REPO" 822 CLOSED || blocked=1

  if pass_if_state 'GATE_B1_4_HARDWARE_ATTESTATION' "$BACKEND_REPO" 548 CLOSED; then
    :
  else
    blocked=1
    next_required+=('close-or-risk-accept-548')
  fi

  if pass_if_state 'GATE_VIEW_ONLY_SCREEN_SHARE' "$GITOPS_REPO" 1580 CLOSED; then
    :
  else
    blocked=1
    next_required+=('close-1580')
  fi

  if ! check_remote_bridge; then
    blocked=1
    next_required+=('fix-remote-bridge-live')
  fi
  if ! check_release_train; then
    blocked=1
    next_required+=('fix-release-lineage-hygiene')
  fi

  if [ "$blocked" -eq 0 ]; then
    printf 'F22_6_COMPLETION=pass\n'
  else
    printf 'F22_6_COMPLETION=blocked\n'
    if [ "${#next_required[@]}" -gt 0 ]; then
      local next_joined
      next_joined="$(IFS=,; printf '%s' "${next_required[*]}")"
      printf 'F22_6_NEXT_REQUIRED=%s\n' "$next_joined"
    else
      printf 'F22_6_NEXT_REQUIRED=inspect-blocked-gates\n'
    fi
  fi
}

main "$@"
; then
    missing+=("owner_approved_by")
  fi

  local finding
  IFS=',' read -r -a _required_findings <<<"$required_findings"
  for finding in "${_required_findings[@]}"; do
    [ -z "$finding" ] && continue
    if ! printf '%s' "$accepted_findings" | tr -d ' ' | grep -Eq "(^|,)${finding}(,|$)"; then
      missing+=("accepted_findings:$finding")
    fi
  done

  local forbidden
  IFS=',' read -r -a _forbidden_claims <<<"$RELEASE_LINEAGE_WAIVER_FORBIDDEN_CLAIMS"
  for forbidden in "${_forbidden_claims[@]}"; do
    [ -z "$forbidden" ] && continue
    if ! printf '%s' "$forbidden_claims" | tr -d ' ' | grep -Eq "(^|,)${forbidden}(,|$)"; then
      missing+=("forbidden_claims:$forbidden")
    fi
  done

  if ! [[ "$approved_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("approved_at")
  fi
  if ! [[ "$expires_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("expires_at")
  fi
  today="$(date -u +%Y-%m-%d 2>/dev/null || true)"
  if ! [[ "$today" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    missing+=("today-unparseable")
  else
    if [[ "$approved_at" > "$today" ]]; then
      missing+=("approved_at-in-future")
    fi
    if [[ "$expires_at" < "$today" ]]; then
      missing+=("expires_at-expired")
    fi
  fi

  if [ "${#missing[@]}" -ne 0 ]; then
    local reason
    reason="$(IFS=,; printf '%s' "${missing[*]}")"
    lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'blocked' "ref=$ref reason=$reason"
    return 1
  fi

  lineage_print_check 'RELEASE_LINEAGE_WAIVER' 'bounded_pilot_pass' "ref=$ref owner=$owner expires_at=$expires_at accepted_findings=$(printf '%q' "$accepted_findings")"
  return 0
}

issue_state() {
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json state --jq .state
}

issue_title() {
  local repo="$1" number="$2"
  gh issue view "$number" -R "$repo" --json title --jq .title
}

pass_if_state() {
  local label="$1" repo="$2" number="$3" want="$4"
  local state title
  state="$(issue_state "$repo" "$number")"
  title="$(issue_title "$repo" "$number")"
  if [ "$state" = "$want" ]; then
    printf '%s=pass state=%s issue=%s#%s title=%q\n' "$label" "$state" "$repo" "$number" "$title"
    return 0
  fi
  printf '%s=blocked state=%s expected=%s issue=%s#%s title=%q\n' "$label" "$state" "$want" "$repo" "$number" "$title"
  return 1
}

check_remote_bridge() {
  local output digest_hits secret_hits
  if ! command -v ssh >/dev/null 2>&1; then
    printf 'REMOTE_BRIDGE_LIVE=unknown reason=missing-ssh\n'
    return 1
  fi
  # shellcheck disable=SC2029 # KUBE_CONTEXT/KUBE_NAMESPACE are intended client-side audit parameters.
  if ! output="$(ssh "$SSH_TARGET" "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get deploy endpoint-admin-service endpoint-admin-remote-bridge -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,UPDATED:.status.updatedReplicas,IMAGE:.spec.template.spec.containers[0].image && kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get pod -l 'app.kubernetes.io/name in (endpoint-admin-service,endpoint-admin-remote-bridge)' -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,RESTARTS:.status.containerStatuses[0].restartCount,IMAGEID:.status.containerStatuses[0].imageID && kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' get externalsecret endpoint-admin-remote-bridge-secrets endpoint-admin-remote-bridge-signer endpoint-admin-remote-bridge-tls -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status,REASON:.status.conditions[0].reason --no-headers" 2>&1)"; then
    printf 'REMOTE_BRIDGE_LIVE=unknown reason=%q\n' "$output"
    return 1
  fi

  printf 'REMOTE_BRIDGE_LIVE_OUTPUT_BEGIN\n%s\nREMOTE_BRIDGE_LIVE_OUTPUT_END\n' "$output"
  # Pilot topology intentionally runs the primary endpoint-admin deployment and
  # the separate remote-bridge broker deployment from the same endpoint-admin
  # image. If remote-bridge becomes a separate image, split this into two
  # explicit digest expectations instead of weakening the check.
  digest_hits="$(printf '%s\n' "$output" | grep -c "@${EXPECTED_REMOTE_BRIDGE_DIGEST}" || true)"
  secret_hits="$(printf '%s\n' "$output" | grep -cE 'True.*SecretSynced' || true)"
  if [ "$digest_hits" -ge 4 ] && [ "$secret_hits" -ge 3 ]; then
    printf 'REMOTE_BRIDGE_LIVE=pass expected_digest=%s\n' "$EXPECTED_REMOTE_BRIDGE_DIGEST"
    return 0
  fi
  printf 'REMOTE_BRIDGE_LIVE=blocked expected_digest=%s digest_hits=%s secret_synced_hits=%s\n' "$EXPECTED_REMOTE_BRIDGE_DIGEST" "$digest_hits" "$secret_hits"
  return 1
}

check_release_train() {
  local releases latest count tags
  if ! releases="$(gh release list -R "$AGENT_REPO" --limit 20 \
      --json tagName,isLatest,isDraft,isPrerelease,publishedAt,name 2>&1)"; then
    printf 'AGENT_RELEASE_TRAIN=unknown reason=%q\n' "$releases"
    return 1
  fi
  latest="$(printf '%s\n' "$releases" \
    | jq -r '(map(select(.isLatest))[0].tagName // .[0].tagName // "unknown")')"
  count="$(printf '%s\n' "$releases" \
    | jq '[.[].tagName | select(test("^v0\\.2\\."))] | length')"
  tags="$(printf '%s\n' "$releases" | jq -r '[.[].tagName] | join(",")')"
  printf 'AGENT_RELEASE_TRAIN_LATEST=%s\n' "${latest:-unknown}"
  printf 'AGENT_RELEASE_TRAIN_RECENT_V0_2_COUNT=%s\n' "$count"
  printf 'AGENT_RELEASE_TRAIN_RECENT_TAGS=%s\n' "$tags"
  if [ "${latest:-}" != "$EXPECTED_AGENT_LATEST_TAG" ]; then
    printf 'AGENT_RELEASE_TRAIN=blocked latest=%s expected_latest=%s\n' "${latest:-unknown}" "$EXPECTED_AGENT_LATEST_TAG"
    return 1
  fi

  if [ "$count" -ge "$RELEASE_HYGIENE_RECENT_THRESHOLD" ]; then
    printf 'AGENT_RELEASE_TRAIN=needs_hygiene latest=%s recent_v0_2_count=%s reason=rapid-v0.2-train-requires-lineage-audit\n' "$latest" "$count"
    return 1
  fi

  printf 'AGENT_RELEASE_TRAIN=pass latest=%s recent_v0_2_count=%s\n' "$latest" "$count"
  return 0
}

main() {
  need gh
  need grep
  need awk
  need jq
  need ssh

  local blocked=0

  printf 'F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion\n'
  printf 'F22_6_AUDIT_CONTRACT=docs/runbooks/RB-faz22.6-autonomous-completion-contract.md\n'

  pass_if_state 'GATE_22_6_1_OPERATION_CATALOG' "$BACKEND_REPO" 701 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_2_APPROVED_SCRIPT_RUNNER' "$BACKEND_REPO" 702 CLOSED || blocked=1
  pass_if_state 'GATE_22_6_3_CONSTRAINED_EXECUTOR' "$AGENT_REPO" 208 CLOSED || blocked=1
  pass_if_state 'GATE_AGENTPC2_BOOTSTRAP' "$GITOPS_REPO" 1768 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_TERMINAL' "$WEB_REPO" 820 CLOSED || blocked=1
  pass_if_state 'GATE_OPERATOR_UX_SESSION_STATE' "$WEB_REPO" 822 CLOSED || blocked=1

  if pass_if_state 'GATE_B1_4_HARDWARE_ATTESTATION' "$BACKEND_REPO" 548 CLOSED; then
    :
  else
    blocked=1
  fi

  if pass_if_state 'GATE_VIEW_ONLY_SCREEN_SHARE' "$GITOPS_REPO" 1580 CLOSED; then
    :
  else
    blocked=1
  fi

  check_remote_bridge || blocked=1
  check_release_train || blocked=1

  if [ "$blocked" -eq 0 ]; then
    printf 'F22_6_COMPLETION=pass\n'
  else
    printf 'F22_6_COMPLETION=blocked\n'
    printf 'F22_6_NEXT_REQUIRED=close-or-risk-accept-548,close-1580,fix-release-lineage-hygiene\n'
  fi
}

main "$@"
\n