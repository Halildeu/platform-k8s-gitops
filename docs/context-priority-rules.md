# Context Priority Rules — platform-k8s-gitops

Bu doküman repo içindeki **canonical bağlam çözümleme sözleşmesi**dir. Amaç, bir agent veya operatörün:

- hangi soruda hangi dokümanı önce okuyacağını,
- hangi kanıt sınıfını hangi dokümana üstün tutacağını,
- `test -> prod` geçişini hangi semantik kapılarla yorumlayacağını,
- repo sınırlarını ve claim disiplinini tek yerden uygulamasını sağlamaktır.

İlk giriş yüzeyi: [../AGENTS.md](../AGENTS.md)

---

## 1. Bu Doküman Ne İçin Var

Bu repo içinde aynı kavram farklı dosyalarda geçebilir. Bu normaldir; fakat şu ayrım net kalmalıdır:

- `README.md` ve `docs/README.md` gezinme yüzeyidir
- `current-state` canlı truth snapshot'ıdır
- `ADR-0002` aktif mimari karardır
- `PLAN.md` roadmap ve done kriteri kaynağıdır
- runbook'lar operasyon adımlarını tarif eder
- handoff belgeleri tarihsel bağlam taşır

Bu doküman, yukarıdaki katmanların **hangi sırayla ve hangi niyetle** okunacağını belirler.

---

## 2. Otorite Zinciri

### 2.1 Kural Çözümü

Bir agent veya operatör repo içindeki kural çatışmasını şu sırayla çözer:

1. [../AGENTS.md](../AGENTS.md)
2. Bu doküman
3. Göreve ait doğrudan live evidence
4. İlgili canonical çalışma dokümanı

`CLAUDE.md`, `README.md`, `docs/README.md` ve handoff belgeleri bu iki katmanı override edemez.

### 2.2 Truth Çözümü

Bir iddia için gerçeklik sırası şöyledir:

1. **Doğrudan live evidence**
   `ssh`, `kubectl`, `curl`, `docker`, `gh`, Prometheus, log, imageID, rollout durumu
2. [state/current-state.md](./state/current-state.md)
   En güncel yazılı truth snapshot
3. [adr/0002-single-host-dual-cluster.md](./adr/0002-single-host-dual-cluster.md)
   Aktif mimari hedef ve kontrat
4. [../PLAN.md](../PLAN.md)
   Faz, done kriteri, roadmap
5. İlgili runbook
   Uygulama sırası ve operasyon detayı
6. Navigator / yardımcı yüzeyler
   `README.md`, `docs/README.md`, `CLAUDE.md`
7. Historical belgeler
   `docs/session-handoff-*.md`, eski plan/review notları

Bir conflict varsa daha yukarıdaki katman aşağıdakini yener.

### 2.3 Soru Türüne Göre İlk Kaynak

| Soru tipi | İlk kaynak | İkinci kaynak | Not |
|---|---|---|---|
| "Şu an ne durumda?" | live evidence | `docs/state/current-state.md` | CI veya eski handoff tek başına yeterli değildir |
| "Hedef mimari ne?" | `ADR-0002` | bu doküman | Aynı-host dual-cluster ana yoldur |
| "Sıradaki faz ne?" | `PLAN.md` | `current-state` | Faz ilerleme iddiası live truth ile teyit edilir |
| "Aktif iş ne / sıradaki ne?" | [platform Roadmap board](https://github.com/users/Halildeu/projects/2) | `docs/board-protocol.md` | Board aktif iş + risk + milestone/gate `Status` için canonical |
| "Nasıl uygularız?" | ilgili runbook | `PLAN.md` | Runbook yoksa önce plan/kontrat netleştirilir |
| "Bu repo neyi sahipleniyor?" | bu doküman | `README.md` | Repo sınırı aşağıda tanımlı |

---

## 3. Repo Sınırı

### 3.1 Bu Repo Ne Değildir

`platform-k8s-gitops`:

- uygulama kaynak kodu repo'su değildir
- backend feature geliştirme backlog'u değildir
- image build otoritesi değildir
- canonical kaynak repo'ların (`platform-backend` / `platform-web`) yerine geçen repo değildir

### 3.2 Bu Repo Ne İçindir

Bu repo:

- Kubernetes desired-state
- host bootstrap ve stateful split hazırlığı
- ArgoCD / ESO / monitoring / ingress / cutover
- manifest, overlay, runtime governance ve operational truth closure

repo'sudur.

### 3.3 Kaynak Repo Sınırı

Uygulama kaynak kodu ve artifact üretimi:

- repo: `platform-backend` (backend) + `platform-web` (frontend) — canonical kaynak repo'lar (`platform-ssot` 2026-04-25'ten beri DEPRECATED, audit-only)
- sorumluluk: backend/frontend code, Dockerfile, immutable image build, runtime config profilleri

