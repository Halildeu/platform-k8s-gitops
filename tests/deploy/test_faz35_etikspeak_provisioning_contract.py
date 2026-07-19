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
        cls.test_root = (
            ROOT / "kustomize/overlays/test/kustomization.yaml"
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
        for script in (self.pg_vault, self.keycloak, self.openfga):
            self.assertLess(script.index("set +x"), script.index("root_token"))

    def test_pg_rerun_reuses_vault_password_instead_of_rotating(self):
        read_index = self.pg_vault.index(
            "existing_db_password=$(vault_get_field ETHICS_DB_PASSWORD"
        )
        random_index = self.pg_vault.index("db_password=$(openssl rand -hex 24)")
        self.assertLess(read_index, random_index)
        self.assertIn("db_password=$existing_db_password", self.pg_vault)
        self.assertIn("vault_password_write=false", self.pg_vault)
        self.assertIn("ETHICS_DB_PASSWORD=-", self.pg_vault)

    def test_provisioners_remain_pinned_to_synthetic_test_targets(self):
        self.assertIn('[ "$PG_CONTAINER" = "platform-pg-test" ]', self.pg_vault)
        self.assertIn('[ "$VAULT_CONTAINER" = "platform-vault-test" ]', self.pg_vault)
        self.assertIn('[ "$KC_CONTAINER" = "platform-kc-test" ]', self.keycloak)
        self.assertIn('[ "$REALM" = "platform-test" ]', self.keycloak)
        self.assertIn('[ "$KUBE_CONTEXT" = "k3d-test" ]', self.openfga)
        self.assertIn('[ "$KUBE_NS" = "platform-test" ]', self.openfga)
        self.assertNotIn("platform-prod", "\n".join((self.pg_vault, self.keycloak, self.openfga)))

    def test_persona_secret_file_and_subject_are_bounded(self):
        self.assertIn("umask 077", self.keycloak)
        self.assertIn('chmod 600 "$PERSONA_PASSWORD_FILE"', self.keycloak)
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

    def test_external_secret_is_eso_owned_and_selector_only(self):
        self.assertIn("creationPolicy: Owner", self.external_secret)
        for key in (
            "ETHICS_DB_USERNAME",
            "ETHICS_DB_PASSWORD",
            "ERP_OPENFGA_STORE_ID",
            "ERP_OPENFGA_MODEL_ID",
        ):
            self.assertEqual(self.external_secret.count(f"secretKey: {key}"), 1)
            self.assertEqual(self.external_secret.count(f"property: {key}"), 1)
        self.assertNotRegex(
            self.external_secret,
            r"(?i)(password|token|secret):\s*[A-Za-z0-9+/=_-]{12,}",
        )

    def test_preflight_is_read_only_and_binds_live_dependencies(self):
        self.assertIn('SSH_TARGET" = "halil@staging-sw', self.preflight)
        self.assertIn('KUBE_CONTEXT" = "k3d-test', self.preflight)
        self.assertIn('KUBE_NS" = "platform-test', self.preflight)
        for required in (
            "platform-pg-test",
            "platform-kc-test",
            "platform-vault-test",
            "vault-platform-gitops",
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
            "check_object_headroom configmaps 1 2",
            "check_object_headroom secrets 1 2",
            "check_object_headroom pods 4 2",
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
