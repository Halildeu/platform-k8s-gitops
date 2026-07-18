'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const { compactAxeViolations } = require('./fullats-axe-evidence.cjs');

const baseURL = process.env.BASE_URL;
const recruiterUsername = process.env.RECRUITER_USERNAME;
const recruiterPasswordFile = process.env.RECRUITER_PASSWORD_FILE;
const evidenceDir = process.env.EVIDENCE_DIR;
const expectedFrontendSha = process.env.EXPECTED_FRONTEND_SHA;
const expectedAtsDigest = process.env.EXPECTED_ATS_DIGEST;
const expectedPermissionDigest = process.env.EXPECTED_PERMISSION_DIGEST;
const expectedFrontendDigest = process.env.EXPECTED_FRONTEND_DIGEST;

if (baseURL !== 'https://testai.acik.com') throw new Error('test-only base URL required');
if (!recruiterUsername || !recruiterPasswordFile || !evidenceDir || !expectedFrontendSha) {
  throw new Error('missing browser acceptance configuration');
}
if (!/^[a-f0-9]{40}$/u.test(expectedFrontendSha)) {
  throw new Error('expected frontend source commit is invalid');
}
for (const digest of [expectedAtsDigest, expectedPermissionDigest, expectedFrontendDigest]) {
  if (!/^sha256:[a-f0-9]{64}$/u.test(digest ?? '')) {
    throw new Error('expected immutable runtime digest is invalid');
  }
}

fs.mkdirSync(evidenceDir, { recursive: true });
const recruiterPassword = fs.readFileSync(recruiterPasswordFile, 'utf8').trim();
if (recruiterPassword.length < 12) throw new Error('recruiter credential invalid');

