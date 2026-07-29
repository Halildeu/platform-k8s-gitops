# Faz 24 TEST Analysis Capability Secret

## Scope

This runbook performs the first activation of the shared TEST-only HMAC trust root used by
`transcript-service` to issue and `meeting-service` to verify one short-lived
analysis-result capability. It does not authorize production activation and it
does not prove the attended Meeting Intelligence journey. It does not authorize
rotation of an already active key; the single-key application contract cannot
rotate without a bounded issuer/verifier mismatch window.

The canonical Vault location is:

```text
kv/platform/meeting-analysis-capability
  hmac_secret_base64
```

Two dedicated service-owned ExternalSecrets read this same remote property into
separate Kubernetes Secrets under the `ANALYSIS_JOB_CAPABILITY_HMAC_SECRET`
key. The capability ExternalSecrets are isolated from each service's unrelated
DB/Redis/OpenFGA/auth secret refresh. The raw value must not be copied to
another Vault path, passed in argv, printed, committed, or attached to evidence.

## Preconditions

1. The GitOps PR containing the exact Vault policies, ExternalSecrets, rollout
   markers, and static guards is merged to `main`.
2. Run from the canonical `main` checkout on `staging-sw`, where TEST Vault is
   reachable at `http://127.0.0.1:8201`.
3. The reconciler role-id and secret-id owner files described by
   `scripts/ops/vault-policy-reconcile.sh` are present with mode `0600`.
4. The owner-gated `vault-config-reconciler` policy has been refreshed once
   from `bootstrap/vault-policies/test/vault-config-reconciler.hcl` so the
   reconciler can manage the exact
   `meeting-analysis-capability-writer-test` policy name. If this capability is
   absent, stop; do not widen the reconciler to a wildcard policy path.
5. No direct `kubectl patch`, `set image`, `edit`, or ad-hoc Kubernetes Secret
   mutation is used for the shared TEST workloads.

## Policy Reconcile And First Seed

The reconciler applies only Git-reviewed policy content and emits one
short-lived bootstrap-writer secret-id. The generated 256-bit value is piped
directly into the property-restricted writer.

```bash
set -euo pipefail
umask 077

SID=/tmp/platform-bootstrap-writer-test-secret-id.txt
RID=/tmp/platform-bootstrap-writer-test-role-id.txt
cleanup() {
  shred -u "$SID" 2>/dev/null || true
}
trap cleanup EXIT

REPO_ROOT="$PWD" scripts/ops/vault-policy-reconcile.sh \
  --emit-seed-secret-id platform-bootstrap-writer-test

openssl rand -base64 32 |
  VAULT_BOOTSTRAP_ROLE_ID="$(cat "$RID")" \
  VAULT_BOOTSTRAP_SECRET_ID_FILE="$SID" \
  bash scripts/ops/platform-ops-vault-patch.sh \
    --vault-addr http://127.0.0.1:8201 \
    --service meeting-analysis-capability \
    --field-from-stdin hmac_secret_base64 \
    --create-only \
    --cleanup-secret-id-file
```

The writer uses KV v2 check-and-set, prints only the field name and resulting
version, and self-revokes. `--create-only` rejects an existing KV version so
this first-activation procedure cannot silently become an unsafe rotation. A
concurrent version change also fails closed.

## GitOps Rollout And Read-back

Seed before Argo reconciles the merged ExternalSecret change. Then verify
desired and live state without printing Secret values:

1. Argo revision equals the merged Git commit for both `platform-eso-test` and
   `platform-test`.
2. `ExternalSecret/meeting-service-analysis-capability` and
   `ExternalSecret/transcript-service-analysis-capability` are `Ready=True`
   with reason `SecretSynced`. The main service ExternalSecrets remain
   independently Ready.
3. Each target Kubernetes Secret contains a non-empty
   `ANALYSIS_JOB_CAPABILITY_HMAC_SECRET` key.
4. SHA-256 of the decoded key is equal across the two target Secrets; record
   only equality and, if needed, a short hash prefix.
5. Both replacement pods are Available and use the immutable image digests
   rendered by the merged overlay.
6. Pod environment reports the key as present; never print its value.

If either ExternalSecret is not Ready or the two hashes differ, do not restart
or patch a workload. Repair the Vault/policy/ESO path, increment both dedicated
`analysis-capability-rev` markers in a reviewed GitOps PR, and reconcile again.

## Capability Smoke

Run the capability-aware synthetic Meeting Intelligence runtime smoke on the
exact merged revision. Required metadata-only evidence:

1. capability issuance no longer returns `JOB_CAPABILITY_UNAVAILABLE`;
2. first analysis-result write succeeds for the exact job tuple;
3. replay of the same capability is rejected;
4. a conflicting tuple or result is rejected;
5. the canonical analysis result can be read back without logging transcript
   content, raw tokens, or the HMAC secret.

This proves the bounded service-to-service write contract only. Attended mic,
loopback, live transcript, stop, canonical transcript, summary, decision,
action, and reopen acceptance remain separate product evidence.

## Rotation Gate And Rollback

Do not rotate an active `hmac_secret_base64` value with this runbook. Both
applications read the value into an environment variable at pod start, and the
issuer and verifier are separate rolling Deployments. Updating Vault and
bumping both rollout markers in one PR is not atomic: one pod can hold the new
key while the other still holds the old key. The one-hour ExternalSecret
refresh interval adds a second stale-target risk. Analysis writes would fail
closed during either mismatch, but that outage is not an accepted rotation
procedure.

Rotation requires a separately reviewed product contract with all of the
following before any Vault mutation:

1. a key identifier on issued capabilities;
2. current plus previous verifier keys with a bounded overlap TTL;
3. an issuer cutover sequence that stops issuing the old key only after both
   verifier targets and pods accept the new key;
4. explicit ExternalSecret refresh and metadata-only hash read-back before each
   rollout step;
5. replay/conflict smoke, overlap expiry, and rollback evidence.

Until that contract exists, an existing KV version is an operator stop
condition and `--create-only` preserves it. For first-activation rollback,
revert the reviewed manifest/rollout changes while preserving Vault version
history; do not delete or destroy KV versions. Keep analysis issuance and
verification fail-closed.
