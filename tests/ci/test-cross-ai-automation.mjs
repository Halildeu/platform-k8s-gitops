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
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = join(REPO_ROOT, 'scripts', 'ci', 'pr-cross-ai-audit.mjs');
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
const NOW = new Date().toISOString();

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
const evidenceComment = (body) => ({
  body,
  author: 'Halildeu',
  authorAssociation: 'OWNER',
  createdAt: NOW,
  updatedAt: NOW,
});
const CLAUDE_REF = evidenceRef(1001);
const MINIMAX_REF = evidenceRef(1002);
const CODEX_REF = evidenceRef(1003);
const EVIDENCE = {
  [CLAUDE_REF]: evidenceComment(evidenceBody('anthropic', 'claude-opus-4-8', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE')),
  [MINIMAX_REF]: evidenceComment(evidenceBody('minimax', 'minimax/MiniMax-M3', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE')),
  [CODEX_REF]: evidenceComment(evidenceBody('openai', 'gpt-5.6-sol', '## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE')),
};

// Build the GitHub event payload and run the real script; return its exit code.
// `changedFiles` is an optional array → written to a temp file and passed via
// `--changed-files-file`. `undefined` skips the flag entirely (older workflows
// and the normal peer-review audit don't need it). `[]` writes an empty file
// (fail-closed via dependabot_changed_files_present).
function runCase({ branch, actor, sender, headRepo = REPO, headSha = HEAD_SHA, baseSha = BASE_TIP_SHA, body, changedFiles, evidence = EVIDENCE, derivedBaseSha = BASE_SHA, derivedScopeSha256 = SCOPE_SHA256, githubActions = false, allowLocalOverride = 'true' }) {
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
  try {
    const childEnv = { ...process.env };
    if (githubActions) childEnv.GITHUB_ACTIONS = 'true';
    else delete childEnv.GITHUB_ACTIONS;
    execFileSync('node', cmdArgs, { stdio: 'pipe', env: childEnv });
    return 0;
  } catch (e) {
    return e.status ?? -1;
  }
}

const autoBody = (src) =>
  `## Summary\nauto\n\n## Cross-AI\n` +
  `Automation source: ${src}\n` +
  `Cross-AI exempt reason: Machine-generated rollout-verified PR; no AI peer-review claim is made.\n` +
  `Automation evidence: https://github.com/Halildeu/platform-k8s-gitops/actions/runs/123\n`;

const peerBody =
  `## Summary\nx\n\n## Cross-AI\n` +
  `Implementer AI: Claude\nReviewer AI: Codex\n` +
  `Codex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n` +
  `Consultation base tip: ${BASE_TIP_SHA}\n` +
  `Consultation base: ${BASE_SHA}\n` +
  `Consultation commit: ${HEAD_SHA}\n` +
  `Consultation scope: ${SCOPE_SHA256}\n` +
  `Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CLAUDE_REF}; sha256=${sha256(EVIDENCE[CLAUDE_REF].body)}\n` +
  `MiniMax receipt: provider=minimax; requested=minimax/MiniMax-M3; actual=minimax/MiniMax-M3; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${MINIMAX_REF}; sha256=${sha256(EVIDENCE[MINIMAX_REF].body)}\n` +
  `Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=gpt-5.6-sol; base_tip=${BASE_TIP_SHA}; base=${BASE_SHA}; head=${HEAD_SHA}; scope=${SCOPE_SHA256}; verdict=AGREE; ref=${CODEX_REF}; sha256=${sha256(EVIDENCE[CODEX_REF].body)}\n`;

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
  [CLAUDE_REF]: {
    ...EVIDENCE[CLAUDE_REF],
    createdAt: new Date(Date.now() + 60_000).toISOString(),
    updatedAt: new Date(Date.now() + 60_000).toISOString(),
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
const minimaxRevisePeerBody = peerBody.replace(
  sha256(EVIDENCE[MINIMAX_REF].body),
  sha256(minimaxReviseBody),
);
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
const LEDGER = 'scripts/promotion/ledger-mark-verified.sh';
const SCAN = 'scripts/promotion/scan-promotion-candidates.sh';
const PRIMARY_OVERLAY = 'kustomize/overlays/test/kustomization.yaml';
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
  ['valid auto-verified PR (bot)',
    { branch: 'auto-verified/test-20260519', actor: BOT, sender: BOT, body: autoBody(LEDGER), changedFiles: [VERIFIED_LEDGER] }, 0],
  ['auto-promotion draft cannot claim an automation exemption',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: autoBody(SCAN) }, 1],
  ['auto-promotion passes only with normal three-channel receipts',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: peerBody }, 0],
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
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody }, 0],
  ['GitHub Actions mode rejects offline evidence-file override',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, githubActions: true }, 1],
  ['local evidence-file requires explicit test override flag',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody, allowLocalOverride: 'false' }, 1],
  ['normal PR + missing three-channel receipts -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: '## Cross-AI\nImplementer AI: Claude\nReviewer AI: Codex\nCodex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n' }, 1],
  ['normal PR + receipt commit differs from PR head -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      headSha: 'fedcba9876543210fedcba9876543210fedcba98', body: peerBody }, 1],
  ['normal PR + MiniMax actual-model mismatch -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace('actual=minimax/MiniMax-M3', 'actual=minimax/MiniMax-M2.7') }, 1],
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
  ['normal PR + evidence publication order is not Claude then MiniMax then Codex -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody, evidence: outOfOrderEvidence }, 1],
  ['normal PR + duplicate provider evidence refs -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: peerBody.replace(MINIMAX_REF, CLAUDE_REF) }, 1],
  ['Claude/Codex AGREE + MiniMax REVISE -> fail closed',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu',
      body: minimaxRevisePeerBody, evidence: minimaxReviseEvidence }, 1],
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
