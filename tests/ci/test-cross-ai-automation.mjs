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
const BOT = 'github-actions[bot]';
const dir = mkdtempSync(join(tmpdir(), 'crossai-'));

// Build the GitHub event payload and run the real script; return its exit code.
function runCase({ branch, actor, sender, headRepo = REPO, body }) {
  const event = {
    pull_request: {
      body,
      head: { ref: branch, repo: { full_name: headRepo } },
      base: { repo: { full_name: REPO } },
      user: { login: actor },
    },
    sender: { login: sender ?? actor },
  };
  const f = join(dir, 'ev.json');
  writeFileSync(f, JSON.stringify(event));
  try {
    execFileSync('node', [SCRIPT, '--event-path', f], { stdio: 'pipe' });
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
  `Codex thread: 019e3f5b-bfa2-71b1-b2df-96d424e4bda8\nVerdict: AGREE\n`;

const WF = '.github/workflows/deploy-backend-testai.yml';
const LEDGER = 'scripts/promotion/ledger-mark-verified.sh';
const SCAN = 'scripts/promotion/scan-promotion-candidates.sh';

const cases = [
  ['valid automation PR (auto-test-overlay, bot author + bot sender)',
    { branch: 'auto-test-overlay/backend-testai-live', actor: BOT, sender: BOT, body: autoBody(WF) }, 0],
  ['valid auto-verified PR (bot)',
    { branch: 'auto-verified/test-20260519', actor: BOT, sender: BOT, body: autoBody(LEDGER) }, 0],
  ['valid auto-promotion PR (bot)',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: BOT, sender: BOT, body: autoBody(SCAN) }, 0],
  ['bot-opened auto-PR + HUMAN sender (synchronize bypass) -> blocked',
    { branch: 'auto-test-overlay/backend-testai-live', actor: BOT, sender: 'mallory', body: autoBody(WF) }, 1],
  ['human-opened auto-* branch -> blocked',
    { branch: 'auto-test-overlay/sneaky', actor: 'mallory', sender: 'mallory', body: autoBody(WF) }, 1],
  ['auto-* + bot, missing Automation source -> fail',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT,
      body: '## Cross-AI\nCross-AI exempt reason: machine PR no review claim\nAutomation evidence: https://x/y/z\n' }, 1],
  ['auto-* + bot, wrong source for prefix -> fail',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, body: autoBody(WF) }, 1],
  ['fork PR on auto-* branch -> blocked',
    { branch: 'auto-verified/x', actor: BOT, sender: BOT, headRepo: 'mallory/platform-k8s-gitops', body: autoBody(LEDGER) }, 1],
  ['normal PR + valid peer review -> normal audit pass',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: peerBody }, 0],
  ['normal PR + no Cross-AI section -> fail',
    { branch: 'roadmap-827-x', actor: 'halilkocoglu', sender: 'halilkocoglu', body: '## Summary\nno cross-ai here\n' }, 1],
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
