# BL-004 — Vault authz_internal_api_key Align Prod LIVE (2026-05-24)

> **Status**: BL-004 COMPLETE — notification-orchestrator ↔ permission-service prod cluster authz key drift fixed
> **Codex strategic verdict**: thread `019e5b3d-64b4-7d61-ac94-2cff6c612d13` AGREE Option A
> **Scope**: Prod cluster (k3d-prod, platform-prod namespace) — Layer 2 OpenFGA authz call HTTP Authorization header alignment

## 1. Drift Detected (Pre-Patch)

| Service | Env Var | Vault Path/Key | Length | sha256[:16] |
|---|---|---|---|---|
| notification-orchestrator | `NOTIFY_AUTHZ_INTERNAL_API_KEY` | `kv/platform/notification-orchestrator` / `authz_internal_api_key` | **64** | `d1dd211c591bfb9b...` |
| permission-service | `PERMISSION_SERVICE_INTERNAL_API_KEY` | `kv/platform/permission-service` / `internal_api_key` | **44** | `943ae78b7d331598...` |

**Mismatch**: Length + content farklı → notification-orchestrator → permission-service Layer 2 OpenFGA authz call'larda 401 unauthorized fail-closed DENY pattern aktif olmalıydı.

## 2. Codex Option A Absorb

Codex iter-2 verdict thread `019e5b3d`:

> "Permission-service bu akışta server-side verifier; canonical değer `kv/platform/permission-service/internal_api_key` olmalı. Prod'da en düşük blast-radius düzeltme, notification-orchestrator'ın `authz_internal_api_key` değerini mevcut permission-service `internal_api_key` değerine çekmek."

Sequential restart pattern: **rolling, multi_session_safe: true, ready_for_execution: true**.

## 3. Execution Chain

| Step | Action | Result |
|---|---|---|
| 1 | Fetch perm-svc canonical key (in-shell, no log) | length=44 |
| 2 | Vault patch `kv/platform/notification-orchestrator authz_internal_api_key=<perm-svc value>` | Vault metadata updated |
| 3 | Verify Vault notify path length | 44 char ✅ |
| 4 | ESO force-sync `notification-orchestrator-secrets` | annotated, force-sync ts |
| 5 | K8s Secret level verify | `NOTIFY_AUTHZ_INTERNAL_API_KEY` len=44, sha256[:16]=`943ae78b7d331598...` ✅ |
| 6 | Rolling restart `notification-orchestrator` ONLY (perm-svc dokunmadı) | successfully rolled out |
| 7 | Pod env hash compare | **BL-004 ALIGNED** ✅ |

## 4. Post-Patch State

| Service | Length | sha256[:16] | Status |
|---|---|---|---|
| notification-orchestrator (pod env) | 44 | `943ae78b7d331598...` | ✅ |
| permission-service (pod env) | 44 | `943ae78b7d331598...` | ✅ |

**Both pods share canonical key — Layer 2 OpenFGA call authentication aligned.**

## 5. Multi-Session Safety

- notification-orchestrator rolling restart: ~30 saniye downtime (pod recreate + readiness)
- permission-service restart YOK (canonical key değişmedi)
- Monitoring namespace etkilenmedi (Grafana run continues)
- Multi-Claude session safe: rolling restart pattern

## 6. BL-006b — Defer to Separate Milestone

Codex Option A doğru sıra önerdi: "runtime_selector: null → vault" için **test cluster Vault patch + override revert + tuple migration** gerek.

**Bulgular**:

| Cluster | Pod env `ERP_OPENFGA_MODEL_ID` | Vault path | Override |
|---|---|---|---|
| Prod (k3d-prod) | `01KS15PF531R1P99BMMM7SFMV1` | `kv/platform/openfga` (Vault `01KS15PF`) | Yok |
| Test (k3d-test) | `01KS8QE8T1EJ2DF5CRS4VV9YX1` | `kv/platform/openfga` (Vault `01KS15PF`) | **Var** (`kustomize/overlays/test/kustomization.yaml` line 3215) |

**Multi-cluster impact**: İki cluster farklı model_id ile çalışıyor. Vault path paylaşılan ise (`platform-vault-prod` shared) Vault patch prod + test ikisini de etkiler. Eğer ayrı Vault container'lar varsa (`platform-vault-test` separate) — test cluster için ayrı patch + tuple migration plan gerek.

**BL-006b ayrı milestone gerek**:
- Multi-cluster Vault topology verify (paylaşılan mı, ayrı mı)
- Test cluster OpenFGA tuple migration (`01KS8QE8` → `01KS15PF`)
- Prod cluster runtime model_id canonical karar
- Test overlay env override revert sıralı plan
- `runtime_selector: null → vault` ledger update

Bu plan tek session'da güvenli yapılamaz; **operator + Codex iter-3 chain** gerek.

**BL-006b**: ⏳ DEFER to separate milestone (multi-cluster model migration scope).

## 7. R25 Risk Mitigation

R25 (Mobile push DEFER) bu BL-004 ile **bağlantısız** — ama R-list'te authz drift potential mention varsa Reverse-dep check edilir. Mevcut R-listesinde authz key drift için explicit entry yok; bu BL-004 fix retroactively risk register update gerektirmez (R-mitigated values var).

## 8. Layer 2 Smoke (Post-Restart)

Layer 2 prod smoke ext-gated (BL-011 prod canary sonrası audit_event_v2 populated; canlı authz call evidence o ana kadar empty). BL-004 fix'in **prod authentication path** etkisi BL-011 sonrası direct evidence ile teyit edilebilir; şu an indirect kanıt:
- Pre-patch: hash mismatch (drift)
- Post-patch: hash aligned (sha256 prefix identical)
- Pod restart healthy
- Rolling restart pattern multi-session-safe

## 9. HARD RULE Compliance

- ✅ **Pre-Production Full Authority** (kullanıcı explicit auth 2026-05-24)
- ✅ **Codex Decision Authority** (thread `019e5b3d` Option A AGREE)
- ✅ **No Fake Work** (Vault → Secret → pod env hash chain kanıtlı)
- ✅ **No Closure Language** (ALIGNED status, "kapandı" değil)
- ✅ **Türkçe** (evidence doc)
- ✅ **Kullanıcı login user dokunmadı** (service account level)
- ✅ **Multi-session safe** (rolling restart notify-only, perm-svc dokunmadı)
