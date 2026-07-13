from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/automation/backend-testai-digest-contract.py"
REQUIRED = (
    "auth-service",
    "permission-service",
    "user-service",
    "variant-service",
    "core-data-service",
    "report-service",
    "schema-service",
    "endpoint-admin-service",
    "audio-gateway-service",
    "meeting-service",
    "transcript-service",
    "audit-event-consumer-service",
    "api-gateway",
)


class BackendTestaiDigestContractTests(unittest.TestCase):
    def run_normalize(self, payload: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "normalize"],
            cwd=ROOT,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def full_map(self) -> dict[str, str]:
        return {service: f"sha256:{index:064x}" for index, service in enumerate(REQUIRED, 1)}

    def test_full_map_is_canonical_and_build_only_entries_are_removed(self):
        payload = self.full_map()
        payload["discovery-server"] = f"sha256:{100:064x}"
        payload["notification-orchestrator"] = f"sha256:{101:064x}"
        result = self.run_normalize(payload)
        self.assertEqual(0, result.returncode, result.stderr)
        normalized = json.loads(result.stdout)
        self.assertEqual(set(REQUIRED), set(normalized))
        self.assertNotIn("discovery-server", normalized)

    def test_stringified_dispatch_payload_is_supported(self):
        payload = json.dumps(self.full_map())
        result = self.run_normalize(payload)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.full_map(), json.loads(result.stdout))

    def test_partial_and_unknown_maps_fail_closed(self):
        partial = self.full_map()
        partial.pop("api-gateway")
        partial_result = self.run_normalize(partial)
        self.assertNotEqual(0, partial_result.returncode)
        self.assertIn("full runtime map required", partial_result.stderr)

        unknown = self.full_map()
        unknown["shadow-service"] = f"sha256:{999:064x}"
        unknown_result = self.run_normalize(unknown)
        self.assertNotEqual(0, unknown_result.returncode)
        self.assertIn("unknown service", unknown_result.stderr)

    def test_overlay_inspection_returns_all_required_services(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), "inspect"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(set(REQUIRED), set(json.loads(result.stdout)))


if __name__ == "__main__":
    unittest.main()
