#!/usr/bin/env python3
"""
scripts/alerting/alertmanager-bridge.py

Codex Sprint A retrospective follow-up — AlertManager webhook → GitHub Issues bridge.
Mevcut alarm_receiver.sh pattern (PR #347) ile uyumlu format'ta GitHub issue
yaratır + auto-deduplication via title match.

Çalışma şekli:
  1. AlertManager firing alert webhook POST → /alert endpoint
  2. Bridge JSON parse → alarm class belirle (severity → P1/P2/P3)
  3. Stable signature title yarat (alertname + namespace + severity)
  4. gh CLI ile GitHub issue aç veya mevcut issue'a comment ekle
  5. Persistent fail log → /var/log/alertmanager-bridge-undelivered.jsonl

Severity mapping:
  - critical → P1 (operator action <10min, GitHub issue + comment)
  - warning  → P2 (review <1 day)
  - info     → P3 (backlog grooming)

Endpoint:
  POST /alert    → AlertManager webhook hedefi
  GET  /healthz  → liveness/readiness probe

Env:
  GITHUB_REPO              — varsayılan: Halildeu/platform-k8s-gitops
  GITHUB_TOKEN            — gh API auth (issue create/comment)
  BRIDGE_PORT             — varsayılan 9093
  BRIDGE_LOG_LEVEL        — INFO/DEBUG/WARN/ERROR (varsayılan INFO)

Usage:
  python3 alertmanager-bridge.py
  GITHUB_TOKEN=ghp_... python3 alertmanager-bridge.py
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

LOG_LEVEL = os.environ.get("BRIDGE_LOG_LEVEL", "INFO")
PORT = int(os.environ.get("BRIDGE_PORT", "9093"))
GH_REPO = os.environ.get("GITHUB_REPO", "Halildeu/platform-k8s-gitops")
UNDELIVERED_LOG = os.environ.get(
    "BRIDGE_UNDELIVERED_LOG",
    "/var/log/alertmanager-bridge-undelivered.jsonl",
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("alertmanager-bridge")


def severity_to_class(severity: str) -> str:
    """Map AlertManager severity → drift detection class."""
    return {
        "critical": "P1",
        "warning": "P2",
        "info": "P3",
    }.get(severity.lower(), "P2")


def make_issue_title(alert: dict[str, Any]) -> str:
    """Stable title for auto-deduplication.

    Codex `019e2a4f` Session 53 P0 #3 absorb (PMD DoD §2.4(d) dedupe key extend):
    title format `[alertmanager-<cls>] <alertname>/<namespace>/<configmap-or-route>@<cluster>`
    - alertname (mandatory)
    - namespace (fallback "")
    - configmap (status writer alert key) veya route (cross-namespace alert)
    - cluster (Prom external_label; fallback "")
    """
    labels = alert.get("labels", {})
    alertname = labels.get("alertname", "UnknownAlert")
    namespace = labels.get("namespace", "")
    configmap = labels.get("configmap", "")
    route = labels.get("route", "")
    cluster = labels.get("cluster", "")
    severity = labels.get("severity", "warning")
    cls = severity_to_class(severity)

    # PMD DoD §2.4(d) dedupe key:
    parts = [alertname]
    if namespace:
        parts.append(namespace)
    # configmap veya route — biri varsa unique key kompozisyonu
    cm_or_route = configmap or route
    if cm_or_route:
        parts.append(cm_or_route)
    suffix = "/".join(parts[1:])
    suffix_str = f"/{suffix}" if suffix else ""
    cluster_str = f"@{cluster}" if cluster else ""
    return f"[alertmanager-{cls}] {parts[0]}{suffix_str}{cluster_str}"


def make_issue_body(alert: dict[str, Any], group_labels: dict[str, str]) -> str:
    """Build markdown body with all alert metadata."""
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    severity = labels.get("severity", "warning")
    cls = severity_to_class(severity)
    starts_at = alert.get("startsAt", "unknown")
    generator_url = alert.get("generatorURL", "")

    body = f"""**Class**: `{cls}`
**Severity**: `{severity}`
**Alertname**: `{labels.get('alertname', 'unknown')}`
**Namespace**: `{labels.get('namespace', '-')}`
**Pod/Service**: `{labels.get('pod', labels.get('service', '-'))}`
**Started at**: `{starts_at}`

## Summary

{annotations.get('summary', '(no summary)')}

## Description

{annotations.get('description', '(no description)')}

## Runbook

{annotations.get('runbook_url', '(no runbook)')}

## Generator

{generator_url}

## Labels

```json
{json.dumps(labels, indent=2)}
```

## Operator playbook

| Class | Action |
|---|---|
| P1 | Operator action required within 10min |
| P2 | Warning — review within 1 day |
| P3 | Info — backlog grooming |

## Auto-deduplication

This issue auto-deduplicates on title match. Repeated alerts add comments to this thread.
Close the issue once alert resolves (AlertManager `send_resolved: true` will note resolution).

