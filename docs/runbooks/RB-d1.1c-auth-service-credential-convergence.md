# Runbook — D1.1c auth-service Credential Convergence

> **Trigger**: D1.1c Phase 3 RCA (2026-05-16) — auth-service'in Vault path'i `kv/platform/auth-service` `db_password`, paylaşımlı `platform` PG rolünün gerçek password'ünden drift etmiş. auth-service DB layer'ı işlevsiz (eager connection `password authentication failed`; lazy connection `DDL_AUTO=none` ile maskeli).
> **RCA**: [`docs/d1.1c-flyway-rca-discovery-2026-05-14.md`](../d1.1c-flyway-rca-discovery-2026-05-14.md) §5.Y
> **Codex review**: thread `019e32d8-e3db-7b41-9c9b-a2b536b8b95b` — VERDICT REVISE absorbed (RCA + fix AGREE; Vault write operator-only; Flyway re-enable follow-up)
> **Supersedes**: `RB-d1.1a-auth-service-vault-rotation.md` — o runbook'un `6f765b6d…` hedefi misdiagnosis (retracted)

---

## 1. Bağlam

5 backend servisi (auth-service, user-service, core-data-service, permission-service, variant-service) PG rolü `platform`'ı paylaşır → tek rol, tek password. D1.1c Phase 3 canlı kanıtı:

- PG `platform` rolünün gerçek password'ü hash prefix **`808bc9ef23cfa266`** (user/core-data/permission/variant Secret'leri bu değeri taşır; `pg_stat_activity` `platform`'ı 7 DB'ye canlı bağlı gösterir).
- auth-service'in Vault path'i `kv/platform/auth-service` `db_password` yanlış değer (hash prefix `fddb842b…`) → `auth_db`'ye hiç `platform` bağlantısı yok.
- Direct TCP/SCRAM kanıtı: `808bc9ef…` değeri `platform@auth_db` bağlanır; `fddb842b…` `FATAL: password authentication failed`.

**Fix**: `kv/platform/auth-service` `db_password`'ü canonical `platform` değerine converge et. PG `platform` rolünün password'üne **DOKUNMA** — 4 servis o role bağımlı, `ALTER ROLE` yanlış blast radius üretir.

---

## 2. Authority Boundary

| Adım | Aktör | Sebep |
|---|---|---|
| 1. Vault `db_password` patch (canonical değeri kopyala) | **Operator** | Credential material read/write — ADR-0011 §2.3 + GA-002; Codex `019e32d8` Q3 REVISE: CLAUDE.md Pre-Prod Full Authority bunu override etmez |
| 2. Vault hash parity verify + prefix sinyali | **Operator** | Plaintext credential handling; agent'a yalnız 16-char hash prefix |
| 3. ESO force-sync (kubectl annotate) | **Agent** | kubectl-level, plaintext yok |
| 4. Secret hash parity verify | **Agent** | Read-only hash prefix kanıt |
| 5. auth-service rollout restart | **Agent** | Pre-prod Full Authority kapsamı |
| 6. DB connection proof (debug pod / TCP-SCRAM) | **Agent** | Standard verification |
| 7. Drift detector re-run | **Agent** | Read-only |

**Hidden shell protokolü**: Operator adımları (1-2) agent transcript dışında çalışır; agent'a yalnız hash prefix (16 char) + status sinyali iletilir. Plaintext password, Vault token, dosya yolu agent transcript'ine asla düşmez.

---

## 3. Operator Adımları (Hidden Shell, agent context dışı)

### Adım 1: Canonical password'ü auth-service Vault path'ine kopyala

Canonical değer `kv/platform/user-service` `db_password`'da (= çalışan `platform` password'ü). Aynı değer auth-service path'ine patch'lenir. Değer dosyaya düşmez, echo edilmez — tek pipe:

