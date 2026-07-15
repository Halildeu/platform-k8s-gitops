import copy
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = (
    Path(__file__).parents[2]
    / "scripts/faz22-remote-ops/assemble-view-only-viewer-product-evidence.py"
)
SPEC = importlib.util.spec_from_file_location("viewer_product_assembler", MODULE_PATH)
ASSEMBLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ASSEMBLER
SPEC.loader.exec_module(ASSEMBLER)


class ViewerProductEvidenceAssemblerTest(unittest.TestCase):
    def assemble(self, client=None, source_ids=None):
        return ASSEMBLER.assemble(
            client or fixtures.FakeClient(),
            fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.RUN_ID,
            1,
            fixtures.HEAD_SHA,
            source_ids or copy.deepcopy(fixtures.SOURCE_RUN_IDS),
            generated_at=datetime(2026, 7, 14, 0, 6, 1, tzinfo=timezone.utc),
        )

    def test_valid_sources_are_copied_byte_for_byte(self):
        client = fixtures.FakeClient()
        root, files = self.assemble(client)
        self.assertEqual(fixtures.binding(), root["binding"])
        expected = {"viewer-product-evidence.json"}
        expected.update(f"evidence/{name}.json" for name in fixtures.SOURCE_TYPES)
        self.assertEqual(expected, set(files))
        for name in fixtures.SOURCE_TYPES:
            self.assertEqual(client.source_children[name], files[f"evidence/{name}.json"])
        self.assertEqual(
            {"startedAt": "2026-07-14T00:01:00Z", "endedAt": "2026-07-14T00:06:00Z"},
            root["pilot"],
        )

    def test_duplicate_source_run_fails_closed(self):
        source_ids = copy.deepcopy(fixtures.SOURCE_RUN_IDS)
        source_ids["broker"] = source_ids["browser"]
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "distinct source run"):
            self.assemble(source_ids=source_ids)

    def test_cross_session_child_fails_closed(self):
        children = fixtures.child_documents()
        children["audit"]["binding"]["sessionSha256"] = fixtures.sha("a")
        client = fixtures.FakeClient(fixtures.build_archive(children=children))
        with self.assertRaisesRegex(ASSEMBLER.AssemblyError, "same-session binding"):
            self.assemble(client)

    def test_tampered_source_archive_fails_closed(self):
        client = fixtures.FakeClient()
        client.source_archives["browser"] = fixtures.encode_zip({
            "evidence/browser.json": b"{}\n",
            "evidence/consent.json": b"{}\n",
            "evidence/consent-source.json": b"{}\n",
        })
        with self.assertRaisesRegex(ASSEMBLER.VERIFIER.EvidenceError, "schema invalid"):
            self.assemble(client)


if __name__ == "__main__":
    unittest.main()
