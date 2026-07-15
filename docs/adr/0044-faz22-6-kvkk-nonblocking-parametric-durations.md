# ADR-0044 — Faz 22.6: KVKK/Legal Items Are NON-BLOCKING for Engineering Completion + Parametric Durations + #1580 VIEW_ONLY Marker Split

> **Status**: ACCEPTED (2026-06-27) — Owner directive (2026-06-27). Cross-AI provider-distinct: Codex `019f05cc` REVISE→**AGREE** (engineering marker stays fail-closed with full evidence list + allowlist machine-enforced + mode-based recording + dual audit output + schema-v2 bump + legacy fail-safe + recording-disabled negative proof absorbed).
>
> **Scope**: How KVKK / legal / DPO obligations relate to the **engineering completion gate** of Faz 22.6 remote-ops (`RB-faz22.6-autonomous-completion-contract.md` + `scripts/faz22-remote-ops/faz22-6-completion-audit.sh`). Reclassifies legal items off the engineering critical path; splits the #1580 VIEW_ONLY acceptance marker; makes retention durations parametric. Does **not** weaken any engineering / security / auditability evidence — those stay fail-closed.
>
> **Owner kararı (2026-06-27, verbatim intent)**: "KVKK ayrı iş, mühendislik blocker'ı OLAMAZ — kural olarak yaz. Süreleri parametrik yap, uygun değere owner karar verince uygulanır. Mimari karar gerekirse cross-AI ile istişare + ADR'ye bağla. Projeyi ilerlet."

---

## Context

Faz 22.6 completion, machine-enforced bir "completion contract" + 861-satırlık marker-hardened audit gate (`F22_6_COMPLETION`) ile korunuyor. Gate fail-closed: issue body marker'ları parse eder (named owner ≠ placeholder, UTC tarih + expiry penceresi). Amaç: ajan'ın completion'ı over-claim etmesini engellemek.

İki kalan blocker, ikisi de owner marker:
1. **#548** hardware-attestation (`GATE_B1_4`) — bu ADR'nin kapsamı DIŞINDA, aynen kalır.
2. **#1580** VIEW_ONLY screen-share (`GATE_VIEW_ONLY_SCREEN_SHARE`). Mevcut marker (`F22_6_VIEW_ONLY_ACCEPTANCE: v1`) **iki şeyi bir arada** istiyor: (a) ENGINEERING canlı-kanıt paketi (HTTPS manifest + `jq -cS` SHA256) **VE** (b) KVKK attended-pilot **hukuki signoff** (`kvkk_attended_pilot_signoff: pass` zorunlu alan, audit `faz22-6-completion-audit.sh:632`).

Bu bundling, bir **hukuki signoff'u mühendislik tamamlanmasının fail-closed önkoşulu** yapıyor. Owner, bunun yanlış sınır olduğunu belirtti: KVKK paralel hukuk/DPO track'idir; mühendislik onun üstünde bloke olmamalı. Aynı zamanda retention süreleri sabit/blocker değil, **parametrik** olmalı (owner uygun değeri verince uygulanır).

KVKK boundary'nin kendisi geçerliliğini korur (aydınlatma, hukuki dayanak, VERBIS "Diğer: ekran gözlemi", retention) — sadece **mühendislik completion gate'ini fail-close etmez**; paralel, izlenen, owner/DPO-sahipli bir yükümlülük olur.

---

## Decision

### D1 — KVKK/Legal = paralel NON-BLOCKING track (ALLOWLIST, serbest metin DEĞİL)
KVKK/legal kalemleri **mühendislik completion blocker'ı olamaz**. Bu kural bir **allowlist** ile makine-zorunlu: yalnız şu enumerated anahtarlar non-blocking track'e gider —
- `kvkk_attended_pilot_signoff` (hukuki attended-pilot signoff)
- `legal_dpo_consent` (DPO / hukuki onay)
- `retention_policy_approval` (retention süresi owner/hukuk kararı)

