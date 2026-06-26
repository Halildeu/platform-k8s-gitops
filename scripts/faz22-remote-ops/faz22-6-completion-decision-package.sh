#!/usr/bin/env bash
# Build a read-only Faz 22.6 owner decision package from completion-audit output.
#
# This script parses a previously captured faz22-6-completion-audit.sh output
# and writes bounded JSON/Markdown describing the remaining owner decisions and
# the package helpers that should be used after approval. It does not approve
# risk, write markers, mutate GitHub, touch Kubernetes, or contact endpoints.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/faz22-remote-ops/endpoint-agent-release-policy.sh
source "$SCRIPT_DIR/endpoint-agent-release-policy.sh"
endpoint_agent_release_policy_load "$REPO_ROOT"

AUDIT_FILE=""
OUTPUT_DIR=""
PREFIX="faz22-6-completion-decision-package"
GENERATED_AT=""

usage() {
  cat <<'EOF'
Usage:
  faz22-6-completion-decision-package.sh \
    --audit-file PATH \
    --output-dir DIR \
    [--prefix NAME] \
    [--generated-at ISO8601_FOR_TESTS]

The output package is read-only:

- <output-dir>/<prefix>.json
- <output-dir>/<prefix>.md

It contains current audit status, remaining owner-decision inputs, and helper
command templates. It does not generate acceptance markers or mutate external
state.
EOF
}

die() {
  printf 'completion-decision-package: %s\n' "$*" >&2
  exit 2
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --audit-file) [ "$#" -ge 2 ] || die "--audit-file needs a value"; AUDIT_FILE="$2"; shift 2 ;;
    --output-dir) [ "$#" -ge 2 ] || die "--output-dir needs a value"; OUTPUT_DIR="$2"; shift 2 ;;
    --prefix) [ "$#" -ge 2 ] || die "--prefix needs a value"; PREFIX="$2"; shift 2 ;;
    --generated-at) [ "$#" -ge 2 ] || die "--generated-at needs a value"; GENERATED_AT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

need jq

[ -n "$AUDIT_FILE" ] || die "audit-file is required"
[ -n "$OUTPUT_DIR" ] || die "output-dir is required"
[ -f "$AUDIT_FILE" ] || die "audit-file does not exist: $AUDIT_FILE"
case "$PREFIX" in
  *[!A-Za-z0-9._-]*|"") die "prefix must contain only A-Z, a-z, 0-9, dot, underscore, or dash" ;;
esac

if [ -z "$GENERATED_AT" ]; then
  GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
[[ "$GENERATED_AT" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
  || die "generated-at must be UTC ISO8601: YYYY-MM-DDTHH:MM:SSZ"

first_line() {
  local prefix="$1"
  awk -v prefix="$prefix" 'index($0, prefix) == 1 { print; exit }' "$AUDIT_FILE"
}

line_value() {
  local prefix="$1" line
  line="$(first_line "$prefix")"
  if [ -z "$line" ]; then
    printf ''
    return 0
  fi
  printf '%s' "${line#*=}"
}

line_status() {
  local line="$1"
  if [ -z "$line" ]; then
    printf 'missing'
    return 0
  fi
  local value
  value="${line#*=}"
  value="${value%% *}"
  case "$value" in
    pass) printf 'pass' ;;
    bounded_pilot_pass) printf 'bounded_pilot_pass' ;;
    bounded_pilot_risk_accepted) printf 'bounded_pilot_risk_accepted' ;;
    needs_hygiene) printf 'needs_hygiene' ;;
    blocked) printf 'blocked' ;;
    unknown) printf 'unknown' ;;
    *) printf 'unparsed' ;;
  esac
}

mkdir -p "$OUTPUT_DIR"

json_out="$OUTPUT_DIR/$PREFIX.json"
markdown_out="$OUTPUT_DIR/$PREFIX.md"

