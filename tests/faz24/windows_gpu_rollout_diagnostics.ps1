param(
  [Parameter(Mandatory = $true)][string]$SourcePath,
  [Parameter(Mandatory = $true)][string]$EncodedBootstrap
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
  throw 'This fixture requires Windows PowerShell 5.1.'
}
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($SourcePath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Remote source parse failed.' }
$names = @('ConvertTo-PowerShellLiteral', 'Invoke-PowerShellChild', 'Read-AcceptanceDiagnostic',
  'Invoke-UpdaterChild', 'Invoke-TaskActionMigration')
$helperDefinitions = @()
foreach ($name in $names) {
  $functions = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
  }, $true))
  if ($functions.Count -ne 1) { throw 'Expected exactly one fixture function.' }
  $helperDefinitions += $functions[0].Extent.Text
  Invoke-Expression $functions[0].Extent.Text
}
function Invoke-InputFixture {
  param([string]$Source, [string]$Invocation)
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = 'powershell.exe'
  $start.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass ' +
    '-InputFormat Text -OutputFormat Text ' + $Invocation
  $start.UseShellExecute = $false
  $start.RedirectStandardInput = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $start
  try {
    [void]$process.Start()
    $process.StandardInput.Write($Source)
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return @{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
  } finally { $process.Dispose() }
}
# Only extracted functions run: never the rollout's host/task/Git orchestration.
$directory = Join-Path $env:TEMP ('rollout-fixture-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($directory)
$RepoRoot = $directory
$TargetCommit = 'd85cb11ccd34dea50b47eed472345cf6477a3c18'
$UpdateScript = Join-Path $directory 'fake-updater.ps1'
$MigrationScript = $UpdateScript
$utf8 = New-Object Text.UTF8Encoding($false)
$prefix = 'FAZ24_GPU_ACCEPTANCE_REASON:'
$valid = '{"schemaVersion":"faz24.gpu-acceptance-diagnostic.v1","candidateCommit":"' +
  $TargetCommit + '","reason":"readiness-failed"}'
try {
  foreach ($code in @(0, 2, 3, 4)) {
    [IO.File]::WriteAllText($UpdateScript, "exit $code", $utf8)
    $script:AcceptanceDiagnostic = $null
    $script:AcceptanceDiagnosticInvalid = $false
    if ((Invoke-UpdaterChild) -ne $code) { throw "Updater exit mismatch: $code" }
    if ((Invoke-TaskActionMigration) -ne $code) { throw "Migration exit mismatch: $code" }
  }
  [IO.File]::WriteAllText($UpdateScript, "throw 'fixture terminating exception'", $utf8)
  if ((Invoke-UpdaterChild) -ne 1) { throw 'Exception exit must be 1.' }
  if ((Invoke-TaskActionMigration) -ne 1) { throw 'Migration exception exit must be 1.' }
  [IO.File]::WriteAllText($UpdateScript, "Write-Output 'normal completion'", $utf8)
  if ((Invoke-UpdaterChild) -ne 0) { throw 'Normal script return must remain supported.' }
  [IO.File]::WriteAllText($UpdateScript,
    "[Console]::Out.WriteLine('$prefix$valid'); exit 3", $utf8)
  if ((Invoke-UpdaterChild) -ne 3) { throw 'Diagnostic must retain rejection exit.' }
  if ($script:AcceptanceDiagnostic.reason -cne 'readiness-failed') { throw 'Reason was lost.' }
  $output = Join-Path $directory 'diagnostic.out'
  $invalid = @(
    $valid.Replace('readiness-failed', 'arbitrary-private-detail'),
    $valid.Replace($TargetCommit, ('a' * 40)),
    $valid.Replace('"reason":', '"extra":true,"reason":'),
    $valid.Replace('"reason":', '"reason":"readiness-failed","reason":'),
    '{malformed',
    ('x' * 513)
  )
  foreach ($raw in $invalid) {
    [IO.File]::WriteAllText($output, $prefix + $raw, $utf8)
    $rejected = $false
    try { $null = Read-AcceptanceDiagnostic -Path $output -ExpectedCommit $TargetCommit }
    catch {
      if ($_.Exception.Message -cne 'acceptance-diagnostic-invalid') { throw }
      $rejected = $true
    }
    if (-not $rejected) { throw 'Invalid diagnostic was accepted.' }
  }
  [IO.File]::WriteAllText($output, "$prefix$valid`n$prefix$valid", $utf8)
  $rejected = $false
  try { $null = Read-AcceptanceDiagnostic -Path $output -ExpectedCommit $TargetCommit }
  catch { $rejected = $_.Exception.Message -ceq 'acceptance-diagnostic-invalid' }
  if (-not $rejected) { throw 'Duplicate diagnostic was accepted.' }
  [IO.File]::WriteAllText($output, 'ordinary progress without metadata', $utf8)
  if ($null -ne (Read-AcceptanceDiagnostic -Path $output -ExpectedCommit $TargetCommit)) {
    throw 'Legacy missing marker is not optional.'
  }
  $script:AcceptanceDiagnostic = $null
  [IO.File]::WriteAllText($UpdateScript,
    "[Console]::Out.WriteLine('${prefix}{malformed'); exit 0", $utf8)
  $rejected = $false
  try { $null = Invoke-UpdaterChild }
  catch { $rejected = $_.Exception.Message -ceq 'acceptance-diagnostic-invalid' }
  if (-not $rejected -or -not $script:AcceptanceDiagnosticInvalid) {
    throw 'Malformed marker did not stop the caller.'
  }
  # Exercise the real stdin transport and exact receipt tail, not only -File.
  # Only helper functions and fake children run; host orchestration is excluded.
  $tailStart = $ast.Extent.Text.LastIndexOf(
    'if ($null -ne $script:AcceptanceDiagnostic -and -not $script:AcceptanceDiagnosticInvalid) {'
  )
  if ($tailStart -lt 0) { throw 'Exact receipt tail missing.' }
  $tail = $ast.Extent.Text.Substring($tailStart)
  $childOut = Join-Path $directory 'transport-child.out'
  $childErr = Join-Path $directory 'transport-child.err'
  $preamble = ($helperDefinitions -join "`n`n") + "`n`n" +
    '$script:AcceptanceDiagnostic = $null' + "`n" +
    '$script:AcceptanceDiagnosticInvalid = $false' + "`n" +
    '$childCode = Invoke-PowerShellChild -Command ''exit 3'' -StdoutPath ' +
    (ConvertTo-PowerShellLiteral $childOut) + ' -StderrPath ' +
    (ConvertTo-PowerShellLiteral $childErr) + "`n" +
    '$evidence = [ordered]@{ fixture = $true; childExitCode = $childCode }' + "`n"
  $legacy = Invoke-InputFixture -Source ($preamble + '$go = $false' + "`n`n" + $tail) `
    -Invocation '-Command -'
  if ($legacy.ExitCode -ne 0 -or $legacy.Stdout.Length -ne 0 -or $legacy.Stderr.Length -ne 0) {
    throw 'Legacy stdin EOF regression was not reproduced.'
  }
  if (-not (Test-Path -LiteralPath $childOut)) { throw 'Legacy fixture child did not run.' }
  foreach ($exit in @(0, 1)) {
    $goLiteral = if ($exit -eq 0) { '$true' } else { '$false' }
    $fixed = Invoke-InputFixture -Source (
      $preamble + '$go = ' + $goLiteral + "`n`n" + $tail
    ) -Invocation ('-EncodedCommand ' + $EncodedBootstrap)
    if ($fixed.ExitCode -ne $exit -or $fixed.Stderr.Length -ne 0) {
      throw ('Whole-input bootstrap failed: expectedExit={0}; actualExit={1}; stderrLength={2}' -f
        $exit, $fixed.ExitCode, $fixed.Stderr.Length)
    }
    $marker = 'FAZ24_GPU_ROLLOUT_JSON:'
    $lines = @($fixed.Stdout.Trim() -split "`r?`n")
    if ($lines.Count -ne 1 -or -not $lines[0].StartsWith($marker)) {
      throw 'Whole-input bootstrap lost or duplicated evidence.'
    }
    $json = [Text.Encoding]::UTF8.GetString(
      [Convert]::FromBase64String($lines[0].Substring($marker.Length))
    ) | ConvertFrom-Json
    if ($json.fixture -ne $true -or $json.childExitCode -ne 3) {
      throw 'Receipt did not survive real child invocation.'
    }
  }
  $parseFlag = Join-Path $directory 'must-not-execute.txt'
  $invalidSource = '[IO.File]::WriteAllText(' + (ConvertTo-PowerShellLiteral $parseFlag) +
    ', ''fixture'')' + "`n" + '$broken = @('
  $invalidParse = Invoke-InputFixture -Source $invalidSource `
    -Invocation ('-EncodedCommand ' + $EncodedBootstrap)
  if ($invalidParse.ExitCode -eq 0 -or (Test-Path -LiteralPath $parseFlag)) {
    throw 'Malformed source executed before complete parsing.'
  }
  function Start-Process { [pscustomobject]@{ ExitCode = $null } }
  $rejected = $false
  try {
    $null = Invoke-PowerShellChild -Command 'exit 0' -StdoutPath $output `
      -StderrPath (Join-Path $directory 'stderr')
  } catch { $rejected = $_.Exception.Message -ceq 'child-exit-code-unavailable' }
  if (-not $rejected) { throw 'Null exit code was treated as success.' }
  Write-Output 'PASS Windows PowerShell 5.1 rollout diagnostics'
} finally {
  Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue
}
