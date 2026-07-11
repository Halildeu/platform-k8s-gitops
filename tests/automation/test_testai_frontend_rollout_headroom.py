from __future__ import annotations

import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy/check-testai-frontend-rollout-headroom.py"
SPEC = importlib.util.spec_from_file_location("frontend_headroom", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def resources(cpu: str = "200m", memory: str = "128Mi") -> dict:
    return {
        "requests": {"cpu": "10m", "memory": "32Mi"},
        "limits": {"cpu": cpu, "memory": memory},
    }


def deployment(
    *,
    replicas: int = 1,
    max_surge: int | str = 1,
    max_unavailable: int | str = 0,
) -> dict:
    return {
        "metadata": {"name": "frontend"},
        "spec": {
            "replicas": replicas,
            "progressDeadlineSeconds": 300,
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {
                    "maxSurge": max_surge,
                    "maxUnavailable": max_unavailable,
                },
            },
            "template": {
                "spec": {"containers": [{"name": "frontend", "resources": resources()}]}
            },
        },
    }


def quotas(
    *, used_limits_cpu: str = "11", hard_limits_cpu: str = "13"
) -> tuple[dict, dict]:
    hard = {
        "requests.cpu": "6",
        "requests.memory": "12Gi",
        "limits.cpu": hard_limits_cpu,
        "limits.memory": "24Gi",
        "pods": "30",
    }
    used = {
        "requests.cpu": "2500m",
        "requests.memory": "6Gi",
        "limits.cpu": used_limits_cpu,
        "limits.memory": "12Gi",
        "pods": "25",
    }
    return (
        {"spec": {"hard": dict(hard)}},
        {"status": {"hard": dict(hard), "used": used}},
    )


class TestaiFrontendHeadroomTests(unittest.TestCase):
    def evaluate(self, deploy: dict | None = None, **quota_args) -> dict:
        desired, live = quotas(**quota_args)
        return MODULE.evaluate(deploy or deployment(), desired, live)

    def test_healthy_headroom_passes(self):
        report = self.evaluate()
        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(1, report["resolved_max_surge"])
        self.assertFalse(report["failures"])

    def test_live_usage_above_hard_fails(self):
        report = self.evaluate(used_limits_cpu="13200m")
        self.assertEqual("FAIL", report["verdict"])
        self.assertTrue(any("limits.cpu" in failure for failure in report["failures"]))

    def test_insufficient_surge_headroom_fails(self):
        report = self.evaluate(used_limits_cpu="12801m")
        self.assertEqual("FAIL", report["verdict"])
        diagnostic = next(
            item for item in report["diagnostics"] if item["metric"] == "limits.cpu"
        )
        self.assertEqual("199m", diagnostic["margin"])
        self.assertEqual("200m", diagnostic["required"])

    def test_exact_fit_is_accepted(self):
        report = self.evaluate(used_limits_cpu="12800m")
        self.assertEqual("PASS", report["verdict"])
        diagnostic = next(
            item for item in report["diagnostics"] if item["metric"] == "limits.cpu"
        )
        self.assertEqual(diagnostic["margin"], diagnostic["required"])

    def test_zero_downtime_strategy_is_mandatory(self):
        desired, live = quotas()
        with self.assertRaisesRegex(MODULE.PreflightError, "maxSurge"):
            MODULE.evaluate(deployment(max_surge=0, max_unavailable=1), desired, live)

    def test_percentage_surge_uses_kubernetes_ceiling(self):
        report = self.evaluate(
            deployment(replicas=3, max_surge="50%", max_unavailable="0%")
        )
        self.assertEqual("PASS", report["verdict"])
        self.assertEqual(2, report["resolved_max_surge"])

    def test_sidecar_init_and_overhead_use_effective_pod_peak(self):
        deploy = deployment()
        pod_spec = deploy["spec"]["template"]["spec"]
        pod_spec["containers"] = [
            {"name": "app", "resources": resources(cpu="100m")},
            {"name": "proxy", "resources": resources(cpu="50m")},
        ]
        pod_spec["initContainers"] = [
            {
                "name": "restartable-sidecar",
                "restartPolicy": "Always",
                "resources": resources(cpu="25m"),
            },
            {"name": "migration", "resources": resources(cpu="400m")},
        ]
        pod_spec["overhead"] = {"cpu": "10m", "memory": "1Mi"}

        effective = MODULE.effective_pod_resources(deploy)
        self.assertEqual(Decimal("0.435"), effective["limits.cpu"])
        self.assertEqual(Decimal(385 * 1024 * 1024), effective["limits.memory"])

    def test_missing_explicit_resources_fail_closed(self):
        deploy = deployment()
        del deploy["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"][
            "cpu"
        ]
        desired, live = quotas()
        with self.assertRaisesRegex(MODULE.PreflightError, "explicit limits.cpu"):
            MODULE.evaluate(deploy, desired, live)

    def test_missing_live_quota_metric_fails_closed(self):
        desired, live = quotas()
        del live["status"]["used"]["pods"]
        with self.assertRaisesRegex(MODULE.PreflightError, "missing from live used"):
            MODULE.evaluate(deployment(), desired, live)


if __name__ == "__main__":
    unittest.main()
