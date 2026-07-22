#!/usr/bin/env python3
"""Verify the Faz 24 live-analysis test-only render contract."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


TEST_NAMESPACE = "platform-test"
PROD_NAMESPACE = "platform-prod"
CONFIG_NAME = "audio-gateway-config"
DEPLOYMENT_NAME = "audio-gateway"
POLICY_NAME = "allow-audio-gateway-egress-live-stt-mtls"


def load_documents(path: Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if isinstance(doc, dict)]


def find_exactly_one(
    documents: list[dict], kind: str, name: str, namespace: str
) -> dict:
    matches = [
        doc
        for doc in documents
        if doc.get("kind") == kind
        and doc.get("metadata", {}).get("name") == name
        and doc.get("metadata", {}).get("namespace") == namespace
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one {kind}/{namespace}/{name}; found {len(matches)}"
        )
    return matches[0]


def assert_absent(documents: list[dict], kind: str, name: str, namespace: str) -> None:
    matches = [
        doc
        for doc in documents
        if doc.get("kind") == kind
        and doc.get("metadata", {}).get("name") == name
        and doc.get("metadata", {}).get("namespace") == namespace
    ]
    if matches:
        raise AssertionError(f"unexpected {kind}/{namespace}/{name} in prod render")


def has_egress_port(policy: dict, cidr: str, port: int) -> bool:
    for rule in policy.get("spec", {}).get("egress", []):
        peers = rule.get("to", [])
        ports = rule.get("ports", [])
        peer_matches = any(peer.get("ipBlock", {}).get("cidr") == cidr for peer in peers)
        port_matches = any(
            item.get("protocol", "TCP") == "TCP" and item.get("port") == port
            for item in ports
        )
        if peer_matches and port_matches:
            return True
    return False


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: verify-faz24-live-analyze-enable.py TEST_RENDER PROD_RENDER BASE_CONFIG",
            file=sys.stderr,
        )
        return 2

    test_docs = load_documents(Path(sys.argv[1]))
    prod_docs = load_documents(Path(sys.argv[2]))
    base_docs = load_documents(Path(sys.argv[3]))

    base_config = next(
        (
            doc
            for doc in base_docs
            if doc.get("kind") == "ConfigMap"
            and doc.get("metadata", {}).get("name") == CONFIG_NAME
        ),
        None,
    )
    if base_config is None:
        raise AssertionError(f"missing base ConfigMap/{CONFIG_NAME}")
    base_data = base_config.get("data", {})
    assert base_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED") == "false"
    assert base_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL") == ""

    test_config = find_exactly_one(test_docs, "ConfigMap", CONFIG_NAME, TEST_NAMESPACE)
    test_data = test_config.get("data", {})
    assert test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED") == "true"
    assert (
        test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL")
        == "http://meeting-ai-service:8080"
    )
    assert test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_SEGMENT_WINDOW") == "5"
    assert test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_TIMEOUT_MS") == "5000"

    deployment = find_exactly_one(
        test_docs, "Deployment", DEPLOYMENT_NAME, TEST_NAMESPACE
    )
    annotations = (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("annotations", {})
    )
    assert (
        annotations.get("audio-gateway.acik.com/live-analyze-enable-rev")
        == "2026-07-22-244-enable-v1"
    )

    policy = find_exactly_one(test_docs, "NetworkPolicy", POLICY_NAME, TEST_NAMESPACE)
    assert policy.get("spec", {}).get("podSelector", {}).get("matchLabels", {}).get(
        "app.kubernetes.io/name"
    ) == "audio-gateway"
    assert has_egress_port(policy, "10.99.0.2/32", 8243)
    assert has_egress_port(policy, "10.99.0.2/32", 8300)

    assert_absent(prod_docs, "ConfigMap", CONFIG_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "Deployment", DEPLOYMENT_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "NetworkPolicy", POLICY_NAME, PROD_NAMESPACE)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"Faz 24 live-analyze render contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
