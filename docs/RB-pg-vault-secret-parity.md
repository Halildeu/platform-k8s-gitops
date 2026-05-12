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

Bu komut:

1. Vault'tan `kv/platform/report-service` `db_username` + `db_password` çeker
2. **Alphanumeric policy** check (özel karakter varsa exit 3 — rotate gerek; bkz §5)
3. PG `platform-pg-test` container'ında `ALTER USER ... WITH PASSWORD '...';`
4. ExternalSecret force-sync + `Ready=True` bekle
5. `rollout restart deploy/<service>` + `rollout status` timeout 240 s
6. Pod-network smoke: pod `Ready=True` (NOT 127.0.0.1=trust)
7. Audit log: `~/.claude/logs/pg-vault-rotation.log`

### 3.2 Toplu (zincir-fail durumu)

```bash
for svc in permission-service variant-service core-data-service \
           notification-orchestrator user-service auth-service \
           report-service endpoint-admin-service; do
  bash scripts/ops/rotate-pg-vault-user.sh "${svc}" --cluster k3d-test || \
    echo "WARN: ${svc} failed, continuing"
done
```

### 3.3 Dry-run

```bash
bash scripts/ops/rotate-pg-vault-user.sh report-service --dry-run
```

Hiçbir mutasyon yapılmaz; sadece yapılacak işlemleri log'a yazar.

---

## 4. Keycloak master-admin recovery (KC drift)

KC password drift'i farklı bir akıştır çünkü KC `kc.sh bootstrap-admin` komutu ile temp admin oluşturur, ardından mevcut `admin` user'ının password'ünü Admin REST API üzerinden sıfırlar.

```bash
bash scripts/ops/kc-bootstrap-admin-recovery.sh test
```

Adımlar:

1. Temp recovery admin (32-char random password) bootstrap
2. Temp admin ile master realm token al
3. `admin` user password = canonical file value (`kc_admin_password.txt`)
4. Temp recovery admin sil (audit clean)
5. Verify: admin login → token alınabiliyor

KC container yeniden başlatılması gerekmez; password DB'ye doğrudan yazılır.

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
