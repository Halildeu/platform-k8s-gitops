#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/bin"
cat >"$tmp_dir/bin/ssh" <<'FAKE_SSH'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$SSH_CAPTURE"
FAKE_SSH
chmod +x "$tmp_dir/bin/ssh"

assert_capture() {
  local label="$1"
  local got=()
  while IFS= read -r line; do
    got+=("$line")
  done <"$SSH_CAPTURE"
  if [ "${#got[@]}" -ne 6 ]; then
    echo "FAIL $label: expected 6 ssh argv entries, got ${#got[@]}: ${got[*]-}" >&2
    exit 1
  fi
  [ "${got[0]}" = "-o" ] || { echo "FAIL $label: missing -o: ${got[*]}" >&2; exit 1; }
  [ "${got[1]}" = "IdentitiesOnly=yes" ] || { echo "FAIL $label: missing IdentitiesOnly: ${got[*]}" >&2; exit 1; }
  [ "${got[2]}" = "-i" ] || { echo "FAIL $label: missing -i: ${got[*]}" >&2; exit 1; }
  [ "${got[3]}" = "/tmp/faz22-test-key" ] || { echo "FAIL $label: missing identity path: ${got[*]}" >&2; exit 1; }
  [ "${got[4]}" = "staging-sw" ] || { echo "FAIL $label: missing target: ${got[*]}" >&2; exit 1; }
  [ "${got[5]}" = "hostname" ] || { echo "FAIL $label: missing remote command: ${got[*]}" >&2; exit 1; }
}

assert_empty_capture() {
  local label="$1"
  local got=()
  while IFS= read -r line; do
    got+=("$line")
  done <"$SSH_CAPTURE"
  if [ "${#got[@]}" -ne 2 ]; then
    echo "FAIL $label: expected 2 ssh argv entries, got ${#got[@]}: ${got[*]-}" >&2
    exit 1
  fi
  [ "${got[0]}" = "staging-sw" ] || { echo "FAIL $label: missing target: ${got[*]}" >&2; exit 1; }
  [ "${got[1]}" = "hostname" ] || { echo "FAIL $label: missing remote command: ${got[*]}" >&2; exit 1; }
}

export PATH="$tmp_dir/bin:$PATH"
export SSH_CAPTURE="$tmp_dir/ssh-argv.txt"
export SSH_OPTS="-o IdentitiesOnly=yes -i /tmp/faz22-test-key"

(
  cd "$ROOT"
  export F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY=1
  # shellcheck source=/dev/null
  source scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
  ssh_cmd staging-sw hostname
)
assert_capture "release-lineage"

(
  cd "$ROOT"
  export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
  # shellcheck source=/dev/null
  source scripts/faz22-remote-ops/faz22-6-completion-audit.sh
  ssh_cmd staging-sw hostname
)
assert_capture "completion"

unset SSH_OPTS

(
  cd "$ROOT"
  export F22_6_RELEASE_LINEAGE_AUDIT_SOURCE_ONLY=1
  # shellcheck source=/dev/null
  source scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
  ssh_cmd staging-sw hostname
)
assert_empty_capture "release-lineage empty SSH_OPTS"

(
  cd "$ROOT"
  export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
  # shellcheck source=/dev/null
  source scripts/faz22-remote-ops/faz22-6-completion-audit.sh
  ssh_cmd staging-sw hostname
)
assert_empty_capture "completion empty SSH_OPTS"

echo "PASS faz22 audit SSH_OPTS forwarding"
