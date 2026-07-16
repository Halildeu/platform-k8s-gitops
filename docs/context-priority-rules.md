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

## 11. Provider İstişare Sırası ve Cursor Adversarial Review

**Kalıcı sıra:** birinci dış istişare kanalı doğrudan Anthropic Claude CLI'dır;
Cursor CLI bundan sonra bağımsız/ilave adversarial ikinci kanaldır. Direct Claude
`claude --version` ile canlı doğrulanır ve headless `claude -p` ile çağrılır.
İlk model tercihi `--model claude-opus-4-8`'dir; JSON `modelUsage` gerçekten
`claude-opus-4-8` dönmeden bu model kullanıldı denmez. Exact model erişilemiyorsa
başarısızlık kaydedilir ve kullanıcı yeni model seçmedikçe daha düşük modele
sessiz fallback yapılmaz. Uzun redacted diff/bağlam stdin üzerinden verilebilir.
Somut bulgu ve verdict üretmeyen boş/limit/auth/error çıktısı başarı değildir.
Attribution `Channel=Direct Anthropic Claude CLI; Model=<exact modelUsage kimliği>;
direct-provider-CLI=true` olur. Cursor-routed Claude bu birinci kanalın yerine
geçmez ve direct Claude ile ikinci bağımsız provider sayılmaz. Hiçbir kanalda
uygulama penceresi fallback'i yoktur.

Yüksek etkili işlerde Cursor adversarial-review/ikinci-görüş kanalı kullanılacaksa ilk model tercihi, yalnız live listede mevcut olduğunda `claude-opus-4-8-thinking-high` olur. Her çağrıdan önce `agent --version` ve `agent --list-models` canlı doğrulanır; slug hafızadan varsayılmaz. Live listede yoksa eşdeğer derin model seçilir ve exact kimliği kanıta yazılır. Model mevcut olduğundaki salt-okunur çağrı:

```bash
agent -p 'REDACTED_GOREV' --output-format text --mode ask --trust \
  --workspace <ABSOLUTE_WORKTREE> \
  --model <LIVE_MODEL_ID>
```

Attribution `Channel=Cursor CLI; Model=<LIVE_MODEL_ID>; direct-provider-CLI=false` olur. Bu yol direct Anthropic çağrısı değildir. Plan/mimari/deploy/rollback/scope kararlarında aşağıdaki rol tablosundaki canonical provider-distinct istişare yolu korunur; Cursor model önceliği bu karar yolunu düşürmez. İşletici/reviewer zaten Anthropic Claude ailesindeyse Cursor-routed Claude aynı-aile bağımsız reviewer sayılmaz ve provider-distinct gate Codex, MiniMax veya başka bağımsız sağlayıcıyla doldurulur. Doğrudan Claude CLI birinci istişare yoludur; `claude --version`/`--help` doğrulamasından sonra mümkünse JSON çıktı alınır ve gerçek model kimliği `modelUsage` anahtarından kaydedilir. Direct yol `Channel=Direct Anthropic Claude CLI; Model=<MODEL_USAGE_ID>; direct-provider-CLI=true` diye raporlanır; CLI'nin `--model opus` alias'ı exact sayısal sürüm diye varsayılmaz.

Exact Cursor modeli unavailable, auth/limit hatalı, boş ya da somut verdict üretmiyorsa başarısızlık açık kaydedilir. Cursor, MiniMax M3 veya başka provider-distinct kanal Direct Claude sonrasında ikinci görüş/fallback olabilir; hiçbir durumda uygulama penceresi kullanılmaz. Prompt veya süreç girdisine secret, token, credential ya da PII konmaz. Cursor-routed Claude ile direct Claude aynı model sağlayıcı ailesine ait olabileceğinden tek başına iki bağımsız provider sayılmaz. Bu sıra, provider-distinct Cross-AI gereksinimini veya test/CI/live evidence/board/insan gate'lerini azaltmaz.

### Cursor CLI — öncelikli ilave adversarial review

Cursor, faz/plan/PR istişaresinde uygulama penceresi üzerinden kullanılmaz. Yalnız canlı doğrulanmış CLI veya mevcutsa aynı redaction ve salt-okunur sınırını sağlayan MCP yolu kabul edilir. CLI/MCP, credential veya somut verdict yoksa UI fallback yapılmaz ve Cursor review kanıtı yazılmaz.

### 11.1 Rol sırası

| Karar/kanıt yüzeyi | Canonical yol | Cursor rolü |
|---|---|---|
| Plan, mimari, deploy, rollback veya scope kararı | **Önce Direct Anthropic Claude CLI**; ardından gerekiyorsa provider-distinct kanal; Claude oturumunda `CLAUDE.md` Codex MCP kuralı | İkinci/ilave görüş; canonical karar yolunu düşürmez |
| Post-implementation güvenlik ve merge-readiness incelemesi | Exact branch/diff + test/CI kanıtıyla **önce Direct Anthropic Claude CLI** | **İkinci ilave adversarial reviewer** |
| PR provider-level cross-AI gate | PR `## Cross-AI` alanları + `gate-cross-ai-audit` | Ek review; structured gate'in yerine geçmez |
| Runtime, ürün veya hukuk kabulü | Live evidence + board + Owner/Legal/DPO/InfoSec/customer gate | Yerine geçmez |

