# RB-endpoint-agent-binary-upgrade

Endpoint Agent Windows binary upgrade (in-place service stop + replace +
start). Lab-only (Faz 22.1) — production IT-owned pilot Faz 22.2'de Azure
Trusted Signing ile yenilenecek.

**Tetik**: Yeni binary release (örn. PR #25 absorb sha-1e915a2) cihaza
deploy edilmeli + agent yeni davranışla heartbeat etmeli.

**Ön koşul**: Hedef cihaz Endpoint Agent zaten kurulu (eski sürüm
çalışıyor). Çalışan tek bir `EndpointAgent` Windows servisi var.

**Geri alma**: Önceki binary'nin SHA256 hash'i kaydedildiyse geri alma
mümkün; bu runbook ileri-yön upgrade pattern'i (rollback eski binary'i
yeniden yüklemek + restart).

## Operator action (3-step, ~5 dakika)

### 1. Fresh enrollment token üret

Web UI: `https://testai.acik.com/endpoint-admin/enrollments` → **+ Yeni
Enrollment Oluştur** → Açıklama: `<HOSTNAME> binary upgrade re-enroll`
→ **Oluştur** → token'ı **hemen kopyala** (tek-defa-görünür reveal
pattern; modal kapatılınca tekrar gösterilmez).

Token TTL default 60 dakika. Adım 3'e kadar zaman var.

### 2. Binary'yi indir

İki yol:

