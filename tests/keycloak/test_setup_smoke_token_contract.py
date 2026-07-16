#!/usr/bin/env python3
"""Fault-injection matrisi — `scripts/keycloak/setup-smoke-token-contract.sh`.

Codex (thread 019f6c7e) post-impl şartı: script'in ANA İDDİASI olan
**"okunamayan / bilinmeyen / güvenli-olmayan state üzerinde HİÇBİR mutasyon yapılmaz"**
davranışı canlı drill ile tam kanıtlanamaz (canlı KC'yi kasten timeout/malformed yapmak doğru değil).
Bu yüzden fake `docker` ile her kcadm GET'i tek tek bozup `--apply`'ın hiç create/update
çağırmadığını doğruluyoruz.

Gerçek Docker/Keycloak/Vault/Kubernetes'e DOKUNULMAZ. Çalıştırma:
    python3 -m unittest discover -s tests/keycloak -v
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "keycloak" / "setup-smoke-token-contract.sh"
FAKE_DOCKER = pathlib.Path(__file__).resolve().parent / "fake_docker.py"

RUNTIME_SID = "sid-runtime"
NOTIFY_SID = "sid-notify"
CID = "uuid-smoke-client"

AUD_CUSTOM = ["endpoint-admin-service", "permission-service", "variant-service",
              "notification-orchestrator", "auth-service"]


def audience_mapper(name, key, value):
    return {"name": "aud-" + name, "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
            "config": {key: value, "access.token.claim": "true",
                       "id.token.claim": "false", "userinfo.token.claim": "false"}}


def attr_mapper(name, attr, claim, multivalued="false"):
    return {"name": name, "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper", "consentRequired": False,
            "config": {"user.attribute": attr, "claim.name": claim, "jsonType.label": "String",
                       "access.token.claim": "true", "id.token.claim": "false",
                       "userinfo.token.claim": "false",
                       "multivalued": multivalued, "aggregate.attrs": "false"}}


def runtime_scope(mappers=None):
    ms = mappers if mappers is not None else (
        [attr_mapper("userId", "userId", "userId")]
        + [audience_mapper(a, "included.custom.audience", a) for a in AUD_CUSTOM]
        + [audience_mapper("account", "included.client.audience", "account")]
    )
    return {"id": RUNTIME_SID, "name": "smoke-runtime-v1", "protocol": "openid-connect",
            "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
            "protocolMappers": ms}


def notify_scope(mappers=None):
    ms = mappers if mappers is not None else [attr_mapper("org_id", "org_id", "org_id")]
    return {"id": NOTIFY_SID, "name": "smoke-notify-v1", "protocol": "openid-connect",
            "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
            "protocolMappers": ms}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calllog = self.root / "calls.log"
        self.calllog.touch()
        # fake `docker` PATH'in başına
        shim = self.bin / "docker"
        shim.write_text("#!/usr/bin/env bash\nexec python3 %s \"$@\"\n" % FAKE_DOCKER)
        shim.chmod(0o755)
        self.addCleanup(self.tmp.cleanup)

    # ---- state kurulumları ----
    def write(self, key, obj):
        (self.state / f"{key}.json").write_text(json.dumps(obj))

    def seed_converged(self):
        self.write("role", {"id": "role-id", "name": "ENDPOINT_ADMIN", "composite": False})
        self.write("clients", [{"id": CID, "clientId": "smoke-client",
                                "fullScopeAllowed": False, "serviceAccountsEnabled": False,
                                "defaultClientScopes": ["roles", "smoke-runtime-v1"],
                                "optionalClientScopes": ["smoke-notify-v1"]}])
        self.write("client-mappers", [])
        self.write("client-scope-mappings",
                   {"realmMappings": [{"id": "role-id", "name": "ENDPOINT_ADMIN"}], "clientMappings": {}})
        self.write("scopes", [runtime_scope(), notify_scope(), {"id": "sid-canary", "name": "notify-canary",
                                                               "protocol": "openid-connect", "attributes": {},
                                                               "protocolMappers": []}])
        self.write("runtime-sm", {"realmMappings": [], "clientMappings": {}})
        self.write("notify-sm", {"realmMappings": [], "clientMappings": {}})

    def seed_missing_scopes(self):
        """Güvenli eksik: scope'lar yok, client temiz."""
        self.seed_converged()
        self.write("clients", [{"id": CID, "clientId": "smoke-client",
                                "fullScopeAllowed": False, "serviceAccountsEnabled": False,
                                "defaultClientScopes": ["roles"], "optionalClientScopes": []}])
        self.write("client-scope-mappings", {"realmMappings": [], "clientMappings": {}})
        self.write("scopes", [{"id": "sid-canary", "name": "notify-canary", "protocol": "openid-connect",
                               "attributes": {}, "protocolMappers": []}])
        for k in ("runtime-sm", "notify-sm"):
            (self.state / f"{k}.json").unlink(missing_ok=True)

    # ---- runner ----
    def run_script(self, mode, **env_extra):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["TMPDIR"] = str(self.root)
        env["REALM"] = "platform-test"
        env["FAKE_KC_STATE"] = str(self.state)
        env["FAKE_KC_CALLLOG"] = str(self.calllog)
        env.update(env_extra)
        return subprocess.run(["bash", str(SCRIPT), mode], env=env,
                              capture_output=True, text=True, timeout=120)

    def mutations(self):
        lines = self.calllog.read_text().splitlines()
        return [ln for ln in lines
                if ln.startswith("create ") or ln.startswith("update ") or ln.startswith("delete ")]

    def assertNoMutation(self, res):
        self.assertEqual(self.mutations(), [],
                         "MUTASYON YAPILDI (yapılmamalıydı):\n%s\nstdout:\n%s"
                         % ("\n".join(self.mutations()), res.stdout))


