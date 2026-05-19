#!/usr/bin/env node
// tests/ci/test-cross-ai-automation.mjs
//
// #827 — regression test for the automation-PR exemption in
// scripts/ci/pr-cross-ai-audit.mjs. Exercises the REAL script via synthetic
// `--event-path` payloads (no network, no GitHub). Verifies:
//   - a legitimate bot auto-PR (allowlisted branch + actor + body fields) passes
//   - a human on an auto-* branch is blocked (the actor allowlist abuse gate)
//   - missing / mismatched automation metadata fails
//   - a fork PR cannot claim the exemption
//   - a normal PR still gets the normal cross-AI peer-review audit
//
// Run: node tests/ci/test-cross-ai-automation.mjs   (exit 0 = all pass)
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = join(REPO_ROOT, 'scripts', 'ci', 'pr-cross-ai-audit.mjs');
const REPO = 'Halildeu/platform-k8s-gitops';
const dir = mkdtempSync(join(tmpdir(), 'crossai-'));

function runEvent(pullRequest) {
  const f = join(dir, 'ev.json');
  writeFileSync(f, JSON.stringify({ pull_request: pullRequest }));
  try {
    execFileSync('node', [SCRIPT, '--event-path', f], { stdio: 'pipe' });
    return 0;
  } catch (e) {
    return e.status ?? -1;
  }
}

const pr = ({ branch, actor, headRepo = REPO, body }) => ({
  body,
  head: { ref: branch, repo: { full_name: headRepo } },
  base: { repo: { full_name: REPO } },
  user: { login: actor },
});

const autoBody = (src) =>
  `## Summary\nauto\n\n## Cross-AI\n` +
  `Automation source: ${src}\n` +
  `Cross-AI exempt reason: Machine-generated rollout-verified PR; no AI peer-review claim is made.\n` +
  `Automation evidence: https://github.com/Halildeu/platform-k8s-gitops/actions/runs/123\n`;

const peerBody =
  `## Summary\nx\n\n## Cross-AI\n` +
  `Implementer AI: Claude\nReviewer AI: Codex\n` +
  `Codex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n`;

const WF = '.github/workflows/deploy-backend-testai.yml';
const LEDGER = 'scripts/promotion/ledger-mark-verified.sh';
const SCAN = 'scripts/promotion/scan-promotion-candidates.sh';

const cases = [
  ['valid automation PR (auto-test-overlay, bot)',
    pr({ branch: 'auto-test-overlay/backend-testai-live', actor: 'github-actions[bot]', body: autoBody(WF) }), 0],
  ['auto-* branch + HUMAN actor -> blocked',
    pr({ branch: 'auto-test-overlay/sneaky', actor: 'mallory', body: autoBody(WF) }), 1],
  ['auto-* + bot, missing Automation source',
    pr({ branch: 'auto-verified/x', actor: 'github-actions[bot]',
         body: '## Cross-AI\nCross-AI exempt reason: machine PR no review claim\nAutomation evidence: https://x/y/z\n' }), 1],
  ['auto-* + bot, wrong source for prefix',
    pr({ branch: 'auto-verified/x', actor: 'github-actions[bot]', body: autoBody(WF) }), 1],
  ['fork PR on auto-* branch -> blocked',
    pr({ branch: 'auto-verified/x', actor: 'github-actions[bot]', headRepo: 'mallory/platform-k8s-gitops', body: autoBody(LEDGER) }), 1],
  ['valid auto-verified PR (bot)',
    pr({ branch: 'auto-verified/test-20260519', actor: 'github-actions[bot]', body: autoBody(LEDGER) }), 0],
  ['valid auto-promotion PR (bot)',
    pr({ branch: 'auto-promotion/prod-platform-backend-abc1234', actor: 'github-actions[bot]', body: autoBody(SCAN) }), 0],
  ['normal PR + valid peer review -> normal audit pass',
    pr({ branch: 'roadmap-827-x', actor: 'halilkocoglu', body: peerBody }), 0],
  ['normal PR + no Cross-AI section -> fail',
    pr({ branch: 'roadmap-827-x', actor: 'halilkocoglu', body: '## Summary\nno cross-ai here\n' }), 1],
];

let fails = 0;
for (const [name, prObj, expect] of cases) {
  const rc = runEvent(prObj);
  const ok = rc === expect;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  (rc=${rc}, expect=${expect})`);
  if (!ok) fails += 1;
}
console.log(fails === 0 ? '\nALL PASS' : `\n${fails} FAILURE(S)`);
process.exit(fails ? 1 : 0);
