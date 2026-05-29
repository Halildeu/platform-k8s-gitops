# RB — Faz 22.5 Software Deployment WinGet Pilot

> **Status (2026-05-29 truth refresh)**: SOURCE-MERGED + testai LIVE for
> catalog (BE-020) + preflight contract (BE-021A) + install command +
> audit (BE-021) + compliance evaluator (BE-023) + ingest/query
> (BE-020I/BE-022/BE-022Q) + adapter (AG-027) + agent foundation
> (AG-025/AG-025H/AG-026/AG-026A/AG-026B/AG-026C/AG-026D) + frontend
> (WEB-011/WEB-013/WEB-014A-D/WEB-017/WEB-018); **7-Zip lifecycle live
> smoke chain end-to-end NOT yet executed** + **AG-027L exit-code /
> redacted log capture TODO**. See `docs/state/current-state.md`
> 2026-05-29 PM delta + `faz-22-software-deployment-plan.md` §0.1bis +
> §9.bis for honest acceptance gates.
>
> Bu runbook'un 2026-05-23 öncesi "execution blocked" iddiası
> superseded; aşağıdaki adımlar source-merged yolu temsil eder.
> 7-Zip pilot live smoke evidence patch'i ayrı PR'da gelecek.
> **Tracked by**: platform-k8s-gitops#1083, platform-k8s-gitops#1086, platform-k8s-gitops#1088, platform-k8s-gitops#1090

Bu runbook, Endpoint-Enes agent hattında ücretsiz WinGet tabanlı yazılım
yönetimi için ilk pilot akışını tarif eder.

Bu dosya bugün install operasyon komutu vermez. `AG-025`/`AG-026` read-only
source foundation merged (`PR #20 0eff2db`, `PR #21 f3b5c68`); 7-Zip install
pilotu için `BE-020` approved catalog (`PR #306/#308`), `BE-021`
result/detection/audit (`PR #317/#318/#321`) ve `AG-027` adapter (`PR #23
7cf6f14`) **kaynak olarak MERGED**, ama **end-to-end live smoke chain
henüz koşturulmadı**. AG-027L exit-code/redacted log capture hâlâ TODO.
Ek quick-win fazları da aynı kuralı izler: WinGet source/egress readiness
(`AG-026A PR #22, PR #25`), install dry-run (`BE-021A PR #312`), compliance
evaluator (`BE-023 PR #313/#314/#315`), outdated visibility (`AG-036 TODO`)
ve diagnostics quick wins (`AG-037/AG-038/AG-039/AG-040 TODO`).

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
| Agent | `AG-026A` WinGet source / egress readiness; source list + package query + proxy/TLS summary |
| Agent | `AG-025H` lightweight/full inventory ayrımı; heartbeat/auto-enroll full scan'e girmemeli |
| Backend | `BE-020I` software inventory ingest/query path |
| Backend | `BE-023` software compliance evaluator (approved/missing/outdated/prohibited) |
| Agent | `AG-036` outdated software inventory read-only |
| Backend | `BE-024` inventory diff/history + `BE-025` prohibited software detection |
| Agent | `AG-030` pending reboot detection |
| Agent | `AG-031` Defender/Firewall/BitLocker posture |
| Agent | `AG-032` local admin group inventory |
| Agent | `AG-033` disk/RAM/uptime health snapshot |
| Agent | `AG-035` hardware/device inventory |
| Agent | `AG-037` Windows Update / hotfix posture |
| Agent | `AG-038` agent self-health / connectivity diagnostics |
| Agent | `AG-039` critical services inventory |
| Agent | `AG-040` startup apps / RDP / event-log health summary |
| Backend | `BE-022` device inventory ingest/query path |
| Backend | `BE-020` approved software catalog |
| Backend | `BE-021A` install dry-run / preflight contract |
| Agent | `AG-027` approved install command |
| Agent | `AG-027L` installer exit-code / redacted log capture |
| Backend | `BE-021` result/detection/audit |
| Web | `WEB-011` inventory view (opsiyonel ilk pilotta) |
| Web | `WEB-014` compliance / outdated software view |
| Web | `WEB-013` hardware/device inventory view (opsiyonel ilk pilotta) |
| Web | `WEB-012` install UI (opsiyonel ilk pilotta) |
| Web | `WEB-015` report / CSV export |
| Backend | `BE-026` deployment rings / device tags |
| Backend | `BE-027` maintenance window / scheduled command |
| Backend | `BE-028` rollout throttle / max concurrency |
| Backend | `BE-029` approved package bundles |

