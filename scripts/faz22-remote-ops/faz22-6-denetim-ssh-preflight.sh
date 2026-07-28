#!/usr/bin/env bash
# Faz 22.6 #1580 Denetim PC SSH/GUI preflight.
#
# This is a narrow readiness check for the attended VIEW_ONLY smoke. It proves
# that the self-hosted runner can authenticate to the Denetim PC with the
# runner-local public-key identity and, when requested, that Windows reports an
# active GUI session. It never opens a remote-bridge session and never writes an
# acceptance marker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_DENETIM_SSH_IDENTITY="${REPO_ROOT}/../.faz24-i3-ssh/faz24-i3-denetim_ed25519"
DEFAULT_DENETIM_SSH_CONFIG="${DEFAULT_DENETIM_SSH_CONFIG:-/home/aiadmin/.ssh/config}"
DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-svc-denetim-agent@10.99.0.2}"
DENETIM_SSH_OPTS="${DENETIM_SSH_OPTS:--i ${DEFAULT_DENETIM_SSH_IDENTITY} -o IdentitiesOnly=yes}"
EXPECTED_DENETIM_SSH_HOSTNAME="${EXPECTED_DENETIM_SSH_HOSTNAME:-10.9.161.202}"
if [[ "$DENETIM_SSH_OPTS" == "__SSH_CONFIG__" ]]; then
  DENETIM_SSH_OPTS="-F ${DEFAULT_DENETIM_SSH_CONFIG}"
fi
REQUIRE_ACTIVE_GUI="${REQUIRE_ACTIVE_GUI:-1}"
EVIDENCE_DIR="${EVIDENCE_DIR:-/tmp/faz22-6-denetim-ssh-preflight-${GITHUB_RUN_ID:-manual}}"
SUMMARY_FILE="${EVIDENCE_DIR}/summary.json"

status="no-go"
reason="not-run"
ssh_failure_class=""
whoami_rc=""
hostname_rc=""
query_user_rc=""
qwinsta_rc=""
active_gui_detected="false"
identity_public_fingerprint=""
identity_public_sha256=""

usage() {
  cat <<'EOF'
Usage:
  faz22-6-denetim-ssh-preflight.sh

Environment:
  DENETIM_SSH_TARGET=svc-denetim-agent@10.99.0.2
  DENETIM_SSH_OPTS="-i ../.faz24-i3-ssh/faz24-i3-denetim_ed25519 -o IdentitiesOnly=yes"
  DENETIM_SSH_OPTS=__SSH_CONFIG__ with DENETIM_SSH_TARGET=denetim-pc
    Uses /home/aiadmin/.ssh/config on the self-hosted aiserver runner.
  EXPECTED_DENETIM_SSH_HOSTNAME=10.9.161.202
  REQUIRE_ACTIVE_GUI=1
  EVIDENCE_DIR=/tmp/faz22-6-denetim-ssh-preflight-<run>

Boundary:
  Checks SSH public-key auth and optional active Windows GUI state only. It does
  not start VIEW_ONLY, does not write #1580, and does not carry KVKK/legal
  signoff.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "denetim-ssh-preflight: missing command: $1" >&2
    exit 2
  }
}

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    shasum -a 256 "$path" | awk '{print $1}'
  fi
}

sha256_text_prefix() {
  local value="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$value" | sha256sum | awk '{print substr($1,1,16)}'
  else
    printf '%s' "$value" | shasum -a 256 | awk '{print substr($1,1,16)}'
  fi
}

sanitize_stderr() {
  sed -E \
    -e 's/[A-Za-z0-9._%+-]+@[0-9A-Za-z._:-]+/<ssh-target>/g' \
    -e 's/[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+/<ip>/g'
}

classify_ssh_failure() {
  local err_file="$1"
  if grep -Eiq 'Permission denied.*publickey|publickey.*Permission denied' "$err_file"; then
    printf 'ssh-auth-publickey'
  elif grep -Eiq 'Operation timed out|Connection timed out|timed out' "$err_file"; then
    printf 'ssh-connect-timeout'
  elif grep -Eiq 'Connection refused' "$err_file"; then
    printf 'ssh-connect-refused'
  elif grep -Eiq 'Could not resolve hostname|Name or service not known|nodename nor servname' "$err_file"; then
    printf 'ssh-target-resolve-failed'
  elif grep -Eiq 'Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED' "$err_file"; then
    printf 'ssh-hostkey-verification-failed'
  else
    printf 'ssh-command-failed'
  fi
}

