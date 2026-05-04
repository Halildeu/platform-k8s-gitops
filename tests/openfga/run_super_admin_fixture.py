#!/usr/bin/env python3
"""
tests/openfga/run_super_admin_fixture.py

Codex Sprint A P0 Item 5 — OpenFGA super-admin fixture executable smoke.

Seeds canonical super-admin tuple (organization:default#admin@user:<id>)
then runs each YAML case in tests/openfga/fixtures/super-admin-allow-deny.yaml
against the running OpenFGA store. Asserts allow/deny outcomes match
the fixture's expected value.

Codex P0 retrospective: existing openfga-fixture-smoke.yml only runs
bootstrap/local-fixtures/openfga/tuples.json smoke_checks. The
super-admin pattern fixture (tests/openfga/fixtures/) was created as
documentation but never executed — that's a fake-test (kural #9).
This runner makes it executable.

Usage:
  OPENFGA_URL=http://localhost:8080 python3 run_super_admin_fixture.py
  OPENFGA_URL=http://localhost:8080 OPENFGA_STORE_ID=01ABC... python3 run_super_admin_fixture.py

Exit codes:
  0 — all cases pass
  1 — at least one case fails (allow/deny mismatch)
  2 — setup error (no store, model missing, fixture file missing)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "openfga" / "fixtures" / "super-admin-allow-deny.yaml"

# Canonical super-admin tuple (matches docs/authz/openfga-model-contract.md)
SUPER_ADMIN_USER_IDS = ["1201", "1204"]  # admin@example.com + halil.kocoglu

OPENFGA_URL = os.environ.get("OPENFGA_URL", "").rstrip("/")
if not OPENFGA_URL:
    print("ERR: OPENFGA_URL must be set (e.g. http://localhost:8080)", file=sys.stderr)
    sys.exit(2)


def http_call(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{OPENFGA_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_store_id() -> str:
    explicit = os.environ.get("OPENFGA_STORE_ID")
    if explicit:
        return explicit
    stores = http_call("GET", "/stores").get("stores", [])
    if not stores:
        print("ERR: no OpenFGA stores; seed first", file=sys.stderr)
        sys.exit(2)
    return stores[0]["id"]


def get_latest_model_id(store_id: str) -> str:
    models = http_call(
        "GET", f"/stores/{store_id}/authorization-models"
    ).get("authorization_models", [])
    if not models:
        print(f"ERR: no auth models in store {store_id}; seed first", file=sys.stderr)
        sys.exit(2)
    return models[0]["id"]


def write_super_admin_tuples(store_id: str, model_id: str) -> int:
    """Seed canonical super-admin tuples for known user IDs. Idempotent (writes existing tuples are no-ops via upsert pattern)."""
    written = 0
    for uid in SUPER_ADMIN_USER_IDS:
        tuple_key = {
            "user": f"user:{uid}",
            "relation": "admin",
            "object": "organization:default",
        }
        try:
            http_call(
                "POST",
                f"/stores/{store_id}/write",
                {
                    "writes": {"tuple_keys": [tuple_key]},
                    "authorization_model_id": model_id,
                },
            )
            written += 1
        except urllib.error.HTTPError as e:
            # 400 = tuple may already exist (write_existing not supported in some versions)
            # 422 = invalid type — model doesn't have organization
            if e.code in (400, 422):
                # Try to verify it exists already via read
                existing = http_call(
                    "POST",
                    f"/stores/{store_id}/read",
                    {"tuple_key": tuple_key},
                ).get("tuples", [])
                if existing:
                    print(f"  [SEED] user:{uid} admin@organization:default already exists")
                else:
                    print(
                        f"  [SEED] user:{uid} write failed ({e.code}): "
                        f"model may lack 'organization' type",
                        file=sys.stderr,
                    )
            else:
                print(f"  [SEED] user:{uid} write error: {e.code}", file=sys.stderr)
                raise
        else:
            print(f"  [SEED] user:{uid} admin@organization:default written")
    return written


def parse_yaml_fixture(path: Path) -> list[dict]:
    """Lightweight YAML parser (PyYAML preferred, fallback if needed)."""
    try:
        import yaml
    except ImportError:
        print("ERR: PyYAML required (pip install pyyaml)", file=sys.stderr)
        sys.exit(2)
    return yaml.safe_load(path.read_text()).get("cases", [])


def run_case(store_id: str, model_id: str, case: dict) -> bool:
    """Return True if expected matches actual."""
    name = case.get("name", "<unnamed>")
    user = case["user"]
    check = case["check"]
    expected = case["expected"]  # "allow" | "deny"

    body = {
        "authorization_model_id": model_id,
        "tuple_key": {
            "user": user,
            "relation": check["relation"],
            "object": check["object"],
        },
    }

    try:
        result = http_call("POST", f"/stores/{store_id}/check", body)
    except urllib.error.HTTPError as e:
        print(f"FAIL [api-error] {name}: {e.code} {e.reason}")
        return False

    actual_allowed = bool(result.get("allowed"))
    expected_allowed = expected == "allow"

    if actual_allowed == expected_allowed:
        print(f"PASS  expected={expected} actual={'allow' if actual_allowed else 'deny':<5}  {name}")
        return True
    else:
        print(
            f"FAIL  expected={expected} actual={'allow' if actual_allowed else 'deny':<5}  {name}"
        )
        return False


def main() -> int:
    if not FIXTURE_PATH.exists():
        print(f"ERR: fixture not found: {FIXTURE_PATH}", file=sys.stderr)
        return 2

    print(f"=== Super-admin fixture smoke ===")
    print(f"openfga: {OPENFGA_URL}")
    print(f"fixture: {FIXTURE_PATH.relative_to(REPO_ROOT)}")
    print()

    store_id = get_store_id()
    model_id = get_latest_model_id(store_id)
    print(f"store={store_id}")
    print(f"model={model_id}")
    print()

    print("--- Seeding canonical super-admin tuples ---")
    write_super_admin_tuples(store_id, model_id)
    print()

    cases = parse_yaml_fixture(FIXTURE_PATH)
    if not cases:
        print("ERR: fixture has no cases", file=sys.stderr)
        return 2

    print(f"--- Running {len(cases)} cases ---")
    passes = 0
    fails = 0
    for case in cases:
        if run_case(store_id, model_id, case):
            passes += 1
        else:
            fails += 1

    print()
    print("=== Summary ===")
    print(f"pass: {passes}")
    print(f"fail: {fails}")
    print(f"total: {len(cases)}")

    if fails > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
