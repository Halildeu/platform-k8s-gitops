from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Faz35EtikSpeakProvisioningContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg_vault = (
            ROOT / "scripts/faz35/provision-test-pg-vault.sh"
        ).read_text()
        cls.vault_accessor_lib_path = (
            ROOT / "scripts/faz35/lib-vault-accessor-inventory.sh"
        )
        cls.vault_accessor_lib = cls.vault_accessor_lib_path.read_text()
        cls.keycloak = (
            ROOT / "scripts/faz35/provision-test-keycloak.sh"
        ).read_text()
        cls.keycloak_persona_lib_path = (
            ROOT / "scripts/faz35/lib-keycloak-persona-preflight.sh"
        )
        cls.keycloak_persona_lib = cls.keycloak_persona_lib_path.read_text()
        cls.openfga = (
            ROOT / "scripts/faz35/provision-test-openfga.sh"
        ).read_text()
        cls.entitlement = (
            ROOT / "scripts/faz35/provision-test-ethic-entitlement.sh"
        ).read_text()
        cls.writer_identity = (
            ROOT / "scripts/faz35/reconcile-test-permission-writer-identity.sh"
        ).read_text()
        cls.writer_credential_repair = (
            ROOT / "scripts/faz24/repair-d35-permission-writer-credential.sh"
        ).read_text()
        cls.keycloak_binding_lib = (
            ROOT / "scripts/faz35/lib-test-keycloak-binding.sh"
        ).read_text()
        cls.role_catalog_lib = (
            ROOT / "scripts/faz35/lib-permission-role-catalog.sh"
        ).read_text()
        cls.activation_runbook = (
            ROOT / "docs/runbooks/RB-faz35-etik-speak-test-activation.md"
        ).read_text()
        cls.authz_projection_lib_path = (
            ROOT / "scripts/faz35/lib-authz-projection.sh"
        )
        cls.authz_projection_lib = cls.authz_projection_lib_path.read_text()
        cls.preflight = (
            ROOT / "scripts/faz35/preflight-test-activation.sh"
        ).read_text()
        cls.activation_artifact_lib_path = (
            ROOT / "scripts/faz35/lib-activation-artifacts.sh"
        )
        cls.activation_artifact_lib = cls.activation_artifact_lib_path.read_text()
        cls.image_attestation_lib_path = (
            ROOT / "scripts/faz35/lib-image-attestation.sh"
        )
        cls.image_attestation_lib = cls.image_attestation_lib_path.read_text()
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
        cls.model_ledger_path = (
            ROOT
            / "runtime-artifacts/openfga-model/711364fb006ac49b630a5df6f5724516fe82086c2418a26aa9e1f829e97d6c33.json"
        )
        cls.model_ledger = cls.model_ledger_path.read_text()
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
        image_sets = list(
            (ROOT / "docs/faz-35-evidence/image-set").glob("*.json")
        )
        if len(image_sets) != 1:
            raise AssertionError("expected exactly one Faz 35 image-set evidence manifest")
        cls.image_set_path = image_sets[0]
        cls.image_set = json.loads(cls.image_set_path.read_text())

    def test_raw_credentials_are_not_in_docker_exec_arguments(self):
        combined = "\n".join((self.pg_vault, self.keycloak, self.entitlement, self.openfga))
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
        self.assertIn("IFS= read -r password", self.keycloak)
        self.assertLess(self.pg_vault.index("set +x"), self.pg_vault.index("root_token"))
        self.assertNotIn("root_token", self.openfga)

    def test_pg_rerun_reuses_vault_password_instead_of_rotating(self):
        read_index = self.pg_vault.index("vault_entry_json=$(")
        random_index = self.pg_vault.index("db_password=$(openssl rand -hex 24)")
        self.assertLess(read_index, random_index)
        self.assertIn("db_password=$existing_db_password", self.pg_vault)
        self.assertIn("vault_password_write=false", self.pg_vault)
        self.assertIn("ETHICS_DB_PASSWORD=-", self.pg_vault)
        self.assertIn("return 44", self.vault_accessor_lib)
        self.assertIn(
            "Vault read failed; refusing to classify it as missing", self.pg_vault
        )
        self.assertLess(
            self.pg_vault.index("Vault DB password read-after-write mismatch"),
            self.pg_vault.index("Create/validate the login role"),
        )

    def test_pg_heredoc_sql_is_attached_to_container_stdin(self):
        self.assertIn(
            'docker exec -i "$PG_CONTAINER" psql -U postgres '
            "-v ON_ERROR_STOP=1 >/dev/null <<'SQL'",
            self.pg_vault,
        )
        self.assertIn(
            'docker exec -i "$PG_CONTAINER" psql -U postgres -d ethics '
            "-v ON_ERROR_STOP=1 >/dev/null <<'SQL'",
            self.pg_vault,
        )

    def test_provisioners_remain_pinned_to_synthetic_test_targets(self):
        self.assertIn('[ "$PG_CONTAINER" = "platform-pg-test" ]', self.pg_vault)
        self.assertIn('[ "$VAULT_CONTAINER" = "platform-vault-test" ]', self.pg_vault)
        self.assertIn('[ "$KC_CONTAINER" = "platform-kc-test" ]', self.keycloak)
        self.assertIn('[ "$REALM" = "platform-test" ]', self.keycloak)
        self.assertIn('[ "$KUBE_CONTEXT" = "k3d-test" ]', self.openfga)
        self.assertIn('[ "$KUBE_NS" = "platform-test" ]', self.openfga)
        self.assertIn("mutation target override refused", self.openfga)
        self.assertIn("entitlement mutation target override refused", self.entitlement)
        self.assertIn("Keycloak/persona mutation target override refused", self.keycloak)
        self.assertIn("public test-gate target override refused", self.pg_vault)
        self.assertIn('readonly KUBE_CONTEXT="k3d-test"', self.writer_identity)
        self.assertIn('readonly KUBE_NS="platform-test"', self.writer_identity)
        self.assertIn('readonly PG_CONTAINER="platform-pg-test"', self.writer_identity)
        self.assertIn('readonly KC_CONTAINER="platform-kc-test"', self.writer_identity)
        self.assertIn("TEST Keycloak container/loopback/issuer binding is invalid", self.writer_identity)
        self.assertIn('readonly KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"', self.writer_identity)
        self.assertIn('productionMutation: false', self.writer_identity)
        self.assertIn('historicalUser1204Mutation: false', self.writer_identity)
        self.assertNotIn(
            "platform-prod",
            "\n".join((self.pg_vault, self.keycloak, self.entitlement, self.openfga, self.writer_identity)),
        )

    def test_permission_writer_identity_is_dedicated_and_least_privilege(self):
        self.assertIn('readonly WRITER_LOCAL_USER_ID="12"', self.writer_identity)
        self.assertIn('readonly LEGACY_LOCAL_USER_ID="1204"', self.writer_identity)
        self.assertIn('readonly WRITER_EMAIL="d35-admin-persona@acik.com"', self.writer_identity)
        self.assertIn('readonly PROVISIONER_ROLE_NAME="ETIK_SPEAK_PROVISIONER"', self.writer_identity)
        self.assertIn('relation:"can_manage",object:"module:ACCESS"', self.writer_identity)
        self.assertIn('{permissions:[{type:"MODULE",key:"ACCESS",grant:"MANAGE"}]}', self.writer_identity)
        self.assertIn('.attributes.userId=[$local]', self.writer_identity)
        self.assertIn('.attributes.subscriberId=[$local]', self.writer_identity)
        self.assertIn("writer-provisioner-granule-conflict", self.writer_identity)
        self.assertIn("writer-provisioner-member-conflict", self.writer_identity)
        self.assertIn("writer-role-catalog-incomplete-or-paged", self.writer_identity)
        self.assertIn("faz35_validate_complete_role_catalog", self.writer_identity)
        self.assertIn('(.modules // {}) == {ACCESS:"MANAGE"}', self.writer_identity)
        self.assertIn('((.allowedModules // []) | sort) == ["ACCESS"]', self.writer_identity)
        self.assertIn('.superAdmin == false', self.writer_identity)
        self.assertIn('((.roles // []) | sort) == [$role]', self.writer_identity)
        self.assertIn('(.actions // {}) == {}', self.writer_identity)
        self.assertIn('(.reports // {}) == {}', self.writer_identity)
        self.assertIn('(.scopes // []) == []', self.writer_identity)
        self.assertIn('(.allowedScopes // []) == []', self.writer_identity)
        self.assertIn("credentialPreflightReady", self.writer_identity)
        self.assertIn("writer-credential-preflight-subject-mismatch", self.writer_identity)
        self.assertIn(
            "(.attributes.userId == [$legacy] and .attributes.subscriberId == [$legacy])",
            self.writer_identity,
        )
        self.assertIn("firstName,lastName,emailVerified", self.writer_identity)
        self.assertNotIn('PROVISIONER_ROLE_NAME="ADMIN"', self.writer_identity)
        self.assertNotIn("user_role_assignments", self.writer_identity)

        credential_preflight = self.writer_identity.index("CREDENTIAL_PREFLIGHT_READY=true")
        identity_alignment = self.writer_identity.index("KEYCLOAK_IDENTITY_ALIGNED=true")
        first_writer_token = self.writer_identity.index("mint_writer_token \"${TMP_DIR}/writer-token-before.json\"")
        first_role_api = self.writer_identity.index("writer-bootstrap-role-read-denied")
        self.assertLess(credential_preflight, identity_alignment)
        self.assertLess(identity_alignment, first_writer_token)
        self.assertLess(first_writer_token, first_role_api)

    def test_runbook_reconciles_and_repairs_writer_before_entitlement(self):
        reconcile = self.activation_runbook.index(
            "./scripts/faz35/reconcile-test-permission-writer-identity.sh"
        )
        repair = self.activation_runbook.index(
            "./scripts/faz24/repair-d35-permission-writer-credential.sh"
        )
        entitlement = self.activation_runbook.index(
            "./scripts/faz35/provision-test-ethic-entitlement.sh"
        )
        self.assertLess(repair, reconcile)
        self.assertLess(reconcile, entitlement)
        self.assertEqual(
            self.activation_runbook.count("--keycloak-admin-password-stdin"), 2
        )
        self.assertNotIn("KC_ADMIN_PASSWORD=\"$(", self.activation_runbook)
        self.assertIn("set +x", self.writer_identity)
        self.assertIn("set +x", self.writer_credential_repair)
        self.assertIn("--pre-identity-credential-only", self.activation_runbook)

    def test_all_keycloak_credential_paths_bind_the_exact_test_container(self):
        for script in (
            self.keycloak,
            self.entitlement,
            self.writer_identity,
            self.writer_credential_repair,
        ):
            self.assertIn("lib-test-keycloak-binding.sh", script)
            self.assertIn("faz35_assert_test_keycloak_binding", script)
        self.assertIn('HostIp":"127.0.0.1', self.keycloak_binding_lib)
        self.assertIn("/.well-known/openid-configuration", self.keycloak_binding_lib)

    def test_entitlement_uses_complete_permission_role_catalog(self):
        self.assertIn("faz35_validate_complete_role_catalog", self.entitlement)
        self.assertIn("permission role catalog is incomplete or paged", self.entitlement)
        self.assertIn('.total == (.items | length)', self.role_catalog_lib)

    def test_permission_writer_identity_never_puts_secrets_in_argv_or_evidence(self):
        self.assertIn('password@${KC_ADMIN_PASSWORD_FILE}', self.writer_identity)
        self.assertIn('username@${TMP_DIR}/writer.username', self.writer_identity)
        self.assertIn('password@${TMP_DIR}/writer.password', self.writer_identity)
        self.assertIn("IFS= read -r VAULT_TOKEN", self.writer_identity)
        self.assertIn("rawCredentialIncluded: false", self.writer_identity)
        self.assertIn("rawTokenIncluded: false", self.writer_identity)
        self.assertNotRegex(self.writer_identity, r"--data-urlencode \"password=\$\{")

    def test_ethic_entitlement_uses_canonical_writer_and_three_narrow_manager_postconditions(self):
        self.assertIn("/api/v1/roles/$role_id/granules", self.entitlement)
        self.assertIn("/api/v1/roles/$role_id/members", self.entitlement)
        self.assertIn('{type:"MODULE",key:"ETHIC",grant:"MANAGE"}', self.entitlement)
        self.assertIn("/api/v1/authz/me", self.entitlement)
        self.assertIn("wrong-org", self.entitlement)
        self.assertIn("denied", self.entitlement)
        self.assertIn("dedicated permission role contains an unrelated member", self.entitlement)
        self.assertIn("expected_member_ids", self.entitlement)
        self.assertIn("all three synthetic managers exact ETHIC=MANAGE", self.entitlement)
        self.assertIn("tenant/OpenFGA remains the sole", self.entitlement)
        self.assertIn("permission-writer Vault response is not one exact JSON document", self.entitlement)
        self.assertIn("permission-writer Vault username is not the canonical synthetic writer", self.entitlement)
        self.assertIn("permission writer is not the exact least-privilege provisioner", self.entitlement)
        self.assertIn('(.modules // {}) == {ACCESS:"MANAGE"}', self.entitlement)
        self.assertIn('.superAdmin == false', self.entitlement)
        writer_gate = self.entitlement.index("writer-authz-preflight.json")
        first_entitlement_mutation = self.entitlement.index("/api/v1/users/me/profile")
        self.assertLess(writer_gate, first_entitlement_mutation)
        self.assertNotIn("kubectl exec", self.entitlement)

    def test_ethic_entitlement_rerun_accepts_only_its_exact_prior_state(self):
        states = {
            "first-run.json": (
                {
                    "userId": "41", "subscriberId": 41, "superAdmin": False,
                    "roles": [], "modules": {}, "allowedModules": [],
                    "permissions": [], "actions": {}, "reports": {},
                    "scopes": [], "allowedScopes": [],
                },
                "ABSENT",
            ),
            "rerun.json": (
                {
                    "userId": "41", "subscriberId": 41, "superAdmin": False,
                    "roles": ["ETIK_SPEAK_MANAGER"],
                    "modules": {"ETHIC": "MANAGE"},
                    "allowedModules": ["ETHIC"], "permissions": ["ETHIC"],
                    "actions": {}, "reports": {}, "scopes": [],
                    "allowedScopes": [],
                },
                "EXACT_MANAGE",
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for filename, (payload, expected) in states.items():
                path = Path(tmp) / filename
                path.write_text(json.dumps(payload))
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; faz35_authz_projection_state "$2"',
                        "bash",
                        str(self.authz_projection_lib_path),
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.stdout.strip(), expected)

            empty = states["first-run.json"][0]
            exact_manage = states["rerun.json"][0]
            for filename, payload in {
                "partial.json": {**exact_manage, "allowedModules": []},
                "broader.json": {**exact_manage, "modules": {"ETHIC": "ADMIN"}},
                "identity-drift.json": {**empty, "userId": "42"},
                "super-admin.json": {**empty, "superAdmin": True},
                "unrelated-role.json": {**empty, "roles": ["ADMIN"]},
                "unrelated-module.json": {
                    **empty,
                    "modules": {"ACCESS": "MANAGE"},
                    "allowedModules": ["ACCESS"],
                    "permissions": ["ACCESS"],
                },
                "unrelated-scope.json": {
                    **empty,
                    "scopes": ["tenant:all"],
                    "allowedScopes": ["tenant:all"],
                },
                "missing-authority-field.json": {
                    key: value
                    for key, value in empty.items()
                    if key != "permissions"
                },
            }.items():
                path = Path(tmp) / filename
                path.write_text(json.dumps(payload))
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; faz35_authz_projection_state "$2"',
                        "bash",
                        str(self.authz_projection_lib_path),
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)

        self.assertIn('>"$TMP_DIR/$label-projection-before"', self.entitlement)
        self.assertIn('= EXACT_MANAGE ] || continue', self.entitlement)
        self.assertIn("ETHIC projection is not linked to the exact dedicated role", self.entitlement)
        self.assertIn("missing_member_ids", self.entitlement)
        self.assertIn("synthetic persona authority differs from the exact allowlist", self.authz_projection_lib)
        self.assertIn("synthetic persona authority document is incomplete or malformed", self.authz_projection_lib)
        self.assertNotIn("gained non-canonical permission-service authority", self.entitlement)

    def test_authz_member_identity_must_match_local_user_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authz.json"
            path.write_text(json.dumps({
                "userId": "41",
                "subscriberId": 41,
                "modules": {},
                "allowedModules": [],
            }))
            exact = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_authz_member_id "$2" "$3"',
                    "bash",
                    str(self.authz_projection_lib_path),
                    str(path),
                    "41",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(exact.stdout.strip(), "41")
            for wrong_id in ("42", "not-numeric"):
                mismatch = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; faz35_authz_member_id "$2" "$3"',
                        "bash",
                        str(self.authz_projection_lib_path),
                        str(path),
                        wrong_id,
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(mismatch.returncode, 0)

            paired_wrong_path = Path(tmp) / "paired-wrong-authz.json"
            paired_wrong_path.write_text(json.dumps({
                "userId": "42",
                "subscriberId": 42,
                "modules": {},
                "allowedModules": [],
            }))
            paired_wrong = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_authz_member_id "$2" "$3"',
                    "bash",
                    str(self.authz_projection_lib_path),
                    str(paired_wrong_path),
                    "41",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(paired_wrong.returncode, 0)

        identity_check = self.authz_projection_lib.index("authz identity differs from the canonical local profile")
        activation = self.authz_projection_lib.index("/api/v1/users/$user_id/activation")
        self.assertLess(identity_check, activation)
        self.assertIn("target_user_id=$(faz35_activate_verified_profiles", self.entitlement)
        self.assertIn(
            'faz35_authz_member_id "$TMP_DIR/$label-authz-after.json" "$expected_user_id"',
            self.entitlement,
        )

    def test_openfga_tuple_read_envelope_is_exact_before_mutation(self):
        self.assertIn(
            'has("tuples")',
            self.openfga,
        )
        self.assertIn(
            '(.key | has("object") and has("relation") and has("user"))',
            self.openfga,
        )
        self.assertIn("direct tuple read response schema mismatch", self.openfga)
        self.assertNotIn("$page.tuples[]?", self.openfga)

        validator = r'''
          type == "object" and
          has("tuples") and
          ((keys - ["continuation_token", "tuples"]) | length) == 0 and
          ((has("continuation_token") | not) or
           ((.continuation_token | type) == "string")) and
          (.tuples | type) == "array" and
          all(.tuples[];
            type == "object" and
            ((keys | sort) == ["key", "timestamp"]) and
            (.timestamp | type) == "string" and (.timestamp | length) > 0 and
            (.key | type) == "object" and
            ((.key | keys - ["condition", "object", "relation", "user"]) | length) == 0 and
            (.key | has("object") and has("relation") and has("user")) and
            ((.key | has("condition") | not) or .key.condition == null) and
            (.key.object | type) == "string" and (.key.object | length) > 0 and
            (.key.relation | type) == "string" and (.key.relation | length) > 0 and
            (.key.user | type) == "string" and (.key.user | length) > 0
          )
        '''
        valid_pages = [
            {"continuation_token": "", "tuples": []},
            {"tuples": []},
            {
                "tuples": [{
                    "key": {
                        "object": "ethics_product:7",
                        "relation": "can_manage",
                        "user": "user:41",
                    },
                    "timestamp": "2026-07-19T12:00:00Z",
                }],
            },
        ]
        invalid_pages = [
            {},
            {"continuation_token": "", "tuples": None},
            {"continuation_token": None, "tuples": []},
            {"continuation_token": "", "tuples": [{"key": {}}]},
        ]
        for page in valid_pages:
            result = subprocess.run(
                ["jq", "-e", validator],
                input=json.dumps(page),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        for page in invalid_pages:
            result = subprocess.run(
                ["jq", "-e", validator],
                input=json.dumps(page),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_identity_mismatch_executes_zero_activation_http_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for label, local_id, authz_id in (
                ("target", 41, 41),
                ("wrong-org", 42, 99),
                ("denied", 43, 43),
            ):
                (tmp_path / f"{label}-user-id").write_text(str(local_id))
                (tmp_path / f"{label}-user.json").write_text(json.dumps({
                    "id": local_id,
                    "enabled": False,
                }))
                (tmp_path / f"{label}-authz-before.json").write_text(json.dumps({
                    "userId": str(authz_id),
                    "subscriberId": authz_id,
                    "modules": {},
                    "allowedModules": [],
                }))

            marker = tmp_path / "http-called"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; marker=$4; '
                    'http_status() { printf called >"$marker"; printf 200; }; '
                    'faz35_activate_verified_profiles "$2" https://test.invalid "$3"',
                    "bash",
                    str(self.authz_projection_lib_path),
                    str(tmp_path),
                    str(tmp_path / "writer-auth.curl"),
                    str(marker),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_persona_secret_file_and_subject_are_bounded(self):
        self.assertIn("umask 077", self.keycloak)
        self.assertIn('prepare_synthetic_password_file "$PERSONA_PASSWORD_FILE" persona', self.keycloak)
        self.assertIn('[ ! -L "$file" ]', self.keycloak)
        self.assertIn("persona password owner/mode assertion failed", self.keycloak)
        self.assertIn("existing synthetic profile drifted from its exact contract", self.keycloak)
        self.assertIn("synthetic profile postcondition is not exact", self.keycloak)
        self.assertIn("canonical synthetic persona username is ambiguous", self.keycloak)
        self.assertIn("synthetic username is ambiguous", self.keycloak)
        manager_profile_gate = self.keycloak.index(
            'assert_persona_profile_precondition "$persona_id"'
        )
        manager_role_mutation = self.keycloak.index(
            'kc add-roles -r "$REALM" --uusername "$PERSONA_USERNAME"'
        )
        self.assertLess(manager_profile_gate, manager_role_mutation)
        self.assertLess(
            self.keycloak.index("prepare_synthetic_password_file \"$PERSONA_PASSWORD_FILE\""),
            self.keycloak.index("if ! kc get roles/ethics-manager"),
        )
        self.assertIn("secret file must be a regular non-symlink", self.pg_vault)
        self.assertRegex(
            self.openfga,
            re.compile(r"STAFF_SUBJECT=.*WRONG_ORG_SUBJECT=.*DENIED_SUBJECT", re.DOTALL),
        )
        self.assertIn("must be a Keycloak UUID from provision-test-keycloak.sh", self.openfga)
        self.assertIn("lib-test-keycloak-binding.sh", self.openfga)
        self.assertIn("assert_subject_persona_binding", self.openfga)
        self.assertIn("exact least-privilege Keycloak persona contract", self.openfga)
        self.assertIn('"password@$password_file"', self.openfga)
        for exact_claim in (
            '.azp == "frontend"',
            '(.aud | sort)',
            '(.scope | split(" ") | sort)',
            '(.roles | sort)',
            '(.resource_roles | keys | sort) == ["account"]',
            '(.groups | type) == "array"',
            '(.has_authorization == false)',
        ):
            self.assertIn(exact_claim, self.openfga)
        subject_proof = self.openfga.index(
            'assert_subject_persona_binding "$DENIED_USERNAME"'
        )
        first_openfga_discovery = self.openfga.index("stores=$(collect_pages")
        self.assertLess(subject_proof, first_openfga_discovery)

    def test_entitlement_materializes_and_activates_canonical_local_users(self):
        self.assertIn("/api/v1/users/me/profile", self.entitlement)
        self.assertIn('.message == "ACCOUNT_DISABLED"', self.entitlement)
        self.assertIn("/api/v1/users/by-email", self.entitlement)
        self.assertIn("/api/v1/users/$user_id/activation", self.authz_projection_lib)
        self.assertIn("$label active local profile postcondition failed", self.authz_projection_lib)
        self.assertIn("target_user_id=$(faz35_activate_verified_profiles", self.entitlement)
        self.assertIn("$label authz identity differs from the canonical local profile", self.authz_projection_lib)
        self.assertNotIn("target_user_id=$(jq -r '.userId'", self.entitlement)
        self.assertIn('numeric subscriberId is missing', self.authz_projection_lib)
        self.assertIn('userId and subscriberId differ', self.authz_projection_lib)

    def test_keycloak_provisioner_mints_and_checks_real_token_contract(self):
        self.assertIn("--data-binary @-", self.keycloak)
        self.assertIn('KC_TOKEN_BASE_URL="${KC_TOKEN_BASE_URL:-http://127.0.0.1:8082}"', self.keycloak)
        self.assertIn("command -v curl", self.keycloak)
        self.assertNotIn("command -v curl >/dev/null 2>&1 || exit 70", self.keycloak)
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
        self.assertEqual(
            self.keycloak.count('config.\"introspection.token.claim\"=true'),
            2,
        )
        self.assertIn(
            '"included.client.audience":"ethics-manager","introspection.token.claim":"true","userinfo.token.claim":"false"',
            self.keycloak,
        )
        self.assertIn(
            '"id.token.claim":"false","introspection.token.claim":"true","jsonType.label":"String"',
            self.keycloak,
        )
        self.assertIn("optional-client-scopes", self.keycloak)
        self.assertIn("default-client-scopes", self.keycloak)
        self.assertIn("scope-mappings/realm", self.keycloak)
        self.assertIn("role mapping is not the exact ethics-manager allowlist", self.keycloak)
        self.assertIn("realm role drifted from the non-composite allowlist", self.keycloak)
        self.assertIn("mapper set drifted from the exact allowlist", self.keycloak)
        self.assertIn("must not contain protocol mappers", self.keycloak)
        self.assertIn("has unexpected realm/client role mappings", self.keycloak)
        self.assertIn("must not inherit privileges from a group", self.keycloak)
        self.assertIn("has unexpected effective/composite realm roles", self.keycloak)
        self.assertIn("has unexpected effective frontend client roles", self.keycloak)
        self.assertIn("has unexpected client-role scope mappings", self.keycloak)
        self.assertIn("resource_roles", self.keycloak)
        self.assertIn("contains a forbidden audience", self.keycloak)
        self.assertIn("kc add-roles", self.keycloak)
        self.assertNotIn("kcadm.sh set-password", self.keycloak)
        self.assertNotIn("--new-password", self.keycloak)

    def test_openfga_model_is_content_bound_to_runtime_ledger(self):
        self.assertIn("EXPECTED_MODEL_JSON_SHA256", self.openfga)
        self.assertIn("EXPECTED_MODEL_FGA_SHA256", self.openfga)
        self.assertIn("artifact_content_digest", self.openfga)
        self.assertIn("OpenFGA source model digest mismatch", self.openfga)
        self.assertIn(
            "canonical OpenFGA model digest does not match runtime ledger",
            self.openfga,
        )
        self.assertIn("select(del(.id) == $desired)", self.openfga)
        self.assertNotIn("tojson) ==", self.openfga)

        compiled_model = json.loads(
            (
                ROOT
                / "bootstrap/openfga/faz35-etik-speak/authorization-model-v1.json"
            ).read_text()
        )
        canonical_model = json.dumps(
            compiled_model,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        canonical_digest = hashlib.sha256(canonical_model).hexdigest()
        ledger = json.loads(self.model_ledger)
        self.assertEqual(
            ledger["artifact_content_digest"],
            f"sha256:{canonical_digest}",
        )
        self.assertEqual(self.model_ledger_path.stem, canonical_digest)
        self.assertIn(
            f'EXPECTED_MODEL_JSON_SHA256="{canonical_digest}"',
            self.preflight,
        )
        self.assertIn(
            "jq -j -cS '.authorization_model | del(.id)'",
            self.preflight,
        )

        # Exercise the exact OpenFGA GET response envelope. The server's JSON
        # whitespace and jq's normal output newline are transport details; only
        # the sorted compact authorization_model without its runtime id is
        # content-addressed.
        live_response = {
            "authorization_model": {
                "id": "01KW0EJTM60YGZTEKNGS7PDPNP",
                **compiled_model,
            }
        }
        canonicalized_live = subprocess.run(
            ["jq", "-j", "-cS", ".authorization_model | del(.id)"],
            input=json.dumps(live_response, indent=2).encode(),
            check=True,
            capture_output=True,
        ).stdout
        self.assertFalse(canonicalized_live.endswith(b"\n"))
        self.assertEqual(
            hashlib.sha256(canonicalized_live).hexdigest(),
            canonical_digest,
        )

        fga_source = (
            ROOT / "runtime-artifacts/faz35-etik-speak/authorization-model-v1.fga"
        ).read_bytes()
        fga_digest = hashlib.sha256(fga_source).hexdigest()
        self.assertNotEqual(fga_digest, canonical_digest)
        self.assertIn(
            f'EXPECTED_MODEL_FGA_SHA256="{fga_digest}"',
            self.openfga,
        )

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
        self.assertIn('"selector_kind": "kubernetes-configmap"', self.model_ledger)
        self.assertIn('"name": "ethics-service-config"', self.model_ledger)
        self.assertIn('"store_id_field": "ERP_OPENFGA_STORE_ID"', self.model_ledger)
        self.assertIn('"model_id_field": "ERP_OPENFGA_MODEL_ID"', self.model_ledger)
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
        self.assertIn("existing AppRole credentials could not be enumerated", self.pg_vault)
        self.assertNotIn('grep -Eqi "no value found|not found" "$accessor_error_file"', self.pg_vault)
        self.assertIn("vault_accessor_inventory_classify", self.pg_vault)
        self.assertIn("post-rotation AppRole credential enumeration failed", self.pg_vault)
        self.assertIn("stale AppRole credential accessor remains", self.pg_vault)
        self.assertIn("ethics_app inherits an unexpected role", self.pg_vault)
        self.assertIn("ethics_app owns an unexpected default ACL", self.pg_vault)
        self.assertIn("ethics_app has an unexpected ACL outside ethics in", self.pg_vault)
        self.assertIn("ethics_app owns an object outside the dedicated ethics database", self.pg_vault)
        self.assertIn("inbound or outbound role membership", self.pg_vault)
        self.assertIn("udt_name='_aclitem'", self.pg_vault)
        self.assertIn("table_name <> 'pg_init_privs'", self.pg_vault)
        self.assertIn("NOINHERIT", self.pg_vault)
        self.assertIn('--from-file=secret-id="$approle_secret_file"', self.pg_vault)

    def test_vault_accessor_inventory_classifier_is_exact_and_fail_closed(self):
        def classify(status: int, stdout: bytes, stderr: bytes):
            with tempfile.TemporaryDirectory() as directory:
                output_path = Path(directory) / "stdout"
                error_path = Path(directory) / "stderr"
                output_path.write_bytes(stdout)
                error_path.write_bytes(stderr)
                return subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; vault_accessor_inventory_classify "$2" "$3" "$4"',
                        "bash",
                        str(self.vault_accessor_lib_path),
                        str(status),
                        str(output_path),
                        str(error_path),
                    ],
                    check=False,
                    capture_output=True,
                )

        success = classify(0, b'["accessor-a"]\n', b"")
        self.assertEqual(success.returncode, 0)
        self.assertEqual(success.stdout, b'["accessor-a"]\n')

        empty = classify(2, b'{ \n }\n', b"")
        self.assertEqual(empty.returncode, 0)
        self.assertEqual(empty.stdout, b"[]")

        for status, stdout, stderr in (
            (2, b"{}", b"warning"),
            (2, b'{"errors":[]}', b""),
            (2, b'["accessor-a"]', b""),
            (1, b"", b"not found"),
            (1, b"{}", b""),
            (0, b"{}", b""),
            (0, b'["accessor-a"]', b"warning"),
            (0, b'[""]', b""),
            (0, b"[null]", b""),
            (0, b'{}\n["accessor-a"]\n', b""),
            (0, b'[""]\n["accessor-a"]\n', b""),
            (0, b'[null]\n["accessor-a"]\n', b""),
            (0, b'["accessor-a"]\n["accessor-b"]\n', b""),
        ):
            with self.subTest(status=status, stdout=stdout, stderr=stderr):
                result = classify(status, stdout, stderr)
                self.assertEqual(result.returncode, 45)
                self.assertEqual(result.stdout, b"")

    def test_generic_vault_json_and_exact_missing_classifiers_are_behavioral(self):
        def classify(function: str, status: int, stdout: bytes, stderr: bytes, extra: str):
            with tempfile.TemporaryDirectory() as directory:
                output_path = Path(directory) / "stdout"
                error_path = Path(directory) / "stderr"
                output_path.write_bytes(stdout)
                error_path.write_bytes(stderr)
                return subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; "$2" "$3" "$4" "$5" "$6"',
                        "bash",
                        str(self.vault_accessor_lib_path),
                        function,
                        str(status),
                        str(output_path),
                        str(error_path),
                        extra,
                    ],
                    check=False,
                    capture_output=True,
                )

        valid = classify(
            "vault_json_document_classify",
            0,
            b'{"data":{"secret_id":"value"}}\n',
            b"",
            '.data.secret_id | type == "string" and length > 0',
        )
        self.assertEqual(valid.returncode, 0)
        self.assertEqual(valid.stdout, b'{"data":{"secret_id":"value"}}\n')
        for stdout, stderr in (
            (b'{"data":{"secret_id":"value"}}\n{}\n', b""),
            (b'{"data":{"secret_id":"value"}}\n', b"warning"),
            (b'{"data":{"secret_id":""}}\n', b""),
        ):
            rejected = classify(
                "vault_json_document_classify",
                0,
                stdout,
                stderr,
                '.data.secret_id | type == "string" and length > 0',
            )
            self.assertEqual(rejected.returncode, 45)
            self.assertEqual(rejected.stdout, b"")

        missing = classify(
            "vault_kv_document_classify",
            2,
            b"",
            b"No value found at kv/data/platform/etik-speak\n",
            "No value found at kv/data/platform/etik-speak",
        )
        self.assertEqual(missing.returncode, 44)
        self.assertEqual(missing.stdout, b"null")
        ambiguous_missing = classify(
            "vault_kv_document_classify",
            2,
            b"",
            b"warning\nNo value found at kv/data/platform/etik-speak\n",
            "No value found at kv/data/platform/etik-speak",
        )
        self.assertEqual(ambiguous_missing.returncode, 45)
        self.assertEqual(ambiguous_missing.stdout, b"")

    def test_negative_personas_are_bound_to_openfga_deny_postconditions(self):
        self.assertIn("ETHICS_WRONG_ORG_SUBJECT=$wrong_org_id", self.keycloak)
        self.assertIn("ETHICS_DENIED_SUBJECT=$denied_id", self.keycloak)
        self.assertIn("WRONG_ORG_SUBJECT", self.openfga)
        self.assertIn("DENIED_SUBJECT", self.openfga)
        self.assertIn("collect_direct_relations", self.openfga)
        self.assertIn("assert_direct_relation_allowlist", self.openfga)
        self.assertIn("page violates the exact response contract", self.openfga)
        self.assertNotIn("$page[$key] // []", self.openfga)
        self.assertIn('has("continuation_token")', self.openfga)
        self.assertIn("wrong-org-canonical", self.openfga)
        self.assertIn("denied-persona", self.openfga)
        self.assertIn("positive-least-privilege", self.openfga)
        for sensitive_relation in (
            "viewer",
            "triager",
            "handler",
            "technical_admin",
            "evidence_approver",
            "ethics_product_admin",
            "content_denied",
            "case_viewer",
            "case_triager",
            "case_handler",
            "evidence_reveal_approved",
        ):
            self.assertIn(sensitive_relation, self.openfga)
        self.assertIn("collect_pages", self.openfga)
        self.assertIn("multiple OpenFGA stores use the canonical", self.openfga)
        self.assertIn("multiple exact Etik Speak authorization models", self.openfga)
        self.assertIn("RECUSAL_SENTINEL_CASE_ID", self.openfga)
        self.assertIn("explicit recusal sentinel did not fail closed", self.openfga)

    def test_all_vault_json_credentials_use_single_document_classification(self):
        self.assertIn("vault_json_document_classify", self.pg_vault)
        self.assertIn("vault_kv_document_classify", self.pg_vault)
        self.assertNotIn("vault_json_document_classify", self.keycloak)
        self.assertNotIn('grep -Eqi "no value found|not found"', self.pg_vault)
        self.assertGreaterEqual(self.pg_vault.count('>"$vault_output_file" 2>"$vault_error_file"'), 3)

    def test_pg_and_keycloak_preconditions_precede_remote_mutation(self):
        self.assertLess(
            self.pg_vault.index("preflight_existing_pg_role"),
            self.pg_vault.index("vault_root_token=$("),
        )
        self.assertIn("pg_shdepend", self.pg_vault)
        self.assertIn("pg_auth_members WHERE roleid=", self.pg_vault)
        self.assertIn("KCADM_CONFIG=$(docker exec", self.keycloak)
        self.assertIn('rm -f "$KCADM_CONFIG"', self.keycloak)
        self.assertIn('KEYCLOAK_ADMIN_PASSWORD_FILE', self.keycloak)
        self.assertIn('--config "$KCADM_CONFIG"', self.keycloak)
        self.assertIn("isolated Keycloak admin login failed", self.keycloak)
        self.assertIn("intentionally lacks manage-realm", self.keycloak)
        direct_kcadm_calls = re.findall(
            r'docker exec -i "\$KC_CONTAINER" "\$KCADM"(.*?>/dev/null)',
            self.keycloak,
            re.DOTALL,
        )
        self.assertEqual(len(direct_kcadm_calls), 5)
        for call in direct_kcadm_calls:
            self.assertIn('--config "$KCADM_CONFIG"', call)
        self.assertNotIn("head -1", self.keycloak)
        self.assertNotRegex(self.keycloak, r"awk[^\n]*\{print \$1; exit\}")
        self.assertGreaterEqual(self.keycloak.count("| sed -n '1p'"), 3)
        self.assertIn("canonical synthetic persona username is ambiguous", self.keycloak)
        self.assertIn("synthetic username is ambiguous", self.keycloak)
        self.assertIn("PostgreSQL database inventory failed before ACL validation", self.pg_vault)
        self.assertIn("PostgreSQL database inventory is empty, malformed, or duplicated", self.pg_vault)
        self.assertIn("json_agg(datname ORDER BY datname)", self.pg_vault)
        self.assertIn("jq -j '.[] | .,\"\\u0000\"'", self.pg_vault)
        self.assertIn("read -r -d '' database_name", self.pg_vault)
        self.assertIn("PostgreSQL database inventory framing failed", self.pg_vault)
        self.assertNotIn('done < <(docker exec "$PG_CONTAINER"', self.pg_vault)
        self.assertIn("client inventory could not be read", self.keycloak)
        self.assertIn("client inventory is empty or malformed", self.keycloak)
        self.assertNotIn("done < <(kc get clients", self.keycloak)
        self.assertNotIn("2>/dev/null || printf '[]'", self.keycloak)
        self.assertNotRegex(
            self.keycloak,
            r"(default|optional)-client-scopes[^\n]*\n[^\n]*\|\| true",
        )
        self.assertNotIn("--arg include ", self.keycloak)
        self.assertNotIn("$include and", self.keycloak)
        self.assertGreaterEqual(self.keycloak.count("--arg include_value"), 2)
        self.assertIn("kc_get_scope_client_mappings()", self.keycloak)
        self.assertEqual(
            self.keycloak.count('kc_get_scope_client_mappings "$scope_id"'), 2
        )
        self.assertIn(
            "Resource not found for url: http://localhost:8080/admin/realms/$REALM/client-scopes/$scope_id/scope-mappings/clients",
            self.keycloak,
        )
        self.assertIn("client-scope mapping lookup requires a canonical UUID", self.keycloak)

    def test_complete_persona_drift_stops_before_every_realm_mutation(self):
        self.assertIn("lib-keycloak-persona-preflight.sh", self.keycloak)
        first_realm_mutation = self.keycloak.index('kc create roles -r "$REALM"')
        for call in (
            'preflight_existing_persona "$PERSONA_USERNAME"',
            'preflight_existing_persona "$WRONG_ORG_USERNAME"',
            'preflight_existing_persona "$DENIED_USERNAME"',
        ):
            self.assertLess(self.keycloak.index(call), first_realm_mutation)

        drifted = {
            "users": [{"id": "persona-id"}],
            "profile": {
                "id": "persona-id",
                "username": "ethics-manager-test",
                "email": "ethics-manager-test@test.invalid",
                "firstName": "Ethics",
                "lastName": "Manager",
                "enabled": True,
                "emailVerified": True,
                "requiredActions": [],
                "attributes": {"org_id": ["wrong-org"]},
            },
            "roleMappings": {"realmMappings": [], "clientMappings": {}},
            "groups": [],
            "effectiveRealm": [],
            "effectiveClients": [{"clientId": "account", "roles": []}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            marker = Path(tmp) / "mutation-called"
            snapshot.write_text(json.dumps(drifted))
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; '
                    'mutation() { : >"$8"; }; '
                    'faz35_validate_keycloak_persona_snapshot '
                    '"$2" "$3" "$4" "$5" "$6" "$7" && mutation',
                    "bash",
                    str(self.keycloak_persona_lib_path),
                    str(snapshot),
                    "ethics-manager-test",
                    "ethics-manager-test@test.invalid",
                    "Ethics",
                    "Manager",
                    "00000000-0000-0000-0000-000000000001",
                    str(marker),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_pg_preflight_preserves_only_dedicated_database_rerun_state(self):
        self.assertIn("OR d.dbid=ethics_db_oid", self.pg_vault)
        self.assertNotIn("current_database()='ethics' AND d.dbid=ethics_db_oid", self.pg_vault)
        self.assertIn(
            "acl_catalog.table_name='pg_database' AND acl_catalog.column_name='datacl'",
            self.pg_vault,
        )
        self.assertIn("WHERE x.grantee=$1 AND c.oid <> $2", self.pg_vault)
        self.assertIn(
            "ethics_app has an unexpected ACL outside ethics",
            self.pg_vault,
        )

    def test_authority_and_persona_password_files_are_strictly_bounded(self):
        self.assertIn("Vault init file must be a readable regular non-symlink", self.pg_vault)
        self.assertIn("Vault init file must be invoking-user-owned mode 600", self.pg_vault)
        self.assertIn("$label password fails the length/format policy", self.keycloak)
        self.assertIn("prepare_synthetic_password_file", self.keycloak)
        self.assertIn("existing secret file was not invoking-user-owned mode 600", self.pg_vault)
        self.assertIn("public gate password fails the canonical length/format policy", self.pg_vault)

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
            'if [ "$PREFLIGHT_STAGE" = foundation ]',
            "check_object_headroom secrets 1 1",
            "check_object_headroom services 2 2",
            "check_object_headroom configmaps 2 2",
            "check_object_headroom secrets 2 2",
            "check_object_headroom pods 4 2",
            "activation must render exactly two ExternalSecrets",
            "both public ingresses must use the synthetic test access gate",
            "one-year HSTS header",
            "foundation provisioning refuses an included Etik Speak activation root",
            "foundation provisioning refuses an early shared test frontend pin",
            "foundation provisioning refuses existing or partial Etik Speak activation resources",
            "secretstore/etik-speak-vault",
            "secret/ethics-service-secrets",
            "secret/etik-speak-public-gate",
            "priorityclass/etik-speak-test",
            "faz35_assert_root_activation_binding",
            "faz35_assert_rendered_deployment_image",
            "image set content does not match its content-addressed filename",
            "image set schema/source-head binding is invalid",
            'kustomize build "$REPO_ROOT/kustomize/overlays/test"',
            'EXPECTED_OPENFGA_STORE_NAME="platform-test-etik-speak"',
            'EXPECTED_OPENFGA_STORE_REF="platform-test/etik-speak"',
            'runtime ledger is not bound to the verified canonical TEST store/model',
            'pinned OpenFGA store is not the canonical live Etik Speak TEST store',
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

    def test_activation_artifact_helpers_reject_stale_duplicate_and_unbound_state(self):
        manifest = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: ethics-service
spec:
  template:
    spec:
      containers:
        - name: ethics-service
          image: ghcr.io/halildeu/platform-backend-ethics-service@sha256:{digest}
"""
        expected_digest = "a" * 64
        expected_image = (
            "ghcr.io/halildeu/platform-backend-ethics-service@sha256:"
            + expected_digest
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "rendered.yaml"
            manifest_path.write_text(manifest.format(digest=expected_digest))
            exact = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_assert_rendered_deployment_image "$2" "$3" "$4"',
                    "bash",
                    str(self.activation_artifact_lib_path),
                    str(manifest_path),
                    "ethics-service",
                    expected_image,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(exact.returncode, 0)

            stale = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_assert_rendered_deployment_image "$2" "$3" "$4"',
                    "bash",
                    str(self.activation_artifact_lib_path),
                    str(manifest_path),
                    "ethics-service",
                    expected_image.replace("a" * 64, "b" * 64),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(stale.returncode, 0)

            manifest_path.write_text(
                manifest.format(digest=expected_digest)
                + "        - name: stale-sidecar\n"
                + f"          image: {expected_image}\n"
            )
            duplicate = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_assert_rendered_deployment_image "$2" "$3" "$4"',
                    "bash",
                    str(self.activation_artifact_lib_path),
                    str(manifest_path),
                    "ethics-service",
                    expected_image,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(duplicate.returncode, 0)

            root_path = Path(directory) / "kustomization.yaml"
            root_path.write_text("resources:\n  - activation/etik-speak\n")
            bound = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; faz35_assert_root_activation_binding "$2"',
                    "bash",
                    str(self.activation_artifact_lib_path),
                    str(root_path),
                ],
                check=False,
            )
            self.assertEqual(bound.returncode, 0)
            for value in (
                "resources:\n",
                "resources:\n  - activation/etik-speak\n  - activation/etik-speak\n",
            ):
                root_path.write_text(value)
                rejected = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; faz35_assert_root_activation_binding "$2"',
                        "bash",
                        str(self.activation_artifact_lib_path),
                        str(root_path),
                    ],
                    check=False,
                    capture_output=True,
                )
                self.assertNotEqual(rejected.returncode, 0)

    def test_image_set_is_content_addressed_source_bound_and_rendered_exactly(self):
        canonical = (
            json.dumps(self.image_set, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), self.image_set_path.stem)
        self.assertEqual(self.image_set["schema_version"], "faz35-test-image-set-v1")
        self.assertEqual(
            self.image_set["images"]["ethics_service"]["source_head"],
            self.image_set["source_heads"]["backend"],
        )
        for name in ("public_web", "manager_web"):
            self.assertEqual(
                self.image_set["images"][name]["source_head"],
                self.image_set["source_heads"]["web"],
            )

        rendered = subprocess.run(
            ["kustomize", "build", str(ROOT / "kustomize/overlays/test/activation/etik-speak")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "activation.yaml"
            manifest_path.write_text(rendered)
            for deployment, image_key in (
                ("ethics-service", "ethics_service"),
                ("etik-speak-public", "public_web"),
            ):
                image = self.image_set["images"][image_key]
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'source "$1"; faz35_assert_rendered_deployment_image "$2" "$3" "$4"',
                        "bash",
                        str(self.activation_artifact_lib_path),
                        str(manifest_path),
                        deployment,
                        f'{image["repository"]}@{image["digest"]}',
                    ],
                    check=False,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0)

    def test_image_attestation_binds_digest_source_workflow_and_run(self):
        digest = "a" * 64
        source_head = "b" * 40
        run_url = "https://github.com/Halildeu/platform-backend/actions/runs/123"
        run_json = {
            "databaseId": 123,
            "headSha": source_head,
            "status": "completed",
            "conclusion": "success",
            "event": "workflow_dispatch",
            "url": run_url,
        }

        def verify(subject_digest: str, invocation_id: str):
            attestation_json = [{
                "verificationResult": {
                    "statement": {
                        "predicateType": "https://slsa.dev/provenance/v1",
                        "subject": [{
                            "name": "ghcr.io/halildeu/platform-backend-ethics-service",
                            "digest": {"sha256": subject_digest},
                        }],
                        "predicate": {
                            "runDetails": {"metadata": {"invocationId": invocation_id}}
                        },
                    }
                }
            }]
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; '
                    'gh() { '
                    'if [ "$1" = api ]; then printf "%s" "$RUN_JSON"; '
                    'else printf "%s" "$ATTESTATION_JSON"; fi; '
                    '}; '
                    'faz35_verify_image_attestation '
                    '"ghcr.io/halildeu/platform-backend-ethics-service@sha256:$2" '
                    'Halildeu/platform-backend .github/workflows/ci-image-push.yml "$3" 123',
                    "bash",
                    str(self.image_attestation_lib_path),
                    digest,
                    source_head,
                ],
                env={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
                    "RUN_JSON": json.dumps(run_json, separators=(",", ":")),
                    "ATTESTATION_JSON": json.dumps(attestation_json, separators=(",", ":")),
                },
                capture_output=True,
                text=True,
            )

        valid = verify(digest, f"{run_url}/attempts/1")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertNotEqual(verify("c" * 64, f"{run_url}/attempts/1").returncode, 0)
        self.assertNotEqual(
            verify(
                digest,
                "https://github.com/Halildeu/platform-backend/actions/runs/999/attempts/1",
            ).returncode,
            0,
        )
        for required in (
            "--signer-workflow",
            "--source-digest",
            "--deny-self-hosted-runners",
            "https://slsa.dev/provenance/v1",
        ):
            self.assertIn(required, self.image_attestation_lib)

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
