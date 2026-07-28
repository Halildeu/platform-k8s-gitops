#!/usr/bin/env bash
# Keycloak Realm Export Cron — weekly (Faz I.1.3)
# Source: ADR-0002 §0.5 + docs/day-2-governance.md
#
# Cron install (staging-sw):
#   0 3 * * 0 /home/halil/platform-k8s-gitops/bootstrap/kc-export-cron.sh  (Pazar 03:00)
#
# Output: /home/halil/platform/backup/keycloak/{prod,test}/<realm>-<YYYYMMDD>.json.gz
# Retention: 56 gün (8 hafta geriye izle)
#
# 2026-04-24: FULL EXPORT (realm + clients + groups + roles + users + credentials).
# Önceki versiyon `kcadm.sh get realms/<realm>` PARTIAL idi (users/creds yok →
# DR drill import incomplete). Keycloak 26+ `kc.sh export` **offline** (server
# durur, prod downtime) olduğu için online alternatif Admin REST API:
#   1. `realms/<realm>/partial-export` → realm + clients + groups + roles
#   2. `realms/<realm>/users?briefRepresentation=false&max=10000` → users + creds
#   3. `jq` ile birleştir (.users = users_json)
# Tek output dosyası (eski path/format uyumu korunur).

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/home/halil/platform/backup/keycloak}"
RETENTION_DAYS="${RETENTION_DAYS:-56}"
TIMESTAMP=$(date +%Y%m%d)
USERS_MAX="${USERS_MAX:-10000}"   # realm başına max user (paging ihtiyacı için artır)

log() { printf '\033[0;36m[kc-export]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[0;31m[kc-export ERR]\033[0m %s\n' "$*" >&2; }

# Host-side jq required for merge
if ! command -v jq >/dev/null 2>&1; then
  err "jq host'ta yok; kurulum gerekli (apt install jq). Abort."
  exit 3
fi

declare -A REALMS=(
  ["prod"]="serban"
  ["test"]="platform-test"
)

for env in prod test; do
  container="platform-kc-${env}"
  realm="${REALMS[${env}]}"
  dir="${BACKUP_ROOT}/${env}"
  mkdir -p "${dir}"

  state=$(docker inspect "${container}" --format "{{.State.Status}}" 2>/dev/null || echo "missing")
  if [[ "${state}" != "running" ]]; then
    log "SKIP ${env}: ${container} state=${state}"
    continue
  fi

  output="${dir}/${realm}-${TIMESTAMP}.json.gz"
  log "EXPORT ${env}:${realm} → ${output}"

  # Admin creds. A per-environment password-file override lets the production
  # host reuse the root-only Docker secret without duplicating it in an env
  # file. The legacy bootstrap-drill env remains supported.
  password_file_var="KC_ADMIN_PASSWORD_FILE_${env^^}"
  password_file="${!password_file_var:-}"
  admin_pw_file="${HOME}/bootstrap-drill/${env}-creds.env"
  ADMIN_PW=""
  if [[ -n "${password_file}" && -f "${password_file}" ]]; then
    ADMIN_PW=$(<"${password_file}")
  elif [[ -f "${admin_pw_file}" ]]; then
    # shellcheck disable=SC1090
    source "${admin_pw_file}"
    ADMIN_PW="${KC_ADMIN_PW_PROD:-${KC_ADMIN_PW_TEST:-}}"
  fi

  if [[ -z "${ADMIN_PW:-}" ]]; then
    log "SKIP ${env}: no admin password source"
    continue
  fi

  # 1. Admin login (kcadm config credentials)
  if ! docker exec "${container}" /opt/keycloak/bin/kcadm.sh config credentials \
       --server http://localhost:8080 --realm master \
       --user admin --password "${ADMIN_PW}" >/dev/null 2>&1; then
    err "LOGIN FAIL ${env}:${realm}"
    continue
  fi

  # 2. partial-export (realm + clients + groups + roles)
  # NOT: Keycloak API `partial-export` POST endpoint'idir; `kcadm.sh get` →
  # "Resource not found" döner. `kcadm.sh create` POST yapar; RealmRepresentation
  # response'u `-o` flag ile stdout'a geçer. `-s dummy=1` boş body için dummy
  # field (server ignore eder — realm spec'e işlemez).
  realm_json=$(docker exec "${container}" /opt/keycloak/bin/kcadm.sh create \
    "realms/${realm}/partial-export" \
    --query exportGroupsAndRoles=true \
    --query exportClients=true \
    -o -s dummy=1 2>/dev/null) || {
      err "partial-export FAIL ${env}:${realm}"
      continue
    }

  # 3. users export (briefRepresentation=false → credentials dahil)
  users_json=$(docker exec "${container}" /opt/keycloak/bin/kcadm.sh get \
    "realms/${realm}/users" \
    --query "briefRepresentation=false" \
    --query "max=${USERS_MAX}" 2>/dev/null) || {
      err "users export FAIL ${env}:${realm}"
      continue
    }

  # 4. Merge (.users = users_json) + gzip
  # Keep the users payload off argv: large realms can exceed Linux's
  # per-argument size limit even when the total ARG_MAX budget is available.
  if combined=$(jq --slurpfile u <(printf '%s' "${users_json:-[]}") '.users = $u[0]' <<<"${realm_json}" 2>/dev/null); then
    echo "${combined}" | gzip > "${output}"
    chmod 600 "${output}"
    size=$(du -h "${output}" | cut -f1)
    # Metrics: realm + user counts
    realm_clients=$(jq -r '.clients | length' <<<"${realm_json}" 2>/dev/null || echo "?")
    users_count=$(jq -r 'length' <<<"${users_json}" 2>/dev/null || echo "?")
    log "OK ${env}:${realm} size=${size} clients=${realm_clients} users=${users_count}"
  else
    err "jq merge FAIL ${env}:${realm}"
    rm -f "${output}"
    continue
  fi

  # Retention
  find "${dir}" -name "*.json.gz" -type f -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true
done

log "DONE ${TIMESTAMP}"
