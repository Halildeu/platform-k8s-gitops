/*
 * Platform shell notification bell — real browser journey (ES-301b, platform-backend#1153).
 *
 *   KC login on the shell -> the shell's own inbox call (GET /api/v1/notify/inbox/me with the
 *   user's org and subscriber ids) -> an item whose subject contains EXPECTED_SUBJECT and whose
 *   topic is EXPECTED_TOPIC -> the bell badge -> screenshot.
 *
 * Reads what the product itself fetched (the inbox response), never the database: the point is
 * that the notification reaches the persona's normal session. Fails closed on console errors
 * and on any non-2xx notify call.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PERSONA_USERNAME;
const password = fs.readFileSync(process.env.PERSONA_PASSWORD_FILE, 'utf8').trim();
const evidenceDir = process.env.EVIDENCE_DIR;
const expectedSubject = (process.env.EXPECTED_SUBJECT || '').trim();
const expectedTopic = (process.env.EXPECTED_TOPIC || 'ethics.case.escalation').trim();
const forbiddenSubject = (process.env.FORBIDDEN_SUBJECT || '').trim();

if (!baseURL || !username || !password || !evidenceDir || !expectedSubject) {
  console.error('BASE_URL, PERSONA_USERNAME, PERSONA_PASSWORD_FILE, EVIDENCE_DIR, EXPECTED_SUBJECT are required');
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

const consoleErrors = [];
const notifyRequests = [];
const timings = {};
let failurePage = null;
let inboxPayload = null;
let inboxIdentity = null;
const now = () => Date.now();

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  failurePage = page;
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(`console: ${message.text()}`);
  });
  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('/api/v1/notify/')) return;
    const entry = { path: new URL(url).pathname, status: response.status() };
    notifyRequests.push(entry);
    if (entry.path.endsWith('/notify/inbox/me') && response.status() === 200) {
      try {
        inboxPayload = await response.json();
        const headers = response.request().headers();
        inboxIdentity = { orgId: headers['x-org-id'] || null, subscriberId: headers['x-subscriber-id'] || null };
      } catch { /* non-JSON */ }
    }
  });

  // 1. Login on the shell.
  const t0 = now();
  // Anonymous users land on the shell's own /login (corporate-login button), not on
  // Keycloak — same flow as schema-explorer-browser-smoke.cjs.
  await page.goto(`${baseURL}/`, { waitUntil: 'domcontentloaded' });
  const corporateButton = page.getByTestId('corporate-login-button');
  await corporateButton.waitFor({ state: 'visible', timeout: 30_000 });
  await corporateButton.click();
  await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
  await page.waitForURL((u) => u.origin === new URL(baseURL).origin && !u.pathname.includes('/realms/') && u.pathname !== '/login', { timeout: 60_000 });
  timings.loginMs = now() - t0;

  // 2. The shell fetches the inbox for its own identity; wait for that call.
  const t1 = now();
  await page.waitForFunction(() => true, null, { timeout: 1 }).catch(() => {});
  for (let i = 0; i < 60 && !inboxPayload; i++) await page.waitForTimeout(1000);
  if (!inboxPayload) throw new Error('the shell never fetched /api/v1/notify/inbox/me (identity unresolved?)');
  timings.inboxMs = now() - t1;
  const items = Array.isArray(inboxPayload.items) ? inboxPayload.items
    : Array.isArray(inboxPayload.content) ? inboxPayload.content : [];
  const match = items.find((it) => (it.subject || '').includes(expectedSubject) && (!it.topicKey || it.topicKey === expectedTopic));
  const forbidden = forbiddenSubject ? items.find((it) => (it.subject || '').includes(forbiddenSubject)) : null;
  await page.screenshot({ path: path.join(evidenceDir, '01-shell-after-login.png'), fullPage: false });

  // 3. Open the bell so the screenshot shows the item in the product, not only in JSON.
  const bell = page.locator('button[aria-label*="ildirim"]').first();
  if (await bell.count()) {
    await bell.click();
    await page.waitForTimeout(1500);
    // The drawer opens on the "Sistem" tab; the escalation sits under "Bildirimlerim".
    const mine = page.getByRole('tab', { name: /Bildirimlerim/u }).first();
    if (await mine.count()) {
      await mine.click();
      await page.waitForTimeout(800);
    }
  }
  await page.screenshot({ path: path.join(evidenceDir, '02-bell-open.png'), fullPage: false });

  const journey = {
    persona: username,
    inboxIdentity,
    unreadCount: inboxPayload.unreadCount ?? inboxPayload.unread ?? null,
    itemCount: items.length,
    matched: match ? { subject: match.subject, topicKey: match.topicKey ?? null, intentId: match.intentId ?? null, severity: match.severity ?? null, createdAt: match.createdAt ?? null } : null,
    forbiddenSeen: forbidden ? { subject: forbidden.subject, intentId: forbidden.intentId ?? null } : null,
    notifyRequests,
    consoleErrors: consoleErrors.length,
    timings,
    at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(evidenceDir, 'journey.json'), JSON.stringify(journey, null, 2));
  fs.writeFileSync(path.join(evidenceDir, 'console-errors.txt'), consoleErrors.join('\n') + (consoleErrors.length ? '\n' : ''));

  const bad = notifyRequests.filter((r) => r.status >= 400);
  if (bad.length) throw new Error(`non-2xx notify istekleri: ${JSON.stringify(bad.slice(0, 3))}`);
  if (!match) throw new Error(`inbox'ta "${expectedSubject}" (${expectedTopic}) yok — ${items.length} öğe: ${JSON.stringify(items.slice(0, 3).map((i) => i.subject))}`);
  if (forbidden) throw new Error(`yasak öğe inbox'ta: "${forbiddenSubject}"`);
  const unexpectedConsole = consoleErrors.filter((l) => !/AG Grid and AG Charts Enterprise License|Trial Period Expired|expired on 13 August 2026|purchase a license|\*{4,}/u.test(l));
  if (unexpectedConsole.length) throw new Error(`console hataları: ${unexpectedConsole.slice(0, 3).join(' | ')}`);

  await browser.close();
  // The persona name comes from the environment; keep it out of the log line (CodeQL
  // js/clear-text-logging) — journey.json carries it, the wrapper already echoed it.
  console.log(`PASS bell: persona inbox (org ${inboxIdentity?.orgId}, subscriber ${inboxIdentity?.subscriberId}) carries "${match.subject}" | unread=${journey.unreadCount} | ${JSON.stringify(timings)}`);
})().catch(async (error) => {
  console.error(`FAIL: ${error.message}`);
  try {
    if (failurePage) await failurePage.screenshot({ path: path.join(evidenceDir, '99-failure.png'), fullPage: true });
  } catch { /* page may be gone */ }
  fs.writeFileSync(path.join(evidenceDir, 'failure.json'), JSON.stringify({
    message: error.message, lastUrl: failurePage ? failurePage.url() : null, consoleErrors: consoleErrors.slice(0, 20), notifyRequests, inboxIdentity, timings,
  }, null, 2));
  process.exit(1);
});
