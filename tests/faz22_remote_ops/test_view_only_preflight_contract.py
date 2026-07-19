from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = (
    "faz22-6-dsse-envelope-v1.schema.json",
    "faz22-6-view-only-checkpoint-lease-redeem-v1.schema.json",
    "faz22-6-view-only-checkpoint-lease-v1.schema.json",
    "faz22-6-view-only-external-checkpoint-create-v1.schema.json",
    "faz22-6-view-only-external-checkpoint-receipt-v1.schema.json",
    "faz22-6-view-only-live-preflight-attestation-v1.schema.json",
    "faz22-6-view-only-live-preflight-request-v1.schema.json",
    "faz22-6-view-only-preflight-error-v1.schema.json",
    "faz22-6-view-only-runtime-trust-root-v1.schema.json",
    "faz22-6-view-only-transaction-binding-handoff-v1.schema.json",
    "faz22-6-view-only-transaction-binding-request-v1.schema.json",
    "faz22-6-view-only-transaction-binding-v1.schema.json",
)
INTENT_REF = (
    "refs/tags/cross-ai-intent/30000000-0000-4000-8000-000000000001"
)
WORKFLOW_REF = (
    "Halildeu/platform-k8s-gitops/.github/workflows/"
    f"faz22-6-view-only-viewer-transaction.yml@{INTENT_REF}"
)
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
HEAD_SHA = "c" * 40


def load_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for name in SCHEMA_NAMES:
        value = json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
        schemas[value["$id"]] = value
    return schemas


SCHEMAS = load_schemas()
REGISTRY = Registry().with_resources(
    (schema_id, Resource.from_contents(schema))
    for schema_id, schema in SCHEMAS.items()
)


