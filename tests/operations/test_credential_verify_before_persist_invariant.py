"""A rotated credential must be proven against Keycloak before it is written to Vault.

Measured on 2026-07-27 against the live `platform-test` realm: `kv/platform/d35-3` had
advanced to v13 while Keycloak's stored password still matched v11. Reading each version
back and attempting ROPC showed it exactly —

    Vault v11 -> HTTP 200   (Keycloak matches this version)
    Vault v12 -> HTTP 401
    Vault v13 -> HTTP 401

Every later reader of that path therefore authenticated with a value that could not work.
`provision-test-ethic-entitlement.sh` and `repair-d35-permission-writer-credential.sh`
both took a 401 from an otherwise healthy realm, which reads like a Keycloak outage rather
than a stale secret and sends the next person debugging the wrong layer.

The self-heal in `fullats-live-browser-acceptance.sh` had the two steps in the order that
makes this state reachable: generate a password, reset Keycloak, **write Vault**, then
verify. `set -o pipefail` covers the case where `kcadm update .../reset-password` exits
non-zero, but not the case where it exits 0 without the intended password becoming usable
-- and on that path Vault has already been written and the FATAL leaves it ahead of
Keycloak with no rollback.

Verifying first costs one token mint and makes the bad state unreachable: if the new
password cannot authenticate, Vault is never touched and the old value stays valid.

This is a guard, not a fix -- the fix is the ordering itself. The guard exists because the
ordering is the kind of thing a later edit reshuffles without noticing, and nothing else
in CI would catch it: these scripts run against a live host, never in CI.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (script, vault-write call, keycloak-verify call)
# Each entry is a rotation path that both resets a Keycloak credential and records the
# new value somewhere durable. Add a row when another script grows the same shape.
ROTATION_PATHS = [
    (
        "scripts/ats/fullats-live-browser-acceptance.sh",
        "persist_d35_password",
        'token_from_password "$ADMIN_USERNAME_FILE" "$ADMIN_PASSWORD_FILE"',
    ),
]

ROTATION_TRIGGER = re.compile(r"openssl rand -hex")


def test_rotation_paths_are_discoverable():
    """A renamed script would make the ordering assertions below vacuously true."""
    for rel, _, _ in ROTATION_PATHS:
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} missing -- update ROTATION_PATHS, do not delete the guard"
        assert ROTATION_TRIGGER.search(path.read_text(encoding="utf-8")), (
            f"{rel} no longer generates a password; if rotation moved elsewhere, move this row"
        )


def test_keycloak_verification_precedes_the_vault_write():
    offenders = []
    for rel, vault_write, kc_verify in ROTATION_PATHS:
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        # Anchor on the rotation branch so an unrelated earlier verify cannot satisfy this.
        start = ROTATION_TRIGGER.search(body)
        assert start, f"{rel}: rotation trigger vanished"
        branch = body[start.start():]
        write_at = branch.find(vault_write)
        verify_at = branch.find(kc_verify)
        if write_at < 0:
            offenders.append(f"{rel}: vault write {vault_write!r} not found after rotation")
            continue
        if verify_at < 0:
            offenders.append(
                f"{rel}: no Keycloak verification ({kc_verify!r}) between rotation and the "
                f"Vault write -- the new password would be persisted unproven"
            )
            continue
        if verify_at > write_at:
            offenders.append(
                f"{rel}: Vault is written at offset {write_at} but Keycloak is only verified "
                f"at {verify_at} -- a failed verification leaves Vault ahead of Keycloak"
            )
    assert not offenders, (
        "credential rotation persists before it proves:\n  "
        + "\n  ".join(offenders)
        + "\n\nReset Keycloak, mint a token with the new password, and only then write the "
          "secret store. Vault must never hold a credential Keycloak has not accepted."
    )
