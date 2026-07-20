"""Independent Kubernetes workload and image measurement for runtime signing."""

from __future__ import annotations

import os
import re
import ssl
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from scripts.github_apps.cross_ai_deployment_policy.errors import reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import loads_json_bytes


DIGEST = re.compile(r"sha256:[a-f0-9]{64}$")
K8S_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?$")
MAX_TOKEN_BYTES = 16384
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class PodTransport(Protocol):
    def get(self, *, path: str, token: str) -> bytes: ...


class KubernetesPodTransport:
    def __init__(self, *, api_origin: str, ca_file: Path) -> None:
        if api_origin != "https://kubernetes.default.svc":
            reject(
                "KUBERNETES_API_ORIGIN_INVALID",
                "runtime workload verification requires the in-cluster API origin",
            )
        context = ssl.create_default_context(cafile=str(ca_file))
        self.origin = api_origin
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
        )

    def get(self, *, path: str, token: str) -> bytes:
        request = urllib.request.Request(
            self.origin + path,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "acik-cross-ai-runtime-attestor/1",
            },
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200 or response.geturl() != request.full_url:
                    raise ValueError("Kubernetes API rejected workload query")
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, ValueError, urllib.error.URLError):
            reject(
                "KUBERNETES_WORKLOAD_UNAVAILABLE",
                "runtime workload identity cannot be queried",
            )
        if len(body) > MAX_RESPONSE_BYTES:
            reject(
                "KUBERNETES_WORKLOAD_INVALID",
                "runtime workload response is oversized",
            )
        return body


def _projected_token(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        reject(
            "KUBERNETES_WORKLOAD_TOKEN_UNAVAILABLE",
            "projected Kubernetes API token cannot be opened",
        )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o027
            or not 100 <= metadata.st_size <= MAX_TOKEN_BYTES
        ):
            reject(
                "KUBERNETES_WORKLOAD_TOKEN_INVALID",
                "projected Kubernetes API token is not bounded read-only material",
            )
        raw = os.read(descriptor, metadata.st_size + 1)
    except OSError:
        reject(
            "KUBERNETES_WORKLOAD_TOKEN_UNAVAILABLE",
            "projected Kubernetes API token cannot be read",
        )
    finally:
        os.close(descriptor)
    token = raw.strip()
    if len(raw) != metadata.st_size or not 100 <= len(token) <= MAX_TOKEN_BYTES:
        reject(
            "KUBERNETES_WORKLOAD_TOKEN_INVALID",
            "projected Kubernetes API token changed or is invalid",
        )
    try:
        return token.decode("ascii")
    except UnicodeDecodeError:
        reject(
            "KUBERNETES_WORKLOAD_TOKEN_INVALID",
            "projected Kubernetes API token must be ASCII",
        )


@dataclass(frozen=True)
class WorkloadMeasurement:
    workload_identity: str
    image_digest: str
    pod_uid: str


class KubernetesWorkloadVerifier:
    def __init__(
        self,
        *,
        namespace: str,
        pod_name: str,
        pod_uid: str,
        service_account: str,
        container_name: str,
        api_token_file: Path,
        transport: PodTransport,
    ) -> None:
        try:
            canonical_uid = str(UUID(pod_uid))
        except (ValueError, AttributeError):
            reject("KUBERNETES_WORKLOAD_INVALID", "pod UID is invalid")
        if (
            canonical_uid != pod_uid
            or any(
                not isinstance(value, str) or K8S_NAME.fullmatch(value) is None
                for value in (namespace, pod_name, service_account, container_name)
            )
        ):
            reject("KUBERNETES_WORKLOAD_INVALID", "pod binding is invalid")
        self.namespace = namespace
        self.pod_name = pod_name
        self.pod_uid = pod_uid
        self.service_account = service_account
        self.container_name = container_name
        self.api_token_file = api_token_file
        self.transport = transport

    def measure(self) -> WorkloadMeasurement:
        path = (
            f"/api/v1/namespaces/{quote(self.namespace, safe='')}/pods/"
            f"{quote(self.pod_name, safe='')}"
        )
        pod = loads_json_bytes(
            self.transport.get(
                path=path,
                token=_projected_token(self.api_token_file),
            ),
            max_bytes=MAX_RESPONSE_BYTES,
            label="Kubernetes Pod",
        )
        metadata = pod.get("metadata") if isinstance(pod, dict) else None
        spec = pod.get("spec") if isinstance(pod, dict) else None
        status = pod.get("status") if isinstance(pod, dict) else None
        statuses = status.get("containerStatuses") if isinstance(status, dict) else None
        matches = (
            [
                item
                for item in statuses
                if isinstance(item, dict) and item.get("name") == self.container_name
            ]
            if isinstance(statuses, list)
            else []
        )
        container = matches[0] if len(matches) == 1 else None
        image_id = container.get("imageID") if isinstance(container, dict) else None
        digest_match = DIGEST.search(image_id) if isinstance(image_id, str) else None
        if (
            not isinstance(metadata, dict)
            or metadata.get("name") != self.pod_name
            or metadata.get("namespace") != self.namespace
            or metadata.get("uid") != self.pod_uid
            or metadata.get("deletionTimestamp") is not None
            or not isinstance(spec, dict)
            or spec.get("serviceAccountName") != self.service_account
            or not isinstance(status, dict)
            or status.get("phase") != "Running"
            or not isinstance(container, dict)
            or container.get("ready") is not True
            or not isinstance(container.get("state"), dict)
            or not isinstance(container["state"].get("running"), dict)
            or digest_match is None
        ):
            reject(
                "KUBERNETES_WORKLOAD_INVALID",
                "running Pod identity or immutable image measurement is invalid",
            )
        return WorkloadMeasurement(
            workload_identity=(
                f"spiffe://testai.acik.com/ns/{self.namespace}/sa/"
                f"{self.service_account}"
            ),
            image_digest=digest_match.group(0),
            pod_uid=self.pod_uid,
        )


__all__ = [
    "KubernetesPodTransport",
    "KubernetesWorkloadVerifier",
    "WorkloadMeasurement",
]
