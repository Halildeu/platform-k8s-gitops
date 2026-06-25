# RB-faz24-wg-bplus-i3-management-audit-drift-monitor

> Scope: `platform-k8s-gitops#1864` / Faz 24 WG-B+ I3. This runbook defines
> metadata-only management audit and drift-monitor evidence for the
> WireGuard-canonical Denetim PC management plane. It does not enable
> direct-STT and does not prove `platform-ai#198` app-mTLS reachability.

## 1. Acceptance Boundary

I3 acceptance is a management-plane auditability gate. A valid evidence bundle
proves:

- who used the management path,
- when it happened,
- what class of operation occurred,
- whether the expected monitoring surfaces are active,
- and that the exported evidence contains no secret, raw audio, transcript, or
  command/script content.

It does not prove:

- product remote-ops acceptance,
- direct audio e2e,
- Denetim `8243` app-mTLS reachability,
- or any production cutover gate.

## 2. Required Evidence Surfaces

The evidence bundle must carry these eight checks with `status: pass`:

| Check id | Source | Required metadata |
|---|---|---|
| `openssh-event-log` | Denetim PC OpenSSH Operational log | user, source WG peer, accepted/denied class, timestamp |
| `powershell-transcription` | Protected transcription path | enabled state, file metadata, ACL, timestamp |
| `powershell-script-block` | PowerShell 4104/script-block metadata | event count/hash metadata only, no command text |
| `failed-login` | Windows Security/OpenSSH failure summary | count, time window, source class |
| `wireguard-health` | Denetim WireGuard peer status | latest handshake age, rx/tx deltas |
| `eset-firewall-drift` | Windows Firewall/WFP/ESET policy | expected WG-only allow surface, drift status |
| `time-sync` | `w32tm` / NTP status | clock offset within audit correlation threshold |
| `staging-connection-log` | `staging-sw` sshd/WireGuard logs | source/target metadata correlation |

The verifier enforces `who`, `when`, `what`, and `evidenceRef` on each check.

## 3. Evidence Contract

Write a JSON file using schema `faz24.wg-bplus.i3.audit.v1`:

```json
{
  "schemaVersion": "faz24.wg-bplus.i3.audit.v1",
  "collectedAt": "2026-06-25T00:10:00Z",
  "protectedEvidencePath": "\\\\denetim-pc\\protected-audit$\\faz24\\i3\\2026-06-25T001000Z",
  "retentionDays": 90,
  "acl": {
    "mode": "protected",
    "readers": ["platform-ops-audit"],
    "writers": ["svc-denetim-agent"]
  },
  "redaction": {
    "rawAudioIncluded": false,
    "rawTranscriptIncluded": false,
    "secretMaterialIncluded": false,
    "commandContentIncluded": false
  },
  "checks": [
    {
      "id": "openssh-event-log",
      "status": "pass",
      "who": "svc-denetim-agent",
      "when": "2026-06-25T00:01:00Z",
      "what": "OpenSSH publickey session accepted from WG peer",
      "evidenceRef": "windows/OpenSSH-Operational.evtx.jsonl"
    }
  ]
}
```

The real bundle includes all eight required check ids. The check `what` field
must describe the operation class, not the raw command or script content.

## 4. Redaction Rules

Allowed:

- usernames, hostnames, source/target IPs, ports, timestamps,
- event ids, event counts, status names, rule names,
- SHA-256 hashes of protected transcript/script-block files,
- relative evidence references under the protected evidence path.

Not allowed:

- passwords, tokens, JWTs, cookies, Vault secret ids, private keys,
- raw PowerShell command lines,
- script-block text,
- transcript text,
- raw audio bytes/base64,
- transcribed meeting content.

If raw protected files must be retained for audit, keep them only under the
protected path with restricted ACL and reference them by metadata/hash in the
JSON contract.

## 5. Collection Commands

### 5.1 Preferred self-hosted workflow path

Use the self-hosted `staging-sw` runner first. The workflow collects a
metadata-only JSON bundle, validates it with the repository verifier, uploads
the evidence artifact, and intentionally fails when any required I3 check is
not proven.

```bash
gh workflow run faz24-wg-bplus-i3-evidence.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f denetim_ssh_target=svc-denetim-agent@10.99.0.2 \
  -f lookback_hours=2 \
  -f wg_interface=auto
```

The artifact name is `faz24-wg-bplus-i3-evidence-<run_id>`. Its
`protectedEvidencePath` is the GitHub Actions artifact URI for that run. A red
workflow conclusion is still useful blocker evidence when the uploaded bundle
shows which management-audit surface is missing. Do not override a verifier
failure manually.

