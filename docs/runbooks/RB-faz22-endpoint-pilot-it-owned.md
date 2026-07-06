# RB Faz 22.2.B — `acik.local` IT-owned domain-joined pilot readiness (opsiyonel ikinci scope)

> **Status**: PILOT PREP — Faz 22.2.B **opsiyonel** ikinci scope (operator-bound; agent docs-only)
> **Scope reframe (2026-05-24)**: Bu runbook **artık Faz 22.2 primary scope DEĞİL**. Endpoint-admin Faz 22.2 primary production scope **non-domain Windows yönetimi** (workgroup/standalone/BYOD) olarak yeniden tanımlandı (kullanıcı kararı; ADR-0012-EA "22.2 scope amendment" section). Bu runbook artık **22.2.B opsiyonel `acik.local` domain-joined pilot** kapsar. Non-domain primary scope için ayrı runbook follow-up: `RB-faz22-non-domain-windows-pilot.md` (ayrı PR sonraki tur).
> **Tracked by**: [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015) (Faz 22.2 IT pilot readiness umbrella) + [#1037](https://github.com/Halildeu/platform-k8s-gitops/issues/1037) (acik.local Gate 0 VPN routing BLOCKER)
> **Scope sınırı**: `acik.local` domain içinde 2 IT-owned Windows test PC ile kontrollü pilot. Bu runbook **opsiyonel ikinci scope pilot prep** dokümanıdır; prod-ready / password-reset-ready / domain-wide rollout-ready iddiası taşımaz. **22.2.A non-domain primary scope için bağlayıcı DEĞİL** — Gate 0 BLOCKER (gitops #1037) sadece 22.2.B için geçerli.
> **Cumulative Faz 22 chain**: handoff `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 P1 + "Faz 22.2 scope amendment" tablosu.
>
> **Scope superseded note (2026-05-26)**: Bu runbook **22.2.B opsiyonel `acik.local` IT-owned 2-PC pilot** olarak KORUNUR (artık primary değil; 2026-05-24 scope amendment'tan beri). Yeni eklenen **Faz 22.3 domain-wide mass deployment** scope (ADR-0029, ADR-0012-EA "22.3 scope addition") **22.2.B small-scale pilot pattern'inin DEVAMI / ÜST-SCOPE EXTENSION'ı değildir** — 22.3 paralel **üçüncü kanal** olarak farklı operator/IT prereq setine sahip (AD CS role + GPO Software Installation + corp firewall cross-subnet açma + EDR allowlist + pilot OU 5→50→800 ramp). 22.2.B manual install pattern'i (2 PC, operator-initiated installer) 22.3'ün **otomatize MSI/GPO** pattern'i ile karışmamalı; iki kanal aynı backend + agent codebase + **audit chain** (BE-016/BE-017) ortak ama **identity model FARKLI (PARTIAL invariant — iter-6 F3 absorb)**: 22.2.B `acik.local` small-scale opsiyonel pilot bearer-then-mTLS-cert pattern (manual cert mint); 22.3 mass deployment AD CS SAN URI:adcomputer:{objectGUID} primary (GPO startup script + certreq 3-step + DirectorySearcher RSAT-free). Install/enroll mekanizması farklı (22.2.B manual installer, 22.3 MSI/GPO automated) ve identity binding farklı (22.2.B manual cert mint, 22.3 AD CS auto SAN URI). 22.3 prereq'leri (özellikle cross-subnet firewall: 9-saatlik AGENTPC2 fail'in root cause'u) **22.2.B için de tetiklenebilir** ama 22.2.B execution scope 2-PC manual + EndpointPilot OU; 22.3 corp-wide ramp. Detay: ADR-0029 §"Cross-scope position" + ADR-0012-EA "22.3 scope addition" sub-scope tablosu.

---

## 1. Amaç

Faz 22.2 IT pilot tier'a giriş: `acik.local` domain içinde IT-owned 2 test PC üzerinden Endpoint-Enes agent'ın (`platform-agent`) gerçek domain ortamında kontrollü exercise'ı. Pilot çıktısı:

- Agent kurulum + servis lifecycle real-world davranış
- Backend `endpoint-admin-service` enrollment + heartbeat + command/result wire-contract real-world doğrulama
- Audit trail (V5 `endpoint_commands` + `endpoint_command_approvals` + `endpoint_audit_events` tablolarına row insert)
- IT'nin EDR/antivirüs + firewall + AD koordinasyon sürtünme noktalarını yakalamak

Bu pilot **bir kanıt katmanı eklemek** içindir; production rollout veya kullanıcı kapsamlı kullanım kararı değildir.

## 2. Pre-pilot lab gate — Parallels W11 CI rehearsal

> **Status**: AGENT-ACTIONABLE altyapı + local workflow_dispatch evidence captured (platform-agent #12 / run `27081667910`). Remaining: this does not replace `acik.local` pilot, multi-device soak, trusted signing or BE-011 helper-based fresh backend command evidence.
> **Tracked by**: [platform-agent #12](https://github.com/Halildeu/platform-agent/issues/12) — "Faz 22.2 Parallels Windows 11 CI pilot rehearsal".
> **Predecessor manual smoke**: gitops PR #1021 (`4ecb71dc`) + platform-agent PR #10 (`402bdc1`) MERGED 2026-05-24 — `docs/faz-22-evidence/2026-05-24-windows-be011-lifecycle.md` (BE-011 + AG-013 fresh smoke).

### 2.1 Amaç

`acik.local` IT pilot acceptance'a girmeden önce **tekrar edilebilir lab rehearsal** kapısı: local Parallels Windows 11 VM `HALILKOOLUB735` (WORKGROUP / PartOfDomain=false) üzerinde endpoint-agent Windows smoke + BE-011 lifecycle akışını **self-hosted Mac runner + `prlctl`** ile workflow_dispatch tetiklenebilir hale getirmek.

### 2.2 Neyi kanıtlar

- Agent build/package + Windows service install/start/diagnose/uninstall lifecycle çalışıyor (Parallels W11 VM üzerinde tekrar edilebilir)
- `endpoint-admin-service` backend reachability (`testai.acik.com:443` TCP/443)
- Non-destructive BE-011 lifecycle (`COLLECT_INVENTORY` veya `inventory_refresh` enroll → heartbeat → command → result → audit)
- D29-EA Up + Functional layer kanıtları (Secured layer için OpenFGA tuple seed test cluster smoke ayrı kapı — gitops PR #1021 §5 + BE-017 PR #1032 referansları)

### 2.3 Neyi KANITLAMAZ (hard scope sınırı)

- **`acik.local` IT-owned pilot acceptance** — Parallels VM `HALILKOOLUB735` WORKGROUP/PartOfDomain=false; domain join + EndpointPilot OU + IT-owned device + EDR/allowlist provisioning **ext-bound**, bu rehearsal kapsamı dışı.
- **Prod-ready / password-reset-ready / domain-wide rollout-ready** iddiası DEĞİL.
- **Destructive command flow** (LOCK_USER_LOGIN/DISABLE_LOCAL_USER vb.) — rehearsal sadece non-destructive (`COLLECT_INVENTORY`/`inventory_refresh`); destructive flow için BE-017 PR #1032 evidence ayrı kapı (test cluster fixture target only).
- **Trusted signing** — Windows Authenticode + timestamp + signed build pipeline AG-018/AG-024 ext-bound.

### 2.4 Self-hosted runner gereksinimi (operator-bound)

GitHub-hosted `windows-latest` runner **local Parallels VM'i göremez** — virtualization layer access yok. CI entegrasyonu için:

- **Self-hosted macOS runner** Parallels Desktop kurulu + Windows 11 VM "Windows 11" (veya alternatif isim) hazır
- **Runner labels**: `[self-hosted, macOS, parallels, windows11]`
- **Runner registration**: GitHub repo settings → Actions → Runners → Add new self-hosted runner
- **Parallels guest user**: local admin (NOT domain admin); credentials out-of-band hazırlanır (workflow asla `--password` ile geçmez)

### 2.5 Artifact'lar (platform-agent)

- `scripts/test/parallels-windows11-ci.sh` — local CI script (prlctl VM discovery/start + PowerShell pre-check + agent build/package + windows-live.ps1 + optional BE-011 hook + sanitized evidence + post-write secret scan + exit code CI uyumlu)
- `.github/workflows/parallels-windows11-smoke.yml` — `workflow_dispatch` only workflow, self-hosted Mac labels + concurrency + preflight + artifact upload + summary boundary reminder
- platform-agent #12 issue acceptance criteria

### 2.6 Evidence doc path

Gerçek workflow run kanıtı:

- `docs/faz-22-evidence/2026-06-07-parallels-windows11-ci-pilot-rehearsal.md`
- platform-agent run [`27081667910`](https://github.com/Halildeu/platform-agent/actions/runs/27081667910)
- uploaded artifact `parallels-w11-ci-evidence-27081667910`

Gelecek run'lar için evidence doc içeriği zorunlu alanlar:

- VM hostname + domain/workgroup classification + PartOfDomain + Windows version/build
- Runner labels + `prlctl` VM name
- Backend reachability (testai.acik.com:443)
- platform-agent commit + package SHA256
- Service install/start/status (windows-live.ps1)
- AG-013 capability list verify
- BE-011 command id + result id + audit row id when the optional
  `scripts/test/be011-lifecycle-helper.sh` exists and is enabled. If absent,
  the evidence doc must say it was skipped and cite the predecessor manual
  evidence instead of implying a fresh backend command.
- Cleanup sonucu (service uninstall + install dir + log dir clean)
- D29-EA matrix (Up/Functional/Secured) ayrı satır
- "Bu gerçek `acik.local` IT pilot acceptance DEĞİL" notu

### 2.7 Gate sıralaması (acik.local pilot relative)

```
[Parallels W11 CI rehearsal (§2)]  →  [acik.local IT pilot (§3-§10)]
        AGENT-ACTIONABLE                OPERATOR-BOUND
        repeatable lab                  one-time real pilot
        WORKGROUP                       PartOfDomain=true (acik.local)
        non-destructive                 dual-control destructive flows
        fixture-level evidence          real IT-owned device evidence
```

Rehearsal **acik.local pilot yerine geçmez** — pilot öncesi tekrar edilebilir lab kapısıdır. Pilot infazı için domain join + EndpointPilot OU + IT-owned device + EDR/allowlist provisioning operator-bound bağımlılıkları gerek (aşağıdaki §3 — Pilot ön koşulları).

## 3. Pilot ön koşulları

### Donanım + AD

- [ ] **2 adet `acik.local` domain-joined Windows 10/11 PC** — IT pool'undan, son kullanıcı tarafından kullanılmayan test cihazları.
- [ ] **Mümkünse `EndpointPilot` OU** — domain controller'da yeni OU; pilot PC'ler buraya taşınır. GPO scope'u dar tutar.
- [ ] PC envanteri kayıt altında: **bilgisayar adı, IP, Windows sürümü (build no), OU path, yerel admin user adı**.

### Erişim

- [ ] **RDP** veya **IT eşliğinde local console erişimi** — agent install + smoke için.
- [ ] **Şifre e-posta ile paylaşılmaz** (HARD RULE — Kullanıcı Aktif Credential'ına Dokunma): operator/IT şahsen veya secrets manager üzerinden paylaşır.
- [ ] **HTTPS 443 backend reachability**: pilot PC'den `testai.acik.com` (test cluster) HTTPS resolve + TCP/443 ulaşabilmeli (firewall + DNS). **Pilot scope test cluster only**; prod host (`ai.acik.com`) bu runbook kapsamı dışıdır (§5 ve §8).
- [ ] **EDR/Antivirüs allowlist muhatabı**: operator çalıştığı SOC veya IT güvenlik ekibinden `endpoint-agent.exe` (ve hash'i) için allowlist permission önceden alınır. EDR allowlist olmadan smoke fail eder (quarantine veya block).
- [ ] **Pilot cihazlarda local admin/install yetkisi**: agent install + Windows service register için gereklidir. Domain user RDP yetersizdir.
- [ ] **Per-device preflight** (read-only, install öncesi + sonrası): `scripts/faz22-mass-deployment/wave-preflight.ps1` — `-Mode preinstall-readiness` (install öncesi: backend reachability + pending-reboot; service/exe yokluğu fail değil) ve enroll sonrası `-Mode enroll-health` (service Running + PE version + signature + reachability). `overall=FAIL` → smoke durdurulur. (M5/M6/M7 wave-gate'leriyle ortak araç.)

> **Agent kimlik referansları doğrulandı (2026-06-13, platform-agent HEAD `b0c1ba0`)**: Windows service = **`EndpointAgent`**, binary = **`endpoint-agent.exe`** (`%ProgramFiles%\EndpointAgent\`), log dizini = **`%ProgramData%\EndpointAgent\logs`**, heartbeat = `POST /api/v1/endpoint-agent/heartbeat`. (Eski `endpoint-enes-agent` / `EndpointEnes\Logs` adları YANLIŞTI — rollback `Stop-Service` komutu canlıda fail ederdi; bu PR'da düzeltildi. "Endpoint-Enes" yalnız ürün takma adıdır, servis/binary adı değil.)

### Backend hazırlık

- [ ] `endpoint-admin-service` test cluster'da READY 1/1 (digest `sha256:1a1d0aac…` — `current-state.md` truth-sync ile uyumlu).
- [ ] Test persona JWT mint mekanizması operator elinde (`c5persona-admin-9001` pattern — handoff §5 P1 ALLOW-path browser smoke örneği).
- [ ] **OpenFGA tuple — pilot persona için doğrulanmalı**: smoke akışı §4 admin/manager command queue path'ine dayanıyor; `module:endpoint-admin` üzerinde `can_manage` (admin) veya en az `can_view` (read-only/status smoke) tuple'ı pilot persona için var olmalı. Tuple yoksa backend 403 FGA fail-closed döner — bu pilot fail olarak okunmaz, FGA layer doğru çalışıyor demektir; ama smoke matrix'in komut queue + result adımları yapılamaz. Seed referansı: `bootstrap/openfga/endpoint-admin-tuples.json` + `docs/faz-22-evidence/2026-05-24-allow-path-browser-smoke.md` §A persona JWT örneği. Eğer pilot scope **sadece read-only/status smoke** ise tuple opsiyonel sayılabilir (status route auth-only, FGA gate'siz).

## 4. İlk pilotta yapılacaklar

| # | Adım | Sorumlu | Amaç |
|---|---|---|---|
| 1 | **Agent install** | IT + operator | `platform-agent` release artifact (SHA256 doğrulanmış) pilot PC'ye kopya + installer çalıştır |
| 2 | **Service start/status** | IT + operator | `EndpointAgent` Windows service start; `Get-Service` status doğrula |
| 3 | **Inventory collect** | agent automatic | İlk başlatmada local inventory: hostname, OS, machine fingerprint, agent version |
| 4 | **Heartbeat** | agent automatic | Backend `/api/v1/endpoint-agent/heartbeat` POST — interval beklenen |
| 5 | **Backend enrollment** | agent + backend | İlk heartbeat sonrası backend `endpoint_devices` tablosuna row insert; `enrollment_id` döner |
| 6 | **Command poll/result smoke** | agent + backend + operator | Test fixture / dummy command (örn. `inventory_refresh`, NON-destructive) backend tarafında queue edilir; agent poll'lar; execute; result submit'ler |
| 7 | **Log/audit kontrolü** | operator | Backend `endpoint_audit_events` tablosu row insert kontrolü; agent local log path doğrulanır |

**Smoke süresi tahmini**: 30-60 dk per PC (ilk pilot için).

## 5. İlk pilotta YAPILMAYACAKLAR (kesin)

- ❌ **Password reset** (kullanıcı parolası yazılım/manuel)
- ❌ **Kullanıcı disable/enable** (`net user`, AD user account management)
- ❌ **File access / SMB dosya erişimi** (file read/write/list pilot scope dışı)
- ❌ **Raw shell / arbitrary script execution** — pilot dummy command sadece backend whitelist'inden tanımlı capability tipi olabilir; `cmd.exe`, `powershell.exe`, `wmic`, ya da agent üzerinden serbest shell/script çalıştırılması pilot kapsamı dışıdır (capability-based no-raw-shell boundary)
- ❌ **IT/admin credential capture, storage veya logging** — agent loglarına, audit row'larına ya da pilot artifact'lerine credential (parola, token, ssh key, vault token) yazılmaz/saklanmaz; agent normal yapılandırması dışında kimlik bilgisi toplamaz
- ❌ **Domain-wide deployment** (GPO push, Intune broadcast, mass-rollout — pilot sadece 2 PC)
- ❌ **`acik.local` dışı domain veya tenant ile çalışma** — pilot tek domain (`acik.local`) tek tenant scope'undadır; cross-domain trust, başka tenant erişimi, ya da multi-domain test pilot kapsamı dışı (Faz 21 multi-tenant tier R10 ayrı kapı)
- ❌ **Gerçek destructive command** (BE-017 dual-control matrix formal smoke'u ayrı kapı; pilot dummy command kullanır)
- ❌ **Trusted signing / üretim EDR allowlist** (production code-signing cert + EDR vendor catalog update prod cutover scope'unda)
- ❌ **Production cluster erişimi** (pilot test cluster'a bağlanır — `ai.acik.com` prod cluster pilot kapsamı dışı)

Bu liste **boundary contract**'ıdır; pilot kapsam genişletmeden önce ayrı issue + Codex strategic consult + operator açık opt-in gerek.

## 6. Evidence checklist (pilot smoke sonrası)

Her PC için aşağıdaki kayıtlar **tam doldurulmalı**:

| Field | Örnek değer |
|---|---|
| PC adı | `WINPILOT01.acik.local` |
| Domain | `acik.local` |
| OU | `EndpointPilot` (veya kayıt) |
| Windows version | `Windows 11 Pro 10.0.22631.4317` |
| `tenantId` (backend) | `<UUID>` — `endpoint_devices.tenant_id` (multi-tenant ayrım kanıtı) |
| Agent version + artifact SHA256 | `platform-agent v0.1.0 sha256:<full>` (release artifact hash) |
| Build run / source provenance | platform-agent ci-image-push run id veya release tag (artifact source traceability) |
| Service status | `Running (PID <N>); Get-Service EndpointAgent → Status=Running` |
| Enrollment id (`endpoint_devices.id`) | `<UUID>` (backend device row) |
| Enrollment token / credential proof | non-secret credential id veya provider (`hmac-sha256` fingerprint id; **gerçek credential value LOGLANMAZ** — sadece type + non-secret id) |
| Heartbeat timestamp | `2026-MM-DDTHH:MM:SSZ` (backend `endpoint_devices.last_heartbeat_at`) |
| Backend command id + action | `<UUID>` (queued dummy command'ın `endpoint_commands.id`'si) + command type/action (örn. `inventory_refresh`) |
| Backend result id + final status | `<UUID>` (`endpoint_command_results.id`) + result status (`COMPLETED` / `FAILED` / `TIMEOUT`) |
| Audit row id + event type | `<UUID>` (`endpoint_audit_events.id`) + `event_type` (örn. `ENDPOINT_COMMAND_APPROVED`, `COMMAND_RESULT_RECEIVED`) |
| Agent local log path | `C:\ProgramData\EndpointAgent\logs\agent-YYYYMMDD.log` (veya benzeri) |
| EDR / AV result | quarantine? block? clean? — pilot başlamadan ve smoke sonrası IT/SOC ile teyit |
| Ekran/log kanıtı | screenshot veya log dump arşivlenir (örn. evidence doc `docs/faz-22-evidence/<date>-it-pilot-<pc>.md`) |

## 7. Rollback

Pilot smoke sırasında sorun olursa veya pilot sonrası temizlik:

1. **Agent service stop**
   ```powershell
   Stop-Service EndpointAgent
   Set-Service EndpointAgent -StartupType Disabled
   ```
2. **Agent uninstall** — installer'ın `/uninstall` flag'i veya Windows "Apps & Features" UI; binary + config + log temizleme runbook'a göre
3. **GPO/Intune policy kaldırma** — pilot için GPO push yapıldıysa, GPO link sil + `gpupdate /force` pilot PC'lerde
4. **Log/artifact toplama** — pilot çıktıları (log, evidence, screenshot) operator'a aktar; pilot sonrası retention süresi belirlenir
5. **EDR allowlist geri alma** — gerekiyorsa IT/SOC ile koordinasyon (allowlist whitelist'ten endpoint-agent.exe çıkarılır)
6. **Backend cleanup (opsiyonel)** — `endpoint_devices` test pilot row'ları operator karar verirse silinir (audit trail backup alındıktan sonra)

## 8. Acceptance sınırı (formal)

Bu runbook **pilot hazırlık dokümanıdır**:

- ✅ İlk pilot sadece **IT-owned test cihazları** içindir (son kullanıcı yok)
- ✅ Sadece **test cluster** kapsamındadır (`testai.acik.com` backend; prod cluster pilot kapsamı dışı)
- ✅ Smoke kapsamı yukarıda §4 ile sınırlıdır; §5 yasak listesi koruma
- ❌ **Prod-ready / password-reset-ready / domain-wide rollout-ready iddiası taşımaz**
- ❌ Pilot başarısı IT pilot tier'ı kapatmaz; full Faz 22.2 acceptance (≥30 day soak + EDR catalog update + trusted signing + helpdesk hand-off runbook) ayrı kapı

Pilot smoke sonrası **operator karar verir** sonraki adımı:
- Pilot başarılı + EDR/AD koordinasyon temiz → tier-2 (5-10 PC) extended pilot
- Pilot fail veya friction → root-cause analiz + agent/backend follow-up issue + 2-PC pilot tekrar

## 9. Referanslar

- **Wave-gate kardeş runbook'lar (Faz 22.5, agent kimlik referansları aynı kaynaktan doğrulandı)**: `RB-faz22-gpo-pilot-5pc.md` (M5 2-PC), `RB-faz22.5-m6-capacity-baseline.md` (M6 50-PC), `RB-faz22.5-m7-rollback-drill.md` (M7 rollback), `RB-faz22.5-1359-acceptance-evidence-template.md` (M2 edge-mTLS, PR #1492), `scripts/faz22-mass-deployment/wave-preflight.ps1` (ortak preflight)
- `docs/state/current-state.md` — Faz 22 truth (Pending: IT pilot 22.2 — operator-bound)
- `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §4-5 — P1 operator queue
- `PLAN.md` row 37 Faz 22 — "Pending: ... IT pilot ayrı kapı"
- `bootstrap/openfga/endpoint-admin-tuples.json` — OpenFGA tuple shape (pilot persona seed için referans)
- `docs/faz-22-evidence/2026-05-24-allow-path-browser-smoke.md` — ALLOW path persona JWT pattern (pilot persona JWT mint örneği)
- `docs/adr/0012-EA-endpoint-admin-governance-charter.md` — Endpoint Admin governance charter
- BE-017 V5 migration + dual-control gate — `endpoint_commands.approval_status` + `endpoint_command_approvals` tabloları

## 10. Audit trail

- Implementer Claude (Anthropic); Reviewer Codex (OpenAI) — provider-level cross-AI HARD RULE per PR
- Runbook docs-only; runtime/credential/cluster mutation yok
- Tracked by [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015)
