# Personal DEV Access

Tracked by platform-k8s-gitops #3582. This enabler supports the developer
workflow for existing ATS #213/#966 product slices. It is not product delivery.

## Installed State

On 2026-09-12, the owner authorized onboarding the employee whose public key
arrived in the DEV access email thread. No private key was requested or copied.

- Account `zeynep`, UID/GID 1002, private primary group only, Bash login shell.
- Home `/home/zeynep`, mode 0750; `.ssh` and `repos` mode 0700;
  `authorized_keys` mode 0600, owned by the employee account.
- `/etc/ssh/sshd_config.d/90-zeynep-dev.conf` requires public-key auth and
  disables password, keyboard-interactive, agent forwarding, X11 and tunnels.
  Local TCP forwarding is allowed for the editor; GatewayPorts is disabled.
- The employee key is restricted to company `10.9.0.0/16`, VPN
  `10.250.250.0/24`, and loopback peers. The existing SSH firewall admits
  company/VPN and rejects other sources. No firewall rules were added.
- No sudo/docker membership or operator secrets. Direct reads of the operator
  SSH config, wildcard private key, runtime compose config and secret-store
  key, plus write access to the Docker socket, were denied as this user.
- `.profile` uses personal `.local/bin` and `.cache`, Java 21, Maven heap 2 GiB
  and umask 077. `.npmrc` uses personal prefix/store with child concurrency 2.
- Installed personal binaries: pnpm 10.12.4, Maven 3.9.10, GitHub CLI 2.100.0,
  Codex 0.153.4, Claude Code 2.1.263. System Node 22.22.2/Java 21.0.12 are reused.
  Maven's downloaded archive matched the publisher's SHA-512 sidecar.
  AI executables are present, not authenticated or subscription-accepted.

The existing operator GitHub authorization bootstrapped four independent
single-branch/shallow clones; no credential helper, token or operator Git
configuration was copied. Current repository permissions for the employee
were checked before cloning. No new GitHub permission was granted.

| Repository | Verified initial HEAD |
| --- | --- |
| ats | `0ace75fc8570e0a26e39d3b5131aa45431674636` |
| platform-web | `2131238f084d27cc1016ae3dbf2ff14654057298` |
| platform-backend | `965cb1c039892d4da81f6251db9dc94bc5ce8c8e` |
| platform-k8s-gitops | `72d896c0c8db004603cb8bf5f850bff51d972202` |

All four passed Git fsck, clean working-tree, exact HEAD and canonical HTTPS
origin checks. Future fetch/push must use the employee's own GitHub login.
The shared `/srv/platform-dev/repos`, caches and runtime were not exposed.

## Employee Workflow

Connect from company/VPN with `ssh zeynep@devai.acik.com`, or configure the
editor's SSH remote with this account. Open `/home/zeynep/repos/<repo>`.
Connection details and the verified server host fingerprint are in the
owner-approved email and `/home/zeynep/DEV-README.md`.

Authenticate GitHub personally with `gh auth login --hostname github.com
--git-protocol https --web`, then `gh auth setup-git`. Verify `gh api user
--jq .login` reports the employee account. AI tools also require personal
authentication. Never copy another user's tokens or agent session directory.

Use a personal branch and PR; follow each repository's instructions and
board claim protocol. Existing TEST/GitOps/production approval gates remain.
No direct production or shared test deployment is authorized by this account.

`https://devai.acik.com` is a shared preview, not a watcher for personal clones.
Use a free loopback port and editor/SSH forwarding for personal frontend work.
Run one heavy build at a time. Required application dependencies and DEV-only
settings are scoped to the task; this setup does not include a personal
database/runtime or broad shared Docker privileges.

## Verified Scope

As the actual Linux account, on the recorded ATS HEAD:

```bash
cd ~/repos/ats
npm --prefix packages/ui ci --no-audit --no-fund
npm --prefix web/mfe-interview-evidence ci --no-audit --no-fund
mvn -B -ntp -f backend/pom.xml -pl application-intake -am test
npm --prefix web/mfe-interview-evidence test -- --maxWorkers=2
npm --prefix web/mfe-interview-evidence run build
```

Results: 78 Java tests, 54 frontend unit tests, frontend typecheck/build pass.
The first frontend check found missing local UI dependencies; installing
`packages/ui` and rerunning fixed this. Existing jsdom pseudo-element warnings
remain; the suite explicitly excludes real color-contrast acceptance.
No application source or dependency lockfile changed. These checks do not
prove live SSO, persistence, user journeys or production readiness.

`sshd -t` and account-specific `sshd -T` passed after a reload. A read-only SSH
public-key offer with the employee's public key was accepted by the server.
No signature was supplied because the private key remains on the employee's
device; authentication then failed as expected. This is not a successful login.
DEV HTTPS from the account returned 200 with TLS verification successful.

Owner-approved email was accepted by Graph and its sent copy was read back,
including sender, recipient, owner CC and complete body. This does not prove
the employee read it. No second email was sent automatically.

## Remaining Acceptance

- Employee device on company/VPN resolves DEV and completes SSH with its key.
- Employee performs personal GitHub/AI login and verifies its identity.
- Employee edits, tests and pushes a personal branch/PR using that identity.
- Any authenticated personal application preview is verified with DEV-only
  dependencies. Shared TEST and production promotion remain separate gates.

Keep #3582 open; server-side preparation and email do not close these items.

## Rollback

To revoke access, remove the exact authorized key and expire the account with
`usermod --expiredate 1 zeynep`. Password locking alone does not revoke SSH keys.
Check existing employee sessions before terminating them; removal of a key
does not kill an already-authenticated session. Retain the home/repos and any
user changes. Do not recursively delete the account's work as a rollback.

For the new SSH drop-in only, restore/remove that file, validate with
`sshd -t`, then reload SSH. Do not change the existing operator SSH/firewall,
shared runtime, wildcard material or TEST/PROD configuration.
