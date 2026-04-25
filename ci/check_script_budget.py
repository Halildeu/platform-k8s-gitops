from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileLineLimit:
    path: str
    soft: int
    hard: int


@dataclass(frozen=True)
class FunctionLineLimits:
    soft: int
    hard: int


@dataclass(frozen=True)
class TrackedTextFileLimits:
    soft_lines: int
    hard_lines: int


@dataclass(frozen=True)
class GrandfatheredFile:
    path: str
    mode: str
    current_lines: int
    max_allowed_lines: int
    expires_on: str | None
    target_soft: int | None
    target_hard: int | None


@dataclass(frozen=True)
class ScriptBudgetConfig:
    tracked_text_file_limits: TrackedTextFileLimits
    grandfathered_files: dict[str, GrandfatheredFile]
    file_line_limits: list[FileLineLimit]
    function_line_limits: FunctionLineLimits
    function_scan_paths: list[str]


EXCLUDED_PREFIXES = (
    ".venv/",
    ".cache/",
    "evidence/",
    "dist/",
    "coverage/",
    "autonomous_orchestrator.egg-info/",
    "backend/target/",
    "web/dist/",
    "web/node_modules/",
    "web/apps/mfe-shell/node_modules/",
    "web/apps/mfe-users/node_modules/",
    "web/apps/mfe-access/node_modules/",
    "web/apps/mfe-audit/node_modules/",
    "web/apps/mfe-ethic/node_modules/",
    "web/apps/mfe-reporting/node_modules/",
    "web/packages/ui-kit/node_modules/",
)

FALLBACK_EXCLUDED_DIRS = {
    ".venv",
    ".cache",
    "evidence",
    "dist",
    "coverage",
    "autonomous_orchestrator.egg-info",
    "target",
    "node_modules",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_relative_to_root(repo_root: Path, rel_path: str) -> Path:
    path = (repo_root / rel_path).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"PATH_OUTSIDE_REPO: {rel_path}") from exc
    return path


