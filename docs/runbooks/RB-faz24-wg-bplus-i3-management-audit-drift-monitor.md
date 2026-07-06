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

### 5.0 Operator Handoff Coordination Package

When #1864 I3 and #1867 I6 are being handed to an operator together, build the
metadata-only coordination artifact first:

```bash
gh workflow run faz24-wg-bplus-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main
```

The uploaded artifact is `faz24-wg-bplus-operator-handoff-<run_id>`. It
contains only `README.md`, `faz24-wg-bplus-operator-handoff.json`, and
`SHA256SUMS`. It does not connect to Denetim PC or `staging-sw`, does not
collect live evidence, and does not change host, cluster, WireGuard,
platform-ai, secret, or production state.

Use the handoff artifact to keep the exact I3 package run id, public-key
fingerprint/hash values, I3 ingest command, I3 evidence rerun command, and I6
operator package command together. The handoff artifact is not acceptance
evidence; #1864 still requires Denetim operator execution, Denetim authorize
evidence ingest PASS, I3 evidence verifier PASS, and reviewer acceptance.

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

When Denetim SSH exits non-zero, read `collector.denetimSshPreflight` before
changing any host config. This field is metadata-only and may include:

- `routeQueryable` / `routeExitCode` for the runner route probe,
- `tcp22Reachable` / `tcp22ErrorClass` for TCP 22 reachability,
- `sshExitCode` / `sshFailureClass` for the real metadata-collector SSH
  attempt,
- `sshErrorFingerprint` for correlating repeated failures without exporting
  raw SSH stderr.

The preflight metadata does not make I3 acceptable by itself. It only narrows
the next action, for example `ssh-auth-publickey` versus `ssh-timeout` versus
`ssh-hostkey`. The evidence bundle must still pass all eight checks before
`platform-k8s-gitops#1864` can move forward.

If the preflight reports `sshFailureClass=ssh-auth-publickey`, first ensure the
self-hosted runner has the deterministic Faz 24 I3 SSH identity available:

```bash
gh workflow run faz24-i3-runner-ssh-identity.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f mode=create \
  -f confirm=CREATE_FAZ24_I3_DENETIM_SSH_IDENTITY
```

The uploaded artifact is `faz24-i3-runner-ssh-identity-<run_id>`. It contains
`ssh-identity.json` and a copy of the public key only. The private key remains
runner-local and must not be copied into issue comments, artifacts, Mavis,
email, or chat. The Denetim PC must still authorize the uploaded public key
for `svc-denetim-agent`; the workflow does not change Denetim PC, clusters,
direct-STT, app-mTLS, or production state.

Build the Denetim-side public-key authorization package from that identity
artifact:

```bash
gh workflow run faz24-i3-denetim-ssh-authorize-package.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f identity_run_id=<faz24-i3-runner-ssh-identity-run-id> \
  -f target_user=svc-denetim-agent
```

The uploaded artifact is
`faz24-i3-denetim-ssh-authorize-package-<run_id>`. It contains only:

- `authorize-denetim-i3-public-key.ps1`
- `faz24-i3-denetim_ed25519.pub`
- `expected-public-key-metadata.json`
- `README.md`
- `SHA256SUMS`

Boundary: the package workflow does not connect to Denetim PC and does not
change Denetim host config. It is public-key-only and rejects private key
material. A Denetim operator must copy the package to the Denetim PC, extract
it to a local directory, and run the PowerShell script from an elevated session:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\authorize-denetim-i3-public-key.ps1 `
  -TargetUser svc-denetim-agent
```

If the package reports `target-user-not-found:svc-denetim-agent`, rerun from
the same elevated local Denetim directory with the explicit bootstrap flags:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\authorize-denetim-i3-public-key.ps1 `
  -TargetUser svc-denetim-agent `
  -CreateTargetUser `
  -GrantEventLogReaders
```

Bootstrap mode creates the dedicated local account with a random non-exported
password, keeps it non-admin, grants Event Log Readers for metadata collection,
prepares the `.ssh` directory when Windows has not created the profile yet, and
records only hashes/boolean state in `denetim-i3-ssh-authorize-evidence.json`.
Without `-CreateTargetUser`, a missing target user remains a fail-closed
condition.

Do not run it from a network share. The script is idempotent: it validates the
public key fingerprint and SHA256, resolves the local `svc-denetim-agent`
profile, appends the key only when the key material is absent, sets the file
owner to the target user, hardens `.ssh` and `authorized_keys` ACLs to the
target user and SYSTEM with FullControl plus Administrators read-only access,
requires `sshd` service status to be `Running`, and writes
`denetim-i3-ssh-authorize-evidence.json`. This evidence file is not acceptance
by itself; it is the Denetim-side authorization proof needed before the I3
collector can reach the endpoint.

Before rerunning the I3 evidence workflow, ingest the Denetim-side metadata
evidence through the verifier workflow. The JSON is metadata-only and must not
contain a raw public key, private key, bearer token, command content, or raw
Windows profile path.

From the elevated Denetim PowerShell session:

```powershell
$EvidenceB64 = [Convert]::ToBase64String(
  [IO.File]::ReadAllBytes((Resolve-Path .\denetim-i3-ssh-authorize-evidence.json))
)
$EvidenceB64
```

Dispatch the ingest workflow with that single-line value:

```bash
gh workflow run faz24-i3-denetim-ssh-authorize-evidence-ingest.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f evidence_json_base64='<single-line-base64-from-denetim>' \
  -f expected_target_user=svc-denetim-agent \
  -f expected_public_key_fingerprint='SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y' \
  -f expected_public_key_line_sha256='83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff' \
  -f expected_public_key_blob_sha256='e2158a715d03df2ad17d6e2cae3d264096fedbdec9f919d2d07ba84740fab756'
```

The uploaded artifact is
`faz24-i3-denetim-ssh-authorize-evidence-<run_id>`. It contains the normalized
metadata evidence, verifier stdout/stderr, and `verification-summary.json`.
Boundary: a passing ingest only proves the Denetim-side authorization evidence
is structurally acceptable. It does not make #1864 acceptable by itself and it
does not replace the I3 evidence verifier.

After Denetim authorization, rerun `faz24-wg-bplus-i3-evidence.yml`. The
workflow passes the same runner-workspace identity path to the collector and
records only path hash plus public-key fingerprint metadata under
`collector.denetimSshPreflight`. Manual collector runs still default to
`~/.ssh/faz24-i3-denetim_ed25519` unless `--ssh-identity-path` is set.

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
