# RB-vault-ops — Vault Operasyon Runbook (Canonical)

ID: RB-vault-ops
Service: vault-cluster (compose stateful tier, ADR-0002 §0.5 D6)
Status: Canonical (gitops authoritative)
Owner: @team/platform

> **Provenance:** platform-ssot `docs/04-operations/RUNBOOKS/RB-vault.md` → migrated as-is (Faz 18.4 Phase 1). Source repo decommissioning ilerledikçe gitops canonical hâline gelir. İçerik compose ortamı için geçerli; K8s tarafı için [S5-vault-audit-retention.md](./S5-vault-audit-retention.md) ve [S2-B1-vault-property-matrix.md](./S2-B1-vault-property-matrix.md) ek referanstır.
>
> **Faz 18.4 ops replace:** host cron install için [RB-vault-ops-host-cron.md](./RB-vault-ops-host-cron.md).

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Vault rekey, unseal, root token yönetimi ve kritik bakım işlemlerini
  tek bir operasyonel runbook altında toplamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Sorumlu ekipler: Platform Engineering (operasyon), Security Engineering (gözetim).
- Ortamlar: prod, stage, test (aynı runbook prensipleri ile).
- Ana sorumluluklar:
  - 3-of-5 shard modeliyle rekey / unseal süreçleri.
  - Root token’in yalnızca break-glass senaryosu için yönetilmesi.
  - Kasalama envanteri ve erişim prosedürlerinin güncel tutulması.
- SLA/SLO:
  - SLA: Vault erişilebilirliği için platform genel SLA’sına uyum (örn. ≥ 99.9%).  
  - SLO örnekleri:
    - Rekey operasyonu planlandığı anda başarıyla tamamlanmalı.  
    - Unseal işlemleri planlı bakım sırasında belirlenen süre içinde bitmeli.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma:
  - Vault servislerini cluster üzerinde başlat, `vault status` ile sealed/unsealed
    durumunu kontrol et.
  - Gerekli shard sayısı ile unseal işlemini tamamla.
- Durdurma / bakım:
  - Planlı bakım öncesi backup ve gerekli notları al.
  - Servisleri kontrollü şekilde durdur veya node’ları maintenance’e al.
  - Bakım sonrası vault’un unsealed ve healthy olduğundan emin ol.
  - Smoke ve SLO kontrollerini çalıştır:
    - `python3 scripts/release_smoke_check.py user-service`
    - `python3 scripts/release_smoke_check.py permission-service`
    - Gerekirse `python3 scripts/check_slo_sla.py metrics.json`

-------------------------------------------------------------------------------
3.1 DEV VAULT (RAFT + VOLUME) – DEV-ONLY
-------------------------------------------------------------------------------

- Lokal geliştirmede `backend/docker-compose.yml` içindeki `vault` servisi kalıcı raft storage ile çalışır.
- İlk kurulum: `bash backend/scripts/vault/dev_init.sh`
  - Bu adım init çıktısını `backend/.vault-dev/` altına yazar (git’e girmez).
  - Ayrıca `vault-unseal-key` / `vault-root-token` helper dosyalarını üretir.
- Unseal:
  - Otomatik (önerilen): `backend/docker-compose.yml` içindeki `vault-unseal` sidecar servis’i
    Vault restart sonrası sealed durumu görür ve unseal eder.
  - Manuel (fallback): `bash backend/scripts/vault/dev_unseal.sh`
- KV v2 mount: `secret/` (enable: `bash backend/scripts/vault/dev_enable_kv.sh`)
- `vault server -dev` / inmem mod kullanılmaz; state `vault-data` volume’da tutulur.
- Init/unseal çıktıları repo’ya yazılmaz; `backend/.vault-dev/` altında tutulur (.gitignore).
- Dev vault restart sonrası:
  - `vault-unseal` çalışıyorsa otomatik unseal beklenir.
  - `vault-unseal` yoksa manuel unseal gerekir (`bash backend/scripts/vault/dev_unseal.sh`).
- SSOT seed: `bash backend/scripts/vault/seed-web-playwright-stage.sh` (Playwright staging config; opsiyonel `PW_REAL_USER_EMAIL` / `PW_REAL_USER_PASSWORD` dahil).
- GitHub-only seed: `Vault → GitHub Secrets Sync (Manual)` workflow’unda
  `mode=seed-web-playwright`; bu mod `playwright_base_url` input’unu ve mevcut
  GitHub repo secret’larındaki `KEYCLOAK_*` değerlerini
  `secret/<env>/web-playwright/{config,keycloak}` path’lerine yazar.
