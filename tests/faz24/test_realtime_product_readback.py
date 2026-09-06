import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/faz24/run_speechmatics_realtime_lifecycle_acceptance.py"
SPEC = importlib.util.spec_from_file_location("realtime_product", SCRIPT)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
RUN = "11111111-1111-4111-8111-111111111111"
MEETING = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def result():
    return {
        "analysisRunId": RUN, "meetingId": MEETING, "sessionId": SESSION,
        "persisted": True, "summary": "Synthetic project report approved.",
        "summary_grounding_status": "verified",
        "decisions": ["Use the test environment."],
        "action_items": [{"text": "Prepare a report."}],
    }


@pytest.mark.parametrize("change", [
    {"summary": ""}, {"summary": " \n "}, {"summary": None},
    {"summary_grounding_status": "withheld"}, {"summary_grounding_status": "partial"},
    {"decisions": []}, {"decisions": [" "]}, {"decisions": "bad"},
    {"action_items": []}, {"action_items": [{"text": ""}]},
    {"action_items": ["bad"]}, {"persisted": False}, {"persisted": "true"},
    {"analysisRunId": None},
])
def test_empty_or_nonpersisted_output_is_not_product_acceptance(result, change):
    result.update(change)
    assert helper.product_evidence(result)["usableProductResult"] is False


def test_product_evidence_only_contains_counts_and_flags(result):
    evidence = helper.product_evidence(result)
    assert evidence["usableProductResult"] is True
    assert evidence["decisionCount"] == evidence["actionCount"] == 1
    assert result["summary"] not in json.dumps(evidence)
    assert "Use the test" not in json.dumps(evidence)


def readback(monkeypatch, result, source_change=None, reopened_change=None):
    text = "Synthetic canonical transcript."
    source = {
        "analysisRunId": RUN, "meetingId": MEETING, "sessionId": SESSION,
        "transcript": text,
        "transcriptSha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    source.update(source_change or {})
    reopened = copy.deepcopy(result)
    reopened.update(reopened_change or {})
    calls = []

    def http(**kwargs):
        calls.append(kwargs)
        return 200, source if len(calls) == 1 else reopened

    monkeypatch.setattr(helper, "http_json", http)
    evidence = helper.reopen_evidence(
        base_url=helper.DEFAULT_BASE_URL, token="synthetic-not-a-token",
        meeting_id=MEETING, canonical_session_id=SESSION, result=result,
        timeout_seconds=1, statuses={},
    )
    assert calls[0]["path"].endswith(f"/results/{RUN}/transcript")
    assert calls[1]["path"].endswith("/intelligence/result")
    assert all(x["method"] == "GET" for x in calls)
    assert text not in json.dumps(evidence)
    return evidence


def test_same_persisted_result_and_exact_canonical_source(monkeypatch, result):
    evidence = readback(monkeypatch, result)
    assert evidence["sameResultReopened"] is True
    assert evidence["canonicalSourceReadBackProven"] is True
    assert evidence["browserCitationInteractionProven"] is False


@pytest.mark.parametrize("change", [
    {"meetingId": "wrong"}, {"sessionId": "wrong"}, {"analysisRunId": "wrong"},
    {"transcriptSha256": "0" * 64}, {"transcript": ""}, {"transcript": None},
])
def test_wrong_source_cannot_pass(monkeypatch, result, change):
    assert readback(monkeypatch, result, source_change=change)["canonicalSourceReadBackProven"] is False


@pytest.mark.parametrize("change", [
    {"analysisRunId": "other-run"}, {"summary": "Changed output"},
    {"decisions": []}, {"action_items": []}, {"persisted": False},
    {"citations": [{"source_index": 8}]},
])
def test_changed_result_does_not_pass_reopen(monkeypatch, result, change):
    assert readback(monkeypatch, result, reopened_change=change)["sameResultReopened"] is False


def test_gate_requires_all_product_checks():
    text = SCRIPT.read_text()
    for name in ("usableProductResult", "sameResultReopened", "canonicalSourceReadBackProven"):
        assert f'durable.get("{name}") is True' in text
