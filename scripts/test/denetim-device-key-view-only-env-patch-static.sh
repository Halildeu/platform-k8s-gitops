#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1"

[[ -f "$script" ]] || { echo "missing $script" >&2; exit 1; }

require() {
  local needle="$1"
  local message="$2"
  if ! grep -Fq -- "$needle" "$script"; then
    echo "$message" >&2
    exit 1
  fi
}

# PowerShell source assertions are intentionally literal shell strings.
# shellcheck disable=SC2016
{
  require 'SupportsShouldProcess = $true' "activation patch must support WhatIf/ShouldProcess"
  require '#requires -RunAsAdministrator' "activation patch must require an Administrator shell"
  require '[StringComparison]::OrdinalIgnoreCase' "activation patch must compare Windows identities case-insensitively"
  require 'Get-FileHash -LiteralPath $BinaryPath -Algorithm SHA256' "activation patch must pin the installed binary"
  require 'service ImagePath is not bound to the approved binary path' "activation patch must bind the service to the approved binary path"
  require '$deviceCert.Issuer -ne $ExpectedDeviceCertIssuer' "activation patch must pin the TPM certificate issuer"
  require 'TPM device certificate subject is not bound to the expected hostname' "activation patch must bind the certificate to the endpoint identity"
  require '$deviceCert.NotAfter.ToUniversalTime() -le $nowUtc' "activation patch must reject expired TPM certificates"
  require 'Get-Tpm -ErrorAction Stop' "activation patch must inspect real TPM readiness"
  require '-not $tpm.TpmPresent -or -not $tpm.TpmReady' "activation patch must fail closed on absent/unready TPM"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED' "activation patch must enable the TPM device-key session"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED' "activation patch must explicitly enable VIEW_ONLY"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED' "activation patch must require attended consent"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT' "activation patch must explicitly disable plaintext"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64' "activation patch must require the permit trust anchor"
  require 'ExpectedPermitPublicKeyB64Sha256' "activation patch must pin the permit trust anchor digest"
  require 'ExpectedPermitKeyId' "activation patch must pin the permit key ID"
  require 'ENDPOINT_AGENT_SELF_UPDATE_ENABLED' "activation patch must preserve the product self-update lane"
  require 'icacls.exe $backupDir /inheritance:r' "activation patch must restrict rollback evidence ACLs"
  require 'reg.exe export' "activation patch must create a local registry rollback export"
  require 'reg.exe import' "activation patch must apply compensating rollback on failure"
  require 'Restart-ServiceAndWait' "activation patch must wait for the service after activation and rollback"
  require 'Assert-MapsEqual -Expected $current -Actual $restored' "activation patch must verify the restored service configuration"
  require 'rawServiceEnvironmentIncluded = $false' "activation evidence must not emit raw service environment values"
  require 'privateKeyBindingVerifiedByThisScript = $false' "activation evidence must not overclaim TPM private-key binding"
  require 'broker device-key challenge acceptance' "activation evidence must not overclaim broker acceptance"
  require 'KVKK or legal approval' "activation evidence must not overclaim legal acceptance"
}

if grep -Fq "Get-Content -LiteralPath \$summaryPath" "$script"; then
  echo "activation patch must not emit the full evidence summary to stdout" >&2
  exit 1
fi

if grep -Eiq '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|bearer[[:space:]]+[A-Za-z0-9._-]{20,}|password[[:space:]]*=)' "$script"; then
  echo "activation patch appears to contain a credential or private key" >&2
  exit 1
fi

if command -v pwsh >/dev/null 2>&1; then
  # PowerShell source passed to pwsh must not be expanded by Bash.
  # shellcheck disable=SC2016
  pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    if ($errors.Count -gt 0) {
      $errors | ForEach-Object { Write-Error $_.Message }
      exit 1
    }
  '
fi

echo "denetim device-key VIEW_ONLY activation static guard passed"
