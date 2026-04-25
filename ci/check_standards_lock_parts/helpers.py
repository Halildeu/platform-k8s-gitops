from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        default="",
        help="Target repo root to validate (default: current repository root).",
    )
    return parser.parse_args(argv)
def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
def _fail(error_code: str, message: str, *, details: dict[str, Any] | None = None) -> int:
    payload: dict[str, Any] = {
        "status": "FAIL",
        "error_code": error_code,
        "message": message,
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1
def _require_json_file(root: Path, rel_path: str, *, key: str) -> dict[str, Any] | None:
    path = root / rel_path
    if not path.exists():
        return None
    try:
        obj = _load_json(path)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None
