#!/usr/bin/env node
// Regression tests for scripts/ci/check-forbidden-close-keywords.mjs.

import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = join(REPO_ROOT, 'scripts', 'ci', 'check-forbidden-close-keywords.mjs');
const dir = mkdtempSync(join(tmpdir(), 'forbidden-close-'));

function writeEvent(title, body) {
  const file = join(dir, `event-${Math.random().toString(16).slice(2)}.json`);
  writeFileSync(
    file,
    JSON.stringify({
      pull_request: {
        title,
        body,
      },
    }),
  );
  return file;
}

function writeCommits(commits) {
  const file = join(dir, `commits-${Math.random().toString(16).slice(2)}.ndjson`);
  writeFileSync(file, commits.map((commit) => JSON.stringify(commit)).join('\n'));
  return file;
}

function writePushEvent(commits) {
  const file = join(dir, `push-${Math.random().toString(16).slice(2)}.json`);
  writeFileSync(
    file,
    JSON.stringify({
      head_commit: commits[0] ?? {},
      commits,
    }),
  );
  return file;
}

function writeReleaseEvent(name, body) {
  const file = join(dir, `release-${Math.random().toString(16).slice(2)}.json`);
  writeFileSync(
    file,
    JSON.stringify({
      release: {
        name,
        body,
      },
    }),
  );
  return file;
}

function run(args) {
  try {
    execFileSync('node', [SCRIPT, ...args], { stdio: 'pipe' });
    return 0;
  } catch (error) {
    return error.status ?? -1;
  }
}

const cases = [
  [
    'Tracked by in PR body is allowed',
    () => ['--event-path', writeEvent('feat(board): add guard', 'Tracked by #1498\nRuntime evidence pending')],
    0,
  ],
  [
    'Closes issue ref in PR body is blocked',
    () => ['--event-path', writeEvent('feat(board): add guard', 'Closes #1498')],
    1,
  ],
  [
    'Close keyword without issue ref is allowed',
    () => ['--event-path', writeEvent('fix: guard', 'Closes the bug class where rollout status was noisy.')],
    0,
  ],
  [
    'Fixes owner/repo issue ref in commit message is blocked',
    () => [
      '--event-path',
      writeEvent('feat(board): add guard', 'Tracked by #1498'),
      '--commit-messages-file',
      writeCommits([
        {
          sha: '0123456789abcdef',
          message: 'fix(board): tighten guard\n\nFixes Halildeu/platform-k8s-gitops#1498',
        },
      ]),
    ],
    1,
  ],
  [
    'Resolves GitHub issue URL in PR title is blocked',
    () => [
      '--event-path',
      writeEvent(
        'Resolves https://github.com/Halildeu/platform-k8s-gitops/issues/1498',
        'Tracked by #1498',
      ),
    ],
    1,
  ],
  [
    'Uppercase close keyword is blocked',
    () => ['--event-path', writeEvent('feat(board): add guard', 'CLOSES #1498')],
    1,
  ],
  [
    'Release note text file can be scanned',
    () => {
      const file = join(dir, 'release-notes.md');
      writeFileSync(file, 'Release notes\n\nResolved #1498\n');
      return ['--text-file', file];
    },
    1,
  ],
  [
    'Push event merge body is blocked',
    () => [
      '--event-path',
      writePushEvent([
        {
          id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          message: 'coordination: merge verifier\n\nCloses #1498',
        },
      ]),
    ],
    1,
  ],
  [
    'Release event notes are blocked',
    () => ['--event-path', writeReleaseEvent('v-test', 'Release notes\n\nFixes #1498')],
    1,
  ],
];

let failures = 0;
for (const [name, argsFactory, expected] of cases) {
  const actual = run(argsFactory());
  const ok = actual === expected;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} (rc=${actual}, expect=${expected})`);
  if (!ok) failures += 1;
}

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures ? 1 : 0);
