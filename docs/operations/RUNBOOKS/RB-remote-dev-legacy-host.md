# Remote development on the retired Platform host

Tracking: [#3582](https://github.com/Halildeu/platform-k8s-gitops/issues/3582).
User request: move development storage and execution away from the nearly full Mac.

## Environment and scope

| Item | Value |
| --- | --- |
| SSH alias | `staging-sw-legacy` |
| Host identity | `stagingsw`, `10.9.10.53` |
| User | `halil` |
| Workspace root | `/srv/platform-dev` |
| Source repositories | `repos/platform-web`, `repos/platform-backend`, `repos/platform-k8s-gitops` |
| Docker service | `platform-dev-docker.service` |
| Docker socket | `/run/platform-dev/docker.sock` |
| Docker data | `/srv/platform-dev/docker` |
| Mac Docker context | `platform-dev-remote` (SSH; original local context remains selected) |
| Frontend shell | `127.0.0.1:33000` on the server, reached through SSH |
| Frontend remotes | `33001`, `33002`, `33004` through `33011`, all loopback |
| Dependency caches | `/srv/platform-dev/cache/pnpm`, `/srv/platform-dev/cache/maven` |
| Evidence | `/srv/platform-dev/evidence` |

This is a remote code/build/test environment with frontend development servers.
No DEV application database, Keycloak realm, backend service deployment, or
complete product login/API journey was installed or accepted by this work.
The frontend explicitly uses the reserved DEV identity address
`http://127.0.0.1:33081`, realm `platform-dev`; fake authentication is off.
The identity endpoint remains unavailable until a separately scoped DEV runtime
setup provides it. Never connect DEV to old production data to make login pass.

The old `docker.service` and `containerd.service` stay masked/inactive. The
dedicated developer daemon starts its own containerd under its separate root.
Neither `staging-sw` nor `aiserver` is the DEV target: both aliases resolve to
the active test/production server at `10.9.10.15`.

## Existing user workflows

On the Mac, `/Users/halilkocoglu/.local/bin/platform-dev` is a copy of
`scripts/dev-remote.sh`:

```bash
platform-dev status
platform-dev shell
platform-dev test-web
platform-dev test-backend
platform-dev build-web
platform-dev preview
platform-dev code
```

`preview` keeps an SSH tunnel in the foreground; Ctrl-C closes that tunnel.
Visit `http://127.0.0.1:33000/`. The setup session also opened two temporary
background tunnels with control sockets `/tmp/platform-dev-3582-preview.sock`
and `/tmp/platform-dev-3582-mfes.sock`. Close those before starting the
foreground tunnel on the same ports:

```bash
ssh -S /tmp/platform-dev-3582-preview.sock -O exit staging-sw-legacy
ssh -S /tmp/platform-dev-3582-mfes.sock -O exit staging-sw-legacy
```

`code` opens `/srv/platform-dev/platform-dev.code-workspace` through VS Code
Remote SSH. The workspace includes the three source repositories. Dependencies
must be installed on Linux; don't copy Mac `node_modules` or binary caches.

For Codex, Settings > Connections > SSH must show `staging-sw-legacy` connected.
Save the three projects under `/srv/platform-dev/repos/` and start new work in
those remote projects. The source repo identity allows the app's supported
handoff flow for existing tasks. Adding a host does not automatically move
existing local tasks, dirty worktrees, history, or files. This setup did not
transfer those items or modify their source content.

Official connection and handoff instructions:
<https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host>.

## Reproduce the installation

Use only the verified retired host, after the owner has authorized retirement
of its old data. No installer deletes old data or re-enables old services.

1. Install Java 21 and ripgrep from the OS package repository. Install
   `pnpm@10.12.4` and `@openai/codex@0.153.4` to the user's `.local` prefix;
   expose `.local/bin` in the login shell. Node observed: `v22.22.2`.
2. Clone the canonical repositories into `/srv/platform-dev/repos/` using the
   host's existing authorized Git access. Do not copy production credentials.
3. Set user login-shell `DOCKER_HOST=unix:///run/platform-dev/docker.sock` and
   `MAVEN_OPTS=-Dmaven.repo.local=/srv/platform-dev/cache/maven`.
4. Run `sudo bash bootstrap/host/install-remote-dev-engine.sh`. Docker data,
   socket, runtime state, bridge subnet, and network pools are DEV-specific.
   Both default bridge and user-defined bridge published ports default to
   loopback; explicit user port mappings can still override Docker defaults.
   Local container logs rotate at 10 MB with three files.
5. In `platform-web`, run `pnpm install --frozen-lockfile --store-dir
   /srv/platform-dev/cache/pnpm`.
6. Copy `install-remote-dev-frontend.py`, `platform-dev-preview.service`, and
   `platform-dev-mfe@.service` together to `/srv/platform-dev/ops/`; run the
   Python installer with sudo. It restarts the eleven DEV frontend servers.
   This deliberately uses the existing real federation entries, not fake auth
   or placeholder remote modules. Endpoint and meeting development federation
   flags are explicitly enabled because their defaults do not provide this
   complete developer bootstrap.
7. Authenticate Codex directly as the user and enable the SSH connection in
   the app. Authentication values must not be copied into logs or evidence.

## Verification recorded on 2026-09-06

- Owner explicitly authorized deletion of retired backups because the new host
  holds newer data. New-host PostgreSQL, Keycloak, Vault, and cluster containers
  were read back first; this was not a claim of byte-identical backup parity.
- Old `/var/lib/docker` and `/srv/platform/archive/aiserver-backup` were removed
  only after hostname/address, stopped container metadata, inactive/masked
  daemons, non-symlink paths, and absence of nested mounts were verified.
  Both paths were read back absent. Measured free-space increase:
  **326,087,487,488 bytes (303.6926 GiB)**. Free space went from approximately
  26 GiB to 329 GiB immediately after removal, then approximately 326 GiB after
  development dependencies were installed. Old services remained masked.
- The dedicated Docker daemon and preview units are enabled and active.
  A digest-pinned Maven container executed successfully. A named-volume marker
  survived removal of its writer container and matched on a fresh read.
  An implicit published port on a user-defined network bound to `127.0.0.1`.
  All proof containers, network, and volume were removed and read back absent.
- Toolchain image: `maven@sha256:8f6ac126f7810bb5549c4cd122d2bf0e9cda5bdeb0838aa928f09e779fd8bef8`.
- Frontend source `c19e8a96ee6b53db41ded73ca15dbb722e87e12b`:
  frozen pnpm install, **100/100 meeting tests**, shell production build.
  Browser readback showed the rendered login page after the remote federation
  servers were started. This is frontend loading evidence, not SSO acceptance.
- Backend source `5c961f597eb4bc4a6057bffc0194a84618280df4`:
  Java 21, Maven wrapper, **85 tests, zero failures/errors/skips** for
  `common-meeting-events`. Logs and outputs are on the server.
- Mac-to-server preview HTTP 200 through SSH; direct LAN access to port 33000
  failed as expected. Test and production public roots still answered 200;
  this reachability check does not claim broader application health.
- Codex `0.153.4` is present in the remote login shell and authenticated. User
  screenshot showed the SSH host connected; app project listing independently
  returned all three `/srv/platform-dev/repos/` remote projects.
- Twenty old local worktree dependency directories passed no-open-file,
  no-recent-Git/install-activity, ignored/generated-only, and lockfile checks.
  Only their `node_modules` were removed. Before/after Git status, binary diff,
  and lockfile hashes matched for every worktree. The **measured** local gain
  was **1,840,959,488 bytes (1.7145 GiB)**; their approximately 22 GiB logical
  directory sizes are not presented as recovered physical capacity.
- Local source worktrees, unsaved changes, the main local dependencies, Docker
  Desktop data, Codex sessions/history, and local credentials were preserved.
  Local disk pressure is reduced only modestly so far; future growth moves to
  the server only for work actually started or handed off there.

## Stop and rollback

Stop only the developer services:

```bash
sudo systemctl disable --now platform-dev-preview.service 'platform-dev-mfe@*.service'
sudo systemctl disable --now platform-dev-docker.service
```

Developer data and source remain on disk for restart. Do not unmask the legacy
production service units. The old backup deletion was owner-authorized and
irreversible; no rollback backup was manufactured. The Mac's original source
repositories remain available. Reinstall a removed worktree's dependencies with
its preserved `pnpm-lock.yaml` if that old local workflow is needed again.
