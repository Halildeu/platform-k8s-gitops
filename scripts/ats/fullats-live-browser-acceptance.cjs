'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;

const baseURL = process.env.BASE_URL;
const recruiterUsername = process.env.RECRUITER_USERNAME;
const recruiterPasswordFile = process.env.RECRUITER_PASSWORD_FILE;
const evidenceDir = process.env.EVIDENCE_DIR;

if (baseURL !== 'https://testai.acik.com') throw new Error('test-only base URL required');
if (!recruiterUsername || !recruiterPasswordFile || !evidenceDir) {
  throw new Error('missing browser acceptance configuration');
}

fs.mkdirSync(evidenceDir, { recursive: true });
const recruiterPassword = fs.readFileSync(recruiterPasswordFile, 'utf8').trim();
if (recruiterPassword.length < 12) throw new Error('recruiter credential invalid');

const runSuffix = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
const candidateName = `Sentetik ATS Adayı ${runSuffix}`;
const candidateEmail = `fullats-${runSuffix}@example.test`;
const networkEvidence = [];
const allowedEvidencePaths = [
  '/api/ats/v1/jobs',
  '/api/ats/v1/candidate/applications',
  '/api/ats/v1/recruiter/applications',
  '/api/v1/authz/me',
];

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const relevantPath = (urlValue) => {
  try {
    const parsed = new URL(urlValue);
    return allowedEvidencePaths.some((prefix) => parsed.pathname.startsWith(prefix))
      ? parsed.pathname
      : null;
  } catch {
    return null;
  }
};

const attachNetworkEvidence = (page, persona) => {
  page.on('response', (response) => {
    const pathname = relevantPath(response.url());
    if (!pathname) return;
    networkEvidence.push({ persona, method: response.request().method(), pathname, status: response.status() });
  });
};

const assertNoHorizontalOverflow = async (page, surface) => {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) throw new Error(`${surface}: horizontal overflow ${overflow}px`);
};

const assertAxeClean = async (page, surface) => {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  if (result.violations.length > 0) {
    const compact = result.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }));
    throw new Error(`${surface}: axe violations ${JSON.stringify(compact)}`);
  }
};

const waitVisible = async (locator, label, timeout = 60_000) => {
  await locator.waitFor({ state: 'visible', timeout }).catch((error) => {
    throw new Error(`${label} visible degil: ${error.message}`);
  });
};

