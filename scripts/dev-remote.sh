#!/usr/bin/env bash
# Mac entrypoint for #3582 remote developer workspace. No production operations.
set -euo pipefail
host=staging-sw-legacy
root=/srv/platform-dev/repos
case "${1:-status}" in
  status)
    ssh -o BatchMode=yes "$host" 'hostname; df -h /; systemctl is-active platform-dev-docker.service; docker --host unix:///run/platform-dev/docker.sock info --format "Docker {{.ServerVersion}} / {{.DockerRootDir}}"'
    ;;
  shell) exec ssh -t "$host" "cd $root && exec bash -l" ;;
  test-web) exec ssh "$host" "bash -lc 'cd $root/platform-web && pnpm test:meeting'" ;;
  test-backend) exec ssh "$host" "bash -lc 'cd $root/platform-backend && ./mvnw -B -ntp -pl common-meeting-events -am test'" ;;
  build-web) exec ssh "$host" "bash -lc 'cd $root/platform-web && pnpm build:shell'" ;;
  preview)
    echo 'DEV preview: http://127.0.0.1:33000 (Ctrl-C closes this SSH tunnel)'
    forwards=()
    for port in 33000 33001 33002 33004 33005 33006 33007 33008 33009 33010 33011; do
      forwards+=(-L "127.0.0.1:$port:127.0.0.1:$port")
    done
    exec ssh -N -o ExitOnForwardFailure=yes "${forwards[@]}" "$host"
    ;;
  code) exec code --remote "ssh-remote+$host" /srv/platform-dev/platform-dev.code-workspace ;;
  *) echo 'Usage: dev-remote.sh status|shell|test-web|test-backend|build-web|preview|code' >&2; exit 2 ;;
esac
