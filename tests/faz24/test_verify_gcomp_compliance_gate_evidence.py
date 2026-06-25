import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_gcomp_compliance_gate_evidence.py"

REQUIRED_CHECKS = [
    "consent",
    "retention",
    "legal_hold",
    "access_audit",
    "deletion_export",
    "kvkk_verbis",
    "redaction",
    "runbook",
]


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.gcompComplianceEvidence.v1",
        "status": "pass",
        "tokenIncluded": False,
        "environment": {"name": "compliance-pilot-1", "class": "compliance-drill"},
        "checks": [
            {
                "name": name,
                "status": "pass",
                "evidenceRef": f"protected://faz24/gcomp/{name}/2026-06-25",
            }
            for name in REQUIRED_CHECKS
        ],
        "metrics": {
            "consentCoverage": 1.0,
            "retentionPolicyCoverage": 1.0,
            "accessAuditCoverage": 0.98,
            "deletionExportCoverage": 1.0,
            "redactionCoverage": 1.0,
            "dataSubjectResponseDays": 7,
            "legalHoldDrillAgeDays": 14,
            "dbCleanupEvidenceAgeDays": 3,
        },
        "boundaries": {
            "consentEvidencePresent": True,
            "retentionEvidencePresent": True,
            "legalHoldEvidencePresent": True,
            "accessAuditEvidencePresent": True,
            "deletionExportEvidencePresent": True,
            "kvkkVerbisEvidencePresent": True,
            "redactionEvidencePresent": True,
            "secretsIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "rawPromptIncluded": False,
            "rawResponseIncluded": False,
            "unredactedPersonalDataIncluded": False,
            "legalAdviceClaimed": False,
            "liveProductionMutation": False,
            "productionReady": False,
        },
        "failures": [],
    }


def run_verifier(tmp_path: Path, payload, *extra_args: str) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "gcomp-evidence.json"
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


def run_verifier_stdin(tmp_path: Path, payload, *extra_args: str) -> subprocess.CompletedProcess[str]:
    if isinstance(payload, str):
        input_data = payload
    else:
        input_data = json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra_args],
        input=input_data,
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
    assert report["evidenceSchemaVersion"] == "faz24.gcompComplianceEvidence.v1"
    assert report["failures"] == []


def test_missing_required_check_blocks(tmp_path):
    data = valid_evidence()
    data["checks"] = [check for check in data["checks"] if check["name"] != "kvkk_verbis"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("required checks" in failure for failure in report["failures"])


def test_skipped_kvkk_verbis_check_blocks(tmp_path):
    data = valid_evidence()
    for check in data["checks"]:
        if check["name"] == "kvkk_verbis":
            check["status"] = "skipped"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("check kvkk_verbis status must be pass" in failure for failure in report["failures"])


def test_consent_coverage_threshold_miss_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["consentCoverage"] = 0.75

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("consentCoverage" in failure for failure in report["failures"])


def test_data_subject_response_threshold_miss_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["dataSubjectResponseDays"] = 45

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("dataSubjectResponseDays" in failure for failure in report["failures"])


def test_old_db_cleanup_evidence_fails(tmp_path):
    data = valid_evidence()
    data["metrics"]["dbCleanupEvidenceAgeDays"] = 120

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("dbCleanupEvidenceAgeDays" in failure for failure in report["failures"])


def test_missing_metric_blocks(tmp_path):
    data = valid_evidence()
    del data["metrics"]["redactionCoverage"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("redactionCoverage" in failure for failure in report["failures"])


def test_github_actions_run_id_evidence_ref_does_not_fail_as_personal_data(tmp_path):
    data = valid_evidence()
    data["checks"][0]["evidenceRef"] = (
        "github-actions://Halildeu/platform-k8s-gitops/actions/runs/28187020107"
    )

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"


def test_email_like_evidence_ref_does_not_fail_as_personal_data(tmp_path):
    data = valid_evidence()
    data["checks"][0]["evidenceRef"] = "operator://dpo@compliance.acik.com/review/2026-06-25"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"


def test_negative_metric_blocks(tmp_path):
    data = valid_evidence()
    data["metrics"]["legalHoldDrillAgeDays"] = -1

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("legalHoldDrillAgeDays must be numeric and >= 0" in failure for failure in report["failures"])


def test_missing_legal_operator_boundary_blocks(tmp_path):
    data = valid_evidence()
    data["boundaries"]["kvkkVerbisEvidencePresent"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("kvkkVerbisEvidencePresent" in failure for failure in report["failures"])


def test_sensitive_key_leak_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {"vault_token": "redacted-looking-but-forbidden"}

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("forbidden key" in failure for failure in report["failures"])


def test_personal_data_value_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {"redacted_note": "participant ali@example.com"}

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("sensitive value" in failure for failure in report["failures"])


def test_token_shaped_value_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {
        "message": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvcHMifQ.signature"
    }

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("sensitive value" in failure for failure in report["failures"])


def test_raw_transcript_key_fails(tmp_path):
    data = valid_evidence()
    data["diagnostic"] = {"raw_transcript": "not allowed"}

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


def test_legal_advice_overclaim_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["legalAdviceClaimed"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("legalAdviceClaimed" in failure for failure in report["failures"])


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
    data["failures"] = ["VERBIS evidence missing"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("failures must be absent or empty" in failure for failure in report["failures"])


def test_wrong_schema_version_fails(tmp_path):
    data = valid_evidence()
    data["schemaVersion"] = "faz24.gcompComplianceEvidence.v2"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("schemaVersion must be" in failure for failure in report["failures"])


def test_invalid_environment_class_blocks(tmp_path):
    data = valid_evidence()
    data["environment"]["class"] = "production"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("environment.class" in failure for failure in report["failures"])


def test_invalid_evidence_ref_blocks(tmp_path):
    data = valid_evidence()
    data["checks"][0]["evidenceRef"] = "https://example.com/raw-export"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("evidenceRef" in failure for failure in report["failures"])


def test_stdin_and_output_file_path(tmp_path):
    output_file = tmp_path / "gcomp.verify.json"

    proc = run_verifier_stdin(tmp_path, valid_evidence(), "--output-file", str(output_file))
    report = json.loads(proc.stdout)
    file_report = json.loads(output_file.read_text(encoding="utf-8"))

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert file_report["status"] == "pass"
    assert output_file.stat().st_mode & 0o777 == 0o600


def test_invalid_json_returns_error(tmp_path):
    proc = run_verifier(tmp_path, "{not-json")
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert "invalid JSON" in report["failures"][0]
