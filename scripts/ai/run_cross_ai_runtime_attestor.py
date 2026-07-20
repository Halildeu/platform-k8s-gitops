#!/usr/bin/env python3
"""Run the isolated fixed-function direct-Codex runtime attestor."""

from __future__ import annotations

import argparse
import hashlib
import os
import signal
import threading
from pathlib import Path

from scripts.ai.cross_ai_runtime_attestor_service import (
    FixedRuntimeAttestorService,
    RuntimeSessionStore,
    make_runtime_server,
)
from scripts.ai.cross_ai_runtime_workload import (
    KubernetesPodTransport,
    KubernetesWorkloadVerifier,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.errors import reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.provider import DirectCodexRunner
from scripts.github_apps.cross_ai_deployment_policy.transit import (
    VaultKubernetesTransitSigner,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--authority-file", type=Path, required=True)
    parser.add_argument("--trust-root-file", type=Path, required=True)
    parser.add_argument("--revocations-file", type=Path, required=True)
    parser.add_argument("--authorization-token-file", type=Path, required=True)
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-kubernetes-jwt-file", type=Path, required=True)
    parser.add_argument("--kubernetes-api-token-file", type=Path, required=True)
    parser.add_argument("--kubernetes-ca-file", type=Path, required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--pod-uid", required=True)
    parser.add_argument("--pod-namespace", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--runner-key-version", type=int, required=True)
    parser.add_argument("--codex-executable", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    authority = load_json_file(args.authority_file)
    trust_root = load_json_file(args.trust_root_file)
    required = {
        "schemaVersion",
        "status",
        "authoritySource",
        "codexExecutablePolicy",
        "trustRootPath",
        "revocationsPath",
        "expectedTrustRootSha256",
        "issuerRuntimePolicy",
        "historicalAuthorities",
        "rotationPolicy",
    }
    if (
        set(authority) != required
        or authority.get("schemaVersion")
        != "acik.cross-ai-provider-review-authority.v1"
        or authority.get("status") != "active"
        or authority.get("trustRootPath")
        != "config/github-apps/cross-ai-provider-review-trust-root.v2.json"
        or authority.get("revocationsPath")
        != "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json"
        or authority.get("expectedTrustRootSha256") != sha256_digest(trust_root)
        or authority.get("issuerRuntimePolicy")
        != trust_root.get("providerReviewRuntimePolicy")
    ):
        reject(
            "PROVIDER_RUNTIME_AUTHORITY_INVALID",
            "runtime service public authority is inactive or inconsistent",
        )
    launcher_digest = "sha256:" + hashlib.sha256(
        Path(__file__).with_name("cross_ai_runtime_attestor_service.py").read_bytes()
    ).hexdigest()
    if authority["issuerRuntimePolicy"].get("launcherSourceSha256") != launcher_digest:
        reject(
            "PROVIDER_RUNTIME_LAUNCHER_MISMATCH",
            "runtime service source differs from the public authority pin",
        )
    args.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = RuntimeSessionStore(args.db)
    signer = VaultKubernetesTransitSigner(
        vault_origin=args.vault_origin,
        kubernetes_jwt_file=args.vault_kubernetes_jwt_file,
        auth_mount=authority["issuerRuntimePolicy"]["vaultKubernetesAuthMount"],
        role=authority["issuerRuntimePolicy"]["vaultKubernetesRole"],
        expected_policy=authority["issuerRuntimePolicy"]["vaultTokenPolicy"],
        mount="cross-ai",
        key_name="runner-management",
        key_version=args.runner_key_version,
    )
    runner = DirectCodexRunner(
        executable=args.codex_executable,
        executable_policy=authority["codexExecutablePolicy"],
    )
    workload_verifier = KubernetesWorkloadVerifier(
        namespace=args.pod_namespace,
        pod_name=args.pod_name,
        pod_uid=args.pod_uid,
        service_account=authority["issuerRuntimePolicy"][
            "kubernetesServiceAccount"
        ],
        container_name=args.container_name,
        expected_image_digest=authority["issuerRuntimePolicy"]["issuerImageDigest"],
        expected_command=authority["issuerRuntimePolicy"]["kubernetesContainerCommand"],
        expected_args_sha256=authority["issuerRuntimePolicy"]["kubernetesContainerArgsSha256"],
        expected_security_context_sha256=authority["issuerRuntimePolicy"][
            "kubernetesContainerSecurityContextSha256"
        ],
        api_token_file=args.kubernetes_api_token_file,
        transport=KubernetesPodTransport(
            api_origin="https://kubernetes.default.svc",
            ca_file=args.kubernetes_ca_file,
        ),
    )
    if (
        args.pod_namespace
        != authority["issuerRuntimePolicy"]["kubernetesNamespace"]
        or args.container_name
        != authority["issuerRuntimePolicy"]["kubernetesContainerName"]
    ):
        reject(
            "PROVIDER_RUNTIME_WORKLOAD_MISMATCH",
            "runtime Pod arguments differ from public policy",
        )
    service = FixedRuntimeAttestorService(
        runtime_policy=authority["issuerRuntimePolicy"],
        trust_root_file=args.trust_root_file,
        expected_trust_root_sha256=authority["expectedTrustRootSha256"],
        revocations_file=args.revocations_file,
        authority_file=args.authority_file,
        authority_root=args.authority_file.resolve().parents[2],
        authorization_token_file=args.authorization_token_file,
        store=store,
        signer=signer,
        runner=runner,
        workload_verifier=workload_verifier,
        workspace=args.work_root,
    )
    server = make_runtime_server(args.listen, args.port, service)
    stopping = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
