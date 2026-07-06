"""Spec YAML validation against config/cross_repo_enum_drift_spec.schema.json.

ADR-0031 §I5: duplicate id, unknown kind, missing field, zero mirrors,
java_grid_column_case_literals without anchor → exit 2 BEFORE any gh api fetch.

This module assumes `jsonschema` is pip-installed by the workflow runner (the
existing `gate-outdated-software-contract.yml:40` pattern; we mirror it).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


class SpecValidationError(ValueError):
    """Raised when the spec YAML fails schema or semantic validation."""


def load_spec_schema(schema_path: Path) -> dict[str, Any]:
    with schema_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_spec(spec: dict[str, Any], schema: dict[str, Any]) -> None:
    """Raise SpecValidationError on any structural or semantic violation."""
    try:
        import jsonschema  # type: ignore
    except ImportError as exc:  # pragma: no cover — caller installs in CI
        raise SpecValidationError(
            "jsonschema package required (pip install jsonschema)"
        ) from exc

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(spec), key=lambda e: e.path)
    if errors:
        formatted = []
        for err in errors:
            path = "/".join(str(p) for p in err.absolute_path) or "<root>"
            formatted.append(f"  - {path}: {err.message}")
        raise SpecValidationError(
            "spec schema validation failed:\n" + "\n".join(formatted)
        )

    # Cross-mapping semantic check: duplicate id.
    ids = [m["id"] for m in spec.get("mappings", [])]
    dupes = [k for k, v in Counter(ids).items() if v > 1]
    if dupes:
        raise SpecValidationError(
            f"duplicate mapping id(s) in spec: {sorted(dupes)!r}"
        )
