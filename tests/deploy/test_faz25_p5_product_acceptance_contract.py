#!/usr/bin/env python3

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Faz25P5ProductAcceptanceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            ROOT / ".github/workflows/verify-faz25-p5-product-surface.yml"
        ).read_text()
        cls.spec = (
            ROOT / "tests/smoke/faz25-p5-product-surface.spec.ts"
        ).read_text()
        cls.config = (
            ROOT / "tests/smoke/playwright.faz25-p5.config.ts"
        ).read_text()
        cls.collector = (
            ROOT / "scripts/deploy/collect-faz25-p5-frontend-lineage.sh"
        ).read_text()
        cls.route_watcher = (
            ROOT / "scripts/deploy/watch-faz25-p5-frontend-routes.sh"
        ).read_text()
        cls.runtime_package = json.loads(
            (ROOT / "tests/smoke/faz25-p5-runtime/package.json").read_text()
        )
        cls.runtime_lock = json.loads(
            (ROOT / "tests/smoke/faz25-p5-runtime/package-lock.json").read_text()
        )
        cls.product_schema = json.loads(
            (ROOT / "tests/smoke/faz25-p5-product-surface.schema.json").read_text()
        )
        cls.manifest_schema = json.loads(
            (ROOT / "tests/smoke/faz25-p5-evidence-manifest.schema.json").read_text()
        )
        cls.lineage_schema = json.loads(
            (ROOT / "tests/smoke/faz25-p5-frontend-lineage.schema.json").read_text()
        )
        cls.route_watch_schema = json.loads(
            (
                ROOT
                / "tests/smoke/faz25-p5-continuous-route-watch.schema.json"
            ).read_text()
        )

    def test_workflow_is_main_only_and_uses_protected_environment_secrets(self):
        self.assertIn('[[ "$GITHUB_REF" == "refs/heads/main" ]]', self.workflow)
        self.assertIn(
            '[[ "$harness_revision" == "$(git rev-parse refs/remotes/origin/main)" ]]',
            self.workflow,
        )
        self.assertIn('canonical_main_at_end=true', self.workflow)
        self.assertIn("environment: testai-product-acceptance", self.workflow)
        self.assertIn("secrets.P5_SMOKE_AUTH_USERNAME", self.workflow)
        self.assertIn("secrets.P5_SMOKE_AUTH_PASSWORD", self.workflow)
        self.assertNotIn("secrets.SMOKE_AUTH_USERNAME", self.workflow)
        self.assertNotIn("secrets.SMOKE_AUTH_PASSWORD", self.workflow)
        self.assertIn("application window not used", self.workflow)
        self.assertIn("Prepare sanitized incomplete-contract diagnostics", self.workflow)
        self.assertIn("Upload sanitized incomplete-contract diagnostics", self.workflow)
        self.assertIn('terminalAcceptance: false', self.workflow)
        self.assertIn("lineage,\n            route", self.workflow)

    def test_locked_browser_runtime_installs_linux_dependencies_noninteractively(self):
        npm_ci = self.workflow.index("npm ci --ignore-scripts --no-audit --no-fund")
        sudo_preflight = self.workflow.index("sudo -n true")
        install = self.workflow.index(
            "./node_modules/.bin/playwright install --with-deps chromium"
        )
        version_probe = self.workflow.index(
            "./node_modules/.bin/playwright --version"
        )
        self.assertLess(npm_ci, sudo_preflight)
        self.assertLess(sudo_preflight, install)
        self.assertLess(install, version_probe)
        self.assertIn("export DEBIAN_FRONTEND=noninteractive", self.workflow)
        self.assertNotIn("npx playwright", self.workflow)
        self.assertIn("serviceWorkers: 'block'", self.config)

        dependencies = self.runtime_package["dependencies"]
        self.assertEqual(dependencies["@playwright/test"], "1.60.0")
        self.assertEqual(dependencies["playwright-core"], "1.60.0")
        for name, tarball in (
            ("@playwright/test", "@playwright/test/-/test-1.60.0.tgz"),
            ("playwright", "playwright/-/playwright-1.60.0.tgz"),
            ("playwright-core", "playwright-core/-/playwright-core-1.60.0.tgz"),
        ):
            package = self.runtime_lock["packages"][f"node_modules/{name}"]
            self.assertEqual(package["version"], "1.60.0")
            self.assertEqual(
                package["resolved"],
                f"https://registry.npmjs.org/{tarball}",
            )
            self.assertRegex(package["integrity"], r"^sha512-[A-Za-z0-9+/]+=*$")

    def test_control_character_scan_uses_real_unicode_range(self):
        corrected = 'test("[\\u0000-\\u001F]")'
        double_escaped = 'test("[\\\\u0000-\\\\u001F]")'
        self.assertEqual(self.workflow.count(corrected), 2)
        self.assertNotIn(double_escaped, self.workflow)

        def jq_matches(value):
            result = subprocess.run(
                [
                    "jq",
                    "-n",
                    "--arg",
                    "value",
                    value,
                    r'$value | test("[\u0000-\u001F]")',
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

        self.assertEqual(jq_matches("PASS https://testai.acik.com"), "false")
        self.assertEqual(jq_matches("line one\nline two"), "true")

    def test_browser_contract_binds_pkce_origin_and_exact_product_sets(self):
        for marker in (
            "callbackCode === exchangeCode",
            "calculatedChallenge === authorizeCodeChallenge",
            "url.origin === issuerOrigin",
            "url.origin === appOrigin",
            "interactiveControlIds).toEqual(expectedInteractiveControlIds)",
            "expect(gateIds).toEqual(expectedGateIds)",
            "expect(headerLabels).toEqual(expectedHeaderLabels)",
            "maxRedirects: 0",
            "expect(buildInfoResponse.url()).toBe(probedBuildInfoUrl)",
            "buildInfoProbeId = randomBytes(16).toString('hex')",
            "buildInfoCacheControl",
            "buildInfoCacheBypassHeadersAbsent",
            "expect(buildInfoResponse.headers()['content-type']).toMatch",
            "expect(Object.keys(buildInfo).sort()).toEqual",
            "expect(report.lineage.buildInfoImageDigest).toBe('')",
            "buildInfoImageDigestStatus: 'NOT_EMBEDDED'",
            "desktopSidebarHref",
            "const desktopSearchQuery = await commandSearch.inputValue()",
            "const mobileViewportWidth = await page.evaluate(() => window.innerWidth)",
            "mobileAtsProductHubActionVisible",
            "expect(capabilityIds).toEqual(expectedCapabilityIds)",
            "expect(targetRoleIds).toEqual(expectedTargetRoleIds)",
            "expect(roleCapabilityCounts).toEqual(expectedRoleCapabilityCounts)",
            "expect(roleCapabilityIds).toEqual(expectedRoleCapabilityIds)",
            "expect(pressedRoleIds).toEqual([roleId])",
            "safeExperienceCapabilityIds",
            "safeScenarioAudit",
            "cvImportInteractiveControlCount",
            "fileUploadControlCount",
            "expectedSyntheticResumeProposalCount",
            "editableAfterFirstKeystroke",
            "acceptAfterEditVisible",
            "rejectAfterEditVisible",
            "rejectAllSecondConfirmationRequired",
            "persistentStoresUnchanged",
            "resumePersistentWriteOperationCount",
            "agenticPersistentStoresUnchanged",
            "agenticPersistentWriteOperationCount",
            "resumeMutationRequestCount",
            "resumeNetworkRequestCount",
            "resumeNetworkChannelConstructionCount",
            "resumeFilePickerInvocationCount",
            "agenticMutationRequestCount",
            "agenticNetworkRequestCount",
            "agenticNetworkChannelConstructionCount",
            "agenticFilePickerInvocationCount",
            "forbiddenActionControlCount",
            "IDBCursor.prototype",
            "CookieStore?.prototype",
            "FileSystemSyncAccessHandle?.prototype",
            "wrapIndexedDbOpenMutation",
            "request.addEventListener('upgradeneeded', recordWrite",
            "opfs.remove",
            "blobSha256",
            "opfsSnapshots",
            "closedAgenticControlSignatures",
            "openedAgenticControlSignatures",
            "completedAgenticControlSignatures",
            "__reactProps$",
            "Closed shadow roots are forbidden",
            "ServiceWorker is forbidden",
            "workerConstructionCount",
            "popupCreationCount",
            "afterDistinctCaptureRegistrations: 2",
            "afterRemovingBubbleRegistration: 1",
            "afterRemovingBothRegistrations: 0",
            "replaceSignatureMultiset",
            "closedShadowRootCount",
            "page.locator('iframe, frame')",
            "mobilePressedRoleIds",
            "mobileSyntheticResumePersistentStoresUnchanged",
            "mobileSyntheticResumeControlsRendered",
            "mobileRoleJourneyCapabilityIds",
            "mobileRoleJourneyEvidenceClass",
            "TOUCH_EXECUTED_UNDER_NAMED_VIEW_PERSONA",
            "Input.dispatchTouchEvent",
            "mobileTouchActivationCount",
            "hubBlockingViolations",
            "desktopHubRendered",
            "mobileHubRendered",
            "mobileRemoteConsoleRendered",
            "frontendAssetPaths",
            "frontendAssetResponses",
            "response.fromServiceWorker()",
            "buildInfoRootEntryMatched",
            "buildInfoAssetsMatched",
            "page.getByRole('button', { name: /Menüyü aç|Open menu/ })",
        ):
            self.assertIn(marker, self.spec)

    def test_browser_contract_maps_owner_by_all_direct_cells_without_waiting(self):
        self.assertIn("toHaveCount(expectedHeaderLabels.length)", self.spec)
        self.assertIn("toHaveCount(expectedGateIds.length)", self.spec)
        self.assertIn("Array.from(row.children)", self.spec)
        self.assertIn("cells.length !== expectedCellCount", self.spec)
        self.assertIn("rows.map((row, rowIndex)", self.spec)
        self.assertIn("ownerCell instanceof HTMLTableCellElement", self.spec)
        self.assertNotIn("locator('td').nth(ownerColumnIndex)", self.spec)

    def test_candidate_boundary_evidence_is_captured_before_filter_reset(self):
        assertion = self.spec.index(
            "toContainText('Bu yönetici adresi adaya verilmez')"
        )
        capture = self.spec.index(
            "const candidateBoundaryVisible = await candidateBoundary.isVisible()"
        )
        reset = self.spec.index("const allRolesFilter =")
        report = self.spec.index("report.hub =")
        self.assertLess(assertion, capture)
        self.assertLess(capture, reset)
        self.assertLess(reset, report)
        self.assertIn("candidateBoundaryVisible,", self.spec[report:])
        self.assertNotIn(
            "candidateBoundaryVisible: await candidateBoundary.isVisible()",
            self.spec[report:],
        )

    def test_synthetic_resume_and_agentic_acceptance_stay_local_and_editable(self):
        first_key = "await emailInput.pressSequentially('a')"
        remaining_keys = (
            "await emailInput.pressSequentially('day.duzenlendi@example.invalid')"
        )
        editability_probe = (
            "const editableAfterFirstKeystroke = "
            "(await emailInput.getAttribute('readonly')) === null"
        )
        self.assertIn(first_key, self.spec)
        self.assertIn(remaining_keys, self.spec)
        self.assertIn(editability_probe, self.spec)
        self.assertLess(self.spec.index(first_key), self.spec.index(editability_probe))
        self.assertLess(self.spec.index(editability_probe), self.spec.index(remaining_keys))
        self.assertNotIn("emailInput.fill(expectedEditedEmail)", self.spec)
        self.assertIn("expect(resumeMutationRequestCount).toBe(0)", self.spec)
        self.assertIn("expect(agenticMutationRequestCount).toBe(0)", self.spec)
        self.assertNotIn("page.off('request'", self.spec)
        self.assertNotIn("page.context().off('page'", self.spec)
        self.assertIn("readJourneyLifecycleAudit", self.spec)
        self.assertIn("roleJourneyCapabilityIds", self.spec)
        self.assertIn("expect(persistentStoresUnchanged).toBe(true)", self.spec)
        self.assertIn(
            "expect(resumePersistentWriteOperationCount).toBe(0)", self.spec
        )
        self.assertIn(
            "expect(agenticPersistentStoresUnchanged).toBe(true)", self.spec
        )
        self.assertIn(
            "expect(agenticPersistentWriteOperationCount).toBe(0)", self.spec
        )
        self.assertIn("expect(forbiddenActionControlCount).toBe(0)", self.spec)
        for state in ("closed", "opened", "completed"):
            self.assertIn(
                f"expect({state}AgenticControlSignatures).toEqual(", self.spec
            )

    def test_persistent_storage_guard_resolves_the_webidl_descriptor_owner(self):
        installer_start = self.spec.index(
            "const installStorageProxy = (property: 'localStorage' | 'sessionStorage')"
        )
        installer_end = self.spec.index(
            "installStorageProxy('localStorage')", installer_start
        )
        installer = self.spec[installer_start:installer_end]

        self.assertIn("let descriptorOwner: object | null = window", installer)
        self.assertIn("while (descriptorOwner)", installer)
        self.assertIn(
            "Object.getOwnPropertyDescriptor(descriptorOwner, property)",
            installer,
        )
        self.assertIn(
            "Object.getPrototypeOf(descriptorOwner) as object | null",
            installer,
        )
        self.assertIn(
            "Object.defineProperty(descriptorOwner, property", installer
        )
        self.assertIn(
            "instrumentationFailures.push(`${property}.native-getter`)",
            installer,
        )
        self.assertNotIn(
            "const windowPrototype = Object.getPrototypeOf(window)", installer
        )

    def test_product_journey_popup_ledger_starts_after_active_page_guard(self):
        popup_listener = self.spec.index("page.context().on('page', (openedPage)")
        navigation_listener = self.spec.index(
            "openedPage.on('framenavigated', (frame)", popup_listener
        )
        close_listener = self.spec.index(
            "openedPage.on('close', recordMainFrameUrl)", navigation_listener
        )
        inert_policy = self.spec.index("const popupHistoryIsInert =")
        inert_policy_url_guard = self.spec.index(
            "observedMainFrameUrls[0] === 'about:blank'", inert_policy
        )
        negative_control = self.spec.index(
            "const popupLedgerNegativeControlPage = await page.context().newPage()",
            inert_policy_url_guard,
        )
        negative_control_rejection = self.spec.index(
            "popupHistoryIsInert([", negative_control
        )
        active_page_guard = self.spec.index(
            "const activeSecondaryPagesAtProductJourneyStart = page",
            negative_control_rejection,
        )
        history_snapshot = self.spec.index(
            "const preJourneyPopupHistory = unexpectedPopupPages.map",
            active_page_guard,
        )
        active_page_assertion = self.spec.index(
            "expect(activeSecondaryPagesAtProductJourneyStart).toEqual([])",
            history_snapshot,
        )
        bounded_history_assertion = self.spec.index(
            "expect(preJourneyPopupHistory.length).toBeLessThanOrEqual(1)",
            active_page_assertion,
        )
        inert_history_assertion = self.spec.index(
            "expect(popupHistoryIsInert(preJourneyPopupHistory)).toBe(true)",
            bounded_history_assertion,
        )
        ledger_reset = self.spec.index(
            "unexpectedPopupPages.length = 0", inert_history_assertion
        )
        journey_start = self.spec.index(
            "const productJourneyAuditStart = await page.evaluate", ledger_reset
        )
        no_product_popup = self.spec.index(
            "expect(unexpectedPopupPages).toEqual([])", journey_start
        )

        self.assertIn(
            "candidatePage !== page && !candidatePage.isClosed()",
            self.spec[active_page_guard:history_snapshot],
        )
        self.assertIn(
            "frame === openedPage.mainFrame()",
            self.spec[navigation_listener:close_listener],
        )
        self.assertIn(
            "observedMainFrameUrls.length === 1",
            self.spec[inert_policy:inert_policy_url_guard],
        )
        self.assertIn(
            "'data:text/html,popup-ledger-negative-control'",
            self.spec[negative_control:negative_control_rejection],
        )
        self.assertIn(
            ").toBe(false)",
            self.spec[negative_control_rejection:active_page_guard],
        )
        self.assertLess(popup_listener, navigation_listener)
        self.assertLess(navigation_listener, close_listener)
        self.assertLess(close_listener, inert_policy)
        self.assertLess(inert_policy_url_guard, negative_control)
        self.assertLess(negative_control, negative_control_rejection)
        self.assertLess(negative_control_rejection, active_page_guard)
        self.assertLess(active_page_guard, active_page_assertion)
        self.assertLess(active_page_assertion, bounded_history_assertion)
        self.assertLess(bounded_history_assertion, inert_history_assertion)
        self.assertLess(active_page_assertion, ledger_reset)
        self.assertLess(ledger_reset, journey_start)
        self.assertLess(journey_start, no_product_popup)

    def test_role_filter_transitions_prove_exclusive_selection(self):
        self.assertIn(
            "expect(pressedRoleIds).toEqual([roleId])", self.spec
        )
        self.assertIn(
            "expect(await readPressedRoleIds()).toEqual(['candidate'])",
            self.spec,
        )
        self.assertIn("expect(await readPressedRoleIds()).toEqual(['all'])", self.spec)

    def test_browser_launch_uses_the_versioned_and_hashed_executable(self):
        self.assertIn("printf 'chromium_path=%s\\n' \"$chromium_path\"", self.workflow)
        self.assertIn("tr -d '\\r'", self.workflow)
        self.assertIn("P5_CHROMIUM_EXECUTABLE_PATH", self.workflow)
        self.assertIn(
            '[[ "$launch_chromium_sha256" == "$P5_CHROMIUM_EXECUTABLE_SHA256" ]]',
            self.workflow,
        )
        self.assertIn(
            '"Google Chrome for Testing 148.0.7778.96"',
            self.workflow,
        )
        self.assertIn("P5_CHROMIUM_EXECUTABLE_PATH is required", self.config)
        self.assertIn("executablePath: chromiumExecutablePath", self.config)

    def test_lineage_collector_binds_owner_chain_and_observed_image_id(self):
        self.assertIn('.metadata.ownerReferences[]?', self.collector)
        self.assertIn('.imageID | endswith("@" + $digest)', self.collector)
        self.assertIn("EXPECTED_BUILD_RUN_ID", self.collector)
        self.assertIn('observed_digest="$(jq -r', self.collector)
        self.assertIn('mv "$report_tmp" "$REPORT_PATH"', self.collector)
        self.assertIn("EXPECTED_CLUSTER_CA_SHA256", self.collector)
        self.assertIn("EXPECTED_KUBE_SYSTEM_UID", self.collector)
        self.assertNotIn("buildProvenanceReceiptSha256", self.collector)
        self.assertNotIn("slsaProvenanceDigest", self.collector)
        self.assertIn('buildAttestationStatus: $build_attestation_status', self.collector)
        self.assertIn("METADATA_ONLY_NON_TERMINAL", self.collector)
        self.assertIn("Terminal browser-to-image binding", self.collector)
        self.assertIn('get ingress platform -o json', self.collector)
        self.assertIn('get service frontend -o json', self.collector)
        self.assertIn('get endpointslices', self.collector)
        self.assertIn('.targetRef.uid]', self.collector)
        self.assertIn('get --raw', self.collector)
        self.assertIn('get ingress -A -o json', self.collector)
        self.assertIn('matchingRoutes: $matching_ingress_routes', self.collector)
        self.assertIn('readyPodNetworkBindings: $endpoint_network_bindings', self.collector)
        self.assertIn('podBuildInfoSha256s: $pod_build_info_hashes', self.collector)
        self.assertNotIn("GITHUB_TOKEN", self.collector)

    def test_pass_schema_requires_terminal_product_evidence(self):
        then_clause = self.product_schema["allOf"][0]["then"]
        self.assertEqual(
            then_clause["required"],
            [
                "authz",
                "discovery",
                "hub",
                "product",
                "responsive",
                "accessibility",
                "runtime",
            ],
        )
        discovery = then_clause["properties"]["discovery"]["allOf"][1]["properties"]
        self.assertTrue(discovery["desktopSidebarVisible"]["const"])
        self.assertEqual(
            discovery["desktopSidebarHref"]["const"],
            "/admin/ats",
        )
        self.assertEqual(discovery["desktopSearchQuery"]["const"], "mülakat")
        self.assertEqual(discovery["mobileViewportWidth"]["const"], 390)
        self.assertEqual(discovery["desktopHubPath"]["const"], "/admin/ats")
        self.assertEqual(
            discovery["desktopLaunchPath"]["const"],
            "/admin/interview-evidence",
        )
        self.assertTrue(discovery["mobileRemoteConsoleRendered"]["const"])
        self.assertFalse(
            self.product_schema["definitions"]["discovery"]["additionalProperties"]
        )
        hub = then_clause["properties"]["hub"]["allOf"][1]["properties"]
        self.assertEqual(hub["visibleCapabilityCount"]["const"], 9)
        self.assertEqual(len(hub["targetRoleIds"]["const"]), 6)
        self.assertEqual(
            hub["roleCapabilityCounts"]["const"],
            {
                "candidate": 3,
                "recruiter": 8,
                "hiring_manager": 6,
                "interviewer": 3,
                "auditor": 7,
                "admin": 6,
            },
        )
        self.assertEqual(hub["cvImportMode"]["const"], "OWNER_GATED")
        self.assertEqual(hub["cvImportInteractiveControlCount"]["const"], 1)
        self.assertEqual(hub["fileUploadControlCount"]["const"], 0)
        synthetic_resume = hub["syntheticResume"]["properties"]
        self.assertEqual(synthetic_resume["proposalCount"]["const"], 5)
        self.assertTrue(synthetic_resume["editableAfterFirstKeystroke"]["const"])
        self.assertTrue(synthetic_resume["acceptAfterEditVisible"]["const"])
        self.assertTrue(synthetic_resume["rejectAfterEditVisible"]["const"])
        self.assertTrue(
            synthetic_resume["rejectAllSecondConfirmationRequired"]["const"]
        )
        self.assertTrue(synthetic_resume["persistentStoresUnchanged"]["const"])
        self.assertEqual(
            synthetic_resume["persistentWriteOperationCount"]["const"], 0
        )
        self.assertEqual(synthetic_resume["mutationQuietPeriodMs"]["const"], 1000)
        self.assertEqual(synthetic_resume["mutationRequestCount"]["const"], 0)
        self.assertEqual(synthetic_resume["workerConstructionCount"]["const"], 0)
        self.assertEqual(synthetic_resume["popupCreationCount"]["const"], 0)
        self.assertEqual(
            synthetic_resume["unsafeDelegatedActionListenerCount"]["const"], 0
        )
        agentic = hub["agentic"]["properties"]
        self.assertEqual(agentic["mode"]["const"], "PROPOSAL_ONLY")
        self.assertEqual(
            agentic["interactiveControlSignatures"]["const"],
            {
                "closed": ["BUTTON:button:Ajan önerisini güvenle dene"],
                "opened": [
                    "BUTTON:button:Güvenli denemeyi kapat",
                    "BUTTON:button:Sentetik çıktıyı üret",
                ],
                "completed": [
                    "BUTTON:button:Denemeyi sıfırla",
                    "BUTTON:button:Güvenli denemeyi kapat",
                ],
            },
        )
        self.assertEqual(agentic["forbiddenActionControlCount"]["const"], 0)
        self.assertTrue(agentic["persistentStoresUnchanged"]["const"])
        self.assertEqual(agentic["persistentWriteOperationCount"]["const"], 0)
        self.assertEqual(agentic["mutationQuietPeriodMs"]["const"], 1000)
        self.assertEqual(agentic["mutationRequestCount"]["const"], 0)
        self.assertEqual(agentic["workerConstructionCount"]["const"], 0)
        self.assertEqual(agentic["popupCreationCount"]["const"], 0)
        self.assertEqual(agentic["unsafeDelegatedActionListenerCount"]["const"], 0)
        self.assertFalse(self.product_schema["definitions"]["hub"]["additionalProperties"])
        self.assertFalse(
            self.product_schema["definitions"]["hub"]["properties"]
            ["syntheticResume"]["additionalProperties"]
        )
        self.assertFalse(
            self.product_schema["definitions"]["hub"]["properties"]
            ["agentic"]["additionalProperties"]
        )
        responsive = then_clause["properties"]["responsive"]["allOf"][1][
            "properties"
        ]
        self.assertTrue(responsive["mobileSyntheticResumeControlsRendered"]["const"])
        self.assertTrue(
            responsive["mobileSyntheticResumePersistentStoresUnchanged"]["const"]
        )
        self.assertEqual(
            responsive["mobileSyntheticResumePersistentWriteOperationCount"]["const"],
            0,
        )
        self.assertEqual(
            responsive["mobileSyntheticResumeMutationRequestCount"]["const"], 0
        )
        self.assertEqual(
            responsive["mobileSyntheticResumeWorkerConstructionCount"]["const"], 0
        )
        self.assertEqual(
            responsive["mobileSyntheticResumePopupCreationCount"]["const"], 0
        )
        self.assertEqual(
            responsive["mobileSyntheticResumeUnsafeDelegatedActionListenerCount"]["const"],
            0,
        )
        self.assertEqual(
            then_clause["properties"]["product"]["allOf"][1]["properties"]
            ["ownerAcceptance"]["const"],
            "0/8",
        )
        self.assertEqual(
            then_clause["properties"]["accessibility"]["allOf"][1]["properties"]
            ["blockingViolationCount"]["const"],
            0,
        )
        self.assertNotIn(
            "loginBlockingViolationCount",
            self.product_schema["definitions"]["authentication"]["required"],
        )
        self.assertIn(
            "loginBlockingViolationCount",
            then_clause["properties"]["authentication"]["allOf"][1]["required"],
        )

    def test_lineage_schema_requires_strict_live_route_to_ready_pod_chain(self):
        self.assertIn("route", self.lineage_schema["required"])
        route = self.lineage_schema["properties"]["route"]
        self.assertFalse(route["additionalProperties"])
        self.assertEqual(route["properties"]["host"]["const"], "testai.acik.com")
        self.assertEqual(
            route["properties"]["ingress"]["properties"]["serviceName"]["const"],
            "frontend",
        )
        self.assertEqual(
            route["properties"]["service"]["properties"]["selector"]["const"],
            {"app.kubernetes.io/name": "frontend"},
        )
        self.assertTrue(
            route["properties"]["endpointSlices"]["properties"]["readyPodUids"][
                "uniqueItems"
            ]
        )
        self.assertIn(
            "matchingRoutes",
            route["properties"]["ingress"]["required"],
        )
        self.assertIn(
            "readyPodNetworkBindings",
            route["properties"]["endpointSlices"]["required"],
        )
        self.assertIn("podBuildInfoSha256s", route["required"])
        self.assertIn("browserAssetBinding", route["required"])
        self.assertEqual(
            route["properties"]["podBuildInfoSha256s"]["maxItems"], 1
        )
        bound_asset = route["properties"]["browserAssetBinding"]["oneOf"][1]
        self.assertFalse(bound_asset["additionalProperties"])
        self.assertEqual(
            set(bound_asset["required"]),
            {
                "status",
                "browserAssetEvidenceSha256",
                "assetCount",
                "podCount",
                "podAssetBindings",
            },
        )
        self.assertIn("EXPECTED_BROWSER_REPORT_PATH", self.workflow)
        self.assertIn("browser_asset_pod_matched", self.workflow)

    def test_manifest_schema_requires_one_child_of_each_source(self):
        children_rules = self.manifest_schema["allOf"][2]["properties"]["children"]
        kinds = {
            rule["contains"]["properties"]["kind"]["const"]
            for rule in children_rules["allOf"]
        }
        self.assertEqual(
            kinds,
            {"browser", "lineage-pre", "lineage-post", "route-watch"},
        )

    def test_workflow_continuously_binds_routes_around_browser(self):
        watcher_start = self.workflow.index("watch-faz25-p5-frontend-routes.sh")
        browser_start = self.workflow.index("./node_modules/.bin/playwright test")
        watcher_stop = self.workflow.index(': > "$P5_ROUTE_WATCH_STOP"')
        watcher_wait = self.workflow.index('wait "$route_watch_pid"')
        self.assertLess(watcher_start, browser_start)
        self.assertLess(browser_start, watcher_stop)
        self.assertLess(watcher_stop, watcher_wait)
        self.assertIn("continuousRouteWatchPassed", self.workflow)
        self.assertIn("faz25-p5-continuous-route-watch.schema.json", self.workflow)
        self.assertIn("route-watch.json evidence-manifest.json", self.workflow)

        self.assertFalse(self.route_watch_schema["additionalProperties"])
        self.assertEqual(
            self.route_watch_schema["properties"]["intervalMilliseconds"]["const"],
            250,
        )
        pass_properties = self.route_watch_schema["allOf"][0]["then"][
            "properties"
        ]
        self.assertEqual(pass_properties["violationCount"]["const"], 0)
        self.assertEqual(pass_properties["sampleCount"]["minimum"], 2)
        self.assertTrue(pass_properties["eventWatchEstablished"]["const"])
        self.assertEqual(pass_properties["eventCount"]["const"], 0)
        self.assertEqual(pass_properties["eventWatchErrorSha256"]["const"], "")
        self.assertIn("finalResourceVersion", pass_properties)
        self.assertIn(
            ".finalResourceVersion == .eventWatchResourceVersion", self.workflow
        )
        self.assertEqual(pass_properties["browserAssetPathCount"]["minimum"], 1)
        self.assertIn("browserAssetPathsSha256", pass_properties)
        self.assertNotIn("--resource-version=", self.route_watcher)
        self.assertNotIn("--watch-only", self.route_watcher)
        self.assertIn(
            'INGRESS_LIST_PATH="/apis/networking.k8s.io/v1/ingresses"',
            self.route_watcher,
        )
        self.assertIn('get --raw "$INGRESS_LIST_PATH"', self.route_watcher)
        self.assertIn(
            '?watch=true&allowWatchBookmarks=false&resourceVersion=${event_watch_resource_version}',
            self.route_watcher,
        )
        self.assertIn('get --raw "$ingress_watch_path"', self.route_watcher)
        self.assertIn("route-event-watch-error", self.route_watcher)
        self.assertIn("eventWatchErrorSha256", self.route_watcher)
        self.assertNotIn(
            'get ingress -A -o json',
            self.route_watcher,
        )
        self.assertIn("route-event-observed", self.route_watcher)
        self.assertIn("browser-asset-route-policy-failure", self.route_watcher)
        self.assertIn("--additional-request-path", self.route_watcher)
        self.assertIn(
            "jq -cS '.runtime.frontendAssetPaths'",
            self.route_watcher,
        )
        self.assertIn(
            "printf '%s\\n' \"$browser_asset_paths_json\"",
            self.workflow,
        )

    def test_manifest_fail_branch_is_strict_diagnostic_only(self):
        self.assertFalse(self.manifest_schema["additionalProperties"])
        fail_then = self.manifest_schema["allOf"][1]["then"]
        self.assertEqual(
            fail_then["properties"]["artifactKind"]["const"],
            "diagnostic",
        )
        binding = self.manifest_schema["properties"]["binding"]
        self.assertFalse(binding["additionalProperties"])
        self.assertEqual(
            set(binding["required"]),
            {
                "canonicalMainAtStart",
                "canonicalMainAtEnd",
                "prePostSameSession",
                "browserPodBuildInfoMatched",
                "browserIngressLogMatched",
                "browserAssetPodMatched",
                "continuousRouteWatchPassed",
                "freshWithinRun",
                "strictChildSchemas",
                "sensitiveValueScanPassed",
            },
        )

        stderr_watch_rule = self.route_watch_schema["allOf"][2]
        self.assertEqual(
            stderr_watch_rule["if"]["properties"]["failureReason"]["const"],
            "route-event-watch-stderr-observed",
        )
        self.assertEqual(
            stderr_watch_rule["then"]["properties"]["eventWatchErrorSha256"][
                "pattern"
            ],
            "^[0-9a-f]{64}$",
        )

    def test_failed_browser_report_can_preserve_desktop_audit_before_mobile_runs(self):
        journey = self.product_schema["definitions"]["hub"]["properties"][
            "journeyLifecycleAudit"
        ]
        self.assertEqual(journey["required"], ["desktop"])
        pass_hub = self.product_schema["allOf"][0]["then"]["properties"]["hub"]
        pass_constraints = pass_hub["allOf"][1]["properties"]
        self.assertIn("mobile", pass_constraints["journeyLifecycleAudit"]["const"])


if __name__ == "__main__":
    unittest.main()
