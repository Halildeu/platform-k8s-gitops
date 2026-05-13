"""Unit tests for lib.deploy_normalizer.

Codex 019e2319 iter-3 AGREE — stdlib unittest (no pytest dep on CI runner).
Validates the endpoint-admin probe drift detection that motivated this gate
(2026-05-13 16h silent CrashLoopBackOff).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Make sibling lib importable
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.deploy_normalizer import (  # noqa: E402
    _normalize_env_list,
    _normalize_probe,
    assert_probe_contract,
    semantic_diff,
    template_contract_view,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestProbeNormalize(unittest.TestCase):
    def test_defaults_injected(self):
        normalized = _normalize_probe(
            {"httpGet": {"path": "/healthz", "port": "http"}}
        )
        self.assertEqual(normalized["periodSeconds"], 10)
        self.assertEqual(normalized["timeoutSeconds"], 1)
        self.assertEqual(normalized["successThreshold"], 1)
        self.assertEqual(normalized["failureThreshold"], 3)
        self.assertEqual(normalized["initialDelaySeconds"], 0)
        self.assertEqual(normalized["httpGet"]["scheme"], "HTTP")

    def test_explicit_value_wins(self):
        normalized = _normalize_probe(
            {"httpGet": {"path": "/x"}, "periodSeconds": 15}
        )
        self.assertEqual(normalized["periodSeconds"], 15)

    def test_none_input_returns_none(self):
        self.assertIsNone(_normalize_probe(None))


class TestEnvNormalize(unittest.TestCase):
    def test_sorted_by_name(self):
        env = [
            {"name": "BBB", "value": "2"},
            {"name": "AAA", "value": "1"},
        ]
        self.assertEqual(
            [e["name"] for e in _normalize_env_list(env)], ["AAA", "BBB"]
        )

    def test_duplicate_raises(self):
        with self.assertRaises(ValueError):
            _normalize_env_list(
                [
                    {"name": "FOO", "value": "1"},
                    {"name": "FOO", "value": "2"},
                ]
            )


class TestSemanticDiff(unittest.TestCase):
    def test_clean_deployment_no_diff_against_itself(self):
        api_gw = _load("api_gateway_clean.json")
        self.assertEqual(semantic_diff(api_gw, api_gw), [])

    def test_endpoint_admin_probe_drift_detected(self):
        desired = _load("endpoint_admin_desired_render.json")
        drifted = _load("endpoint_admin_drifted_live.json")
        diffs = semantic_diff(desired, drifted)
        paths = [d[0] for d in diffs]

        # The 16h silent CrashLoop fingerprint: probe paths + startupProbe drift
        self.assertTrue(
            any("livenessProbe.httpGet.path" in p for p in paths),
            f"expected livenessProbe path drift; got {paths}",
        )
        self.assertTrue(
            any("readinessProbe.httpGet.path" in p for p in paths),
            f"expected readinessProbe path drift; got {paths}",
        )
        self.assertTrue(
            any("startupProbe" in p for p in paths),
            f"expected startupProbe drift; got {paths}",
        )

    def test_empty_dict_equivalent_to_null(self):
        a = {"spec": {"template": {"metadata": {"labels": {}}, "spec": {}}}}
        b = {"spec": {"template": {"metadata": {}, "spec": {}}}}
        self.assertEqual(semantic_diff(a, b), [])


class TestProbeContractAssertion(unittest.TestCase):
    def test_spring_actuator_clean_no_findings(self):
        api_gw = _load("api_gateway_clean.json")
        self.assertEqual(
            assert_probe_contract(api_gw, "spring-actuator", "api-gateway"),
            [],
        )

    def test_spring_actuator_missing_startup_probe(self):
        drifted = _load("endpoint_admin_drifted_live.json")
        findings = assert_probe_contract(
            drifted, "spring-actuator", "endpoint-admin-service"
        )
        kinds = [f["kind"] for f in findings]
        self.assertIn("missing_startup_probe", kinds)

    def test_spring_actuator_path_violation_endpoint_admin(self):
        drifted = _load("endpoint_admin_drifted_live.json")
        findings = assert_probe_contract(
            drifted, "spring-actuator", "endpoint-admin-service"
        )
        path_violations = [f for f in findings if f["kind"] == "probe_path_violation"]
        self.assertGreaterEqual(len(path_violations), 2)
        # /healthz/live and /healthz/ready violations
        joined = " ".join(f["message"] for f in path_violations)
        self.assertIn("/healthz/live", joined)
        self.assertIn("/healthz/ready", joined)

    def test_exempt_contract_skips(self):
        any_deploy = _load("endpoint_admin_drifted_live.json")
        self.assertEqual(
            assert_probe_contract(any_deploy, "exempt", "endpoint-admin-service"),
            [],
        )


class TestContractView(unittest.TestCase):
    def test_image_excluded_from_view(self):
        api_gw = _load("api_gateway_clean.json")
        view = template_contract_view(api_gw)
        container_view = view["containers"]["api-gateway"]
        self.assertNotIn("image", container_view)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
