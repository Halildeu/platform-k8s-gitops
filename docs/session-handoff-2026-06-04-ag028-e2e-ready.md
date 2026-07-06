# Session Handoff — 2026-06-04 — AG-028 Managed Uninstall **E2E-READY**

> Format: D28 5-alan + Codex 12-adım destructive runbook + Codex 019e92a0 7 must-fix (her biri statü ile) + fresh-session P0 aksiyon listesi.
> Bu doküman, AG-028 LIVE end-to-end uninstall smoke'unu **temiz fresh session**'da koşacak agent için canonical giriş noktasıdır. Önceki handoff'lar (`-phase2b-live` #1260, `-phase2b` #1257, `-phase2a` #1251) supersede edilir (kaynak kanıt olarak kalır).

---

## ⚠️ EN KRİTİK DÜZELTME (runtime-verified) — OpenFGA authz gate AÇIK

Önceki session varsayımı ("OpenFGA grant non-issue / realm role yeter") **YANLIŞ çıktı**. Bu session kod-only bir investigation yaptı (yanlış sonuç verdi: "gate kapalı"), sonra **No Fake Work kuralı gereği canlı pod'da runtime doğruladı** — sonuç tam tersi:

```
$ kubectl --context k3d-test -n platform-test exec deploy/endpoint-admin-service -- env | grep ERP_OPENFGA
ERP_OPENFGA_ENABLED=true                       # ← GATE AÇIK
ERP_OPENFGA_STORE_ID=01KPP0CFP4G82K42Y6NYSPT4JF
ERP_OPENFGA_MODEL_ID=01KRTJVEMAW80B2D35GN8HJDPG
ERP_OPENFGA_API_URL=http://openfga:8080
```

**Neden source-only yanılttı**: `kustomize/base/apps/endpoint-admin-service/configmap.yaml`'da `ERP_OPENFGA_*` key'leri YOK (grep boş). Env'ler base configmap dışı bir yoldan inject ediliyor (overlay configmap / ESO / ayrı apply — fresh session inject kaynağını teyit etsin). Ayrıca `application-k8s.yml:38-41` yorumu "configmap bu key'leri set eder" diyor ama base configmap'te yoklar → **stale comment / posture-drift** (ayrı flag, aşağıda).

### Sonuç — authz iki katman (HER İKİSİ aktif)

| Katman | Mekanizma | Aktif mi? | Geçiş şartı |
|---|---|---|---|
| **A — Spring Security filter** | `adminSecurityFilterChain` `/api/v1/admin/**` → `hasAnyAuthority(ROLE_ADMIN, ROLE_ENDPOINT_ADMIN, SCOPE_endpoint-admin)` | Her zaman | JWT'de realm role `ENDPOINT_ADMIN` (→ `ROLE_ENDPOINT_ADMIN`) |
| **B — `@RequireModule` OpenFGA interceptor** | `EndpointAdminRequireModuleInterceptor` → `authzService.check(userId, "can_manage", "module", "endpoint-admin")` | **AÇIK** (`ERP_OPENFGA_ENABLED=true`) | `module:endpoint-admin#can_manage` **direct tuple** |

**Propose POST + Approve POST'un İKİSİ de `@RequireModule(can_manage)` taşır** (`AdminEndpointUninstallController.java:83-97`). Yani maker-checker'ın HER İKİ öznesi (`proposer` + `approver`) `can_manage` tuple'ına sahip olmalı.

**Org-admin bypass YOK** (kanıt: `EndpointAdminRequireModuleInterceptor.java:35-58` — sadece `!isEnabled()→true` veya direkt `check(...)`; `organization:default#admin` ön-kontrolü yok). permission-service'in kendi interceptor'ında org-admin bypass var ama **endpoint-admin-service'te yok** → `organization:default#admin` tuple'ı tek başına can_manage check'ini geçirmez.

---

## 🔑 AÇIK GRANT-SORUSU (fresh session'ın çözeceği tek gerçek blocker)

**Mevcut seed durumu** (`bootstrap/openfga/endpoint-admin-tuples.json`):

| Persona userId | Tuple | Yetki |
|---|---|---|
| `user:9001` | `can_manage module:endpoint-admin` + `admin organization:default` | full admin ✅ |
| `user:9002` | `can_view module:endpoint-admin` + `member organization:default` | **viewer-only** (can_manage YOK) |

→ **Sadece `9001`'de `can_manage` var. İkinci bir `can_manage` persona YOK.** maker-checker (proposer≠approver, ikisi de can_manage) için **ikinci legitimate `can_manage` persona gerekir**.

