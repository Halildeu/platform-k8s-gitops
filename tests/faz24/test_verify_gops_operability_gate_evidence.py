import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_gops_operability_gate_evidence.py"

REQUIRED_CHECKS = [
    "install",
    "upgrade",
    "backup",
    "restore",
    "rollback",
    "secret_delivery",
    "observability",
    "runbook",
]


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.gopsOperabilityEvidence.v1",
        "status": "pass",
        "tokenIncluded": False,
        "environment": {"name": "onprem-pilot-1", "class": "onprem-pilot"},
        "checks": [
            {
                "name": name,
                "status": "pass",
                "evidenceRef": f"github-actions://Halildeu/platform-k8s-gitops/actions/runs/202600{name}",
            }
            for name in REQUIRED_CHECKS
        ],
        "metrics": {
            "installDurationMinutes": 45,
            "upgradeDurationMinutes": 35,
            "backupAgeHours": 4,
            "restoreRtoMinutes": 90,
            "restoreRpoMinutes": 20,
            "rollbackRtoMinutes": 25,
            "secretRotationMinutes": 12,
            "observabilityCoverage": 0.95,
        },
        "boundaries": {
            "installEvidencePresent": True,
            "upgradeEvidencePresent": True,
            "backupEvidencePresent": True,
            "restoreEvidencePresent": True,
            "rollbackEvidencePresent": True,
            "secretDeliveryEvidencePresent": True,
            "observabilityEvidencePresent": True,
            "runbookEvidencePresent": True,
            "secretsIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "liveProductionMutation": False,
            "productionReady": False,
        },
        "failures": [],
    }


def run_verifier(tmp_path: Path, payload, *extra_args: str) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "gops-evidence.json"
    if isinstance(payload, str):
        evidence_file.write_text(payload, encoding="utf-8")
    else:
        evidence_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence-file", str(evidence_file), *extra_args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_valid_evidence_passes(tmp_path):
    proc = run_verifier(tmp_path, valid_evidence())
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert report["evidenceSchemaVersion"] == "faz24.gopsOperabilityEvidence.v1"
    assert report["failures"] == []


def test_missing_required_check_blocks(tmp_path):
    data = valid_evidence()
    data["checks"] = [check for check in data["checks"] if check["name"] != "restore"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("required checks" in failure for failure in report["failures"])


def test_skipped_required_check_blocks(tmp_path):
    data = valid_evidence()
    data["checks"][0]["status"] = "skipped"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("check install status must be pass" in failure for failure in report["failures"])


def test_restore_rto_threshold_miss_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["restoreRtoMinutes"] = 300

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("restoreRtoMinutes" in failure for failure in report["failures"])


def test_backup_age_threshold_miss_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["backupAgeHours"] = 48

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("backupAgeHours" in failure for failure in report["failures"])


def test_low_observability_coverage_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["observabilityCoverage"] = 0.5

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("observabilityCoverage" in failure for failure in report["failures"])


def test_missing_metric_blocks(tmp_path):
    data = valid_evidence()
    del data["metrics"]["secretRotationMinutes"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("secretRotationMinutes" in failure for failure in report["failures"])


def test_negative_metric_blocks(tmp_path):
    data = valid_evidence()
    data["metrics"]["installDurationMinutes"] = -1

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("installDurationMinutes must be numeric and >= 0" in failure for failure in report["failures"])


def test_sensitive_key_leak_fails(tmp_path):
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
    assert any("secret-like value" in failure for failure in report["failures"])


def test_raw_audio_key_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {"raw_audio": "not allowed"}

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("forbidden key" in failure for failure in report["failures"])


def test_production_ready_overclaim_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["productionReady"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("productionReady" in failure for failure in report["failures"])


def test_top_level_token_included_fails(tmp_path):
    data = valid_evidence()
    data["tokenIncluded"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("tokenIncluded" in failure for failure in report["failures"])


def test_top_level_status_not_pass_fails(tmp_path):
    data = valid_evidence()
    data["status"] = "fail"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("status must be pass" in failure for failure in report["failures"])


def test_top_level_failures_not_empty_fails(tmp_path):
    data = valid_evidence()
    data["failures"] = ["restore evidence rejected"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("failures must be absent or empty" in failure for failure in report["failures"])


def test_invalid_evidence_ref_blocks(tmp_path):
    data = valid_evidence()
    data["checks"][0]["evidenceRef"] = "https://example.com/raw-log"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("evidenceRef" in failure for failure in report["failures"])


def test_invalid_json_returns_error(tmp_path):
    proc = run_verifier(tmp_path, "{not-json")
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert "invalid JSON" in report["failures"][0]
