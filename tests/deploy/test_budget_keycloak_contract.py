from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/budget/provision-test-keycloak.sh").read_text()


def test_budget_keycloak_activation_is_test_only_and_two_key():
    assert 'KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"' in SCRIPT
    assert 'REALM="${REALM:-platform-test}"' in SCRIPT
    assert 'PERSONA_USERNAME="${PERSONA_USERNAME:-admin@example.com}"' in SCRIPT
    assert 'ROLE_NAME="budget-planner"' in SCRIPT
    assert 'SCOPES=("budget:read" "budget:write")' in SCRIPT
    assert "budget:approve" in SCRIPT
    assert "budget-service enforces both keys" in SCRIPT


def test_budget_scopes_are_optional_never_default_or_mapper_backed():
    assert "optional-client-scopes" in SCRIPT
    assert "default-client-scopes" in SCRIPT
    assert "! scope_is_default" in SCRIPT
    assert "jq -e 'length == 0'" in SCRIPT
    assert "fullScopeAllowed == true" in SCRIPT
    assert "backend's explicit two-key gate" in SCRIPT
    assert "protocol-mappers/models" in SCRIPT


def test_budget_persona_and_rollback_are_read_back():
    assert "role_is_assigned" in SCRIPT
    assert "check_state" in SCRIPT
    assert "kc add-roles" in SCRIPT
    assert "kc remove-roles" in SCRIPT
    assert "frontend optional bindings removed" in SCRIPT


def test_admin_secret_stays_inside_keycloak_container():
    assert 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' in SCRIPT
    assert 'docker exec -e KC_CONFIG="$KCADM_CONFIG"' in SCRIPT
    assert "--password" not in SCRIPT
