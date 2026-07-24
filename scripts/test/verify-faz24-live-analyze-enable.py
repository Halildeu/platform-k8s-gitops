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
BRIDGE_NAME = "meeting-ai-service"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_documents(path: Path) -> list[dict]:
    return [
        doc for doc in yaml.safe_load_all(path.read_text()) if isinstance(doc, dict)
    ]


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


def sync_wave(resource: dict) -> int:
    raw_wave = (
        resource.get("metadata", {})
        .get("annotations", {})
        .get("argocd.argoproj.io/sync-wave", "0")
    )
    try:
        return int(raw_wave)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid ArgoCD sync wave: {raw_wave!r}") from exc


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

    base_configs = [
        doc
        for doc in base_docs
        if doc.get("kind") == "ConfigMap"
        and doc.get("metadata", {}).get("name") == CONFIG_NAME
    ]
    require(
        len(base_configs) == 1,
        f"expected one base ConfigMap/{CONFIG_NAME}; found {len(base_configs)}",
    )
    base_config = base_configs[0]
    base_data = base_config.get("data", {})
    require(
        base_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED") == "false",
        "base live-analyze enable default must be false",
    )
    require(
        base_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL") == "",
        "base live-analyze URL default must be empty",
    )

    test_config = find_exactly_one(test_docs, "ConfigMap", CONFIG_NAME, TEST_NAMESPACE)
    test_data = test_config.get("data", {})
    require(
        test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED") == "true",
        "test live-analyze enable must be true",
    )
    require(
        test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL")
        == "http://meeting-ai-service:8080",
        "test live-analyze URL must use the canonical bridge Service",
    )
    require(
        test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_SEGMENT_WINDOW") == "5",
        "test live-analyze segment window must be 5",
    )
    require(
        test_data.get("AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_TIMEOUT_MS") == "5000",
        "test live-analyze timeout must be 5000ms",
    )
    require(
        test_config.get("metadata", {})
        .get("annotations", {})
        .get("argocd.argoproj.io/sync-wave")
        == "17",
        "test audio-gateway ConfigMap must sync at wave 17",
    )

    deployment = find_exactly_one(
        test_docs, "Deployment", DEPLOYMENT_NAME, TEST_NAMESPACE
    )
    annotations = (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("annotations", {})
    )
    require(
        annotations.get("audio-gateway.acik.com/live-analyze-enable-rev")
        == "2026-07-22-244-enable-v1",
        "audio-gateway pod template must carry the live-analyze rollout revision",
    )
    require(
        deployment.get("metadata", {})
        .get("annotations", {})
        .get("argocd.argoproj.io/sync-wave")
        == "18",
        "audio-gateway Deployment must sync after config and policy at wave 18",
    )

    policy = find_exactly_one(test_docs, "NetworkPolicy", POLICY_NAME, TEST_NAMESPACE)
    expected_policy_spec = {
        "podSelector": {"matchLabels": {"app.kubernetes.io/name": "audio-gateway"}},
        "policyTypes": ["Egress"],
        "egress": [
            {
                "to": [{"ipBlock": {"cidr": "10.99.0.2/32"}}],
                "ports": [
                    {"protocol": "TCP", "port": 8243},
                    {"protocol": "TCP", "port": 8300},
                ],
            }
        ],
    }
    require(
        policy.get("spec") == expected_policy_spec,
        "audio-gateway egress policy must be the exact /32 TCP 8243+8300 contract",
    )
    require(
        policy.get("metadata", {})
        .get("annotations", {})
        .get("argocd.argoproj.io/sync-wave")
        == "17",
        "audio-gateway egress policy must sync at wave 17",
    )

    service = find_exactly_one(test_docs, "Service", BRIDGE_NAME, TEST_NAMESPACE)
    expected_service_spec = {
        "ports": [
            {
                "name": "http",
                "port": 8080,
                "targetPort": 8300,
                "protocol": "TCP",
            }
        ]
    }
    require(
        service.get("spec") == expected_service_spec,
        "meeting-ai bridge Service must be the exact selectorless ClusterIP contract",
    )
    require(
        sync_wave(service) <= 17,
        "meeting-ai bridge Service must sync no later than wave 17",
    )

    endpoints = find_exactly_one(test_docs, "Endpoints", BRIDGE_NAME, TEST_NAMESPACE)
    require(
        endpoints.get("subsets")
        == [
            {
                "addresses": [{"ip": "10.99.0.2"}],
                "ports": [{"name": "http", "port": 8300, "protocol": "TCP"}],
            }
        ],
        "meeting-ai bridge Endpoints must contain only 10.99.0.2:8300/TCP",
    )
    require(
        sync_wave(endpoints) <= 17,
        "meeting-ai bridge Endpoints must sync no later than wave 17",
    )

    assert_absent(prod_docs, "ConfigMap", CONFIG_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "Deployment", DEPLOYMENT_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "NetworkPolicy", POLICY_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "Service", BRIDGE_NAME, PROD_NAMESPACE)
    assert_absent(prod_docs, "Endpoints", BRIDGE_NAME, PROD_NAMESPACE)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"Faz 24 live-analyze render contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
