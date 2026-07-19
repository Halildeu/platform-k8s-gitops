# platform-k8s-gitops — Canlı Geçiş Planı

**Repo amacı:** Bu repo `autonomous-orchestrator` platformunun Kubernetes GitOps manifest'lerini tutar. Docker Compose üzerinden k3s cluster'a tam geçiş için **tek doğruluk kaynağıdır**. Bu repo'dan geliştirilen yapı, testler yeşil olduğunda **doğrudan canlıya alınır** — deneysel/atılabilir yapı değildir.

**Son güncelleme:** 2026-04-19 (ADR-0002 Single-Host Dual-Cluster + Faz A-I roadmap reset)

**Faz 22 tamamlama eylem planı (2026-06-26):** [`docs/faz-22-completion-action-plan.md`](./docs/faz-22-completion-action-plan.md) — owner/operator/hukuk **yapılacaklar listesi** + agent yürütme planı + sıra/bağımlılıklar. Canonical makine kapısı: `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (origin/main'den koş) + `docs/runbooks/RB-faz22.6-autonomous-completion-contract.md`.

---

## 0. Mevcut Strateji (ADR-0002 sonrası)

> Bağlam önceliği ve kural çözümü için önce [AGENTS.md](./AGENTS.md), ardından [docs/context-priority-rules.md](./docs/context-priority-rules.md) okunur. Bu dosya roadmap ve done kriteri kaynağıdır; tek başına canlı truth kaynağı değildir.

**Referans ADR:** [`docs/adr/0002-single-host-dual-cluster.md`](./docs/adr/0002-single-host-dual-cluster.md)

Bu repo için güncel ana strateji:

- `platform-k8s-gitops` **tek prod desired-state repo**'dur
- Prod + test **aynı fiziksel host** (staging-sw) üzerinde 2 ayrı `k3d` cluster
- Prod + test **ayrı PG / KC / Vault** instance (full stateful isolation)
- `D32 separate-host` (staging-sw-2 ayrı sunucu) **SUPERSEDED** — forward-extension path olarak açık
- Operasyon `normal / cutover-freeze / rollback-window` mod kontratı ile yürütülür
- Test cluster **default scale-to-zero** (user 2026-04-19); ihtiyaç durumunda açılır

### 0.1 Faz A-I Yol Haritası

| Faz | Amaç | Effort | Ana blocker | Done kriteri | Paralel | Status |
|---|---|---|---|---|---|---|
| **A** Decision Reset | ADR-0002 + D32 supersede + PLAN/README yön | 0.5-1 gün | Yok | ADR-0002 accepted; D32 supersede işaretli; PLAN/README güncel | Tek başına önce | 🟢 |
| **B** Test Authoritative Live | `testai.acik.com` full K8s | 3-5 iş günü | smoke-client, schema immutable image, ESO apply, host-bridge determinism | D29 3 katman (Up+Functional+Zanzibar) kanıtlı | D ile paralel | 🟢 |
| **C** Test Stability Gate | Soak + minimal metrics + blackbox | 5-7 takvim günü | Test cluster minimal metrics + remote_write | Soak penceresinde blocker alert yok | D/E ile overlap | 🟢 |
| **D** Prod Isolation Prep | Ayrı PG/KC/Vault instance | 2-4 iş günü | disk path, backup, unseal, network | Prod stateful seed'li + restore prova edildi | B/C ile paralel | 🟢 |
| **E** Prod Control Plane | Prod monitoring + ArgoCD + legacy obs kapatma | 1-2 iş günü | prod-hub ArgoCD, legacy observability shutdown | Prod infra healthy; legacy compose obs kapalı | D ile yakın paralel | 🟢 |
| **F** Prod Workload Preflight | Immutable artifact + dry-run | 1-2 iş günü | prod secrets, local smoke, imageID match | Prod overlay dry-run temiz; local smoke PASS | C sonuna yakın | 🟢 |
| **G** Atomic Prod Cutover | `ai.acik.com` same-host cutover | 0.5 gün + 72h soak | No-go gate, freeze window, stakeholder sign-off | `ai.acik.com` authoritative smoke PASS | H bekler | 🟢 (T0 2026-04-24) |
| **H** Compose Deploy Decommission | dev repo deploy-backend + warm rollback shutdown | 0.5-1 gün | 72h rollback penceresi | Compose deploy job disabled + warm backend kapalı | G sonrası | 🟢 |
| **I** Day-2 Hardening | Governance ritmi | 3-5 iş günü ilk tur + periyodik | backup drill, rotation, cert, vuln, retention | Ritim işliyor (aylık+çeyreklik review) | D sonrası parçalı | 🟡 ongoing |
| **22** Endpoint Admin / Endpoint Agent | **Non-domain Windows endpoint management primary** (workgroup/standalone/BYOD); `acik.local` IT pilot optional second scope (2026-05-24 user scope decision; ADR-0012-EA "22.2 scope amendment" section): Go agent, backend endpoint-admin-service, web MFE, GitOps runtime governance | Evidence-driven | Backend canonical `main` reconciliation + full D29-EA Secured persona/audit smoke + agent live backend integration + Windows identity inventory + IT EndpointPilot OU + trusted signing | Test runtime Up + basic Functional/fail-closed + Live JWT persona + BE-014A Functional (4 deny audit) acceptance kanıtlı; agent repo/CI/Windows MVP servis-installer-tamper evidence var; prod deferred; BE-016 hash-chain + BE-017 dual-control + BE-011 wire-contract MERGED (source-side, 2026-05-22); **Web runtime acceptance LIVE (2026-05-23): platform-web #654+#656+#657 MERGED + testai deploy LIVE + browser smoke 3 routes 200/503-not-401 + gitops #998 D30 frontend digest re-pin sha-5455b07; platform-web #655 + #653 closed.** **Auth-transport zinciri LIVE end-to-end (2026-05-24): platform-web #658 (`endpointAdminApi` `fetchFn: unwrapRequestFetchFn` — Request-object header drop workaround, notify #652 pattern) + gitops #1007 (D30 frontend digest re-pin sha-4c3df71) MERGED; browser-context verify MFE-driven Platform Admin → devices/audit 403 (FGA fail-closed) + status 200 (auth-only); 401 storm giderildi, auth-transport evidence live.** Windows fresh smoke + BE-011 real agent lifecycle 2026-05-24 resmi-kanıtlandı (gitops PR #1021 `4ecb71dc` + platform-agent PR #10 `402bdc1`); ayrı kapılar: BE-017 formal dual-control (agent-actionable — board #1023), Faz 22.2 IT pilot, trusted signing, EDR allowlist, full IT-owned `acik.local` pilot | Faz 23 ile paralel ama destructive aksiyonlar 22.2+ | 🟡 (2026-05-23 Web runtime acceptance LIVE + 2026-05-22 Plan A/B/C + C.5.persona + BE-014A Functional VERIFIED LIVE: evidence-weighted overall ~82% (2026-05-24 post-handoff block truth-refresh — Windows fresh smoke + BE-011 lifecycle yan-kanıt → resmi-kanıt promote; per handoff §5 P0 #2 alt-not "Faz 22 overall %'sını değiştirmiyor" baseline — sub-track aggregates değişti (22.1 backend ~97%, 22.1 Web ~98%, 22.1 lab ~82% ↑) ama overall recalculation operator/IT-pilot ext-bound ağırlığıyla sınırlı; production-ready/password-reset-ready/domain-wide rollout-ready iddiası DEĞİL — ~~agent-actionable kalan = BE-017~~ ✅ BE-017 DONE 2026-05-24 (PR #1032); agent scope tüketildi, sıradaki adım 22.2.A non-domain primary follow-up runbook (`RB-faz22-non-domain-windows-pilot.md` ayrı PR sonraki tur) + 22.2.B `acik.local` operator-bound; geri kalan operator/IT-pilot/trusted-signing/EDR ext-bound); 22.0 governance/repo split ~95% (PR #944 + #924 Done), 22.1 lab foundation ~80% (PR #7 agent capability fix MERGED + #6 Done + Plan C H1/H2 + #956 + #957 gitops digest pins LIVE + #961 ConfigMap fix), 22.1 backend canonicalization ~97% ⬆️ (BE-016/BE-017/BE-011 MERGED + H1+H2 + BE-014A backend PR #293 MERGED mergeCommit c8f244c4 + gitops PR #965 MERGED mergeCommit 90922f30 digest sha256:fd7a9c54... LIVE + **BE-014A Functional 5/5 HMAC matrix VERIFIED LIVE 2026-05-22T09:52Z**: 4 deny event types ALL EMITTING + durability invariant live-runtime proven on test deployment (prod deferred) + 7 DB audit rows + performed_by_subject forensic correlation), **22.1 Web runtime acceptance ~98% ⬆️ (2026-05-24 auth-transport zinciri LIVE end-to-end: 4 platform-web PR — #654 RTK gateway path fix + testai build enablement MERGED `c5d96916` + #656 `createEndpointAdminApp` race protection MERGED `45fa1db7` + #657 `endpointAdminApi.ts` auth Bearer + localStorage fallback MERGED `5455b076` + **#658 `fetchFn: unwrapRequestFetchFn` Request-object header drop fix MERGED `4c3df712`** — testai deploy `26358855612` SUCCESS + browser smoke MFE-driven Platform Admin 3 route post-#658: devices/audit 403 FGA fail-closed + status 200 auth-only (401 storm giderildi); 2 gitops drift-correction — #998 D30 sha-5455b07 MERGED `5ba3b5e2` + **#1007 D30 sha-4c3df71 MERGED `9202ce28`**; platform-web #655 + #653 closed; gitops #1004 evidence note + #1008 Faz 23 M7 truth-sync MERGED `49aaf9c`/`7c16a2a5`)**, ~~22.2 IT pilot ~10%~~ (DEPRECATED per 2026-05-24 user scope decision — see ADR-0012-EA "22.2 scope amendment"); **22.2.A non-domain primary ~80%** (PR #1021 BE-011 + AG-013 WORKGROUP smoke HALILKOOLUB735 + PR #1032 BE-017 dual-control test cluster fixture + PR #13 CI automation source + **platform-agent PR #17 (`91ef533d`) AG-021/AG-022 identity source-foundation MERGED 2026-05-26** — `internal/identity` package + `dsregcmd`/`Win32_ComputerSystem`/`nltest` probes + LOCAL/DOMAIN/ENTRA/WORKPLACE classification + HALILKOOLUB735 `WORKGROUP`/`LOCAL` read-only evidence, redact pass clean (no JWT/Bearer/password/UPN/full-SID leak); eksik: self-hosted CI run + 2+ standalone/BYOD device + 24-72h soak + **BE-015 admin identity compliance API** + **AG-024 signed distribution / Authenticode** + **BE-019 KVKK boundary enforce**. *Identity classification **source path** artık DONE; **field acceptance** — multi-device + soak + BE-015 admin API + signed binary — operator/agent-extra gates altında pending. #1044 PASS DEĞİL, #1037 unblocked DEĞİL.*); **22.2.B `acik.local` optional ~25%** (Gate 0 evidence PR #1039 + runbook + helper PR #14 MERGED; operator-bound VPN routing + DC + EDR + signing waiting — 22.2.A overall blocker DEĞİL); **Faz 22.2 composite portfolio ~67%** (iki-katmanlı sayım; tek-numara closure dili yasak). Cross-AI peer review chain: 24 Codex thread (019e4c3f → 019e4c81 → 019e4c95 → 019e4caa → 019e4cb6 → 019e4cc2 → 019e4e8d → 019e4eaa → 019e4eb9 → 019e4ed6 → 019e4ee1 → 019e4efb → 019e4f15 → **019e516c (#654)** → **019e5196 (#656)** → **019e538c (#657)** → **019e53ab (gitops #998)** → **019e53b5 (#999)** → **019e53be (#1000)** → **019e5955 (#1004 evidence)** → **019e597d (#658)** → **019e598f (gitops #1007)** → **019e599b (M7 strategic)** → **019e59a0 (gitops #1008 M7 post-impl)**). [2026-05-24 post-handoff block: gitops PR #1021 MERGED `4ecb71dc` + platform-agent PR #10 MERGED `402bdc1` — fresh Parallels Windows 11 (HALILKOOLUB735) live smoke `scripts/test/windows-live.ps1` full pass (install → service RUNNING → tamper SDDL → event log source → read-only local-users 5 user JSON → maintenance token stop + uninstall clean) **AG-013 capability coherence verified live** (`DISABLE_LOCAL_USER`/`ENABLE_LOCAL_USER` correctly absent post #7); BE-011 real agent lifecycle live: device `d0efb00a-…` enrolled + 30s heartbeat poll + `COLLECT_INVENTORY` command `8181f20a-…` QUEUED → deliveredAt → startedAt → SUCCEEDED (~65s) + result payload populated + audit row `b3cf5210-…` inserted. Evidence: `docs/faz-22-evidence/2026-05-24-windows-be011-lifecycle.md` (yan-kanıt → resmi-kanıt promote)] ~~Pending: BE-017 formal dual-control matrix~~ ✅ DONE 2026-05-24 (gitops PR #1032 MERGED `507f57c4` — `LOCK_USER_LOGIN` destructive 5-step smoke test-fixture only). Sıradaki **22.2.A non-domain primary follow-up**: yeni runbook `RB-faz22-non-domain-windows-pilot.md` (2+ standalone/BYOD device + 24-72h soak + identity classification + consent/privacy + signed artifact gates) — ayrı PR sonraki tur. **22.2.B `acik.local` optional ikinci scope** — operator-bound (VPN routing per gitops #1037 Gate 0 BLOCKER + DC reachability + EDR allowlist + trusted signing); 22.2.A primary scope için BLOCKER DEĞİL (2026-05-24 user scope decision; ADR-0012-EA "22.2 scope amendment"). **Production-ready / password-reset-ready / domain-wide rollout-ready iddiası DEĞİL** — single VM / no soak / 1 device baseline. [2026-05-23 No Fake Work düzeltmesi: önceki PR #999 satırında "api-gateway D30 drift (live sha256:6137bb2c ≠ desired sha256:84500b5e)" pending olarak yazılmıştı; gerçekte PR #985 ile zaten kapatılmıştı (overlay desired = live = sha256:6137bb2c), bu satır yanlışlıkla taşınmıştı, follow-up PR ile kaldırıldı.]) **PLUS Faz 22.3 — domain-wide mass deployment scope ADDED 2026-05-26** (ADR-0029 Plan A owner-approved; user explicit "tam otonom devam et"): 9-saatlik AGENTPC2 GPO Scheduled Task pilot fail (cross-subnet block + Scheduled Task pattern unreliable) sonrası 6-layer architecture (machine cert TPM-bound mTLS self-enrollment + AD CS code signing + WiX MSI fixed UpgradeCode + GPO Software Installation Computer-assigned + endpoint-admin-service backend SAN-primary identity + Faz 22.1 agent --auto-enroll); 5→50→800 PC pilot ramp; 22.2.A non-domain primary path **KORUNUR** (22.3 NE 22.2'yi amend NE supersede eder — paralel ayrı channel: 22.3 domain-managed `acik.local` MSI/GPO, 22.2.A workgroup/BYOD self-install); Codex cross-AI peer review chain (provider OpenAI threads `019e665f` iter-1/2/3 absorbed + `019e667f-98a5-7980-8f80-613fc1a1ed82` iter-4/5/6/7 REVISE 12 finding absorbed — xhigh reasoning effort); **22.3 ADR + AD CS preflight slice MERGED**: PR #1078 MERGED `d677511e` 2026-05-26 (ADR-0029) + PR #1080 MERGED `a9fab725` 2026-05-26 (`scripts/faz22-mass-deployment/` AD CS preflight + GPO startup + verify gate + 7-section runbook); **22.3 source-side remaining pending**: backend mTLS `POST /endpoint-enrollments/auto` endpoint (canonical platform-backend PR), agent `--auto-enroll` feature (canonical platform-agent PR), MSI WiX build/AD CS sign/local test (operator-bound #180), GPO Software Installation 5-PC pilot (#181), 50/800 ramp (#182)) |
| **22.5** Software Deployment Quick Wins | Endpoint-Enes agent üzerinden ücretsiz WinGet + Approved Software Catalog tabanlı yazılım inventory/install/uninstall + cihaz posture/health/hardware + compliance/diagnostics hattı. 22.3 domain-wide mass deployment yerine geçmez; agent yüklendikten sonraki yönetim kabiliyetidir. | Evidence-driven | AG-025/AG-026 read-only inventory + WinGet readiness; AG-026A WinGet source/egress readiness; AG-025H lightweight/full software inventory guard; AG-035 hardware/device inventory; BE-020 catalog + provenance/hash/version policy; BE-020I software inventory ingest/query; BE-021A install preflight; BE-023 catalog compliance; AG-036 outdated software; BE-024 inventory diff/history; BE-025 prohibited software detection; BE-022 device inventory ingest/query; AG-027 install + AG-027L redacted logs; BE-021 detection/audit; WEB-011/WEB-012/WEB-013/WEB-014/WEB-015 UI/reporting; AG-030/AG-031/AG-032/AG-033/AG-037/AG-038/AG-039/AG-040 reboot/security/local-admin/health/update/diagnostics; BE-026/BE-027/BE-028/BE-029 rollout ring/window/throttle/bundle controls; AG-034 SMB/file action discovery only | Canonical plan ve runbook eklendi: [`docs/faz-22-software-deployment-plan.md`](./docs/faz-22-software-deployment-plan.md), [`docs/runbooks/RB-faz22-software-deployment-winget.md`](./docs/runbooks/RB-faz22-software-deployment-winget.md). 2026-05-27 3-AI review verdict: REVISE. `platform-agent` PR #20 / `0eff2db` ile AG-025/AG-026 read-only source foundation var; hardware/device inventory AG-035 + BE-022 + WEB-013 olarak planlandı; #1090 ile rakiplerdeki free-first quick-win'ler fazlara ayrıldı: source readiness → compliance/outdated → preflight → controlled install → reporting → rollout controls. Backend catalog/command/audit ve web visibility eksik. Install/uninstall/runtime policy kabiliyeti iddia edilmez. | Faz 22.2/22.3 ile paralel; source işleri ilgili repolarda | 🟡 SOURCE-PARTIAL → ✅ AG-037 LIVE (2026-06-01): AG-037 Windows hotfix posture full-chain LIVE on testai (agent PR #45 + backend PR #354/#355 + web PR #723 + gitops PR #1167/#1168; HALILKOOLUB735 86 installed + 1 pending real WUA telemetry rendered, see `docs/state/current-state.md` AG-037 LIVE delta); AG-030/031/032/033 SOURCE-MERGED (PRs #33/#34/#35/#36 binary distribution operator-bound); AG-035 + WEB-013 MERGED+LIVE 2026-05-29; AG-036 + BE-024 + BE-025 SOURCE-MERGED 2026-05-30 Flyway V18/V19/V20 applied; raw shell yok, katalog dışı package yok, ilk pilot 7-Zip (`7zip.7zip`); AG-038/039/040 diagnostics + AG-041 app-control SOURCE-MERGED + Backend LIVE 2026-06-01; AG-027 install LIVE BE-028 install-audit chain 2026-05-31; **WEB-015 v2-a + v2-b + BE-024c v2-c-pre FULL CHAIN LIVE 2026-06-02** (P2-A "Inventory Change Evidence" sprint): DeviceGrid SCHEMA_VERSION 2 → 3 → 4 bumps yapıldı; 11 yeni grid colId LIVE testai (5 v2-a prohibited_status+decision+findings_count + app_control_wdac_mode+app_id_svc_state, 6 v2-b diagnostics_last_poll_latency_ms+last_error_code+last_error_at + startup_rdp_enabled+windows_firewall_event_log_enabled + services_critical_stopped_count); V27 diff cache foundation migration applied LIVE (endpoint_software_diff_cache + endpoint_outdated_software_diff_cache empty cache tables ready for v2-c-pre-2 write path); 12 PR MERGED bu sprint (backend platform-backend#374/#377/#381 + web platform-web#734/#736/#737 + gitops platform-k8s-gitops#1209/#1210/#1214/#1215/#1216/#1218); 5 deploy chain LIVE testai (pod imageID match + V27 Flyway "Successfully applied 1 migration to schema endpoint_admin_service, now at version v27"); HTTP E2E acceptance kanıt seti (33-key v4 row + CSV 33-col Turkish headers + HALILKOOLUB735 gerçek veri `OK;UNKNOWN;0` prohibited + v2-b cells empty agent telemetry instrument bekleyiş); 71 backend grid + diff cache tests + 255 web vitest; Cross-AI Codex consensus 5 thread/30+ iter chain (019e87aa + 019e8785 + 019e87bc + 019e8823 + 019e88b5); bkz `docs/state/current-state.md` v2-a + v2-b + v2-c-pre LIVE delta entry. **Deferred ayrı sprint agent-actionable**: v2-c-pre-2 write path (DiffCacheService.upsert + ingest hooks + DiffCacheBackfillWorker + Service + admin endpoint + UPSERT idempotency + cache vs on-demand consistency + full sweep PG IT — Codex 019e88b5 iter-5 7-step execution order inline), v2-d grid SCHEMA v5 (9 cache-fed colIds LEFT JOIN cache tables), browser smoke acceptance LIVE PASS 2026-06-02 ~19:55Z (Chrome MCP recovery sonrası testai grid render + 11 v2-a/v2-b headers + HALILKOOLUB735 row real values + CSV export 19-col + console clean — HARD RULE Tarayıcıdan Sonuç Doğrulanmadan: satisfied). SMB/file runtime yok, yalnız discovery/guardrail |
| **22.6** Remote Access Bridge | Agent-initiated outbound remote access / reverse tunnel / session broker hattı. Faz 22.5 command polling yerine geçmez; interaktif ve yüksek yetkili destek oturumları için ayrı güvenlik modeli üretir. | Evidence-driven | Operation catalog (#701); approved-script runner (#702); constrained executor (#208); hardware attestation (#548); attended VIEW_ONLY engineering evidence (#1580); live rendered-overlay bridge digest; immutable release lineage | Canonical plan: [`docs/faz-22-remote-access-bridge-plan.md`](./docs/faz-22-remote-access-bridge-plan.md), [`ADR-0033`](./docs/adr/0033-faz-22-6-remote-access-bridge-broker.md), completion contract [`RB-faz22.6-autonomous-completion-contract.md`](./docs/runbooks/RB-faz22.6-autonomous-completion-contract.md). Broker/policy/audit/recording core remains platform-owned; transport is wrapped; inbound endpoint port is not required. The 2026-06-09 design-only / `#1388`-blocked posture is superseded: GitOps #1388/#1400/#1401/#1402, backend #510/#524 and agent #116 are closed. | Narrow engineering completion is independent from viewer-delivery product acceptance and legal/DPO approval | 🟢 **COMPLETION CONTRACT PASS (2026-07-13)** — canonical `main` run [29284637555](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29284637555) produced `F22_6_COMPLETION=pass`, TPM/VIEW_ONLY engineering/remote-bridge/release-lineage pass and `RELEASE_LINEAGE_WAIVER=not_required reason=no-release-lineage-hygiene`. 🟡 **RESIDUAL TRACKS OPEN** — viewer delivery/fanout/product proof [#2373](https://github.com/Halildeu/platform-k8s-gitops/issues/2373); `GATE_VIEW_ONLY_KVKK=tracked_pending reason=no-kvkk-marker` on closed engineering issue #1580, with legal basis/consent/retention/DPO decision owned by [#2374](https://github.com/Halildeu/platform-k8s-gitops/issues/2374). No recording-enabled, production, broad rollout or 5/50/800-device claim. |
| **22.7** Compliance Gap Mart Layer | Endpoint-admin görünürlük verilerini aggregate karar katmanına çeviren compliance gap mart/read-model sprint'i. | 4-5 PR | Mevcut LIVE snapshot tabloları + field allowlist + stale/freshness semantics | Canonical sprint plan: [`docs/sprint-plan-faz-22-7-compliance-gap-mart.md`](./docs/sprint-plan-faz-22-7-compliance-gap-mart.md); board issue platform-backend #376 CLOSED/completed. 22.7 backup/SMB/file-action fazı olarak yeniden kullanılamaz. | 22.5 visibility zinciri üstüne kurulur | 🟢 COMPLETED authority = #376 |
| **22.8** Endpoint Data Protection & Forensic Collection | Scheduled endpoint backup, offboarding copy ve forensic collection için ayrı hassas veri operasyon fazı. 22.5 AG-034 discovery'den türeyen runtime file-copy işi burada ele alınır. | Evidence-driven | Sensitive Endpoint Ops Governance Gate (#1388); 22.8 charter (#1390); OSS-only build-vs-buy matrix (#1400); backup engine matrix (#1399); backup dry-run manifest (#117); Velociraptor clean-room/legal ADR (#1403) | Canonical plan: [`docs/faz-22-endpoint-data-protection-plan.md`](./docs/faz-22-endpoint-data-protection-plan.md). **Karar:** 22.8A için Kopia primary backup engine adayı, restic fallback/cold archive, BorgBackup watchlist; Duplicati conditional/likely reject; rclone storage transport only. 22.8C için Velociraptor standing server/core embed değil, reference/serverless ops-adapter only; YARA integrate candidate; osquery telemetry reference. İlk güvenli slice dry-run manifest; runtime copy için legal basis, dual-control, chain-of-custody, retention ve storage ACL/encryption/audit şart. | 22.6 ile governance gate paylaşır; 22.5 runtime kapsamı değildir | 🔴 PLANNING / BLOCKED by #1388; OSS decisions Todo (#1400/#1399/#1403) |
| **22.9** Endpoint Security Telemetry / Detection Extension | Endpoint-admin görünürlük hattını osquery/YARA/Sigma/Wazuh değerlendirmesiyle security telemetry/detection karar katmanına genişletme fazı. Endpoint scan/runtime action değildir; önce OSS-only karar ve charter gerekir. | Evidence-driven | OSS-only build-vs-buy matrix (#1400); telemetry/security matrix (#1404); sensitive endpoint ops runtime gate (#1388) | Canonical plan: [`docs/faz-22-security-telemetry-plan.md`](./docs/faz-22-security-telemetry-plan.md). **Karar:** osquery-style query/table modeli reference/light adapter; YARA bounded scanner candidate; Sigma DRL license-gated reference; Wazuh core adoption reject/defer, yalnız future SIEM connector olabilir. Runtime scan/action #1388 kabulü olmadan açılmaz. | 22.5 visibility + 22.8 forensic kararları üstüne kurulur | 🔴 PLANNING / MATRIX TODO (#1404); runtime blocked by #1388 |
| **23** Notification Orchestration Platform | Custom Spring Boot multi-channel notification (email/SMS/in-app/Slack/webhook → v1 Teams/push/Web Push → v2 WhatsApp/Voice) | 14-18 hafta (Charter → Prod cutover) | Faz 22.1.1b III review verdict (23.1+); 23.0 paralel | ADR-0013 ACTIVE + 10 must-have 🟢 + Faz 23.9 prod cutover 72h stable | Faz 22 ile paralel (23.0); 23.1+ sıralı | 🟢 source-side/LIVE + 🟡 acceptance/operator-gated (Session 49+ re-baseline 2026-05-23: 23.0 🟢 + 23.2 🟢 (R2 KVKK CLOSED 2026-05-23 Codex `019e5189` final legal verdict) + 23.3 🟢 infra LIVE + 🟡 functional data seed pending (M4 prod LIVE 2026-05-20 sha-6307428; BL-011 SMS canary preflight discovery 2026-05-25 → prod notify_db boş data state — R28 NEW + BL-028 yeni backlog Codex `019e5e76` iter-2; BL-011 DEFER; R1 NetGSM ⏳ DEFER asset-preserved per kullanıcı kararı 2026-05-23) + 23.4 🟢 (M6a + M6b 6/6 LIVE 2026-05-20 board #758) + 23.5 🟢 source-ready (M5 6/6 LIVE) + 23.6 🟢 (T4.1 LIVE) + 23.9 🟢 FULL CLOSURE Session 49 2026-05-14; 23.1 🟡 (Layer-2 channel-level OpenFGA Faz 23.2 v2 rescope per Codex `019e3c74` verdict B) + 23.7 🟡 (WebPush browser-only LIVE end-to-end 2026-05-23 — RB-webpush §3.10+§3.11 ✅; mobile FCM/APNS Faz 22.2 dep DIŞI) + 23.8 🟡 (T4.3 9/9 source-side closed; FBL mailbox + per-template DB RO operator activation pending); 23.X ⏳ deferred. **10/10 must-have tracked/evidence-backed**: #1-#7/#9 🟢, #8 🟢 source-ready/live, #10 🟢 **mock-receipt mitigated (BL-008 2026-05-24)** — test cluster dual-receipt drill evidence; **real Slack #853 + prod activation #854 operator-external residual** (production-ready claim DEĞİL); canonical status authority [milestones.md](docs/notify/milestones.md) + [sprint-plan.md](docs/notify/sprint-plan.md) + [risk-register.md](docs/notify/risk-register.md) + [feature-matrix.md](docs/notify/feature-matrix.md). Önceki "Session 41 re-baseline 2026-05-09 19:50Z" satırı historical — superseded by Session 49+ truth-sync; agent-actionable Faz 23 scope tükendi, kalan iş operator queue (~~R9 D43 drill~~ → R9 mock-receipt mitigated 2026-05-24; real Slack workspace + prod activation operator-external + Vault canonical patch + FBL mailbox + DB RO role + R24 Biotekno OTP)) |
| **24** Meeting Intelligence / STT Platform | **Bağımsız toplantı zekâsı ürünü** — ERP/CRM ürün bağımlılığı değil; telefon/masaüstü/Teams ses kaynaklarından canlı transkript + konuşmacı ayrımı + özet/karar/aksiyon çıkarımı. STT compute worker (`platform-ai` Python servisleri) + Spring Boot orchestration (`audio-gateway-service` + `meeting-service` + `transcript-service`) + React Native mobile (`platform-mobile`) + `platform-desktop` Electron (Faz 24.13 — board canonical 2026-06-05) + `mfe-meeting` MFE. Faz 23 notify entegre. **Two-server topology (ADR-0031 ACCEPTED, 2026-06-03)**: `platform-ai` ayrı dedicated host'ta; diğer `platform-*` staging-sw'da. | Evidence-driven (14-18 hafta MVP) | ADR-0030 KVKK boundary + ADR-0031 D1-D8 two-server topology + Observability/Audit GOP skeleton + Gateway Contract 1.0 freeze (cross-repo contract drift riski); GPU yokken CPU PoC önce, model kararı WER ölçüm sonrası; cross-server WireGuard + mTLS PKI ZORUNLU; **sektör-standardı ürün gate'leri** G-WER/DER, G-INT, G-CAP, G-COMP, G-LAT/COST, G-OPS + #1615 rollup verifier | Faz 24 source-side LIVE chain + acceptance D29 (Up/Functional/KVKK-safe/Cross-server transit-safe) + 3-AI mutabakat (Claude/Codex/Mavis-MiniMax 2026-06-02 — thread `019e879c` AGREE + Mavis msg `78` AGREE + Codex `019e8c09` ADR-0031 iter-1+iter-2+iter-3 REVISE absorb 2026-06-03 + Codex `019e97bb`+`019e97c3`+`019e97cc`+`019e97d2` plan canonical sync iter-1/2/3/4 REVISE absorb → iter-5 AGREE 2026-06-05) | Faz 22-23 ile paralel; 24.0 charter + ADR-0031 → 24.1 Gateway Contract → 24.2+ STT sıralı; 2026-06-26 itibarıyla recorder OpenFGA selector + edge lifecycle kanıtı accepted, WG-B+ I6 pod-CIDR-to-WireGuard MASQ kanıtı accepted, `platform-ai#188` compute-plane audit gate accepted, `platform-ai#226` GPU cold-load timeout fix Denetim runtime'a uygulanmış durumda, `platform-ai#229` G-INT citation coverage gate ve `platform-ai#230` G-WER/DER denominator threshold hardening merged/main-green; direct-STT default-off mTLS/SNI staging chain #2061/#2062/#2063/#2065 ile hazır, fakat Vault/ESO seed + pre-flag mTLS verifier PASS + flag flip sonrası live transcript e2e, desktop mic/loopback, WG-B+ I3 management audit ve Denetim I7 full prod-gate ayrı kapı. | 🟡 Infrastructure evidence advanced; product-value gates open. 24.0 charter Done 2026-06-03 + 24.1 Gateway 4 PR MERGED + 24.13 Desktop sub-Faz added 2026-06-05: live-stt-service PoC iskelet LIVE (platform-ai PR #1 MERGED `4088d9a` — FastAPI + faster-whisper medium int8 + 22/22 test PASS + Codex `019e877b` AGREE); 3-AI mutabakat plan kapısı `019e879c` AGREE final + Mavis `mvs_c922...` msg `78` AGREE; **ADR-0031 Two-Server Topology ACCEPTED 2026-06-03** (gitops PR #1233 MERGED); **PR-gw-01A/B-core/B3 MERGED** + **PR-gw-01C MERGED** + **PR-stt-04 consumer MERGED**; Aşama-2 staging evidence var. 2026-06-26 current truth: OpenFGA `meeting`/`transcript` selector promoted; recorder consent/session/chunk/finish edge lifecycle smoke accepted; I6 MASQ evidence #1867 Done; Denetim deploy mirror reliability #191 Closed and post-#226 runtime pinned to `HEAD=ORIGIN_MAIN=58728b289d40a7cf9f9d59bc65a796fb895f1b09`; #229/#230 main CI success; I3 operator package lane main'de ama #1864 `Needs Verify`; #198 immediate app-mTLS live-stt preflight PASS after ESET/endpoint allow-log, but meeting-ai 8343 and full I7 prod-gate remain open. `verify_faz24_readiness_rollup.py` artık #1615 için tüm child gate kabul kanıtlarını fail-closed aggregate eder ve tek alt gate PASS'i geniş kabul iddiasına çevirmeyi engeller. Sıradaki agent-doable yol: approved Vault/ESO seed authority + `verify_direct_stt_mtls_enablement_preflight.py` PASS + direct-STT flag flip kanıtı + canonical plan §11 T-A/T-B/T-C/T-D/T-E product tracks; operatör-bound yol: #1864 Denetim authorize evidence + #198 full I7 prod-gate acceptance (source-side #198 operator handoff package mevcut; acceptance yerine geçmez). Canonical plan: [`docs/faz-24-meeting-intelligence-plan.md`](./docs/faz-24-meeting-intelligence-plan.md) §11 + ADR-0030 + ADR-0031 + Project #4 board canonical truth. |

**Faz 24 WG-B+ I3 least-privilege source delta (2026-07-15)**:
Project #2 issue [#2434](https://github.com/Halildeu/platform-k8s-gitops/issues/2434)
`In Progress` altında LocalSystem collector -> sanitize atomik snapshot ->
salt-okunur `svc-denetim-agent` evidence mimarisi ve
`faz24.wg-bplus.i3.audit.v2` verifier adayı hazırlanıyor. Apply/Validate/Rollback
paketi paket-fingerprint'ine bağlı transaction ile ilk state'i ve önceden var
olan managed dosyaları geri alma için saklar; snapshot dizin/dosya ACL'leri, exact
firewall allow semantics, dil-bağımsız w32time sync-type kanıtı, canonical
`svc-denetim-agent@10.99.0.2` hedefi, seçili WireGuard arayüzüne bağlı rota,
TOFU'suz pinned SSH host-key, doğrulama-anı freshness ve redaction
fail-closed'dur. Canonical snapshot yolu ayrıca hash ile bağlanır. PowerShell
transcriptleri reparse-point alt ağaçlarına girmeden en fazla 14 gün ve 1 GiB
ile sınırlıdır. Geniş inbound firewall
çakışmaları paket tarafından otomatik değiştirilmez; ayrı, etkisi incelenmiş ve
rollback'i tanımlı operatör işlemi ister. Restricted, identity-bearing ama
secret-free paket artefaktı bir gün saklanır. Odaklı Python testleri `51/51`,
Windows davranış testi PASS ve tam Faz 24 test paketi `538/538` geçse de canlı
Denetim hostu bu delta ile değiştirilmedi; parent #1864 `Needs Verify` ve altı
Windows kontrolü açık. PR/CI, immutable paket hash'i, explicit firewall etki
kararı, controlled Apply/Validate, rollback drill, yeniden Apply/Validate ve fresh v2
evidence kabulü olmadan I3 veya G-OPS ilerlemiş sayılmaz. Yeni sağlayıcı
istişaresi yalnız ayrı bağlamdaki doğrudan OpenAI Codex CLI ile yapılır:
routine iş `gpt-5.3-codex-spark xhigh`, yüksek-etkili iş `gpt-5.6-sol xhigh`;
ikisi de `read-only` ve `ephemeral` olmak zorundadır. Claude, MiniMax, Cursor,
UI, wrapper veya fallback yeni istişare/acceptance zincirinde kabul edilmez;
eski kayıtlar yalnız tarihsel audit kanıtıdır.

**Faz 24 testai frontend promotion durability delta (2026-07-11)**:
`platform-k8s-gitops#2301` merged at
`ea138e990da71193fc503f9be2bedfc81c409b97` and makes the test frontend
rollout contract `maxSurge=1`, `maxUnavailable=0`,
`progressDeadlineSeconds=300`. The promotion verifier now runs a fail-closed
live+desired ResourceQuota headroom preflight before Argo mutation, treats
post-sync health timeout as an Argo result instead of a kubectl-fallback
condition, and triggers on rollout-strategy fingerprint changes as well as
image pins. Post-merge self-hosted run `29157600538` passed live quota,
Argo `Synced/Healthy`, exact digest, public module and full build-SHA gates.
An independent probe over the actual sync/rollout window observed `45/45`
HTTP 200 with zero non-200 responses. Evidence:
[`docs/faz-24-evidence/2026-07-11-testai-frontend-rollout-headroom.md`](./docs/faz-24-evidence/2026-07-11-testai-frontend-rollout-headroom.md).
This is bounded frontend promotion/availability evidence, not broad Faz 24
product acceptance; live transcript, accuracy, diarization and meeting-output
gates remain separate.

**Faz 24 direct-STT late delta (2026-06-26)**: The older row-level
`platform-backend#768` review/merge/deploy unblocker wording is superseded by
current live truth. `platform-backend#768` merged and was deployed through
`platform-k8s-gitops#2061` with testai `audio-gateway-service`
`sha256:abe1e28cc088008d026534ac6cb0ffdc2d0f9e01d62a50029b256170aac0e6b0`.
`platform-k8s-gitops#2062` added the narrow `audio-gateway` ->
`10.99.0.2/32` TCP/8243 egress path and real-pod evidence no longer times out.
`platform-k8s-gitops#2063` staged durable default-off mTLS/SNI wiring:
`AUDIO_GATEWAY_DIRECT_STT_ENABLED=false`,
`https://live-stt.denetim:8243/transcribe`, hostAlias
`live-stt.denetim -> 10.99.0.2`, `/etc/direct-stt-mtls` mount, and
`transcript:direct-stt-results`. Live staging-sw `k3d-test/platform-test`
rollout is Ready and pod readiness is OK. Remaining guarded path for
`platform-ai#182`: Vault seed authority, ESO mapping for
`direct-stt-ca.crt` / `direct-stt-client.crt` / `direct-stt-client.key` into
the dedicated `audio-gateway-direct-stt-mtls` Secret, metadata-only mTLS
enablement preflight PASS while direct-STT is still false, flag flip, and
`/transcribe` result-stream smoke. Keep the Redis aggregate
`audio-gateway-secrets` out of this cert/key failure domain. This does not
change #198 full I7, desktop mic/loopback, product pilot, or production
readiness gates.
The preflight PASS path now has a source-side collector:
`scripts/faz24/collect_direct_stt_mtls_enablement_preflight.py`, which emits
only metadata/key names and bounded mTLS `/health` status/timing before the
existing verifier runs. The preflight now expects the dedicated
`audio-gateway-direct-stt-mtls` ExternalSecret/Secret, not the Redis aggregate.
A live fail-closed collector run before seed confirms the current #182 blocker
remains missing dedicated ESO/runtime Secret key evidence for the three
direct-STT files.

**Faz 24 direct-STT verifier hardening delta (2026-06-27)**:
`verify_direct_stt_mtls_enablement_preflight.py` and
`verify_direct_stt_e2e_evidence.py` now share the same stricter metadata-only
redaction discipline: camelCase sensitive-key variants, URL-like values,
base64 audio data URIs, PEM/token/raw-output/audio/transcript payloads are
rejected. The e2e verifier additionally requires `tokenIncluded=false`, a Ready
real `audio-gateway` pod, explicit mTLS probe host/port
`live-stt.denetim:8243`, and `directClientToStt=false`. This is source-side
false-acceptance hardening only; #182 still requires approved seed, preflight
PASS, flag flip, fresh `/transcribe` result-stream evidence, same-session audit
correlation, and no raw-audio persistence proof.

**Faz 24 direct-STT operator handoff package delta (2026-06-27)**:
`build-direct-stt-operator-handoff.py` plus workflow
`faz24-direct-stt-operator-handoff.yml` now package the remaining #182/#1615
runtime sequence as a metadata-only operator artifact (`README.md` + manifest +
`SHA256SUMS`). It orders credential seed -> preflight PASS -> reviewed flag flip
-> e2e PASS -> reviewer acceptance. Boundary: no Vault read/write, no
Kubernetes mutation, no Denetim PC touch, no direct-STT enablement, no
`/transcribe`, no raw audio, and no #182/#1615 status advance.

**Faz 24 external recorder operator handoff package delta (2026-06-27)**:
`build-external-recorder-operator-handoff.py` plus workflow
`faz24-external-recorder-operator-handoff.yml` now package the remaining
external meeting-admin + recorder lifecycle sequence as a metadata-only
operator artifact (`README.md` + manifest + `SHA256SUMS`). It orders approved
short-lived `platform-desktop` token file -> token-contract PASS -> external
recorder smoke PASS -> verifier PASS -> G-CAP aggregate when enough verifier
summaries exist. Boundary: no token mint/read, no testai connection, no
Keycloak/Kubernetes/Vault mutation, no smoke run, no audio send, and no #1615
status advance.

**Faz 24 external recorder evidence hardening delta (2026-06-27)**:
`run_external_recorder_smoke.py` and
`verify_external_recorder_smoke_evidence.py` now align with the direct-STT and
desktop capture metadata-only standard. The runner omits sensitive response
fields, redacts URL-like/base64-audio values, no longer writes top-level
`baseUrl`, and rejects unsafe `sessionId` before lifecycle path construction.
The verifier rejects camelCase sensitive keys, destination/callback/internal/
webhook/STT/transcribe URL leakage, raw audio/transcript/request/response
payloads, packet captures, unsafe `sessionId`, and direct-STT/direct-client/
compute-plane/production overclaims. Token-contract `issuer` remains the only
URL-shaped value allowed in the external-recorder evidence envelope. Boundary:
source-side false-acceptance hardening only; live external meeting-admin smoke
still requires an approved short-lived `platform-desktop` token, runner PASS,
verifier PASS, and reviewer acceptance.

**Faz 24 KVKK engineering/legal separation delta (2026-06-27)**:
`ADR-0030` now binds KVKK/VERBIS/hukuk owner acceptance as a parallel
owner/legal track, not a Faz 24 engineering completion blocker after owner
notification is recorded. Engineering G-COMP proceeds with fail-closed
parametric controls: retention/deletion durations are owner-supplied config,
unset durable storage refuses to store, consent default is required, deletion
pipeline default is enabled, and legal/production overclaims are forbidden.
Legal acceptance, VERBIS güncelliği or production legal go still require
owner/legal artifact; agent/CI/PR must not claim them.

**Faz 24 G-COMP retention provenance delta (2026-06-27)**:
`scripts/faz24/verify_gcomp_compliance_gate_evidence.py` now treats effective
retention duration values as optional owner-supplied parameters with
machine-checkable provenance. Missing owner values remain non-blocking only
when `retentionDefaultsFailClosed=true`; if `retentionParameters` supplies
effective day values, the envelope must include bounded `ownerDecisionRef`,
`appliedAsConfig=true`, `hardcodedInCode=false`, and positive bounded day
values. This is verifier/runbook hardening only; no owner duration value,
legal acceptance, production lifecycle/deletion proof, or G-COMP acceptance is
claimed.

**Faz 24 desktop capture gate delta (2026-06-27)**:
`platform-k8s-gitops` now carries a metadata-only desktop mic+loopback evidence
verifier and runbook:
`scripts/faz24/verify_desktop_capture_evidence.py` and
`docs/runbooks/RB-faz24-desktop-capture-evidence.md`. The verifier accepts only
real `platform-desktop` smoke metadata proving both microphone and loopback
sources, visible active indicator, consent capture, exact public
`audio-gateway` lifecycle ordering, and matching upload digests. It rejects raw
audio/base64 audio, transcript text, JWT/Bearer/Authorization material,
destination URLs, direct client-to-STT, direct-STT transcript, compute-plane
audit, and production-readiness claims. Boundary: source/runbook package only;
live desktop smoke PASS, direct-STT e2e, aggregate G-CAP reliability, and
product readiness remain separate gates.

**Faz 24 desktop capture operator handoff package delta (2026-06-27)**:
`build-desktop-capture-operator-handoff.py` plus workflow
`faz24-desktop-capture-operator-handoff.yml` now package the remaining real
`platform-desktop` mic+loopback capture sequence as a metadata-only operator
artifact (`README.md` + manifest + `SHA256SUMS`). It orders real desktop run
-> redacted evidence review -> desktop verifier PASS -> G-CAP aggregate when
enough verifier summaries exist. Boundary: no desktop app execution, no token
read, no testai connection, no Kubernetes/Vault mutation, no audio send, and
no #1615 status advance.

**Faz 24 product-gate operator handoff package delta (2026-06-27)**:
`build-product-gate-operator-handoff.py` plus workflow
`faz24-product-gate-operator-handoff.yml` now package the remaining
G-CAP/G-OPS/G-COMP evidence sequence as a metadata-only operator artifact
(`README.md` + manifest + `SHA256SUMS`). It orders redacted evidence selection
-> G-CAP aggregate verifier and ingest wrapper -> G-OPS verifier and ingest
-> G-COMP verifier and ingest -> reviewer acceptance. Existing
external-recorder and desktop handoff G-CAP ingest commands now submit a
`{"reports":[...]}` wrapper built from verifier summaries, not the aggregate
verifier output. Boundary: no live evidence collection, no pilot run, no
Kubernetes/Vault/firewall/legal mutation, no evidence ingest, no legal go, and
no #1615 status advance. KVKK/VERBIS owner legal acceptance remains parallel
and is not an engineering blocker after owner notification.

**Faz 24 G-CAP desktop aggregation delta (2026-06-27)**:
`scripts/faz24/verify_gcap_capture_gate_evidence.py` now accepts both redacted
external recorder verifier summaries and redacted desktop capture verifier
summaries: `faz24.externalRecorderSmokeVerifier.v1` and
`faz24.desktopCaptureEvidenceVerifier.v1`. Raw recorder smoke envelopes and raw
desktop capture envelopes are still rejected. The aggregate output reports
external vs desktop attempt counts, keeps the same threshold model
(`min-attempts`, distinct meeting/session coverage, success/retry/failure rate),
and preserves the no direct-STT / no direct client-to-STT / no direct-STT
transcript / no compute-plane / no production-readiness boundary. External
recorder summaries must be post-hardening `verify_external_recorder_smoke`
outputs with `directClientToStt=false`, `directSttTranscriptProven=false`, and
matching passed boundary checks; stale pre-hardening summaries do not satisfy
G-CAP. This enables real desktop smoke PASS summaries to contribute to G-CAP
reliability evidence, but a single desktop PASS is still only one attempt and
does not close live aggregate G-CAP.

**Faz 24 #161/#162 product-gate hardening delta (2026-06-26)**:
`platform-ai#229` merged as `b4f86b1c8ae9e77ae41846eaf834cc2ea0fa5b50`;
main CI run `28260265821` succeeded across repo-gates and all service-test
lanes. It requires G-INT citation coverage and verified-summary evidence.
`platform-ai#230` merged as `87b3f22022602f9fa853371511e08b0fada82550`;
main CI run `28260320293` succeeded across repo-gates and all service-test
lanes. It requires G-WER/DER denominator thresholds
(`minWerSamples`, `minDerSamples`, `minWerRefWords`). Boundary remains
explicit: these are source-side false-acceptance guards, not real pilot WER/DER,
real pilot G-INT, direct-STT e2e, model/backend selection, LLM enablement, or
production readiness.

**Faz 24 live delta (2026-06-26 + 2026-06-27 source cleanup)**: PR-2 recorder authorization source/runtime
chain is now recorded: `platform-backend#761` added OpenFGA
`meeting#can_record`, the test selector is `01KW0EJTM60YGZTEKNGS7PDPNP`,
`platform-backend#765` added non-admin
`GET /api/v1/meetings/{id}/recording-access`, and
`platform-k8s-gitops#2038` plus deploy run `28206874588` carried the
`audio-gateway-service` / `meeting-service` digest pins through testai
readiness/stability. Later `platform-backend#767` merged source/test cleanup
for the temporary admin GET-by-id relaxation. Boundary remains explicit:
tokened object-level matrix after image rollout, `platform-backend#716`,
`platform-ai#198` full I7 prod-gate, `platform-ai#182`, desktop mic/loopback,
product pilot gates, and production readiness are separate gates. `#198`
immediate Denetim 8243 app-mTLS preflight now has refreshed PASS evidence after
operator ESET/endpoint allow-log completion: staging-sw route
`10.99.0.2 dev wg0 src 10.99.0.1`, TCP/8243 reachable, valid client cert
`/health` HTTP 200, no-client `certificate required` fail-closed, and
wrong-client `unknown ca` fail-closed. Full I7 still needs meeting-ai 8343
(current staging-sw probe timed out), Vault PKI rotation/secret delivery,
request audit, plaintext-bypass closure, failure drill, and reviewer/operator
acceptance.
`platform-backend#716` audience/capability enforcement is also advanced on the
GitOps side: the test desired-state enforce booleans move to `true` and the
test Deployment carries a pod-template rollout marker so the ConfigMap envFrom
change is actually consumed by the running pod.
`docs/runbooks/RB-faz24-audio-gateway-jwt-enforcement.md` and
`scripts/faz24/verify_audio_gateway_authz_enforce_evidence.py` keep live
acceptance bounded to token-drain/maintenance-window proof, pod process-env
rollout proof, the no-token/wrong-audience/missing-role/valid-recorder matrix
PASS and reviewer/operator acceptance.

**Faz 24 #191/#226 Denetim deploy mirror/runtime delta (2026-06-26)**:
`platform-ai#216`-`#220` closed the Denetim deploy-clone drift/update-script
reliability gap with PowerShell 5.1-safe `update.ps1` and `drift-guard.ps1`
hardening. After `platform-ai#226` approval/merge, Denetim runtime was updated
over SSH-over-WG: deploy clone pinned to
`HEAD=ORIGIN_MAIN=58728b289d40a7cf9f9d59bc65a796fb895f1b09`, tracked tree is
clean, `platform-ai-live-stt` / `platform-ai-meeting-ai` scheduled tasks are
running, `STT_REQUEST_TIMEOUT = "180"` is present in `start-live-stt.ps1`,
`update.ps1` warmup cap is `--max-time 240`, live-stt local health is `ok`
on `cuda/float16`, and log tail contains `Transcribe success`. Boundary
remains explicit: this applies the #226 WorkerTimeoutError source/runtime
slice only. It does not merge/deploy `platform-backend#768`, produce
`DIRECT_STT_TRANSCRIPT_RESULT`, satisfy `platform-ai#182`, or change production
readiness.

**Faz 24 #162/#227 G-INT sample metadata delta (2026-06-26)**:
`platform-ai#227` merged after `zeynep-serban` approval as
`7904dc915c985454ab39a02d169320e757c8ed85`; main CI run `28241477589`
completed `success` across repo-gates and all platform-ai service-test lanes.
This binds G-INT pilot evidence to `sample_manifest_hash`,
`sample_count_hash`, positive integer `n_samples`, `eval_set_hash`, and
`prompt_hash`, preventing hand-edited sample counts from silently satisfying
the source-side gate. Boundary remains explicit: this is source-side G-INT
evidence-contract hardening only; it does not provide real pilot transcript or
audio evidence, does not enable an LLM provider, does not satisfy
`platform-ai#162` acceptance, `platform-ai#182`, or any production gate.

**Faz 24 #156 retention delta (2026-06-26)**: DB cleanup runtime evidence
advanced in `k3d-test`: transient smoke Jobs derived from the deployed
`meeting-service` and `transcript-service` images deleted expired synthetic
meeting action/decision, transcript segment, and KVKK access-audit rows, then
wrote `metadata-only` destruction audit rows for `db.meeting-intelligence`,
`db.transcript-records`, and `db.kvkk-access-log`. Evidence is recorded in
`docs/faz-24-evidence/2026-06-26-retention-runtime-smoke.md`. `platform-ai#211`
tightened the source-side retention gate so MinIO lifecycle cannot be accepted
from source script or issue-comment evidence alone; `platform-ai#212` then added
metadata-only test MinIO lifecycle runtime export evidence for `meeting-audio`
7d, `transcripts` 365d, and `audit-archive` 2557d. Current snapshot remains
historical and superseded by the 2026-06-27 KVKK engineering/legal separation
rule: VERBIS/legal owner acceptance is a parallel legal track, not an
engineering blocker. Boundary remains: this is test DB cleanup behavior plus
test MinIO metadata-only lifecycle evidence only; #156 and G-COMP still need
production lifecycle/deletion proof, owner notification evidence, fail-closed
parametric controls, and broader compliance evidence before engineering
pass/readiness language is valid. Legal go/readiness remains owner/legal-gated.

**Faz 24 #162 Ask-AI hardening delta (2026-06-26)**:
`platform-ai#207` merged source-side meeting-ai `/ask` protection: transcript
and question are redacted before real LLM prompt construction, residual PII
returns `422` before any LLM call, and unsupported cloud LLM backends return
`501` instead of silently producing mock output. Boundary remains explicit: this
does not produce real pilot G-INT evidence, does not enable a cloud LLM/API, does
not mutate runtime, and does not change production readiness.

**Faz 24 #162 action-owner grounding delta (2026-06-26)**:
`platform-ai#208` merged source-side meeting-ai action attribution hardening:
`action_items[].owner` is accepted only when it appears in the same cited source
sentence as the grounded action text. Unsupported owner attribution is withheld
from the user-visible assignee field (`owner=null`) and recorded as
`rejected_claims[].kind=action_owner`. Boundary remains explicit: this is G-INT
precision hardening only; it does not provide real pilot G-INT evidence, enable a
cloud LLM/API, mutate runtime, process raw audio, or change production readiness.

**Faz 24 #162 Ask-AI unsupported-answer withholding delta (2026-06-26)**:
`platform-ai#209` merged source-side `/ask` hallucination exposure hardening:
empty/no-info/ungrounded generated answers now return fixed `Metinde bu bilgi
yok.` instead of returning unsupported generated prose merely with
`grounded=false`. The ungrounded citation does not carry the unsupported answer
claim. Boundary remains explicit: this is G-INT source hardening only; it does
not provide real pilot G-INT evidence, enable a cloud LLM/API, mutate runtime,
process raw audio, satisfy #198/#188/#182, or change production readiness.

**Faz 24 #162 summary exposure guard delta (2026-06-26)**: `platform-ai#213`
merged source-side meeting-ai summary hardening. `AnalyzeResponse` is now
`schema_version=3-adr0043`; summary prose is filtered through the transcript-span
citation guard before user exposure, unsupported summary prose is withheld into
`rejected_claims[].kind=summary`, fully withheld summaries return an empty data
string with `summary_grounding_status=withheld`, and `ungrounded_count` remains
scoped to decision/action rejection count. Boundary remains explicit: this is
G-INT hallucination-exposure hardening only; it does not provide real pilot G-INT
evidence, enable a cloud LLM/API, mutate runtime, process raw audio, satisfy
#198/#188/#182, or change production readiness.

**Faz 24 #162 action due-date attribution delta (2026-06-26)**:
`platform-ai#214` merged source-side meeting-ai action due-date hardening.
`AnalyzeResponse` is now `schema_version=4-adr0043`; `action_items[].due_date`
is accepted only when the due-date phrase is present in the same cited source
sentence as the grounded action text. Unsupported, reformatted, or normalized
due dates are withheld from the user-visible action metadata (`due_date=null`)
and recorded as `rejected_claims[].kind=action_due_date`. Boundary remains
explicit: this is G-INT metadata precision hardening only; it does not provide
real pilot G-INT evidence, enable a cloud LLM/API, mutate runtime, process raw
audio, satisfy #198/#188/#182, or change production readiness.

**Faz 24 #162 fact-fusion grounding delta (2026-06-26)**:
`platform-ai#215` merged source-side meeting-ai fact-fusion / single-source
materiality hardening. `AnalyzeResponse` is now `schema_version=5-adr0043`;
default citation grounding requires high-precision single-source material
coverage, and fused decisions/actions/summary sentences that mix supported prose
with unsupported facts outside the cited transcript sentence are withheld. `/ask`
also replaces fused unsupported generated prose with the fixed
`Metinde bu bilgi yok.` answer instead of exposing it with `grounded=false`.
Boundary remains explicit: this is G-INT hallucination-exposure hardening only;
it does not provide real pilot G-INT evidence, enable a cloud LLM/API, mutate
runtime, process raw audio, satisfy #198/#188/#182, or change production
readiness.

**Faz 24 #162 strict materiality delta (2026-06-26)**:
`platform-ai#221` tightened the `#215` materiality guard. Unsupported
content-token allowance for shippable meeting-ai claims is now zero, so a short
unsupported business fact such as `fabrika açtı` cannot ride along inside a long
grounded decision/answer merely because overall overlap remains high.
Deterministic mock `/ask` retrieval is separated from acceptance gating through
`best_matching_sentence()`, but the returned answer still passes through
`ground_claim()` before user exposure. Boundary remains explicit: this is
source-side G-INT precision hardening only; it does not provide real pilot G-INT
evidence, enable a cloud LLM/API, mutate runtime, process raw audio, satisfy
#198/#188/#182, or change production readiness.

**Faz 24 #162 attribution phrase-boundary delta (2026-06-26)**:
`platform-ai#222` tightened meeting-ai action metadata attribution matching.
Copied `action_items[].owner` and `action_items[].due_date` phrases now match on
word/phrase boundaries rather than raw substrings inside unrelated words. This
blocks false-positive attribution cases such as owner `Can` matching `canlı`,
owner `IT` matching `kritik`, and due date `salı` matching `Salıverme`, while
preserving the existing token-subset fallback for legitimate multi-word
attribution. Boundary remains explicit: this is source-side G-INT precision
hardening only; it does not provide real pilot G-INT evidence, enable a cloud
LLM/API, mutate runtime, process raw audio, satisfy #198/#188/#182, or change
production readiness.

**Faz 24 #161 diarization decision-gate delta (2026-06-26)**:
`platform-ai#210` merged source-side diarization backend decision gating:
metadata-only candidate rows can select a backend only with explicit DER, RTF,
latency, VRAM, and sample thresholds, approved pilot evidence, approved
license/deployment metadata, `sha256:<64 hex>` evidence hash, and explicit
non-biometric posture (`voiceprint_enabled=false`,
`biometric_processing=false`, `speaker_identity_mapping=false`). Current
synthetic diarization evidence remains `blocked`; hard policy violations return
`fail`. Boundary remains explicit: this does not produce real pilot DER, select
a diarization backend/model, process real audio, enable voiceprint/biometric
identity, mutate runtime, satisfy #198/#188/#182, or change production
readiness.

**Faz 24 live delta (2026-06-25)**: `platform-ai#187` source/deploy scope is
accepted with `platform-backend#756` (`8c269ccf...`), `platform-k8s-gitops#2015`
(`a9b19c9f...`), and deploy run `28176231063` proving 13-service digest-pin
rollout, readiness, and stability coverage for `meeting-service`,
`transcript-service`, and `audit-event-consumer-service`. This removes the
source/deploy transcript-routing gap, but it does not enable direct-STT runtime
flags, send raw audio, or prove `/transcribe` e2e. `platform-ai#198` remains
the immediate operator/security gate for Denetim source `10.99.0.1`,
destination `10.99.0.2`, `TCP/8243`, program `C:\caddy\caddy.exe` at the
ESET/ERA/central WFP policy layer; after
that live-stt-preflight passes, `platform-ai#188` same-session
`CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit smoke remains the next runtime proof.

**Faz 24 product-gate delta (2026-06-25)**: `platform-ai#199` / `#200` added
metadata-only G-WER/DER and G-INT acceptance gates, `platform-ai#201` added the
#156 retention-readiness gate, `platform-ai#202` closed the Redis
control-plane wording/runtime gap, `platform-ai#203` recorded the
recording/archive boundary as live-path RED / future opt-in only, and
`platform-ai#204` added the metadata-only G-LAT/COST gate.
`platform-k8s-gitops` now also carries the metadata-only G-CAP aggregate
capture gate verifier
(`scripts/faz24/verify_gcap_capture_gate_evidence.py`) for redacted external
recorder and desktop capture verifier summaries. `platform-k8s-gitops` also
carries the metadata-only G-OPS operability gate verifier
(`scripts/faz24/verify_gops_operability_gate_evidence.py`) for on-prem
install/upgrade/backup/restore/rollback/secret-delivery/observability
evidence. This slice adds the metadata-only G-COMP aggregate compliance gate
verifier (`scripts/faz24/verify_gcomp_compliance_gate_evidence.py`) for
redacted consent/retention/legal-hold/access-audit/deletion-export/KVKK-VERBIS
evidence, plus `.github/workflows/faz24-product-gate-evidence-ingest.yml` and
`docs/runbooks/RB-faz24-product-gate-evidence-ingest.md` as a shared
no-mutation ingest path for G-CAP/G-OPS/G-COMP evidence artifacts. This
advances sector-standard quality/compliance governance, but
does not provide real pilot WER/DER, real pilot G-INT, pilot G-LAT/COST, live
aggregate G-CAP evidence, live G-COMP compliance evidence, live G-OPS on-prem
evidence, VERBIS/DB cleanup acceptance, direct-STT runtime, raw-audio transit,
or production readiness.

**Faz 22.5 AG-029 delta (2026-06-07)**: AG-029 is no longer only a
TODO/draft item. `platform-agent` #74 and #75 are merged, and a local
Parallels Windows 11 post-merge self-update baseline is proven on
HALILKOOLUB735 (`0.1.2-lab.2` -> `0.1.3-lab.1`, command
`5c6fe05c-4ce6-4452-9abc-8dda07b6cdb6` `SUCCEEDED`, backend heartbeat +
audit matched). This does not claim multi-device acceptance, trusted
production signing, domain-wide rollout or prod enablement; those remain
separate Faz 22.3 / 22.5.8 gates.

**Faz 22.3 AG-030P delta (2026-06-07)**: `platform-agent` #77 is merged after
local Parallels no-crash proof for `endpoint-agent.exe -auto-enroll -dry-run`.
The auto-enroll preflight now requires an explicit cert filter
(`ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX` or
`ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX`) and replaces broad
certstore scan crashes with fail-closed diagnostics. This is mTLS preflight
hardening only; AD CS provisioning, installed-service distribution,
multi-device batch acceptance and domain-wide rollout remain separate gates.

**Faz 22.2.A #12 delta (2026-06-07)**: the Parallels Windows 11 CI rehearsal
is no longer terminal-only evidence. `platform-agent` #78 is merged and
workflow_dispatch run `27081667910` passed on an ephemeral self-hosted macOS
runner against `HALILKOOLUB735` (`PartOfDomain=false`, A1 workgroup). Evidence
artifact `parallels-w11-ci-evidence-27081667910` proves build/package +
temporary Windows service smoke + secret scans. This does not claim
`acik.local` pilot, BE-011 fresh command ids, multi-device soak, trusted
production signing, password-reset readiness or domain-wide rollout.

**Gerçekçi ufuk:**
- `testai.acik.com` full K8s: **1.5-2 hafta** (7-10 iş günü)
- `ai.acik.com` prod cutover: **3-4 hafta**

### 0.2 Operational Mode Contract (ADR-0002 §5)

#### `normal`
- Prod workload + stateful + edge + monitoring aktif
- Test **default scale-to-zero** (user direktif); ihtiyaç durumunda açık
- Runner concurrency sınırlı (1)
- **Yasak:** shared stateful, legacy compose observability paralel truth

#### `cutover-freeze`
- Prod cutover öncesi değişkenlik minimum
- Test minimal (sadece health/synthetic)
- Runner throttled (CPU %50)
- **Yasak:** test full workload, yeni feature deploy, schema değişikliği, legacy obs

#### `rollback-window`
- Atomic cutover sonrası 72h
- Prod live + warm compose backend standby
- Test scale-to-zero veya minimal
- Runner pause/throttle (CPU %25)
- **Yasak:** test full, prod stateful migration, monitoring stack değişikliği

### 0.3 Mode Transitions
- `normal → cutover-freeze`: cutover kararı + preflight PASS
- `cutover-freeze → rollback-window`: T+15m go gate PASS (runbook §8)
- `rollback-window → normal`: T+72h stabil + warm compose shutdown
- `any → emergency-rollback`:
  - Edge 5xx `> 1%` / 15 dk
  - Gateway p95 `> 2s` / 10 dk
  - Authz synthetic fail ardışık 3 kez
  - Kritik fonksiyonel bozulma

### 0.4 Yasak Kombinasyonlar
- `rollback-window` + `test full workload`
- `rollback-window` + `runner full concurrency`
- `cutover-freeze` + `legacy compose observability active`
- `prod live` + `shared PG/KC/Vault`
- `prod live` + `moving tag main-stable` (D30 ihlal)
- `prod live` + `belirsiz rollback kapsamı`

### 0.5 Kritik 3 Blocker

1. **Test authoritative-live zinciri**
   - smoke-client Keycloak confidential client seed
   - schema-service immutable image (dev repo build gap)
   - ESO pull secret (ghcr-pull dockerconfigjson)
   - host-bridge determinism (compose IP stability)

2. **Prod stateful isolation**
   - Ayrı PG/KC/Vault instance (`platform-{pg,kc,vault}-{prod,test}`)
   - Bind-mount disk path (`/srv/platform/stateful/{prod,test}/...`)
   - Backup + unseal + seed flow
   - Network kontrat (platform-prod-net izolasyon)

3. **Same-host kapasite disiplini (400 GB disk ADR-0002 §7.1)**
   - Runner throttle (cutover/rollback'te CPU %50/%25)
   - Legacy observability kapanışı (prod live ÖNCE)
   - Rollback-window kapsamı dar tutma

### 0.5.1 Faz 22.6.x Remote Response Terminal Reference

Remote Response Terminal / Break-Glass Response Shell ürünleştirme hattı Faz
22.6 parent acceptance'ın devamı değil, ayrı 22.6.x productization lane'idir.
Kanonik detay ve no-go kapıları:

- `docs/faz-22-software-deployment-plan.md` §0.7
- `docs/runbooks/RB-faz22.6-remote-response-terminal.md`
- board gate `platform-k8s-gitops#1693`
- implementation issues: `platform-backend#701`, `platform-backend#702`,
  `platform-agent#208`, `platform-web#820`

Boundary: `platform-backend#510` closed staging parent acceptance proves the
outbound mTLS product path, not raw unrestricted shell, broad remote support,
signed MSI/GPO rollout, 5/50/800-device rollout, or true TPM/device-key
attestation.

### 0.6 Faz-Eski Mapping

| Eski | Yeni karşılık |
|---|---|
| `S0/S1` | Faz B ağırlıklı |
| `S2` | Faz B + D + E |
| `S3` | Faz C |
| `S4` | Faz F + G + H |
| `D32 separate-host` | **SUPERSEDED by ADR-0002** (historical path, forward-extension) |

### 0.7 Referans Dokümanlar
- `AGENTS.md` (repo-geneli giriş yüzeyi ve HARD RULE)
- `docs/context-priority-rules.md` (otorite zinciri, repo sınırı, testten proda promotion semantiği)
- `docs/adr/0002-single-host-dual-cluster.md` (ana ADR)
- `docs/state/current-state.md` (canlı durum ve blocker truth)
- `docs/prod-cutover-runbook-v2.md` (atomic cutover step-by-step)
- `docs/day-2-governance.md` (backup/rotation/cert/vuln/retention)
- `docs/S1-S2-acceptance-smoke-runbook.md` (D29 3 katman kanıt)
- `docs/semantic-architecture.md` (runtime + promotion semantiği)
- `docs/adr/0013-notification-orchestration.md` (Faz 23 ana ADR — DRAFT)
- `docs/notify/event-contract.md` (Faz 23 notification intent contract spec)
- `docs/notify/feature-matrix.md` (Faz 23 16 kategori × tier × özellik canlı tracker, D45 ile 11 → 16)
- `docs/notify/must-have-checklist.md` (Faz 23 10 must-have çizgisi)
- `docs/runbooks/RB-faz-23-charter.md` (Faz 23 sub-faz roadmap)
- Eski: `docs/D32-bootstrap-runbook.md` (historical, SUPERSEDED)
- Eski: `docs/prod-cutover-smoke-runbook.md` (v1, historical)

---

## 0.8 Canlı Durum Kaynağı

Bu dosya hedef roadmap ve operasyon kontratı içindir. Canlı durum, blocker ve optimism temizliği için otoriter kaynak:

- `AGENTS.md` + `docs/context-priority-rules.md` (yorumlama/öncelik kuralları)
- `docs/state/current-state.md`

Eski `S0-S4` seviye snapshot'ı ve oturum-özel sıra listeleri historical bağlamdır; aktif karar veya current truth kaynağı olarak kullanılmamalıdır.

---

## 1. Kilitli Kararlar (FINAL)

| # | Karar | Değer |
|---|---|---|
| D1 | Deployment hedefi | staging-sw üzerinde aynı hostta iki ayrı `k3d` cluster: `prod` + `test`. Bu karar HA/DR değil, **izolasyon** kararıdır |
| D2 | Namespace stratejisi | **Cluster-bazlı**. Prod cluster: `platform-prod`, `ingress-nginx`, `external-secrets`, `argocd`, `monitoring`. Test cluster: `platform-test`, `ingress-nginx`, `external-secrets`. Prod/test aynı cluster'ı **paylaşmaz** |
| D3 | Lokal dev | k3d (Docker Desktop üzerinde) |
| D4 | GitOps motoru | ArgoCD (app-of-apps pattern) |
| D5 | Manifest yönetimi | Kustomize (base + overlays) + Helm (3. parti chart'lar için) |
| D6 | Host-level servisler | PG + Keycloak + Vault → **Kubernetes DIŞINDA** Docker Compose ile host'ta çalışır, test+prod ayrı instance |
| D7 | Service discovery | **Eureka KALDIRILDI** — K8s native DNS (`<svc>.<ns>.svc.cluster.local`). **Dilimli geçiş** (Codex onayı): her PoC diliminde backend + çağıranlar + gateway route birlikte temizlenir. Geçici Eureka YOK |
| D8 | Ingress + TLS | TLS host-level nginx'te termine edilir (cluster içi ingress-nginx HTTP-only). MVP: manuel Sectigo wildcard rotation + script + `60/30/7d` uyarı takvimi + panel erişim doğrulaması. Faz 12 sonrası: yalnız `ai.acik.com` için LE HTTP-01 **dry-run**; başarılıysa otomasyona geç, başarısızsa manuel sürer |
| D9 | Secret | External Secrets Operator + Vault (mevcut Vault source-of-truth kalır) |
| D10 | Observability | kube-prometheus-stack + Loki + Tempo (Helm). **Retention**: Prometheus 10 gün, Loki 7 gün, Tempo 48 saat (MVP). Gerçek ingest ölçüldükten sonra artırma değerlendirilir |
| D11 | Image registry | GHCR (mevcut `deploy-backend.yml` push akışı korunur) |
| D12 | Git stratejisi | Lokal `.git` aktif + **GitHub private remote** (`Halildeu/platform-k8s-gitops`, 2026-04-15 aktif). Lokal → push. Sunucuda deploy key (read-only, port 443 SSH). install-on-staging-sw.sh rsync yerine `git clone/pull`. ArgoCD GitOps bu URL'i kullanır |
| D13 | Yaklaşım | Doğrudan canlı-ready yapı — atılabilir/deney değil |
| D14 | Ana repo paralel | `application-k8s.yml` profili + Dockerfile probe'ları K8s manifest yazımıyla **eş zamanlı** yazılır |
| D15 | CNI | **Calico** (başlangıçtan) — NetworkPolicy garantisi. Flannel değil. +200 MB RAM kabul |
| D16 | Cluster topolojisi | **2 k3d cluster aynı host'ta** (staging-sw): `prod` + `test`. Docker container'larda ayrı k3s node'ları (ayrı API server, etcd, CNI, Docker network, Pod/Svc CIDR). Gerekçe: "birini bozunca diğeri etkileniyor" tecrübesinin tekrarlanmaması. Lokal geliştirici makinede de aynı iki-cluster modeli |
| D17 | Test ortamı çalışma modeli | **Scale-to-zero workload**: test cluster control plane açık (~2 GB sabit), workload'lar default `replicas: 0`. Yoğun saatlerde backend+openfga+frontend kapalı (~0 GB). İhtiyaç halinde `test-toggle.sh up`. Host-level test PG/KC/Vault de kapalı varsayılan |
| D18 | İngress + TLS termination | **Host-level nginx SNI reverse proxy** (mevcut `platform-web-nginx` yerine) 80/443 alır, Sectigo wildcard cert'i termine eder. Hostname'e göre backend: `ai.acik.com` → prod k3d HTTP :30080, `testai.acik.com` → test k3d HTTP :31080. Cluster'ların içindeki ingress-nginx HTTP-only (cert'i host handle ediyor) |
| D19 | Host servis köprüsü | **Service + Endpoints** (IP pin `10.9.10.53`). ExternalName yerine; CoreDNS rewrite kırılgan |
| D20 | Host port ataması | **Mevcut portlar = PROD (`5432, 8081, 8200`)**, yeni portlar = TEST (`5433, 8082, 8201`). Prod verisi migrasyonu YOK |
| D21 | HPA & replica | **MVP'de HPA YOK**. `metrics-server` kapalı kalır. Prod sabit `replicas: 2`, test açıldığında `replicas: 1`. HPA ancak ilk gerçek CPU/latency grafiği toplandıktan sonra geri açılabilir. **Gerekçe**: metrics-server disabled + HPA birlikte tutarsızdı (Codex Tur-1) |
| D22 | CPU bütçesi | Steady-state test kapalı `1.6-2.2 vCPU`, test açık `2.0-2.8 vCPU`; spike (prom compaction + loki flush + rollout aynı anda) `3.4-4.0 vCPU`. **Politika**: CPU request dar ama gerçekçi, limit cömert. `request=limit` yapılmaz. Örüntü: backend `req 150m / lim 750-1000m`, ağır 2-3 servis `req 250-300m`, gateway `req 250m`, kritik podda limit olmayabilir |
| D23 | DR / RPO / RTO | **Prod**: RPO ≤ 24 saat, RTO ≤ 4 saat. **Test**: RPO ≤ 24 saat, RTO ≤ 1 iş günü. Off-host backup (PG dump + Vault raft snapshot farklı host/object storage'a), düzenli restore provası, stateful/node bakım runbook'u **zorunlu**. Tek host bu karar seviyesini destekler — RPO <1h istenirse mimari değişir |
| D24 | JVM bellek politikası | **Ortak explicit heap**: `-Xmx384m` (prod default), ağır 2-3 serviste override (512m), test overlay'de `-Xmx256m`. `-XX:MaxRAMPercentage` **KALDIRILDI** (Xmx ile çelişiyor, yanlış beklenti üretiyordu). Container `resources.limits.memory: 512Mi` (heap + metaspace + direct buffer + JIT için tampon) |
| D25 | PoC dilim stratejisi | Tam manifest çoğaltmasına **geçilmez**, önce ince dilim: `api-gateway + auth-service` (Dilim 1) → `api-gateway + user-service` (Dilim 2) → kalan backend'ler bağımlılık grafına göre. **Kabul kriteri (Dilim 1)**: gateway route `lb://` yok → K8s svc DNS, `auth-service` Eureka'sız kalkar, Keycloak/DB host köprüsü çalışır, smoke yeşil |
| D26 | YAPMA listesi | MVP kapsamında **yok**: MetalLB, GraalVM, K8s içinde geçici Eureka, aynı hosttaki 2 cluster'ı DR/HA gibi sunma, admin UI'ları aynı hostname altında sertleştirmeden bırakma |
| D27 | Upstream-first prensibi | Her bileşen **kendi upstream native mekanizmasını** kullanır: k3s (Rancher), Calico (tigera-operator), ArgoCD (upstream Helm + dex OIDC built-in), kube-prometheus-stack (upstream Helm), External Secrets Operator (upstream CRD), Loki/Tempo (upstream Helm). Bizim yazdığımız custom kod **minimum**: sadece `bootstrap/*.sh` (orchestration), `host-compose/proxy/nginx.conf` (reverse proxy), `kustomize/base/apps/<service>/` (backend manifest'leri, Helm chart değil çünkü zaten build pipeline'ı bizim). **YASAK**: custom admission webhook, özel operator, manuel YAML patch'leri (Kustomize strategic merge yerine). **Gerekçe**: satıcı kilidi yok, upgrade yolu net, community desteği aktif |
| D28 | Handoff şablonu | 5-alan **zorunlu**: `(Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk)`. Tek iddia yeterli değil; her bulgu kanıt ve sınır koşulu ile raporlanır. İlk örnek: `docs/session-handoff-2026-04-17.md`. Sebep: handoff v1↔v2 kanıt sınıfı yarılması (v2 "tam yeşil" iddiası v1'in şüphelerini kapatmadan yazıldı). Kural 2026-04-17 Codex 4-tur mutabakatı |
| D29 | Raporlama seviyeleri | Tek "green" etiketi **YASAK**. 3 seviye zorunlu: (1) **Up** = Pod Ready + edge gerçek backend + kritik dep TCP açık; (2) **Functional** = Up + ana işlev doğru dep ile çalışıyor; (3) **Zanzibar-ready** = Functional + permission-service hub yayında + OpenFGA enabled + `/authz/me`+`/authz/version` + synthetic allow/deny enforce kanıtlı. Ayrıca **Dilim 1A** (authn/transport slice) ≠ **Dilim 1Z** (authz plane env doğru); auth-service permission-service'siz boot edebilir ama "Dilim 1 tamam" denmez |
| D30 | Cutover stratejisi (T0=2026-04-24 LIVE) | Weighted DNS (%10→50→100) **DEĞİL**. Tek-seferlik proxy upstream switch (`ai.acik.com` compose → `k3d-prod:30080` host nginx reload) + **72 saat warm rollback** (compose canlı ama trafik dışı). Ayrıca: test/prod overlay'lerde **digest pin** (repo@sha256) zorunlu, moving tag (`main-stable`) tek başına kanıt değil; pod `imageID` ↔ GHCR digest eşleşmesi doğrulanır. **⚠️ Update 2026-05-15** (PR #695 + Codex `019e2d16` REVISE): Frontend `ai.acik.com` 2026-05-03'den beri cluster-authoritative (Codex `019ded8d` AGREE absorb). System-wide Faz G T0=2026-04-24 satırında zaten 🟢. "Tek-seferlik proxy upstream switch" historical baseline; gerçek pending D30 cutover-execution scope owner clarification gerek (compose decommission OR DNS edge change OR backend Hibernate drift fix epic). V2.1 sub-wave için "Faz G freeze gate unlocked" iddiası sadece **V2.1 prod-readiness sub-wave** kapsamında; system-wide Faz G zaten ✓. Detay: `docs/runbooks/RB-faz-g-rollback-dry-run-inspection.md` + `docs/state/current-state.md` Live Delta entry. |
| D31 | Primary datasource mimarisi | **Tüm mimari PostgreSQL üzerine** kuruludur; PG varsayılan DB (auth, user, variant, core, report, schema, permission, openfga, keycloak). **Dış SQL (MSSQL vb.) secondary/opsiyonel** integration — örn. report/schema Workcube ERP'den `reporting` ve `workcube_mikrolink` DB'lerine **read-only** bağlanır. Dev repo `application-k8s.yml` report/schema için `SQLServerDriver` PRIMARY varsayması **YANLIŞ** → `platform-ssot` tarafında primary PG + secondary MSSQL multi-datasource pattern'e geçilmeli. MSSQL host köprüsü gerekirse D19 pattern (Service+Endpoints IP pin) + ESO-Secret credentials. MSSQL feature **cutover blocker DEĞİL** — feature-flagged opsiyonel |
| D32 | Historical forward-extension path | **SUPERSEDED by ADR-0002**. `staging-sw-2` ayrı fiziksel host yönü tarihsel/gelecek genişleme appendix'i olarak korunur; current main path DEĞİLDİR. Aktif roadmap, same-host dual-cluster + full stateful isolation modelidir. |
| D35 | Canlı scoped E2E gate (D29 synthetic'in karşılığı) | **D29 (Zanzibar-ready) `synthetic allow+deny enforce` gerektirir** — bu CI fixture / ephemeral OpenFGA ile karşılanabilir ve Session 30 itibarıyla `openfga-fixture-smoke.yml` + 10 smoke check ile kalıcıdır. Ancak **canlı ürün davranışı ayrı kapıdır**. D35 = staging-sw k3d-test (sonra k3d-prod) üzerinde tam zincir. **2026-04-28 V22+V23+PR-G outbox merge sonrası 11 adım** (önceki 5'ten genişledi — Codex `019dd0e0` iter-2 eventual-consistency semantic): digest match → env evidence → poller config → POST grant → PG row → outbox PENDING → outbox PROCESSED (eventual) → FGA allow → FGA deny → revoke flip → zero FAILED. Detay: `docs/adr/0009-canli-scoped-e2e-gate.md` + runbook `docs/openfga-multi-org-rollout.md` Step 9. **D29 ≠ D35**: aynı bar değil. Bu ayrım fixture sonucu canlıymış gibi raporlama riskini engeller (Session 30 Codex 019dcbc8 retrospektif + user 2026-04-26 değerlendirmesi). |
| D36 | Image digest auto-sync (Renovate, gitops repo) | **Sorun**: PLAN.md line 810'da "image digest pin (CI günceller)" yazıyor ama pratik **manuel pin sync** (her image yeni → manuel digest pin update PR + rollout). Bu 2026-04-28 D35-3 closure flow'unda gözlemlendi: backend PR #18 merge → image push GHCR → **manuel** PR #242 digest pin → manuel rollout. Frontend drift de aynı pattern (GHCR sha-2dc3734 hazır ama gitops pin sha-57dc28e geride, cluster manuel deploy ile farklı digest). **Karar**: **Renovate** ile auto-bump bot kurulur. **D27 uyumlu** (Renovate community-standard tool, custom kod değil; ArgoCD Image Updater'dan farklı — D27 sadece onu YASAKLAMIŞ). **Kapsam**: (a) test overlay digest pin auto-PR (auto-merge = false; CI checks + boundary block + reviewer onay), (b) prod overlay digest pin için ayrı PR (manuel review + atomic cutover discipline ile uyumlu, D30 selfHeal=false korunur), (c) BG-1.1 dependabot pattern'i ile coverage (`pull_request_target` + boundary block auto-fill: `state-mutation (test cluster)` test overlay'i için, `state-mutation (production)` prod overlay'i için ek `user-approval-required` label). **Boundary**: Renovate bot config (.github/renovate.json) + GitHub App PR yetkisi; image push trigger yok (Renovate kendi cron ile poll eder GHCR'ı). **Faz**: Faz N (D35-3 FULL PASS sonrası, ADR-0011 §4 PR sequence ile paralel). |
| D37 | Admin user OpenFGA tuple coverage discipline | **Sorun**: 2026-04-29 D35-3 FULL PASS sonrası kullanıcı browser session'da admin@example.com (user:1) için 403 toast tespit edildi. Sebep: OpenFGA `organization:default#admin` tuple yalnızca `d35-admin-persona` (user:1204) için manuel seedlenmişti; gerçek `admin@example.com` ve diğer admin user'lar için seed yoktu. AuthorizationControllerV1.checkOrganizationAdmin() bu tuple'ı zorunlu kılar (superAdmin: true cevabı için). Sonuç: DB'de ADMIN role olmayan değil — DB doğru ama OpenFGA katmanında drift. **Karar**: `DefaultAdminRoleAssignmentInitializer` (mevcut Spring Boot CommandLineRunner) **kalıcı olarak aktif edilir** (PR #249 + #250). Pod startup'ta: (a) konfigürasyondaki admin email listesindeki user'lara DB ADMIN role assign, (b) OpenFGA `organization:default#admin` tuple ensure (idempotent writeTuple). Pod restart sonrası admin coverage otomatik onarılır → runtime drift'e karşı kalıcı koruma. **Mevcut kapsam**: ADMIN_EMAILS env var (manuel liste — `admin@example.com,d35-admin@example.com`). **Geliştirme önerileri (post-D37)**: (a) DB-driven dinamik mod — DB'deki ADMIN role'lü user'ları auto-discover (yeni admin eklenince config update gerekmeyecek), (b) DD-6 cross-repo guard — DB ADMIN role ↔ OpenFGA tuple alignment CI lane (DD-5 pattern'i ile uyumlu), (c) RoleChangeEvent listener — assignRole(ADMIN) sonrası tuple seed (cold path startup'a ek olarak hot path). **Codex thread**: `019dd409` (D35-3 prereq strategy + admin tuple coverage gap). |
| D38 | Notification orchestration baseline | **Custom Spring Boot `notification-orchestrator`** (platform-backend repo, yeni sub-dir). Postgres-only stateful (Mongo/Redis/RabbitMQ YASAK — ADR-0002 §7.1 single-host 400GB ile uyumsuz). Mevcut `permission-service` Zanzibar plane reuse (ayrı OpenFGA store değil). 10-aday kıyas tablosu skor: Custom Spring Boot 9/10 (Codex thread `019df86f` AGREE). Novu / Knock / Courier / AWS SNS / SaaS combos = **deferred lab/evaluation candidate**. Ana scope: programmatic transactional notification; no-code workflow editor değer üretmiyor. Detay: ADR-0013-notification-orchestration. |
| D39 | Notification stateful = Postgres-only | Tüm notification state Postgres'te: `notify.notification_intent` + `notification_delivery` + `notification_template` + `subscriber_preference` + `provider_config` + `provider_config_history` + `audit_event` + `dead_letter` + per-domain `notification_outbox`. **Mongo / Redis / RabbitMQ YASAK** — Codex `019df86f` Q2 RED verdict (3 yeni stateful sistem backup/restore + DR matrisi 3 kat büyür; upgrade yüzeyi Java ekibinin dışına çıkar). Outbox pattern: domain service'ler **direct provider çağırmaz**, kendi DB'lerinde transactional outbox row INSERT eder; orchestrator outbox poller PG advisory lock ile pickup eder. |
| D40 | TR SMS provider native Java adapter (tier v1) | TR SMS provider adapter'ları Spring Boot içinde Java client (TS plugin değil). `SmsProvider` interface (`send`, `queryDelivery`/`pollDelivery`, `normalizeError`, `supportsUnicode`, `dlrMode`, `providerKey`). **Provider kararı 2026-05-19 (kullanıcı)**: **Primary**: JetSMS (canlı sözleşme + HTTP API `api.jetsms.com.tr/SMS-Web`), **secondary**: NetGSM 📦 Out of plan / demand-reactivated (ADR-0028 2026-05-25; asset-preserved dormant). İletimerkezi/Mutlucell tertiary DEFERRED. Failover: failover-eligible `SmsFailureClass` (timeout/5xx/system/rate-limit/quota) → secondary auto; kalıcı recipient/content hatası → no-failover. DLR dual-mode: JetSMS **polling pull** (`HttpSmsReport`), NetGSM **webhook push** (`/api/v1/notify/dlr/netgsm`). GSM-7/UCS-2 vs ISO-8859-9 segment + Türkçe karakter + sender ID. **Tier v1** (Codex `019df86f` Q2 REVISE — MVP'den çıkarıldı, MVP-geniş 23.3'e taşındı). Multi-provider PR sequence Codex `019e3f82` AGREE (PR-0..PR-4). **D40-IYS sub-faz drift**: IYS (İleti Yönetim Sistemi) lookup, ticari mesajda zorunlu, OTP/transactional muaf. |
| D41 | Notification multi-tenancy = `org_id` + OpenFGA hard-deny | `subscriber:<userId>#can_receive notification_topic:<key>` OpenFGA tuple kontrolü. `notification_intent.org_id` first-class column, NOT NULL. Cross-org notification isteği reddedilir (deny default). Subscriber-tag authority **yetmez** — OpenFGA otoriter. MVP must-have (D46 #5 — cross-tenant leak kapatır). |
| D42 | Notification KVKK / GDPR disiplin | Açık rıza **transactional kapsam dışı** (Faz 23 marketing değil). **Opt-out**: subscriber `notification_preference` kanal başına; KVKK 11. madde "veri işlemeyi durdurma". **PII redaction**: log'larda mail body / SMS body **maskelenmiş**, sadece `template_id` + `recipient_hash` (sha256) + `org_id` + `correlation_id`. **Retention**: `audit_event` 90 gün default (sub-faz drift 30/180/365). **Right to erasure** (Art.11): payload purge, recipient_hash kalır; **API/runbook MVP**, UI v1. **Right to information** (Art.13): subscriber kendi geçmişi; **API MVP**, UI v1. **DPA**: 3rd party provider sub-faz drift. |
| D43 | Notification outage fallback bypass | **Kritik bulgu** (Codex `019df86f` Q4 PARTIAL): notification-orchestrator **kendi outage'ında alarm gönderemez**. Bu yüzden drift alarm-receiver, break-glass audit, kritik ops alarmı için **Alertmanager → direct SMTP/Slack fallback** ayrı katman olarak tutulur (`monitoring/alertmanager` config). Bu fallback notification-orchestrator'dan **bağımsız**: kendi SMTP/Slack credential'ı ESO ile sync. "Notification-service down" alarmı kendi içinden değil, Prometheus liveness probe + Alertmanager rule'undan gelir. MVP must-have (D46 #10). |
| D44 | Notification channel coverage tier | **Kernel/Closed Beta**: Email + Slack incoming webhook + Webhook egress (3 kanal). **Production MVP dar**: + provider abstraction + preference API + erasure path + alerting. **Production MVP geniş**: + SMS (JetSMS primary + NetGSM secondary) + In-app inbox backend API. **v1**: + SMS DLR + In-app full UI + Microsoft Teams + Web Push + FCM/APNS. **v2**: + WhatsApp Business + Voice/IVR + PWA + A/B testing + No-code workflow editor. **DIŞI**: Email newsletter/marketing + RCS + Apple/Google Business Chat. Detay: `docs/notify/feature-matrix.md`. |
| D45 | Notification 5 yeni kategori (policy axis) | **Codex `019df86f` Q1 eklemesi**: (1) **Deliverability + sender reputation** v1 (bazı email kontrolleri MVP); (2) **Abuse / spam / recipient safety** MVP — yanlış loop, bulk flood, duplicate send, webhook fan-out cap; (3) **Accessibility (WCAG)** v1 (temel template okunabilirliği MVP); (4) **Incident / degraded mode** MVP — outage fallback bypass; (5) **Data classification** MVP — `transactional/security/commercial/system` ayrımı; opt-out + retention + critical bypass policy bu ayrıma bağlı. |
| D46 | Notification 10 must-have çizgisi | Production MVP demek için olmazsa olmaz: (1) Intent + delivery log schema; (2) Idempotency + dedupe; (3) Domain-side outbox; (4) Retry exponential backoff + DLQ + manual replay; (5) OpenFGA hard-deny + org boundary; (6) Vault/ESO + no secret logging; (7) PII redaction + KVKK retention; (8) Preference + critical bypass; (9) Template versioning + safe interpolation; (10) Observability + outage fallback. **Negotiable** (production MVP demek için olmasa da olur): kanal sayısı, workflow editor UI, brand customization, A/B testing, in-app inbox UI. Detay: `docs/notify/must-have-checklist.md`. |
| D47 | Notification Faz 23 süre tahmini ve tier sequencing | **Codex `019df86f` Q5 PARTIAL absorb**: 1 senior Java + 0.5 frontend + 0.5 ops varsayımı. **23.0 Charter** 1 hafta. **23.1 Kernel/Closed Beta** 3-4 hafta (Email + Slack + webhook + outbox + retry/DLQ + audit + OpenFGA + Mailpit/WireMock). **23.2 Production MVP dar** 2-3 hafta original baseline (preference API + erasure + provider versioning + Grafana/alerts + fallback bypass) — **Session 39 iter-2/3 PM re-baseline (Codex thread `019e0c28`): 23.2 closure remaining T1 = ~100h, 4-6 hafta aggressive target M3 2026-06-08 per [sprint-plan.md](docs/notify/sprint-plan.md) + [milestones.md](docs/notify/milestones.md)** — **M3 stale audit 2026-05-09 supersedes ~100h/4-6 hafta**: backend code source-ready 7/9, T1 residual ~52-55h + acceptance gate + Codex iter overhead = ~60-70h provisional sprint / 2.5-3.5 hafta (T1.2 subscriber self-service + T1.4 D43 + T1.6 abuse guards gerçek pending; credential RAID I6 + R2 legal gate açılınca) per [m3-stale-audit-2026-05-09.md](docs/notify/m3-stale-audit-2026-05-09.md). **23.3 Production MVP geniş** 3 hafta (SMS JetSMS primary + NetGSM secondary + in-app backend API). **23.4-23.8 v1** +4-6 hafta. **23.9 Prod cutover** 1 hafta + 72h observation. **Toplam Charter → Prod cutover: 14-18 hafta** (3.5-4.5 ay). v2 (later) +8-12 hafta. **23.0 paralel** ilerleyebilir; 23.1 başlangıcı için **Faz 22.1.1b III review verdict** zorunlu. **Snapshot 2026-05-09 (Session 39, Codex `019e0bff` iter-1 absorb — historical baseline; superseded by M3 stale audit 2026-05-09 5-state matrix per [m3-stale-audit-2026-05-09.md](docs/notify/m3-stale-audit-2026-05-09.md))**: 23.0 🟢 done (1/11); 23.1 🟡 (service runtime LIVE, D29-Functional 3-channel evidence pending); 23.2 🟡 (Session 39 hardening 3/3 done — KVKK retention/Vault/SLO; original MVP-dar acceptance 2/8 done — superseded by audit: source-ready 7/9 + acceptance 1/9); 23.4 🟡 (in-app UI + identity guards LIVE, SMS DLR + archive UI pending); 23.8 🟡 (alerts LIVE, Tempo/bounce/per-tenant pending); 23.9 🟡 (activation LIVE 2026-05-08, 72h observation T+72h=2026-05-11, rollback prova + browser SSO pending); 23.3/23.5/23.6/23.7/23.X ⏳. **Historical: 7/10 must-have 🟢 + 2 partial + 1 pending = ~80% — superseded by M3 audit: 7+3+0 = 8.5/10 = ~85% (#8 ⏳→🟡 demote source-ready) — Session 41 sonu re-baseline 2026-05-09 19:50Z: 7+3+0 = 8.85/10 ≈ ~88.5% (#10 D43 4-PR source-ready bump); 5-state Source-ready 12/12 + Live-deployed 9/12 + Acceptance 0/12; T1 residual ~17-22h (drift -77/-82h vs 99.5h plan); Codex `019e0e51` bağımsız analiz: v1 readiness ~35% acceptance-weighted, "%85 must-have coverage production-ready DEĞİL")**. Net v1 readiness ~30% literal feature, source-ready bias ile semantik daha yüksek. Naming discipline: improvise label OK if cross-references canonical sub-faz ID; canonical status authority = Sub-Faz Tablosu marker'lar. |
| D48 | MFE Auth Transport Contract | Protected MFE HTTP **MUST** wait for shell auth `transportReady`; only bootstrap-chain requests **MAY** bypass the gate (`__skipAuthReadyGate: true` on cookie/authz/login/profile/register endpoints); 401 refresh **MUST** be single-flight and restore token + cookie + authz + Redux + phase state via full closure; observability **MUST** be URL/PII-free (status_class+method counters only, bounded reason enums). Roadmap: PR-Auth-1 #302 → PR-Reporting-2 #304 → PR-HTTP-3 #306 → PR-Refresh-4 #307 → PR-Obs-5 #309 (DONE) + PR-E2E-6 + PR-BE-7 (planned). Detay: ADR-0014. |
| D49 | Notification Graph mail adapter strategy: defer activation, preserve Entra asset | **Codex `019e44b1` defer contract alignment AGREE_WITH_REVISIONS (Session 42 2026-05-20)**: SMTP Office 365 path (`ai@acik.com` + App Password) canonical kalır; Microsoft Graph adapter binary backend (PR #153 sha-585b64f) capability olarak korunur ama **activation deferred** trigger geldiğinde (Microsoft App Password deprecation, SMTP AUTH tenant policy break, outbound 587 ISP block recurrence, ops/security tactical decision, provider migration). Entra App Registration `acik-mail-graph-api` + Mail.Send Application permission + **tenant-wide admin consent verildi** (asset olarak korunur; en ağır setup tamamlandı). Client secret + ApplicationAccessPolicy + Vault graph_* seed + ConfigMap flag flip + digest bump + smoke send 5-adım reactivation chain **atomic** çalıştırılır; parçalı aktivasyon yasak. Mailbox scope ApplicationAccessPolicy ile `ai@acik.com`'a daraltılır (RestrictAccess; blast-radius). Cross-AI peer review chain: `019e44b1` (defer contract), `019e42d1` (PR #872 staged-only ESO 3-key + DNS runbook), `019e4445` (#862 deprecation + bridge truth-cleanup). Detay: [ADR-0024](docs/adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](docs/runbooks/RB-graph-mail-adapter-activation.md) + board [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892). |

### Decision Register Status (Faz 23 — Session 39 truth alignment 2026-05-09)

| ID | Karar | Status | Implementation Reference |
|---|---|:---:|---|
| D38 | Notification orchestration baseline (Custom Spring Boot) | 🟢 implemented | notification-orchestrator service LIVE prod 2026-05-08; PG-only stateful confirmed; permission-service Zanzibar reuse working |
| D39 | Notification stateful = Postgres-only | 🟢 implemented | V1+V8+V9-staging migrations LIVE; no Mongo/Redis/RabbitMQ added; outbox pattern live (alarm-receiver PR #347) |
| D40 | TR SMS provider native Java adapter (tier v1) | 🟡 in-progress (JetSMS primary + NetGSM secondary, 2026-05-19 kullanıcı kararı; PR-0..PR-4 sequence Codex `019e3f82` AGREE) | Charter 23.3 chain; T3.1 sprint plan; R1 NetGSM secondary contract = failover acceptance blocker (primary aktif) |
| D41 | Notification multi-tenancy = `org_id` + OpenFGA hard-deny | 🟢 implemented | NotifyOrgAccessGuard strict cutover LIVE (PR-5.4 default-org close + PR-5.5 subscriberId strict); 25 PrometheusRule alerts |
| D42 | Notification KVKK / GDPR disiplin | 🟢 implemented | Retention 90 day LIVE (PR #427/#437); PII redaction LIVE (Vault pepper); **erasure API + right-to-information LIVE** (M3 R2 K-PR chain 6/7 MERGED = K1-K5+K7 — admin + subscriber self-service `SubscriberErasureController` + `AdminErasureController` + V18 erasure ledger + 30-gün SLA watchdog + audit body redaction LIVE); **R2 CLOSED 2026-05-23** via Codex `019e5189` final legal verdict (kullanıcı kararı 2026-05-23: Codex istişare verdict'i = kabul edilen hukuk onayı); K6 tenant-scoped DPO authz P1 non-blocking 23.2.B follow-up |
| D43 | Notification outage fallback bypass | 🟢 mock-receipt mitigated | Charter 23.2.D T1.4 PR-1/2/3 + first controlled test drill 2026-05-10 (Mailpit SMTP receipt LIVE); **BL-008 mock-receipt drill 2026-05-24 16:14-16:26Z** (Codex `019e5aaf` REVISE absorb): test cluster DUAL receipt evidence (webhook-receiver POST `/slack-mock` 200 length=983 + Mailpit `[D43 DRILL] NotifyServiceAbsent` 16:17:33Z — same Alertmanager dispatch cycle); 10/10 mock-receipt criteria PASS; R9 🟡 Partial → 🟢 Mitigated (mock-receipt). **Real Slack workspace** (board #853) + **prod activation** (board #854 — `auth_*_file` Operator v0.90.1 schema gap fix gerekir) ayrı operator-external action. Evidence: `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md` |
| D44 | Notification channel coverage tier | 🟢 specified | Charter sub-faz mapping (Kernel/MVP-dar/MVP-geniş/v1/v2 with feature-matrix); D29-NOTIFY 3-katman per channel evidence partial |
| D45 | Notification 5 yeni kategori (policy axis) | 🟢 source-ready / 🟡 partial | (1) Deliverability: 🟢 source-ready DKIM relay strategy LIVE prod 2026-05-20 (PR-B1 platform-backend #268 + gitops #914+#915+#916; Office 365 Native CNAME pattern; DNS publish operator-gated); R3 🟢 mitigated upgraded; (2) Abuse: 🟢 M3 T1.6 23.2.F AbuseGuardService + NotifyAbuseStorm PrometheusRule + Service IT LIVE Session 41 FULL ACCEPTANCE (R13 + R19 mitigated); (3) Accessibility: ☐ pending WCAG (Email multipart N1 LIVE via C4 cross-ref); (4) Incident/degraded: 🟢 **T1.4 D43 mock-receipt mitigated** (BL-008 2026-05-24 dual-receipt drill — webhook-receiver POST + Mailpit SMTP); real Slack #853 + prod activation #854 operator-external; (5) Data classification: 🟢 MVP core LIVE (P1; M3 T1.5 23.2.E PR #149 9-test acceptance) — per-class retention/commercial consent refinements (P3/P4 feature-matrix §16) remain partial/pending |
| D46 | Notification 10 must-have çizgisi | 🟢 source-side / 🟡 operator-gated | **9+/10 source-side improved after BL-008 mock-receipt drill 2026-05-24**: #1-#7/#9 🟢, #8 🟢 source-ready/live (M3 T1.1 23.2.A preference trilogy + M5 23.5 UI LIVE), #10 🟢 **mock-receipt mitigated** (BL-008 2026-05-24 dual-receipt drill); real Slack workspace #853 + prod activation #854 operator-external residual (Operator v0.90.1 `auth_*_file` schema gap fix #854 kapsamında). Production-ready claim DEĞİL — canonical status authority [milestones.md](docs/notify/milestones.md) + [sprint-plan.md](docs/notify/sprint-plan.md) + [risk-register.md](docs/notify/risk-register.md) + [feature-matrix.md](docs/notify/feature-matrix.md). [must-have-checklist.md](docs/notify/must-have-checklist.md) marker'ları historical/stale notu kendi başlığında belirtir; evidence path olarak referans, status authority değil. |
| D47 | Notification Faz 23 süre tahmini ve tier sequencing | 🟢 specified | Sub-faz tablosu + M0..M9 milestone tracker [milestones.md](docs/notify/milestones.md); estimation **~232-235h v1 residual** (M3 stale audit 2026-05-09 re-baseline; ~280h historical baseline superseded) + ~144h v2 |
| D48 | MFE Auth Transport Contract | 🟢 implemented | PR-Auth-1 #302 + PR-Reporting-2 #304 + PR-HTTP-3 #306 + PR-Refresh-4 #307 + PR-Obs-5 #309 LIVE; PR-E2E-6 + PR-BE-7 pending |
| D49 | Notification Graph mail adapter strategy | 🟡 deferred | Entra asset preserved (`acik-mail-graph-api` + Mail.Send + admin consent active); SMTP canonical; reactivation chain documented in [ADR-0024](docs/adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](docs/runbooks/RB-graph-mail-adapter-activation.md); tracked by [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) (P3 Backlog future-only); aktif risk sıfır (client secret yok → permission kullanılamaz) |

**Status Legend**: 🟢 implemented (live cluster) · 🟢 specified (charter authoritative, no impl) · 🟡 partial · 🔴 pending · ⏳ deferred

**Cross-references**:
- [risk-register.md](docs/notify/risk-register.md) — risk gates per D-karar
- [sprint-plan.md](docs/notify/sprint-plan.md) — task breakdown per pending D
- [milestones.md](docs/notify/milestones.md) — milestone-level closure dates
- [test-strategy.md](docs/notify/test-strategy.md) — test coverage per sub-faz
- [dependency-graph.md](docs/notify/dependency-graph.md) — task dependency + critical path
- [stakeholder-plan.md](docs/notify/stakeholder-plan.md) — communication discipline

**HARD RULES:**
- **D16 gereği**: `prod` ve `test` **AYRI k3d cluster**'larında çalışır (aynı host'ta ama farklı control plane). Her cluster'da kendi `platform-*` ns'i, kendi `ingress-nginx` + `external-secrets` ns'i. Prod cluster'ında ayrıca `argocd` + `monitoring` ns'leri.
- Her iki cluster da **ayrı host-level PG/KC/Vault** instance'ı kullanır (D6, D20)
- OpenFGA K8s içinde (StatefulSet), PostgreSQL host'ta
- Mevcut `decisions/topics/zanzibar-openfga.v1.json` kuralları K8s'te de geçerlidir (ScopeContextFilter order, vb.). **Not 2026-04-17 revize:** Eski "port 8090 yok" kuralı KALDIRILDI — D-003 TRANSFORMED ile uyumlu olarak `permission-service` Service `port: 8090, targetPort: 8084` **doğru** kontrattır. `platform-ssot` compose `8090:8084` mapping ve `auth-service` K8s profile `http://permission-service.../:8090` bu güncel tasarımı yansıtır.
- Cron deploy DISABLED kalır stabilizasyon bitene kadar
- **Prod dış + iç, test sadece iç**: prod `ai.acik.com` dış proxy (`212.115.26.190`, L4 pass-through) üzerinden kurum ağı/VPN'den erişilir; test `testai.acik.com` yalnız intranet (A kaydı `10.9.10.53`, dış proxy'e yazılmaz)
- **Admin UI'lar path altında**: ArgoCD, Grafana, Prometheus dahil her admin endpoint `ai.acik.com/<path>` şemasını kullanır — ayrı subdomain yok (DNS yükü minimum, tek cert yeter)
- **STABİLİTE KAPISI** (2026-04-15 kararı): `testai.acik.com` üzerinde **tüm Dilim'ler tamamen stabil olduktan sonra** `ai.acik.com` prod cutover'a geçilir. Test ortamı, prod'a geçişin **kabul kriteri**dir; smoke + chaos + load test'leri yeşil olmadan prod kurulumu başlamaz. Bu yüzden sıralama: test cluster ayağa → testai.acik.com smoke → tüm Dilim 1+2+3 testai'de stabil → SONRA prod cluster ayağa + cutover.
- **AUTHORITATIVE ENTRYPOINT** (2026-04-17, Codex 4-tur mutabakat): "Yeşil/hazır/stabil" iddiası, **authoritative entrypoint** ve **hop sınıfı** açık değilse **geçersizdir**. Cluster-bypass kanıtı (intra-cluster exec, management port) gerçek kullanıcı yolunu tek başına ispatlamaz. Smoke tuple zorunlu: `(status + Content-Type + body sentinel)` + negatif kontrol (bilinmeyen host → 200 HTML OLMAZ). Sebep: handoff v2 "testai 7/7 smoke 200" iddiası SNI fallback yüzünden yanıltıcıydı (gerçekte compose frontend HTML döndü).
- **UP ≠ FUNCTIONAL ≠ ZANZIBAR-READY** (2026-04-17, D29 karşılığı): Tek kelimelik "green" etiketi **YASAK**. Her servis için 3 seviye ayrı raporlanır: (1) **Up** = Pod Ready + edge gerçek backend + kritik dep TCP açık; (2) **Functional** = Up + kendi ana işlevi doğru dependency ile (örn. report/schema primary PG kullanımı); (3) **Zanzibar-ready** = Functional + permission-service hub yayında + OpenFGA enabled=true + `/authz/me` + `/authz/version` çalışıyor + synthetic allow+deny enforce kanıtlı. "Dilim 1A" (authn slice) ≠ "Dilim 1Z" (authz plane env doğru).
- **IMMUTABLE ARTIFACT — DIGEST+IMAGEID** (2026-04-17, D30 karşılığı): `main-stable` gibi moving tag **tek başına kanıt sayılmaz**. Overlay'lerde CI tarafından yazılan **digest pin** (repo@sha256:...) zorunlu. Pod `imageID` ile GHCR digest eşleşmesi doğrulanır. Sebep: GHCR rebuild K8s'e "yeni image" dedirtmez, IfNotPresent policy eski image ile çalışır.
- **CUTOVER ATOMIC SWITCH** (2026-04-17, D30 karşılığı): Cutover weighted DNS (%10→50→100) **DEĞİL** — tek-seferlik proxy upstream switch (`ai.acik.com` compose → `k3d-prod:30080`) + **72 saat warm rollback** (compose canlı ama trafik dışı). Weighted yalnızca session/cache/side-effect riski ayrı doğrulandığında açılabilir; şu anki tasarımda gereksiz risk.
- **HANDOFF ŞABLONU 5-ALAN** (2026-04-17, D28 karşılığı): Her drift iddiası `(Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk)` formatında yazılır. Tek başına "iddia" yeterli değil. Örnek: `docs/session-handoff-2026-04-17.md`.
- **NO CLOSURE LANGUAGE** (2026-04-19, kullanıcı direktifi + memory `feedback_no_closure_language.md`): "Bugün kapandı", "tamam bitti", "Seviye X tamam", "gün sonu rapor", "başarıyla tamamlandı" gibi **kapanış/sonlandırma cümleleri YASAK**. Kullanıcı açıkça "yeter/bitti/dur" diyene kadar **sürekli ortak çalışmaya devam edilir**. Her iş bitiminden sonra bir sonraki adım belirlenir ve uygulanır (veya onay alınır). Ara raporlar "durum güncellemesi / devam sırası" tonunda olur — kapanış değil.
- **KULLANICI-FACING GİZLİLİK** (2026-04-19, kullanıcı direktifi + `docs/handoff-S2-X3-security-hygiene.md`): Hiçbir HTTP response (header veya body) dahili IP, hostname, cluster internal resource identifier içermez. Kullanıcı browser'ında yalnız public domain + user-facing error mesajı görünür. Konsekvans: `X-Real-IP`/`X-Forwarded-For` request-only (response'a sızmaz), Spring Boot whitelabel error disabled (prod), Actuator exposure whitelist (`health, info, prometheus, metrics` — env/configprops/loggers YASAK), frontend console.log removal prod build, OIDC issuer-uri domain bazlı. Dokümanlarda IP yerine semantic ad (staging-sw intranet, kurumsal dış proxy, docker bridge).

---

## 1.5 D32 staging-sw-2 Bootstrap Kontrat Listesi (Historical Appendix)

> Bu bölüm current main path değildir. `staging-sw-2` ayrı fiziksel host yönü, ADR-0002 sonrasında **historical / forward-extension appendix** olarak korunur. Aynı-host dual-cluster modeli bloklanmadığı sürece bu checklist aktif roadmap yerine geçmez.

### F1 — Donanım + Temel Kurulum
- [ ] **F1.1** staging-sw-2 fiziksel sunucu satın alma (Ubuntu 22.04 LTS hedef, min 4vCPU/24GB RAM/200GB disk — staging-sw eş spec)
- [ ] **F1.2** Ubuntu kurulum + SSH + `halil` user + sudoers
- [ ] **F1.3** `$HOME/.local/bin` PATH setup + kubectl/k3d/helm binary install
- [ ] **F1.4** Docker CE + compose plugin install
- [ ] **F1.5** Host firewall/port matrisi (80/443 host nginx, 6443/9080/ingress k3d-prod, 5432/8080/8200 host compose)

### F2 — k3d-prod Cluster
- [ ] **F2.1** `bootstrap/k3d-prod.yaml` ile cluster create (CIDR 10.42.0.0/16 pod + 10.43.0.0/16 svc, HTTP ingress hostPort 30080)
- [ ] **F2.2** Tigera Operator + Calico install (tek-node için `typhaDeployment.replicas=0` Installation CR)
- [ ] **F2.3** ingress-nginx install (DaemonSet, hostPort 80/443, values-prod.yaml)
- [ ] **F2.4** ArgoCD install prod cluster (`bootstrap/install-argocd.sh prod`)
- [ ] **F2.5** kube-prometheus-stack install (Prom + Grafana + Alertmanager + node-exporter + kube-state-metrics)
- [ ] **F2.6** Loki + Tempo install (host-level tutulmaz, K8s internal filesystem)
- [ ] **F2.7** Promtail DaemonSet (sysctl `inotify=512` F1 aşamasında host'a set edilmeli — W2 pattern)

### F3 — Host Compose PROD Instance (fresh kurulum, data migration YOK)
- [ ] **F3.1** `host-compose/vault/prod/docker-compose.yml` — Vault prod instance (port 8200)
- [ ] **F3.2** `host-compose/keycloak/prod/docker-compose.yml` — KC prod (port 8081)
- [ ] **F3.3** PostgreSQL prod container (port 5432)
- [ ] **F3.4** PG init script: `CREATE DATABASE auth_db, users_db, variants_db, core_db, reports_db, schemas_db, keycloak, openfga, permission_db` (D32 prereq — bugünkü manuel S1-D7 pattern otomatikleşir)
- [ ] **F3.5** Keycloak realm/clients seed (admin-cli + smoke-client + canary-load + service-token)
- [ ] **F3.6** Vault seed: AppRole + backend-deploy-runtime.hcl policy + KV paths (`kv/platform/<service>/<env>`)
- [ ] **F3.7** `platform-prod-net` Docker bridge — k3d-prod cluster + host compose bağlantı (test'teki `platform-test-net` pattern)

### F4 — Host Nginx SNI Proxy (staging-sw-2)
- [ ] **F4.1** `host-compose/proxy/docker-compose.yml` + `nginx.conf` (D18 referans)
- [ ] **F4.2** Sectigo wildcard `*.acik.com` cert mount (staging-sw ile aynı cert, paylaşımlı)
- [ ] **F4.3** `ai.acik.com` server block → `proxy_pass http://127.0.0.1:30080` (k3d-prod ingress-nginx)
- [ ] **F4.4** nginx `nginx -t` + reload test

### F5 — Network + Dış Proxy Hazırlığı
- [ ] **F5.1** staging-sw-2 kurumsal IP ataması (10.x.x.x intranet)
- [ ] **F5.2** Dış proxy `212.115.26.190` L4 backend tablosuna staging-sw-2 IP eklenmesi (sysadmin iş — **apply değil, hazırlık**)
- [ ] **F5.3** DNS kaydı: `ai.acik.com` A kaydı şu an staging-sw'ye (dış proxy üzerinden), cutover sırasında dokunulmaz (proxy backend değişimi yeterli)

### F6 — Artifact + Secret
- [ ] **F6.1** `ghcr-pull` ESO ExternalSecret (W1 pattern, Vault `kv/gitops/ghcr-token`)
- [ ] **F6.2** Her servis için ExternalSecret (SPRING_DATASOURCE_*, KC_CLIENT_SECRET, AUTH_SERVICE_JWT_PRIVATE_KEY)
- [ ] **F6.3** permission-service ExternalSecret (`PERMISSION_SERVICE_INTERNAL_API_KEY`)

### F7 — GitOps Bağlama
- [ ] **F7.1** ArgoCD repo credential (SSH deploy key — staging-sw ile aynı key)
- [ ] **F7.2** ArgoCD Application CR'ları (root.yaml → 3 app: platform-system, platform-prod, monitoring)
- [ ] **F7.3** ArgoCD first sync — platform-prod overlay (DRY RUN önce, sonra manual sync)

### F8 — Pre-Cutover Smoke (prod cluster hazır ama trafik yok)
- [ ] **F8.1** permission-service + auth + 7 backend Pod Ready
- [ ] **F8.2** imageID kanıt (digest pin = GHCR)
- [ ] **F8.3** Intra-cluster Zanzibar smoke (port-forward, hub + enforcement)
- [ ] **F8.4** Local host `curl` test (staging-sw-2 host nginx → k3d-prod ingress → gateway)
- [ ] **F8.5** No-Go gate review 6 blocker PASS

### F9 — Cutover (S4-D dizisi, F8 PASS sonrası)
- [ ] **F9.1** Preflight + Freeze + Rollback rehearsal
- [ ] **F9.2** Dış proxy backend switch: `staging-sw → staging-sw-2` (sysadmin iş)
- [ ] **F9.3** Atomic smoke (edge `ai.acik.com` gerçek backend staging-sw-2)
- [ ] **F9.4** Hot observation 30-60dk
- [ ] **F9.5** Continuity check (canary restart)
- [ ] **F9.6** 72h warm rollback window (staging-sw compose frozen)
- [ ] **F9.7** Decommission gate (ayrı karar)

**Kritik Not:** Bu checklist **sonraki session başlangıç rehberi**dir. Checklist dışı iş yapılırsa drift üretir (Zanzibar-25 permission-service pattern'i). Her maddenin altı doldurulmadan bir sonraki aşamaya geçilmez.

---

## 2. Mimari

### 2.1 Fiziksel Topoloji

> **Bu bölüm eski tek-k3s modelini anlatıyordu. Güncel 2-k3d topolojisi için
> Bölüm 2.5 Cluster Topolojisi'ne bakın (D16).**
> Aşağıdaki diyagram REFERANS — fiziksel kaynak dağılımı açıklığı için tutuldu.

```
┌────────────────────────── staging-sw (Ubuntu sunucu) ──────────────────────────┐
│                                                                                 │
│   ┌──────────── k3s cluster ────────────┐   ┌──── Host-Level (Docker) ────┐   │
│   │                                      │   │                              │   │
│   │  ns: platform-test                   │   │  postgres-test (port 5432)   │   │
│   │    ├── user-service                  │   │  keycloak-test  (port 8081)  │   │
│   │    ├── auth-service                  │   │  vault-test     (port 8200)  │   │
│   │    ├── variant-service               │   │                              │   │
│   │    ├── core-data-service             │   │  postgres-prod (port 5433)   │   │
│   │    ├── report-service                │   │  keycloak-prod  (port 8082)  │   │
│   │    ├── schema-service                │   │  vault-prod     (port 8201)  │   │
│   │    ├── permission-service            │   │                              │   │
│   │    ├── api-gateway                   │   └──────────────────────────────┘   │
│   │    ├── discovery-server (Eureka)     │                                      │
│   │    ├── openfga (StatefulSet)         │   Host servisleri k8s içinden        │
│   │    └── frontend (nginx + MFE)        │   ExternalName Service + Endpoints   │
│   │                                      │   ile erişilir                       │
│   │  ns: platform-prod                   │                                      │
│   │    └── (aynı 10 workload)            │                                      │
│   │                                      │                                      │
│   │  (platform-system tek-ns modeli     │                                      │
│   │   eski — güncel: ayrı ns'ler        │                                      │
│   │   Bölüm 2.5; cert-manager YOK,      │                                      │
│   │   TLS host nginx'te termine D8/D18) │                                      │
│   └──────────────────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Network Akışı

```
Internet/VPN → host nginx (SSL termine) → prod k3d ingress-nginx → 
  /, /api, /auth, /actuator → api-gateway.platform-prod.svc (gateway route)
  /argocd                   → argocd-server.argocd.svc (ayrı Ingress, argocd ns)
  /grafana                  → grafana.monitoring.svc (ayrı Ingress)
  /prometheus               → prometheus.monitoring.svc (ayrı Ingress)

testai.acik.com → test k3d ingress-nginx → api-gateway.platform-test.svc
  (test cluster'da ArgoCD/Grafana YOK, prod cluster uzaktan yönetir)
```

### 2.3 Hostname & TLS (FINAL)

**Hostname şeması — path-based routing:**

```
PROD (platform-prod)                     TEST (platform-test)
ai.acik.com/                             testai.acik.com/
├── /            → frontend (MFE)        ├── /            → frontend
├── /api         → api-gateway           ├── /api         → api-gateway
├── /auth        → api-gateway → auth-svc├── /auth        → api-gateway → auth-svc
├── /argocd      → argocd-server         ├── /argocd      → argocd-server
├── /grafana     → grafana               ├── /grafana     → grafana
└── /prometheus  → prometheus            └── /prometheus  → prometheus
```

- `ai.acik.com`: **mevcut**, prod. Erişim yolu: internet/VPN → dış proxy `212.115.26.190` (L4 pass-through, kurum yönetiminde) → `10.9.10.53:443` (k3s ingress-nginx)
- `testai.acik.com`: **YENİ**, intranet-only. A kaydı `10.9.10.53` — sadece iç Windows AD DNS'e (`acikdc01.acik.local`) eklenir, dış proxy'e yazılmaz.
- Path-based seçiminin gerekçesi: sadece 1 yeni DNS kaydı (testai.acik.com) + tek wildcard cert, admin UI'lar için subdomain yok.

**TLS stratejisi — host-level nginx'te termine (D18):**

| Lokasyon | Dosya | Cert | Kaynak |
|---|---|---|---|
| Host (Compose) | `host-compose/proxy/tls/wildcard-acik-com.{crt,key}` | Sectigo `*.acik.com` + `acik.com` | mevcut PEM (`STAR_acik_com.crt` + `.key`, Nginx bundle) |

- Hem `ai.acik.com` hem `testai.acik.com` aynı host nginx + aynı cert ile servis edilir (wildcard SAN).
- **Cluster içinde TLS Secret YOK** — k3d ingress-nginx HTTP-only dinler (port 30080/31080), host nginx zaten SSL termine ediyor.
- **cert-manager MVP'de kurulmaz**. Renewal stratejisi (D8): manuel Sectigo rotation + script + 60/30/7 gün uyarı + panel erişim doğrulaması.
- **Faz 12 sonrası**: `ai.acik.com` için LE HTTP-01 dry-run. Başarılıysa cert-manager otomasyonu ayrıca kararlandırılır; `testai.acik.com` intranet-only kaldığı sürece bu kapsam dışı.
- Compose nginx (mevcut `platform-web-nginx`) cutover anında durdurulur; host-compose/proxy/ altındaki yeni nginx devralır (aynı 443 port, aynı cert).

**Cert dosyaları:**
- Local path: `/Users/halilkocoglu/Downloads/STAR_acik_com1/Nginx/STAR_acik_com.{crt,key}`
- Issuer: Sectigo Public Server Authentication CA DV R36
- Validity: 2026-03-17 → **2026-10-01 (P0 renewal reminder)**

### 2.4 Kapasite & Aşamalı Cutover (FINAL — sabit kaynak)

**Sunucu kaynağı (staging-sw):** 4 vCPU · 24 GiB RAM · 97 GiB disk → **200 GiB (ETA: 2026-04-16, sysadmin onayl\u0131)**. RAM ve CPU sabit, sadece disk büyür. Tasarım disk 200 GB sonrasını varsayar; geçiş döneminde 97 GB ile başlayıp 200 GB'a geçilir.

**RAM bütçesi (2 k3d cluster + scale-to-zero test):**

| Bileşen | Prod cluster | Test cluster | Not |
|---|---|---|---|
| k3s control plane (etcd+apiserver+kubelet+kube-proxy) | ~1.5 GB | ~1.5 GB | **Her cluster ayrı** |
| Calico (node + kube-controllers) | ~180 MB | ~130 MB | Test'te Typha skip |
| CoreDNS | ~100 MB | ~80 MB | |
| ingress-nginx | ~250 MB | ~250 MB | |
| External Secrets Operator | ~200 MB | ~150 MB | |
| ArgoCD (server+repo+controller+redis+dex) | ~1 GB | **0** | Sadece prod'da, test uzaktan yönetilir |
| Monitoring stack (prom+grafana+loki+tempo+promtail+alertmanager) | ~2.2 GB | **0** | Sadece prod'da. Retention: Prom 10d, Loki 7d, Tempo 48h (MVP, D10) |
| **Cluster overhead (alt toplam)** | **~5.7 GB** | **~2.1 GB** | |
| Backend prod (8 × 384 MB heap) | ~3 GB | - | `-Xmx384m` explicit (D24 — MaxRAMPercentage kaldırıldı) |
| Backend test (KAPALI — r=0) | - | 0 GB | Yoğun saat |
| Backend test (AÇIK) | - | ~2 GB | 8 × 256 MB heap |
| OpenFGA + Frontend | ~130 MB | 130 MB (açık) / 0 (kapalı) | |
| **Cluster workload (alt toplam)** | **~3.1 GB** | 0 / ~2.1 GB | |
| **K3d Docker overhead (container OS)** | ~300 MB | ~300 MB | |
| **TOPLAM cluster başına** | **~9.1 GB** | **~2.4 GB (kapalı) / ~4.5 GB (açık)** | |
| Host-level Compose prod (PG+KC+Vault) | 0.97 GB | - | sürekli açık |
| Host-level Compose test (PG+KC+Vault) | - | 0 / 0.97 GB | test açılırken up |
| Host OS + Docker daemon | 1.0 GB | shared | |
| **TÜM SİSTEM — test KAPALI** | | | **~13.5 GB → 10.5 GB yedek ✓** |
| **TÜM SİSTEM — test AÇIK** | | | **~16.5 GB → 7.5 GB yedek ✓** |

**Optimizasyonlar (opsiyonel, gerekirse):**
- Test cluster Typha skip → -150 MB
- Test backend `-Xmx192m` → -500 MB
- Test cluster minimal admission → -80 MB
- **Toplam tasarruf:** ~730 MB (test açık → 15.8 GB'a iner)

**CPU bütçesi (D22):**

| Senaryo | CPU kullanımı | Not |
|---|---|---|
| Test kapalı, steady-state | **1.6-2.2 vCPU** | k3d overhead + prod 8 backend idle + Prometheus scrape |
| Test açık, steady-state | **2.0-2.8 vCPU** | + test control plane + test workload idle |
| Spike (prom compaction + loki flush + rollout aynı anda) | **3.4-4.0 vCPU** | Kısa süreli, dar request'li podlarda throttle mümkün |
| Kalıcı saturation (rollout + trafik spike + compaction) | **4.0+ vCPU** | Node CPU pressure → latency artar |

**CPU request/limit örüntü:**
- Backend tipik: `request 150m` / `limit 750m-1000m`
- Ağır 2-3 servis: `request 250-300m` / `limit 1000m`
- api-gateway: `request 250m` / `limit 1000m`
- Kritik podda limit YOK (kontrollü node saturation)
- **`request=limit` YAPILMAZ** (D22) — QoS BestEffort/Burstable avantajı kaybedilir
- JVM için `-XX:ActiveProcessorCount=<limit_cpu>` yoksa GC threadleri host 4 vCPU'ya göre scale eder → throttle artar

**ResourceQuota (FINAL — per cluster):**

Prod cluster:

| Namespace | RAM cap | CPU cap |
|---|---|---|
| `ingress-nginx` | 512 MiB | 0.2 vCPU |
| `external-secrets` | 256 MiB | 0.1 vCPU |
| `argocd` | 1.5 GiB | 0.5 vCPU |
| `monitoring` | 3 GiB | 0.7 vCPU |
| `platform-prod` | 6 GiB | 2 vCPU |

Test cluster:

| Namespace | RAM cap | CPU cap |
|---|---|---|
| `ingress-nginx` | 256 MiB | 0.1 vCPU |
| `external-secrets` | 150 MiB | 0.05 vCPU |
| `platform-test` | 3 GiB | 1 vCPU |

**Pod default LimitRange:** `requests=128Mi/100m, limits=512Mi/500m` (servis bazında override).

**Scale-to-zero test toggle:**
- `scripts/test-toggle.sh up` → `kubectl scale -n platform-test deploy --all --replicas=1` + `docker compose -f host-compose/*/test/docker-compose.yml up -d`
- `scripts/test-toggle.sh down` → tersi
- ArgoCD sync policy test namespace için `ignoreDifferences: [spec.replicas]` (scale manuel yönetilir)

**Aşamalı cutover (disk darlığı yüzünden zorunlu sıralama):**

```
Adım 1  → Hafif docker prune (sadece dangling, kullanıma dokunma)         ~5-10 GB serbest
Adım 2  → k3s kur (containerd ayrı image store; Docker compose ayakta)    +10 GB ihtiyaç
Adım 3  → platform-system + platform-test ayağa kalkar (compose-prod paralel)
Adım 4  → Test smoke testleri YEŞİL (zanzibar, e2e)
Adım 5  → compose-prod STOP (release date: T)
Adım 6  → docker system prune -a --volumes  → ~50 GB serbest (büyük temizlik)
Adım 7  → platform-prod K8s'te ayağa kalkar
Adım 8  → 1 hafta gözlem + rollback hazır (compose-prod restart script <30 sn)
Adım 9  → Compose backend tamamen kaldırılır (host-level PG/KC/Vault KALIR)
```

**Disk projeksiyonu (kritik nokta):**
- Adım 2 sonu: ~84 GB used (%87) ⚠️ — disk monitoring alert eşiği %85 = sınır
- Adım 6 sonu: ~30 GB used (%31) ✓ — rahat
- Steady state (12 ay): retention + state büyümesi ile ~50 GB hedefi

### 2.5 Cluster Topolojisi & Node Mimarisi (FINAL — 2 k3d)

**İki k3d cluster aynı host'ta** (staging-sw + geliştirici makinesi aynı şablon):
- `prod` cluster — üretim workload'ları, merkezi ArgoCD + monitoring
- `test` cluster — sadece workload'lar (ArgoCD/monitoring yok, prod cluster uzaktan yönetir/scrape eder)

**Prod cluster config (`k3d-prod.yaml`):**

```yaml
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: prod
servers: 1
agents: 0
image: rancher/k3s:v1.31.x-k3s1
network: platform-prod-net
kubeAPI:
  hostIP: "127.0.0.1"
  hostPort: "6443"
ports:
  - port: "127.0.0.1:30080:80"      # HTTP — host nginx proxy bunu dinler
    nodeFilters: [server:0]
  - port: "127.0.0.1:30443:443"     # HTTPS — kullanılmaz (TLS host'ta termine)
    nodeFilters: [server:0]
options:
  k3s:
    extraArgs:
      - arg: "--disable=traefik"
      - arg: "--disable=servicelb"
      - arg: "--disable=metrics-server"
      - arg: "--flannel-backend=none"
      - arg: "--disable-network-policy"
      - arg: "--cluster-cidr=10.42.0.0/16"
      - arg: "--service-cidr=10.43.0.0/16"
```

**Test cluster config (`k3d-test.yaml`):**

```yaml
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: test
servers: 1
agents: 0
image: rancher/k3s:v1.31.x-k3s1
network: platform-test-net           # ayrı Docker network
kubeAPI:
  hostIP: "127.0.0.1"
  hostPort: "7443"                   # prod'dan farklı
ports:
  - port: "127.0.0.1:31080:80"       # prod'dan farklı host port
    nodeFilters: [server:0]
options:
  k3s:
    extraArgs:
      - arg: "--disable=traefik"
      - arg: "--disable=servicelb"
      - arg: "--disable=metrics-server"
      - arg: "--flannel-backend=none"
      - arg: "--disable-network-policy"
      - arg: "--cluster-cidr=10.44.0.0/16"   # farklı pod CIDR
      - arg: "--service-cidr=10.45.0.0/16"   # farklı svc CIDR
      - arg: "--kube-apiserver-arg=enable-admission-plugins=NamespaceLifecycle,ResourceQuota"
      - arg: "--kubelet-arg=max-pods=80"     # 50->80 #2306 (live=50 until recreate)
```

**Host-level nginx SNI proxy (`host-compose/proxy/nginx.conf`):**

```nginx
# mevcut platform-web-nginx YERİNE bu çalışacak
events { worker_connections 1024; }

http {
  # Prod upstream
  upstream prod_k3d { server 127.0.0.1:30080; keepalive 32; }
  upstream test_k3d { server 127.0.0.1:31080; keepalive 32; }

  server { listen 80; return 301 https://$host$request_uri; }

  # ai.acik.com → prod cluster
  server {
    listen 443 ssl http2;
    server_name ai.acik.com;
    ssl_certificate     /etc/nginx/tls/wildcard-acik-com.crt;
    ssl_certificate_key /etc/nginx/tls/wildcard-acik-com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
      proxy_pass http://prod_k3d;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Real-IP $remote_addr;
    }
  }

  # testai.acik.com → test cluster
  server {
    listen 443 ssl http2;
    server_name testai.acik.com;
    ssl_certificate     /etc/nginx/tls/wildcard-acik-com.crt;
    ssl_certificate_key /etc/nginx/tls/wildcard-acik-com.key;
    location / { proxy_pass http://test_k3d; ... }
  }
}
```

**Node mimarisi diyagramı:**

```
┌──────────────────── staging-sw HOST (4vCPU/24GB/200GB) ──────────────────────┐
│                                                                                │
│  ┌── Host nginx SNI proxy (Docker Compose) ──┐                                 │
│  │  :80  → redirect 443                       │                                 │
│  │  :443 → SSL termination (Sectigo wildcard) │                                 │
│  │         SNI routing:                       │                                 │
│  │         ai.acik.com   → 127.0.0.1:30080    │                                 │
│  │         testai.acik.com → 127.0.0.1:31080    │                                 │
│  └────────────────────────────────────────────┘                                 │
│         │                          │                                            │
│         ▼                          ▼                                            │
│  ┌─ k3d cluster: prod ──┐   ┌─ k3d cluster: test ─┐                            │
│  │  API :127.0.0.1:6443 │   │  API :127.0.0.1:7443 │                            │
│  │  Ingress HTTP :30080  │   │  Ingress HTTP :31080  │                            │
│  │                       │   │                       │                            │
│  │  NS:                  │   │  NS:                  │                            │
│  │  ├─ kube-system       │   │  ├─ kube-system       │                            │
│  │  ├─ calico-system     │   │  ├─ calico-system     │                            │
│  │  ├─ ingress-nginx     │   │  ├─ ingress-nginx     │                            │
│  │  ├─ external-secrets  │   │  ├─ external-secrets  │                            │
│  │  ├─ argocd            │   │  └─ platform-test     │                            │
│  │  ├─ monitoring        │   │     (workload r=0     │                            │
│  │  │    (test'i de      │   │      default)         │                            │
│  │  │     scrape eder)   │   │                       │                            │
│  │  └─ platform-prod     │   │                       │                            │
│  │     (backend+openfga  │   │                       │                            │
│  │      +frontend)       │   │                       │                            │
│  └───────────────────────┘   └───────────────────────┘                            │
│         │                          │                                            │
│         │                          │                                            │
│  ┌─ Host Compose (K8s dışı) ────────────────────────────────┐                   │
│  │  PROD: postgres :5432, keycloak :8081, vault :8200       │                   │
│  │  TEST: postgres :5433, keycloak :8082, vault :8201       │                   │
│  │        (test yoğun saatlerde kapalı — toggle script)     │                   │
│  └──────────────────────────────────────────────────────────┘                   │
└────────────────────────────────────────────────────────────────────────────────┘

Cluster içinden host-level servisler:
  Service+Endpoints (IP pin) → 10.9.10.53:<port>

ArgoCD multi-cluster:
  prod cluster'daki ArgoCD hem in-cluster hem "test-cluster" context ile deploy eder
  Test cluster'ı scrape: Prometheus federate / remote_write veya service discovery

Docker network ayrımı:
  platform-prod-net ≠ platform-test-net (Docker bridge ayrı)
  Pod CIDR ayrı (10.42 vs 10.44), Svc CIDR ayrı (10.43 vs 10.45)
```

**Calico seçimi (her iki cluster'da):**
- Flannel NetworkPolicy desteklemez
- `tigera-operator` minimal kurulum (tek node için `Installation.spec.nodeSelector` ile)
- **Test cluster'da Typha skip** (tek node için gereksiz, ~150 MB tasarruf)

**ArgoCD multi-cluster kayıt:**
```bash
# prod cluster'da ArgoCD kurulu
kubectl --context k3d-prod apply -f argocd/install.yaml
# test cluster'ı ArgoCD'ye tanıt
argocd cluster add k3d-test \
  --kubeconfig ~/.kube/config \
  --name test-cluster \
  --project platform
# Application'lar `destination.name: test-cluster` ile test'e gider
```

### 2.6 GitOps Akışı

```
Developer                 platform-k8s-gitops           ArgoCD                k3s cluster
    │                           │                          │                       │
    ├── kustomize edit ────────>│                          │                       │
    │                           │                          │                       │
    │   git commit + push ─────>│                          │                       │
    │                           │<─── poll (3 min) ────────┤                       │
    │                           │                          │                       │
    │                           │─── manifest diff ───────>│                       │
    │                           │                          ├── kubectl apply ─────>│
    │                           │                          │                       │
```

---

## 3. Dizin Yapısı

```
platform-k8s-gitops/
├── PLAN.md                     # Bu dosya (son durum + yol haritası)
├── README.md                   # Repo amacı, bootstrap, nasıl başlatılır
├── .gitignore                  # secrets, .env, state, .DS_Store
│
├── kustomize/
│   ├── base/                   # Ortam-bağımsız manifest'ler
│   │   ├── host-services/      # ExternalName Service + Endpoints (PG/KC/Vault köprüsü)
│   │   ├── authz/
│   │   │   └── openfga/        # StatefulSet + Service + migrate Job
│   │   ├── apps/
│   │   │   ├── discovery-server/
│   │   │   ├── user-service/
│   │   │   ├── auth-service/
│   │   │   ├── variant-service/
│   │   │   ├── core-data-service/
│   │   │   ├── report-service/
│   │   │   ├── schema-service/
│   │   │   ├── permission-service/  # NOT: zanzibar-openfga.v1.json kuralı — legacy, yeni kullanım yok
│   │   │   └── api-gateway/
│   │   ├── frontend/           # nginx + MFE shell
│   │   └── monitoring/         # ServiceMonitor CR'ları
│   └── overlays/
│       ├── local/              # k3d — image: Never, ingress: *.localtest.me
│       ├── test/               # platform-test ns — ingress: testai.acik.com (path-based)
│       └── prod/               # platform-prod ns — ingress: ai.acik.com (path-based)
│
├── helm-values/                # 3. parti chart values
│   ├── ingress-nginx/           # values-prod.yaml, values-test.yaml
│   ├── external-secrets/        # (DEFER — Vault auth sonrası)
│   ├── argocd/                  # prod cluster only (multi-cluster yönetir)
│   ├── kube-prometheus-stack/   # prod cluster only
│   ├── loki/                    # prod cluster only
│   ├── promtail/                # DaemonSet, prod cluster
│   └── tempo/                   # prod cluster only
│   # NOT: cert-manager YOK (D8/D18: TLS host nginx'te)
│
├── host-compose/               # Sunucu host-level Docker Compose
│   ├── env/                    # .env örnekleri (gerçek .env git-ignored)
│   ├── vault/
│   │   ├── test/docker-compose.yml
│   │   └── prod/docker-compose.yml
│   ├── keycloak/
│   │   ├── test/docker-compose.yml
│   │   └── prod/docker-compose.yml
│   └── state/                  # volume mount noktaları (git-ignored)
│       ├── test/
│       └── prod/
│
├── argocd/
│   └── applications/           # ArgoCD Application CR'ları (app-of-apps)
│       ├── root.yaml           # app-of-apps kök
│       ├── platform-test.yaml
│       ├── platform-prod.yaml
│       └── platform-system.yaml
│
└── docs/                       # (ileride) runbook'lar, diagram'lar
```

---

## 4. Faz Yol Haritası

### Faz 0 — Ön Hazırlık ✅ TAMAMLANDI
- [x] İskelet dizin ağacı
- [x] `git init` (bu repoda)
- [x] Karar kilitleme (bu PLAN.md)

### Faz 1 — Repo Temeli
- [ ] `README.md` — repo amacı + bootstrap komutları
- [ ] `.gitignore` — secrets, state/, .env, .DS_Store
- [ ] İlk commit: "initial plan + skeleton"
- [ ] **DNS ticket**: sysadmin'e `testai.acik.com` A → `10.9.10.53` kaydı için talep (Windows AD DNS)
- [ ] **Opsiyonel quick-win**: mevcut compose `platform-web-nginx`'i Vault self-signed'dan Sectigo wildcard cert'e geçir (K8s öncesi tarayıcı uyarısını kapat)

### Faz 2 — Host-Level Servisler (Docker Compose)
- [ ] `host-compose/vault/test/docker-compose.yml` + `prod/`
- [ ] `host-compose/keycloak/test/docker-compose.yml` + `prod/`
- [ ] `host-compose/env/vault.env.example`, `keycloak.env.example`
- [ ] PostgreSQL: mevcut compose'daki konfig referans alınacak (`backend/docker-compose.yml` → postgres-db servisi)
- [ ] **Kabul kriteri:** test+prod için 6 container (2x PG, 2x KC, 2x Vault) host'ta ayağa kalkıyor, port çakışması yok

### Faz 3 — Cluster Platform (Helm values + 2 k3d kurulumu)

**Cluster setup:**
- [ ] `bootstrap/k3d-prod.yaml` — prod cluster config
- [ ] `bootstrap/k3d-test.yaml` — test cluster config
- [ ] `bootstrap/setup-clusters.sh` — `k3d cluster create --config k3d-prod.yaml && k3d cluster create --config k3d-test.yaml`
- [ ] `bootstrap/install-calico.sh` — tigera-operator her iki cluster'a apply
- [ ] `host-compose/proxy/` — host-level nginx SNI proxy Compose + nginx.conf + TLS volume

**Platform bileşenleri (prod cluster):**
- [ ] `helm-values/ingress-nginx/values.yaml` — **prod**: HTTP-only (TLS host'ta), hostPort 30080
- [ ] ~~wildcard cert Secret bootstrap in cluster~~ **DEĞİŞTİ**: TLS host nginx'te, cluster içinde cert Secret'a gerek YOK
- [ ] ~~`helm-values/cert-manager/values.yaml`~~ **DEFER**
- [ ] `helm-values/external-secrets/values.yaml` + Vault ClusterSecretStore (prod Vault URL)
- [ ] `helm-values/argocd/values.yaml` (SSO ile Keycloak bağlantısı; path prefix `/argocd`, multi-cluster için tek instance)
- [ ] `helm-values/kube-prometheus-stack/values.yaml` (Grafana path prefix `/grafana`, Prometheus `/prometheus`, test cluster'ı scrape federate)
- [ ] `helm-values/loki/values.yaml`
- [ ] `helm-values/tempo/values.yaml`

**Platform bileşenleri (test cluster — minimal):**
- [x] `helm-values/ingress-nginx/values-test.yaml` — **test**: HTTP-only, hostPort 80/443 (k3d-test 31080:80 map)
- [ ] `helm-values/external-secrets-test/values.yaml` + Vault ClusterSecretStore (test Vault URL)
- [ ] ArgoCD YOK (prod cluster uzaktan yönetecek)
- [ ] Monitoring YOK (prod cluster'dan scrape)

**ArgoCD multi-cluster kayıt:**
- [ ] `argocd cluster add k3d-test --name test-cluster --project platform`

**Kabul kriteri:** 
- İki k3d cluster ayakta, `kubectl get nodes` her ikisinde çalışır
- Host nginx SNI proxy 443'ü alır, `ai.acik.com` prod cluster'a, `testai.acik.com` test cluster'a yönlendirir (dummy backend ile test)
- Prometheus test cluster'ı federate edebiliyor (`up{job="test-federate"}` metriği var)

### Faz 4 — Kustomize Base: Host Service Köprüleri
- [ ] `kustomize/base/host-services/postgres-svc.yaml` (Service + Endpoints, D19 — IP pin `10.9.10.53`, ExternalName kullanılmaz)
- [ ] `kustomize/base/host-services/keycloak-svc.yaml`
- [ ] `kustomize/base/host-services/vault-svc.yaml`
- [ ] `kustomize/base/host-services/kustomization.yaml`
- [ ] **Kabul kriteri:** k3d'den `kubectl exec` ile busybox pod'dan `nc -vz postgres.svc 5432` bağlanır

### Faz 5 — Kustomize Base: OpenFGA
- [x] StatefulSet (1 replica, migrate InitContainer) — `kustomize/base/apps/openfga/` (NOT: PLAN eski `authz/openfga/` dizin şeması YANLIŞ)
- [x] Service (**8080/8081/3000** — NOT: PLAN eski 4000/4001 YANLIŞ; gerçek portlar 8080 gRPC/HTTP, 8081 mgmt, 3000 playground)
- [ ] Secret → ExternalSecret (Vault'tan `OPENFGA_STORE_ID`, `OPENFGA_MODEL_ID`) — şu an stub, ESO S2 iş
- [x] migrate Job (Helm hook benzeri) — init container pattern
- [x] **Kabul kriteri:** k3d'de openfga ayaklanır ✅ (S0 recovery 2026-04-17 sonrası 9/9 Ready)
- **S1 (2026-04-19) FIX:** `ERP_OPENFGA_ENABLED=true` ConfigMap'e caller servisler (auth/user/variant/core) için eklenmeli — default=false Zanzibar enforcement'ı kapalı bırakıyor (S1-C10-13)

### Faz 6 — Kustomize Base: Backend Apps (şablon + çoğaltma)
- **S1 (2026-04-19) FIX:** `permission-service` manifest seti yazılacak (S1-C1..C8), base kustomization include (S1-C9), caller ConfigMap'lere `ERP_OPENFGA_*` + `PERMISSION_SERVICE_BASE_URL` patch (S1-C10..C13), overlay test+prod immutable tag `sha-3923901` (S1-C14-15). Dil 1+2 Zanzibar-25'te kapandı (`d6e0aa8b` + `fb3a94bc`), permission-service gap bugün kapanacak.
- [ ] `user-service/` — şablon olarak tam yaz (Deployment, Service, ConfigMap, ~~HPA~~ (D21 — MVP'de yok), PDB, ServiceMonitor, NetworkPolicy, ExternalSecret)
  - Resource: `requests: 256Mi/150m, limits: 512Mi/750m`, JVM `-Xmx384m` (prod) / `-Xmx256m` (test overlay). **`-XX:MaxRAMPercentage` kullanılmaz** (D24)
  - Replica: prod 2 sabit (D21), test 0 default (D17) / 1 açıldığında
- [ ] `auth-service/`, `variant-service/`, `core-data-service/`, `report-service/`, `schema-service/` — copy+edit
- [ ] `permission-service/` — **AKTIF** (2026-04-17 düzeltme): Zanzibar D-003 FINAL "TRANSFORMED — OpenFGA authorization hub (kaldırılmayacak)" kararı gereği. Eski "SKIP" satırı Codex ref CNS-20260411-001 ile çelişiyordu. Yazılacak: Deployment (port 8084 app), Service (`port: 8090, targetPort: 8084`), ConfigMap (DB + Keycloak + OpenFGA env'leri), ExternalSecret (PG + JWK creds), NetworkPolicy (auth/user/variant/core/report caller'lardan ingress), ServiceMonitor. **Prerequisite:** platform-ssot'ta `permission-service/src/main/resources/application-k8s.yml` YOK → Faz 11'de yazılmalı (Eureka kaldır, actuator expose, JVM heap, no-hardcoded-namespace). Auth-service K8s profile hardcoded `platform-prod` namespace'i de `PERMISSION_SERVICE_BASE_URL` env-driven olacak.
- [ ] ~~`discovery-server/` (Eureka)~~ **SKIP** (D7 revize: K8s native DNS kullanılacak)
- [ ] `api-gateway/` — en son, route'lar + rate limit config
  - Route hedefleri: `lb://user-service` → `http://user-service.platform-prod.svc.cluster.local:8089` (Eureka URI'leri svc URL ile değişir)
- [ ] **Kabul kriteri:** k3d'de api-gateway'den `/actuator/health/readiness` 200 döner, **tüm servis-arası çağrılar K8s svc DNS üzerinden çalışır** (curl `http://user-service.platform-test.svc.cluster.local:8089/actuator/health` test pod'undan)

### Faz 7 — Kustomize Base: Frontend
- [ ] nginx Deployment (MFE shell + remote'lar için path mapping)
- [ ] ConfigMap (nginx.conf — MF resilience için cache header'lar)
- [ ] Service
- [ ] **Kabul kriteri:** k3d'de shell açılır, remote'lar yüklenir, white screen yok

### Faz 8 — Kustomize Base: Monitoring
- [ ] ServiceMonitor CR'ları (her Spring Boot servisi için `/actuator/prometheus`)
- [ ] PrometheusRule'lar (mevcut `backend/infra/observability/alerts/` dosyalarından port)
- [ ] Grafana dashboard ConfigMap'leri (JSON import)

### Faz 9 — Overlay'ler
- [ ] `overlays/local/` — k3d için
  - image pull policy: Never
  - ingress: `*.localtest.me` (RFC2606 local-test domain)
  - replica: 1
  - resources: minimum
- [x] `overlays/test/` — platform-test ns
  - image: **digest pin** (D26 + Codex Tur-4; CI sha256 ile günceller)
  - ingress host: `testai.acik.com` (path-based), **TLS host nginx'te D18** (cluster Secret yok)
  - **replica: 0 (scale-to-zero default, D17)** — `test-toggle.sh up` ile 1'e çekilir
  - ResourceQuota: 3Gi/1vCPU (PLAN §2.4)
- [x] `overlays/prod/` — platform-prod ns
  - image: **digest pin** (CI günceller, ArgoCD Image Updater KULLANILMIYOR — D27 YAPMA listesi dışı)
  - ingress host: `ai.acik.com` (path-based), **TLS host nginx'te D18**
  - replica: 2 sabit (D21: HPA yok)
  - PDB: minAvailable 1

### Faz 10 — ArgoCD Applications
- [ ] `argocd/applications/root.yaml` — app-of-apps kök
- [ ] `argocd/applications/platform-system.yaml` — helm-values içeriğini sync eder
- [ ] `argocd/applications/platform-test.yaml` — `overlays/test/` sync
- [ ] `argocd/applications/platform-prod.yaml` — `overlays/prod/` sync (manual sync!)
- [ ] **Kabul kriteri:** ArgoCD UI'da 4 application healthy + synced

### Faz N — Image Digest Auto-Sync (Renovate)

> **Tetikleyici**: D36 kararı (2026-04-29 D35-3 closure flow gözlemi). Manuel digest pin sync pattern (Faz 21.3 PR #221/#226/#242 ardışık) Renovate ile otomatize edilir. D27 uyumlu (community-standard tool); D30 atomic cutover discipline korunur (prod overlay PR-only manuel review).

- [ ] `.github/renovate.json` config:
  - `regexManagers` → `kustomize/overlays/{test,prod}/kustomization.yaml` içindeki `digest: sha256:...` pattern'ini target et
  - `datasourceTemplate: docker` + `depNameTemplate: ghcr.io/halildeu/<service>` per service mapping
  - `schedule` → cron (örn. her 30dk poll GHCR)
- [ ] Renovate GitHub App kur (Halildeu/platform-k8s-gitops repo'suna PR yetkisi)
- [ ] **Test overlay PR pattern**:
  - PR title: `chore(deps): update permission-service digest sha-XXXXX → sha-YYYYY`
  - Boundary block auto-fill: `state-mutation (test cluster)` checked, no label
  - Auto-merge: false (CI checks + reviewer approval gerek; BG-1 hard gate yine geçerli)
- [ ] **Prod overlay PR pattern**:
  - Aynı PR pattern, ama `state-mutation (production)` checked + `user-approval-required` label otomatik eklenir
  - Manuel reviewer approval mandatory (D30 atomic cutover discipline)
  - Merge sadece D30 cutover decision sonrası
- [ ] **BG-1.1 dependabot coverage** ile aynı pattern: Renovate `pull_request_target` workflow tetikler, boundary declaration validate edilir
- [ ] **Kabul kriteri**:
  - 1 frontend image build (örn. sha-XXXX) → Renovate test overlay PR otomatik açar (~30dk içinde)
  - PR boundary block valid + CI yeşil
  - Reviewer approve sonrası merge
  - Operator/agent test cluster rollout
  - **3+ ardışık otomatik PR** drift sıfır kanıt (DD-style guard)
- [ ] **Cleanup post-Renovate**: PLAN.md line 810 "CI günceller" iddiası fiili durum ile eşleşir; D36 implementation tamam.

### Faz 11 — Ana Repo Paralel İş (`autonomous-orchestrator`)
Bu repo'da DEĞİL, ana repo'da yapılacaklar. Manifest yazımıyla eş zamanlı ilerler.

- [ ] Her backend servise `src/main/resources/application-k8s.yml` profili
  - **Eureka kaldırma**: `spring.cloud.discovery.enabled=false`, `eureka.client.enabled=false` (default)
  - Actuator: `management.endpoints.web.exposure.include=health,prometheus,info`
  - `management.endpoint.health.probes.enabled=true` (startup/liveness/readiness ayrımı)
  - JVM: `JAVA_TOOL_OPTIONS=-Xmx384m` (prod) / `-Xmx256m` (test). `MaxRAMPercentage` **KULLANILMAZ** (D24 + Codex Tur-4)
- [ ] **Eureka temizliği — DİLİMLİ** (D7, Codex onayı):
  - **Dilim 1 (PoC, D25)**: `api-gateway + auth-service`
    - `auth-service`: `@EnableEurekaClient` kaldır, `@LoadBalanced` client yok
    - `api-gateway`: route `lb://auth-service` → `http://auth-service.platform-prod.svc.cluster.local:8088`
    - Smoke: gateway üzerinden `/auth/actuator/health` 200, e2e Keycloak login
  - **Dilim 2**: `+ user-service` (aynı desen)
  - **Dilim 3+**: kalan backend'ler bağımlılık grafına göre
  - **pom.xml temizliği her dilimde**: `spring-cloud-starter-netflix-eureka-client` dependency kaldırılır
  - `discovery-server` modülü: **tüm filo K8s'e geçtikten sonra** arşivlenir (geçici K8s Eureka YOK — D26)
  - Geçici `EUREKA_ENABLED=false` env var kullanılmaz — annotation ve dependency tamamen temizlenir
- [ ] Dockerfile güncelleme: non-root user + USER direktifi
- [ ] `decisions/topics/kubernetes-migration.v1.json` — ADR yaz (Eureka kaldırma + capacity strategy + path-based ingress)
- [ ] `docs/OPERATIONS/INFRASTRUCTURE-ENVIRONMENTS.md` güncelleme (K8s ortamı eklenir)
- [ ] `scripts/doctor-k8s.sh` — K8s için health check script'i (mevcut `doctor-infra.sh` paralel)

### Faz 12 — Lokal Doğrulama (k3d)
- [ ] `k3d cluster create platform --config <...>` komutu dokümante
- [ ] Tam E2E: ingress → gateway → servisler → openfga → host-PG bağlantı
- [ ] MFE shell + remote'lar çalışır
- [ ] Grafana'da metrikler akıyor

### Faz 13 — Staging (staging-sw) Deploy
- [ ] k3s cluster hazırlığı (staging-sw'de)
- [ ] Host-level PG/KC/Vault Compose kurulumu (test+prod paralel)
- [ ] `kubectl apply -k kustomize/overlays/test/` → platform-test
- [ ] Smoke testleri: `.github/workflows/smoke-zanzibar.yml` paralel K8s versiyonu
- [ ] 1 hafta staging gözlem

### Faz 14 — GitHub Remote + ArgoCD Bağlama
- [ ] `gh repo create halildeu/platform-k8s-gitops --private`
- [ ] `git push -u origin main`
- [ ] ArgoCD repo credential (deploy key)
- [ ] ArgoCD `root.yaml` apply → app-of-apps devreye

### Faz 15 — Production Cutover
- [ ] Blue/green: mevcut compose prod = blue, k3s prod = green
- [ ] DNS traffic kaydırma (%10 → %50 → %100)
- [ ] Rollback planı: compose prod 72 saat ayakta kalır
- [ ] Compose decommission (2 hafta sonra)

---

### Faz 16 — Source Data Migration (MSSQL → PG)

**Kapsam**: Rapor + şema gezgini kaynağı `Workcube Mikrolink ERP` MSSQL (`10.9.193.201:1433/workcube_mikrolink`) → PG canonical (`reports_db`, `schemas_db`). ADR-0002 D31 **PG primary, MSSQL secondary/opsiyonel** kontratının veri-gerçekliği boşluğunu kapatır.

**Yürütme penceresi**: Faz 15 T+72h rollback-window kapanışı sonrası (≥ 2026-04-27 01:25 UTC+3). 2-3 hafta süre (single dev), 1-2 hafta (paralel team).

#### Faz 16.2.A — Scope Anchor Load (D35-1 prereq) — DR-6 (ADR-0010)

**Karar tarihi**: 2026-04-28 (Codex thread `019dd2c9` xhigh effort verdict, ADR-0010 §2.4).

**Durum**: AÇIK — operator-driven. Runbook: `docs/RB-faz-16-2-A-scope-anchor-load.md`.

**Amaç**: D35-2 first canlı evidence'ı açabilmek için `workcube_mikrolink.our_company`'ye **minimum 1 gerçek Workcube OUR_COMPANY row**'u ETL ile yüklemek. Sentetik fixture YASAK (Kural #9 + 2026-04-26 mandate); gerçek Workcube source path zorunlu.

**2026-04-28 V25 update** (Codex `019dd34e` + PR #213 V25 migration): anchor table V19/V20/V21 yanlışlıkla `COMPANY` (80,246 row directory) seçmişti. V25 migration `OUR_COMPANY` (42 row tenant boundary) anchor'ına geçti. Faz 16.2.A runbook + tables.yaml + ADR-0008 object id encoding tüm `OUR_COMPANY`/`wc-our-company-<COMP_ID>` ile hizalandı. Bu Fazın hedef tablosu artık OUR_COMPANY.

**Kapsam (sıkı subset)**:
- Sadece canonical schema `workcube_mikrolink` (parametric `workcube_mikrolink_<year>` değil).
- Sadece `COMPANY` tablo (D35 anchor table; diğer 3 anchor — `pro_projects`, `branch`, `department` — D35-2/3 onları gerektiğinde follow-up).
- Minimum row: 1 (AÇIK org'un Workcube COMPANY satırı).
- Mevcut `etl_worker` üstüne dar profil; YENİ ETL stack DEĞİL.

**Ürettiği D35-1 evidence** (per `docs/d35-evidence-template.md`):
- `migration_audit.migration_runs` row (mode=initial, status=SUCCESS, rows_loaded>=1, rejected=0)
- Reconcile MATCH artifact (`docs/migration/reconcile-<run-id>.{md,json}`)
- `data_access.organization_company` mapping AÇIK org → real source_pk
- `workcube_mikrolink.our_company.source_pk` örnek (= COMP_ID lineage; DR-7 SCOPE_REF olarak kullanır, format `["1"]`/`["2"]`/etc per ADR-0008)

**Bağımlılıklar (üst akış)**: V16+V17+V19+V20+V21+V22+V23 reports_db'ye applied (2026-04-28 outbox preflight'da tamamlandı, `current-state.md`).

**Bağımlılıklar (alt akış)**: DR-7 (D35-2 first canlı evidence) bu Fazın çıktı `source_pk`'sini kullanır.

**Operator approval gate** (per ADR-0010 §2.5): Step 2 "Live load" = first canlı Workcube row movement → user onay zorunlu.

**Faz 16.2.P ile ilişki**: Faz 16.2.P parametric ETL **defer kalır**. 16.2.A onun içinde **değil**, ondan **bağımsız dar bir prereq**. Drift guard'lar (sentetik fixture yasağı) korunur.

**Codex thread**: `019dd2c9` (xhigh, ADR-0010 input).

#### Faz 16.2.P — Parametric (multi-tenant + yearly schema) ETL — DEFERRED INDEFINITELY

**Karar tarihi**: 2026-04-26 (Codex thread `019dc88c` iter-4 AGREE).

**Durum**: Defer edildi. Yeniden başlatma şartı:
- (a) canlı MSSQL üzerinde **ölçülebilir analitik performans baskısı**, ya da
- (b) MSSQL **decommission timeline** netleşmesi.

**Rasyonel** (Codex iter-4 dili):
> Canlı raporlar halen MSSQL authoritative path kullanıyor (`testai.acik.com/admin/reports/...` → `report-service` doğrudan MSSQL NTLM). Parametric ETL'in şu anki ek değeri perf/decommission baskısı olmadan sınırlı; agent tarafında read-only / no-admin auth boundary nedeniyle crawler işi kullanıcı içi operasyon olarak kalır. 17 parametric × ~25 tenant × N yıl = potansiyel ~1275+ instance — ürün değerine göre fazla pahalı.

**Kapsam dışına alınanlar** (Codex iter-2/iter-3 plan-time çıktıları arşivde):
- 17 parametric tablo crawl (composite tenant + year axis)
- `source_axis_key` + `source_year_bucket NOT NULL` partition design
- V18 parametric DDL generator extension
- Manifest `source_instances` enrichment
- Runner parametric expansion (1 manifest entry → N TableMeta)
- ~~Schema-service yearly-schema crawl tool~~ — **EXCLUDED'dan kaldırıldı 2026-05-15** (Codex thread `019e2c59` iter-3 revize): mevcut `schema-service` `/api/v1/schema/schemas` ve `/api/v1/schema/snapshot?schema=<name>` endpoint'leri **canlı parametric schema crawl** sağlıyor (319+ schema: canonical + 43 tenant-only + 276 year-tenant). Ayrı yearly-schema crawl tool yazmaya gerek yok; Annex 2A SEAL validation bu endpoint'ler üzerinden 8/8 PASS oldu (PR #680). Parametric ETL pipeline (source_axis_key, partition, V18 generator, runner expansion) hâlâ deferred kalır — sadece schema discovery layer'ı zaten mevcut.

**Korunan Faz 16 kapsamı (canonical only)**: 23 master-data tablosu Day 6+7+hotfix ile DONE. PR #157 (Day 6 audit/retry), #158 (Day 7 orchestrator+reconcile), #159 (Day 7 live smoke hotfix). Mac dev-pg smoke `VERDICT MATCH`, `checksum_pg = checksum_mssql`, idempotent upsert kanıtlı (`docs/migration/reconcile-20260426-1b4f8397-smoke-dev-pg.{md,json}`).

**Agent davranış kuralı (CLAUDE.md drift guard)**:
- Sentetik 17-tablo fixture işine TEKRAR BAŞLAMA (kural #9 ihlali olarak silindi).
- Agent sandbox içinden canlı parametric schema crawl TASARLAMA/KOŞTURMA.
- Bu Faz yeniden açılırsa: yeni Codex iter ile başla, mevcut iter-3 REVISE bulgularını (composite axis + partition PK + explicit_allowlist_required) absorb et.

**Codex adversarial review**: thread `019dbe1d` (ilk REVISE) → `019dbe1f` (PARTIAL) → `019dbe21` (PARTIAL) → `019dbe22` **AGREE** (with 15 dk rollback trigger edit).

**Faz adı önemli**: "Source-Read Cutover / MSSQL-off Switch" — Production Cutover (Faz 15) **değil**. Faz 15 Hybrid GO zaten canlıda kontratlı.

#### 16.0 — Data Contract (ETL öncesi sabitlenmeli)

- Her MSSQL tablosu: `authoritative` / `cache-reference` / `skip` kategorisi
- Idempotency key (natural PK veya surrogate)
- **Type mapping matrisi**:
  - `nvarchar(N)` → `VARCHAR(N)` (collation: PG `C.UTF-8`)
  - `nvarchar(MAX)` → `TEXT`
  - `datetime2` → `TIMESTAMPTZ` (UTC canonical, app-side timezone convert)
  - `decimal(N,M)` → `NUMERIC(N,M)` (precision korunur)
  - `bit` → `BOOLEAN`, `uniqueidentifier` → `UUID`
- **Collation**: MSSQL `Turkish_CI_AS` → PG `C.UTF-8` + `CITEXT` case-insensitive paritede mi? Kural per-column
- **Soft-delete semantics**: MSSQL `DELETED_FLAG` / `REVOKED_AT` → PG aynı kolon + query filter
- **FK load order**: Dependency graph → topological sort (önce parent sonra child)
- **NULL vs empty string**: MSSQL `''` kullanımı → PG `NULL` kural per-column
- **Unicode edge cases**: Surrogate pairs, emoji, BOM stripping
- **Write-freeze owner**: Workcube admin (operasyonel sahip, freeze 10-15 dk hedef)
- **Backup**: freeze öncesi MSSQL full backup (ERP side)
- Deliverable: `docs/migration/mssql-pg-data-contract.md`

#### 16.1 — Source Discovery (inventory)

- Tablo listesi + row count + data size + FK + index
- Kritik tablolar: `REPORTS`, `SAVED_REPORTS`, `custom_reports`, `PERMISSIONS`, `MODULES`, `USERS`
- Deliverable: `docs/migration/mssql-inventory.md`

#### 16.2 — PG Target Schema + Flyway (platform-ssot)

- Repo: **platform-ssot**
- `backend/report-service/src/main/resources/db/migration/V16__reports.sql`
- `backend/schema-service/src/main/resources/db/migration/V16__schemas.sql`
- Index strategy (PG'ye uygun; MSSQL'den farklı olabilir)
- Deliverable: Flyway PR (platform-ssot)

#### 16.3 — ETL Stand-Alone Worker

- **Stand-alone worker** (Python/Go), Spring Batch **değil** (runtime gömülü değil, blast radius daraltılır)
- Idempotent, retry-safe, batch cursor
- Source: `sqlcmd bcp export` + JDBC read fallback
- Target: `psql COPY` bulk
- Repo: **platform-ssot** (worker kodu) + **platform-k8s-gitops** (Job manifest `bootstrap/mssql-etl/`)
- Deliverable: `platform-ssot/backend/mssql-etl-worker/` + K8s Job manifest (tek-seferlik)

#### 16.3.5 — Reconciliation (gate)

- **Row count parity** (MSSQL vs PG)
- **Checksum/MD5** sütun-level (critical fields için)
- **Nullability parity**
- **Encoding parity** (nvarchar → text UTF-8)
- **Sample semantic diff** (ilk 100 row side-by-side)
- PASS/FAIL gate — FAIL ise 16.5 cutover yasak
- Deliverable: `docs/migration/reconcile-YYYYMMDD.md` + per-table PASS/FAIL

#### 16.4 — Delta Sync (varsayılan SKIP)

- CDC/poll-based continuous sync **açılmaz** (scope creep)
- Yalnız "final delta before cutover" (16.5 adımı 2)

#### 16.5 — Source-Read Cutover Sequence

**Adımlar**:
1. Source freeze window (ERP write durdur, Workcube admin owner)
2. Final delta import (16.3 worker tek-seferlik rerun)
3. 16.3.5 reconciliation PASS
4. Feature flag: `REPORT_MSSQL_ENABLED=false`, `SCHEMA_MSSQL_ENABLED=false`
5. Spring restart (`docker compose up -d --force-recreate report-service schema-service`)
6. Read-path kanıtı (rapor UI → PG)

#### 16.5.5 — Test-Authoritative Gate (prod öncesi ZORUNLU)

- `testai.acik.com` k3d-test cluster'da MSSQL-off functional kanıt
- Test PG'ye 16.3 ETL seed
- Test feature flag `*_MSSQL_ENABLED=false`
- Test smoke: rapor UI render + schema explorer + D29 3-katman PASS
- **Prod cutover 16.5 yürütme sadece testai MSSQL-off smoke PASS sonrası**

#### 16.5.X — Rollback Kontratı (açık)

**Tetikleyiciler**:
- 16.3.5 reconciliation fail
- 16.5 smoke fail
- **5xx error rate > %1 persistent (15 dk canonical)** (AGENTS.md canonical süre)
- ERP owner freeze-undo isteği

**Rollback süresi**: < 10 dk

**Re-enable adımları**:
1. `*_MSSQL_ENABLED=true` (compose env)
2. `docker compose up -d --force-recreate report-service schema-service`
3. Smoke: rapor/schemas UI → MSSQL live
4. current-state delta: "Faz 16 source-read cutover rolled back, re-attempt planı"

**Kritik**: Secret/network kaldırma (16.8) **yalnız rollback-window kapanışı sonrası**. Erken yapılırsa geri dönüş zor (Vault path silindiyse restore gerek).

#### 16.6 — Auditability

- Migration manifest (hangi tablo, row count, timestamp)
- Batch log (job start/end, per-table success/fail)
- Reject queue (`migration_rejects` table — PG constraint fail row'lar)
- Tekrar çalıştırılabilirlik kontrol
- Reject-row remediation: manuel review + fix + re-import
- Deliverable: `docs/migration/audit-log-YYYYMMDD.md`

#### 16.7 — Smoke + D29 3-Katman

- **Up**: PG DB accessible, Spring Boot UP
- **Functional**: rapor listesi + render + schema explorer UI
- **Zanzibar-ready**: scope-aware report access (admin vs canary-restricted farklı rapor seti)
- **Başarı kriteri**: MSSQL kapalıyken functional parity

#### 16.8 — MSSQL Decommission Aşamalı (her aşama ayrı PR)

- **Aşama 1** (feature-off): `*_MSSQL_ENABLED=false` → 16.5'te yapılır
- **Aşama 2** (env remove): Vault secret remove + compose env clean → 16.5 PASS + **7 gün gözlem** sonrası
- **Aşama 3** (network deny): `iptables DROP 10.9.193.201:1433` → Aşama 2 + **7 gün** sonrası
- **Aşama 4** (emergency erişim proc): Aşama 3 ile paralel doc — DR dry-run için 30 dk SLA geri-erişim
- **Aşama 5** (tam kesim + decommission): Aşama 3 + **30 gün gözlem** sonrası + ADR eklentisi

#### Repo Sınırı (Codex explicit)

| Repo | İçerik |
|---|---|
| `platform-ssot` | Flyway V16 SQL, entity mapping, ETL worker kodu, unit/integration test, MSSQL driver config |
| `platform-k8s-gitops` | K8s Job manifest (`bootstrap/mssql-etl/`), feature flag env, Vault path (secret remove), compose env, runbook (`docs/phase16-*`), current-state truth closure |

#### Bağlantılar

- ADR-0002 D31 (PG primary, MSSQL secondary)
- `PLAN.md:168-184` (Cutover Atomic Switch — Faz 15'te yapılmış)
- `docs/state/current-state.md` Session X delta (Faz 16 execute sonrası)
- Codex threads: `019dbe1d`, `019dbe1f`, `019dbe21`, `019dbe22` (AGREE)
- **16.0 Data Contract deliverable**: `docs/migration/mssql-pg-data-contract.md` (DRAFT/RFC, SEALED 16.1 inventory sonunda) — Codex thread `019dbe92` iter-4 AGREE

---

### Faz 17 — Local Dev Environment Parity

**Kapsam**: Mac geliştirici makinesi (lokal dev, `k3d-dev`, `platform-dev`, `*.localtest.me`) staging-sw runtime target'larından (`testai.acik.com` / `ai.acik.com`) ayrılır. Mevcut `overlays/local` yanlış `namespace: platform-prod` kullanımını düzeltir. Üç-tier promotion: **Lokal dev** (dev-smoke PASS) → **PR + CI render/lint** → **testai.acik.com** (D29 3-katman) → **prod approval** → **ai.acik.com**.

**Yürütme penceresi**: Faz 16 16.0 ile **tam paralel**; 16.1+ ETL lokal e2e testi isterse 17.X TLS + 17.1 fixtures + 17.2 Tilt **blocker olur**. Effort: 2-3 iş günü (single dev).

**Codex adversarial review**: MCP thread `019dbe80` — iter-1 REVISE (2 RED absorb) → iter-2 PARTIAL → iter-3 PARTIAL → **iter-4 AGREE**.

**Faz adı önemli**: "Local Dev Environment Parity" — prod/test overlay değişikliği **değil**. Hedef: lokal 5 dk fonksiyonel stack, prod secret/Vault/KC'ye sıfır bağımlılık.

#### 17.0 — Naming + Namespace + Image Handoff

- Cluster: Mac lokal `k3d-dev` (eski `k3d-prod` YASAK — staging-sw ile çakışır)
- Namespace: `platform-dev` (overlay'de `platform-prod` kullanımı kaldırılır)
- Domain: `*.localtest.me` (RFC2606, 127.0.0.1 resolve) veya `dev.local` (/etc/hosts)
- `bootstrap/k3d-dev.yaml` (portlar `32080/32443` high-port, network `platform-dev-net`)
- **Image handoff**: `k3d image import` default, `registry.localhost:5000` opt-in (hızlı rebuild)
- Deliverable: `bootstrap/k3d-dev.yaml` + overlays/local-* namespace patch + `docs/local-dev-image-contract.md`

#### 17.1 — Fake Fixtures Seed (Vault token git'e YOK)

- **Fake fixtures** (git-committed, `NOT_FOR_PROD` header): `bootstrap/local-fixtures/` — PEM (openssl rsa:2048), fake KC realm JSON, OpenFGA tuple sample, PG fixture SQL
- **Vault dev-mode opsiyonel** (`full` profile): deterministic `-dev-root-token-id=dev-root-token`, script `export VAULT_TOKEN=dev-root-token` (NEVER git, NEVER shared, NEVER CI)
- `authn-min` + `zanzibar-min`: ESO bypass — overlays/local-* inline Secret'ler (fake fixtures'tan seed)
- `.env.example` committed (no real credentials)
- Versioned seed deterministic: aynı `dev-seed.sh` = aynı PG/KC/OpenFGA state (drift yok)
- Deliverable: `bootstrap/local-fixtures/` + `.env.example` + `scripts/dev-seed.sh`

#### 17.2 — Local Dev Stack Scaffold (Tilt, ssot authoritative)

- **Tiltfile konumu**: `platform-ssot` (authoritative — Java/MFE kod watch + image build)
- Bu repo: Tiltfile **YOK**; ssot `k8s_yaml(kustomize('../platform-k8s-gitops/kustomize/overlays/local-$profile'))` ile tüketir
- Dev scripts (`dev-up/down/seed/smoke`): `platform-k8s-gitops` (cluster lifecycle owner)
- **Profile matrix** (D29 kontrat uyumlu):

| Profile | Workload count | Composition | D29 Gate |
|---|---|---|---|
| `authn-min` | **4** | api-gateway + auth-service + keycloak + postgres | Up + Functional (auth-only; Zanzibar kanıtı **YOK**) |
| `zanzibar-min` | **8** | authn-min + permission-service + user-service + variant-service + openfga | D29 3-katman FULL (Up + Functional + Zanzibar-ready) |
| `full` | **12** | 9-app deployment + openfga + keycloak + postgres | D29 + testai desen paritesi |

"Workload count" = Deployment + StatefulSet sayısı (Job/CronJob sayılmaz)

Deliverable: ssot/Tiltfile (cross-repo PR ref) + `docs/local-dev-tilt.md` + profile switch kontratı

#### 17.2.5 — App Base Split (runtime vs ops)

Mevcut `kustomize/base/apps/<svc>/kustomization.yaml` runtime + ES + ServiceMonitor tek bütün — CRD'siz lokal profile'da çalışmaz. Split:

```
kustomize/base/apps/<svc>/
  kustomization.yaml       ← runtime only: deployment + service + configmap
  ops/
    kustomization.yaml     ← ExternalSecret + ServiceMonitor
```

Overlay tüketim:
- **test/prod overlay**: `resources: [../base/apps/<svc>, ../base/apps/<svc>/ops]` (geriye uyum)
- **local-* overlay**: sadece `../base/apps/<svc>` (CRD bağımsızlığı)

**Parity sanity** = normalized semantic diff (raw byte diff **DEĞİL** — resource sırası varyansı izole edilir)

Deliverable: 9 app × ops/ split PR (18 dosya + overlay ref güncellemeleri)

#### 17.3 — Dev Scripts (profile-aware, idempotent)

- `scripts/dev-up.sh --profile authn-min|zanzibar-min|full` — cluster + ns + fixtures + TLS edge + Tilt
- `scripts/dev-down.sh` — tear-down (cluster + network + Tilt)
- `scripts/dev-seed.sh --profile X` — PG + KC realm + OpenFGA tuple fixtures (profile'a göre)
- `scripts/dev-smoke.sh --profile X` — 17.8 her profile için ayrı kapı
- Idempotent; yeniden çalıştırma state bozmaz; `:8081` internal helper için high-port (18081) kullan (çakışma önleme)

Deliverable: `scripts/dev-*.sh` + `docs/local-dev-runbook.md`

#### 17.4 — Promotion Contract Doc

`docs/promotion-contract.md` — 3-tier akış resmi. Her tier için tablo: domain, cluster, namespace, Vault scope, secret source, rollback kontratı. "Lokal PASS ≠ testai PASS ≠ prod PASS" — her tier bağımsız smoke gate.

Deliverable: `docs/promotion-contract.md`

#### 17.5 — Docs Update

- `README.md` — "Dev vs Test vs Prod" bölümü netleşir
- `CONTRIBUTING.md` — yeni katkı akışı: dev-up → kod → dev-smoke → PR
- `.env.example` referansı (17.1)

Deliverable: README + CONTRIBUTING güncellemeleri

#### 17.6 — Repo Split Decision (cross-repo ownership)

- ADR-0003 **opsiyonel** (overhead düşük)
- AMA authoritative ownership cümlesi **iki repoda birden** yazılır (unilateral yazım drift üretir)
- Cümle: "Inner-loop tooling (Tilt, code watch, image build) → `platform-ssot` authoritative. Env/smoke/scaffolding (`overlays/local-*`, `scripts/dev-*.sh`, fixtures) → `platform-k8s-gitops` authoritative. Değişirse her iki repo CONTRIBUTING senkron güncellenir."

Deliverable: bu repo doc + platform-ssot cross-PR referans

#### 17.7 — Migration from Current State (DROP "delete prod")

- `overlays/local/kustomization.yaml`: `namespace: platform-prod` → `platform-dev`; ConfigMap URL'ler `*.platform-prod.svc.*` → `*.platform-dev.svc.*`
- Comment: "k3d-prod (lokal)" → "k3d-dev (Mac developer)"
- Mac'te mevcut `k3d-prod`+`k3d-test` cluster'ları: **warn + stop (reversible)** — zaten Session 29'da stop edildi. `k3d cluster delete prod` **YAPMA** (gerekirse geliştirici manuel)
- `bootstrap/setup-clusters.sh` (şu an sadece prod|test) → `--dev` bayrağı veya ayrı `bootstrap/setup-dev-cluster.sh`
- Geliştirici rehberi: eski context'leri temizle (`kubectl config delete-context`)

Deliverable: overlay migration PR + migration runbook (1 sayfa) + setup-clusters.sh dev desteği

#### 17.8 — Smoke Criteria (profile-based gates, auth-only authn-min)

| Profile | Smoke Kapıları |
|---|---|
| `authn-min` | (a) External: `GET /realms/dev-local/.well-known/openid-configuration` → 200 + (b) Token mint `POST /realms/dev-local/protocol/openid-connect/token` → access_token + (c) Internal helper (port-forward): `:8081/actuator/health/readiness` → 200. **AUTHZ-gated endpoint'ler YASAK** (permission-service yok, chain patlar) |
| `zanzibar-min` | authn-min + (d) OpenFGA synthetic tuple check + (e) `/variants` scope-aware allow/deny (token'lı) |
| `full` | zanzibar-min + (f) frontend UI render (ssot MFE artifact) + (g) 9-app `/actuator/health/readiness` 200 |

Her profile için `dev-smoke.sh --profile X` exit 0 = PASS; fail → JSON stderr explanation.

Deliverable: `scripts/dev-smoke.sh` + PASS/FAIL kriterleri `docs/local-dev-runbook.md`

#### 17.X — Local Edge TLS (mkcert + Caddy)

- mkcert + Caddy lokal edge `https://app.localtest.me` (:443 sudo gerekirse, :8443 fallback **DEFAULT** — sudo istemez)
- Cookie `Secure=true` + `SameSite=None` parity (testai/prod davranışı)
- OIDC redirect flow HTTPS zorunlu (KC production-mode)
- **Route kontratı**: Caddy explicit proxy — `/realms/*` + `/resources/*` KC'ye direkt (ingress base'de bu rotalar yok, Caddy üstlenecek)
- High-port 32080/32443 k3d ingress arkada kalır; Caddy 443/8443 terminate eder

Deliverable: `bootstrap/local-edge/` (mkcert + Caddy config) + docs port seçim rehberi

#### 17.Y — Image Handoff Contract

- **Default**: Tilt `docker_build` + `k3d image import` (cluster-scope erişim, auto)
- **Alternatif**: lokal registry `registry.localhost:5000` (cluster'dan pull, daha hızlı rebuild replica)
- Trade-off: `k3d image import` basit ama yavaş iteratif build; registry karmaşık ama CI-benzeri

Deliverable: `docs/local-dev-image-contract.md` karar mühürler

#### 17.Z — CI Integration Split

- **Blocking PR CI** (her PR'da): `overlays/local-*` kustomize build + yaml-lint + shell-lint `scripts/dev-*.sh`
- **Non-blocking nightly/manual** (`workflow_dispatch`): tam k3d smoke (GitHub Actions runner'da k3d cluster + dev-up + dev-smoke `authn-min` MVP)
- Cross-repo integration (platform-ssot PR tetikleyen): `17.Z.1` ileri iş

Deliverable: `.github/workflows/local-overlay-lint.yml` (PR) + `.github/workflows/local-smoke-nightly.yml` (manual/nightly)

#### Repo Sınırı (Codex AGREE)

| Repo | İçerik |
|---|---|
| `platform-ssot` | **Tiltfile (authoritative)**, Dockerfile, Maven/Gradle build config, code watch patterns, image build logic |
| `platform-k8s-gitops` | `bootstrap/k3d-dev.yaml`, `overlays/local-*` (ns `platform-dev`), `scripts/dev-*.sh`, `bootstrap/local-fixtures/`, `bootstrap/local-edge/` (mkcert+Caddy), `docs/promotion-contract.md`, `docs/local-dev-runbook.md`, `docs/local-dev-image-contract.md`, CI workflows |

#### Bağlantılar

- ADR-0002 D31 (PG primary + single-host dual-cluster — lokal bozmaz)
- ADR-0003 (opsiyonel, 17.6 — inner-loop tooling ownership)
- `PLAN.md:844-849` Faz 12 "Lokal Doğrulama" — **Faz 17 superseded + modernize**; Faz 12:845 `k3d cluster create platform` artık tarihsel
- `kustomize/overlays/local/kustomization.yaml:1-9` (17.7 düzeltir)
- Faz 16 paralellik: 16.0 data contract tamamen paralel; 16.1+ ETL lokal e2e isterse 17.X TLS + 17.1 fixtures + 17.2 Tilt blocker
- Codex thread: `019dbe80` (iter-1 → iter-4 AGREE)

---

### Faz 18 — Compose Dependencies Retirement + Environment Independence

**Kapsam**: Compose stateless + cross-realm control-plane dependencies retirement. ADR-0002 D6 stateful tier (PG/KC/Vault compose) **korunur**; stateless compose + `platform-service-manager-1` Docker-socket control plane + `platform_microservice-network` legacy + `/api/services/` public debug route bitirilir. D34 yeni karar: runtime/state/secret independence 3-realm arası.

**Yürütme penceresi**: Faz 13 Hybrid GO canlı + rollback-window iptal sonrası. Faz 16 MSSQL migration'dan **bağımsız** (stateless compose MSSQL kullanmaz). Effort: 5-7 iş günü (13 sub-faz, cross-repo).

**Codex adversarial review**: thread `019dbfa5` — iter-1 VERDICT → iter-2 (scope daraltma user "mimari aynı") → **iter-3 AGREE** (3 guardrail: D34 PLAN kararı, 18.11 decision-capture + impl defer, 18.5-7 24h smoke yeterli). Ayrıca diğer repo AI değerlendirme absorb: environment independence contract + lokal k3d-dev smoke kanıtı + prod public debug route cleanup.

**Faz adı kritik**: "Compose Dependencies Retirement" (stateless + control plane) — ADR-0002 topoloji **değişmez** (staging-sw same-host dual-cluster korunur). D34 operasyonel boundary, mimari değil.

#### 18.0 — D34 Environment Independence Contract

Yeni karar satırı PLAN D-log:

**D34 (Accepted 2026-04-24)**: Lokal dev (Mac k3d-dev) + Ubuntu test (staging-sw k3d-test + testai) + Ubuntu prod (staging-sw k3d-prod + ai) **runtime/state/secret/control-plane bağımsız**. Paylaşılabilir: Git repo + CI artifact + immutable image digest + Kustomize base + runbook/docs. Paylaşılmaz: DB, KC realm, Vault path/AppRole, OpenFGA store/model, host nginx debug route, service-manager endpoint, MSSQL canlı bağlantı, runtime container/pod/volume.

ADR-0002 **aynı kalır** (topoloji değişmez; D34 operasyonel boundary).

Deliverable: `PLAN.md` D34 satır + `docs/promotion-contract.md` 3-realm runtime independence bölüm + `docs/state/current-state.md` D34 truth closure.

#### 18.1 — A0 Live Preflight (staging-sw)

Edge/upstream authoritative teyit + cross-realm canlı kanıt:

- `ssh staging-sw docker ps` full container listesi
- Edge nginx upstream: `/api/` (30443 K8s ✓), `/api/services/` (8795 compose DRIFT), `/realms/` (8081 compose KC — ADR-0002 D6 OK)
- `/api/auth/*` compose auth-service dependency teyit/red (canlı canlı curl + access log grep)
- K8s pod sayısı sabit (49 prod Running)
- Access log son 24h grep `/api/services/` (canlı consumer hit sayım)
- `docker inspect platform-service-manager-1` Docker socket mount confirm
- Frontend source: `ai.acik.com/` root → platform-web-nginx static kanıt
- `docs/phase18-evidence/a0-preflight-YYYYMMDD.md`

**Go/No-Go**: Tüm drift kanıtları + consumer count → Aşama 2'ye geç.

#### 18.2 — `/api/services/` Public Debug Route Tombstone (410 Gone)

Codex iter-3 kararı: 410 semantic doğru (resource permanently gone).

- Edge nginx `/api/services/` → `return 410 'Gone; replaced by ArgoCD/Grafana ops links'` JSON tombstone
- **Tombstone deprecation window**: 7 takvim günü + son 24h 0 hit → route tam silme
- `docs/phase18-evidence/service-endpoint-tombstone.md`

#### 18.3 — service-manager-1 Retirement (Cross-Repo)

Codex iter-3: 2 ayrı PR (web vs backend/deploy) blast radius orta.

**platform-ssot PR 1 (web)**:
- `web/apps/mfe-shell/src/pages/admin/service-control/` → kaldır
- `web/apps/mfe-shell/src/pages/home/widgets/ServiceHealthSummaryWidget.tsx` → "Ops Links" (ArgoCD/Grafana/runbook) replace
- `web/apps/mfe-shell/src/app/router/AppRouter.tsx` + `header-navigation.config.ts` + `Sidebar.tsx` + `chord-navigation.config.ts` → route/nav/shortcut cleanup
- Vite local dev plugin `service-health-api.ts` → **dev-only kalabilir** (Faz 17 local fixtures simetrik)

**platform-ssot PR 2 (backend/deploy)**:
- `backend/scripts/service-manager-api.js` → arşiv/silme
- `deploy/docker-compose.prod.yml` → platform-service-manager-1 blok kaldır
- `deploy/ubuntu/deploy-backend.sh` + `platform-start.sh` → service-manager invoke satır temizle

**platform-k8s-gitops PR (bu repo)**:
- `host-compose/web/nginx/default.conf` `/api/services/` route 410 tombstone
- 18.2 tombstone deprecation süresi sonunda route tam silme
- Evidence doc

#### 18.4 — Vault Ops Replacement — **COMPLETE (2026-04-24)**

- `platform-vault-snapshot-1` compose → retire ✓ (PR #552 ssot + host rm)
- **Replace**: `bootstrap/vault-snapshot-cron.sh` multi-vault + Codex guardrails (flock + unique temp + 14-gün retention)
- `platform-vault-audit-init-1` → retire ✓ + `bootstrap/vault-audit-init-cron.sh` idempotent ensure (crontab 02:15)
- Codex AGREE thread `019dc04d` + ready_for_impl=true
- Live kanıt: staging-sw 2026-04-24 19:47 manuel smoke PASS prod+test (80K + 60K) + 4-gün Apr 21-24 log evidence
- Keşif: compose sidecar ZOMBIE (`sleep infinity` 2026-04-23+) — host cron Apr 20'den beri authoritative, retirement = dead code
- PR: platform-k8s-gitops #104 (Phase 1) + #105 (multi-vault hotfix) + platform-ssot #552 (compose blok rm)
- Evidence: `docs/phase18-evidence/faz-18-4-complete-20260424.md`
- 4 ssot vault runbook migrated (RB-vault-ops + kms-autounseal + approle + dev-path → gitops canonical)
- User hard rule UPHELD: "düzgün çalışan sistemleri bozma" + "bekleme yok hızlı güvenli" (no-soak)

#### 18.5 — App Stateless Compose `stop` — **COMPLETE (2026-04-24)**

- Codex AGREE thread `019dc07c` GO no-soak (user "bekleme yok")
- Live stop 17:27:53 UTC: 9 container (auth-service + user-service + variant-service + core-data-service + report-service + schema-service + api-gateway + discovery-server + openfga)
- permission-service zaten Exited 1 (24h önce), openfga-migrate Completed (job)
- prereq PASS: 18.1 A0 + 18.2 tombstone + 18.3 service-manager retire + 18.4 vault ops

#### 18.6 — 5-Dakika Smoke (no-soak, Codex AGREE 019dc07c)

**User direktifi absorb (2026-04-24):** "bekleme yok hızlı ve güvenli" + "sistem kullanıcısı yok" → 24h soak **KALDIRILDI**. Codex thread `019dc07c` GO no-soak (rationale: compose stateless 9 zaten out-of-path per Faz 18.1 A0 upflow kanıtı + edge routing K8s-only).

**Live smoke 17:28:16 UTC PASS (2026-04-24):**
- K8s prod: 19 Running + 1 Completed (baseline korundu)
- K8s test: 10 Running + 1 Completed (baseline korundu)
- `ai.acik.com/` 200 ✓ + `/api/` 401 ✓ + `/realms/` 200 ✓
- `testai.acik.com/` 200 ✓ + `/api/` 401 ✓
- **Codex gate 1 PASS**: `/api/v1/authz/version` 401 "JWT token zorunludur" (authz chain K8s alive + store/model parity confirmed)
- Evidence: `docs/phase18-evidence/faz-18-5-7-complete-20260424.md`

**Go/No-Go**: 5-dk smoke PASS + OpenFGA parity PASS → 18.7'e geçildi (point-of-no-return).

#### 18.7 — App Stateless Compose `rm` + Deploy Script Cleanup — **COMPLETE (2026-04-24 17:29:35 UTC)**

- `docker rm` 11 container (9 stopped + permission-service Exited + openfga-migrate Completed)
- Post-rm smoke 17:30:21 UTC: K8s 19+10 Running + edge 200/401 zero regression ✓
- Cross-repo ssot PR #553: 11 compose blok tombstone + deploy script cleanup (-937/+54 satır)
- `backend/docker-compose.yml` + `deploy/docker-compose.prod.yml` awk script ile toplu retirement
- `deploy-backend.sh` services list 10→3 + backend_services 8→0 + recreate loop retired
- `platform-start.sh` backend phase-2 kaldırıldı (tek phase: stateful + observability)
- Codex AGREE 019dc07c 2 gate PASS (OpenFGA parity + smoke)
- Total retirement süresi: 3 dakika 14 saniye (17:27:07 → 17:30:21)

#### 18.8 — Lokal k3d-dev Clean Smoke (non-blocking evidence lane)

Codex iter-3: paralel, 18.1-18.7 gate değil.

- Mac'te clean worktree (current dirty state ayrı PR'da temizlik)
- `./bootstrap/setup-clusters.sh dev` → cluster up
- `./scripts/dev-up.sh --profile authn-min` → apply
- `./scripts/dev-seed.sh --profile authn-min` → fixtures
- `./scripts/dev-smoke.sh --profile authn-min` → PASS
- D34 "local dev" bacağı evidence
- `docs/phase18-evidence/local-dev-smoke-YYYYMMDD.md`

#### 18.9 — Legacy Observability Retirement — **COMPLETE (2026-04-24 17:54 UTC)**

- platform-{grafana,prometheus,tempo,loki,promtail}-1 compose stop+rm
- K8s kube-prometheus-stack authoritative (monitoring ns 8d uptime, 11 Running)
- Codex AGREE thread `019dc09c` conditional GO + 3 preflight:
  1. K8s `authz-plane-dashboard.yaml` canonical (compose zanzibar-authz.json replacement)
  2. K8s Tempo ClusterIP (port 4317/4318 no host conflict)
  3. Log visibility kabul (ops `docker logs` + user "sistem kullanıcısı yok")
- Live zero regression: K8s 11 Running + edge 200/401 unchanged
- PR: platform-ssot #554 (compose blok + 2 volume + script cleanup -195/+33)

#### 18.10 — Legacy Network Cleanup — **COMPLETE (2026-04-24 17:58 UTC)**

- 4 Created zombie container rm: platform-keycloak-1 + platform-vault-1 + platform-postgres-db-1 + platform-vault-unseal-1 (2026-04-23'ten kalma, never started)
- `docker network rm platform_observability-network` (orphan, 0 attach)
- Kalan networks: platform-prod-net + platform-test-net + platform_microservice-network (active attachments)
- Host-only operation, PR gerekmez (cross-repo impact yok)

#### 18.11 — Frontend Source Decision Capture — **COMPLETE (2026-04-24, 18.11.a only, 18.11.b DEFERRED)**

- **18.11.a**: Canonical truth mühürlendi:
  - **Frontend delivery:** `staging-sw` host üstünde `platform-web-nginx` (prod) + `platform-web-nginx-stage` (test) reverse-proxy
  - **K8s frontend authoritative DEĞİL**; K8s backend'e erişim `nginx → NodePort/Ingress` üzerinden
  - **Port pins:** ai.acik.com → K8s prod NodePort 30443 / testai.acik.com → K8s test 31080/5545
- **18.11.b** (DEFERRED): Option A (K8s frontend authoritative) — Faz 19+ karar kapısı

#### 18.12 — Truth Closure — **COMPLETE**

- PLAN.md §Faz 18.1-18.12 hepsi COMPLETE marker ✓
- docs/state/current-state.md Faz 18 full closure delta ✓
- docs/session-handoff-2026-04-24-faz-18-truth-closure.md (Session 29 wrap) ✓
- Faz 19 gate pointer (Codex `019dc033` 10-step: split-repo authority transfer)

#### Faz 18 Özet Metrikleri

- **14 compose container retire**: service-manager + vault-snapshot + vault-audit-init + 9 app stateless (auth/user/variant/core-data/report/schema/api-gateway/discovery-server/openfga) + permission-service + openfga-migrate + 5 observability + 4 zombie Created
- **9 compose container kalacak** (ADR-0002 D6 uphold): {pg,kc,vault}-{prod,test} + vault-unseal + 2 nginx edge + test registry
- **31 cross-repo PR Session 29**: 26 gitops merged + 5 ssot (4 merged + 1 open)
- **3-realm izolasyon UPHELD**: ubuntu prod (K8s 19 pod + compose stateful) + ubuntu test (K8s 10 pod + compose stateful) + dev lokal (k3d-dev pending 18.8 smoke)
- **Zero regression**: K8s 19+10 Running stable + edge 200/401 tüm retirement boyunca
- **Codex AGREE thread**: 9 Session 29'da (Faz 17, 16.0, 16.2, 16.8, 18 plan, 18.4, 18.5-18.7, 18.9-18.12, 19 split-repo)

---

### Faz 19 — Split-repo Authority Transfer — **COMPLETE (2026-04-25 17:25 UTC)**

**KAPANIŞ KANITI** (e2e Playwright + curl JWT, 8/8 backend endpoint 200):
- /api/v1/users (2 user), /api/v1/reports (31 rapor), /api/v1/dashboards (12)
- /api/v1/schema/snapshot (3.6 MB, 1509 tablo + 26240 kolon, 27 domain)
- /api/v1/permissions, /api/v1/me/theme/resolved, /api/audit/events, /api/v1/authz/me
- HikariPool-1 (MSSQL primary) + workcube-mssql-readonly (qualifier secondary) + report-pg-pool

**Faz 19.MSSQL.A-Q delta** (PR sequence):
| Faz | PR | Repo | Özet |
|---|---|---|---|
| 19.MSSQL.A | #6 | platform-backend | WorkcubeMssqlConfig + workcube package (feature-flagged) |
| 19.MSSQL.B | #7 | platform-backend | application-k8s.yml MSSQL+PG env binding |
| 19.MSSQL.C | #125 | platform-k8s-gitops | configmap + deployment envFrom MSSQL secret |
| 19.MSSQL.D-H | #126 | platform-k8s-gitops | ESO dual-key + bridge proxy + asset merge live patches |
| 19.MSSQL.I | (manuel) | edge nginx | release c1c624c cutover (host-level) |
| 19.MSSQL.J-L | #27 | platform-web | schema-explorer auth interceptor + window.fetch monkey-patch + mfe_shell URL env-driven |
| 19.MSSQL.M | #127 | platform-k8s-gitops | gateway 6 v1 public + audit/events route (kalıcı) |
| 19.MSSQL.N | #128 | platform-k8s-gitops | test overlay platform-test realm + SECURITY_JWT_* + report-service activation (kalıcı) |
| 19.MSSQL.O | #28 | platform-web | CI gateway URL `/api` + build-script asset merge (kalıcı) |
| 19.MSSQL.P | #130 | platform-k8s-gitops | gateway audit/events SSE 404 fix — ROUTES_14 split (root → user-service exact) + ROUTES_15 (sub-paths /live + /export + /export-jobs → permission-service:8090) |
| 19.MSSQL.Q | #132 | platform-k8s-gitops | gateway /api/v1/roles route ekle — ROUTES_16 (mfe-access RoleDrawer + mfe-users UserDetailDrawer rol CRUD + members + scopes 14 endpoint kullanır) |

**Bridge proxy pattern** (Calico routing fix workaround):
- K3d cluster pod overlay → 10.9.193.201 (Workcube MSSQL) Calico drop
- Workaround: docker bridge'de `alpine/socat` per-cluster (`workcube-mssql-proxy-{prod,test}`)
- Path: Pod → kube-proxy DNAT → bridge container (172.21.0.7 prod / 172.19.0.8 test) → 10.9.193.201:1433
- Bootstrap: `bash bootstrap/workcube-mssql-proxy.sh` (idempotent docker run)

**Vault seed** (D34 izolasyon, prod+test):
- `kv/platform/mssql-external` { username, password, jdbc_url } — Boreas AD domain (`authenticationScheme=NTLM;domain=boreas`)

**Frontend digest pin** (gitops live):
- `platform-web-frontend-testai`: sha-c1c624c (manual edge override; kalıcı CI fix sha-ac35567 sonrası)
- `platform-web-frontend` (prod): sha-c1c624c

**Original 10-step plan** (now COMPLETE):

**Canonical ADR**: [docs/adr/0004-split-repo-authority-transfer.md](adr/0004-split-repo-authority-transfer.md)

**User direktifleri (2026-04-24 Session 29 locked):**
1. "Kaynak raporu tek amacı: geliştirme taşıma."
2. "discovery service i almayı unutma."
3. "raporları da taşıyacağız."

**Codex AGREE thread `019dc0ac` — 6 stratejik default:**
1. **2 repo**: `platform-backend` + `platform-web` (Zanzibar backend içinde, ayrı repo overkill)
2. **Path-filtered full history** (git filter-repo multi-path + sha-map saklanır)
3. **Dual-build + single-consumer** transition (gitops tek digest tüketir)
4. **Reports code taşınır, data contract gitops'ta kalır** (Faz 16.1 DRAFT annex pending_manual_validation korunur)
5. **Option A (K8s frontend) Faz 19 SONRASI** karar kapısı
6. **Monorepo + platform-zanzibar ayrı alternatives REDDEDILDI**

**10-step plan özet** (detay ADR-0004):

| Step | Title | Durum | Authority |
|---|---|---|---|
| 19.0 | Authority reset + ADR-0004 | **COMPLETE** | gitops |
| 19.1 | Yeni repo create + filter-repo migration | **COMPLETE (2026-04-24)**: platform-backend 338 commit, platform-web 739 commit; sha-map saved | org + ssot read |
| 19.2 | Backend batch 1: auth + user + variant | **PR-A IN REVIEW (2026-04-24)**: platform-backend PR #1 (CI + hijyen); Codex thread `019dc0cc` AGREE | platform-backend |
| 19.3 | Backend batch 2: permission + Zanzibar plane | **COMPLETE (2026-04-24 19:06 UTC)**: backend PR #2 MERGED (CI batch scope + DSL basic check) | platform-backend |
| 19.4+19.5 | Backend batch 3+4: core + report + schema + api-gateway + discovery-server | **COMPLETE (2026-04-24 19:12 UTC)**: backend PR #3 MERGED; 10-module CI coverage (9 parent + 1 standalone) | platform-backend |
| 19.6 | Frontend migration (platform-web CI + hijyen) | **IN REVIEW**: web PR #12 (pnpm install + lint + 16 legacy workflow disabled) | platform-web |
| 19.7 | Reports code split + data contract gitops'ta | **COMPLETE docs-only**: mfe-reporting web'de + report-service backend'de + data contract gitops'ta (flyway-v16-plan + mssql-pg-data-contract + report-source-annex + schema-introspection-annex) | docs |
| 19.6 | Frontend migration | Pending | platform-web |
| 19.7 | Reports code split + data contract gitops'ta | Pending | mix |
| 19.8 | CI + image pipeline migration (dual-build) | Pending | yeni repolar |
| 19.9 | Cutover test→prod atomic (D29 3-layer) | Pending | gitops overlays |
| 19.10 (opt) | Source repo lock/archive | Pending | org policy |

**Prereq**: Faz 18.12 truth closure ✓ (PR #109, 2026-04-24 18:04 UTC).

#### Repo Sınırı (Faz 19 genişletildi)

| Repo | İçerik | Faz Durum |
|---|---|---|
| `platform-k8s-gitops` | Kustomize + Helm + ArgoCD + day-2 + ADR + PLAN + current-state + host-compose + **ops runbook canonical** + data contract (DRAFT annex dahil) | Mevcut, genişletildi |
| `platform-backend` (YENİ) | 8 Java mikroservis + Zanzibar plane + discovery-server legacy + Flyway | Faz 19.1'de create |
| `platform-web` (YENİ) | MFE shell + mfe-admin + mfe-reporting + mfe-workbench + design-system + i18n | Faz 19.1'de create |
| ~~`platform-ssot`~~ | **DEPRECATED** (Faz 19.10'da read-only archive veya delete) | Faz 19.10'da kilitlenecek |

#### User karar bekleniyor (19.1 öncesi)

Default'tan sapma varsa override:
- Repo count: 2 (default) vs 1 monorepo vs 3 (zanzibar ayrı)
- Naming: `platform-backend` + `platform-web` (default) vs user önerisi
- History scope: Path-filtered full (default) vs squash (Codex uyarı: blame kaybı)
- Transition: Dual-build (default) vs cold-switch
- 18.11.b Option A: Migration SONRASI (default) vs aynı pencere
- Reports data migration: Defer (default, 16.1 DRAFT) vs aynı faz sıkıştır

#### Bağlantılar (Faz 19)

- ADR-0002 D6 (stateful tier compose, değişmez — Faz 19 bunu etkilemez)
- ADR-0003 inner-loop tooling ownership (Faz 17.6 — dev workflow)
- **ADR-0004 split-repo authority transfer** (Faz 19.0 — yeni)
- PLAN D34 (3-realm independence — korunur)
- `docs/promotion-contract.md` (Faz 17.4 + Faz 19.6 frontend source guarantee)
- Codex thread: `019dc033` (Faz 19 initial) + `019dc0ac` (Faz 19 detaylı AGREE 10-step)

---

### Faz 19.11 — platform-ssot Residual Asset Migration (Hard Archive Öncesi)

**Bağlam**: Faz 19.10 platform-ssot soft lock yapıldı (PR ssot #555), 4 critical PR triage edildi (web #29-31 + backend #8). **Ancak platform-ssot'ta migrate edilmemiş büyük miktar asset var** — kullanıcı tespit etti (2026-04-25 değerlendirme).

**Status — OpenFGA model.fga track + Faz 21.A + Faz 16 CI gates (Step 1-4 SEALED 2026-04-26)**:
- Step 1+2: Model snapshotted to `bootstrap/local-fixtures/openfga/model.fga` + `tuples.json#model` path updated (PR #167 superseded; latest: PR #168 aligned with `Halildeu/platform-backend` PR #11 explicit-scope semantic).
- Step 3 (PR #168 merged): `scripts/dev-seed.sh` writes `model.fga` to OpenFGA store via `render_model_json.py` BEFORE writing tuples; `model_id` captured + passed explicitly. Multi-org tuples promoted from `_future_*` to active. 8/8 smoke checks pass against ephemeral OpenFGA (5 allow + 3 deny — D29 third level).
- Step 4 (PR #169 merged): `.github/workflows/openfga-model-drift.yml` — semantic-JSON drift gate against upstream `Halildeu/platform-backend:main:backend/openfga/model.fga`. Triggers on PR/push (path-filtered) + weekly Mondays 03:00 UTC + manual.
- Faz 21.3 fixture smoke gate (PR #170 merged): `.github/workflows/openfga-fixture-smoke.yml` + `scripts/smoke-openfga-fixture.sh` — every `tuples.json#smoke_checks[]` runs against ephemeral OpenFGA container in CI. Catches render/seed/tuples/smoke regressions. PR #173 then absorbed Codex retrospective `019dcbc8` (image pin to `openfga/openfga:v1.14`, +2 containment-deny smoke checks → 10 total, dev-seed.sh `--request-timeout=3s` + body logging).
- Faz 21.A PG schema regression gate (PR #172 merged): `.github/workflows/data-access-migrations.yml` brings up `postgres:16-alpine`, applies V16→V17→V19→V20, runs 11-assertion suite (`sql/migration/tests/test_v19_v20_data_access.sql`) covering AÇIK seed, scope_kind ↔ source_table CHECK, validate_scope_ref(), UPDATE-smuggling guard, partial UNIQUE re-grant.
- Faz 16 ETL worker pytest + lint gate (PR #174 + #175 merged): `.github/workflows/etl-worker-tests.yml` runs 159 pytest assertions (12 modules / 3185 LoC, mocks only — no live DB) with soft floor 150, plus `ruff check` and `python -m mypy etl_worker` strict. ruff 19→0 + mypy 10→0 cleanup landed in #175.
- Step 5 pending (low priority): platform-backend's upstream copy can be pruned once a deployed-`model_id` diff gate is also in place; current upstream-source drift gate is acceptable steady-state.

**Kapsam ölçümü**:
- platform-ssot: **35 workflow + 137 script + 32 Playwright spec + 21 policy + 8 doc kategorisi + 4 schema-docs dir**
- platform-backend + platform-web + platform-k8s-gitops toplam: **6 workflow + sınırlı test/script**

**Hard archive 1 hafta planı içinde 4 dalga halinde migrate**:

#### 19.11.A — Security Gates (KRİTİK — Dalga 1, ~1 saat)

| Workflow | Hedef repo | Amaç |
|---|---|---|
| `gate-secrets.yml` (gitleaks) | tüm 3 repo | secret scan |
| `gate-osv-scan.yml` | platform-backend + web | dependency vuln scan |
| `security-guardrails.yml` | hepsi | security checks |

#### 19.11.B — Test Suites (YÜKSEK — Dalga 2, 4-6 saat)

- 32 Playwright spec → platform-web/tests/playwright/
- web/tests/msw → platform-web/tests/msw
- web/tests/smoke → platform-web/tests/smoke
- 4 workflow: web-playwright-{smoke,nightly,local-nightly} + post-deploy-validate

#### 19.11.C — Smoke + Deploy Workflows (YÜKSEK — Dalga 3, 3-4 saat)

| Workflow | Hedef | D29 katman |
|---|---|---|
| `smoke-zanzibar.yml` | gitops | katman 3 (Zanzibar-ready) |
| `release-canary.yml` | gitops | release pipeline |
| `rollback.yml` (18KB) | gitops | automated rollback |
| `stage-keycloak-smoke-user.yml` (33KB) | gitops | KC realm + test user |
| `staging-error-sweep.yml` | gitops | error log digest |

#### 19.11.D — Knowledge Base + Decisions (ORTA — Dalga 4, 1-2 gün)

- `decisions/registry.v1.json` + `decisions/topics/zanzibar-openfga.v1.json` → gitops/decisions/
- 21 `policies/policy_*.v1.json` → gitops/policies/ (bağlantılı: `gate-policy-dry-run.yml`)
- `AGENT-CODEX.{ai,backend,core,data,docs,mobile,web}.md` → ilgili repolarda
- `docs/00-handbook` + `docs/02-architecture` + `docs/04-operations` → gitops/docs/
- `standards.lock` → gitops (CI gate referansı)
- `ci/` 14 Python check script → gitops/ci/

#### 19.11.E — Operasyonel scripts (selektif, Dalga 4 follow-up)

- `doctor-infra.sh` + `doctor-zanzibar.sh` → gitops/scripts/
- `check-vpn.sh` + `check-mf.sh` → gitops/scripts/
- 40+ `check_*.py` scripts → selektif port (CI gate'lerle bağlantılı olanlar)

#### 19.11.F — Schema docs (Faz 16 referansı, Dalga 4 follow-up)

- `schema-docs-mssql-2026-35/` → gitops/docs/migration/ (Workcube schema introspection — Faz 16 ETL referansı)
- `schema-docs-mssql-35-implied/` → aynı

#### Dependency parity audit (paralel iş)

Migration sırasında **dependency parity audit** koşulur:
- Java Maven (platform-backend pom.xml hierarchy) vs platform-ssot/backend
- Web npm (platform-web package.json hierarchy) vs platform-ssot/web
- Python (requirements-dev.txt) → migrate edilmeli mi karar
- Versiyon güncelliği + CVE alarm

#### Önkoşul

Faz 19.10 hard archive **bu 4 dalga tamamlanmadan yapılmamalı** — archived repo'dan asset çıkarmak `gh api` ile zor (sadece archived state'te raw URL'ler erişilebilir kalır ama PR/Issue history dondurulur).

#### Bağlantılar

- PR #143 (Madde 1+2 fix sonrası kullanıcı değerlendirmesi)
- platform-ssot #555 (DEPRECATED soft lock)
- ADR-0004 split-repo authority transfer

---

### Faz 20 — Calico Routing Root Cause Fix — **COMPLETE (2026-04-25 19:00 UTC)**

**Bağlam**: Faz 19.MSSQL.F'te Calico VXLAN overlay'den external 10.9.193.0/24 LAN'a routing fail tespit edilmişti. Workaround: alpine/socat bridge proxy container per-cluster (workcube-mssql-proxy-{prod,test}). Bu kalıcı çözüm değildi.

**Root cause** (Calico research subagent verdict): K3d gotcha — Calico `Installation` CR'de `containerIPForwarding` default `Disabled`. Bu, CNI ConfigMap `"allow_ip_forwarding": false` üretir → pod ns'de `net.ipv4.ip_forward=0` → external LAN routing FAIL. `natOutgoing: Enabled` tek başına yetmiyor; ip_forward + natOutgoing iki ayar birbirini tamamlar.

**Fix** (PR #136 MERGED): `bootstrap/install-calico.sh` Installation CR'a `spec.calicoNetwork.containerIPForwarding: Enabled` eklendi (1/10 karmaşıklık).

**Live proof** (D29 3-katman):
| Katman | Test | Sonuç |
|---|---|---|
| Up | calico-node DaemonSet rolling restart (test+prod) | Running ✓ |
| Functional | Synthetic pod `cat /proc/sys/net/ipv4/ip_forward` | `1` ✓ |
| External routing | `nc -zv -w5 8.8.8.8 53` (test+prod) | OPEN ✓ |
| Bridge proxy parallel | `nc 172.19.0.8:11433` (test) / `172.21.0.7:11433` (prod) | OPEN ✓ (decommission'a kadar warm) |

**Bridge proxy decommission DONE** (2026-04-25 19:30 UTC, PR #138 MERGED + LIVE apply):

Atomic swap pattern — Vault URL rotation YOK:
- Service `port: 11433` (Vault JDBC URL backward compat) + `targetPort: 1433` (Endpoints'e iletilen)
- Endpoints `IP: 10.9.193.201, port: 1433` (her iki cluster aynı, direct LAN)
- NetPol `cidr: 10.9.193.201/32, port: 1433`
- `bootstrap/workcube-mssql-proxy.sh` → `bootstrap/archived/...faz-20-decommissioned`

Apply sıralaması (D29 + D30 atomic):
1. PR #138 merged → staging-sw git pull
2. Test cluster apply 3 manifest → smoke /api/v1/reports + /api/v1/schema/snapshot 200
3. Prod cluster apply 3 manifest → smoke (anon health 401 doğru shape)
4. `docker stop+rm workcube-mssql-proxy-{test,prod}` → 2 container silindi
5. Final compose state: 16 → **13 container** (tamamı bilinçli mimari)

Live proof (test cluster):
- /api/v1/reports → 200 (MSSQL connection direct)
- /api/v1/dashboards → 200
- /api/v1/schema/snapshot → 200 + 3.6 MB + 1509 tablo + 26240 kolon

**Compose stack final state** (13 container):
- D6 stateful: pg-{prod,test}, kc-{prod,test}, vault-{prod,test} = 6
- Edge nginx (D8/D18): platform-web-nginx, platform-web-nginx-stage = 2
- K3d cluster infra: k3d-{prod,test}-{server-0,serverlb} = 4
- Test registry: platform-test-registry = 1

**Codex thread**: research subagent verdict (k3d Calico guide + Installation API + tigera/operator #1709)

#### Bağlantılar (Faz 20)

- PR #136 (containerIPForwarding=Enabled — root cause fix)
- PR #138 (bridge proxy decommission — atomic swap pattern)
- ADR-0005 Dual DataSource Reporting (bridge proxy → direct routing)
- Codex research subagent (web search + Calico docs analizi)

---

### Faz 21 — Veri Erişimi Multi-Org Scope Layer (PROPOSED)

**Karar tarihi**: 2026-04-26 (kullanıcı UI ekran kanıtı + multi-org gereksinim).

**Bağlam**: Platform "Veri Erişimi" panelinde dört scope sekmesi: Şirketler / Projeler / Depolar / Şubeler. Hizmet **kurum bazlı** verilecek; bir kurum birden fazla Workcube COMPANY'ye sahip olabilir. Her kullanıcının erişebileceği veri scope'u (companies/projects/depots/branches) kurum bazlı atanacak.

**MSSQL kaynak eşleşmesi** (snapshot `docs/migration/workcube-schema.json` ile doğrulandı):

| UI sekme | MSSQL tablosu | Kolon sayısı | V16 DDL'de? |
|---|---|---|---|
| Şirketler | `COMPANY` | 113 | ✓ (Day 7 smoke MATCH'te kullanıldı) |
| Şubeler | `BRANCH` | 107 | ✓ |
| Projeler | `PRO_PROJECTS` | 75 | ✓ |
| **Depolar** | `DEPARTMENT` (43 cols) + `SETUP_DEPARTMENT_TYPE` lookup | 43 + 9 | ✓ DEPARTMENT V16 canonical; lookup Faz 21.4'e defer (PR #164, Faz 21.A merged) |

**Faz 16 ile ilişki**: COMPANY/BRANCH/PRO_PROJECTS zaten Faz 16 canonical kapsamında (V16 DDL üretildi, lineage cols + UNIQUE index hazır). Bu fazda yapılacak: (a) Depolar kaynak tablosunun netleştirilmesi + V16 generator rerun gerekirse, (b) tables.yaml manifest'ine 4 entity için tam kolon set'i ile parametric-olmayan entry'ler, (c) Veri Erişimi domain layer (kurum modeli + scope assignment).

**Faz 21.1 — ETL kapsam genişletme** (canonical, parametric değil):

İki alt-faza bölündü (Codex 019dc8b4 PR #165 iter-1 absorb):

**21.1a — Manifest + V20 contract** (PR #165, MERGED expected):
- ✅ Depolar kaynak tablosu netleşti: `DEPARTMENT` (Faz 21.A doc, PR #164 merged).
- ✅ `config/tables.yaml` manifest'e PRO_PROJECTS + DEPARTMENT eklendi (15 + 6 minimum kolon).
- ✅ V20 migration: `scope_kind='depot'` → `DEPARTMENT` CHECK; validate_scope_ref() depot/DEPARTMENT branch.
- ✅ Live evidence Mac dev-pg: V20 apply OK; depot trigger guard 3 saldırı vektörü reddedildi; valid INSERT pass.
- 159/159 test PASS.

**21.1b — Live ETL run + reconcile evidence** (next, separate PR):
- Test cluster apply (V16 + V17 + V19 + V20) + ad-hoc Job (PR #162 runbook) `--tables COMPANY,BRANCH,PRO_PROJECTS,DEPARTMENT` ile ETL koşumu.
- Reconcile artifact 4-entity kapsamında; Faz 16 Behavior gate'in genişletilmiş hali.
- User-gated deploy step; agent sandbox shared PG erişimi yok.

**Faz 21.2 — Org/Tenant data model** (PG canonical, MSSQL'den bağımsız):
- Schema yeri (Codex 019dc8b4 iter-1 REVISE): **`reports_db` içinde ayrı `data_access` schema**. Cross-DB join karmaşıklığı kaçırılır; `data_access_scope.scope_ref ↔ workcube_mikrolink.<entity>.source_pk` tek SQL ile join edilebilir. ADR consequence: "ileride org_db'ye ayrılabilir, şimdilik lineage-locality wins."
- **AÇIK kurumu seed** (kullanıcı 2026-04-26): Mevcut Workcube MSSQL kaynağındaki tüm 1509 tablo + tüm COMPANY/BRANCH/PRO_PROJECTS satırları **AÇIK** kurumuna ait olarak seed edilir. `organization` tablosuna ilk satır `(id=1, name='AÇIK', status='active')`. Multi-org alt yapı tablo modelinde korunur (N:N tasarım), ama bu fazın canlı verisi tek-org. İleride başka kurum eklenirse (yeni MSSQL kaynağı veya ayrı tenant izolasyonu) `organization` satırı + `organization_company` mapping'i eklenmesi yeterli.
- Tablolar:
  ```
  data_access.organization (
      id BIGSERIAL PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,        -- 'AÇIK' seed
      status TEXT NOT NULL CHECK (status IN ('active','suspended','archived')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      created_by UUID
  );

  data_access.organization_company (
      org_id BIGINT NOT NULL REFERENCES data_access.organization(id),
      workcube_company_source_pk TEXT NOT NULL,
      source_schema TEXT NOT NULL DEFAULT 'workcube_mikrolink'
          CHECK (source_schema = 'workcube_mikrolink'),     -- Codex iter-2
      source_table TEXT NOT NULL DEFAULT 'COMPANY' CHECK (source_table = 'COMPANY'),
      attached_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (org_id, workcube_company_source_pk)
  );

  data_access.scope (
      id BIGSERIAL PRIMARY KEY,
      user_id UUID NOT NULL,
      org_id BIGINT NOT NULL REFERENCES data_access.organization(id),
      scope_kind TEXT NOT NULL CHECK (scope_kind IN ('company','project','depot','branch')),
      scope_source_schema TEXT NOT NULL DEFAULT 'workcube_mikrolink'
          CHECK (scope_source_schema = 'workcube_mikrolink'),  -- Codex iter-2
      scope_source_table TEXT NOT NULL,
      scope_ref TEXT NOT NULL,            -- workcube source_pk (canonical JSON form)
      granted_by UUID,
      granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      revoked_at TIMESTAMPTZ,
      revoked_by UUID,
      -- Codex iter-2: table-level UNIQUE YOK (revoke + re-grant cycle için)
      CHECK (
        (scope_kind = 'company'  AND scope_source_table = 'COMPANY') OR
        (scope_kind = 'project'  AND scope_source_table = 'PRO_PROJECTS') OR
        (scope_kind = 'branch'   AND scope_source_table = 'BRANCH') OR
        (scope_kind = 'depot'    AND scope_source_table = 'DEPARTMENT')  -- V20 (Faz 21.1)
      )
  );

  -- Codex 019dc8b4 iter-2: active-only partial unique
  CREATE UNIQUE INDEX uq_scope_active_assignment
      ON data_access.scope (user_id, org_id, scope_kind, scope_ref)
      WHERE revoked_at IS NULL;
  ```
- Validation function `data_access.validate_scope_ref(kind, source_table, ref)` lineage existence check yapar (PG'de N tablo çapraz FK doğal değil; trigger + function tercih).
- Seed migration: V19 sonrası `INSERT INTO data_access.organization (name, status) VALUES ('AÇIK', 'active');` ve ETL canonical COMPANY satırlarının `source_pk`'lerini `organization_company`'ye bulk insert (initial bootstrap migration veya CLI).
- Flyway migration: `V19__data_access.sql` (V17 lineage ALTER'dan sonra, V18 boş kalır parametric için reserve).

**Faz 21.3 — Authz entegrasyonu** (Zanzibar/OpenFGA):
- Yeni türler (Codex 019dc8b4 iter-2 absorb — UI'daki "Scope atanmadan kullanıcı hiçbir veri göremez" kuralıyla uyumlu, **explicit-scope contract**):
  - `organization` relations:
    - `member: [user]` — kurum üyeliği/tenant bağlamı; **veri görünürlüğü vermez**.
    - `admin: [user]` — scope atama/yönetim yetkisi (kullanıcı veya rol).
  - `company`, `project`, `depot`, `branch` relations:
    - `parent_org: [organization]` — ownership/containment; viewer auto-grant ÜRETMEZ.
    - `viewer: [user]` — explicit scope assignment'tan gelir; `data_access.scope` INSERT'i tuple writer ile bu relation'a yazar.
- Tuple atama akışı: admin Veri Erişimi panelinde user'a company/project/depot/branch atar → backend `data_access.scope` satırı insert + tuple writer `company:<source_pk>#viewer@user:<uid>` yazar. Org membership tek başına hiçbir company'yi açmaz.
- Backend enforcement: ADR-0013 / C-008 gereği direct `OpenFgaAuthzService` SDK; permission-service tuple writer + user-facing authz hub.
- ADR-0008 (yeni) — "multi-org scope, explicit-grant contract" — UI semantiğinin Zanzibar modeline yansıması.

**Faz 21.4 — UI/Backend integration** (out of platform-k8s-gitops scope):
- Frontend admin "Veri Erişimi" panel: scope listesi + atama UI (mevcut MFE'lerden birinde).
- Backend (muhtemelen `permission-service` veya `core-data-service`): scope query API'leri + atama mutation'ları.
- Bu faz kapsamı **platform-web** repo (sub-component) işidir; platform-k8s-gitops sadece manifest/secret/ESO tarafını taşır.

**Sıra ve PR ayrımı** (taslak — Codex iter-1 plan-time onayına bağlı):
1. Depolar kaynak tablosu netleştirme (issue + dosya: `docs/migration/depolar-source-decision.md`).
2. Manifest enrichment PR — `tables.yaml` 4 entity tam kolon + V16 generator için PRO_PROJECTS minimum kolon doğrulaması.
3. ETL koşum + reconcile evidence (PR #162 runbook ile, ayrı evidence commit'i).
4. Data access schema migration PR — `data_access.organization*`, `data_access_scope` (Flyway V19+).
5. OpenFGA tip + tuple yazıcı (Zanzibar plane).
6. Backend API kontratı (platform-web tarafı).

**D29 disiplini**: Her faz alt-PR'ı Up + Functional + Behavior gate ayrı kanıtla. Faz 21.2 schema migration için: pgTAP testi veya en azından integration test koşumu (mevcut etl_worker tests/test_v16_preflight.py paterni).

**Hard rules** (mevcut):
- Kural #9 No Fake Work: scope assignment akışı Functional gate olarak gerçek bir org + 2 user + 1 company atama denemesi ile kanıtlanır; mock UI screenshot yetmez.
- Kural #8 Codex authority: stratejik karar (data_access schema yeri, OpenFGA store ayrımı, vs) Codex iter ile alınır.

**Codex thread**: bu fazın plan-time iter-1'i sonrası açılacak.

---

### Faz 18 Eski Bağlantılar (historical reference)

- ADR-0002 D6 (stateful tier compose, değişmez)
- PLAN D34 (YENİ — 18.0 deliverable, 3-realm runtime independence)
- `docs/promotion-contract.md` (Faz 17.4 — D34 kontrat detay genişlemesi)
- `docs/state/current-state.md` drift (shared edge + compose stateless canlı gateway/auth çelişkisi)
- Codex thread: `019dbfa5` (iter-1 VERDICT → iter-2 revize → iter-3 AGREE)

---

## 5. Ana Repo Bağlantısı

**autonomous-orchestrator** içinde kalacaklar:
- Backend kaynak kod (değişmez)
- Dockerfile'lar (güncellenecek: non-root)
- `application-k8s.yml` profilleri (yeni)
- `decisions/topics/kubernetes-migration.v1.json` (yeni ADR)
- CI/CD: `deploy-backend.yml` → GHCR push aynen kalır
- `scripts/doctor-k8s.sh` (yeni)

**Bu repo'ya taşınmayacaklar:** Hiç K8s manifest'i ana repo'ya girmez. Temiz ayrım.

---

## 6. Riskler ve Mitigasyon

| Risk | Etki | Mitigasyon |
|------|------|-----------|
| ~~Eureka + K8s Service çifte discovery~~ | **PASIF** (D7 revize) | Eureka tamamen kaldırıldı, K8s native DNS kullanılıyor. Geçici Eureka YOK (D26) |
| **CPU throttle** (4 vCPU, spike senaryosu) | Request timeout, GC pause, p95 latency bozulması | D22 politikası: request dar (150m), limit cömert (750-1000m), `request=limit` yok. `-XX:ActiveProcessorCount` JVM için pod limit'ine set. Prometheus scrape 30s→60s gerekirse. Gerçek yük ölçülüp gözden geçirilecek |
| **HPA metrics-server çelişkisi (kapatıldı)** | Autoscaling çalışmazdı | D21: MVP'de HPA YOK, metrics-server kapalı kalır, sabit replica. Gelecekte metrics-server veya Prometheus Adapter kararı ayrıca alınır |
| **Tek host = HA/DR değil** | Hardware failure → toplam outage | D23: RPO/RTO tanımlı, off-host backup + restore prova zorunlu, runbook'lar Faz 12 öncesi hazır. RPO<1h gerekirse mimari değişir |
| **PoC dilim başarısızlığı** | Yanlış mimari varsayımı erken yakalanmazsa manifest çoğaltmasında kaybolmuş olur | D25: kabul kriteri net, yeşil olmadan tam filoya geçilmez. Her dilim ayrı PR + smoke test |
| Host-level PG'ye ağ erişim | Cluster ↔ host network izolasyonu | ExternalName Service + Endpoints ile statik mapping, network policy |
| Vault secret migration | Prod down riski | Önce test namespace'de ESO test et, prod'a son geç |
| MFE React duplicate (mevcut blocker) | White screen | K8s öncesi bu çözülmeli — nginx cache header'ları Faz 7'de revize |
| Decision registry ihlali | permission-service port 8090 yanlışlıkla eklenir | Her PR'da `doctor-zanzibar.sh --quick` koş |
| Cron deploy aktif edilirse erken push | Yarım manifest prod'a gider | DEPLOY_ENABLED=false kalır Faz 15'e kadar |
| **Wildcard cert expiry 2026-10-01** | prod + test TLS kesintisi | **P0 reminder 2026-09-01**: yeni Sectigo cert al ya da cert-manager + LE HTTP-01 otomasyonu aç. Renewal öncesi Secret rotate prosedürü test edilmeli |
| Dış proxy (212.115.26.190) başkasının yönetiminde | `ai.acik.com` üzerinde operasyonel değişiklikler koordinasyon ister | L4 pass-through varsayımı doğrulanmalı (sysadmin'e sor); değilse strateji değişir |
| `testai.acik.com` DNS kaydı sysadmin gecikmesi | Faz 12/13 bloklanır | Faz 1'de erken ticket aç, paralel iş |
| **Eureka kaldırma kod değişikliği** (D7 revize) | Servis-arası çağrılar bozulur | Faz 11'de annotation + pom + route URL'leri sistematik temizle. Önce tek servis (örn. user-service) PoC, smoke yeşil olunca diğerlerine yay |
| **24 GB RAM dar bütçe** | OOM, swap'a düşme, prod degradasyon | Resource quota + LimitRange ZORUNLU. JVM heap explicit `-Xmx`. Retention KISA. Geçiş döneminde compose-prod + K8s-test paralel iken RAM <22 GB tut |
| **Disk %80 dolu, geçiş döneminde %87'ye** | k3s image pull başarısız, cluster instabil | Önce hafif prune; compose-prod stop sonrası `docker system prune -a` ile büyük temizlik. **Disk artırma opsiyonu açık** (sysadmin) |

---

## 6.5 DR / RPO / RTO (FINAL — D23)

**Tek host mimarisinin sınırları:** staging-sw kernel panic/donanım arızası → tüm cluster'lar ve host Compose aynı anda offline. Bu tasarım **HA değil**, operasyonel süreklilik için manuel restore'a güvenir.

**Hedefler:**

| Ortam | RPO | RTO | Kayıp toleransı |
|---|---|---|---|
| **prod** | ≤ 24 saat | ≤ 4 saat | Son gecelik backup'a dön |
| **test** | ≤ 24 saat | ≤ 1 iş günü | İstek halinde restore |

**Backup kapsamı (her öğe için off-host kopya zorunlu):**

| Veri | Kaynak | Yedek | Frekans |
|---|---|---|---|
| PG (prod) | host Compose `/var/lib/postgresql/data` | `pg_dump` + physical snapshot → off-host (S3 veya ayrı makine) | günlük 03:00 (mevcut) |
| PG (test) | host Compose test PG | `pg_dump` → off-host | günlük (ya da on-demand) |
| Vault raft (prod) | host Compose vault state | `vault operator raft snapshot save` → off-host | günlük 03:00 (mevcut) |
| Vault raft (test) | host Compose test vault | raft snapshot → off-host | günlük |
| Keycloak state | PG içinde (KC tabloları) | PG backup içinde | PG ile |
| k3d cluster state (etcd) | PVC'ler | k3d'nin yerleşik backup'ı yok; **etcd snapshot manuel**, ama GitOps'tan **geri kurulum tercih** | on-demand |
| Host Compose state dizinleri | `/home/halil/platform/state/*` | tarball → off-host | günlük |
| Monitoring PVC (prom/loki/tempo) | k3d local-path | **yedek YOK** (retention penceresi kabul) | - |
| Cert ve key (`host-compose/proxy/tls/`) | host | güvenli off-host (Vault KV veya şifreli bucket) | her rotation'da |

**Restore provası (zorunlu):** Her çeyrekte bir kez prod PG dump'ı test'e restore edilmeli. Başarı kriteri: backend `/actuator/health/readiness` 200 döner, smoke test geçer.

**Runbook'lar (docs/runbook/ altında, Faz 12 öncesi hazır):**
- `pg-restore.md` — dump/snapshot'tan restore
- `vault-unseal-restore.md` — raft snapshot + unseal prosedürü
- `cluster-rebuild.md` — k3d cluster'ı GitOps'tan yeniden kurma (<1 saat hedefi)
- `cert-rotation.md` — Sectigo yeni cert indirme + host nginx reload + doğrulama
- `node-maintenance.md` — kernel patch/reboot öncesi downtime planlama + bildirim

**RPO <1 saat veya RTO <1 saat gerekirse:** mevcut mimari yeterli değildir — iki host replication (PG streaming, Vault HA), veya cloud managed DB/KV zorunlu olur. Bu kapsam bu PLAN'ın DIŞINDA.

## 7. Sonraki Session'a Bootstrap

**Bu dosyadan başlayacak session için:**

```
Ben şu anda /Users/halilkocoglu/Documents/platform-k8s-gitops/ dizinindeyim.
Bu repo autonomous-orchestrator platformunun K8s GitOps manifest'lerini tutar.
PLAN.md içindeki kararlar FINAL'dir, Faz 0 tamamlandı.
Devam edeceğim faz: Faz 1 — Repo Temeli (README + .gitignore + ilk commit).
```

**Referanslar (yeni session bu dosyaları okumalı):**
- `PLAN.md` (bu dosya) — tüm kararlar + yol haritası
- `/Users/halilkocoglu/Documents/dev/CLAUDE.md` — ana repo kuralları
- `/Users/halilkocoglu/Documents/dev/AGENTS.md` — orchestrator contract
- `/Users/halilkocoglu/Documents/dev/decisions/topics/zanzibar-openfga.v1.json` — auth FINAL kararlar
- `/Users/halilkocoglu/Documents/dev/backend/docker-compose.yml` — mevcut servis konfigi (manifest üretirken referans)
- `/Users/halilkocoglu/Documents/dev/deploy/docker-compose.prod.yml` — prod env konfigi

**Mevcut ana repo durumu (2026-04-14):**
- Worktree: `zealous-margulis` (branch: `claude/zealous-margulis`)
- Son compose stabilizasyon commit'leri: #357–#363
- Zanzibar Faz 2+3 tamam, Faz 4 %90
- Aktif blocker: MFE React duplicate → K8s öncesi çözülmeli

---

## 8. Değişiklik Kaydı

| Tarih | Değişiklik |
|-------|-----------|
| 2026-04-14 | İlk yazım — 15 faz, 14 FINAL karar kilitlendi |
| 2026-04-14 | **DNS & TLS bloğu netleşti** — D8 revize (wildcard Sectigo cert manuel, cert-manager DEFER), Bölüm 2.3 Hostname & TLS eklendi (path-based routing), Faz 1'e DNS ticket + quick-win, Faz 3 cert-manager çıkarıldı, 3 yeni risk (cert expiry 2026-10-01, dış proxy bağımlılığı, DNS ticket gecikmesi) |
| 2026-04-14 | **Kapasite & Eureka netleşti** — D7 revize (Eureka KALDIRILDI, K8s native DNS), Bölüm 2.4 Kapasite & Aşamalı Cutover eklendi (sabit 24GB/4vCPU/97GB bütçe, namespace quota tablosu, 9 adımlı cutover sırası), Faz 6 (discovery+permission SKIP), Faz 11 (Eureka kod temizliği detaylı), 3 yeni risk (Eureka kaldırma, RAM darlığı, disk darlığı). Disk artırma opsiyonu beklemede |
| 2026-04-14 | **Disk 200 GB onaylandı** (ETA 2026-04-16). Bölüm 2.4 güncellendi. Disk darlığı riski PASIF. RAM 24 GB sabit kalıyor — Eureka kaldırma + JVM heap sıkıştırma + quota stratejisi devam |
| 2026-04-14 | **Cluster mimari netleşti** — D2 revize (5 ns), D15 Calico CNI, D16 tek cluster, **D17 scale-to-zero test** (yoğun saatlerde test KAPALI, RAM=0), D18 hostNetwork ingress, D19 Service+Endpoints host köprü, D20 prod=mevcut portlar. Bölüm 2.5 Cluster Topoloji eklendi (k3s install flags, k3d config, namespace diyagramı). RAM bütçesi iki senaryolu tablo (kapalı 10.3 GB / açık 13.3 GB) |
| 2026-04-14 | **2 k3d cluster mimarisine geçildi** — D16 revize (tek k3s → 2 k3d aynı host), D18 revize (hostNetwork ingress → host nginx SNI proxy 443'ü alır, cluster içi HTTP-only). Gerekçe: "birini bozunca diğeri bozuluyor" deneyimine karşı kontrol düzlemi fiziksel ayrımı. Bölüm 2.5 tamamen yeniden yazıldı (k3d-prod/test.yaml config, host nginx SNI proxy nginx.conf, iki cluster diyagramı, ArgoCD multi-cluster). Bölüm 2.4 RAM tablosu cluster-başına detaylı (test kapalı 13.5 GB / açık 16.5 GB, 24 GB'ta rahat). Faz 3 2 cluster setup'a göre revize |
| 2026-04-14 | **D27 Upstream-first prensibi** eklendi: her bileşen kendi native Helm/operator kullanır, custom kod minimum. Custom admission webhook / özel operator / manuel YAML patch YASAK |
| 2026-04-14 | **Codex Tur-3 + Tur-4**: Kurulum inceleme + kısmi itiraz uzlaşısı. 10 bulgu (3 P0, 5 P1, 2 P2). Tur-4'te benim 2 itirazıma Codex gerekçeyle cevap: (1) admin hardening lokalde toleranslı ama repo-seviyesi prod/test overlay'lerde ŞIMDI sertleştirme, (2) image tag `:poc` REDDEDILDI "cutover'da düzeltilir" argümanım tutmadı — prod/test digest pin + ESO-fed imagePullSecret bugün girdi. NP için C+ model (default-deny + 4 allowlist) seçildi. Tüm 10 madde 3 commit'te kapatıldı (73d8600 + bf7f19f + BU COMMIT). PLAN drift 7 satır temizlendi. |
| 2026-04-14 | **Codex istişaresi — 2 turlu, UZLAŞI** (docs/codex-review-2026-04-14.md). Drift temizliği: D1 (tek cluster → 2 k3d), D2 (5 ns tek cluster → cluster-başına ns), D16 ("Docker-in-Docker" → Docker container), §2.3 TLS (cluster Secret → host nginx), Faz 4 (ExternalName → Service+Endpoints), §6 Risk (Eureka K8s-içi single-replica → PASIF). D7 revize: dilimli Eureka kaldırma. D8 revize: 2 aşamalı cert stratejisi (manuel + Faz 12 HTTP-01 dry-run). D10: retention 14d→10d/14d→7d/3d→48h. **6 yeni karar**: D21 HPA (MVP'de yok), D22 CPU bütçesi, D23 DR/RPO/RTO, D24 JVM `-Xmx` explicit (MaxRAMPercentage kaldırıldı), D25 PoC dilim (`api-gateway + auth-service` → `user-service`), D26 YAPMA listesi. Yeni §6.5 DR/RPO/RTO bölümü. §2.4 CPU bütçesi tablosu. 4 yeni risk (CPU throttle, HPA çelişkisi pasif, tek-host DR sınırı, PoC dilim başarısızlığı) |
| 2026-04-15 | **Hostname rename + STABİLİTE KAPISI**: `test.acik.com` → `testai.acik.com` (5 dosya: PLAN.md, ingress.yaml, overlay test, host nginx.conf, README). Sectigo wildcard `*.acik.com` kapsıyor → cert değişimi YOK. Yeni HARD RULE: testai.acik.com'da Dilim 1+2+3 stabil olmadan ai.acik.com prod cutover BAŞLAMAZ. Sıralama: test cluster ayağa → testai smoke → tüm dilim'ler yeşil → prod cluster + cutover. |
| 2026-04-15 | **GitHub remote AKTİF** (D12 revize). `git@github.com:Halildeu/platform-k8s-gitops.git` private repo. Lokal SSH key + sunucu için ayrı read-only deploy key (port 443 alternatif, kurum firewall 22 kapalı). install-on-staging-sw.sh: rsync → git clone/pull (6/14 adımı güncellendi, SSH config otomatik ekleniyor). ArgoCD Application CR'ları bu URL'i source olarak alacak (Faz 10). |
| 2026-04-15 | **Dilim 1+2+3 CANLI (testai.acik.com)**. Ana repo (autonomous-orchestrator `k8s-migration-dilim1` branch): auth-service + api-gateway + user/variant/core-data/report/schema-service için Eureka dep kaldırıldı + `application-k8s.yml` profile yazıldı + non-root Dockerfile. 7 image local build + staging-sw'ye scp + k3d import. Gitops: image override (`k8s-poc` tag, imagePullPolicy: Never), quota genişletildi (4/8 vCPU, 8/16 GiB), NP/NP, overlay scale patches. Tam smoke: **testai.acik.com 8/8 path HTTP 200** (/testai-healthz, /actuator, /auth, /users, /variants, /core, /reports, /schemas). Mevcut `ai.acik.com` compose DOKUNULMADI (200 dönüyor). OpenFGA migrate Completed, frontend nginx 1/1 Running (MFE artifact boş — Dilim 4). Bazı backend pod'lar hâlâ CrashLoopBackOff (Spring DB resolve env convention — ana repo main-stable rebuild gerekli); ancak zincir çalışıyor (gateway yanıt veriyor, ingress route'lar tam). **Bu repo dilim PASS** — tam sistem sonraki adımda `main-stable` tag güncellenince 5-10 dk içinde temiz deploy edilir. |
| 2026-04-15 | **DILIM 1+2+3 PASS** — Codex Tur-7+8 false-positive 200'lerin nginx'te testai server block silinmesinden kaynaklandığını keşfetti. Pod crash ana nedeni: **ARM64 (M4 Pro) image AMD64 staging-sw'de exec format error**. AMD64 cross-build → tarball → scp → docker load → k3d import → rollout. Ayrıca kustomize patch'ler SPRING_DATASOURCE_URL pod env'e erişemedi (Spring Boot property resolution sırası) → `kubectl set env` ile explicit env ekleme ile çözüldü. Son smoke: **6/6 backend path → 401 "JWT token zorunludur" JSON** (gerçek Spring Security cevabı, HTML değil). Zincir: ingress → gateway:8080 → K8s DNS → `<svc>.platform-test.svc.cluster.local:<port>` → Spring Security 401. ai.acik.com (compose) DOKUNULMADI → 200. PoC smoke PASS. Kalan polish: OpenFGA migrate idempotency, Dockerfile `JAVA_TOOL_OPTIONS` env adı (JAVA_OPTS ENTRYPOINT'te expand olmuyor), testai nginx block'un compose restart'a dayanıklılığı (docker-compose.yml networks block). |
| 2026-04-17 | **Drift teşhis + 4-tur Codex istişare re-baseline** (thread `019d9a75-4299-7313-85bb-003a7de680eb`). **Eklenen:** D28 (handoff 5-alan zorunlu), D29 (Up≠Functional≠Zanzibar-ready 3 seviye raporlama, tek "green" yasak), D30 (cutover atomic switch + 72h warm rollback, digest pin zorunlu, weighted YASAK), D31 (primary DB PostgreSQL, MSSQL secondary/opsiyonel external). **Revize:** "port 8090 yok" HARD RULE KALDIRILDI — D-003 TRANSFORMED uyumlu `permission-service` Service 8090→8084 DOĞRU kontrat. **Düzeltme:** Faz 6 `permission-service SKIP` → **AKTIF** (Zanzibar authz hub, CNS-20260411-001). **Yeni HARD RULES:** Authoritative Entrypoint (smoke tuple + negatif kontrol), Up≠Zanzibar-ready ayrımı, Immutable Artifact (digest pin + imageID), Cutover Atomic Switch, Handoff 5-alan. **Drift haritası (bugünkü gerçek):** Faz 3/4/5/6 REGRESSION (Calico BIRD down + Typha watch cache bozuk; 5 pod crash 20h; testai edge SNI fallback compose frontend'e; users_db+variants_db YOK; OpenFGA enabled=false default; ghcr-pull secret eksik), Faz 10 BAŞLAMADI (ArgoCD yok), Faz 13 REGRESSION (1-hafta gözlem başlamamış), Faz 15 BAŞLAMADI. **Repo ayrımı netleşti:** `platform-k8s-gitops` (bu repo, manifest) + `platform-ssot` (Java backend + MFE, `/Users/halilkocoglu/Documents/dev/`) + `autonomous-orchestrator` (Python control-plane, governance). Handoff v3 `docs/session-handoff-2026-04-17.md` ilk 5-alan örneği. |
| 2026-04-17 | **Seviye 0 canlı recovery TAMAMLANDI** (Codex thread devamı). **Fix uygulandı:** `calico-typha scale=0` + `calico-node` recycle → BIRD up, Tigera DEGRADED=**False**. `users_db`+`variants_db` zaten mevcut (önceki drift). 5 crash pod rollout restart → **9/9 Pod Running + Ready**, tüm Endpoints doldu. **Intra-cluster Up kanıt:** labeled busybox nc 3/3 OPEN (postgres.svc:5432, keycloak.svc:8080, raw 172.19.0.4:5432), management:8081/actuator/health auth/user/variant/core → **4/4 200**. **testai edge fix:** `/home/halil/platform/web/nginx/default.conf` host dosyasına `testai.acik.com` server_block + `/testai-healthz` sentinel + proxy → `127.0.0.1:9080` (k3d-test serverlb). Config mount kalıcı (compose restart dayanıklı). **Gerçek edge smoke:** `/testai-healthz`→200 "testai-healthz" body, `/auth/actuator/health`→ K8s gateway JSON "JWT token zorunludur", `/reports`+`/schemas`→ 401 Spring Security. **compose fallback YOK** (drift #1 kapatıldı). `ai.acik.com` dokunulmadı (200+401 aynen). **Warning kalıntıları** (Seviye 1/2'ye ertelendi): Content-Type text/html vs application/json drift (gateway response header), auth/user/variant/core `/actuator/health` 200 vs report/schema 401 tutarsızlığı, calico-typha Tigera operator auto-recreate (Installation CR override — Seviye 2.5'e), ghcr-pull secret restore, Promtail sysctl fix, dev repo permission-service application-k8s.yml yok, OpenFGA enabled=false default, digest pin yok. **Seviye 0 PASS**; Seviye 1 Zanzibar runtime aktivasyonu sıradaki iş (permission-service manifest + OpenFGA enabled + auth-service hardcoded namespace temizliği). |
| 2026-04-19 | **Seviye 1 DEPLOY-ÖNCESİ KARAR KAYDI** (Codex 4-tur re-baseline Seri 2 + retrospektif ping-pong, aynı thread `019d9a75`). **Zanzibar-25 kapanışı:** platform-ssot'ta 14 PR merged (Dilim 1+2 K8s-ready + STORY-0319 prod-like + PR #502 permission-service application-k8s.yml + OI-03 canary PASS Evidence). **D32 eklendi:** External cloud/KMS REDDEDILDİ → kendi 2. fiziksel sunucu `staging-sw-2` (D1/D16/D18/D23 revize; **Bölüm 1.5 Bootstrap Kontrat Listesi F1-F9** yazıldı — Zanzibar-25 atlama pattern'inin tekrarlanmaması için). **4-tur mutabakat ekseni:** Seviye 1 minimal scope (permission-service + ZORUNLU core-data + variant ConfigMap + overlay test+prod), 2 katmanlı smoke (A. Hub cluster-direct port-forward `/actuator/health:8081`, `/authz/version`, `/authz/me`; B. Enforcement gateway token'lı `/variants` allow/deny), rollback **tek-commit revert** (selector delete yasak), D32 **paralel hat** (test Seviye 1 staging-sw'de devam). **Retrospektif ping-pong uzlaşı (4 madde):** (1) auth-service hardcoded NS default **bugün dev repo PR** paralel; (2) variant-service ConfigMap **ZORUNLU** (opsiyonel değil — `OpenFgaAuthzConfig` default `http://127.0.0.1:8091` self-call drift); (3) immutable tag **bugün** `sha-3923901` (`main-stable` D30 ihlal); (4) D32 kontrat listesi **bugün PLAN'e** (drift önleme). **Kritik düzeltmeler:** actuator health **management port 8081** (8090 değil), auth login `Set.of()` → auth→permission smoke proof değil (Hub cluster-direct zorunlu), gateway K8s GitOps'ta `/api/v1/authz/**` route yok (dev repo'da var, drift not — Seviye 2). **Kod sistemi:** `S<n>-<kategori><madde>` hiyerarşi; S1 = bugün Zanzibar runtime, S2 ops sertleşme, S3 stability soak, S4 cutover. Faz 5+6 REGRESSION → **S1'de FIX** (permission-service + OpenFGA enabled). Deploy-sonrası canlı sonuç ayrı entry olacak. |

| 2026-04-19 | **D33 Service Mesh REDDEDILDI** (`docs/adr/0001-service-mesh-rejected.md`, commit `2c45d81`). Istio/Linkerd/Consul Connect kurulumu red. Gerekçe 6 madde: D27 upstream-first + D22 CPU bütçesi (sidecar overhead 800MB RAM + 1600m CPU, 8 backend pod) + D25 MVP PoC + OpenFGA Zanzibar native authz yeterli + intra-cluster NetworkPolicy trust boundary + dış proxy TLS termination. Negatif kabul: mTLS yok (plaintext intra-cluster), distributed tracing manuel OTel, traffic management sınırlı (Argo Rollouts iç servis DRAFT + edge atomic cutover D30). Reversal koşulları ADR-0001 §Reversal (S5 post-cutover yeniden değerlendirme + Codex adversarial istişare). ADR dizini başlatıldı (`docs/adr/`) — MADR pattern. |
| 2026-04-19 | **S2-S5 repo-side materyal tam paket** (26 commit zinciri `3ab2b4d` → `c13dd2f`, user feedback "pause yasak, yol haritası tamamla" sonrası). **Day-2 ops 8 runbook:** cert-renewal + capacity-expansion + on-call-triage + DR + vault-audit + privileged-access + security-incident + on-call 14 alert karar matrisi. **Monitoring stack 3 sütun:** `promql-query-pack.md` (recording rule tablo dahil) + `logql-query-pack.md` (11 bölüm) + `traceql-query-pack.md` (7 bölüm OTel + sampling). **Grafana:** 4 dashboard ConfigMap (authz plane + platform pods + edge synthetic + JVM/DB/Hikari day-2) + 16 recording rule (hub/gateway/edge/pods/jvm/hikari/probe 7 grup pre-compute). **Backup freshness:** PrometheusRule 5 alert + `bootstrap/backup-freshness-exporter.sh` (node_exporter textfile). **Repo hygiene:** CI 5 job (kustomize-build + yaml-lint + shell-lint + closure-language-check + placeholder-leak-check) + `CLAUDE.md` agent kılavuzu + `CONTRIBUTING.md` workflow 9 adım + PR template + ISSUE template (bug+feature) + CODEOWNERS + dependabot + `README.md` genişletme + `CHANGELOG.md` Keep a Changelog + Namespace manifest (ApplicationSet prereq) + docs/README.md master index 24 doc + ingress-nginx metrics+serviceMonitor+server-tokens:false. **Kyverno admission policy DRAFT:** 5 ClusterPolicy (require-sha-image-tag D30 + disallow-privileged + require-non-root + require-resource-limits D22 + require-image-pull-policy) + helm-values + install-kyverno.sh + platform-policies Application. **Cert-manager DRAFT** (PLAN D8 Aşama 2): helm-values + 2 ClusterIssuer (staging+prod Let's Encrypt HTTP-01) + install-cert-manager.sh + platform-cert-manager Application. **ArgoCD ApplicationSet DRAFT** (D32 sonrası multi-cluster): platform-overlays + platform-eso + README aktivasyon. **k6 load test:** `tests/k6/zanzibar-load.js` (50 VU × 6dk + 5 threshold + 4 group + token cache). **ES automation:** `bootstrap/apply-eso-switch.sh` (7 servis idempotent swap). **Vault policy HCL versioned** (`bootstrap/vault-policies/eso-runtime.hcl` + README apply + AppRole test). **User feedback memory (4 kural):** no-closure-language + IP-sanitize + no-option-list + no-pause (bekleme YASAK, repo-side zincir devam). Canlı apply halen dev repo PR + Vault ops + D32 donanım bağımlı. **Kustomize build sanity:** tüm overlay + base/monitoring/eso/policies/cert-manager build PASS. |
| 2026-04-19 | **W1 ghcr-pull namespace fix + S3 doc drift + 2 runbook** (Codex iter-4 REVISE + iter-5 AGREE Opsiyon B, 3 commit `a486c42` + `41d17e9` + sonraki runbook). **İter-3 absorb (a486c42):** `helm-values/external-secrets/values.yaml` + `bootstrap/install-eso-helm.sh` (Helm upgrade + Deployment Ready bekle + NEXT STEPS) + `install-on-staging-sw-2.sh` F6 düzeltme (`base/eso` YASAK → `overlays/prod/eso`). **İter-4 REVISE tespit:** `base/eso` kustomization `namespace: external-secrets` zorlar → ghcr-pull Secret yanlış ns'de oluşurdu, ServiceAccount platform-*/ns'inde ghcr-pull aranır → pull FAIL. **İter-5 AGREE Opsiyon B absorb (41d17e9):** ghcr-pull ExternalSecret `base/eso` → `overlays/test/eso/` + `overlays/prod/eso/` (workload ns platform-test/platform-prod). Base/eso yalnız ClusterSecretStore (cluster-scope) + external-secrets ns admin. Per-service ES base/apps/<svc>/ altında namespace hardcode YOK, overlay set eder → W1 drift'ine sahip değil. **Apply doğrulama 3 katman** (install-eso-helm.sh + handoff-S2-B + S2-B1 güncel): ClusterSecretStore Ready + ES workload ns Synced + Secret workload ns + **cache-busting pull kanıtı** (Codex iter-5 uyarısı: "secret var" ≠ "pull auth çalıştı" — fresh tag/node cache temizle/`kubectl describe pod` Events). **S3 doc drift paralel fix:** `docs/S3-stability-soak-pack.md:196-201` eski `blackbox-config.yaml` + `zanzibar-authz-probe.yaml` referansları → fiili `blackbox-exporter.yaml` (tek dosya). **2 runbook yazıldı:** `docs/S4-rollback-runbook.md` (D30 72h warm rollback — 7-satır tetikleyici matrisi + 5 dk trafik geri alma + 72h warm window + doğrulama smoke + rollback senaryoları matrisi), `docs/D32-bootstrap-runbook.md` (F1-F9 tam adım-adım: süre + doğrulama komut + fail sinyali + devam eşiği + partial unwind tablosu Codex iter-5 step-wise geri dönüş). **Kustomize build sanity:** overlays/test/eso ClusterSecretStore (external-secrets ns, platform-test.svc FQDN) + ExternalSecret (platform-test ns) ✅, prod eşdeğeri ✅. |
| 2026-04-19 | **S2 no-closure drift + ESO overlay split + monitoring edge probe** (Codex iter-2 AGREE D+C absorb, 2 commit `0cdd116` + `25b3b4a`). **F+G:** 6 metin closure drift (PLAN.md:10/889/890/892 + handoff-smoke-client:12 + S2-A1-apply-plan:4) PASS tonuna çevrildi, commit `8e693d6` subject git-tarih (amend-rebase riski → dokunulmadı); test overlay üst yorum IP drift 10.9.10.53→platform-test-net 172.19.0.x (fiili Endpoints patch satır 240+ zaten doğru). **D ESO overlay split:** base `clustersecretstore-vault.yaml` FQDN → placeholder `vault.OVERLAY_MUST_OVERRIDE.svc:8200` (fail-closed, sessiz drift önlemi). Yeni `kustomize/overlays/test/eso/` + `overlays/prod/eso/` (base + `clustersecretstore-patch.yaml`). ArgoCD `platform-eso.yaml` → `platform-eso-test.yaml` rename + yeni `platform-eso-prod.yaml` (D30 selfHeal: false manuel sync). `docs/S2-B1-vault-property-matrix.md` apply sırası overlay path'e + base apply YASAK; `docs/S2-C-argocd-install-plan.md` manifest yapısı 6 Application. **C monitoring external edge:** `blackbox-exporter.yaml` 4 Probe (testai-deny/health + prod-deny/health) cluster-local FQDN kaldırıldı, 3 katman net ayrım (external edge authoritative + test cluster local kubectl-direct truth + prod→test peering GEREKSİZ). `zanzibar-stability-rule.yaml` alert rename ZanzibarAuthzSyntheticFail→ZanzibarEdgeSyntheticFail (regex job match `blackbox-(testai\|prod)-(deny\|health)`), PlatformTestPod* → PlatformPod* (namespace regex), `cluster_scope: same-cluster` label Hub/OpenFGA/Pod alertlerine. **Kustomize build sanity:** test overlay server platform-test.svc:8200 ✅, prod overlay platform-prod.svc:8200 ✅, monitoring 4 Probe + PrometheusRule render ✅. |
| 2026-04-19 | **S1 DEPLOY-SONRASI CANLI SONUÇ** — Tek atomic commit `ecc3935` (17 dosya). **Selective apply stratejisi uygulandı** (Codex ping-pong #2: full apply YASAK, mevcut 9/9 Running pod korundu). Sıra: permission_db CREATE (compose PG) → k3d image import `sha-3923901` (24bc8d61e255, staging-sw'de hazır) → python YAML split (awk bozuktu, 11 resource doğru extract) → `kubectl apply -f` her resource tek tek → scale replicas=1 → rollout restart auth/user/core-data/variant. **Tag drift runtime fix:** overlay'de `sha-3923901` ama staging-sw tar eskiydi → `kubectl set image` ile düzeltildi (pod recreate `24bc8d61e255`). **Kanıt:** permission-service 1/1 Running, ImageID `sha256:24bc8d61e255686e677e910fe663e17b9221b8aa489d008a89958e5569936ddf` (lokal), tag `sha-3923901`. **Env doğrulama:** SPRING_DATASOURCE_URL shortname (`postgres:5432/permission_db`), ERP_OPENFGA_ENABLED=true, PERMISSION_SERVICE_INTERNAL_API_KEY stub, PERMISSION_AUTHZ_USER_LOOKUP_BASE_URL shortname. **Smoke A (Hub cluster-direct):** `/actuator/health:8081 → 200` ✅, `/api/v1/authz/version:8090 → 401 JWT required` ✅ (endpoint aktif, auth chain doğru), `/api/v1/authz/me → 401` ✅. **Smoke B (Enforcement partial):** caller auth-service → permission-service:8081 mgmt `{"status":"UP"}` ✅, gateway `/variants` + `/auth/login` (no token) → **401 deny** ✅, testai edge `/auth/actuator/health → 200` ✅. **Zanzibar-ready (D29) partial**: Hub up + caller bağlantı + deny tarafı ✅; **allow tarafı için bilinen eksik** (smoke-client Keycloak confidential client yaratımı S2-B3 iş — admin-cli "direct grants disabled"). **Beklenmedik drift:** `testai/variants (no token) → 200` (variant SecurityFilter config veya gateway route şaibesi, Seviye 2'de follow-up). **W1 ghcr-pull dolaylı kapatıldı:** staging-sw docker GHCR login + image preloaded, ESO S2 iş. **Caller ConfigMap env pickup:** 4 pod rolling yeni env'le (`PERMISSION_SERVICE_BASE_URL=permission-service:8090` shortname). **Sonuç:** Dilim 1Z authz plane env **doğru**, Hub aktif, caller bağlantı intra-cluster çalışıyor, deny enforce kanıtlı; **allow synthetic + smoke-client S2**. S1 → S2 geçiş hazır. |
| 2026-04-29 | **D36 Image digest auto-sync (Renovate) D-kararı eklendi + Faz N (Renovate setup) roadmap'e işlendi.** **Tetikleyici:** D35-3 closure flow gözlemi — backend PR #18 (RequireModuleInterceptor relation + numeric userId fix, sha-12480ef) → image build PASS → **manuel** PR #242 digest pin → manuel pod rollout. Frontend tarafında da aynı drift gözlemlendi (gitops pin sha-57dc28e, GHCR sha-2dc3734 hazır, cluster manuel deploy farklı digest). PLAN.md line 810'da "image digest pin (CI günceller)" iddiası ile fiili manuel sync arasında gap. **Karar:** Renovate community-standard tool ile auto-bump bot. **D27 uyumlu** (custom kod değil, ArgoCD Image Updater'dan farklı — D27 yalnız onu YASAKLAMIŞ). **D30 atomic cutover discipline korunur**: test overlay PR auto-aç + reviewer approval + auto-merge=false; prod overlay PR ayrı (`user-approval-required` label otomatik + manuel review zorunlu). **BG-1.1 dependabot pattern'i** ile coverage (`pull_request_target` event + boundary block auto-fill). **Faz N roadmap'a eklendi** (Faz 10 ArgoCD Applications sonrası): renovate.json regexManagers + GitHub App + 4 kabul kriteri + cleanup. **Şu anki kritik path** (D35-3 FULL PASS) için manuel pin sync devam — Renovate setup ayrı initiative. **Cross-repo correlation:** platform-backend PR #18 + platform-k8s-gitops PR #242 (digest pin) + D35-3 first canlı evidence (#240) + amend (#241) + bu D-karar. |
| 2026-04-29 | **D37 Admin user OpenFGA tuple coverage discipline + DefaultAdminRoleAssignmentInitializer activation.** Tetikleyici: D35-3 FULL PASS sonrası kullanıcı browser session'da admin@example.com (user:1) için 403 toast tespit edildi. Sadece d35-admin-persona (user:1204) için organization:default#admin tuple manuel seedlenmişti; gerçek admin user için coverage yoktu. **Manual fix**: user:1, user:2, user:1204 için tuple seedlendi (programmatic chain ile verify). **Kalıcı fix**: PR #249 + #250 ile permission-service'in mevcut DefaultAdminRoleAssignmentInitializer'ı (Spring CommandLineRunner) ConfigMap üzerinden aktif edildi: `PERMISSION_BOOTSTRAP_DEFAULT_ADMIN_ASSIGNMENTS_ENABLED=true` + ADMIN_EMAILS=admin@example.com,d35-admin@example.com + USER_TABLE=users (permission_db.users primary datasource). Initializer pod startup'ta (a) email listesindeki user'lara DB ADMIN role assign, (b) OpenFGA organization:default#admin tuple ensure (idempotent writeTuple). Pod restart sonrası admin coverage otomatik onarılır — runtime drift'e karşı kalıcı koruma. **Idempotency stress-test**: tuple sil → pod restart → /check user:1 admin organization:default → allowed=true (auto-restore). **Geliştirme önerileri**: (a) DB-driven dinamik mod (yeni admin auto-discover), (b) DD-6 admin tuple coverage CI guard, (c) RoleChangeEvent listener (hot path). **27 PR landed Session 33 closure ramp**: cross-repo platform-backend (#18 fix + #19 DD-5 + #20 superAdmin bypass) + platform-k8s-gitops (#240/#241/#242/#243/#244/#245/#246/#247/#248/#249/#250). |
| 2026-05-01 | **Faz 22 Endpoint Admin Service Governance + ADR-0012-EA charter draft (Sprint Prod post-cutover compliance PR-8).** Yeni service: endpoint-admin-service (Go agent + Windows + REST/queue admin API). PR #270 governance mutabakat raporu (Codex 019dd895 iter-3 AGREE) ile kararlaştırılan 10 mutabakat noktası ADR draft'a aktarıldı: (1) manifest aynı repo G7 Operational Isolation, (2) OpenFGA tuple writer permission-service üstünden cross-service tuple discipline, (3) D35-EA ladder 0..5 + 5 destructive command sınıfı dual-control gate, (4) Code signing supply-chain RoT Azure Trusted Signing default, (5) 8 governance guard DD-EA-1..7 + BG-EA-1 ADR-0011 analog, (6) Pilot tier matrisi Lab/Pilot/Restricted, (7) Password reset 4 connector (Local/AD/Entra/M365), (8) Identity discovery parallel read-only + PII boundary, (9) ADR-0012-EA charter (DD-EA + BG-EA + D35-EA), (10) Manifest skeleton (Faz 22.1 lab tier) ayrı PR-9. **5 kullanıcı clarify pending** (ADR Open Questions): endpoint-admin repo URL/branch + admin auth realm + pilot tier başlatma + code signing provider + 5 domain inventory authoritative. **Sub-faz roadmap**: 22.0 charter+skeleton (PR-8/PR-9), 22.1 Lab tier (Parallels lab full destructive test), 22.2 Pilot tier (IT-owned domain VM read-only), 22.3 Restricted tier (gerçek user device). Bağımlılık: D30 prod deploy discipline (PR-2/PR-3 prod workflow) endpoint-admin live deploy için zorunlu (Codex 019de00f kabul). |
| 2026-05-02 | **Faz 22 ADR-0012-EA RESOLVED — 5 clarify cevabı absorb (Sprint PR-8b fill-in).** Kullanıcı 2026-05-02 mesajı ile 5 Open Questions cevaplandı; 4 cevap ADR draft'taki varsayımlardan **farklı** + 1 yeni bilgi (`platform-agent` ayrı repo). **Düzeltmeler**: (1) **REPO yapısı**: yeni ayrı `endpoint-admin-service` repo açılmayacak; 4-component yapısı: backend `Halildeu/platform-backend` `endpoint-admin-service/` sub-dir + agent `Halildeu/platform-agent` ayrı repo + web `Halildeu/platform-web` `apps/mfe-endpoint-admin/` + gitops `Halildeu/platform-k8s-gitops`. (2) **AUTH REALM**: prod=`serban` canonical platform realm (Keycloak built-in `master` realm KULLANILMAYACAK), test=`platform-test`, ayrı client opsiyonel `endpoint-admin-portal`. (3) **PILOT TIER**: 22.1 Lab (Parallels lab + lab-only-evidence imza, gerçek kullanıcı yok, password reset YOK) → 22.2 IT-owned `acik.local` domain-joined Windows 10/11 + ayrı `EndpointPilot` OU + 1-3 test cihaz + agent enrollment/heartbeat/inventory/identity discovery → 22.3 Restricted (sınırlı gerçek kullanıcı + EDR allowlist + IT onayı şart). **BOREAS ve CESS Faz 22 dışı**. (4) **CODE SIGNING**: Azure Trusted Signing 22.2'den itibaren mandatory, 22.1 self-signed `lab-only-evidence`. **Önemli**: signing key Vault/ESO runtime secret olarak taşınMAZ — supply-chain RoT, build-time CI pipeline (`platform-agent` + `platform-backend` CI workflow). ConfigMap `COSIGN_KEY_REF` SADECE public key reference (Azure KMS URI). Secret stub'tan `COSIGN_KEY_PEM` field'ı KALDIRILDI. (5) **DOMAIN INVENTORY**: 5 değil **3 domain** mevcut (`acik.local` + `BOREAS` + `CESS`). Initial scope **sadece acik.local** (22.1 + 22.2). BOREAS/CESS future expansion (3-domain inventory ID-001). Authority modeli: probe-based read-only evidence + IT manager review gate. **Manifest düzeltmeleri**: configmap.yaml `DISCOVERY_AD_ACIK_LOCAL_ENABLED` field eklendi (22.2'de overlay aktif), Entra/M365 `Faz 22.3+` notu, `COSIGN_LAB_ONLY_EVIDENCE` flag (22.1 true, 22.2+ false); secret-stub.yaml `AGENT_ENROLLMENT_SECRET` eklendi (`platform-agent` registration token), `COSIGN_KEY_PEM` kaldırıldı. ADR Open Questions → Resolved Questions; Sonuç (DRAFT) → Sonuç (ACTIVE). Sub-faz roadmap finalized: 22.1 platform-agent skeleton + Parallels lab, 22.2 acik.local + Azure Trusted Signing, 22.3 sınırlı gerçek kullanıcı. |
| 2026-06-02 | **Mavis adversarial review — Faz 22.PW/STT PARTIAL verdict revision absorbed.** Root session adversarial review (2026-06-02) PARTIAL verdict: 2 revision gerekli. **Revision 1**: KVKK ADR-0030 placeholder kesildi — ses + transcript KVKK Madde 6/9 kapsamında hassas veri; GOP BASI (observability pipeline ses/transcript yazmaz; yalnızca metadata); saklama süresi, yetkilendirme, silme talebi, veri paylaşım limiti dokümante edilecek; production gate KVKK uyumluluk kapalı. **Revision 2**: Gateway contract önce kilitlenir (PR-gw-01 Contract 1.0 merged), sonra PR-stt-02 paralel başlar — eş zamanlı contract drift riski önlenir. **Ek notlar**: (B) staging-sw RAM pressure acceptance gate olmalı (23 GiB RAM, Faz 22.5 + Faz 23 notify + STT PoC paralel); (C) multilingual: Turkce sabit yetersiz, per-meeting language (ISO 639-1) contract'ta ZORUNLU; (D) transcript data en hassas alan — kimin okuduğu (participant/IT admin), export sınırı, meeting katılımcı consent vs şirket IT access sınırı KVKK ADR'ye eklendi; (E) multi-tenant isolation: Faz 24.1 MVP tek müşteri ise TBD ama future readiness placeholder ADR-0030'da. **Sonuç**: 2 revision absorb → AGREE. KVKK ADR: [`docs/adr/0030-kvkk-stt-voice-transcript-compliance.md`](docs/adr/0030-kvkk-stt-voice-transcript-compliance.md). |

| 2026-05-02 | **Faz 22 ADR-0012-EA scope clarify (Sprint PR-8c) — 22.1 sıfırdan değil.** Kullanıcı 2026-05-02 ikinci mesajı ile 3 yanlış varsayım düzeltildi: (1) `Halildeu/platform-agent` GitHub remote yok ≠ "agent repo yok"; **lokal** `/Users/halilkocoglu/Documents/platform-agent` mevcut ve dolu (Go repo + HMAC signing + signed heartbeat/command poll/result submit + Windows service wrapper + installer scriptleri + local user read-only adapter + log/redaction + tamper protection + maintenance token local Windows testleri). 22.1 sıfırdan skeleton DEĞİL — local state review + remote bootstrap + build/release pipeline hardening. (2) **Backend sıfırdan değil**: BE-009 OpenFGA live gate + BE-013 maintenance token live gate kod-test ve gitops runtime kanıtları MEVCUT. 22.1'de bu gate'ler paralel ilerleyebilir; "backend 22.2'ye kalır" yanlış çerçeveydi. (3) **22.1 scope tablosu** (PR-8c clarify): agent ana track (lab/release hattı) + backend paralel (BE-009/BE-013 live gate) + gitops manifest reconcile (mevcut endpoint-admin-service skeleton PR #312) + AD/IT (EndpointPilot OU + 1-3 test cihaz hazırlığı); web 22.2'ye kalır. **Acik.local ölçeği**: ~800 cihaz domain'inde; pilot **EndpointPilot OU** + 1-3 IT kontrollü Windows 10/11 test cihaz; domain-wide deployment 22.3+. **Naming convention**: repo geniş tutulur (`platform-agent` — ileride macOS/Linux), binary endpoint odaklı (`endpoint-agent.exe` + `EndpointAgent` Windows service). **Build artifact + distribution**: 22.1 GitHub Releases (private asset) + lab-only-evidence flag; 22.2 Authenticode signed exe + MSI/signed zip + GPO/Intune; 22.3 signed MSI + signed update manifest + SBOM + Intune/GPO/SCCM staged rollout. **GHCR ana kanal değil agent binary için** (container image değil). **ADR §Bağlam clarify**: "manifest aynı repo + repo bölünmez" → "Runtime manifest tek yerde gitops, source kod ilgili platform repolarında; 'repo bölünmez' ifadesi YALNIZ GitOps manifest governance için." Sıralama B→A→C: B (bu PR) ADR clarify; A platform-agent local state review + GitHub remote bootstrap; C Codex plan-time istişare (düzeltilmiş bağlam ile 22.1 sub-tracks AGREE). |
