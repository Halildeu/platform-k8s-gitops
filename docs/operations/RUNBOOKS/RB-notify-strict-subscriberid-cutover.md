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
| **Komut** (Codex iter-2 absorb — actual K8s labels: deployment is `frontend`, label is `app.kubernetes.io/name=frontend`) | <pre>kubectl --context k3d-<env> -n platform-<env> get pods \\<br/>  -l app.kubernetes.io/name=frontend \\<br/>  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.containerStatuses[?(@.name=="frontend")].imageID}{"\n"}{end}'<br/><br/>kubectl --context k3d-<env> -n platform-<env> get deploy/frontend \\<br/>  -o jsonpath='{.spec.template.spec.containers[?(@.name=="frontend")].image}'</pre> |
| **Beklenen** | Pod imageID matches the new GHCR digest from PR-3's build; deployment image pin shows the same digest |
| **Fail sinyali** | Old digest still serving → rollout did not propagate; check `kubectl describe deploy/frontend` for image pull / config issues |
| **Devam eşiği** | Pod imageID == GHCR digest from PR-3 AND deployment image pin matches |
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

> Codex iter-2 absorb: do **NOT** patch `kustomize/base/apps/notification-orchestrator/configmap.yaml` and `kubectl apply -f` it directly. The test/prod overlays patch the same ConfigMap with JWT issuer, JWKS URL, SMTP, tracing and other overlay-only values; a base-level direct apply would silently strip those values from the live ConfigMap and trigger a real outage. Test strict flip lives in the **test overlay only**; prod strict flip lives in the **prod overlay only**, applied at F6 after the prod gate is closed.

| | |
|---|---|
| **Komut (test cluster only — F6 mirrors with prod overlay)** | <pre>kubectl kustomize kustomize/overlays/test \\<br/>  \| yq 'select(.kind == "ConfigMap" and .metadata.name == "notification-orchestrator-config")' \\<br/>  \| kubectl --context k3d-test -n platform-test apply -f -</pre><br/>The kustomize render is what guarantees the overlay's other patches stay intact; the `yq` filter narrows the apply to a single ConfigMap so unrelated overlay resources are not collateral-mutated. Add the `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS: "subscriberId"` line in `kustomize/overlays/test/notification-orchestrator/configmap-patch.yaml` (create if missing) so the kustomize render emits the new value. |
| **Beklenen** | `kubectl get configmap notification-orchestrator-config -n platform-test -o yaml \| grep SUBSCRIBER_IDENTITY` shows `"subscriberId"` AND none of the overlay-only values (JWT issuer, JWKS, SMTP host, etc.) regressed |
| **Fail sinyali** | Apply errors → check `kubectl kustomize kustomize/overlays/test` build sanity first; overlay-only env vars missing post-apply → the `yq` filter dropped extra resources you needed; widen to all ConfigMaps the overlay produces. |
| **Devam eşiği** | ConfigMap reflects new value, all overlay env vars intact, AND F5 rolling restart picked it up |
| **Rollback** | Patch the overlay configmap-patch.yaml back to remove the env var (default reverts to legacy-compatible `application.yml` value) + rolling restart |

### F5 — Rolling restart + post-flip smoke (10 dk)

| | |
|---|---|
| **Komut** | `kubectl --context k3d-<env> -n platform-<env> rollout restart deploy/notification-orchestrator` then `kubectl rollout status deploy/notification-orchestrator -w` |
| **Beklenen** | All pods Running with new ConfigMap mounted; pod environment shows `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS=subscriberId` (verify via `kubectl exec`) |
| **Smoke** (Codex iter-2 absorb — distinguish 401 vs 403 paths) | Three explicit cases:<br/>• **canonical OK (200)**: fresh-login JWT carrying `subscriberId` claim → `GET /api/v1/notify/inbox/me` returns 200<br/>• **strict miss (403)**: a **valid Keycloak-signed** JWT that does NOT carry the `subscriberId` claim → 403. Sources for this token: a test persona whose `attributes.subscriberId` was never backfilled (controlled fixture), or a temporary client/scope that produces a signed token without the claim. **Do not** test with an unsigned/hand-crafted JWT — that path errors out at the resource-server layer with 401 and never reaches `SubscriberIdentityGuard`'s strict 403 branch.<br/>• **invalid token (401)**: any unsigned / wrong-signature JWT → 401 (resource-server reject).<br/>• Metric: `notify_subscriber_identity_match_total{claim="subscriberId"}` increments after the restart timestamp; `claim=~"userId\|sub\|none"` does NOT increment after the restart timestamp. |
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

## Out of scope (Codex iter-1 PARTIAL → 2026-05-08 Step B extension)

This runbook covered ONLY **A: subscriberId strict flip** at iter-1 time.

**B: Org strict tenancy** (FE `DEFAULT_ORG_ID = 'default'` removal +
`NotifyOrgAccessGuard` default fallback close + Keycloak `org_id` mapper)
went LIVE 2026-05-08 as Faz 23.6 PR-5.4 (default-org strict flip). Both A
and B share the same incident response patterns (denied counter storms,
match-counter source distribution drift, fail-close 403 spike). The
sections below extend this runbook to cover both guards.

## Strict cutover storm response (Step B alert absorb 2026-05-08)

