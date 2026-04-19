# ADR-0002 — Single-Host Dual-Cluster Production Topology With Full Stateful Isolation

## 1. Status

**Accepted** — 2026-04-19

## 2. Context

Platform için kalıcı yön şu şekilde netleşmiştir:

- `platform-k8s-gitops` tek prod desired-state repo olacaktır
- Prod ve test aynı fiziksel sunucuda iki ayrı `k3d` cluster olarak çalışacaktır
- Önceki `D32 separate-host` (staging-sw-2 ayrı sunucu) yönü artık ana yol değildir; tarihi bağlam olarak korunur, superseded statüsüne alınır
- Amaç kısa vadede "tek hostta güvenli ve dürüst izolasyon", orta vadede "ikinci host ve ileri genişleme için hazır kontrat" oluşturmaktır

Bu karar aşağıdaki kısıtlar altında verilmiştir:

- Ayrı fiziksel host hemen zorunlu tutulmayacaktır (forward-extension path olarak açık)
- Kubernetes içine PostgreSQL / Keycloak / Vault taşımanın tek-host mimaride gerçek dayanıklılık artışı üretmeyeceği kabul edilmiştir
- Prod ve test arasında stateful servis paylaşımı kabul edilemez bulunmuştur (tek PG-ayrı schema YETERSİZ)
- Failure-domain dürüstlüğü sahte HA söyleminden daha önceliklidir
- Staging-sw donanım kapasitesi: **8 vCPU (gerekirse yükseltilebilir) / 32 GiB / 400 GB SSD**

### 2.1 Değerlendirilen Alternatifler

**A. Ayrı fiziksel prod host (eski D32)**
- Artı: failure-domain temiz, noisy-neighbor minimal, stateful host bazında ayrık
- Eksi: ek donanım, operasyon zamanı, kullanıcı aynı-host kararıyla çelişir, teslim hızı düşer
- **Sonuç:** Forward-extension yolu olarak açık, ana karar değil

**B. Aynı hostta shared PG/KC/Vault**
- Artı: hızlı kurulum, ilk bakışta düşük kaynak
- Eksi: prod/test veri ve kimlik izolasyonu zayıf, yanlış migration/secret/config doğrudan prod'u etkiler, blast radius kabul edilemez
- **Sonuç:** Reddedildi

**C. PG/KC/Vault Kubernetes içine taşıma**
- Artı: GitOps görünürlüğü, manifest tekliği
- Eksi: tek-hostta dayanıklılık artmaz, bootstrap döngüsü, Vault+ESO failure coupling, operatör/PVC karmaşıklığı faydayı aşar
- **Sonuç:** 6-12 ay için reddedildi (forward-extension değerlendirilir)

## 3. Decision

### 3.1 Cluster Topology
1. Aynı fiziksel sunucuda iki ayrı cluster çalışır: `k3d-prod` + `k3d-test`
2. Test cluster **default scale-to-zero** (kullanıcı direktif 2026-04-19: "test genelde kapalı olacak"); ihtiyaç durumunda geçici açılır

### 3.2 Full Stateful Isolation
1. **Ayrı PostgreSQL instance** — `platform-pg-prod` + `platform-pg-test`
2. **Ayrı Keycloak instance** — `platform-kc-prod` + `platform-kc-test`
3. **Ayrı Vault daemon** — `platform-vault-prod` + `platform-vault-test`
4. Tek PG-ayrı schema YETERSİZ; tek Vault-namespace YETERSİZ

### 3.3 Network Contract
- `k3d-prod` + prod stateful servisler → YALNIZ `platform-prod-net`
- `k3d-test` + test stateful servisler → YALNIZ `platform-test-net`
- `platform_microservice-network` stateful'dan arındırılır (geçiş sürecinde eski compose backend yalnız rollback amacıyla)

### 3.4 Host Disk Layout (Bind-Mount)
- `/srv/platform/stateful/prod/postgres`
- `/srv/platform/stateful/prod/keycloak`
- `/srv/platform/stateful/prod/vault`
- `/srv/platform/stateful/test/postgres`
- `/srv/platform/stateful/test/keycloak`
- `/srv/platform/stateful/test/vault`

