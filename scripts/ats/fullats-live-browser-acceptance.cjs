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

  await recruiterPage.getByRole('tab', { name: 'İlanlar' }).click();
  const jobsPanel = recruiterPage.getByTestId('recruiter-jobs-panel');
  await waitVisible(jobsPanel, 'recruiter jobs panel');
  await jobsPanel.getByTestId('recruiter-job-filter-ALL').click();
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
  await createForm.getByRole('button', { name: 'Soru ekle', exact: true }).click();
  await createForm.getByLabel('Soru metni', { exact: true }).nth(0).fill('Hangi teknik alanda deneyiminiz var?');
  await createForm.getByRole('button', { name: 'Soru ekle', exact: true }).click();
  await createForm.getByLabel('Soru metni', { exact: true }).nth(1).fill('Hangi calisma bicimini tercih edersiniz?');
  await createForm.getByLabel(/^Cevap biçimi/u).nth(1).selectOption('SINGLE_CHOICE');
  await createForm.getByLabel('2. soru, 1. seçenek', { exact: true }).fill('Ofis');
  await createForm.getByLabel('2. soru, 2. seçenek', { exact: true }).fill('Uzaktan');
  // #240 B: üçüncü soru YALNIZ silme kapsamı için; ilk iki soru başvuru anında yaşar.
  await createForm.getByRole('button', { name: 'Soru ekle', exact: true }).click();
  await createForm.getByLabel('Soru metni', { exact: true }).nth(2).fill('Silinecek deneme sorusu');
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
  if (createdJob.questions?.length !== 3 || !createdJob.questions.every(q => q.questionId)) throw new Error('question create persistence missing');
  const originalQuestionIds = createdJob.questions.map(q => q.questionId);
  const originalOptionIds = createdJob.questions[1].options.map(o => o.optionId);
  console.log('PASS recruiter question create and server ids');
  jobId = typeof createdJob.jobId === 'string' ? createdJob.jobId : '';
  if (!/^job_[A-Za-z0-9_-]{16,}$/u.test(jobId) || createdJob.slug !== jobSlug || createdJob.status !== 'DRAFT') {
    throw new Error('created job response contract invalid');
  }

  const jobCard = jobsPanel.locator('li').filter({ hasText: jobTitle });
  await waitVisible(jobCard, 'created job card');
  await jobCard.getByRole('button', { name: 'Düzenle' }).click();
  const editForm = jobsPanel.getByRole('form', { name: 'İlanı düzenle' });
  await waitVisible(editForm, 'edit job form');
  await editForm.getByRole('button', { name: '2. soruyu yukarı taşı', exact: true }).click();
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
  // "2. soruyu yukarı taşı": [q1, q2, q3] → [q2, q1, q3]; kimlikler sabit kalır.
  const reorderedQuestionIds = [originalQuestionIds[1], originalQuestionIds[0], originalQuestionIds[2]];
  if (JSON.stringify(updatedJob.questions.map(q => q.questionId)) !== JSON.stringify(reorderedQuestionIds) || JSON.stringify(updatedJob.questions[0].options.map(o => o.optionId)) !== JSON.stringify(originalOptionIds)) throw new Error('question reorder changed ids');
  console.log('PASS recruiter question reorder preserves ids');
  if (updatedJob.summary !== editedJobSummary || updatedJob.version !== 1) {
    throw new Error('updated job response contract invalid');
  }

  await jobCard.getByRole('button', { name: 'Düzenle' }).click();
  await waitVisible(editForm, 'reopened question form');
  if (await editForm.getByLabel('Soru metni', { exact: true }).nth(0).inputValue() !== 'Hangi calisma bicimini tercih edersiniz?') throw new Error('question reopen readback mismatch');
  // #240 B: sorular başvuru anında YAŞAMALI. Silme kapsamı 3. (deneme) soruyla korunur;
  // ilk soru (tek seçim) "Yanıtlanması zorunlu" işaretlenir — aday tarafındaki önizleme
  // kapısı ve backend'in zorunlu-cevap reddi buna dayanır.
  await editForm.getByRole('button', { name: '3. soruyu sil', exact: true }).click();
  await editForm.getByLabel('Yanıtlanması zorunlu', { exact: true }).nth(0).check();
  const removeResponsePromise = recruiterPage.waitForResponse(r => relevantPath(r.url()) === `/api/ats/v1/recruiter/jobs/${jobId}` && r.request().method() === 'PUT');
  await editForm.getByRole('button', { name: 'Değişiklikleri kaydet' }).click();
  const removeResponse = await removeResponsePromise;
  if (removeResponse.status() !== 200) throw new Error(`question deletion/required HTTP ${removeResponse.status()}`);
  const requiredJob = await removeResponse.json();
  if (requiredJob.questions?.length !== 2) throw new Error('question deletion persistence failed');
  if (JSON.stringify(requiredJob.questions.map(q => q.questionId)) !== JSON.stringify(reorderedQuestionIds.slice(0, 2))) {
    throw new Error('question deletion changed surviving ids');
  }
  if (requiredJob.questions[0].required !== true || requiredJob.questions[1].required !== false) {
    throw new Error('question required flag persistence failed');
  }
  const singleChoiceQuestionId = requiredJob.questions[0].questionId;
  const textQuestionId = requiredJob.questions[1].questionId;
  const remoteOptionId = requiredJob.questions[0].options.find((option) => option.label === 'Uzaktan')?.optionId ?? '';
  if (!/^qo_[A-Za-z0-9_-]{12}$/u.test(remoteOptionId)) throw new Error('single-choice option id missing');
  console.log('PASS recruiter question independent reopen, deletion and required flag with stable ids');
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
  const resumeImportNotice = candidatePage.locator('#resume-import-notice');
  await waitVisible(resumeImportNotice, 'candidate resume import notice');
  await resumeImportNotice.check();
  await candidatePage.getByTestId('candidate-resume').setInputFiles({
    name: 'fullats-synthetic-resume.pdf',
    mimeType: 'application/pdf',
    buffer: buildSyntheticResumePdf({ fullName: candidateName, email: candidateEmail }),
  });
  const resumeReview = candidatePage.getByTestId('candidate-resume-review');
  await waitVisible(resumeReview, 'candidate PDF proposal review');
  await resumeReview.getByRole('button', { name: 'Güvenli önerileri kabul et' }).click();
  const applyResumeButton = resumeReview.getByRole('button', {
    name: /Seçtiğim alanları forma aktar/u,
  });
  await applyResumeButton.click({ timeout: 30_000 });
  const resumeMeta = candidatePage.getByTestId('candidate-resume-meta');
  await waitVisible(resumeMeta, 'candidate PDF import result');
  const resumeMetaText = (await resumeMeta.textContent()) ?? '';
  const importedFieldCount = Number.parseInt(
    resumeMetaText.match(/(\d+)\s*alan forma\s*aktarıldı/u)?.[1] ?? '0',
    10,
  );
  if (!Number.isSafeInteger(importedFieldCount) || importedFieldCount < 2) {
    throw new Error('candidate PDF did not autofill the application form');
  }
  if ((await candidatePage.getByTestId('candidate-email').inputValue()) !== candidateEmail) {
    throw new Error('candidate PDF email autofill mismatch');
  }
  if ((await candidatePage.getByTestId('candidate-fullName').inputValue()) !== candidateName) {
    throw new Error('candidate PDF full-name autofill mismatch');
  }
  const editedCandidateName = `${candidateName} Düzenlendi`;
  await candidatePage.getByTestId('candidate-fullName').fill(editedCandidateName);
  const fillIfEmpty = async (testId, value) => {
    const field = candidatePage.getByTestId(testId);
    if ((await field.inputValue()).trim() === '') await field.fill(value);
  };
  await fillIfEmpty('candidate-phone', '+90 555 000 00 00');
  await fillIfEmpty('candidate-city', 'İstanbul');
  await candidatePage.getByRole('button', { name: 'Deneyim bilgilerime geç' }).click();
  await fillIfEmpty(
    'candidate-summary',
    'Müşteri ihtiyacını çalışan ürün yolculuğuna dönüştüren sentetik aday.',
  );
  await fillIfEmpty('candidate-experience-0-title', 'Ürün Uzmanı');
  await fillIfEmpty('candidate-experience-0-company', 'Örnek Teknoloji');
  await fillIfEmpty('candidate-education-0-school', 'Örnek Üniversitesi');
  await fillIfEmpty('candidate-skills', 'Ürün keşfi, kullanıcı araştırması, analitik');
  // #240 B: ilan soruları aday formunda kendi bölümünde, İK'nın verdiği sırayla görünür.
  const questionsSection = candidatePage.getByTestId('candidate-questions');
  await waitVisible(questionsSection, 'candidate questions section');
  const questionsText = (await questionsSection.textContent()) ?? '';
  if (
    questionsText.indexOf('Hangi calisma bicimini tercih edersiniz?') < 0 ||
    questionsText.indexOf('Hangi calisma bicimini tercih edersiniz?') > questionsText.indexOf('Hangi teknik alanda deneyiminiz var?')
  ) {
    throw new Error('candidate questions are not rendered in recruiter order');
  }
  console.log('PASS candidate sees recruiter questions in recruiter order');
  // Zorunlu soru cevapsızken tek gerçek kapı (önizleme) kapalı kalır; backend de reddederdi.
  await candidatePage.getByRole('button', { name: 'Başvuruyu kontrol et' }).click();
  await waitVisible(
    candidatePage.getByRole('alert').filter({ hasText: 'zorunlu ilan sorularını yanıtlayın' }),
    'required question gate',
  );
  if (await candidatePage.getByTestId('candidate-application-preview').isVisible().catch(() => false)) {
    throw new Error('preview opened with a required question unanswered');
  }
  console.log('PASS candidate preview blocked until required question answered');
  await candidatePage.getByTestId(`candidate-question-${singleChoiceQuestionId}-${remoteOptionId}`).check();
  await candidatePage.getByTestId(`candidate-question-${textQuestionId}`).fill('Backend ve veri');
  await candidatePage.getByRole('button', { name: 'Başvuruyu kontrol et' }).click();
  await waitVisible(candidatePage.getByTestId('candidate-application-preview'), 'candidate preview');
  await waitVisible(
    candidatePage.getByTestId(`candidate-preview-question-${singleChoiceQuestionId}`).getByText('Uzaktan', { exact: true }),
    'single-choice answer preview',
  );
  await waitVisible(
    candidatePage.getByTestId(`candidate-preview-question-${textQuestionId}`).getByText('Backend ve veri', { exact: true }),
    'text answer preview',
  );
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
    'answers',
    'city',
    'educationEntries',
    'email',
    'experienceEntries',
    'fullName',
    'noticeAcceptedAt',
    'noticeVersion',
    'phone',
    'resumeDraftVersion',
    'resumeImportId',
    'skills',
    'summary',
  ].sort();
  if (JSON.stringify(submittedKeys) !== JSON.stringify(expectedSubmittedKeys)) {
    throw new Error(`candidate submission field boundary mismatch: ${submittedKeys.join(',')}`);
  }
  if (submittedPayload.fullName !== editedCandidateName || submittedPayload.email !== candidateEmail) {
    throw new Error('candidate edited PDF fields were not submitted');
  }
  if (
    !/^ri_[A-Za-z0-9_-]{24}$/u.test(submittedPayload.resumeImportId ?? '') ||
    !Number.isSafeInteger(submittedPayload.resumeDraftVersion) ||
    submittedPayload.resumeDraftVersion < 0
  ) {
    throw new Error('candidate submission is not bound to the confirmed resume draft');
  }
  // #240 B: cevaplar sunucu kimliklerine bağlı gider (etiket/metin DEĞİL), İK sırasıyla;
  // cevaplanmayan isteğe bağlı soru listeye girmez.
  const expectedAnswers = [
    { questionId: singleChoiceQuestionId, optionId: remoteOptionId },
    { questionId: textQuestionId, text: 'Backend ve veri' },
  ];
  if (JSON.stringify(submittedPayload.answers) !== JSON.stringify(expectedAnswers)) {
    throw new Error(`candidate answers not bound to server ids: ${JSON.stringify(submittedPayload.answers)}`);
  }
  if (JSON.stringify(submittedPayload.answers).includes('Uzaktan')) {
    throw new Error('answer carried a visible option label instead of optionId');
  }
  console.log('PASS candidate answers submitted bound to server ids');
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
  const currentStatusCard = candidatePage.getByText('Güncel durum', { exact: true }).locator('..');
  const currentStatusHeading = (name) =>
    currentStatusCard.getByRole('heading', { name, exact: true });
  const submittedStep = currentStatusHeading('Başvuru alındı');
  await waitVisible(submittedStep, 'submitted current state');
  await assertAxeClean(candidatePage, 'candidate-portal-mobile');
  await assertNoHorizontalOverflow(candidatePage, 'candidate-portal-mobile');

  await recruiterPage.getByRole('tab', { name: 'Başvurular' }).click();
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

  // ats#240 C: İK, adayın cevaplarını soru METNİYLE (cevap anındaki anlık görüntü),
  // İK sırasında ve karar eylemlerinin ÜSTÜNDE görür; seçenek etiketi görünür, kimlik değil.
  const answersSection = reviewPanel.getByTestId('recruiter-application-answers');
  await waitVisible(answersSection, 'recruiter candidate answers section');
  if ((await answersSection.getByRole('listitem').count()) !== 2) {
    throw new Error('recruiter candidate answers row count mismatch');
  }
  const modeAnswerRow = answersSection.getByTestId(`recruiter-application-answer-${singleChoiceQuestionId}`);
  const textAnswerRow = answersSection.getByTestId(`recruiter-application-answer-${textQuestionId}`);
  await waitVisible(
    modeAnswerRow.getByText('Hangi calisma bicimini tercih edersiniz?', { exact: true }),
    'recruiter answer carries the question text',
  );
  await waitVisible(modeAnswerRow.getByText('Uzaktan', { exact: true }), 'recruiter answer option label');
  await waitVisible(modeAnswerRow.getByText('Tek seçim · zorunlu', { exact: true }), 'recruiter answer kind and required marker');
  await waitVisible(textAnswerRow.getByText('Backend ve veri', { exact: true }), 'recruiter answer text');
  const answersText = (await answersSection.textContent()) ?? '';
  if (
    answersText.indexOf('Hangi calisma bicimini tercih edersiniz?') >
    answersText.indexOf('Hangi teknik alanda deneyiminiz var?')
  ) {
    throw new Error('recruiter candidate answers not in recruiter order');
  }
  if (answersText.includes(remoteOptionId) || answersText.includes(singleChoiceQuestionId)) {
    throw new Error('recruiter candidate answers leak ids instead of labels');
  }
  if (answersText.includes('Yanıtlanmadı')) {
    throw new Error('recruiter candidate answers show an unanswered row for answered questions');
  }
  const answersPrecedeDecision = await reviewPanel.evaluate((panel) => {
    const section = panel.querySelector('[data-testid="recruiter-application-answers"]');
    const heading = [...panel.querySelectorAll('h3')].find(
      (node) => node.textContent?.trim() === 'Açık insan eylemleri',
    );
    return Boolean(
      section && heading && section.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
  if (!answersPrecedeDecision) {
    throw new Error('recruiter candidate answers must precede the decision actions');
  }

  await reviewPanel.getByRole('button', { name: 'İnsan incelemesini başlat' }).click();
  await waitVisible(reviewPanel.getByRole('button', { name: 'Kısa listeye al' }), 'under review transition');
  const refreshStatusButton = candidatePage.getByRole('button', { name: 'Durumu yenile' });
  const reviewStep = currentStatusHeading('İnsan incelemesinde');
  await refreshUntilVisible(refreshStatusButton, reviewStep, 'candidate sees under review');

  await reviewPanel.getByRole('button', { name: 'Yapılandırılmış değerlendirme yap' }).click();
  const scorecard = reviewPanel.getByRole('form', { name: 'Yapılandırılmış insan scorecard’ı' });
  await waitVisible(scorecard, 'structured recruiter evaluation');
  const ratingFields = scorecard.getByLabel('Kanıt düzeyi (1–4)');
  const evidenceFields = scorecard.getByLabel('İşle ilgili somut kanıt');
  const criteriaCount = await ratingFields.count();
  if (criteriaCount === 0 || criteriaCount !== (await evidenceFields.count())) {
    throw new Error('structured recruiter scorecard criteria contract mismatch');
  }
  for (let index = 0; index < criteriaCount; index += 1) {
    await ratingFields.nth(index).selectOption('3');
    await evidenceFields
      .nth(index)
      .fill(`Sentetik kabul koşumu için ilana bağlı gözlemlenebilir kanıt ${index + 1}.`);
  }
  await scorecard.getByLabel('Genel gerekçe').fill(
    'Adayın sunduğu bilgiler ilan gereklilikleriyle yapılandırılmış insan incelemesinde eşleşti.',
  );
  await scorecard.getByRole('checkbox').check();
  const evaluationResponsePromise = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      relevantPath(response.url()) === `/api/ats/v1/recruiter/applications/${publicRef}/evaluations`,
    { timeout: 30_000 },
  );
  await scorecard.getByRole('button', { name: 'Immutable değerlendirmeyi kaydet' }).click();
  const evaluationResponse = await evaluationResponsePromise;
  if (evaluationResponse.status() !== 201) {
    throw new Error(`structured recruiter evaluation HTTP ${evaluationResponse.status()}`);
  }
  await scorecard.waitFor({ state: 'hidden', timeout: 30_000 });
  const interviewPendingButton = reviewPanel.getByRole('button', {
    name: 'Kısa listeye al',
  });

  const terminalTransitionResponse = recruiterPage.waitForResponse(
    (response) =>
      response.request().method() === 'PUT' &&
      relevantPath(response.url()) === `/api/ats/v1/recruiter/applications/${publicRef}/status`,
    { timeout: 30_000 },
  );
  await reviewPanel.getByRole('button', { name: 'Kısa listeye al' }).click();
  const terminalResponse = await terminalTransitionResponse;
  if (terminalResponse.status() !== 200) {
    throw new Error(`interview pending transition HTTP ${terminalResponse.status()}`);
  }
  const terminalStatusText = 'Durum güncellendi: Kısa listede.';
  const terminalStatus = reviewPanel.getByRole('status').filter({ hasText: terminalStatusText });
  await waitVisible(terminalStatus, 'interview pending terminal status');
  if ((await terminalStatus.textContent())?.trim() !== terminalStatusText) {
    throw new Error('interview pending terminal status text mismatch');
  }
  await assertAxeClean(recruiterPage, 'recruiter-workspace-terminal-desktop');
  await assertNoHorizontalOverflow(recruiterPage, 'recruiter-workspace-terminal-desktop');
  const interviewStep = currentStatusHeading('Mülakat planlaması');
  await refreshUntilVisible(refreshStatusButton, interviewStep, 'candidate sees interview pending');

  const interviewPanel = recruiterPage.getByTestId('recruiter-interview-workspace');
  await interviewPanel.getByRole('button', { name: 'Yeni görüşme planla', exact: true }).click();
  const scheduleForm = interviewPanel.getByRole('form', { name: 'Yeni görüşme planı', exact: true });
  const scheduleResponsePromise = recruiterPage.waitForResponse(r => r.url().includes(`/recruiter/applications/${publicRef}/interviews`) && r.request().method() === 'POST');
  await scheduleForm.getByRole('button', { name: 'Görüşmeyi kalıcı olarak planla', exact: true }).click();
  const scheduleResponse = await scheduleResponsePromise;
  if (![200,201].includes(scheduleResponse.status())) throw new Error(`interview schedule HTTP ${scheduleResponse.status()}`);
  const scheduled = await scheduleResponse.json();
  if (scheduled.status !== 'SCHEDULED') throw new Error('interview schedule state mismatch');
  const candidateCalendar = candidatePage.getByRole('region', {name:'Görüşme takvimim',exact:true});
  await refreshUntilVisible(refreshStatusButton, candidateCalendar.getByText('Planlandı', {exact:true}), 'candidate schedule readback');
  console.log('PASS synthetic interview scheduled and candidate calendar readback');
  await interviewPanel.getByRole('button', { name: 'Görüşmeyi iptal et', exact: true }).click();
  const internalReason = `Sentetik ic gerekce ${runSuffix}`;
  await interviewPanel.getByLabel('Gerekçe', {exact:true}).fill(internalReason);
  const cancelPromise = recruiterPage.waitForResponse(r => r.url().includes(`/interviews/${scheduled.interviewId}/transitions`) && r.request().method() === 'POST');
  await interviewPanel.getByRole('button', {name:'İnsan eylemini kaydet',exact:true}).click();
  const cancelResponse = await cancelPromise;
  if (cancelResponse.status()!==200 || (await cancelResponse.json()).status!=='CANCELLED') throw new Error('interview cancel persistence failed');
  await interviewPanel.getByRole('button', {name:'Görüşmeleri yenile',exact:true}).click();
  await waitVisible(interviewPanel.getByText('İptal edildi',{exact:true}), 'recruiter cancel independent readback');
  const safeCalendarPromise = candidatePage.waitForResponse(r => r.url().includes(`/candidate/applications/${publicRef}/interviews`) && r.request().method()==='GET');
  await refreshStatusButton.click();
  const safeCalendarResponse = await safeCalendarPromise;
  if (safeCalendarResponse.status()!==200) throw new Error('candidate calendar readback failed');
  const safeCalendar = await safeCalendarResponse.json();
  const forbidden = new Set(['participants','criteria','scorecards','actorRef','reason','summary','ratings','recommendation']);
  const hasInternal = value => Array.isArray(value) ? value.some(hasInternal) : value && typeof value==='object' ? Object.entries(value).some(([k,v]) => forbidden.has(k)||hasInternal(v)) : false;
  if (hasInternal(safeCalendar) || JSON.stringify(safeCalendar).includes(internalReason)) throw new Error('candidate calendar internal field leak');
  if (!Array.isArray(safeCalendar) || !safeCalendar.some(x=>x.interviewId===scheduled.interviewId && x.status==='CANCELLED')) throw new Error('candidate cancelled interview missing');
  await waitVisible(candidateCalendar.getByText('İptal edildi',{exact:true}), 'candidate cancelled state rendered');
  await candidateCalendar.screenshot({path:path.join(evidenceDir,'candidate-cancelled-synthetic.png')});
  console.log('PASS interview cancellation recruiter/candidate readback and internal fields absent');
  fs.writeFileSync(path.join(evidenceDir, 'interview-cancellation.json'), JSON.stringify({
    frontendSourceCommit: expectedFrontendSha, expectedAtsDigest, expectedFrontendDigest,
    syntheticOnly: true, interviewIdSha256: sha256(scheduled.interviewId),
    recruiterStatus: 'CANCELLED', candidateStatus: 'CANCELLED', internalFieldsAbsent: true,
    boundary: 'Two-persona functional check only; aggregate accessibility gate remains independent',
  }, null, 2));

  await recruiterPage.getByRole('button', { name: 'Aday detayını kapat' }).click();
  await recruiterPage.getByRole('tab', { name: 'İlanlar' }).click();
  await waitVisible(jobsPanel, 'recruiter jobs panel after candidate review');
  await recruiterPage.getByTestId('recruiter-job-filter-ALL').click();

  const negativeProbeContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
  });
  const publicStatePage = await negativeProbeContext.newPage();
  attachNetworkEvidence(publicStatePage, 'negative-probe');
  await publicStatePage.goto(`${baseURL}/jobs`, { waitUntil: 'domcontentloaded' });
  const anonymousRecruiterStatus = await publicStatePage.evaluate(async () => {
    const response = await fetch('/api/ats/v1/recruiter/applications', {
      cache: 'no-store',
      credentials: 'omit',
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    });
    return response.status;
  });
  if (anonymousRecruiterStatus !== 401) {
    throw new Error(
      `anonymous recruiter applications API expected 401, got ${anonymousRecruiterStatus}`,
    );
  }
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
    interviewStep,
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
    interviewStep,
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
    ['candidate', 'POST', publicApplicationApiPath, 201],
    ['candidate', 'GET', `/api/ats/v1/candidate/applications/${publicRef}`, 200],
    ['recruiter', 'GET', '/api/ats/v1/recruiter/applications', 200],
    ['recruiter', 'POST', `/api/ats/v1/recruiter/applications/${publicRef}/evaluations`, 201],
    ['recruiter', 'PUT', `/api/ats/v1/recruiter/applications/${publicRef}/status`, 200],
    ['negative-probe', 'GET', '/api/ats/v1/recruiter/applications', 401],
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
      'recruiter-question-create-reorder-stable-ids-reopen-delete',
      'recruiter-question-required-flag-persists',
      'recruiter-previews-draft',
      'recruiter-publishes-job',
      'candidate-opens-dynamic-public-job',
      'candidate-imports-real-pdf-locally',
      'candidate-edits-pdf-autofilled-field',
      'editable-candidate-form',
      'candidate-sees-recruiter-questions-in-order',
      'candidate-preview-blocked-until-required-question-answered',
      'candidate-answers-bound-to-server-ids',
      'explicit-preview-and-confirmation',
      'persistent-receipt-created',
      'candidate-sees-submitted',
      'authorized-recruiter-inbox',
      'recruiter-reads-candidate-answers-with-question-text',
      'human-controlled-under-review-transition',
      'candidate-sees-under-review',
      'human-controlled-interview-pending-transition',
      'candidate-sees-interview-pending',
      'synthetic-interview-schedule-cancel-two-persona-readback-no-internal-fields',
      'recruiter-pauses-job',
      'paused-job-rejects-new-application',
      'existing-candidate-result-survives-pause',
      'recruiter-republishes-job',
      'recruiter-closes-job',
      'closed-job-rejects-new-application',
      'existing-candidate-result-survives-close',
      'anonymous-recruiter-applications-denied',
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
      'network evidence excludes headers and bodies; raw PDF, extracted text, and filename are not retained or submitted; screenshots contain synthetic product state only',
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
