#!/usr/bin/env bash
# #3888 — mirror host-timer node_exporter textfile metrics into the k3d node.
#
# Host timers (meeting-ai client/server cert rotation, trust-root probe) write
# /var/lib/node_exporter/*.prom on aiserver, but node-exporter runs inside the
# k3d node container and reads that node's own /var/lib/node_exporter
# (helm-values/kube-prometheus-stack/values-prod.yaml extraHostVolumeMounts).
# Without this bridge those metrics were never scraped. Atomic per file
# (tmp + mv); only *.prom from SRC are written, nothing in the node is deleted
# (other writers, e.g. vault_policy_drift.prom, share the directory).
set -euo pipefail

SRC="${TEXTFILE_SRC:-/var/lib/node_exporter}"
NODES="${TEXTFILE_K3D_NODES:-k3d-prod-server-0}"
DEST="/var/lib/node_exporter"

shopt -s nullglob
files=("${SRC}"/*.prom)
rc=0
for node in ${NODES}; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "${node}" 2>/dev/null)" != "true" ]]; then
    echo "skip ${node}: not running" >&2
    rc=1
    continue
  fi
  docker exec "${node}" mkdir -p "${DEST}"
  for f in "${files[@]}"; do
    b="$(basename "${f}")"
    if docker exec -i "${node}" sh -c "cat > '${DEST}/.${b}.tmp' && chmod 0644 '${DEST}/.${b}.tmp' && mv -f '${DEST}/.${b}.tmp' '${DEST}/${b}'" < "${f}"; then
      :
    else
      echo "copy failed: ${b} -> ${node}" >&2
      rc=1
    fi
  done
  echo "synced ${#files[@]} file(s) -> ${node}:${DEST}"
done
exit "${rc}"
