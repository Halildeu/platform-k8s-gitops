#!/usr/bin/env python3
"""Fail a PR that pins an image digest the registry cannot serve.

Why this exists (2026-07-24, two outages in one day)
----------------------------------------------------
Both incidents had the same shape: a digest that looked valid everywhere a
human would check -- it appeared in the build log as
``pushing manifest for ...@sha256:...``, its commit was on ``main``, and the
package name matched the service -- but the cluster could not pull it. The
Deployment went ``ImagePullBackOff``, Endpoints emptied, and the service was
down until someone noticed.

  * ``auth-service``  -- 106 minutes down (#2863)
  * ``user-service``  -- down until rolled back (#2874 -> #2875)

The check missing in both cases is the only one that settles it before a pin
lands: *can this digest be retrieved from the registry at all?* Name binding,
lineage, and a green build do not answer that. This guard asks the registry.

The instrument validates itself first
-------------------------------------
GHCR answers an unauthorized manifest lookup with **404**, the same status it
uses for a digest that genuinely does not exist. A checker that reads that 404
as "absent" would fail honest PRs the moment its credential lapsed -- the exact
mistake this repo just spent a day unwinding, where a SEV1 alert fired
continuously about a metric endpoint it was never able to reach.

So before judging any new digest, the guard probes a **control** for the same
package: a digest already pinned on the base ref, i.e. one that is deployed and
therefore known to exist.

  control 200  -> the credential can read this package. A 404 on a new digest
                  then means absent, and the guard fails the PR.
  control 404  -> the credential cannot read this package. The guard reports
                  INCONCLUSIVE and does not fail: it has no basis for a verdict
                  and says so, rather than inventing one.

Scope -- what a PASS does and does not prove
--------------------------------------------
PROVES  the registry serves this digest to CI's credential. Catches
        transcription slips, a digest lifted from the wrong package, an image
        garbage-collected or never actually pushed, and a build-log manifest
        line that was never a retrievable reference.

DOES NOT PROVE the *cluster* can pull it. CI and the cluster authenticate as
        different identities (CI: ``GHCR_TOKEN``/``GITHUB_TOKEN``; cluster: the
        ``ghcr-pull`` imagePullSecret sourced from ``kv/gitops/ghcr-token``). A
        credential that has lapsed on the cluster side yields the 403 behind
        #2876 while CI still succeeds. For that class, run the pull-probe this
        script prints -- see docs/operations/RUNBOOKS/RB-image-digest-promotion.md.

Coverage, stated so nobody has to infer it
------------------------------------------
Both shapes a digest reaches the cluster in are read: the ``images:``
transformer list in an overlay ``kustomization.yaml``, and an ``image:``
reference pinned straight into a pod spec (CronJobs, activation overlays,
lab-deps). Out of scope, deliberately: ``newTag`` pins, which are a mutable-tag
problem rather than an unretrievable-digest one, and registries other than
GHCR -- Docker Hub images such as ``curlimages/curl`` and ``node`` are pinned by
digest here but are public upstream and not what took a service down.

Usage
-----
    check_overlay_digest_pullable.py --base-ref origin/main [--head-ref HEAD]
    check_overlay_digest_pullable.py --all --control-from origin/main

Exit codes: 0 verified or inconclusive | 1 digest proven unretrievable | 2 usage.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs PyYAML==6.0.3
    sys.stderr.write("ERROR: PyYAML required (pip install PyYAML==6.0.3)\n")
    raise SystemExit(2)

REGISTRY = "ghcr.io"

# Digests reach the cluster two ways, and a guard that watched only the first
# would have a silent hole: CronJobs, activation overlays and lab-deps pin
# `image: ghcr.io/...@sha256:...` straight in the pod spec.
OVERLAY_GLOBS = ("kustomize/overlays/**/*.yaml",)

INLINE_IMAGE_RE = re.compile(
    r"""image:\s*["']?(?P<repo>"""
    + re.escape(REGISTRY)
    + r"""/[^"'\s@]+)@(?P<digest>sha256:[0-9a-f]{64})""",
    re.MULTILINE,
)

MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)

HTTP_TIMEOUT = 20