write_summary() {
  local target_hash
  target_hash="$(sha256_text_prefix "$DENETIM_SSH_TARGET")"
  jq -n \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg targetHash "$target_hash" \
    --arg sshFailureClass "$ssh_failure_class" \
    --arg whoamiRc "$whoami_rc" \
    --arg hostnameRc "$hostname_rc" \
    --arg queryUserRc "$query_user_rc" \
    --arg qwinstaRc "$qwinsta_rc" \
    --arg identityFingerprint "$identity_public_fingerprint" \
    --arg identityPublicSha256 "$identity_public_sha256" \
    --arg requireActiveGui "$REQUIRE_ACTIVE_GUI" \
    --argjson activeGuiDetected "$active_gui_detected" \
    '{
      schemaVersion: "faz22.6-denetim-ssh-preflight-v1",
      status: $status,
      reason: $reason,
      denetimTargetSha256Prefix: $targetHash,
      sshFailureClass: $sshFailureClass,
      commandExit: {
        whoami: $whoamiRc,
        hostname: $hostnameRc,
        queryUser: $queryUserRc,
        qwinsta: $qwinstaRc
      },
      requireActiveGui: ($requireActiveGui == "1"),
      activeGuiDetected: $activeGuiDetected,
      runnerIdentity: {
        publicFingerprint: $identityFingerprint,
        publicKeySha256: $identityPublicSha256
      },
      evidenceHygiene: {
        rawGuiOutputRetained: false,
        privateKeyLogged: false,
        rawSecretLogged: false
      },
      boundary: "Denetim PC SSH/GUI preflight only; not VIEW_ONLY evidence, not #1580 marker, not KVKK/legal signoff"
    }' > "$SUMMARY_FILE"
}

write_sha256sums() {
  (
    cd "$EVIDENCE_DIR"
    rm -f SHA256SUMS
    if command -v sha256sum >/dev/null 2>&1; then
      find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
      sha256sum -c SHA256SUMS >/dev/null
    else
      find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS
      shasum -a 256 -c SHA256SUMS >/dev/null
    fi
  )
}

fail_preflight() {
  reason="$1"
  status="no-go"
  write_summary
  write_sha256sums
  printf 'NO_GO %s evidence_dir=%s\n' "$reason" "$EVIDENCE_DIR" >&2
  exit 1
}

run_ssh_capture() {
  local name="$1"
  shift
  local out_file="${EVIDENCE_DIR}/${name}.out.tmp"
  local err_file="${EVIDENCE_DIR}/${name}.stderr"
  local redacted_err="${EVIDENCE_DIR}/${name}.stderr.redacted"
  # shellcheck disable=SC2206
  local opts=( $DENETIM_SSH_OPTS )

  set +e
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
    "${opts[@]}" "$DENETIM_SSH_TARGET" "$@" > "$out_file" 2> "$err_file"
  local rc=$?
  set -e

  sanitize_stderr < "$err_file" > "$redacted_err"
  rm -f "$err_file"
  printf '%s' "$rc" > "${EVIDENCE_DIR}/${name}.rc"
  printf '%s' "$rc"
}

validate_inputs() {
  case "$REQUIRE_ACTIVE_GUI" in
    0|1) ;;
    *) fail_preflight "require-active-gui-invalid" ;;
  esac

  case "$DENETIM_SSH_TARGET" in
    *$'\n'*|*$'\r'*|"") fail_preflight "denetim-ssh-target-invalid" ;;
  esac
  case "$DENETIM_SSH_OPTS" in
    *$'\n'*|*$'\r'*) fail_preflight "denetim-ssh-opts-invalid" ;;
  esac

  if [[ "$DENETIM_SSH_OPTS" == *"$DEFAULT_DENETIM_SSH_IDENTITY"* && ! -r "$DEFAULT_DENETIM_SSH_IDENTITY" ]]; then
    fail_preflight "denetim-ssh-key-not-readable"
  fi

  if [[ "$DENETIM_SSH_TARGET" == "denetim-pc" && "$DENETIM_SSH_OPTS" == *"$DEFAULT_DENETIM_SSH_CONFIG"* ]]; then
    local ssh_config resolved_host resolved_user identity_file
    # shellcheck disable=SC2206
    local opts=( $DENETIM_SSH_OPTS )
    [[ -r "$DEFAULT_DENETIM_SSH_CONFIG" ]] || fail_preflight "denetim-ssh-config-not-readable"
    ssh_config="$(ssh "${opts[@]}" -G "$DENETIM_SSH_TARGET" 2>/dev/null)" \
      || fail_preflight "denetim-ssh-alias-config-unreadable"
    resolved_host="$(awk 'tolower($1) == "hostname" { print $2; exit }' <<<"$ssh_config")"
    resolved_user="$(awk 'tolower($1) == "user" { print $2; exit }' <<<"$ssh_config")"
    identity_file="$(awk 'tolower($1) == "identityfile" { print $2; exit }' <<<"$ssh_config")"

    [[ "$resolved_host" == "$EXPECTED_DENETIM_SSH_HOSTNAME" ]] \
      || fail_preflight "denetim-ssh-alias-missing-hostname"
    [[ "$resolved_user" == "denetimpc" ]] || fail_preflight "denetim-ssh-alias-missing-user"
    [[ "$identity_file" == *"id_denetim"* ]] || fail_preflight "denetim-ssh-alias-missing-identity"
  fi
}

