# RB — Faz 22.5.4 First Install Pilot 7-Zip Lifecycle Live Smoke

> **Status (2026-05-29)**: SOURCE-MERGED across 4 repos; **end-to-end live
> smoke chain NOT yet executed**. This runbook documents the exact
> operator-paste-only path execution detail.
> **Companion runbooks**:
> - `RB-faz22-software-deployment-winget.md` §6.2 — operator-bound
>   3-path matrix (operator-paste-only / fresh Playwright persona /
>   Vault test persona JWT mint) per cluster scope
> - This runbook = §6.2 Path #1 "operator-paste-only" step-by-step
>   execution detail
> **Tracked by**: platform-k8s-gitops#1133 (P0 board) +
> faz-22-software-deployment-plan.md §9.bis P0 item #1

## 1. Amaç

7-Zip controlled install lifecycle smoke chain'inin **canlı kanıtla**
"22.5.4 First Install Pilot LIVE" eşiğini geçmesini sağlar.

Zincirin atomic adımları:

1. Admin JWT acquisition (Keycloak persona)
2. Catalog seed for `7zip.7zip`
3. Install dry-run preflight → PASS/WARN
4. INSTALL_SOFTWARE command dispatch
5. Agent poll cycle pickup (30s heartbeat)
6. Agent winget install execution (HALILKOOLUB735 SYSTEM context)
7. Result + detection submit (BE-021 audit)
8. UI render verify (WEB-014A compliance + endpoint detail drawer)

Bu zincir tamamlandığında acceptance gate'i geçer; eksik kalan
adım varsa partial sayılır ve current-state.md "Critical residual P0"
notu güncellenir.

## 2. Ön Koşullar

### 2.1 Source MERGED + LIVE durumu

| Slice | Durum | Kanıt |
|---|---|---|
| Backend catalog (BE-020) | MERGED + LIVE | `platform-backend` PR #306 + #308 |
| Backend ingest (BE-020I) | MERGED + LIVE | PR #310 + #311 |
| Backend preflight (BE-021A) | MERGED + LIVE | PR #312 |
| Backend install command + audit (BE-021) | MERGED + LIVE | PR #317 + #318 + #321 |
| Backend compliance (BE-023) | MERGED + LIVE | PR #313 + #314 + #315 |
| Agent install adapter (AG-027) | SOURCE-MERGED | `platform-agent` PR #23 |
| Agent winget readiness (AG-026A) | MERGED + LIVE | PR #22 + #25 |
| Agent enrollment friction (AG-026B/C/D) | MERGED + LIVE | PR #26/27/28/29 |
| WEB compliance tab (WEB-014A) | MERGED + LIVE | `platform-web` PR #675 |

Cluster digest 2026-05-29: `sha256:76bacc004f...` (sha-e3a0369).

### 2.2 HALILKOOLUB735 W11 lab agent durumu

- VM running, hostname `HALILKOOLUB735`
- EndpointAgent service Running
- DPAPI HMAC credential persisted (`C:\ProgramData\EndpointAgent\config\hmac-credential.dpapi`)
- Heartbeat aktif (30s poll); device id `d0efb00a-681a-4e32-b7de-a27ef94f2977`
- WinGet binary mevcut: `C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_1.28.239.0_arm64__8wekyb3d8bbwe\winget.exe`
- `winget search 7zip.7zip` reachable; "7-Zip 7zip.7zip 26.01" winget source'tan

### 2.3 Admin JWT prerequisite

Endpoints + RBAC (verified against backend source code 2026-05-29):

| Endpoint | Method | RBAC |
|---|---|---|
| `/api/v1/admin/endpoint-software-catalog` | POST (create) | `module:endpoint-admin can_manage` |
| `/api/v1/admin/endpoint-software-catalog/{slug}` | GET (read) / PUT (update) | `can_view` / `can_manage` |
| `/api/v1/admin/endpoint-software-catalog/{slug}/approve` | POST (approve) | `can_manage` (maker-checker: approver subject ≠ creator subject) |
| `/api/v1/admin/endpoint-software-catalog/{slug}/revoke` | POST (revoke) | `can_manage` |
| `/api/v1/admin/endpoint-devices/{deviceId}/install-preflight?catalogItemId={slug}` | GET | `can_view` |
| `/api/v1/admin/endpoint-devices/{deviceId}/installs` | POST (dispatch) | `can_manage` |
| `/api/v1/admin/endpoint-devices/{deviceId}/installs` | GET (audit list) | `can_view` |

JWT acquisition iki path:

