"""Faz 35 / ES-008 — the relation registry must cover the model exactly.

The authorization model is where a mistake is cheapest to make and most expensive
to find: adding a relation is one line, and nothing downstream complains if
nobody ever states what it must *not* reach. This gate makes that line fail CI
until someone writes the deny down.

The registry is not documentation that trails the model. It is compared against
the model in both directions:

  * a relation in the model but not the registry  -> fail (a new grant landed
    without anyone stating its boundary)
  * a relation in the registry but not the model  -> fail (the registry is
    describing something that no longer exists, which reads as coverage it does
    not have)

Every entry must also carry a non-empty ``denies``. "Allows X" alone is the easy
half; the deny is the part that turns a registry into a boundary.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "runtime-artifacts/faz35-etik-speak/authorization-model-v1.fga"
REGISTRY = ROOT / "runtime-artifacts/faz35-etik-speak/relation-registry-v1.json"

TYPE_LINE = re.compile(r"^type\s+(\S+)\s*$")
RELATION_LINE = re.compile(r"^\s+define\s+([A-Za-z_][A-Za-z0-9_]*)\s*:")


def parse_model(text: str) -> set[tuple[str, str]]:
    """Return {(type, relation)} for every relation the .fga model defines."""
    found: set[tuple[str, str]] = set()
    current: str | None = None
    for line in text.splitlines():
        type_match = TYPE_LINE.match(line)
        if type_match:
            current = type_match.group(1)
            continue
        relation_match = RELATION_LINE.match(line)
        if relation_match:
            if current is None:
                raise AssertionError(f"relation outside any type: {line!r}")
            found.add((current, relation_match.group(1)))
    return found


class Faz35RelationRegistryCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_text = MODEL.read_text()
        cls.registry = json.loads(REGISTRY.read_text())

    def test_parser_actually_sees_the_model(self):
        """A parser that silently matches nothing would make every other check vacuous."""
        parsed = parse_model(self.model_text)
        self.assertGreater(len(parsed), 15)
        # Two relations that must exist for the staff path to work at all.
        self.assertIn(("ethics_product", "case_viewer"), parsed)
        self.assertIn(("ethics_case", "recused"), parsed)

    def test_registry_and_model_cover_each_other_exactly(self):
        model = parse_model(self.model_text)
        registered = {
            (entry["type"], entry["relation"]) for entry in self.registry["relations"]
        }

        missing = sorted(model - registered)
        self.assertEqual(
            missing,
            [],
            f"model relations with no registry entry (state what each one denies): {missing}",
        )

        stale = sorted(registered - model)
        self.assertEqual(
            stale,
            [],
            f"registry entries for relations the model no longer defines: {stale}",
        )

    def test_every_entry_states_what_it_denies(self):
        for entry in self.registry["relations"]:
            label = f'{entry["type"]}.{entry["relation"]}'
            with self.subTest(relation=label):
                self.assertTrue(entry.get("allows", "").strip(), f"{label}: allows is empty")
                denies = entry.get("denies", "").strip()
                self.assertTrue(denies, f"{label}: denies is empty")
                # "None"/"n/a" would pass a length check while saying nothing.
                self.assertNotIn(denies.lower(), {"none", "n/a", "na", "-"})
                self.assertIn(entry.get("kind"), {"direct", "derived"})
                self.assertTrue(entry.get("owner_repo", "").strip())

    def test_derived_entries_record_their_derivation(self):
        """A derived relation's boundary is its expression; omitting it hides the subtraction."""
        for entry in self.registry["relations"]:
            if entry.get("kind") != "derived":
                continue
            label = f'{entry["type"]}.{entry["relation"]}'
            with self.subTest(relation=label):
                self.assertTrue(
                    entry.get("derivation", "").strip(),
                    f"{label}: derived relation without a derivation",
                )

    def test_subtractive_relations_are_registered_as_denying_the_case_relations(self):
        """content_denied / conflicted / recused exist only to take access away.

        If one of them were ever registered as allowing something, the registry
        would be describing a different system than the one that runs.
        """
        by_key = {(e["type"], e["relation"]): e for e in self.registry["relations"]}
        for key in (
            ("ethics_product", "content_denied"),
            ("ethics_case", "conflicted"),
            ("ethics_case", "recused"),
        ):
            with self.subTest(relation=".".join(key)):
                entry = by_key[key]
                self.assertIn("nothing", entry["allows"].lower())
                self.assertIn("case_", entry["denies"])

    def test_registry_declares_its_source_and_schema(self):
        self.assertEqual(self.registry["schema_version"], "faz35-relation-registry-v1")
        self.assertEqual(
            self.registry["model_source"],
            "runtime-artifacts/faz35-etik-speak/authorization-model-v1.fga",
        )
        self.assertTrue(MODEL.exists())


if __name__ == "__main__":
    unittest.main()
