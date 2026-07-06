# ADR-0041 — Faz 24 OpenFGA Tuple Governance (DD-EA-2 Extension to Meeting/Transcript)

> **Status**: ACCEPTED (2026-06-17), **AMENDED 2026-06-17** (Option A — UPPERCASE object id; Codex `019ed603`). Faz 24 Meeting Intelligence modüllerinin (meeting `#410`, transcript `#411`) OpenFGA tuple yazımını ADR-0012-EA **DD-EA-2** disiplinine bağlar. Test-only direct-seed bootstrap exception'ı formalize eder ve **prod-promotion blocker**'ını netleştirir. Amendment, §5 prod-promotion gate'inin permission-service yarısını (catalog + ADMIN seed + writer-path) kapatır ve test-seed object id'lerini `module:meeting/transcript` (lowercase) → `module:MEETING/TRANSCRIPT` (UPPERCASE) olarak hizalar. Bkz. **Amendment** bölümü (en alt).
>
> **Bağlantı**: [ADR-0012-EA](0012-EA-endpoint-admin-governance-charter.md) (DD-EA-2 canonical writer), [ADR-0011](0011-drift-detection-audit-cadence-boundary-governance.md) (BG-1 boundary governance / cross-service tuple discipline), [ADR-0030](0030-kvkk-meeting-intelligence-boundary.md) (KVKK boundary), [ADR-0031](0031-two-server-meeting-intelligence-topology.md) (topology). Issue gitops#1649; activation gitops#1645 + #1648.

---

## Context

ADR-0012-EA **DD-EA-2** kuralı: OpenFGA tuple writer **canonical = permission-service**. Hiçbir servis (endpoint-admin, meeting, transcript, …) OpenFGA store'a doğrudan tuple yazmaz; tuple'lar permission-service'in transactional outbox'ı üzerinden (`tuple_sync_outbox` → `TupleSyncOutboxPoller` → OpenFGA) senkronlanır (cross-service tuple discipline, ADR-0011 BG-1 ile uyumlu).

