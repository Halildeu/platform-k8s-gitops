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
const VALID_VERDICTS = new Set(['agree', 'revise', 'partial', 'red']);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const COMMIT_SHA_RE = /^[0-9a-f]{40}$/i;
const SHA256_RE = /^[0-9a-f]{64}$/i;
const RECEIPT_KEYS = new Set([
  'provider', 'requested', 'actual', 'base_tip', 'base', 'head', 'scope',
  'verdict', 'ref', 'sha256',
]);
const EVIDENCE_KEYS = [
  'actual_model', 'base_sha', 'base_tip_sha', 'head_sha', 'provider',
  'requested_model', 'response', 'response_sha256', 'schema', 'scope_sha256',
  'verdict',
];
const DOCS_ONLY_EXEMPT_ALLOWLIST = [
  /^docs\/session-handoff-[^/]+\.md$/,
  /^docs\/archive\/[^/]+\.md$/,
];
const CONSULTATION_RECEIPTS = {
  'claude receipt': {
    provider: 'anthropic',
    model: 'claude-opus-4-8',
  },
  'minimax receipt': {
    provider: 'minimax',
    model: 'minimax/MiniMax-M3',
  },
  'codex receipt': {
    provider: 'openai',
    model: 'gpt-5.6-sol',
  },
};

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
  'auto-verified/': 'scripts/promotion/ledger-mark-verified.sh',
  'auto-promotion/': 'scripts/promotion/scan-promotion-candidates.sh',
};
// Per-prefix actor contract (#827 PR-B, Codex `019e4048` Q2 REVISE). Each
// automation prefix binds to the specific bot identity authorised to open its
// PRs; a single global actor set would let any allowlisted bot claim any
// prefix. The `auditAutomation` actor check requires BOTH the PR author and
// the event sender to be in the matched prefix's set.
//
// `auto-test-overlay/` (deploy-backend-testai.yml sync-test-overlay-pr job)
// and `auto-promotion/` (promotion-bot-scan-candidates.yml) are opened via a
// GitHub App installation token — NOT GITHUB_TOKEN. A GITHUB_TOKEN-opened PR
// does not trigger the `pull_request` workflows the required `cross-ai-audit`
// check needs, so the App is mandatory; its bot login is
// `platform-gitops-automation[bot]` (the operator names the GitHub App so its slug
// resolves to `platform-gitops-automation` — see
// docs/operations/RUNBOOKS/RB-automation-overlay-sync.md).
//
// `auto-verified/` keeps `github-actions[bot]` from #827 PR-A:
// ledger-mark-verified.sh runs on a staging-sw host (not GitHub Actions), so
// migrating it to a host-minted App token is a separate follow-up
// (#842 / Codex `019e4094` Q3).
const AUTOMATION_PREFIX_ACTORS = {
  'auto-test-overlay/': new Set(['platform-gitops-automation[bot]']),
  'auto-test-frontend/': new Set(['platform-gitops-automation[bot]']),
  'auto-promotion/': new Set(['platform-gitops-automation[bot]']),
  'auto-verified/': new Set(['github-actions[bot]']),
};

