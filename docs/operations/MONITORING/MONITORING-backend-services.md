# MONITORING-backend-services – Backend Servis Monitoring Rehberi

Bu doküman, backend servisleri için temel monitoring prensiplerini, metrik
örneklerini ve runbook bağlantılarını özetler. Amaç: Incident anında hangi
metriklere bakılacağını, hangi runbook’un devreye alınacağını ve SLO/SLA
hedeflerinin nasıl takip edileceğini netleştirmektir.

-------------------------------------------------------------------------------
1. KAPSAM VE AMAÇ
-------------------------------------------------------------------------------

- Kapsam:
  - `user-service`, `permission-service`, `auth-service`, `variant-service` vb.
    HTTP API servisleri.
  - Vault, Keycloak ve MFE access gibi kritik bileşenler için temel metrikler.
- Amaç:
  - SLO/SLA hedefleri ile uyumlu metrik seti tanımlamak.
  - Runbook’lar (RB-*) ile monitoring arasında çift yönlü referans kurmak.

İlgili üst seviye hedefler için:
- `docs/04-operations/SLO-SLA.md`

-------------------------------------------------------------------------------
2. TEMEL METRİK TÜRLERİ
-------------------------------------------------------------------------------

- Uygulama Metriği:
  - İstek sayısı, hata oranı, latency (p95/p99).
- Altyapı Metriği:
  - CPU, bellek, disk, connection pool doluluk oranı.
- Kullanıcı Deneyimi Metriği:
  - Önemli endpoint’ler için başarı oranı, timeout oranı.

-------------------------------------------------------------------------------
3. ÖRNEK METRİKLER VE SLO İLİŞKİSİ
-------------------------------------------------------------------------------

- `http_server_requests_seconds_bucket{service="user-service"}`  
  - Hedef: p95 latency < 500ms (SLO-SLA içinde tanımlanmalıdır).
- `http_server_requests_seconds_bucket{service="permission-service"}`  
  - Hedef: p95 latency < 700ms.
- `http_server_requests_seconds_count{status=~"5.."}`  
  - Hedef: 5xx oranı < %1.
- `vault_health_status`  
  - Hedef: `status == 0` (healthy).
- `keycloak_login_success_rate`  
  - Hedef: ≥ %99.

Bu hedefler, `SLO-SLA.md` dokümanında servis veya domain bazında detaylandırılmalıdır.

-------------------------------------------------------------------------------
4. RUNBOOK İLİŞKİLERİ
-------------------------------------------------------------------------------

Monitoring rehberi, aşağıdaki runbook’larla birlikte düşünülmelidir:

- RB-vault:
  - Dosya: `docs/04-operations/RUNBOOKS/RB-vault.md`
  - İlişkili metrikler:
    - `vault_health_status`
    - `vault_request_error_rate`
- RB-keycloak:
  - Dosya: `docs/04-operations/RUNBOOKS/RB-keycloak.md`
  - İlişkili metrikler:
    - `keycloak_login_success_rate`
    - `keycloak_request_latency_p95`
- RB-mfe-access:
  - Dosya: `docs/04-operations/RUNBOOKS/RB-mfe-access.md`
  - İlişkili metrikler:
    - `fe.access.ttfa_p95`
    - `fe.access.client_error_rate`
- RB-feature-flags:
  - Dosya: `docs/04-operations/RUNBOOKS/RB-feature-flags.md`
  - İlişkili metrikler:
    - Flag rollout sonrası error rate ve latency değişimleri.

-------------------------------------------------------------------------------
5. İNCIDENT AKIŞI (ÖZET)
-------------------------------------------------------------------------------

1. Alarm tetiklendiğinde:
   - İlgili dashboard ve metrikler üzerinden problemin tipini belirle.
2. Etkilenen servis/bileşen için ilgili RB-* runbook’un “Incident Senaryoları”
   bölümünü uygula.
3. Gerekirse:
   - Feature flag fallback için RB-feature-flags’e bak.
   - Access UI sorunlarında RB-mfe-access’i kullan.
   - Auth/JWT sorunlarında RB-keycloak + STORY-0002/TP-0002 zincirine bak.
4. Incident sonrası:
   - İlgili SLO/SLA ihlallerini not et ve gerekirse SLO-SLA.md’yi güncelle.

-------------------------------------------------------------------------------
6. LİNKLER
-------------------------------------------------------------------------------

- SLO/SLA hedefleri: `docs/04-operations/SLO-SLA.md`  
- Runbook’lar:
  - `docs/04-operations/RUNBOOKS/RB-vault.md`
  - `docs/04-operations/RUNBOOKS/RB-keycloak.md`
  - `docs/04-operations/RUNBOOKS/RB-mfe-access.md`
  - `docs/04-operations/RUNBOOKS/RB-feature-flags.md`

