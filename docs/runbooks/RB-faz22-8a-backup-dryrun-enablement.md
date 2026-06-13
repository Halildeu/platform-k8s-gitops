# RB — Faz 22.8A Backup Dry-Run Manifest Enablement (#1390)

> **Code-complete (agent-doable) DONE; enablement owner/operator-gated.** The
> three-layer 22.8A vertical — contract + agent producer + backend mirror — is
> merged, cross-AI AGREE'd, and CI-green (13/13 · 8/8 · 14/14 PR checks), but
> **disabled-by-default end-to-end**. **No supported end-to-end path produces or
> persists a live backup dry-run result** until the owner decides go-forward and
> the operator/backend wire the remaining slices (agent capability default-off;
> generic `/commands` → 422; no dedicated issuing surface; no deploy). This
> runbook is the handoff: what is built, what remains to enable it, and the
> D29-EA + KVKK acceptance gate for the live flip.

DC-EA tier **DC-EA-1**: the manifest is **metadata-only** — the agent lists what
*would* be eligible for backup (path-class / size / mtime-bucket / count)
**without reading any file content and without computing any hash**. DC-EA-RED
classes (credential / browser / mailbox / private-key / cloud-token / password-
manager / DPAPI / registry-hive / app-token / **archive-container**) are
denied-aggregate and never listed (contract v1 P0 amendment, Codex `019ec28a`).

## Built + merged (agent-doable — DONE)

| Layer | Repo / PR | What | Cross-AI |
|---|---|---|---|
| Contract v1 (+ P0 fix) | platform-k8s-gitops `#1532` (`5e5a06fa`) | `docs/faz-22-8a-backup-manifest-contract-v1.md` — schema + DC-EA-RED classes + archive denied-aggregate + pst/ost dedup | Codex `019ec28a` AGREE |
| Agent producer | platform-agent `#153` (`c9dc5132`) | `internal/dataprotection` metadata-only walker (deny-before-descent, `GetFinalPathNameByHandle` canonicalization, no-content static guard, root-field positive-allowlist), `COLLECT_BACKUP_DRYRUN` capability **opt-in** (`EnableBackupDryRun`, default false) | Codex `019ec2bb` AGREE |
| Backend mirror | platform-backend `#640` (`19d58d06`) | `BackupDryRunManifestPayloadPolicy` strict-schema server-side re-validate (additionalProperties:false + full-envelope path-free + aggregate invariants + device/tenant binding), `COLLECT_BACKUP_DRYRUN` in `DEDICATED_PATH_ONLY`, V66 CHECK | Codex `019ec2e6` AGREE |

The Go producer and the Java mirror implement **the same wire contract**
(identical key sets, enums, denylist, aggregate invariants). The backend is a
**strict structural no-trust mirror**: it re-validates the received manifest's
schema / enums / path-free / aggregate-consistency / device-tenant binding — it
does NOT re-walk the device filesystem (it has none) nor re-derive the deny
decision from real paths. Metadata-only is machine-enforced on both sides
(agent: import/call static guard + `FILE_READ_ATTRIBUTES`-only handle; backend:
strict-schema whitelist with no content/hash field).

## Prerequisites to enable (NOT agent-doable — owner/operator/future-slice)

| # | Prerequisite | Owner | Why |
|---|---|---|---|
| P1 | **Owner go-forward decision** on activating 22.8A | **owner** | privacy-sensitive scan; ADR-0034 lifted only the *engineering* (disabled-by-default build) gate — live/first-run needs §11/D10 + DD-EA dual-control. Until this, P2–P6 must not start. |
| P2 | **22.8A.3 dedicated issuing surface** (backend PR) | **platform-backend** | `COLLECT_BACKUP_DRYRUN` is `DEDICATED_PATH_ONLY`; the generic `/commands` path rejects it (422). A dedicated maker-checker REST surface (mirroring install/uninstall) must exist to issue the command with the bounded allowlist payload. |
| P3 | **Managed-data-root registry** (contract §4) | **platform-backend** | the issuing surface needs a bounded registry of proven company-managed roots (OneDrive-for-Business tenant / SharePoint site / corporate-UNC / signed IT-folder / MDM-GPO root) to populate the request `roots`; the agent re-verifies every one. |
| P4 | **endpoint-admin-service deploy** carrying V66 + the mirror validator (D29-EA) | **operator** | the mirror only runs in a deployed build; V66 extends the `command_type` CHECK. |
| P5 | **Agent capability enable** on a policy-ready Windows build | **operator / build** | `RuntimeCapabilityOptions.EnableBackupDryRun=true` is advertised ONLY on Windows + local-policy-ready; a plain build never advertises it. |
| P6 | **DPO / legal sign-off + KVKK aydınlatma** for backup-eligibility scanning | **owner / hukuk** | see KVKK mapping below; the dry-run is metadata-only but the *purpose* (backup eligibility) must be declared. |

