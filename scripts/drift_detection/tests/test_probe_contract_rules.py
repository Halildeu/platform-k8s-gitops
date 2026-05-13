"""Unit tests for lib.probe_contract_rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.probe_contract_rules import (  # noqa: E402
    EXEMPT_CONTRACT,
    PROBE_CONTRACTS,
    get_rule,
    known_contracts,
)


class TestProbeContractRules(unittest.TestCase):
    def test_known_contracts_include_exempt(self):
        self.assertIn(EXEMPT_CONTRACT, known_contracts())
        self.assertIn("spring-actuator", known_contracts())
        self.assertIn("http-healthz", known_contracts())

    def test_spring_actuator_startup_required(self):
        rule = get_rule("spring-actuator")
        self.assertIsNotNone(rule)
        self.assertTrue(rule.startup_required)
        self.assertIn("/actuator/health/liveness", rule.liveness_paths)
        self.assertIn("/actuator/health/readiness", rule.readiness_paths)
        # management port accepted by name or 8081 (named/numeric)
        self.assertIn("management", rule.port_values)
        self.assertIn(8081, rule.port_values)

    def test_http_healthz_path_only(self):
        rule = get_rule("http-healthz")
        self.assertIsNotNone(rule)
        self.assertFalse(rule.startup_required)
        self.assertIn("/healthz", rule.liveness_paths)
        # path-not-port-bound — port_values empty
        self.assertEqual(rule.port_values, ())

    def test_exempt_has_no_rule(self):
        self.assertIsNone(get_rule(EXEMPT_CONTRACT))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
