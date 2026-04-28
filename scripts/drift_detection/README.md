# Drift Detection — ADR-0011 DD-1

Plan-time + CI-time guards for V25/V26 anchor table contract drift.

Codex thread `019dd409` PARTIAL/AGREE-with-revisions strategy:
catch contract drift at PR review (workflow path filter) + on stale main
(weekly cron) + on demand (`workflow_dispatch`) — not at live-load test.

## Scripts

### `check_drift_anchor_table.py`

6 check fonksiyonu, exit 0/1 + structured JSON output:

1. **V25 CHECK constraint pairs** — `scope_kind_source_table_consistent`
   4 pair (company→OUR_COMPANY, project→PRO_PROJECTS, branch→BRANCH, depot→DEPARTMENT).
2. **V25+V26 validate_scope_ref() anchor** — final function company branch
   references `workcube_mikrolink.our_company` (not `.company` directory).
3. **V25 organization_company default + CHECK** — `source_table = 'OUR_COMPANY'`.
4. **V26 dual-format predicate** — `(source_pk = v_pk OR source_pk = p_ref)`
   in all 4 kind branches.
5. **workcube-schema.json anchor tables** — 5 anchor table presence + minimum
   columns (OUR_COMPANY.COMP_ID, COMPANY.COMPANY_ID/OUR_COMPANY_ID, BRANCH.COMPANY_ID,
   DEPARTMENT.OUR_COMPANY_ID, PRO_PROJECTS.COMPANY_ID).
6. **ADR-0008 § Object id encoding** — V25 transition map with `wc-our-company-`
   namespace + `OUR_COMPANY` anchor mention + `workcube_mikrolink.our_company`
   table reference.

```bash
# Default — current main repo state should produce 6/6 PASS
python3 scripts/drift_detection/check_drift_anchor_table.py
python3 scripts/drift_detection/check_drift_anchor_table.py --verbose
python3 scripts/drift_detection/check_drift_anchor_table.py --json > drift-report.json

# Negative test — fixture deliberately regresses V25 anchor
python3 scripts/drift_detection/check_drift_anchor_table.py \
  --v25-path tests/drift_detection/fixtures/V25_company_anchor_regression.sql
# → exit 1 + 3 checks fail (CHECK constraint, anchor, organization_company default)
```

## Tests

```bash
python3 -m unittest tests.drift_detection.test_check_drift_anchor_table -v
```

Coverage:
- `TestPositiveRun` — current main = all 6 checks PASS
- `TestNegativeRegression` — fixture regression triggers 3+ check failures
- `TestSqlParserHelpers` — parser smoke (`strip_sql_comments`, `extract_function_body`)

## Workflow

`.github/workflows/gate-drift-detection.yml` — triggers:

- `workflow_dispatch` (manuel)
- `schedule` weekly Mon 03:30 UTC
- `pull_request` paths: `sql/migration/V*.sql`, `docs/migration/workcube-schema.json`,
  `docs/adr/0008-*.md`, `docs/adr/0011-*.md`, scripts/tests directory

Failure → CI red. If `gate-drift-detection` is set as required check on
`main` branch protection, blocks merge of any data_access schema change PR
that introduces drift.

## Authority

Codex consensus only — no operator approval. Read-only static analysis,
no state mutation, no credential read.

## DD-2 — ETL canonical JSON contract guard

`check_drift_etl_contract.py` — ETL `make_source_pk()` canonical output ↔ DB
side (V26 final function + V16/V17 lineage TEXT contract) symmetric guard.

6 check fonksiyonu:

1. **`make_source_pk_static_contract`** — AST/source body kontratı (json.dumps
   + canonical separators + ensure_ascii=False + None preservation)
2. **`make_source_pk_runtime_outputs`** — import + sample calls (5 sample:
   single, composite, None, non-ASCII, COMP_ID)
3. **`make_source_pk_unit_tests_present`** — `test_transform.py` exact
   canonical assertions (3 cases)
4. **`v26_accepts_etl_canonical_p_ref`** — V26 final function her branch'te
   `alias.source_pk = p_ref` canonical + `= v_pk` raw fallback acceptance
5. **`pg_lineage_source_pk_text_contract`** — V16/V17 anchor tables `source_pk
   TEXT` + UNIQUE INDEX (source_schema, source_table, source_pk)
6. **`anchor_idempotency_keys_documented`** — `tables.yaml` 5 anchor entry
   `idempotency_key` map + `validation.fail_on_pk_mismatch` flag

