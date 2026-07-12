#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I6 MASQ evidence validator (schema v2)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i6-masq-evidence.py"

V2_CHECK_IDS = [
    "cluster-identity-bound",
    "effective-cluster-cidr-matches-config",
    "node-pod-cidrs-within-cluster-cidr",
    "host-owned-chain-authority",
    "peer-route-is-wireguard-path",
    "pod-to-wg-peer-tcp-connect",
    "snat-rule-counter-traversal",
    "reboot-persistence",
    "drift-detect",
    "rollback-defined",
    "no-broad-lan-nat",
    "daemonset-not-assumed",
]


def valid_evidence() -> dict:
    checks = []
    for check_id in V2_CHECK_IDS:
        checks.append(
            {
                "id": check_id,
                "status": "pass",
                "observedAt": "2026-07-12T03:20:00Z",
                "summary": f"{check_id} metadata satisfied",
                "evidenceRef": f"checks/{check_id}.json",
            }
        )

    return {
        "schemaVersion": "faz24.wg-bplus.i6.pod-cidr-wg-masq.v3",
        "collectedAt": "2026-07-12T03:20:00Z",
        "status": "pass",
        "protectedEvidencePath": "github-actions://Halildeu/platform-k8s-gitops/actions/runs/1",
        "redaction": {
            "secretMaterialIncluded": False,
            "rawCommandOutputIncluded": False,
            "rawPacketCaptureIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
        },
        "topology": {
            "clusterName": "k3d-test",
            "clusterCIDR": "10.44.0.0/16",
            "nodePodCIDRs": ["10.44.0.0/24"],
            "serviceCIDR": "10.45.0.0/16",
            "wgInterface": "wg0",
            "platformAiTarget": {
                "host": "10.99.0.2",
                "port": 8243,
            },
        },
        "mechanism": {
            "type": "host-systemd-iptables",
            "managedOutsideCluster": True,
            "daemonSetAssumed": False,
            "host": "staging-sw",
            "systemdUnit": "k3d-wg-masq.service",
            "iptablesTable": "nat",
            "iptablesChain": "POSTROUTING",
            "ownedNatChain": "K3D_WG_MASQ_NAT",
            "expectedRuleHash": "0123456789abcdef",
        },
        "driftDetection": {
            "enabled": True,
            "mode": "systemd-timer",
            "intervalMinutes": 5,
            "expectedRuleHash": "0123456789abcdef",
            "evidenceRef": "drift/k3d-wg-masq-timer.json",
        },
        "rollback": {
            "defined": True,
            "tested": True,
            "commandHash": "fedcba9876543210",
            "evidenceRef": "rollback/dry-run.json",
        },
        "checks": checks,
        "collector": {
            "runner": "self-hosted-staging-sw",
            "clusterIdentity": {
                "contextName": "k3d-test",
                "clusterUidHash": "0123456789abcdef",
                "uidResolved": True,
                "nodeName": "k3d-test-server-0",
                "dockerNetwork": "platform-test-net",
                "nodeExists": True,
                "nodeOnNetwork": True,
                "apiServerHostHash": "fedcba9876543210",  # gitleaks:allow (test fixture: fake sha256_short digest, not a credential)
                "apiServerResolved": True,
                "endpointIsK3dLoopback": True,
                "beltPolicyApplied": True,
                "beltPolicyExpectedCidr": "10.44.0.0/16",
                "beltPolicyOk": True,
                "bound": True,
            },
            "effectiveCidr": {
                "configuredClusterCidr": "10.44.0.0/16",
                "effectiveClusterCidr": "10.44.0.0/16",
                "configSourceCidr": "10.44.0.0/16",
                "cmdlineSourceCidr": "10.44.0.0/16",
                "sourcesConflict": False,
                "matchesConfig": True,
                "resolved": True,
                "passed": True,
            },
            "nodePodCidrs": {
                "nodePodCIDRs": ["10.44.0.0/24"],
                "clusterCidr": "10.44.0.0/16",
                "sourceReadable": True,
                "allWithinClusterCidr": True,
                "passed": True,
            },
            "hostOwnedChain": {
                "hostRuleScript": "bootstrap/host/k3d-wg-masq/k3d-wg-masq-host-rule.sh",
                "runScript": "bootstrap/host/k3d-wg-masq/k3d-wg-masq-host-rule.sh",
                "scriptFound": True,
                "canonicalSha256": "ab" * 32,
                "checkExitCode": 0,
                "installedProvided": False,
                "installedSha256": None,
                "shaMatches": True,
                "executionMode": "sudo-canonical",
                "ownedNatChain": "K3D_WG_MASQ_NAT",
                "passed": True,
            },
            "peerRoute": {
                "expectedWgInterface": "wg0",
                "routeProbeExitCode": 0,
                "routeResolved": True,
                "routeDevice": "wg0",
                "routeDevIsWireguard": True,
                "allowedIpsProbeExitCode": 0,
                "allowedIpsCoverPeer": True,
                "peerFingerprint": "0f1e2d3c4b5a6978",
                "handshakeAgeSeconds": 30,
                "passed": True,
            },
            "podProbe": {
                "namespace": "platform-test",
                "targetHost": "10.99.0.2",
                "targetPort": 8243,
                "attempts": 3,
                "successCount": 3,
                "attemptExitCodes": [0, 0, 0],
                "ncMissing": False,
                "matchCount": 1,
                "podIP": "10.44.5.99",
                "podIpHash": "99990000aaaabbbb",
                "podNameHash": "1111222233334444",
                "podUidHash": "5555666677778888",
                "nodeName": "k3d-test-server-0",
                "hostNetwork": False,
                "phase": "Running",
                "ready": True,
                "deletionTimestampPresent": False,
                "imageRef": "busybox@sha256:" + ("a" * 64),
                "runtimeImageID": "docker-pullable://busybox@sha256:" + ("a" * 64),
                "podWithinClusterCidr": True,
                "podOnTargetNode": True,
                "passed": True,
            },
            "counterTraversal": {
                "ownedNatChain": "K3D_WG_MASQ_NAT",
                "attempts": 3,
                "successCount": 3,
                "counterBefore": 0,
                "counterAfter": 3,
                "counterDelta": 3,
                "ruleFingerprintHash": "abcabcabcabcabca",
                "ruleFingerprintBeforeHash": "abcabcabcabcabca",
                "ruleFingerprintAfterHash": "abcabcabcabcabca",
                "ruleStable": True,
                "counterNotReset": True,
                "tcpProbeGateSatisfied": True,
                "passed": True,
            },
            "systemd": {
                "unit": "k3d-wg-masq.service",
                "active": True,
                "enabled": True,
                "showExitCode": 0,
                "hasExecStart": True,
                "hasExecStop": True,
                "driftTimer": "k3d-wg-masq.timer",
                "driftTimerActive": True,
                "driftTimerEnabled": True,
            },
            "broadNat": {
                "queryable": True,
                "probeExitCode": 0,
                "broadNatDetected": False,
                "passed": True,
            },
            "blockers": [],
        },
    }


