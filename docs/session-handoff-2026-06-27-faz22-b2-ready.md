# Session Handoff — 2026-06-27 (v2) — Faz 22 tamamlama → B2 (#1580) build-ready

> Format: D28 5-alan + sıradaki agent için P0 aksiyon listesi.
> Önceki handoff: [`docs/session-handoff-2026-06-27-faz22-completion.md`](session-handoff-2026-06-27-faz22-completion.md) (#2074). **Bu doc onun delta'sıdır** — o handoff'ta "P0 başlanmadı" denen **B0 + B1 tamamlandı (MERGED)**; bu doc B2'yi (build-ready, tasarım bağlı) sıradaki taze session'a devreder.
> Canonical eylem planı: [`docs/faz-22-completion-action-plan.md`](faz-22-completion-action-plan.md).
> Governing kural: [`docs/adr/0044-faz22-6-kvkk-nonblocking-parametric-durations.md`](adr/0044-faz22-6-kvkk-nonblocking-parametric-durations.md) (#2076).

---

## 1. Bağlam (neden bu handoff)

Standing /goal: **"Faz 22.6 öncelikli olmak üzere Faz 22'nin tamamını sektör standartlarına uygun, sistemle uyumlu, uzun-vadeli kalıcı, en iyi uygulamaları barındıran şekilde tam otonom tamamla."**

Önceki handoff'tan (#2074) sonra bu oturum **governance + makine-zorlaması (B0) + durable drift kilidi (B1)** zincirini kapattı ve **B2'nin (#1580 VIEW_ONLY) ilk slice tasarımını cross-AI ile bağladı**. Kullanıcı **"hand off"** dedi. B2 = ~3-5 eng-haftalık, **güvenlik-hassas** gRPC/Spring inşası (no-control invariant + no-persistence proof + permit-gating + bounded-backpressure concurrency); bu oturum çok derin → kural gereği ("uzun-vadeli kalıcı — integrity işini acele etme") build **taze odaklı session**'da, **bu doc'taki bağlı tasarımdan** başlar (sıfırdan değil).

**Kritik çalışma kuralı (her tuzakta tekrarlandı):** her okuma/iş **`origin/main`** taze worktree'sinden yapılır — paylaşılan checkout (`/Users/halilkocoglu/Documents/platform-k8s-gitops`) kirli + paralel-session olabilir; ASLA oradan checkout/commit etme. Codex MCP'nin cwd'si paylaşılan checkout → ona **hangi tree'yi okuyacağını açıkça söyle** (bu oturumda Codex bir kez 149-satırlık eski state-only audit'i okuyup yanlış-pozitif marker-gap raporladı; origin/main'deki marker-hardened audit ile düzeltildi — o an 861 satır; B0/B1 sonrası 1190 satır).

---

## 2. İddia (bu oturumda yapılan — MERGED)

| PR | Repo | Ne | Durum |
|---|---|---|---|
| **#2076** | gitops | **ADR-0044** — KVKK non-blocking allowlist (D1) + #1580 marker split ENGINEERING:v2/KVKK:v1 + legacy fail-safe (D2) + parametric durations + recording-OFF default (D3) + F22_6_COMPLETION KVKK'yı dışlar (D4) + recording_mode=disabled negatif kanıt (D5) + #1580 state secondary (D6); 6 acceptance kriteri | ✅ MERGED |
| **#2079** | gitops | **B0** — VIEW_ONLY marker split makine-zorlaması: `check_view_only_engineering_gate` (v2, fail-closed, recording-mode-aware, 5-token negatif-matris) + `check_view_only_kvkk` (v1, tracked non-blocking; yalnız `allowlist_violation` bloklar) + `verify_view_only_evidence_manifest` v2 (mode-aware) + legacy `F22_6_VIEW_ONLY_ACCEPTANCE`→`legacy_bundled_marker_detected` + evidence/decision generator v2 + contract §7/§9 split + 4 test | ✅ MERGED |
| **#2101** | gitops | **B1** — #2067 durable digest-drift guard **eliminasyonla** (Codex verdict **C** = drift kaynaklarını yok et): tek SSOT = render'lanan overlay; `lib-remote-bridge-digest.sh` (her iki overlay render + primary==bridge zorla) → audit `expected_digest`'i **türetir** (literal yok); env-override yalnız `diagnostic_pass` (asla canonical, her zaman `return 1`); live check exact JSON+jq per-object (grep-count masking yerine); ES `Ready/SecretSynced` per-name `es_ready` (boş-conditions bypass kapatıldı); apply + gate workflow render-derive + path-trigger; yeni test | ✅ MERGED |

**Global kural eklendi** (`~/.claude/CLAUDE.md`): **"Credential/Güvenlik İşlemleri Ortam-Kapsamlı: PROD Kritik, TEST Serbest (2026-06-27)"** — credential/secret/security mutasyonu TEST'te otonom, PROD'da owner-gated; ölçüt ortam; plaintext sızdırma + login-user-credential dokunma her ortamda yasak.

**Cross-AI (gerçek thread'ler):** `019f05cc` (ADR-0044 design), B0 post-impl REVISE×2→AGREE, B1 `019f0733`/`019f07..` verdict C + post-impl REVISE×2→AGREE, **`019f078a`** (B2 slice-1 architecture **AGREE-to-implement**).

---

## 3. İspatlar (canlı/merged kanıt)

- **B0 + B1 + ADR-0044 tümü MERGED, CI-yeşil** (no `--admin`, no red/pending-merge). Required gate'ler: `ADR-0011 BG-1 boundary`, `cross-ai-audit`, `remote-bridge-digest-alignment` — her PR'da `success` (son B1 CI poll çıktısı: `{"success":20}` + 3 gate `success`).
- **B1 durable guard canlı-doğru:** `scripts/governance/lib-remote-bridge-digest.sh` her iki overlay'i render edip tek endpoint-admin digest çıkarıyor + primary==bridge zorluyor; audit artık literal digest taşımıyor → **bir sonraki endpoint-admin V-bump'ta sessiz re-drift imkânsız** (kullanıcının "gene versiyon karışması mı" şikâyetinin kök kalıcı kilidi). `tests/governance/test_remote_bridge_digest_alignment.sh` lib/guard/evaluate/env-override/apply-default kapsıyor.
- **REMOTE_BRIDGE_LIVE hâlâ pass** (önceki handoff'taki component-verified durum korunuyor; B1 onu artık **türetilen** expected ile makine-kilitledi).
- **B2 transport zaten var (re-baseline düzeltmesi):** platform-backend `origin/main`'de DATA stream **çalışıyor** — `RemoteBridgeConnectService` DATA frame'leri valide edip `dataPlane.onDataFrame(...)` çağırıyor; `DurableRecordingDataPlaneHandler` **var + wired** (`remote-bridge.enabled=true` iken, default FALSE). Önceki "DataPlaneHandler tamamen inert" varsayımı **eskimiş**. Eksik olan: **live fanout (viewer registry) + recording-OFF mode + disabled-mode metadata-audit**.

---

## 4. İspatlamaz (henüz kanıtlanmamış — fail-closed/owner-gated)

- **#1580 VIEW_ONLY runtime** — kod yok (slice-1 tasarımı bağlı ama implement edilmedi); ~3-5 eng-hafta build. Marker `F22_6_VIEW_ONLY_ENGINEERING:v2` **forge edilemez** (B0 fail-closed).
- **#548-A hardware-attestation marker** — owner-gated (A1 Vault gate-B). Canlı TPM session + cert + V74 binding A1 olmadan üretilemez; marker forge edilemez (contract §9).
- **KVKK (artık blocker DEĞİL):** ADR-0044 D1 gereği KVKK kalemleri F22_6_COMPLETION'ı bloklamaz; yalnız `allowlist_violation` bloklar. KVKK 5-madde owner/hukuk işi **paralel** ilerler, mühendislik tamamlanmasını geciktirmez.

---

## 5. Bilinen boşluk + sıradaki agent için P0 aksiyon listesi

### Agent (sıradaki taze session yürütür) — "bloğu kaldır"

| # | İş | Öncelik | Şekil / bağımlılık |
|---|---|---|---|
| **B2 slice-1** | **#1580 backend recording-OFF MVP** (live-only fanout + no-content-persistence + metadata-audit) | **P0 — ŞİMDİ** | Tasarım **bağlı** (Codex `019f078a` AGREE). Taze `platform-backend` `origin/main` worktree. Aşağıdaki §6 file-plan'dan başla. Default-off (`remote-bridge.enabled=false`) + fail-closed. Hedef marker: `F22_6_VIEW_ONLY_ENGINEERING:v2`. Codex post-impl review → platform-backend PR. |
| **B2 slice-2…6** | agent DATA-frame sender (Go) + SCREEN_VIEW permit dispatch → web one-to-one viewer → privacy controls + `REMOTE_SUPPORT_SCREEN_OBSERVATION` purpose-tag → negatif-matris live → evidence + owner marker | P1 | slice-1 sonrası sırayla; her slice ayrı Codex review. |
| **B3** | **#548-A hardware attestation** | P1 | **A1'e bağlı.** A1 sonrası: PKI (RB-faz22-3b) → denetim PC (WG 10.99.0.2, gerçek Intel fTPM) canlı TPM session → Vault cert (`tpm:<ek_pub_sha256>` SAN) → V74 binding → device=true → evidence → marker. |

### Owner / Operator / Hukuk (kullanıcı taahhüt etti: "tamamı için gerekeni yapacağım")

| # | İş | Tür |
|---|---|---|
| **A1** | Vault gate-B enablement (#548-A için TPM-enroll path) | operator — B3 blocker |
| **A2/A4** | owner acceptance marker'ları (named owner + UTC + expiry; forge edilemez) | owner |
| **A3** | KVKK 5-madde (VERBIS "Diğer:" transkript + amaç-beyan + retention karar) — **artık non-blocking, paralel** | hukuk/owner |
| **A5** | 22.5 wave-gate drills (M5/M6/M7) | operator |

---

## 6. B2 slice-1 — bağlı tasarım (Codex `019f078a` AGREE-to-implement)

> Bu, slice-1'in tam dosya planıdır; sıradaki session **buradan** başlar (sıfırdan değil). platform-backend `endpoint-admin-service/.../remoteaccess/bridge/server/`.

**Mod seçimi (config):** `remote-bridge.view-only.recording-mode` ∈ {`disabled` (default), `enabled`}; unknown → **fail-closed boot**.
- `disabled` → yeni **`LiveOnlyViewDataPlaneHandler`** seçilir. **Compile-graph'ında HİÇBİR durable/recording sink YOK** → `content_persistence=none` makine-kanıtlanabilir (marker hedefi).
- `enabled` → **`RecordingThenFanoutDataPlaneHandler`** (record-before-fanout; recording-down → fail-closed kill).

**Fanout seam — `ViewOnlyViewerRegistry`** (production class):
- per-session, **bounded latest-wins drop** (DATA stream'i ASLA bloklamaz), viewer yoksa frame **drop** (persist YOK), `max-viewers-per-session=1`.
- **No-control invariant:** registry yalnız broker→operatör yönü; `ControlStreamRegistry`/permit-dispatch bağımlılığı **taşımaz** → static-guard test ile kanıtlanır.

**Fanout gate (hepsi birlikte):** `session ACTIVE` + aynı `transportPeerKey` + `VIEW_ONLY` capability + push'lanmış `SCREEN_VIEW` permit + `stream_id == permit.operationId` + image MIME allowlist.

**Audit:** **`ViewOnlyMetadataAuditSink`** — metadata-only (session/device/permit + frame count/bytes); **asla payload**.

**Yeni sınıflar (~10):** `ViewOnlyViewerRegistry`, `ViewOnlyViewerSubscription`, `ViewOnlyFrame`, `ViewOnlyStreamAuthorizationRegistry`, `LiveOnlyViewDataPlaneHandler`, `RecordingThenFanoutDataPlaneHandler`, `ViewOnlyMetadataAuditSink` (+ auditor).
**Değişen:** `RemoteBridgeServerProperties` (ViewOnly/RecordingMode), `RemoteBridgeServerConfig` (mode-aware bean), `RemoteBridgeOperatorService` (VIEW_ONLY permit push'ta stream authz register), `RemoteAccessMetrics`.
**Test (~7):** bounded-backpressure (latest-wins), no-persistence (disabled handler compile-graph'ında sink yok), no-control static-guard, fanout-gate matrix (her koşul ayrı reddediyor), mode-selection (disabled/enabled/unknown→fail-closed), metadata-audit (payload sızmıyor), permit↔stream binding.

**Başlama sırası (self-contained foundation önce):** `RemoteBridgeServerProperties` (ViewOnly/RecordingMode) + `ViewOnlyFrame` + `ViewOnlyViewerRegistry` + `ViewOnlyViewerRegistryTest` (bounded latest-wins) → `LiveOnlyViewDataPlaneHandler` + `ViewOnlyStreamAuthorizationRegistry` → metadata audit → bean wiring (`RemoteBridgeServerConfig` mode-aware) → no-persistence/no-control guard testleri.

---

## 7. Yeni session için ilk komutlar

```bash
# gitops context (governance/audit referansı)
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin --quiet
cat docs/session-handoff-2026-06-27-faz22-b2-ready.md   # bu doc
cat docs/faz-22-completion-action-plan.md               # canonical plan
cat docs/adr/0044-faz22-6-kvkk-nonblocking-parametric-durations.md  # governing kural

# B2 slice-1 build — TAZE platform-backend origin/main worktree (paylaşılan checkout'tan DEĞİL)
cd /Users/halilkocoglu/Documents/platform-backend
git fetch origin --quiet
git worktree add -b feat/faz22-6-1580-viewonly-slice1-claude-20260627 \
  /private/tmp/wt-b2-slice1 origin/main
cd /private/tmp/wt-b2-slice1
ls endpoint-admin-service/src/main/java/com/example/endpointadmin/remoteaccess/bridge/server/
# → §6 file-plan'dan başla; Codex 019f078a tasarımı; default-off + fail-closed.
```
