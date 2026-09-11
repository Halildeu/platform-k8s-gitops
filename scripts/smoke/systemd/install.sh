#!/usr/bin/env bash
# scripts/smoke/systemd/install.sh — install the D29 smoke + ledger timers on the
# host that holds the kube contexts (gitops#3677).
#
# The unit files in this directory are written for one host layout
# (User=halil, /home/halil/platform/platform-k8s-gitops). This installer
# renders them for the current user and checkout instead of hand-editing
# copies, so a host migration (staging-sw → aiserver, 2026) does not silently
# leave the pipeline uninstalled again.
#
# Usage (on the host, from the gitops checkout):
#   bash scripts/smoke/systemd/install.sh            # install + enable timers
#   bash scripts/smoke/systemd/install.sh --check    # preflight only
#
# Preflight (fail-closed): gh authenticated (ledger PRs), jq, kubectl with the
# k3d-test context, and the checkout's origin reachable.
set -euo pipefail

CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GITOPS_ROOT="$(cd "$HERE/../../.." && pwd)"
RUN_USER="$(id -un)"
UNITS=(smoke-test.service smoke-test.timer smoke-prod.service smoke-prod.timer)

fail=0
need() { command -v "$1" >/dev/null 2>&1 || { echo "MISSING: $1"; fail=1; }; }
need gh; need jq; need kubectl; need git; need python3
if command -v gh >/dev/null 2>&1 && ! gh auth status >/dev/null 2>&1; then
  echo "MISSING: gh is not authenticated (ledger-mark-verified.sh opens PRs with gh)"; fail=1
fi
kubectl --context k3d-test get ns platform-test >/dev/null 2>&1 || { echo "MISSING: kube context k3d-test / namespace platform-test"; fail=1; }
git -C "$GITOPS_ROOT" ls-remote --exit-code origin main >/dev/null 2>&1 || { echo "MISSING: origin main not reachable from $GITOPS_ROOT"; fail=1; }
echo "preflight: user=$RUN_USER root=$GITOPS_ROOT gh=$(command -v gh || echo -) status=$([[ $fail -eq 0 ]] && echo OK || echo FAIL)"
[[ $fail -eq 0 ]] || exit 2
[[ $CHECK_ONLY -eq 1 ]] && exit 0

GH_BIN_DIR="$(dirname "$(command -v gh)")"
tmp=$(mktemp -d)
for u in "${UNITS[@]}"; do
  sed -e "s#/home/halil/platform/platform-k8s-gitops#${GITOPS_ROOT}#g" \
      -e "s#^User=halil\$#User=${RUN_USER}#" \
      "$HERE/$u" > "$tmp/$u"
  if [[ "$u" == *.service ]]; then
    # ledger entries are derived from GHCR tags when CI did not create them
    # (gitops#3677); gh must be on the unit's PATH.
    sed -i.bak -e "/^\[Service\]/a\\
Environment=LEDGER_AUTOGENERATE=1\\
Environment=PATH=${GH_BIN_DIR}:/usr/local/bin:/usr/bin:/bin\\
Environment=HOME=${HOME}" "$tmp/$u"
    rm -f "$tmp/$u.bak"
  fi
done
sudo install -m 0644 "$tmp"/smoke-*.service "$tmp"/smoke-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smoke-test.timer smoke-prod.timer
sudo touch /var/log/platform-smoke-test.log /var/log/platform-smoke-prod.log
sudo chown "$RUN_USER" /var/log/platform-smoke-test.log /var/log/platform-smoke-prod.log
systemctl list-timers --all --no-pager | grep -E "smoke-(test|prod)" || true
echo "installed: ${UNITS[*]} (user=$RUN_USER root=$GITOPS_ROOT)"
