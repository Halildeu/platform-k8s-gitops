#!/usr/bin/env python3
"""
Endpoint-admin rendered pod-template label guard.

The 2026-05-11 recovery found endpoint-admin-service unable to resolve DNS
because NetworkPolicy default-deny did not select the pod: the live pod template
missed `app.kubernetes.io/part-of=platform`.

This gate checks the rendered kustomize output, not only raw deployment YAML,
because label transformers are part of the desired-state contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


REQUIRED_TEMPLATE_LABELS: dict[str, str] = {
    "app.kubernetes.io/name": "endpoint-admin-service",
    "app.kubernetes.io/part-of": "platform",
}


@dataclass
class RenderCheck:
    source: str
    passed: bool
    message: str
    labels: dict[str, str]
    missing: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check endpoint-admin-service rendered pod-template labels",
    )
    parser.add_argument(
        "--kustomize-path",
        action="append",
        default=[],
        help="Kustomize path to render. Can be repeated.",
    )
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent.parent),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def default_paths(repo_root: Path) -> list[str]:
    candidates = [
        "kustomize/base/apps/endpoint-admin-service",
        "kustomize/overlays/test",
    ]
    return [candidate for candidate in candidates if (repo_root / candidate).exists()]


def render(repo_root: Path, source: str, kubectl_bin: str) -> tuple[str | None, str | None]:
    if not shutil.which(kubectl_bin):
        return None, f"kubectl binary not found: {kubectl_bin}"
    target = repo_root / source
    if not target.exists():
        return None, f"kustomize path not found: {target}"
    try:
        proc = subprocess.run(
            [kubectl_bin, "kustomize", str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout, None
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() or exc.stdout.strip()
        return None, f"kubectl kustomize failed for {source}: {err[:500]}"


def find_deployment(rendered_yaml: str) -> dict[str, Any] | None:
    for doc in yaml.safe_load_all(rendered_yaml):
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "Deployment":
            continue
        metadata = doc.get("metadata", {})
        if metadata.get("name") == "endpoint-admin-service":
            return doc
    return None


def check_source(repo_root: Path, source: str, kubectl_bin: str) -> RenderCheck:
    rendered, error = render(repo_root, source, kubectl_bin)
    if error is not None:
        return RenderCheck(source, False, error, {}, REQUIRED_TEMPLATE_LABELS.copy())
    assert rendered is not None

    deployment = find_deployment(rendered)
    if deployment is None:
        return RenderCheck(
            source,
            False,
            "endpoint-admin-service Deployment not found in rendered output",
            {},
            REQUIRED_TEMPLATE_LABELS.copy(),
        )

    labels = (
        deployment
        .get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("labels", {})
    )
    if not isinstance(labels, dict):
        labels = {}

    actual = {str(key): str(value) for key, value in labels.items()}
    missing = {
        key: expected for key, expected in REQUIRED_TEMPLATE_LABELS.items()
        if actual.get(key) != expected
    }
    if missing:
        return RenderCheck(
            source,
            False,
            f"missing or mismatched {len(missing)} required pod-template label(s)",
            actual,
            missing,
        )
    return RenderCheck(
        source,
        True,
        "required pod-template labels are present",
        actual,
        {},
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    sources = args.kustomize_path or default_paths(repo_root)
    if not sources:
        print("no kustomize paths found", file=sys.stderr)
        return 2

    checks = [check_source(repo_root, source, args.kubectl_bin) for source in sources]
    overall_pass = all(check.passed for check in checks)

    if args.json:
        print(json.dumps({
            "check": "endpoint-admin-template-labels",
            "overall": "PASS" if overall_pass else "FAIL",
            "required": REQUIRED_TEMPLATE_LABELS,
            "results": [check.to_dict() for check in checks],
        }, indent=2, ensure_ascii=False))
    else:
        print("Endpoint-admin rendered pod-template label guard")
        for check in checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"[{status}] {check.source}: {check.message}")
            if check.missing:
                for key, expected in check.missing.items():
                    print(f"  - expected {key}={expected}, got {check.labels.get(key)}")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
