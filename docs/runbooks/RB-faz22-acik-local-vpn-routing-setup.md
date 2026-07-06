# RB Faz 22.2 IT pilot `acik.local` — VPN routing setup operator playbook

> **Status**: PILOT PREP (operator playbook — agent-actionable hazırlık; operator infaz gerekli)
> **Tracked by**: [gitops #1037](https://github.com/Halildeu/platform-k8s-gitops/issues/1037) — Faz 22.2 IT pilot acik.local HALILKOOLUB735 Gate 0 VPN routing BLOCKER
> **Scope sınırı**: Parallels Windows 11 VM `HALILKOOLUB735` `acik.local` DC reachability setup. Bu runbook **Gate 0 unblock** dokümanıdır; prod-ready / password-reset-ready / domain-wide rollout-ready iddiası taşımaz.
> **Predecessor evidence**: `docs/faz-22-evidence/2026-05-24-acik-local-gate0-precheck-vpn-blocker.md`

---

## 1. Amaç

Faz 22.2 IT pilot için kullanıcının Parallels Windows 11 VM'inin (`HALILKOOLUB735`, WORKGROUP, PartOfDomain=false) `acik.local` domain controller'a routing'ini açmak. Mevcut Gate 0 precheck (2026-05-24) DC reachable değil tespit etti (`ERROR_NO_SUCH_DOMAIN` 1355 0x54b); DC corp VPN/intranet arkasında, Mac host VPN bağlı değil.

Bu runbook **kullanıcı/operator** tarafı playbook'tur:
- Mac VPN client identification + connect
- Parallels VM network mode setup (NAT vs Bridged trade-off)
- VM DNS config (Set-DnsClientServerAddress)
- Helper script precheck reproducer

Agent tarafı bu runbook'un çalışmasını **otomasyon kapsamı dışı** sayar — VPN client credentials + corp DNS IP + DC FQDN operator-bound.

---

## 2. VPN client identification + connect (operator)

### 2.1 VPN client tipi belirle

Kuruluş VPN tipi (operator bilgisi):
- **Cisco AnyConnect** — Mac App Store / Cisco resmi installer
- **OpenVPN Connect** — `brew install --cask openvpn-connect`
- **WireGuard** — `brew install --cask wireguard-tools` + macOS App Store WireGuard.app
- **Tailscale** — `brew install --cask tailscale`
- **Pulse Secure / Ivanti Connect Secure** — corp installer
- **Native macOS VPN** (L2TP/IPsec/IKEv2) — System Settings → Network → VPN

### 2.2 VPN connect

Operator VPN client'i açar + credentials girer + connect. **HARD RULE — Kullanıcı Aktif Credential'ına Dokunma**: agent VPN credentials'a dokunmaz; operator manual.

### 2.3 Mac side verification

```bash
# Mac terminal'de (VPN connected sonrası):

# 1. Corp DNS resolve
dig acik.local @<corp-dns-ip>
# Expected: A record(s) returned

# 2. DC SRV records
dig SRV _ldap._tcp.dc._msdcs.acik.local @<corp-dns-ip>
# Expected: SRV records returned (DC FQDN + port)

# 3. DC ping (eğer ICMP allow ise)
ping <dc-fqdn-or-ip>
# Expected: ICMP reply

# 4. Route to DC
traceroute <dc-fqdn-or-ip>
# Expected: VPN tunnel hop görünür (utun0 / ipsec0 / vb.)
```

Eğer 1-2 fail ise: Mac VPN DNS config eksik; VPN client settings'inde "Use DNS from VPN" enable et veya manuel olarak Mac'e corp DNS ekle (System Settings → Network → Wi-Fi/Ethernet → Advanced → DNS).

---

## 3. Parallels VM network mode karar ağacı

> **Codex iter-2 MEDIUM 3 absorb** (2026-05-24): Bridged'i default önerilen yapmak yanıltıcı olabilir — çoğu kurumsal VPN istemcisi (Cisco AnyConnect, Pulse Secure, vb.) host'tan tunnel açar ve bridged VM otomatik olarak VPN tunnel'a dahil olmaz; VM fiziksel LAN'da ayrı cihaz gibi kalır. Bu durumda NAT'tan vazgeçilip daha kötü bir yola düşülebilir. Aşağıdaki karar ağacını sırayla uygula.

### 3.1 Karar ağacı (önce daha az invaziv yol)

**Adım 1 — Mac VPN connected + Parallels Shared (NAT) + VM corp DNS** (önce dene):

1. Mac VPN client aktif (§2.2)
2. Parallels VM network mode **NAT** kalır (mevcut `Shared Network`)
3. VM içinde DNS server'ı corp DNS IP'sine çevir (§4 `Set-DnsClientServerAddress`)
4. Helper script çalıştır (§5) → DNS resolve test
5. **PASS** → §7 pass criteria + pilot smoke; **FAIL** → Adım 2'ye geç

Bu yol bazı VPN client'larında çalışır (e.g. Tailscale subnet routing + Magic DNS, OpenVPN `--dhcp-option DNS`, native macOS L2TP/IPsec). Mac host VPN DNS resolver'ı yapıyorsa ve Parallels NAT gateway forward ediyorsa Adım 1 yeterli.

**Adım 2 — VPN istemcisinin VM/NAT forwarding politikasını kontrol et**:

- Cisco AnyConnect: "Tunnel All DNS over Tunnel" enable veya per-domain `acik.local` allow
- OpenVPN: `--dhcp-option DOMAIN acik.local` + `--dhcp-option DNS <corp-dns>` directive
- Pulse Secure: Split DNS policy → `acik.local` corp DNS
- WireGuard: `AllowedIPs` + `DNS` directive
- Tailscale: `MagicDNS` + tag-based ACL

Bu config VPN tarafı (operator/IT admin); agent dokunmaz. Sonra Adım 1'i tekrar dene.

**Adım 3 — Parallels Bridged mode (yalnız VPN/LAN politikası destekliyorsa)**:

> ⚠️ **Bridged sadece VPN istemcisi bridged interface'i tunnel'a dahil ediyorsa anlamlı.** Çoğu kurumsal VPN'de bu **otomatik değil**. Bridged'e geçmeden önce operator/IT'ten "bridged VM VPN tunnel kullanabilir mi?" yanıtı al.

Eğer VPN bridged'i destekliyorsa:

**Parallels Desktop GUI**:
1. VM → Configure → Hardware → Network → Source
2. "Shared Network" (NAT) → **"Bridged Network"** → Default Adapter
3. Apply + VM restart (network mode hot-swap güvenli değil)

veya **CLI** (`prlctl set`):
```bash
prlctl set "Windows 11" --device-set net0 --type bridged --iface en0
prlctl restart "Windows 11"
```

**Adım 4 — VM içinden VPN client** (son seçenek, credential-riskli):

VM içine VPN credentials geçir + Windows VPN client install. **HARD RULE — Kullanıcı Aktif Credential'ına Dokunma**: VPN credentials kullanıcı manual; agent dokunmaz. Bu seçeneği **sadece** Adım 1-3 hepsi fail ettiğinde + operator açık karar verirse uygula.

### 3.2 Post-config VM IP verify

```powershell
# VM içinde (yeni network config sonrası):
Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway } | `
  Select-Object InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer
```

- Adım 1 (NAT) sonrası: VM IP hâlâ `10.211.55.X`, DNS corp DNS IP
- Adım 3 (Bridged) sonrası: VM IP physical Ethernet subnet (corp `10.X.X.X` veya home `192.168.X.X`); default gateway corp/home router
- Adım 4 (VM-side VPN) sonrası: VM additional virtual adapter (utun/tap) + VPN-assigned IP

### 3.3 Bridged command reference (yalnız Adım 3 sonrası — VPN/LAN politikası onayladıysa)

> Bu komut bloğu **bağımsız bir yol değildir**; sadece §3.1 karar ağacında Adım 3'e ulaşıldıysa (VPN istemcisi bridged VM'i tunnel'a dahil ediyorsa + operator/IT açık onayı varsa) referans olarak kullan.

**Parallels Desktop GUI**:
1. VM → Configure → Hardware → Network → Source
2. "Shared Network" (NAT) → **"Bridged Network"** → Default Adapter
3. Apply + VM restart (hot-swap güvenli değil)

veya **CLI** (`prlctl set`):
```bash
prlctl set "Windows 11" --device-set net0 --type bridged --iface en0
# en0 = default Ethernet; Wi-Fi için en1 (Mac config'e bağlı)

prlctl restart "Windows 11"
```

---

## 4. VM DNS config (corp DNS)

### 4.1 Set-DnsClientServerAddress

VPN tunnel Mac üzerinden geçtiği için VM'in corp DNS'i bilmesi gerek:

```powershell
# VM içinde (admin PowerShell):
$corpDns = "<corp-dns-ip>"  # operator tarafından sağlanan corp internal DNS IP
$alias = "Ethernet"          # adapter alias

Set-DnsClientServerAddress -InterfaceAlias $alias -ServerAddresses $corpDns

# Verify
Get-DnsClientServerAddress -InterfaceAlias $alias -AddressFamily IPv4
```

### 4.2 DNS resolve test

```powershell
Resolve-DnsName -Name acik.local -ErrorAction Continue
# Expected: A record(s) ile DC IP'leri

Resolve-DnsName -Name "_ldap._tcp.dc._msdcs.acik.local" -Type SRV -ErrorAction Continue
# Expected: SRV records (DC FQDN, port 389)
```

Eğer hâlâ fail: corp DNS yanlış IP, VPN tunnel DNS forwarding yok, veya firewall DNS port 53 block.

---

## 5. Helper script — Gate 0 precheck reproducer

### 5.1 Script lokasyonu

**platform-agent** repo:
- `scripts/test/parallels-acik-local-precheck.sh` (bash + prlctl exec)
- Codex strategic `019e5aca` Q2 önerisi pattern

### 5.2 Çalıştırma

```bash
# Mac terminal (platform-agent repo root):
cd ~/Documents/platform-agent
export EVIDENCE_DIR="./tmp/acik-local-precheck-$(date +%Y%m%d%H%M%S)"
bash scripts/test/parallels-acik-local-precheck.sh
```

### 5.3 Output

Script şu sırada probe yapar:
1. VM hostname / domain / PartOfDomain / current user
2. `dsregcmd /status` (join state)
3. `Resolve-DnsName acik.local` + SRV records
4. `nltest /dsgetdc:acik.local` (DC locator)
5. `Test-NetConnection` ports: 53, 88, 135, 389, 445, 464, 636, 9389 (DC FQDN'e karşı)
6. `Test-NetConnection testai.acik.com -Port 443` (baseline)
7. `w32tm /query /status` (time sync — Kerberos için kritik; <5 dakika clock skew gerek)
8. Reachability summary (allow/deny per port)

### 5.4 Exit code

- **0**: tüm probe'lar PASS — pilot smoke phase başlayabilir
- **non-zero**: bir veya daha fazla probe FAIL — troubleshoot table (§6) referans

### 5.5 Evidence

Script `$EVIDENCE_DIR/` altına:
- `precheck.txt` — tam probe output (sanitized; redact filter)
- `run.log` — adım adım log
- Post-write secret scan (`Bearer`/`Authorization`/`password`/`token`/JWT pattern fail-closed)

---

## 6. Troubleshoot table

| Failure | Sebep | Çözüm |
|---|---|---|
| `Resolve-DnsName acik.local` EMPTY | VM DNS server corp DNS değil; veya corp DNS reachable değil | §4.1 `Set-DnsClientServerAddress` + Mac VPN connected verify |
| `nltest /dsgetdc:acik.local` `ERROR_NO_SUCH_DOMAIN` | Domain controller reachable değil; DNS resolve fail veya DC down | §3 karar ağacı (önce Adım 1 NAT + corp DNS; sonra Adım 2 VPN policy; Bridged yalnız VPN/LAN destekliyorsa Adım 3) + §4 DNS config + Mac VPN active |
| `Test-NetConnection <DC> -Port 88` FAIL | Kerberos port block (firewall) | Corp firewall rule ekle (operator); veya VPN ACL'ında 88 izinli olduğunu verify |
| `Test-NetConnection <DC> -Port 389` FAIL | LDAP port block | Aynı (firewall ACL) |
| `w32tm /query /status` clock skew > 5 dk | Time sync fail (Kerberos için kritik) | `w32tm /resync /force`; corp NTP server config |
| Resolve OK ama join sırasında `0x569` (LDAP bind fail) | Domain admin credential yanlış / OU permission yok | Operator domain admin creds + OU permission verify |
| Resolve OK ama join sırasında `0x6BA` (RPC server unavailable) | Dynamic RPC port (49152-65535) block | Corp firewall RPC dynamic port range allowed verify |
| VM tarafında DNS değişimi sonrası corp resolve hâlâ fail | VM cache stale | `ipconfig /flushdns` + `Clear-DnsClientCache` |

---

## 7. Pass criteria → pilot smoke

Helper script `exit 0` ve şu probe'lar PASS:

- ✅ `Resolve-DnsName acik.local` returns A records
- ✅ `_ldap._tcp.dc._msdcs.acik.local` SRV records returned (DC FQDN + port)
- ✅ `nltest /dsgetdc:acik.local` returns DC name + IP
- ✅ Test-NetConnection 53/88/389/445 PASS (minimum required ports)
- ✅ Time sync clock skew < 5 dakika
- ✅ testai.acik.com:443 PASS (baseline cluster reachable)

**Pass → pilot smoke phase başlar**. Sıradaki adım:
1. Yeni gitops PR — pilot smoke evidence doc (gerçek run sonrası, placeholder PR değil)
2. Domain join (operator interactive `Get-Credential` — credential script/log/evidence'a YAZILMAZ)
3. Agent install + windows-live.ps1 smoke
4. BE-011 lifecycle (NON-DESTRUCTIVE `COLLECT_INVENTORY` only)
5. D29-EA matrix Up/Functional/Secured (domain-joined context)
6. Cleanup veya domain-joined 24-72h soak observation

Codex strategic `019e5aca` full pilot pattern (Q2-Q7) bu phase için reference.

---

## 8. References

- gitops `docs/faz-22-evidence/2026-05-24-acik-local-gate0-precheck-vpn-blocker.md` (predecessor evidence)
- gitops `docs/runbooks/RB-faz22-endpoint-pilot-it-owned.md` §2 lab gate + §3-§10 pilot prep
- platform-agent `scripts/test/parallels-acik-local-precheck.sh` (helper)
- platform-agent `scripts/test/parallels-windows11-ci.sh` (lab rehearsal companion)
- platform-agent `scripts/test/windows-live.ps1` (agent install/start/diagnose/uninstall — pilot smoke phase'de reuse)
- Codex strategic thread `019e5aca-edd8-7753-89aa-3f347bd6b9f7`
- Parallels Desktop CLI ref: `prlctl --help` + https://www.parallels.com/products/desktop/resources/

---

## 9. Audit trail

- Implementer AI: Claude (Anthropic)
- Reviewer AI: Codex (OpenAI)
- Codex strategic thread `019e5aca`
- Boundary: Operator playbook — agent VPN credentials / corp DNS IP / DC FQDN dokunmaz; operator infaz; agent helper script post-VPN reproducer + sanitized evidence; **NOT** acik.local IT pilot acceptance (Gate 0 unblock only); **NOT** prod-ready / password-reset-ready / domain-wide rollout-ready.
