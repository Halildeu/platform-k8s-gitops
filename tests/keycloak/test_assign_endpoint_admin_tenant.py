from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/keycloak/assign-endpoint-admin-tenant.sh"


def test_script_is_syntax_valid_and_test_hard_bound():
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
    )
    assert syntax.returncode == 0, syntax.stderr

    source = SCRIPT.read_text()
    assert 'REALM="platform-test"' in source
    assert 'KC_CONTAINER="platform-kc-test"' in source
    assert 'KC_ADMIN_URL="http://127.0.0.1:8082"' in source
    assert "serban" not in source
    assert "platform-kc-prod" not in source


def test_script_preserves_canonical_identity_and_limits_claim_exposure():
    source = SCRIPT.read_text()
    assert 'ATTRIBUTE_NAME="endpoint_admin_tenant_id"' in source
    assert '"access.token.claim": "true"' in source
    assert '"introspection.token.claim": "true"' in source
    assert '"id.token.claim": "false"' in source
    assert '"userinfo.token.claim": "false"' in source
    assert 'displayName: "Endpoint Admin tenant ID"' in source
    assert 'view: ["admin"]' in source
    assert 'edit: ["admin"]' in source
    assert ".attributes = ((.attributes // {}) +" in source
    assert "canonicalOrgOrCompanyChanged: false" in source


def test_script_has_exact_identity_and_postcondition_guards():
    source = SCRIPT.read_text()
    assert "[0-9a-fA-F]{4}-[0-9a-fA-F]{4}" in source
    assert "target must resolve to exactly one enabled user" in source
    assert "frontend must resolve to exactly one client" in source
    assert "controlled mapper name is duplicated" in source
    assert "controlled user profile attribute exists with an unexpected contract" in source
    assert "authoritative postcondition failed" in source
    assert 'result="already-converged"' in source
    assert "mutationCount: $mutationCount" in source
    assert "adminPasswordIncluded: false" in source
    assert "adminTokenIncluded: false" in source
