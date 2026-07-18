#!/usr/bin/env bash
set -euo pipefail

script="scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1"
orchestrator="scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh"
workflow=".github/workflows/faz22-6-view-only-viewer-browser-evidence.yml"
policy="config/faz22-6-endpoint-agent-release-policy.v1.json"

[[ -f "$script" ]] || { echo "missing $script" >&2; exit 1; }
[[ -f "$orchestrator" ]] || { echo "missing $orchestrator" >&2; exit 1; }
[[ -f "$workflow" ]] || { echo "missing $workflow" >&2; exit 1; }
[[ -f "$policy" ]] || { echo "missing $policy" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 1; }
command -v pwsh >/dev/null 2>&1 || {
  echo "PowerShell is required for the activation behavior guard" >&2
  exit 1
}

require() {
  local needle="$1"
  local message="$2"
  if ! grep -Fq -- "$needle" "$script"; then
    echo "$message" >&2
    exit 1
  fi
}

if grep -Fq -- "-notmatch '^[a-f0-9]{64}$'" "$script" \
  || grep -Fq -- "-notmatch '^[A-Z0-9_]+$'" "$script"; then
  echo "canonical digest/key validators must not use culture-sensitive case-insensitive matching" >&2
  exit 1
fi
[[ "$(grep -Fc -- "-cnotmatch '^[a-f0-9]{64}$'" "$script")" -eq 11 ]] || {
  echo "all canonical digest validators must remain case-sensitive and culture-independent" >&2
  exit 1
}
[[ "$(grep -Fc -- "-cnotmatch '^[A-Z0-9_]+$'" "$script")" -eq 1 ]] || {
  echo "managed environment key validator must remain case-sensitive and culture-independent" >&2
  exit 1
}

# PowerShell source assertions are intentionally literal shell strings.
# shellcheck disable=SC2016
{
  require 'SupportsShouldProcess = $true' "activation patch must support WhatIf/ShouldProcess"
  require '$requestedWhatIf = [bool]$WhatIfPreference' "activation patch must preserve the caller WhatIf request"
  require '$WhatIfPreference = $false' "activation patch must run read-only preflight under WhatIf"
  require '$WhatIfPreference = $requestedWhatIf' "activation patch must restore WhatIf before the mutation boundary"
  require '#requires -RunAsAdministrator' "activation patch must require an Administrator shell"
  require '[StringComparison]::OrdinalIgnoreCase' "activation patch must compare Windows identities case-insensitively"
  require 'Get-FileHash -LiteralPath $BinaryPath -Algorithm SHA256' "activation patch must pin the installed binary"
  require 'ExpectedReleaseManifestSha256' "activation patch must pin the immutable release manifest"
  require '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12' "activation patch must pin TLS 1.2 on Windows PowerShell 5.1"
  require 'Release asset base URL must use HTTPS' "activation patch must require HTTPS release assets"
  require '[string]$ReleaseManifestBaseUrl = ""' "activation patch must not duplicate the canonical release manifest URL"
  require '[string]$ReleaseAssetBaseUrl = ""' "activation patch must not duplicate the canonical internal artifact URL"
  require 'Canonical release policy parameter is required for Action=Apply' "activation patch must fail closed without injected canonical release policy"
  require 'Assert-JsonBooleanProperty -Object $manifest -Name "publicly_trusted" -Expected $false' "activation patch must type-check manifest trust metadata"
  require 'Assert-JsonBooleanProperty -Object $attestationSummary -Name "signature_present" -Expected $true' "activation patch must type-check producer signature metadata"
  require 'remote-bridge-attestation-evidence.b64' "activation patch must fetch signed attestation evidence"
  require 'remote-bridge-attestation-evidence-summary.json' "activation patch must verify attestation producer metadata"
  require 'ExpectedAttestationPublicKeySha256' "activation patch must pin the broker attestation verifier public key"
  require '$attestationFields[0] -ne $ExpectedBinarySha256.ToLowerInvariant()' "activation patch must bind provenance to the installed binary"
  require '$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_ATTESTATION_EVIDENCE_B64"] = $attestationEvidenceB64' "activation patch must install verified provenance evidence"
  require 'EndpointAgent service attestation evidence differs from the verified release asset' "activation patch must read back and verify provenance evidence"
  require 'service ImagePath is not bound to the approved binary path' "activation patch must bind the service to the approved binary path"
  require '$deviceCert.Issuer -ne $ExpectedDeviceCertIssuer' "activation patch must pin the TPM certificate issuer"
  require 'TPM device certificate subject is not bound to the expected hostname' "activation patch must bind the certificate to the endpoint identity"
  require '$deviceCert.NotAfter.ToUniversalTime() -le $nowUtc' "activation patch must reject expired TPM certificates"
  require 'Get-Tpm -ErrorAction Stop' "activation patch must inspect real TPM readiness"
  require '-not $tpm.TpmPresent -or -not $tpm.TpmReady' "activation patch must fail closed on absent/unready TPM"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_DEVICE_KEY_SESSION_ENABLED' "activation patch must enable the TPM device-key session"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ENABLED' "activation patch must explicitly enable VIEW_ONLY"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_ATTENDED_CONSENT_ENABLED' "activation patch must require attended consent"
  require 'Assert-ViewOnlyMaskRectBps -Value $ExpectedViewOnlyMaskRectBps' "activation patch must validate the transaction-bound DLP mask policy"
  require '$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_VIEW_ONLY_MASK_RECT_BPS"] = $ExpectedViewOnlyMaskRectBps' "activation patch must write the transaction-bound DLP mask policy"
  require 'viewOnlyMaskRectBps = $ExpectedViewOnlyMaskRectBps' "activation evidence must record the transaction-bound DLP mask policy"
  require '$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT"] = "false"' "activation patch must disable constrained PTY pilot auto-consent"
  require 'Assert-MapValue -Map $after -Key "ENDPOINT_AGENT_REMOTE_BRIDGE_PILOT_AUTO_CONSENT" -Expected "false"' "activation patch must verify pilot auto-consent stayed disabled"
  require 'constrainedPtyPilotAutoConsentEnabled = $false' "activation evidence must record pilot auto-consent as disabled"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_INSECURE_PLAINTEXT' "activation patch must explicitly disable plaintext"
  require 'ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_BROKER_PUBLIC_KEY_B64' "activation patch must require the permit trust anchor"
  require 'ExpectedPermitPublicKeyB64Sha256' "activation patch must pin the permit trust anchor digest"
  require 'ExpectedPermitKeyId' "activation patch must pin the permit key ID"
  require '$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_PERMIT_KEY_ID"] = $ExpectedPermitKeyId' "activation patch must migrate the service to the device-key broker KID"
  require 'ENDPOINT_AGENT_SELF_UPDATE_ENABLED' "activation patch must preserve the product self-update lane"
  require 'icacls.exe $backupDir /inheritance:r' "activation patch must restrict rollback evidence ACLs"
  require 'Write-ServiceEnvironmentBackup -Map $current -Path $environmentBackup' "activation patch must create a scoped service-environment rollback backup"
  require 'Write-ServiceEnvironmentMap -Path $serviceKey -Map $restorationMap' "explicit rollback must restore only the service Environment value"
  require 'Stop-ServiceAndWait' "activation patch must quiesce the product service before Environment mutation"
  require 'Start-ServiceAndWait' "activation patch must wait for the service after activation and rollback"
  require 'Assert-MapsEqual -Expected $expectedAutomaticRollbackResult -Actual $restored' "activation patch must verify the scoped restored service configuration"
  require 'publishedSummaryContainsRawServiceEnvironment = $false' "published activation evidence must not emit raw service environment values"
  require 'protectedLocalEnvironmentBackupMayContainRawServiceEnvironment = $true' "activation evidence must classify the local environment backup as sensitive"
  require 'preMutationServiceEnvironmentSha256' "activation evidence must bind rollback to the pre-mutation service environment digest"
  require 'environmentBackupSha256' "activation evidence must bind rollback to the exact environment backup bytes"
  require 'managedPreMutationSha256' "rollback must recognize an idempotently restored managed subset"
  require 'managedPostMutationSha256' "rollback must bind the transaction-owned environment subset"
  require 'Transaction lock is owned by another migration before rollback' "explicit rollback must reject a foreign lock before quiescing or mutation"
  require 'Managed service environment differs from the transaction-bound activation patch after restart' "activation must verify the managed subset after restart"
  require 'New-ManagedEnvironmentRestorationMap' "rollback must preserve unrelated product environment settings"
  require 'sensitive rollback material cleanup could not be verified' "pre-mutation failure must verify sensitive temporary material removal"
  require 'ConvertTo-Json -InputObject $rows -Compress' "service environment digest must preserve array shape on Windows PowerShell 5.1"
  require 'status=rollback-restored-service-running' "rollback mode must emit a bounded restored status"
  require 'Resolve-TransactionBoundRollback' "rollback must validate the requested transaction"
  require 'Register-RollbackCleanupTask' "sensitive rollback material must have enforced cleanup"
  require 'Register-ScheduledTask -TaskName $taskName' "rollback cleanup must be registered with Windows Task Scheduler"
  require 'New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3' "rollback cleanup must run after downtime and retry failures"
  require '$retryAtLocal = $deleteAtLocal.AddDays(1)' "daily cleanup retry must not collide with the first retention trigger"
  require 'New-ScheduledTaskTrigger -Daily -At $retryAtLocal' "rollback cleanup must retry daily until verified deletion succeeds"
  require '[ValidateSet("Apply", "Rollback", "ReleaseLock", "Inspect")]' "orchestrator recovery must inspect transaction state under the shared mutex"
  require 'Write-EnvironmentMap `$scopedRestorationMap' "expired live transactions must receive scoped compensating rollback before sensitive evidence deletion"
  require '$patched["ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID"] = $TransactionId' "activation must stamp the owning transaction into the service environment"
  require 'transaction lock ownership changed before automatic rollback' "automatic rollback must remain bound to its exclusive transaction lock"
  require 'environment backup changed after preparation and before automatic rollback restore' "automatic rollback must reverify backup bytes immediately before restore"
  require '$releaseStatus = "transaction-lock-released"' "accepted migration must expose verified transaction lock release"
  require 'Transaction evidence directory already exists; refusing transaction replay' "activation must reject reuse of a transaction evidence directory"
  require 'Transaction ID has already been applied to this endpoint' "activation must reject replay of an accepted transaction ID"
  require 'Global\EndpointAgent-F22-ViewOnly-Migration' "apply, rollback, release, and deadline cleanup must share a cross-process operation mutex"
  require 'transaction lock ownership changed during deadline rollback' "deadline rollback must recheck lock ownership immediately before deletion"
  require 'Current managed service environment differs from the committed activation summary' "lock release must verify the managed subset without rejecting unrelated product updates"
  require '[IO.File]::Replace($tempPath, $Path, $replaceBackupPath, $true)' "existing activation summaries must use atomic same-volume replacement"
  require '`$markerPresent = `$current.Contains(`$markerKey)' "deadline cleanup must distinguish an absent marker from an empty marker value"
  require 'deadline transaction lock deletion could not be verified' "deadline cleanup must verify lock deletion before unregistering recovery"
  require 'EndpointAgent binary changed after preflight and before mutation' "activation must revalidate the binary at the mutation boundary"
  require 'EndpointAgent service ImagePath changed across the activation restart' "activation must revalidate service executable binding after restart"
  require 'TPM device certificate changed across the activation restart' "activation must revalidate device certificate bytes after restart"
  require 'privateKeyBindingVerifiedByThisScript = $false' "activation evidence must not overclaim TPM private-key binding"
  require 'broker device-key challenge acceptance' "activation evidence must not overclaim broker acceptance"
  require 'cryptographic signature verification by this script' "activation evidence must defer signature authority to the broker"
  require 'signatureCryptographicallyVerifiedByThisScript = $false' "activation evidence must not claim local signature verification"
  require 'signatureVerificationAuthority = "broker"' "activation evidence must identify the broker as signature authority"
  require 'KVKK or legal approval' "activation evidence must not overclaim legal acceptance"
  require 'permanent AnyDesk-like product runtime integration' "activation evidence must declare the rollout-adapter boundary"
}

