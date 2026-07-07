#!/usr/bin/env bash
# reconcile-kc-subject-backfill.sh
# ---------------------------------------------------------------------------
# Idempotent reconciliation of users_db.users.kc_subject from the Keycloak
# realm's user_entity, joined on lower(email). Canonical steady-state path for
# the "direct DB INSERT — emergency only" backfill documented in backend
# docs/runbooks/RB-kc-subject-backfill.md.
#
# WHY: kc_subject is consumed only by the impersonation-start target-subject
# resolution (auth-service ImpersonationController; NO email fallback; NULL ->
# 422 TARGET_SUBJECT_UNRESOLVABLE). It does NOT affect login/auth. This script
# is the DR post-restore reconcile step (S5-disaster-recovery-runbook.md §3.5)
# and a repeatable replacement for ad-hoc UPDATE statements.
#
# SAFETY MODEL (Codex 019f3ca0 hardening):
#   - dry-run (default): `BEGIN READ ONLY` + inline VALUES CTE — pure SELECT,
#     DB-ENFORCED read-only, NO UPDATE is ever issued, NO temp table. Shows
#     exactly what would change + any conflicts.
#   - --apply: prechecks abort on (dup matched email in KC / dup matched email
#     in users / kc_subject conflict) BEFORE any write; then temp-table +
#     idempotent UPDATE + COMMIT; prod also runs an exact 3-admin assert.
#   - prod --apply is owner-gated (RECONCILE_PROD_CONFIRM=yes).
#
# Run ON the host where `docker` reaches the platform PG container (staging-sw):
#   bash scripts/keycloak/reconcile-kc-subject-backfill.sh test            # dry-run
#   bash scripts/keycloak/reconcile-kc-subject-backfill.sh test --apply     # write (test)
#   RECONCILE_PROD_CONFIRM=yes bash .../reconcile-kc-subject-backfill.sh prod --apply
#
# Ref: board #2276, Codex 019f3ca0, docs/state/serban-realm-live-state-ledger.md
# ---------------------------------------------------------------------------
set -euo pipefail

ENV="${1:-}"; shift || true
MODE="dry-run"
for a in "$@"; do
  case "$a" in
    --apply)   MODE="apply" ;;
    --dry-run) MODE="dry-run" ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

case "$ENV" in
  test) PG="platform-pg-test"; REALM="platform-test" ;;
  prod) PG="platform-pg-prod"; REALM="serban" ;;
  *) echo "usage: $0 <test|prod> [--apply]" >&2; exit 2 ;;
esac

# --- owner gate: prod writes require explicit confirm -----------------------
if [ "$ENV" = "prod" ] && [ "$MODE" = "apply" ] && [ "${RECONCILE_PROD_CONFIRM:-}" != "yes" ]; then
  echo "REFUSED: prod --apply is owner-gated. Re-run with RECONCILE_PROD_CONFIRM=yes." >&2
  echo "         (prod kc_subject mutation — see docs/state/serban-realm-live-state-ledger.md §3)" >&2
  exit 3
fi

echo "=== reconcile-kc-subject-backfill :: env=$ENV realm=$REALM pg=$PG mode=$MODE ==="

# container-side temp file: unique per-run + auto-cleaned (no parallel collision)
TSV="/tmp/kc_subjects_${REALM}_$$.csv"
cleanup() { docker exec "$PG" rm -f "$TSV" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# NOTE: no `-i` here — these run `-c`/`-tAc` (no stdin). Adding `-i` would
# steal the script's own stdin when the script is fed via `bash -s < file`.
# The two heredoc-fed calls below use an explicit `docker exec -i`.
psql_kc()    { docker exec "$PG" psql -U postgres -d keycloak -v ON_ERROR_STOP=1 "$@"; }
psql_users() { docker exec "$PG" psql -U postgres -d users_db -v ON_ERROR_STOP=1 "$@"; }

# --- 1) export KC user_entity (id, lower(email)) via server-side COPY WITH CSV
#        pipe delimiter: UUIDs/emails never contain '|'.
psql_kc -c "COPY (
  SELECT u.id, lower(u.email)
  FROM user_entity u JOIN realm r ON r.id = u.realm_id
  WHERE r.name = '${REALM}' AND u.email IS NOT NULL
) TO '${TSV}' WITH (FORMAT csv, DELIMITER '|')"
KC_ROWS="$(docker exec "$PG" sh -c "grep -c . '${TSV}' 2>/dev/null || true" | tr -d ' ')"
echo "KC user_entity rows with email in realm '${REALM}': ${KC_ROWS:-0}"

# --- 2) build an inline VALUES list from the export (single-quote escaped) ---
VALUES=""
while IFS='|' read -r kc em; do
  [ -z "${kc:-}" ] && continue
  kc="${kc//\'/\'\'}"; em="${em//\'/\'\'}"
  VALUES+="${VALUES:+,}('${kc}','${em}')"
done < <(docker exec "$PG" cat "$TSV" 2>/dev/null || true)

if [ -z "$VALUES" ]; then
  echo "No KC users with email in realm '${REALM}'. Nothing to reconcile."
  exit 0
fi

# --- 3a) DRY-RUN: DB-enforced read-only, inline VALUES, NO update ------------
if [ "$MODE" = "dry-run" ]; then
  docker exec -i "$PG" psql -U postgres -d users_db -v ON_ERROR_STOP=1 <<SQL
