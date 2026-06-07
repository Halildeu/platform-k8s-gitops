#!/usr/bin/env python3
"""Verify #1044 A1 pilot-wide rollup acceptance from a Markdown evidence doc.

This verifier is intentionally strict. It turns RB-faz22-non-domain-windows-
pilot.md §14.4/§14.5 into a machine-checkable gate for the final #1044 rollup:

* tracked issue, tier, status, and soak window must be explicit;
* at least three A1 devices must be present;
* every per-device status must be PASS;
* aggregate heartbeat, terminal/accounted, command-success, gap, and
  repeatability checks must satisfy the thresholds;
* no unresolved PENDING/REVIEW/PARTIAL/FAIL marker may remain in the final doc;
* referenced per-device evidence docs must exist unless explicitly skipped.

It does not query the backend, dispatch commands, mutate state, or infer
acceptance from missing evidence. Current partial evidence is expected to fail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path


UNRESOLVED_TOKEN_RE = re.compile(
    r"\b(PENDING|REVIEW|COMMAND_REVIEW|GAP_REVIEW|LOW_HEARTBEAT_RATIO|NO_HEARTBEAT_DATA|NO_DEVICE_SCOPE|PARTIAL|FAIL)\b"
)


@dataclass
class Check:
    name: str
    passed: bool
    message: str


def die(message: str) -> None:
    print(f"[faz22-a1-acceptance] ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def clean_cell(value: str) -> str:
    return value.strip().strip("`").strip()


def split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [clean_cell(part) for part in stripped.split("|")]


def is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line))


def parse_tables(text: str) -> list[list[dict[str, str]]]:
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines) - 1:
        if "|" not in lines[i] or not is_separator(lines[i + 1]):
            i += 1
            continue
        headers = split_row(lines[i])
        rows: list[dict[str, str]] = []
        i += 2
        while i < len(lines):
            line = lines[i]
            if "|" not in line or not line.strip().startswith("|"):
                break
            cells = split_row(line)
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            i += 1
        if rows:
            tables.append(rows)
        else:
            i += 1
    return tables


def parse_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^>\s*\*\*(.+?)\*\*:\s*(.+?)\s*$", line)
        if not match:
            continue
        key = re.sub(r"\s+", " ", match.group(1).strip().lower())
        metadata[key] = match.group(2).strip()
    return metadata


def parse_acceptance_verdict(text: str) -> str:
    match = re.search(r"(?im)^\*\*Verdict\*\*:\s*([A-Z]+)\s*$", text)
    return match.group(1).upper() if match else "MISSING"


def parse_percent(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", value)
    return float(match.group(1)) if match else None


def parse_leading_int(value: str) -> int | None:
    match = re.search(r"^\s*([0-9]+)\b", value)
    return int(match.group(1)) if match else None


def parse_soak_hours(value: str) -> float | None:
    if not value or value.upper() == "PENDING":
        return None
    parts = re.split(r"\s*(?:->|→)\s*", value)
    if len(parts) != 2:
        return None

    def parse_one(raw: str) -> dt.datetime:
        text = raw.strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)

    try:
        start = parse_one(parts[0])
        end = parse_one(parts[1])
    except ValueError:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return seconds / 3600.0


def find_device_table(tables: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    for table in tables:
        headers = set(table[0].keys())
        lowered = {h.lower() for h in headers}
        if "status" in lowered and any("hostname" in h for h in lowered) and (
            "per-device evidence doc" in lowered or "device id" in lowered or "tier" in lowered
        ):
            return table
    return []


def find_aggregate_table(tables: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    for table in tables:
        lowered = {h.lower() for h in table[0].keys()}
        if "metric" in lowered and "value" in lowered and "verdict" in lowered:
            return table
    return []


def get_cell(row: dict[str, str], wanted: str) -> str:
    for key, value in row.items():
        if key.lower() == wanted.lower():
            return value
    return ""


def row_by_metric(rows: list[dict[str, str]], needle: str) -> dict[str, str] | None:
    for row in rows:
        if needle.lower() in get_cell(row, "Metric").lower():
            return row
    return None


def linked_doc_paths(device_rows: list[dict[str, str]], evidence_root: Path) -> list[Path]:
    paths: list[Path] = []
    for row in device_rows:
        raw = get_cell(row, "Per-device evidence doc")
        if not raw:
            continue
        match = re.search(r"\(([^)]+)\)", raw)
        target = match.group(1) if match else raw
        if target.upper() in {"PENDING", "N/A"}:
            continue
        path = Path(target)
        if not path.is_absolute():
            path = evidence_root / path
        paths.append(path)
    return paths


def accepted_helper_verdict(value: str) -> bool:
    normalized = value.strip().upper()
    return normalized in {"", "PASS", "ROLLUP_FACTS_OK"}


def verify(args: argparse.Namespace, text: str) -> list[Check]:
    metadata = parse_metadata(text)
    tables = parse_tables(text)
    device_rows = find_device_table(tables)
    aggregate_rows = find_aggregate_table(tables)
    checks: list[Check] = []

    status = metadata.get("status", "").upper()
    checks.append(Check("metadata_status_pass", status == "PASS", f"status={status or 'MISSING'}"))

    tracked_by = metadata.get("tracked by", "").lstrip("#")
    checks.append(Check("tracked_by", tracked_by == str(args.tracked_by), f"tracked_by={tracked_by or 'MISSING'}"))

    tier = metadata.get("tier", "").upper()
    checks.append(Check("tier", tier == args.tier, f"tier={tier or 'MISSING'}"))

    scope_text = metadata.get("scope", "")
    scope_match = re.search(r"([0-9]+)", scope_text)
    scope_count = int(scope_match.group(1)) if scope_match else 0
    checks.append(Check("scope_min_devices", scope_count >= args.min_devices, f"scope={scope_count}, required>={args.min_devices}"))

    soak_hours = parse_soak_hours(metadata.get("soak window", ""))
    checks.append(
        Check(
            "soak_window_min_hours",
            soak_hours is not None and soak_hours >= args.min_soak_hours,
            f"soak_hours={soak_hours if soak_hours is not None else 'MISSING'}, required>={args.min_soak_hours}",
        )
    )

    acceptance_verdict = parse_acceptance_verdict(text)
    checks.append(Check("acceptance_verdict_pass", acceptance_verdict == "PASS", f"verdict={acceptance_verdict}"))

    checks.append(Check("device_table_present", bool(device_rows), f"rows={len(device_rows)}"))
    checks.append(Check("device_count_min", len(device_rows) >= args.min_devices, f"rows={len(device_rows)}, required>={args.min_devices}"))
    if device_rows:
        statuses = [get_cell(row, "Status").upper() for row in device_rows]
        checks.append(Check("all_devices_pass", all(status == "PASS" for status in statuses), f"statuses={statuses}"))
        helper_values = [get_cell(row, "Helper verdict") for row in device_rows if "Helper verdict" in row]
        if helper_values:
            checks.append(
                Check(
                    "helper_verdicts_clean",
                    all(accepted_helper_verdict(value) for value in helper_values),
                    f"helper_verdicts={helper_values}",
                )
            )

    checks.append(Check("aggregate_table_present", bool(aggregate_rows), f"rows={len(aggregate_rows)}"))
    if aggregate_rows:
        heartbeat = row_by_metric(aggregate_rows, "Heartbeat success rate")
        terminal = row_by_metric(aggregate_rows, "Command terminal")
        success = row_by_metric(aggregate_rows, "Command success rate")
        gaps = row_by_metric(aggregate_rows, "Soak gap incidents")
        repeatability = row_by_metric(aggregate_rows, "Repeatability gate")

        heartbeat_pct = parse_percent(get_cell(heartbeat or {}, "Value"))
        heartbeat_verdict = get_cell(heartbeat or {}, "Verdict").upper()
        checks.append(
            Check(
                "heartbeat_threshold",
                heartbeat_pct is not None and heartbeat_pct >= 99.0 and heartbeat_verdict == "PASS",
                f"value={heartbeat_pct}, verdict={heartbeat_verdict or 'MISSING'}",
            )
        )

        terminal_pct = parse_percent(get_cell(terminal or {}, "Value"))
        terminal_verdict = get_cell(terminal or {}, "Verdict").upper()
        checks.append(
            Check(
                "terminal_accounted_threshold",
                terminal_pct is not None and terminal_pct >= 100.0 and terminal_verdict == "PASS",
                f"value={terminal_pct}, verdict={terminal_verdict or 'MISSING'}",
            )
        )

        success_pct = parse_percent(get_cell(success or {}, "Value"))
        success_verdict = get_cell(success or {}, "Verdict").upper()
        checks.append(
            Check(
                "command_success_threshold",
                success_pct is not None and success_pct >= 95.0 and success_verdict == "PASS",
                f"value={success_pct}, verdict={success_verdict or 'MISSING'}",
            )
        )

        gap_count = parse_leading_int(get_cell(gaps or {}, "Value"))
        gap_verdict = get_cell(gaps or {}, "Verdict").upper()
        checks.append(
            Check(
                "gap_incidents_zero",
                gap_count == 0 and gap_verdict == "PASS",
                f"value={gap_count}, verdict={gap_verdict or 'MISSING'}",
            )
        )

        repeatability_value = get_cell(repeatability or {}, "Value").upper()
        repeatability_verdict = get_cell(repeatability or {}, "Verdict").upper()
        checks.append(
            Check(
                "repeatability_gate_pass",
                repeatability_value.startswith("PASS") or repeatability_verdict == "PASS",
                f"value={repeatability_value or 'MISSING'}, verdict={repeatability_verdict or 'MISSING'}",
            )
        )

    if not args.skip_doc_existence and device_rows:
        paths = linked_doc_paths(device_rows, args.evidence_root)
        missing = [str(path) for path in paths if not path.exists()]
        checks.append(Check("per_device_docs_exist", not missing and len(paths) >= args.min_devices, f"checked={len(paths)}, missing={missing}"))

    unresolved = sorted(set(UNRESOLVED_TOKEN_RE.findall(text)))
    checks.append(Check("no_unresolved_tokens", not unresolved, f"tokens={unresolved}"))

    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for check in checks:
        symbol = "PASS" if check.passed else "FAIL"
        lines.append(f"{symbol} {check.name}: {check.message}")
    passed = sum(1 for check in checks if check.passed)
    overall = "PASS" if passed == len(checks) else "FAIL"
    lines.append(f"OVERALL {overall} ({passed}/{len(checks)})")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify #1044 A1 rollup acceptance from markdown.")
    parser.add_argument("--rollup-doc", required=True)
    parser.add_argument("--tracked-by", default="1044")
    parser.add_argument("--tier", default="A1")
    parser.add_argument("--min-devices", type=int, default=3)
    parser.add_argument("--min-soak-hours", type=float, default=24.0)
    parser.add_argument("--evidence-root", default="")
    parser.add_argument("--skip-doc-existence", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_devices <= 0:
        die("--min-devices must be > 0")
    if args.min_soak_hours <= 0:
        die("--min-soak-hours must be > 0")
    path = Path(args.rollup_doc)
    if not path.exists():
        die(f"--rollup-doc not found: {path}")
    if not path.is_file():
        die(f"--rollup-doc is not a file: {path}")
    args.evidence_root = Path(args.evidence_root) if args.evidence_root else path.parent
    text = path.read_text(encoding="utf-8")
    checks = verify(args, text)
    print(format_checks(checks))
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
