# endpoint-admin-remote-bridge — Faz 22.6 D10-8 broker isolation (desired-state)

The Faz 22.6 Remote Access Bridge broker, packaged for **§11/D10** pilot
acceptance. Topology decided by Codex (thread
`019ebc38-73d9-7332-a9d4-c9ac59c7dfa0`, **VERDICT A+**): a **separate
Deployment** running the **same `endpoint-admin-service` image** with the
remote-bridge broker enabled, while the **primary `endpoint-admin-service` stays
`remote-bridge.enabled=false`**. Co-location (NetworkPolicy-only, same pod) was
**rejected** for D10-8; a separate module/image is the production target, not a
pilot blocker.

## Desired-state boundary (this PR mutates nothing live)

| Layer | Location | State | Synced? |
|---|---|---|---|
| **Scaffold** (this dir) | `kustomize/base/apps/endpoint-admin-remote-bridge/` | `replicas:0` + `REMOTE_BRIDGE_ENABLED=false` → **inert** | **No** — not referenced by any overlay; not in the Argo root |
| **Activation** | `kustomize/overlays/test/activation/endpoint-admin-remote-bridge/` | `replicas:1` + `enabled=true` + immutable digest + real ExternalSecret + broker NetworkPolicies | **No** — NOT wired into `overlays/test/kustomization.yaml`; owner-gated |

Because neither path is in a synced kustomization, an `apply -k overlays/test`
(or ArgoCD reconcile) **cannot** start the broker. Flipping it live is a
deliberate `kubectl apply -k .../activation/...` the owner runs **after**
T-4a-ii broker beans + signer config land and the live smoke passes
(`docs/RB-22-6-remote-bridge-pilot-flip.md` §A3). Adding the scaffold to a synced
overlay still yields `replicas:0` / disabled — it can never bypass the owner gate.

Sanity build (no apply):
```
kubectl kustomize kustomize/base/apps/endpoint-admin-remote-bridge
kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge
```

## The 11 Codex isolation controls → where each lands

| # | Control | Realized in |
|---|---|---|
| 1 | Separate labels — **no** `part-of=platform` (would grant the broad intra-ns + host-bridge egress) | `kustomization.yaml` (only name-pair) + every manifest's labels |
| 2 | Separate ServiceAccount + `automountServiceAccountToken:false` + **no** Role/RoleBinding | `serviceaccount.yaml`, `deployment.yaml` |
| 3 | Separate Secret/Vault path — **not** `endpoint-admin-service-secrets` | `deployment.yaml` secretRef → `endpoint-admin-remote-bridge-secrets`; activation `externalsecret.yaml` → `kv/platform/endpoint-admin-remote-bridge` |
| 4 | Separate least-priv Postgres role; `FLYWAY_ENABLED=false` (migrations stay primary) | `configmap.yaml` (`SPRING_FLYWAY_ENABLED=false`, `ddl-auto=validate`); activation ESO delivers the broker DB role creds. **Config/env-first — no backend change**; see "Control #4 note" below |
| 5 | Service publishes **only 9444** (no 8096/8081) | `service.yaml`; `deployment.yaml` ports; activation netpol ingress-deny 8096/8081 (documented pilot waiver) |
| 6 | Ingress allowlist 9444 from orchestrator / mTLS-edge **only** | activation `netpol.yaml` (ingress) |
| 7 | Egress default-deny + explicit allow (DNS, JWKS, OpenFGA, scoped-PG, WORM, pilot devices) | namespace default-deny (base, already live) + activation `netpol.yaml` (egress) |
| 8 | Per-session egress ACL — pilot-min static 2–5 device allowlist (dynamic per-session deferred to prod) | activation `netpol.yaml` (`allow-egress-pilot-devices`) + app-layer token target/TTL check |
| 9 | No ambient admin creds — pod compromise yields no admin REST/JPA/DB-write/admin-JWT/cluster-token | controls #2 + #3 + #4 together (SA no token, broker secret no admin keys, DB role least-priv) |
| 10 | WORM append-only recording cred + object-lock/immutable + retention | activation ESO (`...-worm` key); pilot WORM = Postgres `DbRecordingSink` (V65 row+truncate triggers, append-only) — dedicated object-lock store is a production target |
| 11 | Fail-closed activation — `enabled=true` **only** on the broker Deployment; pod not-Ready if signer/verifier/cert/ACL missing | `replicas:0`+`enabled=false` here; activation patch flips both; T-2c refuses to bind without mTLS PEMs |

## Control #4 note (config-first, no backend change)

The broker boots the same Spring Boot app with `SPRING_FLYWAY_ENABLED=false` +
`SPRING_JPA_HIBERNATE_DDL_AUTO=validate`, so it never owns schema evolution and
never issues DDL. The activation ExternalSecret supplies a **least-privilege
Postgres role** (session / recording / ledger `SELECT/INSERT/UPDATE` only).

**Flag (honest):** Hibernate `validate` reads metadata for every mapped entity
at startup, so the least-priv role must still be able to *read* the catalog of
the tables the entity model maps. If, at activation smoke, the broker fails to
boot under the narrow role with config alone, the minimal backend follow-up is a
broker Spring profile that scopes the JPA entity scan to the broker's tables (or
`ddl-auto=none`). That is a **T-4a-ii backend slice**, explicitly out of this
gitops-only PR; the config-first path is attempted first per scope.

## Do NOT

- Do **not** add `app.kubernetes.io/part-of: platform` to any broker manifest.
- Do **not** add this base (or the activation overlay) to `overlays/test` /
  `overlays/prod` `resources:` without owner sign-off (ADR-0034 §13/D10).
- Do **not** point the broker at `endpoint-admin-service-secrets`.
- Do **not** create a Role/RoleBinding for the broker SA.
