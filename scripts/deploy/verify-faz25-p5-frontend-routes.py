#!/usr/bin/env python3
"""Fail-closed ingress ownership check for Faz 25 P5 browser paths.

The normalized JSON emitted on stdout is suitable for content-addressed
pre/post and continuous-watch evidence.  Only routes that can actually match
the protected browser paths are required to belong to the canonical
platform-test/platform Ingress; disjoint API ingresses remain valid.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


REQUEST_PATHS = (
    "/",
    "/home",
    "/login",
    "/admin/ats",
    "/admin/interview-evidence",
    "/build-info.json",
)

MATCH_LOCAL_ANNOTATION = re.compile(
    r"(?:canary|rewrite-target|app-root|permanent-redirect|temporal-redirect|"
    r"configuration-snippet|upstream-vhost|proxy-redirect|mirror-target|"
    r"mirror-host|auth-signin|auth-url)",
    re.IGNORECASE,
)
HOST_GLOBAL_ANNOTATION = re.compile(r"(?:server-snippet)", re.IGNORECASE)


def host_matches(rule_host: Any, request_host: str) -> bool:
    # A missing/empty Ingress rule host is a controller catch-all and can
    # therefore serve the protected host.  It must participate in collision
    # detection instead of being silently ignored.
    if rule_host is None or rule_host == "":
        return True
    if not isinstance(rule_host, str):
        raise ValueError("invalid ingress rule host")
    if rule_host == request_host:
        return True
    if not rule_host.startswith("*."):
        return False
    suffix = rule_host[1:]
    return request_host.endswith(suffix) and request_host.count(".") == rule_host.count(".")


def prefix_matches(rule: str, request: str) -> bool:
    if rule == "/":
        return True
    normalized = rule.rstrip("/")
    return request == normalized or request.startswith(f"{normalized}/")


def regex_matches(rule: str, request: str) -> bool:
    try:
        return re.match(f"^(?:{rule})", request, re.IGNORECASE) is not None
    except re.error as error:
        raise ValueError(f"invalid ingress regex path: {rule}") from error


def path_matches(path: dict[str, Any], request: str, global_regex_mode: bool) -> bool:
    rule = path.get("path")
    path_type = path.get("pathType")
    if not isinstance(rule, str) or not rule.startswith("/"):
        raise ValueError("invalid ingress path")
    if path_type not in {"Exact", "Prefix", "ImplementationSpecific"}:
        raise ValueError("invalid ingress pathType")
    if global_regex_mode or path_type == "ImplementationSpecific":
        return regex_matches(rule, request) if global_regex_mode else prefix_matches(rule, request)
    if path_type == "Exact":
        return request == rule
    return prefix_matches(rule, request)


def service_port(path: dict[str, Any]) -> int | None:
    port = path.get("backend", {}).get("service", {}).get("port", {})
    number = port.get("number")
    return number if isinstance(number, int) else None


def verify(payload: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("ingress list items missing")

    host_ingresses: list[dict[str, Any]] = []
    for ingress in items:
        rules = ingress.get("spec", {}).get("rules", [])
        if any(
            isinstance(rule, dict)
            and host_matches(rule.get("host"), args.host)
            for rule in rules
        ):
            host_ingresses.append(ingress)

    if not host_ingresses:
        raise ValueError("no ingress serves protected host")

    for ingress in host_ingresses:
        annotations = ingress.get("metadata", {}).get("annotations") or {}
        if any(HOST_GLOBAL_ANNOTATION.search(str(key)) for key in annotations):
            raise ValueError("host-global route annotation is forbidden")

    global_regex_mode = any(
        str((ingress.get("metadata", {}).get("annotations") or {}).get(
            "nginx.ingress.kubernetes.io/use-regex", ""
        )).lower()
        == "true"
        or "nginx.ingress.kubernetes.io/rewrite-target"
        in (ingress.get("metadata", {}).get("annotations") or {})
        for ingress in host_ingresses
    )

    normalized: list[dict[str, Any]] = []
    request_paths = tuple(dict.fromkeys((*REQUEST_PATHS, *args.additional_request_path)))
    for request in request_paths:
        if not isinstance(request, str) or not request.startswith("/"):
            raise ValueError("invalid additional protected request path")
        matches: list[dict[str, Any]] = []
        for ingress in host_ingresses:
            metadata = ingress.get("metadata", {})
            annotations = metadata.get("annotations") or {}
            for rule in ingress.get("spec", {}).get("rules", []):
                rule_host = rule.get("host")
                if not host_matches(rule_host, args.host):
                    continue
                for path in rule.get("http", {}).get("paths", []):
                    if not path_matches(path, request, global_regex_mode):
                        continue
                    if any(MATCH_LOCAL_ANNOTATION.search(str(key)) for key in annotations):
                        raise ValueError("matching route has route-altering annotation")
                    service = path.get("backend", {}).get("service", {})
                    matches.append(
                        {
                            "requestPath": request,
                            "namespace": metadata.get("namespace"),
                            "ingressName": metadata.get("name"),
                            "ingressUid": metadata.get("uid"),
                            "rulePath": path.get("path"),
                            "pathType": path.get("pathType"),
                            "serviceName": service.get("name"),
                            "servicePort": service_port(path),
                        }
                    )

        if len(matches) != 1:
            raise ValueError(f"protected path has {len(matches)} matching routes: {request}")
        match = matches[0]
        expected = {
            "namespace": args.ingress_namespace,
            "ingressName": args.ingress_name,
            "ingressUid": args.ingress_uid,
            "rulePath": "/",
            "pathType": "Prefix",
            "serviceName": args.service_name,
            "servicePort": args.service_port,
        }
        if any(match[key] != value for key, value in expected.items()):
            raise ValueError(f"protected path is not owned by canonical ingress: {request}")
        normalized.append(match)

    return sorted(
        normalized,
        key=lambda route: (
            route["requestPath"],
            route["namespace"],
            route["ingressName"],
            route["rulePath"],
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="testai.acik.com")
    parser.add_argument("--ingress-namespace", default="platform-test")
    parser.add_argument("--ingress-name", default="platform")
    parser.add_argument("--ingress-uid", required=True)
    parser.add_argument("--service-name", default="frontend")
    parser.add_argument("--service-port", type=int, default=80)
    parser.add_argument("--additional-request-path", action="append", default=[])
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        routes = verify(payload, args)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"route verification failed: {error}", file=sys.stderr)
        return 1
    json.dump(routes, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