class TestReadFailuresBlockMutation(Harness):
    """Her kcadm GET'i tek tek bozulduğunda: exit 3 + HİÇ mutasyon yok."""

    def _assert_read_failure(self, key):
        self.seed_missing_scopes()   # normalde apply create yapardı
        res = self.run_script("--apply", FAKE_KC_FAIL=key)
        self.assertEqual(res.returncode, 3, f"{key}: exit 3 bekleniyordu\n{res.stdout}\n{res.stderr}")
        self.assertIn("snapshot incomplete", res.stdout, f"{key}: snapshot incomplete raporlanmalı")
        self.assertNoMutation(res)

    def test_01_role_read_failure(self):
        self._assert_read_failure("role")

    def test_02_clients_read_failure(self):
        self._assert_read_failure("clients")

    def test_03_client_mappers_read_failure(self):
        self._assert_read_failure("client-mappers")

    def test_04_client_scope_mappings_read_failure(self):
        self._assert_read_failure("client-scope-mappings")

    def test_05_scopes_read_failure(self):
        self._assert_read_failure("scopes")

    def test_06_runtime_scope_mappings_read_failure(self):
        self.seed_converged()
        res = self.run_script("--apply", FAKE_KC_FAIL="runtime-sm")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("snapshot incomplete", res.stdout)
        self.assertNoMutation(res)

    def test_07_notify_scope_mappings_read_failure(self):
        self.seed_converged()
        res = self.run_script("--apply", FAKE_KC_FAIL="notify-sm")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("snapshot incomplete", res.stdout)
        self.assertNoMutation(res)


class TestWrongShapeBlocksMutation(Harness):
    """exit 0 ama semantik olarak okunamaz cevap → 'boş state' SAYILMAZ."""

    def test_08_client_mappers_object_instead_of_list(self):
        # {} dönerse eski kod len({})==0 → "mapper sayısı=0" diye OK verirdi.
        self.seed_missing_scopes()
        res = self.run_script("--apply", FAKE_KC_SHAPE_CLIENT_MAPPERS="{}")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("snapshot incomplete", res.stdout)
        self.assertNoMutation(res)

    def test_09_scopes_object_instead_of_list(self):
        self.seed_missing_scopes()
        res = self.run_script("--apply", FAKE_KC_SHAPE_SCOPES="{}")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("snapshot incomplete", res.stdout)
        self.assertNoMutation(res)

    def test_09b_scopes_malformed_json(self):
        self.seed_missing_scopes()
        res = self.run_script("--apply", FAKE_KC_SHAPE_SCOPES="not-json-at-all")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertNoMutation(res)


