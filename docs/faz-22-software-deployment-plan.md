# Faz 22.5 — Software Deployment Quick Wins

> **Status**: SOURCE-PARTIAL / install blocked until catalog + contract + audit gates
> **Tracked by**: platform-k8s-gitops#1083, platform-k8s-gitops#1086, platform-k8s-gitops#1088
> **Scope date**: 2026-05-27

Bu doküman Endpoint-Enes / Endpoint Admin agent hattına **ücretsiz ve sektör
standardına yakın yazılım yönetimi** kabiliyeti eklemek için takip edilebilir
planı tanımlar.

Bu plan install/uninstall runtime kabiliyeti iddia etmez. 2026-05-27 üç-AI
değerlendirmesi (Claude Code + Codex + MiniMax/Mavis) ortak hükmü **REVISE**:
read-only agent temeli doğru yönde başlamış, fakat program kurma kabiliyeti
`BE-020` catalog, command contract, detection/result/audit ve web yüzeyi
gelmeden açılmayacak.

### 0.1 Current Implementation Truth (2026-05-27)

| Alan | Repo | Güncel truth | Hüküm |
|---|---|---|---|
| Installed software inventory | `platform-agent` | `0eff2db` / PR #20 ile `internal/software` var; HKLM + HKLM `WOW6432Node` uninstall registry okunuyor, HKCU default dışı | SOURCE-PARTIAL |
| WinGet readiness | `platform-agent` | `internal/winget` yalnız `winget --version` probe eder; install/search/source/upgrade yok | SOURCE-PARTIAL |
| Inventory command | `platform-agent` | `COLLECT_INVENTORY` payload `includeSoftware` okuyabiliyor; full app list yalnız `includeSoftware=true` ile dönmeli | SOURCE-PARTIAL |
| Hardware/device inventory | `platform-agent` + `platform-backend` + `platform-web` | CPU/RAM/disk/BIOS/model/TPM/network gibi donanım envanteri ayrı read-only scope olarak eklendi; source yok | MISSING |
| Approved catalog | `platform-backend` | catalog entity/API/migration yok | MISSING |
| Install command contract | `platform-backend` + `platform-agent` | `INSTALL_APPROVED_SOFTWARE` / `INSTALL_SOFTWARE` command type ve executor yok | MISSING |
| Software / device UI | `platform-web` | `InventoryTab` software/apps/winget readiness ve hardware/device payload parse etmiyor | MISSING |
| GitOps governance | `platform-k8s-gitops` | plan/runbook var; bu revizyon üç-AI mutabakatını işler | SOURCE-PARTIAL |

### 0.2 3-AI Mutabakatı

| AI | Verdict | Absorb edilen karar |
|---|---|---|
| Claude Code | REVISE | Agent AG-025/AG-026 temeli doğru; backend catalog ve web yüzeyi install öncesi blokaj |
| Codex | REVISE | Agent probe yükü ayrıştırılmalı; backend/web command-payload drift'i kapanmalı |
| MiniMax/Mavis | REVISE | Backend approved catalog + install command + web software view olmadan install açılmamalı |

Mutabakat sonucu: yön doğru, ama install PR sırası read-only foundation → web
visibility → approved catalog → command contract → adapter → detection/audit
şeklinde yürür. Katalog dışı paket, raw shell ve rastgele URL/EXE yolu yoktur.

## 1. Ürün Hedefi

Hedef, agent üzerinden Windows cihazlarda kontrollü yazılım yönetimi sağlamaktır:

1. Kurulu program envanteri okunur.
2. Cihazda WinGet hazır mı kontrol edilir.
3. Cihaz donanım/envanter bilgileri read-only toplanır: CPU, RAM, disk, model,
   BIOS, TPM, ağ ve OS/build.
4. Backend'de onaylı yazılım kataloğu tutulur.
5. Agent yalnız katalogda onaylı paketleri sessiz kurar.
6. Kurulum sonucu detection + audit ile kanıtlanır.
7. Pending reboot, Defender/Firewall/BitLocker, local admin ve temel cihaz sağlık
   sinyalleri aynı ekrandan okunur.
8. Kaldırma, rollback ve agent self-update daha sonraki kapılarda açılır.

## 2. Varsayılan Yaklaşım

