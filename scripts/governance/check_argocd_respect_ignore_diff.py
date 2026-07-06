#!/usr/bin/env python3
"""
ArgoCD ``RespectIgnoreDifferences`` + Blanket ``/metadata`` Anti-pattern Gate.

Codex thread ``019e41d7`` AGREE — Session 42 (2026-05-19) bug class fix:
PR #850 (``platform-eso-prod``) + PR #851 (``platform-prod``) sealed the
``metadata.managedFields must be nil`` Server-Side-Apply failure caused by
the combination of:

    syncOptions:
      - ServerSideApply=true
      - RespectIgnoreDifferences=true        # opts in to ignoreDifferences
    ignoreDifferences:
      - kind: <Any CRD>
        jsonPointers:
          - /metadata                        # blanket → swallows managedFields

ArgoCD ``RespectIgnoreDifferences`` makes ignoreDifferences participate in
the desired-state SSA body (not just the diff view). When a blanket
``/metadata`` pointer is in the ignore list, ArgoCD relocates the live
``/metadata`` block — including ``managedFields`` — onto the SSA apply
payload. ``managedFields`` MUST be ``nil`` in any SSA body; otherwise the
API server rejects the apply with ``metadata.managedFields must be nil``
and the entire sync transitions to Failed/OutOfSync/Degraded.

This gate is a PR-time static analysis check that blocks the pattern from
re-entering the codebase. Codex thread ``019e4216`` AGREE_WITH_REVISIONS
defined the matching contract:

- Risk mode trigger: ``RespectIgnoreDifferences=true`` in
  ``spec.syncPolicy.syncOptions``.
- Fail (in risk mode) when any ``spec.ignoreDifferences[].jsonPointers`` or
  ``jqPathExpressions`` matches:
    * JSON pointer exact ``/metadata``
    * JSON pointer exact ``/metadata/managedFields``
    * JSON pointer prefix ``/metadata/managedFields/``
    * Broad container pointers ``/metadata/annotations`` and
      ``/metadata/labels`` with no further segment (those are containers,
      not specific keys, so they still propagate ``/metadata`` semantics)
    * jq exact ``.metadata``
    * jq exact ``.metadata.managedFields`` (and managedFields descendants)
- Pass:
    * ``/status``
    * ``/spec/replicas``
    * ``/metadata/annotations/<escaped specific key>`` (any further segment
      after ``/metadata/annotations/``)
    * ``/metadata/labels/<escaped specific key>``
    * ``/metadata/finalizers`` (exception, documented in the operations doc
      as not-blanket-metadata)
    * Any ignoreDifferences entry while RespectIgnoreDifferences is OFF.

Scope:
    Only ``kind: Application`` documents under ``argocd/applications/``.

Usage::

    python3 scripts/governance/check_argocd_respect_ignore_diff.py [options]

Options::

    --verbose              Detailed per-file log
    --json                 Structured JSON output (CI artifact friendly)
    --fixture PATH         Single fixture file (test mode)
    --repo-root PATH       Override repo root (default: script grand-parent)

Exit codes::

    0 = no offending pattern detected
    1 = at least one ArgoCD Application carries the anti-pattern
    2 = invocation error (file missing, parse error)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

RESPECT_OPTION = "RespectIgnoreDifferences=true"

# Exact JSON pointer matches that count as blanket metadata.
BLANKET_POINTER_EXACT: frozenset[str] = frozenset(
    {
        "/metadata",
        "/metadata/managedFields",
        # Broad containers — no specific key segment after the container.
        "/metadata/annotations",
        "/metadata/labels",
    }
)

# JSON pointer prefixes that count as blanket metadata.
BLANKET_POINTER_PREFIXES: tuple[str, ...] = ("/metadata/managedFields/",)

# Specific-key-segment containers that — when extended with a further
# segment — flip from blanket to allow.
SPECIFIC_KEY_CONTAINERS: tuple[str, ...] = (
    "/metadata/annotations/",
    "/metadata/labels/",
)

# Pointers explicitly documented as not-blanket-metadata exceptions.
EXPLICIT_ALLOWED_POINTERS: frozenset[str] = frozenset(
    {
        "/metadata/finalizers",
    }
)

# jq path expressions that count as blanket metadata.
BLANKET_JQ_EXACT: frozenset[str] = frozenset(
    {
        ".metadata",
        ".metadata.managedFields",
    }
)

# Substrings inside a jq path expression that mark a managedFields
# descendant (rare but possible).
BLANKET_JQ_SUBSTRINGS: tuple[str, ...] = (
    ".metadata.managedFields",
    ".metadata|.managedFields",
    ".metadata | .managedFields",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "ArgoCD RespectIgnoreDifferences + blanket /metadata ignore "
            "anti-pattern gate"
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed log")
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Structured JSON output",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Single fixture file (test mode)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent.parent),
        help="Repo root path (default: script grand-parent)",
    )
    return parser.parse_args()


def find_applications(repo_root: Path) -> list[Path]:
    """Return ArgoCD Application manifest candidates."""
    base = repo_root / "argocd" / "applications"
    if not base.exists():
        return []
    return sorted(base.rglob("*.yaml"))


def _is_blanket_pointer(pointer: str) -> bool:
    if pointer in EXPLICIT_ALLOWED_POINTERS:
        return False
    if pointer in BLANKET_POINTER_EXACT:
        return True
    if any(pointer.startswith(prefix) for prefix in BLANKET_POINTER_PREFIXES):
        return True
    # `/metadata/annotations/<specific-key>` and `/metadata/labels/<specific-key>`
    # are allowed only when there is a key segment after the container slash.
    for container in SPECIFIC_KEY_CONTAINERS:
        if pointer == container.rstrip("/"):
            # Already covered by BLANKET_POINTER_EXACT; safety net.
            return True
        if pointer.startswith(container) and len(pointer) > len(container):
            return False
    return False


def _is_blanket_jq(expression: str) -> bool:
    if expression in BLANKET_JQ_EXACT:
        return True
    for marker in BLANKET_JQ_SUBSTRINGS:
        if marker in expression:
            return True
    return False


def _entry_ref(entry: dict[str, Any]) -> str:
    """Human-readable reference for an ignoreDifferences entry."""
    parts = []
    for key in ("group", "kind", "namespace", "name"):
        value = entry.get(key)
        if value:
            parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "(unscoped entry)"


def check_application_doc(
    doc: dict[str, Any], path: Path
) -> tuple[bool, list[dict[str, Any]]]:
    """Return (respect_on, violations) for one Application document."""
    violations: list[dict[str, Any]] = []
    if not isinstance(doc, dict):
        return False, violations
    if doc.get("kind") != "Application":
        return False, violations

    spec = doc.get("spec") or {}
    sync_policy = spec.get("syncPolicy") or {}
    sync_options = sync_policy.get("syncOptions") or []
    respect_on = RESPECT_OPTION in sync_options
    if not respect_on:
        return False, violations

    app_name = (doc.get("metadata") or {}).get("name") or "(unnamed)"

    for entry in spec.get("ignoreDifferences") or []:
        if not isinstance(entry, dict):
            continue
        entry_ref = _entry_ref(entry)
        for pointer in entry.get("jsonPointers") or []:
            if not isinstance(pointer, str):
                continue
            if _is_blanket_pointer(pointer):
                violations.append(
                    {
                        "file": str(path),
                        "application": app_name,
                        "entry": entry_ref,
                        "kind": "jsonPointer",
                        "value": pointer,
                        "remediation": (
                            "Narrow to /status, /spec/replicas, or a "
                            "specific /metadata/annotations/<key> path; "
                            "see docs/operations/"
                            "argocd-respect-ignore-diff-antipattern.md"
                        ),
                        "references": "Codex 019e41d7, PR #850, PR #851",
                    }
                )
        for expression in entry.get("jqPathExpressions") or []:
            if not isinstance(expression, str):
                continue
            if _is_blanket_jq(expression):
                violations.append(
                    {
                        "file": str(path),
                        "application": app_name,
                        "entry": entry_ref,
                        "kind": "jqPathExpression",
                        "value": expression,
                        "remediation": (
                            "Target a specific field (e.g. "
                            ".spec.data[].remoteRef.conversionStrategy) "
                            "instead of .metadata.* — see docs/operations/"
                            "argocd-respect-ignore-diff-antipattern.md"
                        ),
                        "references": "Codex 019e41d7, PR #850, PR #851",
                    }
                )

    return respect_on, violations


def check_file(path: Path) -> tuple[int, list[dict[str, Any]], list[str]]:
    """Return (apps_with_respect_on, violations, parse_errors)."""
    violations: list[dict[str, Any]] = []
    errors: list[str] = []
    respect_on_count = 0
    try:
        with path.open() as f:
            docs = list(yaml.safe_load_all(f))
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"{path}: parse error — {exc}")
        return 0, violations, errors

    for doc in docs:
        respect_on, file_violations = check_application_doc(doc, path)
        if respect_on:
            respect_on_count += 1
        violations.extend(file_violations)

    return respect_on_count, violations, errors


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    if args.fixture:
        manifests = [Path(args.fixture).resolve()]
    else:
        manifests = find_applications(repo_root)

    if args.verbose:
        print(
            f"[argocd-respect-ignore-diff] repo_root: {repo_root}",
            file=sys.stderr,
        )
        print(
            f"[argocd-respect-ignore-diff] manifests scanned: {len(manifests)}",
            file=sys.stderr,
        )
        for m in manifests:
            try:
                rel = m.relative_to(repo_root)
            except ValueError:
                rel = m
            print(f"  - {rel}", file=sys.stderr)

    total_respect_on = 0
    all_violations: list[dict[str, Any]] = []
    all_errors: list[str] = []

    for m in manifests:
        respect_on, violations, errors = check_file(m)
        total_respect_on += respect_on
        all_violations.extend(violations)
        all_errors.extend(errors)

    verdict = "pass" if not all_violations and not all_errors else "fail"

    if args.json_output:
        result = {
            "check": "argocd-respect-ignore-diff",
            "scope": (
                "argocd/applications/*.yaml — block "
                "RespectIgnoreDifferences=true + blanket /metadata ignore"
            ),
            "manifests_scanned": len(manifests),
            "applications_with_respect_on": total_respect_on,
            "violations": all_violations,
            "parse_errors": all_errors,
            "verdict": verdict,
            "references": (
                "Codex 019e41d7, Codex 019e4216, PR #850, PR #851, "
                "docs/operations/argocd-respect-ignore-diff-antipattern.md"
            ),
        }
        print(json.dumps(result, indent=2))
    else:
        print(
            "argocd-respect-ignore-diff — "
            "block RespectIgnoreDifferences=true + blanket /metadata ignore"
        )
        print(f"  Manifests scanned: {len(manifests)}")
        print(f"  Applications with RespectIgnoreDifferences=true: "
              f"{total_respect_on}")
        if all_violations:
            print(f"  ✗ Violations ({len(all_violations)}):")
            for v in all_violations:
                print(
                    "    {file}: app={application} {entry} "
                    "{kind}={value}".format(**v)
                )
                print(f"      remediation: {v['remediation']}")
                print(f"      refs: {v['references']}")
        if all_errors:
            print(f"  ⚠ Parse errors ({len(all_errors)}):")
            for err in all_errors:
                print(f"    {err}")
        if args.verbose and not all_violations:
            print(
                "  ✓ All Applications with RespectIgnoreDifferences=true "
                "use targeted ignoreDifferences pointers"
            )
        print(f"  Verdict: {verdict.upper()}")

    if all_errors:
        return 2
    if all_violations:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
