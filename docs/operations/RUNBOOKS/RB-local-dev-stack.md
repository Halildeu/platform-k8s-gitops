# RUNBOOK – Local Dev Stack Canonical Start

ID: RB-local-dev-stack  
Service: local-dev-stack  
Status: Draft  
Owner: Platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Repo icindeki coklu baslatma yuzeyleri arasinda tek resmi baslangic noktasini tanimlamak.
- Lokal gelistirme icin "hangi komuttan baslamaliyim?" sorusunun kalici hafiza kaydini tutmak.
- Drift ureten stale entrypoint'leri resmi akistan ayirmak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Repo: `dev`
- Ortam: lokal gelistirme
- Kapsam:
  - backend compose full stack
  - backend hybrid debug stack
  - web full/core/selective stack
  - test icin gecici frontend stack wrapper'lari
- Resmi varsayilan akış:
  - backend compose wrapper: `backend/scripts/run-compose-stack.sh`
  - web full profile: `web/package.json -> start -> web/scripts/health/run-dev-servers.sh --profile full`
- Basari kaniti:
  - `.cache/runtime_guard/*.json` session kayitlari
  - `.cache/reports/*runtime_guard*.json` guard raporlari

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Resmi varsayilan baslangic noktasi:

```bash
cd backend
./scripts/run-compose-stack.sh

cd ../web
pnpm start
```

- Neden bu akış resmi varsayilan?
  - Backend tarafinda en genis kapsami veren yol budur.
  - Web tarafinda `start` komutu `full` profile acarak `shell + suggestions + ethic + users + access + audit + reporting + schema-explorer + cockpit` setini baslatir.
  - Bu kombinasyon lokal calisma sirasinda dogrulanmis en genis stack'tir.

- Backend guard davranisi:
  - Web baslangici backend health + user + theme-registry + audit rotalarini blocking olarak bekler.
  - `roles` ve `permissions` rotalari Zanzibar gecisi tamamlanana kadar advisory olarak raporlanir.
  - Advisory uyarisinda start devam eder; blocking hata varsa start durur.

- Ikincil akışlar:
  - Backend debug/hybrid:

```bash
cd backend
./scripts/run-services.sh
```

  - Bu yol Spring servislerini Maven ile ayri surecler olarak acar; varsayilan full local stack degildir.

  - Test/ephemeral frontend stack:

```bash
cd web
node ./scripts/ops/run-with-frontend-stack.mjs --stack auth-business-routes -- <target-komut>
```

  - Bu yol test wrapper'idir; kalici gelistirici baslangic noktasi degildir.

- Durdurma:
  - Web:

```bash
cd web
bash ./scripts/health/stop-dev-servers.sh
```

  - Backend compose:

```bash
cd backend
docker compose down --remove-orphans
```

  - Backend hybrid:

```bash
cd backend
STOP_INFRA=1 ./scripts/stop-services.sh
```

- Deprecated compatibility yuzeyleri:
  - `web/package.json -> dev:all:raw`
  - `web/package.json -> start:raw`
  - `web/package.json -> dev:frontend`
  - `web/package.json -> dev:full`
  - `backend/scripts/start-local.sh`

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Backend compose session:
  - `.cache/runtime_guard/backend_compose_session.v1.json`
- Backend compose guard:
  - `.cache/reports/backend_compose_runtime_guard.v1.json`
- Backend hybrid session:
  - `.cache/runtime_guard/backend_start_session.v1.json`
- Backend hybrid guard:
  - `.cache/reports/backend_runtime_guard.v1.json`
- Web session:
  - `.cache/runtime_guard/web_start_session.v1.json`
- Web guard:
  - `.cache/reports/web_runtime_guard.v1.json`
- Web backend wait raporu:
  - `.cache/reports/web_backend_guard_wait.v1.json`
- Web loglari:
  - `web/logs/*.log`
- Temel portlar:
  - backend gateway: `8080`
  - shell: `3000`
  - suggestions: `3001`
  - ethic: `3002`
  - users: `3004`
  - access: `3005`
  - audit: `3006`
  - reporting: `3007`
  - schema-explorer: `3008`
  - cockpit: `8790`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Ariza senaryosu 1 – web start backend guard beklemesinde takiliyor
  - Given: `pnpm start` veya `run-dev-servers.sh --profile full` calisiyor
  - When: baslangic, backend guard bekleme asamasinda kalıyor veya `web_backend_guard_wait.v1.json` FAIL uretiyor
  - Then:
    - `.cache/reports/web_backend_guard_wait.v1.json` dosyasini ac.
    - Once `failed_blocking_live_checks` alanini kontrol et.
    - Yalniz `failed_advisory_live_checks` doluysa start devam etmelidir; bu durum ayri migration isi olarak ele alinmalidir.
    - `failed_blocking_live_checks` doluysa backend/runtime drift'i kapatmadan resmi akisa devam etme.

- [ ] Ariza senaryosu 2 – portlar dolu / eski surecler yeni stack'i bozuyor
  - Given: yeni baslangicta bazi web servisleri dinlemiyor veya eski log/session gorunuyor
  - When: `3000-3008` ya da `8790` portlarinda stale surec var
  - Then:
    - `bash web/scripts/health/stop-dev-servers.sh` ile tum web portlarini temizle.
    - Compose kullaniyorsan `cd backend && docker compose down --remove-orphans` calistir.
    - Resmi varsayilan akisi bastan uygula.

- [ ] Ariza senaryosu 3 – eski dokuman/surface yanlis komuta yonlendiriyor
  - Given: `dev:full` veya `start:raw` gibi deprecated bir komut deneniyor
  - When: komut compatibility alias'i uzerinden warning basiyor
  - Then:
    - Bu runbook'a geri don.
    - Baslangici yalnizca "backend compose + web full" akisi ile yap.
    - Gerekirse stale referansi ayri doc cleanup isi olarak isaretle.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Repo icindeki tek resmi baslangic noktasi: `backend/run-compose-stack + web/pnpm start(full)`.
- `run-services.sh` yalnizca debug/hybrid backend akisidir.
- `run-with-frontend-stack.mjs` yalnizca test icin gecici stack wrapper'idir.
- Bu dokuman repo icindeki "baslangic memory" kaydi olarak kabul edilir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Backend README: `backend/README.md`
- Web README: `web/README.md`
- Web contributing: `web/CONTRIBUTING.md`
- Backend compose wrapper: `backend/scripts/run-compose-stack.sh`
- Backend hybrid wrapper: `backend/scripts/run-services.sh`
- Web runtime wrapper: `web/scripts/health/run-dev-servers.sh`
- Test stack wrapper: `web/scripts/ops/run-with-frontend-stack.mjs`