| Karar | Değer |
|---|---|
| Varsayılan paket provider | Microsoft WinGet |
| Kontrol düzlemi | Approved Software Catalog |
| İlk pilot paket | 7-Zip |
| Lisans yaklaşımı | Ücretsiz / Windows-native first |
| Katalog dışı kurulum | Yasak |
| Raw shell | Yasak |
| Rastgele URL / EXE install | Yasak |
| Audit | Zorunlu |
| RBAC | Zorunlu |
| Destructive / geniş dağıtım | Dual-control + pilot kanıtı sonrası |

WinGet seçimi ücretsiz ve Windows 10/11 üzerinde Microsoft-native olduğu için
varsayılandır. MSI/EXE internal catalog fallback desteklenebilir; Chocolatey
Community ancak ayrı supply-chain değerlendirmesi sonrası opt-in olur.

## 3. İş Paketi Haritası

| ID | Repo | İş | Status | Kabul kriteri |
|---|---|---|---|---|
| **AG-025** | `platform-agent` | Installed software inventory | SOURCE-PARTIAL | HKLM + HKLM `WOW6432Node` uninstall registry kaynaklarından sanitized JSON döner; HKCU default dışı/opt-in later; lisans key, product key, full user path sızmaz |
| **AG-026** | `platform-agent` | WinGet readiness check | SOURCE-PARTIAL | `winget --version` readiness structured döner; install/search/source/upgrade komutu çalıştırılmaz |
| **AG-025H** | `platform-agent` | Software probe decoupling / lightweight inventory guard | TODO | Heartbeat/auto-enroll gibi hafif akışlar full software/WinGet probe yüküne girmeden çalışır; `includeSoftware=true` full app list'i bilinçli açar |
| **BE-020** | `platform-backend` | Approved software catalog API | TODO | Package id, provider/source, provenance/hash, version policy, publisher, detection rule, risk metadata ve approval actor tutulur |
| **BE-020I** | `platform-backend` | Software inventory ingest/query surface | TODO | Agent `COLLECT_INVENTORY` software payload'ı backend result/query yüzeyinde kaybolmadan saklanır ve web'e okunabilir hale gelir |
| **AG-027** | `platform-agent` | Approved software install command | BLOCKED | Yalnız backend catalog item id ile silent install çalışır; raw package id kabul edilmez; `BE-020` + preflight PASS olmadan açılmaz |
| **BE-021** | `platform-backend` | Install result / detection / audit | TODO | Install request, result, detection state, actor ve device audit zincirine düşer |
| **WEB-011** | `platform-web` | Software inventory view | TODO | Cihaz detayında kurulu program listesi filtrelenebilir görünür |
| **WEB-012** | `platform-web` | Approved install UI | TODO | Yetkili kullanıcı katalogdan kurulum isteği oluşturabilir; durum/audit görünür |
| **AG-028** | `platform-agent` | Software uninstall / detection | TODO | Yalnız katalog tarafından yönetilen paket kaldırılır; detection sonucu doğrulanır |
| **AG-029** | `platform-agent` | Signed agent self-update | TODO | Signed manifest + hash + version policy + rollback guard ile agent güncelleme yolu açılır |
| **AG-030** | `platform-agent` | Pending reboot detection | TODO | CBS/Windows Update/PendingFileRenameOperations sinyalleri structured döner; install sonrası restart ihtiyacı görünür |
| **AG-031** | `platform-agent` | Endpoint security posture inventory | TODO | Defender, Firewall ve BitLocker durumu read-only JSON döner; recovery key veya secret sızmaz |
| **AG-032** | `platform-agent` | Local admin group inventory | TODO | Local Administrators üyeleri SID/name/type ile döner; domain SID/full token/credential sızmaz |
| **AG-033** | `platform-agent` | Device health snapshot | TODO | Disk/RAM/uptime/boot time temel sağlık özeti döner; performans counter spam'i yok |
| **AG-035** | `platform-agent` | Hardware / device inventory | TODO | CPU, RAM, disk, manufacturer/model, BIOS version, serial policy, TPM status, network adapter summary ve OS/build read-only döner; raw product key/recovery key/token yok |
| **BE-022** | `platform-backend` | Device inventory ingest/query surface | TODO | Agent hardware/device payload'ı normalize edilir, sensitive alan policy uygulanır ve web'e okunabilir hale gelir |
| **WEB-013** | `platform-web` | Hardware / device inventory view | TODO | Cihaz detayında hardware, OS, disk, TPM ve network özetleri ayrı read-only panelde görünür |
| **AG-034** | `platform-agent` | SMB/file actions discovery guardrail | DEFERRED | Dosya aksiyonları sadece discovery/tehdit modeli; whitelist + RBAC + audit + dual-control olmadan runtime yok |

