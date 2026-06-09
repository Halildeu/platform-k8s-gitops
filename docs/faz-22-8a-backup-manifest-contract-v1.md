# Faz 22.8A — Endpoint Backup Dry-Run Manifest Contract v1

> **Status**: PROPOSED / **BLOCKED** — #1388 + #1390 + ADR-0012-EA §0 (DC-EA + DD-EA-9).
> **DC-EA tier**: **DC-EA-1** (metadata-only; **içerik OKUNMAZ, hash YOK**).
> **Tarih**: 2026-06-09 · **Owner**: platform-agent [#117](https://github.com/Halildeu/platform-agent/issues/117)
> **Cross-AI**: Codex `019ea961` AGREE. **İlişkili**: [22.8 plan](faz-22-endpoint-data-protection-plan.md), [ADR-0035 evidence-storage-contract](adr/0035-evidence-storage-contract.md), [ADR-0012-EA §0 DC-EA/DD-EA-9](adr/0012-EA-endpoint-admin-governance-charter.md).

Bu kontrat, 22.8A scheduled backup'ın **ilk güvenli adımını** tanımlar: agent,
dosya **içeriğini okumadan** ne yedekleneceğinin **metadata-only manifest**'ini
üretir. Bu manifest, content copy'ye geçilmeden önce policy/approval review'ı
besler. **Content hash dahil hiçbir içerik erişimi bu adımda yoktur** (Codex
kritik düzeltmesi: SHA256 hesaplamak = içerik okumak).

---

## 1. İnvariantlar (zorunlu)

1. **Metadata-only:** içerik okunmaz, **SHA256/content hash hesaplanmaz**.
2. **DC-EA-RED hariç:** credential / browser profile / token / private-key /
   mailbox cache / DPAPI store / registry hive / password-manager → **manifeste
   GİRMEZ** (path bile listelenmez; varlığı yalnız aggregate "denied_count" olarak).
3. **Allowlist-first:** yalnız backend bounded-allowlist profiline giren path
   sınıfları taranır; denylist agent-side hardcoded ikincil emniyet.
4. **Path canonicalization BEFORE listing:** symlink/junction/reparse/UNC/ADS/
   long-path/cloud-sync-root resolve edilip karara öyle varılır.
5. **Redaction-safe:** manifest backend ingest + (redaction sonrası) evidence
   comment için güvenli; **ham personal path/PII düz basılmaz**.
6. **Disabled-by-default:** capability advertise edilmez (AG-013).

## 2. Manifest schema (v1)

```json
{
  "manifest_version": "1",
  "dc_ea_tier": "DC-EA-1",
  "device_id": "<uuid>",
  "tenant_id": "<id>",
  "generated_at": "<iso8601>",
  "allowlist_profile_id": "<id>",
  "scope": {
    "managed_data_roots": ["<root_ref>"],
    "byod": false
  },
  "entries": [
    {
      "path_class": "managed/onedrive-business | managed/sharepoint | managed/unc-corp | managed/it-folder | mdm-gpo-root",
      "root_ref": "managed_root:<opaque_uuid>",
      "relative_depth": 3,
      "extension_type": "doc | sheet | pdf | image | archive | other",
      "size_bytes": 12345,
      "mtime_bucket": "P7D | P30D | P90D | older",
      "owner_scope_marker": "company | unknown",
      "file_count": 1,
      "is_container": false
    }
  ],
  "aggregate": {
    "total_eligible_count": 1200,
    "total_eligible_size_bytes": 4567890,
    "denied_count": 38,
    "denied_classes": ["credential_store", "browser_profile", "mailbox_cache", "private_key_material", "cloud_cli_token_store", "registry_hive", "dpapi_store"],
    "container_count": 5,
    "unresolved_path_count": 0
  }
}
```

**Alan kuralları:**
- `path_class` = **normalize sınıf**, ham path değil (data minimization, KVKK m.4).
- `root_ref` = **opaque `managed_root:<uuid>`** registry referansı — ham root
  path / share name DEĞİL. Dry-run artifact/log raw `C:\Users\...\Documents` veya
  `\\share\hr_exit\...` **taşımaz**; backend/DPO UI ID'yi yetkili ekrana map eder.
- `mtime_bucket` = aralık (kesin timestamp değil — inference azaltma).
- `denied_*` = DC-EA-RED isabetleri **aggregate**; `denied_classes` **coarse**
  (uygulama/ürün parmak izi YOK — "KeePass found" gibi değil). Ürün adı yalnız
  local debug + DPO-onaylı redacted operator evidence'da.
- `is_container` = true → ADR-0035 §6 + 22.8 plan §4: **release öncesi recursive
  classification / quarantine** (içerik hash bu adımda yok; sadece flag).
- `owner_scope_marker=unknown` → company-managed proof yok → content'e geçmez (§8 plan).

## 3. Denylist (DC-EA-RED) — class-based matcher (agent-hardcoded, policy ile gevşetilemez)

Authoritative kural **sınıf bazlı**dır (aşağıdaki path örnekleri yalnız
*examples*; eşleşme **canonical path** üzerinden, §1.4). Sınıflar:

| Class | Kapsam (örnekler) |
|---|---|
| `credential_store` | Windows Credential Manager / Vault backing stores; `*.git-credentials`, `.npmrc`, `.docker/config.json` |
| `browser_profile` | Chrome/Edge/Firefox `User Data`; `WebCacheV01.dat`; cookies / local-storage / session-storage |
| `mailbox_cache` | `*.ost`/`*.pst`; Outlook / Windows Mail / Thunderbird profile directories |
| `private_key_material` | `*.kdbx *.pem *.key *.pfx *.ppk *.ovpn`; `id_rsa*`, `known_hosts`; `.ssh` |
| `cloud_cli_token_store` | `.aws`, `.azure`, `.config/gcloud`, `.kube`; CLI credential stores |
| `password_manager_vault` | KeePass / 1Password / Bitwarden / LastPass / etc. (class, ürün-adı output'a girmez) |
| `dpapi_store` | `%APPDATA%\Microsoft\Protect` |
| `registry_hive` | `NTUSER.DAT` + diğer hive'lar |
| `app_token_store` | VS Code / JetBrains / Electron app token/secret stores |
| `archive_container` | `zip/7z/rar/vhd/vhdx/pst/ost` → **release öncesi recursive classification veya default quarantine** (RED veri arşivde gizlenebilir) |

Sınıf matcher **agent-hardcoded**; policy ile gevşetilemez; backend mirror (§5)
aynı sınıf kararını server-side doğrular.

## 4. Allowlist profile (backend, bounded)

`managed_data_root` registry'den türetilir (22.8 plan §8): yalnız ispatlı
company-managed root'lar (OneDrive-for-Business tenant ID / SharePoint site ID /
corporate-UNC / signed IT-folder marker / MDM-GPO root). BYOD default: yalnız
pre-managed sync root; personal Documents/Desktop/Pictures/Downloads **deny**.

## 5. Backend mirror validation

Manifest backend'e gelince, **aynı karar motorunun server-side mirror'ı**
re-validate eder (agent'a güvenilmez): allowlist match + denylist negative +
canonicalization sanity + aggregate tutarlılık. Mismatch → reject + audit.

## 6. D29 acceptance (22.8A.1)

| Katman | Kanıt |
|---|---|
| **Up** | Agent dry-run capability **disabled-by-default** + advertise YOK |
| **Functional** | Manifest doğru path-class/size/count/mtime-bucket üretir; **içerik hash YOK**; denied aggregate doğru |
| **Secured** | DC-EA-RED deny enforce (agent-hardcoded) + backend mirror + redaction-safe + canonicalization bypass testleri (symlink/junction/UNC/ADS) yeşil |

## 7. Cross-AI Consensus Log

Codex `019ea961` REVISE→AGREE: metadata-only (no SHA256 in dry-run), denied as
aggregate-only, allowlist-first, hardcoded denylist + canonicalization, backend
mirror, container quarantine-flag, redaction-safe.