### Legitimate grant yolu (DD-EA-2 + CNS-20260415-004 — **direct OpenFGA write YASAK**)

OpenFGA tuple writer **YALNIZ permission-service** (ADR-0012-EA DD-EA-2). Fresh session'ın seçenekleri:

1. **(Önerilen, test-cluster-natural) Seed extend + re-apply**: `endpoint-admin-tuples.json`'a `user:9003 can_manage module:endpoint-admin` ekle + Keycloak'ta eşleşen persona (userId=9003, distinct sub, ENDPOINT_ADMIN, org ...0001) yarat + **`9001`'i seed eden aynı approved-bootstrap yoldan** apply et. Apply yolu runbook: `docs/RB-22-1-1-be-009-openfga-live.md` (§tuple seed permission-service approved bootstrap). `_apply_via` = "permission-service admin OpenFGA bootstrap endpoint (BE-009 final config'da exposed)" — fresh session bu endpoint'in **şu an exposed olup olmadığını teyit etsin** (`PermissionModel.java:19` "Legacy write endpoints" skip notu var → gated olabilir).

2. **(Canonical prod yolu) permission-service granule API**: `AccessControllerV1` `PUT /api/v1/roles/{roleId}/granules` (`@RequireModule("ACCESS","can_manage")` ile korunur) → `MODULE:endpoint-admin:MANAGE` granule taşıyan DB role yarat/assign → `TupleSyncService` `module:endpoint-admin#can_manage@user:<id>` yazar. Grantor caller'ın `ACCESS#can_manage`'i olmalı (9001 org-admin bunu sağlayabilir).

3. **D37 `DefaultAdminRoleAssignmentInitializer`** (LIVE, email-allowlist): pod startup'ta `ADMIN_EMAILS`'teki user'lara DB ADMIN + `organization:default#admin` yazar. **AMA bu sadece org-admin tuple → endpoint-admin-service interceptor'da bypass yok → can_manage geçmez.** Bu yol AG-028 için YETERSİZ (sadece referans).

### Grant doğrulama (destructive adıma geçmeden ÖNCE zorunlu)

İkinci persona grant'lendikten sonra OpenFGA check ile **allow** kanıtla (ClusterIP `10.45.176.98` host'tan routable DEĞİL → `kubectl exec` ile pod-içinden veya permission-service `/check` ile):

```bash
# Pod-içi OpenFGA HTTP API (port 8080) — store/model env'den
kubectl --context k3d-test -n platform-test exec deploy/endpoint-admin-service -- \
  sh -c 'curl -s http://openfga:8080/stores/$ERP_OPENFGA_STORE_ID/check \
    -d "{\"authorization_model_id\":\"$ERP_OPENFGA_MODEL_ID\",\"tuple_key\":{\"user\":\"user:9003\",\"relation\":\"can_manage\",\"object\":\"module:endpoint-admin\"}}"'
# beklenen: {"allowed":true}
```

