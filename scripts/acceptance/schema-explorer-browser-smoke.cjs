/**
 * Schema Explorer product-surface journey (gitops#3605).
 *
 * Proves, in a real browser as the synthetic planner persona, that the IFS ERP
 * Oracle catalog is reachable THROUGH THE PRODUCT — not just the API:
 *   login -> /admin/schema-explorer -> source picker "ifs" -> schema IFSAPP ->
 *   snapshot renders (10k+ objects) -> TRYPE_ALL_VOUCHER_QRY -> its columns.
 *
 * Evidence: screenshots, console errors, every /api/v1/schema request with
 * its status and whether it carried source=ifs, timings, in EVIDENCE_DIR.
 * Fails closed on any console/page error or non-2xx schema-service call.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PLANNER_USERNAME;
const password = fs.readFileSync(process.env.PLANNER_PASSWORD_FILE, 'utf8').trim();
const evidenceDir = process.env.EVIDENCE_DIR;
const expectedTable = process.env.EXPECTED_TABLE || 'TRYPE_ALL_VOUCHER_QRY';
const expectedColumns = (process.env.EXPECTED_COLUMNS || 'LEDGER_ID,COMPANY,VOUCHER_NO').split(',');
const snapshotTimeoutMs = Number(process.env.SNAPSHOT_TIMEOUT_MS || 180_000);

if (!baseURL || !username || !password || !evidenceDir) {
  console.error('BASE_URL, PLANNER_USERNAME, PLANNER_PASSWORD_FILE, EVIDENCE_DIR are required');
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

const consoleErrors = [];
const schemaRequests = [];
const timings = {};
let failurePage = null;

const now = () => Date.now();

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, ignoreHTTPSErrors: false });
  const page = await context.newPage();
  failurePage = page;

  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(`console: ${message.text()}`);
  });
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/v1/schema')) {
      const u = new URL(url);
      schemaRequests.push({
        path: u.pathname,
        source: u.searchParams.get('source'),
        schema: u.searchParams.get('schema'),
        status: response.status(),
      });
    }
  });

  // 1. Route-scoped login: anonymous visit lands on the shell /login, the
  //    corporate button hands off to Keycloak, then back to the route.
  const t0 = now();
  await page.goto(`${baseURL}/admin/schema-explorer`, { waitUntil: 'domcontentloaded' });
  // Anonymous users land on the shell /login page (no automatic KC redirect);
  // the corporate button starts the route-scoped KC flow. `isVisible()` does
  // not wait, so a still-rendering SPA read as "no button" and the click was
  // skipped, while waitForURL matched the pre-redirect URL — the first run
  // reported loginMs 77 and sat on /login. Wait for whichever renders first.
  const corporateButton = page.getByTestId('corporate-login-button');
  const sourcePicker = page.getByTestId('se-source-select');
  const landed = await Promise.race([
    corporateButton.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'login'),
    sourcePicker.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'app'),
  ]).catch(() => 'neither');
  if (landed === 'login') {
    await corporateButton.click();
    await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
    await page.locator('#username').fill(username);
    await page.locator('#password').fill(password);
    await page.locator('#kc-login').click();
  } else if (landed === 'neither') {
    throw new Error(`neither the login button nor the Explorer rendered within 30s (url ${page.url()})`);
  }
  await page.waitForURL((u) => u.pathname.startsWith('/admin/schema-explorer'), { timeout: 60_000 });
  timings.loginMs = now() - t0;

  // 2. The source picker only renders once /sources answered with >0 sources.
  const t1 = now();
  await sourcePicker.waitFor({ state: 'visible', timeout: 60_000 });
  const sourceOptions = await sourcePicker.locator('option').allTextContents();
  await page.screenshot({ path: path.join(evidenceDir, '01-explorer-default.png'), fullPage: false });
  if (!sourceOptions.some((o) => /\bifs\b/u.test(o))) {
    throw new Error(`source picker has no ifs option: ${JSON.stringify(sourceOptions)}`);
  }

  // 3. Switch to IFS: the schema list must come from Oracle (IFSAPP), and the
  //    snapshot must be rebuilt for that source (first build ~45s live).
  await sourcePicker.selectOption('ifs');
  const schemaPicker = page.getByTestId('se-schema-select');
  await page.waitForFunction(
    () => Array.from(document.querySelectorAll('[data-testid="se-schema-select"] option'))
      .some((o) => /IFSAPP/u.test(o.textContent || '')),
    null, { timeout: 60_000 },
  );
  const schemaOptions = await schemaPicker.locator('option').allTextContents();
  await page.waitForFunction(
    () => {
      const stats = document.querySelector('.se-header__stats');
      if (!stats) return false;
      const m = /([\d.,]+)\s*tables/u.exec(stats.textContent || '');
      return m ? Number(m[1].replace(/[.,]/gu, '')) >= 10000 : false;
    },
    null, { timeout: snapshotTimeoutMs },
  );
  timings.ifsSnapshotMs = now() - t1;
  const stats = (await page.locator('.se-header__stats').textContent()) || '';
  await page.screenshot({ path: path.join(evidenceDir, '02-ifs-snapshot.png'), fullPage: false });

  // 4. Find the named view and open its detail; the columns must be there.
  const t2 = now();
  await page.getByPlaceholder('Search tables...').fill(expectedTable);
  await page.getByText(expectedTable, { exact: true }).first().click();
  // The name cell renders the key marker, the name and the IFS label as separate
  // nodes ("🔑 " text, name text, label <div> — platform-web#1157), so the cell's
  // textContent is "🔑 COMPANYCompany". Match the name as its own text node.
  await page.waitForFunction(
    (cols) => {
      const cells = Array.from(document.querySelectorAll('.se-col-table td'));
      const names = new Set();
      for (const td of cells) {
        for (const node of td.childNodes) {
          if (node.nodeType === Node.TEXT_NODE) names.add((node.textContent || '').trim());
        }
      }
      return cols.every((c) => names.has(c));
    },
    expectedColumns, { timeout: 30_000 },
  );
  // gitops#3631: the IFS dictionary's PROMPT labels and FLAGS key columns reach the screen.
  // Off unless EXPECTED_LABELS is set, so the smoke still runs against a service that
  // does not carry labels yet; when set, every listed label must be rendered and at least
  // one key column must be marked — the measured baseline was zero of each. Point
  // EXPECTED_TABLE at a keyed entity for this mode (VOUCHER_ROW: 5-column business key,
  // 118 labels); *_QRY query views carry PROMPT labels but no FLAGS keys (measured
  // 2026-09-10: TRYPE_ALL_VOUCHER_QRY 62 labels, 0 keys).
  const expectedLabels = (process.env.EXPECTED_LABELS || '').split(',').map((s) => s.trim()).filter(Boolean);
  let labels = null;
  if (expectedLabels.length > 0) {
    const rendered = await page.getByTestId('se-col-label').allTextContents();
    const missing = expectedLabels.filter((l) => !rendered.includes(l));
    const keyColumns = await page.locator('.se-col-table td.se-col--pk').count();
    labels = { rendered: rendered.length, expected: expectedLabels, missing, keyColumns };
    if (missing.length > 0) throw new Error(`IFS etiketleri ekranda yok: ${JSON.stringify(missing)} (render edilen ${rendered.length})`);
    if (keyColumns === 0) throw new Error('FLAGS anahtar kolonu işaretlenmedi (se-col--pk = 0)');
  }
  timings.tableDetailMs = now() - t2;
  await page.screenshot({ path: path.join(evidenceDir, `03-${expectedTable.toLowerCase().replace(/_/gu, '-')}.png`), fullPage: false });

  // 5. Evidence and fail-closed checks.
  fs.writeFileSync(path.join(evidenceDir, 'console-errors.txt'), consoleErrors.join('\n') + (consoleErrors.length ? '\n' : ''));
  fs.writeFileSync(path.join(evidenceDir, 'schema-requests.json'), JSON.stringify(schemaRequests, null, 2));
  const ifsRequests = schemaRequests.filter((r) => r.source === 'ifs');
  const bad = schemaRequests.filter((r) => r.status >= 400);
  const journey = {
    persona: username,
    route: '/admin/schema-explorer',
    sourceOptions,
    schemaOptions: schemaOptions.slice(0, 5),
    headerStats: stats.trim(),
    expectedTable,
    expectedColumns,
    labels,
    ifsRequests: ifsRequests.length,
    schemaRequestsTotal: schemaRequests.length,
    non2xx: bad,
    timings,
    consoleErrors: consoleErrors.length,
    expectedFrontendDigest: process.env.EXPECTED_FRONTEND_DIGEST || null,
    at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(evidenceDir, 'journey.json'), JSON.stringify(journey, null, 2));

  if (consoleErrors.length > 0) throw new Error(`console hataları: ${consoleErrors.slice(0, 3).join(' | ')}`);
  if (bad.length > 0) throw new Error(`non-2xx schema istekleri: ${JSON.stringify(bad.slice(0, 3))}`);
  if (ifsRequests.length === 0) throw new Error('hiçbir istek source=ifs taşımadı — seçici bağlı değil');

  await browser.close();
  console.log(`PASS journey: ${stats.trim()} | ${expectedTable} kolonları görüldü | ${ifsRequests.length} ifs isteği | ${JSON.stringify(timings)}`);
})().catch(async (error) => {
  console.error(`FAIL: ${error.message}`);
  try {
    if (failurePage) await failurePage.screenshot({ path: path.join(evidenceDir, '99-failure.png'), fullPage: true });
  } catch { /* page may be gone */ }
  fs.writeFileSync(path.join(evidenceDir, 'failure.json'), JSON.stringify({
    message: error.message,
    lastUrl: failurePage ? failurePage.url() : null,
    consoleErrors: consoleErrors.slice(0, 20),
    schemaRequests: schemaRequests.slice(-20),
    timings,
  }, null, 2));
  process.exit(1);
});
