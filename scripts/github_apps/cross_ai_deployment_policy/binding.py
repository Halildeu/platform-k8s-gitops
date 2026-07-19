"""Fail-closed coordinator-signed VIEW_ONLY transaction binding handoff."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .canonical import sha256_digest
from .contract import EvidenceVerifier, VerifiedBundle
from .dsse import decode_public_key, verify_json_envelope
from .errors import reject
from .intent_store import IdempotentEnvelope, IntentRegistry
from .jsonutil import loads_json_bytes
from .oidc import ISSUER, JWKS_URL, GitHubOIDCVerifier
from .timeutil import parse_utc, utc_now, utc_seconds


ROOT = Path(__file__).resolve().parents[3]
REQUEST_SCHEMA = ROOT / "schema/faz22-6-view-only-transaction-binding-request-v1.schema.json"
BINDING_SCHEMA = ROOT / "schema/faz22-6-view-only-transaction-binding-v1.schema.json"
HANDOFF_SCHEMA = ROOT / "schema/faz22-6-view-only-transaction-binding-handoff-v1.schema.json"
DSSE_SCHEMA = ROOT / "schema/faz22-6-dsse-envelope-v1.schema.json"

WORKFLOW_PATH = ".github/workflows/faz22-6-view-only-viewer-transaction.yml"
AUTHORITY_PATH = "config/faz22-6-view-only-live-preflight-authority.v1.json"
RUNTIME_TRUST_ROOT_PATH = "config/faz22-6-view-only-runtime-trust-root.v1.json"
RUNTIME_TRUST_ROOT_SCHEMA = (
    ROOT / "schema/faz22-6-view-only-runtime-trust-root-v1.schema.json"
)
BINDING_PAYLOAD_TYPE = (
    "application/vnd.acik.faz22-6-view-only-transaction-binding-handoff.v1+json"
)
BINDING_OPERATION = "view-only-transaction-binding"
BINDING_IDEMPOTENCY_DOMAIN = "faz22.6/view-only/transaction-binding-idempotency/v1"
BINDING_DIGEST_DOMAIN = "faz22.6/view-only/transaction-binding/v1"
TRANSACTION_ID_DOMAIN = "faz22.6/view-only/transaction-id/v1"
OIDC_IDENTITY_DOMAIN = "faz22.6/view-only/oidc-stable-identity/v1"
OIDC_JTI_DOMAIN = "faz22.6/view-only/oidc-jti/v1"
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 65536


class BindingGitHubReader(Protocol):
    def workflow_run(
        self, installation_id: int, repository: str, run_id: int
    ) -> dict[str, Any]: ...

    def intent_ref(
        self, installation_id: int, repository: str, request_id: str
    ) -> Any: ...

    def workflow_bytes(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        head_sha: str,
    ) -> bytes: ...


class BindingSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    def sign_json_envelope(
        self, *, payload_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        reject("BINDING_SCHEMA_UNAVAILABLE", f"cannot load {path.name}")
    if not isinstance(value, dict):
        reject("BINDING_SCHEMA_UNAVAILABLE", f"{path.name} is not an object")
    Draft202012Validator.check_schema(value)
    return value


class _BindingSchemas:
    def __init__(self) -> None:
        self.request = _load_schema(REQUEST_SCHEMA)
        self.binding = _load_schema(BINDING_SCHEMA)
        self.handoff = _load_schema(HANDOFF_SCHEMA)
        self.dsse = _load_schema(DSSE_SCHEMA)
        self.runtime_trust_root = _load_schema(RUNTIME_TRUST_ROOT_SCHEMA)
        registry = Registry().with_resources(
            (
                schema["$id"],
                Resource.from_contents(schema),
            )
            for schema in (
                self.request,
                self.binding,
                self.handoff,
                self.dsse,
                self.runtime_trust_root,
            )
        )
        self._registry = registry

    def validate(self, value: object, schema: dict[str, Any], code: str) -> None:
        errors = sorted(
            Draft202012Validator(
                schema,
                registry=self._registry,
                format_checker=FormatChecker(),
            ).iter_errors(value),
            key=lambda item: list(item.path),
        )
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.absolute_path) or "$"
            reject(code, f"invalid binding contract at {location}: {first.message}")


class ViewOnlyBindingAuthority:
    """Derive one signed handoff from verified registry and live GitHub truth."""

    def __init__(
        self,
        *,
        installation_id: int,
        registry: IntentRegistry,
        github: BindingGitHubReader,
        trust_root: dict[str, Any],
        expected_trust_root_sha256: str,
        expected_policy_sha256: str,
        revocations_loader: Callable[[], dict[str, Any]],
        oidc_verifier: GitHubOIDCVerifier,
        signer: BindingSigner,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if installation_id < 1:
            reject("BINDING_CONFIG_INVALID", "installation ID must be positive")
        self.installation_id = installation_id
        self.registry = registry
        self.github = github
        self.trust_root = trust_root
        self.expected_trust_root_sha256 = expected_trust_root_sha256
        self.expected_policy_sha256 = expected_policy_sha256
        self.revocations_loader = revocations_loader
        self.oidc_verifier = oidc_verifier
        self.signer = signer
        self._now = now
        self.schemas = _BindingSchemas()

    def parse_request(self, raw_body: bytes) -> dict[str, Any]:
        request = loads_json_bytes(
            raw_body,
            max_bytes=MAX_REQUEST_BYTES,
            label="VIEW_ONLY binding request",
        )
        self.schemas.validate(
            request,
            self.schemas.request,
            "BINDING_REQUEST_INVALID",
        )
        return request

    @staticmethod
    def _stage(bundle: VerifiedBundle) -> dict[str, Any]:
        stages = bundle.payload["workflowStages"]
        if len(stages) != 1 or stages[0].get("stage") != "transaction":
            reject("BINDING_STAGE_INVALID", "v3 transaction stage is not unique")
        return stages[0]

    def _verified_bundle(self, request_id: str, current: datetime) -> tuple[Any, VerifiedBundle]:
        record, envelope = self.registry.get_finalized(request_id)
        verified = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_loader(),
            now=current,
            expected_trust_root_sha256=self.expected_trust_root_sha256,
            expected_policy_sha256=self.expected_policy_sha256,
            expected_bundle_contract="v3",
        ).verify_bundle(envelope)
        if (
            verified.request_id != request_id
            or record.bundle_digest != verified.bundle_digest
            or record.state != "Finalized"
            or record.ref_object_id is None
            or record.finalized_at is None
        ):
            reject(
                "BINDING_REGISTRY_MISMATCH",
                "finalized registry differs from verified v3 evidence",
            )
        return record, verified

    def _authority_files(
        self,
        *,
        record: Any,
        stage: dict[str, Any],
    ) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for entry in stage["authorityFiles"]:
            path = entry["path"]
            raw = self.github.workflow_bytes(
                self.installation_id,
                record.repository,
                path,
                record.head_sha,
            )
            digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
            if digest != entry["sha256"]:
                reject(
                    "BINDING_AUTHORITY_FILE_MISMATCH",
                    "exact-head authority file differs from signed v3 evidence",
                )
            files[path] = raw
        if AUTHORITY_PATH not in files or RUNTIME_TRUST_ROOT_PATH not in files:
            reject(
                "BINDING_AUTHORITY_FILE_MISSING",
                "binding authority or runtime trust root is absent from signed scope",
            )
        if files.get(stage["workflowPath"]) is None:
            reject(
                "BINDING_AUTHORITY_FILE_MISSING",
                "transaction workflow is absent from signed authority scope",
            )
        return files

    def _authority_config(
        self,
        raw: bytes,
        runtime_trust_root_raw: bytes,
        current: datetime,
    ) -> dict[str, Any]:
        value = loads_json_bytes(
            raw,
            max_bytes=256 * 1024,
            label="VIEW_ONLY live preflight authority",
        )
        runtime_trust_root = loads_json_bytes(
            runtime_trust_root_raw,
            max_bytes=256 * 1024,
            label="VIEW_ONLY runtime trust root",
        )
        self.schemas.validate(
            runtime_trust_root,
            self.schemas.runtime_trust_root,
            "BINDING_RUNTIME_TRUST_ROOT_INVALID",
        )
        try:
            activation = value["activation"]
            profile = value["githubOidcProfiles"]["binding"]
            persona = value["personaPolicy"]
            runtime = value["runtimeTrustRoot"]
        except (KeyError, TypeError):
            reject(
                "BINDING_AUTHORITY_INVALID",
                "live preflight authority is incomplete",
            )
        if (
            value.get("schemaVersion") != "faz22.6.viewOnlyLivePreflightAuthority.v1"
            or value.get("repository") != "Halildeu/platform-k8s-gitops"
            or value.get("transactionWorkflow") != WORKFLOW_PATH
            or activation.get("state") != "active"
            or activation.get("blockers") != []
            or profile.get("issuer") != ISSUER
            or profile.get("jwksUri") != JWKS_URL
            or persona.get("identitySource")
            != "binding.preflightPersonaIdentitySha256"
            or persona.get("tenantSource") != "binding.tenantIdSha256"
            or persona.get("identitySha256") is None
            or persona.get("tenantIdSha256") is None
            or runtime.get("path") != RUNTIME_TRUST_ROOT_PATH
            or runtime.get("schemaRef")
            != "schema/faz22-6-view-only-runtime-trust-root-v1.schema.json"
            or runtime.get("digestDomain")
            != "faz22.6/view-only/runtime-trust-root/v1"
            or runtime.get("expectedSha256")
            != sha256_digest(
                {
                    "domain": runtime.get("digestDomain"),
                    "trustRoot": runtime_trust_root,
                }
            )
            or runtime_trust_root.get("activationState") != "active"
            or runtime_trust_root.get("digestDomain") != runtime.get("digestDomain")
        ):
            reject(
                "BINDING_AUTHORITY_INACTIVE",
                "live preflight authority is not fully pinned and active",
            )
        key_ids = [entry["keyId"] for entry in runtime_trust_root["keys"]]
        roles = [entry["role"] for entry in runtime_trust_root["keys"]]
        revoked = {
            entry["keyId"]
            for entry in runtime_trust_root["revocations"]
            if parse_utc(entry["revokedAt"], "runtimeTrustRoot.revokedAt") <= current
        }
        if (
            len(key_ids) != len(set(key_ids))
            or sorted(roles) != ["checkpoint-signer", "runtime-attestor"]
            or any(key_id in revoked for key_id in key_ids)
            or any(
                not (
                    parse_utc(entry["notBefore"], "runtimeTrustRoot.notBefore")
                    <= current
                    < parse_utc(entry["notAfter"], "runtimeTrustRoot.notAfter")
                )
                for entry in runtime_trust_root["keys"]
            )
        ):
            reject(
                "BINDING_RUNTIME_TRUST_ROOT_INACTIVE",
                "runtime trust root signer set is not active at binding time",
            )
        return value

    @staticmethod
    def _run_binding(record: Any, dispatch: Any, run: dict[str, Any]) -> dict[str, Any]:
        repository = run.get("repository")
        head_repository = run.get("head_repository")
        actor = run.get("triggering_actor")
        expected_branch = record.intent_ref.removeprefix("refs/tags/")
        expected_workflow_ref = f"{record.repository}/{WORKFLOW_PATH}@{record.intent_ref}"
        if (
            dispatch.state != "Accepted"
            or dispatch.run_id is None
            or dispatch.run_id != run.get("id")
            or dispatch.pre_dispatch_run_id_watermark is None
            or dispatch.run_id <= dispatch.pre_dispatch_run_id_watermark
            or dispatch.intent_ref != record.intent_ref
            or dispatch.head_sha != record.head_sha
            or dispatch.workflow_path != WORKFLOW_PATH
            or dispatch.expected_actor_id != record.triggering_actor_id
            or run.get("run_attempt") != 1
            or run.get("event") != "workflow_dispatch"
            or run.get("head_sha") != record.head_sha
            or run.get("head_branch") != expected_branch
            or run.get("path") != WORKFLOW_PATH
            or run.get("status") not in {"queued", "in_progress"}
            or not isinstance(repository, dict)
            or repository.get("id") != record.repository_id
            or repository.get("full_name") != record.repository
            or not isinstance(head_repository, dict)
            or head_repository.get("id") != record.repository_id
            or head_repository.get("full_name") != record.repository
            or not isinstance(actor, dict)
            or actor.get("id") != record.triggering_actor_id
        ):
            reject(
                "BINDING_DISPATCH_MISMATCH",
                "accepted dispatch or live workflow run differs from finalized intent",
            )
        correlated_at = dispatch.resolved_at or run.get("created_at")
        parse_utc(correlated_at, "dispatch.correlatedAt")
        return {
            "expectedBranch": expected_branch,
            "expectedWorkflowRef": expected_workflow_ref,
            "correlatedAt": correlated_at,
        }

    def _verify_oidc(
        self,
        *,
        token: str,
        record: Any,
        verified: VerifiedBundle,
        dispatch: Any,
        authority: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
        profile = authority["githubOidcProfiles"]["binding"]
        static = profile["requiredStaticClaims"]
        expected_workflow_ref = f"{record.repository}/{WORKFLOW_PATH}@{record.intent_ref}"
        exact_claims = {
            **static,
            "ref": record.intent_ref,
            "sha": record.head_sha,
            "workflow_sha": record.head_sha,
            "workflow_ref": expected_workflow_ref,
            "sub": f"repo:{record.repository}:ref:{record.intent_ref}",
        }
        claims = self.oidc_verifier.verify_claim_profile(
            token,
            audience=profile["audience"],
            exact_claims=exact_claims,
            positive_claims={
                "run_id": dispatch.run_id,
                "run_attempt": 1,
                "actor_id": verified.payload["grant"]["triggeringActorId"],
            },
            forbidden_claims=tuple(profile["forbiddenClaims"]),
            required_unique_claims=tuple(profile["requiredUniqueClaims"]),
            max_token_age_seconds=profile["maxTokenAgeSeconds"],
        )
        identity = {
            name: claims[name]
            for name in (
                "iss",
                "sub",
                "actor_id",
                "repository_id",
                "run_id",
                "run_attempt",
                "ref",
                "sha",
            )
        }
        identity_digest = sha256_digest(
            {"domain": OIDC_IDENTITY_DOMAIN, "identity": identity}
        )
        jti_digest = sha256_digest(
            {"domain": OIDC_JTI_DOMAIN, "jti": claims["jti"]}
        )
        return claims, identity, identity_digest, jti_digest, expected_workflow_ref

    @staticmethod
    def _idempotency(
        request: dict[str, Any], identity: dict[str, Any]
    ) -> tuple[str, str]:
        body = dict(request)
        supplied = body.pop("idempotencyKeySha256")
        body_digest = sha256_digest(body)
        expected = sha256_digest(
            {
                "domain": BINDING_IDEMPOTENCY_DOMAIN,
                "requestId": request["requestId"],
                "bodySha256": body_digest,
                "identity": identity,
            }
        )
        if supplied != expected:
            reject(
                "BINDING_IDEMPOTENCY_MISMATCH",
                "binding idempotency key differs from canonical request identity",
            )
        return body_digest, expected

    @staticmethod
    def _binding(
        *,
        record: Any,
        verified: VerifiedBundle,
        stage: dict[str, Any],
        dispatch: Any,
        authority: dict[str, Any],
        workflow_ref: str,
    ) -> dict[str, Any]:
        subject = verified.payload["subject"]
        persona = authority["personaPolicy"]
        binding = {
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "deploymentClass": subject["deploymentClass"],
            "productSlice": subject["productSlice"],
            "intentRef": subject["intentRef"],
            "intentBundleSha256": verified.bundle_digest,
            "transactionSessionSha256": subject["sessionSha256"],
            "headSha": subject["headSha"],
            "workflowPath": stage["workflowPath"],
            "workflowRef": workflow_ref,
            "workflowBlobSha256": stage["workflowBlobSha256"],
            "dependencyLockSha256": stage["dependencyLockSha256"],
            "concurrencySha256": stage["concurrencyGroupSha256"],
            "authoritySetSha256": subject["transactionScopeSha256"],
            "runId": dispatch.run_id,
            "runAttempt": 1,
            "triggeringActorId": verified.payload["grant"]["triggeringActorId"],
            "machineAuthorityPolicySha256": subject["policySha256"],
            "artifactSetSha256": subject["artifactSetSha256"],
            "rollbackPlanSha256": subject["rollbackPlanSha256"],
            "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
            "bootstrapCredentialSha256": subject["bootstrapCredentialSha256"],
            "tenantIdSha256": persona["tenantIdSha256"],
            "preflightPersonaIdentitySha256": persona["identitySha256"],
            "endpointIdSha256": subject["endpointIdSha256"],
            "operatorIdSha256": subject["operatorIdSha256"],
            "deviceHostnameSha256": subject["deviceHostnameSha256"],
            "attendedConsentPolicySha256": subject["attendedConsentPolicySha256"],
            "pilotOwnerPolicySha256": subject["pilotOwnerPolicySha256"],
            "maskPolicySha256": subject["maskPolicySha256"],
            "runtimeImageDigest": subject["runtimeImageDigest"],
            "pilotSeconds": subject["pilotSeconds"],
            "transactionScopeSha256": subject["transactionScopeSha256"],
            "runnerPolicySha256": subject["runnerPolicySha256"],
            "runnerAdmissionLeaseSha256": subject["runnerAdmissionLeaseSha256"],
        }
        if (
            record.request_id != verified.request_id
            or record.intent_ref != binding["intentRef"]
            or record.head_sha != binding["headSha"]
            or binding["authoritySetSha256"] != binding["transactionScopeSha256"]
        ):
            reject(
                "BINDING_DERIVATION_MISMATCH",
                "binding fields differ from registry or signed v3 subject",
            )
        return binding

    def issue(
        self,
        *,
        request: dict[str, Any],
        oidc_token: str,
    ) -> IdempotentEnvelope:
        self.schemas.validate(request, self.schemas.request, "BINDING_REQUEST_INVALID")
        current = self._now()
        record, verified = self._verified_bundle(request["requestId"], current)
        stage = self._stage(verified)
        dispatch = self.registry.get_dispatch(request["requestId"], "transaction")
        if dispatch.state != "Accepted" or dispatch.run_id is None:
            reject(
                "BINDING_DISPATCH_MISMATCH",
                "transaction dispatch is not accepted and correlated",
            )
        run = self.github.workflow_run(
            self.installation_id,
            record.repository,
            dispatch.run_id,
        )
        run_binding = self._run_binding(record, dispatch, run)
        intent_ref = self.github.intent_ref(
            self.installation_id,
            record.repository,
            request["requestId"],
        )
        if (
            intent_ref.ref_object_id != record.ref_object_id
            or intent_ref.head_sha != record.head_sha
        ):
            reject(
                "BINDING_INTENT_REF_MISMATCH",
                "live immutable intent ref differs from finalized registry",
            )
        authority_files = self._authority_files(record=record, stage=stage)
        authority = self._authority_config(
            authority_files[AUTHORITY_PATH],
            authority_files[RUNTIME_TRUST_ROOT_PATH],
            current,
        )
        _, identity, identity_digest, jti_digest, workflow_ref = self._verify_oidc(
            token=oidc_token,
            record=record,
            verified=verified,
            dispatch=dispatch,
            authority=authority,
        )
        request_digest, idempotency_key = self._idempotency(request, identity)
        existing = self.registry.get_idempotent_envelope(
            operation=BINDING_OPERATION,
            request_id=request["requestId"],
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            identity_digest=identity_digest,
        )
        if existing is not None:
            return existing

        verifier = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_loader(),
            now=current,
            expected_trust_root_sha256=self.expected_trust_root_sha256,
            expected_policy_sha256=self.expected_policy_sha256,
            expected_bundle_contract="v3",
        )
        verifier.require_active_signing_key(
            role="coordinator",
            key_id=self.signer.key_id,
            issued_at=current,
        )
        if self.signer.key_id != verified.coordinator_key_id:
            reject(
                "BINDING_SIGNER_MISMATCH",
                "binding signer differs from verified v3 coordinator",
            )
        binding = self._binding(
            record=record,
            verified=verified,
            stage=stage,
            dispatch=dispatch,
            authority=authority,
            workflow_ref=workflow_ref,
        )
        self.schemas.validate(binding, self.schemas.binding, "BINDING_PAYLOAD_INVALID")
        issued_at = current.replace(microsecond=0)
        expires_at = min(issued_at + timedelta(seconds=300), verified.expires_at)
        if expires_at <= issued_at:
            reject("BINDING_EXPIRED", "binding grant has no remaining lifetime")
        payload = {
            "schemaVersion": "faz22.6.viewOnlyTransactionBindingHandoff.v1",
            "handoffId": str(uuid.uuid4()),
            "lookupRequestId": request["requestId"],
            "idempotencyKeySha256": idempotency_key,
            "binding": binding,
            "bindingSha256": sha256_digest(
                {"domain": BINDING_DIGEST_DOMAIN, "binding": binding}
            ),
            "transactionIdSha256": sha256_digest(
                {"domain": TRANSACTION_ID_DOMAIN, "binding": binding}
            ),
            "derivation": {
                "bundleSchemaVersion": verified.payload["schemaVersion"],
                "bundleRequestId": verified.request_id,
                "bundleEnvelopeSha256": verified.bundle_digest,
                "registryState": "DispatchAccepted",
                "intentRefObjectId": record.ref_object_id,
                "intentRefHeadSha": record.head_sha,
                "intentRefFinalized": True,
                "dispatchAccepted": True,
                "dispatchWatermarkRunId": dispatch.pre_dispatch_run_id_watermark,
                "dispatchRunId": dispatch.run_id,
                "dispatchRunAttempt": 1,
                "dispatchTriggeringActorId": dispatch.expected_actor_id,
                "dispatchHeadBranch": run_binding["expectedBranch"],
                "dispatchHeadRepository": record.repository,
                "dispatchRepository": record.repository,
                "dispatchWorkflowPath": WORKFLOW_PATH,
                "dispatchStatus": run["status"],
                "dispatchHeadSha": record.head_sha,
                "dispatchWorkflowRef": run_binding["expectedWorkflowRef"],
                "correlatedAt": run_binding["correlatedAt"],
            },
            "caller": {
                "profile": "binding",
                "subject": identity["sub"],
                "ref": identity["ref"],
                "workflowRef": workflow_ref,
                "headSha": identity["sha"],
                "runId": int(identity["run_id"]),
                "runAttempt": int(identity["run_attempt"]),
                "triggeringActorId": int(identity["actor_id"]),
                "runnerEnvironment": "github-hosted",
                "tokenJtiSha256": jti_digest,
            },
            "issuedAt": utc_seconds(issued_at),
            "expiresAt": utc_seconds(expires_at),
            "maxUses": 1,
            "mutationCount": 0,
        }
        self.schemas.validate(payload, self.schemas.handoff, "BINDING_PAYLOAD_INVALID")
        envelope = self.signer.sign_json_envelope(
            payload_type=BINDING_PAYLOAD_TYPE,
            payload=payload,
        )
        self.schemas.validate(envelope, self.schemas.dsse, "BINDING_ENVELOPE_INVALID")
        public_keys = {
            entry["keyId"]: decode_public_key(
                entry["publicKeyBase64"], entry["keyId"]
            )
            for entry in self.trust_root["keys"]
            if entry.get("role") == "coordinator"
        }
        receipt = verify_json_envelope(
            envelope,
            expected_payload_type=BINDING_PAYLOAD_TYPE,
            allowed_keys=public_keys,
            required_key_ids={self.signer.key_id},
            exactly_one_signature=True,
        )
        if receipt.payload != payload:
            reject(
                "BINDING_SIGNATURE_INVALID",
                "binding payload changed during coordinator signing",
            )
        return self.registry.record_idempotent_envelope(
            operation=BINDING_OPERATION,
            request_id=request["requestId"],
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            identity_digest=identity_digest,
            envelope=envelope,
            max_response_bytes=MAX_RESPONSE_BYTES,
            created_at=current,
        )


__all__ = [
    "BINDING_PAYLOAD_TYPE",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "ViewOnlyBindingAuthority",
]
