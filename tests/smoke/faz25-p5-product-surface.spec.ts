import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { chmodSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

const baseURL = process.env.P5_BASE_URL ?? 'https://testai.acik.com';
const username = process.env.SMOKE_AUTH_USERNAME ?? '';
const password = process.env.SMOKE_AUTH_PASSWORD ?? '';
const expectedUsername = process.env.P5_EXPECTED_USERNAME ?? 'p5-readiness-viewer';
const expectedRole = process.env.P5_EXPECTED_ROLE ?? 'P5_READINESS_VIEWER';
const expectedUserId = process.env.P5_EXPECTED_USER_ID ?? '6';
const expectedSubscriberId = process.env.P5_EXPECTED_SUBSCRIBER_ID ?? '6';
const expectedSourceSha =
  process.env.P5_EXPECTED_SOURCE_SHA ?? '7c8cef6547d4408cc705f9c6afae49b67ed80d1a';
const expectedFrontendDigest =
  process.env.P5_EXPECTED_FRONTEND_DIGEST ??
  'sha256:d3a4b4e7f3fa752a3247eb49d0b1c842fd5be2463ce71e436b8454f341f3db38';
const liveFrontendDigest = process.env.P5_LIVE_FRONTEND_DIGEST ?? '';
const harnessRepository = process.env.P5_HARNESS_REPOSITORY ?? '';
const harnessRevision = process.env.P5_HARNESS_REVISION ?? '';
const specSha256 = process.env.P5_SPEC_SHA256 ?? '';
const configSha256 = process.env.P5_CONFIG_SHA256 ?? '';
const reportPath =
  process.env.P5_REPORT_PATH ?? '/tmp/faz25-p5-authenticated-product-surface.json';

type AcceptanceReport = {
  schemaVersion: 'faz25-p5-authenticated-product-surface-v2';
  verdict: 'PASS' | 'FAIL';
  observedAt: string;
  target: string;
  authentication: {
    browserFlow: 'KEYCLOAK_AUTHORIZATION_CODE_PKCE' | 'UNVERIFIED';
    namedPersona: string;
    applicationWindowUsed: false;
    authorizeEndpointObserved: boolean;
    pkceS256Observed: boolean;
    authorizationCodeCallbackObserved: boolean;
    codeExchangeObserved: boolean;
    codeVerifierObserved: boolean;
    loginBlockingViolationCount?: number;
  };
  lineage?: {
    expectedSourceSha: string;
    observedSourceSha: string;
    expectedFrontendDigest: string;
    liveFrontendDigest: string;
    harnessRepository: string;
    harnessRevision: string;
    specSha256: string;
    configSha256: string;
  };
  authz?: {
    userId: string;
    subscriberId: number | string | null;
    superAdmin: boolean;
    roles: string[];
    modules: Record<string, string>;
    allowedModules: string[];
    permissions: string[];
  };
  product?: {
    finalPath: string;
    profileCount: number;
    gateCount: number;
    ownerAcceptance: string;
    readinessPercentagePresent: boolean;
    verifierAction: string;
    releaseAction: string;
  };
  responsive?: {
    viewportWidth: number;
    rootOverflowPx: number;
    consoleOverflowPx: number;
    evidenceTableKeyboardScrollable: boolean;
  };
  accessibility?: {
    blockingViolationCount: number;
    violations: Array<{ id: string; impact: string | null; nodeCount: number }>;
  };
  runtime?: {
    uncaughtPageErrorCount: number;
  };
  failedTestStatus?: string;
};

const report: AcceptanceReport = {
  schemaVersion: 'faz25-p5-authenticated-product-surface-v2',
  verdict: 'FAIL',
  observedAt: new Date().toISOString(),
  target: baseURL,
  authentication: {
    browserFlow: 'UNVERIFIED',
    namedPersona: expectedUsername,
    applicationWindowUsed: false,
    authorizeEndpointObserved: false,
    pkceS256Observed: false,
    authorizationCodeCallbackObserved: false,
    codeExchangeObserved: false,
    codeVerifierObserved: false,
  },
};

test.afterEach(async ({}, testInfo) => {
  report.verdict = testInfo.status === 'passed' ? 'PASS' : 'FAIL';
  report.observedAt = new Date().toISOString();
  if (testInfo.status !== 'passed') {
    report.failedTestStatus = testInfo.status;
  }
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  chmodSync(reportPath, 0o600);
});

test('proves the named VIEW-only persona on the live P5 product surface', async ({ page }) => {
  expect(username, 'SMOKE_AUTH_USERNAME must be configured').toBe(expectedUsername);
  expect(password, 'SMOKE_AUTH_PASSWORD must be configured').not.toBe('');

  const buildInfoResponse = await page.request.get(`${baseURL}/build-info.json`);
  expect(buildInfoResponse.ok(), 'build-info.json must be reachable').toBe(true);
  const buildInfo = (await buildInfoResponse.json()) as { sha?: string };
  report.lineage = {
    expectedSourceSha,
    observedSourceSha: buildInfo.sha ?? '',
    expectedFrontendDigest,
    liveFrontendDigest,
    harnessRepository,
    harnessRevision,
    specSha256,
    configSha256,
  };
  expect(expectedSourceSha).toMatch(/^[0-9a-f]{40}$/);
  expect(report.lineage.observedSourceSha).toBe(expectedSourceSha);
  expect(expectedFrontendDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(liveFrontendDigest).toBe(expectedFrontendDigest);
  expect(harnessRepository).toBe('Halildeu/platform-k8s-gitops');
  expect(harnessRevision).toMatch(/^[0-9a-f]{40}$/);
  expect(specSha256).toMatch(/^[0-9a-f]{64}$/);
  expect(configSha256).toMatch(/^[0-9a-f]{64}$/);

  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.name));
  const browserFlow = {
    authorizeEndpointObserved: false,
    pkceS256Observed: false,
    authorizationCodeCallbackObserved: false,
    codeExchangeObserved: false,
    codeVerifierObserved: false,
  };
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/realms/platform-test/protocol/openid-connect/auth') {
      browserFlow.authorizeEndpointObserved = true;
      browserFlow.pkceS256Observed =
        url.searchParams.get('code_challenge_method') === 'S256' &&
        Boolean(url.searchParams.get('code_challenge'));
    }
    if (
      request.isNavigationRequest() &&
      url.pathname === '/admin/interview-evidence' &&
      url.searchParams.has('code') &&
      url.searchParams.has('state')
    ) {
      browserFlow.authorizationCodeCallbackObserved = true;
    }
    if (
      request.method() === 'POST' &&
      url.pathname === '/realms/platform-test/protocol/openid-connect/token'
    ) {
      const form = new URLSearchParams(request.postData() ?? '');
      if (form.get('grant_type') === 'authorization_code') {
        browserFlow.codeExchangeObserved = true;
        browserFlow.codeVerifierObserved = Boolean(form.get('code_verifier'));
      }
    }
  });
  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) return;
    const url = new URL(frame.url());
    if (url.pathname !== '/admin/interview-evidence') return;
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    if (
      (url.searchParams.has('code') && url.searchParams.has('state')) ||
      (fragment.has('code') && fragment.has('state'))
    ) {
      browserFlow.authorizationCodeCallbackObserved = true;
    }
  });

  await page.goto('/login?redirect=%2Fadmin%2Finterview-evidence', {
    waitUntil: 'domcontentloaded',
  });
  const corporateLogin = page.getByTestId('corporate-login-button');
  await expect(corporateLogin).toBeVisible();
  await expect(corporateLogin).toBeEnabled();
  await corporateLogin.click();

  await expect(page.locator('#username')).toBeVisible({ timeout: 60_000 });
  expect(new URL(page.url()).pathname).toBe(
    '/realms/platform-test/protocol/openid-connect/auth',
  );
  const loginAxeResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const loginBlockingViolations = loginAxeResults.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  );
  expect(loginBlockingViolations).toEqual([]);
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  const meResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/authz/me' &&
      response.request().method() === 'GET' &&
      response.status() === 200,
    { timeout: 90_000 },
  );
  await page.locator('#kc-login').click();

  const consoleSurface = page.getByTestId('deployment-readiness-console');
  await expect(consoleSurface).toBeVisible({ timeout: 90_000 });
  await expect(page).toHaveURL(/\/admin\/interview-evidence(?:[?#].*)?$/);
  const meResponse = await meResponsePromise;
  const me = (await meResponse.json()) as {
    userId: string | number;
    subscriberId: string | number | null;
    superAdmin: boolean;
    roles: string[];
    modules: Record<string, string>;
    allowedModules: string[];
    permissions: string[];
  };
  report.authz = {
    userId: String(me.userId),
    subscriberId: me.subscriberId,
    superAdmin: me.superAdmin,
    roles: me.roles,
    modules: me.modules,
    allowedModules: me.allowedModules,
    permissions: me.permissions,
  };
  expect(report.authz.userId).toBe(expectedUserId);
  expect(String(report.authz.subscriberId)).toBe(expectedSubscriberId);
  expect(report.authz.superAdmin).toBe(false);
  expect(report.authz.roles).toEqual([expectedRole]);
  expect(report.authz.modules).toEqual({ INTERVIEW_EVIDENCE: 'VIEW' });
  expect(report.authz.allowedModules).toEqual(['INTERVIEW_EVIDENCE']);
  expect(report.authz.permissions).toEqual(['INTERVIEW_EVIDENCE']);

  expect(browserFlow.authorizeEndpointObserved).toBe(true);
  expect(browserFlow.pkceS256Observed).toBe(true);
  expect(browserFlow.authorizationCodeCallbackObserved).toBe(true);
  expect(browserFlow.codeExchangeObserved).toBe(true);
  expect(browserFlow.codeVerifierObserved).toBe(true);
  report.authentication = {
    browserFlow: 'KEYCLOAK_AUTHORIZATION_CODE_PKCE',
    namedPersona: expectedUsername,
    applicationWindowUsed: false,
    ...browserFlow,
    loginBlockingViolationCount: loginBlockingViolations.length,
  };

  const profileCatalog = page.getByTestId('deployment-profile-catalog');
  const evidenceTable = page.getByTestId('deployment-evidence-table');
  const profileCount = await profileCatalog.getByRole('button').count();
  const gateRows = evidenceTable.locator('tbody > tr');
  const gateCount = await gateRows.count();
  const gateIds = await gateRows.evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-testid')),
  );
  const gateOwnerStates = (await gateRows.locator('td:last-child').allInnerTexts()).map((text) =>
    text.replace(/\s+/g, ' ').trim(),
  );
  const consoleText = await consoleSurface.innerText();
  const actionStatus = page.getByTestId('deployment-action-status');
  const actionStatusText = (await actionStatus.innerText()).replace(/\s+/g, ' ').trim();
  const verifierAction =
    actionStatusText.match(/Verifier action:\s*([A-Z_]+)/)?.[1] ?? 'UNVERIFIED';
  const releaseAction =
    actionStatusText.match(/Release action:\s*([A-Z_]+)/)?.[1] ?? 'UNVERIFIED';

  expect(profileCount).toBe(4);
  await expect(evidenceTable.getByRole('columnheader')).toHaveCount(6);
  expect(gateCount).toBe(8);
  expect(gateIds).toEqual([
    'deployment-gate-SUPPLY_CHAIN',
    'deployment-gate-PROFILE_RENDER',
    'deployment-gate-IDENTITY',
    'deployment-gate-EGRESS',
    'deployment-gate-SECRET_ROTATION',
    'deployment-gate-BACKUP_RESTORE',
    'deployment-gate-UPGRADE_ROLLBACK',
    'deployment-gate-AUDIT_EXPORT',
  ]);
  expect(gateOwnerStates).toEqual(Array.from({ length: 8 }, () => 'Kabul yok'));
  await expect(consoleSurface).toContainText('SENTETİK · PRE-G0 · VIEW-ONLY');
  await expect(consoleSurface).toContainText('Owner kabulü 0/8');
  await expect(consoleSurface).toContainText('Tek yüzde / ortalama yok');
  expect(consoleText).not.toMatch(/\b\d+%/);
  await expect(actionStatus).toContainText('Verifier action: UNAVAILABLE');
  await expect(actionStatus).toContainText('Release action: UNAVAILABLE');
  expect(verifierAction).toBe('UNAVAILABLE');
  expect(releaseAction).toBe('UNAVAILABLE');
  await expect(consoleSurface.getByRole('button', { name: /verifier/i })).toHaveCount(0);
  await expect(consoleSurface.getByRole('button', { name: /release/i })).toHaveCount(0);

  const dedicatedProfile = page.getByTestId('deployment-profile-DEDICATED');
  await dedicatedProfile.focus();
  await page.keyboard.press('Space');
  await expect(dedicatedProfile).toHaveAttribute('aria-pressed', 'true');
  await expect(dedicatedProfile).toHaveAttribute(
    'aria-controls',
    'deployment-profile-evidence-panel',
  );
  await expect(page.getByTestId('deployment-profile-detail')).toContainText('Dedicated Tenant');
  await expect(page.getByTestId('deployment-profile-detail')).toContainText('DEDICATED_TENANT');

  await expect(page.getByTestId('deployment-responsibility-boundary')).toContainText(
    'OPERATIONAL_RESPONSIBILITY_NOT_PROVIDED',
  );
  await expect(page.getByTestId('deployment-responsibility-boundary')).toContainText(
    'inference yasak',
  );
  await expect(page.getByTestId('deployment-freshness-boundary')).toContainText(
    'POLICY_NOT_DEFINED',
  );
  await expect(page.getByTestId('deployment-activation-boundary')).toContainText(
    'Connector: P4 ayrı gate',
  );
  await expect(page.getByTestId('deployment-activation-boundary')).toContainText(
    'AI capability: P6 ayrı gate',
  );

  report.product = {
    finalPath: new URL(page.url()).pathname,
    profileCount,
    gateCount,
    ownerAcceptance: `${gateOwnerStates.filter((state) => state !== 'Kabul yok').length}/${gateCount}`,
    readinessPercentagePresent: /\b\d+%/.test(consoleText),
    verifierAction,
    releaseAction,
  };

  await page.setViewportSize({ width: 390, height: 844 });
  await consoleSurface.scrollIntoViewIfNeeded();
  await expect(profileCatalog.getByRole('button')).toHaveCount(4);
  await expect(page.getByTestId('deployment-table-scroll-hint')).toBeVisible();
  const evidenceRegion = page.getByRole('region', { name: /kanıt kapıları/ });
  await evidenceRegion.scrollIntoViewIfNeeded();
  await evidenceRegion.focus();
  await expect(evidenceRegion).toBeFocused();
  const initialScroll = await evidenceRegion.evaluate((region) => {
    region.scrollLeft = 0;
    return region.scrollLeft;
  });
  expect(initialScroll).toBe(0);
  await page.keyboard.press('ArrowRight');
  await expect
    .poll(() => evidenceRegion.evaluate((region) => region.scrollLeft))
    .toBeGreaterThan(0);
  const evidenceScrollLeft = await evidenceRegion.evaluate((region) => region.scrollLeft);

  const layout = await page.evaluate(() => ({
    rootOverflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    rootOverflowModes: [document.documentElement, document.body, document.querySelector('main')]
      .filter((element): element is HTMLElement => element instanceof HTMLElement)
      .map((element) => window.getComputedStyle(element).overflowX),
  }));
  const consoleOverflowPx = await consoleSurface.evaluate(
    (surface) => surface.scrollWidth - surface.clientWidth,
  );
  expect(layout.rootOverflowPx).toBeLessThanOrEqual(1);
  expect(layout.rootOverflowModes).not.toContain('hidden');
  expect(layout.rootOverflowModes).not.toContain('clip');
  expect(consoleOverflowPx).toBeLessThanOrEqual(1);
  report.responsive = {
    viewportWidth: 390,
    rootOverflowPx: layout.rootOverflowPx,
    consoleOverflowPx,
    evidenceTableKeyboardScrollable: evidenceScrollLeft > 0,
  };

  const axeResults = await new AxeBuilder({ page })
    .include('main')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const blockingViolations = axeResults.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  );
  const accessibility = {
    blockingViolationCount: blockingViolations.length,
    violations: blockingViolations.map((violation) => ({
      id: violation.id,
      impact: violation.impact ?? null,
      nodeCount: violation.nodes.length,
    })),
  };
  report.accessibility = accessibility;
  expect(accessibility.violations).toEqual([]);

  report.runtime = { uncaughtPageErrorCount: pageErrors.length };
  expect(pageErrors).toEqual([]);
});
