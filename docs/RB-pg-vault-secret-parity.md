# RB — PG ↔ Vault Secret Parity Runbook

> **Belge tipi**: Runbook
> **Scope**: Test ve prod cluster — PG user password ↔ Vault canonical value drift recovery
> **İlgili initiative**: PERF-INIT-V2 (PMD §4.1 PR-S1)
> **Cross-ref**: `docs/policy/alphanumeric-password-policy.md`, `scripts/ops/rotate-pg-vault-user.sh`
> **Last incident**: 2026-05-10 Session 43 — multi-service CrashLoopBackOff (KC + permission + variant + endpoint-admin)

---

## 1. Ne zaman bu runbook çalıştırılır

Aşağıdaki sinyallerden biri görüldüğünde:

- ExternalSecret `SecretSyncedError`: "could not get secret data from provider"
- Spring Boot Hikari log: `FATAL: password authentication failed for user "<user>"`
- Spring Boot Hibernate log: `Unable to determine Dialect without JDBC metadata`
- Pod CrashLoopBackOff + previous log'ta `org.postgresql.util.PSQLException`
- `kubectl get externalsecret -A` → birden çok `READY=False`
- Browser smoke: `/api/v1/authz/me` → 503 (downstream service down)

**Cluster drift detector CronJob alert** geldiğinde de aynı akış.

---

## 2. Pre-flight (her recovery öncesi)

1. **Hangi cluster?** `kubectl config current-context` → `k3d-test` veya `k3d-prod`
2. **Hangi servis(ler)?**
   ```bash
   kubectl --context k3d-test -n platform-test get externalsecret \
     -o custom-columns=NAME:.metadata.name,READY:.status.conditions[?(@.type==\"Ready\")].status,REASON:.status.conditions[?(@.type==\"Ready\")].reason
   ```
3. **Vault canonical değeri elimde mi?** Vault container çalışıyor olmalı:
   ```bash
   docker ps | grep vault
   # platform-vault-test (port 8301)
   # platform-vault-prod (port 8200)
   ```
4. **Vault root token okunabilir mi?**
   ```bash
   sudo cat /home/halil/bootstrap-drill/vault-init-test.json | jq -r .root_token
   ```

---

## 3. Standart recovery akışı (script-driven)

### 3.1 Tek servis

```bash
cd /home/halil/platform-k8s-gitops
bash scripts/ops/rotate-pg-vault-user.sh report-service --cluster k3d-test
```

Bu komut **8 step** yürütür:

