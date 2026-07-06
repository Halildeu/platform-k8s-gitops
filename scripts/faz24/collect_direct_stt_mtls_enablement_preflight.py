#!/usr/bin/env python3
"""Collect Faz 24 direct-STT mTLS enablement preflight evidence.

The collector is intentionally metadata-only. It reads Kubernetes object shape,
Secret key names, and a bounded HTTP status/timing probe from the real
audio-gateway pod. It never emits Secret values, PEM material, tokens, raw
command output, audio, transcript text, or destination URLs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "faz24.directSttMtlsEnablementPreflight.v1"
DEFAULT_CONTEXT = "k3d-test"
DEFAULT_NAMESPACE = "platform-test"
DEFAULT_DEPLOYMENT = "audio-gateway"
DEFAULT_CONFIGMAP = "audio-gateway-config"
DEFAULT_AGGREGATE_EXTERNAL_SECRET = "audio-gateway-secrets"
DEFAULT_AGGREGATE_SECRET = "audio-gateway-secrets"
DEFAULT_EXTERNAL_SECRET = "audio-gateway-direct-stt-mtls"
DEFAULT_SECRET = "audio-gateway-direct-stt-mtls"
DEFAULT_NETPOL = "allow-audio-gateway-egress-live-stt-mtls"
DEFAULT_SECRET_STORE = "vault-platform-gitops"
DEFAULT_VAULT_PATH = "kv/platform/audio-gateway-service"
EXPECTED_TRANSCRIBE_HOST = "live-stt.denetim"
EXPECTED_TRANSCRIBE_PORT = 8243
EXPECTED_HOST_ALIAS_IP = "10.99.0.2"
EXPECTED_NETPOL_CIDR = "10.99.0.2/32"
EXPECTED_MTLS_MOUNT = "/etc/direct-stt-mtls"
EXPECTED_MTLS_FILES = {
    "ca": "/etc/direct-stt-mtls/direct-stt-ca.crt",
    "cert": "/etc/direct-stt-mtls/direct-stt-client.crt",
    "key": "/etc/direct-stt-mtls/direct-stt-client.key",
}
REQUIRED_VAULT_PROPERTIES = {
    "direct_stt_ca_crt",
    "direct_stt_client_crt",
    "direct_stt_client_key",
}
REQUIRED_SECRET_KEYS = {
    "direct-stt-ca.crt",
    "direct-stt-client.crt",
    "direct-stt-client.key",
}
AGGREGATE_SECRET_KEYS = {"SPRING_DATA_REDIS_PASSWORD"}
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"sha256:([0-9a-f]{64})")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_CONDITION_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{0,160}$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], CommandResult]


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def run_command(argv: list[str], timeout: int = 30) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(127, "", "command-not-found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timeout")
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def load_json(result: CommandResult, name: str) -> tuple[Any | None, str | None]:
    if result.returncode != 0:
        return None, f"{name}:command-exit-{result.returncode}"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, f"{name}:invalid-json"


def kget(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    kind: str,
    name: str | None,
    timeout: int = 30,
) -> tuple[Any | None, str | None]:
    argv = ["kubectl", "--context", context, "-n", namespace, "get", kind]
    if name:
        argv.append(name)
    argv.extend(["-o", "json"])
    return load_json(runner(argv, timeout), f"kubectl-get-{kind}-{name or 'list'}")


def kube_access_status(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    timeout: int = 10,
) -> tuple[bool, bool, str | None]:
    context_result = runner(
        ["kubectl", "config", "get-contexts", context, "-o", "name"],
        timeout,
    )
    if context_result.returncode != 0 or context_result.stdout.strip() != context:
        return False, False, f"kubectl-context-{context}-missing"

    namespace_result = runner(
        ["kubectl", "--context", context, "get", "namespace", namespace, "-o", "json"],
        timeout,
    )
    if namespace_result.returncode != 0:
        return True, False, f"kubectl-namespace-{namespace}:command-exit-{namespace_result.returncode}"
    return True, True, None


def kget_secret_key_names(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    name: str,
    timeout: int = 30,
) -> tuple[set[str], str | None]:
    # Do not pull Secret JSON into this process. kubectl still reads the object
    # from the API server, but the collector receives key names only.
    template = '{{range $k, $_ := .data}}{{printf "%s\\n" $k}}{{end}}'
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "secret",
            name,
            "-o",
            f"go-template={template}",
        ],
        timeout,
    )
    if result.returncode != 0:
        return set(), f"kubectl-get-secret-{name}:command-exit-{result.returncode}"
    keys = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return keys, None


def git_commit(runner: CommandRunner, override: str | None) -> str:
    if override:
        return override
    result = runner(["git", "rev-parse", "HEAD"], 10)
    value = result.stdout.strip()
    return value if result.returncode == 0 and GIT_SHA_RE.match(value) else ""


def container_from_pod(pod: dict[str, Any], name: str) -> dict[str, Any]:
    statuses = pod.get("status", {}).get("containerStatuses", [])
    for status in statuses:
        if status.get("name") == name:
            return status
    return {}


def find_audio_gateway_pod(pods: dict[str, Any], deployment: str) -> dict[str, Any] | None:
    items = pods.get("items", []) if isinstance(pods, dict) else []
    matching: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for pod in items:
        if not isinstance(pod, dict):
            continue
        labels = pod.get("metadata", {}).get("labels", {})
        if labels.get("app.kubernetes.io/name") != deployment:
            continue
        matching.append(pod)
        status = container_from_pod(pod, deployment)
        if pod.get("status", {}).get("phase") == "Running" and status.get("ready") is True:
            candidates.append(pod)
    if candidates:
        candidates.sort(key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""))
        return candidates[-1]
    if matching:
        matching.sort(key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""))
        return matching[-1]
    return None


def image_digest_hex(pod: dict[str, Any]) -> str:
    status = container_from_pod(pod, DEFAULT_DEPLOYMENT)
    for value in [status.get("imageID"), status.get("image")]:
        if isinstance(value, str):
            match = SHA256_RE.search(value)
            if match:
                return match.group(1)
    return ""


def pod_ready(pod: dict[str, Any] | None) -> bool:
    if not pod:
        return False
    status = container_from_pod(pod, DEFAULT_DEPLOYMENT)
    return pod.get("status", {}).get("phase") == "Running" and status.get("ready") is True


def external_secret_ready(external_secret: dict[str, Any] | None) -> bool:
    if not isinstance(external_secret, dict):
        return False
    conditions = external_secret.get("status", {}).get("conditions", [])
    for condition in conditions:
        if condition.get("type") == "Ready" and condition.get("status") == "True":
            return True
    return False


def external_secret_mappings(
    external_secret: dict[str, Any] | None,
) -> tuple[set[str], set[str], set[str]]:
    if not isinstance(external_secret, dict):
        return set(), set(), set()
    data = external_secret.get("spec", {}).get("data", [])
    properties: set[str] = set()
    keys: set[str] = set()
    vault_paths: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if isinstance(item.get("secretKey"), str):
            keys.add(item["secretKey"])
        remote = item.get("remoteRef", {})
        if isinstance(remote.get("key"), str):
            vault_paths.add(remote["key"])
        if isinstance(remote.get("property"), str):
            properties.add(remote["property"])
    return properties, keys, vault_paths


def external_secret_store(external_secret: dict[str, Any] | None) -> str:
    if not isinstance(external_secret, dict):
        return ""
    return external_secret.get("spec", {}).get("secretStoreRef", {}).get("name", "")


def safe_condition_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    if "\n" in value or "\r" in value or not SAFE_CONDITION_VALUE_RE.match(value):
        return "redacted-unsafe-value"
    return value


def external_secret_conditions(external_secret: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(external_secret, dict):
        return []
    conditions = external_secret.get("status", {}).get("conditions", [])
    if not isinstance(conditions, list):
        return []

    diagnostics: list[dict[str, Any]] = []
    for condition in conditions[:6]:
        if not isinstance(condition, dict):
            continue
        message = condition.get("message")
        message_text = message if isinstance(message, str) else ""
        diagnostics.append(
            {
                "type": safe_condition_value(condition.get("type")),
                "status": safe_condition_value(condition.get("status")),
                "reason": safe_condition_value(condition.get("reason")),
                "lastTransitionTime": safe_condition_value(condition.get("lastTransitionTime")),
                "messagePresent": bool(message_text),
                "messageLength": min(len(message_text), 20000),
                "messageIncluded": False,
            }
        )
    return diagnostics


def host_alias_ip(deployment: dict[str, Any] | None, hostname: str) -> str:
    host_aliases = (
        deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("hostAliases", [])
        if isinstance(deployment, dict)
        else []
    )
    for item in host_aliases:
        if hostname in item.get("hostnames", []):
            return str(item.get("ip", ""))
    return ""


def mtls_mount_info(deployment: dict[str, Any] | None, mount_path: str) -> tuple[bool, str, bool | None]:
    pod_spec = (
        deployment.get("spec", {}).get("template", {}).get("spec", {})
        if isinstance(deployment, dict)
        else {}
    )
    containers = pod_spec.get("containers", []) if isinstance(pod_spec, dict) else []
    mount_name = ""
    for container in containers:
        if container.get("name") != DEFAULT_DEPLOYMENT:
            continue
        for mount in container.get("volumeMounts", []):
            if mount.get("mountPath") == mount_path and mount.get("readOnly") is True:
                mount_name = str(mount.get("name", ""))
                break
    if not mount_name:
        return False, "", None
    for volume in pod_spec.get("volumes", []) if isinstance(pod_spec, dict) else []:
        if volume.get("name") != mount_name:
            continue
        secret = volume.get("secret", {})
        return True, str(secret.get("secretName", "")), bool(secret.get("optional", False))
    return True, "", None


def secret_referenced_by_env_from(deployment: dict[str, Any] | None, secret_name: str) -> bool:
    containers = (
        deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if isinstance(deployment, dict)
        else []
    )
    for container in containers:
        if container.get("name") != DEFAULT_DEPLOYMENT:
            continue
        for item in container.get("envFrom", []):
            if item.get("secretRef", {}).get("name") == secret_name:
                return True
    return False


def config_direct_stt_enabled(configmap: dict[str, Any] | None) -> bool | None:
    value = (
        configmap.get("data", {}).get("AUDIO_GATEWAY_DIRECT_STT_ENABLED")
        if isinstance(configmap, dict)
        else None
    )
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def network_policy_target(netpol: dict[str, Any] | None) -> tuple[str, int | None]:
    if not isinstance(netpol, dict):
        return "", None
    for egress in netpol.get("spec", {}).get("egress", []):
        cidr = ""
        for target in egress.get("to", []):
            cidr = target.get("ipBlock", {}).get("cidr", "") or cidr
        for port in egress.get("ports", []):
            if cidr:
                return cidr, port.get("port")
    return "", None


def run_mtls_probe(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    pod_name: str,
    timeout: int,
) -> tuple[int | None, int | None, bool, str | None]:
    if not pod_name:
        return None, None, False, "pod-not-found"
    script = (
        "if ! command -v curl >/dev/null 2>&1; then echo curl-missing; exit 90; fi; "
        "curl -sS --output /dev/null --write-out '%{http_code} %{time_total}' "
        "--connect-timeout 5 --max-time 30 "
        f"--cacert {EXPECTED_MTLS_FILES['ca']} "
        f"--cert {EXPECTED_MTLS_FILES['cert']} "
        f"--key {EXPECTED_MTLS_FILES['key']} "
        f"https://{EXPECTED_TRANSCRIBE_HOST}:{EXPECTED_TRANSCRIBE_PORT}/health"
    )
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "exec",
            pod_name,
            "-c",
            DEFAULT_DEPLOYMENT,
            "--",
            "sh",
            "-c",
            script,
        ],
        timeout,
    )
    if result.returncode != 0:
        return None, None, False, f"mtls-probe-exit-{result.returncode}"
    match = re.search(r"\b(\d{3})\s+([0-9.]+)\b", result.stdout)
    if not match:
        return None, None, False, "mtls-probe-unparseable"
    status = int(match.group(1))
    total_ms = max(1, int(float(match.group(2)) * 1000))
    return status, total_ms, True, None


def build_evidence(
    *,
    runner: CommandRunner = run_command,
    context: str = DEFAULT_CONTEXT,
    namespace: str = DEFAULT_NAMESPACE,
    deployment_name: str = DEFAULT_DEPLOYMENT,
    gitops_commit_override: str | None = None,
    probe_timeout: int = 40,
) -> dict[str, Any]:
    failures: list[str] = []
    context_available, namespace_reachable, access_error = kube_access_status(
        runner,
        context=context,
        namespace=namespace,
    )
    if access_error:
        failures.append(access_error)

    deployment = None
    configmap = None
    aggregate_external_secret = None
    aggregate_runtime_keys: set[str] = set()
    external_secret = None
    runtime_keys: set[str] = set()
    netpol = None
    pods: dict[str, Any] = {}
    pod = None
    if context_available and namespace_reachable:
        deployment, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="deployment",
            name=deployment_name,
        )
        if error:
            failures.append(error)
        configmap, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="configmap",
            name=DEFAULT_CONFIGMAP,
        )
        if error:
            failures.append(error)
        aggregate_external_secret, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="externalsecret",
            name=DEFAULT_AGGREGATE_EXTERNAL_SECRET,
        )
        if error:
            failures.append(error)
        aggregate_runtime_keys, error = kget_secret_key_names(
            runner,
            context=context,
            namespace=namespace,
            name=DEFAULT_AGGREGATE_SECRET,
        )
        if error:
            failures.append(error)
        external_secret, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="externalsecret",
            name=DEFAULT_EXTERNAL_SECRET,
        )
        if error:
            failures.append(error)
        runtime_keys, error = kget_secret_key_names(
            runner,
            context=context,
            namespace=namespace,
            name=DEFAULT_SECRET,
        )
        if error:
            failures.append(error)
        netpol, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="networkpolicy",
            name=DEFAULT_NETPOL,
        )
        if error:
            failures.append(error)
        pods, error = kget(
            runner,
            context=context,
            namespace=namespace,
            kind="pods",
            name=None,
        )
        if error:
            failures.append(error)
        pod = find_audio_gateway_pod(pods or {}, deployment_name)
    pod_name = pod.get("metadata", {}).get("name", "") if isinstance(pod, dict) else ""
    if context_available and namespace_reachable:
        health_status, total_ms, client_cert_used, probe_error = run_mtls_probe(
            runner,
            context=context,
            namespace=namespace,
            pod_name=pod_name,
            timeout=probe_timeout,
        )
    else:
        health_status, total_ms, client_cert_used, probe_error = None, None, False, None
    if probe_error:
        failures.append(probe_error)

    mapped_properties, target_keys, vault_paths = external_secret_mappings(external_secret)
    _aggregate_properties, aggregate_target_keys, _aggregate_vault_paths = external_secret_mappings(
        aggregate_external_secret
    )
    secret_store = external_secret_store(external_secret)
    vault_path = next(iter(vault_paths)) if len(vault_paths) == 1 else ""
    netpol_cidr, netpol_port = network_policy_target(netpol)
    host_ip = host_alias_ip(deployment, EXPECTED_TRANSCRIBE_HOST)
    direct_stt_enabled = config_direct_stt_enabled(configmap)
    mount_present, mtls_secret_name, mtls_secret_optional = mtls_mount_info(
        deployment, EXPECTED_MTLS_MOUNT
    )
    gitops_commit = git_commit(runner, gitops_commit_override)
    backend_image_digest = image_digest_hex(pod or {})
    file_like_keys_not_exported_as_env = REQUIRED_SECRET_KEYS.issubset(runtime_keys) and all(
        ENV_NAME_RE.match(key) is None for key in REQUIRED_SECRET_KEYS
    )
    dedicated_secret_not_env_from = not secret_referenced_by_env_from(deployment, DEFAULT_SECRET)

    readiness_failures = [
        ("source-gitops-commit-invalid", GIT_SHA_RE.match(gitops_commit) is None),
    ]
    if context_available and namespace_reachable:
        readiness_failures.extend(
            [
                ("source-backend-image-digest-missing", not backend_image_digest),
                ("pod-not-ready", not pod_ready(pod)),
                ("direct-stt-not-disabled", direct_stt_enabled is not False),
                ("host-alias-mismatch", host_ip != EXPECTED_HOST_ALIAS_IP),
                (
                    "network-policy-mismatch",
                    netpol_cidr != EXPECTED_NETPOL_CIDR
                    or netpol_port != EXPECTED_TRANSCRIBE_PORT,
                ),
                ("mtls-mount-missing", not mount_present),
                ("mtls-secret-name-mismatch", mtls_secret_name != DEFAULT_SECRET),
                ("mtls-secret-not-optional", mtls_secret_optional is not True),
                ("mtls-secret-envfrom-risk", not dedicated_secret_not_env_from),
                ("aggregate-external-secret-not-ready", not external_secret_ready(aggregate_external_secret)),
                (
                    "aggregate-secret-target-redis-key-missing",
                    not AGGREGATE_SECRET_KEYS.issubset(aggregate_target_keys),
                ),
                (
                    "aggregate-secret-runtime-redis-key-missing",
                    not AGGREGATE_SECRET_KEYS.issubset(aggregate_runtime_keys),
                ),
                (
                    "aggregate-secret-direct-stt-contamination",
                    bool(REQUIRED_SECRET_KEYS & aggregate_runtime_keys)
                    or bool(REQUIRED_SECRET_KEYS & aggregate_target_keys),
                ),
                ("external-secret-not-ready", not external_secret_ready(external_secret)),
                ("external-secret-store-mismatch", secret_store != DEFAULT_SECRET_STORE),
                ("external-secret-vault-path-mismatch", vault_paths != {DEFAULT_VAULT_PATH}),
                ("external-secret-mapping-missing", not REQUIRED_VAULT_PROPERTIES.issubset(mapped_properties)),
                ("external-secret-target-key-missing", not REQUIRED_SECRET_KEYS.issubset(target_keys)),
                ("runtime-secret-key-missing", not REQUIRED_SECRET_KEYS.issubset(runtime_keys)),
                ("mtls-health-not-200", health_status != 200),
            ]
        )
    failures.extend(code for code, failed in readiness_failures if failed)
    failures = sorted(set(failures))

    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "pass" if not failures else "fail",
        "issue": "platform-ai#182",
        "generatedAt": utc_now(),
        "failures": failures,
        "source": {
            "gitopsCommit": gitops_commit,
            "backendImageDigest": backend_image_digest,
        },
        "environment": {
            "cluster": context,
            "kubectlContext": context,
            "namespace": namespace,
            "deployment": deployment_name,
            "podName": pod_name,
            "podReady": pod_ready(pod),
            "contextAvailable": context_available,
            "namespaceReachable": namespace_reachable,
            "contextFailure": access_error or "",
        },
        "desiredState": {
            "directSttEnabled": direct_stt_enabled,
            "transcribeHost": EXPECTED_TRANSCRIBE_HOST,
            "transcribePort": EXPECTED_TRANSCRIBE_PORT,
            "hostAliasIp": host_ip,
            "networkPolicyCidr": netpol_cidr,
            "networkPolicyPort": netpol_port,
            "mtlsMountPath": EXPECTED_MTLS_MOUNT,
            "mtlsMountPresent": mount_present,
            "mtlsSecretName": mtls_secret_name,
            "mtlsSecretOptional": mtls_secret_optional,
        },
        "externalSecret": {
            "name": DEFAULT_EXTERNAL_SECRET,
            "ready": external_secret_ready(external_secret),
            "secretStore": secret_store,
            "vaultPath": vault_path,
            "mappedVaultProperties": sorted(mapped_properties),
            "targetSecretKeys": sorted(target_keys),
            "conditions": external_secret_conditions(external_secret),
            "secretValueIncluded": False,
        },
        "aggregateSecret": {
            "name": DEFAULT_AGGREGATE_SECRET,
            "ready": external_secret_ready(aggregate_external_secret),
            "targetSecretKeys": sorted(aggregate_target_keys),
            "runtimeKeyNames": sorted(aggregate_runtime_keys),
            "directSttKeysPresent": bool(
                REQUIRED_SECRET_KEYS & aggregate_runtime_keys
                or REQUIRED_SECRET_KEYS & aggregate_target_keys
            ),
            "secretValueIncluded": False,
        },
        "runtimeSecret": {
            "name": DEFAULT_SECRET,
            "keyNames": sorted(runtime_keys),
            "secretValueIncluded": False,
            "fileLikeKeysNotExportedAsEnv": file_like_keys_not_exported_as_env,
            "dedicatedSecretNotEnvFrom": dedicated_secret_not_env_from,
        },
        "mtlsProbe": {
            "fromRealPod": bool(pod_name),
            "host": EXPECTED_TRANSCRIBE_HOST,
            "port": EXPECTED_TRANSCRIBE_PORT,
            "clientCertificateUsed": client_cert_used,
            "healthHttpStatus": health_status,
            "totalMs": total_ms,
            "secretValueIncluded": False,
        },
        "boundaries": {
            "vaultSeedAuthorityAccepted": REQUIRED_SECRET_KEYS.issubset(runtime_keys),
            "secretValuesIncluded": False,
            "directSttEnabled": False,
            "rawAudioSent": False,
            "transcribeCalled": False,
            "directAudioE2eProven": False,
            "i7ProdGateProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
    }
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--deployment", default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--gitops-commit", help="Override source.gitopsCommit")
    parser.add_argument("--probe-timeout", type=int, default=40)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path for metadata-only preflight evidence JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = build_evidence(
        context=args.context,
        namespace=args.namespace,
        deployment_name=args.deployment,
        gitops_commit_override=args.gitops_commit,
        probe_timeout=args.probe_timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if evidence["status"] != "pass":
        failure_count = len(evidence.get("failures", []))
        print(
            "direct-STT mTLS preflight collection produced fail evidence "
            f"({failure_count} failure codes); inspect metadata JSON",
            file=sys.stderr,
        )
        return 1
    print(f"direct-STT mTLS preflight evidence written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
