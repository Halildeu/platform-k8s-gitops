# Session Handoff — 2026-06-03 — AG-028 Phase 2B başlangıcı

> Format: D28 5-alan handoff + sıradaki agent P0 aksiyon listesi.
> Codex Phase 2 plan-time AGREE thread `019e8de2-cf3c-7d80-8a31-823fafcbc3ed` iter-2; iter-3 post-impl AGREE Phase 2A için locked.

## 1. Bağlam

AG-028 Managed Uninstall multi-phase chain. Faz 22.5.6. Board platform-k8s-gitops #1239.

Bu oturum (Session 2026-06-03 - 5-PR session) AG-028 zincirini büyük ölçüde tamamladı:

- **Phase 0** — Catalog uninstall flags + change-request maker-checker (platform-backend #399 MERGED)
- **Phase 1a** — V32 uninstall surface schema + JPA mapping (platform-backend #404 MERGED)
- **Phase 1b** — Service + REST + sanitizer + tests (platform-backend #415 MERGED iter-2 absorb)
- **Phase 1b follow-up** — Detection-rule authority gate (platform-backend #419 MERGED)
- **Phase 2A** — Agent UNINSTALL_SOFTWARE adapter + ProbeState + capability (platform-agent #51 MERGED iter-3 absorb)
- **Handoff doc PR** — Phase 2A başlangıç (platform-k8s-gitops #1251 MERGED)

5 PR MERGED, 1 docs PR MERGED. ~5000+ satır kod, ~150 test, 8 Codex thread iter consensus (her biri AGREE'ye konsolide).

Sırada **Phase 2B platform-backend ingest minimal**. Codex Phase 2 plan-time AGREE'de locked.

## 2. İddia (MERGED PR'lar bu session)

| PR | Repo | Title | Squash | Archive Tag |
|---|---|---|---|---|
| #399 | platform-backend | AG-028 Phase 0 catalog flags + change-request | `d73d74c7` | `archive/2026/06/feat-ag-028-phase-0-v3-claude-2026-06-03-pr399` |
| #404 | platform-backend | AG-028 Phase 1a V32 schema + JPA | `370b2791` | `archive/2026/06/feat-ag-028-phase-1a-claude-2026-06-03-v2-pr404` |
| #415 | platform-backend | AG-028 Phase 1b propose/approve | `a95ac78c` | `archive/2026/06/feat-ag-028-phase-1b-claude-2026-06-03-pr415` |
| #419 | platform-backend | AG-028 Phase 1b follow-up authority gate | `afb9ff6e` | `archive/2026/06/feat-ag-028-phase-1b-followup-authority-gate-claude-2026-06-03-pr419` |
| #51 | platform-agent | AG-028 Phase 2A agent adapter + ProbeState | `f0336e44` | `archive/2026/06/feat-ag-028-phase-2a-uninstall-adapter-claude-2026-06-03-pr51` |
| #1251 | platform-k8s-gitops | Handoff docs Phase 1b → 2A | `843e006e` | `archive/2026/06/docs-session-handoff-ag028-phase2a-claude-2026-06-03-pr1251` |

## 3. İspatlar

### CI evidence (her PR için her check yeşil)

- #399 (Phase 0): 13/13 PASS
- #404 (Phase 1a): 13/13 PASS
- #415 (Phase 1b): 13/13 PASS (iter-2 absorb)
- #419 (Phase 1b follow-up): 13/13 PASS
- #51 (Phase 2A agent): 6/6 PASS (Go build + test + cross-build + SBOM + signing + boundary + cross-AI audit)
- #1251 (handoff docs): 9/9 PASS (gitops governance)

### Local test evidence

- Phase 0: 12/12 (8 PG IT + 2 service + 2 MockMvc)
- Phase 1a: 12/12 (PG IT)
- Phase 1b iter-2: 51 Phase 1b + 48 regression = 99/99
- Phase 1b follow-up: 14 service + 4 ff-off + 5 controller + 20 policy + 10 command = 53/53
- Phase 2A agent: 18/18 uninstall + full agent suite (21 packages) + capability coherence

### Cross-AI consensus (Codex MCP)

| Thread | Iterations | Final | Konu |
|---|---:|---|---|
| `019e8c10` | 6 | AGREE | Phase 0 plan-time |
| `019e8d5b` | 2 | AGREE | Phase 0 post-impl |
| `019e8c8a` | replay | AGREE | Phase 0 finalize |
| `019e8d81` | 2 | AGREE | Phase 1 plan-time |
| `019e8d95` | 2 | AGREE | Phase 1a post-impl |
| `019e8dcd` | 2 | AGREE | Phase 1b post-impl |
| `019e8de2` | 3 | **AGREE** | **Phase 2 plan-time + 2A post-impl** |

## 4. İspatlamaz (pending)

- **Phase 2B** — platform-backend ingest minimal: NOT STARTED, branch açılmadı, scope locked (Codex iter-2 + iter-3 findings)
- **Phase 3 (Web)** — platform-web mfe-endpoint-admin: NOT STARTED
- **Phase 4 LIVE** — gitops digest pin + HALILKOOLUB735 7-Zip uninstall E2E: blocked by Phase 2B
- **Pre-LIVE prereq** — 7-Zip catalog WINGET_PACKAGE → REGISTRY_UNINSTALL migration + provenance enabler: blocked by Phase 2B

## 5. Bilinen boşluk + Sıradaki agent için P0 aksiyon listesi

### P0 — Phase 2B platform-backend ingest minimal (Codex `019e8de2` iter-2 + iter-3 findings)

**Branch öneri:** `feat/ag-028-phase-2b-backend-ingest-claude-<YYYY-MM-DD>` (HARD RULE — branch session-id/timestamp suffix R-CONTRACT-2 mitigation)

**Scope (~600-800 satır, ~6 yeni file + 4 modified):**

#### 5.1. `EndpointAgentCommandService.submitResult(...)` UNINSTALL_SOFTWARE branch

Mirror INSTALL_SOFTWARE pattern (commands service line 274-289 + 458-462). 3 yeni constructor dep + 1 yeni branch:

```java
// Constructor: + UninstallEvidencePayloadPolicy uninstallEvidencePayloadPolicy
//              + EndpointUninstallAuditService uninstallAuditService

// L274 region: validate + redact for UNINSTALL_SOFTWARE (parity INSTALL)
if (command.getCommandType() == CommandType.UNINSTALL_SOFTWARE
        && request.details() != null) {
    try {
        uninstallEvidencePayloadPolicy.validate(request.details());
    } catch (IllegalArgumentException ex) {
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, ex.getMessage());
    }
    effectiveDetails = uninstallEvidencePayloadPolicy.redact(request.details());
}

// L458 region: audit row + request state terminal (same transaction)
if (command.getCommandType() == CommandType.UNINSTALL_SOFTWARE
        && isTerminalResult(request.status())) {
    uninstallAuditService.recordUninstallResult(
            command, result, request, effectiveDetails, now);
}
```

#### 5.2. `EndpointUninstallAuditService` (new, ~250 satır parity install audit)

`platform-backend/endpoint-admin-service/src/main/java/com/example/endpointadmin/service/EndpointUninstallAuditService.java`

```java
@Service
public class EndpointUninstallAuditService {
    @Transactional(propagation = MANDATORY)
    public EndpointUninstallAudit recordUninstallResult(
            EndpointCommand command,
            EndpointCommandResult result,
            AgentCommandResultRequest request,
            Map<String, Object> redactedDetails,
            Instant now) {
        // 1. Resolve EndpointUninstallRequest by command.id (V32 schema FK)
        // 2. Extract finalStatus + probeState from redactedDetails.uninstall
        // 3. Map finalStatus → UninstallResultStatus enum
        // 4. uninstallEvidencePayloadPolicy.deriveVerification(redactedDetails) → UninstallVerification
        // 5. SKIP_ALREADY_ABSENT special case: finalStatus=SKIP_ALREADY_ABSENT + verification=ABSENT_VERIFIED
        // 6. INSERT endpoint_uninstall_audit (V32 append-only trigger blocks updates)
        // 7. UPDATE endpoint_uninstall_requests.state → TERMINAL + state_updated_at=now
        // 8. Emit BE-016 hash-chain audit event ENDPOINT_UNINSTALL_RESULT_RECORDED
        // 9. Return persisted audit row
    }
}
```

Mapping (Codex iter-3):
- `SUCCEEDED_VERIFIED` → `UninstallResultStatus.SUCCEEDED_VERIFIED` + verification from `deriveVerification(probeState=ABSENT) = ABSENT_VERIFIED`
- `SKIP_ALREADY_ABSENT` → `UninstallResultStatus.SKIP_ALREADY_ABSENT` + `verification=ABSENT_VERIFIED` (no-mutation preserves info via finalStatus)
- `PARTIAL_RESIDUE` → `UninstallResultStatus.PARTIAL_RESIDUE` + `verification=RESIDUE_PRESENT`
- `PARTIAL_INCONCLUSIVE` → `UninstallResultStatus.PARTIAL_INCONCLUSIVE` + `verification=VERIFY_INCONCLUSIVE`
- `FAILED_VERIFY_GHOST` → `UninstallResultStatus.FAILED_VERIFY_GHOST` + `verification=PRESENT_VERIFIED` (post-probe MATCHED)
- `FAILED_EXIT` → `UninstallResultStatus.FAILED_EXIT` + verification from deriveVerification (likely PRESENT_VERIFIED)
- `FAILED_PRECHECK_INCONCLUSIVE` → same status + verification=VERIFY_INCONCLUSIVE
- `FAILED_UNSUPPORTED_PLATFORM` → same status + verification=NOT_RUN
- `FAILED_UNSUPPORTED_VERIFICATION` → same status + verification=NOT_RUN

#### 5.3. `EndpointUninstallService.buildUninstallPayload(...)` — argsPolicyPreset (Codex iter-2 finding #3)

```java
private Map<String, Object> buildUninstallPayload(...) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("intent", "UNINSTALL");
    payload.put("requestId", req.getId().toString());
    payload.put("argsPolicyPreset", "UNINSTALL_DEFAULT");  // ← yeni (Codex iter-2)
    // ... rest unchanged
}
```

Agent unmarshalUninstallRequest `argsPolicyPreset` zorunlu bekliyor; bu fix olmadan canlı dispatch path agent payload decode'da düşer.

#### 5.4. `UninstallEvidencePayloadPolicy.KNOWN_AUTHORITIES` (Codex iter-2 finding #4)

```java
private static final Set<String> KNOWN_AUTHORITIES = Set.of(
        "REGISTRY_UNINSTALL",
        "WINGET_PACKAGE",
        "FILE_EXISTS",
        "FILE_SHA256",
        "FILE_VERSION",
        "CONFIRM_ONLY",
        "AUTHORITATIVE"  // ← yeni (Codex iter-2)
);
```

Agent `DetectionReliabilityAuthoritative = "AUTHORITATIVE"` gönderiyor; mevcut allow-list'te yok → backend sanitiser dropping.

#### 5.5. (Opsiyonel) `preProbe/postProbe` allow-list veya rename to summary

Codex iter-2 finding #5: agent `preProbe + postProbe + stdoutTail + stderrTail` gönderiyor, backend allow-list'te yok → silently drop. Karar:
- Option A: backend allow-list'e ekle (`ALLOWED_UNINSTALL_KEYS += preProbe + postProbe`; backend redactor için tail strict guard'la)
- Option B: agent değişiklik, `stdoutTail/stderrTail` yerine `stdoutSummary/stderrSummary` üret (AG-028 follow-up agent PR)

Tercih: Option A `preProbe/postProbe` nested projection (parity ALLOWED_POSTVERIFY_KEYS pattern), `stdoutTail/stderrTail` dropped (defense in depth — backend redactor weaker than agent AG-027L; follow-up backend redactor için ayrı task).

#### 5.6. Tests (~150 satır)

- `EndpointAgentCommandServiceUninstallBranchTest` — sanitizer called before result row persist; forbidden key → 400 rollback; audit service called only terminal
- `EndpointUninstallAuditServiceTest` — resultStatus + verification + evidence mapping for each finalStatus; SKIP_ALREADY_ABSENT special case
- `UninstallEvidencePayloadPolicyTest` extend — AUTHORITATIVE in KNOWN_AUTHORITIES; preProbe/postProbe projection (if Option A)
- `EndpointUninstallServiceTest` extend — buildUninstallPayload assertion: `payload.get("argsPolicyPreset") == "UNINSTALL_DEFAULT"`

### P0 chain sıralı

1. Phase 2B SOURCE-MERGED + Codex post-impl AGREE
2. Phase 4 — gitops digest pin (backend + agent) + cluster apply + LIVE smoke
3. Pre-LIVE prereq: HALILKOOLUB735 7-Zip catalog WINGET_PACKAGE → REGISTRY_UNINSTALL migration via Phase 0 change-request flow + noop INSTALL_SOFTWARE (provenance enabler)
4. Phase 3 (Web) — `platform-web mfe-endpoint-admin` catalog admin panel + per-device "Kaldır" button + audit panel + i18n TR/EN

### Plan reference (canonical)

- **Plan-time AGREE**: Codex thread `019e8de2-cf3c-7d80-8a31-823fafcbc3ed` iter-2 + iter-3 (Phase 2A post-impl)
- **Implementation pattern reference**:
  - `EndpointAgentCommandService.submitResult` INSTALL_SOFTWARE branch (mirror pattern)
  - `EndpointInstallAuditService.recordInstallResult` (parity audit service)
  - `InstallEvidencePayloadPolicy` ↔ `UninstallEvidencePayloadPolicy` (already partially built)

### Yeni Session Açılışı

```bash
cd /Users/halilkocoglu/Documents/platform-backend
git checkout main && git pull
git checkout -b feat/ag-028-phase-2b-backend-ingest-claude-2026-06-04

cat /Users/halilkocoglu/Documents/platform-k8s-gitops/docs/session-handoff-2026-06-03-ag028-phase2b.md
```

Plan-time AGREE Codex thread `019e8de2` iter-2'de mevcut; impl direkt başlayabilir (Plan Consensus Autonomy + Continuous Autonomous Mode).

### HARD RULE'lar reminder (yeni session için)

- CI Kırmızıyken Merge YASAK (2026-05-17)
- Admin Merge YASAK (2026-05-05)
- Cross-AI Peer Review zorunlu (provider-distinct, 2026-05-14)
- No Fake Work (test koşmadan green claim YASAK)
- Browser test zorunlu (frontend için)
- Continuous Autonomous Mode + Plan Consensus Autonomy
- Yarın YASAK / şimdi yap
- Workspace tooling = Microsoft Teams
- Mavis CLI default kanal (multi-session koordinasyon)

Phase 2B başlatılabilir — plan AGREE locked, blocker yok.
