param(
  [Parameter(Mandatory = $true)][string]$SourcePath,
  [Parameter(Mandatory = $true)][string]$EncodedBootstrap,
  [Parameter(Mandatory = $true)][string]$RunnerPath,
  [Parameter(Mandatory = $true)][string]$PythonExe
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
  'Invoke-UpdaterChild', 'Invoke-TaskActionMigration', 'ConvertTo-StreamingReadinessMetadata',
  'Get-StreamingReadinessMetadata', 'Test-StreamingReadinessMetadata')
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
  param([string]$Source, [string]$Invocation, [string]$Mode = 'normal')
  $inputPath = Join-Path $env:TEMP ('rollout-input-' + [Guid]::NewGuid().ToString('N') + '.ps1')
  $driver = @'
import base64, gzip, json, pathlib, runpy, subprocess, sys
payload = pathlib.Path(sys.argv[1]).read_bytes()
assert not payload.startswith(b'\xef\xbb\xbf'), 'fixture input must match BOM-free Python transport'
command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
           '-InputFormat', 'Text', '-OutputFormat', 'Text'] + sys.argv[2].split()
mode = sys.argv[4]
if '-EncodedCommand' in command:
    payload = runpy.run_path(sys.argv[3])['encode_remote_input'](payload.decode('utf-8')).encode('ascii')
if mode == 'invalid-base64': payload = b'!invalid!\n'
if mode == 'invalid-gzip': payload = base64.b64encode(b'not-gzip') + b'\n'
if mode == 'invalid-utf8': payload = base64.b64encode(gzip.compress(b'\xff')) + b'\n'
if mode == 'oversize-wire': payload = b'A' * 16385 + b'\n'
if mode == 'oversize-source': payload = base64.b64encode(gzip.compress(b'x' * 131073)) + b'\n'
if mode == 'held-open':
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        process.stdin.write(payload)
        process.stdin.flush()
        process.wait(timeout=20)
        stdout, stderr = process.stdout.read(), process.stderr.read()
        returncode = process.returncode
    finally:
        if process.poll() is None: process.kill(); process.wait()
        process.stdin.close(); process.stdout.close(); process.stderr.close()
else:
    result = subprocess.run(command, input=payload, capture_output=True, timeout=40)
    stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
print(json.dumps({'ExitCode': returncode, 'Stdout': stdout.decode('utf-8'),
                  'Stderr': stderr.decode('utf-8')}))
