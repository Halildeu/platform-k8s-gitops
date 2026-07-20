#!/usr/bin/env node
// tests/ci/test-cross-ai-automation.mjs
//
// #827 — regression test for the automation-PR exemption in
// scripts/ci/pr-cross-ai-audit.mjs. Exercises the REAL script via synthetic
// `--event-path` payloads (no network, no GitHub). Verifies:
//   - a legitimate bot auto-PR (allowlisted branch + bot author + bot sender
//     + body fields) passes
//   - a human is blocked whether they OPEN an auto-* PR (pr.user) or only
//     trigger an event on a bot-opened one (sender) — the actor+sender gate
//   - missing / mismatched automation metadata fails
//   - the per-prefix actor contract is enforced — the bot bound to one prefix
//     cannot claim another (#827 PR-B, Codex 019e4048)
//   - a fork PR cannot claim the exemption
//   - a normal PR still gets the normal cross-AI peer-review audit
//
// Run: node tests/ci/test-cross-ai-automation.mjs   (exit 0 = all pass)
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = join(REPO_ROOT, 'scripts', 'ci', 'pr-cross-ai-audit.mjs');
const ROLLBACK_SCRIPT = join(REPO_ROOT, 'scripts', 'ats', 'open-fullats-test-rollback-pr.sh');
const REPO = 'Halildeu/platform-k8s-gitops';
const BOT = 'github-actions[bot]';
// #827 PR-B — the GitHub App identity bound to the auto-test-overlay/ prefix
// (Codex 019e4048 Q2 — per-prefix actor contract).
const APP_BOT = 'platform-gitops-automation[bot]';
const dir = mkdtempSync(join(tmpdir(), 'crossai-'));
const FETCH_PRELOAD = join(dir, 'github-fetch-preload.mjs');
writeFileSync(FETCH_PRELOAD, `
const fixture = JSON.parse(process.env.CROSS_AI_GITHUB_FIXTURE || '{}');
globalThis.fetch = async (input) => {
  const url = new URL(String(input));
  const page = Number(url.searchParams.get('page') || '1');
  let payload;
  const compareMarker = '/compare/';
  if (url.pathname.includes(compareMarker)) {
    const comparison = decodeURIComponent(url.pathname.split(compareMarker)[1]);
    const head = comparison.split('...')[1];
    const commits = fixture.lineages?.[head] || [];
    payload = {
      total_commits: commits.length,
      commits: page === 1 ? commits.map((sha) => ({ sha })) : [],
    };
  } else if (url.pathname.endsWith('/comments')) {
    payload = [];
  } else if (url.pathname.endsWith('/timeline')) {
    payload = page === 1 ? (fixture.timeline || []) : [];
  } else {
    const statusMatch = url.pathname.match(/\\/commits\\/([0-9a-f]{40})\\/statuses$/i);
    if (statusMatch) payload = page === 1 ? (fixture.statuses?.[statusMatch[1]] || []) : [];
  }
  if (payload === undefined) return { ok: false, status: 404, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => payload };
};
`);
const HEAD_SHA = '0123456789abcdef0123456789abcdef01234567';
const BASE_TIP_SHA = '76543210fedcba9876543210fedcba9876543210';
const BASE_SHA = '89abcdef0123456789abcdef0123456789abcdef';
const SCOPE_SHA256 = 'a'.repeat(64);
const HISTORICAL_TRUSTED_BASE_SHA = '1'.repeat(40);
const REAL_TRUSTED_BASE_SHA = execFileSync('git', ['rev-parse', 'HEAD'], {
  cwd: REPO_ROOT,
  encoding: 'utf8',
}).trim();
const REAL_TRUSTED_BASE_PARENT_SHA = execFileSync('git', ['rev-parse', 'HEAD^'], {
  cwd: REPO_ROOT,
  encoding: 'utf8',
}).trim();
const NOW_MS = Date.now();
const HISTORICAL_CLAUDE_MS = Date.parse('2026-07-19T00:00:00Z');
const HISTORICAL_MINIMAX_MS = Date.parse('2026-07-18T14:00:00Z');
const HISTORICAL_PROVIDER_V1_MS = Date.parse('2026-07-18T23:00:00Z');
const PR_NUMBER = 2690;
const EXECUTION_PROFILE = {
  anthropic: 'claude-cli-no-session-persistence-exact-scope-v1',
  openai: 'codex-exec-ephemeral-read-only-exact-scope-no-tools-v2',
};

const sha256 = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const CURRENT_TRUSTED_SOURCE_DIGESTS = {
  review_harness_sha256: sha256(readFileSync(
    join(REPO_ROOT, 'scripts', 'ai', 'run_isolated_codex_review.py'), 'utf8',
  )),
  scope_preparer_sha256: sha256(readFileSync(
    join(REPO_ROOT, 'scripts', 'ai', 'prepare_cross_ai_scope.py'), 'utf8',
  )),
  pii_attester_sha256: sha256(readFileSync(
    join(REPO_ROOT, 'scripts', 'ai', 'attest_cross_ai_scope_pii.py'), 'utf8',
  )),
  evidence_builder_sha256: sha256(readFileSync(
    join(REPO_ROOT, 'scripts', 'ai', 'build_cross_ai_evidence.py'), 'utf8',
  )),
};
const HISTORICAL_TRUSTED_SOURCE_DIGESTS = {
  review_harness_sha256: '1'.repeat(64),
  scope_preparer_sha256: '2'.repeat(64),
  pii_attester_sha256: '3'.repeat(64),
  evidence_builder_sha256: '4'.repeat(64),
};
const REAL_TRUSTED_SOURCE_DIGESTS = Object.fromEntries(
  Object.entries({
    review_harness_sha256: 'scripts/ai/run_isolated_codex_review.py',
    scope_preparer_sha256: 'scripts/ai/prepare_cross_ai_scope.py',
    pii_attester_sha256: 'scripts/ai/attest_cross_ai_scope_pii.py',
    evidence_builder_sha256: 'scripts/ai/build_cross_ai_evidence.py',
  }).map(([key, path]) => [key, sha256(execFileSync(
    'git', ['show', `${REAL_TRUSTED_BASE_SHA}:${path}`],
    { cwd: REPO_ROOT, encoding: 'utf8' },
  ))]),
);
const REAL_TRUSTED_BASE_PARENT_SOURCE_DIGESTS = Object.fromEntries(
  Object.entries({
    review_harness_sha256: 'scripts/ai/run_isolated_codex_review.py',
    scope_preparer_sha256: 'scripts/ai/prepare_cross_ai_scope.py',
    pii_attester_sha256: 'scripts/ai/attest_cross_ai_scope_pii.py',
    evidence_builder_sha256: 'scripts/ai/build_cross_ai_evidence.py',
  }).map(([key, path]) => [key, sha256(execFileSync(
    'git', ['show', `${REAL_TRUSTED_BASE_PARENT_SHA}:${path}`],
    { cwd: REPO_ROOT, encoding: 'utf8' },
  ))]),
);
const TRUSTED_SOURCE_DIGEST_OVERRIDES = {
  [BASE_TIP_SHA]: CURRENT_TRUSTED_SOURCE_DIGESTS,
  [HISTORICAL_TRUSTED_BASE_SHA]: HISTORICAL_TRUSTED_SOURCE_DIGESTS,
  ['d'.repeat(40)]: CURRENT_TRUSTED_SOURCE_DIGESTS,
};
const sourceActivation = (
  trustedSha = BASE_TIP_SHA,
  sourceDigests = CURRENT_TRUSTED_SOURCE_DIGESTS,
  runId = '12345',
) => ({
  ok: true,
  schema: 'cross-ai-source-trust-activation/v1',
  trusted_sha: trustedSha,
  source_digests: sourceDigests,
  repository: REPO,
  workflow_ref: `${REPO}/.github/workflows/ci.yml@refs/heads/main`,
  event_name: 'push',
  ref: 'refs/heads/main',
  run_id: runId,
  run_attempt: '1',
  activated_at: '2026-07-19T17:30:00Z',
});
const sourceActivationRecovery = (
  trustedSha = BASE_TIP_SHA,
  sourceDigests = CURRENT_TRUSTED_SOURCE_DIGESTS,
  runId = '12345',
) => ({
  ...sourceActivation(trustedSha, sourceDigests, runId),
  schema: 'cross-ai-source-trust-activation/v2',
  workflow_ref: `${REPO}/.github/workflows/gate-cross-ai-audit.yml@refs/heads/main`,
  event_name: 'pull_request_target',
  activation_mode: 'durable-main-status-recovery',
  anchor_sha: trustedSha,
  anchor_status_id: 987,
  anchor_run_id: '7654',
});
const evidenceRef = (id) =>
  `https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/${id}`;
const evidenceBody = (provider, model, response, options = {}) => JSON.stringify({
  schema: provider === 'openai'
    ? 'cross-ai-provider-evidence/v4'
    : 'cross-ai-provider-evidence/v3',
  provider,
  requested_model: model,
  actual_model: provider === 'openai' ? 'not-provider-attested' : model,
  execution_profile: EXECUTION_PROFILE[provider] ?? 'retired-provider-not-accepted',
  execution_provenance: provider === 'openai' ? {
    schema: 'codex-native-execution-provenance/v2',
    thread_id: model === 'gpt-5.3-codex-spark'
      ? '019f7785-c66d-7992-a21a-d4097d9eb3fa'
      : '019f7785-c66d-7992-a21a-d4097d9eb3f9',
    cli_version: '0.144.1',
    cli_native_target: 'codex-linux-x64',
    cli_native_sha256: 'a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902',
    trust_root: 'repo-pinned-codex-native-sha256-v1',
    stderr_classification: 'empty',
    source_trust_root: 'trusted-base-cross-ai-sources-sha256-v1',
    trusted_base_sha: options.trustedBaseSha ?? BASE_TIP_SHA,
    ...(options.sourceDigests ?? CURRENT_TRUSTED_SOURCE_DIGESTS),
    pii_review_status: 'no-sensitive-pii',
    pii_attestation_sha256: 'e'.repeat(64),
  } : null,
  base_tip_sha: options.trustedBaseSha ?? BASE_TIP_SHA,
  base_sha: BASE_SHA,
  head_sha: HEAD_SHA,
  scope_sha256: SCOPE_SHA256,
  verdict: 'AGREE',
  response_sha256: sha256(response),
  response,
});
const evidenceComment = (body, offsetMs = 0, issueNumber = PR_NUMBER) => ({
  body,
  author: 'Halildeu',
  authorAssociation: 'OWNER',
  createdAt: new Date(NOW_MS + offsetMs).toISOString(),
  updatedAt: new Date(NOW_MS + offsetMs).toISOString(),
  issueNumber,
});
const evidenceCommentAt = (body, timestampMs, issueNumber = PR_NUMBER) => ({
  body,
  author: 'Halildeu',
  authorAssociation: 'OWNER',
  createdAt: new Date(timestampMs).toISOString(),
  updatedAt: new Date(timestampMs).toISOString(),
  issueNumber,
});
const evidenceLedgerFromMap = (evidenceMap) => Object.entries(evidenceMap)
  .flatMap(([ref, comment], index) => {
    if (
      comment?.author !== 'Halildeu'
      || comment?.authorAssociation !== 'OWNER'
      || typeof comment?.body !== 'string'
    ) return [];
    let body;
    try {
      body = JSON.parse(comment.body);
    } catch {
      return [];
    }
    if (body?.schema !== 'cross-ai-provider-evidence/v4' || body?.provider !== 'openai') {
      return [];
    }
    return [{
      statusId: index + 1,
      sha: body.head_sha,
      context: `cross-ai/evidence/${sha256(comment.body)}`,
      state: body.verdict === 'AGREE' ? 'success' : 'failure',
      description: `v4 openai ${body.verdict} pr=${comment.issueNumber} thread=${body.execution_provenance?.thread_id}`,
      targetUrl: `https://github.com/${REPO}/pull/${comment.issueNumber}`,
      creator: comment.author,
      createdAt: new Date(Date.parse(comment.createdAt) - 1_000).toISOString(),
      updatedAt: new Date(Date.parse(comment.createdAt) - 1_000).toISOString(),
      ref: `https://api.github.com/repos/${REPO}/statuses/${index + 1}`,
    }];
  });
