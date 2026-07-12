# RB — ATS Interview-Evidence backend'i testai'de (ATS-0019 39d)

> Kapsam: **test cluster (k3d-test / platform-test)** — prod'a HİÇBİR adım uygulanmaz.
> Plan + acceptance matrisi: Codex thread `019f4c6c` (3-iter AGREE) + `019f50b7`.
> Kanonik sınır: motor verisi SENTETİK (ATS-0016); gerçek aday verisi G0=GO'ya bağlı.
> WORM iddiası test-PG'de YAPILMAZ (yalnız uygulama-seviyesi append-only guard).

## Bileşenler

| Parça | Yer |
|---|---|
| İmaj | `ghcr.io/halildeu/ats-app-boot` (public; ats repo `image-push.yml` — trivy CRITICAL fail-closed push-öncesi; `digest:` log satırı AUTHORITY) |
| Base manifest | `kustomize/base/apps/ats-interview-evidence/` (INERT — hiçbir overlay resources listesinde değil) |
| Aktivasyon | `kustomize/overlays/test/activation/ats-interview-evidence/` (Argo-root DIŞI; bilinçli apply) |
| Provisioning | `scripts/ats/provision-test-pg-vault.sh` + `scripts/ats/provision-test-keycloak.sh` (idempotent; staging-sw'de koşulur; secret basmaz) |

## Akış (tetik → adımlar)

1. **PG + Vault** (~30 sn): `scp scripts/ats/provision-test-pg-vault.sh staging-sw:/tmp/ && ssh staging-sw bash /tmp/provision-test-pg-vault.sh`
   - Beklenen: `PG: ats_app role + ats db OK` + `VAULT keys: ['ATS_DB_PASSWORD','ATS_DB_URL','ATS_DB_USERNAME']` + `PG login test: ats_app@ats`
   - Not: her koşum DB parolasını ROTATE eder (Vault ile atomik) — pod restart gerektirir.
2. **Keycloak** (~60 sn): `provision-test-keycloak.sh` aynı yolla.
   - Login `svc-kc-automation` (Vault `kv/platform/keycloak-automation`); user-izinleri eksikse KC26 `bootstrap-admin` geçici-admin yolu (bkz. §Sorun Giderme).
   - Model (Codex `019f50b7` verdict A): audience + 10 permission client-scope **frontend'e DEFAULT**; **yetki YALNIZ `ats-api` client-role atamasıyla** (rol-kapısı ats#96: scope ∩ atanmış-rol ∩ bilinen-10). Persona'lar: `admin@example.com`=operator(10), `ats-reviewer-persona`(7, export/dsar/erasure YOK), `ats-reader-persona`(2 read).
3. **Aktivasyon** (~2 dk): `kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test/activation/ats-interview-evidence`
   - Beklenen: ExternalSecret Ready=True → Secret 3 key; ats-ai-stub Running; ats-interview-evidence Running (startup ≤3 dk: Flyway migration).
   - Fail sinyali: pod `CreateContainerConfigError` = Secret yok (ESO/Vault kontrol); `CrashLoopBackOff` + `AppProperties` log'u = eksik env.
4. **D29 kanıt matrisi** (Codex düzeltmeli adlandırma):
   - **Up**: pod Ready + `imageID == aktivasyon kustomization'daki pinli digest` (D30 immutable; `d29-smoke.sh` default'u pin ile senkron, `ATS_EXPECTED_DIGEST` ile override)
   - **Edge**: `https://testai.acik.com/api/ats/v1/transcripts` → 401 (JWT challenge; HTML DEĞİL)
   - **Authn deny**: token'sız/bozuk-audience → 401
   - **Authz deny**: reader token'ı ile `POST consent` → 403; rolsüz+scope'lu → 403
   - **Functional — stubbed AI**: operator token'ı ile consent→upload(sentetik)→transcribe→read-back (stub segmentleri "test-stub" işaretli)
   - **İSPATLAMAZ**: canlı STT, gerçek KVKK pilotu, WORM, prod-hazırlık
### 39d-4 KANIT (2026-07-11, 14/14 PASS FAIL=0 — `scripts/ats/d29-smoke.sh`)

Up: pod Running/ready + imageID==sha256:c2dcc1da… (pin). Edge: token'sız 401; healthz dışarı kapalı. Authn-deny: audience'sız token 401. Token (redacted): aud⊇ats-api, tenant=t-platform-test, roller tam-küme (reader 2 / reviewer 7 / operator 10 / roleless 0). Authz: reader read 200 + write 403; ROLSÜZ+scope'lu 403 (rol-kapısı canlı); reviewer dsar 403 / operator dsar 201. Functional-stub: consent 204 → raw-WAV upload 201 (ledgerSequence, pointer-only objectKey) → transcribe 201 (segmentCount:3) → transcript?key= read-back 200. Upload kontratı: RAW body (multipart değil) + X-ATS-Filename; transcribe {"sourceObjectKey"}. İSPATLAMAZ: canlı STT, gerçek KVKK pilotu, WORM, prod-hazırlık.

### 39d-7a-fix KANIT (2026-07-12, duplicate→idempotent-replay; 14/14 PASS)

Kök neden: aynı lexical içerik ikinci transcribe'da yeni uuid transcriptKey ürettiğinden adapter'ın birebir-aynı replay yolu tetiklenemiyor, idempotency-conflict "ledger_unavailable"+503'e dönüşüyordu (canlı: PG seq-4 + 503×2). Fix ats#102 (Codex 019f52f5 3-iter REVISE→REVISE→AGREE; hybrid pre-lookup + conflict-recovery + pointer-bütünlük [payload↔güncel-çağrı↔store-hash] + tombstone-matrisi; 282/282 + mutation-check). İmaj sha-7779119/3a84bbb9… apply → pod imageID doğrulandı → **d29-smoke 14/14 FAIL=0**; transcribe 201 cevabı ORİJİNAL kanıtın replay'i (transcriptKey=tr-9cd81b58…, yeni WORM satırı yok). Rollout notu: node 50-pod tavanında eski Running pod elle silinerek slot açıldı (bilinen desen).

Apply-yolu canlı dersleri: LimitRange 500m enjeksiyonu quota'ya çarptı (test limits.cpu 13); eso-runtime allowlist'ine kv/platform/ats; node 50-pod tavanı (test artifact-host 1 replika); runAsNonRoot isimli-kullanıcı hatası → runAsUser 10001 (+ Dockerfile numerik-UID ats#100); rollout kilidi = eski-Pending pod quota işgali → pod sil + RS backoff'una RS-delete.

5. **Canlı STT promotion** (AYRI dilim, 39d-5): `ATS_AI_BASE_URL` patch'i GitOps değişikliğiyle; stub↔live OTOMATİK fallback YASAK.

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

## F7 export — operasyonel residual'lar (R1–R4) ve müdahale

Single-export invariant'ı DB'dedir: `worm_ledger UNIQUE(tenant_id,
idempotency_key)` + ExportService deterministik key
(`tenant:interview:export:caseKey`). Frontend guard'ı yalnız aynı-sekme
best-effort'tur. Aşağıdaki durumlar BAŞARI SAYILMAZ ve UI bunları
ambiguous-kilit olarak gösterir:

| # | Durum | Tespit | Müdahale |
|---|---|---|---|
| R1 | Ledger-conflict sonrası artifact telafi-DELETE'i başarısız → **öksüz artifact** (ledger-bağsız; packet lineage DIŞI) | app-boot log: `ledger append başarısız VE artifact telafi silmesi başarısız (operasyonel müdahale gerekir)` + 503 | SİLMEDEN ÖNCE doğrula: aynı tenant/interview'da HİÇBİR ledger satırı `export_artifact_ref` olarak bu artifact'i göstermiyor + devam eden export yok + retention/legal-hold engeli yok. Yalnız ledger-bağsız orphan KESİNLEŞİRSE onaylı artifact-store delete yolu; işlem + silinen ref audit'e. Vaka state'i bozulmaz; yeni export denenebilir. |
| R2 | Ambiguous sonrası makbuz kimlikleri kayıp (receipt-recovery endpoint'i YOK — backlog) | UI `reconciled-exported (makbuz doğrulanamıyor)` | `worm_ledger`'da tenant + deterministik export idempotency_key satırını bul. `evidenceId` = satırın KENDİ `evidence_id` kolonu (payload'da DEĞİL); payload'dan `export_artifact_ref`→artifactKey, `packet_digest`→packetDigest, `claim_count`→claimCount; payload `case_key` hedef vakayla EXACT eşleşmeli — doğrulanmadan makbuz yeniden-oluşturulmuş sayılmaz. |
| R3 | İkinci istek same-receipt replay ALMAZ (payload'lar artifact-ref'ten ötürü birebir olamaz) → deterministic conflict + telafi | 503 `artifact geri alındı` (net-zero) | Müdahale gerekmez — beklenen davranış; ilk makbuz geçerli. |
| R4 | artifact + ledger yazıldı, `markExported` DÜŞTÜ → vaka FINALIZED kaldı | app-boot log: `EXPORTED geçişi başarısız (artifact + ledger kaydı MEVCUT ... yutulmadı)` + 400 (DİKKAT: her 400 R4 değildir — bu log satırı ŞART) | **YENİ export DENEME** (ledger key tüketildi; retry conflict'e düşer). Repair ÖN-KOŞULLARI: vaka hâlâ FINALIZED + deterministik idempotency_key için TEK export-tipli ledger satırı + payload `case_key` exact-eşleşme + `export_artifact_ref` artifact'i MEVCUT + artifact/ledger `packet_digest` bütünlüğü + aynı vaka için ikinci ledger-bağlı export YOK. TAMAMI sağlanıyorsa onaylı+AUDİTLİ repair mekanizmasıyla FINALIZED→EXPORTED (mevcut artifact ref'iyle); desteklenen repair yolu yoksa ad-hoc DB mutasyonu YAPMA — backend müdahalesine eskale et. Repair sonrası case=EXPORTED + tek ledger satırı + digest bağı yeniden doğrulanır. |

Frontend davranış sözleşmesi (platform-web `apps/mfe-interview-evidence/README.md`):
400/5xx hiçbir zaman "uygulanmadı" sayılmaz; reconciliation'da EXPORTED
görünürse makbuz UYDURULMAZ; FINALIZED görünmesi R4 nedeniyle kanıt değildir.

## 39d-5 canlı-STT promotion (VPN+tünel-gated — bekleyen)

Hedef: activation patch `ATS_AI_BASE_URL` `http://ats-ai-stub:9452` →
`https://live-stt.denetim:8243` (denetim-PC GPU host; mTLS —
`RB-faz24-direct-stt-mtls-enable.md` deseninin ATS aynası). Zincir (tek
VPN-oturumu): ats app-boot mTLS env-adları keşfi → Vault `kv/platform/ats`
STT cert/key/CA seed → activation ExternalSecret + mount + patch PR →
scp+kubectl apply → canlı transcribe kanıtı (ATS-0017: stub↔live otomatik
fallback YASAK; ayrı acceptance). KEY-HİJYENİ: gerçek private-key materyali
scp/terminal-çıktısı/shell-history/runbook-kanıtına YAZILMAZ — Vault'a güvenli
kanaldan seed edilir, cluster'a YALNIZ ExternalSecret ile taşınır.

## Rollback

- Aktivasyonu geri al: `kubectl delete -k kustomize/overlays/test/activation/ats-interview-evidence` → `/api/ats` ana `platform` Ingress'ine (api-gateway 404) geri düşer; MFE demo-motorları etkilenmez.
- İmaj geri alma: activation kustomization `images.digest` önceki değere → apply.
- MFE canlı-mod geri alma (39d-6): test overlay `frontend` pin'ini önceki digest'e döndür (env bundle'a build'de gömülü — revert=pin-revert; ArgoCD sync'ler). Backend'e dokunmaz.
- KC geri alma: `ats-api` client + `ats.*`/`ats-api-audience` client-scope'ları + persona kullanıcıları silinebilir (frontend default-scope bağları client silinince düşer).

## Sorun Giderme

- **kcadm `invalid_grant` (bootstrap env parolası)**: KC26 geçici admin: `kc.sh bootstrap-admin user` — DB parolası compose'ta `KC_DB_PASSWORD_FILE` wrapper-export'u olduğundan exec'te aynı export uygulanır + çalışan sunücüyle port çakışmasına karşı `KC_HTTP_PORT=8091 KC_HTTP_MANAGEMENT_PORT=9901`. İş bitince geçici admin SİLİNİR (kanıt: master'da `username=tmpboot*` sorgusu boş).
- **svc-kc-automation 403 (users)**: service-account'a platform-test `realm-management` rolleri: `manage-users view-users query-users` (geçici-admin ile bir kez).
- **İlk imaj yayını tarihi**: run `29149994945` — trivy kapısı ilk denemede 4 CRITICAL (tomcat 10.1.42 ×3 + spring-security-web 6.5.1) yakalayıp PUSH'U KESTİ; Boot BOM 3.5.16 (ats#99) sonrası yeşil. Kapı davranışı REFERANSTIR: kırmızı imaj GHCR'a çıkmaz.

## Referans

- ats repo: #96 (rol-kapısı) #97 (Dockerfile+workflow) #98 (lowercase) #99 (BOM 3.5.16)
- Codex thread'leri: `019f4c6c` (plan, 3-iter) · `019f50b7` (artifact + KC modeli)
- Pattern: `kustomize/overlays/test/activation/endpoint-admin-remote-bridge/` (Argo-root-dışı aktivasyon)
