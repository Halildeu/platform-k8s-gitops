from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Faz35EtikSpeakProvisioningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg_vault = (
            ROOT / "scripts/faz35/provision-test-pg-vault.sh"
        ).read_text()
        cls.keycloak = (
            ROOT / "scripts/faz35/provision-test-keycloak.sh"
        ).read_text()
        cls.openfga = (
            ROOT / "scripts/faz35/provision-test-openfga.sh"
        ).read_text()
        cls.preflight = (
            ROOT / "scripts/faz35/preflight-test-activation.sh"
        ).read_text()
        cls.external_secret = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/externalsecret.yaml"
        ).read_text()
        cls.secret_store = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/secretstore.yaml"
        ).read_text()
        cls.service_config = (
            ROOT / "kustomize/base/apps/etik-speak/ethics-service-config.yaml"
        ).read_text()
        cls.eso_policy = (
            ROOT / "bootstrap/vault-policies/test/etik-speak-eso.hcl"
        ).read_text()
        cls.test_root = (
            ROOT / "kustomize/overlays/test/kustomization.yaml"
        ).read_text()
        cls.public_api_ingress = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/ingress-public-api.yaml"
        ).read_text()
        cls.public_ui_ingress = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/ingress-public-ui.yaml"
        ).read_text()
        cls.netpol = (
            ROOT / "kustomize/overlays/test/activation/etik-speak/netpol.yaml"
        ).read_text()
        cls.product_quota = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/resource-quota.yaml"
        ).read_text()
        cls.public_upstream_headers = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/public-api-upstream-headers.yaml"
        ).read_text()

    def test_raw_credentials_are_not_in_docker_exec_arguments(self):
        combined = "\n".join((self.pg_vault, self.keycloak, self.openfga))
        forbidden = (
            r"-e\s+VAULT_TOKEN(?:=|\s|\\)",
            r"-e\s+ETHICS_DB_PASSWORD(?:=|\s|\\)",
            r"-e\s+PGPASSWORD(?:=|\s|\\)",
            r"--new-password\s+\$",
        )
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertNotRegex(combined, pattern)

        self.assertGreaterEqual(combined.count("IFS= read -r VAULT_TOKEN"), 5)
        self.assertIn("IFS= read -r ETHICS_DB_PASSWORD", self.pg_vault)
        self.assertIn("IFS= read -r PGPASSWORD", self.pg_vault)
        self.assertIn("IFS= read -r KC_PERSONA_PASSWORD", self.keycloak)
        for script in (self.pg_vault, self.keycloak):
            self.assertLess(script.index("set +x"), script.index("root_token"))
        self.assertNotIn("root_token", self.openfga)

    def test_pg_rerun_reuses_vault_password_instead_of_rotating(self):
        read_index = self.pg_vault.index("vault_entry_json=$(")
        random_index = self.pg_vault.index("db_password=$(openssl rand -hex 24)")
        self.assertLess(read_index, random_index)
        self.assertIn("db_password=$existing_db_password", self.pg_vault)
        self.assertIn("vault_password_write=false", self.pg_vault)
        self.assertIn("ETHICS_DB_PASSWORD=-", self.pg_vault)
        self.assertIn("exit 44", self.pg_vault)
        self.assertIn(
            "Vault read failed; refusing to classify it as missing", self.pg_vault
        )
        self.assertLess(
            self.pg_vault.index("Vault DB password read-after-write mismatch"),
            self.pg_vault.index("Create/validate the login role"),
        )

    def test_provisioners_remain_pinned_to_synthetic_test_targets(self):
        self.assertIn('[ "$PG_CONTAINER" = "platform-pg-test" ]', self.pg_vault)
        self.assertIn('[ "$VAULT_CONTAINER" = "platform-vault-test" ]', self.pg_vault)
        self.assertIn('[ "$KC_CONTAINER" = "platform-kc-test" ]', self.keycloak)
        self.assertIn('[ "$REALM" = "platform-test" ]', self.keycloak)
        self.assertIn('[ "$KUBE_CONTEXT" = "k3d-test" ]', self.openfga)
        self.assertIn('[ "$KUBE_NS" = "platform-test" ]', self.openfga)
        self.assertIn("mutation target override refused", self.openfga)
        self.assertIn("Keycloak/Vault/persona mutation target override refused", self.keycloak)
        self.assertIn("public test-gate target override refused", self.pg_vault)
        self.assertNotIn("platform-prod", "\n".join((self.pg_vault, self.keycloak, self.openfga)))

    def test_persona_secret_file_and_subject_are_bounded(self):
        self.assertIn("umask 077", self.keycloak)
        self.assertIn('chmod 600 "$PERSONA_PASSWORD_FILE"', self.keycloak)
        self.assertIn('[ ! -L "$PERSONA_PASSWORD_FILE" ]', self.keycloak)
        self.assertIn("persona password owner/mode assertion failed", self.keycloak)
        self.assertIn("secret file must be a regular non-symlink", self.pg_vault)
        self.assertRegex(
            self.openfga,
            re.compile(r"STAFF_SUBJECT.*required", re.DOTALL),
        )
        self.assertIn("STAFF_SUBJECT must be a Keycloak UUID", self.openfga)

    def test_keycloak_provisioner_mints_and_checks_real_token_contract(self):
        self.assertIn("--data-binary @-", self.keycloak)
        self.assertIn('"aud": claims.get("aud")', self.keycloak)
        self.assertIn('index("ethics-manager")', self.keycloak)
        self.assertIn('index("ethics:case:manage")', self.keycloak)
        self.assertIn(
            "synthetic access token org_id is not canonical test tenant",
            self.keycloak,
        )
        self.assertIn(
            "unset persona_password org_payload token_json access_token token_claims",
            self.keycloak,
        )
        self.assertIn("config credentials --status", self.keycloak)
        self.assertIn("ethics-org-id-mapper", self.keycloak)
        self.assertIn("optional-client-scopes", self.keycloak)
        self.assertIn("default-client-scopes", self.keycloak)
        self.assertIn("scope-mappings/realm", self.keycloak)
        self.assertIn("is not role-bound to ethics-manager", self.keycloak)
        self.assertIn("kc add-roles", self.keycloak)
        self.assertNotIn("kcadm.sh set-password", self.keycloak)
        self.assertNotIn("--new-password", self.keycloak)

    def test_openfga_model_is_content_bound_to_runtime_ledger(self):
        self.assertIn("EXPECTED_MODEL_JSON_SHA256", self.openfga)
        self.assertIn("artifact_content_digest", self.openfga)
        self.assertIn("OpenFGA source digest does not match runtime ledger", self.openfga)
        self.assertIn("select(del(.id) == $desired)", self.openfga)
        self.assertNotIn("tojson) ==", self.openfga)

    def test_database_owner_and_public_privileges_are_fail_closed(self):
        for required in (
            "existing ethics database owner is not ethics_app",
            "unexpected ethics.public schema owner",
            "REVOKE ALL ON DATABASE ethics FROM PUBLIC",
            "REVOKE ALL ON SCHEMA public FROM PUBLIC",
            '"ethics_app|f|t|f|t"',
            "\\password ethics_app",
        ):
            self.assertIn(required, self.pg_vault)

    def test_external_secret_is_eso_owned_and_runtime_selectors_are_gitops_pinned(self):
        self.assertIn("creationPolicy: Owner", self.external_secret)
        for key in ("ETHICS_DB_USERNAME", "ETHICS_DB_PASSWORD"):
            self.assertEqual(self.external_secret.count(f"secretKey: {key}"), 1)
            self.assertEqual(self.external_secret.count(f"property: {key}"), 1)
        self.assertNotIn("ERP_OPENFGA_STORE_ID", self.external_secret)
        self.assertNotIn("ERP_OPENFGA_MODEL_ID", self.external_secret)
        self.assertIn("PENDING_FAZ35_OPENFGA_STORE_ID", self.service_config)
        self.assertIn("PENDING_FAZ35_OPENFGA_MODEL_ID", self.service_config)
        self.assertEqual(self.external_secret.count("kind: ExternalSecret"), 2)
        self.assertEqual(self.external_secret.count("kind: SecretStore"), 2)
        self.assertEqual(self.external_secret.count("name: etik-speak-vault"), 2)
        self.assertNotIn("ClusterSecretStore", self.external_secret)
        self.assertEqual(self.external_secret.count("name: etik-speak-public-gate"), 2)
        self.assertEqual(self.external_secret.count("secretKey: auth"), 1)
        self.assertEqual(
            self.external_secret.count("property: EDGE_BASIC_AUTH_HTPASSWD"), 1
        )
        self.assertNotRegex(
            self.external_secret,
            r"(?i)(password|token|secret):\s*[A-Za-z0-9+/=_-]{12,}",
        )

    def test_namespaced_secret_store_uses_dedicated_least_privilege_approle(self):
        self.assertIn("kind: SecretStore", self.secret_store)
        self.assertIn("roleId: PENDING_FAZ35_VAULT_ROLE_ID", self.secret_store)
        self.assertIn("name: etik-speak-vault-approle", self.secret_store)
        self.assertNotIn("vault-platform-gitops", self.secret_store)
        self.assertIn('path "kv/data/platform/etik-speak"', self.eso_policy)
        self.assertIn('path "kv/metadata/platform/etik-speak"', self.eso_policy)
        self.assertEqual(self.eso_policy.count('capabilities = ["read"]'), 2)
        for forbidden in ("create", "update", "delete", "list", "sudo"):
            self.assertNotIn(f'"{forbidden}"', self.eso_policy)
        self.assertIn("token_no_default_policy=true", self.pg_vault)
        self.assertIn("secret_id_ttl=720h", self.pg_vault)
        self.assertIn("secret-id-accessor/destroy", self.pg_vault)
        self.assertIn('--from-file=secret-id="$approle_secret_file"', self.pg_vault)

    def test_preflight_is_read_only_and_binds_live_dependencies(self):
        self.assertIn('SSH_TARGET" = "halil@staging-sw', self.preflight)
        self.assertIn('KUBE_CONTEXT" = "k3d-test', self.preflight)
        self.assertIn('KUBE_NS" = "platform-test', self.preflight)
        for required in (
            "platform-pg-test",
            "platform-kc-test",
            "platform-vault-test",
            "etik-speak-vault-approle",
            "PENDING_FAZ35_",
            "EXPECTED_MODEL_JSON_SHA256",
            "externalsecrets.external-secrets.io",
            "http://openfga:8080/stores?page_size=1",
            "etik.acik.com",
            "speakup.acik.com",
            "ssl_verify_result",
            "OVERLAY_MUST_OVERRIDE",
            "ServerAliveCountMax=2",
            "--request-timeout=10s",
            "--max-time 10",
            "check_object_headroom services 2 2",
            "check_object_headroom configmaps 2 2",
            "check_object_headroom secrets 2 2",
            "check_object_headroom pods 4 2",
            "activation must render exactly two ExternalSecrets",
            "both public ingresses must use the synthetic test access gate",
            "one-year HSTS header",
        ):
            self.assertIn(required, self.preflight)
        self.assertNotRegex(
            self.preflight,
            r"kubectl\s+[^\n]*(apply|patch|edit|delete|rollout|set\s+image)",
        )
        self.assertNotRegex(
            self.preflight,
            r"vault\s+(kv\s+)?(put|patch|delete|write)",
        )

    def test_public_test_hosts_are_gated_and_redirect_to_https(self):
        for ingress in (self.public_api_ingress, self.public_ui_ingress):
            self.assertIn('nginx.ingress.kubernetes.io/force-ssl-redirect: "true"', ingress)
            self.assertIn("nginx.ingress.kubernetes.io/auth-type: basic", ingress)
            self.assertIn(
                "nginx.ingress.kubernetes.io/auth-secret: etik-speak-public-gate",
                ingress,
            )
        self.assertIn(
            "nginx.ingress.kubernetes.io/proxy-set-headers: "
            "platform-test/etik-speak-public-upstream-headers",
            self.public_api_ingress,
        )
        self.assertIn('Authorization: ""', self.public_upstream_headers)
        self.assertIn("X-Etik-Speak-Transport: https", self.public_upstream_headers)
        self.assertNotIn("api-gateway", self.netpol)

    def test_product_quota_has_rollout_and_repair_reserve(self):
        for expected in (
            'requests.cpu: "500m"',
            "requests.memory: 896Mi",
            'limits.cpu: "2500m"',
            "limits.memory: 2Gi",
            'pods: "6"',
        ):
            self.assertIn(expected, self.product_quota)
        self.assertNotIn("api-gateway-to-ethics-service", self.netpol)

    def test_test_quota_preserves_etikspeak_activation_and_repair_reserve(self):
        quota_patch = re.search(
            r"(?s)- target:\s+kind: ResourceQuota\s+name: platform-quota"
            r"\s+patch: \|-\s+(.*?)(?=\n  - target:|\Z)",
            self.test_root,
        )
        self.assertIsNotNone(quota_patch)
        patch = quota_patch.group(1)
        expected = {
            "/spec/hard/services": "40",
            "/spec/hard/secrets": "44",
            "/spec/hard/pods": "34",
            "/spec/hard/configmaps": "35",
        }
        for path, value in expected.items():
            with self.subTest(path=path):
                self.assertRegex(
                    patch,
                    re.escape(f"path: {path}")
                    + r"\s+value: \"?"
                    + re.escape(value)
                    + r"\"?",
                )


if __name__ == "__main__":
    unittest.main()