class WgBplusI6MasqEvidenceValidatorTest(unittest.TestCase):
    def run_validator(self, data: dict, *extra_args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(SCRIPT), tmp.name, *extra_args],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_valid_evidence_passes(self):
        result = self.run_validator(valid_evidence())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I6 MASQ evidence: PASS", result.stdout)
        self.assertIn("clusterCIDR=10.44.0.0/16", result.stdout)

    def test_v2_schema_string_is_rejected(self):
        # v3 acceptance semantics differ; v2 (and v1) blocked evidence stays historical.
        data = valid_evidence()
        data["schemaVersion"] = "faz24.wg-bplus.i6.pod-cidr-wg-masq.v2"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema_version", result.stderr)

    def test_daemonset_assumption_fails(self):
        data = valid_evidence()
        data["mechanism"]["daemonSetAssumed"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("mechanism.daemonSetAssumed", result.stderr)

    def test_missing_owned_nat_chain_fails(self):
        data = valid_evidence()
        del data["mechanism"]["ownedNatChain"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("owned_nat_chain", result.stderr)

    def test_missing_required_v2_check_fails(self):
        data = valid_evidence()
        data["checks"] = [c for c in data["checks"] if c["id"] != "snat-rule-counter-traversal"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required check 'snat-rule-counter-traversal'", result.stderr)

    def test_duplicate_check_id_fails(self):
        data = valid_evidence()
        data["checks"].append(dict(data["checks"][0]))

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("duplicate check id", result.stderr)

    def test_secret_or_raw_output_key_fails(self):
        data = valid_evidence()
        data["rawOutput"] = "iptables -t nat -S output"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_secret_like_value_fails(self):
        data = valid_evidence()
        data["operatorNote"] = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJpNiJ9.fakefakefake"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_rollback_must_be_tested(self):
        data = valid_evidence()
        data["rollback"]["tested"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("rollback.tested", result.stderr)

    def test_drift_hash_must_match_mechanism_hash(self):
        data = valid_evidence()
        data["driftDetection"]["expectedRuleHash"] = "1111111111111111"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("drift_hash_mismatch", result.stderr)

    def test_broad_cluster_cidr_fails(self):
        data = valid_evidence()
        data["topology"]["clusterCIDR"] = "10.0.0.0/8"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("prefix is too broad", result.stderr)

    def test_host_bits_in_cluster_cidr_fail(self):
        data = valid_evidence()
        data["topology"]["clusterCIDR"] = "10.44.0.5/16"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be a valid CIDR", result.stderr)

    def test_empty_node_pod_cidrs_fails(self):
        data = valid_evidence()
        data["topology"]["nodePodCIDRs"] = []

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("nodePodCIDRs must be a non-empty list", result.stderr)

    def test_invalid_node_pod_cidr_fails(self):
        data = valid_evidence()
        data["topology"]["nodePodCIDRs"] = ["not-a-cidr"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("nodePodCIDRs", result.stderr)

    def test_absolute_evidence_ref_fails(self):
        data = valid_evidence()
        data["checks"][0]["evidenceRef"] = "/etc/iptables/rules.v4"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must stay under protectedEvidencePath", result.stderr)

    def test_parent_traversal_evidence_ref_fails(self):
        data = valid_evidence()
        data["checks"][0]["evidenceRef"] = "checks/../raw.txt"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must stay under protectedEvidencePath", result.stderr)

    # ------------------------------------------------------------------
    # Semantic re-compute layer: status stays "pass" on all 12 checks but the
    # collector.* / topology metadata contradicts it. status must be necessary
    # but NOT sufficient -> the verifier must FAIL these.
    # ------------------------------------------------------------------
    def assert_semantic_fail(self, data: dict, needle: str = "check_semantic") -> None:
        result = self.run_validator(data)
        self.assertNotEqual(0, result.returncode, "verifier should reject contradictory metadata")
        self.assertIn(needle, result.stderr)

    def test_all_pass_but_probe_success_zero_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["successCount"] = 0
        data["collector"]["podProbe"]["attemptExitCodes"] = [1, 1, 1]
        self.assert_semantic_fail(data)

    def test_all_pass_but_nc_missing_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["ncMissing"] = True
        self.assert_semantic_fail(data)

    def test_vacuous_zero_attempts_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["attempts"] = 0
        data["collector"]["podProbe"]["successCount"] = 0
        data["collector"]["podProbe"]["attemptExitCodes"] = []
        data["collector"]["counterTraversal"]["attempts"] = 0
        data["collector"]["counterTraversal"]["successCount"] = 0
        data["collector"]["counterTraversal"]["counterAfter"] = 0
        data["collector"]["counterTraversal"]["counterDelta"] = 0
        self.assert_semantic_fail(data)

    def test_partial_tcp_success_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["successCount"] = 2
        data["collector"]["podProbe"]["attemptExitCodes"] = [0, 0, 1]
        self.assert_semantic_fail(data)

    def test_probe_and_counter_attempts_mismatch_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["attempts"] = 2
        self.assert_semantic_fail(data)

    def test_counter_delta_arithmetic_mismatch_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["counterBefore"] = 10
        data["collector"]["counterTraversal"]["counterAfter"] = 12
        data["collector"]["counterTraversal"]["counterDelta"] = 3
        self.assert_semantic_fail(data)

    def test_counter_reset_despite_flag_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["counterBefore"] = 10
        data["collector"]["counterTraversal"]["counterAfter"] = 9
        data["collector"]["counterTraversal"]["counterDelta"] = -1
        data["collector"]["counterTraversal"]["counterNotReset"] = True
        self.assert_semantic_fail(data)

    def test_rule_unstable_despite_flag_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["ruleStable"] = False
        self.assert_semantic_fail(data)

    def test_fingerprint_mismatch_despite_stable_flag_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["ruleFingerprintAfterHash"] = "ffffffffffffffff"
        self.assert_semantic_fail(data)

    def test_effective_cidr_mismatch_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["effectiveClusterCidr"] = "10.42.0.0/16"
        self.assert_semantic_fail(data)

    def test_effective_cidr_sources_conflict_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["sourcesConflict"] = True
        self.assert_semantic_fail(data)

    def test_node_pod_cidr_outside_cluster_cidr_fails(self):
        data = valid_evidence()
        data["topology"]["nodePodCIDRs"] = ["10.99.0.0/24"]
        self.assert_semantic_fail(data)

    def test_route_device_wrong_fails(self):
        data = valid_evidence()
        data["collector"]["peerRoute"]["routeDevice"] = "eth0"
        self.assert_semantic_fail(data)

    def test_allowed_ips_not_covering_peer_fails(self):
        data = valid_evidence()
        data["collector"]["peerRoute"]["allowedIpsCoverPeer"] = False
        self.assert_semantic_fail(data)

    def test_installed_sha_mismatch_despite_flag_fails(self):
        data = valid_evidence()
        data["collector"]["hostOwnedChain"]["installedProvided"] = True
        data["collector"]["hostOwnedChain"]["installedSha256"] = "cd" * 32
        data["collector"]["hostOwnedChain"]["shaMatches"] = True
        self.assert_semantic_fail(data)

    def test_cluster_identity_not_bound_fails(self):
        data = valid_evidence()
        data["collector"]["clusterIdentity"]["bound"] = False
        self.assert_semantic_fail(data)

    def test_belt_policy_mismatch_in_metadata_fails(self):
        data = valid_evidence()
        # k3d-test context but clusterCIDR is the prod range -> belt violation.
        data["topology"]["clusterCIDR"] = "10.42.0.0/16"
        data["collector"]["effectiveCidr"]["configuredClusterCidr"] = "10.42.0.0/16"
        data["collector"]["effectiveCidr"]["effectiveClusterCidr"] = "10.42.0.0/16"
        data["collector"]["effectiveCidr"]["configSourceCidr"] = "10.42.0.0/16"
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = "10.42.0.0/16"
        self.assert_semantic_fail(data, "cluster-identity-bound")

    def test_no_collector_block_fails(self):
        data = valid_evidence()
        del data["collector"]
        self.assert_semantic_fail(data)

    def assert_semantic_pass(self, data: dict) -> None:
        result = self.run_validator(data)
        self.assertEqual(0, result.returncode, result.stderr)

    # -- Patch 2: bool-where-int type confusion (isinstance(True,int) is True) --
    def test_bool_check_exit_code_fails(self):
        data = valid_evidence()
        data["collector"]["hostOwnedChain"]["checkExitCode"] = False
        self.assert_semantic_fail(data)

    def test_bool_attempt_exit_codes_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["attemptExitCodes"] = [False, False, False]
        self.assert_semantic_fail(data)

    def test_bool_attempts_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["attempts"] = True
        self.assert_semantic_fail(data)

    def test_bool_success_count_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["successCount"] = True
        self.assert_semantic_fail(data)

    def test_bool_counter_before_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["counterBefore"] = True
        data["collector"]["counterTraversal"]["counterAfter"] = 4
        data["collector"]["counterTraversal"]["counterDelta"] = 3
        self.assert_semantic_fail(data)

    def test_bool_counter_after_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["counterAfter"] = True
        self.assert_semantic_fail(data)

    def test_bool_counter_delta_fails(self):
        data = valid_evidence()
        data["collector"]["counterTraversal"]["counterDelta"] = True
        self.assert_semantic_fail(data)

    # -- Patch 3: attemptExitCodes is mandatory --
    def test_missing_attempt_exit_codes_fails(self):
        data = valid_evidence()
        del data["collector"]["podProbe"]["attemptExitCodes"]
        # successCount left at 3 and all checks status="pass"; must still fail.
        self.assert_semantic_fail(data)

    # -- Patch 4: effective CIDR must be backed by a valid observed source --
    def test_effective_cidr_no_observed_source_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["configSourceCidr"] = None
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = None
        self.assert_semantic_fail(data)

    def test_config_source_not_equal_effective_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["configSourceCidr"] = "10.42.0.0/16"
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = None
        self.assert_semantic_fail(data)

    def test_cmdline_source_not_equal_effective_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["configSourceCidr"] = None
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = "10.42.0.0/16"
        self.assert_semantic_fail(data)

    def test_config_source_present_but_invalid_fails(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["configSourceCidr"] = "garbage"
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = "10.44.0.0/16"
        self.assert_semantic_fail(data)

    def test_only_config_source_valid_passes(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["cmdlineSourceCidr"] = None
        self.assert_semantic_pass(data)

    def test_only_cmdline_source_valid_passes(self):
        data = valid_evidence()
        data["collector"]["effectiveCidr"]["configSourceCidr"] = None
        self.assert_semantic_pass(data)

    # -- Patch 5: unknown context rejected by the positive belt --
    def test_unknown_context_fails(self):
        data = valid_evidence()
        data["topology"]["clusterName"] = "unknown-cluster"
        self.assert_semantic_fail(data, "cluster-identity-bound")

    # -- v3: pod-to-wg-peer-tcp-connect re-derived from RAW pod metadata --
    def test_pod_ip_outside_cluster_cidr_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["podIP"] = "10.99.0.20"
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_within_cluster_cidr_flag_ignored_when_raw_ip_outside(self):
        # the informational boolean is a lie; the verifier recomputes from raw podIP.
        data = valid_evidence()
        data["collector"]["podProbe"]["podIP"] = "10.99.0.20"
        data["collector"]["podProbe"]["podWithinClusterCidr"] = True
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_on_wrong_node_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["nodeName"] = "k3d-test-server-1"
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_on_target_node_flag_ignored_when_nodename_differs(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["nodeName"] = "k3d-test-server-1"
        data["collector"]["podProbe"]["podOnTargetNode"] = True
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_host_network_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["hostNetwork"] = True
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_match_count_zero_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["matchCount"] = 0
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_match_count_two_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["matchCount"] = 2
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_not_ready_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["ready"] = False
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_pod_deletion_timestamp_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["deletionTimestampPresent"] = True
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_image_tag_only_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["imageRef"] = "busybox:1.36"
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_runtime_image_id_missing_fails(self):
        data = valid_evidence()
        data["collector"]["podProbe"]["runtimeImageID"] = None
        self.assert_semantic_fail(data, "pod-to-wg-peer-tcp-connect")

    def test_execution_mode_direct_fails(self):
        # a non-sudo "direct" host-rule run with checkExitCode 0 is not authoritative.
        data = valid_evidence()
        data["collector"]["hostOwnedChain"]["executionMode"] = "direct"
        self.assert_semantic_fail(data, "host-owned-chain-authority")

    def test_summary_json_is_written(self):
        data = valid_evidence()
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as evidence_tmp:
            with tempfile.NamedTemporaryFile("r", suffix=".json", encoding="utf-8") as summary_tmp:
                json.dump(data, evidence_tmp)
                evidence_tmp.flush()

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        evidence_tmp.name,
                        "--summary-json",
                        summary_tmp.name,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                summary = json.load(summary_tmp)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pass", summary["status"])
        self.assertEqual("10.44.0.0/16", summary["clusterCIDR"])
        self.assertEqual(
            "faz24.wg-bplus.i6.pod-cidr-wg-masq-evidence-verification.v3", summary["schemaVersion"]
        )


if __name__ == "__main__":
    unittest.main()
