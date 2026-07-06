# Session Handoff — 2026-06-03 — AG-028 Phase 2A başlangıcı

> Format: D28 5-alan handoff + sıradaki agent P0 aksiyon listesi.

## 1. Bağlam

AG-028 Managed Uninstall multi-phase chain. Faz 22.5.6. Board #1239.

Bu oturumda AG-028 backend tarafı **tam tamamlandı**:

1. **Phase 0** — Catalog uninstall flags + change-request flow (platform-backend #399 MERGED)
2. **Phase 1a** — V32 uninstall surface schema + JPA mapping (platform-backend #404 MERGED)
3. **Phase 1b** — Service + REST + sanitizer + tests (platform-backend #415 MERGED iter-2 absorb)
4. **Phase 1b follow-up** — Detection-rule authority gate (platform-backend #419 — CI pending merge)
5. **Phase 2 plan-time AGREE** — Codex thread `019e8de2` iter-2 (3-PR chain locked)

Backend AG-028 contract'i complete: catalog flag flow + propose/approve maker-checker + capability/heartbeat/provenance/authority gates + sanitizer (UninstallEvidencePayloadPolicy) + V32 audit table hazır. Sırada agent (Phase 2A) + backend ingest wire (Phase 2B) + LIVE smoke (Phase 4).

## 2. İddia (MERGED PR'lar bu session)

| PR | Repo | Title | Status |
|---|---|---|---|
| #399 | platform-backend | AG-028 Phase 0 catalog uninstall flags + change-request maker-checker | MERGED 2026-06-03 |
| #404 | platform-backend | AG-028 Phase 1a V32 uninstall surface schema + JPA mapping | MERGED 2026-06-03 |
| #415 | platform-backend | AG-028 Phase 1b managed uninstall propose/approve flow | MERGED 2026-06-03 (iter-2 absorb) |
| #419 | platform-backend | AG-028 Phase 1b follow-up detection-rule authority gate | CI pending |

Archive tag'leri (cross-machine 1+ yıl recovery hazır):
- `archive/2026/06/feat-ag-028-phase-0-v3-claude-2026-06-03-pr399`
- `archive/2026/06/feat-ag-028-phase-1a-claude-2026-06-03-v2-pr404`
- `archive/2026/06/feat-ag-028-phase-1b-claude-2026-06-03-pr415`

## 3. İspatlar

### Lokal evidence

- **53/53 PASS** Phase 1b follow-up: 14 service + 4 ff-off + 5 controller + 20 policy + 10 command
- **99/99 PASS** Phase 1b iter-2: 51 Phase 1b + 48 regression
- **24/24 PASS** Phase 1a V32 PG IT
- **12/12 PASS** Phase 0 V31 PG IT + service + controller

### CI evidence

- PR #399 (Phase 0): 13/13 PASS
- PR #404 (Phase 1a): 13/13 PASS
- PR #415 (Phase 1b): 13/13 PASS
- PR #419 (Phase 1b follow-up): CI pending (Monitor active)

### Cross-AI consensus (Codex MCP)

| Thread | Iterations | Final | Konu |
|---|---:|---|---|
| `019e8c10` | 6 | AGREE | Phase 0 plan-time |
| `019e8d5b` | 2 | AGREE | Phase 0 post-impl |
| `019e8c8a` | replay | AGREE | Phase 0 finalize |
| `019e8d81` | 2 | AGREE | Phase 1 plan-time |
| `019e8d95` | 2 | AGREE | Phase 1a post-impl |
| `019e8dcd` | 2 | AGREE | Phase 1b post-impl |
| `019e8de2` | 2 | **AGREE** | **Phase 2 plan-time (3-PR chain locked)** |

## 4. İspatlamaz (pending)

- **Phase 1b-follow-up merge** — PR #419 CI pending (Monitor active), Codex AGREE alındı, CI yeşil olur olmaz normal squash merge
- **Phase 2A** — Agent UNINSTALL_SOFTWARE adapter + ProbeState + capability advertise (platform-agent)
- **Phase 2B** — Backend ingest minimal PR (`EndpointAgentCommandService.submitResult` UNINSTALL branch + `EndpointUninstallAuditService` + request state terminal)
- **Phase 4** — Gitops digest pins + LIVE acceptance smoke (HALILKOOLUB735 7-Zip uninstall E2E)
- **Pre-LIVE prereq** — 7-Zip catalog WINGET_PACKAGE → REGISTRY_UNINSTALL migration + noop INSTALL_SOFTWARE on HALILKOOLUB735 (provenance enabler)
- **Phase 3 (Web)** — `platform-web mfe-endpoint-admin`: catalog admin panel + per-device "Kaldır" button + audit panel + i18n TR/EN

## 5. Bilinen boşluk + Sıradaki agent için P0 aksiyon listesi

### P0 — Phase 2A platform-agent implementation (Codex `019e8de2` iter-2 AGREE locked)

**Branch öneri:** `feat/ag-028-phase-2a-uninstall-adapter-claude-<YYYY-MM-DD>` (HARD RULE — session-id veya timestamp suffix R-CONTRACT-2 mitigation)

**Scope (~15 file, ~2000 satır):**

1. **`internal/winget/uninstall_winget.go`** core (cross-platform):
   - `Uninstall(ctx, req UninstallRequest) -> UninstallResult`
   - `ProbeState` enum (`MATCHED / ABSENT / PRESENT_MISMATCH / AMBIGUOUS / ERROR / UNSUPPORTED`)
   - `UninstallProbeResult{state, authority, safeEvidence}` absence-aware wrapper (Codex iter-1: `PreDetectResult.Satisfied=false ≠ ABSENT`)
   - `UninstallResult` payload: finalStatus, schemaVersion, supported, failedReasonCode, exitCode, durationMs, killStrategy, probeState, authority, safeEvidence

2. **`internal/winget/uninstall_winget_windows.go`** runner:
   - 30-min hard cap (Codex: kalsın, MSI uninstall'lar uzayabilir)
   - Job Object + taskkill fallback parity ile install
   - HKLM + WOW6432Node uninstall key scan (HKCU dışarıda, Codex iter-1 absorb)
   - WINGET_PACKAGE detection rule → top'ta `FAILED_UNSUPPORTED_VERIFICATION` (no mutation; Codex: backend gate zaten redde, agent defense in depth)

3. **`internal/winget/uninstall_winget_other.go`** non-Windows stub:
   - `FAILED_UNSUPPORTED_PLATFORM`

4. **Args preset `UNINSTALL_DEFAULT`** (install DEFAULT'tan AYRI):
   ```go
   uninstall --id <pkg> --exact --source winget --silent
     --accept-source-agreements --disable-interactivity
   ```
   Hard-coded argv (shell injection imkansız).

5. **Core flow** (Codex iter-1 final absorb):
   - Validate payload (intent=UNINSTALL, provider=WINGET, packageId, requestId, detectionRule, argsPolicyPreset=UNINSTALL_DEFAULT)
   - Validate detection authority: REGISTRY_UNINSTALL + FILE_* allowed; WINGET_PACKAGE → FAILED_UNSUPPORTED_VERIFICATION
   - Pre-probe → ABSENT skip (SUCCEEDED) / MATCHED proceed / PRESENT_MISMATCH proceed / AMBIGUOUS+ERROR fail-precheck / UNSUPPORTED fail-closed
   - Run winget uninstall (bounded stdoutSummary/stderrSummary only)
   - Post-probe → ABSENT verified (Codex: **`SUCCEEDED_VERIFIED + exitCode!=0` if absent**, exit non-zero anomaly safeEvidence'a kayıt) / MATCHED → FAILED_VERIFY_GHOST / PRESENT_MISMATCH → PARTIAL_RESIDUE / AMBIGUOUS+ERROR+UNSUPPORTED → PARTIAL_INCONCLUSIVE
   - Timeout/cancel → kill tree + PARTIAL_INCONCLUSIVE (failedReasonCode=uninstall_timeout|uninstall_cancelled)

6. **`internal/commands/executor.go`** UNINSTALL_SOFTWARE dispatch case (parity with INSTALL_SOFTWARE)

7. **`internal/inventory/inventory.go`** `RuntimeCapabilities()` — Windows build'de `UNINSTALL_SOFTWARE` advertise (Codex: sadece dispatch edilebilir capability ekle; non-Windows'a eklenmesin; executor case landed olmadan capability eklenmesin)

8. **`internal/config/config.go`** `UninstallCommandTimeout` (parity with INSTALL); HMAC runner + auto-enroll runner timeout seçimi güncelle

9. **`internal/protocol`** `CommandUninstallSoftware` constant + payload shape

10. **Tests** (~5 dosya):
    - `uninstall_winget_test.go`: absent skip, matched run, present_mismatch run, ambiguous no-mutation, exit-0-ghost, post-absent, timeout-kill, non-zero+post classifications
    - `uninstall_winget_other_test.go`: FAILED_UNSUPPORTED_PLATFORM
    - `executor_test.go`: UNINSTALL_SOFTWARE payload decode + dispatch + status mapping
    - `capability_coherence_test.go`: mevcut guard yeni capability'yi yakalar
    - File/registry probe tests: absent vs mismatch ayrımı (FILE_SHA256, FILE_VERSION)

11. **Docs:**
    - `docs/COMMAND-CONTRACT.md` yeni §AG-028 (parity §7 INSTALL)
    - `docs/TESTING-STRATEGY.md` yeni §uninstall test strategy

### P0 — Phase 2B platform-backend ingest (sequential, Phase 2A sonrası)

**Scope:**

1. `EndpointAgentCommandService.submitResult(...)` UNINSTALL_SOFTWARE branch:
   - `UninstallEvidencePayloadPolicy.validate(...)` + `redact(...)` wire'a bağla
   - `EndpointUninstallAuditService.recordUninstallResult(...)` yeni service (parity install audit service)
   - `EndpointUninstallRequest.state` terminal transition: `RUNNING → TERMINAL` (success/failure flag finalStatus'tan)

2. `endpoint_uninstall_audit` row insert (V32 schema hazır)

3. Mapping: `SKIP_ALREADY_ABSENT + ABSENT_VERIFIED` (Codex iter-1 önerisi)

4. **Tests:**
   - `EndpointAgentCommandServiceUninstallBranchTest`: sanitizer-before-persist
   - `EndpointUninstallAuditServiceTest`: resultStatus / verification / evidence mapping
   - `UninstallEvidencePayloadPolicyTest` extend (zaten 20 case var)
   - Controller test: result path canonical `/api/v1/agent/commands/{commandId}/result`

### P0 chain (sıralı)

1. Phase 1b-follow-up #419 merge (CI yeşil olunca; bu session'da otomatik)
2. **Phase 2A platform-agent** PR
3. **Phase 2B platform-backend ingest** PR
4. **Phase 4 LIVE smoke**: gitops digest pin (backend + agent) + cluster apply + HALILKOOLUB735 7-Zip uninstall E2E

### Pre-LIVE prereq

HALILKOOLUB735'te 7-Zip catalog detection rule **WINGET_PACKAGE → REGISTRY_UNINSTALL** migration:
- Phase 0 change-request flow ile catalog re-author
- Noop `INSTALL_SOFTWARE` çalıştır (provenance enabler — V12 audit row gerek)
- Phase 4 öncesi sıralı task

### Plan reference (canonical)

- Plan-time AGREE: Codex thread `019e8de2-cf3c-7d80-8a31-823fafcbc3ed` iter-2
- Phase chain referansı: 3-PR (2A agent + 2B backend ingest + 4 LIVE smoke)
- Implementation pattern reference:
  - `platform-agent/internal/winget/install_winget.go` (cross-platform core)
  - `platform-agent/internal/winget/install_winget_windows.go` (Windows runner Job Object + taskkill)
  - `platform-agent/internal/winget/install_winget_other.go` (non-Windows stub)
  - `platform-agent/internal/commands/executor.go` INSTALL_SOFTWARE case (mirror)
  - `platform-agent/internal/inventory/inventory.go:699` `RuntimeCapabilities()` (where to add UNINSTALL_SOFTWARE)
  - `platform-agent/internal/config/config.go:29` (where to add UninstallCommandTimeout)
  - `platform-backend/.../UninstallEvidencePayloadPolicy.java` (Phase 2B wire-binding endpoint)
  - `platform-backend/.../EndpointInstallAuditService.java` (Phase 2B audit service parity)

### Yeni Session Açılışı

```bash
cd /Users/halilkocoglu/Documents/platform-agent
git checkout main && git pull
git checkout -b feat/ag-028-phase-2a-uninstall-adapter-claude-2026-06-04

# Plan-time AGREE thread:
# Codex MCP threadId: 019e8de2-cf3c-7d80-8a31-823fafcbc3ed
# İlk Codex iter mevcut session sonunda final AGREE verdi; impl direkt başlayabilir.

# Handoff doc:
cat /Users/halilkocoglu/Documents/platform-k8s-gitops/docs/session-handoff-2026-06-03-ag028-phase2a.md
```

### HARD RULE'lar uyarı (yeni session için)

- **CI Kırmızıyken Merge YASAK** (2026-05-17)
- **Admin Merge YASAK** (2026-05-05)
- **Cross-AI Peer Review zorunlu** (provider-distinct, 2026-05-14)
- **No Fake Work** (test koşmadan green claim YASAK)
- **Browser test zorunlu** (2026-05-11 — frontend etkileyen iş için)
- **Continuous Autonomous Mode** + **Plan Consensus Autonomy** (Codex AGREE → impl direct, kullanıcıya plan onayı sormama)
- **Yarın YASAK / şimdi yap**
- **Workspace tooling = Microsoft Teams** (Slack YASAK)
- **TEST cluster scale-to-zero YASAK**
- **Mavis CLI default kanal** (multi-session koordinasyon için, secret payload --content'e YASAK)

Phase 2A başlatılabilir — plan AGREE locked, blocker yok.
