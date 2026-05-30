"""Self-validation for the AG-036 outdated-software payload contract v1.

Faz 22.5 — AG-036 `upgradeCount` wire-semantics decision (board #1147, Codex
thread 019e77df). The `schema/endpoint-*-payload-v1.schema.json` contracts
were previously validated ONLY by the downstream consumer test suites
(platform-backend / platform-web); this test makes the contract repo
machine-enforce its own invariants so the decision cannot silently regress:

  * the 3 inline golden examples + the truncated golden fixture validate
    against the schema (positive regression corpus),
  * `upgradeCount` is bounded [0, maxUpgrade=512] — a value > 512 is rejected
    (lockstep with the agent cap, the backend policy [0,512], and the DB
    CHECK upgrade_count <= max_upgrade),
  * the truncated golden is a TRUTHFUL instance (exactly 512 packages,
    upgradeCount == len(upgrade) == maxUpgrade, upgradeTruncated == true),
  * the stale pre-#40 "parser caps before upgradeTruncated is evaluated ->
    upgradeTruncated=false" wording cannot creep back into the schema.

Run: python3 -m unittest tests.contracts.test_outdated_software_payload_contract_v1 -v
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = REPO_ROOT / "schema" / "endpoint-outdated-software-payload-v1.schema.json"
FIXTURES = REPO_ROOT / "tests" / "contracts" / "fixtures" / "outdated-software"

MAX_UPGRADE = 512


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestOutdatedSoftwarePayloadContractV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA)
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_is_valid_draft202012(self) -> None:
        # Raises SchemaError on an invalid schema.
        Draft202012Validator.check_schema(self.schema)

    def test_inline_golden_examples_validate(self) -> None:
        examples = self.schema.get("examples", [])
        self.assertEqual(
            len(examples), 3,
            "expected the 3 inline golden examples (with-upgrades / clean / unsupported); "
            "the truncated golden lives as a separate fixture, not inline.",
        )
        for i, example in enumerate(examples):
            with self.subTest(example=i):
                errors = list(self.validator.iter_errors(example))
                self.assertEqual(
                    errors, [],
                    f"inline example[{i}] must validate: "
                    + (errors[0].message if errors else ""),
                )

    def test_upgrade_count_is_bounded_zero_to_max(self) -> None:
        uc = self.schema["properties"]["upgradeCount"]
        self.assertEqual(uc.get("type"), "integer")
        self.assertEqual(uc.get("minimum"), 0)
        self.assertEqual(
            uc.get("maximum"), MAX_UPGRADE,
            "upgradeCount MUST machine-enforce maximum:512 (the capped-count "
            "decision, in lockstep with the backend policy + DB CHECK).",
        )

    def test_cap_invariants_are_pinned(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(props["maxUpgrade"].get("const"), MAX_UPGRADE)
        self.assertEqual(props["upgrade"].get("maxItems"), MAX_UPGRADE)
        self.assertEqual(props["schemaVersion"].get("const"), 1)

    def test_upgrade_count_above_cap_is_rejected(self) -> None:
        # The negative fixture isolates the maximum:512 guard.
        instance = load_json(FIXTURES / "invalid-upgradecount-above-cap-v1.json")
        self.assertEqual(instance["upgradeCount"], 513)
        errors = list(self.validator.iter_errors(instance))
        self.assertTrue(
            errors, "upgradeCount=513 MUST be rejected by maximum:512 (it was not)."
        )
        joined = " | ".join(e.message for e in errors)
        self.assertIn(
            "512", joined,
            f"rejection should cite the 512 maximum; got: {joined}",
        )
        # The ONLY violation must be upgradeCount (every other field valid),
        # so the failing path is unambiguously the maximum:512 guard — exact
        # set equality, not mere membership, locks the isolation.
        paths = {tuple(e.absolute_path) for e in errors}
        self.assertEqual(
            paths, {("upgradeCount",)},
            "the negative fixture must violate ONLY the upgradeCount bound so the "
            f"maximum:512 guard is isolated; paths={paths}",
        )

    def test_truncated_golden_is_truthful_and_valid(self) -> None:
        instance = load_json(FIXTURES / "valid-truncated-v1.json")
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual(
            errors, [],
            "valid-truncated-v1 must validate: "
            + (errors[0].message if errors else ""),
        )
        # Truthful truncated instance: exactly the agent's post-#40 shape.
        self.assertIs(instance["supported"], True)
        self.assertIs(instance["probeComplete"], True)
        self.assertIs(instance["upgradeTruncated"], True)
        self.assertEqual(instance["maxUpgrade"], MAX_UPGRADE)
        self.assertEqual(instance["upgradeCount"], MAX_UPGRADE)
        self.assertEqual(
            len(instance["upgrade"]), MAX_UPGRADE,
            "a truthful truncated payload carries exactly maxUpgrade packages "
            "(upgradeCount == len(upgrade) == maxUpgrade); a smaller list would "
            "be a lying fixture.",
        )
        self.assertEqual(instance["sourceUsed"], "winget")

    def test_stale_pre_pr40_wording_cannot_regress(self) -> None:
        # Guard the decision: the pre-#40 "parser caps before the flag is
        # evaluated -> upgradeTruncated=false" wording must not return, and
        # upgradeTruncated must be described as authoritative.
        schema_text = SCHEMA.read_text(encoding="utf-8")
        self.assertNotIn(
            "caps at 512 before", schema_text,
            "stale pre-#40 truncation wording must not regress into the schema.",
        )
        trunc_desc = self.schema["properties"]["upgradeTruncated"]["description"].lower()
        self.assertIn(
            "authoritative", trunc_desc,
            "upgradeTruncated must be documented as the authoritative truncation signal.",
        )


if __name__ == "__main__":
    unittest.main()