# shellcheck disable=SC2016
lock_create_line="$(grep -nF 'New-Item -ItemType Directory -Path $transactionLockDirectory' "$script" | head -1 | cut -d: -f1)"
# shellcheck disable=SC2016
backup_create_line="$(grep -nF 'New-Item -ItemType Directory -Path $backupDir' "$script" | head -1 | cut -d: -f1)"
# shellcheck disable=SC2016
cleanup_register_line="$(grep -nF '$cleanupTaskInfo = Register-RollbackCleanupTask' "$script" | tail -1 | cut -d: -f1)"
apply_quiesce_line="$(awk '/# Quiescing it closes that writer race/{in_apply=1} in_apply && /Stop-ServiceAndWait -Name \$ServiceName/{print NR; exit}' "$script")"
# shellcheck disable=SC2016
apply_point_of_use_line="$(grep -nF '$pointOfUsePreMutationMap = Read-ServiceEnvironmentMap -Path $serviceKey' "$script" | cut -d: -f1)"
# shellcheck disable=SC2016
apply_write_line="$(grep -nF 'Write-ServiceEnvironmentMap -Path $serviceKey -Map $patched' "$script" | cut -d: -f1)"
# shellcheck disable=SC2016
apply_restart_line="$(grep -nF '$serviceAfter = Start-ServiceAndWait -Name $ServiceName' "$script" | cut -d: -f1)"
[[ -n "$lock_create_line" && -n "$backup_create_line" && "$lock_create_line" -lt "$backup_create_line" ]] || {
  echo "exclusive transaction lock must be acquired before creating or touching rollback evidence" >&2
  exit 1
}
[[ -n "$cleanup_register_line" && "$cleanup_register_line" -lt "$lock_create_line" ]] || {
  echo "deadline recovery task must be registered before acquiring the transaction lock" >&2
  exit 1
}
[[ -n "$apply_quiesce_line" && -n "$apply_point_of_use_line" && -n "$apply_write_line" && -n "$apply_restart_line" \
  && "$apply_quiesce_line" -lt "$apply_point_of_use_line" \
  && "$apply_point_of_use_line" -lt "$apply_write_line" \
  && "$apply_write_line" -lt "$apply_restart_line" ]] || {
  echo "apply must quiesce the service before its point-of-use read/write and restart it afterward" >&2
  exit 1
}
# shellcheck disable=SC2016
if grep -Fq '[void]$releaseMap.Remove("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID")' "$script"; then
  echo "accepted lock release must not clear the recovery marker before durable release" >&2
  exit 1
