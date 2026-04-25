"""CI gate: Test Quality check.

Loads policy_test_quality.v1.json, scans test files for fake-test patterns,
computes quality metrics (shallow ratio, assertion density, duplication ratio),
compares against policy thresholds, and outputs a JSON report.

Exit code 0 = pass, non-zero = fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.shared.utils import now_iso8601

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_GLOBS = ["**/*.test.tsx", "**/*.test.ts", "**/*.spec.tsx", "**/*.spec.ts", "**/*_test.tsx", "**/*_test.ts"]
EXCLUDE_DIRS = {"node_modules", "__snapshots__", ".cache", "dist", "build"}

SHALLOW_ASSERTIONS = {
    "toBeInTheDocument", "toBeVisible", "toBeTruthy",
    "toMatchSnapshot", "toMatchInlineSnapshot",
}
INTERACTION_CALLS = {"fireEvent", "userEvent", "rerender", "waitFor", "act"}
TAUTOLOGICAL_RE = re.compile(
    r"expect\s*\(\s*(true|false|1|0|'[^']*'|\"[^\"]*\")\s*\)\s*\.\s*toBe\s*\(\s*\1\s*\)"
)
MARKER_RE = re.compile(r"quality-edge-boost|auto-generated-test|test-scaffold|bulk-test-gen")
MOCK_RE = re.compile(r"\bvi\.mock\b|\bjest\.mock\b")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test quality gate")
    p.add_argument("--repo-root", required=True)
    p.add_argument("--scan-path", default=None, help="Override scan path (default: repo-root)")
    p.add_argument("--policy-path", default=None)
    p.add_argument("--out", default=None, help="Output JSON report path")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def _find_test_files(scan_root: Path) -> list[Path]:
    """Find test files, excluding common non-test directories."""
    files: list[Path] = []
    for glob_pattern in TEST_GLOBS:
        # rglob expects pattern without leading **/
        clean = glob_pattern.removeprefix("**/")
        for f in scan_root.rglob(clean):
            if any(ex in f.parts for ex in EXCLUDE_DIRS):
                continue
            files.append(f)
    return sorted(set(files))


def _normalize_body(content: str) -> str:
    """Normalize test body for duplication detection.

    Strips comments, normalizes whitespace, removes test titles,
    and normalizes import paths.
    """
    lines = content.splitlines()
    stripped: list[str] = []
    for line in lines:
        line = re.sub(r"//.*$", "", line)  # single-line comments
        line = re.sub(r"/\*.*?\*/", "", line)  # inline block comments
        line = line.strip()
        if not line:
            continue
        # Remove test titles: test('...', / it('...', / describe('...',
        line = re.sub(r"(test|it|describe)\s*\(\s*['\"].*?['\"]\s*,", r"\1(,", line)
        # Normalize import paths
        line = re.sub(r"from\s+['\"].*?['\"]", "from '...'", line)
        # Normalize whitespace
        line = re.sub(r"\s+", " ", line)
        stripped.append(line)
    return "\n".join(stripped)


def _extract_component_from_filename(filepath: Path) -> str | None:
    """Extract expected component name from test filename."""
    stem = filepath.stem
    for suffix in [".test", ".spec"]:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    # PascalCase or kebab-case
    if stem and stem[0].isupper():
        return stem
    # kebab to PascalCase
    parts = stem.split("-")
    if len(parts) > 1:
        return "".join(p.capitalize() for p in parts)
    return stem.capitalize() if stem else None


# ---------------------------------------------------------------------------
# Analyzers
# ---------------------------------------------------------------------------

def _analyze_file(filepath: Path) -> dict:
    """Analyze a single test file for quality signals."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    result: dict = {
        "path": str(filepath),
        "issues": [],
        "assertion_count": 0,
        "interaction_count": 0,
        "mock_count": 0,
        "is_shallow": False,
        "has_tautological": False,
        "has_marker": False,
        "has_import_mismatch": False,
        "normalized_hash": "",
    }

    # Count assertions
    expect_count = len(re.findall(r"\bexpect\s*\(", content))
    result["assertion_count"] = expect_count

    # Count interactions
    for call in INTERACTION_CALLS:
        result["interaction_count"] += len(re.findall(rf"\b{call}\b", content))

    # Count mocks
    result["mock_count"] = len(MOCK_RE.findall(content))

    # Shallow render detection (for metric calculation only — violation via EP-006/enforcement script)
    has_render = bool(re.search(r"\brender\s*\(", content))
    shallow_only = True
    if has_render and expect_count > 0:
        for line in lines:
            line_stripped = line.strip()
            if "expect(" in line_stripped:
                is_shallow_assertion = any(
                    sa in line_stripped for sa in SHALLOW_ASSERTIONS
                )
                if not is_shallow_assertion:
                    shallow_only = False
                    break
        if shallow_only and result["interaction_count"] == 0:
            result["is_shallow"] = True

    # Tautological detection (for metric only — violation via EP-007/enforcement script)
    if TAUTOLOGICAL_RE.search(content):
        result["has_tautological"] = True

    # Marker detection (for metric only — violation via EP-008/enforcement script)
    if MARKER_RE.search(content):
        result["has_marker"] = True

    # Check import mismatch (TQ-004)
    expected_component = _extract_component_from_filename(filepath)
    if expected_component:
        import_re = re.compile(
            rf"\bimport\b.*\b{re.escape(expected_component)}\b", re.IGNORECASE
        )
        if not import_re.search(content):
            result["has_import_mismatch"] = True
            result["issues"].append({
                "rule": "TQ-004",
                "message": f"Expected import of '{expected_component}' not found",
            })

    # Check mock-heavy (TQ-005)
    if result["mock_count"] > 3 and result["interaction_count"] == 0:
        mock_ratio = result["mock_count"] / max(result["assertion_count"], 1)
        if mock_ratio > 0.8:
            result["issues"].append({
                "rule": "TQ-005",
                "message": f"Mock-heavy test (mock_ratio={mock_ratio:.2f}, zero interactions)",
            })

    # Normalized hash for duplication (TQ-003)
    normalized = _normalize_body(content)
    result["normalized_hash"] = hashlib.sha256(normalized.encode()).hexdigest()

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    scan_root = Path(args.scan_path).resolve() if args.scan_path else repo_root

    # Load policy
    policy_path = Path(args.policy_path) if args.policy_path else repo_root / "policies" / "policy_test_quality.v1.json"
    if policy_path.exists():
        with open(policy_path) as f:
            policy = json.load(f)
        thresholds = policy.get("thresholds", {})
    else:
        thresholds = {"max_shallow_render_ratio": 0.10, "min_assertion_density": 2.0, "max_duplication_ratio": 0.05}

    # Find and analyze test files
    test_files = _find_test_files(scan_root)
    results = [_analyze_file(f) for f in test_files]
    total = len(results)

    if total == 0:
        report = {
            "version": "v1",
            "generated_at": now_iso8601(),
            "status": "PASS",
            "scan_root": str(scan_root),
            "files_scanned": 0,
            "metrics": {},
            "violations": [],
            "notes": ["no_test_files_found"],
        }
        _write_report(report, args.out)
        print(json.dumps(report, indent=2))
        return 0

    # Compute metrics
    shallow_count = sum(1 for r in results if r["is_shallow"])
    tautological_count = sum(1 for r in results if r["has_tautological"])
    marker_count = sum(1 for r in results if r["has_marker"])
    import_mismatch_count = sum(1 for r in results if r["has_import_mismatch"])

    total_assertions = sum(r["assertion_count"] for r in results)
    test_case_count = max(total, 1)
    assertion_density = total_assertions / test_case_count

    # Duplication detection (TQ-003)
    hash_groups: dict[str, list[str]] = {}
    for r in results:
        h = r["normalized_hash"]
        if h:
            hash_groups.setdefault(h, []).append(r["path"])
    duplicate_groups = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}
    duplicate_file_count = sum(len(paths) for paths in duplicate_groups.values())

    shallow_ratio = shallow_count / total
    duplication_ratio = duplicate_file_count / total

    # Collect all violations
    violations: list[dict] = []
    for r in results:
        for issue in r["issues"]:
            violations.append({"file": r["path"], **issue})
    for h, paths in duplicate_groups.items():
        for p in paths:
            violations.append({"file": p, "rule": "TQ-003", "message": f"Duplicate body (hash={h[:12]}..., {len(paths)} files)"})

    # Threshold check
    threshold_failures: list[str] = []
    max_shallow = thresholds.get("max_shallow_render_ratio", 0.10)
    min_density = thresholds.get("min_assertion_density", 2.0)
    max_dup = thresholds.get("max_duplication_ratio", 0.05)

    if shallow_ratio > max_shallow:
        threshold_failures.append(f"shallow_render_ratio={shallow_ratio:.3f} > {max_shallow}")
    if assertion_density < min_density:
        threshold_failures.append(f"assertion_density={assertion_density:.2f} < {min_density}")
    if duplication_ratio > max_dup:
        threshold_failures.append(f"duplication_ratio={duplication_ratio:.3f} > {max_dup}")

    status = "FAIL" if (threshold_failures or marker_count > 0) else "PASS"
    if args.dry_run:
        status = f"DRY_RUN_{status}"

    metrics = {
        "files_scanned": total,
        "shallow_count": shallow_count,
        "shallow_ratio": round(shallow_ratio, 4),
        "tautological_count": tautological_count,
        "marker_count": marker_count,
        "import_mismatch_count": import_mismatch_count,
        "total_assertions": total_assertions,
        "assertion_density": round(assertion_density, 2),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_file_count": duplicate_file_count,
        "duplication_ratio": round(duplication_ratio, 4),
    }

    report = {
        "version": "v1",
        "generated_at": now_iso8601(),
        "status": status,
        "scan_root": str(scan_root),
        "files_scanned": total,
        "metrics": metrics,
        "thresholds": thresholds,
        "threshold_failures": threshold_failures,
        "violations_count": len(violations),
        "violations": violations[:50],
        "duplicate_groups_count": len(duplicate_groups),
    }

    _write_report(report, args.out)
    print(json.dumps(report, indent=2))
    return 0 if "PASS" in status else 1


def _write_report(report: dict, out_path: str | None) -> None:
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
