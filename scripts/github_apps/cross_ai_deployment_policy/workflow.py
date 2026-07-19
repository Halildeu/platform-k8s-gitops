"""Static policy checks for machine-gated GitHub Actions workflows.

GitHub's deployment-protection webhook and workflow-run REST representation do
not expose ``workflow_dispatch`` inputs.  The v1 contract therefore accepts
only no-input, content-addressed workflows whose runner and dependency surface
can be reproduced from the reviewed commit.

The v3 contract has a separate inspector for the reviewed two-job VIEW_ONLY
transaction.  Its dispatch inputs are permitted only because the dispatcher
hash-binds them to the signed subject and the protected job consumes the
same-run preflight artifact before any mutation.
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
SHA256_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
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
SECRET_CONTEXT = re.compile(r"\bsecrets\s*(?:[.]|\[)", re.IGNORECASE)
BOOTSTRAP_OUTPUT_VALUE = "${{ runner.temp }}/cross-ai-bootstrap.json"
BOOTSTRAP_ACTION_REPOSITORY = "halildeu/platform-k8s-gitops"
BOOTSTRAP_ACTION_PATH = "/.github/actions/protected-bootstrap"
BOOTSTRAP_ENV = {
    "CROSS_AI_BOOTSTRAP_TOKEN": "${{ secrets.CROSS_AI_BOOTSTRAP_TOKEN }}",
    "CROSS_AI_ENDPOINT_ID": "${{ secrets.CROSS_AI_ENDPOINT_ID }}",
    "CROSS_AI_OPERATOR_ID": "${{ secrets.CROSS_AI_OPERATOR_ID }}",
    "CROSS_AI_BOOTSTRAP_OUTPUT": BOOTSTRAP_OUTPUT_VALUE,
}
POST_BOOTSTRAP_ENV = {"CROSS_AI_BOOTSTRAP_FILE": BOOTSTRAP_OUTPUT_VALUE}
PROTECTED_SECRET_NAMES = (
    "CROSS_AI_BOOTSTRAP_TOKEN",
    "CROSS_AI_ENDPOINT_ID",
    "CROSS_AI_OPERATOR_ID",
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
    concurrency_group_sha256: str
    governed_job: str
    runs_on_labels: tuple[str, ...]
    runner_group: str | None
    local_uses: tuple[str, ...]
    external_uses: tuple[str, ...]


@dataclass(frozen=True)
class TransactionWorkflowInspection:
    workflow_sha256: str
    dependency_lock_sha256: str
    concurrency_group_sha256: str
    preflight_job: str
    governed_job: str
    runs_on_labels: tuple[str, ...]
    runner_group: str | None
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


def _validate_permissions(workflow: dict[str, Any]) -> None:
    permissions = _mapping(workflow.get("permissions"), "permissions")
    if permissions != {"contents": "read", "id-token": "write"}:
        reject(
            "WORKFLOW_OIDC_PERMISSION_INVALID",
            "machine-gated workflow permissions must be exact least privilege",
        )


def _concurrency_group(workflow: dict[str, Any]) -> tuple[str, str]:
    concurrency = _mapping(workflow.get("concurrency"), "concurrency")
    if set(concurrency) != {"group", "cancel-in-progress"}:
        reject(
            "WORKFLOW_CONCURRENCY_INVALID",
            "workflow concurrency must contain only group and cancellation policy",
        )
    group = concurrency.get("group")
    cancel = concurrency.get("cancel-in-progress")
    if (
        not isinstance(group, str)
        or not 1 <= len(group) <= 100
        or "${{" in group
        or cancel != "false"
    ):
        reject(
            "WORKFLOW_CONCURRENCY_INVALID",
            "workflow concurrency must be one literal non-cancelling group",
        )
    return group, sha256_digest(
        {
            "domain": "acik.cross-ai-workflow-concurrency-group.v1",
            "group": group,
        }
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
            isinstance(label, str) and 1 <= len(label) <= 100 for label in labels_value
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
            reject(
                "WORKFLOW_ENVIRONMENT_INVALID", "environment contains unknown fields"
            )
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
        reject(
            "WORKFLOW_DEPENDENCY_UNPINNED", "uses must be a literal pinned reference"
        )
    if value.startswith("./"):
        if LOCAL_USE.fullmatch(value) is None or ".." in value.split("/"):
            reject("WORKFLOW_LOCAL_DEPENDENCY_INVALID", "local uses path is invalid")
        local.add(value)
        return
    if value.startswith("docker://"):
        if DOCKER_DIGEST.fullmatch(value) is None:
            reject(
                "WORKFLOW_DEPENDENCY_UNPINNED",
                "container uses must pin a SHA-256 digest",
            )
        external.add(value)
        return
    match = REMOTE_ACTION.fullmatch(value)
    if match is None or FULL_COMMIT_SHA.fullmatch(match.group("revision")) is None:
        reject(
            "WORKFLOW_DEPENDENCY_UNPINNED",
            "external actions must pin a full commit SHA",
        )
    external.add(value)


def _checkout_action(value: object) -> tuple[bool, bool]:
    if not isinstance(value, str):
        return False, False
    match = REMOTE_ACTION.fullmatch(value)
    if match is None or match.group("repository").casefold() != "actions/checkout":
        return False, False
    return True, match.group("path") is None


def _protected_secret_reference_count(raw_text: str, secret_name: str) -> int:
    name = re.escape(secret_name)
    pattern = re.compile(
        rf"\$\{{\{{\s*secrets\s*(?:\.\s*{name}|\[\s*['\"]{name}['\"]\s*\])\s*\}}\}}",
        re.IGNORECASE,
    )
    return len(pattern.findall(raw_text))


def _bootstrap_action(value: object) -> tuple[bool, str | None]:
    if not isinstance(value, str):
        return False, None
    match = REMOTE_ACTION.fullmatch(value)
    if (
        match is None
        or match.group("repository").casefold() != BOOTSTRAP_ACTION_REPOSITORY
        or match.group("path") != BOOTSTRAP_ACTION_PATH
        or FULL_COMMIT_SHA.fullmatch(match.group("revision")) is None
    ):
        return False, None
    return True, match.group("revision")


def _validate_bootstrap_step(
    job: dict[str, Any],
    job_name: str,
    *,
    stage_policy: StagePolicy,
    expected_bootstrap_url: str,
) -> None:
    steps = _sequence(job.get("steps", []), f"jobs.{job_name}.steps")
    matches: list[tuple[int, dict[str, Any]]] = []
    for index, step_value in enumerate(steps):
        step = _mapping(step_value, f"jobs.{job_name}.steps[]")
        is_bootstrap, _revision = _bootstrap_action(step.get("uses"))
        if is_bootstrap:
            matches.append((index, step))
    if len(matches) != 1:
        reject(
            "WORKFLOW_BOOTSTRAP_INVALID",
            "governed job must call the immutable runner bootstrap action exactly once",
        )
    bootstrap_index, bootstrap = matches[0]
    if bootstrap_index != 1:
        reject(
            "WORKFLOW_BOOTSTRAP_ORDER_INVALID",
            "runner bootstrap must immediately follow one pinned checkout step",
        )
    for prior_value in steps[:bootstrap_index]:
        prior = _mapping(prior_value, f"jobs.{job_name}.steps[]")
        use = prior.get("uses")
        is_checkout, is_root_checkout = _checkout_action(use)
        if set(prior) - {"name", "uses"} or not is_checkout or not is_root_checkout:
            reject(
                "WORKFLOW_BOOTSTRAP_ORDER_INVALID",
                "only pinned checkout may run before runner bootstrap",
            )
    if set(bootstrap) - {"name", "env", "uses", "with"}:
        reject(
            "WORKFLOW_BOOTSTRAP_INVALID",
            "bootstrap step contains an unsupported control field",
        )
    is_bootstrap, bootstrap_revision = _bootstrap_action(bootstrap.get("uses"))
    if not is_bootstrap or bootstrap_revision is None:
        reject("WORKFLOW_BOOTSTRAP_INVALID", "bootstrap action pin is invalid")
    arguments = _mapping(bootstrap.get("with"), "runner bootstrap inputs")
    if (
        set(arguments) != {"stage", "workflow-path", "expected-trust-root-sha256"}
        or arguments.get("stage") != stage_policy.stage
        or arguments.get("workflow-path") != stage_policy.workflow_path
        or SHA256_DIGEST.fullmatch(str(arguments.get("expected-trust-root-sha256", "")))
        is None
    ):
        reject(
            "WORKFLOW_BOOTSTRAP_INVALID",
            "bootstrap action inputs differ from the signed stage profile",
        )
    environment = _mapping(bootstrap.get("env"), "runner bootstrap env")
    if set(environment) != set(BOOTSTRAP_ENV) | {"CROSS_AI_BOOTSTRAP_URL"}:
        reject(
            "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID",
            "runner bootstrap environment contains an unsupported value",
        )
    for name, expected in BOOTSTRAP_ENV.items():
        if environment.get(name) != expected:
            reject(
                "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID",
                f"runner bootstrap must receive {name} only through protected env",
            )
    endpoint = environment.get("CROSS_AI_BOOTSTRAP_URL")
    if endpoint != expected_bootstrap_url:
        reject(
            "WORKFLOW_BOOTSTRAP_ENDPOINT_INVALID",
            "runner bootstrap endpoint differs from the signed policy",
        )
    post_bootstrap = steps[bootstrap_index + 1 :]
    if not 1 <= len(post_bootstrap) <= 8:
        reject(
            "WORKFLOW_POST_BOOTSTRAP_INVALID",
            "governed job must have a bounded pinned execution action",
        )
    for step_value in post_bootstrap:
        step = _mapping(step_value, f"jobs.{job_name}.steps[]")
        use = step.get("uses")
        is_checkout, _is_root_checkout = _checkout_action(use)
        if (
            set(step) - {"name", "uses", "env"}
            or not isinstance(use, str)
            or use.startswith("./")
            or is_checkout
            or REMOTE_ACTION.fullmatch(use) is None
            or REMOTE_ACTION.fullmatch(use).group("revision") != bootstrap_revision
            or _mapping(step.get("env"), "post-bootstrap action env")
            != POST_BOOTSTRAP_ENV
        ):
            reject(
                "WORKFLOW_POST_BOOTSTRAP_INVALID",
                "post-bootstrap execution must use only pinned actions with the verified file",
            )


def inspect_workflow(
    raw: bytes,
    *,
    stage_policy: StagePolicy,
    environment: str,
    expected_bootstrap_url: str,
) -> WorkflowInspection:
    """Return reproducible workflow bindings or reject the workflow closed."""

    workflow = _parse_yaml(raw)
    if set(workflow) - {"name", "on", "permissions", "concurrency", "jobs"}:
        reject(
            "WORKFLOW_ROOT_CONTROL_INVALID",
            "workflow contains an unsupported root control field",
        )
    raw_text = raw.decode("utf-8")
    if FORBIDDEN_AUTHORITY.search(raw_text):
        reject(
            "WORKFLOW_INPUT_AUTHORITY_FORBIDDEN",
            "workflow reads an unavailable input or mutable vars authority",
        )
    for secret_name in PROTECTED_SECRET_NAMES:
        if _protected_secret_reference_count(raw_text, secret_name) != 1:
            reject(
                "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID",
                "protected bootstrap values must appear only in the bootstrap step",
            )
    if len(SECRET_CONTEXT.findall(raw_text)) != len(PROTECTED_SECRET_NAMES):
        reject(
            "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID",
            "governed workflow may reference only the three pinned bootstrap secrets",
        )
    _validate_trigger(workflow)
    _validate_permissions(workflow)
    _group, concurrency_group_sha256 = _concurrency_group(workflow)

    jobs = _mapping(workflow.get("jobs"), "jobs")
    if len(jobs) != 1:
        reject(
            "WORKFLOW_JOBS_INVALID", "workflow must contain exactly one governed job"
        )
    governed_jobs: list[str] = []
    local: set[str] = set()
    external: set[str] = set()
    governed_labels: tuple[str, ...] | None = None
    governed_group: str | None = None
    governed_job_value: dict[str, Any] | None = None

    for job_name, job_value in jobs.items():
        job = _mapping(job_value, f"jobs.{job_name}")
        if set(job) - {
            "name",
            "environment",
            "runs-on",
            "steps",
            "timeout-minutes",
        }:
            reject(
                "WORKFLOW_JOB_CONTROL_INVALID",
                "governed job contains an unsupported control field",
            )
        if "continue-on-error" in job:
            reject(
                "WORKFLOW_CONTINUE_ON_ERROR_FORBIDDEN",
                "job continue-on-error is forbidden",
            )
        job_environment = _environment_name(job.get("environment"))
        if job_environment == environment:
            governed_jobs.append(job_name)
            governed_labels, governed_group = _runs_on(job.get("runs-on"))
            governed_job_value = job
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
    assert governed_job_value is not None
    _validate_bootstrap_step(
        governed_job_value,
        governed_jobs[0],
        stage_policy=stage_policy,
        expected_bootstrap_url=expected_bootstrap_url,
    )
    expected_labels = tuple(stage_policy.required_runs_on_labels)
    if governed_labels != expected_labels:
        reject(
            "WORKFLOW_RUNNER_MISMATCH",
            "governed job runs-on labels do not match policy",
        )
    if stage_policy.require_runner_group != (governed_group is not None):
        reject(
            "WORKFLOW_RUNNER_MISMATCH", "runner-group requirement does not match policy"
        )

    dependency_projection = {
        "domain": "acik.cross-ai-workflow-dependency-lock.v1",
        "localUses": sorted(local),
        "externalUses": sorted(external),
    }
    return WorkflowInspection(
        workflow_sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
        dependency_lock_sha256=sha256_digest(dependency_projection),
        concurrency_group_sha256=concurrency_group_sha256,
        governed_job=governed_jobs[0],
        runs_on_labels=governed_labels,
        runner_group=governed_group,
        local_uses=tuple(sorted(local)),
        external_uses=tuple(sorted(external)),
    )


def _validate_transaction_trigger(workflow: dict[str, Any]) -> None:
    trigger = _mapping(workflow.get("on"), "on")
    if set(trigger) != {"workflow_dispatch"}:
        reject(
            "TRANSACTION_WORKFLOW_TRIGGER_INVALID",
            "transaction workflow must use only workflow_dispatch",
        )
    dispatch = _mapping(trigger["workflow_dispatch"], "on.workflow_dispatch")
    if set(dispatch) != {"inputs"}:
        reject(
            "TRANSACTION_WORKFLOW_TRIGGER_INVALID",
            "transaction workflow_dispatch must contain only inputs",
        )
    inputs = _mapping(dispatch["inputs"], "on.workflow_dispatch.inputs")
    if set(inputs) != {
        "confirm",
        "device_id",
        "device_hostname",
        "pilot_seconds",
        "mask_rect_bps",
        "preflight_only",
    }:
        reject(
            "TRANSACTION_WORKFLOW_INPUTS_INVALID",
            "transaction workflow inputs differ from the v3 contract",
        )
    expected: dict[str, dict[str, Any]] = {
        "confirm": {"required": "true", "type": "string"},
        "device_id": {"required": "true", "type": "string"},
        "device_hostname": {"required": "true", "type": "string"},
        "pilot_seconds": {
            "required": "true",
            "default": "300",
            "type": "choice",
            "options": ["300", "600", "900", "1200", "1800"],
        },
        "mask_rect_bps": {
            "required": "true",
            "default": "7500,7500,2500,2500",
            "type": "string",
        },
        "preflight_only": {
            "required": "true",
            "default": "false",
            "type": "boolean",
        },
    }
    for name, required in expected.items():
        item = _mapping(inputs[name], f"on.workflow_dispatch.inputs.{name}")
        if set(item) - {"description", *required} or any(
            item.get(key) != value for key, value in required.items()
        ):
            reject(
                "TRANSACTION_WORKFLOW_INPUTS_INVALID",
                f"transaction input {name} is not the exact bounded contract",
            )


def inspect_transaction_workflow(
    raw: bytes,
    *,
    stage_policy: StagePolicy,
    environment: str,
) -> TransactionWorkflowInspection:
    """Inspect the one-workflow/two-job same-run transaction authority."""

    workflow = _parse_yaml(raw)
    if set(workflow) - {
        "name",
        "on",
        "permissions",
        "concurrency",
        "env",
        "jobs",
    }:
        reject(
            "TRANSACTION_WORKFLOW_ROOT_INVALID",
            "transaction workflow contains an unsupported root control field",
        )
    _validate_transaction_trigger(workflow)
    if _mapping(workflow.get("permissions"), "permissions") != {
        "actions": "read",
        "contents": "read",
        "issues": "read",
    }:
        reject(
            "TRANSACTION_WORKFLOW_PERMISSIONS_INVALID",
            "transaction workflow permissions are not exact least privilege",
        )
    _group, concurrency_group_sha256 = _concurrency_group(workflow)
    jobs = _mapping(workflow.get("jobs"), "jobs")
    if set(jobs) != {"preflight", "transaction"}:
        reject(
            "TRANSACTION_WORKFLOW_JOBS_INVALID",
            "transaction workflow must contain exactly preflight and transaction jobs",
        )
    preflight = _mapping(jobs["preflight"], "jobs.preflight")
    transaction = _mapping(jobs["transaction"], "jobs.transaction")
    if "environment" in preflight or "needs" in preflight:
        reject(
            "TRANSACTION_PREFLIGHT_GATE_INVALID",
            "preflight must run before and outside every protected Environment",
        )
    if transaction.get("needs") != "preflight" or transaction.get("if") != "${{ !inputs.preflight_only }}":
        reject(
            "TRANSACTION_SAME_RUN_BINDING_INVALID",
            "protected transaction must depend on the same-run preflight",
        )
    if _environment_name(transaction.get("environment")) != environment:
        reject(
            "TRANSACTION_ENVIRONMENT_BINDING_INVALID",
            "transaction job must bind the one governed Environment",
        )
    if sum(
        1
        for value in jobs.values()
        if _environment_name(_mapping(value, "job").get("environment")) is not None
    ) != 1:
        reject(
            "TRANSACTION_ENVIRONMENT_BINDING_INVALID",
            "exactly one job may carry an Environment gate",
        )
    preflight_labels, preflight_group = _runs_on(preflight.get("runs-on"))
    transaction_labels, transaction_group = _runs_on(transaction.get("runs-on"))
    expected_labels = tuple(stage_policy.required_runs_on_labels)
    expected_preflight_labels = tuple(
        stage_policy.required_preflight_runs_on_labels
    )
    if (
        preflight_labels != expected_preflight_labels
        or transaction_labels != expected_labels
        or preflight_group is not None
        or stage_policy.require_runner_group != (transaction_group is not None)
    ):
        reject(
            "TRANSACTION_WORKFLOW_RUNNER_MISMATCH",
            "preflight or protected transaction runner differs from policy",
        )
    local: set[str] = set()
    external: set[str] = set()
    for job_name, job in (("preflight", preflight), ("transaction", transaction)):
        if "continue-on-error" in job:
            reject(
                "TRANSACTION_CONTINUE_ON_ERROR_FORBIDDEN",
                "transaction jobs may not continue on error",
            )
        for step_value in _sequence(job.get("steps"), f"jobs.{job_name}.steps"):
            step = _mapping(step_value, f"jobs.{job_name}.steps[]")
            if "continue-on-error" in step:
                reject(
                    "TRANSACTION_CONTINUE_ON_ERROR_FORBIDDEN",
                    "transaction steps may not continue on error",
                )
            if "uses" in step:
                _inspect_use(step["uses"], local=local, external=external)
    if local:
        reject(
            "TRANSACTION_LOCAL_ACTION_FORBIDDEN",
            "transaction authority must not hide execution in a local action",
        )
    preflight_text = yaml.safe_dump(preflight, sort_keys=True)
    if re.search(r"\bsecrets\s*(?:[.]|\[)", preflight_text, re.IGNORECASE):
        reject(
            "TRANSACTION_PREFLIGHT_SECRET_FORBIDDEN",
            "preflight must not access protected secrets",
        )
    raw_text = raw.decode("utf-8")
    required_bindings = (
        "faz22-view-only-transaction-preflight-${{ github.run_id }}-${{ github.run_attempt }}",
        "${{ needs.preflight.outputs.preflight_artifact_name }}",
        "${{ needs.preflight.outputs.preflight_run_attempt }}",
        "${{ needs.preflight.outputs.preflight_sha256 }}",
    )
    if any(value not in raw_text for value in required_bindings):
        reject(
            "TRANSACTION_SAME_RUN_BINDING_INVALID",
            "workflow lacks the exact run/attempt preflight artifact binding",
        )
    external_repositories = {
        REMOTE_ACTION.fullmatch(value).group("repository").casefold()
        for value in external
        if REMOTE_ACTION.fullmatch(value) is not None
    }
    if not {
        "actions/checkout",
        "actions/upload-artifact",
        "actions/download-artifact",
    }.issubset(external_repositories):
        reject(
            "TRANSACTION_DEPENDENCY_INVALID",
            "transaction workflow lacks pinned checkout/upload/download dependencies",
        )
    dependency_lock_sha256 = sha256_digest(
        {
            "domain": "acik.cross-ai-transaction-dependency-lock.v1",
            "externalUses": sorted(external),
        }
    )
    return TransactionWorkflowInspection(
        workflow_sha256=f"sha256:{hashlib.sha256(raw).hexdigest()}",
        dependency_lock_sha256=dependency_lock_sha256,
        concurrency_group_sha256=concurrency_group_sha256,
        preflight_job="preflight",
        governed_job="transaction",
        runs_on_labels=transaction_labels,
        runner_group=transaction_group,
        external_uses=tuple(sorted(external)),
    )


__all__ = [
    "TransactionWorkflowInspection",
    "WorkflowInspection",
    "inspect_transaction_workflow",
    "inspect_workflow",
]
