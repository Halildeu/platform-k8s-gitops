# OWNER-APPROVAL — endpoint-admin-remote-bridge activation (Faz 22.6 D10-8)

> This overlay is the **runtime-activation** half of the broker isolation
> package. It is **NOT in the Argo root** and must never be wired into
> `kustomize/overlays/test/kustomization.yaml`. Applying it is a deliberate,
> owner-gated operator action — not an automated reconcile.

## Gate — do NOT apply until ALL of:

- [ ] **T-4a-ii merged** — broker `SessionContext` assembly + permit-signing-key
      fail-closed config landed as backend code (the broker beans the activation
      enables must exist).
- [ ] **Vault seeded** — `kv/platform/endpoint-admin-remote-bridge` carries the
      broker creds (least-priv DB role, broker mTLS leaf, device-CA, permit
      signing key, recording anchor key). See "Vault path" below.
- [ ] **PKI ready** — dual split-CA per RB §A1 (`rb-broker-ca` signs the broker
      server leaf; `rb-device-ca` signs pilot device client certs). Single-CA
      two-purpose is forbidden.
- [ ] **Owner sign-off** — ADR-0034 §13/D10 sign-off for the first live session
      (4-role: Veri Sorumlusu / Hukuk / İK / IT-Security).
- [ ] **Live exposure smoke planned** — RB-22-6-remote-bridge-pilot-flip.md §A4
      (Phase A D29-EA: Up / Functional-transport / Secured).

## Apply (after the gate)

```bash
# Vault seed (D43 stdin-pipe — values never hit shell history)
ssh halil@staging-sw "vault kv put kv/platform/endpoint-admin-remote-bridge \
  broker_db_username=@broker-db-user.txt broker_db_password=@broker-db-pass.txt \
  broker_tls_cert_chain_pem=@server-chain.pem broker_tls_private_key_pem=@server-key.pem \
  device_ca_pem=@rb-device-ca.pem permit_signing_key_pem=@permit-signing.key \
  recording_anchor_signing_key=@anchor.key openfga_store_id=@store.txt openfga_model_id=@model.txt"

# 1) Pin the REAL digest FIRST — kustomization.yaml images: must reference an
#    immutable endpoint-admin-service digest (same image, Codex A+). For #510
#    parent acceptance verification, #1697 catalog smoke, #1705
#    approved-script smoke, and #710 lifecycle close/reopen smoke, the active
#    digest includes platform-backend #696, #697, #698, #699, #701, #705,
#    #702, #710, #713, #717, and #724 via the #704/#706/#709/#711/#714/#718
#    remote-bridge image chain. The product path
#    keeps redacted PERMIT metadata, advisory AgentHello.deviceId handling,
#    bounded DENY metadata, bounded CRYPTO_IDENTITY deny.policyDetail
#    diagnostics, the operation-catalog gate, the approved-script catalog gate,
#    the explicit operator close path, and heartbeat peer-trust freshness needed
#    for the remote-bridge broker path, plus AgentPC2 constrained executor
#    terminal-output audit (`AGENT_OUTPUT` + `SESSION_END`) needed for #208/#1768:
#    sha256:fb229ff98a1b7afb3cc31fe6de49312192686ee3ff6f80952494892d19b23b0d.

# 2) Re-verify the PG/KC egress /32s in netpol.yaml against the current
#    Endpoints (they drift on compose recreate):
kubectl --context k3d-test -n platform-test get endpoints postgres keycloak

# 3) Build sanity (no apply)
kubectl kustomize kustomize/overlays/test/activation/endpoint-admin-remote-bridge

# 4) Apply (owner action)
kubectl --context k3d-test -n platform-test apply -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge
```

## Vault path — deliberate divergence from RB §A2 (validate at review)

RB §A2 (T-4 kickoff, interim) reused `kv/platform/endpoint-admin-service`. **This
overlay diverges to a SEPARATE path `kv/platform/endpoint-admin-remote-bridge`**
because Codex control #3/#9 require the broker secret to carry **none** of the
primary's Keycloak-admin / enrollment-pepper / command-encryption / broad-DB
material. A shared path would co-locate broker creds with admin secrets and
defeat the isolation. This supersedes the §A2 interim note.

## 11-control evidence checklist (fill at activation smoke)

| # | Control | Evidence to capture |
|---|---|---|
| 1 | no part-of=platform | `kubectl get pod -l app.kubernetes.io/name=endpoint-admin-remote-bridge -o jsonpath` shows no `part-of: platform`; broker matched by zero base allow-netpols |
| 2 | SA no token / no RBAC | pod has no mounted SA token; `kubectl auth can-i --as=system:serviceaccount:platform-test:endpoint-admin-remote-bridge ...` → no |
| 3 | separate secret path | broker env has no Keycloak-admin / pepper / command-encryption keys |
| 4 | least-priv DB role + flyway off | `psql` as broker role denied DDL/other-table; `SPRING_FLYWAY_ENABLED=false` in pod env |
| 5 | only 9444 | Service has one port (9444); 8096/8081 unreachable from the edge |
| 6 | ingress allowlist | 9444 reachable only via edge/orchestrator; other sources denied |
| 7 | egress default-deny + scoped | broker reaches DNS/OpenFGA/PG/KC only; arbitrary egress denied |
| 8 | per-session device ACL | egress to non-pilot device IP denied; pilot devices allowed |
| 9 | no ambient admin creds | broker pod cannot call admin REST / cannot get a cluster token |
| 10 | WORM recording | recording rows append-only (V65 triggers block UPDATE/DELETE/TRUNCATE) |
| 11 | fail-closed activation | remove signer secret → pod never Ready; enabled=true only here |

## Phase A negative reachability tests (Codex 019ebc51 P2 — control #5/#6)

The 8096/8081 close is a documented pilot waiver (the shared image still binds
them; only NetworkPolicy + the 9444-only Service isolate them). Kubelet probes
reach 8081 over the node→pod path the CNI permits outside NetworkPolicy, so that
same exemption could leave a node-origin reach un-governed. Prove the boundary
explicitly at Phase A — each must FAIL (connection refused / timeout):

- [ ] from a **same-namespace** pod (not the orchestrator): `nc -z -w3 endpoint-admin-remote-bridge 8096` and `8081` → fail
- [ ] from the **ingress-nginx** namespace → 8096/8081 → fail
- [ ] from the **host/node / edge** path → 8096/8081 → fail (only 31944→9444 reachable)
- [ ] 9444 reachable ONLY via the edge passthrough + the labelled orchestrator pod
- [ ] arbitrary egress (e.g. broker → a non-pilot IP:443) → fail; pilot device IP:443 → ok

If the node-origin 8096/8081 path is reachable, do NOT proceed to the first live
session — close admin HTTP via the T-4a-ii backend broker profile (or record an
explicit owner waiver).

## Rollback (≤5 min — RB §A5)

```bash
kubectl --context k3d-test -n platform-test delete -k \
  kustomize/overlays/test/activation/endpoint-admin-remote-bridge
# broker beans gone (enabled=false in the scaffold default); 9444 closed.
```
