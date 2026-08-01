"""Faz 35 ES-304 (#2666) — the decision matrix covers the frozen registry, both ways.

The registry (#2654) froze WHICH relations exist. This gate freezes that every one of
them is actually EXERCISED: a relation the model gained without a matrix row fails here,
and a matrix row naming a relation the registry does not carry fails here too. Without
the second direction the matrix could claim coverage it does not have — the same
two-way discipline the registry gate itself uses.
"""

from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/contracts/faz35-authorization-relation-registry.v1.json"
MATRIX = ROOT / "docs/contracts/faz35-authorization-decision-matrix.v1.json"


class Faz35DecisionMatrixCompletenessTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        cls.registry_keys = {
            (item["type"], item["relation"]) for item in cls.registry["relations"]
        }
        cls.matrix_keys = {(row["type"], row["relation"]) for row in cls.matrix["rows"]}

    def test_every_registry_relation_has_at_least_one_executed_row(self):
        missing = sorted(self.registry_keys - self.matrix_keys)
        self.assertEqual(
            missing, [],
            "a frozen relation is never exercised — coverage would be a claim, not a fact",
        )

    def test_the_matrix_never_claims_a_relation_the_registry_does_not_carry(self):
        extra = sorted(self.matrix_keys - self.registry_keys)
        self.assertEqual(
            extra, [],
            "the matrix asserts on a relation outside the frozen universe",
        )

    def test_the_matrix_binds_itself_to_the_registry_file(self):
        self.assertEqual(
            self.matrix["registry_source"],
            "docs/contracts/faz35-authorization-relation-registry.v1.json",
        )

    def test_source_only_rows_name_their_test_and_are_not_faked_as_denials(self):
        # The first live run (2026-08-01) returned HTTP 400 for two rows: their subject
        # or object type made the Check meaningless. Recording those as "deny" would be
        # a false compartment proof, so they carry execution=source and name the test
        # that actually covers them.
        for row in self.matrix["rows"]:
            if row.get("execution") == "source":
                with self.subTest(row=f"{row['type']}#{row['relation']}"):
                    self.assertTrue(row["source_test"].endswith(".py"))
                    self.assertEqual(row["persona"], "n/a")
                    self.assertTrue(
                        (ROOT / row["source_test"]).exists(),
                        "a source-only row names a test that does not exist",
                    )

    def test_every_row_declares_how_it_is_executed(self):
        modes = set(self.matrix["execution_modes"])
        for row in self.matrix["rows"]:
            self.assertIn(row.get("execution"), modes)

    def test_every_row_is_fully_specified(self):
        personas = set(self.matrix["persona_classes"])
        scopes = set(self.matrix["object_scopes"])
        for row in self.matrix["rows"]:
            if row.get("execution") == "source":
                continue
            with self.subTest(row=f"{row['type']}#{row['relation']}/{row['persona']}"):
                self.assertIn(row["persona"], personas)
                self.assertIn(row["object_scope"], scopes)
                self.assertIsInstance(row["expect"], bool)
                # A row without a reason is a row nobody can review later.
                self.assertGreaterEqual(len(row["rationale"].strip()), 20)

    def test_the_matrix_carries_denials_not_only_permissions(self):
        # A matrix of allows proves the product works; the denials are what prove the
        # compartments hold. ES-304's whole subject is the second half.
        denials = [row for row in self.matrix["rows"] if row["expect"] is False]
        self.assertGreater(len(denials), len(self.matrix["rows"]) // 2)

    def test_each_product_relation_is_denied_to_a_foreign_and_a_denied_principal(self):
        product = {
            key for key in self.registry_keys if key[0] == "ethics_product"
        }
        for key in sorted(product):
            covered = {
                (row["persona"], row["expect"])
                for row in self.matrix["rows"]
                if (row["type"], row["relation"]) == key and row.get("execution") == "live"
            }
            with self.subTest(relation=f"{key[0]}#{key[1]}"):
                self.assertIn(("wrong_org", False), covered)
                self.assertIn(("denied", False), covered)

    def test_no_single_principal_reconstructs_across_compartments(self):
        invariants = self.matrix["no_cross_compartment_reconstruction"]
        self.assertGreaterEqual(len(invariants), 4)
        pairs = {(item["holds"], item["must_not_hold"]) for item in invariants}
        # The two that carry the product's promise: case authority never unwraps the
        # reporter's identity, nor the sealed original evidence.
        self.assertIn(("case_handler", "subject_reveal_approved"), pairs)
        self.assertIn(("case_handler", "evidence_reveal_approved"), pairs)
        for item in invariants:
            self.assertIn((item["holds"],), [(k[1],) for k in self.registry_keys])
            self.assertIn((item["must_not_hold"],), [(k[1],) for k in self.registry_keys])


if __name__ == "__main__":
    unittest.main()
