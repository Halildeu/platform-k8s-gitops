"""Guard the Graph mailbox helpers against routine Vault root-token regression."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPERS = (
    "scripts/ops/graph-mail-list.sh",
    "scripts/ops/graph-mail-send.sh",
)
ROOT_BOOTSTRAP_PATH = "/srv/platform/secrets/backup-auth/vault-init-prod.json"


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_graph_helpers_use_only_the_dedicated_approle_bootstrap_files():
    for helper in HELPERS:
        body = read(helper)
        assert ROOT_BOOTSTRAP_PATH not in body
        assert "VAULT_ROOT_TOKEN" not in body
        assert "/srv/platform/secrets/graph-mail-vault/role-id" in body
        assert "/srv/platform/secrets/graph-mail-vault/secret-id" in body
        assert "/v1/auth/approle/login" in body
        assert "/v1/auth/token/revoke-self" in body


def test_graph_helpers_fail_closed_on_policy_ttl_and_path_drift():
    for helper in HELPERS:
        body = read(helper)
        assert 'EXPECTED_VAULT_PATH="kv/platform/graph"' in body
        assert 'EXPECTED_VAULT_POLICY="graph-mail-ops-ro"' in body
        assert "MAX_VAULT_TOKEN_TTL=1800" in body
        assert "VAULT_POLICY_MATCH" in body
        assert "/v1/kv/data/platform/graph" in body
        assert "docker exec" not in body


def test_policy_is_exact_path_read_plus_self_revoke_only():
    policy = read("config/vault/policies/graph-mail-ops-ro.hcl")
    assert policy.count('path "') == 2
    assert 'path "kv/data/platform/graph"' in policy
    assert 'capabilities = ["read"]' in policy
    assert 'path "auth/token/revoke-self"' in policy
    assert 'capabilities = ["update"]' in policy
    assert "*" not in policy
    assert "list" not in policy


def test_provisioner_is_the_only_explicit_root_bootstrap_surface():
    provisioner = read("scripts/ops/provision-graph-mail-vault-approle.sh")
    assert ROOT_BOOTSTRAP_PATH in provisioner
    assert 'token_no_default_policy: true' in provisioner
    assert 'token_num_uses: 3' in provisioner
    assert 'token_policies: [$policy]' in provisioner
    assert 'token_ttl: "15m"' in provisioner
    assert 'token_max_ttl: "30m"' in provisioner
    assert 'secret_id_bound_cidrs: [$cidr]' in provisioner
    assert 'token_bound_cidrs: [$cidr]' in provisioner
    assert 'require_status "$STATUS" "403" "out-of-scope KV read"' in provisioner
    assert 'require_status "$STATUS" "403" "out-of-scope KV list"' in provisioner
