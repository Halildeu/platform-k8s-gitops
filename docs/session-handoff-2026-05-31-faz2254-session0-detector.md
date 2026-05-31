# Session Handoff — 2026-05-31 — Faz 22.5.4 First Install Pilot + Session-0 Durable Detector (#42)

> Format: D28 5-alan + sıradaki agent P0/P1/P2 aksiyon listesi
> Kapsam: cross-repo (platform-agent MERGED + platform-backend PENDING)
> Canonical actionable handoff: **platform-agent issue #42** (Codex-AGREE'li tam backend-PR spec'i comment'te)

---

## 1. Bağlam (neden bu handoff)

Faz 22.5.4 First Install Pilot: HALILKOOLUB735 (Parallels Win11 ARM VM, device_id `d0efb00a-681a-4e32-b7de-a27ef94f2977`) üzerinde 7-Zip lifecycle LIVE smoke (dispatch INSTALL_SOFTWARE → winget install → SUCCESS → testai UI'da GREEN) hedeflendi.

İki major deliverable MERGED + üçüncünün (backend reconciliation) tasarımı Codex consensus ile tamamlandı. Oturum **pre-completion natural break**'e ulaştı (2 PR merged + headline goal LIVE-verified + backend PR fresh büyük efor olarak #42'ye handoff edildi). Kullanıcı `hand off` dedi.

**Kök teknik bulgu:** winget SYSTEM/Session-0 altında `winget list` ile kurulu paketleri **güvenilir enumerate EDEMİYOR** (`--source winget` olsun olmasın — diag binary a21c0c9c ile kanıtlandı). Ama `winget install` exit code'u **güvenilir**. Bu yüzden detection authority registry'ye (ARP) taşındı.

---

## 2. İddia (MERGED PR'lar)

| PR | Repo | Başlık | Merged (UTC) | Cross-AI |
|---|---|---|---|---|
| **#41** | platform-agent | winget install exit = install-state authority; winget list confirm-only (Session-0) | `2026-05-31T09:57:47Z` | Codex AGREE |
| **#43** | platform-agent | REGISTRY_UNINSTALL — authoritative Session-0 installed-state detector (#42) | `2026-05-31T10:44:39Z` | Codex AGREE→REVISE→AGREE |

**PR #41 özü:** winget exit switch → 0=SUCCEEDED, 3010=REBOOT, `0x8A150061`=SUCCEEDED_NOOP (already-installed), diğer=FAILED_INSTALL. Post-verify `winget list` artık **confirm-only** (miss → INCONCLUSIVE, temiz install exit'i downgrade ETMEZ). runner.go observability eklendi (non-success → summary/details log).

**PR #43 özü:** Yeni `REGISTRY_UNINSTALL` detection rule tipi — ARP registry (HKLM Uninstall + WOW6432Node) Session-0'da **güvenilir** olduğu için **AUTHORITATIVE** (miss → FAILED_VERIFICATION). productCode → direct registry Lookup (cap-immune) | displayName+publisher → Enumerate+match fallback. Regex YOK (glob `*`/`?` only). Reliability-keyed: AUTHORITATIVE miss = gerçek denial; WINGET_PACKAGE = CONFIRM_ONLY. Fail-closed: partial/failed read → error, asla "not-installed" varsaymaz. Codex 4 correctness bulgusu absorb edildi (primary-hive error propagate, enum cap → ErrArpEnumTruncated, productCode direct-lookup, GUID-shape validation).

---

## 3. İspatlar (canlı / merkezî kanıt)

