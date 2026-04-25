# SLO-SLA

Bu doküman, servis seviye hedefleri (SLO) ve anlaşmalar (SLA) için kullanılır.
Amaç: Kritik backend/ops bileşenleri için hedeflenen kalite seviyelerini
belirlemek ve monitoring/runbook dokümanları ile hizalamaktır.

-------------------------------------------------------------------------------
1. GENEL İLKELER
-------------------------------------------------------------------------------

- SLO’lar, servislerin beklenen davranışını ve hata toleransını tanımlar.
- SLA’lar, dış paydaşlara verilen sözleri (uptime, cevap süresi) temsil eder.
- Ölçümler, monitoring sisteminde (Prometheus/Grafana vb.) tanımlı metrikler
  üzerinden izlenir.

Detaylı monitoring rehberi için:
- `docs/04-operations/MONITORING/MONITORING-backend-services.md`

-------------------------------------------------------------------------------
2. BACKEND SERVİSLERİ İÇİN ÖRNEK SLO’LAR
-------------------------------------------------------------------------------

### 2.1 User Service

- Latency:
  - Hedef: `http_server_requests_seconds_bucket{service="user-service"}`  
    p95 < 500ms (normal iş yükü koşullarında).
- Hata Oranı:
  - Hedef: 5xx oranı < %1 (30 dakikalık pencere).

### 2.2 Permission Service

- Latency:
  - Hedef: `http_server_requests_seconds_bucket{service="permission-service"}`  
    p95 < 700ms.
- Hata Oranı:
  - Hedef: 5xx oranı < %1 (30 dakikalık pencere).

-------------------------------------------------------------------------------
3. GÜVENLİK VE KİMLİK DOĞRULAMA BİLEŞENLERİ
-------------------------------------------------------------------------------

### 3.1 Keycloak

- Oturum Açma Başarı Oranı:
  - Hedef: `keycloak_login_success_rate` ≥ %99.
- Uygulama Erişilebilirliği:
  - Hedef: Kimlik doğrulama hatası nedeniyle başarısız istek oranı < %1.

İlgili runbook:
- `docs/04-operations/RUNBOOKS/RB-keycloak.md`

### 3.2 Vault

- Sağlık Durumu:
  - Hedef: `vault_health_status == 0` (healthy).
- Hata Oranı:
  - Hedef: `vault_request_error_rate` düşük ve trend olarak stable.

İlgili runbook:
- `docs/04-operations/RUNBOOKS/RB-vault.md`

-------------------------------------------------------------------------------
4. ÖN YÜZ VE ACCESS MODÜLLERİ
-------------------------------------------------------------------------------

### 4.1 MFE Access

- Time-To-First-Action (TTFA):
  - Hedef: `fe.access.ttfa_p95` < 8s.
- Grid Latency:
  - Hedef: `fe.access.grid_fetch_latency_p95` < 2.5s.
- Hata Oranı:
  - Hedef: `fe.access.client_error_rate` < %2.

İlgili runbook:
- `docs/04-operations/RUNBOOKS/RB-mfe-access.md`

-------------------------------------------------------------------------------
5. DEĞERLENDİRME VE İHLAL DURUMLARI
-------------------------------------------------------------------------------

- SLO ihlali tespit edildiğinde:
  - İlgili metrik/dashboards `MONITORING-backend-services` rehberine göre
    incelenir.
  - Gerekirse ilgili RB-* runbook devreye alınır.
- SLO’lar belirli periyotlarla gözden geçirilir ve iş ihtiyaçlarına göre
  güncellenir.