**Yol A — GitHub Actions artifact** (operator GitHub'a erişebiliyorsa):

```
https://github.com/Halildeu/platform-agent/actions/runs/<RUN_ID>
```

`endpoint-agent-lab-evidence-<RUN_ID>` artifact'ını indir, zip aç.
İçinde:

- `endpoint-agent.exe` (signed, ~7 MB)
- `SHA256SUMS` (unsigned hash kontrol için)
- `SIGNING-EVIDENCE.md` (lab cert thumbprint)
- `signtool-verify.log` (signtool verify çıktısı)

**Yol B — Operator portal download** (gelecekte, BL-016 binary
distribution UI):

Henüz aktif değil. Şu an Yol A.

### 3. Cihazda elevated PowerShell ile upgrade çalıştır

Cihaza (örn. RDP / yerel oturum) bağlan, **Run as Administrator**
PowerShell aç, aşağıdaki snippet'i çalıştır:

```powershell
$EnrollmentToken = '<TOKEN_BURAYA>'
$ApiUrl = 'https://testai.acik.com/api/v1/endpoint-agent'
$BinaryPath = 'C:\Path\To\endpoint-agent.exe'  # Adım 2'den

# Mevcut servisi durdur
Stop-Service EndpointAgent -Force
$tries = 0
while ((Get-Service EndpointAgent).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 2
    $tries++
}

# Yeni binary'yi yerleştir (tamper-protected dizine yazma erişimi
# için SYSTEM context gerekir; elevated PowerShell sc.exe + service
# stop sonrası dosya ACL'i geçici release eder)
Copy-Item -LiteralPath $BinaryPath -Destination 'C:\Program Files\EndpointAgent\endpoint-agent.exe' -Force
Unblock-File -LiteralPath 'C:\Program Files\EndpointAgent\endpoint-agent.exe' -ErrorAction SilentlyContinue

# Fresh enrollment token'ı machine env'e yaz (önceki token consumed
# olduğu için service restart sonrası agent yeni token'ı redeem eder)
[Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', $EnrollmentToken, 'Machine')

# Servisi başlat
Start-Service EndpointAgent
Start-Sleep -Seconds 5
Get-Service EndpointAgent | Format-List Name, Status
```

**Beklenen çıktı**: `Status: Running`. Agent süreç ID değişmiş olmalı
(yeni binary fresh start).

## Verify (operator + agent observer)

### Cihaz tarafı

```powershell
# Servis durumu
Get-Service EndpointAgent

# Süreç bilgisi (PID değişmiş olmalı)
Get-CimInstance Win32_Service | Where-Object Name -eq 'EndpointAgent' |
    Select-Object PathName, ProcessId, State

# Diagnose komutları (binary'nin gerçekten yeni sürüm olduğunu doğrula)
& 'C:\Program Files\EndpointAgent\endpoint-agent.exe' diagnose winget-egress
```

PR #25 sonrası beklenen `diagnose winget-egress` wire shape:

```json
{
  "supported": true,
  "schemaVersion": 1,
  "egress": {
    "dns": [{"target": "cdn.winget.microsoft.com", "ok": true}, ...],
    "tcp": [{"target": "cdn.winget.microsoft.com:443", "ok": true}, ...],
    "https": [{"target": "https://cdn.winget.microsoft.com", "ok": true}, ...]
  }
}
```

**Yasak**: `"dns": null` (eski binary bug — backend'i 400 ile reject
ederdi).

### Backend tarafı (observer)

```bash
# 1-2 dakika bekle, agent heartbeat + COLLECT_INVENTORY çalıştırsın
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs deploy/endpoint-admin-service --since=2m 2>&1 | \
  grep -E 'Hardware inventory snapshot persisted device_id=<DEVICE_ID>' | head -5"
```

Web UI:
`https://testai.acik.com/endpoint-admin/devices` → cihazı seç → **Donanım**
tab → "Toplama Zamanı" güncel olmalı.

### Enrollment token

Web UI: `https://testai.acik.com/endpoint-admin/enrollments` → açıklama
satırını bul → Durum **CONSUMED** + Cihaz alanı dolu olmalı.

## Test (HALILKOOLUB735 referans)

Bu runbook 2026-05-29 HALILKOOLUB735 Parallels W11 lab'inde end-to-end
doğrulandı:

- Binary 7491072 → 7195456 bytes swap ✓
- Service PID 5644 → 2832 (yeni süreç) ✓
- `diagnose winget-egress` dolu arrays ✓
- Re-enroll: token `0cFdPw...` CONSUMED → device d0efb00a-... rebound ✓
- BE-022 V14 hardware ingest LIVE (snapshot a4d68420 persisted) ✓
- UI Donanım tab "Toplama Zamanı" 10:22:09 (fresh) ✓

## Bilinen sorunlar

### Enrollment token stale loop

Agent service restart sonrası in-memory HMAC credentials kayboluyor.
Eski token Machine env'inde kalırsa agent sonsuz redeem retry yapar
(409 "Enrollment token is not pending"). Bu yüzden upgrade akışında
**her zaman fresh token** gerekir (Adım 1).

Gelecek fix: agent 2 başarısız enroll sonrası persist marker yazsın,
3. denemede env token'ı clear etsin (out-of-scope this runbook).

### Tamper protection ACL

`C:\Program Files\EndpointAgent\endpoint-agent.exe` SYSTEM-only DACL ile
korunuyor (install.ps1 `Protect-AgentDirectories` çağrısı). Service
çalışırken (file lock + DACL) dosyaya yazılamaz; service stop sonrası
DACL hâlâ aktif ama file lock kalkar ve admin PowerShell write hakkına
sahiptir.

### UAC dialog

Elevated PowerShell başlatmak için UAC dialog "Evet" tıklanması gerek.
Otomasyon mümkün değil (security boundary). Operator açık RDP / yerel
oturumda manuel tıklar.

## Cross-AI peer review (gelecek runbook revize)

Bu runbook taslağı Claude tarafından HALILKOOLUB735 LIVE evidence
çerçevesinden çıkarıldı. Faz 22.2 IT-owned pilot öncesi:

- Codex `019e72a1` benzeri thread aç: bu runbook'u Codex'e oku +
  adversarial review iste
- Production-grade upgrade için Azure Trusted Signing + remote
  PowerShell session pattern ekle
- Rollback path netleştir (önceki binary backup + restore)

## Ref

- platform-agent PR [#25](https://github.com/Halildeu/platform-agent/pull/25)
  — AG-026A defensive wire shape (commit `1e915a2d`)
- HALILKOOLUB735 LIVE evidence: `docs/state/current-state.md`
  "Live Delta — Faz 22.5.2 Hardware ingest end-to-end LIVE (2026-05-29)"
- install.ps1: `platform-agent/installers/windows/install.ps1`
- ADR-0012-EA: Endpoint Admin Governance Charter
