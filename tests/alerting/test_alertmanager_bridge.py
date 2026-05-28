"""
tests/alerting/test_alertmanager_bridge.py

Session 53 P0 #5 — alertmanager-bridge unit tests (Codex `019e2a4f` consensus).

Test scope:
- severity_to_class (P1/P2/P3 mapping)
- make_issue_title (PMD DoD §2.4(d) dedupe key — 5 scenario)
- make_issue_body (markdown render)
- process_alert lifecycle (firing new, firing existing, resolved existing, resolved missing)
- log_undelivered (Path fallback, write error)
- gh_issue_search/create/comment/close (mocked subprocess)

Run:
    pytest tests/alerting/test_alertmanager_bridge.py -v
veya stdlib:
    python3 -m unittest tests.alerting.test_alertmanager_bridge -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# Load alertmanager-bridge.py module (hyphenated filename → importlib spec)
BRIDGE_PATH = Path(__file__).resolve().parents[2] / "kustomize" / "base" / "monitoring" / "alertmanager-bridge" / "alertmanager-bridge.py"

spec = importlib.util.spec_from_file_location("alertmanager_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
sys.modules["alertmanager_bridge"] = bridge
spec.loader.exec_module(bridge)


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestSeverityMapping(unittest.TestCase):
    """severity → P1/P2/P3 class mapping."""

    def test_critical_to_p1(self):
        self.assertEqual(bridge.severity_to_class("critical"), "P1")

    def test_warning_to_p2(self):
        self.assertEqual(bridge.severity_to_class("warning"), "P2")

    def test_info_to_p3(self):
        self.assertEqual(bridge.severity_to_class("info"), "P3")

    def test_unknown_to_p2_default(self):
        self.assertEqual(bridge.severity_to_class("unknown"), "P2")
        self.assertEqual(bridge.severity_to_class(""), "P2")

    def test_case_insensitive(self):
        self.assertEqual(bridge.severity_to_class("CRITICAL"), "P1")
        self.assertEqual(bridge.severity_to_class("Warning"), "P2")


class TestDedupeKey(unittest.TestCase):
    """PMD DoD §2.4(d) — make_issue_title dedupe key extend.
    Format: [alertmanager-<cls>] <alertname>/<namespace>/<configmap-or-route>@<cluster>
    """

    def test_full_labels_perf(self):
        alert = {
            "labels": {
                "alertname": "PerfFederationSmokeFailing",
                "namespace": "platform-prod",
                "configmap": "frontend-federation-smoke-status",
                "cluster": "prod",
                "severity": "warning",
            }
        }
        title = bridge.make_issue_title(alert)
        self.assertEqual(
            title,
            "[alertmanager-P2] PerfFederationSmokeFailing/platform-prod/frontend-federation-smoke-status@prod",
        )

    def test_route_fallback_when_no_configmap(self):
        alert = {
            "labels": {
                "alertname": "RouteAlert",
                "namespace": "platform-test",
                "route": "/api/v1/users",
                "cluster": "test",
                "severity": "critical",
            }
        }
        title = bridge.make_issue_title(alert)
        self.assertIn("/api/v1/users", title)
        self.assertIn("@test", title)
        self.assertIn("alertmanager-P1", title)

    def test_no_cluster_omits_suffix(self):
        alert = {
            "labels": {
                "alertname": "NoClusterAlert",
                "namespace": "default",
                "severity": "info",
            }
        }
        title = bridge.make_issue_title(alert)
        self.assertEqual(title, "[alertmanager-P3] NoClusterAlert/default")
        self.assertNotIn("@", title)

    def test_minimal_alert_alertname_only(self):
        alert = {"labels": {"alertname": "MinimalAlert"}}
        title = bridge.make_issue_title(alert)
        self.assertEqual(title, "[alertmanager-P2] MinimalAlert")

    def test_empty_labels_fallback(self):
        alert = {"labels": {}}
        title = bridge.make_issue_title(alert)
        self.assertEqual(title, "[alertmanager-P2] UnknownAlert")

    def test_configmap_preferred_over_route(self):
        """Eğer hem configmap hem route varsa configmap kullanılır."""
        alert = {
            "labels": {
                "alertname": "BothLabels",
                "namespace": "ns1",
                "configmap": "cm1",
                "route": "/some/route",
                "cluster": "prod",
                "severity": "critical",
            }
        }
        title = bridge.make_issue_title(alert)
        self.assertIn("cm1", title)
        self.assertNotIn("/some/route", title)


class TestIssueBody(unittest.TestCase):
    """make_issue_body markdown structure."""

    def test_body_contains_severity_alertname_namespace(self):
        alert = {
            "labels": {
                "alertname": "TestAlert",
                "namespace": "ns",
                "severity": "warning",
                "pod": "pod-xyz",
            },
            "annotations": {
                "summary": "Test summary",
                "description": "Test description",
            },
            "startsAt": "2026-05-15T07:30:00Z",
            "generatorURL": "http://prom/...",
        }
        body = bridge.make_issue_body(alert, {})
        self.assertIn("Severity", body)
        self.assertIn("warning", body)
        self.assertIn("TestAlert", body)
        self.assertIn("ns", body)
        self.assertIn("Test summary", body)


class TestProcessAlert(unittest.TestCase):
    """process_alert lifecycle (firing/resolved with mocked gh CLI)."""

    @patch.object(bridge, "gh_issue_create")
    @patch.object(bridge, "gh_issue_search_open")
    def test_firing_new_creates_issue(self, mock_search, mock_create):
        mock_search.return_value = None  # no existing
        mock_create.return_value = True

        alert = load_fixture("alertmanager-firing-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})

        self.assertTrue(result)
        mock_create.assert_called_once()
        mock_search.assert_called_once()

    @patch.object(bridge, "gh_issue_comment")
    @patch.object(bridge, "gh_issue_search_open")
    def test_firing_existing_comments(self, mock_search, mock_comment):
        mock_search.return_value = 123  # existing issue
        mock_comment.return_value = True

        alert = load_fixture("alertmanager-firing-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})

        self.assertTrue(result)
        mock_comment.assert_called_once()
        # Recurrence comment check
        args = mock_comment.call_args
        self.assertEqual(args[0][0], 123)
        self.assertIn("Recurrence", args[0][1])

    @patch.object(bridge, "gh_issue_close")
    @patch.object(bridge, "gh_issue_comment")
    @patch.object(bridge, "gh_issue_search_open")
    def test_resolved_existing_comments_and_closes(self, mock_search, mock_comment, mock_close):
        mock_search.return_value = 456
        mock_comment.return_value = True
        mock_close.return_value = True

        alert = load_fixture("alertmanager-resolved-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})

        self.assertTrue(result)
        mock_comment.assert_called_once()
        mock_close.assert_called_once_with(456, reason="completed")

    @patch.object(bridge, "gh_issue_search_open")
    def test_resolved_missing_noop(self, mock_search):
        mock_search.return_value = None  # already closed
        alert = load_fixture("alertmanager-resolved-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})
        self.assertTrue(result)
        mock_search.assert_called_once()

    @patch.object(bridge, "log_undelivered")
    @patch.object(bridge, "gh_issue_close")
    @patch.object(bridge, "gh_issue_comment")
    @patch.object(bridge, "gh_issue_search_open")
    def test_resolved_close_failure_logs_undelivered(
        self, mock_search, mock_comment, mock_close, mock_log
    ):
        """Codex 019e2a4f P1 fix: close fail → log_undelivered."""
        mock_search.return_value = 789
        mock_comment.return_value = True
        mock_close.return_value = False  # close fails

        alert = load_fixture("alertmanager-resolved-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})

        self.assertFalse(result)
        mock_log.assert_called_with(alert, "resolved_close_failed")

    @patch.object(bridge, "log_undelivered")
    @patch.object(bridge, "gh_issue_create")
    @patch.object(bridge, "gh_issue_search_open")
    def test_firing_create_failure_logs_undelivered(
        self, mock_search, mock_create, mock_log
    ):
        mock_search.return_value = None
        mock_create.return_value = False  # create fails

        alert = load_fixture("alertmanager-firing-perf.json")["alerts"][0]
        result = bridge.process_alert(alert, {})

        self.assertFalse(result)
        mock_log.assert_called_with(alert, "gh_issue_create_failed")


class TestUndeliveredLog(unittest.TestCase):
    """log_undelivered Path fallback + write."""

    def test_log_write_to_writable_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "undelivered.jsonl"
            with patch.object(bridge, "UNDELIVERED_LOG", str(log_path)):
                bridge.log_undelivered({"labels": {"alertname": "X"}}, "test_reason")
                self.assertTrue(log_path.exists())
                content = log_path.read_text()
                self.assertIn("test_reason", content)
                self.assertIn("alertname", content)

    def test_log_fallback_to_tmp_on_oserror(self):
        """Path mkdir OSError → fallback /tmp."""
        # Force /nonexistent/path → OSError → fallback
        with patch.object(bridge, "UNDELIVERED_LOG", "/nonexistent/read-only/log.jsonl"):
            # No assert on file (would write to /tmp/...), just ensure no exception
            try:
                bridge.log_undelivered({"labels": {"alertname": "Y"}}, "fallback")
            except Exception as e:
                self.fail(f"log_undelivered raised exception: {e}")


class TestWebhookHandlerSmoke(unittest.TestCase):
    """do_POST /alert webhook payload parse (no actual server start)."""

    def test_parse_fixture_alertmanager_v4_firing(self):
        """Verify fixture payload parse round-trips through json."""
        payload = load_fixture("alertmanager-firing-perf.json")
        self.assertEqual(payload["status"], "firing")
        self.assertEqual(len(payload["alerts"]), 1)
        self.assertEqual(payload["alerts"][0]["labels"]["alertname"], "PerfFederationSmokeFailing")

    def test_parse_fixture_alertmanager_v4_resolved(self):
        payload = load_fixture("alertmanager-resolved-perf.json")
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["alerts"][0]["status"], "resolved")


class TestMetricsExposition(unittest.TestCase):
    """Session 53 P0 C — Prometheus /metrics endpoint (stdlib pure)."""

    def setUp(self):
        # Reset metric state between tests (module-level dict isolation)
        bridge._METRICS["delivered_total"] = 0
        bridge._METRICS["undelivered_total"] = 0
        bridge._METRICS["undelivered_by_reason"] = {}
        bridge._METRICS["github_api_call_total"] = 0
        bridge._METRICS["github_api_fail_total"] = 0
        bridge._METRICS["github_api_latency_seconds_sum"] = 0.0
        bridge._METRICS["github_api_latency_seconds_count"] = 0
        bridge._METRICS["last_delivery_success_timestamp"] = 0
        bridge._METRICS["last_delivery_failure_timestamp"] = 0
        bridge._METRICS["webhook_received_total"] = 0

    def test_metric_inc_counter(self):
        bridge.metric_inc("delivered_total")
        bridge.metric_inc("delivered_total", 5)
        self.assertEqual(bridge._METRICS["delivered_total"], 6)

    def test_metric_inc_reason_label(self):
        bridge.metric_inc_reason("gh_auth_fail")
        bridge.metric_inc_reason("gh_auth_fail")
        bridge.metric_inc_reason("network_error")
        self.assertEqual(bridge._METRICS["undelivered_by_reason"]["gh_auth_fail"], 2)
        self.assertEqual(bridge._METRICS["undelivered_by_reason"]["network_error"], 1)

    def test_metric_observe_latency(self):
        bridge.metric_observe_latency(0.5)
        bridge.metric_observe_latency(1.2)
        self.assertAlmostEqual(bridge._METRICS["github_api_latency_seconds_sum"], 1.7, places=2)
        self.assertEqual(bridge._METRICS["github_api_latency_seconds_count"], 2)

    def test_metric_set_timestamp(self):
        import time as _t
        bridge.metric_set_timestamp("last_delivery_success_timestamp")
        # Timestamp non-zero (recent)
        self.assertGreater(bridge._METRICS["last_delivery_success_timestamp"], 0)
        self.assertAlmostEqual(
            bridge._METRICS["last_delivery_success_timestamp"], int(_t.time()), delta=2
        )

    def _reexec_bridge_module(self):
        """Re-execute the bridge module so module-level _METRICS dict
        re-initializes from the current env state. Module loaded via
        spec_from_file_location (hyphenated filename) — importlib.reload
        cannot find a parent package, so we re-run the loader directly.
        """
        spec.loader.exec_module(bridge)

    def test_github_token_configured_gauge_when_token_set(self):
        """Codex `019e6fb5` iter-2 nice_to_have absorb — startup gauge metric.

        github_token_configured == 1 when GITHUB_TOKEN env non-empty at the
        point process samples it.
        """
        os.environ["GITHUB_TOKEN"] = "ghp_fake_token_for_test_only_xxx"
        try:
            self._reexec_bridge_module()
            self.assertEqual(bridge._METRICS["github_token_configured"], 1)
            payload = bridge.render_metrics().decode("utf-8")
            self.assertIn("alertmanager_bridge_github_token_configured 1", payload)
            self.assertIn(
                "# TYPE alertmanager_bridge_github_token_configured gauge",
                payload,
            )
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            self._reexec_bridge_module()  # restore env-free baseline

    def test_github_token_configured_gauge_when_token_missing(self):
        """Auth-drift sentinel: gauge == 0 when GITHUB_TOKEN unset/empty.

        This is the case PrometheusRule AlertmanagerBridgeGHSecretAbsent fires
        on. Test guarantees the sentinel actually goes to 0 (not silently
        defaulting to 1 because of a missed init path).
        """
        os.environ.pop("GITHUB_TOKEN", None)
        self._reexec_bridge_module()
        self.assertEqual(bridge._METRICS["github_token_configured"], 0)
        payload = bridge.render_metrics().decode("utf-8")
        self.assertIn("alertmanager_bridge_github_token_configured 0", payload)

    def test_render_metrics_exposition_format(self):
        """Prometheus text format v0.0.4 expected lines."""
        bridge.metric_inc("delivered_total", 42)
        bridge.metric_inc("undelivered_total", 3)
        bridge.metric_inc_reason("gh_auth_fail")
        bridge.metric_observe_latency(0.5)
        bridge.metric_set_timestamp("last_delivery_success_timestamp", 1700000000)

        out = bridge.render_metrics().decode("utf-8")

        # HELP + TYPE + value lines
        self.assertIn("# HELP alertmanager_bridge_delivered_total", out)
        self.assertIn("# TYPE alertmanager_bridge_delivered_total counter", out)
        self.assertIn("alertmanager_bridge_delivered_total 42", out)

        self.assertIn("# HELP alertmanager_bridge_undelivered_total", out)
        self.assertIn("alertmanager_bridge_undelivered_total 3", out)

        # Label cardinality
        self.assertIn('alertmanager_bridge_undelivered_by_reason_total{reason="gh_auth_fail"} 1', out)

        # Summary (sum + count)
        self.assertIn("alertmanager_bridge_github_api_latency_seconds_sum", out)
        self.assertIn("alertmanager_bridge_github_api_latency_seconds_count 1", out)

        # Gauge
        self.assertIn("alertmanager_bridge_last_delivery_success_timestamp_seconds 1700000000", out)

    def test_render_metrics_empty_state_valid(self):
        """Empty counters render valid Prometheus text format."""
        out = bridge.render_metrics().decode("utf-8")
        self.assertIn("alertmanager_bridge_delivered_total 0", out)
        self.assertIn("alertmanager_bridge_webhook_received_total 0", out)
        # Format: trailing newline + line-per-metric
        self.assertTrue(out.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
