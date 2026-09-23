"""Probe refuses stale, slow, missing, fabricated or wrongly assigned updates."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "live_probe", Path(__file__).parents[2] / "scripts/faz24/live_incremental_latency_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LiveProbeTest(unittest.TestCase):
    def body(self):
        return {"is_partial": True, "version": 3, "decisions": [probe.SOURCE[1]],
                "action_items": [{"text": probe.SOURCE[2], "owner": "Mehmet", "due_date": None}],
                "ungrounded_count": 0, "grounding_policy": "verified_only", "live_cursor": {}}

    def test_accepts_correct_update_and_optional_explicit_cancellation_decision(self):
        body = self.body()
        self.assertTrue(probe.metadata(body, 3, [1], [2], 1)["qualityPass"])
        body["decisions"].append(probe.SOURCE[3])
        self.assertTrue(probe.metadata(body, 3, [1], [2], 1)["qualityPass"])

    def test_rejects_missing_stale_final_fabricated_or_wrong_owner_update(self):
        changes = [{"version": 1}, {"is_partial": False}, {"decisions": []},
                   {"decisions": ["invented"]}, {"action_items": []},
                   {"action_items": [{"text": probe.SOURCE[2], "owner": "Ayşe"}]},
                   {"ungrounded_count": 1}]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(probe.metadata(self.body() | change, 3, [1], [2], 1)["qualityPass"])

    def test_no_latency_pass_from_recording_staying_open(self):
        result = probe.metadata(self.body(), 3, [1], [2], 76)
        self.assertTrue(result["qualityPass"])
        self.assertFalse(result["withinFiveSeconds"])
        self.assertNotIn("Mehmet", str(result))


if __name__ == "__main__":
    unittest.main()
