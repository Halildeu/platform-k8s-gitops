"""Self-validation for the Faz 22.8A.1 backup dry-run manifest contract v1.

Faz 22.8A (board #1390 charter, agent #117; Codex 019ea961 + 019ec28a). The
`docs/faz-22-8a-backup-manifest-contract-v1.md` contract is metadata-only
(DC-EA-1): the producer reads NO file content and computes NO content/SHA256
hash. This test makes the contract repo machine-enforce its own KVKK-critical
invariants BEFORE any producer (platform-agent #117) or backend consumer is
built, so the decision cannot silently regress:

  * the 3 inline golden examples validate (positive corpus),
  * `additionalProperties:false` on an entry rejects a sneaked content-hash
    field — the structural form of invariant #1 (no SHA256/content read),
  * `extension_type` has NO `archive` value (the 2026-06-13 amendment:
    archive-container is DC-EA-RED and never reaches an entry),
  * `manifest_version`/`dc_ea_tier` are const-pinned,
  * the DC-EA-RED `denied_classes` enum is the full authoritative set,
  * `root_ref` is an opaque `managed_root:<uuid>` ref, never a raw path
    (data minimization, KVKK m.4),
  * the removed `is_container` per-entry field cannot creep back.

Run: python3 -m unittest tests.contracts.test_backup_manifest_payload_contract_v1 -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO_ROOT / "schema" / "faz-22-8a-backup-manifest-v1.schema.json"
FIXTURES = REPO_ROOT / "tests" / "contracts" / "fixtures" / "backup-manifest"

DENIED_CLASSES = {
    "credential_store", "browser_profile", "mailbox_cache",
    "private_key_material", "cloud_cli_token_store", "password_manager_vault",
    "dpapi_store", "registry_hive", "app_token_store", "archive_container",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestBackupManifestContractV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA)
        # generated_at is hard-gated by a dependency-free ISO-8601 regex pattern in
        # the schema (format:date-time alone is annotation-only without the optional
        # jsonschema[format] extra, which CI does not install) — Codex 019f00f6 absorb.
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_is_valid_draft202012(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_inline_golden_examples_validate(self) -> None:
        examples = self.schema.get("examples", [])
        self.assertEqual(len(examples), 3, "expected 3 inline golden examples (with-entries / clean / all-denied)")
        for i, example in enumerate(examples):
            with self.subTest(example=i):
                errors = list(self.validator.iter_errors(example))
                self.assertEqual(errors, [], f"golden example[{i}] must validate: " + (errors[0].message if errors else ""))

    def test_content_hash_field_is_rejected(self) -> None:
        # Invariant #1 in structural form: an entry may carry NO content-hash
        # field. The negative fixture is otherwise fully valid so the ONLY
        # violation is the sneaked sha256 field on entries[0].
        instance = load_json(FIXTURES / "invalid-content-hash-v1.json")
        self.assertIn("sha256", instance["entries"][0])
        errors = list(self.validator.iter_errors(instance))
        self.assertTrue(errors, "an entry with a sha256/content-hash field MUST be rejected (invariant #1).")
        paths = {tuple(e.absolute_path) for e in errors}
        self.assertEqual(
            paths, {("entries", 0)},
            f"the ONLY violation must be entries[0] (the content-hash field via additionalProperties:false); paths={paths}",
        )

    def test_archive_extension_type_is_rejected(self) -> None:
        # 2026-06-13 amendment: extension_type has NO `archive` value.
        instance = load_json(FIXTURES / "invalid-archive-extension-v1.json")
        self.assertEqual(instance["entries"][0]["extension_type"], "archive")
        errors = list(self.validator.iter_errors(instance))
        self.assertTrue(errors, "extension_type:archive MUST be rejected (archive-container is DC-EA-RED, never an entry).")
        paths = {tuple(e.absolute_path) for e in errors}
        self.assertEqual(
            paths, {("entries", 0, "extension_type")},
            f"the ONLY violation must be entries[0].extension_type; paths={paths}",
        )

    def test_version_and_tier_pinned(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(props["manifest_version"].get("const"), "1")
        self.assertEqual(props["dc_ea_tier"].get("const"), "DC-EA-1")

    def test_no_archive_in_extension_type_enum(self) -> None:
        ext_enum = self.schema["properties"]["entries"]["items"]["properties"]["extension_type"]["enum"]
        self.assertNotIn("archive", ext_enum, "archive-container is DC-EA-RED; extension_type must NOT include archive (amendment).")
        self.assertEqual(set(ext_enum), {"doc", "sheet", "pdf", "image", "other"})

    def test_denied_classes_enum_is_authoritative_set(self) -> None:
        enum = set(self.schema["properties"]["aggregate"]["properties"]["denied_classes"]["items"]["enum"])
        self.assertEqual(enum, DENIED_CLASSES, "denied_classes enum must be the full DC-EA-RED authoritative set (§3).")

    def test_entries_and_objects_forbid_additional_properties(self) -> None:
        # Structural no-content-leak: every object closes additionalProperties.
        self.assertFalse(self.schema.get("additionalProperties", True))
        self.assertFalse(self.schema["properties"]["entries"]["items"].get("additionalProperties", True))
        self.assertFalse(self.schema["properties"]["scope"].get("additionalProperties", True))
        self.assertFalse(self.schema["properties"]["aggregate"].get("additionalProperties", True))

    def test_is_container_field_cannot_regress(self) -> None:
        entry_props = self.schema["properties"]["entries"]["items"]["properties"]
        self.assertNotIn("is_container", entry_props, "the removed is_container per-entry field must not return (2026-06-13 amendment).")

    def test_root_ref_is_opaque_not_raw_path(self) -> None:
        pattern = self.schema["properties"]["entries"]["items"]["properties"]["root_ref"].get("pattern", "")
        self.assertIn("managed_root:", pattern, "root_ref must be an opaque managed_root:<uuid> ref, never a raw path (KVKK m.4).")

    def test_root_ref_requires_uuid_shape(self) -> None:
        # Codex 019f00f6 absorb: the pattern is a strict UUID, not just 36 chars.
        instance = load_json(FIXTURES / "invalid-content-hash-v1.json")
        del instance["entries"][0]["sha256"]  # isolate the root_ref violation
        instance["entries"][0]["root_ref"] = "managed_root:not-a-real-uuid-shape-here"
        errors = list(self.validator.iter_errors(instance))
        paths = {tuple(e.absolute_path) for e in errors}
        self.assertEqual(
            paths, {("entries", 0, "root_ref")},
            f"a non-UUID root_ref must be the ONLY violation (strict UUID pattern); paths={paths}",
        )

    def test_generated_at_must_be_iso8601(self) -> None:
        # Codex 019f00f6 absorb: generated_at is hard-gated by the schema's
        # dependency-free ISO-8601 regex pattern (not FormatChecker).
        instance = load_json(FIXTURES / "invalid-content-hash-v1.json")
        del instance["entries"][0]["sha256"]  # isolate the timestamp violation
        instance["generated_at"] = "not-a-timestamp"
        errors = list(self.validator.iter_errors(instance))
        paths = {tuple(e.absolute_path) for e in errors}
        self.assertEqual(
            paths, {("generated_at",)},
            f"a non-ISO-8601 generated_at must be the ONLY violation (ISO-8601 regex pattern gate); paths={paths}",
        )


if __name__ == "__main__":
    unittest.main()