`status`, `owner_approved_by`, `approved_at`, `expires_at` standart lifecycle
alanlaridir. `decision_record_sha256`, `decision_record_ref`,
`approver_policy_sha256` ve `approver_policy_ref` ise yalnizca hukuki karar ve
yetkili-imzaci policy lineage metadata'sidir: referanslar, storage yolu
veya kisi/cihaz kimligi tasimayan
`urn:decision-record:sha256:<64-lowercase-hex>` veya
`urn:approver-policy:sha256:<64-lowercase-hex>` biciminde olmak ve ilgili digest
ile birebir eslesmek zorundadir. `cleared`, ancak iki ayri yetkili insanin Ed25519
imzasini dogrulayan karar-kaydi verifier'i tarafindan uretilir. AI, owner veya
DPO yerine imza atamaz; ham karar kaydi issue marker'ina konmaz.
Marker ayrica signed karar payload digest'ini, iki opaque approver key ID'sini,
imza zamanlarini ve detached imzalari tasir. Audit, bunlari repoda review edilmis
canonical public-key policy
`config/faz22-6-view-only-kvkk-approver-policy.v1.json` ile yeniden dogrular;
policy yoksa, digest'i uyusmuyorsa veya imzalardan biri gecersizse `cleared`
imkansizdir. Canonical policy PII tasimaz; opaque principal'in gercek kisi
eslemesi access-controlled `identityDirectoryRef` arkasindadir.

**Asla** non-blocking'e taşınamaz (mislabel edilirse audit `blocked` döner — Codex constraint #3): `no_control_invariant`, `mtls`, `authz`, `dlp_mask_policy`, `audit_negative_matrix`, `local_abort`, `active_indicator`, `recording_mode`, `ttl_revoke_kill`, `exfiltration_control`, ve **engineering-acceptance owner** (`owner_approved_by` — DPO signoff'tan AYRI tutulur, kaldırılmaz).

### D2 — #1580 marker SPLIT (schema-v2 bump, legacy fail-safe)
`F22_6_VIEW_ONLY_ACCEPTANCE: v1` sessizce mutate edilmez. İki yeni marker:
- **`F22_6_VIEW_ONLY_ENGINEERING: v2`** — FAIL-CLOSED gate. Tam mühendislik kanıt listesini KORUR: non-inert `DataPlaneHandler`, VIEW_ONLY frame akışı, **no-control invariant**, mTLS + authz, TTL/revoke/kill, active indicator, local abort, DLP/mask, audit metadata, negatif matris, HTTPS manifest + `jq -cS` SHA256 eşleşmesi. Hiçbiri legal track'e taşınmaz.
- **`F22_6_VIEW_ONLY_KVKK: v1`** — TRACKED, NON-BLOCKING. Durum: `tracked_pending | cleared | expired`. Görünür kalır, asla `F22_6_COMPLETION`'ı fail-close etmez.
- `cleared` marker, schema-valid karar kaydinin SHA-256 digest'ini ve ayni
  digest'e bagli content-addressed URN'yi tasir. Serbest metin owner/tarih kaydi
  tek basina clearance degildir; iki farkli, engineering-chain disi insan
  imzasi reviewed public-key policy ile dogrulanmadan marker uretilmez.
- Engineering acceptance authority `#1580` olarak kalir. Hukuki karar ve
  `F22_6_VIEW_ONLY_KVKK: v1` marker authority'si takip issue'su `#2374`'tur;
  audit bu iki issue'yu ayri referanslarla okur. Bir issue'daki marker diger
  gate'i geciremez.
- Hukuki karar payload'i uc ayri authority/evidence bagini birlikte imzalar:
  engineering `#1580`, viewer product `#2373`, legal tracking `#2374`; ayrica
  `#2373` viewer-product evidence digest/ref'i protected kayitta zorunludur.
- Marker `v1`, legal decision schema `faz22.6-...-decision-v1`, verifier result
  `...verifier-v1` ve engineering evidence `v2` ayri version namespace'leridir;
  biri digerinin schema versiyonu degildir.

