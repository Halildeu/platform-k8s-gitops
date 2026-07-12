#!/usr/bin/env python3
"""Build a Denetim-side SSH public-key authorization package for Faz 24 I3.

The package is public-key-only. It never accepts, stores, or emits private key
material. The generated PowerShell script is intended for an elevated Denetim
PC operator session and writes metadata-only evidence after idempotently
authorizing the runner public key for the target local account.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "faz24.i3.denetim.ssh-authorize-package.v1"
DEFAULT_TARGET_USER = "svc-denetim-agent"
DEFAULT_PUBLIC_KEY_NAME = "faz24-i3-denetim_ed25519.pub"
POWERSHELL_NAME = "authorize-denetim-i3-public-key.ps1"
METADATA_NAME = "expected-public-key-metadata.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

PRIVATE_KEY_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "BEGIN DSA PRIVATE KEY",
    "PRIVATE KEY-----",
)

PUBLIC_KEY_RE = re.compile(r"^(ssh-ed25519) ([A-Za-z0-9+/]+={0,3})(?: ([^\r\n]+))?$")


@dataclass(frozen=True)
class PublicKey:
    line: str
    key_type: str
    blob_b64: str
    blob: bytes
    comment: str
    fingerprint: str
    line_sha256: str
    blob_sha256: str


def die(message: str) -> None:
    print(f"ERR {message}", file=sys.stderr)
    raise SystemExit(2)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hex_text(value: str) -> str:
    return sha256_hex_bytes(value.encode("utf-8"))


def openssh_sha256_fingerprint(blob: bytes) -> str:
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def read_public_key(args: argparse.Namespace) -> str:
    values = [bool(args.public_key), bool(args.public_key_file)]
    if sum(values) != 1:
        die("exactly one of --public-key or --public-key-file is required")

    if args.public_key:
        return args.public_key

    path = Path(args.public_key_file)
    if not path.is_file():
        die(f"public key file not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_public_key(raw_value: str) -> PublicKey:
    if any(marker in raw_value for marker in PRIVATE_KEY_MARKERS):
        die("private key material is not accepted")

    non_empty_lines = [line.strip() for line in raw_value.splitlines() if line.strip()]
    if len(non_empty_lines) != 1:
        die("public key must be exactly one non-empty line")

    line = non_empty_lines[0]
    if len(line) > 1200:
        die("public key line is unexpectedly long")
    if any(marker in line for marker in PRIVATE_KEY_MARKERS):
        die("private key material is not accepted")

    match = PUBLIC_KEY_RE.match(line)
    if not match:
        die("public key must be an ssh-ed25519 public key line")

    key_type, blob_b64, comment = match.group(1), match.group(2), match.group(3) or ""
    try:
        blob = base64.b64decode(blob_b64.encode("ascii"), validate=True)
    except Exception as exc:  # pragma: no cover - exact exception differs by Python version
        die(f"public key blob is not valid base64: {exc}")

    if len(blob) < 51:
        die("ssh-ed25519 public key blob is too short")

    normalized = f"{key_type} {blob_b64}"
    if comment:
        normalized = f"{normalized} {comment}"

    return PublicKey(
        line=normalized,
        key_type=key_type,
        blob_b64=blob_b64,
        blob=blob,
        comment=comment,
        fingerprint=openssh_sha256_fingerprint(blob),
        line_sha256=sha256_hex_text(normalized),
        blob_sha256=sha256_hex_bytes(blob),
    )


def ps_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_powershell(public_key: PublicKey, target_user: str) -> str:
    return f"""#requires -Version 5.1
