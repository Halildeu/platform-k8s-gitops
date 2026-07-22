from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "helm-values/kube-prometheus-stack/values-prod.yaml"
EXPECTED_RECIPIENT = "ai@acik.com"
RETIRED_RECIPIENT = "notify-ops@acik.com"


def _alertmanager_config() -> dict:
    values = yaml.safe_load(VALUES.read_text(encoding="utf-8"))
    return values["alertmanager"]["config"]


def test_d43_prod_email_config_targets_operator_and_configures_recovery() -> None:
    config = _alertmanager_config()
    receiver = next(
        item for item in config["receivers"] if item["name"] == "direct-fallback"
    )
    email_configs = receiver["email_configs"]

    assert len(email_configs) == 1
    assert email_configs[0]["to"] == EXPECTED_RECIPIENT
    assert email_configs[0]["send_resolved"] is True
    assert email_configs[0]["require_tls"] is True
    assert RETIRED_RECIPIENT not in VALUES.read_text(encoding="utf-8")


def test_d43_prod_route_preserves_bridge_source_contract() -> None:
    config = _alertmanager_config()
    routes = config["route"]["routes"]
    d43_index = next(
        index
        for index, item in enumerate(routes)
        if item.get("receiver") == "direct-fallback"
    )
    route = routes[d43_index]
    bridge_index = next(
        index
        for index, item in enumerate(routes)
        if item.get("receiver") == "alarm-receiver-bridge"
        and item.get("matchers") == ['severity = "critical"']
    )
    bridge_receiver = next(
        item
        for item in config["receivers"]
        if item["name"] == "alarm-receiver-bridge"
    )

    assert route["matchers"] == [
        'alertname =~ "NotifyServiceDown|NotifyServiceAbsent"'
    ]
    assert route["continue"] is True
    assert d43_index < bridge_index
    assert bridge_receiver["webhook_configs"][0]["send_resolved"] is True
