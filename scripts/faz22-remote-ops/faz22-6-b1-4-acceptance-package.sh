#!/usr/bin/env bash
# Generate the exact Faz 22.6 B1.4 hardware-attestation or bounded-risk
# acceptance marker expected by faz22-6-completion-audit.sh.
#
# This helper is offline/read-only. It does not approve #548, does not write to
# GitHub, and does not claim hardware attestation exists. It only prevents
# marker drift after a real owner decision and evidence package already exist.

set -euo pipefail

MODE=""
MARKER_OUT=""
OWNER_APPROVED_BY=""
APPROVED_AT=""
EXPIRES_AT=""

HARDWARE_ACCEPTANCE_SCOPE="hardware-attestation"
HARDWARE_DEVICE_KEY_EVIDENCE="present"
HARDWARE_TPM_OR_SECURE_ELEMENT="present"
HARDWARE_AGENT_WIRE_CONTRACT="present"
HARDWARE_BROKER_VERIFIER="pass"
HARDWARE_ROOT_POLICY="pass"
HARDWARE_FIELD_EVIDENCE="attached"
HARDWARE_POSITIVE_MATRIX="hardware-attested-device"
HARDWARE_NEGATIVE_MATRIX="missing,stale,replay,wrong-device,wrong-tenant"

RISK_SCOPE="bounded-pilot-enrollment-backed-trust"
RISK_ACCEPTED_GAP="no-real-tpm-attestation"
RISK_COMPENSATING_CONTROLS="cert-bound-token,mTLS,revocation-check,signed-permits,dual-control,audit-recording,kill-revoke"
RISK_FORBIDDEN_CLAIMS="tpm-complete,hardware-attestation-complete,5-device,50-device,800-device,production,broad-rollout"

usage() {
  cat <<'EOF'
Usage:
  faz22-6-b1-4-acceptance-package.sh \
    --mode hardware|risk \
    --marker-out PATH \
    --owner-approved-by NAMED_OWNER \
    --approved-at YYYY-MM-DD \
    [--expires-at YYYY-MM-DD]

Modes:
  hardware  Produces F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1.
            Use only after real device-key/TPM evidence, broker verifier,
            root policy, and field positive/negative evidence exist.

  risk      Produces F22_6_B1_4_RISK_ACCEPTANCE: v1.
            Use only after a named owner accepts bounded-pilot residual risk.
            Requires --expires-at.

The helper does not write to GitHub, does not close platform-backend#548, and
does not approve any risk by itself.
EOF
}

die() {
  printf 'b1-4-acceptance-package: %s\n' "$*" >&2
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) [ "$#" -ge 2 ] || die "--mode needs a value"; MODE="$2"; shift 2 ;;
    --marker-out) [ "$#" -ge 2 ] || die "--marker-out needs a value"; MARKER_OUT="$2"; shift 2 ;;
    --owner-approved-by) [ "$#" -ge 2 ] || die "--owner-approved-by needs a value"; OWNER_APPROVED_BY="$2"; shift 2 ;;
    --approved-at) [ "$#" -ge 2 ] || die "--approved-at needs a value"; APPROVED_AT="$2"; shift 2 ;;
    --expires-at) [ "$#" -ge 2 ] || die "--expires-at needs a value"; EXPIRES_AT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

require_nonempty() {
  local name="$1" value="$2"
  [ -n "$value" ] || die "$name is required"
}

require_no_control_chars() {
  local name="$1" value="$2"
  if printf '%s' "$value" | LC_ALL=C grep -q '[[:cntrl:]]'; then
    die "$name must not contain control characters"
  fi
}

owner_is_invalid() {
  local owner_lc
  owner_lc="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [ -z "$owner_lc" ] && return 0
  case "$owner_lc" in
    tbd|none|n/a|na|placeholder|owner|named-owner) return 0 ;;
  esac
  return 1
}

valid_iso_date() {
  [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]
}

require_nonempty "mode" "$MODE"
require_nonempty "marker-out" "$MARKER_OUT"
require_nonempty "owner-approved-by" "$OWNER_APPROVED_BY"
require_nonempty "approved-at" "$APPROVED_AT"

case "$MODE" in
  hardware|risk) ;;
  *) die "mode must be hardware or risk" ;;
esac

require_no_control_chars "owner-approved-by" "$OWNER_APPROVED_BY"
owner_is_invalid "$OWNER_APPROVED_BY" && die "owner-approved-by must be a named owner, not a placeholder"
valid_iso_date "$APPROVED_AT" || die "approved-at must be YYYY-MM-DD"

today="$(date -u +%F)"
if [[ "$APPROVED_AT" > "$today" ]]; then
  die "approved-at must not be in the future"
fi

if [ "$MODE" = "risk" ]; then
  require_nonempty "expires-at" "$EXPIRES_AT"
  valid_iso_date "$EXPIRES_AT" || die "expires-at must be YYYY-MM-DD"
  if [[ "$APPROVED_AT" > "$EXPIRES_AT" ]]; then
    die "approved-at must not be after expires-at"
  fi
  if [[ "$EXPIRES_AT" < "$today" ]]; then
    die "expires-at must not be expired"
  fi
elif [ -n "$EXPIRES_AT" ]; then
  die "expires-at is only valid for risk mode"
fi

mkdir -p "$(dirname "$MARKER_OUT")"

if [ "$MODE" = "hardware" ]; then
  cat >"$MARKER_OUT" <<EOF
F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1
acceptance_scope: $HARDWARE_ACCEPTANCE_SCOPE
device_key_evidence: $HARDWARE_DEVICE_KEY_EVIDENCE
tpm_or_secure_element: $HARDWARE_TPM_OR_SECURE_ELEMENT
agent_wire_contract: $HARDWARE_AGENT_WIRE_CONTRACT
broker_verifier: $HARDWARE_BROKER_VERIFIER
root_policy: $HARDWARE_ROOT_POLICY
field_evidence: $HARDWARE_FIELD_EVIDENCE
positive_matrix: $HARDWARE_POSITIVE_MATRIX
negative_matrix: $HARDWARE_NEGATIVE_MATRIX
owner_approved_by: $OWNER_APPROVED_BY
approved_at: $APPROVED_AT
EOF
else
  cat >"$MARKER_OUT" <<EOF
F22_6_B1_4_RISK_ACCEPTANCE: v1
risk_scope: $RISK_SCOPE
accepted_gap: $RISK_ACCEPTED_GAP
compensating_controls: $RISK_COMPENSATING_CONTROLS
forbidden_claims: $RISK_FORBIDDEN_CLAIMS
owner_approved_by: $OWNER_APPROVED_BY
approved_at: $APPROVED_AT
expires_at: $EXPIRES_AT
EOF
fi

printf 'marker=%s\n' "$MARKER_OUT"
printf 'mode=%s\n' "$MODE"
printf 'owner_approved_by=%s\n' "$OWNER_APPROVED_BY"
printf 'approved_at=%s\n' "$APPROVED_AT"
if [ "$MODE" = "risk" ]; then
  printf 'expires_at=%s\n' "$EXPIRES_AT"
fi
