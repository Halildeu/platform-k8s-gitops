#!/usr/bin/env bash
# Fail closed before protected-environment approval when the requested product
# device does not match the live Denetim endpoint and its active trust rows.

set -euo pipefail

DEVICE_ID="${DEVICE_ID:?DEVICE_ID is required}"
DEVICE_HOSTNAME="${DEVICE_HOSTNAME:?DEVICE_HOSTNAME is required}"
TENANT_ID="${TENANT_ID:-00000000-0000-0000-0000-000000000001}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
PG_DATABASE="${PG_DATABASE:-endpoint_admin}"
PG_USER="${PG_USER:-postgres}"
DB_SCHEMA="${DB_SCHEMA:-endpoint_admin_service}"
DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-denetim-pc}"
DENETIM_SSH_CONFIG="${DENETIM_SSH_CONFIG:-/home/halil/.ssh/config}"

fail() {
  echo "target-preflight: $1" >&2
  exit 1
}

[[ "$DEVICE_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
  || fail "device-id-invalid"
[[ "$TENANT_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
  || fail "tenant-id-invalid"
[[ "$DEVICE_HOSTNAME" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,126}$ ]] \
  || fail "device-hostname-invalid"
[[ "$DENETIM_SSH_TARGET" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$ ]] \
  || fail "denetim-ssh-target-invalid"
[[ "$DB_SCHEMA" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "db-schema-invalid"
command -v docker >/dev/null 2>&1 || fail "docker-missing"
command -v ssh >/dev/null 2>&1 || fail "ssh-missing"
[[ -r "$DENETIM_SSH_CONFIG" ]] || fail "denetim-ssh-config-not-readable"
docker inspect "$PG_CONTAINER" >/dev/null 2>&1 || fail "postgres-container-unavailable"

sql="
WITH requested AS (
  SELECT d.id
  FROM ${DB_SCHEMA}.endpoint_devices d
  WHERE d.id = :'device_id'::uuid
    AND d.tenant_id = :'tenant_id'::uuid
    AND lower(d.hostname) = lower(:'device_hostname')
    AND d.status = 'ONLINE'
    AND EXISTS (
      SELECT 1
      FROM ${DB_SCHEMA}.endpoint_machine_certs c
      WHERE c.device_id = d.id
        AND c.tenant_id = d.tenant_id
        AND c.revoked_at IS NULL
        AND c.channel = 'VAULT_TPM'
        AND c.cert_not_before <= now()
        AND now() < c.cert_not_after
    )
    AND EXISTS (
      SELECT 1
      FROM ${DB_SCHEMA}.endpoint_tpm_device_binding b
      WHERE b.device_id = d.id
        AND b.tenant_id = d.tenant_id
        AND b.revoked_at IS NULL
    )
), hostname_cardinality AS (
  SELECT count(*) AS count
  FROM ${DB_SCHEMA}.endpoint_devices d
  WHERE d.tenant_id = :'tenant_id'::uuid
    AND lower(d.hostname) = lower(:'device_hostname')
)
SELECT (SELECT count(*) FROM requested)::text || '|' ||
       (SELECT count FROM hostname_cardinality)::text;
"

binding_counts="$(
  printf '%s\n' "$sql" \
    | docker exec -i "$PG_CONTAINER" psql \
        -U "$PG_USER" -d "$PG_DATABASE" -At -v ON_ERROR_STOP=1 \
        -v "device_id=$DEVICE_ID" \
        -v "tenant_id=$TENANT_ID" \
        -v "device_hostname=$DEVICE_HOSTNAME" \
        -f -
)" || fail "database-query-failed"
[[ "$binding_counts" == "1|1" ]] || fail "device-id-hostname-live-trust-binding-mismatch"

remote_hostname="$(ssh -n -F "$DENETIM_SSH_CONFIG" -o BatchMode=yes "$DENETIM_SSH_TARGET" hostname 2>/dev/null \
  | tr -d '\r\n[:space:]')" || fail "denetim-ssh-hostname-read-failed"
[[ -n "$remote_hostname" ]] || fail "denetim-ssh-hostname-empty"
remote_hostname_normalized="$(printf '%s' "$remote_hostname" | tr '[:upper:]' '[:lower:]')"
requested_hostname_normalized="$(printf '%s' "$DEVICE_HOSTNAME" | tr '[:upper:]' '[:lower:]')"
[[ "$remote_hostname_normalized" == "$requested_hostname_normalized" ]] \
  || fail "device-hostname-does-not-match-attended-endpoint"

echo "target-preflight: verified live device, hostname, active VAULT_TPM certificate, and TPM binding"
