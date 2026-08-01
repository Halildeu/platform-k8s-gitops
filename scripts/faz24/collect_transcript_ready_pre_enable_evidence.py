#!/usr/bin/env python3
"""Collect metadata-only live evidence before enabling transcript-ready consumption.

The collector is read-only. PostgreSQL and Redis credentials are accepted only
through process environment variables and are never copied into the evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from transcript_ready_pre_enable_contract import (
    EVIDENCE_SCHEMA,
    ISSUE,
    ContractError,
    binding_set_sha256,
    binding_set_sha256_from_sha1s,
    file_sha256,
    load_policy,
    require_git_sha,
    sensitive_findings,
    sha256_bytes,
    utc_now,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config/faz24-transcript-ready-pre-enable-policy.v1.json"
IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
HOST_MARKER = "FAZ24_TRANSCRIPT_READY_PRE_ENABLE_HOST_JSON:"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], int, dict[str, str] | None], CommandResult]


def run_command(
    argv: Sequence[str], timeout: int, env: dict[str, str] | None = None
) -> CommandResult:
    try:
        result = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(126, "", type(exc).__name__)
    return CommandResult(result.returncode, result.stdout, result.stderr)


def parse_json_output(result: CommandResult, label: str) -> dict[str, Any]:
    if result.returncode != 0:
        raise ContractError(f"{label} command-exit-{result.returncode}")
    try:
        value = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise ContractError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} JSON root must be an object")
    return value


def gitops_commit(runner: CommandRunner, override: str | None) -> str:
    if override:
        return require_git_sha(override, "gitops commit")
    result = runner(["git", "rev-parse", "HEAD"], 10, None)
    if result.returncode != 0:
        raise ContractError("cannot resolve GitOps commit")
    return require_git_sha(result.stdout.strip(), "gitops commit")


def pod_ready(pod: dict[str, Any], container_name: str) -> bool:
    statuses = pod.get("status", {}).get("containerStatuses", [])
    return pod.get("status", {}).get("phase") == "Running" and any(
        item.get("name") == container_name and item.get("ready") is True
        for item in statuses
        if isinstance(item, dict)
    )


def collect_transcript_pod(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    deployment: str,
    timeout: int,
) -> dict[str, Any]:
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/name={deployment}",
            "-o",
            "json",
        ],
        timeout,
        None,
    )
    payload = parse_json_output(result, "kubectl transcript pod inventory")
    candidates = [
        pod
        for pod in payload.get("items", [])
        if isinstance(pod, dict) and pod_ready(pod, deployment)
    ]
    if len(candidates) != 1:
        raise ContractError(
            f"expected exactly one ready transcript-service pod, got {len(candidates)}"
        )
    pod = candidates[0]
    statuses = pod.get("status", {}).get("containerStatuses", [])
    status = next(item for item in statuses if item.get("name") == deployment)
    image_id = str(status.get("imageID", ""))
    match = IMAGE_DIGEST_RE.search(image_id)
    if match is None:
        raise ContractError("transcript-service pod imageID lacks immutable digest")
    metadata = pod.get("metadata", {})
    return {
        "collected": True,
        "name": str(metadata.get("name", "")),
        "uid": str(metadata.get("uid", "")),
        "ready": True,
        "restartCount": int(status.get("restartCount", 0)),
        "imageDigest": match.group(0),
    }


def schema_sql(schema: str) -> str:
    return f"""
