#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const HASH = /^sha256:[a-f0-9]{64}$/;
const GIT_SHA = /^[a-f0-9]{40}$/;
const VIEWER_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/;
const TEST_USERNAME = /^[A-Za-z0-9][A-Za-z0-9._@+-]{2,127}$/;
const MIN_PILOT_SECONDS = 300;
const MAX_PILOT_SECONDS = 1800;
const MASK_BASIS_POINTS = 10_000;

export const BROWSER_FAILURE_CODES = Object.freeze([
  'browser-ack-count-diverged',
  'browser-ack-minimum-not-met',
  'browser-auth-callback-failed',
  'browser-auth-session-missing',
  'browser-binding-invalid',
  'browser-console-error',
  'browser-diagnostic-write-failed',
  'browser-evidence-write-failed',
  'browser-frame-active-indicator-invalid',
  'browser-frame-dlp-mask-invalid',
  'browser-frame-inspection-failed',
  'browser-frame-not-visible',
  'browser-frame-pixel-variance-invalid',
  'browser-idp-login-form-not-visible',
  'browser-idp-login-submit-failed',
  'browser-input-invalid',
  'browser-left-live-state',
  'browser-login-entry-not-visible',
  'browser-metadata-not-trusted',
  'browser-observer-install-failed',
  'browser-preflight-api-status-invalid',
  'browser-replay-not-rejected',
  'browser-replay-probe-failed',
  'browser-route-navigation-failed',
  'browser-route-unauthorized',
  'browser-runtime-start-failed',
  'browser-screenshot-failed',
  'browser-telemetry-read-failed',
  'browser-test-credential-file-invalid',
  'browser-unclassified-failure',
  'browser-unexpected-input-control',
  'browser-view-attended-badge-missing',
  'browser-view-recording-off-badge-missing',
  'browser-view-root-not-visible',
  'browser-view-viewonly-badge-missing',
  'browser-viewer-id-invalid',
]);

class BrowserEvidenceError extends Error {
  constructor(code) {
    super(code);
    this.name = 'BrowserEvidenceError';
    this.code = code;
  }
}

function evidenceFailure(code) {
  if (!BROWSER_FAILURE_CODES.includes(code)) {
    return new BrowserEvidenceError('browser-unclassified-failure');
  }
  return new BrowserEvidenceError(code);
}

async function evidenceStep(code, action) {
  try {
    return await action();
  } catch {
    throw evidenceFailure(code);
  }
}

export function classifyBrowserFailure(error) {
  if (error instanceof BrowserEvidenceError && BROWSER_FAILURE_CODES.includes(error.code)) {
    return error.code;
  }
  const message = error instanceof Error ? error.message : '';
  if (message === 'EVIDENCE_BINDING_JSON is not a strict, distinct SHA-256 binding') {
    return 'browser-binding-invalid';
  }
  if (message === 'browser test credential file is invalid') return 'browser-test-credential-file-invalid';
  if (
    message.endsWith(' is required') ||
    message.startsWith('BROWSER_OPERATOR_USERNAME') ||
    message.startsWith('AUTH_ROUTE_PREFLIGHT_ONLY') ||
    message.startsWith('SOURCE_REVISION must be') ||
    message.startsWith('PILOT_SECONDS must be') ||
    message.startsWith('DLP_MASK_RECT_BPS') ||
    message.startsWith('VIEWER_URL')
  ) {
    return 'browser-input-invalid';
  }
  return 'browser-unclassified-failure';
}

function required(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function sha256(value) {
  return `sha256:${createHash('sha256').update(value).digest('hex')}`;
}

function utcSeconds(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function validateBinding(value) {
  const expected = ['sessionSha256', 'tenantSha256', 'operatorSha256', 'deviceSha256'];
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).sort().join(',') !== expected.sort().join(',') ||
    expected.some((key) => !HASH.test(value[key])) ||
    new Set(Object.values(value)).size !== expected.length
  ) {
    throw new Error('EVIDENCE_BINDING_JSON is not a strict, distinct SHA-256 binding');
  }
  return value;
}

function validateViewerUrl(raw) {
  const url = new URL(raw);
  if (
    url.protocol !== 'https:' ||
    url.hostname !== 'testai.acik.com' ||
    url.username ||
    url.password ||
    !/^\/endpoint-admin\/remote-access\/sessions\/[A-Za-z0-9._:-]{1,160}\/view$/.test(
      url.pathname,
    ) ||
    !/^[A-Za-z0-9_-]{1,128}$/.test(url.searchParams.get('streamId') ?? '') ||
    [...url.searchParams.keys()].some((key) => key !== 'streamId')
  ) {
    throw new Error('VIEWER_URL is outside the bounded test VIEW_ONLY product route');
  }
  return url.toString();
}

