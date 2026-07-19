#!/usr/bin/env python3
"""Regression tests for the isolated Codex review harness."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/run_isolated_codex_review.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("run_isolated_codex_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
POSTER_PATH = ROOT / "scripts/ai/post_cross_ai_evidence.py"
POSTER_SPEC = importlib.util.spec_from_file_location(
    "post_cross_ai_evidence_for_harness_test",
    POSTER_PATH,
)
assert POSTER_SPEC is not None and POSTER_SPEC.loader is not None
POSTER_MODULE = importlib.util.module_from_spec(POSTER_SPEC)
POSTER_SPEC.loader.exec_module(POSTER_MODULE)
FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

if sys.argv[1:] == ["--version"]:
    marker = os.environ.get("FAKE_EXECUTION_MARKER")
    if marker:
        Path(marker).write_text("executed", encoding="utf-8")
    print("codex-cli 0.144.1")
    raise SystemExit(0)

required = [
    "exec", "--sandbox", "read-only",
    "--ephemeral", "--ignore-user-config", "--ignore-rules", "--strict-config",
    "--skip-git-repo-check", "--json",
    'model_reasoning_effort="xhigh"',
]
if any(value not in sys.argv[1:] for value in required):
    raise SystemExit(7)
disabled = {
    sys.argv[index + 1]
    for index, value in enumerate(sys.argv[:-1])
    if value == "--disable"
}
expected_disabled = {
    "apps", "browser_use", "chronicle", "computer_use", "goals", "hooks",
    "image_generation", "in_app_browser", "memories", "multi_agent", "plugins",
    "remote_plugin", "shell_tool", "tool_suggest", "unified_exec",
    "workspace_dependencies",
}
if disabled != expected_disabled or sys.argv[1:].count("--disable") != len(expected_disabled):
    raise SystemExit(10)
review_dir = Path(sys.argv[sys.argv.index("-C") + 1])
if (review_dir / ".git").exists():
    raise SystemExit(11)
model = sys.argv[sys.argv.index("--model") + 1]
if model != os.environ.get("FAKE_EXPECTED_MODEL", "gpt-5.3-codex-spark"):
    raise SystemExit(9)
if not sys.stdin.read():
    raise SystemExit(8)
print(json.dumps({"type":"thread.started","thread_id":"019f7785-c66d-7992-a21a-d4097d9eb3f9"}))
if os.environ.get("FAKE_SKIP_TURN_STARTED") != "1":
    print(json.dumps({"type":"turn.started"}))
if os.environ.get("FAKE_DUPLICATE_TURN_STARTED") == "1":
    print(json.dumps({"type":"turn.started"}))
if os.environ.get("FAKE_STDERR") == "1":
    print("model routing warning", file=sys.stderr)
if os.environ.get("FAKE_REASONING_EVENT") == "1":
    reasoning = {"id":"item_r","type":"reasoning","text":"internal summary"}
    print(json.dumps({"type":"item.started","item":reasoning}))
    print(json.dumps({"type":"item.completed","item":reasoning}))
if os.environ.get("FAKE_REASONING_COMPLETION_ONLY") == "1":
    reasoning = {"id":"item_complete","type":"reasoning","text":"summary"}
    print(json.dumps({"type":"item.completed","item":reasoning}))
if os.environ.get("FAKE_REASONING_MISMATCH") == "1":
    print(json.dumps({"type":"item.started","item":{"id":"item_r1","type":"reasoning"}}))
    print(json.dumps({"type":"item.completed","item":{"id":"item_r2","type":"reasoning"}}))
if os.environ.get("FAKE_REASONING_UNFINISHED") == "1":
    print(json.dumps({"type":"item.started","item":{"id":"item_open","type":"reasoning"}}))
if os.environ.get("FAKE_ERROR_EVENT") == "1":
    item = {"id":"item_e","type":"error","message":"model rerouted"}
elif os.environ.get("FAKE_TOOL_EVENT") == "1":
    if "shell_tool" not in disabled or "unified_exec" not in disabled:
        source = Path(os.environ["FAKE_PROTECTED_INPUT"])
        Path(os.environ["FAKE_EXFIL_MARKER"]).write_text(source.read_text(encoding="utf-8"))
    item = {"id":"item_0","type":"command_execution","command":"git status"}
else:
    item = {"id":"item_0","type":"agent_message","text":"P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: AGREE"}
print(json.dumps({"type":"item.completed","item":item}))
if os.environ.get("FAKE_DUPLICATE_AGENT_MESSAGE") == "1":
    print(json.dumps({"type":"item.completed","item":item}))
if os.environ.get("FAKE_REASONING_AFTER_AGENT") == "1":
    item = {"id":"item_late","type":"reasoning","text":"late"}
    print(json.dumps({"type":"item.completed","item":item}))
print(json.dumps({"type":"turn.completed","usage":{}}))
'''

FAKE_GITLEAKS = r'''#!/bin/sh
if [ "$1" = "version" ]; then
    echo "8.30.1"
    exit 0
fi
if [ "$1" != "detect" ]; then
    exit 2
fi
if [ "$FAKE_GITLEAKS_FINDING" = "1" ]; then
    exit 1
fi
exit 0
'''


class IsolatedCodexReviewTests(unittest.TestCase):
    def test_codex_environment_excludes_unrelated_process_values(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "HOME": "/tmp/home",
                "PATH": "/usr/bin",
                "UNRELATED_SECRET": "must-not-cross-process-boundary",
            },
            clear=True,
        ):
            environment = MODULE.build_codex_environment()
        self.assertEqual(environment["HOME"], "/tmp/home")
        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertNotIn("UNRELATED_SECRET", environment)

    def test_stderr_allowlist_accepts_only_exact_bounded_cache_schema_warning(self) -> None:
        timestamp = "2026-07-19T00:35:07.740892Z"
        allowed = (
            f"{timestamp} ERROR codex_models_manager::cache: "
            "failed to load models cache: missing field "
            "`supports_reasoning_summaries` at line 88 column 5\n"
        )
        self.assertEqual(
            MODULE.classify_codex_stderr(allowed),
            "allowlisted-model-cache-schema-warning-v1",
        )
        self.assertIsNone(
            MODULE.classify_codex_stderr(
                f"{timestamp} ERROR codex_models_manager::manager: model rerouted\n"
            )
        )

    def test_every_declared_platform_package_has_a_release_pin(self) -> None:
        package_suffixes = {value[0] for value in MODULE.PLATFORM_PACKAGES.values()}
        pinned_suffixes = {
            target
            for (version, target) in MODULE.TRUSTED_CODEX_NATIVE_SHA256
            if version == "0.144.1"
        }
        self.assertEqual(package_suffixes, pinned_suffixes)

    def test_every_supported_codex_platform_has_a_gitleaks_release_pin(self) -> None:
        supported_platforms = {
            (system, machine)
            for system, machine in MODULE.PLATFORM_PACKAGES
        }
        scanner_platforms = {
            (system, machine)
            for version, system, machine in MODULE.TRUSTED_GITLEAKS_NATIVE_SHA256
            if version == MODULE.GITLEAKS_VERSION
        }
        self.assertEqual(supported_platforms, scanner_platforms)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        fake_gitleaks = self.bin_dir / "gitleaks"
        fake_gitleaks.write_text(FAKE_GITLEAKS, encoding="utf-8")
        fake_gitleaks.chmod(0o700)
        package_root = self.root / "lib" / "node_modules" / "@openai" / "codex"
        launcher = package_root / "bin" / "codex.js"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        launcher.chmod(0o700)
        system = platform.system().lower()
        machine = platform.machine().lower()
        specs = {
            ("darwin", "arm64"): ("codex-darwin-arm64", "aarch64-apple-darwin", "codex"),
            ("darwin", "aarch64"): ("codex-darwin-arm64", "aarch64-apple-darwin", "codex"),
            ("darwin", "x86_64"): ("codex-darwin-x64", "x86_64-apple-darwin", "codex"),
            ("linux", "aarch64"): ("codex-linux-arm64", "aarch64-unknown-linux-musl", "codex"),
            ("linux", "arm64"): ("codex-linux-arm64", "aarch64-unknown-linux-musl", "codex"),
            ("linux", "x86_64"): ("codex-linux-x64", "x86_64-unknown-linux-musl", "codex"),
        }
        package_suffix, target, executable_name = specs[(system, machine)]
        self.package_suffix = package_suffix
        dependency_name = f"@openai/{package_suffix}"
        dependency_version = f"0.144.1-{package_suffix.removeprefix('codex-')}"
        (package_root / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openai/codex",
                    "version": "0.144.1",
                    "bin": {"codex": "bin/codex.js"},
                    "optionalDependencies": {
                        dependency_name: f"npm:@openai/codex@{dependency_version}"
                    },
                }
            ),
            encoding="utf-8",
        )
        platform_root = package_root / "node_modules" / "@openai" / package_suffix
        platform_root.mkdir(parents=True)
        (platform_root / "package.json").write_text(
            json.dumps({"name": "@openai/codex", "version": dependency_version}),
            encoding="utf-8",
        )
        fake_codex = platform_root / "vendor" / target / "bin" / executable_name
        fake_codex.parent.mkdir(parents=True)
        fake_codex.write_text(FAKE_CODEX, encoding="utf-8")
        fake_codex.chmod(0o700)
        self.fake_codex = fake_codex
        self.package_manifest = package_root / "package.json"
        self.execution_marker = self.root / "native-executed.txt"
        self.protected_input = self.root / "provider-must-not-read.txt"
        self.protected_input.write_text("not-for-provider", encoding="utf-8")
        self.exfil_marker = self.root / "provider-read.txt"
        (self.bin_dir / "codex").symlink_to(launcher)
        self.worktree = self.root / "worktree"
        self.worktree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.worktree, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=self.worktree,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Harness Test"],
            cwd=self.worktree,
            check=True,
        )
        source = self.worktree / "scope-source.txt"
        source.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "scope-source.txt"], cwd=self.worktree, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.worktree, check=True)
        self.base_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True
        ).strip()
        subprocess.run(
            ["git", "branch", "cross-ai-test-base", self.base_sha],
            cwd=self.worktree,
            check=True,
        )
        source.write_text("base\nhead\n", encoding="utf-8")
        subprocess.run(["git", "add", "scope-source.txt"], cwd=self.worktree, check=True)
        subprocess.run(["git", "commit", "-qm", "head"], cwd=self.worktree, check=True)
        self.head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True
        ).strip()
        self.base_ref = "refs/heads/cross-ai-test-base"
        self.scope = self.root / "scope.patch"
        prepare = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ai/prepare_cross_ai_scope.py"),
                "--repo",
                str(self.worktree),
                "--base-ref",
                self.base_ref,
                "--base-sha",
                self.base_sha,
                "--head-sha",
                self.head_sha,
                "--output",
                str(self.scope),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            },
            check=False,
        )
        if prepare.returncode != 0:
            raise RuntimeError(prepare.stdout + prepare.stderr)
        self.scope_sha = json.loads(prepare.stdout)["scope_sha256"]
        self.output = self.root / "evidence.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_harness(
        self,
        *,
        tool_event: bool = False,
        error_event: bool = False,
        stderr_event: bool = False,
        skip_turn_started: bool = False,
        duplicate_turn_started: bool = False,
        reasoning_event: bool = False,
        reasoning_completion_only: bool = False,
        duplicate_agent_message: bool = False,
        reasoning_after_agent: bool = False,
        reasoning_mismatch: bool = False,
        reasoning_unfinished: bool = False,
        review_tier: str = "routine",
        trusted_pin: bool = True,
        trusted_gitleaks_pin: bool = True,
        gitleaks_finding: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_EXECUTION_MARKER": str(self.execution_marker),
            "FAKE_PROTECTED_INPUT": str(self.protected_input),
            "FAKE_EXFIL_MARKER": str(self.exfil_marker),
        }
        if tool_event:
            env["FAKE_TOOL_EVENT"] = "1"
        if error_event:
            env["FAKE_ERROR_EVENT"] = "1"
        if stderr_event:
            env["FAKE_STDERR"] = "1"
        if skip_turn_started:
            env["FAKE_SKIP_TURN_STARTED"] = "1"
        if duplicate_turn_started:
            env["FAKE_DUPLICATE_TURN_STARTED"] = "1"
        if reasoning_event:
            env["FAKE_REASONING_EVENT"] = "1"
        if reasoning_completion_only:
            env["FAKE_REASONING_COMPLETION_ONLY"] = "1"
        if duplicate_agent_message:
            env["FAKE_DUPLICATE_AGENT_MESSAGE"] = "1"
        if reasoning_after_agent:
            env["FAKE_REASONING_AFTER_AGENT"] = "1"
        if reasoning_mismatch:
            env["FAKE_REASONING_MISMATCH"] = "1"
        if reasoning_unfinished:
            env["FAKE_REASONING_UNFINISHED"] = "1"
        if review_tier == "high-impact":
            env["FAKE_EXPECTED_MODEL"] = "gpt-5.6-sol"
        if gitleaks_finding:
            env["FAKE_GITLEAKS_FINDING"] = "1"
        arguments = [
            str(SCRIPT),
            "--worktree",
            str(self.worktree),
            "--scope-file",
            str(self.scope),
            "--scope-sha256",
            self.scope_sha,
            "--base-ref",
            self.base_ref,
            "--base-tip-sha",
            self.base_sha,
            "--base-sha",
            self.base_sha,
            "--head-sha",
            self.head_sha,
            "--evidence-output",
            str(self.output),
            "--review-tier",
            review_tier,
        ]
        trusted = dict(MODULE.TRUSTED_CODEX_NATIVE_SHA256)
        if trusted_pin:
            trusted[("0.144.1", self.package_suffix)] = hashlib.sha256(
                self.fake_codex.read_bytes()
            ).hexdigest()
        trusted_gitleaks = dict(MODULE.TRUSTED_GITLEAKS_NATIVE_SHA256)
        if trusted_gitleaks_pin:
            trusted_gitleaks[
                (
                    MODULE.GITLEAKS_VERSION,
                    platform.system().lower(),
                    platform.machine().lower(),
                )
            ] = hashlib.sha256((self.bin_dir / "gitleaks").read_bytes()).hexdigest()
        stdout = io.StringIO()
        stderr = io.StringIO()
        returncode = 0
        codex_env = {
            key: value
            for key, value in env.items()
            if key in MODULE.CODEX_ENV_ALLOWLIST or key.startswith("FAKE_")
        }
        codex_env.update({"LC_ALL": "C", "LANG": "C"})
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(MODULE, "TRUSTED_CODEX_NATIVE_SHA256", trusted),
            mock.patch.object(
                MODULE,
                "TRUSTED_GITLEAKS_NATIVE_SHA256",
                trusted_gitleaks,
            ),
            mock.patch.object(MODULE, "build_codex_environment", return_value=codex_env),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                MODULE.main()
            except SystemExit as exc:
                returncode = int(exc.code or 0)
        return subprocess.CompletedProcess(
            arguments,
            returncode,
            stdout.getvalue(),
            stderr.getvalue(),
        )

    def test_runs_fixed_profile_and_writes_create_once_evidence(self) -> None:
        result = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(
            summary["execution_profile"],
            "codex-exec-ephemeral-read-only-exact-scope-no-tools-v2",
        )
        evidence = json.loads(self.output.read_text(encoding="utf-8"))
        poster_trusted = dict(POSTER_MODULE.TRUSTED_CODEX_NATIVE_SHA256)
        poster_trusted[("0.144.1", self.package_suffix)] = evidence[
            "execution_provenance"
        ]["cli_native_sha256"]
        with mock.patch.object(
            POSTER_MODULE,
            "TRUSTED_CODEX_NATIVE_SHA256",
            poster_trusted,
        ):
            posted_evidence, _ = POSTER_MODULE.validate_evidence_text(
                self.output.read_text(encoding="utf-8")
            )
        self.assertEqual(evidence["provider"], "openai")
        self.assertEqual(posted_evidence, evidence)
        self.assertEqual(evidence["actual_model"], "not-provider-attested")
        self.assertEqual(summary["requested_model"], "gpt-5.3-codex-spark")
        self.assertEqual(summary["review_tier"], "routine")
        self.assertEqual(summary["reasoning_effort"], "xhigh")
        self.assertEqual(summary["cli_version"], "0.144.1")
        self.assertRegex(summary["cli_native_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            summary["cli_trust_root"],
            "repo-pinned-codex-native-sha256-v1",
        )
        self.assertEqual(
            evidence["execution_provenance"]["cli_native_sha256"],
            summary["cli_native_sha256"],
        )
        self.assertEqual(evidence["scope_sha256"], self.scope_sha)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            summary["evidence_sha256"],
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
        )
        self.assertNotIn(evidence["response"], result.stdout)

    def test_high_impact_tier_uses_sol_model(self) -> None:
        result = self.run_harness(review_tier="high-impact")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = json.loads(result.stdout)
        evidence = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(summary["review_tier"], "high-impact")
        self.assertEqual(summary["requested_model"], "gpt-5.6-sol")
        self.assertEqual(evidence["actual_model"], "not-provider-attested")

    def test_rejects_any_tool_or_repository_access_event(self) -> None:
        result = self.run_harness(tool_event=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "codex_tool_or_non_message_event_forbidden",
        )
        self.assertFalse(self.exfil_marker.exists())

    def test_rejects_cli_error_or_reroute_event(self) -> None:
        result = self.run_harness(error_event=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "codex_tool_or_non_message_event_forbidden",
        )

    def test_accepts_bounded_reasoning_lifecycle_before_terminal_message(self) -> None:
        result = self.run_harness(reasoning_event=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(evidence["verdict"], "AGREE")

    def test_accepts_unique_completion_only_reasoning_event(self) -> None:
        result = self.run_harness(reasoning_completion_only=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(evidence["verdict"], "AGREE")

    def test_rejects_duplicate_or_post_terminal_items(self) -> None:
        for options in (
            {"duplicate_agent_message": True},
            {"reasoning_after_agent": True},
        ):
            with self.subTest(options=options):
                result = self.run_harness(**options)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "codex_event_sequence_invalid",
                )

    def test_rejects_mismatched_or_unfinished_reasoning_lifecycle(self) -> None:
        for options in (
            {"reasoning_mismatch": True},
            {"reasoning_unfinished": True},
        ):
            with self.subTest(options=options):
                result = self.run_harness(**options)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "codex_event_sequence_invalid",
                )

    def test_rejects_nonempty_cli_stderr(self) -> None:
        result = self.run_harness(stderr_event=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(result.stdout)["error"], "codex_execution_failed")

    def test_rejects_missing_or_duplicate_turn_started_lifecycle(self) -> None:
        for options in (
            {"skip_turn_started": True},
            {"duplicate_turn_started": True},
        ):
            with self.subTest(options=options):
                result = self.run_harness(**options)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "codex_event_sequence_invalid",
                )

    def test_rejects_scope_not_derived_from_bound_commits(self) -> None:
        self.scope.write_text(
            self.scope.read_text(encoding="utf-8") + "caller made claim\n",
            encoding="utf-8",
        )
        self.scope_sha = hashlib.sha256(self.scope.read_bytes()).hexdigest()
        result = self.run_harness()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "canonical_scope_binding_mismatch",
        )

    def test_refuses_to_overwrite_existing_evidence(self) -> None:
        self.output.write_text("existing", encoding="utf-8")
        result = self.run_harness()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "existing")
        self.assertFalse(self.execution_marker.exists())

    def test_rejects_untrusted_path_codex_without_official_package_layout(self) -> None:
        launcher = self.bin_dir / "codex"
        launcher.unlink()
        launcher.write_text(FAKE_CODEX, encoding="utf-8")
        launcher.chmod(0o700)
        result = self.run_harness()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "codex_package_invalid")

    def test_rejects_official_shaped_package_without_repo_pinned_native_digest(self) -> None:
        result = self.run_harness(trusted_pin=False)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "codex_native_identity_unverifiable",
        )
        self.assertFalse(self.execution_marker.exists())

    def test_rejects_non_object_optional_dependencies_cleanly(self) -> None:
        original = json.loads(self.package_manifest.read_text(encoding="utf-8"))
        for malformed in ([], "not-an-object"):
            with self.subTest(malformed=malformed):
                manifest = dict(original)
                manifest["optionalDependencies"] = malformed
                self.package_manifest.write_text(json.dumps(manifest), encoding="utf-8")
                result = self.run_harness()
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.output.exists())
                self.assertEqual(
                    json.loads(result.stdout)["error"],
                    "codex_platform_package_invalid",
                )
                self.assertFalse(self.execution_marker.exists())

    def test_rejects_known_secret_scope_when_path_scanner_is_untrusted(self) -> None:
        source = self.worktree / "scope-source.txt"
        source.write_text(
            "base\nhead\ncredential=ghp_abcdefghijklmnopqrstuvwxyz\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "commit", "-qam", "secret head"], cwd=self.worktree, check=True)
        self.head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True
        ).strip()
        self.scope = self.root / "secret-scope.patch"
        prepare = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/ai/prepare_cross_ai_scope.py"),
                "--repo",
                str(self.worktree),
                "--base-ref",
                self.base_ref,
                "--base-sha",
                self.base_sha,
                "--head-sha",
                self.head_sha,
                "--output",
                str(self.scope),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            },
            check=False,
        )
        self.assertEqual(prepare.returncode, 0, prepare.stdout + prepare.stderr)
        self.scope_sha = json.loads(prepare.stdout)["scope_sha256"]

        result = self.run_harness(trusted_gitleaks_pin=False)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "gitleaks_identity_unverifiable",
        )
        self.assertFalse(self.output.exists())
        self.assertFalse(self.execution_marker.exists())

    def test_rejects_trusted_scanner_finding_before_codex_execution(self) -> None:
        result = self.run_harness(gitleaks_finding=True)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["error"],
            "gitleaks_finding_detected",
        )
        self.assertFalse(self.output.exists())
        self.assertFalse(self.execution_marker.exists())


if __name__ == "__main__":
    unittest.main()
