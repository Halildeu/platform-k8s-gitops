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
| "Nasıl uygularız?" | ilgili runbook | `PLAN.md` | Runbook yoksa önce plan/kontrat netleştirilir |
| "Bu repo neyi sahipleniyor?" | bu doküman | `README.md` | Repo sınırı aşağıda tanımlı |

---

## 3. Repo Sınırı

### 3.1 Bu Repo Ne Değildir

`platform-k8s-gitops`:

- uygulama kaynak kodu repo'su değildir
- backend feature geliştirme backlog'u değildir
- image build otoritesi değildir
- `platform-ssot` yerine geçen repo değildir

### 3.2 Bu Repo Ne İçindir

Bu repo:

- Kubernetes desired-state
- host bootstrap ve stateful split hazırlığı
- ArgoCD / ESO / monitoring / ingress / cutover
- manifest, overlay, runtime governance ve operational truth closure

repo'sudur.

### 3.3 Kaynak Repo Sınırı

Uygulama kaynak kodu ve artifact üretimi:

- repo: `platform-ssot`
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

---

## 5. Testten Proda Promotion Semantiği

Bu repo için promotion zinciri aşağıdaki sırayla yorumlanır:

1. `platform-ssot` tarafında artifact üretilir
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
