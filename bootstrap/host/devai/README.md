# DEV internal HTTPS integration

Tracked by platform-k8s-gitops #3582; DNS creation evidence is #3719.
This enables the developer journey: company/VPN browser -> DEV login -> real
DEV application/API -> persistent synthetic result. It does not deploy TEST or
PROD and does not replace personal SSH/GitHub accounts.

## Current activation boundary

On 2026-09-12, only the DEV resolver was changed. These HTTPS scripts are a
candidate, not an activated or accepted HTTPS deployment. No certificate chain
is installed. Owner selection of a dedicated DEV certificate or explicit
authorization to reuse the existing wildcard material is pending. Never silently
copy a production private key or mark `curl -k` as trusted browser acceptance.

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

A dedicated RSA-3072 key is root-owned mode 0600 under the root-only directory
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

## Candidate activation sequence

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

The proxy deliberately blocks `/api/services`: its legacy Vite plugin can
start/stop services without application authentication. Use SSH for operations.
Frontend source and HMR remain available to the allowed company/VPN subnet, as
expected for a development server. This is not a public production frontend.

## Candidate rollback

Stop/disable only `platform-dev-proxy.service`; leave database volumes intact.
Run `configure-client.py --rollback` while DEV Keycloak still answers locally.
Remove only the three new `devai.conf` drop-ins, restore the backed-up
`frontend-common.env`, reload systemd and run the original runtime renderer.
Reconcile only the same fourteen DEV containers; restart the eleven frontend
units. Remove only the six UFW rules with the `devai-` comments. Re-run existing
loopback browser/profile/variant/runtime checks. Preserve encrypted backups and
the certificate key; do not unmask legacy services.

## Verified before activation

- Five focused runtime-transform tests; Python compilation; Caddyfile adapter
  parses successfully. Full TLS provisioning cannot validate without the chain.
- Temporary loopback Vite wrapper probe: correct Host 200, foreign Host 403.
  This probe had no frontend runtime env loaded and reported missing disabled
  remote imports; it is not full federation acceptance. Probe was stopped and
  port 33100 confirmed absent.
- Existing runtime after resolver change: 18 containers, 25 HTTP checks succeed.
- Existing synthetic browser login: users API 200 twice, visible 16 rows /
  128 cells, no page errors. Profile write/new-token read/restore verified.
- HTTPS-domain browser, HMR, LAN/VPN boundary and restart acceptance: unverified.

Primary configuration references:
[Vite server options](https://vite.dev/config/server-options),
[Keycloak reverse proxy](https://www.keycloak.org/server/reverseproxy),
[Caddy matchers](https://caddyserver.com/docs/caddyfile/matchers).
