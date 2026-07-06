# Faz 22.5 Consensus Gate Tracker — M2-M7 + #1359

> **Status**: ACTIVE (Session 51 — 2026-05-28; Codex thread `019ea916` plan-time AGREE absorb)
> **Issue**: [#1375](https://github.com/Halildeu/platform-k8s-gitops/issues/1375) Faz 22.5 consensus gate tracker — M2-M7 full-consensus protocol
> **Scope**: Faz 22.5 milestone gate'lerinin (M2/M5/M6/M7/#1359) **source-side LIVE vs operator-gate** boundary matrix; agent-otonom slice + operator-bound condition + consensus verdict ledger
> **Related**: ADR-0029 (Plan A mass deployment), faz-22-software-deployment-plan.md §0.1bis Truth Refresh 2026-05-29, current-state.md
> **HARD RULE Tam Otonom (2026-05-28)**: Operator-gated kalemler için "kullanıcıya iş yıkma" YASAK; agent organize path zorunlu

---

## 1. Tracker amacı

Faz 22.5 M2-M7 gate'leri **full-consensus protocol** (Claude + Codex + Mavis 3-AI mutabakat) ile yönetiliyor. Bu doc her gate için **source vs operator boundary** matrisini, agent-doable slice'ları, operator-bound condition'ları, consensus verdict'i, blocking issue'ları ve closure acceptance kriterini tek satır altında konsolide eder.

**Anti-pattern engeli**: "operator action gerek" tek satır YASAK — her gate için **agent organize path** + bounded operator dependency açıkça yazılır (HARD RULE Tam Otonom).

**Source vs Closure ayrımı**: Gate closure = source-side LIVE **+** operator-gate evidence proof. Source-side merge tek başına acceptance DEĞİL.

---

## 2. Gate Boundary Matrix

### M2 — AD CS / edge mTLS enrollment finalization (#1376)

| Boyut | Durum |
|---|---|
| **Source-side LIVE** | RB-faz22.3-ad-cs-setup.md (7-section operator runbook MERGED PR #1080); AD CS preflight scripts (scripts/faz22-mass-deployment/ad-cs-preflight.ps1 + enroll-endpoint-agent-cert.ps1 + verify-machine-cert.ps1 MERGED 2026-05-26 PR #1078); RB-faz22.3-edge-mtls-autoenroll.md (dedicated host runbook); ADR-0029 source-side referans (Plan A mass deployment + 22.3 path) |
| **Desired state** | DNS record `<edge-mtls-host>.acik.com` resolved; server cert/key path mounted; client CA bundle deployed; valid machine cert end-to-end issuance (agent → CA Web Enrollment → certreq); edge NGINX dedicated host TLSv1.3 + client cert verify on; spoof-header negative test PASS |
| **Live state** | Source slice LIVE; runtime DNS+cert+CA evidence operator-bound (bkz #1359 dependency) |
| **Operator-gate condition** | (a) DNS record yayını (corp DNS admin), (b) AD CS rol install + Enterprise CA + Web Enrollment endpoint LIVE (Windows Server admin), (c) corp-issued client CA bundle export + edge mount, (d) valid machine cert reproduce (agent test PC enrollment chain) |
| **Agent-otonom slice** | (1) edge NGINX template patch + `nginx -t` validate; (2) script holding (preflight + enroll + verify); (3) doc/runbook truth-sync; (4) header spoof negative + no-cert negative smoke planı; (5) `curl --resolve` lokal diagnostic helper; (6) PR commit chain + Codex post-impl iter + merge |
| **Consensus verdict** (Claude + Codex + Mavis) | Source-side AGREE; operator-gate boundary explicit (Codex `019ea916` AGREE "agent backend/agent/GitOps/runbook truth-sync, edge NGINX template, spoof-header negative test planı, cert validation contract") |
| **Blocking issue** | #1359 tokenless AutoEnroll DNS + edge mTLS host activation (operator DNS+cert) |
| **Closure acceptance** | DNS yayını + AD CS Web Enrollment endpoint LIVE + machine cert end-to-end issuance + edge mTLS server-side acceptance + spoof-header negative + no-cert negative + ≥1 test PC agent autoenrollment proof |

### M5 — selected-device same-day GPO pilot smoke gate (#1377)

| Boyut | Durum |
|---|---|
| **Source-side LIVE** | ADR-0029 GPO Software Installation pattern (canonical); RB-faz22.3-ad-cs-setup.md §6 (group policy section); scripts/faz22-mass-deployment/ MSI WiX wrapper (operator-bound source) |
| **Desired state** | Owner-approved same-day pool: `AGENTPC1`, `AGENTPC2`, local Parallels Windows, denetim PC. Domain-gpo denominator counts only domain-joined GPO-scoped devices; local Parallels is control evidence unless domain-joined. GPO Software Installation deploy + tokenless enrollment + T0/T+15/T+60 collector evidence; no 24h wait for this run |
| **Live state** | Source slice LIVE (ADR-0029 + AD CS runbook); selected-device pilot operator-bound |
| **Operator-gate condition** | (a) selected device access, (b) domain admin pilot OU create + GPO link for domain-gpo devices, (c) EDR allowlist whitelist (Defender/CrowdStrike/Sentinel/ESET as applicable), (d) WDAC/AppLocker code-signing policy build, (e) same-day T0/T+15/T+60 monitoring + abort threshold ledger |
| **Agent-otonom slice** | (1) selected-device matrix design (role/denominator split); (2) sanitized evidence pack template (gpresult + Event ID Application Installer + EndpointAgent heartbeat + COLLECT_INVENTORY post-install); (3) same-day collector script `m5-same-day-pilot-collector.ps1`; (4) wave abort formula + threshold; (5) board/Mavis handoff format; (6) PR + Codex/Claude iter + merge |
| **Consensus verdict** | Original source consensus was 5-PC/operator-gated; then superseded by board #1377 owner amendment to 2-PC/24h; now superseded again by owner no-24h same-day pool direction. Source path acceptable only if no-24h risk is explicit and M6 expansion carries risk acceptance or later stabilization gate |
| **Blocking issue** | #1376 (AD CS M2) prerequisite + IT pilot allocation |
| **Closure acceptance** | Domain-gpo denominator frozen + domain-gpo enrollment/GPO install LIVE + selected-device T0/T+15/T+60 collector evidence + one-device rollback/reinstall drill + abort threshold ledger + sanitized evidence pack + `same_day_smoke=true`, `soak_hours=0`, no-24h risk note + Mavis ops sign-off |

### M6 — 50-PC capacity baseline + wave abort evidence (#1378)

| Boyut | Durum |
|---|---|
| **Source-side LIVE** | ADR-0029 ramp 50/800 plan; capacity/runbook scaffold (mevcut faz-22-software-deployment-plan.md §4 milestone 22.5.8 Controlled Rollout Policies referans); backend BE-026-029 source (rollout controls) |
| **Desired state** | 50 PC wave deploy (M5 same-day pilot sonrası, only with explicit no-24h risk acceptance or later stabilization gate); capacity baseline measure (heartbeat ingest rate + COLLECT_INVENTORY frequency + agent CPU/mem/disk); wave abort formula validate + throttling/ring config; pause/resume controls |
| **Live state** | Source slice partial (BE-026-029 source-merged); 50-PC fiziksel ramp operator-gated |
| **Operator-gate condition** | (a) 50 PC IT pilot wave allocation, (b) ring config (group A 10 + group B 20 + group C 20), (c) capacity baseline metrics (Prometheus dashboards + alerts), (d) wave abort decision tree + Mavis ops on-call rotation, (e) throttling guardrails (max concurrent install per ring) |
| **Agent-otonom slice** | (1) capacity baseline runbook draft (PromQL + Grafana dashboards + SQL queries); (2) wave abort formula (failure_rate + heartbeat_loss + queue_depth thresholds); (3) synthetic or existing telemetry rehearsal (mevcut HALILKOOLUB735 + Parallels VM data ile dry-run); (4) throttling/ring config kubeconfig + ConfigMap; (5) ring rollout sequencer script; (6) board handoff Mavis ops; (7) PR + Codex iter + merge |
| **Consensus verdict** | Source AGREE; operator-gated acceptance (Codex "Operator-gated acceptance. 50 cihaz gerçek rollout olmadan PASS denmez"). Agent path = capacity/runbook/dashboards/SQL/PromQL + abort formula + rehearsal |
| **Blocking issue** | M5 (#1377) prerequisite + 50 PC IT allocation + Mavis on-call rotation |
| **Closure acceptance** | 50/50 PC enrollment + heartbeat ingest rate ≥ 95% + capacity baseline measured + wave abort formula validated (1+ controlled abort drill) + throttling config LIVE + Mavis ops sign-off |

### M7 — Rollback drill: MSI uninstall + enrollment revoke + GPO rollback (#1379)

| Boyut | Durum |
|---|---|
| **Source-side LIVE** | ADR-0029 rollback strategy (rollback section); AG-028 testai go-live (uninstall MERGED 2026-06-04); enrollment revoke API (backend); GPO rollback DC pattern (ADR-0029) |
| **Desired state** | Rollback drill 3 layer: (a) MSI uninstall agent-side (signed self-update revoke); (b) enrollment revoke backend-side (token invalidate + ledger proof); (c) GPO rollback DC-side (Software Installation policy un-link or computer object move to non-pilot OU) |
| **Live state** | AG-028 testai uninstall LIVE; enrollment revoke source partial; GPO rollback operator destructive (domain admin) |
| **Operator-gate condition** | (a) lab-clone rollback rehearsal environment from the selected M5 pilot, (b) domain admin GPO rollback authority, (c) Mavis ops coordination (rollback decision tree), (d) destructive action checklist (uninstall + revoke + rollback chronological order) |
| **Agent-otonom slice** | (1) lab-clone rollback rehearsal runbook (RB-faz22.5-m7-rollback-drill.md draft); (2) revoke API + ledger proof contract (backend endpoint + audit row); (3) rollback runbook (exact abort/restore checklist); (4) Mavis/board coordination format; (5) PR + Codex iter (destructive action plan-time AGREE) + merge |
| **Consensus verdict** | Source partial; operator/destructive-gated (Codex "Operator/destructive gate. MSI uninstall + enrollment revoke + GPO rollback domain tarafında destructive sayılır"). Agent path = lab-clone rehearsal + revoke contract + rollback runbook + Mavis coordination |
| **Blocking issue** | M5+M6 (#1377+#1378) prerequisite + IT lab environment + domain admin authority |
| **Closure acceptance** | 1+ lab-clone drill 3-layer rollback PASS (uninstall + revoke + GPO rollback) + audit ledger proof + Mavis ops sign-off + destructive action checklist LIVE |

### #1359 — Endpoint Agent tokenless AutoEnroll DNS / edge mTLS host activation

| Boyut | Durum |
|---|---|
| **Source-side LIVE** | RB-faz22.3-edge-mtls-autoenroll.md (dedicated host runbook + positive/negative smokes); ADR-0029 SAN URI:adcomputer:{objectGUID} primary identity; edge NGINX template (header stripping pattern); agent --auto-enroll source slice (canonical platform-agent PR pending) |
| **Desired state** | DNS record `<autoenroll-edge>.acik.com` resolved; server cert/key Vault mount; client CA bundle deployed; valid machine cert SAN URI:adcomputer:{objectGUID} agent-side issuance; edge dedicated host TLSv1.3 client cert verify on; spoof-header negative PASS |
| **Live state** | Source slice ready; runtime DNS+cert+CA operator-bound |
| **Operator-gate condition** | (a) DNS record creation + propagation (corp DNS admin), (b) server cert/key path provision (Vault seed), (c) client CA bundle export + edge mount, (d) AD CS Web Enrollment LIVE (M2 dependency), (e) valid machine cert chain (test PC enrollment) |
| **Agent-otonom slice** | (1) edge config patch + `nginx -t`; (2) no-cert negative smoke; (3) header spoof negative smoke; (4) `curl --resolve` lokal diagnostic; (5) DNS yayılımı sonrası public smoke checklist; (6) RB §4 acceptance evidence template; (7) PR + Codex iter + merge |
| **Consensus verdict** | Source AGREE; operator-gated closure (Codex "Operator-gated closure. DNS record, server cert/key path, client CA bundle ve valid machine cert private key gerekiyor") |
| **Blocking issue** | M2 (#1376) AD CS prerequisite + DNS admin coordination |
| **Closure acceptance** | DNS resolution LIVE + server cert/key mount + client CA bundle + agent --auto-enroll source PR + valid machine cert end-to-end + edge mTLS LIVE + spoof negative + no-cert negative PASS |

---

## 3. Source vs Operator-Gate Summary

| Gate | Agent-otonom slice DONE | Operator-gate condition | Closure status |
|---|---|---|---|
| **M2** (#1376) | RB + scripts + ADR + Codex consult ✅ | DNS + AD CS + CA + cert | ⏳ pending operator |
| **M5** (#1377) | Same-day matrix + collector + evidence pack template ⏳ DRAFT | selected devices + EDR + WDAC + T0/T+15/T+60 smoke | ⏳ pending operator |
| **M6** (#1378) | Capacity runbook + abort formula ⏳ DRAFT | 50 PC IT + on-call rotation | ⏳ pending operator |
| **M7** (#1379) | Lab-clone runbook + revoke contract ⏳ DRAFT | Lab env + domain admin | ⏳ pending operator |
| **#1359** | Edge NGINX + smoke templates ✅ | DNS + cert + CA + agent --auto-enroll source | ⏳ pending operator |

**Agent-otonom completed**: M2 source (✅) + #1359 source (✅)
**Agent-otonom pending follow-up**: M5/M6/M7 source slice runbook drafts

---

## 4. Operator Dependency Roll-up (HARD RULE Tam Otonom — agent organize path)

Anti-pattern engeli: Aşağıdaki operator dependency'ler **board issue + Mavis ops coordination + agent-prepared evidence pack** ile organize edilir. Tek satır "kullanıcı yapsın" YASAK.

### Dependency #D1 — DNS records (M2 + #1359)

- **Agent organize path**: corp DNS admin board issue (target: `<edge-mtls-host>.acik.com` + `<autoenroll-edge>.acik.com` A records); Mavis ops handoff; DNS propagation monitor script (`scripts/faz22-mass-deployment/check-dns-propagation.sh` agent-doable)
- **Operator action**: corp DNS server entry create (Windows DNS console veya BIND zone file)
- **Acceptance**: `dig +short <host>.acik.com` → IP, ≥10 dk propagation

### Dependency #D2 — AD CS Enterprise CA (M2)

- **Agent organize path**: RB-faz22.3-ad-cs-setup.md mevcut (7-section); preflight script `ad-cs-preflight.ps1` agent-doable; Codex consult for tenant-level CA hierarchy
- **Operator action**: Windows Server admin role install (Server Manager → Add Roles → Active Directory Certificate Services → Enterprise CA + Web Enrollment)
- **Acceptance**: `certutil -ping` resolve + Web Enrollment URL accessible

### Dependency #D3 — Client CA bundle export + edge mount (M2 + #1359)

- **Agent organize path**: export script `scripts/faz22-mass-deployment/export-client-ca-bundle.ps1` agent-doable (DC-side `certutil -ca.cert` + base64); edge mount template Vault seed pattern; ESO ExternalSecret config
- **Operator action**: DC remote PowerShell session OR file transfer (SMB/SFTP) for bundle copy; Vault stdin-pipe seed (D43 pattern, no-token-log)
- **Acceptance**: edge container `/etc/nginx/ssl/client-ca-bundle.pem` non-empty + `openssl verify -CAfile` self-test

### Dependency #D4 — IT pilot PC allocation (M5 + M6 + M7)

- **Agent organize path**: selected-device matrix doc + IT board issue + Mavis ops coordination + sanitized evidence pack template (gpresult + Event ID + heartbeat collectors)
- **Operator action**: selected devices allocate/access (M5) + 50 PC ramp (M6) + lab-clone rollback environment (M7); pilot OU create + GPO link; EDR allowlist
- **Acceptance**: PC list (asset tag + AD object + assigned IT contact) + pilot OU MEMBER OF GPO

### Dependency #D5 — Mavis ops coordination (M5+M6+M7)

- **Agent organize path**: Mavis CLI peer message pattern (`mavis communication send --to <peer> --command prompt --content "<redacted handoff>"`); board issue cross-link; on-call rotation schedule doc
- **Operator action**: Mavis ops sign-off per gate (M5 same-day no-24h smoke gate + M6 50-PC wave abort + M7 rollback drill)
- **Acceptance**: board issue Mavis comment + sign-off date + decision provenance

---

## 5. Cross-AI Consensus Protocol Per Gate

Codex `019ea916` AGREE: "Codex consult per issue makul ama her küçük doc edit için değil. `#1373`, `#1376`, `#1379` gibi prod/security/destructive sınırda plan-time AGREE gerekir."

**Gate-level plan-time consult zorunlu** (destructive/security/prod sınır):
- M2 (#1376) — security (edge mTLS + AD CS) → Codex thread per source slice
- M7 (#1379) — destructive (uninstall + revoke + GPO rollback) → Codex plan-time AGREE şart
- #1359 — security (tokenless DNS+cert) → Codex consult per acceptance gate

**Doc-only edit consult-required değil** (M5 evidence pack template, M6 capacity runbook draft) — Plan Consensus Autonomy gereği impl direkt.

**Named provider attribution** (HARD RULE Cross-AI Peer Review): Codex thread ID + verdict per PR audit trail.

---

## 6. CI / Billing Status Note (Codex `019ea916` flag)

current-state.md billing blocker uyarısı: account-wide Actions spending limit aktif olabilir; CI/merge/deploy standard signal etkilenmiş olabilir. Agent PR hazırlığı + local gates çalıştırma yapılabilir; **standard CI backfill veya merge/deploy iddiası owner/billing çözülmeden kapanış kanıtı olmaz**.

Bu nedenle bu tracker'daki source-side LIVE iddialarının "merge + CI green" boyutu billing dependency'ye tabidir.

---

## 7. Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session 51 Faz 22 otonom chain
- **Reviewer (plan-time)**: Codex (OpenAI GPT-5.2) thread `019ea916`
- **Verdict**: AGREE source-side scope + operator-gate boundary explicit per gate

Acceptance: Bu doc Faz 22.5 M2-M7 + #1359 için **canonical source-vs-operator boundary tracker**'dır. Gate closure her zaman source-side LIVE **+** operator-gate evidence proof gerektirir (Codex No Fake Work HARD RULE — source merge tek başına acceptance DEĞİL).