```bash
# Operator, staging-sw hidden shell. cwd = platform-k8s-gitops repo kökü.
# Ön koşul: VAULT_BOOTSTRAP_ROLE_ID + VAULT_BOOTSTRAP_SECRET_ID (veya
#           VAULT_BOOTSTRAP_SECRET_ID_FILE) hazır — platform-bootstrap-writer
#           AppRole; root token GEREKMEZ.
kubectl --context k3d-test -n platform-test get secret user-service-secrets \
  -o jsonpath='{.data.SPRING_DATASOURCE_PASSWORD}' | base64 -d \
  | scripts/ops/platform-ops-vault-patch.sh \
      --service auth-service --field-from-stdin db_password
```

`platform-ops-vault-patch.sh` KV v2 patch semantiği kullanır — yalnız `db_password` değişir; `db_username`, `jwt_private_key`, `jwt_public_key`, `keycloak_client_secret`, `impersonation_broker_client_secret` korunur. Script token'ı self-revoke eder, audit satırını stderr'e yazar (field adı, value değil).

### Adım 2: Vault parity verify + agent'a sinyal

```bash
docker exec platform-vault-test vault kv get \
  -field=db_password kv/platform/auth-service | sha256sum | head -c 16
# Beklenen: 808bc9ef23cfa266
```

Operator agent'a iletir (chat/komentar):

> Vault patch tamam. `kv/platform/auth-service` `db_password` hash prefix `808bc9ef23cfa266` (canonical `platform` ile match).

Plaintext password / Vault token agent transcript'ine yazılmaz.

---

## 4. Agent Adımları (operator Adım 2 sinyali sonrası)

### Adım 3: ESO force-sync

```bash
PRE_RV=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get secret auth-service-secrets -o jsonpath='{.metadata.resourceVersion}'")
echo "PRE_RV=$PRE_RV"

ssh halil@staging-sw "kubectl --context k3d-test -n platform-test annotate \
  externalsecret auth-service-secrets force-sync=\"\$(date +%s)\" --overwrite"
```

### Adım 4: Secret hash parity verify (hash-authoritative polling)

```bash
EXPECTED="808bc9ef23cfa266"
# 120s poll: auth-service-secrets SPRING_DATASOURCE_PASSWORD base64 -d | sha256sum
# head -c 16 == EXPECTED olana kadar. PASS → resourceVersion bump audit.
# (RB-d1.1a Adım 5 pattern; scripts/ops/rotate-pg-vault-user.sh hash polling)
```

### Adım 5: auth-service rollout restart

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout \
  restart deploy/auth-service"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout \
  status deploy/auth-service --timeout=300s"
```

### Adım 6: DB connection proof

İzole debug pod — auth-service image, `envFrom` aynı CM+Secret, inline `SPRING_JPA_HIBERNATE_DDL_AUTO=validate`, label `app.kubernetes.io/part-of=platform` (NetworkPolicy egress için zorunlu), `restartPolicy: Never`:

- **Beklenen**: `Started AuthServiceApplication` (clean boot). Eski sonuç (D1.1c Phase 3, fix öncesi): `FATAL: password authentication failed`.
- Debug pod credential'ı `envFrom` ile alır — agent plaintext credential'a **dokunmaz**.
- Pod sonrası `kubectl delete pod` ile temizlenir.

Plus running pod log: `password authentication failed` / `HikariPool ... Exception during pool initialization` YOK.

> **Boundary notu (Codex `019e32d8`)**: Direct TCP/SCRAM testi (Secret plaintext'ini shell değişkenine çıkarıp `psql`'e verir) **agent adımı DEĞİL** — credential-read sınıfı (ADR-0011 §2.3 + GA-002). Gerekirse operator hidden-shell'de yapılır; agent'a yalnız PASS/FAIL sinyali döner. Agent'ın acceptance kanıtı = izole debug pod clean boot + running pod log proof (ikisi de plaintext credential'a dokunmaz).

### Adım 7: Drift detector re-run

```bash
ssh halil@staging-sw "cd /home/halil/platform/platform-k8s-gitops && \
  python3 scripts/drift_detection/check_deployment_contracts.py \
  --mode runtime --env test --render-source kustomize/overlays/test \
  --live-context k3d-test --live-namespace platform-test \
  --catalog docs/operations/services.yaml --output text 2>&1 | tail -10"
