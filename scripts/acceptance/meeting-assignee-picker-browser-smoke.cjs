#!/usr/bin/env node
/**
 * Meeting "Göreve ata" people picker — authenticated browser journey (gitops#3834).
 *
 * Journey (synthetic non-admin persona, fixture meeting + unassigned task created over the API):
 *   login -> /admin/meetings/<meeting> -> task row "Ata" -> type the query -> the picker lists
 *   the persona -> pick it -> the row shows the assignee by NAME, never a Keycloak id.
 *
 * Fails closed on: no picker result for the persona, a non-2xx picker or task-update call, a page
 * error, or (EXPECT_ASSIGNEE_NAME=1) a row label that is not a name. Other console errors are
 * recorded as evidence. The fixture meeting and task are always deleted.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PERSONA_USERNAME;
const password = fs.readFileSync(process.env.PERSONA_PASSWORD_FILE, 'utf8').trim();
const clientSecret = fs.readFileSync(process.env.SMOKE_CLIENT_SECRET_FILE, 'utf8').trim();
const evidenceDir = process.env.EVIDENCE_DIR;
const expectName = process.env.EXPECT_ASSIGNEE_NAME === '1';
const query = process.env.PICKER_QUERY || 'meeting-normal';
if (!baseURL || !username || !password || !clientSecret || !evidenceDir) {
  console.error('FATAL: BASE_URL, PERSONA_USERNAME, secrets and EVIDENCE_DIR are required');
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

const KC_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const consoleErrors = [];
const pageErrors = [];
const calls = [];
const failedResponses = [];
const journey = { persona: username, query, expectName, steps: [] };
const step = (name, extra = {}) => journey.steps.push({ name, at: new Date().toISOString(), ...extra });

async function apiToken() {
  const body = new URLSearchParams({
    grant_type: 'password',
    client_id: 'smoke-client',
    client_secret: clientSecret,
    username,
    password,
    scope: 'openid smoke-notify-v1',
  });
  const response = await fetch(`${baseURL}/realms/platform-test/protocol/openid-connect/token`, { method: 'POST', body });
  if (!response.ok) throw new Error(`fixture token: HTTP ${response.status}`);
  return (await response.json()).access_token;
}

async function api(token, method, url, json) {
  const response = await fetch(`${baseURL}${url}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(json ? { 'Content-Type': 'application/json' } : {}) },
    body: json ? JSON.stringify(json) : undefined,
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : null };
}

(async () => {
  const token = await apiToken();
  const meeting = await api(token, 'POST', '/api/v1/admin/meetings', {
    title: '[TEST gitops#3834] tarayıcı kabulü',
    description: 'otomatik tarayıcı kabul testi; test sonunda silinir',
  });
  if (meeting.status !== 201) throw new Error(`fixture meeting: HTTP ${meeting.status}`);
  const meetingId = meeting.body.id;
  const task = await api(token, 'POST', `/api/v1/admin/meetings/${meetingId}/actions`, {
    description: 'Bütçe tablosunu kontrol et (tarayıcı kabulü)',
  });
  if (task.status !== 201) throw new Error(`fixture task: HTTP ${task.status}`);
  step('fixture', { meeting: meetingId.slice(0, 8), task: task.body.id.slice(0, 8) });

  const browser = await chromium.launch();
  const context = await browser.newContext({ locale: 'tr-TR', viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', (error) => pageErrors.push(error.message.slice(0, 300)));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 300));
  });
  page.on('response', (response) => {
    const url = response.url();
    if (response.status() >= 400) {
      // Every failed request, so a console "404" is attributable (ids masked, no query string).
      const u = new URL(url);
      failedResponses.push({
        method: response.request().method(),
        path: u.pathname.replace(meetingId, '<meeting>').replace(task.body.id, '<task>')
          .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/giu, '<uuid>'),
        status: response.status(),
      });
    }
    if (url.includes('/assignee-candidates/') || /\/meetings\/[^/]+\/actions/u.test(url)) {
      calls.push({
        method: response.request().method(),
        path: new URL(url).pathname.replace(meetingId, '<meeting>').replace(task.body.id, '<task>'),
        status: response.status(),
      });
    }
  });

  let failure = null;
  try {
    await page.goto(`${baseURL}/admin/meetings/${meetingId}`, { waitUntil: 'domcontentloaded' });
    const corporateButton = page.getByTestId('corporate-login-button');
    const assigneeButton = page.locator('.task-assignee button').first();
    const landed = await Promise.race([
      corporateButton.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'login'),
      assigneeButton.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'app'),
    ]).catch(() => 'neither');
    if (landed === 'login') {
      await corporateButton.click();
      await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
      await page.locator('#username').fill(username);
      await page.locator('#password').fill(password);
      await page.locator('#kc-login').click();
      await page.waitForURL((u) => u.pathname.startsWith('/admin/meetings'), { timeout: 60_000 });
      if (!page.url().includes(meetingId)) {
        await page.goto(`${baseURL}/admin/meetings/${meetingId}`, { waitUntil: 'domcontentloaded' });
      }
    } else if (landed === 'neither') {
      throw new Error(`neither the login button nor the task row rendered within 30s (url ${page.url()})`);
    }
    step('login', { landed });

    await assigneeButton.waitFor({ state: 'visible', timeout: 90_000 });
    const before = (await assigneeButton.innerText()).trim();
    if (before !== 'Ata') throw new Error(`fixture task should start unassigned, row says "${before}"`);
    await page.screenshot({ path: path.join(evidenceDir, '01-task-unassigned.png'), fullPage: false });
    step('task-row', { label: before });

    await assigneeButton.click();
    await page.getByLabel('Sorumlu ara').fill(query);
    const listbox = page.getByRole('listbox', { name: 'Kişi önerileri' });
    const personaOption = listbox.getByRole('button').filter({ hasText: username });
    await personaOption.first().waitFor({ state: 'visible', timeout: 30_000 });
    const optionCount = await listbox.getByRole('button').count();
    await page.screenshot({ path: path.join(evidenceDir, '02-picker-options.png'), fullPage: false });
    step('picker', { options: optionCount });

    await personaOption.first().click();
    await page.waitForFunction(
      () => {
        const button = document.querySelector('.task-assignee button');
        return button && button.textContent.trim() !== 'Ata';
      },
      null,
      { timeout: 30_000 },
    );
    if (expectName) {
      await page.waitForFunction(
        () => {
          const text = document.querySelector('.task-assignee button')?.textContent.trim() ?? '';
          return text && text !== 'Atanmış kişi';
        },
        null,
        { timeout: 30_000 },
      );
    }
    const after = (await page.locator('.task-assignee button').first().innerText()).trim();
    await page.screenshot({ path: path.join(evidenceDir, '03-task-assigned.png'), fullPage: false });
    step('assigned', { label: after });
    if (KC_ID.test(after)) throw new Error('the row shows a Keycloak id instead of a person');
    if (expectName && (after === 'Atanmış kişi' || after === 'Ata')) throw new Error(`the row does not name the assignee: "${after}"`);

    const pickerCalls = calls.filter((c) => c.path.includes('/assignee-candidates/'));
    const updateCalls = calls.filter((c) => c.method === 'PUT');
    if (!pickerCalls.length || pickerCalls.some((c) => c.status < 200 || c.status > 299)) {
      throw new Error(`picker calls not all 2xx: ${JSON.stringify(pickerCalls)}`);
    }
    if (!updateCalls.length || updateCalls.some((c) => c.status < 200 || c.status > 299)) {
      throw new Error(`task update calls not all 2xx: ${JSON.stringify(updateCalls)}`);
    }
    if (pageErrors.length) throw new Error(`page errors: ${pageErrors.join(' | ')}`);
  } catch (error) {
    failure = error;
    await page.screenshot({ path: path.join(evidenceDir, '99-failure.png'), fullPage: false }).catch(() => {});
  } finally {
    const cleanupTask = await api(token, 'DELETE', `/api/v1/admin/meetings/${meetingId}/actions/${task.body.id}`);
    const cleanupMeeting = await api(token, 'DELETE', `/api/v1/admin/meetings/${meetingId}`);
    step('cleanup', { task: cleanupTask.status, meeting: cleanupMeeting.status });
    await browser.close();
    journey.calls = calls;
    journey.failedResponses = failedResponses;
    journey.consoleErrors = consoleErrors.length;
    journey.pageErrors = pageErrors.length;
    journey.result = failure ? `FAIL: ${failure.message}` : 'PASS';
    fs.writeFileSync(path.join(evidenceDir, 'console-errors.txt'), consoleErrors.join('\n') + (consoleErrors.length ? '\n' : ''));
    fs.writeFileSync(path.join(evidenceDir, 'journey.json'), JSON.stringify(journey, null, 2));
    console.log(JSON.stringify({ result: journey.result, steps: journey.steps, calls, failedResponses, consoleErrors: consoleErrors.length }, null, 2));
    if (failure) process.exit(1);
  }
})().catch((error) => {
  console.error(`FATAL: ${error.message}`);
  process.exit(1);
});
