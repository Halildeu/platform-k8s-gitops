#!/usr/bin/env python3
"""Install existing frontend development servers on retired host .53 only."""
import os
from pathlib import Path
import socket
import subprocess

if os.geteuid() != 0:
    raise SystemExit("Run with sudo")
if socket.gethostname() != "stagingsw":
    raise SystemExit("Unexpected host")
if "10.9.10.53" not in subprocess.check_output(["hostname", "-I"], text=True).split():
    raise SystemExit("Unexpected host address")
source = Path(__file__).resolve().parent
apps = {
    "mfe-suggestions": (33001, "SUGGESTIONS"),
    "mfe-ethic": (33002, "ETHIC"),
    "mfe-users": (33004, "USERS"),
    "mfe-access": (33005, "ACCESS"),
    "mfe-audit": (33006, "AUDIT"),
    "mfe-reporting": (33007, "REPORTING"),
    "mfe-schema-explorer": (33008, "SCHEMA_EXPLORER"),
    "mfe-endpoint-admin": (33009, "ENDPOINT_ADMIN"),
    "mfe-meeting": (33010, "MEETING"),
    "mfe-interview-evidence": (33011, "INTERVIEW_EVIDENCE"),
}
for app in apps:
    if not Path("/srv/platform-dev/repos/platform-web/apps", app, "vite.config.ts").is_file():
        raise SystemExit(f"Missing frontend source: {app}")
base = Path("/etc/platform-dev/frontend")
base.mkdir(parents=True, exist_ok=True)
lines = [
    "MFE_SHELL_URL=http://127.0.0.1:33000/remoteEntry.js",
    "VITE_SHELL_ENABLE_ENDPOINT_ADMIN_REMOTE=1",
    "MFE_MEETING_DEV_FEDERATION=1",
    "VITE_FRONTEND_PUBLIC_ORIGIN=http://127.0.0.1:33000",
    "VITE_KEYCLOAK_URL=http://127.0.0.1:33081",
    "VITE_KEYCLOAK_REALM=platform-dev",
    "VITE_ENABLE_FAKE_AUTH=false",
]
units = ["platform-dev-preview.service"]
for app, (port, key) in apps.items():
    (base / f"{app}.env").write_text(f"DEV_PORT={port}\n")
    lines.append(f"MFE_{key}_URL=http://127.0.0.1:{port}/remoteEntry.js")
    units.append(f"platform-dev-mfe@{app}.service")
Path("/etc/platform-dev/frontend-common.env").write_text("\n".join(lines) + "\n")
for name in ["platform-dev-mfe@.service", "platform-dev-preview.service"]:
    subprocess.run(["install", "-m", "644", str(source / name), f"/etc/systemd/system/{name}"], check=True)
subprocess.run(["systemd-analyze", "verify", "/etc/systemd/system/platform-dev-preview.service", "/etc/systemd/system/platform-dev-mfe@.service"], check=True)
subprocess.run(["systemctl", "daemon-reload"], check=True)
subprocess.run(["systemctl", "enable", *units], check=True)
subprocess.run(["systemctl", "restart", *units], check=True)
print(f"Started {len(units)} loopback DEV frontend servers; application backend acceptance is separate.")