# Beklenen: 0 P1 korunur (credential drift bu detector kapsamında değil —
# regression olmadığı doğrulanır)
```

---

## 5. Acceptance Gate (D1.1c Phase 3 kapanış)

- ☑️ Adım 2 — Vault `kv/platform/auth-service` `db_password` hash prefix `808bc9ef23cfa266`
- ☑️ Adım 4 — `auth-service-secrets` `SPRING_DATASOURCE_PASSWORD` hash parity `808bc9ef23cfa266`
- ☑️ Adım 5 — rollout success, restartCount=0
- ☑️ Adım 6 — DB connection proof: debug pod `DDL_AUTO=validate` clean boot **VEYA** TCP/SCRAM PASS
- ☑️ auth-service log'unda `password authentication failed` yok

---

## 6. Rollback

Bu fix auth-service'i **bozuk** state'ten (DB layer işlevsiz, ~auth_audit_events 0 satır) **doğru** state'e taşır — geri dönülecek "iyi" eski state YOK. Eski Vault değeri (`fddb842b…`) bozuktu; revert YASAK.

- auth-service `DDL_AUTO=none` ile boot ettiği için Adım 5 rollout restart, fix öncesiyle aynı şekilde pod'u Running'e getirir (DB başarısız olsa bile maskeli). Yani restart'ın kendisi düşük riskli.
- Beklenmedik bir hata → `kubectl rollout undo deploy/auth-service` eski pod template'ine döner; Secret canonical kalır. Durum analiz edilir, Vault canonical'a dokunulmaz.

---

## 7. Flyway Restoration — Ayrı Follow-up

Bu runbook **sadece credential convergence** kapsar (Codex `019e32d8` Q5 — REVISE/defer). Flyway re-enable (`DDL_AUTO=validate` + `SPRING_FLYWAY_ENABLED=true`) ayrı plan + ayrı PR:

- `auth_db` non-empty (Hibernate-generated tablolar) + `flyway_schema_history` yok → `spring.flyway.baseline-on-migrate=true` + doğru `baseline-version` kararı
- platform-backend `auth-service` migration inventory + canlı schema diff
- one-shot `flyway info` / `flyway validate`
- Plan-time Codex consultation ayrı thread

---

## 8. Referanslar

- RCA: `docs/d1.1c-flyway-rca-discovery-2026-05-14.md` §5.Y
- Codex thread: `019e32d8-e3db-7b41-9c9b-a2b536b8b95b` (Phase 3 RCA review)
- Vault patch aracı: `scripts/ops/platform-ops-vault-patch.sh` (ADR-0010 DR-3, `platform-bootstrap-writer` AppRole)
- Hash-authoritative polling pattern: `scripts/ops/rotate-pg-vault-user.sh`
- Superseded runbook: `docs/runbooks/RB-d1.1a-auth-service-vault-rotation.md`
- ADR-0011 §2.3 credential-write boundary + `docs/adr/0011-gray-areas/GA-002-eso-approle-reads.md`
- CLAUDE.md HARD RULE Pre-Production Full Authority (2026-04-29)

## 9. Follow-up — Credential Topology Consolidation

5 servis `platform` rolünü paylaşır ama her biri Vault'ta ayrı `kv/platform/<service>` `db_password` kopyası tutar → drift-prone (bu olayın yapısal kök nedeni). Codex `019e32d8` Q4 önerisi:

- **Near-term**: paylaşımlı `platform` rolü için tek canonical Vault path (`db_username`/`db_password`); per-service ExternalSecret'ler bu iki field için o path'e bakar. Service-specific alanlar (JWT, KC client secret, internal API key) kendi service path'inde kalır.
- **Long-term**: per-service dedicated PG roles (daha büyük blast radius, ayrı faz).

Ayrı follow-up task olarak takip edilir.
