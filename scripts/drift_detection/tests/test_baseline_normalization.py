"""Unit tests for Codex 019e234e baseline cleanup normalizer fixes.

Two false-positive classes surfaced by the runtime detector on 2026-05-14
after PR #551 merged:

  1. terminationGracePeriodSeconds — Kubernetes injects 30 when omitted;
     desired (None) vs live (30) produced spurious drift on every backend
     Deployment that didn't pin the field.

  2. resources.{requests,limits}.cpu/memory — Kubernetes stores these as
     canonical quantities; cpu "1" == "1000m", memory "1Gi" == "1024Mi".
     String compare flagged them as drift on api-gateway (overlay used
     "1000m", live serialized "1").

Both classes belong in the normalizer, not in apply-gap remediation:
they are NOT real drift, just serialization differences.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.deploy_normalizer import (  # noqa: E402
    _normalize_resources,
    _parse_cpu_to_millicores,
    _parse_memory_to_bytes,
    semantic_diff,
    template_contract_view,
)


# --- CPU quantity parsing ---


class TestCpuQuantityParsing(unittest.TestCase):
    def test_integer_to_millicores(self):
        self.assertEqual(_parse_cpu_to_millicores("1"), 1000)

    def test_millicore_string(self):
        self.assertEqual(_parse_cpu_to_millicores("1000m"), 1000)

    def test_fractional_to_millicores(self):
        self.assertEqual(_parse_cpu_to_millicores("0.5"), 500)

    def test_quarter_core(self):
        self.assertEqual(_parse_cpu_to_millicores("250m"), 250)

    def test_one_and_a_half(self):
        self.assertEqual(_parse_cpu_to_millicores("1.5"), 1500)

    def test_none_returns_none(self):
        self.assertIsNone(_parse_cpu_to_millicores(None))

    def test_canonical_equality_one_vs_thousand_m(self):
        self.assertEqual(
            _parse_cpu_to_millicores("1"),
            _parse_cpu_to_millicores("1000m"),
        )


# --- Memory quantity parsing ---


class TestMemoryQuantityParsing(unittest.TestCase):
    def test_gibibyte_to_bytes(self):
        self.assertEqual(_parse_memory_to_bytes("1Gi"), 1024 ** 3)

    def test_mebibyte_equivalence_to_gibibyte(self):
        self.assertEqual(
            _parse_memory_to_bytes("1Gi"),
            _parse_memory_to_bytes("1024Mi"),
        )

    def test_decimal_megabyte(self):
        self.assertEqual(_parse_memory_to_bytes("500M"), 500_000_000)

    def test_kibibyte(self):
        self.assertEqual(_parse_memory_to_bytes("100Ki"), 102_400)

    def test_none_returns_none(self):
        self.assertIsNone(_parse_memory_to_bytes(None))

    def test_decimal_gigabyte_vs_binary(self):
        # 1G (decimal) is NOT equal to 1Gi (binary); ensure parser distinguishes
        self.assertNotEqual(
            _parse_memory_to_bytes("1G"),
            _parse_memory_to_bytes("1Gi"),
        )


# --- Resources normalization ---


class TestResourcesNormalization(unittest.TestCase):
    def test_cpu_string_int_equivalence(self):
        a = _normalize_resources({"limits": {"cpu": "1000m"}})
        b = _normalize_resources({"limits": {"cpu": "1"}})
        self.assertEqual(a, b)

    def test_memory_unit_equivalence(self):
        a = _normalize_resources({"requests": {"memory": "1Gi"}})
        b = _normalize_resources({"requests": {"memory": "1024Mi"}})
        self.assertEqual(a, b)

    def test_full_section_round_trip(self):
        original = {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        }
        normalized = _normalize_resources(original)
        self.assertEqual(normalized["requests"]["cpu"], 100)
        self.assertEqual(normalized["requests"]["memory"], 128 * 1024 ** 2)
        self.assertEqual(normalized["limits"]["cpu"], 1000)
        self.assertEqual(normalized["limits"]["memory"], 1024 ** 3)

    def test_empty_input_returns_empty(self):
        self.assertEqual(_normalize_resources(None), {})
        self.assertEqual(_normalize_resources({}), {})


# --- terminationGracePeriodSeconds default injection ---


class TestTerminationGracePeriodDefault(unittest.TestCase):
    def _deploy(self, tgp=None):
        spec: dict = {"containers": [{"name": "x"}]}
        if tgp is not None:
            spec["terminationGracePeriodSeconds"] = tgp
        return {"spec": {"template": {"metadata": {}, "spec": spec}}}

    def test_missing_field_normalized_to_30(self):
        view = template_contract_view(self._deploy(tgp=None))
        self.assertEqual(view["terminationGracePeriodSeconds"], 30)

    def test_explicit_30_kept(self):
        view = template_contract_view(self._deploy(tgp=30))
        self.assertEqual(view["terminationGracePeriodSeconds"], 30)

    def test_explicit_60_kept(self):
        view = template_contract_view(self._deploy(tgp=60))
        self.assertEqual(view["terminationGracePeriodSeconds"], 60)

    def test_missing_vs_explicit_30_no_drift(self):
        a = self._deploy(tgp=None)  # overlay omits field
        b = self._deploy(tgp=30)    # live serialized with default
        self.assertEqual(semantic_diff(a, b), [])


# --- End-to-end semantic diff with normalizer fixes ---


class TestSemanticDiffBaselineCleanup(unittest.TestCase):
    def _deploy_with_resources(self, cpu_limit: str) -> dict:
        return {
            "spec": {
                "template": {
                    "metadata": {},
                    "spec": {
                        "containers": [
                            {
                                "name": "api-gateway",
                                "resources": {
                                    "requests": {"cpu": "200m", "memory": "256Mi"},
                                    "limits": {"cpu": cpu_limit, "memory": "1Gi"},
                                },
                            }
                        ],
                    },
                }
            }
        }

    def test_api_gateway_cpu_one_vs_thousand_m_no_drift(self):
        """The api-gateway runtime drift fingerprint: overlay "1000m" vs live "1"."""
        desired = self._deploy_with_resources("1000m")
        live = self._deploy_with_resources("1")
        self.assertEqual(semantic_diff(desired, live), [])

    def test_memory_unit_equivalence_no_drift(self):
        desired = copy.deepcopy(self._deploy_with_resources("1"))
        live = copy.deepcopy(self._deploy_with_resources("1"))
        # Same workload, different memory unit serialization
        desired["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] = "1Gi"
        live["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] = "1024Mi"
        self.assertEqual(semantic_diff(desired, live), [])

    def test_real_cpu_drift_still_detected(self):
        desired = self._deploy_with_resources("1000m")
        # Live actually has 500m — that's real drift, NOT a unit mismatch
        live = self._deploy_with_resources("500m")
        diffs = semantic_diff(desired, live)
        self.assertTrue(
            any("cpu" in d[0] for d in diffs),
            f"expected real cpu drift; got {[d[0] for d in diffs]}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
