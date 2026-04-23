# Current State — Platform K8s Migration

> **Status as of**: 2026-04-24 ~01:25 UTC+3 (Session 28 T0 — **FAZ 13 HYBRID GO CANLI KANITLI**: Codex verdict PARTIAL+GO (thread `019dbc86`). Kontrat ADR-0002 Faz D6 (stateful PG+KC+Vault K8s-dışı, host-compose'da) ile uyumlu: "Full cutover" (K8s KC deploy + compose decommission) ADR aykırı → reddedildi. **Atomic cutover anlamı kalibre edildi**: `ai.acik.com` authoritative prod yolu K8s workload'a bağlı (byte-perfect canlı kanıt: public=127.0.0.1:30443 NodePort 200 15666B eşleşme) + stateful tier compose'da kalıcı + **72h rollback-window başladı T0=2026-04-24 01:25 UTC+3**. Session 28 açılış 5-komut refresh 5/5 Session 27 canonical eşleşme, T0 minimum teyit 3/3 PASS. Kalan paralel cleanup (non-blocking): ArgoCD cosmetic OutOfSync (RespectIgnoreDifferences syncOption), drill quarterly cron, prod non-superAdmin scoped allow seed.
> **Verified by**: Codex + live `ssh staging-sw`
> **Source set**: Live `kubectl`, `curl`, `docker`, `ssh staging-sw` outputs + repo HEAD
> **Supersedes**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` bölümlerindeki `%99.5`, `DONE + LIVE (Faz H)`, `soft cutover` ifadeleri
> **Interpretation gate**: Önce [../../AGENTS.md](../../AGENTS.md), ardından [../context-priority-rules.md](../context-priority-rules.md) okunur; bu dosya canlı truth snapshot'tır, repo-geneli kural sözleşmesi değildir.

---

## Live Delta — Session 28 (2026-04-24 ~01:25 UTC+3) — FAZ 13 HYBRID GO CANLI + 72h ROLLBACK-WINDOW AÇILDI

### Codex Verdict (thread `019dbc86`)

**VERDICT: PARTIAL + Faz 13 kararı GO/Hybrid**. Ana yorum (Codex'ten):

> "Atomic switch anlamı: `/realms/` K8s'e taşımak değil; mevcut hybrid'in authoritative prod contract olarak kabul edilmesi ve rollback-window'a girilmesi. `ADR-0002` ve `PLAN.md` D6: PG + Keycloak + Vault prod/test ayrık olacak ama Kubernetes dışında, host/compose üzerinde kalacak. Full cutover = K8s KC deploy + compose KC decommission bu repo'nun aktif kontratına uymuyor — yeni mimari/faz olur."

Sonuç: Session 28 = rollback-window başlangıcı + **hybrid kontrat canonical truth**.

### T0 Minimum Teyit (3/3 PASS, 01:25 UTC+3)

```
1. ai.acik.com/api/v1/theme-registry → 200 15666B
2. https://127.0.0.1:30443 Host=ai.acik.com → 200 15666B  (byte-perfect K8s NodePort match)
3. https://ai.acik.com/realms/serban/.well-known/openid-configuration → issuer "https://ai.acik.com/realms/serban" (compose KC)
```

### Session 28 Açılış 5-Komut Refresh (5/5 Session 27 canonical eşleşme)

```
1. CSS vault-platform-gitops:      Ready=True reason=Valid
2. 8 ExternalSecret READY:         TÜM 8x True/SecretSynced
3. openfga-migrate Job:            SuccessCriteriaMet, completions=1
4. ArgoCD Applications:            platform-prod + eso-prod OutOfSync/Healthy rev 82c6abd (cosmetic v1beta1 stored)
5. DR drill log:                   KC imported 30s + 2x SMOKE PASS + RTO 132s + DRILL PASS
6. KC health:                      healthy (dual-network, PR #57 sonrası)
```

### T0 Kaynak Tasarrufu (Codex önerisi)

- **Test cluster scale-to-zero**: 9 deployment (api-gateway + 8 backend + frontend) → 0/0 replicas
  - Rollback-window 72h boyunca test trafiği yok; kaynak prod'a
  - Gerekirse `kubectl -n platform-test scale deploy --all --replicas=1` ile hızlı aç

### Faz 13 Kapsamı — Kalibre Edilmiş Kontrat

**Önceki yorum (reddedildi)**: "nginx upstream switch + /realms/ K8s'e taşıma + compose KC decommission"

**Doğru kontrat (Codex + ADR-0002 D6)**:
- `ai.acik.com/api/*` → K8s workload (zaten byte-perfect aktif)
- `ai.acik.com/realms/*` + `/resources/*` → compose `platform-kc-prod` (kalıcı, ADR D6 stateful izolasyonu)
- `ai.acik.com/api/auth/*` rotası: compose `platform-auth-service-1` (Spring Boot, compose KC'ye bağlı)
- PG + Vault + KC: compose host-compose stack (bind-mount /home/halil/platform-stateful/)
- K8s cluster prod workload layer (frontend + 8 backend + openfga)

**"Atomic cutover"** = bu hybrid kontratın authoritative prod olarak kabul edilmesi, ilave switch yok.

### 72h Rollback-Window Plan + Canlı Gate Sonuçları

- **T0**: 2026-04-24 01:25 UTC+3 ✅ (yukarı kanıtlanan T0 minimum teyit)
- **T+15**: **02:13 UTC+3 PASS** ✅ (Fiili 48 dk geç — ScheduleWakeup + paralel cleanup):
  - Anonymous: theme-registry=200, authz/me=401, variants=401
  - KC OIDC discovery=200 (compose KC)
  - K8s: 19 pod Running + 1 Completed (openfga-migrate Job)
  - ArgoCD: 4/4 Application Healthy
  - Compose: KC + PG + Vault healthy
  - Son 5 dk error log: temiz (fatal/5xx yok)
  - Rollback trigger eşiği altında → devam
- **T+60**: 02:25 UTC+3 — auth chain + scoped deny + error rate (ScheduleWakeup 720s planlandı 23:26 UTC)
- **T+24h**: 2026-04-25 01:25 UTC+3 — 24h soak gate (error rate < %0.1)
- **T+72h**: 2026-04-27 01:25 UTC+3 — rollback-window kapanış, hybrid prod permanent

### Paralel Cleanup Post-T0 (rollback-window içinde)

- **PR #72** RespectIgnoreDifferences syncOption — MERGED (runtime etki: kısmi, cosmetic kalıtım)
- **PR #73** `/metadata` agresif ignoreDifferences — MERGED (kısmi, 7 ES hâlâ spec-level diff)
- **PR #76** jqPathExpressions ESO v1 default fields — MERGED ✅ **TAM FIX** (ArgoCD 4/4 Synced/Healthy revision `52af34a`, cosmetic OutOfSync tamamen kapandı, prod-workload-gitops 75→88)
- **PR #74** `bootstrap/dr-drill-cron.sh` + Prometheus textfile metric — MERGED (3 ayda bir full drill otomasyon, PLAN.md D23 kontrat)
- ArgoCD Apps **OutOfSync/Healthy** cosmetic kalıcı — runtime blocker değil, rollback-window 72h boyunca soak

**Rollback trigger conditions** (her gate'te):
- 5xx error rate > %1 persistent
- KC OIDC discovery fail > 3 iter
- ESO sync fail > 10 dk (eski durumdan rollback)
- prod workload pod crash loop (2+ pod 10 dk)

**Rollback playbook** (runbook §8):
1. nginx config backup → `/home/halil/platform/web/nginx/default.conf.bak.2026-04-24`
2. /api/ upstream `127.0.0.1:30443` → `127.0.0.1:8082` (compose gateway) restore
3. Test: anonymous 200 + token smoke
4. Aktif: 5 dk restore

### Paralel Cleanup (rollback-window içinde, non-blocking)

1. **RespectIgnoreDifferences syncOption** — ArgoCD cosmetic OutOfSync susturma (PR pending)
2. **Drill quarterly cron** — PLAN.md D23 (PR pending)
3. **Prod non-superAdmin scoped allow seed** — variants(1204)=200 seed (PR pending)
4. **KC K8s migration (ileride)**: ayrı yeni faz, şu an scope dışı

### 5-Sayaç Session 28 (T0 post-refresh, honest)

- `test-k8s`: 86 → **84** (scale-to-zero rollback-window boyunca; rollback gerekirse 1 replica bring-up)
- `prod-stateful-split`: 76 (değişim yok, KC healthy + PG+Vault stabil)
- `prod-workload-gitops`: 75 (değişim yok, OutOfSync cosmetic kaldı)
- `secret-delivery`: 87 (değişim yok, CSS Ready + 8 ES Sync)
- `dr-validation`: 85 (değişim yok, full drill PASS kanıtı geçerli)

### Weighted operational continuity: **~%89** (Session 27 %85 + Faz 13 Hybrid GO +1 + T+15 PASS +1 + PR #76 ArgoCD Synced gate +2; T+72h kapanış +1 daha bekleniyor %90)

### Faz 13 Execute Durumu — KABUL EDİLDİ

✅ Prereq CANLI TEYİT + Codex verdict + T0 minimum teyit PASS → **Faz 13 Hybrid GO aktif**.

## Live Delta — Session 27 (2026-04-24 ~01:22 UTC+3) — FULL DR DRILL PASS CANLI

### Zafer: Gerçek Full DR Drill (iter-11, 11 bug fix sonrası)

Drill log (`/tmp/dr-drill-20260424-011903.log`) kanıtı:
```
[dr-drill OK] 01:19:08 PG: restored + keycloak_user/DB unified (2s)
[dr-drill OK] 01:19:24 VAULT: restored (4s)   (init+unseal 12s + restore 4s = 16s)
[dr-drill OK] 01:19:44 KC: up
[dr-drill OK] 01:20:14 KC: imported (30s)                              ← Session 27'de İLK KEZ!
[dr-drill OK] 01:20:15 SMOKE[1] PG: DB listesi görünüyor
[dr-drill OK] 01:20:15 SMOKE[1] Vault: Initialized=true (Sealed=true)
[dr-drill OK] 01:20:15 SMOKE[1] KC: OIDC discovery 200                 ← Session 27'de İLK KEZ!
[dr-drill OK] 01:20:15 SMOKE[1]: PASS
[dr-drill]    01:20:15 SMOKE: 60s sleep before independent re-run
[dr-drill OK] 01:21:15 SMOKE[2] KC: OIDC discovery 200
[dr-drill OK] 01:21:15 SMOKE[2]: PASS
[dr-drill OK] 01:21:15 RTO: PASS (132s / 14400s budget)
[dr-drill OK] === DR DRILL PASS === (exit 0)
```

### Bug Tree: 11 İterasyon Canlı Kanıtlı Sıralı Fix

| Iter | Timestamp | Bug | Fix PR | Kanıt |
|---:|---|---|---|---|
| 1 | 00:19:43 | Safety glob `platform-stateful*` false match | #58 | Default DRILL_ROOT abort |
| 2 | 00:20:01 | `((i++))` set -e infaz (i=0 exit 1) | #58 | PG ready-check öncesi exit |
| 3 | 00:20:02 | `docker run >/dev/null` stderr gizleme | #58 | Manuel stderr: network not found |
| 4 | 00:22:30 | Vault container UID 100 `/vault/data` permission | #59 | Manuel log: bolt file permission denied |
| 5 | 00:26:00 | Vault smoke sealed post-restore FAIL | #60 | SMOKE[1] Vault: status FAIL exit 2 |
| 6 | 00:53:48 | KC container crash (hipotez PG şifre) | #65 (yanlış user) | `container not running` post `KC: up` |
| 7 | 01:06:00 | SIGPIPE bg shell (exit 141) | Ortam fix (setsid+disown) | SELECT sonrası hemen teardown |
| 8 | 01:07:59 | `ALTER ROLE keycloak` user yok | #66 keycloak_user | "kullanıcı yoksa normal" |
| 9 | 01:12:18 | KC Liquibase checksum mismatch 25↔26.5 | #67 | Container logs `jpa-changelog-2.5.0.xml` hash fark |
| 10 | 01:15:46 | `restore_kc t1` unbound variable (set -u) | #68 | Line 368 unbound variable crash |
| **11** | **01:19:03** | **Tüm fix'ler birleşik — GERÇEK FULL PASS** | — | KC imported 30s + 2x KC OIDC 200 + RTO 132s + exit 0 |

### Session 26 Kazanımları (bu Session 27'ye önkoşul)

1. **ESO secret-delivery recovered** (Session 25 stale → Session 26 canlı fix):
   - ArgoCD platform-eso-prod manual sync → roleId UUID canlıya
   - CSS `Ready=True/Valid "store validated"` ✅
   - 8/8 ES `SecretSynced=True` ✅
   - AppRole login 400 error kapandı
2. **openfga-migrate Job Complete** (platform-prod Degraded kaynağı kapandı):
   - Delete + ArgoCD sync → new Job `Complete 1/1 5s`
   - Pod logs: `migration done current version: 6`
   - platform-prod: `OutOfSync/Degraded` → `OutOfSync/**Healthy**` ✅
3. **KC export cron full upgrade** (PR #62/63):
   - `kcadm.sh get realms/<realm>` (PARTIAL) → `partial-export` POST + users API + jq merge
   - Canlı: realm=serban, users=11, clients=11, roles=5

### 5-Sayaç Session 27 (CANLI TEYİT, honest)

- `test-k8s`: 86 (değişim yok)
- `prod-stateful-split`: 76 (KC healthy, S25 doğruydu)
- `prod-workload-gitops`: 72 → **75** (ESO canlı parite + openfga Complete + platform-prod Healthy; ArgoCD cosmetic OutOfSync kaldı)
- `secret-delivery`: **87 CANLI** (S26 honest, S27'de değişim yok)
- `dr-validation`: 75 → **85** (gerçek full KC import drill PASS, 2x KC OIDC smoke, RTO 132s)

### Weighted operational continuity: **~%88** (Session 26 sonrası +5 net: full KC drill +10, platform-prod Healthy +2, ESO hâlâ kozmetik OutOfSync -7 cap)

### Faz 13 Atomic Cutover Prereq Check — CANLI KANITLI

| Gate | Hedef | Canlı | Durum |
|---|---|---|---|
| `secret-delivery` | ≥80 | 87 | ✅ CANLI (CSS Ready + 8 ES Sync) |
| `dr-validation` | ≥85 | 85 | ✅ CANLI (full drill + KC OIDC smoke) |

**Faz 13 GO — atomic cutover için sözleşme koşulları CANLI KANITLI.**

### Kalan Cleanup (Faz 13 öncesi opsiyonel, non-blocking)

1. ArgoCD platform-prod + platform-eso-prod OutOfSync cosmetic (v1beta1 stored serialization + ConfigMap health=null aggregation) — Faz 13 cluster rebuild ile doğal temizlenir
2. Drill quarterly cron scheduling (PLAN.md D23)
3. Prod non-superAdmin scoped allow seed kontratı (variants 1204=200)
4. ArgoCD stuck OutOfSync cosmetic diff için `RespectIgnoreDifferences=true` syncOption

### Session 25 Stale Öğrenilen Dersi (Session 26'dan korunuyor)

- **PR merged ≠ ArgoCD synced ≠ canlı apply** (D30 HARD RULE manual sync)
- Her iddia canlı log + `kubectl get` + smoke **tek-tek** doğrulanmadan rapora girmez
- Bug fix cycle: iterative, adversarial feedback olmadan stale kalma riski yüksek
- "Drill PASS banner" script-level sinyal; her subsystem kanıtı ayrıca doğrulanmalı (PG/Vault/KC OIDC 200)

## Live Delta — Session 26 (2026-04-24 ~01:00 UTC+3) — HONEST CORRECTION

### Session 25 Stale İddia Düzeltmesi (Mea Culpa)

Session 25 delta'sında **"Prod ESO roleId HIGH CLOSED"** + **"secret-delivery=87"** iddiası ile rapor verildi. Kullanıcı canlı kontrol yaptı, stale çıktı:

| İddia (S25) | Kanıt (kullanıcı feedback, S26 check öncesi) |
|---|---|
| ESO roleId real UUID canlıda | ❌ Canlı CSS hâlâ `roleId=eso-runtime` placeholder |
| CSS Ready=True | ❌ `Ready=False InvalidProviderConfig` |
| 8 ES SecretSynced=True | ❌ 8/8 `SecretSyncedError` |
| AppRole login çalışıyor | ❌ ESO log: `Code: 400 invalid role or secret ID` |

**Kök neden**: PR #57 manifest'e yazdı (merged), **ArgoCD platform-eso-prod Application sync tetiklenmemişti**. Merged ≠ sync ≠ canlı apply. Ben "manifest-canlı parite" iddiasını yalnız manifest check ile varsayımsal çıkardım. Doğru: her PR merge sonrası **ArgoCD manual sync + CSS/ES durum canlı doğrulama** yapılmalı.

### Session 26 Canlı Düzeltme (2026-04-24 00:50-00:55 UTC+3)

1. **ArgoCD `platform-eso-prod` manual sync** (hard refresh + force apply):
   ```bash
   kubectl -n argocd annotate application platform-eso-prod argocd.argoproj.io/refresh=hard --overwrite
   kubectl -n argocd patch application platform-eso-prod --type merge \
     -p '{"operation":{"sync":{"syncStrategy":{"apply":{"force":true}},"revision":"HEAD"}}}'
   ```
2. **30s bekle → CSS canlı check**:
   ```
   $ kubectl get clustersecretstore vault-platform-gitops -o jsonpath='{.spec.provider.vault.auth.appRole.roleId}'
   0db7ba83-b485-4afb-da7d-e1041b1f8a56   ← manifest UUID canlıya geçti
   $ kubectl get clustersecretstore ... -o jsonpath='{.status.conditions[0].type}={.status.conditions[0].status} reason={.status.conditions[0].reason}'
   Ready=True reason=Valid  ← AppRole login başarılı
   ```
3. **8 ES force-sync** (annotation-based reconcile):
   ```bash
   for es in auth-service-secrets core-data-service-secrets permission-service-secrets \
            report-service-secrets schema-service-secrets user-service-secrets \
            variant-service-secrets ghcr-pull; do
     kubectl -n platform-prod annotate externalsecret $es force-sync=$(date +%s) --overwrite
   done
   ```
4. **8/8 ES SecretSynced=True kanıtı**:
   ```
   $ kubectl -n platform-prod get externalsecret -o custom-columns=NAME:.metadata.name,READY:.status.conditions[0].status
   NAME                         READY
   auth-service-secrets         True
   core-data-service-secrets    True
   ghcr-pull                    True
   permission-service-secrets   True
   report-service-secrets       True
   schema-service-secrets       True
   user-service-secrets         True
   variant-service-secrets      True
   ```

### PR #62 + #63 KC Export Cron Full Upgrade — CANLI TEYİT

- **PR #62** `fix(faz-12)` (MERGED): partial-export + users + jq merge.
- **PR #63** `fix(faz-12)` (MERGED): `kcadm.sh get` → `create -o -s dummy=1` (POST endpoint fix).

Canlı KC export kanıtı (staging-sw, PR #63 sonrası):
```
$ bash bootstrap/kc-export-cron.sh
[kc-export] OK prod:serban size=16K clients=11 users=11

$ zcat ~/platform/backup/keycloak/prod/serban-20260424.json.gz | jq '{realm,users:(.users|length),clients:(.clients|length),roles_realm:(.roles.realm|length)}'
{"realm":"serban","users":11,"clients":11,"roles_realm":5}
```

### DR Drill iter-6 (SKIP_KC=0) — PARTIAL (KC import FAIL, PG+Vault PASS)

Drill log kanıtı (`/tmp/dr-drill-20260424-005249.log`):

```
[dr-drill OK] 00:52:54 PG: restored (2s)
[dr-drill OK] 00:53:07 VAULT: init + unseal done
[dr-drill OK] 00:53:10 VAULT: restored (3s)
[dr-drill]    00:53:10 KC: start drill keycloak on port 18080
quay.io/keycloak/keycloak:25.0 pull... OK
[dr-drill OK] 00:53:48 KC: up                                  ← container başlatıldı
[dr-drill]    00:53:48 KC: import realm from serban-20260424.json.gz
Error response from daemon: container ee838c5c... is not running
[dr-drill]    00:53:48 KC: import best-effort failed — drill MARK=PARTIAL, PG+Vault still valid
[dr-drill OK] 00:53:48 SMOKE[1] PG: DB listesi görünüyor        (PG PASS)
[dr-drill OK] 00:53:48 SMOKE[1] Vault: Initialized=true         (Vault PASS)
                                                               (KC smoke atlandı — SKIP_KC=1 fallback)
[dr-drill OK] 00:53:48 SMOKE[1]: PASS                           ← PG+Vault için PASS
[dr-drill OK] 00:54:49 SMOKE[2]: PASS                           ← aynı
[dr-drill OK] 00:54:49 RTO: PASS (120s / 14400s budget)
[dr-drill OK] === DR DRILL PASS ===                             ← ancak KC import unresolved
```

**Doğru okuma**: "DR DRILL PASS" banner'ı script'in **PG+Vault smoke PASS + KC best-effort partial fallback** davranışını yansıtıyor. KC restore zinciri kanıtlanmadı.

### KC Drill Import Fail — Kök Neden Hipotezi (unresolved)

KC container `ee838c5c...` `KC: up` yazıldıktan hemen sonra exit olmuş (sleep 20 sonrası).
Muhtemel kök neden: PG restore edilmiş prod `keycloak` user prod password'u taşır (dump bu bilgiyi korur); drill KC container `KC_DB_PASSWORD=drill-only-postgres` ile bağlanmaya çalışır → JDBC auth fail → KC container crash.

**Fix önerisi (PR #65)**:
```bash
# restore_pg sonrası:
docker exec drill-pg psql -U postgres -c \
  "ALTER ROLE keycloak WITH PASSWORD 'drill-only-postgres';"
```

Bu drill scope'unda KC user password'u unify eder; canlı PG/KC password pariteleri etkilenmez (drill sandbox).

### PR #62 + #63 KC Export Cron Full Upgrade (doğru, canlı teyit)

### 5-Sayaç Session 26 (CANLIDA TEYİTLENMİŞ, honest)

- `test-k8s`: 86 (değişim yok — hâlâ Session 23 baseline)
- `prod-stateful-split`: 76 (KC healthy, Session 25 bilgi doğruydu)
- `prod-workload-gitops`: 72 → **73** (ESO canlı parite ✅; `openfga-migrate` Job Degraded platform-prod Application Degraded kaynağı, ESO kaynaklı değil — yeni tespit, ayrı fix)
- `secret-delivery`: **87 CANLI TEYİT** (CSS Ready + 8 ES Sync + roleId UUID canlı + AppRole login; Session 25 "87" iddia stale idi ama Session 26 canlı düzeltme ile iddia = gerçek)
- `dr-validation`: 70 → **75** (PG+Vault drill PASS + KC export full + KC import unresolved; "85" iddia için PR #65 KC drill password-unify fix + rerun lazım)

### Weighted operational continuity: **~%83** (Session 25 iddia %86 ve Session 26 ilk iddia %89 ikisi de stale; dürüst canlı durum %83: ESO recovered + KC compose healthy + PG/Vault drill PASS; KC restore drill unresolved + openfga-migrate Degraded + ArgoCD cosmetic sync kaldı)

### Faz 13 Atomic Cutover Prereq Check — CANLI

| Gate | Hedef | Canlı | Durum |
|---|---|---|---|
| `secret-delivery` | ≥80 | 87 | ✅ CANLI |
| `dr-validation` | ≥85 | 75 | ⚠️ (KC drill unresolved) |

**Faz 13 karar**:
- **Opsiyon A**: PR #65 KC drill password-unify fix + rerun → dr-validation=85 → tam cutover
- **Opsiyon B**: Hybrid kabul (secret-delivery OK + KC compose healthy + PG/Vault drill PASS + compose 72h warm rollback)
- **Opsiyon C**: `openfga-migrate` Job fix + PR #65 + hybrid kabul

Kalan blockers:
- KC drill import container crash (PR #65 candidate)
- `openfga-migrate` Job `BackoffLimitExceeded` platform-prod Degraded kaynak (ayrı fix)
- ArgoCD platform-prod OutOfSync cosmetic (Faz 13 rebuild ile doğal temizlenir)

### Süreç Öğrenilen Dersi

- **PR merge ≠ canlı apply**. ArgoCD manual sync modunda (D30 HARD RULE atomic cutover) her PR merge sonrası sync tetiklemesi + canlı durum check zorunlu.
- Kullanıcının adversarial feedback'i olmasa Session 26 düzeltmesi yapılmazdı, Faz 13'e hatalı state ile geçilirdi.
- Process fix: "PR merged" milestone'u "manifest merged + ArgoCD synced + canlı durum teyit edildi" olarak tanımla.

## Live Delta — Session 25 (2026-04-24 ~00:35 UTC+3) — STALE/ABARTILI (S26'da düzeltildi)

- **5 yeni PR merge** (iterative drill hardening + KC/ESO cherry-pick):
  - `a4e902c` **PR #57** `fix(prod)`: KC dual-network (`platform-prod-net` + `platform_microservice-network`) + healthcheck `localhost→127.0.0.1` + printf portability. Cherry-pick Codex PR #48'in değerli iki deltasından biri; 172.21.0.6 IP regression kaçınıldı (FQDN `vault.platform-prod.svc.cluster.local:8200` korundu). **ESO roleId** placeholder `"eso-runtime"` → gerçek AppRole UUID `0db7ba83-b485-4afb-da7d-e1041b1f8a56`.
  - `27ebffa` **PR #58** `fix(faz-12)`: DR drill script 3 kritik bug fix: safety glob false positive (`platform-stateful*` → `platform-stateful-drill` yanlış match) + `((i++))` set -e infaz bug (eski değer 0 exit 1) + docker run stderr gizleme (`>/dev/null` → `>>DRILL_LOG 2>&1`).
  - `2d067fc` **PR #59** `fix(faz-12)`: DR drill sandbox `chmod 0777` (Vault container UID 100 `/vault/data/vault.db: permission denied` fix).
  - `22c3df9` **PR #60** `fix(faz-12)`: DR drill Vault smoke sealed post-restore accept (exit code 2 = sealed NORMAL, snapshot restore kanıtı `Initialized=true`).
  - PR #48 (Codex DRAFT, CONFLICTING 14 dosya) **closed** supersede-via-cherry-pick; 569 deletion'ı main'deki PR #51/#52/#54/#55 işlerini silecekti.

- **Canlı KC drift kapatma**:
  - `docker compose up -d --force-recreate keycloak` staging-sw host-compose
  - `docker inspect platform-kc-prod --format '{{.State.Status}} {{.State.Health.Status}}'` → `running healthy`
  - Healthcheck log son 3 iter: `[0] [0] [0]` (hepsi başarılı)
  - `/health/ready → HTTP/1.1 200 OK` direct test
  - Known Drift §"platform-kc-prod healthcheck unhealthy" → **CLOSED**

- **Canlı DR drill PASS** (staging-sw, 2026-04-24 00:31:11 → 00:32:33):
  - Komut: `DRILL_ROOT=/home/halil/drill-sandbox DRILL_CONFIRM=yes SKIP_KC=1 bash bootstrap/dr-drill.sh`
  - Aşamalar:
    - SAFETY ✅ + PREFLIGHT ✅ (disk 182GB)
    - PG up 2s + restore 2s (128KB dump `pg_dumpall_20260424-0005.sql.gz`)
    - Vault init+unseal 9s + snapshot restore 4s (88KB `vault-snapshot-20260423-0200.snap`)
    - SMOKE[1] PASS (PG DB listesi + Vault Initialized=true, Sealed=true)
    - 60s independence sleep
    - SMOKE[2] PASS (tekrar doğrulama)
    - **RTO: 81 saniye / 14400s budget (0.56%) ✅**
  - Sonuç: `=== DR DRILL PASS ===` exit 0, teardown clean
  - KC drill SKIP_KC=1 çünkü `kc-export-cron.sh` hâlâ `kcadm.sh get realms/<realm>` (PARTIAL export, users/creds yok) → `dr-validation=70` PARTIAL, full=85 için KC export cron upgrade ayrı iş

- **Faz 11 ESO roleId uyumu** (ArgoCD sync beklentisi):
  - Manifest `kustomize/overlays/prod/eso/clustersecretstore-patch.yaml`: roleId gerçek UUID
  - Canlı CSS zaten aynı UUID ile çalışıyordu (placeholder sadece GitOps drift)
  - Known Drift §"Prod ESO roleId HIGH" → **CLOSED**

- **5-sayaç Session 25 delta**:
  - `test-k8s`: 86 (değişim yok)
  - `prod-stateful-split`: 73 → **76** (KC healthy + ESO roleId manifest-canlı parite)
  - `prod-workload-gitops`: 72 → **75** (ESO roleId paritesi, ArgoCD sync cosmetic diff azalır)
  - `secret-delivery`: 82 → **87** (roleId real UUID manifest + live CSS Ready=True, ghcr-pull zinciri canlı, PR #57 bekleyen uzak detay kapattı)
  - `dr-validation`: 5 → **70** (PARTIAL drill PASS, RTO 81s 4h budget'ın binde 5'i; KC full drill için cron export upgrade gerekir)
- **Weighted operational continuity**: `~%80` → **`~%86`** (Faz 10 T2 kapandı, Faz 11 KC healthy + ESO uyum, Faz 12 drill PASS)

### Faz 12 Follow-up (out-of-scope this session)

1. `bootstrap/kc-export-cron.sh` full `kc.sh export --users realm_file` geçişi → `dr-validation` 70 → 85 (KC dahil full drill)
2. Drill cron scheduling (PLAN.md D23 quarterly) → drill otomasyonu
3. Drill success metric → Prometheus node_exporter textfile (`dr_drill_last_pass_timestamp_seconds`) → alerting

### Faz 13 Atomic Cutover Prereq Check

Gate şartları (`docs/state/current-state.md` §5):
- `secret-delivery>=80` → **87 ✅**
- `dr-validation>=85` → **70 ⚠️** (KC full drill eklenirse 85 hedefi)
- Alternatif: mevcut hybrid cutover kontrat olarak kabul (ai.acik.com/api/ K8s, /realms/+/resources/ compose KC) + 72h warm rollback (compose prod hâlâ ayakta, PR #57 healthy)

## Live Delta — Session 24 (2026-04-24 ~00:00 UTC+3)

- **4 PR merge 5 dk içinde** (Claude execution → kullanıcı approval):
  - `17191e8` **PR #52** `fix(eso)`: 10 manifest `external-secrets.io/v1beta1 → v1` (supersedes PR #44). ArgoCD ComparisonError (`unable to resolve parseableType for GroupVersionKind`) **kapandı** — Apps artık diff hesaplayabiliyor.
  - `bf637f1` **PR #51** `docs(state)`: Codex Session 20-23 truth refresh (prod-workload-gitops 0→63, secret-delivery 58→78).
  - `64f9aa4` **PR #54** `fix(argocd)`: `argocd/applications/platform-prod.yaml` + `platform-eso-prod.yaml` `ignoreDifferences` genişletildi (ExternalSecret + CSS `/metadata/{annotations,managedFields}/status`, Endpoints `/subsets`, ConfigMap openfga-config `/data/OPENFGA_DATASTORE_URI`).
  - `ccf84a5` **PR #55** `feat(faz-12)`: `bootstrap/dr-drill.sh` (447 LOC, shellcheck warning-free). Sandbox-isolated, 6 safety assertion, port offset +10000, drill-* container prefix, 2x smoke + RTO measure.
- **PR #53 OPEN**: Faz 10 T2 handoff split (1290 satır → 10 session-logs + 55 satır index). CI pass.
- **Faz 11 runtime kapalı — canlı kanıt**:
  - `ssh staging-sw 'docker exec k3d-prod-server-0 kubectl -n platform-prod get clustersecretstore vault-platform-gitops -o jsonpath="{.status.conditions[0].type} {.status.conditions[0].status}"'` → `Ready True`
  - `kubectl -n platform-prod get externalsecret -o wide` → 8 ES `SecretSynced=True` (auth, core-data, ghcr-pull, permission, report, schema, user, variant)
  - `kubectl -n platform-prod get pods | grep Running | wc -l` → `19`
  - `curl -sk -o /dev/null -w '%{http_code} %{size_download}B\n' https://ai.acik.com/api/v1/theme-registry` → `200 15666B`
  - `curl -sk -H 'Host: ai.acik.com' https://127.0.0.1:30443/api/v1/theme-registry` → byte-perfect match (K8s ingress-nginx NodePort K8s'e akıtılıyor; /api/ K8s, /realms/+/resources/ compose KC hybrid)
- **Faz 11 GitOps kozmetik boşluk** (runtime'ı etkilemiyor):
  - `kubectl -n argocd get applications.argoproj.io -o wide` → `platform-prod OutOfSync/Degraded` + `platform-eso-prod OutOfSync/Degraded`, revision `ccf84a5`
  - `operationState.phase=Succeeded, message=successfully synced (all tasks run)` — sync fiilen uygulanmış
  - Degraded kök neden: ConfigMap'lerde `health.status=null` (K8s inherent health yok) → Argo Application-level aggregation bunu `Degraded` yorumluyor
  - Diff kök neden: v1beta1 era'dan kalma stored `managedFields` serialization; PR #54 `ignoreDifferences` hedefliyor ama ServerSideApply reconcile'da yeniden üretiyor
  - Açık teknik borç (Faz 11 cleanup): (A) `argocd-cm` ConfigMap'te `resource.customizations.health.ConfigMap` lua script Healthy döndür veya (B) `syncPolicy.syncOptions` içine `RespectIgnoreDifferences=true` ekle veya (C) Faz 13 cluster rebuild bu cosmetic'i doğal temizler
- **Faz 12 başlangıç çıktısı**:
  - `bootstrap/dr-drill.sh` merged, çalıştırılabilir
  - Backup producers canlı: `ssh staging-sw 'ls -lah ~/platform/backup/pg/prod | tail -3'` → `pg_dumpall_*.sql.gz` son 30 gün retention aktif
  - Vault snapshot 14 gün, KC export `kc=0` drift (partial export cron)
  - Manuel drill henüz YAPILMADI: `dr-validation` 0 → **5** (script var, execute yok)
- **5-sayaç Session 24 delta**:
  - `test-k8s`: 86 (değişim yok)
  - `prod-stateful-split`: 73 (değişim yok)
  - `prod-workload-gitops`: 63 → **72** (ComparisonError kapandı + operationState Succeeded; cosmetic diff GitOps gate'i `90+ Synced/Healthy`a taşıyamaz ama runtime gate geçti)
  - `secret-delivery`: 78 → **82** (v1 migration tam uyum, CSS + 8 ES stabil SecretSynced, ghcr-pull pull chain canlı, prod tarafı test tarafıyla paritede)
  - `dr-validation`: 0 → **5** (runbook + script var, drill execute yok)
- **Weighted operational continuity**: `~%74` → **`~%80`**

## Live Delta — Session 23 (2026-04-23 20:15 UTC+3)

- Public front-door no-token kontratı iki hostname'de tekrar doğrulandı:
  - `testai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
  - `ai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
- Prod k8s secret-delivery/workload yüzeyi canlı:
  - `ClusterSecretStore/vault-platform-gitops` `Ready=True/Valid`.
  - `platform-prod` namespace altında kritik `ExternalSecret` seti `SecretSynced=True`.
  - `platform-prod` backend Deployment'lar `READY=2/2`.
  - Argo app health notu: `platform-prod` hâlâ `Unknown/Degraded`, `platform-eso-prod` `Unknown/Healthy`.
- Prod authenticated smoke iki ayrı token sınıfıyla tekrarlandı:
  - `smoke-client` (service account): `authz/me=200`, `variants(1204|test-grid)=401`.
  - `canary-restricted@stage.local` (password grant, `canary-load`): `authz/me=200`, `superAdmin=false`, `permissions_count=7`, `roles_count=15`, `allowedScopes=[]`, `variants(1204)=403`, non-scoped `variants(9999)=401`.
- Kimlik eşleme drift bulgusu: farklı Keycloak kullanıcıları (`admin@example.com` ve `canary-restricted@stage.local`) `authz/me` tarafında aynı `userId=920001` ile dönüyor; scoped allow modelinin kapanmamasında bu eşleşme drift'i aday kök neden.
- Drift'in canlı kaynağı netleşti: prod `serban` realm `canary-load` client'ında `uid-static` hardcoded claim mapper (`claim.value=920001`) bulunuyor. Bu mapper `uid-claim` kullanıcı attribute mapper'ını gölgede bıraktığı için farklı kullanıcı tokenları aynı `uid` ile üretiliyor.
- Sonuç: authenticated zincirde artık deny davranışı (`403`) non-superAdmin kullanıcıyla kanıtlı; açık kapı non-superAdmin scoped allow (`gridId=1204` için `200`) seed kontratıdır.

## Live Delta — Session 22 (2026-04-23 19:41 UTC+3)

- Public front-door no-token kontratı iki hostname'de yeniden doğrulandı:
  - `testai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
  - `ai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
- Prod authenticated smoke (service-account token) tekrarlandı:
  - `smoke-client` client-credentials tokenında `aud=account`, `azp=smoke-client`.
  - Public `ai.acik.com`: `/api/v1/authz/me` `200`, `/api/v1/variants?gridId=1204` `401`, `/api/v1/variants?gridId=test-grid` `401`.
  - Ingress `https://127.0.0.1:30443` + `Host: ai.acik.com`: aynı pattern (`authz/me=200`, `variants=401`).
- Prod Keycloak client kontratı notu: `canary-load` client'ı `client_credentials` için `unauthorized_client (Client not enabled to retrieve service account)` döndürüyor; service-account smoke için aktif client `smoke-client`.
- Realm issuer parity no-token probeda korunuyor:
  - `testai`: `https://testai.acik.com/realms/platform-test`
  - `ai`: `https://ai.acik.com/realms/serban`
- Session 21'de kaydedilen public `503 vault_unavailable` bu turdaki no-token front-door probeda tekrar üretilemedi.
- Açık boşluk (Session 23 sonrası güncel): non-superAdmin scoped deny kanıtlandı (`403`), ancak scoped allow (`gridId=1204` için `200`) henüz canlıda kapanmadı.

## Live Delta — Session 21 (2026-04-23 18:05 UTC+3)

- Host-bridge ağ kontratı prod için tek modelde çalışıyor:
  - Compose bind: `platform-pg-prod` `10.9.10.53:5432`, `platform-kc-prod` `10.9.10.53:8081`, `platform-vault-prod` `10.9.10.53:8200` (+ `127.0.0.1` admin bind).
  - K8s host-service Endpoints: `postgres=10.9.10.53:5432`, `keycloak=10.9.10.53:8081`, `vault=10.9.10.53:8200`.
  - UFW routed modeli canlı: `10.9.10.53:{5432,8081,8200}` için `ALLOW IN` + `ALLOW FWD` kuralları aktif.
- Gate sonucu (istenen sıra):
  - `ClusterSecretStore Ready=True`: `vault-platform-gitops -> True/Valid`.
  - `prod ExternalSecret SecretSynced=True`: kritik setin tamamı `True/SecretSynced`.
  - `backend rollout Running`: tüm backend Deployment'lar `ready=desired`, `openfga` StatefulSet `1/1`.
  - `authenticated prod smoke`: **PARTIAL** (k8s ingress: `authz/me=200`, `variants=401`; public `ai.acik.com`: `authz/me` ve `variants` `503 vault_unavailable`).
- Authenticated zincirde kök neden ayrıştırması:
  - Aynı bearer token ile `127.0.0.1:30443` (ingress) ve `ai.acik.com` (public front-door) farklı davranıyor; bu, blocker'ın host-bridge/ESO değil front-door backend zinciri olduğunu doğruluyor.
  - `variant-service` authenticated çağrıda halen `401` dönüyor; ağ/ESO katmanı geçti, kalan blocker authz/contract düzeyi.
- Ek kapanış:
  - `kv/platform/openfga` placeholder değerleri canlıda güncellendi (`store_id` + `model_id` gerçek ID), `permission-service-secrets` ve `variant-service-secrets` yeni ID'lerle senkronlandı.
  - `smoke-client` service-account token ve `testuser` password-grant token ile sonuç aynı pattern'i veriyor (`ingress 200/401`, public 503).

---

## 1. 5-Sayaç Dashboard (0-95 skala)

Codex önerisi: `0=yok`, `25=doküman`, `50=partial live`, `75=kanıtlı ama cutover-ready değil`, `90+=gate geçmiş`. Tek host + warm rollback yok → tavan ~95.

| Sayaç | Değer | Claim | Last Evidence | Last Verified | Owner | Next Gate |
|---|---:|---|---|---|---|---|
| **test-k8s** | **86** | Authoritative `staging-sw` test cluster'da bridge/ESO zinciri canlı: `ClusterSecretStore` `Ready=True`, kritik `ExternalSecret`'ler `SecretSynced=True`, `variant-service` + `permission-service` + `api-gateway` `1/1 Running`. `api-gateway` üstündeki public v1 theme ve variants route drift'i live patch ile kapatıldı; `/api/v1/theme-registry` `200`. Scoped authz kanıtı artık non-superAdmin synthetic kullanıcıyla canlı: `canaryscope` tokenında `superAdmin=false`, `roles=[\"VARIANT_SCOPE_CANARY\"]`, allow scope `PROJECT/1204`; aynı tokenla `/api/v1/variants?gridId=1204` `200`, `gridId=test-grid` `403`. Anonymous crawler ikinci kez `0` hata verdi. Caveat: authoritative remote `k3d-test` cluster'da şu an `monitoring` namespace / `Probe` / `PrometheusRule` yüzeyi yok; bu yüzden `24h` soak `2026-04-22 23:18 UTC+3` itibarıyla public/front-door soak olarak başladı, full in-cluster alert-backed soak değil | `curl -ks https://testai.acik.com/` → `VITE_FRONTEND_PUBLIC_ORIGIN=https://testai.acik.com`, `VITE_KEYCLOAK_REALM=platform-test`, `VITE_GATEWAY_URL=https://testai.acik.com/api`; `curl -sk https://testai.acik.com/realms/platform-test/.well-known/openid-configuration | jq -r .issuer` → `https://testai.acik.com/realms/platform-test`; `curl -sk -I https://testai.acik.com/resources/4wivm/login/keycloak.v2/css/styles.css` → `200 text/css`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get clustersecretstore vault-platform-gitops -o jsonpath=\"{.status.conditions[0].type} {.status.conditions[0].status} {.status.conditions[0].reason}\"'` → `Ready True Valid`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl -n platform-test get externalsecret -o wide'` → kritik secret'ler `SecretSynced=True`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl -n platform-test get deploy variant-service permission-service api-gateway -o wide'` → `1/1`; `curl -sk -o /dev/null -w '%{http_code}' https://testai.acik.com/api/v1/theme-registry` → `200`; password grant (`client_id=frontend`, `username=canaryscope`) + `curl -sk -H 'Authorization: Bearer …' https://testai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false` + `allowedScopes=[{\"scopeType\":\"PROJECT\",\"scopeRefId\":1204}]`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `200`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=test-grid'` → `403`; crawler raporları `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-02-11-902Z.json` ve `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-22-28-113Z.json` → `routes with errors: 0`, `console errors: 0`, `network failures: 0`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get ns'` → `monitoring` yok; `kubectl get probe -A` / `kubectl get prometheusrule -A` → boş | 2026-04-23 | Codex | `24h` public soak penceresini izle; authoritative test monitoring truth'unu geri kur veya yokluğunu plan/durumda açıkça taşı |
| **prod-stateful-split** | **76** | Session 25+26 birleşik: `platform-pg-prod` + `platform-vault-prod` canlı; prod compose/discovery yüzeyi stabil; `platform-kc-prod` compose recreate sonrası `Health.Status=healthy` (PR #57 dual-network + healthcheck `localhost→127.0.0.1` + printf). Known Drift §"platform-kc-prod unhealthy" → CLOSED. Authenticated prod çağrıda `authz/me` `200`; `variants` davranışı token sınıfına göre ayrışıyor (`canary-restricted@stage.local` için canary `gridId=1204` → `403`, non-scoped `gridId=9999` → `401`). Açık blocker: prod non-superAdmin scoped allow seed kontratı | `docker inspect platform-kc-prod --format '{{.State.Status}} {{.State.Health.Status}}'` → `running healthy`; dual network `platform-prod-net platform_microservice-network`; healthcheck exit log son 3 `[0] [0] [0]`; Eureka: `AUTH-SERVICE/USER-SERVICE/PERMISSION-SERVICE/VARIANT-SERVICE/API-GATEWAY/CORE-DATA-SERVICE/REPORT-SERVICE` kayıtlı; prod token smoke: `authz/me=200`, `variants(1204)=403`, `variants(9999)=401` | 2026-04-24 | Ops | Prod scoped allow seed kontratı + DR drill full kapanış |
| **prod-workload-gitops** | **88** | Session 28 T+30: ArgoCD platform-prod + platform-eso-prod artık **Synced/Healthy** ✅ (revision `52af34a`). PR #72 RespectIgnoreDifferences + PR #73 /metadata wide + PR #76 jqPathExpressions ESO v1 default fields (`conversionStrategy`, `decodingStrategy`, `metadataPolicy`, `nullBytePolicy`) combine ile OutOfSync cosmetic drift tamamen kapandı. 19 pod Running + openfga Complete + canlı trafik ai.acik.com/api/ 200 byte-perfect match. Codex scale: **90+ GitOps gate geçti** (runtime cutover-ready). 2 puan eksik: 72h rollback-window hâlâ aktif (T+24h/T+72h gate'leri pending) | `kubectl -n argocd get applications.argoproj.io -o wide` → 4/4 **Synced/Healthy** revision `52af34a`; CSS + 8 ES Synced; openfga Complete; runtime 19 pod Running; `ai.acik.com/api/v1/theme-registry → 200 15666B` byte-perfect | 2026-04-24 | Claude | T+72h rollback-window kapanış → hybrid prod permanent (GitOps gate 88 → 92 beklenir) |
| **secret-delivery** | **87** | Session 26 CANLIDA TEYİT: Session 25 iddia stale idi (manifest merged ≠ canlı apply). Session 26'da manual sync tetiklendi: roleId UUID (`0db7ba83-b485-4afb-da7d-e1041b1f8a56`) canlıya geçti, CSS `Ready=True/Valid "store validated"`, 8/8 ES `SecretSynced=True` (auth/core-data/ghcr-pull/permission/report/schema/user/variant). AppRole login 400 error kapandı | CANLIDA KANIT: `ssh staging-sw 'docker exec k3d-prod-server-0 kubectl get clustersecretstore vault-platform-gitops -o jsonpath=\"{.spec.provider.vault.auth.appRole.roleId} | {.status.conditions[0].status}\"'` → `0db7ba83-b485-4afb-da7d-e1041b1f8a56 \| True`; 8 ES force-sync annotation sonrası `READY=True` (tümü) | 2026-04-24 | Claude | Faz 13 atomic cutover için gate ≥80 ✅ CANLI KANITLI |
| **dr-validation** | **85** | Session 27: **Gerçek full DR drill PASS** (iter-11, 2026-04-24 01:19:03-01:21:15 UTC+3). 11 iterative bug fix cycle: #58 (safety+set-e+stderr) + #59 (permission) + #60 (sealed smoke) + #65 (wrong user adı) + #66 (keycloak_user correct) + #67 (KC 26.5.5 image match) + #68 (t1 unbound). Final akış: PG restore 2s + Vault 16s + KC up 20s + **KC imported 30s** + SMOKE[1] (PG+Vault+KC OIDC 200) + 60s sleep + SMOKE[2] (PG+Vault+KC OIDC 200) + RTO 132s + exit 0. `dr-validation=85` gerçek full drill + 2x KC OIDC smoke kanıtlı | `cat /tmp/dr-drill-20260424-011903.log` → `KC: imported (30s)`, `SMOKE[1] KC: OIDC discovery 200`, `SMOKE[2] KC: OIDC discovery 200`, `RTO: PASS (132s / 14400s budget)`, `=== DR DRILL PASS ===` exit 0 | 2026-04-24 | Claude | Faz 13 prereq ≥85 ✅ CANLI; drill cron scheduling (PLAN.md D23 quarterly) sonraki opsiyonel iş |

**Weighted operational continuity**: `~%85` (Session 27 HONEST — Codex adversarial review verdict=REVISE sonrası kalibre edildi. Önceki iddia "%88" secret+dr çift-ağırlık gate olarak değil düz ortalama olarak okunduğunda abartılıydı. Codex önerisi %84; runtime kanıtları (ESO canlı recovered + openfga Complete + platform-prod Healthy + full DR drill iter-11 PASS) %85'i savunuyor. Faz 13 prereq CANLIDA TEYİT: secret-delivery=87 ≥80 ✅ + dr-validation=85 ≥85 ✅. Faz 13 execute kararı **koşullu GO**: Session 28 açılışında 5 komutluk live refresh eşleşirse execute; yoksa hedefli cleanup (ArgoCD cosmetic, KC token path unify). Kalan opsiyonel: drill quarterly cron, prod scoped allow seed, RespectIgnoreDifferences syncOption.)

---

## 2. Canlı Trafik Matrisi

| Hostname | Edge | Real Backend Owner | Smoke Evidence |
|---|---|---|---|
| `ai.acik.com` | staging-sw live edge + restored prod web root | Prod web rollback sonrası authoritative root yeniden `/home/halil/platform/web/releases/773175b`; frontend `platform-web-nginx` container'ı bu release'i mount ediyor ve host-network modunda `:80/:443` front-door'u servis ediyor. Backend tarafında prod compose/discovery yüzeyi toparlandı: `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE` healthy ve Eureka'da kayıtlı. Canlı recovery zinciri: prod/test PG alias collision kapatıldı, aktif `platform-web-nginx` config'inde `ai` `/api/` upstream'i `127.0.0.1:8082` yerine `127.0.0.1:8080` gateway yoluna çevrildi, prod `api-gateway` temiz env ile recreate edilerek gerçek prod issuer/JWKS değerleri container'a geçirildi, ardından `variant-service` canlı compose env'i audience/OpenFGA/permission-service internal port açısından hizalandı. Sonuçta public no-token kontratı hizalı, authenticated hatta `authz/me` `200`; kalan açık drift scoped allow seed kontratı (`smoke-client` service-account hattında `variants=401`, non-superAdmin password-grant hattında canary `gridId=1204` için `403`, non-scoped `gridId=9999` için `401`) | `docker inspect platform-web-nginx` → `NetworkMode=host`; canlı config `/home/halil/platform/web/nginx/default.conf` ve `docker exec platform-web-nginx nginx -T` içinde `server_name ai.acik.com` + `location /api/`; fix öncesi `proxy_pass http://127.0.0.1:8082;`, source canonical örnekte `/Users/halilkocoglu/Documents/dev/deploy/ubuntu/nginx-frontend-5544.example.conf` içinde `/api/` → `127.0.0.1:8080/api/`; fix sonrası public no-token smoke: `curl -sk https://ai.acik.com/api/v1/authz/me` → `401`, `curl -sk https://ai.acik.com/api/v1/theme-registry` → `200`, `curl -sk 'https://ai.acik.com/api/v1/variants?gridId=1204'` → `401`; gerçek prod token smoke: `curl -sk -X POST https://ai.acik.com/realms/serban/protocol/openid-connect/token ... client_id=canary-load ...` → token, decoded claims `aud=\"account\"`; aynı tokenla `curl -sk -H 'Authorization: Bearer …' https://ai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false` + `permissions_count=7`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=1204'` → `403`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=9999'` → `401`; service-account token smoke: `authz/me=200`, `variants=401`; `docker exec platform-variant-service-1 env` → `SECURITY_JWT_AUDIENCE=account`, `ERP_OPENFGA_STORE_ID=01KPVGQCTZ3K5PHHM1HY0PMN13`, `ERP_OPENFGA_MODEL_ID=01KPVGQCY4XGRVAHWATQ4PQ974`, `PERMISSION_SERVICE_BASE_URL=http://permission-service:8084`; `docker exec platform-discovery-server-1 curl http://localhost:8761/eureka/apps` → `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE`, `API-GATEWAY`, `CORE-DATA-SERVICE`, `REPORT-SERVICE` kayıtlı |
| `testai.acik.com` | Authoritative external edge doğru stage release yüzeyine bakıyor | Host üstündeki `/home/halil/platform/web-stage/releases/a67f34e` release'i, `platform-web-nginx-stage`, `platform-kc-test`, `platform-pg-test`, `platform-vault-test` ve remote `k3d-test` public front-door'a bağlı. Frontend bundle public `testai/api` kontratıyla derlenmiş. Test ESO/bridge zinciri remote hostta sağlıklı; `api-gateway` üstündeki eksik `theme` + public v1 `variants` route'ları live patch edildiği için `/api/v1/theme-registry` `200`. Scoped authz zinciri artık gerçek non-superAdmin synthetic ile kanıtlı: `canaryscope` kullanıcı/tokenu canary `gridId=1204` için `200`, non-canary `test-grid` için `403`. Anonymous crawler iki koşuda da hata üretmedi | Public truth: `curl -ks https://testai.acik.com/` → `VITE_FRONTEND_PUBLIC_ORIGIN=https://testai.acik.com`, `VITE_KEYCLOAK_REALM=platform-test`, `VITE_GATEWAY_URL=https://testai.acik.com/api`; `curl -sk https://testai.acik.com/realms/platform-test/.well-known/openid-configuration | jq -r .issuer` → `https://testai.acik.com/realms/platform-test`; `curl -sk https://testai.acik.com/login` → `200`; `curl -sk -I https://testai.acik.com/resources/4wivm/login/keycloak.v2/css/styles.css` → `200 text/css`; `curl -sk -o /dev/null -w '%{http_code}' https://testai.acik.com/api/v1/theme-registry` → `200`; no-token `curl -sk -o /dev/null -w '%{http_code}' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `401`; password grant (`client_id=frontend`, `username=canaryscope`) ile `curl -sk -H 'Authorization: Bearer …' https://testai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `200`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=test-grid'` → `403`; crawler raporları `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-02-11-902Z.json` ve `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-22-28-113Z.json` → `routes with errors: 0`, `console errors: 0`, `network failures: 0` |
| `argocd` | live host `k3d-prod` control-plane ayakta, apps OutOfSync/**Healthy** (Session 27) | `argocd` + `external-secrets` + `platform-prod` namespace/CRD/app yüzeyi mevcut; `platform-prod` + `platform-eso-prod` `OutOfSync/Healthy` (Degraded kapandı — openfga-migrate Complete + 8 ES Healthy); root + platform-system `Synced/Healthy`. OutOfSync cosmetic v1beta1 stored serialization kalıntı (PR #54 ignoreDifferences kısmi, Faz 13 rebuild ile doğal temizlenir) | `kubectl -n argocd get applications.argoproj.io -o wide` → prod apps `OutOfSync/Healthy`; `kubectl -n platform-prod get job openfga-migrate` → `Complete 1/1 5s` |
| Monitoring | Host backup freshness metriği var; authoritative test cluster monitoring yüzeyi şu an yok | Remote `k3d-test` authoritative cluster'da `monitoring` namespace, `Probe` ve `PrometheusRule` bulunmuyor. Bu nedenle `24h` soak, Prometheus-backed değil public front-door/manual soak olarak başladı. Host textfile exporter tarafında `pg`/`vault` timestamp var, `kc=0` devam ediyor | `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get ns'` → `monitoring` yok; `kubectl get probe -A` → boş; `kubectl get prometheusrule -A` → boş; `backup_freshness.prom` içinde `backup_last_success_timestamp_seconds{type=\"kc\"} 0` |

---

## 3. Rollback Durumu

| Akış | Status | Preserved Volumes | Last Test Date | RTO/RPO |
|---|---|---|---|---|
| **ai.acik.com → compose legacy** | `cold-potential` (test edilmedi) | Docker volume: `platform_loki_data`, `platform_tempo_data`, `platform_vault-data`, `platform_vault_logs`, `platform_vault_snapshots`; host bind-mount: `/home/halil/platform-stateful/prod/{postgres,keycloak,vault}` | **NEVER** | Hedef: RTO≤4h, RPO≤24h (ölçülmedi) |
| **testai.acik.com → compose legacy** | `no rollback path` | Test stateful yeni stack, eski yoktu | N/A | N/A |
| **K8s workload rollback** | `k8s workload henüz apply edilmedi prod` | N/A | N/A | N/A |

**Warm rollback iddiası ihlali**: ADR-0002 §8 `T+72h warm rollback` istiyor. Şu an `cold rollback potential` = sözleşmeye aykırı.

---

## 4. Known Drift (Yazılı Karar Yok)

| Drift | ADR/Kontrat | Gerçek Durum | Owner | Target Date | Blocker Class |
|---|---|---|---|---|---|
| Disk path | `/srv/platform/stateful/{prod,test}/...` (ADR §3.2) | `/home/halil/platform-stateful/...` (override) | Ops | 2026-04-25 | LOW (çalışıyor, doküman eksik) |
| Test Vault port | 8201 (ADR §0.2) | 8301 (eski vault 8201'i tutuyor) | Ops | 2026-04-25 | LOW |
| Vault version | ≥1.21 (eski compose) | 1.17 (yeni host-compose) | Claude | 2026-04-23 | MEDIUM — undocumented version track change |
| k3d CLI | staging-sw'de kurulu (ADR §3.1 varsayım) | VAR; Session 13 recreate runbook'u `ssh staging-sw` üstünden `k3d cluster delete/create test` ile canlı çalıştı | Ops | N/A | LOW |
| Test runtime closure | `testai.acik.com` public root, gateway ve realm stage yüzeyine gidiyor olmalı; bunun üstüne runtime deny/login/crawler + authenticated allow kapanmalı; test authoritative before prod | Front-door parity doğru, Keycloak browser static asset zinciri canlıda temiz, anonymous crawler iki kez `0` hata üretti. Scoped authz zinciri artık non-superAdmin synthetic ile kanıtlı: `canaryscope` tokenıyla `authz/me` `200` + `superAdmin=false`, `/api/v1/variants?gridId=1204` `200`, `/api/v1/variants?gridId=test-grid` `403`. Ayrı not: authoritative remote `k3d-test` cluster'da monitoring/blackbox yüzeyi yok; başlatılan `24h` soak bu yüzden public/front-door soak. Prod public hedefleri (`ai.acik.com/api/v1/*`) no-token tarafta hizalı; authenticated hatta `authz/me` `200` korunuyor fakat `variants` davranışı token sınıfına göre ayrışıyor (`smoke-client` service-account `401`, non-superAdmin password-grant `403`). Bu artık audience/JWKS değil; prod scoped allow seed kontratı ayrı blocker olarak açık | Ops/App | Faz 11 | HIGH |
| Kubectl context split | `testai` için authoritative cluster aynı hostta çalışan `staging-sw` `k3d-test` olmalı | Lokal Mac `kubectl --context k3d-test` ayrı cluster'a gidiyor (`linuxkit`/Docker Desktop) ve `testai.acik.com` için karar kaynağı değildir; live truth bundan sonra `ssh staging-sw` üstünden alınmalı | Codex | Hemen | MEDIUM |
| Test monitoring drift | Faz C tarzı soak için authoritative test cluster'da monitoring/Probe/PrometheusRule yüzeyi bulunmalı | Remote `k3d-test` cluster recreate sonrası `monitoring` namespace ve Prometheus operator yüzeyi yok; mevcut soak yalnız public/front-door kanıtı üretiyor | Ops | Faz 11 | HIGH |
| Prod authenticated public contract | `ai.acik.com` public `/api/v1/*` kontratı front-door'da internal gateway ile hizalanmalı ve gerçek prod token authenticated smoke geçmeli | Prod `platform-api-gateway-1` route table'da v1 path'ler var; compose/discovery yüzeyi toparlanmış durumda ve `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE` Eureka'da kayıtlı. Front-door drift kapatıldı: aktif `platform-web-nginx` config'inde `ai` `/api/` upstream'i `127.0.0.1:8082` idi, `127.0.0.1:8080` yapıldı ve public no-token smoke internal gateway ile hizalandı (`401/200/401`). Prod `api-gateway` issuer/JWKS drift'i kapatıldı: canlı env artık `SECURITY_JWT_ISSUER=https://ai.acik.com/realms/serban` + `SECURITY_JWT_JWK_SET_URI=http://keycloak:8080/realms/serban/protocol/openid-connect/certs` taşıyor ve gerçek prod token ile `authz/me` `200` dönüyor. Bu turda `variant-service` canlı compose env'i de düzeltildi: `SECURITY_JWT_AUDIENCE=account`, OpenFGA store/model dolu, `permission-service` internal URL `http://permission-service:8084`. Açık authenticated blocker artık audience/JWKS/env değil: `canary-load` tokenındaki `canary-restricted@stage.local` kullanıcısı için `authz/me` `200` + `permissions_count=7` + `allowedScopes=[]` + `superAdmin=false`; canary `variants?gridId=1204` `403`, non-scoped `variants?gridId=9999` `401`. Service-account tokenında ise `variants` `401` devam ediyor. `platform-kc-prod` healthcheck ayrı drift olarak `unhealthy` kalıyor, fakat token mint ve `authz/me` geçtiği için artık birincil public blocker gateway decoder değil | Ops/App | Faz 11 | HIGH |
| Prod Keycloak uid mapper drift | Non-superAdmin scoped parity için farklı kullanıcı tokenları farklı kimlik claim'i taşımalı (`uid` veya `userId`) | `serban` realm `canary-load` client'ında iki mapper birlikte aktif: `uid-claim` (user attribute) + `uid-static` (hardcoded). Hardcoded mapper `claim.value=920001` nedeniyle farklı kullanıcılar aynı `uid` ile token alıyor (`admin@example.com` ve `canary-restricted@stage.local` için `uid=920001`). Bu yüzden scoped allow modelinde kullanıcı ayrımı bozuluyor | `kcadm get clients/<canary-load-id>/protocol-mappers/models -r serban` → `uid-static` + `claim.value=920001`; token decode (`grant_type=password`, `client_id=canary-load`) ile iki farklı user için `uid=920001`; `variant-service` logu `Resolved variant authz context ... userId=920001` | Ops/App | Faz 11 | HIGH |
| Prod ESO `roleId` | Gerçek UUID overlay patch | Placeholder literal `"eso-runtime"` | Claude | Faz 11 | HIGH (secret delivery block) |
| ClusterIssuer Let's Encrypt | `bootstrap/install-cert-manager.sh` var, apply edilmiş | ClusterIssuer YOK canlıda | Claude | Faz 12 | MEDIUM |
| Test cluster ArgoCD register | Prod hub'dan yönet (ADR §3.7) | k3d-test kayıtlı DEĞİL | Ops | Faz 11 | MEDIUM |
| Handoff split | Append-only 1207 satır | Bu PR ile canonical + historical ayrımı başladı | Claude | Faz 10 | LOW |

---

## 5. Sonraki 4 Faz (Codex Planı)

Detay bu dokümanda tutulur; ayrı session log split'i henüz repo içine alınmadı.

| Faz | Pencere | Done Kriter | No-Go |
|---|---|---|---|
| **10 Dürüstlük Recovery** | D0-D1 (21-22 Nis) | Bu dosya + handoff split + söylem revizyonu | Aktif 1207 satır handoff karar kaynağı kalırsa |
| **11 Secret Delivery Truth** | D2-D4 (23-25 Nis) | Test CSS Ready + kritik ExternalSecret Sync + frontend canonical image + frontend SA public pull path + stage/prod web path isolation host üzerinde doğrulanmış + authoritative public `testai.acik.com` root gerçekten stage bundle'ı servis ediyor: `VITE_FRONTEND_PUBLIC_ORIGIN=testai`, `VITE_GATEWAY_URL=testai/api`, `VITE_KEYCLOAK_REALM=platform-test` + `/.well-known/openid-configuration` `200` + Keycloak browser login support path temiz (`3p-cookies` beklenen davranışta, login static resources 2xx/MIME doğru) + deny zinciri yeşil + crawler `runtimeErrors=0` + public authenticated path dürüstçe yazılmış: `canaryscope` (non-superAdmin, `VARIANT_SCOPE_CANARY`, `PROJECT/1204`) ile canary `gridId=1204` `200`, non-canary `test-grid` `403`; `testuser(superAdmin)` yalnız broad-admin smoke olarak kalır + authoritative test monitoring yokluğu açıkça yazılmış + prod ESO/live-host yokluğu ve prod public `/api/v1/*` kontrat açığı dürüstçe yazılmış | `curl https://testai.acik.com/` veya `/.well-known/openid-configuration` yeniden drift ederse; anonymous crawler yeniden hata üretirse; browser Keycloak static resources `404/500` + yanlış MIME verirse; login smoke callback/token aşamasında kırılırsa; authoritative test monitoring yokluğu gizlenirse veya prod public `/api/v1/*` kontratı kapanmamışken hazır dili kullanılırsa |
| **12 DR Cold Rollback** | D5-D7 (26-28 Nis) | Clone drill + 2x independent boot-smoke + RTO≤4h | Canlı volume dokunulursa |
| **13 Atomic Cutover** | D8-D11 (29 Nis-3 May) | Nginx upstream switch + T+15 gate + 72h warm rollback | `secret-delivery<80` veya `dr-validation<85` |

---

## 6. Yasak Terimler (Söylem Temizliği)

Bu dokümanda ve sonraki iletişimde **kullanılmayacak**:

- ❌ "Faz H DONE" / "H fiilen yapıldı" → ✅ "Legacy container rm, Faz H formal olarak henüz BAŞLAMADI (soak sonrası)"
- ❌ "Faz G cutover yapıldı" / "soft cutover" → ✅ "Stateful split migration with compose-preserved workload"
- ❌ "%99.5 migration complete" → ✅ "Weighted operational continuity ~%74"
- ❌ "test Zanzibar smoke tamam" → ✅ "Front-door, Keycloak static asset zinciri, test ESO/ExternalSecret, non-superAdmin scoped deny/allow, authenticated allow ve anonymous crawler canlıda doğrulandı; authoritative test monitoring ise şu an yok"
- ❌ "warm rollback available" → ✅ "cold rollback potential, drill yapılmadı"
- ❌ "ESO chain hazır, sadece routing" → ✅ "Authoritative `staging-sw` test cluster'da ESO/ExternalSecret zinciri çalışıyor; `theme-registry` sorunu live `api-gateway` route drift'iydi ve patch edildi. Prod cluster'da ESO yüzeyi ise henüz yok"

---

## 7. Referanslar

- **ADR**: `docs/adr/0002-single-host-dual-cluster.md` (supersedes D32)
- **Roadmap**: `PLAN.md` §0 Faz A-I (Faz 10-13 bu dokümanda ek)
- **Runbook**: `docs/prod-cutover-runbook-v2.md`, `docs/S5-disaster-recovery-runbook.md`
- **Handoff**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (Session 1-10 kronolojik, append-only, karar kaynağı değil)
- **Review backlog**: `docs/plan-revision-review-2026-04-20.md` (canonical cleanup backlog)
- **Codex adversarial reviews**: thread `019daa7f` (adversarial), thread `019daad8` (4-faz plan)
