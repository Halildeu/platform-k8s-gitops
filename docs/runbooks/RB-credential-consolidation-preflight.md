# Runbook — Credential Consolidation Faz A Preflight Checklist

> **Trigger**: PR-0 (policy allowlist + S2-B1 matrix) merged → pilot repoint (sprint parçası #3) açılmadan ÖNCE çalıştırılır.
> **Scope**: Faz A canonical path `kv/platform/pg-platform-role` Vault + policy hazırlık doğrulaması. **Runtime repoint YOK** — bu runbook yalnız hazırlık gate'i.
> **Plan**: [`docs/architecture/runtime/credential-consolidation-plan.md`](../architecture/runtime/credential-consolidation-plan.md) §5-§6
> **Codex**: thread `019e3386-f41e-7820-861a-0ab90255e09c` (consolidation plan AGREE-with-scoping)

---

## 1. Bağlam

Faz A: 7 platform-role servisi (auth / user / core-data / variant / permission / notification-orchestrator / endpoint-admin) `SPRING_DATASOURCE_USERNAME`/`PASSWORD`'ünü tek canonical path `kv/platform/pg-platform-role`'e repoint eder. Her servisin ayrı `db_password` kopyası drift sınıfını doğurmuştu (D1.1c auth-service kök nedeni).

Repoint (sprint #3+) yalnız ExternalSecret YAML değişimiyle **ÇALIŞMAZ** (plan §5): canonical path Vault'ta yoksa veya iki policy allowlist'e eklenmemişse ESO **403** alır → Secret sync fail. Bu runbook o ön koşulun karşılandığını — path mevcut + populate + iki policy hazır — pilot repoint'ten önce doğrular. Hepsi ☑️ olmadan pilot AÇILMAZ.

## 2. Authority Boundary

| Adım | Aktör | Sebep |
|---|---|---|
| P1. Policy HCL apply (eso-runtime + bootstrap-writer) | **Operator** | Vault policy mutation |
| P2. Canonical path create + populate | **Operator** | Plaintext credential material — ADR-0010 §2.5 + ADR-0011 §2.3 |
| P3. ESO read capability verify | **Operator** | Vault token capability testi |
| P4. bootstrap-writer write capability verify | **Operator** | Vault token capability testi |
| P5. Hash-only proof → agent sinyali | **Operator** | Plaintext handling; agent'a yalnız 16-char hash prefix |
| A1. PR-0 merged confirm | **Agent** | Read-only git/gh |
| A2. Repoint henüz yok confirm | **Agent** | Read-only grep |
| A3. kustomize build sanity | **Agent** | Read-only render |

**Hidden shell protokolü**: Operator adımları (P1-P5) agent transcript dışında çalışır; agent'a yalnız hash prefix (16 char) + status sinyali iletilir. Plaintext password, Vault token, secret-id dosya yolu agent transcript'ine asla düşmez.

---

## 3. Operator Adımları (hidden shell, agent context dışı)

### P1 — Policy HCL apply (~2 dk)

PR-0 merge sonrası canonical HCL repo'da. İki policy uygulanır:

```bash
# Operator, staging-sw, platform-k8s-gitops repo kökü. Vault policy-write token.
vault policy write eso-runtime \
  bootstrap/vault-policies/common/eso-runtime.hcl
vault policy write platform-bootstrap-writer \
  bootstrap/vault-policies/common/bootstrap-writer.hcl
```

- **Beklenen**: `Success! Uploaded policy: eso-runtime` + `Success! Uploaded policy: platform-bootstrap-writer`
- **Fail sinyali**: `permission denied` (token policy-write yetkisiz) · HCL parse error
- **Devam eşiği**: iki policy de Success

### P2 — Canonical path create + populate (~2 dk)

Canonical `platform` password değeri çalışan servis Secret'lerindeki ile aynı (`kv/platform/user-service` `db_password` — D1.1c'de doğrulanmış canonical kaynak). `db_username` = `platform` (hassas değil). Password değeri **stdin pipe** ile geçer — `db_password=-` Vault CLI'a değeri stdin'den okutur; plaintext argv'ye, command substitution'a veya dosyaya düşmez:

```bash
# Operator hidden shell. platform-bootstrap-writer AppRole token (create yetkisi).
vault kv get -field=db_password kv/platform/user-service \
  | vault kv put kv/platform/pg-platform-role db_username=platform db_password=-
```

- **Beklenen**: `Success! Data written to: kv/platform/pg-platform-role` (version 1)
- **Fail sinyali**: `permission denied` (bootstrap-writer policy P1'de uygulanmadı) · `db_password` boş
- **Devam eşiği**: version 1 yazıldı
- **Not**: `vault kv put` yeni path için doğru (create); re-run idempotent. `db_password=-` tek stdin key'i — `vault kv get -field` çıktısı trailing newline içermez, değer birebir geçer. Wrapper (`platform-ops vault-patch`) bu path'i henüz desteklemiyor → §6.

### P3 — ESO read capability verify (~1 dk)

eso-runtime token'ı canonical path'i okuyabilmeli (403 değil):

```bash
# Operator. eso-runtime AppRole token (geçici login).
VAULT_TOKEN=<eso-runtime-token> vault kv get \
  -field=db_username kv/platform/pg-platform-role
```

- **Beklenen**: `platform` döner (403 YOK)
- **Fail sinyali**: `403` / `permission denied` → eso-runtime policy uygulanmadı veya HCL'de `kv/data/platform/pg-platform-role` path eksik
- **Devam eşiği**: read OK, 403 yok

### P4 — bootstrap-writer write capability verify (~1 dk)

```bash
# Operator. bootstrap-writer token.
vault token capabilities <bootstrap-writer-token> kv/data/platform/pg-platform-role
```

- **Beklenen**: `create, read, update` listelenir
- **Fail sinyali**: `update`/`create` yok → bootstrap-writer HCL'de path eksik
- **Devam eşiği**: P2 zaten başarılı olduğu için write yetkisi fiilen kanıtlı; bu adım explicit doğrulama

### P5 — Hash-only proof → agent sinyali (~1 dk)

```bash
docker exec platform-vault-test vault kv get \
  -field=db_password kv/platform/pg-platform-role | sha256sum | head -c 16
# Beklenen: 808bc9ef23cfa266  (canonical platform password — D1.1c ile match)
docker exec platform-vault-test vault kv get \
  -field=db_username kv/platform/pg-platform-role
# Beklenen: platform
```

Operator agent'a iletir (chat/yorum):

> Preflight P2-P5 tamam. `kv/platform/pg-platform-role` — `db_password` hash prefix `808bc9ef23cfa266`, `db_username=platform`. eso-runtime read OK, bootstrap-writer write OK.

Plaintext password / Vault token agent transcript'ine yazılmaz.

---

## 4. Agent Adımları

### A1 — PR-0 merged confirm (~1 dk)

```bash
git -C <repo> fetch origin main --quiet
grep -c "kv/data/platform/pg-platform-role" \
  bootstrap/vault-policies/common/eso-runtime.hcl \
  bootstrap/vault-policies/common/bootstrap-writer.hcl
```

- **Beklenen**: iki dosyada da `pg-platform-role` path mevcut (her biri ≥1)
- **Fail sinyali**: path yok → PR-0 merge edilmemiş
- **Devam eşiği**: iki HCL'de de path var

### A2 — Repoint henüz yok confirm (~1 dk)

```bash
grep -rl "pg-platform-role" kustomize/ 2>/dev/null
```

- **Beklenen**: çıktı **BOŞ** — preflight pilot repoint'ten ÖNCE çalışır
- **Fail sinyali**: bir ExternalSecret zaten `pg-platform-role` referansı içeriyor → sequencing ihlali; pilot runbook'a geç
- **Devam eşiği**: `kustomize/` altında repoint referansı yok

### A3 — kustomize build sanity (~1 dk)

```bash
kubectl kustomize kustomize/overlays/test/eso >/dev/null && echo "test/eso OK"
kubectl kustomize kustomize/overlays/prod/eso >/dev/null && echo "prod/eso OK"
```

- **Beklenen**: ikisi de `OK` (PR-0 manifest'e dokunmadı → clean başlangıç state kanıtı)
- **Fail sinyali**: build error → ilgisiz drift; pilot öncesi çöz
- **Devam eşiği**: iki overlay de build ediyor

---

## 5. Preflight Gate

Hepsi ☑️ → pilot repoint (sprint parçası #3) açılır:

- ☐ P1 — iki policy apply Success
- ☐ P2 — `kv/platform/pg-platform-role` version 1 yazıldı
- ☐ P3 — eso-runtime read OK (403 yok)
- ☐ P4 — bootstrap-writer write capability doğrulandı
- ☐ P5 — hash prefix `808bc9ef23cfa266` + `db_username=platform` (operator sinyali)
- ☐ A1 — PR-0 MERGED, iki HCL'de path mevcut
- ☐ A2 — `kustomize/` altında repoint referansı yok
- ☐ A3 — test/eso + prod/eso build sanity OK

---

## 6. Bu Preflight NE DEĞİL

- **ExternalSecret repoint** (`remoteRef.key` → canonical path değişimi) — ayrı pilot runbook (sprint #3).
- **Prod Vault** `pg-platform-role` — bu runbook **test Vault** gate'i. Prod ayrı tekrar gerektirir (plan §6 test/prod truth ayrımı); prod credential write açık user approval (ADR-0010 §2.5).
- **7-servis live switch** — kademeli (plan §7): test pilot 1 → test cohort → prod. Tek atomik switch ÖNERİLMEZ.
- **`platform-ops vault-patch` wrapper desteği** `pg-platform-role` path'i için — wrapper'ın `--service` allowlist'i şu an yalnız per-service path'leri kapsıyor; canonical path create/rotation için wrapper genişletmesi ayrı follow-up (consolidation execution sprint kapsamı). Bu preflight'ta P2 doğrudan Vault CLI (`vault kv put`, stdin pipe) kullanır — bootstrap-writer AppRole yine de policy düzeyinde yetkili.

---

## 7. Rollback / Abort

- **P1 policy**: additive — yeni path eklendi, mevcut servis path'leri etkilenmedi. Geri almak gerekirse PR-0 `git revert` + policy yeniden apply.
- **P2 canonical path** yanlış değerle yazıldıysa: operator `vault kv put` ile düzeltir (KV v2 yeni version; eski version history'de kalır).
- Hiçbir ExternalSecret bu path'i okumadığı için preflight aşamasında **cluster etkisi YOK** — abort güvenli, repoint henüz başlamadı.

---

## 8. Referanslar

- Plan: `docs/architecture/runtime/credential-consolidation-plan.md` §5-§6
- Policy: `bootstrap/vault-policies/common/eso-runtime.hcl`, `bootstrap/vault-policies/common/bootstrap-writer.hcl`
- Property matrix: `docs/S2-B1-vault-property-matrix.md` §1.6 + §2.4
- D1.1c convergence runbook (hash-proof pattern): `docs/runbooks/RB-d1.1c-auth-service-credential-convergence.md`
- Vault patch aracı: `scripts/ops/platform-ops-vault-patch.sh` (ADR-0010 DR-3)
- ADR-0010 Vault credential lifecycle + DR; ADR-0011 §2.3 boundary declaration
- Codex thread: `019e3386-f41e-7820-861a-0ab90255e09c`
