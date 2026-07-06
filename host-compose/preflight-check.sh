#!/usr/bin/env bash
# Host Compose Preflight Check — ADR-0002 bootstrap sertleştirme
# Usage: bash host-compose/preflight-check.sh <prod|test>
# Codex PR #12 iter-1 refinement: UID + network + bind-mount doğrulama

set -euo pipefail

ENV="${1:-}"
if [[ "${ENV}" != "prod" && "${ENV}" != "test" ]]; then
  echo "USAGE: $0 <prod|test>" >&2
  exit 1
fi

REMOTE="${REMOTE:-staging-sw}"
PASS=0
FAIL=0

check() {
  local name="$1"
  local result="$2"
  local detail="${3:-}"
  if [[ "${result}" == "PASS" ]]; then
    printf '\033[32m✓\033[0m %s\n' "${name}"
    PASS=$((PASS + 1))
  else
    printf '\033[31m✗\033[0m %s — %s\n' "${name}" "${detail}"
    FAIL=$((FAIL + 1))
  fi
}

sshrun() {
  ssh -o BatchMode=no "${REMOTE}" "$@"
}

echo "=== Preflight Check — host-compose ${ENV} (ADR-0002) ==="
echo

# 1. Docker network pre-create
NET="platform-${ENV}-net"
if sshrun "docker network inspect ${NET} >/dev/null 2>&1"; then
  check "Network ${NET} exists" PASS
else
  check "Network ${NET} exists" FAIL "docker network create ${NET}"
fi

# 2. Bind-mount dizinleri + ownership
for svc in postgres keycloak vault; do
  path="/srv/platform/stateful/${ENV}/${svc}"
  if sshrun "test -d ${path}"; then
    # UID check: postgres=999, keycloak+vault=1000
    expected_uid=999
    [[ "${svc}" != "postgres" ]] && expected_uid=1000
    actual_uid=$(sshrun "stat -c %u ${path}")
    if [[ "${actual_uid}" == "${expected_uid}" ]]; then
      check "Bind-mount ${path} (UID ${expected_uid})" PASS
    else
      check "Bind-mount ${path} (UID ${expected_uid})" FAIL "actual UID ${actual_uid}; sudo chown -R ${expected_uid}:${expected_uid} ${path}"
    fi
  else
    check "Bind-mount ${path}" FAIL "sudo mkdir -p ${path}"
  fi
done

# Vault alt-klasörler (data + logs)
for sub in data logs; do
  path="/srv/platform/stateful/${ENV}/vault/${sub}"
  if sshrun "test -d ${path}"; then
    check "Vault subdir ${path}" PASS
  else
    check "Vault subdir ${path}" FAIL "sudo mkdir -p ${path}"
  fi
done

# 3. Port çakışması kontrol (host bind)
declare -A ports
if [[ "${ENV}" == "prod" ]]; then
  ports[pg]=5432; ports[kc]=8081; ports[vault]=8200
else
  ports[pg]=5433; ports[kc]=8082; ports[vault]=8201
fi

for svc in pg kc vault; do
  port="${ports[$svc]}"
  # Zaten bir process dinliyor mu?
  if sshrun "ss -tlnp 2>&1 | grep -q ':${port} '"; then
    # Dinleyici platform-${svc}-${ENV} container'ı mı? (expected)
    container="platform-${svc}-${ENV}"
    if sshrun "docker inspect -f '{{.State.Running}}' ${container} 2>/dev/null" | grep -q true; then
      check "Port ${port} (${svc}/${ENV})" PASS
    else
      check "Port ${port} (${svc}/${ENV})" FAIL "Başka process dinliyor — legacy container (platform-postgres-db-1 vs)?"
    fi
  else
    check "Port ${port} free" PASS
  fi
done

# 4. Disk kapasite (ADR §7.1 400 GB eşikleri)
disk_usage=$(sshrun "df -h /srv 2>/dev/null | tail -1 | awk '{print \$5}' | tr -d '%'" || echo "0")
if [[ "${disk_usage}" -lt 75 ]]; then
  check "Disk /srv kullanım ${disk_usage}% < 75%" PASS
elif [[ "${disk_usage}" -lt 85 ]]; then
  check "Disk /srv kullanım ${disk_usage}%" FAIL "Warning eşik (75-85%); cleanup + growth review"
else
  check "Disk /srv kullanım ${disk_usage}%" FAIL "CRITICAL ≥85% — yeni deploy YASAK (day-2-governance §5.1)"
fi

# 5. Docker daemon healthy
if sshrun "docker info >/dev/null 2>&1"; then
  check "Docker daemon" PASS
else
  check "Docker daemon" FAIL "systemctl status docker"
fi

