# Faz 22.8A — Endpoint Backup Dry-Run Manifest Contract v1

> **Status**: PROPOSED — **engineering (disabled-by-default) UNBLOCKED** (ADR-0034 #1388 lift); **live/runtime BLOCKED** (§11/D10 + 22.8 collection-scope addendum + DPO/legal + #1390 charter + ADR-0012-EA §0 DC-EA/DD-EA-9).
> **DC-EA tier**: **DC-EA-1** (metadata-only; **içerik OKUNMAZ, hash YOK**).
> **Tarih**: 2026-06-09 · **Owner**: platform-agent [#117](https://github.com/Halildeu/platform-agent/issues/117)
> **Cross-AI**: Codex `019ea961` AGREE (v1 baseline) · Codex `019ec28a` REVISE→ (P0 `archive_container`/`is_container` çelişki çözümü, 2026-06-13). **İlişkili**: [22.8 plan](faz-22-endpoint-data-protection-plan.md), [ADR-0034 #1388 lift](adr/0034-1388-sensitive-endpoint-ops-owner-decision.md), [ADR-0035 evidence-storage-contract](adr/0035-evidence-storage-contract.md), [ADR-0012-EA §0 DC-EA/DD-EA-9](adr/0012-EA-endpoint-admin-governance-charter.md).
>
> **Amendment 2026-06-13 (P0)**: `is_container` per-entry alanı + `extension_type:archive` enum değeri **kaldırıldı** (archive-container DC-EA-RED ⇒ denied-aggregate, entry değil — §1.2/§3 ile çelişiyordu). `container_count` artık "denied archive alt-sayısı" (release-gate flag). Schema henüz hiçbir producer/consumer tarafından implement edilmediği için `manifest_version` "1" kalır.

Bu kontrat, 22.8A scheduled backup'ın **ilk güvenli adımını** tanımlar: agent,
dosya **içeriğini okumadan** ne yedekleneceğinin **metadata-only manifest**'ini
üretir. Bu manifest, content copy'ye geçilmeden önce policy/approval review'ı
besler. **Content hash dahil hiçbir içerik erişimi bu adımda yoktur** (Codex
kritik düzeltmesi: SHA256 hesaplamak = içerik okumak).

---

## 1. İnvariantlar (zorunlu)

1. **Metadata-only:** içerik okunmaz, **SHA256/content hash hesaplanmaz**.
2. **DC-EA-RED hariç:** credential / browser profile / token / private-key /
   mailbox cache / DPAPI store / registry hive / password-manager /
   **archive-container** (`zip/7z/rar/vhd/vhdx/pst/ost`) → **manifeste GİRMEZ**
   (path bile listelenmez, **entry üretilmez**; varlığı yalnız aggregate
   `denied_count` + ilgili `denied_classes` olarak). Archive-container ayrıca
   `container_count`'a (release-gate recursive-classification için işaretli denied
   archive sayısı) sayılır — **içeriği 22.8A.1'de açılmaz/okunmaz/descent edilmez**.
3. **Allowlist-first:** yalnız backend bounded-allowlist profiline giren path
   sınıfları taranır; denylist agent-side hardcoded ikincil emniyet.
4. **Path canonicalization BEFORE listing:** symlink/junction/reparse/UNC/ADS/
   long-path/cloud-sync-root resolve edilip karara öyle varılır.
5. **Redaction-safe:** manifest backend ingest + (redaction sonrası) evidence
   comment için güvenli; **ham personal path/PII düz basılmaz**.
6. **Disabled-by-default:** capability advertise edilmez (AG-013).

## 2. Manifest schema (v1)

> **Machine-readable + CI-enforced**: [`schema/faz-22-8a-backup-manifest-v1.schema.json`](../schema/faz-22-8a-backup-manifest-v1.schema.json) (JSON Schema Draft 2020-12) is the canonical machine form of this section, validated by `tests/contracts/test_backup_manifest_payload_contract_v1.py` (CI gate `gate-faz22-8a-backup-manifest-contract.yml`). It pins the invariants structurally: `additionalProperties:false` on every object **forbids a content-hash/SHA256 field** (invariant #1) and the removed `is_container` field; `extension_type` carries **no `archive`** value (§1.2 + 2026-06-13 amendment); `manifest_version`/`dc_ea_tier` are const; `denied_classes` is the authoritative §3 set; `root_ref` must be an opaque `managed_root:<uuid>` ref. A future producer (platform-agent [#117](https://github.com/Halildeu/platform-agent/issues/117)) and the backend mirror (§5) validate against this one schema.

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
      "extension_type": "doc | sheet | pdf | image | other",
      "size_bytes": 12345,
      "mtime_bucket": "P7D | P30D | P90D | older",
      "owner_scope_marker": "company | unknown",
      "file_count": 1
    }
  ],
  "aggregate": {
    "total_eligible_count": 1200,
    "total_eligible_size_bytes": 4567890,
    "denied_count": 38,
    "denied_classes": ["credential_store", "browser_profile", "mailbox_cache", "private_key_material", "cloud_cli_token_store", "registry_hive", "dpapi_store", "archive_container"],
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
- `extension_type` = **coarse enum** (`doc | sheet | pdf | image | other`);
  **`archive` YOK** — archive-container DC-EA-RED'dir (§1.2 + §3), entry'e ulaşmadan
  denylist'te elenir. RED-sınıf uzantı (örn. `.kdbx`, `.pem`, `.ost`) entry'e
  dönüşmeden denied-aggregate'e gider. `file_count > 1` = dizin rollup sinyali
  (ayrı container-flag alanı **yok**; çelişki kaynağı `is_container` v1'de kaldırıldı).
- `container_count` (aggregate) = DC-EA-RED `archive_container` isabetlerinin
  **alt sayısı** — release öncesi recursive-classification / quarantine için
  işaretli (ADR-0035 §6 + 22.8 plan §4). **22.8A.1'de archive açılmaz, içerik
  okunmaz, içine descent edilmez**; recursive classification ayrı + ayrıca-gated
  bir sonraki adımdır.
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
| `archive_container` | `zip/7z/rar/vhd/vhdx/pst/ost` → **22.8A.1'de DENIED** (entry üretilmez; `denied_count` + `denied_classes:archive_container` + `container_count` artar). Recursive classification / quarantine **ayrı + ayrıca-gated sonraki adım** (RED veri arşivde gizlenebilir; içerik 22.8A.1'de **açılmaz/descent edilmez**) |

Sınıf matcher **agent-hardcoded**; policy ile gevşetilemez; backend mirror (§5)
aynı sınıf kararını server-side doğrular.

**Dual-match dedup (`pst/ost`)**: `.pst`/`.ost` hem `mailbox_cache` hem
`archive_container` predicate'ine uyar. Aynı obje **`denied_count`'a yalnız bir
kez** sayılır; primary class `mailbox_cache`, ek olarak archive-container predicate
true olduğundan `container_count++` ve `denied_classes` set'ine `archive_container`
da eklenir. Producer ve backend mirror (§5) bu dedup'ı **aynı** uygular (Codex
`019ec28a` netleştirme).

## 4. Allowlist profile (backend, bounded)

`managed_data_root` registry'den türetilir (22.8 plan §8): yalnız ispatlı
company-managed root'lar (OneDrive-for-Business tenant ID / SharePoint site ID /
corporate-UNC / signed IT-folder marker / MDM-GPO root). BYOD default: yalnız
pre-managed sync root; personal Documents/Desktop/Pictures/Downloads **deny**.

