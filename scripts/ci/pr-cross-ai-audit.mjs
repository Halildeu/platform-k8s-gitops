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

// ── Automation-PR governance contract (#827) ──────────────────────────────
// A machine-generated PR cannot make a cross-AI peer-review claim. It is
// instead *exempt* from the peer-review requirement iff it proves — via a
// multi-signal predicate, NOT a fake reviewer — that it is a genuine, known
// automation source. The actor allowlist is the hard gate against
// HUMAN-authored spoofing: a human PR has a human actor and can never satisfy
// the exemption, no matter how the head branch is named or the body is
// crafted. It is NOT full bot-token isolation — `github-actions[bot]` is
// shared by every write-capable workflow; the same-repo + branch-prefix +
// source-contract + evidence chain bounds the automation class, and a diff
// path allowlist (#827 PR-A2 / PR-B) is what closes a compromised-bot blast
// radius.
// value = the generating file path; deliberately no `#<anchor>` — extractFields()
// strips an inline `#` as a YAML comment, so the source identifier must be #-free.
const AUTOMATION_BRANCH_CONTRACT = {
  'auto-test-overlay/': '.github/workflows/deploy-backend-testai.yml',
  'auto-verified/': 'scripts/promotion/ledger-mark-verified.sh',
  'auto-promotion/': 'scripts/promotion/scan-promotion-candidates.sh',
};
const AUTOMATION_ACTORS = new Set(['github-actions[bot]']);

function matchedAutomationPrefix(headRef) {
  return (
    Object.keys(AUTOMATION_BRANCH_CONTRACT).find((p) => headRef.startsWith(p)) ?? null
  );
}

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

function loadInput(args) {
  if (args['body-file']) {
    // Local test mode — no PR metadata, so the automation-exemption path is
    // unavailable and the normal peer-review audit runs.
    return { body: readFileSync(args['body-file'], 'utf8'), prMeta: null };
  }
  if (args['event-path']) {
    const ev = JSON.parse(readFileSync(args['event-path'], 'utf8'));
    const pr = ev.pull_request ?? {};
    return {
      body: pr.body ?? '',
      prMeta: {
        headRef: pr.head?.ref ?? '',
        headRepo: pr.head?.repo?.full_name ?? '',
        baseRepo: pr.base?.repo?.full_name ?? '',
        actor: pr.user?.login ?? '',
      },
    };
  }
  console.error('[cross-ai-audit] ERROR: --event-path veya --body-file gerekli');
  exit(2);
}

// Codex `019e2693` MED-4 + PR #589 parser bug fix + Codex `019e26ae` field-aware refactor:
// PR body'sinde birden fazla "## Cross-AI" heading olabilir (audit summary + field block sıralı/ters).
// Doğru kural: required field'ları İÇEREN son strict section; yoksa required field'ları içeren son
// permissive section. Hiç valid candidate yoksa son strict/permissive section (diagnostic için).

const REQUIRED_FIELD_KEYS = ['implementer ai', 'reviewer ai', 'codex thread', 'verdict'];

function collectHeadingSections(body, strictMode) {
  const lines = body.split(/\r?\n/);
  const matches = [];
  let inSection = false;
  let currentSection = [];
  const headingRe = strictMode
    ? /^##\s+Cross-AI\s*$/i  // strict: exact "## Cross-AI" only
    : /^##\s+Cross-AI/i;     // permissive: trailing text allowed

  for (const line of lines) {
    if (headingRe.test(line)) {
      if (inSection) {
        matches.push(currentSection.join('\n'));
      }
      inSection = true;
      currentSection = [];
      continue;
    }
    if (inSection && /^##\s+/.test(line)) {
      matches.push(currentSection.join('\n'));
      inSection = false;
      currentSection = [];
      continue;
    }
    if (inSection) {
      currentSection.push(line);
    }
  }
  if (inSection) {
    matches.push(currentSection.join('\n'));
  }
  return matches;
}

function sectionHasRequiredFields(section) {
  // Codex `019e26ae` tur-2 absorb: use real extractFields() parser (colon-form YAML field),
  // not `.includes()` heuristic — audit table column headers da "Implementer AI" içerebilir
  // ama gerçek YAML key:value değildir. Field-aware selection parser semantik uyumlu olmalı.
  const fields = extractFields(section);
  return REQUIRED_FIELD_KEYS.every((k) => fields[k]);
}

function extractCrossAiSection(body) {
  // Pass 1: strict candidates
  const strictMatches = collectHeadingSections(body, true);

  // Pass 2: permissive candidates (excluded strict matches dahil, regex match'i überset)
  const permissiveMatches = collectHeadingSections(body, false);

  // Field-aware selection (Codex `019e26ae` blocking absorb):
  //   1. Last strict section with all required fields
  //   2. Last permissive section with all required fields
  //   3. Fallback: last strict (diagnostic), then last permissive (diagnostic)

  const lastValidStrict = [...strictMatches].reverse().find(sectionHasRequiredFields);
  if (lastValidStrict !== undefined) return lastValidStrict;

  const lastValidPermissive = [...permissiveMatches].reverse().find(sectionHasRequiredFields);
  if (lastValidPermissive !== undefined) return lastValidPermissive;

  // Diagnostic fallback: hiç valid candidate yoksa son strict varsa onu, yoksa son permissive
  if (strictMatches.length > 0) return strictMatches[strictMatches.length - 1];
  if (permissiveMatches.length > 0) return permissiveMatches[permissiveMatches.length - 1];
  return '';
}

