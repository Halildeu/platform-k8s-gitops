#!/usr/bin/env python3
"""Register, dispatch and reconcile signed Cross-AI deployment intents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from scripts.github_apps.cross_ai_deployment_policy.canonical import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    EvidenceVerifier,
    VerifiedBundle,
)
from scripts.github_apps.cross_ai_deployment_policy.dispatcher import (
    IntentDispatchOrchestrator,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.github import (
    GitHubAppTokenProvider,
    GitHubDispatcherClient,
    GitHubReader,
)
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    DispatchJob,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.policy import (
    DeploymentPolicy,
    load_policy,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import utc_now


STAGES = ("apply", "browser-evidence", "compensating-rollback")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cas-dir", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--trust-root-file", type=Path, required=True)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--revocations-file", type=Path, required=True)
    parser.add_argument("--github-app-id", type=int, required=True)
    parser.add_argument("--github-app-key-file", type=Path, required=True)
    parser.add_argument("--installation-id", type=int, required=True)
    parser.add_argument("--github-api-origin", default="https://api.github.com")
    parser.add_argument(
        "--registration-principal",
        default="spiffe://acik/platform/trusted-dispatcher",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register-and-dispatch-apply")
    register.add_argument("--bundle-file", type=Path, required=True)
    dispatch = commands.add_parser("dispatch-stage")
    dispatch.add_argument("--request-id", required=True)
    dispatch.add_argument("--stage", choices=STAGES, required=True)
    reconcile = commands.add_parser("reconcile-dispatch")
    reconcile.add_argument("--request-id", required=True)
    reconcile.add_argument("--stage", choices=STAGES, required=True)
    return parser.parse_args()


def _policy_verifier(
    *,
    policy: DeploymentPolicy,
    trust_root: dict[str, Any],
    expected_trust_root_sha256: str,
    revocations_file: Path,
):
    def verify(envelope: dict[str, Any]) -> VerifiedBundle:
        verified = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=load_json_file(revocations_file),
            now=utc_now(),
            expected_policy_sha256=policy.digest,
            expected_trust_root_sha256=expected_trust_root_sha256,
        ).verify_bundle(envelope)
        subject = verified.payload["subject"]
        grant = verified.payload["grant"]
        if (
            subject["repositoryId"] != policy.repository_id
            or subject["repository"] != policy.repository
            or subject["environment"] != policy.environment
            or subject["deploymentClass"] not in policy.allowed_deployment_classes
        ):
            reject("DISPATCH_POLICY_MISMATCH", "signed intent is outside dispatcher policy")
        if grant["triggeringActorId"] not in policy.allowed_dispatcher_actor_ids:
            reject("DISPATCH_ACTOR_MISMATCH", "signed dispatcher actor is not allowlisted")
        signed_paths = {
            stage["stage"]: stage["workflowPath"]
            for stage in verified.payload["workflowStages"]
        }
        if signed_paths != {
            name: stage.workflow_path for name, stage in policy.stages.items()
        }:
            reject("DISPATCH_WORKFLOW_MISMATCH", "signed workflow paths differ from policy")
        return verified

    return verify


def _result(job: DispatchJob) -> dict[str, Any]:
    return {
        "requestId": job.request_id,
        "stage": job.stage,
        "state": job.state,
        "reasonCode": job.reason_code,
        "httpStatus": job.http_status,
        "runId": job.run_id,
        "automaticRetryAllowed": False,
    }


def main() -> int:
    args = parse_args()
    registry: IntentRegistry | None = None
    try:
        policy = load_policy(args.policy_file)
        if args.github_api_origin not in policy.allowed_api_origins:
            reject("GITHUB_API_ORIGIN_MISMATCH", "dispatcher API origin is not allowlisted")
        if args.installation_id not in policy.allowed_dispatcher_installation_ids:
            reject(
                "GITHUB_INSTALLATION_MISMATCH",
                "dispatcher installation is not allowlisted by policy",
            )
        trust_root = load_json_file(args.trust_root_file)
        token_provider = GitHubAppTokenProvider(
            app_id=args.github_app_id,
            private_key_file=args.github_app_key_file,
            api_origin=args.github_api_origin,
        )
        reader = GitHubReader(
            token_provider=token_provider,
            api_origin=args.github_api_origin,
        )
        registry = IntentRegistry(
            args.db,
            ContentAddressedStore(args.cas_dir),
        )
        orchestrator = IntentDispatchOrchestrator(
            registry=registry,
            dispatcher=GitHubDispatcherClient(
                token_provider=token_provider,
                reader=reader,
                api_origin=args.github_api_origin,
            ),
            reader=reader,
            installation_id=args.installation_id,
            registration_principal=args.registration_principal,
            verify_envelope=_policy_verifier(
                policy=policy,
                trust_root=trust_root,
                expected_trust_root_sha256=args.expected_trust_root_sha256,
                revocations_file=args.revocations_file,
            ),
        )
        if args.command == "register-and-dispatch-apply":
            job = orchestrator.register_and_dispatch_apply(
                envelope=load_json_file(args.bundle_file),
            )
        elif args.command == "dispatch-stage":
            job = orchestrator.dispatch_stage(
                request_id=args.request_id,
                stage=args.stage,
            )
        else:
            job = orchestrator.reconcile_dispatch(
                request_id=args.request_id,
                stage=args.stage,
            )
        sys.stdout.buffer.write(canonical_bytes(_result(job)) + b"\n")
        return 0 if job.state == "Accepted" else 3
    except PolicyError as exc:
        sys.stdout.buffer.write(
            canonical_bytes(
                {
                    "error": exc.code,
                    "message": exc.message,
                    "automaticRetryAllowed": False,
                }
            )
            + b"\n"
        )
        return 2
    finally:
        if registry is not None:
            registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