class TestUnsafeStateBlocksMutation(Harness):
    def test_11_duplicate_mapper(self):
        self.seed_converged()
        ms = runtime_scope()["protocolMappers"] + [attr_mapper("userId", "userId", "userId")]
        self.write("scopes", [runtime_scope(ms), notify_scope()])
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("DUPLICATE mapper", res.stdout)
        self.assertNoMutation(res)

    def test_12_multivalued_true_breaks_scalar_contract(self):
        self.seed_converged()
        self.write("scopes", [runtime_scope(), notify_scope([attr_mapper("org_id", "org_id", "org_id",
                                                                         multivalued="true")])])
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("multivalued", res.stdout)
        self.assertNoMutation(res)

    def test_12b_notify_canary_bound_is_unsafe(self):
        self.seed_converged()
        clients = json.loads((self.state / "clients.json").read_text())
        clients[0]["optionalClientScopes"].append("notify-canary")
        self.write("clients", clients)
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("notify-canary", res.stdout)
        self.assertNoMutation(res)

    def test_12c_roles_scope_missing_is_unsafe(self):
        self.seed_converged()
        clients = json.loads((self.state / "clients.json").read_text())
        clients[0]["defaultClientScopes"] = ["smoke-runtime-v1"]   # `roles` yok
        self.write("clients", clients)
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("roles", res.stdout)
        self.assertNoMutation(res)

    def test_12d_composite_role_is_unsafe(self):
        self.seed_converged()
        self.write("role", {"id": "role-id", "name": "ENDPOINT_ADMIN", "composite": True})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertNoMutation(res)

    def test_12e_composite_field_missing_is_unsafe(self):
        # grep tabanlı eski kontrol burada false-positive "OK" veriyordu
        self.seed_converged()
        self.write("role", {"id": "role-id", "name": "ENDPOINT_ADMIN"})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertNoMutation(res)

    def test_12f_client_level_mapper_present_is_unsafe(self):
        self.seed_converged()
        self.write("client-mappers", [attr_mapper("userId", "userId", "userId")])
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertNoMutation(res)