---

🤖 Auto-opened by alertmanager-bridge (Codex Sprint A follow-up).
"""
    return body


def gh_issue_search_open(title: str) -> int | None:
    """Find existing open issue by exact title. Returns issue number or None."""
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                GH_REPO,
                "--state",
                "open",
                "--search",
                f'"{title}" in:title',
                "--json",
                "number,title",
                "--jq",
                f'.[] | select(.title == "{title}") | .number',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split("\n")[0])
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
        log.warning(f"gh issue search failed: {e}")
    return None


def gh_issue_create(title: str, body: str, labels: list[str]) -> bool:
    """Open new GitHub issue. Returns True on success."""
    label_arg = ",".join(labels)
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                GH_REPO,
                "--title",
                title,
                "--label",
                label_arg,
                "--body",
                body,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            log.info(f"opened: {title}")
            return True
        log.error(f"gh issue create failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error(f"gh issue create exception: {e}")
    return False


def gh_issue_comment(num: int, body: str) -> bool:
    """Comment on existing issue. Returns True on success."""
    try:
        result = subprocess.run(
            ["gh", "issue", "comment", str(num), "--repo", GH_REPO, "--body", body],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            log.info(f"commented #{num}")
            return True
        log.error(f"gh issue comment failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error(f"gh issue comment exception: {e}")
    return False


def gh_issue_close(num: int, reason: str = "completed") -> bool:
    """Close existing issue with reason (Codex `019e2a4f` Session 53 P0 #2 absorb —
    resolved lifecycle: send_resolved=true → issue close + final comment).
    Returns True on success.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "close",
                str(num),
                "--repo",
                GH_REPO,
                "--reason",
                reason,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            log.info(f"closed #{num} (reason={reason})")
            return True
        log.error(f"gh issue close failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error(f"gh issue close exception: {e}")
    return False


def log_undelivered(alert: dict[str, Any], reason: str) -> None:
    """Persist failed delivery for retry/audit."""
    try:
        log_dir = Path(UNDELIVERED_LOG).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback to /tmp
        global UNDELIVERED_LOG
        UNDELIVERED_LOG = "/tmp/alertmanager-bridge-undelivered.jsonl"

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "alert": alert,
        "reason": reason,
    }
    try:
        with open(UNDELIVERED_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        log.error(f"undelivered log write failed: {e}")


def process_alert(alert: dict[str, Any], group_labels: dict[str, str]) -> bool:
    """Process single firing alert. Returns True if delivered.

    Codex `019e2a4f` Session 53 P0 #2 absorb (lifecycle):
    - firing + no open issue → create new
    - firing + existing open issue → comment recurrence
    - resolved + existing open issue → comment resolved + CLOSE issue
    - resolved + no open issue → no-op (already closed earlier)
    """
    status = alert.get("status", "firing")
    title = make_issue_title(alert)

    if status == "resolved":
        existing = gh_issue_search_open(title)
        if existing:
            ends_at = alert.get("endsAt", "unknown")
            comment_ok = gh_issue_comment(
                existing,
                f"✅ Alert resolved at `{ends_at}` (AlertManager send_resolved=true).",
            )
            close_ok = gh_issue_close(existing, reason="completed")
            return comment_ok and close_ok
        log.info(f"resolved alert {title} but no open issue found (already closed)")
        return True

    body = make_issue_body(alert, group_labels)
    labels = alert.get("labels", {})
    severity = labels.get("severity", "warning")
    cls = severity_to_class(severity)

    issue_labels = ["alertmanager", cls.lower(), severity]

    existing = gh_issue_search_open(title)
    if existing:
        starts_at = alert.get("startsAt", "unknown")
        return gh_issue_comment(
            existing, f"🔥 Recurrence at `{starts_at}` (still firing)."
        )

    delivered = gh_issue_create(title, body, issue_labels)
    if not delivered:
        log_undelivered(alert, "gh_issue_create_failed")
    return delivered


class AlertHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default access log; use our logger."""
        log.debug(fmt % args)

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/alert":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError) as e:
            log.error(f"invalid JSON payload: {e}")
            self.send_response(400)
            self.end_headers()
            return

        # AlertManager webhook payload structure:
        # { version, groupKey, status, receiver, groupLabels, commonLabels, alerts: [...] }
        alerts = payload.get("alerts", [])
        group_labels = payload.get("groupLabels", {})
        log.info(f"received {len(alerts)} alert(s) from group {group_labels}")

        delivered = 0
        for alert in alerts:
            if process_alert(alert, group_labels):
                delivered += 1

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = {"received": len(alerts), "delivered": delivered}
        self.wfile.write(json.dumps(response).encode())


def main() -> int:
    log.info(f"alertmanager-bridge starting on :{PORT} (repo={GH_REPO})")
    server = HTTPServer(("0.0.0.0", PORT), AlertHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
