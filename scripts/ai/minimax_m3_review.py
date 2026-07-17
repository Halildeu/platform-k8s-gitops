#!/usr/bin/env python3
"""Run a redacted MiniMax M3 review through the bundled headless transport.

The prompt is accepted only on stdin so it is not exposed in process argv. The
receipt reports the provider-returned model identity and never prints auth
material or provider error bodies.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import NoReturn


MODEL_REF = "minimax/MiniMax-M3"
BUNDLED_SKILL = (
    Path.home() / ".mavis/.builtin-skills/llm-call/scripts/llm_call.py"
)
AUTH_FILE = Path.home() / ".mavis/local-runtime.auth.json"


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.max_tokens < 1 or args.max_tokens > 32_000:
        fail("invalid_max_tokens")
    if args.temperature < 0 or args.temperature > 1:
        fail("invalid_temperature")
    if args.timeout <= 0 or args.timeout > 600:
        fail("invalid_timeout")

    prompt = sys.stdin.read().strip()
    if not prompt:
        fail("stdin_prompt_required")

    module = load_bundled_module()
    caller = module.LLMCaller()
    listed_models = {item["ref"] for item in caller.list_models()}
    if MODEL_REF not in listed_models:
        fail("required_model_not_listed")

    protocol_name, provider_config, model_config, model_id = caller.resolve(MODEL_REF)
    if protocol_name != "anthropic":
        fail("unexpected_minimax_protocol")
    protocol = module.PROTOCOLS[protocol_name]

    options = provider_config.get("options", {})
    base_url = options.get("baseURL", "")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        fail("invalid_provider_origin")

    headers = dict(options.get("headers", {}))
    headers["Authorization"] = f"Bearer {load_access_token()}"
    if isinstance(model_config, dict) and model_config.get("headers"):
        headers.update(model_config["headers"])
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
                    "redacted scope and end with VERDICT: AGREE or VERDICT: REVISE."
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

    print(
        json.dumps(
            {
                "ok": True,
                "provider": "minimax",
                "requested_model": MODEL_REF,
                "actual_model": actual_model,
                "transport": "mavis-bundled-llm-call",
                "response": result,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
