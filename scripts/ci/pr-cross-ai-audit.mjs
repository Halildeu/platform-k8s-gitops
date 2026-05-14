#!/usr/bin/env node
// PR-V2.1-GOV-1 Cross-AI Peer Review Audit
// PMD v9.1 §7 + HARD RULE Cross-AI Peer Review (provider seviyesinde)
// Codex `019e2693` tur-1 REVISE → 4 finding absorb:
//   HIGH-1: workflow job name canonical `cross-ai-audit` (PMD §2.10 must-pass)
//   HIGH-2: same-provider exception requires `exception_reason:` evidence field
//   MED-3:  Codex thread `N/A` allowed only with explicit `cross_ai_exempt_reason:`
//   MED-4:  parser scoped to `## Cross-AI` heading + inline YAML comment strip
//
// CI gate: gate-cross-ai-audit (V2.1 GOV-1 10 must-pass'dan biri)
//
// Usage:
//   node scripts/ci/pr-cross-ai-audit.mjs --event-path "$GITHUB_EVENT_PATH"
//   node scripts/ci/pr-cross-ai-audit.mjs --body-file <path>  (local test)
//
// Exit codes:
//   0 — PASS
//   1 — FAIL (cross-ai violation)
//   2 — INPUT ERROR

import { readFileSync } from 'node:fs';
import { argv, exit } from 'node:process';

const VALID_PROVIDERS = new Set(['claude', 'codex', 'gemini', 'other']);
const VALID_VERDICTS = new Set(['agree', 'revise', 'partial', 'red']);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Codex `019e2693` MED-3 absorb: known-provider canonicalizer (R2 question response)
const PROVIDER_ALIASES = {
  // claude family
  claude: 'claude',
  'anthropic claude': 'claude',
  'claude opus': 'claude',
  'claude sonnet': 'claude',
  'claude haiku': 'claude',
  // codex family
  codex: 'codex',
  'openai codex': 'codex',
  'gpt codex': 'codex',
  // gemini family
  gemini: 'gemini',
  'google gemini': 'gemini',
  'gemini pro': 'gemini',
  // grok family
  grok: 'other',
  'xai grok': 'other',
  // catch-all
  other: 'other',
};

function parseArgs() {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      args[key] = argv[i + 1];
      i++;
    }
  }
  return args;
}

function loadBody(args) {
  if (args['body-file']) {
    return readFileSync(args['body-file'], 'utf8');
  }
  if (args['event-path']) {
    const ev = JSON.parse(readFileSync(args['event-path'], 'utf8'));
    return ev.pull_request?.body ?? '';
  }
  console.error('[cross-ai-audit] ERROR: --event-path veya --body-file gerekli');
  exit(2);
}

// Codex `019e2693` MED-4 absorb: scoped parser — only `## Cross-AI` section
function extractCrossAiSection(body) {
  const lines = body.split(/\r?\n/);
  let inSection = false;
  const sectionLines = [];
  for (const line of lines) {
    if (/^##\s+Cross-AI/i.test(line)) {
      inSection = true;
      continue;
    }
    if (inSection && /^##\s+/.test(line)) {
      // Next section starts; stop
      break;
    }
    if (inSection) {
      sectionLines.push(line);
    }
  }
  return sectionLines.join('\n');
}

