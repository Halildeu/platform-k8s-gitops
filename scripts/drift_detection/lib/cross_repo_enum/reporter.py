"""Report assembly — JSON artifact + Markdown step summary.

ADR-0031 §I8 schema:
{
  "spec_path": "...",
  "spec_schema_version": 1,
  "action_commit_sha": "...",
  "own_repo_role": "canonical|mirror|spec-host",
  "pairing": "paired|unpaired-main",
  "paired_pr_url": "...",
  "reciprocal_pairing": true|false,
  "residual_main_drift_risk": true|false,
  "mappings": [...]
}
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MirrorReport:
    repo: str
    path: str
    ref: str
    sha: str
    strategy: str
    symbol: str
    extracted: list[str]
    missing_in_mirror: list[str] = field(default_factory=list)
    missing_in_canonical: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


@dataclass
class CanonicalReport:
    repo: str
    path: str
    ref: str
    sha: str
    strategy: str
    symbol: str
    extracted: list[str]
    duplicates: list[str] = field(default_factory=list)


@dataclass
class MappingReport:
    id: str
    verdict: str  # PASS | FAIL | ERROR
    canonical: CanonicalReport | None = None
    mirrors: list[MirrorReport] = field(default_factory=list)
    error: str | None = None


@dataclass
class Report:
    spec_path: str
    spec_schema_version: int
    action_commit_sha: str
    own_repo_role: str
    pairing: str
    paired_pr_url: str | None
    reciprocal_pairing: bool
    residual_main_drift_risk: bool
    mappings: list[MappingReport] = field(default_factory=list)

    @property
    def overall_pass(self) -> bool:
        return all(m.verdict == "PASS" for m in self.mappings)


def write_json(report: Report, path: Path) -> None:
    payload = _asdict_filtering_none(report)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def render_step_summary(report: Report) -> str:
    """Render a Markdown table for `$GITHUB_STEP_SUMMARY`.

    Header line (per ADR-0031 §I4 nice-to-have) includes action_commit_sha and
    spec_schema_version so a reviewer can confirm the pinned version without
    opening the action source.
    """
    lines: list[str] = []
    lines.append("## ADR-0031 cross-repo enum drift report")
    lines.append("")
    lines.append(
        f"- action_commit_sha: `{report.action_commit_sha or '(unset)'}`"
    )
    lines.append(f"- spec_schema_version: `{report.spec_schema_version}`")
    lines.append(f"- own_repo_role: `{report.own_repo_role}`")
    lines.append(f"- pairing: `{report.pairing}`")
    if report.paired_pr_url:
        lines.append(f"- paired_pr_url: <{report.paired_pr_url}>")
        lines.append(
            f"- reciprocal_pairing: `{str(report.reciprocal_pairing).lower()}`"
        )
    lines.append(
        f"- residual_main_drift_risk: `{str(report.residual_main_drift_risk).lower()}`"
    )
    lines.append("")
    overall = "PASS" if report.overall_pass else "FAIL"
    lines.append(f"**Overall**: `{overall}`")
    lines.append("")
    lines.append("| mapping | verdict | mirrors | note |")
    lines.append("|---|---|---|---|")
    for m in report.mappings:
        mirror_count = len(m.mirrors)
        if m.verdict == "ERROR":
            note = (m.error or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{m.id}` | ERROR | {mirror_count} | {note} |")
            continue
        notes: list[str] = []
        for mr in m.mirrors:
            issues: list[str] = []
            if mr.missing_in_mirror:
                issues.append(f"missing_in_mirror: {sorted(mr.missing_in_mirror)}")
            if mr.missing_in_canonical:
                issues.append(f"missing_in_canonical: {sorted(mr.missing_in_canonical)}")
            if mr.duplicates:
                issues.append(f"duplicates: {sorted(mr.duplicates)}")
            if issues:
                notes.append(f"`{mr.symbol}` — " + "; ".join(issues))
        note_md = "<br>".join(notes) if notes else ""
        lines.append(f"| `{m.id}` | {m.verdict} | {mirror_count} | {note_md} |")
    return "\n".join(lines) + "\n"


def append_step_summary(report: Report, path_env: str = "GITHUB_STEP_SUMMARY") -> None:
    import os

    summary_path_str = os.environ.get(path_env)
    if not summary_path_str:
        return
    summary_path = Path(summary_path_str)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_step_summary(report)
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(rendered)
        fh.write("\n")


def _asdict_filtering_none(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_asdict_filtering_none(v) for v in obj]
    if hasattr(obj, "__dataclass_fields__"):
        out: dict[str, Any] = {}
        for k, v in asdict(obj).items():
            out[k] = _asdict_filtering_none(v)
        return out
    if isinstance(obj, dict):
        return {k: _asdict_filtering_none(v) for k, v in obj.items()}
    return obj
