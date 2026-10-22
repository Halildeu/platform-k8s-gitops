"""#3888 — k3d stuck-pod self-heal selection contract.

Shapes below are trimmed copies of real pods observed on aiserver on
2026-10-22 after the 2026-10-15 reboot (k3d-test tempo-0, auth-service,
artifact-host; k3d-prod external-secrets) plus the cases that must NOT be
touched (healthy, CrashLoopBackOff, Job pods, pods being deleted).
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "k3d_stuck_pod_heal.py"
spec = importlib.util.spec_from_file_location("k3d_stuck_pod_heal", SCRIPT)
heal = importlib.util.module_from_spec(spec)
sys.modules["k3d_stuck_pod_heal"] = heal
spec.loader.exec_module(heal)

NOW = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)


def pod(name, owner="ReplicaSet", phase="Running", containers=None, init=None, deleting=False, ns="platform-test"):
    meta = {"name": name, "namespace": ns}
    if owner:
        meta["ownerReferences"] = [{"kind": owner, "name": name.rsplit("-", 1)[0]}]
    if deleting:
        meta["deletionTimestamp"] = "2026-10-22T05:59:00Z"
    status = {"phase": phase, "containerStatuses": containers or []}
    if init is not None:
        status["initContainerStatuses"] = init
    return {"metadata": meta, "status": status}


def terminated(finished="2026-10-15T11:58:43Z", code=137):
    return {"name": "c", "state": {"terminated": {"exitCode": code, "finishedAt": finished}}}


def waiting(reason, message=""):
    return {"name": "c", "state": {"waiting": {"reason": reason, "message": message}}}


RUNNING = {"name": "c", "state": {"running": {"startedAt": "2026-10-22T05:00:00Z"}}}


class TestClassify(unittest.TestCase):
    def test_reserved_container_name_is_recycled(self):
        p = pod("external-secrets-7d956d6c57-gqjb6", ns="external-secrets", containers=[waiting(
            "CreateContainerError",
            'failed to reserve container name "external-secrets_..._5": name "..." is reserved for "abc"')])
        self.assertEqual(heal.classify(p, NOW, 10), "reserved_name")

    def test_reserved_name_in_init_container_is_recycled(self):
        p = pod("x-1", init=[waiting("CreateContainerError", "failed to reserve container name \"i\"")],
                containers=[waiting("PodInitializing")])
        self.assertEqual(heal.classify(p, NOW, 10), "reserved_name")

    def test_controller_pod_terminated_for_days_is_abandoned(self):
        self.assertEqual(heal.classify(pod("tempo-0", owner="StatefulSet", containers=[terminated()]), NOW, 10),
                         "abandoned")

    def test_rs_pod_completed_exit0_is_abandoned(self):
        # artifact-host-7b8dc7655d-lfzwj showed "0/1 Completed" under a Deployment
        p = pod("artifact-host-7b8dc7655d-lfzwj", phase="Succeeded", containers=[terminated(code=0)])
        self.assertEqual(heal.classify(p, NOW, 10), "abandoned")

    def test_recently_terminated_pod_gets_grace(self):
        p = pod("auth-service-1", containers=[terminated(finished="2026-10-22T05:55:00Z")])
        self.assertIsNone(heal.classify(p, NOW, 10))

    def test_crashloopbackoff_is_left_alone(self):
        p = pod("auth-service-2", containers=[waiting("CrashLoopBackOff", "back-off 5m0s restarting failed container")])
        self.assertIsNone(heal.classify(p, NOW, 10))

    def test_healthy_and_partially_running_pods_untouched(self):
        self.assertIsNone(heal.classify(pod("ok-1", containers=[RUNNING]), NOW, 10))
        self.assertIsNone(heal.classify(pod("mixed-1", containers=[RUNNING, terminated()]), NOW, 10))

    def test_job_pods_are_never_touched(self):
        self.assertIsNone(heal.classify(pod("smoke-29876610-x", owner="Job", phase="Succeeded",
                                            containers=[terminated(code=0)]), NOW, 10))
        self.assertIsNone(heal.classify(pod("smoke-29876611-y", owner="Job", phase="Failed",
                                            containers=[terminated(code=1)]), NOW, 10))

    def test_bare_pod_terminated_is_not_abandoned(self):
        self.assertIsNone(heal.classify(pod("debug", owner=None, containers=[terminated()]), NOW, 10))

    def test_pod_already_being_deleted_is_skipped(self):
        p = pod("x", deleting=True, containers=[waiting("CreateContainerError", "failed to reserve sandbox name")])
        self.assertIsNone(heal.classify(p, NOW, 10))

    def test_select_reports_namespace_name_reason(self):
        pods = [pod("tempo-0", owner="StatefulSet", ns="monitoring", containers=[terminated()]),
                pod("ok-1", containers=[RUNNING])]
        self.assertEqual(heal.select(pods, NOW, 10), [("monitoring", "tempo-0", "abandoned")])


class TestRunCaps(unittest.TestCase):
    def test_dry_run_never_deletes_and_cap_limits_selection(self):
        pods = [pod(f"p-{i}", containers=[terminated()]) for i in range(5)]
        calls = []

        def fake_kubectl(ctx, *args):
            calls.append(args)
            if args[:2] == ("get", "pods"):
                import json
                return json.dumps({"items": pods})
            return ""

        orig = heal._kubectl
        heal._kubectl = fake_kubectl
        try:
            self.assertEqual(heal.run(["k3d-test"], apply=False, grace_minutes=10, max_deletes=3), 0)
            self.assertFalse(any("delete" in a for a in calls))
            calls.clear()
            heal.run(["k3d-test"], apply=True, grace_minutes=10, max_deletes=3)
            self.assertEqual(sum("delete" in a for a in calls), 3)
        finally:
            heal._kubectl = orig


if __name__ == "__main__":
    unittest.main()
