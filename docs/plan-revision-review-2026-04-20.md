# Plan Revision Review - 2026-04-20

Bu not, `codex/origin-main-plan-review` branch'i uzerinde `origin/main@f0aa766` baz alinarak hazirlandi.

Amac:

- guncel HEAD uzerinde canonical karar/drift noktalarini ayirmak
- `PLAN.md`, `README.md` ve `docs/state/current-state.md` icin net revizyon backlog'u cikarmak
- eski snapshot ile guncel karar setini karistirmamayi saglamak

## Calisma Zemini

- Branch: `codex/origin-main-plan-review`
- Base: `origin/main`
- Lokal ek dosyalar korundu:
  - `docs/semantic-architecture.md`
  - `docs/semantic-architecture.mmd`
  - `docs/semantic-architecture.svg`

## Ana Hukum

Planin omurgasi dogru, ama dokuman zinciri henuz tam net degil. En buyuk problem teknik eksik degil; `active contract`, `historical path` ve `current live state` ayni anlatim yuzeyinde birbirine karisiyor.

Bu nedenle repo icin ilk cleanup isi:

1. active karar setini sabitlemek
2. stale/historical akisleri ekten once ana govdeden ayirmak
3. `current-state` ile `PLAN` arasinda otorite sirasini acik yazmak

## Revision Findings

### 1. D32 same-host karariyla celisiyor ve aktif karar gibi gorunuyor

Sorun:

- `PLAN.md` basinda D32 `SUPERSEDED` deniyor.
- Ama ayni dosyada D32 tekrar aktif karar olarak yaziliyor.
- Hatta staging-sw-2 bootstrap checklist'i aktif is akisi gibi duruyor.

Kanit:

- `PLAN.md:15-19`
- `PLAN.md:106`
- `PLAN.md:184-185`
- `PLAN.md:205-260`
- `docs/adr/0002-single-host-dual-cluster.md:11-14`
- `docs/adr/0002-single-host-dual-cluster.md:26-30`

Etkisi:

- Okuyucu ayni anda hem "same-host dual-cluster ana yol" hem de "staging-sw-2 aktif yol" sonucu cikariyor.
- Faz G/H ve cutover stratejisi gereksiz sekilde iki farkli fiziksel topolojiye ayriliyor.

Oneri:

- D32 aktif karar tablosundan cikarilmali.
- D32 sadece `historical / forward-extension appendix` olarak tutulmali.
- `install-on-staging-sw-2.sh`, `docs/D32-bootstrap-runbook.md` ve ilgili checklist'ler "ana yol degil" etiketiyle tasinmali.

### 2. PLAN icindeki seviye/faz anlatimi eski akisi tasiyor

Sorun:

- `PLAN.md` icinde S0-S4 seviye anlatisi var.
- Bu blok, yeni `docs/state/current-state.md` icindeki Faz 10-13 recovery planiyla uyumsuz.
- S4 satiri halen D32 hardware + atomic switch uzerinden konusuyor.

Kanit:

- `PLAN.md:118-140`
- `PLAN.md:125`
- `docs/state/current-state.md:64-73`

Etkisi:

- Repo iki ayri roadmap dilinde konusuyor:
  - eski S0-S4 / D32 dili
  - yeni Faz 10-13 / truth recovery dili

Oneri:

- `PLAN.md` icindeki S0-S4 bolumu ya kaldirilmali ya da `historical status snapshot` diye acikca isaretlenmeli.
- Guncel operasyonel roadmap icin `docs/state/current-state.md` tek referans olmali.
- Alternatif olarak Faz 10-13 dogrudan `PLAN.md` icine alinmali ve tek roadmap dili kullanilmali.

### 3. `current-state` kirik referans tasiyor

Sorun:

- `current-state` icinde `docs/session-logs/...` referansi var.
- Repo agacinda `docs/session-logs/` klasoru yok.

Kanit:

- `docs/state/current-state.md:66`
- `docs/state/current-state.md:95`
- repo klasorleri: `docs`, `docs/adr`, `docs/state`

Etkisi:

- Canonical state dokumani olmayan artifact'lara isaret ediyor.
- "Bu oturumda eklenecek" dili kalici ana dokumanda duruyor.

Oneri:

- Ya `docs/session-logs/` ve ilgili dosyalar gercekten eklenmeli
- Ya da `current-state` icinden bu referanslar kaldirilip mevcut dokumanlara baglanmali

### 4. `current-state` test hazirligini fazla iyimser anlatiyor

Sorun:

