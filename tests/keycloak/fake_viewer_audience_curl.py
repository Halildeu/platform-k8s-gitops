#!/usr/bin/env python3

import json
import os
import pathlib
import sys
import urllib.parse


def argument_value(args: list[str], name: str, default: str = "") -> str:
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return default


args = sys.argv[1:]
state_path = pathlib.Path(os.environ["FAKE_KC_STATE"])
log_path = pathlib.Path(os.environ["FAKE_KC_LOG"])
state = json.loads(state_path.read_text())
method = argument_value(args, "-X", "GET")
output = pathlib.Path(argument_value(args, "-o"))
url = next((arg for arg in args if arg.startswith("http://") or arg.startswith("https://")), "")
body_arg = argument_value(args, "--data-binary")

with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps({"method": method, "url": url}) + "\n")

if url.endswith("/realms/master/protocol/openid-connect/token"):
    output.write_text(json.dumps({"access_token": "test-admin-token-value-with-safe-length"}))
    print("200", end="")
    raise SystemExit(0)

parsed = urllib.parse.urlparse(url)
path = parsed.path.split("/admin/realms/platform-test", 1)[-1]
query = urllib.parse.parse_qs(parsed.query)

if method == "GET" and path == "/clients":
    client_id = query.get("clientId", [""])[0]
    clients = {
        "frontend": [{"id": "frontend-uuid", "clientId": "frontend"}],
        "remote-bridge-operator-api": [
            {"id": "resource-uuid", "clientId": "remote-bridge-operator-api"}
        ],
    }
    output.write_text(json.dumps(clients.get(client_id, [])))
    print("200", end="")
elif path == "/clients/frontend-uuid/protocol-mappers/models" and method == "GET":
    output.write_text(json.dumps(state["mappers"]))
    print("200", end="")
elif path == "/clients/frontend-uuid/protocol-mappers/models" and method == "POST":
    payload = json.loads(pathlib.Path(body_arg.removeprefix("@")).read_text())
    payload["id"] = "server-assigned-id"
    if os.environ.get("FAKE_MUTATE_MAPPER_POST") == "1":
        payload["config"]["access.token.claim"] = "false"
    if os.environ.get("FAKE_DROP_MAPPER_POST") != "1":
        state["mappers"].append(payload)
    state_path.write_text(json.dumps(state))
    output.write_text("")
    print("201", end="")
elif path.startswith("/clients/frontend-uuid/protocol-mappers/models/") and method == "DELETE":
    mapper_id = path.rsplit("/", 1)[-1]
    state["mappers"] = [row for row in state["mappers"] if row.get("id") != mapper_id]
    state_path.write_text(json.dumps(state))
    output.write_text("")
    print("204", end="")
else:
    output.write_text(json.dumps({"error": "unexpected fake request", "method": method, "path": path}))
    print("500", end="")
