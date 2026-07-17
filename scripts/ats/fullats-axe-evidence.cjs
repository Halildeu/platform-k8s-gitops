'use strict';

const MAX_NODE_SAMPLES = 5;
const MAX_SELECTOR_INPUT = 2_000;

const safeClassName = new RegExp(
  '^(?:' +
    'text-(?:state|text|component|xs|sm|base|lg|xl|[0-9])|' +
    'bg-(?:state|surface|action|component)|' +
    'border(?:-(?:state|border|component))?|' +
    'rounded(?:-|$)|font(?:-|$)|leading(?:-|$)|tracking(?:-|$)|' +
    'p[trblxy]?(?:-|$)|m[trblxy]?(?:-|$)|gap(?:-|$)|space(?:-|$)|' +
    'flex(?:-|$)|grid(?:-|$)|block$|inline(?:-|$)|relative$|absolute$|sticky$|' +
    'shadow(?:-|$)|truncate$|overflow(?:-|$)|whitespace(?:-|$)|break(?:-|$)|' +
    'opacity(?:-|$)|items(?:-|$)|justify(?:-|$)|min-[wh](?:-|$)|max-[wh](?:-|$)|[wh](?:-|$)' +
    ')',
  'u',
);

const unique = (values) => [...new Set(values)];

const selectorFingerprint = (value) => {
  const raw = String(value);
  const source = raw.slice(0, MAX_SELECTOR_INPUT);
  const tags = [...source.matchAll(/(?:^|[\s>+~])([a-z][a-z0-9-]*)/giu)].map(
    (match) => match[1].toLowerCase(),
  );
  const classes = [...source.matchAll(/\.(-?[_a-zA-Z]+[_a-zA-Z0-9-]*)/gu)]
    .map((match) => match[1])
    .filter((name) => safeClassName.test(name));
  const attributes = [...source.matchAll(/\[\s*([_a-zA-Z][\w:.-]*)/gu)].map(
    (match) => match[1].toLowerCase(),
  );
  const pseudoClasses = [...source.matchAll(/:([a-z][a-z0-9-]*)/giu)]
    .map((match) => match[1].toLowerCase())
    .filter((name) => ['first-child', 'last-child', 'nth-child', 'nth-of-type'].includes(name));

  return {
    tags: unique(tags).slice(0, 8),
    classes: unique(classes).slice(0, 12),
    attributes: unique(attributes).slice(0, 8),
    pseudoClasses: unique(pseudoClasses).slice(0, 4),
    hasId: source.includes('#'),
    sourceTruncated: raw.length > MAX_SELECTOR_INPUT,
  };
};

const finiteNumber = (value) =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

const safeCssScalar = (value, pattern) => {
  const candidate = String(value ?? '');
  return pattern.test(candidate) ? candidate : undefined;
};

const contrastEvidence = (checks) => {
  const contrastCheck = checks.find((check) => check?.id === 'color-contrast');
  if (!contrastCheck || !contrastCheck.data || typeof contrastCheck.data !== 'object') return undefined;
  const data = contrastCheck.data;
  const evidence = {
    foreground: safeCssScalar(data.fgColor, /^#[0-9a-f]{3,8}$/iu),
    background: safeCssScalar(data.bgColor, /^#[0-9a-f]{3,8}$/iu),
    contrastRatio: finiteNumber(data.contrastRatio),
    expectedContrastRatio: safeCssScalar(data.expectedContrastRatio, /^\d+(?:\.\d+)?:1$/u),
    fontSize: safeCssScalar(data.fontSize, /^\d+(?:\.\d+)?px$/u),
    fontWeight: safeCssScalar(data.fontWeight, /^(?:normal|bold|[1-9]00)$/u),
  };
  return Object.fromEntries(Object.entries(evidence).filter(([, value]) => value !== undefined));
};

const compactAxeViolations = (violations) =>
  violations.map((item) => ({
    id: String(item.id ?? '').replace(/[^a-z0-9-]/giu, '').slice(0, 80),
    impact: ['minor', 'moderate', 'serious', 'critical'].includes(item.impact)
      ? item.impact
      : null,
    nodes: item.nodes.length,
    sampledNodes: item.nodes.slice(0, MAX_NODE_SAMPLES).map((node) => {
      const checks = [...(node.any ?? []), ...(node.all ?? []), ...(node.none ?? [])];
      const contrast = contrastEvidence(checks);
      return {
        target: node.target.map(selectorFingerprint),
        checkIds: unique(
          checks
            .map((check) => String(check?.id ?? '').replace(/[^a-z0-9-]/giu, '').slice(0, 80))
            .filter(Boolean),
        ).slice(0, 12),
        ...(contrast ? { contrast } : {}),
      };
    }),
    omittedNodes: Math.max(0, item.nodes.length - MAX_NODE_SAMPLES),
  }));

module.exports = { compactAxeViolations };
