#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/faz22-remote-ops/check-remote-bridge-standard-port.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$tmpdir/valid" "$tmpdir/invalid-host-port" "$tmpdir/invalid-forwarder" "$tmpdir/unrelated"

cat >"$tmpdir/valid/runbook.md" <<'EOF'
Use outbound-only EndpointAgent product-channel traffic through
remote-bridge-mtls.testai.acik.com:443.
EOF

cat >"$tmpdir/invalid-host-port/runbook.md" <<'EOF'
ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR=remote-bridge-mtls.testai.acik.com:9446
EOF

cat >"$tmpdir/invalid-forwarder/runbook.md" <<'EOF'
Do not add a socat forwarder for endpoint-admin-remote-bridge device-key traffic.
EOF

cat >"$tmpdir/unrelated/evidence.txt" <<'EOF'
This historical hash fragment contains 9446 but no remote bridge context.
EOF

"$SCRIPT" "$tmpdir/valid" "$tmpdir/unrelated" >/dev/null

if "$SCRIPT" "$tmpdir/invalid-host-port" >/tmp/remote-bridge-port-test.out 2>&1; then
  cat /tmp/remote-bridge-port-test.out
  echo "expected invalid host port fixture to fail" >&2
  exit 1
fi
grep -q 'REMOTE_BRIDGE_STANDARD_PORT_VIOLATION explicit-host-port' /tmp/remote-bridge-port-test.out

if "$SCRIPT" "$tmpdir/invalid-forwarder" >/tmp/remote-bridge-port-test.out 2>&1; then
  cat /tmp/remote-bridge-port-test.out
  echo "expected ad-hoc forwarder fixture to fail" >&2
  exit 1
fi
grep -q 'REMOTE_BRIDGE_STANDARD_PORT_REVIEW ad-hoc-forwarder-or-firewall' /tmp/remote-bridge-port-test.out

"$SCRIPT" >/dev/null

echo "remote-bridge-standard-port-test=pass"
