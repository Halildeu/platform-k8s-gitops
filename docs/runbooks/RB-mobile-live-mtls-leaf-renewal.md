# TEST live-analysis expired leaf recovery

Tracked by #3440 and platform-mobile#8. Agent-initiated under Zeynep's instruction
to verify and continue the independent mobile work; not independent human approval.

## Evidence and scope

- Run35823107425: public mobile SSE HTTP200, 12 heartbeats, zero analyses before EOF.
- Run35823384610: same meeting live requests fail before HTTP in 39-43ms.
- Run35824331148: TCP reaches 8243/8244, curl60/OpenSSL10, verified TLS rejects expiry.
- Run35824822012: Caddy leaf `C:\caddy\certs\server.crt`, SHA256
  `5b7039cb5514ff88eafe6afebdda484b9580a6ea5288a5fdce3157a5a1ed0a23`,
  expired 2026-09-20T19:27:29Z. Both listeners are present.
- Run35825128525: mounted client is valid until 2026-10-21T11:42:41Z; CA until
  2027-06-22T19:27:29Z. The GPU's obsolete client copy is not the installed gateway
  credential. No client/Vault/ESO update is needed for this leaf recovery.

Only this TEST leaf is renewed, retaining its CA, public/private key and exact
subject/SANs, with the same 90-day validity policy. CA and keys stay on GPU host.
No production overlay, permissions, model, STT or Meeting-AI service changes.

## Procedure and rollback

`faz24-test-live-mtls-renewal.yml` defaults to apply=false. It uses the existing
governed denetim-pc SSH alias and pinned host key. The fixed target and observed
CA/leaf fingerprints are validated; unexpected replacement is refused.

1. Dry-run creates only public CSR/proposal files. OpenSSL verifies CA chain,
   server purpose and hostname. Public key, subject and SAN equality are checked.
2. Apply additionally refuses active 8243/8244 connections or unexpected Caddy
   task state. It preserves the file ACL, saves the old public certificate and
   atomically replaces the leaf. It validates Caddy config before reload.
3. Caddy admin API is disabled and stays disabled. Restart only existing
   `CaddyI7AppMtls`; leave the duplicate task, task settings, network and identity
   untouched. This briefly interrupts only the currently unusable mTLS bridge.
4. If replacement/config/reload fails after mutation, restore the saved leaf and
   reload the same task; report rollback status. No raw native output is exported.
5. From the actual TEST gateway verify both health probes with current mounted
   credentials: curl0, SSL verification0, HTTP200. A failed external check is a
   failed recovery, not product success: inspect and restore the saved public
   `previous-server.crt` at the reported proposalDirectory if the renewal caused
   the regression. Never restore a different identity or disable TLS checking.
6. Run public recorder plus live SSE acceptance again. Require real decisions and
   actions before EOF, then saved-result acceptance. Physical phone acceptance
   remains separate.

The old leaf is already expired: rollback restores prior state, not working TLS.
Automated renewal/expiry alerting for both server and client remains tracked in
#3440; this one-shot repair does not assert unattended future rotation.

## Local proof

`scripts/test/test_test_live_mtls_renewal_windows.py` uses generated synthetic
certificates in an isolated directory. It exercises real OpenSSL signing and
identity preservation, refuses a mismatched source fingerprint, and injects a
restart failure after real atomic file replacement to prove backup restoration.
No real scheduled task is touched by these tests. SSH metadata tests separately
reject wrong hosts/missing host-key pins and suppress raw remote failures.
