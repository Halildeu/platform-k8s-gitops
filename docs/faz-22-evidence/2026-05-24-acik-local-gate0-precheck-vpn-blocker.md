# Faz 22.2 IT pilot `acik.local` — Gate 0 precheck VPN routing BLOCKER (2026-05-24)

> **Issue**: [gitops #1037](https://github.com/Halildeu/platform-k8s-gitops/issues/1037) — Faz 22.2 IT pilot acik.local HALILKOOLUB735 Gate 0 VPN routing BLOCKER + agent-actionable hazırlık.
> **Predecessor manual smoke**: gitops PR #1021 (`4ecb71dc`) + platform-agent PR #10 (`402bdc1`) — BE-011 + AG-013 WORKGROUP smoke MERGED 2026-05-24.
> **Predecessor lab gate**: gitops PR #1034 + platform-agent PR #13 — Parallels W11 CI rehearsal lab gate altyapısı MERGED 2026-05-24.
> **Codex strategic thread**: `019e5aca-edd8-7753-89aa-3f347bd6b9f7` — VERDICT REVISE / `ready_for_impl: false` for full pilot (DC reachability fail); `ready_for_impl: true` for non-destructive Gate 0 precheck + agent-actionable hazırlık scope.

---

## 1. Amaç ve boundary

Faz 22.2 IT pilot `acik.local` domain join attempt için Gate 0 (non-destructive precheck) — DC/DNS/Kerberos/LDAP/SMB reachability **fail evidence** kayıt altına alınır + sıradaki operator action chain (Mac VPN connect + Parallels routing + DNS config) playbook'a bağlanır.

**Boundary — HARD constraints**:
- **Single VM IT pilot attempt** — HALILKOOLUB735 only; **NOT** domain-wide rollout-ready, **NOT** prod-ready, **NOT** password-reset-ready
- **No destructive command** — LOCK_USER_LOGIN / DISABLE_LOCAL_USER / password reset / user disable-enable YASAK
- **Domain admin credential** kullanıcı interaktif girer; script/evidence/log/transcript **YOK**
- **HARD RULE — Kullanıcı Aktif Credential'ına Dokunma**: local `halilkocoglu` user kaybolmaz; domain join sonrası login user değişebilir (domain user ayrı profil)
- **No browser/UI flow** — CLI-level Gate 0 precheck
- **Test cluster only** (`testai.acik.com`); prod cluster bu pilot kapsamı dışı

---

## 2. Parallels VM baseline (HALILKOOLUB735)

| Alan | Değer |
|---|---|
| VM Name (Parallels) | `Windows 11` |
| Hostname | `HALILKOOLUB735` |
| Current Domain | `WORKGROUP` (PartOfDomain=false) |
| Local User | `halilkocoglu` (HARD RULE protected) |
| VM IP | `10.211.55.3` (Parallels NAT subnet `10.211.55.0/24`) |
| VM DNS Server | `10.211.55.1` (Parallels NAT gateway → upstream Mac host DNS) |
| Network Mode | NAT (Parallels default) |
| testai.acik.com:443 | ✅ Reachable → `212.115.26.190` (public IP — internet routing OK) |
| OS | Windows 11 (build verify post-VPN reproducer) |

---

## 3. Gate 0 precheck snapshot (2026-05-24, NAT mode + no VPN)

### 3.1 DNS resolution

```powershell
Resolve-DnsName -Name acik.local -ErrorAction SilentlyContinue
# Result: EMPTY (DNS query returns no records)

Resolve-DnsName -Name "_ldap._tcp.dc._msdcs.acik.local" -Type SRV -ErrorAction SilentlyContinue
# Result: EMPTY (DC SRV records not resolved)
```

### 3.2 DC locator

```
nltest /dsgetdc:acik.local
# Result: Getting DC name failed: Status = 1355 0x54b ERROR_NO_SUCH_DOMAIN
```

### 3.3 Reachability summary

- `acik.local` ad çözümleme: **FAIL** (VM DNS resolver `10.211.55.1` → Mac upstream DNS → public DNS, private `acik.local` records yok)
- DC SRV record discovery: **FAIL** (`_ldap._tcp.dc._msdcs.acik.local`, `_kerberos._tcp.acik.local` resolve edilmiyor)
- DC locator: **FAIL** (`ERROR_NO_SUCH_DOMAIN`)
- Port reachability (53/88/135/389/445/464/636/3268): **NA** (DC IP bilinmediği için test edilemiyor)
- testai.acik.com:443: ✅ PASS (public cluster reachable, internet path normal)

---

## 4. Diagnosis

**Tanı**: `testai.acik.com` (public cluster hostname, public DNS) çözülüyor; `acik.local` (private AD domain, internal DNS) DC reachable değil.

**Sebep**: DC corp **VPN/intranet** arkasında, Mac host VPN bağlı değil (kullanıcı doğrulaması 2026-05-24). Parallels VM NAT mode'unda Mac host'un DNS resolver'ına bağımlı; Mac VPN'siz iken corp internal records (e.g. `acik.local`) görünmüyor.

**Codex strategic verdict** (`019e5aca` Q1): "Önce non-destructive precheck koşulsuz yapılmalı. Doğrudan domain join yapmayın." — bu evidence onun doğrulamasıdır. Reachability fail durumunda join'e geçmek gereksiz reboot + login user değişim + AD object kirletme riski üretir.

---

## 5. Operator action plan (Gate 0 unblock)

Aşağıdaki sıralı playbook'u **kullanıcı/operator** infaz eder; agent helper script post-VPN reproducer için hazır (`scripts/test/parallels-acik-local-precheck.sh` — platform-agent repo). Detay runbook: `docs/runbooks/RB-faz22-acik-local-vpn-routing-setup.md`.

1. **Mac VPN client connect** — corp VPN credentials ile (Cisco AnyConnect / OpenVPN / WireGuard / Tailscale / vb. — operator tarafı; agent credential dokunmaz)
2. **Mac side verification** — `dig acik.local @<corp-dns-ip>` Mac terminal'de — corp DNS'in `acik.local` çözebildiğini doğrula
3. **Parallels VM network mode review** (3 alternatif):
   - **Option A (önerilen)**: Parallels `Bridged` mode — VM physical Ethernet ile aynı subnet IP alır; Mac VPN routing pass-through olabilir
   - **Option B**: Parallels NAT mode + custom routing — Mac VPN'i NAT gateway üzerinden VM'e forward (kompleks routing)
   - **Option C**: VM içinden VPN client — Windows-side VPN connect (kullanıcı VPN credentials VM içine geçirmesi gerek; complexity)
4. **VM DNS config** — `Set-DnsClientServerAddress -InterfaceAlias Ethernet -ServerAddresses <corp-dns-ip>` (DC IP veya corp internal DNS server)
5. **Gate 0 precheck reproducer** — `scripts/test/parallels-acik-local-precheck.sh` (helper) → DNS resolve + DC SRV + nltest + Test-NetConnection ports + dsregcmd; PASS ise pilot smoke phase başlar
6. **Cleanup** — Eğer Bridged mode geçici idiyse VM Settings → Network → NAT'a geri çevir (post-pilot rollback)

---

## 6. Helper script reference

**platform-agent** `scripts/test/parallels-acik-local-precheck.sh` (Codex `019e5aca` Q2 önerisi):

```bash
# Post-VPN precheck reproducer (non-destructive, no credentials, sanitized output)
$ export EVIDENCE_DIR=./tmp/acik-local-precheck-$(date +%s)
$ bash scripts/test/parallels-acik-local-precheck.sh
```

Script probe matrix (Codex önerisi):
- `Get-CimInstance Win32_ComputerSystem` (DNSHostName / Domain / PartOfDomain / Workgroup)
- `dsregcmd /status` (Azure AD / Workplace Join / Domain Join state)
- `Resolve-DnsName acik.local` + SRV records (`_ldap._tcp.dc._msdcs.acik.local`, `_kerberos._tcp.acik.local`)
- `nltest /dsgetdc:acik.local`
- `Test-NetConnection -ComputerName <DC> -Port {53,88,135,389,445,464,636,9389}`
- `Test-NetConnection testai.acik.com -Port 443` (baseline)
- `w32tm /query /status` (time sync — Kerberos için kritik)
- Reachability summary (allow/deny per port)

**Sanitization**: stream `redact` filtresi (Bearer/Authorization/password/token/secret/JWT) + post-write secret scan fail-closed (helper script PR'da detay).

---

## 7. D29-EA matrix (pre-Gate 0 — NA durumunda)

| Layer | Status | Note |
|---|---|---|
| **Up** | NA (pre-Gate 0) | VM up + WORKGROUP runtime; agent pre-install state |
| **Functional** | NA (pre-Gate 0) | Backend `testai.acik.com:443` reachable ama domain context'siz; pilot smoke (BE-011 lifecycle) post-VPN sonrası |
| **Secured** | NA (pre-Gate 0) | OpenFGA test cluster (test persona JWT) hazır; domain user federation **NOT first pilot** (Codex Q3) |
| **Zanzibar-ready** | NA (pre-Gate 0) | OpenFGA store + model + tuple seed test cluster context, pilot AD-federation kanıtı değil |

**Tam D29-EA değerlendirmesi**: post-Gate 0 pilot smoke evidence doc'unda (ayrı PR, gerçek run sonrası — Codex önerisi: placeholder PR değil).

---

## 8. Pending / out-of-scope

- **Mac VPN connect + Parallels routing** — operator-bound (kullanıcı; bu evidence doc scope dışı)
- **EndpointPilot OU placement** — operator-bound (domain ops; DC tarafında `New-ADOrganizationalUnit OU=EndpointPilot,DC=acik,DC=local` veya ADUC GUI)
- **EDR allowlist** — operator-bound (SOC tarafında; `endpoint-enes-agent.exe` SHA256 + service display name + install path + network destination)
- **Trusted signing** — operator-bound (AG-018/AG-024 ext; mevcut agent build unsigned; single-VM unsigned exception **rollout-ready sinyali değil**)
- **AD federation** — Codex Q3 önerisi: NOT first pilot; mevcut test persona JWT + agent device credential path; AD federation ayrı sub-faz (Keycloak LDAP federation + UPN mapper + numeric userId backfill + role/group mapping + OpenFGA tuple seed + browser/JWT acceptance)
- **Domain join + agent install + pilot smoke** — post-Gate 0 (operator unblock → agent infaz)
- **BE-017 `LOCK_USER_LOGIN` admin-creatable test overlay risk** — Codex `019e5aca` Q4: real VM için command scope `COLLECT_INVENTORY` only daraltma veya evidence/audit'te açık gate (mevcut test overlay PR #1028 ile LOCK_USER_LOGIN enabled; real domain VM bağlandığında dikkat)

---

## 9. Cross-AI peer review

- **Implementer AI**: Claude (Anthropic)
- **Reviewer AI**: Codex (OpenAI)
- **Codex strategic thread**: `019e5aca-edd8-7753-89aa-3f347bd6b9f7` — VERDICT REVISE / `ready_for_impl: false` for full pilot, `ready_for_impl: true` for Gate 0 precheck + agent-actionable hazırlık scope; 3 revision items:
  1. Önce non-destructive precheck koşulsuz (THIS evidence)
  2. AD federation NOT first pilot (mevcut test persona JWT + device credential path)
  3. Test overlay BE-017 `LOCK_USER_LOGIN` admin-creatable risk — real VM scope dar (`COLLECT_INVENTORY` only) veya evidence açık gate

### 9.1 Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above

Docs-only evidence + runbook PR; no cluster mutation, no source code, no destructive real PC action, no agent dispatch. Underlying precheck operation = read-only DNS/port probe (PowerShell `Get-CimInstance`/`Resolve-DnsName`/`nltest`/`Test-NetConnection`/`dsregcmd /status`); no credential exposure.

---

## 10. Tracked by

- gitops #1037 (this issue — Gate 0 BLOCKER + agent-actionable hazırlık)
- platform-agent #12 (Parallels W11 CI pilot rehearsal lab gate — WORKGROUP separate scope, Status=Needs Verify operator self-hosted runner waiting)
- gitops `#1015` (Faz 22.2 IT pilot readiness umbrella — parent)
- gitops PR #1034 (`RB-faz22-endpoint-pilot-it-owned.md` §2 lab gate + §3-§10 pilot prep)
- gitops PR #1021 (`4ecb71dc`) — BE-011 + AG-013 WORKGROUP smoke MERGED
- gitops PR #1032 (`507f57c4`) — BE-017 dual-control test cluster fixture MERGED
- gitops PR #1028 (`6a0630bd`) — test overlay LOCK_USER_LOGIN admin-creatable (BE-017 Gate 0 preflight)
- platform-agent PR #10 (`402bdc1`) — AG-013 Verified 2026-05-24 MERGED
- platform-agent PR #13 (`ab1eb0ee`) — Parallels W11 CI lab gate script + workflow MERGED
- Codex strategic thread `019e5aca-edd8-7753-89aa-3f347bd6b9f7`
- gitops handoff `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 P1 operator queue Faz 22.2 IT pilot

---

## 11. Audit note (squash mesajı için)

```
Codex strategic AGREE for Gate 0 scope: HALILKOOLUB735 VM WORKGROUP/
PartOfDomain=false baseline captured; acik.local DNS/DC SRV/nltest fail
(ERROR_NO_SUCH_DOMAIN) documented; testai.acik.com:443 public path
reachable; DC corp VPN/intranet behind; operator unblock chain (Mac VPN
+ Parallels routing + DNS config) ayrı runbook + post-VPN agent helper
script reproducer; full pilot (domain join + agent install + smoke)
post-Gate 0 unblock + ayrı evidence PR; no destructive real PC action,
no credential logging, single-VM scope only, NOT acik.local IT pilot
acceptance, NOT prod-ready, NOT domain-wide rollout-ready.
```
