# Faz 22.5 — AG-039 / AG-040 / 22.5.3C Browser-Smoke Acceptance (2026-06-09)

> **Closes the acceptance gaps flagged in the 2026-06-09 22.5 assessment:**
> "AG-039/040 browser/digest acceptance pending" + "22.5.3C authenticated
> full-surface acceptance kısmi". All three now **browser-verified LIVE on testai
> with real data, HTTP 200, and a clean console** (HARD RULE — Tarayıcıdan Sonuç
> Doğrulanmadan İş Bitmedi).

**Environment**
- URL: `https://testai.acik.com/endpoint-admin/devices` (Platform Admin, logged-in)
- Device: **HALILKOOLUB735** (`d0efb00a-681a-4e32-b7de-a27ef94f2977`), Çevrim içi, agent `0.1.0-dev`
- Frontend digest: `sha-3627195` (gitops #1396); device-query `POST /endpoint-devices/query` 200
- Method: Claude-in-Chrome MCP browser smoke (real browser, real session)

## AG-039 — Critical Services (Hizmetler tab) ✅ PASS

- Drawer tab **"Hizmetler"** renders **6 canonical services with real probe data**:
  | Hizmet | Kurulu | Çalışma Durumu | Başlangıç |
  |---|---|---|---|
  | WinDefend | Evet | Çalışıyor | Otomatik |
  | wuauserv | Evet | Çalışıyor | Manuel |
  | BITS | Evet | **Durduruldu** | Manuel |
  | EventLog | Evet | Çalışıyor | Otomatik |
  | EndpointAgent | Evet | Çalışıyor | Otomatik (gecikmeli) |
  | MpsSvc | Evet | Çalışıyor | Otomatik |
- Scan metadata: Toplama Zamanı `08.06.2026 17:54:43`, Tarama Süresi `2 ms`; "Probe sırasında hata kaydedilmedi".
- Network: `GET /api/v1/endpoint-admin/endpoint-devices/d0efb00a.../services/latest` → **200**.
- Console: **clean** (no errors).

## AG-040 — Startup + Exposure (Başlangıç + Maruziyet tab) ✅ PASS

- Drawer tab **"Başlangıç + Maruziyet"** renders startup/exposure summary with
  source rows (**Kayıt Defteri** / **Görev Zamanlayıcı**), redaction-aware
  (uzantı/GUID/SID görünen satırlar).
- Network: `GET /api/v1/endpoint-admin/endpoint-devices/d0efb00a.../startup-exposure/latest` → **200**.
- Console: **clean**.

## 22.5.3C — Software Inventory Diff (Yazılım Değişimleri tab) ✅ PASS (query)

- Drawer tab **"Yazılım Değişimleri"** (BE-024 diff surface) active, authenticated query fires.
- Network: `GET /api/v1/endpoint-admin/endpoint-devices/d0efb00a.../software-inventory/diff` → **200**.
- Console: **clean**.

## Incidental — deployed surfaces confirmed in drawer

The device drawer also exposes (deployed on testai frontend `sha-3627195`):
Envanter, Donanım, Sağlık, **Güncel Olmayan Yazılım**, **Hotfix Duruşu** (AG-037),
**Agent Tanılaması** (AG-038), **Hizmetler** (AG-039), **Başlangıç + Maruziyet**
(AG-040), **Görüntü Politikası** (#508), **Uygulama Kontrolü** (AG-041),
**Yazılım Değişimleri** (BE-024), **Güncel Olmayan Değişimler** (BE-024b),
**Yasaklı Yazılım** (BE-025), **Yazılım Kataloğu**.

## Net

- **AG-039 + AG-040 browser/digest acceptance: CLOSED** (was the assessment's primary 22.5.2A pending gap).
- **22.5.3C authenticated diff surface: CONFIRMED 200** (closes part of the "authenticated full-surface acceptance kısmi" gap).
- Remaining 22.5 work is now overwhelmingly **operator/infra/time-gated** (multi-device 24h soak #1044, rollout-controls testai functional acceptance, M0-M7 productization incl. M2 edge-mTLS #1359 + M4 signed MSI, domain pilot #1037/#1015, prod enablement) — not agent-doable browser acceptance.

> Cross-AI note: this is a live browser-smoke evidence ledger (not a code change);
> the underlying source (AG-039 #47/#362/#728, AG-040 #48/#364/#729, BE-024 #334)
> was already merged + cross-AI-reviewed per current-state.md.
