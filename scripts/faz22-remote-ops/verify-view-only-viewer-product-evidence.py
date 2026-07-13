#!/usr/bin/env python3
"""Fail-closed verifier for Faz 22.6 VIEW_ONLY product-channel evidence.

The input is a redacted metadata envelope. It must not contain frame bytes,
screen content, credentials, tokens, cookies or private endpoints. This gate
proves a bounded one-viewer test pilot only; it cannot claim production, broad
rollout, recording mode, legal acceptance or multi-viewer fanout.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


EVIDENCE_SCHEMA = "faz22.6.viewOnlyViewerProductEvidence.v1"
VERIFIER_SCHEMA = "faz22.6.viewOnlyViewerProductEvidenceVerifier.v1"
MARKER = "F22_6_VIEW_ONLY_VIEWER_PRODUCT_ACCEPTANCE: v1"

FIRST_FRAME_MAX_MS = 5_000
STEADY_P95_MAX_MS = 2_000
MAX_DROP_RATE = 0.20
MAX_RECONNECTS = 1
MIN_STEADY_SAMPLES = 5
MIN_SOAK_SECONDS = 300

PASS_KEYS = {
    "noAuth",
    "wrongRole",
    "wrongTenant",
    "wrongDevice",
    "expired",
    "revoked",
    "replayed",
    "overConcurrency",
    "disconnectedViewer",
}
TERMINATION_KEYS = {
    "localAbort",
    "killOrRevoke",
    "ttlExpiry",
    "heartbeatLoss",
    "consentWithdrawal",
    "indicatorLoss",
}
NO_INPUT_KEYS = {
    "keyboard",
    "mouse",
    "clipboard",
    "fileTransfer",
    "credentialEntry",
    "shell",
    "portForward",
    "hiddenControl",
}
BOUNDARY_FALSE_KEYS = {
    "productionReady",
    "broadRolloutReady",
    "multiViewerFanoutProven",
    "recordingEnabled",
    "legalAcceptance",
    "secretsIncluded",
    "rawScreenIncluded",
}
SENSITIVE_KEYS = {
    "access_token", "refresh_token", "token", "authorization", "bearer", "jwt",
    "credential", "password", "secret", "cookie", "private_key", "data_b64",
    "payload", "frame_bytes", "screen_content", "raw_screen", "image_bytes",
}
SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
)
SAFE_REF = re.compile(r"^(github|github-actions|artifact|operator|protected|runbook)://[A-Za-z0-9_.:@/#%+-]{3,240}$")
REQUIRED_REF_SCHEMES = {"github-actions", "artifact", "operator", "protected"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass
class Check:
    name: str
    passed: bool
    message: str


def add(checks: list[Check], name: str, passed: bool, message: str) -> None:
    checks.append(Check(name, passed, message))


def iter_values(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from iter_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, None, child
            yield from iter_values(child, child_path)


def normalized_key(key: str) -> str:
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return key.replace("-", "_").replace(".", "_").lower()


def check_sensitive(data: dict[str, Any], checks: list[Check]) -> None:
    findings: list[str] = []
    for path, key, value in iter_values(data):
        if key is not None and normalized_key(key) in SENSITIVE_KEYS:
            findings.append(f"{path}: forbidden key")
        if isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
            findings.append(f"{path}: secret/content-shaped value")
    add(checks, "redaction", not findings,
        "no secret or screen-content fields" if not findings else "; ".join(findings[:8]))


def object_at(data: dict[str, Any], key: str, checks: list[Check]) -> dict[str, Any]:
    value = data.get(key)
    ok = isinstance(value, dict)
    add(checks, f"{key}_shape", ok, f"{key} must be an object")
    return value if ok else {}


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None and value != "0" * 64


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def validate(data: dict[str, Any]) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    computed: dict[str, Any] = {}

    add(checks, "schema", data.get("schemaVersion") == EVIDENCE_SCHEMA,
        f"schemaVersion must be {EVIDENCE_SCHEMA}")
    add(checks, "environment", data.get("environment") == "test",
        "environment must be test")
    check_sensitive(data, checks)

    refs = data.get("evidenceRefs")
    refs_ok = isinstance(refs, list) and len(refs) >= 4 and all(
        isinstance(ref, str) and SAFE_REF.fullmatch(ref) for ref in refs
    )
    ref_schemes = {ref.split("://", 1)[0] for ref in refs} if refs_ok else set()
    refs_ok = refs_ok and REQUIRED_REF_SCHEMES.issubset(ref_schemes)
    add(checks, "evidence_refs", refs_ok,
        "safe github-actions, artifact, operator and protected evidence references are required")

    states = object_at(data, "states", checks)
    state_values: dict[str, int] = {}
    for key in ("captured", "brokerReceived", "viewerDelivered", "viewerRendered"):
        value = states.get(key)
        ok = isinstance(value, int) and not isinstance(value, bool) and value > 0
        add(checks, f"state_{key}", ok, f"states.{key} must be a positive integer")
        state_values[key] = value if ok else 0
    monotonic = (
        state_values["captured"] >= state_values["brokerReceived"]
        >= state_values["viewerDelivered"] >= state_values["viewerRendered"] > 0
    )
    add(checks, "state_chain", monotonic,
        "CAPTURED >= BROKER_RECEIVED >= VIEWER_DELIVERED >= VIEWER_RENDERED > 0")

    quality = object_at(data, "quality", checks)
    first = number(quality.get("firstFrameAgeMillis"))
    add(checks, "first_frame_slo", first is not None and 0 < first <= FIRST_FRAME_MAX_MS,
        f"firstFrameAgeMillis must be > 0 and <= {FIRST_FRAME_MAX_MS}")
    ages_raw = quality.get("steadyFrameAgeMillis")
    ages = [number(v) for v in ages_raw] if isinstance(ages_raw, list) else []
    ages_ok = len(ages) >= MIN_STEADY_SAMPLES and all(v is not None and v >= 0 for v in ages)
    add(checks, "steady_samples", ages_ok,
        f"at least {MIN_STEADY_SAMPLES} non-negative steady frame-age samples are required")
    numeric_ages = [float(v) for v in ages if v is not None and v >= 0]
    p50 = percentile(numeric_ages, 0.50) if numeric_ages else None
    p95 = percentile(numeric_ages, 0.95) if numeric_ages else None
    computed["steadyFrameAgeP50Millis"] = p50
    computed["steadyFrameAgeP95Millis"] = p95
    add(checks, "steady_p95_slo", p95 is not None and p95 <= STEADY_P95_MAX_MS,
        f"steady frame-age p95 must be <= {STEADY_P95_MAX_MS}")

    broker_count = state_values["brokerReceived"]
    delivered_count = state_values["viewerDelivered"]
    drop_rate = (broker_count - delivered_count) / broker_count if broker_count else 1.0
    computed["dropRate"] = round(drop_rate, 6)
    add(checks, "drop_rate_slo", 0 <= drop_rate <= MAX_DROP_RATE,
        f"broker-to-viewer drop rate must be <= {MAX_DROP_RATE:.0%}")
    reconnects = quality.get("reconnectCount")
    add(checks, "reconnect_slo", isinstance(reconnects, int) and 0 <= reconnects <= MAX_RECONNECTS,
        f"reconnectCount must be <= {MAX_RECONNECTS}")
    add(checks, "backpressure_contract",
        quality.get("backpressureMode") == "latest-wins-single-slot"
        and quality.get("maxPendingFrames") == 1,
        "latest-wins-single-slot with maxPendingFrames=1 is required")
    soak = number(quality.get("soakSeconds"))
    add(checks, "bounded_soak", soak is not None and soak >= MIN_SOAK_SECONDS,
        f"soakSeconds must be >= {MIN_SOAK_SECONDS}")

    negative = object_at(data, "negativeMatrix", checks)
    for key in sorted(PASS_KEYS):
        add(checks, f"negative_{key}", negative.get(key) == "pass", f"negativeMatrix.{key} must pass")

    termination = object_at(data, "termination", checks)
    for key in sorted(TERMINATION_KEYS):
        add(checks, f"termination_{key}", termination.get(key) == "pass", f"termination.{key} must pass")

    channels = object_at(data, "inputChannels", checks)
    for key in sorted(NO_INPUT_KEYS):
        add(checks, f"no_input_{key}", channels.get(key) is False, f"inputChannels.{key} must be false")

    dlp = object_at(data, "dlp", checks)
    add(checks, "dlp_delivered_path",
        dlp.get("deliveredPathProven") is True
        and dlp.get("rawContentIncluded") is False
        and valid_sha256(dlp.get("maskedFrameSha256")),
        "DLP must be proven on delivered path with hash-only evidence")

    persistence = object_at(data, "persistence", checks)
    add(checks, "recording_off_no_persistence",
        persistence.get("recordingMode") == "disabled"
        and persistence.get("contentPersisted") is False
        and persistence.get("contentStorageWrites") == 0,
        "recording disabled must prove zero content persistence")

    browser = object_at(data, "browser", checks)
    add(checks, "browser_render",
        browser.get("imageElementRendered") is True
        and browser.get("pixelCheckPassed") is True
        and browser.get("renderAckAcceptedCount") == state_values["viewerRendered"]
        and browser.get("consoleErrorCount") == 0
        and valid_sha256(browser.get("screenshotSha256")),
        "browser render, independent pixel check, accepted acknowledgement, clean console and screenshot hash must agree")

    broker = object_at(data, "broker", checks)
    add(checks, "broker_metric_correlation",
        broker.get("framesSentMetricDelta") == state_values["viewerDelivered"]
        and broker.get("renderAckAcceptedMetricDelta") == state_values["viewerRendered"]
        and isinstance(broker.get("renderAckRejectedMetricDelta"), int)
        and not isinstance(broker.get("renderAckRejectedMetricDelta"), bool)
        and broker.get("renderAckRejectedMetricDelta") >= 1
        and valid_sha256(broker.get("metricsSnapshotSha256")),
        "broker sent/accepted metric deltas must correlate, rejected ACKs must be observed, and snapshot hash must be valid")

    images = data.get("d30Images")
    images_ok = isinstance(images, list) and len(images) >= 2
    image_components: set[str] = set()
    if images_ok:
        for image in images:
            images_ok = images_ok and isinstance(image, dict)
            if isinstance(image, dict):
                component = image.get("component")
                desired = image.get("desiredDigest")
                live = image.get("liveImageIdDigest")
                images_ok = images_ok and component in {"backend", "web"} and component not in image_components
                if component in {"backend", "web"}:
                    image_components.add(component)
                images_ok = images_ok and isinstance(desired, str) and DIGEST.fullmatch(desired) is not None
                images_ok = images_ok and desired == live
        images_ok = images_ok and image_components == {"backend", "web"}
    add(checks, "d30_image_parity", images_ok, "backend and web desired digests must equal live imageID digests")

    audit = object_at(data, "audit", checks)
    add(checks, "audit_correlation",
        audit.get("viewStartPresent") is True
        and audit.get("viewStartCommittedBeforeFirstDelivered") is True
        and audit.get("viewStopPresent") is True
        and audit.get("hashChainVerified") is True
        and audit.get("framesDelivered") == state_values["viewerDelivered"]
        and audit.get("framesRenderAcknowledged") == state_values["viewerRendered"]
        and valid_sha256(audit.get("snapshotSha256")),
        "committed-before-delivery VIEW_START and VIEW_STOP hash-chain counts must correlate with delivery and render")

    boundaries = object_at(data, "boundaries", checks)
    for key in sorted(BOUNDARY_FALSE_KEYS):
        add(checks, f"boundary_{key}", boundaries.get(key) is False, f"boundaries.{key} must be false")

    return checks, computed


def result_document(checks: list[Check], computed: dict[str, Any]) -> dict[str, Any]:
    passed = all(check.passed for check in checks)
    result: dict[str, Any] = {
        "schemaVersion": VERIFIER_SCHEMA,
        "status": "pass" if passed else "fail",
        "computed": computed,
        "checks": [asdict(check) for check in checks],
    }
    if passed:
        result["marker"] = MARKER
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Evidence JSON; stdin when omitted")
    parser.add_argument("--output", type=Path, help="Optional verifier result JSON")
    args = parser.parse_args()
    try:
        raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"evidence read failed: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("top-level evidence must be an object", file=sys.stderr)
        return 2

    checks, computed = validate(data)
    result = result_document(checks, computed)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