const CLAUDE_REF = evidenceRef(1001);
const MINIMAX_REF = evidenceRef(1002);
const CODEX_REF = evidenceRef(1003);
const SPARK_REF = evidenceRef(1004);
const EVIDENCE = {
  [CLAUDE_REF]: evidenceCommentAt(
    evidenceBody('anthropic', 'claude-opus-4-8', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'),
    HISTORICAL_CLAUDE_MS,
  ),
  [CODEX_REF]: evidenceComment(evidenceBody('openai', 'gpt-5.6-sol', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'), 2_000),
  [SPARK_REF]: evidenceComment(evidenceBody('openai', 'gpt-5.3-codex-spark', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'), 2_000),
};
const RETRIED_CODEX_REF = evidenceRef(1017);
const RETRIED_EVIDENCE = {
  ...EVIDENCE,
  [RETRIED_CODEX_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 3_000),
};
const CODEX_V3_BODY = (() => {
  const body = JSON.parse(EVIDENCE[CODEX_REF].body);
  body.schema = 'cross-ai-provider-evidence/v3';
  body.execution_provenance = {
    schema: 'codex-native-execution-provenance/v1',
    thread_id: body.execution_provenance.thread_id,
    cli_version: body.execution_provenance.cli_version,
    cli_native_target: body.execution_provenance.cli_native_target,
    cli_native_sha256: body.execution_provenance.cli_native_sha256,
    trust_root: body.execution_provenance.trust_root,
    stderr_classification: body.execution_provenance.stderr_classification,
  };
  return JSON.stringify(body);
})();
const CODEX_V3_REVISE_BODY = (() => {
  const body = JSON.parse(CODEX_V3_BODY);
  const response = '## P0\nNone\n## P1\nHistorical issue\n## P2\nNone\nVERDICT: REVISE';
  body.verdict = 'REVISE';
  body.response = response;
  body.response_sha256 = sha256(response);
  return JSON.stringify(body);
})();
const HISTORICAL_CODEX_V3_EVIDENCE = {
  [evidenceRef(1015)]: evidenceCommentAt(
    CODEX_V3_BODY,
    Date.parse('2026-07-19T17:00:00Z'),
  ),
};
const PRE_ACTIVATION_CODEX_V3_EVIDENCE = {
  [evidenceRef(1016)]: evidenceCommentAt(
    CODEX_V3_BODY,
    Date.parse('2026-07-19T17:10:00Z'),
  ),
};
const PRE_ACTIVATION_CODEX_V3_REVISE_EVIDENCE = {
  [evidenceRef(1021)]: evidenceCommentAt(
    CODEX_V3_REVISE_BODY,
    Date.parse('2026-07-19T17:10:00Z'),
  ),
};
const POST_ACTIVATION_CODEX_V3_EVIDENCE = {
  [evidenceRef(1018)]: evidenceCommentAt(
    CODEX_V3_BODY,
    Date.parse('2026-07-19T17:31:00Z'),
  ),
};
const MINIMAX_V3_BODY = evidenceBody(
  'minimax',
  'minimax/MiniMax-M3',
  '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE',
);
const MINIMAX_V3_EVIDENCE = {
  [MINIMAX_REF]: evidenceComment(MINIMAX_V3_BODY, 1_000),
};
const MINIMAX_V1_BODY = JSON.stringify({
  schema: 'cross-ai-provider-evidence/v1',
  provider: 'minimax',
  requested_model: 'minimax/MiniMax-M3',
  actual_model: 'minimax/MiniMax-M3',
  base_tip_sha: BASE_TIP_SHA,
  base_sha: BASE_SHA,
  head_sha: HEAD_SHA,
  scope_sha256: SCOPE_SHA256,
  verdict: 'AGREE',
  response_sha256: sha256('## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'),
  response: '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE',
});
const MINIMAX_V1_EVIDENCE = {
  [MINIMAX_REF]: evidenceCommentAt(MINIMAX_V1_BODY, HISTORICAL_MINIMAX_MS),
};
const HISTORICAL_CLAUDE_V1_REF = evidenceRef(1010);
const HISTORICAL_CODEX_V1_REF = evidenceRef(1011);
const HISTORICAL_CODEX_V4_REF = evidenceRef(1012);
const historicalV1Body = (provider, model, verdict = 'AGREE') => {
  const response = verdict === 'AGREE'
    ? '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'
    : '## P0\nNone\n## P1\nHistorical binding issue\n## P2\nNone\nVERDICT: REVISE';
  return JSON.stringify({
    schema: 'cross-ai-provider-evidence/v1',
    provider,
    requested_model: model,
    actual_model: model,
    base_tip_sha: BASE_TIP_SHA,
    base_sha: BASE_SHA,
    head_sha: HEAD_SHA,
    scope_sha256: SCOPE_SHA256,
    verdict,
    response_sha256: sha256(response),
    response,
  });
};
const HISTORICAL_PROVIDER_V1_EVIDENCE = {
  [HISTORICAL_CLAUDE_V1_REF]: evidenceCommentAt(
    historicalV1Body('anthropic', 'claude-opus-4-8'),
    HISTORICAL_PROVIDER_V1_MS,
  ),
  [HISTORICAL_CODEX_V1_REF]: evidenceCommentAt(
    historicalV1Body('openai', 'gpt-5.6-sol'),
    HISTORICAL_PROVIDER_V1_MS,
  ),
};
const HISTORICAL_CODEX_V1_REVISE_EVIDENCE = {
  [HISTORICAL_CODEX_V1_REF]: evidenceCommentAt(
    historicalV1Body('openai', 'gpt-5.6-sol', 'REVISE'),
    HISTORICAL_PROVIDER_V1_MS,
  ),
};
const DELETED_V1_MUTATION_LEDGER = [{
  statusId: 8_001,
  sha: HEAD_SHA,
  context: `cross-ai/mutation/1011/deleted`,
  state: 'failure',
  description: `owner comment mutation pr=${PR_NUMBER} comment=1011 action=deleted`,
  targetUrl: `https://github.com/${REPO}/pull/${PR_NUMBER}`,
  creator: 'github-actions[bot]',
  createdAt: '2026-07-19T18:20:00.000Z',
  updatedAt: '2026-07-19T18:20:00.000Z',
  ref: `https://api.github.com/repos/${REPO}/statuses/8001`,
}];
const historicalCodexV4Body = JSON.stringify({
  ...JSON.parse(evidenceBody(
    'openai',
    'gpt-5.6-sol',
    '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE',
    {
      trustedBaseSha: HISTORICAL_TRUSTED_BASE_SHA,
      sourceDigests: HISTORICAL_TRUSTED_SOURCE_DIGESTS,
    },
  )),
  execution_provenance: {
    ...JSON.parse(evidenceBody(
      'openai',
      'gpt-5.6-sol',
      '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE',
      {
        trustedBaseSha: HISTORICAL_TRUSTED_BASE_SHA,
        sourceDigests: HISTORICAL_TRUSTED_SOURCE_DIGESTS,
      },
    )).execution_provenance,
    thread_id: '019f7785-c66d-7992-a21a-d4097d9eb3fd',
  },
});
const HISTORICAL_CODEX_V4_EVIDENCE = {
  [HISTORICAL_CODEX_V4_REF]: evidenceComment(historicalCodexV4Body, 1_500),
};
const realTrustedBaseCodexV4Evidence = {
  [HISTORICAL_CODEX_V4_REF]: evidenceComment(evidenceBody(
    'openai',
    'gpt-5.6-sol',
    '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE',
    {
      trustedBaseSha: REAL_TRUSTED_BASE_SHA,
      sourceDigests: REAL_TRUSTED_SOURCE_DIGESTS,
    },
  ), 1_500),
};
const CURRENT_CODEX_V1_EVIDENCE = {
  [HISTORICAL_CODEX_V1_REF]: evidenceComment(
    historicalV1Body('openai', 'gpt-5.6-sol'),
    1_000,
  ),
};
const INVALID_HISTORICAL_CODEX_V1_EVIDENCE = {
  [HISTORICAL_CODEX_V1_REF]: evidenceCommentAt(
    JSON.stringify({
      ...JSON.parse(historicalV1Body('openai', 'gpt-5.6-sol')),
      response_sha256: 'f'.repeat(64),
    }),
    HISTORICAL_PROVIDER_V1_MS,
  ),
};
const CURRENT_MINIMAX_V1_EVIDENCE = {
  [MINIMAX_REF]: evidenceComment(MINIMAX_V1_BODY, 1_000),
};
const INVALID_HISTORICAL_MINIMAX_V1_EVIDENCE = {
  [MINIMAX_REF]: evidenceCommentAt(
    JSON.stringify({
      ...JSON.parse(MINIMAX_V1_BODY),
      response_sha256: 'f'.repeat(64),
    }),
    HISTORICAL_MINIMAX_MS,
  ),
};
const CURRENT_CLAUDE_V3_EVIDENCE = {
  [CLAUDE_REF]: evidenceComment(
    evidenceBody('anthropic', 'claude-opus-4-8', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'),
    1_000,
  ),
};
const UNREFERENCED_CODEX_REVISE_REF = evidenceRef(1005);
const UNREFERENCED_CODEX_AGREE_REF = evidenceRef(1006);
const codexReviseResponse = '## P0\nNone\n## P1\nFinding\n## P2\nNone\nVERDICT: REVISE';
const codexReviseBody = JSON.stringify({
  ...JSON.parse(evidenceBody('openai', 'gpt-5.6-sol', codexReviseResponse)),
  execution_provenance: {
    ...JSON.parse(evidenceBody('openai', 'gpt-5.6-sol', codexReviseResponse)).execution_provenance,
    thread_id: '019f7785-c66d-7992-a21a-d4097d9eb3fb',
  },
  verdict: 'REVISE',
});
const unresolvedCodexReviseEvidence = {
  ...EVIDENCE,
  [UNREFERENCED_CODEX_REVISE_REF]: evidenceComment(codexReviseBody, 3_000),
};
const PRE_ACTIVATION_V4_REVISE_REF = evidenceRef(1020);
const preActivationV4ReviseEvidence = {
  [PRE_ACTIVATION_V4_REVISE_REF]: evidenceCommentAt(
    codexReviseBody,
    Date.parse('2026-07-19T17:20:00Z'),
  ),
};
const ERASED_OWNER_HISTORY_REF = evidenceRef(1007);
const erasedOwnerHistoryComment = evidenceComment(
  'Routine status note with no remaining evidence fields.',
  3_000,
);
const erasedOwnerHistoryEvidence = {
  ...EVIDENCE,
  [ERASED_OWNER_HISTORY_REF]: {
    ...erasedOwnerHistoryComment,
    updatedAt: new Date(NOW_MS + 4_000).toISOString(),
  },
};
const PRE_ACTIVATION_EDITED_REF = evidenceRef(1019);
const preActivationEditedOwnerHistoryEvidence = {
  ...EVIDENCE,
  [PRE_ACTIVATION_EDITED_REF]: {
    ...evidenceCommentAt(
      codexReviseBody,
      Date.parse('2026-07-19T17:20:00Z'),
    ),
    updatedAt: '2026-07-19T17:25:00.000Z',
  },
};
const resolvedCodexReviseEvidence = {
  ...unresolvedCodexReviseEvidence,
  [UNREFERENCED_CODEX_AGREE_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 4_000),
};
const freshCodexAgreeBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CODEX_REF].body),
  execution_provenance: {
    ...JSON.parse(EVIDENCE[CODEX_REF].body).execution_provenance,
    thread_id: '019f7785-c66d-7992-a21a-d4097d9eb3fc',
  },
});
const freshSelectedCodexReviseEvidence = {
  ...unresolvedCodexReviseEvidence,
  [UNREFERENCED_CODEX_AGREE_REF]: evidenceComment(freshCodexAgreeBody, 4_000),
};
const SAME_SECOND_REVIEW_MS = Date.parse('2026-07-19T18:10:00Z');
const sameSecondSelectedCodexReviseEvidence = {
  ...EVIDENCE,
  [UNREFERENCED_CODEX_REVISE_REF]: evidenceCommentAt(
    codexReviseBody,
    SAME_SECOND_REVIEW_MS,
  ),
  [UNREFERENCED_CODEX_AGREE_REF]: evidenceCommentAt(
    freshCodexAgreeBody,
    SAME_SECOND_REVIEW_MS,
  ),
};
const resolvedSelectedCodexReviseEvidence = {
  ...unresolvedCodexReviseEvidence,
  [CODEX_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 4_000),
};
const historicalClaudeReviseBody = JSON.stringify({
  ...JSON.parse(evidenceBody('anthropic', 'claude-opus-4-8', codexReviseResponse)),
  verdict: 'REVISE',
});
const historicalClaudeReviseEvidence = {
  [CLAUDE_REF]: evidenceCommentAt(historicalClaudeReviseBody, HISTORICAL_CLAUDE_MS),
};
const changedBindingCodexReviseBody = JSON.stringify({
  ...JSON.parse(codexReviseBody),
  execution_provenance: {
    ...JSON.parse(codexReviseBody).execution_provenance,
    trusted_base_sha: 'd'.repeat(40),
  },
  base_tip_sha: 'd'.repeat(40),
  base_sha: 'e'.repeat(40),
  head_sha: 'f'.repeat(40),
  scope_sha256: 'b'.repeat(64),
});
const unresolvedChangedBindingEvidence = {
  ...EVIDENCE,
  [UNREFERENCED_CODEX_REVISE_REF]: evidenceComment(changedBindingCodexReviseBody, 3_000),
};
const resolvedChangedBindingEvidence = {
  ...unresolvedChangedBindingEvidence,
  [CODEX_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 4_000),
};
const differentPrEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 0, PR_NUMBER + 1),
  [CLAUDE_REF]: evidenceComment(EVIDENCE[CLAUDE_REF].body, 0, PR_NUMBER + 1),
};
const agedUnresolvedReviseComment = evidenceComment(codexReviseBody);
agedUnresolvedReviseComment.createdAt = new Date(
  NOW_MS - (8 * 24 * 60 * 60 * 1000),
).toISOString();
agedUnresolvedReviseComment.updatedAt = agedUnresolvedReviseComment.createdAt;
const agedUnresolvedReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: agedUnresolvedReviseComment,
};
const otherPrReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: evidenceComment(
    codexReviseBody, 0, PR_NUMBER + 1,
  ),
};
const editedHistoricalReviseComment = evidenceComment(codexReviseBody, 3_000);
editedHistoricalReviseComment.updatedAt = new Date(NOW_MS + 4_000).toISOString();
const editedHistoricalReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: editedHistoricalReviseComment,
};
const invalidDigestHistoricalReviseBody = JSON.stringify({
  ...JSON.parse(codexReviseBody),
  response_sha256: 'f'.repeat(64),
});
const invalidDigestHistoricalReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: evidenceComment(
    invalidDigestHistoricalReviseBody, 3_000,
  ),
};
const changedProviderHistoricalRevise = JSON.parse(codexReviseBody);
changedProviderHistoricalRevise.provider = 'retired-or-unknown-provider';
const changedProviderHistoricalReviseComment = evidenceComment(
  JSON.stringify(changedProviderHistoricalRevise), 3_000,
);
changedProviderHistoricalReviseComment.updatedAt = new Date(NOW_MS + 4_000).toISOString();
const changedProviderHistoricalReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: changedProviderHistoricalReviseComment,
};
const strippedIdentityHistoricalRevise = JSON.parse(codexReviseBody);
delete strippedIdentityHistoricalRevise.schema;
delete strippedIdentityHistoricalRevise.provider;
const strippedIdentityHistoricalReviseComment = evidenceComment(
  JSON.stringify(strippedIdentityHistoricalRevise), 3_000,
);
strippedIdentityHistoricalReviseComment.updatedAt = new Date(NOW_MS + 4_000).toISOString();
const strippedIdentityHistoricalReviseEvidence = {
  [UNREFERENCED_CODEX_REVISE_REF]: strippedIdentityHistoricalReviseComment,
};
const immutableHistoricalMinimaxV1Evidence = {
  ...MINIMAX_V1_EVIDENCE,
};
const immutableHistoricalMinimaxV3Evidence = {
  ...MINIMAX_V3_EVIDENCE,
};
const editedHistoricalMinimaxV1Comment = {
  ...MINIMAX_V1_EVIDENCE[MINIMAX_REF],
  updatedAt: new Date(NOW_MS + 5_000).toISOString(),
};
const editedHistoricalMinimaxV1Evidence = {
  [MINIMAX_REF]: editedHistoricalMinimaxV1Comment,
};
const nonOwnerEvidenceRef = evidenceRef(1007);
const nonOwnerJsonEvidence = {
  [nonOwnerEvidenceRef]: {
    ...evidenceComment(codexReviseBody, 3_000),
    author: 'mallory',
    authorAssociation: 'CONTRIBUTOR',
  },
};
const nonOwnerRawEvidence = {
  [nonOwnerEvidenceRef]: {
    ...evidenceComment(
      'cross-ai-provider-evidence/v3 base_tip_sha head_sha verdict REVISE',
      3_000,
    ),
    author: 'mallory',
    authorAssociation: 'NONE',
  },
};
const SOL_RECEIPT_SPARK_EVIDENCE = {
  ...EVIDENCE,
  [CODEX_REF]: evidenceComment(EVIDENCE[SPARK_REF].body, 2_000),
};
// Historical dual records remain read-only fixtures; they are never selectable.
const REVERSED_DUAL_CODEX_EVIDENCE = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(EVIDENCE[CLAUDE_REF].body, 2_000),
  [CODEX_REF]: evidenceComment(EVIDENCE[CODEX_REF].body, 0),
};