**Path A (operator-paste-only — default testai)**: Operator testai.acik.com Software Center UI'da login → DevTools Network tab'den Authorization header'i copy → operator agent'a iletir (scratch buffer). Token PR/issue/chat/log/disk'e **yazılmaz**. Companion `RB-faz22-software-deployment-winget.md` §6.2 Path #1.

**Path B (fresh Playwright persona — lab cluster)**: Test persona `endpoint-admin-test-smoke@<realm>` ayrı session/cookie isolation. Operator-driven Playwright fixture; JWT Playwright konteksti dışına çıkmaz.

**Path C (Vault test persona JWT mint — pre-prod)**: Operator-authorized Vault secret lane'den test persona credentials → Keycloak password grant → JWT mint. Auditable secret lane; "tam autonomous credential access" değil.

**Maker-checker invariant**: Path A operator subject = catalog creator. Catalog approve adımı (4.2c) ayrı bir manager subject gerektirir; aynı operator hem create hem approve YAPAMAZ (BE-020 enforcement). Bu pilot smoke için **ikinci operator/persona** ya da Path B/C zorunlu approve aşamasında.

## 3. Güvenlik Sınırları

- **JWT no-history/no-log**: Path A'da kopyalanan JWT **shell history/PR/issue/chat/log/disk'e yazılmaz**.
  ```bash
  # Doğru:
  set +o history     # bash; veya zsh: setopt HIST_IGNORE_SPACE + space prefix
  read -r -s ADMIN_JWT
  # JWT prompt'a paste; Enter; echo gizli
  set -o history     # geri aç (yeni komutlar tekrar geçer)
  
  # YASAK:
  # export ADMIN_JWT="eyJ..."   # ← history'ye yazar
  # echo "$ADMIN_JWT"            # ← terminal scrollback'e yazar
  ```
- **Curl argv leak guard**: `curl -H "Authorization: Bearer $ADMIN_JWT"` ps'de argv'de görünür. Preprod testai için kabul edilebilir risk; sıkı operasyonel mod için `curl -K config pipe` kullan:
  ```bash
  curl -K <(printf 'header = "Authorization: Bearer %s"\n' "$ADMIN_JWT") \
       -X POST "https://testai.acik.com/..." ...
  ```
- **Smoke sonrası cleanup zorunlu**:
  ```bash
  unset ADMIN_JWT APPROVER_JWT
  # Browser session: operator portal logout-revoke (Keycloak End Session)
  # Veya: testai.acik.com/auth/realms/<realm>/protocol/openid-connect/logout
  ```
- **Smoke evidence dosyalarında JWT yok** — tüm curl response paste'leri JWT'yi redacte eder; gitleaks .gitleaksignore'a yeni fingerprint eklemeye gerek bırakma. Evidence patch öncesi `grep -E "eyJ[A-Za-z0-9_-]{20,}\."` ile pre-flight scan.
- HALILKOOLUB735 W11 lab cihaz; pre-production scope. 7-Zip kurulumu reversible (uninstall §7).
- SRB-AIDENETIMPC veya prod cihazlarda smoke YASAK — yalnız HALILKOOLUB735.
- 7-Zip dışı paket smoke YASAK — Approved Catalog'da yalnız 7-Zip satırı seed edilir.

## 4. Smoke Chain Adımları

### 4.1 Path A — Admin JWT acquisition (no-history mode)

```bash
# Operator (browser):
# 1. testai.acik.com'a login
# 2. DevTools → Network → Filter "endpoint-admin" → any request
# 3. Request Headers → Authorization: Bearer eyJ... → copy
# 4. Terminal (history-disabled):
set +o history
read -r -s ADMIN_JWT   # JWT prompt'a paste, Enter
set -o history
# 5. Quick verify (JWT format, no content leak):
echo "JWT length=$(echo -n "$ADMIN_JWT" | wc -c)"   # ~1000-2000 char beklenir
```

### 4.2 Catalog seed for 7-Zip — 3 adım (create → APPROVE → verify enabled)

**4.2a — Create (DRAFT, enabled=false)**:

```bash
curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-software-catalog" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "catalogItemId": "7zip",
    "provider": "WINGET",
    "sourceType": "WINGET",
    "sourceName": "winget",
    "sourceTrust": "WINGET_COMMUNITY_REVIEWED",
    "packageId": "7zip.7zip",
    "displayName": "7-Zip",
    "publisher": "Igor Pavlov",
    "versionPolicyType": "LATEST",
    "installerType": "WINGET_SILENT",
    "silentArgsPolicy": "DEFAULT",
    "detectionRule": {
      "type": "WINGET_PACKAGE",
      "wingetPackageId": "7zip.7zip"
    },
    "riskTier": "LOW"
  }' | jq .
```

