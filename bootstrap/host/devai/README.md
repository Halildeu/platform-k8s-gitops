# DEV internal HTTPS integration

Tracked by platform-k8s-gitops #3582; DNS creation evidence is #3719.
This enables the developer journey: company/VPN browser -> DEV login -> real
DEV application/API -> persistent synthetic result. It does not deploy TEST or
PROD and does not replace personal SSH/GitHub accounts.

## Current activation boundary

Owner explicitly approved existing wildcard certificate/private-key reuse on
2026-09-12 (issue #3582 comment 5645710067). The approved material was streamed
over SSH from the existing read-only edge certificate paths into DEV root:caddy
0640 files. The source certificate and source service configuration were not
changed. DEV hostname matching, chain trust and key-pair matching pass.

The dedicated `platform-dev-proxy.service` now serves `https://devai.acik.com`
on `.53` only. UFW allows company `10.9.0.0/16` and VPN `10.250.250.0/24`
before destination-specific TCP 80/443 deny rules. The proxy independently checks
the socket peer, not forwarded headers. Legacy docker/containerd/caddy units
remain masked; databases and backend/frontend listeners remain loopback-only.
No TEST/PROD deployment or source mutation was performed.

The existing Sectigo wildcard expires **2026-10-01 23:59:59 UTC**. This is a
static certificate copy, not automatic renewal. Renew the authoritative
certificate and update the approved DEV copy before that date. Its SHA-256
fingerprint is `EF:2E:7E:90:8A:4B:58:08:5F:18:1A:C5:7D:5D:7F:D3:5F:86:58:C2:A4:AE:E6:CF:58:14:07:E5:0E:33:CF:E0`.

The installed DEV bootstrap currently lives in `/srv/platform-dev/ops/`; its
original source is the separate `remote-dev-3582` worktree. This integration adds
a systemd post-render hook without replacing that renderer or its encrypted
credential store. Calling the old renderer manually bypasses the post-render
hook: immediately run `configure-runtime.py` before any compose reconciliation.
Calling the old frontend installer overwrites public-origin settings: rerun this
installer before restarting the frontend. Do not mix these operational paths.

## Resolver evidence and rollback

`/etc/netplan/50-cloud-init.yaml` now has only `10.9.10.10` under ens160 DNS,
replacing `10.9.10.1` and `8.8.8.8`. The address, route and SSH settings were
unchanged. `netplan generate` readback in
`/run/systemd/network/10-netplan-ens160.network` shows `DNS=10.9.10.10`.
`resolvectl dns ens160 10.9.10.10` applied the resolver without resetting the
network link. Both `devai.acik.com` and `github.com` resolve through that link;
`getent ahostsv4 devai.acik.com` returns `10.9.10.53` without a hosts override.
AD DNS also forwards public lookups; this is not a two-resolver split-DNS setup.

Rollback: restore `/etc/netplan/50-cloud-init.yaml.pre-devai-20260912` to the
original file, run `sudo netplan generate`, then
`sudo resolvectl dns ens160 10.9.10.1 8.8.8.8`. Do not restart the NIC.
Previously established `ai`/`testai` hosts entries remain unchanged.

## Certificate

A separate, unused RSA-3072 key is root-owned mode 0600 under the root-only directory
`/etc/platform-dev/devai-csr/`. Its self-verified CSR contains only
`CN=devai.acik.com` and `SAN=DNS:devai.acik.com`.
Public CSR: `/srv/platform-dev/evidence/devai-20260912/devai.acik.com.csr`.
SHA-256: `7f785f367130fd0dc5ee4b5a3c09506ea011a587bb4756c771c88ba8c0218c19`.
Only the CSR may be shared for signing; never share the key.

Before activation, install the approved chain and matching key as
`/etc/platform-dev/proxy/tls/{fullchain.pem,privkey.pem}`, root:caddy 0640,
parent directories 0750. The installer checks hostname, validity, system trust
and matching public keys. An internal CA must be trusted by the actual company
and VPN client browsers as well; trusting it on DEV alone is insufficient.

## Activation sequence

1. Read the claimed issue, source and runtime states; confirm `.53` scope.
2. Preserve an encrypted DEV PostgreSQL backup and verify its readability before
   changing the Keycloak issuer. Do not change any application artifacts/volumes.
3. Run `sudo python3 bootstrap/host/devai/install.py` from this worktree.
   Existing files are backed up under root-only
   `/etc/platform-dev/pre-devai-20260912`. This installs configuration and scoped
   UFW rules but does not restart services. Legacy `caddy.service` stays masked.
4. Run `python3 /srv/platform-dev/ops/devai/configure-client.py` as `halil`.
   This updates only the existing DEV frontend client's redirect/origin lists,
   keeps PKCE/users/mappers intact, stores an encrypted rollback snapshot and
   requires exact live client representation readback.
5. Run the post-render hook as `halil`, then reconcile only DEV Keycloak and the
   thirteen backend services with the existing compose file/socket. Do not
   restart the Docker daemon or recreate databases. Allow service readiness.
6. Restart `platform-dev-preview` and the ten `platform-dev-mfe@` instances;
   enable/start `platform-dev-proxy.service`. Verify the expected 80/443 bind is
   only `10.9.10.53`; every frontend/backend/dependency still binds loopback.
7. Verify DNS + TLS without bypass, OIDC issuer/PKCE redirects, all federation
   entries and HMR over wss. Use a normal synthetic DEV persona in Chromium to
   sign in, reload the users grid, write/read a profile in a new session and
   restore the original. Check anonymous API rejection, foreign Origin and
   outside-subnet rejection (including forged XFF), management-path denial, and
   denied direct backend ports from another host. Check restart persistence.
   A real company/VPN client must confirm normal certificate trust; a local
   resolver override or custom browser trust is not that proof.

The Vite wrapper uses `--configLoader runner` so the root-owned ops directory
does not need developer write permission for bundled temporary config files.
Each MFE has its own `/mfe/<name>/` base and wss endpoint; legacy direct
`/remoteEntry.js` health requests redirect to that base. Original app plugins and
API ownership remain in the canonical app config.

Keycloak login forms with its no-referrer policy send `Origin: null`. OIDC
routes reach Keycloak before the Vite-specific Origin guard; Keycloak retains
session/code and PKCE validation. A form POST without a bound session returns
400. Foreign Origin on the Vite surface returns 403. `/admin/users` remains an
application route; only Keycloak administration paths are blocked.

The proxy deliberately blocks `/api/services`: its legacy Vite plugin can
start/stop services without application authentication. Use SSH for operations.
Frontend source and HMR remain available to the allowed company/VPN subnet, as
expected for a development server. This is not a public production frontend.

## Rollback

Stop/disable only `platform-dev-proxy.service`; leave database volumes intact.
Run `configure-client.py --rollback` while DEV Keycloak still answers locally.
Remove only the three new `devai.conf` drop-ins, restore the backed-up
`frontend-common.env`, reload systemd and run the original runtime renderer.
Reconcile only the same fourteen DEV containers; restart the eleven frontend
units. Remove only the six UFW rules with the `devai-` comments. Re-run existing
loopback browser/profile/variant/runtime checks. Preserve encrypted backups and
the certificate key; do not unmask legacy services.

## Verification

- Five focused runtime-transform tests; Python compilation; Caddy validation;
  trusted wildcard hostname/chain/key match (no TLS bypass).
- `verify-http.py`: eleven real federation JavaScript entries, correct public
  OIDC endpoints, management paths 404, anonymous users 401, foreign Origin 403,
  unbound login 400, untrusted socket peer 403 even with forged corporate XFF.
- `verify-profile.py`: synthetic HTTPS login, profile write, fresh-token readback
  and restoration. No production data is used.
- `verify-browser.cjs`: normal DNS/TLS Chromium login, users grid and reload,
  successful API calls, no observed page errors, failed requests or foreign
  origins. A unique temporary source module is imported, changed and observed
  updating in the browser over wss; the file is removed and app Git status is
  clean afterward. Desktop/mobile screenshots are inspected. These screenshots
  retain the existing DEV AG Grid trial watermark; no license migration is
  claimed by the HTTPS work. Authenticated screenshots and receipts remain in the private local
  evidence directory, not the repository.
- Proxy and all eleven frontend services restarted; the original runtime check
  again passed 18 container artifact/mount/process checks and 25 HTTP checks.
- Original renderer plus persistent post-render hook reproduces all 19 generated
  configuration files byte-for-byte. Full machine reboot was not performed.
- Real second host `.15` reaches DEV HTTPS with status 200/TLS verify 0; its
  direct request to DEV port 33000 times out. This second-host HTTPS probe used
  `--resolve`, so it does not claim that host's normal DNS is configured.
- A temporary external-subnet namespace (`192.0.2.253`) times out on 80/443 even
  with forged XFF; both UFW destination deny counters increment. The namespace
  and veth were removed and read back absent.
- Individual Mac/VPN resolver configuration and Zeynep's personal SSH account
  remain outside these server-side proofs. VPN clients must use corporate DNS.

Run the three `verify-*` helpers in this directory plus the existing runtime
verifier. Evidence: `/srv/platform-dev/evidence/devai-20260912/`. Preserve the
encrypted PostgreSQL archives (`platform`, `keycloak`, `openfga`) and encrypted
Keycloak client snapshot under the existing private DEV secret directory.

Primary configuration references:
[Vite server options](https://vite.dev/config/server-options),
[Keycloak reverse proxy](https://www.keycloak.org/server/reverseproxy),
[Caddy matchers](https://caddyserver.com/docs/caddyfile/matchers).
