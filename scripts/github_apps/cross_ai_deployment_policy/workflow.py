"""Static policy checks for machine-gated GitHub Actions workflows.

GitHub's deployment-protection webhook and workflow-run REST representation do
not expose ``workflow_dispatch`` inputs.  The v1 contract therefore accepts
only no-input, content-addressed workflows whose runner and dependency surface
can be reproduced from the reviewed commit.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import yaml

from .canonical import sha256_digest
from .errors import PolicyError, reject
from .policy import StagePolicy


MAX_WORKFLOW_BYTES = 1024 * 1024
FULL_COMMIT_SHA = re.compile(r"^[a-f0-9]{40}$")
DOCKER_DIGEST = re.compile(r"^docker://[^\s@]+@sha256:[a-f0-9]{64}$")
REMOTE_ACTION = re.compile(
    r"^(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"(?P<path>/[^@\s]+)?@(?P<revision>[^@\s]+)$"
)
LOCAL_USE = re.compile(r"^[.]/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+$")
FORBIDDEN_AUTHORITY = re.compile(
    r"\$\{\{\s*(?:inputs\.|vars\.|github[.]event[.]inputs(?:[.\s}]))",
    re.IGNORECASE,
)
REMOTE_CONTROL = re.compile(
    r"(?:\bcurl\b|\bwget\b)[^\n]*(?:https?://|\|\s*(?:ba)?sh\b)",
    re.IGNORECASE,
)


class _StrictBaseLoader(yaml.BaseLoader):
    """BaseLoader variant that preserves GitHub's literal ``on`` key."""