// Desired-state sync bots are further bounded to the exact files their
// deterministic writers own. A compromised bot identity therefore cannot use
// the cross-AI exemption to carry an unrelated source or workflow change.
const AUTOMATION_DIFF_ALLOWLIST = {
  'auto-test-overlay/': new Set([
    'kustomize/overlays/test/kustomization.yaml',
    'kustomize/overlays/test/activation/endpoint-admin-remote-bridge/kustomization.yaml',
    'kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key/kustomization.yaml',
  ]),
  'auto-test-frontend/': new Set([
    'kustomize/overlays/test/kustomization.yaml',
  ]),
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
  const keyRe = /^\s*(Implementer AI|Reviewer AI|Codex thread|Verdict|Verdict reason|Same-provider exception|Exception reason|Cross-AI exempt reason|Absorb edilen düzeltmeler|Consultation base tip|Consultation base|Consultation commit|Consultation scope|Claude receipt|MiniMax receipt|Codex receipt|Automation source|Automation evidence)\s*:\s*(.*?)\s*$/i;
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
  const matches = [...response.matchAll(/^VERDICT:\s*(AGREE|REVISE)\s*$/gim)];
  const lines = response.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (matches.length !== 1 || !lines.length || !/^VERDICT:\s*(AGREE|REVISE)\s*$/i.test(lines.at(-1))) {
    return null;
  }
  const sectionsPresent = ['P0', 'P1', 'P2'].every((priority) =>
    new RegExp(`^\\s*(?:#{1,6}\\s*)?(?:\\*\\*)?${priority}(?:\\*\\*)?(?:\\s*[—:-].*)?\\s*$`, 'im').test(response)
  );
  return sectionsPresent ? matches[0][1].toUpperCase() : null;
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
  if (
    !comment
    || typeof comment.body !== 'string'
    || typeof comment.author !== 'string'
    || comment.author.toLowerCase() !== expectedOwner.toLowerCase()
    || comment.authorAssociation !== 'OWNER'
    || !comment.createdAt
    || comment.createdAt !== comment.updatedAt
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
    evidence.schema === 'cross-ai-provider-evidence/v1'
    && evidence.provider === expected.provider
    && evidence.requested_model === expected.model
    && evidence.actual_model === expected.model
    && evidence.base_tip_sha?.toLowerCase() === baseTip.toLowerCase()
    && evidence.base_sha?.toLowerCase() === base.toLowerCase()
    && evidence.head_sha?.toLowerCase() === head.toLowerCase()
    && evidence.scope_sha256?.toLowerCase() === scope.toLowerCase()
    && evidence.verdict === 'AGREE'
    && responseVerdict === evidence.verdict
    && typeof evidence.response === 'string'
    && evidence.response.length > 0
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

async function appendConsultationFindings(findings, fields, prMeta, evidenceOverrides) {
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
  for (const [field, expected] of Object.entries(CONSULTATION_RECEIPTS)) {
    const receipt = parseReceipt(fields[field]);
    if (receipt?.ref) refs.push(receipt.ref);
    const shapePass = Boolean(
      receipt
      && receipt.provider?.toLowerCase() === expected.provider
      && receipt.requested === expected.model
      && receipt.actual === expected.model
      && receipt.base_tip?.toLowerCase() === baseTip.toLowerCase()
      && receipt.base?.toLowerCase() === base.toLowerCase()
      && receipt.head?.toLowerCase() === commit.toLowerCase()
      && receipt.scope?.toLowerCase() === scope.toLowerCase()
      && receipt.verdict?.toLowerCase() === 'agree'
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
        ? `${expected.provider}/${expected.model} fetched evidence + response digest + base/head/scope doğrulandı`
        : `${field}: strict receipt + GitHub issue-comment evidence + matching body/response SHA-256 zorunlu`,
    });
  }
  findings.push({
    check: 'consultation_evidence_refs_unique',
    pass: refs.length === 3 && new Set(refs).size === 3,
    detail: "Üç provider receipt ref'i birbirinden farklı olmalıdır",
  });
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

  // Check 1: required fields present
  const exemption = docsOnlyExemption(fields, prMeta);
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
  const verdict = (fields['verdict'] || '').trim().toLowerCase();
  if (verdict) {
    if (verdict === 'agree') {
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

  // Desired-state automation prefixes have an exact changed-file allowlist.
  // Missing file metadata fails closed; gate-cross-ai-audit.yml always injects
  // the paginated list from the trusted base workflow.
  const diffAllowlist = AUTOMATION_DIFF_ALLOWLIST[prefix];
  if (diffAllowlist) {
    const filesPresent =
      Array.isArray(prMeta.changedFiles) && prMeta.changedFiles.length > 0;
    const badPath = filesPresent
      ? prMeta.changedFiles.find((file) => !diffAllowlist.has(file))
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
