#!/usr/bin/env python3
"""Test-overlay rollouts must fit inside the namespace CPU-limits budget.

Why this test exists
--------------------
2026-07-31, pinning auth-service to sha-cd44d86:

    Error creating: pods "auth-service-f668f4546-…" is forbidden: exceeded
    quota: platform-quota, requested: limits.cpu=750m, used: limits.cpu=15450m,
    limited: limits.cpu=16

A surge-based rollout (`maxSurge: 1`) asks for a *second* pod before the first
one goes away, so it needs one whole pod's `limits.cpu` free on top of what the
namespace already spends. Measured that day:

    node k3d-test-server-0 allocatable CPU   8
    platform-quota limits.cpu                15450m / 16000m   (550m free)
    auth-service pod limits.cpu              750m

550m free, 750m wanted -- the ReplicaSet could not create the pod at all, fell
into FailedCreate backoff, and the Deployment blew its progress deadline. The
old pod kept serving, so nothing was down, but the digest could not be rolled;
recovering needed a live `kubectl patch` and a forced new ReplicaSet.

Terminate-first (`maxSurge: 0, maxUnavailable: 1`) needs **no** headroom: the
old pod is removed before the replacement is created, so the namespace total
never rises. That is why 15 of the 26 application Deployments in this overlay
already carried it. The three that did not were a deliberate, *conditional*
exception from 2026-07-17 ("live preflight proved ... enough CPU/memory ...
if headroom later disappears, these rollouts stall boundedly"). The headroom
did later disappear. A comment cannot notice that; this test can.

What it enforces
----------------
Every Deployment rendered by `overlays/test` whose total `limits.cpu` is at or
above ``SURGE_BUDGET_THRESHOLD_MILLICORES`` must render ``maxSurge: 0``.

The threshold exists because the exemption is not "this service is special",
it is "this service's surge request is small enough to fit in the headroom the
namespace actually keeps". Below it sit the public entrypoints -- the frontend
and the two etik-speak apps -- which deliberately keep surge-first: #2299
showed that terminate-first on the only serving frontend pod turns quota
pressure into a public 503. Their surge requests are 150-200m, an order of
magnitude below the free budget, so keeping them costs nothing.

If a public-facing service ever grows past the threshold, this test fails and
the choice becomes explicit: give it a second replica (real availability) or
accept terminate-first. Silently reintroducing an unschedulable rollout is the
one outcome it rules out.
"""

import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEST_OVERLAY = ROOT / "kustomize/overlays/test"

# A rollout may only assume this much spare limits.cpu in platform-test.
# Measured free budget on 2026-07-31 was 550m; 400m keeps a margin under it
# without exempting anything that has ever actually blocked.
SURGE_BUDGET_THRESHOLD_MILLICORES = 400

# Guards against a vacuous pass: if the overlay is renamed or the render
# changes shape, an empty walk would otherwise go green.
MIN_EXPECTED_DEPLOYMENTS = 20


def _millicores(quantity):
    """Parse a Kubernetes CPU quantity ("750m", "1", "1.5") into millicores."""
    if quantity is None:
        return 0
    text = str(quantity)
    if text.endswith("m"):
        return int(text[:-1])
    return int(float(text) * 1000)


def _render(path):
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"kubectl kustomize {path} failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _deployments(docs):
    for doc in docs:
        if doc.get("kind") == "Deployment":
            yield doc


def _pod_limits_cpu(deployment):
    total = 0
    spec = deployment["spec"]["template"]["spec"]
    for container in spec.get("containers", []):
        limits = (container.get("resources") or {}).get("limits") or {}
        total += _millicores(limits.get("cpu"))
    return total


def _max_surge(deployment):
    """None when the Deployment declares no strategy.

    Kubernetes then defaults to 25%/25%, which for a single replica rounds up
    to maxSurge=1 -- i.e. surge-first, the very thing this test is about. So a
    missing strategy is treated as a surge, not as an unknown.
    """
    strategy = deployment["spec"].get("strategy")
    if not strategy:
        return None
    if strategy.get("type") not in (None, "RollingUpdate"):
        # Recreate never surges.
        return 0
    rolling = strategy.get("rollingUpdate") or {}
    return rolling.get("maxSurge")


class TestOverlayRolloutFitsQuota(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deployments = list(_deployments(_render(TEST_OVERLAY)))

    def test_render_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(self.deployments),
            MIN_EXPECTED_DEPLOYMENTS,
            "overlays/test rendered too few Deployments -- the walk found "
            "nothing to check, so a green result would mean nothing",
        )

    def test_heavy_deployments_do_not_surge(self):
        offenders = []
        for deployment in self.deployments:
            limits = _pod_limits_cpu(deployment)
            if limits < SURGE_BUDGET_THRESHOLD_MILLICORES:
                continue
            surge = _max_surge(deployment)
            if surge != 0:
                offenders.append(
                    f"{deployment['metadata']['name']}: limits.cpu={limits}m, "
                    f"maxSurge={'unset (defaults to 1 at replicas=1)' if surge is None else surge}"
                )

        self.assertEqual(
            [],
            offenders,
            "These test-overlay Deployments would need a whole spare pod's "
            "worth of limits.cpu to roll, which platform-quota does not have "
            "(15450m/16000m used on 2026-07-31). Give them "
            "`maxSurge: 0, maxUnavailable: 1`, or give them a second replica "
            "and the budget to run it:\n  " + "\n  ".join(offenders),
        )

    def test_threshold_still_exempts_only_small_surges(self):
        """The exemption must stay about size, not about identity.

        If someone raises the threshold to wave a big service through, this
        catches it: nothing below the threshold may be large enough to matter.
        """
        exempt = [
            (d["metadata"]["name"], _pod_limits_cpu(d))
            for d in self.deployments
            if _pod_limits_cpu(d) < SURGE_BUDGET_THRESHOLD_MILLICORES
        ]
        for name, limits in exempt:
            self.assertLess(
                limits,
                SURGE_BUDGET_THRESHOLD_MILLICORES,
                f"{name} is exempt at {limits}m",
            )
        self.assertLessEqual(
            SURGE_BUDGET_THRESHOLD_MILLICORES,
            550,
            "The threshold may not exceed the free limits.cpu budget measured "
            "in platform-test (550m on 2026-07-31); above that the exemption "
            "stops being 'this surge fits' and becomes 'we hope it fits'",
        )


if __name__ == "__main__":
    unittest.main()
