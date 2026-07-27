"""Fail-closed guards for the Budget Control TEST source boundary.

Workcube MSSQL and SMB are live ERP sources. Budget Control may read approved
source extracts through separate ingestion work, but this workload must have
only PostgreSQL runtime credentials and must never inherit the dedicated
Workcube MSSQL egress rule.
"""

from pathlib import Path
import ipaddress
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def _documents(relative_path: str) -> list[dict]:
    content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    return [doc for doc in yaml.safe_load_all(content) if isinstance(doc, dict)]


def _named_policy(relative_path: str, name: str) -> dict:
    for document in _documents(relative_path):
        if (
            document.get("kind") == "NetworkPolicy"
            and document.get("metadata", {}).get("name") == name
        ):
            return document
    raise AssertionError(f"NetworkPolicy not found: {name}")


def _ports(policy: dict) -> set[int]:
    ports = set()
    for rule in policy["spec"].get("egress", []):
        for item in rule.get("ports", []):
            value = item["port"]
            if isinstance(value, int) or str(value).isdigit():
                ports.add(int(value))
    return ports


def _selector_matches(selector: dict, labels: dict[str, str]) -> bool:
    if any(
        labels.get(key) != value
        for key, value in selector.get("matchLabels", {}).items()
    ):
        return False
    for expression in selector.get("matchExpressions", []):
        key = expression["key"]
        operator = expression["operator"]
        values = expression.get("values", [])
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and (key not in labels or labels[key] in values):
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
    return True


def _render_test_overlay() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", "kustomize/overlays/test"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [doc for doc in yaml.safe_load_all(rendered) if isinstance(doc, dict)]


def _rule_reaches_external_endpoint(rule: dict, address: str, port: int) -> bool:
    declared_ports = rule.get("ports")
    if declared_ports:
        numeric_ports = {
            int(item["port"])
            for item in declared_ports
            if isinstance(item.get("port"), int)
            or str(item.get("port", "")).isdigit()
        }
        if port not in numeric_ports:
            return False

    peers = rule.get("to")
    if not peers:
        return True

    target = ipaddress.ip_address(address)
    for peer in peers:
        block = peer.get("ipBlock")
        if not block or target not in ipaddress.ip_network(block["cidr"]):
            continue
        excluded = [
            ipaddress.ip_network(cidr)
            for cidr in block.get("except", [])
        ]
        if not any(target in network for network in excluded):
            return True
    return False


def _policy_reaches_external_endpoint(
    policy: dict, address: str, port: int
) -> bool:
    return any(
        _rule_reaches_external_endpoint(rule, address, port)
        for rule in policy["spec"].get("egress", [])
    )


def test_budget_service_uses_common_deny_and_postgres_allow_without_erp_ports():
    deployment = _documents(
        "kustomize/base/apps/budget-service/deployment.yaml"
    )[0]
    labels = deployment["spec"]["template"]["metadata"]["labels"]
    assert labels["app.kubernetes.io/name"] == "budget-service"
    assert labels["app.kubernetes.io/part-of"] == "platform"

    deny = _named_policy(
        "kustomize/base/netpol/default-deny.yaml", "default-deny-egress"
    )
    assert deny["spec"]["podSelector"] == {}
    assert "Egress" in deny["spec"]["policyTypes"]
    assert not deny["spec"].get("egress")

    common_path = "kustomize/base/netpol/allow-egress-dns-and-host.yaml"
    dns = _named_policy(common_path, "allow-egress-dns")
    host = _named_policy(common_path, "allow-egress-host-bridge")
    expected_selector = {
        "matchLabels": {"app.kubernetes.io/part-of": "platform"}
    }
    assert dns["spec"]["podSelector"] == expected_selector
    assert {53} <= _ports(dns)
    assert host["spec"]["podSelector"] == expected_selector
    assert 5432 in _ports(host)
    assert 1433 not in _ports(host)
    assert 445 not in _ports(host)


def test_workcube_mssql_policy_does_not_select_budget_service():
    policy = _named_policy(
        "kustomize/overlays/test/netpol-workcube-mssql.yaml",
        "allow-egress-workcube-mssql",
    )
    expression = next(
        item
        for item in policy["spec"]["podSelector"]["matchExpressions"]
        if item["key"] == "app.kubernetes.io/name"
    )
    assert expression["key"] == "app.kubernetes.io/name"
    assert expression["operator"] == "In"
    assert set(expression["values"]) == {"report-service", "schema-service"}
    assert "budget-service" not in expression["values"]
    assert _ports(policy) == {1433}


def test_no_effective_erp_policy_selects_budget_service():
    budget_labels = {
        "app.kubernetes.io/name": "budget-service",
        "app.kubernetes.io/component": "backend",
        "app.kubernetes.io/part-of": "platform",
    }
    forbidden_endpoints = {
        (address, port)
        for address in ("10.9.193.200", "10.9.193.201")
        for port in (445, 1433)
    }
    violations = []
    for document in _render_test_overlay():
        if document.get("kind") != "NetworkPolicy":
            continue
        if not _selector_matches(
            document["spec"].get("podSelector", {}), budget_labels
        ):
            continue
        for address, port in forbidden_endpoints:
            if _policy_reaches_external_endpoint(document, address, port):
                violations.append(
                    f'{document["metadata"]["name"]}->{address}:{port}'
                )
    assert violations == [], (
        "ERP egress policy selects budget-service: " + ", ".join(violations)
    )


def test_budget_runtime_receives_only_postgres_connection_material():
    deployment = _documents(
        "kustomize/base/apps/budget-service/deployment.yaml"
    )[0]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["envFrom"] == [
        {"configMapRef": {"name": "budget-service-config"}},
        {
            "secretRef": {
                "name": "budget-service-secrets",
                "optional": False,
            }
        },
    ]

    config = _documents("kustomize/base/apps/budget-service/configmap.yaml")[0][
        "data"
    ]
    assert config["BUDGET_DB_URL"].startswith("jdbc:postgresql://")
    serialized_config = yaml.safe_dump(config).lower()
    for forbidden in ("mssql", "sqlserver", "smb", "10.9.193."):
        assert forbidden not in serialized_config

    external_secret = _documents(
        "kustomize/overlays/test/eso/budget-service/externalsecret.yaml"
    )[0]
    secret_keys = {entry["secretKey"] for entry in external_secret["spec"]["data"]}
    remote_properties = {
        entry["remoteRef"]["property"]
        for entry in external_secret["spec"]["data"]
    }
    assert secret_keys == {"BUDGET_DB_USERNAME", "BUDGET_DB_PASSWORD"}
    assert remote_properties == {"db_username", "db_password"}


def test_budget_service_is_test_only_and_prod_remains_deferred():
    test_kustomization = (
        REPO_ROOT / "kustomize/overlays/test/kustomization.yaml"
    ).read_text(encoding="utf-8")
    prod_kustomization = (
        REPO_ROOT / "kustomize/overlays/prod/kustomization.yaml"
    ).read_text(encoding="utf-8")
    resource = "../../base/apps/budget-service"
    assert resource in test_kustomization
    assert resource not in prod_kustomization
