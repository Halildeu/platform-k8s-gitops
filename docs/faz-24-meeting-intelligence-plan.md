# Faz 24 — Meeting Intelligence / STT Platform Canonical Plan

> **Status**: ACTIVE (2026-06-02, 3-AI mutabakat sonrası sabit)
>
> **Mutabakat trail**: Claude (Anthropic) + Codex `019e879c` (OpenAI, AGREE final) + Mavis `mvs_c922505d66a94a45b031feb3489f9488` msg `78` (MiniMax, AGREE).
>
> **2026-06-27 KVKK engineering/legal separation addendum**: KVKK/VERBIS/hukuk owner acceptance, owner bildirimi kayda alındıktan sonra Faz 24 mühendislik completion blocker'ı değildir. Legal/VERBIS track paralel yürür; mühendislik `ADR-0030` uyarınca owner-supplied parametrik retention/deletion kontrolleri, fail-closed unset/default davranışı, consent default required, deletion pipeline default enabled, redaction/audit ve overclaim guard ile ilerler. Legal acceptance, VERBIS güncelliği veya production legal go yalnız owner/legal artifact ile söylenir; agent/CI/PR bunu iddia etmez. 2026-06-27 Claude adversarial review bu ayrımı destekledi, P0 risk olarak sonsuz/default retention veya consent-disabled default'u işaretledi.
> Sabit duration değeri veya owner duration kararının henüz verilmemiş olması engineering blocker değildir **yalnız** fail-closed/refuse-to-store default aktifse; owner uygun değeri verdiğinde config/evidence olarak uygulanır. Mimari karar tetikleyicileri için canonical kural `ADR-0030` D6'dır.
>
> **2026-06-27 G-COMP retention provenance addendum**: `scripts/faz24/verify_gcomp_compliance_gate_evidence.py` now enforces owner provenance when effective retention duration values are supplied. Missing owner values remain non-blocking only under fail-closed unset/default behavior; supplied `retentionParameters` require bounded `ownerDecisionRef`, `appliedAsConfig=true`, `hardcodedInCode=false`, and positive bounded day values. This is engineering evidence hardening only; no owner duration value, legal acceptance, production lifecycle/deletion proof, or G-COMP acceptance is claimed.
>
> **2026-06-26 truth refresh**: Faz 24 bağımsız ürün olarak konumlanır; belirli ERP/CRM entegrasyonu ürün bağımlılığı değildir. Sektör-standardı yol haritası §11'e eklendi ve mevcut runtime truth'a göre sınırlandı: recorder OpenFGA selector artık `01KW0EJTM60YGZTEKNGS7PDPNP` ve `meeting#can_record` içeriyor; PR-2 `recording-access` source/runtime evidence `platform-backend#765`, `platform-k8s-gitops#2038` ve deploy run `28206874588` ile testai'da kayıtlı. `platform-backend#767` later source-cleanup olarak temporary admin GET-by-id relaxation'ı kaldırdı; bu source/test hardening'dir, backend image rollout veya tokened recorder matrix acceptance yerine geçmez. `platform-backend#716` audio-gateway audience/capability enforcement için backend source package + fail-closed evidence verifier/runbook var; test desired-state booleans artık enforce flip'e gider, fakat token-drain/maintenance-window kanıtı + live rollout + no-token/wrong-audience/missing-role/valid-recorder matrix hâlâ açık. `platform-ai#156` için test ortamında DB retention cleanup smoke deployed meeting/transcript servislerinde metadata-only destruction audit ile kanıtlı; `platform-ai#211` retention gate artık source-only MinIO lifecycle script/issue evidence'ını active kabul etmez; `platform-ai#212` test MinIO metadata-only lifecycle runtime export evidence'ını ekledi. 2026-06-27 kuralı eski legal-status-blocker yorumunu supersede eder: VERBIS/legal owner acceptance paralel legal track'tir, mühendislik blocker'ı değildir; production lifecycle/deletion proof ve G-COMP engineering readiness hâlâ açık kalır. `platform-ai#207` meeting-ai `/ask` transcript+question redaction guard source hardening'i ekledi; `platform-ai#208` action-item owner attribution'ı aynı cited source sentence'e bağlayıp unsupported owner'ı `owner=null` + `rejected_claims[].kind=action_owner` olarak sınırlar; `platform-ai#209` unsupported `/ask` generated answer prose'unu fixed no-evidence cevapla fail-closed saklar; `platform-ai#213` meeting-ai summary prose'unu citation guard'dan geçirip unsupported summary cümlelerini `rejected_claims[].kind=summary` altında saklar; `platform-ai#214` action-item due-date attribution'ı aynı cited source sentence içinde kopya phrase olarak desteklenirse gösterilir; unsupported/reformatted/normalized tarihleri `due_date=null` + `rejected_claims[].kind=action_due_date` olur. `platform-ai#215` fact-fusion/single-source guard ekleyip destekli cümleyle unsupported ayrı olguları birleştiren karar/aksiyon/özet/Ask-AI prose'unu saklar ve response contract `5-adr0043`e çıkar. `platform-ai#221` bu guard'ı precision-first hale getirip kısa unsupported business fact'leri toleransla geçirmeyi kapatır; mock `/ask` retrieval ayrı olsa da user-visible cevap hâlâ `ground_claim()` acceptance gate'inden geçer. `platform-ai#222` owner/due-date phrase eşleşmesini word-boundary seviyesine indirip substring false-positive attribution'ları kapatır. `platform-ai#227` G-INT pilot sample metadata contract'ını hash + positive sample count ile bağladı. `platform-ai#210` diarization backend decision'ı pilot DER + lisans/deployment + non-biometric metadata gate'ine bağlar. `platform-ai#191` Denetim deploy mirror drift/update-script reliability scope kapandı: Denetim deploy clone `platform-ai/main=2f97d2fbf99d65850194d91a12f7d5bc87f921a3` ile `HEAD=ORIGIN_MAIN`, `update.ps1 -NoRestart` ve `drift-guard.ps1` PASS, scheduled task'lar running; bu yalnız deploy-clone reliability kanıtıdır. Bu G-INT/T-B/source/deploy-hardening zinciri pilot acceptance veya backend/model seçimi yerine geçmez. Tokened object-level matrix, #198 Denetim app-mTLS central endpoint policy, #188 compute-plane audit live smoke, #182 direct audio e2e, desktop mic/loopback ve WG-B+ I3 management-audit gate hâlâ ayrı kanıt ister.
>
> **2026-06-26 #222 addendum**: `platform-ai#222` meeting-ai owner/due-date attribution phrase matching'i raw substring yerine word-boundary seviyesine indirdi; bu yalnız G-INT source precision hardening'dir ve pilot G-INT acceptance yerine geçmez.
>
> **2026-06-26 #226/#182 runtime addendum**: `platform-ai#226` Zeynep approval sonrası merge edildi (`58728b289d40a7cf9f9d59bc65a796fb895f1b09`), main CI `28240240432` success, Denetim GPU host `update.ps1` ile bu SHA'ya pinlendi; `platform-ai-live-stt`/`platform-ai-meeting-ai` task'ları Running, live-stt local health `status=ok`/`device=cuda`/`compute=float16`, log tail `Transcribe success`. #226 WorkerTimeoutError source/runtime slice böylece Denetim runtime'a uygulanmış kabul edilir. Later truth supersedes the older `platform-backend#768 review/merge/deploy` blocker: #768 is merged/deployed through the default-off #2061/#2062/#2063/#2065 chain. Current #182 path is approved credential seed authority -> ESO mapping -> pre-flag mTLS enablement preflight PASS -> `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true` flag flip -> fresh direct-STT e2e (`HTTP 200`, `DIRECT_STT_TRANSCRIPT_RESULT`, same-session audit, no raw-audio persistence).
>
> **2026-06-26 #227/I7 refresh addendum**: `platform-ai#227` Zeynep approval sonrası merge edildi (`7904dc915c985454ab39a02d169320e757c8ed85`) ve main CI `28241477589` success. Bu yalnız G-INT pilot sample metadata hardening'dir (`sample_manifest_hash`, `sample_count_hash`, positive `n_samples`, `eval_set_hash`, `prompt_hash`); gerçek pilot G-INT acceptance değildir. Operatör ESET/endpoint allow-log sonrası Denetim `8243` preflight da staging-sw kaynaklı yenilendi: route `10.99.0.2 dev wg0 src 10.99.0.1`, TCP/8243 reachable, valid client cert `/health` HTTP 200, no-client `certificate required` fail-closed, wrong-client `unknown ca` fail-closed. `10.99.0.2:8343` hâlâ timeout ve mevcut Caddyfile'da meeting-ai 8343 server block yok; full I7 prod-gate açık kalır.
>
> **2026-06-26 #229/#230 addendum**: `platform-ai#229` merged (`b4f86b1c8ae9e77ae41846eaf834cc2ea0fa5b50`, main CI `28260265821` success) and now requires G-INT citation coverage plus verified-summary evidence. `platform-ai#230` merged (`87b3f22022602f9fa853371511e08b0fada82550`, main CI `28260320293` success) and now requires explicit G-WER/DER denominator thresholds (`minWerSamples`, `minDerSamples`, `minWerRefWords`). Both PRs had provider-separated Claude Cross-AI review with no P0/P1 blockers after fixes. Boundary: source-side false-acceptance guard only; no real pilot WER/DER, no real pilot G-INT, no direct-STT e2e, no model/backend selection, no LLM enablement, no production readiness.
>
> **2026-06-26 direct-STT pre-flag verifier addendum**: `scripts/faz24/verify_direct_stt_mtls_enablement_preflight.py` adds a metadata-only gate for the exact point after Vault/ESO secret delivery and before `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true`. It requires real `audio-gateway` pod evidence while the flag is still false: hostAlias `live-stt.denetim -> 10.99.0.2`, narrow `10.99.0.2/32:8243` NetworkPolicy, `/etc/direct-stt-mtls` mount, ESO mappings for the three direct-STT Vault properties, runtime Secret key names for `direct-stt-*.crt/key`, and mTLS `/health` HTTP 200 using the mounted client cert. It rejects PEM/token/raw-output/destination URL/raw-audio/transcript evidence and keeps #182 e2e, #198 full I7, desktop mic/loopback, and production readiness separate.
>
> **2026-06-27 direct-STT preflight collector addendum**: `scripts/faz24/collect_direct_stt_mtls_enablement_preflight.py` now collects the same pre-flag gate from live Kubernetes metadata without emitting values: explicit `k3d-test` context, `platform-test` namespace reachability, `audio-gateway` pod readiness, hostAlias, NetworkPolicy, `/etc/direct-stt-mtls` mount, ExternalSecret mapping names, runtime Secret key names, and bounded mTLS `/health` status/timing. Later 2026-06-27 hardening splits direct-STT mTLS material into dedicated `audio-gateway-direct-stt-mtls` so missing cert/key seed cannot poison the Redis aggregate `audio-gateway-secrets`; preflight now requires that dedicated ExternalSecret/Secret to be Ready, mounted, not envFrom-exported, and carrying `direct-stt-ca.crt`, `direct-stt-client.crt`, and `direct-stt-client.key`. Context guard evidence uses `environment.contextAvailable`, `environment.namespaceReachable`, and `environment.contextFailure`; a missing local `k3d-test` context is execution-environment failure, not runtime drift proof. #182 e2e remains gated on seed -> preflight PASS -> flag flip -> `/transcribe` evidence.
>
> **2026-06-27 direct-STT verifier hardening addendum**: `scripts/faz24/verify_direct_stt_mtls_enablement_preflight.py` and `scripts/faz24/verify_direct_stt_e2e_evidence.py` now reject camelCase sensitive-key bypasses (`destinationUrl`, `transcriptText`), URL-like values, base64 audio data URIs, PEM/token/raw-output/audio/transcript payloads. The e2e gate also requires `tokenIncluded=false`, `environment.podReady=true`, explicit mTLS probe host/port `live-stt.denetim:8243`, and `directClientToStt=false`. This is source-side false-acceptance hardening only; no credential seed, flag flip, `/transcribe` run, or #182 acceptance is claimed by this addendum.
>
> **2026-06-27 direct-STT operator handoff addendum**: `scripts/faz24/build-direct-stt-operator-handoff.py` and workflow `faz24-direct-stt-operator-handoff.yml` now package the remaining #182/#1615 operator sequence as a metadata-only handoff artifact (`README.md` + manifest + `SHA256SUMS`). It orders credential seed -> preflight PASS -> reviewed flag flip -> e2e PASS -> reviewer acceptance. This is coordination packaging only; it does not read/write Vault, mutate Kubernetes, touch Denetim PC, enable direct-STT, call `/transcribe`, send audio, or advance #182/#1615.
>
> **2026-06-27 direct-STT self-hosted preflight collector addendum**: workflow `faz24-direct-stt-mtls-preflight-collect.yml` now runs `collect_direct_stt_mtls_enablement_preflight.py` plus the existing verifier on the self-hosted `staging-sw` runner. It provides a canonical no-mutation Gate 1 evidence path after approved Vault/ESO seed and before the direct-STT flag flip, uploading a metadata-only artifact even for fail-closed blocker evidence while keeping the workflow red unless the verifier passes. This does not seed credentials, mutate Kubernetes/Vault/Caddy/firewall, enable direct-STT, call `/transcribe`, send audio, or advance #182/#1615 by itself.
>
> **2026-06-27 external-recorder operator handoff addendum**: `scripts/faz24/build-external-recorder-operator-handoff.py` and workflow `faz24-external-recorder-operator-handoff.yml` now package the remaining external meeting-admin + recorder lifecycle sequence as a metadata-only handoff artifact (`README.md` + manifest + `SHA256SUMS`). It orders approved short-lived `platform-desktop` token file -> token-contract PASS -> external recorder smoke PASS -> verifier PASS -> G-CAP aggregate when enough verifier summaries exist. This is coordination packaging only; it does not mint/read tokens, connect to testai, mutate Keycloak/Kubernetes/Vault, run the smoke, send audio, or advance #1615.
>
> **2026-06-27 external-recorder evidence hardening addendum**: `scripts/faz24/run_external_recorder_smoke.py` and `scripts/faz24/verify_external_recorder_smoke_evidence.py` now apply the same metadata-only standard to #1996/#1997 external meeting-admin smoke evidence. Runner output omits sensitive response fields, redacts URL-like/base64-audio values, no longer writes top-level `baseUrl`, and fails closed on unsafe `sessionId`; the verifier rejects camelCase sensitive keys (`destinationUrl`), URL-like values outside token-contract `issuer`, raw audio/transcript/request/response payloads, packet captures, unsafe `sessionId`, direct client-to-STT, direct-STT transcript, compute-plane audit, and production-readiness overclaims. This is source-side false-acceptance hardening only; no token minting, live smoke, or #1615 acceptance is claimed.
>
> **2026-06-27 desktop capture evidence addendum**: `scripts/faz24/verify_desktop_capture_evidence.py` and `docs/runbooks/RB-faz24-desktop-capture-evidence.md` package the remaining desktop mic+loopback gate as metadata-only, fail-closed evidence. A passing envelope must come from a real `platform-desktop` run, prove both `microphone` and `loopback` real-device sources, visible active capture indicator, consent capture, exact public `audio-gateway` lifecycle step order, and uploaded chunk digest matches. The verifier rejects raw audio/base64 audio, transcript text, JWT/Bearer/Authorization material, destination URLs, direct client-to-STT, direct-STT transcript, compute-plane audit, and production-readiness claims. This is not a live desktop smoke by itself and does not satisfy the aggregate G-CAP reliability threshold by itself.
>
> **2026-06-27 desktop capture operator handoff addendum**: `scripts/faz24/build-desktop-capture-operator-handoff.py` and workflow `faz24-desktop-capture-operator-handoff.yml` now package the remaining real `platform-desktop` microphone + loopback sequence as a metadata-only handoff artifact (`README.md` + manifest + `SHA256SUMS`). It orders real desktop run -> redacted evidence review -> desktop verifier PASS -> G-CAP aggregate when enough verifier summaries exist. This is coordination packaging only; it does not run the desktop app, read tokens, connect to testai, mutate Kubernetes/Vault, send audio, or advance #1615.
>
> **2026-06-27 product-gate operator handoff addendum**: `scripts/faz24/build-product-gate-operator-handoff.py` and workflow `faz24-product-gate-operator-handoff.yml` now package the remaining G-CAP/G-OPS/G-COMP evidence sequence as a metadata-only handoff artifact (`README.md` + manifest + `SHA256SUMS`). It orders redacted evidence selection -> G-CAP aggregate verifier + ingest wrapper -> G-OPS verifier + ingest -> G-COMP verifier + ingest -> reviewer acceptance. Existing external-recorder and desktop handoff G-CAP ingest commands now submit a `{"reports":[...]}` wrapper built from verifier summaries, not the aggregate verifier output. This is coordination packaging only; it does not collect live evidence, run a pilot, mutate Kubernetes/Vault/firewall/legal state, ingest evidence, claim legal go, or advance #1615.
>
> **2026-06-27 G-CAP desktop aggregation addendum**: `scripts/faz24/verify_gcap_capture_gate_evidence.py` now accepts both `faz24.externalRecorderSmokeVerifier.v1` and `faz24.desktopCaptureEvidenceVerifier.v1` summaries. It still rejects raw external-recorder and raw desktop evidence envelopes, raw audio/transcript/token material, direct-STT, compute-plane audit, and production-readiness overclaims. Aggregate G-CAP can therefore count desktop capture attempts after the desktop verifier has produced a redacted PASS summary, but a single desktop PASS remains one attempt and does not by itself satisfy reliability thresholds.
>
> **2026-06-27 G-CAP external summary boundary hardening addendum**: `scripts/faz24/verify_gcap_capture_gate_evidence.py` now requires post-#2084 external-recorder verifier summaries to include `directClientToStt=false`, `directSttTranscriptProven=false`, and passed `boundary_directClientToStt` / `boundary_directSttTranscriptProven` checks. Stale pre-hardening `faz24.externalRecorderSmokeVerifier.v1` summaries no longer satisfy aggregate G-CAP success thresholds. This is aggregate false-acceptance hardening only; no live recorder smoke, desktop smoke, direct-STT, compute-plane audit, or #1615 acceptance is claimed.
>
> **2026-06-26 #716 rollout-trigger addendum**: the test ConfigMap authz enforce booleans can be true while the running `audio-gateway` pod still has stale env values, because `envFrom` ConfigMap changes do not restart pods. The test overlay therefore carries `audio-gateway.acik.com/authz-enforce-rev=2026-06-26-716-enforce-v2` on the Deployment pod template. #716 live acceptance now explicitly requires pod process env proof (`AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE=true` and `AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE=true`) before the no-token/wrong-audience/missing-role/valid-recorder matrix is meaningful.

