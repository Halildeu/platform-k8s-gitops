# Vault Policies — ADR-0002 Env-Split Yapı

> **Referans ADR:** [`docs/adr/0002-single-host-dual-cluster.md`](../../docs/adr/0002-single-host-dual-cluster.md) §3.6 Vault Design
> **Tasarım:** `common/` + `prod/` + `test/` ayrık policy; 2 ayrı Vault daemon (prod + test full isolation)
> **Apply (env-specific):** `vault policy write <name> bootstrap/vault-policies/<dir>/<file>.hcl`

---

## 1. Dizin Yapısı (ADR-0002 §3.6)

```
bootstrap/vault-policies/
├── common/
│   └── eso-runtime.hcl              # Her Vault'ta aynı shared paths (kv/data/platform/* + kv/data/gitops/*)
├── prod/
│   └── eso-runtime-extras.hcl       # Prod Vault'a özel ek path/capability
└── test/
    └── eso-runtime-extras.hcl       # Test Vault'a özel ek path/capability
```

## 2. Policy Listesi

| Policy | Dizin | Amaç | Vault (hangi daemon) |
|---|---|---|---|
| `eso-runtime` | `common/` | ESO ExternalSecret read (kv/platform/* + kv/gitops/* + smoke-client) | Hem prod hem test Vault |
| `eso-runtime-prod-extras` | `prod/` | Prod-only ek paths (sys/audit read, forward-extension) | SADECE prod Vault |
| `eso-runtime-test-extras` | `test/` | Test-only ek paths (token self-lookup debug, forward-extension) | SADECE test Vault |

## 3. Apply (Prod Vault)

```bash
# Prod Vault login
export VAULT_ADDR=http://localhost:8200
vault login <prod-root-token>

# Common + prod extras
vault policy write eso-runtime bootstrap/vault-policies/common/eso-runtime.hcl
vault policy write eso-runtime-prod-extras bootstrap/vault-policies/prod/eso-runtime-extras.hcl

# AppRole binding (multi-policy)
vault auth enable approle 2>/dev/null || true
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime,eso-runtime-prod-extras" \
  token_ttl=1h \
  token_max_ttl=24h \
  secret_id_ttl=0

# Doğrula (prod'da üç politika bağlı)
vault read auth/approle/role/eso-runtime | grep policies
# Beklenen: token_policies=[eso-runtime eso-runtime-prod-extras]
```

## 4. Apply (Test Vault)

```bash
# Test Vault login (platform-vault-test, port 8201)
export VAULT_ADDR=http://localhost:8201
vault login <test-root-token>

vault policy write eso-runtime bootstrap/vault-policies/common/eso-runtime.hcl
vault policy write eso-runtime-test-extras bootstrap/vault-policies/test/eso-runtime-extras.hcl

vault auth enable approle 2>/dev/null || true
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime,eso-runtime-test-extras" \
  token_ttl=1h \
  token_max_ttl=24h \
  secret_id_ttl=0
```

## 5. Apply Pattern (common policy her iki Vault'ta aynı)

Her iki Vault instance'ında `eso-runtime` policy içeriği **birebir aynı** olur. Env-specific fark sadece `extras` policy'de.

Bu yüzden:
- Common policy **her iki Vault'ta ayrı write** edilir (Vault state ayrı)
- Policy dosyası **tek git'te** (drift önleme)
- Rotation/audit **env-independent** (ortak path'ler)

## 6. Rotation + AppRole Secret ID

```bash
# Secret ID generate (her iki env'de ayrı)
vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id

# K8s Secret create (env-specific context)
kubectl --context k3d-prod -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${PROD_SECRET_ID}"

kubectl --context k3d-test -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${TEST_SECRET_ID}"
```

**Rotation takvim (day-2-governance §2.1):**
- Prod secret_id: **30 gün**
- Test secret_id: **14 gün**
- Token TTL: 1h (otomatik renew)

## 6.5 Faz 24 direct-STT app-mTLS seeder (I7 — TEST only)

> **Referans:** `docs/runbooks/RB-bplus-i7-app-mtls.md` · Codex `019ef0a2` (design) + `019f1124` (review-REVISE absorb) · ADR-0030/0031
> **Amaç:** root token OLMADAN, additive (server-side PATCH), **ayrı blast-radius-izole** AppRole ile audio-gateway client mTLS material'ını üret + `kv/platform/audio-gateway-service`'e seed et → ESO `audio-gateway-direct-stt-mtls` Ready. **bootstrap-writer'a bind ETME** (leak → cert-mint sızması).

Policy: `bootstrap/vault-policies/test/audio-gateway-mtls-seeder.hcl` (test-only). KV `patch,read` (overwrite YOK), `pki-denetim-ai/issue/audio-gateway-client` `update` (tek rol), server-issue/sign/root/config/revoke/sys/auth/identity DENY.

**Adım 0 — PKI role config'i KİLİTLE (asıl risk; policy değil rol)** — Codex `019f1124`:
```bash
export VAULT_ADDR=http://localhost:8201
VAULT_TOKEN=<test-root> vault read pki-denetim-ai/roles/audio-gateway-client
# Beklenen: client_flag=true, server_flag=false, max_ttl<=24h (86400),
#           allow_any_name=false, allowed CN/URI-SAN dar, key_type/bits uygun.
# Permissive ise issue'dan ÖNCE düzelt (aksi halde token permissive cert mint eder).
```

**Adım 1 — Apply (operator; `vault policy write` = sys/policies, agent üstünde):**
```bash
vault login <test-root-token>      # SADECE policy write + approle create için; paylaşılmaz
vault policy write audio-gateway-mtls-seeder bootstrap/vault-policies/test/audio-gateway-mtls-seeder.hcl

# DEDICATED, one-shot, kısa-ömürlü AppRole (bootstrap-writer DEĞİL):
vault write auth/approle/role/audio-gateway-mtls-seeder-test \
  token_policies="audio-gateway-mtls-seeder" \
  token_ttl=15m token_max_ttl=15m token_num_uses=0 \
  secret_id_ttl=30m secret_id_num_uses=1 bind_secret_id=true
# token_num_uses=0 = 15m TTL içinde sınırsız çağrı (bound: one-shot secret_id + 15m);
# fixed num_uses YOK ki verifier tam negatif-suite'i tek token'da koşabilsin (Codex 019f1124).

ROLE_ID=$(vault read -field=role_id auth/approle/role/audio-gateway-mtls-seeder-test/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/audio-gateway-mtls-seeder-test/secret-id)
# role-id/secret-id agent'a güvenli ver (umask 077; dosya mode 0600). secret-id GİT'E GİRMEZ.
```

**Adım 2 — Boundary doğrula (negatif testler PASS olmalı):**
```bash
export ROLE_ID; printf '%s' "$SECRET_ID" > /tmp/ag-mtls-seeder-secret-id.txt; chmod 600 /tmp/ag-mtls-seeder-secret-id.txt
bash bootstrap/vault-policies/test/audio-gateway-mtls-seeder-verify.sh
# kv=patch,read · issue=update · server-issue/sign/root/config/revoke/sys/approle/foreign-kv = 403
```

**Adım 3 — Seed (agent; root yok, dedicated AppRole token, multiline PEM-safe):**

> **Precondition (Codex 019f1124 caveat-3):** `patch` var-olan path gerektirir; bu
> AppRole `create` taşımaz → yeni path YARATAMAZ. Seed öncesi path'in mevcut
> olduğunu kanıtla (redis_password orada): `vault kv get -mount=kv platform/audio-gateway-service`
> (değer bas­ma; key-presence yeter). Path yoksa owner/operator preseed eder.

```bash
T=$(curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" \
     -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$(cat /tmp/ag-mtls-seeder-secret-id.txt)\"}" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["auth"]["client_token"])')

umask 077; D=$(mktemp -d)
# 1) client cert üret (audio-gateway-client rolü; CN/SAN role-enforced)
curl -sf -X PUT -H "X-Vault-Token: $T" "$VAULT_ADDR/v1/pki-denetim-ai/issue/audio-gateway-client" \
  -d '{"common_name":"audio-gateway","ttl":"24h"}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin)["data"];open("'"$D"'/crt","w").write(d["certificate"]);open("'"$D"'/key","w").write(d["private_key"]);open("'"$D"'/ca","w").write(d["issuing_ca"])'

# 2) additive server-side PATCH (mevcut redis pw KORUNUR; overwrite YOK)
vault kv patch -mount=kv platform/audio-gateway-service \
  direct_stt_client_crt=@"$D/crt" direct_stt_client_key=@"$D/key" direct_stt_ca_crt=@"$D/ca"   # VAULT_TOKEN=$T

shred -u "$D"/crt "$D"/key "$D"/ca 2>/dev/null; rm -rf "$D"; unset T   # raw key diske kalmaz
```

**Adım 4 — ESO reconcile + doğrula:**
```bash
kubectl --context k3d-test -n platform-test annotate externalsecret audio-gateway-direct-stt-mtls \
  force-sync="$(date +%s)" --overwrite
kubectl --context k3d-test -n platform-test get externalsecret audio-gateway-direct-stt-mtls   # READY=True
```

> **Neden Vault bozulmaz:** `patch` = server-side KV v2 merge → yalnız `direct_stt_*` key'leri set edilir, var-olan key'ler (redis pw) korunur; `create/update/delete/destroy/metadata` GRANT EDİLMEZ. PEM çok-satırlı `@file` ile taşınır (argv/process-list sızıntısı yok; raw key tempdir 0600 + shred). Ayrı AppRole → bootstrap-writer blast-radius'una eklenmez. Prod Vault'a hiçbiri yazılmaz (I7-prod = KVKK m.6 gate).
>
> **Evidence (raw key ASLA log/tee/evidence'e düşmez — Codex 019f1124 caveat-4/5):** yalnız cert
> `serial_number`, `not_after`, fingerprint/hash-prefix, KV version ve ESO `Ready=True` kaydedilir.
> Vault audit device `log_raw=false` doğrulanır. **24h client cert ≠ kalıcı readiness:** evidence'a
> `not_after` + refresh-deadline yazılır; rotation/renewal drill prod/uzun-koşu için ayrı gate (I7-prod).

## 6.6 GitOps Vault-config reconciler (AI-otonom, TEST only)

> **Amaç:** Vault CONFIG (ACL policy + scoped AppRole) değişikliklerini **operatörün her seferinde root koşması olmadan**, git-reviewed kaynaktan otonom apply et — ESO/ArgoCD'nin secret/manifest için yaptığını policy için yap.
> **Policy:** `test/vault-config-reconciler.hcl` · **Script:** `scripts/ops/vault-policy-reconcile.sh`

**Güven modeli (dürüst):** Reconciler approle ≈ **TEST-Vault config-admin** (policy-write + approle-manage). OSS Vault'ta policy-write güçlüdür (teorik self-escalation) → "güvenli" = **bounded**: TEST-only (prod'a ASLA yazılmaz), host-local 0600 secret-id, short-lived token, audited, **git-review = content gate** (script runtime'da policy yazmaz, yalnız commit'li içeriği apply eder). Hard DENY: `unseal / generate-root / seal / rekey / raw / storage / audit-disable / identity / token-create / kv-secret-read / pki-issue`. Yani sızsa bile **Vault ele geçirilemez, unseal edilemez, secret okunamaz, prod'a dokunulamaz** — agent'ın zaten sahip olduğu SSH+sudo güveniyle tutarlı. Root-of-trust (root token + unseal key) **owner-only** kalır.

> **Net (Codex 019f1150):** Reconciler credential staging-sw'deki mevcut sudo trust boundary'sini aşan **yeni bir prod/root-of-trust yetkisi VERMEZ**; ancak TEST Vault named policy/approle surface üzerinde **pratik config-admin yetkisi VERİR** — bu yetki git-review + named-path scope + fail-closed policy-lint + audit + finite secret_id TTL ile *bounded* kabul edilir. (Vault açısından pozitif bir yetkidir; yalnızca mevcut host trust modeline göre sudo-on-staging'den *materially larger* değildir.)

**Bir-kez owner kurulumu (ömürlük — root sadece BURADA; sonra AI-otonom):**
```bash
export VAULT_ADDR=http://localhost:8201        # platform-vault-test
vault login <test-root>                        # SADECE bu adim; bir kez
vault policy write vault-config-reconciler bootstrap/vault-policies/test/vault-config-reconciler.hcl
vault write auth/approle/role/vault-config-reconciler \
  token_policies="vault-config-reconciler" \
  token_ttl=15m token_max_ttl=30m secret_id_ttl=168h bind_secret_id=true
# secret_id_ttl=168h (7g) — Codex 019f1150: ttl=0 (süresiz) host-local dosya
# sızarsa süresiz config-admin demek. Haftalık rotasyon (owner cron / re-run):
#   vault write -f -field=secret_id auth/approle/role/vault-config-reconciler/secret-id \
#     > /home/halil/.vault/reconciler-secret-id ; chmod 600 ...
# İdeal (gelecek): per-run response-wrapped single-use secret_id + bound_cidrs.
umask 077; mkdir -p /home/halil/.vault
vault read  -field=role_id   auth/approle/role/vault-config-reconciler/role-id   > /home/halil/.vault/reconciler-role-id
vault write -f -field=secret_id auth/approle/role/vault-config-reconciler/secret-id > /home/halil/.vault/reconciler-secret-id
chmod 600 /home/halil/.vault/reconciler-role-id /home/halil/.vault/reconciler-secret-id
```

**Bundan sonra (agent, root yok — her policy değişiminde):**
```bash
# tüm git-reviewed policy + approle'leri idempotent apply:
scripts/ops/vault-policy-reconcile.sh
# bir seed approle için taze secret-id üret (seed yapmak üzere):
scripts/ops/vault-policy-reconcile.sh --emit-seed-secret-id audio-gateway-mtls-seeder-test
# kuru çalıştırma:
scripts/ops/vault-policy-reconcile.sh --dry-run
```
Reconciler `common/*` + `test/*` policy'lerini ve manifest'teki approle'leri (eso-runtime, bootstrap-writer, audio-gateway-mtls-seeder) apply eder; **prod/* ASLA**. Runner-management Transit signing yalnız `cross-ai/provider-review-issuer` Kubernetes ServiceAccount rolüne bağlanır; legacy runner AppRole reconcile sırasında silinir ve yokluğu doğrulanır. Yeni policy → manifest'e satır ekle (PR + cross-AI) → reconcile.

## 7. ClusterSecretStore Entegrasyon

`kustomize/base/eso/clustersecretstore-vault.yaml` base tanım:
- `roleId: "eso-runtime"` — literal (placeholder, fail-closed)
- `secretRef.name: vault-approle-secret`, `key: secret-id`

Overlay patch (env-specific UUID):
- `overlays/test/eso/clustersecretstore-patch.yaml` → test Vault `role_id` UUID
- `overlays/prod/eso/clustersecretstore-patch.yaml` → prod Vault `role_id` UUID (OPS-PREREQ gated)

Role ID okuma:
```bash
# Prod Vault
vault read -field=role_id auth/approle/role/eso-runtime/role-id
# → overlays/prod/eso/clustersecretstore-patch.yaml JSON6902 patch'ine commit
```

## 8. Forward-Extension Paths

ADR-0002 §6 forward-extension:
- **Vault replication** (primary-secondary): common policy her iki node'da aynı, extras farklılaşır
- **Common policy büyüdükçe**: yeni dosya ekle `common/eso-runtime-additional.hcl` + both envs write
- **Prod-only external vendor paths**: `prod/eso-runtime-extras.hcl` içine ek path tanımla
- **İkinci host**: Vault replication + common/prod/test aynı yapı kalır

## 9. Open Question (PR #12 iter deferred)

**Vault `api_addr` vs K8s Service endpoint hizalama:**
- Compose `api_addr: http://platform-vault-prod:8200` (intra-network DNS)
- K8s Service `vault.platform-prod.svc.cluster.local:8200` (K8s DNS üzerinden host bridge Endpoints)

Bugün: bilinçli diverge. Vault self-addr intra-compose, K8s tarafı host-bridge Service/Endpoints. ESO ClusterSecretStore K8s Service kullanır.

Gelecek: prod cutover sonrası net entegrasyon runbook'u (PR-next-5 ArgoCD + cutover).

## 10. Negatif Test (policy sınır doğrulama)

```bash
# AppRole login
ROLE_ID=$(vault read -field=role_id auth/approle/role/eso-runtime/role-id)
SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id)
APPROLE_TOKEN=$(vault write -field=token auth/approle/login \
  role_id="${ROLE_ID}" secret_id="${SECRET_ID}")

# Pozitif: ESO beklediği path'ler
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/platform/auth-service     # ✓ read
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/gitops/ghcr-token          # ✓ read
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/platform/keycloak/smoke-client  # ✓ read

# Negatif: policy dışı path'ler
VAULT_TOKEN="${APPROLE_TOKEN}" vault kv get kv/root-secret 2>&1            # ✗ permission denied
VAULT_TOKEN="${APPROLE_TOKEN}" vault write kv/platform/auth-service foo=bar 2>&1  # ✗ permission denied (capabilities=read)

# Prod-specific (sys/audit) sadece prod'da PASS
VAULT_TOKEN="${APPROLE_TOKEN}" vault read sys/audit  # Prod: ✓, Test: ✗
```

## 11. Referanslar

- [ADR-0002 §3.6](../../docs/adr/0002-single-host-dual-cluster.md) Vault Design
- [docs/S2-B1-vault-property-matrix.md](../../docs/S2-B1-vault-property-matrix.md) — Vault path + property tablosu
- [docs/day-2-governance.md §2.1](../../docs/day-2-governance.md) — Secret rotation takvim
- [host-compose/BOOTSTRAP.md](../../host-compose/BOOTSTRAP.md) — Fresh bootstrap credential chain
- [kustomize/base/eso/clustersecretstore-vault.yaml](../../kustomize/base/eso/clustersecretstore-vault.yaml) — ClusterSecretStore base
