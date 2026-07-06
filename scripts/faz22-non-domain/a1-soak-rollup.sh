#!/usr/bin/env bash
# Faz 22.2.A / #1044 — A1 non-domain pilot soak rollup helper.
#
# Purpose:
#   Produce read-only DB evidence for the #1044 24h soak gate after the
#   HALILKOOLUB735 + 2 fresh Parallels Windows devices have enrolled.
#
# Safety contract:
#   - Default is dry-run and prints the SQL plus thresholds.
#   - Execute mode runs SELECT-only SQL through psql; it never mutates DB rows.
#   - No credentials are accepted as arguments. Use an existing docker/ssh
#     context with psql access.
#   - This helper does not produce a PASS verdict by itself; it surfaces the
#     heartbeat and command facts used in the per-device/rollup evidence docs.
#
# Usage:
#   bash scripts/faz22-non-domain/a1-soak-rollup.sh
#   bash scripts/faz22-non-domain/a1-soak-rollup.sh --device-id <uuid>
#   bash scripts/faz22-non-domain/a1-soak-rollup.sh --execute --ssh-target halil@staging-sw
#   bash scripts/faz22-non-domain/a1-soak-rollup.sh --execute --ssh-target halil@staging-sw --ssh-identity-file ~/.ssh/id_ed25519
#   bash scripts/faz22-non-domain/a1-soak-rollup.sh --execute --docker-container platform-pg-test

set -euo pipefail

WINDOW_HOURS=24
HEARTBEAT_INTERVAL_SECONDS=30
MAX_GAP_MINUTES=30
DOCKER_CONTAINER="platform-pg-test"
PG_USER="platform"
PG_DATABASE="endpoint_admin"
SSH_TARGET=""
SSH_IDENTITY_FILE=""
EXECUTE=0
DEVICE_IDS=()

usage() {
  sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

log() {
  printf '[faz22-a1-soak-rollup] %s\n' "$*"
}

die() {
  printf '[faz22-a1-soak-rollup] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

safe_name() {
  [[ "$1" =~ ^[A-Za-z0-9_.-]+$ ]]
}

safe_ssh_target() {
  [[ "$1" =~ ^[A-Za-z0-9_.@:-]+$ ]]
}

valid_uuid() {
  [[ "$1" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage 0
      ;;
    --execute)
      EXECUTE=1
      shift
      ;;
    --dry-run)
      EXECUTE=0
      shift
      ;;
    --window-hours)
      WINDOW_HOURS="${2:-}"
      [[ "$WINDOW_HOURS" =~ ^[0-9]+$ ]] || die "--window-hours must be an integer"
      [ "$WINDOW_HOURS" -gt 0 ] || die "--window-hours must be > 0"
      shift 2
      ;;
    --heartbeat-interval-seconds)
      HEARTBEAT_INTERVAL_SECONDS="${2:-}"
      [[ "$HEARTBEAT_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || die "--heartbeat-interval-seconds must be an integer"
      [ "$HEARTBEAT_INTERVAL_SECONDS" -gt 0 ] || die "--heartbeat-interval-seconds must be > 0"
      shift 2
      ;;
    --max-gap-minutes)
      MAX_GAP_MINUTES="${2:-}"
      [[ "$MAX_GAP_MINUTES" =~ ^[0-9]+$ ]] || die "--max-gap-minutes must be an integer"
      [ "$MAX_GAP_MINUTES" -gt 0 ] || die "--max-gap-minutes must be > 0"
      shift 2
      ;;
    --device-id)
      [ -n "${2:-}" ] || die "--device-id requires a UUID"
      valid_uuid "$2" || die "--device-id must be a UUID: $2"
      DEVICE_IDS+=("$2")
      shift 2
      ;;
    --docker-container)
      DOCKER_CONTAINER="${2:-}"
      safe_name "$DOCKER_CONTAINER" || die "--docker-container contains unsafe characters"
      shift 2
      ;;
    --db)
      PG_DATABASE="${2:-}"
      safe_name "$PG_DATABASE" || die "--db contains unsafe characters"
      shift 2
      ;;
    --user)
      PG_USER="${2:-}"
      safe_name "$PG_USER" || die "--user contains unsafe characters"
      shift 2
      ;;
    --ssh-target)
      SSH_TARGET="${2:-}"
      safe_ssh_target "$SSH_TARGET" || die "--ssh-target contains unsafe characters"
      shift 2
      ;;
    --ssh-identity-file)
      SSH_IDENTITY_FILE="${2:-}"
      [ -n "$SSH_IDENTITY_FILE" ] || die "--ssh-identity-file requires a path"
      case "$SSH_IDENTITY_FILE" in
        *$'\n'*|*$'\t'*)
          die "--ssh-identity-file contains unsafe whitespace"
          ;;
      esac
      [ -f "$SSH_IDENTITY_FILE" ] || die "--ssh-identity-file not found: $SSH_IDENTITY_FILE"
      [ -r "$SSH_IDENTITY_FILE" ] || die "--ssh-identity-file not readable: $SSH_IDENTITY_FILE"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown flag: $1"
      ;;
    *)
      die "unexpected positional argument: $1"
      ;;
  esac