fi
if grep -Fq 'reg.exe export' "$script" || grep -Fq 'reg.exe import' "$script"; then
  echo "rollback must not export or import the entire service registry key" >&2
  exit 1
fi

for policy_literal in \
  "$(jq -er '.current_bounded_pilot.release_tag' "$policy")" \
  "$(jq -er '.current_bounded_pilot.release_manifest_sha256' "$policy")" \
  "$(jq -er '.current_bounded_pilot.endpoint_agent_sha256' "$policy")" \
  "$(jq -er '.current_bounded_pilot.artifact_host_digest' "$policy")" \
  "$(jq -er '.current_bounded_pilot.artifact_host_image_ref' "$policy")"; do
  if grep -Fq -- "$policy_literal" "$script"; then
    echo "activation patch must not duplicate release-policy literal: $policy_literal" >&2
    exit 1
  fi
done
if grep -Eq 'v[0-9]+\.[0-9]+\.[0-9]+' "$script"; then
  echo "activation patch must not carry any independently maintained release version" >&2
  exit 1
fi

release_arguments="$(bash -c 'source scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh; release_policy_patch_arguments')"
for injected_literal in \
  "$(jq -er '.current_bounded_pilot.release_tag' "$policy")" \
  "$(jq -er '.current_bounded_pilot.github_release_base_url' "$policy")" \
  "$(jq -er '.current_bounded_pilot.artifact_release_base_url' "$policy")" \
  "$(jq -er '.current_bounded_pilot.release_manifest_sha256' "$policy")" \
  "$(jq -er '.current_bounded_pilot.endpoint_agent_sha256' "$policy")" \
  "$(jq -er '.current_bounded_pilot.artifact_host_digest' "$policy")" \
  "$(jq -er '.current_bounded_pilot.artifact_host_image_ref' "$policy")"; do
  if [[ "$release_arguments" != *"$injected_literal"* ]]; then
    echo "migration orchestrator did not inject canonical policy value: $injected_literal" >&2
    exit 1
  fi
done

if EXPECTED_AGENT_TAG=v9.9.9 bash -c '
  source scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh
  validate_release_policy_bindings
' >/dev/null 2>&1; then
  echo "migration orchestrator accepted a release-policy environment override" >&2
  exit 1
fi

# shellcheck disable=SC2016
if grep -Fq 'signaturePresent = $true' "$script" || grep -Fq 'publicKeyVerification = "verified-by-release-producer' "$script"; then
  echo "activation evidence must not encode unverified signature claims as verified facts" >&2
  exit 1
fi

if grep -Fq "Get-Content -LiteralPath \$summaryPath" "$script"; then
  echo "activation patch must not emit the full evidence summary to stdout" >&2
  exit 1
fi

if grep -Eiq '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|bearer[[:space:]]+[A-Za-z0-9._-]{20,}|password[[:space:]]*=)' "$script"; then
  echo "activation patch appears to contain a credential or private key" >&2
  exit 1
fi

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

