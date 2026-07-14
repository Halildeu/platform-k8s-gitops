#!/usr/bin/env python3
"""Enforce single Argo ownership for the test notification ExternalSecret."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


TARGET_API_VERSION = "external-secrets.io/v1"
TARGET_KIND = "ExternalSecret"
TARGET_NAMESPACE = "platform-test"
TARGET_NAME = "notification-orchestrator-secrets"


def load_documents(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [doc for doc in yaml.safe_load_all(stream) if isinstance(doc, dict)]


def count_resource(documents: list[dict[str, Any]], *, kind: str) -> int:
    return sum(
        1
        for doc in documents
        if doc.get("apiVersion") == ("v1" if kind == "Secret" else TARGET_API_VERSION)
        and doc.get("kind") == kind
        and doc.get("metadata", {}).get("namespace") == TARGET_NAMESPACE
        and doc.get("metadata", {}).get("name") == TARGET_NAME
    )


def load_application(path: Path) -> dict[str, Any]:
    documents = load_documents(path)
    if len(documents) != 1 or documents[0].get("kind") != "Application":
        raise ValueError(f"{path}: expected exactly one ArgoCD Application")
    return documents[0]


def source_path(application: dict[str, Any]) -> str:
    source = application.get("spec", {}).get("source") or {}
    return str(source.get("path") or "")


def automated_prune(application: dict[str, Any]) -> Any:
    return (
        application.get("spec", {})
        .get("syncPolicy", {})
        .get("automated", {})
        .get("prune")
    )


def has_targeted_ignore(application: dict[str, Any]) -> bool:
    entries = application.get("spec", {}).get("ignoreDifferences") or []
    return any(
        entry.get("group") == "external-secrets.io"
        and entry.get("kind") == TARGET_KIND
        and entry.get("name") == TARGET_NAME
        for entry in entries
        if isinstance(entry, dict)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload-render", type=Path, required=True)
    parser.add_argument("--eso-render", type=Path, required=True)
    parser.add_argument("--workload-application", type=Path, required=True)
    parser.add_argument("--eso-application", type=Path, required=True)
    args = parser.parse_args()

    workload_documents = load_documents(args.workload_render)
    eso_documents = load_documents(args.eso_render)
    workload_application = load_application(args.workload_application)
    eso_application = load_application(args.eso_application)

    checks = {
        "workload_external_secret_count": count_resource(
            workload_documents, kind=TARGET_KIND
        ),
        "eso_external_secret_count": count_resource(eso_documents, kind=TARGET_KIND),
        "workload_bootstrap_secret_count": count_resource(
            workload_documents, kind="Secret"
        ),
        "workload_source_path": source_path(workload_application),
        "eso_source_path": source_path(eso_application),
        "workload_prune": automated_prune(workload_application),
        "eso_prune": automated_prune(eso_application),
        "workload_targeted_ignore": has_targeted_ignore(workload_application),
    }

    expected = {
        "workload_external_secret_count": 0,
        "eso_external_secret_count": 1,
        "workload_bootstrap_secret_count": 0,
        "workload_source_path": "kustomize/overlays/test",
        "eso_source_path": "kustomize/overlays/test/eso",
        "workload_prune": False,
        "eso_prune": False,
        "workload_targeted_ignore": False,
    }
    if checks != expected:
        for name, expected_value in expected.items():
            actual_value = checks.get(name)
            if actual_value != expected_value:
                print(f"FAIL: {name}={actual_value!r}; expected {expected_value!r}")
        return 1

    print(
        "PASS: notification ExternalSecret is rendered only by platform-eso-test; "
        "platform-test renders neither the ExternalSecret nor bootstrap Secret"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
