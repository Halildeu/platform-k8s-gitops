"""Faz 16.3 — ETL Worker config (env + DSN)."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    # MSSQL source (Workcube)
    mssql_dsn: str  # ODBC connection string
    mssql_database: str  # workcube_mikrolink

    # PG target
    pg_dsn: str  # postgresql://user:pass@host:port/db

    # Worker settings
    batch_size: int = 10000
    max_reject_ratio: float = 0.0  # cutover: 0; dry-run: 0.05
    log_level: str = "INFO"

    # Worker identity
    worker_version: str = "0.1.0"
    git_sha: str = "unknown"
    contract_version: str = "v1.0-DRAFT"
    annex_version: str = "2A-2026-04-25"

    @classmethod
    def from_env(cls) -> "Config":
        mssql_host = os.environ.get("MSSQL_HOST", "10.9.193.201")
        mssql_port = os.environ.get("MSSQL_PORT", "1433")
        mssql_user = os.environ.get("MSSQL_USER", "AlUser_App")
        mssql_password = os.environ.get("MSSQL_PASSWORD", "")
        mssql_db = os.environ.get("MSSQL_DATABASE", "workcube_mikrolink")
        mssql_domain = os.environ.get("MSSQL_DOMAIN", "boreas")

        # NTLM authentication için ODBC string
        mssql_dsn = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={mssql_host},{mssql_port};"
            f"DATABASE={mssql_db};"
            f"UID={mssql_user};"
            f"PWD={mssql_password};"
            f"TrustServerCertificate=yes;"
            f"Encrypt=yes;"
            f"AuthenticationScheme=NTLM;"
            f"Domain={mssql_domain};"
        )

        pg_host = os.environ.get("PG_HOST", "postgres")
        pg_port = os.environ.get("PG_PORT", "5432")
        pg_user = os.environ.get("PG_USER", "postgres")
        pg_password = os.environ.get("PG_PASSWORD", "")
        pg_db = os.environ.get("PG_DATABASE", "reports_db")

        pg_dsn = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"

        return cls(
            mssql_dsn=mssql_dsn,
            mssql_database=mssql_db,
            pg_dsn=pg_dsn,
            batch_size=int(os.environ.get("ETL_BATCH_SIZE", "10000")),
            max_reject_ratio=float(os.environ.get("ETL_MAX_REJECT_RATIO", "0.0")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            worker_version="0.1.0",
            git_sha=os.environ.get("GIT_SHA", "unknown"),
        )