def _count_lines(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def _count_lines_from_bytes(data: bytes) -> int:
    return len(data.splitlines())


def _is_text_bytes(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_git_work_tree(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"
    except Exception:
        return False


def _git_is_dirty(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and bool((result.stdout or "").strip())
    except Exception:
        return False


def _git_ref_exists(repo_root: Path, ref: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _git_show_bytes(repo_root: Path, ref: str, rel_path: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def _iter_tracked_text_files(repo_root: Path) -> list[str]:
    if _is_git_work_tree(repo_root):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            paths: list[str] = []
            for line in (result.stdout or "").splitlines():
                rel = line.strip()
                if not rel:
                    continue
                if any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
                    continue
                abs_path = repo_root / rel
                if not abs_path.is_file():
                    continue
                try:
                    data = abs_path.read_bytes()
                except Exception:
                    continue
                if not _is_text_bytes(data):
                    continue
                paths.append(rel)
            return sorted(set(paths))

    out: list[str] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [name for name in sorted(dirs) if name not in FALLBACK_EXCLUDED_DIRS]
        for name in sorted(files):
            abs_path = Path(root) / name
            try:
                rel = abs_path.resolve().relative_to(repo_root.resolve()).as_posix()
            except Exception:
                continue
            if any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
                continue
            try:
                data = abs_path.read_bytes()
            except Exception:
                continue
            if not _is_text_bytes(data):
                continue
            out.append(rel)
    return sorted(set(out))


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, *, source_path: str):
        self._stack: list[str] = []
        self.functions: list[dict[str, Any]] = []
        self._source_path = source_path

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._record_function(node)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._record_function(node)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()
        return None

    def _record_function(self, node: ast.AST) -> None:
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        name = getattr(node, "name", None)
        if not isinstance(lineno, int) or not isinstance(end_lineno, int) or not isinstance(name, str):
            return
        lines = int(end_lineno - lineno + 1)
        qualname = ".".join([*self._stack, name]) if self._stack else name
        self.functions.append(
            {
                "path": self._source_path,
                "qualname": qualname,
                "start_line": lineno,
                "end_line": end_lineno,
                "lines": lines,
            }
        )


def _parse_config(obj: Any) -> ScriptBudgetConfig:
    if not isinstance(obj, dict):
        raise ValueError("CONFIG_INVALID: root must be an object")
    if obj.get("version") != "v1":
        raise ValueError("CONFIG_INVALID: version must be v1")

    raw_limits = obj.get("tracked_text_file_limits")
    if not isinstance(raw_limits, dict):
        raise ValueError("CONFIG_INVALID: tracked_text_file_limits must be an object")
    soft_lines = raw_limits.get("soft_lines")
    hard_lines = raw_limits.get("hard_lines")
    if (
        not isinstance(soft_lines, int)
        or not isinstance(hard_lines, int)
        or soft_lines < 0
        or hard_lines < 0
    ):
        raise ValueError("CONFIG_INVALID: tracked_text_file_limits soft_lines/hard_lines must be non-negative integers")
    tracked_limits = TrackedTextFileLimits(soft_lines=int(soft_lines), hard_lines=int(hard_lines))

    raw_grandfathered = obj.get("grandfathered_files")
    if not isinstance(raw_grandfathered, list):
        raise ValueError("CONFIG_INVALID: grandfathered_files must be a list")
    grandfathered: dict[str, GrandfatheredFile] = {}
    for item in raw_grandfathered:
        if not isinstance(item, dict):
            raise ValueError("CONFIG_INVALID: grandfathered_files entries must be objects")
        path = item.get("path")
        mode = item.get("mode") if isinstance(item.get("mode"), str) else "baseline_ref"
        current_lines = item.get("current_lines")
        max_allowed = item.get("max_allowed_lines")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("CONFIG_INVALID: grandfathered_files.path must be non-empty string")
        if mode not in {"baseline_ref", "no_growth_only"}:
            raise ValueError("CONFIG_INVALID: grandfathered_files.mode must be baseline_ref|no_growth_only")
        if not isinstance(current_lines, int) or current_lines < 0:
            raise ValueError("CONFIG_INVALID: grandfathered_files.current_lines must be a non-negative integer")
        if not isinstance(max_allowed, int) or max_allowed < 0:
            raise ValueError("CONFIG_INVALID: grandfathered_files.max_allowed_lines must be a non-negative integer")
        expires_on = item.get("expires_on")
        if expires_on is not None and not isinstance(expires_on, str):
            raise ValueError("CONFIG_INVALID: grandfathered_files.expires_on must be string|null")
        target_soft = item.get("target_soft")
        if target_soft is not None and (not isinstance(target_soft, int) or target_soft < 0):
            raise ValueError("CONFIG_INVALID: grandfathered_files.target_soft must be int|null (>=0)")
        target_hard = item.get("target_hard")
        if target_hard is not None and (not isinstance(target_hard, int) or target_hard < 0):
            raise ValueError("CONFIG_INVALID: grandfathered_files.target_hard must be int|null (>=0)")

        grandfathered[path] = GrandfatheredFile(
            path=path,
            mode=mode,
            current_lines=int(current_lines),
            max_allowed_lines=int(max_allowed),
            expires_on=str(expires_on) if isinstance(expires_on, str) else None,
            target_soft=int(target_soft) if isinstance(target_soft, int) else None,
            target_hard=int(target_hard) if isinstance(target_hard, int) else None,
        )

    raw_file_limits = obj.get("file_line_limits")
    if not isinstance(raw_file_limits, list):
        raise ValueError("CONFIG_INVALID: file_line_limits must be a list")
    file_limits: list[FileLineLimit] = []
    for item in raw_file_limits:
        if not isinstance(item, dict):
            raise ValueError("CONFIG_INVALID: file_line_limits entries must be objects")
        path = item.get("path")
        soft = item.get("soft")
        hard = item.get("hard")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("CONFIG_INVALID: file_line_limits.path must be non-empty string")
        if not isinstance(soft, int) or not isinstance(hard, int) or soft < 0 or hard < 0:
            raise ValueError("CONFIG_INVALID: file_line_limits soft/hard must be non-negative integers")
        file_limits.append(FileLineLimit(path=path, soft=int(soft), hard=int(hard)))

    raw_function_limits = obj.get("function_line_limits")
    if not isinstance(raw_function_limits, dict):
        raise ValueError("CONFIG_INVALID: function_line_limits must be an object")
    function_soft = raw_function_limits.get("soft")
    function_hard = raw_function_limits.get("hard")
    if (
        not isinstance(function_soft, int)
        or not isinstance(function_hard, int)
        or function_soft < 0
        or function_hard < 0
    ):
        raise ValueError("CONFIG_INVALID: function_line_limits soft/hard must be non-negative integers")

    raw_scan_paths = obj.get("function_scan_paths")
    if not isinstance(raw_scan_paths, list) or not raw_scan_paths:
        raise ValueError("CONFIG_INVALID: function_scan_paths must be a non-empty list")
    scan_paths: list[str] = []
    for path in raw_scan_paths:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("CONFIG_INVALID: function_scan_paths entries must be non-empty strings")
        scan_paths.append(path)

    return ScriptBudgetConfig(
        tracked_text_file_limits=tracked_limits,
        grandfathered_files=grandfathered,
        file_line_limits=file_limits,
        function_line_limits=FunctionLineLimits(soft=int(function_soft), hard=int(function_hard)),
        function_scan_paths=scan_paths,
    )


def _status_from_violations(
    *,
    exceeded_soft: list[dict[str, Any]],
    exceeded_hard: list[dict[str, Any]],
    function_soft: list[dict[str, Any]],
    function_hard: list[dict[str, Any]],
) -> str:
    if exceeded_hard or function_hard:
        return "FAIL"
    if exceeded_soft or function_soft:
        return "WARN"
    return "OK"


def _write_github_step_summary(report: dict[str, Any]) -> None:
    if (os.environ.get("GITHUB_ACTIONS") or "").strip().lower() != "true":
        return
    summary_path = (os.environ.get("GITHUB_STEP_SUMMARY") or "").strip()
    if not summary_path:
        return

    status = str(report.get("status", "OK"))
    exceeded_soft = report.get("exceeded_soft") if isinstance(report.get("exceeded_soft"), list) else []
    exceeded_hard = report.get("exceeded_hard") if isinstance(report.get("exceeded_hard"), list) else []
    function_soft = report.get("function_soft") if isinstance(report.get("function_soft"), list) else []
    function_hard = report.get("function_hard") if isinstance(report.get("function_hard"), list) else []

    def format_file(item: dict[str, Any]) -> str:
        return f"{item.get('path')} lines={item.get('lines')} soft={item.get('soft')} hard={item.get('hard')}"

    def format_function(item: dict[str, Any]) -> str:
        return (
            f"{item.get('path')}::{item.get('qualname')} "
            f"lines={item.get('lines')} soft={item.get('soft')} hard={item.get('hard')}"
        )

    offenders: list[str] = []
    offenders.extend([format_file(item) for item in exceeded_hard[:5]])
    offenders.extend([format_function(item) for item in function_hard[:5]])
    offenders.extend([format_file(item) for item in exceeded_soft[:5]])
    offenders.extend([format_function(item) for item in function_soft[:5]])
    offenders = offenders[:5]

    lines: list[str] = []
    lines.append("### Script Budget")
    lines.append(f"- status: **{status}**")
    lines.append(
        "- counts: "
        + f"file_hard={len(exceeded_hard)} file_soft={len(exceeded_soft)} "
        + f"fn_hard={len(function_hard)} fn_soft={len(function_soft)}"
    )
    if offenders:
        lines.append("")
        lines.append("Top offenders (max 5):")
        for offender in offenders:
            lines.append(f"- `{offender}`")
    lines.append("")
    lines.append("Recommendation: split large code/text artifacts into smaller modules or documented shards before increasing limits.")

    top_text = report.get("top_largest_text") if isinstance(report.get("top_largest_text"), list) else []
    if top_text:
        lines.append("")
        lines.append("Top 5 largest tracked text files:")
        for item in top_text[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{item.get('path')}` lines={item.get('lines')}")

    grandfathered_growth = report.get("grandfathered_growth_check")
    if isinstance(grandfathered_growth, list) and grandfathered_growth:
        lines.append("")
        lines.append(f"Grandfathered growth check: total={len(grandfathered_growth)}")
        for item in grandfathered_growth[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('path')}` current={item.get('current_lines')} "
                f"baseline={item.get('baseline_lines')} status={item.get('status')}"
            )

    try:
        Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8", append=True)  # type: ignore[arg-type]
    except TypeError:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def _evaluate_explicit_file_limits(
    repo_root: Path,
    file_limits: list[FileLineLimit],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    exceeded_soft: list[dict[str, Any]] = []
    exceeded_hard: list[dict[str, Any]] = []
    explicit_paths = {item.path for item in file_limits}
    for file_limit in sorted(file_limits, key=lambda item: item.path):
        abs_path = _require_relative_to_root(repo_root, file_limit.path)
        if not abs_path.exists():
            exceeded_hard.append(
                {
                    "path": file_limit.path,
                    "lines": None,
                    "soft": file_limit.soft,
                    "hard": file_limit.hard,
                    "error": "FILE_MISSING",
                }
            )
            continue
        lines = _count_lines(abs_path)
        entry = {
            "path": file_limit.path,
            "lines": lines,
            "soft": file_limit.soft,
            "hard": file_limit.hard,
        }
        if lines > file_limit.hard:
            exceeded_hard.append(entry)
        elif lines > file_limit.soft:
            exceeded_soft.append(entry)
    return exceeded_soft, exceeded_hard, explicit_paths


def _collect_text_line_counts(repo_root: Path, tracked_text_paths: list[str]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    text_line_counts: dict[str, int] = {}
    for rel in tracked_text_paths:
        abs_path = _require_relative_to_root(repo_root, rel)
        if not abs_path.exists():
            text_line_counts[rel] = -1
            continue
        text_line_counts[rel] = _count_lines(abs_path)

    top_largest_text: list[dict[str, Any]] = []
    for rel, lines in sorted(text_line_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        if lines < 0:
            continue
        top_largest_text.append({"path": rel, "lines": lines})
        if len(top_largest_text) >= 10:
            break
    return text_line_counts, top_largest_text


def _classify_budget_bucket(*, lines: int, soft: int, hard: int) -> str:
    if lines < 0 or lines > hard:
        return "fail"
    if lines > soft:
        return "warn"
    return "ok"


def _evaluate_explicit_tracked_text_file(
    *,
    rel: str,
    lines: int,
    file_limits_by_path: dict[str, FileLineLimit],
) -> str:
    file_limit = file_limits_by_path.get(rel)
    if file_limit is None:
        return "fail"
    return _classify_budget_bucket(lines=lines, soft=file_limit.soft, hard=file_limit.hard)


def _evaluate_no_growth_grandfathered_file(
    *,
    rel: str,
    lines: int,
    soft: int,
    hard: int,
    grandfathered_entry: GrandfatheredFile,
) -> dict[str, Any]:
    baseline_lines = grandfathered_entry.current_lines
    delta_lines = int(lines) - int(baseline_lines)
    growth_status = "OK" if delta_lines <= 0 else "GROWN"
    hard_entries: list[dict[str, Any]] = []
    bucket = "ok"
    if delta_lines > 0:
        hard_entries.append(
            {
                "path": rel,
                "lines": lines,
                "soft": soft,
                "hard": hard,
                "error_code": "TEXT_FILE_NO_GROWTH",
                "baseline_ref": "PINNED",
                "baseline_lines": baseline_lines,
                "delta_lines": delta_lines,
            }
        )
        bucket = "fail"
    return {
        "bucket": bucket,
        "soft_entries": [],
        "hard_entries": hard_entries,
        "growth_check": {
            "path": rel,
            "mode": grandfathered_entry.mode,
            "current_lines": lines,
            "baseline_ref": "PINNED",
            "baseline_lines": baseline_lines,
            "delta_lines": delta_lines,
            "status": growth_status,
            "max_allowed_lines": grandfathered_entry.max_allowed_lines,
        },
    }


def _evaluate_baseline_grandfathered_file(
    *,
    repo_root: Path,
    rel: str,
    lines: int,
    soft: int,
    hard: int,
    grandfathered_entry: GrandfatheredFile,
    baseline_ref: str,
    in_git: bool,
    dirty: bool,
    baseline_ok: bool,
) -> dict[str, Any]:
    baseline_lines: int | None = None
    growth_status = "SKIPPED_NO_GIT"
    hard_entries: list[dict[str, Any]] = []
    soft_entries: list[dict[str, Any]] = []
    bucket = "ok"
    if baseline_ok:
        baseline_bytes = _git_show_bytes(repo_root, baseline_ref, rel)
        baseline_lines = _count_lines_from_bytes(baseline_bytes) if baseline_bytes is not None else lines
        growth_status = "OK"
        if baseline_lines is not None and lines > baseline_lines:
            growth_status = "GROWN"
            hard_entries.append(
                {
                    "path": rel,
                    "lines": lines,
                    "soft": soft,
                    "hard": hard,
                    "error_code": "TEXT_FILE_GROWTH_FORBIDDEN",
                    "baseline_ref": baseline_ref,
                    "baseline_lines": baseline_lines,
                }
            )
            bucket = "fail"
    elif in_git and dirty:
        growth_status = "SKIPPED_DIRTY_WORKTREE"
    elif in_git:
        growth_status = "SKIPPED_BASELINE_REF_MISSING"

    if bucket != "fail" and lines > hard:
        soft_entries.append(
            {
                "path": rel,
                "lines": lines,
                "soft": soft,
                "hard": hard,
                "error": "GRANDFATHERED",
            }
        )
        bucket = "warn"

    return {
        "bucket": bucket,
        "soft_entries": soft_entries,
        "hard_entries": hard_entries,
        "growth_check": {
            "path": rel,
            "mode": grandfathered_entry.mode,
            "current_lines": lines,
            "baseline_ref": baseline_ref,
            "baseline_lines": baseline_lines,
            "delta_lines": None,
            "status": growth_status,
            "max_allowed_lines": grandfathered_entry.max_allowed_lines,
        },
    }


def _evaluate_grandfathered_text_file(
    *,
    repo_root: Path,
    rel: str,
    lines: int,
    soft: int,
    hard: int,
    grandfathered_entry: GrandfatheredFile,
    baseline_ref: str,
    in_git: bool,
    dirty: bool,
    baseline_ok: bool,
) -> dict[str, Any]:
    if grandfathered_entry.mode == "no_growth_only":
        return _evaluate_no_growth_grandfathered_file(
            rel=rel,
            lines=lines,
            soft=soft,
            hard=hard,
            grandfathered_entry=grandfathered_entry,
        )
    return _evaluate_baseline_grandfathered_file(
        repo_root=repo_root,
        rel=rel,
        lines=lines,
        soft=soft,
        hard=hard,
        grandfathered_entry=grandfathered_entry,
        baseline_ref=baseline_ref,
        in_git=in_git,
        dirty=dirty,
        baseline_ok=baseline_ok,
    )


def _evaluate_tracked_text_files(
    *,
    repo_root: Path,
    tracked_text_paths: list[str],
    text_line_counts: dict[str, int],
    explicit_paths: set[str],
    file_limits: list[FileLineLimit],
    tracked_text_limits: TrackedTextFileLimits,
    grandfathered: dict[str, GrandfatheredFile],
    baseline_ref: str,
) -> dict[str, Any]:
    exceeded_soft: list[dict[str, Any]] = []
    exceeded_hard: list[dict[str, Any]] = []
    grandfathered_growth_check: list[dict[str, Any]] = []
    text_ok = 0
    text_warn = 0
    text_fail = 0

    in_git = _is_git_work_tree(repo_root)
    dirty = _git_is_dirty(repo_root) if in_git else False
    baseline_ok = in_git and not dirty and _git_ref_exists(repo_root, baseline_ref)
    file_limits_by_path = {item.path: item for item in file_limits}

    for rel in sorted(tracked_text_paths):
        if rel in explicit_paths:
            lines = text_line_counts.get(rel, -1)
            bucket = _evaluate_explicit_tracked_text_file(
                rel=rel,
                lines=lines,
                file_limits_by_path=file_limits_by_path,
            )
            if bucket == "ok":
                text_ok += 1
            elif bucket == "warn":
                text_warn += 1
            else:
                text_fail += 1
            continue

        lines = text_line_counts.get(rel, -1)
        soft = tracked_text_limits.soft_lines
        hard = tracked_text_limits.hard_lines
        if lines < 0:
            text_fail += 1
            exceeded_hard.append(
                {
                    "path": rel,
                    "lines": None,
                    "soft": soft,
                    "hard": hard,
                    "error": "FILE_MISSING",
                }
            )
            continue

        grandfathered_entry = grandfathered.get(rel)
        if grandfathered_entry is not None:
            grandfathered_result = _evaluate_grandfathered_text_file(
                repo_root=repo_root,
                rel=rel,
                lines=lines,
                soft=soft,
                hard=hard,
                grandfathered_entry=grandfathered_entry,
                baseline_ref=baseline_ref,
                in_git=in_git,
                dirty=dirty,
                baseline_ok=baseline_ok,
            )
            exceeded_soft.extend(grandfathered_result["soft_entries"])
            exceeded_hard.extend(grandfathered_result["hard_entries"])
            grandfathered_growth_check.append(grandfathered_result["growth_check"])
            bucket = grandfathered_result["bucket"]
            if bucket == "ok":
                text_ok += 1
            elif bucket == "warn":
                text_warn += 1
            else:
                text_fail += 1
            continue

        bucket = _classify_budget_bucket(lines=lines, soft=soft, hard=hard)
        if bucket == "fail":
            text_fail += 1
            exceeded_hard.append({"path": rel, "lines": lines, "soft": soft, "hard": hard})
        elif bucket == "warn":
            text_warn += 1
            exceeded_soft.append({"path": rel, "lines": lines, "soft": soft, "hard": hard})
        else:
            text_ok += 1

    return {
        "exceeded_soft": exceeded_soft,
        "exceeded_hard": exceeded_hard,
        "grandfathered_growth_check": sorted(grandfathered_growth_check, key=lambda item: str(item.get("path") or "")),
        "text_budget_summary": {
            "total": len(tracked_text_paths),
            "ok": text_ok,
            "warn": text_warn,
            "fail": text_fail,
            "soft_lines": tracked_text_limits.soft_lines,
            "hard_lines": tracked_text_limits.hard_lines,
        },
        "git": {
            "available": in_git,
            "dirty": dirty,
            "baseline_ref_exists": bool(baseline_ok),
        },
    }


def _evaluate_function_budgets(
    repo_root: Path,
    scan_paths: list[str],
    function_limits: FunctionLineLimits,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    function_soft: list[dict[str, Any]] = []
    function_hard: list[dict[str, Any]] = []
    for rel in sorted(set(scan_paths)):
        abs_path = _require_relative_to_root(repo_root, rel)
        if not abs_path.exists():
            function_hard.append(
                {
                    "path": rel,
                    "qualname": None,
                    "start_line": None,
                    "end_line": None,
                    "lines": None,
                    "soft": function_limits.soft,
                    "hard": function_limits.hard,
                    "error": "FILE_MISSING",
                }
            )
            continue
        if abs_path.suffix.lower() != ".py":
            continue
        try:
            src = abs_path.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except Exception:
            function_hard.append(
                {
                    "path": rel,
                    "qualname": None,
                    "start_line": None,
                    "end_line": None,
                    "lines": None,
                    "soft": function_limits.soft,
                    "hard": function_limits.hard,
                    "error": "PARSE_FAILED",
                }
            )
            continue
        visitor = _FunctionVisitor(source_path=rel)
        visitor.visit(tree)
        for fn in visitor.functions:
            lines = int(fn.get("lines") or 0)
            entry = dict(fn)
            entry["soft"] = function_limits.soft
            entry["hard"] = function_limits.hard
            if lines > function_limits.hard:
                function_hard.append(entry)
            elif lines > function_limits.soft:
                function_soft.append(entry)
    return function_soft, function_hard


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_script_budget",
        description="Deterministic script/text budget guardrails (soft=warn, hard=fail).",
    )
    parser.add_argument("--config", default="ci/script_budget.v1.json")
    parser.add_argument("--out", default=".cache/script_budget/report.json")
    parser.add_argument(
        "--baseline-ref",
        default="HEAD~1",
        help="Git ref used for grandfathered no-growth checks (default: HEAD~1).",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    out_path = _require_relative_to_root(repo_root, str(args.out))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "status": "FAIL",
        "exceeded_soft": [],
        "exceeded_hard": [],
        "function_soft": [],
        "function_hard": [],
    }

    try:
        config_path = _require_relative_to_root(repo_root, str(args.config))
        config_obj = _load_json(config_path)
        cfg = _parse_config(config_obj)
        file_limits = cfg.file_line_limits
        function_limits = cfg.function_line_limits
        scan_paths = cfg.function_scan_paths
        tracked_text_limits = cfg.tracked_text_file_limits
        grandfathered = cfg.grandfathered_files
        baseline_ref = str(getattr(args, "baseline_ref", "HEAD~1") or "HEAD~1")

        explicit_soft, explicit_hard, explicit_paths = _evaluate_explicit_file_limits(repo_root, file_limits)
        tracked_text_paths = _iter_tracked_text_files(repo_root)
        text_line_counts, top_largest_text = _collect_text_line_counts(repo_root, tracked_text_paths)
        text_result = _evaluate_tracked_text_files(
            repo_root=repo_root,
            tracked_text_paths=tracked_text_paths,
            text_line_counts=text_line_counts,
            explicit_paths=explicit_paths,
            file_limits=file_limits,
            tracked_text_limits=tracked_text_limits,
            grandfathered=grandfathered,
            baseline_ref=baseline_ref,
        )
        function_soft, function_hard = _evaluate_function_budgets(repo_root, scan_paths, function_limits)

        exceeded_soft = [*explicit_soft, *text_result["exceeded_soft"]]
        exceeded_hard = [*explicit_hard, *text_result["exceeded_hard"]]

        exceeded_soft.sort(key=lambda item: (str(item.get("path")), int(item.get("lines") or 0)))
        exceeded_hard.sort(key=lambda item: (str(item.get("path")), int(item.get("lines") or 0)))
        function_soft.sort(key=lambda item: (str(item.get("path")), str(item.get("qualname") or ""), int(item.get("lines") or 0)))
        function_hard.sort(key=lambda item: (str(item.get("path")), str(item.get("qualname") or ""), int(item.get("lines") or 0)))

        status = _status_from_violations(
            exceeded_soft=exceeded_soft,
            exceeded_hard=exceeded_hard,
            function_soft=function_soft,
            function_hard=function_hard,
        )

        report = {
            "status": status,
            "exceeded_soft": exceeded_soft,
            "exceeded_hard": exceeded_hard,
            "function_soft": function_soft,
            "function_hard": function_hard,
            "text_budget_summary": text_result["text_budget_summary"],
            "top_largest_text": top_largest_text,
            "grandfathered_growth_check": text_result["grandfathered_growth_check"],
            "baseline_ref_used": baseline_ref,
            "git": text_result["git"],
        }
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        _write_github_step_summary(report)

        soft_total = len(exceeded_soft) + len(function_soft)
        hard_total = len(exceeded_hard) + len(function_hard)
        print(
            "SCRIPT_BUDGET "
            f"status={status} hard_exceeded={hard_total} soft_exceeded={soft_total} out={out_path.as_posix()}"
        )
        return 1 if status == "FAIL" else 0
    except Exception as exc:
        report = {
            "status": "FAIL",
            "exceeded_soft": [],
            "exceeded_hard": [],
            "function_soft": [],
            "function_hard": [],
            "error": str(exc)[:300],
        }
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        _write_github_step_summary(report)
        print("SCRIPT_BUDGET status=FAIL hard_exceeded=0 soft_exceeded=0 out=" + out_path.as_posix())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
