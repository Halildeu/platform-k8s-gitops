# Faz 22.2.A SRB-AIDENETIMPC — testai.acik.com inventory UI render verify (browser smoke)

> **Tarih**: 2026-05-27
> **Scope**: Faz 22.2.A non-domain Windows pilot — `SRB-AIDENETIMPC` (real corp hardware A1, install evidence: `2026-05-25-srb-aidenetimpc-strategy-d-pilot.md`) için **testai.acik.com endpoint-admin inventory UI render verify** (HARD RULE — Deploy Sonrası Tarayıcı Console Verifikasyonu pattern; agent browser MCP ile end-to-end smoke koştu)
> **Status**: **PASS** — device list + detail panel + envanter sekmesi tümü render; SRB-AIDENETIMPC `Çevrim içi`, agent v0.1.0-dev, son görülme `27.05.2026 13:49:39`, son inventory `26.05.2026 12:30:02`; console error yok, ag-grid-license DEBUG mesajları dışında trafik temiz
> **Boundary**: Mevcut state'in browser-level render verify'ı; **yeni deploy değil**, mevcut runtime state inspection. **Production-ready / password-reset-ready / domain-wide rollout-ready iddiası DEĞİL**. #1044 PASS DEĞİL (multi-device + soak hâlâ pending).

---

## 1. Bağlam (Why)

`docs/faz-22-evidence/2026-05-25-srb-aidenetimpc-strategy-d-pilot.md` SRB-AIDENETIMPC corp hardware install + enroll + command lifecycle SUCCEEDED dedi (PARTIAL-VERIFIED with v0.1.0-dev gaps). Backend-side enrollment/heartbeat/inventory data captured ama **frontend inventory UI'da render edip etmediği görsel olarak doğrulanmamıştı** (TaskCreate #175 — Claude internal task, board issue değil).

HARD RULE — Deploy Sonrası Tarayıcı Console Verifikasyonu (2026-05-08) pattern'i: agent browser MCP ile gerçek tarayıcıda inventory UI'yı koşturup render + console + network kanıtı toplar; kullanıcıya manuel test yıkmaz.

## 2. Tool stack

- **Browser**: Chrome MCP `mcp__Claude_in_Chrome` — deviceId `4338e69b-3938-4392-96cf-8937b216ac47` (Browser 1, macOS, local user session)
- **Tab**: tabId `1641108273`, "Platform" tab, mevcut URL `https://testai.acik.com/endpoint-admin/devices`
- **Tools**: `tabs_context_mcp` + `navigate` + `browser_batch` (computer screenshot + read_console_messages + read_network_requests)

## 3. Smoke chain

### 3.1 Devices listesi (Uç Birimler)

URL: `https://testai.acik.com/endpoint-admin/devices`

Reload sonrası device table render. **Toplam: 6** device:

| Hostname | İşletim Sistemi | Ajan Sürümü | Durum | Son Görülme |
|---|---|---|---|---|
| HALILKOOLUB735 | Windows | 0.1.0-dev | Çevrim içi | 24.05.2026 15:55:54 |
| **SRB-AIDENETIMPC** | **Windows** | **0.1.0-dev** | **Çevrim içi** | **27.05.2026 13:49:39** |
| be013-smoke-host (BE013 Smok…) | Windows | 0.1.0-smoke | Çevrim içi | — |
| be014a-hmac-smoke-host | Windows 11 Pro 22H2 | 0.3.0-smoke | Çevrim içi | 22.05.2026 12:51:08 |
| be017-fixture-host (BE-017 F…) | Windows 10.0-fixture | 0.0.0-fixture | Hizmet dışı | — |
| stagingsw | Linux | 0.1.0-dev | Çevrim içi | 22.05.2026 17:42:03 |

**SRB-AIDENETIMPC görünüyor** ✅ — 2026-05-25 evidence sonrası 2 gün boyunca aktif heartbeat (`Çevrim içi` flag + `Son Görülme` bugün öğleden sonra).

### 3.2 Detay paneli (modal)

SRB-AIDENETIMPC satırına click → modal açıldı:

| Alan | Değer |
|---|---|
| Hostname | `SRB-AIDENETIMPC` |
| Görünen Ad | — |
| Durum | Çevrim içi |
| İşletim Sistemi | WINDOWS |
| OS Sürümü | — |
| Ajan Sürümü | 0.1.0-dev |
| Cihaz ID | `423b6fc3-7497-4083-bd2f-5e2fe543bfe9` |
| Kiracı ID | `00000000-0000-0000-0000-000000000001` (default tenant) |
| Makine Parmak İzi | `a1dc61a42e62b1fa893e0456be7dc8156bd4ebc7a68b9b695116f45eddfa3523` |