completion_line="$(first_line 'F22_6_COMPLETION=')"
next_required="$(line_value 'F22_6_NEXT_REQUIRED=')"
remote_bridge_line="$(first_line 'REMOTE_BRIDGE_LIVE=')"
b1_line="$(first_line 'GATE_B1_4_HARDWARE_ATTESTATION=')"
# ADR-0044: the fail-closed VIEW_ONLY gate is the ENGINEERING gate. The KVKK gate
# is tracked but non-blocking (surfaced for visibility; not an actionable blocker
# unless it is an allowlist_violation).
view_line="$(first_line 'GATE_VIEW_ONLY_ENGINEERING=')"
kvkk_line="$(first_line 'GATE_VIEW_ONLY_KVKK=')"
release_line="$(first_line 'F22_6_RELEASE_LINEAGE=')"
release_gate_line="$(first_line 'RELEASE_LINEAGE_GATE=')"
release_waiver_line="$(first_line 'RELEASE_LINEAGE_WAIVER=')"
agent_train_line="$(first_line 'AGENT_RELEASE_TRAIN=')"

b1_status="$(line_status "$b1_line")"
view_status="$(line_status "$view_line")"
release_status="$(line_status "$release_line")"
release_gate_status="$(line_status "$release_gate_line")"
release_waiver_status="$(line_status "$release_waiver_line")"
agent_train_status="$(line_status "$agent_train_line")"
completion_status="$(line_status "$completion_line")"
remote_bridge_status="$(line_status "$remote_bridge_line")"

status_is_satisfied() {
  case "$1" in
    pass|bounded_pilot_pass|bounded_pilot_risk_accepted) return 0 ;;
    *) return 1 ;;
  esac
}

b1_required=0
view_required=0
release_required=0
status_is_satisfied "$b1_status" || b1_required=1
status_is_satisfied "$view_status" || view_required=1
if ! { status_is_satisfied "$release_status" && status_is_satisfied "$release_gate_status"; }; then
  release_required=1
fi

# Command templates intentionally keep shell variables literal for the operator
# or follow-up automation that will fill owner-approved values.
# shellcheck disable=SC2016
b1_hardware_cmd='scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh --mode hardware --marker-out "$MARKER_DIR/b1-4-hardware-marker.txt" --owner-approved-by "$OWNER_APPROVED_BY" --approved-at "$APPROVED_AT"'
# shellcheck disable=SC2016
b1_risk_cmd='scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh --mode risk --marker-out "$MARKER_DIR/b1-4-risk-marker.txt" --owner-approved-by "$OWNER_APPROVED_BY" --approved-at "$APPROVED_AT" --expires-at "$EXPIRES_AT"'
# shellcheck disable=SC2016
view_cmd='scripts/faz22-remote-ops/faz22-6-view-only-evidence-package.sh --manifest-out "$MARKER_DIR/view-only-evidence.json" --marker-out "$MARKER_DIR/view-only-marker.txt" --evidence-url "$VIEW_ONLY_EVIDENCE_URL" --pilot-device "$PILOT_DEVICE" --session-id "$VIEW_ONLY_SESSION_ID" --recording-mode disabled --d10-fail-closed pass --dlp-mask-policy pass --local-abort pass --active-indicator pass --viewer-path-decision "$VIEWER_PATH_DECISION" --owner-approved-by "$OWNER_APPROVED_BY" --approved-at "$APPROVED_AT" --expires-at "$EXPIRES_AT"'
# shellcheck disable=SC2016
release_cmd="scripts/faz22-remote-ops/faz22-6-release-lineage-waiver-package.sh --marker-out \"\$MARKER_DIR/release-lineage-waiver-marker.txt\" --release-tag $EXPECTED_AGENT_TAG --artifact-host-digest $EXPECTED_ARTIFACT_HOST_DIGEST --owner-approved-by \"\$OWNER_APPROVED_BY\" --approved-at \"\$APPROVED_AT\" --expires-at \"\$EXPIRES_AT\""

