# Session Handoff — 2026-06-04 — AG-028 Phase 2B SOURCE+LIVE + release.yml fix

> Format: D28 5-alan handoff + sıradaki agent P0 aksiyon listesi.
> Board: platform-k8s-gitops #1239 (AG-028 multi-PR chain). Faz 22.5.6.

## 1. Bağlam

Bu oturum AG-028 Managed Uninstall zincirinin **backend yarısını tamamen LIVE'a** taşıdı ve yolda keşfedilen bir red-on-main workflow bug'ını düzeltti. Önceki oturumlar Phase 0/1a/1b/1b-followup/2A'yı SOURCE-MERGED bırakmıştı; bu oturum Phase 2B'yi yazdı + merge etti + **testai cluster'a deploy edip V31/V32/V33 migration'larını canlı çalıştırdı**.

## 2. İddia (bu oturumda MERGED + LIVE)

| PR | Repo | Konu | Squash | Durum |
|---|---|---|---|---|
| **#441** | platform-backend | AG-028 Phase 2B UNINSTALL_SOFTWARE terminal-result ingest | `25042f6a` | MERGED |
| **#1259** | platform-k8s-gitops | endpoint-admin-service sha-25042f6 (V31/V32/V33 deploy) | `3f65103d` | MERGED + LIVE |
| **#52** | platform-agent | release.yml here-string → .ps1 (invalid-YAML red-on-main fix) | `90ccd7b2` | MERGED |

3 PR MERGED, hepsi provider-distinct cross-AI AGREE, hepsi archive-tag'li.

## 3. İspatlar

