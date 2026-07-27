"""Reader + accessor for docs/operations/services.yaml.

Codex 019e2319 iter-3 AGREE — Single truth source. The 4 drift-gate fields
(workload_kind, runtime_class, probe_contract, jvm_warmup_extra) extend the
existing service catalog rather than introducing a second YAML.

Loader exposes:
  Service        — dataclass with all relevant fields per service entry.
  ServicesCatalog — collection with `enabled_in(env)` / lookup helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


VALID_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "Job", "external"}
# `third-party` is a vendor daemon we run but do not build: it exposes no HTTP
# health surface of ours and brings its own readiness model. The probe-contract
# table already names this case (see probe_contract_rules — `exempt` covers
# "third-party with own readiness model"); the runtime vocabulary simply had no
# word for it, which would force such a workload to be mislabelled a lab tool.
VALID_RUNTIME_CLASSES = {
    "spring-backend",
    "nginx",
    "openfga",
    "job",
    "lab-tool",
    "third-party",
}
VALID_PROBE_CONTRACTS = {"spring-actuator", "http-healthz", "exempt"}
VALID_ENV_STATES = {"enabled", "deferred", "disabled"}


@dataclass(frozen=True)
class Service:
    name: str
    workload_kind: str
    runtime_class: str
    probe_contract: str
    jvm_warmup_extra: bool = False
    environments: dict[str, str] = field(default_factory=dict)
    third_party: bool = False
    jwt_validates: bool = True
    image_digest_required: dict[str, bool] = field(default_factory=dict)

    def is_enabled_in(self, env: str) -> bool:
        return self.environments.get(env) == "enabled"

    def is_deferred_in(self, env: str) -> bool:
        return self.environments.get(env) == "deferred"

    def is_disabled_in(self, env: str) -> bool:
        return self.environments.get(env) == "disabled"

    def requires_image_digest_in(self, env: str) -> bool:
        return self.image_digest_required.get(env, True)


@dataclass
class CatalogValidationError(Exception):
    """Raised when services.yaml entry is malformed for drift-gate purposes."""

    service_name: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover (trivial)
        return f"services.yaml[{self.service_name}]: {self.reason}"


class ServicesCatalog:
    """Wraps the services list from services.yaml."""

    def __init__(self, services: list[Service]):
        self._services = {s.name: s for s in services}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ServicesCatalog":
        data = yaml.safe_load(Path(path).read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "ServicesCatalog":
        entries = data.get("services", [])
        services: list[Service] = []
        for entry in entries:
            services.append(_parse_service(entry))
        return cls(services)

    def all_names(self) -> set[str]:
        return set(self._services.keys())

    def get(self, name: str) -> Service | None:
        return self._services.get(name)

    def enabled_in(self, env: str) -> list[Service]:
        return [s for s in self._services.values() if s.is_enabled_in(env)]

    def deferred_in(self, env: str) -> list[Service]:
        return [s for s in self._services.values() if s.is_deferred_in(env)]

    def __iter__(self) -> Iterable[Service]:
        return iter(self._services.values())

    def __len__(self) -> int:
        return len(self._services)


def _parse_service(entry: dict) -> Service:
    name = entry.get("name")
    if not name:
        raise CatalogValidationError("(missing-name)", "service entry has no `name`")

    workload_kind = entry.get("workload_kind")
    if workload_kind not in VALID_WORKLOAD_KINDS:
        raise CatalogValidationError(
            name, f"workload_kind={workload_kind!r} not in {sorted(VALID_WORKLOAD_KINDS)}"
        )

    runtime_class = entry.get("runtime_class")
    if runtime_class not in VALID_RUNTIME_CLASSES:
        raise CatalogValidationError(
            name, f"runtime_class={runtime_class!r} not in {sorted(VALID_RUNTIME_CLASSES)}"
        )

    probe_contract = entry.get("probe_contract")
    if probe_contract not in VALID_PROBE_CONTRACTS:
        raise CatalogValidationError(
            name, f"probe_contract={probe_contract!r} not in {sorted(VALID_PROBE_CONTRACTS)}"
        )

    envs = entry.get("environments", {})
    for env, state in envs.items():
        if state not in VALID_ENV_STATES:
            raise CatalogValidationError(
                name, f"environments[{env}]={state!r} not in {sorted(VALID_ENV_STATES)}"
            )

    image_digest_required = entry.get("image_digest_required", {})
    if not isinstance(image_digest_required, dict):
        raise CatalogValidationError(name, "image_digest_required must be an environment map")
    for env, required in image_digest_required.items():
        if env not in envs:
            raise CatalogValidationError(
                name, f"image_digest_required[{env}] has no matching environment declaration"
            )
        if not isinstance(required, bool):
            raise CatalogValidationError(
                name, f"image_digest_required[{env}] must be boolean"
            )
        if required is False and not bool(entry.get("third_party", False)):
            raise CatalogValidationError(
                name, "only an explicitly third-party service may carry a digest exception"
            )

    return Service(
        name=name,
        workload_kind=workload_kind,
        runtime_class=runtime_class,
        probe_contract=probe_contract,
        jvm_warmup_extra=bool(entry.get("jvm_warmup_extra", False)),
        environments=dict(envs),
        third_party=bool(entry.get("third_party", False)),
        jwt_validates=bool(entry.get("jwt_validates", True)),
        image_digest_required=dict(image_digest_required),
    )
