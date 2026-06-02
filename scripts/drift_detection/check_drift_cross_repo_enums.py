#!/usr/bin/env python3
"""ADR-0031 DD-5-1 — Cross-Repo Enum / Contract Drift Guard.

Compare backend canonical enum value-sets against frontend mirror value-sets
across `platform-backend` and `platform-web`. Per-mirror equality (ADR-0031
§I2): a mapping passes IFF every mirror_j individually has
`set(canonical) == set(mirror_j)`. Union-of-mirrors WILL hide a stale mirror
and is NOT used to determine pass/fail.

Spec: config/cross_repo_enum_drift_spec.yaml (validated against the JSON
Schema at config/cross_repo_enum_drift_spec.schema.json before any fetch).

Caller patterns:

  # platform-k8s-gitops scheduled / PR run (spec-host repo)
  python3 scripts/drift_detection/check_drift_cross_repo_enums.py \
      --spec config/cross_repo_enum_drift_spec.yaml \
      --spec-schema config/cross_repo_enum_drift_spec.schema.json \
      --own-repo Halildeu/platform-k8s-gitops \
      --own-pr-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/pull/$PR_NUMBER" \
      --own-pr-body-file /tmp/pr-body.txt \
      --report-out /tmp/cross-repo-enum-drift-report.json

  # platform-backend caller (canonical-side change)
  python3 scripts/drift_detection/check_drift_cross_repo_enums.py \
      ... \
      --own-repo Halildeu/platform-backend \
      --own-role canonical \
      --canonical-ref "$GITHUB_HEAD_SHA" \
      --mirror-ref main

Exit codes:
  0 = all mappings pass
  1 = drift detected on at least one mapping (or merge_order_violation)
  2 = invocation / parse / fetch / spec validation error

ADR-0031 references: §I1 spec, §I2 per-mirror equality, §I3 token + 403/404
disambiguation, §I4 composite-action SHA pin, §I5 spec validation,
§I6 paired-PR canonical-first invariant, §I7 not path-filtered,
§I8 JSON + step summary, §I9 fixture matrix.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_ROOT = REPO_ROOT / "scripts" / "drift_detection"
sys.path.insert(0, str(LIB_ROOT))

from lib.cross_repo_enum import parsers  # noqa: E402
from lib.cross_repo_enum.fetcher import (  # noqa: E402
    ContentsKey,
    Fetcher,
    FetchError,
)
from lib.cross_repo_enum.paired_pr import (  # noqa: E402
    MergeOrderViolation,
    PairingError,
    PairingResult,
    check_canonical_first,
    extract_paired_pr_url,
    guarded_paths_from_spec,
    parse_pr_url,
    validate_paired_pr,
)
from lib.cross_repo_enum.reporter import (  # noqa: E402
    CanonicalReport,
    MappingReport,
    MirrorReport,
    Report,
    append_step_summary,
    write_json,
)
from lib.cross_repo_enum.spec_validator import (  # noqa: E402
    SpecValidationError,
    load_spec_schema,
    validate_spec,
)

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cross-repo enum drift guard — ADR-0031 DD-5-1.",
    )
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--spec-schema", required=True, type=Path)
    p.add_argument(
        "--own-repo",
        required=True,
        help="The repo this run is happening in (owner/repo).",
    )
    p.add_argument(
        "--own-role",
        choices=("canonical", "mirror", "spec-host"),
        default="spec-host",
        help="canonical when running in platform-backend; mirror in platform-web; "
        "spec-host in platform-k8s-gitops (default).",
    )
    p.add_argument("--canonical-ref", default="main")
    p.add_argument("--mirror-ref", default="main")
    p.add_argument(
        "--own-pr-url",
        default="",
        help="HTML URL of the PR triggering this run (for reciprocal pairing check).",
    )
    p.add_argument(
        "--own-pr-body-file",
        type=Path,
        default=None,
        help="Path to a file containing the PR description body. "
        "When omitted, paired-PR protocol is not invoked.",
    )
    p.add_argument(
        "--own-changed-paths-file",
        type=Path,
        default=None,
        help="Path to a newline-separated list of file paths modified by the "
        "running PR. Used by §I6 same-mapping enforcement on canonical/mirror "
        "side runs. When omitted, the own-side same-mapping check is skipped.",
    )
    p.add_argument(
        "--report-out",
        type=Path,
        default=Path("/tmp/cross-repo-enum-drift-report.json"),
    )
    p.add_argument(
        "--action-commit-sha",
        default=os.environ.get("ACTION_COMMIT_SHA", ""),
    )
    p.add_argument(
        "--no-step-summary",
        action="store_true",
        help="Suppress GITHUB_STEP_SUMMARY append (for local runs).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    # ------ Spec load + validate ------
    try:
        spec = _load_spec_yaml(args.spec)
    except Exception as exc:
        print(f"ERROR: failed to load spec {args.spec}: {exc}", file=sys.stderr)
        return 2
    try:
        schema = load_spec_schema(args.spec_schema)
    except Exception as exc:
        print(f"ERROR: failed to load schema {args.spec_schema}: {exc}", file=sys.stderr)
        return 2
    try:
        validate_spec(spec, schema)
    except SpecValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    schema_version = spec["schema_version"]
    mappings_spec = spec["mappings"]

    # ------ Paired-PR resolution ------
    fetcher = Fetcher()
    pr_body = ""
    if args.own_pr_body_file and args.own_pr_body_file.exists():
        pr_body = args.own_pr_body_file.read_text(encoding="utf-8")
    own_changed_paths: set[str] | None = None
    if args.own_changed_paths_file and args.own_changed_paths_file.exists():
        own_changed_paths = {
            line.strip()
            for line in args.own_changed_paths_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    guarded_paths_by_repo = guarded_paths_from_spec(mappings_spec)
    pairing = _resolve_pairing(
        pr_body=pr_body,
        own_repo=args.own_repo,
        own_role=args.own_role,
        own_pr_url=args.own_pr_url,
        canonical_default=args.canonical_ref,
        mirror_default=args.mirror_ref,
        own_changed_paths=own_changed_paths,
        guarded_paths_by_repo=guarded_paths_by_repo,
        fetcher=fetcher,
    )
    if isinstance(pairing, _PairingFailure):
        # report-out is written for diagnostic purposes
        report = Report(
            spec_path=str(args.spec),
            spec_schema_version=schema_version,
            action_commit_sha=args.action_commit_sha,
            own_repo_role=args.own_role,
            pairing=pairing.mode,
            paired_pr_url=pairing.paired_pr_url,
            reciprocal_pairing=False,
            residual_main_drift_risk=True,
            mappings=[
                MappingReport(id="__paired_pr__", verdict="ERROR", error=pairing.message)
            ],
        )
        write_json(report, args.report_out)
        if not args.no_step_summary:
            append_step_summary(report)
        print(f"ERROR: {pairing.message}", file=sys.stderr)
        return pairing.exit_code

    # ------ Per-mapping comparison ------
    canonical_ref = pairing.canonical_ref
    mirror_ref = pairing.mirror_ref
    paired_pr_url = pairing.paired_pr_url
    reciprocal = pairing.reciprocal_pairing
    mappings: list[MappingReport] = []
    for mapping_spec in mappings_spec:
        mappings.append(
            _run_mapping(
                mapping_spec=mapping_spec,
                fetcher=fetcher,
                canonical_ref=canonical_ref,
                mirror_ref=mirror_ref,
                own_role=args.own_role,
            )
        )

    report = Report(
        spec_path=str(args.spec),
        spec_schema_version=schema_version,
        action_commit_sha=args.action_commit_sha,
        own_repo_role=args.own_role,
        pairing=pairing.mode,
        paired_pr_url=paired_pr_url,
        reciprocal_pairing=reciprocal,
        residual_main_drift_risk=_compute_residual_main_drift_risk(
            mode=pairing.mode, own_role=args.own_role
        ),
        mappings=mappings,
    )
    write_json(report, args.report_out)
    if not args.no_step_summary:
        append_step_summary(report)

    if any(m.verdict == "ERROR" for m in mappings):
        return 2
    if not report.overall_pass:
        return 1
    return 0


# ----------------------------------------------------------------------
# Mapping comparison
# ----------------------------------------------------------------------


def _run_mapping(
    *,
    mapping_spec: dict,
    fetcher: Fetcher,
    canonical_ref: str,
    mirror_ref: str,
    own_role: str,
) -> MappingReport:
    mapping_id = mapping_spec["id"]
    try:
        canonical = _fetch_and_parse(
            mapping_spec["canonical"],
            ref=canonical_ref,
            fetcher=fetcher,
        )
    except (FetchError, parsers.ParseError) as exc:
        return MappingReport(id=mapping_id, verdict="ERROR", error=str(exc))

    canonical_extracted = canonical.extracted
    canonical_dupes = _find_duplicates(canonical_extracted)
    canonical_report = CanonicalReport(
        repo=mapping_spec["canonical"]["repo"],
        path=mapping_spec["canonical"]["path"],
        ref=canonical_ref,
        sha=canonical.sha,
        strategy=mapping_spec["canonical"]["kind"],
        symbol=mapping_spec["canonical"]["symbol"],
        extracted=canonical_extracted,
        duplicates=canonical_dupes,
    )

    mirror_reports: list[MirrorReport] = []
    canonical_set = set(canonical_extracted)
    for mirror_spec in mapping_spec["mirrors"]:
        try:
            mirror = _fetch_and_parse(
                mirror_spec,
                ref=mirror_ref,
                fetcher=fetcher,
            )
        except (FetchError, parsers.ParseError) as exc:
            return MappingReport(
                id=mapping_id,
                verdict="ERROR",
                canonical=canonical_report,
                error=f"mirror {mirror_spec['symbol']}: {exc}",
            )
        mirror_set = set(mirror.extracted)
        mirror_dupes = _find_duplicates(mirror.extracted)
        mirror_reports.append(
            MirrorReport(
                repo=mirror_spec["repo"],
                path=mirror_spec["path"],
                ref=mirror_ref,
                sha=mirror.sha,
                strategy=mirror_spec["kind"],
                symbol=mirror_spec["symbol"],
                extracted=mirror.extracted,
                missing_in_mirror=sorted(canonical_set - mirror_set),
                missing_in_canonical=sorted(mirror_set - canonical_set),
                duplicates=mirror_dupes,
            )
        )

    # Per-mirror equality (NOT union) — ADR-0031 §I2
    pass_per_mirror = all(
        not mr.missing_in_mirror and not mr.missing_in_canonical and not mr.duplicates
        for mr in mirror_reports
    )
    canonical_clean = not canonical_dupes
    verdict = "PASS" if (pass_per_mirror and canonical_clean) else "FAIL"
    return MappingReport(
        id=mapping_id,
        verdict=verdict,
        canonical=canonical_report,
        mirrors=mirror_reports,
    )


def _fetch_and_parse(
    side_spec: dict,
    *,
    ref: str,
    fetcher: Fetcher,
):
    """Fetch the source file via gh api contents, parse via the spec's strategy.

    Returns a small namespace-like object with `.extracted: list[str]` and
    `.sha: str`. ParseError or FetchError propagate (caller turns into ERROR).
    """
    key = ContentsKey(repo=side_spec["repo"], path=side_spec["path"], ref=ref)
    contents = fetcher.get_contents(key)
    extracted = parsers.parse(
        kind=side_spec["kind"],
        src=contents.text,
        symbol=side_spec["symbol"],
        anchor=side_spec.get("anchor"),
    )

    class _R:
        pass

    r = _R()
    r.extracted = extracted
    r.sha = contents.sha
    return r


# ----------------------------------------------------------------------
# Paired-PR resolution
# ----------------------------------------------------------------------


class _PairingFailure:
    def __init__(self, *, mode: str, paired_pr_url: str | None, message: str, exit_code: int) -> None:
        self.mode = mode
        self.paired_pr_url = paired_pr_url
        self.message = message
        self.exit_code = exit_code


class _PairingResolved:
    def __init__(
        self,
        *,
        mode: str,
        paired_pr_url: str | None,
        canonical_ref: str,
        mirror_ref: str,
        reciprocal_pairing: bool,
    ) -> None:
        self.mode = mode
        self.paired_pr_url = paired_pr_url
        self.canonical_ref = canonical_ref
        self.mirror_ref = mirror_ref
        self.reciprocal_pairing = reciprocal_pairing


REPO_PAIR = {
    "Halildeu/platform-backend": "Halildeu/platform-web",
    "Halildeu/platform-web": "Halildeu/platform-backend",
}


def _resolve_pairing(
    *,
    pr_body: str,
    own_repo: str,
    own_role: str,
    own_pr_url: str,
    canonical_default: str,
    mirror_default: str,
    own_changed_paths: set[str] | None,
    guarded_paths_by_repo: dict[str, set[str]],
    fetcher: Fetcher,
) -> _PairingResolved | _PairingFailure:
    """Determine pairing mode + canonical/mirror refs to use."""
    try:
        paired_url = extract_paired_pr_url(pr_body)
    except PairingError as exc:
        return _PairingFailure(
            mode="unpaired-main",
            paired_pr_url=None,
            message=str(exc),
            exit_code=2,
        )
    if not paired_url:
        return _PairingResolved(
            mode="unpaired-main",
            paired_pr_url=None,
            canonical_ref=canonical_default,
            mirror_ref=mirror_default,
            reciprocal_pairing=False,
        )
    expected_other = REPO_PAIR.get(own_repo)
    if expected_other is None:
        return _PairingFailure(
            mode="unpaired-main",
            paired_pr_url=paired_url,
            message=f"own_repo {own_repo!r} not in paired-repo registry",
            exit_code=2,
        )
    try:
        result = validate_paired_pr(
            paired_url=paired_url,
            own_repo=own_repo,
            expected_other_repo=expected_other,
            own_pr_url=own_pr_url,
            own_changed_paths=own_changed_paths if own_role != "spec-host" else None,
            guarded_paths_by_repo=guarded_paths_by_repo,
            fetcher=fetcher,
        )
    except (PairingError, FetchError) as exc:
        exit_code = getattr(exc, "exit_code", 2)
        return _PairingFailure(
            mode="unpaired-main",
            paired_pr_url=paired_url,
            message=str(exc),
            exit_code=exit_code,
        )
    if own_role in ("canonical", "mirror"):
        try:
            check_canonical_first(own_role=own_role, paired=result)
        except MergeOrderViolation as exc:
            return _PairingFailure(
                mode="paired",
                paired_pr_url=paired_url,
                message=str(exc),
                exit_code=1,
            )
    paired_pull = result.paired_pull
    if own_role == "canonical":
        canonical_ref = canonical_default
        # mirror_ref → paired PR head
        mirror_ref = paired_pull.head_sha if paired_pull else mirror_default
    elif own_role == "mirror":
        # canonical_ref → main (paired canonical already merged, per check_canonical_first)
        canonical_ref = canonical_default
        mirror_ref = mirror_default
    else:
        canonical_ref = canonical_default
        mirror_ref = mirror_default
    return _PairingResolved(
        mode="paired",
        paired_pr_url=paired_url,
        canonical_ref=canonical_ref,
        mirror_ref=mirror_ref,
        reciprocal_pairing=result.reciprocal_pairing,
    )


def _compute_residual_main_drift_risk(*, mode: str, own_role: str) -> bool:
    # If we ran paired AND we are the mirror-side, the canonical-first invariant
    # has been verified — once mirror PR merges, main is set-equal. No residual.
    if mode == "paired" and own_role == "mirror":
        return False
    # Canonical-side paired run has residual risk between canonical merge and
    # mirror merge — flagged for reviewer awareness.
    if mode == "paired" and own_role == "canonical":
        return True
    return False


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _find_duplicates(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    return sorted(k for k, c in seen.items() if c > 1)


def _load_spec_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        # Fallback for environments without PyYAML — caller (CI) installs PyYAML.
        raise RuntimeError("PyYAML is required (pip install pyyaml)")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    raise SystemExit(main())