Use `wg_interface=auto` unless the staging host's WireGuard interface is
already confirmed. Auto mode runs `wg show interfaces` with the same
non-interactive `sudo -n` fallback as the per-interface metadata probes and
records only interface/probe metadata in the JSON bundle.

If the evidence artifact reports `wgToolFound=false`, repair only the
self-hosted runner prerequisite first:

```bash
gh workflow run faz24-i3-runner-wg-tool-repair.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f mode=install \
  -f confirm=INSTALL_WIREGUARD_TOOLS_FOR_FAZ24_I3 \
  -f package_manager=auto
```

Boundary: this workflow is a controlled host prerequisite repair for
`staging-sw` only. It may install `wireguard-tools` when the confirmation token
matches. It does not touch Denetim PC config, clusters, direct-STT, app-mTLS, or
production state. If it installed the package, rollback is host package-manager
removal after confirming no other runner job depends on `wg`.

### 5.2 Manual fallback

Run these from an elevated Denetim PC PowerShell session or an approved
operator automation wrapper. Do not paste secrets into the shell.

OpenSSH Operational metadata:

```powershell
$since = (Get-Date).ToUniversalTime().AddHours(-2)
Get-WinEvent -LogName 'OpenSSH/Operational' |
  Where-Object { $_.TimeCreated.ToUniversalTime() -ge $since } |
  Select-Object TimeCreated, Id, ProviderName, MachineName, LevelDisplayName |
  ConvertTo-Json -Depth 4
```

PowerShell transcription metadata:

```powershell
$transcriptRoot = '\\denetim-pc\protected-audit$\PowerShellTranscripts'
Get-ChildItem -Path $transcriptRoot -Recurse -File |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 20 FullName, Length, CreationTimeUtc, LastWriteTimeUtc |
  ConvertTo-Json -Depth 4
```

PowerShell script-block metadata without command content:

```powershell
Get-WinEvent -LogName 'Microsoft-Windows-PowerShell/Operational' |
  Where-Object { $_.Id -in 4103,4104 -and $_.TimeCreated.ToUniversalTime() -ge $since } |
  Select-Object TimeCreated, Id, ProviderName, MachineName, LevelDisplayName |
  ConvertTo-Json -Depth 4
```

Failed-login summary:

```powershell
Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625; StartTime=(Get-Date).AddHours(-2)} |
  Group-Object ProviderName |
  Select-Object Name, Count |
  ConvertTo-Json -Depth 4
```

Firewall/WFP/ESET drift metadata:

```powershell
Get-NetFirewallRule |
  Where-Object { $_.DisplayName -match 'WireGuard|OpenSSH|Caddy|8243|8200' } |
  Select-Object DisplayName, Enabled, Direction, Action, Profile |
  ConvertTo-Json -Depth 4
```

Time sync:

```powershell
w32tm /query /status
w32tm /stripchart /computer:time.windows.com /samples:5 /dataonly
```

WireGuard health:

```powershell
# Do not copy full raw output into the JSON evidence. Derive metadata:
# interface, latest-handshake age, endpoint class, rx/tx byte deltas.
wg show | Select-String 'interface:|endpoint:|latest handshake:|transfer:'
```

On `staging-sw`, capture only connection metadata:

```bash
sudo journalctl -u ssh --since "2 hours ago" --no-pager |
  rg 'svc-denetim-agent|10\.99\.0\.2|Accepted|Failed' || true
# Avoid attaching raw wg output. Keep derived metadata only; shorten peer ids.
sudo wg show wg0 latest-handshakes | awk '{print "peer_prefix=" substr($1,1,12) " latest_handshake=" $2}'
sudo wg show wg0 transfer | awk '{print "peer_prefix=" substr($1,1,12) " rx_bytes=" $2 " tx_bytes=" $3}'
sudo wg show wg0 endpoints | awk '{print "peer_prefix=" substr($1,1,12) " endpoint=" $2}'
ss -Htn state established '( sport = :22 or dport = :22 )' || true
```

## 6. Verification

Validate the final metadata JSON before attaching or referencing it:

```bash
python3 scripts/faz24/verify-wg-bplus-i3-evidence.py \
  docs/faz-24-evidence/<date>-wg-bplus-i3-management-audit.json
```

Expected output shape:

```text
Faz24 WG-B+ I3 evidence: PASS
- openssh-event-log: who=... when=... what=...
- powershell-transcription: who=... when=... what=...
```

Any finding from the verifier means the bundle is not acceptable for #1864.

## 7. Follow-up Status

After verifier PASS:

1. Attach or reference the protected evidence path in `platform-k8s-gitops#1864`.
2. Add an `EVIDENCE` comment with verifier output and the no-leak boundary.
3. Move the issue to `Needs Verify` only if no I3 drift remains.
4. Do not mark I7/#198, #188, or #182 based on this management-plane evidence.
