# RB Faz 22.2 — IT-owned Endpoint-Enes pilot readiness

> **Status**: PILOT PREP (readiness runbook — agent docs-only; operator execution gerekli)
> **Tracked by**: [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015) (Faz 22.2 IT pilot readiness umbrella)
> **Scope sınırı**: `acik.local` domain içinde 2 IT-owned Windows test PC ile kontrollü pilot. Bu runbook **ilk pilot prep** dokümanıdır; prod-ready / password-reset-ready / domain-wide rollout-ready iddiası taşımaz.
> **Cumulative Faz 22 chain**: handoff `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 P1.4 ile uyumlu.

---

## 1. Amaç

Faz 22.2 IT pilot tier'a giriş: `acik.local` domain içinde IT-owned 2 test PC üzerinden Endpoint-Enes agent'ın (`platform-agent`) gerçek domain ortamında kontrollü exercise'ı. Pilot çıktısı:

- Agent kurulum + servis lifecycle real-world davranış
- Backend `endpoint-admin-service` enrollment + heartbeat + command/result wire-contract real-world doğrulama
- Audit trail (V5 `endpoint_commands` + `endpoint_command_approvals` + `endpoint_audit_events` tablolarına row insert)
- IT'nin EDR/antivirüs + firewall + AD koordinasyon sürtünme noktalarını yakalamak

Bu pilot **bir kanıt katmanı eklemek** içindir; production rollout veya kullanıcı kapsamlı kullanım kararı değildir.

## 2. Pilot ön koşulları

### Donanım + AD

- [ ] **2 adet `acik.local` domain-joined Windows 10/11 PC** — IT pool'undan, son kullanıcı tarafından kullanılmayan test cihazları.
- [ ] **Mümkünse `EndpointPilot` OU** — domain controller'da yeni OU; pilot PC'ler buraya taşınır. GPO scope'u dar tutar.
- [ ] PC envanteri kayıt altında: **bilgisayar adı, IP, Windows sürümü (build no), OU path, yerel admin user adı**.

### Erişim

- [ ] **RDP** veya **IT eşliğinde local console erişimi** — agent install + smoke için.
- [ ] **Şifre e-posta ile paylaşılmaz** (HARD RULE — Kullanıcı Aktif Credential'ına Dokunma): operator/IT şahsen veya secrets manager üzerinden paylaşır.
- [ ] **HTTPS 443 backend reachability**: pilot PC'den `testai.acik.com` (initial test cluster) veya `ai.acik.com` (prod when applicable) HTTPS resolve + TCP/443 ulaşabilmeli (firewall + DNS).
- [ ] **EDR/Antivirüs allowlist muhatabı**: operator çalıştığı SOC veya IT güvenlik ekibinden `endpoint-enes-agent.exe` (ve hash'i) için allowlist permission önceden alınır. EDR allowlist olmadan smoke fail eder (quarantine veya block).
- [ ] **Pilot cihazlarda local admin/install yetkisi**: agent install + Windows service register için gereklidir. Domain user RDP yetersizdir.

### Backend hazırlık

- [ ] `endpoint-admin-service` test cluster'da READY 1/1 (digest `sha256:1a1d0aac…` — `current-state.md` truth-sync ile uyumlu).
- [ ] Test persona JWT mint mekanizması operator elinde (`c5persona-admin-9001` pattern — handoff §5 P1 ALLOW-path browser smoke örneği).
- [ ] Optional: OpenFGA tuple seed pilot persona için (`module:endpoint-admin` `can_manage` veya `can_view` — `bootstrap/openfga/endpoint-admin-tuples.json` pattern).

## 3. İlk pilotta yapılacaklar

| # | Adım | Sorumlu | Amaç |
|---|---|---|---|
| 1 | **Agent install** | IT + operator | `platform-agent` release artifact (SHA256 doğrulanmış) pilot PC'ye kopya + installer çalıştır |
| 2 | **Service start/status** | IT + operator | `endpoint-enes-agent` Windows service start; `Get-Service` status doğrula |
| 3 | **Inventory collect** | agent automatic | İlk başlatmada local inventory: hostname, OS, machine fingerprint, agent version |
| 4 | **Heartbeat** | agent automatic | Backend `/api/v1/endpoint-agent/heartbeat` POST — interval beklenen |
| 5 | **Backend enrollment** | agent + backend | İlk heartbeat sonrası backend `endpoint_devices` tablosuna row insert; `enrollment_id` döner |
| 6 | **Command poll/result smoke** | agent + backend + operator | Test fixture / dummy command (örn. `inventory_refresh`, NON-destructive) backend tarafında queue edilir; agent poll'lar; execute; result submit'ler |
| 7 | **Log/audit kontrolü** | operator | Backend `endpoint_audit_events` tablosu row insert kontrolü; agent local log path doğrulanır |

**Smoke süresi tahmini**: 30-60 dk per PC (ilk pilot için).

## 4. İlk pilotta YAPILMAYACAKLAR (kesin)

- ❌ **Password reset** (kullanıcı parolası yazılım/manuel)
- ❌ **Kullanıcı disable/enable** (`net user`, AD user account management)
- ❌ **File access / SMB dosya erişimi** (file read/write/list pilot scope dışı)
- ❌ **Domain-wide deployment** (GPO push, Intune broadcast, mass-rollout — pilot sadece 2 PC)
- ❌ **Gerçek destructive command** (BE-017 dual-control matrix formal smoke'u ayrı kapı; pilot dummy command kullanır)
- ❌ **Trusted signing / üretim EDR allowlist** (production code-signing cert + EDR vendor catalog update prod cutover scope'unda)
- ❌ **Production cluster erişimi** (pilot test cluster'a bağlanır — `ai.acik.com` prod cluster pilot kapsamı dışı)

Bu liste **boundary contract**'ıdır; pilot kapsam genişletmeden önce ayrı issue + Codex strategic consult + operator açık opt-in gerek.

## 5. Evidence checklist (pilot smoke sonrası)

Her PC için aşağıdaki kayıtlar **tam doldurulmalı**:

| Field | Örnek değer |
|---|---|
| PC adı | `WINPILOT01.acik.local` |
| Domain | `acik.local` |
| OU | `EndpointPilot` (veya kayıt) |
| Windows version | `Windows 11 Pro 10.0.22631.4317` |
| Agent version + artifact SHA256 | `platform-agent v0.1.0 sha256:<full>` (release artifact hash) |
| Service status | `Running (PID <N>); Get-Service endpoint-enes-agent → Status=Running` |
| Enrollment id | `<UUID>` (backend `endpoint_devices.id` döner) |
| Heartbeat timestamp | `2026-MM-DDTHH:MM:SSZ` (backend `endpoint_devices.last_heartbeat_at`) |
| Backend command id | `<UUID>` (queued dummy command'ın `endpoint_commands.id`'si) |
| Backend result id | `<UUID>` (command result submission'ın `endpoint_command_results.id`'si) |
| Audit row id | `<UUID>` (`endpoint_audit_events.id`; `event_type` örn. `ENDPOINT_COMMAND_APPROVED`/`COMMAND_RESULT_RECEIVED`) |
| Agent local log path | `C:\ProgramData\EndpointEnes\Logs\agent-YYYYMMDD.log` (veya benzeri) |
| Ekran/log kanıtı | screenshot veya log dump arşivlenir (örn. evidence doc `docs/faz-22-evidence/<date>-it-pilot-<pc>.md`) |

## 6. Rollback

Pilot smoke sırasında sorun olursa veya pilot sonrası temizlik:

1. **Agent service stop**
   ```powershell
   Stop-Service endpoint-enes-agent
   Set-Service endpoint-enes-agent -StartupType Disabled
   ```
2. **Agent uninstall** — installer'ın `/uninstall` flag'i veya Windows "Apps & Features" UI; binary + config + log temizleme runbook'a göre
3. **GPO/Intune policy kaldırma** — pilot için GPO push yapıldıysa, GPO link sil + `gpupdate /force` pilot PC'lerde
4. **Log/artifact toplama** — pilot çıktıları (log, evidence, screenshot) operator'a aktar; pilot sonrası retention süresi belirlenir
5. **EDR allowlist geri alma** — gerekiyorsa IT/SOC ile koordinasyon (allowlist whitelist'ten endpoint-enes-agent çıkarılır)
6. **Backend cleanup (opsiyonel)** — `endpoint_devices` test pilot row'ları operator karar verirse silinir (audit trail backup alındıktan sonra)

## 7. Acceptance sınırı (formal)

Bu runbook **pilot hazırlık dokümanıdır**:

- ✅ İlk pilot sadece **IT-owned test cihazları** içindir (son kullanıcı yok)
- ✅ Sadece **test cluster** kapsamındadır (`testai.acik.com` backend; prod cluster pilot kapsamı dışı)
- ✅ Smoke kapsamı yukarıda §3 ile sınırlıdır; §4 yasak listesi koruma
- ❌ **Prod-ready / password-reset-ready / domain-wide rollout-ready iddiası taşımaz**
- ❌ Pilot başarısı IT pilot tier'ı kapatmaz; full Faz 22.2 acceptance (≥30 day soak + EDR catalog update + trusted signing + helpdesk hand-off runbook) ayrı kapı

Pilot smoke sonrası **operator karar verir** sonraki adımı:
- Pilot başarılı + EDR/AD koordinasyon temiz → tier-2 (5-10 PC) extended pilot
- Pilot fail veya friction → root-cause analiz + agent/backend follow-up issue + 2-PC pilot tekrar

## 8. Referanslar

- `docs/state/current-state.md` — Faz 22 truth (Pending: IT pilot 22.2 — operator-bound)
- `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §4-5 — P1 operator queue
- `PLAN.md` row 37 Faz 22 — "Pending: ... IT pilot ayrı kapı"
- `bootstrap/openfga/endpoint-admin-tuples.json` — OpenFGA tuple shape (pilot persona seed için referans)
- `docs/faz-22-evidence/2026-05-24-allow-path-browser-smoke.md` — ALLOW path persona JWT pattern (pilot persona JWT mint örneği)
- `docs/adr/0012-EA-endpoint-admin-governance-charter.md` — Endpoint Admin governance charter
- BE-017 V5 migration + dual-control gate — `endpoint_commands.approval_status` + `endpoint_command_approvals` tabloları

## 9. Audit trail

- Implementer Claude (Anthropic); Reviewer Codex (OpenAI) — provider-level cross-AI HARD RULE per PR
- Runbook docs-only; runtime/credential/cluster mutation yok
- Tracked by [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015)
