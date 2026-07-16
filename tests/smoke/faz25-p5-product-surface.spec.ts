import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Frame, type Locator, type Page } from '@playwright/test';
import { createHash, randomBytes } from 'node:crypto';
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
  process.env.P5_EXPECTED_SOURCE_SHA ?? 'bc33397de0a1eb097a1e045396c178d66c1bed95';
const expectedFrontendDigest =
  process.env.P5_EXPECTED_FRONTEND_DIGEST ??
  'sha256:aab566968dc0406fe5ca81143a3eac378fc8a877a00f0ab88e0f048603949f6d';
const expectedBuildRunId = process.env.P5_EXPECTED_BUILD_RUN_ID ?? '29487972095';
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
const expectedHubPath = '/admin/ats';
const expectedFinalPath = '/admin/interview-evidence';
const startedAt = new Date().toISOString();

const expectedCapabilityIds = [
  'interview-evidence-workspace',
  'candidate-cv-pdf-import',
  'candidate-review-and-appeal',
  'citation-backed-coaching',
  'fairness-audit',
  'quality-of-hire',
  'skills-evidence',
  'media-integrity',
  'agentic-screening',
] as const;
const expectedTargetRoleIds = [
  'candidate',
  'recruiter',
  'hiring_manager',
  'interviewer',
  'auditor',
  'admin',
] as const;
const expectedRoleCapabilityCounts = {
  candidate: 3,
  recruiter: 8,
  hiring_manager: 6,
  interviewer: 3,
  auditor: 7,
  admin: 6,
} as const;
const expectedRoleCapabilityIds = {
  candidate: [
    'candidate-cv-pdf-import',
    'candidate-review-and-appeal',
    'skills-evidence',
  ],
  recruiter: [
    'interview-evidence-workspace',
    'candidate-cv-pdf-import',
    'candidate-review-and-appeal',
    'citation-backed-coaching',
    'quality-of-hire',
    'skills-evidence',
    'media-integrity',
    'agentic-screening',
  ],
  hiring_manager: [
    'interview-evidence-workspace',
    'citation-backed-coaching',
    'fairness-audit',
    'quality-of-hire',
    'skills-evidence',
    'agentic-screening',
  ],
  interviewer: [
    'interview-evidence-workspace',
    'citation-backed-coaching',
    'skills-evidence',
  ],
  auditor: [
    'interview-evidence-workspace',
    'candidate-review-and-appeal',
    'citation-backed-coaching',
    'fairness-audit',
    'quality-of-hire',
    'media-integrity',
    'agentic-screening',
  ],
  admin: [
    'interview-evidence-workspace',
    'candidate-review-and-appeal',
    'fairness-audit',
    'quality-of-hire',
    'media-integrity',
    'agentic-screening',
  ],
} as const;
const expectedSyntheticResumeProposalCount = 5;
const expectedEditedEmail = 'aday.duzenlendi@example.invalid';
const mutationQuietPeriodMs = 1_000;
const expectedAgenticInteractiveControlSignatures = {
  closed: ['BUTTON:button:Ajan önerisini güvenle dene'],
  opened: [
    'BUTTON:button:Güvenli denemeyi kapat',
    'BUTTON:button:Sentetik çıktıyı üret',
  ],
  completed: ['BUTTON:button:Güvenli denemeyi kapat', 'BUTTON:button:Denemeyi sıfırla'],
} as const;
const expectedSafeScenarioJourneys = {
  'candidate-review-and-appeal': {
    action: 'Düzeltme taslağını dene',
    scenario: 'Sentetik aday, transkriptteki görev süresi bilgisinin yanlış olduğunu işaretler.',
    output: 'İnsan incelemesine gönderilecek kanıta bağlı düzeltme taslağı gösterilir.',
    boundary: 'Talep gönderilmez; aday kimliği, kişisel veri ve üretim kaydı kullanılmaz.',
  },
  'citation-backed-coaching': {
    action: 'Koçluk önerisini dene',
    scenario: 'Sentetik görüşmede bir yetkinlik için takip sorusu eksik kalır.',
    output: 'İlgili kanıt alıntısına bağlı, tarafsız bir takip sorusu taslağı gösterilir.',
    boundary: 'Öneri uygulanamaz; duygu, kişilik, aldatma veya uygunluk çıkarımı yapılmaz.',
  },
  'fairness-audit': {
    action: 'Adalet senaryosunu dene',
    scenario:
      'Tamamen sentetik iki değerlendirme grubunda ölçüt kullanım oranları karşılaştırılır.',
    output: 'Tutarlılık farkı, örneklem uyarısı ve insan inceleme önerisi gösterilir.',
    boundary: 'Gerçek aday, korunan özellik, sıralama veya otomatik aksiyon kullanılmaz.',
  },
  'quality-of-hire': {
    action: 'Kalite ölçümünü dene',
    scenario: 'Sentetik bir işe alım kohortunda kanıt kapsama oranı zaman içinde izlenir.',
    output: 'Eksik kanıt alanları ve ölçüm belirsizliği gösterilir.',
    boundary: 'Kişi puanı, performans tahmini, sıralama veya iş akışı mutasyonu yoktur.',
  },
  'skills-evidence': {
    action: 'Beceri kanıtını dene',
    scenario: 'Sentetik yanıt, problem çözme ölçütüyle ilişkili açık bir örnek içerir.',
    output: 'Kanıt alıntısı ve insanın onaylayabileceği beceri etiketi taslağı gösterilir.',
    boundary: 'Etiket kaydedilmez ve aday hakkında nihai çıkarım yapılmaz.',
  },
  'media-integrity': {
    action: 'Bütünlük incelemesini dene',
    scenario: 'Sentetik medya manifestinde beklenen dosya özeti ile gelen özet uyuşmaz.',
    output: 'Teknik yeniden-doğrulama uyarısı ve insan inceleme adımı gösterilir.',
    boundary: 'Kişi niyeti veya aldatma çıkarımı yapılmaz; aday kararı etkilenmez.',
  },
} as const;
const allSafeExperienceCapabilityIds = [
  'candidate-cv-pdf-import',
  ...Object.keys(expectedSafeScenarioJourneys),
  'agentic-screening',
] as const;
const expectedRoleJourneyCapabilityIds = {
  candidate: ['candidate-cv-pdf-import', 'candidate-review-and-appeal', 'skills-evidence'],
  recruiter: [
    'candidate-cv-pdf-import',
    'candidate-review-and-appeal',
    'citation-backed-coaching',
    'quality-of-hire',
    'skills-evidence',
    'media-integrity',
    'agentic-screening',
  ],
  hiring_manager: [
    'citation-backed-coaching',
    'fairness-audit',
    'quality-of-hire',
    'skills-evidence',
    'agentic-screening',
  ],
  interviewer: ['citation-backed-coaching', 'skills-evidence'],
  auditor: [
    'candidate-review-and-appeal',
    'citation-backed-coaching',
    'fairness-audit',
    'quality-of-hire',
    'media-integrity',
    'agentic-screening',
  ],
  admin: [
    'candidate-review-and-appeal',
    'fairness-audit',
    'quality-of-hire',
    'media-integrity',
    'agentic-screening',
  ],
} as const;
const expectedAgenticJourney = {
  action: 'Ajan önerisini güvenle dene',
  scenario:
    'Sentetik bir başvuruda eksik insan inceleme adımı için açıklanabilir sonraki-adım taslağı istenir.',
  output:
    'Gerekçe, gerekli insan onayları ve uygulanamayacak eylemlerle birlikte salt-okunur öneri gösterilir.',
  boundary:
    'Mesaj gönderilmez, aday durumu değişmez, red/teklif/sıralama üretilmez ve toplu onay yoktur.',
} as const;
const expectedInitialHubControlSignatures = [
  'A::Canlı Interview Evidence modülünü aç',
  'BUTTON:button:Tüm roller',
  'BUTTON:button:Aday',
  'BUTTON:button:İşe alım uzmanı',
  'BUTTON:button:İşe alım yöneticisi',
  'BUTTON:button:Mülakatçı',
  'BUTTON:button:Denetçi',
  'BUTTON:button:Yönetici',
  'BUTTON:button:Sentetik PDF taslak akışını dene',
  ...Object.values(expectedSafeScenarioJourneys).map(
    (journey) => `BUTTON:button:${journey.action}`,
  ),
  'BUTTON:button:Ajan önerisini güvenle dene',
].sort();

const readInteractiveControlSignatures = (rootLocator: Locator) =>
  rootLocator.evaluate((rootElement) => {
    const selector = [
      'button',
      'a[href]',
      'area[href]',
      'input',
      'select',
      'textarea',
      'summary',
      'audio[controls]',
      'video[controls]',
      'iframe',
      'frame',
      'portal',
      'object',
      'embed',
      'form[action]',
      '[contenteditable]:not([contenteditable="false" i])',
      '[role="button"]',
      '[role="link"]',
      '[role="menuitem"]',
      '[role="menuitemcheckbox"]',
      '[role="menuitemradio"]',
      '[role="checkbox"]',
      '[role="radio"]',
      '[role="switch"]',
      '[role="tab"]',
      '[role="slider"]',
      '[role="spinbutton"]',
      '[role="textbox"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[role="option"]',
      '[role="treeitem"]',
      '[tabindex]:not([tabindex="-1"])',
      '[target="_blank"]',
      '[formtarget="_blank"]',
      '[onclick]',
      '[ondblclick]',
      '[onmousedown]',
      '[onmouseup]',
      '[onpointerdown]',
      '[onpointerup]',
      '[ontouchstart]',
      '[ontouchend]',
      '[onkeydown]',
      '[onkeypress]',
      '[onkeyup]',
      '[onauxclick]',
      '[onbeforeinput]',
      '[onchange]',
      '[oncontextmenu]',
      '[ondragend]',
      '[ondragstart]',
      '[ondrop]',
      '[oninput]',
      '[onsubmit]',
      '[draggable="true"]',
    ].join(',');
    const controls = new Set<Element>();
    const syntheticSignatures = new Set<string>();
    const actionHandlerNames = new Set([
      'onClick',
      'onAuxClick',
      'onBeforeInput',
      'onChange',
      'onContextMenu',
      'onDoubleClick',
      'onDragEnd',
      'onDragStart',
      'onDrop',
      'onInput',
      'onMouseDown',
      'onMouseUp',
      'onPointerDown',
      'onPointerUp',
      'onTouchStart',
      'onTouchEnd',
      'onKeyDown',
      'onKeyUp',
      'onKeyPress',
      'onSubmit',
    ]);
    const visit = (root: Element | ShadowRoot) => {
      root.querySelectorAll(selector).forEach((control) => controls.add(control));
      const elements = [
        ...(root instanceof Element ? [root] : []),
        ...Array.from(root.querySelectorAll('*')),
      ];
      elements.forEach((element) => {
        const nativeEventTarget = element as HTMLElement;
        if (
          [
            nativeEventTarget.onclick,
            nativeEventTarget.onauxclick,
            nativeEventTarget.onbeforeinput,
            nativeEventTarget.onchange,
            nativeEventTarget.oncontextmenu,
            nativeEventTarget.ondblclick,
            nativeEventTarget.ondragend,
            nativeEventTarget.ondragstart,
            nativeEventTarget.ondrop,
            nativeEventTarget.oninput,
            nativeEventTarget.onkeydown,
            nativeEventTarget.onkeypress,
            nativeEventTarget.onkeyup,
            nativeEventTarget.onmousedown,
            nativeEventTarget.onmouseup,
            nativeEventTarget.onpointerdown,
            nativeEventTarget.onpointerup,
            nativeEventTarget.onsubmit,
            nativeEventTarget.ontouchend,
            nativeEventTarget.ontouchstart,
          ].some((handler) => typeof handler === 'function')
        ) {
          controls.add(element);
        }
        for (const key of Object.getOwnPropertyNames(element)) {
          if (!key.startsWith('__reactProps$')) continue;
          const props = (element as unknown as Record<string, unknown>)[key];
          if (
            props &&
            typeof props === 'object' &&
            Object.entries(props).some(
              ([name, value]) => actionHandlerNames.has(name) && typeof value === 'function',
            )
          ) {
            controls.add(element);
          }
        }
        if (element.shadowRoot) visit(element.shadowRoot);
      });
      const snapshot = (
        window as Window & {
          __p5BrowserAuditSnapshot?: () => {
            actionTargets: Array<{
              target: EventTarget;
              listeners: Array<{ type: string; count: number }>;
            }>;
          };
        }
      ).__p5BrowserAuditSnapshot?.();
      for (const entry of snapshot?.actionTargets ?? []) {
        const target = entry.target;
        const isReactDelegationRoot =
          target instanceof Element &&
          Object.getOwnPropertyNames(target).some(
            (key) => key === '_reactRootContainer' || key.startsWith('__reactContainer$'),
          );
        const isWithinRoot =
          target instanceof Element &&
          (root instanceof Element
            ? target === root || root.contains(target)
            : root.contains(target));
        const shadowHostWithinRoot =
          target instanceof ShadowRoot &&
          (root instanceof Element
            ? root === target.host || root.contains(target.host)
            : root.contains(target.host));
        const listenerIdentity = entry.listeners
          .map(({ type, count }) => `${type}=${count}`)
          .sort()
          .join(',');
        if (isReactDelegationRoot && isWithinRoot) {
          const rootIdentity =
            target.getAttribute('id') ?? target.getAttribute('data-testid') ?? target.tagName;
          syntheticSignatures.add(`REACT_ROOT:${rootIdentity}:${listenerIdentity}`);
        } else if (isWithinRoot) {
          controls.add(target);
          const targetIdentity =
            target.getAttribute('data-testid') ?? target.getAttribute('id') ?? target.tagName;
          syntheticSignatures.add(`LISTENERS:${targetIdentity}:${listenerIdentity}`);
        } else if (shadowHostWithinRoot) {
          controls.add(target.host);
          const targetIdentity =
            target.host.getAttribute('data-testid') ??
            target.host.getAttribute('id') ??
            target.host.tagName;
          syntheticSignatures.add(`SHADOW_LISTENERS:${targetIdentity}:${listenerIdentity}`);
        }
      }
    };
    visit(rootElement);
    const controlSignatures = Array.from(controls).map((control) => {
      const label =
        control.getAttribute('aria-label') ??
        (control.textContent ?? '').replace(/\s+/g, ' ').trim();
      return `${control.tagName}:${control.getAttribute('type') ?? ''}:${label}`;
    });
    return [...controlSignatures, ...syntheticSignatures].sort();
  });

const replaceSignatureMultiset = (
  baseline: string[],
  removed: readonly string[],
  added: readonly string[],
) => {
  const expected = [...baseline];
  for (const signature of removed) {
    const index = expected.indexOf(signature);
    expect(index).toBeGreaterThanOrEqual(0);
    expected.splice(index, 1);
  }
  return [...expected, ...added].sort();
};

const activateByKeyboard = async (control: Locator, key: 'Enter' | 'Space' = 'Enter') => {
  await expect(control).toBeVisible();
  await expect(control).toBeEnabled();
  await control.focus();
  await expect(control).toBeFocused();
  await control.press(key);
};