Bu repo ise o artifact'leri **digest/tag düzeyinde** consume eder ve cluster/edge'e taşır.

---

## 4. Semantik Kapılar

### 4.1 D29 Kanıt Disiplini

Tek kelimelik "green" veya "çalışıyor" ifadesi geçersizdir. Her işlev üç ayrı seviyede konuşulur:

1. **Up**
   Pod/endpoint ayakta, temel ulaşılabilirlik var
2. **Functional**
   Ana işlev doğru dependency ile gerçekten çalışıyor
3. **Zanzibar-ready**
   Authz plane doğru env ile ayağa kalkmış, allow/deny sentetikleri enforce ediyor

Bu üç seviye birbirinin yerine kullanılamaz.

### 4.2 D30 Artifact Disiplini

- moving tag kanıt değildir
- `sha-<short>` veya digest pin gerekir
- prod readiness için `pod imageID == beklenen artifact` eşleşmesi aranır

### 4.3 Authoritative Entrypoint

Bir smoke sonucu sadece doğru hop sınıfından geldiyse anlamlıdır.

Örnek:
- external edge için browser/public URL veya host-level `curl`
- cluster-internal port-forward yalnızca yardımcı kanıttır

Cluster-bypass başarıları gerçek kullanıcı yolunu tek başına ispatlamaz.

### 4.4 No Closure Language

Bu repo içinde plan, handoff ve durum dili kapanış değil **devamlılık** üretir.

Yasak örnekler:
- "bitti"
- "tamamlandı"
- "kapanış"
- "soft cutover yapıldı"

Doğru yaklaşım:
- mevcut truth
- kanıt sınıfı
- blocker
- sıradaki kapı

### 4.5 Faz 24 Legal Track vs Engineering Gate

Faz 24 Meeting Intelligence için KVKK/VERBIS/hukuk owner acceptance, owner
bildirimi kayda alındıktan sonra mühendislik completion blocker'ı değildir.
Mühendislik değerlendirmesi şunları arar:

- retention/silme süreleri owner tarafından sonra verilebilen parametrelerdir;
  hardcoded süre veya sınırsız default kabul edilmez
- eksik owner duration değeri veya sabit süre seçilmemiş olması engineering
  blocker değildir **yalnız** fail-closed/refuse-to-store default aktifse;
  owner uygun değeri verdiğinde config/evidence olarak uygulanır
- saklama default'u fail-closed olur: owner parametresi yoksa durable storage
  açılmaz veya ilgili path refuse-to-store davranır
- consent default required, deletion pipeline default enabled, redaction/audit
  kontrolleri machine-checkable evidence ile doğrulanır
- legal acceptance, VERBIS güncelliği, DPA veya production legal go agent/CI/PR
  tarafından iddia edilmez
- veri akışı, recording/retention modu, consent/deletion boundary veya
  legal-vs-engineering ayrımı değişirse `ADR-0030` D6 tetiklenir; karar önce
  provider-distinct cross-AI istişareyle değerlendirilir ve ADR'ye bağlanmadan
  canonical kural sayılmaz

Doğru status dili: "engineering G-COMP controls pass/pending", "legal track
parallel/pending", "production legal go owner-gated". Yanlış status dili:
"KVKK accepted", "VERBIS closed", "legal review not required" veya legal
pending olduğu için mühendislik gate'ini otomatik blocked saymak.

---

## 5. Testten Proda Promotion Semantiği

Bu repo için promotion zinciri aşağıdaki sırayla yorumlanır:

1. `platform-backend` / `platform-web` CI'ında artifact (immutable image) üretilir
2. artifact immutable referansla bu repoya taşınır
3. `testai.acik.com` üzerinde D29 seviyeleri kanıtlanır
4. soak / monitoring / blocker kapıları temizlenir
5. prod preflight ve secret delivery doğrulanır
6. atomic cutover yapılır
7. `72h` rollback-window boyunca sıcak geri dönüş korunur
8. ancak bundan sonra decommission konuşulur