> **No Fake Work guard (Codex must-fix #3)**: tuple'ı doğrudan OpenFGA'ya yazıp "grant edildi" demek = **fake-authz-seed YASAK**. Grant her zaman permission-service yolundan; check ile allow=true kanıtlanmadan S7'ye (propose) geçilmez.

---

## 1. Bağlam — Neden bu handoff?

AG-028 Managed Uninstall'ın **Phase 0 → Phase 2B (backend ingest) tamamlandı ve testai'de LIVE**. Geriye **destructive LIVE E2E** kaldı: gerçek bir Windows VM'de (HALILKOOLUB735) gerçek 7-Zip uninstall + ingest verify + gateway-path smoke. Bu E2E:

- **maker-checker** (2 distinct can_manage persona) gerektiriyor → ikinci persona grant'i açık (yukarıda).
- **destructive** (agent swap + feature flag enable + gerçek uninstall) → governance-careful, timeboxed.
- Mevcut session post-compaction + context-yoğun; kullanıcı **(B) E2E-ready handoff** seçti → fresh session destructive kısmı temiz koşsun.

---

## 2. İddia — Bu session'da ne yapıldı (MERGED + LIVE)

| PR | Repo | İçerik | Merge SHA | Cross-AI |
|---|---|---|---|---|
| #441 | platform-backend | AG-028 Phase 2B ingest (EndpointUninstallAuditService + submitResult UNINSTALL branch + consistency matrix) | `25042f6a` | Codex 019e8f9c AGREE iter-2 |
| #1259 | platform-k8s-gitops | endpoint-admin digest bump sha-25042f6 (V31/V32/V33 deploy) | `3f65103d` | Codex AGREE |
| #52 | platform-agent | release.yml YAML fix — here-string → standalone `emit-release-notes.ps1` (red-on-main fix) | `90ccd7b2` | Codex AGREE |
| #1260 | platform-k8s-gitops | handoff Phase 2B SOURCE+LIVE | `b9308ecc` | exempt (docs) |

Tüm merge'ler CI-green (admin bypass YOK), archive-tag'li, cross-AI AGREE.

**Cross-field consistency matrix** (Codex 019e8f9c REVISE absorb): verification artık `resultStatus`'tan deterministik türetilir (bağımsız `probeState` okunmaz); drift'te fail-closed; `FAILED_EXIT` clamp'li (non-zero exit asla `ABSENT_VERIFIED` okumaz). 1599 test green.

---

## 3. İspatlar — Canlı / doğrulanmış kanıtlar

- **Backend LIVE**: `endpoint-admin-service` pod `sha256:2d9f4678…` ready, 3h39m uptime. AG-028 Phase 2B (#441) sonraki C1 V34 (#1262) + C2a V35 (#1263) build'lerine dahil (superset). V32 tabloları (`endpoint_uninstall_requests` + `endpoint_uninstall_audit`) applied (task #162'de verify).
- **OpenFGA gate AÇIK**: runtime env (yukarıda) — `ERP_OPENFGA_ENABLED=true`, store/model set.
- **Device hedefi**: `d0efb00a` (HALILKOOLUB735), `tenant_id = org_id = 00000000-0000-0000-0000-000000000001` (persona org ile eşleşir).
- **Provenance**: 7-Zip için 3 adet `SUCCEEDED + SATISFIED` install audit satırı (provenance gate'i besler).
- **Catalog**: `be026-smoke-7zip-registry`, detection `REGISTRY_UNINSTALL`, **`uninstall_supported=false`** (S5'te maker-checker ile flip edilecek).
- **Phase 2A agent binary**: build edilmiş, sha `75568a40c7f44ce6c5313f1dd767619fd5fa5d01178d229dde71e09b6edfb405`, staged: `~/endpoint-agent-ag028.exe` (Mac) + `/tmp/endpoint-agent-ag028.exe` (staging-sw).
- **VM erişimi**: W11 HALILKOOLUB735 Parallels'te Running; `prlctl exec <VM> <program> <args>` (split-arg, quoted multi-word YOK) + `\\Mac\Home` shared folder çalışıyor → **computer-use'suz otonom erişim**.
- **Keycloak**: external docker `platform-kc-test` @ `172.19.0.5:8080`, realm `platform-test`, issuer `https://testai.acik.com/realms/platform-test`. Admin erişimi kullanıcı tarafından **yalnız test-persona token minting için** yetkilendirildi (admin@example.com = kullanıcının login user'ı; ASLA dokunma).
- **Mevcut personalar**: `c5persona-admin-9001` (kc_id `87b1d2c8-aeed-40af-8742-de8431efeee2`, userId=9001, org ...0001) — **bu `can_manage` sahibi** (seed). `c5persona-viewer-9002` (userId=9002, can_view).

---

## 4. İspatlamaz — Henüz kanıtlanmamış (fresh session'ın koşacağı)

- ❌ Gerçek 7-Zip uninstall'ın bir Windows endpoint'te **fiilen** koştuğu (binary çağrısı + exit code + post-probe ABSENT).
- ❌ Phase 2A agent'ın `UNINSTALL_SOFTWARE` capability'sini canlı advertise ettiği (swap + heartbeat <5min).
- ❌ Backend ingest'in gerçek uninstall result'ı `endpoint_uninstall_audit`'e doğru consistency ile yazdığı (LIVE).
- ❌ Gateway product-path (`/api/v1/endpoint-admin/...`) propose→approve→dispatch akışının uçtan uca çalıştığı.
- ❌ İkinci `can_manage` persona'nın legitimate grant'i (açık grant-sorusu — Bölüm 🔑).

---

## 5. Codex 019e92a0 REVISE — 7 must-fix (her biri statü ile)

| # | Must-fix | Statü (bu session sonrası) |
|---|---|---|
| 1 | **Fresh personas** — `c5persona-admin-9002`'yi reuse etme (userId 9002 viewer-9002 ile collide) | ✅ Doğrulandı (userId=9001/9002 confirmed); fresh `ag028-proposer`+`ag028-approver` gerekir |
| 2 | **Token decode assert** — `iss/azp/aud/realm_access.roles=ENDPOINT_ADMIN/userId/org_id/preferred_username/exp` | ⏳ fresh session (mint sonrası decode + assert) |
| 3 | **OpenFGA can_manage gate ≠ role** — legitimate grant path bul (direct write = fake-authz-seed) | ✅ **ÇÖZÜLDÜ**: gate AÇIK (runtime); grant = permission-service yolu (Bölüm 🔑); direct write YASAK |
| 4 | **Distinctness BOTH sub AND userId** — iki persona hem sub hem userId farklı | ⏳ fresh session (yaratım sırasında) |
| 5 | **Hardened token hygiene** — `mktemp -d` + `umask 077` + `trap cleanup` + stdout/argv'de Bearer YOK + post-smoke disable | ⏳ fresh session (token mint scriptinde) |
| 6 | **Gateway-path smokes** — product path `/api/v1/endpoint-admin/...` (internal `/api/v1/admin/...` değil) | ⏳ fresh session (S7/S11) |
| 7 | **maker-checker via Phase 0** — catalog flip + propose/approve gerçek 2-admin, direct DB değil | ⏳ fresh session (S5 + S7-S8) |

> **Token hygiene şablonu** (must-fix #5):
> ```bash
> umask 077; TD=$(mktemp -d); trap 'rm -rf "$TD"' EXIT
> # token'ı dosyaya yaz, ASLA stdout/argv'ye; curl --header @<file> veya -d @<file>
> # Bearer'ı `set -x` altında çalıştırma; smoke sonrası persona disable (enabled=false)
> ```

---

## 6. Codex 12-adım destructive runbook (S1→S12)

> Her adım: tetik → komut → beklenen → fail sinyali → devam eşiği. **Hiçbir destructive adım, bir önceki adımın kanıtı alınmadan başlamaz.**

**S1 — Auth preflight** (task #164): 2 fresh `can_manage` persona (proposer≠approver, distinct sub+userId, org ...0001, ENDPOINT_ADMIN). İkinci persona grant'i = Bölüm 🔑. Her persona için JWT mint (audience `endpoint-admin-service`; allowed client `frontend/admin-cli/serban-web/account`) + token decode assert (must-fix #2) + OpenFGA check allow=true. **Token hygiene zorunlu** (must-fix #5).

**S2 — Baseline snapshot** (read-only, task #165): VM'de 7-Zip REGISTRY MATCHED (kurulu) doğrula (`prlctl exec`); backend'de açık uninstall request YOK + queued command YOK (idempotent başlangıç).

**S3 — Agent swap** (task #166): VM'de eski binary backup (`C:\Program Files\EndpointAgent\endpoint-agent.exe` → `.bak`); Phase 2A binary'yi `\\Mac\Home`'dan kopyala (sha `75568a40…` doğrula); `Unblock-File`; `Restart-Service EndpointAgent`.

**S4 — Capability verify** (task #166): swap sonrası heartbeat `received_at > swap_start` + freshness `<5min` + `UNINSTALL_SOFTWARE ∈ capabilities`. (Capability+heartbeat guard backend'de enforce.)

**S5 — Catalog flip** (task #167): `be026-smoke-7zip-registry` `uninstall_supported=true` — **Phase 0 maker-checker ile** (direct DB UPDATE YASAK). Authority gate: REGISTRY_UNINSTALL ✅ (WINGET_PACKAGE reddedilir).

**S6 — Flag enable** (task #167, **timeboxed**): `ENDPOINT_ADMIN_UNINSTALL_ENABLED=true` (env; Spring prop `endpoint-admin.uninstall.enabled`). Smoke biter bitmez `false`'a geri al (cleanup S12).

**S7 — Propose** (gateway, task #168): proposer persona ile `POST /api/v1/endpoint-admin/.../uninstall` (product path → RewritePath `/api/v1/admin/...`). Provenance gate: 3 SUCCEEDED+SATISFIED satırı geçer.

**S8 — Approve** (distinct persona, task #168): approver persona ile `POST .../{requestId}/approve`. maker-checker: proposer≠approver (2 distinct admin subject) enforce.

**S9 — Dispatch**: approved request → agent command queue → Phase 2A agent poll.

**S10 — Gerçek uninstall** (W11): agent 7-Zip'i gerçekten kaldırır (REGISTRY_UNINSTALL authority; Job Object + redacted log). Exit code + post-probe ABSENT.

**S11 — Ingest verify + smoke**: result submit → `endpoint_uninstall_audit` satırı (consistency matrix: SUCCEEDED_VERIFIED→ABSENT_VERIFIED). Gateway-path API + browser smoke (must-fix #6) → request TERMINAL + BE-016 hash-chain event `ENDPOINT_UNINSTALL_RESULT_RECORDED`.

**S12 — Cleanup**: flag `false`; 7-Zip reinstall (VM baseline restore); fresh persona disable (`enabled=false`); catalog `uninstall_supported` istenirse geri al; eski agent binary restore opsiyonel (Phase 2A kalabilir).

---

## 7. Bilinen boşluk + fresh-session P0 aksiyon listesi

| P | Aksiyon | Efor | Bağımlılık |
|---|---|---|---|
| **P0** | İkinci `can_manage` persona legitimate grant (Bölüm 🔑 — seed extend + approved bootstrap apply VEYA granule API) + OpenFGA check allow=true | ~30-45dk | permission-service bootstrap endpoint exposed mı teyit |
| **P0** | S1 auth preflight tamam (2 persona JWT + decode assert + token hygiene) | ~20dk | yukarıdaki grant |
| **P0** | S2-S12 destructive E2E koş (runbook Bölüm 6) | ~1-1.5h | S1 + VM up + binary staged |
| **P1** | **Authz posture-drift flag**: `application-k8s.yml:38-41` comment "configmap ERP_OPENFGA_* set eder" diyor ama base configmap'te yok; env başka yoldan inject — bu drift'i kalıcı kapat (configmap'e ekle veya comment düzelt + inject kaynağını dokümante et) | ~30dk | ayrı PR (AG-028 scope dışı, spawn_task adayı) |
| **P2** | Phase 3 Web UI — `mfe-endpoint-admin` uninstall surface | ayrı sprint | E2E PASS sonrası |

---

## 8. Hazır artifact'lar (fresh session kullanır)

| Artifact | Konum | Doğrulama |
|---|---|---|
| Phase 2A agent binary | `~/endpoint-agent-ag028.exe` (Mac) + `/tmp/endpoint-agent-ag028.exe` (staging-sw) | sha256 `75568a40c7f44ce6c5313f1dd767619fd5fa5d01178d229dde71e09b6edfb405` |
| Auth discover script | staging-sw `/tmp/ag028-auth-discover.sh` | çalışıyor (persona/kc_id/org listeler) |
| Seed tuple dosyası | `bootstrap/openfga/endpoint-admin-tuples.json` | 9001 can_manage; 9003 eklenecek |
| BE-009 OpenFGA runbook | `docs/RB-22-1-1-be-009-openfga-live.md` | tuple seed approved-bootstrap yolu |
| Persona/rol runbook | `docs/RB-faz-21-3-d35-3-persona-rol-atama.md` + `-prereq-tuple-seed.md` | "realm rol ≠ frontend authz" notu |

### Kanonik referans dosyalar (authz)
- Enforcement: `endpoint-admin-service/.../config/SecurityConfig.java:59-75,121-135` + `EndpointAdminRequireModuleInterceptor.java:35-58` + `controller/AdminEndpointUninstallController.java:83-97`
- Grant: `permission-service/.../controller/AccessControllerV1.java` (`/api/v1/roles` granule) + `service/TupleSyncService.java`
- Model: `platform-backend/backend/openfga/model.fga:45-50` (`can_manage = [user] or can_edit, but not blocked` — direct, inheritance YOK)
- Live config: `endpoint-admin-service/.../resources/application-k8s.yml:45-51` (`ERP_OPENFGA_ENABLED:false` default ama runtime `true`)

---

## Yeni session için ilk komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-06-04-ag028-e2e-ready.md   # bu doküman
# P0: ikinci can_manage persona grant (Bölüm 🔑) → S1 auth preflight → S2-S12 destructive E2E (Bölüm 6)
# Board: AG-028 issue In Progress; her adımda kanıt comment'i
```

> **Governance hatırlatma**: CI kırmızıyken merge YASAK · admin merge YASAK · cross-AI (Claude impl → Codex review) · No Fake Work (her adım reproducible kanıt) · direct OpenFGA write YASAK (fake-authz-seed) · admin@example.com'a dokunma · token stdout/log/history'ye sızdırma.