const canonicalizeJson = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalizeJson(item)]),
    );
  }
  return value;
};

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
  schemaVersion: 'faz25-p5-authenticated-product-surface-v5';
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
    buildInfoImageDigest: string;
    buildInfoImageDigestStatus: 'NOT_EMBEDDED';
    buildInfoSha256: string;
    buildInfoProbeId: string;
    buildInfoCacheControl: string;
    buildInfoCacheBypassHeadersAbsent: boolean;
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
  discovery?: {
    desktopHomePath: string;
    desktopSidebarVisible: boolean;
    desktopSidebarHref: string;
    desktopSearchQuery: string;
    desktopSearchResultVisible: boolean;
    desktopHubPath: string;
    desktopHubRendered: boolean;
    desktopLaunchPath: string;
    desktopRemoteConsoleRendered: boolean;
    mobileViewportWidth: number;
    mobileHomePath: string;
    mobileMenuOpened: boolean;
    mobileHrSectionOpened: boolean;
    mobileAtsProductHubActionVisible: boolean;
    mobileHubPath: string;
    mobileHubRendered: boolean;
    mobileLaunchPath: string;
    mobileRemoteConsoleRendered: boolean;
  };
  hub?: {
    path: string;
    rendered: boolean;
    runtimeReady: boolean;
    capabilityIds: string[];
    targetRoleIds: string[];
    visibleCapabilityCount: number;
    roleCapabilityCounts: Record<string, number>;
    roleCapabilityIds: Record<string, string[]>;
    roleJourneyCapabilityIds: Record<string, string[]>;
    roleJourneyEvidenceClass: 'TARGET_ROLE_FILTER_UNDER_NAMED_VIEW_PERSONA';
    journeyLifecycleAudit: {
      desktop: Record<string, number>;
      mobile?: Record<string, number>;
    };
    candidateFilterVisible: boolean;
    candidateBoundaryVisible: boolean;
    cvImportMode: 'OWNER_GATED';
    cvImportInteractiveControlCount: number;
    fileUploadControlCount: number;
    syntheticResume: {
      proposalCount: number;
      invalidFixtureCount: number;
      editableAfterFirstKeystroke: boolean;
      editedEmail: string;
      acceptAfterEditVisible: boolean;
      rejectAfterEditVisible: boolean;
      acceptedDraftFieldCount: number;
      localDraftVisible: boolean;
      localDraftContainsEditedEmail: boolean;
      rejectAllSecondConfirmationRequired: boolean;
      rejectAllApplied: boolean;
      resetReturnedToStart: boolean;
      persistentStoresUnchanged: boolean;
      persistentWriteOperationCount: number;
      mutationQuietPeriodMs: number;
      mutationRequestCount: number;
      networkRequestCount: number;
      networkChannelConstructionCount: number;
      workerConstructionCount: number;
      popupCreationCount: number;
      filePickerInvocationCount: number;
      unsafeDelegatedActionListenerCount: number;
    };
    agentic: {
      mode: 'PROPOSAL_ONLY' | 'UNVERIFIED';
      runnerCompleted: boolean;
      boundaryVisible: boolean;
      interactiveControlSignatures: {
        closed: string[];
        opened: string[];
        completed: string[];
      };
      forbiddenActionControlCount: number;
      persistentStoresUnchanged: boolean;
      persistentWriteOperationCount: number;
      mutationQuietPeriodMs: number;
      mutationRequestCount: number;
      networkRequestCount: number;
      networkChannelConstructionCount: number;
      workerConstructionCount: number;
      popupCreationCount: number;
      filePickerInvocationCount: number;
      unsafeDelegatedActionListenerCount: number;
    };
    safeExperienceCapabilityIds: string[];
    safeScenarioAudit: {
      completedCapabilityIds: string[];
      persistentStoresUnchanged: boolean;
      persistentWriteOperationCount: number;
      networkRequestCount: number;
      mutationRequestCount: number;
      networkChannelConstructionCount: number;
      workerConstructionCount: number;
      popupCreationCount: number;
      filePickerInvocationCount: number;
      unsafeDelegatedActionListenerCount: number;
    };
    liveLaunchHref: string;
    productBoundaryVisible: boolean;
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
    mobileUserAgentMatched: boolean;
    mobileTouchPoints: number;
    mobilePointerCoarse: boolean;
    mobileDeviceScaleFactor: number;
    hubRootOverflowPx: number;
    hubOverflowPx: number;
    rootOverflowPx: number;
    consoleOverflowPx: number;
    mobileSyntheticResumeControlsRendered: boolean;
    mobileCandidateCapabilityIds: string[];
    mobileCompletedSafeScenarioCapabilityIds: string[];
    mobileSyntheticResumePersistentStoresUnchanged: boolean;
    mobileSyntheticResumePersistentWriteOperationCount: number;
    mobileSyntheticResumeMutationRequestCount: number;
    mobileSyntheticResumeNetworkRequestCount: number;
    mobileSyntheticResumeNetworkChannelConstructionCount: number;
    mobileSyntheticResumeWorkerConstructionCount: number;
    mobileSyntheticResumePopupCreationCount: number;
    mobileSyntheticResumeFilePickerInvocationCount: number;
    mobileSyntheticResumeUnsafeDelegatedActionListenerCount: number;
    mobileRoleJourneyCapabilityIds: Record<string, string[]>;
    mobileRoleJourneyEvidenceClass: string;
    mobileTouchActivationCount: number;
    evidenceTableKeyboardScrollable: boolean;
  };
  accessibility?: {
    loginBlockingViolationCount: number;
    hubBlockingViolationCount: number;
    productBlockingViolationCount: number;
    blockingViolationCount: number;
    violations: Array<{
      surface: 'login' | 'hub' | 'product';
      id: string;
      impact: string | null;
      nodeCount: number;
    }>;
  };
  runtime?: {
    uncaughtPageErrorCount: number;
    frontendAssetPaths: string[];
    frontendAssetResponses: Array<{
      path: string;
      resourceType: 'script' | 'stylesheet';
      status: number;
      contentType: string;
      bodySha256: string;
      fromServiceWorker: boolean;
    }>;
    buildInfoRootEntryMatched: boolean;
    buildInfoAssetsMatched: boolean;
  };
  failedTestStatus?: string;
};