Bind-mount deseni kasıtlı forward-extension path: ileride ayrı partition/disk/block device'a taşınabilir.

### 3.5 Port Contract
| Service | Prod | Test |
|---|---:|---:|
| PostgreSQL | 5432 | 5433 |
| Keycloak | 8081 | 8082 |
| Vault | 8200 | 8201 |

### 3.6 Vault Design
- İki ayrı Vault daemon (namespace YETERSİZ)
- Secret path her Vault içinde env-neutral: `kv/platform/<svc>` (manifest sadeliği; overlay sadece store endpoint + role_id patch)
- Policy dizin yapısı:
  - `bootstrap/vault-policies/common/` — ortak policy logic
  - `bootstrap/vault-policies/prod/` — prod-specific role binding
  - `bootstrap/vault-policies/test/` — test-specific role binding

### 3.7 ArgoCD Design
- Tek ArgoCD hub prod cluster'da
- Prod auto-sync MANUAL, test auto-sync açık olabilir
- Test cluster credential **Git'te tutulmaz** — Vault/out-of-band bootstrap flow
- Root AppOfApps pattern korunur

### 3.8 Observability Design
- Prod cluster kube-prometheus-stack ana gözlem hub'ı
- Test cluster minimal metrics (kube-state-metrics + node-exporter + ingress + ESO)
- Test → prod `remote_write` (blackbox-only YETERSİZ, pod/ingress iç sinyalleri görünmeli)
- Grafana tek instance prod, dashboard'lar `cluster=test|prod` label ayrımı
- Loki/Tempo prod only (ilk aşama); test logs/traces nice-to-have
- Legacy compose `platform_observability-network` prod live ÖNCE kapatılır

### 3.9 Operational Mode Contract
Aşağıdaki üç mod standartlaşır: `normal` / `cutover-freeze` / `rollback-window` (bkz §5).

### 3.10 HA Disclaimer
Bu mimari **HA DEĞİLDİR**. Tek host kaybında prod ve test birlikte etkilenebilir. Bu durum açıkça kabul edilmiştir.

## 4. Consequences

### 4.1 Positive
- Tek host üstünde bile prod/test değişiklik izolasyonu net
- Prod ve test veri/kimlik/secret sınırları belirgin (cross-contamination olanaksız)
- GitOps repo tek prod truth olarak sadeleşir
- İkinci host veya güçlü stateful katmana geçiş için kontrat hazır (forward-extension)
- Host bind-mount + sabit naming, backup/restore'u kolaylaştırır
- ArgoCD topolojisi sade: tek hub, iki hedef

### 4.2 Negative
- Failure-domain tektir (kernel, Docker daemon, disk, NIC, host nginx, fiziksel sunucu ortak)
- Aynı hostta test + runner + monitoring + rollback yükleri yönetilmezse noisy-neighbor riski
- Vault auto-unseal / HSM / gerçek HA yoktur (manual unseal kabul)
- Tek-host storage pressure ve log growth KRİTİK risk (400 GB disk daralığı)

### 4.3 Honest Disclosure
Bu karar **sağlamaz**:
- Yüksek erişilebilirlik
- Disaster-proof izolasyon
- Host kaybında bağımsız prod devamlılığı
- Stateful tier quorum tabanlı güvenliği

Bu karar **sağlar**:
- Tek host içinde dürüst, net, audit edilebilir izolasyon
- State-sharing kaynaklı prod kirlenme engeli
- İleri genişleme için temiz geçiş yüzeyi

## 5. Operational Mode Contract

### 5.1 `normal` Mode
**Amaç:** Günlük işletim, test, kontrollü değişiklik, standart gözlem

**Aktif bileşenler:**
- `k3d-prod` + prod workload
- Prod stateful servisler (PG/KC/Vault)
- Host nginx edge
- Prod monitoring stack
- Actions runner (concurrency sınırlı, `1`)
- `k3d-test` control plane
- Test workload **default scale-to-zero** (kullanıcı direktif); ihtiyaç durumunda açık

**Yasaklar:**
- Prod ve test arasında shared stateful service
- Legacy compose observability'yi paralel truth olarak yaşatmak
- Rollback kapsamını belirsiz bırakmak

