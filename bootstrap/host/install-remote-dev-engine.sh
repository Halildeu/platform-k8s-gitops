#!/usr/bin/env bash
# Dedicated developer engine on the retired .53 host. Never starts legacy Docker.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
[[ $(hostname) == stagingsw ]] || { echo 'Unexpected host' >&2; exit 1; }
hostname -I | tr ' ' '\n' | grep -Fxq 10.9.10.53
for service in docker containerd; do
  [[ $(systemctl show "$service" -p ActiveState --value) == inactive ]]
  [[ $(systemctl show "$service" -p UnitFileState --value) == masked ]]
done
[[ ! -e /var/lib/docker ]] || { echo 'Legacy Docker data must be retired first' >&2; exit 1; }
install -d -m 0755 /etc/platform-dev
install -d -m 0750 -o halil -g halil /srv/platform-dev/{repos,cache,ops,evidence}
install -d -m 0710 -o root -g docker /srv/platform-dev/docker
config=$(mktemp)
trap 'rm -f "$config"' EXIT
cat > "$config" <<'JSON'
{
  "data-root": "/srv/platform-dev/docker",
  "exec-root": "/run/platform-dev/exec",
  "pidfile": "/run/platform-dev/docker.pid",
  "hosts": ["unix:///run/platform-dev/docker.sock"],
  "group": "docker",
  "bip": "172.29.240.1/24",
  "default-address-pools": [{"base":"172.28.0.0/16","size":24}],
  "ip": "127.0.0.1",
  "default-network-opts": {"bridge":{"com.docker.network.bridge.host_binding_ipv4":"127.0.0.1"}},
  "log-driver": "local",
  "log-opts": {"max-size":"10m","max-file":"3"},
  "live-restore": true
}
JSON
dockerd --validate --config-file "$config"
config_changed=0
cmp -s "$config" /etc/platform-dev/docker.json || config_changed=1
was_active=$(systemctl is-active platform-dev-docker.service || true)
install -m 0644 "$config" /etc/platform-dev/docker.json
cat > /etc/systemd/system/platform-dev-docker.service <<'UNIT'
[Unit]
Description=Isolated remote developer Docker engine
After=network-online.target
Wants=network-online.target
Conflicts=docker.service containerd.service

[Service]
Type=notify
ExecStart=/usr/bin/dockerd --config-file=/etc/platform-dev/docker.json
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5
RuntimeDirectory=platform-dev
RuntimeDirectoryMode=0755
Delegate=yes
KillMode=process
TimeoutStartSec=90
LimitNOFILE=1048576
TasksMax=infinity

[Install]
WantedBy=multi-user.target
UNIT
systemd-analyze verify /etc/systemd/system/platform-dev-docker.service
systemctl daemon-reload
systemctl enable --now platform-dev-docker.service
if [[ $config_changed == 1 && $was_active == active ]]; then
  systemctl restart platform-dev-docker.service
fi
for _ in $(seq 1 30); do
  if docker --host unix:///run/platform-dev/docker.sock info >/dev/null 2>&1; then
    docker --host unix:///run/platform-dev/docker.sock info --format 'DEV_ENGINE={{.ServerVersion}} ROOT={{.DockerRootDir}} CONTAINERS={{.Containers}}'
    exit 0
  fi
  sleep 1
done
echo 'Developer engine did not become ready' >&2
exit 1
