"""Cross-repo enum drift guard library — ADR-0031 DD-5-1.

Modules:
    parsers           — five strategies (java_enum, java_set_of, ts_const_tuple,
                        ts_union_type, java_grid_column_case_literals).
    spec_validator    — JSON Schema validation of cross_repo_enum_drift_spec.yaml.
    fetcher           — gh api wrapper with process-scoped cache.
    paired_pr         — paired-PR protocol parsing + canonical-first invariant.
    reporter          — JSON artifact + Markdown step summary emission.
"""