Implementasyon Cursor worker ile üretildiyse aynı Cursor kanalı reviewer olarak provider-distinct kanıt sayılmaz. Cursor gate katılımcısı ancak worker/reviewer provider ayrımı canlı model ve gerçek implementer kaydıyla kanıtlanabiliyorsa structured alana yazılır. Ayrım doğrulanamıyorsa sonuç yalnız ek adversarial review'dur; gerçek provider-distinct review ayrıca alınır ve structured `Reviewer AI` alanını o reviewer doldurur.

### 11.2 Her çağrıdan önce canlı doğrulama

1. Önce PATH'teki `agent`, bulunamazsa `$HOME/.local/bin/agent` denenir.
2. `--version` ve `--list-models` aynı oturumda çalıştırılır.
3. Model adı, availability veya sürüm hafızadan alınmaz. Hız/derinlik seçimi yalnız canlı model listesi ve görev riskine göre yapılır.
4. Repo dışı bir harness kullanılacaksa önce kendi availability/list komutuyla doğrulanır; host-specific mutlak yol canonical varsayım değildir.

Salt-okunur doğrudan kalıp:

```bash
agent -p 'REDACTED_GOREV' \
  --output-format text \
  --mode ask \
  --trust \
  --workspace <ABSOLUTE_WORKTREE> \
  --model <LIVE_MODEL_ID>
```

`--trust` yalnız `--mode ask` ile kullanılabilir. MCP yolu kullanılırsa da write/tool yetkisi kapalı olmalı ve exact diff/evidence referansı salt-okunur verilmelidir.

### 11.3 Redaction ve process sınırı

`-p` argümanı shell history ve process argv yüzeyine düşebilir. Prompt/argümana şunlar yazılmaz:

- secret, JWT, refresh token, raw bearer
- webhook URL, cookie, OAuth client secret
- private key, signing key, HMAC secret
- admin credential, root token veya password
- kullanıcı email, telefon, UPN veya diğer PII

Yalnız redacted görev özeti ile repo içi evidence path, issue veya PR referansı gönderilir. `ps`, `pgrep` veya eşdeğer araçlarla agent süreç komut satırı dump edilmez. Raw secret/PII içeren task-file da güvenli fallback değildir.

### 11.4 Başarı ve attribution kontratı

`exit=0` tek başına başarı değildir. Çıktı boşsa veya limit/auth/error metni ise review tamamlanmış sayılmaz. Kabul edilen kanıt exact branch/diff'i okuyan somut bulgular ve `AGREE|REVISE|PARTIAL|RED` benzeri net verdict taşır.

Cursor içinden seçilen Claude/GPT/Composer modeli direct Anthropic/OpenAI CLI görüşü diye raporlanmaz. İki kayıt modu vardır:

1. **Provider ayrımı kanıtlı gate katılımcısı:** Cursor reviewer ise `Reviewer AI: Other`, Cursor worker ise `Implementer AI: Other` kullanılır. İki durumda da kanal/model bilgisi `Verdict reason` içine yazılır.
2. **Supplemental adversarial review:** Provider ayrımı kanıtlı değilse `Implementer AI` ve `Reviewer AI` gerçek provider-distinct gate çiftini gösterir; Cursor sonucu `Absorb edilen düzeltmeler` alanında `Supplemental Cursor CLI / <LIVE_MODEL_ID>` diye kaydedilir. Cursor structured reviewer slotunu devralmaz.

Gate-katılımcısı reviewer örneği:

```yaml
Reviewer AI: Other
Verdict reason: Channel=Cursor CLI; Model=<LIVE_MODEL_ID>; direct-provider-CLI=false; <somut özet>
```

Gate-katılımcısı worker örneğinde `Implementer AI: Other` kullanılır ve aynı `Verdict reason` kanal/model alanları korunur. Bu mapping yalnız kanal attribution'ını çözer; provider-distinct olmayı otomatik kanıtlamaz. Implementer/reviewer provider ayrımı ayrıca doğru ve denetlenebilir olmalıdır.

### 11.5 Acceptance gate bypass değil

Cursor review şunların yerine geçmez:

- `gate-cross-ai-audit` ve PR `## Cross-AI` structured alanları
- test, CI ve exact-head/digest kanıtı
- board claim/status ve deliberate acceptance
- D29 Up/Functional/Zanzibar-ready veya browser smoke
- Owner/Product, Legal/DPO, InfoSec, customer veya production operator kararı

Review sonucu önce bulgu listesine çevrilir; doğrulanan P0/P1 bulguları absorbe edilip exact diff yeniden incelenmeden merge-readiness dili kullanılmaz.

### Detay

- Kısa HARD RULE: [AGENTS.md §3](../AGENTS.md)
- PR structured alanları: [.github/pull_request_template.md](../.github/pull_request_template.md)
- Claude oturumlarının plan/mimari Codex MCP tamamlayıcısı: [CLAUDE.md Ana Kurallar #8](../CLAUDE.md)