### Phase 2B backend (#441)
- CI **13/13 SUCCESS** (Maven full reactor 12 modül + endpoint-admin-service unit+slice + 4 cross-service Testcontainers + governance).
- Full `endpoint-admin-service` modülü **1599 test yeşil** (0 fail / 0 error).
- Cross-AI: Codex `019e8f9c` **REVISE → AGREE**. REVISE absorb = cross-field consistency matrix (verification artık `resultStatus`'ten deterministik türetiliyor, bağımsız `probeState` okuması değil; drift altında fail-closed, `FAILED_EXIT` clamp ile non-zero exit asla `ABSENT_VERIFIED` okumaz). iter-2 non-blocker doc-drift de düzeltildi.

### Phase 4 LIVE deploy (#1259) — testai k3d-test
- D30: pod imageID `sha256:278aea19f65e…dcde2` == pinned digest.
- Flyway: **V31 + V32 + V33** → `Successfully applied 3 migrations, now at version v33`. V32 = `endpoint_uninstall_surface` (requests + audit tabloları + closed result_status/verification CHECK enum + append-only trigger) transactional CREATE TABLE çalıştı.
- D29 Up: pod Running 1/1, `Started EndpointAdminServiceApplication in 91.8s`.
- D29 Functional: actuator `{"status":"UP"}` (:8081); uninstall route `/api/v1/admin/endpoint-devices/{id}/uninstalls` → **401 (kayıtlı, 404 değil)**.
- Clean boot: 0 ERROR/Exception/FATAL.

### release.yml fix (#52)
- Kök neden: "Emit RELEASE_NOTES.md" adımı YAML `run: |` block scalar içinde column-0 PowerShell here-string (`@"…"@`) kullanıyordu — `"@` terminatörü column-0 zorunlu, block scalar ile uyumsuz → Faz 22.1'den beri **invalid workflow file**, her main push'ta 0s "workflow file issue" fail. #51 dokunmamıştı (pre-existing).
- Fix: here-string → `scripts/release/emit-release-notes.ps1` (sibling `patch-installer-manifest.ps1` pattern), `pwsh scripts/release/...` ile çağrı, `${{ github.repository }}` → `$env:REPO`. Notes içeriği byte-identical.
- Cross-AI: Codex `019e9198` **AGREE** (no must-fix).
- Kanıt: pre-fix her main push `failure | push` release.yml run üretiyordu; post-fix HEAD `90ccd7b2` **hiç release.yml run üretmiyor** (valid YAML → phantom validation-failure yok). red→green.

## 4. İspatlamaz (pending — operator/Windows/computer-use-bound)

AG-028 backend plane LIVE; ama **uçtan uca gerçek uninstall** henüz koşulmadı. Eksikler:

- **Feature flag**: `endpoint-admin.uninstall.enabled` testai'de hâlâ `false` (503). REST propose/approve dark mode.
- **Pre-LIVE prereq**: 7-Zip catalog detection rule `WINGET_PACKAGE` → `REGISTRY_UNINSTALL` migration. Authority gate `WINGET_PACKAGE`'ı reddediyor (CONFIRM_ONLY tier `ABSENT_VERIFIED` sertifikalayamaz). + provenance enabler (bir SUCCEEDED+SATISFIED install audit row gerek).
- **Agent**: HALILKOOLUB735 (Parallels W11) şu an **eski** agent binary'sini koşuyor (AG-037 dönemi); Phase 2A (#51) `UNINSTALL_SOFTWARE` capability'sini advertise eden yeni binary deploy edilmedi. Approve gate capability+heartbeat guard → yeni binary olmadan 422.
- **Phase 3 Web**: `platform-web mfe-endpoint-admin` uninstall UI (per-device "Kaldır" button + propose/approve + audit panel + i18n) — NOT STARTED.

## 5. Bilinen boşluk + Sıradaki agent için P0 aksiyon listesi

### P0 chain (sıralı) — AG-028 full E2E

1. **Agent binary deploy** (computer-use/prlctl): Phase 2A `endpoint-agent.exe` (CI build job 26895685194 SUCCESS artifact'i VEYA local `GOOS=windows GOARCH=amd64 go build`) → HALILKOOLUB735'e transfer → install → heartbeat'te `UNINSTALL_SOFTWARE` capability advertise doğrula (`mavis`/prlctl + backend heartbeat payload check).
   - NOT: release.yml artık valid; bir `v0.1.0-lab.N` tag push'u ile signed binary üretilebilir (tercih), VEYA manuel cross-compile (pratik yol, prior #58/#122/#135 pattern).
2. **7-Zip catalog migration**: Phase 0 change-request flow ile detection rule `WINGET_PACKAGE` → `REGISTRY_UNINSTALL`; + noop `INSTALL_SOFTWARE` ile uninstall provenance seed.
3. **Feature flag enable**: testai overlay/env `endpoint-admin.uninstall.enabled=true` (per-tenant). Kustomize ConfigMap selective apply + rollout restart.
4. **Full uninstall E2E**: propose → approve (maker-checker, farklı subject) → dispatch `UNINSTALL_SOFTWARE` → agent ProbeState execute → terminal-result ingest → `endpoint_uninstall_audit` row (resultStatus/verification consistency matrix) + request state→TERMINAL.
5. **Browser smoke** (HARD RULE Tarayıcıdan Sonuç Doğrulanmadan): testai endpoint-admin UI'da uninstall sonucu görünür + audit panel render + console clean.

### P1 — Phase 3 Web (paralel, agent-doable)

`platform-web mfe-endpoint-admin` uninstall surface: per-device "Kaldır" button + propose dialog + approve flow + audit panel + i18n TR/EN + MockMvc/RTL tests. Code → CI → cross-AI → image → gitops digest pin → testai apply → browser smoke. (Feature flag P0.3 sonrası full-functional smoke mümkün.)

### Yeni Session Açılışı

```bash
cd /Users/halilkocoglu/Documents/platform-agent
git checkout main && git pull
# Phase 2A binary: ya tag push (release.yml artık valid) ya local cross-compile
GOOS=windows GOARCH=amd64 go build -o /tmp/endpoint-agent.exe ./cmd/endpoint-agent

cat /Users/halilkocoglu/Documents/platform-k8s-gitops/docs/session-handoff-2026-06-04-ag028-phase2b-live.md
```

### HARD RULE'lar reminder (yeni session)
- CI Kırmızıyken Merge YASAK · Admin Merge YASAK · Cross-AI Peer Review (provider-distinct)
- No Fake Work · Browser smoke zorunlu (frontend) · Continuous Autonomous Mode + Plan Consensus Autonomy
- TEST cluster scale-to-zero YASAK · Yarın YASAK / şimdi yap · Workspace tooling = Microsoft Teams
- Kullanıcı aktif credential'ına dokunma YASAK (test persona kullan)

Plan-time AGREE referansları: Codex `019e8de2` (Phase 2 plan) + `019e8f9c` (Phase 2B post-impl consistency matrix). AG-028 backend plane LIVE — sıradaki = full E2E (operator/Windows) + Phase 3 Web.