---

## 1. Vizyon

Bağımsız toplantı zekâsı platformu. Belirli bir ERP/CRM markası bu plan için ürün bağımlılığı değildir; ilk pilotlar yalnızca generic ERP/CRM adapter kontratı üzerinden map edilir. Telefon / masaüstü / Teams ses kaynaklarından:

**ERP/CRM-agnostic ürün kuralı**: Herhangi bir ERP/CRM markası, müşteri adı veya pilot adapter adı Faz 24 core product contract'ında, UI'da, API/DTO'da, acceptance gate'te veya "done" dilinde ürün bağımlılığı olarak kullanılamaz. Pilot/customer/adapter isimleri yalnız adapter konfigürasyonu, tarihsel migration/lineage dokümanı veya kanıtı, evidence paketi ya da deployment notu sınırında kalır; yeni ürün işi "generic ERP/CRM adapter" kontratıyla yazılır ve tüm ERP/CRM'lerle çalışabilirlik hedeflenir. Hiçbir ERP/CRM markası için özel prompt, parser, workflow, UI branch, feature flag, scoring rule ya da acceptance shortcut kurulmaz; pilot adaptör yalnız generic ERP/CRM adapter contract'ının bir implementasyonu olarak davranır.

- Canlı geçici transkript (2-8 sn gecikme)
- Kesinleşmiş transkript (10-20 sn bağlamlı)
- Konuşmacı ayrımı (diarization)
- Özet + karar + aksiyon LLM çıkarımı
- KVKK uyumlu retention + audit + consent