## Enablement steps (after P1–P6 — none optional)

1. Land 22.8A.3 issuing surface + managed-data-root registry (P2/P3), cross-AI reviewed + CI-green.
2. Deploy endpoint-admin-service with V66 + the mirror (P4); confirm pod imageID == GHCR digest (D30 immutable).
3. Enable the agent capability on the pilot Windows build (P5); confirm `COLLECT_BACKUP_DRYRUN` appears in the heartbeat `payload.capabilities` ONLY on that build.
4. Issue one `COLLECT_BACKUP_DRYRUN` via the dedicated surface (P2) with a single bounded managed root + a reason (RequiresReason); dual-control approve.
5. Agent produces the metadata-only manifest; backend mirror re-validates (accept on valid; on violation → 400, the offending result payload/manifest is not persisted, the command is marked FAILED with a bounded path-free error; the P2 issuing surface must capture the rejection in its own audit trail).
6. Run the live Windows-VM smoke (below) and capture the D29-EA evidence.

## D29-EA acceptance gate

| Layer | Kanıt |
|---|---|
| **Up** | Capability advertised ONLY on the policy-ready Windows build (`EnableBackupDryRun`); absent from a plain build + non-Windows + the lightweight heartbeat (AG-013 coherence). |
| **Functional** | Valid manifest → mirror accepts + result stored; manifest correct path-class/size/count/mtime-bucket; **no content hash anywhere**; denied aggregate correct (archive denied, never an entry). |
| **Secured** | Metadata-only enforced both sides (agent static guard + backend strict-schema); a manifest with a RED entry / raw path (incl. summary/errorCode) / unknown field / decimal count / device-tenant mismatch → **400; the offending result payload/manifest is NOT persisted; the command is marked FAILED with a bounded, path-free error**; issuing path dual-control + DEDICATED_PATH_ONLY 422 on the generic path. (The future dedicated issuing surface (P2) must also capture the rejection in its own audit trail.) |

## Live Windows-VM smoke (operator/VM-gated — like #149)

On the pilot Windows host (or a Parallels Win11 guest, SYSTEM context):
1. Confirm the capability advertises (heartbeat `capabilities` contains `COLLECT_BACKUP_DRYRUN`).
2. Issue the command (dedicated surface) over a tree containing a managed root + a planted `.zip`, `id_rsa`, and a normal `.docx`.
3. Assert the manifest: the `.docx` is an entry (extension_type `doc`), the `.zip` + `id_rsa` are denied-aggregate (no entry; `denied_classes` carries `archive_container` + `private_key_material`; `container_count ≥ 1`), and **no raw path appears anywhere** in the manifest / result / audit.
4. Capture screenshot + the stored result payload (path-free) as the D29-EA Functional+Secured evidence.

## KVKK mapping

- **m.4 (data minimization)**: metadata-only manifest, opaque `root_ref`, coarse `mtime_bucket`, path-free — the artifact carries no file content and no raw personal path.
- **m.5 / m.6 (lawful basis)**: the lawful basis is **NOT locked here — DPO / Hukuk decide** (22.8 plan §8; **DPIA + VERBİS impact-check mandatory** before live). The *candidate* basis is `meşru menfaat` / `sözleşmenin ifası`, scoped to company-managed roots only (BYOD personal roots denied), declared in the aydınlatma metni after sign-off. **m.6 (özel nitelikli veri)**: DC-EA-1 does not target special-category data; if special-category inference/processing risk emerges, a **separate m.6 gate** is required.
- **DC-EA-1 / DD-EA-9 (ADR-0012-EA §0)**: this tier permits metadata-only; any move to content read/copy is a separate, higher tier with its own gate (ADR-0035 evidence-storage, BLOCKED).

## Rollback

The feature is disabled-by-default; to revert at any stage: unset `EnableBackupDryRun` on the agent build (capability disappears from the heartbeat) and/or remove the dedicated issuing surface. **No file content is copied and no hash/content artifact is produced.** Any already-persisted metadata-only result remains **governed evidence** — path-class / size / mtime-bucket / count metadata is still KVKK-in-scope and subject to the audit retention + purge controls (not content, but not "zero data" either).

## References

- Contract: `docs/faz-22-8a-backup-manifest-contract-v1.md` (gitops `#1530`)
- PRs: platform-k8s-gitops `#1532`, platform-agent `#153`, platform-backend `#640`
- Charter: gitops `#1390` (Faz 22.8 Endpoint Data Protection); ADR-0034 (#1388 lift); ADR-0012-EA §0 (DC-EA/DD-EA-9); ADR-0035 (evidence-storage, BLOCKED)
- Codex threads: `019ec28a` (contract), `019ec2bb` (agent), `019ec2e6` (backend mirror)
