#!/usr/bin/env python3
"""Recycle pods that kubelet on a k3d node has stopped retrying (#3888).

Why this exists
---------------
After the 2026-10-15 aiserver reboot, containerd inside the k3d node kept
stale sandbox/container name reservations. kubelet then failed every attempt
with ``failed to reserve sandbox name ... is reserved for <id>`` (~43k
retries over 6 days) and never recovered on its own: k3d-test lost 30 pods
(ingress included, testai 502) and k3d-prod lost ESO, grafana and
tigera-operator. Deleting the pod fixes it immediately because the
replacement pod gets a new UID, hence a new sandbox name.

Selection (deliberately narrow — normal CrashLoopBackOff is left alone):

1. ``reserved_name``: any container is waiting with a message containing
   ``failed to reserve`` (sandbox or container name collision).
2. ``abandoned``: pod owned by a ReplicaSet/StatefulSet/DaemonSet whose every
   container is *terminated* (not waiting, not running) for longer than
   ``--grace-minutes``. A controller-owned pod with restartPolicy Always is
   never legitimately left terminated; kubelet normally flips it to waiting
   (CrashLoopBackOff) within seconds.

Default is dry-run; ``--apply`` deletes. ``--max-deletes`` caps each context
per run so a mis-selection can never mass-delete a namespace.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

CONTROLLER_KINDS = {"ReplicaSet", "StatefulSet", "DaemonSet"}
RESERVE_MARKER = "failed to reserve"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _owner_kind(pod: dict[str, Any]) -> str:
    owners = pod.get("metadata", {}).get("ownerReferences") or []
    return owners[0].get("kind", "") if owners else ""


def classify(pod: dict[str, Any], now: datetime, grace_minutes: int) -> str | None:
    """Return the reason a pod should be recycled, or None to leave it alone."""
    meta = pod.get("metadata", {})
    if meta.get("deletionTimestamp"):
        return None
    status = pod.get("status", {})
    if status.get("phase") == "Succeeded" and _owner_kind(pod) not in CONTROLLER_KINDS:
        return None  # Job/CronJob pods legitimately complete
    statuses = (status.get("initContainerStatuses") or []) + (status.get("containerStatuses") or [])

    for cs in statuses:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        if RESERVE_MARKER in (waiting.get("message") or ""):
            return "reserved_name"

    if _owner_kind(pod) not in CONTROLLER_KINDS:
        return None
    main = status.get("containerStatuses") or []
    if not main:
        return None
    finished: list[datetime] = []
    for cs in main:
        terminated = (cs.get("state") or {}).get("terminated")
        if not terminated:
            return None  # running or waiting → kubelet is still working on it
        ts = _parse_ts(terminated.get("finishedAt"))
        if ts is None:
            return None
        finished.append(ts)
    if (now - max(finished)).total_seconds() >= grace_minutes * 60:
        return "abandoned"
    return None


def select(pods: list[dict[str, Any]], now: datetime, grace_minutes: int) -> list[tuple[str, str, str]]:
    out = []
    for pod in pods:
        reason = classify(pod, now, grace_minutes)
        if reason:
            meta = pod["metadata"]
            out.append((meta["namespace"], meta["name"], reason))
    return out


def _kubectl(context: str, *args: str) -> str:
    return subprocess.run(
        ["kubectl", "--context", context, *args],
        check=True, capture_output=True, text=True, timeout=60,
    ).stdout


def run(contexts: list[str], apply: bool, grace_minutes: int, max_deletes: int) -> int:
    now = datetime.now(timezone.utc)
    rc = 0
    for ctx in contexts:
        try:
            pods = json.loads(_kubectl(ctx, "get", "pods", "-A", "-o", "json"))["items"]
        except (subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
            print(json.dumps({"context": ctx, "event": "list_failed", "error": type(e).__name__}), flush=True)
            rc = 1
            continue
        picked = select(pods, now, grace_minutes)
        if len(picked) > max_deletes:
            print(json.dumps({"context": ctx, "event": "cap_exceeded", "candidates": len(picked),
                              "max_deletes": max_deletes}), flush=True)
            picked = picked[:max_deletes]
        for ns, name, reason in picked:
            event = {"context": ctx, "namespace": ns, "pod": name, "reason": reason,
                     "action": "delete" if apply else "dry-run"}
            if apply:
                try:
                    _kubectl(ctx, "-n", ns, "delete", "pod", name, "--wait=false")
                except subprocess.SubprocessError as e:
                    event["action"] = f"delete_failed:{type(e).__name__}"
                    rc = 1
            print(json.dumps(event), flush=True)
        print(json.dumps({"context": ctx, "event": "summary", "pods": len(pods), "selected": len(picked),
                          "apply": apply}), flush=True)
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--context", action="append", dest="contexts",
                   help="kubectl context (repeatable; default k3d-test and k3d-prod)")
    p.add_argument("--apply", action="store_true", help="delete selected pods (default: dry-run)")
    p.add_argument("--grace-minutes", type=int, default=10)
    p.add_argument("--max-deletes", type=int, default=40)
    a = p.parse_args(argv)
    return run(a.contexts or ["k3d-test", "k3d-prod"], a.apply, a.grace_minutes, a.max_deletes)


if __name__ == "__main__":
    sys.exit(main())
