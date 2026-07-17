"""Stable fail-closed error types and reason codes."""

from __future__ import annotations


class PolicyError(Exception):
    """A bounded policy rejection safe to map to a stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def reject(code: str, message: str) -> "NoReturn":
    raise PolicyError(code, message)


from typing import NoReturn  # noqa: E402  (keeps the public error surface first)
