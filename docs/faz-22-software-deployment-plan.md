# Faz 22.5 — Software Deployment Quick Wins

> **2026-06-18 #1601 bounded acceptance truth refresh**:
> `platform-k8s-gitops#1601` is closed and Project #2 Status is `Done` for the
> bounded operatorless/product-channel acceptance scope. Denetim PC product
> session artifact `rb-denetim-20260617T191335Z-product` remains available;
> `summary.json` SHA256 is
> `433e1273e13b1dafb24160948447abb490c87fd1db1c29ef642df0f7f52320f0`, and the
> product path returned open/approve/challenge/verify/operation `200`,
> non-pilot `400`, `PERMIT`, and `transportPushed=true`. AgentPC2 third-device
> product-channel evidence is accepted under `#1643`: tokenless mTLS
> auto-enroll, persisted DPAPI state, authenticated command polling, restart
> continuity, and `v0.2.9` artifact promotion. `audit-archive-exporter`
> Degraded was fixed by `#1677/#1678/#1679` with ExternalSecret
> `True/SecretSynced`, successful rollout, `pg_up 1`, and
> `pg_exporter_last_scrape_error 0`. Broader signed MSI/GPO rollout is split to
> `#1680`, and broader attended remote-access remains `platform-backend#510`;
> this does not claim 5-PC/50-PC/800-PC rollout readiness.

> **2026-06-15 M2 durable AD DNS + service-mode truth refresh**:
> backend + agent cert-auth command lifecycle source slice remains as previously
> recorded: `platform-backend` #665 (`47d29d5f`) added cert-auth command poll
> and result endpoints, and `platform-agent` #157 (`83cd30d0`) connected
> tokenless AutoEnroll heartbeat -> command poll -> execute -> result submit.
> The subsequent durable service-mode blocker is now addressed for the bounded
> ERP-MOBIL subgate: `platform-agent` #171 (`5319454f`) fixed AD CS CNG machine
> certs with noncanonical KeySpec/AT_NONE by accepting them only after a positive
> NCrypt Algorithm Name probe; release `v0.2.4` was published and GitOps #1575
> (`c25dd56e`) pinned artifact-host to
> `ghcr.io/halildeu/platform-agent-artifacts:v0.2.4@sha256:f52480d300852cd0c2c398482e25f188eb8b3eda75d93aa495fa90e32a4b9592`.
> On `ERP-MOBIL.acik.local`, no-hosts AD DNS now resolves `testai.acik.com` and
> `mtls.testai.acik.com` through `10.9.10.10` to `10.9.10.53`; both TCP/443
> checks pass. Current artifact path
> `https://testai.acik.com/artifacts/endpoint-agent/current/` serves
> `release_tag=v0.2.4`, `EndpointAgent.zip` SHA256
> `9caea9fb851513717cc1e3d54c5378dd850731de8e73e21df9351cf7077ec8a8`, and agent
> binary SHA256 `067e42eab24ee1f73dc28903774c6f5db6c6dcb2bf1163271efa3803587e06a3`.
> `EndpointAgent` was restored as a `LocalSystem` auto-start service and,
> after restart, logs show `auto-enroll cert loaded` followed by repeated
> `no command available`, proving tokenless mTLS command-poll continuity over
> `https://mtls.testai.acik.com/api/v1/endpoint-agent`. Project #2 bounded
> gate #1569 is now `Done` / closed after Codex re-verified AD DNS from this
> host (`mtls.testai.acik.com` and `testai.acik.com` both resolve through
> `10.9.10.10` to `10.9.10.53`). Broader #1359/#1376 remain `Blocked` for
> the board-authoritative M5 same-day selected-device GPO pilot and later
> wave/prod gates (`mtls.ai.acik.com`, 50/800 staged rollout, and any negative
> matrix kept in M2 scope). ArgoCD
> `platform-test` still lacks registered
> `test-cluster`; follow-up #1577 tracks that GitOps automation debt.
> Canonical ayrıntı: `docs/state/current-state.md` 2026-06-15 M2 live delta.

> **2026-06-07 endpoint-admin OpenFGA selector truth refresh**:
> platform-k8s-gitops #1267 and #1331 are CLOSED + Project Done after workflow
> run `27096356021` passed on `main@513e238b`. Runtime report verdict `PASS`:
> endpoint-admin expected/observed/pod OpenFGA model
> `01KS8QE8T1EJ2DF5CRS4VV9YX1` and store
> `01KPP0CFP4G82K42Y6NYSPT4JF` resolve through the ESO-managed shared
> `kv/platform/openfga` Secret rather than stale ConfigMap pins. The workflow
> used selected GitOps-rendered resources because ArgoCD core was unavailable
> on the self-hosted runner; this is runtime selector proof, not a new
> persona allow/deny or multi-device soak claim.

> **2026-06-07 prod truth refresh**: #1241 prod ESO and #1242 prod workload/config are MERGED and live-verified; release-candidate ledger PR #1315 recorded the prod promotion evidence. `endpoint-admin-service` is present in prod with immutable imageID `sha256:7fa5975c1d0c54e3611db5d89d7b8f8919c1952f6b74f94e562ffd1d90a0f9d2`; ESO `Ready=True:SecretSynced`; prod D29 runner `/tmp/smoke-report-prod-20260606T020443Z.json` returned Up/Functional/Secured/Zanzibar GREEN. This does **not** claim D30 atomic cutover, domain-wide rollout, signed self-update production rollout, or sensitive/file actions.

> **2026-06-07 AG-029 truth refresh**: `platform-agent` #74 and #75 are
> MERGED and local Parallels Windows 11 post-merge self-update smoke is
> proven on `HALILKOOLUB735`. Latest accepted #55 evidence is
> `0.1.0-dev` -> `0.1.4-lab.1`, command
> `0640e361-ccb7-4a7b-8967-27ea992ba7ad` `SUCCEEDED`, stageStatus
> `STAGED_ACTIVATION_READY`, activation outcome `ACTIVATED`, service
> `Running`, backend heartbeat `0.1.4-lab.1`, and audit row
> `ENDPOINT_AGENT_UPDATE_COMMAND_CREATED`. Earlier `0.1.2-lab.2` ->
> `0.1.3-lab.1` smoke remains superseded evidence. This is **local lab baseline
> evidence only**; multi-device acceptance, trusted production signing and
> domain-wide rollout remain separate gates.

> **2026-06-07 BE-026..BE-029 rollout truth refresh**: the controlled rollout
> policy source sprint is no longer draft-only. `platform-backend` PR #478
> (BE-026 rings/device tags, `665ac312`), PR #490 (BE-027 install schedule
> `notBefore`/`expiresAt`, `b23d1e0`), PR #491 (BE-028 install throttle,
> `c1cd9e5`) and PR #492 (BE-029 approved bundles, `3614837`) are MERGED with
> checks passing, and platform-backend #477/#479/#481/#483 are reconciled.
> This is **backend source-side rollout control** evidence; image/digest
> rollout, live testai policy acceptance, AG-029 multi-device acceptance,
> trusted signing and domain-wide rollout remain separate gates.