// Inline YAML comment strip + key/value extract from Cross-AI section
function extractFields(section) {
  const fields = {};
  // Strip fenced code block markers
  const cleaned = section.replace(/```[a-z]*\n?/g, '').replace(/```/g, '');
  const lines = cleaned.split(/\r?\n/);
  const keyRe = /^\s*(Implementer AI|Reviewer AI|Codex thread|Verdict|Verdict reason|Same-provider exception|Exception reason|Cross-AI exempt reason|Absorb edilen düzeltmeler|Automation source|Automation evidence)\s*:\s*(.*?)\s*$/i;
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

// ── Automation-PR exemption audit (#827) ──────────────────────────────────
// Runs INSTEAD of audit() when the PR head branch matches an automation
// prefix. A PR is exempt from the cross-AI peer-review requirement iff every
// check below passes — proof the PR is a known, in-repo, bot-authored
// automation artifact, NOT a fabricated peer review.
function auditAutomation(body, prMeta) {
  const findings = [];
  const prefix = matchedAutomationPrefix(prMeta.headRef);
  const expectedSource = AUTOMATION_BRANCH_CONTRACT[prefix];

  // 1. same-repo — a fork PR can never claim the automation exemption
  const sameRepo =
    !!prMeta.headRepo && !!prMeta.baseRepo && prMeta.headRepo === prMeta.baseRepo;
  findings.push({
    check: 'automation_same_repo',
    pass: sameRepo,
    detail: sameRepo
      ? `head & base both "${prMeta.baseRepo}"`
      : `fork PR ("${prMeta.headRepo}" != "${prMeta.baseRepo}") — not exemption-eligible`,
  });

  // 2. head branch in the automation prefix allowlist (re-asserted for the report)
  findings.push({
    check: 'automation_branch_allowlist',
    pass: true,
    detail: `head.ref "${prMeta.headRef}" matches allowlisted prefix "${prefix}"`,
  });

  // 3. actor allowlist — the hard gate against human-authored spoofing. A
  //    human PR has a human actor and can never satisfy this. (Not full bot
  //    isolation: github-actions[bot] is shared across workflows — the wider
  //    contract chain + a future diff path allowlist bound a compromised bot.)
  const actorOk = AUTOMATION_ACTORS.has(prMeta.actor);
  findings.push({
    check: 'automation_actor_allowlist',
    pass: actorOk,
    detail: actorOk
      ? `actor "${prMeta.actor}" is an allowlisted automation bot`
      : `actor "${prMeta.actor}" is not an automation bot — exemption denied`,
  });

  // PR-body ## Cross-AI section fields
  const section = extractCrossAiSection(body);
  const fields = section ? extractFields(section) : {};

  // 4. Automation source field present AND 1:1-consistent with the branch prefix
  const src = fields['automation source'] || '';
  if (!src) {
    findings.push({
      check: 'automation_source_field',
      pass: false,
      detail: '`Automation source:` field missing from the ## Cross-AI section',
    });
  } else if (src !== expectedSource) {
    findings.push({
      check: 'automation_source_field',
      pass: false,
      detail: `Automation source "${src}" does not match the contract "${expectedSource}" for prefix "${prefix}"`,
    });
  } else {
    findings.push({
      check: 'automation_source_field',
      pass: true,
      detail: `Automation source matches contract: ${src}`,
    });
  }

  // 5. Cross-AI exempt reason — an explicit, non-trivial statement
  const reason = fields['cross-ai exempt reason'] || '';
  findings.push({
    check: 'automation_exempt_reason',
    pass: reason.length >= 10,
    detail:
      reason.length >= 10
        ? `Cross-AI exempt reason provided (${reason.length}c)`
        : '`Cross-AI exempt reason:` missing or shorter than 10 chars',
  });

  // 6. Automation evidence — a non-empty link to the generating run / report
  const evidence = fields['automation evidence'] || '';
  findings.push({
    check: 'automation_evidence',
    pass: evidence.length > 0,
    detail: evidence.length > 0
      ? 'Automation evidence link present'
      : '`Automation evidence:` field missing or empty',
  });

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
const { body, prMeta } = loadInput(args);
const automationPrefix = prMeta ? matchedAutomationPrefix(prMeta.headRef) : null;
let findings;
if (automationPrefix) {
  console.log(
    `[cross-ai-audit] automation-PR exemption mode — head.ref "${prMeta.headRef}" matches "${automationPrefix}"`,
  );
  findings = auditAutomation(body, prMeta);
} else {
  findings = audit(body);
}
const ok = report(findings);
exit(ok ? 0 : 1);
