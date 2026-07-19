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
//   node scripts/ci/pr-cross-ai-audit.mjs --body-file <path> \
//     --base-tip-sha <sha> --head-sha <sha> --evidence-file <json-map>
//
// Exit codes:
//   0 — PASS
//   1 — FAIL (cross-ai violation)
//   2 — INPUT ERROR

import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { argv, env, exit } from 'node:process';

const VALID_PROVIDERS = new Set(['claude', 'codex', 'gemini', 'other']);
const VALID_VERDICTS = new Set(['AGREE', 'REVISE', 'PARTIAL', 'RED']);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const COMMIT_SHA_RE = /^[0-9a-f]{40}$/i;
const SHA256_RE = /^[0-9a-f]{64}$/i;
const EVIDENCE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const EVIDENCE_FUTURE_SKEW_MS = 5 * 60 * 1000;
const NO_FINDINGS_RE = /^None$/;
const EMAIL_RE = /(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])/;
const TURKISH_PHONE_RE = /(?<!\d)(?:\+90|0090|0)\s*\(?5\d{2}\)?(?:[ .-]*\d){7}(?!\d)/;
const PRIVATE_KEY_RE = /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/;
const BEARER_RE = /(?<![A-Za-z0-9])bearer[ \t]+[A-Za-z0-9._~+/=-]{12,}/i;
const JWT_RE = /(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])/;
const KNOWN_TOKEN_RE = /(?<![A-Za-z0-9])(?:(?:AKIA|ASIA)[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,}|sk_live_[A-Za-z0-9]{16,})(?![A-Za-z0-9])/;
const SECRET_ASSIGNMENT_RE = /\b(?:password|passwd|pwd|api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|session[_-]?secret|secret[_-]?access[_-]?key|service[_-]?account[_-]?key|signing[_-]?key|hmac[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*["']?[A-Za-z0-9._~+/=-]{12,}["']?/i;
const WEBHOOK_URL_RE = /\bwebhook[_-]?url\b\s*[:=]\s*https?:\/\/[^\s"'<>]{12,}/i;
const COOKIE_HEADER_RE = /^[ \t]*(?:set-)?cookie[ \t]*:[ \t]*[^\r\n]{12,}$/im;
const RECEIPT_KEYS = new Set([
  'provider', 'requested', 'actual', 'base_tip', 'base', 'head', 'scope',
  'effort', 'sandbox', 'ephemeral', 'verdict', 'ref', 'sha256',
]);
const EVIDENCE_KEYS = [
  'actual_model', 'base_sha', 'base_tip_sha', 'ephemeral', 'head_sha',
  'provider', 'reasoning_effort', 'requested_model', 'response',
  'response_sha256', 'sandbox', 'schema', 'scope_sha256', 'verdict',
];
const FULLATS_ROLLBACK_ATTESTATION_KEYS = [
  'base_sha', 'branch', 'changed_diff_sha256', 'expected_paths', 'head_sha',
  'promotion_base_sha', 'promotion_head_sha', 'promotion_merge_sha',
  'promotion_pr', 'promotion_scope_sha256', 'schema', 'source', 'valid',
];
const FULLATS_ROLLBACK_PATHS = [
  'kustomize/overlays/test/fullats-promotion-state.txt',
  'kustomize/overlays/test/kustomization.yaml',
];
const FULLATS_PROMOTION_BASE_SHA = 'aa93f4743dc8254ce8e22a0317f92db1f5819268';
const DOCS_ONLY_EXEMPT_ALLOWLIST = [
  /^docs\/session-handoff-[^/]+\.md$/,
  /^docs\/archive\/[^/]+\.md$/,
];
const CONSULTATION_RECEIPTS = {
  'codex receipt': {
    provider: 'openai',
  },
};
const ROUTINE_CODEX_MODEL = 'gpt-5.3-codex-spark';
const HIGH_IMPACT_CODEX_MODEL = 'gpt-5.6-sol';
const REQUIRED_REASONING_EFFORT = 'xhigh';
const REQUIRED_SANDBOX = 'read-only';
const FORBIDDEN_CONSULTATION_FIELDS = new Set(['claude receipt', 'minimax receipt']);
const CONSULTATION_MODES = new Set(['none', 'single']);
const CONSULTATION_GOVERNANCE_PATHS = [
  /^AGENTS\.md$/,
  /^CLAUDE\.md$/,
  /^docs\/context-priority-rules\.md$/,
  /^\.github\/pull_request_template\.md$/,
  /^\.github\/workflows\/gate-cross-ai-audit\.yml$/,
  /^scripts\/ci\/pr-cross-ai-audit\.mjs$/,
  // Tombstone: deleting the retired wrapper remains a governance change, and
  // any future MiniMax-named review helper cannot be reintroduced under none.
  /^scripts\/ai\/[^/]*minimax[^/]*\.py$/i,
  /^scripts\/ai\/(?:prepare_cross_ai_scope|build_cross_ai_evidence|post_cross_ai_evidence)\.py$/,
  /^tests\/ci\/test-cross-ai-automation\.mjs$/,
  /^tests\/deploy\/test_faz25_fullats_gitops_contract\.py$/,
];
const CONSULTATION_AT_LEAST_SINGLE_HIGH_RISK_PATHS = [
  /(?:^|\/)(?:[^/]+[-_.])?(?:rbac|clusterrole|clusterrolebinding|role|rolebinding|networkpolicy|externalsecret|clusterexternalsecret|secretstore|clustersecretstore)(?:[-_.][^/]*)?\.ya?ml$/i,
  /(?:^|\/)vault\/polic(?:y|ies)\/[^/]+\.hcl$/i,
  /(?:^|\/)(?:db\/migration|migrations?)(?:\/|$)/i,
  /^kustomize\/overlays\/prod\//i,
  /^host-compose\/[^/]+\/prod\//i,
  /^\.github\/workflows\/[^/]*(?:prod|production|cutover)[^/]*\.ya?ml$/i,
];
const CONSULTATION_AT_LEAST_SINGLE_BRANCH_PREFIXES = ['auto-promotion/'];
const PLACEHOLDER_WORD_RE = /\b(?:todo|tbd|fixme|placeholder|dummy|example|unknown)\b/i;
const NON_ACTIONABLE_SENTINEL_RE = /^(?:n\/a|none)$/i;
const EXPLICIT_MODE_LEGACY_FIELDS = [
  'reviewer ai',
  'codex thread',
  'verdict reason',
  'same-provider exception',
  'exception reason',
  'cross-ai exempt reason',
  'absorb edilen düzeltmeler',
  'automation source',
  'automation evidence',
];
const DUPLICATE_FIELDS = Symbol('duplicate-fields');

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
  'auto-test-frontend/': '.github/workflows/deploy-testai.yml',
  'auto-fullats-rollback/': '.github/workflows/faz25-fullats-live-browser-acceptance.yml',
  'auto-verified/': 'scripts/promotion/ledger-mark-verified.sh',
};
// Per-prefix actor contract (#827 PR-B, Codex `019e4048` Q2 REVISE). Each
// automation prefix binds to the specific bot identity authorised to open its
// PRs; a single global actor set would let any allowlisted bot claim any
// prefix. The `auditAutomation` actor check requires BOTH the PR author and
// the event sender to be in the matched prefix's set.
//
// `auto-test-overlay/` and `auto-test-frontend/` are opened via a GitHub App
// installation token — NOT GITHUB_TOKEN. A GITHUB_TOKEN-opened PR
// does not trigger the `pull_request` workflows the required `cross-ai-audit`
// check needs, so the App is mandatory; its bot login is
// `platform-gitops-automation[bot]` (the operator names the GitHub App so its slug
// resolves to `platform-gitops-automation` — see
// docs/operations/RUNBOOKS/RB-automation-overlay-sync.md).
//
// Production `auto-promotion/` is intentionally absent: it changes prod
// desired state and therefore must pass the normal explicit consultation-mode path.
// `auto-verified/` keeps `github-actions[bot]` from #827 PR-A:
// ledger-mark-verified.sh runs on a staging-sw host (not GitHub Actions), so
// migrating it to a host-minted App token is a separate follow-up
// (#842 / Codex `019e4094` Q3).
const AUTOMATION_PREFIX_ACTORS = {
  'auto-test-overlay/': new Set(['platform-gitops-automation[bot]']),
  'auto-test-frontend/': new Set(['platform-gitops-automation[bot]']),
  'auto-fullats-rollback/': new Set(['platform-gitops-automation[bot]']),
  'auto-verified/': new Set(['github-actions[bot]']),
};

// Every automation bot is further bounded to the exact file family its
// deterministic writer owns. A compromised bot identity therefore cannot use
// the cross-AI exemption to carry an unrelated source, workflow, or governance
// change. Regexes are anchored and deliberately do not accept subdirectories
// unless the writer's contract explicitly owns them.
const AUTOMATION_DIFF_ALLOWLIST = {
  'auto-test-overlay/': [
    /^kustomize\/overlays\/test\/kustomization\.yaml$/,
    /^kustomize\/overlays\/test\/activation\/endpoint-admin-remote-bridge\/kustomization\.yaml$/,
    /^kustomize\/overlays\/test\/activation\/endpoint-admin-remote-bridge-device-key\/kustomization\.yaml$/,
  ],
  'auto-test-frontend/': [
    /^kustomize\/overlays\/test\/kustomization\.yaml$/,
  ],
  // Faz 25 #2615: failure compensator can restore only the frontend pin in
  // the test overlay and the explicit promotion marker. ATS and permission
  // artifacts stay on the already-validated current baseline.
  // It cannot carry workflow/governance/application changes in its bot PR.
  'auto-fullats-rollback/': [
    /^kustomize\/overlays\/test\/fullats-promotion-state\.txt$/,
    /^kustomize\/overlays\/test\/kustomization\.yaml$/,
  ],
  'auto-verified/': [
    /^release-candidates\/(?:platform-agent|platform-backend|platform-web)\/[0-9a-f]{40}\.json$/,
  ],
};

function matchedAutomationPrefix(headRef) {
  return (
    Object.keys(AUTOMATION_BRANCH_CONTRACT).find((p) => headRef.startsWith(p)) ?? null
  );
}

// ── Dependabot bot PR exemption (#898, Codex `019e4517` AGREE 3-iter consensus) ─
// A Dependabot-opened PR is a non-AI, machine-generated dependency bump that
// cannot satisfy the cross-AI peer-review claim (the bot is not an AI, and
// dep-version bumps are ADR-0011 §2.3.1 "none of the above" boundary class).
// Exemption is fail-closed and bounded by FIVE gates running together:
//   1. branch prefix `dependabot/` (Dependabot's deterministic head ref)
//   2. same-repo (fork PR named `dependabot/foo` is blocked)
//   3. PR author = `dependabot[bot]` (immutable once opened)
//   4. event sender = `dependabot[bot]` (blocks human `synchronize`/`labeled`)
//   5. changed-files list present AND every path matches the diff allowlist
//
// Diff allowlist is intentionally NARROW — only `.github/workflows/*.{yml,yaml}`.
// `.github/dependabot.yml` config in this repo only enables the `github-actions`
// ecosystem; widening to `pom.xml`, `package.json`, `requirements*.txt`, etc.
// requires a separate consensus iteration. Helm/Kustomize/Dockerfile paths are
// deliberately excluded — GitOps runtime state / deploy manifests are governed
// by Renovate-class promotion flows, not Dependabot exemption.
//
// If branch prefix is `dependabot/` but ANY gate fails, the exemption is denied
// with a `dependabot_*` finding — the audit does NOT fall back to normal body
// audit. A spoofed `dependabot/*` head with a forged PR body must fail closed.
const DEPENDABOT_BRANCH_PREFIX = 'dependabot/';
const DEPENDABOT_ACTOR = 'dependabot[bot]';
const DEPENDABOT_DIFF_ALLOWLIST = [
  /^\.github\/workflows\/[^/]+\.ya?ml$/,
];

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

// Read PR changed-files list from a workflow-prepared text file (one path per
// line). Returns `null` if the flag is absent (local-test mode or older
// workflow). The Dependabot lane treats `null`/empty as fail-closed via the
// `dependabot_changed_files_present` check.
function readChangedFiles(args) {
  if (!args['changed-files-file']) return null;
  return readFileSync(args['changed-files-file'], 'utf8')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function readAutomationContentAttestation(args) {
  if (!args['automation-content-attestation-file']) return null;
  const parsed = JSON.parse(
    readFileSync(args['automation-content-attestation-file'], 'utf8'),
  );
  return parsed && !Array.isArray(parsed) && typeof parsed === 'object'
    ? parsed
    : null;
}

function readEvidenceOverrides(args) {
  if (!args['evidence-file']) return {};
  if (args['allow-local-evidence-override'] !== 'true') {
    throw new Error('evidence-file icin explicit allow-local-evidence-override=true gerekir');
  }
  if (env.GITHUB_ACTIONS === 'true') {
    throw new Error('evidence-file GitHub Actions event modunda yasaktır');
  }
  const parsed = JSON.parse(readFileSync(args['evidence-file'], 'utf8'));
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('evidence-file object map olmalı');
  }
  return parsed;
}

function loadInput(args) {
  if (args['body-file']) {
    // Local test mode still requires explicit head metadata; exact-head
    // consultation must never silently degrade to a body-only declaration.
    return {
      body: readFileSync(args['body-file'], 'utf8'),
      prMeta: {
        headRef: '',
        headSha: args['head-sha'] ?? '',
        baseSha: args['base-tip-sha'] ?? '',
        derivedBaseSha: args['derived-base-sha'] ?? '',
        derivedScopeSha256: args['derived-scope-sha256'] ?? '',
        headRepo: '',
        baseRepo: '',
        actor: '',
        sender: '',
        changedFiles: readChangedFiles(args),
        automationContentAttestation: readAutomationContentAttestation(args),
      },
    };
  }
  if (args['event-path']) {
    const ev = JSON.parse(readFileSync(args['event-path'], 'utf8'));
    const pr = ev.pull_request ?? {};
    return {
      body: pr.body ?? '',
      prMeta: {
        headRef: pr.head?.ref ?? '',
        headSha: pr.head?.sha ?? '',
        baseSha: pr.base?.sha ?? '',
        derivedBaseSha: args['derived-base-sha'] ?? '',
        derivedScopeSha256: args['derived-scope-sha256'] ?? '',
        headRepo: pr.head?.repo?.full_name ?? '',
        baseRepo: pr.base?.repo?.full_name ?? '',
        // `actor` = PR author (immutable once opened). `sender` = who
        // triggered THIS event. Both must be a bot for the exemption — else a
        // human could push a `synchronize` commit to / `edited` the body of a
        // bot-opened auto-PR (pr.user stays the bot; sender is the human).
        actor: pr.user?.login ?? '',
        sender: ev.sender?.login ?? '',
        // Dependabot exemption needs the diff allowlist gate; the workflow
        // pre-fetches the file list via `gh api ... --paginate` to avoid both
        // `pull_request_target` permission expansion and giving the script
        // direct GitHub API access.
        changedFiles: readChangedFiles(args),
        automationContentAttestation: readAutomationContentAttestation(args),
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
  // Presence is authoritative even when the value is empty. Otherwise an
  // explicitly declared but empty mode could fall through to the legacy
  // three-receipt contract and bypass the invalid-mode fail-closed check.
  if (Object.hasOwn(fields, 'consultation mode')) {
    return Boolean(
      fields['implementer ai']
      && fields['consultation reason']
    );
  }
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
  const duplicateFields = new Set();
  // Strip fenced code block markers
  const cleaned = section.replace(/```[a-z]*\n?/g, '').replace(/```/g, '');
  const lines = cleaned.split(/\r?\n/);
  const keyRe = /^\s*(Implementer AI|Reviewer AI|Codex thread|Verdict|Verdict reason|Same-provider exception|Exception reason|Cross-AI exempt reason|Absorb edilen düzeltmeler|Consultation mode|Consultation reason|Risk trigger|Consultation base tip|Consultation base|Consultation commit|Consultation scope|Claude receipt|MiniMax receipt|Codex receipt|Automation source|Automation evidence)\s*:\s*(.*?)\s*$/i;
  for (const line of lines) {
    const m = line.match(keyRe);
    if (m) {
      const key = m[1].toLowerCase();
      if (Object.hasOwn(fields, key)) duplicateFields.add(key);
      let val = m[2];
      // Strip inline YAML comments (e.g. "Claude # one of [...]")
      const commentIdx = val.indexOf('#');
      if (commentIdx >= 0) val = val.slice(0, commentIdx);
      // Strip surrounding quotes/backticks
      val = val.replace(/^[`"']|[`"']$/g, '').trim();
      // Presence itself matters for incompatible legacy controls. Preserve an
      // explicit empty value so `Consultation mode` cannot hide `Reviewer AI:`
      // or another deprecated key by leaving only its value blank.
      fields[key] = val;
    }
  }
  fields[DUPLICATE_FIELDS] = [...duplicateFields];
  return fields;
}

function appendDuplicateFieldFinding(findings, fields) {
  const duplicates = fields[DUPLICATE_FIELDS] ?? [];
  findings.push({
    check: 'cross_ai_structured_fields_unique',
    pass: duplicates.length === 0,
    detail: duplicates.length === 0
      ? 'structured Cross-AI field keys are unique'
      : `Yinelenen structured Cross-AI field reddedildi: ${duplicates.join(', ')}`,
  });
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

function meaningfulStatement(value) {
  const clean = (value || '').trim();
  const words = clean.toLowerCase().match(/[\p{L}\p{N}][\p{L}\p{N}_-]*/gu) ?? [];
  return clean.length >= 10
    && !/[<>]/.test(clean)
    && !PLACEHOLDER_WORD_RE.test(clean)
    && !NON_ACTIONABLE_SENTINEL_RE.test(clean)
    && words.length >= 3
    && new Set(words).size >= 3;
}

function minimumConsultationMode(prMeta) {
  const files = prMeta?.changedFiles;
  // Missing event-bound scope metadata must never silently authorize `none`.
  // Raising the floor to `single` is the intentional fail-closed fallback.
  if (!Array.isArray(files) || files.length === 0) {
    return { mode: 'single', reason: 'changed-files metadata missing' };
  }
  const governancePath = files.find((path) =>
    CONSULTATION_GOVERNANCE_PATHS.some((pattern) => pattern.test(path))
  );
  if (governancePath) {
    return { mode: 'single', reason: `consultation governance path: ${governancePath}` };
  }
  const branchPrefix = CONSULTATION_AT_LEAST_SINGLE_BRANCH_PREFIXES.find((prefix) =>
    (prMeta?.headRef || '').startsWith(prefix)
  );
  if (branchPrefix) {
    return { mode: 'single', reason: `production promotion branch: ${branchPrefix}` };
  }
  const highRiskPath = files.find((path) =>
    CONSULTATION_AT_LEAST_SINGLE_HIGH_RISK_PATHS.some((pattern) => pattern.test(path))
  );
  if (highRiskPath) {
    return { mode: 'single', reason: `high-confidence risk path: ${highRiskPath}` };
  }
  return { mode: 'none', reason: 'routine scope' };
}

function expectedConsultationModel(prMeta) {
  return minimumConsultationMode(prMeta).mode === 'single'
    ? HIGH_IMPACT_CODEX_MODEL
    : ROUTINE_CODEX_MODEL;
}

function parseReceipt(value) {
  if (!value) return null;
  const parsed = {};
  for (const item of value.split(';')) {
    const separator = item.indexOf('=');
    if (separator < 1) return null;
    const key = item.slice(0, separator).trim().toLowerCase();
    const val = item.slice(separator + 1).trim();
    if (!RECEIPT_KEYS.has(key) || !val || Object.hasOwn(parsed, key)) return null;
    parsed[key] = val;
  }
  return Object.keys(parsed).length === RECEIPT_KEYS.size ? parsed : null;
}

function validEvidenceRef(value, baseRepo) {
  if (!value || !baseRepo) return false;
  try {
    const url = new URL(value);
    const prefix = `/repos/${baseRepo}/issues/comments/`;
    const commentId = url.pathname.toLowerCase().startsWith(prefix.toLowerCase())
      ? url.pathname.slice(prefix.length)
      : '';
    return url.protocol === 'https:'
      && url.hostname === 'api.github.com'
      && url.search === ''
      && url.hash === ''
      && /^\d+$/.test(commentId);
  } catch {
    return false;
  }
}

function sha256Utf8(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

function parseProviderResponseVerdict(response) {
  if (typeof response !== 'string') return null;
  const matches = [...response.matchAll(/^VERDICT:[ \t]*(AGREE|REVISE)[ \t]*$/gm)];
  const lines = response.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (matches.length !== 1 || !lines.length || !/^VERDICT:[ \t]*(AGREE|REVISE)[ \t]*$/.test(lines.at(-1))) {
    return null;
  }
  const headingRe = /^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?(P[012])(?:\*\*)?(?:[ \t]*[—:-].*)?[ \t]*$/gim;
  const headings = [...response.matchAll(headingRe)];
  if (headings.map((match) => match[1].toUpperCase()).join(',') !== 'P0,P1,P2') {
    return null;
  }
  const sectionContents = headings.map((heading, index) => {
    const start = heading.index + heading[0].length;
    const end = index < 2 ? headings[index + 1].index : matches[0].index;
    return response.slice(start, end).trim();
  });
  if (sectionContents.some((content) => content.length === 0)) return null;
  const verdict = matches[0][1].toUpperCase();
  if (verdict === 'AGREE' && (
    !NO_FINDINGS_RE.test(sectionContents[0]) || !NO_FINDINGS_RE.test(sectionContents[1])
  )) return null;
  return verdict;
}

function containsSensitiveResponse(response) {
  return EMAIL_RE.test(response)
    || TURKISH_PHONE_RE.test(response)
    || PRIVATE_KEY_RE.test(response)
    || BEARER_RE.test(response)
    || JWT_RE.test(response)
    || KNOWN_TOKEN_RE.test(response)
    || SECRET_ASSIGNMENT_RE.test(response)
    || WEBHOOK_URL_RE.test(response)
    || COOKIE_HEADER_RE.test(response);
}

async function loadEvidenceComment(ref, baseRepo, evidenceOverrides) {
  if (Object.hasOwn(evidenceOverrides, ref)) {
    const override = evidenceOverrides[ref];
    return override && typeof override === 'object' ? override : null;
  }
  if (!validEvidenceRef(ref, baseRepo)) return null;
  const headers = { Accept: 'application/vnd.github+json' };
  const token = env.GITHUB_TOKEN || env.GH_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const response = await fetch(ref, {
      headers,
      signal: AbortSignal.timeout(15_000),
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return {
      body: payload?.body,
      author: payload?.user?.login,
      authorAssociation: payload?.author_association,
      createdAt: payload?.created_at,
      updatedAt: payload?.updated_at,
    };
  } catch {
    return null;
  }
}

function evidenceMatches(
  comment, receipt, expected, expectedOwner, baseTip, base, head, scope,
) {
  const createdAtMs = Date.parse(comment?.createdAt || '');
  const evidenceAgeMs = Date.now() - createdAtMs;
  if (
    !comment
    || typeof comment.body !== 'string'
    || typeof comment.author !== 'string'
    || comment.author.toLowerCase() !== expectedOwner.toLowerCase()
    || comment.authorAssociation !== 'OWNER'
    || !comment.createdAt
    || comment.createdAt !== comment.updatedAt
    || !Number.isFinite(createdAtMs)
    || evidenceAgeMs < -EVIDENCE_FUTURE_SKEW_MS
    || evidenceAgeMs > EVIDENCE_MAX_AGE_MS
    || sha256Utf8(comment.body) !== receipt.sha256.toLowerCase()
  ) return false;
  let evidence;
  try {
    evidence = JSON.parse(comment.body);
  } catch {
    return false;
  }
  if (!evidence || Array.isArray(evidence) || typeof evidence !== 'object') return false;
  const keys = Object.keys(evidence).sort();
  if (keys.length !== EVIDENCE_KEYS.length || keys.some((key, index) => key !== EVIDENCE_KEYS[index])) {
    return false;
  }
  const responseVerdict = parseProviderResponseVerdict(evidence.response);
  return Boolean(
    evidence.schema === 'cross-ai-provider-evidence/v2'
    && evidence.provider === expected.provider
    && evidence.requested_model === expected.model
    && evidence.actual_model === expected.model
    && evidence.reasoning_effort === REQUIRED_REASONING_EFFORT
    && evidence.sandbox === REQUIRED_SANDBOX
    && evidence.ephemeral === true
    && evidence.base_tip_sha?.toLowerCase() === baseTip.toLowerCase()
    && evidence.base_sha?.toLowerCase() === base.toLowerCase()
    && evidence.head_sha?.toLowerCase() === head.toLowerCase()
    && evidence.scope_sha256?.toLowerCase() === scope.toLowerCase()
    && evidence.verdict === 'AGREE'
    && responseVerdict === evidence.verdict
    && typeof evidence.response === 'string'
    && evidence.response.length > 0
    && !containsSensitiveResponse(evidence.response)
    && SHA256_RE.test(evidence.response_sha256 || '')
    && sha256Utf8(evidence.response) === evidence.response_sha256.toLowerCase()
  );
}

function docsOnlyExemption(fields, prMeta) {
  const requested = (fields['codex thread'] || '').trim().toLowerCase() === 'n/a';
  if (!requested) return { requested: false, pass: false, detail: '' };
  const reason = fields['cross-ai exempt reason'] || '';
  const files = prMeta?.changedFiles;
  const filesPresent = Array.isArray(files) && files.length > 0;
  const pathsAllowed = filesPresent && files.every((path) =>
    DOCS_ONLY_EXEMPT_ALLOWLIST.some((pattern) => pattern.test(path))
  );
  const pass = reason.length >= 10 && pathsAllowed;
  return {
    requested: true,
    pass,
    detail: pass
      ? `dar historical-docs allowlist doğrulandı (${files.length} path)`
      : 'N/A yalnız event-bound changed-files listesi tamamen historical docs allowlist içindeyse geçerlidir',
  };
}

async function appendConsultationFindings(
  findings,
  fields,
  prMeta,
  evidenceOverrides,
  receiptFields = Object.keys(CONSULTATION_RECEIPTS),
) {
  const expectedOwner = (prMeta?.baseRepo || '').split('/')[0];
  const baseTip = fields['consultation base tip'] || '';
  const base = fields['consultation base'] || '';
  const commit = fields['consultation commit'] || '';
  const scope = fields['consultation scope'] || '';
  const validBaseTip = COMMIT_SHA_RE.test(baseTip);
  const baseTipPresent = COMMIT_SHA_RE.test(prMeta?.baseSha || '');
  const baseTipMatches = baseTipPresent && baseTip.toLowerCase() === prMeta.baseSha.toLowerCase();
  const validBase = COMMIT_SHA_RE.test(base);
  const derivedBasePresent = COMMIT_SHA_RE.test(prMeta?.derivedBaseSha || '');
  const derivedBaseMatches = derivedBasePresent
    && base.toLowerCase() === prMeta.derivedBaseSha.toLowerCase();
  const validFormat = COMMIT_SHA_RE.test(commit);
  const headPresent = COMMIT_SHA_RE.test(prMeta?.headSha || '');
  const matchesHead = headPresent && commit.toLowerCase() === prMeta.headSha.toLowerCase();
  const validScope = SHA256_RE.test(scope);
  const derivedScopePresent = SHA256_RE.test(prMeta?.derivedScopeSha256 || '');
  const derivedScopeMatches = derivedScopePresent
    && scope.toLowerCase() === prMeta.derivedScopeSha256.toLowerCase();
  findings.push({
    check: 'consultation_base_tip_exact_event',
    pass: validBaseTip && baseTipMatches,
    detail: !validBaseTip
      ? 'Consultation base tip 40-char git SHA değil'
      : !baseTipPresent
        ? 'PR base SHA metadata eksik; base binding fail-closed'
        : baseTipMatches
          ? `consultation base tip ${baseTip.slice(0, 12)} event ile eşleşiyor`
          : `consultation base tip ${baseTip.slice(0, 12)} PR base ${prMeta.baseSha.slice(0, 12)} ile eşleşmiyor`,
  });
  findings.push({
    check: 'consultation_base_format',
    pass: validBase,
    detail: validBase ? `consultation base ${base.slice(0, 12)} formatı geçerli` : 'Consultation base 40-char git SHA değil',
  });
  findings.push({
    check: 'consultation_base_exact_ci_merge_base',
    pass: validBase && derivedBaseMatches,
    detail: !derivedBasePresent
      ? 'CI-derived merge-base eksik; fail-closed'
      : derivedBaseMatches
        ? `consultation base ${base.slice(0, 12)} CI git merge-base ile eşleşiyor`
        : `consultation base ${base.slice(0, 12)} CI merge-base ${prMeta.derivedBaseSha.slice(0, 12)} ile eşleşmiyor`,
  });
  findings.push({
    check: 'consultation_commit_exact_head',
    pass: validFormat && matchesHead,
    detail: !validFormat
      ? 'Consultation commit 40-char git SHA değil'
        : !headPresent
          ? 'PR head SHA metadata eksik; exact-head binding fail-closed'
          : matchesHead
        ? `consultation commit ${commit.slice(0, 12)} exact-head ile eşleşiyor`
        : `consultation commit ${commit.slice(0, 12)} PR head ${prMeta.headSha.slice(0, 12)} ile eşleşmiyor`,
  });
  findings.push({
    check: 'consultation_scope_sha256',
    pass: validScope,
    detail: validScope ? `consultation scope sha256 ${scope.slice(0, 12)} formatı geçerli` : 'Consultation scope 64-char SHA-256 değil',
  });
  findings.push({
    check: 'consultation_scope_exact_ci_derivation',
    pass: validScope && derivedScopeMatches,
    detail: !derivedScopePresent
      ? 'CI-derived scope SHA-256 eksik; fail-closed'
      : derivedScopeMatches
        ? `consultation scope ${scope.slice(0, 12)} CI full-range derivation ile eşleşiyor`
        : `consultation scope ${scope.slice(0, 12)} CI-derived ${prMeta.derivedScopeSha256.slice(0, 12)} ile eşleşmiyor`,
  });

  const refs = [];
  for (const field of receiptFields) {
    const expected = {
      ...CONSULTATION_RECEIPTS[field],
      model: expectedConsultationModel(prMeta),
    };
    const receipt = parseReceipt(fields[field]);
    if (receipt?.ref) refs.push(receipt.ref);
    const shapePass = Boolean(
      receipt
      && receipt.provider?.toLowerCase() === expected.provider
      && receipt.requested === expected.model
      && receipt.actual === expected.model
      && receipt.effort === REQUIRED_REASONING_EFFORT
      && receipt.sandbox === REQUIRED_SANDBOX
      && receipt.ephemeral === 'true'
      && receipt.base_tip?.toLowerCase() === baseTip.toLowerCase()
      && receipt.base?.toLowerCase() === base.toLowerCase()
      && receipt.head?.toLowerCase() === commit.toLowerCase()
      && receipt.scope?.toLowerCase() === scope.toLowerCase()
      && receipt.verdict === 'AGREE'
      && validEvidenceRef(receipt.ref, prMeta?.baseRepo)
      && SHA256_RE.test(receipt.sha256 || '')
    );
    const evidenceComment = shapePass
      ? await loadEvidenceComment(receipt.ref, prMeta.baseRepo, evidenceOverrides)
      : null;
    const pass = shapePass && evidenceMatches(
      evidenceComment, receipt, expected, expectedOwner,
      baseTip, base, commit, scope,
    );
    findings.push({
      check: field.replaceAll(' ', '_'),
      pass,
      detail: pass
        ? `${expected.provider}/${expected.model}/${REQUIRED_REASONING_EFFORT} read-only ephemeral evidence + response digest + base/head/scope doğrulandı`
        : `${field}: scope sınıfına uygun exact model + xhigh/read-only/ephemeral receipt + matching GitHub evidence zorunlu`,
    });
  }
  findings.push({
    check: 'consultation_evidence_refs_unique',
    pass: refs.length === receiptFields.length && new Set(refs).size === receiptFields.length,
    detail: 'Seçilen provider receipt referansları birbirinden farklı olmalıdır',
  });
}

async function auditExplicitConsultationMode(fields, prMeta, evidenceOverrides) {
  const findings = [];
  const mode = (fields['consultation mode'] || '').trim().toLowerCase();
  const reason = (fields['consultation reason'] || '').trim();
  const implementer = normalizeProvider(fields['implementer ai']);
  const receiptNames = Object.keys(CONSULTATION_RECEIPTS);
  const presentReceipts = receiptNames.filter((field) => Object.hasOwn(fields, field));
  const forbiddenFields = [...FORBIDDEN_CONSULTATION_FIELDS].filter((field) =>
    Object.hasOwn(fields, field)
  );
  const requiredFloor = minimumConsultationMode(prMeta);
  const modeRank = { none: 0, single: 1 };
  const legacyFields = EXPLICIT_MODE_LEGACY_FIELDS.filter((field) =>
    Object.hasOwn(fields, field)
  );

  findings.push({
    check: 'consultation_mode_valid',
    pass: CONSULTATION_MODES.has(mode),
    detail: CONSULTATION_MODES.has(mode)
      ? `consultation mode ${mode}`
      : 'Consultation mode yalnız none veya single olabilir',
  });
  findings.push({
    check: 'consultation_reason_present',
    pass: meaningfulStatement(reason),
    detail: meaningfulStatement(reason)
      ? `consultation reason recorded (${reason.length}c)`
      : 'Consultation reason somut olmalı; placeholder/tekrarlı metin olamaz ve en az 10 karakter olmalıdır',
  });
  const implementerAllowed = Boolean(
    implementer === 'codex'
  );
  findings.push({
    check: 'implementer_provider_enum',
    pass: implementerAllowed,
    detail: implementerAllowed
      ? `implementer ${implementer}`
      : 'Yeni explicit-mode sözleşmesinde Implementer AI yalnız Codex olabilir',
  });
  findings.push({
    check: 'consultation_changed_files_present',
    pass: Array.isArray(prMeta?.changedFiles) && prMeta.changedFiles.length > 0,
    detail: Array.isArray(prMeta?.changedFiles) && prMeta.changedFiles.length > 0
      ? `${prMeta.changedFiles.length} changed file(s) classified`
      : 'changed-files metadata eksik; explicit mode fail-closed',
  });
  findings.push({
    check: 'consultation_mode_meets_scope_floor',
    pass: CONSULTATION_MODES.has(mode) && modeRank[mode] >= modeRank[requiredFloor.mode],
    detail: CONSULTATION_MODES.has(mode) && modeRank[mode] >= modeRank[requiredFloor.mode]
      ? `${requiredFloor.reason}; ${mode} floor'u karşılıyor`
      : `${requiredFloor.reason}; en az ${requiredFloor.mode} zorunlu`,
  });
  findings.push({
    check: 'consultation_explicit_mode_has_no_legacy_controls',
    pass: legacyFields.length === 0,
    detail: legacyFields.length === 0
      ? 'explicit mode legacy control field taşımıyor'
      : `Explicit mode ile uyumsuz legacy field: ${legacyFields.join(', ')}`,
  });
  // Claude and MiniMax are retired as accepted consultation channels. The
  // parser still recognizes both fields solely to reject them fail-closed.
  const retiredReceiptsRejected = forbiddenFields.length === 0;
  findings.push({
    check: 'consultation_retired_provider_receipts_rejected',
    pass: retiredReceiptsRejected,
    detail: retiredReceiptsRejected
      ? 'Claude ve MiniMax yeni istişare zincirinde receipt taşımıyor'
      : `Yasak provider receipt alanı: ${forbiddenFields.join(', ')}`,
  });

  if (mode === 'none') {
    const outcomeFields = [
      'verdict',
      'risk trigger',
      'consultation base tip',
      'consultation base',
      'consultation commit',
      'consultation scope',
    ];
    const presentOutcomeFields = outcomeFields.filter((field) => Object.hasOwn(fields, field));
    findings.push({
      check: 'consultation_none_has_no_receipts',
      pass: presentReceipts.length === 0,
      detail: presentReceipts.length === 0
        ? 'routine work carries no fabricated provider receipt'
        : 'Consultation mode none iken provider receipt bulunamaz',
    });
    findings.push({
      check: 'consultation_none_has_no_consultation_outcome_fields',
      pass: presentOutcomeFields.length === 0,
      detail: presentOutcomeFields.length === 0
        ? 'none mode binding, verdict veya risk trigger taşımıyor'
        : `none mode outcome/binding field taşıyamaz: ${presentOutcomeFields.join(', ')}`,
    });
    return findings;
  }

  const baseFields = [
    'consultation base tip',
    'consultation base',
    'consultation commit',
    'consultation scope',
  ];
  const missingBaseFields = baseFields.filter((field) => !fields[field]);
  findings.push({
    check: 'consultation_binding_fields_present',
    pass: missingBaseFields.length === 0,
    detail: missingBaseFields.length === 0
      ? 'exact consultation binding fields present'
      : `Eksik consultation binding field: ${missingBaseFields.join(', ')}`,
  });
  findings.push({
    check: 'consultation_verdict_agree',
    pass: fields.verdict === 'AGREE',
    detail: fields.verdict === 'AGREE'
      ? 'consultation verdict AGREE'
      : 'single consultation yalnız AGREE ile geçer',
  });

  const selectedReceipts = ['codex receipt'];
  if (mode === 'single') {
    findings.push({
      check: 'consultation_single_exact_channel_count',
      pass: presentReceipts.length === 1 && presentReceipts[0] === 'codex receipt',
      detail: `single mode exact direct OpenAI Codex ${expectedConsultationModel(prMeta)} xhigh read-only ephemeral channel requires one receipt`,
    });
    findings.push({
      check: 'consultation_single_has_no_risk_trigger',
      pass: !Object.hasOwn(fields, 'risk trigger'),
      detail: !Object.hasOwn(fields, 'risk trigger')
        ? 'single mode removed dual risk-trigger field taşımıyor'
        : 'Risk trigger Codex-only none|single sözleşmesinde kabul edilmez',
    });
  }

  // Run strict provider/evidence checks even when a binding field is missing.
  // The missing-field finding already fails the PR; this additionally prevents
  // a malformed or fabricated receipt from escaping diagnostics on that path.
  if (
    mode === 'single'
    && selectedReceipts.length === 1
  ) {
    await appendConsultationFindings(
      findings,
      fields,
      prMeta,
      evidenceOverrides,
      selectedReceipts,
    );
  }
  return findings;
}

async function audit(body, prMeta = null, evidenceOverrides = {}) {
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
  appendDuplicateFieldFinding(findings, fields);
  const forbiddenFields = [...FORBIDDEN_CONSULTATION_FIELDS].filter((field) =>
    Object.hasOwn(fields, field)
  );
  findings.push({
    check: 'consultation_has_no_forbidden_provider_receipt',
    pass: forbiddenFields.length === 0,
    detail: forbiddenFields.length === 0
      ? 'Claude ve MiniMax yeni istişare ve receipt zincirinde bulunmuyor'
      : `Yasak provider receipt alanı: ${forbiddenFields.join(', ')}`,
  });
  if (Object.hasOwn(fields, 'consultation mode')) {
    findings.push(...await auditExplicitConsultationMode(fields, prMeta, evidenceOverrides));
    return findings;
  }

  // Forward policy has no current legacy lane. Only the narrowly allowlisted
  // docs-only exemption may retain the old body shape; it produces no provider
  // receipt or acceptance authority. Every other PR must declare an explicit
  // none|single mode so legacy provider fields cannot bypass the mode floor.
  const exemption = docsOnlyExemption(fields, prMeta);
  if (!exemption.pass) {
    if (exemption.requested) {
      findings.push({
        check: 'cross_ai_docs_only_exemption',
        pass: false,
        detail: exemption.detail,
      });
    }
    findings.push({
      check: 'consultation_explicit_mode_required',
      pass: false,
      detail: 'Yeni PR yalnız explicit Consultation mode: none|single ile değerlendirilebilir; legacy receipt gövdesi acceptance üretmez',
    });
    return findings;
  }

  // Narrow historical-docs exemption only; no provider evidence is accepted.
  const consultationExempt = exemption.pass;
  if (exemption.requested) {
    findings.push({
      check: 'cross_ai_docs_only_exemption',
      pass: exemption.pass,
      detail: exemption.detail,
    });
  }
  const required = ['implementer ai', 'reviewer ai', 'codex thread', 'verdict'];
  if (!consultationExempt) {
    required.push(
      'consultation base tip',
      'consultation base',
      'consultation commit',
      'consultation scope',
      ...Object.keys(CONSULTATION_RECEIPTS),
    );
  }
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

  if (!consultationExempt) {
    await appendConsultationFindings(findings, fields, prMeta, evidenceOverrides);
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

  // Check 5: merge/readiness lane is fail-closed — only AGREE can pass.
  const verdict = (fields['verdict'] || '').trim();
  if (verdict) {
    if (verdict === 'AGREE') {
      findings.push({ check: 'verdict_agree', pass: true });
    } else {
      findings.push({
        check: 'verdict_agree',
        pass: false,
        detail: VALID_VERDICTS.has(verdict)
          ? `Verdict "${verdict}" consensus değildir; yalnız AGREE geçer`
          : `Verdict "${verdict}" invalid ve fail-closed`,
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

  // 3. actor + sender allowlist — the hard gate against human-authored
  //    spoofing. `actor` is the PR author, `sender` is who triggered this
  //    event; BOTH must be the automation bot bound to THIS prefix
  //    (AUTOMATION_PREFIX_ACTORS — a global set would let any allowlisted bot
  //    claim any prefix). Otherwise a human could push a `synchronize` commit
  //    to (or `edited` the body of) a bot-opened auto-PR: pr.user stays the
  //    bot, but the sender is the human. (Not full bot isolation — the wider
  //    contract chain + a diff path allowlist bound a compromised bot.)
  const allowedActors = AUTOMATION_PREFIX_ACTORS[prefix] ?? new Set();
  const actorOk = allowedActors.has(prMeta.actor);
  const senderOk = allowedActors.has(prMeta.sender);
  findings.push({
    check: 'automation_actor_allowlist',
    pass: actorOk && senderOk,
    detail:
      actorOk && senderOk
        ? `PR author "${prMeta.actor}" and event sender "${prMeta.sender}" are both the automation bot bound to "${prefix}"`
        : `PR author "${prMeta.actor}" / event sender "${prMeta.sender}" — both must be the automation bot bound to "${prefix}" (${[...allowedActors].join(', ') || 'none'}); denied`,
  });

  // Every automation prefix has an anchored changed-file allowlist.
  // Missing file metadata fails closed; gate-cross-ai-audit.yml always injects
  // the paginated list from the trusted base workflow.
  const diffAllowlist = AUTOMATION_DIFF_ALLOWLIST[prefix];
  if (diffAllowlist) {
    const filesPresent =
      Array.isArray(prMeta.changedFiles) && prMeta.changedFiles.length > 0;
    const badPath = filesPresent
      ? prMeta.changedFiles.find(
        (file) => !diffAllowlist.some((pattern) => pattern.test(file)),
      )
      : null;
    findings.push({
      check: 'automation_changed_files_present',
      pass: filesPresent,
      detail: filesPresent
        ? `${prMeta.changedFiles.length} changed file(s) declared`
        : 'changedFiles null or empty — fail-closed',
    });
    findings.push({
      check: 'automation_diff_allowlist',
      pass: filesPresent && !badPath,
      detail: filesPresent && !badPath
        ? `${prMeta.changedFiles.length} file(s) inside the ${prefix} allowlist`
        : `path "${badPath ?? '<missing list>'}" not in the ${prefix} allowlist`,
    });
  }

  if (prefix === 'auto-fullats-rollback/') {
    const attestation = prMeta.automationContentAttestation;
    const keys = attestation && typeof attestation === 'object'
      ? Object.keys(attestation).sort()
      : [];
    const expectedPaths = Array.isArray(attestation?.expected_paths)
      ? [...attestation.expected_paths].sort()
      : [];
    const actualChangedFiles = Array.isArray(prMeta.changedFiles)
      ? [...prMeta.changedFiles].sort()
      : [];
    const attestationPass =
      keys.join(',') === [...FULLATS_ROLLBACK_ATTESTATION_KEYS].sort().join(',')
      && attestation.schema === 'fullats-rollback-content-attestation/v1'
      && attestation.valid === true
      && attestation.source === expectedSource
      && /^auto-fullats-rollback\/faz25-fullats-[0-9]+-[0-9]+$/u.test(prMeta.headRef)
      && attestation.branch === prMeta.headRef
      && attestation.base_sha === prMeta.baseSha
      && attestation.head_sha === prMeta.headSha
      && attestation.promotion_pr === 2636
      && attestation.promotion_merge_sha === prMeta.baseSha
      && COMMIT_SHA_RE.test(attestation.promotion_head_sha || '')
      && attestation.promotion_base_sha === FULLATS_PROMOTION_BASE_SHA
      && SHA256_RE.test(attestation.promotion_scope_sha256 || '')
      && SHA256_RE.test(attestation.changed_diff_sha256 || '')
      && actualChangedFiles.join(',') === [...FULLATS_ROLLBACK_PATHS].sort().join(',')
      && expectedPaths.join(',') === [...FULLATS_ROLLBACK_PATHS].sort().join(',');
    findings.push({
      check: 'automation_fullats_content_attestation',
      pass: attestationPass,
      detail: attestationPass
        ? 'trusted-base verifier bound exact promotion tree, explicit consultation mode, one-commit rollback and four expected file blobs'
        : 'trusted-base Full ATS rollback content attestation missing or does not match PR base/head/source/exact paths',
    });
  }

  // PR-body ## Cross-AI section fields
  const section = extractCrossAiSection(body);
  const fields = section ? extractFields(section) : {};
  appendDuplicateFieldFinding(findings, fields);

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

// ── Dependabot bot PR exemption audit (#898) ──────────────────────────────
// Runs INSTEAD of audit() / auditAutomation() when the PR head branch matches
// the `dependabot/` prefix. Returns the same `findings` array shape so report()
// summarizes uniformly — lane identification is emitted via console.log in the
// main dispatch, not as a separate output field (Codex `019e4523` AGREE).
function auditDependabot(prMeta) {
  const findings = [];

  // 1. Branch prefix (re-asserted for the report — the dispatch already
  //    matched, but emitting it here makes the failure mode explicit if the
  //    function is ever called on a non-dependabot PR by mistake).
  const prefixOk = (prMeta.headRef ?? '').startsWith(DEPENDABOT_BRANCH_PREFIX);
  findings.push({
    check: 'dependabot_branch_prefix',
    pass: prefixOk,
    detail: prefixOk
      ? `head.ref "${prMeta.headRef}" matches "${DEPENDABOT_BRANCH_PREFIX}"`
      : `head.ref "${prMeta.headRef}" does not match "${DEPENDABOT_BRANCH_PREFIX}"`,
  });

  // 2. Same-repo — a fork PR named `dependabot/foo` is blocked. Mirrors the
  //    automation lane's hard gate against fork-based spoofing.
  const sameRepo =
    !!prMeta.headRepo && !!prMeta.baseRepo && prMeta.headRepo === prMeta.baseRepo;
  findings.push({
    check: 'dependabot_same_repo',
    pass: sameRepo,
    detail: sameRepo
      ? `head & base both "${prMeta.baseRepo}"`
      : `fork PR ("${prMeta.headRepo}" != "${prMeta.baseRepo}") — not exemption-eligible`,
  });

  // 3. PR author (immutable once opened) MUST be `dependabot[bot]`.
  const authorOk = prMeta.actor === DEPENDABOT_ACTOR;
  findings.push({
    check: 'dependabot_author',
    pass: authorOk,
    detail: authorOk
      ? `pr.user.login = "${prMeta.actor}"`
      : `pr.user.login = "${prMeta.actor}" — must be "${DEPENDABOT_ACTOR}"`,
  });

  // 4. Event sender — blocks human `synchronize`/`labeled`/`edited` bypass.
  //    A human pushing to or labeling a `dependabot/*` branch cannot retain
  //    the exemption (Codex `019e451f` HIGH).
  const senderOk = prMeta.sender === DEPENDABOT_ACTOR;
  findings.push({
    check: 'dependabot_sender',
    pass: senderOk,
    detail: senderOk
      ? `event.sender.login = "${prMeta.sender}"`
      : `event.sender.login = "${prMeta.sender}" — must be "${DEPENDABOT_ACTOR}" (human metadata event blocked)`,
  });

  // 5. Changed-files list must be present (null/empty = fail-closed). The
  //    workflow injects this via `--changed-files-file` from a
  //    pre-fetched `gh api ... --paginate` REST call (read-only token).
  const filesPresent =
    Array.isArray(prMeta.changedFiles) && prMeta.changedFiles.length > 0;
  findings.push({
    check: 'dependabot_changed_files_present',
    pass: filesPresent,
    detail: filesPresent
      ? `${prMeta.changedFiles.length} changed file(s) declared`
      : 'changedFiles null or empty — fail-closed (workflow must inject `--changed-files-file`)',
  });

  // 6. Diff allowlist — every changed path must match the github-actions
  //    workflow ecosystem regex. Anything outside (src/*, kustomize/*,
  //    helm-values/*, Dockerfile, etc.) denies the exemption.
  if (filesPresent) {
    const badPath = prMeta.changedFiles.find(
      (f) => !DEPENDABOT_DIFF_ALLOWLIST.some((re) => re.test(f)),
    );
    findings.push({
      check: 'dependabot_diff_allowlist',
      pass: !badPath,
      detail: !badPath
        ? `${prMeta.changedFiles.length} file(s) all inside github-actions workflow allowlist`
        : `path "${badPath}" not in allowlist (only .github/workflows/*.yml|.yaml accepted)`,
    });
  } else {
    findings.push({
      check: 'dependabot_diff_allowlist',
      pass: false,
      detail: 'diff allowlist gate skipped — changed-files list missing (see dependabot_changed_files_present)',
    });
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

// Main — dispatch order matters. Dependabot first (so a spoofed
// `dependabot/*` head with forged body cannot fall back to normal body audit
// when ANY of its 6 gates fails), then automation prefix, then normal audit.
const args = parseArgs();
const { body, prMeta } = loadInput(args);
const evidenceOverrides = readEvidenceOverrides(args);
let findings;
if (prMeta?.headRef?.startsWith(DEPENDABOT_BRANCH_PREFIX)) {
  console.log(
    `[cross-ai-audit] dependabot exemption mode — head.ref "${prMeta.headRef}"`,
  );
  findings = auditDependabot(prMeta);
} else {
  const automationPrefix = prMeta ? matchedAutomationPrefix(prMeta.headRef) : null;
  if (automationPrefix) {
    console.log(
      `[cross-ai-audit] automation-PR exemption mode — head.ref "${prMeta.headRef}" matches "${automationPrefix}"`,
    );
    findings = auditAutomation(body, prMeta);
  } else {
    findings = await audit(body, prMeta, evidenceOverrides);
  }
}
const ok = report(findings);
exit(ok ? 0 : 1);
