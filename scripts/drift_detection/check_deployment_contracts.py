#!/usr/bin/env python3
"""CLI: Deployment contract drift gate (PR-time + runtime).

Codex 019e2319 iter-3 AGREE — Single CLI consumed by both bash orchestrators:
  * scripts/drift-detection/check_pr_time.sh  (mode=pr-time)
  * scripts/drift-detection/check_env_drift.sh (mode=runtime)

Both modes share the same contract motor (lib/deploy_normalizer +
lib/probe_contract_rules + lib/services_catalog). Modes differ in inputs:
  pr-time : --render-source <overlay-dir>  → enforce probe contract +
             catalog↔render parity. Workloads are in scope when they either
             carry part-of=platform or have an exact name in services.yaml;
             this keeps lab dependencies out while covering isolated product
             cells such as Etik Speak.
  runtime : --render-source <overlay-dir> + --live-source <kubectl-context>
             → semantic template drift + RS-split detection.

Exit codes:
  0 — clean
  1 — P1 finding(s) emitted
  2 — P2 finding(s) only (no P1)
  3 — exec error (rendering failed, kubectl unreachable, catalog malformed)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure local imports work when invoked directly.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.deploy_normalizer import (  # noqa: E402
    assert_probe_contract,
    make_finding,
    semantic_diff,
)
from lib.probe_contract_rules import EXEMPT_CONTRACT, known_contracts  # noqa: E402
from lib.services_catalog import (  # noqa: E402
    CatalogValidationError,
    Service,
    ServicesCatalog,
)


SCOPE_LABEL = "app.kubernetes.io/part-of"
SCOPE_VALUE = "platform"  # Codex iter-3 note #2 — exclude monitoring/lab deps

EXEC_ERROR_EXIT = 3  # Codex 019e2327 review #2 — runtime exec failure must
                    # signal exit 3, not be downgraded into a P1 finding.

# Workload kinds covered by this gate (have spec.template).
TEMPLATE_WORKLOAD_KINDS = {"Deployment", "StatefulSet"}


# --- Helpers ---


def _err(msg: str) -> None:
    sys.stderr.write(f"[check_deployment_contracts] ERROR: {msg}\n")


def _is_platform_scoped(deploy: dict) -> bool:
    labels = (deploy.get("metadata") or {}).get("labels") or {}
    return labels.get(SCOPE_LABEL) == SCOPE_VALUE


def _is_contract_scoped(workload: dict, catalog_names: set[str] | None = None) -> bool:
    """Return whether a workload belongs to the deployment contract gate.

    The historical ``part-of=platform`` boundary remains the default for
    discovering unmanaged platform workloads. A workload whose exact name is
    present in the service catalog is also in scope, allowing separately
    packaged product cells to keep their truthful ``part-of`` label without
    escaping render, probe, runtime-drift, or ReplicaSet-split checks.
    """
    return _is_platform_scoped(workload) or _deploy_name(workload) in (
        catalog_names or set()
    )


def _deploy_name(deploy: dict) -> str:
    return (deploy.get("metadata") or {}).get("name", "") or ""


def _kustomize_render(overlay_dir: str) -> list[dict]:
    """Run `kubectl kustomize` and return all top-level docs as dicts."""
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found on PATH")
    proc = subprocess.run(
        ["kubectl", "kustomize", overlay_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"kubectl kustomize {overlay_dir} failed: {proc.stderr.strip()}")
    import yaml  # local import — pyyaml is a dependency

    docs = [d for d in yaml.safe_load_all(proc.stdout) if d]
    return docs


def _kubectl_get_deployments_and_statefulsets(context: str, namespace: str) -> list[dict]:
    """Codex 019e2327 review #3 — fetch both Deployment and StatefulSet so the
    motor can apply template-contract checks to workloads like openfga.
    """
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not found on PATH")
    items: list[dict] = []
    for kind in ("deployments", "statefulsets"):
        proc = subprocess.run(
            [
                "kubectl",
                f"--context={context}",
                "-n",
                namespace,
                "get",
                kind,
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"kubectl get {kind} ctx={context} ns={namespace} failed: {proc.stderr.strip()}"
            )
        payload = json.loads(proc.stdout)
        items.extend(payload.get("items", []))
    return items


def _kubectl_get_replicasets(context: str, namespace: str) -> list[dict]:
    proc = subprocess.run(
        [
            "kubectl",
            f"--context={context}",
            "-n",
            namespace,
            "get",
            "replicasets",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"kubectl get replicasets failed: {proc.stderr.strip()}"
        )
    return json.loads(proc.stdout).get("items", [])


def _filter_template_workloads(
    docs: list[dict], catalog_names: set[str] | None = None
) -> list[dict]:
    """Accept contract-scoped Deployment and StatefulSet resources."""
    out = []
    for d in docs:
        if d.get("kind") not in TEMPLATE_WORKLOAD_KINDS:
            continue
        if not _is_contract_scoped(d, catalog_names):
            continue
        out.append(d)
    return out


# --- Mode: pr-time ---


def run_pr_time(
    overlay_dir: str,
    env: str,
    catalog: ServicesCatalog,
):
    """Returns (findings, exec_error_str_or_None)."""
    findings: list[dict] = []

    try:
        docs = _kustomize_render(overlay_dir)
    except RuntimeError as exc:
        # PR-time render failure is a drift bug (manifest broken), exit 1.
        return [
            make_finding(
                "P1",
                "render_failed",
                "(overlay)",
                f"{overlay_dir}: {exc}",
            )
        ], None

    rendered = _filter_template_workloads(docs, catalog.all_names())
    rendered_by_name = {_deploy_name(d): d for d in rendered}

    # 1. enabled template-workload service → must render in overlay
    for svc in catalog.enabled_in(env):
        if svc.workload_kind not in TEMPLATE_WORKLOAD_KINDS:
            continue  # Job / external out of scope
        if svc.name not in rendered_by_name:
            findings.append(
                make_finding(
                    "P1",
                    "missing_render",
                    svc.name,
                    f"catalog enabled in {env} but no {svc.workload_kind} rendered by {overlay_dir}",
                )
            )

    # 2. rendered workload → must be in catalog + classified
    known = known_contracts()
    for name, workload in rendered_by_name.items():
        svc = catalog.get(name)
        if svc is None:
            findings.append(
                make_finding(
                    "P1",
                    "unknown_service",
                    name,
                    f"rendered in {overlay_dir} but absent from services.yaml — add catalog entry",
                )
            )
            continue
        if svc.probe_contract not in known:
            findings.append(
                make_finding(
                    "P1",
                    "uncategorized_probe_contract",
                    name,
                    f"probe_contract={svc.probe_contract!r} unrecognized",
                )
            )

    # 3. probe contract assertion for enabled + non-exempt template workloads
    for svc in catalog.enabled_in(env):
        if svc.probe_contract == EXEMPT_CONTRACT:
            continue
        if svc.workload_kind not in TEMPLATE_WORKLOAD_KINDS:
            continue
        workload = rendered_by_name.get(svc.name)
        if workload is None:
            continue  # already flagged in step 1
        findings.extend(assert_probe_contract(workload, svc.probe_contract, svc.name))

    return findings, None


# --- Mode: runtime ---


def run_runtime(
    overlay_dir: str,
    context: str,
    namespace: str,
    env: str,
    catalog: ServicesCatalog,
    rs_split_grace_seconds: int = 300,
):
    """Returns (findings, exec_error_str_or_None).

    Codex 019e2327 review #2 — exec errors must NOT be downgraded into
    P1 findings; the caller emits exit 3 so wrappers can distinguish "drift"
    from "gate-broken / cluster unreachable".
    """
    findings: list[dict] = []

    try:
        docs = _kustomize_render(overlay_dir)
        live_deployments = _kubectl_get_deployments_and_statefulsets(context, namespace)
        replicasets = _kubectl_get_replicasets(context, namespace)
    except RuntimeError as exc:
        return [], str(exc)

    catalog_names = catalog.all_names()
    rendered_by_name = {
        _deploy_name(d): d
        for d in _filter_template_workloads(docs, catalog_names)
    }
    live_by_name = {
        _deploy_name(d): d
        for d in live_deployments
        if _is_contract_scoped(d, catalog_names)
    }

    # 6. Workload spec drift — semantic template diff (Deployment + StatefulSet)
    for svc in catalog.enabled_in(env):
        if svc.workload_kind not in TEMPLATE_WORKLOAD_KINDS:
            continue
        desired = rendered_by_name.get(svc.name)
        live = live_by_name.get(svc.name)
        if desired is None:
            findings.append(
                make_finding(
                    "P1",
                    "missing_render",
                    svc.name,
                    f"catalog enabled but no Deployment rendered for {svc.name}",
                )
            )
            continue
        if live is None:
            findings.append(
                make_finding(
                    "P2",
                    "service_missing_live",
                    svc.name,
                    f"catalog enabled but no live Deployment in cluster",
                )
            )
            continue
        diffs = semantic_diff(desired, live)
        for path, desired_val, live_val in diffs:
            findings.append(
                make_finding(
                    "P1",
                    "deploy_spec_drift",
                    svc.name,
                    f"{path}: desired={_short(desired_val)}, live={_short(live_val)}",
                    diff_path=path,
                    details={
                        "desired": _short(desired_val, limit=500),
                        "live": _short(live_val, limit=500),
                    },
                )
            )

    # 7. ReplicaSet split detection (ownerReferences authoritative)
    findings.extend(
        _check_rs_split(
            live_deployments,
            replicasets,
            rs_split_grace_seconds,
            contract_names=catalog_names,
        )
    )

    return findings, None


def _short(value: Any, limit: int = 80) -> str:
    text = json.dumps(value, default=str, sort_keys=True)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _check_rs_split(
    live_deployments: list[dict],
    replicasets: list[dict],
    grace_seconds: int,
    contract_names: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    deploy_uid_to_name: dict[str, str] = {}
    for d in live_deployments:
        if not _is_contract_scoped(d, contract_names):
            continue
        uid = (d.get("metadata") or {}).get("uid")
        name = _deploy_name(d)
        if uid and name:
            deploy_uid_to_name[uid] = name

    # Group ReplicaSets by ownerReference UID → Deployment
    rs_by_deploy: dict[str, list[dict]] = {}
    for rs in replicasets:
        owners = (rs.get("metadata") or {}).get("ownerReferences") or []
        for owner in owners:
            if owner.get("kind") == "Deployment":
                uid = owner.get("uid")
                if uid in deploy_uid_to_name:
                    rs_by_deploy.setdefault(uid, []).append(rs)

    now = datetime.now(timezone.utc)
    for deploy_uid, rss in rs_by_deploy.items():
        name = deploy_uid_to_name.get(deploy_uid, "<unknown>")
        active = [r for r in rss if ((r.get("spec") or {}).get("replicas") or 0) > 0]
        if len(active) <= 1:
            continue
        # Pick newest by creationTimestamp
        def _ts(r: dict):
            return (r.get("metadata") or {}).get("creationTimestamp", "")

        newest = max(active, key=_ts)
        ready = (newest.get("status") or {}).get("readyReplicas") or 0
        creation = _ts(newest)
        try:
            created = datetime.strptime(creation, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            created = now
        age_seconds = (now - created).total_seconds()

        if ready == 0 and age_seconds > grace_seconds:
            findings.append(
                make_finding(
                    "P1",
                    "replicaset_split_stalled",
                    name,
                    f"{len(active)} active ReplicaSets; newest {_rs_name(newest)} "
                    f"ready=0 age={int(age_seconds)}s (> {grace_seconds}s grace)",
                    details={
                        "active_rs_count": len(active),
                        "newest_rs": _rs_name(newest),
                        "age_seconds": int(age_seconds),
                    },
                )
            )
    return findings


def _rs_name(rs: dict) -> str:
    return (rs.get("metadata") or {}).get("name", "<unnamed>")


# --- CLI ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--mode", choices=["pr-time", "runtime"], required=True)
    parser.add_argument("--env", choices=["test", "prod"], required=True)
    parser.add_argument(
        "--render-source",
        required=True,
        help="kustomize overlay directory (e.g. kustomize/overlays/test)",
    )
    parser.add_argument(
        "--live-context",
        help="kubectl context for runtime mode (e.g. k3d-test)",
    )
    parser.add_argument(
        "--live-namespace",
        help="kubectl namespace for runtime mode (e.g. platform-test)",
    )
    parser.add_argument(
        "--catalog",
        default="docs/operations/services.yaml",
        help="path to services.yaml",
    )
    parser.add_argument("--output", choices=["json", "text"], default="text")
    parser.add_argument(
        "--rs-split-grace-seconds",
        type=int,
        default=300,
        help="ignore ReplicaSet split younger than this (transient rollout, default 300s)",
    )

    args = parser.parse_args(argv)

    try:
        catalog = ServicesCatalog.from_yaml(args.catalog)
    except (CatalogValidationError, FileNotFoundError) as exc:
        _err(f"catalog load failed: {exc}")
        return 3

    if args.mode == "pr-time":
        findings, exec_error = run_pr_time(args.render_source, args.env, catalog)
    else:
        if not args.live_context or not args.live_namespace:
            _err("runtime mode requires --live-context and --live-namespace")
            return EXEC_ERROR_EXIT
        findings, exec_error = run_runtime(
            overlay_dir=args.render_source,
            context=args.live_context,
            namespace=args.live_namespace,
            env=args.env,
            catalog=catalog,
            rs_split_grace_seconds=args.rs_split_grace_seconds,
        )

    if exec_error:
        _err(f"runtime exec error: {exec_error}")
        if args.output == "json":
            sys.stdout.write(
                json.dumps({"env": args.env, "exec_error": exec_error, "findings": []})
            )
            sys.stdout.write("\n")
        return EXEC_ERROR_EXIT

    return _emit(findings, args.output, args.env)


def _emit(findings: list[dict], output: str, env: str) -> int:
    if output == "json":
        sys.stdout.write(json.dumps({"env": env, "findings": findings}, indent=2))
        sys.stdout.write("\n")
    else:
        if not findings:
            print(f"[check_deployment_contracts] {env}: clean (0 findings)")
        else:
            print(f"[check_deployment_contracts] {env}: {len(findings)} finding(s)")
            for f in findings:
                print(f"  [{f['class']}] {f['kind']} {f['service']}: {f['message']}")

    has_p1 = any(f["class"] == "P1" for f in findings)
    has_p2 = any(f["class"] == "P2" for f in findings)
    if has_p1:
        return 1
    if has_p2:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover (CLI entry)
    raise SystemExit(main())
