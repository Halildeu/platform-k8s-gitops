import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_faz24_readiness_rollup.py"

REQUIRED_GATES = [
    "foundation_deploy",
    "recorder_edge_lifecycle",
    "gcap_aggregate",
    "desktop_capture",
    "direct_stt_preflight",
    "direct_stt_e2e",
    "compute_plane_audit",
    "wg_bplus_i3",
    "wg_bplus_i6",
    "i7_live_stt_app_mtls",
    "i7_full_prod_gate",
    "cert_rotation_drill",
    "gops_operability",
    "gcomp_engineering",
    "retention_lifecycle",
    "gwer_der_pilot",
    "gint_pilot",
    "glat_cost_pilot",
    "browser_smoke",
]


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.readinessRollupEvidence.v1",
        "status": "pass",
        "issue": "platform-k8s-gitops#1615",
        "generatedAt": "2026-06-28T15:00:00Z",
        "tokenIncluded": False,
        "gates": [
            {
                "name": name,
                "status": "pass",
                "acceptedByVerifier": True,
                "evidenceRef": f"github-actions://Halildeu/platform-k8s-gitops/actions/runs/28{name}",
                "issueRef": "platform-k8s-gitops#1615",
                "observedAt": "2026-06-28T15:00:00Z",
                "summary": f"{name} accepted by its redacted verifier evidence",
            }
            for name in REQUIRED_GATES
        ],
        "boundaries": {
            "allRequiredGatesAccepted": True,
            "secretsIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "rawPromptIncluded": False,
            "rawResponseIncluded": False,
            "unredactedPersonalDataIncluded": False,
            "directClientToStt": False,
            "legalAdviceClaimed": False,
            "legalAcceptanceClaimed": False,
            "productionLegalGoClaimed": False,
            "runtimeMutationPerformedByVerifier": False,
            "productionReady": False,
        },
        "failures": [],
    }


def run_verifier(tmp_path: Path, payload) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "faz24-readiness-rollup.json"
    if isinstance(payload, str):
        evidence_file.write_text(payload, encoding="utf-8")
    else:
        evidence_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence-file", str(evidence_file)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_valid_rollup_passes(tmp_path):
    proc = run_verifier(tmp_path, valid_evidence())
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["evidenceSchemaVersion"] == "faz24.readinessRollupEvidence.v1"
    assert report["openGates"] == []
    assert report["blockedGates"] == []
    assert report["tokenIncluded"] is False


def test_current_partial_rollup_blocks(tmp_path):
    data = valid_evidence()
    data["status"] = "blocked"
    data["boundaries"]["allRequiredGatesAccepted"] = False
    for gate in data["gates"]:
        if gate["name"] in {
            "desktop_capture",
            "direct_stt_preflight",
            "direct_stt_e2e",
            "wg_bplus_i3",
            "i7_full_prod_gate",
            "gops_operability",
            "gcomp_engineering",
            "gwer_der_pilot",
            "gint_pilot",
            "glat_cost_pilot",
            "browser_smoke",
        }:
            gate["status"] = "blocked"
            gate["acceptedByVerifier"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert "direct_stt_e2e" in report["openGates"]
    assert "i7_full_prod_gate" in report["blockedGates"]
    assert any("top-level status must be pass" in failure for failure in report["failures"])


def test_missing_required_gate_blocks(tmp_path):
    data = valid_evidence()
    data["gates"] = [gate for gate in data["gates"] if gate["name"] != "gcomp_engineering"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert "gcomp_engineering" in report["blockedGates"]
    assert any("missing required gates" in failure for failure in report["failures"])


def test_missing_cert_rotation_drill_gate_blocks(tmp_path):
    data = valid_evidence()
    data["gates"] = [gate for gate in data["gates"] if gate["name"] != "cert_rotation_drill"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert "cert_rotation_drill" in report["blockedGates"]
    assert "cert_rotation_drill" in report["requiredGates"]
    assert any("missing required gates" in failure for failure in report["failures"])


def test_gate_without_verifier_acceptance_blocks(tmp_path):
    data = valid_evidence()
    data["gates"][0]["acceptedByVerifier"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert data["gates"][0]["name"] in report["blockedGates"]
    assert any("acceptedByVerifier must be true" in failure for failure in report["failures"])


def test_unsafe_evidence_ref_blocks(tmp_path):
    data = valid_evidence()
    data["gates"][0]["evidenceRef"] = "https://example.invalid/raw-log.txt"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("evidenceRef" in failure for failure in report["failures"])


def test_platform_mobile_issue_ref_is_allowed_for_client_smoke(tmp_path):
    data = valid_evidence()
    for gate in data["gates"]:
        if gate["name"] == "browser_smoke":
            gate["issueRef"] = "platform-mobile#57"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"


def test_production_ready_overclaim_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["productionReady"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("productionReady" in failure for failure in report["failures"])


def test_legal_acceptance_overclaim_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["legalAcceptanceClaimed"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("legalAcceptanceClaimed" in failure for failure in report["failures"])


def test_sensitive_key_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {"vault_token": "redacted-looking-but-forbidden"}

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("forbidden key" in failure for failure in report["failures"])


def test_token_shaped_value_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {
        "message": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcHMifQ.signature"
    }

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("secret-like" in failure for failure in report["failures"])


def test_invalid_json_returns_error(tmp_path):
    proc = run_verifier(tmp_path, "{not-json")
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert any("invalid JSON" in failure for failure in report["failures"])