SELECT json_build_object(
  'databaseName', current_database(),
  'serverAddress', COALESCE(inet_server_addr()::text, ''),
  'serverPort', inet_server_port(),
  'finalizationTablePresent', to_regclass('{schema}.transcript_finalizations') IS NOT NULL,
  'outboxTablePresent', to_regclass('{schema}.transcript_event_outbox') IS NOT NULL,
  'analysisRunIdColumnPresent', EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = 'transcript_finalizations'
      AND column_name = 'analysis_run_id'
  ),
  'analysisRunIdNotNull', COALESCE((
    SELECT is_nullable = 'NO' FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = 'transcript_finalizations'
      AND column_name = 'analysis_run_id'
  ), FALSE),
  'analysisRunIdUuid', COALESCE((
    SELECT data_type = 'uuid' FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = 'transcript_finalizations'
      AND column_name = 'analysis_run_id'
  ), FALSE),
  'finalizationOccurrenceColumnsPresent', (
    SELECT count(*) = 5 FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = 'transcript_finalizations'
      AND column_name IN ('id', 'tenant_id', 'meeting_id', 'session_id', 'finalization_version')
  ),
  'outboxRequiredColumnsPresent', (
    SELECT count(*) = 8 FROM information_schema.columns
    WHERE table_schema = '{schema}' AND table_name = 'transcript_event_outbox'
      AND column_name IN (
        'event_type', 'payload', 'status', 'lease_expires_at', 'event_key',
        'aggregate_id', 'meeting_id', 'tenant_id'
      )
  )
);
""".strip()


def counts_sql(schema: str) -> str:
    return f"""
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
WITH ready AS (
  SELECT status, lease_expires_at, aggregate_id, meeting_id, tenant_id,
    payload::jsonb AS doc
  FROM {schema}.transcript_event_outbox
  WHERE event_type = 'meeting.transcript.ready'
), classified AS (
  SELECT ready.status, ready.lease_expires_at,
    COALESCE((ready.doc->>'schema' = 'meeting.event.v1'
      AND (NOT (ready.doc ? 'analysisRunId')
        OR jsonb_typeof(ready.doc->'analysisRunId') = 'null')), false) AS legacy,
    COALESCE((ready.doc->>'schema' = 'meeting.event.v1'
      AND ready.doc->>'eventType' = 'meeting.transcript.ready'
      AND ready.doc->>'tenantId' = ready.tenant_id::text
      AND ready.doc->>'meetingId' = ready.meeting_id::text
      AND ready.doc->>'transcriptSessionId' = ready.aggregate_id::text
      AND (ready.doc->>'finalizationVersion') ~ '^[1-9][0-9]*$'
      AND jsonb_typeof(ready.doc->'analysisRunId') = 'string'
      AND (ready.doc->>'analysisRunId') ~
        '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[1-5][0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$'
      AND finalization.id IS NOT NULL
      AND finalization.analysis_run_id::text = ready.doc->>'analysisRunId'), false)
      AS compatible,
    ready.tenant_id::text || '|' || ready.meeting_id::text || '|'
      || ready.aggregate_id::text || '|' || (ready.doc->>'finalizationVersion') || '|'
      || (ready.doc->>'analysisRunId') AS binding
  FROM ready
  LEFT JOIN {schema}.transcript_finalizations AS finalization
    ON finalization.tenant_id = ready.tenant_id
    AND finalization.meeting_id = ready.meeting_id
    AND finalization.session_id = ready.aggregate_id
    AND finalization.finalization_version = CASE
      WHEN jsonb_typeof(ready.doc->'finalizationVersion') = 'number'
        AND (ready.doc->>'finalizationVersion') ~ '^[1-9][0-9]*$'
        THEN (ready.doc->>'finalizationVersion')::bigint
      ELSE NULL
    END
)
SELECT json_build_object(
  'capturedAt', to_char(transaction_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
  'finalizationNullAnalysisRunId', (
    SELECT count(*) FROM {schema}.transcript_finalizations WHERE analysis_run_id IS NULL
  ),
  'legacyOutbox', json_build_object(
    'pending', count(*) FILTER (WHERE legacy AND status = 'PENDING'),
    'claimedActive', count(*) FILTER (
      WHERE legacy AND status = 'CLAIMED' AND lease_expires_at > transaction_timestamp()
    ),
    'claimedStale', count(*) FILTER (
      WHERE legacy AND status = 'CLAIMED'
        AND (lease_expires_at IS NULL OR lease_expires_at <= transaction_timestamp())
    ),
    'dead', count(*) FILTER (WHERE legacy AND status = 'DEAD'),
    'published', count(*) FILTER (WHERE legacy AND status = 'PUBLISHED'),
    'total', count(*) FILTER (WHERE legacy)
  ),
  'malformedReadyOutbox', count(*) FILTER (WHERE NOT legacy AND NOT compatible),
  'compatibleReadyOutbox', count(*) FILTER (WHERE compatible),
  '_compatibleBindings', COALESCE(
    json_agg(binding ORDER BY binding) FILTER (WHERE compatible), '[]'::json
  ),
  'readyOutboxTotal', count(*)
) FROM classified;
COMMIT;
""".strip()


REDIS_LUA = r"""
local stream = KEYS[1]
local target_group = ARGV[1]
local max_entries = tonumber(ARGV[2])
local batch_size = tonumber(ARGV[3])

local function as_map(values)
  local result = {}
  for index = 1, #values, 2 do result[values[index]] = values[index + 1] end
  return result
end

local function lower_uuid(value)
  if type(value) ~= 'string' or string.len(value) ~= 36 then return false end
  if string.sub(value, 9, 9) ~= '-' or string.sub(value, 14, 14) ~= '-'
    or string.sub(value, 19, 19) ~= '-' or string.sub(value, 24, 24) ~= '-' then
    return false
  end
  for index = 1, 36 do
    if index ~= 9 and index ~= 14 and index ~= 19 and index ~= 24 then
      local char = string.sub(value, index, index)
      if not string.find('0123456789abcdef', char, 1, true) then return false end
    end
  end
  return string.find('12345', string.sub(value, 15, 15), 1, true) ~= nil
    and string.find('89ab', string.sub(value, 20, 20), 1, true) ~= nil
end

local function positive_integer(value)
  return type(value) == 'number' and value >= 1 and math.floor(value) == value
end

local info_before = as_map(redis.call('XINFO', 'STREAM', stream))
local length = tonumber(info_before['length']) or 0
local first_id = ''
local last_id = ''
if info_before['first-entry'] then first_id = info_before['first-entry'][1] end
if info_before['last-entry'] then last_id = info_before['last-entry'][1] end

local scanned = 0
local legacy = 0
local malformed = 0
local compatible = 0
local other = 0
local cursor = '-'
local digest = string.rep('0', 40)
local compatible_binding_sha1s = {}

while scanned < length and scanned < max_entries do
  local remaining = math.min(batch_size, max_entries - scanned)
  local rows = redis.call('XRANGE', stream, cursor, '+', 'COUNT', remaining)
  if #rows == 0 then break end
  for _, row in ipairs(rows) do
    local id = row[1]
    local fields = row[2]
    local outer_type = nil
    local payload = nil
    for index = 1, #fields, 2 do
      if fields[index] == 'eventType' then outer_type = fields[index + 1] end
      if fields[index] == 'payload' then payload = fields[index + 1] end
    end
    local decoded = nil
    if payload then pcall(function() decoded = cjson.decode(payload) end) end
    local payload_type = decoded and decoded['eventType'] or nil
    local is_ready = outer_type == 'meeting.transcript.ready'
      or payload_type == 'meeting.transcript.ready'
    local class = 'other'
    if is_ready then
      if not decoded or outer_type ~= 'meeting.transcript.ready'
        or payload_type ~= 'meeting.transcript.ready' then
        malformed = malformed + 1
        class = 'malformed'
      elseif decoded['schema'] == 'meeting.event.v1'
        and (decoded['analysisRunId'] == nil or decoded['analysisRunId'] == cjson.null) then
        legacy = legacy + 1
        class = 'legacy'
      elseif decoded['schema'] == 'meeting.event.v1'
        and lower_uuid(decoded['analysisRunId'])
        and lower_uuid(decoded['tenantId'])
        and lower_uuid(decoded['meetingId'])
        and lower_uuid(decoded['transcriptSessionId'])
        and positive_integer(decoded['finalizationVersion']) then
        compatible = compatible + 1
        class = 'compatible'
        local binding = decoded['tenantId'] .. '|' .. decoded['meetingId'] .. '|'
          .. decoded['transcriptSessionId'] .. '|' .. tostring(decoded['finalizationVersion'])
          .. '|' .. decoded['analysisRunId']
        table.insert(compatible_binding_sha1s, redis.sha1hex(binding))
      else
        malformed = malformed + 1
        class = 'malformed'
      end
    else
      other = other + 1
    end
    digest = redis.sha1hex(digest .. '|' .. id .. '|' .. class)
    scanned = scanned + 1
    cursor = '(' .. id
  end
end

table.sort(compatible_binding_sha1s)

local group = {
  exists = false,
  pending = 0,
  consumers = 0,
  lastDeliveredId = '',
  entriesRead = -1,
  lag = -1
}
for _, values in ipairs(redis.call('XINFO', 'GROUPS', stream)) do
  local item = as_map(values)
  if item['name'] == target_group then
    group.exists = true
    group.pending = tonumber(item['pending']) or 0
    group.consumers = tonumber(item['consumers']) or 0
    group.lastDeliveredId = item['last-delivered-id'] or ''
    group.entriesRead = tonumber(item['entries-read']) or -1
    group.lag = tonumber(item['lag']) or -1
  end
end

local info_after = as_map(redis.call('XINFO', 'STREAM', stream))
local result = {
  length = length,
  firstId = first_id,
  lastId = last_id,
  maxDeletedEntryId = info_before['max-deleted-entry-id'] or '',
  scanned = scanned,
  complete = scanned == length,
  truncated = scanned < length,
  legacyReadyV1 = legacy,
  malformedReady = malformed,
  compatibleReady = compatible,
  _compatibleBindingSha1s = compatible_binding_sha1s,
  otherEvents = other,
  classificationDigestSha1 = digest,
  atomicMetadataStable = tonumber(info_after['length']) == length,
  group = group
}
return cjson.encode(result)
""".strip()


HOST_POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
$RepoRoot = 'C:\platform-ai'
$StatePath = 'C:\ProgramData\Acik\platform-ai\deployment-state.json'
$ConfigPath = 'C:\ProgramData\Acik\platform-ai\meeting-ai.env'
$StartPath = Join-Path $RepoRoot 'deploy\gpu-host\start-meeting-ai.ps1'
$marker = '__STARTUP_GATE_MARKER__'

function Classify-Bool([string]$Value) {
  if ([string]::IsNullOrWhiteSpace($Value)) { return 'unset' }
  if ($Value.Equals('true', [StringComparison]::OrdinalIgnoreCase)) { return 'true' }
  if ($Value.Equals('false', [StringComparison]::OrdinalIgnoreCase)) { return 'false' }
  return 'invalid'
}

$state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$repoHead = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
$startBytes = [IO.File]::ReadAllBytes($StartPath)
try {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $startSha = -join ($sha.ComputeHash($startBytes) | ForEach-Object { $_.ToString('x2') }) }
  finally { $sha.Dispose() }
  $startText = (New-Object Text.UTF8Encoding($false, $true)).GetString($startBytes)
} finally { [Array]::Clear($startBytes, 0, $startBytes.Length) }

$configState = 'absent'
$configMatchCount = 0
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
  foreach ($line in [IO.File]::ReadLines($ConfigPath)) {
    if ($line -match '^\s*MAI_READY_CONSUMER_ENABLED\s*=\s*(.*?)\s*$') {
      $configMatchCount += 1
      if ($configMatchCount -eq 1) { $configState = Classify-Bool $Matches[1] }
      else { $configState = 'invalid' }
    }
  }
}
$machineState = Classify-Bool ([Environment]::GetEnvironmentVariable(
  'MAI_READY_CONSUMER_ENABLED', 'Machine'
))

$health = $null
try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8300/health' -TimeoutSec 10 }
catch { $health = $null }
$ready = if ($null -ne $health) { $health.ready_consumer } else { $null }
$result = [ordered]@{
  computerName = [string]$env:COMPUTERNAME
  platformAiCommit = [string]$state.currentCommit
  repoHeadCommit = $repoHead
  deploymentStateMatch = ([string]$state.currentCommit -eq $repoHead)
  startupScriptSha256 = $startSha
  startupGateMarkerPresent = $startText.Contains($marker)
  runtimeConfigState = $configState
  runtimeConfigMatchCount = $configMatchCount
  machineEnvironmentState = $machineState
  healthReachable = ($null -ne $health)
  healthConsumerPresent = ($null -ne $ready)
  healthEnabled = if ($null -ne $ready) { [bool]$ready.enabled } else { $null }
  healthStatus = if ($null -ne $ready) { [string]$ready.status } else { '' }
  healthWorkerRunning = if ($null -ne $ready) { [bool]$ready.worker_running } else { $null }
  healthRedisGroupReady = if ($null -ne $ready) { [bool]$ready.redis_group_ready } else { $null }
}
Write-Output ('FAZ24_TRANSCRIPT_READY_PRE_ENABLE_HOST_JSON:' + ($result | ConvertTo-Json -Compress))
""".strip()


def psql_env(environment: dict[str, Any]) -> dict[str, str]:
    required = ("PGUSER", "PGPASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ContractError("missing PostgreSQL environment: " + ",".join(missing))
    forbidden = [
        name for name in ("PGSERVICE", "PGSERVICEFILE") if os.environ.get(name)
    ]
    if forbidden:
        raise ContractError("implicit PostgreSQL service config is forbidden")
    env = os.environ.copy()
    env.pop("PSQLRC", None)
    env["PGHOST"] = str(environment["postgresHost"])
    env["PGPORT"] = str(environment["postgresPort"])
    env["PGDATABASE"] = str(environment["postgresDatabase"])
    env["PGSSLMODE"] = str(environment["postgresSslMode"])
    env["PGOPTIONS"] = (
        "-c default_transaction_read_only=on "
        "-c statement_timeout=30000 -c lock_timeout=5000"
    )
    return env


def psql_json(
    runner: CommandRunner,
    sql: str,
    *,
    environment: dict[str, Any],
    timeout: int,
    label: str,
) -> dict[str, Any]:
    result = runner(
        [
            "psql",
            "--no-psqlrc",
            "--quiet",
            "--set",
            "ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--command",
            sql,
        ],
        timeout,
        psql_env(environment),
    )
    return parse_json_output(result, label)


def collect_postgres_snapshot(
    runner: CommandRunner,
    *,
    schema: str,
    environment: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    metadata = psql_json(
        runner,
        schema_sql(schema),
        environment=environment,
        timeout=timeout,
        label="PostgreSQL schema",
    )
    ready = all(
        metadata.get(key) is True
        for key in (
            "finalizationTablePresent",
            "outboxTablePresent",
            "analysisRunIdColumnPresent",
            "analysisRunIdNotNull",
            "analysisRunIdUuid",
            "finalizationOccurrenceColumnsPresent",
            "outboxRequiredColumnsPresent",
        )
    )
    counts = None
    if ready:
        counts = psql_json(
            runner,
            counts_sql(schema),
            environment=environment,
            timeout=timeout,
            label="PostgreSQL counts",
        )
        bindings = counts.pop("_compatibleBindings", None)
        compatible_count = counts.get("compatibleReadyOutbox")
        if not isinstance(bindings, list) or len(bindings) != compatible_count:
            raise ContractError("PostgreSQL compatible binding inventory is invalid")
        if any(not isinstance(value, str) or len(value) > 240 for value in bindings):
            raise ContractError("PostgreSQL compatible binding metadata is invalid")
        legacy = counts.get("legacyOutbox")
        classified = (
            legacy.get("total")
            if isinstance(legacy, dict) and isinstance(legacy.get("total"), int)
            else None
        )
        malformed = counts.get("malformedReadyOutbox")
        ready_total = counts.get("readyOutboxTotal")
        if (
            classified is None
            or isinstance(classified, bool)
            or not isinstance(malformed, int)
            or isinstance(malformed, bool)
            or not isinstance(compatible_count, int)
            or isinstance(compatible_count, bool)
            or not isinstance(ready_total, int)
            or isinstance(ready_total, bool)
            or min(classified, malformed, compatible_count, ready_total) < 0
            or classified + malformed + compatible_count != ready_total
        ):
            raise ContractError("PostgreSQL ready classification is not exhaustive")
        counts["compatibleBindingSetSha256"] = binding_set_sha256(bindings)
    return {"collected": True, "schema": metadata, "counts": counts}


def redis_env() -> dict[str, str]:
    if not os.environ.get("REDISCLI_AUTH"):
        raise ContractError("REDISCLI_AUTH is required")
    return os.environ.copy()


def collect_redis(
    runner: CommandRunner,
    *,
    host: str,
    port: int,
    stream: str,
    group: str,
    max_entries: int,
    timeout: int,
    tls: bool,
) -> dict[str, Any]:
    argv = [
        "redis-cli",
        "--no-auth-warning",
        "--raw",
        "-h",
        host,
        "-p",
        str(port),
    ]
    if tls:
        argv.append("--tls")
    argv.extend(["EVAL_RO", REDIS_LUA, "1", stream, group, str(max_entries), "500"])
    result = runner(argv, timeout, redis_env())
    payload = parse_json_output(result, "Redis atomic stream scan")
    binding_hashes = payload.pop("_compatibleBindingSha1s", None)
    if not isinstance(binding_hashes, list) or len(binding_hashes) != payload.get(
        "compatibleReady"
    ):
        raise ContractError("Redis compatible binding inventory is invalid")
    payload["compatibleBindingSetSha256"] = binding_set_sha256_from_sha1s(
        binding_hashes
    )
    payload["collected"] = True
    payload["host"] = host
    payload["port"] = port
    payload["tls"] = tls
    payload["scriptSha256"] = sha256_bytes(REDIS_LUA.encode("utf-8"))
    return payload


def collect_host(
    runner: CommandRunner,
    *,
    target: str,
    ssh_config: Path,
    startup_marker: str,
    timeout: int,
) -> dict[str, Any]:
    script = HOST_POWERSHELL.replace("__STARTUP_GATE_MARKER__", startup_marker)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = runner(
        [
            "ssh",
            "-F",
            str(ssh_config),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            target,
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        timeout,
        None,
    )
    if result.returncode != 0:
        raise ContractError(f"GPU host probe command-exit-{result.returncode}")
    marker_lines = [
        line[len(HOST_MARKER) :]
        for line in result.stdout.splitlines()
        if line.startswith(HOST_MARKER)
    ]
    if len(marker_lines) != 1:
        raise ContractError("GPU host probe returned no unique metadata marker")
    try:
        payload = json.loads(marker_lines[0])
    except json.JSONDecodeError as exc:
        raise ContractError("GPU host probe marker is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ContractError("GPU host probe marker root must be an object")
    payload["collected"] = True
    payload["probeSha256"] = sha256_bytes(script.encode("utf-8"))
    return payload


def failed_component(exc: Exception) -> dict[str, Any]:
    return {"collected": False, "failureClass": type(exc).__name__}


def contract_sha256(schema: str, startup_marker: str) -> str:
    host_probe = HOST_POWERSHELL.replace("__STARTUP_GATE_MARKER__", startup_marker)
    material = "\n---\n".join(
        (schema_sql(schema), counts_sql(schema), REDIS_LUA, host_probe)
    )
    return sha256_bytes(material.encode("utf-8"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gitops-commit")
    parser.add_argument("--redis-tls", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=45)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        policy = load_policy(args.policy)
        environment = policy["environment"]
        db_schema = environment["postgresSchema"]
        if not IDENTIFIER_RE.fullmatch(db_schema):
            raise ContractError(
                "environment.postgresSchema must be a simple lowercase identifier"
            )
        redis_host = os.environ.get("REDIS_HOST", "")
        redis_port_text = os.environ.get("REDIS_PORT", "")
        if redis_host != environment["redisHost"]:
            raise ContractError("REDIS_HOST must match the policy target")
        if redis_port_text != str(environment["redisPort"]):
            raise ContractError("REDIS_PORT must match the policy target")
        if args.redis_tls is not environment["redisTls"]:
            raise ContractError("Redis TLS mode must match the policy target")
        if not 5 <= args.timeout_seconds <= 60:
            raise ContractError("timeout-seconds must be between 5 and 60")
        git_commit = gitops_commit(run_command, args.gitops_commit)
    except ContractError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2

    failures: list[str] = []
    collection_started_at = utc_now()

    def collect(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            result = operation()
        except (ContractError, OSError, ValueError) as exc:
            failures.append(name)
            result = failed_component(exc)
        result["observedAt"] = utc_now()
        return result

    transcript_pod = collect(
        "transcriptPod",
        lambda: collect_transcript_pod(
            run_command,
            context=environment["kubectlContext"],
            namespace=environment["namespace"],
            deployment=environment["transcriptDeployment"],
            timeout=args.timeout_seconds,
        ),
    )
    pg_before = collect(
        "postgresBefore",
        lambda: collect_postgres_snapshot(
            run_command,
            schema=db_schema,
            environment=environment,
            timeout=args.timeout_seconds,
        ),
    )
    redis = collect(
        "redis",
        lambda: collect_redis(
            run_command,
            host=redis_host,
            port=int(redis_port_text),
            stream=environment["redisStream"],
            group=environment["redisGroup"],
            max_entries=int(policy["redisScanMaxEntries"]),
            timeout=args.timeout_seconds,
            tls=args.redis_tls,
        ),
    )
    pg_after = collect(
        "postgresAfter",
        lambda: collect_postgres_snapshot(
            run_command,
            schema=db_schema,
            environment=environment,
            timeout=args.timeout_seconds,
        ),
    )
    host = collect(
        "gpuHost",
        lambda: collect_host(
            run_command,
            target=environment["gpuHost"],
            ssh_config=Path.home() / ".ssh/config",
            startup_marker=policy["requiredStartupGateMarker"],
            timeout=args.timeout_seconds,
        ),
    )
    collection_finished_at = utc_now()
    evidence: dict[str, Any] = {
        "schemaVersion": EVIDENCE_SCHEMA,
        "generatedAt": collection_finished_at,
        "issue": ISSUE,
        "status": "candidate" if not failures else "collection-blocked",
        "source": {
            "gitopsCommit": git_commit,
            "policySha256": file_sha256(args.policy),
            "queryContractSha256": contract_sha256(
                db_schema, policy["requiredStartupGateMarker"]
            ),
            "collectionStartedAt": collection_started_at,
            "collectionFinishedAt": collection_finished_at,
        },
        "environment": environment,
        "live": {
            "transcriptPod": transcript_pod,
            "postgresBefore": pg_before,
            "redis": redis,
            "postgresAfter": pg_after,
            "gpuHost": host,
        },
        "collectionFailures": failures,
        "boundary": {
            "readOnly": True,
            "consumerEnableAttempted": False,
            "workloadMutationAttempted": False,
            "secretValuesIncluded": False,
            "customerContentIncluded": False,
            "enableAuthorized": False,
        },
    }
    findings = sensitive_findings(evidence)
    if findings:
        print(
            "REJECTED: collector output violated metadata-only boundary",
            file=sys.stderr,
        )
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(args.output, 0o600)
    print(f"WROTE: {args.output} status={evidence['status']}")
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