class TestSemanticSnapshotCompleteness(Harness):
    """Codex P1 (false SAFE): identity alanı eksikse child kaynaklar HİÇ okunmaz;
    audit eksik child'ı 'boş/rol taşımıyor' sanıp SAFE derdi — gizli drift'e rağmen."""

    def test_18_client_without_id_hides_children(self):
        """clientId exact ama `id` yok → client-mappers + client-scope-mappings okunamaz.
        Fake state'te GİZLİ client mapper + GİZLİ ADMIN scope-mapping var; SAFE denemez."""
        self.seed_converged()
        clients = json.loads((self.state / "clients.json").read_text())
        del clients[0]["id"]                       # ← identity alanı yok
        self.write("clients", clients)
        # okunmayacak olan child'lara tehlikeli içerik koy
        self.write("client-mappers", [attr_mapper("hardcoded", "x", "hardcoded")])
        self.write("client-scope-mappings",
                   {"realmMappings": [{"id": "r", "name": "ADMIN"}], "clientMappings": {}})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"false SAFE!\n{res.stdout}")
        self.assertIn("id", res.stdout)
        self.assertNoMutation(res)

    def test_19_scope_without_id_hides_scope_mappings(self):
        """Owned scope doğru isim/shape ama `id` yok → kendi scope-mappings'i okunamaz.
        Arkasında GİZLİ ADMIN realm mapping var; SAFE denemez."""
        self.seed_converged()
        rs = runtime_scope()
        del rs["id"]                               # ← identity alanı yok
        self.write("scopes", [rs, notify_scope()])
        self.write("runtime-sm", {"realmMappings": [{"id": "r", "name": "ADMIN"}], "clientMappings": {}})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"false SAFE!\n{res.stdout}")
        self.assertNoMutation(res)

    def test_20_wrong_client_identity(self):
        """clients sorgusu başka bir client döndürürse clients[0] KULLANILMAMALI."""
        self.seed_converged()
        self.write("clients", [{"id": "uuid-other", "clientId": "frontend",
                                "fullScopeAllowed": True, "serviceAccountsEnabled": True,
                                "defaultClientScopes": [], "optionalClientScopes": []}])
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"false SAFE!\n{res.stdout}")
        self.assertIn("smoke-client YOK", res.stdout)
        self.assertNoMutation(res)

    def test_21_duplicate_client_match(self):
        self.seed_converged()
        clients = json.loads((self.state / "clients.json").read_text())
        clients.append(dict(clients[0], id="uuid-dup"))
        self.write("clients", clients)
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("eşleşme", res.stdout)
        self.assertNoMutation(res)

    def test_22_duplicate_owned_scope_name(self):
        self.seed_converged()
        self.write("scopes", [runtime_scope(), dict(runtime_scope(), id="sid-dup"), notify_scope()])
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("duplicate scope", res.stdout.lower())
        self.assertNoMutation(res)

    def test_23_nested_realm_mappings_wrong_type(self):
        """realmMappings={} (list değil) → `or []` normalizasyonu bunu gizliyordu."""
        self.seed_converged()
        self.write("runtime-sm", {"realmMappings": {}, "clientMappings": {}})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"false SAFE!\n{res.stdout}")
        self.assertIn("realmMappings", res.stdout)
        self.assertNoMutation(res)

    def test_24_nested_client_mappings_wrong_type(self):
        self.seed_converged()
        self.write("client-scope-mappings",
                   {"realmMappings": [{"id": "role-id", "name": "ENDPOINT_ADMIN"}], "clientMappings": []})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"false SAFE!\n{res.stdout}")
        self.assertIn("clientMappings", res.stdout)
        self.assertNoMutation(res)

    def test_25_nested_field_absent_is_kc_omit_empty(self):
        """KC 26.5.5 omit-empty: boş koleksiyon JSON'dan çıkarılır → alan yokluğu GEÇERLİ 'boş'.
        Canlı kanıt: clients/<id>/scope-mappings, ENDPOINT_ADMIN atanmışken clientMappings alanı YOK.
        Bu yüzden 'alan mevcut olmalı' kuralı canlıda false-UNSAFE üretirdi; ama YANLIŞ TİP
        (test_23/test_24) hâlâ UNSAFE."""
        self.seed_converged()
        self.write("notify-sm", {})            # her iki alan da yok = boş
        self.write("runtime-sm", {})
        self.write("client-scope-mappings", {"realmMappings": [{"id": "role-id", "name": "ENDPOINT_ADMIN"}]})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 0, f"KC omit-empty şekli SAFE olmalıydı:\n{res.stdout}")
        self.assertIn("zaten converged", res.stdout)
        self.assertNoMutation(res)


