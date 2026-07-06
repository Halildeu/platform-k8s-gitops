# Faz 22.5 M2 Durable DNS / No-hosts Service Preflight

Date: 2026-06-15

Issue: platform-k8s-gitops#1569
Related: platform-k8s-gitops#1359, platform-k8s-gitops#1376, platform-k8s-gitops#1567, platform-agent#151, platform-agent#165

## Scope

This evidence file records the next autonomous M2 subgate after the bounded
local service-mode smoke: prove whether a Windows domain host can reach
`mtls.testai.acik.com` through durable AD DNS without a temporary hosts-file
shim, then continue to service-mode continuity over that path.

## Access Path

- Mac/Codex host can reach `ERP-MOBIL` through the existing reverse SSH tunnel:
  `staging-sw -> 127.0.0.1:22022 -> ERP-MOBIL:22`.
- Authenticated Windows identity: `acik\ca.setup`.
- Windows domain state:
  - Computer: `ERP-MOBIL`
  - Domain: `acik.local`
  - `PartOfDomain=True`
  - DC discovery: `ACIKDC01.acik.local` at `10.9.10.10`
  - Secure channel verification: `NERR_Success`

## Read-only DNS Preflight

Windows DNS client state:

- `Ethernet0` IPv4 DNS server: `10.9.10.10`
- `testai.acik.com` resolves through AD DNS to `10.9.10.53`
- `mtls.testai.acik.com` does not resolve through default DNS or explicit
  `-Server 10.9.10.10`
- `C:\Windows\System32\drivers\etc\hosts` contains no active
  `mtls.testai.acik.com`, `mtls.ai.acik.com`, `TEMP-M2-SMOKE`, or
  `10.9.10.53` shim line
- `Test-NetConnection 10.9.10.53 -Port 443` succeeds from `ERP-MOBIL`
- `Test-NetConnection mtls.testai.acik.com -Port 443` fails because name
  resolution fails

## Existing Agent Signal

The existing EndpointAgent log confirms the previous temporary-hosts proof and
the durable DNS failure after the shim was removed:

- With the temporary hosts shim, the agent selected the AD CS cert
  `ERP-MOBIL.acik.local` and sent repeated tokenless mTLS heartbeats.
- After shim removal, repeated iterations failed with:
  `lookup mtls.testai.acik.com: no such host`.
- Later bounded command/result smoke also succeeded only under the temporary
  route and is tracked separately.

## Attempted Autonomous DNS Mutation

The session attempted to inspect and prepare the narrow AD DNS fix from
`ERP-MOBIL` as `acik\ca.setup`.

Observed:

- `DnsServer` PowerShell module is installed.
- `RSAT-DNS-Server` is installed.
- `dnscmd.exe` is available.
- `whoami /groups` shows `ACIK\Domain Admins`, `ACIK\Enterprise Admins`,
  `BUILTIN\Administrators`, and High Mandatory Level.

Blocked operations:

- `Get-DnsServerZone -ComputerName 10.9.10.10` failed to enumerate zones.
- `dnscmd 10.9.10.10 /enumzones` returned `ERROR_ACCESS_DENIED`.
- `dnscmd ACIKDC01.acik.local /enumzones` returned `ERROR_ACCESS_DENIED`.
- Remote `schtasks` query against `ACIKDC01.acik.local` returned
  `Access is denied`.
- Direct DC management ports from the Codex host are limited: TCP 53, 135, 389
  and 445 are reachable; TCP 22, 3389, 5985, 5986, 636 and 9389 are not
  reachable.

## Interpretation

The M2 durable DNS blocker is now isolated:

1. The Windows host and service path are reachable.
2. The staging edge `10.9.10.53:443` is reachable.
3. The hosts-file shim is absent.
4. `mtls.testai.acik.com` is missing from AD DNS.
5. This Codex SSH session cannot mutate the DC DNS server despite the visible
   admin group membership, because DNS Server remote management and remote
   task creation return access denied.

This is an infrastructure/administrative access gate, not an agent code
blocker. No M2 closure is claimed.

## Narrow Fix Required

The intended durable DNS result is:

```text
mtls.testai.acik.com -> 10.9.10.53
```

The safest implementation is the narrowest AD DNS change that does not shadow
unrelated public names:

1. If an AD DNS zone `testai.acik.com` already exists, add only host record:
   `mtls A 10.9.10.53`.
2. If that zone does not exist, create an exact AD DNS zone
   `mtls.testai.acik.com` and add its apex A record to `10.9.10.53`.

After applying the DNS fix, rerun from `ERP-MOBIL`:

```powershell
Clear-DnsClientCache
Resolve-DnsName mtls.testai.acik.com -Server 10.9.10.10
Test-NetConnection mtls.testai.acik.com -Port 443
```

Then rerun the EndpointAgent no-hosts service continuity smoke.

## Boundary

This file proves the durable DNS blocker and the current autonomous access
limit. It does not prove service restart continuity over durable DNS, OS reboot
continuity, signed MSI/GPO deployment, 5-PC pilot, 24h soak, 50/800 staged
rollout, or prod `mtls.ai.acik.com` activation.
