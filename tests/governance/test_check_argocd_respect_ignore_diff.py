"""Unit tests for the ArgoCD RespectIgnoreDifferences + blanket /metadata
ignore anti-pattern gate (Codex thread 019e41d7 / 019e4216)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "governance"
    / "check_argocd_respect_ignore_diff.py"
)
FIXTURES = REPO_ROOT / "tests" / "governance" / "fixtures"


def run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class TestArgoRespectIgnoreDiff(unittest.TestCase):
    # ----- failing fixtures -----

    def test_fail_blanket_metadata(self) -> None:
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-fail-blanket-metadata.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "fail")
        self.assertEqual(len(data["violations"]), 1)
        v = data["violations"][0]
        self.assertEqual(v["kind"], "jsonPointer")
        self.assertEqual(v["value"], "/metadata")

    def test_fail_managed_fields_pointer(self) -> None:
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-fail-managed-fields.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "fail")
        # Both the exact /metadata/managedFields and the prefixed nested
        # pointer must be flagged.
        values = sorted(v["value"] for v in data["violations"])
        self.assertEqual(
            values,
            sorted(["/metadata/managedFields", "/metadata/managedFields/manager"]),
        )

    def test_fail_broad_annotations(self) -> None:
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-fail-broad-annotations.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "fail")
        values = sorted(v["value"] for v in data["violations"])
        self.assertEqual(
            values, sorted(["/metadata/annotations", "/metadata/labels"])
        )

    def test_fail_jq_metadata(self) -> None:
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-fail-jq-metadata.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "fail")
        # .metadata exact and .metadata.managedFields exact must both fire.
        kinds = [v["kind"] for v in data["violations"]]
        for v in data["violations"]:
            self.assertEqual(v["kind"], "jqPathExpression")
        values = sorted(v["value"] for v in data["violations"])
        self.assertEqual(
            values, sorted([".metadata", ".metadata.managedFields"])
        )
        # remediation must mention the operations doc
        for v in data["violations"]:
            self.assertIn(
                "argocd-respect-ignore-diff-antipattern.md", v["remediation"]
            )

    # ----- passing fixtures -----

    def test_pass_platform_test_pattern(self) -> None:
        """RespectIgnoreDifferences=true with `/metadata/annotations/<key>`
        specific paths is allowed (mirrors the live `platform-test`
        manifest at the time of writing)."""
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-pass-platform-test.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(data["applications_with_respect_on"], 1)
        self.assertEqual(data["violations"], [])

    def test_pass_platform_prod_pattern(self) -> None:
        """`/status`, `/spec/replicas`, ConfigMap `/data`, and specific
        annotation paths must pass even with RespectIgnoreDifferences=true
        (mirrors the live `platform-prod` manifest after PR #851)."""
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-pass-platform-prod.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(data["applications_with_respect_on"], 1)

    def test_pass_no_respect_option(self) -> None:
        """RespectIgnoreDifferences=false (or absent) means even a blanket
        `/metadata` ignore is not a managedFields trap and is allowed."""
        result = run_script(
            [
                "--fixture",
                str(FIXTURES / "argocd-respect-ignore-pass-no-respect-option.yaml"),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "pass")
        # RespectIgnoreDifferences=true ile risk modu açılmadığı için 0
        self.assertEqual(data["applications_with_respect_on"], 0)

    # ----- live repo manifests -----

    def test_live_repo_is_clean(self) -> None:
        """The real `argocd/applications/*.yaml` set must currently pass
        the gate — PR #850 + PR #851 cleared the only known instances."""
        result = run_script([])
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "Live argocd/applications/*.yaml contains the "
                "RespectIgnoreDifferences + blanket /metadata "
                "anti-pattern:\n" + result.stdout + result.stderr
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
