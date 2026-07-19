#!/bin/bash
# Read-only Faz 35 Etik Speak test activation preflight.
# Runs from a reviewed local GitOps checkout and inspects staging-sw over SSH.
set -euo pipefail

SSH_TARGET="${SSH_TARGET:-halil@staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
PREFLIGHT_STAGE="${PREFLIGHT_STAGE:-activation}"
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ACTIVATION="$REPO_ROOT/kustomize/overlays/test/activation/etik-speak"
NETPOL="$ACTIVATION/netpol.yaml"
ROOT_OVERLAY="$REPO_ROOT/kustomize/overlays/test/kustomization.yaml"
SERVICE_CONFIG="$REPO_ROOT/kustomize/base/apps/etik-speak/ethics-service-config.yaml"
SECRET_STORE="$ACTIVATION/secretstore.yaml"
EXPECTED_MODEL_JSON_SHA256="9234b1d6356698f7bd2825c0842d6eed31cd5cb99d30101d22eb2a01a821409c"

[ "$SSH_TARGET" = "halil@staging-sw" ] || {
  echo "FATAL: Faz 35 preflight is pinned to halil@staging-sw" >&2
  exit 1
}
[ "$KUBE_CONTEXT" = "k3d-test" ] && [ "$KUBE_NS" = "platform-test" ] || {
  echo "FATAL: Faz 35 preflight is pinned to k3d-test/platform-test" >&2
  exit 1
}
case "$PREFLIGHT_STAGE" in
  foundation|activation) ;;
  *) echo "FATAL: PREFLIGHT_STAGE must be foundation or activation" >&2; exit 1 ;;
esac

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
sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

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

remote \
  'kubectl --request-timeout=10s --context k3d-test -n platform-test exec deploy/meeting-service -- curl --connect-timeout 5 --max-time 10 -fsS "http://vault.platform-test.svc.cluster.local:8200/v1/sys/health" >/dev/null'
if [ "$PREFLIGHT_STAGE" = activation ]; then
  approle_secret_bytes=$(remote \
    'kubectl --request-timeout=10s --context k3d-test -n platform-test get secret etik-speak-vault-approle -o jsonpath="{.data.secret-id}" | base64 -d | wc -c | tr -d " "')
  [[ "$approle_secret_bytes" =~ ^[0-9]+$ ]] && [ "$approle_secret_bytes" -ge 24 ] || {
    echo "FATAL: dedicated Etik Speak AppRole secret is missing or too short" >&2
    exit 1
  }
fi
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
if [ "$PREFLIGHT_STAGE" = foundation ]; then
  # Provisioning creates one Kubernetes Secret for the dedicated Vault
  # AppRole. Keep one additional Secret slot for retry/repair, but do not make
  # foundation provisioning depend on workload quotas that activation owns.
  check_object_headroom secrets 1 1
else
  check_object_headroom services 2 2
  check_object_headroom configmaps 2 2
  check_object_headroom secrets 2 2
  check_object_headroom pods 4 2
fi
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
  edge_headers=$(curl --connect-timeout 5 --max-time 10 -sSI "https://$host/")
  printf '%s\n' "$edge_headers" | grep -Eqi \
    '^strict-transport-security:[[:space:]]*max-age=31536000(;|$)' || {
    echo "FATAL: $host lacks the required one-year HSTS header" >&2
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
if [ "$PREFLIGHT_STAGE" = activation ]; then
  grep -Eq 'PENDING_FAZ35_(VAULT_ROLE_ID|OPENFGA_STORE_ID|OPENFGA_MODEL_ID)' "$rendered" && {
    echo "FATAL: post-provision Vault/OpenFGA binding is not GitOps-pinned" >&2
    exit 1
  }
fi
grep -Fq 'sha256:0000000000000000000000000000000000000000000000000000000000000000' "$rendered" && {
  echo "FATAL: all-zero image digest reached rendered activation" >&2
  exit 1
}
grep -Fq OVERLAY_MUST_OVERRIDE "$rendered" && {
  echo "FATAL: overlay placeholder reached rendered activation" >&2
  exit 1
}
external_secret_count=$(awk '
  /^kind: ExternalSecret$/ { count++ }
  END { print count + 0 }
' "$rendered")
[ "$external_secret_count" -eq 2 ] || {
  echo "FATAL: activation must render exactly two ExternalSecrets" >&2
  exit 1
}
[ "$(grep -c '^kind: SecretStore$' "$rendered")" -eq 1 ] || {
  echo "FATAL: activation must render exactly one namespaced SecretStore" >&2
  exit 1
}
[ "$(grep -c 'kind: SecretStore' "$rendered")" -eq 3 ] || {
  echo "FATAL: both ExternalSecrets must reference the namespaced SecretStore" >&2
  exit 1
}
grep -Fq 'name: vault-platform-gitops' "$rendered" && {
  echo "FATAL: Etik Speak must not use the broad shared ClusterSecretStore" >&2
  exit 1
}
[ "$(grep -c 'nginx.ingress.kubernetes.io/auth-secret: etik-speak-public-gate' "$rendered")" -eq 2 ] || {
  echo "FATAL: both public ingresses must use the synthetic test access gate" >&2
  exit 1
}
[ "$(grep -c 'nginx.ingress.kubernetes.io/proxy-set-headers: platform-test/etik-speak-public-upstream-headers' "$rendered")" -eq 1 ] || {
  echo "FATAL: public API ingress must bind the reviewed upstream-header contract" >&2
  exit 1
}
grep -Fq 'X-Etik-Speak-Transport: https' "$rendered" || {
  echo "FATAL: public API transport proof header is missing" >&2
  exit 1
}

if [ "$PREFLIGHT_STAGE" = activation ]; then
  store_id=$(awk '$1 == "ERP_OPENFGA_STORE_ID:" {gsub(/"/, "", $2); print $2; exit}' "$SERVICE_CONFIG")
  model_id=$(awk '$1 == "ERP_OPENFGA_MODEL_ID:" {gsub(/"/, "", $2); print $2; exit}' "$SERVICE_CONFIG")
  role_id=$(awk '$1 == "roleId:" {print $2; exit}' "$SECRET_STORE")
  printf '%s' "$store_id$model_id" | grep -Eq '^[0-9A-HJKMNP-TV-Z]{52}$' || {
    echo "FATAL: pinned OpenFGA store/model IDs are not canonical ULIDs" >&2
    exit 1
  }
  printf '%s' "$role_id" | grep -Eq '^[0-9A-Fa-f-]{36}$' || {
    echo "FATAL: pinned dedicated Vault role ID is not a UUID" >&2
    exit 1
  }
  live_model=$(remote \
    "kubectl --request-timeout=10s --context k3d-test -n platform-test exec deploy/meeting-service -- curl --connect-timeout 5 --max-time 10 -fsS 'http://openfga:8080/stores/$store_id/authorization-models/$model_id'")
  live_model_sha=$(printf '%s' "$live_model" | jq -cS '.authorization_model | del(.id)' | sha256_stream)
  [ "$live_model_sha" = "$EXPECTED_MODEL_JSON_SHA256" ] || {
    echo "FATAL: pinned live OpenFGA model differs from the reviewed canonical model" >&2
    exit 1
  }
fi

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
echo "Preflight: READ-ONLY $PREFLIGHT_STAGE PASS (this is not deployment or customer acceptance)"