## 4. Milestone Sırası

### 22.5.0 Tracking Foundation

- Bu doküman ve runbook canonical plan olarak eklenir.
- Board issue'ları gerçek source repolarda açılır.
- Runtime claim yapılmaz.

### 22.5.1 Read-only Device Software View

- `AG-025` ve `AG-026`.
- Sadece okuma yapılır.
- `platform-agent` source-side foundation PR #20 (`0eff2db`) ile başlamıştır;
  field acceptance ve backend/web görünürlük hâlâ ayrı kapıdır.
- `COLLECT_INVENTORY` payload'ına geniş özet eklenebilir:
  - `installedSoftwareCount`
  - `wingetInstalled`
  - `wingetVersion`
  - `wingetSourceAvailable`
- Full app list yalnız `includeSoftware=true` ile döner.
- Default registry scope HKLM + HKLM `WOW6432Node`; HKCU, LocalSystem altında
  gerçek kullanıcıyı temsil etmediği için ilk fazda default dışıdır.

### 22.5.1A Agent Probe Decoupling / Lightweight Guard

- `AG-025H`.
- Heartbeat, auto-enroll ve lightweight inventory yolları full software scan
  veya WinGet probe maliyetine yanlışlıkla girmez.
- Kabul:
  - `includeSoftware=false` veya lightweight mode full `apps[]` listesi üretmez,
  - `includeSoftware=true` full list'i explicit üretir,
  - WinGet readiness timeout/redaction testleri korunur,
  - no shell / no PowerShell / no `winget install` sınırı testle kilitlenir.

### 22.5.1B Web Read-only Visibility

- `WEB-011`.
- Mevcut agent payload'unu görünür yapar:
  - app count,
  - WinGet readiness,
  - WinGet version,
  - full app list varsa filtrelenebilir tablo.
- Backend result shape'i `details.inventory.software` gibi nested olabilir;
  web normalize layer bu şekli açıkça destekler.
- Backend status enum drift'i giderilir: backend `PARTIAL` / `UNSUPPORTED`
  dönerse UI yanlış `TIMEOUT` / `CANCELLED` varsayımı yapmaz.

### 22.5.2 Device Posture + Hardware Quick Wins

- `AG-030`, `AG-031`, `AG-032`, `AG-033`, `AG-035`, `BE-022` ve `WEB-013`.
- Sadece read-only inventory sinyalleri toplanır.
- Panelde program kurulumu için karar vermeyi kolaylaştırır:
  - restart bekliyor mu,
  - Defender aktif mi,
  - Firewall profilleri açık mı,
  - BitLocker koruması açık mı,
  - local admin grubunda kimler var,
  - disk/RAM/uptime sağlığı nedir,
  - cihaz modeli, CPU/RAM/disk kapasitesi, BIOS/TPM ve ağ özeti nedir.
- BitLocker recovery key, credential, bearer token, password, product key ve
  tam kullanıcı profili path'i toplanmaz.

Hardware/device inventory varsayılan alanları:

| Grup | Alanlar | Privacy / güvenlik sınırı |
|---|---|---|
| OS | edition, version, build, architecture | lisans/product key yok |
| Hardware | manufacturer, model, CPU model, logical core count, RAM total | yüksek kardinaliteli raw sensor/process dump yok |
| Disk | volume count, total/free, drive type, boot volume flag | kullanıcı dosya path'i veya dosya listesi yok |
| BIOS/Firmware | BIOS version/date, serial policy | serial raw gösterimi policy-gated; varsayılan hash veya masked |
| TPM | present, enabled, ready, version | key material veya attestation secret yok |
| Network | adapter count, primary adapter type, IP family, DNS suffix | MAC/IP raw gösterimi policy-gated; default summary/masked |
| Agent | agent version, service status, capabilities | token, HMAC secret veya enrollment secret yok |