[CmdletBinding()]
param(
  [string]$TargetUser = {ps_single_quoted(target_user)},
  [string]$PublicKeyFile = (Join-Path $PSScriptRoot {ps_single_quoted(DEFAULT_PUBLIC_KEY_NAME)}),
  [string]$EvidencePath = (Join-Path $PSScriptRoot 'denetim-i3-ssh-authorize-evidence.json'),
  [switch]$CreateTargetUser,
  [switch]$GrantEventLogReaders,
  [switch]$RestartSshd
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SchemaVersion = {ps_single_quoted(SCHEMA_VERSION + ".evidence")}
$ExpectedPublicKeyLineSha256 = {ps_single_quoted(public_key.line_sha256)}
$ExpectedPublicKeyBlobSha256 = {ps_single_quoted(public_key.blob_sha256)}
$ExpectedPublicKeyFingerprint = {ps_single_quoted(public_key.fingerprint)}
$PrivateKeyIncluded = $false

function Get-UtcNow {{
  return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}}

function Get-Sha256HexForText {{
  param([Parameter(Mandatory=$true)][string]$Value)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {{
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    return -join ($sha.ComputeHash($bytes) | ForEach-Object {{ $_.ToString('x2') }})
  }} finally {{
    $sha.Dispose()
  }}
}}

function Get-Sha256HexForBytes {{
  param([Parameter(Mandatory=$true)][byte[]]$Bytes)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {{
    return -join ($sha.ComputeHash($Bytes) | ForEach-Object {{ $_.ToString('x2') }})
  }} finally {{
    $sha.Dispose()
  }}
}}

function Get-Sha256ShortForText {{
  param([Parameter(Mandatory=$true)][string]$Value)
  return (Get-Sha256HexForText -Value $Value).Substring(0, 16)
}}

function Get-OpenSshFingerprint {{
  param([Parameter(Mandatory=$true)][byte[]]$Blob)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {{
    $digest = $sha.ComputeHash($Blob)
    return 'SHA256:' + [Convert]::ToBase64String($digest).TrimEnd('=')
  }} finally {{
    $sha.Dispose()
  }}
}}

function Get-PublicKeyInfo {{
  param([Parameter(Mandatory=$true)][string]$Line)

  if ($Line -match 'BEGIN .*PRIVATE KEY|PRIVATE KEY-----') {{
    throw 'private key material is not accepted'
  }}
  if ($Line -match '[\\r\\n]') {{
    throw 'public key must be a single line'
  }}

  $trimmed = $Line.Trim()
  $parts = $trimmed -split '\\s+', 3
  if ($parts.Count -lt 2 -or $parts[0] -ne 'ssh-ed25519') {{
    throw 'public key must be an ssh-ed25519 public key line'
  }}

  $blob = [Convert]::FromBase64String($parts[1])
  if ($blob.Length -lt 51) {{
    throw 'ssh-ed25519 public key blob is too short'
  }}

  $comment = ''
  if ($parts.Count -eq 3) {{
    $comment = $parts[2]
  }}
  $normalized = "$($parts[0]) $($parts[1])"
  if ($comment) {{
    $normalized = "$normalized $comment"
  }}

  return [ordered]@{{
    keyType = $parts[0]
    blobBase64 = $parts[1]
    comment = $comment
    normalizedLine = $normalized
    blobSha256 = Get-Sha256HexForBytes -Bytes $blob
    lineSha256 = Get-Sha256HexForText -Value $normalized
    fingerprint = Get-OpenSshFingerprint -Blob $blob
  }}
}}

function Test-IsAdministrator {{
  $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
  return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}}

function New-RandomSecurePassword {{
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {{
    $rng.GetBytes($bytes)
  }} finally {{
    $rng.Dispose()
  }}
  $password = ([Convert]::ToBase64String($bytes) + '!aA1')
  return ConvertTo-SecureString -String $password -AsPlainText -Force
}}

function Get-LocalAccountSid {{
  param([Parameter(Mandatory=$true)][string]$UserName)

  $account = New-Object System.Security.Principal.NTAccount($env:COMPUTERNAME, $UserName)
  return $account.Translate([System.Security.Principal.SecurityIdentifier]).Value
}}

function Ensure-TargetUser {{
  param(
    [Parameter(Mandatory=$true)][string]$UserName,
    [Parameter(Mandatory=$true)][bool]$CreateIfMissing
  )

  $user = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
  $created = $false
  if ($null -eq $user) {{
    if (-not $CreateIfMissing) {{
      throw "target-user-not-found:$UserName"
    }}
    $securePassword = New-RandomSecurePassword
    New-LocalUser `
      -Name $UserName `
      -Password $securePassword `
      -AccountNeverExpires `
      -PasswordNeverExpires `
      -UserMayNotChangePassword `
      -Description 'Faz 24 I3 metadata-only SSH audit account' `
      -ErrorAction Stop | Out-Null
    $created = $true
    $user = Get-LocalUser -Name $UserName -ErrorAction Stop
  }}

  if (-not $user.Enabled) {{
    throw "target-user-disabled:$UserName"
  }}

  return [ordered]@{{
    created = $created
    existed = (-not $created)
    enabled = [bool]$user.Enabled
    sid = Get-LocalAccountSid -UserName $UserName
  }}
}}

function Ensure-EventLogReadersMembership {{
  param(
    [Parameter(Mandatory=$true)][string]$UserName,
    [Parameter(Mandatory=$true)][bool]$GrantMembership
  )

  if (-not $GrantMembership) {{
    return [ordered]@{{ attempted = $false; present = $false }}
  }}

  $targetSid = Get-LocalAccountSid -UserName $UserName
  $groupSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-573')
  $group = Get-LocalGroup -SID $groupSid.Value -ErrorAction Stop
  $groupName = $group.Name
  $memberAccount = "$env:COMPUTERNAME\\$UserName"
  $members = @(Get-LocalGroupMember -Group $groupName -ErrorAction Stop)
  $present = (@($members | Where-Object {{ $_.SID.Value -eq $targetSid }}).Count -gt 0)

  if (-not $present) {{
    Add-LocalGroupMember -Group $groupName -Member $memberAccount -ErrorAction Stop
    $members = @(Get-LocalGroupMember -Group $groupName -ErrorAction Stop)
    $present = (@($members | Where-Object {{ $_.SID.Value -eq $targetSid }}).Count -gt 0)
  }}

  return [ordered]@{{ attempted = $true; present = [bool]$present }}
}}

function Resolve-LocalProfilePath {{
  param(
    [Parameter(Mandatory=$true)][string]$UserName,
    [Parameter(Mandatory=$true)][bool]$AllowFallback
  )

  $null = Get-LocalUser -Name $UserName -ErrorAction Stop
  $sid = Get-LocalAccountSid -UserName $UserName
  $profileKey = "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\$sid"
  $registryPresent = Test-Path -LiteralPath $profileKey
  $profileCreated = $false
  $profileFallbackUsed = $false

  if (-not $registryPresent) {{
    if (-not $AllowFallback) {{
      throw "profile-not-found:$UserName"
    }}
    $profilePath = Join-Path $env:SystemDrive "Users\\$UserName"
    $profileFallbackUsed = $true
  }} else {{
    $profilePath = (Get-ItemProperty -LiteralPath $profileKey).ProfileImagePath
  }}

  if ([string]::IsNullOrWhiteSpace($profilePath)) {{
    throw "profile-path-not-found:$UserName"
  }}
  if (-not (Test-Path -LiteralPath $profilePath)) {{
    if (-not $AllowFallback) {{
      throw "profile-path-not-found:$UserName"
    }}
    New-Item -ItemType Directory -Path $profilePath -Force | Out-Null
    $profileCreated = $true
  }}

  return [ordered]@{{
    sid = $sid
    profilePath = $profilePath
    registryPresent = [bool]$registryPresent
    profileCreated = [bool]$profileCreated
    profileFallbackUsed = [bool]$profileFallbackUsed
  }}
}}

function Set-StrictFileAcl {{
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$UserName,
    [Parameter(Mandatory=$true)][bool]$Directory
  )

  $acl = Get-Acl -LiteralPath $Path
  $owner = New-Object System.Security.Principal.NTAccount($env:COMPUTERNAME, $UserName)
  $acl.SetOwner($owner)
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($rule in @($acl.Access)) {{
    [void]$acl.RemoveAccessRuleSpecific($rule)
  }}

  $adminRights = [System.Security.AccessControl.FileSystemRights]::Read
  if ($Directory) {{
    $adminRights = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
  }}

  $accessRules = @(
    @{{
      identity = "$env:COMPUTERNAME\\$UserName"
      rights = [System.Security.AccessControl.FileSystemRights]::FullControl
    }},
    @{{
      identity = 'NT AUTHORITY\\SYSTEM'
      rights = [System.Security.AccessControl.FileSystemRights]::FullControl
    }},
    @{{
      identity = 'BUILTIN\\Administrators'
      rights = $adminRights
    }}
  )

  $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
  if ($Directory) {{
    $inheritance = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
  }}

  foreach ($accessRule in $accessRules) {{
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
      $accessRule.identity,
      $accessRule.rights,
      $inheritance,
      [System.Security.AccessControl.PropagationFlags]::None,
      [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
  }}

  Set-Acl -LiteralPath $Path -AclObject $acl
}}

function Write-Evidence {{
  param(
    [Parameter(Mandatory=$true)][string]$Status,
    [Parameter(Mandatory=$true)][string]$Reason,
    [hashtable]$Extra = @{{}}
  )

  $parent = Split-Path -Parent $EvidencePath
  if ($parent -and -not (Test-Path -LiteralPath $parent)) {{
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }}

  $body = [ordered]@{{
    schemaVersion = $SchemaVersion
    collectedAt = Get-UtcNow
    status = $Status
    reason = $Reason
    targetUser = $TargetUser
    expectedPublicKeyFingerprint = $ExpectedPublicKeyFingerprint
    expectedPublicKeyLineSha256 = $ExpectedPublicKeyLineSha256
    expectedPublicKeyBlobSha256 = $ExpectedPublicKeyBlobSha256
    privateKeyIncluded = $PrivateKeyIncluded
    rawPublicKeyIncluded = $false
  }}

  foreach ($key in $Extra.Keys) {{
    $body[$key] = $Extra[$key]
  }}

  $json = $body | ConvertTo-Json -Depth 8
  [IO.File]::WriteAllText(
    $EvidencePath,
    $json + [Environment]::NewLine,
    (New-Object Text.UTF8Encoding($false))
  )
}}

try {{
  $publicKeyLine = (Get-Content -LiteralPath $PublicKeyFile -Raw -ErrorAction Stop).Trim()
  $publicKeyInfo = Get-PublicKeyInfo -Line $publicKeyLine

  if ($publicKeyInfo.lineSha256 -ne $ExpectedPublicKeyLineSha256) {{
    throw 'public-key-line-sha256-mismatch'
  }}
  if ($publicKeyInfo.blobSha256 -ne $ExpectedPublicKeyBlobSha256) {{
    throw 'public-key-blob-sha256-mismatch'
  }}
  if ($publicKeyInfo.fingerprint -ne $ExpectedPublicKeyFingerprint) {{
    throw 'public-key-fingerprint-mismatch'
  }}

  if (-not (Test-IsAdministrator)) {{
    Write-Evidence -Status 'blocked' -Reason 'administrator-required' -Extra @{{
      publicKeyFingerprint = $publicKeyInfo.fingerprint
      publicKeyLineSha256 = $publicKeyInfo.lineSha256
    }}
    Write-Error 'administrator-required'
    exit 2
  }}

  $targetUserState = Ensure-TargetUser -UserName $TargetUser -CreateIfMissing ([bool]$CreateTargetUser)
  $eventLogReaders = Ensure-EventLogReadersMembership -UserName $TargetUser -GrantMembership ([bool]$GrantEventLogReaders)
  $profile = Resolve-LocalProfilePath -UserName $TargetUser -AllowFallback ([bool]$CreateTargetUser)
  $sshDir = Join-Path $profile.profilePath '.ssh'
  $authorizedKeys = Join-Path $sshDir 'authorized_keys'

  New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
  if (-not (Test-Path -LiteralPath $authorizedKeys)) {{
    New-Item -ItemType File -Path $authorizedKeys -Force | Out-Null
  }}

  $existingLines = @(Get-Content -LiteralPath $authorizedKeys -ErrorAction Stop | Where-Object {{ $_.Trim() }})
  $alreadyPresent = $false
  foreach ($line in $existingLines) {{
    try {{
      $existingInfo = Get-PublicKeyInfo -Line $line
      if ($existingInfo.blobSha256 -eq $publicKeyInfo.blobSha256) {{
        $alreadyPresent = $true
      }}
    }} catch {{
      # Ignore non-OpenSSH or malformed historical lines; do not rewrite them.
    }}
  }}

  $keyAdded = $false
  if (-not $alreadyPresent) {{
    Add-Content -LiteralPath $authorizedKeys -Value $publicKeyInfo.normalizedLine -Encoding ascii
    $keyAdded = $true
  }}

  Set-StrictFileAcl -Path $sshDir -UserName $TargetUser -Directory $true
  Set-StrictFileAcl -Path $authorizedKeys -UserName $TargetUser -Directory $false

  $sshd = Get-Service -Name sshd -ErrorAction SilentlyContinue
  $restartAttempted = $false
  $sshdStatusBefore = if ($sshd) {{ $sshd.Status.ToString() }} else {{ 'not-found' }}
  if ($RestartSshd -and $sshd) {{
    $restartAttempted = $true
    Restart-Service -Name sshd -Force -ErrorAction Stop
    $sshd = Get-Service -Name sshd -ErrorAction SilentlyContinue
  }}
  $sshdStatusAfter = if ($sshd) {{ $sshd.Status.ToString() }} else {{ 'not-found' }}

  $evidenceExtra = @{{
    publicKeyFingerprint = $publicKeyInfo.fingerprint
    publicKeyLineSha256 = $publicKeyInfo.lineSha256
    publicKeyBlobSha256 = $publicKeyInfo.blobSha256
    targetUserSidHash = Get-Sha256ShortForText -Value $profile.sid
    targetUserCreated = [bool]$targetUserState.created
    targetUserExisted = [bool]$targetUserState.existed
    targetUserEnabled = [bool]$targetUserState.enabled
    eventLogReadersGrantAttempted = [bool]$eventLogReaders.attempted
    eventLogReadersMembershipPresent = [bool]$eventLogReaders.present
    profileRegistryPresent = [bool]$profile.registryPresent
    profileCreated = [bool]$profile.profileCreated
    profileFallbackUsed = [bool]$profile.profileFallbackUsed
    profilePathHash = Get-Sha256ShortForText -Value $profile.profilePath
    authorizedKeysPathHash = Get-Sha256ShortForText -Value $authorizedKeys
    keyAdded = $keyAdded
    keyAlreadyPresent = $alreadyPresent
    aclHardened = $true
    sshdServiceStatusBefore = $sshdStatusBefore
    sshdServiceStatusAfter = $sshdStatusAfter
    sshdRestartAttempted = $restartAttempted
  }}

  if ($sshdStatusAfter -ne 'Running') {{
    Write-Evidence -Status 'blocked' -Reason 'sshd-not-running' -Extra $evidenceExtra
    Write-Error "sshd-not-running:$sshdStatusAfter"
    exit 1
  }}

  $reason = if ($keyAdded) {{ 'authorized-key-added' }} else {{ 'authorized-key-present' }}
  Write-Evidence -Status 'pass' -Reason $reason -Extra $evidenceExtra

  Write-Host "FAZ24_I3_DENETIM_SSH_AUTHORIZE status=pass reason=$reason fingerprint=$($publicKeyInfo.fingerprint)"
  exit 0
}} catch {{
  Write-Evidence -Status 'blocked' -Reason $_.Exception.Message -Extra @{{
    evidencePathHash = Get-Sha256ShortForText -Value $EvidencePath
  }}
  Write-Error $_.Exception.Message
  exit 1
}}
"""


def render_readme(public_key: PublicKey, target_user: str, source_identity_run_id: str) -> str:
    source = source_identity_run_id or "not-recorded"
    return f"""# Faz 24 I3 Denetim SSH authorization package

Scope: `platform-k8s-gitops#1864` / Faz 24 WG-B+ I3.

This package authorizes the runner public key for the Denetim PC local account
`{target_user}`. It contains public verifier material only. It does not contain
an SSH private key, bearer token, JWT, cookie, password, audio, transcript, or
raw command output.

Expected public key:

- identity workflow run: `{source}`
- fingerprint: `{public_key.fingerprint}`
- line SHA256: `{public_key.line_sha256}`
- key comment: `{public_key.comment or "none"}`

Run from an elevated Denetim PC PowerShell session:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\{POWERSHELL_NAME} -TargetUser {target_user}
```

Extract the artifact to a local Denetim PC directory before running the script.
Do not execute it from a network share. The script sets the final `.ssh` and
`authorized_keys` ACLs itself, so archive ownership metadata is not used as
authorization evidence.

If the dedicated local account is missing, use the explicit bootstrap mode:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\{POWERSHELL_NAME} -TargetUser {target_user} -CreateTargetUser -GrantEventLogReaders
```

This creates `{target_user}` with a random non-exported password, keeps it
non-admin, grants Event Log Readers for audit metadata collection, prepares the
local profile `.ssh` directory when Windows has not created one yet, and records
only hashes/boolean state in the evidence file. The generated password is not
printed, written to the evidence JSON, or included in this package.

The script is idempotent. It resolves the local user's profile, appends the
public key only when the key material is absent, hardens `.ssh` and
`authorized_keys` ACLs to the target user and SYSTEM with FullControl plus
Administrators read-only access, and writes
`denetim-i3-ssh-authorize-evidence.json`. When bootstrap mode is not used, a
missing target user remains a fail-closed condition.

Optional sshd restart, only if the operator explicitly chooses it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\{POWERSHELL_NAME} -TargetUser {target_user} -RestartSshd
```

After a `status=pass` evidence file is produced, rerun
`faz24-wg-bplus-i3-evidence.yml`. This package does not make #1864 acceptable by
itself; the I3 evidence verifier must pass all required checks.
"""


def write_text(path: Path, content: str, mode: int | None = None) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    if mode is not None:
        path.chmod(mode)


def write_sha256sums(output_dir: Path, files: list[Path]) -> None:
    lines = []
    for path in files:
        digest = sha256_hex_bytes(path.read_bytes())
        lines.append(f"{digest}  {path.name}")
    write_text(output_dir / SHA256SUMS_NAME, "\n".join(lines) + "\n")


def build_package(args: argparse.Namespace) -> dict:
    public_key = parse_public_key(read_public_key(args))
    target_user = args.target_user or DEFAULT_TARGET_USER
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    public_key_path = output_dir / DEFAULT_PUBLIC_KEY_NAME
    powershell_path = output_dir / POWERSHELL_NAME
    metadata_path = output_dir / METADATA_NAME
    readme_path = output_dir / README_NAME

    metadata = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "targetUser": target_user,
        "sourceIdentityRunId": args.source_identity_run_id or "",
        "publicKeyFile": DEFAULT_PUBLIC_KEY_NAME,
        "publicKeyType": public_key.key_type,
        "publicKeyComment": public_key.comment,
        "publicKeyFingerprint": public_key.fingerprint,
        "publicKeyLineSha256": public_key.line_sha256,
        "publicKeyBlobSha256": public_key.blob_sha256,
        "publicKeyLength": len(public_key.line),
        "privateKeyIncluded": False,
        "rawPublicKeyIncludedInMetadata": False,
        "supportsTargetUserBootstrap": True,
        "recommendedMissingUserFlags": ["CreateTargetUser", "GrantEventLogReaders"],
        "operatorScript": POWERSHELL_NAME,
        "operatorEvidenceFile": "denetim-i3-ssh-authorize-evidence.json",
        "nextVerification": "rerun faz24-wg-bplus-i3-evidence.yml after Denetim authorization",
    }

    write_text(public_key_path, public_key.line + "\n", stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    write_text(powershell_path, render_powershell(public_key, target_user), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    write_text(metadata_path, json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_text(readme_path, render_readme(public_key, target_user, args.source_identity_run_id or ""))
    write_sha256sums(output_dir, [public_key_path, powershell_path, metadata_path, readme_path])

    return metadata


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--public-key", help="single-line ssh-ed25519 public key")
    group.add_argument("--public-key-file", help="path to single-line ssh-ed25519 public key")
    parser.add_argument("--output-dir", required=True, help="directory for the package files")
    parser.add_argument("--target-user", default=DEFAULT_TARGET_USER, help="Denetim local user to authorize")
    parser.add_argument("--source-identity-run-id", default="", help="runner SSH identity workflow run id")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    metadata = build_package(args)
    print(
        "FAZ24_I3_DENETIM_SSH_AUTHORIZE_PACKAGE "
        f"status=pass target_user={metadata['targetUser']} "
        f"fingerprint={metadata['publicKeyFingerprint']} "
        f"output_dir={os.fspath(Path(args.output_dir))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
