# ao-kernel Context Bridge — `.md` Bağlamını Governed Hale Getirme

Bu repo binlerce `.md` dosyasıyla bağlam yönetiyor (`AGENTS.md`,
`docs/context-priority-rules.md`, `docs/adr/*`, `decisions/*`,
`docs/state/current-state.md`, runbook'lar, plan'lar). Bir AI agent'ına
(Claude / Codex / Mavis) bu ham yığını vermek yerine **ao-kernel context
bridge** onları **governed bir store**'a (confidence + freshness +
provenance + tier) alıp **kısa, fail-closed, provenance-tagged** bir
*context packet* üretir.

> Bu, `host-compose/ao-gate`'in (AO **runtime** gate servisleri) **bağlam**
> tarafındaki tamamlayıcısıdır. Repo **read-only** taranır, governed store
> ephemeral bir workspace'te yaşar ve çıkışta silinir; cluster komutu (kubectl/
> argocd) veya secret store çağrısı yapmaz.
>
> ⚠️ **Sandbox DEĞİL.** `pip install` + ao-kernel, PyPI'den gerçek Python kodu
> indirir/çalıştırır ve çağıranın env/dosya/ağ yetkilerini miras alır; yalnız
> ao-kernel **sürümü** pinlidir, tedarik zinciri değil. Güvenilir bir shell'den
> çalıştır; cluster/Vault/cloud secret'larını bu prosesin env'ine **export
> etme**.

## Kullanım

```bash
make context-packet
# whitelisted knob'lar (env var olarak):
MAX_ITEMS=12 MIN_CONF=0.7 INCLUDE_DOC_CLAIMS=1 make context-packet
# başka argüman için script'i doğrudan çağır:
scripts/ao-context-packet.sh --max-items 12 --min-conf 0.7 --include-doc-claims
```

Ortam değişkenleri:

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `AO_KERNEL_VERSION` | `4.3.0` | ao-kernel sürümü (PyPI); default pin, override edilebilir |
| `AO_CONTEXT_PROFILE` | `TASK_EXECUTION` | Context profil etiketi |

Gereksinim: `python3` (>= 3.11) + venv + PyPI erişimi. Script izole bir venv
kurar; host Python ortamını kirletmez.

## Ne üretir

1. **Ingest** — default mapping tüm `.md` yığınını değil yalnız haritalanan
   bağlam yüzeylerini tarar: `AGENTS.md`, `docs/context-priority-rules.md`,
   `docs/adr/[0-9]*.md` (~31 ADR), `docs/state/current-state.md`. (Repo'daki
   `decisions/*` default kapsamda DEĞİL — gerekirse `--mapping` ile eklenir.)
   Güncel ölçüm (origin/main): **~40 governed item**
   (≈30 ADR-decision + 8 current-state fact + 2 rule), 0 collision,
   **0 secret**, tek CAS revision. Her item'da SHA256 `provenance.doc_bridge`
   (`src`, `doc_hash`, `value_hash`, `doc_date`, `tier`, `status`,
   `observed_at`). (Repo'daki tracked `.md` toplamı ~638; çoğu runbook/evidence
   default mapping kapsamı dışındadır — kapsam `--mapping` ile genişletilebilir.)
2. **Packet** — yalnız **fresh + high-confidence** öğeler (Rules conf 0.95 +
   Accepted ADR'lar conf 0.90) gösterilir; doğrulanmamış `current-state`
   iddiaları (`doc_claim`, conf 0.55) **fail-closed dışlanır**
   (`--include-doc-claims` ile opt-in). Header açıkça belirtir: *source-derived
   context, release authority DEĞİL; `support_widening` /
   `production_platform_claim` / `live_adapter_execution` guard flag'lerini
   override edemez.*

## Garantiler

- **Read-only**: repo working tree değişmez; `.ao/` store repo içinde değil,
  ephemeral `mktemp` workspace'te oluşur.
- **Fail-closed**: stale / düşük-confidence / kaynağı silinmiş/drift etmiş /
  secret-benzeri değerler packet'e **girmez**.
- **Deterministik**: aynı içerik aynı item key + `value_hash` üretir; yalnız
  `observed_at` her koşumda tazelenir.

## İlişki

| Yüzey | Sorumluluk |
|---|---|
| `host-compose/ao-gate` | AO **runtime** gate servisleri (GPP-2: policy + release-gate) |
| `scripts/ao-context-packet.sh` (bu) | AO **context** bridge — `.md` → governed packet |

Kaynak: [`ao-kernel`](https://github.com/Halildeu/ao-kernel) (PyPI
`ao-kernel`), `ao_kernel.context.doc_bridge` + `ao-kernel context
{ingest,packet}`.