const report: AcceptanceReport = {
  schemaVersion: 'faz25-p5-authenticated-product-surface-v5',
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
    buildInfoImageDigest: '',
    buildInfoImageDigestStatus: 'NOT_EMBEDDED',
    buildInfoSha256: '',
    buildInfoProbeId: '',
    buildInfoCacheControl: '',
    buildInfoCacheBypassHeadersAbsent: false,
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
  report.lineage.buildInfoProbeId = randomBytes(16).toString('hex');
  const probedBuildInfoUrl = `${buildInfoUrl}?p5_probe=${report.lineage.buildInfoProbeId}`;
  const buildInfoResponse = await page.request.get(probedBuildInfoUrl, {
    maxRedirects: 0,
  });
  expect(buildInfoResponse.ok(), 'build-info.json must be reachable').toBe(true);
  expect(buildInfoResponse.url()).toBe(probedBuildInfoUrl);
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
    'rootEntrypoints',
    'schemaVersion',
    'sha',
    'shortSha',
  ]);
  expect(buildInfo.schemaVersion).toBe('acik.platform.web-build-info/v2');
  expect(buildInfo.origin).toBe(baseURL);
  expect(buildInfo.ref).toBe('main');
  const buildInfoAssets = Array.isArray(buildInfo.assets)
    ? buildInfo.assets.filter((asset): asset is string => typeof asset === 'string')
    : [];
  expect(Array.isArray(buildInfo.assets)).toBe(true);
  expect(buildInfoAssets).toHaveLength(
    Array.isArray(buildInfo.assets) ? buildInfo.assets.length : -1,
  );
  expect(buildInfoAssets).toEqual([...buildInfoAssets].sort());
  expect(buildInfoAssets.length).toBeGreaterThan(0);
  type BuildInfoRootEntrypoint = { path: string; bodySha256: string };
  const buildInfoRootEntrypoints = Array.isArray(buildInfo.rootEntrypoints)
    ? buildInfo.rootEntrypoints.filter(
        (entry): entry is BuildInfoRootEntrypoint =>
          typeof entry === 'object' && entry !== null && !Array.isArray(entry),
      )
    : [];
  expect(Array.isArray(buildInfo.rootEntrypoints)).toBe(true);
  expect(buildInfoRootEntrypoints).toHaveLength(
    Array.isArray(buildInfo.rootEntrypoints) ? buildInfo.rootEntrypoints.length : -1,
  );
  expect(buildInfoRootEntrypoints.length).toBeGreaterThan(0);
  const rootEntrypointPaths = new Set<string>();
  for (const rootEntrypoint of buildInfoRootEntrypoints) {
    expect(Object.keys(rootEntrypoint).sort()).toEqual(['bodySha256', 'path']);
    expect(rootEntrypoint.path).toMatch(/^\/[A-Za-z0-9._/-]+\.(?:js|mjs)$/);
    expect(rootEntrypoint.path).not.toContain('//');
    expect(rootEntrypoint.path.split('/')).not.toContain('.');
    expect(rootEntrypoint.path.split('/')).not.toContain('..');
    expect(rootEntrypoint.bodySha256).toMatch(/^[0-9a-f]{64}$/);
    expect(rootEntrypointPaths.has(rootEntrypoint.path)).toBe(false);
    rootEntrypointPaths.add(rootEntrypoint.path);
  }
  const buildInfoRootEntry =
    typeof buildInfo.rootEntry === 'string' ? buildInfo.rootEntry : '';
  expect(buildInfoRootEntry).toMatch(/^[A-Za-z0-9._-]+\.(?:js|mjs)$/);
  expect(buildInfoRootEntry).toBe(
    buildInfoRootEntrypoints[0].path.split('/').at(-1),
  );
  report.lineage.observedSourceSha =
    typeof buildInfo.sha === 'string' ? buildInfo.sha : '';
  expect(report.lineage.observedSourceSha).toBe(expectedSourceSha);
  report.lineage.buildInfoImageDigest =
    typeof buildInfo.imageDigest === 'string' ? buildInfo.imageDigest : '';
  expect(report.lineage.buildInfoImageDigest).toBe('');
  expect(report.lineage.buildInfoImageDigestStatus).toBe('NOT_EMBEDDED');
  const buildInfoHeaders = buildInfoResponse.headers();
  report.lineage.buildInfoCacheControl = buildInfoHeaders['cache-control'] ?? '';
  expect(report.lineage.buildInfoCacheControl).toBe('no-store');
  const cacheBypassHeaders = [
    'age',
    'cf-cache-status',
    'via',
    'x-cache',
    'x-proxy-cache',
    'x-served-by',
  ];
  report.lineage.buildInfoCacheBypassHeadersAbsent = cacheBypassHeaders.every(
    (header) => !(header in buildInfoHeaders),
  );
  expect(report.lineage.buildInfoCacheBypassHeadersAbsent).toBe(true);
  report.lineage.buildInfoSha256 = createHash('sha256')
    .update(JSON.stringify(canonicalizeJson(buildInfo)))
    .digest('hex');
  expect(report.lineage.buildInfoSha256).toMatch(/^[0-9a-f]{64}$/);

  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.name));
  const applicationNetworkRequests: Array<{ method: string; origin: string; path: string }> = [];
  type FrontendAssetResponse = {
    path: string;
    resourceType: 'script' | 'stylesheet';
    status: number;
    contentType: string;
    bodySha256: string;
    fromServiceWorker: boolean;
  };
  const frontendAssetResponsePromises: Array<Promise<FrontendAssetResponse>> = [];
  const unexpectedPopupPages: Array<{
    page: Page;
    observedMainFrameUrls: string[];
  }> = [];
  const unexpectedWebSockets: string[] = [];
  const unexpectedWorkers: string[] = [];
  const frameLifecycleRecords: Array<{
    frame: Frame;
    observedUrls: string[];
    detached: boolean;
  }> = [];
  const frameLifecycleByFrame = new Map<
    Frame,
    (typeof frameLifecycleRecords)[number]
  >();
  const normalizeFrameUrl = (value: string) => {
    if (value === '' || value === 'about:blank') return 'about:blank';
    try {
      const parsed = new URL(value);
      return ['http:', 'https:'].includes(parsed.protocol)
        ? `${parsed.origin}${parsed.pathname}`
        : parsed.protocol;
    } catch {
      // Never echo an unparseable raw URL into logs or evidence. The sentinel
      // is deliberately absent from every allowlist and therefore fails closed.
      return '<malformed>';
    }
  };
  const recordFrameUrl = (frame: Frame) => {
    const record = frameLifecycleByFrame.get(frame);
    if (!record) return;
    const normalizedUrl = normalizeFrameUrl(frame.url());
    if (record.observedUrls.at(-1) !== normalizedUrl) {
      record.observedUrls.push(normalizedUrl);
    }
  };
  let fileChooserEventCount = 0;
  let downloadEventCount = 0;
  let dialogEventCount = 0;
  page.context().on('page', (openedPage) => {
    if (openedPage === page) return;
    const observedMainFrameUrls: string[] = [];
    const recordMainFrameUrl = () => {
      const url = openedPage.url();
      if (observedMainFrameUrls.at(-1) !== url) observedMainFrameUrls.push(url);
    };
    const popupRecord = { page: openedPage, observedMainFrameUrls };
    unexpectedPopupPages.push(popupRecord);
    recordMainFrameUrl();
    openedPage.on('framenavigated', (frame) => {
      if (frame === openedPage.mainFrame()) recordMainFrameUrl();
    });
    openedPage.on('close', recordMainFrameUrl);
  });
  page.on('request', (request) => {
    const method = request.method();
    const url = new URL(request.url());
    applicationNetworkRequests.push({ method, origin: url.origin, path: url.pathname });
  });
  page.on('response', (response) => {
    const request = response.request();
    const resourceType = request.resourceType();
    const url = new URL(response.url());
    if (
      url.origin !== new URL(baseURL).origin ||
      (!url.pathname.startsWith('/assets/') && !rootEntrypointPaths.has(url.pathname)) ||
      !['script', 'stylesheet'].includes(resourceType) ||
      !/\.(?:js|mjs|css)$/.test(url.pathname)
    ) {
      return;
    }
    frontendAssetResponsePromises.push(
      (async () => {
        let bodySha256 = '';
        try {
          bodySha256 = createHash('sha256').update(await response.body()).digest('hex');
        } catch {
          bodySha256 = '';
        }
        return {
          path: url.pathname,
          resourceType: resourceType as 'script' | 'stylesheet',
          status: response.status(),
          contentType: response.headers()['content-type'] ?? '',
          bodySha256,
          fromServiceWorker: response.fromServiceWorker(),
        };
      })(),
    );
  });
  page.on('websocket', (webSocket) => unexpectedWebSockets.push(webSocket.url()));
  page.on('worker', (worker) => unexpectedWorkers.push(worker.url()));
  page.on('frameattached', (frame) => {
    const record = { frame, observedUrls: [] as string[], detached: false };
    frameLifecycleRecords.push(record);
    frameLifecycleByFrame.set(frame, record);
    recordFrameUrl(frame);
  });
  page.on('framenavigated', (frame) => recordFrameUrl(frame));
  page.on('framedetached', (frame) => {
    recordFrameUrl(frame);
    const record = frameLifecycleByFrame.get(frame);
    if (record) record.detached = true;
  });
  page.on('filechooser', () => {
    fileChooserEventCount += 1;
  });
  page.on('download', () => {
    downloadEventCount += 1;
  });
  page.on('dialog', (dialog) => {
    dialogEventCount += 1;
    void dialog.dismiss();
  });
  const mutationRequestCount = () =>
    applicationNetworkRequests.filter(
      ({ method }) => !['GET', 'HEAD', 'OPTIONS'].includes(method),
    ).length;
  await page.context().addInitScript(() => {
    const auditWindow = window as Window & {
      __p5BrowserAuditSnapshot?: () => {
        workerConstructionCount: number;
        popupCreationCount: number;
        filePickerInvocationCount: number;
        networkChannelConstructionCount: number;
        networkChannelConstructionTypes: string[];
        historyMutationCount: number;
        hashChangeCount: number;
        closedShadowRootAttemptCount: number;
        unsafeDomInsertionCount: number;
        productJourneyBegun: boolean;
        instrumentationFailureCount: number;
        actionTargets: Array<{
          target: EventTarget;
          listeners: Array<{ type: string; count: number }>;
        }>;
      };
      __p5BrowserAuditBeginProductJourney?: () => void;
    };
    const workerConstructions: string[] = [];
    const popupConstructions: string[] = [];
    const filePickerInvocations: string[] = [];
    const networkChannelConstructions: string[] = [];
    const historyMutations: string[] = [];
    const hashChanges: string[] = [];
    const closedShadowRootAttempts: string[] = [];
    const unsafeDomInsertions: string[] = [];
    const instrumentationFailures: string[] = [];
    let productJourneyBegun = false;
    const actionEventTargets = new Map<
      EventTarget,
      Map<string, Map<unknown, Set<boolean>>>
    >();
    Object.defineProperty(auditWindow, '__p5BrowserAuditSnapshot', {
      configurable: false,
      writable: false,
      value: () => ({
        workerConstructionCount: workerConstructions.length,
        popupCreationCount: popupConstructions.length,
        filePickerInvocationCount: filePickerInvocations.length,
        networkChannelConstructionCount: networkChannelConstructions.length,
        networkChannelConstructionTypes: [...networkChannelConstructions],
        historyMutationCount: historyMutations.length,
        hashChangeCount: hashChanges.length,
        closedShadowRootAttemptCount: closedShadowRootAttempts.length,
        unsafeDomInsertionCount: unsafeDomInsertions.length,
        productJourneyBegun,
        instrumentationFailureCount: instrumentationFailures.length,
        actionTargets: Array.from(actionEventTargets.entries()).map(
          ([target, listenersByType]) => ({
            target,
            listeners: Array.from(listenersByType.entries()).map(
              ([type, listeners]) => ({
                type,
                count: Array.from(listeners.values()).reduce(
                  (sum, captures) => sum + captures.size,
                  0,
                ),
              }),
            ),
          }),
        ),
      }),
    });
    Object.defineProperty(auditWindow, '__p5BrowserAuditBeginProductJourney', {
      configurable: false,
      writable: false,
      value: () => {
        if (productJourneyBegun) {
          instrumentationFailures.push('product-journey-reset-repeated');
          return;
        }
        workerConstructions.length = 0;
        popupConstructions.length = 0;
        filePickerInvocations.length = 0;
        networkChannelConstructions.length = 0;
        historyMutations.length = 0;
        hashChanges.length = 0;
        closedShadowRootAttempts.length = 0;
        unsafeDomInsertions.length = 0;
        productJourneyBegun = true;
      },
    });
    const installLockedValue = (target: object, property: string, value: unknown) => {
      const descriptor = Object.getOwnPropertyDescriptor(target, property);
      if (descriptor && descriptor.configurable === false && descriptor.writable === false) {
        instrumentationFailures.push(property);
        return;
      }
      Object.defineProperty(target, property, {
        configurable: false,
        writable: false,
        value,
      });
    };
    const blockedConstructor = (name: string, original: unknown) => {
      if (typeof original !== 'function') return original;
      return new Proxy(original, {
        construct() {
          workerConstructions.push(name);
          throw new Error(`${name} is forbidden during the local-only acceptance flow`);
        },
      });
    };
    const auditedConstructor = (name: string, original: unknown) => {
      if (typeof original !== 'function') return original;
      return new Proxy(original, {
        construct(target, args, newTarget) {
          networkChannelConstructions.push(name);
          return Reflect.construct(target, args, newTarget);
        },
      });
    };
    installLockedValue(window, 'Worker', blockedConstructor('Worker', window.Worker));
    if ('SharedWorker' in window) {
      installLockedValue(
        window,
        'SharedWorker',
        blockedConstructor('SharedWorker', window.SharedWorker),
      );
    }
    for (const channel of ['WebSocket', 'EventSource', 'WebTransport', 'RTCPeerConnection']) {
      const original = (window as unknown as Record<string, unknown>)[channel];
      if (typeof original === 'function') {
        installLockedValue(window, channel, auditedConstructor(channel, original));
      }
    }
    installLockedValue(
      window,
      'open',
      function blockedWindowOpen() {
        popupConstructions.push('WindowOpen');
        throw new Error('Popup creation is forbidden during the local-only acceptance flow');
      },
    );
    for (const picker of ['showOpenFilePicker', 'showSaveFilePicker', 'showDirectoryPicker']) {
      const original = (window as unknown as Record<string, unknown>)[picker];
      if (typeof original === 'function') {
        installLockedValue(window, picker, () => {
          filePickerInvocations.push(picker);
          throw new Error(`${picker} is forbidden during the local-only acceptance flow`);
        });
      }
    }
    if (typeof HTMLInputElement.prototype.showPicker === 'function') {
      installLockedValue(
        HTMLInputElement.prototype,
        'showPicker',
        function blockedInputShowPicker() {
          filePickerInvocations.push('HTMLInputElement.showPicker');
          throw new Error('Input picker is forbidden during the local-only acceptance flow');
        },
      );
    }
    const actionEventTypes = new Set([
      'auxclick',
      'beforeinput',
      'change',
      'click',
      'contextmenu',
      'dblclick',
      'dragend',
      'dragstart',
      'drop',
      'input',
      'keydown',
      'keypress',
      'keyup',
      'mousedown',
      'mouseup',
      'pointerdown',
      'pointerup',
      'submit',
      'touchend',
      'touchstart',
    ]);
    const originalAddEventListener = EventTarget.prototype.addEventListener;
    const captureFlag = (options?: boolean | AddEventListenerOptions | EventListenerOptions) =>
      typeof options === 'boolean' ? options : Boolean(options?.capture);
    const auditedAddEventListener = function auditedAddEventListener(
      this: EventTarget,
      type: string,
      listener: EventListenerOrEventListenerObject | null,
      options?: boolean | AddEventListenerOptions,
    ) {
      if (actionEventTypes.has(type) && listener) {
        const listenersByType =
          actionEventTargets.get(this) ?? new Map<string, Map<unknown, Set<boolean>>>();
        const listeners = listenersByType.get(type) ?? new Map<unknown, Set<boolean>>();
        const captures = listeners.get(listener) ?? new Set<boolean>();
        captures.add(captureFlag(options));
        listeners.set(listener, captures);
        listenersByType.set(type, listeners);
        actionEventTargets.set(this, listenersByType);
      }
      return originalAddEventListener.call(this, type, listener, options);
    };
    const originalRemoveEventListener = EventTarget.prototype.removeEventListener;
    const auditedRemoveEventListener = function auditedRemoveEventListener(
      this: EventTarget,
      type: string,
      listener: EventListenerOrEventListenerObject | null,
      options?: boolean | EventListenerOptions,
    ) {
      const listenersByType = actionEventTargets.get(this);
      const listeners = listenersByType?.get(type);
      if (listener && listeners) {
        const captures = listeners.get(listener);
        captures?.delete(captureFlag(options));
        if (captures?.size === 0) listeners.delete(listener);
        if (listeners.size === 0) listenersByType?.delete(type);
        if (listenersByType?.size === 0) actionEventTargets.delete(this);
      }
      return originalRemoveEventListener.call(this, type, listener, options);
    };
    installLockedValue(EventTarget.prototype, 'addEventListener', auditedAddEventListener);
    installLockedValue(EventTarget.prototype, 'removeEventListener', auditedRemoveEventListener);
    const serviceWorkerPrototype = navigator.serviceWorker
      ? (Object.getPrototypeOf(navigator.serviceWorker) as ServiceWorkerContainer & {
          register: ServiceWorkerContainer['register'];
        })
      : null;
    if (serviceWorkerPrototype && typeof serviceWorkerPrototype.register === 'function') {
      installLockedValue(
        serviceWorkerPrototype,
        'register',
        function blockedServiceWorkerRegister() {
          workerConstructions.push('ServiceWorker');
          return Promise.reject(
            new Error('ServiceWorker is forbidden during the local-only acceptance flow'),
          );
        },
      );
    }
    const navigatorPrototype = Object.getPrototypeOf(navigator) as Navigator & {
      sendBeacon?: Navigator['sendBeacon'];
    };
    if (typeof navigatorPrototype.sendBeacon === 'function') {
      const originalSendBeacon = navigatorPrototype.sendBeacon;
      installLockedValue(
        navigatorPrototype,
        'sendBeacon',
        function auditedSendBeacon(this: Navigator, ...args: Parameters<Navigator['sendBeacon']>) {
          networkChannelConstructions.push('sendBeacon');
          return Reflect.apply(originalSendBeacon, this, args);
        },
      );
    }
    for (const historyMethod of ['pushState', 'replaceState'] as const) {
      const original = History.prototype[historyMethod];
      installLockedValue(
        History.prototype,
        historyMethod,
        function auditedHistoryMutation(
          this: History,
          ...args: Parameters<History[typeof historyMethod]>
        ) {
          historyMutations.push(historyMethod);
          return Reflect.apply(original, this, args);
        },
      );
    }
    window.addEventListener('hashchange', () => hashChanges.push('hashchange'));
    const originalAttachShadow = Element.prototype.attachShadow;
    installLockedValue(
      Element.prototype,
      'attachShadow',
      function guardedAttachShadow(this: Element, init: ShadowRootInit) {
        if (init.mode === 'closed') {
          closedShadowRootAttempts.push('closed');
          throw new Error('Closed shadow roots are forbidden on the audited product surface');
        }
        return originalAttachShadow.call(this, init);
      },
    );
    const unsafeSelector = [
      'input[type="file"]',
      'iframe',
      'frame',
      'portal',
      '[target="_blank"]',
      '[formtarget="_blank"]',
      'template[shadowrootmode="closed"]',
    ].join(',');
    const recordUnsafeInsertion = (node: Node) => {
      if (!(node instanceof Element)) return;
      if (node.matches(unsafeSelector)) unsafeDomInsertions.push(node.tagName);
      node.querySelectorAll(unsafeSelector).forEach((element) =>
        unsafeDomInsertions.push(element.tagName),
      );
    };
    const unsafeDomObserver = new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach(recordUnsafeInsertion));
    });
    unsafeDomObserver.observe(document, { childList: true, subtree: true });
  });
  await page.context().addInitScript(persistentMutationAuditInstaller);

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
      url.pathname === expectedHubPath &&
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
    if (url.origin !== appOrigin || url.pathname !== expectedHubPath) return;
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

  await page.goto('/login?redirect=%2Fadmin%2Fats', {
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
  expect(redirectUri.pathname).toBe(expectedHubPath);

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

  const hubSurface = page.getByTestId('ats-product-hub');
  const consoleSurface = page.getByTestId('deployment-readiness-console');
  await expect(hubSurface).toBeVisible({ timeout: 90_000 });
  await expect(page).toHaveURL(/\/admin\/ats(?:[?#].*)?$/);
  const finalUrl = new URL(page.url());
  const finalFragment = new URLSearchParams(finalUrl.hash.replace(/^#/, ''));
  observed.oauthParametersCleared = ['code', 'state', 'session_state'].every(
    (key) => !finalUrl.searchParams.has(key) && !finalFragment.has(key),
  );
  expect(finalUrl.origin).toBe(appOrigin);
  expect(finalUrl.pathname).toBe(expectedHubPath);
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

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/home', { waitUntil: 'domcontentloaded' });
  const desktopHomePath = new URL(page.url()).pathname;
  expect(desktopHomePath).toBe('/home');

  const desktopSidebar = page.getByRole('complementary', { name: 'Sidebar' });
  const desktopSidebarLink = desktopSidebar.getByRole('link', {
    name: /ATS Ürün Merkezi/,
  });
  await expect(desktopSidebarLink).toBeVisible();
  await expect(desktopSidebarLink).toHaveAttribute('href', expectedHubPath);
  const desktopSidebarVisible = await desktopSidebarLink.isVisible();
  const desktopSidebarHref = (await desktopSidebarLink.getAttribute('href')) ?? '';

  const desktopSearchButton = page.getByRole('button', { name: /^(Ara|Search)$/ });
  await desktopSearchButton.focus();
  await expect(desktopSearchButton).toBeFocused();
  await page.keyboard.press('Enter');
  const commandPalette = page.getByRole('dialog');
  await expect(commandPalette).toBeVisible();
  const commandSearch = commandPalette.getByRole('textbox', { name: 'Command search' });
  await commandSearch.pressSequentially('mülakat');
  const desktopSearchQuery = await commandSearch.inputValue();
  expect(desktopSearchQuery).toBe('mülakat');
  const desktopSearchResult = commandPalette
    .getByRole('button', { name: /ATS Ürün Merkezi/ })
    .first();
  await expect(desktopSearchResult).toBeVisible();
  const desktopSearchResultVisible = await desktopSearchResult.isVisible();
  await desktopSearchResult.focus();
  await expect(desktopSearchResult).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(hubSurface).toBeVisible({ timeout: 90_000 });
  const desktopHubPath = new URL(page.url()).pathname;
  expect(desktopHubPath).toBe(expectedHubPath);
  const desktopHubRendered = await hubSurface.isVisible();

  type PopupHistorySnapshot = {
    closed: boolean;
    observedMainFrameUrls: string[];
  };
  const popupHistoryIsInert = (history: PopupHistorySnapshot[]) =>
    history.length <= 1 &&
    history.every(
      ({ closed, observedMainFrameUrls }) =>
        closed &&
        observedMainFrameUrls.length === 1 &&
        observedMainFrameUrls[0] === 'about:blank',
    );

  // Exercise the real context-level listener with an isolated, network-free
  // secondary page. The exact policy used below must reject a popup that
  // navigated away from about:blank, even after that page has closed.
  const popupLedgerNegativeControlPage = await page.context().newPage();
  await popupLedgerNegativeControlPage.goto(
    'data:text/html,popup-ledger-negative-control',
  );
  await popupLedgerNegativeControlPage.close();
  const popupLedgerNegativeControlIndex = unexpectedPopupPages.findIndex(
    (popupRecord) => popupRecord.page === popupLedgerNegativeControlPage,
  );
  if (popupLedgerNegativeControlIndex < 0) {
    throw new Error('popup-ledger-negative-control-not-observed');
  }
  const [popupLedgerNegativeControl] = unexpectedPopupPages.splice(
    popupLedgerNegativeControlIndex,
    1,
  );
  if (!popupLedgerNegativeControl) {
    throw new Error('popup-ledger-negative-control-missing');
  }
  expect(
    popupHistoryIsInert([
      {
        closed: popupLedgerNegativeControl.page.isClosed(),
        observedMainFrameUrls: popupLedgerNegativeControl.observedMainFrameUrls,
      },
    ]),
  ).toBe(false);

  // Browser and identity-provider setup may create and close one transient
  // blank target before the audited product journey begins. Never carry that
  // inert setup history into the product-journey ledger, but fail if any page
  // is still active or if the transient target ever navigated away from
  // about:blank. Any page created after this boundary remains an immediate
  // acceptance failure through the context-level page listener.
  const activeSecondaryPagesAtProductJourneyStart = page
    .context()
    .pages()
    .filter((candidatePage) => candidatePage !== page && !candidatePage.isClosed())
    .map((candidatePage) => candidatePage.url());
  const preJourneyPopupHistory = unexpectedPopupPages.map((popupRecord) => ({
    closed: popupRecord.page.isClosed(),
    observedMainFrameUrls: popupRecord.observedMainFrameUrls,
  }));
  expect(activeSecondaryPagesAtProductJourneyStart).toEqual([]);
  expect(preJourneyPopupHistory.length).toBeLessThanOrEqual(1);
  expect(popupHistoryIsInert(preJourneyPopupHistory)).toBe(true);
  unexpectedPopupPages.length = 0;

  type FrameHistorySnapshot = {
    detached: boolean;
    observedUrls: string[];
  };
  // Canonicalized from the query/hash-free failure evidence emitted by
  // Chromium 148 run 29493204761. That run remained DIAGNOSTIC_ONLY; this is
  // the source observation to be proven by the next exact-main run, not a
  // claim that terminal acceptance already passed.
  const expectedThirdPartyCookieFrameHistory: FrameHistorySnapshot = {
    detached: true,
    observedUrls: [
      'about:blank',
      `${issuerOrigin}${issuerPath}/protocol/openid-connect/3p-cookies/step1.html`,
      `${issuerOrigin}${issuerPath}/protocol/openid-connect/3p-cookies/step2.html`,
    ],
  };
  const expectedSilentCheckFrameHistory: FrameHistorySnapshot = {
    detached: true,
    observedUrls: ['about:blank', `${appOrigin}/silent-check-sso.html`],
  };
  const canonicalizeFrameHistory = (history: FrameHistorySnapshot[]) =>
    history
      .map(({ detached, observedUrls }) => ({
        detached,
        observedUrls: [...observedUrls],
      }))
      .sort((left, right) => {
        const leftKey = left.observedUrls.join('\n');
        const rightKey = right.observedUrls.join('\n');
        return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
      });
  const expectedPreJourneyFrameHistory = canonicalizeFrameHistory([
    expectedThirdPartyCookieFrameHistory,
    expectedSilentCheckFrameHistory,
  ]);
  const allowedPreJourneyFrameUrls = new Set(
    expectedPreJourneyFrameHistory.flatMap(({ observedUrls }) => observedUrls),
  );
  const frameHistoryIsExpectedSetup = (history: FrameHistorySnapshot[]) =>
    JSON.stringify(canonicalizeFrameHistory(history)) ===
    JSON.stringify(expectedPreJourneyFrameHistory);

  // Exercise the actual primary-page frame lifecycle listener with a
  // network-free data: iframe. The exact setup policy must reject this frame
  // after detach, then only the identity-matched negative-control record is
  // removed before evaluating real authentication/setup history.
  await page.evaluate(() => {
    const negativeControlFrame = document.createElement('iframe');
    negativeControlFrame.dataset.testid = 'frame-ledger-negative-control';
    negativeControlFrame.src = 'data:text/html,frame-ledger-negative-control';
    document.body.append(negativeControlFrame);
  });
  const frameLedgerNegativeControlElement = await page
    .locator('iframe[data-testid="frame-ledger-negative-control"]')
    .elementHandle();
  if (!frameLedgerNegativeControlElement) {
    throw new Error('frame-ledger-negative-control-element-missing');
  }
  const frameLedgerNegativeControlFrame =
    await frameLedgerNegativeControlElement.contentFrame();
  if (!frameLedgerNegativeControlFrame) {
    throw new Error('frame-ledger-negative-control-frame-missing');
  }
  await frameLedgerNegativeControlFrame.waitForLoadState('load');
  await expect
    .poll(
      () =>
        frameLifecycleByFrame
          .get(frameLedgerNegativeControlFrame)
          ?.observedUrls.includes('data:') ?? false,
    )
    .toBe(true);
  await page.evaluate(() => {
    document
      .querySelector('iframe[data-testid="frame-ledger-negative-control"]')
      ?.remove();
  });
  await expect
    .poll(
      () =>
        frameLifecycleByFrame.get(frameLedgerNegativeControlFrame)?.detached ?? false,
    )
    .toBe(true);
  const frameLedgerNegativeControl = frameLifecycleByFrame.get(
    frameLedgerNegativeControlFrame,
  );
  if (!frameLedgerNegativeControl) {
    throw new Error('frame-ledger-negative-control-record-missing');
  }
  const frameLedgerNegativeControlIndex = frameLifecycleRecords.indexOf(
    frameLedgerNegativeControl,
  );
  if (frameLedgerNegativeControlIndex < 0) {
    throw new Error('frame-ledger-negative-control-index-missing');
  }
  frameLifecycleRecords.splice(frameLedgerNegativeControlIndex, 1);
  frameLifecycleByFrame.delete(frameLedgerNegativeControl.frame);
  expect(frameLedgerNegativeControl.detached).toBe(true);
  expect(frameLedgerNegativeControl.observedUrls).toContain('data:');
  expect(allowedPreJourneyFrameUrls.has('data:')).toBe(false);
  expect(
    frameHistoryIsExpectedSetup([
      {
        detached: frameLedgerNegativeControl.detached,
        observedUrls: frameLedgerNegativeControl.observedUrls,
      },
      {
        detached: true,
        observedUrls: [...expectedThirdPartyCookieFrameHistory.observedUrls],
      },
    ]),
  ).toBe(false);

  const activeChildFramesAtProductJourneyStart = page
    .frames()
    .filter((frame) => frame !== page.mainFrame())
    .map((frame) => normalizeFrameUrl(frame.url()));
  const preJourneyFrameHistory = frameLifecycleRecords.map((record) => ({
    detached: record.detached,
    observedUrls: record.observedUrls,
  }));
  expect(activeChildFramesAtProductJourneyStart).toEqual([]);
  expect(
    frameHistoryIsExpectedSetup(preJourneyFrameHistory),
    `unexpected sanitized pre-journey frame history: ${JSON.stringify(preJourneyFrameHistory)}`,
  ).toBe(true);
  frameLifecycleRecords.length = 0;
  frameLifecycleByFrame.clear();

  const productJourneyAuditStart = await page.evaluate(() => {
    const auditWindow = window as Window & {
      __p5BrowserAuditBeginProductJourney?: () => void;
      __p5PersistentMutationAuditBeginProductJourney?: () => void;
      __p5BrowserAuditSnapshot?: () => Record<string, unknown>;
      __p5PersistentMutationAuditSnapshot?: () => Record<string, unknown>;
    };
    auditWindow.__p5BrowserAuditBeginProductJourney?.();
    auditWindow.__p5PersistentMutationAuditBeginProductJourney?.();
    return {
      browser: auditWindow.__p5BrowserAuditSnapshot?.(),
      persistence: auditWindow.__p5PersistentMutationAuditSnapshot?.(),
    };
  });
  expect(productJourneyAuditStart.browser).toMatchObject({
    workerConstructionCount: 0,
    popupCreationCount: 0,
    filePickerInvocationCount: 0,
    networkChannelConstructionCount: 0,
    historyMutationCount: 0,
    hashChangeCount: 0,
    closedShadowRootAttemptCount: 0,
    unsafeDomInsertionCount: 0,
    productJourneyBegun: true,
    instrumentationFailureCount: 0,
  });
  expect(productJourneyAuditStart.persistence).toMatchObject({
    writeCount: 0,
    instrumentationFailureCount: 0,
    storageProxyCount: 2,
    productJourneyBegun: true,
  });

  const eventListenerCaptureLedgerProbe = await page.evaluate(() => {
    const probe = document.createElement('button');
    const listener = () => undefined;
    const count = () => {
      const snapshot = (
        window as Window & {
          __p5BrowserAuditSnapshot?: () => {
            actionTargets: Array<{
              target: EventTarget;
              listeners: Array<{ type: string; count: number }>;
            }>;
          };
        }
      ).__p5BrowserAuditSnapshot?.();
      return (
        snapshot?.actionTargets
          .find(({ target }) => target === probe)
          ?.listeners.find(({ type }) => type === 'click')?.count ?? 0
      );
    };
    probe.addEventListener('click', listener, false);
    probe.addEventListener('click', listener, true);
    const afterDistinctCaptureRegistrations = count();
    probe.removeEventListener('click', listener, false);
    const afterRemovingBubbleRegistration = count();
    probe.removeEventListener('click', listener, true);
    const afterRemovingBothRegistrations = count();
    return {
      afterDistinctCaptureRegistrations,
      afterRemovingBubbleRegistration,
      afterRemovingBothRegistrations,
    };
  });
  expect(eventListenerCaptureLedgerProbe).toEqual({
    afterDistinctCaptureRegistrations: 2,
    afterRemovingBubbleRegistration: 1,
    afterRemovingBothRegistrations: 0,
  });
  expect(unexpectedPopupPages).toEqual([]);
  expect(unexpectedWebSockets).toEqual([]);
  expect(unexpectedWorkers).toEqual([]);
  expect(frameLifecycleRecords).toEqual([]);
  expect(fileChooserEventCount).toBe(0);
  expect(downloadEventCount).toBe(0);
  expect(dialogEventCount).toBe(0);
  const productJourneyNetworkStart = applicationNetworkRequests.length;
  const productJourneyMutationStart = mutationRequestCount();

  const runtimeStatus = page.getByTestId('ats-runtime-status');
  await expect(runtimeStatus).toContainText('Canlı mülakat çalışma alanı bu dağıtımda hazır.');
  const runtimeReady = await runtimeStatus.isVisible();

  const capabilityCards = page.locator('article[data-testid^="ats-capability-"]');
  await expect(capabilityCards).toHaveCount(expectedCapabilityIds.length);
  const capabilityIds = await capabilityCards.evaluateAll((cards) =>
    cards.map((card) =>
      (card.getAttribute('data-testid') ?? '').replace(/^ats-capability-/, ''),
    ),
  );
  expect(capabilityIds).toEqual(expectedCapabilityIds);
  expect(await readInteractiveControlSignatures(hubSurface)).toEqual(
    expectedInitialHubControlSignatures,
  );

  const roleFilters = hubSurface.locator('button[data-testid^="ats-role-filter-"]');
  await expect(roleFilters).toHaveCount(expectedTargetRoleIds.length + 1);
  const targetRoleIds = (await roleFilters.evaluateAll((controls) =>
    controls.map((control) =>
      (control.getAttribute('data-testid') ?? '').replace(/^ats-role-filter-/, ''),
    ),
  )).filter((role) => role !== 'all');
  expect(targetRoleIds).toEqual(expectedTargetRoleIds);
  const readPressedRoleIds = () =>
    roleFilters.evaluateAll((controls) =>
      controls
        .filter((control) => control.getAttribute('aria-pressed') === 'true')
        .map((control) =>
          (control.getAttribute('data-testid') ?? '').replace(/^ats-role-filter-/, ''),
        ),
    );

  const roleCapabilityCounts: Record<string, number> = {};
  const roleCapabilityIds: Record<string, string[]> = {};
  for (const [roleId, expectedCount] of Object.entries(expectedRoleCapabilityCounts)) {
    const filter = page.getByTestId(`ats-role-filter-${roleId}`);
    await filter.focus();
    await expect(filter).toBeFocused();
    await page.keyboard.press('Space');
    await expect(filter).toHaveAttribute('aria-pressed', 'true');
    const pressedRoleIds = await readPressedRoleIds();
    expect(pressedRoleIds).toEqual([roleId]);
    await expect(capabilityCards).toHaveCount(expectedCount);
    roleCapabilityCounts[roleId] = await capabilityCards.count();
    const visibleIds = await capabilityCards.evaluateAll((cards) =>
      cards.map((card) =>
        (card.getAttribute('data-testid') ?? '').replace(/^ats-capability-/, ''),
      ),
    );
    expect(visibleIds).toEqual(
      expectedRoleCapabilityIds[roleId as keyof typeof expectedRoleCapabilityIds],
    );
    roleCapabilityIds[roleId] = visibleIds;
  }
  expect(roleCapabilityCounts).toEqual(expectedRoleCapabilityCounts);
  expect(roleCapabilityIds).toEqual(expectedRoleCapabilityIds);

  const candidateFilter = page.getByTestId('ats-role-filter-candidate');
  await candidateFilter.focus();
  await expect(candidateFilter).toBeFocused();
  await page.keyboard.press('Space');
  await expect(candidateFilter).toHaveAttribute('aria-pressed', 'true');
  expect(await readPressedRoleIds()).toEqual(['candidate']);
  const candidateBoundary = page.getByTestId('ats-candidate-role-boundary');
  await expect(candidateBoundary).toBeVisible();
  await expect(candidateBoundary).toContainText('Bu yönetici adresi adaya verilmez');
  const candidateBoundaryVisible = await candidateBoundary.isVisible();

  const cvImportCard = page.getByTestId('ats-capability-candidate-cv-pdf-import');
  await expect(cvImportCard).toBeVisible();
  await expect(cvImportCard).toContainText('Onay kapılı');
  await expect(cvImportCard).toContainText('yükleme kontrolü açılmaz');
  const cvImportInteractiveControlCount = await cvImportCard
    .locator(
      'button, a[href], input, select, textarea, [contenteditable="true"], [role="button"], [role="link"]',
    )
    .count();
  expect(cvImportInteractiveControlCount).toBe(1);
  const fileUploadControlCount = await hubSurface.locator('input[type="file"]').count();
  expect(fileUploadControlCount).toBe(0);

  function persistentMutationAuditInstaller() {
    const auditWindow = window as Window & {
      __p5PersistentMutationAuditSnapshot?: () => {
        writeCount: number;
        instrumentationFailureCount: number;
        storageProxyCount: number;
        productJourneyBegun: boolean;
      };
      __p5PersistentMutationAuditBeginProductJourney?: () => void;
    };
    let writeCount = 0;
    let storageProxyCount = 0;
    let productJourneyBegun = false;
    const instrumentationFailures: string[] = [];
    const recordWrite = () => {
      writeCount += 1;
    };
    Object.defineProperty(auditWindow, '__p5PersistentMutationAuditSnapshot', {
      configurable: false,
      writable: false,
      value: () => ({
        writeCount,
        instrumentationFailureCount: instrumentationFailures.length,
        storageProxyCount,
        productJourneyBegun,
      }),
    });
    Object.defineProperty(auditWindow, '__p5PersistentMutationAuditBeginProductJourney', {
      configurable: false,
      writable: false,
      value: () => {
        if (productJourneyBegun) {
          instrumentationFailures.push('product-journey-reset-repeated');
          return;
        }
        writeCount = 0;
        productJourneyBegun = true;
      },
    });

    const installLockedMethod = (target: object, method: string, value: unknown) => {
      const descriptor = Object.getOwnPropertyDescriptor(target, method);
      if (descriptor && descriptor.configurable === false && descriptor.writable === false) {
        instrumentationFailures.push(method);
        return;
      }
      Object.defineProperty(target, method, {
        configurable: false,
        writable: false,
        value,
      });
    };
    const wrapMutation = (target: object | undefined, method: string, label: string) => {
      if (!target) return;
      const record = target as Record<string, unknown>;
      const original = record[method];
      if (typeof original !== 'function') return;
      installLockedMethod(
        target,
        method,
        function wrappedMutation(this: unknown, ...args: unknown[]) {
          void label;
          recordWrite();
          return Reflect.apply(original, this, args);
        },
      );
    };
    const wrapConditionalMutation = (
      target: object | undefined,
      method: string,
      label: string,
      isMutation: (args: unknown[]) => boolean,
    ) => {
      if (!target) return;
      const record = target as Record<string, unknown>;
      const original = record[method];
      if (typeof original !== 'function') return;
      installLockedMethod(
        target,
        method,
        function wrappedConditionalMutation(this: unknown, ...args: unknown[]) {
          void label;
          if (isMutation(args)) recordWrite();
          return Reflect.apply(original, this, args);
        },
      );
    };
    const wrapIndexedDbOpenMutation = () => {
      const original = IDBFactory.prototype.open;
      installLockedMethod(
        IDBFactory.prototype,
        'open',
        function wrappedIndexedDbOpen(
          this: IDBFactory,
          ...args: Parameters<IDBFactory['open']>
        ) {
          const request = Reflect.apply(original, this, args) as IDBOpenDBRequest;
          request.addEventListener('upgradeneeded', recordWrite, { once: true });
          return request;
        },
      );
    };

    wrapMutation(Storage.prototype, 'setItem', 'storage.setItem');
    wrapMutation(Storage.prototype, 'removeItem', 'storage.removeItem');
    wrapMutation(Storage.prototype, 'clear', 'storage.clear');
    const installStorageProxy = (property: 'localStorage' | 'sessionStorage') => {
      // Chromium does not guarantee that the WebIDL accessor is an own
      // property of the first object returned by Object.getPrototypeOf(window).
      // Resolve the actual descriptor owner instead of assuming a fixed
      // prototype depth; otherwise the audit silently loses coverage when the
      // browser changes its Window prototype layout.
      let descriptorOwner: object | null = window;
      let nativeDescriptor: PropertyDescriptor | undefined;
      while (descriptorOwner) {
        nativeDescriptor = Object.getOwnPropertyDescriptor(descriptorOwner, property);
        if (nativeDescriptor) break;
        descriptorOwner = Object.getPrototypeOf(descriptorOwner) as object | null;
      }
      if (
        !descriptorOwner ||
        !nativeDescriptor?.get ||
        nativeDescriptor.configurable !== true
      ) {
        instrumentationFailures.push(`${property}.native-getter`);
        return;
      }
      const nativeStorage = nativeDescriptor.get.call(window) as Storage;
      const proxy = new Proxy(nativeStorage, {
        get(target, key) {
          const value = Reflect.get(target, key, target);
          return typeof value === 'function' ? value.bind(target) : value;
        },
        set(target, key, value) {
          recordWrite();
          return Reflect.set(target, key, value, target);
        },
        deleteProperty(target, key) {
          recordWrite();
          return Reflect.deleteProperty(target, key);
        },
        defineProperty(target, key, descriptor) {
          recordWrite();
          return Reflect.defineProperty(target, key, descriptor);
        },
      });
      try {
        Object.defineProperty(descriptorOwner, property, {
          configurable: false,
          enumerable: nativeDescriptor.enumerable,
          get(this: Window) {
            if (this === window) return proxy;
            return nativeDescriptor.get?.call(this) as Storage;
          },
        });
        storageProxyCount += 1;
      } catch {
        instrumentationFailures.push(`${property}.proxy`);
      }
    };
    installStorageProxy('localStorage');
    installStorageProxy('sessionStorage');
    wrapMutation(IDBObjectStore.prototype, 'add', 'indexeddb.add');
    wrapMutation(IDBObjectStore.prototype, 'put', 'indexeddb.put');
    wrapMutation(IDBObjectStore.prototype, 'delete', 'indexeddb.delete');
    wrapMutation(IDBObjectStore.prototype, 'clear', 'indexeddb.clear');
    wrapMutation(IDBCursor.prototype, 'update', 'indexeddb.cursor.update');
    wrapMutation(IDBCursor.prototype, 'delete', 'indexeddb.cursor.delete');
    wrapMutation(IDBDatabase.prototype, 'createObjectStore', 'indexeddb.createObjectStore');
    wrapMutation(IDBDatabase.prototype, 'deleteObjectStore', 'indexeddb.deleteObjectStore');
    wrapIndexedDbOpenMutation();
    wrapMutation(IDBFactory.prototype, 'deleteDatabase', 'indexeddb.deleteDatabase');
    wrapMutation(Cache.prototype, 'add', 'cache.add');
    wrapMutation(Cache.prototype, 'addAll', 'cache.addAll');
    wrapMutation(Cache.prototype, 'put', 'cache.put');
    wrapMutation(Cache.prototype, 'delete', 'cache.delete');
    wrapMutation(CacheStorage.prototype, 'delete', 'cacheStorage.delete');

    const runtime = globalThis as unknown as Record<string, { prototype?: object } | undefined>;
    wrapMutation(runtime.CookieStore?.prototype, 'set', 'cookieStore.set');
    wrapMutation(runtime.CookieStore?.prototype, 'delete', 'cookieStore.delete');
    wrapMutation(runtime.FileSystemFileHandle?.prototype, 'createWritable', 'opfs.createWritable');
    wrapMutation(
      runtime.FileSystemFileHandle?.prototype,
      'createSyncAccessHandle',
      'opfs.createSyncAccessHandle',
    );
    wrapMutation(runtime.FileSystemWritableFileStream?.prototype, 'write', 'opfs.write');
    wrapMutation(runtime.FileSystemWritableFileStream?.prototype, 'truncate', 'opfs.truncate');
    wrapMutation(runtime.FileSystemSyncAccessHandle?.prototype, 'write', 'opfs.sync.write');
    wrapMutation(runtime.FileSystemSyncAccessHandle?.prototype, 'truncate', 'opfs.sync.truncate');
    wrapMutation(runtime.FileSystemDirectoryHandle?.prototype, 'removeEntry', 'opfs.removeEntry');
    wrapConditionalMutation(
      runtime.FileSystemDirectoryHandle?.prototype,
      'getFileHandle',
      'opfs.createFile',
      (args) => Boolean((args[1] as { create?: boolean } | undefined)?.create),
    );
    wrapConditionalMutation(
      runtime.FileSystemDirectoryHandle?.prototype,
      'getDirectoryHandle',
      'opfs.createDirectory',
      (args) => Boolean((args[1] as { create?: boolean } | undefined)?.create),
    );
    wrapMutation(runtime.FileSystemHandle?.prototype, 'remove', 'opfs.remove');
    wrapMutation(runtime.FileSystemHandle?.prototype, 'move', 'opfs.move');

    const cookieDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (cookieDescriptor?.configurable && cookieDescriptor.get && cookieDescriptor.set) {
      Object.defineProperty(Document.prototype, 'cookie', {
        configurable: true,
        enumerable: cookieDescriptor.enumerable,
        get: cookieDescriptor.get,
        set(this: Document, value: string) {
          recordWrite();
          cookieDescriptor.set?.call(this, value);
        },
      });
      Object.defineProperty(Document.prototype, 'cookie', {
        ...Object.getOwnPropertyDescriptor(Document.prototype, 'cookie'),
        configurable: false,
      });
    } else {
      instrumentationFailures.push('document.cookie');
    }
  }

  const browserAuditSnapshot = () =>
    page.evaluate(() => {
      const snapshot = (
        window as Window & {
          __p5BrowserAuditSnapshot?: () => {
            workerConstructionCount: number;
            popupCreationCount: number;
            filePickerInvocationCount: number;
            networkChannelConstructionCount: number;
            networkChannelConstructionTypes: string[];
            historyMutationCount: number;
            hashChangeCount: number;
            closedShadowRootAttemptCount: number;
            unsafeDomInsertionCount: number;
            productJourneyBegun: boolean;
            instrumentationFailureCount: number;
            actionTargets: Array<{
              target: EventTarget;
              listeners: Array<{ type: string; count: number }>;
            }>;
          };
        }
      ).__p5BrowserAuditSnapshot?.();
      return snapshot
        ? {
            workerConstructionCount: snapshot.workerConstructionCount,
            popupCreationCount: snapshot.popupCreationCount,
            filePickerInvocationCount: snapshot.filePickerInvocationCount,
            networkChannelConstructionCount: snapshot.networkChannelConstructionCount,
            networkChannelConstructionTypes: snapshot.networkChannelConstructionTypes,
            historyMutationCount: snapshot.historyMutationCount,
            hashChangeCount: snapshot.hashChangeCount,
            closedShadowRootAttemptCount: snapshot.closedShadowRootAttemptCount,
            unsafeDomInsertionCount: snapshot.unsafeDomInsertionCount,
            productJourneyBegun: snapshot.productJourneyBegun,
            instrumentationFailureCount: snapshot.instrumentationFailureCount,
          }
        : null;
    });
  const workerConstructionCount = async () =>
    (await browserAuditSnapshot())?.workerConstructionCount ?? -1;
  const popupCreationCount = async () =>
    (await browserAuditSnapshot())?.popupCreationCount ?? -1;
  const filePickerInvocationCount = async () =>
    (await browserAuditSnapshot())?.filePickerInvocationCount ?? -1;
  const networkChannelConstructionCount = async () =>
    (await browserAuditSnapshot())?.networkChannelConstructionCount ?? -1;
  const crossPageCreationCount = async () =>
    (await popupCreationCount()) + unexpectedPopupPages.length;
  const unsafeDelegatedActionListenerCount = () =>
    page.evaluate(() => {
      const snapshot = (
        window as Window & {
          __p5BrowserAuditSnapshot?: () => {
            actionTargets: Array<{
              target: EventTarget;
              listeners: Array<{ type: string; count: number }>;
            }>;
          };
        }
      ).__p5BrowserAuditSnapshot?.();
      const pointerOrMutationEvents = new Set([
        'auxclick',
        'beforeinput',
        'change',
        'click',
        'contextmenu',
        'dblclick',
        'dragend',
        'dragstart',
        'drop',
        'input',
        'keydown',
        'keypress',
        'keyup',
        'mousedown',
        'mouseup',
        'pointerdown',
        'pointerup',
        'submit',
        'touchend',
        'touchstart',
      ]);
      let count = 0;
      for (const { target, listeners } of snapshot?.actionTargets ?? []) {
        const isReactDelegationRoot =
          target instanceof Element &&
          Object.getOwnPropertyNames(target).some(
            (key) => key === '_reactRootContainer' || key.startsWith('__reactContainer$'),
          );
        if (isReactDelegationRoot) {
          continue;
        }
        for (const listener of listeners) {
          if (pointerOrMutationEvents.has(listener.type)) count += listener.count;
        }
      }
      return count;
    });

  const persistentAuditSnapshot = () =>
    page.evaluate(() =>
      (
        window as Window & {
          __p5PersistentMutationAuditSnapshot?: () => {
            writeCount: number;
            instrumentationFailureCount: number;
            storageProxyCount: number;
            productJourneyBegun: boolean;
          };
        }
      ).__p5PersistentMutationAuditSnapshot?.(),
    );
  const persistentWriteCount = async () =>
    (await persistentAuditSnapshot())?.writeCount ?? -1;
  const persistentStateSnapshot = () =>
    page.evaluate(async () => {
      const sha256 = async (value: string | ArrayBuffer) => {
        const bytes =
          typeof value === 'string' ? new TextEncoder().encode(value) : new Uint8Array(value);
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join(
          '',
        );
      };
      let nextReference = 1;
      const normalizeValue = async (
        value: unknown,
        seen = new WeakMap<object, number>(),
      ): Promise<unknown> => {
        if (
          value === null ||
          value === undefined ||
          typeof value === 'string' ||
          typeof value === 'number' ||
          typeof value === 'boolean'
        ) {
          return value ?? null;
        }
        if (typeof value === 'bigint') return `bigint:${value.toString()}`;
        if (typeof value !== 'object') return String(value);
        const existingReference = seen.get(value);
        if (existingReference !== undefined) return { reference: existingReference };
        const reference = nextReference;
        nextReference += 1;
        seen.set(value, reference);
        if (value instanceof Blob) {
          return {
            reference,
            blobSize: value.size,
            blobType: value.type,
            blobSha256: await sha256(await value.arrayBuffer()),
          };
        }
        if (value instanceof ArrayBuffer) {
          return { reference, arrayBufferSha256: await sha256(value) };
        }
        if (ArrayBuffer.isView(value)) {
          const bytes = Uint8Array.from(
            new Uint8Array(value.buffer, value.byteOffset, value.byteLength),
          ).buffer;
          return { reference, typedArray: value.constructor.name, sha256: await sha256(bytes) };
        }
        if (value instanceof Date) return { reference, date: value.toISOString() };
        if (value instanceof RegExp) return { reference, regexp: value.toString() };
        if (value instanceof Map) {
          const entries = [];
          for (const [key, item] of value.entries()) {
            entries.push([
              await normalizeValue(key, seen),
              await normalizeValue(item, seen),
            ]);
          }
          entries.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
          return { reference, map: entries };
        }
        if (value instanceof Set) {
          const items = [];
          for (const item of value.values()) items.push(await normalizeValue(item, seen));
          items.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
          return { reference, set: items };
        }
        if (Array.isArray(value)) {
          return {
            reference,
            array: await Promise.all(value.map((item) => normalizeValue(item, seen))),
          };
        }
        const normalized: Record<string, unknown> = { reference };
        for (const key of Object.keys(value as Record<string, unknown>).sort()) {
          normalized[key] = await normalizeValue(
            (value as Record<string, unknown>)[key],
            seen,
          );
        }
        return normalized;
      };
      const stableJson = (value: unknown) => JSON.stringify(value) ?? 'undefined';
      const storageSnapshot = async (storage: Storage) => {
        const entries =
        Array.from({ length: storage.length }, (_, index) => {
          const key = storage.key(index) ?? '';
          return [key, storage.getItem(key) ?? ''] as const;
        }).sort(([left], [right]) => left.localeCompare(right));
        return { count: entries.length, sha256: await sha256(stableJson(entries)) };
      };
      const requestValue = <T,>(request: IDBRequest<T>) =>
        new Promise<T>((resolve, reject) => {
          request.addEventListener('success', () => resolve(request.result), { once: true });
          request.addEventListener('error', () => reject(request.error), { once: true });
        });
      const databaseSnapshots = [];
      for (const databaseInfo of (await window.indexedDB.databases()).sort((left, right) =>
        (left.name ?? '').localeCompare(right.name ?? ''),
      )) {
        const name = databaseInfo.name ?? '';
        if (!name) continue;
        const database = await requestValue(window.indexedDB.open(name));
        const stores = [];
        for (const storeName of Array.from(database.objectStoreNames).sort()) {
          const transaction = database.transaction(storeName, 'readonly');
          const objectStore = transaction.objectStore(storeName);
          const [keys, values] = await Promise.all([
            requestValue(objectStore.getAllKeys()),
            requestValue(objectStore.getAll()),
          ]);
          stores.push({
            name: storeName,
            recordCount: values.length,
            sha256: await sha256(stableJson(await normalizeValue({ keys, values }))),
          });
        }
        database.close();
        databaseSnapshots.push({
          name,
          version: databaseInfo.version ?? 0,
          stores,
        });
      }
      const cacheSnapshots = [];
      for (const cacheName of (await window.caches.keys()).sort()) {
        const cache = await window.caches.open(cacheName);
        const entries = [];
        for (const request of Array.from(await cache.keys()).sort((left, right) =>
          left.url.localeCompare(right.url),
        )) {
          const response = await cache.match(request);
          entries.push({
            method: request.method,
            urlSha256: await sha256(request.url),
            status: response?.status ?? 0,
            bodySha256: response ? await sha256(await response.clone().arrayBuffer()) : '',
          });
        }
        cacheSnapshots.push({ nameSha256: await sha256(cacheName), entries });
      }
      const opfsSnapshots: Array<{
        pathSha256: string;
        kind: 'directory' | 'file';
        size?: number;
        bodySha256?: string;
      }> = [];
      const storageWithDirectory = navigator.storage as StorageManager & {
        getDirectory?: () => Promise<FileSystemDirectoryHandle>;
      };
      if (typeof storageWithDirectory.getDirectory === 'function') {
        const visitDirectory = async (directory: FileSystemDirectoryHandle, prefix: string) => {
          const iterableDirectory = directory as FileSystemDirectoryHandle & {
            entries(): AsyncIterableIterator<[string, FileSystemHandle]>;
          };
          for await (const [name, handle] of iterableDirectory.entries()) {
            const path = prefix ? `${prefix}/${name}` : name;
            if (handle.kind === 'directory') {
              opfsSnapshots.push({ pathSha256: await sha256(path), kind: 'directory' });
              await visitDirectory(handle as FileSystemDirectoryHandle, path);
            } else {
              const file = await (handle as FileSystemFileHandle).getFile();
              opfsSnapshots.push({
                pathSha256: await sha256(path),
                kind: 'file',
                size: file.size,
                bodySha256: await sha256(await file.arrayBuffer()),
              });
            }
          }
        };
        await visitDirectory(await storageWithDirectory.getDirectory(), '');
        opfsSnapshots.sort((left, right) => left.pathSha256.localeCompare(right.pathSha256));
      }
      return {
        local: await storageSnapshot(window.localStorage),
        session: await storageSnapshot(window.sessionStorage),
        indexedDb: databaseSnapshots,
        caches: cacheSnapshots,
        opfs: opfsSnapshots,
        cookieSha256: await sha256(document.cookie),
      };
    });
  type CdpDomNode = {
    shadowRootType?: string;
    children?: CdpDomNode[];
    shadowRoots?: CdpDomNode[];
    contentDocument?: CdpDomNode;
    templateContent?: CdpDomNode;
  };
  const cdpSession = await page.context().newCDPSession(page);
  let mobileTouchActivationCount = 0;
  const activateByTouch = async (control: Locator) => {
    await control.scrollIntoViewIfNeeded();
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    const x = (box?.x ?? 0) + (box?.width ?? 0) / 2;
    const y = (box?.y ?? 0) + (box?.height ?? 0) / 2;
    await cdpSession.send('Input.dispatchTouchEvent', {
      type: 'touchStart',
      touchPoints: [{ x, y, radiusX: 2, radiusY: 2, force: 1 }],
    });
    await cdpSession.send('Input.dispatchTouchEvent', {
      type: 'touchEnd',
      touchPoints: [],
    });
    mobileTouchActivationCount += 1;
  };
  const closedShadowRootCount = async () => {
    const documentSnapshot = (await cdpSession.send('DOM.getDocument', {
      depth: -1,
      pierce: true,
    })) as { root: CdpDomNode };
    const countNode = (node: CdpDomNode): number =>
      (node.shadowRootType === 'closed' ? 1 : 0) +
      (node.children ?? []).reduce((count, child) => count + countNode(child), 0) +
      (node.shadowRoots ?? []).reduce((count, child) => count + countNode(child), 0) +
      (node.contentDocument ? countNode(node.contentDocument) : 0) +
      (node.templateContent ? countNode(node.templateContent) : 0);
    return countNode(documentSnapshot.root);
  };
  const assertNoExternalProductSurface = async () => {
    expect(
      await page
        .locator(
          'input[type="file"], iframe, frame, portal, [target="_blank"], [formtarget="_blank"]',
        )
        .count(),
    ).toBe(0);
    expect(await closedShadowRootCount()).toBe(0);
  };
  const initialBrowserAudit = await browserAuditSnapshot();
  expect(initialBrowserAudit?.instrumentationFailureCount).toBe(0);
  expect(initialBrowserAudit?.productJourneyBegun).toBe(true);
  expect(initialBrowserAudit).toMatchObject({
    workerConstructionCount: 0,
    popupCreationCount: 0,
    filePickerInvocationCount: 0,
    networkChannelConstructionCount: 0,
    networkChannelConstructionTypes: [],
    historyMutationCount: 0,
    hashChangeCount: 0,
    closedShadowRootAttemptCount: 0,
    unsafeDomInsertionCount: 0,
  });
  const initialPersistentAudit = await persistentAuditSnapshot();
  expect(initialPersistentAudit?.instrumentationFailureCount).toBe(0);
  expect(initialPersistentAudit?.storageProxyCount).toBe(2);
  expect(initialPersistentAudit?.productJourneyBegun).toBe(true);
  expect(initialPersistentAudit?.writeCount).toBe(0);

  const readJourneyLifecycleAudit = async (networkStart: number, mutationStart: number) => {
    await page.waitForTimeout(2_000);
    const browser = await browserAuditSnapshot();
    const persistence = await persistentAuditSnapshot();
    expect(browser).not.toBeNull();
    expect(persistence).toBeDefined();
    const audit = {
      persistentWriteOperationCount: persistence?.writeCount ?? -1,
      networkRequestCount: applicationNetworkRequests.length - networkStart,
      mutationRequestCount: mutationRequestCount() - mutationStart,
      networkChannelConstructionCount: browser?.networkChannelConstructionCount ?? -1,
      workerConstructionCount: browser?.workerConstructionCount ?? -1,
      popupCreationCount: (browser?.popupCreationCount ?? -1) + unexpectedPopupPages.length,
      filePickerInvocationCount: browser?.filePickerInvocationCount ?? -1,
      historyMutationCount: browser?.historyMutationCount ?? -1,
      hashChangeCount: browser?.hashChangeCount ?? -1,
      closedShadowRootAttemptCount: browser?.closedShadowRootAttemptCount ?? -1,
      unsafeDomInsertionCount: browser?.unsafeDomInsertionCount ?? -1,
      instrumentationFailureCount:
        (browser?.instrumentationFailureCount ?? -1) +
        (persistence?.instrumentationFailureCount ?? -1),
      webSocketEventCount: unexpectedWebSockets.length,
      workerEventCount: unexpectedWorkers.length,
      frameAttachmentCount: frameLifecycleRecords.length,
      fileChooserEventCount,
      downloadEventCount,
      dialogEventCount,
      unsafeDelegatedActionListenerCount: await unsafeDelegatedActionListenerCount(),
      activePageWorkerCount: page.workers().length,
      activeServiceWorkerCount: page.context().serviceWorkers().length,
      closedShadowRootCount: await closedShadowRootCount(),
    };
    for (const count of Object.values(audit)) expect(count).toBe(0);
    return audit;
  };

  const resumeFieldLabels = ['E-posta', 'Deneyim', 'Eğitim', 'Beceriler', 'Dil'] as const;
  const resumeClosedControls = ['BUTTON:button:Sentetik PDF taslak akışını dene'].sort();
  const resumeOpenedControls = [
    'BUTTON:button:Sentetik taslak denemesini kapat',
    'BUTTON:button:Sentetik PDF örneğini işle',
  ].sort();
  const resumeBaseProcessedControls = [
    'BUTTON:button:Sentetik taslak denemesini kapat',
    ...Array.from({ length: expectedSyntheticResumeProposalCount }, () => 'INPUT::'),
    ...resumeFieldLabels.flatMap((label) => [
      `BUTTON:button:${label} alanını kabul et`,
      `BUTTON:button:${label} alanını reddet`,
    ]),
    'BUTTON:button:Seçtiğim alanları taslağa aktar (0)',
    'BUTTON:button:Tümünü reddet',
    'BUTTON:button:Denemeyi sıfırla',
  ].sort();
  const resumeEditedControls = resumeBaseProcessedControls
    .filter(
      (signature) =>
        signature !== 'BUTTON:button:E-posta alanını kabul et' &&
        signature !== 'BUTTON:button:E-posta alanını reddet',
    )
    .concat([
      'BUTTON:button:E-posta düzenlemesini kabul et',
      'BUTTON:button:E-posta düzenlemesini reddet',
    ])
    .sort();
  const resumeReviewedControls = [
    'BUTTON:button:Sentetik taslak denemesini kapat',
    ...Array.from({ length: expectedSyntheticResumeProposalCount }, () => 'INPUT::'),
    'BUTTON:button:Eğitim alanını kabul et',
    'BUTTON:button:Eğitim alanını reddet',
    'BUTTON:button:Dil alanını kabul et',
    'BUTTON:button:Dil alanını reddet',
    'BUTTON:button:Seçtiğim alanları taslağa aktar (2)',
    'BUTTON:button:Tümünü reddet',
    'BUTTON:button:Denemeyi sıfırla',
  ].sort();
  const resumeRejectArmedControls = resumeReviewedControls
    .filter((signature) => signature !== 'BUTTON:button:Tümünü reddet')
    .concat('BUTTON:button:Tümünü reddetmeyi onayla')
    .sort();
  const resumeAllRejectedControls = [
    'BUTTON:button:Sentetik taslak denemesini kapat',
    ...Array.from({ length: expectedSyntheticResumeProposalCount }, () => 'INPUT::'),
    'BUTTON:button:Seçtiğim alanları taslağa aktar (0)',
    'BUTTON:button:Tümünü reddet',
    'BUTTON:button:Denemeyi sıfırla',
  ].sort();
  let resumeCardControls = await readInteractiveControlSignatures(cvImportCard);
  expect(resumeCardControls).toEqual(resumeClosedControls);
  let resumeDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
  const advanceResumeControlState = async (expectedControls: string[]) => {
    const nextCardControls = await readInteractiveControlSignatures(cvImportCard);
    expect(nextCardControls).toEqual(expectedControls);
    const nextDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
    expect(nextDocumentControls).toEqual(
      replaceSignatureMultiset(resumeDocumentControls, resumeCardControls, expectedControls),
    );
    resumeCardControls = nextCardControls;
    resumeDocumentControls = nextDocumentControls;
    await assertNoExternalProductSurface();
    expect(await unsafeDelegatedActionListenerCount()).toBe(0);
  };
  await assertNoExternalProductSurface();
  const persistentStateBeforeResume = await persistentStateSnapshot();
  const resumePersistentWriteStart = await persistentWriteCount();
  const resumeNetworkStart = applicationNetworkRequests.length;
  const resumeMutationStart = mutationRequestCount();
  const resumeWorkerConstructionStart = await workerConstructionCount();
  const resumePopupCreationStart = await crossPageCreationCount();
  const resumeFilePickerInvocationStart = await filePickerInvocationCount();
  const resumeNetworkChannelConstructionStart = await networkChannelConstructionCount();
  expect(resumeWorkerConstructionStart).toBe(0);
  expect(resumePopupCreationStart).toBe(0);
  expect(page.workers()).toHaveLength(0);
  expect(page.context().serviceWorkers()).toHaveLength(0);
  expect(await hubSurface.locator('[target="_blank"], [formtarget="_blank"]').count()).toBe(0);
  expect(await hubSurface.locator('iframe, frame').count()).toBe(0);
  const resumeUnsafeDelegatedActionListenerCountBefore =
    await unsafeDelegatedActionListenerCount();
  expect(resumeUnsafeDelegatedActionListenerCountBefore).toBe(0);

  const resumeDemoButton = cvImportCard.getByRole('button', {
    name: 'Sentetik PDF taslak akışını dene',
  });
  await resumeDemoButton.focus();
  await expect(resumeDemoButton).toBeFocused();
  await page.keyboard.press('Enter');
  await advanceResumeControlState(resumeOpenedControls);
  const resumeProcessButton = page.getByTestId('ats-synthetic-resume-process');
  await expect(resumeProcessButton).toBeVisible();
  await resumeProcessButton.focus();
  await page.keyboard.press('Enter');
  await advanceResumeControlState(resumeBaseProcessedControls);

  const resumeProposals = page.getByTestId('ats-synthetic-resume-proposals');
  const resumeFields = resumeProposals.locator('article[data-testid^="ats-resume-field-"]');
  await expect(resumeFields).toHaveCount(expectedSyntheticResumeProposalCount);
  const proposalCount = await resumeFields.count();
  const invalidFixtureCount = await resumeProposals.locator('input').evaluateAll((inputs) =>
    inputs.filter(
      (input) => input instanceof HTMLInputElement && input.value.endsWith('@example.invalid'),
    ).length,
  );
  expect(invalidFixtureCount).toBe(1);

  const emailField = page.getByTestId('ats-resume-field-contact-email');
  const emailInput = emailField.getByLabel('E-posta');
  await expect(emailInput).not.toHaveAttribute('readonly');
  await emailInput.selectText();
  await emailInput.pressSequentially('a');
  const editableAfterFirstKeystroke = (await emailInput.getAttribute('readonly')) === null;
  expect(editableAfterFirstKeystroke).toBe(true);
  await emailInput.pressSequentially('day.duzenlendi@example.invalid');
  await expect(emailInput).toHaveValue(expectedEditedEmail);
  await advanceResumeControlState(resumeEditedControls);
  const editedEmail = await emailInput.inputValue();
  const acceptAfterEdit = emailField.getByRole('button', {
    name: 'E-posta düzenlemesini kabul et',
  });
  const rejectAfterEdit = emailField.getByRole('button', {
    name: 'E-posta düzenlemesini reddet',
  });
  await expect(acceptAfterEdit).toBeVisible();
  await expect(rejectAfterEdit).toBeVisible();
  const acceptAfterEditVisible = await acceptAfterEdit.isVisible();
  const rejectAfterEditVisible = await rejectAfterEdit.isVisible();
  await activateByKeyboard(acceptAfterEdit, 'Space');
  await expect(emailInput).toHaveAttribute('readonly');
  await expect(emailField).toContainText('Kabul edildi');

  await activateByKeyboard(
    page
      .getByTestId('ats-resume-field-skills')
      .getByRole('button', { name: 'Beceriler alanını kabul et' }),
    'Space',
  );
  await activateByKeyboard(
    page
      .getByTestId('ats-resume-field-experience')
      .getByRole('button', { name: 'Deneyim alanını reddet' }),
    'Space',
  );
  await advanceResumeControlState(resumeReviewedControls);

  const transferSelected = page.getByTestId('ats-resume-transfer-selected');
  await expect(transferSelected).toContainText('(2)');
  await activateByKeyboard(transferSelected, 'Space');
  await advanceResumeControlState(resumeReviewedControls);
  const localDraft = page.getByTestId('ats-synthetic-resume-draft');
  await expect(localDraft).toBeVisible();
  await expect(localDraft).toContainText(expectedEditedEmail);
  await expect(localDraft).toContainText('Araştırma, erişilebilir ürün tasarımı');
  const acceptedDraftFieldCount = await localDraft.locator('dl > div').count();
  expect(acceptedDraftFieldCount).toBe(2);
  const localDraftVisible = await localDraft.isVisible();
  const localDraftContainsEditedEmail = (await localDraft.innerText()).includes(expectedEditedEmail);

  const rejectAll = cvImportCard.getByRole('button', { name: 'Tümünü reddet', exact: true });
  await activateByKeyboard(rejectAll, 'Space');
  const rejectAllAlert = cvImportCard.getByRole('alert');
  await expect(rejectAllAlert).toBeVisible();
  const rejectAllConfirm = cvImportCard.getByRole('button', {
    name: 'Tümünü reddetmeyi onayla',
  });
  await expect(rejectAllConfirm).toBeVisible();
  await advanceResumeControlState(resumeRejectArmedControls);
  const rejectAllSecondConfirmationRequired = await rejectAllConfirm.isVisible();
  expect(await emailField.innerText()).toContain('Kabul edildi');
  await activateByKeyboard(rejectAllConfirm, 'Space');
  for (const field of await resumeFields.all()) {
    await expect(field).toContainText('Reddedildi');
  }
  await expect(localDraft).toHaveCount(0);
  const rejectAllApplied =
    (await resumeFields.filter({ hasText: 'Reddedildi' }).count()) ===
    expectedSyntheticResumeProposalCount;
  expect(rejectAllApplied).toBe(true);
  await advanceResumeControlState(resumeAllRejectedControls);

  await activateByKeyboard(
    cvImportCard.getByRole('button', { name: 'Denemeyi sıfırla' }),
    'Space',
  );
  await expect(page.getByTestId('ats-synthetic-resume-process')).toBeVisible();
  await expect(page.getByTestId('ats-synthetic-resume-proposals')).toHaveCount(0);
  await advanceResumeControlState(resumeOpenedControls);
  const resetReturnedToStart = await page.getByTestId('ats-synthetic-resume-process').isVisible();
  await activateByKeyboard(
    cvImportCard.getByRole('button', { name: 'Sentetik taslak denemesini kapat' }),
    'Space',
  );
  await advanceResumeControlState(resumeClosedControls);
  await page.waitForTimeout(mutationQuietPeriodMs);
  const persistentStateAfterResume = await persistentStateSnapshot();
  const persistentStoresUnchanged =
    JSON.stringify(persistentStateBeforeResume) === JSON.stringify(persistentStateAfterResume);
  expect(persistentStoresUnchanged).toBe(true);
  const resumePersistentWriteOperationCount =
    (await persistentWriteCount()) - resumePersistentWriteStart;
  expect(resumePersistentWriteOperationCount).toBe(0);
  const resumeNetworkRequestCount = applicationNetworkRequests.length - resumeNetworkStart;
  expect(resumeNetworkRequestCount).toBe(0);
  const resumeMutationRequestCount = mutationRequestCount() - resumeMutationStart;
  expect(resumeMutationRequestCount).toBe(0);
  const resumeWorkerConstructionCount =
    (await workerConstructionCount()) - resumeWorkerConstructionStart;
  expect(resumeWorkerConstructionCount).toBe(0);
  const resumePopupCreationCount =
    (await crossPageCreationCount()) - resumePopupCreationStart;
  expect(resumePopupCreationCount).toBe(0);
  const resumeFilePickerInvocationCount =
    (await filePickerInvocationCount()) - resumeFilePickerInvocationStart;
  expect(resumeFilePickerInvocationCount).toBe(0);
  const resumeNetworkChannelConstructionCount =
    (await networkChannelConstructionCount()) - resumeNetworkChannelConstructionStart;
  expect(resumeNetworkChannelConstructionCount).toBe(0);
  const resumeUnsafeDelegatedActionListenerCountAfter =
    await unsafeDelegatedActionListenerCount();
  expect(resumeUnsafeDelegatedActionListenerCountAfter).toBe(0);
  const resumeUnsafeDelegatedActionListenerCount = Math.max(
    resumeUnsafeDelegatedActionListenerCountBefore,
    resumeUnsafeDelegatedActionListenerCountAfter,
  );
  expect(await hubSurface.locator('input[type="file"]').count()).toBe(0);

  const allRolesFilter = page.getByTestId('ats-role-filter-all');
  await allRolesFilter.focus();
  await page.keyboard.press('Space');
  await expect(allRolesFilter).toHaveAttribute('aria-pressed', 'true');
  expect(await readPressedRoleIds()).toEqual(['all']);
  await expect(capabilityCards).toHaveCount(expectedCapabilityIds.length);

  const safeScenarioPersistentStateBefore = await persistentStateSnapshot();
  const safeScenarioPersistentWriteStart = await persistentWriteCount();
  const safeScenarioNetworkStart = applicationNetworkRequests.length;
  const safeScenarioMutationStart = mutationRequestCount();
  const safeScenarioWorkerStart = await workerConstructionCount();
  const safeScenarioPopupStart = await crossPageCreationCount();
  const safeScenarioFilePickerStart = await filePickerInvocationCount();
  const safeScenarioNetworkChannelStart = await networkChannelConstructionCount();
  const safeScenarioUnsafeDelegatedBefore = await unsafeDelegatedActionListenerCount();
  expect(safeScenarioUnsafeDelegatedBefore).toBe(0);
  const completedSafeScenarioCapabilityIds: string[] = [];
  for (const [capabilityId, journey] of Object.entries(expectedSafeScenarioJourneys)) {
    const card = page.getByTestId(`ats-capability-${capabilityId}`);
    const closedControls = [`BUTTON:button:${journey.action}`].sort();
    const openedControls = [
      'BUTTON:button:Güvenli denemeyi kapat',
      'BUTTON:button:Sentetik çıktıyı üret',
    ].sort();
    const completedControls = [
      'BUTTON:button:Güvenli denemeyi kapat',
      'BUTTON:button:Denemeyi sıfırla',
    ].sort();
    expect(await readInteractiveControlSignatures(card)).toEqual(closedControls);
    const closedDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
    await activateByKeyboard(card.getByRole('button', { name: journey.action }), 'Space');
    expect(await readInteractiveControlSignatures(card)).toEqual(openedControls);
    const openedDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
    expect(openedDocumentControls).toEqual(
      replaceSignatureMultiset(closedDocumentControls, closedControls, openedControls),
    );
    await assertNoExternalProductSurface();
    await activateByKeyboard(page.getByTestId(`ats-safe-run-${capabilityId}`), 'Space');
    await expect(card).toContainText(journey.scenario);
    await expect(card).toContainText(journey.output);
    await expect(card).toContainText(journey.boundary);
    await expect(card).toContainText(
      'Bu deneme tarayıcı belleğinde çalıştı; ağ isteği, kayıt, bildirim veya karar üretilmedi.',
    );
    expect(await readInteractiveControlSignatures(card)).toEqual(completedControls);
    const completedDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
    expect(completedDocumentControls).toEqual(
      replaceSignatureMultiset(openedDocumentControls, openedControls, completedControls),
    );
    await assertNoExternalProductSurface();
    await activateByKeyboard(card.getByRole('button', { name: 'Denemeyi sıfırla' }), 'Space');
    expect(await readInteractiveControlSignatures(card)).toEqual(openedControls);
    expect(await readInteractiveControlSignatures(page.locator('body'))).toEqual(
      openedDocumentControls,
    );
    await assertNoExternalProductSurface();
    await activateByKeyboard(
      card.getByRole('button', { name: 'Güvenli denemeyi kapat' }),
      'Space',
    );
    expect(await readInteractiveControlSignatures(card)).toEqual(closedControls);
    expect(await readInteractiveControlSignatures(page.locator('body'))).toEqual(
      closedDocumentControls,
    );
    await assertNoExternalProductSurface();
    completedSafeScenarioCapabilityIds.push(capabilityId);
  }
  expect(completedSafeScenarioCapabilityIds).toEqual(Object.keys(expectedSafeScenarioJourneys));
  await page.waitForTimeout(mutationQuietPeriodMs);
  const safeScenarioPersistentStateAfter = await persistentStateSnapshot();
  const safeScenarioPersistentStoresUnchanged =
    JSON.stringify(safeScenarioPersistentStateBefore) ===
    JSON.stringify(safeScenarioPersistentStateAfter);
  expect(safeScenarioPersistentStoresUnchanged).toBe(true);
  const safeScenarioPersistentWriteOperationCount =
    (await persistentWriteCount()) - safeScenarioPersistentWriteStart;
  const safeScenarioNetworkRequestCount =
    applicationNetworkRequests.length - safeScenarioNetworkStart;
  const safeScenarioMutationRequestCount = mutationRequestCount() - safeScenarioMutationStart;
  const safeScenarioWorkerConstructionCount =
    (await workerConstructionCount()) - safeScenarioWorkerStart;
  const safeScenarioPopupCreationCount =
    (await crossPageCreationCount()) - safeScenarioPopupStart;
  const safeScenarioFilePickerInvocationCount =
    (await filePickerInvocationCount()) - safeScenarioFilePickerStart;
  const safeScenarioNetworkChannelConstructionCount =
    (await networkChannelConstructionCount()) - safeScenarioNetworkChannelStart;
  const safeScenarioUnsafeDelegatedAfter = await unsafeDelegatedActionListenerCount();
  for (const count of [
    safeScenarioPersistentWriteOperationCount,
    safeScenarioNetworkRequestCount,
    safeScenarioMutationRequestCount,
    safeScenarioWorkerConstructionCount,
    safeScenarioPopupCreationCount,
    safeScenarioFilePickerInvocationCount,
    safeScenarioNetworkChannelConstructionCount,
    safeScenarioUnsafeDelegatedAfter,
  ]) {
    expect(count).toBe(0);
  }
  const safeScenarioUnsafeDelegatedActionListenerCount = Math.max(
    safeScenarioUnsafeDelegatedBefore,
    safeScenarioUnsafeDelegatedAfter,
  );

  const persistentStateBeforeAgentic = await persistentStateSnapshot();
  const agenticPersistentWriteStart = await persistentWriteCount();
  const agenticNetworkStart = applicationNetworkRequests.length;
  const agenticMutationStart = mutationRequestCount();
  const agenticWorkerConstructionStart = await workerConstructionCount();
  const agenticPopupCreationStart = await crossPageCreationCount();
  const agenticFilePickerInvocationStart = await filePickerInvocationCount();
  const agenticNetworkChannelConstructionStart = await networkChannelConstructionCount();
  const agenticUnsafeDelegatedActionListenerCountBefore =
    await unsafeDelegatedActionListenerCount();
  expect(agenticUnsafeDelegatedActionListenerCountBefore).toBe(0);
  const agenticCard = page.getByTestId('ats-capability-agentic-screening');
  const agenticModeBadge = agenticCard.getByText('Yalnız öneri', { exact: true });
  await expect(agenticModeBadge).toHaveCount(1);
  await expect(agenticModeBadge).toBeVisible();
  const agenticMode =
    (await agenticModeBadge.innerText()).trim() === 'Yalnız öneri'
      ? ('PROPOSAL_ONLY' as const)
      : ('UNVERIFIED' as const);
  expect(agenticMode).toBe('PROPOSAL_ONLY');
  const closedAgenticControlSignatures = await readInteractiveControlSignatures(agenticCard);
  expect(await page.locator('iframe, frame').count()).toBe(0);
  const closedDocumentControlSignatures = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(closedAgenticControlSignatures).toEqual(
    [...expectedAgenticInteractiveControlSignatures.closed].sort(),
  );
  expect(await closedShadowRootCount()).toBe(0);
  const agenticOpen = agenticCard.getByRole('button', {
    name: 'Ajan önerisini güvenle dene',
  });
  await agenticOpen.focus();
  await expect(agenticOpen).toBeFocused();
  await page.keyboard.press('Enter');
  const openedAgenticControlSignatures = await readInteractiveControlSignatures(agenticCard);
  const openedDocumentControlSignatures = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(openedAgenticControlSignatures).toEqual(
    [...expectedAgenticInteractiveControlSignatures.opened].sort(),
  );
  expect([...openedDocumentControlSignatures].sort()).toEqual(
    replaceSignatureMultiset(
      closedDocumentControlSignatures,
      expectedAgenticInteractiveControlSignatures.closed,
      expectedAgenticInteractiveControlSignatures.opened,
    ),
  );
  expect(await closedShadowRootCount()).toBe(0);
  await activateByKeyboard(page.getByTestId('ats-safe-run-agentic-screening'), 'Space');
  await expect(agenticCard).toContainText(
    'Sentetik bir başvuruda eksik insan inceleme adımı için açıklanabilir sonraki-adım taslağı istenir.',
  );
  await expect(agenticCard).toContainText('Salt-okunur örnek çıktı');
  await expect(agenticCard).toContainText(
    'Gerekçe, gerekli insan onayları ve uygulanamayacak eylemlerle birlikte salt-okunur öneri gösterilir.',
  );
  await expect(agenticCard).toContainText(
    'Mesaj gönderilmez, aday durumu değişmez, red/teklif/sıralama üretilmez ve toplu onay yoktur.',
  );
  const completedAgenticControlSignatures = await readInteractiveControlSignatures(agenticCard);
  const completedDocumentControlSignatures = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(completedAgenticControlSignatures).toEqual(
    [...expectedAgenticInteractiveControlSignatures.completed].sort(),
  );
  expect([...completedDocumentControlSignatures].sort()).toEqual(
    replaceSignatureMultiset(
      openedDocumentControlSignatures,
      expectedAgenticInteractiveControlSignatures.opened,
      expectedAgenticInteractiveControlSignatures.completed,
    ),
  );
  expect(await closedShadowRootCount()).toBe(0);
  const agenticInteractiveControlSignatures = {
    closed: closedAgenticControlSignatures,
    opened: openedAgenticControlSignatures,
    completed: completedAgenticControlSignatures,
  };
  const forbiddenActionControlCount = (
    Object.keys(expectedAgenticInteractiveControlSignatures) as Array<
      keyof typeof expectedAgenticInteractiveControlSignatures
    >
  ).reduce(
    (count, state) =>
      count +
      agenticInteractiveControlSignatures[state].filter(
        (signature) =>
          !(expectedAgenticInteractiveControlSignatures[state] as readonly string[]).includes(
            signature,
          ),
      ).length,
    0,
  );
  expect(forbiddenActionControlCount).toBe(0);
  const agenticRunnerCompleted = (await agenticCard.innerText()).includes(
    'Salt-okunur örnek çıktı',
  );
  const agenticBoundaryVisible = (await agenticCard.innerText()).includes(
    'Mesaj gönderilmez',
  );
  await activateByKeyboard(agenticCard.getByRole('button', { name: 'Denemeyi sıfırla' }), 'Space');
  expect(await readInteractiveControlSignatures(agenticCard)).toEqual(
    [...expectedAgenticInteractiveControlSignatures.opened].sort(),
  );
  await activateByKeyboard(
    agenticCard.getByRole('button', { name: 'Güvenli denemeyi kapat' }),
    'Space',
  );
  expect(await readInteractiveControlSignatures(agenticCard)).toEqual(
    [...expectedAgenticInteractiveControlSignatures.closed].sort(),
  );
  expect(await readInteractiveControlSignatures(page.locator('body'))).toEqual(
    closedDocumentControlSignatures,
  );
  await page.waitForTimeout(mutationQuietPeriodMs);
  const persistentStateAfterAgentic = await persistentStateSnapshot();
  const agenticPersistentStoresUnchanged =
    JSON.stringify(persistentStateBeforeAgentic) === JSON.stringify(persistentStateAfterAgentic);
  expect(agenticPersistentStoresUnchanged).toBe(true);
  const agenticPersistentWriteOperationCount =
    (await persistentWriteCount()) - agenticPersistentWriteStart;
  expect(agenticPersistentWriteOperationCount).toBe(0);
  const agenticNetworkRequestCount = applicationNetworkRequests.length - agenticNetworkStart;
  expect(agenticNetworkRequestCount).toBe(0);
  const agenticMutationRequestCount = mutationRequestCount() - agenticMutationStart;
  expect(agenticMutationRequestCount).toBe(0);
  const agenticWorkerConstructionCount =
    (await workerConstructionCount()) - agenticWorkerConstructionStart;
  expect(agenticWorkerConstructionCount).toBe(0);
  const agenticPopupCreationCount =
    (await crossPageCreationCount()) - agenticPopupCreationStart;
  expect(agenticPopupCreationCount).toBe(0);
  const agenticFilePickerInvocationCount =
    (await filePickerInvocationCount()) - agenticFilePickerInvocationStart;
  expect(agenticFilePickerInvocationCount).toBe(0);
  const agenticNetworkChannelConstructionCount =
    (await networkChannelConstructionCount()) - agenticNetworkChannelConstructionStart;
  expect(agenticNetworkChannelConstructionCount).toBe(0);
  const agenticUnsafeDelegatedActionListenerCountAfter =
    await unsafeDelegatedActionListenerCount();
  expect(agenticUnsafeDelegatedActionListenerCountAfter).toBe(0);
  const agenticUnsafeDelegatedActionListenerCount = Math.max(
    agenticUnsafeDelegatedActionListenerCountBefore,
    agenticUnsafeDelegatedActionListenerCountAfter,
  );

  const roleJourneyCapabilityIds: Record<string, string[]> = {};
  for (const [roleId, expectedJourneyIds] of Object.entries(
    expectedRoleJourneyCapabilityIds,
  )) {
    const roleFilter = page.getByTestId(`ats-role-filter-${roleId}`);
    await activateByKeyboard(roleFilter, 'Space');
    expect(await readPressedRoleIds()).toEqual([roleId]);
    const visibleRoleCapabilityIds = await capabilityCards.evaluateAll((cards) =>
      cards.map((card) =>
        (card.getAttribute('data-testid') ?? '').replace(/^ats-capability-/, ''),
      ),
    );
    expect(visibleRoleCapabilityIds).toEqual(
      expectedRoleCapabilityIds[roleId as keyof typeof expectedRoleCapabilityIds],
    );
    const journeyIds = visibleRoleCapabilityIds.filter((capabilityId) =>
      (allSafeExperienceCapabilityIds as readonly string[]).includes(capabilityId),
    );
    expect(journeyIds).toEqual(expectedJourneyIds);

    for (const capabilityId of journeyIds) {
      const card = page.getByTestId(`ats-capability-${capabilityId}`);
      if (capabilityId === 'candidate-cv-pdf-import') {
        await activateByKeyboard(
          card.getByRole('button', { name: 'Sentetik PDF taslak akışını dene' }),
          'Space',
        );
        await activateByKeyboard(page.getByTestId('ats-synthetic-resume-process'), 'Space');
        const proposals = card.locator('article[data-testid^="ats-resume-field-"]');
        await expect(proposals).toHaveCount(expectedSyntheticResumeProposalCount);
        const journeyEmail = card.getByLabel('E-posta');
        await journeyEmail.selectText();
        const expectedJourneyEmail = `${roleId}.journey@example.invalid`;
        await journeyEmail.pressSequentially(expectedJourneyEmail);
        await expect(journeyEmail).toHaveValue(expectedJourneyEmail);
        await activateByKeyboard(
          card.getByRole('button', { name: 'E-posta düzenlemesini kabul et' }),
          'Space',
        );
        await activateByKeyboard(
          card.getByRole('button', { name: 'Deneyim alanını reddet' }),
          'Space',
        );
        const journeyTransfer = card.getByTestId('ats-resume-transfer-selected');
        await expect(journeyTransfer).toContainText('(1)');
        await activateByKeyboard(journeyTransfer, 'Space');
        const journeyDraft = card.getByTestId('ats-synthetic-resume-draft');
        await expect(journeyDraft).toContainText(expectedJourneyEmail);
        await activateByKeyboard(
          card.getByRole('button', { name: 'Tümünü reddet', exact: true }),
          'Space',
        );
        const journeyRejectAllConfirm = card.getByRole('button', {
          name: 'Tümünü reddetmeyi onayla',
        });
        await expect(journeyRejectAllConfirm).toBeVisible();
        await activateByKeyboard(journeyRejectAllConfirm, 'Space');
        await expect(journeyDraft).toHaveCount(0);
        await activateByKeyboard(card.getByRole('button', { name: 'Denemeyi sıfırla' }), 'Space');
        await expect(page.getByTestId('ats-synthetic-resume-process')).toBeVisible();
        await activateByKeyboard(
          card.getByRole('button', { name: 'Sentetik taslak denemesini kapat' }),
          'Space',
        );
        expect(await readInteractiveControlSignatures(card)).toEqual(resumeClosedControls);
        expect(await card.locator('input[type="file"]').count()).toBe(0);
      } else {
        const journey =
          capabilityId === 'agentic-screening'
            ? expectedAgenticJourney
            : expectedSafeScenarioJourneys[
                capabilityId as keyof typeof expectedSafeScenarioJourneys
              ];
        await activateByKeyboard(card.getByRole('button', { name: journey.action }), 'Space');
        await expect(card).toContainText(journey.scenario);
        await activateByKeyboard(page.getByTestId(`ats-safe-run-${capabilityId}`), 'Space');
        await expect(card).toContainText(journey.output);
        await expect(card).toContainText(journey.boundary);
        await expect(card).toContainText(
          'Bu deneme tarayıcı belleğinde çalıştı; ağ isteği, kayıt, bildirim veya karar üretilmedi.',
        );
        await activateByKeyboard(card.getByRole('button', { name: 'Denemeyi sıfırla' }), 'Space');
        await activateByKeyboard(
          card.getByRole('button', { name: 'Güvenli denemeyi kapat' }),
          'Space',
        );
      }
      await assertNoExternalProductSurface();
      expect(await unsafeDelegatedActionListenerCount()).toBe(0);
    }
    roleJourneyCapabilityIds[roleId] = journeyIds;
  }
  expect(roleJourneyCapabilityIds).toEqual(expectedRoleJourneyCapabilityIds);
  await activateByKeyboard(allRolesFilter, 'Space');
  expect(await readPressedRoleIds()).toEqual(['all']);
  await expect(capabilityCards).toHaveCount(expectedCapabilityIds.length);
  expect(await readInteractiveControlSignatures(hubSurface)).toEqual(
    expectedInitialHubControlSignatures,
  );

  const desktopJourneyLifecycleAudit = await readJourneyLifecycleAudit(
    productJourneyNetworkStart,
    productJourneyMutationStart,
  );

  const liveLaunch = page.getByTestId('ats-live-interview-evidence-link');
  await expect(liveLaunch).toBeVisible();
  await expect(liveLaunch).toHaveAttribute('href', expectedFinalPath);
  const liveLaunchHref = (await liveLaunch.getAttribute('href')) ?? '';
  const productBoundary = page.getByTestId('ats-product-boundary');
  await expect(productBoundary).toBeVisible();
  await expect(productBoundary).toContainText(
    'otomatik eleme veya sıralama, istihdam kararı, Legal/DPO, owner ve müşteri onayı bu merkezle açılmaz',
  );

  report.hub = {
    path: desktopHubPath,
    rendered: desktopHubRendered,
    runtimeReady,
    capabilityIds,
    targetRoleIds,
    visibleCapabilityCount: capabilityIds.length,
    roleCapabilityCounts,
    roleCapabilityIds,
    roleJourneyCapabilityIds,
    roleJourneyEvidenceClass: 'TARGET_ROLE_FILTER_UNDER_NAMED_VIEW_PERSONA',
    journeyLifecycleAudit: {
      desktop: desktopJourneyLifecycleAudit,
    },
    candidateFilterVisible: await candidateFilter.isVisible(),
    candidateBoundaryVisible,
    cvImportMode: 'OWNER_GATED',
    cvImportInteractiveControlCount,
    fileUploadControlCount,
    syntheticResume: {
      proposalCount,
      invalidFixtureCount,
      editableAfterFirstKeystroke,
      editedEmail,
      acceptAfterEditVisible,
      rejectAfterEditVisible,
      acceptedDraftFieldCount,
      localDraftVisible,
      localDraftContainsEditedEmail,
      rejectAllSecondConfirmationRequired,
      rejectAllApplied,
      resetReturnedToStart,
      persistentStoresUnchanged,
      persistentWriteOperationCount: resumePersistentWriteOperationCount,
      mutationQuietPeriodMs,
      mutationRequestCount: resumeMutationRequestCount,
      networkRequestCount: resumeNetworkRequestCount,
      networkChannelConstructionCount: resumeNetworkChannelConstructionCount,
      workerConstructionCount: resumeWorkerConstructionCount,
      popupCreationCount: resumePopupCreationCount,
      filePickerInvocationCount: resumeFilePickerInvocationCount,
      unsafeDelegatedActionListenerCount: resumeUnsafeDelegatedActionListenerCount,
    },
    agentic: {
      mode: agenticMode,
      runnerCompleted: agenticRunnerCompleted,
      boundaryVisible: agenticBoundaryVisible,
      interactiveControlSignatures: agenticInteractiveControlSignatures,
      forbiddenActionControlCount,
      persistentStoresUnchanged: agenticPersistentStoresUnchanged,
      persistentWriteOperationCount: agenticPersistentWriteOperationCount,
      mutationQuietPeriodMs,
      mutationRequestCount: agenticMutationRequestCount,
      networkRequestCount: agenticNetworkRequestCount,
      networkChannelConstructionCount: agenticNetworkChannelConstructionCount,
      workerConstructionCount: agenticWorkerConstructionCount,
      popupCreationCount: agenticPopupCreationCount,
      filePickerInvocationCount: agenticFilePickerInvocationCount,
      unsafeDelegatedActionListenerCount: agenticUnsafeDelegatedActionListenerCount,
    },
    safeExperienceCapabilityIds: [...allSafeExperienceCapabilityIds],
    safeScenarioAudit: {
      completedCapabilityIds: completedSafeScenarioCapabilityIds,
      persistentStoresUnchanged: safeScenarioPersistentStoresUnchanged,
      persistentWriteOperationCount: safeScenarioPersistentWriteOperationCount,
      networkRequestCount: safeScenarioNetworkRequestCount,
      mutationRequestCount: safeScenarioMutationRequestCount,
      networkChannelConstructionCount: safeScenarioNetworkChannelConstructionCount,
      workerConstructionCount: safeScenarioWorkerConstructionCount,
      popupCreationCount: safeScenarioPopupCreationCount,
      filePickerInvocationCount: safeScenarioFilePickerInvocationCount,
      unsafeDelegatedActionListenerCount: safeScenarioUnsafeDelegatedActionListenerCount,
    },
    liveLaunchHref,
    productBoundaryVisible: await productBoundary.isVisible(),
  };

  await liveLaunch.focus();
  await expect(liveLaunch).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(consoleSurface).toBeVisible({ timeout: 90_000 });
  const desktopLaunchPath = new URL(page.url()).pathname;
  expect(desktopLaunchPath).toBe(expectedFinalPath);
  const desktopRemoteConsoleRendered = await consoleSurface.isVisible();

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
    finalPath: desktopLaunchPath,
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
  await cdpSession.send('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 3,
    mobile: true,
    screenWidth: 390,
    screenHeight: 844,
  });
  await cdpSession.send('Emulation.setTouchEmulationEnabled', {
    enabled: true,
    maxTouchPoints: 5,
  });
  await cdpSession.send('Network.setUserAgentOverride', {
    userAgent:
      'Mozilla/5.0 (Linux; Android 15; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36',
  });
  await page.goto('/home', { waitUntil: 'domcontentloaded' });
  const mobileViewportWidth = await page.evaluate(() => window.innerWidth);
  expect(mobileViewportWidth).toBe(390);
  const mobileEmulation = await page.evaluate(() => ({
    userAgentMatched: /Android 15; Pixel 7/.test(navigator.userAgent),
    touchPoints: navigator.maxTouchPoints,
    pointerCoarse: window.matchMedia('(pointer: coarse)').matches,
    deviceScaleFactor: window.devicePixelRatio,
  }));
  expect(mobileEmulation).toEqual({
    userAgentMatched: true,
    touchPoints: 5,
    pointerCoarse: true,
    deviceScaleFactor: 3,
  });
  const mobileHomePath = new URL(page.url()).pathname;
  expect(mobileHomePath).toBe('/home');
  const mobileMenuButton = page.getByRole('button', { name: /Menüyü aç|Open menu/ });
  await activateByTouch(mobileMenuButton);
  const mobileNavigation = page.getByRole('navigation', { name: 'Ana gezinme' });
  await expect(mobileNavigation).toBeVisible();
  const mobileHrButton = mobileNavigation.getByRole('button', {
    name: /^(İK|HR|Personal|RRHH)$/,
  });
  await expect(mobileHrButton).toBeVisible();
  const mobileMenuOpened = await mobileHrButton.isVisible();
  await activateByTouch(mobileHrButton);
  const mobileAtsProductHubAction = mobileNavigation.getByRole('button', {
    name: /ATS Ürün Merkezi/,
  });
  await expect(mobileAtsProductHubAction).toBeVisible();
  const mobileHrSectionOpened = await mobileAtsProductHubAction.isVisible();
  const mobileAtsProductHubActionVisible = await mobileAtsProductHubAction.isVisible();
  await activateByTouch(mobileAtsProductHubAction);
  await expect(hubSurface).toBeVisible({ timeout: 90_000 });
  const mobileHubPath = new URL(page.url()).pathname;
  expect(mobileHubPath).toBe(expectedHubPath);
  const mobileHubRendered = await hubSurface.isVisible();
  const mobileProductJourneyAuditStart = await page.evaluate(() => {
    const auditWindow = window as Window & {
      __p5BrowserAuditBeginProductJourney?: () => void;
      __p5PersistentMutationAuditBeginProductJourney?: () => void;
      __p5BrowserAuditSnapshot?: () => Record<string, unknown>;
      __p5PersistentMutationAuditSnapshot?: () => Record<string, unknown>;
    };
    auditWindow.__p5BrowserAuditBeginProductJourney?.();
    auditWindow.__p5PersistentMutationAuditBeginProductJourney?.();
    return {
      browser: auditWindow.__p5BrowserAuditSnapshot?.(),
      persistence: auditWindow.__p5PersistentMutationAuditSnapshot?.(),
    };
  });
  expect(mobileProductJourneyAuditStart.browser).toMatchObject({
    workerConstructionCount: 0,
    popupCreationCount: 0,
    filePickerInvocationCount: 0,
    networkChannelConstructionCount: 0,
    historyMutationCount: 0,
    hashChangeCount: 0,
    closedShadowRootAttemptCount: 0,
    unsafeDomInsertionCount: 0,
    productJourneyBegun: true,
    instrumentationFailureCount: 0,
  });
  expect(mobileProductJourneyAuditStart.persistence).toMatchObject({
    writeCount: 0,
    instrumentationFailureCount: 0,
    storageProxyCount: 2,
    productJourneyBegun: true,
  });
  const mobileProductJourneyNetworkStart = applicationNetworkRequests.length;
  const mobileProductJourneyMutationStart = mutationRequestCount();
  const persistentStateBeforeMobileResume = await persistentStateSnapshot();
  const mobileResumePersistentWriteStart = await persistentWriteCount();
  const mobileResumeNetworkStart = applicationNetworkRequests.length;
  const mobileResumeMutationStart = mutationRequestCount();
  const mobileResumeWorkerConstructionStart = await workerConstructionCount();
  const mobileResumePopupCreationStart = await crossPageCreationCount();
  const mobileResumeFilePickerInvocationStart = await filePickerInvocationCount();
  const mobileResumeNetworkChannelConstructionStart = await networkChannelConstructionCount();
  expect(mobileResumeWorkerConstructionStart).toBe(0);
  expect(mobileResumePopupCreationStart).toBe(0);
  expect(page.workers()).toHaveLength(0);
  expect(page.context().serviceWorkers()).toHaveLength(0);
  const mobileSyntheticResumeUnsafeDelegatedActionListenerCountBefore =
    await unsafeDelegatedActionListenerCount();
  expect(mobileSyntheticResumeUnsafeDelegatedActionListenerCountBefore).toBe(0);
  await assertNoExternalProductSurface();

  const mobileCandidateFilter = page.getByTestId('ats-role-filter-candidate');
  const mobileRoleFilters = hubSurface.locator('button[data-testid^="ats-role-filter-"]');
  await expect(mobileRoleFilters).toHaveCount(expectedTargetRoleIds.length + 1);
  await activateByTouch(mobileCandidateFilter);
  const mobilePressedRoleIds = await mobileRoleFilters.evaluateAll((controls) =>
    controls
      .filter((control) => control.getAttribute('aria-pressed') === 'true')
      .map((control) =>
        (control.getAttribute('data-testid') ?? '').replace(/^ats-role-filter-/, ''),
      ),
  );
  expect(mobilePressedRoleIds).toEqual(['candidate']);
  const mobileCandidateCapabilityIds = await capabilityCards.evaluateAll((cards) =>
    cards.map((card) =>
      (card.getAttribute('data-testid') ?? '').replace(/^ats-capability-/, ''),
    ),
  );
  expect(mobileCandidateCapabilityIds).toEqual(expectedRoleCapabilityIds.candidate);
  const mobileCvImportCard = page.getByTestId('ats-capability-candidate-cv-pdf-import');
  const mobileClosedResumeControls = await readInteractiveControlSignatures(mobileCvImportCard);
  expect(mobileClosedResumeControls).toEqual(resumeClosedControls);
  const mobileClosedDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
  await activateByTouch(
    mobileCvImportCard.getByRole('button', { name: 'Sentetik PDF taslak akışını dene' }),
  );
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeOpenedControls,
  );
  const mobileOpenedDocumentControls = await readInteractiveControlSignatures(page.locator('body'));
  expect(mobileOpenedDocumentControls).toEqual(
    replaceSignatureMultiset(
      mobileClosedDocumentControls,
      mobileClosedResumeControls,
      resumeOpenedControls,
    ),
  );
  await assertNoExternalProductSurface();
  await activateByTouch(page.getByTestId('ats-synthetic-resume-process'));
  await expect(page.getByTestId('ats-synthetic-resume-proposals')).toBeVisible();
  await expect(
    page
      .getByTestId('ats-synthetic-resume-proposals')
      .locator('article[data-testid^="ats-resume-field-"]'),
  ).toHaveCount(expectedSyntheticResumeProposalCount);
  const mobileSyntheticResumeControlsRendered = await page
    .getByTestId('ats-synthetic-resume-proposals')
    .isVisible();
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeBaseProcessedControls,
  );
  const mobileProcessedDocumentControls = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(mobileProcessedDocumentControls).toEqual(
    replaceSignatureMultiset(mobileOpenedDocumentControls, resumeOpenedControls, resumeBaseProcessedControls),
  );
  await assertNoExternalProductSurface();

  const mobileEmailField = mobileCvImportCard.getByTestId('ats-resume-field-contact-email');
  const mobileEmailInput = mobileEmailField.getByLabel('E-posta');
  await mobileEmailInput.selectText();
  await mobileEmailInput.pressSequentially('mobil.duzenlendi@example.invalid');
  await expect(mobileEmailInput).toHaveValue('mobil.duzenlendi@example.invalid');
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeEditedControls,
  );
  const mobileEditedDocumentControls = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(mobileEditedDocumentControls).toEqual(
    replaceSignatureMultiset(
      mobileProcessedDocumentControls,
      resumeBaseProcessedControls,
      resumeEditedControls,
    ),
  );
  await activateByTouch(
    mobileEmailField.getByRole('button', { name: 'E-posta düzenlemesini kabul et' }),
  );
  await activateByTouch(
    mobileCvImportCard
      .getByTestId('ats-resume-field-skills')
      .getByRole('button', { name: 'Beceriler alanını kabul et' }),
  );
  await activateByTouch(
    mobileCvImportCard
      .getByTestId('ats-resume-field-experience')
      .getByRole('button', { name: 'Deneyim alanını reddet' }),
  );
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeReviewedControls,
  );
  const mobileReviewedDocumentControls = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(mobileReviewedDocumentControls).toEqual(
    replaceSignatureMultiset(
      mobileEditedDocumentControls,
      resumeEditedControls,
      resumeReviewedControls,
    ),
  );
  const mobileTransferSelected = mobileCvImportCard.getByTestId('ats-resume-transfer-selected');
  await expect(mobileTransferSelected).toContainText('(2)');
  await activateByTouch(mobileTransferSelected);
  const mobileDraft = mobileCvImportCard.getByTestId('ats-synthetic-resume-draft');
  await expect(mobileDraft).toContainText('mobil.duzenlendi@example.invalid');
  await expect(mobileDraft).toContainText('Araştırma, erişilebilir ürün tasarımı');
  await activateByTouch(
    mobileCvImportCard.getByRole('button', { name: 'Tümünü reddet', exact: true }),
  );
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeRejectArmedControls,
  );
  const mobileRejectArmedDocumentControls = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(mobileRejectArmedDocumentControls).toEqual(
    replaceSignatureMultiset(
      mobileReviewedDocumentControls,
      resumeReviewedControls,
      resumeRejectArmedControls,
    ),
  );
  const mobileRejectAllConfirm = mobileCvImportCard.getByRole('button', {
    name: 'Tümünü reddetmeyi onayla',
  });
  await expect(mobileRejectAllConfirm).toBeVisible();
  await activateByTouch(mobileRejectAllConfirm);
  await expect(mobileDraft).toHaveCount(0);
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeAllRejectedControls,
  );
  const mobileAllRejectedDocumentControls = await readInteractiveControlSignatures(
    page.locator('body'),
  );
  expect(mobileAllRejectedDocumentControls).toEqual(
    replaceSignatureMultiset(
      mobileRejectArmedDocumentControls,
      resumeRejectArmedControls,
      resumeAllRejectedControls,
    ),
  );
  await activateByTouch(
    mobileCvImportCard.getByRole('button', { name: 'Denemeyi sıfırla' }),
  );
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeOpenedControls,
  );
  expect(await readInteractiveControlSignatures(page.locator('body'))).toEqual(
    mobileOpenedDocumentControls,
  );
  await activateByTouch(
    mobileCvImportCard.getByRole('button', { name: 'Sentetik taslak denemesini kapat' }),
  );
  expect(await readInteractiveControlSignatures(mobileCvImportCard)).toEqual(
    resumeClosedControls,
  );
  expect(await readInteractiveControlSignatures(page.locator('body'))).toEqual(
    mobileClosedDocumentControls,
  );
  await assertNoExternalProductSurface();
  const mobileCompletedSafeScenarioCapabilityIdSet = new Set<string>();
  const mobileRoleJourneyCapabilityIds: Record<string, string[]> = {};
  for (const roleId of expectedTargetRoleIds) {
    await activateByTouch(page.getByTestId(`ats-role-filter-${roleId}`));
    const pressedRoleIds = await mobileRoleFilters.evaluateAll((controls) =>
      controls
        .filter((control) => control.getAttribute('aria-pressed') === 'true')
        .map((control) =>
          (control.getAttribute('data-testid') ?? '').replace(/^ats-role-filter-/, ''),
        ),
    );
    expect(pressedRoleIds).toEqual([roleId]);
    const visibleCapabilityIds = await capabilityCards.evaluateAll((cards) =>
      cards.map((card) =>
        (card.getAttribute('data-testid') ?? '').replace(/^ats-capability-/, ''),
      ),
    );
    expect(visibleCapabilityIds).toEqual(expectedRoleCapabilityIds[roleId]);
    const journeyIds = visibleCapabilityIds.filter((capabilityId) =>
      (allSafeExperienceCapabilityIds as readonly string[]).includes(capabilityId),
    );
    expect(journeyIds).toEqual(expectedRoleJourneyCapabilityIds[roleId]);

    for (const capabilityId of journeyIds) {
      const card = page.getByTestId(`ats-capability-${capabilityId}`);
      if (capabilityId === 'candidate-cv-pdf-import') {
        if (roleId !== 'candidate') {
          await activateByTouch(
            card.getByRole('button', { name: 'Sentetik PDF taslak akışını dene' }),
          );
          await activateByTouch(page.getByTestId('ats-synthetic-resume-process'));
          await expect(
            card.locator('article[data-testid^="ats-resume-field-"]'),
          ).toHaveCount(expectedSyntheticResumeProposalCount);
          const journeyEmail = card.getByLabel('E-posta');
          await journeyEmail.selectText();
          const journeyEmailValue = `${roleId}.mobile@example.invalid`;
          await journeyEmail.pressSequentially(journeyEmailValue);
          await expect(journeyEmail).toHaveValue(journeyEmailValue);
          await activateByTouch(
            card.getByRole('button', { name: 'E-posta düzenlemesini kabul et' }),
          );
          await activateByTouch(
            card.getByRole('button', { name: 'Deneyim alanını reddet' }),
          );
          const journeyTransfer = card.getByTestId('ats-resume-transfer-selected');
          await expect(journeyTransfer).toContainText('(1)');
          await activateByTouch(journeyTransfer);
          await expect(card.getByTestId('ats-synthetic-resume-draft')).toContainText(
            journeyEmailValue,
          );
          await activateByTouch(
            card.getByRole('button', { name: 'Tümünü reddet', exact: true }),
          );
          await activateByTouch(
            card.getByRole('button', { name: 'Tümünü reddetmeyi onayla' }),
          );
          await expect(card.getByTestId('ats-synthetic-resume-draft')).toHaveCount(0);
          await activateByTouch(card.getByRole('button', { name: 'Denemeyi sıfırla' }));
          await activateByTouch(
            card.getByRole('button', { name: 'Sentetik taslak denemesini kapat' }),
          );
          expect(await readInteractiveControlSignatures(card)).toEqual(resumeClosedControls);
        }
      } else {
        const journey =
          capabilityId === 'agentic-screening'
            ? expectedAgenticJourney
            : expectedSafeScenarioJourneys[
                capabilityId as keyof typeof expectedSafeScenarioJourneys
              ];
        await activateByTouch(card.getByRole('button', { name: journey.action }));
        await expect(card).toContainText(journey.scenario);
        await activateByTouch(page.getByTestId(`ats-safe-run-${capabilityId}`));
        await expect(card).toContainText(journey.output);
        await expect(card).toContainText(journey.boundary);
        await expect(card).toContainText(
          'Bu deneme tarayıcı belleğinde çalıştı; ağ isteği, kayıt, bildirim veya karar üretilmedi.',
        );
        await activateByTouch(card.getByRole('button', { name: 'Denemeyi sıfırla' }));
        await activateByTouch(
          card.getByRole('button', { name: 'Güvenli denemeyi kapat' }),
        );
      }
      await assertNoExternalProductSurface();
      expect(await unsafeDelegatedActionListenerCount()).toBe(0);
      mobileCompletedSafeScenarioCapabilityIdSet.add(capabilityId);
    }
    mobileRoleJourneyCapabilityIds[roleId] = journeyIds;
  }
  const mobileCompletedSafeScenarioCapabilityIds = allSafeExperienceCapabilityIds.filter(
    (capabilityId) => mobileCompletedSafeScenarioCapabilityIdSet.has(capabilityId),
  );
  expect(mobileCompletedSafeScenarioCapabilityIds).toEqual(allSafeExperienceCapabilityIds);
  expect(mobileRoleJourneyCapabilityIds).toEqual(expectedRoleJourneyCapabilityIds);
  expect(mobileTouchActivationCount).toBeGreaterThanOrEqual(50);
  await page.waitForTimeout(mutationQuietPeriodMs);
  const persistentStateAfterMobileResume = await persistentStateSnapshot();
  const mobileSyntheticResumePersistentStoresUnchanged =
    JSON.stringify(persistentStateBeforeMobileResume) ===
    JSON.stringify(persistentStateAfterMobileResume);
  expect(mobileSyntheticResumePersistentStoresUnchanged).toBe(true);
  const mobileSyntheticResumePersistentWriteOperationCount =
    (await persistentWriteCount()) - mobileResumePersistentWriteStart;
  expect(mobileSyntheticResumePersistentWriteOperationCount).toBe(0);
  const mobileSyntheticResumeMutationRequestCount =
    mutationRequestCount() - mobileResumeMutationStart;
  expect(mobileSyntheticResumeMutationRequestCount).toBe(0);
  const mobileSyntheticResumeNetworkRequestCount =
    applicationNetworkRequests.length - mobileResumeNetworkStart;
  expect(mobileSyntheticResumeNetworkRequestCount).toBe(0);
  const mobileSyntheticResumeWorkerConstructionCount =
    (await workerConstructionCount()) - mobileResumeWorkerConstructionStart;
  expect(mobileSyntheticResumeWorkerConstructionCount).toBe(0);
  const mobileSyntheticResumePopupCreationCount =
    (await crossPageCreationCount()) - mobileResumePopupCreationStart;
  expect(mobileSyntheticResumePopupCreationCount).toBe(0);
  const mobileSyntheticResumeFilePickerInvocationCount =
    (await filePickerInvocationCount()) - mobileResumeFilePickerInvocationStart;
  expect(mobileSyntheticResumeFilePickerInvocationCount).toBe(0);
  const mobileSyntheticResumeNetworkChannelConstructionCount =
    (await networkChannelConstructionCount()) - mobileResumeNetworkChannelConstructionStart;
  expect(mobileSyntheticResumeNetworkChannelConstructionCount).toBe(0);
  const mobileSyntheticResumeUnsafeDelegatedActionListenerCountAfter =
    await unsafeDelegatedActionListenerCount();
  expect(mobileSyntheticResumeUnsafeDelegatedActionListenerCountAfter).toBe(0);
  const mobileSyntheticResumeUnsafeDelegatedActionListenerCount = Math.max(
    mobileSyntheticResumeUnsafeDelegatedActionListenerCountBefore,
    mobileSyntheticResumeUnsafeDelegatedActionListenerCountAfter,
  );
  const hubLayout = await page.evaluate(() => ({
    rootOverflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    rootOverflowModes: [document.documentElement, document.body, document.querySelector('main')]
      .filter((element): element is HTMLElement => element instanceof HTMLElement)
      .map((element) => window.getComputedStyle(element).overflowX),
  }));
  const hubOverflowPx = await hubSurface.evaluate(
    (surface) => surface.scrollWidth - surface.clientWidth,
  );
  expect(hubLayout.rootOverflowPx).toBeLessThanOrEqual(1);
  expect(hubLayout.rootOverflowModes).not.toContain('hidden');
  expect(hubLayout.rootOverflowModes).not.toContain('clip');
  expect(hubOverflowPx).toBeLessThanOrEqual(1);

  const hubAxeResults = await new AxeBuilder({ page })
    .include('[data-testid="ats-product-hub"]')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze();
  const hubBlockingViolations = hubAxeResults.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  );
  expect(hubBlockingViolations).toEqual([]);
  const mobileJourneyLifecycleAudit = await readJourneyLifecycleAudit(
    mobileProductJourneyNetworkStart,
    mobileProductJourneyMutationStart,
  );
  expect(report.hub).toBeDefined();
  report.hub!.journeyLifecycleAudit.mobile = mobileJourneyLifecycleAudit;

  const mobileLiveLaunch = page.getByTestId('ats-live-interview-evidence-link');
  await expect(mobileLiveLaunch).toBeVisible();
  await expect(mobileLiveLaunch).toHaveAttribute('href', expectedFinalPath);
  await mobileLiveLaunch.focus();
  await expect(mobileLiveLaunch).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(consoleSurface).toBeVisible({ timeout: 90_000 });
  const mobileLaunchPath = new URL(page.url()).pathname;
  expect(mobileLaunchPath).toBe(expectedFinalPath);
  const mobileRemoteConsoleRendered = await consoleSurface.isVisible();
  report.discovery = {
    desktopHomePath,
    desktopSidebarVisible,
    desktopSidebarHref,
    desktopSearchQuery,
    desktopSearchResultVisible,
    desktopHubPath,
    desktopHubRendered,
    desktopLaunchPath,
    desktopRemoteConsoleRendered,
    mobileViewportWidth,
    mobileHomePath,
    mobileMenuOpened,
    mobileHrSectionOpened,
    mobileAtsProductHubActionVisible,
    mobileHubPath,
    mobileHubRendered,
    mobileLaunchPath,
    mobileRemoteConsoleRendered,
  };

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
    mobileUserAgentMatched: mobileEmulation.userAgentMatched,
    mobileTouchPoints: mobileEmulation.touchPoints,
    mobilePointerCoarse: mobileEmulation.pointerCoarse,
    mobileDeviceScaleFactor: mobileEmulation.deviceScaleFactor,
    hubRootOverflowPx: hubLayout.rootOverflowPx,
    hubOverflowPx,
    rootOverflowPx: layout.rootOverflowPx,
    consoleOverflowPx,
    mobileSyntheticResumeControlsRendered,
    mobileCandidateCapabilityIds,
    mobileCompletedSafeScenarioCapabilityIds,
    mobileSyntheticResumePersistentStoresUnchanged,
    mobileSyntheticResumePersistentWriteOperationCount,
    mobileSyntheticResumeMutationRequestCount,
    mobileSyntheticResumeNetworkRequestCount,
    mobileSyntheticResumeNetworkChannelConstructionCount,
    mobileSyntheticResumeWorkerConstructionCount,
    mobileSyntheticResumePopupCreationCount,
    mobileSyntheticResumeFilePickerInvocationCount,
    mobileSyntheticResumeUnsafeDelegatedActionListenerCount,
    mobileRoleJourneyCapabilityIds,
    mobileRoleJourneyEvidenceClass: 'TOUCH_EXECUTED_UNDER_NAMED_VIEW_PERSONA',
    mobileTouchActivationCount,
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
    ...hubBlockingViolations.map((violation) => ({
      surface: 'hub' as const,
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
    hubBlockingViolationCount: hubBlockingViolations.length,
    productBlockingViolationCount: productBlockingViolations.length,
    blockingViolationCount: violations.length,
    violations,
  };
  expect(violations).toEqual([]);

  const observedFrontendAssetResponses = await Promise.all(frontendAssetResponsePromises);
  expect(observedFrontendAssetResponses.length).toBeGreaterThan(0);
  const frontendAssetResponsesByPath = new Map<string, FrontendAssetResponse>();
  for (const response of observedFrontendAssetResponses) {
    expect(response.status).toBe(200);
    expect(response.bodySha256).toMatch(/^[0-9a-f]{64}$/);
    expect(response.fromServiceWorker).toBe(false);
    expect(response.contentType).toMatch(
      response.resourceType === 'script'
        ? /^(?:application|text)\/(?:javascript|x-javascript)(?:;|$)/i
        : /^text\/css(?:;|$)/i,
    );
    const prior = frontendAssetResponsesByPath.get(response.path);
    if (prior) {
      expect(response).toEqual(prior);
    } else {
      frontendAssetResponsesByPath.set(response.path, response);
    }
  }
  const frontendAssetResponses = Array.from(frontendAssetResponsesByPath.values()).sort(
    (left, right) => left.path.localeCompare(right.path),
  );
  const frontendAssetPaths = frontendAssetResponses.map(({ path }) => path);
  expect(frontendAssetPaths.length).toBeGreaterThan(0);
  expect(frontendAssetPaths.some((path) => path.startsWith('/assets/'))).toBe(true);
  const expectedBuildInfoAssetPaths = new Set(
    buildInfoAssets
      .filter((asset) => /\.(?:js|css)$/.test(asset))
      .map((asset) => `/assets/${asset}`),
  );
  for (const rootEntrypoint of buildInfoRootEntrypoints) {
    expectedBuildInfoAssetPaths.add(rootEntrypoint.path);
  }
  const buildInfoAssetsMatched = frontendAssetPaths.every((path) =>
    expectedBuildInfoAssetPaths.has(path),
  );
  expect(buildInfoAssetsMatched).toBe(true);
  const buildInfoRootEntryMatched = buildInfoRootEntrypoints.every((rootEntrypoint) => {
    const response = frontendAssetResponsesByPath.get(rootEntrypoint.path);
    return response?.resourceType === 'script' &&
      response.bodySha256 === rootEntrypoint.bodySha256;
  });
  expect(buildInfoRootEntryMatched).toBe(true);
  report.runtime = {
    uncaughtPageErrorCount: pageErrors.length,
    frontendAssetPaths,
    frontendAssetResponses,
    buildInfoRootEntryMatched,
    buildInfoAssetsMatched,
  };
  expect(pageErrors).toEqual([]);
  await cdpSession.detach();
});