üretir. **STT compute worker yapısı** (`platform-ai`) Spring Boot orchestration arkasında konumlanır — mobile/web/desktop hiçbir zaman doğrudan Python servisine bağlanmaz.

## 2. Repo + Host Topology

> **Karar**: Faz 24 **iki-sunucu (two-server) topolojisi** — ADR-0031 (2026-06-03). `platform-ai` ayrı dedicated host'ta; diğer tüm `platform-*` servisleri staging-sw'da; mobile/desktop client kullanıcı cihazlarında.

| Repo | Rol | Host | Durum |
|---|---|---|---|
| `platform-ai` | Python STT/diarization/meeting-ai (FastAPI + faster-whisper + pyannote + LLM) | **Dedicated host (yeni)** — k3s ai-test → ai-prod; ArgoCD remote register | 🟢 live-stt-service PoC + Redis consumer source/live chain var; direct-STT transcript routing source/deploy slice `platform-ai#187` accepted; compute-plane audit smoke `platform-ai#188` accepted; #226 GPU cold-load timeout fix applied on Denetim; #229 G-INT citation coverage and #230 G-WER/DER denominator threshold hardening merged/main-green; #182 e2e still waits on credential seed + pre-flag mTLS verifier PASS + flag flip + fresh live proof |
| `platform-backend` | Spring Boot — `audio-gateway-service` (WebFlux) + `meeting-service` + `transcript-service` + `audit-event-consumer-service` | **staging-sw** k3d-test/k3d-prod | 🟢 k3d-test foundation + recorder edge lifecycle + #187 13-service transcript runtime deploy + PR-2 `recording-access` digest/readiness/stability evidence kanıtlı; #767 admin GET source cleanup merged; #716 audience/capability test desired-state enforce flip path underway, live fail-closed matrix pending; tokened object-level recorder matrix, #198 app-mTLS, direct-STT e2e ve desktop mic/loopback ayrı gate |
| `platform-web` | React + Single-SPA — `mfe-meeting` MFE | **staging-sw** (frontend serve) | ⏳ planning (Faz 24.6) |
| `platform-mobile` | **React Native + Expo** + TypeScript — iOS + Android mobile client | **Kullanıcı cihazı** (App Store / Google Play distribution) | 🟢 **scaffold LIVE 2026-06-02** (commits `a774412`+`3a609a8`) |
| `platform-desktop` | **Electron + React** + TypeScript — macOS + Windows + Linux desktop client | **Kullanıcı cihazı** (electron-updater + signed installer) | 🟢 scaffold + recorder contract source chain var; gerçek mic/loopback smoke ayrı kanıt ister |
| `platform-k8s-gitops` | Kustomize + ArgoCD GitOps + ADR-0030 + ADR-0031 + observability skeleton + WG-B+ evidence packaging | **staging-sw** ArgoCD hub + platform-ai k3s remote cluster | 🟢 runtime desired-state + I6 MASQ evidence accepted (`#1867` Done); I3 management-audit package lane main'de ama `#1864` `Needs Verify` |

### 2.1 Current Runtime Boundary (2026-06-26)

- `meeting-service`, `transcript-service`, `audit-event-consumer-service`, `audio-gateway` ve Redis Streams foundation k3d-test hattında kanıtlıdır; #187 direct-STT transcript routing source/deploy slice ve PR-2 `recording-access` slice 13-service digest/readiness/stability run ile testai'a taşındı. Bu, production veya direct-STT e2e readiness iddiası değildir.
- OpenFGA runtime selector artık `01KW0EJTM60YGZTEKNGS7PDPNP`; model `meeting#can_record` içerir. Önceki recorder edge lifecycle smoke `testai.acik.com/api/v1/audio-gateway` üzerinde consent/session/chunk/finish seviyesinde kanıtlı kalır.
- Dedicated non-admin `GET /api/v1/meetings/{id}/recording-access` endpoint'i auth arkasında canlıdır ve no-token public smoke `401` döner; `audio-gateway` recorder validation artık bu endpoint'i kullanır. Tokened object-level matrix hâlâ açık: owner/participant `204`, no-recorder `403`, tenant-hidden/unknown `404`, blocked-owner `403`.
- External `POST https://testai.acik.com/api/v1/admin/meetings` hâlâ external meeting fixture creation için ayrı gateway-contract takip ister. Temporary admin GET-by-id B-narrow cleanup source-side `platform-backend#767` ile merge edildi, fakat image rollout + tokened object-level recorder matrix olmadan runtime acceptance veya `#766` closure iddiası kurulmaz.
- `platform-ai#191` Denetim deploy mirror reliability scope kapandı: source chain `#216`-`#220` ile `update.ps1`/`drift-guard.ps1` PowerShell 5.1-safe hale geldi. Son canlı deploy evidence #226 sonrası Denetim clone `HEAD=ORIGIN_MAIN=58728b289d40a7cf9f9d59bc65a796fb895f1b09`, tracked tree clean, `platform-ai-live-stt` ve `platform-ai-meeting-ai` Running, live-stt local health `status=ok`/`device=cuda`/`compute=float16`, meeting-ai `status=ok`. Bu deploy/update runtime evidence'dır; #182 transcript-result e2e veya production readiness yerine geçmez.
- `platform-ai#198` için Denetim 8243 app-mTLS immediate preflight PASS kanıtı bugünkü ESET/endpoint allow-log sonrası yenilendi: staging-sw source route `10.99.0.2 dev wg0 src 10.99.0.1`, TCP/8243 reachable, valid client cert `/health` HTTP 200, no-client `certificate required` fail-closed, wrong-client `unknown ca` fail-closed. Ancak full I7 prod-gate hâlâ meeting-ai 8343 (bugünkü `10.99.0.2:8343` probe timeout), Vault PKI rotation/secret delivery, request audit, plaintext-bypass closure, failure drill ve reviewer/operator acceptance ister.
- `platform-backend#716` için backend validator image lineage mevcut ve GitOps test desired-state enforce booleans `true` yoluna alınır; ConfigMap-only truth yeterli değildir, canlı pod process env de `AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE=true` + `AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE=true` göstermelidir. Live enforce acceptance için token-drain/maintenance-window kanıtı, pod-env rollout kanıtı, no-token/wrong-audience/missing-role/valid-recorder matrix ve reviewer/operator acceptance gerekir.
- `platform-ai#156` için deployed DB cleanup jobs test runtime smoke ile kanıtlandı: expired synthetic meeting action/decision, transcript segment ve KVKK access-audit row'ları silindi; `db.meeting-intelligence`, `db.transcript-records` ve `db.kvkk-access-log` destruction audit row'ları `metadata-only` payload ile yazıldı. `platform-ai#211` retention gate'i source-only MinIO lifecycle evidence'ını reddedecek şekilde sıkılaştırdı; `platform-ai#212` test MinIO lifecycle runtime export evidence'ını metadata-only olarak ekledi (`meeting-audio` 7d, `transcripts` 365d, `audit-archive` 2557d). Bu yalnız DB-cleanup test kanıtı + test MinIO metadata evidence'dır; production lifecycle/deletion proof ve G-COMP engineering evidence yerine geçmez. VERBIS/legal owner acceptance paralel legal track'tir; mühendislik blocker'ı değildir ve legal go olarak iddia edilmez.
- `platform-ai#207` meeting-ai `/ask` path'ini source seviyesinde sertleştirdi: transcript ve question redaction, residual PII fail-closed `422`, unsupported cloud backend için silent mock fallback yerine `501`.
- `platform-ai#208` meeting-ai action-item owner attribution guard ekledi: grounded action text korunur, ancak owner aynı cited source sentence içinde desteklenmiyorsa kullanıcıya assignee olarak gösterilmez ve `action_owner` rejection kaydı bırakılır. Bu #207/#208 zinciri yalnız G-INT source hardening'dir; gerçek pilot transcript/audio veya reviewer/operator acceptance değildir.
- `platform-ai#209` meeting-ai `/ask` unsupported-answer withholding ekledi: empty/no-info/ungrounded generated answers fixed `Metinde bu bilgi yok.` cevabına düşer ve ungrounded citation unsupported generated prose taşımaz. `platform-ai#213` summary exposure guard ekledi: yalnız citation-guard'dan geçen summary cümleleri `summary` alanında kalır, unsupported summary prose `rejected_claims[].kind=summary` olarak saklanır ve `ungrounded_count` decision/action sayacı olarak kalır. `platform-ai#214` action due-date attribution guard ekledi: `action_items[].due_date` yalnız aynı cited source sentence içinde kopya phrase olarak desteklenirse gösterilir; unsupported/reformatted/normalized tarih `due_date=null` + `rejected_claims[].kind=action_due_date` olur. `platform-ai#215` fact-fusion/single-source guard ekledi: bir cited sentence tarafından taşınmayan ayrı olgularla birleştirilmiş karar/aksiyon/özet/Ask-AI prose'u saklanır ve response contract `5-adr0043`e çıkar. `platform-ai#221` bu guard'ı precision-first hale getirip kısa unsupported business fact'leri toleransla geçirmeyi kapatır; mock `/ask` retrieval ayrı olsa da user-visible cevap hâlâ `ground_claim()` acceptance gate'inden geçer. `platform-ai#222` owner/due-date phrase eşleşmesini word-boundary seviyesine indirip `Can`/`canlı`, `IT`/`kritik`, `salı`/`Salıverme` gibi substring false-positive attribution'ları kapatır. `platform-ai#227` G-INT pilot sample metadata contract'ını `sample_manifest_hash`, `sample_count_hash`, positive `n_samples`, `eval_set_hash` ve `prompt_hash` ile bağladı. Bu #207/#208/#209/#213/#214/#215/#221/#222/#227 zinciri yalnız G-INT source hardening'dir; gerçek pilot transcript/audio veya reviewer/operator acceptance değildir.
- `platform-ai#188` same-session `CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit gate verifier PASS ile accepted/Done durumundadır. `platform-ai#182` direct-STT e2e hâlâ açık: #226 GPU timeout fix Denetim runtime'a uygulanmıştır; `platform-backend#768` artık merge/deploy edilmiş ve #2061/#2062/#2063/#2065 default-off mTLS/SNI/evidence chain hazırdır. Kalan live path: approved Vault/ESO credential seed, `verify_direct_stt_mtls_enablement_preflight.py` PASS while direct-STT is still false, `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true` flag flip, fresh `/transcribe -> DIRECT_STT_TRANSCRIPT_RESULT` evidence, same-session audit correlation ve no raw-audio persistence proof.
- WG-B+ I6 cross-server MASQ evidence accepted only for pod-CIDR-to-WireGuard transit. WG-B+ I3 management audit (`#1864`), Denetim I7 full prod-gate (`platform-ai#198`), #182 direct audio e2e and desktop mic/loopback remain separate gates; broad Faz 24 readiness olarak konuşulmaz.