// Inline YAML comment strip + key/value extract from Cross-AI section
function extractFields(section) {
  const fields = {};
  // Strip fenced code block markers
  const cleaned = section.replace(/```[a-z]*\n?/g, '').replace(/```/g, '');
  const lines = cleaned.split(/\r?\n/);
  const keyRe = /^\s*(Implementer AI|Reviewer AI|Codex thread|Verdict|Verdict reason|Same-provider exception|Exception reason|Cross-AI exempt reason|Absorb edilen düzeltmeler)\s*:\s*(.*?)\s*$/i;
  for (const line of lines) {
    const m = line.match(keyRe);
    if (m) {
      const key = m[1].toLowerCase();
      let val = m[2];
      // Strip inline YAML comments (e.g. "Claude # one of [...]")
      const commentIdx = val.indexOf('#');
      if (commentIdx >= 0) val = val.slice(0, commentIdx);
      // Strip surrounding quotes/backticks
      val = val.replace(/^[`"']|[`"']$/g, '').trim();
      if (val.length > 0) {
        fields[key] = val;
      }
    }
  }
  return fields;
}

function normalizeProvider(s) {
  if (!s) return null;
  // Strip parenthetical org annotations: "Claude (Anthropic)" → "claude"
  const cleaned = s
    .replace(/\(.*?\)/g, '')
    .trim()
    .toLowerCase();
  // Look up alias table
  return PROVIDER_ALIASES[cleaned] ?? cleaned;
}

function audit(body) {
  const findings = [];
  const section = extractCrossAiSection(body);
  if (!section) {
    findings.push({
      check: 'cross_ai_section_present',
      pass: false,
      detail: '`## Cross-AI` heading PR body\'sinde bulunamadı',
    });
    return findings;
  }
  findings.push({ check: 'cross_ai_section_present', pass: true });

  const fields = extractFields(section);

  // Check 1: required fields present
  const required = ['implementer ai', 'reviewer ai', 'codex thread', 'verdict'];
  const missing = required.filter((k) => !fields[k]);
  if (missing.length > 0) {
    findings.push({
      check: 'required_fields_present',
      pass: false,
      detail: `Eksik field'lar: ${missing.join(', ')}`,
    });
  } else {
    findings.push({ check: 'required_fields_present', pass: true });
  }

  // Check 2: provider enum
  const impl = normalizeProvider(fields['implementer ai']);
  const rev = normalizeProvider(fields['reviewer ai']);
  if (impl && !VALID_PROVIDERS.has(impl)) {
    findings.push({
      check: 'implementer_provider_enum',
      pass: false,
      detail: `Implementer AI "${fields['implementer ai']}" invalid (canonical: ${[...VALID_PROVIDERS].join(', ')})`,
    });
  } else if (impl) {
    findings.push({ check: 'implementer_provider_enum', pass: true });
  }
  if (rev && !VALID_PROVIDERS.has(rev)) {
    findings.push({
      check: 'reviewer_provider_enum',
      pass: false,
      detail: `Reviewer AI "${fields['reviewer ai']}" invalid (canonical: ${[...VALID_PROVIDERS].join(', ')})`,
    });
  } else if (rev) {
    findings.push({ check: 'reviewer_provider_enum', pass: true });
  }

  // Check 3: different providers (HARD RULE) + Codex HIGH-2 evidence requirement
  if (impl && rev) {
    const sameProvider = impl === rev;
    const exception = (fields['same-provider exception'] || '').toLowerCase();
    const hasUserApproval = /user-explicit-approval/i.test(exception);
    const exceptionReason = fields['exception reason'] || '';
    if (sameProvider) {
      if (!hasUserApproval) {
        findings.push({
          check: 'cross_ai_provider_differs',
          pass: false,
          detail: `Aynı provider "${impl}" + same-provider exception "user-explicit-approval" beyanı yok`,
        });
      } else if (!exceptionReason || exceptionReason.length < 10) {
        // Codex `019e2693` HIGH-2 absorb: phrase + zorunlu reason field
        findings.push({
          check: 'cross_ai_provider_differs',
          pass: false,
          detail: `Same-provider exception declared ama "Exception reason:" field eksik veya < 10 karakter (PMD §7.2 evidence requirement)`,
        });
      } else {
        findings.push({
          check: 'cross_ai_provider_differs',
          pass: true,
          detail: `Same provider — user-explicit-approval + exception reason (${exceptionReason.length}c)`,
        });
      }
    } else {
      findings.push({
        check: 'cross_ai_provider_differs',
        pass: true,
        detail: `Implementer "${impl}" ≠ Reviewer "${rev}"`,
      });
    }
  }

  // Check 4: Codex thread format — Codex `019e2693` MED-3 absorb
  const thread = fields['codex thread'];
  if (thread) {
    const clean = thread.trim();
    // N/A requires explicit cross_ai_exempt_reason
    if (clean.toLowerCase() === 'n/a') {
      const exemptReason = fields['cross-ai exempt reason'] || '';
      if (exemptReason && exemptReason.length >= 10) {
        findings.push({
          check: 'codex_thread_format',
          pass: true,
          detail: `N/A allowed — Cross-AI exempt reason provided (${exemptReason.length}c)`,
        });
      } else {
        findings.push({
          check: 'codex_thread_format',
          pass: false,
          detail: `Codex thread N/A requires "Cross-AI exempt reason:" field (≥ 10 char, e.g. "docs-only handoff PR, no code change")`,
        });
      }
    } else if (clean === '-' || clean === '') {
      // Codex MED-3: remove `-` alias bypass
      findings.push({
        check: 'codex_thread_format',
        pass: false,
        detail: `Codex thread "${clean}" rejected (use full UUID or N/A + Cross-AI exempt reason)`,
      });
    } else {
      // Extract first UUID candidate (multi-line allowed)
      const firstUuid = clean.split(/\s+/).find((t) => UUID_RE.test(t));
      if (firstUuid) {
        findings.push({ check: 'codex_thread_format', pass: true });
      } else {
        findings.push({
          check: 'codex_thread_format',
          pass: false,
          detail: `Thread ID "${clean.slice(0, 40)}..." UUID format değil (beklenen: 019eXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)`,
        });
      }
    }
  }

  // Check 5: Verdict enum (compound verdict tolerance)
  const verdict = (fields['verdict'] || '').toLowerCase();
  if (verdict) {
    const baseVerdict = verdict.split(/[\s_:]/)[0];
    if (VALID_VERDICTS.has(baseVerdict)) {
      findings.push({ check: 'verdict_enum', pass: true });
    } else {
      findings.push({
        check: 'verdict_enum',
        pass: false,
        detail: `Verdict "${verdict}" invalid (valid: ${[...VALID_VERDICTS].join(', ')})`,
      });
    }
  }

  return findings;
}

function report(findings) {
  const passed = findings.filter((f) => f.pass).length;
  const total = findings.length;
  let allPass = true;
  for (const f of findings) {
    const mark = f.pass ? '✓' : '✗';
    const detail = f.detail ? `: ${f.detail}` : '';
    console.log(`  ${mark} ${f.check}${detail}`);
    if (!f.pass) allPass = false;
  }
  console.log('');
  console.log(`Cross-AI audit: ${allPass ? 'PASS' : 'FAIL'} (${passed}/${total})`);
  return allPass;
}

// Main
const args = parseArgs();
const body = loadBody(args);
const findings = audit(body);
const ok = report(findings);
exit(ok ? 0 : 1);
