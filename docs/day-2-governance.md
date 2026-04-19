# Day-2 Governance — Backup, Rotation, Cert, Vulnerability, Retention

> **Scope:** ADR-0002 sonrası prod/test full isolation işletim kontratı
> **Review cadence:** Aylık + çeyreklik + olay-sonrası
> **Not:** Bu doküman operasyon ritmini tanımlar; runbook yerine geçmez

## 1. Backup / Restore Drill

### 1.1 Cadence Tablo
| Konu | Prod | Test |
|---|---|---|
| PG logical dump | Günlük | Günlük |
| PG base backup + WAL | Günlük / sürekli WAL | Opsiyonel (en az günlük dump) |
| Vault snapshot (raft) | Günlük | Günlük |
| Keycloak realm export | Haftalık | Haftalık |
| Aylık prod backup review | Zorunlu | Önerilen |
| Full restore prova | Çeyreklik | Çeyreklik |

### 1.2 PostgreSQL

**Politika:**
- Prod PG üçlü model:
  - Base backup
  - WAL archive (continuous)
  - Günlük logical dump
- Retention:
  - Günlük logical dump: **14 gün**
  - Haftalık base backup: **4 hafta**
  - WAL: restore zinciri sağlayacak kadar
- **Off-host ship ZORUNLU** (400 GB disk darlığı — ADR-0002 §7.1)

**Doğrulama:**
- Her backup sonrası checksum + boyut kontrolü
- Ayda 1 restore dry-run
- Çeyrekte 1 tam restore prova

**Başarı kriteri:**
- RPO ≤ 24 saat
- Restore zinciri tek operatörün belleğine bağlı değil
- Prod/test backup KARIŞMAZ (ayrı klasör: `/srv/backup/{prod,test}/postgres`)

### 1.3 Vault

**Politika:**
- Günlük raft snapshot (her Vault ayrı)
- Recovery key materyali ayrı + kontrollü saklanır
- Prod/test snapshot AYRI

**Retention:**
- Günlük snapshot: **14 gün**
- Haftalık archive: **4 hafta**
- Off-host kopya: ZORUNLU

**Doğrulama:**
- Çeyrekte 1 test restore (prod-like)
- Policy/role/KV path smoke sonrası

### 1.4 Keycloak

**Politika:**
- Haftalık realm export (JSON)
- DB snapshot ile birlikte saklanır
- Prod/test ayrı klasör: `/srv/backup/{prod,test}/keycloak`

**Retention:**
- Export: **8 hafta**
- DB snapshot retention PG politikasına bağlı

**Doğrulama:**
- Restore sonrası client/realm/token smoke

## 2. Secret Rotation Takvimi

### 2.1 Rotation Tablosu
| Secret / Credential | Prod | Test | Not |
|---|---|---|---|
| Vault AppRole `secret_id` (ESO) | **30 gün** | **14 gün** | automation path |
| GHCR PAT (image pull) | Çeyreklik | Çeyreklik | read-only scope |
| Keycloak confidential client secret | Çeyreklik | Çeyreklik | smoke/service clients |
| Vault admin token | 90 gün | 90 gün | root token bootstrap sonrası revoke |
| JWT signing keys | Yılda 1 | Yılda 1 | overlapping window |
| SSH deploy key review | Çeyreklik | Çeyreklik | rotate değil, review |

### 2.2 Rotation Kuralları
- **Prod ve test hiçbir secret PAYLAŞMAZ** (ADR-0002 §3.2 full isolation)
- Rotation flow: yeni secret üret → consumer update → eski revoke
- JWT key rotation overlap window (eski + yeni aynı anda kısa süre verify edilebilir)
- Rotation log tutulur (`docs/ops-rotation.log`)

### 2.3 Başarı Kriteri
- Rotation sonrası smoke PASS
- ESO sync PASS
- Consumer restart/reload kontrollü
- Eski credential REVOKE edildi (teyit)

## 3. Certificate Renewal

### 3.1 Ana Politika
- Ana yol: **Sectigo wildcard manuel renewal** (`*.acik.com`)
- Yardımcı yol: `cert-manager + Let's Encrypt` (DRAFT, prod-ready DEĞİL)
- Renewal sorumluluğu kişiye bağlı değil, takvime bağlı

### 3.2 Renewal Takvim (T = expiry)
| Eşik | Aksiyon |
|---|---|
| **T-90** | Uyarı doğrulama (expiry alert aktif mi) |
| **T-60** | Renewal hazırlık (CSR şablon + DNS kontrolü) |
| **T-30** | CSR / Sectigo sipariş |
| **T-14** | Yeni cert teslim + chain + SAN doğrulama |
| **T-7** | Host mount + ingress smoke (testai öncelik) |
| **T-3** | Prod apply penceresi |
| **T+1** | Renewal sonrası doğrulama + expiry alert reset |

### 3.3 Başarı Kriteri
- `testai.acik.com` + `ai.acik.com` yeni cert ile PASS
- Expiry alert reset
- Chain ve SAN doğrulandı

## 4. Image Vulnerability Management

### 4.1 CI Politikası
`platform-ssot` repo CI'ya scanner gate eklenir:
- Önerilen: **Trivy** veya **Grype**
- Çalışma noktaları:
  - PR build (changed service)
  - Main branch build
  - Haftalık full repository scan