> **Status**: SOURCE-MERGED + testai LIVE for catalog/inventory/compliance/preflight/audit; AG-027L installer log redaction SOURCE-MERGED 2026-05-29 PM (platform-agent PR #32 `4f5e152`); **First Install Pilot LIVE 2026-05-31** ([#1133 GREEN](https://github.com/Halildeu/platform-k8s-gitops/issues/1133) — `be021-smoke-7zip` SUCCEEDED end-to-end on HALILKOOLUB735 SYSTEM Session-0 ARM64 Win11; UI "Başarılı" 12:37:27; true root cause 3-layer fix: backend PR #338 contract gap + agent PR #41 `winget list` Session-0 unreliable → INSTALL exit code authoritative + `0x8A150061` → SUCCEEDED_NOOP); **WEB-014D-followup fixed in source** — platform-web PR #726 removed the disabled-confirm first-paint/refetch regression and current web main also carries AG-029 self-update dispatch UI PR #755. Runtime/browser acceptance remains evidence-gated by the active overlay digest, but no stale draft PR remains for this UI fix.
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
> diagnostics were later superseded by AG-037/038/039/040 evidence below. See `docs/state/current-state.md`
> "2026-05-29 PM" delta for honest acceptance gate map and live evidence.
>
> **2026-06-01 supersession**: AG-030/031/032/033 SOURCE-MERGED (PRs #33/#34/
> #35/#36, Codex cross-AI AGREE; binary distribution operator-bound); AG-036
> SOURCE-MERGED + Flyway V20 applied on testai; **AG-037 MERGED + LIVE
> end-to-end** (agent #45 + backend #354/#355 + web #723 + gitops #1167/
> #1168 + HALILKOOLUB735 86 installed + 1 pending WUA telemetry browser-
> smoked). The 2026-05-29 PM "TODO" assertions above are STALE for
> AG-030/031/032/033/036/037; AG-038 is SOURCE-MERGED + backend LIVE, while
> AG-039 and AG-040 are SOURCE-MERGED across agent/backend/web with
> digest/browser acceptance still pending. See
> `docs/state/current-state.md` "AG-037 Hotfix Posture LIVE END-TO-END
> VERIFIED (2026-06-01)" delta for canonical truth.
>
> **2026-06-07 supersession**: AG-029 is no longer "TODO / draft PR only".
> The source fix (#74) and checklist (#75) are merged, BE-031/BE-032-backed
> release/dispatch path was used in local Parallels live smokes, and #55 now
> carries accepted one-device evidence through target `0.1.4-lab.1`. The
> acceptance level is **local-lab baseline**, not multi-device/domain/prod
> readiness.
>
> **2026-06-07 AG-030P addendum**: `platform-agent` PR #77 is MERGED
> (`1ec4a5a9`) after local Parallels Windows 11 no-crash proof. The
> auto-enroll startup/dry-run path now fails closed unless a disambiguating
> cert filter is configured (`ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX`
> or `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX`); the local
> `HALILKOOLUB735` temp-binary smoke replaced the native certstore access
> violation with actionable `EXIT=1` diagnostics. This is 22.3/mTLS preflight
> hardening only; AD CS cert provisioning, domain enrollment, trusted signing,
> installed-service distribution and multi-device acceptance remain separate
> gates.

> **2026-06-07 P1 visibility local probe addendum**: a temporary Windows ARM64
> probe built from `platform-agent origin/main@eebd198` executed on local
> Parallels Windows 11 `HALILKOOLUB735` as `nt authority\system` and exercised
> explicit opt-in collectors for `AG-030/031/032/033/036/037/038/039/040`.
> `AG-030`, `AG-031`, `AG-032`, `AG-033` and `AG-039` produced local read-only
> probe evidence. `AG-038` and `AG-040` are recorded as fail-closed/incomplete
> in this temp-binary context (`BACKEND_HOST_UNRESOLVED` without service env;
> task-scheduler redaction guard), so backend/browser acceptance remains a
> separate evidence class. Evidence:
> `docs/faz-22-evidence/2026-06-07-p1-visibility-parallels-probe-smoke.md`.

> **2026-06-07 AG-042 local account truth refresh**: local Parallels Windows
> 11 (`HALILKOOLUB735`) now has both local adapter proof and backend-to-agent
> dual-control dispatch proof for local Windows SAM operations. Agent-side
> proof: `TestMutateLocalWindowsIntegration` exercised `LOCK_USER_LOGIN`,
> `UNLOCK_USER_LOGIN`, and `CHANGE_LOCAL_PASSWORD` on a disposable `ea-*`
> local account, then removed it with `secretEchoed=false`. Backend/JWT
> dispatch proof: AG-092 command `2825b275-4f31-4324-9ad6-a96e08d8b27e`
> reached the agent and failed safely on the reserved built-in `Administrator`
> guard with VM state unchanged; AG-042 command
> `c06cd030-c62e-40da-814d-90956e960eaa` changed disposable local user
> `ea-recovery-smoke`, then cleanup verified the user was `ABSENT`. Follow-up
> #1343 then proved the success path for disposable local lock/unlock:
> `LOCK_USER_LOGIN` command `a8dfaac1-1c3b-4f4f-84cd-77b62c2bd553`
> `SUCCEEDED` and changed `Enabled=true -> false`; `UNLOCK_USER_LOGIN`
> command `fd62b31e-c84a-4ee7-b1d0-e433c35768e1` `SUCCEEDED` and changed
> `Enabled=false -> true`; cleanup removed `ea-lockunlock-smoke`. Evidence:
> `docs/faz-22-evidence/2026-06-07-ag92-ag42-backend-dispatch-smoke.md` and
> `docs/faz-22-evidence/2026-06-07-ag92-disposable-lockunlock-dispatch-smoke.md`.
> This proves local SAM only; domain/M365 password reset, cached-domain
> credential update, pre-logon VPN, #1044 multi-device batch and `acik.local`
> IT pilot remain separate gates.

> **2026-06-08 standard PC install productization addendum**:
> PR #1354 added the Standard PC Install Productization lane below. The first
> source/desired-state slices are now landed: `platform-agent` #102/#103
> provide the PS5.1-safe package, canonical ZIP bootstrap and `-AutoEnroll`
> installer/bootstrap path; #105/#106/#107 align the agent client, packaged
> bootstrap and direct `install.ps1` AutoEnroll defaults to the deployed
> `/api/v1/endpoint-agent` route; `platform-backend` #511 provides result-submit
> failure visibility; GitOps #1355 pinned the endpoint-admin digest; GitOps
> #1358 added the exact auto-enroll gateway route and live no-cert POST now
> fails closed with `MTLS_CERT_MISSING`. Later M2 evidence supersedes the
> initial blocker wording: `mtls.testai.acik.com` test/pilot DNS, edge/backend
> mTLS activation, AD CS machine cert positive path, artifact-host current
> package, and ERP-MOBIL service restart continuity are now proven for bounded
> gate #1569. The HMAC bootstrap is still usable for short pilot reruns, but it
> prompts for a hidden enrollment token and is not the final 800-PC rollout
> channel. Remaining broader gates: M5 same-day selected-device GPO pilot,
> OS reboot continuity, explicit no-24h risk acceptance or later stabilization
> evidence before M6 expansion, 50/800 staged waves, and prod
> `mtls.ai.acik.com`.

> **2026-06-16 operatorless access / artifact-host pin addendum**:
> `platform-agent` #193/#194 moved the operatorless access lane forward without
> making it the default install path. #193 added disabled-by-default remote
> bridge installer/bootstrap/MSI wiring; #194 made the trusted EXE release
> manifest D30-pinnable by carrying `artifact_host_image_ref`. Trusted release
> `v0.2.7` is published with artifact-host image
> `ghcr.io/halildeu/platform-agent-artifacts:v0.2.7@sha256:c1266c66fd1f53fdbcec23f815ee181bb3f574624aa6267df9fb63c4b99b00d8`,
> `EndpointAgent.zip` SHA256
> `598add6fa01cf8fd5adc3acd8c68ef2a251452831bfbc3246c7ea26c590b9f97`,
> and agent binary SHA256
> `80df31855c92a37a4592f30d58ae3352e5ff9bb93ed23eae69aa1137a9fbdfed`.
> GitOps PR #1602 merged that test artifact-host digest pin to origin/main;
> live artifact-host `/current/` now serves `release_tag=v0.2.7` and
> `EndpointAgent.zip` SHA256
> `598add6fa01cf8fd5adc3acd8c68ef2a251452831bfbc3246c7ea26c590b9f97`.
> Staging `k3d-test` now verifies `platform-test/artifact-host` Deployment `2/2`
> ready on the same digest; both pods report imageID
> `ghcr.io/halildeu/platform-agent-artifacts@sha256:c1266c66fd1f53fdbcec23f815ee181bb3f574624aa6267df9fb63c4b99b00d8`,
> `ready=true`, `restartCount=0`, rollout succeeded, and ArgoCD `platform-test`
> is `Synced / Healthy`.
> The signed MSI release-lane hygiene bug was fixed by `platform-agent` #195
> (`5a48900177ece937a9c17a8ed2117a672b186149`): fresh trusted MSI run
> `27619652974` succeeded for `0.2.8`, produced
> `EndpointAgent-0.2.8-signed.msi` SHA256
> `8af982357e32c9553f22ef1761fd808513b9945df67b3e280e2ba971626067e7`, and
> emitted a trusted production manifest with `signing_tier=trusted-internal-ca`,
> `timestamped=true`, and signature status `Valid`. This proves MSI release
> artifact generation; endpoint-side MSI install and GPO rollout readiness still
> require live pilot smoke evidence.

> **2026-06-17 artifact-host v0.2.8 truth refresh**:
> `platform-agent` #203 (`78f2ee35dcd64e7fc70d6d63e4e8f8ce016b85c1`) moved
> the canonical bootstrap to host-aware URL derivation: `PackageUrl` host
> derives default API base `https://<host>/api/v1/endpoint-agent`, and
> `-AutoEnroll` derives `https://mtls.<host>/api/v1/endpoint-agent` unless the
> operator explicitly passes an override. Trusted release `v0.2.8` published
> artifact-host image
> `ghcr.io/halildeu/platform-agent-artifacts:v0.2.8@sha256:b3118c6e14fd7cb6d157d684b56333e10eb99e9defc7d84dadbf9e078fca4a86`,
> `EndpointAgent.zip` SHA256
> `73ce4aaf0409344a36ea3619c8cca22cfdcb2a222002a902cd03e197145a6b06`, and
> agent binary SHA256
> `353e9b33d34862d9b42fb836c09f77ae485a8c2d19035efbaed02d2ed59de41b`.
> GitOps PR #1641 merged the test overlay digest pin; ArgoCD `platform-test`
> reports `Synced / Healthy` at revision
> `38fd3a3f90e3b261d87a9cc121268bcf54b0dc16`, and
> `platform-test/artifact-host` is `2/2` ready with both pods imageID
> `ghcr.io/halildeu/platform-agent-artifacts@sha256:b3118c6e14fd7cb6d157d684b56333e10eb99e9defc7d84dadbf9e078fca4a86`,
> `ready=true`, `restartCount=0`. Public
> `https://testai.acik.com/artifacts/endpoint-agent/current/` now serves
> `release_tag=v0.2.8`; `EndpointAgent.zip.sha256` matches
> `73ce4aaf0409344a36ea3619c8cca22cfdcb2a222002a902cd03e197145a6b06`; and
> public `bootstrap-package.ps1` contains `Resolve-BootstrapApiUrls`,
> `Get-PackageUrlHost`, and `https://mtls.$hostName/api/v1/endpoint-agent`
> with the older hardcoded `testai` API defaults absent. Project #2 issue
> #1640 has live acceptance evidence and Project Status `Done`. This refresh
> does not claim GPO/MSI pilot acceptance, 50/800 staged rollout, product
> remote-ops, or prod-domain readiness.

> **2026-06-17 AgentPC2 gate truth refresh**:
> Project #2 issue #1643 now tracks `AgentPC2` as the accepted third-device
> product-channel acceptance gate. Status is `Done` after tokenless mTLS
> auto-enroll, persisted DPAPI state, authenticated command polling, restart
> continuity, and `v0.2.9` artifact promotion evidence.
> Lab reverse SSH/RDP, open inbound SSH/WinRM/SMB/RPC, and operator-pasted
> commands are explicitly not acceptance evidence. #1601 has Denetim PC product
> remote-ops positive session evidence and is Project `Done`; `platform-backend#510`
> parent staging acceptance is also `Done` after
> `rb-denetim-20260618T145831Z` returned `PERMIT` with `transportPushed=true`
> on live digest
> `sha256:e66269bc609b35bc7f4a6f0ab8629a4fd14739827ea01d59ab3fc36e3833b392`.
> Signed MSI/GPO rollout acceptance is split to #1680. #1609 remains Done for
> the accepted `SRB-AIDENETIMPC` + `ERP-MOBIL` two-device record.

> **2026-06-17 remote-ops product-session refresh**:
> GitOps #1666 merged the remote-bridge heartbeat/freshness test overlay
> settings (`REMOTE_BRIDGE_HEARTBEAT_INTERVAL_MILLIS=10000`,
> `REMOTE_BRIDGE_PEER_TRUST_FRESHNESS_TTL_MILLIS=120000`). Live
> `platform-test/endpoint-admin-remote-bridge` is ready on imageID
> `ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:f76511a01ed8e5656008a796a6a4d7a094f886647da293739e8a0a49bb35565f`.
> Product-session acceptance contract is now canonicalized in
> `docs/runbooks/RB-faz22.6-product-remote-ops-session-gate.md`: outbound mTLS
> product channel only, typed `PTY_COMMAND hostname` read-only operation,
> approval/audit/negative evidence, and explicit exclusion of reverse
> SSH/RDP/manual bridge evidence.
> Denetim product smoke evidence directory:
> `/home/halil/codex-rb-smoke/20260617T191335Z-product`. HTTP path:
> `open=200`, `approve=200`, `challenge=200`, `verify=200`, `operation=200`;
> operation response `PERMIT`, `transportPushed=true`; non-pilot `FULL_RDP`
> remains rejected with `400`. Backend robustness follow-up
> `platform-backend#690` is now Done after DENY cleanup smoke
> `rb-deny-cleanup-20260617T211003Z`. ESO/Vault cleanup #1662 is also Done:
> remote-bridge ExternalSecrets are `Ready=True / SecretSynced` and final
> preflight is `PRECHECK_STATUS=ready failures=0 not_ready=0`.

> **2026-06-17 M4 MSI lifecycle lab-smoke refresh**:
> `platform-agent` #115 now has endpoint-side MSI lifecycle evidence from a
> snapshot-backed local Parallels Windows 11 VM. Source `platform-agent@08972ac`
> built lab MSI versions `0.1.2` and `0.1.3`; install, repair,
> `0.1.2 -> 0.1.3` upgrade, and uninstall all passed. Evidence ZIP SHA256 is
> `7cd97ba0922ecf11a2fc0ed63905816487733dcc01937915bafda2788f58d486`;
> MSI hashes are `F462CFB3214FDD1729961FA2168C089022F2ACC4A56195C7C69BDE04E8494441`
> (`0.1.2`) and `CB1A3B7C877B73739E97BBBAED5A2730B5C0090872E9ABC7D3077E4EA2DA40B4`
> (`0.1.3`). This proves controlled lab lifecycle behavior only. It does not
> prove production trusted code-signing, EDR/AppLocker/WDAC allowlisting, GPO
> rollout, or 5/50/800-device rollout; #115 therefore remains `Needs Verify`.

### 0.7 Remote Response Terminal Productization Lane — 2026-06-18

`platform-backend#510` kapalı parent staging acceptance, **güvenli taşıma ve
ürün session kapısını** kanıtlar: outbound mTLS/gRPC, product API
open/approve/challenge/verify/operation akışı, `PERMIT`, `transportPushed=true`,
`deny=null`, WORM/audit/recording ve immutable digest eşleşmesi. Bu kanıt
**serbest terminal** veya broad remote-support readiness anlamına gelmez.

2026-06-18 Claude CLI advisory sonucu: **koşullu evet**. Mimari rakiplerdeki
Microsoft Defender Live Response, CrowdStrike RTR, SentinelOne Remote Shell,
Sophos Live Response ve RMM Backstage/Remote Terminal sınıfıyla uyumludur; ürün
dili **"serbest terminal"** değil **Remote Response Terminal / Break-Glass
Response Shell** olmalıdır. Transport/auth layer #510 ile kabul edildi; komut
ve içerik katmanı ayrı 22.6.x productization fazı olarak yürür.

Board tracking:

| Lane | Board issue | Owner repo | Gate |
|---|---|---|---|
| **22.6.x governance + runbook** | `platform-k8s-gitops#1693` | gitops | Canonical no-go, acceptance checklist, evidence/runbook |
| **22.6.1 Operation Catalog** | `platform-backend#701` | backend | Approved diagnostic operations; raw shell yok |
| **22.6.2 Approved Script Runner** | `platform-backend#702` | backend | Signed/approved script library; arbitrary script text yok |
| **22.6.3 Break-glass constrained executor** | `platform-agent#208` | agent | Deny-by-default terminal executor; allowlisted diagnostic commands |
| **22.6.x operator UX** | `platform-web#820` | web | Justification, approval, step-up, TTL, recording state visible |

Canonical runbook skeleton:
[`docs/runbooks/RB-faz22.6-remote-response-terminal.md`](./runbooks/RB-faz22.6-remote-response-terminal.md).

#### 0.7.1 Product shape

Üç katmanlı sıra zorunludur; sonraki katman önceki katmanın yerine geçmez:

| Katman | Amaç | Varsayılan risk posture |
|---|---|---|
| **22.6.1 Approved Operation Catalog** | `GET_AGENT_STATUS`, `GET_AGENT_VERSION`, `GET_HOSTNAME`, `GET_NETWORK_SUMMARY`, `GET_SERVICE_STATUS`, `COLLECT_AGENT_LOGS`, `RUN_CERT_AUTOENROLL_PULSE`, `REFRESH_SOFTWARE_INVENTORY` gibi bounded operasyonlar | Default-deny, read-only ağırlıklı |
| **22.6.2 Approved Script Runner** | İmzalı, hash-pinned, versioned script library üzerinden bakım/triage script'i çalıştırma | Dual-control + WebAuthn + arg schema |
| **22.6.3 Break-Glass Remote Response Terminal** | Önceden kataloglanamayan incident/support durumunda kısa süreli, audit'li, allowlist'li terminal | High-risk, owner/approver gated |

#### 0.7.2 Non-negotiable no-go gates

Aşağıdaki koşullardan biri sağlanmıyorsa terminal veya script runner production
claim'i yapılamaz:

- Endpoint inbound RDP/SSH/WinRM/SMB/RPC yok; agent yalnız bizim broker'a
  outbound mTLS/gRPC açar.
- WORM/session recording kapatılamaz; audit sink down ise permit veya operation
  fail-closed olur.
- Operator ve approver aynı kişi olamaz; self-approval fail-closed olur.
- WebAuthn/MFA step-up terminal ve write/elevated script için zorunludur.
- Justification/ticket reference olmadan break-glass session açılamaz.
- Permit device-bound, tenant-bound, short-lived ve replay-safe olur.
- Command/script policy default-deny çalışır; unknown operation, raw
  `cmd`/`powershell`, encoded command, arbitrary download/execute ve credential
  export/dump sınıfları DENY olur.
- Transcript/output redaction vardır; JWT/token/password/private key/cert
  material response, browser log, audit body veya issue comment'e yazılmaz.
- File transfer ve clipboard default kapalıdır; ayrı owner-approved gate
  olmadan açılmaz.
- Kill/revoke, heartbeat-loss ve TTL expiry session'ı terminal state'e taşır.
- Tenant/device isolation negatifleri kanıtlanır.

#### 0.7.3 B1.4 hardware-attestation boundary

`platform-backend#548` açık/blocked kalır: true device-key / TPM
hardware-attestation agent wire üzerinde henüz kapanmadı. #510 staging parent
acceptance, B1.1-B1.3 ve enrollment-backed machine-cert trust için yeterli
bounded kanıt sağlar; **B1.4 closure değildir**. 22.6.1/22.6.2 staging pilotu
owner risk kabulüyle enrollment-backed trust üzerinde ilerleyebilir; 22.6.3
broad rollout veya production remote-support claim'i için #548 ya kapanır ya da
owner tarafından açık, süreli ve yazılı risk acceptance verilir.

2026-06-23 source progress: backend parser path `platform-backend#731`
(`5d1e4fd36792e5b7bb08fa312669c4f4db6c7038`) and agent producer path
`platform-agent#229` (`178db2952219e24951eba18c81e77480ed328d42`) are merged.
The agent can now assemble the strict v1 evidence envelope from pre-provisioned
SLSA/device-key material, and the backend can parse that envelope. This is
source/wire progress only; #548 remains blocked until real TPM/device-key
evidence, device-attestation roots/provisioning, broker verifier pass, negative
matrix, and accepted live field evidence exist.

#### 0.7.4 Acceptance evidence checklist

Her 22.6.x lane için kanıt issue comment'i ve current-state/runbook referansı
ile kalıcılaştırılır:

- allowed operation/script/terminal command: `PERMIT`, `transportPushed=true`,
  bounded output, WORM transcript.
- no-auth, missing role, self-approval, missing justification, missing step-up,
  wrong tenant, wrong device, expired permit, replayed `jti`/seq, audit-down,
  heartbeat-loss, mid-session revoke, clock skew: fail-closed.
- raw-shell classes (`cmd /c`, unrestricted `powershell`, encoded command,
  arbitrary download-and-execute, credential export/dump, arbitrary registry
  save, arbitrary service/task creation, arbitrary file delete): `DENY`,
  `transportPushed=false`, no endpoint execution.
- browser/operator UX shows risk, TTL, approver, consent/recording state and
  does not unlock input before server-side approval/step-up/recording gates.
- evidence explicitly says what it **does not** prove: signed MSI/GPO rollout,
  5-PC/50-PC/800-PC readiness, production support readiness, unrestricted
  shell/RDP/WinRM/SMB/SSH, and true TPM/device-key attestation unless that gate
  has separate accepted evidence.

#### 0.7.5 2026-06-20 #208 / #1768 no-go handoff

`platform-backend#718` merged the endpoint-admin machine-certificate rotation
fix, and the latest 2026-06-20 AgentPC2 constrained-executor acceptance rerun
(`platform-k8s-gitops` workflow `27871280141`; supersedes earlier reruns
`27869889116`, `27869662051`, `27868590359`, and `27867580698`) verified the staging
prerequisites before stopping at the intended no-go gate:

- endpoint-admin remote-bridge deployment/pod digest:
  `sha256:fb229ff98a1b7afb3cc31fe6de49312192686ee3ff6f80952494892d19b23b0d`
- artifact-host `v0.2.13` digest:
  `sha256:6d19a740c5ba4b1a555d3398f5b80387b98b769c1ada2814954d3d914c975454`
- public agent artifact SHA256:
  `6e3a79b8ea076d08e2288be98359d3db6049b6179e655ceaff924f792736cd0c`
- no-go reason: `pilot-readiness-agent-version-mismatch`
- AgentPC2 target/observed identity: AD object GUID
  `fa2d1ad6-a0a8-4101-ab77-9f2a0b25742a`; product device id
  `2f7ad30f-970a-42e7-8af8-08764ae6066f`
- AgentPC2 latest acceptance observed state:
  `agent_version=v0.2.12`, `status=ONLINE`,
  `last_seen_at=2026-06-20 12:33:18.975489+00`, `capabilities=[]`.
- readiness helper decision: `owner-approved-seed-required`, reason
  `Target is older and does not advertise UPDATE_AGENT; do not use Software
  Catalog or Approved Script Runner as a hidden installer lane.`
- acceptance evidence hashes:
  `summary.json=6ea4338267428c2e0171dc9d98d623f81a00464af172804ba3f044c89aafcfc6`,
  `pilot-readiness/summary.json=76ed0b6578198b11c7066b49daef2c4e0c216d8c18e10d9682ba069b3da2dbba`,
  `workflow-smoke.log=06e8b1409f2edcac6ac732f56ba126fd4efd0be8edd0ade00f459171d7235290`,
  `SHA256SUMS=afba29e7afd7de08361953f4574c76f42117c2a3865a10ccc303ea12f17b62da`.

Bu, `#208` için acceptance değildir. `#1768` first-install bootstrap artifact
hazırdır. Geçerli seed yolları sınırlıdır: heartbeat `UPDATE_AGENT` advertise
ettiğinde catalog-bound `UPDATE_AGENT`, owner-approved local maintenance install
for this one pilot endpoint, veya beklenen sürümle zaten sertifika-enrolled bir
test endpoint. Sıradaki geçerli kapı AgentPC2 üzerinde endpoint-local
`agentpc2-first-install-bootstrap.ps1` çalıştırılması ya da eşdeğer kabul edilen
seed yolundan sonra endpoint evidence'in `Faz 22.6.3 AgentPC2 first-install
evidence ingest` workflow'u ile doğrulanmasıdır. Bu ingest geçerse #208
workflow'u yeniden koşulur ve aynı session'da `HELLO`, permit,
constrained-operation, negative, audit ledger kanıtlarının alınması gerekir.
Software Catalog abuse, Approved Script Runner
download-and-execute, generic endpoint-commands `UPDATE_AGENT`, direct DB
insert, caller-supplied binary/hash/signer fields, raw PowerShell, unrestricted
terminal, RDP/WinRM/SMB/SSH/RPC veya reverse tunnel acceptance kanıtı değildir.
Bu kanıt gelmeden `#208`, broad rollout, production remote support veya
TPM/device-key closure dili kullanılmaz.

#### 0.7.6 2026-06-20 #208 v0.2.14 consent responder release

`platform-agent#213` merged the gated pilot consent responder that keeps
remote-bridge operation consent disabled by default and only enables the
bounded pilot path through explicit installer/MSI configuration. Release
`v0.2.14` then passed the trusted internal-CA EXE and MSI workflows:

- trusted EXE/artifact-host workflow:
  `https://github.com/Halildeu/platform-agent/actions/runs/27879277114`
- trusted MSI workflow:
  `https://github.com/Halildeu/platform-agent/actions/runs/27879277123`
- artifact-host `v0.2.14` digest:
  `sha256:54ad8a712df02e4ed445e7dd3d3b3e4261764265d04259121bbb4df7056aa7b0`
- public agent artifact SHA256:
  `624d7f4efd520de1382c7d82027a25cf2dd860bc5574eb31815eafa3c99d6618`
- EndpointAgent.zip SHA256:
  `2d7b372c7a3dda548caec66fbcb9327a04e54531369b9b1f2bd7f0c56910a7b1`
- signed MSI SHA256:
  `D5289D68050C5B703C9EDBFF6F338941BF894BD71DB0067DABED6EBA7D3C17ED`
- signer thumbprint:
  `D68F4F530137EB65CE44E3405E82B46205E753E5`

At this 0.7.6 stage, the evidence was release and desired-state evidence only.
#208 remained open until the pilot endpoint consumed `v0.2.14` through an
approved path and the constrained executor workflow recorded live outbound 443
mTLS `HELLO`, permit, constrained operation, negative/plaintext refusal, and
audit evidence. The 0.7.7 entry below adds the later live GitOps/SNI proof.

#### 0.7.7 2026-06-20 #208 v0.2.14 GitOps live + SNI broker route truth refresh

`platform-k8s-gitops#1796` merged the `v0.2.14` artifact-host test overlay
pin at `f8a45f34a0845d33d0c0d914a9e11d70913b977b`. ArgoCD `platform-test`
was refreshed to that revision and live `platform-test/artifact-host` rolled
out successfully:

- desired/live artifact-host image:
  `ghcr.io/halildeu/platform-agent-artifacts:v0.2.14@sha256:54ad8a712df02e4ed445e7dd3d3b3e4261764265d04259121bbb4df7056aa7b0`
- deployment state: `generation=19`, `observed=19`, `ready=2`,
  `updated=2`, `available=2`
- live pod imageID parity:
  `ghcr.io/halildeu/platform-agent-artifacts@sha256:54ad8a712df02e4ed445e7dd3d3b3e4261764265d04259121bbb4df7056aa7b0`,
  `ready=true`, restart count `0` on both pods

The dedicated remote bridge hostname was also live-rechecked through the
public 443/SNI entrypoint. `remote-bridge-mtls.testai.acik.com:443` serves
the AD CS leaf `CN=remote-bridge-mtls.testai.acik.com` with SHA256
fingerprint
`40:4E:21:30:0A:AD:34:C0:8D:E5:E9:D6:66:31:5B:9A:61:B5:99:D9:8C:8C:FC:27:1D:2D:2A:13:D5:DE:C0:D6`.
The sibling hostnames remain separated: `mtls.testai.acik.com:443` serves the
endpoint-agent mTLS API certificate and `testai.acik.com:443` serves the public
wildcard web certificate. Live `platform-web-nginx` stream config maps
`remote-bridge-mtls.testai.acik.com` to upstream `test_remote_bridge_broker`
via `172.19.0.2:19445`, and `endpoint-rb-node-forwarder` logged a successful
connection to the broker pod IP `10.45.62.59:9444` during the recheck.

The AgentPC2 endpoint acceptance gate is still open. Product update workflow
`27880118884` correctly returned HTTP `422` because the current AgentPC2
heartbeat does not advertise `UPDATE_AGENT`. Live DB state after the recheck:
product device `2f7ad30f-970a-42e7-8af8-08764ae6066f`, hostname `AgentPc2`,
`agent_version=v0.2.13`, `status=ONLINE`, `last_seen_at=2026-06-20
18:48:39.637374+00`. Bootstrap workflow `27880208124` produced the bounded
first-install handoff for `v0.2.14` with public agent artifact SHA256
`624d7f4efd520de1382c7d82027a25cf2dd860bc5574eb31815eafa3c99d6618`,
`install.ps1` SHA256
`5819207b63795ca0f14c1949f2a187dd996372f066992d692672e8f0d71c79df`, broker
`remote-bridge-mtls.testai.acik.com:443`, and permit public-key SHA256
`0a92abcd8f84619fb8f14f530beb94cbdc4e0981c9eb14a4756bdc85175a1110`.

This closes the SNI-routing prerequisite, not #208 itself. #208 remains open
until AgentPC2 consumes the pinned `v0.2.14` artifact through the approved
first-install/product path and the normal constrained-executor acceptance
records live outbound 443 mTLS `HELLO`, permit, constrained operation,
negative/plaintext refusal, and audit evidence.

#### 0.7.8 2026-06-22 #208 v0.2.23 product update stage succeeded, activation no-go

`platform-k8s-gitops#1848` merged a bounded AgentPC2 endpoint-local SHA256
signer-policy seed helper at
`5bbeeb868053469e7e6eb47245a1612b37980036`. Live artifact-host/public HTTPS
served
`agentpc2-self-update-policy-seed-v023-sha256.ps1` with SHA256
`0697369e93671e30de874b5f0589f8ed00355225284a70fa5f52ae1a0aac7aa1`.
Operator-run AgentPC2 evidence showed that the seed script hash matched,
`EndpointAgent` stayed `Running`, and local self-update signer policy now uses
the expected `sha256(cert.Raw)` fingerprint form.

The follow-up product `UPDATE_AGENT` workflow
`https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27934293027`
proved a narrower but important gate:

- release/version attempted: `v0.2.23` / `0.2.23`
- binary SHA256:
  `72b5c14f9b45111d450a363fce5ceecaae6310cbf7cdc9bd01d8d4c23e591484`
- release-manifest signer thumbprint:
  `D68F4F530137EB65CE44E3405E82B46205E753E5`
- command `f65c51be-8739-4a32-b531-3f5d25179d1d` reached AgentPC2 and
  returned `SUCCEEDED`
- result summary: `UPDATE_AGENT STAGED_ACTIVATION_READY`
- activation plan:
  `c015f8ec89519cb221f613b005004112`
- actual signer fingerprint:
  `EB16FA8C2C2325295483ED2271D87632DA5EA631E3095039D6CFC358F16CAACD`

The workflow still ended `no-go` because AgentPC2 did not report `v0.2.23`
inside the 900s observation window. It remained `ONLINE` at
`agent_version=v0.2.20`; direct DB recheck after the workflow confirmed the
same state. Therefore this stage evidence is **not** #208 acceptance and must
not be used as constrained executor, production support, broad rollout, or
unrestricted shell evidence.

Next valid gate: inspect/fix the endpoint-local self-update activation
helper/outcome for activation plan `c015f8ec89519cb221f613b005004112`, rerun
the product update until AgentPC2 reports `v0.2.23`, then run the normal
outbound 443 mTLS `HELLO` / permit / constrained-operation / negative / audit
acceptance workflow for `platform-agent#208`.

#### 0.7.9 2026-06-22 #208 activation outcome source hardening merged

The activation no-go in §0.7.8 exposed a source-side evidence gap: successful
activation wrote an outcome, but several failure and rollback paths could return
an in-process activation result without persisting
`activation-outcome-<stagingId>.json` in the endpoint-local self-update staging
root. That made a staged-but-not-activated product update harder to diagnose.

`platform-agent#222` merged the narrow source hardening at
`eaee50d569ff6e51d6441278225685afe7a3f352`:

- activation readiness failures, service stop failures, rollback outcomes, and
  rollback failures now attempt to persist local activation outcome evidence;
- outcome persistence failures are surfaced as path-free
  `evidencePersistenceError` while keeping `evidencePersisted=false`;
- fail-closed behavior is preserved; a failed activation is not converted into
  success because evidence writing failed;
- local tests and PR CI passed, including full `go test ./...`, Windows Go
  test, reproducible build, SBOM, gitleaks, and BG-EA-1 boundary declaration;
- Claude second-pass review reported no merge blocker after earlier review
  findings were addressed.

Boundary: this does **not** activate the currently installed AgentPC2
`v0.2.20`, does **not** close `platform-agent#208`, and does **not** replace
the required endpoint-local diagnostic for activation plan
`c015f8ec89519cb221f613b005004112`. It only ensures the next release/retry path
has stronger activation no-go evidence if activation fails again. The accepted
path remains: prove AgentPC2 is actually running the target version through the
product update path, then run outbound 443 mTLS `HELLO` / permit /
constrained-operation / negative / audit evidence for `platform-agent#208`.

#### 0.7.10 2026-06-23 #208 AgentPC2 v0.2.28 product-channel full-matrix accepted

The later product-channel path supersedes the earlier AgentPC2 activation
no-go for the narrow bounded pilot. AgentPC2 was updated through the release
catalog and then produced full-matrix constrained-executor evidence.

Product update evidence:

- workflow:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27964789754`
- result: `status=update-observed`, `reason=agent-version-updated`
- target: `AgentPc2` / `2f7ad30f-970a-42e7-8af8-08764ae6066f`
- observed endpoint state: `agent_version=v0.2.28`, `status=ONLINE`,
  `lastSeenAt=2026-06-22T15:38:07.751839Z`
- release artifact: `v0.2.28`, endpoint-agent.exe SHA256
  `e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4`,
  signer thumbprint `D68F4F530137EB65CE44E3405E82B46205E753E5`
- evidence SHA256SUMS hash:
  `77151aabe14ab316213edc10a19debaecec44d4752328e701485880f10e82ae8`

Constrained executor evidence:

- workflow:
  `https://github.com/Halildeu/platform-k8s-gitops/actions/runs/27992032625`
  (`success`)
- artifact: `agentpc2-constrained-executor-evidence-27992032625`
- runtime image digest:
  `sha256:0e451bb690f6511fe76292e1843ca95e2b9501aa20ae0e7ae7cd4eb1509c09f3`
- product path: `GET_HOSTNAME`, `CONSTRAINED_PTY`, `PERMIT`,
  `transportPushed=true`, `operationStatus=permit-transport-pushed`
- HTTP path: open/approve/step-up challenge/step-up verify/catalog operation
  returned `200/200/200/200/200`
- verifier result: `accepted-candidate`, `requireFullMatrix=true`,
  `fullMatrixOk=true`
- recording evidence: `rowCount=3`, `hasAgentOutput=true`,
  `hasEndStream=true`
- negative evidence: no-auth catalog `401`, disabled catalog `422`,
  command/policy override `400`, raw unrestricted PTY `400`, non-pilot
  capability open `400`, wrong-device/unenrolled open `404`, expired permit
  `422`, replay `422`, operator close `204`, and closed-session operation
  `404`
- post-run cleanup: no run-scoped annotation and no step-up public-key env
  override remained on the deployment

Live runtime re-check on 2026-06-23 matches that accepted evidence boundary:
`endpoint-admin-remote-bridge` is running digest
`sha256:0e451bb690f6511fe76292e1843ca95e2b9501aa20ae0e7ae7cd4eb1509c09f3`
with `restartCount=0`; all three remote-bridge ExternalSecrets are
`Ready=True / SecretSynced`; broker heartbeat interval is `5000ms`; and the
recent audit log shows `HELLO_VERIFIED:cert=true,attestation=false,device=false`.
This proves current product-channel connectivity for the bounded AgentPC2
executor gate, not true device-key / TPM attestation.

Board result: `platform-agent#208` is Closed / Done for the bounded AgentPC2
product-channel constrained executor scope. `platform-k8s-gitops#1768` and
stale pointer `platform-agent#116` are also Closed / Done as superseded by this
accepted evidence.

Boundary: this does not prove production remote support, broad signed MSI/GPO
rollout, 5/50/800 device waves, inbound SSH/RDP/WinRM/SMB/RPC, unrestricted
shell/file browser/clipboard/file transfer, or true TPM/device-key hardware
attestation. `platform-backend#548` remains Open / Blocked for broad rollout
hardware-attestation evidence.

Bu doküman Endpoint-Enes / Endpoint Admin agent hattına **ücretsiz ve sektör
standardına yakın yazılım yönetimi** kabiliyeti eklemek için takip edilebilir
planı tanımlar.

Bu plan artık testai üzerinde install/uninstall runtime kabiliyeti ve local
Parallels üzerinde AG-029 self-update baseline kabiliyeti iddia eder; bu iddia
yalnız kanıtlanan test kapsamı içindir. 2026-05-27 üç-AI değerlendirmesi
(Claude Code + Codex + MiniMax/Mavis) ortak hükmü **REVISE** idi: read-only
agent temeli doğru yönde başlamış, fakat program kurma kabiliyeti `BE-020`
catalog, command contract, detection/result/audit ve web yüzeyi gelmeden
açılmayacaktı. Sonraki kanıtlar bu kapıların test kapsamında geçtiğini
gösterir; prod/domain-wide deployment-ready iddiası üretmez.

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
| Outdated software / inventory diff / prohibited | `platform-backend` + `platform-agent` | AG-036 SOURCE-MERGED (agent PR #38 `a29eef4` + #40 `e64c131` `UpgradeTruncated` fix; backend PR #336 `7f8c1a90` V20 ingest+query); BE-024 SOURCE-MERGED (PR #334 `d154ac7a` V18 software-inventory state diff/history, atomic ON CONFLICT append); BE-025 SOURCE-MERGED (PR #335 `7bb0340e` V19 prohibited-software denylist + EndpointComplianceService integration); cluster image `sha256:389565a9d5411247be6735f6816a77e3906ad2ecf8552ea5216d64584618be97` includes these surfaces. 2026-06-07 #1164 live admin JWT smoke used a role-bearing `ENDPOINT_ADMIN` token (`userId=1169`) + OpenFGA `can_view`; 4/4 direct service endpoints returned 200 JSON: `/software-inventory/diff`, `/software-inventory/history`, `/outdated-software/latest`, `/prohibited-software` | SOURCE-MERGED + TESTAI LIVE acceptance for admin JWT path (#1164); no-JWT fail-closed remains 401; user-owned #1044 multi-device soak is separate |
| Posture / health / hotfix / diagnostics / services / exposure | `platform-agent` | AG-030 / AG-031 / AG-032 / AG-033 SOURCE-MERGED (PRs #33/#34/#35/#36, Codex cross-AI AGREE) + local Parallels temp-probe evidence 2026-06-07; **AG-037 MERGED + LIVE 2026-06-01** (end-to-end chain agent #45 + backend #354/#355 + web #723 + gitops #1167/#1168 + HALILKOOLUB735 86 installed + 1 pending real WUA telemetry + browser smoke); **AG-038 MERGED + LIVE 2026-06-01** end-to-end chain (agent #39 + backend #357/#355 V23 LIVE + web #727 + gitops #1181 digest bump APPLIED + browser-verified Agent Tanılaması tab 404 empty + `includeDiagnostics:true` literal hint) + local temp-probe fail-closed evidence when backend service env is absent; **AG-039 SOURCE-MERGED + backend LIVE 2026-06-01** end-to-end 3-repo chain: agent PR [#47](https://github.com/Halildeu/platform-agent/pull/47) `0d8e7b4` (critical services probe — 6-service canonical allowlist WinDefend/wuauserv/BITS/EventLog/EndpointAgent/MpsSvc; per-service {present, state, startupMode} from SCM + registry) + backend PR [#362](https://github.com/Halildeu/platform-backend/pull/362) `65d9fbd5` (V24 migration + ingest + GET /services/latest query) + web PR [#728](https://github.com/Halildeu/platform-web/pull/728) ServicesView drawer tab (Codex 019e8389 2-iter REVISE→PARTIAL→AGREE absorb 6+1 must_fix incl. IslemlerTab default 8-bit payload + fail-closed container parity + startupMode=DISABLED danger chip + DICT_EN parity + nullable summary/serviceName) + local Parallels probe of all six canonical services; **AG-040 SOURCE-MERGED 2026-06-01** end-to-end chain (agent 92320cd + backend b6daaee2 V25 startup-exposure ingest+query + web PR [#729](https://github.com/Halildeu/platform-web/pull/729) StartupExposureView drawer tab; Codex 019e83a6 3-iter REVISE→REVISE→AGREE absorb incl. AG-040/AG-041 numbering disambiguation + fail-closed exposure-scalar evidence helpers + per-scalar polarity split + StartupAppLocation enum source type) + local redaction/fail-closed probe evidence; AG-041 (Application Control / WDAC / AppLocker) reserved for new zincir | AG-037/AG-038 LIVE; AG-030–033 and AG-039 local Parallels probe evidence added; AG-040 local redaction/fail-closed evidence added; AG-039/AG-040 backend/browser acceptance remains separate; AG-041 TODO |
| Uninstall + signed self-update + rollout controls | `platform-agent` + `platform-backend` + `platform-web` + `platform-k8s-gitops` | AG-028 testai go-live proven 2026-06-04; AG-029 source fix/checklist MERGED + local Parallels post-merge baseline proven 2026-06-07; BE-026..BE-033 source/digest path progressed separately | PARTIAL |
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

### 0.4 Standard PC Install Productization Lane — 2026-06-08

MKR-A1 standard `acik.local` Windows 11 cihaz testi, agent runtime'ın
çalışabildiğini ama kurulum deneyiminin 800-PC rollout için
ürünleştirilmesi gerektiğini gösterdi. Bu lane, Faz 22.5 yazılım yönetimi
kabiliyetini Faz 22.3 domain-wide dağıtım kanalıyla bağlar; mevcut 22.5
install/uninstall kanıtlarını supersede etmez.

**Observed standard-PC friction (MKR-A1):**

- App Installer yüklüydü ama `winget.exe` user alias/PATH başlangıçta yoktu.
- `install.ps1` Windows PowerShell 5.1 altında encoding/parse hatası verdi.
- Enrollment token clipboard/paste akışı kırıldı; tek tek token girmek
  800-PC rollout için kabul edilemez.
- Geçici artifact route ve elle ZIP/SHA/binary swap kullanıldı.
- AG-038 `configHash` kısa gönderildi, backend 64-char bekledi; result submit
  400 oldu ve command lifecycle görünürlüğü yetersiz kaldı.
- ESET/EDR agent service + HTTPS trafiğini engellemedi, fakat signing/allowlist
  kurumsal dağıtım kapısı olarak kalır.

**Non-negotiable target:**

- Domain cihazları için per-PC one-time token ve elle ZIP taşıma yok.
- 800-PC yolunda signed MSI + GPO Software Installation + machine
  cert/mTLS auto-enroll ana kanal olur.
- Domain dışı/hızlı pilot için tek satır signed/hash-verified bootstrap +
  kısa ömürlü claim-code kullanılabilir.
- Command/result submit hataları `DELIVERED` gibi sessiz kalmaz; agent/backend
  tarafında retry/fail/last-error görünürlüğü üretilir.

| Milestone | Scope | Sahip repo / kanal | Tahmini süre | Acceptance |
|---|---|---|---:|---|
| **M0 Official Hotfix Release** | AG-038 full `configHash`, PS5.1 installer encoding/BOM regression, canonical artifact URL, initial Authenticode/dev-signing path, result-submit 4xx/5xx visibility | `platform-agent` + `platform-backend` + release/artifact ops | **1-2 iş günü** | MKR-A1 clean reinstall: service running + enrollment OK + HMAC OK + `COLLECT_INVENTORY` result submit 200 + audit row |
| **M1 One-command Pilot Bootstrap** | Signed/hash-verified PowerShell bootstrap, short-lived claim-code, AppInstaller/WinGet readiness check/repair, post-install smoke | `platform-agent` + backend enrollment surface | **1-2 iş günü** | 2-5 pilot cihazda tek komutla install + enroll + inventory smoke; raw token paste yok |
| **M2 Backend mTLS Auto-enroll** | Machine cert doğrulayan `POST /endpoint-enrollments/auto`, AD computer identity binding, audit/revoke semantics | `platform-backend` | **PROD HOST LIVE / broader rollout gates separate** | `mtls.testai.acik.com` test edge/backend mTLS, no-cert fail-closed, valid ERP-MOBIL machine cert AutoEnroll HTTP 201, DB/audit cert identity, #155 tokenless heartbeat rows, #157 cert-auth command/result smoke (`COLLECT_INVENTORY` command `125d46a7-55b7-4379-a7d2-72bf7b0600cc` -> `SUCCEEDED`), #1569 durable no-hosts AD DNS + service restart continuity proven/closed, #1377 same-day selected-device M5 accepted, and prod `mtls.ai.acik.com` activation proven via #1593 + ingress-nginx rev4 ssl-passthrough: AD CS backend cert served, no-cert `exit=56` fail-closed, `SRB-AIDENETIMPC` machine-cert AutoEnroll HTTP 201, isolated-config agent `-once` logged `auto-enroll already-enrolled` + `no command available`, exit 0. Remaining broad rollout gates: 50/800 wave, longer stabilization, OS reboot continuity, revocation/wrong-CA matrix if retained, and destructive rollback/uninstall drills. |
| **M3 Agent `--auto-enroll`** | Agent machine cert/domain identity ile backend auto-enroll, fallback claim-code ayrımı | `platform-agent` | **BOUNDED LIVE / accepted for AgentPC2 product-channel scope** | Domain cihazda kullanıcı token'ı olmadan service start -> enrolled -> heartbeat proven on ERP-MOBIL and AgentPC2; #171/#v0.2.4 CNG signer fix released; #207/v0.2.9 CNG/KSP signer fix promoted for AgentPC2; restart logs show `auto-enroll cert loaded` + authenticated command polling over durable `mtls.testai.acik.com`. Remaining: signed MSI/GPO bootstrap acceptance, OS reboot continuity, broader rollout |
| **M4 Signed WiX MSI** | Authenticode signed MSI, fixed UpgradeCode, service install/upgrade/uninstall, EDR allowlist doc | `platform-agent` CI + operator signing | **Artifact ready / endpoint pilot Needs Verify** | #115 lab MSI lifecycle smoke passed on snapshot-backed local Parallels Windows 11 (`0.1.2` install/repair -> `0.1.3` upgrade -> uninstall). Trusted MSI run `27794936579` produced `EndpointAgent-0.2.10-signed.msi` SHA256 `132b8990bc78c4952ccaa7d2076cf26a37f0616f81e1a82274b5570b49f24ea4`, `production=true`, `trusted-internal-ca`, `timestamped=true`, signer thumbprint `D68F4F530137EB65CE44E3405E82B46205E753E5`, and root cert SHA256 `078494D03E2FB51EA35DB71FFC04B5C5230EE9F52E0D5A057B6F35B8F7E0B59E`; the MSI and `msi-build-manifest.json` SHA256 `68929426674f6524e6fdbc78e2eb024920cfd686dd637573537c1717196c69ee` are durable `v0.2.10` release assets. Current public agent artifact is also `v0.2.10` (`EndpointAgent.zip` SHA256 `fa72f278b81497bf2480ea312c7d13cff410372bfcef6ddca23dc3e50a1f292e`), so the previous `signed != current` blocker is removed. #1680 evidence must still run collectors with `ExpectedMinimumAgentVersion=0.2.10`; the signed MSI artifact alone cannot close the two-device GPO/MSI install, mTLS, rollback, and failure-triage gates. |
| **M5 Same-day selected-device pilot** | Pilot OU'ya GPO Software Installation for domain-gpo devices; local Parallels/control + denetim evidence lanes; T0/T+15/T+60 collector monitoring | Operator + IT + gitops evidence | **aynı gün** (no-24h owner direction) | Board #1377 accepted the earlier same-day selected-device scope; #1609 narrows active productization to max 2 devices and #1643 accepts AgentPC2 as the third product-channel device. Signed MSI/GPO rollout acceptance is split to #1680 before any broader wave; #1680 now requires a single selected method (`gpo-msi` or `one-command-bootstrap`), constrained pilot targeting, per-device collector evidence with the current version floor, and one rollback drill. `scripts/faz22-mass-deployment/build-gpo-msi-acceptance-bundle.ps1` prepares the non-secret `v0.2.10` `gpo-msi` pilot bundle (MSI, manifest, startup install, verify, rollback, collectors, and read-only evidence-package verifier) so the operator-bound/domain-ops step runs an exact script/artifact set instead of ad-hoc commands. |
| **M5A Domain Ops Broker gate** | Delegated Windows service for EndpointTest OU / EndpointAgentPilotComputers / Endpoint Agent GPO mutation; maker-checker + TTL + audit | `platform-k8s-gitops` plan + backend/ops implementation | **P0 design gate + first slice accepted** | SSH/RDP clipboard is not the durable AD/GPO mutation channel. Broker design is documented in `docs/faz-22-domain-ops-broker-plan.md`; platform-backend #676 accepted the Admin API + durable request state + credential-ref custody + typed connector dispatch + deterministic fail-closed result/status/audit slice. Real AD/GPO mutation success remains a later connector/live gate. |
| **M5B Remote-ops MVP safety gate** | Endpoint-side outbound mTLS operatorless diagnostics/remediation; default-off, TTL, bounded command allowlist, no raw shell | `platform-agent` + backend broker surface | **PARENT STAGING ACCEPTED / #510 + #1601 Done** | `platform-backend#510` parent staging acceptance is closed on `rb-denetim-20260618T145831Z`: live digest `sha256:e66269bc609b35bc7f4a6f0ab8629a4fd14739827ea01d59ab3fc36e3833b392`, mTLS `HELLO_VERIFIED:cert=true,attestation=true`, operation `PERMIT`, `transportPushed=true`, negative non-pilot `400`, evidence bundle `/home/halil/codex-rb-smoke/20260618T145831Z-parent-acceptance`. #1601 bounded MVP remains Done; AgentPC2 product-channel evidence is accepted under #1643. Signed MSI/GPO rollout, rollback drill, packaged agent remote-ops capability, and broader device waves remain separate gates. Temporary reverse SSH is lab-only. |
| **M6 50-PC Wave** | Ring/tag rollout, concurrency/maintenance window discipline, alerting | Operator + backend rollout controls | **GATE CLOSED by #1609** | Do not start a 50-PC denominator while only 2 active pilot devices are available. Reopen only after the owner-approved two-device evidence pair is accepted, remote-ops MVP safety gate, signed MSI/GPO smoke, rollback/reinstall proof, and explicit owner acceptance. `AgentPC2` should be used as the next product-channel verify candidate when GPO/MSI or remote-ops access is stable. |
| **M7 800-PC Rollout** | OU/ring bazlı staged rollout, rollback/uninstall path, stale-device alerting | Operator + IT | **1-2 hafta** staged | 800-PC rollout raporu; failed devices explicit queue; rollback path ready |

**Duration baseline:** signing/AD CS/GPO erişimleri hazırsa selected-device M5
same-day smoke kapısına **aynı gün**, 50/800 staged rollout kapısına yaklaşık **2-3 hafta**
gerçekçi görünür. AD CS/code-signing/EDR allowlist procurement hazır değilse
bu süreye **3-10+ iş günü** operator beklemesi eklenir.

**No-24h boundary (owner 2026-06-15):** M5 için 24h bekleme yapılmayacak. Bu,
same-day pilot hızını artırır fakat 50/800 ramp öncesi risk notunu zorunlu kılar:
M6 ya açık no-24h risk acceptance ile başlar ya da ayrı bir stabilization gate
eklenir.

**Pilot-cap boundary (owner 2026-06-16 / #1609):** 50-PC M6 artık açık risk
acceptance ile bile otomatik başlamaz. Kullanıcı aynı anda en fazla iki aktif
pilot cihaz sağlayabildiği için, sektör-standardına yakın güvenli yol iki
kanıtlanmış cihazla acceptance almak ve geniş dalgayı kapalı tutmaktır. Bu
oturumda owner-approved acceptance pair `SRB-AIDENETIMPC` + `ERP-MOBIL` olarak
kanıtlandı. `AgentPC2` artık #1609 iki-cihaz kaydının kapanış blocker'ı değil;
#1643 altında kabul edilmiş üçüncü cihaz product-channel gate'idir. Bu, signed
MSI/GPO rollout acceptance değildir; o gate #1680'e ayrılmıştır. AD/GPO
mutation için kalıcı model SSH değil,
`docs/faz-22-domain-ops-broker-plan.md` içindeki delegated Domain Ops
Broker'dır.

**2026-06-08 implementation delta:**

- `platform-agent` PR #102 MERGED: PS5.1-safe installer packaging, UTF-8 BOM
  packaged scripts, ZIP bootstrap, internal SHA256 verification and encoding
  regression gate. Main workflow run `27134177634` produced unsigned and
  lab-evidence artifacts successfully.
- `platform-agent` PR #103 MERGED: the same bootstrap/install lane now supports
  `-AutoEnroll` with machine-certificate filter requirements and HMAC fallback
  separation. Main workflow run `27137185247` succeeded.
- `platform-agent` PR #105 MERGED: AutoEnroll default/base examples were
  aligned with the deployed gateway/backend route. The agent AutoEnroll client
  appends `/endpoint-enrollments/auto`, so the canonical external base is
  `https://mtls.testai.acik.com/api/v1/endpoint-agent`.
- `platform-agent` PR #106 MERGED: the packaged `bootstrap-package.ps1`
  default and installer README were also aligned to
  `/api/v1/endpoint-agent`; `scripts/test/windows-installer-encoding.sh` now
  guards this canonical URL. Main workflow run `27142499833` succeeded.
- `platform-agent` PR #107 MERGED: the direct `install.ps1` `-AutoEnroll`
  default was aligned to `/api/v1/endpoint-agent`; the static encoding guard
  now requires this URL and rejects stale `/api/v1/endpoint-admin` in both
  install and bootstrap scripts. Main workflow run `27144437218` succeeded
  across Linux build/package, lab signing and Windows Go test.
- Canonical test artifact endpoint refreshed again after artifact-host v0.2.4
  promotion: `https://testai.acik.com/artifacts/endpoint-agent/current/`
  serves the live pilot pointer, with immutable equivalent under
  `/artifacts/endpoint-agent/v0.2.4/`. Current `EndpointAgent.zip` SHA256 is
  `9caea9fb851513717cc1e3d54c5378dd850731de8e73e21df9351cf7077ec8a8`; agent
  binary SHA256 is
  `067e42eab24ee1f73dc28903774c6f5db6c6dcb2bf1163271efa3803587e06a3`.
  The older `/0.1.0-dev/` path is stale and returns 404 on the live artifact
  host. Public/internal HTTPS verification confirmed `current/` and `v0.2.4/`
  `bootstrap-package.ps1`, `EndpointAgent.zip`, `EndpointAgent.zip.sha256`,
  `SHA256SUMS`, and `release-manifest.json` return HTTP 200.
- 2026-06-16 follow-up: `platform-agent` #193/#194 merged and trusted release
  `v0.2.7` published a release asset manifest with artifact-host digest
  `sha256:c1266c66fd1f53fdbcec23f815ee181bb3f574624aa6267df9fb63c4b99b00d8`;
  GitOps #1602 merged the test artifact-host pin to this immutable image so
  `/current/` serves the remote-bridge-capable bootstrap after ArgoCD sync.
  Follow-up public live checks show `release_tag=v0.2.7`,
  `EndpointAgent.zip.sha256=598add6fa01cf8fd5adc3acd8c68ef2a251452831bfbc3246c7ea26c590b9f97`,
  and bootstrap remote-bridge parameters present. Pod imageID verification is
  still pending staging/k3d-test access.
- `platform-backend` PR #511 MERGED: rejected result submissions no longer
  leave commands silently locked; backend marks command `FAILED`, clears claim
  lock and stores bounded/redacted `RESULT_REJECTED` last-error without
  persisting rejected raw payload rows.
- `platform-k8s-gitops` PR #1355 MERGED: endpoint-admin test overlay pin for
  the #511 backend image digest; live pod imageID matches
  `sha256:0c1e384b414b35ddd9540fa6fcacb9fcc6a856a19ca25d92277166f76041ae45`.
- `platform-k8s-gitops` PR #1358 MERGED: api-gateway route parity for
  `/api/v1/endpoint-agent/endpoint-enrollments/auto`; live no-cert POST reaches
  backend and returns `MTLS_CERT_MISSING`.
- `platform-k8s-gitops` edge runbook added:
  `docs/runbooks/RB-faz22.3-edge-mtls-autoenroll.md`; canonical passthrough
  activation is now `docs/runbooks/RB-faz22-M2-edge-mtls-activation.md`. The
  dedicated hosts are `mtls.testai.acik.com` for test/pilot and
  `mtls.ai.acik.com` for prod. The runbooks define the backend header contract
  (`X-Client-Cert` + `X-Tenant-Id`), spoof-header stripping, no-cert negative
  smoke, header-injection negative smoke and valid machine-cert positive smoke.
- 2026-06-08 local Parallels rerun: `HALILKOOLUB735` downloaded the canonical
  #107 `EndpointAgent.zip` from `testai.acik.com`, verified SHA256, installed
  the current binary, enrolled through the HMAC fallback path, confirmed HMAC
  credential persistence, removed enrollment-token material from the service
  environment and completed backend -> agent -> result -> audit
  `COLLECT_INVENTORY` command `5482af96-b480-463f-a5a1-2d8b3bcd6aa4`
  `SUCCEEDED`. Evidence:
  `docs/faz-22-evidence/2026-06-08-agent-101-parallels-bootstrap-smoke.md`.
- Fresh-reinstall product gap: the first rerun on an already-enrolled machine
  loaded the existing DPAPI HMAC store while a new enrollment token was
  supplied. That is acceptable for upgrade continuity but ambiguous for fresh
  re-enrollment. platform-agent #109 now tracks an explicit
  fail-fast/reset-credential-store guard.
- Board state: `platform-agent` #101 has HMAC fallback standard-PC runtime
  evidence for board acceptance; `platform-backend` #509 has runtime
  invalid-result visibility evidence. `platform-k8s-gitops` #1359 tracks the
  DNS/edge mTLS host activation gate for tokenless AutoEnroll.

**Claude CLI advisory 2026-06-08:** verdict `AGREE — conditional`. Absorbed
revizyonlar: (1) bootstrap claim-code -> mTLS geçişi netleşti, (2) signing M4'e
bırakılmayıp M0/M1'de başlatıldı, (3) result-submit silent failure P0-0 olarak
öne alındı.

### 0.5 Sensitive Endpoint Ops Boundary - 2026-06-09

Kullanıcı talebiyle tartışılan gRPC-streaming benzeri sürekli kanal, SSH/remote
support, SMB/file actions, endpoint backup, offboarding copy ve forensic
collection işleri Faz 22.5 software deployment kapsamına eklenmez. Bunlar ayrı
güvenlik modeli gerektirir.

| Alan | Canonical yer | Board authority | 22.5 ile ilişki |
|---|---|---|---|
| Remote support / reverse tunnel / session broker | [Faz 22.6 Remote Access Bridge](./faz-22-remote-access-bridge-plan.md) | gitops #1388/#1389, backend #510/#524, agent #116 | 22.5 command polling yerine geçmez |
| Compliance Gap Mart aggregate reporting | [Faz 22.7 Compliance Gap Mart Layer](./sprint-plan-faz-22-7-compliance-gap-mart.md) | backend #376 | 22.5 visibility verisini aggregate eder |
| Endpoint backup / offboarding / forensic collection | [Faz 22.8 Endpoint Data Protection](./faz-22-endpoint-data-protection-plan.md) | gitops #1388/#1390, agent #117 | AG-034 discovery'den türeyen runtime file-copy işi 22.8'e taşınır |
| Endpoint security telemetry / detection extension | [Faz 22.9 Endpoint Security Telemetry](./faz-22-security-telemetry-plan.md) | gitops #1400/#1404, #1388 runtime gate | osquery/YARA/Sigma/Wazuh değerlendirmesi 22.5 software quick-win kapsamı değildir |
| Sensitive endpoint ops governance | Gate issue, phase değil | gitops #1388 | 22.6 ve 22.8 runtime ön koşulu |

Bu ayrımın pratik sonucu: AG-034 22.5 içinde yalnız threat-model/discovery
olarak kalır. Runtime SMB/file copy, backup veya forensic collection iddiası
ancak #1388 governance gate ve 22.8 charter kabulünden sonra kurulabilir.

OSS-only build-vs-buy kararları #1400 altında tutulur. Güncel karar özeti:
22.6 için endpoint-admin broker/policy/audit core bizde, MeshCentral yalnız
transport POC primary aday, RustDesk secondary/defer; 22.8A için Kopia primary
backup engine adayı, restic fallback, BorgBackup watchlist; 22.8C için
Velociraptor reference/serverless ops-adapter only; 22.9 için osquery/YARA
bounded candidate, Sigma license-gated reference, Wazuh core adoption
reject/defer. Bu kararların hiçbiri 22.5 runtime scope'unu genişletmez.

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
| **AG-036** | `platform-agent` | Outdated software inventory | **SOURCE-MERGED + TESTAI LIVE admin JWT surface smoke 2026-06-07 (#1164)** | WinGet `upgrade --include-returning-apps --source winget` read-only; otomatik upgrade YOK; per-package `{packageId, installedVersion, availableVersion}` (no Name/Source/publisher/install path/stdout/stderr on wire); PR #40 `UpgradeTruncated` semantics for results exceeding cap; opt-in `COLLECT_INVENTORY{includeOutdatedSoftware:true}` flag + `daa072e1` (#339) `collect-now` opt-in; contract: `docs/faz-22-outdated-software-contract-v1.md`; `/outdated-software/latest` returned 200 JSON under role-bearing admin JWT |
| **BE-024** | `platform-backend` | Software inventory diff/history | **SOURCE-MERGED + TESTAI LIVE 2026-06-07 (#1164)** | Append-only `endpoint_software_inventory_state_history` (full apps[] snapshots; summary-only + egress-only ingests skipped); REST: `GET /software-inventory/diff` (latest-vs-previous) + `GET /software-inventory/history`; synthetic `appKey` (BE-020I installed inventory has no packageId, so packageId reserved for WinGet/outdated/catalog surfaces); atomic ON CONFLICT append; user path/log YOK; `/software-inventory/diff` 200 status=OK and `/software-inventory/history` 200 totalElements=5 under role-bearing admin JWT |
| **BE-025** | `platform-backend` | Prohibited software detection | **SOURCE-MERGED + TESTAI LIVE 2026-06-07 (#1164)** | Non-catalog-bound `endpoint_prohibited_software_rules` table + `ProhibitedSoftwareRuleService` + `EndpointComplianceService` integration; `ComplianceState = UNAUTHORIZED` with reason `prohibited_app_installed` (NO new `PROHIBITED` enum — V19 migration comment explicitly says catalog-bound `FORBIDDEN` is contradictory for banned software); otomatik uninstall YOK; `/prohibited-software` returned 200 status=OK under role-bearing admin JWT |
| **WEB-011** | `platform-web` | Software inventory view | **MERGED + LIVE (PR #674 `70a038ac`)** | InventoryTab software + WinGet readiness; gateway path; testai deployed |
| **WEB-014A** | `platform-web` | Compliance Tab + GET state + POST evaluate | **MERGED + LIVE (PR #675 `0c4f33a8`)** | Read-only compliance tab + evaluate trigger |
| **WEB-014B** | `platform-web` | Cross-device compliance list + per-device history | **MERGED + LIVE (PR #676 `b6b15983`)** | Org-level compliance list + per-device evaluation history |
| **WEB-014C** | `platform-web` | Policy CRUD UI (REQUIRED/ALLOWED/FORBIDDEN) | **MERGED + LIVE (PR #678 + PR #682)** | Per catalog item policy CRUD; bulk import deferred |
| **WEB-014D / WEB-012** | `platform-web` | Approved install UI surface | **MERGED + LIVE (PR #683 + perf/follow-up PR #693, Codex absorb)** | Full chain LIVE: `SoftwareCatalogTab.tsx` "Kur" button per catalog row → `InstallPreflightModal.tsx` PASS/WARN/BLOCK + `useCreateInstallMutation()` dispatch POST + "Son Kurulumlar" audit panel via `useListInstallAuditsQuery` with auto-refetch on `EndpointInstallAudit:device-{id}` tag invalidation. Codex 019e6ff0 post-impl absorb already applied (in-flight POST race guard) |
| **WEB-015** | `platform-web` | Endpoint report / CSV export | **MERGED + TESTAI LIVE 2026-06-07 (#1134)** | RBAC-controlled export; public gateway `POST /api/v1/endpoint-admin/endpoint-devices/export` with `{format:csv, exportMode:raw}` returned 200 `text/csv;charset=UTF-8`, filename `endpoint-devices-raw.csv`, 7 lines, and headers including `Bilgisayar Adı`, `Yasaklı Yazılım`, `Ajan Son Poll` |
| **AG-028** | `platform-agent` + `platform-backend` + `platform-web` + `platform-k8s-gitops` | Software uninstall / detection | **SOURCE-MERGED + TESTAI LIVE (2026-06-04)** | Catalog-managed package only; real 7-Zip uninstall on HALILKOOLUB735 verified `SUCCEEDED_VERIFIED` + `ABSENT_VERIFIED`; maker-checker proposer != approver enforced; prod remains dark |
| **AG-029** | `platform-agent` | Signed agent self-update | **MERGED + LOCAL PARALLELS BASELINE (2026-06-07)** | PR #74 `656cd1a` fixed Windows verifier sharing violation; PR #75 `5f32181` added multi-device checklist; accepted #55 evidence updated `HALILKOOLUB735` from `0.1.0-dev` to `0.1.4-lab.1` through BE-031/BE-032 release/dispatch path with negative trust-field preflight, `SUCCEEDED` command, `ACTIVATED` outcome, service `Running`, and backend heartbeat match. Remaining: multi-device batch, trusted production signing and rollout policy acceptance |
| **AG-042** | `platform-agent` + `platform-backend` | Local SAM lock / unlock / password change | **AGENT-SIDE + BACKEND DISPATCH PROVEN (2026-06-07)** | Agent-side: `TestMutateLocalWindowsIntegration` created disposable `ea-pwd-0607a`, exercised `LOCK_USER_LOGIN` + `UNLOCK_USER_LOGIN` + `CHANGE_LOCAL_PASSWORD`, removed the user, and reported `secretEchoed=false`. Backend/JWT dispatch: AG-092 `LOCK_USER_LOGIN` command `2825b275-4f31-4324-9ad6-a96e08d8b27e` reached the agent and failed safely on reserved `Administrator` with VM unchanged; AG-042 `CHANGE_LOCAL_PASSWORD` command `c06cd030-c62e-40da-814d-90956e960eaa` succeeded on disposable local user `ea-recovery-smoke`, then cleanup verified `ABSENT`; #1343 disposable success-path smoke then proved `LOCK_USER_LOGIN` command `a8dfaac1-1c3b-4f4f-84cd-77b62c2bd553` `SUCCEEDED` (`Enabled=true -> false`) and `UNLOCK_USER_LOGIN` command `fd62b31e-c84a-4ee7-b1d0-e433c35768e1` `SUCCEEDED` (`Enabled=false -> true`) on `ea-lockunlock-smoke`, followed by cleanup. Domain/M365/cached-domain/pre-logon VPN behavior remains out of scope |
| **AG-030P** | `platform-agent` | Auto-enroll dry-run certstore preflight hardening | **MERGED + LOCAL PARALLELS NO-CRASH PROOF (PR #77, 2026-06-07)** | `-auto-enroll -dry-run` no longer broad-scans arbitrary LocalMachine certs without an operator filter; requires `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX` or `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX`; local temp binary proved no-filter fail-closed and filtered no-cert paths without native crash. Installed-service distribution and AD CS cert provisioning remain separate gates |
| **AG-030** | `platform-agent` | Pending reboot detection | **SOURCE-MERGED + LOCAL PARALLELS PROBE (PR #33; 2026-06-07)** | CBS/Windows Update/PendingFileRenameOperations sinyalleri; local temp probe on HALILKOOLUB735 observed `pendingReboot=true` with CBS + PendingFileRenameOperations sources. Backend ingest/browser acceptance remains separate |
| **AG-031** | `platform-agent` | Endpoint security posture inventory | **SOURCE-MERGED + LOCAL PARALLELS PROBE (PR #34, Codex 019e74b5 4-iter AGREE; 2026-06-07)** | Defender/Firewall/BitLocker read-only; local temp probe observed Defender present, firewall enabled for Domain/Private/Public, BitLocker system drive present but unprotected; recovery key/drive-id/vendor-name sızmaz |
| **AG-032** | `platform-agent` | Local admin group inventory | **SOURCE-MERGED + LOCAL PARALLELS PROBE (PR #35, Codex 019e74d7 5-plan+2-impl AGREE; 2026-06-07)** | Built-in Administrators summary via NetAPI; local temp probe observed local member count 2 and domain member count 0; ZERO raw SID/RID/name on wire |
| **AG-033** | `platform-agent` | Device health snapshot | **SOURCE-MERGED + LOCAL PARALLELS PROBE (PR #36, Codex 019e7500 plan+impl AGREE; 2026-06-07)** | Disk/RAM/uptime/boot time özet; local temp probe observed one fixed disk, 21.4 GB RAM, 22% used memory, 2-day uptime; direct Win32 syscall; no performance counter spam |
| **AG-035** | `platform-agent` | Hardware / device inventory | **MERGED + LIVE (PR #24, HALILKOOLUB735 verified 2026-05-29)** | CPU/RAM/disk/model/BIOS/TPM/network read-only; SRB-AIDENETIMPC binary distribution operator-bound |
| **AG-037** | `platform-agent` | Windows Update / hotfix posture | ✅ **MERGED + LIVE (2026-06-01)** | Hotfix history + pending update + health summary; patch install/reboot tetiklemez. End-to-end LIVE: agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) `2b0f3b5` (WUA COM + PS fallback + service + registry + agent-health) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) `2ac67f11` (V22 5-table) + PR [#355](https://github.com/Halildeu/platform-backend/pull/355) `fb80db67` (omitempty critical follow-up) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) `577a89f2` (HotfixPostureView tab) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168) (digest pins). HALILKOOLUB735 binary upgrade + manual `COLLECT_INVENTORY{includeHotfixPosture:true}` → backend ingest **86 installed + 1 pending** (KB2267602 DEFINITION UNSPECIFIED) → browser smoke testai.acik.com Hotfix Duruşu tab full panel render (NO errors). Cross-AI Codex threads `019e81fe` + `019e822b` + `019e8245`. |
| **AG-038** | `platform-agent` + `platform-backend` + `platform-web` | Agent self-health / connectivity diagnostics | **SOURCE-MERGED + backend LIVE 2026-06-01 + LOCAL FAIL-CLOSED PROBE 2026-06-07** (agent #39 + backend #357/#355 + web #727) | Agent version/config hash + last poll latency + backend DNS/TLS tri-state + flat lastError triad + bounded probeErrors[]; local temp probe emitted config hash but `probeComplete=false` / `BACKEND_HOST_UNRESOLVED` because no service env was present; backend/browser acceptance remains separate |
| **AG-039** | `platform-agent` + `platform-backend` + `platform-web` | Critical services inventory | **SOURCE-MERGED + testai SINGLE-DEVICE BROWSER-SMOKED 2026-06-09 (frontend digest #1185 deployed)** | Agent PR #47 + backend PR #362 + web PR #728: 6-service read-only allowlist (`WinDefend`, `wuauserv`, `BITS`, `EventLog`, `EndpointAgent`, `MpsSvc`) with nullable service state/startup mode and drawer Services tab. Local temp probe observed all six canonical services; `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend`, `wuauserv` running and `BITS` stopped/manual. **testai browser smoke 2026-06-09 (Chrome MCP, HALILKOOLUB735 `d0efb00a`): "Hizmetler" drawer tab renders all 6 services with live agent-probe data — `BITS` `Durduruldu`/`Manuel`, `EndpointAgent` `Çalışıyor`/`Otomatik (gecikmeli)`, scan 08.06 17:54:43 / 2 ms, "Probe sırasında hata kaydedilmedi", console clean.** No service mutation |
| **AG-040** | `platform-agent` + `platform-backend` + `platform-web` | Startup apps / exposure summary | **SOURCE-MERGED + testai SINGLE-DEVICE BROWSER-SMOKED 2026-06-09 (frontend digests #1190/#1189 deployed)** | Agent PR #48 + backend V25 startup-exposure ingest/query + web PR #729 StartupExposure tab. Local temp probe observed `startupAppCount=38` and RDP disabled, then held `probeComplete=false` because task-scheduler names triggered redaction guard entries. Registry/folder/task-scheduler/RDP/firewall summary is read-only and redacted. **testai browser smoke 2026-06-09 (Chrome MCP, HALILKOOLUB735 `d0efb00a`): "Başlangıç + Maruziyet" drawer tab renders live exposure data — startup entries with Aktif/Kaynak (`Kayıt Defteri`, `Görev Zamanlayıcı`), Firewall event-log exposure summary, redaction-guard note for executable-extension/GUID/SID, console clean; minor left-label clipping noted as a cosmetic follow-up.** |
| **BE-022** | `platform-backend` | Device inventory ingest surface | **MERGED + LIVE (PR #322 V13 + PR #324 V14)** | Hardware payload normalize + sanitizer + EndpointHardwareInventoryService idempotent ingest; ALTER payload_hash_sha256 VARCHAR(64) fix |
| **BE-022Q** | `platform-backend` | Device inventory query surface | **MERGED + LIVE (PR #325 / current sha-e3a0369)** | AdminEndpointHardwareInventoryController GET /latest + /history; module:endpoint-admin can_view RBAC; cluster live 2026-05-29 = `sha256:76bacc004f...` (sha-e3a0369, post backend #326 + gitops #1130); BE-022Q deep payload-hash equality SQL surface partial bug (`lower(bytea)`) tracked separately |
| **WEB-013** | `platform-web` | Hardware / device inventory view | **MERGED + LIVE (PR #700 `26e68658`)** | DeviceDetailDrawer Donanım tab + HardwareInventoryView + history accordion + i18n TR+EN + 8 RTL tests |
| **WEB-017** | `platform-web` | Endpoint Enrollment Management UI | **MERGED + LIVE (PR #701 `c0201c08`)** | Enrollment workflow surface |
| **WEB-018** | `platform-web` | Envanteri Şimdi Topla + Donanım dedicated trigger | **MERGED + LIVE (PR #702 `e096837b`)** | COLLECT_INVENTORY payload UI + Donanım trigger |
| **BE-026** | `platform-backend` | Deployment rings / device tags | **SOURCE-MERGED (PR #478)** | V51 rollout ring/device tag foundation + admin rollout metadata surface. Policy fan-out and operator acceptance remain separate gates. |
| **BE-027** | `platform-backend` | Maintenance window / scheduled command | **SOURCE-MERGED (PR #490)** | Install command contract carries `notBefore` + `expiresAt`, maps to `EndpointCommand.visibleAfterAt` / `expiresAt`, fails closed for past/not-after windows, and includes schedule fields in idempotency replay + payload/audit metadata. Full recurring/named maintenance-window policy engine is outside this accepted source slice. |
| **BE-028** | `platform-backend` | Rollout throttle / max concurrency | **SOURCE-MERGED (PR #491)** | Tenant-wide install throttle foundation via `endpoint-admin.commands.install-max-concurrent`; live/operator rollout acceptance remains separate. |
| **BE-029** | `platform-backend` | Approved package bundles | **SOURCE-MERGED (PR #492)** | Approved bundle control-plane primitive + maker-checker/audit; automatic bundle rollout fan-out remains future work. |
| **AG-034** | `platform-agent` | SMB/file actions discovery guardrail | **DEFERRED / 22.8-boundary** | Discovery/tehdit modeli; whitelist + RBAC + audit + dual-control olmadan runtime yok. Runtime file copy / backup / forensic collection 22.8 charter + #1388 governance gate kapsamıdır |

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
- 2026-06-07 local Parallels baseline: `platform-agent` #74 + #75 merged,
  target `endpoint-agent 0.1.4-lab.1` built from merged `origin/main`,
  BE-031/BE-032 release catalog + catalog-bound dispatch path exercised,
  negative trust-field preflight returned HTTP `400`, command
  `0640e361-ccb7-4a7b-8967-27ea992ba7ad` finished `SUCCEEDED`, Windows
  service activated to `0.1.4-lab.1`, activation outcome was `ACTIVATED`,
  serviceRunningVerified/evidencePersisted were true, signed lab binary SHA256
  matched `9CEBCC2022DEE8AC8A466CF22F347B17F9AA26EF4624414EECC3C68A429EE244`,
  and backend heartbeat/audit saw the new version. Evidence:
  `platform-agent` #55 raw evidence comment
  `https://github.com/Halildeu/platform-agent/issues/55#issuecomment-4642413343`;
  #55 accepted sign-off comment
  `https://github.com/Halildeu/platform-agent/issues/55#issuecomment-4642421851`.
- This is local lab acceptance only. The checklist added by PR #75 keeps
  additional machines as `PENDING_BATCH`; trusted signing and domain-wide
  rollout remain separate gates.
- Adjacent mTLS preflight hardening: AG-030P / `platform-agent` PR #77 fixed a
  local Parallels `-auto-enroll -dry-run` certstore crash by requiring an
  explicit cert filter before auto-enroll startup/dry-run and by adding a
  private-key binding precheck. This does not distribute the fix to the
  installed service by itself and does not provision AD CS certificates.

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
- Runtime file copy, backup, offboarding copy veya forensic collection işleri
  Faz 22.8'e taşınır; #1388 governance gate kabul edilmeden açılmaz.
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
8. `platform-agent`: `AG-036` outdated software inventory. **DONE (SOURCE-MERGED — agent PR #38 `a29eef4` + #40 `e64c131` `UpgradeTruncated` fix; backend PR #336 `7f8c1a90` V20 ingest+query); TESTAI LIVE admin JWT surface smoke PASS 2026-06-07 (#1164)**
9. `platform-web`: `WEB-014` compliance / outdated view. **DONE + LIVE (WEB-014A/B/C/D)** — Note: outdated/diff/prohibited surfaces in WEB are a separate WEB-014E gap (compliance/policy/install covered; outdated/diff list view + prohibited alert view pending)
10. `platform-backend`: `BE-024` inventory diff/history + `BE-025` prohibited software detection. **DONE (SOURCE-MERGED — BE-024 PR #334 `d154ac7a` V18 `endpoint_software_inventory_state_history`; BE-025 PR #335 `7bb0340e` V19 `endpoint_prohibited_software_rules`); TESTAI LIVE admin JWT surface smoke PASS 2026-06-07 (#1164): diff/history/outdated/prohibited 4/4 returned 200 JSON**
11. `platform-backend`: `BE-021A` install dry-run / preflight contract. **DONE + LIVE**
12. `platform-backend`: `INSTALL_APPROVED_SOFTWARE` command contract + `BE-021` audit/detection state. **DONE + LIVE**
13. `platform-agent`: `AG-027` 7-Zip install adapter + `AG-027L` exit-code/redacted log capture. **AG-027 DONE (MERGED + LIVE 2026-05-31 #1133 GREEN — winget-list-Session-0 fix landed in PR #41); AG-027L DONE (SOURCE-MERGED 2026-05-29 PM PR #32, binary distributed + service health PASS; LIVE smoke proven 2026-05-31 through the redacted wire path; explicit deep-trace evidence followup pending)**
14. `platform-web`: `WEB-012` approved install UI + `WEB-015` report/export. **WEB-012 ≡ WEB-014D DONE foundation; WEB-015 DONE + TESTAI LIVE 2026-06-07 (#1134): CSV raw export returned 200 via public gateway**
15. `platform-agent`: `AG-030` + `AG-031` + `AG-032` + `AG-033` + `AG-035` posture/health/hardware quick wins. **AG-035 DONE + LIVE; AG-030/031/032/033 SOURCE-MERGED 2026-05-29 (PR #33/#34/#35/#36, all Codex cross-AI AGREE) + LOCAL PARALLELS PROBE 2026-06-07** (`HALILKOOLUB735` temp Windows ARM64 probe observed pending reboot, Defender/Firewall/BitLocker posture, local admin summary and device health; backend ingest/browser acceptance remains separate)
16. `platform-agent`: `AG-037` + `AG-038` + `AG-039` + `AG-040` update/diagnostic/service/exposure quick wins. **AG-037 MERGED + LIVE 2026-06-01** (agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) + [#355](https://github.com/Halildeu/platform-backend/pull/355) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168); HALILKOOLUB735 86 installed + 1 pending real WUA telemetry browser-smoked); **AG-038 SOURCE-MERGED + backend LIVE 2026-06-01 + local fail-closed probe 2026-06-07** (agent PR [#39](https://github.com/Halildeu/platform-agent/pull/39) + backend PR [#357](https://github.com/Halildeu/platform-backend/pull/357)/[#355](https://github.com/Halildeu/platform-backend/pull/355) V23 migration LIVE + web PR [#727](https://github.com/Halildeu/platform-web/pull/727) DiagnosticsView tab; temp probe emitted config hash but no backend connectivity acceptance without service env); **AG-039 SOURCE-MERGED + local Parallels probe 2026-06-07** (six canonical services observed); **AG-040 SOURCE-MERGED + local redaction/fail-closed probe 2026-06-07**; backend/browser acceptance remains separate for AG-039/040.
17. `platform-backend`: `BE-022` device inventory ingest/query. **DONE + LIVE (BE-022 + BE-022Q)**
18. `platform-web`: `WEB-013` hardware/device inventory view. **DONE + LIVE**
19. `platform-agent` + `platform-backend` + `platform-web` + `platform-k8s-gitops`: `AG-028` uninstall. **SOURCE-MERGED + TESTAI LIVE (2026-06-04)** — real 7-Zip uninstall on HALILKOOLUB735 yielded `SUCCEEDED_VERIFIED` + `ABSENT_VERIFIED`; prod remains dark.
20. `platform-agent`: `AG-029` signed update. **MERGED + LOCAL PARALLELS BASELINE 2026-06-07** — PR #74 verifier sharing fix + PR #75 multi-device checklist; accepted #55 local `HALILKOOLUB735` self-update evidence reached `0.1.4-lab.1` through BE-031/BE-032 catalog-bound dispatch with activation, audit and heartbeat evidence. Multi-device/trusted-signing/domain rollout gates pending.
21. `platform-backend`: `BE-026` + `BE-027` + `BE-028` + `BE-029` rollout ring/window/throttle/bundle controls. **SOURCE-MERGED (accepted source sprint)** — BE-026 PR #478, BE-027 PR #490, BE-028 PR #491 and BE-029 PR #492 are merged. Boundary: backend source/control-plane only; image/digest rollout, live testai policy acceptance, AG-029 multi-device acceptance, trusted signing and domain rollout remain separate gates.
22. `platform-agent`: `AG-034` SMB/file action discovery, runtime yok; runtime file-copy/backup/forensic scope 22.8 + #1388 gate'e bağlı. **DEFERRED**

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
6. ~~**AG-030 / AG-031 / AG-032 / AG-033** posture/health quick wins (4 PR)~~ — **SOURCE-MERGED 2026-05-29 + LOCAL PARALLELS PROBE 2026-06-07**: AG-030 PR #33, AG-031 PR #34 (Codex 019e74b5 4-iter), AG-032 PR #35 (Codex 019e74d7 5-plan+2-impl), AG-033 PR #36 (Codex 019e7500 plan+impl). All opt-in, identifier-leak-free, AG-025H lightweight contract intact. Local temp probe observed real HALILKOOLUB735 pending reboot/security/local-admin/device-health values. Remaining: backend ingest (BE) + WEB visualization acceptance
7. ~~**AG-037**~~ **MERGED + LIVE 2026-06-01** (agent PR [#45](https://github.com/Halildeu/platform-agent/pull/45) + backend PR [#354](https://github.com/Halildeu/platform-backend/pull/354) + [#355](https://github.com/Halildeu/platform-backend/pull/355) + web PR [#723](https://github.com/Halildeu/platform-web/pull/723) + gitops PR [#1167](https://github.com/Halildeu/platform-k8s-gitops/pull/1167) + [#1168](https://github.com/Halildeu/platform-k8s-gitops/pull/1168); HALILKOOLUB735 86 installed + 1 pending real WUA telemetry browser-smoked; Codex threads `019e81fe` + `019e822b` + `019e8245`); ~~**AG-038**~~ **SOURCE-MERGED + backend LIVE 2026-06-01 + local fail-closed probe 2026-06-07** (agent PR [#39](https://github.com/Halildeu/platform-agent/pull/39) + backend PR [#357](https://github.com/Halildeu/platform-backend/pull/357)/[#355](https://github.com/Halildeu/platform-backend/pull/355) — V23 migration applied 12:42 UTC, GET /diagnostics/latest LIVE + 404 "no snapshot" until first ingest + web PR [#727](https://github.com/Halildeu/platform-web/pull/727) DiagnosticsView drawer tab with currentData-anchored fail-closed render; Codex thread `019e833d` 3-iter REVISE→REVISE→AGREE absorbing 8 + 4 + 2 must_fix). **AG-039** is SOURCE-MERGED + local Parallels services probe; **AG-040** is SOURCE-MERGED + local redaction/fail-closed probe. Digest/browser smoke remains pending for AG-039/040; AG-041 Credential Guard remains Sprint D.
8. ~~**BE-024** Software inventory diff/history~~ — **DONE + TESTAI LIVE 2026-06-07 (#1164)**.
9. ~~**BE-025** Prohibited software detection~~ — **DONE + TESTAI LIVE 2026-06-07 (#1164)**.
10. ~~**WEB-015** CSV/report export~~ — **DONE + TESTAI LIVE 2026-06-07 (#1134)**.

P2 (rollout controls + uninstall + signed self-update — managed lifecycle):
11. **AG-028** Software uninstall (catalog-managed only) — **testai LIVE 2026-06-04**; prod remains dark.
12. **AG-029** Signed agent self-update (Authenticode + manifest + SHA256/SHA512 + rollback guard; moved from P0 2026-05-29 PM per adversarial review — not 22.5.4 First Install Pilot blocker; lives in §22.5.7 managed lifecycle scope) — **local Parallels baseline proven 2026-06-07** (`HALILKOOLUB735`, command `0640e361-ccb7-4a7b-8967-27ea992ba7ad`, `0.1.0-dev` -> `0.1.4-lab.1`, activation outcome `ACTIVATED`, backend heartbeat/audit matched); **remaining** multi-device batch + trusted signing + rollout acceptance.
13. **BE-026 / BE-027 / BE-028 / BE-029** rollout ring/window/throttle/bundle — SOURCE-MERGED accepted source sprint: BE-026 rings/device tags (#478), BE-027 schedule fields (#490), BE-028 tenant-wide throttle (#491) and BE-029 bundles (#492) merged. Remaining gates are runtime/operator acceptance: image/digest rollout, testai controlled-rollout smoke, AG-029 multi-device batch, trusted signing and domain rollout.

Deferred:
14. **AG-034** SMB/file action discovery (runtime yok; runtime 22.8'e bağlı)

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