```bash
python3 scripts/drift_detection/check_drift_etl_contract.py
python3 scripts/drift_detection/check_drift_etl_contract.py --verbose --json

# Negative regression tests
python3 scripts/drift_detection/check_drift_etl_contract.py \
  --transform-path tests/drift_detection/fixtures/transform_etl_contract_regression.py
# → 2 checks fail (static + runtime)

python3 scripts/drift_detection/check_drift_etl_contract.py \
  --v26-path tests/drift_detection/fixtures/V26_no_canonical_p_ref_regression.sql
# → 1 check fail (v26_accepts_etl_canonical_p_ref)

python3 -m unittest tests.drift_detection.test_check_drift_etl_contract -v
```

## DD-3 — Schema-service snapshot drift (operator-loop)

`check_drift_reports_db_snapshot.py` — committed source snapshot
(`workcube-schema.json`) ile canlı PG `reports_db.workcube_mikrolink.*`
actual schema arasındaki **runtime drift**'i yakalar. Quarterly cadence.

**Operator-loop**: artifact (`docs/migration/reports-db-workcube-actual-schema.json`)
operatör tarafından read-only psql export ile üretilir + PR olarak commit
edilir. Runbook: `docs/RB-faz-21-3-adr-0011-dd-3-schema-snapshot.md`.

**Graceful pending state**: artifact yoksa script `PENDING` raporlar +
exit 0 (CI green). Artifact varsa hard validation:

1. `actual_artifact_present` — dosya var mı?
2. `actual_artifact_freshness` — ≤120 days
3. `actual_artifact_source_hash_match` — `source_snapshot_sha256` field current `workcube-schema.json` SHA'ya eşit
4. `etl_managed_tables_in_source` — `tables.yaml` ETL-managed entry'leri source'ta var
5. `etl_managed_tables_in_actual` — aynı entry'ler PG actual'da var
6. `pg_lineage_columns_present` — V17 lineage cols (`source_schema, source_table, source_pk, content_hash`)

```bash
# PENDING state (default — current main, no artifact)
python3 scripts/drift_detection/check_drift_reports_db_snapshot.py --verbose

# Strict mode (PENDING treated as fail)
python3 scripts/drift_detection/check_drift_reports_db_snapshot.py --strict

python3 -m unittest tests.drift_detection.test_check_drift_reports_db_snapshot -v
```

Workflow: `.github/workflows/gate-drift-schema-service-snapshot.yml`
(quarterly cron + workflow_dispatch + `pull_request` paths filter; ayrı
workflow çünkü cadence + boundary semantiği farklı).

## DD-4 — env + Dockerfile + Python compat lint

`check_drift_env_dockerfile.py` — Session 32 drift events 2'sini kapsar
(etl-worker env prefix + Dockerfile signing convention). 5 check:

1. **`env_prefix_consistency`** — config.py fallback hierarchy 4 prefix
   içeriyor (MSSQL_, REPORT_MSSQL_, SCHEMA_MSSQL_, WORKCUBE_MSSQL_)
2. **`python_version_compat`** — Python 3.12 tutarlılığı (pyproject
   requires-python + ruff target + mypy + Dockerfile FROM + workflow
   python-version)
3. **`dockerfile_keyring_signing`** — msodbcsql18 install + signed-by= +
   gpg --dearmor pattern (Debian 12 Bookworm sqv-based verification)
4. **`tables_yaml_schema_validity`** — minimum field set (name,
   source_schema, columns, idempotency_key, parametric, reports) +
   3 validation flag
5. **`readme_docs_sync`** — make_source_pk + env prefix references
   (warn-only)

```bash
python3 scripts/drift_detection/check_drift_env_dockerfile.py --verbose
python3 scripts/drift_detection/check_drift_env_dockerfile.py --json

# Negative tests
python3 scripts/drift_detection/check_drift_env_dockerfile.py \
  --config-path tests/drift_detection/fixtures/config_dd4_missing_prefix.py
# → env_prefix_consistency fail

python3 scripts/drift_detection/check_drift_env_dockerfile.py \
  --dockerfile-path tests/drift_detection/fixtures/Dockerfile_dd4_no_signed_by.txt
# → dockerfile_keyring_signing fail

python3 -m unittest tests.drift_detection.test_check_drift_env_dockerfile -v
```

DD-4 umbrella workflow'a entegre (`gate-drift-detection.yml` — DD-1 + DD-2 + DD-4 birlikte).

## Roadmap (next DD/AC/BG PRs)

- **DD-4**: env-prefix + Python compat + Dockerfile keyring lint.
- **AC-1**: drill evidence template + first-drill runbook.
- **BG-1**: per-PR boundary declaration template + check_pr_description CI gate.
- **BG-2**: sandbox-blocking pattern playbook + 3 gray-area resolution docs.

## References

- ADR-0011 § 2.1.1 (anchor table / Workcube schema verification)
- ADR-0008 § Object id encoding (V25 transition map)
- Codex thread `019dd409` (DD-1 spec PARTIAL/AGREE-with-revisions)
