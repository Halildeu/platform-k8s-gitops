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
const candidateName = `Sentetik ATS Adayi ${runSuffix}`;
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
  '/api/ats/v1/candidate/resume-imports',
  '/api/ats/v1/interviews',
  '/api/ats/v1/recruiter/applications',
  '/api/ats/v1/recruiter/jobs',
  '/api/v1/authz/me',
];

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const buildSyntheticResumePdf = ({ fullName, email }) => {
  if (/[^\x20-\x7e]/u.test(`${fullName}${email}`)) {
    throw new Error('synthetic PDF identity must be ASCII-safe');
  }
  const lines = [
    `Ad Soyad: ${fullName}`,
    `E-posta: ${email}`,
    'Telefon: +90 555 000 00 00',
    'Sehir: Istanbul',
    'LinkedIn: https://www.linkedin.com/in/fullats-synthetic',
    'Portfoy: https://portfolio.example.test/fullats-synthetic',
    'Profesyonel Ozet',
    'Musteri ihtiyacini calisan urun yolculuguna donusturen sentetik aday.',
    'Is Deneyimi',
    'Urun Uzmani - Ornek Teknoloji - 2022-2026',
    'Egitim',
    'Yonetim Bilisim Sistemleri - Ornek Universitesi - 2020',
    'Beceriler',
    'Urun kesfi, kullanici arastirmasi, analitik',
    'Not',
    'Urun odakli ekibinizle calismak istiyorum.',
  ];
  const escape = (value) => value.replace(/([\\()])/gu, '\\$1');
  const stream = `BT\n/F1 10 Tf\n48 760 Td\n14 TL\n${lines
    .map((line) => `(${escape(line)}) Tj T*`)
    .join('\n')}\nET`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream, 'ascii')} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(Buffer.byteLength(pdf, 'ascii'));
    pdf += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf, 'ascii');
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`)
    .join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf, 'ascii');
};

const fetchBuildInfo = async (phase) => {
  const url = `${baseURL}/build-info.json?fullats_run=${encodeURIComponent(runSuffix)}&phase=${encodeURIComponent(phase)}`;
  const response = await fetch(url, {
    cache: 'no-store',
    headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
  });
  if (!response.ok) throw new Error(`build-info ${phase} HTTP ${response.status}`);
  const body = await response.json();
  if (body.sha !== expectedFrontendSha) {
    throw new Error(`live frontend sha does not match reviewed source commit at ${phase}`);
  }
  return body;
};
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

const waitEnabled = async (locator, label, timeout = 60_000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await locator.isEnabled().catch(() => false)) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`${label} ${timeout}ms icinde etkinlesmedi`);
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
const buildInfo = await fetchBuildInfo('pre');

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
let publicRef = '';
let jobId = '';
let publicHandle = '';
let interviewId = '';
let offerId = '';
let resumeImportId = '';
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
  await waitVisible(
    jobPreview.getByText(editedJobSummary, { exact: true }),
    'job preview edited summary',
  );
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
  await waitVisible(
    candidatePage.getByText(editedJobSummary, { exact: true }),
    'published edited job summary',
  );
  await assertAxeClean(candidatePage, 'public-job-detail-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'public-job-detail-mobile');
  await candidatePage.getByRole('link', { name: 'Başvuru formuna geç' }).click();
  await waitVisible(candidatePage.getByTestId('candidate-application-page'), 'candidate application page');
  await waitVisible(candidatePage.getByRole('heading', { name: jobTitle }), 'job title');
  await candidatePage.getByLabel(/CV içe aktarma aydınlatmasını okudum/u).check();
  const resumeCreateResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/careers/${publicHandle}/jobs/${jobSlug}/resume-imports`,
    { timeout: 30_000 },
  );
  const resumeUploadResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      /^\/api\/ats\/v1\/candidate\/resume-imports\/ri_[A-Za-z0-9_-]{24}\/document$/u.test(
        relevantPath(response.url()) ?? '',
      ),
    { timeout: 30_000 },
  );
  await candidatePage.getByTestId('candidate-resume').setInputFiles({
    name: 'fullats-synthetic-resume.pdf',
    mimeType: 'application/pdf',
    buffer: buildSyntheticResumePdf({ fullName: candidateName, email: candidateEmail }),
  });
  const resumeCreateResponse = await resumeCreateResponsePromise;
  if (resumeCreateResponse.status() !== 201) {
    throw new Error(`candidate resume import create HTTP ${resumeCreateResponse.status()}`);
  }
  const createdResumeImport = await resumeCreateResponse.json();
  resumeImportId = typeof createdResumeImport.importId === 'string' ? createdResumeImport.importId : '';
  if (!/^ri_[A-Za-z0-9_-]{24}$/u.test(resumeImportId)) {
    throw new Error('candidate resume import id invalid');
  }
  const resumeUploadResponse = await resumeUploadResponsePromise;
  if (![201, 202].includes(resumeUploadResponse.status())) {
    throw new Error(`candidate resume upload HTTP ${resumeUploadResponse.status()}`);
  }

  const resumeReview = candidatePage.getByTestId('candidate-resume-review');
  await waitVisible(resumeReview, 'candidate resume proposal review');
  if ((await candidatePage.getByTestId('candidate-email').inputValue()) !== '') {
    throw new Error('unreviewed PDF proposal escaped into authoritative form');
  }
  await waitVisible(
    resumeReview.getByText(/Sayfa 1 · güven %\d+ · metin konumu doğrulandı/u).first(),
    'candidate resume proposal provenance',
  );

  const editedCandidateName = `${candidateName} Düzenlendi`;
  const fullNameProposal = candidatePage.getByTestId('resume-proposal-fullName');
  await fullNameProposal.getByLabel('Aday tarafından düzenlenebilir değer').fill(editedCandidateName);
  const fullNameEditResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/candidate/resume-imports/${resumeImportId}/fields/fullName`,
    { timeout: 30_000 },
  );
  await fullNameProposal.getByRole('button', { name: 'Düzenlediğimi kaydet' }).click();
  if ((await fullNameEditResponsePromise).status() !== 200) {
    throw new Error('candidate resume full-name edit was not persisted');
  }
  await waitVisible(fullNameProposal.getByText('Düzenlendi', { exact: true }), 'edited resume field state');

  const cityProposal = candidatePage.getByTestId('resume-proposal-city');
  const cityRejectResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/candidate/resume-imports/${resumeImportId}/fields/city`,
    { timeout: 30_000 },
  );
  await cityProposal.getByRole('button', { name: 'Reddet' }).click();
  if ((await cityRejectResponsePromise).status() !== 200) {
    throw new Error('candidate resume city rejection was not persisted');
  }
  await waitVisible(cityProposal.getByText('Reddedildi', { exact: true }), 'rejected resume field state');

  await resumeReview.getByRole('button', { name: 'Güvenli önerileri kabul et' }).click();
  const applySelectedButton = resumeReview.getByRole('button', {
    name: /Seçtiğim alanları forma aktar \(\d+\)/u,
  });
  await waitEnabled(applySelectedButton, 'reviewed resume confirmation');
  const resumeConfirmResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/candidate/resume-imports/${resumeImportId}/confirm`,
    { timeout: 30_000 },
  );
  await applySelectedButton.click();
  const resumeConfirmResponse = await resumeConfirmResponsePromise;
  if (resumeConfirmResponse.status() !== 200) {
    throw new Error(`candidate resume confirm HTTP ${resumeConfirmResponse.status()}`);
  }
  const confirmedResume = await resumeConfirmResponse.json();
  if (
    confirmedResume?.resumeImport?.state !== 'CONFIRMED' ||
    confirmedResume?.draft?.importId !== resumeImportId ||
    !Number.isInteger(confirmedResume?.draft?.version)
  ) {
    throw new Error('candidate resume confirmation binding invalid');
  }
  const resumeMeta = candidatePage.getByTestId('candidate-resume-meta');
  await waitVisible(resumeMeta, 'candidate confirmed resume draft');
  if (!/CV kararları kaydedildi; \d+ alan forma aktarıldı/u.test((await resumeMeta.textContent()) ?? '')) {
    throw new Error('candidate confirmed resume draft did not populate the form');
  }
  if ((await candidatePage.getByTestId('candidate-email').inputValue()) !== candidateEmail) {
    throw new Error('candidate accepted PDF email proposal mismatch');
  }
  if ((await candidatePage.getByTestId('candidate-fullName').inputValue()) !== editedCandidateName) {
    throw new Error('candidate edited PDF full-name proposal mismatch');
  }
  if ((await candidatePage.getByTestId('candidate-city').inputValue()) !== '') {
    throw new Error('candidate rejected PDF city proposal escaped into form');
  }
  await candidatePage.getByTestId('candidate-city').fill('Istanbul');
  if ((await candidatePage.getByTestId('candidate-resume').count()) !== 0) {
    throw new Error('raw PDF input remained mounted after terminal confirmation');
  }
  if (((await resumeMeta.textContent()) ?? '').includes('fullats-synthetic-resume.pdf')) {
    throw new Error('candidate PDF filename escaped into confirmed product state');
  }
  await candidatePage.getByRole('button', { name: 'Başvuruyu önizle' }).click();
  await waitVisible(candidatePage.getByTestId('candidate-application-preview'), 'candidate preview');
  await waitVisible(
    candidatePage.getByTestId('candidate-application-preview').getByText(editedCandidateName, {
      exact: true,
    }),
    'candidate edited PDF field preview',
  );
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
  const submittedPayload = submitted.request().postDataJSON();
  const submittedKeys = Object.keys(submittedPayload ?? {}).sort();
  const expectedSubmittedKeys = [
    'accuracyConfirmedAt',
    'city',
    'education',
    'email',
    'experience',
    'fullName',
    'linkedIn',
    'note',
    'noticeAcceptedAt',
    'noticeVersion',
    'phone',
    'portfolio',
    'resumeDraftVersion',
    'resumeImportId',
    'skills',
    'summary',
  ].sort();
  if (JSON.stringify(submittedKeys) !== JSON.stringify(expectedSubmittedKeys)) {
    throw new Error(`candidate submission field boundary mismatch: ${submittedKeys.join(',')}`);
  }
  if (
    submittedPayload.fullName !== editedCandidateName ||
    submittedPayload.email !== candidateEmail ||
    submittedPayload.city !== 'Istanbul' ||
    submittedPayload.resumeImportId !== resumeImportId ||
    submittedPayload.resumeDraftVersion !== confirmedResume.draft.version
  ) {
    throw new Error('candidate edited PDF fields were not submitted');
  }
  const serializedSubmission = JSON.stringify(submittedPayload);
  if (serializedSubmission.includes('%PDF') || serializedSubmission.includes('fullats-synthetic-resume.pdf')) {
    throw new Error('raw PDF content or filename escaped the browser-local parser boundary');
  }
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

  await reviewPanel.getByRole('button', { name: 'Yapılandırılmış değerlendirme yap' }).click();
  const applicationEvaluationForm = reviewPanel.getByRole('form', {
    name: 'Yapılandırılmış insan scorecard’ı',
  });
  await waitVisible(applicationEvaluationForm, 'application human scorecard');
  const applicationRatings = await applicationEvaluationForm
    .getByLabel('Kanıt düzeyi (1–4)', { exact: true })
    .all();
  const applicationEvidenceFields = await applicationEvaluationForm
    .getByLabel('İşle ilgili somut kanıt', { exact: true })
    .all();
  if (applicationRatings.length !== 3 || applicationEvidenceFields.length !== 3) {
    throw new Error('application scorecard criterion count mismatch');
  }
  for (let index = 0; index < applicationRatings.length; index += 1) {
    await applicationRatings[index].selectOption('3');
    await applicationEvidenceFields[index].fill(
      `Sentetik işle ilgili değerlendirme kanıtı ${index + 1}: aday örnek ve doğrulanabilir sonuç sundu.`,
    );
  }
  await applicationEvaluationForm.getByLabel('İlerletme önerisi').check();
  await applicationEvaluationForm
    .getByLabel('Genel gerekçe')
    .fill('Sentetik adayın işle ilgili örnekleri yapılandırılmış insan değerlendirmesiyle incelendi.');
  await applicationEvaluationForm
    .getByLabel(/Değerlendirme yalnız ilandaki iş gereklilikleri/u)
    .check();
  const evaluationResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/recruiter/applications/${publicRef}/evaluations`,
    { timeout: 30_000 },
  );
  await applicationEvaluationForm
    .getByRole('button', { name: 'Immutable değerlendirmeyi kaydet' })
    .click();
  const evaluationResponse = await evaluationResponsePromise;
  if (evaluationResponse.status() !== 201) {
    throw new Error(`application evaluation HTTP ${evaluationResponse.status()}`);
  }
  await waitVisible(
    reviewPanel.getByText(/İnsan değerlendirmesi revizyon 1 olarak kaydedildi/u),
    'application evaluation persisted',
  );

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

  const interviewWorkspace = reviewPanel.getByTestId('recruiter-interview-workspace');
  await waitVisible(
    interviewWorkspace.getByRole('button', { name: 'Yeni görüşme planla' }),
    'new interview action',
  );
  await interviewWorkspace.getByRole('button', { name: 'Yeni görüşme planla' }).click();
  const interviewPlanForm = interviewWorkspace.getByRole('form', {
    name: 'Yeni görüşme planı',
  });
  await waitVisible(interviewPlanForm, 'interview plan form');
  const interviewCreateResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/recruiter/applications/${publicRef}/interviews`,
    { timeout: 30_000 },
  );
  await interviewPlanForm
    .getByRole('button', { name: 'Görüşmeyi kalıcı olarak planla' })
    .click();
  const interviewCreateResponse = await interviewCreateResponsePromise;
  if (interviewCreateResponse.status() !== 201) {
    throw new Error(`interview create HTTP ${interviewCreateResponse.status()}`);
  }
  const createdInterview = await interviewCreateResponse.json();
  interviewId = typeof createdInterview.interviewId === 'string' ? createdInterview.interviewId : '';
  if (!/^int_[A-Za-z0-9_-]{24}$/u.test(interviewId) || createdInterview.status !== 'SCHEDULED') {
    throw new Error('created interview response contract invalid');
  }
  await waitVisible(
    interviewWorkspace.getByText('Görüşme planlandı; adayın güvenli takvimine yansıdı.', {
      exact: true,
    }),
    'interview persisted',
  );
  await refreshUntilVisible(
    refreshStatusButton,
    candidatePage.getByRole('heading', { name: 'Ön görüşme' }),
    'candidate sees scheduled interview',
  );
  await waitVisible(
    candidatePage.getByRole('link', { name: 'Güvenli görüşme bağlantısını aç' }),
    'candidate-safe interview link',
  );

  await interviewWorkspace.getByRole('button', { name: 'İnsan scorecard’ı doldur' }).click();
  const interviewScorecardForm = interviewWorkspace.getByRole('form', {
    name: "Görüşme insan scorecard'ı",
  });
  await waitVisible(interviewScorecardForm, 'interview human scorecard');
  const interviewRatings = await interviewScorecardForm
    .getByLabel('Kanıt düzeyi (1–4)', { exact: true })
    .all();
  const interviewEvidenceFields = await interviewScorecardForm
    .getByLabel('Somut iş kanıtı', { exact: true })
    .all();
  if (interviewRatings.length !== 3 || interviewEvidenceFields.length !== 3) {
    throw new Error('interview scorecard criterion count mismatch');
  }
  for (let index = 0; index < interviewRatings.length; index += 1) {
    await interviewRatings[index].selectOption('3');
    await interviewEvidenceFields[index].fill(
      `Sentetik görüşme kanıtı ${index + 1}: aday iş örneğini, kendi katkısını ve sonucu açıkladı.`,
    );
  }
  await interviewScorecardForm.getByLabel('İnsan önerisi').selectOption('ADVANCE');
  await interviewScorecardForm
    .getByLabel('Genel gerekçe')
    .fill('Sentetik görüşmede yalnız işle ilgili rubric ve gözlemlenebilir kanıtlar değerlendirildi.');
  await interviewScorecardForm
    .getByLabel(/Değerlendirme yalnız işle ilgili rubric/u)
    .check();
  const interviewScorecardResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) === `/api/ats/v1/interviews/${interviewId}/scorecards`,
    { timeout: 30_000 },
  );
  await interviewScorecardForm
    .getByRole('button', { name: 'Immutable scorecard’ı kaydet' })
    .click();
  const interviewScorecardResponse = await interviewScorecardResponsePromise;
  if (interviewScorecardResponse.status() !== 201) {
    throw new Error(`interview scorecard HTTP ${interviewScorecardResponse.status()}`);
  }
  await waitVisible(
    interviewWorkspace.getByText(/İnsan scorecard’ı revizyon 1 olarak kaydedildi/u),
    'interview scorecard persisted',
  );

  await interviewWorkspace.getByRole('button', { name: 'Görüşmeyi tamamla' }).click();
  const interviewCompleteResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/recruiter/applications/${publicRef}/interviews/${interviewId}/transitions`,
    { timeout: 30_000 },
  );
  await interviewWorkspace.getByRole('button', { name: 'İnsan eylemini kaydet' }).click();
  const interviewCompleteResponse = await interviewCompleteResponsePromise;
  if (interviewCompleteResponse.status() !== 200) {
    throw new Error(`interview complete HTTP ${interviewCompleteResponse.status()}`);
  }
  await refreshUntilVisible(
    refreshStatusButton,
    candidatePage
      .getByRole('listitem')
      .filter({ hasText: 'Ön görüşme' })
      .getByText('Tamamlandı', { exact: true }),
    'candidate sees completed interview',
  );

  const offerWorkspace = reviewPanel.getByTestId('recruiter-offer-workspace');
  await waitVisible(
    offerWorkspace.getByRole('button', { name: 'Teklif taslağı oluştur' }),
    'new offer action',
  );
  await offerWorkspace.getByRole('button', { name: 'Teklif taslağı oluştur' }).click();
  const offerForm = offerWorkspace.getByRole('form', { name: 'Yeni teklif taslağı' });
  await waitVisible(offerForm, 'offer draft form');
  await offerForm.getByLabel('Brüt ücret').fill('125000');
  await offerForm
    .getByLabel('Teklif özeti')
    .fill('Sentetik Full ATS kabulü için açık rol, ücret dönemi ve başlangıç koşulları.');
  const offerCreateResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) === `/api/ats/v1/recruiter/applications/${publicRef}/offers`,
    { timeout: 30_000 },
  );
  await offerForm.getByRole('button', { name: 'Taslağı kalıcı kaydet' }).click();
  const offerCreateResponse = await offerCreateResponsePromise;
  if (offerCreateResponse.status() !== 201) {
    throw new Error(`offer draft HTTP ${offerCreateResponse.status()}`);
  }
  const createdOffer = await offerCreateResponse.json();
  offerId = typeof createdOffer.offerId === 'string' ? createdOffer.offerId : '';
  if (!/^off_[A-Za-z0-9_-]{24}$/u.test(offerId) || createdOffer.status !== 'DRAFT') {
    throw new Error('created offer response contract invalid');
  }
  await waitVisible(
    offerWorkspace.getByRole('button', { name: 'Adaya iletmeyi hazırla' }),
    'extend offer action',
  );
  await offerWorkspace.getByRole('button', { name: 'Adaya iletmeyi hazırla' }).click();
  const extendOfferPanel = offerWorkspace.getByRole('region', { name: 'Teklifi adaya ilet' });
  await waitVisible(extendOfferPanel, 'extend offer confirmation');
  await extendOfferPanel
    .getByLabel('İnsan kararı gerekçesi')
    .fill('Sentetik scorecard ve tamamlanmış görüşme sonrası teklif onayı.');
  await extendOfferPanel
    .getByLabel(/Koşulları, ücret dönemini ve yanıt son tarihini kontrol ettim/u)
    .check();
  const extendOfferResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/recruiter/applications/${publicRef}/offers/${offerId}/transitions`,
    { timeout: 30_000 },
  );
  await extendOfferPanel.getByRole('button', { name: 'Teklifi adaya ilet' }).click();
  const extendOfferResponse = await extendOfferResponsePromise;
  if (extendOfferResponse.status() !== 200) {
    throw new Error(`offer extend HTTP ${extendOfferResponse.status()}`);
  }

  await refreshUntilVisible(
    refreshStatusButton,
    candidatePage.getByRole('button', { name: 'Teklifi kabul etmeyi hazırla' }),
    'candidate sees extended offer',
  );
  await candidatePage.getByRole('button', { name: 'Teklifi kabul etmeyi hazırla' }).click();
  const candidateOfferPanel = candidatePage.getByRole('region', { name: 'Teklif kabul onayı' });
  await waitVisible(candidateOfferPanel, 'candidate offer acceptance confirmation');
  await candidateOfferPanel
    .getByLabel(/Koşulları ve yanıt son tarihini inceledim/u)
    .check();
  const candidateAcceptResponsePromise = candidatePage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/candidate/applications/${publicRef}/offers/${offerId}/response`,
    { timeout: 30_000 },
  );
  await candidateOfferPanel
    .getByRole('button', { name: 'Kabul yanıtını kalıcı kaydet' })
    .click();
  const candidateAcceptResponse = await candidateAcceptResponsePromise;
  if (candidateAcceptResponse.status() !== 200) {
    throw new Error(`candidate offer acceptance HTTP ${candidateAcceptResponse.status()}`);
  }
  await waitVisible(
    candidatePage.getByRole('heading', { name: 'Teklifi kabul ettiniz' }),
    'candidate accepted status',
  );

  await offerWorkspace.getByRole('button', { name: 'Teklifleri yenile' }).click();
  await waitVisible(
    offerWorkspace.getByRole('button', { name: 'İşe alım sonucunu hazırla' }),
    'hire result action',
  );
  await offerWorkspace.getByRole('button', { name: 'İşe alım sonucunu hazırla' }).click();
  const hirePanel = offerWorkspace.getByRole('region', { name: 'İşe alım sonucunu kaydet' });
  await waitVisible(hirePanel, 'hire result confirmation');
  await hirePanel
    .getByLabel('İnsan kararı gerekçesi')
    .fill('Adayın kalıcı ATS teklif kabulü doğrulandı ve sentetik işe alım sonucu kaydediliyor.');
  await hirePanel
    .getByLabel(/Adayın ATS kabul yanıtını inceledim/u)
    .check();
  const hireResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) ===
        `/api/ats/v1/recruiter/applications/${publicRef}/offers/${offerId}/transitions`,
    { timeout: 30_000 },
  );
  await hirePanel.getByRole('button', { name: 'İşe alındı olarak kaydet' }).click();
  const hireResponse = await hireResponsePromise;
  if (hireResponse.status() !== 200) {
    throw new Error(`hire result HTTP ${hireResponse.status()}`);
  }
  const hiredStep = candidatePage.getByRole('listitem').filter({
    hasText: 'İşe alım sonucu kaydedildi',
  });
  await refreshUntilVisible(refreshStatusButton, hiredStep.getByText('Şimdi'), 'candidate sees hired result');
  await waitVisible(candidatePage.getByText('İşe alındı', { exact: true }), 'candidate sees hired offer');
  await assertAxeClean(recruiterPage, 'recruiter-workspace-hired-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-workspace-hired-desktop');
  await assertAxeClean(candidatePage, 'candidate-portal-hired-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-portal-hired-mobile');

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
    hiredStep.getByText('Şimdi'),
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
    hiredStep.getByText('Şimdi'),
    'existing candidate receipt survives close',
  );
  await assertAxeClean(candidatePage, 'candidate-portal-after-job-close-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-portal-after-job-close-mobile');

  const journeyPanel = candidatePage.getByRole('heading', { name: 'Başvuru yolculuğum' }).locator('xpath=..').locator('xpath=..');
  await journeyPanel.screenshot({ path: path.join(evidenceDir, 'candidate-status-mobile.png') });
  await jobCard.screenshot({ path: path.join(evidenceDir, 'recruiter-closed-job-card.png') });

  const finalBuildInfo = await fetchBuildInfo('post');
  if (finalBuildInfo.sha !== buildInfo.sha) {
    throw new Error('frontend source changed during the live customer journey');
  }

  await publicStatePage.close();
  await negativeProbeContext.close();
  await recruiterContext.close();
  await candidateContext.close();

  const requiredChecks = [
    ['recruiter', 'GET', '/api/ats/v1/recruiter/jobs', 200],
    ['recruiter', 'POST', '/api/ats/v1/recruiter/jobs', 201],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/jobs/${jobId}`, 200],
    ['candidate', 'GET', `/api/ats/v1/careers/${publicHandle}/jobs/${jobSlug}`, 200],
    [
      'candidate',
      'POST',
      `/api/ats/v1/careers/${publicHandle}/jobs/${jobSlug}/resume-imports`,
      201,
    ],
    [
      'candidate',
      'PUT',
      `/api/ats/v1/candidate/resume-imports/${resumeImportId}/fields/fullName`,
      200,
    ],
    [
      'candidate',
      'PUT',
      `/api/ats/v1/candidate/resume-imports/${resumeImportId}/fields/city`,
      200,
    ],
    [
      'candidate',
      'POST',
      `/api/ats/v1/candidate/resume-imports/${resumeImportId}/confirm`,
      200,
    ],
    ['candidate', 'POST', publicApplicationApiPath, 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}`, 200],
    ['recruiter', 'GET', '/api/ats/v1/recruiter/applications', 200],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/applications/${publicRef}/status`, 200],
    ['recruiter', 'POST', `/api/ats/v1/recruiter/applications/${publicRef}/evaluations`, 201],
    ['recruiter', 'POST', `/api/ats/v1/recruiter/applications/${publicRef}/interviews`, 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}/interviews`, 200],
    ['recruiter', 'POST', `/api/ats/v1/interviews/${interviewId}/scorecards`, 201],
    [
      'recruiter',
      'POST',
      `/api/ats/v1/recruiter/applications/${publicRef}/interviews/${interviewId}/transitions`,
      200,
    ],
    ['recruiter', 'POST', `/api/ats/v1/recruiter/applications/${publicRef}/offers`, 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}/offers`, 200],
    [
      'candidate',
      'POST',
      `/api/ats/v1/candidate/applications/${publicRef}/offers/${offerId}/response`,
      200,
    ],
  ];
  for (const [persona, method, pathname, status] of requiredChecks) {
    if (!networkEvidence.some((entry) => entry.persona === persona && entry.method === method && entry.pathname === pathname && entry.status === status)) {
      throw new Error(`missing network evidence: ${persona} ${method} ${pathname} ${status}`);
    }
  }
  const resumeUploads = networkEvidence.filter(
    (entry) =>
      entry.persona === 'candidate' &&
      entry.method === 'PUT' &&
      entry.pathname === `/api/ats/v1/candidate/resume-imports/${resumeImportId}/document` &&
      [201, 202].includes(entry.status),
  );
  if (resumeUploads.length !== 1) {
    throw new Error(`expected one bounded PDF upload, got ${resumeUploads.length}`);
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
  const offerTransitions = networkEvidence.filter(
    (entry) =>
      entry.persona === 'recruiter' &&
      entry.method === 'POST' &&
      entry.pathname ===
        `/api/ats/v1/recruiter/applications/${publicRef}/offers/${offerId}/transitions` &&
      entry.status === 200,
  );
  if (offerTransitions.length !== 2) {
    throw new Error(`expected 2 successful offer transitions, got ${offerTransitions.length}`);
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
      [interviewId, '[INTERVIEW_ID]'],
      [offerId, '[OFFER_ID]'],
      [resumeImportId, '[RESUME_IMPORT_ID]'],
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
    schemaVersion: 'fullats-live-browser-acceptance/v4',
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
      'candidate-acknowledges-versioned-resume-import-notice',
      'candidate-uploads-real-pdf-to-bounded-ats-parser',
      'candidate-reviews-field-provenance-before-form-transfer',
      'candidate-edits-one-pdf-proposal',
      'candidate-rejects-one-pdf-proposal',
      'candidate-accepts-remaining-safe-proposals',
      'candidate-confirms-selected-fields-atomically',
      'candidate-manually-completes-rejected-required-field',
      'editable-candidate-form',
      'explicit-preview-and-confirmation',
      'persistent-receipt-created',
      'candidate-sees-submitted',
      'authorized-recruiter-inbox',
      'human-controlled-under-review-transition',
      'candidate-sees-under-review',
      'structured-human-application-evaluation',
      'human-controlled-interview-pending-transition',
      'candidate-sees-interview-pending',
      'recruiter-schedules-persistent-interview',
      'candidate-sees-safe-interview-schedule',
      'assigned-human-submits-structured-scorecard',
      'human-completes-scorecard-backed-interview',
      'candidate-sees-completed-interview',
      'recruiter-creates-persistent-offer-draft',
      'human-extends-offer-to-candidate',
      'candidate-sees-and-accepts-offer',
      'human-records-hire-result',
      'candidate-sees-hired-result',
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
    interviewIdSha256: sha256(interviewId),
    offerIdSha256: sha256(offerId),
    resumeImportIdSha256: sha256(resumeImportId),
    jobSlugSha256: sha256(jobSlug),
    publicHandleSha256: sha256(publicHandle),
    finalJobState: 'CLOSED',
    finalApplicationState: 'HIRED',
    accessibility: 'axe-wcag2a-wcag2aa-wcag21a-wcag21aa-zero-violations',
    horizontalOverflow: 'none',
    candidateTracking: 'sessionStorage-only; no URL/localStorage token',
    capturedNetworkFields: ['persona', 'method', 'pathname', 'status'],
    evidenceBoundary:
      'network evidence excludes headers and bodies; the synthetic raw PDF is transiently uploaded only to the bounded ATS parser and is absent from the final application/evidence; extracted text and filename are not retained in evidence; screenshots contain synthetic product state only',
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
