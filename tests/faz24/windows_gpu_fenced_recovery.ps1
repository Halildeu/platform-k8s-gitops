param([Parameter(Mandatory=$true)][string]$SourcePath)
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($SourcePath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Parse failed.' }
foreach ($name in @('Assert-FencedRecoveryContract','ConvertTo-PowerShellLiteral','Invoke-PowerShellChild','Read-AcceptanceDiagnostic','Invoke-UpdaterChild')) {
  $fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))
  if ($fn.Count -ne 1) { throw 'Function missing.' }
  Invoke-Expression $fn[0].Extent.Text
}
$directory=Join-Path $env:TEMP ('recovery-fixture-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($directory)
$RepoRoot=$directory
$TargetCommit='d85cb11ccd34dea50b47eed472345cf6477a3c18'
$UpdateScript=Join-Path $directory 'fake-updater.ps1'
$utf8=New-Object Text.UTF8Encoding($false)
$script:AcceptanceDiagnostic=$null
$script:AcceptanceDiagnosticInvalid=$false
try {
  Assert-FencedRecoveryContract -CurrentCommit $TargetCommit -ExpectedCommit $TargetCommit `
    -MigrationRequired $false -LiveTaskState 1 -MeetingTaskState 1
  foreach ($case in @(
    @{CurrentCommit=('a' * 40); ExpectedCommit=$TargetCommit; MigrationRequired=$false; LiveTaskState=1; MeetingTaskState=1},
    @{CurrentCommit=$TargetCommit; ExpectedCommit=$TargetCommit; MigrationRequired=$true; LiveTaskState=1; MeetingTaskState=1},
    @{CurrentCommit=$TargetCommit; ExpectedCommit=$TargetCommit; MigrationRequired=$false; LiveTaskState=4; MeetingTaskState=4}
  )) {
    $rejected=$false
    try { Assert-FencedRecoveryContract @case } catch { $rejected=$_.Exception.Message.StartsWith('recovery-') }
    if (-not $rejected) { throw 'Unsafe recovery contract was accepted.' }
  }
  $RecoverFencedRuntime=$true
  [IO.File]::WriteAllText($UpdateScript,'param([switch]$RecoverFencedRuntime); if ($RecoverFencedRuntime) { exit 0 }; exit 87',$utf8)
  if ((Invoke-UpdaterChild) -ne 0) { throw 'Recovery switch was not forwarded.' }
  $rejected=$false
  try { Invoke-UpdaterChild -NoRestartOnly | Out-Null } catch { $rejected=$_.Exception.Message -eq 'recovery-mode-conflict' }
  if (-not $rejected) { throw 'Recovery incorrectly allowed NoRestart.' }
  Write-Output 'PASS Windows recovery guard and updater switch'
} finally {
  # Only the fixture file in the new temporary directory is removed.
  if (Test-Path -LiteralPath $UpdateScript) { Remove-Item -LiteralPath $UpdateScript -Force }
  [IO.Directory]::Delete($directory)
}
