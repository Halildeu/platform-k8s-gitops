#!/usr/bin/env node
/**
 * Reopen a persisted meeting analysis in the product UI (gitops#3807 reboot acceptance).
 *
 * Journey: route-scoped KC login -> /admin/meetings/<MEETING_ID> -> the intelligence result
 * request answers 200 -> the "Özet" block has text and the Kararlar / Aksiyonlar lists render
 * exactly EXPECT_DECISIONS / EXPECT_ACTIONS rows (the durable counts of the synthetic chain).
 *
 * Fails closed on: a non-200 intelligence result, a missing summary, a count mismatch, or a page
 * error. Evidence holds counts, statuses and masked request paths only; no analysis or transcript
 * text is written. A screenshot of the synthetic TEST meeting stays in the evidence directory.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PERSONA_USERNAME;
const password = fs.readFileSync(process.env.PERSONA_PASSWORD_FILE, 'utf8').trim();
const meetingId = process.env.MEETING_ID;
const expectDecisions = Number.parseInt(process.env.EXPECT_DECISIONS, 10);
const expectActions = Number.parseInt(process.env.EXPECT_ACTIONS, 10);
const evidenceDir = process.env.EVIDENCE_DIR;
if (!baseURL || !username || !password || !meetingId || !evidenceDir ||
    !Number.isInteger(expectDecisions) || !Number.isInteger(expectActions)) {
  console.error('FATAL: BASE_URL, PERSONA_USERNAME, secret, MEETING_ID, counts and EVIDENCE_DIR are required');
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/giu;
const mask = (pathname) => pathname.replace(meetingId, '<meeting>').replace(UUID, '<uuid>');
const consoleErrors = [];
const pageErrors = [];
const failedResponses = [];
const resultCalls = [];
const journey = { persona: username, meeting: meetingId.slice(0, 8), expectDecisions, expectActions, steps: [] };
const step = (name, extra = {}) => journey.steps.push({ name, at: new Date().toISOString(), ...extra });

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: 'tr-TR', viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => pageErrors.push(error.message.slice(0, 300)));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
  });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (response.status() >= 400) {
      failedResponses.push({ method: response.request().method(), path: mask(url.pathname), status: response.status() });
    }
    if (url.pathname.includes(meetingId) && url.pathname.endsWith('/intelligence/result')) {
      resultCalls.push({ method: response.request().method(), path: mask(url.pathname), status: response.status() });
    }
  });

  let failure = null;
  const rendered = {};
  try {
    await page.goto(`${baseURL}/admin/meetings/${meetingId}`, { waitUntil: 'domcontentloaded' });
    const corporateButton = page.getByTestId('corporate-login-button');
    const decisions = page.locator('section[aria-labelledby="decisions-title"]');
    const landed = await Promise.race([
      corporateButton.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'login'),
      decisions.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'app'),
    ]).catch(() => 'neither');
    if (landed === 'login') {
      await corporateButton.click();
      await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
      await page.locator('#username').fill(username);
      await page.locator('#password').fill(password);
      await page.locator('#kc-login').click();
      await page.waitForURL((u) => u.pathname.startsWith('/admin'), { timeout: 60_000 });
      if (!page.url().includes(meetingId)) {
        await page.goto(`${baseURL}/admin/meetings/${meetingId}`, { waitUntil: 'domcontentloaded' });
      }
    } else if (landed === 'neither') {
      throw new Error(`neither the login button nor the meeting analysis rendered within 30s (url ${mask(new URL(page.url()).pathname)})`);
    }
    step('login', { landed });

    // The durable analysis must come back from the product API, not from a cached shell.
    await page.waitForResponse(
      (response) => new URL(response.url()).pathname.includes(meetingId) &&
        new URL(response.url()).pathname.endsWith('/intelligence/result'),
      { timeout: 90_000 },
    ).catch(() => null);
    await decisions.waitFor({ state: 'visible', timeout: 90_000 });
    // Lists settle after the result request resolves; wait for the expected count, then read it.
    const decisionItems = decisions.locator('.output-list li');
    const actionItems = page.locator('section[aria-labelledby="actions-title"] .output-list li');
    await page.waitForFunction(
      ([d, a]) => document.querySelectorAll('section[aria-labelledby="decisions-title"] .output-list li').length === d &&
        document.querySelectorAll('section[aria-labelledby="actions-title"] .output-list li').length === a,
      [expectDecisions, expectActions],
      { timeout: 60_000 },
    ).catch(() => null);
    rendered.decisions = await decisionItems.count();
    rendered.actions = await actionItems.count();
    rendered.summaryHeading = (await page.locator('.summary-block h3').first().textContent() || '').trim();
    rendered.summaryChars = ((await page.locator('.summary-block p').first().textContent()) || '').trim().length;
    await page.screenshot({ path: path.join(evidenceDir, 'meeting-analysis-reopen.png'), fullPage: true });
    step('rendered', rendered);

    const okResult = resultCalls.some((call) => call.method === 'GET' && call.status === 200);
    if (!okResult) failure = `intelligence result did not answer 200: ${JSON.stringify(resultCalls)}`;
    else if (rendered.summaryHeading !== 'Özet' || rendered.summaryChars === 0) failure = 'summary block is missing or empty';
    else if (rendered.decisions !== expectDecisions) failure = `decisions rendered ${rendered.decisions}, durable ${expectDecisions}`;
    else if (rendered.actions !== expectActions) failure = `actions rendered ${rendered.actions}, durable ${expectActions}`;
    else if (pageErrors.length) failure = `page errors: ${pageErrors.length}`;
  } catch (error) {
    failure = error.message.slice(0, 500);
  } finally {
    await browser.close();
  }

  const evidence = {
    schemaVersion: 'faz24.meeting-analysis-reopen-browser.v1',
    generatedAt: new Date().toISOString(),
    status: failure ? 'fail' : 'pass',
    failure,
    journey,
    rendered,
    resultCalls,
    failedResponses,
    consoleErrors,
    pageErrors,
    privacy: { analysisTextIncluded: false, transcriptTextIncluded: false, secretMaterialIncluded: false },
  };
  fs.writeFileSync(path.join(evidenceDir, 'meeting-analysis-reopen.json'), `${JSON.stringify(evidence, null, 2)}\n`);
  console.log(JSON.stringify({ status: evidence.status, failure, rendered, resultCalls, failedResponses: failedResponses.length }));
  process.exit(failure ? 1 : 0);
})().catch((error) => {
  console.error(`FATAL: ${error.message.slice(0, 300)}`);
  process.exit(1);
});
