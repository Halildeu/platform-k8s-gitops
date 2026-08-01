#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SOURCE_DIR
readonly TLS_DIR="/etc/platform/meeting-ai-gateway/tls"
readonly LOG_DIR="/var/log/platform/meeting-ai-gateway"
readonly ACCESS_LOG="${LOG_DIR}/access.json"

die() {
  printf 'meeting-ai gateway install: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || die "root is required"
command -v caddy >/dev/null 2>&1 || die "install the package-managed Caddy binary first"
command -v systemd-analyze >/dev/null 2>&1 || die "systemd is required"
getent passwd caddy >/dev/null || die "the package-managed caddy user does not exist"

install -d -o root -g caddy -m 0750 /etc/platform/meeting-ai-gateway "${TLS_DIR}"
install -d -o caddy -g caddy -m 0750 /run/caddy "${LOG_DIR}"
if [[ -L "${ACCESS_LOG}" || ( -e "${ACCESS_LOG}" && ! -f "${ACCESS_LOG}" ) ]]; then
  die "access log must be a regular non-symlink file"
fi
if [[ ! -e "${ACCESS_LOG}" ]]; then
  install -o caddy -g caddy -m 0640 /dev/null "${ACCESS_LOG}"
else
  chown caddy:caddy "${ACCESS_LOG}"
  chmod 0640 "${ACCESS_LOG}"
fi
install -d -o root -g root -m 0755 /usr/local/libexec/platform
mkdir -p /var/lib/node_exporter
chmod 0755 /var/lib/node_exporter
if [[ ! -e /var/lib/node_exporter/meeting_ai_gateway.prom ]]; then
  install -o root -g root -m 0644 /dev/null \
    /var/lib/node_exporter/meeting_ai_gateway.prom
  printf '%s\n' \
    '# HELP meeting_ai_gateway_rotation_last_attempt_timestamp_seconds Last certificate rotation attempt.' \
    '# TYPE meeting_ai_gateway_rotation_last_attempt_timestamp_seconds gauge' \
    'meeting_ai_gateway_rotation_last_attempt_timestamp_seconds 0' \
    '# HELP meeting_ai_gateway_rotation_last_success_timestamp_seconds Last successful certificate activation.' \
    '# TYPE meeting_ai_gateway_rotation_last_success_timestamp_seconds gauge' \
    'meeting_ai_gateway_rotation_last_success_timestamp_seconds 0' \
    '# HELP meeting_ai_gateway_rotation_last_run_success Whether the latest rotation attempt succeeded.' \
    '# TYPE meeting_ai_gateway_rotation_last_run_success gauge' \
    'meeting_ai_gateway_rotation_last_run_success 0' \
    '# HELP meeting_ai_gateway_certificate_not_after_timestamp_seconds Active server certificate expiry.' \
    '# TYPE meeting_ai_gateway_certificate_not_after_timestamp_seconds gauge' \
    'meeting_ai_gateway_certificate_not_after_timestamp_seconds 0' \
    >/var/lib/node_exporter/meeting_ai_gateway.prom
fi

install -o root -g caddy -m 0640 "${SOURCE_DIR}/Caddyfile" \
  /etc/caddy/meeting-ai-private.Caddyfile
install -o root -g root -m 0755 "${SOURCE_DIR}/firewall.sh" \
  /usr/local/libexec/platform/meeting-ai-gateway-firewall
install -o root -g root -m 0750 "${SOURCE_DIR}/rotate-server-cert.sh" \
  /usr/local/libexec/platform/meeting-ai-gateway-rotate-server-cert

for unit in \
  meeting-ai-gateway-firewall.service \
  meeting-ai-private-gateway.service \
  meeting-ai-server-cert-rotation.service \
  meeting-ai-server-cert-rotation.timer; do
  install -o root -g root -m 0644 "${SOURCE_DIR}/${unit}" "/etc/systemd/system/${unit}"
done

systemd-analyze verify \
  /etc/systemd/system/meeting-ai-gateway-firewall.service \
  /etc/systemd/system/meeting-ai-private-gateway.service \
  /etc/systemd/system/meeting-ai-server-cert-rotation.service \
  /etc/systemd/system/meeting-ai-server-cert-rotation.timer
systemctl daemon-reload

printf '%s\n' \
  'Meeting-AI gateway files installed but not enabled.' \
  'Seed dedicated PKI/client secret and install server.crt, server.key, client-ca.crt first.' \
  'Then run the activation and negative probes in RB-faz24-meeting-ai-private-gateway.md.'
