# RB — ATS Interview-Evidence backend'i testai'de (ATS-0019 39d)

> Kapsam: **test cluster (k3d-test / platform-test)** — prod'a HİÇBİR adım uygulanmaz.
> Plan + acceptance matrisi: Codex thread `019f4c6c` (3-iter AGREE) + `019f50b7`.
> Kanonik sınır: motor verisi SENTETİK (ATS-0016); gerçek aday verisi G0=GO'ya bağlı.
> WORM iddiası test-PG'de YAPILMAZ (yalnız uygulama-seviyesi append-only guard).
> Canlı test gerçeği: `ats_app` bugün test `ats` veritabanı/şema/tablolarının sahibidir; migration yorumlarındaki ayrı-owner/least-privilege hedefi testte sağlanmış sayılmaz. Ayrı Flyway migrator + runtime rolü ve ownership transferi prod/gerçek PII öncesi P0 kapısıdır: `Halildeu/ats#176`.

## Bileşenler

| Parça | Yer |
|---|---|
| İmaj | `ghcr.io/halildeu/ats-app-boot` (public; ats repo `image-push.yml` — trivy CRITICAL fail-closed push-öncesi; `digest:` log satırı AUTHORITY) |
| Base manifest | `kustomize/base/apps/ats-interview-evidence/` (test activation overlay üzerinden kullanılır) |
| Aktivasyon | `kustomize/overlays/test/activation/ats-interview-evidence/` (Faz 25 #2615: test Argo-root içinde, self-heal aktif) |
| Provisioning | `scripts/ats/provision-test-pg-vault.sh` + `scripts/ats/transition-test-model-governance.sh` + `scripts/ats/provision-test-keycloak.sh` (idempotent; staging-sw'de koşulur; secret basmaz) |

## Akış (tetik → adımlar)

1. **PG + Vault** (~30 sn): `scp scripts/ats/provision-test-pg-vault.sh staging-sw:/tmp/ && ssh staging-sw bash /tmp/provision-test-pg-vault.sh`
   - Beklenen: `PG: ats_governance_writer NOLOGIN role OK` + `PG: ats_app role + ats db OK` + `VAULT keys: ['ATS_DB_PASSWORD','ATS_DB_URL','ATS_DB_USERNAME']` + `PG login test: ats_app@ats`
   - Not: her koşum DB parolasını ROTATE eder (Vault ile atomik) — pod restart gerektirir.
   - Flyway V4 `permission denied to create role` ile durmuş mevcut test DB'si için parolayı/Vault'u değiştirmeyen hedefli önkoşul: `ssh staging-sw bash /tmp/provision-test-pg-vault.sh --roles-only`. Bu yalnız `ats_governance_writer` rolünü idempotent oluşturur/doğrular, mevcut `ats_app` rolündeki admin-attribute drift'ini fail-closed reddeder ve `ats_app` rolüne `CREATEROLE` **vermez**. Tek başına ürün recovery'sini tamamlamaz: başarısız Flyway satırı olmadığı kanıtlandıktan sonra GitOps rollout V4→V6'yı uygular; ardından exact merged checkout'tan `transition-test-model-governance.sh` append ve en son digest/Ready + V4/V5/V6 doğrulaması gerekir. Bu tam sıra aşağıdaki canonical self-hosted workflow'dadır; manuel yol her aynı kapıyı ayrıca sağlamadıkça kullanılmaz. Başarısız history satırı varsa otomatik `repair` yapılmaz; önce checksum/migration state ayrıca incelenir.
   - Mac→staging SSH kapalı fakat self-hosted `staging-sw-testai-deploy` runner online ise canonical fallback: Actions'ta `.github/workflows/faz25-fullats-test-recovery.yml` yalnız `main` üzerinden dispatch edilir. Önce `dry_run=true`; canlı test recovery için `dry_run=false` + exact `confirm=APPLY_FAZ25_FULLATS_TEST_RECOVERY`. Her iki koşum da mutation öncesinde `platform-test` Argo Application observed revision'ının exact workflow commit'i olmasını ve Argo resource inventory'de yalnız hedef `ats-interview-evidence` Deployment + ConfigMap'in `Synced` olmasını; canlı Deployment image + ConfigMap endpoint/approval üçlüsünün canonical değerlerle birebir bağlanmasını 300 saniyeye kadar bekler. Overall Application `OutOfSync`, ATS dışı aynı-wave kaynaklar henüz uygulanmadığında target resource'lar exact/Synced olsa bile görülebilir; bu yüzden pre-append kapısı unrelated resource statüsünü safety sinyali saymaz. Full acceptance sonunda overall Argo `Synced/Healthy` yine ayrıca zorunludur. Workflow doğrudan workload patch/restart yapmaz; `--roles-only` → V6 → fixed-id model-governance append → immutable digest/Ready + V4/V5/V6 → Keycloak → sentetik 10/10 sırasını fail-closed yürütür. Ready bekleyişi 600 saniyede tükenirse raw log/env/secret basmadan yalnız deployment condition, pod phase/container wait-termination nedeni/restart sayısı ve ilgili Pod event özetini yayınlayıp durur.
2. **Keycloak** (~60 sn): `provision-test-keycloak.sh` aynı yolla.
   - Login `svc-kc-automation` (Vault `kv/platform/keycloak-automation`); user-izinleri eksikse KC26 `bootstrap-admin` geçici-admin yolu (bkz. §Sorun Giderme).
   - Model: audience + 13 permission + atanmayan repair client-scope **frontend'e DEFAULT**; **yetki YALNIZ `ats-api` client-role atamasıyla** (scope ∩ atanmış-rol ∩ bilinen permission). Toplam 14 rol / 15 default scope. Tenant claim hardcoded değildir; `ats_tenant` user attribute mapper'ından gelir. `ats-recruiter-persona` yalnız public careers tenant + `ats.application.{read,status.write}` exact-set taşır.
3. **Aktivasyon** (~2 dk): normal GitOps PR merge + ArgoCD reconcile (`kustomize/overlays/test` bu activation overlay'ini içerir).
   - Beklenen ara durum: yeni pod Flyway V6'yı uygular; model-governance ledger henüz boşken boot gate kasıtlı fail-closed olduğu için pod `CrashLoopBackOff` kalabilir. Bu sırada `Ready` beklenmez ve workload'a doğrudan restart/patch yapılmaz.
   - Beklenen son durum: §Faz 25 test model-governance artifact geçişi fixed-id append'i doğrulandıktan sonra boot gate açılır; ExternalSecret Ready=True → Secret 3 key; ats-interview-evidence Running/Ready olur. Provider live-stt fail-closed; kullanılmayan ai-stub pod'u desired-state dışıdır. CrashLoop exponential backoff 600 saniyelik Ready penceresini aşarsa workflow fail-loud durur; fixed transition idempotent olduğu için aynı exact-main koşumu yeniden dispatch etmek normal ve güvenlidir, doğrudan workload restart/patch yapılmaz.
   - `platform-test` Argo uygulamasında `prune:false` olduğu için eski manuel `ats-ai-stub` kaynakları otomatik silinmez. Argo `Synced/Healthy` ve `ATS_AI_PROVIDER=live-stt` kanıtından **sonra** tek-seferlik, isimle sınırlı temizlik: `kubectl --context k3d-test -n platform-test delete deployment/ats-ai-stub service/ats-ai-stub configmap/ats-ai-stub-script networkpolicy/ats-ai-stub --ignore-not-found`. NetworkPolicy, önceki çok-belgeli `netpol.yaml` desired-state'inin ikinci nesnesiydi; güncel `ai-stub.yaml` içinde olmaması onu eski cluster'da hayalet yapmaz. Önce aynı isimlerle `kubectl get` kanıtı al; wildcard/label tabanlı toplu silme kullanma.
   - Fail sinyali: pod `CreateContainerConfigError` = Secret yok (ESO/Vault kontrol); `CrashLoopBackOff` + `AppProperties` log'u = eksik env.
4. **D29 kanıt matrisi** (Codex düzeltmeli adlandırma):
   - **Up**: pod Ready + `imageID == aktivasyon kustomization'daki pinli digest` (D30 immutable; `d29-smoke.sh` default'u pin ile senkron, `ATS_EXPECTED_DIGEST` ile override)
   - **Edge**: `https://testai.acik.com/api/ats/v1/transcripts` → 401 (JWT challenge; HTML DEĞİL)
   - **Authn deny**: token'sız/bozuk-audience → 401
   - **Authz deny**: reader token'ı ile `POST consent` → 403; rolsüz+scope'lu → 403
   - **Functional — live-stt**: reviewer token'ı ile consent→upload(sentetik)→transcribe→read-back
   - **İSPATLAMAZ**: gerçek KVKK pilotu, prod-hazırlık

### Faz 25 Full ATS aday/recruiter acceptance (#2615)

- Public careers tenant: `00000000-0000-0000-0000-000000000001`; request/header/body tenant seçemez.
- Backend yalnız `.test` e-posta kabul eder; gerçek aday PII G0 kilidinde kalır.
- Recruiter persona ayrı `ats_tenant` attribute'u taşır; platform product API'leriyle `INTERVIEW_EVIDENCE=VIEW`, `ATS=VIEW`, `ATS_JOB_MANAGE=ALLOW` ve `ATS_APPLICATION_MANAGE=ALLOW` exact least-privilege granule set'i kurulur. `/authz/me` aynı kimlik için `superAdmin=false` ve dört exact grant'i kanıtlamadan browser kabulü başlamaz.
- Canlı API zinciri: `scripts/ats/fullats-application-smoke.sh` — TLS doğrulamalı public jobs → sentetik submit → idempotent replay → session-token candidate status (PII-free) → tenant-scoped recruiter inbox → aynı application rollerine sahip diğer tenant için listeleme reddi + status `PUT` 404 negatif izolasyonu → iki optimistic-lock status transition. `10/10 PASS` beklenir; JWT/parola/candidate token basmaz.
- Ürün kabulü `.github/workflows/faz25-fullats-live-browser-acceptance.yml` ile exact ATS + permission + frontend digest'lerine ve exact frontend source SHA'ya bağlanır. Browser zinciri İK login → kalıcı taslak oluşturma → düzenlenen özetin hem modal önizlemede hem public ilanda exact görünmesi → yayın → dinamik `/careers/<handle>/jobs/<slug>` ilanı → adayın düzenlenebilir form/önizleme/açık onay/kalıcı makbuzu → İK inbox ve insan kontrollü durumlar → ilanı duraklat/yeniden yayınla/kapat → duraklatılmış/kapalı ilanda yeni POST 404 + `NOT_FOUND` → mevcut aday makbuzunun yaşamaya devam etmesidir. API smoke, yalnız update yanıtı veya local UI testi bu browser kanıtı yerine geçmez.

### Faz 25 test model-governance artifact geçişi (#2526)

- `live-stt` boot gate üç exact desired-state bağı ister: `ATS_AI_ENDPOINT_REF=faz24-stt-prod`, `ATS_AI_APPROVAL_TRANSCRIBE_REF=mapr_04cabd…fc43` ve aynı katalog kaydını taşıyan immutable ATS image digest. Yeni ref, `Systran/faster-whisper-medium` + immutable revision + doğrulanmış `model.bin` SHA-256 içeriğine bağlıdır. Activation ConfigMap, canlı Deployment image ve operator image birebir eşleşmeden script çalışmaz.
- Flyway→boot-gate sırası ATS source `f34a761` içinde explicit bean bağıdır: `WiringConfig.flyway(DataSource)` önce `flyway.migrate()` çağırır; `modelGovernanceLedgerReader(DataSource, Flyway)` bu bean'e, registry reader'a ve `authorizedModelBindings` registry'ye bağımlıdır. Bu nedenle V6 fail-closed boot'ta yazılabilir; yeni artifact ref ledger'da APPROVED değilken composition/Ready engellenir. Workflow önce V6'yı canlı DB'de kanıtlar, sonra append yapar, en son Ready bekler. Eski `mapr_549a8e…a732d` satırı audit geçmişi için append-only kalır; silinmez veya yeniden yazılmaz.
- `scripts/ats/transition-test-model-governance.sh` normal app boot'u veya `ats_app` credential'ını writer yapmaz. Admin düzlemi yalnız rastgele, kısa ömürlü `ats_governance_op_<hex>` LOGIN oluşturur; bu login adminsizdir ve NOLOGIN `ats_governance_writer` rolünün explicit member'ıdır. Parola yalnız PostgreSQL ve pinli operator container stdin'ine gider; script-owned argv/env/CI output/shell history/Vault/Kubernetes Secret/repo dosyasına girmez. Script rolü oluşturmadan önce test PG'de `log_statement=none`, `log_min_duration_statement=-1` ve varsa `pgaudit.log=none` doğrular; aksi halde DDL çalıştırmadan fail-closed durur. Ayrıca rol DDL transaction'ında `log_min_error_statement=PANIC` session-local uygulanır; DDL hata verse dahi parola içeren statement normal error log'una yazılmaz.
- Dış check confirmation: `CHECK_FAZ25_TEST_MODEL_GOVERNANCE`; append confirmation: `APPEND_FAZ25_TEST_MODEL_GOVERNANCE`. Yeni artifact onayı sabit `mgt_25260000-0000-4000-8000-000000000002` transition kimliği + opak `cross-ai/faz25/2526` actor ref kullanır. Tekrar koşum yeni satır üretmez; canonical CLI idempotent replay döndürür.
- Script global dosya kilidi, stale ephemeral-role preflight'ı, her CLI çağrısı öncesi writer/`ats_app`/live-image drift kontrolü, 120 saniye container timeout'u ve üç denemeli `REVOKE`+`DROP ROLE` cleanup uygular. `INT`/`TERM`/`HUP` cleanup'a yönlenir; `SIGKILL`/host-crash cleanup'ı teknik olarak çalıştıramaz. Sonraki koşum stale role sayısını fail-loud bildirir; otomatik wildcard role silme yapmaz.
- Stale role reconciliation otomatik değildir: önce `SELECT rolname FROM pg_roles WHERE rolname ~ '^ats_governance_op_[0-9a-f]{16}$'` ve `pg_stat_activity` ile exact rol/oturum incelenir; yalnız doğrulanan exact isim için aktif oturumlar sonlandırılıp üyelik revoke edilir ve rol drop edilir. Wildcard/dinamik toplu drop yasaktır; işlem issue #2526 kanıtına yazılır ve recovery baştan çalıştırılır.
- Append sonrası kabul: CLI projeksiyonu `APPROVED idempotent=true`; eski approval sequence `0` + genesis previous-hash ile byte-for-byte korunur, yeni artifact approval sequence `1` olur ve `previous_hash` eski satırın exact `entry_hash` değerine eşitlenir. Yeni satır exact actor/reason ve CLI çıktısıyla aynı 64-hex entry-hash taşır. İlk append ve idempotent replay aynı iki-satırlı zincir sözleşmesiyle doğrulanır. Test-PG append-only mekanizma kanıtıdır; mevzuatsal/harici WORM depolama iddiası değildir.
- Bu owner-delegated test kararı direct Anthropic Claude + provider-ayrık Cursor CLI `AGREE` zincirine ve runtime issue #2526 kanıtına bağlıdır. AI review, gerçek prod secret-owner/hukuk/DPO imzası veya GitHub protected Environment insan tıklaması yerine geçmez.
- Append rollback'i satır silmek/değiştirmek değildir; WORM trigger bunu reddeder. Ürün rollout rollback'i image/config GitOps PR'ıyla yapılır ve transition additive kalır. Gerçek bir revoke kararı ayrı transition kimliği, exact confirmation ve yeni kayıtlı owner/reviewer kararı ister.

### 39d-4 KANIT (2026-07-11, 14/14 PASS FAIL=0 — `scripts/ats/d29-smoke.sh`)

Up: pod Running/ready + imageID==sha256:c2dcc1da… (pin). Edge: token'sız 401; healthz dışarı kapalı. Authn-deny: audience'sız token 401. Token (redacted): aud⊇ats-api, tenant=t-platform-test, roller tam-küme (reader 2 / reviewer 7 / operator 10 / roleless 0). Authz: reader read 200 + write 403; ROLSÜZ+scope'lu 403 (rol-kapısı canlı); reviewer dsar 403 / operator dsar 201. Functional-stub: consent 204 → raw-WAV upload 201 (ledgerSequence, pointer-only objectKey) → transcribe 201 (segmentCount:3) → transcript?key= read-back 200. Upload kontratı: RAW body (multipart değil) + X-ATS-Filename; transcribe {"sourceObjectKey"}. İSPATLAMAZ: canlı STT, gerçek KVKK pilotu, WORM, prod-hazırlık.

### 39d-7a-fix KANIT (2026-07-12, duplicate→idempotent-replay; 14/14 PASS)

Kök neden: aynı lexical içerik ikinci transcribe'da yeni uuid transcriptKey ürettiğinden adapter'ın birebir-aynı replay yolu tetiklenemiyor, idempotency-conflict "ledger_unavailable"+503'e dönüşüyordu (canlı: PG seq-4 + 503×2). Fix ats#102 (Codex 019f52f5 3-iter REVISE→REVISE→AGREE; hybrid pre-lookup + conflict-recovery + pointer-bütünlük [payload↔güncel-çağrı↔store-hash] + tombstone-matrisi; 282/282 + mutation-check). İmaj sha-7779119/3a84bbb9… apply → pod imageID doğrulandı → **d29-smoke 14/14 FAIL=0**; transcribe 201 cevabı ORİJİNAL kanıtın replay'i (transcriptKey=tr-9cd81b58…, yeni WORM satırı yok). Rollout notu: node 50-pod tavanında eski Running pod elle silinerek slot açıldı (bilinen desen).

Apply-yolu canlı dersleri: LimitRange 500m enjeksiyonu quota'ya çarptı (test limits.cpu 13); eso-runtime allowlist'ine kv/platform/ats; node 50-pod tavanı (test artifact-host 1 replika); runAsNonRoot isimli-kullanıcı hatası → runAsUser 10001 (+ Dockerfile numerik-UID ats#100); rollout kilidi = eski-Pending pod quota işgali → pod sil + RS backoff'una RS-delete.

5. **Canlı STT doğrulaması**: test desired-state `ATS_AI_BASE_URL=https://live-stt.denetim:8243`, `ATS_AI_PROVIDER=live-stt` ve mTLS-required pinlidir; stub↔live OTOMATİK fallback YASAK. ConfigMap + canlı sentetik transcribe/read-back birlikte kanıtlanır.

### 39d-6 MFE canlı READ (platform-web #869; Codex 019f50b7 AGREE)

MFE (`mfe-interview-evidence`) canlı `/api/ats` READ'i **runtime env** ile açılır (build-arg değil):

| Anahtar (window.__env__) | Değer | Davranış |
|---|---|---|
| `INTERVIEW_EVIDENCE_DATA_MODE` | *yok/boş* | **demo** (default — 39c-7 davranışı birebir) |
| | `live` | transcript listesi + F3 segmentler shell-token'lı shared-http ile `/api/ats/v1`'den |
| | başka değer | **config-error kartı** (fail-closed; sessiz demo düşüşü YOK) |
| `INTERVIEW_EVIDENCE_INTERVIEW_ID` | live modda ZORUNLU | boşsa config-error (id uygulama koduna hardcode edilmez) |

- testai değerleri `platform-web scripts/deploy/build-single-domain.mjs` STAGE spread'inden **explicit** enjekte edilir: `live` + `iv-smoke-1` (39d-4 D29 smoke'unun SENTETİK fixture'ı — gerçek aday verisi DEĞİL; ATS-0016/G0 sınırı). Prod build'de anahtarlar yok → demo.
- Auth zinciri: shell `createProtectedRemoteApp` remote'u mount etmeden ÖNCE `configureShellServices` çağırır (Bearer/auth-ready/refresh shell'den; MFE token üretmez). UI hata ayrımı D29 aynası: **401→"Oturum hatası"** (rol atamak çözmez) ≠ **403→"Yetki hatası"** (ats-api client-role eksik); 200+bozuk gövde `AtsContractError` (sessiz boş-veri YOK).
- Yazma yüzeyleri (rıza/inceleme/DSAR) canlı modda 39d-7'ye kadar gizli; tam akış demo modunda.
- Doğrulama: browser network'te `GET /api/ats/v1/interviews/iv-smoke-1/transcripts` 200 + liste render + seçimde `transcript?key=` 200 + segment render.

### 39d-7b/7b-2/7c/7d KANIT (2026-07-12 — canlı ürün yüzeyi F1→F10 TAMAM)

| Dilim | platform-web PR | gitops pin | Edge-LIVE marker (MF zinciri) |
|---|---|---|---|
| 7b citation (F4) | #871 | #2312 (sha-9dda59b) | — (7b-2 build'ine katlandı) |
| 7b-2 insan-onay/finalize (F5) | #872 | #2319 (sha-2d6cebb) | `App-DapSGjkm.js`: `live-review-panel` |
| 7c DSAR/erasure (F10) | #873 | #2320 (sha-92795e1) | `App-D7p-aR-M.js`: `live-dsar-panel` |
| 7d export (F7) | #874 | #2322 (sha-31bee61) | `App-D-yVTgGe.js`: `live-export-panel` + `export-reconcile-error` |

Edge-marker doğrulama (VPN'siz; esbuild non-ASCII'yi escape'ler → ASCII
testid marker'ı kullan):

```bash
B=https://testai.acik.com/remotes/interview-evidence
# remoteEntry → inner → exposes → App-shim → App-real zinciri; App-real'de:
grep -c 'live-export-panel' <(curl -sk "$B/assets/App-<hash>.js")
```

> KEŞİF KISAYOLU (2026-07-12 dersi): `https://testai.acik.com/build-info.json`
> sha + remotes[].assets listesini verir — zinciri elle yürütme. DİKKAT: remote
> path'i SLUG'ladır (`/remotes/interview-evidence/...`, `mfe-` önekli DEĞİL).

### 39d-8→10 receipt/artifact/replay zinciri (MERGED — aktivasyon pin'i VPN-dönüşü)

Backend (ats): **#103** receipt-recovery GET + **#104** no-store kontrat-hijyeni +
**#105** 200-yolu E2E kontratı + **#106** artifact READ (ledger-bağlı
`artifact_digest`; erasure'ın content-silmesi API'dan kanıtlı) + **#107**
idempotent-replay (`request_digest`; 200+`X-ATS-Replay` / 409 R4-repair-first).
FE (platform-web): **#875** makbuz-kurtarma UI (gitops **#2325** pin
sha-8d2d81a — EDGE-LIVE: `App-yQDs4iSN.js` 5/5 marker: `live-export-panel`,
`export-receipt-recover`, `export-recovered-receipt`, `export-receipt-note`,
`not-found-unresolved`).

### 39d-8→12 CANLI KANIT (2026-07-12 VPN-oturumu — zincir tamam)

KC #2328 koşumu: **ASSERT OK 12 rol + 13 default-scope** (export.repair
ATANMADAN). Pin `sha-f3ccad7` apply → **canlı smoke İLK koşumda ürün-bulgusu
yakaladı**: export 400 `ref-pattern ihlali: human_actor_ref` — canlı KC sub'ı
UUID (rakam-başlı), packet REF_PATTERN ilk-karakter-harf şartına takılıyordu
(E2E'ler harf-başlı sub kullandığından görünmemişti). Fix **ats#109 (39d-12)**:
packet `human_actor_ref` → `actor.v1.<sha256>` (Codex kararı: koşullu-prefix
collision üretir; ham sub packet'e taşınmaz; vaka/ledger raw; diğer ref
alanları fail-closed). Yeni pin **`sha-e6b7409` /
`sha256:b4b6a806…a8e9d7`** (gitops#2332) apply → pod imageID birebir.

Kanıtlar (aynı oturum):
- `d29-smoke.sh` (ATS_EXPECTED_DIGEST override): **14/14 FAIL=0**
- `d29-smoke-receipt-chain.sh`: **20/20 FAIL=0** — receipt 200-COMPLETED+
  no-store / reader-403 / anon-401; artifact 200 + Content-Type + no-store +
  **VERBATIM (sha256(HTTP-gövdesi)==worm_ledger.artifact_digest)** + HEAD-403;
  replay 200+`X-ATS-Replay`+birebir-makbuz+**case-scoped WORM 0→1** /
  değişik-gövde-400; repair onay-kapısı rolsüz-403; erasure-sonrası artifact-404
  (+no-store) / **makbuz 200-COMPLETED sağ çıktı**.

İSPATLAMAZ: repair 200-REPAIRED canlı yolu (rol manuel atanınca — onay-kapısı;
E2E'de kanıtlı), canlı STT (39d-5), browser-acceptance (login-gated).

**39d-12 son canlı D29 baseline: `e6b7409` / `sha256:b4b6a806…a8e9d7`.**
**Faz 25 #2615 branch-acceptance pini: ATS #183 exact head `f4d2b4f` / `sha256:8812ab4e…66a11`; canlı D29 pending ve yalnız recovery + acceptance koşumuyla kanıtlanacaktır.**
(Tarihsel aktivasyon hedefi: ~~f3ccad71~~ → `e6b7409` UYGULANDI.)
(39d-8/8c/8d/9/10/**11** birlikte; #108 R4-repair dahil — KC koşumu
`provision-test-keycloak.sh` gitops#2328 sürümüyle: 12 rol/13 scope,
`ats.export.repair` ATANMADAN). Pin sonrası smoke EKLERİ (mevcut d29-smoke 14'üne):

| Kanıt | Beklenen |
|---|---|
| operator token → `GET /export/receipt?caseKey=<exported>` | 200 COMPLETED + no-store; reader(export.read yok)→403; anon→401 |
| `GET /export/artifact?caseKey=` | 200 verbatim (sha256(gövde)==ledger.artifact_digest) + `Content-Type: application/json`; HEAD→403; erasure-sonrası→404 |
| AYNI gövdeyle ikinci export POST | 200 + `X-ATS-Replay: true` + birebir makbuz + WORM satır-sayısı SABİT |
| DEĞİŞİK gövdeyle ikinci POST | 400 conflict (makbuz sızmaz) |
| FINALIZED+ledger-satırlı vakada POST (R4) | 409 repair-first (üretimsiz); receipt GET 200 INCOMPLETE |
| repair-rolü ATANMADAN `POST /export/repair` | 403 (onay-kapısı kanıtı); rol manuel atandıktan sonra → 200 REPAIRED + WORM `export.transition_repair_intent` satırı |

## F7 export — operasyonel residual'lar (R1–R4) ve müdahale

Single-export invariant'ı DB'dedir: `worm_ledger UNIQUE(tenant_id,
idempotency_key)` + ExportService deterministik key
(`tenant:interview:export:caseKey`). Frontend guard'ı yalnız aynı-sekme
best-effort'tur. Aşağıdaki durumlar BAŞARI SAYILMAZ ve UI bunları
ambiguous-kilit olarak gösterir:

| # | Durum | Tespit | Müdahale |
|---|---|---|---|
| R1 | Ledger-conflict sonrası artifact telafi-DELETE'i başarısız → **öksüz artifact** (ledger-bağsız; packet lineage DIŞI). NOT (ats#107): telafi başarılı **VE kazanan ledger satırı görünürse** sistem otomatik reconcile eder (replay/409); satır yoksa operasyonel hata korunur — R1 yalnız telafi-FAIL'de | app-boot log: `ledger append başarısız VE artifact telafi silmesi başarısız (operasyonel müdahale gerekir)` + 503 | SİLMEDEN ÖNCE doğrula: aynı tenant/interview'da HİÇBİR ledger satırı `export_artifact_ref` olarak bu artifact'i göstermiyor + devam eden export yok + retention/legal-hold engeli yok. Yalnız ledger-bağsız orphan KESİNLEŞİRSE onaylı artifact-store delete yolu; işlem + silinen ref audit'e. SONRA deterministik idempotency_key + vaka state'i YENİDEN doğrula: export ledger satırı VARSA yeni export DENEME (EXPORTED→R2; FINALIZED+ledger→R4); yalnız ledger satırı YOK + vaka FINALIZED + devam eden işlem YOK ise onaylı yeni export (otomatik retry değil). |
| R2 | Ambiguous sonrası makbuz kimlikleri kayıp | UI `reconciled-exported` / ambiguous-kilit | **BİRİNCİL YOL (ats#103 pinliyken)**: `GET /export/receipt?caseKey=` → 200 COMPLETED alanları makbuzdur (UI "Makbuzu getir" aynı işi yapar); 200 INCOMPLETE=R4; 404 "yok" KANITI DEĞİLDİR (in-flight yarışı/kapsam-düzlemesi — kilit çözülmez). **FALLBACK (pin öncesi/endpoint erişilemezken)**: `worm_ledger`'da tenant + deterministik export idempotency_key satırını bul. `evidenceId` = satırın KENDİ `evidence_id` kolonu (payload'da DEĞİL); payload'dan `export_artifact_ref`→artifactKey, `packet_digest`→packetDigest, `claim_count`→claimCount; payload `case_key` hedef vakayla EXACT eşleşmeli — doğrulanmadan makbuz yeniden-oluşturulmuş sayılmaz. |
| R3 | ~~İkinci istek same-receipt replay ALMAZ~~ **ats#107 ile YENİ export'larda kapandı**: aynı-gövde POST → 200 replay (`X-ATS-Replay`); yarış kaybedeni otomatik reconcile (rollback-OK'ta replay/409). KALAN: legacy satırlar (request_digest'siz) POST-replay alamaz → receipt GET; rollback-FAIL hâlâ R1'e düşer | Pin-öncesi imajda eski davranış: 503 `artifact geri alındı` (net-zero) — bu imajda YENİ EXPORT DENEME; kazanan durumunu doğrula (EXPORTED→R2, FINALIZED+ledger→R4). **#107 pinliyken**: birincil yol receipt GET; POST yalnız BİREBİR AYNI gövdeyle güvenlidir (doğrulanmış 200-replay); FARKLI gövde YASAK (400 conflict — makbuz sızmaz). | Kaybeden istek net-zero — bu istek için orphan temizliği gerekmez. AMA kazananın tamamlandığı VARSAYILMAZ: ledger satırı + vaka state'i doğrula — EXPORTED ise etkili export var (makbuz yoksa R2); FINALIZED + ledger satırı varsa R4 repair. YENİ EXPORT DENEME. |
| R4 | artifact + ledger yazıldı, `markExported` DÜŞTÜ → vaka FINALIZED kaldı | app-boot log: `EXPORTED geçişi başarısız (artifact + ledger kaydı MEVCUT ... yutulmadı)` + 400 (DİKKAT: her 400 R4 değildir — bu log satırı ŞART). **Pin sonrası ek sinyaller**: retry-POST → 409 `repair-first` (üretimsiz); `GET /export/receipt` → 200 **INCOMPLETE** | **YENİ üretim / DEĞİŞİK-gövde deneme YASAK** (ledger key tüketildi; pin-öncesi imajda retry conflict'e düşer, **#107 pinliyken aynı-gövde retry deterministik 409 döner — self-heal YAPMAZ**; durum kanıtı receipt GET 200 INCOMPLETE). Repair ÖN-KOŞULLARI: vaka hâlâ FINALIZED + deterministik idempotency_key için TEK export-tipli ledger satırı + payload `case_key` exact-eşleşme + `export_artifact_ref` artifact'i MEVCUT + artifact/ledger `packet_digest` bütünlüğü + aynı vaka için ikinci ledger-bağlı export YOK. TAMAMI sağlanıyorsa onaylı+AUDİTLİ repair: **`POST /export/repair {caseKey}` (ats#108; `ats.export.repair` rolü onay-kapısıyla MANUEL atanır — script otomatik atamaz)** — endpoint önkoşulları kendisi doğrular (artifact varlık+digest), WORM repair-intent yazmadan geçiş YAPMAZ, cevap repairStatus=REPAIRED|ALREADY_EXPORTED; endpoint erişilemiyorsa ad-hoc DB mutasyonu YAPMA — backend müdahalesine eskale et. Repair sonrası case=EXPORTED + tek ledger satırı + digest bağı yeniden doğrulanır. |

Frontend davranış sözleşmesi (platform-web `apps/mfe-interview-evidence/README.md`):
400/5xx hiçbir zaman "uygulanmadı" sayılmaz; reconciliation'da EXPORTED
görünürse makbuz UYDURULMAZ; FINALIZED görünmesi R4 nedeniyle kanıt değildir.

## 39d-5 canlı-STT promotion (test desired-state'te aktif; canlı erişim ayrıca kanıtlanır)

Desired-state: activation patch `ATS_AI_BASE_URL` =
`https://live-stt.denetim:8243` (denetim-PC GPU host; mTLS —
`RB-faz24-direct-stt-mtls-enable.md` deseninin ATS aynası). Zincir (tek
VPN-oturumu): ats app-boot mTLS env-adları keşfi → Vault `kv/platform/ats`
STT cert/key/CA seed → activation ExternalSecret + mount + GitOps PR →
ArgoCD reconcile → canlı transcribe kanıtı (ATS-0017: stub↔live otomatik
fallback YASAK; ayrı acceptance). KEY-HİJYENİ: gerçek private-key materyali
scp/terminal-çıktısı/shell-history/runbook-kanıtına YAZILMAZ — Vault'a güvenli
kanaldan seed edilir, cluster'a YALNIZ ExternalSecret ile taşınır.

## Rollback (ArgoCD-aware)

- **Sıra:** doğrudan `kubectl delete -k` kullanma; Argo `selfHeal:true` kaynağı geri getirir ve sahte rollback üretir. Önce rollback GitOps PR'ını merge et, Argo'nun yeni revision'ı `Synced/Healthy` yaptığını kanıtla, yalnız desired-state'ten çıkarılmış ve `prune:false` nedeniyle kalmış kaynakları sonra isimle sil.
- **Faz 25 Full ATS frontend-only compensator:** #2632'nin exact merge SHA'sında çalışan `faz25-fullats-live-browser-acceptance.yml`, runtime veya gerçek browser kabulü düşerse GitHub App kimliğiyle yalnız test-root frontend pinini reviewed base'deki `sha-9f82edb@sha256:f23165a5…fe8b0` artifactine döndüren ve `fullats-promotion-state.txt=ROLLED_BACK` yapan iki dosyalık PR açar. ATS `sha256:8812ab4e…a11` ve permission-service `sha256:55f2f2f2…e13d` pinleri korunur; önceki geniş rollback bu düzeltmeleri artık geri almaz. Compensator ancak failed workflow SHA, current main ve #2632 merge SHA birebir aynıysa; #2632 tek-parent squash commit'i doğrudan reviewed `e06ba1ad…faf0d` base'in çocuğu ve squash tree'si receipt'lerle bağlı exact PR head tree'si ise çalışır. Trusted-base verifier exact iki-path diff'i, restored frontend blob'unu ve marker'ı doğrulayıp base/head'e bağlı attestation üretmeden automation istisnası geçmez. Bot PR required check'leri bekler, head'i yeniden doğrular, `--match-head-commit` ile normal korumalı squash merge yapar; `--admin` yoktur. Ardından exact rollback merge revision'ı `Synced/Healthy`, üç current Deployment/Ready-pod digest'i, public `build-info.json` eski frontend SHA'sı ve current ATS digest'iyle tam D29 matrisi yeniden kanıtlanır. Merge veya post-rollback kanıtı düşerse workflow kırmızı kalır. Doğrudan cluster patch'i ve production rollback yetkisi yoktur.
- **Artifact/source kanıt sınırı:** canlı kabul desired Deployment image'i ve Ready pod `imageID` değerini üç immutable digest ile birebir bağlar. Source commit ve Actions build run kayıtları lineage metadata'sıdır; bu artifact'lerde imzalı provenance attestation bulunmadığından kriptografik source→digest provenance iddiası yapılmaz. Prod promotion öncesinde ayrı imzalı provenance kapısı gerekir.
- **Yalnız backend sürümü:** activation `images.digest` değerini son kanıtlı digest'e döndüren PR → merge → Argo reconcile → pod `imageID` eşitliği + D29. Flyway V5 tablosu additive bırakılır; incident sırasında tablo/drop veya veri silme yapılmaz.
- **Frontend sürümü:** test root `frontend` image tag+digest+sourceRevision üçlüsünü önceki kanıtlı immutable sürüme döndüren PR → merge → Argo reconcile → edge `build-info.json` + browser smoke.
- **ATS yüzeyini test root'tan çıkarma:** PR ile `kustomize/overlays/test/kustomization.yaml` içindeki `activation/ats-interview-evidence` kaynağını kaldır → merge → Argo revision doğrula → `prune:false` nedeniyle kalan ATS kaynaklarını, `kubectl kustomize kustomize/overlays/test/activation/ats-interview-evidence` çıktısındaki kind/name çiftlerine göre tek tek sil. Wildcard veya namespace-wide silme yasaktır.
- **Keycloak:** `ats-api`, audience scope'u ve interview persona'ları başka ATS akışlarınca paylaşılır; topluca silme yasaktır. Full ATS rollback'inde recruiter persona/iki application rolü inert bırakılabilir. Güvenlik gerekçesiyle kaldırılacaksa önce uygulama rollback'i doğrulanır, sonra yalnız `ats-recruiter-persona` rol eşlemeleri/kullanıcısı ve hiçbir token/policy tarafından kullanılmadığı kanıtlanan `ats.application.*` rolleri için ayrı, kayıtlı değişiklik yapılır. Hardcoded global tenant mapper'a sessiz geri dönüş yapılmaz.

## Sorun Giderme

- **`guvensiz role attribute tasiyor` / `LOGIN/no-admin-attributes assert basarisiz`**: Recovery fail-closed durur; script `ALTER ROLE` ile ayrıcalığı sessizce sökmez ve Vault/parola yoluna geçmez. `pg_roles` altı attribute'u admin düzleminden oku, drift'in kaynağını issue/evidence olarak kaydet ve yalnız ayrı, incelenmiş bir least-privilege düzeltmesinden sonra yeniden çalıştır.
- **kcadm `invalid_grant` (bootstrap env parolası)**: KC26 geçici admin: `kc.sh bootstrap-admin user` — DB parolası compose'ta `KC_DB_PASSWORD_FILE` wrapper-export'u olduğundan exec'te aynı export uygulanır + çalışan sunücüyle port çakışmasına karşı `KC_HTTP_PORT=8091 KC_HTTP_MANAGEMENT_PORT=9901`. İş bitince geçici admin SİLİNİR (kanıt: master'da `username=tmpboot*` sorgusu boş).
- **svc-kc-automation 403 (users)**: service-account'a platform-test `realm-management` rolleri: `manage-users view-users query-users` (geçici-admin ile bir kez).
- **İlk imaj yayını tarihi**: run `29149994945` — trivy kapısı ilk denemede 4 CRITICAL (tomcat 10.1.42 ×3 + spring-security-web 6.5.1) yakalayıp PUSH'U KESTİ; Boot BOM 3.5.16 (ats#99) sonrası yeşil. Kapı davranışı REFERANSTIR: kırmızı imaj GHCR'a çıkmaz.

## Referans

- ats repo: #96 (rol-kapısı) #97 (Dockerfile+workflow) #98 (lowercase) #99 (BOM 3.5.16)
- Codex thread'leri: `019f4c6c` (plan, 3-iter) · `019f50b7` (artifact + KC modeli)
- Pattern: `kustomize/overlays/test/activation/endpoint-admin-remote-bridge/` (Argo-root-dışı aktivasyon)
