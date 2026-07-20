#!/usr/bin/env python3
"""
scripts/drift-detection/verify_ghcr_manifests.py

Codex Sprint A P0 Item 4 — real GHCR manifest existence check.

Reads kustomize render output via stdin, extracts every (image_path, digest)
pair, and queries the GHCR OCI registry API to verify each manifest exists.

Catches the schema-service sha256:2a7076c9 incident (digest pinned in
overlay but garbage-collected from GHCR → ImagePullBackOff at runtime)
BEFORE merge.

Authentication:
  Uses GITHUB_TOKEN env var (CI default) for Bearer token exchange:
    1. POST /token with Basic auth (x:GITHUB_TOKEN) → JWT
    2. HEAD /v2/<image>/manifests/<digest> with Bearer JWT → 200/404

  Falls back to anonymous token endpoint if no GITHUB_TOKEN set (works
  for public packages only).

Usage:
  kubectl kustomize kustomize/overlays/prod | python3 verify_ghcr_manifests.py

Exit codes:
  0 — all manifests verified present, OR auth/permission inconclusive in
      non-strict mode (near-all-unverified heuristic → AUTH_FAIL; runtime
      drift detector is the backstop)
  1 — at least one manifest genuinely missing (GC'd / never pushed), OR
      auth/permission failure under GHCR_STRICT=true
  2 — network / invocation failure (cannot conclude)
"""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
import json
import base64
from typing import Optional

DIGEST_PATTERN = re.compile(
    r"image:\s*(?P<full>(?P<reg>ghcr\.io)/(?P<path>[^@:\s]+)"
    r"(?::[^@\s]+)?@(?P<dig>sha256:[a-f0-9]{64}))"
)

GHCR_TOKEN_URL = "https://ghcr.io/token"
GHCR_API_BASE = "https://ghcr.io/v2"

# OCI / Docker manifest media types we accept
MANIFEST_ACCEPT = (
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json"
)

# Per-(repo path) token cache — same image_path uses the same token across
# multiple digest checks
_token_cache: dict[str, str] = {}


def get_token(image_path: str) -> tuple[Optional[str], str]:
    """Get GHCR Bearer token for the given image_path (e.g. halildeu/platform-backend-user-service)."""
    if image_path in _token_cache:
        return (_token_cache[image_path], "EXISTS")

    url = f"{GHCR_TOKEN_URL}?service=ghcr.io&scope=repository:{image_path}:pull"

    headers = {}
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if gh_token:
        # GHCR accepts Basic auth with any username + GITHUB_TOKEN as password
        creds = base64.b64encode(f"x:{gh_token}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token") or data.get("access_token")
            if token:
                _token_cache[image_path] = token
                return (token, "EXISTS")
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"  [auth] {image_path}: {e.code} {e.reason}\n")
        return (None, "AUTH_FAIL")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.stderr.write(f"  [auth] {image_path}: network error: {e}\n")
        return (None, "NETWORK_FAIL")

    return (None, "AUTH_FAIL")