BEGIN READ ONLY;
\echo ''
\echo '--- rows that WOULD be backfilled (kc_subject NULL -> KC uuid) ---'
WITH _kc(kc_id,email) AS (VALUES ${VALUES})
SELECT u.id, u.email, k.kc_id
FROM users u JOIN _kc k ON lower(u.email) = k.email
WHERE u.kc_subject IS NULL ORDER BY u.email;

\echo '--- counts ---'
WITH _kc(kc_id,email) AS (VALUES ${VALUES})
SELECT (SELECT count(*) FROM users)                          AS users_total,
       (SELECT count(kc_subject) FROM users)                 AS with_subject,
       (SELECT count(*) FROM users WHERE kc_subject IS NULL) AS null_subject,
       (SELECT count(*) FROM users u JOIN _kc k ON lower(u.email)=k.email
          WHERE u.kc_subject IS NULL)                        AS would_backfill;

\echo '--- CONFLICTS (non-null kc_subject that DISAGREES with KC) — expect 0 rows ---'
WITH _kc(kc_id,email) AS (VALUES ${VALUES})
SELECT u.id, u.email, u.kc_subject AS current_subject, k.kc_id AS kc_subject
FROM users u JOIN _kc k ON lower(u.email)=k.email
WHERE u.kc_subject IS NOT NULL AND u.kc_subject <> k.kc_id;
ROLLBACK;
SQL
  echo ""
  echo "DRY-RUN complete (BEGIN READ ONLY — DB-enforced; no UPDATE issued)."
  echo "  To persist:  add --apply   (prod also needs RECONCILE_PROD_CONFIRM=yes)"
  echo "NOTE: remaining NULL kc_subject rows are EXPECTED — legacy users with no"
  echo "      Keycloak identity (e.g. Workcube ERP imports). Only realm '${REALM}'"
  echo "      user_entity members can be backfilled."
  exit 0
fi

# --- 3b) APPLY: prechecks (abort before any write) --------------------------
DUP_KC="$(psql_kc -tAc "SELECT count(*) FROM (
  SELECT lower(email) e FROM user_entity u JOIN realm r ON r.id=u.realm_id
  WHERE r.name='${REALM}' AND email IS NOT NULL GROUP BY lower(email) HAVING count(*)>1) x" | tr -d '[:space:]')"
DUP_USERS="$(psql_users -tAc "WITH _kc(kc_id,email) AS (VALUES ${VALUES})
  SELECT count(*) FROM (SELECT lower(u.email) e FROM users u JOIN _kc k ON lower(u.email)=k.email
    GROUP BY lower(u.email) HAVING count(*)>1) x" | tr -d '[:space:]')"
CONFLICT="$(psql_users -tAc "WITH _kc(kc_id,email) AS (VALUES ${VALUES})
  SELECT count(*) FROM users u JOIN _kc k ON lower(u.email)=k.email
  WHERE u.kc_subject IS NOT NULL AND u.kc_subject<>k.kc_id" | tr -d '[:space:]')"

for chk in "dup_matched_email_in_KC:${DUP_KC:-0}" "dup_matched_email_in_users:${DUP_USERS:-0}" "kc_subject_conflict:${CONFLICT:-0}"; do
  name="${chk%%:*}"; val="${chk#*:}"
  if [ "$val" != 0 ]; then
    echo "ABORT precheck '${name}'=${val} — refusing to mutate. Investigate first" >&2
    echo "      (see docs/state/serban-realm-live-state-ledger.md + RB-kc-subject-backfill.md)." >&2
    exit 5
  fi
done
echo "prechecks OK (no duplicate matched emails, no kc_subject conflicts)"

# --- 3c) APPLY: idempotent UPDATE in a transaction --------------------------
docker exec -i "$PG" psql -U postgres -d users_db -v ON_ERROR_STOP=1 <<SQL
BEGIN;
CREATE TEMP TABLE _kc (kc_id text, email text);
\copy _kc(kc_id, email) FROM '${TSV}' WITH (FORMAT csv, DELIMITER '|')
UPDATE users u SET kc_subject = k.kc_id
FROM _kc k WHERE lower(u.email) = k.email AND u.kc_subject IS NULL;
\echo '--- post-state (committed) ---'
SELECT (SELECT count(kc_subject) FROM users)                 AS with_subject_after,
       (SELECT count(*) FROM users WHERE kc_subject IS NULL) AS null_after;
COMMIT;
SQL

# --- 3d) prod-only: exact 3-admin assert ------------------------------------
if [ "$ENV" = "prod" ]; then
  MISMATCH="$(psql_users -tAc "SELECT count(*) FROM (VALUES
    (1201,'48102a7f-5144-4e5b-8e01-4b869fd73511'),
    (1203,'dfc7d1bf-c138-4f72-9dfb-14e0691b68da'),
    (1204,'d14c0a96-4e61-4b9a-9a69-43e8424e14fb')) e(id,uuid)
    LEFT JOIN users u ON u.id=e.id
    WHERE u.kc_subject IS DISTINCT FROM e.uuid" | tr -d '[:space:]')"
  if [ "${MISMATCH:-1}" != 0 ]; then
    echo "FAIL: prod 3-admin kc_subject exact assert mismatch=${MISMATCH}" >&2
    exit 4
  fi
  echo "prod 3-admin exact assert: OK (1201/1203/1204 match expected UUIDs)"
fi

echo "APPLIED (transaction COMMITted)."
echo "NOTE: remaining NULL kc_subject rows are EXPECTED — legacy users with no"
echo "      Keycloak identity (Workcube ERP imports), not an alarm."