### 5.2 `cutover-freeze` Mode
**Amaç:** Prod cutover öncesi değişkenlik minimumu

**Aktif bileşenler:**
- `k3d-prod` + prod workload
- Prod stateful servisler
- Host nginx edge
- Prod monitoring
- Test minimal workload (sadece health/synthetic)
- Throttled runner (CPU quota %50)

**Zorunlu kısıtlar:**
- Test full workload yasak
- Yeni feature deploy yasak
- Schema değişikliği yasak
- Legacy compose observability kapalı
- CI concurrency düşük
- Prod dışı topology churn yasak

**Transition checklist (entry):**
- Runner throttle uygulandı
- Legacy observability kapandı
- Prod preflight smoke PASS
- Secret seed doğrulandı
- Image immutability doğrulandı
- T-30m no-go checklist yeşil

### 5.3 `rollback-window` Mode
**Amaç:** Atomic cutover sonrası 72 saat güvenli geri dönüş

**Aktif bileşenler:**
- `k3d-prod` live trafik
- Prod stateful servisler
- Host nginx edge
- Prod monitoring
- Prod legacy compose backend warm standby (72h)
- Test minimal veya scale-to-zero
- Runner pause veya sert throttle (CPU quota %25)

**Zorunlu kısıtlar:**
- Test full workload yasak
- Prod stateful migration yasak
- Monitoring stack değişikliği yasak
- ArgoCD prod auto-sync churn yasak
- Ek topology değişikliği yasak

### 5.4 Mode Transitions
- `normal → cutover-freeze`: cutover kararı + preflight PASS
- `cutover-freeze → rollback-window`: T+15m go gate PASS (cutover runbook §8)
- `rollback-window → normal`: T+72h stabil + warm compose shutdown
- `any → emergency rollback`: aşağıdaki sinyallerden herhangi biri:
  - Edge 5xx ratio `> 1%` / 15 dk
  - Gateway p95 latency `> 2s` / 10 dk
  - Authz synthetic fail ardışık 3 kez
  - Kritik fonksiyonel bozulma
  - Stateful servis unhealthy

### 5.5 Yasak Kombinasyonlar
- `rollback-window` + `test full workload`
- `rollback-window` + `runner full concurrency`
- `cutover-freeze` + `legacy compose observability active`
- `prod live` + `shared PG/KC/Vault`
- `prod live` + `moving tag main-stable` (D30 ihlal)
- `prod live` + `belirsiz rollback kapsamı`

## 6. Forward-Extension Paths

Bu karar kapalı sokak değil, genişleme-hazır kontrat:

### 6.1 Second Host Extension
- Prod cluster veya prod stateful tier ikinci hosta taşınabilir
- Network/disk/naming kontratı kolaylaştırır
- D32 mantığı yeni ADR altında forward-extension olarak dönebilir

### 6.2 Vault Replication / Stronger Seal
- İkinci Vault node, replication, managed seal entegrasyonu eklenebilir
- Mevcut policy + path ayrımı geçişi bloke etmez

### 6.3 Cross-Host Storage Tier
- PG + KC disk katmanı ayrı partition / block device / host storage'a taşınabilir
- Bind-mount yolu kasıtlı bu genişlemeye uygun

### 6.4 ArgoCD Multi-Cluster Hardening
- Test cluster registration bugün out-of-band bootstrap
- İleride external identity, secret dağıtımı, cluster bootstrap automation

### 6.5 HA PostgreSQL
- Patroni / Stolon / managed PG / external replication ileride değerlendirilir
- Bugünkü karar shared single instance yerine full isolation'ı önceler

## 7. Resource Contract

### 7.1 Physical Floor (Staging-SW Actual)
| Seviye | CPU | RAM | Disk |
|---|---:|---:|---:|
| **Mevcut (staging-sw)** | 8 vCPU (scalable) | 32 GiB | **400 GB** SSD |
| Önerilen minimum | 12 vCPU | 48 GiB | 500 GB NVMe |
| Rahat operasyon | 16 vCPU | 64 GiB | 1 TB NVMe |

**Not:** 400 GB disk hard floor'un altında; retention + log growth + backup off-host ship disiplini KRİTİK. CPU gerekirse yükseltilebilir (kullanıcı onay 2026-04-19).