// Build the GitHub event payload and run the real script; return its exit code.
// `changedFiles` is an optional array → written to a temp file and passed via
// `--changed-files-file`. `undefined` skips the flag entirely (older workflows
// and the normal peer-review audit don't need it). `[]` writes an empty file
// (fail-closed via dependabot_changed_files_present).
function runCase({ branch, actor, sender, headRepo = REPO, headSha = HEAD_SHA, baseSha = BASE_TIP_SHA, body, draft = false, changedFiles, automationAttestation, evidence = EVIDENCE, includeEvidenceOverride = true, evidenceLedger, includeEvidenceLedgerOverride = true, sourceActivationAttestation, includeSourceActivationAttestation = true, activationRunId, trustedSourceDigests = TRUSTED_SOURCE_DIGEST_OVERRIDES, includeTrustedSourceOverride = true, derivedBaseSha = BASE_SHA, derivedScopeSha256 = SCOPE_SHA256, githubActions = false, allowLocalOverride = 'true', expectedFailureCheck, githubApiFixture }) {
  const event = {
    pull_request: {
      number: PR_NUMBER,
      body,
      head: { ref: branch, sha: headSha, repo: { full_name: headRepo } },
      base: { sha: baseSha, repo: { full_name: REPO } },
      user: { login: actor },
      draft,
    },
    sender: { login: sender ?? actor },
  };
  const f = join(dir, 'ev.json');
  writeFileSync(f, JSON.stringify(event));
  const cmdArgs = [
    SCRIPT,
    '--event-path',
    f,
    '--allow-local-evidence-override',
    allowLocalOverride,
    '--derived-base-sha',
    derivedBaseSha,
    '--derived-scope-sha256',
    derivedScopeSha256,
  ];
  if (includeTrustedSourceOverride) {
    const trustedSourceDigestsFile = join(dir, 'trusted-source-digests.json');
    writeFileSync(trustedSourceDigestsFile, JSON.stringify(trustedSourceDigests));
    cmdArgs.push('--trusted-source-digests-file', trustedSourceDigestsFile);
  }
  if (includeEvidenceOverride) {
    const evidenceFile = join(dir, 'evidence.json');
    writeFileSync(evidenceFile, JSON.stringify(evidence));
    cmdArgs.push('--evidence-file', evidenceFile);
  }
  if (includeEvidenceOverride && includeEvidenceLedgerOverride) {
    const evidenceLedgerFile = join(dir, 'evidence-ledger.json');
    writeFileSync(
      evidenceLedgerFile,
      JSON.stringify(evidenceLedger ?? evidenceLedgerFromMap(evidence)),
    );
    cmdArgs.push('--evidence-ledger-file', evidenceLedgerFile);
  }
  if (includeSourceActivationAttestation) {
    const effectiveSourceDigests = trustedSourceDigests?.[baseSha]
      ?? (baseSha === REAL_TRUSTED_BASE_SHA
        ? REAL_TRUSTED_SOURCE_DIGESTS
        : CURRENT_TRUSTED_SOURCE_DIGESTS);
    const effectiveActivation = sourceActivationAttestation
      ?? sourceActivation(baseSha, effectiveSourceDigests);
    const activationFile = join(dir, 'source-activation.json');
    writeFileSync(activationFile, JSON.stringify(effectiveActivation));
    cmdArgs.push(
      '--activation-attestation-file', activationFile,
      '--activation-run-id', activationRunId ?? effectiveActivation.run_id,
    );
  }
  if (Array.isArray(changedFiles)) {
    const cf = join(dir, 'changed-files.txt');
    writeFileSync(cf, changedFiles.join('\n'));
    cmdArgs.push('--changed-files-file', cf);
  }
  if (automationAttestation !== undefined) {
    const af = join(dir, 'automation-content-attestation.json');
    writeFileSync(af, JSON.stringify(automationAttestation));
    cmdArgs.push('--automation-content-attestation-file', af);
  }
  try {
    const childEnv = { ...process.env };
    if (githubActions) childEnv.GITHUB_ACTIONS = 'true';
    else delete childEnv.GITHUB_ACTIONS;
    if (githubApiFixture) {
      childEnv.NODE_OPTIONS = `--import=${FETCH_PRELOAD}`;
      childEnv.CROSS_AI_GITHUB_FIXTURE = JSON.stringify(githubApiFixture);
    }
    execFileSync('node', cmdArgs, { stdio: 'pipe', env: childEnv });
    return 0;
  } catch (e) {
    const status = e.status ?? -1;
    if (process.env.CROSS_AI_TEST_DEBUG === 'true') {
      const output = `${e.stdout ?? ''}${e.stderr ?? ''}`;
      process.stderr.write(`\n[cross-ai test debug]\n${output}\n`);
    }
    if (expectedFailureCheck) {
      const output = `${e.stdout ?? ''}${e.stderr ?? ''}`;
      return output.includes(`✗ ${expectedFailureCheck}`) ? status : -2;
    }
    return status;
  }
}

