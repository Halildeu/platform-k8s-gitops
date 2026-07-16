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

// Build the GitHub event payload and run the real script; return its exit code.
// `changedFiles` is an optional array → written to a temp file and passed via
// `--changed-files-file`. `undefined` skips the flag entirely (older workflows
// and the normal peer-review audit don't need it). `[]` writes an empty file
// (fail-closed via dependabot_changed_files_present).
function runCase({ branch, actor, sender, headRepo = REPO, body, changedFiles }) {
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
  const cmdArgs = [SCRIPT, '--event-path', f];
  if (Array.isArray(changedFiles)) {
    const cf = join(dir, 'changed-files.txt');
    writeFileSync(cf, changedFiles.join('\n'));
    cmdArgs.push('--changed-files-file', cf);
  }
  try {
    execFileSync('node', cmdArgs, { stdio: 'pipe' });
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
const FRONTEND_WF = '.github/workflows/deploy-testai.yml';
const LEDGER = 'scripts/promotion/ledger-mark-verified.sh';
const SCAN = 'scripts/promotion/scan-promotion-candidates.sh';
const PRIMARY_OVERLAY = 'kustomize/overlays/test/kustomization.yaml';

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
    { branch: 'auto-verified/test-20260519', actor: BOT, sender: BOT, body: autoBody(LEDGER) }, 0],
  ['valid auto-promotion PR (App-bot)',
    { branch: 'auto-promotion/prod-platform-backend-abc1234', actor: APP_BOT, sender: APP_BOT, body: autoBody(SCAN) }, 0],
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
  ['#842: auto-promotion + github-actions[bot] (wrong bot for prefix) -> blocked',
    { branch: 'auto-promotion/x', actor: BOT, sender: BOT, body: autoBody(SCAN) }, 1],
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