### 7.2 Steady-State Budget
| Katman | CPU ceiling | RAM max | Not |
|---|---:|---:|---|
| `platform-prod.slice` | 3.5 core | 14 GiB | Prod workload + ingress + ESO + ArgoCD + monitoring |
| `platform-prod-stateful.slice` | 1.5 core | 6 GiB | En yüksek disk IO önceliği |
| `platform-test.slice` | 1.5 core | 6 GiB | Default scale-to-zero; upper bound |
| `platform-test-stateful.slice` | 0.75 core | 3 GiB | Test kapalıyken durabilir |
| `platform-ci.slice` | 1.5 core | 4 GiB | Runner concurrency `1` |
| `platform-rollback.slice` | 1.5 core | 5 GiB | Default kapalı; 72h penceresinde açılır |
| Host nginx + OS + Docker daemon | 1-1.5 core | 4-5 GiB | Sıkıştırılmamalı |

**Peak + cutover disiplini:**
- `cutover-freeze`: runner throttle (CPU %50), test minimal, legacy observability kapalı
- `rollback-window`: test workload yasak, runner pause/throttle (CPU %25), `platform-rollback.slice` aktif

### 7.3 Systemd Slice Names (Standart)
- `platform-prod.slice`
- `platform-prod-stateful.slice`
- `platform-test.slice`
- `platform-test-stateful.slice`
- `platform-ci.slice`
- `platform-rollback.slice`

**Not:** Reservation değil upper-bound kontrolü. `platform-ci.slice` cutover/rollback penceresinde daha da daraltılır.

## 8. Superseded Decisions

Aşağıdaki kararlar açıkça **superseded** edilmiştir:

- **`PLAN.md D32`** — ayrı fiziksel `staging-sw-2` üzerinde prod cluster ana stratejisi
- **`docs/D32-bootstrap-runbook.md`** — D32 ayrı-host prod kurulum runbook (tarihi bağlam)
- **`bootstrap/install-on-staging-sw-2.sh`** — ayrı sunucu prod bootstrap script

**İşleme:**
- D32 referansları **hemen silinmez**; tarihi bağlam korunur
- İlgili dosyalara `> **SUPERSEDED by ADR-0002** (2026-04-19)` not eklenir
- Sonraki doküman temizliğinde archive/historical statüsüne alınır

## 9. Follow-up Commitments

Bu ADR yalnız yön beyanı değildir; aşağıdaki takip işleri zorunludur:

1. `PLAN.md` ADR-0002 sonrası yeni Faz A-I ile güncellenecek
2. `docs/prod-cutover-runbook-v2.md` yazılacak (atomic cutover adım adım)
3. `docs/day-2-governance.md` yazılacak (backup/rotation/cert/vuln/retention)
4. Backup/restore prova ritmi işletilecek (aylık + çeyreklik full restore)
5. Secret rotation takvimi yazılı ve ölçülebilir olacak
6. Quarterly ADR review yapılacak
7. Operational mode transition log'u tutulacak
8. Legacy compose observability prod live ÖNCE kapatılacak
9. Prod ve test stateful isolation compose şablonları ayrılaştırılacak (`host-compose/{prod,test}/` iki izole klasör)

## 10. Review Cadence

Bu ADR aşağıdaki durumlarda yeniden gözden geçirilir:

- İkinci host alımı
- Kalıcı disk baskısı (%85+) veya memory pressure
- 2 veya daha fazla `rollback-window` aktivasyonu
- Vault / PG / KC major upgrade
- RPO / RTO hedef değişikliği
- Çeyreklik governance review (zorunlu periyodik)

## 11. Referanslar

- Codex thread: `019da70b` (3-turn strategic review, 2026-04-19)
- İlgili ADR: `ADR-0001-service-mesh-rejected.md` (Istio/Linkerd kapsam dışı)
- İlgili kararlar: D6 (host bridge), D17 (scale-to-zero), D20 (host Vault), D29 (3 katman kanıt), D30 (immutable + 72h warm rollback)
- PLAN.md §0 (ADR-0002 sonrası strateji)
- `docs/prod-cutover-runbook-v2.md`
- `docs/day-2-governance.md`
