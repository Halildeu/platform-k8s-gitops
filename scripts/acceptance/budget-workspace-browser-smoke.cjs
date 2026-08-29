'use strict';
/*
 * Budget Workspace browser smoke (gitops#3479) — the real planner journey:
 * KC form login -> /admin/reports/budget-control -> Workcube plan import
 * (scenario opt-in, TEST ERP data is scenario-only) -> COMPLETED result
 * panel -> versioned draft table with annual-bucket periods.
 *
 * Evidence: screenshots + console errors + /api/v1/budgets network log in
 * EVIDENCE_DIR. Fails closed on any console page error or non-2xx budget
 * API response outside the expected shapes.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const baseURL = process.env.BASE_URL;
const username = process.env.PLANNER_USERNAME;
const password = fs
  .readFileSync(process.env.PLANNER_PASSWORD_FILE, 'utf8')
  .trim();
const evidenceDir = process.env.EVIDENCE_DIR;
if (!baseURL || !username || !password || !evidenceDir) {
  throw new Error('BASE_URL / PLANNER_USERNAME / password file / EVIDENCE_DIR are required');
}

const consoleErrors = [];
const budgetRequests = [];

const waitVisible = async (locator, label, timeout) => {
  await locator.waitFor({ state: 'visible', timeout }).catch(() => {
    throw new Error(`beklenen görünmedi: ${label}`);
  });
};

let failurePage = null;

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    ignoreHTTPSErrors: false,
  });
  const page = await context.newPage();
  failurePage = page;

  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(`console: ${message.text()}`);
  });
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/v1/budgets')) {
      budgetRequests.push({
        method: response.request().method(),
        status: response.status(),
        url: url.replace(baseURL, ''),
      });
    }
  });

  // 1 — route-scoped login. The shell requests budget:read/budget:write for
  // this exact route (keycloakRouteScope.ts), so landing here first is part
  // of the contract under test.
  await page.goto(`${baseURL}/admin/reports/budget-control`, { waitUntil: 'domcontentloaded' });
  const importSection = page.getByRole('region', { name: 'Workcube bütçe planı içe aktarma' });
  if (!(await importSection.isVisible().catch(() => false))) {
    // Anonymous users land on the shell /login page (no automatic KC
    // redirect); the corporate button starts the route-scoped KC flow.
    const corporateButton = page.getByTestId('corporate-login-button');
    await waitVisible(corporateButton, 'kurumsal giriş butonu', 30_000);
    await corporateButton.click();
    await page.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
    await page.locator('#username').fill(username);
    await page.locator('#password').fill(password);
    await page.locator('#kc-login').click();
  }
  await waitVisible(importSection, 'plan import bölümü', 60_000);
  await page.screenshot({ path: path.join(evidenceDir, '01-workspace.png'), fullPage: true });

  // 2 — company scope, then the import trigger. TEST ERP carries only the
  // scenario demo budget, so the explicit opt-in is part of the journey.
  await page.getByLabel('Şirket adı').selectOption({ index: 1 });
  await page.getByRole('checkbox', { name: /Senaryo planlarını da al/u }).check();
  const importButton = page.getByRole('button', { name: 'Planı içe aktar' });
  await waitVisible(importButton, 'içe aktarma butonu', 10_000);
  if (await importButton.isDisabled()) throw new Error('içe aktarma butonu şirket seçimine rağmen kapalı');
  await importButton.click();

  // 3 — real result panel from the live import.
  const resultPanel = page.getByRole('status');
  await waitVisible(resultPanel, 'içe aktarma sonucu', 120_000);
  const resultText = (await resultPanel.textContent()) ?? '';
  if (!/İçe aktarma tamamlandı/u.test(resultText)) {
    throw new Error(`sonuç paneli COMPLETED değil: ${resultText.slice(0, 200)}`);
  }
  if (!/kaynak satırı okundu/u.test(resultText)) {
    throw new Error('sonuç paneli gerçek sayaçları göstermiyor');
  }

  // 4 — versioned draft: annual-bucket periods (#3474) + line table.
  await waitVisible(page.getByText(/bütçe taslağı · sürüm/u), 'taslak başlığı', 30_000);
  const periodCells = page.locator('tbody td:first-child');
  const periodCount = await periodCells.count();
  if (periodCount < 1) throw new Error('taslak tablosunda satır yok');
  for (let i = 0; i < periodCount; i += 1) {
    const value = ((await periodCells.nth(i).textContent()) ?? '').trim();
    if (!/^\d{4}-01$/u.test(value)) {
      throw new Error(`yıllık kova ihlali: dönem hücresi '${value}'`);
    }
  }
  const statusBadge = page
    .locator('span', { hasText: /^(Taslak|Onaya gönderildi)$/u })
    .first();
  await waitVisible(statusBadge, 'sürüm durum rozeti', 10_000);
  await page.screenshot({ path: path.join(evidenceDir, '02-import-draft.png'), fullPage: true });

  // 5 — evidence + fail-closed checks.
  fs.writeFileSync(
    path.join(evidenceDir, 'network-budget.json'),
    JSON.stringify(budgetRequests, null, 2),
  );
  fs.writeFileSync(
    path.join(evidenceDir, 'console-errors.txt'),
    consoleErrors.join('\n') + (consoleErrors.length ? '\n' : ''),
  );
  const badBudget = budgetRequests.filter((r) => r.status >= 400);
  if (badBudget.length > 0) {
    throw new Error(`budget API hataları: ${JSON.stringify(badBudget)}`);
  }
  if (consoleErrors.length > 0) {
    throw new Error(`console hataları: ${consoleErrors.slice(0, 3).join(' | ')}`);
  }

  fs.writeFileSync(
    path.join(evidenceDir, 'journey.json'),
    JSON.stringify(
      {
        journey: 'login -> budget-control -> import (scenario opt-in) -> draft table',
        persona: username,
        resultText: resultText.slice(0, 300),
        draftRows: periodCount,
        budgetRequests: budgetRequests.length,
        expectedFrontendDigest: process.env.EXPECTED_FRONTEND_DIGEST || null,
      },
      null,
      2,
    ),
  );

  await browser.close();
  console.log(`PASS journey: ${periodCount} taslak satırı, ${budgetRequests.length} budget isteği, 0 console hatası`);
})().catch(async (error) => {
  console.error(`FAIL: ${error.message}`);
  // Leave debuggable evidence on failure too — the artifact step depends on
  // the directory being non-empty.
  try {
    if (failurePage) {
      await failurePage.screenshot({
        path: path.join(evidenceDir, '99-failure.png'),
        fullPage: true,
      });
    }
  } catch {
    /* the page may already be unusable */
  }
  try {
    fs.writeFileSync(
      path.join(evidenceDir, 'failure.json'),
      JSON.stringify(
        {
          error: error.message,
          lastUrl: failurePage ? failurePage.url() : null,
          consoleErrors: consoleErrors.slice(0, 20),
          budgetRequests,
        },
        null,
        2,
      ),
    );
  } catch {
    /* best effort */
  }
  process.exit(1);
});