# Execute the exact atomic summary writer for initial create and replacement.
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-AtomicJsonFile"
    }, $true)
    if ($null -eq $functionAst) { throw "atomic JSON writer missing" }
    Invoke-Expression $functionAst.Extent.Text
    $root = Join-Path ([IO.Path]::GetTempPath()) ("f22-atomic-json-" + [Guid]::NewGuid().ToString("N"))
    $path = Join-Path $root "summary.json"
    try {
      New-Item -ItemType Directory -Path $root | Out-Null
      Write-AtomicJsonFile -Value ([ordered]@{ generation = 1 }) -Path $path -Depth 3
      Write-AtomicJsonFile -Value ([ordered]@{ generation = 2 }) -Path $path -Depth 3
      $result = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
      if ([int]$result.generation -ne 2) { throw "atomic JSON replacement did not commit the second generation" }
      if (@(Get-ChildItem -LiteralPath $root -Filter "*.tmp").Count -ne 0) { throw "atomic JSON temporary file leaked" }
    } finally {
      Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
  '

# Round-trip the exact scoped environment backup with characters that make
# ad-hoc line parsing unsafe, then reject duplicate keys.
# Keep the parser shape compatible with Windows PowerShell 5.1. Directly
# wrapping ConvertFrom-Json in @() produces a nested top-level array there,
# and PSMemberInfoCollection["name"] can return null for an existing property.
# shellcheck disable=SC2016
ps51_parse='$parsed = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json'
# shellcheck disable=SC2016
ps51_rows='$rows = @($parsed)'
# shellcheck disable=SC2016
ps51_direct_re='\$rows = @\(Get-Content -LiteralPath .*\| ConvertFrom-Json\)'
# shellcheck disable=SC2016
ps51_key_guard='$row.PSObject.Properties.Name -contains "key"'
# shellcheck disable=SC2016
ps51_value_guard='$row.PSObject.Properties.Name -contains "value"'
grep -Fq "$ps51_parse" "$script" || {
  echo "missing Windows PowerShell 5.1 two-stage JSON parse" >&2
  exit 1
}
grep -Fq "$ps51_rows" "$script" || {
  echo "missing Windows PowerShell 5.1 backup row enumeration" >&2
  exit 1
}
if grep -Eq "$ps51_direct_re" "$script"; then
  echo "direct ConvertFrom-Json array capture is incompatible with Windows PowerShell 5.1" >&2
  exit 1
fi
grep -Fq "$ps51_key_guard" "$script" || {
  echo "missing Windows PowerShell 5.1 key-property guard" >&2
  exit 1
}
grep -Fq "$ps51_value_guard" "$script" || {
  echo "missing Windows PowerShell 5.1 value-property guard" >&2
  exit 1
}
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    foreach ($name in @("Write-AtomicJsonFile", "Write-ServiceEnvironmentBackup", "Read-ServiceEnvironmentBackup", "Assert-MapsEqual", "Get-Utf8Sha256", "Get-ServiceEnvironmentSubsetSha256", "New-ManagedEnvironmentRestorationMap")) {
      $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
      }, $true)
      if ($null -eq $functionAst) { throw "required environment-backup function missing: $name" }
      Invoke-Expression $functionAst.Extent.Text
    }
    $root = Join-Path ([IO.Path]::GetTempPath()) ("f22-env-backup-" + [Guid]::NewGuid().ToString("N"))
    $path = Join-Path $root "EndpointAgent-environment-before.json"
    try {
      New-Item -ItemType Directory -Path $root | Out-Null
      $expected = [ordered]@{ ALPHA = "one=two"; BETA = "line1`nline2"; EMPTY = "" }
      Write-ServiceEnvironmentBackup -Map $expected -Path $path
      $actual = Read-ServiceEnvironmentBackup -Path $path
      Assert-MapsEqual -Expected $expected -Actual $actual
      $current = [ordered]@{ ALPHA = "transaction"; BETA = "line1`nline2"; EMPTY = ""; UNRELATED = "concurrent-update" }
      $scoped = New-ManagedEnvironmentRestorationMap -CurrentMap $current -BackupMap $actual -ManagedKeys @("ALPHA")
      if ($scoped.ALPHA -ne "one=two" -or $scoped.UNRELATED -ne "concurrent-update") {
        throw "managed restoration did not preserve an unrelated concurrent update"
      }
      $subsetOne = Get-ServiceEnvironmentSubsetSha256 -Map $current -Keys @("ALPHA")
      $current.UNRELATED = "another-update"
      $subsetTwo = Get-ServiceEnvironmentSubsetSha256 -Map $current -Keys @("ALPHA")
      if ($subsetOne -ne $subsetTwo) { throw "managed subset digest included an unrelated key" }
      @(
        [ordered]@{ key = "DUP"; value = "one" },
        [ordered]@{ key = "DUP"; value = "two" }
      ) | ConvertTo-Json | Set-Content -LiteralPath $path
      $duplicateRejected = $false
      try { Read-ServiceEnvironmentBackup -Path $path | Out-Null } catch { $duplicateRejected = $true }
      if (-not $duplicateRejected) { throw "duplicate environment backup key was accepted" }
    } finally {
      Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
  '

pwsh -NoProfile -NonInteractive -File \
  scripts/test/denetim-device-key-view-only-env-patch-roundtrip.ps1 \
  -ScriptPath "$script"

# Materialize and parse the encoded SYSTEM cleanup body. The outer script parser
# treats the here-string as data, so this catches syntax errors in the scheduled
# compensating rollback itself.
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    if ($errors.Count -gt 0) { exit 1 }
    $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Register-RollbackCleanupTask"
    }, $true)
    if ($null -eq $functionAst) { throw "cleanup registration function missing" }
    Invoke-Expression $functionAst.Extent.Text

    function New-ScheduledTaskAction {
      param($Execute, $Argument)
      $script:cleanupArgument = $Argument
      [pscustomobject]@{ Execute = $Execute; Argument = $Argument }
    }
    function New-ScheduledTaskTrigger { param([switch]$Once, [switch]$Daily, $At) [pscustomobject]@{} }
    function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) [pscustomobject]@{} }
    function New-ScheduledTaskSettingsSet {
      param([switch]$StartWhenAvailable, $RestartCount, $RestartInterval, $ExecutionTimeLimit)
      [pscustomobject]@{}
    }
    function Register-ScheduledTask {
      param($TaskName, $Action, $Trigger, $Principal, $Settings, [switch]$Force)
      [pscustomobject]@{ TaskName = $TaskName }
    }
    function Get-ScheduledTask { param($TaskName) [pscustomobject]@{ TaskName = $TaskName } }

    $tx = "a" * 32
    $originalCulture = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
      [Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo("tr-TR")
      Register-RollbackCleanupTask `
        -BackupDirectory "C:\evidence\/denetim-device-key-view-only-$tx" `
        -EvidenceRootPath "C:\evidence" `
        -TransactionLockDirectory "C:\locks\migration.lock" `
        -TransactionLockOwnerFile "C:\locks\migration.lock\owner.txt" `
        -BoundTransactionId $tx `
        -BoundServiceName EndpointAgent `
        -ExpectedPreMutationServiceEnvironmentSha256 ("b" * 64) `
        -ManagedEnvironmentKeys @("ENDPOINT_AGENT_REMOTE_BRIDGE_MIGRATION_TRANSACTION_ID") `
        -DeleteAfterUtc ([DateTime]::UtcNow.AddHours(1).ToString("o")) | Out-Null
      $invalidKeyRejected = $false
      try {
        Register-RollbackCleanupTask `
          -BackupDirectory "C:\evidence\/denetim-device-key-view-only-$tx" `
          -EvidenceRootPath "C:\evidence" `
          -TransactionLockDirectory "C:\locks\migration.lock" `
          -TransactionLockOwnerFile "C:\locks\migration.lock\owner.txt" `
          -BoundTransactionId $tx `
          -BoundServiceName EndpointAgent `
          -ExpectedPreMutationServiceEnvironmentSha256 ("b" * 64) `
          -ManagedEnvironmentKeys @("endpoint_agent_remote_bridge_migration_transaction_id") `
          -DeleteAfterUtc ([DateTime]::UtcNow.AddHours(1).ToString("o")) | Out-Null
      } catch {
        if ($_.Exception.Message -eq "Managed environment key set is invalid for cleanup registration") {
          $invalidKeyRejected = $true
        } else {
          throw
        }
      }
      if (-not $invalidKeyRejected) { throw "non-canonical managed environment key was accepted under tr-TR" }
    } finally {
      [Threading.Thread]::CurrentThread.CurrentCulture = $originalCulture
    }

    $encoded = ($script:cleanupArgument -split " ")[-1]
    $cleanupCode = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($encoded))
    if ($cleanupCode.Contains("-notmatch")) {
      throw "embedded cleanup body contains a culture-sensitive digest validator"
    }
    if (-not $cleanupCode.Contains("-cnotmatch")) {
      throw "embedded cleanup body is missing culture-independent digest validation"
    }
    if ($cleanupCode -match "\`$rows = @\(Get-Content -LiteralPath .*\| ConvertFrom-Json\)") {
      throw "embedded cleanup body uses the Windows PowerShell 5.1-incompatible JSON array capture"
    }
    if (-not $cleanupCode.Contains("`$parsed = Get-Content -LiteralPath `$environmentBackup -Raw -ErrorAction Stop | ConvertFrom-Json") -or
        -not $cleanupCode.Contains("`$rows = @(`$parsed)")) {
      throw "embedded cleanup body is missing the Windows PowerShell 5.1 two-stage JSON parse"
    }
    $singleQuote = [char]39
    if (-not $cleanupCode.Contains("`$row.PSObject.Properties.Name -contains " + $singleQuote + "key" + $singleQuote) -or
        -not $cleanupCode.Contains("`$row.PSObject.Properties.Name -contains " + $singleQuote + "value" + $singleQuote)) {
      throw "embedded cleanup body is missing Windows PowerShell 5.1 property guards"
    }
    $cleanupTokens = $null
    $cleanupErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput(
      $cleanupCode,
      [ref]$cleanupTokens,
      [ref]$cleanupErrors
    )
    if ($cleanupErrors.Count -gt 0) {
      $cleanupErrors | ForEach-Object { Write-Error $_.Message }
      exit 1
    }
  '

