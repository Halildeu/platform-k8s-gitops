#!/usr/bin/env python3
"""Tests for the Faz 24 I3 Denetim audit-controls package builder."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-i3-denetim-audit-controls-package.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-i3-denetim-audit-controls-package.yml"


class BuildI3DenetimAuditControlsPackageTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_least_privilege_rollback_capable_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script("--output-dir", tmpdir)
            output = Path(tmpdir)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)
            self.assertEqual(
                {
                    "collect-audit-snapshot.ps1",
                    "install-audit-controls.ps1",
                    "rollback-audit-controls.ps1",
                    "baseline.json",
                    "package-manifest.json",
                    "README.md",
                    "SHA256SUMS",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads((output / "package-manifest.json").read_text(encoding="utf-8"))
            baseline = json.loads((output / "baseline.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "faz24.i3.denetim.audit-controls-package.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual("windows-system", manifest["privilegeModel"]["collectorIdentity"])
            self.assertEqual("snapshot-read-only", manifest["privilegeModel"]["transportAccess"])
            self.assertTrue(manifest["rollback"]["initialStateCapturedBeforeMutation"])
            self.assertTrue(manifest["rollback"]["automaticOnPartialApplyFailure"])
            self.assertTrue(manifest["rollback"]["packageFingerprintBound"])
            self.assertTrue(manifest["rollback"]["preexistingManagedFilesRestored"])
            self.assertEqual(
                "logon-subcategory-only", manifest["rollback"]["auditPolicyRestoreScope"]
            )
            self.assertEqual(
                [
                    "firewall-impact-decision",
                    "apply",
                    "validate",
                    "rollback-drill",
                    "reapply",
                    "revalidate",
                    "fresh-evidence",
                ],
                manifest["operatorFlow"],
            )
            self.assertEqual(14, manifest["transcriptRetention"]["maximumDays"])
            self.assertEqual(1073741824, manifest["transcriptRetention"]["maximumBytes"])
            self.assertTrue(manifest["transcriptRetention"]["reparsePointsRejected"])
            self.assertFalse(manifest["secretMaterialIncluded"])
            self.assertEqual("restricted-operator-config", manifest["classification"])
            self.assertTrue(manifest["containsIdentityMetadata"])
            self.assertEqual([22, 8200, 8243], baseline["prohibitedBroadInboundPorts"])
            self.assertEqual(14, baseline["transcriptRetentionDays"])
            self.assertEqual(1073741824, baseline["maximumTranscriptBytes"])
            self.assertEqual(3, len(baseline["expectedFirewallRules"]))
            self.assertTrue(
                all(rule["remoteAddress"] == "10.99.0.1" for rule in baseline["expectedFirewallRules"])
            )
            self.assertTrue(
                all(
                    rule["localAddress"] == "Any"
                    and rule["profile"] == "Any"
                    and rule["program"] == "Any"
                    and rule["service"] == "Any"
                    for rule in baseline["expectedFirewallRules"]
                )
            )

            collector = (output / "collect-audit-snapshot.ps1").read_text(encoding="utf-8")
            installer = (output / "install-audit-controls.ps1").read_text(encoding="utf-8")
            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertIn("AuditQuerySystemPolicy", collector)
            self.assertIn("show all dump", collector)
            self.assertIn("$fields[5]", collector)
            self.assertNotIn("$fields[4]", collector)
            self.assertIn("eventMessagesIncluded = $false", collector)
            self.assertIn("Write-AtomicJson", collector)
            self.assertIn("[System.IO.File]::Replace", collector)
            self.assertIn("$stream.Flush($true)", collector)
            self.assertIn("$remoteAddresses.Count -eq 1", collector)
            self.assertIn("Get-NetFirewallApplicationFilter", collector)
            self.assertIn("Get-NetFirewallServiceFilter", collector)
            self.assertIn("$localAddresses.Count -eq 1", collector)
            self.assertIn("$profiles.Count -eq 1", collector)
            self.assertIn("function Test-RemoteAddressBroad", collector)
            self.assertIn("'LocalSubnet'", collector)
            self.assertIn("$prefixLength -lt $maximumPrefix", collector)
            self.assertIn("-RemoteAddresses $remoteAddresses", collector)
            self.assertIn("sourceSynchronized", collector)
            self.assertIn("syncTypeConfigured", collector)
            self.assertIn("W32Time\\Parameters", collector)
            self.assertIn("sourceFormatSafe", collector)
            self.assertIn("eventAfterServiceStart", collector)
            self.assertIn("serviceProcess.StartTime.ToUniversalTime()", collector)
            self.assertNotIn("Local CMOS Clock", collector)
            self.assertIn("protectedSnapshotDirectoryAcl", collector)
            self.assertIn("protectedSnapshotFileAcl", collector)
            self.assertIn("Get-TranscriptFilesNoReparse", collector)
            self.assertIn("Invoke-TranscriptRetention", collector)
            self.assertIn("Invoke-TranscriptRetentionForPolicy", collector)
            self.assertIn("-Path $outputPath", collector)
            self.assertNotIn("-Path $TranscriptPath -RetentionDays", collector)
            self.assertIn("transcript-descendant-reparse-point-rejected", collector)
            self.assertIn("maximumTranscriptBytes", collector)
            self.assertIn("Save-InitialState", installer)
            self.assertIn("rollback-state-incomplete", installer)
            self.assertIn("faz24.windows-audit-rollback.v2", installer)
            self.assertIn("rollback-required-before-package-change", installer)
            self.assertIn("apply-failed-auto-rollback-completed", installer)
            self.assertIn("Restore-InitialState -State $state", installer)
            self.assertIn("Get-LogonAuditPolicyState", installer)
            self.assertIn("('/success:' + $successSetting)", installer)
            self.assertNotIn("auditpol /restore", installer)
            self.assertNotIn("auditpol /backup", installer)
            self.assertIn("GetValueKind", installer)
            self.assertIn("reserved-firewall-rule-name-conflict", installer)
            self.assertIn("$snapshotTime.UtcDateTime -ge $startedAt.AddSeconds(-5)", installer)
            self.assertIn("aclRestoreRoot=(Split-Path -Parent $Root)", installer)
            self.assertIn("$restoreRoot -ne (Split-Path -Parent $Root)", installer)
            self.assertNotIn("[System.IO.Path]::GetPathRoot($Root)", installer)
            self.assertNotIn("DisableBroadConflicts", installer)
            self.assertNotIn(
                "-DisableBroadConflicts", (output / "README.md").read_text(encoding="utf-8")
            )
            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("package-fingerprint-bound transaction", readme)
            self.assertIn("14 days", readme)
            self.assertIn("1 GiB", readme)
            self.assertIn("never performs a full-machine `auditpol /restore`", readme)
            self.assertIn("broad-firewall-conflicts-require-separate-reviewed-remediation", installer)
            self.assertIn("function Test-RemoteAddressBroad", installer)
            self.assertIn("-RemoteAddresses @($address.RemoteAddress)", installer)
            self.assertIn("New-ExactDirectorySecurity", installer)
            self.assertIn("-LocalAddress Any", installer)
            self.assertIn("-Program Any", installer)
            self.assertIn("-Service Any", installer)
            self.assertGreaterEqual(installer.count("Invoke-SnapshotAndRead"), 4)
            self.assertNotIn("Restore-RuleState", installer)
            self.assertIn("Register-ScheduledTask", installer)
            self.assertIn("-User 'SYSTEM'", installer)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)

    def test_generated_powershell_has_no_parser_errors(self):
        if shutil.which("pwsh") is None:
            self.skipTest("pwsh not installed")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script("--output-dir", tmpdir)
            self.assertEqual(0, result.returncode, result.stderr)
            command = r'''
$failed = $false
Get-ChildItem -LiteralPath $env:PACKAGE_DIR -Filter '*.ps1' | ForEach-Object {
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
  if ($errors.Count -gt 0) {
    $failed = $true
    $errors | ForEach-Object { Write-Error $_.Message }
  }
}
if ($failed) { exit 1 }
'''
            parsed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                env={**os.environ, "PACKAGE_DIR": tmpdir},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)

    def test_rejects_unsafe_target_user_and_address(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user_result = self.run_script(
                "--output-dir", tmpdir, "--target-user", "user;whoami"
            )
        self.assertNotEqual(0, user_result.returncode)
        self.assertIn("target user contains unsupported characters", user_result.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            address_result = self.run_script(
                "--output-dir", tmpdir, "--management-address", "10.99.0.999"
            )
        self.assertNotEqual(0, address_result.returncode)
        self.assertIn("invalid IPv4 octet", address_result.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            alternate_user = self.run_script(
                "--output-dir", tmpdir, "--target-user", "alternate-reader"
            )
        self.assertNotEqual(0, alternate_user.returncode)
        self.assertIn("must be the canonical svc-denetim-agent", alternate_user.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            alternate_address = self.run_script(
                "--output-dir", tmpdir, "--management-address", "10.99.0.9"
            )
        self.assertNotEqual(0, alternate_address.returncode)
        self.assertIn("must be the canonical 10.99.0.1", alternate_address.stderr)

    def test_workflow_builds_and_scans_operator_artifact(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("build-i3-denetim-audit-controls-package.py", workflow)
        self.assertIn("private/secret-like material", workflow)
        self.assertIn("actions/upload-artifact@v7", workflow)
        self.assertIn("RESTRICTED-faz24-i3-denetim-audit-controls", workflow)
        self.assertIn("retention-days: 1", workflow)
        self.assertIn("must match the canonical read-only identity", workflow)
        self.assertIn("must match the canonical WireGuard management peer", workflow)


if __name__ == "__main__":
    unittest.main()
