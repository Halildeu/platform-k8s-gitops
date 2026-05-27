# Faz 22.5 — Software Deployment Quick Wins

> **Status**: PLAN-ONLY / source work not started
> **Tracked by**: platform-k8s-gitops#1083
> **Scope date**: 2026-05-27

Bu doküman Endpoint-Enes / Endpoint Admin agent hattına **ücretsiz ve sektör
standardına yakın yazılım yönetimi** kabiliyeti eklemek için takip edilebilir
planı tanımlar.

Bu plan bir runtime kabiliyeti iddia etmez. `AG-025` ve sonraki işler ilgili
source repolarda ayrıca uygulanıp test edilmeden agent'ın yazılım kurabildiği
söylenmez.

## 1. Ürün Hedefi

Hedef, agent üzerinden Windows cihazlarda kontrollü yazılım yönetimi sağlamaktır:

1. Kurulu program envanteri okunur.
2. Cihazda WinGet hazır mı kontrol edilir.
3. Backend'de onaylı yazılım kataloğu tutulur.
4. Agent yalnız katalogda onaylı paketleri sessiz kurar.
5. Kurulum sonucu detection + audit ile kanıtlanır.
6. Pending reboot, Defender/Firewall/BitLocker, local admin ve temel cihaz sağlık
   sinyalleri aynı ekrandan okunur.
7. Kaldırma, rollback ve agent self-update daha sonraki kapılarda açılır.

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
| **AG-025** | `platform-agent` | Installed software inventory | TODO | HKLM/HKCU uninstall registry kaynaklarından sanitized JSON döner; lisans key, product key, user path sızmaz |
| **AG-026** | `platform-agent` | WinGet readiness check | TODO | `winget --version`, source list ve approved package query sonucu structured döner |
| **BE-020** | `platform-backend` | Approved software catalog API | TODO | Package id, provider, version policy, publisher, detection rule ve risk metadata tutulur |
| **AG-027** | `platform-agent` | Approved software install command | TODO | Yalnız backend catalog item id ile silent install çalışır; raw package id kabul edilmez |
| **BE-021** | `platform-backend` | Install result / detection / audit | TODO | Install request, result, detection state, actor ve device audit zincirine düşer |
| **WEB-011** | `platform-web` | Software inventory view | TODO | Cihaz detayında kurulu program listesi filtrelenebilir görünür |
| **WEB-012** | `platform-web` | Approved install UI | TODO | Yetkili kullanıcı katalogdan kurulum isteği oluşturabilir; durum/audit görünür |
| **AG-028** | `platform-agent` | Software uninstall / detection | TODO | Yalnız katalog tarafından yönetilen paket kaldırılır; detection sonucu doğrulanır |
| **AG-029** | `platform-agent` | Signed agent self-update | TODO | Signed manifest + hash + version policy + rollback guard ile agent güncelleme yolu açılır |
| **AG-030** | `platform-agent` | Pending reboot detection | TODO | CBS/Windows Update/PendingFileRenameOperations sinyalleri structured döner; install sonrası restart ihtiyacı görünür |
| **AG-031** | `platform-agent` | Endpoint security posture inventory | TODO | Defender, Firewall ve BitLocker durumu read-only JSON döner; recovery key veya secret sızmaz |
| **AG-032** | `platform-agent` | Local admin group inventory | TODO | Local Administrators üyeleri SID/name/type ile döner; domain SID/full token/credential sızmaz |
| **AG-033** | `platform-agent` | Device health snapshot | TODO | Disk/RAM/uptime/boot time temel sağlık özeti döner; performans counter spam'i yok |
| **AG-034** | `platform-agent` | SMB/file actions discovery guardrail | DEFERRED | Dosya aksiyonları sadece discovery/tehdit modeli; whitelist + RBAC + audit + dual-control olmadan runtime yok |

## 4. Milestone Sırası

### 22.5.0 Tracking Foundation

- Bu doküman ve runbook canonical plan olarak eklenir.
- Board issue'ları gerçek source repolarda açılır.
- Runtime claim yapılmaz.

### 22.5.1 Read-only Device Software View

- `AG-025` ve `AG-026`.
- Sadece okuma yapılır.
- `COLLECT_INVENTORY` payload'ına geniş özet eklenebilir:
  - `installedSoftwareCount`
  - `wingetInstalled`
  - `wingetVersion`
  - `wingetSourceAvailable`

### 22.5.2 Device Posture Quick Wins

- `AG-030`, `AG-031`, `AG-032` ve `AG-033`.
- Sadece read-only inventory sinyalleri toplanır.
- Panelde program kurulumu için karar vermeyi kolaylaştırır:
  - restart bekliyor mu,
  - Defender aktif mi,
  - Firewall profilleri açık mı,
  - BitLocker koruması açık mı,
  - local admin grubunda kimler var,
  - disk/RAM/uptime sağlığı nedir.
- BitLocker recovery key, credential, bearer token, password, product key ve
  tam kullanıcı profili path'i toplanmaz.

### 22.5.3 Approved Catalog Control Plane

- `BE-020`.
- İlk katalog satırı: `7zip.7zip`.
- Katalog alanları:
  - `catalogItemId`
  - `provider`
  - `packageId`
  - `displayName`
  - `publisher`
  - `versionPolicy`
  - `silentArgs`
  - `detectionRule`
  - `riskLevel`
  - `enabled`

### 22.5.4 First Install Pilot

- `AG-027` + `BE-021`.
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
| `platform-agent` | Registry inventory, WinGet adapter, install/uninstall executor, posture/health inventory, self-update |
| `platform-backend` | Catalog API, command validation, result/detection/audit |
| `platform-web` | Inventory view, approved install UI, command status |
| `platform-k8s-gitops` | Plan, runbook, runtime governance, test/prod digest movement |

## 9. İlk Source PR Sırası

1. `platform-agent`: `AG-025` + `AG-026`.
2. `platform-agent`: `AG-030` + `AG-031` + `AG-032` + `AG-033`.
3. `platform-backend`: `BE-020` catalog skeleton.
4. `platform-agent`: `AG-027` 7-Zip install adapter.
5. `platform-backend`: `BE-021` result/detection/audit.
6. `platform-web`: `WEB-011` inventory/posture view.
7. `platform-web`: `WEB-012` approved install UI.
8. `platform-agent`: `AG-028` uninstall.
9. `platform-agent`: `AG-029` signed update.
10. `platform-agent`: `AG-034` SMB/file action discovery, runtime yok.

## 10. Açık Notlar

- Bu plan Intune/SCCM/PDQ alternatifi olarak başlamaz; ücretsiz WinGet +
  controlled catalog çizgisiyle başlar.
- Intune varsa ileride provider olarak eklenebilir, ama bu planın ana yolu
  değildir.
- 22.3 domain-wide mass deployment bu planı tamamlayıcıdır: agent'ın dağıtım
  kanalıdır. 22.5 ise agent yüklendikten sonra yazılım yönetimi kabiliyetidir.
- Domain pilot flow, Faz 22.2.B / 22.3 altında ilerler; 22.5 yalnız agent
  kurulu cihazda software/posture yönetimi sağlar.
- Dual-control destructive command, BE-017 / D35-EA hattıdır; 22.5 install
  pilotu katalog + RBAC + audit ile başlar.
- Policy-based deployment, 22.3 MSI/GPO mass deployment hattıdır; 22.5 ilk
  aşamada tek cihaz / tek katalog item pilotudur.
- EDR allowlist + code signing, 22.2/22.3/22.4 güvenlik kapılarıdır; 22.5
  agent self-update ve install adapter'ları bu kapılara bağlı kalır.