const autoBody = (src) =>
  `## Summary\nauto\n\n## Cross-AI\n` +
  `Automation source: ${src}\n` +
  `Cross-AI exempt reason: Machine-generated rollout-verified PR; no AI peer-review claim is made.\n` +
  `Automation evidence: https://github.com/Halildeu/platform-k8s-gitops/actions/runs/123\n`;

const rollbackScriptSource = readFileSync(ROLLBACK_SCRIPT, 'utf8');
const rollbackBodyMatch = rollbackScriptSource.match(/body="\$\(cat <<'EOF'\n([\s\S]*?)\nEOF\n\)"/u);
if (!rollbackBodyMatch) throw new Error('rollback PR body heredoc not found');
const renderedRollbackBody = rollbackBodyMatch[1]
  .replaceAll('__PROMOTION_PR__', '2636')
  .replaceAll('__RUN_URL__', 'https://github.com/Halildeu/platform-k8s-gitops/actions/runs/123')
  .replaceAll('__FAILED_SHA__', HEAD_SHA);

const MINIMAX_RECEIPT_LINE =
  `MiniMax receipt: provider=minimax; requested=minimax/MiniMax-M3; actual=minimax/MiniMax-M3; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${MINIMAX_REF}; sha256=${sha256(MINIMAX_V3_BODY)}`;
const legacyPeerBody =
  `## Summary\nx\n\n## Cross-AI\n` +
  `Implementer AI: Claude\nReviewer AI: Codex\n` +
  `Codex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n` +
  `Consultation base tip: ${BASE_TIP_SHA}\n` +
  `Consultation base: ${BASE_SHA}\n` +
  `Consultation commit: ${HEAD_SHA}\n` +
  `Consultation scope: ${SCOPE_SHA256}\n` +
  `Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; execution=claude-cli-no-session-persistence-exact-scope-v1; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CLAUDE_REF}; sha256=${sha256(EVIDENCE[CLAUDE_REF].body)}\n` +
  `Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=not-provider-attested; execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CODEX_REF}; sha256=${sha256(EVIDENCE[CODEX_REF].body)}\n`;

const explicitNoneBody =
  `## Cross-AI\n` +
  `Implementer AI: Codex\n` +
  `Consultation mode: none\n` +
  `Consultation reason: Routine implementation and automated tests do not need external consultation.\n`;
const explicitSingleBody =
  `## Cross-AI\n` +
  `Implementer AI: Codex\n` +
  `Consultation mode: single\n` +
  `Consultation tier: high-impact\n` +
  `Consultation reason: One isolated Codex architecture review is sufficient for this reversible decision.\n` +
  `Verdict: AGREE\n` +
  `Consultation base tip: ${BASE_TIP_SHA}\n` +
  `Consultation base: ${BASE_SHA}\n` +
  `Consultation commit: ${HEAD_SHA}\n` +
  `Consultation scope: ${SCOPE_SHA256}\n` +
  `Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=not-provider-attested; execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CODEX_REF}; sha256=${sha256(EVIDENCE[CODEX_REF].body)}\n`;
const replayedSelectedCodexBody = explicitSingleBody.replace(
  CODEX_REF,
  UNREFERENCED_CODEX_AGREE_REF,
);
const freshSelectedCodexBody = explicitSingleBody
  .replace(CODEX_REF, UNREFERENCED_CODEX_AGREE_REF)
  .replace(sha256(EVIDENCE[CODEX_REF].body), sha256(freshCodexAgreeBody));
const explicitSparkSingleBody = explicitSingleBody.replace(
  'Consultation tier: high-impact',
  'Consultation tier: routine',
).replace(
  /^Codex receipt:.*$/m,
  `Codex receipt: provider=openai; requested=gpt-5.3-codex-spark; actual=not-provider-attested; execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${SPARK_REF}; sha256=${sha256(EVIDENCE[SPARK_REF].body)}`,
);
const explicitRoutineSolBody = explicitSingleBody.replace(
  'Consultation tier: high-impact',
  'Consultation tier: routine',
);
const solReceiptSparkEvidenceBody = explicitSingleBody.replace(
  sha256(EVIDENCE[CODEX_REF].body),
  sha256(EVIDENCE[SPARK_REF].body),
);
const explicitDualBody =
  explicitSingleBody
    .replace('Consultation mode: single', 'Consultation mode: dual')
    .replace(
      'Consultation reason: One isolated Codex architecture review is sufficient for this reversible decision.',
      'Consultation reason: An optional Claude challenger is justified by the irreversible decision.',
    ) +
  `Risk trigger: irreversible-production: Production security boundary with named human authority.\n` +
  `Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; execution=claude-cli-no-session-persistence-exact-scope-v1; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CLAUDE_REF}; sha256=${sha256(EVIDENCE[CLAUDE_REF].body)}\n`;
// All current acceptance/evidence tests use the explicit forward contract.
// The old fixture remains only for explicit legacy-rejection coverage.
const peerBody = explicitSingleBody;
const explicitDualMiniMaxBody = explicitDualBody.replace(
  /^Claude receipt:.*$/m,
  MINIMAX_RECEIPT_LINE,
);
const explicitDualClaudeImplementerBody = explicitDualBody.replace(
  'Implementer AI: Codex',
  'Implementer AI: Claude',
);
const explicitDualMiniMaxWrongCodexDigestBody = explicitDualMiniMaxBody.replace(
  sha256(EVIDENCE[CODEX_REF].body),
  'f'.repeat(64),
);
// Claude + Codex (the valid dual pair) plus a retired MiniMax receipt appended.
// The forward policy fail-closes on the MiniMax field regardless of the two
// otherwise-valid channels.
const explicitDualClaudeCodexMiniMaxBody =
  `${explicitDualBody}${MINIMAX_RECEIPT_LINE}\n`;
// none / single explicit-mode bodies carrying a retired MiniMax receipt.
const explicitNoneMiniMaxBody =
  `${explicitNoneBody}${MINIMAX_RECEIPT_LINE}\n`;
const explicitSingleMiniMaxBody =
  `${explicitSingleBody}${MINIMAX_RECEIPT_LINE}\n`;
const ROUTINE_PATH = 'docs/operations/RUNBOOKS/RB-routine-update.md';
const GOVERNANCE_PATH = 'AGENTS.md';
const GATE_WORKFLOW_PATH = '.github/workflows/gate-cross-ai-audit.yml';
const ACTIVATION_WORKFLOW_PATH = '.github/workflows/ci.yml';
const ENFORCEMENT_PATH = 'scripts/ci/pr-cross-ai-audit.mjs';
const ACTIVATION_VERIFIER_PATH = 'scripts/ai/verify_cross_ai_source_activation.py';
const AUDIT_COMPLETION_PATH = 'scripts/ai/complete_cross_ai_audit_status.py';
const ACTIVATION_MARKER_PATH = 'scripts/ai/cross_ai_source_activation_marker.json';
const ACTIVATION_TEST_PATH = 'tests/ai/test_verify_cross_ai_source_activation.py';
const RETIRED_MINIMAX_WRAPPER_PATH = 'scripts/ai/minimax_m3_review.py';
const RBAC_PATH = 'kustomize/base/security/clusterrolebinding-platform-admin.yaml';
const MIGRATION_PATH = 'services/reporting/src/main/resources/db/migration/V42__grant.sql';
const HARMLESS_RBAC_DOC_PATH = 'docs/rbac-overview.md';
const GOVERNANCE_CONTRACT_TEST_PATH = 'tests/deploy/test_faz25_fullats_gitops_contract.py';

const staleClaudeBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  head_sha: 'f'.repeat(40),
});
const staleEvidence = { ...EVIDENCE, [CLAUDE_REF]: evidenceComment(staleClaudeBody) };
const staleEvidencePeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(staleClaudeBody),
);
const nonIsolatedCodexBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CODEX_REF].body),
  execution_profile: 'codex-current-chat',
});
const nonIsolatedCodexEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: evidenceComment(nonIsolatedCodexBody),
};
const nonIsolatedCodexReceiptBody = explicitSingleBody.replace(
  sha256(EVIDENCE[CODEX_REF].body),
  sha256(nonIsolatedCodexBody),
);
const overclaimedActualCodexBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CODEX_REF].body),
  actual_model: 'gpt-5.6-sol',
});
const overclaimedActualCodexEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: evidenceComment(overclaimedActualCodexBody),
};
const overclaimedActualCodexReceiptBody = explicitSingleBody
  .replace('actual=not-provider-attested', 'actual=gpt-5.6-sol')
  .replace(
    sha256(EVIDENCE[CODEX_REF].body),
    sha256(overclaimedActualCodexBody),
  );
const unpinnedNativeCodexBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CODEX_REF].body),
  execution_provenance: {
    ...JSON.parse(EVIDENCE[CODEX_REF].body).execution_provenance,
    cli_native_sha256: 'f'.repeat(64),
  },
});
const unpinnedNativeCodexEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: evidenceComment(unpinnedNativeCodexBody),
};
const unpinnedNativeCodexReceiptBody = explicitSingleBody.replace(
  sha256(EVIDENCE[CODEX_REF].body),
  sha256(unpinnedNativeCodexBody),
);
const reviseResponse = '## P0\nFinding\n## P1\nNone\n## P2\nNone\nVERDICT: REVISE';
const contradictoryClaudeBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  verdict: 'AGREE',
  response_sha256: sha256(reviseResponse),
  response: reviseResponse,
});
const contradictoryEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(contradictoryClaudeBody),
};
const contradictoryPeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(contradictoryClaudeBody),
);
const editedEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: {
    ...EVIDENCE[CLAUDE_REF],
    updatedAt: new Date(Date.now() + 60_000).toISOString(),
  },
};
const agedEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: {
    ...EVIDENCE[CLAUDE_REF],
    createdAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
    updatedAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString(),
  },
};
const wrongAuthorEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: {
    ...EVIDENCE[CLAUDE_REF],
    author: 'mallory',
  },
};
const wrongAssociationEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: {
    ...EVIDENCE[CLAUDE_REF],
    authorAssociation: 'MEMBER',
  },
};
const outOfOrderEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: {
    ...EVIDENCE[CODEX_REF],
    createdAt: new Date(NOW_MS - 1_000).toISOString(),
    updatedAt: new Date(NOW_MS - 1_000).toISOString(),
  },
};
const equalTimestampEvidence = {
  ...EVIDENCE,
  [CODEX_REF]: {
    ...EVIDENCE[CODEX_REF],
    createdAt: EVIDENCE[CLAUDE_REF].createdAt,
    updatedAt: EVIDENCE[CLAUDE_REF].updatedAt,
  },
};
const minimaxReviseResponse = '## P0\nNone\n## P1\nFinding\n## P2\nNone\nVERDICT: REVISE';
const minimaxReviseBody = JSON.stringify({
  ...JSON.parse(MINIMAX_V3_BODY),
  verdict: 'REVISE',
  response_sha256: sha256(minimaxReviseResponse),
  response: minimaxReviseResponse,
});
const minimaxReviseEvidence = {
  ...EVIDENCE,
  [MINIMAX_REF]: evidenceComment(minimaxReviseBody),
};
const emptySectionsResponse = 'P0\nP1\nP2\nVERDICT: AGREE';
const emptySectionsClaudeBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(emptySectionsResponse),
  response: emptySectionsResponse,
});
const emptySectionsEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(emptySectionsClaudeBody),
};
const emptySectionsPeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(emptySectionsClaudeBody),
);
const agreeWithP1FindingResponse = 'P0\nNone\nP1\nHigh finding\nP2\nNone\nVERDICT: AGREE';
const agreeWithP1FindingBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(agreeWithP1FindingResponse),
  response: agreeWithP1FindingResponse,
});
const agreeWithP1FindingEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(agreeWithP1FindingBody),
};
const agreeWithP1FindingPeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(agreeWithP1FindingBody),
);
const sensitiveResponse = 'P0\nNone\nP1\nNone\nP2\nperson@example.com\nVERDICT: AGREE';
const sensitiveBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(sensitiveResponse),
  response: sensitiveResponse,
});
const sensitiveEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(sensitiveBody),
};
const sensitivePeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(sensitiveBody),
);
const rawBearerResponse = 'P0\nNone\nP1\nNone\nP2\nBearer ' + 'abcdefghijklmnop\nVERDICT: AGREE';
const rawBearerBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(rawBearerResponse),
  response: rawBearerResponse,
});
const rawBearerEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(rawBearerBody),
};
const rawBearerPeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(rawBearerBody),
);
const highConfidenceSensitiveFixtures = [
  ['JWT', 'eyJ' + 'a'.repeat(16) + '.' + 'b'.repeat(16) + '.' + 'c'.repeat(16)],
  ['known API key', 'ghp_' + 'a'.repeat(30)],
  ['secret assignment', 'password=' + 'a'.repeat(16)],
  ['AWS secret assignment', 'secret_access_key=' + 'a'.repeat(32)],
  ['service-account secret assignment', 'service_account_key=' + 'a'.repeat(32)],
  ['webhook URL', 'webhook_url=https://example.invalid/' + 'a'.repeat(20)],
  ['cookie header', 'Cookie: session=' + 'a'.repeat(20)],
].map(([label, value]) => {
  const response = `P0\nNone\nP1\nNone\nP2\n${value}\nVERDICT: AGREE`;
  const body = JSON.stringify({
    ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
    response_sha256: sha256(response),
    response,
  });
  return [label, {
    body: peerBody.replace(
      sha256(EVIDENCE[CLAUDE_REF].body),
      sha256(body),
    ),
    evidence: {
      ...EVIDENCE,
      [CLAUDE_REF]: evidenceComment(body),
    },
  }];
});
const nonExactNoneResponse = 'P0\nnOnE\nP1\nNone\nP2\nNone\nVERDICT: AGREE';
const nonExactNoneBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(nonExactNoneResponse),
  response: nonExactNoneResponse,
});
const nonExactNoneEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(nonExactNoneBody),
};
const nonExactNonePeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(nonExactNoneBody),
);
const lowercaseVerdictResponse = 'P0\nNone\nP1\nNone\nP2\nNone\nVERDICT: agree';
const lowercaseVerdictBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[CLAUDE_REF].body),
  response_sha256: sha256(lowercaseVerdictResponse),
  response: lowercaseVerdictResponse,
});
const lowercaseVerdictEvidence = {
  ...EVIDENCE,
  [CLAUDE_REF]: evidenceComment(lowercaseVerdictBody),
};
const lowercaseVerdictPeerBody = peerBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
  sha256(lowercaseVerdictBody),
);

const WF = '.github/workflows/deploy-backend-testai.yml';
const FRONTEND_WF = '.github/workflows/deploy-testai.yml';
const FULLATS_ROLLBACK_WF = '.github/workflows/faz25-fullats-live-browser-acceptance.yml';
const LEDGER = 'scripts/promotion/ledger-mark-verified.sh';
const SCAN = 'scripts/promotion/scan-promotion-candidates.sh';
const PRIMARY_OVERLAY = 'kustomize/overlays/test/kustomization.yaml';
const FULLATS_STATE = 'kustomize/overlays/test/fullats-promotion-state.txt';
const FULLATS_ROLLBACK_FILES = [FULLATS_STATE, PRIMARY_OVERLAY];
const FULLATS_ATTESTATION = {
  schema: 'fullats-rollback-content-attestation/v1',
  valid: true,
  source: FULLATS_ROLLBACK_WF,
  branch: 'auto-fullats-rollback/faz25-fullats-123-1',
  base_sha: BASE_TIP_SHA,
  head_sha: HEAD_SHA,
  promotion_pr: 2636,
  promotion_merge_sha: BASE_TIP_SHA,
  promotion_head_sha: 'b'.repeat(40),
  promotion_base_sha: 'aa93f4743dc8254ce8e22a0317f92db1f5819268',
  promotion_scope_sha256: 'c'.repeat(64),
  changed_diff_sha256: 'd'.repeat(64),
  expected_paths: FULLATS_ROLLBACK_FILES,
};
const VERIFIED_LEDGER = `release-candidates/platform-backend/${'a'.repeat(40)}.json`;
const HIDDEN_REVISE_H1 = '1'.repeat(40);
const HIDDEN_REVISE_H2 = '2'.repeat(40);
const HIDDEN_REVISE_DIGEST = '3'.repeat(64);
const HIDDEN_REVISE_THREAD = '019f7785-c66d-7992-a21a-d4097d9eb3fd';
const TWO_STEP_FORCE_PUSH_FIXTURE = {
  timeline: [{
    event: 'head_ref_force_pushed',
    before_commit: HIDDEN_REVISE_H2,
    after_commit: HEAD_SHA,
  }],
  lineages: {
    [HIDDEN_REVISE_H2]: [HIDDEN_REVISE_H1, HIDDEN_REVISE_H2],
    [HEAD_SHA]: [HEAD_SHA],
  },
  statuses: {
    [HIDDEN_REVISE_H1]: [{
      id: 9001,
      context: `cross-ai/evidence/${HIDDEN_REVISE_DIGEST}`,
      state: 'failure',
      description: `v4 openai REVISE pr=${PR_NUMBER} thread=${HIDDEN_REVISE_THREAD}`,
      target_url: `https://github.com/${REPO}/pull/${PR_NUMBER}`,
      creator: { login: 'Halildeu' },
      created_at: new Date(NOW_MS + 5_000).toISOString(),
      updated_at: new Date(NOW_MS + 5_000).toISOString(),
      url: `https://api.github.com/repos/${REPO}/statuses/9001`,
    }],
  },
};

// #898 — Dependabot bot PR exemption (Codex `019e4517` AGREE).
// Dependabot doesn't fill the Cross-AI body fields; the exemption is gated by
// (branch prefix + same-repo + dual-actor + changed-file allowlist), all of
// which the audit reads from event payload + injected changed-files file.
const DEPENDABOT_BOT = 'dependabot[bot]';
const dependabotBody =
  `## Summary\nBumps actions/setup-node from 4 to 6.\n\n` +
  `Dependabot release notes elided for brevity.\n`;