- `current-state` test-k8s icin "login canli" diyor.
- Ayni dokuman frontend pod'u belirli bir GHCR image/digest ile tarif ediyor.
- Canli kontrolte test cluster'da `openfga-0` hala `CrashLoopBackOff`.
- Firing critical alert'ler mevcut.
- Frontend deployment image'i de beklendigi gibi GHCR artifact degil.

Kanit:

- `docs/state/current-state.md:16-20`
- `docs/state/current-state.md:31`
- canli kontrol:
  - `kubectl --context k3d-test -n platform-test get pods`
  - `openfga-0 0/1 CrashLoopBackOff`
  - `kubectl ... get deploy frontend -o jsonpath=...`
  - sonuc: `nginx:1.27-alpine`
  - Prometheus alerts:
    - `OpenFGADown` critical
    - `BackupExporterDown` critical

Etkisi:

- `test-k8s=75` gibi skorlarin anlami bulaniyor.
- "login canli" ile "gate'e hazir" ayni sey gibi okunuyor.

Oneri:

- `current-state` dili daha daraltilmali:
  - "OIDC discovery canli"
  - "frontend render var"
  - "authz plane degrede"
- `test-k8s` sayaci altina blocker alert durumu acik eklenmeli.

### 5. README hala stale/historical path'i spotlight ediyor

Sorun:

- README mimari ozette same-host ana yolu soyluyor.
- Ama dizin yapisinda `host-compose/data/` yaziyor; gercekte `postgres/`, `keycloak/`, `vault/`, `proxy/` var.
- Ayrica runbook tablosunda D32 bootstrap runbook aktif gibi sunuluyor.

Kanit:

- `README.md:15-18`
- `README.md:45-47`
- `README.md:71-77`
- gercek tree:
  - `host-compose/postgres/...`
  - `host-compose/keycloak/...`
  - `host-compose/vault/...`
  - `host-compose/proxy/...`

Etkisi:

- Yeni gelen biri README'den stale topoloji okuyabiliyor.
- Repo siniri ve ana yol ilk ekranda net verilmiyor.

Oneri:

- README dizin yapisi guncellenmeli.
- `docs/state/current-state.md` README'de ilk seviye link olarak eklenmeli.
- D32 runbook "historical / superseded" etiketiyle tasinmali.

### 6. Otorite sirasi yazili degil

Sorun:

- `PLAN.md`, `README.md`, `docs/state/current-state.md`, handoff belgeleri ve ADR ayni seviyede gorunuyor.
- Hangi belge karar kaynagi, hangisi canli snapshot, hangisi tarihce tam acik degil.

Kanit:

- `README.md:71-72`
- `docs/state/current-state.md:6`
- `docs/state/current-state.md:91-96`

Etkisi:

- Review sirasinda "master plan mi", "canli truth mu", "historical handoff mu" sorusu tekrar aciliyor.

Oneri:

- Repo icin canonical precedence acik yazilmali:
  1. ADR
  2. current-state
  3. PLAN
  4. runbook
  5. handoff / historical log

### 7. Cutover contract daha acik ayrilmali

Sorun:

- Atomic cutover karari artik dogru yaziliyor.
- Ama `prod preflight`, `dark validation`, `T+15 gate`, `T+72 rollback window` tek yerde toplanmis degil.
- Hedef kontrat ile bugunku gercek rollback durumu da farkli.

Kanit:

- `PLAN.md:182`
- `PLAN.md:198`
- `docs/state/current-state.md:37-45`

Etkisi:

- Hedef durum ile bugunku yetenek karisabiliyor.

Oneri:

- Faz G bir runbook summary yerine explicit gate listesine donusturulmeli:
  - prod dark validation
  - edge switch
  - T+15 go gate
  - T+72 rollback window
  - decommission prerequisite

## Onerilen Cleanup Sirasi

1. `README.md`
   - canonical belge zinciri
   - dizin yapisi
   - stale D32 spotlarini temizleme
2. `PLAN.md`
   - D32'yi appendix'e it
   - S0-S4 blokunu kaldir veya tarihsel etiketle
   - Faz G/H/I kapilarini netlestir
3. `docs/state/current-state.md`
   - kirik `session-logs` referanslarini temizle
   - test-k8s ve rollback dilini daralt
4. sonra yeni `docs/semantic-architecture.*` dokumanlarini canonical referans olarak bagla

## Sonraki Pratik Adim

Bu review'dan sonra en dogru implementasyon isi:

- `README.md` + `PLAN.md` + `docs/state/current-state.md` uzerinde tek PR/branch cleanup
- amac: repo'yu "tek ana yol + tek current truth + acik historical appendix" modeline oturtmak
