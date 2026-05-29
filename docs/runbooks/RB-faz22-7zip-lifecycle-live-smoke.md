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

INSTALL_SOFTWARE dispatch endpoint RBAC: `module:endpoint-admin can_manage`.

JWT acquisition iki path:

**Path A (operator-assisted)**: Operator testai.acik.com Software Center UI'da login → DevTools Network tab'den Authorization header'i copy → curl REST chain.

**Path B (test persona seed, future automation)**: Keycloak admin REST üzerinden `test-pilot-admin-7zip` persona create → token endpoint password grant. Bu path için ayrı bir prereq runbook + Vault'ta persona credential seed gerek; operator-bound önce.

Aktif öneri: **Path A** ilk lifecycle smoke için (operator 5dk içinde execute eder); Path B follow-up automation prereq olarak board issue.

## 3. Güvenlik Sınırları

- Path A'da kopyalanan JWT yalnız bu lifecycle smoke için kullanılır;
  artifact'lara yazılmaz. JWT operator'ın aktif user session'ına
  bağlı; kullanım sonrası invalidate gerek değil (browser session
  expire ile kendiliğinden geçersizleşir).
- HALILKOOLUB735 W11 lab cihaz; pre-production scope. 7-Zip kurulumu
  reversible (uninstall AG-028 sonra).
- SRB-AIDENETIMPC veya prod cihazlarda smoke YASAK — yalnız
  HALILKOOLUB735 (D17 Pre-Production Full Authority scope dışı
  cihazlar).
- 7-Zip dışı paket smoke YASAK — Approved Catalog'da yalnız 7-Zip
  satırı seed edilir.

## 4. Smoke Chain Adımları

### 4.1 Path A — Admin JWT acquisition

```bash
# Operator (browser):
# 1. testai.acik.com'a login (varsa)
# 2. DevTools → Network → Filter "endpoint-admin" → any request
# 3. Request Headers → Authorization: Bearer eyJ... → copy
# 4. Export to local shell env:
export ADMIN_JWT="eyJ..."
```

### 4.2 Catalog seed for 7-Zip

```bash
curl -X POST "https://testai.acik.com/api/v1/admin/catalog/software" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "catalogItemId": "7zip",
    "provider": "WINGET",
    "sourceType": "WINGET_COMMUNITY",
    "sourceName": "winget",
    "sourceTrust": "COMMUNITY_VERIFIED",
    "packageId": "7zip.7zip",
    "displayName": "7-Zip",
    "publisher": "Igor Pavlov",
    "approvedVersion": "26.01",
    "installerType": "WINGET",
    "argsPolicyPreset": "DEFAULT",
    "detectionRule": {
      "type": "WINGET_PACKAGE",
      "packageId": "7zip.7zip"
    },
    "riskTier": "LOW",
    "enabled": true
  }' | jq .
```

Expected: HTTP 201 + catalog item DTO döner.

Verify catalog item:

```bash
curl -s "https://testai.acik.com/api/v1/admin/catalog/software/7zip" \
  -H "Authorization: Bearer $ADMIN_JWT" | jq .
```

### 4.3 Install dry-run preflight

```bash
DEVICE_ID="d0efb00a-681a-4e32-b7de-a27ef94f2977"  # HALILKOOLUB735

curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/install-preflight" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "catalogItemId": "7zip"
  }' | jq .
```

Expected: HTTP 200 + `{ "result": "PASS" | "WARN", "checks": [...] }` döner.

PASS olmadan dispatch yasak (BE-021 gate). WARN durumunda operator
açıkça kabul ederek devam edebilir.

### 4.4 INSTALL_SOFTWARE command dispatch

```bash
curl -X POST "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/installs" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 7zip-pilot-$(date -u +%Y%m%d-%H%M%S)" \
  -d '{
    "catalogItemId": "7zip",
    "requestedVersion": "latest"
  }' | jq .
```

Expected: HTTP 201 + EndpointCommandDto döner (command id, status pending).

### 4.5 Agent poll cycle pickup

