#!/usr/bin/env python3
"""Fake `docker` — setup-smoke-token-contract.sh'ın fault-injection testleri için.

Gerçek Docker/Keycloak/Vault/Kubernetes'e DOKUNMAZ. `docker exec … kcadm.sh …` çağrılarını
karşılar, her çağrıyı call-log'a yazar ve senaryoya göre başarı/hata/bozuk-shape döner.

Env sözleşmesi:
  FAKE_KC_STATE    : JSON state dosyalarının bulunduğu dizin (role.json, clients.json, ...)
  FAKE_KC_CALLLOG  : her kcadm çağrısının yazıldığı dosya (mutasyon assert'i buradan)
  FAKE_KC_FAIL     : virgüllü resource key listesi → o GET exit 1 (okuma hatası simülasyonu)
  FAKE_KC_NOTFOUND : virgüllü key listesi → o GET stderr'e "Not found" yazıp exit 1 (gerçek yokluk)
  FAKE_KC_SHAPE_<KEY> : o GET'in ham gövdesini override eder (bozuk shape simülasyonu)
  FAKE_KC_CREATE_DRIFT: "1" → create sonrası scope, desired'dan sapan bir shape ile döner

Resource key'leri: role, clients, client-mappers, client-scope-mappings, scopes,
                   runtime-sm, notify-sm
"""
import json
import os
import pathlib
import sys

STATE = pathlib.Path(os.environ["FAKE_KC_STATE"])
CALLLOG = pathlib.Path(os.environ["FAKE_KC_CALLLOG"])
RUNTIME_SID = "sid-runtime"
NOTIFY_SID = "sid-notify"
CID = "uuid-smoke-client"


def log(line):
    with CALLLOG.open("a") as f:
        f.write(line + "\n")


def fail_set(var):
    return {x.strip() for x in os.environ.get(var, "").split(",") if x.strip()}


def resource_key(kcadm_args):
    """kcadm get <path> … → resource key"""
    if not kcadm_args or kcadm_args[0] != "get":
        return None
    path = kcadm_args[1] if len(kcadm_args) > 1 else ""
    if path.startswith("roles/"):
        return "role"
    if path == "clients":
        return "clients"
    if path.endswith("/protocol-mappers/models"):
        return "client-mappers"
    if path.startswith("clients/") and path.endswith("/scope-mappings"):
        return "client-scope-mappings"
    if path == "client-scopes":
        return "scopes"
    if path.startswith("client-scopes/") and path.endswith("/scope-mappings"):
        return "runtime-sm" if RUNTIME_SID in path else "notify-sm"
    return None


def state_file(key):
    return STATE / f"{key}.json"


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] != "exec":
        return 0
    # docker exec [-i] [-e K=V]... <container> <cmd> [args...]
    i = 1
    while i < len(argv) and (argv[i] in ("-i", "-t") or argv[i] == "-e"):
        i += 2 if argv[i] == "-e" else 1
    if i >= len(argv):
        return 1
    i += 1  # container
    if i >= len(argv):
        return 1
    cmd = argv[i]
    rest = argv[i + 1:]

    # admin password okuma (script kc_login'de kullanıyor)
    if cmd == "sh":
        print("fake-admin-password")
        return 0

    if not cmd.endswith("kcadm.sh"):
        return 0

    log(" ".join(rest))

    if rest and rest[0] == "config":
        return 0  # login

    if rest and rest[0] == "get":
        key = resource_key(rest)
        if key is None:
            print("[]")
            return 0
        if key in fail_set("FAKE_KC_NOTFOUND"):
            sys.stderr.write("Not found: resource\n")
            return 1
        if key in fail_set("FAKE_KC_FAIL"):
            sys.stderr.write("connection refused / timeout\n")
            return 1
        override = os.environ.get("FAKE_KC_SHAPE_" + key.upper().replace("-", "_"))
        if override is not None:
            print(override)
            return 0
        f = state_file(key)
        if not f.exists():
            sys.stderr.write("Not found\n")
            return 1
        print(f.read_text())
        return 0

    # mutasyonlar: create / update / delete
    if rest and rest[0] in ("create", "update", "delete"):
        if rest[0] == "create" and len(rest) > 1 and rest[1] == "client-scopes":
            body = sys.stdin.read()
            try:
                desired = json.loads(body)
            except Exception:
                return 1
            scopes = json.loads(state_file("scopes").read_text())
            new = dict(desired)
            new["id"] = RUNTIME_SID if desired["name"] == "smoke-runtime-v1" else NOTIFY_SID
            if os.environ.get("FAKE_KC_CREATE_DRIFT") == "1":
                # KC create sonrası beklenmeyen bir mapper eklemiş gibi davran
                new["protocolMappers"] = list(new.get("protocolMappers") or []) + [{
                    "name": "surprise-mapper", "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-attribute-mapper",
                    "config": {"claim.name": "surprise", "access.token.claim": "true"},
                }]
            scopes.append(new)
            state_file("scopes").write_text(json.dumps(scopes))
            sm = {"realmMappings": [], "clientMappings": {}}
            state_file("runtime-sm" if new["id"] == RUNTIME_SID else "notify-sm").write_text(json.dumps(sm))
            return 0
        if rest[0] == "update" and "default-client-scopes/" in " ".join(rest):
            clients = json.loads(state_file("clients").read_text())
            name = "smoke-runtime-v1" if RUNTIME_SID in " ".join(rest) else "smoke-notify-v1"
            clients[0].setdefault("defaultClientScopes", []).append(name)
            state_file("clients").write_text(json.dumps(clients))
            return 0
        if rest[0] == "update" and "optional-client-scopes/" in " ".join(rest):
            clients = json.loads(state_file("clients").read_text())
            name = "smoke-notify-v1" if NOTIFY_SID in " ".join(rest) else "smoke-runtime-v1"
            clients[0].setdefault("optionalClientScopes", []).append(name)
            state_file("clients").write_text(json.dumps(clients))
            return 0
        if rest[0] == "create" and "scope-mappings/realm" in " ".join(rest):
            sys.stdin.read()
            csm = json.loads(state_file("client-scope-mappings").read_text())
            csm["realmMappings"] = [{"id": "role-id", "name": "ENDPOINT_ADMIN"}]
            state_file("client-scope-mappings").write_text(json.dumps(csm))
            return 0
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
