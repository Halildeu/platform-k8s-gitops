#!/usr/bin/env python3
"""Regression checks for backend post-merge stability coverage."""

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-testai-backend-rollout.yml"
RUNTIME = REPO_ROOT / "scripts" / "deploy" / "verify-testai-backend-runtime.sh"


class DeployBackendTestaiStabilityGateTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.runtime = RUNTIME.read_text(encoding="utf-8")

    def _gate_1d_services(self):
        match = re.search(r"SERVICE_SPECS=\(\n(?P<body>.*?)\n\)", self.runtime, re.DOTALL)
        self.assertIsNotNone(match, "runtime SERVICE_SPECS not found")
        return [item.split("|")[1] for item in re.findall(r'"([^"]+)"', match.group("body"))]

    def test_endpoint_admin_is_in_stability_window(self):
        services = self._gate_1d_services()
        self.assertIn("endpoint-admin-service", services)

    def test_stability_window_budget_comment_matches_service_count(self):
        services = self._gate_1d_services()
        self.assertEqual(13, len(services), services)
        self.assertIn("audio-gateway", services)
        self.assertIn("meeting-service", services)
        self.assertIn("transcript-service", services)
        self.assertIn("audit-event-consumer-service", services)
        self.assertIn("timeout-minutes: 60", self.workflow)
        self.assertIn("gate-stability-window.sh", self.runtime)

    def test_faz24_runtime_rollout_mappings_are_explicit(self):
        self.assertIn(
            '"audio-gateway-service|audio-gateway"',
            self.runtime,
        )
        self.assertIn(
            '"meeting-service|meeting-service"',
            self.runtime,
        )
        self.assertIn(
            '"transcript-service|transcript-service"',
            self.runtime,
        )
        self.assertIn(
            '"audit-event-consumer-service|audit-event-consumer-service"',
            self.runtime,
        )


if __name__ == "__main__":
    unittest.main()