load_identity_public_metadata() {
  local identity_file="$DEFAULT_DENETIM_SSH_IDENTITY"
  if [[ "$DENETIM_SSH_TARGET" == "denetim-pc" && "$DENETIM_SSH_OPTS" == *"$DEFAULT_DENETIM_SSH_CONFIG"* ]]; then
    # shellcheck disable=SC2206
    local opts=( $DENETIM_SSH_OPTS )
    identity_file="$(ssh "${opts[@]}" -G "$DENETIM_SSH_TARGET" 2>/dev/null | awk 'tolower($1) == "identityfile" { print $2; exit }' || true)"
    identity_file="${identity_file/#\~/$HOME}"
  fi

  if [[ -r "$identity_file" ]] && command -v ssh-keygen >/dev/null 2>&1; then
    local pub_file="${EVIDENCE_DIR}/runner-identity.pub"
    ssh-keygen -y -f "$identity_file" > "$pub_file" 2>/dev/null || return
    identity_public_sha256="$(sha256_file "$pub_file")"
    identity_public_fingerprint="$(ssh-keygen -lf "$pub_file" 2>/dev/null | awk '{print $2}' || true)"
  fi
}

main() {
  need_cmd ssh
  need_cmd jq
  need_cmd grep
  need_cmd awk
  mkdir -p "$EVIDENCE_DIR"
  validate_inputs
  load_identity_public_metadata

  whoami_rc="$(run_ssh_capture whoami whoami)"
  if [[ "$whoami_rc" != "0" ]]; then
    ssh_failure_class="$(classify_ssh_failure "${EVIDENCE_DIR}/whoami.stderr.redacted")"
    fail_preflight "$ssh_failure_class"
  fi
  rm -f "${EVIDENCE_DIR}/whoami.out.tmp"

  hostname_rc="$(run_ssh_capture hostname hostname)"
  if [[ "$hostname_rc" != "0" ]]; then
    ssh_failure_class="$(classify_ssh_failure "${EVIDENCE_DIR}/hostname.stderr.redacted")"
    fail_preflight "$ssh_failure_class"
  fi
  rm -f "${EVIDENCE_DIR}/hostname.out.tmp"

  query_user_rc="$(run_ssh_capture query-user 'query user')"
  query_out="${EVIDENCE_DIR}/query-user.out.tmp"
  qwinsta_rc="$(run_ssh_capture qwinsta qwinsta)"
  qwinsta_out="${EVIDENCE_DIR}/qwinsta.out.tmp"

  if grep -Eiq '\bActive\b' "$query_out" "$qwinsta_out" 2>/dev/null; then
    active_gui_detected="true"
  fi

  {
    printf 'query_user_rc=%s\n' "$query_user_rc"
    printf 'qwinsta_rc=%s\n' "$qwinsta_rc"
    printf 'active_gui_detected=%s\n' "$active_gui_detected"
    printf 'raw_gui_output_retained=false\n'
  } > "${EVIDENCE_DIR}/gui-session.redacted.txt"
  rm -f "$query_out" "$qwinsta_out"

  if [[ "$REQUIRE_ACTIVE_GUI" == "1" ]]; then
    if [[ "$query_user_rc" != "0" && "$qwinsta_rc" != "0" ]]; then
      ssh_failure_class="windows-gui-query-failed"
      fail_preflight "denetim-gui-session-check-failed"
    fi
    if [[ "$active_gui_detected" != "true" ]]; then
      fail_preflight "denetim-gui-session-not-active"
    fi
  fi

  status="pass"
  reason="denetim-ssh-publickey-and-gui-preflight-pass"
  write_summary
  write_sha256sums
  printf 'PASS denetim_ssh_preflight evidence_dir=%s\n' "$EVIDENCE_DIR"
}

main "$@"
