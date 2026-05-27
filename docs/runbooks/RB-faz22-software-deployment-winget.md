# RB — Faz 22.5 Software Deployment WinGet Pilot

> **Status**: SOURCE-PARTIAL / execution blocked until BE-020 + BE-021 + AG-027
> **Tracked by**: platform-k8s-gitops#1083, platform-k8s-gitops#1086, platform-k8s-gitops#1088

Bu runbook, Endpoint-Enes agent hattında ücretsiz WinGet tabanlı yazılım
yönetimi için ilk pilot akışını tarif eder.

Bu dosya bugün install operasyon komutu vermez. `AG-025`/`AG-026` read-only
source foundation başlamış olsa da 7-Zip install pilotu `BE-020` approved
catalog, `BE-021` result/detection/audit ve `AG-027` adapter gelmeden
çalıştırılmaz.

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
| Agent | `AG-025` installed software inventory source-partial + field smoke |
| Agent | `AG-026` WinGet readiness source-partial + field smoke |
| Agent | `AG-025H` lightweight/full inventory ayrımı; heartbeat/auto-enroll full scan'e girmemeli |
| Backend | `BE-020I` software inventory ingest/query path |
| Agent | `AG-030` pending reboot detection |
| Agent | `AG-031` Defender/Firewall/BitLocker posture |
| Agent | `AG-032` local admin group inventory |
| Agent | `AG-033` disk/RAM/uptime health snapshot |
| Agent | `AG-035` hardware/device inventory |
| Backend | `BE-022` device inventory ingest/query path |
| Backend | `BE-020` approved software catalog |
| Agent | `AG-027` approved install command |
| Backend | `BE-021` result/detection/audit |
| Web | `WEB-011` inventory view (opsiyonel ilk pilotta) |
| Web | `WEB-013` hardware/device inventory view (opsiyonel ilk pilotta) |
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
  "sourceType": "winget",
  "sourceName": "winget-community",
  "sourceTrust": "approved",
  "packageId": "7zip.7zip",
  "publisher": "Igor Pavlov",
  "approvedVersionRange": "latest",
  "installerType": "winget",
  "silentArgsPolicy": "provider-template-only",
  "sha256": null,
  "provenance": "winget-community-catalog-reviewed",
  "silent": true,
  "enabled": true,
  "riskTier": "low",
  "detectionRule": {
    "type": "registryDisplayName",
    "displayNameContains": "7-Zip"
  },
  "approvedBy": "endpoint-admin-manager"
}
```

## 5. Read-only Preflight

Agent tarafında beklenen read-only komutlar:

```powershell
endpoint-agent.exe diagnose software
endpoint-agent.exe diagnose winget
endpoint-agent.exe diagnose posture
endpoint-agent.exe diagnose health
endpoint-agent.exe diagnose hardware
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
- Hardware/device inventory CPU, RAM, disk, manufacturer/model, BIOS version,
  TPM status, network adapter summary ve OS/build bilgilerini read-only döner.
- Serial number, MAC/IP gibi alanlar policy-gated olur; varsayılan çıktı hash,
  masked veya summary seviyesinde kalır.
- Product key, BitLocker recovery key, TPM key material, token veya credential
  hiçbir koşulda toplanmaz.

Inventory command preflight:

```json
{
  "type": "COLLECT_INVENTORY",
  "payload": {
    "includeSoftware": true
  }
}
```

Install gate için bu komutun backend result/query yüzeyinde software summary ve
gerekiyorsa `apps[]` listesini kaybetmeden görünmesi gerekir. Bu yol
kanıtlanmadan `INSTALL_APPROVED_SOFTWARE` açılmaz.

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

### 6.1 Install Açma Kapısı

Install pilotu ancak aşağıdaki durum birlikte kanıtlanırsa koşulur:

1. `AG-025`/`AG-026` read-only preflight PASS.
2. Lightweight/heartbeat akışları full software scan'e girmiyor.
3. `BE-020` catalog item enabled + approved.
4. `BE-020I` inventory ingest/query path software payload'ı saklıyor.
5. `BE-021` result/detection/audit state hazır.
6. Yetkisiz kullanıcı 403, no-token 401, katalog dışı package id reject.
7. Agent yalnız kendi template'inden WinGet komutu üretir; raw shell, raw URL,
   raw installer args kabul edilmez.

## 7. D29 Pilot Acceptance

| Katman | Kanıt |
|---|---|
| Up | Agent running, backend endpoint healthy, command queue reachable |
| Functional | `INSTALL_APPROVED_SOFTWARE` 7-Zip için `SUCCEEDED` döner |
| Detection | Registry / WinGet query 7-Zip kurulumunu doğrular |
| Posture | Pending reboot, security posture, local admins ve device health read-only döner |
| Hardware | CPU/RAM/disk/model/BIOS/TPM/network summary read-only döner; serial/MAC/IP policy-gated |
| Secured | Yetkisiz kullanıcı 403; no-token 401; katalog dışı id reject |
| Audit | Created, delivered, started, completed/result event'leri görünür |

Bu tablodaki `Functional` ve sonrası bugün claimed değildir. Read-only
preflight kanıtı install acceptance yerine geçmez.

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
