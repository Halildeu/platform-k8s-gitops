#!/usr/bin/env python3
"""Produce D30 child evidence from a digest-verified live snapshot artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import view_only_viewer_source_common as common


def produce(client: object, repository: str, browser_run_id: int, head_sha: str) -> dict:
    browser = common.fetch_browser_child(client, repository, browser_run_id, head_sha)
    files = common.fetch_runtime_snapshots(client, repository, browser_run_id, head_sha)
    raw = files["snapshots/d30-snapshot.json"]
    snapshot = common.VERIFIER.load_json_bytes(raw, "d30-snapshot.json")
    if set(snapshot) != {"schemaVersion", "capturedAt", "images"}:
        raise common.VERIFIER.EvidenceError("D30 snapshot field set mismatch")
    if snapshot["schemaVersion"] != "faz22.6-viewer-d30-raw-v2":
        raise common.VERIFIER.EvidenceError("D30 snapshot schema mismatch")
    common.VERIFIER.parse_utc(snapshot["capturedAt"], "D30 capturedAt")
    images = snapshot["images"]
    if not isinstance(images, list) or len(images) != 2:
        raise common.VERIFIER.EvidenceError("D30 snapshot must contain two images")
    expected_deployments = {"backend": "endpoint-admin-remote-bridge-device-key", "web": "frontend"}
    payload_images = []
    seen = set()
    for image in images:
        if not isinstance(image, dict) or set(image) != {
            "component", "deployment", "desiredImage", "liveImageId", "runtimeBinding"
        }:
            raise common.VERIFIER.EvidenceError("D30 image field set mismatch")
        component = image["component"]
        if component in seen or expected_deployments.get(component) != image["deployment"]:
            raise common.VERIFIER.EvidenceError("D30 component or deployment mismatch")
        seen.add(component)
        desired = common.image_digest(image["desiredImage"], f"{component} desired image")
        live = common.image_digest(image["liveImageId"], f"{component} live imageID")
        runtime_binding = image["runtimeBinding"]
        verification_mode = "direct-imageid-digest-v1"
        runtime_content_id = None
        if desired == live:
            if runtime_binding is not None:
                raise common.VERIFIER.EvidenceError(
                    f"D30 {component} direct digest match must not carry a runtime binding"
                )
        else:
            if component != "web" or not isinstance(runtime_binding, dict) or set(runtime_binding) != {
                "kind", "expectedRepoDigest", "observedRepoDigest", "contentId"
            }:
                raise common.VERIFIER.EvidenceError(
                    f"D30 {component} desired/live digest mismatch is not CRI-bound"
                )
            expected_ref = f"ghcr.io/halildeu/platform-web-frontend-testai@{desired}"
            observed_ref = image["liveImageId"].removeprefix("docker-pullable://")
            if runtime_binding["kind"] != "cri-repo-digest-alias-v1":
                raise common.VERIFIER.EvidenceError("D30 web runtime binding kind mismatch")
            if runtime_binding["expectedRepoDigest"] != expected_ref:
                raise common.VERIFIER.EvidenceError("D30 web expected repository digest mismatch")
            if runtime_binding["observedRepoDigest"] != observed_ref:
                raise common.VERIFIER.EvidenceError("D30 web observed repository digest mismatch")
            runtime_content_id = runtime_binding["contentId"]
            if not isinstance(runtime_content_id, str) or not common.VERIFIER.SHA256.fullmatch(
                runtime_content_id
            ):
                raise common.VERIFIER.EvidenceError("D30 web runtime content ID is invalid")
            verification_mode = "cri-repo-digest-alias-v1"
        payload_images.append({
            "component": component,
            "desiredDigest": desired,
            "liveImageIdDigest": live,
            "verificationMode": verification_mode,
            "runtimeContentId": runtime_content_id,
        })
    if seen != set(expected_deployments):
        raise common.VERIFIER.EvidenceError("D30 component set mismatch")
    return common.child(
        "d30", "d30-verifier",
        "scripts/faz22-remote-ops/produce-view-only-viewer-d30-evidence.py",
        head_sha, snapshot["capturedAt"], browser["binding"],
        {"images": sorted(payload_images, key=lambda item: item["component"]),
         "snapshotSha256": common.VERIFIER.digest_bytes(raw)},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--browser-run-id", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = produce(
            common.VERIFIER.GitHubClient(os.environ.get("GITHUB_TOKEN", "")),
            args.repository, args.browser_run_id, args.head_sha,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (common.VERIFIER.EvidenceError, OSError, ValueError) as exc:
        print(f"d30_evidence=fail reason={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
