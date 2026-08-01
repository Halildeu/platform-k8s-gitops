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
        cls.openfga_normalization_lib_path = (
            ROOT / "scripts/faz35/lib-openfga-model-normalization.sh"
        )
        cls.openfga_normalization_lib = cls.openfga_normalization_lib_path.read_text()
        cls.entitlement = (
            ROOT / "scripts/faz35/provision-test-ethic-entitlement.sh"
        ).read_text()
        cls.writer_identity = (
            ROOT / "scripts/faz35/reconcile-test-permission-writer-identity.sh"
        ).read_text()
        cls.writer_credential_repair = (
            ROOT / "scripts/faz24/repair-d35-permission-writer-credential.sh"
        ).read_text()
        cls.notification_identity = (
            ROOT / "scripts/faz35/provision-test-notification-service-identity.sh"
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
        cls.topology_adr = (
            ROOT / "docs/adr/0046-faz35-etik-speak-product-cell-topology.md"
        ).read_text()
        cls.api_ui_contract = (
            ROOT / "docs/contracts/faz35-etik-speak-api-mfe-v1.md"
        ).read_text()
        cls.semantic_gate_workflow = (
            ROOT / ".github/workflows/gate-drift-pr-time.yml"
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
        cls.notification_external_secret = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/externalsecret-notification.yaml"
        ).read_text()
        cls.auth_ethics_external_secret = (
            ROOT
            / "kustomize/overlays/test/auth-service-ethics-externalsecret.yaml"
        ).read_text()
        cls.activation_kustomization = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/kustomization.yaml"
        ).read_text()
        cls.secret_store = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/secretstore.yaml"
        ).read_text()
        cls.deactivation = (
            ROOT
            / "kustomize/overlays/test/deactivation/etik-speak/kustomization.yaml"
        ).read_text()
        cls.service_config = (
            ROOT / "kustomize/base/apps/etik-speak/ethics-service-config.yaml"
        ).read_text()
        cls.evidence_worker_config = (
            ROOT / "kustomize/base/apps/etik-speak/evidence-worker-config.yaml"
        ).read_text()
        cls.ethics_deployment = (
            ROOT / "kustomize/base/apps/etik-speak/ethics-service-deployment.yaml"
        ).read_text()
        cls.eso_policy = (
            ROOT / "bootstrap/vault-policies/test/etik-speak-eso.hcl"
        ).read_text()
        cls.model_ledger_path = (
            ROOT
            / "runtime-artifacts/openfga-model/3a426b464bced864e0da8431b56bcb85a5584eabb8d09d68f8b2d7d384848e30.json"
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
        cls.manager_ui_ingress = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/ingress-manager-ui.yaml"
        ).read_text()
        cls.netpol = (
            ROOT / "kustomize/overlays/test/activation/etik-speak/netpol.yaml"
        ).read_text()
        cls.product_quota = (
            ROOT
            / "kustomize/overlays/test/activation/etik-speak/resource-quota.yaml"
        ).read_text()
        cls.host_edge = (
            ROOT / "host-compose/web-nginx/default.conf"
        ).read_text()
        cls.no_correlation_verifier = (
            ROOT / "scripts/faz35/verify-test-public-no-correlation.sh"
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

    def test_ethics_service_keeps_native_memory_headroom(self):
        self.assertIn(
            'value: "-Xmx384m -XX:+UseG1GC '
            '-XX:MaxGCPauseMillis=100 -XX:ActiveProcessorCount=1"',
            self.ethics_deployment,
        )
        self.assertIn(
            "requests: {cpu: 150m, memory: 384Mi}",
            self.ethics_deployment,
        )
        self.assertIn(
            "limits: {cpu: 750m, memory: 768Mi}",
            self.ethics_deployment,
        )
        self.assertNotIn("-Xmx256m", self.activation_kustomization)
        self.assertNotIn(
            "path: /spec/template/spec/containers/0/resources/limits/memory",
            self.activation_kustomization,
        )

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
        self.assertIn("'.userId=[$local] | .subscriberId=[$local]'", self.writer_identity)
        self.assertNotIn("'.attributes.userId=[$local]", self.writer_identity)
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

    def test_permission_writer_expected_attributes_remain_a_flat_keycloak_map(self):
        attributes = {
            "org_id": ["default"],
            "subscriberId": ["1204"],
            "userId": ["1204"],
        }
        result = subprocess.run(
            [
                "jq",
                "--arg",
                "local",
                "12",
                ".userId=[$local] | .subscriberId=[$local]",
            ],
            input=json.dumps(attributes),
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "org_id": ["default"],
                "subscriberId": ["12"],
                "userId": ["12"],
            },
        )
        self.assertNotIn("attributes", json.loads(result.stdout))

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
        # A2c: ROPC runs through the dedicated confidential client now, and the secret
        # arrives as a caller-supplied file so this script never reads the Vault root
        # token -- see the assertNotIn("root_token") boundary above.
        self.assertIn('"client_secret@$SMOKE_CLIENT_SECRET_FILE"', self.openfga)
        self.assertNotIn(
            "client_id=frontend", self.openfga.split("set -euo pipefail", 1)[1]
        )
        for exact_claim in (
            '.azp == "smoke-client"',
            '(.aud | sort)',
            '(.scope | split(" ") | sort)',
            '(.roles | sort)',
            '(.resource_roles | keys | sort) == []',
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
        self.assertIn("faz35_select_equivalent_openfga_models", self.openfga)
        self.assertIn("faz35_normalize_openfga_model", self.preflight)
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
        self.assertIn("expected_model_normalized", self.preflight)
        self.assertIn(
            'expected_model_sha=$(jq -j -cS . "$EXPECTED_MODEL_JSON" | sha256_stream)',
            self.preflight,
        )
        self.assertIn(
            '[ "$expected_model_sha" = "$EXPECTED_MODEL_JSON_SHA256" ]',
            self.preflight,
        )
        self.assertIn(
            '[ "$ledger_content_sha" = "$expected_model_sha" ]',
            self.preflight,
        )
        self.assertIn("faz35_assert_openfga_model_response_id", self.preflight)

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

        # OpenFGA's protobuf JSON readback adds empty/default fields that were
        # not present in the reviewed write payload. Those exact defaults are
        # transport representation, not a different authorization model.
        server_readback = json.loads(json.dumps(compiled_model))
        server_readback["conditions"] = {}
        server_readback["type_definitions"][0]["metadata"] = None
        server_readback["type_definitions"][0]["relations"] = {}
        server_readback["type_definitions"][1]["metadata"]["module"] = ""
        server_readback["type_definitions"][1]["metadata"]["source_info"] = None
        member_metadata = server_readback["type_definitions"][1]["metadata"]["relations"]["member"]
        member_metadata["module"] = ""
        member_metadata["source_info"] = None
        member_metadata["directly_related_user_types"][0]["condition"] = ""
        normalized_desired = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.openfga_normalization_lib_path}"; '
                "faz35_normalize_openfga_model",
            ],
            input=json.dumps(compiled_model),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        normalized_readback = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{self.openfga_normalization_lib_path}"; '
                "faz35_normalize_openfga_model",
            ],
            input=json.dumps(server_readback),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(normalized_readback, normalized_desired)
        self.assertIn("del(.condition | select(. == \"\"))", self.openfga_normalization_lib)
        self.assertIn("del(.object | select(. == \"\"))", self.openfga_normalization_lib)

        materially_different = json.loads(json.dumps(server_readback))
        materially_different["type_definitions"][1]["relations"]["member"] = {
            "computedUserset": {"relation": "member", "object": ""}
        }

        def select_matches(models):
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; '
                    'desired=$(printf "%s" "$2" | faz35_normalize_openfga_model); '
                    'printf "%s" "$3" | '
                    'faz35_select_equivalent_openfga_models "$desired"',
                    "bash",
                    str(self.openfga_normalization_lib_path),
                    json.dumps(compiled_model),
                    json.dumps(models),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        equivalent_one = {"id": "01KW0EJTM60YGZTEKNGS7PDPNP", **server_readback}
        different_one = {"id": "01KW0EJTM60YGZTEKNGS7PDPNQ", **materially_different}
        self.assertEqual(
            [model["id"] for model in select_matches([equivalent_one, different_one])],
            [equivalent_one["id"]],
        )
        equivalent_two = {"id": "01KW0EJTM60YGZTEKNGS7PDPNR", **server_readback}
        self.assertEqual(
            len(select_matches([equivalent_one, equivalent_two])),
            2,
        )

        valid_response = {"authorization_model": equivalent_one}
        valid_id = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; printf "%s" "$3" | '
                'faz35_assert_openfga_model_response_id "$2"',
                "bash",
                str(self.openfga_normalization_lib_path),
                equivalent_one["id"],
                json.dumps(valid_response),
            ],
            check=False,
        )
        wrong_id = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; printf "%s" "$3" | '
                'faz35_assert_openfga_model_response_id "$2"',
                "bash",
                str(self.openfga_normalization_lib_path),
                different_one["id"],
                json.dumps(valid_response),
            ],
            check=False,
        )
        missing_id = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; printf "%s" "$3" | '
                'faz35_assert_openfga_model_response_id "$2"',
                "bash",
                str(self.openfga_normalization_lib_path),
                equivalent_one["id"],
                json.dumps({"authorization_model": compiled_model}),
            ],
            check=False,
        )
        self.assertEqual(valid_id.returncode, 0)
        self.assertNotEqual(wrong_id.returncode, 0)
        self.assertNotEqual(missing_id.returncode, 0)

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
        self.assertNotIn("PENDING_FAZ35_OPENFGA_", self.service_config)
        store_match = re.search(
            r'^  ERP_OPENFGA_STORE_ID: "([0-9A-HJKMNP-TV-Z]{26})"$',
            self.service_config,
            re.MULTILINE,
        )
        model_match = re.search(
            r'^  ERP_OPENFGA_MODEL_ID: "([0-9A-HJKMNP-TV-Z]{26})"$',
            self.service_config,
            re.MULTILINE,
        )
        self.assertIsNotNone(store_match)
        self.assertIsNotNone(model_match)
        ledger = json.loads(self.model_ledger)
        model_id = model_match.group(1)
        self.assertEqual(
            model_id,
            ledger["promotion"]["test"]["model_id_env"],
        )
        self.assertTrue(
            ledger["source"]["canonical_source_ref"].endswith(
                f"/authorization-models/{model_id}"
            )
        )
        self.assertEqual(self.external_secret.count("kind: ExternalSecret"), 3)
        self.assertEqual(self.external_secret.count("kind: SecretStore"), 3)
        self.assertEqual(self.external_secret.count("name: etik-speak-vault"), 3)
        self.assertNotIn("ClusterSecretStore", self.external_secret)
        # ES-104G separation of duties. The worker's Secret must resolve the
        # WORKER Vault properties: the two ExternalSecrets deliberately expose
        # the same variable names, so a copy-paste that pointed the worker at
        # the request-facing identity would collapse the whole split silently —
        # everything would still work, and one credential would be able to
        # accept an upload, seal it and read the derivative back.
        self.assertEqual(
            self.external_secret.count("property: ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY"),
            1,
        )
        self.assertEqual(
            self.external_secret.count("property: ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY"),
            1,
        )
        worker_document = next(
            document
            for document in self.external_secret.split("\n---\n")
            if "name: ethics-evidence-worker-secrets" in document
        )
        self.assertIn("property: ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY", worker_document)
        self.assertNotIn(
            "property: ETHICS_EVIDENCE_S3_ACCESS_KEY", worker_document
        )
        # The request-facing Secret must not carry the worker identity either.
        service_document = next(
            document
            for document in self.external_secret.split("\n---\n")
            if "name: ethics-service-secrets" in document
        )
        self.assertNotIn("WORKER_S3", service_document)
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
        self.assertNotIn("PENDING_FAZ35_VAULT_ROLE_ID", self.secret_store)
        role_id_match = re.search(
            r"^          roleId: "
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
            self.secret_store,
            re.MULTILINE,
        )
        self.assertIsNotNone(role_id_match)
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

    def test_activation_preflight_reproves_live_openfga_authorization(self):
        verifier = (
            ROOT / "scripts/faz35/verify-test-openfga-authz.sh"
        ).read_text()
        self.assertIn('verify-test-openfga-authz.sh', self.preflight)
        self.assertIn('remote "bash -s --', self.preflight)
        self.assertIn("resolve_persona_subject ethics-manager-test", verifier)
        self.assertIn("resolve_persona_subject ethics-manager-wrong-org-test", verifier)
        self.assertIn("resolve_persona_subject ethics-manager-denied-test", verifier)
        self.assertIn("case_viewer case_triager case_handler", verifier)
        self.assertIn("wrong-org-canonical", verifier)
        self.assertIn("denied-persona", verifier)
        self.assertIn("assert_exact_tuple", verifier)
        self.assertIn("recusal-sentinel", verifier)

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
        self.assertIn('SSH_TARGET" = "aiserver', self.preflight)
        self.assertNotIn('SSH_TARGET="${SSH_TARGET:-staging-sw', self.preflight)
        self.assertNotIn('[ "$SSH_TARGET" = "staging-sw', self.preflight)
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
            # The host edge sits in front of ingress-nginx, so its body limit is
            # the operative one. Without a directive nginx applies a 1m default
            # and rejects a compliant 25 MiB attachment before reading the body,
            # while the ingress annotation looks correct.
            "client_max_body_size 26m;",
            "check_object_headroom services 4 2",
            "check_object_headroom configmaps 4 2",
            "check_object_headroom secrets 3 2",
            "check_object_headroom pods 9 2",
            "activation must render exactly four ExternalSecrets",
            "public reporter ingresses must not retain the removed Basic Auth gate",
            "public reporter ingress displaced edge",
            "platform-web-nginx nginx -T",
            "canonical host edge misses Etik Speak rate-limit policy",
            "live host edge misses Etik Speak rate-limit policy",
            "Etik Speak host edge access logs are not disabled",
            "one-year HSTS header",
            "foundation provisioning refuses an included Etik Speak activation root",
            "Faz 35 activation must not reference the shared test frontend",
            "foundation provisioning refuses existing or partial Etik Speak activation resources",
            "secretstore/etik-speak-vault",
            "secret/ethics-service-secrets",
            "secret/etik-speak-public-gate",
            "priorityclass/etik-speak-test",
            "faz35_assert_root_activation_binding",
            "faz35_assert_rendered_deployment_image",
            "image set content does not match its content-addressed filename",
            "image set schema/source-head binding is invalid",
            ".github/workflows/release-etik-speak-manager-image.yml",
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

    def test_synthetic_persona_secrets_are_pinned_to_aiserver_secret_root(self):
        secret_root = "/srv/platform/secrets/faz35-test"
        verifier = (
            ROOT / "scripts/faz35/verify-test-openfga-authz.sh"
        ).read_text()
        for script in (self.keycloak, self.openfga, self.entitlement, verifier):
            self.assertIn(secret_root, script)
            self.assertNotIn("/home/halil/bootstrap-drill/ethics-manager", script)

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
        self.assertEqual(self.image_set["schema_version"], "faz35-test-image-set-v2")
        self.assertEqual(
            self.image_set["images"]["ethics_service"]["source_head"],
            self.image_set["source_heads"]["backend"],
        )
        self.assertEqual(
            self.image_set["images"]["public_web"]["source_head"],
            self.image_set["source_heads"]["web_public"],
        )
        self.assertEqual(
            self.image_set["images"]["manager_web"]["source_head"],
            self.image_set["source_heads"]["web_manager"],
        )

        rendered = subprocess.run(
            ["kustomize", "build", str(ROOT / "kustomize/overlays/test/activation/etik-speak")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("ETHICS_AUDIT_DELIVERY_ENABLED", self.service_config)
        self.assertEqual(
            rendered.count('ETHICS_AUDIT_DELIVERY_ENABLED: "true"'),
            1,
        )
        self.assertEqual(
            rendered.count('ETHICS_NOTIFICATION_DELIVERY_ENABLED: "true"'),
            1,
        )
        self.assertIn(
            'ETHICS_AUDIT_DELIVERY_ENABLED: "true"',
            self.preflight,
        )
        self.assertIn(
            'ETHICS_NOTIFICATION_DELIVERY_ENABLED: "true"',
            self.preflight,
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "activation.yaml"
            manifest_path.write_text(rendered)
            for deployment, image_key in (
                ("ethics-service", "ethics_service"),
                ("etik-speak-public", "public_web"),
                ("etik-speak-manager", "manager_web"),
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

    def test_notification_delivery_is_isolated_least_privilege_and_fail_closed(self):
        self.assertIn(
            "auth-service-ethics-externalsecret.yaml",
            self.test_root,
        )
        self.assertIn(
            "externalsecret-notification.yaml",
            self.activation_kustomization,
        )
        self.assertIn(
            "property: service_client_ethics_service_secret",
            self.auth_ethics_external_secret,
        )
        self.assertIn(
            "secretKey: SERVICE_CLIENT_ETHICS_SERVICE_SECRET",
            self.auth_ethics_external_secret,
        )
        self.assertIn(
            "property: ETHICS_NOTIFICATION_CLIENT_SECRET",
            self.notification_external_secret,
        )
        self.assertIn(
            "secretKey: ETHICS_NOTIFICATION_CLIENT_SECRET",
            self.notification_external_secret,
        )
        self.assertIn(
            "name: ethics-service-notification-secret",
            self.notification_external_secret,
        )
        self.assertIn(
            "name: ethics-service-notification-secret",
            self.activation_kustomization,
        )
        self.assertIn(
            'path: /data/ETHICS_NOTIFICATION_DELIVERY_ENABLED',
            self.activation_kustomization,
        )
        self.assertIn(
            'value: "f8a3b6f6-a984-49d1-b666-c535b11c742f"',
            self.activation_kustomization,
        )
        for destination in (
            "allow-ethics-service-to-auth-service",
            "allow-ethics-service-to-notification-orchestrator",
        ):
            self.assertIn(destination, self.netpol)
        self.assertNotIn("client-secret:", self.activation_kustomization)
        self.assertNotIn("client-secret:", self.auth_ethics_external_secret)
        self.assertNotIn("client-secret:", self.notification_external_secret)

    def test_notification_identity_provisioner_keeps_secret_off_argv_and_fails_closed(self):
        for required in (
            'AUTH_PATH="kv/platform/auth-service"',
            'ETHICS_PATH="kv/platform/etik-speak"',
            'CONFIRM_TEST_NOTIFICATION_IDENTITY:-',
            "seed-faz35-es208",
            "automatic rotation refused",
            "read-after-write mismatch",
            "IFS= read -r VAULT_TOKEN",
            'vault kv patch "$1" "$2"=-',
            "openssl rand -hex 32",
            "10.9.10.15",
        ):
            self.assertIn(required, self.notification_identity)
        self.assertNotRegex(
            self.notification_identity,
            r"vault kv patch[^\n]*\$(?:candidate|auth_value|ethics_value)",
        )
        self.assertNotRegex(
            self.notification_identity,
            r"-e\s+VAULT_TOKEN(?:=|\s|\\)",
        )

    def test_preflight_pins_new_aiserver_identity_and_bounds_optional_jump(self):
        for required in (
            'SSH_TARGET="${SSH_TARGET:-aiserver}"',
            'SSH_PROXY_JUMP="${SSH_PROXY_JUMP:-}"',
            '""|staging-sw-legacy)',
            '[ "$target_hostname" != "aiserver" ]',
            "grep -qw '10.9.10.15'",
            "SSH path does not terminate on authoritative aiserver 10.9.10.15",
            'resolve_ip=""',
            '--resolve "$host:443:$resolve_ip"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.preflight)

        self.assertNotIn("resolve_args", self.preflight)
        self.assertIn(
            "SSH_PROXY_JUMP=staging-sw-legacy",
            self.activation_runbook,
        )

    def test_semantic_gate_triggers_for_every_authoritative_external_input(self):
        for required_path in (
            "scripts/faz35/**",
            "scripts/faz24/repair-d35-permission-writer-credential.sh",
            "bootstrap/vault-policies/test/etik-speak-eso.hcl",
            "bootstrap/openfga/faz35-etik-speak/**",
            "runtime-artifacts/faz35-etik-speak/**",
            "runtime-artifacts/openfga-model/**",
            "docs/faz-35-evidence/**",
            "tests/deploy/test_faz35_etikspeak_provisioning_contract.py",
        ):
            with self.subTest(required_path=required_path):
                self.assertIn(f"- '{required_path}'", self.semantic_gate_workflow)

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

    def test_public_test_hosts_are_open_rate_limited_and_redirect_to_https(self):
        for ingress in (self.public_api_ingress, self.public_ui_ingress):
            self.assertIn('nginx.ingress.kubernetes.io/force-ssl-redirect: "true"', ingress)
            self.assertIn('nginx.ingress.kubernetes.io/enable-access-log: "false"', ingress)
            self.assertIn('nginx.ingress.kubernetes.io/enable-opentelemetry: "false"', ingress)
            self.assertNotIn("nginx.ingress.kubernetes.io/auth-type:", ingress)
            self.assertNotIn("nginx.ingress.kubernetes.io/auth-secret:", ingress)
            self.assertNotIn("nginx.ingress.kubernetes.io/auth-realm:", ingress)
            for forbidden in (
                "nginx.ingress.kubernetes.io/proxy-set-headers:",
                "nginx.ingress.kubernetes.io/proxy-hide-headers:",
                "nginx.ingress.kubernetes.io/limit-rps:",
                "nginx.ingress.kubernetes.io/limit-rpm:",
                "nginx.ingress.kubernetes.io/limit-connections:",
                "nginx.ingress.kubernetes.io/limit-burst-multiplier:",
            ):
                self.assertNotIn(forbidden, ingress)

        for expected in (
            "server_name etik.acik.com speakup.acik.com;",
            "map $http_cookie $etik_speak_public_cookie",
            "__Host-etik_mailbox=[^;]+",
            "limit_req_zone $binary_remote_addr zone=etik_speak_api_rps:10m rate=3r/s;",
            "limit_req_zone $binary_remote_addr zone=etik_speak_api_rpm:10m rate=60r/m;",
            "limit_req_zone $binary_remote_addr zone=etik_speak_ui_rps:10m rate=10r/s;",
            "limit_req_zone $binary_remote_addr zone=etik_speak_ui_rpm:10m rate=300r/m;",
            "limit_conn_zone $binary_remote_addr zone=etik_speak_public_conn:10m;",
            "location ^~ /api/v1/public/ethics",
            "limit_req zone=etik_speak_api_rps burst=6 nodelay;",
            "limit_req zone=etik_speak_api_rpm burst=120 nodelay;",
            "limit_conn etik_speak_public_conn 10;",
            "limit_req zone=etik_speak_ui_rps burst=30 nodelay;",
            "limit_req zone=etik_speak_ui_rpm burst=900 nodelay;",
            "limit_conn etik_speak_public_conn 20;",
            "proxy_set_header Cookie $etik_speak_public_cookie;",
            "proxy_set_header X-Etik-Speak-Transport https;",
            "map $upstream_http_set_cookie $etik_speak_mailbox_set_cookie_name",
            "map $etik_speak_mailbox_set_cookie_httponly $etik_speak_public_set_cookie",
            "proxy_hide_header Set-Cookie;",
            "add_header Set-Cookie $etik_speak_public_set_cookie always;",
            '"~*;\\s*Domain=" "";',
            '"~*;\\s*Path=/(?:;|$)" $etik_speak_mailbox_set_cookie_domain;',
            '"~*;\\s*Secure(?:;|$)" $etik_speak_mailbox_set_cookie_path;',
            '"~*;\\s*HttpOnly(?:;|$)" $etik_speak_mailbox_set_cookie_secure;',
            '"~*;\\s*SameSite=Strict(?:;|$)" $etik_speak_mailbox_set_cookie_httponly;',
        ):
            self.assertIn(expected, self.host_edge)
        self.assertGreaterEqual(self.host_edge.count("access_log off;"), 2)
        self.assertEqual(
            self.host_edge.count(
                "proxy_set_header Cookie $etik_speak_public_cookie;"
            ),
            2,
        )
        self.assertEqual(self.host_edge.count("proxy_hide_header Set-Cookie;"), 2)
        self.assertEqual(
            self.host_edge.count(
                "add_header Set-Cookie $etik_speak_public_set_cookie always;"
            ),
            2,
        )
        for security_header in (
            "Strict-Transport-Security",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Referrer-Policy",
            "Permissions-Policy",
        ):
            self.assertGreaterEqual(
                self.host_edge.count(f"add_header {security_header} "),
                3,
            )
        for header in (
            "Authorization",
            "Forwarded",
            "Referer",
            "User-Agent",
            "X-Forwarded-For",
            "X-Original-Forwarded-For",
            "X-Real-IP",
            "X-Request-ID",
        ):
            self.assertEqual(
                self.host_edge.count(f'proxy_set_header {header} "";'),
                2,
            )
        self.assertNotIn("api-gateway", self.netpol)

    def test_public_no_correlation_runtime_verifier_is_fail_closed(self):
        for expected in (
            'readonly KUBE_CONTEXT="k3d-test"',
            'readonly KUBE_NS="platform-test"',
            'readonly SSH_TARGET="${SSH_TARGET:-staging-sw}"',
            "enable-access-log",
            "enable-opentelemetry",
            "platform-web-nginx",
            "etik_speak_public_cookie",
            "X-Original-Forwarded-For",
            "LIVE_HOST_EDGE_ACCESS_LOG_DISABLED=true",
            "LIVE_HOST_EDGE_VOLATILE_RATE_LIMIT=true",
            "LIVE_SUITE_COOKIE_FILTER=true",
            "PUBLIC_DNS_A_RECORD_VERIFIED=true",
            'dig +short @1.1.1.1 A "$host"',
            '--resolve "${host}:443:${public_ip}"',
            "server_name[[:space:]]+etik\\.acik\\.com",
            "synthetic sentinel leaked",
            "Domain=.acik.com",
            "NO_CORRELATION_ACCEPTED=true",
        ):
            self.assertIn(expected, self.no_correlation_verifier)
        for forbidden in (
            "kubectl apply",
            "kubectl patch",
            "kubectl edit",
            "kubectl set image",
            "platform-prod",
            "ai.acik.com",
        ):
            self.assertNotIn(forbidden, self.no_correlation_verifier)
        self.assertNotIn(
            "sed -n '/# Faz 35 ES-106/,$p'",
            self.no_correlation_verifier,
        )
        self.assertIn(
            "SSH_TARGET=staging-sw "
            "./scripts/faz35/verify-test-public-no-correlation.sh",
            self.activation_runbook,
        )
        self.assertIn("NO_CORRELATION_ACCEPTED=true", self.activation_runbook)

    def test_recorded_scanner_identity_is_the_scanner_that_actually_runs(self):
        """The provenance digest and the deployed ClamAV image must be the same value.

        `ETHICS_EVIDENCE_PARSER_DIGEST` is what every scanned attachment records as the
        thing that scanned it. The overlay separately pins the ClamAV image. Today the two
        strings match, but only because someone typed them that way — nothing kept them
        matching.

        That gap fails in the direction you least want. Updating the scanner is the
        *correct* operational move; when someone bumps the image digest for a security
        release, this config keeps the old value and every attachment scanned afterwards
        records a scanner version that never touched it. The custody chain would read as
        intact and be wrong, which is worse than an obvious break.
        """
        recorded = re.search(
            r'ETHICS_EVIDENCE_PARSER_DIGEST:\s*"(sha256:[0-9a-f]{64})"', self.evidence_worker_config
        )
        self.assertIsNotNone(recorded, "worker config carries no parser digest")

        deployed = re.search(
            r"docker\.io/clamav/clamav\s*\n\s*digest:\s*(sha256:[0-9a-f]{64})",
            self.activation_kustomization,
        )
        self.assertIsNotNone(deployed, "overlay pins no clamav image digest")

        self.assertEqual(
            recorded.group(1),
            deployed.group(1),
            "kanit kokenine yazilan tarayici digest'i, dagitilan clamav imajiyla ayni degil; "
            "tarayici guncellenirken bu deger de tasinmali",
        )

    def test_manager_ui_is_isolated_at_the_exact_test_path(self):
        self.assertIn("name: etik-speak-manager-ui", self.manager_ui_ingress)
        self.assertIn("host: testai.acik.com", self.manager_ui_ingress)
        self.assertIn("path: /ethic", self.manager_ui_ingress)
        self.assertIn("name: etik-speak-manager", self.manager_ui_ingress)
        self.assertIn("name: etik-speak-manager", self.netpol)
        self.assertIn(
            "Faz 35 activation must not reference the shared test frontend",
            self.preflight,
        )

    def test_manager_route_matches_canonical_isolated_auth_contract(self):
        for expected in (
            "ES-1 isolated etik-speak-manager",
            "check-sso",
            "PKCE S256",
            "credentials: omit",
            "401/403",
            "2fae733d31f574908859307f8af0dbc375e053eb",
            "sha256:931f3432810fc2c55ec89ec0617d084a46536daf77559c53c8d0203f885a1b28",
            "prompt=login",
        ):
            self.assertIn(expected, self.topology_adr)

    def test_auth_contract_anchor_points_at_the_guard_that_can_actually_fail(self):
        """The ADR must say where the living check is, and must not claim to be it.

        This assertion exists because of the failure it replaces (#3078). The ADR used to
        state that `apps/etik-speak-manager` had not changed since a reviewed commit, and
        the test above "verified" it by checking that the ADR text *contained* that commit
        hash. When the auth path did change — scope handling and `prompt: 'login'`, twelve
        files — the sentence became false and every gate stayed green: evidence about a
        fact had been mistaken for the fact.

        This repository cannot fix that by asserting harder. It has no platform-web
        checkout, so any continuing claim it makes about that directory is unfalsifiable
        here by construction. What it *can* enforce is that the ADR keeps pointing at the
        guard that lives next to the source and can genuinely fail — and that the pointer
        cannot be quietly deleted while the historical hashes above stay put.
        """
        self.assertIn(
            "apps/etik-speak-manager/src/auth-contract-anchor.test.ts",
            self.topology_adr,
            "ADR-0046 auth sözleşmesinin canlı korumasına işaret etmiyor",
        )
        # A dated record, not a standing equality claim. The exact wording is the point:
        # the earlier sentence promised present-tense sameness and could not keep it.
        self.assertIn("Auth sözleşmesi inceleme kaydı", self.topology_adr)
        self.assertNotIn(
            "arasında `apps/etik-speak-manager` farkı yoktur",
            self.topology_adr,
            "süregelen eşitlik iddiası geri gelmiş — bu cümle bir kez yanlışa düştü",
        )
        for expected in (
            "ES-1 TEST isolated manager",
            "aud=ethics-manager",
            "ethics:case:manage",
            "realm role `ethics-manager`",
            "credentials: omit",
            "Authorization`/`Cookie",
            "wrong-org/OpenFGA-deny",
        ):
            self.assertIn(expected, self.api_ui_contract)
        self.assertIn("intentionally an isolated SPA", self.activation_runbook)
        self.assertIn("Neither source tests nor attestation replace Gate 4", self.activation_runbook)

    def test_worker_memory_budget_covers_a_contract_maximum_attachment(self):
        """The pipeline holds a whole attachment in memory and then its
        sanitized derivative alongside it. At a limit below that the worker is
        OOM-killed mid-scan, the processing lease expires, another attempt
        starts, and the attachment livelocks — while every pod stays Ready and
        every dashboard stays green. Bind the memory budget to the declared
        maximum so raising one without the other fails here instead of in
        production."""
        worker_config = (
            ROOT / "kustomize/base/apps/etik-speak/evidence-worker-config.yaml"
        ).read_text()
        service_config = (
            ROOT / "kustomize/base/apps/etik-speak/ethics-service-config.yaml"
        ).read_text()
        max_bytes_match = re.search(
            r'(?m)^  ETHICS_EVIDENCE_MAX_BYTES: "(\d+)"$', service_config
        )
        self.assertIsNotNone(max_bytes_match)
        max_bytes = int(max_bytes_match.group(1))

        deployment = (
            ROOT / "kustomize/base/apps/etik-speak/evidence-worker-deployment.yaml"
        ).read_text()
        limit_match = re.search(r"limits: \{cpu: [^,]+, memory: (\d+)Mi\}", deployment)
        self.assertIsNotNone(limit_match)
        limit_bytes = int(limit_match.group(1)) * 1024 * 1024

        # Two copies of the payload plus a Spring baseline that measured ~300Mi.
        required = 2 * max_bytes + 300 * 1024 * 1024
        self.assertGreaterEqual(
            limit_bytes,
            required,
            f"worker memory limit {limit_bytes} is below the "
            f"{required} needed for a {max_bytes}-byte attachment",
        )
        # A heap budget must be stated: the JVM otherwise claims 25% of the
        # limit, so raising the limit alone changes nothing.
        self.assertIn("MaxRAMPercentage", deployment)
        self.assertIn("JAVA_TOOL_OPTIONS", deployment)

    def test_pinned_scanner_rules_version_is_a_real_clamd_reply(self):
        """The processor compares this value byte-for-byte with clamd's own
        VERSION reply and refuses to scan on any difference. A human-friendly
        label here does not fail loudly at deploy time — every attachment simply
        stops at SCAN_PENDING with EVIDENCE_SCANNER_RULES_MISMATCH, which reads
        like a scanner outage rather than a config error."""
        worker_config = (
            ROOT / "kustomize/base/apps/etik-speak/evidence-worker-config.yaml"
        ).read_text()
        match = re.search(
            r'(?m)^  ETHICS_EVIDENCE_RULES_VERSION: "([^"]+)"$', worker_config
        )
        self.assertIsNotNone(match)
        self.assertRegex(
            match.group(1),
            r"^ClamAV \d+\.\d+\.\d+/\d+/.+$",
            "pinned rules version must be a verbatim clamd VERSION reply",
        )

    def test_product_quota_has_rollout_and_repair_reserve(self):
        for expected in (
            'requests.cpu: "800m"',
            "requests.memory: 3584Mi",
            'limits.cpu: "5500m"',
            "limits.memory: 7680Mi",
        ):
            self.assertIn(expected, self.product_quota)

        rendered = subprocess.run(
            [
                "kustomize",
                "build",
                str(ROOT / "kustomize/overlays/test/activation/etik-speak"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        documents = rendered.split("---\n")
        deployment_documents = [
            document
            for document in documents
            if re.search(r"(?m)^kind: Deployment$", document)
        ]
        service_count = sum(
            bool(re.search(r"(?m)^kind: Service$", document))
            for document in documents
        )
        rollout_peak = 0
        for document in deployment_documents:
            replicas = re.search(r"(?m)^  replicas: ([0-9]+)$", document)
            self.assertIsNotNone(replicas)
            # A Recreate rollout never runs an extra pod, so it contributes no
            # surge. Demanding a maxSurge from every Deployment would force the
            # quota to reserve capacity that can never be used — and would
            # block any workload that must not run two instances at once, which
            # is exactly the case for the lease-holding evidence worker.
            strategy = re.search(r"(?m)^    type: (\w+)$", document)
            max_surge = re.search(r"(?m)^      maxSurge: ([0-9]+)$", document)
            if strategy is not None and strategy.group(1) == "Recreate":
                self.assertIsNone(max_surge)
                surge = 0
            else:
                self.assertIsNotNone(max_surge)
                surge = int(max_surge.group(1))
            rollout_peak += int(replicas.group(1)) + surge

        repair_reserve = 2
        # Three request-facing Deployments plus the ES-104G evidence worker, its
        # scanner, and the ES-104J PDF CDR worker; the two workers answer no
        # traffic and therefore have no Service of their own.
        self.assertEqual(len(deployment_documents), 6)
        self.assertEqual(service_count, 4)
        self.assertIn(f'pods: "{rollout_peak + repair_reserve}"', self.product_quota)
        self.assertIn(
            f"check_object_headroom pods {rollout_peak} {repair_reserve}",
            self.preflight,
        )
        self.assertIn(
            f"check_object_headroom services {service_count} {repair_reserve}",
            self.preflight,
        )
        self.assertNotIn("api-gateway-to-ethics-service", self.netpol)

    def test_prune_false_rollback_uses_fail_closed_gitops_tombstone(self):
        self.assertIn("../../activation/etik-speak", self.deactivation)
        self.assertEqual(self.deactivation.count("value: 0"), 1)
        for disabled_host in (
            "etik-speak-disabled.invalid",
            "speakup-disabled.invalid",
            "etik-speak-manager-disabled.invalid",
        ):
            self.assertIn(disabled_host, self.deactivation)

        rendered = subprocess.run(
            [
                "kustomize",
                "build",
                str(ROOT / "kustomize/overlays/test/deactivation/etik-speak"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(rendered.count("replicas: 0"), 3)
        for active_host in (
            "host: etik.acik.com",
            "host: speakup.acik.com",
            "host: testai.acik.com",
        ):
            self.assertNotIn(active_host, rendered)
        for resource_name in (
            "name: ethics-service",
            "name: etik-speak-public",
            "name: etik-speak-manager",
            "name: etik-speak-public-api",
            "name: etik-speak-public-ui",
            "name: etik-speak-staff-api",
            "name: etik-speak-manager-ui",
            "name: ethics-service-secrets",
            "name: etik-speak-vault",
        ):
            self.assertIn(resource_name, rendered)

        for required in (
            "prune: false",
            "deactivation/etik-speak",
            "replicas: 0",
            ".invalid",
            "Never roll back by only deleting the root resource line",
        ):
            self.assertIn(required, self.activation_runbook)

    def test_test_quota_preserves_etikspeak_activation_and_repair_reserve(self):
        quota_patch = re.search(
            r"(?s)- target:\s+kind: ResourceQuota\s+name: platform-quota"
            r"\s+patch: \|-\s+(.*?)(?=\n  - target:|\Z)",
            self.test_root,
        )
        self.assertIsNotNone(quota_patch)
        patch = quota_patch.group(1)
        expected = {
            "/spec/hard/limits.cpu": "17",
            "/spec/hard/services": "40",
            "/spec/hard/secrets": "45",
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