1. Vault'tan `kv/platform/report-service` `db_username` + `db_password` çeker (masked log)
2. **Policy check**: alphanumeric (`[A-Za-z0-9]+`) + minimum 24 char + PG identifier safety (`^[A-Za-z_][A-Za-z0-9_]*$`). Fail → exit 3 (bkz §6)
3. **Shared-user parity precheck**: `kv/platform/*` altında aynı user'a sahip diğer path'lerin password hash'ini karşılaştır. Mismatch → exit 4 + conflicting paths listesi (bkz §5)
4. PG `platform-pg-test` container'ında `printf '%s\n' "ALTER USER ... WITH PASSWORD '...';" | psql -i` (stdin pipe + literal — eski bash quoting bug'ından korunma)
5. ESO force-sync **+ K8s Secret value compare**: pre/post resourceVersion + decoded password hash == Vault canonical hash. **Mismatch → exit 5** (ExternalSecret varsa parity zorunlu)
6. `rollout restart deploy/<service>` + `rollout status` timeout 240 s
7. **Pod-network DB indicator smoke**: pod'dan `wget /actuator/health/readiness` body parse + `.components.db.status == UP` check:
   - `UP` → DB auth proven ✓
   - `ABSENT` (readiness group'a db dahil değil) → **exit 5** (DB auth NOT proven); override için `--allow-ready-only` flag
   - `DOWN` veya status != UP → exit 5
8. Audit log: `~/.claude/logs/pg-vault-rotation.log` (passwords masked, sadece sha256 hash prefix loglanır)

### 3.2 Toplu (zincir-fail durumu)

**ÖNEMLİ — shared-user trap'i**: birden çok servis aynı PG user'ını kullanıyorsa (örn. `platform` user permission/variant/core-data/notify-orch/user/auth/report tarafından paylaşılıyor), her servisin Vault path'inde **aynı canonical password** olduğundan emin olun. Aksi halde script'in §4 shared-user parity precheck'i her ikinci servis için exit 4 verecek.

**Önce shared-user reconciliation** (manuel):

```bash
# 1. Hangi servisler aynı PG user'ını kullanıyor tespit et
for svc in $(docker exec -e VAULT_TOKEN platform-vault-test \
              vault kv list -format=json kv/platform | jq -r '.[]'); do
  [[ "${svc}" == */ ]] && continue   # subdirectories skip
  USER=$(docker exec -e VAULT_TOKEN platform-vault-test \
          vault kv get -mount=kv -format=json "platform/${svc}" 2>/dev/null \
          | jq -r '.data.data.db_username // .data.data.username // "-"')
  HASH=$(docker exec -e VAULT_TOKEN platform-vault-test \
          vault kv get -mount=kv -format=json "platform/${svc}" 2>/dev/null \
          | jq -r '.data.data.db_password // .data.data.password // ""' \
          | shasum -a 256 | awk '{print $1}')
  printf '%-32s user=%-20s hash=%s\n' "${svc}" "${USER}" "${HASH:0:16}"
done
```

Aynı user için farklı hash gözüküyorsa **canonical seç + diğer path'leri patch** et:

```bash
CANONICAL_PASS="$(docker exec -e VAULT_TOKEN platform-vault-test \
  vault kv get -mount=kv -format=json platform/report-service \
  | jq -r '.data.data.db_password')"

for svc in permission-service variant-service core-data-service \
           notification-orchestrator user-service auth-service; do
  docker exec -e VAULT_TOKEN platform-vault-test \
    vault kv patch "kv/platform/${svc}" db_password="${CANONICAL_PASS}"
done
```

**Sonra toplu rotate**:

```bash
# Tek servisle çalıştır; shared-user'lı diğer servisler bu rotation'dan
# zaten faydalanacak çünkü PG ALTER USER tüm user için tek hash yazıyor.
bash scripts/ops/rotate-pg-vault-user.sh report-service --cluster k3d-test

# Sonra her servis için rollout restart (PG canonical artık eşleşti)
for svc in permission-service variant-service core-data-service \
           notification-orchestrator user-service auth-service \
           endpoint-admin-service; do
  kubectl --context k3d-test -n platform-test rollout restart deploy/"${svc}"
done

# Pod-network Ready bekle
kubectl --context k3d-test -n platform-test get pod -A
```

### 3.3 Dry-run

```bash
bash scripts/ops/rotate-pg-vault-user.sh report-service --dry-run
```

Hiçbir mutasyon yapılmaz; sadece yapılacak işlemleri log'a yazar.

---

## 4. Keycloak master-admin recovery (KC drift)

KC password drift'i farklı bir akıştır. Running KC `kc.sh bootstrap-admin user` komutu **port 9000 conflict** ile fail eder (`Address already in use`); bunun yerine **temp container approach** kullanılır.

```bash
bash scripts/ops/kc-bootstrap-admin-recovery.sh test
```

Adımlar (5 step + trap cleanup):

1. **Pre-flight + DB env extract**: main KC container'dan `KC_DB`, `KC_DB_URL_HOST`, `KC_DB_URL_PORT`, `KC_DB_URL_DATABASE`, `KC_DB_USERNAME`, `KC_DB_PASSWORD_FILE` env'lerini al (compose layout ile birebir uyumlu)
2. **Temp container spawn**: aynı KC image + aynı PG network + secrets mount, `--entrypoint sleep 300`. :9000 host'a publish edilmez → port conflict yok
3. **bootstrap-admin user**: temp container içinde `sh -lc 'export KC_DB_PASSWORD=$(cat $KC_DB_PASSWORD_FILE) && kc.sh bootstrap-admin user --username temp-recovery-... --password:env KC_TEMP_PASS --no-prompt'`. Wrapper entrypoint çalışmadığı için `KC_DB_PASSWORD` literal manuel export edilir
4. Temp container tear down
5. Main KC's Admin REST API ile token al → `admin` user password reset → temp user delete (trap'lı, fail durumunda orphan detected)
6. Verify: admin login → token

**Main KC restart YOK**; password değişiklikleri shared PG DB üzerinden anında main KC'ye yansır.

**Trap cleanup**: temp container ve temp user `EXIT|INT|TERM` trap ile garanti temizlenir. Temp user delete fail olursa `exit 5` + manuel cleanup uyarısı.

---

## 5. pg_hba.conf trust trap'i — ÖNEMLİ

Test cluster'da `pg_hba.conf` şu şekilde:

```
local   all   all                       trust    # local socket
host    all   all   127.0.0.1/32        trust    # host loopback
host    all   all   ::1/128             trust    # host loopback v6
local   replication   all               trust
host    replication   all   127.0.0.1/32   trust
host    replication   all   ::1/128        trust
host    all   all   all                 scram-sha-256    # everything else (pod network!)
```

