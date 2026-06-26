# RB-faz22.6-548-vault-https-enablement — test Vault HTTPS listener for #548 device-cert issuance

> **Tetik:** Faz 22.6 #548 `/attest` step needs the endpoint-admin-service `VaultPkiClient` to issue the
> TPM device leaf cert (→ the V74 binding row → §3.1 → device-key session). The backend `VaultPkiProperties`
> **fail-fasts at startup unless `endpoint-admin.tpm-attest.vault.base-url` is `https://` with a pinned CA**,
> but the test Vault (`platform-vault-test`) currently serves **HTTP only** (`config.hcl` single
> `tls_disable=true` listener). This runbook stands up an **additive** HTTPS listener so the in-cluster
> backend can reach Vault over TLS — **without touching** the existing `:8200` HTTP plane (host nginx + ESO
> ClusterSecretStore + every other consumer).
>
> **Cross-AI note:** Codex (thread 019efd6b) directed "Vault server-cert + pinned-CA, NOT a proxy" — this
> runbook follows that (real TLS on the Vault listener, backend pins the internal CA). Author: Claude.
>
> **Owner/operator-gated:** touches the shared, 2-month-stable test Vault. Apply only after the companion
> `config.hcl` change is merged AND a live `/nonce` confirms the chain reaches the `/attest` Vault layer.

## 1. AMAÇ
Unblock the `/attest` Vault PKI leg of #548 on the test cluster by giving `platform-vault-test` a TLS
listener the backend can pin, so `/attest` issues the device leaf cert and writes the V74 binding row.
**Out of scope:** the PKI mount/role/AppRole themselves — see `RB-faz22-3b-vault-pki-setup.md` (this runbook
is strictly the HTTP→HTTPS transport enablement that RB-faz22-3b assumes already exists).

## 2. KAPSAM
- ADD a 2nd `listener "tcp"` on `:8202` (TLS) to `host-compose/vault/test/config/config.hcl` — **merged in
  the companion PR**; this runbook is the host-side activation.
- Generate an internal-CA server cert host-side (`host-compose/vault/test/tls/gen-vault-test-tls.sh`).
- Expose `:8202` from the container + the in-cluster `vault` Service (mirror the existing `:8200` path).
- Point the backend at `https://vault.platform-test.svc.cluster.local:8202` + pin the CA PEM.
- The `:8200` HTTP listener, nginx SSL-termination, and ESO ClusterSecretStore are **UNCHANGED** throughout.

## 3. ÖNKOŞULLAR (operator)
- Host shell on staging-sw (`ssh halil@staging-sw`), docker control of `platform-vault-test`.
- Companion `config.hcl` PR (the `:8202` listener) merged to gitops main.
- `openssl` on the host (for `gen-vault-test-tls.sh`).
- `RB-faz22-3b-vault-pki-setup.md` PKI mount + `tpm-device` role + backend AppRole already provisioned
  (the HTTPS transport is necessary but not sufficient — the PKI engine must exist for issuance).

## 4. ADIMLAR

### 4.1 Generate the TLS material (host-side; ~30s; key never leaves the host)
```bash
ssh halil@staging-sw
cd /home/halil/platform-k8s-gitops/host-compose/vault/test/tls
bash gen-vault-test-tls.sh
# Beklenen: vault-test-{ca,server}.{crt,key} in ../config/tls/ ; SAN lists
#   vault.platform-test.svc.cluster.local, platform-vault-test, localhost, 127.0.0.1
# Fail sinyali: openssl error / missing SAN → do NOT restart Vault (it would serve a wrong-SAN cert)
```
> Devam eşiği: `../config/tls/vault-test-server.crt` exists and `openssl x509 -in … -ext subjectAltName`
> lists `vault.platform-test.svc.cluster.local`.

### 4.2 Reach `:8202` from the cluster — NO host-publish needed
The in-cluster `vault` Service resolves to the container's **docker-bridge IP** via a manual Endpoints
object (test overlay patches it to `172.19.0.4:8200` — the platform-vault-test bridge IP + *container*
port, NOT a published host port). So pods reach the container port directly; `:8202` needs **no docker
host-publish** — only the container listening on 8202 (config.hcl).

