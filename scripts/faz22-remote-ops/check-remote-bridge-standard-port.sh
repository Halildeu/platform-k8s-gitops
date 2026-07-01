#!/usr/bin/env bash
# Fail-fast guard for the Faz 22.6 remote-bridge product-channel entrypoint.
#
# EndpointAgent acceptance traffic must use the shared product SNI endpoint:
#
#   remote-bridge-mtls.testai.acik.com:443
#
# Do not reintroduce endpoint-specific inbound ports, ad-hoc forwarders, or the
# abandoned :9446 path into active runbooks, manifests, bootstrap packets, or
# acceptance verifiers.

set -euo pipefail

REMOTE_BRIDGE_HOST="${REMOTE_BRIDGE_HOST:-remote-bridge-mtls.testai.acik.com}"
REMOTE_BRIDGE_PORT="${REMOTE_BRIDGE_PORT:-443}"

default_paths=(
  .github/workflows
  config
  docs/faz-22-software-deployment-plan.md
  docs/runbooks
  docs/state/current-state.md
  kustomize
  scripts/faz22-remote-ops
  tests/faz22
  tests/faz22_remote_ops
)

paths=("$@")
if [ "${#paths[@]}" -eq 0 ]; then
  paths=("${default_paths[@]}")
fi

existing_paths=()
for path in "${paths[@]}"; do
  if [ -e "$path" ]; then
    existing_paths+=("$path")
  fi
done

if [ "${#existing_paths[@]}" -eq 0 ]; then
  echo "REMOTE_BRIDGE_STANDARD_PORT=blocked reason=no-scan-paths"
  exit 1
fi

tmp_matches="$(mktemp)"
trap 'rm -f "$tmp_matches"' EXIT

grep -RInE \
  --exclude='check-remote-bridge-standard-port.sh' \
  --exclude='test_remote_bridge_standard_port.sh' \
  "${REMOTE_BRIDGE_HOST//./\\.}:[0-9]+|9446|BROKER_ADDR|REMOTE_BRIDGE_BROKER_ADDR|forwarder|socat|ufw allow" \
  "${existing_paths[@]}" \
  >"$tmp_matches" || true

awk -v host="$REMOTE_BRIDGE_HOST" -v expected_port="$REMOTE_BRIDGE_PORT" '
  BEGIN {
    status = 0
    explicit_host_port = host ":[0-9]+"
  }

  {
    line = $0
    text = $0
    sub(/^[^:]+:[0-9]+:/, "", text)
  }

  text ~ explicit_host_port {
    while (match(text, explicit_host_port)) {
      hit = substr(text, RSTART, RLENGTH)
      port = hit
      sub("^" host ":", "", port)
      if (port != expected_port) {
        print "REMOTE_BRIDGE_STANDARD_PORT_VIOLATION explicit-host-port " line
        status = 1
      }
      text = substr(text, RSTART + RLENGTH)
    }
  }

  text ~ /9446/ && text ~ /(remote-bridge|REMOTE_BRIDGE|BROKER_ADDR|EndpointAgent|AgentPC|device-key|endpoint-admin-remote-bridge|socat|forwarder|ufw allow)/ {
    print "REMOTE_BRIDGE_STANDARD_PORT_VIOLATION abandoned-9446-path " line
    status = 1
  }

  text ~ /(socat|forwarder|ufw allow)/ && text ~ /(remote-bridge|REMOTE_BRIDGE|endpoint-admin-remote-bridge|AgentPC|device-key)/ {
    print "REMOTE_BRIDGE_STANDARD_PORT_REVIEW ad-hoc-forwarder-or-firewall " line
    status = 1
  }

  END {
    exit status
  }
' "$tmp_matches"

echo "REMOTE_BRIDGE_STANDARD_PORT=pass host=${REMOTE_BRIDGE_HOST} port=${REMOTE_BRIDGE_PORT}"