const cases = [
  ['valid automation PR (auto-test-overlay, App-bot author + App-bot sender)',
    { branch: 'auto-test-overlay/backend-testai-live', actor: APP_BOT, sender: APP_BOT, body: autoBody(WF), changedFiles: [PRIMARY_OVERLAY] }, 0],
  ['valid automation exemption cannot bypass an unresolved Codex REVISE',
    { branch: 'auto-test-overlay/backend-testai-live', actor: APP_BOT, sender: APP_BOT,
      body: autoBody(WF), changedFiles: [PRIMARY_OVERLAY],
      evidence: unresolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['automation lane can resolve a REVISE only with a valid selected fresh Codex AGREE',
    { branch: 'auto-test-overlay/backend-testai-live', actor: APP_BOT, sender: APP_BOT,
      body: `${autoBody(WF)}${freshSelectedCodexBody.replace(/^## Cross-AI\n/u, '')}`,
      changedFiles: [PRIMARY_OVERLAY], evidence: freshSelectedCodexReviseEvidence }, 0],
  ['valid frontend desired-state PR (auto-test-frontend, App-bot)',
    { branch: 'auto-test-frontend/testai', actor: APP_BOT, sender: APP_BOT, body: autoBody(FRONTEND_WF), changedFiles: [PRIMARY_OVERLAY] }, 0],
  ['valid Full ATS two-file frontend rollback PR (App-bot)',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES, automationAttestation: FULLATS_ATTESTATION }, 0],
  ['live Full ATS rollback script body passes automation audit',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: renderedRollbackBody, changedFiles: FULLATS_ROLLBACK_FILES, automationAttestation: FULLATS_ATTESTATION }, 0],
  ['Full ATS rollback without trusted content attestation -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES }, 1],
  ['Full ATS rollback with attestation bound to a different head -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES, automationAttestation: { ...FULLATS_ATTESTATION, head_sha: 'e'.repeat(40) } }, 1],
  ['Full ATS rollback with non-exact attested path set -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES, automationAttestation: { ...FULLATS_ATTESTATION, expected_paths: [...FULLATS_ROLLBACK_FILES, '.github/workflows/ci.yml'] } }, 1],
  ['Full ATS rollback with extra self-authored attestation field -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES, automationAttestation: { ...FULLATS_ATTESTATION, claimed: 'pass' } }, 1],
  ['valid auto-verified PR (bot)',
    { branch: 'auto-verified/test-20260519', actor: BOT, sender: BOT, body: autoBody(LEDGER), changedFiles: [VERIFIED_LEDGER] }, 0],
  ['auto-promotion draft cannot claim an automation exemption',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: autoBody(SCAN) }, 1],
  ['auto-promotion accepts the required isolated Codex SOL receipt',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: explicitSingleBody, changedFiles: [SCAN] }, 0],
  ['#827 PR-B: auto-test-overlay + github-actions[bot] (wrong bot for prefix) -> blocked',
    { branch: 'auto-test-overlay/x', actor: BOT, sender: BOT, body: autoBody(WF) }, 1],
  ['#2295: auto-test-frontend + github-actions[bot] (wrong bot for prefix) -> blocked',
    { branch: 'auto-test-frontend/x', actor: BOT, sender: BOT, body: autoBody(FRONTEND_WF) }, 1],
  ['#2295: auto-test-frontend with backend workflow source -> blocked',
    { branch: 'auto-test-frontend/x', actor: APP_BOT, sender: APP_BOT, body: autoBody(WF), changedFiles: [PRIMARY_OVERLAY] }, 1],
  ['#2295: auto-test-frontend with unrelated changed file -> blocked',
    { branch: 'auto-test-frontend/x', actor: APP_BOT, sender: APP_BOT, body: autoBody(FRONTEND_WF), changedFiles: [PRIMARY_OVERLAY, '.github/workflows/ci.yml'] }, 1],
  ['#2295: auto-test-frontend without changed-file evidence -> blocked',
    { branch: 'auto-test-frontend/x', actor: APP_BOT, sender: APP_BOT, body: autoBody(FRONTEND_WF) }, 1],
  ['Full ATS rollback with unrelated workflow change -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: [...FULLATS_ROLLBACK_FILES, '.github/workflows/ci.yml'] }, 1],
  ['Full ATS rollback with wrong automation source -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: APP_BOT, body: autoBody(FRONTEND_WF), changedFiles: FULLATS_ROLLBACK_FILES }, 1],
  ['Full ATS rollback with human sender -> blocked',
    { branch: 'auto-fullats-rollback/faz25-fullats-123-1', actor: APP_BOT, sender: 'mallory', body: autoBody(FULLATS_ROLLBACK_WF), changedFiles: FULLATS_ROLLBACK_FILES }, 1],
  ['#827 PR-B: auto-verified + platform-gitops-automation[bot] (wrong bot for prefix) -> blocked',
    { branch: 'auto-verified/x', actor: APP_BOT, sender: APP_BOT, body: autoBody(LEDGER) }, 1],
  ['auto-verified touching governance outside its ledger family -> blocked',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, body: autoBody(LEDGER), changedFiles: [VERIFIED_LEDGER, 'AGENTS.md'] }, 1],
  ['auto-verified without changed-file evidence -> blocked',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, body: autoBody(LEDGER) }, 1],
  ['App-bot-opened auto-PR + HUMAN sender (synchronize bypass) -> blocked',
    { branch: 'auto-test-overlay/backend-testai-live', actor: APP_BOT, sender: 'mallory', body: autoBody(WF), changedFiles: [PRIMARY_OVERLAY] }, 1],
  ['human-opened auto-* branch -> blocked',
    { branch: 'auto-test-overlay/sneaky', actor: 'mallory', sender: 'mallory', body: autoBody(WF), changedFiles: [PRIMARY_OVERLAY] }, 1],
  ['auto-* + bot, missing Automation source -> fail',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT,
      body: '## Cross-AI\nCross-AI exempt reason: machine PR no review claim\nAutomation evidence: https://x/y/z\n' }, 1],
  ['auto-* + bot, wrong source for prefix -> fail',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, body: autoBody(WF) }, 1],
  ['fork PR on auto-* branch -> blocked',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, headRepo: 'mallory/platform-k8s-gitops', body: autoBody(LEDGER) }, 1],
  ['normal PR + valid peer review -> normal audit pass',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['draft PR cannot produce required audit success',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, draft: true, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'pr_ready_for_review' }, 1],
  ['normal PR accepts durable main-status activation recovery',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, changedFiles: [ROUTINE_PATH], sourceActivationAttestation: sourceActivationRecovery() }, 0],
  ['durable activation recovery rejects a non-exact-base anchor',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, changedFiles: [ROUTINE_PATH], sourceActivationAttestation: { ...sourceActivationRecovery(), anchor_sha: '9'.repeat(40) }, expectedFailureCheck: 'cross_ai_source_trust_activation' }, 1],
  ['two-step force-push history still discovers an ancestor REVISE tombstone',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: {},
      includeEvidenceLedgerOverride: false,
      githubApiFixture: TWO_STEP_FORCE_PUSH_FIXTURE,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['normal PR without successful exact-base source activation -> blocked',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, changedFiles: [ROUTINE_PATH],
      includeSourceActivationAttestation: false,
      expectedFailureCheck: 'cross_ai_source_trust_activation' }, 1],
  ['normal PR with a non-main source activation context -> blocked',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, changedFiles: [ROUTINE_PATH],
      sourceActivationAttestation: {
        ...sourceActivation(),
        ref: 'refs/heads/staging',
      },
      expectedFailureCheck: 'cross_ai_source_trust_activation' }, 1],
  ['normal PR with source activation before ledger policy introduction -> blocked',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, changedFiles: [ROUTINE_PATH],
      sourceActivationAttestation: {
        ...sourceActivation(),
        activated_at: '2026-07-19T17:00:00Z',
      },
      expectedFailureCheck: 'cross_ai_source_trust_activation' }, 1],
  ['normal PR with a future source activation timestamp -> blocked',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, changedFiles: [ROUTINE_PATH],
      sourceActivationAttestation: {
        ...sourceActivation(),
        activated_at: '2099-01-01T00:00:00Z',
      },
      expectedFailureCheck: 'cross_ai_source_trust_activation' }, 1],
  ['legacy receipt body cannot produce current acceptance',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: legacyPeerBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_explicit_mode_required' }, 1],
  ['explicit none mode lets routine work pass without provider receipts',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['none mode ignores an immutable pre-retirement Claude REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: historicalClaudeReviseEvidence }, 0],
  ['none mode ignores immutable pre-retirement Claude and OpenAI v1 AGREE records',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: HISTORICAL_PROVIDER_V1_EVIDENCE }, 0],
  ['none mode cannot hide an immutable pre-retirement OpenAI v1 REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: HISTORICAL_CODEX_V1_REVISE_EVIDENCE,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['historical Codex v4 evidence uses producer digests from its own trusted base',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: HISTORICAL_CODEX_V4_EVIDENCE }, 0],
  ['historical Codex v4 evidence resolves producer bytes from a real git commit',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      baseSha: REAL_TRUSTED_BASE_SHA, body: explicitNoneBody,
      changedFiles: [ROUTINE_PATH], evidence: realTrustedBaseCodexV4Evidence,
      includeTrustedSourceOverride: false }, 0],
  ['historical Codex v4 evidence rejects a trusted base outside PR-base ancestry',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      baseSha: REAL_TRUSTED_BASE_PARENT_SHA, body: explicitNoneBody,
      changedFiles: [ROUTINE_PATH], evidence: realTrustedBaseCodexV4Evidence,
      includeTrustedSourceOverride: false,
      sourceActivationAttestation: sourceActivation(
        REAL_TRUSTED_BASE_PARENT_SHA,
        REAL_TRUSTED_BASE_PARENT_SOURCE_DIGESTS,
      ),
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['none mode rejects a post-retirement OpenAI v1 record',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: CURRENT_CODEX_V1_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['none mode rejects malformed historical OpenAI v1 audit data',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: INVALID_HISTORICAL_CODEX_V1_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['none mode rejects a new Claude v3 receipt-shaped record',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: CURRENT_CLAUDE_V3_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['none mode keeps pre-ledger OpenAI v3 as read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: HISTORICAL_CODEX_V3_EVIDENCE }, 0],
  ['none mode keeps OpenAI v3 before verified source activation as read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: PRE_ACTIVATION_CODEX_V3_EVIDENCE }, 0],
  ['none mode keeps pre-activation OpenAI v3 REVISE as read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: PRE_ACTIVATION_CODEX_V3_REVISE_EVIDENCE }, 0],
  ['none mode keeps ledgerless OpenAI v4 before verified source activation as read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: preActivationV4ReviseEvidence, evidenceLedger: [] }, 0],
  ['none mode rejects OpenAI v3 created after verified source activation',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: POST_ACTIVATION_CODEX_V3_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['none mode cannot hide an unreferenced same-head Codex REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: unresolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['none mode cannot hide a deleted Codex REVISE with an immutable status tombstone',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: EVIDENCE,
      evidenceLedger: evidenceLedgerFromMap({
        ...EVIDENCE,
        ...unresolvedCodexReviseEvidence,
      }),
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['none mode cannot hide a deleted retired v1 REVISE after mutation guard tombstone',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH], evidence: {},
      evidenceLedger: DELETED_V1_MUTATION_LEDGER,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['none mode ignores a status tombstone created before verified source activation',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: EVIDENCE,
      evidenceLedger: [
        ...evidenceLedgerFromMap(EVIDENCE),
        {
          statusId: 7000,
          sha: HEAD_SHA,
          context: `cross-ai/evidence/${sha256(codexReviseBody)}`,
          state: 'failure',
          description: `v4 openai REVISE pr=${PR_NUMBER} thread=${JSON.parse(codexReviseBody).execution_provenance.thread_id}`,
          targetUrl: `https://github.com/${REPO}/pull/${PR_NUMBER}`,
          creator: 'Halildeu',
          createdAt: '2026-07-19T17:20:00.000Z',
          updatedAt: '2026-07-19T17:20:00.000Z',
          ref: `https://api.github.com/repos/${REPO}/statuses/7000`,
        },
      ] }, 0],
  ['none mode keeps an aged ledgerless REVISE predating source activation as read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: agedUnresolvedReviseEvidence }, 0],
  ['a REVISE on another PR does not contaminate this PR history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: otherPrReviseEvidence }, 0],
  ['an edited historical REVISE candidate fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: editedHistoricalReviseEvidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an owner comment edited after evidence immutability activation fails closed even after evidence fields are erased',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: erasedOwnerHistoryEvidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an owner evidence comment edited before verified source activation has no authority',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: preActivationEditedOwnerHistoryEvidence }, 0],
  ['an invalid-digest historical REVISE candidate fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: invalidDigestHistoricalReviseEvidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an edited historical REVISE with changed provider fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: changedProviderHistoricalReviseEvidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an edited historical REVISE with stripped identity fields fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: strippedIdentityHistoricalReviseEvidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an immutable retired MiniMax v1 record remains read-only history',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: immutableHistoricalMinimaxV1Evidence }, 0],
  ['a post-retirement MiniMax v1 record fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: CURRENT_MINIMAX_V1_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['a malformed pre-retirement MiniMax v1 record fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: INVALID_HISTORICAL_MINIMAX_V1_EVIDENCE,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['a new MiniMax v3 history record fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: immutableHistoricalMinimaxV3Evidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['an edited retired MiniMax v1 record fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: editedHistoricalMinimaxV1Evidence,
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['non-owner JSON evidence-like history cannot poison the gate',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: nonOwnerJsonEvidence }, 0],
  ['non-owner raw evidence-like history cannot poison the gate',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH],
      evidence: nonOwnerRawEvidence }, 0],
  ['explicit none mode accepts substantive prose containing the word none',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody.replace(/^Consultation reason:.*$/m, 'Consultation reason: Reversible documentation update; none of the protected runtime paths apply.'),
      changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit none mode rejects a fabricated or stale provider receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}${explicitDualBody.match(/^Claude receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects an empty provider receipt key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Claude receipt:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects decorative consultation binding fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Consultation scope: ${SCOPE_SHA256}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects consultation governance changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [GOVERNANCE_PATH] }, 1],
  ['explicit none mode rejects the Cross-AI gate workflow path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [GATE_WORKFLOW_PATH] }, 1],
  ['explicit none mode rejects the Cross-AI activation workflow path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ACTIVATION_WORKFLOW_PATH] }, 1],
  ['explicit none mode rejects the Cross-AI activation verifier',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ACTIVATION_VERIFIER_PATH] }, 1],
  ['explicit none mode rejects the Cross-AI audit completion helper',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [AUDIT_COMPLETION_PATH] }, 1],
  ['explicit none mode rejects the Cross-AI activation marker',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ACTIVATION_MARKER_PATH] }, 1],
  ['explicit none mode rejects Cross-AI Python contract tests',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ACTIVATION_TEST_PATH] }, 1],
  ['explicit none mode rejects consultation governance contract-test changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [GOVERNANCE_CONTRACT_TEST_PATH] }, 1],
  ['explicit none mode rejects production promotion branch',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects missing changed-file metadata',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody }, 1],
  ['explicit single mode also rejects missing changed-file metadata',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody }, 1],
  ['invalid explicit consultation mode fails closed without legacy fallback',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody.replace('Consultation mode: none', 'Consultation mode: sngle'), changedFiles: [ROUTINE_PATH] }, 1],
  ['empty explicit consultation mode fails closed even with complete legacy receipts',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody.replace('Consultation mode: none', 'Consultation mode:')}${legacyPeerBody.split('## Cross-AI\n')[1]}`,
      changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects untouched template placeholder',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody.replace(/^Consultation reason:.*$/m, 'Consultation reason: <neden none seçildi>'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects ignored legacy controls',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Reviewer AI: Codex\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects an empty legacy control key',
    // Empty values remain present in extractFields so explicit-mode legacy
    // keys cannot disappear merely by omitting their value.
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Reviewer AI:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['field-aware selection prefers a complete explicit-mode section',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `## Cross-AI\nsummary without structured fields\n\n${explicitNoneBody}`, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit single mode accepts exact context-isolated Codex evidence',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit single mode coalesces an exact status-first status/comment retry',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidence: RETRIED_EVIDENCE,
      evidenceLedger: evidenceLedgerFromMap(RETRIED_EVIDENCE) }, 0],
  ['explicit single mode rejects a conflicting status retry for one digest',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidenceLedger: (() => {
        const statuses = evidenceLedgerFromMap(EVIDENCE);
        const status = statuses.find(
          (candidate) => candidate.context === `cross-ai/evidence/${sha256(EVIDENCE[CODEX_REF].body)}`,
        );
        return [...statuses, {
          ...status,
          state: 'failure',
          description: status.description.replace('AGREE', 'REVISE'),
          ref: `https://api.github.com/repos/${REPO}/statuses/conflict`,
          createdAt: new Date(Date.parse(status.createdAt) + 1_000).toISOString(),
          updatedAt: new Date(Date.parse(status.createdAt) + 1_000).toISOString(),
        }];
      })(),
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['explicit single mode rejects a selected receipt without an immutable ledger status',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidenceLedger: [],
      expectedFailureCheck: 'consultation_selected_receipts_ledgered' }, 1],
  ['selected receipt rejects an equal-timestamp ledger with unproven publication order',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidenceLedger: evidenceLedgerFromMap(EVIDENCE).map((status) => (
        status.context === `cross-ai/evidence/${sha256(EVIDENCE[CODEX_REF].body)}`
          ? { ...status,
              createdAt: EVIDENCE[CODEX_REF].createdAt,
              updatedAt: EVIDENCE[CODEX_REF].createdAt }
          : status
      )),
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['selected receipt rejects a ledger created after its owner comment',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidenceLedger: evidenceLedgerFromMap(EVIDENCE).map((status) => {
        if (status.context !== `cross-ai/evidence/${sha256(EVIDENCE[CODEX_REF].body)}`) {
          return status;
        }
        const afterComment = new Date(
          Date.parse(EVIDENCE[CODEX_REF].createdAt) + 1_000,
        ).toISOString();
        return { ...status, createdAt: afterComment, updatedAt: afterComment };
      }),
      expectedFailureCheck: 'consultation_evidence_history_valid' }, 1],
  ['explicit single mode rejects a missing consultation tier',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace(/^Consultation tier:.*\n/m, ''), changedFiles: [ROUTINE_PATH],
      expectedFailureCheck: 'consultation_tier_valid' }, 1],
  ['single mode ignores an immutable pre-retirement Claude REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidence: { ...EVIDENCE, ...historicalClaudeReviseEvidence } }, 0],
  ['single mode cannot hide an unreferenced same-head Codex REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidence: unresolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['an unselected same-provider AGREE cannot resolve a REVISE in single mode',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidence: resolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['a reposted selected AGREE cannot resolve a later REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: replayedSelectedCodexBody, changedFiles: [ROUTINE_PATH],
      evidence: resolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['a newly executed selected AGREE resolves a prior REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: freshSelectedCodexBody, changedFiles: [ROUTINE_PATH],
      evidence: freshSelectedCodexReviseEvidence }, 0],
  ['a same-second selected AGREE resolves a REVISE only through a larger status id',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: freshSelectedCodexBody, changedFiles: [ROUTINE_PATH],
      evidence: sameSecondSelectedCodexReviseEvidence }, 0],
  ['a same-second selected AGREE with an older status id cannot resolve a REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: freshSelectedCodexBody, changedFiles: [ROUTINE_PATH],
      evidence: sameSecondSelectedCodexReviseEvidence,
      evidenceLedger: (() => {
        const statuses = evidenceLedgerFromMap(sameSecondSelectedCodexReviseEvidence);
        const reviseDigest = sha256(codexReviseBody);
        const agreeDigest = sha256(freshCodexAgreeBody);
        return statuses.map((status) => {
          if (status.context === `cross-ai/evidence/${reviseDigest}`) {
            return {
              ...status,
              statusId: 9200,
              ref: `https://api.github.com/repos/${REPO}/statuses/9200`,
            };
          }
          if (status.context === `cross-ai/evidence/${agreeDigest}`) {
            return {
              ...status,
              statusId: 9100,
              ref: `https://api.github.com/repos/${REPO}/statuses/9100`,
            };
          }
          return status;
        });
      })(),
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['a newly executed selected AGREE resolves a historical OpenAI v1 REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: freshSelectedCodexBody, changedFiles: [ROUTINE_PATH],
      evidence: {
        ...freshSelectedCodexReviseEvidence,
        ...HISTORICAL_CODEX_V1_REVISE_EVIDENCE,
      } }, 0],
  ['a forbidden dual mode cannot resolve a prior REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody, changedFiles: [ROUTINE_PATH],
      evidence: resolvedSelectedCodexReviseEvidence }, 1],
  ['a prior-head REVISE remains unresolved after PR head and scope change',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH],
      evidence: unresolvedChangedBindingEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['a forbidden dual current-head AGREE cannot resolve a prior-head REVISE',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody, changedFiles: [ROUTINE_PATH],
      evidence: resolvedChangedBindingEvidence }, 1],
  ['explicit single mode rejects SOL receipt bound to Spark evidence',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: solReceiptSparkEvidenceBody, changedFiles: [GOVERNANCE_PATH],
      evidence: SOL_RECEIPT_SPARK_EVIDENCE, expectedFailureCheck: 'codex_receipt' }, 1],
  ['explicit single mode accepts Spark for a routine voluntary consultation',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSparkSingleBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit routine tier rejects SOL instead of silently escalating models',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitRoutineSolBody, changedFiles: [ROUTINE_PATH],
      expectedFailureCheck: 'consultation_codex_model_tier' }, 1],
  ['explicit single mode rejects routine tier for a governance path floor',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSparkSingleBody, changedFiles: [GOVERNANCE_PATH], expectedFailureCheck: 'consultation_tier_meets_scope_floor' }, 1],
  ['explicit single mode rejects Spark when the author declares high-impact on a neutral path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSparkSingleBody.replace('Consultation tier: routine', 'Consultation tier: high-impact'),
      changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_codex_model_tier' }, 1],
  ['explicit single mode rejects Spark for consultation governance changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSparkSingleBody, changedFiles: ['AGENTS.md'], expectedFailureCheck: 'consultation_codex_model_tier' }, 1],
  ['explicit single mode rejects Spark for the Cross-AI gate workflow path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSparkSingleBody, changedFiles: [GATE_WORKFLOW_PATH], expectedFailureCheck: 'consultation_codex_model_tier' }, 1],
  ['explicit single mode rejects a receipt without the exact execution profile',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace('; execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2', ''), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects evidence from the current non-isolated Codex chat',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: nonIsolatedCodexReceiptBody, changedFiles: [ROUTINE_PATH], evidence: nonIsolatedCodexEvidence }, 1],
  ['explicit single mode rejects a provider-attested actual-model overclaim',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: overclaimedActualCodexReceiptBody, changedFiles: [ROUTINE_PATH], evidence: overclaimedActualCodexEvidence, expectedFailureCheck: 'codex_receipt' }, 1],
  ['explicit single mode rejects evidence from an unpinned native binary',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: unpinnedNativeCodexReceiptBody, changedFiles: [ROUTINE_PATH], evidence: unpinnedNativeCodexEvidence, expectedFailureCheck: 'codex_receipt' }, 1],
  ['explicit single mode accepts consultation governance changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [GOVERNANCE_PATH] }, 0],
  ['explicit single SOL mode accepts the Cross-AI gate workflow path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [GATE_WORKFLOW_PATH] }, 0],
  ['an active evidence publication lease fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}\n<!-- cross-ai-publication-lock:${'a'.repeat(64)}:${'b'.repeat(64)} -->\n`,
      changedFiles: [GATE_WORKFLOW_PATH],
      expectedFailureCheck: 'cross_ai_publication_lock_absent' }, 1],
  ['explicit single mode accepts consultation enforcement changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [ENFORCEMENT_PATH] }, 0],
  ['retired MiniMax wrapper tombstone accepts exact single review',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [RETIRED_MINIMAX_WRAPPER_PATH] }, 0],
  ['retired MiniMax wrapper deletion rejects forbidden dual review',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [RETIRED_MINIMAX_WRAPPER_PATH] }, 1],
  ['explicit dual mode is rejected for consultation enforcement changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ENFORCEMENT_PATH] }, 1],
  ['explicit none mode rejects a high-confidence RBAC path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [RBAC_PATH] }, 1],
  ['explicit single mode accepts a high-confidence RBAC path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [RBAC_PATH] }, 0],
  ['explicit none mode rejects a high-confidence database migration path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [MIGRATION_PATH] }, 1],
  ['explicit none mode accepts a harmless RBAC-named documentation path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [HARMLESS_RBAC_DOC_PATH] }, 0],
  ['explicit single mode accepts same-provider Codex with process isolation',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit single mode rejects an unidentifiable other implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace('Implementer AI: Codex', 'Implementer AI: other'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate consultation-mode fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Consultation mode: single\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate consultation-tier fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Consultation tier: high-impact\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate implementer fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Implementer AI: Codex\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate receipt fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}${explicitSingleBody.match(/^Codex receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects duplicate risk-trigger fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitDualBody}Risk trigger: security-authz: Duplicate security authority must not override prior classification.\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects non-AGREE verdict',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace('Verdict: AGREE', 'Verdict: REVISE'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects missing exact scope binding',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace(/^Consultation scope:.*\n/m, ''), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects a second consultation channel',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}${explicitDualBody.match(/^Claude receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects an empty risk-trigger key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Risk trigger:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects Codex primary plus Claude challenger',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects MiniMax as a retired secondary channel',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects the Codex+Claude pair for a Codex implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects the Codex+Claude pair for a Claude implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualClaudeImplementerBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode remains rejected with reverse evidence publication timestamps',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH], evidence: REVERSED_DUAL_CODEX_EVIDENCE }, 1],
  ['explicit dual mode rejects a Claude+Codex+MiniMax three-channel mixture',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualClaudeCodexMiniMaxBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_has_no_forbidden_challenger_receipt' }, 1],
  ['explicit none mode rejects a retired MiniMax receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects a retired MiniMax receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects an empty third receipt key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitDualBody}MiniMax receipt:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['invalid MiniMax dual still validates the present allowlisted Codex receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualMiniMaxWrongCodexDigestBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_mode_valid' }, 1],
  ['explicit dual mode requires a concrete high-risk trigger',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody.replace(/^Risk trigger:.*\n/m, ''), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects unclassified free-form risk trigger',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody.replace(/^Risk trigger:.*$/m, 'Risk trigger: aaaaaaaaaa'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects unknown risk category',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody.replace(/^Risk trigger:.*$/m, 'Risk trigger: nonexistent-cat: Concrete production boundary would be irreversible'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects categorized placeholder detail',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody.replace(/^Risk trigger:.*$/m, 'Risk trigger: security-authz: placeholder'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects categorized repeated todo detail',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitDualBody.replace(/^Risk trigger:.*$/m, 'Risk trigger: human-authority: todo todo todo'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects three consultation channels',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitDualBody}${MINIMAX_RECEIPT_LINE}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['GitHub Actions mode rejects offline evidence-file override',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, githubActions: true }, 1],
  ['GitHub Actions mode rejects trusted-source digest override',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [ROUTINE_PATH], githubActions: true,
      includeEvidenceOverride: false }, 1],
  ['local evidence-file requires explicit test override flag',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, allowLocalOverride: 'false' }, 1],
  ['normal PR + missing required consultation receipts -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n' }, 1],
  ['normal legacy PR + empty required field still fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: legacyPeerBody.replace('Reviewer AI: Codex', 'Reviewer AI:'), changedFiles: [ROUTINE_PATH] }, 1],
  ['normal PR + metadata-only head change reuses byte-identical reviewed scope',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      headSha: 'fedcba9876543210fedcba9876543210fedcba98', body: peerBody,
      changedFiles: [ROUTINE_PATH] }, 0],
  ['normal PR + MiniMax receipt is forbidden even with an actual-model mismatch',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${peerBody}${MINIMAX_RECEIPT_LINE.replace('actual=minimax/MiniMax-M3', 'actual=minimax/MiniMax-M2.7')}\n` }, 1],
  ['normal PR + Claude non-AGREE receipt -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(`verdict=AGREE; ref=${CLAUDE_REF}`, `verdict=REVISE; ref=${CLAUDE_REF}`) }, 1],
  ['normal PR + arbitrary receipt ref -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(CLAUDE_REF, 'old-ref-123') }, 1],
  ['normal PR + evidence ref points to a different repository -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(CLAUDE_REF, 'https://api.github.com/repos/other/repo/issues/comments/1001') }, 1],
  ['normal PR + fetched evidence belongs to a different PR -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: differentPrEvidence, expectedFailureCheck: 'codex_receipt' }, 1],
  ['normal PR + malformed receipt digest -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(sha256(EVIDENCE[CLAUDE_REF].body), 'not-a-sha256') }, 1],
  ['normal PR + well-formed but wrong evidence body digest -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(sha256(EVIDENCE[CLAUDE_REF].body), 'f'.repeat(64)) }, 1],
  ['normal PR + stale evidence internal head with matching body digest -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: staleEvidencePeerBody, evidence: staleEvidence }, 1],
  ['normal PR + evidence says AGREE but response terminal verdict is REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: contradictoryPeerBody, evidence: contradictoryEvidence }, 1],
  ['normal PR + edited evidence comment -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: editedEvidence }, 1],
  ['normal PR + evidence older than seven days -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: agedEvidence }, 1],
  ['normal PR + evidence author differs from repository owner -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: wrongAuthorEvidence }, 1],
  ['normal PR + owner login without OWNER association -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: wrongAssociationEvidence }, 1],
  ['normal PR + reverse two-provider evidence timestamps remain accepted',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: outOfOrderEvidence, changedFiles: [ROUTINE_PATH] }, 0],
  ['normal PR + pre-activation Codex v4 cannot gain authority from an equal timestamp',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: equalTimestampEvidence, changedFiles: [ROUTINE_PATH],
      expectedFailureCheck: 'consultation_selected_receipts_ledgered' }, 1],
  ['normal PR + duplicate provider evidence refs -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(CODEX_REF, CLAUDE_REF) }, 1],
  ['Claude/Codex AGREE plus forbidden MiniMax REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${peerBody}${MINIMAX_RECEIPT_LINE.replace(sha256(MINIMAX_V3_BODY), sha256(minimaxReviseBody))}\n`, evidence: minimaxReviseEvidence }, 1],
  ['provider response with empty P0/P1/P2 sections -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: emptySectionsPeerBody, evidence: emptySectionsEvidence }, 1],
  ['provider response says AGREE while P1 contains a finding -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: agreeWithP1FindingPeerBody, evidence: agreeWithP1FindingEvidence }, 1],
  ['provider response contains PII -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: sensitivePeerBody, evidence: sensitiveEvidence }, 1],
  ['provider response contains raw bearer without Authorization prefix -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: rawBearerPeerBody, evidence: rawBearerEvidence }, 1],
  ...highConfidenceSensitiveFixtures.map(([label, fixture]) => [
    `provider response contains ${label} -> fail closed`,
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', ...fixture },
    1,
  ]),
  ['provider AGREE uses a non-exact None sentinel -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: nonExactNonePeerBody, evidence: nonExactNoneEvidence }, 1],
  ['provider terminal verdict uses lowercase agree -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: lowercaseVerdictPeerBody, evidence: lowercaseVerdictEvidence }, 1],
  ['receipt verdict uses lowercase agree -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(`verdict=AGREE; ref=${CLAUDE_REF}`, `verdict=agree; ref=${CLAUDE_REF}`) }, 1],
  ['PR top-level verdict uses lowercase agree -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: agree') }, 1],
  ['auto-verified ledger outside the three canonical product families -> blocked',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, body: autoBody(LEDGER),
      changedFiles: [`release-candidates/fake-product/${'a'.repeat(40)}.json`] }, 1],
  ['normal PR + event base tip mismatch -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      baseSha: 'fedcba9876543210fedcba9876543210fedcba98', body: peerBody }, 1],
  ['normal PR + receipt merge-base mismatch -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(`base=${BASE_SHA}`, `base=${'e'.repeat(40)}`) }, 1],
  ['normal PR + receipt scope mismatch -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(`scope=${SCOPE_SHA256}`, `scope=${'e'.repeat(64)}`) }, 1],
  ['normal PR + missing event head SHA -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', headSha: '', body: peerBody }, 1],
  ['normal PR + missing CI-derived merge-base -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', derivedBaseSha: '', body: peerBody }, 1],
  ['normal PR + missing CI-derived scope digest -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', derivedScopeSha256: '', body: peerBody }, 1],
  ['normal PR + overall REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: REVISE') }, 1],
  ['normal PR + overall PARTIAL -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: PARTIAL') }, 1],
  ['normal PR + overall RED -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: RED') }, 1],
  ['normal PR + overall tracked_pending -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: tracked_pending') }, 1],
  ['normal PR + compound AGREE_REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: AGREE_REVISE') }, 1],
  ['normal PR + compound AGREE:RED -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: AGREE:RED') }, 1],
  ['normal PR + compound AGREE tracked_pending -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('Verdict: AGREE', 'Verdict: AGREE tracked_pending') }, 1],
  ['historical docs-only exemption requires event-bound allowlisted path',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['docs/session-handoff-2026-07-17-example.md'],
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: docs-only historical handoff with no code or governance delta\n' }, 0],
  ['historical docs-only exemption cannot bypass an unresolved Codex REVISE',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['docs/session-handoff-2026-07-17-example.md'],
      evidence: unresolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved',
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: docs-only historical handoff with no code or governance delta\n' }, 1],
  ['archived historical doc is inside the narrow exemption allowlist',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['docs/archive/2025-historical.md'],
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: archived historical record only\n' }, 0],
  ['governance file renamed into archive remains non-exempt',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['AGENTS.md', 'docs/archive/AGENTS.md'],
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: attempted authority rename into archive\n' }, 1],
  ['historical doc mixed with governance path -> fail closed',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['docs/session-handoff-2026-07-17-example.md', 'CLAUDE.md'],
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: mixed change must not qualify\n' }, 1],
  ['governance doc + body-only N/A claim -> fail closed',
    { branch: 'docs-only-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      changedFiles: ['docs/context-priority-rules.md'],
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: N/A\nVerdict: AGREE\nCross-AI exempt reason: claimed docs-only but this is governance\n' }, 1],
  ['normal PR + no Cross-AI section -> fail',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: '## Summary\nno cross-ai here\n' }, 1],

  // #898 — Dependabot bot PR exemption (Codex `019e4517` AGREE 3-iter consensus).
  ['#898 valid dependabot PR (prefix + dependabot[bot] author/sender + same-repo + github-actions allowlist diff) -> exempt PASS',
    { branch: 'dependabot/github_actions/actions/setup-node-6', actor: DEPENDABOT_BOT, sender: DEPENDABOT_BOT,
      body: dependabotBody, changedFiles: ['.github/workflows/ci.yml'] }, 0],
  ['#898 dependabot exemption cannot bypass an unresolved Codex REVISE',
    { branch: 'dependabot/github_actions/actions/setup-node-6', actor: DEPENDABOT_BOT, sender: DEPENDABOT_BOT,
      body: dependabotBody, changedFiles: ['.github/workflows/ci.yml'],
      evidence: unresolvedCodexReviseEvidence,
      expectedFailureCheck: 'consultation_prior_revise_resolved' }, 1],
  ['#898 dependabot PR with non-allowlisted diff path (src/main.py) -> blocked',
    { branch: 'dependabot/python_pkg/foo', actor: DEPENDABOT_BOT, sender: DEPENDABOT_BOT,
      body: dependabotBody, changedFiles: ['.github/workflows/ci.yml', 'src/main.py'] }, 1],
  ['#898 human-opened dependabot/spoof branch -> blocked (actor gate)',
    { branch: 'dependabot/spoof', actor: 'mallory', sender: 'mallory',
      body: dependabotBody, changedFiles: ['.github/workflows/ci.yml'] }, 1],
  ['#898 dependabot[bot] author + human sender (synchronize bypass) -> blocked',
    { branch: 'dependabot/github_actions/actions/setup-node-6', actor: DEPENDABOT_BOT, sender: 'mallory',
      body: dependabotBody, changedFiles: ['.github/workflows/ci.yml'] }, 1],
  ['#898 fork PR on dependabot/* branch -> blocked (same-repo gate)',
    { branch: 'dependabot/github_actions/actions/checkout-6', actor: DEPENDABOT_BOT, sender: DEPENDABOT_BOT,
      headRepo: 'mallory/platform-k8s-gitops', body: dependabotBody, changedFiles: ['.github/workflows/ci.yml'] }, 1],
  ['#898 dependabot PR missing changed-files input -> blocked (fail-closed)',
    { branch: 'dependabot/github_actions/actions/setup-node-6', actor: DEPENDABOT_BOT, sender: DEPENDABOT_BOT,
      body: dependabotBody /* no changedFiles */ }, 1],
];

let fails = 0;
const caseFilter = process.env.CROSS_AI_TEST_FILTER ?? '';
for (const [name, spec, expect] of cases) {
  if (caseFilter && !name.includes(caseFilter)) continue;
  const rc = runCase(spec);
  const ok = rc === expect;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  (rc=${rc}, expect=${expect})`);
  if (!ok) fails += 1;
}
console.log(fails === 0 ? '\nALL PASS' : `\n${fails} FAILURE(S)`);
process.exit(fails ? 1 : 0);