# 6. Secret file existence (çalışma dizinine bağlı, opsiyonel)
for svc_path in "postgres/${ENV}" "keycloak/${ENV}"; do
  secret_dir="host-compose/${svc_path}/secrets"
  if [[ -d "${secret_dir}" ]]; then
    case "${svc_path}" in
      postgres/*)
        if [[ -f "${secret_dir}/pg_password.txt" ]]; then
          check "Secret ${secret_dir}/pg_password.txt" PASS
        else
          check "Secret ${secret_dir}/pg_password.txt" FAIL "Missing — bkz BOOTSTRAP.md Step 1"
        fi
        ;;
      keycloak/*)
        for f in kc_db_password.txt kc_admin_password.txt; do
          if [[ -f "${secret_dir}/${f}" ]]; then
            check "Secret ${secret_dir}/${f}" PASS
          else
            check "Secret ${secret_dir}/${f}" FAIL "Missing — bkz BOOTSTRAP.md Step 2"
          fi
        done
        ;;
    esac
  fi
done

# 7. Network drift verification (2026-05-20 vault-prod incident class).
# For each host-bridge service (postgres, keycloak, vault) verify three
# things must all agree:
#   a. docker inspect .NetworkSettings.Networks[platform-<env>-net] present
#      (non-empty). On 2026-05-20 vault-prod was found with .Networks: {}
#      despite Up 39m — this is the primary signal.
#   b. docker IPv4 on that network equals the ipv4_address pinned in
#      host-compose/<svc>/<env>/docker-compose.yml (the reserved table
#      below is the authoritative source for the pin).
#   c. k8s Endpoints/<svc> in the platform-<env> namespace addresses[0].ip
#      matches (b). If not, kube-proxy will route traffic to the wrong
#      container or fail with "no endpoints".
# Auto-fix is intentionally off (per Codex 019f37d9 adversarial review):
# preflight is a fail-loud detector; the recovery command is printed and
# the operator (or the runbook) applies it. Silent auto-patching would
# create a second uncontrolled control plane.
declare -A pin_ip
declare -A container_of
declare -A endpoint_of
# container_of maps preflight-svc-name → actual docker container name
# endpoint_of maps preflight-svc-name → k8s Endpoints resource name
container_of[postgres]=pg     # docker: platform-pg-<env>
container_of[keycloak]=kc     # docker: platform-kc-<env>
container_of[vault]=vault     # docker: platform-vault-<env>
endpoint_of[postgres]=postgres
endpoint_of[keycloak]=keycloak
endpoint_of[vault]=vault
if [[ "${ENV}" == "prod" ]]; then
  pin_ip[postgres]=172.21.0.10
  pin_ip[keycloak]=172.21.0.3
  pin_ip[vault]=172.21.0.9
else
  pin_ip[postgres]=172.19.0.6
  pin_ip[keycloak]=172.19.0.7
  pin_ip[vault]=172.19.0.4
fi
NS="platform-${ENV}"
KCTX="k3d-${ENV}"

for svc in postgres keycloak vault; do
  container="platform-${container_of[$svc]}-${ENV}"
  want="${pin_ip[$svc]}"

  # (a) network attachment
  net_json=$(sshrun "docker inspect ${container} --format '{{json .NetworkSettings.Networks}}' 2>/dev/null" || echo "{}")
  if [[ "${net_json}" == "{}" || -z "${net_json}" ]]; then
    check "Network drift ${container} attach" FAIL "container has NO network attachments; recover: docker network connect ${NET} ${container}"
    continue
  fi
  if ! printf '%s' "${net_json}" | grep -q "\"${NET}\""; then
    check "Network drift ${container} on ${NET}" FAIL "not attached to ${NET}; recover: docker network connect ${NET} ${container}"
    continue
  fi

  # (b) docker IPv4 vs compose pin
  docker_ip=$(sshrun "docker inspect ${container} --format '{{(index .NetworkSettings.Networks \"${NET}\").IPAddress}}' 2>/dev/null" || echo "")
  if [[ "${docker_ip}" != "${want}" ]]; then
    check "Network drift ${container} IP" FAIL "docker IP=${docker_ip:-<empty>} != compose pin=${want}; recover: docker rm -f ${container} && docker compose -f host-compose/${svc}/${ENV}/docker-compose.yml up -d (owner window; vault requires unseal)"
    continue
  fi

  # (c) k8s Endpoints match
  ep_name="${endpoint_of[$svc]}"
  ep_ip=$(sshrun "kubectl --context ${KCTX} -n ${NS} get endpoints ${ep_name} -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null" || echo "")
  if [[ "${ep_ip}" != "${want}" ]]; then
    check "Network drift ${ep_name}/${NS} Endpoint" FAIL "k8s Endpoints=${ep_ip:-<empty>} != docker/compose=${want}; recover: kubectl --context ${KCTX} -n ${NS} patch endpoints ${ep_name} --type json -p '[{\"op\":\"replace\",\"path\":\"/subsets/0/addresses/0/ip\",\"value\":\"${want}\"}]' — then Argo sync to make it durable"
    continue
  fi

  check "Network drift ${svc}/${ENV} (docker+k8s+pin all=${want})" PASS
done

echo
echo "=== Özet ==="
echo "PASS: ${PASS}"
echo "FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
  echo
  echo "⚠ ${FAIL} preflight check fail. Fix + re-run."
  exit 1
fi

echo "✓ Preflight PASS — ${ENV} stack up edilebilir"
exit 0
