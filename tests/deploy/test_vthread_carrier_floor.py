"""The virtual-thread carrier floor must stay lifted on the hot-path JVMs.

Why this exists. All five hot-path services (auth, permission, user, variant,
gateway) run Spring's ``spring.threads.virtual.enabled=true`` on Java 21, and
their manifests pin ``-XX:ActiveProcessorCount=1``. Together those give the
virtual-thread scheduler a SINGLE carrier thread: one pinned virtual thread
(``synchronized`` + blocking I/O — pgjdbc and Apache HttpClient both pin)
stalls every other virtual thread in that JVM, and the stalls stack across the
gateway -> user -> permission -> user call chain.

Measured on the live test cell 2026-07-30 before the fix: permission-service's
outbound ``/api/users/by-email`` averaged 14.3s client-side while user-service
served the same request in 49ms; ``/api/v1/users`` answered 503 after ~30s,
seven out of seven attempts. Codex thread 019fb47c ruled the remedy (F1):
``-Djdk.virtualThreadScheduler.parallelism=4 -Djdk.virtualThreadScheduler.maxPoolSize=8``,
with ``ActiveProcessorCount=1`` deliberately KEPT — it still sizes GC/JIT
correctly for the 750m CPU quota; only the carrier count must be decoupled
from it.

What is enforced, per rendered overlay (test AND prod, because the fix lives
in the shared base): for each hot-path Deployment the single
``JAVA_TOOL_OPTIONS`` value carries all three flags exactly once, and the
per-service heap override survives (the test overlay REPLACES the whole env
string for auth-service and api-gateway — a partial edit there silently drops
the scheduler flags, which is exactly the regression this test is for).
"""

import re
import subprocess
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

HOT_PATH_SERVICES = (
    "auth-service",
    "permission-service",
    "user-service",
    "variant-service",
    "api-gateway",
)

REQUIRED_FLAGS = (
    "-XX:ActiveProcessorCount=1",
    "-Djdk.virtualThreadScheduler.parallelism=4",
    "-Djdk.virtualThreadScheduler.maxPoolSize=8",
)

# Heap must not be silently changed while touching the flag string. The test
# overlay deliberately lowers auth to 256m and gateway to 384m (base is 512m).
EXPECTED_HEAP = {
    ("test", "auth-service"): "-Xmx256m",
    ("test", "api-gateway"): "-Xmx384m",
    ("prod", "api-gateway"): "-Xmx512m",
}


def _render(overlay: str) -> str:
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / "kustomize" / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _java_tool_options(rendered: str, service: str) -> str:
    values = []
    for doc in yaml.safe_load_all(rendered):
        if not doc or doc.get("kind") != "Deployment":
            continue
        if doc.get("metadata", {}).get("name") != service:
            continue
        for container in doc["spec"]["template"]["spec"].get("containers", []):
            for env in container.get("env", []) or []:
                if env.get("name") == "JAVA_TOOL_OPTIONS":
                    values.append(env.get("value", ""))
    if len(values) != 1:
        raise AssertionError(
            f"{service}: expected exactly one JAVA_TOOL_OPTIONS value, found {len(values)}"
        )
    return values[0]


class VthreadCarrierFloorTests(unittest.TestCase):
    """Rendered-manifest gate for the F1 scheduler flags (Codex 019fb47c Gate 1)."""

    @classmethod
    def setUpClass(cls):
        cls.rendered = {overlay: _render(overlay) for overlay in ("test", "prod")}

    def test_hot_path_jvms_carry_the_scheduler_flags_exactly_once(self):
        for overlay, rendered in self.rendered.items():
            for service in HOT_PATH_SERVICES:
                with self.subTest(overlay=overlay, service=service):
                    value = _java_tool_options(rendered, service)
                    for flag in REQUIRED_FLAGS:
                        occurrences = value.count(flag)
                        self.assertEqual(
                            occurrences,
                            1,
                            f"{overlay}/{service}: {flag!r} must appear exactly once "
                            f"in JAVA_TOOL_OPTIONS, found {occurrences} in {value!r} — "
                            "a single-carrier JVM turns one pinned virtual thread "
                            "into a whole-service stall",
                        )

    def test_parallelism_stays_below_pool_ceiling(self):
        for overlay, rendered in self.rendered.items():
            for service in HOT_PATH_SERVICES:
                with self.subTest(overlay=overlay, service=service):
                    value = _java_tool_options(rendered, service)
                    par = int(re.search(r"parallelism=(\d+)", value).group(1))
                    ceiling = int(re.search(r"maxPoolSize=(\d+)", value).group(1))
                    self.assertLessEqual(
                        par,
                        ceiling,
                        f"{overlay}/{service}: scheduler parallelism above maxPoolSize "
                        "cannot start — the JVM rejects it at boot",
                    )

    def test_heap_overrides_survive_the_flag_edit(self):
        for (overlay, service), heap in EXPECTED_HEAP.items():
            with self.subTest(overlay=overlay, service=service):
                value = _java_tool_options(self.rendered[overlay], service)
                self.assertIn(
                    heap,
                    value,
                    f"{overlay}/{service}: expected heap {heap} lost while editing "
                    "JAVA_TOOL_OPTIONS — the overlay replaces the WHOLE string, so a "
                    "partial edit drops sibling settings silently",
                )


if __name__ == "__main__":
    unittest.main()