### 5.1 Test Otoritesi

`testai.acik.com` canlı ve authoritative gate'tir. Şunlar netleşmeden prod ready denmez:

- edge doğru backend'e gidiyor mu
- authn zinciri doğru mu
- Zanzibar authz plane gerçek allow/deny enforce ediyor mu
- blocker alert temiz mi

### 5.2 Prod Otoritesi

`ai.acik.com` için prod readiness; yalnız manifest render veya pod Ready ile değil, şu kombinasyonla değerlendirilir:

- prod stateful split gerçek mi
- secret delivery zinciri gerçek mi
- artifact immutable ve doğrulanmış mı
- cutover runbook uygulanabilir mi
- rollback-window gerçek mi

---

## 6. Canlı Değişiklik Disiplini

Canlı sisteme dokunmadan önce minimum kayıt:

1. hedeflenen değişiklik
2. neden şimdi gerektiği
3. hangi kanıtla doğrulanacağı
4. rollback etkisi

Canlı değişiklikten sonra minimum kapanış değil, minimum **truth closure** gerekir:

1. live kanıt toplanır
2. gerekiyorsa `docs/state/current-state.md` güncellenir
3. varsa roadmap/done dili düzeltilir
4. hâlâ açık blocker net yazılır

Repo dışında yapılan hotfix, repo truth'una geri bağlanmadıkça geçici kabul edilir.

---

## 7. Dokümantasyon Rol Haritası

| Doküman sınıfı | Rol | Override yetkisi |
|---|---|---|
| `AGENTS.md` | giriş yüzeyi ve hard rule | en yüksek |
| Bu doküman | bağlam çözümleme sözleşmesi | yüksek |
| `docs/state/current-state.md` | canlı truth snapshot | live evidence altında |
| platform Roadmap board (Project #2) | aktif iş + açık risk + milestone/gate `Status` | live evidence altında |
| `docs/board-protocol.md` | board okuma/güncelleme protokol sözleşmesi | yüksek (board mekaniğinde) |
| `docs/adr/*.md` | aktif mimari karar | current-state'i override etmez |
| `PLAN.md` | roadmap ve faz kontratı | live truth'u override etmez |
| Runbook'lar | operasyon uygulama sırası | karar üretmez, uygular |
| `README.md`, `docs/README.md`, `CLAUDE.md` | navigator / yardımcı yorum | düşük |
| Handoff'lar | tarihsel bağlam | en düşük |

---

## 8. Uygulama Kuralı

Bu repoda yeni bir kritik kural eklenecekse:

1. önce `AGENTS.md` ve bu dokümana yazılır
2. sonra gerekiyorsa README/PLAN/current-state buna referans verecek şekilde güncellenir
3. aynı kural rastgele farklı dosyalarda sessizce çoğaltılmaz

Amaç, kural üretimini tek yerde toplamak; navigator ve historical dokümanlar yalnız bu çekirdeği yansıtmalıdır.

---

## 9. Board — Aktif İş Takibi

Aktif iş durumu, açık risk/issue ve milestone/gate `Status`'ü **[platform Roadmap board](https://github.com/users/Halildeu/projects/2) (GitHub Project #2)** üzerinde canonical tutulur. Board pasif bir snapshot değil; agent'ların okuyup güncellediği aktif iş yüzeyidir.

- **Executable iş = gerçek issue.** Agent'ın claim edeceği / PR bağlayacağı / state güncelleyeceği iş gerçek GitHub issue olur; draft item yalnız umbrella/roadmap özeti içindir. Issue, işin yapılacağı repo'da açılır.
- **Oturum ritüeli.** Oturum başında board okunur, uygun iş claim edilir (`scripts/board-sync.sh`); çalışırken `Status=In Progress` + kanıt comment'i; bitince acceptance evidence sonrası deliberate close → `Done`.
- **Overclaim guard.** `Done` yalnız accepted/live (§4.1 D29 ile uyumlu — `source-ready ≠ live-deployed ≠ accepted`). PR-merge bir runtime issue'sunu otomatik `Done` yapmaz; runtime tracking issue'sunda PR body `Tracked by #N` kullanır, `Closes/Fixes/Resolves` değil. `Needs Verify` acceptance kuyruğudur.
- **Curated board.** Board roadmap/risk yüzeyidir, intake kuyruğu değil. Normal code PR board'a girmez; roadmap-visible iş `project-roadmap` label ile alınır.
- **Backlog lane (iter-3).** İş sırasında keşfedilen scope-dışı iş/sorun `board-sync.sh backlog-add` ile `Backlog` statüsünde yakalanır — kaybolmaz, ama eligible değil (roadmap view kirlenmez); triage'da `Todo`ya alınır. `spawn_task` chip'i tek başına yeterli değil (ephemeral; board truth üretmez).
- **Source-of-truth sınırı.** Board aktif iş `Status`'ü için canonical; `current-state.md` runtime truth kalır; bir item iki yerde bağımsız yürütülmez.

Detaylı protokol (agent-state şablonu, claim protokolü, comment taxonomy, eligible-work filtresi): **[docs/board-protocol.md](board-protocol.md)**.

---

## 10. Agent İletişimi — Mavis CLI

Lokal agent'lar (paralel Claude session'lar dahil) arası ve kullanıcı ile koordinasyon kanalı **Mavis CLI**'dir. Multi-session geliştirme modelinde paralel agent koordinasyonu için tek standart kanal.