Faz 24 activation (gitops#1645) sırasında meeting-service ve transcript-service'in `@RequireModule` kapısını **fail-closed-deny'dan enforce'a** taşımak için `module:meeting` + `module:transcript` instance'ları ve grant tuple'ları (`user:<id> can_view|can_manage module:<svc>`) **doğrudan OpenFGA REST** ile seed edildi (`bootstrap/openfga/meeting-transcript-tuples.json` + `scripts/faz24/openfga-meeting-transcript-seed.sh`, meeting-service pod üzerinden curl). Enforce, OpenFGA `/check` allow/deny synthetic ile doğrulandı (gitops#1645 7/7 smoke: ALLOW + DENY + DENY-by-relation, fail-closed seed script). (Authenticated gateway-forward 200 smoke ayrı bir kapıdır; `docs/operations/services.yaml` o satırda hâlâ "pending" diyor ve ayrıca reconcile edilmelidir — bu ADR onu canlı saymaz.)

Bu direct-seed, DD-EA-2'nin canonical writer kuralının **dışındadır**. endpoint-admin için bir bootstrap artefact precedent'i var; ama orada **approved/preferred path açıkça permission-service** idi ve direct OpenFGA yalnız "permission-service admin tuple API mevcut olmadığında **test-only fallback**" olarak kayıtlıydı (`bootstrap/openfga/endpoint-admin-tuples.json` `_apply_via` + `docs/RB-22-1-1-be-009-openfga-live.md`). Faz 24 ise (permission-service modül-grant modeli henüz olmadığından) **fiilen** direct OpenFGA REST kullandı — yani bu, endpoint-admin'inkinden **daha dar ve daha explicit bir geçici exception**'dır ve bu sebeple ayrıca kayda geçirilir.

permission-service canonical mekanizması **role/granule-driven**: modül erişimi rol granule + assignment olarak ifade edilir; `TupleSyncService` `MODULE + MANAGE/VIEW/DENY`'yi `can_manage`/`can_view`/`blocked module` tuple'ına map eder. Role-permission değişiklikleri **outbox-backed** (`tuple_sync_outbox` → `TupleSyncOutboxPoller`); rol assign/revoke ayrıca **fail-loud senkron** tuple refresh yapar (`PermissionService`). Yani modül erişimi (`module:meeting can_view`) prod'da bir permission-service grant'ı olarak ifade edilmelidir ki canonical writer tuple'ı üretsin.

## Decision

1. **DD-EA-2 Faz 24 modüllerini kapsar.** `module:meeting` ve `module:transcript` tuple'ları (instance + grant) production'da **yalnız permission-service** tarafından (outbox → OpenFGA) yazılır. Meeting/transcript/audio-gateway servisleri OpenFGA'ya doğrudan tuple yazmaz (read/check serbest; write YASAK).

2. **Test-only direct-seed bootstrap exception — ACCEPTED (dar + geçici).** k3d-test cluster + `platform-test` realm'de, canlı `@RequireModule` enforce smoke'u için direct OpenFGA REST seed (`scripts/faz24/openfga-meeting-transcript-seed.sh`) **kabul edilir**. Bu, endpoint-admin precedent'inin **birebir kopyası değildir**: endpoint-admin'de preferred path permission-service, direct yalnız fallback'ti; Faz 24 modül-grant modeli henüz olmadığından fiilen direct REST kullanıyor → daha dar, daha explicit, **geçici** bir exception. Gerekçe: permission-service modül-grant modellemesi tamamlanana kadar test enforce kanıtını bloke etmemek; idempotent + fail-closed + explicit-subject + machine-enforced-invariant (§4) seed governance hijyenini korur.

3. **Production yolu = permission-service role/granule writer.** Prod-promotion'da Faz 24 modül erişimi permission-service'te **granule** olarak tanımlanır (`MODULE:MEETING`/`MODULE:TRANSCRIPT` + `VIEW`/`MANAGE`); rol/kullanıcı assignment ile `TupleSyncService` `MODULE + MANAGE/VIEW/DENY → can_manage/can_view/blocked module` tuple'ını üretir (role-permission değişimleri outbox-backed `tuple_sync_outbox`; assign/revoke fail-loud senkron refresh). Direct OpenFGA REST seed **prod realm'de YASAK**.

4. **Invariants** (test seed; seed script `scripts/faz24/openfga-meeting-transcript-seed.sh` tarafından **machine-enforced**, fail-closed):
   - `KUBE_NS == platform-test` zorunlu — başka/prod realm seed reddedilir (guard `exit 1`).
   - Wildcard subject (`user:*` / `:*` suffix) YASAK (guard).
   - Yalnız `module:MEETING` / `module:TRANSCRIPT` object'leri (guard; foreign object reddedilir). **(AMENDED 2026-06-17: lowercase → UPPERCASE, Option A — Amendment bölümü.)**
   - Test subject = numeric mock persona (committed seed: `user:1`, `user:9102`; gerçek prod kullanıcısı DEĞİL).
   - Tuple'lar canonical JSON'da tek-source (`bootstrap/openfga/meeting-transcript-tuples.json`) + post-seed `/check` allow/deny assertion.
   - Model değişikliği gerektirmez: `module` type (`can_view`/`can_manage`/`can_edit`/`blocked`) zaten var; meeting/transcript yeni instance.

5. **Prod-promotion gate (somut gap).** ~~permission catalog şu an `MEETING`/`TRANSCRIPT` modülünü **içermiyor** (`PermissionCatalogService`)~~ **(AMENDED 2026-06-17 — (a) KAPANDI: platform-backend #688)**. Prod cutover'ından ÖNCE: (a) ~~module catalog entry + default role/granule (`MODULE:MEETING|TRANSCRIPT` × `VIEW|MANAGE`)~~ **DONE (#688: catalog + ADMIN MANAGE seed + Initializer→outbox→OpenFGA `module:MEETING`/`TRANSCRIPT` UPPERCASE)**, (b) assignment akışı (`PUT /api/v1/roles/{roleId}/granules` + role/user assignment), (c) outbox→OpenFGA sync evidence + runbook **(b+c = live writer-path prod-gate evidence, staged re-seed runbook `docs/runbooks/RB-faz24-mt-uppercase-reseed.md`)**. Bu gate kapanana kadar Faz 24 modülleri **prod'a promote edilmez** (test'te direct-seed enforce LIVE kalır).

## Consequences

- **Pozitif**: Governance boundary (DD-EA-2) Faz 24 için explicit; test enforce kanıtı bloke olmadan ilerledi; prod direct-seed riski kayda geçti + gate'lendi. endpoint-admin ile tutarlı tek disiplin.
- **Negatif / maliyet**: permission-service'te modül-grant modellemesi bir **ön-koşul iş** (ayrı backend slice; bu ADR onu prescribe etmez, gate'ler). Test ve prod tuple-write yolları farklı (test=direct-seed, prod=outbox) — bu fark explicit + geçici (prod path tamamlanınca test de outbox'a taşınabilir, opsiyonel).
- **Blocker kapsamı**: Bu bir **prod-promotion blocker**'dır, test PR'larını bloke ETMEZ. Faz 24 test cluster activation (enforce LIVE) bu ADR ile uyumlu devam eder. **Exception genişletilemez**: bu dar kayıt yalnız gitops#1645 meeting/transcript içindir; yeni modül/servisin direct-seed'i ayrı karar/ADR ister (seed script guard zaten yalnız `module:meeting|transcript`'e izin verir).
- **Evidence boundary**: test direct-seed ile kanıtlanan authz enforce, prod permission-service writer path'ini **kanıtlamaz** (iki yol farklı). Prod path ayrıca §5 gate'inde (catalog + assignment + outbox sync evidence) kanıtlanır.
- **Takip işi** (bu ADR'nin dışında, ayrı issue): permission-service Faz 24 modül-access granule/catalog modeli + assignment + outbox sync + prod seed runbook. Tamamlanınca bu ADR'nin §5 gate'i acceptance ile kapanır.

## Acceptance (bu ADR için)

- [x] DD-EA-2'nin Faz 24'e uygulanması yazılı + canonical kayıtta.
- [x] Test-only direct-seed exception + invariants **machine-enforced** (seed script guard: platform-test-only + no-wildcard + module:{meeting,transcript}-only; committed JSON guard'ı geçer — `user:1`/`user:9102`).
- [x] Prod path (permission-service role/granule + assignment → TupleSyncService) + somut gap (catalog'da MEETING/TRANSCRIPT yok) netleştirildi.
- [x] (prod-promotion **a**) permission-service modül granule/catalog **DONE** (platform-backend #688: catalog MEETING/TRANSCRIPT + ADMIN MANAGE seed + tests; UPPERCASE Option A).
- [ ] (prod-promotion **b+c**) live writer-path evidence (grant → outbox DONE → `module:MEETING` tuple → meeting/transcript endpoint 200) + staged uppercase re-seed — gitops #1657, runbook `RB-faz24-mt-uppercase-reseed.md`.

---

## Amendment (2026-06-17) — Option A: UPPERCASE object id + §5 catalog half closed

> Cross-AI: Codex thread `019ed603` (plan AGREE + post-impl AGREE). Bağlı PR'lar: platform-backend **#688** (catalog + services uppercase), gitops **#1657** (test-seed/invariant/ADR + staged live re-seed).

### Sorun (keystone, bu ADR yazılırken fark edilmemişti)

Bu ADR'nin orijinal §3 prod path'i UPPERCASE `MODULE:MEETING`/`MODULE:TRANSCRIPT` granule öngörürken, §4 test-seed invariant'ı **lowercase** `module:meeting`/`module:transcript` enforce ediyordu. meeting/transcript servisleri de lowercase (`MeetingAuthz.MODULE="meeting"`) check ediyordu. permission-service **MODULE write path'i case transform YAPMAZ** (`TupleSyncService` objectId=key verbatim; `AccessControllerV1` PUT granules `key.trim()` verbatim). Dolayısıyla §3 prod path canlıya alınsaydı `module:MEETING` tuple yazılır, servis `module:meeting` check ederdi → **prod authz sessiz fail** (tuple miss → fail-closed deny). Test (lowercase) ile prod (uppercase) iki farklı object id üretip aynı servisi tatmin edemezdi.

### Karar — Option A (uppercase-align)

Tüm zincir **tek string** olacak şekilde core-module convention'ına (`module:ACCESS`/`module:AUDIT`, tümü UPPERCASE) hizalandı:

`PermissionCatalogService` catalog key == `role_permissions.permission_key` == OpenFGA object id == servis `@RequireModule` literal'i (`MeetingAuthz.MODULE`/`TranscriptAuthz.MODULE`) = **`MEETING` / `TRANSCRIPT`** (UPPERCASE).

- platform-backend #688: catalog'a MEETING/TRANSCRIPT + ADMIN'e MANAGE granule seed (IMPERSONATION_AUDIT emsali) + servis sabitleri uppercase. **Flyway YOK** — `PermissionDataInitializer` granule seed'i `RoleChangeEvent`→outbox→sync üretir (SQL üretmez).
- gitops #1657: bu ADR + `bootstrap/openfga/meeting-transcript-tuples.json` + seed script invariant `module:MEETING`/`module:TRANSCRIPT`.

### endpoint-admin emsal DEĞİL

endpoint-admin'in catalog key'i (`ENDPOINT_ADMIN`, UPPERCASE) ile OpenFGA object id'si (`endpoint-admin`, lowercase kebab) **ayrışır**; ama bu **wired bir auto-grant köprüsü değildir** (MODULE write path transform yapmadığı için UI-drawer grant'ı `module:ENDPOINT_ADMIN` üretir, servis `module:endpoint-admin` bekler — uyuşmaz; grant fiilen manual tuple seed ister). Bu yüzden endpoint-admin'in split'i **legacy exception**'dır, meeting/transcript için **emsal alınmadı**. Yeni invariant: **governed module object id = catalog key = role permission_key = OpenFGA object id = servis check literal'i** (hepsi aynı string).

### Staged live re-seed (delete-first DEĞİL — Codex zorunlu sıra)

Merge tek başına k3d-test'i bozmaz (deploy gitops digest-pin ile). Kırılma noktası = uppercase servis imajlarını lowercase-only store'a deploy etmek. Doğru sıra (`RB-faz24-mt-uppercase-reseed.md`):

1. backend #688 merge + image build.
2. uppercase JSON ile seed script → `module:MEETING`/`TRANSCRIPT` tuple'ları **ADDITIVE** eklenir (lowercase durur).
3. yeni uppercase imaj pod'ları deploy + 7/7 smoke.
4. lowercase tuple'ları DELETE + invariant uppercase-only + 7/7 tekrar.
5. **writer-path prod-gate evidence**: permission-service grant → outbox DONE → `module:MEETING` tuple → meeting/transcript endpoint 200 (direct-seed bu gate'i kapatmaz).

### Residual (Codex)

Live `backend/openfga/model.fga`'da `type meeting` (owner/participant/viewer) tanımının mevcut olduğu §39 live re-seed sırasında ayrıca doğrulanmalı (module gate düzelse bile create-path owner tuple write fail-closed olmasın).
