#!/usr/bin/env python3
"""Build or run the #1044 A1 operator evidence pack from a device manifest.

The existing #1044 helpers are intentionally small:

* a1-local-vm-diagnostics.sh collects read-only local Parallels diagnostics.
* a1-evidence-doc-from-diagnostics.py renders one per-device evidence draft.
* a1-soak-rollup.sh reads backend heartbeat/command facts with SELECT-only SQL.
* a1-rollup-doc-from-soak.py renders the pilot-wide rollup draft.

This wrapper ties those helpers together from a no-secret JSON manifest. Default
mode is dry-run: it writes an operator checklist and a command script. Optional
flags can execute diagnostics, render per-device docs, run the SELECT-only soak
helper, and render the rollup doc. It never accepts JWTs, passwords, enrollment
tokens, webhook URLs, private keys, or raw credentials.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+(?!<redacted>)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"Authorization:\s*(?!<redacted>)[^\s]+", re.IGNORECASE),
    re.compile(r"credential=(?!<redacted>)[^,;\s]+", re.IGNORECASE),
    re.compile(r"(token|secret|password|clientSecret|accessToken|refreshToken)\s*[:=]\s*(?!<redacted>)[^,}\r\n]+", re.IGNORECASE),
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
SAFE_STATUS = {"PASS", "PARTIAL", "FAIL", "PENDING"}
SAFE_TIER = {"A1", "A2", "A3", "A4"}


def die(message: str) -> None:
    print(f"[faz22-a1-operator-pack] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def log(message: str) -> None:
    print(f"[faz22-a1-operator-pack] {message}")


def scan_for_secrets(text: str, source: str) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            die(f"potential secret-like value in {source}: {match.group(0)[:80]!r}")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_date() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return safe or "unknown-device"


def q(value: str | Path) -> str:
    return shlex.quote(str(value))


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        die(f"--manifest not found: {path}")
    if not path.is_file():
        die(f"--manifest is not a file: {path}")
    text = path.read_text(encoding="utf-8")
    scan_for_secrets(text, str(path))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"--manifest is not valid JSON: {exc}")
    if not isinstance(data, dict):
        die("--manifest root must be a JSON object")
    return data


def validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    tracked_by = str(data.get("trackedBy", "1044")).lstrip("#")
    if not tracked_by.isdigit():
        die("manifest trackedBy must be a GitHub issue number, e.g. 1044")

    tier = str(data.get("tier", "A1"))
    if tier not in SAFE_TIER:
        die(f"manifest tier must be one of {sorted(SAFE_TIER)}")
    if tier != "A1":
        die("this wrapper is intentionally bounded to A1 evidence packs")

    devices_raw = data.get("devices")
    if not isinstance(devices_raw, list) or not devices_raw:
        die("manifest devices must be a non-empty array")

    devices: list[dict[str, str]] = []
    for index, raw in enumerate(devices_raw, start=1):
        if not isinstance(raw, dict):
            die(f"devices[{index}] must be an object")
        vm = str(raw.get("vm", "")).strip()
        hostname = str(raw.get("hostname", vm)).strip()
        device_id = str(raw.get("deviceId", "PENDING")).strip()
        status = str(raw.get("status", "PENDING")).strip().upper()
        if not vm:
            die(f"devices[{index}].vm is required")
        if "\n" in vm or "\r" in vm or "\t" in vm:
            die(f"devices[{index}].vm contains unsafe control whitespace")
        if not hostname:
            die(f"devices[{index}].hostname is required")
        if device_id != "PENDING" and not UUID_RE.match(device_id):
            die(f"devices[{index}].deviceId must be a UUID or PENDING")
        if status not in SAFE_STATUS:
            die(f"devices[{index}].status must be one of {sorted(SAFE_STATUS)}")
        evidence_doc = str(raw.get("evidenceDoc", "")).strip()
        if not evidence_doc:
            evidence_doc = f"{utc_date()}-non-domain-pilot-tier{tier}-{safe_component(hostname)}.md"
        devices.append(
            {
                "vm": vm,
                "hostname": hostname,
                "deviceId": device_id,
                "status": status,
                "evidenceDoc": evidence_doc,
                "operator": str(raw.get("operator", data.get("operator", "operator"))).strip() or "operator",
                "installMethod": str(raw.get("installMethod", data.get("installMethod", "A1 lab install"))).strip() or "A1 lab install",
                "platformAgentCommit": str(raw.get("platformAgentCommit", "PENDING")).strip() or "PENDING",
                "agentSha256": str(raw.get("agentSha256", "PENDING")).strip() or "PENDING",
            }
        )

    return {
        "trackedBy": tracked_by,
        "tier": tier,
        "operator": str(data.get("operator", "operator")).strip() or "operator",
        "soakWindow": str(data.get("soakWindow", "PENDING")).strip() or "PENDING",
        "codexThread": str(data.get("codexThread", "PENDING")).strip() or "PENDING",
        "devices": devices,
    }


def example_manifest() -> dict[str, Any]:
    return {
        "trackedBy": "1044",
        "tier": "A1",
        "operator": "local-operator",
        "installMethod": "A1 lab install",
        "soakWindow": "PENDING",
        "devices": [
            {
                "vm": "Windows 11",
                "hostname": "HALILKOOLUB735",
                "deviceId": "d0efb00a-681a-4e32-b7de-a27ef94f2977",
                "status": "PARTIAL",
                "evidenceDoc": "2026-06-07-non-domain-pilot-tierA1-HALILKOOLUB735-current.md",
            },
            {
                "vm": "NONDOMAIN-W11-LAB-01",
                "hostname": "NONDOMAIN-W11-LAB-01",
                "deviceId": "PENDING",
                "status": "PENDING",
            },
            {
                "vm": "NONDOMAIN-W11-LAB-02",
                "hostname": "NONDOMAIN-W11-LAB-02",
                "deviceId": "PENDING",
                "status": "PENDING",
            },
        ],
    }


def command_plan(args: argparse.Namespace, manifest: dict[str, Any], out_dir: Path, diagnostics_dir: Path) -> list[list[str]]:
    devices = manifest["devices"]
    soak_devices = [device for device in devices if device["deviceId"] != "PENDING"]
    vm_args: list[str] = []
    for device in devices:
        vm_args.extend(["--vm", device["vm"]])

    diagnostics_cmd = [
        "bash",
        "scripts/faz22-non-domain/a1-local-vm-diagnostics.sh",
        "--output-dir",
        str(diagnostics_dir),
        "--section-timeout-seconds",
        str(args.section_timeout_seconds),
    ]
    if args.include_winget_egress:
        diagnostics_cmd.append("--include-winget-egress")
    diagnostics_cmd.extend(vm_args)

    commands: list[list[str]] = [diagnostics_cmd]

    for device in devices:
        diag_path = diagnostics_dir / safe_component(device["vm"]) / "read-only-diagnostics.txt"
        evidence_path = Path(args.evidence_dir) / device["evidenceDoc"]
        commands.append(
            [
                "env",
                "PYTHONDONTWRITEBYTECODE=1",
                "python3",
                "scripts/faz22-non-domain/a1-evidence-doc-from-diagnostics.py",
                "--diagnostics-file",
                str(diag_path),
                "--output",
                str(evidence_path),
                "--tracked-by",
                manifest["trackedBy"],
                "--tier",
                manifest["tier"],
                "--status",
                "PARTIAL" if device["status"] == "PENDING" else device["status"],
                "--operator",
                device["operator"],
                "--codex-thread",
                manifest["codexThread"],
                "--device-id",
                device["deviceId"],
                "--platform-agent-commit",
                device["platformAgentCommit"],
                "--agent-sha256",
                device["agentSha256"],
                "--install-method",
                device["installMethod"],
            ]
        )

    soak_path = Path(args.soak_output) if args.soak_output else out_dir / "soak-rollup.txt"
    if args.run_soak and not args.soak_output:
        soak_cmd = [
            "bash",
            "scripts/faz22-non-domain/a1-soak-rollup.sh",
            "--window-hours",
            str(args.window_hours),
        ]
        for device in soak_devices:
            soak_cmd.extend(["--device-id", device["deviceId"]])
        if args.run_soak:
            soak_cmd.append("--execute")
        if args.ssh_target:
            soak_cmd.extend(["--ssh-target", args.ssh_target])
        if args.ssh_identity_file:
            soak_cmd.extend(["--ssh-identity-file", args.ssh_identity_file])
        if args.docker_container:
            soak_cmd.extend(["--docker-container", args.docker_container])
        if args.db:
            soak_cmd.extend(["--db", args.db])
        if args.user:
            soak_cmd.extend(["--user", args.user])
        commands.append(["bash", "-c", " ".join(q(part) for part in soak_cmd) + " | tee " + q(soak_path)])

    if args.soak_output or args.run_soak:
        rollup_args = [
            "env",
            "PYTHONDONTWRITEBYTECODE=1",
            "python3",
            "scripts/faz22-non-domain/a1-rollup-doc-from-soak.py",
            "--soak-output",
            str(soak_path),
            "--output",
            str(Path(args.evidence_dir) / args.rollup_doc),
            "--tracked-by",
            manifest["trackedBy"],
            "--tier",
            manifest["tier"],
            "--status",
            args.rollup_status,
            "--soak-window",
            manifest["soakWindow"],
            "--codex-thread",
            manifest["codexThread"],
        ]
        for device in soak_devices:
            doc_ref = "./" + Path(device["evidenceDoc"]).name
            rollup_args.extend(
                [
                    "--device",
                    f"{device['deviceId']}={device['hostname']},{manifest['tier']},{doc_ref},{device['status']}",
                ]
            )
        commands.append(rollup_args)
    return commands


def write_shell_script(path: Path, commands: list[list[str]]) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by a1-operator-evidence-pack.py. Review before execute.",
        "",
    ]
    for index, command in enumerate(commands, start=1):
        lines.append(f"echo '[faz22-a1-operator-pack] step {index}/{len(commands)}'")
        lines.append(" ".join(q(part) for part in command))
        lines.append("")
    rendered = "\n".join(lines)
    scan_for_secrets(rendered, str(path))
    path.write_text(rendered, encoding="utf-8")
    path.chmod(0o755)


def write_checklist(path: Path, manifest: dict[str, Any], commands_path: Path, diagnostics_dir: Path, args: argparse.Namespace) -> None:
    generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        "# Faz 22.2.A #1044 A1 operator evidence pack",
        "",
        f"> Generated at: {generated_at}",
        f"> Tracked by: #{manifest['trackedBy']}",
        f"> Tier: {manifest['tier']}",
        f"> Status: operator checklist; not acceptance evidence by itself",
        "",
        "## Device manifest",
        "",
        "| # | VM | Hostname | Device ID | Status | Evidence doc |",
        "|---|---|---|---|---|---|",
    ]
    for index, device in enumerate(manifest["devices"], start=1):
        lines.append(
            f"| {index} | `{device['vm']}` | `{device['hostname']}` | `{device['deviceId']}` | {device['status']} | `{device['evidenceDoc']}` |"
        )
    lines += [
        "",
        "## Operator sequence",
        "",
        "1. Prepare or start each listed Parallels Windows VM.",
        "2. Ensure each VM has a unique hostname, is A1 workgroup/non-domain, and reaches `testai.acik.com:443`.",
        "3. Install/enroll EndpointAgent on each VM using the existing runbook. Do not store enrollment tokens in this manifest.",
        "4. Run read-only diagnostics for all VMs.",
        "5. Generate one per-device evidence markdown file per VM.",
        "6. Run one non-destructive `COLLECT_INVENTORY` command per device from the admin UI/API and record command IDs in the per-device docs.",
        "7. After the observation window, run the SELECT-only soak rollup.",
        "8. Generate the pilot-wide rollup evidence draft.",
        "9. Review every `PENDING`, `PARTIAL`, `REVIEW`, `FAILED`, and nonterminal command before #1044 acceptance.",
        "",
        "## Generated local paths",
        "",
        f"- Diagnostics output dir: `{diagnostics_dir}`",
        f"- Command script: `{commands_path}`",
        f"- Evidence dir: `{args.evidence_dir}`",
        f"- Rollup doc: `{args.rollup_doc}`",
        f"- Soak/rollup command scope: `{sum(1 for d in manifest['devices'] if d['deviceId'] != 'PENDING')}` device(s) with concrete backend UUID; replace `PENDING` device IDs and rerun before final acceptance.",
        f"- Soak SELECT command included: `{'yes' if args.run_soak else 'no — pass --run-soak after the observation window'}`",
        f"- Rollup generation command included: `{'yes' if args.soak_output or args.run_soak else 'no — provide --soak-output or --run-soak after the observation window'}`",
        "",
        "## Commands",
        "",
        "Run manually after review:",
        "",
        "```bash",
        str(commands_path),
        "```",
        "",
        "## Boundary",
        "",
        "- This pack does not dispatch backend commands, read credentials, mutate accounts, or complete #1044.",
        "- It does not contain JWTs, enrollment tokens, passwords, private keys, webhook URLs, or raw credential material.",
        "- It is A1-only. A2 BYOD, A3 Entra, A4 Workplace, domain join, password reset, SMB/file actions, and destructive commands are out of scope.",
    ]
    rendered = "\n".join(lines) + "\n"
    scan_for_secrets(rendered, str(path))
    path.write_text(rendered, encoding="utf-8")


def run_checked(command: list[str]) -> None:
    log("+ " + " ".join(q(part) for part in command))
    subprocess.run(command, check=True)


def execute_selected(args: argparse.Namespace, commands: list[list[str]], manifest: dict[str, Any]) -> None:
    device_count = len(manifest["devices"])
    if args.run_diagnostics:
        run_checked(commands[0])
    if args.generate_device_docs:
        for command in commands[1 : 1 + device_count]:
            run_checked(command)
    if args.run_soak:
        soak_index = 1 + device_count
        if soak_index >= len(commands):
            die("--run-soak requested but no soak command was generated")
        run_checked(commands[soak_index])
    if args.generate_rollup_doc:
        run_checked(commands[-1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or run the #1044 A1 operator evidence pack.")
    parser.add_argument("--manifest", help="No-secret JSON device manifest.")
    parser.add_argument("--write-example-manifest", help="Write a starter manifest JSON and exit.")
    parser.add_argument("--output-dir", default="", help="Pack output dir. Default: /tmp/faz22-a1-operator-pack-<utc>.")
    parser.add_argument("--diagnostics-dir", default="", help="Diagnostics dir. Default: <output-dir>/diagnostics.")
    parser.add_argument("--evidence-dir", default="docs/faz-22-evidence")
    parser.add_argument("--rollup-doc", default=f"{utc_date()}-non-domain-pilot-tierA1-rollup.md")
    parser.add_argument("--rollup-status", default="PARTIAL", choices=["PARTIAL", "FAIL"])
    parser.add_argument("--section-timeout-seconds", type=int, default=120)
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--include-winget-egress", action="store_true")
    parser.add_argument("--run-diagnostics", action="store_true")
    parser.add_argument("--generate-device-docs", action="store_true")
    parser.add_argument("--run-soak", action="store_true")
    parser.add_argument("--generate-rollup-doc", action="store_true")
    parser.add_argument("--soak-output", default="")
    parser.add_argument("--ssh-target", default="")
    parser.add_argument("--ssh-identity-file", default="")
    parser.add_argument("--docker-container", default="")
    parser.add_argument("--db", default="")
    parser.add_argument("--user", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.write_example_manifest:
        dest = Path(args.write_example_manifest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(example_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        log(f"wrote example manifest: {dest}")
        return 0

    if not args.manifest:
        die("--manifest is required unless --write-example-manifest is used")
    if args.section_timeout_seconds <= 0:
        die("--section-timeout-seconds must be > 0")
    if args.window_hours <= 0:
        die("--window-hours must be > 0")
    if args.generate_rollup_doc and not (args.soak_output or args.run_soak):
        die("--generate-rollup-doc requires --soak-output or --run-soak")

    manifest = validate_manifest(load_manifest(Path(args.manifest)))
    concrete_device_count = sum(1 for device in manifest["devices"] if device["deviceId"] != "PENDING")
    if (args.run_soak or args.generate_rollup_doc) and concrete_device_count == 0:
        die("--run-soak/--generate-rollup-doc requires at least one concrete backend deviceId in the manifest")
    if (args.run_soak or args.generate_rollup_doc) and concrete_device_count < len(manifest["devices"]):
        log(
            "manifest has PENDING deviceId entries; soak/rollup commands will include only "
            f"{concrete_device_count}/{len(manifest['devices'])} concrete device(s)"
        )
    out_dir = Path(args.output_dir) if args.output_dir else Path(f"/tmp/faz22-a1-operator-pack-{utc_stamp()}")
    diagnostics_dir = Path(args.diagnostics_dir) if args.diagnostics_dir else out_dir / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    normalized_manifest = out_dir / "manifest.normalized.json"
    normalized_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    commands = command_plan(args, manifest, out_dir, diagnostics_dir)
    commands_path = out_dir / "run-evidence-pack.sh"
    checklist_path = out_dir / "operator-checklist.md"
    write_shell_script(commands_path, commands)
    write_checklist(checklist_path, manifest, commands_path, diagnostics_dir, args)

    log(f"wrote normalized manifest: {normalized_manifest}")
    log(f"wrote command script: {commands_path}")
    log(f"wrote checklist: {checklist_path}")

    execute_selected(args, commands, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