# Exercise the exact lock release helper against matching and conflicting owners.
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    if ($errors.Count -gt 0) { exit 1 }
    $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Remove-TransactionLock"
    }, $true)
    if ($null -eq $functionAst) { throw "transaction lock helper missing" }
    Invoke-Expression $functionAst.Extent.Text

    $root = Join-Path ([IO.Path]::GetTempPath()) ("f22-lock-test-" + [Guid]::NewGuid().ToString("N"))
    $owner = Join-Path $root "owner.txt"
    try {
      New-Item -ItemType Directory -Force -Path $root | Out-Null
      Set-Content -LiteralPath $owner -Value ("b" * 32)
      $wrongOwnerRejected = $false
      try {
        Remove-TransactionLock -LockDirectory $root -OwnerFile $owner -BoundTransactionId ("a" * 32)
      } catch { $wrongOwnerRejected = $true }
      if (-not $wrongOwnerRejected -or -not (Test-Path -LiteralPath $root)) {
        throw "conflicting transaction lock owner was not preserved"
      }
      Remove-TransactionLock -LockDirectory $root -OwnerFile $owner -BoundTransactionId ("b" * 32)
      if (Test-Path -LiteralPath $root) { throw "matching transaction lock was not removed" }
    } finally {
      Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 0
  '

# Exercise the exact transaction-bound rollback resolver with a valid fixture,
# a wrong requested transaction, and a tampered summary transaction.
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    if ($errors.Count -gt 0) { exit 1 }
    $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-TransactionBoundRollback"
    }, $true)
    if ($null -eq $functionAst) { throw "rollback resolver function missing" }
    Invoke-Expression $functionAst.Extent.Text

    $root = Join-Path ([IO.Path]::GetTempPath()) ("f22-rollback-test-" + [Guid]::NewGuid().ToString("N"))
    $tx = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    $dir = Join-Path $root "denetim-device-key-view-only-$tx"
    $export = Join-Path $dir "EndpointAgent-environment-before.json"
    $summary = Join-Path $dir "summary.json"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -LiteralPath $export -Value "fixture"
    $exportSha256 = (Get-FileHash -LiteralPath $export -Algorithm SHA256).Hash.ToLowerInvariant()
    [ordered]@{
      schema = "faz22.6.denetimepc-device-key-view-only-activation.v4"
      transactionId = $tx
      rollback = [ordered]@{
        environmentBackupSha256 = $exportSha256
        preMutationServiceEnvironmentSha256 = ("b" * 64)
        managedPreMutationSha256 = ("d" * 64)
        managedPostMutationSha256 = ("c" * 64)
      }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary
    try {
      $valid = Resolve-TransactionBoundRollback -EvidenceRootPath $root -EnvironmentBackupPath $export -BoundServiceName EndpointAgent -BoundTransactionId $tx
      if ($valid.expectedServiceEnvironmentSha256 -ne ("b" * 64)) { throw "valid rollback binding failed" }

      $wrongRejected = $false
      try {
        Resolve-TransactionBoundRollback -EvidenceRootPath $root -EnvironmentBackupPath $export -BoundServiceName EndpointAgent -BoundTransactionId ("c" * 32) | Out-Null
      } catch { $wrongRejected = $true }
      if (-not $wrongRejected) { throw "wrong rollback transaction was accepted" }

      Add-Content -LiteralPath $export -Value "tampered"
      $exportTamperRejected = $false
      try {
        Resolve-TransactionBoundRollback -EvidenceRootPath $root -EnvironmentBackupPath $export -BoundServiceName EndpointAgent -BoundTransactionId $tx | Out-Null
      } catch { $exportTamperRejected = $true }
      if (-not $exportTamperRejected) { throw "tampered environment backup was accepted" }
      Set-Content -LiteralPath $export -Value "fixture"

      $tampered = Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
      $tampered.transactionId = "d" * 32
      $tampered | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary
      $tamperedRejected = $false
      try {
        Resolve-TransactionBoundRollback -EvidenceRootPath $root -EnvironmentBackupPath $export -BoundServiceName EndpointAgent -BoundTransactionId $tx | Out-Null
      } catch { $tamperedRejected = $true }
      if (-not $tamperedRejected) { throw "tampered rollback summary transaction was accepted" }
    } finally {
      Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
  '

# Execute the exact pure validator from the production script against typed,
# stringly-typed, null, and missing fixtures. This catches Windows PowerShell
# truthiness bugs such as [bool]"false" evaluating to true.
# shellcheck disable=SC2016
pwsh -NoProfile -NonInteractive -Command '
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
      "scripts/faz22-remote-ops/denetim-device-key-view-only-env-patch.ps1",
      [ref]$tokens,
      [ref]$errors
    )
    if ($errors.Count -gt 0) { exit 1 }
    $functionAst = $ast.Find({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Assert-JsonBooleanProperty"
    }, $true)
    if ($null -eq $functionAst) { throw "boolean validator function missing" }
    Invoke-Expression $functionAst.Extent.Text

    Assert-JsonBooleanProperty -Object ([pscustomobject]@{ flag = $true }) -Name flag -Expected $true
    Assert-JsonBooleanProperty -Object ([pscustomobject]@{ flag = $false }) -Name flag -Expected $false
    $stringTrueRejected = $false
    try {
      Assert-JsonBooleanProperty -Object ([pscustomobject]@{ flag = "true" }) -Name flag -Expected $true
    } catch {
      $stringTrueRejected = $true
    }
    if (-not $stringTrueRejected) { throw "boolean validator accepted string true for expected true" }
    foreach ($bad in @(
      [pscustomobject]@{ flag = "true" },
      [pscustomobject]@{ flag = "false" },
      [pscustomobject]@{ flag = $null },
      [pscustomobject]@{}
    )) {
      $rejected = $false
      try {
        Assert-JsonBooleanProperty -Object $bad -Name flag -Expected $false
      } catch {
        $rejected = $true
      }
      if (-not $rejected) { throw "boolean validator accepted an untyped or missing fixture" }
    }
  '

bash -n "$orchestrator"
grep -Fq 'source "${SCRIPT_DIR}/endpoint-agent-release-policy.sh"' "$orchestrator" || {
  echo "migration orchestrator must source the canonical release policy loader" >&2
  exit 1
}
grep -Fq 'endpoint_agent_release_policy_load "$REPO_ROOT"' "$orchestrator" || {
  echo "migration orchestrator must load the canonical release policy" >&2
  exit 1
}
grep -Fq 'release_policy_patch_arguments' "$orchestrator" || {
  echo "migration orchestrator must inject a transaction-scoped release-policy snapshot" >&2
  exit 1
}
grep -Fq 'validate_mask_rect_bps' "$orchestrator" || {
  echo "migration orchestrator must validate the transaction-bound DLP mask policy" >&2
  exit 1
}
# shellcheck disable=SC2016
if ! grep -Fq -- '-ExpectedViewOnlyMaskRectBps' "$orchestrator" \
  || ! grep -Fq 'powershell_single_quote "$DLP_MASK_RECT_BPS"' "$orchestrator"; then
  echo "migration orchestrator must inject the workflow DLP mask policy into the endpoint transaction" >&2
  exit 1
fi

DLP_MASK_RECT_BPS=7500,7500,2500,2500 bash -c '
  source scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh
  validate_mask_rect_bps
' || {
  echo "migration orchestrator rejected a valid DLP mask policy" >&2
  exit 1
}
for invalid_mask in "" "0,0,0,1" "7500,7500,2500,0" "7500,7500,2501,2500" \
  "10000,0,1,1" "99999,0,1,1" "7500,7500,2500" "a,7500,2500,2500"; do
  if DLP_MASK_RECT_BPS="$invalid_mask" bash -c '
    source scripts/faz22-remote-ops/apply-denetim-attestation-migration.sh
    validate_mask_rect_bps
  ' >/dev/null 2>&1; then
    echo "migration orchestrator accepted invalid DLP mask policy: ${invalid_mask:-empty}" >&2
    exit 1
  fi
