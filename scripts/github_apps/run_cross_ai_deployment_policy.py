#!/usr/bin/env python3
"""Run the Cross-AI deployment protection GitHub App webhook service."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.ledger import ObserveLedger
from scripts.github_apps.cross_ai_deployment_policy.evaluator import DeploymentEvaluator
from scripts.github_apps.cross_ai_deployment_policy.github import (
    GitHubAppTokenProvider,
    GitHubArtifactDownloader,
    GitHubDecisionClient,
    GitHubReader,
)
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.reconciler import (
    GitHubOutcomeReconciler,
    GitHubStageArtifactSource,
    OutcomeSweeper,
)
from scripts.github_apps.cross_ai_deployment_policy.server import (
    ObserveService,
    make_server,
)
from scripts.github_apps.cross_ai_deployment_policy.webhook import load_secret_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--webhook-secret-file",
        type=Path,
        action="append",
        required=True,
        help="Mounted secret path; repeat once during bounded rotation.",
    )
    parser.add_argument(
        "--mode",
        choices=("observe", "enforce"),
        default="observe",
        help="Observe never calls back; enforce requires every evaluator argument.",
    )
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--trust-root-file", type=Path)
    parser.add_argument(
        "--expected-trust-root-sha256",
        help="Canonical sha256:... digest pinned outside the trust-root manifest.",
    )
    parser.add_argument("--revocations-file", type=Path)
    parser.add_argument("--cas-dir", type=Path)
    parser.add_argument("--registry-db", type=Path)
    parser.add_argument("--github-app-id", type=int)
    parser.add_argument("--github-app-key-file", type=Path)
    parser.add_argument("--github-api-origin", default="https://api.github.com")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    secrets = load_secret_files(args.webhook_secret_file)
    ledger = ObserveLedger(args.db)
    evaluator_args = (
        args.policy_file,
        args.trust_root_file,
        args.expected_trust_root_sha256,
        args.revocations_file,
        args.cas_dir,
        args.registry_db,
        args.github_app_id,
        args.github_app_key_file,
    )
    configured = any(value is not None for value in evaluator_args)
    if configured and not all(value is not None for value in evaluator_args):
        raise SystemExit("all evaluator/GitHub App arguments must be supplied together")
    if args.mode == "enforce" and not configured:
        raise SystemExit("enforce mode requires evaluator/GitHub App arguments")

    registry = None
    evaluator = None
    decision_client = None
    outcome_sweeper = None
    allowed_origins: tuple[str, ...] = (args.github_api_origin,)
    if configured:
        policy = load_policy(args.policy_file)
        if args.github_api_origin not in policy.allowed_api_origins:
            raise SystemExit("GitHub API origin is not allowlisted by policy")
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
            args.registry_db,
            ContentAddressedStore(args.cas_dir),
        )
        evaluator = DeploymentEvaluator(
            policy=policy,
            registry=registry,
            github=reader,
            trust_root=trust_root,
            expected_trust_root_sha256=args.expected_trust_root_sha256,
            revocations_loader=lambda: load_json_file(args.revocations_file),
            mode=args.mode,
        )
        if args.mode == "enforce":
            decision_client = GitHubDecisionClient(
                token_provider=token_provider,
                api_origin=args.github_api_origin,
            )
            outcome_reconciler = GitHubOutcomeReconciler(
                installation_id=next(iter(policy.allowed_installation_ids)),
                registry=registry,
                github=reader,
                artifact_source=GitHubStageArtifactSource(
                    reader=reader,
                    downloader=GitHubArtifactDownloader(
                        token_provider=token_provider,
                        api_origin=args.github_api_origin,
                    ),
                ),
                trust_root=trust_root,
                expected_trust_root_sha256=args.expected_trust_root_sha256,
                revocations_loader=lambda: load_json_file(args.revocations_file),
            )
            outcome_sweeper = OutcomeSweeper(
                registry=registry,
                reconciler=outcome_reconciler,
            )
        allowed_origins = policy.allowed_api_origins
    service = ObserveService(
        secrets=secrets,
        ledger=ledger,
        allowed_api_origins=allowed_origins,
        evaluator=evaluator,
        mode=args.mode,
        registry=registry,
        decision_client=decision_client,
        outcome_sweeper=outcome_sweeper,
    )
    server = make_server(args.listen, args.port, service)
    shutdown_started = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        service.stop()
        if registry is not None:
            registry.close()
        ledger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
