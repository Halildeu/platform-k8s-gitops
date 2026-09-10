/**
 * Etik Speak manager product-surface journey — ES-301 escalation (platform-backend#882).
 *
 * Proves, in a real browser as a synthetic TEST-org staff persona, that the
 * server-recorded SLA escalation reaches the handler THROUGH THE PRODUCT:
 *   KC login (manager app redirects on its own) -> /ethic/ case grid ->
 *   "SLA eskalasyonu" column present -> sorted, the top row shows "Seviye N" ->
 *   open that case -> the detail carries the "SLA eskalasyonu: Seviye N" line.
 *
 * Evidence: screenshots, console errors, every /api/v1/ethics request with
 * its status, timings, in EVIDENCE_DIR. Fails closed on any console/page
 * error or non-2xx ethics-service call. Same substrate as the schema-explorer
 * and budget-workspace smokes.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PERSONA_USERNAME;
const password = fs.readFileSync(process.env.PERSONA_PASSWORD_FILE, 'utf8').trim();
const evidenceDir = process.env.EVIDENCE_DIR;
const expectedLevel = Number(process.env.EXPECTED_LEVEL || 1);
// Known, pre-existing console noise on the manager surface, tracked as platform-web#1155:
// the AG Grid Enterprise licence banner. (The CSP style-src violations that were on this
// list collapsed the grid; platform-web#1156 fixed the policy and the entry was removed
// so a regression fails this smoke again.) Reported in journey.json, never counted as a
// failure. Anything else in the console still fails closed.
const knownNoise = (process.env.CONSOLE_ERROR_ALLOWLIST || 'AG Grid and AG Charts Enterprise License')
  .split('|').map((s) => s.trim()).filter(Boolean);
const isKnownNoise = (line) => knownNoise.some((n) => line.includes(n));
// "Failed to load resource" console lines carry no URL; the network capture below does,
// so those lines are judged there. Non-ethics failures on this allowlist are known and
// tracked (platform-web#1155: the grid variant service answers 401 to the ethics
// persona — pre-existing, not part of the case journey). Everything else fails closed.
const knownNon2xx = (process.env.NON2XX_ALLOWLIST || '/api/v1/variants:401')
  .split(',').map((s) => s.trim()).filter(Boolean);
const isKnownNon2xx = (r) => knownNon2xx.includes(`${r.path}:${r.status}`);
const isNetworkEcho = (line) => line.startsWith('console: Failed to load resource');

if (!baseURL || !username || !password || !evidenceDir) {
  console.error('BASE_URL, PERSONA_USERNAME, PERSONA_PASSWORD_FILE, EVIDENCE_DIR are required');
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

const consoleErrors = [];
const ethicsRequests = [];
const otherFailures = [];
const timings = {};
let failurePage = null;
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
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/v1/ethics')) {
      ethicsRequests.push({ path: new URL(url).pathname, status: response.status() });
    } else if (response.status() >= 400) {
      // Every other failing resource, so a "Failed to load resource" console line can be
      // traced to a path instead of being an anonymous error.
      otherFailures.push({ path: new URL(url).pathname, status: response.status() });
    }
  });

  // 1. The manager app sends an anonymous visitor straight to Keycloak.
  const t0 = now();
  await page.goto(`${baseURL}/ethic/`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
  await page.waitForURL((u) => u.pathname.startsWith('/ethic'), { timeout: 60_000 });
  timings.loginMs = now() - t0;

  // 2. The grid, and the new column in its header.
  const t1 = now();
  const header = page.locator('.ag-header-cell-text', { hasText: 'SLA eskalasyonu' });
  await header.first().waitFor({ state: 'visible', timeout: 60_000 });
  const headers = await page.locator('.ag-header-cell-text').allTextContents();
  await page.screenshot({ path: path.join(evidenceDir, '01-grid-with-escalation-column.png'), fullPage: false });

  // 3. Sort by the column (higher levels first) and read the top row's cell.
  await header.first().click();
  await page.waitForFunction(
    () => {
      const cell = document.querySelector('.ag-row[row-index="0"] .ag-cell[col-id="escalationText"]');
      return cell ? /Seviye \d/u.test(cell.textContent || '') : false;
    },
    null, { timeout: 30_000 },
  );
  const topCell = page.locator('.ag-row[row-index="0"] .ag-cell[col-id="escalationText"]');
  const topText = ((await topCell.textContent()) || '').trim();
  const topTone = (await topCell.getAttribute('class')) || '';
  const topSubject = ((await page.locator('.ag-row[row-index="0"] .ag-cell[col-id="subject"]').textContent()) || '').trim();
  // Layout, not only DOM: platform-web#1155 showed a grid whose cells were all present and
  // all stacked vertically (CSP had blocked AG Grid's injected styles). A row is laid out
  // when its cells sit on one line and the escalation cell is to the right of the subject.
  const layout = await page.evaluate(() => {
    const row = document.querySelector('.ag-row[row-index="0"]');
    const subject = row?.querySelector('.ag-cell[col-id="subject"]');
    const esc = row?.querySelector('.ag-cell[col-id="escalationText"]');
    if (!row || !subject || !esc) return null;
    const r = row.getBoundingClientRect(); const a = subject.getBoundingClientRect(); const b = esc.getBoundingClientRect();
    return { rowHeight: r.height, sameLine: Math.abs(a.top - b.top) < 2, leftToRight: b.left > a.right - 1, rows: document.querySelectorAll('.ag-row').length };
  });
  timings.gridMs = now() - t1;
  await page.screenshot({ path: path.join(evidenceDir, '02-grid-sorted-by-escalation.png'), fullPage: false });
  if (!layout) throw new Error('üst satırın hücreleri bulunamadı');
  if (!layout.sameLine || !layout.leftToRight || layout.rowHeight > 120) {
    throw new Error(`grid görsel olarak çökük (satır yüksekliği ${Math.round(layout.rowHeight)}px, aynı satır=${layout.sameLine}, soldan sağa=${layout.leftToRight}) — bkz. platform-web#1155`);
  }
  const levelInGrid = Number((/Seviye (\d+)/u.exec(topText) || [])[1] || 0);
  if (levelInGrid < expectedLevel) throw new Error(`en yüksek seviye ${topText}, beklenen >= Seviye ${expectedLevel}`);
  if (!/is-danger/u.test(topTone)) throw new Error(`eskalasyon hücresi danger tonu taşımıyor: ${topTone}`);

  // 4. Open that case and read the detail line.
  const t2 = now();
  await page.locator('.ag-row[row-index="0"] .ag-cell[col-id="subject"]').click();
  const detailLine = page.getByTestId('escalation-level');
  await detailLine.waitFor({ state: 'visible', timeout: 30_000 });
  const detailText = ((await detailLine.textContent()) || '').trim();
  const detailLevel = await detailLine.getAttribute('data-level');
  const ackState = page.getByTestId('acknowledgement-state');
  const ackText = ((await ackState.textContent()) || '').trim();
  timings.detailMs = now() - t2;
  await page.screenshot({ path: path.join(evidenceDir, '03-case-detail-escalation-line.png'), fullPage: false });
  if (!detailText.includes(`SLA eskalasyonu: Seviye ${levelInGrid}`)) {
    throw new Error(`detay satırı grid ile uyuşmuyor: "${detailText}" vs ${topText}`);
  }

  // 5. Evidence and fail-closed checks.
  fs.writeFileSync(path.join(evidenceDir, 'console-errors.txt'), consoleErrors.join('\n') + (consoleErrors.length ? '\n' : ''));
  fs.writeFileSync(path.join(evidenceDir, 'ethics-requests.json'), JSON.stringify(ethicsRequests, null, 2));
  const bad = ethicsRequests.filter((r) => r.status >= 400);
  const journey = {
    persona: username,
    route: '/ethic/',
    headers,
    topRow: { subject: topSubject, escalation: topText, cellClass: topTone, layout },
    detail: { text: detailText, level: detailLevel, acknowledgement: ackText },
    ethicsRequestsTotal: ethicsRequests.length,
    non2xx: bad,
    otherNon2xx: otherFailures,
    timings,
    consoleErrors: consoleErrors.length,
    at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(evidenceDir, 'journey.json'), JSON.stringify(journey, null, 2));
  const unexpectedErrors = consoleErrors.filter((line) => !isKnownNoise(line) && !isNetworkEcho(line));
  const unexpectedNon2xx = otherFailures.filter((r) => !isKnownNon2xx(r));
  journey.otherNon2xxUnexpected = unexpectedNon2xx;
  journey.consoleErrorsKnownNoise = consoleErrors.length - unexpectedErrors.length;
  journey.consoleErrorsUnexpected = unexpectedErrors.length;
  fs.writeFileSync(path.join(evidenceDir, 'journey.json'), JSON.stringify(journey, null, 2));
  if (unexpectedErrors.length > 0) throw new Error(`console hataları: ${unexpectedErrors.slice(0, 3).join(' | ')}`);
  if (bad.length > 0) throw new Error(`non-2xx ethics istekleri: ${JSON.stringify(bad.slice(0, 3))}`);
  if (unexpectedNon2xx.length > 0) throw new Error(`beklenmeyen non-2xx istekler: ${JSON.stringify(unexpectedNon2xx.slice(0, 3))}`);

  await browser.close();
  console.log(`PASS journey: sütun var | üst satır "${topText}" (${topSubject.slice(0, 40)}) | detay "${detailText}" | ${ethicsRequests.length} ethics isteği | ${JSON.stringify(timings)}`);
})().catch(async (error) => {
  console.error(`FAIL: ${error.message}`);
  try {
    if (failurePage) await failurePage.screenshot({ path: path.join(evidenceDir, '99-failure.png'), fullPage: true });
  } catch { /* page may be gone */ }
  fs.writeFileSync(path.join(evidenceDir, 'failure.json'), JSON.stringify({
    message: error.message,
    lastUrl: failurePage ? failurePage.url() : null,
    consoleErrors: consoleErrors.slice(0, 20),
    ethicsRequests: ethicsRequests.slice(-20),
    otherNon2xx: otherFailures,
    timings,
  }, null, 2));
  process.exit(1);
});
