#!/usr/bin/env python3
"""Build a sanitized #1044 pilot-wide rollup draft from soak helper output.

Input is the text output from `a1-soak-rollup.sh --execute ...`. This script is
local and read-only: it parses psql pipe-table output and emits the §14.3/§14.4
rollup Markdown draft. It does not connect to the backend, rerun SQL, dispatch
commands, mutate devices, or claim #1044 completion by itself.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
import sys
from pathlib import Path
from typing import Any


SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+(?!<redacted>)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"Authorization:\s*(?!<redacted>)[^\s]+", re.IGNORECASE),
    re.compile(r"credential=(?!<redacted>)[^,;\s]+", re.IGNORECASE),
    re.compile(r"(token|secret|password)\s*[:=]\s*(?!<redacted>)[^,}\r\n]+", re.IGNORECASE),
]


def die(message: str) -> None:
    print(f"[faz22-a1-rollup-doc] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def scan_for_secrets(text: str, source: str) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            die(f"potential secret-like output in {source}: {match.group(0)[:80]!r}")


def is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*-+(\+-+)+\s*$", line))


def parse_psql_tables(text: str) -> list[list[dict[str, str]]]:
    """Parse simple psql aligned pipe tables.

    This intentionally ignores SQL and log lines. It only captures tables with a
    pipe-delimited header followed by a psql dashed separator.
    """
    lines = text.splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    while i < len(lines) - 1:
        header_line = lines[i]
        separator_line = lines[i + 1]
        if "|" not in header_line or not is_separator(separator_line):
            i += 1
            continue

        headers = [cell.strip() for cell in header_line.split("|")]
        rows: list[dict[str, str]] = []
        i += 2
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                break
            if re.match(r"^\(\d+ rows?\)$", line.strip()):
                i += 1
                break
            if "|" not in line:
                i += 1
                break
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            i += 1
        if rows:
            tables.append(rows)
    return tables


def rows_by_section(tables: list[list[dict[str, str]]], section: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table in tables:
        for row in table:
            if row.get("section") == section:
                rows.append(row)
    return rows


def decimal(value: str) -> float:
    if value in {"", "(null)", "PENDING"}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def integer(value: str) -> int:
    if value in {"", "(null)", "PENDING"}:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "PENDING"
    return f"{(numerator / denominator) * 100:.2f}%"


def metric_verdict(ok: bool, value: str = "") -> str:
    return "PASS" if ok else f"REVIEW{f' ({value})' if value else ''}"


def parse_device_arg(raw: str) -> dict[str, str]:
    # Format: DEVICE_ID=hostname,tier,doc,status
    if "=" not in raw:
        die("--device expects DEVICE_ID=hostname,tier,doc,status")
    device_id, rest = raw.split("=", 1)
    parts = [part.strip() for part in rest.split(",", 3)]
    if len(parts) != 4:
        die("--device expects DEVICE_ID=hostname,tier,doc,status")
    hostname, tier, doc, status = parts
    if not re.match(r"^[0-9A-Fa-f-]{36}$", device_id):
        die(f"--device id does not look like a UUID: {device_id}")
    if status not in {"PASS", "PARTIAL", "FAIL", "PENDING"}:
        die(f"--device status must be PASS/PARTIAL/FAIL/PENDING: {status}")
    return {
        "device_id": device_id,
        "hostname": hostname or device_id,
        "tier": tier or "A1",
        "doc": doc or "PENDING",
        "status": status,
    }


def lookup_device(devices: dict[str, dict[str, str]], device_id: str) -> dict[str, str]:
    return devices.get(
        device_id,
        {
            "device_id": device_id,
            "hostname": device_id,
            "tier": "A1",
            "doc": "PENDING",
            "status": "PENDING",
        },
    )


def build_markdown(args: argparse.Namespace, soak_text: str) -> str:
    tables = parse_psql_tables(soak_text)
    device_rows = rows_by_section(tables, "SOAK_DEVICE_ROLLUP")
    status_rows = rows_by_section(tables, "COMMAND_STATUS_ROLLUP")
    recent_rows = rows_by_section(tables, "COMMAND_RECENT_DETAIL")
    if not device_rows:
        die("soak output does not contain SOAK_DEVICE_ROLLUP rows")

    devices = {item["device_id"]: item for item in (parse_device_arg(raw) for raw in args.device)}

    expected_total = sum(integer(row.get("expected_heartbeat_count", "0")) for row in device_rows)
    heartbeat_total = sum(integer(row.get("heartbeat_count", "0")) for row in device_rows)
    gap_total = sum(integer(row.get("gap_count_over_threshold", "0")) for row in device_rows)
    command_total = sum(integer(row.get("command_count", "0")) for row in device_rows)
    terminal_total = sum(integer(row.get("terminal_count", "0")) for row in device_rows)
    succeeded_total = sum(integer(row.get("succeeded_count", "0")) for row in device_rows)
    nonterminal_total = sum(integer(row.get("nonterminal_count", "0")) for row in device_rows)

    heartbeat_rate = pct(heartbeat_total, expected_total)
    terminal_rate = pct(terminal_total, command_total)
    success_rate = pct(succeeded_total, command_total)

    heartbeat_ok = expected_total > 0 and (heartbeat_total / expected_total) >= 0.99
    terminal_ok = command_total > 0 and nonterminal_total == 0
    success_ok = command_total > 0 and (succeeded_total / command_total) >= 0.95
    gap_ok = gap_total == 0

    statuses = [lookup_device(devices, row["device_id"])["status"] for row in device_rows]
    pass_devices = statuses.count("PASS")
    required_pass_devices = math.ceil((2 * len(device_rows)) / 3)
    repeatability_note = (
        "PASS-candidate only if every per-device evidence doc is PASS and all aggregate metrics are PASS"
        if pass_devices == len(device_rows) and heartbeat_ok and terminal_ok and success_ok and gap_ok
        else f"REVIEW: pass_devices={pass_devices}/{len(device_rows)}, required_for_partial={required_pass_devices}"
    )

    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines: list[str] = [
        f"# Faz 22.2.A non-domain pilot rollup — Tier {args.tier} multi-device",
        "",
        f"> **Status**: {args.status}",
        f"> **Tracked by**: #{args.tracked_by}",
        f"> **Tier**: {args.tier}",
        f"> **Scope**: {len(device_rows)} device(s)",
        f"> **Soak window**: {args.soak_window}",
        f"> **Codex thread**: {args.codex_thread}",
        f"> **Generated at**: {generated_at}",
        f"> **Source soak output**: `{Path(args.soak_output)}`",
        "",
        "## 1. Device summary table",
        "",
        "| # | Hostname (or pseudonym) | Device ID | Tier | Per-device evidence doc | Status | Helper verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    for index, row in enumerate(device_rows, start=1):
        meta = lookup_device(devices, row["device_id"])
        doc = meta["doc"]
        doc_cell = f"[link]({doc})" if doc not in {"", "PENDING"} else "PENDING"
        lines.append(
            "| {index} | {hostname} | `{device_id}` | {tier} | {doc} | {status} | {helper_verdict} |".format(
                index=index,
                hostname=meta["hostname"],
                device_id=row["device_id"],
                tier=meta["tier"],
                doc=doc_cell,
                status=meta["status"],
                helper_verdict=row.get("helper_verdict", "PENDING"),
            )
        )

    lines += [
        "",
        "## 2. Aggregate metrics (per §14.5 formula)",
        "",
        "| Metric | Value | Acceptance threshold | Verdict |",
        "|---|---|---|---|",
        f"| Heartbeat success rate (pilot-wide) | {heartbeat_rate} ({heartbeat_total}/{expected_total}) | ≥99% | {metric_verdict(heartbeat_ok)} |",
        f"| Command terminal/accounted rate (pilot-wide) | {terminal_rate} ({terminal_total}/{command_total}) | 100% | {metric_verdict(terminal_ok, f'nonterminal={nonterminal_total}')} |",
        f"| Command success rate (pilot-wide) | {success_rate} ({succeeded_total}/{command_total}) | ≥95% | {metric_verdict(success_ok)} |",
        f"| Soak gap incidents (unexplained > 30m) | {gap_total} | 0 required | {metric_verdict(gap_ok)} |",
        f"| Repeatability gate | {repeatability_note} | per §14.5 rule | REVIEW |",
        "",
        "## 3. Acceptance verdict",
        "",
        f"**Verdict**: {args.status}",
        "",
        "**Rationale**:",
        "- This generator summarizes helper facts; it does not decide final #1044 acceptance by itself.",
        "- Set final PASS/PARTIAL/FAIL only after per-device evidence docs, planned command facts, and operator-reviewed soak notes are complete.",
        "",
        "## 4. Command status rollup",
        "",
        "| Device ID | Command type | Status | Count | First issued | Last issued | Max duration |",
        "|---|---|---|---:|---|---|---|",
    ]

    if status_rows:
        for row in status_rows:
            lines.append(
                f"| `{row.get('device_id', 'PENDING')}` | {row.get('command_type', 'PENDING')} | {row.get('status', 'PENDING')} | {row.get('count', '0')} | {row.get('first_issued_at', 'PENDING')} | {row.get('last_issued_at', 'PENDING')} | {row.get('max_duration', 'PENDING')} |"
            )
    else:
        lines.append("| PENDING | PENDING | PENDING | 0 | PENDING | PENDING | PENDING |")

    lines += [
        "",
        "## 5. Recent command detail",
        "",
        "| Device ID | Command type | Status | Issued | Delivered | Started | Completed | Duration |",
        "|---|---|---|---|---|---|---|---|",
    ]

    if recent_rows:
        for row in recent_rows[:50]:
            lines.append(
                f"| `{row.get('device_id', 'PENDING')}` | {row.get('command_type', 'PENDING')} | {row.get('status', 'PENDING')} | {row.get('issued_at', 'PENDING')} | {row.get('delivered_at', 'PENDING')} | {row.get('started_at', 'PENDING')} | {row.get('completed_at', 'PENDING')} | {row.get('duration', 'PENDING')} |"
            )
    else:
        lines.append("| PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |")

    lines += [
        "",
        "## 6. Cross-device anomaly notes",
        "",
        "| Device | Anomaly | Root cause (if known) | Action |",
        "|---|---|---|---|",
        "| PENDING | PENDING | PENDING | PENDING |",
        "",
        "## 7. Cross-AI peer review",
        "",
        "Implementer AI: Codex",
        "Reviewer AI: PENDING",
        f"Codex thread: {args.codex_thread}",
        "Verdict: PENDING",
        "",
        "## 8. Boundary",
        "",
        f"- Tier {args.tier} scope only; other tier rollup ayrı doc.",
        "- This rollup draft is not prod-ready, password-reset-ready, or domain-wide rollout-ready evidence.",
        "- This script does not run SQL, dispatch commands, mutate devices, or perform runtime actions.",
        "- 24h soak facts must be operator-reviewed before #1044 moves out of Needs Verify.",
        "",
    ]

    rendered = "\n".join(lines)
    scan_for_secrets(rendered, "generated rollup markdown")
    return rendered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a #1044 pilot-wide rollup markdown draft from a1-soak-rollup.sh output.",
    )
    parser.add_argument("--soak-output", required=True, help="Text output captured from a1-soak-rollup.sh --execute")
    parser.add_argument("--output", help="Write markdown to this path. Defaults to stdout unless --output-dir is set.")
    parser.add_argument("--output-dir", help="Write markdown under this directory using date/tier rollup naming.")
    parser.add_argument("--tracked-by", default="1044")
    parser.add_argument("--tier", default="A1", choices=["A1", "A2", "A3", "A4"])
    parser.add_argument("--status", default="PARTIAL", choices=["PARTIAL", "FAIL"])
    parser.add_argument("--soak-window", default="PENDING")
    parser.add_argument("--codex-thread", default="PENDING")
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        help="Device metadata: DEVICE_ID=hostname,tier,relative-doc-path,status",
    )
    return parser.parse_args()


def output_path(args: argparse.Namespace) -> Path | None:
    if args.output:
        return Path(args.output)
    if args.output_dir:
        date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        return Path(args.output_dir) / f"{date}-non-domain-pilot-tier{args.tier}-rollup.md"
    return None


def main() -> int:
    args = parse_args()
    soak_path = Path(args.soak_output)
    if not soak_path.exists():
        die(f"--soak-output not found: {soak_path}")
    if not soak_path.is_file():
        die(f"--soak-output is not a file: {soak_path}")
    text = soak_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        die("--soak-output is empty")
    scan_for_secrets(text, str(soak_path))

    rendered = build_markdown(args, text)
    destination = output_path(args)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(f"[faz22-a1-rollup-doc] wrote {destination}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
