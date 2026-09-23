"""Bounded, metadata-only observer for the mobile gateway SSE contract."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any


def snapshot_counts(value: Any) -> dict[str, Any] | None:
    """Mirror the mobile display contract; never return transcript/analysis text."""

    def short(value: Any) -> bool:
        return isinstance(value, str) and len(value) <= 20000

    if not isinstance(value, dict):
        return None
    version = value.get("version")
    decisions = value.get("decisions")
    actions = value.get("action_items")
    if not all(
        (
            value.get("grounding_policy") == "verified_only",
            type(version) is int and 0 <= version <= 9007199254740991,
            type(value.get("is_partial")) is bool,
            short(value.get("summary")),
            isinstance(decisions, list) and len(decisions) <= 100,
            isinstance(actions, list) and len(actions) <= 100,
        )
    ):
        return None
    if not all(short(item) for item in decisions):
        return None
    for item in actions:
        if not isinstance(item, dict) or not short(item.get("text")):
            return None
        if any(
            item.get(key) is not None and not short(item[key])
            for key in ("owner", "due_date")
        ):
            return None
    return {
        "version": version,
        "summaryVisible": value.get("summary_grounding_status")
        in ("verified", "partial_verified")
        and bool(value["summary"].strip()),
        "decisionCount": sum(bool(item.strip()) for item in decisions),
        "actionCount": sum(bool(item["text"].strip()) for item in actions),
    }


class AnalysisObserver:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.usable = asyncio.Event()
        self.recording = False
        self.audio_started_at: float | None = None
        self.carry = b""
        self.metrics: dict[str, Any] = {
            "httpStatus": None,
            "connected": False,
            "bytes": 0,
            "heartbeats": 0,
            "accepted": 0,
            "rejected": 0,
            "invalidJson": 0,
            "unknownEvents": 0,
            "overflows": 0,
            "usableBeforeEof": False,
            "firstUsableMs": None,
            "decisionCount": 0,
            "actionCount": 0,
            "summaryVisible": False,
            "payloadIncluded": False,
        }

    def push(self, chunk: bytes) -> None:
        self.metrics["bytes"] += len(chunk)
        self.carry += chunk
        if len(self.carry) > 262144:
            self.metrics["overflows"] += 1
            self.carry = b""
            raise ValueError("live-analysis-frame-limit")
        parts = re.split(rb"\r?\n\r?\n", self.carry)
        self.carry = parts.pop()
        for part in parts:
            event, data = "", []
            try:
                lines = part.decode("utf-8").splitlines()
            except UnicodeError:
                self.metrics["invalidJson"] += 1
                continue
            for line in lines:
                if line.startswith(":") and line[1:].strip() == "heartbeat":
                    self.metrics["heartbeats"] += 1
                field, sep, value = line.partition(":")
                if not sep or not field:
                    continue
                value = value.removeprefix(" ")
                if field == "event":
                    event = value
                elif field == "data":
                    data.append(value)
            if event != "analysis":
                if event or data:
                    self.metrics["unknownEvents"] += 1
                continue
            try:
                counts = snapshot_counts(json.loads("\n".join(data)))
            except (ValueError, RecursionError):
                self.metrics["invalidJson"] += 1
                continue
            if counts is None:
                self.metrics["rejected"] += 1
                continue
            self.metrics["accepted"] += 1
            self.metrics["latestSnapshot"] = counts
            if (
                "firstAcceptedMs" not in self.metrics
                and self.audio_started_at is not None
            ):
                self.metrics["firstAcceptedMs"] = round(
                    (time.monotonic() - self.audio_started_at) * 1000
                )
            if (
                self.recording
                and self.audio_started_at is not None
                and counts["summaryVisible"]
                and counts["decisionCount"] > 0
                and counts["actionCount"] > 0
                and not self.usable.is_set()
            ):
                self.metrics.update(counts)
                self.metrics["usableBeforeEof"] = True
                self.metrics["firstUsableMs"] = round(
                    (time.monotonic() - self.audio_started_at) * 1000
                )
                self.usable.set()

    async def observe(self, url: str, token: str, max_seconds: int) -> None:
        # curl reads the bearer through a private pipe, never argv or a file.
        # Disable curlrc, redirects and proxy CONNECT headers; retain TLS checks.
        if not re.fullmatch(r"[A-Za-z0-9._~-]+", token):
            self.metrics["errorCode"] = "invalid-bearer-format"
            return
        process = await asyncio.create_subprocess_exec(
            "curl",
            "--disable",
            "--silent",
            "--no-buffer",
            "--include",
            "--http1.1",
            "--suppress-connect-headers",
            "--proto",
            "=https",
            "--connect-timeout",
            "15",
            "--max-time",
            str(max_seconds),
            "--config",
            "-",
            "--url",
            url,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            process.stdin.write(
                (
                    f'header = "Authorization: Bearer {token}"\n'
                    'header = "Accept: text/event-stream"\n'
                ).encode()
            )
            await process.stdin.drain()
            process.stdin.close()
            headers = b""
            while b"\r\n\r\n" not in headers:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    raise ValueError("live-analysis-headers-missing")
                headers += chunk
                if len(headers) > 32768:
                    raise ValueError("live-analysis-header-limit")
            header, remainder = headers.split(b"\r\n\r\n", 1)
            status = re.match(rb"HTTP/1\.[01] ([0-9]{3})", header)
            self.metrics["httpStatus"] = int(status[1]) if status else None
            if self.metrics["httpStatus"] != 200:
                raise ValueError("live-analysis-http-rejected")
            if not re.search(
                rb"(?im)^content-type:\s*text/event-stream(?:[;\s]|$)", header
            ):
                raise ValueError("live-analysis-content-type")
            self.metrics["connected"] = True
            self.ready.set()
            self.push(remainder)
            while chunk := await process.stdout.read(8192):
                self.push(chunk)
            self.metrics["closed"] = True
        except ValueError as error:
            self.metrics["errorCode"] = str(error)
        except Exception:
            self.metrics["errorCode"] = "live-analysis-transport-error"
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
