"""`smoke-ats-v1` least-privilege invariant — Faz 22 Sec A2b.3 (gitops #2746).

The whole reason a dedicated ATS smoke client exists is that the two ways of making
`resource_access["ats-api"].roles` appear are NOT equivalent:

* `fullScopeAllowed=true` — passes EVERY role the user holds, unfiltered. This is what
  `frontend` does today and exactly what A2c is retiring. One leaked test secret would
  mint tokens carrying every role in the realm.
* `fullScopeAllowed=false` + explicit `ats-api` role scope-mappings — passes only those
  roles. Measured 2026-07-27 on a live token: the authorized party is the smoke-ats
  client, the audience is the ATS API alone, and `resource_access` carries all 16
  `ats-api` roles.

Both produce a *working* ATS token, so the narrow one is easy to "fix" into the wide one
when something looks broken. That regression is silent — the token still works, it just
carries far more authority. Hence this guard.

Also pinned: the client stays ROPC-only. `standardFlowEnabled=true` would make a
confidential smoke credential usable in a browser redirect flow;
`serviceAccountsEnabled=true` would attach a second, unaudited identity to the same secret.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/keycloak/setup-smoke-ats-client.sh"

# key -> the ONLY value the desired state may declare
REQUIRED_FLAGS = {
    "fullScopeAllowed": "false",
    "publicClient": "false",
    "serviceAccountsEnabled": "false",
    "standardFlowEnabled": "false",
    "implicitFlowEnabled": "false",
    "directAccessGrantsEnabled": "true",
}


def _desired_assignments() -> dict:
    """Collect every `-s key=value` the script declares, keyed by key."""
    text = SCRIPT.read_text(encoding="utf-8")
    out: dict = {}
    for key, val in re.findall(r'"-s"\s+"([A-Za-z]+)=([^"]*)"', text):
        out.setdefault(key, []).append(val)
    return out


def test_script_exists():
    assert SCRIPT.is_file(), f"{SCRIPT.relative_to(REPO_ROOT)} missing"


def test_desired_state_is_parseable_and_non_empty():
    """A regex that silently matches nothing would make every assertion below vacuous."""
    found = _desired_assignments()
    assert found, "no `-s key=value` desired-state assignments parsed from the script"
    assert "clientId" in found, "desired state does not declare clientId"


def test_least_privilege_flags_are_pinned():
    found = _desired_assignments()
    problems = []
    for key, want in REQUIRED_FLAGS.items():
        vals = found.get(key)
        if not vals:
            problems.append(f"{key}: not declared (must be pinned to {want!r})")
            continue
        bad = [v for v in vals if v != want]
        if bad:
            problems.append(f"{key}: declared {bad!r}, must be exactly {want!r}")
    assert not problems, (
        "smoke-ats-v1 desired state violates least privilege:\n  "
        + "\n  ".join(problems)
        + "\n\nfullScopeAllowed=true would pass EVERY role the user holds — the "
        "frontend behaviour A2c is retiring. Explicit ats-api role scope-mappings "
        "are sufficient (measured: 16/16 roles in resource_access)."
    )


def test_roles_are_discovered_at_runtime_not_hardcoded():
    """A frozen role list silently narrows coverage the day a new ats.* role lands."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "ats_role_names()" in text, "runtime role discovery helper missing"
    literals = re.findall(r'"(ats\.[a-z.]+)"', text)
    assert not literals, f"hardcoded ats.* role names found: {literals}"


# Client-level audience mappers the desired state may declare — EXACTLY these.
# 2026-09-06: ATS delegates authorization to the platform (permission-service) and
# both permission-service and user-service validate `aud`; with `aud=["ats-api"]`
# alone every smoke-ats-v1 call died with 401 (measured: users/me/profile, authz/me,
# recruiter/jobs). `account` and `frontend` are accepted by every platform service
# and are deliberately absent — adding either would widen one test credential to the
# whole platform, the same silent regression the fullScopeAllowed guard exists for.
REQUIRED_AUDIENCES = {"permission-service", "user-service"}
FORBIDDEN_AUDIENCES = {"account", "frontend"}


def _desired_audiences() -> set:
    text = SCRIPT.read_text(encoding="utf-8")
    block = re.search(r"desired_audience_mappers\(\)\s*\{(.*?)\n\}", text, re.S)
    assert block, "desired_audience_mappers() helper missing"
    return set(re.findall(r'"[a-z0-9-]+\|([a-z-]+)"', block.group(1)))


def test_platform_audiences_are_exactly_the_two_delegation_targets():
    got = _desired_audiences()
    assert got == REQUIRED_AUDIENCES, (
        f"declared audiences {sorted(got)} must be exactly {sorted(REQUIRED_AUDIENCES)}"
    )
    assert not (got & FORBIDDEN_AUDIENCES), "account/frontend audience widens the credential"
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"protocolMapper":"oidc-audience-mapper"' in text
    assert 'clients/$CID/protocol-mappers/models' in text, "mappers must be client-level"
    # --check reports drift and --apply asserts the read-back; neither may skip it.
    assert text.count('AUD_MISSING=$(audience_missing_count "$CID"') == 2
    assert 'audience-eksik=$AUD_MISSING' in text
