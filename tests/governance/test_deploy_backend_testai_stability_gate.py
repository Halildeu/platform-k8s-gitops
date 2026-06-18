#!/usr/bin/env python3
"""Regression checks for deploy-backend-testai Gate 1d coverage."""

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-backend-testai.yml"


class DeployBackendTestaiStabilityGateTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def _gate_1d_services(self):
        match = re.search(
            r"- name: Gate 1d .*?\n\s+run: \|\n(?P<body>.*?)(?:\n\s+# Gate 2|\Z)",
            self.workflow,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Gate 1d step not found")
        body = match.group("body")
        return re.findall(r'"([a-z0-9-]+)"', body)

    def test_endpoint_admin_is_in_stability_window(self):
        services = self._gate_1d_services()
        self.assertIn("endpoint-admin-service", services)

    def test_stability_window_budget_comment_matches_service_count(self):
        services = self._gate_1d_services()
        self.assertEqual(9, len(services), services)
        self.assertIn("20 min budget", self.workflow)
        self.assertIn("rollout (9 * 180s = 27m max)", self.workflow)


if __name__ == "__main__":
    unittest.main()