@dataclass(frozen=True)
class Pin:
    """One ``images:`` entry that pins a digest."""

    path: str
    name: str
    repo: str  # e.g. halildeu/platform-backend-user-service
    digest: str

    @property
    def reference(self) -> str:
        return f"{REGISTRY}/{self.repo}@{self.digest}"


# --------------------------------------------------------------------------- #
# Reading pins out of the overlays
# --------------------------------------------------------------------------- #


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _inline_pins(text: str, path: str) -> list[Pin]:
    """Digests written directly into a pod spec (`image: ghcr.io/x@sha256:...`)."""
    return [
        Pin(
            path=path,
            name=match.group("repo").rsplit("/", 1)[-1],
            repo=match.group("repo")[len(REGISTRY) + 1 :],
            digest=match.group("digest"),
        )
        for match in INLINE_IMAGE_RE.finditer(text)
    ]


def parse_pins(text: str, path: str) -> list[Pin]:
    """Extract every digest-pinned image reference from one overlay document."""
    pins: list[Pin] = list(_inline_pins(text, path))
    if not path.endswith("kustomization.yaml"):
        return pins  # only kustomizations carry an `images:` transformer list
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: {path} is not parseable YAML: {exc}")
    if not isinstance(doc, dict):
        return pins
    for entry in doc.get("images") or []:
        if not isinstance(entry, dict):
            continue
        digest = entry.get("digest")
        if not digest:
            continue  # newTag pins are a separate (mutable-tag) concern
        new_name = entry.get("newName") or entry.get("name") or ""
        if not new_name.startswith(f"{REGISTRY}/"):
            continue  # only this registry is in scope
        pins.append(
            Pin(
                path=path,
                name=str(entry.get("name", "")),
                repo=new_name[len(REGISTRY) + 1 :],
                digest=str(digest),
            )
        )
    return pins


def _overlay_files() -> list[str]:
    files: list[str] = []
    for pattern in OVERLAY_GLOBS:
        files.extend(str(p) for p in sorted(Path().glob(pattern)))
    return files


def pins_at(ref: str, path: str) -> list[Pin]:
    """Pins as they exist at ``ref``; empty if the file is absent there."""
    if ref == "HEAD" and Path(path).exists():
        return parse_pins(Path(path).read_text(encoding="utf-8"), path)
    code, out = _run(["git", "show", f"{ref}:{path}"])
    return parse_pins(out, path) if code == 0 else []


def collect_changed_pins(base_ref: str, head_ref: str) -> list[Pin]:
    """Pins introduced or modified between base and head."""
    changed: list[Pin] = []
    for path in _overlay_files():
        head = pins_at(head_ref, path)
        if not head:
            continue
        before = {(p.repo, p.digest) for p in pins_at(base_ref, path)}
        changed.extend(p for p in head if (p.repo, p.digest) not in before)
    return changed


def collect_all_pins() -> list[Pin]:
    pins: list[Pin] = []
    for path in _overlay_files():
        pins.extend(parse_pins(Path(path).read_text(encoding="utf-8"), path))
    return pins


def controls_at(ref: str) -> dict[str, str]:
    """One known-good digest per package, taken from ``ref`` (already deployed)."""
    controls: dict[str, str] = {}
    for path in _overlay_files():
        for pin in pins_at(ref, path):
            controls.setdefault(pin.repo, pin.digest)
    return controls


# --------------------------------------------------------------------------- #
# Asking the registry
# --------------------------------------------------------------------------- #


