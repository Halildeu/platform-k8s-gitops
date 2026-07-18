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
const HEAD_SHA = '0123456789abcdef0123456789abcdef01234567';
const BASE_TIP_SHA = '76543210fedcba9876543210fedcba9876543210';
const BASE_SHA = '89abcdef0123456789abcdef0123456789abcdef';
const SCOPE_SHA256 = 'a'.repeat(64);
const NOW_MS = Date.now();

const sha256 = (value) => createHash('sha256').update(value, 'utf8').digest('hex');
const evidenceRef = (id) =>
  `https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/${id}`;
const evidenceBody = (provider, model, response) => JSON.stringify({
  schema: 'cross-ai-provider-evidence/v1',
  provider,
  requested_model: model,
  actual_model: model,
  base_tip_sha: BASE_TIP_SHA,
  base_sha: BASE_SHA,
  head_sha: HEAD_SHA,
  scope_sha256: SCOPE_SHA256,
  verdict: 'AGREE',
  response_sha256: sha256(response),
  response,
});
const evidenceComment = (body, offsetMs = 0) => ({
  body,
  author: 'Halildeu',
  authorAssociation: 'OWNER',
  createdAt: new Date(NOW_MS + offsetMs).toISOString(),
  updatedAt: new Date(NOW_MS + offsetMs).toISOString(),
});
const CLAUDE_REF = evidenceRef(1001);
const MINIMAX_REF = evidenceRef(1002);
const CODEX_REF = evidenceRef(1003);
const EVIDENCE = {
  [CLAUDE_REF]: evidenceComment(evidenceBody('anthropic', 'claude-opus-4-8', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'), 0),
  [MINIMAX_REF]: evidenceComment(evidenceBody('minimax', 'minimax/MiniMax-M3', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'), 1_000),
  [CODEX_REF]: evidenceComment(evidenceBody('openai', 'gpt-5.6-sol', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE'), 2_000),
};
// Forward-policy dual channel is Claude + Codex; reverse their publication order
// to prove the accepted dual path does not depend on receipt timestamp ordering.
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
function runCase({ branch, actor, sender, headRepo = REPO, headSha = HEAD_SHA, baseSha = BASE_TIP_SHA, body, changedFiles, automationAttestation, evidence = EVIDENCE, derivedBaseSha = BASE_SHA, derivedScopeSha256 = SCOPE_SHA256, githubActions = false, allowLocalOverride = 'true', expectedFailureCheck }) {
  const event = {
    pull_request: {
      body,
      head: { ref: branch, sha: headSha, repo: { full_name: headRepo } },
      base: { sha: baseSha, repo: { full_name: REPO } },
      user: { login: actor },
    },
    sender: { login: sender ?? actor },
  };
  const f = join(dir, 'ev.json');
  writeFileSync(f, JSON.stringify(event));
  const evidenceFile = join(dir, 'evidence.json');
  writeFileSync(evidenceFile, JSON.stringify(evidence));
  const cmdArgs = [
    SCRIPT,
    '--event-path',
    f,
    '--evidence-file',
    evidenceFile,
    '--allow-local-evidence-override',
    allowLocalOverride,
    '--derived-base-sha',
    derivedBaseSha,
    '--derived-scope-sha256',
    derivedScopeSha256,
  ];
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
    execFileSync('node', cmdArgs, { stdio: 'pipe', env: childEnv });
    return 0;
  } catch (e) {
    const status = e.status ?? -1;
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
  .replaceAll('__PROMOTION_PR__', '2685')
  .replaceAll('__RUN_URL__', 'https://github.com/Halildeu/platform-k8s-gitops/actions/runs/123')
  .replaceAll('__FAILED_SHA__', HEAD_SHA);

const MINIMAX_RECEIPT_LINE =
  `MiniMax receipt: provider=minimax; requested=minimax/MiniMax-M3; actual=minimax/MiniMax-M3; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${MINIMAX_REF}; sha256=${sha256(EVIDENCE[MINIMAX_REF].body)}`;
const legacyPeerBody =
  `## Summary\nx\n\n## Cross-AI\n` +
  `Implementer AI: Claude\nReviewer AI: Codex\n` +
  `Codex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n` +
  `Consultation base tip: ${BASE_TIP_SHA}\n` +
  `Consultation base: ${BASE_SHA}\n` +
  `Consultation commit: ${HEAD_SHA}\n` +
  `Consultation scope: ${SCOPE_SHA256}\n` +
  `Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CLAUDE_REF}; sha256=${sha256(EVIDENCE[CLAUDE_REF].body)}\n` +
  `Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=gpt-5.6-sol; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CODEX_REF}; sha256=${sha256(EVIDENCE[CODEX_REF].body)}\n`;

const explicitNoneBody =
  `## Cross-AI\n` +
  `Implementer AI: Codex\n` +
  `Consultation mode: none\n` +
  `Consultation reason: Routine implementation and automated tests do not need external consultation.\n`;
const explicitSingleBody =
  `## Cross-AI\n` +
  `Implementer AI: Codex\n` +
  `Consultation mode: single\n` +
  `Consultation reason: One primary architecture opinion is sufficient for this reversible decision.\n` +
  `Verdict: AGREE\n` +
  `Consultation base tip: ${BASE_TIP_SHA}\n` +
  `Consultation base: ${BASE_SHA}\n` +
  `Consultation commit: ${HEAD_SHA}\n` +
  `Consultation scope: ${SCOPE_SHA256}\n` +
  `Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CLAUDE_REF}; sha256=${sha256(EVIDENCE[CLAUDE_REF].body)}\n`;
const explicitDualBody =
  explicitSingleBody
    .replace('Consultation mode: single', 'Consultation mode: dual')
    .replace(
      'Consultation reason: One primary architecture opinion is sufficient for this reversible decision.',
      'Consultation reason: A second provider-distinct opinion is justified by the irreversible decision.',
    ) +
  `Risk trigger: irreversible-production: Production security boundary with named human authority.\n` +
  `Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=gpt-5.6-sol; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CODEX_REF}; sha256=${sha256(EVIDENCE[CODEX_REF].body)}\n`;
// All current acceptance/evidence tests use the explicit forward contract.
// The old fixture remains only for explicit legacy-rejection coverage.
const peerBody = explicitDualBody;
const explicitSingleClaudeImplementerBody = explicitSingleBody.replace(
  'Implementer AI: Codex',
  'Implementer AI: Claude',
);
const explicitDualMiniMaxBody = explicitDualBody.replace(
  /^Codex receipt:.*$/m,
  MINIMAX_RECEIPT_LINE,
);
const explicitDualClaudeImplementerBody = explicitDualBody.replace(
  'Implementer AI: Codex',
  'Implementer AI: Claude',
);
const explicitDualMiniMaxWrongClaudeDigestBody = explicitDualMiniMaxBody.replace(
  sha256(EVIDENCE[CLAUDE_REF].body),
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
const ENFORCEMENT_PATH = 'scripts/ci/pr-cross-ai-audit.mjs';
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
  [MINIMAX_REF]: {
    ...EVIDENCE[MINIMAX_REF],
    createdAt: new Date(NOW_MS - 1_000).toISOString(),
    updatedAt: new Date(NOW_MS - 1_000).toISOString(),
  },
};
const equalTimestampEvidence = {
  ...EVIDENCE,
  [MINIMAX_REF]: {
    ...EVIDENCE[MINIMAX_REF],
    createdAt: EVIDENCE[CLAUDE_REF].createdAt,
    updatedAt: EVIDENCE[CLAUDE_REF].updatedAt,
  },
};
const minimaxReviseResponse = '## P0\nNone\n## P1\nFinding\n## P2\nNone\nVERDICT: REVISE';
const minimaxReviseBody = JSON.stringify({
  ...JSON.parse(EVIDENCE[MINIMAX_REF].body),
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
const ATS_ACTIVATION = 'kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml';
const FULLATS_STATE = 'kustomize/overlays/test/fullats-promotion-state.txt';
const FULLATS_ROLLBACK_FILES = [ATS_ACTIVATION, FULLATS_STATE, PRIMARY_OVERLAY];
const FULLATS_ATTESTATION = {
  schema: 'fullats-rollback-content-attestation/v1',
  valid: true,
  source: FULLATS_ROLLBACK_WF,
  branch: 'auto-fullats-rollback/faz25-fullats-123-1',
  base_sha: BASE_TIP_SHA,
  head_sha: HEAD_SHA,
  promotion_pr: 2685,
  promotion_merge_sha: BASE_TIP_SHA,
  promotion_head_sha: 'b'.repeat(40),
  promotion_base_sha: 'c341e5c4f8616bf0693e4aab2823db2d96426d72',
  promotion_scope_sha256: 'c'.repeat(64),
  changed_diff_sha256: 'd'.repeat(64),
  expected_paths: FULLATS_ROLLBACK_FILES,
};
const VERIFIED_LEDGER = `release-candidates/platform-backend/${'a'.repeat(40)}.json`;

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
  ['valid frontend desired-state PR (auto-test-frontend, App-bot)',
    { branch: 'auto-test-frontend/testai', actor: APP_BOT, sender: APP_BOT, body: autoBody(FRONTEND_WF), changedFiles: [PRIMARY_OVERLAY] }, 0],
  ['valid Full ATS three-file ATS and frontend rollback PR (App-bot)',
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
  ['auto-promotion passes only with required Claude and Codex receipts',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: peerBody, changedFiles: [SCAN] }, 0],
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
  ['legacy receipt body cannot produce current acceptance',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: legacyPeerBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_explicit_mode_required' }, 1],
  ['explicit none mode lets routine work pass without provider receipts',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit none mode accepts substantive prose containing the word none',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody.replace(/^Consultation reason:.*$/m, 'Consultation reason: Reversible documentation update; none of the protected runtime paths apply.'),
      changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit none mode rejects a fabricated or stale provider receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}${peerBody.match(/^Claude receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects an empty provider receipt key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Claude receipt:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects decorative consultation binding fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitNoneBody}Consultation scope: ${SCOPE_SHA256}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit none mode rejects consultation governance changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitNoneBody, changedFiles: [GOVERNANCE_PATH] }, 1],
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
  ['explicit single mode accepts exact direct Claude Opus 4.8 evidence',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit single mode accepts consultation governance changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [GOVERNANCE_PATH] }, 0],
  ['explicit single mode rejects consultation enforcement changes that require dual',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [ENFORCEMENT_PATH] }, 1],
  ['retired MiniMax wrapper tombstone requires dual governance review',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [RETIRED_MINIMAX_WRAPPER_PATH] }, 1],
  ['retired MiniMax wrapper deletion passes only with exact dual review',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [RETIRED_MINIMAX_WRAPPER_PATH] }, 0],
  ['explicit dual mode accepts consultation enforcement changes',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ENFORCEMENT_PATH] }, 0],
  ['explicit none mode rejects a high-confidence RBAC path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [RBAC_PATH] }, 1],
  ['explicit single mode accepts a high-confidence RBAC path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleBody, changedFiles: [RBAC_PATH] }, 0],
  ['explicit none mode rejects a high-confidence database migration path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [MIGRATION_PATH] }, 1],
  ['explicit none mode accepts a harmless RBAC-named documentation path',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneBody, changedFiles: [HARMLESS_RBAC_DOC_PATH] }, 0],
  ['explicit single mode rejects same-provider Claude self-review',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleClaudeImplementerBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects an unidentifiable other implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: explicitSingleBody.replace('Implementer AI: Codex', 'Implementer AI: other'), changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate consultation-mode fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Consultation mode: single\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate implementer fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Implementer AI: Codex\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit mode rejects duplicate receipt fields',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}${explicitSingleBody.match(/^Claude receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
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
      body: `${explicitSingleBody}${peerBody.match(/^Codex receipt:.*$/m)[0]}\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects an empty risk-trigger key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitSingleBody}Risk trigger:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode accepts Claude plus Codex provider-distinct channels',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit dual mode rejects MiniMax as a retired secondary channel',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode accepts the exact Claude+Codex pair for a Codex implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit dual mode accepts the exact Claude+Codex pair for a Claude implementer',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualClaudeImplementerBody, changedFiles: [ROUTINE_PATH] }, 0],
  ['explicit dual mode accepts reverse evidence publication timestamps',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualBody, changedFiles: [ROUTINE_PATH], evidence: REVERSED_DUAL_CODEX_EVIDENCE }, 0],
  ['explicit dual mode rejects a Claude+Codex+MiniMax three-channel mixture',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualClaudeCodexMiniMaxBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'consultation_minimax_receipt_rejected' }, 1],
  ['explicit none mode rejects a retired MiniMax receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitNoneMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit single mode rejects a retired MiniMax receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitSingleMiniMaxBody, changedFiles: [ROUTINE_PATH] }, 1],
  ['explicit dual mode rejects an empty third receipt key',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${explicitDualBody}MiniMax receipt:\n`, changedFiles: [ROUTINE_PATH] }, 1],
  ['invalid MiniMax dual still validates the present allowlisted Claude receipt',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: explicitDualMiniMaxWrongClaudeDigestBody, changedFiles: [ROUTINE_PATH], expectedFailureCheck: 'claude_receipt' }, 1],
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
  ['local evidence-file requires explicit test override flag',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, allowLocalOverride: 'false' }, 1],
  ['normal PR + missing required consultation receipts -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n' }, 1],
  ['normal legacy PR + empty required field still fails closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: legacyPeerBody.replace('Reviewer AI: Codex', 'Reviewer AI:'), changedFiles: [ROUTINE_PATH] }, 1],
  ['normal PR + receipt commit differs from PR head -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      headSha: 'fedcba9876543210fedcba9876543210fedcba98', body: peerBody }, 1],
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
  ['normal PR + equal two-provider evidence timestamps remain accepted',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: equalTimestampEvidence, changedFiles: [ROUTINE_PATH] }, 0],
  ['normal PR + duplicate provider evidence refs -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(CODEX_REF, CLAUDE_REF) }, 1],
  ['Claude/Codex AGREE plus forbidden MiniMax REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: `${peerBody}${MINIMAX_RECEIPT_LINE.replace(sha256(EVIDENCE[MINIMAX_REF].body), sha256(minimaxReviseBody))}\n`, evidence: minimaxReviseEvidence }, 1],
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
for (const [name, spec, expect] of cases) {
  const rc = runCase(spec);
  const ok = rc === expect;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  (rc=${rc}, expect=${expect})`);
  if (!ok) fails += 1;
}
console.log(fails === 0 ? '\nALL PASS' : `\n${fails} FAILURE(S)`);
process.exit(fails ? 1 : 0);
