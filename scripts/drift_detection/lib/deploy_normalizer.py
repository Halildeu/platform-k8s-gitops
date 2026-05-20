"""Deployment template normalizer + semantic diff + probe contract assertion.

Codex 019e2319 iter-3 AGREE — Pure functions consumed by the CLI. No I/O,
no kubectl calls — operates on parsed dict structures (kustomize render
output or `kubectl get -o json`).

Surface ("CONTRACT_SURFACE") covered by `template_contract_view`:
  * spec.template.metadata.labels
  * spec.template.spec.serviceAccountName
  * spec.template.spec.automountServiceAccountToken
  * spec.template.spec.imagePullSecrets (sorted by name)
  * spec.template.spec.volumes (Codex iter-3 note #3 — added)
  * spec.template.spec.containers[<name>].(
        ports, startupProbe, livenessProbe, readinessProbe,
        resources, env, envFrom, command, args,
        securityContext, volumeMounts
    )

`image` is excluded — digest parity is governed by the existing image-pin
gate in check_env_drift.sh (Section 2).

Probe defaults applied per Kubernetes API server injection:
  scheme=HTTP, periodSeconds=10, timeoutSeconds=1, successThreshold=1,
  failureThreshold=3, initialDelaySeconds=0.
"""

from __future__ import annotations

import copy
from typing import Any

from .probe_contract_rules import EXEMPT_CONTRACT, ProbeContractRule, get_rule


# --- Probe defaults (Kubernetes API server injection) ---

PROBE_DEFAULTS: dict[str, Any] = {
    "periodSeconds": 10,
    "timeoutSeconds": 1,
    "successThreshold": 1,
    "failureThreshold": 3,
    "initialDelaySeconds": 0,
}

HTTPGET_DEFAULTS: dict[str, Any] = {
    "scheme": "HTTP",
}


# --- Finding shape ---


def make_finding(
    klass: str,
    kind: str,
    service: str,
    message: str,
    diff_path: str | None = None,
    details: dict | None = None,
) -> dict:
    f: dict[str, Any] = {
        "class": klass,
        "kind": kind,
        "service": service,
        "message": message,
    }
    if diff_path is not None:
        f["diff_path"] = diff_path
    if details is not None:
        f["details"] = details
    return f


# --- Normalization ---


def _normalize_probe(probe: dict | None) -> dict | None:
    if probe is None:
        return None
    out = copy.deepcopy(probe)
    for k, v in PROBE_DEFAULTS.items():
        out.setdefault(k, v)
    if "httpGet" in out and isinstance(out["httpGet"], dict):
        for k, v in HTTPGET_DEFAULTS.items():
            out["httpGet"].setdefault(k, v)
    return out


def _normalize_env_list(env: list | None) -> list:
    if not env:
        return []
    seen: set[str] = set()
    duplicates: list[str] = []
    for e in env:
        n = e.get("name")
        if n in seen:
            duplicates.append(n)
        seen.add(n)
    if duplicates:
        raise ValueError(f"duplicate env names: {sorted(set(duplicates))}")
    return sorted(env, key=lambda e: e.get("name", ""))


def _normalize_envfrom_list(envfrom: list | None) -> list:
    if not envfrom:
        return []
    def key(ef: dict) -> str:
        for ref_type in ("configMapRef", "secretRef"):
            if ref_type in ef and isinstance(ef[ref_type], dict):
                return f"{ref_type}:{ef[ref_type].get('name', '')}"
        return ""
    return sorted(envfrom, key=key)


def _normalize_ports(ports: list | None) -> list:
    if not ports:
        return []
    return sorted(ports, key=lambda p: (p.get("name", ""), p.get("containerPort", 0)))


def _normalize_volume_mounts(vm: list | None) -> list:
    if not vm:
        return []
    return sorted(vm, key=lambda v: (v.get("name", ""), v.get("mountPath", "")))


def _normalize_volumes(volumes: list | None) -> list:
    """Normalize volume defaults injected by the Kubernetes API server.

    Codex 019e2327 review #4 — `configMap.defaultMode`, `secret.defaultMode`,
    `projected.defaultMode` are injected as 420 (0644 octal) when absent.
    Without normalization the live ↔ desired diff produces false-positive
    drift on every Deployment that uses configMap/secret volumes.
    """
    if not volumes:
        return []
    normalized: list[dict] = []
    for v in volumes:
        v = copy.deepcopy(v)
        for key in ("configMap", "secret", "projected"):
            sub = v.get(key)
            if isinstance(sub, dict):
                sub.setdefault("defaultMode", 420)
        normalized.append(v)
    return sorted(normalized, key=lambda v: v.get("name", ""))


def _normalize_image_pull_secrets(secrets: list | None) -> list:
    if not secrets:
        return []
    return sorted(secrets, key=lambda s: s.get("name", ""))


