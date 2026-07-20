"""Integration-style tests for the CLI wrapper.

Codex 019e2327 review #6 — earlier coverage missed:
  * wrapper exit semantics (rc=3 exec error, rc=1 drift, rc=0 clean)
  * StatefulSet probe contract assertion (openfga http-healthz)
  * volume defaultMode normalization (configMap.defaultMode injection)
  * pod-level securityContext + terminationGracePeriodSeconds in CONTRACT_SURFACE
  * runtime exec error → exit 3 (not silently downgraded to P1)
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.deploy_normalizer import (  # noqa: E402
    _normalize_volumes,
    assert_probe_contract,
    semantic_diff,
    template_contract_view,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestVolumeDefaultModeNormalization(unittest.TestCase):
    """Codex 019e2327 review #4 — defaultMode 420 injection must not produce drift."""

    def test_configmap_defaultmode_normalized(self):
        desired = [{"name": "config", "configMap": {"name": "x"}}]
        live = [{"name": "config", "configMap": {"name": "x", "defaultMode": 420}}]
        self.assertEqual(_normalize_volumes(desired), _normalize_volumes(live))

    def test_secret_defaultmode_normalized(self):
        desired = [{"name": "tls", "secret": {"secretName": "tls-cert"}}]
        live = [{"name": "tls", "secret": {"secretName": "tls-cert", "defaultMode": 420}}]
        self.assertEqual(_normalize_volumes(desired), _normalize_volumes(live))

    def test_projected_defaultmode_normalized(self):
        desired = [{"name": "p", "projected": {"sources": []}}]
        live = [{"name": "p", "projected": {"sources": [], "defaultMode": 420}}]
        self.assertEqual(_normalize_volumes(desired), _normalize_volumes(live))

    def test_explicit_defaultmode_wins(self):
        desired = [{"name": "config", "configMap": {"name": "x", "defaultMode": 256}}]
        live = [{"name": "config", "configMap": {"name": "x", "defaultMode": 256}}]
        self.assertEqual(_normalize_volumes(desired), _normalize_volumes(live))


class TestStatefulSetSupport(unittest.TestCase):
    """Codex 019e2327 review #3 — StatefulSet must not be inert."""

    def test_openfga_http_healthz_clean(self):
        ofga = _load("openfga_statefulset.json")
        findings = assert_probe_contract(ofga, "http-healthz", "openfga")
        self.assertEqual(findings, [])

    def test_openfga_template_view_extracts_container(self):
        ofga = _load("openfga_statefulset.json")
        view = template_contract_view(ofga)
        self.assertIn("openfga", view["containers"])
        self.assertEqual(
            view["containers"]["openfga"]["livenessProbe"]["httpGet"]["path"],
            "/healthz",
        )

    def test_openfga_drift_detected(self):
        ofga = _load("openfga_statefulset.json")
        drifted = copy.deepcopy(ofga)
        drifted["spec"]["template"]["spec"]["containers"][0]["livenessProbe"][
            "httpGet"
        ]["path"] = "/healthcheck"
        diffs = semantic_diff(ofga, drifted)
        self.assertTrue(any("livenessProbe.httpGet.path" in d[0] for d in diffs))


class TestIndependentProductCellScope(unittest.TestCase):
    """Catalogued product cells remain covered without a false platform label."""

    def test_catalogued_non_platform_workload_is_in_scope(self):
        from check_deployment_contracts import _filter_template_workloads

        ethics = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "ethics-service",
                "labels": {"app.kubernetes.io/part-of": "etik-speak"},
            },
        }
        self.assertEqual(
            _filter_template_workloads([ethics], {"ethics-service"}),
            [ethics],
        )

    def test_uncatalogued_non_platform_workload_stays_out_of_scope(self):
        from check_deployment_contracts import _filter_template_workloads

        lab = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "unmanaged-lab",
                "labels": {"app.kubernetes.io/part-of": "lab"},
            },
        }
        self.assertEqual(_filter_template_workloads([lab], {"ethics-service"}), [])

    def test_catalogued_non_platform_workload_gets_rs_split_check(self):
        from check_deployment_contracts import _check_rs_split

        ethics = {
            "metadata": {
                "name": "ethics-service",
                "uid": "ethics-uid",
                "labels": {"app.kubernetes.io/part-of": "etik-speak"},
            }
        }
        old = _rs("ethics-old", "ethics-uid", replicas=1, ready=1, age_s=3600)
        stalled = _rs("ethics-new", "ethics-uid", replicas=1, ready=0, age_s=600)
        findings = _check_rs_split(
            [ethics],
            [old, stalled],
            grace_seconds=300,
            contract_names={"ethics-service"},
        )
        self.assertTrue(any(f["service"] == "ethics-service" for f in findings))


