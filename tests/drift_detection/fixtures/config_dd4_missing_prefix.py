"""DD-4 negative fixture: config.py with missing env prefix (SCHEMA_MSSQL_ removed)."""
import os


def from_env():
    def _env_first(*names: str, default: str = "") -> str:
        for name in names:
            v = os.environ.get(name)
            if v:
                return v
        return default

    # Missing SCHEMA_MSSQL_* — only 3 prefixes
    mssql_host = _env_first(
        "MSSQL_HOST", "REPORT_MSSQL_HOST", "WORKCUBE_MSSQL_HOST",
        default="0.0.0.0",
    )
    mssql_user = _env_first(
        "MSSQL_USER", "REPORT_MSSQL_USER", "WORKCUBE_MSSQL_USER",
    )
    mssql_password = _env_first(
        "MSSQL_PASSWORD", "REPORT_MSSQL_PASSWORD", "WORKCUBE_MSSQL_PASSWORD",
    )
    return mssql_host, mssql_user, mssql_password
