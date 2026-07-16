#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/verify-view-only-viewer-target.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "inspect" ]]; then exit 0; fi
cat >/dev/null
printf '%s\n' "${MOCK_DB_COUNTS:-1|1}"
EOF
cat > "$TMP/bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${MOCK_REMOTE_HOSTNAME:-SRB-AIDENETIMPC}"
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/ssh"
printf '%s\n' 'Host denetim-pc' > "$TMP/ssh-config"

common=(
  DEVICE_ID=423b6fc3-7497-4083-bd2f-5e2fe543bfe9
  DEVICE_HOSTNAME=SRB-AIDENETIMPC
  DENETIM_SSH_CONFIG="$TMP/ssh-config"
)

env PATH="$TMP/bin:$PATH" "${common[@]}" bash "$SCRIPT" | grep -Fq 'target-preflight: verified'

if env PATH="$TMP/bin:$PATH" MOCK_DB_COUNTS='0|1' "${common[@]}" bash "$SCRIPT" \
    >"$TMP/db.out" 2>"$TMP/db.err"; then
  echo "mismatched device id unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'device-id-hostname-live-trust-binding-mismatch' "$TMP/db.err"

if env PATH="$TMP/bin:$PATH" MOCK_DB_COUNTS='1|2' "${common[@]}" bash "$SCRIPT" \
    >"$TMP/duplicate.out" 2>"$TMP/duplicate.err"; then
  echo "duplicate hostname unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'device-id-hostname-live-trust-binding-mismatch' "$TMP/duplicate.err"

if env PATH="$TMP/bin:$PATH" MOCK_REMOTE_HOSTNAME=AGENTPC2 "${common[@]}" bash "$SCRIPT" \
    >"$TMP/host.out" 2>"$TMP/host.err"; then
  echo "mismatched attended endpoint hostname unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'device-hostname-does-not-match-attended-endpoint' "$TMP/host.err"

if env PATH="$TMP/bin:$PATH" "${common[@]}" DENETIM_SSH_TARGET=-oProxyCommand=bad bash "$SCRIPT" \
    >"$TMP/target.out" 2>"$TMP/target.err"; then
  echo "option-shaped SSH target unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'denetim-ssh-target-invalid' "$TMP/target.err"

if env PATH="$TMP/bin:$PATH" \
    DEVICE_ID=------------------------------------ \
    DEVICE_HOSTNAME=SRB-AIDENETIMPC \
    DENETIM_SSH_CONFIG="$TMP/ssh-config" \
    bash "$SCRIPT" >"$TMP/uuid.out" 2>"$TMP/uuid.err"; then
  echo "invalid UUID unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'device-id-invalid' "$TMP/uuid.err"

if env PATH="$TMP/bin:$PATH" \
    DEVICE_ID=423b6fc3-7497-4083-bd2f-5e2fe543bfe9 \
    DEVICE_HOSTNAME=SRB-AIDENETIMPC \
    DENETIM_SSH_CONFIG="$TMP/missing-config" \
    bash "$SCRIPT" >"$TMP/config.out" 2>"$TMP/config.err"; then
  echo "missing SSH config unexpectedly passed" >&2
  exit 1
fi
grep -Fq 'denetim-ssh-config-not-readable' "$TMP/config.err"

echo ok
