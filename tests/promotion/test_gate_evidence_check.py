"""
tests/promotion/test_gate_evidence_check.py

Unit tests for scripts/promotion/gate-evidence-check.py — specifically the
`check_evidence(entry, jwt_validates_map)` function that was refactored in
FU-Gate-Refactor (2026-05-21) to delegate tier policy to the shared helper
`d29_evidence_policy.check_tiers()`.

Scope:
- Entry-level checks that STAY in the gate (not in the helper):
    1. `promotion.test.smoke_evidence is null` → reject
    2. `promotion.test.verified_at is null` → reject (with tiers OK)
- Tier-policy delegation that LIVES in the helper but is reachable here:
    3. Frontend (jwt_validates=false) + d29_zanzibar=AMBER → ACCEPT
    4. Backend (jwt_validates=true)  + d29_zanzibar=AMBER → REJECT
    5. d29_up=AMBER for any service → REJECT
- `load_zanzibar_required_services()` wrapper delegates correctly.

Run:
    python3 -m unittest tests.promotion.test_gate_evidence_check -v
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_PATH = _REPO_ROOT / "scripts" / "promotion" / "gate-evidence-check.py"


def _load_gate():
    """Import gate-evidence-check.py via importlib. The hyphen in the
    filename prevents normal `import` syntax."""
    import sys

    # The gate script does `import d29_evidence_policy` at module top, so the
    # promotion directory must be on sys.path before exec_module fires.
    promo_dir = str(_GATE_PATH.parent)
    if promo_dir not in sys.path:
        sys.path.insert(0, promo_dir)

    spec = importlib.util.spec_from_file_location("gate_evidence_check", _GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(
    service: str,
    up: str = "GREEN",
    fn: str = "GREEN",
    zb: str = "GREEN",
    verified_at: str | None = "2026-05-21T00:00:00Z",
    smoke_evidence_null: bool = False,
) -> dict:
    """Construct a minimal ledger-entry dict for check_evidence()."""
    if smoke_evidence_null:
        smoke = None
    else:
        smoke = {
            "d29_up": {"status": up, "checked_at": "2026-05-21T00:00:00Z"},
            "d29_functional": {"status": fn, "checked_at": "2026-05-21T00:00:00Z"},
            "d29_zanzibar": {
                "status": zb,
                "checked_at": "2026-05-21T00:00:00Z",
                "allow_deny_synthetic": "PASS" if zb == "GREEN" else "SKIP",
            },
        }
    return {
        "service": service,
        "repo": "platform-web" if service == "frontend" else "platform-backend",
        "image": {"digest": "sha256:" + "a" * 64, "path": "test/test"},
        "promotion": {
            "test": {
                "smoke_evidence": smoke,
                "verified_at": verified_at,
            }
        },
    }


class CheckEvidenceEntryLevelTests(unittest.TestCase):
    """Entry-level checks that live in the gate (not delegated to helper)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_gate()
        cls.jwt_map = {
            "user-service": True,
            "frontend": False,
            "auth-service": False,
            "core-data-service": True,
        }

    def test_smoke_evidence_null_rejects(self) -> None:
        entry = _entry("frontend", smoke_evidence_null=True)
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("smoke_evidence is null", reason)
        self.assertIn("smoke not run yet", reason)

    def test_verified_at_null_rejects(self) -> None:
        # Tiers all GREEN but verified_at missing → still reject (incomplete record).
        entry = _entry("user-service", up="GREEN", fn="GREEN", zb="GREEN", verified_at=None)
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("verified_at not set", reason)

    def test_verified_at_empty_string_rejects(self) -> None:
        entry = _entry("user-service", verified_at="")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("verified_at not set", reason)


class CheckEvidenceTierDelegationTests(unittest.TestCase):
    """Verify the gate correctly delegates to d29_evidence_policy.check_tiers()
    and reports the helper's reason text on rejection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_gate()
        cls.jwt_map = {
            "user-service": True,
            "frontend": False,
            "auth-service": False,
            "core-data-service": True,
        }

    def test_frontend_amber_zanzibar_accepts(self) -> None:
        """jwt_validates=false → AMBER zanzibar accepted; gate's verified_at +
        smoke_evidence checks pass; final ok=True."""
        entry = _entry("frontend", up="GREEN", fn="GREEN", zb="AMBER")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertTrue(ok, msg=reason)
        self.assertIn("GREEN-or-AMBER", reason)

    def test_backend_amber_zanzibar_rejects(self) -> None:
        """jwt_validates=true → AMBER zanzibar rejected; helper's reason
        bubbles up unchanged."""
        entry = _entry("user-service", up="GREEN", fn="GREEN", zb="AMBER")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("d29_zanzibar status=AMBER", reason)
        self.assertIn("Zanzibar-required", reason)

    def test_d29_up_amber_rejects_for_any_service(self) -> None:
        """d29_up is always strict GREEN — even lenient services reject on AMBER."""
        entry = _entry("frontend", up="AMBER", fn="GREEN", zb="AMBER")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("d29_up status=AMBER", reason)

    def test_d29_functional_red_rejects_for_any_service(self) -> None:
        entry = _entry("frontend", up="GREEN", fn="RED", zb="GREEN")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("d29_functional status=RED", reason)

    def test_unknown_service_defaults_to_strict(self) -> None:
        """Service missing from services.yaml → default jwt_validates=true →
        AMBER zanzibar rejects."""
        entry = _entry("future-service-not-in-catalog", up="GREEN", fn="GREEN", zb="AMBER")
        ok, reason = self.mod.check_evidence(entry, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("Zanzibar-required", reason)


class LoadZanzibarRequiredServicesWrapperTests(unittest.TestCase):
    """The wrapper must return the same shape as the helper's
    load_jwt_validates_map() — bool-valued dict keyed by service name."""

    def test_wrapper_returns_dict(self) -> None:
        mod = _load_gate()
        m = mod.load_zanzibar_required_services()
        # Real catalog should be populated (services.yaml exists in repo).
        self.assertIsInstance(m, dict)
        # Frontend is jwt_validates=false per ADR-0022; verifies the wrapper
        # delegates to the helper which reads the real catalog.
        self.assertIn("frontend", m)
        self.assertEqual(m["frontend"], False)
        self.assertIn("api-gateway", m)
        self.assertEqual(m["api-gateway"], True)


if __name__ == "__main__":
    unittest.main()
