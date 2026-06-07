#!/usr/bin/env python3
"""Regression tests for Faz 22.2.A / #1044 evidence helper CLIs.

These tests intentionally exercise the command-line surface instead of importing
helpers as modules. The helpers are used by operators and CI-like runbooks, so
the CLI contract is the relevant compatibility surface.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ACCEPTANCE = REPO_ROOT / "scripts/faz22-non-domain/a1-acceptance-verifier.py"
OPERATOR_PACK = REPO_ROOT / "scripts/faz22-non-domain/a1-operator-evidence-pack.py"
CURRENT_ROLLUP = REPO_ROOT / "docs/faz-22-evidence/2026-06-07-non-domain-pilot-tierA1-rollup-current.md"


def run_cmd(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class A1AcceptanceVerifierTest(unittest.TestCase):
    def test_current_partial_rollup_fails(self) -> None:
        result = run_cmd(str(ACCEPTANCE), "--rollup-doc", str(CURRENT_ROLLUP))

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("OVERALL FAIL", result.stdout)
        self.assertIn("metadata_status_pass", result.stdout)
        self.assertIn("device_count_min", result.stdout)
        self.assertIn("heartbeat_threshold", result.stdout)

    def test_synthetic_three_device_pass_rollup_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("device1.md", "device2.md", "device3.md"):
                (root / name).write_text("# per-device evidence\n", encoding="utf-8")
            rollup = root / "rollup-pass.md"
            rollup.write_text(
                textwrap.dedent(
                    """\
                    # Faz 22.2.A non-domain pilot rollup — Tier A1 multi-device

                    > **Status**: PASS
                    > **Tracked by**: #1044
                    > **Tier**: A1
                    > **Scope**: 3 devices
                    > **Soak window**: 2026-06-06T06:00Z -> 2026-06-07T06:00Z
                    > **Codex thread**: test-thread

                    ## 1. Device summary table

                    | # | Hostname (or pseudonym) | Device ID | Tier | Per-device evidence doc | Status | Helper verdict |
                    |---|---|---|---|---|---|---|
                    | 1 | device1 | `00000000-0000-0000-0000-000000000001` | A1 | [link](./device1.md) | PASS | ROLLUP_FACTS_OK |
                    | 2 | device2 | `00000000-0000-0000-0000-000000000002` | A1 | [link](./device2.md) | PASS | ROLLUP_FACTS_OK |
                    | 3 | device3 | `00000000-0000-0000-0000-000000000003` | A1 | [link](./device3.md) | PASS | ROLLUP_FACTS_OK |

                    ## 2. Aggregate metrics (per §14.5 formula)

                    | Metric | Value | Acceptance threshold | Verdict |
                    |---|---|---|---|
                    | Heartbeat success rate (pilot-wide) | 99.50% (8597/8640) | >=99% | PASS |
                    | Command terminal/accounted rate (pilot-wide) | 100.00% (3/3) | 100% | PASS |
                    | Command success rate (pilot-wide) | 100.00% (3/3) | >=95% | PASS |
                    | Soak gap incidents (unexplained > 30m) | 0 | 0 required | PASS |
                    | Repeatability gate | PASS | per §14.5 rule | PASS |

                    ## 3. Acceptance verdict

                    **Verdict**: PASS

                    ## 5. Cross-AI peer review

                    Implementer AI: Codex
                    Reviewer AI: Claude
                    Verdict: AGREE
                    """
                ),
                encoding="utf-8",
            )

            result = run_cmd(str(ACCEPTANCE), "--rollup-doc", str(rollup))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OVERALL PASS (18/18)", result.stdout)


class A1OperatorEvidencePackTest(unittest.TestCase):
    def test_default_pack_is_review_only_and_excludes_soak_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            out_dir = root / "out"

            write = run_cmd(str(OPERATOR_PACK), "--write-example-manifest", str(manifest))
            self.assertEqual(write.returncode, 0, write.stdout + write.stderr)

            build = run_cmd(
                str(OPERATOR_PACK),
                "--manifest",
                str(manifest),
                "--output-dir",
                str(out_dir),
                "--include-winget-egress",
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            command_script = (out_dir / "run-evidence-pack.sh").read_text(encoding="utf-8")
            checklist = (out_dir / "operator-checklist.md").read_text(encoding="utf-8")

        self.assertIn("a1-local-vm-diagnostics.sh", command_script)
        self.assertIn("a1-evidence-doc-from-diagnostics.py", command_script)
        self.assertNotIn("a1-soak-rollup.sh", command_script)
        self.assertNotIn("a1-rollup-doc-from-soak.py", command_script)
        self.assertIn("Soak SELECT command included: `no", checklist)
        self.assertIn("Rollup generation command included: `no", checklist)
        forbidden_credential_pattern = "|".join(
            (
                "Bearer" + r"\s+",
                "Authorization:" + r"\s+" + "Bearer",
                "-" * 5 + "BEGIN",
            )
        )
        self.assertNotRegex(command_script + checklist, forbidden_credential_pattern)

    def test_generate_rollup_requires_soak_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            run_cmd(str(OPERATOR_PACK), "--write-example-manifest", str(manifest))

            result = run_cmd(
                str(OPERATOR_PACK),
                "--manifest",
                str(manifest),
                "--output-dir",
                str(root / "out"),
                "--generate-rollup-doc",
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--generate-rollup-doc requires --soak-output or --run-soak", result.stderr)

    def test_manifest_secret_like_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            fake_bearer = "Bearer " + "eyJ" + ("a" * 20) + "." + ("b" * 24) + "." + ("c" * 10)
            manifest.write_text(
                json.dumps(
                    {
                        "trackedBy": "1044",
                        "tier": "A1",
                        "operator": fake_bearer,
                        "devices": [
                            {
                                "vm": "Windows 11",
                                "hostname": "HALILKOOLUB735",
                                "deviceId": "PENDING",
                            }
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = run_cmd(str(OPERATOR_PACK), "--manifest", str(manifest), "--output-dir", str(root / "out"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("potential secret-like value", result.stderr)


if __name__ == "__main__":
    unittest.main()