void (async () => {
const buildInfo = await fetch(`${baseURL}/build-info.json`).then(async (response) => {
  if (!response.ok) throw new Error(`build-info HTTP ${response.status}`);
  return response.json();
});
if (!/^[a-f0-9]{40}$/u.test(String(buildInfo.sha ?? ''))) {
  throw new Error('live frontend sha is not immutable');
}

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
let publicRef = '';
try {
  const candidateContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
  });
  const candidatePage = await candidateContext.newPage();
  attachNetworkEvidence(candidatePage, 'candidate');

  await candidatePage.goto(`${baseURL}/jobs`, { waitUntil: 'domcontentloaded' });
  await waitVisible(candidatePage.getByRole('heading', { name: /Açık pozisyonlar/i }), 'jobs heading');
  await candidatePage.goto(`${baseURL}/jobs/urun-yoneticisi/apply`, { waitUntil: 'domcontentloaded' });
  await waitVisible(candidatePage.getByTestId('candidate-application-page'), 'candidate application page');
  await waitVisible(candidatePage.getByRole('heading', { name: 'Ürün Yöneticisi' }), 'job title');
  await candidatePage.getByTestId('fill-synthetic-resume').click();
  await candidatePage.getByTestId('candidate-fullName').fill(candidateName);
  await candidatePage.getByTestId('candidate-email').fill(candidateEmail);
  await candidatePage.getByRole('button', { name: 'Başvuruyu önizle' }).click();
  await waitVisible(candidatePage.getByTestId('candidate-application-preview'), 'candidate preview');
  await candidatePage.locator('#candidate-notice-accepted').check();
  await candidatePage.locator('#candidate-accuracy-confirmed').check();
  await assertAxeClean(candidatePage, 'candidate-preview-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-preview-mobile');

  const submitResponse = candidatePage.waitForResponse(
    (response) =>
      response.url().includes('/api/ats/v1/jobs/urun-yoneticisi/applications') &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await candidatePage.getByTestId('create-application-receipt').click();
  const submitted = await submitResponse;
  if (submitted.status() !== 201) throw new Error(`candidate submit HTTP ${submitted.status()}`);
  await waitVisible(candidatePage.getByTestId('candidate-application-receipt'), 'persistent receipt');
  publicRef = (await candidatePage.getByTestId('candidate-receipt-id').textContent())?.trim() ?? '';
  if (!/^app_[A-Za-z0-9_-]{24}$/u.test(publicRef)) throw new Error('persistent receipt ref invalid');
  const sessionShape = await candidatePage.evaluate(() => {
    const raw = sessionStorage.getItem('ats.candidate.latest.v1');
    const parsed = raw ? JSON.parse(raw) : null;
    return {
      hasRef: typeof parsed?.publicRef === 'string',
      hasToken: typeof parsed?.candidateAccessToken === 'string',
      localStorageToken: localStorage.getItem('ats.candidate.latest.v1'),
      url: location.href,
    };
  });
  if (!sessionShape.hasRef || !sessionShape.hasToken || sessionShape.localStorageToken !== null) {
    throw new Error('candidate session minimization contract failed');
  }
  if (sessionShape.url.includes(publicRef)) throw new Error('candidate reference leaked to URL');

  const candidateLink = candidatePage.locator('a[href="/candidate"]').filter({ hasText: /durumu gör/i });
  await candidateLink.click();
  await waitVisible(candidatePage.getByTestId('candidate-portal-page'), 'candidate portal');
  await waitVisible(candidatePage.getByRole('heading', { name: 'Başvuru yolculuğum' }), 'candidate journey');
  const submittedStep = candidatePage.getByRole('listitem').filter({ hasText: 'Başvuru alındı' });
  await waitVisible(submittedStep.getByText('Şimdi'), 'submitted current state');
  await assertAxeClean(candidatePage, 'candidate-portal-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-portal-mobile');

  const recruiterContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
  });
  const recruiterPage = await recruiterContext.newPage();
  attachNetworkEvidence(recruiterPage, 'recruiter');
  await recruiterPage.goto(`${baseURL}/admin/ats/recruiter`, { waitUntil: 'domcontentloaded' });

  const workspace = recruiterPage.getByTestId('recruiter-workspace-page');
  if (!(await workspace.isVisible().catch(() => false))) {
    const corporateButton = recruiterPage.getByTestId('corporate-login-button');
    if (await corporateButton.isVisible().catch(() => false)) await corporateButton.click();
    await recruiterPage.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
    await recruiterPage.locator('#username').fill(recruiterUsername);
    await recruiterPage.locator('#password').fill(recruiterPassword);
    await recruiterPage.locator('#kc-login').click();
  }
  await waitVisible(workspace, 'recruiter workspace', 60_000);
  if (recruiterPage.url().includes('/unauthorized')) throw new Error('recruiter module grant denied');
  await recruiterPage.locator('#recruiter-search').fill(candidateEmail);
  const candidateEmailText = recruiterPage.getByText(candidateEmail, { exact: true });
  await waitVisible(candidateEmailText, 'recruiter candidate card', 30_000);
  const applicationCard = candidateEmailText.locator('xpath=ancestor::article');
  await applicationCard.getByRole('button', { name: 'Başvuruyu incele' }).click();
  const reviewPanel = recruiterPage.getByTestId('recruiter-review-panel');
  await waitVisible(reviewPanel.getByText(candidateEmail, { exact: true }), 'recruiter review details');
  await assertAxeClean(recruiterPage, 'recruiter-workspace-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-workspace-desktop');

  await reviewPanel.getByRole('button', { name: 'İnsan incelemesini başlat' }).click();
  await waitVisible(reviewPanel.getByRole('button', { name: 'Mülakat planlamasına al' }), 'under review transition');
  await candidatePage.getByRole('button', { name: 'Durumu yenile' }).click();
  const reviewStep = candidatePage.getByRole('listitem').filter({ hasText: 'İnsan incelemesinde' });
  await waitVisible(reviewStep.getByText('Şimdi'), 'candidate sees under review');

  await reviewPanel.getByRole('button', { name: 'Mülakat planlamasına al' }).click();
  await waitVisible(reviewPanel.getByText('Mülakat planlaması bekleniyor.'), 'interview pending transition');
  await candidatePage.getByRole('button', { name: 'Durumu yenile' }).click();
  const interviewStep = candidatePage.getByRole('listitem').filter({ hasText: 'Mülakat planlaması' });
  await waitVisible(interviewStep.getByText('Şimdi'), 'candidate sees interview pending');

  const journeyPanel = candidatePage.getByRole('heading', { name: 'Başvuru yolculuğum' }).locator('xpath=..').locator('xpath=..');
  await journeyPanel.screenshot({ path: path.join(evidenceDir, 'candidate-status-mobile.png') });
  await recruiterPage.locator('header').first().screenshot({ path: path.join(evidenceDir, 'recruiter-workspace-header.png') });

  await recruiterContext.close();
  await candidateContext.close();

  const requiredChecks = [
    ['candidate', 'POST', '/api/ats/v1/jobs/urun-yoneticisi/applications', 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}`, 200],
    ['recruiter', 'GET', '/api/ats/v1/recruiter/applications', 200],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/applications/${publicRef}/status`, 200],
  ];
  for (const [persona, method, pathname, status] of requiredChecks) {
    if (!networkEvidence.some((entry) => entry.persona === persona && entry.method === method && entry.pathname === pathname && entry.status === status)) {
      throw new Error(`missing network evidence: ${persona} ${method} ${pathname} ${status}`);
    }
  }
  const serverErrors = networkEvidence
    .filter((entry) => entry.status >= 500)
    .map((entry) => ({
      ...entry,
      pathname: entry.pathname.replace(publicRef, '[APPLICATION_REF]'),
    }));
  if (serverErrors.length > 0) {
    throw new Error(`allowlisted ATS network path returned 5xx: ${JSON.stringify(serverErrors)}`);
  }

  const summary = {
    schemaVersion: 'fullats-live-browser-acceptance/v1',
    environment: 'testai.acik.com',
    syntheticOnly: true,
    frontendSourceCommit: buildInfo.sha,
    candidateViewport: '390x844',
    recruiterViewport: '1440x1000',
    journey: [
      'public-jobs-visible',
      'editable-candidate-form',
      'explicit-preview-and-confirmation',
      'persistent-receipt-created',
      'candidate-sees-submitted',
      'real-keycloak-recruiter-login',
      'authorized-recruiter-inbox',
      'human-controlled-under-review-transition',
      'candidate-sees-under-review',
      'human-controlled-interview-pending-transition',
      'candidate-sees-interview-pending',
    ],
    publicRefSha256: sha256(publicRef),
    accessibility: 'axe-wcag2a-wcag2aa-wcag21a-wcag21aa-zero-violations',
    horizontalOverflow: 'none',
    candidateTracking: 'sessionStorage-only; no URL/localStorage token',
    networkEvidence: networkEvidence.map((entry) => ({
      ...entry,
      pathname: entry.pathname.replace(publicRef, '[APPLICATION_REF]'),
    })),
    containsRawCandidateAccessToken: false,
    containsRawPasswordOrJwt: false,
    result: 'PASS',
  };
  const summaryBytes = `${JSON.stringify(summary, null, 2)}\n`;
  fs.writeFileSync(path.join(evidenceDir, 'summary.json'), summaryBytes, { mode: 0o644 });
  fs.writeFileSync(path.join(evidenceDir, 'SHA256SUMS'), `${sha256(summaryBytes)}  summary.json\n`, { mode: 0o644 });
} finally {
  await browser.close();
}
})().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`FULLATS_BROWSER_FAIL ${message}`);
  process.exitCode = 1;
});
