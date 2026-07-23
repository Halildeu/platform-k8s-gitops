#!/usr/bin/env python3
"""Regression guard for the 10.9.10.15 active / 10.9.10.53 standby split."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def render(path: str) -> list[dict]:
    result = subprocess.run(
        ["kustomize", "build", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        document
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict)
    ]


def resources(documents: list[dict], kind: str, name: str) -> list[dict]:
    return [
        document
        for document in documents
        if document.get("kind") == kind
        and document.get("metadata", {}).get("name") == name
    ]


def endpoint_ip(documents: list[dict], name: str) -> str:
    matches = resources(documents, "Endpoints", name)
    assert len(matches) == 1, f"expected one Endpoints/{name}, got {len(matches)}"
    return matches[0]["subsets"][0]["addresses"][0]["ip"]


base = render("kustomize/base")
test = render("kustomize/overlays/test")
prod = render("kustomize/overlays/prod")
bridge = render(
    "kustomize/overlays/test/activation/endpoint-admin-remote-bridge"
)
device_key = render(
    "kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key"
)

for rendered, label in (
    (test, "test"),
    (prod, "prod"),
    (bridge, "bridge"),
    (device_key, "device-key"),
):
    assert "10.9.10.53" not in yaml.safe_dump_all(rendered), (
        f"{label} render still references archive standby"
    )

assert endpoint_ip(base, "minio") == "192.0.2.1"
assert endpoint_ip(base, "redis-streams") == "192.0.2.1"
assert endpoint_ip(base, "postgres") == "192.0.2.1"
assert endpoint_ip(base, "keycloak") == "192.0.2.1"
assert endpoint_ip(base, "vault") == "192.0.2.1"
assert endpoint_ip(test, "minio") == "172.19.0.252"
assert endpoint_ip(test, "redis-streams") == "172.19.0.250"

for name in ("minio", "redis-streams"):
    assert not resources(prod, "Service", name), f"prod must not render Service/{name}"
    assert not resources(
        prod, "Endpoints", name
    ), f"prod must not render Endpoints/{name}"

for rendered, label in ((bridge, "bridge"), (device_key, "device-key")):
    ingress_policies = [
        document
        for document in rendered
        if document.get("kind") == "NetworkPolicy"
        and any(
            port.get("port") == 9444
            for rule in document.get("spec", {}).get("ingress", [])
            for port in rule.get("ports", [])
        )
    ]
    assert ingress_policies, f"{label} ingress policy missing"
    cidrs = {
        source["ipBlock"]["cidr"]
        for policy in ingress_policies
        for rule in policy["spec"]["ingress"]
        for source in rule.get("from", [])
        if "ipBlock" in source
    }
    assert "10.9.10.53/32" not in cidrs, f"{label} still trusts archive standby"
    assert "172.19.0.2/32" in cidrs, f"{label} node-netns forwarder pin missing"

expected_source_fragments = {
    "scripts/drift-detection/check_env_drift.sh": (
        "/srv/platform/gitops/platform-k8s-gitops",
        "self-hosted aiserver runner",
    ),
    "scripts/verify-vault-paths.sh": (
        'SSH_HOST="${VAULT_PATHS_SSH_HOST:-aiadmin@aiserver}"',
        "/srv/platform/secrets/backup-auth/vault-init-prod.json",
    ),
    "scripts/faz22-remote-ops/faz22-6-completion-audit.sh": (
        'SSH_TARGET="${SSH_TARGET:-aiadmin@aiserver}"',
    ),
    "scripts/faz22-remote-ops/faz22-6-a1-preflight.sh": (
        'SSH_TARGET="${SSH_TARGET:-aiadmin@aiserver}"',
        "/srv/platform/stateful/test/vault/tls",
    ),
    "scripts/faz24/reconcile-edge-nginx.sh": (
        'SSH_TARGET="${SSH_TARGET:-aiadmin@aiserver}"',
        'REMOTE_FILE="${EDGE_NGINX_REMOTE_FILE:-/srv/platform/web/nginx/default.conf}"',
    ),
    "scripts/faz24/provision-meeting-intelligence-access.sh": (
        "/srv/platform/secrets/backup-auth/vault-init-prod.json",
        "/srv/platform/secrets/backup-auth/vault-init-test.json",
    ),
    "scripts/faz24/repair-d35-permission-writer-credential.sh": (
        'readonly VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/faz24-live-e2e-smoke.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/d29-smoke.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/d29-smoke-receipt-chain.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/fullats-application-smoke.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/fullats-live-browser-acceptance.sh": (
        'VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/provision-test-keycloak.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ats/provision-test-pg-vault.sh": (
        'VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"',
    ),
    "scripts/ops/graph-mail-list.sh": (
        'SSH_HOST="aiadmin@aiserver"',
        "/srv/platform/secrets/backup-auth/vault-init-prod.json",
    ),
    "scripts/ops/graph-mail-send.sh": (
        'SSH_HOST="aiadmin@aiserver"',
        "/srv/platform/secrets/backup-auth/vault-init-prod.json",
    ),
    "host-compose/preflight-check.sh": (
        'REMOTE="${REMOTE:-aiadmin@aiserver}"',
    ),
    "gha-runner/entrypoint.sh": (
        'RUNNER_NAME="${RUNNER_NAME:-aiserver-testai-deploy}"',
        'RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,aiserver,testai-deploy}"',
    ),
    "gha-runner/docker-compose.yml": (
        "RUNNER_NAME: ${RUNNER_NAME:-aiserver-testai-deploy}",
        "RUNNER_LABELS: ${RUNNER_LABELS:-self-hosted,aiserver,testai-deploy}",
    ),
    "bootstrap/reconnect-compose-to-test-net.sh": (
        'REMOTE="${REMOTE:-aiadmin@aiserver}"',
        "This tool is intentionally read-only",
        "repair host-compose or GitOps source, then sync",
    ),
    "bootstrap/host/aiserver-backup/platform-backup-run": (
        'BACKUP_EXPORT_USER="${BACKUP_EXPORT_USER:-platform-backup-export}"',
        'setfacl -m "u:${BACKUP_EXPORT_USER}:--x"',
    ),
    "bootstrap/host/archive-standby-backup/platform-backup-archive-pull": (
        'SOURCE="${SOURCE:-platform-backup-export@10.9.10.15}"',
        "--ignore-existing",
        "--checksum",
        "--log-file-format='%i|%n'",
        "sha256sum",
    ),
    "bootstrap/host/archive-standby-backup/platform-backup-archive-pull.service": (
        "ConditionPathExists=/etc/aiserver-archive/ARCHIVE_STANDBY",
        "ProtectSystem=strict",
    ),
    "scripts/ops/install-aiserver-backup-replication.sh": (
        'command="/usr/bin/rrsync -ro /srv/platform/backup"',
        "platform-backup-archive-pull.timer",
    ),
}

for relative_path, fragments in expected_source_fragments.items():
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    for fragment in fragments:
        assert fragment in source, f"{relative_path} missing {fragment!r}"

reconnect_source = (
    ROOT / "bootstrap/reconnect-compose-to-test-net.sh"
).read_text(encoding="utf-8")
for forbidden in ("docker network connect", "kubectl patch", "rollout restart"):
    executable_lines = [
        line
        for line in reconnect_source.splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert forbidden not in "\n".join(executable_lines), (
        f"reconnect verifier contains forbidden mutation: {forbidden}"
    )

print("PASS aiserver post-cutover contract")
