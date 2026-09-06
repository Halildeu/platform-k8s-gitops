#!/usr/bin/env python3
"""Verify exact rendered Faz 24 finalization secret and activation bindings."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load(path: str) -> list[dict[str, Any]]:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return [doc for doc in yaml.safe_load_all(stream) if isinstance(doc, dict)]
    except OSError as error:
        fail(f"cannot read rendered YAML {path}: {error}")
    except yaml.YAMLError as error:
        marker = getattr(error, "problem_mark", None)
        fail(f"rendered YAML is invalid: {marker or error}")


def resource(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    matches = [
        doc
        for doc in docs
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name
    ]
    if len(matches) != 1:
        fail(f"expected one rendered {kind}/{name}, got {len(matches)}")
    return matches[0]


def external_secret_binding(
    manifest: dict[str, Any], secret_key: str, vault_key: str, property_name: str
) -> None:
    matches = [
        item
        for item in manifest.get("spec", {}).get("data", [])
        if item.get("secretKey") == secret_key
    ]
    if len(matches) != 1:
        fail(
            f"expected one ExternalSecret binding for {secret_key}, got {len(matches)}"
        )
    remote = matches[0].get("remoteRef", {})
    if remote.get("key") != vault_key or remote.get("property") != property_name:
        fail(
            f"{secret_key} must bind {vault_key}:{property_name}, got "
            f"{remote.get('key')}:{remote.get('property')}"
        )


def external_secret_target(manifest: dict[str, Any], expected: str) -> str:
    target = manifest.get("spec", {}).get("target", {}).get("name")
    if target != expected:
        fail(f"ExternalSecret target must be {expected}, got {target}")
    return target


def container_env(
    manifest: dict[str, Any], container_name: str, env_name: str
) -> dict[str, Any]:
    containers = (
        manifest.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    containers = [item for item in containers if item.get("name") == container_name]
    if len(containers) != 1:
        fail(f"expected one container {container_name}, got {len(containers)}")
    matches = [
        item for item in containers[0].get("env", []) if item.get("name") == env_name
    ]
    if len(matches) != 1:
        fail(
            f"expected one env binding {container_name}/{env_name}, got {len(matches)}"
        )
    return matches[0]


def required_secret_env(
    manifest: dict[str, Any],
    container_name: str,
    env_name: str,
    secret_name: str,
    secret_key: str,
    optional: bool = False,
) -> None:
    ref = (
        container_env(manifest, container_name, env_name)
        .get("valueFrom", {})
        .get("secretKeyRef", {})
    )
    if (
        ref.get("name") != secret_name
        or ref.get("key") != secret_key
        or ref.get("optional") is not optional
    ):
        fail(
            f"{container_name}/{env_name} must bind "
            f"{secret_name}:{secret_key} with optional={str(optional).lower()}"
        )


def bounded_rollout(manifest: dict[str, Any], name: str) -> None:
    """The Faz 24 chain must roll terminate-first, within a bounded deadline.

    This asserted surge=1/unavailable=0 until 2026-07-31. That came from the
    2026-07-17 exception, which was explicitly conditional on a live preflight
    showing room for the surge pods. On 2026-07-31 the room was gone —
    platform-quota limits.cpu 15450m/16000m against a 750m pod — and the
    auth-service rollout could not create a pod at all:

        Error creating: pods "auth-service-…" is forbidden: exceeded quota:
        platform-quota, requested: limits.cpu=750m, used: 15450m, limited: 16

    So the guard now pins the opposite, and for the same underlying reason it
    was written: a rollout of this chain must be able to *complete*. Surge-first
    only completes while spare budget happens to exist; terminate-first needs
    none. The deadline stays — it still bounds a stall from any other cause.

    The namespace-wide form of this invariant (every Deployment at or above
    400m limits.cpu renders maxSurge 0) lives in
    tests/deploy/test_test_overlay_rollout_fits_quota.py.
    """
    spec = manifest.get("spec", {})
    rolling = spec.get("strategy", {}).get("rollingUpdate", {})
    if (
        rolling.get("maxSurge") != 0
        or rolling.get("maxUnavailable") != 1
        or spec.get("progressDeadlineSeconds") != 300
    ):
        fail(f"{name} must render surge=0, unavailable=1, deadline=300")


def sync_wave(manifest: dict[str, Any], expected: str) -> None:
    actual = (
        manifest.get("metadata", {})
        .get("annotations", {})
        .get("argocd.argoproj.io/sync-wave")
    )
    if str(actual) != expected:
        kind = manifest.get("kind", "resource")
        name = manifest.get("metadata", {}).get("name", "unknown")
        fail(f"{kind}/{name} sync-wave must be {expected}, got {actual}")


def container_image(
    manifest: dict[str, Any], container_name: str, expected: str
) -> None:
    containers = (
        manifest.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    matches = [item for item in containers if item.get("name") == container_name]
    if len(matches) != 1 or matches[0].get("image") != expected:
        actual = matches[0].get("image") if len(matches) == 1 else None
        fail(f"{container_name} image must be {expected}, got {actual}")


def pod_annotation(manifest: dict[str, Any], annotation: str, expected: str) -> None:
    actual = (
        manifest.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("annotations", {})
        .get(annotation)
    )
    if actual != expected:
        name = manifest.get("metadata", {}).get("name", "unknown")
        fail(f"Deployment/{name} annotation {annotation} must be {expected}")


def reject_prod_leakage(
    prod_docs: list[dict[str, Any]], prod_eso_docs: list[dict[str, Any]]
) -> None:
    all_docs = prod_docs + prod_eso_docs
    forbidden_resource = [
        doc
        for doc in all_docs
        if doc.get("kind") == "ExternalSecret"
        and doc.get("metadata", {}).get("name")
        == "auth-service-transcript-service-secret"
    ]
    if forbidden_resource:
        fail("test-only transcript auth ExternalSecret leaked into prod render")

    forbidden_config_keys = {
        "meeting-service-config": {
            "MEETING_AUTHZ_LEGACY_USER_ID_DUAL_WRITE_ENABLED",
            "MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS",
            "MEETING_REDIS_HOST",
            "MEETING_REDIS_PORT",
            "MEETING_REDIS_HEALTH_ENABLED",
            "MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE",
            "MEETING_EVENTS_REDIS_ENABLED",
            "MEETING_EVENTS_OUTBOX_POLLER_ENABLED",
        },
        "transcript-service-config": {
            "TRANSCRIPT_REDIS_HOST",
            "TRANSCRIPT_REDIS_PORT",
            "TRANSCRIPT_REDIS_HEALTH_ENABLED",
            "MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE",
            "TRANSCRIPT_MEETING_SESSION_RESOLVER_ENABLED",
            "TRANSCRIPT_MEETING_SERVICE_BASE_URL",
            "TRANSCRIPT_MEETING_SERVICE_TOKEN_URL",
            "TRANSCRIPT_MEETING_SERVICE_CLIENT_ID",
            "TRANSCRIPT_RECORDING_FINISHED_CONSUMER_ENABLED",
            "TRANSCRIPT_FINALIZATION_WORKER_ENABLED",
            "TRANSCRIPT_MEETING_EVENTS_REDIS_ENABLED",
            "TRANSCRIPT_MEETING_EVENTS_OUTBOX_POLLER_ENABLED",
            "TRANSCRIPT_FINALIZATION_QUIESCENCE",
            "TRANSCRIPT_FINALIZATION_MIN_WAIT",
            "TRANSCRIPT_FINALIZATION_MAX_WAIT",
        },
    }
    for config_map in (doc for doc in prod_docs if doc.get("kind") == "ConfigMap"):
        name = config_map.get("metadata", {}).get("name", "unknown")
        leaked = forbidden_config_keys.get(str(name), set()).intersection(
            config_map.get("data", {}).keys()
        )
        if leaked:
            fail(
                f"test-only config keys leaked into prod ConfigMap/{name}: "
                f"{', '.join(sorted(leaked))}"
            )

    serialized = "\n".join(yaml.safe_dump(doc, sort_keys=True) for doc in all_docs)
    forbidden_fragments = {
        "plural test allow-list": "MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS",
        "meeting finalization transport": "MEETING_EVENTS_OUTBOX_POLLER_ENABLED",
        "transcript resolver": "TRANSCRIPT_MEETING_SESSION_RESOLVER_ENABLED",
        "transcript finalizer": "TRANSCRIPT_FINALIZATION_WORKER_ENABLED",
        "transcript issuer secret": "SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET",
        "transcript meeting client secret env": (
            "TRANSCRIPT_MEETING_SERVICE_CLIENT_SECRET"
        ),
        "transcript meeting client secret Vault property": (
            "service_client_transcript_service_secret"
        ),
        "analysis capability HMAC env": "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
        "analysis capability Vault path": "meeting-analysis-capability",
        "analysis capability Vault property": "hmac_secret_base64",
        "meeting rollout marker": "platform.acik.com/faz24-meeting-ai-base-url-rev",
        "transcript rollout marker": "transcript-service.acik.com/direct-stt-result-consumer-rev",
        "meeting test digest": "sha256:03378764b00ba1a08fd73fd18ddb3ed3bd7c2ecfaeb8903a9050c0830d6fd4a2",
        "transcript test digest": "sha256:1c36a94701d203b1191ff8f43179db0a5378175b2b205799c09e2ad04053d238",
        "auth test digest": "sha256:dfd6dc43085f7ee362de2f34b038129ebe931e5c7708082e70d6b10346a66abd",
        "audio test digest": "sha256:9c859cbbc3114ab8df5a3bde3305f86fa4de2b76305566333c21edf7617a4fac",
    }
    for label, fragment in forbidden_fragments.items():
        if fragment in serialized:
            fail(f"test-only {label} leaked into prod render")


def main() -> None:
    if len(sys.argv) != 5:
        fail(
            "usage: verify-faz24-finalization-rollout.py "
            "TEST_RENDER ESO_RENDER PROD_RENDER PROD_ESO_RENDER"
        )
    workload_docs = load(sys.argv[1])
    eso_docs = load(sys.argv[2])
    prod_docs = load(sys.argv[3])
    prod_eso_docs = load(sys.argv[4])

    auth_core = resource(workload_docs, "ExternalSecret", "auth-service-secrets")
    auth_transcript = resource(
        workload_docs, "ExternalSecret", "auth-service-transcript-service-secret"
    )
    meeting_eso = resource(eso_docs, "ExternalSecret", "meeting-service-secrets")
    meeting_capability_eso = resource(
        eso_docs, "ExternalSecret", "meeting-service-analysis-capability"
    )
    transcript_eso = resource(eso_docs, "ExternalSecret", "transcript-service-secrets")
    transcript_capability_eso = resource(
        eso_docs, "ExternalSecret", "transcript-service-analysis-capability"
    )
    audio_eso = resource(eso_docs, "ExternalSecret", "audio-gateway-secrets")

    secret_targets = {
        external_secret_target(
            auth_transcript, "auth-service-transcript-service-secret"
        ),
        external_secret_target(meeting_eso, "meeting-service-secrets"),
        external_secret_target(
            meeting_capability_eso, "meeting-service-analysis-capability"
        ),
        external_secret_target(transcript_eso, "transcript-service-secrets"),
        external_secret_target(
            transcript_capability_eso, "transcript-service-analysis-capability"
        ),
        external_secret_target(audio_eso, "audio-gateway-secrets"),
    }
    if len(secret_targets) != 6:
        fail("Faz 24 ExternalSecret target names must be distinct")

    core_keys = {
        item.get("secretKey") for item in auth_core.get("spec", {}).get("data", [])
    }
    if "SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET" in core_keys:
        fail("transcript-service issuer key leaked into core auth ExternalSecret")
    for manifest in (meeting_eso, transcript_eso):
        service_secret_keys = {
            item.get("secretKey")
            for item in manifest.get("spec", {}).get("data", [])
        }
        if "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET" in service_secret_keys:
            name = manifest.get("metadata", {}).get("name", "unknown")
            fail(f"analysis capability key must be isolated from {name}")

    external_secret_binding(
        auth_transcript,
        "SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET",
        "kv/platform/auth-service",
        "service_client_transcript_service_secret",
    )
    external_secret_binding(
        audio_eso,
        "SPRING_DATA_REDIS_PASSWORD",
        "kv/platform/audio-gateway-service",
        "redis_password",
    )
    external_secret_binding(
        meeting_eso,
        "MEETING_REDIS_PASSWORD",
        "kv/platform/meeting-service",
        "redis_password",
    )
    external_secret_binding(
        transcript_eso,
        "TRANSCRIPT_REDIS_PASSWORD",
        "kv/platform/audio-gateway-service",
        "redis_password",
    )
    external_secret_binding(
        transcript_eso,
        "TRANSCRIPT_MEETING_SERVICE_CLIENT_SECRET",
        "kv/platform/auth-service",
        "service_client_transcript_service_secret",
    )
    external_secret_binding(
        meeting_capability_eso,
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
        "kv/platform/meeting-analysis-capability",
        "hmac_secret_base64",
    )
    external_secret_binding(
        transcript_capability_eso,
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
        "kv/platform/meeting-analysis-capability",
        "hmac_secret_base64",
    )

    meeting_deploy = resource(workload_docs, "Deployment", "meeting-service")
    auth_deploy = resource(workload_docs, "Deployment", "auth-service")
    transcript_deploy = resource(workload_docs, "Deployment", "transcript-service")
    audio_deploy = resource(workload_docs, "Deployment", "audio-gateway")
    redis_service = resource(workload_docs, "Service", "redis-streams")
    redis_endpoints = resource(workload_docs, "Endpoints", "redis-streams")
    service_ports = redis_service.get("spec", {}).get("ports", [])
    endpoint_ports = [
        port
        for subset in redis_endpoints.get("subsets", [])
        for port in subset.get("ports", [])
    ]
    if not any(port.get("port") == 6379 for port in service_ports):
        fail("Service/redis-streams must expose port 6379")
    if not any(port.get("port") == 6379 for port in endpoint_ports):
        fail("Endpoints/redis-streams must resolve port 6379")
    bounded_rollout(auth_deploy, "auth-service")
    bounded_rollout(meeting_deploy, "meeting-service")
    bounded_rollout(transcript_deploy, "transcript-service")
    pod_annotation(
        meeting_deploy,
        "meeting-service.acik.com/analysis-capability-rev",
        "2026-07-29-3144-v1",
    )
    pod_annotation(
        transcript_deploy,
        "transcript-service.acik.com/analysis-capability-rev",
        "2026-07-29-3144-v1",
    )
    sync_wave(auth_deploy, "10")
    sync_wave(meeting_deploy, "20")
    sync_wave(transcript_deploy, "21")
    sync_wave(auth_transcript, "0")
    sync_wave(meeting_eso, "0")
    sync_wave(meeting_capability_eso, "0")
    sync_wave(transcript_eso, "0")
    sync_wave(transcript_capability_eso, "0")
    required_secret_env(
        meeting_deploy,
        "meeting-service",
        "MEETING_REDIS_PASSWORD",
        "meeting-service-secrets",
        "MEETING_REDIS_PASSWORD",
    )
    required_secret_env(
        meeting_deploy,
        "meeting-service",
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
        "meeting-service-analysis-capability",
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
    )
    required_secret_env(
        auth_deploy,
        "auth-service",
        "SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET",
        "auth-service-transcript-service-secret",
        "SERVICE_CLIENT_TRANSCRIPT_SERVICE_SECRET",
    )
    required_secret_env(
        transcript_deploy,
        "transcript-service",
        "TRANSCRIPT_REDIS_PASSWORD",
        "transcript-service-secrets",
        "TRANSCRIPT_REDIS_PASSWORD",
    )
    required_secret_env(
        transcript_deploy,
        "transcript-service",
        "TRANSCRIPT_MEETING_SERVICE_CLIENT_SECRET",
        "transcript-service-secrets",
        "TRANSCRIPT_MEETING_SERVICE_CLIENT_SECRET",
    )
    required_secret_env(
        transcript_deploy,
        "transcript-service",
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
        "transcript-service-analysis-capability",
        "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET",
    )

    meeting_config = resource(workload_docs, "ConfigMap", "meeting-service-config")
    transcript_config = resource(
        workload_docs, "ConfigMap", "transcript-service-config"
    )
    expected_meeting = {
        "MEETING_AUTHZ_LEGACY_USER_ID_DUAL_WRITE_ENABLED": "true",
        "MEETING_INTERNAL_SERVICE_JWT_CLIENT_ID": "meeting-ai,transcript-service",
        "MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS": "meeting-ai,transcript-service",
        "MEETING_REDIS_HOST": "redis-streams",
        "MEETING_REDIS_PORT": "6379",
        "MEETING_REDIS_HEALTH_ENABLED": "true",
        "MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE": "readinessState",
        "MEETING_EVENTS_REDIS_ENABLED": "true",
        "MEETING_EVENTS_OUTBOX_POLLER_ENABLED": "true",
    }
    expected_transcript = {
        "TRANSCRIPT_REDIS_HOST": "redis-streams",
        "TRANSCRIPT_REDIS_PORT": "6379",
        "TRANSCRIPT_REDIS_HEALTH_ENABLED": "true",
        "MANAGEMENT_ENDPOINT_HEALTH_GROUP_READINESS_INCLUDE": "readinessState,redis",
        "TRANSCRIPT_MEETING_SESSION_RESOLVER_ENABLED": "true",
        "TRANSCRIPT_MEETING_SERVICE_BASE_URL": "http://meeting-service:8097",
        "TRANSCRIPT_MEETING_SERVICE_TOKEN_URL": "http://auth-service:8088/oauth2/token",
        "TRANSCRIPT_MEETING_SERVICE_CLIENT_ID": "transcript-service",
        "TRANSCRIPT_RECORDING_FINISHED_CONSUMER_ENABLED": "true",
        "TRANSCRIPT_FINALIZATION_WORKER_ENABLED": "true",
        "TRANSCRIPT_MEETING_EVENTS_REDIS_ENABLED": "true",
        "TRANSCRIPT_MEETING_EVENTS_OUTBOX_POLLER_ENABLED": "true",
        "TRANSCRIPT_FINALIZATION_QUIESCENCE": "PT1M",
        "TRANSCRIPT_FINALIZATION_MIN_WAIT": "PT6M",
        "TRANSCRIPT_FINALIZATION_MAX_WAIT": "PT15M",
    }
    for key, value in expected_meeting.items():
        if meeting_config.get("data", {}).get(key) != value:
            fail(f"meeting-service-config {key} must be {value}")
    for key, value in expected_transcript.items():
        if transcript_config.get("data", {}).get(key) != value:
            fail(f"transcript-service-config {key} must be {value}")

    container_image(
        auth_deploy,
        "auth-service",
        # 2026-08-01 (gitops#3285): sha-43ab06d — the delivery-grant
        # allow-lists move inside a purpose, so `account_invite` can exist
        # without handing its client the MFA lane. `mfa_otp` resolves to
        # exactly the values it had, which the ten pre-existing grant tests
        # assert unchanged. The Faz 24 mint surface this verifier pins is a
        # different endpoint and is untouched.
        # 2026-08-29 (gitops#3507): sha-813e0d0 — meeting-service service
        # client gains the user-service audience with an audience-pinned
        # users:internal permission (platform-backend#1120); the Faz 24 mint
        # surface stays untouched.
        # 2026-09-03 (gitops#3537): sha-a41b5ce — meeting-service client also mints
        # notification-orchestrator / notify:intents:system (platform-backend#1128,
        # Görevler dilim-4b); the Faz 24 mint surface stays untouched.
        "ghcr.io/halildeu/platform-backend-auth-service@"
        "sha256:ffd2bff1d2fe62872cde8e14f7b9f7e3ef66d6debf2b5982f9f81dce7b30c7d8",
    )
    container_image(
        meeting_deploy,
        "meeting-service",
        # 2026-08-29 (gitops#3507): sha-813e0d0 — actions accept an optional
        # assigneeUserId resolved server-side to the stable KC subject; the
        # durable-finalization surface this verifier pins is untouched.
        # 2026-09-03 (gitops#3537): sha-a41b5ce — outbox poller delivers assignment
        # events to Notify as system intents (platform-backend#1128); the
        # durable-finalization surface this verifier pins is untouched.
        # 2026-09-04 (platform-backend#1024 slice 1): sha-7d8e198 — consent-bound
        # speechContextTerms on the meeting contract (platform-backend#1129); the
        # durable-finalization surface this verifier pins is untouched.
        "ghcr.io/halildeu/platform-backend-meeting-service@"
        "sha256:e11c77ab4c0f9f9b660f54ad0a831a66bb2a65c9bd58e6937f2bbd77ce33691d",
    )
    # The plural authorization expansion is valid only with the exact image
    # that implements it. Keeping both checks in one verifier makes a future
    # config-only or image-only change fail closed.
    if (
        meeting_config.get("data", {}).get("MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS")
        != "meeting-ai,transcript-service"
    ):
        fail("plural meeting client allow-list must match the pinned image contract")
    container_image(
        transcript_deploy,
        "transcript-service",
        # 2026-08-01 (backend#1058, gitops#2610): Flyway V13 and the entity
        # mapping require occurrence-bound analysis_run_id UUID NOT NULL.
        "ghcr.io/halildeu/platform-backend-transcript-service@"
        "sha256:3c4dd2b59217e2d0d400c378464ec84bc477be3d2be87e171907eecaae443e7f",
    )
    container_image(
        audio_deploy,
        "audio-gateway",
        # 2026-08-04 (backend#1101, gitops#3419 RT-5): superset of backend#1100
        # (configurable max_delay_mode, vendor-default flexible) which is a
        # superset of backend#1095
        # (bounded two-phase Speechmatics terminal drain; per-session
        # internal|speechmatics provider contract; fail-closed on disabled
        # providers, missing credentials, queue overflow, incomplete receipts
        # and terminal events). Adds configurable Speechmatics max_delay_mode
        # with the vendor-default "flexible" replacing the old hardcoded
        # "fixed", pairing with the overlay's max_delay 1.0 (gitops#3424) so
        # live finals commit fast without mid-word cuts.
        "platform-test-registry:5000/platform-backend-audio-gateway-service@"
        # 2026-09-03 (gitops#3486): sha-2f63a74 — platform-backend#1127 makes the
        # live-analyze window cumulative; the durable-finalization surface this
        # verifier pins is untouched.
        "sha256:94f3cc848ba64c7294649cef4245bbcd72ae29609dd8ddbaf75ad6eacaa89773",
    )
    pod_annotation(
        meeting_deploy,
        "platform.acik.com/faz24-meeting-ai-base-url-rev",
        "2026-07-18-2610",
    )
    pod_annotation(
        transcript_deploy,
        "transcript-service.acik.com/direct-stt-result-consumer-rev",
        "2026-07-29-2610-v6-transport-epoch",
    )
    pod_annotation(
        transcript_deploy,
        "transcript-service.acik.com/analysis-run-contract-rev",
        "2026-08-01-2610-v1",
    )
    reject_prod_leakage(prod_docs, prod_eso_docs)

    print("PASS: Faz 24 rendered finalization rollout contract")


if __name__ == "__main__":
    main()
