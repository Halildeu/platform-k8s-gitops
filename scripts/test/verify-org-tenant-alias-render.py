#!/usr/bin/env python3
"""Verify the org -> tenant alias renders only where it was measured (board #2559).

An alias silently redirects an org's whole device view. That is exactly what TEST needs today
(admin org 68c73eb9-… vs. the fixed enrolment tenant 00000000-…-0001) and exactly what prod
must never inherit by accident: a stray alias there would point a real customer at another
tenant's fleet. "We only edited the test overlay" is not an invariant — this is.

Usage: verify-org-tenant-alias-render.py <test.yaml> <prod.yaml>
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

KEY = "ENDPOINT_ADMIN_TENANT_ORG_ALIASES"
CONFIGMAP_PREFIX = "endpoint-admin-service-config"
DEPLOYMENT = "endpoint-admin-service"
MARKER = "endpoint-admin.acik.com/org-alias-rev"


def load(path: Path) -> list[dict]:
    docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    if not docs:
        raise SystemExit(f"FAIL: {path} rendered nothing — refusing to pass on an empty snapshot")
    return docs


def alias_values(docs: list[dict]) -> list[str]:
    found = []
    for doc in docs:
        if doc.get("kind") != "ConfigMap":
            continue
        if not doc.get("metadata", {}).get("name", "").startswith(CONFIGMAP_PREFIX):
            continue
        data = doc.get("data") or {}
        if KEY not in data:
            # The base declares the key explicitly; its absence means the contract moved and the
            # overlay `replace` would fail. Treat it as a failure rather than "no alias".
            raise SystemExit(f"FAIL: {KEY} missing from {doc['metadata']['name']} — base contract lost")
        found.append(data[KEY])
    if not found:
        raise SystemExit(f"FAIL: no {CONFIGMAP_PREFIX} ConfigMap rendered — cannot verify the alias")
    return found


def marker(docs: list[dict]) -> str | None:
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc.get("metadata", {}).get("name") == DEPLOYMENT:
            annotations = doc["spec"]["template"]["metadata"].get("annotations") or {}
            return annotations.get(MARKER)
    raise SystemExit(f"FAIL: no {DEPLOYMENT} Deployment rendered")


def parse_pairs(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        org, sep, tenant = entry.partition("=")
        if not sep:
            raise SystemExit(f"FAIL: alias entry is not <org>=<tenant>: {entry!r}")
        pairs.append((org.strip(), tenant.strip()))
    return pairs


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    test_docs, prod_docs = load(Path(sys.argv[1])), load(Path(sys.argv[2]))

    # prod: the alias must be absent in effect. Empty string is the base default and the only
    # value prod may carry.
    for value in alias_values(prod_docs):
        if value.strip():
            print(f"FAIL: prod renders an org->tenant alias: {value!r}", file=sys.stderr)
            print("An alias redirects a whole fleet view; prod must derive its tenant.", file=sys.stderr)
            return 1
    if marker(prod_docs) is not None:
        print("FAIL: prod carries the alias rollout marker — the TEST-only patch leaked", file=sys.stderr)
        return 1

    # test: exactly one pair, and it must be injective (two orgs on one tenant would hand both
    # of them the same devices — the resolver rejects it at startup; catch it before rollout).
    values = alias_values(test_docs)
    if len(values) != 1:
        print(f"FAIL: expected one endpoint-admin ConfigMap in test, got {len(values)}", file=sys.stderr)
        return 1
    pairs = parse_pairs(values[0])
    if len(pairs) != 1:
        print(f"FAIL: test must declare exactly one alias pair, got {len(pairs)}: {pairs}", file=sys.stderr)
        return 1
    tenants = [t for _, t in pairs]
    if len(set(tenants)) != len(tenants):
        print(f"FAIL: alias is not one-to-one — two orgs share a tenant: {pairs}", file=sys.stderr)
        return 1
    if marker(test_docs) is None:
        print("FAIL: test declares an alias but carries no rollout marker — a ConfigMap-only", file=sys.stderr)
        print("change never reaches the running pod (envFrom is read at container start).", file=sys.stderr)
        return 1

    org, tenant = pairs[0]
    print(f"PASS: test aliases {org} -> {tenant} (marker {marker(test_docs)}); prod carries none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
