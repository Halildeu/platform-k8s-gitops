#!/usr/bin/env python3
"""
scripts/automation/apply-test-overlay-digests.py

#827 PR-B — surgically rewrite the backend `digest:` lines of the test-overlay
kustomization to a validated {service: digest} map produced by the immutable
platform-backend image build before any runtime rollout.

Comment-preserving by construction: only the `digest:` value of a matched
`images:` entry is rewritten *in place*. Every other byte — including the
hundreds of provenance comment lines in that file — is left untouched, so the
resulting `git diff` is exactly the changed digest lines and the #827 diff-guard
in sync-test-overlay.sh stays trivially satisfiable. `kustomize edit set image`
is deliberately NOT used: it reserialises the whole file and strips all comments.

Entry identification: an `images:` entry is recognised by its
`newName: ghcr.io/<owner>/platform-backend-<service>` line; the *same entry's*
`digest: sha256:<64hex>` line is the one rewritten. A `- name:` line resets the
"current entry" so a digest is only ever attributed to the entry it belongs to.

Usage:
  apply-test-overlay-digests.py --digest-map '<json>' [--kustomization PATH] [--check] [--fail-on-change]
  DIGEST_MAP='<json>' apply-test-overlay-digests.py [--check] [--fail-on-change]

Exit:
  0 — applied (or, with --check, every mapped service resolvable + digests valid)
  1 — drift/consistency error (out-of-scope service, bad digest value, service
      not found, entry has no digest: field) — fail-closed, nothing written
  2 — invocation error (no/!json digest map)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_KUSTOMIZATION = "kustomize/overlays/test/kustomization.yaml"

# The backend services deploy-backend-testai.yml rolls out (its SERVICE_SPECS).
# The digest map must contain ONLY these — a key outside this set (e.g. a
# non-rolled backend entry such as notification-orchestrator) is a contract
# violation and is rejected fail-closed (Codex 019e407c P3).
SYNC_SERVICES = frozenset({
    "auth-service",
    "permission-service",
    "user-service",
    "variant-service",
    "core-data-service",
    "report-service",
    "schema-service",
    "endpoint-admin-service",
    "audio-gateway-service",
    "meeting-service",
    "transcript-service",
    "audit-event-consumer-service",
    "api-gateway",
})

# An `images:` entry boundary — `  - name: <something>`.
ENTRY_START_RE = re.compile(r"^[ \t]*-[ \t]+name:[ \t]*\S")
# The entry's identifying line — `    newName: ghcr.io/<owner>/platform-backend-<svc>`.
NEWNAME_RE = re.compile(
    r"^[ \t]+newName:[ \t]*ghcr\.io/[^/\s]+/platform-backend-(?P<svc>[a-z0-9-]+)[ \t]*$"
)
# The entry's `digest:` field line.
DIGEST_RE = re.compile(
    r"^(?P<indent>[ \t]+)digest:[ \t]*(?P<digest>sha256:[a-f0-9]{64})[ \t]*$"
)
# A well-formed image digest value.
DIGEST_VALUE_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a {service: digest} map to the test-overlay kustomization.",
    )
    parser.add_argument(
        "--digest-map",
        help="JSON object {service: 'sha256:...'} (default: $DIGEST_MAP env)",
    )
    parser.add_argument(
        "--kustomization",
        default=DEFAULT_KUSTOMIZATION,
        help=f"Path to the kustomization.yaml (default: {DEFAULT_KUSTOMIZATION})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate + report only; do not write the file.",
    )
    parser.add_argument(
        "--fail-on-change",
        action="store_true",
        help="With --check, fail if any digest line would change.",
    )
    return parser.parse_args(argv)


def load_digest_map(raw: str | None) -> dict[str, str]:
    if raw is None or raw.strip() == "":
        print("[apply-test-overlay] ERROR: no digest map (--digest-map / $DIGEST_MAP)", file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[apply-test-overlay] ERROR: digest map is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print("[apply-test-overlay] ERROR: digest map must be a JSON object", file=sys.stderr)
        sys.exit(2)
    return {str(k): str(v) for k, v in data.items()}


def index_digest_lines(lines: list[str]) -> dict[str, tuple[int, str, str]]:
    """Walk the file once; return {service: (line_index, indent, current_digest)}.

    `current_svc` is set by a `newName:` line and cleared by the next entry
    boundary or once that entry's `digest:` line has been attributed — a digest
    is therefore never mis-assigned across entries.
    """
    found: dict[str, tuple[int, str, str]] = {}
    current_svc: str | None = None
    for i, line in enumerate(lines):
        if ENTRY_START_RE.match(line):
            current_svc = None
            continue
        m_new = NEWNAME_RE.match(line)
        if m_new:
            current_svc = m_new.group("svc")
            continue
        if current_svc is not None:
            m_dig = DIGEST_RE.match(line)
            if m_dig:
                found[current_svc] = (i, m_dig.group("indent"), m_dig.group("digest"))
                current_svc = None  # entry's digest consumed
    return found


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    digest_map = load_digest_map(args.digest_map or os.environ.get("DIGEST_MAP"))

    out_of_scope = sorted(set(digest_map) - SYNC_SERVICES)
    if out_of_scope:
        print(
            "[apply-test-overlay] FAIL — digest map contains service(s) outside "
            f"the deploy-backend-testai.yml rollout scope: {', '.join(out_of_scope)}",
            file=sys.stderr,
        )
        return 1

    kustomization = Path(args.kustomization)
    if not kustomization.is_file():
        print(f"[apply-test-overlay] ERROR: kustomization not found: {kustomization}", file=sys.stderr)
        return 1

    if not digest_map:
        print("[apply-test-overlay] digest map empty — nothing to do")
        return 0

    lines = kustomization.read_text(encoding="utf-8").splitlines(keepends=True)
    digest_lines = index_digest_lines(lines)

    errors: list[str] = []
    changes: list[tuple[str, str, str]] = []
    unchanged: list[str] = []

    for svc in sorted(digest_map):
        new_digest = digest_map[svc]
        if not DIGEST_VALUE_RE.match(new_digest):
            errors.append(f"{svc}: invalid digest value {new_digest!r} (want sha256:<64 hex>)")
            continue
        if svc not in digest_lines:
            errors.append(
                f"{svc}: no `platform-backend-{svc}` images entry with a `digest:` field "
                f"in {kustomization}"
            )
            continue
        idx, indent, old_digest = digest_lines[svc]
        if old_digest == new_digest:
            unchanged.append(svc)
            continue
        changes.append((svc, old_digest, new_digest))
        lines[idx] = f"{indent}digest: {new_digest}\n"

    if errors:
        print("[apply-test-overlay] FAIL — digest map inconsistent with the overlay:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    for svc in unchanged:
        print(f"  = {svc}: already at {digest_map[svc]}")
    for svc, old_digest, new_digest in changes:
        print(f"  ~ {svc}: {old_digest} -> {new_digest}")

    if not changes:
        print(f"[apply-test-overlay] overlay already in sync ({len(unchanged)} service(s)) — no write")
        return 0

    if args.check:
        if args.fail_on_change and changes:
            print(
                "[apply-test-overlay] --fail-on-change: overlay desired-state "
                f"differs from digest map ({len(changes)} digest line(s) would change)",
                file=sys.stderr,
            )
            return 1
        print(f"[apply-test-overlay] --check: {len(changes)} digest line(s) would change — not written")
        return 0

    kustomization.write_text("".join(lines), encoding="utf-8")
    print(
        f"[apply-test-overlay] wrote {kustomization}: "
        f"{len(changes)} digest line(s) changed, {len(unchanged)} already current"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