jq -nS \
  --arg schema_version "faz22.6-completion-decision-package-v1" \
  --arg generated_at "$GENERATED_AT" \
  --arg audit_file "$AUDIT_FILE" \
  --arg completion_status "$completion_status" \
  --arg completion_line "$completion_line" \
  --arg next_required "$next_required" \
  --arg remote_bridge_status "$remote_bridge_status" \
  --arg remote_bridge_line "$remote_bridge_line" \
  --arg b1_status "$b1_status" \
  --arg b1_line "$b1_line" \
  --arg b1_hardware_cmd "$b1_hardware_cmd" \
  --arg b1_risk_cmd "$b1_risk_cmd" \
  --arg view_status "$view_status" \
  --arg view_line "$view_line" \
  --arg view_cmd "$view_cmd" \
  --arg release_status "$release_status" \
  --arg release_line "$release_line" \
  --arg release_gate_status "$release_gate_status" \
  --arg release_gate_line "$release_gate_line" \
  --arg release_waiver_status "$release_waiver_status" \
  --arg release_waiver_line "$release_waiver_line" \
  --arg agent_train_status "$agent_train_status" \
  --arg agent_train_line "$agent_train_line" \
  --arg release_cmd "$release_cmd" \
  '{
    schema_version: $schema_version,
    generated_at: $generated_at,
    audit_file: $audit_file,
    boundary: [
      "read-only decision package",
      "does not approve risk",
      "does not write markers",
      "does not mutate GitHub, Kubernetes, releases, endpoints, or secrets",
      "does not claim Faz 22.6 completion"
    ],
    completion: {
      status: $completion_status,
      line: $completion_line,
      next_required: ($next_required | split(",") | map(select(length > 0))),
      remote_bridge: {
        status: $remote_bridge_status,
        line: $remote_bridge_line
      }
    },
    decisions: [
      {
        id: "b1_4_hardware_attestation",
        issue: "Halildeu/platform-backend#548",
        current_status: $b1_status,
        audit_line: $b1_line,
        owner_inputs_required: ["OWNER_APPROVED_BY", "APPROVED_AT", "EXPIRES_AT for bounded-risk path"],
        acceptance_paths: [
          {
            id: "hardware",
            meaning: "real device-key/TPM evidence exists and #548 can carry the hardware marker",
            helper_command: $b1_hardware_cmd
          },
          {
            id: "bounded-risk",
            meaning: "named owner accepts time-bounded enrollment-backed pilot risk",
            helper_command: $b1_risk_cmd
          }
        ],
        forbidden_claims: ["tpm-complete", "hardware-attestation-complete", "5-device", "50-device", "800-device", "production", "broad-rollout"]
      },
      {
        id: "view_only_screen_share",
        issue: "Halildeu/platform-k8s-gitops#1580",
        current_status: $view_status,
        audit_line: $view_line,
        owner_inputs_required: ["OWNER_APPROVED_BY", "APPROVED_AT", "EXPIRES_AT", "PILOT_DEVICE", "VIEW_ONLY_SESSION_ID", "VIEW_ONLY_EVIDENCE_URL", "VIEWER_PATH_DECISION"],
        acceptance_paths: [
          {
            id: "view-only-evidence-package",
            meaning: "real VIEW_ONLY product-channel evidence package and owner signoff exist",
            helper_command: $view_cmd
          }
        ],
        forbidden_claims: ["rdp", "credential-entry", "raw-shell", "port-forward", "5-device", "50-device", "800-device", "production", "broad-rollout"]
      },
      {
        id: "release_lineage",
        issue: "Halildeu/platform-k8s-gitops#1901",
        current_status: $release_status,
        audit_line: $release_line,
        completion_gate_status: $release_gate_status,
        completion_gate_line: $release_gate_line,
        waiver_status: $release_waiver_status,
        waiver_line: $release_waiver_line,
        agent_release_train_status: $agent_train_status,
        agent_release_train_line: $agent_train_line,
        owner_inputs_required: ["OWNER_APPROVED_BY", "APPROVED_AT", "EXPIRES_AT"],
        acceptance_paths: [
          {
            id: "full-hygiene-fix",
            meaning: "release-lineage audit prints F22_6_RELEASE_LINEAGE=pass without waiver",
            helper_command: "N/A"
          },
          {
            id: "bounded-pilot-waiver",
            meaning: "named owner accepts time-bounded pilot-only waiver for mutable release object and dense release train",
            helper_command: $release_cmd
          }
        ],
        forbidden_claims: ["5-device", "50-device", "800-device", "production", "broad-rollout"]
      }
    ]
  }' >"$json_out"

