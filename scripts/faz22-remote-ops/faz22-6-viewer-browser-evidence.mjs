#!/usr/bin/env node

import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const HASH = /^sha256:[a-f0-9]{64}$/;
const GIT_SHA = /^[a-f0-9]{40}$/;
const VIEWER_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/;
const MIN_PILOT_SECONDS = 300;
const MAX_PILOT_SECONDS = 1800;
const MASK_BASIS_POINTS = 10_000;

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
  const tokenFile = required('OPERATOR_TOKEN_FILE');
  const output = required('EVIDENCE_OUTPUT');
  const sourceRevision = required('SOURCE_REVISION');
  if (!GIT_SHA.test(sourceRevision)) throw new Error('SOURCE_REVISION must be a full Git SHA');
  const maskRect = validateMaskRect(required('DLP_MASK_RECT_BPS'));
  const binding = validateBinding(JSON.parse(required('EVIDENCE_BINDING_JSON')));
  const pilotSeconds = Number.parseInt(process.env.PILOT_SECONDS ?? '300', 10);
  if (!Number.isSafeInteger(pilotSeconds) || pilotSeconds < MIN_PILOT_SECONDS || pilotSeconds > MAX_PILOT_SECONDS) {
    throw new Error(`PILOT_SECONDS must be ${MIN_PILOT_SECONDS}-${MAX_PILOT_SECONDS}`);
  }

  const token = (await readFile(tokenFile, 'utf8')).trim();
  if (token.length < 32 || /[\r\n]/.test(token)) throw new Error('operator token file is invalid');

  const packageRoot = process.env.PLAYWRIGHT_PACKAGE_ROOT ?? path.join(process.cwd(), 'platform-web');
  const requireFromWeb = createRequire(path.join(packageRoot, 'package.json'));
  const { chromium } = requireFromWeb('playwright');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(
    ({ bearer, expiresAt }) => {
      window.localStorage.setItem('token', bearer);
      window.localStorage.setItem('tokenExpiresAt', String(expiresAt));
    },
    { bearer: token, expiresAt: Date.now() + (pilotSeconds + 900) * 1000 },
  );

  let consoleErrorCount = 0;
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrorCount += 1;
  });
  page.on('pageerror', () => {
    consoleErrorCount += 1;
  });

  const startedAt = new Date();
  try {
    await page.goto(viewerUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    const root = page.getByTestId('remote-view-page');
    await root.waitFor({ state: 'visible', timeout: 60_000 });
    await page.waitForFunction(
      () => document.querySelector('[data-testid="remote-view-page"]')?.getAttribute('data-metadata-trusted') === 'true',
      undefined,
      { timeout: 60_000 },
    );
    await page.getByTestId('remote-view-badge-viewonly').waitFor({ state: 'visible' });
    await page.getByTestId('remote-view-badge-recording-off').waitFor({ state: 'visible' });
    await page.getByTestId('remote-view-badge-attended').waitFor({ state: 'visible' });
    await page.getByTestId('remote-view-frame').waitFor({ state: 'visible', timeout: 60_000 });

    const viewerId = await root.getAttribute('data-viewer-id');
    if (!viewerId || !VIEWER_ID.test(viewerId)) throw new Error('trusted viewer id is absent or invalid');
    const interactive = await page.locator('input,textarea,select,[contenteditable="true"]').count();
    const buttons = await page.getByRole('button').count();
    if (interactive !== 0 || buttons !== 1) throw new Error('VIEW_ONLY page exposes an unexpected input control');

    await page.evaluate(() => {
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
    });

    const screenshot = await page.screenshot({ type: 'png', fullPage: false });
    const frameChecks = await page.getByTestId('remote-view-frame').evaluate(async (image, mask) => {
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
    }, maskRect);
    if (!frameChecks || !frameChecks.pixelCheckPassed) throw new Error('rendered frame pixel variance check failed');
    if (!frameChecks.dlpMaskPixelCheckPassed) throw new Error('delivered frame DLP mask pixel check failed');
    if (!frameChecks.activeIndicatorPixelCheckPassed) throw new Error('delivered frame active indicator pixel check failed');

    const deadline = Date.now() + pilotSeconds * 1000;
    while (Date.now() < deadline) {
      const status = await page.getByTestId('remote-view-status').textContent();
      if (!status || /error|hata|forbidden|yetkiniz|closed|kapandı/i.test(status)) {
        throw new Error('viewer left the live state during the bounded pilot');
      }
      await page.waitForTimeout(1_000);
    }

    const telemetry = await page.evaluate(() => {
      const target = document.querySelector('[data-testid="remote-view-page"]');
      const evidence = window.__faz226ViewerEvidence;
      evidence?.stop();
      return {
        samples: evidence?.samples ?? [],
        attempted: Number(target?.getAttribute('data-render-ack-attempted-count') ?? '-1'),
        accepted: Number(target?.getAttribute('data-render-ack-accepted-count') ?? '-1'),
      };
    });
    const unique = new Map(telemetry.samples.map((sample) => [sample.seq, sample]));
    const samples = [...unique.values()].sort((left, right) => left.seq - right.seq);
    if (samples.length < 100 || telemetry.attempted < 100 || telemetry.accepted < 100) {
      throw new Error('minimum 100 real browser render acknowledgements were not observed');
    }
    if (telemetry.attempted !== telemetry.accepted || telemetry.accepted !== samples.length) {
      throw new Error('browser samples and render acknowledgement counts diverged');
    }
    const replayStatus = await page.evaluate(
      async ({ url, bearer, replayViewerId, replaySeq }) => {
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
      { url: viewerUrl, bearer: token, replayViewerId: viewerId, replaySeq: samples.at(-1).seq },
    );
    if (replayStatus !== 404) {
      throw new Error('broker did not reject a replayed render acknowledgement');
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
          recording: false,
          attended: true,
          capability: 'VIEW_ONLY',
          viewerIdSha256: sha256(viewerId),
        },
      },
    };
    if (consoleErrorCount !== 0) throw new Error('browser console/page errors were observed');
    await writeFile(output, `${JSON.stringify(child, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  } finally {
    await context.close();
    await browser.close();
  }

  process.stdout.write(`browser_evidence=pass output=${path.basename(output)}\n`);
}

main().catch((error) => {
  process.stderr.write(`browser_evidence=fail reason=${error instanceof Error ? error.message : 'unknown'}\n`);
  process.exitCode = 1;
});
