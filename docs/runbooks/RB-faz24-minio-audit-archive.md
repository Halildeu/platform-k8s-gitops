# RB — Faz 24 MinIO `audit-archive` 7yr WORM Cold Storage (#1250 / ADR-0042)

> **Tetik**: audit-retention-worker (C-slice) deploy öncesi/sonrası MinIO
> altyapısının doğrulanması; host-compose MinIO recreate sonrası bridge/bucket
> recovery; D29 (Up/Functional/Secured) kanıt yenileme.
>
> **Kapsam**: TEST cluster (k3d-test / platform-test). PROD ayrı (ADR-0042 §5
> off-host legal-grade WORM prerequisite — bu runbook prod'u kapsamaz).

## 0. Topoloji (canlı truth 2026-06-17)

| Bileşen | Değer |
|---|---|
| MinIO host-compose | `/opt/platform/minio/docker-compose.yml` profile=test (`minio-minio-test-1`, `minio/minio:RELEASE.2025-09-07`); #55 ile kurulu (meeting/transcript artifact + audit-archive paylaşımlı instance) |
| S3 API (cluster) | `minio:9000` (Service → Endpoints `172.19.0.252:9000`, platform-test-net **container native port**; host-published `:9100` cluster yolu DEĞİL) |
| Console | host `:9101` |
| Bucket | `audit-archive` — object-lock **COMPLIANCE 7YEARS** + versioning enabled |
| Worker cred | Vault `kv/platform/audit-retention-worker` (`minio_access_key`/`minio_secret_key`) → ESO `audit-retention-worker-secrets` |
| Worker policy | inline session policy: `PutObject`/`GetObject`/`Get`+`PutObjectRetention`/`GetObjectLegalHold` + `ListBucket`/`GetBucket*`; **NO** `DeleteObject`/`BypassGovernanceRetention`/admin |

## 0.1 KRİTİK — MinIO `platform-test-net`'te TEK-HOMED olmalı (return-path)

> **Bulgu 2026-06-17**: `minio-minio-test-1` hem `minio_default` (172.20.0.2,
> PRIMARY) hem `platform-test-net` (172.19.0.252) ağına bağlıyken **multi-homed**
> oluyor. k3d pod'u `172.19.0.252:9000`'e istek atınca MinIO yanıtı **default
> route = minio_default (eth0)** üzerinden gönderiyor → **return-path asymmetry**
> → pod i/o timeout. Host her iki bridge'de olduğu için `host→252:9000=200`,
> ama pod tek-yönlü platform-test-net'te → erişemez. (redis-streams tek-homed
> olduğu için sorunsuz çalışıyor — emsal budur.)
>
> **Çözüm (owner onayı gerek — paylaşılan instance #55 meeting/transcript)**:
> `minio-test`'i **yalnız platform-test-net**'e bağla (redis emsali). İki yol:
> 1. **Durable (tercih)**: `/opt/platform/minio/docker-compose.yml` `minio-test`
>    servisine `networks: { platform-test-net: { ipv4_address: 172.19.0.252 } }`
>    + top-level `networks: { platform-test-net: { external: true } }`; `sudo
>    docker compose --profile test up -d` recreate (buckets named-volume'da kalır;
>    meeting/transcript MinIO'yu henüz kullanmıyor → boş bucket, kesinti yok).
> 2. **Live (geçici)**: `docker network disconnect minio_default minio-minio-test-1`
>    (reversible; recreate'te kaybolur → reconnect script single-home sağlamalı).
>
> Tek-homed olduktan sonra pod → `minio:9000` (Endpoints 172.19.0.252:9000)
> erişir; D29 §4 koşulur. **Bu adım yapılana kadar gitops Endpoints desired-state
> doğru ama pod-path live DEĞİL.**

## 1. Bucket bootstrap (yalnız ilk kurulum / lock-yokken recreate)

> Object-lock **yalnız bucket CREATE'te** açılır. Mevcut audit-archive lock'suz
> ise (boş olmalı) sil + lock'la yeniden yarat. Creds container env'inden
> (`$MINIO_ROOT_USER`) — **asla loglanmaz**.

```bash
ssh halil@staging-sw 'docker exec minio-minio-test-1 sh -c '\''
  mc alias set adm http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
  mc ls adm/audit-archive >/dev/null 2>&1 && mc rb --force adm/audit-archive   # boşsa
  mc mb --with-lock adm/audit-archive
  mc retention set --default COMPLIANCE 7y adm/audit-archive
  mc version info adm/audit-archive          # beklenen: versioning is enabled
  mc retention info --default adm/audit-archive   # beklenen: COMPLIANCE 7YEARS
'\'''
```

## 2. Least-privilege svcacct + Vault seed (yalnız ilk kurulum / rotation)

> MinIO svcacct keys'i **server-generate** eder (argv-leak yok); inline session
> policy least-privilege'i zorlar. Keys host var'larında kalır → Vault'a
> stdin/env ile; **stdout'a yazılmaz**.

```bash
ssh halil@staging-sw '
POLICY="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:GetObject\",\"s3:GetObjectRetention\",\"s3:PutObjectRetention\",\"s3:GetObjectLegalHold\"],\"Resource\":[\"arn:aws:s3:::audit-archive/*\"]},{\"Effect\":\"Allow\",\"Action\":[\"s3:ListBucket\",\"s3:GetBucketLocation\",\"s3:GetBucketVersioning\",\"s3:GetBucketObjectLockConfiguration\"],\"Resource\":[\"arn:aws:s3:::audit-archive\"]}]}"
SVCJSON=$(docker exec -e POL="$POLICY" minio-minio-test-1 sh -c '\''mc alias set adm http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; printf "%s" "$POL" > /tmp/aaw.json; mc admin user svcacct add --json --policy /tmp/aaw.json adm "$MINIO_ROOT_USER"; rm -f /tmp/aaw.json'\'')
AK=$(printf "%s" "$SVCJSON" | jq -r .accessKey); SK=$(printf "%s" "$SVCJSON" | jq -r .secretKey)
VT=$(jq -r .root_token ~/bootstrap-drill/vault-init-test.json)
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$VT" -e AK="$AK" -e SK="$SK" platform-vault-test sh -c '\''vault kv put kv/platform/audit-retention-worker minio_access_key="$AK" minio_secret_key="$SK" minio_endpoint="http://minio:9000" minio_bucket="audit-archive" minio_region="us-east-1"'\''
echo "seeded (AK_len=${#AK} SK_len=${#SK})"   # values redacted
'
```

## 3. Network bridge + gitops apply

```bash
# (a) MinIO'yu platform-test-net'e bağla (recreate sonrası kaybolur → reconnect)
ssh halil@staging-sw 'docker network connect platform-test-net minio-minio-test-1 --ip 172.19.0.252 2>&1 || echo already'
# Recreate sonrası toplu recovery (postgres/kc/vault/minio + Endpoints patch):
./bootstrap/reconnect-compose-to-test-net.sh

# (b) gitops apply (selective — host-bridge Service/Endpoints + NetPol + ESO)
kubectl --context k3d-test apply -k kustomize/overlays/test/eso     # audit-retention-worker-secrets
kubectl --context k3d-test -n platform-test apply -f kustomize/base/host-services/minio-svc.yaml
kubectl --context k3d-test -n platform-test patch endpoints minio --type=json \
  -p='[{"op":"replace","path":"/subsets/0/addresses/0/ip","value":"172.19.0.252"}]'
kubectl --context k3d-test -n platform-test apply -f kustomize/base/netpol/allow-egress-dns-and-host.yaml
```

## 4. D29 smoke (Up / Functional / Secured)

```bash
# Up: Service+Endpoints çözülüyor, reachable
kubectl --context k3d-test -n platform-test get endpoints minio
# Functional: cluster pod'undan put/get/head (least-priv svcacct ile)
#   — ESO Secret'tan AK/SK ile geçici curl/mc; put OK + get OK + retention header.
# Secured: (a) DELETE of a locked version DENIED (COMPLIANCE + least-priv).
#   (b) Overwrite is NOT a hard-deny — same-key re-PUT yeni VERSION yaratır;
#   orijinal version COMPLIANCE-lock'lu retained (version-lock tamper-evidence,
#   NOT "overwrite reddi"). Worker version_id pin'ler (ADR-0042 amendment).
# ESO sync: kubectl get secret audit-retention-worker-secrets (keys MINIO_ACCESS_KEY/MINIO_SECRET_KEY)
kubectl --context k3d-test -n platform-test get externalsecret audit-retention-worker-secrets -o jsonpath='{.status.conditions[0].reason}'
```

> **Secured kanıt notu** (Codex 019ed4f4 düzeltmesi): COMPLIANCE mode'da
> arşivlenmiş object **version**'ı süre dolmadan **root dahil** silinemez/
> kısaltılamaz; least-privilege svcacct ayrıca delete iznini hiç taşımaz
> (defense-in-depth). Kanıt 2026-06-17 svcacct smoke: PUT OK / GET OK / **DELETE
> DENIED**. **ÖNEMLİ — "overwrite denied" YANLIŞ iddia**: S3 Object Lock +
> versioning aynı key'e yeni version yazmayı **engellemez**; eski version
> immutable kalır ama latest değişebilir. Doğru garanti = "arşiv version'ı
> retained + immutable (tamper-evident)", "overwrite reddi" DEĞİL. → ADR-0042
> D4.6/D4.7 **amendment** gerekir: ledger `version_id` tutar; worker HEAD/GET
> **version-specific**; beklenmeyen yeni latest-version = tamper alert
> (fail-closed), orijinal version-lock korur. (Takip: ADR-0042 amendment PR.)

## 5. Rollback / recovery

| Durum | Aksiyon |
|---|---|
| MinIO container recreate → bridge kayıp | `./bootstrap/reconnect-compose-to-test-net.sh` (docker connect + Endpoints patch) |
| Endpoints IP drift | `kubectl ... patch endpoints minio ... value:<yeni IP>` (docker inspect ile doğrula) |
| svcacct cred sızıntısı | `mc admin user svcacct rm adm <AK>` + §2 yeniden seed + ESO refresh (`kubectl annotate es audit-retention-worker-secrets force-sync=$(date +%s) --overwrite`) |
| Bucket yanlış (lock yok) | §1 (boşsa recreate; doluysa **DELETE YASAK** — COMPLIANCE altında zaten silinemez; yeni bucket + migration ADR gerek) |

## 6. Referans

- ADR-0042 (audit-archive retention worker kontratı) + ADR-0031 (cold-off-hot topoloji).
- Issue gitops`#1250` (worker) + object-store prerequisite issue.
- Codex plan-time `019ed4f4`.
- Pattern emsali: `kustomize/base/host-services/redis-streams-svc.yaml` + `bootstrap/reconnect-compose-to-test-net.sh`.
