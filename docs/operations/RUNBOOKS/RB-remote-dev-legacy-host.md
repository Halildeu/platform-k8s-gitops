# Remote development on the retired Platform host

Tracking: [#3582](https://github.com/Halildeu/platform-k8s-gitops/issues/3582).
User request: move development storage and execution away from the nearly full Mac.

Automatic compose startup is now supplied by the merged #3590 units and helper.
Install it using [the autostart runbook](./RB-remote-dev-runtime-autostart.md).
A subsequent daemon restart, with no manual compose call, preserved all 18 PIDs
and triggered a new runtime-service invocation; real login/profile/variant checks
passed afterward. The historical manual cold test below is a separate proof.

## Current verified scope (2026-09-08)

- SSH to `stagingsw` (`10.9.10.53`) works. The prior eleven-exited-container
  finding was reproduced: 44 orphan processes retained ports while Docker lost
  ownership. Volatile runtime-directory removal with live-restore processes was
  the cause. `RuntimeDirectoryPreserve=yes` retains the daemon runtime sockets.
  Three PostgreSQL dumps were read back before scoped graceful shutdown.
- Eighteen containers now match configured immutable images, server-local mounts,
  JAR hashes and Docker-owned PIDs/cgroups. Thirteen backend health endpoints,
  eleven frontend federation endpoints and OIDC discovery respond. Added services:
  notification, endpoint-admin, ethics, report, schema, SQL Server and Mailpit.
- Live-daemon restart retained the process identities. Cold recovery stopped all
  containers and config delivery, verified tmpfs removal, then regenerated it and
  started the stack. All 18 acquired new owned PIDs with identical artifacts and
  mounts; zero orphan container cgroups remained. This is controlled service
  recovery, not a physical machine reboot claim.
- Real DEV login opens user, meeting, report, schema and endpoint screens without
  observed page/API errors. Profile update/new-session readback and variant
  create/new-session read/delete passed after cold recovery. An API-created meeting
  remained visible in the browser after cold start and reload, then was deleted
  and read back absent. Wrong notification tenant returns 403; anonymous variant
  access returns 401.
- Variant authz JWT forwarding is fixed in [backend PR #1139](https://github.com/Halildeu/platform-backend/pull/1139),
  commit `81a5f6f84b8c31af0a39a27249bed50b1aaf83ae`. Nineteen targeted tests and
  all 24 PR checks passed. Mounted JAR SHA-256:
  `20a0afda2675664b0980c8760846c2ce065b810d4fef5aea454624d0f4fed6dd`.
  Wrong-hash/outside-root overrides fail closed; restored config hashes match.
- OpenFGA uses the canonical 17-type model, preserving all nine old definitions;
  ten allow/deny fixtures pass. Developer claims use the canonical user identity.
  The dedicated `REMOTE_DEV` role was assigned/read back through permission APIs.
- SQL has two synthetic fixture tables and one FK; reader SELECT passes and INSERT
  is denied. The users-overview report returns DEV rows. Real ERP financial data,
  external AI/transcription, physical endpoint enrollment and native Apple builds
  are not accepted. Meeting AI/transcript and outbound notification dispatch remain
  explicitly disabled. Ethics retains its secure-transport guard.
- All 45 checked DEV TCP listeners are loopback-only, including mapped IPv4
  loopback. Legacy docker/containerd stay masked/inactive. Remote Claude/Codex
  authentication and tmux work. Mac Docker resolves to `stagingsw` and
  `/srv/platform-dev/docker`. Approximately 168 GiB is free on .53.
- Receipts: `/srv/platform-dev/evidence/recovery-20260908/`, especially
  `cold-acceptance.json`, `post-cold.json`, `meeting-browser.json`,
  `api-modules.json`, `browser-modules.json` and `network-units.json`.
  The installation and recovery procedures follow below.
  Historical copy hashes below are snapshots and do not cover later Mac edits.
  Local source/history deletion was not performed; held credentials, unique later
  edits and live task handoff remain outside this DEV acceptance.

## Environment and scope

| Item | Value |
| --- | --- |
| SSH alias | `staging-sw-legacy` |
| Host identity | `stagingsw`, `10.9.10.53` |
| User | `halil` |
| Workspace root | `/srv/platform-dev` |
| Source repositories | `repos/{platform-web,platform-backend,platform-k8s-gitops,ats,platform-ai,platform-agent,ao-kernel,platform-desktop,platform-mobile}` |
| Docker service | `platform-dev-docker.service` |
| Docker socket | `/run/platform-dev/docker.sock` |
| Docker data | `/srv/platform-dev/docker` |
| Mac Docker context | `platform-dev-remote` (SSH; selected Mac default) |
| Frontend shell | `127.0.0.1:33000` on the server, reached through SSH |
| Frontend remotes | `33001`, `33002`, `33004` through `33011`, all loopback |
| Dependency caches | `/srv/platform-dev/cache/pnpm`, `/srv/platform-dev/cache/maven` |
| Evidence | `/srv/platform-dev/evidence` |

The current runtime has PostgreSQL, Keycloak, OpenFGA, SQL Server Developer,
Mailpit and thirteen Java services: gateway, auth, user, permission, variant,
core-data, meeting, budget, notification, endpoint-admin, ethics, report and schema.
Eleven frontend processes use this isolated stack. All DEV listeners bind loopback
and are reached through SSH. No active production data/credential was imported.
Mailpit is a local capture service; outbound dispatch remains disabled. Native
macOS/iOS builds still require an Apple toolchain host.

The old `docker.service` and `containerd.service` stay masked/inactive. The
dedicated developer daemon starts its own containerd under its separate root.
Neither `staging-sw` nor `aiserver` is the DEV target: both aliases resolve to
the active test/production server at `10.9.10.15`.

## Existing user workflows

On the Mac, `/Users/halilkocoglu/.local/bin/platform-dev` is a copy of
`scripts/dev-remote.sh`:

```bash
platform-dev status
platform-dev runtime-status
platform-dev verify
platform-dev shell
platform-dev session
platform-dev test-web
platform-dev test-backend
platform-dev build-web
platform-dev preview
platform-dev code
```

`session` opens the persistent `platform-dev` tmux session on the server.
Detach with Ctrl-B then D; CLI jobs in that session can continue after the SSH
client disconnects. Git identity was copied without exposing its values, read
back, and private GitHub repository access was verified. Maven settings, the global Git ignore rule, and
pnpm user configuration point to their shared Linux caches.

The Mac's default Docker context now points to the verified remote daemon
(`stagingsw`, `/srv/platform-dev/docker`). Local Colima was confirmed to have zero
containers and zero named volumes, then stopped; the remote context was read back
after stopping it. Local Docker disk/source files were not removed by this step.

`preview` keeps an SSH tunnel in the foreground; Ctrl-C closes it.
Visit `http://127.0.0.1:33000/`. The September 8 setup has a temporary background
tunnel at `/tmp/platform-dev-20260908.sock`; close it before starting another
tunnel on the same ports:

```bash
ssh -S /tmp/platform-dev-20260908.sock -O exit staging-sw-legacy
platform-dev preview
```

`code` opens `/srv/platform-dev/platform-dev.code-workspace` through VS Code
Remote SSH. The workspace includes nine source repositories and two active worktrees:
`/srv/platform-dev/worktrees/remote-dev-3582` and
`/srv/platform-dev/worktrees/variant-authz-1138`. Dependencies
must be installed on Linux; don't copy Mac `node_modules` or binary caches.

For Codex, Settings > Connections > SSH must show `staging-sw-legacy` connected.
Save the three projects under `/srv/platform-dev/repos/` and start new work in
those remote projects. The source repo identity allows the app's supported
handoff flow for existing tasks. Adding a host does not automatically move
existing local tasks, dirty worktrees, history, or files. The protected file/history migration described below preserves those items; an
archive is not a supported live task handoff. The current task cannot hand itself
off through the exposed tool. Use the app's supported handoff action before
removing a local task's checkout.

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
   `RuntimeDirectoryPreserve=yes` is mandatory with live-restore: do not remove
   runtime sockets while the child container processes remain alive.
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

## Isolated runtime bootstrap

Build all backend modules first with Java 21 and the shared Maven cache:
`./mvnw -Dmaven.repo.local=/srv/platform-dev/cache/maven -DskipTests package`.
Build `schema-service` separately with its standalone POM after installing
`common-auth` and required reactor dependencies in the shared cache; it is not
in the root reactor. Copy the Python runtime/fixture scripts (including `remote_dev_credentials.py`),
browser verification script and runtime-config unit from `bootstrap/host/` to
`/srv/platform-dev/ops/`. Run the following on the verified old host as `halil`:

```bash
export DOCKER_HOST=unix:///run/platform-dev/docker.sock
python3 /srv/platform-dev/ops/install-remote-dev-runtime.py
docker compose -f /srv/platform-dev/runtime/compose.json up -d postgres mssql
# Wait for SQL readiness before seeding its isolated synthetic fixture:
python3 /srv/platform-dev/ops/seed-remote-dev-mssql.py
docker compose -f /srv/platform-dev/runtime/compose.json run --rm --no-deps openfga migrate
docker compose -f /srv/platform-dev/runtime/compose.json up -d openfga
python3 /srv/platform-dev/ops/seed-remote-dev-openfga.py
python3 /srv/platform-dev/ops/install-remote-dev-runtime.py
docker compose -f /srv/platform-dev/runtime/compose.json up -d
# After the identity and user services are ready, initial synthetic fixture only:
python3 /srv/platform-dev/ops/verify-remote-dev-profile.py --activate-fixture
python3 /srv/platform-dev/ops/seed-remote-dev-identity.py
# Wait for permission bootstrap and authz readiness:
python3 /srv/platform-dev/ops/seed-remote-dev-role.py
```

The permission service bootstraps the synthetic admin using the explicitly
verified canonical `user_service.users` ID space. Its bootstrap loop can need time
after the user fixture is created; check `/api/v1/authz/me` with that identity.
Subsequent persistence verification omits `--activate-fixture`. Browser acceptance
uses `node /srv/platform-dev/ops/verify-remote-dev-browser.cjs` after installing
the frontend Playwright Chromium browser and its Linux OS dependencies.

The generator stores DEV-only random credentials in authenticated Fernet ciphertext
at `runtime/secrets/credentials.enc` (0600). Its key is in the separate root-owned
`/etc/platform-dev/secret-store/credential.key` (0600, parent 0700), accessed through
the existing operator sudo authorization. An unavailable key fails closed; it is
never silently replaced for an existing encrypted store. Python's OS-provided
`cryptography` package is required. Legacy DEV values are encrypted without rotation
and compared in memory before obsolete plaintext helper files are removed.

Generated env, realm import and database-init files live in the verified tmpfs
`/run/platform-dev-config` (0700); no duplicate plaintext credential JSON or login
text file is retained. `platform-dev-runtime-config.service` renders this directory
before `platform-dev-docker.service` starts. Install/enable the config unit and add
`Requires=platform-dev-runtime-config.service` plus
`After=platform-dev-runtime-config.service` to the Docker unit's `[Unit]` drop-in.
This keeps required bind-mounted files available after a host/daemon cold start.
Docker's privileged runtime metadata still contains its normal container environment;
this setup does not claim full-disk encryption of Docker state. The September 8 cold recovery re-rendered absent tmpfs configuration, restarted
18 owned containers and checked 13 backend health responses plus persistent
meeting/profile/variant behavior. Earlier HTTP-only checks had missed orphan
processes and are superseded for runtime lifecycle acceptance. The
missing-key path refused regeneration; fifteen obsolete plaintext files were
removed only after the encrypted values and authenticated behavior matched.

For the synthetic DEV login, a human may run
`python3 /srv/platform-dev/ops/remote_dev_credentials.py --show-dev-login` in their
own SSH terminal. Never paste its output into chat, logs or GitHub.
Postgres uses a persistent named volume. Application connections use
`platform_app` with `NOSUPERUSER NOBYPASSRLS`; infrastructure owns its own database
setup. Hibernate `update` is scoped to this synthetic DEV bootstrap, not a claim
of production migration parity. OpenFGA remains real and enabled; security
startup guards were not disabled to make a service start.

## Artifact overrides and daily verification

`runtime/artifact-overrides.json` selects a built JAR by service using `path`,
`sha256` and `source_commit`. Its resolved path must be under
`/srv/platform-dev/artifacts/`; a wrong hash or outside-root path refuses runtime
generation. Keep the file private (0600). The current variant override is built
from the active backend worktree; other jars retain their recorded build sources.
Changing the selected artifact requires fresh behavior checks.

```bash
python3 /srv/platform-dev/ops/verify-remote-dev-runtime.py
python3 /srv/platform-dev/ops/verify-remote-dev-profile.py
python3 /srv/platform-dev/ops/verify-remote-dev-variant.py
node /srv/platform-dev/ops/verify-remote-dev-browser.cjs
```

`platform-dev verify` runs the first three remotely. Profile/variant verification
creates and reverses narrowly scoped synthetic data. The browser check verifies
real authentication, the users API and visible identity after a page reload.
These checks are not acceptance of every customer workflow.

For controlled cold recovery (interrupts only this DEV stack), preserve volumes:
`docker compose stop --timeout 45`, stop the dedicated Docker and config units,
then start the Docker unit (which requires config regeneration). Run
`docker compose up -d`: explicitly stopped containers do not auto-resume via
`unless-stopped`. Allow several minutes for thirteen Java services on four CPUs.
Re-run behavior verification after health returns. Never use `down -v` here.

## Development data and history migration

The source inventory contains 1,434 Git areas, including nested test-fixture
repositories and 259 areas with local changes; this is not 1,434 distinct products.
The file selection is approximately 51.23 GiB, excluding reproducible dependency
caches. Protected manifests and verification outputs live under
`/srv/platform-dev/migration/evidence/`. The snapshot preserves the original path
layout under `migration/mac-files/`. Host-only compatibility symlinks for
`/Users/halilkocoglu` and `/private/tmp` preserve absolute Git worktree pointers.

The selected source/configuration files include reviewed credential-free npm
configuration and tracked test certificates. Twelve credential-bearing or
credential-like files remain on the Mac for separate handling; generated DEV
secrets replace the needed local DEV authentication. Do not remove those held
files as part of a generic cleanup. Mac binaries, `node_modules`, virtualenvs and
Maven caches are rebuilt on Linux rather than reused.

Codex sessions, archived sessions, and Claude project history are streamed to the
protected `migration/history/mac-agent-history.tar.gz`. This is a backup snapshot;
it is not restoration into the active Codex task database. Global Codex/Claude instructions and three portable personal skills were also
installed in the remote user profile and hash-checked. Claude's user-scoped
Codex MCP passed its connection health check. Thirteen development Claude project histories were copied into the remote
projects directory without replacing new remote files; checksum dry-run found
zero differences. Nine non-development histories are retained only under
`migration/claude-other-history`, outside the active remote project list. Mac-specific app/MCP
integrations and active task routing are not automatically portable.

The stopped Mac Docker Desktop disk is also preserved as a sparse recovery
copy under `migration/docker-desktop/`; its application contents are not mounted
or asserted restored. Local Colima has zero containers and zero named volumes.

The full transfer selected 2,922,990 file/symlink entries including the reviewed
supplement. The target has 2,922,977 of those entries; the thirteen absent entries
are Git references/checkpoints already removed by ongoing source-side Git activity.
There are zero selected files that still exist on the source but are missing only
on the target. No source code or local working change is classified as lost.
The file set is approximately 51.23 GiB; transfer protocol checksums and the
source/target presence/size inventory are recorded in the protected evidence.

All 1,430 valid HEADs and tracked binary-diff hashes matched. The three previously
broken worktrees and one empty/no-HEAD Git area were distinguished from transfer
errors; the empty Git directory structure was restored on the target. After
accounting for intentionally excluded caches/held files and copying the global
Git ignore rule, normalized working status matched. All 386 sets of local branch,
tag and stash references matched. Remote-tracking references and temporary Codex
checkpoint references changed while the source remained active; they are not
misrepresented as a frozen whole-repository transaction.

SHA-256 matched for all 27,914 selected uncommitted/untracked working files. The
71,938 missing entries in that separate working-change scan were exclusively
reproducible `.pnpm-store`, `.m2`, `.npm`, and `__pycache__` contents. The nine
active Linux repositories also imported 3,500 branch references from ten source
clones (desktop has both Documents and home copies), under `mac-documents` and
`mac-home` namespaces. Fetch uses `--update-shallow` because the original clones
contain shallow boundaries; all imported branch names and commit IDs matched.

The agent-history archive is 36,290,785,280 bytes, SHA-256
`106af8c484f777df6083c135798e75f269d449e1a9b2258805c0a88941b11e30`.
Source/target archive hashes and the 1,962-entry count matched; gzip/tar readback
exited successfully. GNU tar ignored only macOS extended metadata headers.
This is a point-in-time backup of histories that can continue growing on the Mac.
The stopped Docker Desktop disk's 42,949,672,960 logical bytes also passed a full
source/target SHA-256 comparison; the sparse copy remains a recovery artifact.

Local source/worktree/history removal has not been performed. Existing Codex
local tasks still require supported handoff; their active task routing is not
changed by these file copies. Migration receipts and file lists are private
operational evidence, never committed to this repository.

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
  servers were started. A later real Keycloak login returned to `/home` without browser page errors;
  profile persistence across a new authenticated session also passed.
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
- Additional Linux checks: all 23 backend modules packaged (`-DskipTests`); ATS
  backend packaged; desktop typecheck and 652 tests; mobile typecheck; ao-kernel
  27 adapter-manifest tests; Go config/security tests; four Python AI-service
  dependency installations. This does not assert GPU/provider inference or native
  Mac/iOS build acceptance. Exact repository heads, runtime image IDs, jar SHA256s
  and eight service health responses are in `evidence/final-dev-runtime.json`.
- Claude Code and Codex are independently authenticated on the remote host.
  GitHub CLI 2.100.0, uv, Go and Linux build tools are available there.
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


## 2026-09-09 — Verified cleanup boundary and recovery

The private acceptance root is
`/srv/platform-dev/migration/snapshots/20260909-predelete/`.
Use `evidence/migration-acceptance.json`, `dirty-work-recovery.json`,
`git-comparison.json`, `candidate-source-fence.json`, and the history restore
receipts to decide whether a particular local path is covered. Keep raw
inventories, histories, SQLite files and recovery keys out of GitHub and Git.

A clean Git status is insufficient. Preserve user branches/tags/stashes,
detached heads, staged and unstaged changes, untracked source files, locally
installed Maven artifacts, and separate credentials. The verified candidate
CSV names 294 old worktree directories and four package-cache directories.
It is not permission to recursively remove Documents, ~/.codex, ~/.claude,
~/.ssh, ~/.docker, VM storage, or the active local project.

### Recovery checks that caught real verification problems

1. GNU Git on this host rewrites an index while running `git diff`, even with
   `GIT_OPTIONAL_LOCKS=0`; a measured index grew by 64 bytes. Git semantic
   verification therefore ran before the final byte-preservation correction.
   The 1,412 affected indexes were recopied from unchanged Mac sources and
   rehashed; one actively written scheduler log was frozen and rehashed.
   The full file pass plus all 1,413 targeted corrections leave zero
   mismatches. Do not run ordinary Git mutations against a backup snapshot.
2. Fetching from a shallow source initially omitted one branch with
   "shallow roots are not allowed to be updated". The independent restore
   uses `git fetch --update-shallow`, then compares the complete user-ref set
   and runs full fsck. This preserves the source's existing history boundary.
3. Comparing default abbreviated diff headers produced a two-byte false
   mismatch between object stores of different sizes. Recovery compares
   `git diff --full-index --binary` and actual working-file hashes instead.
4. History files continue to grow while agents are active. The authenticated
   encrypted base and later delta are explicit time cuts. SQLite files use
   the backup API and are reopened with `PRAGMA quick_check`; archives are
   not copied into a live agent database as a substitute for supported
   remote-task handoff.

The source snapshot is mounted read-only for the current session. The
read-only mount must be checked again after host reboot. Recover into a
separate writable Git clone/worktree; the four verified examples are under
`recovery-test/`. Never overwrite an active server repository to test recovery.

The encrypted history format is AES-256-GCM over tar.gz with a per-file
SHA-256 manifest. The key is separate in a root-only store. Use the private
`verify-history.py` with the archive, key path and an isolated restore
directory; it authenticates the entire archive, checks every entry and
reopens the SQLite snapshots. Preserve the base archive together with its
delta; existing older archives remain available.

The copied Docker Desktop disk was mounted ext4 with `ro,noload`, read,
unmounted and detached. This proves filesystem access; it does not claim
that every historical application volume was booted or its database tested.
The Mac Docker disk is outside the current deletion candidate list.

Before deleting a named candidate, repeat its source fence if anything has
written there since the recorded acceptance. Use the remote saved projects
for new Codex development tasks. The calling local task cannot hand itself
off; archived history is not an active remote task.
