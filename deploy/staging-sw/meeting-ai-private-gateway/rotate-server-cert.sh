#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly TLS_DIR="/etc/platform/meeting-ai-gateway/tls"
readonly TOKEN_FILE="${VAULT_TOKEN_FILE:-/etc/platform/meeting-ai-gateway/vault-token}"
readonly VAULT_TRANSPORT="${VAULT_TRANSPORT:-https}"
readonly VAULT_ADDR_VALUE="${VAULT_ADDR:-https://127.0.0.1:8202}"
readonly VAULT_CACERT_FILE="${VAULT_CACERT_FILE:-/etc/platform/meeting-ai-gateway/vault-ca.crt}"
readonly VAULT_DOCKER_CONTAINER="${VAULT_DOCKER_CONTAINER:-platform-vault-test}"
readonly METRIC_FILE="${METRIC_FILE:-/var/lib/node_exporter/meeting_ai_gateway.prom}"
rotation_success=0
last_success=0
certificate_not_after=0
tmp_dir=""

die() {
  printf 'meeting-ai cert rotation: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || die "root is required"
command -v jq >/dev/null 2>&1 || die "jq is required"
command -v openssl >/dev/null 2>&1 || die "openssl is required"
command -v caddy >/dev/null 2>&1 || die "caddy is required"
cleanup() {
  [[ -z "${tmp_dir}" ]] || rm -rf -- "${tmp_dir}"
}

write_metrics() {
  local now metric_tmp
  now="$(date +%s)"
  if [[ ${rotation_success} -eq 1 ]]; then
    last_success="${now}"
  elif [[ -r "${METRIC_FILE}" ]]; then
    last_success="$(awk '/^meeting_ai_gateway_rotation_last_success_timestamp_seconds / {print $2}' "${METRIC_FILE}" | tail -1)"
    [[ "${last_success}" =~ ^[0-9]+$ ]] || last_success=0
  fi
  if [[ ${certificate_not_after} -eq 0 && -r "${TLS_DIR}/current/server.crt" ]]; then
    certificate_not_after="$(date -d "$(openssl x509 -in "${TLS_DIR}/current/server.crt" -noout -enddate | cut -d= -f2-)" +%s 2>/dev/null || echo 0)"
  fi
  metric_tmp="$(mktemp "${METRIC_FILE}.XXXXXX")" || return 1
  cat >"${metric_tmp}" <<EOF
# HELP meeting_ai_gateway_rotation_last_attempt_timestamp_seconds Last certificate rotation attempt.
# TYPE meeting_ai_gateway_rotation_last_attempt_timestamp_seconds gauge
meeting_ai_gateway_rotation_last_attempt_timestamp_seconds ${now}
# HELP meeting_ai_gateway_rotation_last_success_timestamp_seconds Last successful certificate activation.
# TYPE meeting_ai_gateway_rotation_last_success_timestamp_seconds gauge
meeting_ai_gateway_rotation_last_success_timestamp_seconds ${last_success}
# HELP meeting_ai_gateway_rotation_last_run_success Whether the latest rotation attempt succeeded.
# TYPE meeting_ai_gateway_rotation_last_run_success gauge
meeting_ai_gateway_rotation_last_run_success ${rotation_success}
# HELP meeting_ai_gateway_certificate_not_after_timestamp_seconds Active server certificate expiry.
# TYPE meeting_ai_gateway_certificate_not_after_timestamp_seconds gauge
meeting_ai_gateway_certificate_not_after_timestamp_seconds ${certificate_not_after}
EOF
  chmod 0644 "${metric_tmp}"
  mv -f -- "${metric_tmp}" "${METRIC_FILE}"
}

finish() {
  local rc=$?
  set +e
  cleanup
  write_metrics || printf 'meeting-ai cert rotation: metric write failed\n' >&2
  unset VAULT_TOKEN VAULT_CACERT response
  exit "${rc}"
}
trap finish EXIT
trap 'exit 130' INT TERM

[[ -r "${TOKEN_FILE}" ]] || die "scoped Vault token file is unreadable"
[[ -d "$(dirname -- "${METRIC_FILE}")" ]] || die "node_exporter textfile directory is missing"

tmp_dir="$(mktemp -d "${TLS_DIR}/.rotate.XXXXXX")"

VAULT_TOKEN="$(<"${TOKEN_FILE}")"
case "${VAULT_TRANSPORT}" in
  https)
    command -v vault >/dev/null 2>&1 || die "vault CLI is required for https transport"
    [[ -r "${VAULT_CACERT_FILE}" ]] || die "pinned Vault CA file is unreadable"
    export VAULT_ADDR="${VAULT_ADDR_VALUE}"
    export VAULT_CACERT="${VAULT_CACERT_FILE}"
    export VAULT_TOKEN
    vault token renew -format=json -increment=24h -self >/dev/null
    response="$(vault write -format=json pki_meeting_ai_server/issue/staging-gateway \
      common_name=meeting-ai-gateway.internal \
      alt_names=meeting-ai-gateway.internal \
      ttl=24h)"
    ;;
  container)
    command -v docker >/dev/null 2>&1 || die "docker CLI is required for container transport"
    [[ "${VAULT_DOCKER_CONTAINER}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]] || \
      die "invalid Vault container name"
    [[ "$(docker inspect -f '{{.State.Running}}' "${VAULT_DOCKER_CONTAINER}" 2>/dev/null)" == true ]] || \
      die "Vault container is not running"
    response="$(printf '%s\n' "${VAULT_TOKEN}" | docker exec -i "${VAULT_DOCKER_CONTAINER}" sh -ec '
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN VAULT_ADDR=http://127.0.0.1:8200
      vault token renew -format=json -increment=24h -self >/dev/null
      vault write -format=json pki_meeting_ai_server/issue/staging-gateway \
        common_name=meeting-ai-gateway.internal \
        alt_names=meeting-ai-gateway.internal \
        ttl=24h
    ')"
    ;;
  *) die "unsupported VAULT_TRANSPORT: ${VAULT_TRANSPORT}" ;;
esac

jq -er '.data.certificate' <<<"${response}" >"${tmp_dir}/server-leaf.crt"
jq -er '.data.private_key' <<<"${response}" >"${tmp_dir}/server.key"
jq -er '.data.issuing_ca' <<<"${response}" >"${tmp_dir}/server-ca.crt"
cat "${tmp_dir}/server-leaf.crt" "${tmp_dir}/server-ca.crt" >"${tmp_dir}/server.crt"
chmod 0640 "${tmp_dir}/server.crt" "${tmp_dir}/server-ca.crt"
chmod 0600 "${tmp_dir}/server.key"
chown -R caddy:caddy "${tmp_dir}"
chmod 0750 "${tmp_dir}"

openssl verify -CAfile "${tmp_dir}/server-ca.crt" "${tmp_dir}/server-leaf.crt" >/dev/null
openssl x509 -in "${tmp_dir}/server-leaf.crt" -noout -checkend 43200 >/dev/null || \
  die "issued server certificate has less than 12h validity"
openssl x509 -in "${tmp_dir}/server-leaf.crt" -noout -ext subjectAltName | \
  grep -Fq 'DNS:meeting-ai-gateway.internal' || \
  die "issued server certificate lacks DNS SAN meeting-ai-gateway.internal"
certificate_not_after="$(date -d "$(openssl x509 -in "${tmp_dir}/server-leaf.crt" -noout -enddate | cut -d= -f2-)" +%s)"
rm -f -- "${tmp_dir}/server-leaf.crt"

version="issued-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
version_dir="${TLS_DIR}/${version}"
mv -- "${tmp_dir}" "${version_dir}"
tmp_dir=""

previous_target=""
if [[ -L "${TLS_DIR}/current" ]]; then
  previous_target="$(readlink -- "${TLS_DIR}/current")"
fi

rm -f -- "${TLS_DIR}/current.new" "${TLS_DIR}/current.rollback"
ln -s -- "${version}" "${TLS_DIR}/current.new"
mv -Tf -- "${TLS_DIR}/current.new" "${TLS_DIR}/current"

activate_failed=0
if systemctl is-active --quiet meeting-ai-private-gateway.service; then
  systemctl reload meeting-ai-private-gateway.service || activate_failed=1
else
  caddy validate --config /etc/caddy/meeting-ai-private.Caddyfile \
    --adapter caddyfile >/dev/null || activate_failed=1
fi

if [[ ${activate_failed} -ne 0 ]]; then
  if [[ -n "${previous_target}" ]]; then
    ln -s -- "${previous_target}" "${TLS_DIR}/current.rollback"
    mv -Tf -- "${TLS_DIR}/current.rollback" "${TLS_DIR}/current"
    if systemctl is-active --quiet meeting-ai-private-gateway.service; then
      systemctl reload meeting-ai-private-gateway.service || true
    fi
  else
    rm -f -- "${TLS_DIR}/current"
  fi
  rm -rf -- "${version_dir}"
  certificate_not_after=0
  die "gateway reload failed; certificate pointer rolled back"
fi

rotation_success=1
# Retain the active version plus two previous versions for operator rollback.
find "${TLS_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'issued-*' -print0 | \
  xargs -0 stat --format='%Y %n' | sort -nr | awk 'NR > 3 {sub(/^[^ ]+ /, ""); print}' | \
  while IFS= read -r old_version; do
    [[ "${old_version}" == "${version_dir}" ]] || rm -rf -- "${old_version}"
  done || true
