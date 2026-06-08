# Session Handoff — 2026-06-08 (User-Management İşlemler Menüsü + Soft-Delete + Köprü) v1

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Kapsam: platform-web (Phase 1 LIVE) + platform-backend (Phase 2 DELETE foundation + 2 yeni board) + remote-access bridge tasarım/board

---

## 1. Bağlam (bu oturumda ne yapıldı, neden bu handoff)

Kullanıcının bildirdiği bug: **"İşlemler menüsünde kullanıcı oluşturma/silme/düzeltme yok."** Kök sebep: `mfe-users` `UserActions` menüsü `usePermissions()` (local `@mfe/auth` PermissionContext) okuyordu; Vite-alias / Module-Federation singleton bypass altında bu no-op default dönüyordu → menü öğeleri görünmüyordu.

Çözüm 3 faza ayrıldı:
- **Phase 1 (TAMAMLANDI/LIVE):** authz-gate'i shell-singleton'a taşı (`getModuleLevel`) + impersonate i18n.
- **Phase 2 (BAŞLANDI):** CREATE / DELETE / EDIT user aksiyonları. EDIT zaten drawer'da var. DELETE = soft-delete (foundation pushed). CREATE = operator-KC-credential-gated.
- **Ek board'lar:** Display Policy (screensaver+wallpaper), Remote-access bridge (SSH alternatifi).

Handoff sebebi: kullanıcı "hand off" dedi. Phase 1 LIVE-verified; Phase 2 DELETE backend body (~10 güvenlik-kritik dosya) + 2 yeni feature sıradaki session'a devredilecek.

---

## 2. İddia (MERGED / pushed)

| Repo | PR/Branch | Başlık | Durum | Kanıt |
|---|---|---|---|---|
| platform-web | **#771** | fix(mfe-users): user actions menu shell-singleton authz gate + impersonate i18n | **MERGED** cc55d92c | REST no-admin merge |
| platform-k8s-gitops | **#1353** | deploy(test): bump frontend digest sha-cc55d92 — web #771 | **MERGED** 5bf25e75 (2026-06-07 22:57Z) | test overlay frontend digest |
| platform-backend | branch `be-user-soft-delete-claude-20260608` | feat(user-service): soft-delete tombstone foundation (V17 + User.deletedAt) [WIP] | **PUSHED** efaf2750 (PR YOK) | V17 migration + entity |

**Cross-AI (Phase 1):** Implementer Claude → Reviewer Codex `019ea409` (REVISE→absorb→AGREE: contract version 1.1.0 + reset-on-omit + selector tests).

**Board:**
- platform-backend **#507** OPEN — BE soft-delete + DELETE /api/v1/users/{id} (Codex 019ea573 design)
- platform-backend **#508** OPEN — Endpoint Display Policy (remote screensaver + desktop wallpaper)
- platform-backend **#510** OPEN — remote-access bridge (agent outbound reverse-tunnel + session broker, KVKK-by-design) **← yeni, bu oturumda board'landı**

---

## 3. İspatlar (canlı/doğrulanmış kanıt)

