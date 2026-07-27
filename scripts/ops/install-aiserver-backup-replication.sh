#!/usr/bin/env bash
# Install the read-only aiserver -> archive-standby backup pull contract.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ACTIVE_SSH="${ACTIVE_SSH:-aiadmin@aiserver}"
ARCHIVE_SSH="${ARCHIVE_SSH:-halil@staging-sw}"
ACTIVE_HOSTNAME="${ACTIVE_HOSTNAME:-aiserver}"
ARCHIVE_HOSTNAME="${ARCHIVE_HOSTNAME:-stagingsw}"
EXPORT_USER="${EXPORT_USER:-platform-backup-export}"
APPLY=0

if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--apply]" >&2
  exit 64
fi

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 69
  }
}

need ssh
need scp
need base64
need ssh-keygen

active_seen="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "${ACTIVE_SSH}" hostname)"
archive_seen="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "${ARCHIVE_SSH}" hostname)"
[[ "${active_seen}" == "${ACTIVE_HOSTNAME}" ]] || {
  echo "active host mismatch: ${active_seen}" >&2
  exit 78
}
[[ "${archive_seen}" == "${ARCHIVE_HOSTNAME}" ]] || {
  echo "archive host mismatch: ${archive_seen}" >&2
  exit 78
}

ssh -o BatchMode=yes "${ACTIVE_SSH}" \
  'test -f /etc/aiserver-archive/ARCHIVE_STANDBY && exit 1 || exit 0'
ssh -o BatchMode=yes "${ARCHIVE_SSH}" \
  'sudo -n test -f /etc/aiserver-archive/ARCHIVE_STANDBY'

if [[ "${APPLY}" -ne 1 ]]; then
  echo "preflight=pass active=${ACTIVE_HOSTNAME} archive=${ARCHIVE_HOSTNAME} mode=dry-run"
  exit 0
fi

archive_dir="${ROOT}/bootstrap/host/archive-standby-backup"
active_backup_dir="${ROOT}/bootstrap/host/aiserver-backup"

scp -q "${active_backup_dir}/platform-backup-run" \
  "${ACTIVE_SSH}:/tmp/platform-backup-run"
ssh -o BatchMode=yes "${ACTIVE_SSH}" \
  'sudo -n install -m 0750 -o root -g root /tmp/platform-backup-run /usr/local/sbin/platform-backup-run && rm -f /tmp/platform-backup-run'

scp -q \
  "${archive_dir}/platform-backup-archive-pull" \
  "${archive_dir}/platform-backup-archive-pull.service" \
  "${archive_dir}/platform-backup-archive-pull.timer" \
  "${ARCHIVE_SSH}:/tmp/"

ssh -o BatchMode=yes "${ARCHIVE_SSH}" '
  set -euo pipefail
  sudo -n install -d -m 0700 -o root -g root /root/.ssh
  if ! sudo -n test -f /root/.ssh/aiserver-backup-pull; then
    sudo -n ssh-keygen -q -t ed25519 -N "" -C "aiserver-backup-pull@stagingsw" -f /root/.ssh/aiserver-backup-pull
  fi
  sudo -n chmod 0600 /root/.ssh/aiserver-backup-pull
  sudo -n chmod 0644 /root/.ssh/aiserver-backup-pull.pub
'

public_key="$(ssh -o BatchMode=yes "${ARCHIVE_SSH}" \
  'sudo -n cat /root/.ssh/aiserver-backup-pull.pub')"
[[ "${public_key}" =~ ^ssh-ed25519[[:space:]][A-Za-z0-9+/=]+[[:space:]][A-Za-z0-9@._-]+$ ]] || {
  echo "archive public key validation failed" >&2
  exit 65
}
public_key_b64="$(printf '%s' "${public_key}" | base64 | tr -d '\n')"

host_key_raw="$(ssh -o BatchMode=yes "${ACTIVE_SSH}" \
  'sudo -n ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key')"
host_key="$(printf '%s\n' "${host_key_raw}" | awk 'NF >= 2 { print $1 " " $2 }')"
[[ "${host_key}" =~ ^ssh-ed25519[[:space:]][A-Za-z0-9+/=]+$ ]] || {
  echo "active SSH host key validation failed" >&2
  exit 65
}
host_key_b64="$(printf '%s' "${host_key}" | base64 | tr -d '\n')"

ssh -o BatchMode=yes "${ACTIVE_SSH}" bash -s -- \
  "${EXPORT_USER}" "${public_key_b64}" <<'ACTIVE'
set -euo pipefail
user="$1"
public_key="$(printf '%s' "$2" | base64 -d)"

if ! getent passwd "${user}" >/dev/null; then
  sudo -n useradd --system --create-home --home-dir "/var/lib/${user}" \
    --shell /bin/sh "${user}"
fi
sudo -n passwd -l "${user}" >/dev/null

tmp="$(mktemp)"
printf 'restrict,command="/usr/bin/rrsync -ro /srv/platform/backup" %s\n' \
  "${public_key}" >"${tmp}"
sudo -n install -d -m 0755 -o root -g root "/var/lib/${user}"
sudo -n install -d -m 0755 -o root -g root "/var/lib/${user}/.ssh"
sudo -n install -m 0644 -o root -g root "${tmp}" \
  "/var/lib/${user}/.ssh/authorized_keys"
rm -f "${tmp}"

sudo -n setfacl -m "u:${user}:--x" /srv/platform/backup
for class in pg vault keycloak; do
  sudo -n find "/srv/platform/backup/${class}" -type d -exec \
    setfacl -m "u:${user}:r-x" {} +
  sudo -n find "/srv/platform/backup/${class}" -type f -exec \
    setfacl -m "u:${user}:r--" {} +
done
ACTIVE

ssh -o BatchMode=yes "${ARCHIVE_SSH}" bash -s -- \
  "${host_key_b64}" <<'ARCHIVE'
set -euo pipefail
host_key="$(printf '%s' "$1" | base64 -d)"
known_hosts="$(mktemp)"
printf 'aiserver,10.9.10.15 %s\n' "${host_key}" >"${known_hosts}"
sudo -n install -m 0600 -o root -g root "${known_hosts}" \
  /root/.ssh/aiserver-backup-known-hosts
rm -f "${known_hosts}"

sudo -n install -d -m 0700 -o root -g root /srv/platform/archive/aiserver-backup
sudo -n install -m 0750 -o root -g root \
  /tmp/platform-backup-archive-pull \
  /usr/local/sbin/platform-backup-archive-pull
sudo -n install -m 0644 -o root -g root \
  /tmp/platform-backup-archive-pull.service \
  /etc/systemd/system/platform-backup-archive-pull.service
sudo -n install -m 0644 -o root -g root \
  /tmp/platform-backup-archive-pull.timer \
  /etc/systemd/system/platform-backup-archive-pull.timer
rm -f /tmp/platform-backup-archive-pull \
  /tmp/platform-backup-archive-pull.service \
  /tmp/platform-backup-archive-pull.timer

sudo -n systemctl daemon-reload
sudo -n systemctl enable --now platform-backup-archive-pull.timer
sudo -n systemctl start platform-backup-archive-pull.service
ARCHIVE

fingerprint="$(printf '%s\n' "${public_key}" | ssh-keygen -lf - | awk '{print $2}')"
echo "install=pass active=${ACTIVE_HOSTNAME} archive=${ARCHIVE_HOSTNAME} key=${fingerprint}"