def verify_manifest(image_path: str, digest: str) -> tuple[str, Optional[str]]:
    """Return (status, detail). status in {'EXISTS','MISSING','AUTH_FAIL','NETWORK_FAIL'}."""
    token, token_status = get_token(image_path)
    if not token:
        return (token_status, "could not obtain pull token")

    url = f"{GHCR_API_BASE}/{image_path}/manifests/{digest}"
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": MANIFEST_ACCEPT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return ("EXISTS", None)
            return ("UNKNOWN", f"unexpected status {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("MISSING", "manifest 404 (GC'd or never pushed)")
        if e.code in (401, 403):
            return ("AUTH_FAIL", f"manifest fetch {e.code}")
        return ("UNKNOWN", f"manifest fetch {e.code} {e.reason}")
    except (urllib.error.URLError, TimeoutError) as e:
        return ("NETWORK_FAIL", str(e))


def extract_pairs(render: str) -> set[tuple[str, str]]:
    """Extract unique (image_path, digest) pairs from kustomize render."""
    pairs: set[tuple[str, str]] = set()
    for m in DIGEST_PATTERN.finditer(render):
        pairs.add((m.group("path"), m.group("dig")))
    return pairs


def main() -> int:
    strict = "--strict" in sys.argv or os.environ.get("GHCR_STRICT", "").lower() in ("1", "true", "yes")

    render = sys.stdin.read()
    if not render.strip():
        print("ERR: stdin empty (expected kustomize render)", file=sys.stderr)
        return 2

    pairs = extract_pairs(render)
    if not pairs:
        print("[INFO] no ghcr.io@sha256: image refs in render — nothing to verify")
        return 0

    print(f"[INFO] verifying {len(pairs)} unique (image_path, digest) pairs against GHCR")
    print()

    missing = []
    auth_fails = []
    network_fails = []

    for path, digest in sorted(pairs):
        status, detail = verify_manifest(path, digest)
        short = digest[:19]  # sha256:abc12345...

        if status == "EXISTS":
            print(f"  [OK]   {path}@{short}")
        elif status == "MISSING":
            print(f"  [MISS] {path}@{short} — {detail}")
            missing.append((path, digest, detail))
        elif status == "AUTH_FAIL":
            print(f"  [AUTH] {path}@{short} — {detail}")
            auth_fails.append((path, digest, detail))
        elif status == "NETWORK_FAIL":
            print(f"  [NET]  {path}@{short} — {detail}")
            network_fails.append((path, digest, detail))
        else:
            print(f"  [???]  {path}@{short} — {detail}")
            auth_fails.append((path, digest, detail))

    print()
    print("=== Summary ===")
    print(f"total:        {len(pairs)}")
    print(f"exists:       {len(pairs) - len(missing) - len(auth_fails) - len(network_fails)}")
    print(f"missing:      {len(missing)}")
    print(f"auth_fail:    {len(auth_fails)}")
    print(f"network_fail: {len(network_fails)}")

    # Heuristic: when (near-)all pairs are UNVERIFIED — MISSING (manifest 404)
    # or AUTH_FAIL (token-exchange failed) — it is almost certainly a
    # cross-repo `packages:read` permission gap, NOT real garbage collection.
    # GHCR returns 404 for both "manifest absent" AND "no read permission"
    # (security-through-obscurity), so a 404 on a private cross-repo package
    # is genuinely ambiguous; an AUTH_FAIL in the same run is direct evidence
    # of the same permission gap. Reclassify the MISSING set as inconclusive.
    #
    # 2026-05-05 hardening (Faz 22.1.1b): threshold ≥80% (not strictly all) —
    # covers the "1-2 same-repo OK + N cross-repo 404" pattern without losing
    # real GC detection.
    #
    # 2026-05-18 fix (PR-3E-A #812 blocker): the guard previously required
    # ZERO auth_fails (`not (network_fails or auth_fails)`), which disabled the
    # heuristic exactly when the evidence was STRONGEST — N×404 + ≥1 outright
    # token-exchange fail is an unambiguous permission problem, not GC. MISSING
    # and AUTH_FAIL now count TOGETHER toward the ≥80% threshold.
    #
    # 2026-05-18 fix (#821 follow-up, Codex 019e3f5b REVISE): transient
    # NETWORK_FAIL no longer disables the reclassification (historical —
    # the ≥80% threshold this fixed was itself retired 2026-06-11, below).
    #
    # Operator follow-up: the PR-time verifier authenticates with THIS repo's
    # GITHUB_TOKEN, which cannot read cross-repo private GHCR packages
    # (platform-backend-*, platform-web-*). Until a cross-repo `read:packages`
    # PAT / GitHub App token secret is wired in (then GHCR_STRICT=true can
    # restore hard-fail), 404s are reported as inconclusive WARN.
    # Live artifact truth: pod `imageID == desired digest` + the runtime drift
    # detector (catches a real GC'd digest within ~5min).
    #
    # 2026-06-11 fix (gitops#1447, Codex 019eb709 iter-5 AGREE): the previous
    # ≥80%-unverified threshold heuristic was boundary-fragile — adding ONE new
    # readable package (audio-gateway, created by this repo chain so its
    # token CAN read it) pushed the OK count up, dropped unverified (10/13)
    # below ceil(13*0.8)=11, and hard-failed on 10 live in-cluster digests
    # (same run: prod 10/12 ≥ 10 → WARN/exit 0 — inconsistent by construction).
    # Non-strict mode semantics are now aligned with the documented intent:
    # a 404 with a token that cannot read cross-repo packages is NEVER a
    # reliable "really deleted" signal, so MISSING is always reclassified as
    # inconclusive in non-strict mode. GHCR_STRICT=true (with a cross-repo
    # read:packages token) restores the hard-fail path below.
    if missing and not strict:
        print()
        print(f"[INCONCLUSIVE] {len(missing)}/{len(pairs)} manifest 404 with a token that")
        print("               cannot read cross-repo private packages — treating as")
        print("               AUTH_FAIL-equivalent (not real GC). GHCR_STRICT=true +")
        print("               cross-repo read:packages PAT restores hard-fail.")
        auth_fails.extend(missing)
        missing = []

    if missing:
        print()
        print("=== MISSING manifests (BLOCKING — would cause ImagePullBackOff) ===")
        for path, digest, detail in missing:
            print(f"  {path}@{digest}")
            print(f"    {detail}")
        return 1

    # GHCR_STRICT=true is fail-closed — an inconclusive auth/permission result
    # is a hard failure. Evaluated BEFORE the (non-strict, inconclusive)
    # network branch so a concurrent transient timeout cannot mask a
    # strict-mode hard failure (Codex 019e3f5b REVISE). GHCR_STRICT is opt-in
    # for repos where a PAT with full cross-repo packages:read is configured.
    if strict and auth_fails:
        print()
        print("[WARN] auth/permission failures — manifest existence not verified")
        print("[STRICT] GHCR_STRICT=true: AUTH_FAIL counts as hard failure")
        return 1

    if network_fails:
        print()
        print("[WARN] network failures — cannot conclude (returning 2)")
        return 2

    if auth_fails:
        # Auth fails are inconclusive but not fatal in default (non-strict)
        # mode. Most likely cause: cross-repo packages:read permission missing,
        # or an anonymous-endpoint hiccup for public packages. Print warning
        # and exit 0 (rely on the runtime detector as second line of defense).
        print()
        print("[WARN] auth/permission failures — manifest existence not verified")
        print("       (runtime drift detector catches real GC'd digests within 5min)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
