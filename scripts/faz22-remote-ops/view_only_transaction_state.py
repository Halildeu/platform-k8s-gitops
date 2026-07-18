#!/usr/bin/env python3
"""Atomic, content-addressed state ledger for one VIEW_ONLY transaction.

This runner-local ledger detects corruption and impossible lifecycle sequences. It is
not a cryptographic acceptance signature; an external signed authority receipt must
bind its final artifact digest to the protected workflow run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "faz22.6.viewOnlyTransactionState.v1"
SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
REASON_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SHA_RE = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PILOT_SECONDS = {300, 600, 900, 1200, 1800}
UTC_SECONDS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

TRANSITIONS: dict[str, set[str]] = {
    "INIT": {"PREFLIGHT_VERIFIED"},
    "PREFLIGHT_VERIFIED": {"DECISION_AUTHORIZED"},
    "DECISION_AUTHORIZED": {"LIVE_REVALIDATED", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "LIVE_REVALIDATED": {"ACTIVATED", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "ACTIVATED": {"CONSENT_PENDING", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "CONSENT_PENDING": {"EVIDENCE_COLLECTED", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "EVIDENCE_COLLECTED": {"EVIDENCE_VERIFIED", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "EVIDENCE_VERIFIED": {"ARTIFACTS_STAGED", "FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"},
    "FAILURE_CAPTURED": {"ARTIFACTS_STAGED", "ARTIFACTS_STAGE_FAILED"},
    "ARTIFACTS_STAGE_FAILED": {"ROLLBACK_PENDING"},
    "ARTIFACTS_STAGED": {"ROLLBACK_PENDING"},
    "ROLLBACK_PENDING": {"ROLLED_BACK"},
    "ROLLED_BACK": {"COMPLETED", "FAILED_CLEAN"},
    "COMPLETED": set(),
    "FAILED_CLEAN": set(),
}


class StateError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def epoch_now() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def require_sha256(value: str, field: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise StateError(f"{field} must be canonical sha256")
    return value


def require_reason(value: str) -> str:
    if not REASON_RE.fullmatch(value):
        raise StateError("reason code is invalid")
    return value


def parse_observed_at(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not UTC_SECONDS_RE.fullmatch(value):
        raise StateError("checkpoint observedAt must be RFC3339 UTC seconds")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as error:
        raise StateError("checkpoint observedAt is not a real UTC timestamp") from error


def checkpoint(
    sequence: int,
    state: str,
    reason: str,
    payload: str,
    previous: str | None,
    binding_sha256: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "sequence": sequence,
        "state": state,
        "observedAt": utc_now(),
        "reasonCode": require_reason(reason),
        "payloadSha256": require_sha256(payload, "payload sha256"),
        "bindingSha256": require_sha256(binding_sha256, "binding sha256"),
        "previousCheckpointSha256": previous,
    }
    item["checkpointSha256"] = digest(item)
    return item


def validate_state(value: dict[str, Any]) -> None:
    if set(value) != {"schemaVersion", "binding", "currentState", "sequence", "reasonCode", "checkpoints"}:
        raise StateError("state contains missing or additional top-level fields")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise StateError("state schema version mismatch")
    binding = value["binding"]
    expected_binding = {
        "repository",
        "workflowRef",
        "headSha",
        "runId",
        "runAttempt",
        "endpointIdSha256",
        "deviceHostnameSha256",
        "policySha256",
        "maskPolicySha256",
        "pilotSeconds",
        "preflightSha256",
        "authorizationSha256",
        "watchdogExpiresEpoch",
        "sessionSha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding:
        raise StateError("state binding contains missing or additional fields")
    if not REPOSITORY_RE.fullmatch(binding["repository"]):
        raise StateError("repository binding is invalid")
    if not isinstance(binding["workflowRef"], str) or not 1 <= len(binding["workflowRef"]) <= 512:
        raise StateError("workflow ref binding is invalid")
    if not SHA_RE.fullmatch(binding["headSha"]):
        raise StateError("head sha binding is invalid")
    for name in ("runId", "runAttempt"):
        if not isinstance(binding[name], int) or isinstance(binding[name], bool) or binding[name] < 1:
            raise StateError(f"{name} binding is invalid")
    for name in (
        "endpointIdSha256",
        "deviceHostnameSha256",
        "policySha256",
        "maskPolicySha256",
        "preflightSha256",
    ):
        require_sha256(binding[name], name)
    if binding["pilotSeconds"] not in PILOT_SECONDS:
        raise StateError("pilot seconds binding is invalid")
    for name in ("authorizationSha256", "sessionSha256"):
        if binding[name] is not None:
            require_sha256(binding[name], name)
    expiry = binding["watchdogExpiresEpoch"]
    if expiry is not None and (not isinstance(expiry, int) or isinstance(expiry, bool) or expiry < 1):
        raise StateError("watchdog expiry binding is invalid")
    authorization_bound = binding["authorizationSha256"] is not None and expiry is not None
    if (binding["authorizationSha256"] is None) != (expiry is None):
        raise StateError("authorization digest and watchdog expiry must be bound together")
    if value["currentState"] not in TRANSITIONS:
        raise StateError("current state is invalid")
    require_reason(value["reasonCode"])
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, list) or not checkpoints:
        raise StateError("checkpoint chain is empty")
    if value["sequence"] != len(checkpoints) - 1:
        raise StateError("checkpoint sequence is not contiguous")
    previous = None
    previous_observed_at: dt.datetime | None = None
    authorization_seen = False
    evidence_seen = False
    failure_seen = False
    for index, item in enumerate(checkpoints):
        expected_keys = {
            "sequence",
            "state",
            "observedAt",
            "reasonCode",
            "payloadSha256",
            "bindingSha256",
            "previousCheckpointSha256",
            "checkpointSha256",
        }
        if not isinstance(item, dict) or set(item) != expected_keys or item["sequence"] != index:
            raise StateError("checkpoint shape or sequence is invalid")
        if item["state"] not in TRANSITIONS:
            raise StateError("checkpoint state is invalid")
        if item["state"] == "DECISION_AUTHORIZED":
            authorization_seen = True
        if item["state"] == "EVIDENCE_COLLECTED":
            evidence_seen = True
        if item["state"] in {"FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"}:
            failure_seen = True
        require_reason(item["reasonCode"])
        require_sha256(item["payloadSha256"], "checkpoint payload sha256")
        require_sha256(item["bindingSha256"], "checkpoint binding sha256")
        if item["previousCheckpointSha256"] != previous:
            raise StateError("checkpoint previous digest mismatch")
        unsigned = dict(item)
        observed_digest = unsigned.pop("checkpointSha256")
        require_sha256(observed_digest, "checkpoint sha256")
        if digest(unsigned) != observed_digest:
            raise StateError("checkpoint digest mismatch")
        observed_at = parse_observed_at(item["observedAt"])
        if previous_observed_at is not None and observed_at < previous_observed_at:
            raise StateError("checkpoint observedAt values are not monotonic")
        previous_observed_at = observed_at
        historical_binding = dict(binding)
        if not authorization_seen:
            historical_binding["authorizationSha256"] = None
            historical_binding["watchdogExpiresEpoch"] = None
        if not evidence_seen:
            historical_binding["sessionSha256"] = None
        if item["bindingSha256"] != digest(historical_binding):
            raise StateError("checkpoint binding digest is inconsistent with its lifecycle state")
        previous = observed_digest
        if index == 0:
            if item["state"] != "INIT" or item["previousCheckpointSha256"] is not None:
                raise StateError("checkpoint chain must start at INIT")
        elif item["state"] not in TRANSITIONS[checkpoints[index - 1]["state"]]:
            raise StateError("checkpoint transition is invalid")
    if checkpoints[-1]["state"] != value["currentState"]:
        raise StateError("current state does not match the checkpoint tail")
    if checkpoints[-1]["reasonCode"] != value["reasonCode"]:
        raise StateError("current reason does not match the checkpoint tail")
    if checkpoints[-1]["bindingSha256"] != digest(binding):
        raise StateError("current binding digest does not match the checkpoint tail")
    if checkpoints[0]["payloadSha256"] != binding["preflightSha256"]:
        raise StateError("initial checkpoint is not bound to the preflight")
    if authorization_seen != authorization_bound:
        raise StateError("authorization lifecycle and final binding disagree")
    if evidence_seen != (binding["sessionSha256"] is not None):
        raise StateError("evidence lifecycle and session binding disagree")
    if value["currentState"] == "COMPLETED":
        required_success = {"EVIDENCE_COLLECTED", "EVIDENCE_VERIFIED", "ARTIFACTS_STAGED", "ROLLED_BACK"}
        observed_states = {item["state"] for item in checkpoints}
        if failure_seen or not required_success.issubset(observed_states):
            raise StateError("COMPLETED is reserved for the verified success path")
    if value["currentState"] == "FAILED_CLEAN" and not failure_seen:
        raise StateError("FAILED_CLEAN requires a recorded failure checkpoint")


def read_state(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        os.close(descriptor)
        raise StateError("state file must be a private regular file")
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        value = json.load(handle)
    validate_state(value)
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    validate_state(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_metadata = path.parent.stat()
    if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_IMODE(parent_metadata.st_mode) & 0o077:
        raise StateError("state parent directory must be private")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(args: argparse.Namespace) -> None:
    path = Path(args.output)
    if path.exists() or path.is_symlink():
        raise StateError("state output already exists")
    binding = {
        "repository": args.repository,
        "workflowRef": args.workflow_ref,
        "headSha": args.head_sha,
        "runId": args.run_id,
        "runAttempt": args.run_attempt,
        "endpointIdSha256": args.endpoint_id_sha256,
        "deviceHostnameSha256": args.device_hostname_sha256,
        "policySha256": args.policy_sha256,
        "maskPolicySha256": args.mask_policy_sha256,
        "pilotSeconds": args.pilot_seconds,
        "preflightSha256": args.preflight_sha256,
        "authorizationSha256": None,
        "watchdogExpiresEpoch": None,
        "sessionSha256": None,
    }
    initial = checkpoint(
        0,
        "INIT",
        "transaction-initialized",
        args.preflight_sha256,
        None,
        digest(binding),
    )
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "binding": binding,
        "currentState": "INIT",
        "sequence": 0,
        "reasonCode": "transaction-initialized",
        "checkpoints": [initial],
    }
    atomic_write(path, state)


def transition(args: argparse.Namespace) -> None:
    path = Path(args.state_file)
    state = read_state(path)
    current = state["currentState"]
    target = args.to
    if target not in TRANSITIONS[current]:
        raise StateError(f"transition {current} -> {target} is not allowed")
    if target == "DECISION_AUTHORIZED":
        if not args.authorization_sha256 or not args.watchdog_expires_epoch:
            raise StateError("decision transition requires authorization and watchdog expiry")
        if args.watchdog_expires_epoch <= epoch_now():
            raise StateError("decision authorization is already expired")
        state["binding"]["authorizationSha256"] = require_sha256(
            args.authorization_sha256, "authorization sha256"
        )
        state["binding"]["watchdogExpiresEpoch"] = args.watchdog_expires_epoch
    elif args.authorization_sha256 or args.watchdog_expires_epoch:
        raise StateError("authorization binding may only be set at DECISION_AUTHORIZED")
    if target == "EVIDENCE_COLLECTED":
        if not args.session_sha256:
            raise StateError("evidence transition requires a session sha256")
        state["binding"]["sessionSha256"] = require_sha256(args.session_sha256, "session sha256")
    elif args.session_sha256:
        raise StateError("session binding may only be set at EVIDENCE_COLLECTED")
    expiry = state["binding"]["watchdogExpiresEpoch"]
    if target in {"LIVE_REVALIDATED", "ACTIVATED", "CONSENT_PENDING", "EVIDENCE_COLLECTED", "EVIDENCE_VERIFIED"}:
        if expiry is None or expiry <= epoch_now():
            raise StateError("authorization/watchdog TTL expired")
    next_sequence = state["sequence"] + 1
    item = checkpoint(
        next_sequence,
        target,
        args.reason_code,
        args.payload_sha256,
        state["checkpoints"][-1]["checkpointSha256"],
        digest(state["binding"]),
    )
    state["currentState"] = target
    state["sequence"] = next_sequence
    state["reasonCode"] = args.reason_code
    state["checkpoints"].append(item)
    atomic_write(path, state)


def verify(args: argparse.Namespace) -> None:
    state = read_state(Path(args.state_file))
    expected = {
        "repository": args.repository,
        "workflowRef": args.workflow_ref,
        "headSha": args.head_sha,
        "runId": args.run_id,
        "runAttempt": args.run_attempt,
    }
    for field, value in expected.items():
        if value is not None and state["binding"][field] != value:
            raise StateError(f"state binding mismatch: {field}")
    if args.expected_state and state["currentState"] != args.expected_state:
        raise StateError("state is not at the expected checkpoint")
    print(json.dumps({
        "state": state["currentState"],
        "checkpointSha256": state["checkpoints"][-1]["checkpointSha256"],
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--output", required=True)
    init.add_argument("--repository", required=True)
    init.add_argument("--workflow-ref", required=True)
    init.add_argument("--head-sha", required=True)
    init.add_argument("--run-id", type=int, required=True)
    init.add_argument("--run-attempt", type=int, required=True)
    init.add_argument("--endpoint-id-sha256", required=True)
    init.add_argument("--device-hostname-sha256", required=True)
    init.add_argument("--policy-sha256", required=True)
    init.add_argument("--mask-policy-sha256", required=True)
    init.add_argument("--pilot-seconds", type=int, required=True)
    init.add_argument("--preflight-sha256", required=True)
    init.set_defaults(handler=initialize)

    move = sub.add_parser("transition")
    move.add_argument("--state-file", required=True)
    move.add_argument("--to", choices=sorted(TRANSITIONS), required=True)
    move.add_argument("--reason-code", required=True)
    move.add_argument("--payload-sha256", required=True)
    move.add_argument("--authorization-sha256")
    move.add_argument("--watchdog-expires-epoch", type=int)
    move.add_argument("--session-sha256")
    move.set_defaults(handler=transition)

    check = sub.add_parser("verify")
    check.add_argument("--state-file", required=True)
    check.add_argument("--repository")
    check.add_argument("--workflow-ref")
    check.add_argument("--head-sha")
    check.add_argument("--run-id", type=int)
    check.add_argument("--run-attempt", type=int)
    check.add_argument("--expected-state", choices=sorted(TRANSITIONS))
    check.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError, StateError) as error:
        print(f"view-only-transaction-state: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
