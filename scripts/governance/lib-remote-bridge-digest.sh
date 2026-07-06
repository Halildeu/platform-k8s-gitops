#!/usr/bin/env bash
# lib-remote-bridge-digest.sh — SOURCED helper (no `set -e`; the caller owns it).
#
# Single source of truth for the Faz 22.6 remote-bridge "expected" endpoint-admin
# digest (issue #2067, Codex 019f0733 verdict C): the digest is DERIVED by
# rendering the kustomize overlay, never hardcoded. Same-image pilot topology
# means the primary test overlay, the remote-bridge activation overlay, and the
# #548 device-key activation overlay must render the SAME endpoint-admin-service
# image digest. This lib is shared by:
#   - scripts/governance/check-remote-bridge-digest-alignment.sh (PR-time guard)
#   - scripts/faz22-remote-ops/faz22-6-completion-audit.sh (REMOTE_BRIDGE_LIVE)
# so both derive the expected digest the same way and cannot drift from each
# other or from the overlay.

RBD_IMG="${RBD_IMG:-ghcr.io/halildeu/platform-backend-endpoint-admin-service}"
RBD_PRIMARY_OVERLAY="${RBD_PRIMARY_OVERLAY:-kustomize/overlays/test}"
RBD_BRIDGE_OVERLAY="${RBD_BRIDGE_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge}"
RBD_DEVICE_KEY_BRIDGE_OVERLAY="${RBD_DEVICE_KEY_BRIDGE_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key}"

rbd_render_cmd() {
  # Echo the render command words (standalone kustomize preferred — the CI image;
  # kubectl kustomize is the local/runner fallback). Both render identical bytes.
  # Returns 1 if neither tool is present.
  if command -v kustomize >/dev/null 2>&1; then
    printf 'kustomize build'
    return 0
  fi
  if command -v kubectl >/dev/null 2>&1; then
    printf 'kubectl kustomize'
    return 0
  fi
  return 1
}

rbd_overlay_digest() {
  # rbd_overlay_digest <overlay-path>
  # Render the overlay and print the SINGLE endpoint-admin-service image digest
  # (the container `image:` field; kustomize's images transformer is the only
  # producer of this IMG@sha256, so the singular-count assertion pins it to the
  # endpoint-admin container without needing yq).
  # Exit: 0 + digest on stdout | 1 render-failed | 2 digest-not-singular | 3 no-render-tool.
  local overlay="$1" render rendered digests count
  render="$(rbd_render_cmd)" || return 3
  # shellcheck disable=SC2086 # $render is a deliberate 2-word command (kustomize build | kubectl kustomize).
  rendered="$($render "$overlay" 2>/dev/null)" || return 1
  digests="$(printf '%s\n' "$rendered" \
    | grep -oE "image: ${RBD_IMG}@sha256:[0-9a-f]{64}" \
    | sed -E 's/^image:[[:space:]]*//' \
    | sort -u)"
  count="$(printf '%s\n' "$digests" | grep -c . || true)"
  [ "$count" = "1" ] || return 2
  printf '%s\n' "$digests"
}

rbd_expected_digest() {
  # rbd_expected_digest — print the canonical remote-bridge expected digest.
  # Derived from the BRIDGE activation overlay (the bridge's own desired state)
  # AND cross-checked equal to the PRIMARY test overlay (same-image invariant).
  # Echoes the digest on success; on failure prints nothing and returns:
  #   1 bridge render/parse failed | 2 primary render/parse failed
  #   3 no-render-tool | 4 primary != bridge (drift).
  local primary bridge prc brc
  bridge="$(rbd_overlay_digest "$RBD_BRIDGE_OVERLAY")"; brc=$?
  if [ "$brc" = 3 ]; then return 3; fi
  if [ "$brc" != 0 ]; then return 1; fi
  primary="$(rbd_overlay_digest "$RBD_PRIMARY_OVERLAY")"; prc=$?
  if [ "$prc" = 3 ]; then return 3; fi
  if [ "$prc" != 0 ]; then return 2; fi
  if [ "$primary" != "$bridge" ]; then
    return 4
  fi
  printf '%s\n' "$bridge"
}
