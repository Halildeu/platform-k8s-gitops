#!/usr/bin/env python3
"""Which runtime services still owe a stability window (gitops#3618).

The post-merge verifier used to run a 2-3 min stability window for all 13
services on every push. Scoping the windows to "what this push changed" is not
enough: a push whose run was superseded mid-way (or failed) never ran its
windows, and the next push's before/after diff no longer lists that service.

The scope is therefore derived from the last *successfully verified* backend
map — the ``expectedDigests`` of the newest successful run's
``testai-backend-acceptance-*`` evidence artifact whose runtime report says
``verdict == "PASS"``. Every service whose current digest differs from that
map (or is absent from it) still owes a window. By induction every service in
a PASS map was verified by that run or an earlier one.

The evidence also names the revision it verified (``effectiveRevision`` of the
convergence report). The workflow compares the verifier contract between that
revision and the current one; a changed contract voids the inheritance and
every service is verified again.

Fail-closed: no usable evidence (no successful run, artifact missing/expired,
unreadable report, no revision), or a push that also changed the verifier
contract, yields an empty list, which the verifier treats as "all services".
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from typing import Callable, Iterable

RUNTIME_REPORT = "testai-backend-runtime-verification.json"
RECONCILE_REPORT = "testai-backend-argocd-auto-sync.json"
# A successful run publishes its evidence as testai-backend-acceptance-<rev>-<run>-<attempt>
# (see the workflow's artifact_kind=acceptance); "diagnostic" only exists on failed runs.
ARTIFACT_PREFIX = "testai-backend-acceptance-"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def changed_services(current: dict[str, str], verified: dict[str, str] | None, contract_changed: bool) -> list[str]:
    """Services owing a stability window; empty means "all" (fail-closed)."""
    if contract_changed or verified is None:
        return []
    return sorted(service for service, digest in current.items() if verified.get(service) != digest)


def verified_map_from_report(report: dict) -> dict[str, str] | None:
    if report.get("schemaVersion") != "testai-backend-runtime-verification-v1":
        return None
    if report.get("verdict") != "PASS":
        return None
    digests = report.get("expectedDigests")
    if not isinstance(digests, dict) or not digests:
        return None
    if not all(isinstance(k, str) and isinstance(v, str) and v.startswith("sha256:") for k, v in digests.items()):
        return None
    return dict(digests)


def verified_revision_from_report(report: dict) -> str | None:
    """The revision the convergence report certifies (must be a full sha)."""
    if report.get("verdict") != "PASS":
        return None
    revision = report.get("effectiveRevision")
    return revision if isinstance(revision, str) and SHA_RE.match(revision) else None


def latest_verified(
    fetch_json: Callable[[str], dict],
    fetch_bytes: Callable[[str], bytes],
    repo: str,
    workflow_file: str,
    max_runs: int = 30,
) -> tuple[dict[str, str], str] | None:
    """Walk successful runs newest-first; return (PASS map, verified revision)."""
    runs = fetch_json(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/runs"
        f"?status=success&branch=main&per_page={max_runs}"
    ).get("workflow_runs", [])
    for run in runs:
        artifacts = fetch_json(run["artifacts_url"] + "?per_page=20").get("artifacts", [])
        for artifact in artifacts:
            if not str(artifact.get("name", "")).startswith(ARTIFACT_PREFIX) or artifact.get("expired"):
                continue
            try:
                payload = fetch_bytes(artifact["archive_download_url"])
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    names = set(archive.namelist())
                    if RUNTIME_REPORT not in names or RECONCILE_REPORT not in names:
                        continue
                    runtime = json.loads(archive.read(RUNTIME_REPORT))
                    reconcile = json.loads(archive.read(RECONCILE_REPORT))
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
            verified = verified_map_from_report(runtime)
            revision = verified_revision_from_report(reconcile)
            if verified is not None and revision is not None:
                return verified, revision
    return None


def build_request(url: str, token: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    """Authorization is an *unredirected* header: the artifact download answers
    with a redirect to a signed storage URL on another origin, and the token
    must not travel there (Codex 01a08891)."""
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "testai-last-verified-map",
    })
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def _github(token: str) -> tuple[Callable[[str], dict], Callable[[str], bytes]]:
    def request(url: str) -> bytes:
        with urllib.request.urlopen(build_request(url, token), timeout=30) as resp:  # noqa: S310 - api.github.com
            return resp.read()

    def fetch_json(url: str) -> dict:
        return json.loads(request(url))

    def fetch_bytes(url: str) -> bytes:
        return request(url)

    return fetch_json, fetch_bytes


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--current-map", required=True, help="JSON object service -> sha256 digest")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--workflow-file", default="verify-testai-backend-rollout.yml")
    parser.add_argument("--contract-changed", choices=("true", "false"), default="false",
                        help="the push itself changed the verifier contract: verify every service")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--out-json", help="also write {changed_services, verified_revision, verified_map} here")
    args = parser.parse_args(list(argv) if argv is not None else None)

    current = json.loads(args.current_map)
    if not isinstance(current, dict):
        print("current map must be a JSON object", file=sys.stderr)
        return 2
    verified: dict[str, str] | None = None
    revision: str | None = None
    if args.contract_changed == "false":
        token = os.environ.get(args.token_env, "")
        if token:
            fetch_json, fetch_bytes = _github(token)
            try:
                found = latest_verified(fetch_json, fetch_bytes, args.repo, args.workflow_file)
            except (OSError, ValueError) as exc:
                print(f"last verified map unavailable ({exc.__class__.__name__}: {exc}); verifying every service", file=sys.stderr)
                found = None
            if found is not None:
                verified, revision = found
        else:
            print("no token; verifying every service", file=sys.stderr)
    services = changed_services(current, verified, args.contract_changed == "true")
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump({"changed_services": services, "verified_revision": revision, "verified_map": verified}, fh)
    print(" ".join(services))
    return 0


if __name__ == "__main__":
    sys.exit(main())