## 3. Güvenlik Kuralları

- Raw shell yok.
- Serbest package id yok.
- Rastgele URL/EXE yok.
- Katalog dışı package install yok.
- Install request RBAC ile korunur.
- Install/uninstall audit zorunludur.
- Detection olmadan success kabul edilmez.
- Install öncesi dry-run / preflight sonucu zorunludur.
- Installer log'u yalnız redacted ve sınırlı tail olarak tutulur.
- Auto-upgrade, auto-uninstall ve Windows patch install bu runbook kapsamında değildir.

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
endpoint-agent.exe diagnose winget-source
endpoint-agent.exe diagnose outdated-software
endpoint-agent.exe diagnose posture
endpoint-agent.exe diagnose health
endpoint-agent.exe diagnose hardware
endpoint-agent.exe diagnose local-admins
endpoint-agent.exe diagnose update-posture
endpoint-agent.exe diagnose agent-health
endpoint-agent.exe diagnose critical-services
endpoint-agent.exe diagnose exposure-summary
```

Beklenen kanıtlar:

- Kurulu program listesi JSON döner.
- Lisans key, product key, bearer token, password, full SID, kullanıcı home path
  sızmaz.
- `winget` versiyonu döner veya structured `notInstalled` sonucu döner.
- `winget` source list okunur.
- `7zip.7zip` query sonucu structured döner.
- WinGet source / egress readiness source list, package query, proxy/TLS ve
  timeout reason ile döner.
- Outdated software read-only sonucu döner; upgrade/install çalıştırılmaz.
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
- Windows Update / hotfix posture read-only döner; patch install veya reboot
  tetiklenmez.
- Agent self-health backend connectivity, DNS/TLS, last poll/result latency ve
  last error summary döner; enrollment/HMAC secret yoktur.
- Critical service inventory WinDefend, wuauserv, BITS, EventLog ve
  endpoint-agent service state döner; service restart yoktur.
- Startup/RDP/event summary yalnız count/state döner; full event message,
  browser history, command line dump veya credential yoktur.

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
3. `AG-026A` WinGet source / egress readiness PASS.
4. `BE-020` catalog item enabled + approved.
5. `BE-020I` inventory ingest/query path software payload'ı saklıyor.
6. `BE-023` catalog compliance state `COMPLIANT` veya kabul edilen `WARN`
   döndürüyor.
7. `BE-021A` install dry-run / preflight sonucu `PASS`.
8. `BE-021` result/detection/audit state hazır.
9. `AG-027L` exit-code ve redacted log capture hazır.
10. Yetkisiz kullanıcı 403, no-token 401, katalog dışı package id reject.
11. Agent yalnız kendi template'inden WinGet komutu üretir; raw shell, raw URL,
   raw installer args kabul edilmez.

## 7. D29 Pilot Acceptance

| Katman | Kanıt |
|---|---|
| Up | Agent running, backend endpoint healthy, command queue reachable |
| Functional | `INSTALL_APPROVED_SOFTWARE` 7-Zip için `SUCCEEDED` döner |
| Detection | Registry / WinGet query 7-Zip kurulumunu doğrular |
| Posture | Pending reboot, security posture, local admins ve device health read-only döner |
| Hardware | CPU/RAM/disk/model/BIOS/TPM/network summary read-only döner; serial/MAC/IP policy-gated |
| WinGet egress | Source/package query/proxy/TLS readiness PASS; install/upgrade yok |
| Compliance | Approved catalog status + outdated/prohibited state görünür; auto-remediation yok |
| Diagnostics | Agent health + critical services + Windows Update posture read-only döner |
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
