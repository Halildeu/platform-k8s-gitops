"""CI gate: Enforcement Rules check (script-based, replaces regex-only semgrep rules).

Scans source files for policy violations using regex patterns.
Replaces semgrep for rules that don't need AST analysis.
Semgrep is retained only for EP-006, EP-009, EP-014 (AST required).

Exit code 0 = pass, non-zero = fail.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.shared.utils import now_iso8601

# ---------------------------------------------------------------------------
# Exclude sets
# ---------------------------------------------------------------------------
GLOBAL_EXCLUDES = {"node_modules", "__pycache__", ".cache", "dist", "build", ".git", ".claude"}
TEST_EXCLUDES = {"__tests__", "__mocks__"}

# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------
# Each rule: id, ep_id, message, severity, stage, globs, excludes, patterns, file_excludes
# patterns: list of compiled regex — any match = violation

RULES: list[dict[str, Any]] = [
    # --- Python orchestrator rules (EP-001..005) ---
    {
        "id": "EP-001",
        "message": "EP-001 Boundary Breach: prj_github_ops must not import prj_kernel_api.",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["src/prj_github_ops/**/*.py"],
        "file_excludes": [],
        "patterns": [
            re.compile(r"from\s+src\.prj_kernel_api\.|import\s+src\.prj_kernel_api"),
        ],
    },
    {
        "id": "EP-002",
        "message": "EP-002 Structure Align: extension folder name should match extension_id casing.",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["extensions/prj-github-ops/extension.manifest.v1.json",
                  "extensions/release-automation/extension.manifest.v1.json"],
        "file_excludes": [],
        "patterns": [
            re.compile(r'"extension_id"\s*:\s*"PRJ-(GITHUB-OPS|RELEASE-AUTOMATION)"'),
        ],
    },
    {
        "id": "EP-003",
        "message": "EP-003 Contract Drift: Use src.shared.utils instead of custom JSON/timestamp helpers.",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["src/**/*.py", "ci/**/*.py"],
        "file_excludes": ["src/shared/utils.py", "src/utils/jsonio.py", "*test*", "*contract*"],
        "patterns": [
            re.compile(r"def\s+_(?:load_json|dump_json|write_json|read_json)\s*\("),
            re.compile(r"def\s+_(?:now_iso|now_utc|now_iso_utc|iso_now)\s*\("),
        ],
    },
    {
        "id": "EP-004",
        "message": "EP-004 Allow-Path Hitchhiking: Use write_json_atomic() instead of direct path.write_text().",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["src/ops/**/*.py", "src/orchestrator/**/*.py", "src/shared/**/*.py"],
        "file_excludes": ["src/shared/utils.py", "src/shared/wal.py", "*test*", "*contract*"],
        "patterns": [
            re.compile(r"\.write_text\s*\("),
        ],
    },
    {
        "id": "EP-005",
        "message": "EP-005 Evidence Check: State transition call detected — ensure evidence recording.",
        "severity": "WARNING",
        "stage": "v1_advisory",
        "globs": ["src/ops/**/*.py", "src/orchestrator/**/*.py"],
        "file_excludes": ["src/evidence/**", "src/shared/wal.py", "*test*"],
        "patterns": [
            re.compile(r"validate_(?:transition|run_transition|node_transition)\("),
        ],
    },
    # --- TS/JS test quality (EP-007 tautological, EP-008 marker) ---
    {
        "id": "EP-007",
        "message": "EP-007 Fake Test: Tautological assertion — literal compared to itself.",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["**/*.test.tsx", "**/*.test.ts", "**/*.spec.tsx", "**/*.spec.ts"],
        "file_excludes": ["*fixtures*"],
        "patterns": [
            re.compile(r"expect\s*\(\s*(?:true|false|1|0)\s*\)\s*\.\s*toBe\s*\(\s*(?:true|false|1|0)\s*\)"),
        ],
    },
    {
        "id": "EP-008",
        "message": "EP-008 Fake Test: Bulk-generation marker detected. Zero tolerance.",
        "severity": "ERROR",
        "stage": "v1_real",
        "globs": ["**/*.test.tsx", "**/*.test.ts", "**/*.spec.tsx", "**/*.spec.ts"],
        "file_excludes": [],
        "patterns": [
            re.compile(r"quality-edge-boost|auto-generated-test|test-scaffold|bulk-test-gen"),
        ],
    },
    # --- Dev repo frontend rules (EP-010..013, 015, 017) ---
    {
        "id": "EP-010",
        "message": "EP-010 Forbidden UI Library: Direct import of banned UI library. Use @mfe/design-system.",
        "severity": "ERROR",
        "stage": "v1_real",
        "globs": ["**/*.tsx", "**/*.ts"],
        "file_excludes": ["**/web/packages/design-system/**", "**/web/packages/x-charts/**",
                          "*.test.*", "*.spec.*", "*.stories.*"],
        "patterns": [
            re.compile(r"from\s+['\"](?:antd|@ant-design/icons|@mui/material|@chakra-ui/react|recharts|victory|chart\.js)[/'\"]"),
            re.compile(r"from\s+['\"]@nivo/"),
            re.compile(r"from\s+['\"]d3[/'\"-]"),
            re.compile(r"require\s*\(\s*['\"](?:antd|@ant-design/icons|@mui/material|@chakra-ui/react|recharts|victory|chart\.js)['\"]"),
        ],
    },
    {
        "id": "EP-011",
        "message": "EP-011 Raw HTTP Client: Use @mfe/shared-http instead of raw fetch/axios.",
        "severity": "WARNING",
        "stage": "v1_advisory",
        "globs": ["web/apps/**/*.ts", "web/apps/**/*.tsx", "web/packages/**/*.ts", "web/packages/**/*.tsx"],
        "file_excludes": ["**/web/packages/shared-http/**", "*.test.*", "*.spec.*",
                          "*__mocks__*", "*__tests__*", "*.stories.*"],
        "patterns": [
            re.compile(r"(?:window\.)?fetch\s*\("),
            re.compile(r"(?:import\s+.*from\s+['\"]axios['\"]|require\s*\(['\"]axios['\"])"),
        ],
    },
    {
        "id": "EP-012",
        "message": "EP-012 Inline Auth Check: Use OpenFGA authorization layer instead of inline checks.",
        "severity": "WARNING",
        "stage": "v1_advisory",
        "globs": ["web/apps/**/*.ts", "web/apps/**/*.tsx"],
        "file_excludes": ["**/web/packages/auth/**", "*.test.*", "*.spec.*",
                          "*__tests__*", "*__mocks__*", "*.stories.*", "*.d.ts",
                          "**/types/**", "**/models/**", "**/constants/**"],
        "patterns": [
            re.compile(r"from\s+['\"].*(?:permission-check|role-guard|auth-guard|access-control|permission-util)['\"]"),
            re.compile(r"from\s+['\"].*legacy.*auth['\"]"),
            re.compile(r"role\s*===\s*['\"](?:admin|ADMIN|superadmin|SUPERADMIN|manager|MANAGER)['\"]"),
            re.compile(r"\.roles\.includes\s*\("),
        ],
    },
    {
        "id": "EP-013",
        "message": "EP-013 Direct Chart Engine: Use @mfe/x-charts wrapper instead of direct engine import.",
        "severity": "ERROR",
        "stage": "v1_real",
        "globs": ["web/apps/**/*.ts", "web/apps/**/*.tsx"],
        "file_excludes": ["**/web/packages/x-charts/**", "**/web/packages/design-system/**"],
        "patterns": [
            re.compile(r"from\s+['\"]echarts[/'\"]"),
            re.compile(r"from\s+['\"]echarts/core['\"]"),
            re.compile(r"from\s+['\"]echarts-gl['\"]"),
            re.compile(r"from\s+['\"]ag-charts-(?:community|react|enterprise)['\"]"),
            re.compile(r"require\s*\(['\"]echarts"),
        ],
    },
    {
        "id": "EP-015",
        "message": "EP-015 Webpack Pattern: Webpack API in Vite codebase. Use Vite equivalents.",
        "severity": "WARNING",
        "stage": "v1_real",
        "globs": ["**/*.ts", "**/*.tsx"],
        "file_excludes": ["*webpack.config*", "*vite.config*"],
        "patterns": [
            re.compile(r"require\.ensure\s*\("),
            re.compile(r"module\.hot\b"),
            re.compile(r"import\s*\(\s*/\*\s*webpackChunkName"),
            re.compile(r"__webpack_require__"),
        ],
    },
    {
        "id": "EP-016",
        "message": "EP-016 Legacy Auth Import Ban: Legacy authorization imports are banned. Use @mfe/auth hooks instead of useAuthorization, and OpenFGA instead of PermissionServiceClient.",
        "severity": "WARNING",
        "stage": "v1_advisory",
        "globs": ["web/apps/**/*.ts", "web/apps/**/*.tsx",
                  "web/packages/**/*.ts", "web/packages/**/*.tsx",
                  "backend/**/*.java"],
        "file_excludes": ["**/node_modules/**", "**/dist/**", "**/target/**",
                          "**/__tests__/**", "*.test.*", "**/compat.ts"],
        "patterns": [
            re.compile(r"from\s+['\"].*compat['\"]"),
            re.compile(r"useAuthorization\s*\("),
            re.compile(r"import.*PermissionServiceClient"),
            re.compile(r"new\s+PermissionServiceClient"),
        ],
    },
    {
        "id": "EP-017",
        "message": "EP-017 Deep Import Ban: Use public API exports, not internal package paths.",
        "severity": "WARNING",
        "stage": "v1_advisory",
        "globs": ["web/apps/**/*.ts", "web/apps/**/*.tsx"],
        "file_excludes": ["**/web/packages/design-system/**", "**/web/packages/shared-http/**",
                          "**/web/packages/x-charts/**", "*.test.*", "*.spec.*", "*.stories.*"],
        "patterns": [
            re.compile(r"from\s+['\"]@mfe/(?:design-system|shared-http|x-charts)/(?:src|lib|internal|dist(?:/esm|/cjs)?)/"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def _should_exclude_file(filepath: Path, file_excludes: list[str]) -> bool:
    """Check if a file should be excluded based on exclude patterns."""
    path_str = str(filepath)
    name = filepath.name
    for ex in file_excludes:
        if ex.startswith("**"):
            if ex.lstrip("**/") in path_str:
                return True
        elif "*" in ex:
            # Simple wildcard matching
            pattern = ex.replace("*", "")
            if pattern in path_str or pattern in name:
                return True
        elif ex in path_str:
            return True
    return False


def _find_files(root: Path, globs: list[str]) -> list[Path]:
    """Find files matching glob patterns, excluding global excludes."""
    files: set[Path] = set()
    for pattern in globs:
        clean = pattern.removeprefix("**/")
        for f in root.rglob(clean):
            if f.is_file() and not any(ex in f.parts for ex in GLOBAL_EXCLUDES):
                files.add(f)
    return sorted(files)


def _scan_rule(root: Path, rule: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan files for a single rule. Returns list of violations."""
    violations: list[dict[str, Any]] = []
    files = _find_files(root, rule["globs"])

    for filepath in files:
        if _should_exclude_file(filepath, rule.get("file_excludes", [])):
            continue
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for pattern in rule["patterns"]:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                violations.append({
                    "rule_id": rule["id"],
                    "file": str(filepath.relative_to(root)),
                    "line": line_no,
                    "message": rule["message"],
                    "severity": rule["severity"],
                    "stage": rule["stage"],
                    "match": match.group()[:80],
                })
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enforcement rules gate (script-based)")
    p.add_argument("--repo-root", required=True)
    p.add_argument("--scan-path", default=None, help="Override scan path")
    p.add_argument("--out", default=None, help="Output JSON report path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rules", default=None, help="Comma-separated EP IDs to run (default: all)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root).resolve()
    scan_root = Path(args.scan_path).resolve() if args.scan_path else root

    # Filter rules if specific ones requested
    rules_to_run = RULES
    if args.rules:
        selected = {r.strip() for r in args.rules.split(",")}
        rules_to_run = [r for r in RULES if r["id"] in selected]

    # Scan
    all_violations: list[dict[str, Any]] = []
    rule_counts: dict[str, int] = {}
    for rule in rules_to_run:
        violations = _scan_rule(scan_root, rule)
        rule_counts[rule["id"]] = len(violations)
        all_violations.extend(violations)

    # Classify
    error_count = sum(1 for v in all_violations if v["severity"] == "ERROR")
    warning_count = sum(1 for v in all_violations if v["severity"] == "WARNING")

    status = "FAIL" if error_count > 0 else ("WARN" if warning_count > 0 else "PASS")
    if args.dry_run:
        status = f"DRY_RUN_{status}"

    report = {
        "version": "v1",
        "generated_at": now_iso8601(),
        "status": status,
        "scan_root": str(scan_root),
        "rules_count": len(rules_to_run),
        "rules_checked": [r["id"] for r in rules_to_run],
        "findings_count": len(all_violations),
        "error_count": error_count,
        "warning_count": warning_count,
        "by_rule": rule_counts,
        "violations": all_violations[:100],
        "notes": [
            "Script-based enforcement. AST rules (EP-006, EP-009, EP-014) require semgrep separately.",
        ],
    }

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0 if "PASS" in status else 1


if __name__ == "__main__":
    sys.exit(main())