Sekmeler: `Detay` (aktif) | `İşlemler` | `Denetim Geçmişi` | `Envanter`

### 3.3 Envanter sekmesi (inventory JSON render)

`Envanter` sekmesine click → Yapısal / Ham JSON toggle (default Yapısal görünüm; JSON görüntülendi):

```json
{
  "claimId": "75179a61-dc13-42db-a559-35c7da7c08b0",
  "details": {
    "inventory": {
      "osName": "windows",
      "hostname": "SRB-AIDENETIMPC",
      "osFamily": "WINDOWS",
      "collectedAt": "2026-05-26T12:30:02.1893765+03:00",
      "agentVersion": "0.1.0-dev",
      "architecture": "amd64"
    }
  },
  "summary": "Inventory collected",
  "startedAt": 1779787802.1893766,
  "finishedAt": 1779787802.1893766,
  "attemptNumber": 1
}
```

- Son güncelleme: `26.05.2026 12:30:02` (install evidence günü ile uyumlu)
- `claimId` populated ✅
- `inventory` payload minimal (`v0.1.0-dev` capability seti): osName + hostname + osFamily + collectedAt + agentVersion + architecture
- `summary: "Inventory collected"` + `attemptNumber: 1` + `startedAt`/`finishedAt` timestamps populated

### 3.4 Console + network

**Console (pattern: `error|Error|ERROR|fail|404|401|403|500|TypeError|inventory|envanter`)**:

5 mesaj — hepsi `[DEBUG] [ag-grid-license] resolved key: found` (3rd-party UI lib license check; benign). Yeni `error|fail|401|403|500` mesajı YOK.

**Network**: `read_network_requests` tab navigation öncesi tracker boş; sayfa yüklemesi browser cache hit ile geldiği için yeni HTTP request listede görünmedi. **Fresh backend 200 kanıtı captured değil** — UI DOM'da inventory JSON render olduğu iz canıtı ama fresh HTTP status code bu smoke için ayrı kapı (network log live ya da `curl` API hit ile doğrulanmalı; bu evidence DOM render scope).

## 4. PASS scope (browser render only)

- ✅ Devices listesi `Toplam: 6` + SRB-AIDENETIMPC satırı render (Çevrim içi, v0.1.0-dev, son görülme 27.05.2026)
- ✅ Detay modal: device ID + tenant ID + machine fingerprint render
- ✅ Envanter sekmesi: inventory JSON payload tam render (claimId, osName=windows, hostname=SRB-AIDENETIMPC, agentVersion=0.1.0-dev, architecture=amd64, summary "Inventory collected")
- ✅ Console temiz (ag-grid-license DEBUG dışında trafik yok)
- ⚠️ Browser render PASS; **fresh backend 200 ayrı kapı** (network tracker boş; cache hit pattern; HTTP status fresh kanıt için ayrı network log + `curl` smoke gerek)

## 5. Boundary (non-claims — verbatim)

- ❌ **NOT prod-ready** — bu evidence mevcut state render verify; deploy/lifecycle değişikliği yok
- ❌ **NOT password-reset-ready** — destructive command real device YASAK
- ❌ **NOT domain-wide rollout-ready** — bu evidence non-domain workgroup PC; domain mass deployment 22.3 ayrı kapı
- ❌ **NOT #1044 PASS** — A1 multi-VM repeatability hâlâ pending (HALILKOOLUB735 + SRB-AIDENETIMPC = 2 device gözleniyor ama 24-72h soak + per-device pending gates listesi açık)
- ❌ **NOT #1037 unblocked** — Gate 0 VPN BLOCKER 22.2.B operator-bound; bu evidence 22.2.A non-domain workgroup scope
- ❌ **NOT acik.local pilot acceptance** — SRB-AIDENETIMPC workgroup PC, AD-joined değil
- ❌ **NOT signed binary** — Authenticode/timestamp pre-req gates açık (AG-024 + SEC-001/SEC-002)
- ❌ **NOT 24h soak** — sadece son 2 gün heartbeat aktif gözlemleniyor; formal soak observation/rollup ayrı kapı
- ❌ **NOT field acceptance gate full PASS** — install evidence + UI render verify ≠ full acceptance (multi-device rollup + soak + signing + KVKK)

## 6. Current outcome / Next gate

`TaskCreate #175` (internal Claude session task tracking) — status updated to evidence-recorded.

22.2.A non-domain primary scope için **UI render + backend inventory pipeline yaşıyor sinyali** captured (DOM render kanıtı; fresh backend HTTP 200 ayrı kapı). Field acceptance gate'leri açık kalmaya devam ediyor (multi-device + 24-72h soak + signed binary + KVKK + per-device gates).