```bash
# Mac local, prlctl exec
prlctl exec "Windows 11" cmd.exe /c \
  "powershell -NoProfile -Command \"Get-Content C:\ProgramData\EndpointAgent\logs\endpoint-agent.log -Tail 30 | Select-String 'INSTALL_SOFTWARE|install|7zip'\""
```

Expected: Agent log içinde "command received: INSTALL_SOFTWARE" benzeri satır (30s sonra heartbeat'te pickup).

### 4.6 Agent winget install execution

Agent AG-027 install adapter:
1. Pre-detect: `winget list 7zip.7zip --exact` — yoksa fresh install path
2. `winget install --id 7zip.7zip --exact --silent --accept-package-agreements --accept-source-agreements`
3. Post-verify: `winget list 7zip.7zip --exact` — installed version match

Süre: ~30-60sn (paket boyutu küçük).

Verify (operator HALILKOOLUB735):

```powershell
# Direct file check
Test-Path "C:\Program Files\7-Zip\7z.exe"  # True beklenir
& "C:\Program Files\7-Zip\7z.exe" --help   # 7-Zip version banner
```

### 4.7 Result + detection submit (BE-021 audit)

```bash
curl -s "https://testai.acik.com/api/v1/admin/endpoint-devices/$DEVICE_ID/installs" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  | jq '.[] | select(.catalogItemId == "7zip") | {commandId, status, result, exitCode, completedAt}'
```

Expected:
```json
{
  "commandId": "...",
  "status": "COMPLETED",
  "result": "SUCCEEDED",
  "exitCode": 0,
  "completedAt": "2026-05-29T..."
}
```

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

## 5. D29 Pilot Acceptance Gate

| Katman | Kanıt |
|---|---|
| **Up** | Backend endpoint-admin-service Running; agent HALILKOOLUB735 Running |
| **Functional** | 4.5-4.7 zinciri 8 adım sırayla SUCCEED; UI render 4.8 |
| **Secured** | RBAC enforced (4.4 manager-only); preflight gate (4.3 BLOCK reject); raw shell yok |
| **Audit** | BE-021 install_audit table row + endpoint_audit_events row |
| **D30 artifact** | Agent binary commit `5f0a806` (AG-026B); backend digest `sha256:76bacc004f...` (sha-e3a0369); web frontend digest (current testai) |

5 katmanın 5'i pass olunca **22.5.4 First Install Pilot LIVE** claim
edilebilir.

## 6. Evidence Patch (smoke pass sonrası)

`docs/state/current-state.md` "Critical residual P0" block'u
supersede edecek yeni delta:

```markdown
## Live Delta — Faz 22.5.4 First Install Pilot LIVE (YYYY-MM-DD)

7-Zip lifecycle smoke chain end-to-end LIVE on HALILKOOLUB735.

### Evidence
- Catalog seed: catalog item `7zip` exists in BE-020 (POST 201)
- Preflight: result=PASS (POST 200)
- Dispatch: command id `<uuid>` (POST 201)
- Agent log: "INSTALL_SOFTWARE command received" + "winget install completed exit=0"
- Detection verify: `winget list 7zip.7zip` → version 26.01
- Install audit: BE-021 row status=COMPLETED result=SUCCEEDED exitCode=0
- UI: Compliance tab "7-Zip: COMPLIANT"; Audit drawer "7zip SUCCEEDED"
- D29 truth matrix: Up ✓ Functional ✓ Secured ✓ Audit ✓ D30 artifact ✓
```

## 7. Rollback / Uninstall

7-Zip uninstall AG-028 ile yapılır (henüz MERGED değil; TODO). İlk
pilot için operator manuel uninstall:

```powershell
& "C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe" \
  uninstall --id 7zip.7zip --exact --silent
```

veya Programlar ve Özellikler → 7-Zip → Kaldır.

Uninstall sonrası catalog item enable=false set:

```bash
curl -X PATCH "https://testai.acik.com/api/v1/admin/catalog/software/7zip" \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

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
