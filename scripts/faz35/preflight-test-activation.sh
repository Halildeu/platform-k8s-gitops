#!/bin/bash
# Read-only Faz 35 Etik Speak test activation preflight.
# Runs from a reviewed local GitOps checkout and inspects staging-sw over SSH.
set -euo pipefail

SSH_TARGET="${SSH_TARGET:-halil@staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ACTIVATION="$REPO_ROOT/kustomize/overlays/test/activation/etik-speak"
NETPOL="$ACTIVATION/netpol.yaml"
ROOT_OVERLAY="$REPO_ROOT/kustomize/overlays/test/kustomization.yaml"

[ "$SSH_TARGET" = "halil@staging-sw" ] || {
  echo "FATAL: Faz 35 preflight is pinned to halil@staging-sw" >&2
  exit 1
}
[ "$KUBE_CONTEXT" = "k3d-test" ] && [ "$KUBE_NS" = "platform-test" ] || {
  echo "FATAL: Faz 35 preflight is pinned to k3d-test/platform-test" >&2
  exit 1
}

for command_name in ssh curl jq kustomize grep awk; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command missing: $command_name" >&2
    exit 1
  }
done

ssh_opts=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ConnectionAttempts=1
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=2
)
# shellcheck disable=SC2029 # target/context are exact-guarded above; callers pass static read-only commands.
remote() { ssh "${ssh_opts[@]}" "$SSH_TARGET" "$@"; }

container_state=$(remote \
  'timeout 15 docker inspect -f "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" platform-pg-test platform-kc-test platform-vault-test')
while IFS='|' read -r container status health; do
  [ "$status" = running ] || {
    echo "FATAL: $container is not running" >&2
    exit 1
  }
  [ "$health" = healthy ] || [ "$health" = none ] || {
    echo "FATAL: $container health is $health" >&2
    exit 1
  }
done <<<"$container_state"

pg_ip=$(remote 'timeout 15 docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" platform-pg-test')
kc_ip=$(remote 'timeout 15 docker inspect -f "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" platform-kc-test')
pg_endpoint=$(remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test get endpoints postgres -o jsonpath="{.subsets[0].addresses[0].ip}"')
kc_endpoint=$(remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test get endpoints keycloak -o jsonpath="{.subsets[0].addresses[0].ip}"')
[ -n "$pg_ip" ] && [ "$pg_ip" = "$pg_endpoint" ] || {
  echo "FATAL: Postgres container/Endpoint IP drift" >&2
  exit 1
}
[ -n "$kc_ip" ] && [ "$kc_ip" = "$kc_endpoint" ] || {
  echo "FATAL: Keycloak container/Endpoint IP drift" >&2
  exit 1
}
grep -Fq "cidr: $pg_ip/32" "$NETPOL" || {
  echo "FATAL: Faz 35 NetworkPolicy does not pin current Postgres Endpoint" >&2
  exit 1
}
grep -Fq "cidr: $kc_ip/32" "$NETPOL" || {
  echo "FATAL: Faz 35 NetworkPolicy does not pin current Keycloak Endpoint" >&2
  exit 1
}

store_ready=$(remote \
  'kubectl --request-timeout=10s --context k3d-test get clustersecretstore vault-platform-gitops -o jsonpath="{range .status.conditions[?(@.type==\"Ready\")]}{.status}{end}"')
[ "$store_ready" = True ] || {
  echo "FATAL: vault-platform-gitops ClusterSecretStore is not Ready" >&2
  exit 1
}
remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test exec deploy/meeting-service -- curl --connect-timeout 5 --max-time 10 -fsS "http://openfga:8080/stores?page_size=1" >/dev/null'
remote \
  'kubectl --request-timeout=10s --context k3d-test get ingressclass nginx >/dev/null && kubectl --request-timeout=10s --context k3d-test get crd externalsecrets.external-secrets.io >/dev/null'

# Object-count quota must cover the full simultaneous rollout plus a bounded
# repair reserve. Merely fitting exactly at hard=used+new is fail-closed: an
# ExternalSecret refresh, rollback pod or recovery Service would be blocked.
quota_json=$(remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test get resourcequota platform-quota -o json')
quota_failures=0
check_object_headroom() {
  local resource=$1 activation_peak=$2 repair_reserve=$3 hard used available required
  hard=$(printf '%s' "$quota_json" | jq -r --arg r "$resource" '.status.hard[$r] // "0"')
  used=$(printf '%s' "$quota_json" | jq -r --arg r "$resource" '.status.used[$r] // "0"')
  [[ "$hard" =~ ^[0-9]+$ ]] && [[ "$used" =~ ^[0-9]+$ ]] || {
    echo "FATAL: non-integer ResourceQuota value for $resource" >&2
    quota_failures=$((quota_failures + 1))
    return
  }
  available=$((hard - used))
  required=$((activation_peak + repair_reserve))
  echo "Quota: $resource used=$used hard=$hard available=$available required=$required"
  if [ "$available" -lt "$required" ]; then
    echo "FATAL: $resource quota lacks activation + repair headroom" >&2
    quota_failures=$((quota_failures + 1))
  fi
}
check_object_headroom services 2 2
check_object_headroom configmaps 1 2
check_object_headroom secrets 1 2
check_object_headroom pods 4 2
[ "$quota_failures" -eq 0 ] || exit 1

public_ip=""
for host in etik.acik.com speakup.acik.com; do
  edge=$(curl --connect-timeout 5 --max-time 10 -sS -o /dev/null \
    -w '%{http_code}|%{ssl_verify_result}|%{remote_ip}' "https://$host/")
  IFS='|' read -r http_code verify_result remote_ip <<<"$edge"
  [ "$verify_result" = 0 ] || {
    echo "FATAL: $host TLS verification failed" >&2
    exit 1
  }
  [ -n "$remote_ip" ] || {
    echo "FATAL: $host did not resolve to a reachable edge" >&2
    exit 1
  }
  if [ -z "$public_ip" ]; then
    public_ip=$remote_ip
  else
    [ "$public_ip" = "$remote_ip" ] || {
      echo "FATAL: public hosts do not resolve to the same edge" >&2
      exit 1
    }
  fi
  echo "Edge: $host TLS=valid HTTP=$http_code IP=$remote_ip"
done

rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT
kustomize build "$ACTIVATION" >"$rendered"
grep -Fq 'sha256:0000000000000000000000000000000000000000000000000000000000000000' "$rendered" && {
  echo "FATAL: all-zero image digest reached rendered activation" >&2
  exit 1
}
grep -Fq OVERLAY_MUST_OVERRIDE "$rendered" && {
  echo "FATAL: overlay placeholder reached rendered activation" >&2
  exit 1
}

existing_count=$(remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test get deploy,svc,ingress,externalsecret -l app.kubernetes.io/part-of=etik-speak -o name 2>/dev/null | wc -l | tr -d " "')
if grep -Fq 'activation/etik-speak' "$ROOT_OVERLAY"; then
  root_state=included
else
  root_state=not-included
fi

echo "Host bridge: postgres=$pg_ip keycloak=$kc_ip (Endpoint + NetworkPolicy match)"
echo "Dependencies: Vault ESO Ready; OpenFGA in-cluster path reachable"
echo "Capacity: object quotas cover activation peak plus bounded repair reserve"
echo "Desired state: activation render immutable; root=$root_state; live_resource_count=$existing_count"
echo "Preflight: READ-ONLY PASS (this is not deployment or customer acceptance)"
