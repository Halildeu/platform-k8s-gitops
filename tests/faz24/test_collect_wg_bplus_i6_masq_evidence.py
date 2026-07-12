#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I6 MASQ metadata collector (schema v2).

These tests drive the collector through a configurable fake host runner so the
full adversarial matrix can be exercised offline. The single most important
regression guarded here is: the owned SNAT counter advancing is NOT sufficient —
unless the pod-origin TCP probe actually succeeds N/N, the evidence FAILS.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "faz24" / "collect-wg-bplus-i6-masq-evidence.py"
VERIFIER_PATH = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i6-masq-evidence.py"

spec = importlib.util.spec_from_file_location("collect_wg_bplus_i6_masq_evidence", COLLECTOR_PATH)
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

CHAIN = collector.OWNED_NAT_CHAIN


class FakeHostRunner:
    """Configurable fake for collector.run_command.

    Every knob defaults to a HEALTHY k3d-test topology. Adversarial tests flip a
    single knob and assert exactly the affected check(s) fail.
    """

    def __init__(
        self,
        *,
        uid: str = "kube-system-uid-abcdef",
        server_url: str = "https://0.0.0.0:6446",
        node_networks: dict | None = None,
        node_missing: bool = False,
        config_yaml_cidr: str | None = "10.44.0.0/16",
        cmdline_cidr: str | None = "10.44.0.0/16",
        node_pod_cidrs: list[str] | None = None,
        nodes_unreadable: bool = False,
        host_rule_check_exit: int = 0,
        route_dev: str = "wg0",
        allowed_ips_cover: bool = True,
        peer_pubkey: str = "ABtestPeerPublicKeyMaterial0000000000000000=",
        pods_running: bool = True,
        pod_ip: str = "10.44.0.15",
        nc_exit: list[int] | None = None,
        counter_before: int = 0,
        counter_after: int = 3,
        owned_source_before: str = "172.18.0.2/32",
        owned_source_after: str | None = None,
        broad_nat: bool = False,
        systemd_healthy: bool = True,
    ) -> None:
        self.commands: list[list[str]] = []
        self.uid = uid
        self.server_url = server_url
        self.node_networks = node_networks if node_networks is not None else {
            "platform-test-net": {"IPAddress": "172.18.0.2"}
        }
        self.node_missing = node_missing
        self.config_yaml_cidr = config_yaml_cidr
        self.cmdline_cidr = cmdline_cidr
        self.node_pod_cidrs = node_pod_cidrs if node_pod_cidrs is not None else ["10.44.0.0/24"]
        self.nodes_unreadable = nodes_unreadable
        self.host_rule_check_exit = host_rule_check_exit
        self.route_dev = route_dev
        self.allowed_ips_cover = allowed_ips_cover
        self.peer_pubkey = peer_pubkey
        self.pods_running = pods_running
        self.pod_ip = pod_ip
        self.nc_queue = list(nc_exit if nc_exit is not None else [0, 0, 0])
        self.counter_before = counter_before
        self.counter_after = counter_after
        self.owned_source_before = owned_source_before
        self.owned_source_after = owned_source_after if owned_source_after is not None else owned_source_before
        self.broad_nat = broad_nat
        self.systemd_healthy = systemd_healthy
        self._chain_s_calls = 0
        self._save_c_calls = 0

    # -- helpers ----------------------------------------------------------
    def _owned_rule(self, source: str) -> str:
        return f"-A {CHAIN} -s {source} -d 10.99.0.0/24 -o wg0 -j MASQUERADE"

    def _chain_s_output(self) -> str:
        source = self.owned_source_before if self._chain_s_calls == 0 else self.owned_source_after
        self._chain_s_calls += 1
        return f"-N {CHAIN}\n{self._owned_rule(source)}\n"

    def _counter_output(self) -> str:
        pkts = self.counter_before if self._save_c_calls == 0 else self.counter_after
        self._save_c_calls += 1
        return (
            "*nat\n"
            ":PREROUTING ACCEPT [0:0]\n"
            f":{CHAIN} - [0:0]\n"
            f"[{pkts}:{pkts * 60}] {self._owned_rule('172.18.0.2/32')}\n"
            f"[0:0] -A POSTROUTING -j {CHAIN}\n"
            "COMMIT\n"
        )

    def _full_nat_table(self) -> str:
        lines = [
            "-P POSTROUTING ACCEPT",
            f"-N {CHAIN}",
            f"-A POSTROUTING -j {CHAIN}",
            self._owned_rule("172.18.0.2/32"),
        ]
        if self.broad_nat:
            lines.append("-A POSTROUTING -s 0.0.0.0/0 -j MASQUERADE")
        return "\n".join(lines) + "\n"

    def _pods_json(self) -> str:
        if not self.pods_running:
            return json.dumps({"items": []})
        return json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": "audio-gateway-0", "uid": "pod-uid-1"},
                        "spec": {"nodeName": "k3d-test-server-0"},
                        "status": {"phase": "Running", "podIP": self.pod_ip},
                    }
                ]
            }
        )

    def _nodes_json(self) -> str:
        items = []
        for cidr in self.node_pod_cidrs:
            items.append({"spec": {"podCIDR": cidr, "podCIDRs": [cidr]}})
        return json.dumps({"items": items})

    def _wg_allowed_ips(self) -> str:
        if self.allowed_ips_cover:
            return f"{self.peer_pubkey}\t10.99.0.0/24 10.99.0.2/32\n"
        return "OTHERKEY0000000000000000000000000000000000=\t10.88.0.0/24\n"

    def _wg_handshakes(self) -> str:
        ts = int(time.time()) - 30
        return f"{self.peer_pubkey}\t{ts}\n"

    # -- dispatch ---------------------------------------------------------
    def __call__(self, argv: list[str], timeout: int = 12, env: dict | None = None):
        self.commands.append(argv)
        command, args = self._normalize(argv)

        if command == "wg":
            if args == ["show", "interfaces"]:
                return collector.CommandResult(0, "wg0\n", "")
            if len(args) >= 3 and args[0] == "show" and args[2] == "allowed-ips":
                return collector.CommandResult(0, self._wg_allowed_ips(), "")
            if len(args) >= 3 and args[0] == "show" and args[2] == "latest-handshakes":
                return collector.CommandResult(0, self._wg_handshakes(), "")
            return collector.CommandResult(1, "", "wg-unknown")

        if command == "ip" and args[:2] == ["route", "get"]:
            return collector.CommandResult(0, f"10.99.0.2 dev {self.route_dev} src 10.99.0.1\n", "")

        if command == "docker":
            if args and args[0] == "inspect":
                if self.node_missing:
                    return collector.CommandResult(1, "", "no such object")
                return collector.CommandResult(0, json.dumps(self.node_networks), "")
            if args[:1] == ["exec"]:
                path = args[-1]
                if path == "/etc/rancher/k3s/config.yaml":
                    if self.config_yaml_cidr is None:
                        return collector.CommandResult(1, "", "no config")
                    return collector.CommandResult(
                        0, f"cluster-cidr: {self.config_yaml_cidr}\nservice-cidr: 10.45.0.0/16\n", ""
                    )
                if path == "/proc/1/cmdline":
                    if self.cmdline_cidr is None:
                        return collector.CommandResult(1, "", "no cmdline")
                    cmdline = "\x00".join(
                        ["k3s", "server", f"--cluster-cidr={self.cmdline_cidr}", "--disable=traefik"]
                    )
                    return collector.CommandResult(0, cmdline, "")
            return collector.CommandResult(1, "", "docker-unknown")

        if command == "bash":
            return collector.CommandResult(self.host_rule_check_exit, "", "")

        if command == "kubectl":
            if "exec" in args:
                code = self.nc_queue.pop(0) if self.nc_queue else 0
                return collector.CommandResult(code, "", "")
            if "namespace" in args and "kube-system" in args:
                return collector.CommandResult(0, self.uid, "")
            if "config" in args and "view" in args:
                return collector.CommandResult(0, self.server_url, "")
            if "nodes" in args:
                if self.nodes_unreadable:
                    return collector.CommandResult(1, "", "forbidden")
                return collector.CommandResult(0, self._nodes_json(), "")
            if "pods" in args:
                return collector.CommandResult(0, self._pods_json(), "")
            return collector.CommandResult(1, "", "kubectl-unknown")

        if command in {"iptables", "iptables-nft", "iptables-legacy"}:
            if "-S" in args:
                idx = args.index("-S")
                if idx == len(args) - 1:
                    return collector.CommandResult(0, self._full_nat_table(), "")
                if args[idx + 1] == CHAIN:
                    return collector.CommandResult(0, self._chain_s_output(), "")
            return collector.CommandResult(1, "", "iptables-unknown")

        if command == "iptables-save":
            if "-c" in args:
                return collector.CommandResult(0, self._counter_output(), "")
            return collector.CommandResult(0, self._full_nat_table(), "")

        if command == "systemctl":
            if not self.systemd_healthy:
                return collector.CommandResult(3, "inactive\n", "")
            if args[:1] == ["is-active"]:
                return collector.CommandResult(0, "active\n", "")
            if args[:1] == ["is-enabled"]:
                return collector.CommandResult(0, "enabled\n", "")
            if args[:1] == ["show"]:
                return collector.CommandResult(
                    0,
                    "ActiveState=active\n"
                    "UnitFileState=enabled\n"
                    "ExecStart={ path=/usr/local/sbin/k3d-wg-masq-host-rule }\n"
                    "ExecStop={ path=/usr/local/sbin/k3d-wg-masq-rollback }\n",
                    "",
                )

        return collector.CommandResult(127, "", f"unexpected command: {argv}")

    def _normalize(self, argv: list[str]) -> tuple[str, list[str]]:
        normalized = list(argv)
        if normalized[:2] == ["sudo", "-n"]:
            normalized = normalized[2:]
        if normalized and Path(normalized[0]).name == "nsenter":
            marker = normalized.index("--")
            normalized = normalized[marker + 1 :]
        return Path(normalized[0]).name, normalized[1:]


