#!/usr/bin/env python3
"""Render, post, and verify Coordination Ledger materialized comments.

The script has three modes:

- render: build the deterministic GitHub issue comment body.
- verify: validate a fetched GitHub issue-comment JSON object and emit the
  `comment_binding` object expected by Coordination Ledger v1 events.
- post: create the GitHub issue comment through `gh api`, fetch it back, verify
  it, and emit the same binding JSON.

It does not append ledger events and does not mutate Project fields, issue
bodies, or PR bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HASH_RE = re.compile(r"^(?:sha256:)?([a-f0-9]{64})$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
EXPECTED_SURFACE = "github_issue_comment"
MARKER_START = "<!-- coordination-ledger-materialized-comment:v1"
MARKER_END = "-->"
TOLERANCE_MINUTES = {
    "normal": 5,
    "degraded": 15,
    "recovery": 15,
}


class MaterializeError(Exception):
    """User-facing verification refusal."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_hash(value: str, field: str) -> str:
    match = HASH_RE.match(value or "")
    if not match:
        raise MaterializeError(f"{field} must be sha256:<64-hex> or bare 64-hex")
    return match.group(1)


def normalized_hash_label(value: str, field: str) -> str:
    return f"sha256:{normalize_hash(value, field)}"


def parse_utc_z(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MaterializeError(f"{field} must be an ISO-8601 UTC string ending with Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MaterializeError(f"{field} is not parseable: {exc}") from exc


def require_repo(value: str) -> str:
    if not REPO_RE.match(value or ""):
        raise MaterializeError("--repo must be owner/repo with safe path characters")
    return value


def require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MaterializeError(f"{field} must be a positive integer")
    return value


def load_comment_json(path: str) -> dict[str, Any]:
    try:
        if path == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError as exc:
        raise MaterializeError(f"comment JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MaterializeError(f"comment JSON invalid: {exc}") from exc

    if not isinstance(data, dict):
        raise MaterializeError("comment JSON must be an object")
    return data


def render_body(args: argparse.Namespace) -> str:
    payload_hash = normalized_hash_label(args.payload_hash, "--payload-hash")
    mode = args.verification_mode
    if mode not in TOLERANCE_MINUTES:
        raise MaterializeError(f"--verification-mode must be one of: {', '.join(sorted(TOLERANCE_MINUTES))}")

    lines = [
        MARKER_START,
        f"repository: {require_repo(args.repo)}",
        f"issue: {args.issue}",
        f"event_uuid: {args.event_uuid}",
        f"event_type: {args.event_type}",
        f"writer_role: {args.writer_role}",
        f"payload_hash: {payload_hash}",
        f"verification_mode: {mode}",
        MARKER_END,
        "",
        "Coordination Ledger materialized comment v1",
        "",
        f"- repository: {args.repo}",
        f"- issue: {args.issue}",
        f"- event_uuid: {args.event_uuid}",
        f"- event_type: {args.event_type}",
        f"- writer_role: {args.writer_role}",
        f"- payload_hash: {payload_hash}",
        f"- verification_mode: {mode}",
        "",
    ]
    return "\n".join(lines)


def parse_marker(body: str) -> dict[str, str]:
    if not isinstance(body, str) or not body.startswith(MARKER_START):
        raise MaterializeError("comment body missing coordination ledger v1 marker")
    end_index = body.find(MARKER_END)
    if end_index < 0:
        raise MaterializeError("comment body marker is not closed")

    marker_body = body[len(MARKER_START):end_index].strip()
    parsed: dict[str, str] = {}
    for raw_line in marker_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise MaterializeError(f"comment marker line missing ':' separator: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise MaterializeError(f"comment marker line has blank key/value: {line!r}")
        parsed[key] = value
    return parsed


def assert_marker_matches(args: argparse.Namespace, marker: dict[str, str]) -> None:
    expected = {
        "repository": require_repo(args.repo),
        "issue": str(args.issue),
        "event_uuid": args.event_uuid,
        "event_type": args.event_type,
        "writer_role": args.writer_role,
        "payload_hash": normalized_hash_label(args.payload_hash, "--payload-hash"),
        "verification_mode": args.verification_mode,
    }
    for key, expected_value in expected.items():
        actual = marker.get(key)
        if actual != expected_value:
            raise MaterializeError(
                f"comment marker {key} mismatch expected={expected_value!r} actual={actual!r}"
            )


def verify_comment(args: argparse.Namespace, comment: dict[str, Any]) -> dict[str, Any]:
    body = comment.get("body")
    if not isinstance(body, str) or not body:
        raise MaterializeError("comment.body must be a non-empty string")
    marker = parse_marker(body)
    assert_marker_matches(args, marker)

    comment_id = require_positive_int(comment.get("id"), "comment.id")
    user = comment.get("user")
    if not isinstance(user, dict):
        raise MaterializeError("comment.user must be an object")
    author_id = require_positive_int(user.get("id"), "comment.user.id")

    author_login = user.get("login")
    author_type = user.get("type")
    if not isinstance(author_login, str) or not author_login:
        raise MaterializeError("comment.user.login must be a non-empty string")
    if not isinstance(author_type, str) or not author_type:
        raise MaterializeError("comment.user.type must be a non-empty string")

    created_at = parse_utc_z(comment.get("created_at"), "comment.created_at")
    updated_at = parse_utc_z(comment.get("updated_at"), "comment.updated_at")
    if updated_at != created_at:
        raise MaterializeError("comment.updated_at must equal comment.created_at")

    mode = args.verification_mode
    tolerance = TOLERANCE_MINUTES.get(mode)
    if tolerance is None:
        raise MaterializeError(f"--verification-mode must be one of: {', '.join(sorted(TOLERANCE_MINUTES))}")

    if args.committed_at:
        committed_at = parse_utc_z(args.committed_at, "--committed-at")
        delta_seconds = abs((created_at - committed_at).total_seconds())
        if delta_seconds > tolerance * 60:
            raise MaterializeError(
                f"comment.created_at outside tolerance mode={mode} tolerance_minutes={tolerance}"
            )

    return {
        "surface": EXPECTED_SURFACE,
        "repository": require_repo(args.repo),
        "issue": args.issue,
        "comment_id": comment_id,
        "author_id": author_id,
        "author_login": author_login,
        "author_type": author_type,
        "created_at": comment["created_at"],
        "updated_at": comment["updated_at"],
        "raw_body_hash": f"sha256:{sha256_text(body)}",
        "payload_hash": normalized_hash_label(args.payload_hash, "--payload-hash"),
        "verification_mode": mode,
        "timestamp_tolerance_minutes": tolerance,
    }


def gh_api_json(args: list[str], *, input_text: str | None = None) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise MaterializeError(result.stderr.strip() or "gh api failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MaterializeError(f"gh api returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MaterializeError("gh api returned non-object JSON")
    return data


def cmd_render(args: argparse.Namespace) -> int:
    body = render_body(args)
    if args.json:
        print(
            json.dumps(
                {
                    "body": body,
                    "raw_body_hash": f"sha256:{sha256_text(body)}",
                    "payload_hash": normalized_hash_label(args.payload_hash, "--payload-hash"),
                },
                sort_keys=True,
            )
        )
    else:
        print(body, end="")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    comment = load_comment_json(args.comment_json)
    binding = verify_comment(args, comment)
    print(json.dumps(binding, sort_keys=True))
    return 0


def cmd_post(args: argparse.Namespace) -> int:
    body = render_body(args)
    created = gh_api_json(
        [
            "-X",
            "POST",
            f"repos/{require_repo(args.repo)}/issues/{args.issue}/comments",
            "-f",
            f"body={body}",
        ]
    )
    comment_id = require_positive_int(created.get("id"), "comment.id")
    fetched = gh_api_json([f"repos/{require_repo(args.repo)}/issues/comments/{comment_id}"])
    binding = verify_comment(args, fetched)
    print(json.dumps(binding, sort_keys=True))
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--issue", required=True, type=int, help="GitHub issue number")
    parser.add_argument("--event-uuid", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--writer-role", required=True)
    parser.add_argument("--payload-hash", required=True, help="sha256:<64-hex> or bare 64-hex")
    parser.add_argument(
        "--verification-mode",
        default="normal",
        choices=sorted(TOLERANCE_MINUTES),
        help="timestamp tolerance mode",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="render deterministic materialized comment body")
    add_common_args(render)
    render.add_argument("--json", action="store_true", help="emit body and hashes as JSON")
    render.set_defaults(func=cmd_render)

    verify = sub.add_parser("verify", help="verify fetched GitHub comment JSON and emit binding")
    add_common_args(verify)
    verify.add_argument("--comment-json", required=True, help="comment JSON file path, or '-' for stdin")
    verify.add_argument("--committed-at", help="optional event committed_at UTC timestamp for tolerance check")
    verify.set_defaults(func=cmd_verify)

    post = sub.add_parser("post", help="create, fetch, verify comment, and emit binding")
    add_common_args(post)
    post.add_argument("--committed-at", help="optional event committed_at UTC timestamp for tolerance check")
    post.set_defaults(func=cmd_post)

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.issue <= 0:
        raise MaterializeError("--issue must be a positive integer")
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except MaterializeError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        sys.exit(1)
