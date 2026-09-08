#!/usr/bin/env bash
# Exercise the kill branch of clear-orphan-cgroups.sh without touching any real
# container. A fake `docker` reports one container that is not running, and a
# real cgroup holds a real sleep process, so the script must actually kill it.
#
# Two cases, because a recovery path that only kills is as wrong as one that
# never kills:
#   case A  running=false + populated cgroup  -> must kill
#   case B  running=true  + populated cgroup  -> must NOT kill
set -uo pipefail

WORK=$(mktemp -d)
ID_A=aaaa1111cafe0000000000000000000000000000000000000000000000000001
ID_B=bbbb2222cafe0000000000000000000000000000000000000000000000000002
CG_A=/sys/fs/cgroup/docker-$ID_A.scope
CG_B=/sys/fs/cgroup/docker-$ID_B.scope
rc=0

cleanup() {
  for d in "$CG_A" "$CG_B"; do
    [ -d "$d" ] || continue
    while read -r p; do kill -9 "$p" 2>/dev/null || true; done < <(sudo -n cat "$d/cgroup.procs" 2>/dev/null)
    sleep 1
    sudo -n rmdir "$d" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

run_case() {
  local label="$1" running="$2" cid="$3" cg="$4" expect_dead="$5"

  sudo -n mkdir -p "$cg" || { echo "SKIP $label: cannot create $cg"; return 0; }

  sleep 600 &
  local pid=$!
  echo "$pid" | sudo -n tee "$cg/cgroup.procs" >/dev/null || {
    echo "SKIP $label: cannot move pid into cgroup"; kill -9 "$pid" 2>/dev/null; return 0; }

  local populated
  populated=$(sudo -n bash -c "[ -n \"\$(head -c1 '$cg/cgroup.procs')\" ] && echo yes || echo no")
  echo "--- $label"
  echo "    pid=$pid cgroup=$(basename "$cg") populated_before=$populated reported_size=$(sudo -n stat -c %s "$cg/cgroup.procs")"

  cat > "$WORK/docker" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *-aq*)             echo "$cid" ;;
  *State.Running*)   echo "$running" ;;
  *.Name*)           echo "/platform-dev-runtime-killpath-fake-1" ;;
  *)                 exit 0 ;;
esac
EOF
  chmod +x "$WORK/docker"

  sudo -n env DOCKER="$WORK/docker" /srv/platform-dev/ops/clear-orphan-cgroups.sh 2>&1 | sed 's/^/    /'

  sleep 2
  local alive=no
  kill -0 "$pid" 2>/dev/null && alive=yes

  if [ "$expect_dead" = "yes" ]; then
    if [ "$alive" = "no" ]; then echo "    RESULT: PASS — orphan was killed"
    else echo "    RESULT: FAIL — orphan survived"; rc=1; fi
  else
    if [ "$alive" = "yes" ]; then echo "    RESULT: PASS — running container untouched"
    else echo "    RESULT: FAIL — killed a running container"; rc=1; fi
  fi

  kill -9 "$pid" 2>/dev/null || true
  sleep 1
  sudo -n rmdir "$cg" 2>/dev/null || true
}

echo "=== kill-path test: real script, fake docker, real cgroups, no real container touched"
run_case "case A  State.Running=false -> must kill" false "$ID_A" "$CG_A" yes
run_case "case B  State.Running=true  -> must not kill" true "$ID_B" "$CG_B" no
echo "=== overall: $([ $rc = 0 ] && echo ALL PASS || echo FAILURES)"
exit $rc
