# RB Faz 22.2.A — Non-domain Windows pilot readiness (primary scope)

> **Status**: PILOT PREP (operasyon runbook — agent docs-only; operator/IT/legal execution gerekli)
> **Scope**: Non-domain Windows yönetimi primary scope (workgroup / standalone / BYOD / Entra-joined / Workplace-registered) — endpoint-admin platformu için **22.2 primary production scope** kapsamı. Domain-joined (`acik.local`) IT pilot **22.2.B opsiyonel ikinci scope** olarak ayrı runbook'ta (`RB-faz22-endpoint-pilot-it-owned.md`).
> **Canonical decision**: ADR-0012-EA "22.2 scope amendment (2026-05-24)" section (kullanıcı kararı; Codex strategic thread `019e5afc-2ce2-7811-9d98-73ff6eac1434` REVISE iter-1 with `ready_for_impl=true` for docs-only scope realignment; full pilot scope still pending operator gates)
> **Tracked by**: [#1015](https://github.com/Halildeu/platform-k8s-gitops/issues/1015) (Faz 22.2 IT pilot readiness umbrella — 22.2.A primary scope reframe per ADR amendment)
> **Predecessor evidence (22.2.A substantive)**: gitops PR #1021 BE-011 + AG-013 WORKGROUP smoke HALILKOOLUB735 + gitops PR #1032 BE-017 dual-control test cluster fixture + platform-agent PR #13 CI automation
> **Codex strategic thread (this runbook)**: `019e5b17-4086-7fc3-b82b-5303be3948fe` REVISE iter-1 with `ready_for_impl=true` for docs-only standalone runbook implementation (post-impl review iter-2 absorb 3 source-truth fixes; full pilot infazı device + signed + KVKK/consent + soak gate'lerine bağlı)
>
> **Scope addition note (2026-05-26; host naming amended 2026-06-14)**: Bu runbook **22.2.A non-domain Windows primary scope** için **KORUNUR** ve bağlayıcılığını sürdürür. Yeni eklenen **Faz 22.3 domain-wide mass deployment** scope (ADR-0029, ADR-0012-EA "22.3 scope addition") **bu runbook'u amend/supersede ETMEZ**. 22.3 paralel üçüncü kanal (MSI + AD CS + GPO Software Installation, `acik.local` ~800 PC otomatize) — manual install ile non-domain hedefler için 22.2.A pattern'i tek geçerli kanal. **Cross-scope invariants (PARTIAL — semantik ayrımı net olsun)**: tek backend/device API sözleşmesi (`https://mtls.testai.acik.com/api/v1/endpoint-agent` test/pilot; `https://mtls.ai.acik.com/api/v1/endpoint-agent` prod) ✅ ortak; tek agent codebase ✅ ortak; **identity model FARKLI** — 22.3 path AD CS SAN URI:adcomputer:{objectGUID} primary (template mint sırasında dahil), 22.2.A path manual single-use bearer token enrollment (workgroup/BYOD'da AD computer object yok, cert SAN URI mekanizması yok); audit chain BE-016/BE-017 ✅ ortak (her iki path için aynı backend hash-chain + dual-control). 22.3'ün operator/IT prereq listesi (AD CS / GPO Software Installation / EDR allowlist / pilot OU) 22.2.A non-domain hedefler için **gerek değil**. Detay: ADR-0029 §"Cross-scope position" + ADR-0012-EA "22.3 scope addition" sub-scope tablosu.

---

## 1. Status, Scope, Canonical References

### 1.1 Scope

Bu runbook **Faz 22.2.A non-domain Windows primary production scope** için operasyon dokümantasyonudur. Hedef class'lar (ADR-0012-EA "22.2 scope amendment" non-domain taxonomy):

- **A1 — Workgroup / standalone Windows** (current `HALILKOOLUB735` substantive evidence cover)
- **A2 — BYOD unmanaged Windows** (consent + uninstall + privacy/KVKK + local-admin/install boundary)
- **A3 — Entra-joined / Azure AD-joined Windows** (no AD DS) — agent install/enroll/heartbeat/inventory **read-only**; Graph/Intune management ikinci gate
- **A4 — Workplace-registered only Windows** — read-only inventory/support class; tenant/MDM aksiyonları scope dışı

### 1.2 Out-of-scope (ayrı runbook'lara referans)

- **22.2.B Domain-joined (`acik.local`) IT pilot** — `RB-faz22-endpoint-pilot-it-owned.md` (gitops PR #1034 + #1041 reframe MERGED)
- **B1 Hybrid Azure AD-joined** — 22.2.B class (AD DS join + DC/Kerberos/GPO/cached credential riskleri)
- **C Mobile (iOS / Android)** — Faz 23.7.b mobile push veya ayrı future device-management fazı

### 1.3 Canonical references

- ADR-0012-EA "22.2 scope amendment (2026-05-24)" section (scope realignment kanonik karar)
- PLAN.md row 37 (three-layer %: 22.2.A ~78% / 22.2.B ~25% / portfolio ~67%)
- `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 "Faz 22.2 scope amendment" sub-section
- `docs/faz-22-evidence/2026-05-24-windows-be011-lifecycle.md` (22.2.A substantive evidence — reclassification note)
- platform-agent `docs/TRACKING-ROADMAP.md` (AG-013 / AG-021 / AG-022 / AG-024 / BE-011 / BE-015 / BE-017 / BE-019)
- platform-agent `scripts/test/windows-live.ps1` (agent service install/start/diagnose/uninstall — pilot smoke phase reuse)
- platform-agent `scripts/test/parallels-windows11-ci.sh` (CI repeatability rehearsal — primary scope CI hat'ı)
- gitops PR #1032 `docs/faz-22-evidence/2026-05-24-be017-dual-control-matrix.md` (destructive command dual-control contract — fixture proof)

---

## 2. Evidence baseline (mevcut substantive) ve non-claims

### 2.1 Substantive evidence cover (~78% per ADR portfolio)

| Track | Evidence | Status |
|---|---|---|
| Agent lifecycle (A1 workgroup) | gitops PR #1021 BE-011 fresh smoke HALILKOOLUB735 + windows-live.ps1 full chain pass | ✅ DONE 2026-05-24 |
| AG-013 capability coherence (no false advertising) | platform-agent PR #10 Verified 2026-05-24 (capability list post-fix) | ✅ DONE 2026-05-24 |
| Destructive command dual-control contract | gitops PR #1032 BE-017 LOCK_USER_LOGIN fixture (test cluster, no real PC) | ✅ DONE 2026-05-24 |
| CI repeatability (Parallels W11 lab gate) | platform-agent PR #13 (`scripts/test/parallels-windows11-ci.sh` + workflow) | ✅ MERGED 2026-05-24 |

### 2.2 Non-claims (HARD — bu runbook kapsamına alınamaz)

- **NOT prod-ready** — single VM / no soak / 1 device baseline; production roll-out gate ayrı
- **NOT password-reset-ready** — `LOCK_USER_LOGIN` ve destructive flow real device'de YASAK
- **NOT domain-wide rollout-ready** — non-domain pilot tek device class çözümü
- **NOT mobile-ready** — iOS / Android scope dışı (Faz 23.7.b ayrı)
- **NOT BYOD-ready (henüz)** — A2 BYOD class için consent/privacy/KVKK + signed binary mandatory; bu runbook'ta gate'ler tanımlanır, infaz operator-bound

---

## 3. Hard constraints / non-goals (HARD)

- **Non-destructive only** on real (non-fixture) device: ilk ve tek backend command `COLLECT_INVENTORY` veya `inventory_refresh` (BE-008 + BE-011 contract); `LOCK_USER_LOGIN` / `DISABLE_LOCAL_USER` / `password_reset` / `software_uninstall` / `service_disable` / `network_isolate` real device'de **YAPILMAZ**
- **No password reset / user disable-enable / file access / raw shell** — agent command contract `docs/COMMAND-CONTRACT.md` whitelist disiplini
- **HARD RULE — Kullanıcı Aktif Credential'ına Dokunma** — agent kullanıcısı login session'ında olan user'ın creds touched DEĞİL; test persona only (BYOD context'te kullanıcı kendisi)
- **No new runtime evidence claim without ADR amendment** — mevcut evidence boundary'leri korunur (single VM / no soak / 1 device); yeni evidence yeni PR + Codex review zorunlu
- **Cross-AI provider-level review** — Implementer Claude (Anthropic) ≠ Reviewer Codex (OpenAI) her PR; provider-level HARD RULE (2026-05-05 + 2026-05-14)
- **No closure language** (HARD RULE 2026-04-19) — closure-anlamlı ifadeler YASAK; status hep "in progress / needs verify / pending" şeklinde kullanılır. Detay: `~/.claude/CLAUDE.md` "HARD RULE — No Closure Language" + `feedback_no_closure_language.md`.
- **Trusted signing for real BYOD** — A2 BYOD class signed binary mandatory (AG-024 + Authenticode + timestamp); unsigned lab exception yalnız A1 workgroup lab cihazları için time-boxed + SHA-pinned

---

## 4. Non-domain taxonomy A1-A4

### 4.1 Detection table

| Tier | `PartOfDomain` | `AzureAdJoined` (dsregcmd) | `WorkplaceJoined` (dsregcmd) | Ownership | Scope |
|---|:---:|:---:|:---:|---|---|
| **A1** Workgroup / standalone | false | NO | NO | corporate-owned standalone | tam pilot (agent install/enroll/lifecycle/inventory) |
| **A2** BYOD unmanaged | false | NO | NO | personal-owned BYOD | tam pilot **+** consent/privacy/KVKK/uninstall + signed binary mandatory |
| **A3** Entra-joined / Azure AD-joined | false | YES | NO | corporate-owned (modern hybrid) | read-only agent (install/enroll/heartbeat/inventory); Graph/Intune management ikinci gate |
| **A4** Workplace-registered only | false | NO | YES | corporate access + personal device | read-only inventory/support; tenant/MDM aksiyonları scope dışı |

### 4.2 Detection commands (precheck)

```powershell
# 1. Domain/workgroup state
$cs = Get-CimInstance Win32_ComputerSystem
[PSCustomObject]@{
  Hostname     = $env:COMPUTERNAME
  Domain       = $cs.Domain
  PartOfDomain = $cs.PartOfDomain
  Workgroup    = $cs.Workgroup
  UserName     = "$env:USERDOMAIN\$env:USERNAME"
}

# 2. AAD / Workplace join state (dsregcmd)
dsregcmd /status | Select-String -Pattern "AzureAdJoined|EnterpriseJoined|DomainJoined|DeviceName|TenantName|WorkplaceJoined"

# 3. MDM / Intune enrollment state
$mdm = Get-CimInstance -Namespace root/cimv2/mdm/dmmap -ClassName MDM_DevDetail_Ext01 -ErrorAction SilentlyContinue
$mdm | Select-Object DeviceClientId, OEMVersion, DeviceID

# 4. Logged-in identity (current/last user)
Get-CimInstance -ClassName Win32_LoggedOnUser -ErrorAction SilentlyContinue | Select-Object -First 5
```

### 4.3 Classification logic (script-side)

```
if (PartOfDomain == true)                              → 22.2.B (B1 Hybrid AAD veya B2 acik.local) — bu runbook scope dışı
elif (AzureAdJoined == YES)                            → A3 Entra-joined / Azure AD-joined
elif (WorkplaceJoined == YES && AzureAdJoined == NO)   → A4 Workplace-registered only
elif (PartOfDomain == false && all joins == NO)        → A1 workgroup (default) veya A2 BYOD (ownership flag operator evidence)
```

### 4.4 Audit trail + redaction policy

Detection sonuçları evidence dosyasına **sanitized JSON** olarak yazılır:

- ✅ **Allowed**: hostname (machine), domain class (true/false), workgroup name, OS version/build, MDM tenant id (truncated last-4 veya hash), AAD device id (truncated)
- ❌ **Redacted / Hashed**: full UPN (`user@tenant.com` → `***@tenant.com` veya `sha256:abc...`), SID (full SID → `S-1-5-21-***-***-***-1001`), user display name, last login timestamp (rounded to day)
- ❌ **Never logged**: password / token / JWT / enrollment token / device credential / SMB share content / app config secrets

Bu redaction policy `BE-019` KVKK retention enforcement gate ile uyumlu (TRACKING-ROADMAP backlog) — `BE-019` MERGED olmadan tam KVKK uyumlu acceptance verilmez.

---

## 5. Roles, credentials, and test persona boundary

### 5.1 Roles (operator + agent ayrımı)

| Role | Sorumluluk | Authority boundary |
|---|---|---|
| **Pilot operator** (sen / IT admin) | Cihaz temini + onboarding + consent (BYOD) + signed binary distribution + EDR allowlist coordination | local admin / install authority; agent script triggers; evidence doc operator sign-off |
| **Agent (Claude/Codex)** | Script / workflow / runbook authoring; CI automation; post-impl evidence doc; cross-AI review chain | docs-only; no real PC destructive action; no credential capture |
| **Backend (`endpoint-admin-service`)** | Enrollment token mint + heartbeat ingest + command queue + audit trail (V4 hash-chain) | test cluster + prod cluster (Faz 23 future); device credential rotation per PR #224 |
| **DPO / Legal** (A2 BYOD only) | Consent metni + KVKK data inventory + retention policy + DPO sign-off | A2 BYOD acceptance için bağlayıcı; A1 standalone için meşru menfaat zemini tartışılabilir |
| **SOC / EDR** | A2 BYOD agent SHA + service display name + install path EDR allowlist | A2 acceptance prerequisite |
| **Codex API service** (cross-AI reviewer) | Provider-level peer review (HARD RULE 2026-05-05 + 2026-05-14) | her PR'da Implementer Claude ≠ Reviewer Codex |

### 5.2 Test persona boundary (HARD RULE — Kullanıcı Aktif Credential'ına Dokunma)

- **Backend admin actions** (enrollment token mint, command create, audit query): test persona JWT only — `c5persona-admin-9001` pattern (gitops PR #1021 + #1032 evidence baseline)
- **Real device pilot user**: agent kullanılan cihazın gerçek kullanıcısı (A1: operator/IT; A2: BYOD user himself); agent credential rotation **kullanıcı login user'ına dokunmaz**
- **Post-pilot rotation**: test persona password random unknown'a rotate (BE-017 pattern PR #1032)

### 5.3 Cred / token boundary

| Artifact | Storage | Logged in script/evidence? |
|---|---|---|
| Backend admin JWT (`c5persona-admin-9001`) | Mac terminal env var; redact filter | ❌ Never logged (Bearer token redacted) |
| Enrollment token (single-use) | install.ps1 -EnrollmentToken arg + agent state | ❌ Never logged (script + evidence redacted) |
| Agent device credential (HMAC secret) | agent local state file (encrypted at rest per AG-019 tamper protection) | ❌ Never logged |
| BYOD user consent record | Operator evidence (separate doc, not agent script) | ✅ Logged in evidence doc (consent id only, not personal data) |

---

## 6. Device source and onboarding rules

### 6.1 Device source matrix

| Source | Tier coverage | Acceptance |
|---|---|---|
| Mevcut Parallels W11 VM (HALILKOOLUB735) | A1 — substantive evidence cover | gitops PR #1021 + #10 + #11 |
| Yeni Parallels W11 VM (fresh, Mac altında 2-3 VM) | A1 multi-VM repeatability | docs-only (eklenecek VM evidence ayrı tur) |
| Gerçek corporate-owned standalone PC (IT pool dışı) | A1 real-world | operator onboarding + IT install pipeline |
| Gerçek BYOD PC (employee personal laptop) | A2 — consent şart | operator consent flow (BYOD onboarding script) + signed binary mandatory |
| Entra-joined corporate Windows | A3 — read-only | operator coordination (Entra admin); agent read-only mode |
| Workplace-registered personal device | A4 — read-only support | operator coordination; agent inventory-only |

### 6.1A Local Parallels A1 linked-clone batch (#1044)

2026-06-07 local preflight:

```text
Current parent VM: Windows 11 / HALILKOOLUB735
Parent PVM size: 75G
Host free space: 47GiB on /System/Volumes/Data
Parallels snapshot count: 0
Parent VM state: running
```

Implication:

- Full/deep clone is not safe at the current disk pressure level.
- Linked clone is the preferred local path for #1044 A1 repeatability.
- Parallels refuses clone creation while the parent VM is running; a planned
  maintenance window is required.
- Linked clone evidence is acceptable only after the clone is personalized and
  re-enrolled as a distinct endpoint. A raw clone of HALILKOOLUB735 is not a new
  device evidence by itself.

Operator maintenance window procedure:

```bash
# 0. Record current parent VM state.
prlctl list -a
prlctl snapshot-list "Windows 11"
df -h /System/Volumes/Data

# 1. Stop or suspend the parent VM from Parallels GUI.
#    Do not force-stop unless the operator accepts guest OS risk.
prlctl status "Windows 11"

# 2. Create linked clones. These commands must be run only while the parent VM
#    is not busy/running.
prlctl clone "Windows 11" --linked --name "NONDOMAIN-W11-LAB-01"
prlctl clone "Windows 11" --linked --name "NONDOMAIN-W11-LAB-02"

# 3. Start one clone at a time to avoid host RAM pressure.
prlctl start "NONDOMAIN-W11-LAB-01"

# Verify first clone boot + host RAM/disk pressure before starting the second.
prlctl list -a
df -h /System/Volumes/Data

prlctl start "NONDOMAIN-W11-LAB-02"
```

Fail-closed helper alternative:

```bash
# Dry-run: prints parent VM state, disk pressure, snapshot count, clone target
# availability, and the required operator maintenance-window action. No
# mutation.
bash scripts/faz22-non-domain/a1-linked-clone-batch.sh

# Execute: only after the operator has gracefully stopped/suspended the parent
# VM. The script refuses to clone while the parent VM is running.
bash scripts/faz22-non-domain/a1-linked-clone-batch.sh --execute
```

Per-clone personalization before evidence:

```text
[ ] Unique hostname set (NONDOMAIN-W11-LAB-01/02 or equivalent).
[ ] Parent agent install/state removed or re-enrolled with a fresh one-time token.
[ ] `PartOfDomain=false`, AzureAdJoined=NO, WorkplaceJoined=NO confirmed.
[ ] Backend endpoint identity is distinct from HALILKOOLUB735.
[ ] No destructive command dispatched; only COLLECT_INVENTORY / read-only probes.
[ ] Evidence doc includes "linked clone" boundary and parent VM reference.
```

Known preflight failure mode:

```text
prlctl clone "Windows 11" --name "NONDOMAIN-W11-LAB-DRYRUN-CHECK" --linked --dst /tmp
Failed to clone the VM: Unable to perform the action because the virtual machine is busy.
The virtual machine is currently running. Please try again later.
```

### 6.1B Other-computer batch checklist (deferred until local completion)

Bu checklist, mevcut local Parallels `Windows 11 / HALILKOOLUB735` zinciri
tam kanıtlanmadan diğer bilgisayarlarda tekil/ad-hoc işlem yapılmaması için
kanonik toplu iş listesidir. Amaç: localde agent/backend/web/runbook davranışı
kanıtlandıktan sonra diğer cihazlarda aynı sırayı tekrar edilebilir şekilde
uygulamak.

Kısa operator yürütme paketi: `docs/runbooks/RB-faz22-a1-two-device-operator-packet.md`.
Bu paket aşağıdaki kontratı değiştirmez; yalnız #1044 iki-cihaz batch için
copy/paste odaklı özet sağlar.

**Batch trigger**:
- [ ] Local Parallels HALILKOOLUB735 health/smoke evidence güncel.
- [ ] #1044 için iki ek Parallels cihaz veya eşdeğer lab cihazı hazır.
- [ ] 24h soak penceresi ve rollup helper (§11.3A) çalıştırma zamanı planlandı.
- [ ] Operator maintenance window var; parent VM gerekiyorsa stop/suspend edilecek.
- [ ] Hiçbir gerçek kullanıcı cihazında destructive command kullanılmayacağı tekrar teyit edildi.

**Per-device pre-batch intake**:
- [ ] Hostname / asset tag / cihaz sahibi sınıfı yazıldı.
- [ ] Device class seçildi: A1 standalone lab, A2 BYOD, A3 Entra, A4 Workplace.
- [ ] Local admin erişimi operator tarafından doğrulandı; parola/JWT/token mail veya chat ile paylaşılmadı.
- [ ] `testai.acik.com:443` erişimi doğrulandı.
- [ ] EDR/antivirus allowlist gerekiyorsa ticket/ref kaydedildi.
- [ ] Signed artifact gereksinimi belirlendi: A1 lab exception veya A2-A4 signed mandatory.

**Per-device execution checklist**:
- [ ] Agent install/enroll fresh token ile yapıldı.
- [ ] Backend device id benzersiz; parent/clone stale enrollment yok.
- [ ] Identity classification alındı: `PartOfDomain`, `AzureAdJoined`, `WorkplaceJoined`.
- [ ] `EndpointAgent` service Running + Automatic.
- [ ] `COLLECT_INVENTORY` veya `inventory_refresh` non-destructive command terminal state'e ulaştı.
- [ ] Audit/lifecycle fact set alındı; raw credential/JWT/token/UPN/full SID evidence'a yazılmadı.

**Local Parallels per-device diagnostics helper**:

Clone'lar hazırlandıktan ve her VM benzersiz hostname + fresh enrollment aldıktan
sonra, per-device local evidence aynı komutla toplanır:

```bash
# Dry-run: VM'ler running mı kontrol eder; guest komut çalıştırmaz.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --dry-run \
  --vm "Windows 11" \
  --vm "NONDOMAIN-W11-LAB-01" \
  --vm "NONDOMAIN-W11-LAB-02"

# Read-only execution: prlctl exec ile identity/winget/software/hardware/
# services/local-users diagnose çıktılarını klasöre yazar. WinGet egress
# probe'u default skip edilir; uzun ağ/source probe'u için aşağıdaki opsiyon
# ayrıca eklenir.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --vm "Windows 11" \
  --vm "NONDOMAIN-W11-LAB-01" \
  --vm "NONDOMAIN-W11-LAB-02"

# Optional: WinGet source/egress probe dahil.
bash scripts/faz22-non-domain/a1-local-vm-diagnostics.sh \
  --include-winget-egress \
  --section-timeout-seconds 180 \
  --vm "Windows 11"
```

Helper sözleşmesi:
- VM stop/suspend/clone yapmaz.
- Backend command dispatch yapmaz.
- Install/uninstall, restart, account mutation, password change, domain join,
  SMB/file action yapmaz.
- Agent `diagnose` yüzeylerini ve temel Windows read-only state'ini toplar.
- Host-side timeout ile takılan guest diagnostics prosesini fail-closed keser.
- Output içinde JWT/Bearer/credential-like pattern yakalarsa fail-closed olur.
- Helper output'u per-device evidence doc'a taşınır; tek başına #1044 PASS
  değildir.

**Per-device evidence draft generator**:

Local diagnostics helper çıktısı alındıktan sonra §14.1/§14.2 formatındaki
evidence taslağı otomatik üretilebilir. Bu generator local dosya okur/yazar;
backend'e bağlanmaz, command dispatch yapmaz ve PASS iddiası üretmez.

```bash
DIAG=/tmp/faz22-a1-local-vm-diagnostics-<timestamp>/Windows_11/read-only-diagnostics.txt

python3 scripts/faz22-non-domain/a1-evidence-doc-from-diagnostics.py \
  --diagnostics-file "$DIAG" \
  --output-dir docs/faz-22-evidence \
  --device-id <backend-device-uuid> \
  --operator "<operator-role>" \
  --install-method "A1 lab install"
```

Generator taslağı `PARTIAL` statüsüyle üretir; planned non-destructive command
facts, 24h soak facts ve pilot-wide rollup ayrı doldurulur. Bu nedenle generator
çıktısı tek başına #1044 acceptance PASS değildir.

**Post-batch acceptance checklist**:
- [ ] Her cihaz için §14.1/§14.2 evidence doc dolduruldu.
- [ ] §11.3A soak helper read-only çalıştırıldı; heartbeat/command fact set'i evidence'a taşındı.
- [ ] Offline gap >30 dk varsa planned/unplanned ayrımı yazıldı.
- [ ] Pilot-wide rollup (§14.3/§14.4) oluşturuldu.
- [ ] Cross-AI peer review alındı.
- [ ] #1044 yalnız rollup evidence sonrası Needs Verify'dan çıkarılır; helper/runbook/source PR'ı tek başına acceptance değildir.

### 6.2 Onboarding flow (A1 standalone)

```
1. Operator: cihaz inventory kayıt (hostname, IP, OS version/build, MAC, owner=corporate-IT)
2. Operator: local admin yetkisi verify (msc → Local Users → halilkocoglu or pilot user member of Administrators)
3. Agent: backend reachability test (Test-NetConnection testai.acik.com 443; sonra prod cluster için ai.acik.com 443 future)
4. Agent: enrollment token mint (Mac side: c5persona-admin-9001 JWT + POST /api/v1/endpoint-admin/endpoint-enrollments)
5. Operator: agent install — signed installer (A2 BYOD: mandatory; A1 standalone: lab unsigned exception OK if time-boxed)
6. Agent: enroll → heartbeat → command poll → result → audit chain
7. Operator: evidence doc + identity classification + soak observation
```

### 6.3 Onboarding flow (A2 BYOD) — additional gates

Önce 6.1-6.2 + ek olarak:

- **Consent flow** (§12): kullanıcıya yazılı consent + opt-in form + uninstall talimatı + KVKK data inventory; consent ID evidence'a
- **Signed binary verify** (§7): SHA256 + Authenticode imza verify (`signtool verify /pa endpoint-agent.exe`); evidence'a thumbprint
- **EDR allowlist coordination** (§13 acceptance gate): SOC tarafında `endpoint-agent.exe` SHA + service display name + install path allowlist
- **Uninstall self-service test** (§15): kullanıcı agent'ı kaldırabilmeli (local admin → installer uninstall.ps1 veya Add/Remove Programs); test successful uninstall + service removed + log dir cleaned

---

## 7. Signed distribution policy

### 7.1 İki sınıflı karar (Codex Q5 absorb)

| Class | Signing requirement | Rationale |
|---|---|---|
| **A1 lab / repeatability** (Parallels W11 + Mac altında multi-VM) | Unsigned exception kabul edilebilir: **time-boxed + SHA-pinned + evidence-doc-explicit "unsigned lab exception"** | repeatability + CI rehearsal için signed pipeline kuruluş öncesi (AG-024 backlog); rollout-ready sinyali **DEĞİL** |
| **A2 BYOD real device** | **Signed binary mandatory** (Authenticode + timestamp + signed release artifact) | SmartScreen + EDR + user trust; unsigned binary BYOD pilot acceptance vermez |
| **A3 / A4 Entra-joined / Workplace-registered real device** | Signed binary mandatory (corporate trust) | Aynı gerekçe |

### 7.2 Signed binary chain (AG-024 unlock öncesi)

Mevcut state: AG-024 "Signed update manifest verification" + AG-018 trusted signing pipeline `TODO` (TRACKING-ROADMAP backlog). A2-A4 real device acceptance için bu gate'ler unlock şart.

ADR-0012-EA "22.2 pre-req docs" section'da listelenen items (Codex iter-3 PR-8d/PR-8e):
1. Azure Trusted Signing onaylı mı?
2. CI auth modeli (GitHub OIDC + workload identity)
3. Certificate profile (subject metadata + OID + EKU)
4. Timestamp endpoint (RFC 3161)
5. Role assignments (Azure RBAC)
6. Release promotion modeli (lab ephemeral → IT pilot signed)
7. Trusted signed artifact olmadan EndpointPilot dışı yok invariant

Bu pre-req docs `docs/22-2-trusted-signing-onboarding.md` dosyasında 22.1 son haftasında hazırlanır (ADR-0012-EA referansı).

### 7.3 SHA-pinned lab exception evidence template

A1 lab cihazları için unsigned exception kullanıldığında evidence'a şu kalıp yazılır:

```
Unsigned lab exception (A1 only):
- Artifact: endpoint-agent.exe
- SHA256: 53a45b637147145025b68c5ab1235ae6e6ee491cef9f6925f83a61fb7fb42669
- Cihaz listesi: HALILKOOLUB735 (Parallels W11), <yeni VM names>
- Süre: 2026-05-24 → 2026-06-24 (max 30 gün; yenileme: yeni evidence + ADR review)
- Sınır: A1 workgroup lab cihazları only; A2 BYOD / A3 Entra / A4 Workplace için signed mandatory
- Boundary: lab exception rollout-ready DEĞİL; production binary distribution AG-018/AG-024 unlock şart
```

---

## 8. Identity classification precheck

### 8.1 Agent capability gap

Source-foundation status (post-platform-agent PR #17 `91ef533d` MERGED 2026-05-26 + HALILKOOLUB735 `WORKGROUP`/`LOCAL` read-only evidence):

| Capability | Agent state | Backend state | TRACKING-ROADMAP |
|---|---|---|---|
| Hostname + Domain + PartOfDomain | ✅ inventory.go via `Win32_ComputerSystem` (mevcut) | ✅ heartbeat payload (mevcut) | AG-009 DONE |
| `dsregcmd /status` parse (AzureAd / Workplace join) | ✅ `internal/identity` package (platform-agent #17 MERGED `91ef533d`) | 🟡 source-ready via `COLLECT_INVENTORY.identity` block; admin identity compliance API ayrı kapı | **AG-021** source MERGED (field/multi-device acceptance ayrı gate) |
| Logged-in identity classification (LOCAL/DOMAIN/ENTRA/WORKPLACE/UNKNOWN) | ✅ `internal/identity` classification (platform-agent #17 MERGED `91ef533d`); UPN/SID hash/mask, raw UPN/full SID yok | 🟡 source-ready via `COLLECT_INVENTORY.identity` block | **AG-022** source MERGED (field/multi-device acceptance ayrı gate) |
| Endpoint identity compliance API (admin surface) | N/A | ❌ admin API yok | **BE-015** TODO |
| KVKK retention enforcement | ❌ | ❌ retention policy enforce yok | **BE-019** TODO |
| Trusted signing pipeline | ❌ | N/A | **AG-018 / AG-024** TODO |

AG-021/022 source-foundation A1 workgroup (HALILKOOLUB735 `WORKGROUP`/`LOCAL` evidence) sınıfında **read-only classification** ile kanıtlanmış; A3 Entra-joined / A4 Workplace-registered acceptance hâlâ **field evidence + BE-015 admin API + signed binary + EDR allowlist + KVKK gate** bağımlı (gitops #1044 PASS DEĞİL; gitops #1037 unblocked DEĞİL).

### 8.2 Pre-check script — agent-native + raw probe parity

Post-AG-021/022 source-foundation (platform-agent #17 MERGED), agent CLI native komut **kanonik yol**:

```bash
# Agent-native (preferred — sanitized JSON output)
endpoint-agent diagnose identity > identity.json

# Raw probe parity (audit/operator visibility — agent dışında PowerShell)
prlctl exec "Windows 11" powershell -NoProfile -Command "
dsregcmd /status | Select-String -Pattern 'AzureAdJoined|EnterpriseJoined|DomainJoined|DeviceName|TenantName|WorkplaceJoined'
" 2>&1 | redact | tee -a precheck.txt

# Classification logic — agent-side (LOCAL/DOMAIN/ENTRA/WORKPLACE/UNKNOWN)
# Decision tree §4.3 ile uyumlu; raw output redact + UPN/SID hash/mask kanıt
```

`scripts/test/parallels-windows11-ci.sh` agent-native `diagnose identity` ile genişletilmesi follow-up PR (ayrı tur — CI script alignment).

### 8.3 Backend identity compliance API (BE-015 unlock öncesi)

Mevcut heartbeat payload generic `inventory/localUsers/metrics` field'ları taşıyabiliyor (Codex source verify: `AgentHeartbeatRequest.java`). Identity classification için canonical admin API:

```
GET /api/v1/endpoint-admin/endpoint-devices/{deviceId}/identity-compliance
→ {
    "tier": "A1" | "A2" | "A3" | "A4" | "B1" | "B2",
    "partOfDomain": false,
    "azureAdJoined": false,
    "workplaceJoined": false,
    "tenantId": null,
    "deviceClass": "standalone" | "byod" | "entra" | "workplace",
    "ownership": "corporate" | "personal",
    "classifiedAt": "2026-05-24T12:00:00Z"
  }
```

Bu API `BE-015` TODO; runbook'ta placeholder olarak referans, gerçek implementasyon ayrı tur.

---

## 9. Install / Enroll / Heartbeat / Inventory flow

### 9.1 Mevcut substantive flow (PR #1021 BE-011 lifecycle)

Mevcut HALILKOOLUB735 evidence (gitops PR #1021):

1. **Backend admin enrollment token mint** (Mac side):
   ```bash
   TOKEN=$(curl -sk -X POST 'https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments' \
     -H "Authorization: Bearer $C5PERSONA_ADMIN_9001_JWT" \
     -H 'Content-Type: application/json' \
     -d '{"description":"Pilot device HALILKOOLUB735"}' | jq -r .token)
   ```

2. **Agent install** (VM side, admin PowerShell):
   ```powershell
   .\install.ps1 -ApiUrl 'https://testai.acik.com/api/v1/endpoint-agent' `
                 -EnrollmentToken $TOKEN `
                 -Start
   ```

3. **Enroll + heartbeat verify** (agent log):
   ```
   2026/05/24 12:51:10 agent enrolled: device=d0efb00a-... credential=<redacted>
   2026/05/24 12:51:11 no command available
   2026/05/24 12:51:41 no command available  (30s heartbeat poll)
   ```

4. **Backend device list verify** (Mac side):
   ```bash
   curl -sk -X GET 'https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices?hostname=HALILKOOLUB735' \
     -H "Authorization: Bearer $C5PERSONA_ADMIN_9001_JWT"
   ```

### 9.2 Non-domain class farklılaşması (A1-A4)

| Tier | Install method | Identity tier classification | Read/Write scope |
|---|---|---|---|
| A1 standalone | local install.ps1 (operator manual veya CI) | A1 (PartOfDomain=false, all joins=NO) | full pilot (enroll + heartbeat + non-destructive command + inventory) |
| A2 BYOD | signed installer + consent flow (§12) | A2 (operator-flagged ownership=personal) | full pilot + consent gate |
| A3 Entra | local install.ps1 (corporate IT push veya manual) | A3 (AzureAdJoined=YES) | **read-only** (enroll + heartbeat + inventory; non-destructive command only — Graph/Intune mgmt out-of-scope) |
| A4 Workplace | local install.ps1 (limited corporate access) | A4 (WorkplaceJoined=YES, AzureAdJoined=NO) | **read-only inventory/support** |

### 9.3 Cleanup (post-pilot per device)

Mevcut `scripts/test/windows-live.ps1` cleanup chain:
- Service stop + uninstall (with maintenance token; PR #978 BE-013)
- Install dir + log dir removal
- Env var cleanup
- Backend device decommission (admin REST `DELETE /api/v1/endpoint-admin/endpoint-devices/{deviceId}`)

Per device evidence'a final state record.

---

## 10. Non-destructive command smoke

### 10.1 Allowed commands (real device pilot)

| Command | BE source | Destructive? | Pilot scope |
|---|---|---|---|
| `COLLECT_INVENTORY` | BE-008 + BE-011 | NO | A1-A4 hepsi |
| `inventory_refresh` | BE-008 | NO (same as COLLECT_INVENTORY trigger) | A1-A4 hepsi |
| `GET_LOGGED_IN_USER` | AG-010 | NO (read-only identity probe) | A1-A4 hepsi (BYOD A2 için redaction policy §4.4) |
| `GET_USER_HOME_PATHS` | AG-010 | NO (read-only path enumeration) | A1-A4 hepsi |
| `LIST_LOCAL_USERS` | AG-013 (Windows only) | NO (read-only) | A1-A4 hepsi |

### 10.2 Forbidden commands (real device pilot)

| Command | BE source | Destructive? | Why forbidden |
|---|---|---|---|
| `LOCK_USER_LOGIN` | BE-017 dual-control | YES | real user lockout — BYOD/standalone user erişim kaybı; BE-017 fixture-only proof (PR #1032) |
| `DISABLE_LOCAL_USER` / `ENABLE_LOCAL_USER` | AG-013 absent capability | YES | user account state change; AG-013 capability coherence guard absent post-fix |
| `password_reset` (local + AD + Entra + M365) | BE-018B BLOCKED | YES | user credential rotation; ADR-0012-EA D35-EA-5 dual-control + audit immutable gate |
| `software_uninstall` | TBD (AG backlog) | YES | system mutation; pilot scope dışı |
| `service_disable` | TBD (AG backlog) | YES | service state change; pilot scope dışı |
| `network_isolate` | TBD (AG backlog) | YES | firewall isolate; pilot scope dışı |
| `system_format` | TBD (AG backlog) | YES | disk/partition format; ABSOLUTE NO |

### 10.3 Smoke flow per device

```bash
# Per device, post-install + post-enroll + post-heartbeat stable:

# 1. Create COLLECT_INVENTORY command
COMMAND=$(curl -sk -X POST "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices/$DEVICE_ID/commands" \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "COLLECT_INVENTORY",
    "reason": "Faz 22.2.A non-domain pilot smoke 2026-05-24",
    "priority": 100,
    "idempotencyKey": "fp22-2a-collect-inv-'$(date +%Y%m%d%H%M%S)'"
  }')

# 2. Wait for SUCCEEDED (agent poll interval 30s)
sleep 90

# 3. Verify result
curl -sk -X GET "https://testai.acik.com/api/v1/endpoint-admin/endpoint-commands/$COMMAND_ID" \
  -H "Authorization: Bearer $JWT" | jq '.status, .result.payload.details.inventory'

# Expected: status="SUCCEEDED", inventory payload with hostname/osName/osFamily
```

### 10.4 Audit chain verify

```bash
# REST audit chain (post-smoke)
curl -sk -X GET "https://testai.acik.com/api/v1/endpoint-admin/endpoint-audit-events?commandId=$COMMAND_ID" \
  -H "Authorization: Bearer $JWT" | jq '.[].eventType'

# Expected: ENDPOINT_COMMAND_CREATED only (non-destructive command create emits 1 audit row;
# dispatch/start/complete lifecycle state'leri ENDPOINT_COMMAND_DISPATCHED veya ENDPOINT_COMMAND_COMPLETED
# audit row emit ETMEZ — bunlar command field'larında tutulur: deliveredAt / startedAt / completedAt).
# Codex 019e5b17 iter-2 absorb (source-truth verify): backend `EndpointAdminCommandService`
# non-destructive command create için ENDPOINT_COMMAND_CREATED; lifecycle command/result endpoint
# veya DB field'ları üzerinden doğrulanır. Dual-control destructive command için ek
# ENDPOINT_COMMAND_APPROVED veya ENDPOINT_COMMAND_REJECTED emit edilir (BE-017 PR #1032 evidence).

# Command lifecycle field verify (mandatory)
curl -sk -X GET "https://testai.acik.com/api/v1/endpoint-admin/endpoint-commands/$COMMAND_ID" \
  -H "Authorization: Bearer $JWT" | jq '{status, deliveredAt, startedAt, completedAt}'

# Expected:
# {
#   "status": "SUCCEEDED",
#   "deliveredAt": "2026-05-24T...Z",
#   "startedAt": "2026-05-24T...Z",
#   "completedAt": "2026-05-24T...Z"
# }
```

DB-direct hash-chain verify (BE-016) per ADR-0012-EA — optional, advanced verification (V4 prev_event_hash/event_hash linkage; non-destructive command için tek-row audit, chain length=1).

---

## 11. 24-72h soak observation

### 11.1 Minimum acceptance (Codex Q6 absorb)

- **Süre**: minimum 24h, tercihen 72h
- **Heartbeat interval**: agent declared (default 30s) ± 10s tolerance
- **Offline gap threshold**: > 30 dk → alert/flag (planned reboot/sleep windows separately tagged)
- **Planned `COLLECT_INVENTORY` / `inventory_refresh` commands**: ALL terminal `SUCCEEDED` veya açıklanmış `FAILED` (timeout/network/transient)
- **Agent service**: no unexplained crash/uninstall/tamper events; audit trail clean

### 11.2 Küçük N (1-3 device) için kabul kriteri

% metrik yerine **explicit count** kullan:

```
Per device:
- 0 unexplained offline > 30 dk
- 0 unhandled command timeout
- All planned non-destructive commands accounted (CREATED → SUCCEEDED veya FAILED-with-reason)
- 0 agent service crash/uninstall/tamper event
```

### 11.3 Backend telemetry query (interim — Prometheus + Grafana setup öncesi)

> **Source-truth verified columns** (Codex 019e5b17 iter-2 absorb): `endpoint_heartbeats.received_at` (NOT `reported_at`) + `endpoint_commands.command_type` (NOT `type`). Backend migration kanonik şemaya bağlı.

```sql
-- DB-direct query (psql via platform-pg-test):
-- Heartbeat history per device
SELECT device_id, MAX(received_at) AS last_seen,
       COUNT(*) AS heartbeat_count_24h
FROM endpoint_admin_service.endpoint_heartbeats
WHERE received_at > now() - interval '24 hours'
GROUP BY device_id;

-- Command lifecycle per device
SELECT device_id, command_type, status,
       (completed_at - issued_at) AS duration
FROM endpoint_admin_service.endpoint_commands
WHERE issued_at > now() - interval '24 hours'
ORDER BY device_id, issued_at;
```

#### 11.3A Read-only rollup helper (#1044)

24h soak penceresi tamamlandıktan sonra DB-direct SQL'i elle tekrar yazmak
yerine read-only helper ile aynı source-truth kolonları üzerinden rollup fact
set'i çıkarılır:

```bash
# Dry-run: SQL + threshold bilgisini basar, DB'ye bağlanmaz.
bash scripts/faz22-non-domain/a1-soak-rollup.sh

# Test host üzerinden read-only psql; credential argümanı almaz/yazmaz.
bash scripts/faz22-non-domain/a1-soak-rollup.sh \
  --execute \
  --ssh-target halil@staging-sw \
  --ssh-identity-file ~/.ssh/id_ed25519 \
  --device-id <HALILKOOLUB735-device-uuid> \
  --device-id <NONDOMAIN-W11-LAB-01-device-uuid> \
  --device-id <NONDOMAIN-W11-LAB-02-device-uuid>
```

Helper sözleşmesi:
- `SELECT`-only; endpoint/admin/runtime state mutate etmez.
- Varsayılan mod dry-run'dır.
- SSH execution path `BatchMode=yes` + `IdentitiesOnly=yes` kullanır; parola
  prompt'u açmaz ve çok fazla ssh-agent identity nedeniyle false-fail riskini azaltır.
- `endpoint_heartbeats.received_at` ve `endpoint_commands.command_type`
  source-truth kolonlarını kullanır.
- `ROLLUP_FACTS_OK`, tek başına acceptance PASS değildir; per-device evidence
  (§14.1+§14.2) ve pilot-wide rollup (§14.3+§14.4) içine taşınacak fact set'idir.
- `NO_HEARTBEAT_DATA`, `GAP_REVIEW`, `COMMAND_REVIEW` veya
  `LOW_HEARTBEAT_RATIO` verdict'i, operator açıklaması ve/veya yeniden soak
  gerektirir.

#### 11.3B Pilot-wide rollup draft generator (#1044)

`a1-soak-rollup.sh --execute` çıktısı dosyaya alındıktan sonra §14.3/§14.4
formatındaki pilot-wide rollup taslağı local generator ile üretilebilir:

```bash
bash scripts/faz22-non-domain/a1-soak-rollup.sh \
  --execute \
  --ssh-target halil@staging-sw \
  --ssh-identity-file ~/.ssh/id_ed25519 \
  --device-id <HALILKOOLUB735-device-uuid> \
  --device-id <NONDOMAIN-W11-LAB-01-device-uuid> \
  --device-id <NONDOMAIN-W11-LAB-02-device-uuid> \
  > /tmp/faz22-a1-soak-rollup.txt

python3 scripts/faz22-non-domain/a1-rollup-doc-from-soak.py \
  --soak-output /tmp/faz22-a1-soak-rollup.txt \
  --output-dir docs/faz-22-evidence \
  --soak-window "<iso-start> -> <iso-end>" \
  --device "<HALILKOOLUB735-device-uuid>=HALILKOOLUB735,A1,./YYYY-MM-DD-non-domain-pilot-tierA1-HALILKOOLUB735.md,PENDING" \
  --device "<NONDOMAIN-W11-LAB-01-device-uuid>=NONDOMAIN-W11-LAB-01,A1,./YYYY-MM-DD-non-domain-pilot-tierA1-NONDOMAIN-W11-LAB-01.md,PENDING" \
  --device "<NONDOMAIN-W11-LAB-02-device-uuid>=NONDOMAIN-W11-LAB-02,A1,./YYYY-MM-DD-non-domain-pilot-tierA1-NONDOMAIN-W11-LAB-02.md,PENDING"
```

Generator local dosya okur/yazar; SQL çalıştırmaz, backend'e bağlanmaz,
command dispatch yapmaz ve runtime state mutate etmez. Default `PARTIAL`
taslak üretir; final PASS/PARTIAL/FAIL kararı per-device evidence doc'ları,
planned command facts ve operator-reviewed soak notları tamamlandıktan sonra
verilir.

### 11.4 Operator dashboard (future)

`BE-XXX` future task: Prometheus exporter `endpoint_agent_last_seen_seconds` + Grafana dashboard "Endpoint Pilot — Device Status" + Alertmanager rule "DeviceOfflineGap > 30m". Pilot evidence'da placeholder olarak referans, gerçek implementasyon ayrı tur.

---

## 12. BYOD consent, privacy, KVKK, uninstall (A2 ONLY)

### 12.1 Consent flow (A2 BYOD acceptance prerequisite)

A2 BYOD class için **explicit consent şart** (Codex Q4 absorb):

1. **Bilgilendirme metni** (kullanıcıya, Türkçe + English):
   - Toplanan veri kategorileri (hostname, machine fingerprint, OS version, logged-in identity, local users, app inventory varsa, heartbeat timestamps, command audit metadata)
   - Veri kullanım amacı (endpoint güvenlik telemetri + audit + compliance)
   - Retention süresi (raw inventory 30 gün; audit/command receipts 90 gün)
   - Kullanıcı hakları (KVKK Madde 11: erişim, düzeltme, silme, açıklama)
   - Uninstall self-service yolu (kullanıcı local admin ile `uninstall.ps1` çalıştırabilir)
   - DPO contact info (operator/IT side)

2. **Açık opt-in** (yazılı imza veya digital consent platform):
   - Kullanıcı consent metnini imzalar / digital onay verir
   - Consent ID evidence'a (raw consent text personal data; consent ID only logged)

3. **Reddi kabul** (opt-out):
   - Kullanıcı consent vermezse agent install YAPILMAZ
   - Operator alternatif: A1 standalone corporate-owned device (eğer mevcut)

### 12.2 KVKK data inventory + retention

| Veri kategorisi | Field | Retention | Anonymization/redaction |
|---|---|---|---|
| Machine identifier | hostname, machine_fingerprint | 90 gün (audit) | full-text (machine-level, not personal) |
| OS metadata | osName, osFamily, osVersion, osBuild | 90 gün | full-text |
| Network identifier | ipAddress | 30 gün | last-octet redacted (`192.168.1.***`) post-30d |
| Logged-in identity | UPN, SID, displayName, lastLogon | 30 gün raw + 90 gün hashed | UPN → `sha256:abc...`, SID → `S-1-5-21-***-***-***-NNNN`, displayName → first-initial only (`J.D.`) |
| Local users (Win) | username, enabled, lastLogon | 30 gün | username full-text (machine-level), lastLogon rounded to day |
| Installed software | name, version, publisher, installDate | 30 gün | full-text (no path/uninstall string) |
| Heartbeat | timestamp, lastSeen, agentVersion | 90 gün | full-text |
| Command/audit | type, status, duration, audit row hash | 365 gün (audit integrity) | full-text + hash-chain (BE-016) |

`BE-019` KVKK retention enforcement gate (TRACKING-ROADMAP backlog) — bu policy enforce eden backend mekanizma; MERGED olmadan A2 BYOD acceptance verilmez (compliance gap).

### 12.3 Uninstall self-service (A2 BYOD HARD)

Kullanıcı local admin yetkisiyle agent'ı kaldırabilmeli:

```powershell
# Method 1: installer uninstall script (preferred)
cd "C:\Program Files\EndpointAgent"
.\uninstall.ps1 -RemoveConfig -RemoveLogs

# Method 2: Add/Remove Programs (Settings → Apps → EndpointAgent → Uninstall)

# Method 3: PowerShell direct (fallback)
Stop-Service EndpointAgent
sc.exe delete EndpointAgent
Remove-Item -Path "C:\Program Files\EndpointAgent" -Recurse -Force
Remove-Item -Path "C:\ProgramData\EndpointAgent" -Recurse -Force
```

Post-uninstall:
- Backend device decommission (operator action: admin REST `DELETE /endpoint-devices/{id}` veya admin API "decommission" workflow — gerek varsa `BE-XXX` future task)
- Agent data backend'de soft-delete + retention policy per §12.2
- BYOD kullanıcı bilgilendirme: "Agent kaldırıldı; backend'de data X gün içinde silinecek per KVKK Madde 7"

---

## 13. Acceptance gates matrix

### 13.1 Per-gate breakdown (Codex Q2 absorb)

| Gate | Sınıf | Effort | Bağımlılık | Status (2026-06-07 — #12 workflow PASS + #1044 linked-clone preflight update) |
|---|---|---:|---|---|
| Self-hosted CI run (Parallels W11 lab gate) | Karma | agent 0.5-1g + operator 0.5g | self-hosted Mac runner + Parallels VM + labels + artifact upload + secret scan | ✅ DONE 2026-06-07: platform-agent PR #78 + workflow run `27081667910` + gitops PR #1300 evidence; artifact secret scan clean |
| 2+ standalone device evidence (A1 multi-VM) | Karma | docs/evidence 0.5g + operator 0.5-1g/device | cihaz temini (gerçek veya Parallels VM) + local admin + backend reachability | ⏳ pending (mevcut 1 VM HALILKOOLUB735). 2026-06-07 linked-clone preflight: full clone disk-unsafe; parent VM must be stopped/suspended before `prlctl clone --linked` |
| 24-72h soak observation | Karma | metric/query 1-2g + wall-clock 1-3g | heartbeat visibility + offline threshold + command/result query | ⏳ pending (Prometheus/Grafana setup öncesi DB-direct query) |
| Identity classification (A1-A4 detection) | Agent source MERGED; field acceptance pending | agent ✅ source DONE + backend 1-2g (BE-015) + privacy schema | `AG-021` + `AG-022` source MERGED (platform-agent #17 `91ef533d`); `BE-015` + privacy schema pending | 🟡 source DONE (A1 HALILKOOLUB735 `WORKGROUP`/`LOCAL` read-only evidence); field acceptance (multi-device classification + soak) ⏳ pending |
| Signed distribution | Karma / operator-heavy | agent CI 2-4g + Azure/owner 0.5-2g | `SEC-001` + `SEC-002` + Authenticode cert + timestamp + release channel | ⏳ pending (AG-018/AG-024 backlog; ADR pre-req docs) |
| KVKK boundary (A2 BYOD prerequisite) | Karma / operator / legal | docs 0.5-1g + `BE-019` 2-5g | data inventory + retention + erasure/anonymization + DPO/legal approval | ⏳ pending (BE-019 backlog) |
| A2 BYOD consent flow + uninstall self-service | Operator + agent | operator 1-2g + agent docs 0.5g | consent metni + uninstall test | ⏳ pending (BYOD pilot başlamadan önce) |
| EDR allowlist coordination (A2 BYOD prerequisite) | Operator | SOC coordination | `endpoint-agent.exe` SHA + service display name + install path + network destination | ⏳ pending (SOC tarafı) |
| Cross-AI provider-level review per PR | Agent automation | 0.5g per PR | Codex API + audit trail | ✅ active (HARD RULE 2026-05-05 + 2026-05-14) |

### 13.2 Tier-based acceptance summary

| Tier | Minimum acceptance gates |
|---|---|
| **A1 standalone (1 device)** | mevcut substantive evidence ✅ |
| **A1 standalone (2+ device repeatability)** | + 2+ device evidence + CI self-hosted run + 24h soak |
| **A2 BYOD** | A1 + consent flow + signed binary + KVKK + EDR allowlist + uninstall self-service + 72h soak |
| **A3 Entra-joined** | A1 + identity classification (AG-021/022 + BE-015) + signed binary + EDR allowlist |
| **A4 Workplace-registered** | A1 read-only + identity classification + signed binary |

---

## 14. Evidence document template

### 14.1 Per-pilot evidence doc path

`docs/faz-22-evidence/YYYY-MM-DD-non-domain-pilot-tierX-deviceY.md` (tier = A1/A2/A3/A4; device = hostname veya pseudonym)

### 14.2 Required fields

```markdown
# Faz 22.2.A non-domain pilot — Tier <A1/A2/A3/A4>, Device <hostname>

> **Status**: PASS / PARTIAL / FAIL
> **Tracked by**: <board issue #>
> **Tier**: A1/A2/A3/A4 (detection §4.3)
> **Operator**: <name/role>
> **DPO sign-off** (A2 only): <signed-yes/no, consent-id>
> **Codex thread**: <thread-id>

## 1. Identity classification

| Field | Value | Source | Redaction |
|---|---|---|---|
| Hostname | <machine-name> | Win32_ComputerSystem | none |
| PartOfDomain | false | Win32_ComputerSystem | none |
| Domain/Workgroup | <workgroup> | Win32_ComputerSystem | none |
| AzureAdJoined | NO/YES | dsregcmd | none |
| WorkplaceJoined | NO/YES | dsregcmd | none |
| Tenant ID | <hash:abc-last4> | dsregcmd | last-4 only |
| Logged-in identity (UPN) | <sha256:hash> | Win32_LoggedOnUser | hashed |
| Detected tier | A1/A2/A3/A4 | classification logic §4.3 | none |

## 2. Build provenance

- platform-agent commit: <sha>
- endpoint-agent.exe SHA256: <full>
- Authenticode signed?: yes/no (lab exception ref if no)
- install method: <signed installer / unsigned lab>

## 3. Install / Enroll / Heartbeat

- install timestamp: <iso>
- enrollment token mint timestamp: <iso>
- device ID (backend): <uuid>
- enroll timestamp: <iso>
- heartbeat interval (configured): 30s
- heartbeat 24h count: <N>
- heartbeat 24h max gap: <N>s (acceptance: <30m)

## 4. Smoke (non-destructive)

| Command | ID | Status | Duration | Audit row |
|---|---|---|---|---|
| COLLECT_INVENTORY | <uuid> | SUCCEEDED | <Ns> | <uuid> |
| inventory_refresh (optional) | <uuid> | SUCCEEDED | <Ns> | <uuid> |

## 5. Soak observation (24-72h)

| Metric | Value | Acceptance |
|---|---|---|
| Heartbeat success rate | <%> | per-device explicit count §11.2 |
| Unexplained offline > 30m | <N> | 0 required |
| Command timeout | <N> | 0 unhandled |
| Service crash/uninstall/tamper | <N> | 0 unexplained |

## 6. KVKK / consent (A2 BYOD only)

- Consent ID: <id>
- Consent timestamp: <iso>
- Data inventory ref: §12.2
- Retention policy enforced (BE-019): pending / active
- Uninstall self-service tested: yes/no

## 7. EDR allowlist (A2/A3/A4 only)

- SOC ticket: <id>
- Agent SHA256 allowlisted: <full>
- Service display name allowlisted: EndpointAgent
- Install path allowlisted: C:\Program Files\EndpointAgent

## 8. Cleanup / rollback

- Uninstall timestamp: <iso>
- Install dir removed: yes
- Log dir removed: yes
- Backend device decommission: <iso>
- KVKK data purge: yes/N day retention

## 9. Cross-AI peer review

Implementer AI: Claude (Anthropic)
Reviewer AI: Codex (OpenAI)
Codex thread: <thread-id>
Verdict: AGREE / PARTIAL / REVISE

## 10. Boundary

- NOT prod-ready / NOT password-reset-ready / NOT domain-wide rollout-ready
- Tier <A1/A2/A3/A4> scope only; other tiers ayrı evidence
- Non-destructive command only (real device)
- Test persona JWT only (backend admin actions)
```

### 14.3 Pilot-wide rollup evidence doc path

`docs/faz-22-evidence/YYYY-MM-DD-non-domain-pilot-tier<A1/A2/A3/A4>-rollup.md`

Path naming convention:
- **Tier prefix**: `tierA1` (multi-device A1 repeatability), `tierA2` (multi-device BYOD), etc.
- **One rollup per pilot scope**: A1 multi-VM rollup ≠ A2 BYOD rollup (ayrı doc; iki tier karışık dahil edilemez)
- **Tracked by**: rollup ait olduğu pilot board issue (örn. #1044 A1 multi-VM repeatability)

### 14.4 Pilot-wide rollup required fields

Per-device evidence doc'ları (§14.1+§14.2) tamamlandıktan sonra agent rollup doc'ı doldurur. Operator infaz sırasında değil; **post-soak verification phase**.

```markdown
# Faz 22.2.A non-domain pilot rollup — Tier <A1/A2/A3/A4> multi-device

> **Status**: PASS / PARTIAL / FAIL
> **Tracked by**: <board issue #> (örn. #1044)
> **Tier**: A1/A2/A3/A4 (per-device §14.2 §1 sınıflandırması ile tutarlı)
> **Scope**: <minimum device count target> devices (örn. 3 = HALILKOOLUB735 + 2 fresh Parallels VM)
> **Soak window**: <iso-start> → <iso-end> (minimum 24h; tercihen 72h)
> **Codex thread**: <thread-id>

## 1. Device summary table

| # | Hostname (or pseudonym) | Tier (detected) | Per-device evidence doc | Status |
|---|---|---|---|---|
| 1 | <hostname-or-pseudonym> | A1/A2/A3/A4 | [link](./YYYY-MM-DD-non-domain-pilot-tierX-deviceY.md) | PASS/PARTIAL/FAIL |
| 2 | ... | ... | ... | ... |
| 3 | ... | ... | ... | ... |

## 2. Aggregate metrics (per §14.5 formula)

| Metric | Value | Acceptance threshold | Verdict |
|---|---|---|---|
| Heartbeat success rate (pilot-wide) | <%> | ≥99% (24h window per device) | PASS/PARTIAL/FAIL |
| Command terminal/accounted rate (pilot-wide) | <%> | 100% (no CREATED/RUNNING/UNKNOWN after soak window) | PASS/PARTIAL/FAIL |
| Command success rate (pilot-wide) | <%> | ≥95% (FAILED-with-explained-reason accounted but not success) | PASS/PARTIAL/FAIL |
| Soak gap incidents (unexplained > 30m) | <count> | 0 required | PASS/PARTIAL/FAIL |
| Repeatability gate | PASS / PARTIAL / FAIL | per §14.5 rule | computed |

## 3. Acceptance verdict

**Verdict**: PASS / PARTIAL / FAIL

**Rationale** (1-3 sentences):
- <why PASS — all devices stable, aggregate metrics within threshold>
- <why PARTIAL — N/M devices pass, exception devices documented per-device evidence doc>
- <why FAIL — repeatability gate fail; rollback initiated; root cause linked>

## 4. Cross-device anomaly notes

(opsiyonel — eğer bir device diğerlerinden anlamlı sapma gösterdiyse)

| Device | Anomaly | Root cause (if known) | Action |
|---|---|---|---|
| <hostname> | <e.g. unexplained 45m offline gap day 2> | <e.g. host laptop sleep undeclared> | <e.g. annotated in per-device evidence §5, not pilot-wide regression> |

## 5. Cross-AI peer review

Implementer AI: Claude (Anthropic)
Reviewer AI: Codex (OpenAI)
Codex thread: <thread-id>
Verdict: AGREE / PARTIAL / REVISE

## 6. Boundary

- Tier <A1/A2/A3/A4> scope only; other tier rollup ayrı doc
- **NOT** prod-ready signal — A1 standalone lab repeatability ≠ A1 corporate fleet readiness
- **NOT** rollout-ready signal — repeatability lab proof; gerçek rollout `BE-019` (KVKK retention) + signed binary (AG-018/AG-024) + EDR allowlist coordination gerek
- 24-72h soak ≠ 30-day stability proof
- Test persona JWT only; prod cluster pilot kapsamı dışı (gitops `#1037` ayrı kapı 22.2.B opsiyonel scope)
```

### 14.5 Aggregate metric formula (multi-VM küçük N için)

Per-device explicit count (§11.2) tamamen agent script ile toplandıktan sonra rollup için aggregate computation:

```
# Heartbeat success rate (pilot-wide)
SUM(actual_heartbeat_count_24h_per_device) / SUM(expected_heartbeat_24h_per_device)
  where expected_heartbeat_24h_per_device = 86400 / heartbeat_interval_seconds_per_device
                                          = 2880 if interval = 30s (default)
  rationale: per-device heartbeat interval §14.2 §3'te kayıtlı; default 30s ama
             küçük lab variasyonları olabilir (örn. 60s ile başlatılan device).
             Sabit `N × 2880` denominator yanlış olur eğer bir device farklı
             interval ile çalışıyorsa.
  acceptance: ≥ 99% (allows ~28 missed beats per device per 24h @ 30s default)

# Command terminal/accounted rate (pilot-wide)
SUM(terminated_command_count_per_device) / SUM(total_planned_command_count_per_device)
  where terminated = SUCCEEDED ∪ FAILED-with-explained-reason
  acceptance: 100% (no command may be left in CREATED/RUNNING/UNKNOWN after soak window)

# Command success rate (pilot-wide) — strict
SUM(succeeded_command_count_per_device) / SUM(total_planned_command_count_per_device)
  acceptance: ≥ 95% (≤ 5% FAILED-with-explained-reason tolerated; absolute SUCCEEDED count
              critical for repeatability)
  rationale: FAILED-with-explained-reason terminal'dir (accounted) ama success
             değildir. Per-device gate'te accounted ama PASS verdict'e success-rate
             katkı sıfırdır. Pilot-wide aggregate'te ayrı tracked.

# Soak gap incidents (pilot-wide)
SUM(unexplained_offline_gap_count_per_device WHERE gap > 30m AND not in declared_sleep_window)
  acceptance: 0 incidents
```

#### Repeatability gate (PASS / PARTIAL / FAIL)

Küçük N pilot için **per-device gate** öncelikli, aggregate threshold ikincil:

| Verdict | Rule |
|---|---|
| **PASS** | ALL devices PASS at §14.2 acceptance (per-device explicit count §11.2 + soak §11.1) AND aggregate metrics within §14.5 threshold |
| **PARTIAL** | `pass_devices >= ceil(2 × N_devices / 3)` (örn. 3-device pilot için ≥2 PASS; 4-device için ≥3 PASS; 6-device için ≥4 PASS) AND failed device(s) ALL satisfy §14.5.1 isolation checklist below AND aggregate metrics within threshold when failed device(s) excluded |
| **FAIL** | `pass_devices < ceil(2 × N_devices / 3)` OR ANY isolation checklist item fails for ANY failed device OR systemic agent bug (crash/uninstall/tamper) on any device OR aggregate metrics below threshold even after isolated device exclusion |

##### 14.5.1 Isolation checklist (PARTIAL verdict objective criteria)

PARTIAL kararı verilebilir ancak failed device(s) için **TÜM** aşağıdaki maddeler kanıtlanırsa. **Eksik bir madde = FAIL** (sübjektif "operator inisiyatifi" yok).

- [ ] **Incident scope**: Failed device per-device evidence doc §5'te exact incident tipi + zaman aralığı + count dokümante (örn. "unexplained offline gap 45m at 2026-05-29T14:23Z—15:08Z")
- [ ] **Agent build parity**: Failed device ile en az 2 peer PASS device'da **aynı** `endpoint-agent.exe SHA256` (§14.2 §2 build provenance ile cross-check)
- [ ] **Command set parity**: Failed device ile peer PASS device'larda **aynı** planned command set koşturuldu (§14.2 §4 smoke list ile cross-check)
- [ ] **No matching error signature**: Peer PASS device'ların audit/heartbeat/agent log'larında failed device'ın error signature'ı (exception class, stack trace head, log message head) **bulunmuyor**
- [ ] **Host/operator-specific causality**: Failed device'ın incident nedeni host-specific veya operator-specific olarak kanıtlı (örn. host laptop sleep undeclared; operator network outage; VM provisioning artifact)
- [ ] **Aggregate restoration**: Failed device exclude edildiğinde §14.5 **dört** aggregate check (heartbeat success rate / command terminal/accounted rate / command success rate / soak gap incidents) **tümü** threshold dahilinde

**Rollback signal**: FAIL verdict → §15.2 pilot-wide rollback initiated; root cause analysis cross-AI review (Codex) per §17.

### 14.6 A2 BYOD rollup appendix (extra fields)

A2 BYOD rollup için §14.4 6-bölüm template **+ aşağıdaki appendix** eklenir (A2 acceptance kapısı §12.1+§12.3 + §13.1 satırı + ADR-0012-EA scope amendment "A2 BYOD class"). A1 standalone rollup için bu appendix YAZIL**MA**Z (over-spec; A1 evidence kapsamı dışı).

#### 14.6.1 BYOD scope context

A2 BYOD per §13.2 tier summary "A1 + consent flow + signed binary + KVKK + EDR allowlist + uninstall self-service + 72h soak". A2 rollup verdict bu kapsamın **her birinin tüm device'larda kanıtlanmasına** bağlı; A1 §14.4 + §14.5 pass etmek yeterli değildir.

#### 14.6.2 Required appendix template

`docs/faz-22-evidence/YYYY-MM-DD-non-domain-pilot-tierA2-rollup.md` §14.4 6-bölümün **sonuna** §A2-A ile §A2-F ekle:

```markdown
## §A2-A. Consent coverage (per-device)

| # | Device (hash/pseudonym) | Consent ID | Consent timestamp | DPO/legal sign-off | Bilgilendirme dili |
|---|---|---|---|---|---|
| 1 | <hash> | <consent-id> | <iso> | yes/no (signature ref) | TR/EN |
| 2 | ... | ... | ... | ... | ... |

**Aggregate**: `consent_coverage = signed_consent_devices / installed_enrolled_A2_pilot_devices` — acceptance: **N/N (100%)**. **Denominator clarification**: opt-out adaylar rollup denominator'a dahil DEĞİL (operator opt-out log'una ayrı kayıt); rollup denominator yalnız installed + enrolled A2 pilot device set. Eksik bir installed/enrolled device varsa A2 rollup FAIL (consent prerequisite §12.1).

## §A2-B. KVKK / privacy compliance

| Compliance gate | Per-device evidence link | Status |
|---|---|---|
| Data inventory referenced (§12.2 mapping) | <link> | ✅ / ❌ |
| Retention policy enforced live (BE-019) | <link or "pending"> | ✅ active / 🟡 pending / ❌ missing |
| Erasure/anonymization runtime check | <link> | ✅ / ❌ |
| KVKK Madde 11 user rights addressable (DPO request-channel smoke + sample DSAR workflow + DPO sign-off ref) | <link> | ✅ / ❌ |
| Consent withdraw self-service tested | <link> | ✅ / ❌ |

**Aggregate**: TÜM 5 gate ✅ olmalı; **BE-019 🟡 pending durumunda A2 rollup verdict en fazla PARTIAL**. ❌ veya missing varsa FAIL.

## §A2-C. Uninstall self-service (per-device)

| # | Device (hash) | Method tested | Method success | Backend decommission | Post-uninstall data purge |
|---|---|---|---|---|---|
| 1 | <hash> | installer/Add-Remove/PowerShell | yes/no | <iso decommission> | yes (per BE-019) / N gün retention |
| 2 | ... | ... | ... | ... | ... |

**Aggregate**: `uninstall_success = successful_uninstall_devices / total_devices` — acceptance: **N/N (100%)**. Per §12.3 BYOD HARD requirement.

## §A2-D. Signed artifact verification

| # | Device (hash) | Installed agent SHA256 | Signed (Authenticode)? | Trusted Signing timestamp valid? | Signer subject |
|---|---|---|---|---|---|
| 1 | <hash> | <sha256> | yes (mandatory A2) | yes (RFC 3161) | <CN/O extracted from cert> |

**Verification command** (operator script — visual review yetersiz):
```powershell
# Authenticode + RFC 3161 verify + thumbprint/subject allowlist match
signtool verify /pa /v /tw "C:\Program Files\EndpointAgent\endpoint-agent.exe"
# Capture: SHA256 + Authenticode result + Timestamp result + Signer Subject (CN/O)
# Match: Subject regex against Trusted Signing tenant allowlist (operator runbook §13.1)
```

**Aggregate**: TÜM device'lar signed + valid timestamp + signer subject Trusted Signing tenant ile match olmalı (`signtool verify /pa` output + thumbprint/subject allowlist check). Tek unsigned device varsa A2 rollup **FAIL** (signed distribution prerequisite §13.1 + AG-024).

## §A2-E. EDR allowlist coverage (SOC coordination)

| Gate | Per-device evidence | Status |
|---|---|---|
| SOC ticket ID + coordination doc | <ticket-id> | ✅ closed / 🟡 open / ❌ missing |
| Agent SHA256 allowlisted at EDR vendor | <sha256> + allowlist-id | ✅ / ❌ |
| Service display name `EndpointAgent` allowlisted | <allowlist-id> | ✅ / ❌ |
| Install path `C:\Program Files\EndpointAgent` allowlisted | <allowlist-id> | ✅ / ❌ |
| Network destination (actual pilot environment destination(s) — örn. `testai.acik.com:443` A2 lab pilot; prod evaluation ayrı PR + ayrı `ai.acik.com:443` allowlist gate) | <allowlist-id> | ✅ / ❌ |

**Aggregate**: TÜM 5 gate ✅ olmalı; eksik bir gate varsa A2 rollup FAIL (EDR coordination prerequisite §13.1).

## §A2-F. BE-019 KVKK retention enforcement status

| Field | Value | Source |
|---|---|---|
| BE-019 PR | <#N> | backend repo |
| BE-019 status | MERGED / source-ready / backlog | platform-backend tracking-roadmap |
| Retention policy enforced (live) | yes / no | backend smoke evidence (binary — `live` semantic sadece "enforce ediliyor mu / etmiyor mu"; nuanced gap `TTL match` alanı `partial` ile taşınır) |
| Per-data-category retention TTL match §12.2 | yes / partial / no | backend integration test ref — `partial` durumunda affected categories list + manual gap ref (operator-side documentation) zorunlu |

**Aggregate**: BE-019 MERGED + live enforcement + §12.2 TTL match = A2 rollup eligible. BE-019 pending durumunda A2 rollup verdict en fazla **PARTIAL** + explicit "BE-019 unlock gate not satisfied; BYOD acceptance defer" rationale.
```

#### 14.6.3 A2 rollup verdict adjustment matrix

§14.5 standart PASS/PARTIAL/FAIL kuralı **A2 için ek constrait** ile bağlı:

| §A2 section | PASS prerequisite for A2 verdict |
|---|---|
| §A2-A Consent coverage | N/N (eksik = FAIL, geçici PARTIAL yok) |
| §A2-B KVKK compliance | 5/5 ✅ (BE-019 🟡 → en fazla PARTIAL) |
| §A2-C Uninstall self-service | N/N (eksik = FAIL) |
| §A2-D Signed artifact | TÜM device signed + timestamp + signer match (eksik = FAIL) |
| §A2-E EDR allowlist | 5/5 ✅ (SOC ticket closed; eksik = FAIL) |
| §A2-F BE-019 enforcement | MERGED + live=yes + §12.2 TTL match=yes (status pending/source-ready OR TTL=partial → max PARTIAL; live=no OR TTL=no → FAIL) |

**A2 final verdict rule** (explicit hard-gate vs deferred-unlock semantics):

- **PASS**:
  - §14.5 PASS AND
  - §14.6 §A2-A consent N/N AND §A2-C uninstall N/N AND §A2-D signed all PASS AND §A2-E EDR 5/5 AND
  - §14.6 §A2-B KVKK 5/5 ✅ (no ❌, no missing) AND
  - §14.6 §A2-F BE-019 status=MERGED **AND** live=yes **AND** §12.2 TTL match=yes

- **PARTIAL** (deferred-unlock semantic — sınırlı kapsam):
  - §14.5 PASS/PARTIAL AND
  - §14.6 §A2-A consent N/N AND §A2-C uninstall N/N AND §A2-D signed all PASS AND §A2-E EDR 5/5 AND
  - **EXACTLY ONE** of:
    - §A2-F BE-019 status=source-ready or backlog (pending deferred); §A2-B retention row 🟡 olabilir
    - §A2-F BE-019 MERGED + live=yes ama §12.2 TTL match partial (operator-side manual gap dokümante)
  - explicit "deferred unlock gate" rationale + planned MERGE/live date

- **FAIL** (any of):
  - §14.5 FAIL
  - §A2-A consent eksik (rollup denominator için)
  - §A2-C uninstall N/N değil
  - §A2-D signed: tek unsigned device VEYA timestamp invalid VEYA signer subject mismatch
  - §A2-E EDR: herhangi 5-gate eksik VEYA SOC ticket open/missing
  - §A2-B KVKK: consent withdrawal ❌ VEYA Madde 11 rights channel ❌ VEYA erasure/anonymization smoke ❌ VEYA data inventory missing (BE-019 pending dışı non-retention KVKK gap)
  - §A2-F BE-019 live=no (status MERGED ama live enforcement YAPIL**MA**MIŞ) — pending statünden farklı: live=no = active mismatch = FAIL
  - §A2-F BE-019 §12.2 TTL match=no (retention live ama TTL canonical inventory ile çakışmıyor) = FAIL

**Anahtar ayrım**:
- BE-019 `pending/source-ready` (henüz MERGE değil) → PARTIAL eligible
- BE-019 `MERGED` ama `live=no` (deployed ama enforce edilmiyor) → **FAIL** (active drift)
- §A2-B KVKK non-retention gates (consent withdrawal / Madde 11 / erasure) ❌ → **FAIL** (BE-019 partial argument geçmez; retention dışı KVKK kapsamı zaten implementasyon gerektirir)

#### 14.6.4 A2 boundary signals

A2 BYOD rollup PASS bile **prod-ready signal değil**:
- A2 pilot scope = lab + sınırlı BYOD opt-in user pool (≤10 device tercih)
- Domain-wide BYOD rollout = ayrı kapı (A3/A4 tier + organizational policy + IT/SOC + legal)
- Trusted Signing **mandatory** A2 (§7.3 SHA-pinned lab exception YASAK)
- KVKK Madde 11 user rights addressable; **legal SLA = 30 gün** (canonical [docs/22-2-kvkk-data-inventory.md](../22-2-kvkk-data-inventory.md) Madde 11/13 response süresi ile hizalı + [docs/22-2-byod-consent-template.md](../22-2-byod-consent-template.md)); **pilot internal target = 7 gün** (operasyonel hedef, DPO sign-off ile dokümante; 7-30 gün arasında response = pilot target miss ama legal compliant); 30 gün geçerse legal non-compliance + immediate escalation (BE-019 enforce + DPO incident response)
- Production BYOD rollout requires **separate prod evidence PR** + DPO/legal/SOC sign-off + live prod enforcement; **bu appendix pilot evidence ONLY** — A2 PASS verdict prod-readiness sinyal etmez

---

## 15. Rollback / cleanup / decommission

### 15.1 Per device cleanup chain

1. Agent service stop (with maintenance token; BE-013 PR #978)
2. Agent uninstall (installer uninstall.ps1)
3. Install dir + log dir cleanup
4. Backend device decommission (admin REST `DELETE` veya admin workflow)
5. KVKK data purge (per retention policy §12.2 — BE-019 enforces)
6. EDR allowlist remove (A2 only — SOC coordination)

### 15.2 Pilot-wide rollback

Eğer pilot fail veya scope iptal:
- Tüm pilot device'ları cleanup chain ile decommission
- Test persona JWT rotate random unknown (PR #1032 pattern)
- OpenFGA tuple cleanup (if any pilot-specific tuple seed)
- Evidence doc'a "Pilot rollback" note + rationale + closure timestamp

### 15.3 Disaster recovery

Agent service crash / tamper / unexplained behavior tespiti:
- Audit trail freeze (BE-016 hash-chain integrity)
- Operator incident response (separate incident doc per ADR-0010)
- Affected device(s) full cleanup + forensic snapshot
- Cross-AI review (Codex) per incident root cause analysis

### 15.4 Parallels snapshot-based atomic rollback (Strateji B — domain join HALILKOOLUB735)

ADR-0012-EA "Strategy B decision (2026-05-25)" kapsamında HALILKOOLUB735 mevcut VM `acik.local` domain'e join edilirken **Parallels snapshot-based atomic rollback** §15.1+§15.2 zincirine alternatif **recommended path**. Disk +1-3GB delta (snapshot copy-on-write); fresh VM gerektirmez.

#### 15.4.1 Pre-domain-join snapshot (zorunlu)

```
Parallels Desktop GUI:
  → HALILKOOLUB735 → Actions menüsü → Take Snapshot...
  → Name: pre-domain-join-A1-baseline-2026-05-25
  → Description: A1 baseline pre-domain-join (PR #1021 evidence context); rollback hattı.
  → Save
```

CLI alternatifi (`prlctl`):
```bash
prlctl snapshot HALILKOOLUB735 --name "pre-domain-join-A1-baseline-2026-05-25" --description "A1 baseline pre-domain-join rollback"
```

**Verification**: `prlctl snapshot-list HALILKOOLUB735` → snapshot mevcut + timestamp doğru.

#### 15.4.2 Rollback senaryosu

Domain join sonrası beklenmedik durum (DC discovery fail, Kerberos auth break, AD cached credential issue, agent service crash domain context'te, identity discovery scope drift, vb.):

> **⚠️ ÖNEMLİ — Codex iter-1 BLOCKER düzeltmesi (2026-05-25)**: Parallels snapshot restore **sadece VM-local state**'i geri alır. **AD'deki computer object orphan kalır** (Add-Computer başarılı olduysa AD'de oluşmuştur). AD cleanup AYRI GATE — snapshot restore otomatik çözmez. Aşağıdaki 5-step zincir VM rollback **+ AD post-rollback gate** birlikte verilmiştir.

**VM-local atomic rollback (Adım 1-4)**:

1. **VM shutdown** (CLI veya GUI):
   ```bash
   prlctl stop HALILKOOLUB735
   ```
2. **Snapshot restore** (VM-local atomic; AD object backend'de orphan kalır, bkz Adım 5):
   ```
   Parallels GUI: HALILKOOLUB735 → Snapshots → pre-domain-join-A1-baseline-2026-05-25 → Switch To
   ```
   veya CLI:
   ```bash
   prlctl snapshot-switch HALILKOOLUB735 --id <snapshot-uuid-from-list>
   ```
3. **VM start** — pre-domain-join state geri yüklenir (workgroup + PartOfDomain=false + agent original WORKGROUP enrollment)
4. **Post-restore VM verify**:
   ```powershell
   (Get-WmiObject Win32_ComputerSystem).PartOfDomain   # False bekleniyor
   Get-WmiObject Win32_ComputerSystem | Select-Object Workgroup, Domain   # Workgroup adı geri
   Get-Service EndpointAgent                              # Running state korunmuş
   ```

**AD post-rollback gate (Adım 5 — zorunlu)**:

5. **AD computer object cleanup** (snapshot otomatik çözmez — operator + AD admin coordination):
   - **a)** AD object DN/SAM capture (rollback öncesi pre-join state'i kaydedildiyse atla; aksi halde AD admin'den `Get-ADComputer HALILKOOLUB735 -Properties *` ile DN + SAM + LastLogon + OU path al)
   - **b)** OU path identify (`OU=EndpointPilot,DC=acik,DC=local` veya operator domain join sırasında verdiği OU)
   - **c)** Owner kararı + execute (AD admin tarafından sıralı tercih):
     - **delete** (default — orphan temizlik): `Remove-ADComputer HALILKOOLUB735 -Confirm:$false`
     - **disable** (forensic retain — AD audit için stale object): `Disable-ADAccount -Identity HALILKOOLUB735$`
     - **reset** (re-join için preserve): `Reset-ComputerMachinePassword -Server <DC>` (rare; sadece tekrar join planı varsa)
   - **d)** Post-cleanup verify:
     ```powershell
     # AD admin Mac/Windows admin workstation üzerinde (VM içinde değil — VM workgroup'ta)
     # Ana kanıt: computer object durumu
     Get-ADComputer HALILKOOLUB735 -ErrorAction SilentlyContinue   # delete sonrası NULL; disable sonrası Enabled=False
     # Yan kanıt: DC reachability sanity (DC listesini verir; computer object yokluğunu KANITLAMAZ)
     nltest /dclist:acik.local                                       # DC inventory — domain hâlâ erişilebilir
     ```
   - **e)** Backend `endpoint_devices` stale device decision:
     - **decommission** (default — clean state): admin REST `DELETE /api/v1/endpoint-admin/devices/<device-id>`
     - **keep for forensic** (rare — audit retention için): backend `is_active=false` flag (bkz BE-019 retention policy)

**Süre toplam**: 1dk VM operations + 5dk AD coordination = **~6dk** (snapshot restore atomic kısmı 1dk ama AD cleanup operator+admin koordinasyon süresi sebebiyle ana iş 5dk).

#### 15.4.3 vs `Remove-Computer` (legacy §15.1 path) — 11-property karşılaştırma

| Property | Snapshot restore (§15.4) | `Remove-Computer` (§15.1) |
|---|---|---|
| VM-local atomic | ✅ tek operasyon | ❌ unjoin + restart + AD cleanup ayrı |
| **AD object cleanup** | ❌ **VM state restored, AD object cleanup still required** (bkz §15.4.2 Adım 5) | ❌ operator manual ya da AD admin cleanup; unutma riski (orphan object) |
| Süre | ~6dk (1dk VM + 5dk AD coordination) | ~5-10dk (unjoin + restart + AD cleanup) |
| Credential (VM kısmı) | ❌ gerek yok | ✅ domain admin credential interactive (`Get-Credential`) |
| Credential (AD kısmı) | ✅ AD admin (cleanup için) | ✅ AD admin (orphan cleanup için) |
| Disk delta | +1-3GB snapshot (silinene kadar; Windows update + domain join sonrası büyür) | 0 (sadece state değişimi) |
| Rollback reversibility | ✅ snapshot silinene kadar her zaman geri dönülebilir | ❌ unjoin tek yön; tekrar join interactive credential gerek |
| **AD/GPO/cached credential drift** | ✅ snapshot rollback (cached cred clean) | ⚠️ `Remove-Computer` AD cred remove eder ama cached GPO/policy residue VM'de kalabilir; `gpupdate /force` + cached profile cleanup ayrı |
| **Dynamic RPC / SMB / DC firewall failure mode** | ⚠️ snapshot pre-join state — dynamic RPC port range (49152-65535) ve SMB 445 firewall config rollback öncesi state kaybolur | ⚠️ aynı drift; VM içi firewall rules domain context'te değişmiş olabilir |
| **Backend `endpoint_devices` enrollment drift** | ⚠️ device ID korunur ama post-rollback host re-context (workgroup) — backend admin REST stale device decommission gate gerek (bkz §15.4.2 Adım 5e) | ⚠️ aynı drift; backend device record `Remove-Computer` ile otomatik silinmez |
| **Operator auditability** | ✅ snapshot UUID + timestamp + name (Parallels metadata) | ⚠️ OS event log + AD security log + backend audit log (3 kaynak dağınık) |

**Recommendation**: Strateji B kapsamında **snapshot rollback default** (VM-local atomic + cached cred clean + operator auditable), **AD cleanup ayrı zorunlu gate** (§15.4.2 Adım 5). `Remove-Computer` yedek path (disaster — örn. snapshot corrupt, disk failure, VM tamir gereği).

**Anahtar mit düzeltmesi (Codex iter-1 BLOCKER)**: "Snapshot restore = AD cleanup'sız çözüm" YANLIŞ; snapshot restore VM kısmını atomically döndürür ama AD'deki computer object'i temizlemez. Her iki path da AD admin coordination gerektirir; snapshot'ın gerçek avantajı **VM-local cached state cleanliness + atomic timing** üzerine.

#### 15.4.4 Snapshot lifecycle policy (disk pressure vs retention trade-off)

**Default lifecycle**:
- Pre-domain-join snapshot tutulma süresi: **acceptance smoke + 72h soak + evidence PR merge** bitene kadar zorunlu (rollback window açık)
- Bitince **operator opt-in** silme (default): snapshot delete + disk reclaim
- Maksimum cap: **7 gün** (acceptance smoke + soak + evidence + buffer); ötesi operator explicit extension kararı + rationale

**Disk pressure izleme**:
- Snapshot delta `+1-3GB` Windows update / domain join / agent reinstall sonrası büyür (öncesinde küçük, sonrasında büyük); `prlctl snapshot-list HALILKOOLUB735` ile delta size monitor
- Mac host disk free threshold: snapshot delta + Windows update headroom + Mac dev work için minimum **10GB free** önerilir
- Disk pressure varsa **operator explicit opt-in ile erken silme** (default 7 gün yerine acceptance smoke+72h soak bitince hemen)
- Alternatif: snapshot export + Mac host external storage (USB SSD / NAS) → snapshot Mac'ten silinir ama backup external'da → disk-sparse + recovery slow path

**Snapshot rollback kullanılırsa evidence chain**:
- "Strateji B rollback" note: rationale + closure timestamp + snapshot UUID kanıt
- Post-rollback VM state + AD cleanup gate evidence (snapshot restore tek başına rollback evidence değil; AD cleanup + backend stale device action complete kanıt gerek)
- `docs/faz-22-evidence/YYYY-MM-DD-strategy-b-rollback-<reason>.md` (6-bölüm format §14.2)

**Snapshot silme komutu**:
```bash
# UUID list
prlctl snapshot-list HALILKOOLUB735
# Silme
prlctl snapshot-delete HALILKOOLUB735 --id <snapshot-uuid>
# Verify
prlctl snapshot-list HALILKOOLUB735   # UUID listede olmamalı
```

**Snapshot vs disk full failure mode**:
- Snapshot delta disk dolduğunda Parallels otomatik snapshot create reddedebilir veya VM I/O degraded olur
- Mitigation: snapshot lifecycle policy disciplined uygula; disk free threshold automated monitor (gelecek `docs/operations/parallels-host-monitor.md` runbook kapsamı)

---

## 16. Risk register

| Risk | Severity | Mitigation | Owner |
|---|:---:|---|---|
| Real device'de destructive command yanlışlıkla queue edilir | **HIGH** | Non-destructive only allowlist §10.1; BE-017 dual-control fixture-only proof; admin-creatable-types env config (PR #1028) | Agent + Backend |
| Self-hosted CI runner false-green verir | Medium | labels + concurrency + VM identity + secret scan + artifact SHA verify | Agent CI |
| Identity classification (A3/A4) yanlış sınıflanır | Medium | AG-021/022 tests + raw sanitized evidence + operator manual review | Agent (TRACKING) |
| BYOD A2 consent/privacy/KVKK eksikliği | **HIGH** | explicit consent ID + uninstall self-service test + data inventory + BE-019 enforcement | DPO + Legal + Operator |
| Unsigned binary yanlış rollout sinyali (A2/A3/A4) | **HIGH** | A1 lab-only time-boxed SHA-pinned exception; A2-A4 signed mandatory | SEC + Operator |
| Soak observation laptop sleep/network gap | Medium | declared sleep/reboot windows tagged separately; offline >30m flag | Operator |
| KVKK retention enforcement yok (BE-019 backlog) | **HIGH** | A2 BYOD acceptance BE-019 unlock gate; A1 standalone meşru menfaat zemini geçici | Backend (BE-019) |
| Cross-AI provider-level review atlanır | Medium | runbook §17 audit trail HARD requirement; PR cross-ai-audit CI gate | Agent automation |
| BYOD uninstall self-service fail | Medium | installer uninstall.ps1 test + Add/Remove Programs verify + PowerShell fallback | Operator + agent script |
| EDR allowlist gap (A2-A4) | Medium | SOC pre-coordination + SHA pin + service/path allowlist + ticket reference in evidence | SOC + Operator |
| Backend device decommission incomplete | Low | admin REST `DELETE` workflow + audit row insert + KVKK purge per BE-019 | Backend |
| Mobile (iOS/Android) scope creep | Low | runbook §1.2 explicit out-of-scope + ADR amendment scope cap | Agent docs |
| **AD computer object orphan after snapshot restore (Strategy B)** | **Medium** | §15.4.2 Adım 5 AD post-rollback gate zorunlu: DN/SAM capture + OU identify + delete/disable/reset owner kararı + post-cleanup `Get-ADComputer` verify; backend `endpoint_devices` stale device decommission gate | Operator + AD admin + Backend |
| **Disk pressure vs snapshot retention trade-off (Strategy B)** | Low | §15.4.4 lifecycle policy: default 7 gün cap + operator opt-in extension; snapshot delta size monitor (`prlctl snapshot-list`); Mac host 10GB free threshold; alternatif snapshot export + external storage | Operator |
| **A1 baseline state loss / historical-only evidence (Strategy B)** | Low | PR #1021 historical mark + new evidence doc'ta açık note; rollback recovery snapshot ile mümkün ama snapshot silindikten sonra fresh workgroup VM gerek (disk constraint dep) | Agent docs + Operator |

---

## 17. Audit trail and cross-AI review

### 17.1 Cross-AI provider-level (HARD RULE)

- Implementer AI: Claude (Anthropic)
- Reviewer AI: Codex (OpenAI)
- Codex strategic thread (this runbook): `019e5b17-4086-7fc3-b82b-5303be3948fe` REVISE iter-1 with `ready_for_impl=true` for docs-only standalone runbook implementation
- Codex post-impl thread (this PR): pending

Every pilot evidence PR carries Cross-AI review chain (Implementer ≠ Reviewer provider-level).

### 17.2 Boundary declaration (ADR-0011 §2.3)

PR-level boundary template her pilot evidence PR'da:

```
- [ ] credential-read
- [ ] credential-write (test persona only; rotate post-smoke per BE-017 pattern)
- [ ] state-mutation (test cluster)  ← if backend mutation (enrollment token, command, audit row)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication (A2 BYOD consent flow only)
- [x] none of the above  ← if docs-only evidence (no cluster mutation)
```

### 17.3 Hard rule references

- ADR-0011 governance layer pattern (DD-EA + BG-EA)
- ADR-0012-EA "22.2 scope amendment" section (scope realignment kanonik karar)
- HARD RULE — Cross-AI Peer Review (2026-05-05 + 2026-05-14)
- HARD RULE — Kullanıcı Aktif Credential'ına Dokunma (2026-04-29)
- HARD RULE — Continuous Autonomous Mode (2026-04-25)
- HARD RULE — No Closure Language (2026-04-19)
- HARD RULE — No Fake Work (2026-04-25)
- HARD RULE — Pre-Production Full Authority (2026-04-29)

### 17.4 Pilot evidence audit trail

Per pilot evidence PR:
1. Implementer Claude evidence doc + smoke + DB query + cleanup record
2. Codex post-impl review (read-only sandbox; PR diff + branch HEAD + boundary verify)
3. AGREE/PARTIAL/REVISE/RED verdict + ready_for_merge: true/false + audit note for squash mesajı
4. Iter absorb chain (REVISE → AGREE) per PR
5. Squash merge with Codex audit note
6. Post-merge cleanup (archive tag + branch delete + audit log)

---

## 18. Sıradaki adımlar (post-runbook merge)

### 18.1 #1044 operator evidence pack

`scripts/faz22-non-domain/a1-operator-evidence-pack.py` #1044 A1
multi-device acceptance zinciri için manifest tabanlı üst wrapper'dır. Default
modu dry-run'dır: secret/JWT/token kabul etmez, backend command dispatch etmez,
hesap veya cluster state mutate etmez. Çıktı olarak:

- `operator-checklist.md`
- `run-evidence-pack.sh`
- `manifest.normalized.json`

üretir. Script, iki ek cihaz hazır olduğunda aynı manifest üzerinden
diagnostics → per-device evidence doc → SELECT-only soak rollup → pilot-wide
rollup doc sıralamasını tek plana bağlar.

Starter manifest:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --write-example-manifest /tmp/faz22-a1-devices.json
```

Review-only pack:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --manifest /tmp/faz22-a1-devices.json \
  --output-dir /tmp/faz22-a1-operator-pack \
  --include-winget-egress
```

Observation window sonrası gerçek soak output ile rollup draft üretimi:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/faz22-non-domain/a1-operator-evidence-pack.py \
  --manifest /tmp/faz22-a1-devices.json \
  --output-dir /tmp/faz22-a1-operator-pack-final \
  --soak-output /tmp/faz22-a1-soak-rollup.txt \
  --generate-rollup-doc
```

Boundary: Bu wrapper #1044'ü PASS yapmaz; yalnız kanıt üretim sırasını
standardize eder. `PENDING` deviceId bulunan manifest ile final rollup kabulü
yapılamaz; iki ek cihaz backend device UUID aldıktan sonra manifest tekrar
çalıştırılır.

### 18.2 #1044 final acceptance verifier

`scripts/faz22-non-domain/a1-acceptance-verifier.py` final A1 rollup
dokümanını §14.4/§14.5 kurallarına göre fail-closed denetler. Bu verifier:

- `Status: PASS`, `Tracked by: #1044`, `Tier: A1` metadata'sını arar
- minimum 3 cihaz ve her cihaz `PASS` ister
- soak window süresinin en az 24h olduğunu doğrular
- heartbeat ≥99%, terminal/accounted 100%, command success ≥95%, gap 0 ve
  repeatability PASS ister
- rollup içinde `PENDING`, `REVIEW`, `PARTIAL`, `FAIL` marker'ı kalırsa fail
  verir
- per-device evidence doc linklerinin dosyada varlığını kontrol eder

Mevcut partial rollup'ın fail vermesi beklenen davranıştır:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/faz22-non-domain/a1-acceptance-verifier.py \
  --rollup-doc docs/faz-22-evidence/2026-06-07-non-domain-pilot-tierA1-rollup-current.md
```

Final #1044 evidence PR öncesi beklenen pass komutu:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/faz22-non-domain/a1-acceptance-verifier.py \
  --rollup-doc docs/faz-22-evidence/YYYY-MM-DD-non-domain-pilot-tierA1-rollup.md
```

Boundary: Verifier backend'e bağlanmaz, SQL çalıştırmaz, command dispatch etmez
ve issue status mutate etmez. Sadece mevcut Markdown evidence dosyasını okur.

### 18.3 Carry-over list

1. **CI script extension**: `scripts/test/parallels-windows11-ci.sh` non-domain classification precheck genişletmesi (Codex Q8 + §8.2 önerisi) — ayrı PR
2. **Yeni board issue**: "Faz 22.2.A non-domain pilot — A1 multi-VM repeatability" (mevcut HALILKOOLUB735 + 2 yeni Parallels VM evidence; 24h soak)
3. **TRACKING-ROADMAP backlog unlock**: ~~AG-021 (identity inventory) + AG-022 (logged-in identity)~~ ✅ source-foundation MERGED 2026-05-26 (platform-agent #17 `91ef533d`); kalan field-acceptance pendingler — AG-021/022 multi-device classification evidence + CI script alignment (`scripts/test/parallels-windows11-ci.sh` agent-native `diagnose identity` çağrısı) + **BE-015** (admin identity compliance API) + **AG-024** (signed manifest / Authenticode) + **BE-019** (KVKK retention enforce) priority bump
4. **A2 BYOD prerequisite docs**: `docs/22-2-byod-consent-template.md` (Turkish + English) + `docs/22-2-kvkk-data-inventory.md` (DPO sign-off için)
5. **Signed distribution pre-req docs**: ADR-0012-EA "22.2 pre-req docs" listesi (7 item) `docs/22-2-trusted-signing-onboarding.md` follow-up
6. **22.2.A pilot kabul evidence chain**: gate matrix §13 her item için ayrı evidence PR