- Sonra `vault-secrets-sync` workflow’unu `dry_run=true` ile çalıştırıp FOUND/MISSING kontrol et.
- KV v2 “key kaybı” şüphesi (izleme):
  - Key list (value yok): `vault kv get -format=json secret/<env>/<path> | jq -r '.data.data | keys[]'`
  - Version history: `vault kv metadata get secret/<env>/<path>`
  - Geri alma: `vault kv rollback -version=<N> secret/<env>/<path>`
  - Not: “put” (tam yazım) secret’ı overwrite eder; tek bir alan güncellemek için `vault kv patch` tercih edilir.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Loglar:
  - Vault server log’ları (örn. `logs-vault-*` index’leri).
  - Rekey/unseal log dosyaları: `vault-rekey-log-YYYYMMDD.md`,
    `vault-unseal-log-YYYYMMDD.md`.
- Metrikler:
  - Vault availability, request latency, error rate.
  - Backup job’larının başarı durumu (örn. CronJob metrikleri).
- Dashboard’lar:
  - Vault ve secret management için monitoring panoları (Grafana vb.).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Rekey sırasında hata:
  - Given: Rekey kararı alınmış ve süreç başlatılmıştır.  
    When: Rekey komutları hata üretir veya gerekli shard sayısı sağlanamaz.  
    Then: İşlemi durdur, mevcut shard envanterini ve sahiplik bilgilerini
    doğrula; gerekli onaylarla birlikte süreci yeniden planla ve rekey logunu
    güncelle.

- [ ] Arıza senaryosu 2 – Unseal başarısız:
  - Given: Restart/upgrade sonrası Vault sealed durumdadır.  
    When: Yeterli shard ile unseal denemeleri başarısız olur veya tutarsızlık
    gözlenir.  
    Then: Kullanılan shard’ları ve komutları kontrol et, gerekirse farklı
    node’da dene; sorun devam ederse bu runbook’taki notlara göre incident aç
    ve Security/Platform ekibiyle birlikte ilerle.

- [ ] Arıza senaryosu 3 – Root token misuse / compromise şüphesi:
  - Given: Root token sadece break-glass senaryosu için kullanılmalıdır.  
    When: Yetkisiz kullanım şüphesi veya sızıntı işaretleri görülür.  
    Then: Root token’ı derhal revoke et, audit loglarını incele, ilgili
    governance/incident sürecini başlat ve gelecekteki kullanım için ek
    koruma önlemlerini planla.

-------------------------------------------------------------------------------
5.1 NETWORK DRIFT (host-bridge IP kopması, 2026-05-20 vault-prod incident)
-------------------------------------------------------------------------------

