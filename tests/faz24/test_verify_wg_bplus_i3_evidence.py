#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I3 evidence validator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i3-evidence.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class WgBplusI3EvidenceValidatorTest(unittest.TestCase):
    def run_validator(
        self, path: Path, *, refresh_timestamps: bool = True
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secure_path = Path(tmp_dir) / "evidence.json"
            raw = path.read_bytes()
            if refresh_timestamps:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    pass
                else:
                    now = datetime.now(timezone.utc).replace(microsecond=0).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    data["collectedAt"] = now
                    for check in data.get("checks", []):
                        if isinstance(check.get("when"), str) and check["when"].endswith("Z"):
                            check["when"] = now
                        control = check.get("control")
                        if isinstance(control, dict):
                            control["collectedAt"] = now
                    raw = (json.dumps(data, indent=2) + "\n").encode("utf-8")
            secure_path.write_bytes(raw)
            secure_path.chmod(0o600)
            return self.run_validator_direct(secure_path)

    def run_validator_direct(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            capture_output=True,
            check=False,
        )

    def run_data(
        self, data: dict, *, refresh_timestamps: bool = True
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return self.run_validator(
                Path(tmp.name), refresh_timestamps=refresh_timestamps
            )

    def test_valid_fixture_prints_redacted_control_summary(self):
        result = self.run_validator(FIXTURES / "wg-bplus-i3-valid.json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I3 evidence: PASS", result.stdout)
        self.assertIn("openssh-event-log: verdict=pass errorClass=none fresh=true", result.stdout)
        self.assertIn("staging-connection-log: verdict=pass", result.stdout)
        self.assertNotIn("svc-denetim-agent", result.stdout)
        self.assertNotIn("denetim-pc", result.stdout.lower())
        self.assertNotIn("Bearer ", result.stdout)

    def test_missing_required_check_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"] = [check for check in data["checks"] if check["id"] != "time-sync"]

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required check 'time-sync'", result.stderr)

    def test_secret_like_key_or_value_fails(self):
        result = self.run_validator(FIXTURES / "wg-bplus-i3-secret-leak.json")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_secret_like_value_fails_without_committed_secret_fixture(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        jwt_parts = [
            "eyJhbGciOiJIUzI1NiJ9",
            "eyJzdWIiOiJzbW9rZSJ9",
            "fakefakefake",
        ]
        data["notes"] = "Bearer " + ".".join(jwt_parts)

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_redaction_flags_must_be_false(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["redaction"]["rawTranscriptIncluded"] = True

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("redaction.rawTranscriptIncluded must be false", result.stderr)

    def test_timestamp_and_evidence_ref_are_bounded(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["when"] = "yesterday"
        data["checks"][0]["evidenceRef"] = "../../secret.txt"

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("when must use UTC format", result.stderr)
        self.assertIn("evidenceRef must be a relative path", result.stderr)

    def test_stale_control_fails_even_when_status_says_pass(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][1]["control"]["fresh"] = False
        data["checks"][1]["control"]["ageSeconds"] = 901

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("fresh must be true", result.stderr)
        self.assertIn("ageSeconds must equal the timestamp-derived age", result.stderr)

    def test_semantically_weak_firewall_claim_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        firewall = next(check for check in data["checks"] if check["id"] == "eset-firewall-drift")
        firewall["control"]["observed"]["broadConflictCount"] = 2

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "unconstrained broad inbound hard-block count must be zero",
            result.stderr,
        )

    def test_negative_constrained_broad_review_count_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        firewall = next(check for check in data["checks"] if check["id"] == "eset-firewall-drift")
        firewall["control"]["observed"]["constrainedBroadReviewCount"] = -1

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "constrained broad review count must be a non-negative integer",
            result.stderr,
        )

    def test_constrained_broad_review_approval_count_must_match(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        firewall = next(check for check in data["checks"] if check["id"] == "eset-firewall-drift")
        firewall["control"]["observed"]["constrainedBroadReviewCount"] = 2
        firewall["control"]["observed"]["approvedConstrainedBroadReviewCount"] = 1

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "constrained broad review approval must match the observed count",
            result.stderr,
        )

    def test_v1_control_contract_is_not_reused_as_v2_evidence(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["control"]["contractVersion"] = (
            "faz24.windows-audit-control.v1"
        )

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "control.contractVersion must be 'faz24.windows-audit-control.v2'",
            result.stderr,
        )

    def test_zero_failed_login_count_is_valid_with_native_audit_proof(self):
        result = self.run_validator(FIXTURES / "wg-bplus-i3-valid.json")

        self.assertEqual(0, result.returncode, result.stderr)

    def test_transport_service_cannot_be_declared_as_writer(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["acl"]["writers"].append("svc-denetim-agent")

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("exact writer set", result.stderr)

    def test_unknown_top_level_field_fails_closed(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["notes"] = "unexpected"

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown_field", result.stderr)
        self.assertIn("$.notes", result.stderr)

    def test_unknown_observed_field_fails_closed(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["control"]["observed"]["optimistic"] = True

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown_field", result.stderr)
        self.assertIn("optimistic", result.stderr)

    def test_duplicate_json_key_fails(self):
        raw = (FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8")
        raw = raw.replace(
            '"schemaVersion": "faz24.wg-bplus.i3.audit.v2",',
            '"schemaVersion": "faz24.wg-bplus.i3.audit.v2",\n'
            '  "schemaVersion": "faz24.wg-bplus.i3.audit.v2",',
            1,
        )

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            tmp.write(raw)
            tmp.flush()
            result = self.run_validator(Path(tmp.name), refresh_timestamps=False)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("duplicate_json_key", result.stderr)

    def test_raw_identity_value_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["who"] = "svc-denetim-agent@10.99.0.2"

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("raw_identity_value", result.stderr)

    def test_redacted_target_hash_cannot_be_rebound_consistently(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["collector"]["denetimTargetHash"] = "deadbeefdeadbeef"
        data["checks"][0]["who"] = "windows-transport-target:deadbeefdeadbeef"

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("canonical Denetim target", result.stderr)
        self.assertIn("canonical redacted principal", result.stderr)

    def test_redacted_host_hash_cannot_be_rebound(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["collector"]["denetimSshPreflight"]["targetHostHash"] = "deadbeefdeadbeef"

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("canonical Denetim host", result.stderr)

    def test_remote_snapshot_path_hash_cannot_be_rebound(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["collector"]["remoteSnapshotPathHash"] = "deadbeefdeadbeef"

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("canonical snapshot path", result.stderr)

    def test_route_hash_must_match_selected_wireguard_interface(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        preflight = data["collector"]["denetimSshPreflight"]
        preflight["routeDeviceHash"] = "deadbeefdeadbeef"
        preflight["routeUsesSelectedWireGuardInterface"] = True

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("route device must equal", result.stderr)

    def test_snapshot_acl_proof_is_mandatory(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        transcription = next(
            check for check in data["checks"] if check["id"] == "powershell-transcription"
        )
        transcription["control"]["observed"]["protectedSnapshotFileAcl"] = False

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("protectedSnapshotFileAcl must be proven true", result.stderr)

    def test_staging_requires_a_correlated_journal_match(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        staging = next(check for check in data["checks"] if check["id"] == "staging-connection-log")
        staging["control"]["observed"]["journalMatchCount"] = 0

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("journalMatchCount must meet minimumJournalMatchCount", result.stderr)

    def test_stale_bundle_cannot_pass_with_forged_freshness_fields(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))

        result = self.run_data(data, refresh_timestamps=False)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("bundle_freshness", result.stderr)
        self.assertIn("control timestamp is stale at validation time", result.stderr)

    def test_timestamp_derived_age_mismatch_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["control"]["ageSeconds"] = 7

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("control_age_mismatch", result.stderr)

    def test_artifact_cannot_weaken_canonical_thresholds(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        wireguard = next(check for check in data["checks"] if check["id"] == "wireguard-health")
        wireguard["control"]["expected"]["maximumHandshakeAgeSeconds"] = 999999
        wireguard["control"]["observed"]["latestHandshakeAgeSeconds"] = 950000

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("repository canonical policy", result.stderr)

    def test_unsynchronized_time_source_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        time_sync = next(check for check in data["checks"] if check["id"] == "time-sync")
        time_sync["control"]["observed"]["sourceSynchronized"] = False

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be synchronized", result.stderr)

    def test_no_sync_registry_type_fails_even_with_source_text(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        time_sync = next(check for check in data["checks"] if check["id"] == "time-sync")
        time_sync["control"]["observed"]["syncTypeConfigured"] = False

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sync type must be configured", result.stderr)

    def test_staging_socket_query_and_current_attempt_are_mandatory(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        staging = next(
            check for check in data["checks"] if check["id"] == "staging-connection-log"
        )
        staging["control"]["observed"]["sshSocketQueryable"] = False
        staging["control"]["observed"]["journalSinceAttemptStart"] = False

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sshSocketQueryable must be proven true", result.stderr)
        self.assertIn("journalSinceAttemptStart must be proven true", result.stderr)

    def test_email_identity_is_rejected_even_when_not_a_known_service_account(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["who"] = "alice@example.com"

        result = self.run_data(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("raw_identity_value", result.stderr)
        self.assertIn("check_who", result.stderr)

    def test_group_or_world_readable_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            evidence = Path(tmp_dir) / "evidence.json"
            evidence.write_bytes((FIXTURES / "wg-bplus-i3-valid.json").read_bytes())
            evidence.chmod(0o644)
            result = self.run_validator_direct(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("evidence_file_mode", result.stderr)

    def test_symlink_evidence_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "target.json"
            link = Path(tmp_dir) / "evidence.json"
            target.write_bytes((FIXTURES / "wg-bplus-i3-valid.json").read_bytes())
            target.chmod(0o600)
            os.symlink(target, link)
            result = self.run_validator_direct(link)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("evidence_symlink", result.stderr)


if __name__ == "__main__":
    unittest.main()
