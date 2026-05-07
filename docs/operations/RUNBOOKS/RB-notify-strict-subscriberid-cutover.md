# RB-notify-strict-subscriberid-cutover

> Faz 24 / PR-4 — strict-mode flip of `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS` from the legacy-compatible default `subscriberId,userId,sub` to canonical-only `subscriberId` (Codex thread `019e0400` AGREE iter-1, scope = "A only, sequential").

## Tetik

PR-1 / PR-2 / PR-3 are merged and live:

| PR | Repo | Effect |
|---|---|---|
| PR-1 (`0afa3aa`) | platform-backend | `SubscriberIdentityGuard` config-driven; metric `notify.subscriber.identity.match{claim=...}` instrumented |
| PR-2 (PR #391) | platform-k8s-gitops | Keycloak realm protocol mapper emits `subscriberId` claim from `attributes.subscriberId` |
| PR-3 (PR #303) | platform-web | mfe-shell `mapKeycloakProfile()` reads JWT `subscriberId` claim into `UserProfile`; selector + reducer pipeline carries it to `X-Subscriber-Id` header |

This runbook closes the loop with a one-line GitOps env override that drops the legacy `userId,sub` fallback, plus a rolling restart of `notification-orchestrator`.

## Karar matrisi (Codex iter-1 AGREE özet)

| Soru | Karar |
|---|---|
| PR-4 scope | A only — subscriberId strict flip (Org strict tenancy = ayrı PR-5 / Faz 24 iter-2) |
| Cutover sırası | FE/claim producers first (PR-3 + KC mapper + backfill), backend strict last |
| Metric gating (pre-prod) | 2-4 saat OR full smoke evidence |
| Metric gating (prod) | 24-48 saat (max token TTL + FE cache propagation + bir normal kullanım döngüsü) |
| Rollback | Env back to `subscriberId,userId,sub` + rolling restart |

## Adımlar

### F1 — PR-3 live verification (30 dk)

| | |
|---|---|
| **Giriş şartı** | `platform-web` PR-3 merged + mfe-shell image rebuild done + cluster overlay digest pinned |
| **Komut** | `kubectl --context k3d-<env> -n platform-<env> get pods -l app=mfe-shell -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'` |
| **Beklenen** | Pod imageID matches the new GHCR digest from PR-3's build |
| **Fail sinyali** | Old digest still serving → rollout did not propagate; check `kubectl describe deploy/mfe-shell` for image pull / config issues |
| **Devam eşiği** | Pod imageID == GHCR digest from PR-3 |
| **Rollback** | None — verification step, no mutation |

### F2 — Fresh login token claim verification (5 dk)

| | |
|---|---|
| **Komut** | `bash scripts/keycloak/validate-subscriber-id-claim.sh` (PR-2's validator) against the post-PR-3 cluster |
| **Beklenen** | `{ subscriberIdPresent: true, subscriberIdMatchesExpected: true, claimType: "string" }` |
| **Fail sinyali** | `subscriberIdPresent: false` → realm mapper not deployed OR persona attribute missing. Re-check PR-2 phase F2/F3. |
| **Devam eşiği** | Validator green on the dedicated test persona AND a real login user (manually decode their token) |
| **Rollback** | None — verification step |

### F3 — Backend metric observation gate (2-4h pre-prod / 24-48h prod)

| | |
|---|---|
| **PromQL probe** | See "Metric queries" section below |
| **Beklenen** | `legacy_increase_24h == 0` AND `canonical_increase_24h > 0` AND `none_increase_24h == 0` |
| **Fail sinyali** | Non-zero `none` → some JWTs in flight have neither canonical nor legacy claim; this WILL 403 under strict. Investigate which user/session produced the `none` match. Non-zero `userId/sub` → some clients (FE bundle? other service?) are still sending legacy claims; chase down before flip. |
| **Devam eşiği** | Pre-prod: gate green for 2-4 contiguous hours OR full notification user-path smoke evidence. Prod: gate green for 24h minimum, 48h preferred. |
| **Rollback** | None — observation step |

### F4 — GitOps env override (5 dk)

| | |
|---|---|
| **Komut (test cluster first)** | Patch `kustomize/base/apps/notification-orchestrator/configmap.yaml` (or test overlay configmap.yaml) to add `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS: "subscriberId"`. Selective apply: `kubectl --context k3d-test -n platform-test apply -f kustomize/base/apps/notification-orchestrator/configmap.yaml` |
| **Beklenen** | `kubectl get configmap notification-orchestrator-config -o yaml \| grep SUBSCRIBER_IDENTITY` shows `"subscriberId"` |
| **Fail sinyali** | Apply errors → check kustomize build sanity first (`kubectl kustomize kustomize/overlays/test`); ConfigMap missing key → check the configmap file, not the apply call |
| **Devam eşiği** | ConfigMap reflects new value AND F5 rolling restart picked it up |
| **Rollback** | Patch the file back to remove the env var (default reverts to legacy-compatible application.yml value) + rolling restart |

### F5 — Rolling restart + post-flip smoke (10 dk)

| | |
|---|---|
| **Komut** | `kubectl --context k3d-<env> -n platform-<env> rollout restart deploy/notification-orchestrator` then `kubectl rollout status deploy/notification-orchestrator -w` |
| **Beklenen** | All pods Running with new ConfigMap mounted; pod environment shows `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS=subscriberId` (verify via `kubectl exec`) |
| **Smoke** | Hit `GET /api/v1/notify/inbox/me` with a fresh-login JWT → 200 OK; same call with a hand-crafted JWT missing the `subscriberId` claim → 403; metric `notify_subscriber_identity_match_total{claim="subscriberId"}` increments; `claim=~"userId\|sub\|none"` does NOT increment after the restart timestamp |
| **Fail sinyali** | 403 on legitimate fresh-login session → either the realm mapper regressed or the token in flight is too old (TTL not expired); check `kubectl logs deploy/notification-orchestrator \| grep "subscriber identity"` for the rejection reason |
| **Devam eşiği** | Smoke 200/403 split is correct AND metric trend is canonical-only |
| **Rollback** | Revert F4 ConfigMap patch + rolling restart again. Both backend and FE continue to function on legacy claims because PR-3 left the fallback chain in place. |

### F6 — Prod cutover (same flow against prod cluster)

Repeat F1–F5 on `k3d-prod` / `platform-prod` after pre-prod gate is closed for at least 24h.

## Metric queries

Backend Prometheus probes (PR-1 instrumented `notify.subscriber.identity.match` counter with `{claim=subscriberId|userId|sub|none}` label).

```promql
# F3 main gates
legacy_increase_24h:    sum(increase(notify_subscriber_identity_match_total{claim=~"userId|sub|none"}[24h]))
canonical_increase_24h: sum(increase(notify_subscriber_identity_match_total{claim="subscriberId"}[24h]))
none_increase_24h:      sum(increase(notify_subscriber_identity_match_total{claim="none"}[24h]))

# Per-claim breakdown for debugging
sum by (claim) (increase(notify_subscriber_identity_match_total[1h]))
```

Strict-flip readiness condition (combined):

```promql
legacy_increase_24h == 0 AND canonical_increase_24h > 0 AND none_increase_24h == 0
```

## HARD RULE notes

* **Pre-prod authority** (HARD RULE): the agent can run F1–F5 against the pre-prod cluster end-to-end (selective apply, rolling restart, smoke evidence) and report. Prod cutover (F6) is still an explicit operator decision because the metric observation window is the only defense against a botched flip 403'ing live browser sessions.
* **No `--admin` merge** (HARD RULE): the GitOps PR carrying F4's ConfigMap patch goes through normal CI gates. If CI is red, fix the underlying issue rather than bypassing.
* **Cross-AI peer review** (HARD RULE): the GitOps PR for F4 needs Codex post-impl review before merge.

## Out of scope (Codex iter-1 PARTIAL)

This runbook covers ONLY **A: subscriberId strict flip**.

**B: Org strict tenancy** (FE `DEFAULT_ORG_ID = 'default'` removal + `NotifyOrgAccessGuard` default fallback close + Keycloak `org_id` mapper) is tracked separately as **Faz 24 / PR-5**. Per Codex's analysis combining A+B in the same cutover would conflate 403 failure modes — keep them sequential so the metric signal stays attributable.

## Referans

* Codex thread: `019e0400` AGREE iter-1 (scope split + cutover sequence + gating windows)
* PR-1 backend: notification-orchestrator `0afa3aa`
* PR-2 ops: platform-k8s-gitops PR #391 + `RB-keycloak-subscriberId-migration.md`
* PR-3 frontend: platform-web PR #303
* PR-5 backlog: Faz 24 Org Strict Tenancy iter-1 plan (separate runbook + separate Codex thread)