**Transport-reach is COMMITTED in this PR (#2054) as durable desired-state — already merged, no action:**
```
#   (a) test overlay `vault` Service: 2nd port { name: https, port: 8202, targetPort: 8202 }   ✅ committed
#   (b) test overlay `vault` Endpoints: add { name: https, port: 8202 } on the 172.19.0.4 subset ✅ committed
#   (c) NARROW NetworkPolicy allow-egress-endpoint-admin-vault-https: endpoint-admin-service →
#       172.19.0.4/32 TCP 8202 only (base 0.0.0.0/0 allowlist NOT widened)                       ✅ committed
# Confirm the live bridge IP still matches before activation:
#   kubectl --context k3d-test -n platform-test get endpoints vault -o yaml   (expect 172.19.0.4)
```
> The backend config flip — base-url + raw-PEM caCertPem + AppRole roleId/secretId — is **NOT** in this
> PR (it is activation-time secret/config; see §4.4). This foundation PR only prepares the listener +
> reachability; it does not half-flip the backend.

> Devam eşiği: after `kubectl apply -k overlays/test` (or the sync), a backend pod resolves
> `vault.platform-test.svc.cluster.local:8202` and the egress NetPol permits it. **Do not proceed if
> only :8200 is reachable / NetPol blocks 8202.**

### 4.3 PREFLIGHT (hard, fail-closed) then restart `platform-vault-test`
```bash
# PREFLIGHT — Vault REFUSES to start without a readable cert; a blind restart/reboot with the cert
# absent or unreadable takes the test Vault DOWN (Codex 019f02db Must-Fix #5). Run ALL before restart:
test -r host-compose/vault/test/config/tls/vault-test-server.crt || { echo "MISSING server cert — run 4.1"; exit 1; }
test -r host-compose/vault/test/config/tls/vault-test-server.key || { echo "MISSING server key — run 4.1"; exit 1; }
docker exec platform-vault-test test -r /vault/config/tls/vault-test-server.key \
  || { echo "Vault UID cannot READ the key over :ro mount — chown to 'docker exec platform-vault-test id' UID"; exit 1; }
openssl x509 -in host-compose/vault/test/config/tls/vault-test-server.crt -noout -checkend 0 \
  || { echo "server cert expired — regen 4.1"; exit 1; }

docker restart platform-vault-test
sleep 5
docker logs platform-vault-test 2>&1 | tail -30 | grep -iE "listener|tls|vault is unsealed|error"
docker exec platform-vault-test sh -c "ss -ltn 2>/dev/null || netstat -ltn" | grep -E ':8200|:8201|:8202|:8203'
# Beklenen: listeners on :8200 (HTTP) + :8202 (TLS) + :8201 (raft cluster). NOTE the 2nd TCP listener
# may auto-open a cluster port :8203 (Vault default address+1) — confirm it is INTERNAL only; if it
# surfaces unexpectedly, pin/disable it. No TLS-cert load errors. Vault re-unseals as before (Raft).
# Fail sinyali: "open /vault/config/tls/...: no such file" → 4.1 not done; "error loading TLS cert" →
#   regen 4.1. If Vault won't start, revert (§6) IMMEDIATELY (the :8200 HTTP plane must stay up).
```
> Devam eşiği: `docker exec platform-vault-test vault status` → Initialized=true, Sealed=false; AND
> `curl --cacert <ca> https://<bridge-ip>:8202/v1/sys/health` returns JSON over TLS; AND `:8200`
> HTTP health still 200 (ESO/nginx untouched). The SAN must exact-match the backend base-url host
> (`vault.platform-test.svc.cluster.local`) — a short-name base-url (`vault`, `vault.platform-test`)
> would fail SAN validation unless added to the cert in 4.1.

### 4.4 Pin the CA + flip the backend to HTTPS  (activation — NOT in PR #2054)
```bash
# caCertPem is RAW PEM, NOT base64 (Codex 019f02db re-review #2): the backend asserts the property value
# contains "BEGIN CERTIFICATE" (VaultPkiProperties). If you write base64 to the Vault KV value the pod
# FAIL-FASTS. Put the RAW PEM of the CA *public* cert (NOT the server cert, NOT any private key):
#   vault kv patch kv/platform/endpoint-admin-service \
#     tpm_vault_ca_cert_pem="$(cat host-compose/vault/test/tls/ca/vault-test-ca.crt)" \
#     tpm_vault_base_url="https://vault.platform-test.svc.cluster.local:8202" \
#     tpm_vault_role_id="<approle role-id, RB-faz22-3b>" tpm_vault_secret_id="<approle secret-id>"
# The K8s Secret .data layer base64-encodes for transport — that is NOT the property value; Spring
# decodes it back to raw PEM in the env var. Then EXTEND the endpoint-admin ExternalSecret (it does NOT
# carry these keys today — that addition is an ACTIVATION-PR concern, not this foundation PR) to map:
#   ENDPOINT_ADMIN_TPM_ATTEST_VAULT_BASE_URL    <- tpm_vault_base_url
#   ENDPOINT_ADMIN_TPM_ATTEST_VAULT_CA_CERT_PEM <- tpm_vault_ca_cert_pem   (raw PEM)
#   ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID / _SECRET_ID  <- tpm_vault_role_id / _secret_id
# (Spring relaxed binding of prefix endpoint-admin.tpm-attest.vault.{base-url,ca-cert-pem,role-id,secret-id}.)
# Then rollout:
kubectl --context k3d-test -n platform-test rollout restart deploy/endpoint-admin-service
kubectl --context k3d-test -n platform-test rollout status deploy/endpoint-admin-service --timeout=300s
```
> Devam eşiği: pod reaches Ready (no `VaultPkiProperties` fail-fast in logs — previously the startup guard
> rejected non-HTTPS/missing-CA).

## 5. DOĞRULAMA
- **Startup:** `kubectl logs deploy/endpoint-admin-service | grep -iE "VaultPki|vault.*base-url"` — no
  fail-fast; the client initialized against `https://…:8202`.
- **TLS pin:** from a backend pod, the Vault TLS handshake validates against the pinned CA (a wrong/missing
  CA → handshake failure, which is the correct fail-closed).
- **Issuance reach:** a live `/attest` (the user-run TPM re-enroll, after `/nonce` succeeds) now reaches
  `VaultPkiClient.signCsr` instead of `FEATURE_DISABLED` → the V74 binding row is written. (Confirm the
  binding row per `RB-faz22.6-548-device-key-session-live-run.md` §2.)
- **No regression:** `:8200` HTTP still serves nginx + ESO (ESO ClusterSecretStore Ready=True unchanged).

## 6. ROLLBACK (HTTP plane stays up throughout — low blast radius)
1. Backend: revert `endpoint-admin.tpm-attest.vault.base-url` (disable tpm-attest Vault, or back to the
   pre-change value) + rollout restart. The startup guard then no longer requires HTTPS.
2. Service/container: remove the `:8202` publish (revert the host-compose change).
3. Vault: revert `config.hcl` to the single `:8200` listener + `docker restart platform-vault-test`.
   (Removing the TLS listener is safe — no consumer depends on `:8202` until 4.4 lands.)
4. The `:8200` HTTP listener, nginx, and ESO are untouched in every step → no broad-drift risk.

## 7. REFERANS
- Companion config change: `host-compose/vault/test/config/config.hcl` (`:8202` listener) + `tls/.gitignore`.
- Cert-gen: `host-compose/vault/test/tls/gen-vault-test-tls.sh`.
- PKI engine (mount/role/AppRole): `docs/runbooks/RB-faz22-3b-vault-pki-setup.md`.
- Live run (binding row §2, §3.1 leaf-SPKI, markers): `docs/runbooks/RB-faz22.6-548-device-key-session-live-run.md`.
- Codex thread 019efd6b (server-cert + pinned-CA, NOT proxy).