Bu bilgiler `software inventory` değildir; genel `device inventory` başlığı
altında ayrı tutulur. Yazılım envanteri kurulu programları; hardware inventory
cihazın donanım ve platform kimliğini ifade eder.

### 22.5.3 Approved Catalog Control Plane

- `BE-020`.
- İlk katalog satırı: `7zip.7zip`.
- Katalog alanları:
  - `catalogItemId`
  - `provider` / `sourceType`
  - `sourceName`
  - `sourceTrust`
  - `packageId`
  - `displayName`
  - `publisher`
  - `approvedVersion` veya `approvedVersionRange`
  - `installerType`
  - `silentArgsPolicy`
  - `sha256` / `provenance`
  - `detectionRule`
  - `riskTier`
  - `enabled`
  - `createdBy`
  - `approvedBy`
  - `createdAt`
  - `approvedAt`

Katalog, WinGet Community kaynağı dahil her provider için supply-chain karar
yeridir. Agent hiçbir zaman kullanıcıdan gelen raw package id, raw URL veya raw
installer argument'i execute etmez.

### 22.5.4 First Install Pilot

- `AG-027` + `BE-021`.
- Install adapter şu kapılar olmadan başlamaz:
  - read-only preflight PASS (`AG-025`/`AG-026`),
  - backend inventory ingest/query path (`BE-020I`),
  - approved catalog (`BE-020`),
  - command contract ve audit (`BE-021`).
- İlk canlı paket: 7-Zip.
- Komut shape raw shell içermez:

```json
{
  "type": "INSTALL_APPROVED_SOFTWARE",
  "catalogItemId": "7zip",
  "requestedVersion": "latest"
}
```

Agent backend'den gelen `catalogItemId` ile katalog metadata'sını doğrular,
sonra provider komutunu kendi adapter'ında üretir.

### 22.5.5 Web Surface

- `WEB-011` ve `WEB-012`.
- Cihaz detayında:
  - kurulu programlar,
  - WinGet readiness,
  - pending reboot,
  - Defender/Firewall/BitLocker durumu,
  - local admin grubu,
  - disk/RAM/uptime özeti,
  - son kurulum/kaldırma sonucu,
  - audit event'leri görünür.

### 22.5.6 Managed Uninstall / Rollback

- `AG-028`.
- Sadece bizim katalog üzerinden kurulan veya katalogda yönetilebilir işaretli
paketler için açılır.

### 22.5.7 Agent Self-update

- `AG-029`.
- Signed update manifest olmadan agent self-update açılmaz.
- Authenticode + manifest signature + SHA256/SHA512 kanıtı gerekir.

### 22.5.X Deferred / High-Risk File Actions

- `AG-034`.
- SMB/file actions bu quick-win planının runtime hedefi değildir.
- İlk iş yalnız discovery olur:
  - hangi path sınıfları riskli,
  - hangi whitelist modeli gerekir,
  - hangi RBAC scope gerekir,
  - hangi audit ve pre/post snapshot zorunlu,
  - dual-control gerektiren aksiyonlar hangileri.
- Kullanıcı masaüstü/dosya işlemleri whitelist + RBAC + audit + dual-control
  tasarımı olmadan açılmaz.

## 5. Güvenlik Sınırları

| Yasak | Sebep |
|---|---|
| Raw shell command | Remote code execution yüzeyini kontrolsüz büyütür |
| Rastgele URL'den EXE/MSI indirme | Supply-chain ve malware riski |
| Kullanıcı tarafından serbest package id yazma | Katalog kontrolünü bypass eder |
| Publisher/hash/detection olmadan install | Kurulum kanıtı ve rollback zayıflar |
| Audit olmadan install/uninstall | Non-repudiation kaybolur |
| Domain-wide deployment'e doğrudan geçiş | 5→50→800 ramp ve EDR/signing kapıları atlanır |

## 6. D29 Kabul Katmanları

| Katman | Kanıt |
|---|---|
| **Up** | Backend catalog endpoint / agent command adapter / web route ayakta |
| **Functional** | 7-Zip install request → agent execute → detection success → result submit |
| **Secured** | RBAC allow/deny, catalog-only validation, audit row, no-token 401, unauthorized 403 |
| **D30 artifact** | Agent release hash/signature, backend image digest, web digest istenenle canlı eşleşir |

