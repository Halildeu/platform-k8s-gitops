#!/usr/bin/env bash
# Faz 22.6 durable re-drift guard (Codex 019f008a Q6, issue #2031).
#
# Same-image pilot topology: the remote-bridge activation overlay runs the SAME
# endpoint-admin-service image as the primary test overlay. The completion-audit
# REMOTE_BRIDGE_LIVE gate requires both live deployments to share ONE digest
# (digest_hits>=4). A PR that bumps the PRIMARY test-overlay endpoint-admin digest
# without also bumping the bridge activation overlay re-drifts them and re-blocks
# the gate at runtime (proven live: 3015656f->5eff536b drifted within an hour of
# PR #2030). This guard asserts the two RENDERED endpoint-admin-service digests are
# EQUAL at PR time, so the drift is caught before it ships. Fail-closed.
#
# Why a guard alone is the right durable fix (Codex 019f008a AGREE, 2026-06-26):
# the testai auto-sync does NOT touch endpoint-admin — it is excluded in all three
# places (deploy-backend-testai.yml SERVICES array + REQUIRED_SVCS, and
# apply-test-overlay-digests.py SYNC_SERVICES rejects it fail-closed). The overlay
# endpoint-admin digest is therefore maintained ONLY by deliberate manual PRs
# (e.g. #2032), so this guard enforces real PR-authoring discipline and never
# blocks the auto-sync bot (which leaves the endpoint-admin line untouched).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

IMG="ghcr.io/halildeu/platform-backend-endpoint-admin-service"
PRIMARY_OVERLAY="kustomize/overlays/test"
BRIDGE_OVERLAY="kustomize/overlays/test/activation/endpoint-admin-remote-bridge"

# Prefer standalone kustomize (the CI image, imranismail/setup-kustomize); fall back to
# kubectl kustomize (local/cluster hosts). Both render the same overlay bytes.
if command -v kustomize >/dev/null 2>&1; then
  KUSTOMIZE_RENDER=(kustomize build)
elif command -v kubectl >/dev/null 2>&1; then
  KUSTOMIZE_RENDER=(kubectl kustomize)
else
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=unknown reason=missing-kustomize-and-kubectl" >&2
  exit 2
fi

extract_digest() {
  # $1 = overlay path. Echoes the unique endpoint-admin-service image digest(s).
  # Returns non-zero if the overlay does not render.
  local overlay="$1" rendered
  if ! rendered="$("${KUSTOMIZE_RENDER[@]}" "$overlay" 2>/dev/null)"; then
    return 1
  fi
  printf '%s\n' "$rendered" | grep -oE "${IMG}@sha256:[0-9a-f]{64}" | sort -u
}

if ! primary="$(extract_digest "$PRIMARY_OVERLAY")"; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=primary-overlay-render-failed overlay=$PRIMARY_OVERLAY"
  exit 1
fi
if ! bridge="$(extract_digest "$BRIDGE_OVERLAY")"; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=bridge-overlay-render-failed overlay=$BRIDGE_OVERLAY"
  exit 1
fi

primary_count="$(printf '%s\n' "$primary" | grep -c . || true)"
bridge_count="$(printf '%s\n' "$bridge" | grep -c . || true)"

if [ "$primary_count" != "1" ]; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=primary-digest-not-singular count=$primary_count"
  printf '  %s\n' "$primary"
  exit 1
fi
if [ "$bridge_count" != "1" ]; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=bridge-digest-not-singular count=$bridge_count"
  printf '  %s\n' "$bridge"
  exit 1
fi

if [ "$primary" != "$bridge" ]; then
  echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=digest-drift"
  echo "  primary ($PRIMARY_OVERLAY): $primary"
  echo "  bridge  ($BRIDGE_OVERLAY): $bridge"
  echo "  Same-image pilot topology requires these to match. A manual endpoint-admin"
  echo "  digest bump must update BOTH the test overlay primary AND the bridge activation"
  echo "  overlay, else completion-audit REMOTE_BRIDGE_LIVE re-blocks (Codex 019f008a Q6 / #2031)."
  exit 1
fi

echo "REMOTE_BRIDGE_DIGEST_ALIGNMENT=pass digest=$primary"
