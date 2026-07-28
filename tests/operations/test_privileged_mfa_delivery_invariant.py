"""`requires-mfa` must reach named humans directly, never through a role composite.

Supersedes `test_mfa_composite_target_shape_invariant.py`, whose premise no longer holds:
that guard checked that no composite TARGET had a pinned role shape, and there are now no
composite targets at all, so it passed vacuously. This asserts the stronger property.

Two measurements on `platform-test`, 2026-07-27, drove the redesign.

**Automation cannot do TOTP.** The six privileged roles have 34 holders: 4 humans, 4
ambiguous automation identities, 26 synthetic personas. 30 of 34 are automation --
`ag028-approver`, `c5persona-admin-9001`, `codex-1164-role-smoke-1167`,
`rb-operator-denetim`, `endpoint-admin-test-approver` and so on. A script cannot complete a
TOTP enrollment, so compositing the marker into these roles would force TOTP on every
ENDPOINT_ADMIN smoke persona, every AG-0xx acceptance persona and every remote-bridge
operator identity the moment the flow is bound.

**Composite delivery mutates the parent and hides its own reach.** Adding the marker as a
composite child flipped `ethics-manager.composite` from false to true, which broke four
checks in the Faz 35 provisioning chain. And `roles/requires-mfa/users` returns only DIRECT
assignments, so it read `0` while 34 users effectively held the role -- a security control
whose blast radius is invisible in the obvious query is a bad control.

Direct assignment fixes both: no parent role changes shape, and the obvious query becomes
truthful. The cost is that the human list is explicit, which is why the script reports
privileged-role holders missing from it rather than guessing -- deciding that someone is a
person is not a call a script should make on its own.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MFA_SCRIPT = REPO_ROOT / "scripts/keycloak/setup-privileged-mfa.sh"

# A POST to a role's composites endpoint is the forbidden operation. DELETE is the
# reconcile path and must stay.
COMPOSITE_WRITE = re.compile(r"-X\s+POST[^\n]*roles/[^\n]*composites")
DIRECT_USERS = re.compile(r'^DIRECT_MFA_USERS="\$\{DIRECT_MFA_USERS:-([^}]*)\}"', re.MULTILINE)
AUTOMATION = re.compile(r'^AUTOMATION_MARKERS="\$\{AUTOMATION_MARKERS:-([^}]*)\}"', re.MULTILINE)
SHAPE_PIN = re.compile(
    r'\.name\s*==\s*"([A-Za-z0-9_.:-]+)"(?=(?:[^\'"]|"[^"]*")*?\.composite\s*==\s*false)'
)


def _body() -> str:
    return MFA_SCRIPT.read_text(encoding="utf-8")


def test_script_and_its_declarations_are_discoverable():
    """Renaming a variable must fail loudly, not make the assertions below vacuous."""
    body = _body()
    assert MFA_SCRIPT.is_file(), "setup-privileged-mfa.sh missing"
    assert DIRECT_USERS.search(body), "DIRECT_MFA_USERS declaration not found"
    assert AUTOMATION.search(body), "AUTOMATION_MARKERS declaration not found"
    assert "composites" in body, "no composites handling at all — reconcile path lost?"


def test_marker_is_never_written_into_a_role_composite():
    hits = COMPOSITE_WRITE.findall(_body())
    assert not hits, (
        "setup-privileged-mfa.sh writes the marker into a role composite:\n  "
        + "\n  ".join(hits)
        + "\n\nCompositing mutates the parent role's .composite field, breaks any contract "
          "that pins the parent's shape, and hides its own blast radius from "
          "roles/<marker>/users. Assign the marker directly to the identities in "
          "DIRECT_MFA_USERS instead."
    )


def test_no_automation_identity_is_listed_for_direct_mfa():
    body = _body()
    users = DIRECT_USERS.search(body).group(1).split()
    markers = AUTOMATION.search(body).group(1).split()
    assert users, "DIRECT_MFA_USERS is empty — nobody would be covered"
    offenders = [u for u in users if any(m in u for m in markers)]
    assert not offenders, (
        "DIRECT_MFA_USERS contains identities that match an automation marker: "
        f"{offenders}\n\nA script cannot complete TOTP enrollment, so arming one locks the "
        "automation out. Either the identity is a person and the marker is too broad, or it "
        "belongs to no MFA list at all."
    )


def test_a_shape_pinned_role_is_still_never_a_composite_parent():
    """Safety net: if composite targets are ever reintroduced, the old clash must fail."""
    body = _body()
    pinned = set()
    for root in ("scripts", "bootstrap", "tests"):
        for path in (REPO_ROOT / root).rglob("*"):
            if path.is_file() and path.suffix in (".sh", ".py", ".json"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if ".composite" in text:
                    pinned.update(SHAPE_PIN.findall(text))
    assert pinned, "no `.composite == false` shape pin found — regex probably stopped matching"
    targeted = {r for hit in COMPOSITE_WRITE.findall(body) for r in pinned if r in hit}
    assert not targeted, f"shape-pinned role would be composited: {sorted(targeted)}"