def _construct_mapping(
    loader: _StrictBaseLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            reject("WORKFLOW_YAML_INVALID", "workflow mapping keys must be strings")
        if key in result:
            reject("WORKFLOW_YAML_DUPLICATE_KEY", f"duplicate YAML key {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictBaseLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


@dataclass(frozen=True)
class WorkflowInspection:
    workflow_sha256: str
    dependency_lock_sha256: str
    governed_job: str
    runs_on_labels: tuple[str, ...]
    runner_group: str | None
    local_uses: tuple[str, ...]
    external_uses: tuple[str, ...]


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        reject("WORKFLOW_SHAPE_INVALID", f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        reject("WORKFLOW_SHAPE_INVALID", f"{label} must be a sequence")
    return value


def _parse_yaml(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_WORKFLOW_BYTES:
        reject("WORKFLOW_SIZE_INVALID", "workflow must contain 1..1048576 bytes")
    if b"\x00" in raw:
        reject("WORKFLOW_YAML_INVALID", "workflow contains a NUL byte")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        reject("WORKFLOW_YAML_INVALID", "workflow is not UTF-8")
    try:
        if any(
            isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
            for token in yaml.scan(text, Loader=_StrictBaseLoader)
        ):
            reject(
                "WORKFLOW_YAML_ALIAS_FORBIDDEN",
                "governed workflows must not use YAML anchors or aliases",
            )
        value = yaml.load(text, Loader=_StrictBaseLoader)
    except PolicyError:
        raise
    except yaml.YAMLError:
        reject("WORKFLOW_YAML_INVALID", "workflow is not valid YAML")
    return _mapping(value, "workflow")


def _validate_trigger(workflow: dict[str, Any]) -> None:
    trigger = workflow.get("on")
    if trigger == "workflow_dispatch":
        return
    if not isinstance(trigger, dict) or set(trigger) != {"workflow_dispatch"}:
        reject(
            "WORKFLOW_TRIGGER_INVALID",
            "machine-gated workflow must use only workflow_dispatch",
        )
    dispatch = trigger["workflow_dispatch"]
    if dispatch is None or dispatch == "":
        return
    dispatch_mapping = _mapping(dispatch, "on.workflow_dispatch")
    if dispatch_mapping.get("inputs") not in (None, "", {}):
        reject(
            "WORKFLOW_INPUTS_FORBIDDEN",
            "machine-gated workflow must not declare dispatch inputs",
        )
    if set(dispatch_mapping) - {"inputs"}:
        reject(
            "WORKFLOW_TRIGGER_INVALID",
            "workflow_dispatch contains unsupported control fields",
        )


def _runs_on(value: object) -> tuple[tuple[str, ...], str | None]:
    group: str | None = None
    labels_value = value
    if isinstance(value, dict):
        if set(value) - {"group", "labels"}:
            reject("WORKFLOW_RUNNER_INVALID", "runs-on contains unknown fields")
        group_value = value.get("group")
        if not isinstance(group_value, str) or not group_value:
            reject("WORKFLOW_RUNNER_INVALID", "runs-on group must be a literal string")
        group = group_value
        labels_value = value.get("labels")
    if isinstance(labels_value, str):
        labels = (labels_value,)
    elif isinstance(labels_value, list):
        if not labels_value or not all(
            isinstance(label, str) and 1 <= len(label) <= 100
            for label in labels_value
        ):
            reject("WORKFLOW_RUNNER_INVALID", "runs-on labels are invalid")
        labels = tuple(labels_value)
    else:
        reject("WORKFLOW_RUNNER_INVALID", "runs-on must be literal labels")
    if len(set(labels)) != len(labels) or any("${{" in label for label in labels):
        reject("WORKFLOW_RUNNER_INVALID", "runs-on labels must be unique literals")
    return labels, group


def _environment_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if set(value) - {"name", "url"}:
            reject("WORKFLOW_ENVIRONMENT_INVALID", "environment contains unknown fields")
        name = value.get("name")
        if not isinstance(name, str):
            reject("WORKFLOW_ENVIRONMENT_INVALID", "environment name must be literal")
        return name
    if value is None:
        return None
    reject("WORKFLOW_ENVIRONMENT_INVALID", "environment has invalid shape")


def _inspect_use(
    value: object,
    *,
    local: set[str],
    external: set[str],
) -> None:
    if not isinstance(value, str) or not value or "${{" in value:
        reject("WORKFLOW_DEPENDENCY_UNPINNED", "uses must be a literal pinned reference")
    if value.startswith("./"):
        if LOCAL_USE.fullmatch(value) is None or ".." in value.split("/"):
            reject("WORKFLOW_LOCAL_DEPENDENCY_INVALID", "local uses path is invalid")
        local.add(value)
        return
    if value.startswith("docker://"):
        if DOCKER_DIGEST.fullmatch(value) is None:
            reject("WORKFLOW_DEPENDENCY_UNPINNED", "container uses must pin a SHA-256 digest")
        external.add(value)
        return
    match = REMOTE_ACTION.fullmatch(value)
    if match is None or FULL_COMMIT_SHA.fullmatch(match.group("revision")) is None:
        reject("WORKFLOW_DEPENDENCY_UNPINNED", "external actions must pin a full commit SHA")
    external.add(value)


def inspect_workflow(
    raw: bytes,
    *,
    stage_policy: StagePolicy,
    environment: str,
) -> WorkflowInspection:
    """Return reproducible workflow bindings or reject the workflow closed."""

    workflow = _parse_yaml(raw)
    raw_text = raw.decode("utf-8")
    if FORBIDDEN_AUTHORITY.search(raw_text):
        reject(
            "WORKFLOW_INPUT_AUTHORITY_FORBIDDEN",
            "workflow reads an unavailable input or mutable vars authority",
        )
    if REMOTE_CONTROL.search(raw_text):
        reject(
            "WORKFLOW_REMOTE_CONTROL_FORBIDDEN",
            "workflow may not download remote control content",
        )
    _validate_trigger(workflow)

    jobs = _mapping(workflow.get("jobs"), "jobs")
    if not jobs:
        reject("WORKFLOW_JOBS_INVALID", "workflow must contain jobs")
    governed_jobs: list[str] = []
    local: set[str] = set()
    external: set[str] = set()
    governed_labels: tuple[str, ...] | None = None
    governed_group: str | None = None

    for job_name, job_value in jobs.items():
        job = _mapping(job_value, f"jobs.{job_name}")
        if "continue-on-error" in job:
            reject("WORKFLOW_CONTINUE_ON_ERROR_FORBIDDEN", "job continue-on-error is forbidden")
        job_environment = _environment_name(job.get("environment"))
        if job_environment == environment:
            governed_jobs.append(job_name)
            governed_labels, governed_group = _runs_on(job.get("runs-on"))
        if "uses" in job:
            _inspect_use(job["uses"], local=local, external=external)
        steps_value = job.get("steps", [])
        for step_value in _sequence(steps_value, f"jobs.{job_name}.steps"):
            step = _mapping(step_value, f"jobs.{job_name}.steps[]")
            if "continue-on-error" in step:
                reject(
                    "WORKFLOW_CONTINUE_ON_ERROR_FORBIDDEN",
                    "step continue-on-error is forbidden",
                )
            if "uses" in step:
                _inspect_use(step["uses"], local=local, external=external)

    if len(governed_jobs) != 1 or governed_labels is None:
        reject(
            "WORKFLOW_ENVIRONMENT_BINDING_INVALID",
            "exactly one job must bind the governed Environment",
        )
    expected_labels = tuple(stage_policy.required_runs_on_labels)
    if governed_labels != expected_labels:
        reject("WORKFLOW_RUNNER_MISMATCH", "governed job runs-on labels do not match policy")
    if stage_policy.require_runner_group != (governed_group is not None):
        reject("WORKFLOW_RUNNER_MISMATCH", "runner-group requirement does not match policy")

    dependency_projection = {
        "domain": "acik.cross-ai-workflow-dependency-lock.v1",
        "localUses": sorted(local),
        "externalUses": sorted(external),
    }
    return WorkflowInspection(
        workflow_sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
        dependency_lock_sha256=sha256_digest(dependency_projection),
        governed_job=governed_jobs[0],
        runs_on_labels=governed_labels,
        runner_group=governed_group,
        local_uses=tuple(sorted(local)),
        external_uses=tuple(sorted(external)),
    )


__all__ = ["WorkflowInspection", "inspect_workflow"]