### 3 Yol (öncelik sırası)

- **Session ID** (en kesin): `mvs_<id>` — bilinen session'a direkt mesaj
- **Agent name** (daha portable): `agent-<name>` — session crash'inde Agent name persist, yeni session ile devam eder
- **`peers`** (discovery): kim erişilebilir görmek için

```bash
# Discovery
mavis communication peers

# Send (Session ID veya Agent name ile)
mavis communication send --to <id|name> --command prompt --content "..."
```

### Ne zaman

- Multi-session paralel iş koordinasyonu
- Async tamamlanma bildirimi (örn. "build done, deploy hazır")
- Agent handoff / iş paylaşımı / context transfer
- Long-running operation trigger gönderme

### Redaction guard (zorunlu)

`--content` içine **YASAK**:

- Secret, JWT, refresh token, raw bearer
- Webhook URL, cookie, OAuth client secret
- Private key, signing key, HMAC secret
- Admin credential (password, root token)
- Kullanıcı PII (kullanıcı email/telefon/UPN)

Sebep: `--content` shell history, process list, Mavis transport/log queue ve karşı peer transcript'ine düşebilir. Gerekirse sadece **redacted özet + evidence path/issue/PR linki** gönderilir.

### Acceptance gate bypass değil

Mavis bildirimi **yerine geçmez**:

- Board claim (`Claim-before-work` kuralı bypass değil)
- Live evidence (D29 Up/Functional/Secured ayrı kanıt)
- Browser smoke kanıtı (HARD RULE Tarayıcıdan Sonuç Doğrulanmadan)
- PR/CI truth (HARD RULE CI Kırmızıyken Merge YASAK)
- Runtime acceptance (No Fake Work — yalnız koordinasyon kanıtı)

"X session'a haber verdim" demek "iş bitti / accepted" demek **değildir**. Acceptance ayrı kapı; Mavis sadece async iletişim kanalı.

### Detay

