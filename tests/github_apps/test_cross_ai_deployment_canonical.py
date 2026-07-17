from __future__ import annotations

import unittest

from scripts.github_apps.cross_ai_deployment_policy.canonical import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError


class CanonicalJsonTest(unittest.TestCase):
    def test_canonicalizes_nested_json(self) -> None:
        self.assertEqual(
            canonical_bytes({"z": [True, None, "ı"], "a": {"b": 2, "a": 1}}),
            '{"a":{"a":1,"b":2},"z":[true,null,"ı"]}'.encode(),
        )

    def test_utf16_property_sort_order(self) -> None:
        # U+10000 sorts before U+E000 in UTF-16 code-unit order.
        self.assertEqual(
            canonical_bytes({"\ue000": 1, "\U00010000": 2}),
            '{"𐀀":2,"":1}'.encode(),
        )

    def test_rejects_floats(self) -> None:
        with self.assertRaisesRegex(PolicyError, "JCS_FLOAT_FORBIDDEN"):
            canonical_bytes({"n": 1.25})

    def test_rejects_unsafe_integers(self) -> None:
        with self.assertRaisesRegex(PolicyError, "JCS_UNSAFE_INTEGER"):
            canonical_bytes({"n": 1 << 53})

    def test_rejects_surrogate_codepoints(self) -> None:
        with self.assertRaisesRegex(PolicyError, "JCS_INVALID_STRING"):
            canonical_bytes({"bad": "\ud800"})


if __name__ == "__main__":
    unittest.main()