done

device_filter_sql() {
  if [ "${#DEVICE_IDS[@]}" -eq 0 ]; then
    printf 'SELECT NULL::uuid AS device_id WHERE false'
    return
  fi

  local first=1
  printf 'VALUES '
  for device_id in "${DEVICE_IDS[@]}"; do
    if [ "$first" -eq 0 ]; then
      printf ', '
    fi
    first=0
    printf "('%s'::uuid)" "$device_id"
  done
}

build_sql() {
  local device_filter
  device_filter="$(device_filter_sql)"

  cat <<SQL
\\pset pager off
\\pset null '(null)'
\\timing off

-- Faz 22.2.A / #1044 A1 soak rollup helper.
-- Source-truth columns: endpoint_heartbeats.received_at + endpoint_commands.command_type.
-- This query is SELECT-only.

WITH
params AS (
  SELECT
    ${WINDOW_HOURS}::int AS window_hours,
    ${HEARTBEAT_INTERVAL_SECONDS}::int AS heartbeat_interval_seconds,
    ${MAX_GAP_MINUTES}::int AS max_gap_minutes,
    now() - (${WINDOW_HOURS}::text || ' hours')::interval AS window_start,
    now() AS window_end
),
device_filter(device_id) AS (
  ${device_filter}
),
filter_state AS (
  SELECT count(*) > 0 AS enabled FROM device_filter
),
heartbeats AS (
  SELECT h.device_id, h.received_at
  FROM endpoint_admin_service.endpoint_heartbeats h
  CROSS JOIN params p
  CROSS JOIN filter_state fs
  WHERE h.received_at >= p.window_start
    AND h.received_at <= p.window_end
    AND (NOT fs.enabled OR h.device_id IN (SELECT device_id FROM device_filter))
),
heartbeat_ordered AS (
  SELECT
    device_id,
    received_at,
    lag(received_at) OVER (PARTITION BY device_id ORDER BY received_at) AS prev_received_at
  FROM heartbeats
),
heartbeat_rollup AS (
  SELECT
    device_id,
    min(received_at) AS first_seen,
    max(received_at) AS last_seen,
    count(*) AS heartbeat_count,
    coalesce(max(extract(epoch FROM (received_at - prev_received_at))) FILTER (WHERE prev_received_at IS NOT NULL), 0) AS max_gap_seconds,
    count(*) FILTER (
      WHERE prev_received_at IS NOT NULL
        AND (received_at - prev_received_at) > ((SELECT max_gap_minutes FROM params) * interval '1 minute')
    ) AS gap_count_over_threshold
  FROM heartbeat_ordered
  GROUP BY device_id
),
commands AS (
  SELECT
    c.device_id,
    c.command_type,
    c.status,
    c.issued_at,
    c.delivered_at,
    c.started_at,
    c.completed_at
  FROM endpoint_admin_service.endpoint_commands c
  CROSS JOIN params p
  CROSS JOIN filter_state fs
  WHERE c.issued_at >= p.window_start
    AND c.issued_at <= p.window_end
    AND (NOT fs.enabled OR c.device_id IN (SELECT device_id FROM device_filter))
),
device_scope AS (
  SELECT device_id FROM device_filter
  UNION
  SELECT device_id FROM heartbeat_rollup
  UNION
  SELECT device_id FROM commands
),
command_rollup AS (
  SELECT
    device_id,
    count(*) AS command_count,
    count(*) FILTER (WHERE status IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED')) AS terminal_count,
    count(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded_count,
    count(*) FILTER (WHERE status NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED')) AS nonterminal_count
  FROM commands
  GROUP BY device_id
)
SELECT
  'SOAK_DEVICE_ROLLUP' AS section,
  ds.device_id,
  coalesce(hr.heartbeat_count, 0) AS heartbeat_count,
  floor((p.window_hours * 3600.0) / p.heartbeat_interval_seconds)::int AS expected_heartbeat_count,
  round((coalesce(hr.heartbeat_count, 0)::numeric / nullif(floor((p.window_hours * 3600.0) / p.heartbeat_interval_seconds), 0)) * 100, 2) AS heartbeat_ratio_percent,
  hr.first_seen,
  hr.last_seen,
  round(coalesce(hr.max_gap_seconds, 0)::numeric, 2) AS max_gap_seconds,
  coalesce(hr.gap_count_over_threshold, 0) AS gap_count_over_threshold,
  coalesce(cr.command_count, 0) AS command_count,
  coalesce(cr.terminal_count, 0) AS terminal_count,
  coalesce(cr.succeeded_count, 0) AS succeeded_count,
  coalesce(cr.nonterminal_count, 0) AS nonterminal_count,
  CASE
    WHEN ds.device_id IS NULL THEN 'NO_DEVICE_SCOPE'
    WHEN coalesce(hr.heartbeat_count, 0) = 0 THEN 'NO_HEARTBEAT_DATA'
    WHEN coalesce(hr.gap_count_over_threshold, 0) > 0 THEN 'GAP_REVIEW'
    WHEN coalesce(cr.nonterminal_count, 0) > 0 THEN 'COMMAND_REVIEW'
    WHEN round((coalesce(hr.heartbeat_count, 0)::numeric / nullif(floor((p.window_hours * 3600.0) / p.heartbeat_interval_seconds), 0)) * 100, 2) < 99 THEN 'LOW_HEARTBEAT_RATIO'
    ELSE 'ROLLUP_FACTS_OK'
  END AS helper_verdict
FROM device_scope ds
CROSS JOIN params p
LEFT JOIN heartbeat_rollup hr ON hr.device_id = ds.device_id
LEFT JOIN command_rollup cr ON cr.device_id = ds.device_id
ORDER BY ds.device_id;

WITH
params AS (
  SELECT
    ${WINDOW_HOURS}::int AS window_hours,
    now() - (${WINDOW_HOURS}::text || ' hours')::interval AS window_start,
    now() AS window_end
),
device_filter(device_id) AS (
  ${device_filter}
),
filter_state AS (
  SELECT count(*) > 0 AS enabled FROM device_filter
),
commands AS (
  SELECT
    c.device_id,
    c.command_type,
    c.status,
    c.issued_at,
    c.delivered_at,
    c.started_at,
    c.completed_at
  FROM endpoint_admin_service.endpoint_commands c
  CROSS JOIN params p
  CROSS JOIN filter_state fs
  WHERE c.issued_at >= p.window_start
    AND c.issued_at <= p.window_end
    AND (NOT fs.enabled OR c.device_id IN (SELECT device_id FROM device_filter))
)
SELECT
  'COMMAND_STATUS_ROLLUP' AS section,
  device_id,
  command_type,
  status,
  count(*) AS count,
  min(issued_at) AS first_issued_at,
  max(issued_at) AS last_issued_at,
  max(completed_at - issued_at) AS max_duration
FROM commands
GROUP BY device_id, command_type, status
ORDER BY device_id, command_type, status;

WITH
params AS (
  SELECT
    ${WINDOW_HOURS}::int AS window_hours,
    now() - (${WINDOW_HOURS}::text || ' hours')::interval AS window_start,
    now() AS window_end
),
device_filter(device_id) AS (
  ${device_filter}
),
filter_state AS (
  SELECT count(*) > 0 AS enabled FROM device_filter
),
commands AS (
  SELECT
    c.device_id,
    c.command_type,
    c.status,
    c.issued_at,
    c.delivered_at,
    c.started_at,
    c.completed_at
  FROM endpoint_admin_service.endpoint_commands c
  CROSS JOIN params p
  CROSS JOIN filter_state fs
  WHERE c.issued_at >= p.window_start
    AND c.issued_at <= p.window_end
    AND (NOT fs.enabled OR c.device_id IN (SELECT device_id FROM device_filter))
)
SELECT
  'COMMAND_RECENT_DETAIL' AS section,
  device_id,
  command_type,
  status,
  issued_at,
  delivered_at,
  started_at,
  completed_at,
  completed_at - issued_at AS duration
FROM commands
ORDER BY issued_at DESC
LIMIT 50;
SQL
}

run_sql() {
  if [ -n "$SSH_TARGET" ]; then
    require_cmd ssh
    log "execute via ssh target=$SSH_TARGET docker_container=$DOCKER_CONTAINER db=$PG_DATABASE user=$PG_USER"
    local ssh_args=(-o BatchMode=yes -o IdentitiesOnly=yes)
    if [ -n "$SSH_IDENTITY_FILE" ]; then
      ssh_args+=(-i "$SSH_IDENTITY_FILE")
    fi
    # shellcheck disable=SC2029 # validated local args intentionally select the remote docker/psql target.
    build_sql | ssh "${ssh_args[@]}" "$SSH_TARGET" "docker exec -i '$DOCKER_CONTAINER' psql -U '$PG_USER' -d '$PG_DATABASE' -v ON_ERROR_STOP=1"
    return
  fi

  require_cmd docker
  if ! docker inspect "$DOCKER_CONTAINER" >/dev/null 2>&1; then
    die "docker container not found locally: $DOCKER_CONTAINER; pass --ssh-target <host> or run dry-run"
  fi

  log "execute via local docker_container=$DOCKER_CONTAINER db=$PG_DATABASE user=$PG_USER"
  build_sql | docker exec -i "$DOCKER_CONTAINER" psql -U "$PG_USER" -d "$PG_DATABASE" -v ON_ERROR_STOP=1
}

log "window_hours=$WINDOW_HOURS"
log "heartbeat_interval_seconds=$HEARTBEAT_INTERVAL_SECONDS"
log "max_gap_minutes=$MAX_GAP_MINUTES"
log "device_filter_count=${#DEVICE_IDS[@]}"
log "mode=$([ "$EXECUTE" -eq 1 ] && printf execute || printf dry-run)"

if [ "$EXECUTE" -eq 0 ]; then
  log "dry-run; no DB connection attempted"
  log "acceptance reminder: helper facts must be copied into per-device + rollup evidence; this script is not a standalone PASS"
  build_sql
  exit 0
fi

run_sql