Triggered by:
- `NotifyOrgAccessDeniedStorm` (severity=critical, page=true — single P1 source)
- `NotifySubscriberIdentityDeniedStorm` (severity=warning + `security_impact=critical` annotation, no P1 page — paired with above; bridge routes by severity, demoted to warning to avoid double P1)
- `NotifyOrgAccessSourceDefaultRegression` (warning — F3 gate sentinel)
- `NotifyOrgAccessSourceNoneRegression` (warning — pre-401/403 anomaly)
- `NotifyStrictCutoverTelemetryAbsent` (warning — silent-green guard)

### Incident triage (denied storm)

1. **Pair check**: are both Org + Subscriber denied alerts firing?
   - **Both** → upstream auth chain failure (filter chain not injecting JWT,
     auth-service down, Keycloak realm down). Check
     `kubectl logs deploy/api-gateway` for upstream JWT decode errors first.
   - **Only Org** → org_id resolve regression (Keycloak `org_id` mapper
     missing, ConfigMap env reverted, FE sending wrong header). Check
     guard logs `kubectl logs deploy/notification-orchestrator | grep
     OrgAccessDenied`.
   - **Only Subscriber** → subscriberId claim missing. Check Keycloak realm
     `subscriberId` mapper (PR-2 setup) + `attributes.subscriberId`
     populated for live users.

2. **Reason distribution**: query per-series counters to identify reason:
   ```bash
   kubectl --context k3d-prod -n platform-prod exec deploy/notification-orchestrator -- \
     wget -qO- localhost:8081/actuator/prometheus | \
     grep -E "notify_(org_access|subscriber_identity)_denied_total"
   ```
   Reasons:
   - `no_auth` — SecurityContextHolder empty (filter chain broken)
   - `non_jwt` — anonymous / username-password principal hitting guard
   - `missing_org_id` (Org only) — claim chain returned null
   - `mismatch_org_id` (Org only) — caller-supplied org_id ≠ resolved
   - `cross_org_lookup_attempt` (Org only) — repo lookup with denied org

3. **Quick rollback path** (if regression suspected):

   PR-5.5 strict subscriberId rollback:
   ```bash
   # Edit overlay configmap patch
   # File: kustomize/overlays/{test,prod}/kustomization.yaml
   # Find the notification-orchestrator-config patch block, change:
   #   NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT: "true"
   # to:
   #   NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT: "false"

   # Selective apply + rolling restart (D17 koruma — full overlay apply YASAK):
   kubectl kustomize kustomize/overlays/{env} \
     | yq 'select(.kind == "ConfigMap" and .metadata.name == "notification-orchestrator-config")' \
     | kubectl --context k3d-{env} -n platform-{env} apply -f -

   kubectl --context k3d-{env} -n platform-{env} rollout restart deploy/notification-orchestrator

   # Verify env reverted:
   kubectl --context k3d-{env} -n platform-{env} exec deploy/notification-orchestrator -- \
     env | grep NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT
   ```

   PR-5.4 default-org close rollback:
   ```bash
   # Same pattern, different env var:
   #   NOTIFY_SECURITY_DEFAULT_ORG_ID: ""           (current strict)
   # to:
   #   NOTIFY_SECURITY_DEFAULT_ORG_ID: "default"    (legacy fallback)

   # Apply via the same kustomize | yq | kubectl apply chain above.
   ```

   Both rollbacks restore the legacy "silent pass" / fallback paths the
   FE / auth-service stack worked under before Faz 23.6. Pods retain
   existing in-flight requests; new requests after rolling restart use
   the legacy behaviour. PRs to revert the overlay env in git follow
   immediately afterwards (cross-AI peer review HARD RULE applies even
   for revert PRs).

### F3 gate regression response (source default/none)

**source="default" non-zero**: F3 cutover gate was supposed to be 0 post-PR-5.4.
Check:
1. Has the env override been reverted? `kubectl -n platform-{env} get configmap
   notification-orchestrator-config -o yaml | grep DEFAULT_ORG_ID`
2. If env is correct but the counter still emits, the org_id resolve chain
   regressed somewhere upstream — check auth-service JWT enrichment via
   `kubectl logs deploy/auth-service | grep -i "org_id"`.

**source="none" non-zero**: indicates a request reached the guard with no
resolvable org id (no claim, no tenant, no allowed_orgs). Almost always
a multi-tenant onboarding gap:
1. Is the user a new tenant? Their JWT may not carry the `org_id` claim
   if Keycloak realm mapper isn't extended for them.
2. If sustained from a known-good user, see "denied storm" above.

### Telemetry absent response

`NotifyStrictCutoverTelemetryAbsent` fires when ServiceMonitor stops
seeing the target. This means denied-storm alerts above are silently
zero. Check:
1. ServiceMonitor selector: `kubectl get servicemonitor -A | grep notification`
2. Service endpoints: `kubectl -n platform-{env} get endpoints
   notification-orchestrator` — must list `<podIP>:8081`.
3. Prometheus scrape config render: see `kubectl -n monitoring exec
   prometheus-... -c prometheus -- cat /etc/prometheus/config_out/prometheus.env.yaml`
   and grep for `notification-orchestrator`.

## Referans

* Codex thread: `019e0400` AGREE iter-1 (scope split + cutover sequence + gating windows)
* PR-1 backend: notification-orchestrator `0afa3aa`
* PR-2 ops: platform-k8s-gitops PR #391 + `RB-keycloak-subscriberId-migration.md`
* PR-3 frontend: platform-web PR #303
* PR-5 backlog: Faz 24 Org Strict Tenancy iter-1 plan (separate runbook + separate Codex thread)
