#!/usr/bin/env python3
"""Run a redacted MiniMax M3 review through the bundled headless transport.

The prompt is accepted only on stdin so it is not exposed in process argv. The
receipt reports the provider-returned model identity and never prints auth
material or provider error bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse


MODEL_REF = "minimax/MiniMax-M3"
EXPECTED_PROVIDER_NAME = "MiniMax"
EXPECTED_PROVIDER_HOST = "agent.minimax.io"
MAX_PROMPT_BYTES = 2_000_000
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
VERDICT_RE = re.compile(r"^VERDICT:\s*(AGREE|REVISE)\s*$", re.IGNORECASE | re.MULTILINE)


def mavis_data_dir() -> Path:
    configured = os.environ.get("__MAVIS_PARENT_DATA_DIR") or os.environ.get(
        "MAVIS_HOME"
    )
    return Path(configured).expanduser() if configured else Path.home() / ".mavis"


MAVIS_DATA_DIR = mavis_data_dir()
BUNDLED_SKILL = (
    MAVIS_DATA_DIR / ".builtin-skills/llm-call/scripts/llm_call.py"
)
AUTH_FILE = MAVIS_DATA_DIR / "local-runtime.auth.json"


def fail(code: str) -> NoReturn:
    print(json.dumps({"ok": False, "error": code}, ensure_ascii=False))
    raise SystemExit(1)


def load_bundled_module():
    if not BUNDLED_SKILL.is_file():
        fail("bundled_llm_call_missing")
    spec = importlib.util.spec_from_file_location(
        "mavis_bundled_llm_call", BUNDLED_SKILL
    )
    if spec is None or spec.loader is None:
        fail("bundled_llm_call_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_access_token() -> str:
    try:
        payload = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        token = payload["auth"]["accessToken"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        fail("mavis_auth_unavailable")
    if not isinstance(token, str) or not token.strip():
        fail("mavis_auth_unavailable")
    return token


def normalize_actual_model(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("provider_model_identity_missing")
    model = value.strip()
    return model if "/" in model else f"minimax/{model}"


def parse_verdict(result: str) -> str:
    matches = VERDICT_RE.findall(result)
    if len(matches) != 1:
        fail("provider_verdict_missing_or_ambiguous")
    nonempty_lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not nonempty_lines or not VERDICT_RE.fullmatch(nonempty_lines[-1]):
        fail("provider_verdict_not_terminal")
    for priority in ("P0", "P1", "P2"):
        if not re.search(rf"(?im)^.*\b{priority}\b", result):
            fail("provider_findings_sections_missing")
    return matches[0].upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    args = parser.parse_args()
    if args.max_tokens < 1 or args.max_tokens > 32_000:
        fail("invalid_max_tokens")
    if args.temperature < 0 or args.temperature > 1:
        fail("invalid_temperature")
    if args.timeout <= 0 or args.timeout > 600:
        fail("invalid_timeout")
    if bool(args.base_sha) != bool(args.head_sha):
        fail("base_and_head_sha_required_together")
    if args.base_sha and not COMMIT_SHA_RE.fullmatch(args.base_sha):
        fail("invalid_base_sha")
    if args.head_sha and not COMMIT_SHA_RE.fullmatch(args.head_sha):
        fail("invalid_head_sha")

    prompt = sys.stdin.read().strip()
    if not prompt:
        fail("stdin_prompt_required")
    prompt_bytes = prompt.encode("utf-8")
    if len(prompt_bytes) > MAX_PROMPT_BYTES:
        fail("stdin_prompt_too_large")
    scope_sha256 = hashlib.sha256(prompt_bytes).hexdigest()

    module = load_bundled_module()
    caller = module.LLMCaller()
    listed_models = {item["ref"] for item in caller.list_models()}
    if MODEL_REF not in listed_models:
        fail("required_model_not_listed")

    protocol_name, provider_config, model_config, model_id = caller.resolve(MODEL_REF)
    if protocol_name != "anthropic":
        fail("unexpected_minimax_protocol")
    if provider_config.get("name") != EXPECTED_PROVIDER_NAME:
        fail("unexpected_minimax_provider_config")
    protocol = module.PROTOCOLS[protocol_name]

    options = provider_config.get("options", {})
    base_url = options.get("baseURL", "")
    parsed_origin = urlparse(base_url) if isinstance(base_url, str) else None
    if (
        parsed_origin is None
        or parsed_origin.scheme != "https"
        or parsed_origin.hostname != EXPECTED_PROVIDER_HOST
    ):
        fail("invalid_provider_origin")

    headers = dict(options.get("headers", {}))
    if isinstance(model_config, dict) and model_config.get("headers"):
        headers.update(model_config["headers"])
    headers["Authorization"] = f"Bearer {load_access_token()}"
    model_options = (
        model_config.get("options", {}) if isinstance(model_config, dict) else {}
    )
    url, request_headers, body = protocol.build_request(
        base_url,
        model_id,
        [
            {
                "role": "system",
                "content": (
                    "You are a strict adversarial reviewer. Review only the supplied "
                    "redacted scope. Include explicit P0, P1 and P2 sections, then "
                    "end with exactly one terminal VERDICT: AGREE or VERDICT: REVISE."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        stream=False,
        extra_headers=headers,
        model_options=model_options,
    )

    try:
        with module.httpx.Client(timeout=args.timeout) as client:
            response = client.post(url, headers=request_headers, json=body)
    except module.httpx.HTTPError:
        fail("provider_transport_error")
    if response.status_code != 200:
        fail(f"provider_http_{response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        fail("provider_response_not_json")

    actual_model = normalize_actual_model(payload.get("model"))
    if actual_model != MODEL_REF:
        fail("provider_model_identity_mismatch")
    result = protocol.extract_text(payload).strip()
    if not result:
        fail("provider_response_empty")
    verdict = parse_verdict(result)

    print(
        json.dumps(
            {
                "ok": True,
                "provider": "minimax",
                "provider_claim_source": "trusted-bundled-config",
                "provider_origin_host": EXPECTED_PROVIDER_HOST,
                "requested_model": MODEL_REF,
                "actual_model": actual_model,
                "base_sha": args.base_sha,
                "head_sha": args.head_sha,
                "scope_sha256": scope_sha256,
                "verdict": verdict,
                "findings_present": True,
                "transport": "mavis-bundled-llm-call",
                "response": result,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
