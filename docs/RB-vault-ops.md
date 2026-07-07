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
3.2 HOST-COMPOSE UNSEAL — OPERATOR-SINGLE + @reboot AUTO-UNSEAL (test/prod)
-------------------------------------------------------------------------------

> Staging-sw host-compose vault'ları (`platform-vault-test`, `platform-vault-prod`).
> 3-of-5 seremonisi tek-operatör recovery'de tek adıma iner (shard'lar tek dosyada).

**Canonical init-file authority (2026-07-06 stale-swap incident sonrası):**

| Ortam | Canonical JSON | Shares/Threshold |
|---|---|---|
| test | `~/bootstrap-drill/vault-init-test.json` | 3 / 2 |
| prod | `~/bootstrap-drill/vault-init-prod.json` | 5 / 3 |

- **`~/platform/state/vault/*.json` = STALE/SWAPPED — KULLANMA.** Bunlar yanlış init
  epoch'undan; farklı dosyalardan shard karıştırmak
  `Error: failed to decrypt keys from storage: error decrypting seal wrapped value`
  üretir (progress ilerler ama threshold'da reconstruct edilen master key mevcut
  storage'ı açmaz). Aynı canonical dosyanın `[0]`+`[1]` çiftini kullan.

**Shape-guard (swap kazasına düşme — önce doğrula):**

```bash
ssh halil@staging-sw '
  jq "{shares:.unseal_shares,threshold:.unseal_threshold,keys:(.unseal_keys_b64|length)}" \
     /home/halil/bootstrap-drill/vault-init-test.json
  docker exec platform-vault-test vault status | grep -E "Total Shares|Threshold"
'   # dosya shape'i == vault shape olmalı
```

**Operator-single manuel unseal — key'i jq ile çek, POSITIONAL ARGV ver (chat'e düşürme):**

```bash
# TEST (2 shard)
ssh halil@staging-sw '
  set -e; JSON=/home/halil/bootstrap-drill/vault-init-test.json
  for i in 0 1; do
    KEY=$(jq -r ".unseal_keys_b64[$i]" "$JSON")
    docker exec platform-vault-test env VAULT_ADDR=http://127.0.0.1:8200 \
      vault operator unseal "$KEY" 2>&1 | grep -E "^Sealed|Unseal Progress"
    unset KEY
  done
'
# PROD (3 shard) — JSON=.../vault-init-prod.json, for i in 0 1 2, container platform-vault-prod
```