- **7-Zip LIVE GREEN:** command `70a852b4` → SUCCEEDED + testai UI "Başarılı" (HALILKOOLUB735, device `d0efb00a-…`). PR #41 fix LIVE-proven. Board #1133 closed.
- **PR merge kanıtı:** `gh pr view 41/43 -R Halildeu/platform-agent` → state MERGED + mergedAt (yukarıda).
- **CI:** PR #41 6/6 green; PR #43 6/6 green (windows/amd64 cross-compile + detect_registry_test.go all pass).
- **Autonomous binary transfer çözüldü:** `\\Mac\Home` SYSTEM'den prlctl ile okunabilir → `~/agent-deploy/` → prlctl PowerShell stop/copy/start EndpointAgent service. Manuel-swap blocker'ı yok.
- **Backend reconciliation tasarımı:** Codex thread `019e7d82` VERDICT A — backend'i agent şemasına hizala. Tam 7-maddelik spec + SQL migration + 7-Zip rule → issue #42 comment'inde (https://github.com/Halildeu/platform-agent/issues/42#issuecomment-4586463108).

---

## 4. İspatlamaz (henüz kanıtlanmamış / bekleyen)

- **PR #43 detector LIVE DEĞİL:** REGISTRY_UNINSTALL source'ta merged ama VM'de **fresh binary build/swap YAPILMADI**. Live binary hâlâ `a21c0c9c` (diag2 = PR #41 fix v2 + observability; REGISTRY_UNINSTALL detector içermiyor).
- **Backend PR başlamadı:** DetectionRuleValidator hâlâ eski BE-020 şeması (`hive`/`uninstallKeyName`/`displayNameRegex`) — agent şemasıyla (`productCode`/`displayName`/`publisher`) **ÇELİŞİYOR**. Bu P0.
- **7-Zip authoritative registry detection live-smoke EDİLMEDİ** (backend rule author + fresh binary gerekiyor).
- **Backend audit persistence** of detectionMethod/authority — follow-up.

---

## 5. Bilinen Boşluk + Sıradaki Agent için Aksiyon Listesi

### P0 — platform-backend PR (Codex VERDICT A, tam spec issue #42 comment'inde)

`endpoint-admin-service/src/main/java/com/example/endpointadmin/service/DetectionRuleValidator.java`:

1. `validateRegistryUninstall` rewrite → agent canonical şema: productCode **XOR** displayName-selector; GLOB sadece `*`/`?`; publisher required (unless `allowPublisherMissing` + EXACT); match-mode default → EXACT; productCode → GUID-shape `{8-4-4-4-12 hex}`.
2. **Drop** `hive` / `uninstallKeyName` / `displayNameRegex` (BE-020 deprecated).
3. WINGET_PACKAGE: `wingetPackageId` → `packageId`.
4. `buildAgentDetectionRule`: authored rule'u **normalize edip forward** et (fabricate YOK) — WINGET_PACKAGE + REGISTRY_UNINSTALL için.
5. WINGET identity invariant **sadece** WINGET_PACKAGE için.
6. REGISTRY_UNINSTALL → packageId **yok**.
7. Dispatch gating: sadece WINGET_PACKAGE + REGISTRY_UNINSTALL; `FILE_*` → **422** `detection_rule_type_not_supported_by_agent`.

\+ validator/payload/audit/compliance testleri (Testcontainers/MockMvc) güncelle + eski-şekil catalog satırları için **migration sweep** (SQL #42'de).
Cross-AI review (Codex) → AGREE → normal squash merge (admin YASAK, CI-red YASAK).

**Agent canonical şema referansı:** `/tmp/agent-detect/internal/winget/detect_registry.go` → `validateDetectionRule` / `validateRegistryRule` / `isMsiProductCode` / `matchString`.

### P1 — Live smoke (backend PR sonrası)

- Catalog-author 7-Zip rule: `{"type":"REGISTRY_UNINSTALL","displayName":"7-Zip","displayNameMatch":"PREFIX","publisher":"Igor Pavlov","publisherMatch":"EXACT"}` (productCode DEĞİL — Codex tercihi).
- Fresh agent binary build (windows/amd64, CGO_ENABLED=0) PR #43 detector ile → HALILKOOLUB735'e swap (`\\Mac\Home` + prlctl pattern).
- Live smoke: authoritative SUCCEEDED via registry (winget exit + ARP confirm).

### P2 — Follow-up

- Bounded post-verify retry (ARP-write-lag toleransı).
- `FILE_EXISTS` / `FILE_SHA256` agent rule tipleri (detector genişletme).
- Backend audit persistence: detectionMethod + authority alanları.

---

## Yeni Session İçin İlk Komut

```bash
# P0 — backend PR: tam Codex-AGREE'li spec
gh issue view 42 -R Halildeu/platform-agent --comments

# Agent canonical şema (backend bunu mirror'layacak)
sed -n '1,80p' /tmp/agent-detect/internal/winget/detect_registry.go   # validateRegistryRule + matchString

# Backend hedef dosya
#   endpoint-admin-service/src/main/java/com/example/endpointadmin/service/DetectionRuleValidator.java
# platform-backend main'den worktree aç → DetectionRuleValidator rewrite → testler → cross-AI → merge
```

**Referanslar:** Codex thread `019e7d82` (VERDICT A) · platform-agent #41/#43 (merged) · #42 (open, P0 spec) · gitops endpoint-admin-service pin `e7a9ebef` (live `sha-daa072e` daha yeni, dokunulmadı).
