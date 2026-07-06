#!/usr/bin/env node
// Runtime/GitOps PR auto-close guard.
//
// Runtime and acceptance-gated roadmap issues must be linked with
// "Tracked by #N", not GitHub auto-close keywords. This script scans PR
// metadata and commit messages for close keywords only when they target an
// issue reference, avoiding false positives such as "Closes the bug class".

import { basename } from 'node:path';
import { argv, exit } from 'node:process';
import { readFileSync } from 'node:fs';

const CLOSE_KEYWORD_RE =
  /\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\b\s*:?\s+((?:https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/issues\/\d+)|(?:(?:[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)?#\d+))/gi;

function parseArgs() {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) {
      console.error(`[forbidden-close-keywords] ERROR: unexpected positional argument: ${arg}`);
      exit(2);
    }
    const key = arg.slice(2);
    const value = argv[i + 1];
    if (value === undefined || value.startsWith('--')) {
      console.error(`[forbidden-close-keywords] ERROR: --${key} requires a value`);
      exit(2);
    }
    if (args[key] === undefined) {
      args[key] = value;
    } else if (Array.isArray(args[key])) {
      args[key].push(value);
    } else {
      args[key] = [args[key], value];
    }
    i++;
  }
  return args;
}

function asArray(value) {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

function locationFor(text, index) {
  const prefix = text.slice(0, index);
  const lines = prefix.split(/\r?\n/);
  const line = lines.length;
  const column = lines[lines.length - 1].length + 1;
  return { line, column };
}

function excerpt(text, index, length) {
  const start = Math.max(0, index - 50);
  const end = Math.min(text.length, index + length + 50);
  return text
    .slice(start, end)
    .replace(/\s+/g, ' ')
    .trim();
}

function scanSurface(findings, surface, text) {
  if (!text) return;
  CLOSE_KEYWORD_RE.lastIndex = 0;
  let match;
  while ((match = CLOSE_KEYWORD_RE.exec(text)) !== null) {
    const loc = locationFor(text, match.index);
    findings.push({
      surface,
      line: loc.line,
      column: loc.column,
      keyword: match[1],
      issueRef: match[2],
      match: match[0],
      excerpt: excerpt(text, match.index, match[0].length),
    });
  }
}

function loadEventSurfaces(args, findings) {
  if (!args['event-path']) return;
  const event = JSON.parse(readFileSync(args['event-path'], 'utf8'));
  const pr = event.pull_request ?? {};
  scanSurface(findings, 'pull_request.title', pr.title ?? '');
  scanSurface(findings, 'pull_request.body', pr.body ?? '');

  const release = event.release ?? {};
  scanSurface(findings, 'release.name', release.name ?? release.tag_name ?? '');
  scanSurface(findings, 'release.body', release.body ?? '');

  const headCommit = event.head_commit ?? {};
  scanSurface(findings, 'push.head_commit.message', headCommit.message ?? '');
  for (const [idx, commit] of (event.commits ?? []).entries()) {
    scanSurface(findings, `push.commits[${idx}].message`, commit.message ?? '');
  }
}

function loadBodySurfaces(args, findings) {
  if (args['title-file']) {
    scanSurface(findings, `file:${basename(args['title-file'])}:title`, readFileSync(args['title-file'], 'utf8'));
  }
  if (args['body-file']) {
    scanSurface(findings, `file:${basename(args['body-file'])}:body`, readFileSync(args['body-file'], 'utf8'));
  }
  for (const file of asArray(args['text-file'])) {
    scanSurface(findings, `file:${basename(file)}`, readFileSync(file, 'utf8'));
  }
}

function loadCommitSurfaces(args, findings) {
  const file = args['commit-messages-file'];
  if (!file) return;

  const lines = readFileSync(file, 'utf8')
    .split(/\r?\n/)
    .filter(Boolean);

  for (const [idx, line] of lines.entries()) {
    try {
      const item = JSON.parse(line);
      const sha = String(item.sha ?? `line-${idx + 1}`);
      const message = String(item.message ?? '');
      scanSurface(findings, `commit:${sha.slice(0, 12)}`, message);
    } catch (error) {
      console.error(
        `[forbidden-close-keywords] ERROR: invalid commit JSON line ${idx + 1} in ${file}: ${error.message}`,
      );
      exit(2);
    }
  }
}

function main() {
  const args = parseArgs();
  const hasInput =
    args['event-path'] ||
    args['title-file'] ||
    args['body-file'] ||
    args['text-file'] ||
    args['commit-messages-file'];

  if (!hasInput) {
    console.error(
      '[forbidden-close-keywords] ERROR: provide --event-path, --body-file, --title-file, --text-file, or --commit-messages-file',
    );
    exit(2);
  }

  const findings = [];
  loadEventSurfaces(args, findings);
  loadBodySurfaces(args, findings);
  loadCommitSurfaces(args, findings);

  if (findings.length > 0) {
    console.error('[forbidden-close-keywords] FAIL: forbidden GitHub auto-close keyword found.');
    console.error('Use "Tracked by #N" for runtime/GitOps/acceptance issues; do not use Closes/Fixes/Resolves.');
    for (const finding of findings) {
      console.error(
        `- ${finding.surface}:${finding.line}:${finding.column} ${finding.match} ` +
          `(keyword=${finding.keyword}, issue=${finding.issueRef})`,
      );
      console.error(`  ${finding.excerpt}`);
    }
    exit(1);
  }

  console.log('[forbidden-close-keywords] PASS: no forbidden auto-close issue references found.');
}

main();
