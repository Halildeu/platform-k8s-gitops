"""Guard the Graph mailbox helpers against routine Vault root-token regression.

Two identities share the helpers: `graph` (legacy app, Mail.Read + Mail.Send,
ai@acik.com only) and `graph-read` (Mail.Read-only app, ai@ + halil.kocoglu@).
Each identity has its own KV path, policy, AppRole and bootstrap files, and the
send helper is pinned to the legacy identity only.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST_HELPER = "scripts/ops/graph-mail-list.sh"
SEND_HELPER = "scripts/ops/graph-mail-send.sh"
HELPERS = (LIST_HELPER, SEND_HELPER)
PROVISIONER = "scripts/ops/provision-graph-mail-vault-approle.sh"
SEEDER = "scripts/ops/seed-graph-read-kv.sh"
ROOT_BOOTSTRAP_PATH = "/srv/platform/secrets/backup-auth/vault-init-prod.json"
IDENTITIES = {
    "graph": {
        "policy": "graph-mail-ops-ro",
        "role": "graph-mail-ops",
        "approle_dir": "/srv/platform/secrets/graph-mail-vault",
        "kv_path": "kv/platform/graph",
    },
    "graph-read": {
        "policy": "graph-mail-read-ops-ro",
        "role": "graph-mail-read-ops",
        "approle_dir": "/srv/platform/secrets/graph-mail-read-vault",
        "kv_path": "kv/platform/graph-read",
    },
}


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_graph_helpers_use_only_the_dedicated_approle_bootstrap_files():
    for helper in HELPERS:
        body = read(helper)
        assert ROOT_BOOTSTRAP_PATH not in body
        assert "VAULT_ROOT_TOKEN" not in body
        assert "/v1/auth/approle/login" in body
        assert "/v1/auth/token/revoke-self" in body
    listing = read(LIST_HELPER)
    for identity in IDENTITIES.values():
        assert f'{identity["approle_dir"]}/role-id' in listing
        assert f'{identity["approle_dir"]}/secret-id' in listing


def test_graph_helpers_fail_closed_on_policy_ttl_and_path_drift():
    for helper in HELPERS:
        body = read(helper)
        assert "MAX_VAULT_TOKEN_TTL=1800" in body
        assert "VAULT_POLICY_MATCH" in body
        assert "docker exec" not in body
    listing = read(LIST_HELPER)
    for identity in IDENTITIES.values():
        assert f'EXPECTED_VAULT_PATH="{identity["kv_path"]}"' in listing
        assert f'EXPECTED_VAULT_POLICY="{identity["policy"]}"' in listing
    # The KV read follows the identity; the identity is re-derived and re-checked remotely.
    assert "/v1/kv/data/platform/${IDENTITY}" in listing
    assert 'case "${IDENTITY:-}" in' in listing
    assert "unknown Graph mail identity" in listing


def test_list_helper_identity_selector_is_closed_and_roles_are_opt_in():
    listing = read(LIST_HELPER)
    assert "--identity) IDENTITY=" in listing
    assert "graph|graph-read) ;;" in listing
    assert "--identity must be graph or graph-read" in listing
    assert 'VAULT_PATH="kv/platform/${IDENTITY}"' in listing
    # Roles are surfaced only on request and only as the decoded claim, never the token.
    assert "--show-roles) SHOW_ROLES=1" in listing
    assert "jq -c '.roles // []'" in listing
    assert "token_roles" in listing


def test_send_helper_is_pinned_to_the_legacy_identity_only():
    sending = read(SEND_HELPER)
    legacy = IDENTITIES["graph"]
    assert f'EXPECTED_VAULT_PATH="{legacy["kv_path"]}"' in sending
    assert f'EXPECTED_VAULT_POLICY="{legacy["policy"]}"' in sending
    assert f'{legacy["approle_dir"]}/role-id' in sending
    assert f'{legacy["approle_dir"]}/secret-id' in sending
    assert "/v1/kv/data/platform/graph" in sending
    # The read-only identity has no Mail.Send grant; the send surface must not even name it.
    assert "graph-read" not in sending
    assert "--identity" not in sending


def test_every_identity_policy_is_exact_path_read_plus_self_revoke_only():
    for identity in IDENTITIES.values():
        policy = read(f'config/vault/policies/{identity["policy"]}.hcl')
        kv_data_path = identity["kv_path"].replace("kv/", "kv/data/", 1)
        assert policy.count('path "') == 2
        assert f'path "{kv_data_path}"' in policy
        assert 'capabilities = ["read"]' in policy
        assert 'path "auth/token/revoke-self"' in policy
        assert 'capabilities = ["update"]' in policy
        assert "*" not in policy
        assert "list" not in policy


def test_provisioner_covers_both_identities_and_proves_cross_identity_denial():
    provisioner = read(PROVISIONER)
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
    assert "--identity) IDENTITY=" in provisioner
    assert "--identity must be graph or graph-read" in provisioner
    for identity in IDENTITIES.values():
        assert f'POLICY_NAME="{identity["policy"]}"' in provisioner
        assert f'ROLE_NAME="{identity["role"]}"' in provisioner
        assert f'APPROLE_DIR_DEFAULT="{identity["approle_dir"]}"' in provisioner
    assert 'POLICY_FILE="${REPO_ROOT}/config/vault/policies/${POLICY_NAME}.hcl"' in provisioner
    assert '"/v1/kv/data/platform/${KV_LEAF}"' in provisioner
    assert '"/v1/kv/data/platform/${DENIED_KV_LEAF}"' in provisioner
    # graph denies graph-read and graph-read denies graph — the pairing is explicit.
    assert 'KV_LEAF="graph"\n        DENIED_KV_LEAF="graph-read"' in provisioner
    assert 'KV_LEAF="graph-read"\n        DENIED_KV_LEAF="graph"' in provisioner


def test_root_bootstrap_surfaces_are_exactly_the_provisioner_and_the_seeder():
    for surface in (PROVISIONER, SEEDER):
        body = read(surface)
        assert ROOT_BOOTSTRAP_PATH in body
        assert "set -euo pipefail" in body
    seeder = read(SEEDER)
    # The secret is prompted without echo and travels via stdin only.
    assert "read -rs -p" in seeder
    assert "graph_client_secret=-" in seeder
    assert "[[ -t 0 ]]" in seeder
    assert "--client-secret" not in seeder
    assert "--secret" not in seeder
    assert 'KV_PATH="kv/platform/graph-read"' in seeder
    # Only key names and version are printed after the write.
    assert "keys: (.data.data | keys)" in seeder
    assert ".data.data.graph_client_secret" not in seeder