## 3. 3-AI Mutabakat Noktaları (her biri 3 AI tarafından onaylı)

### 1. STT compute worker ≠ ürün API'si

`live-stt-service` iç compute worker'dır; mobile/web hiçbir zaman doğrudan `platform-ai`'a bağlanmaz.

**Neden**: Auth / tenant / audit / permission / KVKK pattern'leri Spring Boot Gateway'de tutulur. `live-stt`'ye client WebSocket koymak = yanlış ownership boundary + deprecation borcu.

### 2. Audio Gateway Contract 1.0 ÖNCE kilitlenir

PR-stt-02 ve PR-gw-01 **eş zamanlı yapılmaz**. Önce Gateway Contract 1.0 freeze, sonra STT entegre.

**Neden**: Contract drift riski — STT iki yere bağlı (kendi `/transcribe` + Gateway şekli), drift sessizce yanlış kontrat üretir.

### 3. Observability GOP başı

Correlation id + redacted structured log + audit event boundary + metric isimleri Gateway Contract ile **birlikte** tanımlanır — sonraki PR'a ertelenmez.

**Neden**: KVKK çerçevesinde audit trail PR-stt-02'den itibaren işlemeli. "Dashboard sonra" diyebilirsin ama "correlation id sonra" diyemezsin.

### 4. KVKK engineering controls ADR ŞART

Ayrı `ADR-0030 KVKK boundary for Meeting Intelligence` — owner notification, parametric retention, consent, deletion, access boundary, audit sorumluluğu ve legal-track parallelism.

**Neden**: Ses + transcript = KVKK Madde 6/9 hassas/özel kategori veri. Sonradan ekleme = compliance riski.

### 5. Transcript ≥ Ses (KVKK ek)

KVKK ADR'ye transcript için **ayrı boyut**: kim okuyabilir (participant / company IT admin / rapor), export sınırı, katılımcı consent ↔ şirket IT access sınırı.

**Neden**: Transcript metin halinde dolaşıma daha açık (kopyala-yapıştır, e-posta, rapor) — ses kaydı kadar koruma kritik.

### 6. `language` ZORUNLU başlangıçtan (ISO 639-1)

Gateway Contract 1.0'da `language` required field; `tr` sadece local/dev default. Product API explicit gönderir.

**Neden**: Bağımsız ürün müşteri çeşitliliği multi-dil destek gerektirir. Sonradan eklemek = breaking change retroaktif.

### 7. Worker isolation = b + d kombinasyonu

- **b**: STT tarafında supervised subprocess (multiprocessing.Process); timeout = process kill semantic + temiz worker re-start
- **d**: Gateway + Redis bounded queue + admission control + hızlı reject

**Neden**: `asyncio.wait_for` yalnızca HTTP client'a cevap; worker thread arka planda CPU+model lock tutmaya devam edebilir. `ProcessPoolExecutor` `future.cancel()` çalışan native inference'ı öldürmez.

### 8. WER PoC = Common Voice TR + gerçek pilot meeting (triangulate)

Sentetik TTS yalnızca pipeline smoke/CI (WER claim için kullanılmaz).

**Neden**: Sentetik "okuma" sesi meeting domain'i (overlap, duraksama, aksan, arka plan) yansıtmaz.

### 9. Two-host resource pressure acceptance gate (ADR-0031 update 2026-06-03)

PR-stt-02 e2e öncesi **iki host için ayrı baseline** (Codex `019e8c09` iter-2 absorb):