function validateMaskRect(raw) {
  if (!/^[0-9]{1,5},[0-9]{1,5},[0-9]{1,5},[0-9]{1,5}$/.test(raw)) {
    throw new Error('DLP_MASK_RECT_BPS is not canonical x,y,width,height');
  }
  const values = raw.split(',').map((value) => Number.parseInt(value, 10));
  const [x, y, width, height] = values;
  if (
    values.some((value) => !Number.isSafeInteger(value) || value < 0 || value > MASK_BASIS_POINTS) ||
    width <= 0 ||
    height <= 0 ||
    x + width > MASK_BASIS_POINTS ||
    y + height > MASK_BASIS_POINTS
  ) {
    throw new Error('DLP_MASK_RECT_BPS is empty or outside the primary monitor');
  }
  return { raw, x, y, width, height };
}

async function main() {
  const viewerUrl = validateViewerUrl(required('VIEWER_URL'));
  const output = required('EVIDENCE_OUTPUT');
  const sourceRevision = required('SOURCE_REVISION');
  if (!GIT_SHA.test(sourceRevision)) throw new Error('SOURCE_REVISION must be a full Git SHA');
  const maskRect = validateMaskRect(required('DLP_MASK_RECT_BPS'));
  const binding = validateBinding(JSON.parse(required('EVIDENCE_BINDING_JSON')));
  const operatorUsername = required('BROWSER_OPERATOR_USERNAME');
  const operatorPasswordFile = required('BROWSER_OPERATOR_PASSWORD_FILE');
  const authRoutePreflightOnly = process.env.AUTH_ROUTE_PREFLIGHT_ONLY?.trim() ?? '0';
  if (!['0', '1'].includes(authRoutePreflightOnly)) {
    throw new Error('AUTH_ROUTE_PREFLIGHT_ONLY must be 0 or 1');
  }
  if (!TEST_USERNAME.test(operatorUsername)) throw new Error('BROWSER_OPERATOR_USERNAME is invalid');
  const pilotSeconds = Number.parseInt(process.env.PILOT_SECONDS ?? '300', 10);
  if (!Number.isSafeInteger(pilotSeconds) || pilotSeconds < MIN_PILOT_SECONDS || pilotSeconds > MAX_PILOT_SECONDS) {
    throw new Error(`PILOT_SECONDS must be ${MIN_PILOT_SECONDS}-${MAX_PILOT_SECONDS}`);
  }

  const operatorPassword = (
    await evidenceStep('browser-test-credential-file-invalid', async () =>
      readFile(operatorPasswordFile, 'utf8'),
    )
  ).trim();
  if (operatorPassword.length < 16 || operatorPassword.length > 256 || /[\r\n]/.test(operatorPassword)) {
    throw new Error('browser test credential file is invalid');
  }

  const packageRoot = process.env.PLAYWRIGHT_PACKAGE_ROOT ?? path.join(process.cwd(), 'platform-web');
  let browser = null;
  let context = null;
  try {
    const requireFromWeb = createRequire(path.join(packageRoot, 'package.json'));
    const { chromium } = await evidenceStep('browser-runtime-start-failed', async () => requireFromWeb('playwright'));
    browser = await evidenceStep('browser-runtime-start-failed', async () => chromium.launch({ headless: true }));
    context = await evidenceStep('browser-runtime-start-failed', async () =>
      browser.newContext({ viewport: { width: 1440, height: 900 } }),
    );
    let consoleErrorCount = 0;
    let viewerApiStatus = null;
    const page = await evidenceStep('browser-runtime-start-failed', async () => context.newPage());
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrorCount += 1;
    });
    page.on('pageerror', () => {
      consoleErrorCount += 1;
    });
    page.on('response', (response) => {
      const responseUrl = new URL(response.url());
      if (
        responseUrl.origin === 'https://testai.acik.com' &&
        /^\/api\/v1\/endpoint-admin\/remote-access\/sessions\/[A-Za-z0-9._:-]{1,160}\/view$/.test(
          responseUrl.pathname,
        )
      ) {
        viewerApiStatus = response.status();
      }
    });

    const startedAt = new Date();
    await evidenceStep('browser-route-navigation-failed', async () =>
      page.goto(viewerUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 }),
    );

    // Exercise the same Authorization Code + PKCE journey as a real operator.
    // A bearer copied into localStorage is intentionally rejected by the shell's
    // Keycloak bootstrap and would bypass the product's cookie/authz readiness gates.
    const loginEntry = page.getByTestId('corporate-login-button');
    await evidenceStep('browser-login-entry-not-visible', async () =>
      loginEntry.waitFor({ state: 'visible', timeout: 60_000 }),
    );
    await evidenceStep('browser-idp-login-form-not-visible', async () => {
      await loginEntry.click();
      await page.locator('#username').waitFor({ state: 'visible', timeout: 60_000 });
      await page.locator('#password').waitFor({ state: 'visible', timeout: 60_000 });
      await page.locator('#kc-login').waitFor({ state: 'visible', timeout: 60_000 });
    });
    await evidenceStep('browser-idp-login-submit-failed', async () => {
      await page.locator('#username').fill(operatorUsername);
      await page.locator('#password').fill(operatorPassword);
      await page.locator('#kc-login').click();
    });

    const root = page.getByTestId('remote-view-page');
    await evidenceStep('browser-auth-callback-failed', async () => {
      await Promise.race([
        root.waitFor({ state: 'visible', timeout: 60_000 }),
        page.waitForURL((url) => url.origin === 'https://testai.acik.com' && url.pathname === '/unauthorized', {
          timeout: 60_000,
        }),
      ]);
    });
    if (new URL(page.url()).pathname === '/unauthorized') {
      throw evidenceFailure('browser-route-unauthorized');
    }
    await evidenceStep('browser-view-root-not-visible', async () =>
      root.waitFor({ state: 'visible', timeout: 5_000 }),
    );
    const browserAuthReady = await page.evaluate(() => {
      const token = window.localStorage.getItem('token');
      return typeof token === 'string' && token.length >= 32;
    });
    if (!browserAuthReady) throw evidenceFailure('browser-auth-session-missing');
    if (authRoutePreflightOnly === '1') {
      for (let attempt = 0; attempt < 100 && viewerApiStatus === null; attempt += 1) {
        await page.waitForTimeout(100);
      }
      if (viewerApiStatus !== 404) throw evidenceFailure('browser-preflight-api-status-invalid');
      const routeMounted = await root.isVisible();
      const preflight = {
        schemaVersion: 'faz22.6.viewOnlyViewerAuthRoutePreflight.v1',
        evidenceType: 'browser-auth-route-preflight',
        status: 'pass',
        sourceRevision,
        observedAt: utcSeconds(),
        binding,
        producer: {
          kind: 'browser-harness',
          tool: 'scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs',
          toolVersion: 'v2',
        },
        payload: {
          authentication: 'keycloak-authorization-code-pkce',
          productOrigin: new URL(page.url()).origin,
          routeTemplate: '/endpoint-admin/remote-access/sessions/:sessionId/view',
          routeMounted,
          browserAuthSessionPresent: browserAuthReady,
          viewerApiStatus,
          consoleErrorCount,
          viewerUrlSha256: sha256(viewerUrl),
        },
      };
      await evidenceStep('browser-evidence-write-failed', async () =>
        writeFile(output, `${JSON.stringify(preflight, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 }),
      );
      return;
    }
    await evidenceStep('browser-metadata-not-trusted', async () =>
      page.waitForFunction(
        () => document.querySelector('[data-testid="remote-view-page"]')?.getAttribute('data-metadata-trusted') === 'true',
        undefined,
        { timeout: 60_000 },
      ),
    );
    await evidenceStep('browser-view-viewonly-badge-missing', async () =>
      page.getByTestId('remote-view-badge-viewonly').waitFor({ state: 'visible' }),
    );
    await evidenceStep('browser-view-recording-off-badge-missing', async () =>
      page.getByTestId('remote-view-badge-recording-off').waitFor({ state: 'visible' }),
    );
    await evidenceStep('browser-view-attended-badge-missing', async () =>
      page.getByTestId('remote-view-badge-attended').waitFor({ state: 'visible' }),
    );
    await evidenceStep('browser-frame-not-visible', async () =>
      page.getByTestId('remote-view-frame').waitFor({ state: 'visible', timeout: 60_000 }),
    );

    const viewerId = await root.getAttribute('data-viewer-id');
    if (!viewerId || !VIEWER_ID.test(viewerId)) throw evidenceFailure('browser-viewer-id-invalid');
    const interactive = await page.locator('input,textarea,select,[contenteditable="true"]').count();
    const buttons = await page.getByRole('button').count();
    if (interactive !== 0 || buttons !== 1) throw evidenceFailure('browser-unexpected-input-control');

    await evidenceStep('browser-observer-install-failed', async () => page.evaluate(() => {
      const target = document.querySelector('[data-testid="remote-view-page"]');
      if (!target) throw new Error('remote view evidence root missing');
      const samples = [];
      let lastSeq = null;
      const record = () => {
        const seqRaw = target.getAttribute('data-frame-seq');
        const observedRaw = target.getAttribute('data-frame-observed-at');
        const sentRaw = target.getAttribute('data-frame-sent-at');
        if (seqRaw === null || observedRaw === null || sentRaw === null || seqRaw === lastSeq) return;
        const seq = Number(seqRaw);
        const observedAt = Number(observedRaw);
        const sentAt = Number(sentRaw);
        if (Number.isSafeInteger(seq) && Number.isFinite(observedAt) && Number.isFinite(sentAt)) {
          samples.push({ seq, observedAt, sentAt, sampledAt: Date.now() });
          lastSeq = seqRaw;
        }
      };
      record();
      const observer = new MutationObserver(record);
      observer.observe(target, {
        attributes: true,
        attributeFilter: ['data-frame-seq', 'data-frame-observed-at', 'data-frame-sent-at'],
      });
      window.__faz226ViewerEvidence = { samples, stop: () => observer.disconnect() };
    }));

    const screenshot = await evidenceStep('browser-screenshot-failed', async () =>
      page.screenshot({ type: 'png', fullPage: false }),
    );
    const frameChecks = await evidenceStep('browser-frame-inspection-failed', async () =>
      page.getByTestId('remote-view-frame').evaluate(async (image, mask) => {
      if (!(image instanceof HTMLImageElement) || image.naturalWidth < 2 || image.naturalHeight < 2) return false;
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (!ctx) return false;
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const x = Math.floor((canvas.width * mask.x) / 10_000);
      const y = Math.floor((canvas.height * mask.y) / 10_000);
      const xEnd = Math.ceil((canvas.width * (mask.x + mask.width)) / 10_000);
      const yEnd = Math.ceil((canvas.height * (mask.y + mask.height)) / 10_000);
      if (xEnd <= x || yEnd <= y) return false;

      let dlpMaskPixelCheckPassed = true;
      for (let py = y; py < yEnd && dlpMaskPixelCheckPassed; py += 1) {
        for (let px = x; px < xEnd; px += 1) {
          const offset = (py * canvas.width + px) * 4;
          if (pixels[offset] !== 0 || pixels[offset + 1] !== 0 || pixels[offset + 2] !== 0 || pixels[offset + 3] !== 255) {
            dlpMaskPixelCheckPassed = false;
            break;
          }
        }
      }

      let activeIndicatorPixelCheckPassed = true;
      const indicatorEnd = Math.min(28, canvas.height);
      for (let py = 0; py < indicatorEnd && activeIndicatorPixelCheckPassed; py += 1) {
        for (let px = 0; px < canvas.width; px += 1) {
          const offset = (py * canvas.width + px) * 4;
          if (pixels[offset] !== 255 || pixels[offset + 1] !== 0 || pixels[offset + 2] !== 0 || pixels[offset + 3] !== 255) {
            activeIndicatorPixelCheckPassed = false;
            break;
          }
        }
      }

      let min = 255;
      let max = 0;
      for (let py = indicatorEnd; py < canvas.height; py += 2) {
        for (let px = 0; px < canvas.width; px += 2) {
          if (px >= x && px < xEnd && py >= y && py < yEnd) continue;
          const offset = (py * canvas.width + px) * 4;
          const luminance = Math.round((pixels[offset] + pixels[offset + 1] + pixels[offset + 2]) / 3);
          min = Math.min(min, luminance);
          max = Math.max(max, luminance);
        }
      }
      const digest = await crypto.subtle.digest('SHA-256', pixels);
      return {
        pixelCheckPassed: max - min >= 8,
        dlpMaskPixelCheckPassed,
        activeIndicatorPixelCheckPassed,
        maskedFrameSha256: `sha256:${[...new Uint8Array(digest)]
          .map((value) => value.toString(16).padStart(2, '0'))
          .join('')}`,
      };
      }, maskRect),
    );
    if (!frameChecks || !frameChecks.pixelCheckPassed) throw evidenceFailure('browser-frame-pixel-variance-invalid');
    if (!frameChecks.dlpMaskPixelCheckPassed) throw evidenceFailure('browser-frame-dlp-mask-invalid');
    if (!frameChecks.activeIndicatorPixelCheckPassed) {
      throw evidenceFailure('browser-frame-active-indicator-invalid');
    }

    const deadline = Date.now() + pilotSeconds * 1000;
    while (Date.now() < deadline) {
      const status = await page.getByTestId('remote-view-status').textContent();
      if (!status || /error|hata|forbidden|yetkiniz|closed|kapandı/i.test(status)) {
        throw evidenceFailure('browser-left-live-state');
      }
      await page.waitForTimeout(1_000);
    }

    const telemetry = await evidenceStep('browser-telemetry-read-failed', async () => page.evaluate(() => {
      const target = document.querySelector('[data-testid="remote-view-page"]');
      const evidence = window.__faz226ViewerEvidence;
      evidence?.stop();
      return {
        samples: evidence?.samples ?? [],
        attempted: Number(target?.getAttribute('data-render-ack-attempted-count') ?? '-1'),
        accepted: Number(target?.getAttribute('data-render-ack-accepted-count') ?? '-1'),
      };
    }));
    const unique = new Map(telemetry.samples.map((sample) => [sample.seq, sample]));
    const samples = [...unique.values()].sort((left, right) => left.seq - right.seq);
    if (samples.length < 100 || telemetry.attempted < 100 || telemetry.accepted < 100) {
      throw evidenceFailure('browser-ack-minimum-not-met');
    }
    if (telemetry.attempted !== telemetry.accepted || telemetry.accepted !== samples.length) {
      throw evidenceFailure('browser-ack-count-diverged');
    }
    const replayStatus = await evidenceStep('browser-replay-probe-failed', async () => page.evaluate(
      async ({ url, replayViewerId, replaySeq }) => {
        const bearer = window.localStorage.getItem('token');
        if (!bearer) return 0;
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            Authorization: `Bearer ${bearer}`,
          },
          cache: 'no-store',
          body: JSON.stringify({ viewerId: replayViewerId, frameSeq: replaySeq }),
        });
        return response.status;
      },
      { url: viewerUrl, replayViewerId: viewerId, replaySeq: samples.at(-1).seq },
    ));
    if (replayStatus !== 404) {
      throw evidenceFailure('browser-replay-not-rejected');
    }
    const ages = samples.map((sample) => Math.max(0, sample.sampledAt - sample.observedAt));

    const endedAt = new Date();
    const child = {
      schemaVersion: 'faz22.6.viewOnlyViewerProductChildEvidence.v2',
      evidenceType: 'browser',
      sourceRevision,
      observedAt: utcSeconds(),
      binding,
      producer: {
        kind: 'browser-harness',
        tool: 'scripts/faz22-remote-ops/faz22-6-viewer-browser-evidence.mjs',
        toolVersion: 'v2',
      },
      payload: {
        pilotStartedAt: utcSeconds(startedAt),
        pilotEndedAt: utcSeconds(endedAt),
        imageElementRendered: true,
        pixelCheckPassed: true,
        inputChannelControlCount: interactive,
        dlpMaskRectBps: maskRect.raw,
        dlpMaskPixelCheckPassed: true,
        activeIndicatorPixelCheckPassed: true,
        maskedFrameSha256: frameChecks.maskedFrameSha256,
        renderAckAttemptedCount: telemetry.attempted,
        renderAckAcceptedCount: telemetry.accepted,
        consoleErrorCount,
        screenshotSha256: sha256(screenshot),
        firstFrameAgeMillis: Math.max(1, ages[0]),
        steadyFrameAgeMillis: ages,
        meta: {
          authentication: 'keycloak-authorization-code-pkce',
          recording: false,
          attended: true,
          capability: 'VIEW_ONLY',
          viewerIdSha256: sha256(viewerId),
        },
      },
    };
    if (consoleErrorCount !== 0) throw evidenceFailure('browser-console-error');
    await evidenceStep('browser-evidence-write-failed', async () =>
      writeFile(output, `${JSON.stringify(child, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 }),
    );
  } finally {
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
  }

  process.stdout.write(`browser_evidence=pass output=${path.basename(output)}\n`);
}

async function writeFailureDiagnostic(code) {
  const output = process.env.BROWSER_DIAGNOSTIC_OUTPUT?.trim();
  if (!output) return;
  const sourceRevision = process.env.SOURCE_REVISION?.trim() ?? '';
  const diagnostic = {
    schemaVersion: 'faz22.6.viewOnlyViewerBrowserDiagnostic.v1',
    sourceRevision: GIT_SHA.test(sourceRevision) ? sourceRevision : null,
    failureCode: code,
  };
  await writeFile(output, `${JSON.stringify(diagnostic, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(async (error) => {
    let code = classifyBrowserFailure(error);
    try {
      await writeFailureDiagnostic(code);
    } catch {
      code = 'browser-diagnostic-write-failed';
    }
    process.stderr.write(`browser_evidence=fail code=${code}\n`);
    process.exitCode = 1;
  });
}
