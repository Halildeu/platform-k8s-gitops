# RUNBOOK – Live Service Schema Cutover

ID: RB-live-service-schema-cutover
Service: backend-runtime
Status: In-Use
Owner: @team/backend

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

`users` veritabanı üstünde canlı schema cutover'ı güvenli şekilde uygulamak ve
aynı akışı gerektiğinde tekrar edilebilir operasyon paketi olarak işletmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- `auth-service`
- `user-service`
- `permission-service`
- `variant-service`
- `core-data-service`
- `api-gateway`

Infra servisleri:
- `postgres-db`
- `discovery-server`
- `vault`
- `keycloak`
- observability container'ları

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Çalıştırma:
  - Ön koşullar:
    - `02-offline-service-schema-cutover.sql` ve rollback SQL mevcut olmalı.
    - `legacy-flyway-cutover-plan` ve `database-isolation-plan` rehearsal geçmiş olmalı.
    - Canlı stack health yeşil olmalı.
    - `permission-service` için
      `PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_USER_TABLE=user_service.users`
      env yüzeyi compose'a bağlanmış olmalı.
  - Operasyon sırası:
    - pre-cutover live lock snapshot al
    - `users` veritabanı için pre-cutover dump üret
    - business servisleri durdur:
      - `api-gateway`
      - `auth-service`
      - `user-service`
      - `permission-service`
      - `variant-service`
      - `core-data-service`
    - `02-offline-service-schema-cutover.sql` uygula
    - target schema env değerleriyle servisleri şu sırada aç:
      - `permission-service`
      - `user-service`
      - `auth-service`
      - `variant-service`
      - `core-data-service`
      - `api-gateway`
    - post-cutover smoke al:
      - health
      - Eureka
      - gateway `401`
      - admin assignment
      - schema inventory
      - Flyway history counts
    - `.env` içine target schema değerlerini kalıcı yaz

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Kanıt paketleri:
  - pre-lock: `backend/.autopilot-tmp/live-schema-cutover/pre`
  - post-lock: `backend/.autopilot-tmp/live-schema-cutover/post`
  - rollback gerekirse: `backend/.autopilot-tmp/live-schema-cutover/rollback`
- İzlenecek sinyaller:
  - `permission-service`, `user-service`, `auth-service`, `variant-service`,
    `core-data-service`, `api-gateway` health durumu
  - Eureka registry
  - `GET /api/v1/companies` sonucu
  - admin assignment sorgusu
  - schema ve sequence inventory
  - Flyway history count snapshot

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Health timeout:
  - Given: Cutover sonrası servisler target schema env ile yeniden ayağa kalkmaktadır.
    When: Herhangi bir kritik servis health timeout verirse.
    Then: rollback SQL uygula, `.env` pre-cutover yedeğini geri koy, business
    servisleri yeniden ayağa kaldır ve rollback lock snapshot al.

- [ ] Arıza senaryosu 2 – Gateway smoke başarısız:
  - Given: Servisler yeniden açılmıştır.
    When: `GET /api/v1/companies` çağrısı `401` yerine `404` veya `5xx`
    dönerse.
    Then: registry ve downstream health zincirini kontrol et; kritik kopukluk
    varsa rollback akışını tetikle.

- [ ] Arıza senaryosu 3 – Admin assignment kaybı:
  - Given: `permission-service` ve `user-service` target schema altında
    çalışmaktadır.
    When: `admin@example.com` veya `admin1@example.com` için aktif `ADMIN`
    assignment bulunamazsa.
    Then: `permission-service` bootstrap ve cross-schema query yüzeyini kontrol
    et; veri doğrulaması düzelmezse rollback uygula.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Bu runbook canlı `users` veritabanını service-owned schema yapısına taşır.
- Başarı kriteri:
  - tüm kritik servisler `healthy`
  - Eureka kayıtları tam
  - gateway sonucu `401 Unauthorized`
  - admin assignment aktif
  - 27 runtime tablo hedef schema'lar altında
  - `.env` target schema değerleri kalıcı yazılmış

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Canlı runner:
  - `backend/scripts/ops/run-live-service-schema-cutover.sh`
- Live lock snapshot helper:
  - `backend/scripts/ops/capture-live-schema-cutover-lock.sh`
- Plan:
  - `docs/02-architecture/runtime/legacy-flyway-cutover-plan.md`
  - `docs/02-architecture/runtime/database-isolation-plan.md`