**Phase 1 LIVE chain (browser-smoke PASS):**
- platform-web origin/main HEAD = `cc55d92c` (#771 merge).
- gitops origin/main HEAD bölgesi: `5bf25e75` = #1353 frontend digest bump (sha-cc55d92 / sha256:ea8aa700…).
- ArgoCD auto-sync → testai pod imageID = `ea8aa700` (deploy chain).
- **Browser-smoke (testai):** İşlemler menüsü artık reset-password + toggle-status + SuperAdmin grant/revoke + **"Hesaba Geç"** (impersonate, doğru i18n) gösteriyor; self-target guard çalışıyor; ham i18n key yok; console temiz.

**Soft-delete foundation (kaynak, branch'te):**
- `V17__add_deleted_at_to_users.sql`: `ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP` + partial index `idx_users_active … WHERE deleted_at IS NULL`. Global `@Where` YOK (kasıtlı — Codex 019ea573).
- `User.java`: `deletedAt` alanı + getter/setter + `isDeleted()`.

---

## 4. İspatlamaz (henüz kanıtlanmamış / pending)

- **DELETE backend davranışı** — sadece foundation var; tombstone-aware repo/service/controller/guard YOK; hiçbir DELETE testi koşmadı; PR yok; deploy yok; browser-smoke yok.
- **CREATE chain** — user-service'te Keycloak admin client YOK (KC-first + lazy-provision mimarisi). CREATE için operatörün KC admin credential seed'lemesi gerekir (OPERATOR sınırı — agent admin JWT mint etmez/credential çıkarmaz).
- **Display Policy (#508)** — sadece board; impl/iter yok.
- **Remote-access bridge (#510)** — sadece tasarım + board; Codex plan-time iter yok, impl yok. KVKK = **uygun KURULABİLİR ama koşullu** (meşru menfaat + aydınlatma + ölçülülük + attended-banner + audit + DPIA/VERBİS); Hukuk reviewer zorunlu (issue body'de acceptance kriterleri var).

---

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

### P0 — DELETE backend body (platform-backend #507, branch `be-user-soft-delete-claude-20260608`)
Codex `019ea573` tasarımına göre ~10 güvenlik-kritik dosya (foundation üzerine):
1. `UserRepository` — tombstone-aware metotlar (`findActiveById`, `findActiveByEmail`, active-only list/export); ham `findById` çağrı sitelerini denetle.
2. `UserSpecifications.notDeleted()` — public/query yüzeyleri tombstone'ları hariç tutar.
3. `UserService.deleteUser(id)` (soft-delete: `deletedAt=now`, audit) + `restoreUser(id)`.
4. **No-resurrection guard'ları:** `lazyProvisionFromJwt` + `provisionFromKeycloak` — silinmiş email/kcSubject'i yeni satıra diriltme; `409 USER_DELETED_RESTORE_REQUIRED`.
5. `CurrentUserResolver` — silinmiş kullanıcı için temiz `403 USER_DELETED`.
6. common-auth `AuthenticatedUserLookupService` — `deleted_at` filtresi (silinmiş kullanıcı kimlik çözümlenmez).
7. `UserAuditEventService.recordDeleteEvent` / `recordRestoreEvent` (INSERT-only, append-only).
8. `UserControllerV1` — `DELETE /{id}` + `POST /{id}/restore`; RBAC `MANAGE_USERS` + company-scope gate; `UserMutationAckDto.ok(auditId)`.
9. Tüm okuma yüzeyleri active-only (impersonation-target dahil).
10. Testler: MockMvc (DELETE/restore/403/409) + service + Testcontainers PG.

→ Sonra: cross-AI Codex post-impl review → CI-green (no-admin REST merge) → image build → gitops digest bump → testai apply → **browser-smoke** (İşlemler menüsünde Sil görünür + silinen kullanıcı login 403).

### P1 — Display Policy (platform-backend #508)
Windows endpoint display policy: screensaver (`Control Panel\Desktop` ScreenSaveActive/TimeOut/IsSecure/SCRNSAVE.EXE) + wallpaper (`Policies\System` Wallpaper/WallpaperStyle), HKLM Group-Policy registry, machine-wide enforce. platform-agent (apply) + platform-backend (policy CRUD + dispatch) + platform-web (UI). Codex plan-time iter ile başla.

### P1 — Remote-access bridge (platform-backend #510)
Codex plan-time adversarial iter (protokol WS vs gRPC-stream, broker state machine, dual-control gate, KVKK attended-banner UX) → AGREE → backend broker impl. **KVKK acceptance kriterleri issue body'de**; Hukuk reviewer zorunlu.

### P2 — CREATE chain (operatör-bağımlı)
Operatör KC admin credential seed'lerse: user-service'e KC admin client + CREATE endpoint + KC-create-on-provision + web CREATE drawer. Agent başlatamaz (OPERATOR sınırı).

---

## Yeni Session İçin İlk Komut

```bash
# 1. Bu handoff'u oku (tam context)
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin && git show origin/main:docs/session-handoff-2026-06-08-user-mgmt-actions-v1.md  # merge sonrası
# (merge öncesi bu branch'te: docs/session-handoff-20260608-claude)

# 2. DELETE backend body'ye devam (P0)
cd /Users/halilkocoglu/Documents/platform-backend
git fetch origin && git checkout be-user-soft-delete-claude-20260608
# Codex 019ea573 tasarımı + platform-backend #507 continuation spec
gh issue view 507 --repo Halildeu/platform-backend

# 3. Board claim + In Progress
#    platform-backend #507 (DELETE) / #508 (Display) / #510 (Bridge)
```

**Kalıcı kayıtlar (handoff doc'a ek):** board #507/#508/#510 (issue body'lerinde tam spec) + Codex thread 019ea573 (DELETE) + 019ea409 (Phase 1) + branch be-user-soft-delete-claude-20260608 (foundation).

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