**Sonuç**: host'tan `psql -h 127.0.0.1 -U platform -d reports_db` HERHANGI bir password ile başarılı olur (trust mode). Ama pod'dan (10.44.x.x) yapılan bağlantı `scram-sha-256` ile gerçek password doğrulaması ister.

**Yanıltıcı false-positive**: 2026-05-10 incident'inde `psql -h 127.0.0.1` testi başarılıydı, ama servisler hâlâ "password authentication failed" alıyordu. Bunun nedeni host loopback'in trust olması.

**Bu yüzden**: smoke testi **mutlaka pod'dan** yapılmalı. `rotate-pg-vault-user.sh` Step 6'da `kubectl wait --for=condition=Ready pod/...` ile dolaylı olarak doğrular (Spring Boot health indicator pod-network'ten PG'ye bağlanır, başarısızsa pod Ready olmaz).

---

## 6. Alphanumeric password policy

`scripts/ops/rotate-pg-vault-user.sh` Step 2'de Vault'tan gelen password alphanumeric değilse `exit 3` ile durur. Sebep:

1. **Spring `${...}` placeholder parser** — JDBC URL içinde `$` veya `{` görürse placeholder değişimi denemeye çalışır → `Unable to resolve placeholder` hatası
2. **Hibernate Dialect detection** — JDBC URL parse fail olunca Hibernate dialect auto-detect edemiyor → `Unable to determine Dialect without JDBC metadata`
3. **YAML escape karmaşıklığı** — ConfigMap/Secret YAML'da `\` veya `"` karakter escape problemi
4. **Shell quoting** — bash double-quote içinde `$` expansion → 2026-05-10 incident'inin ana sebebi

Eğer Vault'ta non-alphanumeric password varsa rotate gerekir:

```bash
# Vault'ta yeni alphanumeric password set et
NEW_PASS="$(openssl rand -base64 48 | tr -d '/+=' | head -c 48)"
docker exec -e VAULT_TOKEN="${VAULT_TOKEN}" platform-vault-test \
  vault kv patch kv/platform/<service> db_password="${NEW_PASS}"
# Sonra bu runbook'un §3.1 akışını çalıştır
```

PR-S2 (paralel iz) bu policy'yi backend tarafında da kalıcı çözer: password env var ayrı, JDBC URL içine gömme yok, ESO template escape net.

---

## 7. Audit log

| Konu | Log dosyası |
|---|---|
| PG rotation | `~/.claude/logs/pg-vault-rotation.log` |
| KC recovery | `~/.claude/logs/kc-recovery.log` |
| Cluster drift detector | (gelecekte) Prometheus + alert webhook |

Her satır: `[ISO8601 timestamp UTC] [script-name] message`. Plain-text password hiçbir log'a basılmaz (mask edilir).

---

## 8. Test fixture — local simülasyon

Bu runbook'un test ortamı için bir simülasyon fixture'ı:

```bash
# 1. Vault'ta yeni canonical set et (örnek)
docker exec -e VAULT_TOKEN="${VAULT_TOKEN}" platform-vault-test \
  vault kv patch kv/platform/report-service \
  db_password="testCanonical$(date +%s)alnum"

# 2. PG'de eski password tut (drift simüle)
docker exec platform-pg-test psql -U postgres -d postgres \
  -c "ALTER USER platform WITH PASSWORD 'eskiPassword123';"

# 3. report-service rollout restart → CrashLoopBackOff bekle
kubectl --context k3d-test -n platform-test rollout restart deploy/report-service
sleep 30
kubectl --context k3d-test -n platform-test logs deploy/report-service --previous | grep "password authentication failed"

# 4. Recovery script çalıştır
bash scripts/ops/rotate-pg-vault-user.sh report-service --cluster k3d-test

# 5. Verify: pod 1/1 Ready
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=report-service
```

---

## 9. İlgili dokümanlar

- `docs/performance/PERF-INIT-V2-plan.md` — PMD §4.1 PR-S1
- `docs/policy/alphanumeric-password-policy.md` — policy detayı
- `scripts/ops/rotate-pg-vault-user.sh` — bu runbook'un script implementasyonu
- `scripts/ops/kc-bootstrap-admin-recovery.sh` — KC akışı
- ADR-0010 §2.5 boundary matrix — operator vs agent yetki sınırı

## 10. Out-of-scope (PR-S2 paralel iz)

Bu runbook **workaround**. Root-cause Spring config fix `platform-backend` repo'da PR-S2 ile yapılır:

- Password ayrı env var (`SPRING_DATASOURCE_PASSWORD`)
- JDBC URL'de password gömme YASAK
- ESO template `${...}` escape syntax
- Helm/kustomize template'lerinde placeholder collision audit

PR-S2 tamamlandığında bu runbook'un §6 alphanumeric policy gevşetilebilir (özel karakter destek).
