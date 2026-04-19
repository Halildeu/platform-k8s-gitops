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
