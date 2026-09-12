const { chromium } = require('/srv/platform-dev/repos/platform-web/node_modules/@playwright/test');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const origin = 'https://devai.acik.com';
const evidence = '/srv/platform-dev/evidence/devai-20260912';

(async () => {
  const password = execFileSync('python3', ['-c', "import sys; sys.path.insert(0, '/srv/platform-dev/ops'); from remote_dev_credentials import load_credentials; print(load_credentials()['developer'])"], { encoding: 'utf8' }).trim();
  const browser = await chromium.launch({ headless: true });
  const result = { origin, syntheticDev: true, tlsBypass: false, api: [], pageErrors: [], failed: [], foreignRequests: [], websocketConnections: [] };
  let page;
  let probe;
  try {
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', error => result.pageErrors.push(error.name));
    page.on('requestfailed', request => {
      const url = new URL(request.url());
      if (request.failure()?.errorText !== 'net::ERR_ABORTED') result.failed.push({ path: url.pathname, error: request.failure()?.errorText });
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.protocol.startsWith('http') && url.origin !== origin) result.foreignRequests.push({ origin: url.origin, path: url.pathname });
    });
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname === '/api/v1/users') result.api.push(response.status());
      if (url.pathname.includes('/login-actions/authenticate') && response.request().method() === 'POST') {
        result.loginPost = { status: response.status(), origin: response.request().headers()['origin'] };
        console.log(JSON.stringify({ loginPost: result.loginPost }));
      }
    });
    page.on('websocket', ws => {
      const url = new URL(ws.url());
      const entry = { origin: url.origin, path: url.pathname, received: false };
      result.websocketConnections.push(entry);
      ws.on('framereceived', () => { entry.received = true; });
    });
    result.stage = 'open_root';
    await page.goto(origin + '/', { waitUntil: 'domcontentloaded', timeout: 90000 });
    result.stage = 'login_link';
    await page.getByRole('link', { name: 'Güvenli Kurumsal Giriş' }).click({ timeout: 90000 });
    result.stage = 'keycloak_form';
    await page.locator('#username').fill('developer', { timeout: 90000 });
    await page.locator('#password').fill(password);
    await page.locator('#kc-login').click();
    result.stage = 'login_return';
    await page.waitForURL(origin + '/home', { timeout: 90000 });
    result.loginReturned = true;
    result.stage = 'users_grid';
    await page.goto(origin + '/admin/users');
    await page.locator('.ag-center-cols-container .ag-row').first().waitFor({ state: 'visible', timeout: 90000 });
    await page.reload();
    await page.locator('.ag-center-cols-container .ag-row').first().waitFor({ state: 'visible', timeout: 90000 });
    result.rows = await page.locator('.ag-center-cols-container .ag-row').count();
    result.cells = await page.locator('.ag-center-cols-container .ag-cell').count();
    await page.screenshot({ path: evidence + '/users-desktop.png', fullPage: true });
    result.stage = 'hmr_edit';
    const probeName = 'devai-hmr-proof-' + randomUUID() + '.ts';
    const probePath = '/srv/platform-dev/repos/platform-web/apps/mfe-shell/src/' + probeName;
    const moduleBody = value => `window.__devaiHmrProof = '${value}'; if (import.meta.hot) import.meta.hot.accept(); export {};\n`;
    fs.writeFileSync(probePath, moduleBody('before'), { flag: 'wx', mode: 0o600 });
    probe = probePath;
    await page.evaluate(url => import(url), origin + '/src/' + probeName);
    await page.waitForFunction(() => window.__devaiHmrProof === 'before');
    fs.writeFileSync(probe, moduleBody('after'), { mode: 0o600 });
    await page.waitForFunction(() => window.__devaiHmrProof === 'after', undefined, { timeout: 30000 });
    result.hmrEditApplied = true;
    fs.unlinkSync(probe);
    probe = undefined;
    result.stage = 'mobile';
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: evidence + '/users-mobile.png', fullPage: true });
    result.passed = result.hmrEditApplied && result.rows > 0 && result.api.length >= 2 && result.api.every(x => x === 200) && !result.pageErrors.length && !result.failed.length && !result.foreignRequests.length;
  } catch (error) {
    result.errorType = error.name;
    result.passed = false;
    if (page) {
      result.path = new URL(page.url()).pathname;
      await page.screenshot({ path: evidence + '/failure.png', fullPage: true }).catch(() => {});
    }
  } finally {
    if (probe) fs.unlinkSync(probe);
    await browser.close();
    fs.writeFileSync(evidence + '/browser.json', JSON.stringify(result, null, 2), { mode: 0o600 });
    console.log(JSON.stringify(result));
    process.exitCode = result.passed ? 0 : 1;
  }
})();