**Legacy fail-safe (Codex #2)**: eski bundled `F22_6_VIEW_ONLY_ACCEPTANCE: v1` marker'ı yeni engineering gate'i **otomatik geçemez**; audit `legacy_bundled_marker_detected` raporlar (acceptance sayılmaz). Yeni v2 engineering alanları manifest'te mevcut + hash'li olmadan pass yok.

### D3 — Parametrik süreler + privacy-safe default (mode-based)
- **Content-recording DEFAULT = `disabled`** (en privacy-koruyucu): MVP = saf canlı VIEW_ONLY, **içerik persist edilmez** → retention/KVKK bağımlılığı YOK.
- **Session metadata audit = HER ZAMAN açık** (kim/ne zaman/hangi cihaz/süre — güvenlik, KVKK-hafif; kapatılamaz).
- **Recording opt-in (`enabled`) olduğunda** retention **parametrik**: config key + `min`/`max` + `unit` (gün) + `effective value` + **owner-decision reference** zorunlu; ve WORM + record-before-fanout + recording-down negatif testi yeniden **fail-closed**.

Parametrik config anahtarları (Helm values / ConfigMap; owner uygun değeri verince uygulanır):

| Key | Default | Bound | Not |
|---|---|---|---|
| `remote_ops.view_only.recording_mode` | `disabled` | `disabled\|enabled` | enabled → D5 negatif proof + retention zorunlu |
| `remote_ops.view_only.recording_retention_days` | `0` (N/A; disabled iken) | `min 1, max <owner>` | yalnız `enabled` iken; owner-decision-ref zorunlu |
| `remote_ops.view_only.session_metadata_retention_days` | `<conservative-default>` | `min 1` | always-on metadata; owner-override parametrik |

KVKK A3 retention kalemleri (ekran-gözlemi içerik retention, audit 7yr) bu parametrelerle owner/DPO-kararlı; **kod-değişikliği veya blocker değil** — owner değeri verir, config'e yansır.

### D4 — `F22_6_COMPLETION` yalnız engineering + #548 + live broker/release
Audit **İKİSİNİ DE** emit eder (Codex #4):
- `F22_6_VIEW_ONLY_ENGINEERING=pass|blocked`
- `F22_6_VIEW_ONLY_KVKK=tracked_pending|cleared|expired`

`F22_6_COMPLETION` = `F22_6_VIEW_ONLY_ENGINEERING` **+** `GATE_B1_4` (#548) **+** live broker/release kanıtı (REMOTE_BRIDGE_LIVE + RELEASE_LINEAGE) yalnız. KVKK **görünür** kalır (pending), ama completion'ı fail-close ETMEZ.

### D5 — `recording_mode=disabled` kendi negatif proof'unu ister (Codex #4)
"Recording off" test-edilmemiş bir privacy iddiası olmasın: `disabled` modda manifest **pozitif olarak** kanıtlar — (a) config value `disabled`, (b) runtime effective value `disabled`, (c) **no content object/storage write path active**, (d) recording'i kapatmanın metadata audit'i kapatMADIĞI negatif kontrolü. `enabled` modda: WORM + record-before-fanout + recording-down negatif + retention parametresi fail-closed.

### D6 — #1580 issue state ikincil (Codex #5)
Pass koşulu = marker + manifest + live evidence hash + geçerli **engineering** owner approval + non-expired pencere. Issue closed/open state'i tek başına ASLA yeterli değil. #1580 ancak **taze v2 engineering manifest** üretildikten sonra kapanır.

### D7 — Dar test pilotu yetkisi hukuki clearance değildir

Owner, `#2373` için tek cihazlı ve attended TEST pilotunda provider-distinct AI
danışma mutabakatının mühendislik/risk yetkisi olarak kullanılmasına izin
verebilir. Bu yetki yalnız aşağıdaki koşulların tümü fail-closed doğrulandığında
geçerlidir:

- owner direktifi ve MiniMax M3 + Codex `AGREE` danışma kaydı GitHub yorum ID,
  OWNER association, URL ve içerik SHA-256 ile bağlanır;
- AI kaydı `advisoryOnly=true` taşır; `#2374` açık ve `tracked_pending`,
  `legalClearanceClaimed=false` kalır;
- kapsam TEST, tek operator/cihaz, attended VIEW_ONLY, kayıt kapalı, ekran içeriği
  kalıcı değil, auto-consent kapalı, görünür gösterge ve local-abort zorunludur;
- GitHub Environment required reviewer + `prevent_self_review=true` uygular;
  operator/cihaz opaque SHA-256 binding'leri farklıdır ve receipt en fazla 120
  dakika geçerlidir;
- güncel revocation ledger, cluster-side mutlak-expiry watchdog ve compensating
  rollback exposure'u geri çekebilir;
- ürün acceptance'ı yalnız gerçek endpoint `CONSENT_GRANTED` sinyaline bağlı,
  content-addressed consent artefaktı dahil yedi bağımsız kaynakla kanıtlanır.

Bu sözleşme `F22_6_VIEW_ONLY_KVKK: v1=cleared` üretmez, iki insan imzasının
yerine geçmez ve production/broad-rollout/multi-viewer kabulü değildir. Hukuki
clearance istenirse D1-D2'deki iki ayrı yetkili insan imzası aynen zorunludur.

---

## Acceptance criteria (implementation follow-up — Codex 019f05cc 5 constraint)

Aşağıdaki tek atomik PR (contract §7/§9 + audit script + manifest schema **birlikte**) bu kriterleri karşılamadan landlenmez:

1. **Schema-v2 bump**: `F22_6_VIEW_ONLY_ENGINEERING: v2` + `F22_6_VIEW_ONLY_KVKK: v1` ayrı; `v1` bundled mutate edilmez.
2. **Legacy fail-safe**: bundled `F22_6_VIEW_ONLY_ACCEPTANCE: v1` → `legacy_bundled_marker_detected`, pass değil.
3. **Allowlist machine-enforced**: D1 dışı bir anahtar "KVKK/legal" etiketlenirse `blocked`.
4. **recording_mode=disabled negatif proof**: D5'in 4 pozitif kanıtı manifest'te + audit kontrolü.
5. **#1580 state ikincil**: D6 pass koşulu; close yalnız taze v2 manifest sonrası.
6. **Audit test**: yukarıdakilerin her biri için doc-invariant test (marker parse + manifest validate + allowlist reject + legacy detect + mode-based recording + dual output) — `F22_6_COMPLETION_AUDIT_SOURCE_ONLY` harness ile.

---

## Implementation status + sequencing (NO doc-vs-impl gap)

- **BU ADR** = kararın bağlanması (decision record) + acceptance criteria. **`docs/faz-22-completion-action-plan.md`** KVKK'yı paralel non-blocking track'e + parametrik sürelere taşır (bu PR).
- **Contract §7/§9 + audit script + manifest schema** birlikte, **tek atomik follow-up PR**'da revize edilir (bu arc'ın bir sonraki adımı; Codex post-impl review + test). Tek PR olması contract ↔ machine-gate drift'ini engeller (Codex'in orijinal point-5 endişesi).
- **Ara dönemde** mevcut bundled `F22_6_VIEW_ONLY_ACCEPTANCE` gate'i yürürlükte kalır — bu gate **DAHA SIKI** (KVKK'yı hâlâ zorunlu tutar), dolayısıyla **over-claim penceresi YOK**; sistem fail-closed-stricter'da güvende kalır, sonra bu ADR'nin (KVKK-non-blocking ama engineering-strict) gate'ine geçilir.

