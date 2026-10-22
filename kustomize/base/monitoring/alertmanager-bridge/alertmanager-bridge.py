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

import collections
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

LOG_LEVEL = os.environ.get("BRIDGE_LOG_LEVEL", "INFO")
PORT = int(os.environ.get("BRIDGE_PORT", "9093"))
GH_REPO = os.environ.get("GITHUB_REPO", "Halildeu/platform-k8s-gitops")
UNDELIVERED_LOG = os.environ.get(
    "BRIDGE_UNDELIVERED_LOG",
    "/var/log/alertmanager-bridge-undelivered.jsonl",
)
# Codex `019e2a4f` Session 53 P0 C absorb: undelivered.jsonl bounded size guard
# (PVC opsiyonel; pod restart kayıp accepted — metrics ile görünürlük).
UNDELIVERED_MAX_BYTES = int(os.environ.get("BRIDGE_UNDELIVERED_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("alertmanager-bridge")


# Codex `019e2a4f` Session 53 P0 C — Prometheus metrics (stdlib, no external deps)
# /metrics endpoint exposes operational counters; ServiceMonitor scrape.
# Future: prometheus_client library + histogram. Şu an pure stdlib pattern.
_METRICS = {
    "delivered_total": 0,
    "undelivered_total": 0,
    "undelivered_by_reason": {},  # reason → count
    "github_api_call_total": 0,
    "github_api_fail_total": 0,
    "github_api_latency_seconds_sum": 0.0,
    "github_api_latency_seconds_count": 0,
    "last_delivery_success_timestamp": 0,
    "last_delivery_failure_timestamp": 0,
    "webhook_received_total": 0,
    "synthetic_skipped_total": 0,
    # Codex `019e6fb5` AGREE Yol C-prime — startup auth drift sentinel.
    # 1 if GITHUB_TOKEN env non-empty at process start; 0 otherwise. Pairs with
    # PrometheusRule AlertmanagerBridgeGHSecretAbsent — silent ESO sync errors
    # become visible without bridge depending on itself for paging.
    "github_token_configured": 1 if os.environ.get("GITHUB_TOKEN", "") else 0,
    # #3888 — direct operator paging (SMS via JetSMS + email via Graph), independent
    # of notification-orchestrator so a notify outage still pages a human.
    "notify_sent_total": {},      # channel → count
    "notify_fail_total": {},      # channel → count
    "notify_sms_ratelimited_total": 0,
}


def metric_inc(name: str, value: int | float = 1) -> None:
    """Increment counter metric."""
    _METRICS[name] = _METRICS.get(name, 0) + value


def metric_inc_reason(reason: str) -> None:
    """Increment undelivered counter by reason."""
    _METRICS["undelivered_by_reason"][reason] = _METRICS["undelivered_by_reason"].get(reason, 0) + 1


def metric_observe_latency(seconds: float) -> None:
    """Record GitHub API call latency (sum + count for histogram_quantile via Prom)."""
    _METRICS["github_api_latency_seconds_sum"] += seconds
    _METRICS["github_api_latency_seconds_count"] += 1


def metric_set_timestamp(name: str, ts: float | None = None) -> None:
    """Set timestamp gauge (last delivery success/failure)."""
    _METRICS[name] = int(ts if ts is not None else time.time())


def render_metrics() -> bytes:
    """Render Prometheus text exposition format (no external lib)."""
    lines = []
    # Counter: delivered_total
    lines.append("# HELP alertmanager_bridge_delivered_total Total alerts successfully delivered as GitHub issues (create/comment/close)")
    lines.append("# TYPE alertmanager_bridge_delivered_total counter")
    lines.append(f"alertmanager_bridge_delivered_total {_METRICS['delivered_total']}")
    # Counter: undelivered_total + by_reason
    lines.append("# HELP alertmanager_bridge_undelivered_total Total alerts that failed delivery")
    lines.append("# TYPE alertmanager_bridge_undelivered_total counter")
    lines.append(f"alertmanager_bridge_undelivered_total {_METRICS['undelivered_total']}")
    lines.append("# HELP alertmanager_bridge_undelivered_by_reason_total Undelivered alerts by failure reason")
    lines.append("# TYPE alertmanager_bridge_undelivered_by_reason_total counter")
    for reason, count in _METRICS["undelivered_by_reason"].items():
        # Escape reason label per Prom text format (basic — no quotes/newlines expected)
        safe_reason = reason.replace('"', '\\"')
        lines.append(f'alertmanager_bridge_undelivered_by_reason_total{{reason="{safe_reason}"}} {count}')
    # Counter: github_api_call_total + fail_total
    lines.append("# HELP alertmanager_bridge_github_api_call_total Total GitHub API calls (issue search/create/comment/close)")
    lines.append("# TYPE alertmanager_bridge_github_api_call_total counter")
    lines.append(f"alertmanager_bridge_github_api_call_total {_METRICS['github_api_call_total']}")
    lines.append("# HELP alertmanager_bridge_github_api_fail_total GitHub API calls that returned non-zero exit (auth/rate-limit/network)")
    lines.append("# TYPE alertmanager_bridge_github_api_fail_total counter")
    lines.append(f"alertmanager_bridge_github_api_fail_total {_METRICS['github_api_fail_total']}")
    # Summary: github_api_latency (sum + count, histogram_quantile via Prom rate)
    lines.append("# HELP alertmanager_bridge_github_api_latency_seconds GitHub API call latency in seconds")
    lines.append("# TYPE alertmanager_bridge_github_api_latency_seconds summary")
    lines.append(f"alertmanager_bridge_github_api_latency_seconds_sum {_METRICS['github_api_latency_seconds_sum']:.6f}")
    lines.append(f"alertmanager_bridge_github_api_latency_seconds_count {_METRICS['github_api_latency_seconds_count']}")
    # Gauge: last delivery timestamps
    lines.append("# HELP alertmanager_bridge_last_delivery_success_timestamp_seconds Unix timestamp of last successful delivery")
    lines.append("# TYPE alertmanager_bridge_last_delivery_success_timestamp_seconds gauge")
    lines.append(f"alertmanager_bridge_last_delivery_success_timestamp_seconds {_METRICS['last_delivery_success_timestamp']}")
    lines.append("# HELP alertmanager_bridge_last_delivery_failure_timestamp_seconds Unix timestamp of last failed delivery")
    lines.append("# TYPE alertmanager_bridge_last_delivery_failure_timestamp_seconds gauge")
    lines.append(f"alertmanager_bridge_last_delivery_failure_timestamp_seconds {_METRICS['last_delivery_failure_timestamp']}")
    # Counter: webhook_received_total
    lines.append("# HELP alertmanager_bridge_webhook_received_total Total Alertmanager webhook POSTs received")
    lines.append("# TYPE alertmanager_bridge_webhook_received_total counter")
    lines.append(f"alertmanager_bridge_webhook_received_total {_METRICS['webhook_received_total']}")
    lines.append("# HELP alertmanager_bridge_synthetic_skipped_total Synthetic alerts skipped (is_synthetic=true filter; BL-008-bridge Codex 019e6de3)")
    lines.append("# TYPE alertmanager_bridge_synthetic_skipped_total counter")
    lines.append(f"alertmanager_bridge_synthetic_skipped_total {_METRICS['synthetic_skipped_total']}")
    # Gauge: github_token_configured — startup auth presence sentinel
    # (Codex `019e6fb5` AGREE Yol C-prime). 1 = GITHUB_TOKEN env non-empty at
    # process start; 0 = missing (ESO sync drift, secret absent, deploy misconfig).
    # Sampled once at startup; restart required to refresh after PAT rotation.
    lines.append("# HELP alertmanager_bridge_github_token_configured GH token env presence at startup (1=set non-empty, 0=missing — silent auth-drift sentinel)")
    lines.append("# TYPE alertmanager_bridge_github_token_configured gauge")
    lines.append(f"alertmanager_bridge_github_token_configured {_METRICS['github_token_configured']}")
    # #3888 operator paging channels
    lines.append("# HELP alertmanager_bridge_notify_channel_configured Paging channel has complete config at startup (1) or not (0)")
    lines.append("# TYPE alertmanager_bridge_notify_channel_configured gauge")
    for channel, ok in notify_channels_configured().items():
        lines.append(f'alertmanager_bridge_notify_channel_configured{{channel="{channel}"}} {1 if ok else 0}')
    lines.append("# HELP alertmanager_bridge_notify_sent_total Operator notifications accepted by the provider")
    lines.append("# TYPE alertmanager_bridge_notify_sent_total counter")
    lines.append("# HELP alertmanager_bridge_notify_fail_total Operator notifications rejected or not delivered to the provider")
    lines.append("# TYPE alertmanager_bridge_notify_fail_total counter")
    for channel in ("sms", "email"):
        lines.append(f'alertmanager_bridge_notify_sent_total{{channel="{channel}"}} {_METRICS["notify_sent_total"].get(channel, 0)}')
        lines.append(f'alertmanager_bridge_notify_fail_total{{channel="{channel}"}} {_METRICS["notify_fail_total"].get(channel, 0)}')
    lines.append("# HELP alertmanager_bridge_notify_sms_ratelimited_total SMS skipped by the hourly cap (email still sent)")
    lines.append("# TYPE alertmanager_bridge_notify_sms_ratelimited_total counter")
    lines.append(f"alertmanager_bridge_notify_sms_ratelimited_total {_METRICS['notify_sms_ratelimited_total']}")
    return ("\n".join(lines) + "\n").encode()


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
    metric_inc("github_api_call_total")
    start = time.monotonic()
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
        metric_observe_latency(time.monotonic() - start)
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split("\n")[0])
        if result.returncode != 0:
            metric_inc("github_api_fail_total")
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
        metric_observe_latency(time.monotonic() - start)
        metric_inc("github_api_fail_total")
        log.warning(f"gh issue search failed: {e}")
    return None


def gh_issue_create(title: str, body: str, labels: list[str]) -> bool:
    """Open new GitHub issue. Returns True on success."""
    label_arg = ",".join(labels)
    metric_inc("github_api_call_total")
    start = time.monotonic()
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
        metric_observe_latency(time.monotonic() - start)
        if result.returncode == 0:
            log.info(f"opened: {title}")
            return True
        metric_inc("github_api_fail_total")
        log.error(f"gh issue create failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        metric_observe_latency(time.monotonic() - start)
        metric_inc("github_api_fail_total")
        log.error(f"gh issue create exception: {e}")
    return False


def gh_issue_comment(num: int, body: str) -> bool:
    """Comment on existing issue. Returns True on success."""
    metric_inc("github_api_call_total")
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["gh", "issue", "comment", str(num), "--repo", GH_REPO, "--body", body],
            capture_output=True,
            text=True,
            timeout=15,
        )
        metric_observe_latency(time.monotonic() - start)
        if result.returncode == 0:
            log.info(f"commented #{num}")
            return True
        metric_inc("github_api_fail_total")
        log.error(f"gh issue comment failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        metric_observe_latency(time.monotonic() - start)
        metric_inc("github_api_fail_total")
        log.error(f"gh issue comment exception: {e}")
    return False


def gh_issue_close(num: int, reason: str = "completed") -> bool:
    """Close existing issue with reason (Codex `019e2a4f` Session 53 P0 #2 absorb —
    resolved lifecycle: send_resolved=true → issue close + final comment).
    Returns True on success.
    """
    metric_inc("github_api_call_total")
    start = time.monotonic()
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
        metric_observe_latency(time.monotonic() - start)
        if result.returncode == 0:
            log.info(f"closed #{num} (reason={reason})")
            return True
        metric_inc("github_api_fail_total")
        log.error(f"gh issue close failed: {result.stderr[:200]}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        metric_observe_latency(time.monotonic() - start)
        metric_inc("github_api_fail_total")
        log.error(f"gh issue close exception: {e}")
    return False


def log_undelivered(alert: dict[str, Any], reason: str) -> None:
    """Persist failed delivery for retry/audit.

    Codex `019e2a4f` Session 53 P0 #1 syntax fix + Session 53 P0 C absorb:
    - global UNDELIVERED_LOG declaration fonksiyon başına taşındı
    - Metric counters: undelivered_total + undelivered_by_reason
    - Bounded size guard: UNDELIVERED_MAX_BYTES (10MB default) overflow rotate
      (emptyDir storage; pod restart kayıp accepted — metric ile görünürlük).
    """
    global UNDELIVERED_LOG

    # Metric increment (her undelivered çağrısında)
    metric_inc("undelivered_total")
    metric_inc_reason(reason)
    metric_set_timestamp("last_delivery_failure_timestamp")

    try:
        log_dir = Path(UNDELIVERED_LOG).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback to /tmp
        UNDELIVERED_LOG = "/tmp/alertmanager-bridge-undelivered.jsonl"

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "alert": alert,
        "reason": reason,
    }
    try:
        # Bounded size guard: dosya UNDELIVERED_MAX_BYTES'ı aşarsa rotate
        # (emptyDir disk usage cap; pod restart kayıp accepted).
        try:
            size = Path(UNDELIVERED_LOG).stat().st_size
            if size >= UNDELIVERED_MAX_BYTES:
                rotated = f"{UNDELIVERED_LOG}.1"
                Path(UNDELIVERED_LOG).replace(rotated)
                log.warning(
                    f"undelivered log rotated (size={size} > max={UNDELIVERED_MAX_BYTES}); old → {rotated}"
                )
        except FileNotFoundError:
            pass  # ilk yazım, dosya yok

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

    BL-008-bridge — synthetic alert filter (Codex `019e6de3` AGREE B path +
    `019e6e03` REVISE iter-2 contract clarification):

    **Bridge GH Issue suppression contract** (governance-explicit):
    - Filter triggers ONLY on exact match `labels.is_synthetic == "true"`.
    - Loose aliases ("synthetic", "test", "smoke") NOT honored — risks accidentally
      swallowing a real alert that happens to mention "synthetic" in another label.
    - All synthetic-firing CronJobs (R29 monthly Teams smoke + future diagnostic
      injectors) MUST set this exact label or accept GH Issue spam.

    Behavior:
    - `is_synthetic=true` → skip GH Issue creation (no create/comment/close).
    - Synthetic alert still routes through Alertmanager to Teams (perf-alerts-teams
      receiver) for Adaptive Card receipt validation — bridge sibling route hit
      via `continue:true` but suppressed here.
    - `synthetic_skipped_total` metric increments (operator: zero-rate expected
      outside scheduled synthetic windows; spike = unexpected injection).
    """
    labels = alert.get("labels", {})
    if labels.get("is_synthetic") == "true":
        metric_inc("synthetic_skipped_total")
        log.info(
            f"synthetic alert skipped (is_synthetic=true): "
            f"alertname={labels.get('alertname', 'unknown')} "
            f"status={alert.get('status', 'unknown')}"
        )
        return True

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
            # Codex `019e2a4f` Session 53 P0 #1 P1 fix:
            # resolved comment veya close fail olursa undelivered log audit/retry için
            if not comment_ok:
                log_undelivered(alert, "resolved_comment_failed")
            if not close_ok:
                log_undelivered(alert, "resolved_close_failed")
            if comment_ok and close_ok:
                metric_inc("delivered_total")
                metric_set_timestamp("last_delivery_success_timestamp")
                return True
            return False
        # Codex `019e2a4f` Session 53 P0 C: resolved + no open issue = idempotent success
        # (zaten kapanmış; counter increment delivery sayılır).
        metric_inc("delivered_total")
        metric_set_timestamp("last_delivery_success_timestamp")
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
        comment_ok = gh_issue_comment(
            existing, f"🔥 Recurrence at `{starts_at}` (still firing)."
        )
        if comment_ok:
            metric_inc("delivered_total")
            metric_set_timestamp("last_delivery_success_timestamp")
        else:
            log_undelivered(alert, "firing_recurrence_comment_failed")
        return comment_ok

    delivered = gh_issue_create(title, body, issue_labels)
    if delivered:
        metric_inc("delivered_total")
        metric_set_timestamp("last_delivery_success_timestamp")
    else:
        log_undelivered(alert, "gh_issue_create_failed")
    return delivered


# ---------------------------------------------------------------------------
# #3888 — Operator paging: SMS (JetSMS SOAP) + email (Microsoft Graph sendMail)
#
# The GitHub-issue path above is an audit trail, not a pager: on 2026-10-15 a
# host reboot took k3d-test down for 6 days and 27 alerts fired with nobody
# notified (GH token absent, SMTP fallback password expired). This section
# pages a human directly. It deliberately does NOT go through
# notification-orchestrator (same D43 bypass principle as direct-fallback):
# a notify outage must still page.
#
# One SMS and one email per Alertmanager webhook group (not per alert) keeps
# volume proportional to incidents. SMS only for page="sms" crisis alerts
# (platform-crisis rules) and capped per hour; email only for critical;
# email is never capped. Missing config → channel skipped and exported as
# alertmanager_bridge_notify_channel_configured=0 (rule-backed sentinel).
# ---------------------------------------------------------------------------

SEVERITY_RANK = {"critical": 3, "warning": 2, "info": 1}
_TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_SMS_SENT_AT: collections.deque = collections.deque()
_NOTIFY_LOCK = threading.Lock()
_GRAPH_TOKEN: dict[str, Any] = {"value": "", "expires_at": 0.0}


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def notify_channels_configured() -> dict[str, bool]:
    sms = all(os.environ.get(k, "") for k in ("JETSMS_USERNAME", "JETSMS_PASSWORD", "JETSMS_ORIGINATOR")) \
        and bool(_env_list("ALERT_SMS_TO", ""))
    email = all(os.environ.get(k, "") for k in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")) \
        and bool(_env_list("ALERT_EMAIL_TO", "")) and bool(os.environ.get("GRAPH_SENDER_MAILBOX", ""))
    return {"sms": sms, "email": email}


def _notify_inc(bucket: str, channel: str) -> None:
    _METRICS[bucket][channel] = _METRICS[bucket].get(channel, 0) + 1


def _group_severity(alerts: list[dict[str, Any]]) -> str:
    best = "info"
    for a in alerts:
        sev = a.get("labels", {}).get("severity", "warning").lower()
        if SEVERITY_RANK.get(sev, 0) > SEVERITY_RANK.get(best, 0):
            best = sev
    return best


def build_sms_text(status: str, alerts: list[dict[str, Any]], severity: str) -> str:
    """Single-segment ASCII SMS (≤160): status, cluster, alert names, count."""
    names: list[str] = []
    for a in alerts:
        n = a.get("labels", {}).get("alertname", "?")
        if n not in names:
            names.append(n)
    clusters = sorted({a.get("labels", {}).get("cluster", "") for a in alerts} - {""})
    head = "COZULDU" if status == "resolved" else {"critical": "KRITIK", "warning": "UYARI"}.get(severity, "BILGI")
    text = f"[{head}] {'/'.join(clusters) or 'platform'} {len(alerts)} alarm: {', '.join(names)}"
    text = text.translate(_TR_ASCII)
    text = text.encode("ascii", "replace").decode("ascii")
    return text if len(text) <= 160 else text[:157] + "..."


def build_email(status: str, alerts: list[dict[str, Any]], severity: str) -> tuple[str, str]:
    names = sorted({a.get("labels", {}).get("alertname", "?") for a in alerts})
    clusters = sorted({a.get("labels", {}).get("cluster", "") for a in alerts} - {""})
    head = "ÇÖZÜLDÜ" if status == "resolved" else {"critical": "KRİTİK", "warning": "UYARI"}.get(severity, "BİLGİ")
    subject = f"[{head}] {'/'.join(clusters) or 'platform'}: {', '.join(names)}"[:200]
    lines = [f"Durum: {status}  |  Önem: {severity}  |  Alarm sayısı: {len(alerts)}", ""]
    for a in alerts:
        lab = a.get("labels", {})
        ann = a.get("annotations", {})
        lines.append(f"• {lab.get('alertname', '?')} ({lab.get('severity', '?')})")
        for k in ("cluster", "namespace", "pod", "deployment", "job", "instance", "name"):
            if lab.get(k):
                lines.append(f"    {k}: {lab[k]}")
        for k in ("summary", "description"):
            if ann.get(k):
                lines.append(f"    {k}: {ann[k]}")
        lines.append(f"    başladı: {a.get('startsAt', '?')}")
        if a.get("status") == "resolved":
            lines.append(f"    bitti: {a.get('endsAt', '?')}")
        if a.get("generatorURL"):
            lines.append(f"    kaynak: {a['generatorURL']}")
        lines.append("")
    lines.append("— alertmanager-bridge (#3888)")
    return subject, "\n".join(lines)


def _http(req: urllib.request.Request, timeout: float = 15.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https endpoints)
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def send_sms(phone: str, text: str) -> bool:
    """JetSMS SOAP SendSMSSingle (same contract as notification-orchestrator JetSmsProvider)."""
    to = phone[1:] if phone.startswith("+") else phone
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        '<SendSMSSingle xmlns="http://tempuri.org/">'
        f"<user>{xml_escape(os.environ['JETSMS_USERNAME'])}</user>"
        f"<password>{xml_escape(os.environ['JETSMS_PASSWORD'])}</password>"
        f"<originator>{xml_escape(os.environ['JETSMS_ORIGINATOR'])}</originator>"
        "<reference></reference><startdate></startdate><expiredate></expiredate>"
        f"<messages>{xml_escape(text)}</messages><receipents>{xml_escape(to)}</receipents>"
        "<exclusionstarttime></exclusionstarttime><exclusionexpiretime></exclusionexpiretime>"
        f"<channel>{xml_escape(os.environ.get('JETSMS_CHANNEL', 'VF'))}</channel>"
        "<blacklistfilter></blacklistfilter><optinfilter></optinfilter><x></x>"
        "<onlengthproblem>SendAllPackage</onlengthproblem>"
        "</SendSMSSingle></soap:Body></soap:Envelope>"
    )
    req = urllib.request.Request(
        os.environ.get("JETSMS_SOAP_URL", "https://api.jetsms.com.tr/ws/soapSMS.asmx"),
        data=envelope.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://tempuri.org/SendSMSSingle"'},
        method="POST",
    )
    try:
        code, body = _http(req)
    except (urllib.error.URLError, OSError) as e:
        log.error(f"sms send transport error: {type(e).__name__}")
        return False
    error_code = ""
    start = body.find("ErrorCode>")
    if start != -1:
        error_code = body[start + len("ErrorCode>"):].split("<", 1)[0].strip()
    if code == 200 and error_code.startswith("00"):
        return True
    log.error(f"sms send rejected: http={code} errorCode={error_code or 'none'}")
    return False


def _graph_token() -> str:
    if _GRAPH_TOKEN["value"] and time.time() < _GRAPH_TOKEN["expires_at"] - 60:
        return _GRAPH_TOKEN["value"]
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["GRAPH_CLIENT_ID"],
        "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}/oauth2/v2.0/token",
        data=data, method="POST",
    )
    code, body = _http(req)
    if code != 200:
        raise RuntimeError(f"graph token http={code}")
    tok = json.loads(body)
    _GRAPH_TOKEN["value"] = tok["access_token"]
    _GRAPH_TOKEN["expires_at"] = time.time() + int(tok.get("expires_in", 3000))
    return _GRAPH_TOKEN["value"]


def send_email(recipients: list[str], subject: str, text: str) -> bool:
    sender = os.environ["GRAPH_SENDER_MAILBOX"]
    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": text},
            "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
        },
        "saveToSentItems": True,
    }
    try:
        token = _graph_token()
        req = urllib.request.Request(
            f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(sender)}/sendMail",
            data=json.dumps(message).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        code, body = _http(req)
    except (urllib.error.URLError, OSError, RuntimeError, KeyError, ValueError) as e:
        log.error(f"email send error: {type(e).__name__}: {str(e)[:120]}")
        return False
    if code == 202:
        return True
    log.error(f"email send rejected: http={code} body={body[:200]}")
    return False


def _sms_allowed(now: float) -> bool:
    cap = int(os.environ.get("ALERT_SMS_MAX_PER_HOUR", "12"))
    while _SMS_SENT_AT and now - _SMS_SENT_AT[0] > 3600:
        _SMS_SENT_AT.popleft()
    return len(_SMS_SENT_AT) < cap


def notify_group(payload: dict[str, Any]) -> dict[str, int]:
    """Page operators for one Alertmanager webhook group. Returns per-channel sent counts."""
    alerts = [a for a in payload.get("alerts", []) if a.get("labels", {}).get("is_synthetic") != "true"]
    result = {"sms": 0, "email": 0}
    if not alerts:
        return result
    status = payload.get("status", "firing")
    severity = _group_severity(alerts)
    configured = notify_channels_configured()
    with _NOTIFY_LOCK:
        # Owner decision 2026-10-23: SMS only in a real crisis. Severity alone is
        # not enough (many "critical" alerts are housekeeping: token absent,
        # telemetry gaps); only alerts explicitly labelled page="sms" by the
        # platform-crisis PrometheusRule wake a human up.
        crisis = [a for a in alerts if a.get("labels", {}).get("page") == "sms"]
        if configured["sms"] and crisis:
            now = time.time()
            if _sms_allowed(now):
                text = build_sms_text(status, crisis, "critical")
                for phone in _env_list("ALERT_SMS_TO", ""):
                    if send_sms(phone, text):
                        _notify_inc("notify_sent_total", "sms")
                        result["sms"] += 1
                    else:
                        _notify_inc("notify_fail_total", "sms")
                _SMS_SENT_AT.append(now)
            else:
                metric_inc("notify_sms_ratelimited_total")
                log.warning("sms hourly cap reached; email only for this group")
        if configured["email"] and severity in _env_list("ALERT_EMAIL_SEVERITIES", "critical"):
            subject, text = build_email(status, alerts, severity)
            if send_email(_env_list("ALERT_EMAIL_TO", ""), subject, text):
                _notify_inc("notify_sent_total", "email")
                result["email"] += 1
            else:
                _notify_inc("notify_fail_total", "email")
    log.info(f"notify group status={status} severity={severity} alerts={len(alerts)} sent={result}")
    return result


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
        # Codex `019e2a4f` Session 53 P0 C: Prometheus /metrics endpoint
        # (stdlib pure, prometheus_client dep yok). ServiceMonitor scrape hedef.
        if self.path == "/metrics":
            payload = render_metrics()
            self.send_response(200)
            # Prometheus text exposition format v0.0.4
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
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
        # Codex `019e2a4f` Session 53 P0 C: webhook_received_total counter
        metric_inc("webhook_received_total")
        log.info(f"received {len(alerts)} alert(s) from group {group_labels}")

        # #3888 — page operators off the request thread so slow SMS/Graph calls
        # never delay the Alertmanager webhook acknowledgement.
        threading.Thread(target=notify_group, args=(payload,), daemon=True).start()

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
    log.info(f"alertmanager-bridge starting on :{PORT} (repo={GH_REPO}) notify_channels={notify_channels_configured()}")
    server = HTTPServer(("0.0.0.0", PORT), AlertHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
