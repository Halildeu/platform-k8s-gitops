import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
VAULT_API_PATH = "kv/data/platform/audio-gateway-speechmatics"


class SpeechmaticsSecretPolicyContractTest(unittest.TestCase):
    def test_test_policy_grants_exact_read_only_path(self) -> None:
        policy = (
            ROOT / "bootstrap/vault-policies/test/eso-runtime-extras.hcl"
        ).read_text(encoding="utf-8")

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

    def test_speechmatics_path_is_not_granted_to_common_or_prod_policy(self) -> None:
        for relative_path in (
            "bootstrap/vault-policies/common/eso-runtime.hcl",
            "bootstrap/vault-policies/prod/eso-runtime-extras.hcl",
        ):
            with self.subTest(policy=relative_path):
                policy = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn(VAULT_API_PATH, policy)

    def test_reconciler_applies_test_extras_policy(self) -> None:
        reconciler = (ROOT / "scripts/ops/vault-policy-reconcile.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "test/eso-runtime-extras.hcl|eso-runtime-test-extras",
            reconciler,
        )


if __name__ == "__main__":
    unittest.main()
