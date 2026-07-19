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
  §11'deki durumsal Cross-AI sözleşmesiyle değerlendirilir ve ADR'ye bağlanmadan
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

<a id="cross-ai-consultation"></a>

## 11. Durumsal Cross-AI İstişare — Varsayılan Az Kanal

Kullanıcının [#2621](https://github.com/Halildeu/platform-k8s-gitops/issues/2621)
ve [#2638](https://github.com/Halildeu/platform-k8s-gitops/issues/2638)
kararları, 2026-07-17 tarihli zorunlu üç-kanal politikasını yürürlükten kaldırır
ve MiniMax'i yeni istişare/receipt zincirinden çıkarır. Kullanıcının 2026-07-19
kararı ayrıca zorunlu Claude primary kapısını kaldırır; context-isolated direct
Codex exec'i birincil ve tek başına yeterli Cross-AI reviewer yapar.
Normal kodlama, test, küçük düzeltme, rutin PR ve geri alınabilir uygulama
adımlarında istişare açılmaz. İstişare bir teslimat ritüeli değil, yalnız karar
belirsizliği veya risk için kullanılan sınırlı araçtır.

İki açık acceptance modu vardır:

1. **`none` — varsayılan:** Rutin implementation/test işinde provider çağrısı
   yapılmaz. PR'da somut `Consultation reason` yazılır; receipt üretilmez.
   Changed-files kanıtı eksikse, consultation governance dosyası, yüksek güvenli
   RBAC/NetworkPolicy/Vault-policy/ExternalSecret/migration yolu değişiyorsa veya
   branch `auto-promotion/` ise gate en az `single` zorunlu tutar. Audit/evidence
   enforcement kodunun kendisi değişse de mekanik taban `single` kalır.
2. **`single` — kesin bağımsız Cross-AI review:** Tek ve birincil kanal direct
   OpenAI Codex'tir. Çağrı ayrı bir süreçte, yalnız hazırlanmış exact scope/head
   ile çalışır. PR `Consultation tier: routine|high-impact` alanını zorunlu
   taşır. Path/branch sınıflandırıcısının `single` zorunlu tuttuğu kapsamın
   tabanı `high-impact` olur; path adı nötr olsa bile karar authz, retention,
   concurrency, cutover veya production etkisi taşıyorsa author `high-impact`
   beyan eder. Scope external provider'a verilmeden önce exact scope byte'ları
   owner tarafından secret/PII açısından incelenir ve create-once attestation
   üretilir:

   ```bash
   python3 scripts/ai/attest_cross_ai_scope_pii.py \
     --scope-file <CANONICAL_SCOPE_PATH> \
     --scope-sha256 <CANONICAL_SCOPE_SHA256> \
     --decision no-sensitive-pii \
     --output <CREATE_ONCE_PII_ATTESTATION>
   ```

   Ardından şu zorunlu profil çalışır:

   ```bash
   python3 scripts/ai/run_isolated_codex_review.py \
     --worktree <ABSOLUTE_WORKTREE> \
     --scope-file <CANONICAL_SCOPE_PATH> \
     --scope-sha256 <CANONICAL_SCOPE_SHA256> \
     --pii-attestation-file <OWNER_ONLY_PII_ATTESTATION> \
     --base-ref origin/main \
     --trusted-source-ref origin/main \
     --base-tip-sha <BASE_TIP_SHA> --base-sha <BASE_SHA> \
     --head-sha <HEAD_SHA> --evidence-output <CREATE_ONCE_OUTPUT> \
     --review-tier routine
   ```

   Bu harness doğrudan `codex exec` çalıştırır. Rutin istişarenin varsayılan
   exact modeli `gpt-5.3-codex-spark` olur; governance, güvenlik/authz,
   production promotion, migration ve diğer yüksek etkili scope'ta
   `--review-tier high-impact` exact `gpt-5.6-sol` seçer. Sandbox `read-only`
   ve reasoning effort exact `xhigh` olur. Zorunlu bayraklar `--ephemeral`,
   `--ignore-user-config`, `--ignore-rules` olur; plugin, app, remote-plugin ve
   memory bağlamları kapatılır. JSONL içinde
   tool/repo erişim olayı görülürse evidence üretmez. Harness PATH'teki keyfi bir
   executable'a güvenmez: resmi `@openai/codex` launcher/package/version
   eşleşmesini doğrular ve platforma özel native binary'yi doğrudan çalıştırıp
   SHA-256 kimliğini kaydeder. CLI-accepted requested model, sandbox ve execution
   bayrakları doğrulanır; receipt execution
   profili exact `codex-exec-ephemeral-read-only-exact-scope-no-tools-v2` olur. Yeni
   süreç bu sohbet geçmişini, önceki Claude/Codex bulgularını veya uygulayıcı
   yorumunu almaz. Implementer Codex olsa dahi bu process/context isolation,
   proje acceptance sözleşmesinde bağımsız Cross-AI reviewer sayılır ve tek
   başına `single` kapısını karşılar. Provider çeşitliliği zorunlu değildir.

Direct Anthropic Claude yalnız isteğe bağlı, non-authoritative challenger
olabilir. Claude çıktısı PR receipt'i, CI acceptance kanalı veya Codex evidence
girdisi değildir ve yeniden paketlenemez. Claude erişilemezliği geçerli Codex
`single` hükmünü `tracked_pending` yapmaz. MiniMax çağrısı, makbuzu veya
wrapper'ı yeni karar için kabul edilmez.

Cursor CLI/MCP/model/harness, Cursor-routed model ve AI uygulama pencereleri
istişare kanalı değildir. Normal/current sohbet içindeki öz-yorum da bağımsız
kanal sayılmaz; kabul yalnız ayrı `codex exec` süreci + ephemeral + read-only +
exact-scope profilinin tamamı sağlanırsa verilir. CLI, credential, exact model,
sandbox veya ephemeral capability hazır değilse UI/wrapper fallback yapılmaz.
`REVISE` yoksa veya karar scope'u maddi değişmediyse rutin her push'ta review
tekrarlanmaz. Geçerli `REVISE` bulgusu düzeltildiğinde canonical isolated Codex
kanalı değişen exact scope üzerinde yeniden inceler.
Yalnız commit metadata'sı değişmiş, target base-tip + merge-base + canonical
scope SHA-256 aynı kalmışsa fresh receipt review head'ine bağlı biçimde yeniden
kullanılabilir; scope byte'ı değiştiğinde yeni exact-scope review zorunludur.
Bir Codex `REVISE` kaydı yalnız PR gövdesinde seçilmiş daha yeni Codex receipt
referansındaki `AGREE` ile çözülür; `none` veya challenger yorumları çözüm
yetkisi üretmez. Düzenlenmiş ya da yapısal olarak geçersiz
evidence adayı geçmişten sessizce düşmez, gate'i fail-closed yapar. Politika
aktivasyonundan sonra her owner-authored OpenAI v4 evidence için PR numarası,
exact head, body SHA-256, thread ve verdict'e bağlı ayrı create-only commit-status
ledger kaydı yorumdan önce üretilir ve exact PR URL'sine bağlanır. Gate yorumları
ledger'a mutable yorum URL'siyle değil body digest'iyle bağlar; aynı digest'in
exact retry kopyaları tek authority kaydıdır, çelişkili duplicate fail-closed olur.
Gate mevcut PR commit'leriyle birlikte force-push timeline head'lerini tarar;
yorum POST'u başarısız olsa veya yorum silinse bile `REVISE` ledger tombstone
olarak kalır. Yorum edit'i, seçilmiş receipt için eksik ledger,
ledger/comment bağ uyuşmazlığı veya aktivasyon sonrasında oluşturulmuş OpenAI v3
adayı fail-closed yapar. Dar tarihsel docs-only muafiyeti de aynı PR'daki açık
`REVISE` geçmişini atlayamaz.

### 11.0.1 Varsayımsal istişare ile kesin inceleme sınırı

Varsayımsal senaryo yalnız erken yol/opsiyon keşfinde kullanılabilir. Böyle bir
çıktı açıkça `non-authoritative direction exploration` olarak etiketlenir;
`P0/P1/P2`, terminal `VERDICT`, provider receipt veya gate evidence üretmez ve
merge, deploy, readiness, acceptance ya da kapanış kararı için kullanılamaz.
Seçilen yol uygulanmadan önce karar gerekiyorsa ayrı bir kesin inceleme exact
mevcut scope/head ve doğrulanabilir kod, test veya canlı kanıta bağlanır.

Kesin `single` incelemede bulgu:

- sağlanan mevcut scope'ta bulunmalı,
- somut ve yeniden üretilebilir olmalı,
- dosya/satır/davranış ile beklenen-gerçek sonucu açıklamalı,
- mevcut validator, test veya invariant tarafından zaten imkansız kılınmamış
  olmalıdır.

“İleride bu kontrol gevşetilirse”, “bir gün başka tüketici eklenirse”,
“potansiyel olarak olabilir” veya gözlenmemiş dış durum varsayımı kesin
`P0`/`P1` ya da `REVISE` gerekçesi olamaz. Bunlar ancak yol keşfinde seçenek
etkisi veya kesin incelemede non-blocking yön önerisi olarak yazılabilir. Kanıt
yetersizse sağlayıcı boşluğu varsayımla doldurmaz; `tracked_pending` ve karar
için gereken exact eksik kanıtı yazar. Varsayımsal blocker içeren provider
yanıtı düzeltilmiş gibi evidence'a çevrilmez; kesin-review prompt'u düzeltilip
aynı scope yeniden incelenir.

PR structured alanları:

```yaml
Implementer AI: Codex|Claude|Gemini|other # other yalnız none modunda
Consultation mode: none|single
Consultation reason: <neden bu mod seçildi>
Consultation tier: routine|high-impact # yalnız single
Verdict: AGREE # yalnız single
Consultation base tip: <single exact target tip>
Consultation base: <single exact merge-base>
Consultation commit: <single reviewed head; current head farklıysa canonical scope byte-identical olmalı>
Consultation scope: <single content SHA-256>
Codex receipt: <single exact receipt; execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2>
```

`single` audit attribution için implementer kimliğini canonical tutar;
`other` yalnız receipt taşımayan `none` modunda kullanılabilir. Codex implementer
ile Codex `single` aynı sağlayıcı olsa da ayrı ephemeral/read-only exact-scope
süreç sözleşmesi nedeniyle kabul edilir; farklı sağlayıcı iddiası yazılmaz.
`gate-cross-ai-audit` açık modda kanal sayısını ve makinece görülebilen asgari
risk zeminini doğrular: `none` receipt, binding/outcome veya legacy control field taşıyamaz,
`single` yalnız exact Codex execution-profile receipt'i taşır. Routine scope'ta
`routine` tier beyan edilir; Spark varsayılandır ve Spark/SOL ikisi de kabul
edilir. Gate'in `single` zemini zorunlu tuttuğu governance/yüksek etkili scope'ta
veya author `high-impact` beyan ettiğinde exact SOL zorunludur. Claude
ve MiniMax receipt alanları fail-closed reddedilir. `single` çıktısı `P0/P1/P2` ve tek terminal
`VERDICT: AGREE|REVISE` sözleşmesine uyar; bozuk yanıt elle veya otomatik biçim
onarımıyla evidence yapılamaz. Exact scope, owner-captured GitHub comment,
freshness, digest, redaction ve provider/model eşlemesi korunur.

Güncel evidence comment gövdesi exact `cross-ai-provider-evidence/v4` JSON'dur.
`additionalProperties` kabul edilmez; `single` Codex kanıtında aşağıdaki
`execution_profile` değeri exact olmalıdır:

```json
{"schema":"cross-ai-provider-evidence/v4","provider":"openai","requested_model":"gpt-5.3-codex-spark|gpt-5.6-sol","actual_model":"not-provider-attested","execution_profile":"codex-exec-ephemeral-read-only-exact-scope-no-tools-v2","execution_provenance":{"schema":"codex-native-execution-provenance/v2","thread_id":"<uuid>","cli_version":"<pinned-version>","cli_native_target":"<pinned-platform-package>","cli_native_sha256":"<pinned-64hex>","trust_root":"repo-pinned-codex-native-sha256-v1","stderr_classification":"empty|allowlisted-model-cache-schema-warning-v1","source_trust_root":"trusted-base-cross-ai-sources-sha256-v1","trusted_base_sha":"<40hex>","review_harness_sha256":"<64hex>","scope_preparer_sha256":"<64hex>","pii_attester_sha256":"<64hex>","evidence_builder_sha256":"<64hex>","pii_review_status":"no-sensitive-pii","pii_attestation_sha256":"<64hex>"},"base_tip_sha":"<40hex>","base_sha":"<40hex>","head_sha":"<40hex>","scope_sha256":"<64hex>","verdict":"AGREE","response_sha256":"<64hex>","response":"<full provider response>"}
```

Desteklenen OpenAI evidence yolu yalnız
`scripts/ai/run_isolated_codex_review.py` harness'idir; genel builder OpenAI
girdisini ve modül seviyesinde OpenAI yeniden paketlemesini reddeder. Harness
exact komutu kendi çalıştırır, canonical scope'u
temiz worktree HEAD/target-ref/merge-base'den yeniden türetip caller scope
byte'larıyla eşleştirir; sabit talimat + untrusted scope'u tek stdin payload'ıyla
verir, herhangi bir tool/repo erişim event'ini reddeder ve evidence'ı mode-0600
create-once yazar. Native binary SHA-256, repo-review edilmiş
`repo-pinned-codex-native-sha256-v1` release pinsetiyle byte-exact eşleşmeden
çağrı başlamaz. Çalışan harness, scope preparer, PII attester ve builder
byte'ları `trusted-base-cross-ai-sources-sha256-v1` ile exact base tip'e bağlı
olmalıdır. Poster ve CI tarihsel v4 evidence producer digest'lerini mevcut
checkout'tan değil evidence'ın kendi immutable `trusted_base_sha` commit'inden
okur; bu commit mevcut PR base tip'inin atası değilse evidence fail-closed olur.
Producer güncellemesi bu nedenle daha önce geçerli olan immutable kanıtı geriye
dönük olarak bozmaz. Scope external provider'a verilmeden önce owner-only
`attest_cross_ai_scope_pii.py` exact digest için `no-sensitive-pii` kararı
üretmelidir; yokluğu `tracked_pending` olur. Evidence v4 exact CLI
version/target/native SHA-256/trust-root, producer kimlikleri, PII attestation
ve izole thread kimliğini taşır; poster ve CI aynı provenance pinini yeniden
doğrular. Yeni CLI sürümü pinset güncellemesi ve high-impact SOL exact-head
review ister. Poster exact şema/profil/provenance dışında fail-closed olur;
trusted producer commit'inin exact PR base tip'inin atası olduğunu posting
öncesinde doğrular, immutable status ledger'ı owner comment'ten önce üretir.
Comment yazımı başarısız kalırsa ledger tombstone korunur; aynı evidence digest'i
ile retry güvenlidir. CI receipt, GitHub comment gövdesi ve status-ledger bağını
digest üzerinden birlikte doğrular.
Böylece normal sohbet
yanıtı desteklenen araç zincirinde OpenAI `single` evidence olarak yeniden
etiketlenemez. Bu kayıt yine provider imzalı değildir ve
`operator-captured, provider-unsigned` sınırında kalır; yerel owner hesabının
bilinçli sahteciliğine karşı kriptografik attestation iddiası taşımaz.
Codex `--json` protokolü provider-imzalı effective-model metadata'sı vermediği
için OpenAI evidence'da `actual_model` exact `not-provider-attested` olur.
`requested_model`, doğrulanmış resmi native CLI'ya verilen ve error/reroute
event'i olmadan kabul edilen policy girdisidir; `actual_model` alanında tekrar
edilerek provider-signed model attestation varmış gibi sunulamaz. Model-tier
enforcement (`Spark` rutin, `SOL` yüksek etkili) `requested_model` üzerinden
yapılır ve bu sınır receipt'te açık kalır.

Producer zincirini ilk kez ekleyen aktivasyon PR'ı, trusted base commit'inde
harness/preparer/attester/builder bulunmadığı için kendi v4 evidence'ını
üretemez ve yeni zinciri kendisiyle doğrulamış sayılmaz. Bu bootstrap delta'sı
predecessor branch protection ve required-check sözleşmesine tabidir; ham direct
Codex çıktısı inceleme kanıtıdır ama canonical v4 receipt değildir. Yeni politika
yalnız merge sonrası exact `main` push checkout'unda
`scripts/ai/verify_cross_ai_source_activation.py` tarafından üretilen
`cross-ai-source-trust-activation/v1` sonucu CI artifact'i olarak saklanıp,
sonraki `pull_request_target` gate'i tarafından exact PR base SHA, successful
run ID, main workflow/ref/event ve producer digest bağıyla yeniden tüketilince
aktif kabul edilir; yalnız log'a yazılan veya tüketilmeyen çıktı aktivasyon
yetkisi üretmez. Bu
aktivasyondan sonraki PR'lar merged trusted producer stack'i kullanır.

Codex process `stderr` politikası da fail-closed'dur. Boş `stderr` kabul edilir;
yalnız Codex 0.144.1 ile server model-cache şeması arasındaki doğrulanmış
`supports_reasoning_summaries` eksikliği için iki satırı aşmayan exact cache-load
ve cache-TTL regex'i `allowlisted-model-cache-schema-warning-v1` olarak kabul
edilir ve evidence provenance'a yazılır. Model routing, auth, provider, sandbox,
tool veya başka herhangi bir uyarı/hata bu allowlist'e girmez ve evidence üretmez.

Path/branch sınıflandırıcısı yalnız açık governance ve production-promotion
ile yüksek güvenli RBAC/NetworkPolicy/Vault-policy/ExternalSecret/migration
sinyallerini fail-closed yakalar; diff'in iş anlamını eksiksiz anlayan bir risk
oracle'ı değildir. Authz, retention/silme, concurrency, cutover veya geri
döndürülemez başka bir karar path adına yansımıyorsa agent doğru
`single` modunu ve `high-impact` tier'ını beyan etmek zorundadır; `none` veya
`routine` bu sorumluluğu kaldırmaz.

`Consultation mode` içermeyen tarihsel PR gövdeleri GitHub'da immutable kayıt
olarak kalabilir; güncel gate bunları yeniden doğrulamaz ve `PASS`/acceptance
üretmez. Yalnız dar `docs-only historical` allowlist'i receiptsiz muafiyet
olarak kalır; bu muafiyet açık Codex `REVISE` geçmişini çözmez. Güncel parser'da
görülen her MiniMax receipt fail-closed reddedilir.
Yeni PR şablonu yalnız açık `none|single` sözleşmesini üretir; `single` yalnız
Codex receipt ister. Claude challenger receipt veya gate yetkisi üretmez.

İstişare hiçbir modda test/CI/live evidence/browser smoke/board claim/protected
Environment reviewer/gerçek kullanıcı rızası/hukuk veya secret-owner kapısının
yerine geçmez. Prompt, argüman ve receipt'e secret, JWT, raw bearer, webhook,
cookie, private key, admin credential veya kullanıcı PII yazılmaz.

### 11.H Tarihsel Politika Tombstone

2026-07-17 tarihli Claude-primary, zorunlu üç-sağlayıcı ve MiniMax receipt
sözleşmesi yürürlükten kaldırılmıştır. Yeni karar, gate veya receipt yetkisi
üretmez; ayrıntılı eski metin canonical kurallarda tutulmaz. Tarihsel GitHub
issue/comment ve immutable evidence kayıtları yalnız audit amacıyla yerinde kalır.

### Detay

- Kısa HARD RULE: [AGENTS.md §3](../AGENTS.md)
- PR structured alanları: [.github/pull_request_template.md](../.github/pull_request_template.md)
- Claude oturumlarının tamamlayıcısı: [CLAUDE.md Ana Kurallar #0.1 ve #8](../CLAUDE.md)
