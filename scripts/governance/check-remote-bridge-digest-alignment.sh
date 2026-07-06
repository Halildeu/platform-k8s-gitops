#!/usr/bin/env bash
# Faz 22.6 durable re-drift guard (Codex 019f008a Q6 #2031; issue #2067 verdict C
# Codex 019f0733).
#
# Same-image pilot topology: the remote-bridge activation overlays run the SAME
# endpoint-admin-service image as the primary test overlay. The completion-audit
# REMOTE_BRIDGE_LIVE gate DERIVES its expected digest from the rendered overlay
# (single source of truth, no hardcoded literal — issue #2067), and requires the
# live deployments to share that one digest. The #548 device-key broker also
# needs the same image line so strong-attestation evidence does not execute stale
# backend bytecode. A PR that bumps the PRIMARY test-overlay endpoint-admin
# digest without also bumping bridge activation overlays re-drifts them and
# re-blocks the gate/evidence path at runtime (proven live:
# 3015656f->5eff536b drifted within an hour of PR #2030). This guard asserts the
# two RENDERED endpoint-admin-service digests are EQUAL at PR time, so the drift
# is caught before it ships. Fail-closed.
#
# Because the audit + this guard both derive the expected digest from the overlay
# via the SHARED lib below, there is no longer a separate hardcoded "expected
# digest" copy to drift (the old EXPECTED_REMOTE_BRIDGE_DIGEST literal is gone) —
# this guard is the canonical PR-time enforcement of the single-source invariant.
#
# Companion: the testai auto-sync co-bumps the bridge whenever it bumps the
# primary endpoint-admin digest (scripts/automation/sync-test-overlay.sh #2031/#548),
# so auto-sync PRs stay aligned and pass this guard. This guard catches any manual
# PR (or future regression) that bumps one side without the other.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# shellcheck source=scripts/governance/lib-remote-bridge-digest.sh
source "$REPO_ROOT/scripts/governance/lib-remote-bridge-digest.sh"

if [ -z "$(rbd_render_cmd || true)" ]; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=unknown reason=missing-kustomize-and-kubectl" >&2
  exit 2
fi

primary=""; prc=0
primary="$(rbd_overlay_digest "$RBD_PRIMARY_OVERLAY")" || prc=$?
if [ "$prc" != 0 ]; then
  case "$prc" in
    2) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=primary-digest-not-singular overlay=$RBD_PRIMARY_OVERLAY" ;;
    *) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=primary-overlay-render-failed overlay=$RBD_PRIMARY_OVERLAY" ;;
  esac
  exit 1
fi

bridge=""; brc=0
bridge="$(rbd_overlay_digest "$RBD_BRIDGE_OVERLAY")" || brc=$?
if [ "$brc" != 0 ]; then
  case "$brc" in
    2) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=bridge-digest-not-singular overlay=$RBD_BRIDGE_OVERLAY" ;;
    *) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=bridge-overlay-render-failed overlay=$RBD_BRIDGE_OVERLAY" ;;
  esac
  exit 1
fi

device_key=""; dkc=0
device_key="$(rbd_overlay_digest "$RBD_DEVICE_KEY_BRIDGE_OVERLAY")" || dkc=$?
if [ "$dkc" != 0 ]; then
  case "$dkc" in
    2) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=device-key-digest-not-singular overlay=$RBD_DEVICE_KEY_BRIDGE_OVERLAY" ;;
    *) echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=device-key-overlay-render-failed overlay=$RBD_DEVICE_KEY_BRIDGE_OVERLAY" ;;
  esac
  exit 1
fi

if [ "$primary" != "$bridge" ] || [ "$primary" != "$device_key" ]; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=digest-drift"
  echo "  primary    ($RBD_PRIMARY_OVERLAY): $primary"
  echo "  bridge     ($RBD_BRIDGE_OVERLAY): $bridge"
  echo "  device-key ($RBD_DEVICE_KEY_BRIDGE_OVERLAY): $device_key"
  echo "  Same-image pilot topology requires these to match. A bump of the endpoint-admin"
  echo "  digest must update the test overlay primary AND both bridge activation overlays"
  echo "  (the auto-sync does this automatically; a manual PR must too) else completion-audit"
  echo "  REMOTE_BRIDGE_LIVE or #548 device-key evidence re-blocks (Codex 019f008a Q6 / #2031 / #2067 / #548)."
  exit 1
fi

echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=pass digest=$primary"
