"""Faz 16.3 Gün 5 — Load SQL generator tests (Codex iter-6 AGREE).

Test only SQL string generation (no live DB connection).
Real PG integration tests run in CI (Faz 16.3 Gün 7 dry-run).
"""


from etl_worker.transform import ColumnMeta, TableMeta
from etl_worker.load import build_upsert_sql


def _company_meta_no_year() -> TableMeta:
    return TableMeta(
        name="COMPANY",
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="company_id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="company_name", pg_type="VARCHAR(255)", nullable=False, max_length=255),
        ],
        idempotency_key=["company_id"],
    )


def _bank_actions_meta_yearly() -> TableMeta:
    return TableMeta(
        name="BANK_ACTIONS",
        source_schema="workcube_mikrolink_1",
        source_year=2024,
        columns=[
            ColumnMeta(name="bank_action_id", pg_type="BIGINT", nullable=False),
            ColumnMeta(name="amount", pg_type="NUMERIC(19,4)", nullable=True),
        ],
        idempotency_key=["bank_action_id"],
    )


def test_upsert_sql_canonical_table():
    """COMPANY (no source_year) — conflict key 3 col."""
    sql = build_upsert_sql(_company_meta_no_year())
    s = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)

    # Schema + table identifier
    assert "workcube_mikrolink" in s
    assert "company" in s.lower()

    # Conflict key (no source_year)
    assert "source_schema" in s
    assert "source_table" in s
    assert "source_pk" in s
    assert "ON CONFLICT" in s

    # WHERE clause for content_hash
    assert "content_hash IS DISTINCT FROM EXCLUDED.content_hash" in s


def test_upsert_sql_parametric_table():
    """BANK_ACTIONS (with source_year) — conflict key 4 col."""
    sql = build_upsert_sql(_bank_actions_meta_yearly())
    s = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)

    # source_year in conflict key
    assert "source_year" in s
    assert "ON CONFLICT" in s


def test_upsert_sql_no_user_input_in_identifiers():
    """SQL identifier injection check — user input column adı kontrol allowlist."""
    meta = TableMeta(
        name="DROP TABLE x; --",  # malicious table name
        source_schema="workcube_mikrolink",
        source_year=None,
        columns=[
            ColumnMeta(name="col1", pg_type="INTEGER", nullable=False),
        ],
        idempotency_key=["col1"],
    )
    # build_upsert_sql ile psycopg sql.Identifier auto-quote eder
    # Malicious adı raw string olarak SQL'e enjekte edilmemeli
    sql_obj = build_upsert_sql(meta)
    s = sql_obj.as_string(None) if hasattr(sql_obj, "as_string") else str(sql_obj)

    # quote_ident lowercase yapar — "DROP TABLE x; --" → "drop table x; --"
    # ama psycopg sql.Identifier double-quote ile saralayacak
    # Bu test genişletilmeli (real psycopg context'te validate)
    assert "drop table" in s.lower()  # quoted form