cat >"$markdown_out" <<EOF
# Faz 22.6 Completion Decision Package

- Generated at: \`$GENERATED_AT\`
- Audit file: \`$AUDIT_FILE\`
- Completion status: \`$completion_status\`
- Next required: \`${next_required:-missing}\`

## Boundary

This package is read-only. It does not approve risk, write markers, mutate
GitHub, Kubernetes, releases, endpoints, or secrets, and it does not claim Faz
22.6 completion.

## Live Audit Lines

\`\`\`text
${remote_bridge_line:-REMOTE_BRIDGE_LIVE=missing}
${b1_line:-GATE_B1_4_HARDWARE_ATTESTATION=missing}
${view_line:-GATE_VIEW_ONLY_ENGINEERING=missing}
${kvkk_line:-GATE_VIEW_ONLY_KVKK=missing}
${release_gate_line:-RELEASE_LINEAGE_GATE=missing}
${release_line:-F22_6_RELEASE_LINEAGE=missing}
${release_waiver_line:-RELEASE_LINEAGE_WAIVER=missing}
${completion_line:-F22_6_COMPLETION=missing}
F22_6_NEXT_REQUIRED=${next_required:-missing}
\`\`\`
EOF

cat >>"$markdown_out" <<EOF

## Satisfied / Non-Actionable Gates
EOF

satisfied_written=0
if [ "$b1_required" = "0" ]; then
  cat >>"$markdown_out" <<EOF

- Halildeu/platform-backend#548: \`$b1_status\`; no B1.4 marker helper action is required by this package.
EOF
  satisfied_written=1
fi
if [ "$view_required" = "0" ]; then
  cat >>"$markdown_out" <<EOF

- Halildeu/platform-k8s-gitops#1580: \`$view_status\`; no VIEW_ONLY marker helper action is required by this package.
EOF
  satisfied_written=1
fi
if [ "$release_required" = "0" ]; then
  cat >>"$markdown_out" <<EOF

- Halildeu/platform-k8s-gitops#1901: \`$release_status\` / \`$release_gate_status\`; release-lineage is evidence-only here, no waiver/helper action is required.
EOF
  satisfied_written=1
fi
if [ "$satisfied_written" = "0" ]; then
  cat >>"$markdown_out" <<'EOF'

- None.
EOF
fi

cat >>"$markdown_out" <<'EOF'

## Required Decisions
EOF

required_written=0
if [ "$b1_required" = "1" ]; then
  cat >>"$markdown_out" <<EOF

### Halildeu/platform-backend#548

Choose exactly one path after a real owner decision:

\`\`\`bash
$b1_hardware_cmd
$b1_risk_cmd
\`\`\`
EOF
  required_written=1
fi

if [ "$view_required" = "1" ]; then
  cat >>"$markdown_out" <<EOF

### Halildeu/platform-k8s-gitops#1580

Use only after real VIEW_ONLY product-channel evidence and owner signoff exist:

\`\`\`bash
$view_cmd
\`\`\`
EOF
  required_written=1
fi

if [ "$release_required" = "1" ]; then
  cat >>"$markdown_out" <<EOF

### Halildeu/platform-k8s-gitops#1901

Either fix release-lineage hygiene until the release-lineage audit passes
without a waiver, or use this bounded-pilot-only waiver helper after owner
approval:

\`\`\`bash
$release_cmd
\`\`\`
EOF
  required_written=1
fi

if [ "$required_written" = "0" ]; then
  cat >>"$markdown_out" <<'EOF'

No owner/operator decisions are required by this package.
EOF
fi

printf 'json=%s\n' "$json_out"
printf 'markdown=%s\n' "$markdown_out"
