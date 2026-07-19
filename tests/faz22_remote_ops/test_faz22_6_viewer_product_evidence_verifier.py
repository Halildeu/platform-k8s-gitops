import copy
import base64
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
sys.path.insert(0, str(MODULE_PATH.parents[2]))
from tests.ai.signed_evidence_fixture import make_signed_evidence
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    REVOCATIONS_PAYLOAD_TYPE,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory

SPEC = importlib.util.spec_from_file_location("viewer_product_verifier", MODULE_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


RUN_ID = 123456
HEAD_SHA = "1" * 40
NOW = datetime(2026, 7, 14, 0, 10, 0, tzinfo=timezone.utc)
SOURCE_TYPES = tuple(sorted(VERIFIER.EXPECTED_CHILD_TYPES))
SOURCE_RUN_IDS = {name: 200000 + index for index, name in enumerate(SOURCE_TYPES, start=1)}
SOURCE_ARTIFACT_IDS = {name: 300000 + index for index, name in enumerate(SOURCE_TYPES, start=1)}
ACTIVATION_RUN_ID = 400001
AUTHORIZATION_ARTIFACT_ID = 500001
OWNER_COMMENT_ID = 900001
ADVISORY_COMMENT_ID = 900002
OWNER_COMMENT_BODY = "Owner authorizes the bounded attended VIEW_ONLY test pilot; legal clearance is not claimed."
ADVISORY_BASE_TIP_SHA = "0" * 40
ADVISORY_BASE_SHA = "9" * 40
ADVISORY_FIXTURE = make_signed_evidence(
    base_tip_sha=ADVISORY_BASE_TIP_SHA,
    base_sha=ADVISORY_BASE_SHA,
    head_sha=HEAD_SHA,
    reference_time=datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
)
ADVISORY_SCOPE_SHA256 = ADVISORY_FIXTURE.bindings["scope_sha256"]
ADVISORY_COMMENT_BODY = json.dumps(
    ADVISORY_FIXTURE.evidence,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)


def sha(char):
    return "sha256:" + char * 64


def binding():
    return {
        "sessionSha256": sha("1"),
        "tenantSha256": sha("2"),
        "operatorSha256": sha("3"),
        "deviceSha256": sha("4"),
    }


def child(evidence_type, kind, payload, observed_at="2026-07-14T00:05:00Z"):
    return {
        "schemaVersion": "faz22.6.viewOnlyViewerProductChildEvidence.v2",
        "evidenceType": evidence_type,
        "sourceRevision": HEAD_SHA,
        "observedAt": observed_at,
        "binding": binding(),
        "producer": {
            "kind": kind,
            "tool": f"scripts/evidence/{evidence_type}",
            "toolVersion": "v3-ack-drain" if evidence_type == "browser" else "v2",
        },
        "payload": payload,
    }


def case_binding(session_char):
    value = binding()
    value["sessionSha256"] = sha(session_char)
    return value


def negative_payload():
    cases = {
        name: {
            "observedAt": "2026-07-14T00:05:00Z",
            "binding": (
                {**case_binding("0"), "deviceSha256": sha("5")}
                if name == "wrongDevice" else case_binding("f")
            ),
            "result": "fail-closed",
            "outcome": VERIFIER.NEGATIVE_CASE_CONTRACT[name].outcome,
            "requestAccepted": False,
            "deliveryContinued": False,
            "httpStatus": VERIFIER.NEGATIVE_CASE_CONTRACT[name].http_status,
            "evidenceSha256": sha(format(index, "x")),
        }
        for index, name in enumerate(VERIFIER.NEGATIVE_CASES)
    }
    payload = {
        "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
        "cases": cases,
    }
    payload["suiteSha256"] = VERIFIER.digest_json(payload)
    return payload


def termination_payload():
    specs = {
        "localAbort": ("local-abort", 700),
        "killOrRevoke": ("kill-or-revoke", 500),
        "ttlExpiry": ("ttl-expiry", 900),
        "heartbeatLoss": ("heartbeat-loss", 30_000),
        "indicatorLoss": ("indicator-loss", 800),
    }
    session_chars = ("5", "6", "7", "8", "9")
    evidence_chars = ("a", "b", "c", "d", "e")
    audit_chars = ("0", "5", "6", "7", "8")
    cases = {}
    for index, (name, (trigger, latency)) in enumerate(specs.items()):
        cases[name] = {
            "observedAt": "2026-07-14T00:05:00Z",
            "binding": case_binding(session_chars[index]),
            "result": "terminated",
            "trigger": trigger,
            "deliveryTerminated": True,
            "terminationLatencyMillis": latency,
            "evidenceSha256": sha(evidence_chars[index]),
            "viewStopAuditSha256": sha(audit_chars[index]),
        }
    payload = {
        "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
        "cases": cases,
    }
    payload["suiteSha256"] = VERIFIER.digest_json(payload)
    return payload


def matrix_attestation_files(evidence_type, document):
    files = {}
    observation_lines = []
    audit_lines = []
    payload = document["payload"]
    termination_ordinals = {name: index for index, name in enumerate(VERIFIER.TERMINATION_CASES)}
    case_names = VERIFIER.NEGATIVE_CASES if evidence_type == "negative" else VERIFIER.TERMINATION_CASES
    for ordinal, case_name in enumerate(case_names):
        case = payload["cases"][case_name]
        support_common = {
            "caseName": case_name,
            "sourceRevision": document["sourceRevision"],
            "observedAt": case["observedAt"],
            "binding": case["binding"],
        }
        common = {
            "schemaVersion": f"faz22.6.viewOnlyViewer{evidence_type.title()}CaseAttestation.v1",
            **support_common,
            "authorizationSha256": payload["authorizationSha256"],
        }
        if evidence_type == "negative":
            contract = VERIFIER.NEGATIVE_CASE_CONTRACT[case_name]
            body_raw = f"redacted-product-response:{case_name}".encode()
            viewer_rejection_expected = case_name not in {
                "wrongDevice", "expired", "replayed", "disconnectedViewer",
            }
            request = {
                "method": contract.method,
                "targetClass": contract.target_class,
                "credentialClass": contract.credential_class,
                "pathTemplate": contract.path_template,
                "bodySha256": (
                    None if contract.method == "GET"
                    else VERIFIER.digest_bytes(
                        b'{"deviceId":"different","sessionId":"attempted"}'
                        if case_name == "wrongDevice" else b""
                    )
                ),
                "startedAt": (
                    "2026-07-14T00:01:00Z" if case_name == "disconnectedViewer"
                    else "2026-07-14T00:04:56Z"
                ),
                "completedAt": (
                    "2026-07-14T00:04:57Z" if case_name == "disconnectedViewer"
                    else "2026-07-14T00:04:57Z"
                ),
                "subjectSha256": (
                    None if case_name == "noAuth"
                    else sha("6") if case_name in {"wrongRole", "wrongTenant"}
                    else binding()["operatorSha256"]
                ),
                "tenantSha256": (
                    None if case_name == "noAuth"
                    else sha("7") if case_name == "wrongTenant"
                    else binding()["tenantSha256"]
                ),
                "rolePresent": case_name not in {"noAuth", "wrongRole"},
            }
            snapshot = {
                "schemaVersion": "faz22.6.viewOnlyViewerNegativeRuntimeSnapshot.v1",
                **support_common,
                "evidenceSource": {
                    "wrongDevice": "operator-session-open-http-probe",
                    "expired": "agent-error-ledger-and-http-probe",
                    "replayed": "agent-error-ledger-and-http-probe",
                }.get(case_name, "viewer-http-and-metric-probe"),
                "request": request,
                "response": {
                    "httpStatus": case["httpStatus"],
                    "bodyClass": (
                        "agent-deny-redacted"
                        if case_name in {"expired", "replayed"}
                        else "stream-content-digested-no-persistence"
                        if case_name == "disconnectedViewer"
                        else "empty-or-opaque"
                    ),
                    "bodyLength": len(body_raw),
                    "bodySha256": VERIFIER.digest_bytes(body_raw),
                    "screenContentPersisted": False,
                    "artifactRepresentation": "hash-and-length-only",
                },
                "delivery": {
                    "framesBefore": 100 + ordinal,
                    "framesAfter": 100 + ordinal,
                    "streamClosed": True,
                    "viewerRejectedBefore": 300 + ordinal,
                    "viewerRejectedAfter": 301 + ordinal if viewer_rejection_expected else 300 + ordinal,
                    "metricsBeforeObservedAt": (
                        "2026-07-14T00:04:58Z" if case_name == "disconnectedViewer"
                        else "2026-07-14T00:04:55Z"
                    ),
                    "metricsAfterObservedAt": "2026-07-14T00:04:59Z",
                },
                "agentDeny": {
                    "required": case_name in {"expired", "replayed"},
                    "observed": case_name in {"expired", "replayed"},
                    "code": {
                        "expired": "operation-dispatch-failed:permit-invalid",
                        "replayed": "operation-dispatch-failed:seq-replay",
                    }.get(case_name),
                },
            }
            snapshot_raw = canonical_jsonl_line(snapshot)
            attestation = {
                **common,
                "runtimeSnapshotSha256": VERIFIER.digest_bytes(snapshot_raw),
                "request": request,
                "result": {
                    "outcome": case["outcome"],
                    "requestAccepted": False,
                    "deliveryContinued": False,
                    "httpStatus": case["httpStatus"],
                },
            }
        else:
            started = 1_752_451_500_000 + termination_ordinals[case_name] * 10_000
            product_signals = {
                "viewerClosed": True,
                "brokerSessionTerminal": True,
                "agentEventObserved": True,
                "viewStopAuditVerified": True,
                **({
                    "endpointUserInitiated": True,
                    "consentLeaseRevoked": True,
                } if case_name == "localAbort" else {}),
            }
            snapshot = {
                "schemaVersion": "faz22.6.viewOnlyViewerTerminationRuntimeSnapshot.v1",
                **support_common,
                "trigger": case["trigger"],
                "triggeredAtEpochMillis": started,
                "deliveryEndedAtEpochMillis": started + case["terminationLatencyMillis"],
                "counters": {
                    "viewerEndedBefore": ordinal,
                    "viewerEndedAfter": ordinal + 1,
                    "globalFramesSentAtEnd": 200 + ordinal,
                    "globalFramesSentAfterObservationWindow": 200 + ordinal,
                    "sessionFramesDeliveredAtEnd": 100 + ordinal,
                    "observationWindowMillis": 3000,
                },
                "terminal": product_signals,
            }
            audit = {
                "schemaVersion": "faz22.6.viewOnlyViewerMatrixAuditRecord.v1",
                **support_common,
                "eventType": "VIEW_STOP",
                "outcome": True,
                "chainVerified": True,
                "chainSha256": VERIFIER.digest_bytes(f"termination:{case_name}:chain".encode()),
                "chainCheckedCount": ordinal + 1,
                "framesDelivered": 100 + ordinal,
                "verificationSource": "tenant-audit-chain-builder",
            }
            snapshot_raw = canonical_jsonl_line(snapshot)
            audit_raw = canonical_jsonl_line(audit)
            case["viewStopAuditSha256"] = VERIFIER.digest_bytes(audit_raw)
            attestation = {
                **common,
                "runtimeSnapshotSha256": VERIFIER.digest_bytes(snapshot_raw),
                "trigger": case["trigger"],
                "triggeredAtEpochMillis": started,
                "deliveryEndedAtEpochMillis": started + case["terminationLatencyMillis"],
                "result": {"deliveryTerminated": True},
                "viewStopAuditSha256": case["viewStopAuditSha256"],
                "productSignals": product_signals,
            }
        raw = encode_json(attestation)
        case["evidenceSha256"] = VERIFIER.digest_bytes(raw)
        files[f"attestations/{evidence_type}/{case_name}.json"] = raw
        observation_lines.append(snapshot_raw)
        if evidence_type == "termination":
            audit_lines.append(audit_raw)
    files[f"observations/{evidence_type}.jsonl"] = b"".join(observation_lines)
    if evidence_type == "termination":
        files["audit/termination.jsonl"] = b"".join(audit_lines)
    payload["suiteSha256"] = VERIFIER.digest_json({
        "authorizationSha256": payload["authorizationSha256"],
        "cases": payload["cases"],
    })
    return files


def child_documents():
    states = {"captured": 105, "brokerReceived": 105, "viewerDelivered": 100, "viewerRendered": 100}
    documents = {
        "browser": child(
            "browser",
            "browser-harness",
            {
                "pilotStartedAt": "2026-07-14T00:01:00Z",
                "pilotEndedAt": "2026-07-14T00:06:00Z",
                "ackDrainCompleted": True,
                "ackDrainCutoffAt": "2026-07-14T00:06:00Z",
                "ackDrainNonceSha256": sha("a"),
                "ackDrainClosureKind": "none",
                "imageElementRendered": True,
                "pixelCheckPassed": True,
                "inputChannelControlCount": 0,
                "dlpMaskRectBps": "7500,7500,2500,2500",
                "dlpMaskPixelCheckPassed": True,
                "activeIndicatorPixelCheckPassed": True,
                "maskedFrameSha256": sha("8"),
                "renderAckAttemptedCount": 100,
                "renderAckAcceptedCount": 100,
                "renderAckRejectedCount": 0,
                "renderAckPendingCount": 0,
                "consoleErrorCount": 0,
                "screenshotSha256": sha("5"),
                "firstFrameAgeMillis": 900,
                "steadyFrameAgeMillis": [200 + (index % 10) * 50 for index in range(100)],
                "consentEvidenceSha256": sha("0"),
                "meta": {
                    "authentication": "keycloak-authorization-code-pkce",
                    "recording": False,
                    "attended": True,
                    "capability": "VIEW_ONLY",
                    "viewerIdSha256": sha("6"),
                },
            },
        ),
        "broker": child(
            "broker",
            "prometheus-query",
            {
                "states": states,
                "framesSentMetricDelta": 100,
                "renderAckAcceptedMetricDelta": 100,
                "renderAckRejectedMetricDelta": 2,
                "reconnectCount": 0,
                "backpressureMode": "latest-wins-single-slot",
                "maxPendingFrames": 1,
                "metricsSnapshotSha256": sha("7"),
                "inputChannels": {
                    "keyboard": False,
                    "mouse": False,
                    "clipboard": False,
                    "fileTransfer": False,
                    "credentialEntry": False,
                    "shell": False,
                    "portForward": False,
                    "hiddenControl": False,
                },
                "dlp": {
                    "deliveredPathProven": True,
                    "rawContentIncluded": False,
                    "maskedFrameSha256": sha("8"),
                },
                "persistence": {
                    "recordingMode": "disabled",
                    "contentPersisted": False,
                    "contentStorageWrites": 0,
                },
            },
        ),
        "audit": child(
            "audit",
            "audit-verifier",
            {
                "viewStartPresent": True,
                "viewStartCommittedBeforeFirstDelivered": True,
                "viewStopPresent": True,
                "hashChainVerified": True,
                "framesDelivered": 100,
                "framesRenderAcknowledged": 100,
                "snapshotSha256": sha("9"),
            },
        ),
        "d30": child(
            "d30",
            "d30-verifier",
            {
                "images": [
                    {"component": "backend", "desiredDigest": sha("a"), "liveImageIdDigest": sha("a")},
                    {"component": "web", "desiredDigest": sha("b"), "liveImageIdDigest": sha("b")},
                ],
                "snapshotSha256": sha("c"),
            },
        ),
        "negative": child(
            "negative",
            "negative-harness",
            negative_payload(),
        ),
        "termination": child(
            "termination",
            "termination-harness",
            termination_payload(),
        ),
        "operator": child(
            "operator",
            "protected-authorization",
            {
                "onePersonRoster": True,
                "pilotDeviceConsented": True,
                "exposureApproved": True,
                "protectedEnvironment": "faz22-view-only-pilot",
                "activationRunId": ACTIVATION_RUN_ID,
                "activationRunAttempt": 1,
                "activationHeadSha": HEAD_SHA,
                "activationActorLogin": "workflow-operator",
                "activationCreatedAt": "2026-07-14T00:00:00Z",
                "activationRunStartedAt": "2026-07-14T00:00:00Z",
                "activationUpdatedAt": "2026-07-14T00:00:30Z",
                "authorizationArtifactId": AUTHORIZATION_ARTIFACT_ID,
                "authorizationArtifactDigest": VERIFIER.digest_bytes(activation_archive()),
                "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
                "authorizationCarrierBase64": base64.b64encode(
                    authorization_bytes()
                ).decode("ascii"),
                "advisoryCommentCarrierBase64": base64.b64encode(
                    encode_json(advisory_comment_document())
                ).decode("ascii"),
                "ownerDirectiveCarrierBase64": base64.b64encode(
                    encode_json(owner_comment_document())
                ).decode("ascii"),
                "authorizationSchemaVersion": VERIFIER.AUTHORIZATION_SCHEMA,
                "ownerPolicySha256": VERIFIER.digest_json(owner_policy_fixture()),
                "ownerDirectiveSha256": VERIFIER.digest_bytes(OWNER_COMMENT_BODY.encode()),
                "aiAdvisorySha256": VERIFIER.digest_bytes(ADVISORY_COMMENT_BODY.encode()),
                "legalTrackStatus": "tracked_pending",
                "legalClearanceClaimed": False,
            },
            observed_at="2026-07-14T00:00:30Z",
        ),
    }
    documents["browser"]["payload"]["consentEvidenceSha256"] = VERIFIER.digest_bytes(
        consent_bytes(documents["browser"])
    )
    matrix_attestation_files("negative", documents["negative"])
    matrix_attestation_files("termination", documents["termination"])
    return documents


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def canonical_jsonl_line(value):
    return VERIFIER.canonical_bytes(value) + b"\n"


def mutate_jsonl_case(raw, case_name, mutator):
    found = False
    output = []
    for line in raw.splitlines():
        value = json.loads(line)
        if value["caseName"] == case_name:
            mutator(value)
            found = True
        output.append(canonical_jsonl_line(value))
    if not found:
        raise AssertionError(f"fixture case not found: {case_name}")
    return b"".join(output)


def rewrite_negative_request(document, files, case_name, mutator):
    observations_path = "observations/negative.jsonl"
    snapshot = None

    def mutate_snapshot(value):
        nonlocal snapshot
        mutator(value["request"])
        snapshot = value

    files[observations_path] = mutate_jsonl_case(
        files[observations_path], case_name, mutate_snapshot,
    )
    assert snapshot is not None
    snapshot_raw = canonical_jsonl_line(snapshot)
    attestation_path = f"attestations/negative/{case_name}.json"
    attestation = json.loads(files[attestation_path])
    attestation["request"] = copy.deepcopy(snapshot["request"])
    attestation["runtimeSnapshotSha256"] = VERIFIER.digest_bytes(snapshot_raw)
    files[attestation_path] = encode_json(attestation)
    case = document["payload"]["cases"][case_name]
    case["evidenceSha256"] = VERIFIER.digest_bytes(files[attestation_path])
    document["payload"]["suiteSha256"] = VERIFIER.digest_json({
        "authorizationSha256": document["payload"]["authorizationSha256"],
        "cases": document["payload"]["cases"],
    })
    return encode_json(document)


def encode_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    return output.getvalue()


def owner_policy_fixture():
    return {
        "schemaVersion": "faz22.6-view-only-pilot-owner-policy-v2",
        "status": "tracked_pending",
        "ownerDirective": {
            "commentId": OWNER_COMMENT_ID,
            "ref": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373#issuecomment-{OWNER_COMMENT_ID}",
            "bodySha256": VERIFIER.digest_bytes(OWNER_COMMENT_BODY.encode()),
            "authorLogin": "Halildeu",
            "authorAssociation": "OWNER",
        },
        "aiAdvisory": {
            "commentId": None,
            "ref": None,
            "bodySha256": None,
            "authorLogin": None,
            "authorAssociation": None,
            "advisoryOnly": True,
            "consensusVerdict": "PENDING",
            "providers": ["OpenAI/gpt-5.6-sol"],
            "provenanceClass": "signed-direct-codex-launch-attested-v3",
            "providerCryptographicAttestation": True,
            "evidenceBinding": {
                "baseTipSha": None,
                "baseSha": None,
                "headSha": None,
                "scopeSha256": None,
            },
            "maxAgeHours": 168,
        },
        "legalTracking": {
            "ref": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2374",
            "status": "tracked_pending",
            "clearanceClaimed": False,
            "dependencyAcknowledgedBy": "owner",
            "dependencyRationaleCode": "bounded-test-owner-risk-acceptance",
        },
        "scope": {
            "environment": "test",
            "mode": "attended-view-only",
            "recordingMode": "disabled",
            "screenContentPersisted": False,
            "pilotAutoConsent": False,
            "attendedConsentRequired": True,
            "visibleIndicatorRequired": True,
            "localAbortRequired": True,
            "maxViewers": 1,
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
        },
        "authorization": {
            "protectedEnvironment": "faz22-view-only-pilot",
            "requirePreventSelfReview": True,
            "maxTtlMinutes": 120,
            "killSwitchWorkflowRef": ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback",
            "revocationLedgerRef": "config/faz22-6-view-only-pilot-authorization-revocations.v1.json",
        },
        "lifecycle": {
            "validFrom": "2026-07-14T00:00:00Z",
            "validUntil": "2027-07-14T00:00:00Z",
        },
    }


def revocation_fixture():
    return {
        "schemaVersion": "faz22.6-view-only-pilot-authorization-revocations-v1",
        "revokedAuthorizationSha256": [],
    }


def authorization_document():
    return {
        "schemaVersion": VERIFIER.AUTHORIZATION_SCHEMA,
        "minimumAcceptedAuthorizationSchema": VERIFIER.AUTHORIZATION_SCHEMA,
        "environment": "faz22-view-only-pilot",
        "onePersonRoster": True,
        "operatorSha256": binding()["operatorSha256"],
        "consentingPilotDevice": True,
        "deviceSha256": binding()["deviceSha256"],
        "exposureApprovedByProtectedEnvironment": True,
        "protectedEnvironmentPreventSelfReview": True,
        "protectedEnvironmentReviewerCount": 1,
        "protectedEnvironmentReviewerSetSha256": VERIFIER.digest_json([
            {"type": "User", "id": 700001, "name": "security-reviewer"}
        ]),
        "ownerPolicySha256": VERIFIER.digest_json(owner_policy_fixture()),
        "ownerDirectiveRef": owner_policy_fixture()["ownerDirective"]["ref"],
        "ownerDirectiveSha256": VERIFIER.digest_bytes(OWNER_COMMENT_BODY.encode()),
        "aiAdvisoryOnly": True,
        "aiAdvisoryProvenanceClass": "signed-direct-codex-launch-attested-v3",
        "aiProviderCryptographicAttestation": True,
        "aiAdvisoryCommentId": ADVISORY_COMMENT_ID,
        "aiAdvisoryRef": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373#issuecomment-{ADVISORY_COMMENT_ID}",
        "aiAdvisorySha256": VERIFIER.digest_bytes(ADVISORY_COMMENT_BODY.encode()),
        "aiAdvisoryBaseTipSha": ADVISORY_BASE_TIP_SHA,
        "aiAdvisoryBaseSha": ADVISORY_BASE_SHA,
        "aiAdvisoryHeadSha": HEAD_SHA,
        "aiAdvisoryScopeSha256": ADVISORY_SCOPE_SHA256,
        "aiConsensusVerdict": "AGREE",
        "legalTrackingIssueRef": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2374",
        "legalTrackStatus": "tracked_pending",
        "legalClearanceClaimed": False,
        "legalDependencyAcknowledgedBy": "owner",
        "legalDependencyRationaleCode": "bounded-test-owner-risk-acceptance",
        "recordingMode": "disabled",
        "screenContentPersisted": False,
        "attendedConsentRequired": True,
        "pilotAutoConsent": False,
        "visibleIndicatorRequired": True,
        "localAbortRequired": True,
        "killSwitchWorkflowRef": ".github/workflows/apply-view-only-viewer-pilot-enable.yml?action=rollback",
        "revocationLedgerRef": "config/faz22-6-view-only-pilot-authorization-revocations.v1.json",
        "issuedAt": "2026-07-14T00:00:10Z",
        "expiresAt": "2026-07-14T00:20:00Z",
        "authorizationRunId": ACTIVATION_RUN_ID,
        "authorizationHeadSha": HEAD_SHA,
    }


def authorization_bytes():
    return VERIFIER.canonical_bytes(authorization_document()) + b"\n"


def advisory_comment_document(
    *,
    body=ADVISORY_COMMENT_BODY,
    created_at="2026-07-14T00:00:00Z",
    updated_at="2026-07-14T00:00:00Z",
):
    return {
        "id": ADVISORY_COMMENT_ID,
        "html_url": (
            f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373"
            f"#issuecomment-{ADVISORY_COMMENT_ID}"
        ),
        "issue_url": (
            f"https://api.github.com/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373"
        ),
        "author_association": "OWNER",
        "user": {"login": "Halildeu"},
        "body": body,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def owner_comment_document(
    *,
    body=OWNER_COMMENT_BODY,
    created_at="2026-07-13T00:00:00Z",
    updated_at="2026-07-13T00:00:00Z",
):
    return {
        "id": OWNER_COMMENT_ID,
        "html_url": owner_policy_fixture()["ownerDirective"]["ref"],
        "issue_url": (
            f"https://api.github.com/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373"
        ),
        "author_association": "OWNER",
        "user": {"login": "Halildeu"},
        "body": body,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def activation_archive(raw_authorization=None, advisory_comment=None, owner_comment=None):
    files = {
        "advisory-comment.json": encode_json(
            advisory_comment or advisory_comment_document()
        ),
        "owner-comment.json": encode_json(owner_comment or owner_comment_document()),
        "protected-authorization.json": raw_authorization or authorization_bytes(),
    }
    sums = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  {name}\n" for name, raw in files.items()
    ).encode("ascii")
    return encode_zip({**files, "SHA256SUMS": sums})


def consent_bytes(document):
    consent = {
        "schemaVersion": "faz22.6.viewOnlyViewerConsentEvidence.v1",
        "sourceRevision": document["sourceRevision"],
        "observedAt": document["observedAt"],
        "binding": document["binding"],
        "consentPromptSent": True,
        "decision": "granted",
        "decisionSignal": "CONSENT_GRANTED",
        "decisionProtocol": "remote-bridge-consent-signal-v1",
        "decisionSource": "device-key-attested-endpoint-outbound-channel",
        "sourceAttestationSha256": VERIFIER.digest_bytes(consent_source_bytes(document)),
        "pilotAutoConsent": False,
        "recordingMode": "disabled",
        "screenContentPersisted": False,
    }
    return VERIFIER.canonical_bytes(consent) + b"\n"


def consent_source_bytes(document):
    source = {
        "schemaVersion": "faz22.6.viewOnlyViewerConsentSourceAttestation.v1",
        "sourceRevision": document["sourceRevision"],
        "observedAt": document["observedAt"],
        "binding": document["binding"],
        "smokeSummarySha256": sha("a"),
        "openSessionResponseSha256": sha("b"),
        "endpointConsentLogLineSha256": sha("c"),
        "openSessionConsentPromptSent": True,
        "brokerHelloVerified": True,
        "brokerConsentGranted": True,
        "endpointConsentGranted": True,
        "transportPushed": True,
    }
    return VERIFIER.canonical_bytes(source) + b"\n"


def source_archive(name, raw):
    files = {f"evidence/{name}.json": raw}
    if name == "browser":
        try:
            document = json.loads(raw)
            files["evidence/consent.json"] = consent_bytes(document)
            files["evidence/consent-source.json"] = consent_source_bytes(document)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    if name in {"negative", "termination"}:
        document = json.loads(raw)
        files.update(matrix_attestation_files(name, document))
        regenerated = encode_json(document)
        if regenerated != raw:
            raise AssertionError(f"{name} fixture attestation digest drift")
    return encode_zip(files)


def source_entry(name, raw):
    run_id = SOURCE_RUN_IDS[name]
    archive = source_archive(name, raw)
    workflow_path, _ = VERIFIER.EXPECTED_SOURCE_WORKFLOWS[name]
    return {
        "repository": VERIFIER.EXPECTED_REPOSITORY,
        "workflowPath": workflow_path,
        "runId": run_id,
        "runAttempt": 1,
        "headSha": HEAD_SHA,
        "artifactId": SOURCE_ARTIFACT_IDS[name],
        "artifactName": f"faz22-6-view-only-viewer-{name}-evidence-{run_id}",
        "artifactDigest": VERIFIER.digest_bytes(archive),
        "artifactFile": f"evidence/{name}.json",
    }


def build_archive(children=None, mutate_root=None, extra_files=None, zip_entry=None):
    children = copy.deepcopy(children or child_documents())
    child_bytes = {f"evidence/{name}.json": encode_json(value) for name, value in children.items()}
    root = {
        "schemaVersion": VERIFIER.EVIDENCE_SCHEMA,
        "environment": "test",
        "producer": {
            "repository": VERIFIER.EXPECTED_REPOSITORY,
            "workflowPath": VERIFIER.EXPECTED_WORKFLOW_PATH,
            "runId": RUN_ID,
            "runAttempt": 1,
            "headSha": HEAD_SHA,
        },
        "generatedAt": "2026-07-14T00:06:01Z",
        "pilot": {"startedAt": "2026-07-14T00:01:00Z", "endedAt": "2026-07-14T00:06:00Z"},
        "binding": binding(),
        "scope": {
            "mode": "VIEW_ONLY",
            "recordingMode": "disabled",
            "attended": True,
            "maxViewers": 1,
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
            "legalAcceptance": False,
        },
        "evidence": [
            {
                "type": name,
                "path": path,
                "sha256": VERIFIER.digest_bytes(raw),
                "source": source_entry(name, raw),
            }
            for path, raw in sorted(child_bytes.items())
            for name in [Path(path).stem]
        ],
    }
    if mutate_root:
        mutate_root(root)
    files = {"viewer-product-evidence.json": encode_json(root), **child_bytes, **(extra_files or {})}
    if zip_entry:
        files[zip_entry[0]] = zip_entry[1]
    return encode_zip(files)


class FakeClient:
    def __init__(self, archive=None):
        self.archive = archive or build_archive()
        with zipfile.ZipFile(io.BytesIO(self.archive)) as final_archive:
            self.source_children = {
                name: final_archive.read(f"evidence/{name}.json")
                for name in SOURCE_TYPES
                if f"evidence/{name}.json" in final_archive.namelist()
            }
        self.source_archives = {
            name: source_archive(name, raw) for name, raw in self.source_children.items()
        }
        self.activation_archive = activation_archive()
        self.run_missing = False
        self.artifact_missing = False
        self.artifact_digest = VERIFIER.digest_bytes(self.archive)
        self.run_conclusion = "success"
        self.run_updated_at = "2026-07-14T00:07:00Z"
        self.run_started_at = "2026-07-14T00:06:01Z"
        self.source_run_started_at = {name: "2026-07-14T00:00:00Z" for name in SOURCE_TYPES}
        self.source_run_updated_at = {name: "2026-07-14T00:06:00Z" for name in SOURCE_TYPES}
        self.artifact_expired = False
        self.source_run_missing = None
        self.activation_created_at = "2026-07-14T00:00:00Z"
        self.activation_updated_at = "2026-07-14T00:00:30Z"
        self.owner_comment_body = OWNER_COMMENT_BODY
        self.advisory_comment_body = ADVISORY_COMMENT_BODY
        self.advisory_comment_created_at = "2026-07-14T00:00:00Z"
        self.advisory_comment_updated_at = "2026-07-14T00:00:00Z"
        self.legal_issue_state = "open"
        self.environment_prevent_self_review = True
        self.environment_reviewers = [{
            "type": "User",
            "reviewer": {"id": 700001, "login": "security-reviewer"},
        }]

    def refresh_activation_archive(self):
        self.activation_archive = activation_archive(
            advisory_comment=advisory_comment_document(
                body=self.advisory_comment_body,
                created_at=self.advisory_comment_created_at,
                updated_at=self.advisory_comment_updated_at,
            )
        )

    def get_json(self, path):
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{ACTIVATION_RUN_ID}":
            return {
                "id": ACTIVATION_RUN_ID,
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": HEAD_SHA,
                "run_attempt": 1,
                "name": VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_NAME,
                "path": VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_PATH,
                "actor": {"login": "workflow-operator"},
                "created_at": self.activation_created_at,
                "run_started_at": self.activation_created_at,
                "updated_at": self.activation_updated_at,
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{ACTIVATION_RUN_ID}/artifacts?per_page=100":
            return {
                "total_count": 1,
                "artifacts": [{
                    "id": AUTHORIZATION_ARTIFACT_ID,
                    "name": f"faz22-view-only-pilot-protected-authorization-{ACTIVATION_RUN_ID}",
                    "expired": False,
                    "digest": VERIFIER.digest_bytes(self.activation_archive),
                    "created_at": "2026-07-14T00:00:20Z",
                    "updated_at": "2026-07-14T00:00:20Z",
                    "workflow_run": {"id": ACTIVATION_RUN_ID, "head_sha": HEAD_SHA},
                }],
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{RUN_ID}":
            if self.run_missing:
                raise VERIFIER.EvidenceError("GitHub API run returned HTTP 404")
            return {
                "id": RUN_ID,
                "status": "completed",
                "conclusion": self.run_conclusion,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": HEAD_SHA,
                "run_attempt": 1,
                "name": VERIFIER.EXPECTED_WORKFLOW_NAME,
                "path": VERIFIER.EXPECTED_WORKFLOW_PATH,
                "run_started_at": self.run_started_at,
                "updated_at": self.run_updated_at,
            }
        for name in SOURCE_TYPES:
            run_id = SOURCE_RUN_IDS[name]
            artifact_id = SOURCE_ARTIFACT_IDS[name]
            workflow_path, workflow_name = VERIFIER.EXPECTED_SOURCE_WORKFLOWS[name]
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{run_id}":
                if self.source_run_missing == name:
                    raise VERIFIER.EvidenceError(f"{name} source run returned HTTP 404")
                return {
                    "id": run_id,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "head_sha": HEAD_SHA,
                    "run_attempt": 1,
                    "name": workflow_name,
                    "path": workflow_path,
                    "run_started_at": self.source_run_started_at[name],
                    "updated_at": self.source_run_updated_at[name],
                }
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100":
                archive = self.source_archives[name]
                return {
                    "total_count": 1,
                    "artifacts": [{
                        "id": artifact_id,
                        "name": f"faz22-6-view-only-viewer-{name}-evidence-{run_id}",
                        "expired": False,
                        "digest": VERIFIER.digest_bytes(archive),
                        "created_at": "2026-07-14T00:06:30Z",
                        "updated_at": "2026-07-14T00:06:30Z",
                        "workflow_run": {"id": run_id, "head_sha": HEAD_SHA},
                    }],
                }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{RUN_ID}/artifacts?per_page=100":
            artifacts = [] if self.artifact_missing else [{
                "id": 789,
                "name": f"faz22-6-view-only-viewer-product-evidence-{RUN_ID}",
                "expired": self.artifact_expired,
                "digest": self.artifact_digest,
                "created_at": "2026-07-14T00:06:30Z",
                "updated_at": "2026-07-14T00:06:30Z",
                "workflow_run": {"id": RUN_ID, "head_sha": HEAD_SHA},
            }]
            return {"total_count": len(artifacts), "artifacts": artifacts}
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/comments/{OWNER_COMMENT_ID}":
            return {
                "id": OWNER_COMMENT_ID,
                "html_url": owner_policy_fixture()["ownerDirective"]["ref"],
                "issue_url": f"https://api.github.com/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373",
                "author_association": "OWNER",
                "user": {"login": "Halildeu"},
                "body": self.owner_comment_body,
                "created_at": "2026-07-13T00:00:00Z",
                "updated_at": "2026-07-13T00:00:00Z",
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/comments/{ADVISORY_COMMENT_ID}":
            return {
                "id": ADVISORY_COMMENT_ID,
                "html_url": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373#issuecomment-{ADVISORY_COMMENT_ID}",
                "issue_url": f"https://api.github.com/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/2373",
                "author_association": "OWNER",
                "user": {"login": "Halildeu"},
                "body": self.advisory_comment_body,
                "created_at": self.advisory_comment_created_at,
                "updated_at": self.advisory_comment_updated_at,
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/issues/2374":
            return {
                "number": 2374,
                "state": self.legal_issue_state,
                "html_url": f"https://github.com/{VERIFIER.EXPECTED_REPOSITORY}/issues/2374",
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/environments/faz22-view-only-pilot":
            return {
                "name": "faz22-view-only-pilot",
                "protection_rules": [{
                    "type": "required_reviewers",
                    "prevent_self_review": self.environment_prevent_self_review,
                    "reviewers": self.environment_reviewers,
                }],
            }
        raise AssertionError(f"unexpected JSON API path: {path}")

    def get_bytes(self, path):
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{AUTHORIZATION_ARTIFACT_ID}/zip":
            return self.activation_archive
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/789/zip":
            return self.archive
        for name, artifact_id in SOURCE_ARTIFACT_IDS.items():
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{artifact_id}/zip":
                return self.source_archives[name]
        raise AssertionError(f"unexpected artifact API path: {path}")


class ViewerProductEvidenceVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_owner_policy_v2 = VERIFIER.OWNER_POLICY_V2
        self.original_owner_policy_history = VERIFIER.OWNER_POLICY_HISTORY
        self.original_revocation_ledger = VERIFIER.REVOCATION_LEDGER
        VERIFIER.OWNER_POLICY_V2 = Path(self.temp_dir.name) / "owner-policy.json"
        VERIFIER.OWNER_POLICY_HISTORY = Path(self.temp_dir.name) / "owner-policy-history"
        VERIFIER.OWNER_POLICY_HISTORY.mkdir()
        VERIFIER.REVOCATION_LEDGER = Path(self.temp_dir.name) / "revocations.json"
        VERIFIER.OWNER_POLICY_V2.write_bytes(encode_json(owner_policy_fixture()))
        VERIFIER.REVOCATION_LEDGER.write_bytes(encode_json(revocation_fixture()))

    def tearDown(self):
        VERIFIER.OWNER_POLICY_V2 = self.original_owner_policy_v2
        VERIFIER.OWNER_POLICY_HISTORY = self.original_owner_policy_history
        VERIFIER.REVOCATION_LEDGER = self.original_revocation_ledger
        self.temp_dir.cleanup()

    def verify(
        self, client=None, now=NOW,
        advisory_scope_bytes=ADVISORY_FIXTURE.scope_bytes,
        cross_ai_revocations=None,
        authority_repo_root=None,
        current_authority=None,
    ):
        authority = current_authority or ADVISORY_FIXTURE.authority
        return VERIFIER.verify_product_evidence(
            client or FakeClient(),
            VERIFIER.EXPECTED_REPOSITORY,
            RUN_ID,
            now=now,
            advisory_scope_bytes=advisory_scope_bytes,
            cross_ai_trust_root=authority.trust_root,
            cross_ai_revocations=(
                cross_ai_revocations
                or authority.revocations_envelope
            ),
            expected_cross_ai_trust_root_sha256=(
                authority.expected_trust_root_sha256
            ),
            codex_executable_policy=(
                authority.codex_executable_policy
            ),
            issuer_runtime_policy=(
                authority.issuer_runtime_policy
            ),
            authority_repo_root=authority_repo_root,
        )

    def client_for_policy(
        self, policy_value, *, legacy_v1=False, authorization_updates=None,
        advisory_comment=None,
    ):
        if not legacy_v1:
            VERIFIER.OWNER_POLICY_V2.write_bytes(encode_json(policy_value))
        authorization = authorization_document()
        authorization["ownerPolicySha256"] = VERIFIER.digest_json(policy_value)
        authorization["ownerDirectiveRef"] = policy_value["ownerDirective"]["ref"]
        authorization["ownerDirectiveSha256"] = policy_value["ownerDirective"]["bodySha256"]
        authorization["aiAdvisoryProvenanceClass"] = policy_value["aiAdvisory"]["provenanceClass"]
        if legacy_v1:
            for field in (
                "aiAdvisoryCommentId", "aiAdvisoryBaseTipSha",
                "aiAdvisoryBaseSha", "aiAdvisoryHeadSha",
                "aiAdvisoryScopeSha256",
            ):
                authorization.pop(field)
            authorization["aiAdvisoryRef"] = policy_value["aiAdvisory"]["ref"]
            authorization["aiAdvisorySha256"] = policy_value["aiAdvisory"]["bodySha256"]
            authorization["aiProviderCryptographicAttestation"] = False
        authorization.update(authorization_updates or {})
        raw_authorization = VERIFIER.canonical_bytes(authorization) + b"\n"
        protected_archive = activation_archive(
            raw_authorization, advisory_comment=advisory_comment
        )
        authorization_digest = VERIFIER.digest_bytes(raw_authorization)

        children = child_documents()
        operator = children["operator"]["payload"]
        operator.update({
            "authorizationArtifactDigest": VERIFIER.digest_bytes(protected_archive),
            "authorizationSha256": authorization_digest,
            "authorizationCarrierBase64": base64.b64encode(
                raw_authorization
            ).decode("ascii"),
            "advisoryCommentCarrierBase64": base64.b64encode(
                encode_json(advisory_comment or advisory_comment_document())
            ).decode("ascii"),
            "ownerDirectiveCarrierBase64": base64.b64encode(
                encode_json(owner_comment_document())
            ).decode("ascii"),
            "ownerPolicySha256": authorization["ownerPolicySha256"],
            "ownerDirectiveSha256": authorization["ownerDirectiveSha256"],
            "aiAdvisorySha256": authorization["aiAdvisorySha256"],
        })
        for evidence_type in ("negative", "termination"):
            payload = children[evidence_type]["payload"]
            payload["authorizationSha256"] = authorization_digest
            matrix_attestation_files(evidence_type, children[evidence_type])
        client = FakeClient(build_archive(children=children))
        client.activation_archive = protected_archive
        client.operator_payload = operator
        return client

    def validate_matrices(self, children):
        VERIFIER.validate_negative_and_termination(
            children["negative"]["payload"],
            children["termination"]["payload"],
            children["operator"]["payload"],
            binding(),
            datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 0, 20, tzinfo=timezone.utc),
            {
                "negative": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                "termination": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
            },
        )

    def test_valid_provenance_bound_artifact_passes_with_digest_marker(self):
        result = self.verify()
        self.assertEqual("pass", result["status"])
        self.assertEqual(100, result["computed"]["renderedFrames"])
        self.assertEqual(0.0, result["computed"]["renderLossRate"])
        self.assertIn(VERIFIER.MARKER, result["marker"])
        self.assertIn(f"run_id: {RUN_ID}", result["marker"])
        self.assertIn(f"artifact_digest: {result['artifactDigest']}", result["marker"])
        self.assertIn(f"evidence_root_sha256: {result['evidenceRootSha256']}", result["marker"])
        self.assertNotIn("sessionId", result["marker"])
        self.assertNotIn("deviceId", result["marker"])

    def test_runtime_advisory_binding_derives_scope_without_policy_mutation(self):
        with patch.object(
            VERIFIER,
            "derive_scope",
            return_value=(ADVISORY_FIXTURE.scope_bytes, 0, 0),
        ) as derive:
            result = self.verify(advisory_scope_bytes=None)
        self.assertEqual(result["status"], "pass")
        derive.assert_called_once_with(
            VERIFIER.ROOT,
            base_tip_sha=ADVISORY_BASE_TIP_SHA,
            base_sha=ADVISORY_BASE_SHA,
            head_sha=HEAD_SHA,
            max_scope_bytes=VERIFIER.MAX_SCOPE_BYTES,
            scan_secrets=True,
        )
        policy_value = json.loads(VERIFIER.OWNER_POLICY_V2.read_bytes())
        self.assertEqual(policy_value["status"], "tracked_pending")
        self.assertTrue(
            all(
                value is None
                for value in policy_value["aiAdvisory"]["evidenceBinding"].values()
            )
        )

    def test_post_pilot_source_attestation_is_allowed_before_producer(self):
        archive = build_archive(
            mutate_root=lambda root: root.update({"generatedAt": "2026-07-14T00:08:02Z"})
        )
        client = FakeClient(archive)
        client.source_run_started_at["broker"] = "2026-07-14T00:07:00Z"
        client.source_run_updated_at["broker"] = "2026-07-14T00:08:00Z"
        client.run_started_at = "2026-07-14T00:08:01Z"
        client.run_updated_at = "2026-07-14T00:09:00Z"
        self.assertEqual("pass", self.verify(client)["status"])

    def test_source_attestation_24h_and_producer_order_boundaries(self):
        observed = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)
        VERIFIER.validate_source_attestation_timing(
            observed,
            datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
            "broker",
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "attestation is stale"):
            VERIFIER.validate_source_attestation_timing(
                observed,
                datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 15, 0, 0, 2, tzinfo=timezone.utc),
                "broker",
            )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "before the producer"):
            VERIFIER.validate_source_attestation_timing(
                observed,
                datetime(2026, 7, 14, 1, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc),
                "broker",
            )

    def test_nonexistent_run_and_artifact_fail_closed(self):
        client = FakeClient()
        client.run_missing = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "404"):
            self.verify(client)
        client = FakeClient()
        client.artifact_missing = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exactly one"):
            self.verify(client)

    def test_failed_run_and_expired_artifact_fail_closed(self):
        client = FakeClient()
        client.run_conclusion = "failure"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "conclusion"):
            self.verify(client)
        client = FakeClient()
        client.artifact_expired = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "expired"):
            self.verify(client)

    def test_archive_digest_mismatch_fails_closed(self):
        client = FakeClient()
        client.artifact_digest = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "digest"):
            self.verify(client)

    def test_missing_or_tampered_source_artifact_fails_closed(self):
        client = FakeClient()
        client.source_run_missing = "browser"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "browser source run returned HTTP 404"):
            self.verify(client)

        client = FakeClient()
        client.source_archives["browser"] = source_archive("browser", b'{}\n')
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "source artifact digest"):
            self.verify(client)

    def test_duplicate_source_run_is_rejected(self):
        def duplicate(root):
            by_type = {entry["type"]: entry for entry in root["evidence"]}
            by_type["broker"]["source"]["runId"] = by_type["browser"]["source"]["runId"]

        with self.assertRaisesRegex(VERIFIER.EvidenceError, "distinct source run"):
            self.verify(FakeClient(build_archive(mutate_root=duplicate)))

    def test_zip_slip_and_unexpected_file_fail_closed(self):
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "unsafe entry"):
            self.verify(FakeClient(build_archive(zip_entry=("../escape.json", b"{}"))))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "file set mismatch"):
            self.verify(FakeClient(build_archive(extra_files={"claim.txt": b"pass"})))

    def test_unknown_root_field_is_rejected_by_strict_schema(self):
        archive = build_archive(mutate_root=lambda root: root.update({"callerClaim": "pass"}))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "Additional properties"):
            self.verify(FakeClient(archive))

    def test_pre_drain_browser_producer_is_rejected_even_with_fresh_revision(self):
        children = child_documents()
        children["browser"]["producer"]["toolVersion"] = "v2"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "v3-ack-drain"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_child_digest_tamper_fails_closed(self):
        archive = build_archive()
        with zipfile.ZipFile(io.BytesIO(archive)) as original:
            files = {info.filename: original.read(info) for info in original.infolist()}
        files["evidence/browser.json"] += b" "
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as changed:
            for name, raw in files.items():
                changed.writestr(name, raw)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "child digest mismatch"):
            self.verify(FakeClient(output.getvalue()))

    def test_cross_session_child_binding_fails_closed(self):
        children = child_documents()
        children["audit"]["binding"]["sessionSha256"] = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "same-session binding"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_activation_receipt_is_content_and_identity_bound(self):
        client = FakeClient()
        children = child_documents()
        children["operator"]["payload"]["authorizationCarrierBase64"] = (
            base64.b64encode(authorization_bytes() + b"tamper").decode("ascii")
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorization receipt digest"):
            self.verify(FakeClient(build_archive(children=children)))

        operator = child_documents()["operator"]["payload"]
        unauthorized_binding = binding()
        unauthorized_binding["operatorSha256"] = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorized operator binding"):
            VERIFIER.verify_activation_authorization(
                FakeClient(), operator, HEAD_SHA, unauthorized_binding,
                datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 0, 6, tzinfo=timezone.utc),
            )

    def test_revoked_authorization_fails_without_invalidating_other_receipts(self):
        client = FakeClient()
        revoked = revocation_fixture()
        revoked["revokedAuthorizationSha256"] = [VERIFIER.digest_bytes(authorization_bytes())]
        VERIFIER.REVOCATION_LEDGER.write_bytes(encode_json(revoked))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "has been revoked"):
            self.verify(client)

    def test_owner_advisory_legal_and_environment_controls_fail_closed(self):
        children = child_documents()
        tampered_owner = owner_comment_document(body=OWNER_COMMENT_BODY + " tampered")
        children["operator"]["payload"]["ownerDirectiveCarrierBase64"] = (
            base64.b64encode(encode_json(tampered_owner)).decode("ascii")
        )
        client = FakeClient(build_archive(children=children))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "owner directive body digest"):
            self.verify(client)

        edited_owner = owner_comment_document(
            updated_at="2026-07-13T00:00:01Z"
        )
        children = child_documents()
        children["operator"]["payload"]["ownerDirectiveCarrierBase64"] = (
            base64.b64encode(encode_json(edited_owner)).decode("ascii")
        )
        client = FakeClient(build_archive(children=children))
        with self.assertRaisesRegex(
            VERIFIER.EvidenceError, "owner directive immutable timestamp"
        ):
            self.verify(client)

        client = self.client_for_policy(
            owner_policy_fixture(),
            advisory_comment=advisory_comment_document(
                body=ADVISORY_COMMENT_BODY + " tampered"
            ),
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "AI advisory body digest"):
            self.verify(client)

        client = FakeClient()
        client.legal_issue_state = "closed"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "legal tracking state"):
            self.verify(client)

        client = FakeClient()
        client.environment_prevent_self_review = False
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "self-review prevention"):
            self.verify(client)

    def test_advisory_expected_bindings_edit_and_freshness_fail_closed(self):
        for authorization_field, evidence_key, bad_value in (
            ("aiAdvisoryBaseTipSha", "base_tip_sha", "1" * 40),
            ("aiAdvisoryBaseSha", "base_sha", "2" * 40),
            ("aiAdvisoryHeadSha", "head_sha", "3" * 40),
            ("aiAdvisoryScopeSha256", "scope_sha256", "4" * 64),
        ):
            with self.subTest(binding=evidence_key):
                policy_value = owner_policy_fixture()
                client = self.client_for_policy(
                    policy_value,
                    authorization_updates={authorization_field: bad_value},
                )
                with self.assertRaisesRegex(
                    VERIFIER.EvidenceError,
                    "activation/advisory head binding|canonical advisory scope digest|scope bytes differ|subject or prompt binding mismatch",
                ):
                    self.verify(client)

        VERIFIER.OWNER_POLICY_V2.write_bytes(encode_json(owner_policy_fixture()))
        edited = self.client_for_policy(
            owner_policy_fixture(),
            advisory_comment=advisory_comment_document(
                updated_at="2026-07-14T00:00:01Z"
            ),
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "edited or has invalid timestamps"):
            self.verify(edited)

        stale = self.client_for_policy(
            owner_policy_fixture(),
            advisory_comment=advisory_comment_document(
                created_at="2026-07-06T23:59:59Z",
                updated_at="2026-07-06T23:59:59Z",
            ),
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "comment is stale"):
            self.verify(stale)

    def test_current_revocations_can_refresh_after_pilot_review_reference(self):
        factory = FixtureFactory("v2")
        refreshed = factory.sign(
            REVOCATIONS_PAYLOAD_TYPE,
            {
                "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
                "revocationSetId": "20000000-0000-4000-8000-000000000002",
                "issuedAt": "2026-07-14T00:05:00Z",
                "nextUpdate": "2026-07-14T00:55:00Z",
                "entries": [],
            },
            factory.REVOCATION_KEY_ID,
        )
        self.assertEqual(
            "pass", self.verify(cross_ai_revocations=refreshed)["status"]
        )

    def test_retired_review_root_is_resolved_for_durable_product_evidence(self):
        rotated = SimpleNamespace(
            trust_root={},
            revocations_envelope={},
            expected_trust_root_sha256="sha256:" + ("f" * 64),
            codex_executable_policy={},
            issuer_runtime_policy={},
            observed_at=NOW,
        )
        with patch.object(
            VERIFIER,
            "load_authority_for_evidence",
            return_value=ADVISORY_FIXTURE.authority,
        ) as resolver, patch.object(
            VERIFIER,
            "validate_codex_advisory_evidence",
            wraps=VERIFIER.validate_codex_advisory_evidence,
        ) as advisory_verifier:
            result = self.verify(
                authority_repo_root=Path("/trusted/repo"),
                current_authority=rotated,
            )
        self.assertEqual("pass", result["status"])
        self.assertEqual(
            ADVISORY_FIXTURE.authority.expected_trust_root_sha256,
            resolver.call_args.kwargs["expected_trust_root_sha256"],
        )
        self.assertEqual(
            datetime(2026, 7, 13, 23, 51, tzinfo=timezone.utc),
            resolver.call_args.kwargs["evidence_reference_time"],
        )
        self.assertEqual(
            ADVISORY_FIXTURE.authority.observed_at,
            advisory_verifier.call_args.kwargs["authority_observed_at"],
        )

    def test_durable_advisory_carrier_does_not_refetch_live_comment(self):
        client = FakeClient()
        original = client.get_json

        def unavailable(path):
            if path.endswith(f"/issues/comments/{ADVISORY_COMMENT_ID}"):
                raise VERIFIER.EvidenceError("live advisory transport unavailable")
            return original(path)

        client.get_json = unavailable
        self.assertEqual("pass", self.verify(client)["status"])

    def test_empty_durable_advisory_carrier_does_not_fall_back_to_live_comment(self):
        children = child_documents()
        children["operator"]["payload"]["advisoryCommentCarrierBase64"] = (
            base64.b64encode(b"{                                                }\n").decode(
                "ascii"
            )
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "AI advisory URL"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_durable_owner_directive_carrier_does_not_refetch_live_comment(self):
        client = FakeClient()
        original = client.get_json

        def unavailable(path):
            if path.endswith(f"/issues/comments/{OWNER_COMMENT_ID}"):
                raise VERIFIER.EvidenceError("live owner transport unavailable")
            return original(path)

        client.get_json = unavailable
        self.assertEqual("pass", self.verify(client)["status"])

    def test_durable_authorization_carrier_does_not_refetch_activation_artifact(self):
        client = FakeClient()
        original_json = client.get_json
        original_bytes = client.get_bytes

        def unavailable_json(path):
            if f"/actions/runs/{ACTIVATION_RUN_ID}" in path:
                raise VERIFIER.EvidenceError("activation artifact transport unavailable")
            return original_json(path)

        def unavailable_bytes(path):
            if path.endswith(f"/actions/artifacts/{AUTHORIZATION_ARTIFACT_ID}/zip"):
                raise VERIFIER.EvidenceError("activation artifact transport unavailable")
            return original_bytes(path)

        client.get_json = unavailable_json
        client.get_bytes = unavailable_bytes
        self.assertEqual("pass", self.verify(client)["status"])

    def test_cli_resolves_carried_authority_without_loading_current_authority(self):
        output = Path(self.temp_dir.name) / "cli-result.json"
        args = SimpleNamespace(
            repository=VERIFIER.EXPECTED_REPOSITORY,
            run_id=RUN_ID,
            github_api_url="https://api.github.invalid",
            github_token_env="TEST_GITHUB_TOKEN",
            output=output,
            marker_out=None,
        )
        with patch.object(VERIFIER, "parse_args", return_value=args), patch.object(
            VERIFIER, "GitHubClient", return_value=object(),
        ), patch.object(
            VERIFIER,
            "verify_product_evidence",
            return_value={"status": "pass"},
        ) as verify:
            self.assertEqual(0, VERIFIER.main())
        self.assertEqual(VERIFIER.ROOT, verify.call_args.kwargs["authority_repo_root"])
        self.assertNotIn("cross_ai_trust_root", verify.call_args.kwargs)

    def test_v2_replay_resolves_content_addressed_policy_after_current_changes(self):
        archived_policy = owner_policy_fixture()
        client = self.client_for_policy(archived_policy)
        archived_digest = VERIFIER.digest_json(archived_policy).removeprefix("sha256:")
        (VERIFIER.OWNER_POLICY_HISTORY / f"{archived_digest}.json").write_bytes(
            encode_json(archived_policy)
        )
        replacement = copy.deepcopy(archived_policy)
        replacement["legalTracking"]["ref"] = (
            "https://github.com/Halildeu/platform-k8s-gitops/issues/9999"
        )
        VERIFIER.OWNER_POLICY_V2.write_bytes(encode_json(replacement))
        self.assertEqual("pass", self.verify(client)["status"])

    def test_preexisting_v2_operator_child_remains_schema_valid(self):
        operator_child = child_documents()["operator"]
        for field in (
            "activationActorLogin", "activationCreatedAt", "activationRunStartedAt",
            "activationUpdatedAt", "authorizationCarrierBase64",
            "advisoryCommentCarrierBase64", "ownerDirectiveCarrierBase64",
        ):
            operator_child["payload"].pop(field)
        VERIFIER.validate_schema(
            operator_child, VERIFIER.CHILD_SCHEMA, "preexisting v2 operator child"
        )

    def test_current_v2_operator_without_durable_carrier_fails_closed(self):
        operator = child_documents()["operator"]["payload"]
        for field in (
            "activationActorLogin", "activationCreatedAt", "activationRunStartedAt",
            "activationUpdatedAt", "authorizationCarrierBase64",
            "advisoryCommentCarrierBase64", "ownerDirectiveCarrierBase64",
        ):
            operator.pop(field)
        with self.assertRaisesRegex(
            VERIFIER.EvidenceError, "complete durable authorization carrier"
        ):
            VERIFIER.verify_activation_authorization(
                FakeClient(), operator, HEAD_SHA, binding(),
                datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 0, 6, tzinfo=timezone.utc),
            )

    def test_preexisting_v2_operator_child_uses_bounded_legacy_decoder(self):
        legacy_policy = json.loads(VERIFIER.OWNER_POLICY_V1.read_bytes())
        client = self.client_for_policy(legacy_policy, legacy_v1=True)
        operator = client.operator_payload
        raw_authorization = base64.b64decode(
            operator["authorizationCarrierBase64"], validate=True
        )
        legacy_files = {"protected-authorization.json": raw_authorization}
        sums = (
            f"{hashlib.sha256(raw_authorization).hexdigest()}  "
            "protected-authorization.json\n"
        ).encode("ascii")
        client.activation_archive = encode_zip({
            **legacy_files, "SHA256SUMS": sums,
        })
        operator["authorizationArtifactDigest"] = VERIFIER.digest_bytes(
            client.activation_archive
        )
        for field in (
            "activationActorLogin", "activationCreatedAt", "activationRunStartedAt",
            "activationUpdatedAt", "authorizationCarrierBase64",
            "advisoryCommentCarrierBase64", "ownerDirectiveCarrierBase64",
        ):
            operator.pop(field)
        expires = VERIFIER.verify_activation_authorization(
            client, operator, HEAD_SHA, binding(),
            datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 0, 6, tzinfo=timezone.utc),
            allow_legacy_v1=True,
        )
        self.assertEqual(
            datetime(2026, 7, 14, 0, 20, tzinfo=timezone.utc), expires,
        )

    def test_immutable_v1_is_rejected_for_current_product_but_allowed_for_explicit_forensics(self):
        legacy_policy = json.loads(VERIFIER.OWNER_POLICY_V1.read_bytes())
        self.assertEqual(
            VERIFIER.LEGACY_POLICY_CANONICAL_SHA256,
            VERIFIER.digest_json(legacy_policy),
        )
        client = self.client_for_policy(legacy_policy, legacy_v1=True)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "forbidden for current product"):
            self.verify(client)
        expires = VERIFIER.verify_activation_authorization(
            client, client.operator_payload, HEAD_SHA, binding(),
            datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 0, 6, tzinfo=timezone.utc),
            allow_legacy_v1=True,
        )
        self.assertEqual(
            datetime(2026, 7, 14, 0, 20, tzinfo=timezone.utc), expires,
        )

    def test_legacy_v1_forensics_rejects_authorization_at_migration_cutoff(self):
        legacy_policy = json.loads(VERIFIER.OWNER_POLICY_V1.read_bytes())
        client = self.client_for_policy(
            legacy_policy, legacy_v1=True,
            authorization_updates={
                "issuedAt": "2026-07-19T00:00:00Z",
                "expiresAt": "2026-07-19T00:20:00Z",
            },
        )
        client.operator_payload["activationCreatedAt"] = "2026-07-19T00:00:00Z"
        client.operator_payload["activationRunStartedAt"] = "2026-07-19T00:00:00Z"
        client.operator_payload["activationUpdatedAt"] = "2026-07-19T00:00:30Z"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "migration cutoff"):
            VERIFIER.verify_activation_authorization(
                client, client.operator_payload, HEAD_SHA, binding(),
                datetime(2026, 7, 19, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 19, 0, 6, tzinfo=timezone.utc),
                allow_legacy_v1=True,
            )

    def test_legacy_v1_forensics_rejects_backdated_receipt_from_post_cutoff_run(self):
        legacy_policy = json.loads(VERIFIER.OWNER_POLICY_V1.read_bytes())
        client = self.client_for_policy(legacy_policy, legacy_v1=True)
        client.operator_payload["activationCreatedAt"] = "2026-07-19T00:00:00Z"
        client.operator_payload["activationRunStartedAt"] = "2026-07-19T00:00:00Z"
        client.operator_payload["activationUpdatedAt"] = "2026-07-19T00:00:30Z"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "activation run started"):
            VERIFIER.verify_activation_authorization(
                client, client.operator_payload, HEAD_SHA, binding(),
                datetime(2026, 7, 19, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 19, 0, 6, tzinfo=timezone.utc),
                allow_legacy_v1=True,
            )

    def test_tampered_or_automatic_consent_evidence_fails_closed(self):
        base_archive = build_archive()
        client = FakeClient(base_archive)
        browser_raw = client.source_children["browser"]
        original_source = client.source_archives["browser"]
        with zipfile.ZipFile(io.BytesIO(original_source)) as archive:
            source_files = {info.filename: archive.read(info) for info in archive.infolist()}
        consent = json.loads(source_files["evidence/consent.json"])
        consent["pilotAutoConsent"] = True
        source_files["evidence/consent.json"] = VERIFIER.canonical_bytes(consent) + b"\n"
        tampered_source = encode_zip(source_files)

        with zipfile.ZipFile(io.BytesIO(base_archive)) as archive:
            product_files = {info.filename: archive.read(info) for info in archive.infolist()}
        root = json.loads(product_files["viewer-product-evidence.json"])
        browser_entry = next(entry for entry in root["evidence"] if entry["type"] == "browser")
        browser_entry["source"]["artifactDigest"] = VERIFIER.digest_bytes(tampered_source)
        product_files["viewer-product-evidence.json"] = encode_json(root)
        client = FakeClient(encode_zip(product_files))
        client.source_archives["browser"] = tampered_source
        self.assertEqual(browser_raw, client.source_children["browser"])
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "browser consent evidence digest"):
            self.verify(client)

        children = child_documents()
        consent = json.loads(consent_bytes(children["browser"]))
        consent["pilotAutoConsent"] = True
        consent_raw = VERIFIER.canonical_bytes(consent) + b"\n"
        children["browser"]["payload"]["consentEvidenceSha256"] = VERIFIER.digest_bytes(consent_raw)
        browser_raw = encode_json(children["browser"])
        semantic_source = encode_zip({
            "evidence/browser.json": browser_raw,
            "evidence/consent.json": consent_raw,
            "evidence/consent-source.json": consent_source_bytes(children["browser"]),
        })
        product_archive = build_archive(children=children)
        with zipfile.ZipFile(io.BytesIO(product_archive)) as archive:
            product_files = {info.filename: archive.read(info) for info in archive.infolist()}
        root = json.loads(product_files["viewer-product-evidence.json"])
        browser_entry = next(entry for entry in root["evidence"] if entry["type"] == "browser")
        browser_entry["source"]["artifactDigest"] = VERIFIER.digest_bytes(semantic_source)
        product_files["viewer-product-evidence.json"] = encode_json(root)
        client = FakeClient(encode_zip(product_files))
        client.source_archives["browser"] = semantic_source
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "consent pilotAutoConsent"):
            self.verify(client)

    def test_95_delivered_one_rendered_class_and_low_render_ratio_fail(self):
        children = child_documents()
        broker = children["broker"]["payload"]
        broker["states"] = {"captured": 200, "brokerReceived": 200, "viewerDelivered": 200, "viewerRendered": 100}
        broker["framesSentMetricDelta"] = 200
        children["audit"]["payload"]["framesDelivered"] = 200
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "loss-rate"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_short_or_stale_pilot_fails_closed(self):
        short = build_archive(
            mutate_root=lambda root: root["pilot"].update({"startedAt": "2026-07-14T00:05:00Z"})
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "pilot duration"):
            self.verify(FakeClient(short))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "stale"):
            self.verify(FakeClient(), now=datetime(2026, 7, 16, tzinfo=timezone.utc))

    def test_root_pilot_must_match_browser_measured_window(self):
        archive = build_archive(
            mutate_root=lambda root: root["pilot"].update({"startedAt": "2026-07-14T00:00:59Z"})
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "browser pilot start"):
            self.verify(FakeClient(archive))

    def test_d30_drift_and_duplicate_component_fail_closed(self):
        children = child_documents()
        children["d30"]["payload"]["images"][1]["component"] = "backend"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exactly one"):
            self.verify(FakeClient(build_archive(children=children)))
        children = child_documents()
        children["d30"]["payload"]["images"][0]["liveImageIdDigest"] = sha("f")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "desired digest"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_secret_or_raw_identifier_shape_fails_hygiene(self):
        children = child_documents()
        children["operator"]["payload"]["authorization"] = "Bearer abcdefghijklmnop"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "schema invalid"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_boolean_only_negative_claim_is_rejected(self):
        children = child_documents()
        children["negative"]["payload"]["cases"]["noAuth"] = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "schema invalid"):
            VERIFIER.validate_schema(children["negative"], VERIFIER.CHILD_SCHEMA, "negative child")

    def test_matrix_suite_digest_and_authorization_are_content_bound(self):
        children = child_documents()
        children["negative"]["payload"]["cases"]["noAuth"]["httpStatus"] = 403
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "negative suite digest"):
            self.validate_matrices(children)

        children = child_documents()
        children["termination"]["payload"]["authorizationSha256"] = sha("f")
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"],
            "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "protected authorization digest"):
            self.validate_matrices(children)

    def test_termination_cases_require_isolated_sessions_and_latency_slo(self):
        children = child_documents()
        negative = children["negative"]["payload"]
        for name, case in negative["cases"].items():
            if name != "wrongDevice":
                case["binding"]["sessionSha256"] = binding()["sessionSha256"]
        negative["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": negative["authorizationSha256"], "cases": negative["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "isolated protected session"):
            self.validate_matrices(children)

        children = child_documents()
        cases = children["termination"]["payload"]["cases"]
        cases["indicatorLoss"]["binding"]["sessionSha256"] = cases["localAbort"]["binding"]["sessionSha256"]
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": cases,
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "distinct isolated sessions"):
            self.validate_matrices(children)

        children = child_documents()
        children["termination"]["payload"]["cases"]["killOrRevoke"]["terminationLatencyMillis"] = 1001
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exceeded the 1000ms"):
            self.validate_matrices(children)

    def test_matrix_case_attestation_bytes_are_independently_digest_bound(self):
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        path = "attestations/negative/noAuth.json"
        files[path] += b" "
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "attestation digest"):
            VERIFIER.validate_matrix_source_attestations("negative", files, raw_child)

    def test_matrix_runtime_snapshot_and_audit_bytes_are_digest_bound(self):
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        files["observations/negative.jsonl"] = mutate_jsonl_case(
            files["observations/negative.jsonl"], "noAuth",
            lambda value: value["delivery"].update({"framesAfter": 101}),
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "runtime snapshot digest"):
            VERIFIER.validate_matrix_source_attestations("negative", files, raw_child)

        document = child_documents()["termination"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("termination", raw_child))
        files["audit/termination.jsonl"] = mutate_jsonl_case(
            files["audit/termination.jsonl"], "localAbort",
            lambda value: value.update({"chainCheckedCount": 99}),
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "audit record digest"):
            VERIFIER.validate_matrix_source_attestations("termination", files, raw_child)

    def test_matrix_required_jsonl_files_fail_closed_when_missing(self):
        for evidence_type, missing_path in (
            ("negative", "observations/negative.jsonl"),
            ("termination", "audit/termination.jsonl"),
        ):
            with self.subTest(evidence_type=evidence_type):
                document = child_documents()[evidence_type]
                raw_child = encode_json(document)
                files = VERIFIER.safe_archive_files(source_archive(evidence_type, raw_child))
                del files[missing_path]
                with self.assertRaisesRegex(
                    VERIFIER.EvidenceError,
                    f"required source artifact file is missing: {missing_path}",
                ):
                    VERIFIER.validate_matrix_source_attestations(
                        evidence_type, files, raw_child,
                    )

    def test_matrix_jsonl_rejects_noncanonical_bytes_and_order(self):
        record = {
            "caseName": "noAuth",
            "schemaVersion": "fixture.v1",
        }
        canonical = canonical_jsonl_line(record)
        variants = {
            "missing-newline": canonical.rstrip(b"\n"),
            "trailing-whitespace": canonical.rstrip(b"\n") + b" \n",
            "blank-line": canonical + b"\n",
            "utf8-bom": b"\xef\xbb\xbf" + canonical,
        }
        for label, raw in variants.items():
            with self.subTest(label=label), self.assertRaises(VERIFIER.EvidenceError):
                VERIFIER.load_canonical_matrix_jsonl(raw, label, ("noAuth",))

        raw = canonical_jsonl_line({"caseName": "wrongRole"}) + canonical_jsonl_line(record)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "case order mismatch"):
            VERIFIER.load_canonical_matrix_jsonl(raw, "reordered", ("noAuth", "wrongRole"))

    def test_matrix_observation_rejects_unknown_fields_after_digest_binding(self):
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        attestation = json.loads(files["attestations/negative/noAuth.json"])
        observations = VERIFIER.load_canonical_matrix_jsonl(
            files["observations/negative.jsonl"], "observations", VERIFIER.NEGATIVE_CASES,
        )
        snapshot, _ = observations["noAuth"]
        snapshot["unexpected"] = True
        snapshot_raw = canonical_jsonl_line(snapshot)
        attestation["runtimeSnapshotSha256"] = VERIFIER.digest_bytes(snapshot_raw)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "runtime snapshot field set mismatch"):
            VERIFIER.validate_matrix_supporting_evidence(
                "negative", "noAuth", attestation, snapshot, snapshot_raw,
            )

    def test_local_abort_must_also_prove_attended_consent_withdrawal(self):
        document = child_documents()["termination"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("termination", raw_child))
        path = "attestations/termination/localAbort.json"
        attestation = json.loads(files[path])
        del attestation["productSignals"]["consentLeaseRevoked"]
        files[path] = encode_json(attestation)
        document["payload"]["cases"]["localAbort"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        raw_child = encode_json(document)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "localAbort attested product signals"):
            VERIFIER.validate_matrix_source_attestations("termination", files, raw_child)

    def test_matrix_cases_must_fit_protected_authorization_expiry(self):
        children = child_documents()
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorized matrix window"):
            VERIFIER.validate_negative_and_termination(
                children["negative"]["payload"], children["termination"]["payload"],
                children["operator"]["payload"], binding(),
                datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 0, 4, 59, tzinfo=timezone.utc),
                {
                    "negative": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                    "termination": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                },
            )

    def test_matrix_collection_window_is_bounded_to_two_hours(self):
        children = child_documents()
        pilot_started = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)
        authorization_expires = datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc)

        def set_observed_at(value):
            for payload in (children["negative"]["payload"], children["termination"]["payload"]):
                for case in payload["cases"].values():
                    case["observedAt"] = value
                payload["suiteSha256"] = VERIFIER.digest_json({
                    "authorizationSha256": payload["authorizationSha256"],
                    "cases": payload["cases"],
                })

        set_observed_at("2026-07-14T01:30:00Z")
        observed = {
            "negative": datetime(2026, 7, 14, 1, 30, tzinfo=timezone.utc),
            "termination": datetime(2026, 7, 14, 1, 30, tzinfo=timezone.utc),
        }
        VERIFIER.validate_negative_and_termination(
            children["negative"]["payload"], children["termination"]["payload"],
            children["operator"]["payload"], binding(), pilot_started,
            authorization_expires, observed,
        )

        set_observed_at("2026-07-14T02:01:00Z")
        observed = {
            "negative": datetime(2026, 7, 14, 2, 1, tzinfo=timezone.utc),
            "termination": datetime(2026, 7, 14, 2, 1, tzinfo=timezone.utc),
        }
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorized matrix window"):
            VERIFIER.validate_negative_and_termination(
                children["negative"]["payload"], children["termination"]["payload"],
                children["operator"]["payload"], binding(), pilot_started,
                authorization_expires, observed,
            )

    def test_negative_case_name_cannot_be_relabelled_with_another_outcome(self):
        self.assertEqual("unauthorized", VERIFIER.NEGATIVE_CASE_CONTRACT["wrongRole"].outcome)
        children = child_documents()
        payload = children["negative"]["payload"]
        payload["cases"]["wrongRole"]["outcome"] = "not-found"
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "wrongRole outcome"):
            self.validate_matrices(children)

    def test_wrong_device_requires_distinct_device_and_attempted_session_bindings(self):
        for field, expected_error in (
            ("deviceSha256", "wrongDevice must use a different device"),
            ("sessionSha256", "wrongDevice must use a distinct attempted session"),
        ):
            with self.subTest(field=field):
                children = child_documents()
                payload = children["negative"]["payload"]
                payload["cases"]["wrongDevice"]["binding"][field] = binding()[field]
                payload["suiteSha256"] = VERIFIER.digest_json({
                    "authorizationSha256": payload["authorizationSha256"],
                    "cases": payload["cases"],
                })
                with self.assertRaisesRegex(VERIFIER.EvidenceError, expected_error):
                    self.validate_matrices(children)

    def test_negative_request_identity_route_body_and_window_are_fail_closed(self):
        mutations = (
            (
                "wrongTenant",
                lambda request: request.update(tenantSha256=binding()["tenantSha256"]),
                "wrongTenant must use a distinct request tenant",
            ),
            (
                "wrongDevice",
                lambda request: request.update(pathTemplate="/unrelated/not-found"),
                "wrongDevice request path template",
            ),
            (
                "wrongDevice",
                lambda request: request.update(bodySha256=VERIFIER.digest_bytes(b"")),
                "wrongDevice request body must be non-empty",
            ),
            (
                "noAuth",
                lambda request: request.update(completedAt="2026-07-14T00:05:01Z"),
                "request/metric window ordering",
            ),
        )
        for case_name, mutator, expected_error in mutations:
            with self.subTest(case_name=case_name, expected_error=expected_error):
                document = child_documents()["negative"]
                files = matrix_attestation_files("negative", document)
                raw_child = rewrite_negative_request(document, files, case_name, mutator)
                with self.assertRaisesRegex(VERIFIER.EvidenceError, expected_error):
                    VERIFIER.validate_matrix_source_attestations("negative", files, raw_child)

    def test_negative_case_must_use_the_real_product_channel_contract(self):
        # Wrong-role authentication must be 401, while signed-permit expiry is
        # exercised through the acceptance-only POST agent-permit channel.
        self.assertEqual(401, VERIFIER.NEGATIVE_CASE_CONTRACT["wrongRole"].http_status)
        self.assertEqual("POST", VERIFIER.NEGATIVE_CASE_CONTRACT["expired"].method)
        self.assertEqual("POST", VERIFIER.NEGATIVE_CASE_CONTRACT["wrongDevice"].method)
        self.assertEqual(
            "operator-session-open-channel",
            VERIFIER.NEGATIVE_CASE_CONTRACT["wrongDevice"].target_class,
        )
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))

        wrong_role_path = "attestations/negative/wrongRole.json"
        wrong_role = json.loads(files[wrong_role_path])
        wrong_role["result"]["httpStatus"] = 404
        files[wrong_role_path] = encode_json(wrong_role)
        document["payload"]["cases"]["wrongRole"]["httpStatus"] = 404
        document["payload"]["cases"]["wrongRole"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[wrong_role_path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        with self.assertRaisesRegex(
            VERIFIER.EvidenceError, "negative wrongRole runtime HTTP status mismatch",
        ):
            VERIFIER.validate_matrix_source_attestations(
                "negative", files, encode_json(document),
            )

        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        expired_path = "attestations/negative/expired.json"
        expired = json.loads(files[expired_path])
        expired["request"].update({
            "method": "GET",
            "targetClass": "viewer-product-channel",
        })
        files[expired_path] = encode_json(expired)
        document["payload"]["cases"]["expired"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[expired_path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        with self.assertRaisesRegex(
            VERIFIER.EvidenceError, "negative expired runtime request mismatch",
        ):
            VERIFIER.validate_matrix_source_attestations(
                "negative", files, encode_json(document),
            )


if __name__ == "__main__":
    unittest.main()