def validator(name: str) -> Draft202012Validator:
    schema = next(value for key, value in SCHEMAS.items() if key.endswith(name))
    return Draft202012Validator(
        schema,
        registry=REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def binding() -> dict:
    return {
        "repositoryId": 1211415632,
        "repository": "Halildeu/platform-k8s-gitops",
        "environment": "faz22-view-only-pilot",
        "deploymentClass": "reversible-test",
        "productSlice": "Halildeu/platform-k8s-gitops#2373",
        "intentRef": INTENT_REF,
        "intentBundleSha256": DIGEST,
        "transactionSessionSha256": DIGEST,
        "headSha": HEAD_SHA,
        "workflowPath": ".github/workflows/faz22-6-view-only-viewer-transaction.yml",
        "workflowRef": WORKFLOW_REF,
        "workflowBlobSha256": DIGEST,
        "dependencyLockSha256": DIGEST,
        "concurrencySha256": DIGEST,
        "authoritySetSha256": DIGEST,
        "runId": 123456789,
        "runAttempt": 1,
        "triggeringActorId": 186576227,
        "machineAuthorityPolicySha256": DIGEST,
        "artifactSetSha256": DIGEST,
        "rollbackPlanSha256": DIGEST,
        "postDeployVerifierSha256": DIGEST,
        "bootstrapCredentialSha256": DIGEST,
        "tenantIdSha256": DIGEST,
        "preflightPersonaIdentitySha256": OTHER_DIGEST,
        "endpointIdSha256": DIGEST,
        "operatorIdSha256": OTHER_DIGEST,
        "deviceHostnameSha256": DIGEST,
        "attendedConsentPolicySha256": DIGEST,
        "pilotOwnerPolicySha256": DIGEST,
        "maskPolicySha256": DIGEST,
        "runtimeImageDigest": DIGEST,
        "pilotSeconds": 300,
        "transactionScopeSha256": DIGEST,
        "runnerPolicySha256": DIGEST,
        "runnerAdmissionLeaseSha256": DIGEST,
    }


def preflight_request() -> dict:
    return {
        "schemaVersion": "faz22.6.viewOnlyLivePreflightRequest.v1",
        "requestId": "40000000-0000-4000-8000-000000000001",
        "idempotencyKeySha256": DIGEST,
        "bindingHandoffEnvelope": {
            "payloadType": "application/vnd.acik.faz22-6-view-only-transaction-binding-handoff.v1+json",
            "payload": "e30=",
            "signatures": [
                {
                    "keyid": "vault-transit://cross-ai/coordinator#v1",
                    "sig": "A" * 86 + "==",
                }
            ],
        },
        "requestedChecks": [
            "targetIdentity",
            "pkceAuthorizationCode",
            "tokenRefresh",
            "routeApi",
            "browserConsole",
            "replayIsolation",
            "clusterContext",
            "portsTunnels",
            "imageDigests",
            "policyMask",
            "runnerCapacity",
            "watchdogRollback",
        ],
    }


def check() -> dict:
    return {
        "checkVersion": "v1",
        "status": "PASS",
        "source": "attestor-runtime",
        "evidenceSha256": DIGEST,
        "observedAt": "2026-07-18T00:00:00Z",
        "expiresAt": "2026-07-18T00:05:00Z",
    }


def attestation() -> dict:
    return {
        "schemaVersion": "faz22.6.viewOnlyLivePreflightAttestation.v1",
        "receiptId": "50000000-0000-4000-8000-000000000001",
        "requestId": "40000000-0000-4000-8000-000000000001",
        "idempotencyKeySha256": DIGEST,
        "requestSha256": DIGEST,
        "bindingHandoffEnvelopeSha256": DIGEST,
        "bindingSha256": DIGEST,
        "transactionIdSha256": DIGEST,
        "binding": binding(),
        "caller": {
            "profile": "preflight",
            "issuer": "https://token.actions.githubusercontent.com",
            "audience": "faz22-view-only-preflight",
            "subject": f"repo:Halildeu/platform-k8s-gitops:ref:{INTENT_REF}",
            "repository": "Halildeu/platform-k8s-gitops",
            "repositoryId": "1211415632",
            "workflowRef": WORKFLOW_REF,
            "ref": INTENT_REF,
            "headSha": HEAD_SHA,
            "runId": 123456789,
            "runAttempt": 1,
            "runnerEnvironment": "github-hosted",
            "tokenIssuedAt": "2026-07-18T00:00:00Z",
            "tokenExpiresAt": "2026-07-18T00:05:00Z",
            "tokenJtiSha256": DIGEST,
        },
        "persona": {
            "identitySha256": OTHER_DIGEST,
            "tenantIdSha256": DIGEST,
            "expiresAt": "2026-07-18T02:00:00Z",
            "preprovisioned": True,
            "adminCredentialUsed": False,
            "userConfigurationMutationCount": 0,
        },
        "checks": {name: check() for name in preflight_request()["requestedChecks"]},
        "mutationCount": 0,
        "attendedConsentAttempted": False,
        "issuedAt": "2026-07-18T00:00:00Z",
        "expiresAt": "2026-07-18T00:05:00Z",
        "maxUses": 1,
        "replayIdentitySha256": DIGEST,
        "verdict": "PASS",
    }


def checkpoint_create() -> dict:
    return {
        "schemaVersion": "faz22.6.viewOnlyExternalCheckpointCreate.v1",
        "requestId": "60000000-0000-4000-8000-000000000001",
        "leaseEnvelope": {
            "payloadType": "application/vnd.acik.faz22-6-view-only-checkpoint-lease.v1+json",
            "payload": "e30=",
            "signatures": [
                {
                    "keyid": "vault-transit://endpoint-admin/view-only-checkpoint#v1",
                    "sig": "A" * 86 + "==",
                }
            ],
        },
        "transactionIdSha256": DIGEST,
        "bindingSha256": DIGEST,
        "sequence": 0,
        "previousState": None,
        "state": "DECISION_AUTHORIZED",
        "reasonCode": "decision-authorized",
        "localCheckpointSha256": DIGEST,
        "localPayloadSha256": DIGEST,
        "previousStoredObjectSha256": None,
        "idempotencyKeySha256": DIGEST,
        "terminal": False,
    }


class ViewOnlyPreflightContractTest(unittest.TestCase):
    def test_request_has_no_caller_verdict_surface(self) -> None:
        value = preflight_request()
        validator("faz22-6-view-only-live-preflight-request-v1.schema.json").validate(value)
        value["verdict"] = "PASS"
        self.assertTrue(
            list(
                validator(
                    "faz22-6-view-only-live-preflight-request-v1.schema.json"
                ).iter_errors(value)
            )
        )

    def test_normal_workflow_receipt_rejects_job_workflow_ref(self) -> None:
        value = attestation()
        receipt_validator = validator(
            "faz22-6-view-only-live-preflight-attestation-v1.schema.json"
        )
        receipt_validator.validate(value)
        value["caller"]["jobWorkflowRef"] = WORKFLOW_REF
        self.assertTrue(list(receipt_validator.iter_errors(value)))

    def test_binding_rejects_main_workflow_ref(self) -> None:
        value = binding()
        value["workflowRef"] = (
            "Halildeu/platform-k8s-gitops/.github/workflows/"
            "faz22-6-view-only-viewer-transaction.yml@refs/heads/main"
        )
        self.assertTrue(
            list(
                validator(
                    "faz22-6-view-only-transaction-binding-v1.schema.json"
                ).iter_errors(value)
            )
        )

    def test_checkpoint_sequence_previous_digest_invariants(self) -> None:
        create_validator = validator(
            "faz22-6-view-only-external-checkpoint-create-v1.schema.json"
        )
        value = checkpoint_create()
        create_validator.validate(value)
        invalid_zero = copy.deepcopy(value)
        invalid_zero["previousStoredObjectSha256"] = DIGEST
        self.assertTrue(list(create_validator.iter_errors(invalid_zero)))
        invalid_one = copy.deepcopy(value)
        invalid_one["sequence"] = 1
        self.assertTrue(list(create_validator.iter_errors(invalid_one)))
        invalid_initial_state = copy.deepcopy(value)
        invalid_initial_state["state"] = "LIVE_REVALIDATED"
        self.assertTrue(list(create_validator.iter_errors(invalid_initial_state)))

    def test_checkpoint_terminal_state_invariants(self) -> None:
        create_validator = validator(
            "faz22-6-view-only-external-checkpoint-create-v1.schema.json"
        )
        value = checkpoint_create()
        value["terminal"] = True
        self.assertTrue(list(create_validator.iter_errors(value)))
        value["state"] = "ROLLED_BACK"
        self.assertTrue(list(create_validator.iter_errors(value)))
        value["sequence"] = 1
        value["previousState"] = "ROLLBACK_PENDING"
        value["previousStoredObjectSha256"] = DIGEST
        create_validator.validate(value)

    def test_error_never_claims_api_mutation(self) -> None:
        value = {
            "schemaVersion": "faz22.6.viewOnlyPreflightError.v1",
            "errorId": "70000000-0000-4000-8000-000000000001",
            "code": "PREFLIGHT_CHECK_FAILED",
            "message": "fixed-function check failed",
            "retryable": False,
            "mutationCount": 0,
            "credentialMaterialIncluded": False,
        }
        error_validator = validator(
            "faz22-6-view-only-preflight-error-v1.schema.json"
        )
        error_validator.validate(value)
        value["mutationCount"] = 1
        self.assertTrue(list(error_validator.iter_errors(value)))

    def test_transport_retry_keys_are_mandatory(self) -> None:
        requests = {
            "faz22-6-view-only-transaction-binding-request-v1.schema.json": {
                "schemaVersion": "faz22.6.viewOnlyTransactionBindingRequest.v1",
                "requestId": "30000000-0000-4000-8000-000000000001",
                "idempotencyKeySha256": DIGEST,
                "requestedPayloadType": (
                    "application/vnd.acik.faz22-6-view-only-"
                    "transaction-binding-handoff.v1+json"
                ),
                "workflowPath": (
                    ".github/workflows/"
                    "faz22-6-view-only-viewer-transaction.yml"
                ),
            },
            "faz22-6-view-only-live-preflight-request-v1.schema.json": (
                preflight_request()
            ),
        }
        for schema_name, value in requests.items():
            request_validator = validator(schema_name)
            request_validator.validate(value)
            without_key = copy.deepcopy(value)
            del without_key["idempotencyKeySha256"]
            self.assertTrue(list(request_validator.iter_errors(without_key)))

    def test_persona_and_tenant_are_bound_to_signed_binding(self) -> None:
        value = attestation()
        self.assertEqual(
            value["persona"]["identitySha256"],
            value["binding"]["preflightPersonaIdentitySha256"],
        )
        self.assertEqual(
            value["persona"]["tenantIdSha256"],
            value["binding"]["tenantIdSha256"],
        )
        wrong_persona = copy.deepcopy(value)
        wrong_persona["persona"]["identitySha256"] = DIGEST
        self.assertNotEqual(
            wrong_persona["persona"]["identitySha256"],
            wrong_persona["binding"]["preflightPersonaIdentitySha256"],
        )

    def test_active_runtime_trust_root_requires_both_signer_roles(self) -> None:
        trust_validator = validator(
            "faz22-6-view-only-runtime-trust-root-v1.schema.json"
        )
        pending = {
            "schemaVersion": "faz22.6.viewOnlyRuntimeTrustRoot.v1",
            "activationState": "tracked_pending",
            "trustRootId": "faz22-view-only-runtime-test-v1",
            "digestDomain": "faz22.6/view-only/runtime-trust-root/v1",
            "algorithm": "ed25519",
            "keys": [],
            "revocations": [],
            "generatedAt": "2026-07-18T00:00:00Z",
        }
        trust_validator.validate(pending)
        active_without_keys = copy.deepcopy(pending)
        active_without_keys["activationState"] = "active"
        self.assertTrue(list(trust_validator.iter_errors(active_without_keys)))

    def test_external_cas_transition_contract_is_exact(self) -> None:
        authority = json.loads(
            (
                ROOT
                / "config"
                / "faz22-6-view-only-live-preflight-authority.v1.json"
            ).read_text(encoding="utf-8")
        )
        transitions = authority["checkpointCas"]["stateMachine"]["transitions"]
        self.assertEqual(
            transitions,
            {
                "DECISION_AUTHORIZED": [
                    "LIVE_REVALIDATED",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "LIVE_REVALIDATED": [
                    "ACTIVATED",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "ACTIVATED": [
                    "CONSENT_PENDING",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "CONSENT_PENDING": [
                    "EVIDENCE_COLLECTED",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "EVIDENCE_COLLECTED": [
                    "EVIDENCE_VERIFIED",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "EVIDENCE_VERIFIED": [
                    "ARTIFACTS_STAGED",
                    "FAILURE_CAPTURED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "FAILURE_CAPTURED": [
                    "ARTIFACTS_STAGED",
                    "ARTIFACTS_STAGE_FAILED",
                ],
                "ARTIFACTS_STAGE_FAILED": ["ROLLBACK_PENDING"],
                "ARTIFACTS_STAGED": ["ROLLBACK_PENDING"],
                "ROLLBACK_PENDING": ["ROLLED_BACK"],
                "ROLLED_BACK": ["COMPLETED", "FAILED_CLEAN"],
                "COMPLETED": [],
                "FAILED_CLEAN": [],
            },
        )
        self.assertIn(
            "without-idempotencyKeySha256",
            authority["digestDomains"]["idempotencyKeySha256"],
        )


if __name__ == "__main__":
    unittest.main()