# --- Resource quantity normalization (Codex 019e234e baseline cleanup) ---
#
# Kubernetes treats "1" and "1000m" as the same CPU quantity, and "1Gi" and
# "1024Mi" as the same memory quantity. Without parsing these to canonical
# numeric form the runtime detector flags every Deployment that pins integer
# CPU (e.g. limits.cpu="1") because the API server stores "1" while overlays
# render "1000m" (or vice versa). Same problem with memory binary vs decimal.

_MEMORY_SUFFIX_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "K": 1000, "Ki": 1024,
    "M": 1000 ** 2, "Mi": 1024 ** 2,
    "G": 1000 ** 3, "Gi": 1024 ** 3,
    "T": 1000 ** 4, "Ti": 1024 ** 4,
    "P": 1000 ** 5, "Pi": 1024 ** 5,
    "E": 1000 ** 6, "Ei": 1024 ** 6,
}

# Order matters: Ti must match before T, etc.
_MEMORY_SUFFIX_ORDER: tuple[str, ...] = (
    "Ei", "Pi", "Ti", "Gi", "Mi", "Ki",
    "E", "P", "T", "G", "M", "K",
    "",
)


def _parse_cpu_to_millicores(value) -> int | None:
    """Convert a Kubernetes CPU quantity to integer millicores.

    Examples:
        "1"      → 1000
        "1000m"  → 1000
        "0.5"    → 500
        "250m"   → 250
        None     → None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("m"):
        return int(float(s[:-1]))
    return int(round(float(s) * 1000))


def _parse_memory_to_bytes(value) -> int | None:
    """Convert a Kubernetes memory quantity to integer bytes.

    Examples:
        "1Gi"     → 1073741824
        "1024Mi"  → 1073741824  (== "1Gi")
        "500M"    → 500000000
        "100Ki"   → 102400
        None      → None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for suffix in _MEMORY_SUFFIX_ORDER:
        if suffix == "":
            return int(float(s))
        if s.endswith(suffix):
            number = s[: len(s) - len(suffix)]
            return int(float(number) * _MEMORY_SUFFIX_MULTIPLIERS[suffix])
    return int(float(s))  # pragma: no cover (unreachable; "" suffix always matches)


def _normalize_resources(resources: dict | None) -> dict:
    """Canonicalize requests/limits cpu+memory into comparable numeric form."""
    if not resources:
        return {}
    out: dict[str, dict] = {}
    for section_key in ("requests", "limits"):
        section = resources.get(section_key) or {}
        if not section:
            continue
        normalized_section: dict[str, object] = {}
        for resource_name, raw in section.items():
            if resource_name == "cpu":
                normalized_section[resource_name] = _parse_cpu_to_millicores(raw)
            elif resource_name == "memory":
                normalized_section[resource_name] = _parse_memory_to_bytes(raw)
            else:
                normalized_section[resource_name] = raw
        out[section_key] = normalized_section
    return out


def _container_contract_view(container: dict) -> dict:
    """Extract the contract-relevant subset of a container spec.

    Codex 019e234e baseline cleanup — `resources` is now normalized to
    canonical numeric form (millicores / bytes) so cpu "1" == "1000m" and
    memory "1Gi" == "1024Mi" stop producing false-positive drift.
    """
    return {
        "ports": _normalize_ports(container.get("ports")),
        "startupProbe": _normalize_probe(container.get("startupProbe")),
        "livenessProbe": _normalize_probe(container.get("livenessProbe")),
        "readinessProbe": _normalize_probe(container.get("readinessProbe")),
        "resources": _normalize_resources(container.get("resources")),
        "env": _normalize_env_list(container.get("env")),
        "envFrom": _normalize_envfrom_list(container.get("envFrom")),
        "command": container.get("command") or [],
        "args": container.get("args") or [],
        "securityContext": container.get("securityContext") or {},
        "volumeMounts": _normalize_volume_mounts(container.get("volumeMounts")),
    }


def template_contract_view(deploy: dict) -> dict:
    """Project a Deployment / StatefulSet dict to its contract surface.

    Codex 019e2327 review #3 — works for any workload with `.spec.template`,
    i.e. Deployment + StatefulSet. Jobs use `.spec.template` too but their
    probe-contract is exempt; callers gate by workload_kind.

    Codex 019e2327 review #5 — pod-level `securityContext` and
    `terminationGracePeriodSeconds` are part of the contract surface.
    Initial drafts only compared container-level securityContext; pod-level
    drift (runAsUser/fsGroup) escaped semantic diff.
    """
    template = (deploy.get("spec") or {}).get("template") or {}
    template_meta = template.get("metadata") or {}
    spec = template.get("spec") or {}

    containers = spec.get("containers") or []
    container_views: dict[str, dict] = {}
    for c in containers:
        name = c.get("name")
        if not name:
            continue
        container_views[name] = _container_contract_view(c)

    # Codex 019e234e baseline cleanup — Kubernetes API server injects
    # `terminationGracePeriodSeconds: 30` when the field is absent. Treat
    # missing == 30 so live state matches desired without manifest churn.
    tgp = spec.get("terminationGracePeriodSeconds")
    if tgp is None:
        tgp = 30

    return {
        "labels": template_meta.get("labels") or {},
        "serviceAccountName": spec.get("serviceAccountName"),
        "automountServiceAccountToken": spec.get("automountServiceAccountToken"),
        "terminationGracePeriodSeconds": tgp,
        "podSecurityContext": spec.get("securityContext") or {},
        "imagePullSecrets": _normalize_image_pull_secrets(spec.get("imagePullSecrets")),
        "volumes": _normalize_volumes(spec.get("volumes")),
        "containers": container_views,
    }


