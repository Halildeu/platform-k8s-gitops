"""Keycloak client CORS/redirect invariant — Faz 22 Sec A3 (narrowing).

A3 narrows `redirectUris` and `webOrigins` on Keycloak clients. On the TEST realm the
narrowing exists **only in live state** — there is no realm import or client-creation
script for `frontend` anywhere in this repo, so nothing reproduces it and nothing
prevents a wildcard from being reintroduced.

What this repo *does* control is its Keycloak fixtures and provisioning scripts. This
guard makes that surface machine-enforced, so the one place a wildcard can enter through
review cannot regress silently. It is not a substitute for managing the live TEST/PROD
clients as desired state — that gap is recorded in
`docs/operations/RUNBOOKS/RB-kc-realm-security-hardening.md` (row A3).

Why `webOrigins: ["*"]` matters: it disables CORS origin checking for that client, so any
web origin can read authenticated responses. Keycloak's narrow form is `"+"`, meaning
"allow exactly the origins of the registered redirectUris" — narrow *and* self-maintaining,
because it follows redirectUris instead of duplicating them into a list that drifts.

Found and fixed when this guard was written: `bootstrap/local-fixtures/keycloak/
dev-local-realm.json` had `"webOrigins": ["*"]` on both `platform-gateway` and
`platform-frontend`.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Wildcards that switch a check OFF rather than narrowing it.
FORBIDDEN_ORIGINS = {"*"}
# A redirectUri that is only a wildcard accepts any callback target.
FORBIDDEN_REDIRECTS = {"*", "/*", "http://*", "https://*", "*/*"}


def _keycloak_realm_fixtures() -> list[Path]:
    """Discover realm fixtures by GLOB, never a hardcoded list.

    A hardcoded list stops covering a fixture added next month; the glob means a new
    `bootstrap/**/*realm*.json` is guarded the day it lands.
    """
    return sorted(
        p
        for p in REPO_ROOT.glob("bootstrap/**/*realm*.json")
        if p.is_file()
    )


def _clients_of(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # a malformed fixture must fail loudly
        raise AssertionError(f"{path.relative_to(REPO_ROOT)} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        return []
    return [c for c in (doc.get("clients") or []) if isinstance(c, dict)]


def test_realm_fixtures_are_discoverable():
    """Guard against a silently empty glob making every assertion below vacuous."""
    assert _keycloak_realm_fixtures(), "no bootstrap/**/*realm*.json fixture discovered"


def test_no_fixture_client_allows_wildcard_web_origins():
    offenders: list[str] = []
    clients_checked = 0

    for path in _keycloak_realm_fixtures():
        rel = path.relative_to(REPO_ROOT)
        for client in _clients_of(path):
            origins = client.get("webOrigins")
            if origins is None:
                continue
            clients_checked += 1
            bad = [o for o in origins if str(o).strip() in FORBIDDEN_ORIGINS]
            if bad:
                offenders.append(
                    f"{rel}: client {client.get('clientId')!r} webOrigins={origins!r} "
                    "-> CORS origin checking disabled; use [\"+\"] to allow exactly the "
                    "origins of the registered redirectUris"
                )

    assert clients_checked, (
        "no fixture client declares webOrigins — the invariant would be vacuous; "
        "if Keycloak fixtures were removed on purpose, delete this test"
    )
    assert not offenders, "wildcard webOrigins in a repo-managed fixture:\n  " + "\n  ".join(offenders)


def test_no_fixture_client_allows_wildcard_only_redirect_uri():
    offenders: list[str] = []
    clients_checked = 0

    for path in _keycloak_realm_fixtures():
        rel = path.relative_to(REPO_ROOT)
        for client in _clients_of(path):
            redirects = client.get("redirectUris")
            if redirects is None:
                continue
            clients_checked += 1
            bad = [r for r in redirects if str(r).strip() in FORBIDDEN_REDIRECTS]
            if bad:
                offenders.append(
                    f"{rel}: client {client.get('clientId')!r} redirectUris={redirects!r} "
                    "-> accepts any callback target; pin scheme+host(+port)"
                )

    assert clients_checked, "no fixture client declares redirectUris — invariant vacuous"
    assert not offenders, "wildcard redirectUri in a repo-managed fixture:\n  " + "\n  ".join(offenders)