---

## Consequences

**Pozitif:**
- Mühendislik (B2 #1580 VIEW_ONLY build) KVKK signoff'una bağımlı olmadan ilerleyebilir; owner/DPO paralel çalışır.
- Privacy-safe default (recording OFF) MVP'yi KVKK-içerik-retention'dan ayırır.
- Süreler parametrik → owner kararı kod değişikliği değil, config flip.
- No-fake-work korunur: engineering/security/audit kanıtı fail-closed kalır; sadece hukuki signoff kritik yoldan çıkar.

**Negatif / dikkat:**
- İki marker + mode-based audit, gate mantığını karmaşıklaştırır → kapsamlı test + Codex post-impl review zorunlu (acceptance criteria #6).
- KVKK `tracked_pending` görünür kalmalı; "non-blocking" "unutuldu"ya dönüşmesin diye audit her koşumda KVKK durumunu basar (D4).
- `enabled` recording'e geçince retention + WORM + record-before-fanout fail-closed geri gelir — bu geçiş ayrı, test-edilmiş olmalı.

---

## İlgili

- [ADR-0034](0034-1388-sensitive-endpoint-ops-owner-decision.md) Faz 22.6 sensitive-endpoint-ops owner decision (#1388 gate, owner-signed) — bu ADR onun completion-gate hukuk/mühendislik sınırını netleştirir.
- `docs/runbooks/RB-faz22.6-autonomous-completion-contract.md` (§3/§7/§9 — follow-up PR'da revize).
- `scripts/faz22-remote-ops/faz22-6-completion-audit.sh` (861-satır marker-hardened — follow-up PR'da split).
- `docs/faz-22-completion-action-plan.md` (PART A/B — bu PR'da KVKK reclassify + parametrik).
- KVKK boundary: VERBIS "Diğer: ekran gözlemi" purpose (owner/DPO paralel track).
- Cross-AI: Codex thread `019f05cc-eea8-79b1-9008-2a83b09100dd` (REVISE→AGREE).
