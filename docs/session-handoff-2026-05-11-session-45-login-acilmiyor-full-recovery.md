# Session 45 Handoff — 2026-05-11

> **Topic**: `testai.acik.com` login açılmıyor full-stack fix + PG data-loss incident + cluster recovery
>
> **Format**: D28 5-area (Bağlam / İddia / İspatlar / İspatlamaz / Bilinen Boşluk)
>
> **Cross-AI peer review chain**: Codex threads `019e142d`, `019e1457`, `019e153d`, `019e15dd`, `019e1612` — all AGREE.

## 1. Bağlam

User-reported symptom on `testai.acik.com`: clicking "Güvenli Kurumsal Giriş" → KC SSO form → submit credentials → 302 back to SPA → **SPA stays on `/login`, no error toast** → user reads as "açılmıyor".

Previous Session 44 had partially diagnosed this (multiple hot-fix PRs already merged: PR #381 P0/P1 login flow fixes, PR #383 stale-bundle recovery, PR #152 vault-failfast narrow trigger, PR #148 gateway Set-Cookie, etc.) but the actual user-visible flow still didn't work end-to-end.

This session (45):
- Initial hypothesis was KC config (`KC_PROXY=edge` deprecated in KC 26) → CORS preflight on `/token` was 403. Fixed via PR #512.
- Playwright headless E2E from this machine exposed a second, deeper bug in `mfe-shell/auth-sync.ts`: `subscribeAuthState` replayed self-broadcast cached payload to late subscribers, firing `setAuthInitialized(true)` before `kc.init()` processed the URL fragment. Fixed via PR #390.
- 5 follow-up PRs absorbed Codex peer-review feedback (unit tests, comment cleanup, LAN bind hardening, docs).
- Mid-session: a LAN-bind hardening PR (#519) `force-recreate`d test PG. The host bind-mount path in YAML (`/srv/platform/stateful/test/postgres`) was created fresh by Docker because the previous container had been running off a different path (`/home/halil/platform-stateful/test/postgres`). PG ran `initdb` into the empty new path → all test databases lost.
- Recovery via Codex Option D: cold rsync from `/home/halil/...` (intact 173 MB, clean shutdown state) to canonical `/srv/...` path. All databases restored.
- Cascade fixes: `openfga` PG user password align (pre-existing 34h drift, unrelated to today's incident), `endpoint-admin-service` pod-template label fix (missing `app.kubernetes.io/part-of: platform` → NetworkPolicy `allow-egress-*` didn't select pod → DNS blocked → JDBC failed).

End state: testai login green end-to-end, all 15 cluster pods healthy, zero crashloops. Codex thread `019e1612` AGREE on full recovery.

## 2. İddia (MERGED PR'lar bu oturumda)

| # | Repo | Title | Merge time (local) | Codex thread |
|---|---|---|---|---|
| 389 | platform-web | `chore(mfe-shell): inline-string diagnostic payload (PR #387 follow-up)` | 2026-05-11 01:39 | (continuation) |
| 390 | platform-web | `fix(mfe-shell): suppress self-broadcast replay in subscribeAuthState` | 2026-05-11 03:08 | 019e1457 |
| 391 | platform-web | `test(mfe-shell): unit tests for auth-sync subscribeAuthState sourceId guard` | 2026-05-11 07:25 | 019e153d |
| 512 | platform-k8s-gitops | `fix(kc): KC_PROXY=edge → KC_PROXY_HEADERS=xforwarded (login açılmıyor root cause)` | 2026-05-11 02:39 | 019e142d |
| 516 | platform-k8s-gitops | `chore(overlay-test): bump frontend to sha-d3ef67e (login açılmıyor real fix LIVE on testai)` | 2026-05-11 03:23 | (deployment artifact) |
| 517 | platform-k8s-gitops | `chore(kc-test): drop unused 10.9.10.53:8082 LAN bind + runbook canonical edge path` | 2026-05-11 10:25 | 019e15dd |
| 519 | platform-k8s-gitops | `chore(pg-test): drop unused 10.9.10.53:5433 LAN bind + svc.yaml header truth` | 2026-05-11 10:35 | 019e15dd iter-3 |
| 520 | platform-k8s-gitops | `docs: fix stale host-bridge LAN refs after #517 + #519` | 2026-05-11 10:39 | (docs sweep) |

Plus LIVE cluster operations not in any PR (pre-prod authority, user explicit):
- KC test compose recreated multiple times with new env (`KC_PROXY_HEADERS=xforwarded`, `KC_HOSTNAME=https://testai.acik.com`, no deprecated `KC_HOSTNAME_STRICT_HTTPS`)
- KC prod compose recreated with same env (`KC_HOSTNAME=https://ai.acik.com`)
- Test PG data recovery via cold rsync (Codex Option D)
- openfga PG user password `ALTER USER` (aligned to placeholder used by current cluster Secret)
- endpoint-admin-service Deployment patch: `spec.template.metadata.labels.app.kubernetes.io/part-of=platform` + `component=backend` added (was missing → blocked by NetworkPolicy default-deny-egress)
- platform-test realm restore via `/tmp/restore-platform-test-realm.sh` (kcadm: frontend client PKCE, admin@example.com user) — used as bridge while PG was wiped, superseded by full PG restore

## 3. İspatlar (LIVE state, captured 2026-05-11 ~11:30 local)

### Cluster pod state (k3d-test, namespace `platform-test`)

```
NAME                                        READY   STATUS      RESTARTS   AGE
api-gateway-7dd69ff75c-99c69                1/1     Running     0          8h
auth-service-67f5d56d76-nw9r8               1/1     Running     0          42m
core-data-service-75f9d8db8c-tggx8          1/1     Running     0          42m
endpoint-admin-service-79748674b9-ff4zw     1/1     Running     0          90s
frontend-57858c5f56-brqwg                   1/1     Running     0          84m
mailpit-84f55d8c78-sjgqh                    1/1     Running     0          44h
notification-orchestrator-c958d5cdb-kq22k   1/1     Running     0          42m
openfga-0                                   1/1     Running     0          3m59s
openfga-migrate-2ggtl                       0/1     Completed   0          19d
permission-service-7dcbc7dbb7-sc9n6         1/1     Running     0          13m
report-service-f8dc4d758-l5st5              1/1     Running     0          8h
schema-service-5fd79b848b-xb9qv             1/1     Running     0          8h
user-service-5d56748c66-m6hjv               1/1     Running     0          42m
variant-service-7547f9868b-9j5xb            1/1     Running     0          13m
webhook-receiver-77579f67db-vxvb8           1/1     Running     0          44h
```

15/15 Running, 0 crashloops, 0 recent restarts.

### KC compose live env (both edges)

Test KC (`platform-kc-test`):
```
KC_HOSTNAME=https://testai.acik.com
KC_HOSTNAME_STRICT=false
KC_PROXY_HEADERS=xforwarded
KC_HTTP_ENABLED=true
KC_FEATURES=token-exchange,admin-fine-grained-authz:v1,authorization
```

Prod KC (`platform-kc-prod`):
```
KC_HOSTNAME=https://ai.acik.com
KC_HOSTNAME_STRICT=false
KC_PROXY_HEADERS=xforwarded
KC_HTTP_ENABLED=true
KC_FEATURES=token-exchange,admin-fine-grained-authz
```

No deprecated `KC_PROXY` or `KC_HOSTNAME_STRICT_HTTPS` on either.

### Host port binds (after #517 + #519 hardening)

```
ss -tlnp | grep ':808[12]\|:5433'
LISTEN 0  4096  127.0.0.1:8081  0.0.0.0:*    docker-proxy (platform-kc-prod)
LISTEN 0  4096  127.0.0.1:8082  0.0.0.0:*    docker-proxy (platform-kc-test)
LISTEN 0  4096  127.0.0.1:5433  0.0.0.0:*    docker-proxy (platform-pg-test)
```

All localhost-only. No more 10.9.10.53 LAN binds.

### CORS preflight (was 403 before #512, now 200)

```
$ curl -I -X OPTIONS \
    -H 'Origin: https://testai.acik.com' \
    -H 'Access-Control-Request-Method: POST' \
    https://testai.acik.com/realms/platform-test/protocol/openid-connect/token
HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://testai.acik.com
Access-Control-Allow-Methods: POST, OPTIONS
```

Same `200` on the prod edge (`ai.acik.com`).

### End-to-end Playwright headless smoke (RE-VERIFIED post-recovery)

```
PROBE earliest = https://testai.acik.com/#state=...&code=...
AuthBootstrapper: isLoginRoute=false  urlHasAuthCode=true  callbackExists=true

POST /realms/platform-test/.../token   = 200
POST /api/auth/cookie                   = 200
GET  /api/v1/authz/me                   = 200
FINAL_URL = https://testai.acik.com/    (root, NOT /login)
phase=transportReady                    (FSM full walk)
erp_access_token cookie present, Secure=true
```

### PG data integrity

```
$ kubectl -n platform-test get endpoints postgres
postgres   172.19.0.6:5432   19d

$ docker exec platform-pg-test psql -U postgres -l
auth_db, core_db, endpoint_admin, keycloak, notify_db, openfga,
permission_db, postgres, reports_db, schemas_db, template0, template1

$ docker exec platform-pg-test psql -U postgres -d keycloak -c "SELECT name FROM realm"
master, platform-test

$ docker exec platform-pg-test psql -U postgres -d reports_db -c "\\dn"
data_access, migration_audit, public, workcube_mikrolink, workcube_mssql_raw

$ docker exec platform-pg-test psql -U postgres -d reports_db -c "\\dt data_access.*"
data_access.organization, organization_company, scope, scope_outbox
```

### Frontend pod imageID

```
ghcr.io/halildeu/platform-web-frontend-testai@sha256:d40f7554a59b7880ac7c4f237a01edddd0f85f30abade446f8a8dc488fcfa875
```

Matches PR #516 pin exactly (no drift).

### Forensic snapshots preserved on staging-sw

- `/srv/platform/stateful/test/postgres.empty-incident-20260511T102820/` — the empty initdb'd dir from the incident, kept as forensic snapshot per Codex Option D guidance. Includes the post-incident state (KC manual realm restore + Flyway-applied auth_db/core_db schemas), small but useful for retrospective comparison.
- `/home/halil/platform-stateful/test/postgres/` — original pre-incident data, intact, NOT deleted after rsync. Future operators have a known-good fallback if `/srv/...` is ever corrupted again.

## 4. İspatlamaz

These are claims the session deliberately did NOT make:

- **Prod-side login flow is shipped.** Codex 019e15dd warned explicitly: prod frontend digest bump (PR #516 analog for `overlays/prod`) is a D30 cutover item, not done here. PR #516 only shipped `overlays/test`. The mfe-shell `auth-sync` fix exists in the prod-ready bundle (sha-d3ef67e) but the prod cluster's frontend Deployment digest pin still points at an older image (pre-#390). Prod login flow STILL HAS the original race condition until prod overlay digest bump merges.
- **Prod PG / prod KC are mount-drift-safe.** Codex 019e1612 explicitly warned: prod PG container is running with a mount source that hasn't been audited. If anyone runs `docker compose --force-recreate` on prod PG before drift reconcile, prod PG will hit the SAME data-loss incident as test did today.
- **`endpoint-admin-service` Deployment label fix is gitops-canonical.** Today's fix is a `kubectl patch` on the live Deployment. The Kustomize base/overlay manifest in this repo still lacks the labels. Next ArgoCD reconcile will revert the patch and the pod will crashloop again with the same DNS error.
- **`openfga-secrets` is properly designed.** The Secret has both `OPENFGA_DATASTORE_URI` (with real password) and `OPENFGA_DATASTORE_PASSWORD` (with placeholder `change-me-local-only`); OpenFGA's config reader uses PASSWORD env to override URI password, which is why the placeholder is what PG must match. Today's fix aligned PG to the placeholder. Long-term Vault hygiene: drop the PASSWORD field entirely OR rotate the placeholder to a real value.
- **`docs/state/current-state.md` is up to date.** It still reflects the pre-Session-45 cluster state. A delta commit is appropriate but was deferred to keep this session's PR chain focused.
- **The bind-mount path drift was caught by any PR-time gate.** It wasn't. The drift snuck through 5 Codex AGREE reviews of compose changes because the smoke gates measured post-recreate health, not mount-source continuity. Codex 019e1612 §5 proposes a PR-time gate; it has not been implemented.

## 5. Bilinen Boşluk + P0 Aksiyon Listesi

### P0 — Next session must do FIRST (otherwise regressions next ArgoCD cycle)

1. **`endpoint-admin-service` Deployment manifest fix in gitops** ← **P0 highest**
   - Path: `kustomize/base/apps/endpoint-admin-service/deployment.yaml` (or wherever it's defined)
   - Add to `spec.template.metadata.labels`:
     ```yaml
     app.kubernetes.io/component: backend
     app.kubernetes.io/part-of: platform
     ```
   - PR through Codex peer review. Without this, ArgoCD reconciles the manifest, pod gets recreated with missing labels, NetworkPolicy `allow-egress-*` doesn't select it, DNS lookup of `postgres` fails, crash loop returns.

2. **Prod-side mount-source parity audit** (read-only, no recreate) ← **P0 to prevent prod data loss**
   ```bash
   # On staging-sw:
   docker inspect platform-pg-prod  --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{println}}{{end}}'
   docker inspect platform-kc-prod  --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{println}}{{end}}'
   docker inspect platform-vault-prod --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{println}}{{end}}'

   cd host-compose/postgres/prod  && docker compose config | grep -A 1 source
   cd host-compose/keycloak/prod  && docker compose config | grep -A 1 source
   cd host-compose/vault/prod     && docker compose config | grep -A 1 source
   ```
   Compare `docker inspect` Source vs `docker compose config` source. Each mismatch is a "force-recreate will wipe data" landmine.

   If drift found: cold migration plan (Codex Option D) in a planned maintenance window. **Until then: NO `docker compose --force-recreate` on any prod stateful container.**

### P1 — Sprint-bound

3. **PR-time stateful safety gate** (Codex 019e1612 §5)
   - CI gate triggered when `host-compose/{postgres,keycloak,vault,openfga}/**` files change
   - Compare `docker inspect Source` (via SSH to staging-sw) vs `docker compose config` rendered source
   - For PG: also verify `PG_VERSION` + `global/pg_control` exist at the declared source
   - Mismatch → CI fail with a "stateful mount-source drift detected; cold migration required before recreate" message
   - Source: scaffolded in `scripts/ci/stateful-mount-source-parity.sh`

4. **Prod frontend digest bump for auth-sync fix** (PR analog to #516, but for `overlays/prod`)
   - Same digest? No — prod is built from `overlays/prod` env vars (different KC URL, etc.). The image is `ghcr.io/halildeu/platform-web-frontend` (no `-testai` suffix) and gets built by the prod track of the platform-web image workflow.
   - Sequence: wait until prod frontend image with the auth-sync fix is built → bump `overlays/prod/kustomization.yaml` digest → Codex peer review → merge → ArgoCD apply.
   - D30 cutover gate dependency.

5. **`openfga-secrets` hygiene** in Vault
   - `kv/platform/openfga` currently has BOTH `db_uri` (with real password) and a separate password field that lands in cluster Secret as `OPENFGA_DATASTORE_PASSWORD=change-me-local-only`.
   - Option A: drop the password field; let URI carry the credential.
   - Option B: rotate placeholder to real password in Vault; ALTER PG user to match.
   - Either way: `kv/platform/openfga` rotation + ESO refresh + PG ALTER USER + openfga rollout restart.

### P2 — Longer-running

6. **`docs/state/current-state.md` delta commit** to reflect Session 45 changes:
   - Auth-sync fix shipped to test, pending prod
   - Stateful mount paths migrated from `/home/halil/platform-stateful/` to `/srv/platform/stateful/` (canonical per ADR-0002)
   - Forensic snapshot preserved at `/srv/.../postgres.empty-incident-20260511T102820/`
   - `openfga` and `endpoint-admin-service` PG/label fixes (live-patched, gitops-pending per P0/P1 above)

7. **`docs/runbooks/RB-openfga-schema-rev.md` rewrite** (Codex 019e15dd noted, deferred from PR #520)
   - Multiple commands reference `http://10.9.10.53:8081` as "OpenFGA URL" but OpenFGA is a k3d cluster pod, not host LAN
   - Rewrite commands to use `kubectl port-forward` or in-cluster Service paths

8. **`/home/halil/platform-stateful/` deprecation policy** — after a soak period (~1 week) of `/srv/...` being the canonical path:
   - Either delete `/home/halil/platform-stateful/` (final cleanup) — recommend after first prod-side migration confirms `/srv/...` works for prod too
   - Or keep as cold-backup snapshot tagged with date

## Yeni Session Açılışı

### İlk komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git rebase origin/main
cat docs/session-handoff-2026-05-11-session-45-login-acilmiyor-full-recovery.md
```

### İlk iş (P0 başla)

Düzeltilecek ilk dosya: `kustomize/base/apps/endpoint-admin-service/deployment.yaml` (path doğrula). PR title: `fix(endpoint-admin-service): add missing pod-template labels (NetworkPolicy egress selector)`. Codex peer-review zinciri (yeni thread).

Sonra P0 #2 prod-side mount audit (read-only).

## Codex thread referansları (tam zinciri korumak için)

- `019e142d` — KC compose KC_PROXY_HEADERS hotfix review (AGREE iter-1, iter-2)
- `019e1457` — mfe-shell auth-sync sourceId guard review (AGREE)
- `019e153d` — auth-sync unit tests PR review (AGREE)
- `019e15dd` — KC + PG LAN bind hardening review (AGREE iter-3)
- `019e1612` — PG data-loss incident root cause + Option D recovery (AGREE)

Hepsi read-only Codex sessions. Yeni session aynı kişiliği devam ettirmek isterse `codex-reply` ile thread ID'yi kullanır.

## Kapanış

Session 45 tamamlandı. `testai` login flow tam çalışır durumda, cluster sağlıklı. Prod-side promotion + governance hardening sıradaki session'a temiz handoff ile bırakıldı. Codex consensus chain (5 thread) audit'te kalır.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
