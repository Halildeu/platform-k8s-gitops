# Faz 22.5 M7 — Rollback Drill Evidence

> **Template**. Canlı drill (1 pilot cihaz) sırasında doldurulur. Runbook: `docs/runbooks/RB-faz22-m7-rollback-drill.md`. Gate: [#1379](https://github.com/Halildeu/platform-k8s-gitops/issues/1379).
> **Redaction**: raw token / cert / key / JWT / rejected payload / PII (UPN, email) **YAZILMAZ**. Yalnız class / prefix / redacted summary.

## Drill kimliği

| Alan | Değer |
|---|---|
| Drill tarihi (UTC) | `YYYY-MM-DDTHH:MMZ` |
| Pilot cihaz hostname | |
| Cihaz device_id (UUID prefix, ilk 8) | `xxxxxxxx` |
| OS / build | |
| MSI sürümü (signed) | `EndpointAgent-<ver>-signed.msi` |
| Signer thumbprint class | internal-CA leaf (AG-018) |
| Operatör | |
| Supervise (agent session) | |

## D1 — MSI uninstall + reinstall

| Kontrol | Beklenen | Gözlenen | PASS/FAIL |
|---|---|---|---|
| ProductCode bulundu | `{GUID}` | | |
| Uninstall exit code | 0 / 3010 | | |
| Reinstall exit code | 0 | | |
| Reinstall sonrası service | `Running` | | |

Uninstall log tail (redacted): `<son 10 satır, secret yok>`

## D2 — Post-rollback cihaz state

| Kontrol | Beklenen (uninstall sonrası) | Gözlenen | PASS/FAIL |
|---|---|---|---|
| Service `EndpointAgent` | yok | | |
| Scheduled task `EndpointAgent*` | yok | | |
| HKLM `Services\EndpointAgent` | yok | | |
| HKLM `Services\EndpointAgent\Environment` regkey | temizlendi | | |
| HKLM `SOFTWARE\EndpointAgent` `Mode` | reinstall mode'una eşit (stale değil) | | |
| `endpoint-agent.exe` | yok | | |
| Log dizini (`ProgramData\EndpointAgent\logs`) | korundu | | |
| Config store (`hmac-credential.dpapi`) | korundu (`-RemoveConfig` yoksa) | | |
| Orphan process / locked binary | yok | | |

## D3 — Enrollment revoke (decommission) + reactivate

| Kontrol | Beklenen | Gözlenen | PASS/FAIL |
|---|---|---|---|
| Decommission status | `DECOMMISSIONED` | | |
| Revoked cihaza komut YARATMA (`type` field) | **409** "...is decommissioned..." (400 = field hatası, FAIL) | | |
| Agent-side poll (revoked) | komut yok | | |
| Reactivate status | `OFFLINE` / `PENDING_ENROLLMENT` | | |
| Reactivate sonrası heartbeat | `ONLINE` | | |
| Audit row `ENDPOINT_DEVICE_DECOMMISSIONED` | yazıldı (lifecycle + hash-chain) | | |
| Audit row `ENDPOINT_DEVICE_REACTIVATED` | yazıldı | | |

Cascade counts (decommission, gerçek audit alanları): `cancelledCommands`=`?`, `revokedTokens`=`?`, `finalizedUninstalls`=`?` (secret clear yan-etki, ayrı count yok)

## D4 — GPO rollback (operatör AD)

| Kontrol | Beklenen | Gözlenen | PASS/FAIL |
|---|---|---|---|
| GPO unlink / security-filter remove | uygulandı | | |
| `gpresult /r` GPO görünmüyor | evet | | |
| GPO Software Installation "uninstall on scope exit" | configured / NOT-configured (manuel) | | |
| Assigned-MSI scope-dışı uninstall | (yalnız configured ise) uninstall | | |
| Propagation süresi | kaydedildi | `__ dk` | |

## D5 — Backend dark / pause

| Katman | Komut | Etki gözlendi | PASS/FAIL |
|---|---|---|---|
| 1. Yeni komut üretimi durdu (PRIMARY) | (operasyonel — yeni POST yok) | | |
| 2. Rollout-ring de-assign (yalnız yaratma-zamanı) | `PATCH .../rollout` | | |
| 3. Zaten-queued iptal (cascade) | `POST .../decommission` | | |
| Pause sonrası YENİ komut üretimi | yok | | |
| Queued komut (ring de-assign sonrası, decommission ÖNCESİ) | hâlâ claim edilebilir (beklenen — ring claim'i filtrelemez) | | |

## D6 — Evidence retention + comms

| Kontrol | Durum |
|---|---|
| Failed-device bundle (varsa) saklandı | |
| Audit row referansları kaydedildi | |
| IT/help-desk comms gönderildi | |
| Escalation owner + SLA yazılı | |

## Sonuç

| Alan | Değer |
|---|---|
| **Recommendation** | PASS (M5/M6 expansion açılabilir) / FAIL (gate kapalı) |
| Root-cause class (FAIL ise) | |
| Sonraki dalga onayı | bekliyor / verildi |
| Full-consensus (§0.5.9) | Claude / Mavis / Codex verdict |
