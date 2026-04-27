-- Faz 21.3 PR-G — data_access.scope_outbox transactional outbox table.
--
-- Codex 019dcf5c strategic primary recommendation (after C3c phase-0 land):
-- ADR-0008 § Tuple writer flow "outbox preferred for durability". V22 enables
-- transactional grant/revoke: PG scope row + outbox row commit atomically;
-- OpenFGA tuple write is async (poller-driven), idempotent, retry-safe.
--
-- Schema placement: reports_db.data_access (same as scope table).
-- Reason: outbox INSERT must be in same TX as scope INSERT.
-- permission_db placement → cross-DB FK (PG doesn't support) +
-- non-atomic two-phase write → orphan/lost-write risk.
--
-- Naming convention enum-as-text-CHECK over PG enum type per Codex 019dcf5c:
-- text CHECK constraints are easier to evolve in future migrations
-- (add new state without ALTER TYPE).
--
-- Idempotent / safe-to-rerun: CREATE TABLE IF NOT EXISTS guard. Re-running
-- this migration on a cluster that already has it is a no-op (Flyway
-- baseline tracks already-applied; this guard is for defensive testing).

BEGIN;

-- ============================================================================
-- scope_outbox table
-- ============================================================================

CREATE TABLE IF NOT EXISTS data_access.scope_outbox (
    id BIGSERIAL PRIMARY KEY,
    scope_id BIGINT NOT NULL REFERENCES data_access.scope(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('GRANT', 'REVOKE')),
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'FAILED')),
    attempt_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by TEXT,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

COMMENT ON TABLE data_access.scope_outbox IS
    'Faz 21.3 V22 transactional outbox for OpenFGA tuple writes. '
    'INSERT happens atomically with data_access.scope row write/update; '
    'a poller (permission-service OutboxPoller) claims rows via '
    'FOR UPDATE SKIP LOCKED, calls OpenFGA, marks PROCESSED or schedules retry.';

COMMENT ON COLUMN data_access.scope_outbox.payload IS
    'Full tuple key + scope context (avoid recomputing from mutable scope state). '
    'Minimum keys: scopeId, userId, orgId, scopeKind, scopeRef, '
    'tuple.{user,relation,object}.';

COMMENT ON COLUMN data_access.scope_outbox.status IS
    'PENDING (claimable) → PROCESSING (claimed, locked_until set) → '
    'PROCESSED (success, processed_at set) | FAILED (terminal, max_attempts).';

COMMENT ON COLUMN data_access.scope_outbox.locked_by IS
    'Poller instance ID (e.g., pod hostname). Released on PROCESSED/FAILED. '
    'Stuck rows where locked_until < now() are recovered to PENDING.';

-- ============================================================================
-- Indexes — claim query + recovery + ordering
-- ============================================================================

-- Claim query: WHERE status = 'PENDING' AND next_attempt_at <= now()
CREATE INDEX idx_scope_outbox_claim
    ON data_access.scope_outbox (status, next_attempt_at)
    WHERE status = 'PENDING';

-- Per-scope_id ordering guard (Codex 019dcf5c risk #1):
-- Prevent GRANT/REVEKE race for same scope under future multi-worker scale-up.
-- Poller's WHERE clause uses NOT EXISTS subquery on this scope_id.
CREATE INDEX idx_scope_outbox_scope_ordering
    ON data_access.scope_outbox (scope_id, id)
    WHERE status IN ('PENDING', 'PROCESSING');

-- Stuck row recovery query: WHERE status='PROCESSING' AND locked_until < now()
CREATE INDEX idx_scope_outbox_recovery
    ON data_access.scope_outbox (locked_until)
    WHERE status = 'PROCESSING';

-- Audit/observability: failed rows + processed rows for D35 evidence
CREATE INDEX idx_scope_outbox_failed
    ON data_access.scope_outbox (created_at)
    WHERE status = 'FAILED';

CREATE INDEX idx_scope_outbox_scope_id ON data_access.scope_outbox (scope_id);

-- ============================================================================
-- Helper: recover_stuck_outbox_rows()
-- ============================================================================
-- Idempotent recovery function called by poller startup or background sweeper.
-- Releases PROCESSING rows where the lock has expired (pod crash, etc.) back
-- to PENDING for re-claim. Atomic; safe under concurrent calls.

CREATE OR REPLACE FUNCTION data_access.recover_stuck_outbox_rows()
    RETURNS INT AS $$
DECLARE
    v_recovered INT;
BEGIN
    UPDATE data_access.scope_outbox
    SET status = 'PENDING',
        locked_by = NULL,
        locked_until = NULL,
        last_error = COALESCE(last_error || E'\n', '') ||
                     'recovered from stuck PROCESSING at ' || now()::text
    WHERE status = 'PROCESSING'
      AND locked_until < now();

    GET DIAGNOSTICS v_recovered = ROW_COUNT;
    RETURN v_recovered;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION data_access.recover_stuck_outbox_rows() IS
    'Faz 21.3 V22: release PROCESSING rows where locked_until < now() back '
    'to PENDING. Used by poller startup + background sweeper. Idempotent.';

COMMIT;
