#!/usr/bin/env python3
"""Fail-closed ResourceQuota headroom check for the testai frontend rollout."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


QUOTA_METRICS = (
    "requests.cpu",
    "requests.memory",
    "limits.cpu",
    "limits.memory",
    "pods",
)
RESOURCE_FIELDS = {
    "requests.cpu": ("requests", "cpu"),
    "requests.memory": ("requests", "memory"),
    "limits.cpu": ("limits", "cpu"),
    "limits.memory": ("limits", "memory"),
}
QUANTITY_RE = re.compile(r"^([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))([a-zA-Z]*)$")
DECIMAL_SUFFIXES = {
    "": Decimal(1),
    "n": Decimal("0.000000001"),
    "u": Decimal("0.000001"),
    "m": Decimal("0.001"),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000) ** 2,
    "G": Decimal(1000) ** 3,
    "T": Decimal(1000) ** 4,
    "P": Decimal(1000) ** 5,
    "E": Decimal(1000) ** 6,
}
BINARY_SUFFIXES = {
    "Ki": Decimal(1024),
    "Mi": Decimal(1024) ** 2,
    "Gi": Decimal(1024) ** 3,
    "Ti": Decimal(1024) ** 4,
    "Pi": Decimal(1024) ** 5,
    "Ei": Decimal(1024) ** 6,
}


class PreflightError(ValueError):
    """Raised when desired/live state cannot prove a safe rollout."""


def load_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path}: expected a JSON object")
    return value


def parse_quantity(value: Any, *, metric: str) -> Decimal:
    if value is None:
        raise PreflightError(f"{metric}: quantity is missing")
    text = str(value).strip()
    match = QUANTITY_RE.fullmatch(text)
    if not match:
        raise PreflightError(f"{metric}: unsupported Kubernetes quantity {text!r}")
    number, suffix = match.groups()
    multiplier = BINARY_SUFFIXES.get(suffix, DECIMAL_SUFFIXES.get(suffix))
    if multiplier is None:
        raise PreflightError(
            f"{metric}: unsupported Kubernetes quantity suffix {suffix!r}"
        )
    try:
        parsed = Decimal(number) * multiplier
    except InvalidOperation as exc:
        raise PreflightError(f"{metric}: invalid Kubernetes quantity {text!r}") from exc
    if parsed < 0:
        raise PreflightError(f"{metric}: negative quantities are not supported")
    return parsed


def resolve_int_or_percent(
    value: Any, replicas: int, *, round_up: bool, field: str
) -> int:
    if isinstance(value, bool):
        raise PreflightError(f"{field}: boolean is not a valid IntOrString")
    if isinstance(value, int):
        resolved = value
    else:
        text = str(value).strip()
        if text.endswith("%"):
            try:
                percentage = Decimal(text[:-1])
            except InvalidOperation as exc:
                raise PreflightError(f"{field}: invalid percentage {text!r}") from exc
            raw = Decimal(replicas) * percentage / Decimal(100)
            resolved = math.ceil(raw) if round_up else math.floor(raw)
        else:
            try:
                resolved = int(text)
            except ValueError as exc:
                raise PreflightError(f"{field}: invalid IntOrString {value!r}") from exc
    if resolved < 0:
        raise PreflightError(f"{field}: value must be non-negative")
    return resolved


def container_resources(container: dict[str, Any], *, role: str) -> dict[str, Decimal]:
    name = container.get("name", "<unnamed>")
    resources = container.get("resources") or {}
    result: dict[str, Decimal] = {}
    for metric, (section, resource_name) in RESOURCE_FIELDS.items():
        raw = (resources.get(section) or {}).get(resource_name)
        if raw is None:
            raise PreflightError(
                f"{role} container {name}: explicit {section}.{resource_name} is required; "
                "LimitRange defaulting cannot be used by this preflight"
            )
        result[metric] = parse_quantity(raw, metric=f"{role}.{name}.{metric}")
    return result


def add_resources(*values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {
        metric: sum((value.get(metric, Decimal(0)) for value in values), Decimal(0))
        for metric in RESOURCE_FIELDS
    }


def max_resources(*values: dict[str, Decimal]) -> dict[str, Decimal]:
    return {
        metric: max(
            (value.get(metric, Decimal(0)) for value in values), default=Decimal(0)
        )
        for metric in RESOURCE_FIELDS
    }


def effective_pod_resources(deployment: dict[str, Any]) -> dict[str, Decimal]:
    pod_spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
    containers = pod_spec.get("containers") or []
    if not containers:
        raise PreflightError("deployment pod template has no containers")

    app_total = add_resources(
        *(container_resources(container, role="app") for container in containers)
    )
    restartable_init_total: dict[str, Decimal] = {
        metric: Decimal(0) for metric in RESOURCE_FIELDS
    }
    init_peak: dict[str, Decimal] = {metric: Decimal(0) for metric in RESOURCE_FIELDS}
    for container in pod_spec.get("initContainers") or []:
        current = container_resources(container, role="init")
        step_total = add_resources(restartable_init_total, current)
        init_peak = max_resources(init_peak, step_total)
        if container.get("restartPolicy") == "Always":
            restartable_init_total = add_resources(restartable_init_total, current)

    steady_state = add_resources(app_total, restartable_init_total)
    effective = max_resources(steady_state, init_peak)
    overhead = pod_spec.get("overhead") or {}
    if overhead:
        for metric, (_, resource_name) in RESOURCE_FIELDS.items():
            raw = overhead.get(resource_name)
            if raw is not None:
                effective[metric] += parse_quantity(
                    raw, metric=f"pod.overhead.{resource_name}"
                )
    return effective


def display_quantity(metric: str, value: Decimal) -> str:
    if metric.endswith(".cpu"):
        return f"{value * Decimal(1000):.0f}m"
    if metric.endswith(".memory"):
        mebibytes = value / (Decimal(1024) ** 2)
        return f"{mebibytes.normalize()}Mi"
    return str(int(value))


def evaluate(
    deployment: dict[str, Any],
    desired_quota: dict[str, Any],
    live_quota: dict[str, Any],
) -> dict[str, Any]:
    spec = deployment.get("spec") or {}
    replicas = int(spec.get("replicas", 1))
    if replicas < 1:
        raise PreflightError("frontend replicas must be at least 1")

    strategy = spec.get("strategy") or {}
    if strategy.get("type", "RollingUpdate") != "RollingUpdate":
        raise PreflightError("frontend rollout strategy must be RollingUpdate")
    rolling = strategy.get("rollingUpdate") or {}
    max_surge = resolve_int_or_percent(
        rolling.get("maxSurge", "25%"),
        replicas,
        round_up=True,
        field="strategy.maxSurge",
    )
    max_unavailable = resolve_int_or_percent(
        rolling.get("maxUnavailable", "25%"),
        replicas,
        round_up=False,
        field="strategy.maxUnavailable",
    )
    if max_surge < 1:
        raise PreflightError("zero-downtime rollout requires resolved maxSurge >= 1")
    if max_unavailable != 0:
        raise PreflightError(
            "zero-downtime rollout requires resolved maxUnavailable == 0"
        )

    progress_deadline = spec.get("progressDeadlineSeconds")
    if not isinstance(progress_deadline, int) or progress_deadline <= 0:
        raise PreflightError("positive progressDeadlineSeconds is required")

    per_pod = effective_pod_resources(deployment)
    required = {
        **{metric: value * max_surge for metric, value in per_pod.items()},
        "pods": Decimal(max_surge),
    }

    desired_hard = desired_quota.get("spec", {}).get("hard") or {}
    live_status = live_quota.get("status") or {}
    live_hard = live_status.get("hard") or {}
    live_used = live_status.get("used") or {}
    diagnostics: list[dict[str, Any]] = []
    failures: list[str] = []

    for metric in QUOTA_METRICS:
        for source_name, source in (
            ("desired hard", desired_hard),
            ("live hard", live_hard),
            ("live used", live_used),
        ):
            if metric not in source:
                raise PreflightError(
                    f"{metric}: missing from {source_name} ResourceQuota"
                )
        desired = parse_quantity(desired_hard[metric], metric=metric)
        hard = parse_quantity(live_hard[metric], metric=metric)
        used = parse_quantity(live_used[metric], metric=metric)
        effective_hard = min(desired, hard)
        margin = effective_hard - used
        needed = required[metric]
        passed = margin >= needed and used <= effective_hard
        if not passed:
            failures.append(
                f"{metric}: margin {display_quantity(metric, margin)} < "
                f"required {display_quantity(metric, needed)}"
            )
        diagnostics.append(
            {
                "metric": metric,
                "desired_hard": display_quantity(metric, desired),
                "live_hard": display_quantity(metric, hard),
                "effective_hard": display_quantity(metric, effective_hard),
                "live_used": display_quantity(metric, used),
                "required": display_quantity(metric, needed),
                "margin": display_quantity(metric, margin),
                "pass": passed,
            }
        )

    return {
        "verdict": "PASS" if not failures else "FAIL",
        "deployment": deployment.get("metadata", {}).get("name"),
        "replicas": replicas,
        "resolved_max_surge": max_surge,
        "resolved_max_unavailable": max_unavailable,
        "progress_deadline_seconds": progress_deadline,
        "diagnostics": diagnostics,
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-json", required=True)
    parser.add_argument("--desired-quota-json", required=True)
    parser.add_argument("--live-quota-json", required=True)
    parser.add_argument("--output-json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = evaluate(
            load_json(args.deployment_json),
            load_json(args.desired_quota_json),
            load_json(args.live_quota_json),
        )
    except (
        OSError,
        json.JSONDecodeError,
        PreflightError,
        TypeError,
        ValueError,
    ) as exc:
        report = {"verdict": "FAIL", "failures": [str(exc)], "diagnostics": []}

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output_json:
        Path(args.output_json).write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
