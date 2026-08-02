import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
VAULT_API_PATH = "kv/data/platform/audio-gateway-service"
LEGACY_VAULT_API_PATH = "kv/data/platform/audio-gateway-speechmatics"
VAULT_KV_PATH = "kv/platform/audio-gateway-service"


class SpeechmaticsSecretPolicyContractTest(unittest.TestCase):
    def test_common_policy_grants_exact_read_only_path(self) -> None:
        policy = (ROOT / "bootstrap/vault-policies/common/eso-runtime.hcl").read_text(
            encoding="utf-8"
        )

        block = re.search(
            rf'path "{re.escape(VAULT_API_PATH)}"\s*\{{(?P<body>.*?)\}}',
            policy,
            re.DOTALL,
        )
        self.assertIsNotNone(block)
        self.assertRegex(block.group("body"), r'capabilities\s*=\s*\["read"\]')
        self.assertNotRegex(
            block.group("body"),
            r'"(?:create|update|patch|delete|list|sudo)"',
        )

    def test_legacy_dedicated_path_has_no_eso_grant(self) -> None:
        for relative_path in (
            "bootstrap/vault-policies/common/eso-runtime.hcl",
            "bootstrap/vault-policies/test/eso-runtime-extras.hcl",
            "bootstrap/vault-policies/prod/eso-runtime-extras.hcl",
        ):
            with self.subTest(policy=relative_path):
                policy = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn(LEGACY_VAULT_API_PATH, policy)

    def test_external_secret_uses_existing_path_and_dedicated_target(self) -> None:
        external_secret = (
            ROOT / "kustomize/overlays/test/eso/audio-gateway/externalsecret.yaml"
        ).read_text(encoding="utf-8")

        speechmatics_document = external_secret.split(
            "name: audio-gateway-speechmatics", maxsplit=1
        )[1]
        self.assertIn(
            "target:\n    name: audio-gateway-speechmatics",
            speechmatics_document,
        )
        self.assertIn(f"key: {VAULT_KV_PATH}", speechmatics_document)
        self.assertIn("property: speechmatics_api_key", speechmatics_document)
        self.assertNotIn(
            "kv/platform/audio-gateway-speechmatics",
            speechmatics_document,
        )

    def test_seed_script_uses_scoped_seeder_and_additive_patch(self) -> None:
        script = (ROOT / "scripts/faz24/seed-speechmatics-test-secret.sh").read_text(
            encoding="utf-8",
        )
        self.assertIn("audio-gateway-mtls-seeder", script)
        self.assertIn("PATCH", script)
        self.assertIn("application/merge-patch+json", script)
        self.assertIn("speechmatics_api_key", script)
        self.assertIn("read-back hash mismatch", script)
        self.assertIn("http://127.0.0.1:8201", script)
        self.assertNotIn("http://127.0.0.1:8301", script)
        self.assertNotIn("vault kv put", script)
        self.assertNotIn("root token", script.lower())

    def test_test_overlay_enables_explicit_speechmatics_selection(self) -> None:
        overlay = (ROOT / "kustomize/overlays/test/kustomization.yaml").read_text(
            encoding="utf-8"
        )

        selectable_patch = re.search(
            r"path: /data/AUDIO_GATEWAY_DIRECT_STT_SELECTABLE_PROVIDERS\s+"
            r'value: "(?P<providers>[^"]+)"',
            overlay,
        )
        self.assertIsNotNone(selectable_patch)
        self.assertEqual(
            selectable_patch.group("providers"),
            "internal,speechmatics",
        )
        self.assertIn(
            "2026-08-02-3349-v20-speechmatics-immediate-terminal-flush",
            overlay,
        )
        self.assertNotIn("2026-08-01-3240-v7-credential-failsafe", overlay)


if __name__ == "__main__":
    unittest.main()
