# Faz 22.5 — Software Deployment Quick Wins

> **Status**: SOURCE-MERGED + testai LIVE for catalog/inventory/compliance/preflight/audit; AG-027L installer log redaction SOURCE-MERGED 2026-05-29 PM (platform-agent PR #32 `4f5e152`); **First Install Pilot LIVE 2026-05-31** ([#1133 GREEN](https://github.com/Halildeu/platform-k8s-gitops/issues/1133) — `be021-smoke-7zip` SUCCEEDED end-to-end on HALILKOOLUB735 SYSTEM Session-0 ARM64 Win11; UI "Başarılı" 12:37:27; true root cause 3-layer fix: backend PR #338 contract gap + agent PR #41 `winget list` Session-0 unreliable → INSTALL exit code authoritative + `0x8A150061` → SUCCEEDED_NOOP); **WEB-014D-followup discovered 2026-06-01** — `InstallPreflightModal.tsx` "Kurulumu Onayla" footer button disabled regression on catalog rows with PASS preflight (operator-confirmed across multiple catalog items); REST workaround verified backend POST contract still healthy (commandId `4d3c097f-7842-4ec2-8c7f-a60465a1b01c` 201 CREATED) — bug is frontend-only; agent re-pickup pending operator service restart
> **Tracked by**: platform-k8s-gitops#1083, platform-k8s-gitops#1086, platform-k8s-gitops#1088, platform-k8s-gitops#1090
> **Scope date**: 2026-05-27 (initial 3-AI mutabakatı); **truth refresh 2026-05-29**

> **Truth refresh 2026-05-29 (this section was superseded 2026-05-31)**: source chain
> (catalog + ingest + preflight + compliance + adapter + audit + ingest
> backend + frontend) MERGED across 4 repos; testai deployed for backend
> + frontend slices. End-to-end LIVE smoke (7-Zip catalog seed →
> preflight PASS → dispatch → agent install → result submit → UI render)
> **was pending as of 2026-05-29; superseded 2026-05-31 (#1133 GREEN)** —
> end-to-end on the genuine `EndpointAgent` service under SYSTEM Session-0
> ARM64 Win11 produced `be021-smoke-7zip · PASS · Başarılı` (command
> `70a852b4-e87b-4060-8ac9-bb1dd97c1245`); 3-layer root cause sealed (see
> §0.1bis status banner). AG-027L installer log redaction SOURCE-MERGED (PR #32 `4f5e152`) — binary distributed to HALILKOOLUB735 + service health PASS; the 2026-05-31 GREEN smoke went end-to-end through the AG-027L redacted wire path with no observable leak. Explicit deep-trace redaction evidence collection (intentional sensitive payload → verify StdoutTail/StderrTail scrubbing) is a separate lower-priority followup. AG-028 uninstall
> + AG-029 self-update + AG-030/031/032/033 posture + AG-036/037/038/039/040
> diagnostics still TODO. See `docs/state/current-state.md`
> "2026-05-29 PM" delta for honest acceptance gate map and live evidence.
>
> **2026-06-01 supersession**: AG-030/031/032/033 SOURCE-MERGED (PRs #33/#34/
> #35/#36, Codex cross-AI AGREE; binary distribution operator-bound); AG-036
> SOURCE-MERGED + Flyway V20 applied on testai; **AG-037 MERGED + LIVE
> end-to-end** (agent #45 + backend #354/#355 + web #723 + gitops #1167/
> #1168 + HALILKOOLUB735 86 installed + 1 pending WUA telemetry browser-
> smoked). The 2026-05-29 PM "TODO" assertions above are STALE for
> AG-030/031/032/033/036/037; AG-038/039/040 remain TODO. See
> `docs/state/current-state.md` "AG-037 Hotfix Posture LIVE END-TO-END
> VERIFIED (2026-06-01)" delta for canonical truth.

Bu doküman Endpoint-Enes / Endpoint Admin agent hattına **ücretsiz ve sektör
standardına yakın yazılım yönetimi** kabiliyeti eklemek için takip edilebilir
planı tanımlar.

Bu plan install/uninstall runtime kabiliyeti iddia etmez. 2026-05-27 üç-AI
değerlendirmesi (Claude Code + Codex + MiniMax/Mavis) ortak hükmü **REVISE**:
read-only agent temeli doğru yönde başlamış, fakat program kurma kabiliyeti
`BE-020` catalog, command contract, detection/result/audit ve web yüzeyi
gelmeden açılmayacak.

### 0.1 Current Implementation Truth (2026-05-27 — superseded by §0.1bis 2026-05-29)

> The table below is the **2026-05-27** scope-anchor snapshot. For the
> 2026-05-29 truth refresh see §0.1bis. Rows here retained verbatim
> for audit / cross-AI mutabakatı reconstructibility.



| Alan | Repo | Güncel truth | Hüküm |
|---|---|---|---|
| Installed software inventory | `platform-agent` | `0eff2db` / PR #20 ile `internal/software` var; HKLM + HKLM `WOW6432Node` uninstall registry okunuyor, HKCU default dışı | SOURCE-PARTIAL |
| WinGet readiness | `platform-agent` | `internal/winget` yalnız `winget --version` probe eder; install/search/source/upgrade yok | SOURCE-PARTIAL |
| Inventory command | `platform-agent` | `COLLECT_INVENTORY` payload `includeSoftware` okuyabiliyor; full app list yalnız `includeSoftware=true` ile dönmeli | SOURCE-PARTIAL |
| Hardware/device inventory (agent probe) | `platform-agent` | AG-035 MERGED 2026-05-28 (PR #24 `ef83531c`) — `internal/inventory/hardware.go` + Windows PowerShell + Get-CimInstance probe + cross-platform stub; `COLLECT_INVENTORY` includeHardware payload bit + schemaVersion=1 + all-null CIM_NO_DATA guard + macAddress wire fix; SRB binary distribution pending | SOURCE-MERGED (binary distribution operator-bound) |
| Hardware/device inventory (backend ingest) | `platform-backend` | BE-022 V14 MERGED + LIVE 2026-05-28: V13 migration (snapshot + disks + network_interfaces composite-FK + DB CHECK) + entities + HardwareInventoryPayloadPolicy + EndpointHardwareInventoryService idempotent ingest + agent SUBMIT hook; V14 ALTER TABLE payload_hash_sha256 VARCHAR(64) fix | LIVE (testai) |
| Hardware/device inventory (backend query) | `platform-backend` | BE-022Q MERGED + LIVE 2026-05-28 (PR #325 `4ff2ceb4`, gitops #1124 `f29d7b17`) — AdminEndpointHardwareInventoryController GET /latest (200/404) + GET /history (Page<SummaryResponse>) + 4 whitelist DTOs + @Transactional(readOnly=true) lazy guard + Page cap 20/50 + module:endpoint-admin can_view RBAC; cluster pod imageID match initial digest `sha256:c895cfd60d64...` (sha-4ff2ceb); **superseded 2026-05-29** by sha-e3a0369 / `sha256:76bacc004f...` after backend #326 + gitops #1130 | LIVE (testai) |
| Hardware/device inventory (frontend view) | `platform-web` | WEB-013 source-ready 2026-05-28 (PR #700) — DTO types + RTK Query endpoints on gateway path + DeviceDetailDrawer 7th lazy "Donanım" tab + HardwareInventoryView (latest summary + disks + NICs + history accordion + 404 empty + 403 forbidden + currentData stale guard + tri-state domain) + i18n TR+EN + 8 RTL tests; Codex iter-2 AGREE; merge + frontend digest bump + browser smoke pending | SOURCE-READY (CI/merge pending) |
| WinGet source / egress readiness | `platform-agent` | `AG-026` yalnız version probe eder; source list, App Installer, Store source, proxy/TLS ve package query readiness yok | MISSING |
| Install dry-run / preflight | `platform-backend` + `platform-agent` | Approved catalog item için install öncesi dry-run / preflight contract yok | MISSING |
| Software compliance / drift | `platform-backend` + `platform-web` | Approved catalog'a göre compliant/outdated/unknown/prohibited status ve inventory diff/history yok | MISSING |
| Agent diagnostics | `platform-agent` + `platform-web` | Agent self-health, backend connectivity, WinGet source connectivity, critical service ve event summary paneli yok | MISSING |
| Approved catalog | `platform-backend` | catalog entity/API/migration yok | MISSING |
| Install command contract | `platform-backend` + `platform-agent` | `INSTALL_APPROVED_SOFTWARE` / `INSTALL_SOFTWARE` command type ve executor yok | MISSING |
| Software / device UI | `platform-web` | `InventoryTab` software/apps/winget readiness ve hardware/device payload parse etmiyor | MISSING |
| GitOps governance | `platform-k8s-gitops` | plan/runbook var; bu revizyon üç-AI mutabakatını işler | SOURCE-PARTIAL |

### 0.1bis Truth Refresh (2026-05-29)

| Alan | Repo | 2026-05-29 truth | Hüküm |
|---|---|---|---|
| Installed software inventory | `platform-agent` | `0eff2db` PR #20 + `f3b5c68` PR #21 (AG-025H lightweight guard); HKLM + HKLM `WOW6432Node` registry; HKCU default-off | LIVE (deployed binaries on HALILKOOLUB735) |
| WinGet readiness + source/egress | `platform-agent` | PR #22 AG-026A source/egress preflight + PR #25 `1e915a2` defensive wire shape; `winget --version` + source list + Store/App Installer state + DNS/TCP/HTTPS egress probes; full PowerShell + Get-CimInstance probe; `winget install` yok | LIVE (HALILKOOLUB735 verified 2026-05-29) |
| Inventory command (includeSoftware/Hardware) | `platform-agent` | PR #20/21/24 — `COLLECT_INVENTORY` includeSoftware + includeHardware payload bits + schemaVersion=1 + redaction policy + macAddress wire fix | LIVE |
| Hardware/device inventory (agent probe) | `platform-agent` | PR #24 AG-035 (`ef83531c`) hardware probe + cross-platform stub; SRB binary distribution operator-bound; HALILKOOLUB735 LIVE | LIVE (HALILKOOLUB735) / pending SRB distribution |
| Hardware/device inventory (backend ingest + query) | `platform-backend` | BE-022 V13/V14 PR #322/#324 + BE-022Q PR #325 (`4ff2ceb4`) — sanitizer + ingest + query API + history; cluster live digest 2026-05-29 = `sha256:76bacc004f...` (sha-e3a0369 after backend #326 + gitops #1130; sha-4ff2ceb / `sha256:c895cfd60d64...` superseded). NOTE: backend #326 review surfaced a `lower(bytea)` SQL grammar issue on payload_hash query path; BE-022Q LIVE = ingest + /history routes verified; deep equality query path partial pending fix follow-up | LIVE (testai, partial query bug pending) |
| Hardware/device inventory (frontend view) | `platform-web` | PR #700 WEB-013 + LIVE on testai; DeviceDetailDrawer Donanım tab + history accordion; UI smoke 2026-05-29 PASS | LIVE |
| Operator enrollment friction | `platform-agent` | PR #26 AG-026D (DPAPI HMAC persistence) + PR #27 AG-026C (install.ps1 service env regkey) + PR #28 AG-026B (`--enrollment-token` CLI) + PR #29 AG-026C `-Force` splat fix (`97edf17`); HALILKOOLUB735 hydrate proof + sentinel gate | LIVE (HALILKOOLUB735) |
| Approved software catalog | `platform-backend` | BE-020 PR #306 PR-A + PR #308 PR-B (`5033f1c6`) — V7 sequence guard + entity + repo + service + audit + validator + REST + RBAC + MockMvc | LIVE (testai) |
| Software inventory ingest/query | `platform-backend` | BE-020I PR #310 (`54d5dcf8`) + #311 (`79dba92d`) shape fix — agent `details.inventory.software` ingest path + query surface | LIVE (testai) |
| Install dry-run / preflight | `platform-backend` | BE-021A PR #312 (`dd5df4c0`) — `POST /endpoint-devices/{id}/install-preflight` PASS/WARN/BLOCK contract; recompute-at-create gate | LIVE (testai) |
| Install command contract + audit + detection | `platform-backend` | BE-021 PR #317 (`305561df`) + V12 dynamic CHECK drop #318 + Mockito guard #321 + AdminEndpointInstallController dedicated `POST /endpoint-devices/{id}/installs` endpoint with manager RBAC + preflight recompute gate | LIVE (testai) |
| Install execution adapter (agent) | `platform-agent` | PR #23 AG-027 (`7cf6f14`) — `install_winget` core decision pipeline + Windows runner with Job Object + taskkill fallback + non-Windows stub + executor wiring; HARD BOUNDARIES (fail-closed on unsupported detection rule, enum args policy, pre-detect, post-verify, 30-min cap); **+ PR #41 winget-list-Session-0 fix (2026-05-31 Codex 019e7d3d AGREE) — winget INSTALL exit code is install-state authority, `winget list` confirm-only, `0x8A150061` → SUCCEEDED_NOOP** | **LIVE 2026-05-31** (#1133 GREEN — `be021-smoke-7zip · Başarılı` end-to-end under SYSTEM Session-0 ARM64 Win11) |
| Installer exit-code / redacted log capture | `platform-agent` | AG-027L SOURCE-MERGED 2026-05-29 PM (PR #32 `4f5e152`): `RedactInstallerString` 3 pattern classes (URL userinfo / MSI property assignments / token-bearing query params) layered on AG-025/AG-026 baseline + `sanitizeForWire` switched to layered redaction + COMMAND-CONTRACT.md §11.3a documents policy. Binary distributed + service health PASS; **LIVE smoke proven 2026-05-31** (the #1133 GREEN end-to-end smoke went through the AG-027L redacted wire path — agent's INSTALL_SOFTWARE result was reported via the redacted Stdout/StderrTail emit, UI rendered audit row with no observable leak); backend POST contract re-verified 2026-06-01 (commandId `4d3c097f-7842-4ec2-8c7f-a60465a1b01c`). Explicit deep-trace evidence collection (intentional sensitive payload installer → verify each pattern class) is a separate lower-priority followup. | SOURCE-MERGED + LIVE smoke 2026-05-31 (#1133 GREEN); deep-trace evidence followup pending |
| Software compliance evaluator | `platform-backend` | BE-023 PR #313 (`7ea090c5`) + PR #314 (`6144eb91`) JPMS --add-opens + PR #315 (`4aa29dd0`) ObjectProvider — COMPLIANT/NON_COMPLIANT/UNAUTHORIZED/UNKNOWN evaluator + AFTER_COMMIT listener + V10 migration + DTOs/controllers | LIVE (testai) |
| Software inventory view (UI) | `platform-web` | WEB-011 LIVE + cluster apply | LIVE |
| Software compliance view (UI) | `platform-web` | WEB-014A/B/C/D MERGED + LIVE (Compliance Tab + cross-device list + per-device history + Policy CRUD UI + WEB-014D follow-up PR Codex absorb) | LIVE |
| Endpoint Enrollment Management UI | `platform-web` | WEB-017 MERGED + LIVE | LIVE |
| Inventory trigger UI | `platform-web` | WEB-018 MERGED + LIVE (Envanteri Şimdi Topla payload + Donanım dedicated trigger) | LIVE |
| Approved install dispatch UI | `platform-web` | WEB-012 ≡ WEB-014D (PR #683 + perf #693 follow-up Codex absorb) — `SoftwareCatalogTab.tsx` "Kur" button per catalog row + `InstallPreflightModal.tsx` PASS/WARN/BLOCK → `useCreateInstallMutation()` dispatch POST + "Son Kurulumlar" audit panel via `useListInstallAuditsQuery` Page.content render | **MERGED + LIVE** |
| Outdated software / inventory diff / prohibited | `platform-backend` + `platform-agent` | AG-036 SOURCE-MERGED (agent PR #38 `a29eef4` + #40 `e64c131` `UpgradeTruncated` fix; backend PR #336 `7f8c1a90` V20 ingest+query); BE-024 SOURCE-MERGED (PR #334 `d154ac7a` V18 software-inventory state diff/history, atomic ON CONFLICT append); BE-025 SOURCE-MERGED (PR #335 `7bb0340e` V19 prohibited-software denylist + EndpointComplianceService integration); cluster image `fd272365` (#348) ⊃ #336 ⊃ #335 ⊃ #334 → all 3 included end-to-end | SOURCE-MERGED + LIVE acceptance pending (testai cluster image fd272365; V18/V19/V20 migration files included in deployed image, Flyway apply verified 2026-05-30 (V18/V19/V20 `success=true` rows live in `endpoint_admin_service.endpoint_admin_flyway_history`); API service reachability + Spring Security admin auth-gate verified 2026-06-01 (no-JWT cluster-internal GET returned HTTP 401 for 4/4 admin URLs: `/software-inventory/diff` + `/software-inventory/history` + `/outdated-software/latest` + `/prohibited-software`; no 500 / no connection-refused — this is NOT route-level controller-mapping acceptance; SecurityConfig admin chain enforces 401 before handler mapping); authenticated 200 + JSON shape smoke (admin JWT path) + WEB surface verify pending) |
| Posture / health / hotfix / diagnostics / services / exposure | `platform-agent` | AG-030 / AG-031 / AG-032 / AG-033 SOURCE-MERGED (PRs #33/#34/#35/#36, Codex cross-AI AGREE; binary distribution operator-bound); **AG-037 MERGED + LIVE 2026-06-01** (end-to-end chain agent #45 + backend #354/#355 + web #723 + gitops #1167/#1168 + HALILKOOLUB735 86 installed + 1 pending real WUA telemetry + browser smoke); **AG-038 MERGED + LIVE 2026-06-01** end-to-end chain (agent #39 + backend #357/#355 V23 LIVE + web #727 + gitops #1181 digest bump APPLIED + browser-verified Agent Tanılaması tab 404 empty + `includeDiagnostics:true` literal hint); **AG-039 SOURCE-MERGED + backend LIVE 2026-06-01** end-to-end 3-repo chain: agent PR [#47](https://github.com/Halildeu/platform-agent/pull/47) `0d8e7b4` (critical services probe — 6-service canonical allowlist WinDefend/wuauserv/BITS/EventLog/EndpointAgent/MpsSvc; per-service {present, state, startupMode} from SCM + registry) + backend PR [#362](https://github.com/Halildeu/platform-backend/pull/362) `65d9fbd5` (V24 migration + ingest + GET /services/latest query) + web PR [#728](https://github.com/Halildeu/platform-web/pull/728) ServicesView drawer tab (Codex 019e8389 2-iter REVISE→PARTIAL→AGREE absorb 6+1 must_fix incl. IslemlerTab default 8-bit payload + fail-closed container parity + startupMode=DISABLED danger chip + DICT_EN parity + nullable summary/serviceName); browser smoke + testai frontend digest bump pending (gitops PR #1185); **AG-040 SOURCE-MERGED 2026-06-01** end-to-end chain (agent 92320cd + backend b6daaee2 V25 startup-exposure ingest+query + web PR [#729](https://github.com/Halildeu/platform-web/pull/729) StartupExposureView drawer tab; Codex 019e83a6 3-iter REVISE→REVISE→AGREE absorb incl. AG-040/AG-041 numbering disambiguation + fail-closed exposure-scalar evidence helpers + per-scalar polarity split + StartupAppLocation enum source type); AG-041 (Application Control / WDAC / AppLocker) reserved for new zincir | AG-037/AG-038 LIVE; AG-039 SOURCE-MERGED + backend LIVE (digest bump + browser smoke pending); AG-040 SOURCE-MERGED (browser smoke + digest bump pending); AG-030–033 SOURCE-MERGED (live smoke operator-bound); AG-041 TODO |
| Uninstall + signed self-update + rollout controls | `platform-agent` + `platform-backend` | AG-028 / AG-029 / BE-026 / BE-027 / BE-028 / BE-029 NOT YET IMPLEMENTED | TODO |
| GitOps governance | `platform-k8s-gitops` | plan + runbook + ADR mature; current-state delta 2026-05-29 PM | LIVE |

### 0.2 3-AI Mutabakatı

| AI | Verdict | Absorb edilen karar |
|---|---|---|
| Claude Code | REVISE | Agent AG-025/AG-026 temeli doğru; backend catalog ve web yüzeyi install öncesi blokaj |
| Codex | REVISE | Agent probe yükü ayrıştırılmalı; backend/web command-payload drift'i kapanmalı |
| MiniMax/Mavis | REVISE | Backend approved catalog + install command + web software view olmadan install açılmamalı |

Mutabakat sonucu: yön doğru, ama install PR sırası read-only foundation → web
visibility → approved catalog → command contract → adapter → detection/audit
şeklinde yürür. Katalog dışı paket, raw shell ve rastgele URL/EXE yolu yoktur.

### 0.3 Rakip Quick-win Absorb

2026-05-27 ek review sonucu rakiplerdeki free-first endpoint yönetimi
kabiliyetleri fazlara ayrıldı. Eklenenler Intune/PDQ/Action1/ManageEngine
çizgisindeki görünürlük ve kontrollü dağıtım değerini hedefler, fakat RMM
seviyesinde raw execution açmaz:

| Faz | Yeni değer | Scope |
|---|---|---|
| P0 | WinGet source / egress readiness | `AG-026A`; install/upgrade yok |
| P0 | Install dry-run / preflight | `BE-021A`; install başlatmadan PASS/WARN/BLOCK |
| P0 | Catalog compliance | `BE-023`; approved/missing/outdated/unknown/prohibited |
| P0/P1 | Installer exit-code / redacted logs | `AG-027L`; troubleshooting, secret yok |
| P1 | Outdated software visibility | `AG-036`; read-only upgrade availability |
| P1 | Inventory diff/history | `BE-024`; added/removed/version-changed |
| P1 | Prohibited software detection | `BE-025`; alert/compliance, auto-uninstall yok |
| P1 | Agent health / connectivity diagnostics | `AG-038`; backend/DNS/TLS/last error summary |
| P1/P2 | Rollout controls | `BE-026..BE-029`; ring/window/throttle/bundle |

## 1. Ürün Hedefi

Hedef, agent üzerinden Windows cihazlarda kontrollü yazılım yönetimi sağlamaktır:

1. Kurulu program envanteri okunur.
2. Cihazda WinGet hazır mı kontrol edilir.
3. WinGet source / egress readiness doğrulanır: source list, App Installer,
   Store source, proxy/TLS ve paket query erişimi.
4. Cihaz donanım/envanter bilgileri read-only toplanır: CPU, RAM, disk, model,
   BIOS, TPM, ağ ve OS/build.
5. Backend'de onaylı yazılım kataloğu tutulur.
6. Cihaz approved catalog'a göre compliant / missing / outdated / prohibited
   olarak değerlendirilir.
7. Install öncesi dry-run / preflight ile cihaz ve paket şartları doğrulanır.
8. Agent yalnız katalogda onaylı paketleri sessiz kurar.
9. Kurulum sonucu detection + audit + exit-code + redacted log ile kanıtlanır.
10. Pending reboot, Defender/Firewall/BitLocker, local admin ve temel cihaz sağlık
   sinyalleri aynı ekrandan okunur.
11. Kaldırma, rollback, rollout ring/window ve agent self-update daha sonraki
   kapılarda açılır.

## 2. Varsayılan Yaklaşım

| Karar | Değer |
|---|---|
| Varsayılan paket provider | Microsoft WinGet |
| Kontrol düzlemi | Approved Software Catalog |
| İlk pilot paket | 7-Zip |
| Lisans yaklaşımı | Ücretsiz / Windows-native first |
| Katalog dışı kurulum | Yasak |
| Raw shell | Yasak |
| Rastgele URL / EXE install | Yasak |
| Audit | Zorunlu |
| RBAC | Zorunlu |
| Destructive / geniş dağıtım | Dual-control + pilot kanıtı sonrası |

WinGet seçimi ücretsiz ve Windows 10/11 üzerinde Microsoft-native olduğu için
varsayılandır. MSI/EXE internal catalog fallback desteklenebilir; Chocolatey
Community ancak ayrı supply-chain değerlendirmesi sonrası opt-in olur.

## 3. İş Paketi Haritası

| ID | Repo | İş | Status | Kabul kriteri |
|---|---|---|---|---|
| **AG-025** | `platform-agent` | Installed software inventory | **MERGED (PR #20)** | HKLM + HKLM `WOW6432Node` registry sanitized JSON; HKCU default-off; lisans/product key/user path sızmaz |
| **AG-026** | `platform-agent` | WinGet readiness check | **MERGED (PR #20)** | `winget --version` readiness structured; install/search/source/upgrade çalıştırılmaz |
| **AG-026A** | `platform-agent` | WinGet source / egress readiness | **MERGED + LIVE (PR #22, PR #25 wire shape fix)** | `winget source list`, App Installer/Store source state, DNS/TCP/HTTPS egress probes, package query reachability; verified HALILKOOLUB735 2026-05-29 |
| **AG-026B** | `platform-agent` | `--enrollment-token` CLI flag escape hatch | **MERGED + LIVE (PR #28, 2026-05-29 PM)** | CLI flag (trimmed) > env > regkey precedence; HMAC-only enforcement; HALILKOOLUB735 verified |
| **AG-026C** | `platform-agent` | install.ps1 service env regkey + post-install enroll gate | **MERGED + LIVE (PR #27 + PR #29 `-Force` splat fix, 2026-05-29 PM)** | HKLM Services\\<name>\\Environment REG_MULTI_SZ override SCM env cache; sentinel gate; baseline-aware false-positive guard; PR #29 `97edf17` install.ps1 -Force uninstall splat array→hashtable live evidence absorb |
| **AG-026D** | `platform-agent` | HMAC credential DPAPI persistence + typed 401 routing | **MERGED + LIVE (PR #26, 2026-05-29 PM)** | machine-scope DPAPI; atomic temp+fsync+rename; SetHardenedACL; hydrate-on-cold-start; HALILKOOLUB735 hydrate proof |
| **AG-025H** | `platform-agent` | Software probe decoupling / lightweight inventory guard | **MERGED (PR #21)** | Heartbeat/auto-enroll lightweight path; `includeSoftware=true` explicit full-list opt-in; no-shell/no-PowerShell test guard |
| **BE-020** | `platform-backend` | Approved software catalog API | **MERGED + LIVE (PR #306 PR-A + PR #308 PR-B)** | V7 sequence + entity + repo + service + audit + validator + REST + RBAC + MockMvc; testai deployed |
| **BE-020I** | `platform-backend` | Software inventory ingest/query surface | **MERGED + LIVE (PR #310 + #311 shape fix)** | Agent `details.inventory.software` ingest path canonical; query surface live |
| **BE-021A** | `platform-backend` | Install dry-run / preflight result contract | **MERGED + LIVE (PR #312)** | `POST /endpoint-devices/{id}/install-preflight` PASS/WARN/BLOCK contract; recompute-at-create gate enforced |
| **AG-027** | `platform-agent` | Approved software install command | **MERGED + LIVE 2026-05-31 (PR #23 + PR #41 winget-list-Session-0 fix; #1133 GREEN)** | install_winget core pipeline + Windows runner with Job Object + taskkill fallback + non-Windows stub + executor wiring; HARD BOUNDARIES locked; **end-to-end 7-Zip dispatch smoke PROVEN under SYSTEM Session-0 ARM64 Win11** — winget INSTALL exit code authoritative, `winget list` confirm-only (miss → INCONCLUSIVE never denial), `0x8A150061` → SUCCEEDED_NOOP |
| **AG-027L** | `platform-agent` | Installer exit-code / redacted log capture | **SOURCE-MERGED (PR #32 `4f5e152`, 2026-05-29 PM); binary distributed + service health PASS; LIVE smoke proven 2026-05-31** (the #1133 GREEN end-to-end smoke went through the redacted wire path with no observable leak); explicit deep-trace evidence collection pending (separate lower-priority followup) | RedactInstallerString 3 pattern classes (URL userinfo / MSI property assignments / token query params) + sanitizeForWire layered with baseline; ExitCode + DurationMs + FailedReasonCode + StdoutTail/StderrTail wire-safe with 4KB cap already exist in AG-027 InstallResult struct |
| **BE-021** | `platform-backend` | Install result / detection / audit | **MERGED + LIVE (PR #317 + V12 PR #318 + Mockito guard PR #321)** | install_audit table + EndpointInstallAuditService + AdminEndpointInstallController dedicated `POST /endpoint-devices/{id}/installs` + manager RBAC + preflight recompute gate |
| **BE-023** | `platform-backend` | Software compliance evaluator | **MERGED + LIVE (PR #313, #314, #315)** | COMPLIANT/NON_COMPLIANT/UNAUTHORIZED/UNKNOWN evaluator + AFTER_COMMIT listener + V10 migration + DTOs/controllers; JPMS + ObjectProvider permanent fix |
| **AG-036** | `platform-agent` | Outdated software inventory | **SOURCE-MERGED (agent PR #38 `a29eef4` + #40 `e64c131`; backend PR #336 `7f8c1a90` V20)** | WinGet `upgrade --include-returning-apps --source winget` read-only; otomatik upgrade YOK; per-package `{packageId, installedVersion, availableVersion}` (no Name/Source/publisher/install path/stdout/stderr on wire); PR #40 `UpgradeTruncated` semantics for results exceeding cap; opt-in `COLLECT_INVENTORY{includeOutdatedSoftware:true}` flag + `daa072e1` (#339) `collect-now` opt-in; contract: `docs/faz-22-outdated-software-contract-v1.md`; LIVE acceptance pending on testai cluster `fd272365` |
| **BE-024** | `platform-backend` | Software inventory diff/history | **SOURCE-MERGED (PR #334 `d154ac7a` V18)** | Append-only `endpoint_software_inventory_state_history` (full apps[] snapshots; summary-only + egress-only ingests skipped); REST: `GET /software-inventory/diff` (latest-vs-previous) + `GET /software-inventory/history`; synthetic `appKey` (BE-020I installed inventory has no packageId, so packageId reserved for WinGet/outdated/catalog surfaces); atomic ON CONFLICT append; user path/log YOK; LIVE acceptance pending |
| **BE-025** | `platform-backend` | Prohibited software detection | **SOURCE-MERGED (PR #335 `7bb0340e` V19)** | Non-catalog-bound `endpoint_prohibited_software_rules` table + `ProhibitedSoftwareRuleService` + `EndpointComplianceService` integration; `ComplianceState = UNAUTHORIZED` with reason `prohibited_app_installed` (NO new `PROHIBITED` enum — V19 migration comment explicitly says catalog-bound `FORBIDDEN` is contradictory for banned software); otomatik uninstall YOK; LIVE acceptance pending |
| **WEB-011** | `platform-web` | Software inventory view | **MERGED + LIVE (PR #674 `70a038ac`)** | InventoryTab software + WinGet readiness; gateway path; testai deployed |
| **WEB-014A** | `platform-web` | Compliance Tab + GET state + POST evaluate | **MERGED + LIVE (PR #675 `0c4f33a8`)** | Read-only compliance tab + evaluate trigger |
| **WEB-014B** | `platform-web` | Cross-device compliance list + per-device history | **MERGED + LIVE (PR #676 `b6b15983`)** | Org-level compliance list + per-device evaluation history |
| **WEB-014C** | `platform-web` | Policy CRUD UI (REQUIRED/ALLOWED/FORBIDDEN) | **MERGED + LIVE (PR #678 + PR #682)** | Per catalog item policy CRUD; bulk import deferred |
| **WEB-014D / WEB-012** | `platform-web` | Approved install UI surface | **MERGED + LIVE (PR #683 + perf/follow-up PR #693, Codex absorb)** | Full chain LIVE: `SoftwareCatalogTab.tsx` "Kur" button per catalog row → `InstallPreflightModal.tsx` PASS/WARN/BLOCK + `useCreateInstallMutation()` dispatch POST + "Son Kurulumlar" audit panel via `useListInstallAuditsQuery` with auto-refetch on `EndpointInstallAudit:device-{id}` tag invalidation. Codex 019e6ff0 post-impl absorb already applied (in-flight POST race guard) |
| **WEB-015** | `platform-web` | Endpoint report / CSV export | **TODO** | RBAC-controlled export |
| **AG-028** | `platform-agent` | Software uninstall / detection | **TODO** | Catalog-managed package only; detection verified |
| **AG-029** | `platform-agent` | Signed agent self-update | **TODO** | Signed manifest + hash + version policy + rollback guard |
| **AG-030** | `platform-agent` | Pending reboot detection | **SOURCE-MERGED (PR #33)** | CBS/Windows Update/PendingFileRenameOperations sinyalleri; binary distribution + HALILKOOLUB735 lab smoke operator-bound |
| **AG-031** | `platform-agent` | Endpoint security posture inventory | **SOURCE-MERGED (PR #34, Codex 019e74b5 4-iter AGREE)** | Defender/Firewall/BitLocker read-only; recovery key/drive-id/vendor-name sızmaz; tri-state nullable; binary distribution operator-bound |
| **AG-032** | `platform-agent` | Local admin group inventory | **SOURCE-MERGED (PR #35, Codex 019e74d7 5-plan+2-impl AGREE)** | Built-in Administrators (S-1-5-32-544) direct membership; ZERO raw SID/RID/name on wire; NetAPI primary + PowerShell fallback; binary distribution operator-bound |
| **AG-033** | `platform-agent` | Device health snapshot | **SOURCE-MERGED (PR #36, Codex 019e7500 plan+impl AGREE)** | Disk/RAM/uptime/boot time özet; direct Win32 syscall; no performans counter spam; only drive letter on wire; binary distribution operator-bound |
| **AG-035** | `platform-agent` | Hardware / device inventory | **MERGED + LIVE (PR #24, HALILKOOLUB735 verified 2026-05-29)** | CPU/RAM/disk/model/BIOS/TPM/network read-only; SRB-AIDENETIMPC binary distribution operator-bound |
| **AG-037** | `platform-agent` | Windows Update / hotfix posture | ✅ **MERGED + LIVE (2026-06-01)** | Hotfix history + pending update + health summary; patch install/reboot tetiklemez. End-to-end LIVE: agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) `2b0f3b5` (WUA COM + PS fallback + service + registry + agent-health) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) `2ac67f11` (V22 5-table) + PR [#355](https://github.com/Halildeu/platform-backend/pull/355) `fb80db67` (omitempty critical follow-up) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) `577a89f2` (HotfixPostureView tab) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168) (digest pins). HALILKOOLUB735 binary upgrade + manual `COLLECT_INVENTORY{includeHotfixPosture:true}` → backend ingest **86 installed + 1 pending** (KB2267602 DEFINITION UNSPECIFIED) → browser smoke testai.acik.com Hotfix Duruşu tab full panel render (NO errors). Cross-AI Codex threads `019e81fe` + `019e822b` + `019e8245`. |
| **AG-038** | `platform-agent` + `platform-backend` + `platform-web` | Agent self-health / connectivity diagnostics | **SOURCE-MERGED + backend LIVE 2026-06-01** (agent #39 + backend #357/#355 + web #727) | Agent version/config hash + last poll latency + backend DNS/TLS tri-state + flat lastError triad + bounded probeErrors[]; V23 migration applied + GET /diagnostics/latest LIVE; drawer "Agent Tanılaması" tab read-only view (Codex 019e833d 3-iter AGREE); browser smoke + frontend digest bump pending |
| **AG-039** | `platform-agent` | Critical services inventory | **TODO** | WinDefend/wuauserv/BITS/EventLog/endpoint-agent state read-only |
| **AG-040** | `platform-agent` | Startup apps / exposure summary | **TODO** | Startup registry/folder summary + RDP/NLA status + event-log health count |
| **BE-022** | `platform-backend` | Device inventory ingest surface | **MERGED + LIVE (PR #322 V13 + PR #324 V14)** | Hardware payload normalize + sanitizer + EndpointHardwareInventoryService idempotent ingest; ALTER payload_hash_sha256 VARCHAR(64) fix |
| **BE-022Q** | `platform-backend` | Device inventory query surface | **MERGED + LIVE (PR #325 / current sha-e3a0369)** | AdminEndpointHardwareInventoryController GET /latest + /history; module:endpoint-admin can_view RBAC; cluster live 2026-05-29 = `sha256:76bacc004f...` (sha-e3a0369, post backend #326 + gitops #1130); BE-022Q deep payload-hash equality SQL surface partial bug (`lower(bytea)`) tracked separately |
| **WEB-013** | `platform-web` | Hardware / device inventory view | **MERGED + LIVE (PR #700 `26e68658`)** | DeviceDetailDrawer Donanım tab + HardwareInventoryView + history accordion + i18n TR+EN + 8 RTL tests |
| **WEB-017** | `platform-web` | Endpoint Enrollment Management UI | **MERGED + LIVE (PR #701 `c0201c08`)** | Enrollment workflow surface |
| **WEB-018** | `platform-web` | Envanteri Şimdi Topla + Donanım dedicated trigger | **MERGED + LIVE (PR #702 `e096837b`)** | COLLECT_INVENTORY payload UI + Donanım trigger |
| **BE-026** | `platform-backend` | Deployment rings / device tags | **TODO** | Pilot/IT/department/all rollout ring; policy motorundan önce kontrollü yayılım |
| **BE-027** | `platform-backend` | Maintenance window / scheduled command | **TODO** | `notBefore`/`expiresAt`/allowed window/timezone |
| **BE-028** | `platform-backend` | Rollout throttle / max concurrency | **TODO** | Concurrent install limit + retry/backoff |
| **BE-029** | `platform-backend` | Approved package bundles | **TODO** | Standart bundle (office/finance) tanımı; tekil katalog kanıtından sonra |
| **AG-034** | `platform-agent` | SMB/file actions discovery guardrail | **DEFERRED** | Discovery/tehdit modeli; whitelist + RBAC + audit + dual-control olmadan runtime yok |

## 4. Milestone Sırası

### 22.5.0 Tracking Foundation

- Bu doküman ve runbook canonical plan olarak eklenir.
- Board issue'ları gerçek source repolarda açılır.
- Runtime claim yapılmaz.

### 22.5.1 Read-only Device Software View

- `AG-025` ve `AG-026`.
- Sadece okuma yapılır.
- `platform-agent` source-side foundation PR #20 (`0eff2db`) ile başlamıştır;
  field acceptance ve backend/web görünürlük hâlâ ayrı kapıdır.
- `COLLECT_INVENTORY` payload'ına geniş özet eklenebilir:
  - `installedSoftwareCount`
  - `wingetInstalled`
  - `wingetVersion`
  - `wingetSourceAvailable`
- Full app list yalnız `includeSoftware=true` ile döner.
- Default registry scope HKLM + HKLM `WOW6432Node`; HKCU, LocalSystem altında
  gerçek kullanıcıyı temsil etmediği için ilk fazda default dışıdır.

### 22.5.1A Agent Probe Decoupling / Lightweight Guard

- `AG-025H`.
- Heartbeat, auto-enroll ve lightweight inventory yolları full software scan
  veya WinGet probe maliyetine yanlışlıkla girmez.
- Kabul:
  - `includeSoftware=false` veya lightweight mode full `apps[]` listesi üretmez,
  - `includeSoftware=true` full list'i explicit üretir,
  - WinGet readiness timeout/redaction testleri korunur,
  - no shell / no PowerShell / no `winget install` sınırı testle kilitlenir.

### 22.5.1B Web Read-only Visibility

- `WEB-011`.
- Mevcut agent payload'unu görünür yapar:
  - app count,
  - WinGet readiness,
  - WinGet version,
  - full app list varsa filtrelenebilir tablo.
- Backend result shape'i `details.inventory.software` gibi nested olabilir;
  web normalize layer bu şekli açıkça destekler.
- Backend status enum drift'i giderilir: backend `PARTIAL` / `UNSUPPORTED`
  dönerse UI yanlış `TIMEOUT` / `CANCELLED` varsayımı yapmaz.

### 22.5.1C WinGet Source / Egress Readiness

- `AG-026A`.
- `winget --version` tek başına yeterli sayılmaz.
- Read-only preflight şu sinyalleri döner:
  - `winget source list` structured parse,
  - Microsoft Store / App Installer source state,
  - `7zip.7zip` package query reachability,
  - backend/proxy/TLS/DNS egress summary,
  - timeout ve redacted error reason.
- Bu fazda `winget install`, `winget upgrade` veya source mutation yoktur.

### 22.5.2 Device Posture + Hardware Quick Wins

- `AG-030`, `AG-031`, `AG-032`, `AG-033`, `AG-035`, `BE-022` ve `WEB-013`.
- Sadece read-only inventory sinyalleri toplanır.
- Panelde program kurulumu için karar vermeyi kolaylaştırır:
  - restart bekliyor mu,
  - Defender aktif mi,
  - Firewall profilleri açık mı,
  - BitLocker koruması açık mı,
  - local admin grubunda kimler var,
  - disk/RAM/uptime sağlığı nedir,
  - cihaz modeli, CPU/RAM/disk kapasitesi, BIOS/TPM ve ağ özeti nedir.
- BitLocker recovery key, credential, bearer token, password, product key ve
  tam kullanıcı profili path'i toplanmaz.

Hardware/device inventory varsayılan alanları:

| Grup | Alanlar | Privacy / güvenlik sınırı |
|---|---|---|
| OS | edition, version, build, architecture | lisans/product key yok |
| Hardware | manufacturer, model, CPU model, logical core count, RAM total | yüksek kardinaliteli raw sensor/process dump yok |
| Disk | volume count, total/free, drive type, boot volume flag | kullanıcı dosya path'i veya dosya listesi yok |
| BIOS/Firmware | BIOS version/date, serial policy | serial raw gösterimi policy-gated; varsayılan hash veya masked |
| TPM | present, enabled, ready, version | key material veya attestation secret yok |
| Network | adapter count, primary adapter type, IP family, DNS suffix | MAC/IP raw gösterimi policy-gated; default summary/masked |
| Agent | agent version, service status, capabilities | token, HMAC secret veya enrollment secret yok |

Bu bilgiler `software inventory` değildir; genel `device inventory` başlığı
altında ayrı tutulur. Yazılım envanteri kurulu programları; hardware inventory
cihazın donanım ve platform kimliğini ifade eder.

### 22.5.2A Endpoint Diagnostics + Update Visibility

- `AG-037`, `AG-038`, `AG-039` ve `AG-040`.
- Rakiplerdeki RMM/endpoint posture hissini read-only seviyede sağlar:
  - Windows Update / hotfix posture,
  - agent self-health ve backend connectivity,
  - critical Windows service state,
  - startup apps summary,
  - RDP/NLA exposure status,
  - event-log health count.
- Patch install, remote reboot, service restart, process kill veya full event
  log upload yoktur.

### 22.5.3 Approved Catalog Control Plane

- `BE-020`.
- İlk katalog satırı: `7zip.7zip`.
- Katalog alanları:
  - `catalogItemId`
  - `provider` / `sourceType`
  - `sourceName`
  - `sourceTrust`
  - `packageId`
  - `displayName`
  - `publisher`
  - `approvedVersion` veya `approvedVersionRange`
  - `installerType`
  - `silentArgsPolicy`
  - `sha256` / `provenance`
  - `detectionRule`
  - `riskTier`
  - `enabled`
  - `createdBy`
  - `approvedBy`
  - `createdAt`
  - `approvedAt`

Katalog, WinGet Community kaynağı dahil her provider için supply-chain karar
yeridir. Agent hiçbir zaman kullanıcıdan gelen raw package id, raw URL veya raw
installer argument'i execute etmez.

### 22.5.3A Software Inventory Ingest / Query

- `BE-020I`.
- Agent `COLLECT_INVENTORY` software payload'ı backend'de canonical snapshot
  olarak saklanır.
- Web ve compliance evaluator bu shape'i kullanır.

### 22.5.3B Catalog Compliance + Outdated Visibility

- `BE-023`, `AG-036` ve `WEB-014`.
- Amaç kurulum yapmadan önce görünürlük sağlamaktır:
  - approved catalog item cihazda var mı,
  - kurulu sürüm approved policy ile uyumlu mu,
  - WinGet read-only outdated result var mı,
  - cihaz `COMPLIANT`, `MISSING`, `OUTDATED`, `UNKNOWN` veya `PROHIBITED`
    olarak işaretlenir.
- Otomatik upgrade veya uninstall bu fazın parçası değildir.

### 22.5.3C Inventory Diff / Prohibited Software Detection

- `BE-024` ve `BE-025`.
- Son inventory snapshot'ları karşılaştırılır:
  - yeni kurulan uygulama,
  - kaldırılan uygulama,
  - versiyon değişimi,
  - denylist/prohibited software eşleşmesi.
- İlk davranış yalnız alert/compliance state üretmektir; otomatik kaldırma yok.

### 22.5.4 First Install Pilot

- `BE-021A`, `AG-027`, `AG-027L` ve `BE-021`.
- Install adapter şu kapılar olmadan başlamaz:
  - read-only preflight PASS (`AG-025`/`AG-026`),
  - WinGet source / egress readiness PASS (`AG-026A`),
  - backend inventory ingest/query path (`BE-020I`),
  - approved catalog (`BE-020`),
  - install dry-run / preflight `PASS` veya açıkça kabul edilen `WARN`
    (`BE-021A`),
  - command contract ve audit (`BE-021`).
- İlk canlı paket: 7-Zip.
- Kurulum sonucunda provider exit code, duration, sanitized reason ve redacted
  log tail tutulur; secret, token veya kullanıcı path'i tutulmaz.
- Komut shape raw shell içermez:

```json
{
  "type": "INSTALL_APPROVED_SOFTWARE",
  "catalogItemId": "7zip",
  "requestedVersion": "latest"
}
```

Agent backend'den gelen `catalogItemId` ile katalog metadata'sını doğrular,
sonra provider komutunu kendi adapter'ında üretir.

### 22.5.5 Web Surface

- `WEB-011`, `WEB-012`, `WEB-014` ve `WEB-015`.
- Cihaz detayında:
  - kurulu programlar,
  - WinGet readiness,
  - WinGet source / egress readiness,
  - approved catalog compliance,
  - outdated software,
  - pending reboot,
  - Defender/Firewall/BitLocker durumu,
  - local admin grubu,
  - disk/RAM/uptime özeti,
  - hardware/device inventory,
  - son kurulum/kaldırma sonucu,
  - audit event'leri,
  - CSV/report export görünür.

### 22.5.6 Managed Uninstall / Rollback

- `AG-028`.
- Sadece bizim katalog üzerinden kurulan veya katalogda yönetilebilir işaretli
paketler için açılır.

### 22.5.7 Agent Self-update

- `AG-029`.
- Signed update manifest olmadan agent self-update açılmaz.
- Authenticode + manifest signature + SHA256/SHA512 kanıtı gerekir.

### 22.5.8 Controlled Rollout Policies

- `BE-026`, `BE-027`, `BE-028` ve `BE-029`.
- Tek cihaz pilotu kanıtlanmadan geniş deployment açılmaz.
- Kontrollü yayılım modeli:
  - deployment rings / device tags,
  - maintenance window / scheduled command,
  - rollout throttle / max concurrency,
  - retry/backoff/timeout policy,
  - approved package bundles.
- Bu faz policy-based domain-wide deployment yerine geçmez; Faz 22.3 MSI/GPO
  hattını tamamlayıcı agent-side yönetim katmanıdır.

### 22.5.X Deferred / High-Risk File Actions

- `AG-034`.
- SMB/file actions bu quick-win planının runtime hedefi değildir.
- İlk iş yalnız discovery olur:
  - hangi path sınıfları riskli,
  - hangi whitelist modeli gerekir,
  - hangi RBAC scope gerekir,
  - hangi audit ve pre/post snapshot zorunlu,
  - dual-control gerektiren aksiyonlar hangileri.
- Kullanıcı masaüstü/dosya işlemleri whitelist + RBAC + audit + dual-control
  tasarımı olmadan açılmaz.

## 5. Güvenlik Sınırları

| Yasak | Sebep |
|---|---|
| Raw shell command | Remote code execution yüzeyini kontrolsüz büyütür |
| Rastgele URL'den EXE/MSI indirme | Supply-chain ve malware riski |
| Kullanıcı tarafından serbest package id yazma | Katalog kontrolünü bypass eder |
| Publisher/hash/detection olmadan install | Kurulum kanıtı ve rollback zayıflar |
| Audit olmadan install/uninstall | Non-repudiation kaybolur |
| Domain-wide deployment'e doğrudan geçiş | 5→50→800 ramp ve EDR/signing kapıları atlanır |

## 6. D29 Kabul Katmanları

| Katman | Kanıt |
|---|---|
| **Up** | Backend catalog endpoint / agent command adapter / web route ayakta |
| **Functional** | 7-Zip install request → agent execute → detection success → result submit |
| **Secured** | RBAC allow/deny, catalog-only validation, audit row, no-token 401, unauthorized 403 |
| **D30 artifact** | Agent release hash/signature, backend image digest, web digest istenenle canlı eşleşir |

Read-only posture sinyalleri için ek kabul:

| Sinyal | Kanıt |
|---|---|
| Pending reboot | Structured `pendingReboot=true/false` + source list |
| Security posture | Defender/Firewall/BitLocker status; secret/recovery key yok |
| Local admins | Administrators grubu sanitized üyelik listesi |
| Device health | Disk/RAM/uptime özet metrikleri; raw process/user dump yok |
| Hardware/device | CPU/RAM/disk/model/BIOS/TPM/network summary; serial/MAC/IP policy-gated |
| WinGet egress | Source list + package query + proxy/TLS readiness; install/upgrade yok |
| Compliance | Approved/missing/outdated/prohibited status; auto-remediation yok |
| Diagnostics | Agent health, backend connectivity, critical services ve event count summary; full logs yok |
| Rollout controls | Ring/window/throttle policy source-ready; geniş deployment canlı kanıt ayrı |

## 7. İlk Pilot Paketleri

| Paket | Provider | Paket ID | Neden |
|---|---|---|---|
| 7-Zip | WinGet | `7zip.7zip` | Küçük, ücretsiz, yaygın, detection kolay |
| Notepad++ | WinGet | `Notepad++.Notepad++` | Yaygın, düşük risk |
| Google Chrome | WinGet | `Google.Chrome` | Yaygın ama policy/enterprise installer kontrolü ayrıca değerlendirilmeli |

İlk PR yalnız 7-Zip ile ilerler; ikinci/üçüncü paketler capability kanıtından
sonra açılır.

## 8. Repo Sınırı

| Repo | Sahip olduğu iş |
|---|---|
| `platform-agent` | Registry inventory, WinGet adapter, install/uninstall executor, posture/health/hardware inventory, self-update |
| `platform-backend` | Catalog API, command validation, software/hardware inventory ingest/query, result/detection/audit |
| `platform-web` | Software inventory view, hardware/device inventory view, approved install UI, command status |
| `platform-k8s-gitops` | Plan, runbook, runtime governance, test/prod digest movement |

## 9. Source PR Sırası

> **SUPERSEDED 2026-05-29** — orijinal §9 (1-13) sıralaması source-side
> tamamlandı (BE-020/BE-020I/BE-021A/BE-021/BE-022/BE-022Q/BE-023 + AG-025/
> AG-025H/AG-026/AG-026A/AG-026B/AG-026C/AG-026D/AG-027/AG-035 + WEB-011/
> WEB-013/WEB-014A-D/WEB-017/WEB-018 hepsi MERGED). Aşağıdaki tablo
> 2026-05-27 mutabakat-zamanı sırası olarak kalır; **aktif sıralama
> §9.bis** altındadır.

### 9.a Original 2026-05-27 sırası (historical)

1. `platform-k8s-gitops`: üç-AI mutabakat patch'i bu plan/runbook/ADR/current-state yüzeylerine işlenir.
2. `platform-agent`: `AG-025H` probe decoupling + explicit lightweight/full inventory tests. **DONE**
3. `platform-agent`: `AG-026A` WinGet source / egress readiness. **DONE + LIVE**
4. `platform-web`: `WEB-011` read-only software + WinGet readiness görünümü. **DONE + LIVE**
5. `platform-backend`: `BE-020` approved catalog skeleton. **DONE + LIVE**
6. `platform-backend`: `BE-020I` software inventory ingest/query surface. **DONE + LIVE**
7. `platform-backend`: `BE-023` software compliance evaluator. **DONE + LIVE**
8. `platform-agent`: `AG-036` outdated software inventory. **DONE (SOURCE-MERGED — agent PR #38 `a29eef4` + #40 `e64c131` `UpgradeTruncated` fix; backend PR #336 `7f8c1a90` V20 ingest+query); LIVE acceptance pending on testai cluster `fd272365`**
9. `platform-web`: `WEB-014` compliance / outdated view. **DONE + LIVE (WEB-014A/B/C/D)** — Note: outdated/diff/prohibited surfaces in WEB are a separate WEB-014E gap (compliance/policy/install covered; outdated/diff list view + prohibited alert view pending)
10. `platform-backend`: `BE-024` inventory diff/history + `BE-025` prohibited software detection. **DONE (SOURCE-MERGED — BE-024 PR #334 `d154ac7a` V18 `endpoint_software_inventory_state_history`; BE-025 PR #335 `7bb0340e` V19 `endpoint_prohibited_software_rules`); LIVE acceptance pending on testai cluster `fd272365` (V18/V19 migration files included in deployed image, Flyway apply verified 2026-05-30 (V18/V19/V20 `success=true` rows live in `endpoint_admin_service.endpoint_admin_flyway_history`))**
11. `platform-backend`: `BE-021A` install dry-run / preflight contract. **DONE + LIVE**
12. `platform-backend`: `INSTALL_APPROVED_SOFTWARE` command contract + `BE-021` audit/detection state. **DONE + LIVE**
13. `platform-agent`: `AG-027` 7-Zip install adapter + `AG-027L` exit-code/redacted log capture. **AG-027 DONE (MERGED + LIVE 2026-05-31 #1133 GREEN — winget-list-Session-0 fix landed in PR #41); AG-027L DONE (SOURCE-MERGED 2026-05-29 PM PR #32, binary distributed + service health PASS; LIVE smoke proven 2026-05-31 through the redacted wire path; explicit deep-trace evidence followup pending)**
14. `platform-web`: `WEB-012` approved install UI + `WEB-015` report/export. **WEB-012 ≡ WEB-014D DONE foundation; WEB-015 TODO**
15. `platform-agent`: `AG-030` + `AG-031` + `AG-032` + `AG-033` + `AG-035` posture/health/hardware quick wins. **AG-035 DONE + LIVE; AG-030/031/032/033 SOURCE-MERGED 2026-05-29 (PR #33/#34/#35/#36, all Codex cross-AI AGREE; binary distribution + HALILKOOLUB735 lab smoke operator-bound)**
16. `platform-agent`: `AG-037` + `AG-038` + `AG-039` + `AG-040` update/diagnostic/service/exposure quick wins. **AG-037 MERGED + LIVE 2026-06-01** (agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) + [#355](https://github.com/Halildeu/platform-backend/pull/355) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168); HALILKOOLUB735 86 installed + 1 pending real WUA telemetry browser-smoked); **AG-038 SOURCE-MERGED + backend LIVE 2026-06-01** (agent PR [#39](https://github.com/Halildeu/platform-agent/pull/39) + backend PR [#357](https://github.com/Halildeu/platform-backend/pull/357)/[#355](https://github.com/Halildeu/platform-backend/pull/355) V23 migration LIVE + web PR [#727](https://github.com/Halildeu/platform-web/pull/727) DiagnosticsView tab; Codex thread `019e833d` 3-iter REVISE→REVISE→AGREE; browser smoke + frontend digest bump pending); **AG-039 / AG-040 TODO**
17. `platform-backend`: `BE-022` device inventory ingest/query. **DONE + LIVE (BE-022 + BE-022Q)**
18. `platform-web`: `WEB-013` hardware/device inventory view. **DONE + LIVE**
19. `platform-agent`: `AG-028` uninstall. **TODO**
20. `platform-agent`: `AG-029` signed update. **TODO**
21. `platform-backend`: `BE-026` + `BE-027` + `BE-028` + `BE-029` rollout ring/window/throttle/bundle controls. **TODO**
22. `platform-agent`: `AG-034` SMB/file action discovery, runtime yok. **DEFERRED**

### 9.bis Active 2026-05-29 sıralaması — sıradaki iş paketleri

P0 (kritik path, acceptance):
1. ~~**7-Zip lifecycle live smoke chain**~~ — **✅ LIVE 2026-05-31** ([#1133 GREEN](https://github.com/Halildeu/platform-k8s-gitops/issues/1133)): catalog seed → preflight PASS → dispatch → agent INSTALL_SOFTWARE under SYSTEM Session-0 → winget exec → `be021-smoke-7zip` SUCCEEDED → UI "Başarılı" (HALILKOOLUB735, command `70a852b4-e87b-4060-8ac9-bb1dd97c1245`, 12:37:27 Türkiye). True root cause 3-layer fix uncovered + sealed: (a) backend `buildInstallPayload` missing agent-contract fields — fixed in platform-backend PR #338; (b) `winget list` unreliable under SYSTEM Session-0 — fixed in platform-agent PR #41 (Codex `019e7d3d` AGREE): INSTALL exit code is install-state authority, `winget list` confirm-only (miss → INCONCLUSIVE, never denial), `0x8A150061` already-installed → SUCCEEDED_NOOP; (c) winget actually downloaded `7z2601-x64.msi` and installed 7-Zip 26.01 in earlier run, subsequent dispatches SUCCEEDED_NOOP.
   - **2026-06-01 follow-up smoke (independent verification)**: REST workaround POST `/installs` 201 CREATED (commandId `4d3c097f-7842-4ec2-8c7f-a60465a1b01c`) on HALILKOOLUB735 / `be026-smoke-7zip-registry` (different catalog row from the GREEN smoke); preflightDecision PASS + approvalStatus NOT_REQUIRED. Agent last heartbeat 2026-06-01 UTC 09:45:57 — backend command queue holds `4d3c097f-...` pending agent restart (operator-bound; not a 22.5.4 regression — already GREEN from 2026-05-31). Backend log window UTC 09:46–11:18 shows no INSTALL_SOFTWARE poll/deliver from `d0efb00a-...`, consistent with agent service idle.
2. **AG-027L INSTALL_SOFTWARE command-path live verification on HALILKOOLUB735** — PR #32 (2026-05-29 PM) SOURCE-MERGED; **binary distributed to HALILKOOLUB735 + service health PASS 2026-05-29 PM** (post-merge build `4f5e152` swap; logger init + DPAPI hydrate + heartbeat accept sentinel verified). **2026-05-31 GREEN smoke** showed end-to-end command-path execution succeeded under the AG-027L-redacted wire path (UI rendered audit row from agent-reported result, no PII leak observed). Remaining: explicit deep-trace AG-027L redaction live-evidence collection (record StdoutTail/StderrTail bytes from an installer with intentional sensitive payload — e.g. dummy URL userinfo / MSI property assignment — and verify backend receives properly-scrubbed values) — **lower priority follow-up** (separate from 22.5.4 acceptance).
3. **WEB-014D-followup (NEW 2026-06-01 — fix landed)** — `InstallPreflightModal.tsx` "Kurulumu Onayla" footer confirm button observed disabled even on a catalog row where preflight decision is PASS (operator: "diğer kurulu olmadığı halde silik"). **Regression vs 2026-05-31 GREEN** (smoke went through UI dispatch successfully then; button now disabled). **Confirmed root cause + fix**: platform-web PR #726 (Codex 019e830b REVISE → AGREE):
   - **Layer 1** — `idempotencyKey` `useState('')` + post-paint `useEffect` left the first paint with `!idempotencyKey === true`, firing the disabled gate before the effect ran. **Fix**: per-intent reset moved to `useLayoutEffect` so the key is set after commit but before paint; empty initial state preserved so per-intent counter semantics stay intact.
   - **Layer 2** — `preflightFetching` was a `confirmDisabled` gate AND collapsed `renderPreflightBody` to a loading placeholder. Any RTK Query refetch frame locked the UI even though the last-known PASS was perfectly safe. **Fix**: `preflightFetching` removed from both render and gate; body keeps showing the last-known PASS during refetches. Anti-stale-PASS safety now relies on `currentData`-anchored `effectivePreflight` (a leftover `data` from a prior catalog row can no longer authorise the active intent's submit) + the existing backend POST 409 BLOCK recompute path that flips the modal to local BLOCK if the decision changes server-side.
   - **Layer 3** — No DOM-inspectable disabled-reason. **Fix**: `confirmDisabledReason` single source-of-truth string (`ok|loading|no-data|block|in-flight|no-key`) drives both `disabled` and a production-visible `data-confirm-disabled-reason` attribute. Orthogonal `data-preflight-fetching` exposes the background-refetch state honestly.
   - 333/333 vitest pass, eslint clean, Codex AGREE `ready_to_merge: true`.
   - Originally enumerated hypotheses (a)/(b)/(c)/(d) below are kept verbatim for audit reconstructibility — Codex iter-1 confirmed Layer 1 + Layer 2 as the actual root; (b) `installedState=INSTALLED → BLOCK` and (d) `i18n decision label drift` were ruled out (no hidden gate; PASS i18n maps correctly to "GEÇTİ" and BLOCK to "ENGELLENDİ").
   - (a) preflight endpoint returning 400 VALIDATION_ERROR / 404 → `effectivePreflight` stays null → `confirmDisabled=true` (this case has no PASS badge visible — eliminates if operator sees "GEÇTİ" badge)
   - (b) `installedState=INSTALLED` even on the BE-026 smoke catalog item because packageId `7zip.7zip` registry-match shared with the real 7-Zip catalog row, and policy returns `decision=BLOCK` (then badge should be "BLOCK" not "GEÇTİ" — verify i18n decision label / badge race)
   - (c) `idempotencyKey` state-reset effect race against confirm gate during initial mount tick (resolves after re-render; but if `preflightFetching` stays true on RTK refetch the gate stays disabled). Codex 019e6fe4 must-fix #2 path.
   - **Superseded audit note** (kept for reconstructibility): backend log scan ruled out (a) for the observed window. Original "Most-likely (b)" guess was wrong; platform-web PR #726 / Codex 019e830b later ruled out (b) and (d) and confirmed the Layer 1 + Layer 2 path above (`idempotencyKey` first-paint race via post-paint `useEffect` + over-tight `preflightFetching` gate that locked both render and submit). No separate diagnostic PR remains required for this item — the fix PR is canonical.
4. ~~AG-029 Signed agent self-update~~ — **moved from P0 to P2 managed lifecycle item #12 (2026-05-29 PM)** per adversarial review (not blocker for 22.5.4 First Install Pilot; lives in §22.5.7 managed lifecycle scope)
5. ~~**WEB pilot dispatch button + audit/result render** on per-device drawer (platform-web)~~ — **2026-05-29 truth correction**: this item was already LIVE in WEB-014D (PR #683 + perf follow-up #693). `SoftwareCatalogTab.tsx` ships per-row "Kur" button; `InstallPreflightModal.tsx` handles PASS/WARN/BLOCK + dispatch via `useCreateInstallMutation()`; "Son Kurulumlar" panel renders audit via `useListInstallAuditsQuery` with auto-refetch tag. Original truth-refresh PR (2026-05-29 AM) mis-flagged this as pending; board issue platform-web#703 closed as already-shipped. **2026-06-01 followup** spawned as item #3 above (modal confirm-disabled regression).

P1 (görünürlük genişletme):
5. **AG-036** Outdated software inventory (read-only winget upgrade compare)
6. ~~**AG-030 / AG-031 / AG-032 / AG-033** posture/health quick wins (4 PR)~~ — **DONE (SOURCE-MERGED 2026-05-29)**: AG-030 PR #33, AG-031 PR #34 (Codex 019e74b5 4-iter), AG-032 PR #35 (Codex 019e74d7 5-plan+2-impl), AG-033 PR #36 (Codex 019e7500 plan+impl). All opt-in, identifier-leak-free, AG-025H lightweight contract intact. Remaining: binary distribution + HALILKOOLUB735 lab smoke (operator-bound) + backend ingest (BE) + WEB visualization
7. ~~**AG-037**~~ **MERGED + LIVE 2026-06-01** (agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) + [#355](https://github.com/Halildeu/platform-backend/pull/355) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168); HALILKOOLUB735 86 installed + 1 pending real WUA telemetry browser-smoked; Codex threads `019e81fe` + `019e822b` + `019e8245`); ~~**AG-038**~~ **SOURCE-MERGED + backend LIVE 2026-06-01** (agent PR [#39](https://github.com/Halildeu/platform-agent/pull/39) + backend PR [#357](https://github.com/Halildeu/platform-backend/pull/357)/[#355](https://github.com/Halildeu/platform-backend/pull/355) — V23 migration applied 12:42 UTC, GET /diagnostics/latest LIVE + 404 "no snapshot" until first ingest + web PR [#727](https://github.com/Halildeu/platform-web/pull/727) DiagnosticsView drawer tab with currentData-anchored fail-closed render; Codex thread `019e833d` 3-iter REVISE→REVISE→AGREE absorbing 8 + 4 + 2 must_fix). **AG-039 / AG-040** EDR posture + WDAC/AppLocker remain P1 (2 PR pending; AG-041 Credential Guard Sprint D)
8. **BE-024** Software inventory diff/history
9. **BE-025** Prohibited software detection
10. **WEB-015** CSV/report export

P2 (rollout controls + uninstall + signed self-update — managed lifecycle):
11. **AG-028** Software uninstall (catalog-managed only)
12. **AG-029** Signed agent self-update (Authenticode + manifest + SHA256/SHA512 + rollback guard; moved from P0 2026-05-29 PM per adversarial review — not 22.5.4 First Install Pilot blocker; lives in §22.5.7 managed lifecycle scope)
13. **BE-026 / BE-027 / BE-028 / BE-029** rollout ring/window/throttle/bundle (4 PR)

Deferred:
14. **AG-034** SMB/file action discovery (runtime yok)

Bu sıra 2026-05-29 truth refresh sonrası geçerlidir.

## 10. Açık Notlar

- Bu plan Intune/SCCM/PDQ alternatifi olarak başlamaz; ücretsiz WinGet +
  controlled catalog çizgisiyle başlar.
- Intune varsa ileride provider olarak eklenebilir, ama bu planın ana yolu
  değildir.
- 22.3 domain-wide mass deployment bu planı tamamlayıcıdır: agent'ın dağıtım
  kanalıdır. 22.5 ise agent yüklendikten sonra yazılım yönetimi kabiliyetidir.
- Domain pilot flow, Faz 22.2.B / 22.3 altında ilerler; 22.5 yalnız agent
  kurulu cihazda software/posture/hardware yönetimi sağlar.
- Dual-control destructive command, BE-017 / D35-EA hattıdır; 22.5 install
  pilotu katalog + RBAC + audit ile başlar.
- Policy-based deployment, 22.3 MSI/GPO mass deployment hattıdır; 22.5 ilk
  aşamada tek cihaz / tek katalog item pilotudur.
- EDR allowlist + code signing, 22.2/22.3/22.4 güvenlik kapılarıdır; 22.5
  agent self-update ve install adapter'ları bu kapılara bağlı kalır.
- Windows Update install/reboot trigger, arbitrary PowerShell/script execution,
  process kill, registry edit, browser history, Wi-Fi password ve saved
  credential collection 22.5 quick-win kapsamına alınmaz.
