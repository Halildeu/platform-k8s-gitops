"""Probe contract rule table.

Codex 019e2319 iter-3 AGREE — Mandatory probe shape per `probe_contract`
classification in docs/operations/services.yaml.

A `probe_contract` value resolves to a `ProbeContractRule` that
`deploy_normalizer.assert_probe_contract(deploy, contract)` consumes.

Contract semantics
------------------
spring-actuator:
  Spring Boot Actuator management server (port 8081 / named "management").
  startupProbe REQUIRED (slow-start grace before liveness clock starts).
  liveness path == /actuator/health/liveness
  readiness path == /actuator/health/readiness

http-healthz:
  Plain HTTP `/healthz` style (nginx, openfga). startupProbe optional.
  liveness/readiness path in {/healthz, /healthz/live, /healthz/ready}.

exempt:
  No probe assertion (Jobs, lab-tools, third-party with own readiness model).

Allowed `port` field values (probe.httpGet.port):
  - "management"      (Spring Boot named port — preferred for spring-actuator)
  - 8081              (numeric fallback — accepted for spring-actuator)
  - any string/int    (for http-healthz, where contract is path-not-port-bound)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ProbeContractRule:
    """A single probe-contract specification."""

    name: str
    startup_required: bool
    liveness_paths: tuple[str, ...]
    readiness_paths: tuple[str, ...]
    port_values: tuple[object, ...] = field(default_factory=tuple)
    # If port_values is empty, port is not constrained by this contract.


PROBE_CONTRACTS: dict[str, ProbeContractRule] = {
    "spring-actuator": ProbeContractRule(
        name="spring-actuator",
        startup_required=True,
        liveness_paths=("/actuator/health/liveness",),
        readiness_paths=("/actuator/health/readiness",),
        port_values=("management", 8081, "8081"),
    ),
    "http-healthz": ProbeContractRule(
        name="http-healthz",
        startup_required=False,
        liveness_paths=("/healthz", "/healthz/live"),
        readiness_paths=("/healthz", "/healthz/ready"),
        port_values=(),  # path-not-port-bound
    ),
}


# `exempt` is special-cased: no rule entry; assertion short-circuits.
EXEMPT_CONTRACT = "exempt"


def known_contracts() -> Iterable[str]:
    """Return the set of recognized probe_contract values (including exempt)."""
    return list(PROBE_CONTRACTS.keys()) + [EXEMPT_CONTRACT]


def get_rule(contract: str) -> ProbeContractRule | None:
    """Return the rule for a contract, or None for `exempt` / unknown."""
    return PROBE_CONTRACTS.get(contract)