class WgBplusI6MasqEvidenceCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_runner = collector.run_command
        self.original_hostname = collector.socket.gethostname
        self._tmp = tempfile.TemporaryDirectory()
        self.canonical_script = Path(self._tmp.name) / "k3d-wg-masq-host-rule.sh"
        self.canonical_script.write_text("#!/usr/bin/env bash\necho canonical\n", encoding="utf-8")

    def tearDown(self) -> None:
        collector.run_command = self.original_runner
        collector.socket.gethostname = self.original_hostname
        self._tmp.cleanup()

    def args(self, **overrides) -> SimpleNamespace:
        base = dict(
            output=Path("/tmp/unused.json"),
            kube_context="k3d-test",
            namespace="platform-test",
            cluster_cidr="10.44.0.0/16",
            service_cidr="",
            wg_interface="wg0",
            peer_host="10.99.0.2",
            peer_port=8243,
            wg_node="k3d-test-server-0",
            docker_network="platform-test-net",
            host_rule_script=str(self.canonical_script),
            installed_host_rule_script="",
            probe_attempts=3,
            systemd_unit="k3d-wg-masq.service",
            drift_timer="k3d-wg-masq.timer",
            drift_interval_minutes=5,
            rollback_tested_ref="rollback/k3d-wg-masq-dry-run.json",
            protected_evidence_path="",
            github_run_id="12345",
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def build(self, arg_overrides: dict | None = None, runner_overrides: dict | None = None) -> dict:
        collector.run_command = FakeHostRunner(**(runner_overrides or {}))
        collector.socket.gethostname = lambda: "staging-sw"
        return collector.build_evidence(self.args(**(arg_overrides or {})))

    def checks(self, evidence: dict) -> dict:
        return {item["id"]: item for item in evidence["checks"]}

    def assertCheckFails(self, evidence: dict, check_id: str) -> None:
        self.assertNotEqual("pass", evidence["status"], "evidence.status should not be pass")
        self.assertEqual("fail", self.checks(evidence)[check_id]["status"], f"{check_id} should fail")

    def assertCheckPasses(self, evidence: dict, check_id: str) -> None:
        self.assertEqual("pass", self.checks(evidence)[check_id]["status"], f"{check_id} should pass")

    def run_verifier(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(VERIFIER_PATH), tmp.name],
                text=True,
                capture_output=True,
                check=False,
            )

    # -- positive ---------------------------------------------------------
    def test_healthy_topology_passes_and_verifier_accepts(self):
        evidence = self.build(
            arg_overrides={"protected_evidence_path": "operator://staging-sw/protected/faz24/i6/20260712T060000Z"}
        )

        self.assertEqual("pass", evidence["status"])
        self.assertTrue(all(check["status"] == "pass" for check in evidence["checks"]))
        self.assertEqual(collector.SCHEMA_VERSION, evidence["schemaVersion"])
        self.assertEqual("10.44.0.0/16", evidence["topology"]["clusterCIDR"])
        self.assertEqual(["10.44.0.0/24"], evidence["topology"]["nodePodCIDRs"])
        self.assertEqual(CHAIN, evidence["mechanism"]["ownedNatChain"])
        self.assertEqual(3, evidence["collector"]["counterTraversal"]["counterDelta"])
        self.assertEqual(3, evidence["collector"]["podProbe"]["successCount"])
        self.assertFalse(evidence["redaction"]["rawCommandOutputIncluded"])

        result = self.run_verifier(evidence)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I6 MASQ evidence: PASS", result.stdout)
        self.assertIn("clusterCIDR=10.44.0.0/16", result.stdout)

    # -- belt policy ------------------------------------------------------
    def test_belt_policy_rejects_k3d_test_with_prod_cidr(self):
        evidence = self.build(arg_overrides={"cluster_cidr": "10.42.0.0/16"})
        self.assertCheckFails(evidence, "cluster-identity-bound")
        self.assertFalse(evidence["collector"]["clusterIdentity"]["beltPolicyOk"])

    # -- effective cluster cidr ------------------------------------------
    def test_effective_cidr_wrong_fails(self):
        # configured 10.44 (belt ok) but the node effectively runs 10.42.
        evidence = self.build(
            runner_overrides={"config_yaml_cidr": "10.42.0.0/16", "cmdline_cidr": "10.42.0.0/16"}
        )
        self.assertCheckFails(evidence, "effective-cluster-cidr-matches-config")
        self.assertCheckPasses(evidence, "cluster-identity-bound")

    def test_effective_cidr_source_conflict_fails(self):
        evidence = self.build(
            runner_overrides={"config_yaml_cidr": "10.44.0.0/16", "cmdline_cidr": "10.42.0.0/16"}
        )
        self.assertCheckFails(evidence, "effective-cluster-cidr-matches-config")
        self.assertTrue(evidence["collector"]["effectiveCidr"]["sourcesConflict"])

    # -- node podCIDR containment ----------------------------------------
    def test_node_pod_cidr_outside_cluster_cidr_fails(self):
        evidence = self.build(
            runner_overrides={"node_pod_cidrs": ["10.99.0.0/24"], "pod_ip": "10.99.0.20"}
        )
        self.assertCheckFails(evidence, "node-pod-cidrs-within-cluster-cidr")
        # containment is the failing invariant; identity/effective still pass.
        self.assertCheckPasses(evidence, "cluster-identity-bound")

    # -- host-owned chain authority --------------------------------------
    def test_host_rule_script_missing_fails(self):
        evidence = self.build(arg_overrides={"host_rule_script": str(self.canonical_script) + ".nope"})
        self.assertCheckFails(evidence, "host-owned-chain-authority")
        self.assertFalse(evidence["collector"]["hostOwnedChain"]["scriptFound"])

    def test_host_rule_exit_zero_but_installed_sha_mismatch_fails(self):
        installed = Path(self._tmp.name) / "installed-drifted.sh"
        installed.write_text("#!/usr/bin/env bash\necho DRIFTED\n", encoding="utf-8")
        evidence = self.build(arg_overrides={"installed_host_rule_script": str(installed)})
        self.assertCheckFails(evidence, "host-owned-chain-authority")
        self.assertFalse(evidence["collector"]["hostOwnedChain"]["shaMatches"])

    def test_host_rule_check_nonzero_fails(self):
        evidence = self.build(runner_overrides={"host_rule_check_exit": 1})
        self.assertCheckFails(evidence, "host-owned-chain-authority")

    # -- peer route -------------------------------------------------------
    def test_route_dev_not_wireguard_fails(self):
        evidence = self.build(runner_overrides={"route_dev": "eth0"})
        self.assertCheckFails(evidence, "peer-route-is-wireguard-path")

    def test_allowed_ips_not_covering_peer_fails(self):
        evidence = self.build(runner_overrides={"allowed_ips_cover": False})
        self.assertCheckFails(evidence, "peer-route-is-wireguard-path")

    # -- THE critical regression: counter advances but TCP fails ---------
    def test_counter_advances_but_tcp_fails_is_rejected(self):
        # 0/3 TCP success yet the owned SNAT counter still advanced by 3.
        evidence = self.build(runner_overrides={"nc_exit": [1, 1, 1], "counter_before": 0, "counter_after": 3})
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertCheckFails(evidence, "snat-rule-counter-traversal")
        # prove the counter DID move — the TCP gate is what rejects it.
        self.assertEqual(3, evidence["collector"]["counterTraversal"]["counterDelta"])
        self.assertEqual(0, evidence["collector"]["podProbe"]["successCount"])

    def test_partial_tcp_success_is_rejected(self):
        evidence = self.build(runner_overrides={"nc_exit": [0, 0, 1]})
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertCheckFails(evidence, "snat-rule-counter-traversal")

    # -- counter traversal ------------------------------------------------
    def test_tcp_ok_but_counter_delta_zero_fails(self):
        evidence = self.build(runner_overrides={"counter_before": 3, "counter_after": 3})
        self.assertCheckPasses(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertCheckFails(evidence, "snat-rule-counter-traversal")
        self.assertEqual(0, evidence["collector"]["counterTraversal"]["counterDelta"])

    def test_rule_fingerprint_change_fails(self):
        evidence = self.build(
            runner_overrides={"owned_source_before": "172.18.0.2/32", "owned_source_after": "172.18.0.9/32"}
        )
        self.assertCheckPasses(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertCheckFails(evidence, "snat-rule-counter-traversal")
        self.assertFalse(evidence["collector"]["counterTraversal"]["ruleStable"])

    # -- pod selection ----------------------------------------------------
    def test_pod_not_found_fails(self):
        evidence = self.build(runner_overrides={"pods_running": False})
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertFalse(evidence["collector"]["podProbe"]["podFound"])

    def test_probe_pod_ip_outside_node_cidr_fails(self):
        # node podCIDR valid (check-3 passes), but the only Running pod is outside it.
        evidence = self.build(runner_overrides={"pod_ip": "10.88.0.5"})
        self.assertCheckPasses(evidence, "node-pod-cidrs-within-cluster-cidr")
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertFalse(evidence["collector"]["podProbe"]["podWithinNodeCidr"])

    def test_nc_missing_in_pod_fails(self):
        evidence = self.build(runner_overrides={"nc_exit": [127, 127, 127]})
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertTrue(evidence["collector"]["podProbe"]["ncMissing"])

    def test_zero_probe_attempts_is_not_vacuously_true(self):
        # attempts==0 -> loop runs 0 times; success==attempts==0 must NOT pass.
        evidence = self.build(
            arg_overrides={"probe_attempts": 0}, runner_overrides={"nc_exit": [], "counter_after": 0}
        )
        self.assertCheckFails(evidence, "pod-to-wg-peer-tcp-connect")
        self.assertCheckFails(evidence, "snat-rule-counter-traversal")
        self.assertEqual(0, evidence["collector"]["podProbe"]["successCount"])

    def test_parse_args_enforces_min_probe_attempts(self):
        base = ["--output", "/tmp/x.json", "--cluster-cidr", "10.44.0.0/16"]
        for bad in ("0", "1", "2"):
            with self.assertRaises(SystemExit):
                collector.parse_args(base + ["--probe-attempts", bad])
        for good in ("3", "4"):
            parsed = collector.parse_args(base + ["--probe-attempts", good])
            self.assertEqual(int(good), parsed.probe_attempts)

    # -- broad lan nat ----------------------------------------------------
    def test_broad_lan_nat_detected_fails(self):
        evidence = self.build(runner_overrides={"broad_nat": True})
        self.assertCheckFails(evidence, "no-broad-lan-nat")

    # -- leak guard against collector-shaped evidence --------------------
    def test_forbidden_key_leaked_into_evidence_is_rejected_by_verifier(self):
        evidence = self.build()
        self.assertEqual("pass", evidence["status"])
        evidence["collector"]["podProbe"]["command_output"] = "kubectl exec ... nc -z 10.99.0.2 8243"
        result = self.run_verifier(evidence)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    # -- default protected path (adapted) --------------------------------
    def test_default_protected_path_uses_github_run_id(self):
        evidence_path = collector.protected_evidence_path(self.args())
        self.assertEqual(
            "github-actions://Halildeu/platform-k8s-gitops/actions/runs/12345",
            evidence_path,
        )


if __name__ == "__main__":
    unittest.main()
