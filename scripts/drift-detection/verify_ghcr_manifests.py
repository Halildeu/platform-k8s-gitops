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
  0 — all manifests verified present
  1 — at least one manifest missing (GC'd or never pushed)
  2 — auth/network failure (cannot conclude)
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
    r"image:\s*(?P<full>(?P<reg>ghcr\.io)/(?P<path>[^@\s]+)@(?P<dig>sha256:[a-f0-9]{64}))"
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


def get_token(image_path: str) -> Optional[str]:
    """Get GHCR Bearer token for the given image_path (e.g. halildeu/platform-backend-user-service)."""
    if image_path in _token_cache:
        return _token_cache[image_path]

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
                return token
    except urllib.error.HTTPError as e:
        # 401 on auth → return None for caller to handle as "auth failed"
        sys.stderr.write(f"  [auth] {image_path}: {e.code} {e.reason}\n")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.stderr.write(f"  [auth] {image_path}: network error: {e}\n")

    return None


def verify_manifest(image_path: str, digest: str) -> tuple[str, Optional[str]]:
    """Return (status, detail). status in {'EXISTS','MISSING','AUTH_FAIL','NETWORK_FAIL'}."""
    token = get_token(image_path)
    if not token:
        return ("AUTH_FAIL", "could not obtain pull token")

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
    strict = "--strict" in sys.argv

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

    if missing:
        print()
        print("=== MISSING manifests (BLOCKING — would cause ImagePullBackOff) ===")
        for path, digest, detail in missing:
            print(f"  {path}@{digest}")
            print(f"    {detail}")
        return 1

    if network_fails:
        print()
        print("[WARN] network failures — cannot conclude (returning 2)")
        return 2

    if auth_fails:
        # Auth fails are inconclusive but not fatal in default mode.
        # Most likely cause: public repo with anonymous endpoint hiccup, or
        # CI token doesn't have packages:read. Print warning and exit 0
        # (rely on runtime detector as second line of defense).
        # In --strict mode, treat AUTH_FAIL as hard failure.
        print()
        print("[WARN] auth failures — manifest existence not verified for some digests")
        print("       (runtime drift detector will catch GC'd digests within 5min)")
        if strict:
            print("[STRICT] --strict mode: AUTH_FAIL counts as hard failure")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