'@
  try {
    # The real runner uses Python's pipe transport; .NET adds a BOM itself.
    $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($Source)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and
        $bytes[1] -eq 187 -and $bytes[2] -eq 191) { throw 'Fixture payload contains a BOM.' }
    [IO.File]::WriteAllBytes($inputPath, $bytes)
    $result = & $PythonExe -c $driver $inputPath $Invocation $RunnerPath $Mode
    if ($LASTEXITCODE -ne 0) { throw 'Isolated Python transport fixture failed.' }
    return ($result | ConvertFrom-Json)
  } finally { Remove-Item -LiteralPath $inputPath -Force -ErrorAction Stop }
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
      # This is an isolated fake-script process, never runtime output.
      throw ('Whole-input fixture failed: expectedExit={0}; actualExit={1}; stderr={2}' -f
        $exit, $fixed.ExitCode, $fixed.Stderr)
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
  foreach ($size in @(27612, 65536, 131072)) {
    $body = "`nif (`$source.Length -ne $size) { throw 'size-mismatch' }; " +
      "[Console]::Out.WriteLine('SIZE_OK:$size'); exit 0`n"
    $source = '#' + ('x' * ($size - $body.Length - 1)) + $body
    $sized = Invoke-InputFixture -Source $source -Mode 'held-open' `
      -Invocation ('-EncodedCommand ' + $EncodedBootstrap)
    if ($sized.ExitCode -ne 0 -or $sized.Stdout.Trim() -cne "SIZE_OK:$size" -or
        $sized.Stderr.Length -ne 0) { throw 'Bounded frame did not execute before stdin EOF.' }
  }
  # Preserve real source compression complexity, but comment every line so none
  # of the host orchestration can execute in this transport-only fixture.
  $commentedSource = '# ' + ($ast.Extent.Text -replace "`n", "`n# ") +
    "`n[Console]::Out.WriteLine('SOURCE_COMPLEXITY_OK'); exit 0`n"
  $complexFrame = Invoke-InputFixture -Source $commentedSource -Mode 'held-open' `
    -Invocation ('-EncodedCommand ' + $EncodedBootstrap)
  if ($complexFrame.ExitCode -ne 0 -or $complexFrame.Stdout.Trim() -cne 'SOURCE_COMPLEXITY_OK' -or
      $complexFrame.Stderr.Length -ne 0) { throw 'Real-complexity framed transport failed.' }
  foreach ($mode in @('invalid-base64', 'invalid-gzip', 'invalid-utf8',
      'oversize-wire', 'oversize-source')) {
    $invalidFrame = Invoke-InputFixture -Source "[Console]::Out.WriteLine('MUST_NOT_RUN')" `
      -Mode $mode -Invocation ('-EncodedCommand ' + $EncodedBootstrap)
    if ($invalidFrame.ExitCode -eq 0 -or $invalidFrame.Stdout.Length -ne 0) {
      throw "Invalid frame was accepted: $mode"
    }
  }
  function New-ReadyFixture {
    return ('{"status":"ready","runtime_commit":"' + $TargetCommit + '",' +
      '"streaming_preload_enabled":true,"workers_healthy":true,' +
      '"roles":{"live":"ready","final":"ready"},"runtime":{' +
      '"legacy":{"device":"cpu","compute_type":"int8"},' +
      '"live":{"device":"cuda","compute_type":"int8"},' +
      '"final":{"device":"cuda","compute_type":"float16"}},' +
      '"speech_gate":{"profile":"silero-balanced-v1"}}') | ConvertFrom-Json
  }
  function Invoke-WebRequest {
    param([string]$Uri)
    if ($Uri -cne 'http://127.0.0.1:8200/ready') { throw 'Unexpected fixture endpoint.' }
    if ($script:ReadyThrow) { throw 'Fixture request failure.' }
    if ($script:ReadyMalformed) { return [pscustomobject]@{StatusCode=200;Content='{malformed'} }
    return [pscustomobject]@{ StatusCode = $script:ReadyHttpStatus;
      Content = ($script:ReadyResponse | ConvertTo-Json -Depth 6 -Compress) }
  }
  $script:ReadyThrow = $false
  $script:ReadyMalformed = $false
  $script:ReadyHttpStatus = 200
  $script:ReadyResponse = New-ReadyFixture
  $ready = Get-StreamingReadinessMetadata
  if (-not (Test-StreamingReadinessMetadata $ready $TargetCommit)) { throw 'Valid streaming readiness rejected.' }
  foreach ($field in @('streaming_preload_enabled', 'workers_healthy')) {
    foreach ($invalid in @($false, 'true', 1, $null)) {
      $script:ReadyResponse = New-ReadyFixture
      $script:ReadyResponse.$field = $invalid
      $ready = Get-StreamingReadinessMetadata
      if (Test-StreamingReadinessMetadata $ready $TargetCommit) { throw 'Invalid readiness boolean accepted.' }
    }
  }
  foreach ($mutation in @(
    { param($raw) $raw.runtime_commit = 'a' * 40 },
    { param($raw) $raw.status = 'loading' },
    { param($raw) $raw.roles.PSObject.Properties.Remove('final') },
    { param($raw) $raw.runtime.live.device = 'cpu' },
    { param($raw) $raw.runtime.final.device = 'cpu' },
    { param($raw) $raw.runtime.final.compute_type = 'int8' },
    { param($raw) $raw.speech_gate.profile = 'development-unpinned' }
  )) {
    $script:ReadyResponse = New-ReadyFixture
    & $mutation $script:ReadyResponse
    if (Test-StreamingReadinessMetadata (Get-StreamingReadinessMetadata) $TargetCommit) {
      throw 'Invalid streaming runtime metadata accepted.'
    }
  }
  $script:ReadyResponse = New-ReadyFixture
  $script:ReadyHttpStatus = 503
  if (Test-StreamingReadinessMetadata (Get-StreamingReadinessMetadata) $TargetCommit) {
    throw 'Non-200 streaming readiness accepted.'
  }
  $script:ReadyHttpStatus = 200
  $script:ReadyResponse = $null
  if (Test-StreamingReadinessMetadata (Get-StreamingReadinessMetadata) $TargetCommit) {
    throw 'Null streaming readiness accepted.'
  }
  $script:ReadyMalformed = $true
  if (Test-StreamingReadinessMetadata (Get-StreamingReadinessMetadata) $TargetCommit) {
    throw 'Malformed streaming readiness accepted.'
  }
  $script:ReadyMalformed = $false
  $script:ReadyThrow = $true
  if (Test-StreamingReadinessMetadata (Get-StreamingReadinessMetadata) $TargetCommit) {
    throw 'Unavailable streaming readiness accepted.'
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
