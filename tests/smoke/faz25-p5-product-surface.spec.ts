import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';
import { chmodSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

const baseURL = process.env.P5_BASE_URL ?? 'https://testai.acik.com';
const issuer =
  process.env.P5_KEYCLOAK_ISSUER ?? 'https://testai.acik.com/realms/platform-test';
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
const expectedBuildRunId = process.env.P5_EXPECTED_BUILD_RUN_ID ?? '29328643364';
const liveFrontendDigest = process.env.P5_LIVE_FRONTEND_DIGEST ?? '';
const harnessRepository = process.env.P5_HARNESS_REPOSITORY ?? '';
const harnessRevision = process.env.P5_HARNESS_REVISION ?? '';
const specSha256 = process.env.P5_SPEC_SHA256 ?? '';
const configSha256 = process.env.P5_CONFIG_SHA256 ?? '';
const packageLockSha256 = process.env.P5_PACKAGE_LOCK_SHA256 ?? '';
const chromiumExecutableSha256 = process.env.P5_CHROMIUM_EXECUTABLE_SHA256 ?? '';
const chromiumRevision = process.env.P5_CHROMIUM_REVISION ?? '';
const chromiumBrowserVersion = process.env.P5_CHROMIUM_BROWSER_VERSION ?? '';
const chromiumExecutableVersion = process.env.P5_CHROMIUM_EXECUTABLE_VERSION ?? '';
const playwrightVersion = process.env.P5_PLAYWRIGHT_VERSION ?? '';
const reportPath =
  process.env.P5_REPORT_PATH ?? '/tmp/faz25-p5-authenticated-product-surface.json';

const githubContext = {
  repository: process.env.P5_GITHUB_REPOSITORY ?? '',
  workflow: process.env.P5_GITHUB_WORKFLOW ?? '',
  runId: process.env.P5_GITHUB_RUN_ID ?? '',
  runAttempt: process.env.P5_GITHUB_RUN_ATTEMPT ?? '',
  eventName: process.env.P5_GITHUB_EVENT_NAME ?? '',
  ref: process.env.P5_GITHUB_REF ?? '',
  sha: process.env.P5_GITHUB_SHA ?? '',
};

const appOrigin = new URL(baseURL).origin;
const issuerUrl = new URL(issuer);
const issuerOrigin = issuerUrl.origin;
const issuerPath = issuerUrl.pathname.replace(/\/$/, '');
const authorizationPath = `${issuerPath}/protocol/openid-connect/auth`;
const tokenPath = `${issuerPath}/protocol/openid-connect/token`;
const expectedFinalPath = '/admin/interview-evidence';
const startedAt = new Date().toISOString();

const expectedProfileIds = [
  'deployment-profile-MANAGED',
  'deployment-profile-DEDICATED',
  'deployment-profile-BYO_REGION',
  'deployment-profile-SOVEREIGN_ON_PREM',
] as const;
const expectedGateIds = [
  'deployment-gate-SUPPLY_CHAIN',
  'deployment-gate-PROFILE_RENDER',
  'deployment-gate-IDENTITY',
  'deployment-gate-EGRESS',
  'deployment-gate-SECRET_ROTATION',
  'deployment-gate-BACKUP_RESTORE',
  'deployment-gate-UPGRADE_ROLLBACK',
  'deployment-gate-AUDIT_EXPORT',
] as const;
const expectedHeaderLabels = [
  'Kapı / authority',
  'Exact durum',
  'Kanıt sınıfı',
  'Drill',
  'Receipt / zaman',
  'Owner',
] as const;
const expectedInteractiveControlIds = [
  ...expectedProfileIds,
  'deployment-evidence-scroll-region',
] as const;

type AcceptanceReport = {
  schemaVersion: 'faz25-p5-authenticated-product-surface-v2';
  verdict: 'PASS' | 'FAIL';
  startedAt: string;
  observedAt: string;
  target: string;
  github: typeof githubContext;
  authentication: {
    browserFlow: 'KEYCLOAK_AUTHORIZATION_CODE_PKCE' | 'UNVERIFIED';
    namedPersona: string;
    applicationWindowUsed: false;
    issuerMatched: boolean;
    authorizeEndpointObserved: boolean;
    pkceS256Observed: boolean;
    authorizationCodeCallbackObserved: boolean;
    callbackOriginMatched: boolean;
    codeExchangeObserved: boolean;
    codeVerifierObserved: boolean;
    stateCorrelationMatched: boolean;
    codeCorrelationMatched: boolean;
    pkceChallengeMatched: boolean;
    tokenResponseSuccessful: boolean;
    oauthParametersCleared: boolean;
    loginBlockingViolationCount?: number;
  };
  lineage: {
    expectedSourceSha: string;
    observedSourceSha: string;
    expectedFrontendDigest: string;
    liveFrontendDigest: string;
    expectedBuildRunId: string;
    harnessRepository: string;
    harnessRevision: string;
    specSha256: string;
    configSha256: string;
    packageLockSha256: string;
    chromiumExecutableSha256: string;
    chromiumRevision: string;
    chromiumBrowserVersion: string;
    chromiumExecutableVersion: string;
    playwrightVersion: string;
  };
  authz?: {
    userIdMatched: boolean;
    subscriberIdMatched: boolean;
    superAdminFalse: boolean;
    exactRolesMatched: boolean;
    exactModulesMatched: boolean;
    exactAllowedModulesMatched: boolean;
    exactPermissionsMatched: boolean;
    manageGrantAbsent: boolean;
    exactViewOnlySnapshotMatched: boolean;
  };
  product?: {
    finalPath: string;
    profileIds: string[];
    gateIds: string[];
    headerLabels: string[];
    gateOwnerZeroCount: number;
    ownerAcceptance: string;
    readinessPercentagePresent: boolean;
    verifierAction: string;
    releaseAction: string;
    interactiveControlIds: string[];
  };
  responsive?: {
    viewportWidth: number;
    rootOverflowPx: number;
    consoleOverflowPx: number;
    evidenceTableKeyboardScrollable: boolean;
  };
  accessibility?: {
    loginBlockingViolationCount: number;
    productBlockingViolationCount: number;
    blockingViolationCount: number;
    violations: Array<{
      surface: 'login' | 'product';
      id: string;
      impact: string | null;
      nodeCount: number;
    }>;
  };
  runtime?: {
    uncaughtPageErrorCount: number;
  };
  failedTestStatus?: string;
};

const report: AcceptanceReport = {
  schemaVersion: 'faz25-p5-authenticated-product-surface-v2',
  verdict: 'FAIL',
  startedAt,
  observedAt: startedAt,
  target: baseURL,
  github: githubContext,
  authentication: {
    browserFlow: 'UNVERIFIED',
    namedPersona: expectedUsername,
    applicationWindowUsed: false,
    issuerMatched: false,
    authorizeEndpointObserved: false,
    pkceS256Observed: false,
    authorizationCodeCallbackObserved: false,
    callbackOriginMatched: false,
    codeExchangeObserved: false,
    codeVerifierObserved: false,
    stateCorrelationMatched: false,
    codeCorrelationMatched: false,
    pkceChallengeMatched: false,
    tokenResponseSuccessful: false,
    oauthParametersCleared: false,
  },
  lineage: {
    expectedSourceSha,
    observedSourceSha: '',
    expectedFrontendDigest,
    liveFrontendDigest,
    expectedBuildRunId,
    harnessRepository,
    harnessRevision,
    specSha256,
    configSha256,
    packageLockSha256,
    chromiumExecutableSha256,
    chromiumRevision,
    chromiumBrowserVersion,
    chromiumExecutableVersion,
    playwrightVersion,
  },
};

// This file intentionally owns exactly one acceptance test. afterEach writes
// one terminal report and cannot overwrite evidence from another test case.
test.afterEach(async ({}, testInfo) => {
  report.verdict = testInfo.status === 'passed' ? 'PASS' : 'FAIL';
  report.observedAt = new Date().toISOString();
  if (testInfo.status !== 'passed') report.failedTestStatus = testInfo.status;
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  chmodSync(reportPath, 0o600);
});

test('proves the named VIEW-only persona on the live P5 product surface', async ({ page }) => {
  expect(username, 'SMOKE_AUTH_USERNAME must be the dedicated persona').toBe(expectedUsername);
  expect(password, 'SMOKE_AUTH_PASSWORD must be configured').not.toBe('');
  expect(baseURL).toBe('https://testai.acik.com');
  expect(issuer).toBe('https://testai.acik.com/realms/platform-test');
  expect(githubContext).toEqual({
    repository: 'Halildeu/platform-k8s-gitops',
    workflow: 'Verify Faz 25 P5 authenticated product surface',
    runId: expect.stringMatching(/^[0-9]+$/),
    runAttempt: expect.stringMatching(/^[0-9]+$/),
    eventName: 'workflow_dispatch',
    ref: 'refs/heads/main',
    sha: harnessRevision,
  });

  expect(expectedSourceSha).toMatch(/^[0-9a-f]{40}$/);
  expect(expectedFrontendDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(liveFrontendDigest).toBe(expectedFrontendDigest);
  expect(expectedBuildRunId).toMatch(/^[0-9]+$/);
  expect(harnessRepository).toBe('Halildeu/platform-k8s-gitops');
  expect(harnessRevision).toMatch(/^[0-9a-f]{40}$/);
  for (const digest of [
    specSha256,
    configSha256,
    packageLockSha256,
    chromiumExecutableSha256,
  ]) {
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
  }
  expect(chromiumRevision).toBe('1223');
  expect(chromiumBrowserVersion).toBe('148.0.7778.96');
  expect(chromiumExecutableVersion).toContain('148.0.7778.96');
  expect(playwrightVersion).toBe('Version 1.60.0');

  const buildInfoUrl = `${baseURL}/build-info.json`;
  const buildInfoResponse = await page.request.get(buildInfoUrl, {
    maxRedirects: 0,
  });
  expect(buildInfoResponse.ok(), 'build-info.json must be reachable').toBe(true);
  expect(buildInfoResponse.url()).toBe(buildInfoUrl);
  expect(buildInfoResponse.headers()['content-type']).toMatch(
    /^application\/json(?:;|$)/i,
  );
  const buildInfo = (await buildInfoResponse.json()) as Record<string, unknown>;
  expect(Array.isArray(buildInfo)).toBe(false);
  expect(buildInfo).not.toBeNull();
  expect(typeof buildInfo).toBe('object');
  expect(Object.keys(buildInfo).sort()).toEqual([
    'assets',
    'buildTime',
    'image',
    'imageDigest',
    'origin',
    'ref',
    'remotes',
    'rootEntry',
    'sha',
    'shortSha',
  ]);
  expect(buildInfo.origin).toBe(baseURL);
  expect(buildInfo.ref).toBe('main');
  report.lineage.observedSourceSha =
    typeof buildInfo.sha === 'string' ? buildInfo.sha : '';
  expect(report.lineage.observedSourceSha).toBe(expectedSourceSha);

  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.name));

  const observed = {
    issuerMatched: false,
    authorizeEndpointObserved: false,
    pkceS256Observed: false,
    authorizationCodeCallbackObserved: false,
    callbackOriginMatched: false,
    codeExchangeObserved: false,
    codeVerifierObserved: false,
    stateCorrelationMatched: false,
    codeCorrelationMatched: false,
    pkceChallengeMatched: false,
    tokenResponseSuccessful: false,
    oauthParametersCleared: false,
  };
  let authorizeCodeChallenge = '';
  let callbackCode = '';
  let exchangeCode = '';
  let codeVerifier = '';
  let authorizeState = '';
  let callbackState = '';

  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin === issuerOrigin && url.pathname === authorizationPath) {
      observed.authorizeEndpointObserved = true;
      observed.issuerMatched = true;
      authorizeCodeChallenge = url.searchParams.get('code_challenge') ?? '';
      authorizeState = url.searchParams.get('state') ?? '';
      observed.pkceS256Observed =
        url.searchParams.get('code_challenge_method') === 'S256' &&
        authorizeCodeChallenge.length >= 43 &&
        authorizeState.length > 0;
    }
    if (
      request.isNavigationRequest() &&
      url.origin === appOrigin &&
      url.pathname === expectedFinalPath &&
      url.searchParams.has('code') &&
      url.searchParams.has('state')
    ) {
      observed.authorizationCodeCallbackObserved = true;
      observed.callbackOriginMatched = true;
      callbackCode = url.searchParams.get('code') ?? '';
      callbackState = url.searchParams.get('state') ?? '';
    }
    if (request.method() === 'POST' && url.origin === issuerOrigin && url.pathname === tokenPath) {
      const form = new URLSearchParams(request.postData() ?? '');
      if (form.get('grant_type') === 'authorization_code') {
        observed.codeExchangeObserved = true;
        exchangeCode = form.get('code') ?? '';
        codeVerifier = form.get('code_verifier') ?? '';
        observed.codeVerifierObserved = codeVerifier.length >= 43;
      }
    }
  });
  page.on('framenavigated', (frame) => {
    if (frame !== page.mainFrame()) return;
    const url = new URL(frame.url());
    if (url.origin !== appOrigin || url.pathname !== expectedFinalPath) return;
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const code = url.searchParams.get('code') ?? fragment.get('code') ?? '';
    const state = url.searchParams.get('state') ?? fragment.get('state') ?? '';
    if (code && state) {
      observed.authorizationCodeCallbackObserved = true;
      observed.callbackOriginMatched = true;
      callbackCode = code;
      callbackState = state;
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
  const keycloakLoginUrl = new URL(page.url());
  expect(keycloakLoginUrl.origin).toBe(issuerOrigin);
  expect(keycloakLoginUrl.pathname).toBe(authorizationPath);
  expect(keycloakLoginUrl.searchParams.get('client_id')).toBe('frontend');
  expect(keycloakLoginUrl.searchParams.get('code_challenge_method')).toBe('S256');
  const redirectUri = new URL(keycloakLoginUrl.searchParams.get('redirect_uri') ?? 'invalid:');
  expect(redirectUri.origin).toBe(appOrigin);
  expect(redirectUri.pathname).toBe(expectedFinalPath);

  const loginAxeResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const loginBlockingViolations = loginAxeResults.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  );
  expect(loginBlockingViolations).toEqual([]);

  // Credentials are entered only after exact canonical issuer/origin binding.
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  const tokenResponsePromise = page.waitForResponse(
    (response) => {
      const url = new URL(response.url());
      return (
        url.origin === issuerOrigin &&
        url.pathname === tokenPath &&
        response.request().method() === 'POST'
      );
    },
    { timeout: 90_000 },
  );
  const meResponsePromise = page.waitForResponse(
    (response) => {
      const url = new URL(response.url());
      return (
        url.origin === appOrigin &&
        url.pathname === '/api/v1/authz/me' &&
        response.request().method() === 'GET' &&
        response.status() === 200
      );
    },
    { timeout: 90_000 },
  );
  await page.locator('#kc-login').click();

  const tokenResponse = await tokenResponsePromise;
  observed.tokenResponseSuccessful = tokenResponse.status() >= 200 && tokenResponse.status() < 300;
  expect(observed.tokenResponseSuccessful).toBe(true);

  const consoleSurface = page.getByTestId('deployment-readiness-console');
  await expect(consoleSurface).toBeVisible({ timeout: 90_000 });
  await expect(page).toHaveURL(/\/admin\/interview-evidence(?:[?#].*)?$/);
  const finalUrl = new URL(page.url());
  const finalFragment = new URLSearchParams(finalUrl.hash.replace(/^#/, ''));
  observed.oauthParametersCleared = ['code', 'state', 'session_state'].every(
    (key) => !finalUrl.searchParams.has(key) && !finalFragment.has(key),
  );
  expect(finalUrl.origin).toBe(appOrigin);
  expect(finalUrl.pathname).toBe(expectedFinalPath);
  expect(observed.oauthParametersCleared).toBe(true);

  observed.codeCorrelationMatched =
    callbackCode.length > 0 && exchangeCode.length > 0 && callbackCode === exchangeCode;
  observed.stateCorrelationMatched =
    authorizeState.length > 0 && callbackState.length > 0 && authorizeState === callbackState;
  const calculatedChallenge = codeVerifier
    ? createHash('sha256').update(codeVerifier).digest('base64url')
    : '';
  observed.pkceChallengeMatched =
    authorizeCodeChallenge.length > 0 && calculatedChallenge === authorizeCodeChallenge;
  expect(observed).toEqual({
    issuerMatched: true,
    authorizeEndpointObserved: true,
    pkceS256Observed: true,
    authorizationCodeCallbackObserved: true,
    callbackOriginMatched: true,
    codeExchangeObserved: true,
    codeVerifierObserved: true,
    stateCorrelationMatched: true,
    codeCorrelationMatched: true,
    pkceChallengeMatched: true,
    tokenResponseSuccessful: true,
    oauthParametersCleared: true,
  });
  authorizeCodeChallenge = '';
  callbackCode = '';
  exchangeCode = '';
  codeVerifier = '';
  authorizeState = '';
  callbackState = '';
  report.authentication = {
    browserFlow: 'KEYCLOAK_AUTHORIZATION_CODE_PKCE',
    namedPersona: expectedUsername,
    applicationWindowUsed: false,
    ...observed,
    loginBlockingViolationCount: loginBlockingViolations.length,
  };

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
  const authz = {
    userIdMatched: String(me.userId) === expectedUserId,
    subscriberIdMatched: String(me.subscriberId) === expectedSubscriberId,
    superAdminFalse: me.superAdmin === false,
    exactRolesMatched: JSON.stringify(me.roles) === JSON.stringify([expectedRole]),
    exactModulesMatched:
      JSON.stringify(me.modules) === JSON.stringify({ INTERVIEW_EVIDENCE: 'VIEW' }),
    exactAllowedModulesMatched:
      JSON.stringify(me.allowedModules) === JSON.stringify(['INTERVIEW_EVIDENCE']),
    exactPermissionsMatched:
      JSON.stringify(me.permissions) === JSON.stringify(['INTERVIEW_EVIDENCE']),
    manageGrantAbsent:
      !Object.values(me.modules).includes('MANAGE') &&
      !me.permissions.some((permission) => /MANAGE|APPROVE|RELEASE/i.test(permission)),
    exactViewOnlySnapshotMatched: false,
  };
  authz.exactViewOnlySnapshotMatched = Object.entries(authz)
    .filter(([key]) => key !== 'exactViewOnlySnapshotMatched')
    .every(([, value]) => value === true);
  expect(authz).toEqual({
    userIdMatched: true,
    subscriberIdMatched: true,
    superAdminFalse: true,
    exactRolesMatched: true,
    exactModulesMatched: true,
    exactAllowedModulesMatched: true,
    exactPermissionsMatched: true,
    manageGrantAbsent: true,
    exactViewOnlySnapshotMatched: true,
  });
  report.authz = authz;

  const profileCatalog = page.getByTestId('deployment-profile-catalog');
  await expect(profileCatalog).toBeVisible();
  const profileButtons = profileCatalog.getByRole('button');
  const profileIds = await profileButtons.evaluateAll((buttons) =>
    buttons.map((button) => button.getAttribute('data-testid') ?? ''),
  );
  expect(profileIds).toEqual(expectedProfileIds);
  for (const profileId of expectedProfileIds) {
    const profile = page.getByTestId(profileId);
    await expect(profile).toBeVisible();
    await expect(profile).toBeEnabled();
  }

  const evidenceTable = page.getByTestId('deployment-evidence-table');
  await expect(evidenceTable).toBeVisible();
  const headers = evidenceTable.getByRole('columnheader');
  await expect(headers).toHaveCount(expectedHeaderLabels.length);
  for (let index = 0; index < expectedHeaderLabels.length; index += 1) {
    await expect(headers.nth(index)).toBeVisible();
  }
  const headerLabels = (await headers.allInnerTexts()).map((text) =>
    text.replace(/\s+/g, ' ').trim(),
  );
  expect(headerLabels).toEqual(expectedHeaderLabels);
  const ownerColumnIndex = headerLabels.indexOf('Owner');
  expect(ownerColumnIndex).toBe(5);

  const gateRows = evidenceTable.locator('tbody > tr');
  const gateIds = await gateRows.evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-testid') ?? ''),
  );
  expect(gateIds).toEqual(expectedGateIds);
  for (let index = 0; index < expectedGateIds.length; index += 1) {
    await expect(gateRows.nth(index)).toBeVisible();
  }
  await expect(gateRows).toHaveCount(expectedGateIds.length);
  const gateOwnerStates = await gateRows.evaluateAll(
    (rows, { ownerIndex, expectedCellCount }) =>
      rows.map((row, rowIndex) => {
        const cells = Array.from(row.children);
        if (cells.length !== expectedCellCount) {
          throw new Error(
            `Row ${rowIndex}: expected ${expectedCellCount} direct cells, got ${cells.length}`,
          );
        }
        const ownerCell = cells[ownerIndex];
        if (!(ownerCell instanceof HTMLTableCellElement)) {
          throw new Error(`Row ${rowIndex}: owner cell ${ownerIndex} is not a table cell`);
        }
        return (ownerCell.textContent ?? '').replace(/\s+/g, ' ').trim();
      }),
    { ownerIndex: ownerColumnIndex, expectedCellCount: expectedHeaderLabels.length },
  );
  expect(gateOwnerStates).toEqual(Array.from({ length: 8 }, () => 'Kabul yok'));

  const consoleText = await consoleSurface.innerText();
  const actionStatus = page.getByTestId('deployment-action-status');
  const actionStatusText = (await actionStatus.innerText()).replace(/\s+/g, ' ').trim();
  const verifierAction =
    actionStatusText.match(/Verifier action:\s*([A-Z_]+)/)?.[1] ?? 'UNVERIFIED';
  const releaseAction =
    actionStatusText.match(/Release action:\s*([A-Z_]+)/)?.[1] ?? 'UNVERIFIED';

  await expect(consoleSurface).toContainText('SENTETİK · PRE-G0 · VIEW-ONLY');
  await expect(consoleSurface).toContainText('Owner kabulü 0/8');
  await expect(consoleSurface).toContainText('Tek yüzde / ortalama yok');
  expect(consoleText).not.toMatch(/\b\d+%/);
  expect(verifierAction).toBe('UNAVAILABLE');
  expect(releaseAction).toBe('UNAVAILABLE');

  const interactiveControls = consoleSurface.locator(
    'button, a[href], input:not([type="hidden"]), select, textarea, [contenteditable="true"], [role="button"], [role="link"], [role="menuitem"], [role="checkbox"], [role="switch"], [role="tab"], [tabindex]:not([tabindex="-1"])',
  );
  const interactiveControlIds = await interactiveControls.evaluateAll((controls) =>
    controls.map((control) => {
      const testId = control.getAttribute('data-testid');
      if (testId) return testId;
      if (
        control.getAttribute('role') === 'region' &&
        control.getAttribute('tabindex') === '0' &&
        /kanıt kapıları/i.test(control.getAttribute('aria-label') ?? '')
      ) {
        return 'deployment-evidence-scroll-region';
      }
      return `UNEXPECTED:${control.tagName}:${control.getAttribute('role') ?? ''}:${control.getAttribute('type') ?? ''}`;
    }),
  );
  expect(interactiveControlIds).toEqual(expectedInteractiveControlIds);

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
    finalPath: finalUrl.pathname,
    profileIds,
    gateIds,
    headerLabels,
    gateOwnerZeroCount: gateOwnerStates.filter((state) => state === 'Kabul yok').length,
    ownerAcceptance: `${gateOwnerStates.filter((state) => state !== 'Kabul yok').length}/${gateIds.length}`,
    readinessPercentagePresent: /\b\d+%/.test(consoleText),
    verifierAction,
    releaseAction,
    interactiveControlIds,
  };

  await page.setViewportSize({ width: 390, height: 844 });
  await consoleSurface.scrollIntoViewIfNeeded();
  await expect(profileButtons).toHaveCount(4);
  await expect(page.getByTestId('deployment-table-scroll-hint')).toBeVisible();
  const evidenceRegion = page.getByRole('region', { name: /kanıt kapıları/ });
  await evidenceRegion.scrollIntoViewIfNeeded();
  await evidenceRegion.focus();
  await expect(evidenceRegion).toBeFocused();
  await evidenceRegion.evaluate((region) => {
    region.scrollLeft = 0;
  });
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

  const main = page.getByRole('main');
  await expect(main).toHaveCount(1);
  await expect(main).toBeVisible();
  expect(await main.locator('[data-testid="deployment-readiness-console"]').count()).toBe(1);
  const productAxeResults = await new AxeBuilder({ page })
    .include('[data-testid="deployment-readiness-console"]')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const productBlockingViolations = productAxeResults.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  );
  const violations = [
    ...loginBlockingViolations.map((violation) => ({
      surface: 'login' as const,
      id: violation.id,
      impact: violation.impact ?? null,
      nodeCount: violation.nodes.length,
    })),
    ...productBlockingViolations.map((violation) => ({
      surface: 'product' as const,
      id: violation.id,
      impact: violation.impact ?? null,
      nodeCount: violation.nodes.length,
    })),
  ];
  report.accessibility = {
    loginBlockingViolationCount: loginBlockingViolations.length,
    productBlockingViolationCount: productBlockingViolations.length,
    blockingViolationCount: violations.length,
    violations,
  };
  expect(violations).toEqual([]);

  report.runtime = { uncaughtPageErrorCount: pageErrors.length };
  expect(pageErrors).toEqual([]);
});