const runSuffix = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}`;
const candidateName = `Sentetik ATS Adayı ${runSuffix}`;
const candidateEmail = `fullats-${runSuffix}@example.test`;
const jobTitle = `Sentetik Ürün Uzmanı ${runSuffix}`;
const jobSlug = `sentetik-urun-uzmani-${Date.now()}`;
const editedJobSummary =
  'Müşteri ihtiyaçlarını çalışan ürün yolculuklarına dönüştüren sentetik ürün uzmanı arıyoruz. Bu özet İK düzenleme adımında güncellendi.';
const networkEvidence = [];
const allowedEvidencePaths = [
  '/api/ats/v1/jobs',
  '/api/ats/v1/careers/',
  '/api/ats/v1/candidate/applications',
  '/api/ats/v1/recruiter/applications',
  '/api/ats/v1/recruiter/jobs',
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
    const compact = compactAxeViolations(result.violations);
    throw new Error(`${surface}: axe violations ${JSON.stringify(compact)}`);
  }
};

const waitVisible = async (locator, label, timeout = 60_000) => {
  await locator.waitFor({ state: 'visible', timeout }).catch((error) => {
    throw new Error(`${label} visible degil: ${error.message}`);
  });
};

const refreshUntilVisible = async (refreshButton, target, label, attempts = 3) => {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    await refreshButton.click();
    try {
      await waitVisible(target, label, 10_000);
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`${label} ${attempts} yenileme denemesinden sonra gorunmedi: ${lastError?.message ?? 'bilinmeyen hata'}`);
};

const assertNewApplicationRejected = async (page, applicationPath, state) => {
  const result = await page.evaluate(
    async ({ targetPath, suffix }) => {
      const randomBase64Url = (byteLength) => {
        const bytes = crypto.getRandomValues(new Uint8Array(byteLength));
        const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
        return btoa(binary).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/u, '');
      };
      const now = new Date().toISOString();
      const response = await fetch(targetPath, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-ATS-Idempotency-Key': `acceptance-${crypto.randomUUID()}`,
          'X-ATS-Candidate-Access': randomBase64Url(32),
        },
        body: JSON.stringify({
          fullName: `Reddedilen Sentetik Aday ${suffix}`,
          email: `rejected-${suffix}@example.test`,
          phone: '+90 555 000 00 01',
          city: 'İstanbul',
          linkedIn: 'https://www.linkedin.com/in/rejected-synthetic',
          portfolio: 'https://portfolio.example.test/rejected',
          summary: 'Duraklatılmış veya kapatılmış ilana sentetik başvuru denemesi.',
          experience: 'Sentetik deneyim kaydı',
          education: 'Sentetik eğitim kaydı',
          skills: ['Ürün keşfi', 'Erişilebilirlik'],
          note: 'Fail-closed kabul probu',
          noticeVersion: 'kvkk-application-v1',
          noticeAcceptedAt: now,
          accuracyConfirmedAt: now,
        }),
      });
      const body = await response.clone().json().catch(() => null);
      return {
        status: response.status,
        error: typeof body?.error === 'string' ? body.error : '',
      };
    },
    { targetPath: applicationPath, suffix: `${state.toLowerCase()}-${Date.now()}` },
  );
  if (result.status !== 404 || result.error !== 'NOT_FOUND') {
    throw new Error(`${state} job fail-closed contract mismatch: HTTP ${result.status} error=${result.error}`);
  }
};

void (async () => {
const buildInfo = await fetch(`${baseURL}/build-info.json`).then(async (response) => {
  if (!response.ok) throw new Error(`build-info HTTP ${response.status}`);
  return response.json();
});
if (buildInfo.sha !== expectedFrontendSha) {
  throw new Error('live frontend sha does not match the reviewed source commit');
}

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
let publicRef = '';
let jobId = '';
let publicHandle = '';
try {
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
    await waitVisible(corporateButton, 'corporate login button', 30_000);
    await corporateButton.click();
    await recruiterPage.waitForURL(/\/realms\/platform-test\//u, { timeout: 30_000 });
    await recruiterPage.locator('#username').fill(recruiterUsername);
    await recruiterPage.locator('#password').fill(recruiterPassword);
    await recruiterPage.locator('#kc-login').click();
  }
  await waitVisible(workspace, 'recruiter workspace', 60_000);
  if (recruiterPage.url().includes('/unauthorized')) throw new Error('recruiter ATS grant denied');

  const jobsPanel = recruiterPage.getByTestId('recruiter-jobs-panel');
  await waitVisible(jobsPanel, 'recruiter jobs panel');
  await jobsPanel.getByRole('button', { name: 'Yeni ilan oluştur' }).click();
  const createForm = jobsPanel.getByRole('form', { name: 'Yeni ilan' });
  await waitVisible(createForm, 'new job form');
  await createForm.getByLabel('İlan başlığı').fill(jobTitle);
  await createForm.getByLabel('URL kısa adı').fill(jobSlug);
  await createForm.getByLabel('Ekip').fill('Ürün');
  await createForm.getByLabel('Konum').fill('İstanbul');
  await createForm.getByLabel('Çalışma modeli').fill('Hibrit');
  await createForm.getByLabel('İstihdam türü').fill('Tam zamanlı');
  await createForm
    .getByLabel('İlan özeti')
    .fill('Sentetik adayların uçtan uca test edebileceği müşteri odaklı ürün rolü.');
  await createForm.getByLabel('Öne çıkanlar').fill('Müşteri keşfi\nUçtan uca teslimat');
  const createJobResponse = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === '/api/ats/v1/recruiter/jobs' &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await createForm.getByRole('button', { name: 'Taslak oluştur' }).click();
  const createdResponse = await createJobResponse;
  if (createdResponse.status() !== 201) throw new Error(`job create HTTP ${createdResponse.status()}`);
  const createdJob = await createdResponse.json();
  jobId = typeof createdJob.jobId === 'string' ? createdJob.jobId : '';
  if (!/^job_[A-Za-z0-9_-]{16,}$/u.test(jobId) || createdJob.slug !== jobSlug || createdJob.status !== 'DRAFT') {
    throw new Error('created job response contract invalid');
  }

  const jobCard = jobsPanel.locator('li').filter({ hasText: jobTitle });
  await waitVisible(jobCard, 'created job card');
  await jobCard.getByRole('button', { name: 'Düzenle' }).click();
  const editForm = jobsPanel.getByRole('form', { name: 'İlanı düzenle' });
  await waitVisible(editForm, 'edit job form');
  await editForm.getByLabel('İlan özeti').fill(editedJobSummary);
  const updateJobResponse = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === `/api/ats/v1/recruiter/jobs/${jobId}` &&
      response.request().method() === 'PUT',
    { timeout: 30_000 },
  );
  await editForm.getByRole('button', { name: 'Değişiklikleri kaydet' }).click();
  const updatedResponse = await updateJobResponse;
  if (updatedResponse.status() !== 200) throw new Error(`job update HTTP ${updatedResponse.status()}`);
  const updatedJob = await updatedResponse.json();
  if (updatedJob.summary !== editedJobSummary || updatedJob.version !== 1) {
    throw new Error('updated job response contract invalid');
  }

  await jobCard.getByRole('button', { name: 'Önizle' }).click();
  const jobPreview = recruiterPage.getByTestId('recruiter-job-preview');
  await waitVisible(jobPreview, 'job preview');
  await waitVisible(jobPreview.getByRole('heading', { name: jobTitle }), 'job preview title');
  await assertAxeClean(recruiterPage, 'recruiter-job-preview-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-job-preview-desktop');
  await jobPreview.getByRole('button', { name: 'Önizlemeyi kapat' }).click();
  await jobPreview.waitFor({ state: 'hidden', timeout: 10_000 });

  const publishResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === `/api/ats/v1/recruiter/jobs/${jobId}/transitions` &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await jobCard.getByRole('button', { name: 'Yayınla' }).click();
  const publishResponse = await publishResponsePromise;
  if (publishResponse.status() !== 200) throw new Error(`job publish HTTP ${publishResponse.status()}`);
  const publishedJob = await publishResponse.json();
  publicHandle = typeof publishedJob.publicHandle === 'string' ? publishedJob.publicHandle : '';
  if (!/^[a-z0-9]+(?:-[a-z0-9]+){0,7}$/u.test(publicHandle) || publishedJob.status !== 'PUBLISHED') {
    throw new Error('published job response contract invalid');
  }
  await waitVisible(jobCard.getByText('Yayında', { exact: true }), 'published job state');
  await waitVisible(jobCard.getByRole('link', { name: 'Public ilanı aç' }), 'public job link');

  const candidateContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
  });
  const candidatePage = await candidateContext.newPage();
  attachNetworkEvidence(candidatePage, 'candidate');

  const publicJobPath = `/careers/${publicHandle}/jobs/${jobSlug}`;
  const publicApplicationApiPath = `/api/ats/v1/careers/${publicHandle}/jobs/${jobSlug}/applications`;
  await candidatePage.goto(`${baseURL}${publicJobPath}`, { waitUntil: 'domcontentloaded' });
  await waitVisible(candidatePage.getByTestId('public-job-detail-page'), 'public job detail');
  await waitVisible(candidatePage.getByRole('heading', { name: jobTitle }), 'published job title');
  await assertAxeClean(candidatePage, 'public-job-detail-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'public-job-detail-mobile');
  await candidatePage.getByRole('link', { name: 'Başvuru formuna geç' }).click();
  await waitVisible(candidatePage.getByTestId('candidate-application-page'), 'candidate application page');
  await waitVisible(candidatePage.getByRole('heading', { name: jobTitle }), 'job title');
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
      relevantPath(response.url()) === publicApplicationApiPath &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await candidatePage.getByTestId('create-application-receipt').click();
  const submitted = await submitResponse;
  if (submitted.status() !== 201) throw new Error(`candidate submit HTTP ${submitted.status()}`);
  await waitVisible(candidatePage.getByTestId('candidate-application-receipt'), 'persistent receipt');
  publicRef = (await candidatePage.getByTestId('candidate-receipt-id').textContent())?.trim() ?? '';
  if (!/^app_[A-Za-z0-9_-]{24}$/u.test(publicRef)) throw new Error('persistent receipt ref invalid');
  const sessionShape = await candidatePage.evaluate(async () => {
    const raw = sessionStorage.getItem('ats.candidate.latest.v1');
    const parsed = raw ? JSON.parse(raw) : null;
    const token = typeof parsed?.candidateAccessToken === 'string' ? parsed.candidateAccessToken : '';
    const tokenDigest = token
      ? Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token))))
          .map((byte) => byte.toString(16).padStart(2, '0'))
          .join('')
      : '';
    const localStorageContainsToken = token
      ? Object.values(localStorage).some((value) => value.includes(token))
      : false;
    const documentCookieContainsToken = token ? document.cookie.includes(token) : false;

    let cacheContainsToken = false;
    if (token && 'caches' in globalThis) {
      for (const cacheName of await caches.keys()) {
        const cache = await caches.open(cacheName);
        for (const request of await cache.keys()) {
          const response = await cache.match(request);
          const text = await response?.clone().text().catch(() => '');
          if (text?.includes(token)) cacheContainsToken = true;
        }
      }
    }

    let indexedDbContainsToken = false;
    const valueContainsToken = (value, seen = new WeakSet()) => {
      if (typeof value === 'string') return token ? value.includes(token) : false;
      if (!value || typeof value !== 'object') return false;
      if (seen.has(value)) return false;
      seen.add(value);
      return Object.values(value).some((child) => valueContainsToken(child, seen));
    };
    const databaseNames = typeof indexedDB.databases === 'function'
      ? (await indexedDB.databases()).map((database) => database.name).filter(Boolean)
      : [];
    for (const databaseName of databaseNames) {
      const database = await new Promise((resolve, reject) => {
        const request = indexedDB.open(databaseName);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      try {
        for (const storeName of Array.from(database.objectStoreNames)) {
          const values = await new Promise((resolve, reject) => {
            const transaction = database.transaction(storeName, 'readonly');
            const request = transaction.objectStore(storeName).getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          if (values.some((value) => valueContainsToken(value))) {
            indexedDbContainsToken = true;
          }
        }
      } finally {
        database.close();
      }
    }
    return {
      hasRef: typeof parsed?.publicRef === 'string',
      hasToken: token.length > 0,
      tokenSha256: tokenDigest,
      localStorageToken: localStorage.getItem('ats.candidate.latest.v1'),
      localStorageContainsToken,
      documentCookieContainsToken,
      cacheContainsToken,
      indexedDbContainsToken,
      urlContainsToken: token ? location.href.includes(token) : false,
      url: location.href,
    };
  });
  const contextCookieContainsToken = (await candidateContext.cookies()).some(
    (cookie) => sha256(cookie.value) === sessionShape.tokenSha256,
  );
  if (
    !sessionShape.hasRef ||
    !sessionShape.hasToken ||
    sessionShape.localStorageToken !== null ||
    sessionShape.localStorageContainsToken ||
    sessionShape.documentCookieContainsToken ||
    sessionShape.cacheContainsToken ||
    sessionShape.indexedDbContainsToken ||
    sessionShape.urlContainsToken ||
    contextCookieContainsToken
  ) {
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

  const refreshInboxResponse = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === '/api/ats/v1/recruiter/applications' &&
      response.request().method() === 'GET',
    { timeout: 30_000 },
  );
  await recruiterPage.getByRole('button', { name: 'Başvuru kutusunu yenile' }).click();
  if ((await refreshInboxResponse).status() !== 200) {
    throw new Error('recruiter inbox refresh failed');
  }
  await recruiterPage.locator('#recruiter-search').fill(candidateEmail);
  const candidateEmailText = recruiterPage.getByText(candidateEmail, { exact: true });
  await waitVisible(candidateEmailText, 'recruiter candidate card', 30_000);
  const applicationCard = candidateEmailText.locator('xpath=ancestor::article');
  await applicationCard.getByRole('button', { name: 'Başvuruyu incele' }).click();
  const reviewPanel = recruiterPage.getByTestId('recruiter-review-panel');
  await waitVisible(reviewPanel.getByText(publicRef, { exact: true }), 'recruiter review details');
  await assertAxeClean(recruiterPage, 'recruiter-workspace-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-workspace-desktop');

  await reviewPanel.getByRole('button', { name: 'İnsan incelemesini başlat' }).click();
  await waitVisible(reviewPanel.getByRole('button', { name: 'Mülakat planlamasına al' }), 'under review transition');
  const refreshStatusButton = candidatePage.getByRole('button', { name: 'Durumu yenile' });
  const reviewStep = candidatePage.getByRole('listitem').filter({ hasText: 'İnsan incelemesinde' });
  await refreshUntilVisible(refreshStatusButton, reviewStep.getByText('Şimdi'), 'candidate sees under review');

  const terminalTransitionResponse = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      relevantPath(response.url()) === `/api/ats/v1/recruiter/applications/${publicRef}/status`,
    { timeout: 30_000 },
  );
  await reviewPanel.getByRole('button', { name: 'Mülakat planlamasına al' }).click();
  const terminalResponse = await terminalTransitionResponse;
  if (terminalResponse.status() !== 200) {
    throw new Error(`interview pending transition HTTP ${terminalResponse.status()}`);
  }
  const terminalStatus = reviewPanel.getByRole('status');
  await waitVisible(terminalStatus, 'interview pending terminal status');
  if ((await terminalStatus.textContent())?.trim() !== 'Mülakat planlaması bekleniyor.') {
    throw new Error('interview pending terminal status text mismatch');
  }
  await assertAxeClean(recruiterPage, 'recruiter-workspace-terminal-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-workspace-terminal-desktop');
  const interviewStep = candidatePage.getByRole('listitem').filter({ hasText: 'Mülakat planlaması' });
  await refreshUntilVisible(refreshStatusButton, interviewStep.getByText('Şimdi'), 'candidate sees interview pending');

  const negativeProbeContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
  });
  const publicStatePage = await negativeProbeContext.newPage();
  attachNetworkEvidence(publicStatePage, 'negative-probe');
  const pauseResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === `/api/ats/v1/recruiter/jobs/${jobId}/transitions` &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await jobCard.getByRole('button', { name: 'Duraklat' }).click();
  const pauseResponse = await pauseResponsePromise;
  if (pauseResponse.status() !== 200 || (await pauseResponse.json()).status !== 'PAUSED') {
    throw new Error(`job pause contract failed: HTTP ${pauseResponse.status()}`);
  }
  await waitVisible(jobCard.getByText('Duraklatıldı', { exact: true }), 'paused job state');
  await publicStatePage.goto(`${baseURL}${publicJobPath}`, { waitUntil: 'domcontentloaded' });
  await waitVisible(publicStatePage.getByRole('alert'), 'paused public job unavailable');
  await assertNewApplicationRejected(publicStatePage, publicApplicationApiPath, 'PAUSED');
  await refreshUntilVisible(
    refreshStatusButton,
    interviewStep.getByText('Şimdi'),
    'existing candidate receipt survives pause',
  );

  const republishResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === `/api/ats/v1/recruiter/jobs/${jobId}/transitions` &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await jobCard.getByRole('button', { name: 'Yayınla' }).click();
  const republishResponse = await republishResponsePromise;
  if (republishResponse.status() !== 200 || (await republishResponse.json()).status !== 'PUBLISHED') {
    throw new Error(`job republish contract failed: HTTP ${republishResponse.status()}`);
  }
  await waitVisible(jobCard.getByText('Yayında', { exact: true }), 'republished job state');
  await publicStatePage.goto(`${baseURL}${publicJobPath}`, { waitUntil: 'domcontentloaded' });
  await waitVisible(publicStatePage.getByRole('heading', { name: jobTitle }), 'republished public job');

  const closeResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      relevantPath(response.url()) === `/api/ats/v1/recruiter/jobs/${jobId}/transitions` &&
      response.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await jobCard.getByRole('button', { name: 'İlanı kapat' }).click();
  const closeResponse = await closeResponsePromise;
  if (closeResponse.status() !== 200 || (await closeResponse.json()).status !== 'CLOSED') {
    throw new Error(`job close contract failed: HTTP ${closeResponse.status()}`);
  }
  await waitVisible(jobCard.getByText('Kapandı', { exact: true }), 'closed job state');
  await publicStatePage.goto(`${baseURL}${publicJobPath}`, { waitUntil: 'domcontentloaded' });
  await waitVisible(publicStatePage.getByRole('alert'), 'closed public job unavailable');
  await assertNewApplicationRejected(publicStatePage, publicApplicationApiPath, 'CLOSED');
  await refreshUntilVisible(
    refreshStatusButton,
    interviewStep.getByText('Şimdi'),
    'existing candidate receipt survives close',
  );
  await assertAxeClean(candidatePage, 'candidate-portal-after-job-close-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-portal-after-job-close-mobile');

  const journeyPanel = candidatePage.getByRole('heading', { name: 'Başvuru yolculuğum' }).locator('xpath=..').locator('xpath=..');
  await journeyPanel.screenshot({ path: path.join(evidenceDir, 'candidate-status-mobile.png') });
  await jobCard.screenshot({ path: path.join(evidenceDir, 'recruiter-closed-job-card.png') });

  await publicStatePage.close();
  await negativeProbeContext.close();
  await recruiterContext.close();
  await candidateContext.close();

  const requiredChecks = [
    ['recruiter', 'GET', '/api/ats/v1/recruiter/jobs', 200],
    ['recruiter', 'POST', '/api/ats/v1/recruiter/jobs', 201],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/jobs/${jobId}`, 200],
    ['candidate', 'GET', `/api/ats/v1/careers/${publicHandle}/jobs/${jobSlug}`, 200],
    ['candidate', 'POST', publicApplicationApiPath, 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}`, 200],
    ['recruiter', 'GET', '/api/ats/v1/recruiter/applications', 200],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/applications/${publicRef}/status`, 200],
  ];
  for (const [persona, method, pathname, status] of requiredChecks) {
    if (!networkEvidence.some((entry) => entry.persona === persona && entry.method === method && entry.pathname === pathname && entry.status === status)) {
      throw new Error(`missing network evidence: ${persona} ${method} ${pathname} ${status}`);
    }
  }
  const jobTransitions = networkEvidence.filter(
    (entry) =>
      entry.persona === 'recruiter' &&
      entry.method === 'POST' &&
      entry.pathname === `/api/ats/v1/recruiter/jobs/${jobId}/transitions` &&
      entry.status === 200,
  );
  if (jobTransitions.length !== 4) {
    throw new Error(`expected 4 successful job transitions, got ${jobTransitions.length}`);
  }
  const rejectedApplications = networkEvidence.filter(
    (entry) =>
      entry.persona === 'negative-probe' &&
      entry.method === 'POST' &&
      entry.pathname === publicApplicationApiPath &&
      entry.status === 404,
  );
  if (rejectedApplications.length !== 2) {
    throw new Error(`expected 2 fail-closed application rejections, got ${rejectedApplications.length}`);
  }
  const redactPath = (pathname) => {
    let redacted = pathname;
    for (const [value, marker] of [
      [publicRef, '[APPLICATION_REF]'],
      [jobId, '[JOB_ID]'],
      [publicHandle, '[PUBLIC_HANDLE]'],
      [jobSlug, '[JOB_SLUG]'],
    ]) {
      if (value) redacted = redacted.replaceAll(value, marker);
    }
    return redacted;
  };
  const serverErrors = networkEvidence
    .filter((entry) => entry.status >= 500)
    .map((entry) => ({
      ...entry,
      pathname: redactPath(entry.pathname),
    }));
  if (serverErrors.length > 0) {
    throw new Error(`allowlisted ATS network path returned 5xx: ${JSON.stringify(serverErrors)}`);
  }

  const summary = {
    schemaVersion: 'fullats-live-browser-acceptance/v2',
    environment: 'testai.acik.com',
    syntheticOnly: true,
    frontendSourceCommit: buildInfo.sha,
    artifactBinding: {
      atsRuntimeDigest: expectedAtsDigest,
      permissionRuntimeDigest: expectedPermissionDigest,
      frontendRuntimeDigest: expectedFrontendDigest,
      runtimeAuthority: 'live deployment desired image plus ready pod imageID exact digest',
      sourceLineageBoundary:
        'source refs and build runs are recorded workflow metadata; no signed provenance attestation is claimed',
    },
    candidateViewport: '390x844',
    recruiterViewport: '1440x1000',
    journey: [
      'real-keycloak-recruiter-login',
      'authorized-recruiter-job-management',
      'recruiter-creates-persistent-draft',
      'recruiter-edits-draft',
      'recruiter-previews-draft',
      'recruiter-publishes-job',
      'candidate-opens-dynamic-public-job',
      'editable-candidate-form',
      'explicit-preview-and-confirmation',
      'persistent-receipt-created',
      'candidate-sees-submitted',
      'authorized-recruiter-inbox',
      'human-controlled-under-review-transition',
      'candidate-sees-under-review',
      'human-controlled-interview-pending-transition',
      'candidate-sees-interview-pending',
      'recruiter-pauses-job',
      'paused-job-rejects-new-application',
      'existing-candidate-result-survives-pause',
      'recruiter-republishes-job',
      'recruiter-closes-job',
      'closed-job-rejects-new-application',
      'existing-candidate-result-survives-close',
    ],
    publicRefSha256: sha256(publicRef),
    jobIdSha256: sha256(jobId),
    jobSlugSha256: sha256(jobSlug),
    publicHandleSha256: sha256(publicHandle),
    finalJobState: 'CLOSED',
    accessibility: 'axe-wcag2a-wcag2aa-wcag21a-wcag21aa-zero-violations',
    horizontalOverflow: 'none',
    candidateTracking: 'sessionStorage-only; no URL/localStorage token',
    capturedNetworkFields: ['persona', 'method', 'pathname', 'status'],
    evidenceBoundary:
      'network evidence excludes headers and bodies; screenshots contain synthetic product state only',
    networkEvidence: networkEvidence.map((entry) => ({
      ...entry,
      pathname: redactPath(entry.pathname),
    })),
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
