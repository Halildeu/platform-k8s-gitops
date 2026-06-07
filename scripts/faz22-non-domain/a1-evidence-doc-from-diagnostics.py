#!/usr/bin/env python3
"""Build a sanitized #1044 per-device evidence draft from local VM diagnostics.

The input is produced by `a1-local-vm-diagnostics.sh`. This script is local and
read-only: it parses a sanitized diagnostics file and emits a Markdown evidence
draft matching RB-faz22-non-domain-windows-pilot.md §14.1/§14.2. It does not
connect to the backend, dispatch commands, mutate devices, or claim #1044
acceptance completion.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
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
    re.compile(r"S-1-5-21-[0-9-]+"),
]


def die(message: str) -> None:
    print(f"[faz22-a1-evidence-doc] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def scan_for_secrets(text: str, source: str) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            snippet = match.group(0)[:80]
            die(f"potential secret-like output in {source}: {snippet!r}")


def sections(text: str) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = re.match(r"^===\s+(.+?)\s+===$", line)
        if match:
            current = match.group(1).strip()
            found[current] = []
            continue
        if current:
            found[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


def first_json(section_text: str) -> Any:
    for raw in section_text.splitlines():
        line = raw.strip()
        if not line or not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def value_from_format_list(section_text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", section_text)
    return match.group(1).strip() if match else "PENDING"


def scalar(value: Any, default: str = "PENDING") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    return text if text else default


def yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return scalar(value)


def markdown_escape(value: Any) -> str:
    text = scalar(value)
    return text.replace("|", "\\|").replace("\n", " ")


def agent_version(service_section: str) -> str:
    match = re.search(r"(?im)^endpoint-agent\s+(.+?)\s*$", service_section)
    if match:
        return f"endpoint-agent {match.group(1).strip()}"
    return "PENDING"


def service_status(service_section: str) -> str:
    status = value_from_format_list(service_section, "Status")
    start_type = value_from_format_list(service_section, "StartType")
    if status == "PENDING" and start_type == "PENDING":
        return "PENDING"
    return f"{status} / {start_type}"


def reachability(section_text: str) -> str:
    match = re.search(r"testai\.acik\.com:443 reachable=(True|False)", section_text, re.IGNORECASE)
    return match.group(1).lower() if match else "PENDING"


def output_path(args: argparse.Namespace, hostname: str) -> Path | None:
    if args.output:
        return Path(args.output)
    if args.output_dir:
        safe_host = re.sub(r"[^A-Za-z0-9_.-]+", "-", hostname).strip("-") or "unknown-device"
        date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        return Path(args.output_dir) / f"{date}-non-domain-pilot-tier{args.tier}-{safe_host}.md"
    return None


def build_markdown(args: argparse.Namespace, text: str, parsed_sections: dict[str, str]) -> str:
    identity = first_json(parsed_sections.get("diagnose-identity", "")) or {}
    winget = first_json(parsed_sections.get("diagnose-winget", "")) or {}
    software = first_json(parsed_sections.get("diagnose-software", "")) or {}
    hardware = first_json(parsed_sections.get("diagnose-hardware", "")) or {}
    services = first_json(parsed_sections.get("diagnose-services", "")) or {}
    local_users = first_json(parsed_sections.get("diagnose-local-users", "")) or []
    winget_egress = first_json(parsed_sections.get("diagnose-winget-egress", "")) or {}

    host_section = parsed_sections.get("timestamp-host-computer", "")
    service_section = parsed_sections.get("service-process-version", "")
    backend_section = parsed_sections.get("backend-reachability", "")
    dsreg_section = parsed_sections.get("dsregcmd", "")

    hostname = scalar(identity.get("hostname"), value_from_format_list(host_section, "Name"))
    part_of_domain = scalar(identity.get("partOfDomain"), value_from_format_list(host_section, "PartOfDomain"))
    domain = scalar(identity.get("domain"), value_from_format_list(host_section, "Domain"))
    workgroup = scalar(identity.get("workgroup"), value_from_format_list(host_section, "Workgroup"))
    identity_class = scalar(identity.get("classification"), "PENDING")

    azure_joined = scalar(identity.get("azureAdJoined"), "PENDING")
    workplace_joined = scalar(identity.get("workplaceJoined"), "PENDING")
    if azure_joined == "PENDING":
        match = re.search(r"AzureAdJoined\s*:\s*(YES|NO)", dsreg_section, re.IGNORECASE)
        if match:
            azure_joined = match.group(1).upper()
    if workplace_joined == "PENDING":
        match = re.search(r"WorkplaceJoined\s*:\s*(YES|NO)", dsreg_section, re.IGNORECASE)
        if match:
            workplace_joined = match.group(1).upper()

    apps = software.get("apps") if isinstance(software, dict) else []
    if not isinstance(apps, list):
        apps = []
    app_count = software.get("appCount") if isinstance(software, dict) else None

    service_rows = services.get("services") if isinstance(services, dict) else []
    if not isinstance(service_rows, list):
        service_rows = []
    endpoint_service = next((s for s in service_rows if s.get("name") == "EndpointAgent"), {})

    egress_package = winget_egress.get("packageQuery") if isinstance(winget_egress, dict) else {}
    if not isinstance(egress_package, dict):
        egress_package = {}

    source_path = Path(args.diagnostics_file)
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    lines: list[str] = [
        f"# Faz 22.2.A non-domain pilot — Tier {args.tier}, Device {hostname}",
        "",
        f"> **Status**: {args.status}",
        f"> **Tracked by**: #{args.tracked_by}",
        f"> **Tier**: {args.tier}",
        f"> **Operator**: {args.operator}",
        "> **DPO sign-off** (A2 only): N/A for A1",
        f"> **Codex thread**: {args.codex_thread}",
        f"> **Generated at**: {generated_at}",
        f"> **Source diagnostics**: `{source_path}`",
        "",
        "## 1. Identity classification",
        "",
        "| Field | Value | Source | Redaction |",
        "|---|---|---|---|",
        f"| Hostname | {markdown_escape(hostname)} | `diagnose identity` / Win32_ComputerSystem | none |",
        f"| PartOfDomain | {markdown_escape(part_of_domain)} | `diagnose identity` / Win32_ComputerSystem | none |",
        f"| Domain/Workgroup | {markdown_escape(domain)} / {markdown_escape(workgroup)} | `diagnose identity` | none |",
        f"| AzureAdJoined | {markdown_escape(azure_joined)} | `diagnose identity` / dsregcmd | none |",
        f"| WorkplaceJoined | {markdown_escape(workplace_joined)} | `diagnose identity` / dsregcmd | none |",
        "| Tenant ID | N/A | A1 local/workgroup device | not captured |",
        "| Logged-in identity | hash/mask only | `diagnose identity` | UPN/full SID not captured |",
        f"| Agent identity class | {markdown_escape(identity_class)} | agent identity classifier | none |",
        f"| Detected tier | {args.tier} | runbook taxonomy mapping | none |",
        "",
        "## 2. Build provenance",
        "",
        f"- platform-agent commit: {args.platform_agent_commit}",
        f"- endpoint-agent.exe SHA256: {args.agent_sha256}",
        f"- Agent version: {agent_version(service_section)}",
        f"- EndpointAgent service: {service_status(service_section)}",
        f"- Authenticode signed?: {args.authenticode_signed}",
        f"- install method: {args.install_method}",
        "",
        "## 3. Install / Enroll / Heartbeat",
        "",
        f"- install timestamp: {args.install_timestamp}",
        f"- enrollment token mint timestamp: {args.enrollment_token_mint_timestamp}",
        f"- device ID (backend): {args.device_id}",
        f"- enroll timestamp: {args.enroll_timestamp}",
        "- heartbeat interval (configured): 30s unless device config evidence says otherwise",
        "- heartbeat 24h count: PENDING — fill from `a1-soak-rollup.sh` after the soak window",
        "- heartbeat 24h max gap: PENDING — fill from `a1-soak-rollup.sh` after the soak window",
        "",
        "## 4. Read-only local diagnostics",
        "",
        "| Check | Value | Evidence |",
        "|---|---|---|",
        f"| Backend reachability | {reachability(backend_section)} | `testai.acik.com:443` |",
        f"| WinGet ready | {yes_no(winget.get('systemContextReady'))} | version `{markdown_escape(winget.get('version'))}` |",
        f"| WinGet egress package | {yes_no(egress_package.get('found'))} | package `7zip.7zip`; `PENDING` means probe skipped |",
        f"| Software inventory app count | {markdown_escape(app_count)} | `diagnose software` |",
        f"| Hardware OS | {markdown_escape(hardware.get('osName'))} / {markdown_escape(hardware.get('osArch'))} | `diagnose hardware` |",
        f"| EndpointAgent service probe | {markdown_escape(endpoint_service.get('state'))} / {markdown_escape(endpoint_service.get('startupMode'))} | `diagnose services` |",
        f"| Local users observed | {len(local_users) if isinstance(local_users, list) else 'PENDING'} | usernames redacted/hash-only evidence |",
        "",
        "## 5. Smoke (non-destructive)",
        "",
        "| Command | ID | Status | Duration | Audit row |",
        "|---|---|---|---|---|",
        "| COLLECT_INVENTORY | PENDING | PENDING | PENDING | PENDING |",
        "| inventory_refresh (optional) | N/A | N/A | N/A | N/A |",
        "",
        "This generator does not dispatch commands. Fill this section from the planned non-destructive backend command smoke.",
        "",
        "## 6. Soak observation (24-72h)",
        "",
        "| Metric | Value | Acceptance |",
        "|---|---|---|",
        "| Heartbeat success rate | PENDING | per-device explicit count §11.2 |",
        "| Unexplained offline > 30m | PENDING | 0 required |",
        "| Command timeout | PENDING | 0 unhandled |",
        "| Service crash/uninstall/tamper | PENDING | 0 unexplained |",
        "",
        "Fill this section from `scripts/faz22-non-domain/a1-soak-rollup.sh` after the evidence window. Do not infer PASS from local diagnostics alone.",
        "",
        "## 7. KVKK / consent (A2 BYOD only)",
        "",
        "- Consent ID: N/A for A1",
        "- Consent timestamp: N/A for A1",
        "- Data inventory ref: N/A for A1",
        "- Retention policy enforced (BE-019): N/A for A1",
        "- Uninstall self-service tested: N/A for A1",
        "",
        "## 8. EDR allowlist (A2/A3/A4 only)",
        "",
        "- SOC ticket: N/A for A1",
        "- Agent SHA256 allowlisted: N/A for A1 lab exception unless operator policy requires it",
        "- Service display name allowlisted: EndpointAgent",
        "- Install path allowlisted: `C:\\Program Files\\EndpointAgent`",
        "",
        "## 9. Cleanup / rollback",
        "",
        "- Uninstall timestamp: PENDING / N/A during soak",
        "- Install dir removed: PENDING / N/A during soak",
        "- Log dir removed: PENDING / N/A during soak",
        "- Backend device disabled: PENDING / N/A during soak",
        "",
        "## 10. Boundary",
        "",
        "- This evidence draft is per-device only.",
        "- It does **not** complete #1044 by itself.",
        "- #1044 still requires the remaining devices, planned non-destructive command facts, 24h soak facts, and pilot-wide rollup evidence.",
        "- No destructive command, password reset, local password change, domain join, SMB/file action, or account mutation is represented by this draft.",
        "",
    ]

    rendered = "\n".join(lines)
    scan_for_secrets(rendered, "generated markdown")
    return rendered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a sanitized #1044 per-device evidence markdown draft from local VM diagnostics.",
    )
    parser.add_argument("--diagnostics-file", required=True, help="Path to read-only-diagnostics.txt from a1-local-vm-diagnostics.sh")
    parser.add_argument("--output", help="Write markdown to this exact path. Defaults to stdout unless --output-dir is set.")
    parser.add_argument("--output-dir", help="Write markdown under this directory using date/tier/hostname naming.")
    parser.add_argument("--tracked-by", default="1044")
    parser.add_argument("--tier", default="A1", choices=["A1", "A2", "A3", "A4"])
    parser.add_argument("--status", default="PARTIAL", choices=["PARTIAL", "FAIL"])
    parser.add_argument("--operator", default="operator")
    parser.add_argument("--codex-thread", default="PENDING")
    parser.add_argument("--device-id", default="PENDING")
    parser.add_argument("--platform-agent-commit", default="PENDING")
    parser.add_argument("--agent-sha256", default="PENDING")
    parser.add_argument("--authenticode-signed", default="no — A1 lab exception unless signed evidence is provided")
    parser.add_argument("--install-method", default="PENDING")
    parser.add_argument("--install-timestamp", default="PENDING")
    parser.add_argument("--enrollment-token-mint-timestamp", default="PENDING")
    parser.add_argument("--enroll-timestamp", default="PENDING")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diag_path = Path(args.diagnostics_file)
    if not diag_path.exists():
        die(f"--diagnostics-file not found: {diag_path}")
    if not diag_path.is_file():
        die(f"--diagnostics-file is not a file: {diag_path}")

    text = diag_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        die("--diagnostics-file is empty")
    scan_for_secrets(text, str(diag_path))

    parsed_sections = sections(text)
    if "diagnose-identity" not in parsed_sections:
        die("diagnostics file is missing required section: diagnose-identity")

    identity = first_json(parsed_sections.get("diagnose-identity", "")) or {}
    hostname = scalar(identity.get("hostname"), "unknown-device")
    rendered = build_markdown(args, text, parsed_sections)

    destination = output_path(args, hostname)
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        print(f"[faz22-a1-evidence-doc] wrote {destination}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
