#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/completion-release-lineage.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

fake_script_dir="$tmp_dir/fake-scripts"
mkdir -p "$fake_script_dir"
SCRIPT_DIR="$fake_script_dir"

write_fake_release_lineage_audit() {
  local body="$1"
  cat >"$fake_script_dir/faz22-6-release-lineage-audit.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
$body
EOF
  chmod +x "$fake_script_dir/faz22-6-release-lineage-audit.sh"
}

run_gate() {
  local mode="${1:-local-kubectl}"
  REMOTE_BRIDGE_KUBECTL_MODE="$mode" \
    SSH_TARGET="local" \
    KUBE_CONTEXT="k3d-test" \
    KUBE_NAMESPACE="platform-test" \
    check_release_lineage_gate
}

write_fake_release_lineage_audit 'printf "%s\n" "F22_6_RELEASE_LINEAGE=pass"'
run_gate | tee "$tmp_dir/pass.out"
grep -q '^RELEASE_LINEAGE_GATE=pass mode=local-kubectl status=pass$' "$tmp_dir/pass.out"

write_fake_release_lineage_audit 'printf "%s\n" "F22_6_RELEASE_LINEAGE=bounded_pilot_pass"'
run_gate | tee "$tmp_dir/bounded.out"
grep -q '^RELEASE_LINEAGE_GATE=bounded_pilot_pass mode=local-kubectl status=bounded_pilot_pass$' "$tmp_dir/bounded.out"

write_fake_release_lineage_audit 'printf "%s\n" "F22_6_RELEASE_LINEAGE=needs_hygiene"'
set +e
run_gate >"$tmp_dir/needs-hygiene.out"
rc="$?"
set -e
[ "$rc" != "0" ] || {
  echo "expected needs_hygiene release-lineage status to block completion" >&2
  exit 1
}
grep -q '^RELEASE_LINEAGE_GATE=blocked mode=local-kubectl status=needs_hygiene$' "$tmp_dir/needs-hygiene.out"

write_fake_release_lineage_audit 'printf "%s\n" "GITHUB_RELEASE_IMMUTABLE=pass"'
set +e
run_gate >"$tmp_dir/missing-status.out"
rc="$?"
set -e
[ "$rc" != "0" ] || {
  echo "expected missing F22_6_RELEASE_LINEAGE status to block completion" >&2
  exit 1
}
grep -q '^RELEASE_LINEAGE_GATE=blocked mode=local-kubectl reason=missing-F22_6_RELEASE_LINEAGE$' "$tmp_dir/missing-status.out"

write_fake_release_lineage_audit 'printf "%s\n" "F22_6_RELEASE_LINEAGE=pass"'
set +e
run_gate invalid-mode >"$tmp_dir/invalid-mode.out"
rc="$?"
set -e
[ "$rc" != "0" ] || {
  echo "expected invalid release-lineage kubectl mode to block completion" >&2
  exit 1
}
grep -q '^RELEASE_LINEAGE_GATE=blocked mode=invalid-mode reason=invalid-release-lineage-kubectl-mode$' "$tmp_dir/invalid-mode.out"

echo "completion-release-lineage-gate-ok"
