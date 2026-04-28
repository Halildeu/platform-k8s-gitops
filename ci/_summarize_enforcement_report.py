#!/usr/bin/env python3
"""Summarize the JSON output of `check_enforcement_rules.py` for CI logs.

Used by `.github/workflows/gate-enforcement-check.yml` step "Show report
summary". Avoids embedding Python in YAML/bash where indentation +
shell quoting collide.

Reads a single positional arg: path to the report JSON file. Prints a
human-readable summary to stdout. Exit 0 on success.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write(f"usage: {sys.argv[0]} <report.json>\n")
        sys.exit(2)

    path = sys.argv[1]
    with open(path) as f:
        d = json.load(f)

    print("=== Enforcement Rules Summary ===")
    print(f"  Status: {d.get('status', '?')}")
    print(f"  Generated at: {d.get('generated_at', '?')}")
    print(f"  Rules checked: {d.get('rules_count', '?')}")
    print(f"  Findings: {d.get('findings_count', '?')}")
    print(f"  Errors: {d.get('error_count', '?')}")
    print(f"  Warnings: {d.get('warning_count', '?')}")

    by_rule = d.get("by_rule", {})
    non_zero = {k: v for k, v in by_rule.items() if v > 0}
    print(f"  Rules with hits: {len(non_zero)} of {len(by_rule)}")
    for rule, n in non_zero.items():
        print(f"    {rule}: {n} hits")

    violations = d.get("violations", [])
    for v in violations[:5]:
        print(f"    - {v.get('rule', '?')}: {v.get('file', '?')}:{v.get('line', '?')}")
    if len(violations) > 5:
        print(f"    ... and {len(violations) - 5} more (see artifact)")


if __name__ == "__main__":
    main()
