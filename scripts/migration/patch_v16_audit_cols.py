"""Faz 16.3 Gün 7 iter-7 — patch V16__reports.sql to add ETL idempotency
lineage columns (source_table + source_pk) and a UNIQUE index on
(source_schema, source_table, source_pk) to every canonical
`workcube_mikrolink.*` table.

Why this script exists
----------------------
The original generator (`scripts/migration/generate_v16_sql.py`) was
updated in the same commit to emit these columns. But regenerating
V16__reports.sql requires the source schema-service snapshot JSON, which
is NOT committed to this repo. This patcher is a one-shot transform
applied to the existing V16__reports.sql so the file matches what the
new generator would produce on a rerun. Future generator runs (post Faz
16.2.P) will produce identical output.

Idempotent: running twice is a no-op (skips tables that already have
`source_table` column).

Usage:
  python3 scripts/migration/patch_v16_audit_cols.py \
      sql/migration/V16__reports.sql
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Match a canonical table block: from `CREATE TABLE workcube_mikrolink.<name> (`
# down to the matching `);`. We patch the trailing audit/PK section.
CANONICAL_BLOCK = re.compile(
    r"(CREATE TABLE workcube_mikrolink\.(\w+) \(.*?)"
    r"(    content_hash VARCHAR\(64\) NOT NULL,\n"
    r"    migration_row_id BIGSERIAL,  -- surrogate \(PK metadata snapshot'ta yok, Codex iter-4\)\n"
    r"    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now\(\),\n"
    r"    PRIMARY KEY \(migration_row_id\)  -- TODO: business PK manual review\n)"
    r"(\);\n\nCREATE INDEX idx_(\w+)_hash ON workcube_mikrolink\.(\w+) \(content_hash\);)",
    re.DOTALL,
)

NEW_AUDIT_BLOCK = (
    "    source_table VARCHAR(128) NOT NULL,\n"
    "    source_pk TEXT NOT NULL,\n"
    "    content_hash VARCHAR(64) NOT NULL,\n"
    "    migration_row_id BIGSERIAL,  -- surrogate (PK metadata snapshot'ta yok, Codex iter-4)\n"
    "    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n"
    "    PRIMARY KEY (migration_row_id),\n"
    "    UNIQUE (source_schema, source_table, source_pk)\n"
)


def patch(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    patched_count = 0
    skipped_count = 0

    def replace(m: re.Match) -> str:
        nonlocal patched_count, skipped_count
        head, table_name, _audit_block, tail, idx_table_a, idx_table_b = m.groups()
        # Idempotency: if head already mentions `source_table VARCHAR`, skip.
        if "source_table VARCHAR(128) NOT NULL" in head:
            skipped_count += 1
            return m.group(0)
        patched_count += 1
        new_tail = (
            tail
            + f"\nCREATE INDEX idx_{idx_table_a}_lineage ON workcube_mikrolink.{idx_table_b}"
            f" (source_schema, source_table, source_pk);"
        )
        return head + NEW_AUDIT_BLOCK + new_tail

    new_text = CANONICAL_BLOCK.sub(replace, text)
    if patched_count == 0 and skipped_count == 0:
        raise RuntimeError(
            "No canonical workcube_mikrolink.* tables found — "
            "regex pattern may need an update."
        )
    if patched_count > 0:
        path.write_text(new_text, encoding="utf-8")
    return patched_count, skipped_count


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: patch_v16_audit_cols.py <V16__reports.sql>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    patched, skipped = patch(path)
    print(f"patched={patched} skipped={skipped} (file: {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