- **Gate A — staging-sw orchestration plane**: `free -m` + `kubectl top` baseline + Faz 22-23 paralel çakışma notu (audio-gateway-service + meeting-service + transcript-service + Faz 22.5 PR-D2.5 + Faz 23 notify aynı host)
- **Gate B — platform-ai compute plane**: Model warm-load sonrası RAM/CPU/GPU baseline + worker count + inference p95 + queue consume lag (live-stt-service dedicated host'ta — Faz 22-23 ile yarışmaz)

**Neden**: staging-sw 23 GiB RAM / 6.2 GiB available + Faz 22-23 paralel = Gate A sıkı. platform-ai dedicated host kendi resource bütçesi var (Gate B); sessiz capacity exhaustion riski iki host için ayrı doğrulanır.

### 10. Multi-tenant readiness placeholder

Faz 24.1 MVP tek müşteri OK, ama ADR-0030'da "future multi-tenant readiness" placeholder — tenantId metadata + auth token validation Gateway seviyesinde.

**Neden**: Yeni müşteri/tenant girişi geldiğinde retroactively eklemek pahalı.

---

## 4. 3 RED (yapılmayacak — Codex + Mavis ortak)

1. ❌ **Gateway contract kilitlenmeden** mobile/Web veya STT WebSocket contract yazılması
2. ❌ **ADR-0030 engineering controls + owner notification olmadan** gerçek müşteri meeting kaydı kullanılması
3. ❌ **Synthetic WER ile** model kararı kapatılması

---

## 5. Faz 24 Akış (3-AI sabit + ADR-0031 two-server topology)

> **Not (2026-06-05 Codex `019e97bb` REVISE absorb)**: §5 akış diyagramı **backend/STT critical path** sırasını gösterir (Adım 0 → PR-gw-01 → PR-stt-02 → PR-stt-03 → PR-gw-01C → PR-obs-01 → PR-wer-01 → PR-final-stt-01 → PR-gpu-01). Client plane işleri (Mobile = Faz 24.11, MFE = Faz 24.12, Desktop = Faz 24.13) PR-gw-01C LIVE testai sonrası **paralel cross-repo lane** olarak §6 cross-repo bağımlılık tablosunda izlenir; STT worker sırasının parçası değildir.

```
Adım 0  (gitops PR #1207 + #1233 MERGED 2026-06-03)
   ├─ ADR-0030 KVKK Meeting Intelligence boundary (placeholder + §"Cross-Server STT Transit Boundary" 2026-06-03)
   ├─ ADR-0031 Two-Server Topology — platform-ai compute plane + staging-sw orchestration plane (ACCEPTED 2026-06-03; gitops PR #1233 MERGED)
   ├─ Observability/Audit GOP skeleton (correlation id + log + metric + audit event contract)
   └─ PLAN.md Faz 24 satırı + canonical plan (bu doküman)
        ↓
ADR-0031 ACCEPTED + cross-server contract field/admission semantics canonical (blocker — PR-gw-01 öncesi; Codex `019e8c09` iter-2 absorb)
        ↓
PR-gw-01  Audio Gateway Contract 1.0 freeze (platform-backend) — source-level contract; physical host gerek YOK
   fields: language (ISO 639-1) + correlation_id + meeting_id + session_id + tenant_id + user_id + auth + audio chunk metadata + admission contract + cross-server contract field/admission semantics (ADR-0031 §D2)
        ↓
platform-ai dedicated host provision + k3s ai-test cluster + ArgoCD remote register + Vault AppRole `ai-runtime-test` + WireGuard tunnel + mTLS PKI + Redis Streams bounded setup (blocker — gerçek meeting audio cross-server e2e için PR-stt-02 live veya PR-gw-01C öncesi; synthetic/local Docker e2e için PoC fixture istisnası açık)
        ↓
PR-stt-02  real audio + Docker e2e + Gate A/B baseline (platform-ai)
   Gateway contract uyumlu language/correlation metadata; Gate A staging-sw + Gate B platform-ai baseline; Türkçe wav fixture (Common Voice TR sample veya privacy-safe TTS); synthetic/local Docker e2e için cross-server security gate istisnası açık (private LAN fixture); gerçek meeting audio için cross-server mTLS/WireGuard ZORUNLU
        ↓
PR-stt-03  supervised subprocess worker + hard timeout kill (platform-ai)
        ↓
PR-gw-01C  audio-gateway-service Redis Streams cross-server dispatcher producer (ADR-0031 D2 cross-server network topology + D8 failure modes + plan §3 mutabakat #9) — eski PR-queue-01 scope dağıtıldı: session lifecycle + bounded in-memory registry/idempotency replay PR-gw-01A'da (`bounds.max-active-sessions: 1000` + `idempotency.replay-cache-size: 4096`; `admission-queue-capacity` property tanımlı ama şu an unused — future use için reserve), REST chunk admission PR-gw-01B-core'da, dispatcher backpressure 429/503 + Retry-After PR-gw-01B3'te (DispatchOutcome.QueueFull/Unavailable; registry mutation sadece Accepted'da), Redis Streams producer PR-gw-01C'de (`audio:chunks:p00..p31` stream keys, consumer group `live-stt-v1`, XADD per chunk, idempotency `(sessionId, chunkSeq)`), live-stt consumer ownership PR-stt-03'te (subprocess worker + Redis Streams reader — PR-stt-03 scope genişledi; ayrıca PR-stt-04 ayrı issue gerekirse ileride karar)
        ↓
PR-obs-01  Grafana/Prometheus dashboard genişletme (skeleton zaten Adım 0'da)
        ↓
PR-wer-01  Common Voice TR + gerçek pilot meeting WER raporu (ADR girdisi)
        ↓
PR-final-stt-01  final-stt-service (WER sonucuna göre model kararı; `large-v3-turbo` varsayım YOK)
        ↓
PR-gpu-01  GPU Dockerfile variant (donanım + ölçüm sonrası)
```

## 6. Cross-Repo Bağımlılık Sırası

| Repo | İş | Bağımlı |
|---|---|---|
| platform-k8s-gitops (Adım 0) | ADR-0030 + ADR-0031 + obs skeleton + PLAN.md | yok (gitops PR #1207 + #1233 MERGED 2026-06-03) |
| platform-backend | PR-gw-01 Gateway Contract 1.0 freeze (source-level contract, physical host gerek YOK) | Adım 0 MERGED + ADR-0031 ACCEPTED + cross-server contract field/admission semantics canonical |
| **platform-k8s-gitops + ops** | **platform-ai dedicated host provision + k3s ai-test cluster + ArgoCD remote register + Vault AppRole `ai-runtime-test` + WireGuard tunnel + mTLS PKI cert auth** | ADR-0031 ACCEPTED; gerçek meeting audio cross-server e2e (PR-stt-02 live veya PR-gw-01C) öncesi blocker; synthetic/local Docker e2e için istisna |
| **platform-k8s-gitops + ops** | **staging-sw Redis Streams runtime setup/runbook**: streams `audio:chunks:p00..p31` (32 partition), consumer group `live-stt-v1`, persistence OFF (`appendonly no` + `save ""`); MAXLEN per stream + XADD `~` trim semantic; maxmemory + `maxmemory-policy: noeviction` (backlog fail-fast); TTL kısa; ACL/TLS/WireGuard reachability cross-server; Vault `kv/platform-ai/redis/*` secret delivery (ESO); XLEN/lag metrics Prometheus; init + reconcile runbook `docs/runbooks/redis-streams-staging-sw.md` ✅ (gitops#1447) — **LIVE 2026-06-11**: host-compose 172.19.0.250 + D29 tam yeşil (platform-ai#151) | ADR-0031 D2 + D3 + D8 ACCEPTED + PR-gw-01C contract MERGED ✅ |
| platform-ai | PR-stt-02 real audio + container e2e | PR-gw-01 MERGED |
| platform-ai | PR-stt-03 subprocess isolation | PR-stt-02 MERGED |
| platform-k8s-gitops | Kustomize base/apps/{audio-gateway,live-stt} + overlay | PR-gw-01 + PR-stt-03 source-merged |
| platform-backend | PR-gw-01C Redis Streams cross-server producer (eski PR-queue-01 absorbe) | PR-stt-03 MERGED |
| platform-k8s-gitops | PR-obs-01 dashboard + alertmanager rules (audio-gateway Prometheus + Redis Streams XLEN/lag + consumer group offsets) | PR-gw-01C MERGED + staging-sw Redis Streams setup LIVE |
| platform-ai | PR-wer-01 WER raporu | PR-stt-03 MERGED + pilot meeting kaydı |
| platform-ai | PR-final-stt-01 | WER raporu çıktısına göre |
| platform-ai | PR-gpu-01 | donanım + ölçüm sonrası |
| **platform-mobile** | **PR-mobile-01..10** (Faz 24.11 — board canonical) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| **platform-desktop** | **PR-desktop-01..10** (Faz 24.13 — board canonical 2026-06-05; client plane simetri Mobile/MFE ile) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| platform-web | mfe-meeting MFE (Faz 24.12) | PR-gw-01 MERGED + PR-gw-01C LIVE testai |
| platform-backend | meeting-service + transcript-service | PR-gw-01 ile paralel veya hemen sonra |
| platform-backend | Faz 23 notification entegre (meeting events) | M6 ortası |
| platform-backend | report-service weekly-meeting-summary | M6 sonu |

## 7. Donanım & Resource Stratejisi (2026-06-03 — ADR-0031 two-server topology)

> **Mimari karar**: Faz 24 **iki-sunucu topolojisi** ile çalışır (ADR-0031 — Codex `019e8c09` iter-1 REVISE absorb). `platform-ai` ayrı dedicated host'ta; diğer tüm `platform-*` servisleri staging-sw'da.

### İki-sunucu boundary

| Plane | Host | Workload | Sahip |
|---|---|---|---|
| **Orchestration plane** | staging-sw (23 GiB RAM, GPU YOK) | `audio-gateway-service`, `meeting-service`, `transcript-service`, `notification`, `report-service`, Faz 22-23 workloads, Redis bounded queue, Vault, ArgoCD hub, host nginx edge | Spring Boot + Java ekosistem |
| **Compute plane** | **platform-ai** (yeni dedicated server — MVP'de GPU upgrade) | `live-stt-service`, `diarization-service` (ileri faz), `meeting-ai-service` (LLM özet/karar/aksiyon), worker subprocess pool | Python + faster-whisper + pyannote + LLM client |
| **Client plane** | Kullanıcı cihazları | platform-mobile (iOS/Android) + platform-desktop (macOS/Win/Linux) + platform-web (browser) | RN/Expo + Electron + React |

Mobile/desktop/web client'lar **hiçbir zaman** doğrudan `platform-ai`'a bağlanmaz (3-AI mutabakat noktası #1 korunur). Bağlantı her zaman `audio-gateway-service` üzerinden (staging-sw → cross-server hop → platform-ai).

### Network topology (Gateway ↔ STT cross-server)

- **Redis bounded queue**: **staging-sw** (admission/rate-limit/tenant fairness Gateway boundary ownership). Transient, bounded memory, persistence **OFF**, kısa TTL, backlog threshold aşınca 429/503 fail-fast.
- **Cross-server kanal**: **WireGuard host-to-host + TLS service auth** (MVP); **mTLS / Vault PKI / SPIFFE workload identity** (production). Private LAN **yetmez** (KVKK transit hassasiyet — Codex iter-1 net).
- **STT pull model**: live-stt-service Redis'ten chunk consume eder; Gateway push (admission control sahibi).
- **Failure mode**: platform-ai unreachable → Gateway 503 fail-fast + Redis backlog kısa süre tolerate; threshold sonra admission reject.

### Resource pressure ayrımı (acceptance gate §9 ile uyumlu)

- **Gate A — staging-sw orchestration plane**: `free -m available > 2 GiB`, `kubectl top` (audio-gateway + meeting + transcript + Faz 22-23 paralel), Redis queue depth bounded, OOM/restart count 0.
- **Gate B — platform-ai compute plane**: Model warm-load sonrası RAM < %70, worker count config-aligned, GPU VRAM headroom > 2 GiB (varsa), inference p95 < 5s (PoC) / < 2s (MVP), queue consume lag < 5s.

### PoC Aşaması (Faz 24.0-24.6)

- CPU-only Whisper `medium int8` (~1.5 GB model) — **platform-ai server kendi CPU/RAM** (staging-sw Faz 22-23 ile yarışmaz)
- Tek worker, çoklu request threadpool serial (b+d isolation)
- Gate A + Gate B her e2e öncesi ölçüm dokümante

### MVP Aşaması (Faz 24.7-24.9)

- **platform-ai server kendi GPU upgrade** (örn. RTX 4070 12 GB VRAM) — vendor lock-in yok, KVKK sınır içi
- (Mevcut "Cloud GPU bridge Lambda Labs / Vast.ai" tahmini **stale** — ADR-0031 ile kayma)
- WER PoC + maliyet ölçüm platform-ai dedicated host'ta
- Production karar (GPU upgrade vs SaaS) data-driven (WER + latency + cost)

### Production Aşaması

- platform-ai dedicated host + k3s ai-prod cluster + ArgoCD remote register
- staging-sw GPU upgrade **gereksiz** (Spring Boot orchestration → CPU yeterli)
- Karar: platform-ai donanım upgrade tier (consumer-grade RTX 4070 vs server-grade A10/A100) WER + latency + cost data-driven

## 8. Risk Matrix (3-AI mutabakat sonrası)

| Risk | Önlem | Sahibi |
|---|---|---|
| Gateway contract drift (STT iki yere bağlı) | Contract 1.0 freeze ÖNCE; ayrıca contract test (consumer-driven) | PR-gw-01 |
| Worker thread leak (asyncio.wait_for) | Subprocess + hard kill semantic (PR-stt-03) | platform-ai |
| KVKK compliance (ses+transcript hassas) | ADR-0030 engineering/legal separation + owner legal-track notification + fail-closed parametric controls; hukuk/VERBIS legal track paralel | Adım 0 + G-COMP |
| **Cross-server transit ses/transcript açık** (KVKK Madde 6/9 hassas) | WireGuard + mTLS PKI ZORUNLU; private LAN yetmez; ADR-0030 §"Cross-Server STT Transit Boundary" | ADR-0031 + PR-gw-01 |
| **platform-ai host failure** (network/crash) | Gateway 503 fail-fast (`DispatchOutcome.Unavailable` + Retry-After=30) + Redis Streams MAXLEN trim drain + circuit breaker + alert | ADR-0031 D8 + PR-gw-01C contract + PR-gw-01B3 dispatcher |
| **Vault cross-server unreachable** (platform-ai → staging-sw Vault) | AppRole secret TTL cache + WireGuard tunnel health monitor + alert | ADR-0031 + ADR-0010 reuse |
| Staging resource exhaustion (Faz 22-23 paralel) | **Gate A** acceptance: `free -m`/`kubectl top` baseline staging-sw (orchestration plane) | her PR-stt-* |
| **platform-ai compute exhaustion** (model load + worker pool RAM) | **Gate B** acceptance: model warm-load + worker count + GPU VRAM (varsa) + inference p95 + queue consume lag | her PR-stt-* (Gate B yeni) |
| Türkçe doğruluk düşük kalır | Common Voice TR + pilot meeting WER triangulate (sentetik yok) | PR-wer-01 |
| Model kararı erken kilitlenir | `large-v3-turbo` varsayım yok; WER sonrası karar | PR-final-stt-01 |
| GPU yatırım atıl kalır | PoC CPU önce → ölç → GPU karar (Adım 24.7+) | PR-gpu-01 |
| Multi-tenant retroactive zorluk | ADR placeholder + tenantId reserved field şimdi | ADR-0030 |
| LLM API yurt dışı veri akışı | Option A (transcript only, no audio) → Option B (self-host) karar | pilot öncesi |
| Mobile RN/Expo test harness yetersiz | Detox e2e + Expo dev preview (browser MCP mobile için yetmez) | Faz 24.5 |

## 9. Acceptance Gates (D29 paralel — ADR-0031 two-server uyumlu)

| Layer | Gate |
|---|---|
| **Up** | Pod Running + TCP reachable + `/health` 200 (Gateway staging-sw + STT platform-ai ayrı kanıt) |
| **Functional** | `POST /transcribe` real audio fixture ile 200 + non-empty text + meta complete; cross-server WS/HTTP smoke pass |
| **KVKK-safe** | Audit event emit + log redaction verify + access RBAC enforce + retention policy applied; `audio_chunk_forwarded_to_platform_ai` audit event (ADR-0030 §"Cross-Server STT Transit Boundary") |
| **Resource-pressure-safe — Gate A (staging-sw)** | `free -m` available > 2 GiB + `kubectl top` (gateway+meeting+transcript+Faz 22-23) + Redis queue depth bounded + OOM/restart=0 |
| **Resource-pressure-safe — Gate B (platform-ai)** | Model warm-load sonrası RAM < %70 + worker count config-aligned + GPU VRAM headroom > 2 GiB (varsa) + inference p95 < 5s (PoC) + queue consume lag < 5s |
| **Cross-server transit-safe** | WireGuard tunnel UP + mTLS cert valid + Vault PKI auto-rotate alert healthy + failure drill (platform-ai down → Gateway 503 + Redis fail-fast) geçti |
| **Cross-AI peer review** | Implementer ≠ Reviewer (provider seviyesinde); thread referansı PR squash |
| **Browser smoke** | Mobile/Web kullanıcı end-to-end senaryo (Faz 24.5+ için; PoC için skip) |

## 10. Cross-AI Mutabakat Trail

| Karar | Codex `019e879c` | Mavis msg | Claude |
|---|---|---|---|
| live-stt = compute worker, ürün API değil | RED 1+2 | AGREE | AGREE |
| Gateway Contract 1.0 freeze önce | iter-3 AGREE/REVISE | msg `74` PARTIAL + msg `78` AGREE | AGREE |
| Observability GOP başı | iter-3 AGREE | msg `74` vurgu | AGREE |
| KVKK engineering controls ADR şart | iter-3 AGREE | msg `74` ŞART | AGREE; 2026-06-27 Claude review legal-track parallelism'i fail-closed parametric controls şartıyla kabul etti |
| Transcript = ses koruma kapsam | (örtük) | msg `78` C önerisi | AGREE |
| `language` ZORUNLU + Gateway Contract field | iter-3 REVISE | msg `74` C | AGREE |
| Worker isolation b + d | iter-1 critical note | msg `74` AGREE | AGREE |
| WER triangulate (Common Voice + pilot) | iter-1 H matrisi | msg `74` AGREE | AGREE |
| Staging resource pressure gate | iter-3 AGREE | msg `74` B eksik risk | AGREE |
| Multi-tenant placeholder | (örtük) | msg `78` B tek eksik | AGREE |
| **Two-server topology** (ADR-0031) | `019e8c09` iter-1+iter-2+iter-3 REVISE absorb → **iter-4 AGREE final** ("merge blocker bulmadım") | msg `78` AGREE final 2026-06-03 (ADR-0031 mutabakat closed) | AGREE (kullanıcı 2026-06-03 mimari notu) |

## 11. Sektör-Standardı Yol Haritası (bağımsız ürün)

> **Kapsam**: Faz 24 artık belirli bir ERP'ye gömülü özellik olarak değil, Türkiye ve regüle/veri-hassas enterprise pazarına satılabilir bağımsız meeting-intelligence ürünü olarak planlanır. Rakip paritesi Otter, Fireflies, Gong, Teams Copilot ve Zoom AI Companion sınıfına göre okunur; farklılaşma ise Türkçe-first kalite, self-host/on-prem opsiyon, KVKK governance ve citation'lı intelligence kombinasyonudur.

> **2026-07-15 I3 least-privilege addendum**: WG-B+ I3 için
> `svc-denetim-agent` yetkisini genişletmek yerine LocalSystem collector ->
> sanitize edilmiş atomik snapshot -> salt-okunur SSH evidence zinciri seçildi.
> `faz24.wg-bplus.i3.audit.v2` kaynak adayı ve Validate/Apply/Rollback operator
> paketi #2434 altında ilerliyor. Bu, on-prem/self-host operability için gerekli
> uzun vadeli G-OPS altyapısıdır; canlı Denetim hostuna uygulanmış değildir,
> #1864 `Needs Verify` durumunu veya ürün-değer gate'lerini değiştirmez. Paket
> geniş inbound firewall çakışmalarını otomatik değiştirmez; bunun için ayrı,
> etkisi incelenmiş ve rollback'i tanımlı operatör işlemi gerekir. Verifier
> eşikleri artefaktın bildirimine bırakmaz, doğrulama anında freshness'i yeniden
> hesaplar ve staging korelasyonunu yalnız mevcut SSH denemesinin rastgele audit
> kimliğine bağlar. Canonical hedef `svc-denetim-agent@10.99.0.2` olarak sabittir;
> staging rotası seçili WireGuard arayüzüne, Windows snapshot dizin/dosya ACL'i
> salt-okunur transport kimliğine, zaman senkronu dil-bağımsız w32time `Type`
> ayarına ve firewall kuralları tüm kritik filtre alanlarına birebir bağlanır.
> Sağlayıcı istişaresi yalnız gerçek Claude ve Mavis/MiniMax
> CLI/daemon yoluyla kabul edilir; UI veya simülasyon istişare kanıtı değildir.

### 11.1 Kazanma Formülü

Savunulabilir pozisyon: **Türkçe-first + on-prem/self-host + compliance-grade governance + kaynaklı intelligence**. Tek başına STT, tek başına chat/summary veya tek başına self-host yeterli değildir. Hedef wedge, yatay self-serve SaaS değil; kamu, finans, sağlık, savunma, hukuk ve yönetim kurulu gibi veri hassasiyeti yüksek enterprise segmentleridir.

Current diagnosis:

- Altyapı hattı ileri: gateway, Redis Streams, meeting/transcript/audit services, OpenFGA selector ve recorder edge lifecycle evidence var.
- Ürün-değer hattında source-side guardrail ilerledi: G-WER/DER verifier (`platform-ai#199`), G-WER/DER denominator threshold hardening (`platform-ai#230`), G-INT verifier (`platform-ai#200`), G-INT sample/citation coverage hardening (`platform-ai#227` + `platform-ai#229`), meeting-ai `/ask` redaction hardening (`platform-ai#207`), meeting-ai action-owner grounding (`platform-ai#208`), meeting-ai unsupported-answer withholding (`platform-ai#209`), meeting-ai summary exposure guard (`platform-ai#213`), meeting-ai action due-date grounding (`platform-ai#214`), meeting-ai fact-fusion/single-source grounding (`platform-ai#215`), meeting-ai strict materiality + attribution phrase-boundary guards (`platform-ai#221` + `platform-ai#222`), diarization backend decision gate (`platform-ai#210`), retention readiness gate (`platform-ai#201` + MinIO runtime-evidence hardening `platform-ai#211` + test MinIO runtime evidence `platform-ai#212`), Redis control-plane cleanup (`platform-ai#202`), recording/archive RED boundary (`platform-ai#203`), G-LAT/COST verifier (`platform-ai#204`), G-CAP aggregate capture gate with external-recorder + desktop-verifier input support (`scripts/faz24/verify_gcap_capture_gate_evidence.py`), desktop mic+loopback evidence verifier (`scripts/faz24/verify_desktop_capture_evidence.py`), G-COMP aggregate compliance gate (`scripts/faz24/verify_gcomp_compliance_gate_evidence.py`) ve G-OPS operability gate (`scripts/faz24/verify_gops_operability_gate_evidence.py`) main'de. #156 DB-cleanup runtime slice test ortamında metadata-only destruction audit ile kanıtlandı; test MinIO lifecycle runtime export evidence da metadata-only olarak eklendi. 2026-06-27 kuralıyla VERBIS/legal owner acceptance legal track'te paralel kalır ve mühendislik blocker'ı değildir; G-COMP engineering evidence owner notification + fail-closed parametric controls + redaction/audit/deletion evidence ister. Buna rağmen gerçek pilot WER/DER, gerçek pilot G-INT, pilot G-LAT/COST, live aggregate G-CAP evidence, production lifecycle/deletion proof, live G-COMP engineering evidence, direct-STT e2e ve canlı desktop mic/loopback verifier PASS hâlâ açık.
- Acceptance dili bu ayrımı korur: infrastructure evidence, market-ready product evidence yerine geçmez.

### 11.2 Capability Tracks

| Track | Kapsam | Sektör boşluğu | Öncelik | Ana repo |
|---|---|---|:--:|---|
| **T-A Capture** | Teams/Calendar bot, Zoom/Meet bot, desktop recorder production smoke, browser upload fallback; desktop mic+loopback acceptance `scripts/faz24/verify_desktop_capture_evidence.py` ile ayrı metadata-only gate | Bot/capture yoksa ürün dosya-yükleme aracı seviyesinde kalır | P0 | backend + desktop/web/mobile |
| **T-B Quality** | Türkçe WER harness, gerçek toplantı benchmark, diarization DER, speaker→person mapping, latency/cost/throughput gate; `gwer_gate.py` + `glat_cost_gate.py` + `diar_decision_gate.py` source-side gates main'de, pilot evidence ve backend decision evidence bekliyor | Türkçe doğruluk, diarization ve ölçülü latency/cost rakip paritesinin temel kanıtı | P0 | `platform-ai` |
| **T-C Intelligence** | Özet, karar, aksiyon, owner/date extraction, citation/timecode, transcript Q&A; `gint_gate.py` source-side gate main'de, gerçek pilot evidence bekliyor | Asıl ürün değeri; regüle pazarda her çıkarım kaynağa bağlanmalı | P0 | `platform-ai` + backend |
| **T-D Compliance Productization** | ADR-0030 engineering/legal separation, owner legal-track notification, consent UI, parametric retention/legal-hold, access matrix, audit export, on-prem install pack; #156 DB cleanup test evidence + test MinIO metadata-only lifecycle evidence var, #185 recording/archive RED boundary ve G-COMP/G-OPS source-side verifier'ları hazır. VERBIS/legal owner acceptance paralel legal track'tir; live G-COMP engineering evidence ve prod lifecycle/deletion proof bekler | Bu pazar için farklılaşma noktası; doküman değil ürün yüzeyi olmalı | P1 | gitops + web + backend |
| **T-E Integration Parity** | Webhook, CRM/Jira/CSV/export, notification follow-up, calendar/task sink | Diferansiyatör değil ama enterprise satışta eksiklik gibi görünür | P2 | backend + web |

Deferred by design:

- Üç client'ta erken tam parite; önce capture + desktop/web reliable path.
- Canlı altyazı latency takıntısı; önce transcript/intelligence correctness.
- GPU/model kararını WER/latency/cost ölçümü olmadan kilitlemek.
- Self-host LLM'i tek opsiyon yapmak; transcript-only özel bulut modu opsiyon olarak kalabilir.

### 11.3 Product Quality Gates

| Gate | Evidence |
|---|---|
| **G-WER/DER** | Gerçek Türkçe toplantı setinde WER ve diarization DER hedefi; `platform-ai#199` gate synthetic/Common Voice kanıtı acceptance yerine kullanmayı bloklar; `platform-ai#230` explicit denominator thresholds (`minWerSamples`, `minDerSamples`, `minWerRefWords`) olmadan küçük/lucky pilot satırlarının pass üretmesini engeller; `platform-ai#210` diarization backend/model decision'ı approved pilot DER + lisans/deployment + non-biometric metadata gate'ine bağlar |
| **G-INT** | Faithfulness + action-item precision/recall + owner/date accuracy; her summary/action citation/timecode ile bağlanır; `platform-ai#200` gate synthetic/mock kanıtı pilot acceptance yerine kullanmayı bloklar, `platform-ai#213` source-side summary prose exposure guard ekler, `platform-ai#214` due-date attribution'ı aynı kaynak cümlede kopya phrase yoksa `due_date=null` + `action_due_date` rejection olarak saklar, `platform-ai#215` fact-fusion guard ile tek cited sentence tarafından taşınmayan fused karar/aksiyon/özet/Ask-AI prose'unu saklar, `platform-ai#221` kısa unsupported business fact'lerin uzun grounded claim içinde toleransla geçmesini kapatır, `platform-ai#222` owner/date phrase eşleşmesini raw substring yerine word-boundary seviyesine indirir, `platform-ai#227` pilot sample metadata'yı manifest/count hashleri ve positive `n_samples` ile bağlar, `platform-ai#229` citation coverage + verified-summary evidence ister; gerçek pilot evidence ve operator acceptance olmadan pass üretmez |
| **G-CAP** | Teams/Calendar veya desktop recorder ile kayıt başlatma, consent alma, chunk upload, finish ve failure/retry oranı ölçülü; `scripts/faz24/verify_gcap_capture_gate_evidence.py` yalnız redacted verifier summary'lerini (`faz24.externalRecorderSmokeVerifier.v1`, `faz24.desktopCaptureEvidenceVerifier.v1`) aggregate eder, raw recorder/desktop evidence kabul etmez; external recorder summary'leri post-#2084 `directClientToStt=false` + `directSttTranscriptProven=false` boundary/check set'ini taşımadan aggregate success sayılmaz; `.github/workflows/faz24-product-gate-evidence-ingest.yml` bu kanıtı artifact'li no-mutation ingest path'e taşır, live pilot evidence bekler. Desktop mic+loopback smoke için ayrı `scripts/faz24/verify_desktop_capture_evidence.py` PASS gerekir; bu PASS aggregate G-CAP threshold'unu tek başına sağlamaz |
| **G-COMP** | Consent, retention, legal hold, access audit ve deletion/export policy canlı; ADR-0030 engineering controls accepted + legal track parallel. `platform-ai#201` retention gate source-only evidence'ı reddeder, `platform-ai#211` source-only MinIO lifecycle evidence'ı active kabul etmeyecek şekilde sıkılaştırdı ve `platform-ai#212` test MinIO metadata-only lifecycle runtime evidence'ını ekledi; `platform-ai#203` raw-audio archive'i default live path'ten çıkarır. `scripts/faz24/verify_gcomp_compliance_gate_evidence.py` yalnız redacted metadata envelope'ını kabul eder ve legal acceptance yerine owner legal-track notification + fail-closed parametric retention/defaults + owner-provenance-required supplied retention values + consent required + deletion pipeline enabled + no legal/production overclaim boundaries ister; `.github/workflows/faz24-product-gate-evidence-ingest.yml` bu kanıtı artifact'li no-mutation ingest path'e taşır. #156 DB cleanup smoke ve test MinIO lifecycle export evidence var, ancak production lifecycle/deletion proof ve live G-COMP engineering/operator evidence olmadan G-COMP pass üretmez; VERBIS/legal owner acceptance paralel legal track'tir ve mühendislik blocker'ı değildir |
| **G-LAT/COST** | Latency p50/p95, queue lag, cost/dakika ve GPU/CPU utilization ölçülür; `platform-ai#204` gate lab/synthetic/Common Voice performans kanıtını acceptance yerine kullanmayı bloklar; model/GPU kararı pilot ölçüme dayanır |
| **G-OPS** | On-prem install/upgrade/backup/restore/runbook kanıtı; secret delivery ve rollback path test edilir; `scripts/faz24/verify_gops_operability_gate_evidence.py` redacted metadata envelope'ını RPO/RTO/coverage eşikleriyle gate eder, `.github/workflows/faz24-product-gate-evidence-ingest.yml` bu kanıtı artifact'li no-mutation ingest path'e taşır, live on-prem evidence bekler. WG-B+ I3 Windows yönetim-audit alt kapısı, LocalSystem'ın ürettiği sanitize snapshot'ı salt-okunur servis hesabıyla taşıyan ayrı least-privilege zinciridir; kaynak paket/CI tek başına G-OPS veya #1864 kabulü üretmez, kontrollü Apply + rollback drill + fresh v2 evidence gerekir |
| **#1615 rollup** | `scripts/faz24/verify_faz24_readiness_rollup.py` tüm alt gate'lerin redacted verifier kabulünü tek `faz24.readinessRollupEvidence.v1` zarfında fail-closed kontrol eder; `.github/workflows/faz24-readiness-rollup-evidence-ingest.yml` no-mutation artifact'li ingest path sağlar. Bu rollup child gate yerine geçmez; direct-STT, desktop capture, I3, full I7, G-OPS/G-COMP, pilot WER/DER, G-INT, G-LAT/COST, retention lifecycle ve browser/client smoke kanıtları kendi verifier'larında accepted olmadan #1615 kabulü üretmez |

### 11.4 Aşama Sırası

```text
Aşama-2 evidence line
  Gateway + Redis + foundation services + recorder edge lifecycle evidence
  Boundary: direct-STT, desktop mic/loopback and WG-B+ I3 live acceptance open; I3 v2 least-privilege source candidate is not host acceptance. I6 MASQ accepted only for pod-CIDR-to-WG metadata evidence.

Aşama-3 Core Product Value (P0)
  T-B WER/DER + G-LAT/COST + T-C G-INT + T-A G-CAP gate infrastructure main'de; gerçek pilot kanıtı pending
  Citation'lı summary / decision / action + owner/due-date metadata acceptance hattı hâlâ gerçek pilot kanıtı ister
  İlk gerçek toplantı e2e: capture -> transcript -> intelligence -> audit.

Aşama-4 Adoption + Compliance (P0/P1)
  T-A Teams/Calendar veya desktop recorder production-grade capture
  T-D consent / retention / legal-hold / access audit UX
  Raw-audio archive default-off; future opt-in only (platform-ai-scoped ADR-0036)
  ADR-0030 engineering controls + owner legal-track notification + G-COMP engineering gate evidence + on-prem installation package + G-OPS operability gate evidence.

Aşama-5 Proof
  3-5 design-partner PoC
  Türkçe benchmark raporu
  Regulated-segment reference evidence.

Aşama-6 Scale + GTM
  Tek dikey wedge seçimi
  T-E integration parity
  SaaS/private-cloud/on-prem SKU paketleme.
```

### 11.5 MVP Definition

İlk satılabilir MVP: **Teams/Calendar veya desktop capture → Türkçe transcript + diarization → citation'lı özet/karar/aksiyon → admin consent/retention/access/audit → on-prem opsiyon → basit export**. Canlı altyazı, full mobile parity, multi-platform bot paritesi ve revenue-coaching dikeyleri MVP dışıdır.

### 11.6 ADR Backlog

| ADR | Konu | Tetik |
|---|---|---|
| Capture strategy | Bot vs native recorder vs desktop capture; tek güçlü initial path | T-A implementation öncesi |
| Diarization approach | pyannote/alternatif, DER ölçümü, speaker→person mapping | T-B `PR-diar-*` öncesi |
| Intelligence layer | Citation, hallucination guard, LLM routing, self-host/private-cloud sınırı | T-C `PR-llm-*` öncesi |
| ADR-0030 legal evidence package | KVKK boundary'yi hukuk/VERBIS kanıtı, consent/retention/access kararları ve audit evidence ile operasyonel acceptance'a taşıma | Gerçek customer audio/transcript PoC öncesi |
| Packaging/GTM | SaaS + on-prem lisans, regulated premium tier, backup/restore/SLA | Aşama-6 öncesi |

## References

- Codex thread: `019e879c-c51e-7691-8f16-69c781fb787e` (plan-time + iter-3 AGREE final — single-host varsayımıyla)
- Codex thread: `019e877b-bd31-72f3-b86a-229f933e51cb` (live-stt PR #1 review AGREE)
- Codex thread: `019e8c09-2cc7-7d23-a414-2c1d2950232c` (ADR-0031 two-server topology iter-1 REVISE absorb)
- Codex/Claude sector-roadmap handoff: PR #1614 historical input, refreshed on `origin/main` with 2026-06-25 runtime boundaries
- Mavis msgs: `74` (PARTIAL historical) → `76` (absorb wait historical) → `78` (AGREE final 2026-06-03 — ADR-0031 cross-AI mutabakat closed); HARD RULE Cross-AI Peer Review provider seviyesinde Anthropic + OpenAI yeterli, MiniMax non-blocking
- ADR-0030 KVKK Meeting Intelligence Boundary (placeholder + §"Cross-Server STT Transit Boundary" eklendi 2026-06-03)
- **ADR-0031 Two-Server Meeting Intelligence Topology** ACCEPTED 2026-06-03 (gitops PR #1233 MERGED — D1-D8 host boundary + network topology + resource pressure + GPU + deployment + Vault + KVKK + failure modes)
- Observability skeleton: `docs/observability-skeleton-meeting-intelligence.md`
- platform-ai PR #1 MERGED `4088d9a` — live-stt-service PoC iskelet
- platform-ai PR #199 MERGED `243de9d` — G-WER/DER gate verifier
- platform-ai PR #200 MERGED `7cc2612` — G-INT gate verifier
- platform-ai PR #213 MERGED `4648bd5` — #162 meeting-ai summary exposure guard
- platform-ai PR #214 MERGED `d82f7a0` — #162 meeting-ai action due-date attribution guard
- platform-ai PR #215 MERGED `d84befa` — #162 meeting-ai fact-fusion / single-source materiality guard
- platform-ai PR #221 MERGED `28c483a` — #162 meeting-ai strict materiality guard
- platform-ai PR #222 MERGED `5b7149e` — #162 meeting-ai attribution phrase-boundary guard
- platform-ai PR #229 MERGED `b4f86b1` — #162 G-INT citation coverage evidence gate
- platform-ai PR #230 MERGED `87b3f22` — #161 G-WER/DER denominator threshold gate
- platform-ai PR #201 MERGED `3549c28` — #156 retention readiness gate
- platform-ai PR #211 MERGED `b349cba` — #156 retention gate MinIO runtime-evidence hardening
- platform-ai PR #212 MERGED `f6d7d70` — #156 test MinIO metadata-only lifecycle runtime evidence
- platform-ai PR #202 MERGED `74d55b6` — Redis consumer control-plane semantics
- platform-ai PR #203 MERGED `546bf13` — #185 recording/archive boundary (platform-ai-scoped ADR-0036, not gitops ADR-0036)
- platform-ai PR #204 MERGED `1c9a2cc` — G-LAT/COST gate verifier
- platform-ai Issue #19 re-scope (Faz 24 two-host resource baseline — ADR-0031 ile uyumlu)
- Global HARD RULE: Cross-AI Peer Review provider seviyesinde + Plan Consensus Autonomy + No Fake Work + Türkçe cevap + Uzun Vadeli Kalıcı Çözüm