## 5. Backend mirror validation

Manifest backend'e gelince, **aynı karar motorunun server-side mirror'ı**
re-validate eder (agent'a güvenilmez): allowlist match + denylist negative +
canonicalization sanity + aggregate tutarlılık. Mismatch → reject + audit.

> **Düzeltme 2026-07-22 (#1536, Codex `019ec30d` 2× flag)**: bu paragraf
> önceden mirror'ın `archive_container` deny kararını ve `container_count`'u
> **"yeniden hesapladığını"** söylüyordu. Bu **overclaim**'di ve güvenlik
> duruşunu olduğundan güçlü gösteriyordu.
>
> Backend'in **cihaz dosya sistemi yok** — `BackupDryRunManifestPayloadPolicy`
> javadoc'u bunu açıkça yazıyor: *"the backend has no device filesystem, so the
> mirror is a STRICT STRUCTURAL re-validation (not a re-walk)"*. Mirror
> arşivin içine inmez, dizin ağacını yeniden yürümez, dolayısıyla
> `container_count`'u kaynak veriden **türetemez**.
>
> Fiilen yapılan şey **cross-field tutarlılık zorlaması** (no-trust, ama
> yapısal):
>
> - `container_count` ≤ `denied_count`
> - `denied_classes` içinde `archive_container` varsa → `container_count` ≥ 1
>   (yoksa reject: *"archive_container denied but container_count is zero"*)
> - `container_count` > 0 ise → `denied_classes` içinde `archive_container`
>   **zorunlu** (yoksa reject: *"container_count positive but archive_container
>   missing from denied_classes"*)
> - full-envelope path-free (KVKK m.4) + enum/şema uyumu
>
> **Neden bu ayrım önemli**: "yeniden hesaplar" okuyan biri, kötü niyetli bir
> agent'ın gönderdiği `container_count`'un bağımsız olarak doğrulandığını sanır.
> Gerçekte **kendi içinde tutarlı ama yanlış** bir manifest bu kapıdan geçer.
> Mirror'ın koruduğu şey, üreticiye güvenmeden **iç tutarlılık ve şema
> disiplini**; sayının maddi doğruluğu değil.
>
> Kod ve runbook **zaten doğruydu** — düzeltilen yalnız bu sözleşme cümlesi.
> Gerçek recompute, arşiv içi recursive classification ile birlikte gelirse
> anlamlı olur; o **ayrı ve ayrıca-gated** bir sonraki adım (bkz. §3
> `archive_container` satırı).

## 6. D29 acceptance (22.8A.1)

| Katman | Kanıt |
|---|---|
| **Up** | Agent dry-run capability **disabled-by-default** + advertise YOK |
| **Functional** | Manifest doğru path-class/size/count/mtime-bucket üretir; **içerik hash YOK**; **archive-container entry YOK** (denied-aggregate + `container_count` doğru, archive içine descent yok); denied aggregate doğru |
| **Secured** | DC-EA-RED deny enforce (agent-hardcoded) + backend mirror + redaction-safe + canonicalization bypass testleri (symlink/junction/UNC/ADS) yeşil |

## 7. Cross-AI Consensus Log

Codex `019ea961` REVISE→AGREE: metadata-only (no SHA256 in dry-run), denied as
aggregate-only, allowlist-first, hardcoded denylist + canonicalization, backend
mirror, container quarantine-flag, redaction-safe.

Codex `019ec28a` (impl plan-consult, 2026-06-13) **REVISE — P0**: önceki "container
quarantine-flag" entry'si §1.2/§3 ile çelişiyor — `archive_container` DC-EA-RED
olduğundan **entry üretilemez**. Çözüm (bu amendment): archive = denied-aggregate
(`denied_count` + `denied_classes:archive_container` + `container_count`), per-entry
`is_container` alanı + `extension_type:archive` enum kaldırıldı; recursive
classification ayrıca-gated sonraki adıma ertelendi. Codex'in diğer impl-time
revizyonları (default-off advertise modeli, `GetFinalPathNameByHandleW`
canonicalization, no-content static guard, custom deny-before-descent walker,
path-free error codes) **22.8A.1 impl PR'ında** (platform-agent #117) test edilir.