Expected: **HTTP 200** + `AdminCatalogItemResponse`. **Catalog status: DRAFT, enabled: false**. Cannot install yet.

**4.2b — Approve (maker-checker invariant)**:

```bash
# ÖNEMLİ: Bu adımı 4.2a yapan subject DEĞİL, ikinci bir manager subject ile koş.
# Aksi halde BE-020 service layer "same subject cannot maker+checker" error döner.
# Path A operator için: ikinci operator/persona ile login + paste yapılır.
# Path B/C için: test-pilot-approver persona ile auth.

curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-software-catalog/7zip/approve" \
  -H "Authorization: Bearer $APPROVER_JWT" \
  -H "Content-Type: application/json" | jq .
```

Expected: HTTP 200 + `AdminCatalogItemResponse`. **Catalog status: APPROVED, enabled: true**.

**4.2c — Verify enabled before preflight**:

```bash
curl -s "https://testai.acik.com/api/v1/admin/endpoint-software-catalog/7zip" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  | jq '{catalogItemId, status, enabled}'
```

Expected: `{"catalogItemId":"7zip","status":"APPROVED","enabled":true}`.

Eğer `enabled=false` ise 4.3 preflight BLOCK döner (reason: `catalog_item_draft`).

### 4.3 Install dry-run preflight (GET + query param)

```bash
DEVICE_ID="d0efb00a-681a-4e32-b7de-a27ef94f2977"  # HALILKOOLUB735

curl -s "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/install-preflight?catalogItemId=7zip" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  | jq '{decision, blockingReasons, warnings, requirements, installedState, evidence}'
```

Expected: HTTP 200 + `InstallPreflightResponse`:
```json
{
  "decision": "PASS" | "WARN" | "BLOCK",
  "blockingReasons": [],
  "warnings": [],
  "requirements": [],
  "installedState": "NOT_INSTALLED" | "INSTALLED" | "UNKNOWN",
  "evidence": { ... }
}
```

`decision != PASS` ve `decision != WARN` durumda dispatch YAPMA (BE-021 recompute gate aynı sebepten BLOCK döner). WARN durumunda operator açıkça kabul ederek devam edebilir (warnings non-blocking).

### 4.4 INSTALL_SOFTWARE command dispatch (idempotencyKey body field)

```bash
# Idempotency key max 40 char (BE-021 prefix `admin-install:{deviceId}:{catalogUuid}:` 88 char + key + 128 char column).
IDEMPOTENCY_KEY="7zip-pilot-$(date -u +%Y%m%d-%H%M%S)"

curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/installs" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d "{
    \"catalogItemId\": \"7zip\",
    \"idempotencyKey\": \"$IDEMPOTENCY_KEY\",
    \"reason\": \"Faz 22.5.4 First Install Pilot lifecycle smoke\"
  }" | jq '{id, status, type, approvalStatus, idempotencyKey}'
```

Expected: HTTP 201 + `EndpointCommandDto`:
```json
{
  "id": "<uuid>",
  "status": "QUEUED",
  "type": "INSTALL_SOFTWARE",
  "approvalStatus": "NOT_REQUIRED",
  "idempotencyKey": "7zip-pilot-..."
}
```

`id` (= command UUID) ve `status=QUEUED` notla. `approvalStatus=NOT_REQUIRED` çünkü INSTALL_SOFTWARE dual-control gerektirmez (BE-021 EndpointAdminCommandService.java); BE-017 destructive command dual-control INSTALL_SOFTWARE'i kapsamaz.

`HTTP 409 Conflict` döner ise:
- Body `InstallPreflightResponse` ile gelir (BLOCK recompute); preflight değişmiş.
- Veya idempotency key reuse + device/catalog mismatch.

### 4.5 Agent poll cycle pickup (30s heartbeat)

```bash
# Mac local, prlctl exec
prlctl exec "Windows 11" cmd.exe /c \
  "powershell -NoProfile -Command \"Get-Content C:\ProgramData\EndpointAgent\logs\endpoint-agent.log -Tail 50 | Select-String 'INSTALL_SOFTWARE|install_winget|7zip'\""
```