- Repo: [AGENTS.md §3 HARD RULE](../AGENTS.md) (kısa canonical bullet) + [CLAUDE.md Ana Kurallar #0](../CLAUDE.md) (proje-spesifik genişletme)
- Global: `~/.claude/CLAUDE.md` — "HARD RULE — Lokal Agent İletişimi: Mavis CLI" (tüm projeler için kapsamlı geniş açıklama + akış detayları + HARD RULE bağlantıları)

---

<a id="cross-ai-three-channel"></a>

## 11. Zorunlu Üç Kanallı Cross-AI İstişare

Faz/plan/PR ikinci görüşü ile authz, kişisel veri, retention/silme, migration,
concurrency, cutover, faz kapanışı ve merge-readiness gibi yüksek etkili kararlar
aynı exact scope veya commit üzerinde aşağıdaki üç headless kanalda incelenir:

1. **Anthropic:** doğrudan Claude CLI ile **`claude-opus-4-8`**.
2. **MiniMax:** resmi bundled headless provider CLI ile
   **`minimax/MiniMax-M3`**.
3. **OpenAI:** doğrudan Codex CLI ile **`gpt-5.6-sol`**.

Cursor kullanım yolu, kullanıcının 2026-07-17 tarihli doğrudan üç sağlayıcı
kararıyla bu kural setinden kaldırılmıştır; canonical karar kaydı
[#2601](https://github.com/Halildeu/platform-k8s-gitops/issues/2601)'dir. Cursor CLI, Cursor MCP, Cursor modeli,
Cursor harness'i ve Cursor-routed modeller bu üç kanaldan biri olarak
kullanılamaz. Bir sağlayıcının başka wrapper üzerinden çağrılması yeni ve
bağımsız sağlayıcı sayılmaz.

### 11.1 Headless çağrı ve model kimliği

```bash
# Kurulu flag/capability doğrulaması
claude --version && claude --help
codex --version && codex exec --help
python3 scripts/ai/minimax_m3_review.py --help

# Tüm PR aralığını bir kez hazırla; secret bulgusunda fail-closed, email PII redacted
BASE_SHA="$(git merge-base origin/main HEAD)"
HEAD_SHA="$(git rev-parse HEAD)"
SCOPE_RECEIPT="$(python3 scripts/ai/prepare_cross_ai_scope.py \
  --base-ref origin/main --base-sha "$BASE_SHA" --head-sha "$HEAD_SHA")"
BASE_TIP_SHA="$(printf '%s' "$SCOPE_RECEIPT" | jq -r .base_tip_sha)"
SCOPE_PATH="$(printf '%s' "$SCOPE_RECEIPT" | jq -r .scope_path)"
SCOPE_SHA256="$(printf '%s' "$SCOPE_RECEIPT" | jq -r .scope_sha256)"

# Anthropic — hazırlanmış aynı scope artifact'i stdin'den verilir
claude -p 'Supplied exact PR scope için adversarial review yap.' \
  --model claude-opus-4-8 \
  --permission-mode plan --tools '' \
  --output-format json --no-session-persistence < "$SCOPE_PATH"

# MiniMax — bundled llm-call üstündeki repo-owned receipt transport
python3 scripts/ai/minimax_m3_review.py \
  --base-sha "$BASE_SHA" --head-sha "$HEAD_SHA" < "$SCOPE_PATH"

# OpenAI — aynı scope; user config/rules bu bounded review'a eklenmez
codex exec --model gpt-5.6-sol \
  --sandbox read-only --ephemeral --ignore-user-config --ignore-rules \
  -C <ABSOLUTE_WORKTREE> \
  'Supplied exact PR scope için adversarial review yap.' < "$SCOPE_PATH"
```

Ham `git show/git diff | provider` kalıbı canonical değildir. Hazırlayıcı,
verilen base'in `--base-ref` için gerçek merge-base olduğunu doğrulayıp
`BASE...HEAD` aralığının tamamını alır; gitleaks veya yüksek güvenli secret
bulgusunda hiçbir provider çağrılmadan durur. Binary veya başka metinsel olmayan
değişiklik `binary_scope_unsupported` ile fail-closed olur; bu kapsam için tam
inceleme iddiası üretilmez. Hazırlayıcı email/UPN ve Türkiye mobil telefon
biçimli PII'yi redakte eder ve
üç kanalın okuyacağı aynı mode-0600 artifact için SHA-256 üretir. Artifact
tamamlanınca yerel dosya silinir. Her push/yeni head scope'u hükümsüz kılar;
hazırlama ve üç review yeni exact head için baştan çalıştırılır.
Otomatik tarayıcının kapsamadığı isim veya serbest metinli kişisel veri varsa
çağrı yapılmaz; scope ayrıca elle redakte edilip yeniden content-address edilir.
Varsayılan 2 MB sınırı `--max-bytes` ile en çok 16 MB'a çıkarılabilir; sağlayıcı
context sınırına sığmayan scope tek tek eksiltilmez, aynı sıralı chunk manifesti
üç kanala da verilene kadar `tracked_pending` kalır.

`scripts/ai/minimax_m3_review.py`, kurulu resmi bundled `llm-call` betiğini
kullanan onaylı headless **transport**tur; kendi başına provider değildir.
Prompt'u yalnız stdin'den alır, auth materialini yazdırmaz, trusted bundled
dosyanın current-user ownership/no-group-world-write sınırını, transport
dosyasından canonical `~/.mavis` köküne kadar tüm üst klasörlerin owner ve
no-group-world-write sınırını, çalıştırılan exact byte'ların transport digest'ini,
provider adı + resmi `agent.minimax.io` origin'ini doğrular ve provider response
modeli `minimax/MiniMax-M3` değilse fail-closed olur. Terminal ve tekil
`VERDICT: AGREE|REVISE` ile P0/P1/P2 bölümlerini ayrıca zorlar. Geçici wrapper, model
değiştiren proxy, UI veya exact provider/model kimliği üretmeyen taşıma yolu
canonical değildir.
`transport_sha256` denetim kaydıdır; published vendor signature/allowlist olmadığı
için provider imzası sayılmaz. Current-user owned `~/.mavis` bundled install
yerel supply-chain trust boundary'sidir ve başka `MAVIS_HOME`/data-dir override'ı
kabul edilmez.

Model slug'ı hafızadan varsayılmaz. CLI `exit=0` olsa bile boş çıktı, auth/kota
metni, model fallback'i veya model kimliği bulunmayan yanıt gerçek review
değildir. Claude JSON `modelUsage`, MiniMax receipt JSON
`provider/requested_model/actual_model`, Codex başlangıç receipt'i ise
`provider/model/session id` alanlarını kanıtlar. Her turda provider,
`requested_model`, provider-reported `actual_model`, exact commit/scope,
`VERDICT: AGREE|REVISE`, somut P0/P1/P2 bulguları ve receipt referansı kaydedilir.
Bu asgari yapıyı taşımayan özet/belirsiz metin `tracked_pending` sayılır.

### 11.2 Mutabakat ve bağımsızlık

- İlk `REVISE` bulguları kod/kanıtla doğrulanır ve geçerli olanlar absorbe edilir.
- Düzeltmeden sonra aynı exact head üç kanala yeniden verilir; her üç kanal
  doğrulanmış `AGREE` verene kadar ping-pong sürer.
- Implementer ile aynı sağlayıcının zorunlu kanalı adversarial challenger olarak
  tutulur fakat bağımsız-provider onayı sayılmaz. Bağımsızlık her durumda
  implementer dışındaki diğer iki doğrudan sağlayıcıdan gelir.
- `tracked_pending`, `REVISE`, provider/model uyuşmazlığı veya çözümsüz ayrışma
  `consensus=false` demektir; merge, deploy, faz kapanışı veya merge-readiness
  yetkisi vermez. PR metnine yazılan bir istisna bu kapıyı aşamaz. Kullanıcı bu
  politikayı değiştirmek isterse #2601'e bağlı ayrı, denetlenebilir governance
  değişikliği gerekir; agent ayrışmayı kendi kendine aşamaz.
- AI mutabakatı test, CI, canlı ortam, tarayıcı smoke, board claim, protected
  Environment reviewer, gerçek kullanıcı rızası veya hukuk/secret-owner
  kapılarının yerine geçmez.

### 11.3 PR receipt ve gate eşlemesi

PR `## Cross-AI` bölümündeki `Implementer AI` / `Reviewer AI` alanları mevcut
provider-distinct alt sınırı korur. Zorunlu üç kanal ayrıca şu structured
alanlarla aynı PR head SHA'sına bağlanır:

```yaml
Consultation base tip: <40-char exact target branch tip SHA>
Consultation base: <40-char exact merge-base SHA>
Consultation commit: <40-char exact PR HEAD SHA>
Consultation scope: <64-char prepared scope SHA-256>
Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; base_tip=<base-tip>; base=<base>; head=<head>; scope=<scope-sha256>; verdict=AGREE; ref=https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/<id>; sha256=<evidence-comment-body-sha256>
MiniMax receipt: provider=minimax; requested=minimax/MiniMax-M3; actual=minimax/MiniMax-M3; base_tip=<base-tip>; base=<base>; head=<head>; scope=<scope-sha256>; verdict=AGREE; ref=https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/<id>; sha256=<evidence-comment-body-sha256>
Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=gpt-5.6-sol; base_tip=<base-tip>; base=<base>; head=<head>; scope=<scope-sha256>; verdict=AGREE; ref=https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/<id>; sha256=<evidence-comment-body-sha256>
```

Her ref'in GitHub issue comment gövdesi yalnız `cross-ai-provider-evidence/v1`
JSON olur; exact provider/model, `base_tip_sha`, `base_sha`, `head_sha`,
`scope_sha256`, `verdict`, tam `response` ve onun `response_sha256` alanlarını
taşır. Üç comment ref'i farklı olmalıdır.

```json
{"schema":"cross-ai-provider-evidence/v1","provider":"anthropic|minimax|openai","requested_model":"<exact>","actual_model":"<provider-reported-exact>","base_tip_sha":"<40hex>","base_sha":"<40hex>","head_sha":"<40hex>","scope_sha256":"<64hex>","verdict":"AGREE","response_sha256":"<64hex>","response":"<full provider response>"}
```

Bu gövde elle yeniden yazılmaz. Provider'ın tam final response'u stdin'den
`scripts/ai/build_cross_ai_evidence.py` betiğine verilir; builder model ve SHA
formatını, tekil terminal verdict'i ve response digest'ini üretir. `REVISE`
yanıtı dürüstçe `REVISE` evidence üretir ve gate'i açmaz.

`gate-cross-ai-audit` trusted base checkout'ta PR head objesini checkout etmeden
fetch eder; gerçek `git merge-base` ve aynı redaction algoritmasıyla full-range
scope SHA-256'yı yeniden türetir. Gitleaks ayrı required security gate olarak
kalır; bu adım `--derive-only` ile yalnız deterministik scope binding yapar.
Base tip event `pull_request.base.sha`, head event `pull_request.head.sha`,
merge-base ve scope ise bu CI türetimiyle eşleşmelidir. Gate her evidence
comment ref'ini event'teki base repository adına bağlar ve GitHub API'den fetch
eder; author login event'teki base repository
owner'ıyla case-insensitive eşleşen, `author_association=OWNER` taşıyan ve hiç
edit edilmemiş (`created_at == updated_at`) comment kabul edilir.
Comment body SHA-256, iç response SHA-256 ve response'un tekil terminal
`VERDICT: AGREE` semantiği yeniden hesaplanır; sonra aynı base-tip/base/head/scope'a
bağlı exact provider/model ve `AGREE` alanları fail-closed doğrulanır. Top-level verdict de yalnız
`AGREE` olabilir. PR body receipt'i provider'ın kriptografik imzası değildir;
fetched audit declaration + content-addressed, unedited owner provenance'dır.
Sağlayıcılar kullanıcı-CLI yanıtlarına doğrulanabilir imza sunmadığı için bu katman
provider kriptografik attestation iddia etmez. Kaynak CLI receipt'i ve
referans verilen evidence korunmadan bu alan tek başına provider çağrısını
kanıtlamaz veya insan kapısını ikame etmez.
`--evidence-file` yalnız offline regresyon fixture'ı içindir; explicit
`--allow-local-evidence-override true` ister ve `GITHUB_ACTIONS=true` iken koşulsuz
reddedilir.

`Codex thread: N/A` body-only istisna değildir. Yalnız workflow'un event-bound
changed-files listesi tamamen `docs/session-handoff-*.md` veya
`docs/archive/*.md` dar historical-docs allowlist'indeyse kullanılabilir.
`AGENTS.md`, `CLAUDE.md`, `PLAN.md`, ADR, governance, workflow, CI, manifest,
authz, migration ve deployment değişiklikleri bu istisnaya giremez.

### 11.4 Redaction ve süreç sınırı

Prompt, argüman ve receipt içine secret, JWT, refresh token, raw bearer, webhook
URL, cookie, OAuth client secret, private/signing/HMAC key, admin credential veya
kullanıcı PII yazılmaz. Yalnız redacted görev özeti ile repo içi evidence path,
issue veya PR referansı verilir. Credential taşıyan süreçlerin komut satırı
ve argv'si `ps`/`pgrep` veya eşdeğer araçla dump edilmez. İstişare hiçbir AI uygulama penceresinden
yürütülmez; CLI/daemon hazır değilse UI fallback yapılmaz.

### Detay

- Kısa HARD RULE: [AGENTS.md §3](../AGENTS.md)
- PR structured alanları: [.github/pull_request_template.md](../.github/pull_request_template.md)
- Claude oturumlarının tamamlayıcısı: [CLAUDE.md Ana Kurallar #0.1 ve #8](../CLAUDE.md)
