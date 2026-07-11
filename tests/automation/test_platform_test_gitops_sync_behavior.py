from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = ROOT / "scripts/faz22/sync-platform-test-gitops.sh"
REVISION = "a" * 40


class PlatformTestGitopsSyncBehaviorTests(unittest.TestCase):
    def write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_sync(self, *, sync_exit: int, wait_exit: int):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            mutation_marker = tmp / "kubectl-mutation"
            report_path = tmp / "report.json"

            self.write_executable(
                fake_bin / "argocd",
                f"""
                #!/usr/bin/env python3
                import sys
                args = sys.argv[1:]
                if "wait" in args:
                    raise SystemExit({wait_exit})
                if "sync" in args:
                    raise SystemExit({sync_exit})
                raise SystemExit(0)
                """,
            )
            self.write_executable(
                fake_bin / "kubectl",
                f"""
                #!/usr/bin/env python3
                import json
                import pathlib
                import sys

                args = sys.argv[1:]
                if args[:2] == ["config", "view"]:
                    print("apiVersion: v1")
                    raise SystemExit(0)
                if "config" in args and "set-context" in args:
                    raise SystemExit(0)
                if "apply" in args or "patch" in args or "replace" in args:
                    pathlib.Path({str(mutation_marker)!r}).write_text("mutation")
                    raise SystemExit(0)
                if "get" in args and "application" in args:
                    if "-o" in args:
                        output = args[args.index("-o") + 1]
                        if output == "json":
                            print(json.dumps({{"spec": {{"source": {{"targetRevision": "main"}}}}}}))
                        elif "sync.status" in output:
                            print("Synced", end="")
                        elif "health.status" in output:
                            print("Progressing", end="")
                        elif "sync.revision" in output:
                            print({REVISION!r}, end="")
                    raise SystemExit(0)
                raise SystemExit(0)
                """,
            )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "REVISION": REVISION,
                    "TIMEOUT": "1",
                    "REPORT_PATH": str(report_path),
                    "RUNNER_TEMP": str(tmp),
                    "ALLOW_KUBECTL_SELECTED_RESOURCE_FALLBACK": "false",
                }
            )
            result = subprocess.run(
                ["bash", str(SYNC_SCRIPT)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            return (
                result,
                mutation_marker.exists(),
                json.loads(report_path.read_text(encoding="utf-8")),
            )

    def test_post_sync_health_timeout_never_enters_kubectl_fallback(self):
        result, mutated, report = self.run_sync(sync_exit=0, wait_exit=1)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "sync completed but application did not reach Synced/Healthy",
            result.stderr,
        )
        self.assertFalse(mutated)
        self.assertEqual("FAIL", report["verdict"])
        self.assertEqual("argocd", report["sync_mode"])
        self.assertEqual("Synced", report["sync_status"])
        self.assertEqual("Progressing", report["health_status"])

    def test_sync_command_failure_is_not_swallowed_or_fallback_mutated(self):
        result, mutated, report = self.run_sync(sync_exit=42, wait_exit=0)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("ArgoCD sync command failed", result.stderr)
        self.assertIn("fallback was not attempted", result.stderr)
        self.assertFalse(mutated)
        self.assertEqual("FAIL", report["verdict"])


if __name__ == "__main__":
    unittest.main()