def _registry_token(repo: str, credential: str | None) -> str | None:
    url = f"https://{REGISTRY}/token?service={REGISTRY}&scope=repository:{repo}:pull"
    request = urllib.request.Request(url)
    if credential:
        basic = base64.b64encode(f"x-access-token:{credential}".encode()).decode()
        request.add_header("Authorization", f"Basic {basic}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode())
        return payload.get("token") or payload.get("access_token")
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def probe(repo: str, reference: str, credential: str | None) -> tuple[int | None, str]:
    """HEAD a manifest. Returns (status, detail); status None means no answer."""
    token = _registry_token(repo, credential)
    request = urllib.request.Request(
        f"https://{REGISTRY}/v2/{repo}/manifests/{reference}", method="HEAD"
    )
    request.add_header("Accept", MANIFEST_ACCEPT)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return exc.code, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return None, f"registry unreachable: {exc}"


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-ref", help="compare against this ref (e.g. origin/main)")
    parser.add_argument("--head-ref", default="HEAD", help="ref holding the new pins")
    parser.add_argument("--all", action="store_true", help="check every pinned digest")
    parser.add_argument(
        "--control-from",
        help="ref supplying per-package control digests (default: --base-ref)",
    )
    args = parser.parse_args()

    if not args.all and not args.base_ref:
        parser.error("pass --base-ref <ref> or --all")

    control_ref = args.control_from or args.base_ref
    pins = (
        collect_all_pins()
        if args.all
        else collect_changed_pins(args.base_ref, args.head_ref)
    )

    if not pins:
        print("No new or changed digest pins in this diff — nothing to verify.")
        return 0

    credential = os.environ.get("GHCR_TOKEN") or os.environ.get("GITHUB_TOKEN")
    controls = controls_at(control_ref) if control_ref else {}
    print(
        f"Verifying {len(pins)} pinned digest(s) against {REGISTRY} "
        f"({'authenticated' if credential else 'anonymous'})\n"
    )

    # A package is "readable" only if a control digest for it answers 200.
    readable: dict[str, bool] = {}
    for repo in sorted({p.repo for p in pins}):
        control = controls.get(repo)
        if not control:
            readable[repo] = False
            print(f"  control  {repo}: none on {control_ref} — cannot self-validate")
            continue
        status, detail = probe(repo, control, credential)
        readable[repo] = status == 200
        verdict = "readable" if status == 200 else "NOT readable"
        print(f"  control  {repo}: {verdict} ({detail[:72]})")
    print()

    failures: list[tuple[Pin, str]] = []
    inconclusive: list[Pin] = []
    for pin in pins:
        if not readable[pin.repo]:
            inconclusive.append(pin)
            print(f"  SKIP  {pin.repo}@{pin.digest[:19]}…  (package not readable here)")
            continue
        status, detail = probe(pin.repo, pin.digest, credential)
        if status == 200:
            print(f"  PASS  {pin.repo}@{pin.digest[:19]}…  ({detail})")
        else:
            reason = (
                "digest is not in the registry"
                if status == 404
                else f"registry answered {detail}"
            )
            print(f"  FAIL  {pin.repo}@{pin.digest[:19]}…  ({reason})")
            failures.append((pin, reason))
    print()

    if failures:
        print("UNRETRIEVABLE DIGEST — this pin would take the service down on apply.\n")
        for pin, reason in failures:
            print(f"  {pin.path}")
            print(f"    image:  {pin.name}")
            print(f"    ref:    {pin.reference}")
            print(f"    reason: {reason}\n")
        print(
            "Do not merge. Capture the digest by pulling the image (see\n"
            "docs/operations/RUNBOOKS/RB-image-digest-promotion.md) rather than\n"
            "copying it from a build log — a build log records what the builder\n"
            "pushed, not what the registry will serve back."
        )
        return 1

    if inconclusive:
        print("=" * 72)
        print("INCONCLUSIVE — the guard could not read these packages, so it makes")
        print("no claim about them. It is not reporting them as good.\n")
        for pin in sorted({p.repo for p in inconclusive}):
            print(f"  {pin}")
        print(
            "\nGHCR answers an unauthorized manifest lookup with 404, indistinguishable\n"
            "from a missing digest, so a verdict here would be a guess. Give CI a\n"
            "credential with read:packages (GHCR_TOKEN secret) and this guard starts\n"
            "enforcing on its own — no code change needed.\n"
        )
        print("Until then, verify by pull-probing on the cluster:")
        for pin in inconclusive:
            print(
                f"  kubectl -n platform-test run digest-probe --restart=Never "
                f"--image={pin.reference} --command -- sleep 20"
            )
        print("=" * 72)
        return 0

    print("All new digests are retrievable from the registry.\n")
    print(
        "Note: this proves the REGISTRY serves these digests to CI. It does not\n"
        "prove the cluster's ghcr-pull credential can pull them (#2876). Before\n"
        "applying, probe on the cluster:\n"
    )
    for pin in pins:
        print(
            f"  kubectl -n platform-test run digest-probe --restart=Never "
            f"--image={pin.reference} --command -- sleep 20"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