done
grep -Fq 'trap rollback_on_failure EXIT' "$orchestrator" || {
  echo "migration orchestrator must arm automatic rollback after endpoint apply" >&2
  exit 1
}
grep -Fq 'CONSENT_TRUST_REFRESHED:cert=true,attestation=true' "$orchestrator" || {
  echo "migration orchestrator must require session-bound broker attestation proof" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'session=${expected_session_id} ' "$orchestrator" || {
  echo "migration orchestrator must bind broker proof to the transaction session" >&2
  exit 1
}
if grep -Fq 'HELLO_VERIFIED:cert=true,attestation=true' "$orchestrator"; then
  echo "migration orchestrator must not accept an unbound peer HELLO" >&2
  exit 1
fi
grep -Fq 'status=rollback-restored-service-running' "$orchestrator" || {
  echo "migration orchestrator must verify rollback completion" >&2
  exit 1
}
grep -Fq 'transaction patch script SHA256 mismatch' "$orchestrator" || {
  echo "migration orchestrator must verify the transaction-specific remote patch digest" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'denetim-device-key-view-only-env-patch-${transaction_id}.ps1' "$orchestrator" || {
  echo "migration orchestrator must use a transaction-specific remote patch path" >&2
  exit 1
}
grep -Fq -- '-Action ReleaseLock' "$orchestrator" || {
  echo "migration orchestrator must release its transaction lock only after product proof" >&2
  exit 1
}
grep -Fq 'permanent AnyDesk-like product runtime' "$orchestrator" || {
  echo "migration orchestrator must declare that it is not a permanent product runtime dependency" >&2
  exit 1
}
grep -Fq "apply-denetim-attestation-migration.sh" "$workflow" || {
  echo "browser evidence workflow must run the transaction-bound migration wrapper" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'collector_kubeconfig="$(mktemp "$RUNNER_TEMP/faz22-viewer-kubeconfig.XXXXXX")"' "$workflow" || {
  echo "browser evidence workflow must create the collector kubeconfig atomically with a random name" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'kubectl config view --raw --flatten --minify --context=k3d-test > "$collector_kubeconfig"' "$workflow" || {
  echo "browser evidence workflow must derive an isolated k3d-test-only kubeconfig" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'KUBECONFIG="$collector_kubeconfig" kubectl config use-context k3d-test' "$workflow" || {
  echo "browser evidence workflow must scope context selection to the isolated kubeconfig" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'KUBECONFIG="$collector_kubeconfig" kubectl config current-context' "$workflow" || {
  echo "browser evidence workflow must verify the isolated current context" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'chmod 600 "$collector_kubeconfig"' "$workflow" || {
  echo "browser evidence workflow must protect the credential-bearing kubeconfig" >&2
  exit 1
}
grep -Fq 'trap cleanup_collector_kubeconfig EXIT' "$workflow" || {
  echo "browser evidence workflow must remove the isolated kubeconfig on every exit" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'shred -u -- "$path"' "$workflow" || {
  echo "browser evidence workflow must securely remove the credential-bearing kubeconfig" >&2
  exit 1
}
grep -Fq 'name: Remove isolated collector kubeconfig' "$workflow" || {
  echo "browser evidence workflow must have an always-run kubeconfig cleanup step" >&2
  exit 1
}
grep -Fq 'COLLECTOR_KUBECONFIG_CLEANUP_PATH=' "$workflow" || {
  echo "browser evidence workflow must bind cleanup to the exact random kubeconfig path" >&2
  exit 1
}
grep -Fq "printf 'COLLECTOR_KUBECONFIG_CLEANUP_PATH=\\n'" "$workflow" || {
  echo "browser evidence workflow must clear the cross-step cleanup-path variable" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq '[ ! -L "$collector_kubeconfig" ]' "$workflow" || {
  echo "browser evidence workflow must reject a symlinked collector kubeconfig" >&2
  exit 1
}
grep -Fq 'umask 077' "$workflow" || {
  echo "browser evidence workflow must create collector evidence and credentials owner-only" >&2
  exit 1
}
grep -Fq "stat -c '%a'" "$workflow" || {
  echo "browser evidence workflow must verify kubeconfig mode 0600 at runtime" >&2
  exit 1
}
# shellcheck disable=SC2016
grep -Fq 'export KUBECONFIG="$collector_kubeconfig"' "$workflow" || {
  echo "browser evidence workflow must scope the isolated kubeconfig to collector children" >&2
  exit 1
}
while IFS= read -r config_mutation; do
  trimmed="${config_mutation#"${config_mutation%%[![:space:]]*}"}"
  # shellcheck disable=SC2016
  [[ "$trimmed" == 'KUBECONFIG="$collector_kubeconfig" kubectl config use-context k3d-test >/dev/null' ]] || {
    echo "browser evidence workflow contains an unscoped or unexpected kubeconfig mutation" >&2
    exit 1
  }
done < <(grep -E 'kubectl config (use-context|set|set-context|set-cluster|set-credentials|unset|rename-context|delete-context|delete-cluster|delete-user)([[:space:]]|$)' "$workflow" || true)

# Execute the exact orchestrator evidence validator against valid, wrong-session,
# wrong-broker-session, and insufficient-ACK fixtures.
ORCHESTRATOR_PATH="$orchestrator" bash -euo pipefail -c '
  source "$ORCHESTRATOR_PATH"
  d="$(mktemp -d)"
  trap '\''rm -rf "$d"'\'' EXIT
  marker="$d/proof-start"
  : >"$marker"
  sleep 1
  sid="rb-viewonly-attended-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  export SOURCE_REVISION="abc123"
  cat >"$d/summary.json" <<JSON
{"status":"accepted-candidate","sessionId":"$sid","consentWait":"granted","brokerSignals":["CONSENT_GRANTED"]}
JSON
  printf '\''{"consentPromptSent":true}\n'\'' >"$d/open-session.body"
  session_sha="sha256:$(printf '\''%s'\'' "$sid" | sha256_text)"
  cat >"$d/browser.json" <<JSON
{"schemaVersion":"faz22.6.viewOnlyViewerProductChildEvidence.v2","evidenceType":"browser","sourceRevision":"abc123","producer":{"kind":"browser-harness","toolVersion":"v3-ack-drain"},"binding":{"sessionSha256":"$session_sha"},"payload":{"pilotEndedAt":"2026-07-18T00:00:00Z","ackDrainCompleted":true,"ackDrainCutoffAt":"2026-07-18T00:00:00Z","ackDrainNonceSha256":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","ackDrainClosureKind":"none","renderAckAcceptedCount":100,"renderAckAttemptedCount":100,"renderAckRejectedCount":0,"renderAckPendingCount":0}}
JSON
  printf '\''session="%s" granted=true\n'\'' "$sid" >"$d/endpoint-agent-relevant.log"
  printf '\''session=%s type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true\n'\'' "$sid" >"$d/broker-relevant.log"
  validate_product_evidence "$d" "$sid" "$marker" >/dev/null
  printf '\''session=%s type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=false\n'\'' "$sid" >"$d/broker-relevant.log"
  if validate_product_evidence "$d" "$sid" "$marker" >/dev/null 2>&1; then
    echo "orchestrator accepted broker evidence without real device-key verification" >&2; exit 1
  fi
  printf '\''session=%s type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true\n'\'' "$sid" >"$d/broker-relevant.log"
  stale_marker="$d/stale-check-start"
  : >"$stale_marker"
  if validate_product_evidence "$d" "$sid" "$stale_marker" >/dev/null 2>&1; then
    echo "orchestrator accepted product evidence created before the transaction marker" >&2; exit 1
  fi

  if validate_product_evidence "$d" "rb-viewonly-attended-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" "$marker" >/dev/null 2>&1; then
    echo "orchestrator accepted wrong product session" >&2; exit 1
  fi
  printf '\''session=rb-viewonly-attended-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true\n'\'' >"$d/broker-relevant.log"
  if validate_product_evidence "$d" "$sid" "$marker" >/dev/null 2>&1; then
    echo "orchestrator accepted wrong broker session" >&2; exit 1
  fi
  printf '\''session=%s type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true\n'\'' "$sid" >"$d/broker-relevant.log"
  jq '\''.payload.renderAckAcceptedCount = 99 | .payload.renderAckAttemptedCount = 100'\'' "$d/browser.json" >"$d/browser.tmp"
  mv "$d/browser.tmp" "$d/browser.json"
  if validate_product_evidence "$d" "$sid" "$marker" >/dev/null 2>&1; then
    echo "orchestrator accepted insufficient render ACK evidence" >&2; exit 1
  fi
'

# Run the orchestrator entrypoint with command stubs to prove that a child
# product-command failure enters the transaction-bound rollback path, and that
# a rollback failure remains a hard error.
orchestrator_harness="$(mktemp -d)"
trap 'rm -rf "$orchestrator_harness"' EXIT
mkdir -p "$orchestrator_harness/bin"
cat >"$orchestrator_harness/bin/hostname" <<'SH'
#!/usr/bin/env bash
printf 'stagingsw\n'
SH
cat >"$orchestrator_harness/bin/kubectl" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == "config" && "${2:-}" == "current-context" ]]; then
  printf 'k3d-test\n'
fi
SH
cat >"$orchestrator_harness/bin/scp" <<'SH'
#!/usr/bin/env bash
exit 0
SH
cat >"$orchestrator_harness/bin/base64" <<'SH'
#!/usr/bin/env bash
python3 -c 'import base64,sys; sys.stdout.write(base64.b64encode(sys.stdin.buffer.read()).decode())'
SH
cat >"$orchestrator_harness/bin/ssh" <<'SH'
#!/usr/bin/env bash
if [[ " $* " == *" -G "* ]]; then
  exit 0
fi
remote_command="${!#}"
encoded="${remote_command##* }"
encoded="${encoded#\'}"
encoded="${encoded%\'}"
body="$(python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.argv[1]))' "$encoded" | iconv -f UTF-16LE -t UTF-8)"
if [[ "$body" == *"-Action Apply"* ]]; then
  tx="$(grep -Eo -- "-TransactionId '[a-f0-9]{32}'" <<<"$body" | cut -d "'" -f2)"
  [[ "$body" == *"denetim-device-key-view-only-env-patch-${tx}.ps1"* ]] || exit 1
  [[ "$body" == *"transaction patch script SHA256 mismatch"* ]] || exit 1
  [[ "$body" == *"-ExpectedViewOnlyMaskRectBps '7500,7500,2500,2500'"* ]] || exit 1
  if [[ "${FAKE_APPLY_RESPONSE_LOST:-0}" == "1" ]]; then
    exit 1
  fi
  printf 'status=configuration-written-service-running-awaiting-broker-proof\r\n'
  printf 'evidence=C:\\ProgramData\\EndpointAgent\\rollout-evidence\\denetim-device-key-view-only-%s\\summary.json\r\n' "$tx"
elif [[ "$body" == *"-Action Rollback"* ]]; then
  if [[ "${FAKE_ROLLBACK_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
  printf 'status=rollback-restored-service-running\r\n'
  printf 'restoredServiceEnvironmentSha256=%064d\r\n' 0
  if [[ -n "${FAKE_ACTION_LOG:-}" ]]; then printf 'rollback\n' >>"$FAKE_ACTION_LOG"; fi
elif [[ "$body" == *"-Action Inspect"* ]]; then
  printf 'status=transaction-state-observed\r\n'
  if [[ "${FAKE_INSPECT_NO_MUTATION:-0}" == "1" ]]; then
    printf 'lockState=absent\r\nmarkerState=foreign\r\nbackupPresent=false\r\nsummaryState=absent\r\n'
  else
    printf 'lockState=owned\r\nmarkerState=owned\r\nbackupPresent=true\r\nsummaryState=configuration-written-service-running-awaiting-broker-proof\r\n'
  fi
elif [[ "$body" == *"-Action ReleaseLock"* ]]; then
  if [[ "${FAKE_RELEASE_AMBIGUOUS:-0}" == "1" && ! -e "${FAKE_RELEASE_STATE:?}" ]]; then
    : >"$FAKE_RELEASE_STATE"
    exit 1
  fi
  if [[ "${FAKE_RELEASE_AMBIGUOUS:-0}" == "1" ]]; then
    printf 'status=transaction-lock-already-released\r\n'
  else
  printf 'status=transaction-lock-released\r\n'
  fi
  if [[ -n "${FAKE_ACTION_LOG:-}" ]]; then printf 'release\n' >>"$FAKE_ACTION_LOG"; fi
elif [[ "$body" == *"backupPresent"* ]]; then
  printf 'backupPresent=true\r\n'
elif [[ "$body" == *"summarySha256="* ]]; then
  printf 'summarySha256=%064d\r\n' 0
elif [[ "$body" == *"Remove-Item -LiteralPath"* ]]; then
  exit 0
else
  exit 1
fi
SH
chmod +x "$orchestrator_harness/bin/"*

set +e
env -u DLP_MASK_RECT_BPS \
  PATH="$orchestrator_harness/bin:$PATH" \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  bash "$orchestrator" false >"$orchestrator_harness/missing-mask.out" 2>&1
missing_mask_rc=$?
set -e
[[ "$missing_mask_rc" -eq 2 ]] || {
  cat "$orchestrator_harness/missing-mask.out" >&2
  echo "orchestrator accepted a missing DLP mask policy" >&2
  exit 1
}
grep -Fq 'DLP_MASK_RECT_BPS must be canonical' "$orchestrator_harness/missing-mask.out" || {
  echo "orchestrator did not explain the missing DLP mask policy" >&2
  exit 1
}

export DLP_MASK_RECT_BPS=7500,7500,2500,2500

set +e
PATH="$orchestrator_harness/bin:$PATH" \
  TRANSACTION_ID_OVERRIDE=dddddddddddddddddddddddddddddddd \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  bash "$orchestrator" false >"$orchestrator_harness/override-rejected.out" 2>&1
override_rejected_rc=$?
set -e
[[ "$override_rejected_rc" -eq 2 ]] || { echo "orchestrator accepted a transaction override without the test-only guard" >&2; exit 1; }
grep -Fq 'TRANSACTION_ID_OVERRIDE is test-only' "$orchestrator_harness/override-rejected.out" || {
  echo "orchestrator did not explain the rejected test-only transaction override" >&2; exit 1;
}

set +e
PATH="$orchestrator_harness/bin:$PATH" \
  TRANSACTION_ID_OVERRIDE=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  bash "$orchestrator" false >"$orchestrator_harness/child-failure.out" 2>&1
child_failure_rc=$?
set -e
[[ "$child_failure_rc" -ne 0 ]] || { echo "orchestrator child failure returned success" >&2; exit 1; }
grep -Fq 'status=rollback-restored-service-running' "$orchestrator_harness/child-failure.out" || {
  cat "$orchestrator_harness/child-failure.out" >&2
  echo "orchestrator child failure did not execute verified rollback" >&2; exit 1;
}

set +e
PATH="$orchestrator_harness/bin:$PATH" FAKE_ROLLBACK_FAIL=1 \
  TRANSACTION_ID_OVERRIDE=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  bash "$orchestrator" false >"$orchestrator_harness/rollback-failure.out" 2>&1
rollback_failure_rc=$?
set -e
[[ "$rollback_failure_rc" -ne 0 ]] || { echo "orchestrator rollback failure returned success" >&2; exit 1; }
grep -Fq 'CRITICAL verified rollback failed' "$orchestrator_harness/rollback-failure.out" || {
  echo "orchestrator rollback failure was not surfaced as critical" >&2; exit 1;
}

set +e
PATH="$orchestrator_harness/bin:$PATH" FAKE_APPLY_RESPONSE_LOST=1 \
  TRANSACTION_ID_OVERRIDE=ffffffffffffffffffffffffffffffff \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  FAKE_ACTION_LOG="$orchestrator_harness/lost-apply-action.log" \
  bash "$orchestrator" false >"$orchestrator_harness/lost-apply-response.out" 2>&1
lost_apply_response_rc=$?
set -e
[[ "$lost_apply_response_rc" -ne 0 ]] || { echo "lost Apply response returned success" >&2; exit 1; }
grep -Fq 'rollback' "$orchestrator_harness/lost-apply-action.log" || {
  cat "$orchestrator_harness/lost-apply-response.out" >&2
  echo "lost Apply response did not serialize state inspection and rollback" >&2; exit 1;
}
if grep -Fq 'release' "$orchestrator_harness/lost-apply-action.log"; then
  echo "lost Apply response incorrectly released an unproven transaction" >&2; exit 1;
fi

set +e
PATH="$orchestrator_harness/bin:$PATH" FAKE_APPLY_RESPONSE_LOST=1 FAKE_INSPECT_NO_MUTATION=1 \
  TRANSACTION_ID_OVERRIDE=11111111111111111111111111111111 \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  FAKE_ACTION_LOG="$orchestrator_harness/no-mutation-action.log" \
  bash "$orchestrator" false >"$orchestrator_harness/no-mutation-response.out" 2>&1
no_mutation_response_rc=$?
set -e
[[ "$no_mutation_response_rc" -ne 0 ]] || { echo "lost no-mutation Apply response returned success" >&2; exit 1; }
grep -Fq 'serialized inspection proved that the mutation boundary was not crossed' \
  "$orchestrator_harness/no-mutation-response.out" || {
  cat "$orchestrator_harness/no-mutation-response.out" >&2
  echo "foreign baseline marker was not accepted as a serialized no-mutation state" >&2; exit 1;
}
if [[ -s "$orchestrator_harness/no-mutation-action.log" ]]; then
  echo "serialized no-mutation state triggered rollback or ReleaseLock" >&2; exit 1;
fi

cat >"$orchestrator_harness/bin/product-proof" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$EVIDENCE_DIR"
cat >"$EVIDENCE_DIR/summary.json" <<JSON
{"status":"accepted-candidate","sessionId":"$SESSION_ID","consentWait":"granted","brokerSignals":["CONSENT_GRANTED"]}
JSON
printf '{"consentPromptSent":true}\n' >"$EVIDENCE_DIR/open-session.body"
cat >"$EVIDENCE_DIR/browser.json" <<JSON
{"schemaVersion":"faz22.6.viewOnlyViewerProductChildEvidence.v2","evidenceType":"browser","sourceRevision":"$SOURCE_REVISION","producer":{"kind":"browser-harness","toolVersion":"v3-ack-drain"},"binding":{"sessionSha256":"$SESSION_SHA256"},"payload":{"pilotEndedAt":"2026-07-18T00:00:00Z","ackDrainCompleted":true,"ackDrainCutoffAt":"2026-07-18T00:00:00Z","ackDrainNonceSha256":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","ackDrainClosureKind":"none","renderAckAcceptedCount":100,"renderAckAttemptedCount":100,"renderAckRejectedCount":0,"renderAckPendingCount":0}}
JSON
printf 'session="%s" granted=true\n' "$SESSION_ID" >"$EVIDENCE_DIR/endpoint-agent-relevant.log"
printf 'session=%s type=CONSENT_TRUST_REFRESHED:cert=true,attestation=true,device=true\n' "$SESSION_ID" >"$EVIDENCE_DIR/broker-relevant.log"
SH
chmod +x "$orchestrator_harness/bin/product-proof"
mkdir -p "$orchestrator_harness/product-evidence"
PATH="$orchestrator_harness/bin:$PATH" \
  TRANSACTION_ID_OVERRIDE=cccccccccccccccccccccccccccccccc \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  EVIDENCE_DIR="$orchestrator_harness/product-evidence" SOURCE_REVISION=abc123 \
  FAKE_ACTION_LOG="$orchestrator_harness/action.log" \
  bash "$orchestrator" product-proof >"$orchestrator_harness/success.out" 2>&1
grep -Fq 'status=transaction-bound-product-attestation-verified' "$orchestrator_harness/success.out" || {
  cat "$orchestrator_harness/success.out" >&2
  echo "orchestrator did not accept valid transaction-bound product proof" >&2; exit 1;
}
grep -Eq '^brokerProofLineSha256=[a-f0-9]{64}$' "$orchestrator_harness/success.out" || {
  echo "orchestrator did not emit a non-empty broker proof-line digest" >&2; exit 1;
}
grep -Eq '^transactionBrokerProofSha256=[a-f0-9]{64}$' "$orchestrator_harness/success.out" || {
  echo "orchestrator did not bind the broker proof digest to the transaction" >&2; exit 1;
}
grep -Fq 'release' "$orchestrator_harness/action.log" || {
  echo "orchestrator did not execute verified lock release after valid product proof" >&2; exit 1;
}

# Simulate the server completing ReleaseLock while the SSH response is lost.
# The EXIT trap must reconcile the same transaction idempotently and must not
# roll back already accepted product evidence.
mkdir -p "$orchestrator_harness/ambiguous-product-evidence"
PATH="$orchestrator_harness/bin:$PATH" \
  TRANSACTION_ID_OVERRIDE=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee \
  ALLOW_TEST_TRANSACTION_ID_OVERRIDE=1 \
  PATCH_SCRIPT="$script" DENETIM_SSH_CONFIG="$orchestrator_harness/ssh-config" \
  EVIDENCE_DIR="$orchestrator_harness/ambiguous-product-evidence" SOURCE_REVISION=abc123 \
  FAKE_ACTION_LOG="$orchestrator_harness/ambiguous-action.log" \
  FAKE_RELEASE_AMBIGUOUS=1 FAKE_RELEASE_STATE="$orchestrator_harness/release-completed.state" \
  bash "$orchestrator" product-proof >"$orchestrator_harness/ambiguous-release.out" 2>&1
grep -Fq 'status=transaction-bound-product-attestation-verified-after-release-reconciliation' \
  "$orchestrator_harness/ambiguous-release.out" || {
  cat "$orchestrator_harness/ambiguous-release.out" >&2
  echo "orchestrator did not reconcile a lost successful ReleaseLock response" >&2; exit 1;
}
if grep -Fq 'status=rollback-restored-service-running' "$orchestrator_harness/ambiguous-release.out"; then
  echo "orchestrator rolled back after product proof and idempotent lock-release reconciliation" >&2; exit 1;
fi

echo "denetim device-key VIEW_ONLY activation static guard passed"