**İki tuzak (bu session'da kanıtlandı — tekrarlama):**

1. **stdin `unseal -` ÇALIŞMAZ.** `docker exec -i ... vault operator unseal -` →
   `400 must be a valid hex or base64 string`. Positional argv (`unseal "$KEY"`) kullan.
2. **Unseal key = 44-char base64, padding YOK** (33 byte = 1 versiyon + 32 share; 33 mod 3 = 0
   → trailing `=` yok). Scan regex'i `{43}=` gerektirirse **gerçek key'leri kaçırır**;
   doğru regex `[A-Za-z0-9+/]{44}` (padding'siz).

**@reboot AUTO-UNSEAL durability (Faz 22.6, 2026-07-07):**

- Script: `/home/halil/platform/scripts/vault-test-auto-unseal.sh` (deterministic —
  canonical dosyadan jq+argv; shape-guard; already-unsealed → no-op exit 0; last-resort
  scan fallback doğru argv+padding'siz regex ile).
- Cron (user halil): `@reboot sleep 45 && /home/halil/platform/scripts/vault-test-auto-unseal.sh >> /home/halil/platform/state/vault-test-unseal.log 2>&1`
- **Legacy `vault-auto-unseal.sh` (VAULT_CONTAINER=platform-vault-1 default) DISABLED** —
  yanlış container hedefliyordu. Eski scan+stdin test scripti de fragile'dı (regex `=`
  gerektiriyordu + stdin 400 → hiç fire etmemişti); deterministic sürümle değişti.
- **PROD @reboot unseal line DISABLED** — prod vault volume-perm crashloop'unda (§5.2);
  önce volume fix, sonra prod auto-unseal aktive edilir.

**ANTI-PATTERN — LIVE vault'u test için re-seal ETME.** 2026-07-06'da auto-unseal'i
doğrulamak için canlı test vault re-seal edildi; scan-based unseal açamadı → platform
degrade (Meetings pasif) + ESO SecretSyncedError. Reboot-path yalnız gerçek reboot'ta
(cron log'u) veya disposable vault'ta test edilir; canlı seal state'e dokunulmaz.

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
docker network connect platform-prod-net platform-vault-prod
# Docker DHCP yeni IP atar — compose ipv4_address ile pin'li olduğu için
# static IP alınır. Doğrula:
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

**Bağlantı:** platform-k8s-gitops#2268 (Faz 18 vault-ops). Original
incident evidence: Vault container `NetworkSettings.Networks: {}` +
`kubectl describe service vault` "no endpoints" + ESO status
`SecretSyncedError` 2d17h.

-------------------------------------------------------------------------------
5.2 PROD-VAULT VOLUME-PERMISSION CRASHLOOP (2026-07-07, fiziksel taşıma sonrası)
-------------------------------------------------------------------------------

**Semptom:** `platform-vault-prod` container `restartcount` sürekli artıyor
(exitcode=1, ~7s'de bir restart). `docker inspect -f '{{.State.Status}}'` →
`restarting`. Log:

```
chown: /vault/config: Read-only file system                 # (benign — config RO mount)
Error initializing storage of type raft: failed to create fsm:
  failed to open bolt file: open /vault/data/vault.db: permission denied   # FATAL
```

**Kök neden:** prod vault `/vault/data` bir docker NAMED VOLUME
(`platform_vault-data`, eski compose project prefix `platform_`) —
`/var/lib/docker/volumes/platform_vault-data/_data`. Bu volume'un `_data` dizini
vault process uid'sinin (`100`) sahipliğinde DEĞİL → bolt dosyası açılamıyor.
Karşılaştırma (çalışan test vault): host bind-mount
`/home/halil/platform-stateful/test/vault/data`, `raft/` + `vault.db` sahibi
`100:1000` (doğru). Fiziksel taşıma/reboot sonrası named-volume ownership drift'i.

**Fix (OWNER-GATED — prod credential-plane, HARD RULE):**

```bash
ssh halil@staging-sw
# 1. Volume _data ownership'i vault uid'sine hizala (test vault ile aynı: 100:1000)
sudo chown -R 100:1000 /var/lib/docker/volumes/platform_vault-data/_data
# 2. Restart + crashloop bitti mi (Sealed=true + Running beklenir, artık restarting değil)
docker restart platform-vault-prod
sleep 5; docker inspect -f '{{.State.Status}} rc={{.RestartCount}}' platform-vault-prod
docker exec platform-vault-prod env VAULT_ADDR=http://127.0.0.1:8200 vault status | grep Sealed
# 3. Unseal — §3.2 operator-single (PROD: bootstrap-drill/vault-init-prod.json, 3 shard)
# 4. §3.2 prod @reboot auto-unseal line'ını aktive et
```

**Kalıcı çözüm (kök neden — HARD RULE uzun-vadeli):** test vault bind-mount,
prod vault named-volume — bu **model tutarsızlığı** normalize edilmeli. Prod'u da
host bind-mount'a (`/home/halil/platform-stateful/prod/vault/data`, ownership `100:1000`)
geçir; ADR-0002 stateful tier ile hizala; `host-compose/vault/prod/docker-compose.yml`
volume tanımını bind-mount'a çevir. Aksi halde her volume-ownership drift'inde
crashloop tekrar eder.

**Açık soru (owner):** prod vault D30-öncesi (pre-cutover) çalışmalı mı, yoksa
`restart=unless-stopped` bir zombie'yi mi ayakta tutuyor? Config path gitops
`host-compose/vault/prod/config`'e bağlı → intended görünüyor. Karar owner'a ait
(prod credential-plane mutasyonu owner onayı şart).

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