class TestPodLevelContractSurface(unittest.TestCase):
    """Codex 019e2327 review #5 — pod-level securityContext +
    terminationGracePeriodSeconds must be part of the diff surface.
    """

    def test_pod_security_context_drift_detected(self):
        api_gw = _load("api_gateway_clean.json")
        drifted = copy.deepcopy(api_gw)
        drifted["spec"]["template"]["spec"]["securityContext"] = {"runAsUser": 1000}
        diffs = semantic_diff(api_gw, drifted)
        self.assertTrue(
            any("podSecurityContext" in d[0] for d in diffs),
            f"expected podSecurityContext drift; got {[d[0] for d in diffs]}",
        )

    def test_termination_grace_drift_detected(self):
        api_gw = _load("api_gateway_clean.json")
        drifted = copy.deepcopy(api_gw)
        drifted["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] = 60
        diffs = semantic_diff(api_gw, drifted)
        self.assertTrue(
            any("terminationGracePeriodSeconds" in d[0] for d in diffs),
            f"expected terminationGracePeriodSeconds drift; got {[d[0] for d in diffs]}",
        )


class TestRsSplitOwnerReferences(unittest.TestCase):
    """Codex 019e2327 review — RS-split mapping must use ownerReferences."""

    def test_label_only_match_rejected(self):
        from check_deployment_contracts import _check_rs_split

        # Two RS with the same label but different ownerRef Deployment UIDs
        # — must NOT be conflated.
        deploy_a = {
            "metadata": {
                "name": "deploy-a",
                "uid": "uid-a",
                "labels": {"app.kubernetes.io/part-of": "platform"},
            }
        }
        deploy_b = {
            "metadata": {
                "name": "deploy-b",
                "uid": "uid-b",
                "labels": {"app.kubernetes.io/part-of": "platform"},
            }
        }
        # rs_a_old: 1h old, still has a replica (rolling held over)
        # rs_a_new: 10min old, ready=0 → stalled past grace (5min)
        rs_a_old = _rs("rs-a-old", "uid-a", replicas=1, ready=1, age_s=3600)
        rs_a_new = _rs("rs-a-new", "uid-a", replicas=1, ready=0, age_s=600)
        rs_b_only = _rs("rs-b", "uid-b", replicas=1, ready=1, age_s=3600)

        findings = _check_rs_split(
            [deploy_a, deploy_b],
            [rs_a_old, rs_a_new, rs_b_only],
            grace_seconds=300,
        )
        names = [f["service"] for f in findings]
        self.assertIn("deploy-a", names)
        self.assertNotIn("deploy-b", names)


def _rs(name: str, owner_uid: str, replicas: int, ready: int, age_s: int) -> dict:
    from datetime import datetime, timedelta, timezone

    created = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "metadata": {
            "name": name,
            "creationTimestamp": created,
            "ownerReferences": [{"kind": "Deployment", "uid": owner_uid}],
        },
        "spec": {"replicas": replicas},
        "status": {"readyReplicas": ready},
    }


class TestExecErrorSurfacing(unittest.TestCase):
    """Codex 019e2327 review #2 — runtime exec error must yield exit 3,
    not be downgraded into a P1 finding tied to "(cluster)"."""

    def test_runtime_returns_exec_error_tuple(self):
        # Import lazily to avoid CLI side-effects at module load.
        from check_deployment_contracts import run_runtime
        from lib.services_catalog import ServicesCatalog

        catalog = ServicesCatalog.from_dict(
            {
                "services": [
                    {
                        "name": "api-gateway",
                        "workload_kind": "Deployment",
                        "runtime_class": "spring-backend",
                        "probe_contract": "spring-actuator",
                        "environments": {"test": "enabled"},
                    }
                ]
            }
        )
        # Unreachable context — exec failure.
        findings, exec_error = run_runtime(
            overlay_dir="/nonexistent",
            context="k3d-nope",
            namespace="platform-nope",
            env="test",
            catalog=catalog,
            rs_split_grace_seconds=300,
        )
        self.assertEqual(findings, [])
        self.assertIsNotNone(exec_error)
        self.assertNotEqual(exec_error, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
