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
OPERATOR_PACKET = REPO_ROOT / "docs/runbooks/RB-faz22-a1-two-device-operator-packet.md"
LINKED_CLONE = REPO_ROOT / "scripts/faz22-non-domain/a1-linked-clone-batch.sh"
LOCAL_DIAGNOSTICS = REPO_ROOT / "scripts/faz22-non-domain/a1-local-vm-diagnostics.sh"
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


def run_shell(*args: str, env: dict[str, str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        ["bash", *args],
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_fake_a1_linked_clone_tools(root: Path, *, parent_status: str = "running", free_gib: int = 47) -> dict[str, str]:
    bin_dir = root / "bin"
    parent_home = root / "Windows 11.pvm"
    parent_home.mkdir()
    clone_log = root / "clone.log"
    bin_dir.mkdir()

    (bin_dir / "prlctl").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail

            cmd="${1:-}"
            shift || true

            case "$cmd" in
              status)
                vm="${1:-}"
                if [ "$vm" = "${FAKE_PARENT_VM}" ]; then
                  printf 'The VM is %s\\n' "${FAKE_PARENT_STATUS}"
                  exit 0
                fi
                exit 1
                ;;
              list)
                if [ "${1:-}" = "-i" ]; then
                  printf 'Home: %s\\n' "${FAKE_PARENT_HOME}"
                else
                  printf 'UUID STATUS IP_ADDR NAME\\n'
                  printf 'fake stopped - %s\\n' "${FAKE_PARENT_VM}"
                fi
                ;;
              snapshot-list)
                printf 'ID NAME DATE\\n'
                ;;
              clone)
                parent="${1:-}"
                shift || true
                clone=""
                while [ $# -gt 0 ]; do
                  case "$1" in
                    --name)
                      clone="${2:-}"
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                printf 'clone|%s|%s\\n' "$parent" "$clone" >> "${FAKE_CLONE_LOG}"
                ;;
              *)
                printf 'unexpected prlctl command: %s\\n' "$cmd" >&2
                exit 2
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    (bin_dir / "df").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            free_kib=$((FAKE_FREE_GIB * 1024 * 1024))
            printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'
            printf '/dev/fake 999999999 1 %s 1%% /System/Volumes/Data\\n' "$free_kib"
            """
        ),
        encoding="utf-8",
    )
    (bin_dir / "du").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '75G\\t%s\\n' "${*: -1}"
            """
        ),
        encoding="utf-8",
    )
    for helper in ("prlctl", "df", "du"):
        (bin_dir / helper).chmod(0o755)

    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_PARENT_VM": "Windows 11",
        "FAKE_PARENT_STATUS": parent_status,
        "FAKE_PARENT_HOME": str(parent_home),
        "FAKE_FREE_GIB": str(free_gib),
        "FAKE_CLONE_LOG": str(clone_log),
    }


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


class A1OperatorPacketDocTest(unittest.TestCase):
    def test_packet_links_manifest_driven_wrapper(self) -> None:
        text = OPERATOR_PACKET.read_text(encoding="utf-8")

        self.assertIn("a1-operator-evidence-pack.py", text)
        self.assertIn("--write-example-manifest", text)
        self.assertIn("--manifest", text)
        self.assertIn("no secrets", text.lower())
        self.assertIn("operator-checklist.md", text)
        self.assertIn("run-evidence-pack.sh", text)


class A1LinkedCloneBatchTest(unittest.TestCase):
    def test_linked_clone_help_is_comment_only(self) -> None:
        result = run_shell(str(LINKED_CLONE), "--help", env={})

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("local Parallels A1 linked-clone batch helper", result.stdout)
        self.assertIn("--execute", result.stdout)
        self.assertNotIn("set -euo pipefail", result.stdout)
        self.assertNotIn("CLONES=(", result.stdout)

    def test_dry_run_reports_running_parent_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = write_fake_a1_linked_clone_tools(root, parent_status="running")

            result = run_shell(str(LINKED_CLONE), env=env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("parent VM is running", result.stdout)
        self.assertIn("dry-run complete", result.stdout)
        self.assertNotIn("creating linked clone", result.stdout)

    def test_execute_refuses_running_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = write_fake_a1_linked_clone_tools(root, parent_status="running")
            clone_log = Path(env["FAKE_CLONE_LOG"])

            result = run_shell(str(LINKED_CLONE), "--execute", env=env)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to clone while parent VM is running", result.stderr)
            self.assertFalse(clone_log.exists())

    def test_execute_stopped_parent_creates_requested_linked_clones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = write_fake_a1_linked_clone_tools(root, parent_status="stopped")
            clone_log = Path(env["FAKE_CLONE_LOG"])

            result = run_shell(
                str(LINKED_CLONE),
                "--clone",
                "NONDOMAIN-W11-LAB-ALPHA",
                "--clone",
                "NONDOMAIN-W11-LAB-BETA",
                "--execute",
                env=env,
            )
            log_text = clone_log.read_text(encoding="utf-8") if clone_log.exists() else ""

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("linked-clone batch created", result.stdout)
        self.assertIn("clone|Windows 11|NONDOMAIN-W11-LAB-ALPHA", log_text)
        self.assertIn("clone|Windows 11|NONDOMAIN-W11-LAB-BETA", log_text)
        self.assertNotIn("NONDOMAIN-W11-LAB-01", log_text)
        self.assertNotIn("NONDOMAIN-W11-LAB-02", log_text)

    def test_low_disk_fails_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = write_fake_a1_linked_clone_tools(root, parent_status="stopped", free_gib=5)
            clone_log = Path(env["FAKE_CLONE_LOG"])

            result = run_shell(str(LINKED_CLONE), "--execute", "--min-free-gib", "10", env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("host free space 5GiB is below minimum 10GiB", result.stderr)
        self.assertFalse(clone_log.exists())


class A1LocalVmDiagnosticsTest(unittest.TestCase):
    def test_local_diagnostics_help_is_comment_only_and_complete(self) -> None:
        result = run_shell(str(LOCAL_DIAGNOSTICS), "--help", env={})

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("local Parallels A1 read-only diagnostics helper", result.stdout)
        self.assertIn("--include-winget-egress", result.stdout)
        self.assertIn('--vm "Windows 11"', result.stdout)
        self.assertNotIn("shellcheck disable", result.stdout)
        self.assertNotIn("set -euo pipefail", result.stdout)


if __name__ == "__main__":
    unittest.main()