**Semptom:** k3d-<env> cluster'ından Vault'a (veya postgres/keycloak'a)
erişim aniden koptu. `kubectl -n platform-<env> get endpoints <svc>` boş
subset veya IP hedef container'ı değil başka bir container'ı gösteriyor.
ExternalSecret'lar `SecretSyncedError` durumunda kalıyor. `kubectl describe
service vault` "no endpoints" hatası veriyor.

**Kök neden sınıfı:** `host-compose/*/{prod,test}/docker-compose.yml`
içindeki container docker network attach'i kayboluyor VEYA docker
DHCP yeni bir IP atıyor — overlay Endpoints resource ise sabit IP'ye
pin'li. Live incident (2026-05-20): `platform-vault-prod` container'ı
`NetworkSettings.Networks: {}` durumunda kaldı (Up 39m) ve prod
ExternalSecret'lar 2d17h `SecretSyncedError`'da kaldı.

**Kalıcı fix (2026-07-06 landed):** Tüm host-bridge servisler compose
tarafında static IPv4 (`ipv4_address`) ile pin'li; overlay Endpoints ile
aynı IP'yi paylaşıyor. Reserved IP tablosu (authoritative):

| Env | Servis | Container | Docker network | Static IP | K8s Endpoint IP | Port |
|---|---|---|---|---|---|---|
| prod | postgres | `platform-pg-prod` | `platform-prod-net` | `172.21.0.10` | `172.21.0.10` | 5432 |
| prod | keycloak | `platform-kc-prod` | `platform-prod-net` | `172.21.0.3` | `172.21.0.3` | 8080 |
| prod | vault | `platform-vault-prod` | `platform-prod-net` | `172.21.0.9` | `172.21.0.9` | 8200 |
| test | postgres | `platform-pg-test` | `platform-test-net` | `172.19.0.6` | `172.19.0.6` | 5432 |
| test | keycloak | `platform-kc-test` | `platform-test-net` | `172.19.0.7` | `172.19.0.7` | 8080 |
| test | vault | `platform-vault-test` | `platform-test-net` | `172.19.0.4` | `172.19.0.4` | 8200 |

Bu üç değer (compose `ipv4_address`, docker runtime IP, k8s Endpoints IP)
aynı satırda olmak ZORUNDA. Aralarında sapma tespit edilirse fix uygulanır.

**Detection (fail-loud, no auto-fix):** `host-compose/preflight-check.sh
<env>` script'inin 7. bölümü her host-bridge servisi 3 boyutta doğrular:
(a) container `platform-<env>-net`'e attach; (b) docker IPv4 == compose
pin; (c) k8s Endpoints IP == compose pin. Sapma varsa recovery komutu
konsola basılır. Auto-fix yok (Codex 019f37d9 adversarial review kararı:
silent auto-patch ikinci kontrol düzlemi yaratır).

**Recovery (single-service drift):**

```bash
# 1. Diagnostic — hangi katmanda sapma?
ssh halil@staging-sw
docker inspect platform-vault-prod --format '{{json .NetworkSettings.Networks}}' | jq .
kubectl --context k3d-prod -n platform-prod get endpoints vault -o yaml | grep ip

# 2A. Network detach ise re-attach (container mevcut, network yok):
# --ip <reserved> ZORUNLU: bu flag olmadan Docker DHCP dinamik bir IP verir
# ve bu bölümün çözdüğü drift sınıfını yeniden üretir (compose'daki
# ipv4_address sadece `docker compose up`/recreate akışında etkilidir).
docker network connect --ip 172.21.0.9 platform-prod-net platform-vault-prod
# Doğrula:
docker inspect platform-vault-prod --format '{{(index .NetworkSettings.Networks "platform-prod-net").IPAddress}}'
# → 172.21.0.9 beklenir

# 2B. IP drift ise container recreate (owner maintenance window!):
# Vault için unseal shard-holder'lar hazır olmalı (3-of-5 threshold).
cd /path/to/platform-k8s-gitops/host-compose/vault/prod
docker compose down
docker compose up -d
# Container static IP'ye pin'lenir. Ardından unseal:
docker exec -it platform-vault-prod vault operator unseal <key-1>
docker exec -it platform-vault-prod vault operator unseal <key-2>
docker exec -it platform-vault-prod vault operator unseal <key-3>

# 3. Preflight ile doğrula
bash host-compose/preflight-check.sh prod   # section 7 all PASS beklenir

# 4. ArgoCD sync (manual — HARD RULE D30 atomic cutover)
# platform-prod app manual sync policy'de. Overlay ↔ live hizalanmışsa
# sync no-op olacak. Değilse çakışmayı runbook ile çöz.
```

**Argo manual-sync notu:** `argocd/applications/platform-prod.yaml`
`automated:` block YOK → operator explicit sync tetikler. Bu drift'in
2d17h sürmesinin bir sebebi: manual patch (`kubectl patch endpoints`)
persist etti ama overlay stale kaldı; ekip re-sync tetiklemedi.
Yeni bir manual patch uygulandığında **aynı gün overlay güncellemesi PR
açılmalı** (governance debt önleme).

**Prometheus alert:** `ExternalSecretNotReady` (5m sürekli) → Teams
webhook. PrometheusRule + ServiceMonitor bu PR ile landed. Vault-kaynaklı
secret delivery başarısızlığı 5dk içinde alert üretir; pg/kc endpoint
drift'i için preflight + runbook birincil sinyal.

**Alert bootstrap-ordering (fresh cluster):** ESO alert yolunun kanıt
sayılması için iki apply yüzeyi birlikte devrede olmalı — (i) `base/eso`
altındaki `external-secrets-metrics` Service (metrics port 8080'i selector
ile controller Pod'una bağlar); (ii) `base/monitoring` altındaki
`ServiceMonitor` + `PrometheusRule` (scrape + alert kuralları). Fresh
cluster kurulumunda önce `kubectl apply -k kustomize/overlays/<env>/eso`
sonra `kubectl apply -k kustomize/base/monitoring` (veya prod'da ArgoCD
platform-system app'ini beklet). O ana kadar preflight (§5.1 detection)
tek başına ground-truth detector.

**Bağlantı:** platform-k8s-gitops#2268 (Faz 18 vault-ops). Original
incident evidence: Vault container `NetworkSettings.Networks: {}` +
`kubectl describe service vault` "no endpoints" + ESO status
`SecretSyncedError` 2d17h.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Vault operasyonları (rekey, unseal, root token yönetimi, bakım) bu runbook
  altında standartlaştırılmıştır.
- Başarılı operasyon için güncel shard envanteri, düzenli bakım ve sağlam
  monitoring gereklidir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SLO/SLA: docs/04-operations/SLO-SLA.md
- Monitoring: docs/04-operations/MONITORING/…
