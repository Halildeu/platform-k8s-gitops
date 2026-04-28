# GA-002 — ESO AppRole reads

## Class

**Split decision** — material türüne göre değişir:

| Material | Class | Agent? |
|---|---|---|
| `role_id` (CRD metadata, redacted config) | not credential | ✅ Agent okuyabilir |
| `secret_id` (ClusterSecretStore secret) | `credential-read` | ❌ Agent yasak |
| Vault token / KV secret (downstream sync target) | `credential-read` | ❌ Agent yasak |
| `secret_id` generation/rotation | `credential-write` | ❌ Agent yasak |
| Capabilities-self check (redacted output) | `credential-read` (limited) | 🟡 Operator-provided output parse OK |

## Sandbox behavior

`sandbox-gap` (partial) — Session 32'de sandbox `role_id` metadata + `secret_id` material arasında ayrım yapmadı. ADR-0011 §1 Context'te kayıtlı: "ESO AppRole reads (sandbox didn't block, role-id may be public-ish but secret-id should not be)".

## Decision

`role_id` ve `secret_id` farklı sınıflarda:

- **`role_id`**: ExternalSecret CRD'de `data.spec.auth.appRole.roleId` field'ında veya `valueFrom: configmapKeyRef` ile ConfigMap'te yaşar. Public-like metadata (Vault auth path discovery için yetmez kendi başına). Agent okuyabilir.
- **`secret_id`**: Wrapped token veya `secretKeyRef` ile Kubernetes Secret'inde yaşar. Vault auth credential. Agent okuma/işleme yasak.
- **Vault token / KV secret content**: ESO'nun fetch ettiği downstream secret (REPORTS_DB_PASSWORD, JWT_PRIVATE_KEY, vs). Agent için literal yasak; runtime SSH üzerinden `kubectl exec ... env | grep` ile pod env'e bakmak da bypass. Sadece operator-provided output parse edilir.

`secret_id` generation veya rotation `credential-write`.

`vault token capabilities-self` gibi self-check'ler genelde sadece policy/path enumeration verir, secret material değil. Yine de canlı çalıştırma agent yasak; operator output redacted paste-back agent için OK.

## Agent allowed

- ExternalSecret CRD spec read-only (`role_id` metadata)
- ConfigMap/Secret structure inspection (key listesi — value değil)
- ESO refresh annotation update (`force-sync` triggering — credential dokunmaz, sadece sync state)
- Operator-provided redacted output parse (e.g., "vault token verified, capabilities: [foo, bar]")

## Agent blocked

- `vault read auth/approle/role/<name>/secret-id` (secret_id read)
- `vault write auth/approle/role/<name>/secret-id` (secret_id generation)
- `kubectl get secret -n <ns> <vault-creds> -o jsonpath` (secret material read)
- `kubectl exec deploy/<svc> -- env | grep PASSWORD` (downstream credential leak)
- `vault token lookup` (token material handling)

## User path

1. Operator local shell'de credential read (Vault CLI, kubectl exec)
2. Output redact + agent transcript'e gerekli information sadece redacted aktar
3. `secret_id` rotate gerekiyorsa: dual-clearance + BG-1 `credential-write` + `user-approval-required` + evidence link

## BG-1 mapping

`role_id` only iş:
- [x] none of the above (Codex consensus only — metadata-level read)

`secret_id` veya downstream credential iş:
- [x] credential-read (or credential-write)
- [x] user-approval-required label
- User-approval evidence link zorunlu

## References

- ADR-0011 §1 Context (gray-area #2: "ESO AppRole reads (sandbox didn't block, role-id may be public-ish but secret-id should not be)")
- ADR-0011 §2.3 (boundary class taxonomy)
- ADR-0010 §2.5 (Operator/agent authority — Vault credential operations)
- ESO documentation: ClusterSecretStore + ExternalSecret CRD model
- BG-1: `docs/RB-adr-0011-bg-1-pr-boundary-declaration.md`
- Codex thread `019dd409` BG-2 split-decision direktifi
