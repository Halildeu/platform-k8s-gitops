"""A role whose shape another subsystem pins must not become an MFA composite parent.

Adding `requires-mfa` as a composite child flips the parent role's `.composite` from
false to true. That is invisible in the parent's name and in any role listing, but it is
load-bearing for anyone who pinned the parent's shape.

Measured 2026-07-27 on `platform-test`. `setup-privileged-mfa.sh` composited the marker
into `ethics-manager`, and Faz 35 pins the opposite for that exact role:

    provision-test-keycloak.sh:184  .composite == false
    provision-test-keycloak.sh:344  .composite == false
    provision-test-keycloak.sh:540  effective realm roles allowlist, no requires-mfa
    provision-test-keycloak.sh:755  token roles allowlist, no requires-mfa
    provision-test-openfga.sh       exact-set token role pin, no requires-mfa

Live state confirmed the clash: `roles/ethics-manager` reported `composite=True` with
`requires-mfa` as its only child, and the line-341 predicate failed against it. The whole
ETHICS provisioning chain was down, and the failure surfaced four steps away from its
cause -- as a token pin mismatch and a 401 -- which is why it survived a merge.

There is a granularity argument underneath the contract clash, and it is the durable
reason: `ethics-manager` is held by 3 humans and 4 synthetic automation personas. A script
cannot complete a TOTP enrollment, so a role shared with automation is the wrong place to
hang an interactive second factor. Humans take the marker by direct assignment; personas
do not take it at all.

This guard is deliberately structural rather than a hardcoded denylist of one role: it
reads the composite targets out of the script and the shape pins out of the repo, so a
role that grows a shape contract next month is covered without anyone remembering to
update a list here.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MFA_SCRIPT = REPO_ROOT / "scripts/keycloak/setup-privileged-mfa.sh"
SEARCH_ROOTS = ("scripts", "bootstrap", "tests")

PRIV_ROLES = re.compile(r'^PRIV_ROLES="([^"]*)"', re.MULTILINE)
# `.name == "<role>" and ... .composite == false` in any order, within one predicate.
SHAPE_PIN = re.compile(
    r'\.name\s*==\s*"([A-Za-z0-9_.:-]+)"(?=(?:[^\'"]|"[^"]*")*?\.composite\s*==\s*false)'
)


def _composite_targets() -> list[str]:
    body = MFA_SCRIPT.read_text(encoding="utf-8")
    m = PRIV_ROLES.search(body)
    assert m, "PRIV_ROLES assignment not found -- did the variable get renamed?"
    return m.group(1).split()


def _shape_pinned_roles() -> dict[str, list[str]]:
    """role -> files that assert `.composite == false` for it."""
    found: dict[str, list[str]] = {}
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix not in (".sh", ".py", ".json"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if ".composite" not in text:
                continue
            for role in SHAPE_PIN.findall(text):
                found.setdefault(role, []).append(str(path.relative_to(REPO_ROOT)))
    return found


def test_the_inputs_are_discoverable():
    """Both halves must be non-empty, or the intersection below is vacuously safe."""
    targets = _composite_targets()
    assert len(targets) >= 3, f"only {len(targets)} composite targets parsed: {targets}"
    pinned = _shape_pinned_roles()
    assert pinned, (
        "no `.composite == false` shape pin found anywhere -- the regex probably stopped "
        "matching, which would make this guard silently useless"
    )


def test_no_composite_target_has_a_pinned_shape():
    targets = set(_composite_targets())
    pinned = _shape_pinned_roles()
    clashes = sorted(targets & pinned.keys())
    assert not clashes, "MFA composite target collides with a pinned role shape:\n  " + "\n  ".join(
        f"{role}: pinned `.composite == false` by {', '.join(pinned[role])}" for role in clashes
    ) + (
        "\n\nCompositing requires-mfa into this role sets .composite=true and breaks that "
        "contract. Drop it from PRIV_ROLES and give the marker to its HUMAN holders via "
        "DIRECT_MFA_USERS instead -- roles shared with automation personas cannot carry an "
        "interactive second factor, because a script cannot complete TOTP enrollment."
    )
