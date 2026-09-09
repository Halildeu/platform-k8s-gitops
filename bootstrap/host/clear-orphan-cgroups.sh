#!/usr/bin/env bash
# Clear cgroups left behind by containers Docker no longer runs.
#
# Why this is needed: with live-restore, a daemon restart can leave container
# processes alive while the new daemon state records the container as not
# running. Those processes keep the cgroup populated, and runc refuses to
# recreate a container whose cgroup is not empty:
#   runc create failed: container's cgroup is not empty: N process(es) found
#
# Two rules keep this safe, and both are load-bearing:
#
#   1. Only act on containers whose State.Running is false. A running container
#      also has a populated cgroup, so selecting on "populated" alone would kill
#      healthy services, databases included.
#   2. Test emptiness by reading a byte, not with test -s. Files under cgroupfs
#      always report size 0, so `[ -s cgroup.procs ]` is false even when the
#      cgroup holds processes, which silently turns the whole cleanup into a
#      no-op.
#
# --dry-run prints what would be killed and changes nothing.
set -uo pipefail

PROJECT="platform-dev-runtime"
DOCKER="${DOCKER:-/usr/bin/docker}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cgroup_populated() {
  # cgroupfs reports size 0 for every file, so read a byte instead.
  [ -n "$(head -c 1 "$1" 2>/dev/null)" ]
}

killed=0
skipped_running=0

for cid in $("$DOCKER" ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null); do
  running="$("$DOCKER" inspect -f '{{.State.Running}}' "$cid" 2>/dev/null)"
  name="$("$DOCKER" inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed "s#^/##")"

  if [ "$running" != "false" ]; then
    skipped_running=$((skipped_running + 1))
    continue
  fi

  while IFS= read -r cg; do
    [ -f "$cg/cgroup.kill" ] || continue
    [ -f "$cg/cgroup.procs" ] || continue
    cgroup_populated "$cg/cgroup.procs" || continue

    procs="$(wc -l < "$cg/cgroup.procs" 2>/dev/null || echo '?')"
    if [ "$DRY_RUN" = "1" ]; then
      echo "would-kill $name running=$running procs=$procs"
    else
      echo "kill $name running=$running procs=$procs"
      echo 1 > "$cg/cgroup.kill" 2>/dev/null || true
    fi
    killed=$((killed + 1))
  done < <(find /sys/fs/cgroup -type d -name "*$cid*" 2>/dev/null)
done

echo "orphan_cgroups=$killed skipped_running_containers=$skipped_running dry_run=$DRY_RUN"
[ "$DRY_RUN" = "1" ] || sleep 3
exit 0