# --- Semantic diff ---


def _diff_recursive(desired: Any, live: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Walk both sides; emit (path, desired_value, live_value) on mismatch.

    Treats None / {} / [] as equivalent for empty-state stability.
    """
    if _is_empty(desired) and _is_empty(live):
        return []
    if isinstance(desired, dict) and isinstance(live, dict):
        diffs: list[tuple[str, Any, Any]] = []
        for key in sorted(set(desired.keys()) | set(live.keys())):
            sub_path = f"{path}.{key}" if path else key
            diffs.extend(_diff_recursive(desired.get(key), live.get(key), sub_path))
        return diffs
    if isinstance(desired, list) and isinstance(live, list):
        if len(desired) != len(live):
            return [(path, desired, live)]
        diffs = []
        for i, (d_item, l_item) in enumerate(zip(desired, live)):
            sub_path = f"{path}[{i}]"
            diffs.extend(_diff_recursive(d_item, l_item, sub_path))
        return diffs
    if desired != live:
        return [(path, desired, live)]
    return []


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (dict, list, str)) and len(value) == 0:
        return True
    return False


def semantic_diff(desired_deploy: dict, live_deploy: dict) -> list[tuple[str, Any, Any]]:
    """Return a list of (path, desired_value, live_value) drift entries."""
    return _diff_recursive(
        template_contract_view(desired_deploy),
        template_contract_view(live_deploy),
        path="",
    )


# --- Probe contract assertion ---


def assert_probe_contract(
    deploy: dict,
    contract: str,
    service_name: str,
) -> list[dict]:
    """Validate the container's probes against the given contract.

    Returns a list of P1 findings (empty if compliant).
    """
    if contract == EXEMPT_CONTRACT:
        return []

    rule = get_rule(contract)
    if rule is None:
        return [
            make_finding(
                "P1",
                "unknown_probe_contract",
                service_name,
                f"probe_contract={contract!r} not in known set",
            )
        ]

    containers = (((deploy.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
        "containers"
    ) or []

    primary = _pick_primary_container(containers, service_name)
    if primary is None:
        return [
            make_finding(
                "P1",
                "missing_primary_container",
                service_name,
                f"no container named '{service_name}' or single-container fallback",
            )
        ]

    findings: list[dict] = []

    if rule.startup_required and not primary.get("startupProbe"):
        findings.append(
            make_finding(
                "P1",
                "missing_startup_probe",
                service_name,
                f"contract {rule.name} requires startupProbe; none defined",
                diff_path="spec.template.spec.containers[].startupProbe",
            )
        )

    findings.extend(
        _assert_probe_shape(
            primary.get("livenessProbe"),
            rule,
            "livenessProbe",
            rule.liveness_paths,
            service_name,
        )
    )
    findings.extend(
        _assert_probe_shape(
            primary.get("readinessProbe"),
            rule,
            "readinessProbe",
            rule.readiness_paths,
            service_name,
        )
    )
    return findings


def _pick_primary_container(containers: list[dict], service_name: str) -> dict | None:
    """Prefer container whose name == service_name; else fall back to single-container."""
    for c in containers:
        if c.get("name") == service_name:
            return c
    if len(containers) == 1:
        return containers[0]
    return None


def _assert_probe_shape(
    probe: dict | None,
    rule: ProbeContractRule,
    field_name: str,
    valid_paths: tuple[str, ...],
    service_name: str,
) -> list[dict]:
    findings: list[dict] = []
    if probe is None:
        findings.append(
            make_finding(
                "P1",
                f"missing_{field_name.lower()}",
                service_name,
                f"contract {rule.name} requires {field_name}",
                diff_path=f"spec.template.spec.containers[].{field_name}",
            )
        )
        return findings

    httpget = probe.get("httpGet") or {}
    path = httpget.get("path")
    port = httpget.get("port")

    if path not in valid_paths:
        findings.append(
            make_finding(
                "P1",
                "probe_path_violation",
                service_name,
                f"contract {rule.name} {field_name}.path expected one of {list(valid_paths)}, got {path!r}",
                diff_path=f"spec.template.spec.containers[].{field_name}.httpGet.path",
                details={"expected_one_of": list(valid_paths), "actual": path},
            )
        )

    if rule.port_values and port not in rule.port_values:
        findings.append(
            make_finding(
                "P1",
                "probe_port_violation",
                service_name,
                f"contract {rule.name} {field_name}.port expected one of {list(rule.port_values)}, got {port!r}",
                diff_path=f"spec.template.spec.containers[].{field_name}.httpGet.port",
                details={"expected_one_of": list(rule.port_values), "actual": port},
            )
        )
    return findings