class TestNullVsAbsentAndItemShape(Harness):
    """Codex P1: `dict.get()` 'alan yok' ile 'alan var ama null'u ayırmıyordu; ve malformed
    eleman filtrelenip 'mapping yok' sayılıyordu → ikisi de false SAFE üretiyordu."""

    def test_26_realm_mappings_explicit_null(self):
        self.seed_converged()
        self.write("runtime-sm", {"realmMappings": None})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"explicit null omit-empty sayıldı!\n{res.stdout}")
        self.assertIn("null", res.stdout.lower() + res.stdout)
        self.assertNoMutation(res)

    def test_27_client_mappings_explicit_null(self):
        self.seed_converged()
        self.write("client-scope-mappings",
                   {"realmMappings": [{"id": "role-id", "name": "ENDPOINT_ADMIN"}], "clientMappings": None})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"explicit null omit-empty sayıldı!\n{res.stdout}")
        self.assertNoMutation(res)

    def test_28_realm_mapping_item_empty_object(self):
        self.seed_converged()
        self.write("runtime-sm", {"realmMappings": [{}]})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"malformed eleman filtrelendi!\n{res.stdout}")
        self.assertIn("geçersiz eleman", res.stdout)
        self.assertNoMutation(res)

    def test_29_realm_mapping_item_bare_string(self):
        self.seed_converged()
        self.write("notify-sm", {"realmMappings": ["ADMIN"]})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"malformed eleman filtrelendi!\n{res.stdout}")
        self.assertNoMutation(res)

    def test_30_extra_malformed_item_alongside_valid(self):
        """Geçerli ENDPOINT_ADMIN + `name`siz gizli eleman → filtreleme onu görünmez kılıyordu."""
        self.seed_converged()
        self.write("client-scope-mappings",
                   {"realmMappings": [{"id": "role-id", "name": "ENDPOINT_ADMIN"}, {"id": "hidden-role"}],
                    "clientMappings": {}})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 3, f"gizli eleman filtrelendi!\n{res.stdout}")
        self.assertNoMutation(res)

    def test_31_explicit_empty_containers_are_valid(self):
        """Doğru tipte explicit boş container'lar GEÇERLİ kalmalı (omit-empty ile birlikte)."""
        self.seed_converged()
        self.write("runtime-sm", {"realmMappings": [], "clientMappings": {}})
        self.write("notify-sm", {"realmMappings": [], "clientMappings": {}})
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("zaten converged", res.stdout)
        self.assertNoMutation(res)


class TestSecondBarrier(Harness):
    def test_10_post_create_drift_blocks_association(self):
        """Scope create edildi ama KC beklenmeyen shape döndürdü → association YAPILMAMALI."""
        self.seed_missing_scopes()
        res = self.run_script("--apply", FAKE_KC_CREATE_DRIFT="1")
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("SAFETY BARRIER (stage 2)", res.stdout)
        muts = self.mutations()
        self.assertTrue(any(m.startswith("create client-scopes") for m in muts),
                        "scope create beklenirdi:\n%s" % muts)
        self.assertFalse(any("default-client-scopes" in m or "optional-client-scopes" in m
                             or "scope-mappings/realm" in m for m in muts),
                         "association/scope-mapping YAPILMAMALIYDI:\n%s" % muts)


class TestHappyPath(Harness):
    def test_13_safe_missing_applies_only_expected(self):
        self.seed_missing_scopes()
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        muts = self.mutations()
        self.assertEqual(sum(1 for m in muts if m.startswith("create client-scopes")), 2, muts)
        self.assertTrue(any("default-client-scopes" in m for m in muts), muts)
        self.assertTrue(any("optional-client-scopes" in m for m in muts), muts)
        self.assertTrue(any("scope-mappings/realm" in m for m in muts), muts)
        self.assertFalse(any(m.startswith("delete ") for m in muts), "script hiçbir şeyi SİLMEZ")

    def test_14_second_apply_is_noop(self):
        self.seed_converged()
        res = self.run_script("--apply")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("zaten converged", res.stdout)
        self.assertNoMutation(res)

    def test_14b_check_never_mutates_even_when_missing(self):
        self.seed_missing_scopes()
        res = self.run_script("--check")
        self.assertEqual(res.returncode, 2, res.stdout)
        self.assertNoMutation(res)


class TestEnvGuards(Harness):
    def test_15_unknown_realm_refused(self):
        self.seed_converged()
        res = self.run_script("--apply", REALM="some-other-realm")
        self.assertEqual(res.returncode, 1)
        self.assertIn("bilinmeyen realm", res.stderr)
        self.assertNoMutation(res)

    def test_16_prod_realm_requires_confirm(self):
        self.seed_converged()
        res = self.run_script("--apply", REALM="serban")
        self.assertEqual(res.returncode, 1)
        self.assertIn("CONFIRM_PROD_SMOKE_CONTRACT", res.stderr)
        self.assertNoMutation(res)

    def test_17_container_override_fail_closed(self):
        self.seed_converged()
        res = self.run_script("--apply", KC_CONTAINER_OVERRIDE="platform-kc-prod")
        self.assertEqual(res.returncode, 1)
        self.assertIn("fail-closed", res.stderr)
        self.assertNoMutation(res)


if __name__ == "__main__":
    unittest.main(verbosity=2)
