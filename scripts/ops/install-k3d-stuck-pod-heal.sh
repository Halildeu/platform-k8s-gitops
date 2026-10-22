#!/usr/bin/env bash
# #3888 — install the k3d stuck-pod self-heal timer on aiserver.
# Usage: scripts/ops/install-k3d-stuck-pod-heal.sh [--apply]
#   default: print what would change; --apply: install + enable + run once (dry-run first).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH=(ssh -o ConnectTimeout=15 -J "${JUMP_HOST:-staging-sw-legacy}" "${TARGET_HOST:-aiserver}")
SCRIPT="$ROOT/scripts/ops/k3d_stuck_pod_heal.py"
UNIT="$ROOT/scripts/ops/systemd/k3d-stuck-pod-heal.service"
TIMER="$ROOT/scripts/ops/systemd/k3d-stuck-pod-heal.timer"

python3 -m py_compile "$SCRIPT"
if [[ "${1:-}" != "--apply" ]]; then
  echo "would install: /usr/local/lib/platform-ops/k3d_stuck_pod_heal.py, /etc/systemd/system/k3d-stuck-pod-heal.{service,timer}"
  exit 0
fi

payload=$(COPYFILE_DISABLE=1 tar --no-xattrs -C "$ROOT" -czf - scripts/ops/k3d_stuck_pod_heal.py \
  scripts/ops/systemd/k3d-stuck-pod-heal.service scripts/ops/systemd/k3d-stuck-pod-heal.timer | base64)
printf '%s' "$payload" | "${SSH[@]}" '
  set -euo pipefail
  d=$(mktemp -d); base64 -d | tar -xzf - -C "$d"
  sudo -n install -D -m 0755 "$d/scripts/ops/k3d_stuck_pod_heal.py" /usr/local/lib/platform-ops/k3d_stuck_pod_heal.py
  sudo -n install -m 0644 "$d/scripts/ops/systemd/k3d-stuck-pod-heal.service" /etc/systemd/system/k3d-stuck-pod-heal.service
  sudo -n install -m 0644 "$d/scripts/ops/systemd/k3d-stuck-pod-heal.timer" /etc/systemd/system/k3d-stuck-pod-heal.timer
  rm -rf "$d"
  python3 /usr/local/lib/platform-ops/k3d_stuck_pod_heal.py   # dry-run evidence before enabling
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable --now k3d-stuck-pod-heal.timer
  systemctl list-timers k3d-stuck-pod-heal.timer --no-pager
'
