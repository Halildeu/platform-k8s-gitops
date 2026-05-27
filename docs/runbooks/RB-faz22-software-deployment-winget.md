# RB — Faz 22.5 Software Deployment WinGet Pilot

> **Status**: PLAN-ONLY / execution blocked until AG-025, AG-026, BE-020, AG-027, BE-021
> **Tracked by**: platform-k8s-gitops#1083

Bu runbook, Endpoint-Enes agent hattında ücretsiz WinGet tabanlı yazılım
yönetimi için ilk pilot akışını tarif eder.

Bu dosya bugün çalıştırılacak operasyon komutu vermez. İlgili agent/backend
capability'leri source repolarda gelene kadar sadece takip planıdır.

## 1. Amaç

İlk pilotta 7-Zip kurulumu üzerinden şu zincir kanıtlanır:

```text
Approved catalog item
→ backend command queue
→ agent poll
→ WinGet silent install
→ detection
→ result submit
→ audit row
→ web status
```

## 2. Ön Koşullar

| Gate | Gereken |
|---|---|
| Agent | `AG-025` installed software inventory |
| Agent | `AG-026` WinGet readiness |
| Agent | `AG-030` pending reboot detection |
| Agent | `AG-031` Defender/Firewall/BitLocker posture |
| Agent | `AG-032` local admin group inventory |
| Agent | `AG-033` disk/RAM/uptime health snapshot |
| Backend | `BE-020` approved software catalog |
| Agent | `AG-027` approved install command |
| Backend | `BE-021` result/detection/audit |
| Web | `WEB-011` inventory view (opsiyonel ilk pilotta) |
| Web | `WEB-012` install UI (opsiyonel ilk pilotta) |

## 3. Güvenlik Kuralları

- Raw shell yok.
- Serbest package id yok.
- Rastgele URL/EXE yok.
- Katalog dışı package install yok.
- Install request RBAC ile korunur.
- Install/uninstall audit zorunludur.
- Detection olmadan success kabul edilmez.

## 4. İlk Katalog Kaydı

```json
{
  "catalogItemId": "7zip",
  "displayName": "7-Zip",
  "provider": "winget",
  "packageId": "7zip.7zip",
  "publisher": "Igor Pavlov",
  "versionPolicy": "latest",
  "silent": true,
  "enabled": true,
  "riskLevel": "low",
  "detectionRule": {
    "type": "registryDisplayName",
    "displayNameContains": "7-Zip"
  }
}
```

## 5. Read-only Preflight

Agent tarafında beklenen read-only komutlar:

```powershell
endpoint-agent.exe diagnose software
endpoint-agent.exe diagnose winget
endpoint-agent.exe diagnose posture
endpoint-agent.exe diagnose health
endpoint-agent.exe diagnose local-admins
```

Beklenen kanıtlar:

- Kurulu program listesi JSON döner.
- Lisans key, product key, bearer token, password, full SID, kullanıcı home path
  sızmaz.
- `winget` versiyonu döner veya structured `notInstalled` sonucu döner.
- `winget` source list okunur.
- `7zip.7zip` query sonucu structured döner.
- Pending reboot structured döner; hangi source tetiklediği listelenir.
- Defender/Firewall/BitLocker durumları döner; BitLocker recovery key veya
  secret toplanmaz.
- Local Administrators grubu sanitized üyelik listesi döner; credential veya
  full token dump yoktur.
- Disk/RAM/uptime özeti döner; process/user dump veya gereksiz yüksek
  kardinaliteli performans verisi yoktur.

## 6. Install Command Shape

Backend komutu raw provider parametresi taşımaz:

```json
{
  "type": "INSTALL_APPROVED_SOFTWARE",
  "catalogItemId": "7zip",
  "requestedVersion": "latest"
}
```

Agent kendi tarafında catalog metadata ile provider komutunu üretir.

## 7. D29 Pilot Acceptance

| Katman | Kanıt |
|---|---|
| Up | Agent running, backend endpoint healthy, command queue reachable |
| Functional | `INSTALL_APPROVED_SOFTWARE` 7-Zip için `SUCCEEDED` döner |
| Detection | Registry / WinGet query 7-Zip kurulumunu doğrular |
| Posture | Pending reboot, security posture, local admins ve device health read-only döner |
| Secured | Yetkisiz kullanıcı 403; no-token 401; katalog dışı id reject |
| Audit | Created, delivered, started, completed/result event'leri görünür |

## 8. Rollback / Uninstall Gate

Uninstall ilk pilotun parçası değildir. `AG-028` gelince ayrı test edilir:

```json
{
  "type": "UNINSTALL_APPROVED_SOFTWARE",
  "catalogItemId": "7zip"
}
```

Bu komut yalnız katalogda `managedUninstall=true` olduğunda açılır.

## 9. Operator Notu

Bu pilot için Intune, SCCM, PDQ veya ManageEngine gerekmez. Bunlar ileride
provider/integration olarak değerlendirilebilir; ilk ücretsiz yol WinGet +
Approved Software Catalog'dur.

## 10. Deferred SMB / File Action Notu

SMB veya kullanıcı dosyası aksiyonları bu runbook'un pilot kapsamı değildir.
Bu alan ayrı discovery ile ele alınır:

- path whitelist,
- RBAC scope,
- dual-control gerektiren aksiyon sınıfları,
- pre/post snapshot,
- audit retention,
- destructive saga / rollback sınırı.

Bu kapılar yazılmadan agent üzerinden dosya silme, taşıma, kopyalama veya
kullanıcı masaüstüne müdahale açılmaz.