Expected: Agent log içinde "command received: INSTALL_SOFTWARE" benzeri satır (30s sonra heartbeat'te pickup).

### 4.6 Agent winget install execution

Agent AG-027 install adapter:
1. Pre-detect: `winget list --id 7zip.7zip --exact --source winget` — yoksa fresh install path
2. `winget install --id 7zip.7zip --exact --silent --accept-package-agreements --accept-source-agreements` (DEFAULT silentArgsPolicy preset)
3. Post-verify: `winget list --id 7zip.7zip --exact --source winget` — installed version match

Süre: ~30-60sn (paket boyutu küçük).

Verify (operator HALILKOOLUB735):

```powershell
# Direct file check
Test-Path "C:\Program Files\7-Zip\7z.exe"  # True beklenir
& "C:\Program Files\7-Zip\7z.exe" --help   # 7-Zip version banner
```

### 4.7 Result + detection submit readback (BE-021 audit Page.content)

```bash
curl -s "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/installs?size=20&sort=reportedAt,desc" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  | jq '.content[] | select(.catalogItemId == "7zip") | {auditId, commandId, resultStatus, exitCode, detectedVersion, reportedAt, startedAt, finishedAt}'
```

Expected: `Page<EndpointInstallAuditDto>` (Spring Data pagination) content[]:
```json
{
  "auditId": "<uuid>",
  "commandId": "<uuid>",
  "resultStatus": "SUCCEEDED",
  "exitCode": 0,
  "detectedVersion": "26.01",
  "reportedAt": "2026-05-29T...",
  "startedAt": "2026-05-29T...",
  "finishedAt": "2026-05-29T..."
}
```

`resultStatus` top-level values (CommandResultStatus enum): `SUCCEEDED` | `FAILED` | `PARTIAL` | `UNSUPPORTED`. Agent fine-grained values (`SUCCEEDED_NOOP`, `SUCCEEDED_REBOOT_REQUIRED`, `FAILED_PREEXISTING_VERSION_CONFLICT`, `FAILED_UNSUPPORTED_DETECTION_RULE`, `FAILED_VERIFICATION`, timeout/cancel) sadece `details.install.finalStatus` (redactedPayload içinden okunur) tarafında; top-level `resultStatus` bu enum'lardan birine map edilir.

### 4.8 UI render verify

Operator browser:

1. testai.acik.com/endpoint-admin/devices/$DEVICE_ID açar
2. Compliance Tab (WEB-014A) → "7-Zip" listede COMPLIANT görünür
3. Endpoint Detail Drawer → install audit listesi (WEB-014D foundation)
   → 7zip install command + SUCCEEDED status + timestamp

Browser smoke kanıtı:
- Screenshot: Compliance tab "7-Zip: COMPLIANT" satır
- Screenshot: Install audit drawer "7zip → SUCCEEDED"
- Console temiz (yeni JS error yok)
- Network 2xx (no 401/403/500)

## 5. Acceptance Gate — Band 1 Smoke PASS

> **Önemli**: Bu zincir tamamlandığında "22.5.4 **Band 1** lifecycle smoke PASS" eşiği geçilir. **Full 22.5.4 telemetry close-out**, AG-027L exit-code + redacted log capture (P0 board platform-agent#30) + pilot dispatch UI (P0 board platform-web#703) tamamlanana kadar **claim edilemez**. Companion runbook §6.2 aynı disiplini koyuyor.

| Katman | Kanıt | Band 1 |
|---|---|---|
| **Up** | Backend endpoint-admin-service Running; agent HALILKOOLUB735 Running | ✓ |
| **Functional** | 4.2c APPROVED + enabled=true → 4.3 PASS → 4.4 QUEUED → 4.5 pickup → 4.6 winget SUCCEEDED → 4.7 audit SUCCEEDED+exit=0 → 4.8 UI render | ✓ |
| **Secured** | RBAC enforced (4.2b maker-checker; 4.4 can_manage); preflight gate (4.3 BLOCK reject); raw shell yok; JWT no-history | ✓ |
| **Audit** | BE-021 install_audit row + endpoint_audit_events row + catalog approval audit | ✓ |
| **D30 artifact (full digest match)** | Agent binary `platform-agent` PR #28 squash commit `5f0a806` (operator: `git -C platform-agent log --oneline | head -10` ile full sha doğrula); backend image `sha256:76bacc004fa25dcbd1c71c8cdcd3c0e90b741158d195352ac66c49177531670d` (sha-e3a0369); web frontend digest **smoke-zamanı yakalanacak** (`ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=endpoint-admin-web -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'"`). Truncated/placeholder digest ile Band 1 PASS sayılmaz | Full sha required |
| **Telemetry close-out** | AG-027L exit-code/redacted log capture; pilot dispatch UI button + audit/result render | ✗ (deferred — P0 board) |

**Band 1 PASS** = 5 katmanın 5'i ✓; "First Install Pilot **lifecycle smoke** PASS" claim edilebilir. **Full 22.5.4 LIVE close-out** ≠ Band 1; AG-027L + dispatch UI gelene kadar partial.

## 6. Evidence Patch (Band 1 PASS sonrası)

`docs/state/current-state.md` "Critical residual P0" block'una eklenecek (supersede DEĞİL; sadece Band 1 PASS deltası ekle, AG-027L + dispatch UI residual'larını koru):

```markdown
## Live Delta — Faz 22.5.4 Band 1 Smoke PASS (YYYY-MM-DD)

7-Zip lifecycle smoke chain Band 1 end-to-end PASS on HALILKOOLUB735.
Full 22.5.4 telemetry close-out HÂLÂ pending (AG-027L + pilot dispatch UI).

### Band 1 Evidence
- Catalog seed: `endpoint-software-catalog` POST 200 → status=DRAFT, enabled=false
- Approve (maker-checker): `/{catalogItemId}/approve` POST 200 → APPROVED+enabled=true
- Preflight: GET 200 + decision=PASS (evidence refs in response)
- Dispatch: POST 201 + EndpointCommandDto id=<uuid> status=QUEUED
- Agent log: "INSTALL_SOFTWARE command received" + "winget install completed exit=0"
- Detection verify: `winget list 7zip.7zip` → version 26.01
- Install audit (BE-021 Page.content): resultStatus=SUCCEEDED exitCode=0 detectedVersion=26.01
- UI: Compliance tab "7-Zip: COMPLIANT"; Audit drawer "7zip SUCCEEDED"
- D29 truth matrix: Up ✓ Functional ✓ Secured ✓ Audit ✓ D30 artifact ✓ (full digest match)

### Residual (Band 1 ≠ full close-out)
- 🟡 AG-027L exit-code + redacted log capture (P0 board platform-agent#30)
- 🟡 Pilot dispatch UI button + audit/result render (P0 board platform-web#703)
- 🟡 Full 22.5.4 telemetry acceptance only after both residual items LIVE
```

## 7. Rollback / Uninstall

7-Zip uninstall AG-028 ile yapılır (henüz MERGED değil; TODO). İlk
pilot için operator manuel uninstall:

```powershell
& "C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe" \
  uninstall --id 7zip.7zip --exact --silent
```

veya Programlar ve Özellikler → 7-Zip → Kaldır.

Uninstall sonrası catalog item disable (BE-020 revoke endpoint):

```bash
curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-software-catalog/7zip/revoke" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"revocationReason":"7-Zip pilot rollback / smoke cleanup"}'
```

`revocationReason` body field required (AdminCatalogRevokeRequest.java). Backend revoke service catalog status APPROVED kontrolü yapar; **maker-checker invariant SADECE approve endpoint'inde enforced**, revoke'da yok. Operasyonel disiplin olarak ikinci manager tercih edilebilir ama backend enforcement değil.

## 8. Operator Notu

Bu runbook smoke chain'i **bir kez** koşturmak için tasarlandı.
Sonraki çağrılar için:

- Catalog seed adımı (4.2) skip; mevcut satır kullanılır
- Agent poll cycle (4.5) gerçek-zamanlı; bekle
- UI verify (4.8) idempotent; her zaman güncel state'i gösterir

Otomasyon (Path B) için ayrı board issue açılacak: Keycloak persona
seed + token endpoint password grant + Vault'ta persona credential
seed. Bu prereq tamamlanınca smoke chain CI'ya entegre edilebilir.

## 9. Deferred (smoke sonrası)

- **AG-027L** installer exit-code/redacted log capture (P0 residual)
- **Pilot dispatch button + audit/result render UI** on per-device drawer (P0 residual)
- **WEB-015** CSV/report export (P1)

## 10. Bağlantılar

- `docs/faz-22-software-deployment-plan.md` §9.bis P0 item #1
- `docs/state/current-state.md` 2026-05-29 PM "Critical residual P0"
- `docs/adr/0012-EA-endpoint-admin-governance-charter.md` §22.5.4
- `docs/runbooks/RB-faz22-software-deployment-winget.md` (pilot mutabakat + security guardrails)
- Board: platform-k8s-gitops#1133 (P0 7-Zip smoke)
- Board: platform-agent#30 (P0 AG-027L)
- Board: platform-web#703 (P0 pilot dispatch UI)
- Board: platform-backend#327 (P0 BE-022Q SQL fix)