Read-only posture sinyalleri için ek kabul:

| Sinyal | Kanıt |
|---|---|
| Pending reboot | Structured `pendingReboot=true/false` + source list |
| Security posture | Defender/Firewall/BitLocker status; secret/recovery key yok |
| Local admins | Administrators grubu sanitized üyelik listesi |
| Device health | Disk/RAM/uptime özet metrikleri; raw process/user dump yok |
| Hardware/device | CPU/RAM/disk/model/BIOS/TPM/network summary; serial/MAC/IP policy-gated |

## 7. İlk Pilot Paketleri

| Paket | Provider | Paket ID | Neden |
|---|---|---|---|
| 7-Zip | WinGet | `7zip.7zip` | Küçük, ücretsiz, yaygın, detection kolay |
| Notepad++ | WinGet | `Notepad++.Notepad++` | Yaygın, düşük risk |
| Google Chrome | WinGet | `Google.Chrome` | Yaygın ama policy/enterprise installer kontrolü ayrıca değerlendirilmeli |

İlk PR yalnız 7-Zip ile ilerler; ikinci/üçüncü paketler capability kanıtından
sonra açılır.

## 8. Repo Sınırı

| Repo | Sahip olduğu iş |
|---|---|
| `platform-agent` | Registry inventory, WinGet adapter, install/uninstall executor, posture/health/hardware inventory, self-update |
| `platform-backend` | Catalog API, command validation, software/hardware inventory ingest/query, result/detection/audit |
| `platform-web` | Software inventory view, hardware/device inventory view, approved install UI, command status |
| `platform-k8s-gitops` | Plan, runbook, runtime governance, test/prod digest movement |

## 9. İlk Source PR Sırası

1. `platform-k8s-gitops`: üç-AI mutabakat patch'i bu plan/runbook/ADR/current-state yüzeylerine işlenir.
2. `platform-agent`: `AG-025H` probe decoupling + explicit lightweight/full inventory tests.
3. `platform-web`: `WEB-011` read-only software + WinGet readiness görünümü.
4. `platform-backend`: `BE-020` approved catalog skeleton.
5. `platform-backend`: `BE-020I` software inventory ingest/query surface.
6. `platform-backend`: `INSTALL_APPROVED_SOFTWARE` command contract + `BE-021` audit/detection state.
7. `platform-agent`: `AG-027` 7-Zip install adapter.
8. `platform-web`: `WEB-012` approved install UI.
9. `platform-agent`: `AG-030` + `AG-031` + `AG-032` + `AG-033` + `AG-035` posture/health/hardware quick wins.
10. `platform-backend`: `BE-022` device inventory ingest/query.
11. `platform-web`: `WEB-013` hardware/device inventory view.
12. `platform-agent`: `AG-028` uninstall.
13. `platform-agent`: `AG-029` signed update.
14. `platform-agent`: `AG-034` SMB/file action discovery, runtime yok.

## 10. Açık Notlar

- Bu plan Intune/SCCM/PDQ alternatifi olarak başlamaz; ücretsiz WinGet +
  controlled catalog çizgisiyle başlar.
- Intune varsa ileride provider olarak eklenebilir, ama bu planın ana yolu
  değildir.
- 22.3 domain-wide mass deployment bu planı tamamlayıcıdır: agent'ın dağıtım
  kanalıdır. 22.5 ise agent yüklendikten sonra yazılım yönetimi kabiliyetidir.
- Domain pilot flow, Faz 22.2.B / 22.3 altında ilerler; 22.5 yalnız agent
  kurulu cihazda software/posture/hardware yönetimi sağlar.
- Dual-control destructive command, BE-017 / D35-EA hattıdır; 22.5 install
  pilotu katalog + RBAC + audit ile başlar.
- Policy-based deployment, 22.3 MSI/GPO mass deployment hattıdır; 22.5 ilk
  aşamada tek cihaz / tek katalog item pilotudur.
- EDR allowlist + code signing, 22.2/22.3/22.4 güvenlik kapılarıdır; 22.5
  agent self-update ve install adapter'ları bu kapılara bağlı kalır.