### 4.2 Gate Kuralları
- `CRITICAL` bulgu → PR **fail**
- `HIGH` bulgu → raporlanır; runtime-image ise sahip atama zorunlu
- Base image drift haftalık rapor
- Ignore list **kısa ömürlü + tarihli** olmak zorunda

### 4.3 Başarı Kriteri
- Prod'a çıkan her image en az bir scanner'dan geçmiş
- Scanner sonuçları artifact olarak saklanır (30 gün retention)
- İstisnalar süreli + kayıtlı

## 5. Storage Growth Monitoring (400 GB Disk)

### 5.1 Disk Eşikleri (Staging-SW 400 GB)
| Eşik | Disk Kullanım | Durum | Aksiyon |
|---|---|---|---|
| `< 75%` | `< 300 GB` | Normal | İzleme |
| `75-85%` | `300-340 GB` | **Warning** | Temizlik + growth review |
| `85-90%` | `340-360 GB` | **Critical** | Release/soak/rollback risk değerlendirmesi |
| `> 90%` | `> 360 GB` | **Blocker** | Yeni cutover/deploy DURDUR |

### 5.2 İzlenecek Alanlar
- `/srv/platform/stateful/prod` (PG + KC + Vault prod data)
- `/srv/platform/stateful/test` (PG + KC + Vault test data)
- `/srv/backup/{prod,test}` (backup retention)
- Prometheus TSDB (`/var/lib/prometheus` veya k3d PVC)
- Loki storage (prod only)
- Docker image cache (`/var/lib/docker`)
- Container log büyümesi (`/var/lib/docker/containers/*/json.log`)

### 5.3 Başarı Kriteri
- Disk pressure sürpriz değil, önceden görünür (alert)
- Retention + cleanup takvimi yazılı + çalışıyor
- 400 GB aşırı zorlanıyorsa `12/48/1TB` upgrade kararı GECİKMEZ (ADR-0002 §10 review trigger)

## 6. Observability Retention

### 6.1 Hedef Retention (400 GB Disk Kısıtı)
| Bileşen | Hedef | Not |
|---|---|---|
| Prometheus | **14-30 gün** | 400 GB disk üstünde 30 gün agresif; başlangıç 14 gün + haftalık review |
| Loki | **7-14 gün** | Başlangıç 7 gün |
| Tempo | **3-7 gün** | Başlangıç 3 gün |

**Not:** ADR-0002 §7.1 önerilen minimum `12/48/1TB` üzerinde retention eğrisi daha rahat. 400 GB hard floor'da retention ilk ay **haftalık gözden geçirilir**.

### 6.2 Topoloji Kuralları (ADR-0002 §3.8)
- Prod kube-prometheus-stack = ana gözlem hub
- Test cluster minimal metrics → `remote_write` prod Prom
- Grafana tek instance prod
- Legacy compose observability prod live ÖNCE kapalı

## 7. Quarterly Governance Review

Her çeyrek zorunlu gözden geçirme:

1. **ADR-0002 hâlâ doğru mu** (assumptions, constraints, forward-extension)
2. **Operational mode transition log'ları** (`docs/ops-mode-transition.log`)
3. **Rollback-window sayısı + nedenleri** (2+ aktivasyon → ADR revizyon trigger)
4. **Backup/restore prova sonuçları** (aylık + çeyreklik)
5. **Secret rotation uyumu** (takvimden sapma var mı)
6. **Cert renewal takvimi** (T-90 alert tetiklendi mi)
7. **Vulnerability backlog** (CRITICAL/HIGH adedi + trend)
8. **Storage growth eğrisi** (400 GB disk + retention)
9. **Incident postmortem aksiyonları** (tamamlanan vs bekleyen)

### 7.1 Review Çıktıları
- Güncellenmiş risk listesi
- Gecikmiş aksiyon listesi
- Gerekirse ADR revizyon kararı
- Capacity uplift gereksinimi (12/48/1TB hardware upgrade?)

## 8. Incident Postmortem Template

```markdown
# Incident <YYYY-MM-DD-NN> — <başlık>

## Timeline
- Detection: <timestamp, source>
- Triage: <operator, action>
- Rollback (if any): <timestamp, method>
- Resolution: <timestamp>
- Post-verify: <smoke, metrics reset>

## Root Cause
<what broke, why>

## Corrective Actions
- [ ] Immediate fix
- [ ] Runbook update
- [ ] Alert tuning
- [ ] Monitoring gap kapatılsın
- [ ] ADR revision (gerekirse)

## Operational Mode
- Before: <normal|cutover-freeze|rollback-window>
- During: <emergency-rollback?>
- After: <normal>

## Referanslar
- ADR-0002
- Runbook: docs/prod-cutover-runbook-v2.md
- Grafana: <link>
```

## 9. Referanslar
- `docs/adr/0002-single-host-dual-cluster.md` (ADR-0002)
- `PLAN.md` §0 (ADR-0002 sonrası strateji)
- `docs/prod-cutover-runbook-v2.md` (atomic cutover)
- Eski: `docs/S5-*` runbook seti (historical Day-2 referansları)
