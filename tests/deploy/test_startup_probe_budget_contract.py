#!/usr/bin/env python3
"""startupProbe budget invariant.

Why this test exists
--------------------
2026-07-23: `endpoint-admin-service` boots in **243 s** while its startupProbe
budget was 150 s (`failureThreshold: 30` x `periodSeconds: 5`). The kubelet
therefore SIGKILLed the container (`Error`, exit 137) before Spring Boot could
bind the management port -- 153 probe failures in 68 minutes, 8-10 restarts, and
the remote-bridge broker flapping with it.

The manifest comment still claimed "Spring Boot startup takes 50-60 seconds".
That was true when it was written; the services grew and the fixed budget did
not. Two services (`notification-orchestrator`, `endpoint-admin-remote-bridge-
device-key`) had already been patched locally to 200 s -- the symptom was met
service-by-service, the shared root cause was never fixed.

A comment cannot enforce a budget. This test can: it fails the build if any
startupProbe budget drops below the measured worst case plus headroom.

Measured boot times (k3d-test, 15 services booting concurrently, 2026-07-23):

    endpoint-admin-service                   243.0 s   <- worst case
    endpoint-admin-remote-bridge-device-key  179.5 s
    endpoint-admin-remote-bridge             131.2 s
    audio-gateway                            123.2 s
    ats-interview-evidence                   113.6 s
    ... 10 further services                42.6-108.7 s

`MIN_BUDGET_SECONDS` is worst-case x ~2.5. A generous startupProbe is cheap:
while it runs, liveness/readiness are suspended and the pod receives no traffic,
so a genuinely broken pod still never serves -- it is just restarted later.
An undersized one is expensive, as the incident above shows.
"""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE_APPS = ROOT / "kustomize/base/apps"
TEST_ACTIVATION = ROOT / "kustomize/overlays/test/activation"

MIN_BUDGET_SECONDS = 600

# Guards against a vacuous pass: if a refactor moves or renames the manifests,
# the walk would silently find nothing and the suite would still go green.
MIN_EXPECTED_PROBES = 15


def _budget(probe):
    """Kubelet gives a container failureThreshold x periodSeconds to start.

    initialDelaySeconds is added because the kubelet waits it out before the
    first probe, so it genuinely extends the window.
    """
    period = int(probe.get("periodSeconds", 10))
    failures = int(probe.get("failureThreshold", 3))
    initial = int(probe.get("initialDelaySeconds", 0))
    return initial + period * failures


def _iter_startup_probes(root):
    """Yield (path, container_name, probe) for every startupProbe under root.

    Overlay files are strategic-merge fragments rather than whole Deployments,
    so the containers list is read directly instead of via a schema.
    """
    for path in sorted(root.rglob("*.yaml")):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") not in (None, "Deployment", "StatefulSet"):
                continue
            spec = (((doc.get("spec") or {}).get("template") or {}).get("spec") or {})
            for container in spec.get("containers") or []:
                probe = container.get("startupProbe")
                if isinstance(probe, dict):
                    yield path, container.get("name", "?"), probe


class StartupProbeBudgetTest(unittest.TestCase):
    def test_base_app_budgets_meet_measured_worst_case(self):
        probes = list(_iter_startup_probes(BASE_APPS))
        undersized = [
            (p.relative_to(ROOT).as_posix(), name, _budget(probe))
            for p, name, probe in probes
            if _budget(probe) < MIN_BUDGET_SECONDS
        ]
        self.assertEqual(
            undersized,
            [],
            "startupProbe budget below the measured worst-case boot time "
            f"({MIN_BUDGET_SECONDS}s floor). Undersized: {undersized}",
        )

    def test_test_overlay_patches_do_not_lower_the_budget(self):
        """An overlay patch replaces the base probe wholesale.

        `endpoint-admin-remote-bridge-device-key` did exactly this: it pinned
        200 s and so silently overrode whatever the base declared.
        """
        undersized = [
            (p.relative_to(ROOT).as_posix(), name, _budget(probe))
            for p, name, probe in _iter_startup_probes(TEST_ACTIVATION)
            if _budget(probe) < MIN_BUDGET_SECONDS
        ]
        self.assertEqual(
            undersized,
            [],
            "test-overlay startupProbe patch lowers the budget below the "
            f"{MIN_BUDGET_SECONDS}s floor. Undersized: {undersized}",
        )

    def test_probe_walk_is_not_vacuous(self):
        found = len(list(_iter_startup_probes(BASE_APPS)))
        self.assertGreaterEqual(
            found,
            MIN_EXPECTED_PROBES,
            f"only {found} startupProbe(s) found under {BASE_APPS}; the walk "
            "is probably no longer reaching the manifests, so the budget "
            "assertions above would pass vacuously",
        )

    def test_stale_60_second_boot_claim_is_gone(self):
        """The obsolete comment is what made the undersized budget look sane."""
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in BASE_APPS.rglob("deployment.yaml")
            if re.search(r"startup that takes 50-60 seconds", path.read_text())
        ]
        self.assertEqual(
            offenders,
            [],
            "manifest still claims a 50-60 second Spring Boot startup; the "
            f"measured worst case is 243 s. Offenders: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
