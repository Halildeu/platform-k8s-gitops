from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_LANES = ("unit", "database", "api", "contract", "integration", "e2e")


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _tail_preview(text: str, *, max_lines: int = 20, max_chars: int = 4000) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    if max_chars > 0:
        joined = "\n".join(lines)
        if len(joined) > max_chars:
            joined = joined[-max_chars:]
            lines = [line.rstrip() for line in joined.splitlines() if line.strip()]
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", required=True, choices=VALID_LANES)
    parser.add_argument("--config", default="ci/module_delivery_lanes.v1.json")
    parser.add_argument("--outdir", default=".cache/reports/module_delivery_lanes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = _repo_root()

    lane = str(args.lane).strip()
    config_path = Path(str(args.config).strip())
    config_path = (root / config_path).resolve() if not config_path.is_absolute() else config_path.resolve()

    if not config_path.exists():
        payload = {
            "status": "FAIL",
            "error_code": "LANE_CONFIG_MISSING",
            "lane": lane,
            "config_path": str(config_path),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    try:
        config_obj = _load_json(config_path)
    except Exception:
        payload = {
            "status": "FAIL",
            "error_code": "LANE_CONFIG_INVALID_JSON",
            "lane": lane,
            "config_path": str(config_path),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    lanes = config_obj.get("lanes") if isinstance(config_obj, dict) else None
    lane_obj = lanes.get(lane) if isinstance(lanes, dict) and isinstance(lanes.get(lane), dict) else {}
    command = str(lane_obj.get("command") or "").strip()
    if not command:
        payload = {
            "status": "FAIL",
            "error_code": "LANE_COMMAND_MISSING",
            "lane": lane,
            "config_path": str(config_path),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    timeout_seconds = int(lane_obj.get("timeout_seconds") or 900)
    if timeout_seconds <= 0:
        timeout_seconds = 900

    started_at = _now_iso_utc()
    started_ts = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return_code = int(proc.returncode)
        stdout_text = str(proc.stdout or "")
        stderr_text = str(proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout_text = str(exc.stdout or "")
        stderr_text = str(exc.stderr or "")

    duration_ms = int((time.time() - started_ts) * 1000)
    finished_at = _now_iso_utc()
    status = "OK" if return_code == 0 and not timed_out else "FAIL"

    outdir = Path(str(args.outdir).strip())
    outdir = (root / outdir).resolve() if not outdir.is_absolute() else outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    report_path = outdir / f"{lane}.v1.json"

    report = {
        "version": "v1",
        "kind": "module-delivery-lane-report",
        "lane": lane,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "return_code": return_code,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "command": command,
        "config_path": str(config_path),
        "stdout_tail": _tail_preview(stdout_text),
        "stderr_tail": _tail_preview(stderr_text),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    payload = {
        "status": status,
        "lane": lane,
        "return_code": return_code,
        "report_path": str(report_path),
        "timed_out": timed_out,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if status == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
