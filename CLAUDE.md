# CLAUDE.md — platform-k8s-gitops Agent Kılavuzu

> Bu dosya Claude Code / agent session'larında otomatik yüklenir. Repo-specific kurallar, pattern'ler ve bağlam.

> Öncelik notu: Repo-geneli giriş yüzeyi [AGENTS.md](./AGENTS.md), canonical kural seti ise [docs/context-priority-rules.md](./docs/context-priority-rules.md) dosyasıdır. Bu dosya agent-özel tamamlayıcıdır; çelişki halinde `AGENTS.md` ve canonical kural seti üstün gelir.

---

## HARD RULE — `platform-ssot` is DEPRECATED, code there is YASAK (2026-05-06)

`Halildeu/platform-ssot` is **DEPRECATED, audit-only**. Faz 19 split-repo authority transfer completed 2026-04-25. **No commits, no PRs, no workflow / Dockerfile / governance changes in `platform-ssot`.**

**Why:** ssot's GHCR push rights for `platform-{backend,web}-*` packages have been **revoked** (403 Forbidden). Image builds there are orphaned — never reach the cluster. Live evidence: deploy-backend run `25408778230` failed with the same 403.

**Repo mapping:**

| Old (`platform-ssot`) | Canonical |
|---|---|
| `backend/<service>/` | `platform-backend/<service>/` |
| `web/apps/mfe-*/` | `platform-web/apps/mfe-*/` |
| `kustomize/`, `argocd/` | `platform-k8s-gitops/` (this repo) |

**Existing ssot residue (audit-only):**

PRs #561/#564/#567/#568/#570/#571/#572 merged in ssot 2026-05-05 never reached the cluster (GHCR 403). Their diffs were re-applied in canonical repos:

- platform-backend PR #63: AuthCookieEndpoint /refresh path matcher (from ssot #571)
- platform-web PR #257: muavin v3 frontend (from ssot #564 + #570)
- platform-k8s-gitops PR #372: api-gateway digest bump to sha-76c517b (the one that actually rolls the fix to the cluster)
- platform-backend muavin v3 mega PR: pending

**This repo (`platform-k8s-gitops`)** is the correct canonical for kustomize overlays + ArgoCD/manual deploy manifests. Image digests must come from canonical builds (`platform-backend-*`, `platform-web-*`); never pin a digest produced by an ssot pipeline.

---

## Proje Bağlamı

`autonomous-orchestrator` platformunun Docker Compose → Kubernetes geçişi için GitOps manifest repo. İki k3d cluster (test + prod), host nginx SSL edge, Vault + ESO secret flow, Zanzibar authz plane (permission-service + OpenFGA).

**Detay:** [README.md](./README.md) + [PLAN.md](./PLAN.md)

## Ana Kurallar (HARD RULE)

### 0. Mavis CLI — Lokal Agent İletişimi (2026-05-29, üst-seviye iletişim kanalı)

**Lokal agent'lar arası ve kullanıcı ile iletişim için Mavis CLI kullanılır**. Multi-session koordinasyon, paralel agent handoff, tamamlanma bildirimi, async iş zinciri için tek standart kanal.

**3 Yol** (öncelik sırası):

```bash
# 1. Session ID ile (en kesin)
mavis communication send --to mvs_88b2fffe2de74dbe9a17b929569552ac \
  --command prompt --content "İş tamamlandı, sonuç: ..."

# 2. Agent name ile (daha genel — session crash olursa Agent name persist)
mavis communication send --to agent-d2f425d1ea79 \
  --command prompt --content "Şunu yap: ..."

# 3. Peers listele (discovery — kim erişilebilir)
mavis communication peers
```

**Discovery + send akışı**: `peers` ile listele → Session ID veya Agent name seç → `send` ile prompt gönder.

**Ne zaman**: multi-session paralel iş, async tamamlanma bildirimi, agent handoff, long-running trigger.

**Yasak (redaction guard genişletilmiş)**: `--content` içine **secret/JWT/refresh token/raw bearer/webhook URL/cookie/OAuth client secret/private key/signing key/HMAC secret/admin credential/PII YASAK** (shell history, process list, Mavis log/queue, karşı peer transcript'ine düşebilir). Gerekirse sadece **redacted özet + evidence path/issue/PR linki** gönderilir.

**Acceptance gate bypass değil**: Mavis bildirimi **board claim'i, live evidence (D29 Up/Functional/Secured), browser smoke (HARD RULE Tarayıcıdan Sonuç Doğrulanmadan), PR/CI truth (HARD RULE CI Kırmızıyken Merge YASAK)** yerine geçmez — yalnız koordinasyon kanıtıdır (HARD RULE No Fake Work uyumlu). "X session'a haber verdim" ≠ "iş bitti".

**Canonical referans**:

- [AGENTS.md §3 HARD RULE](./AGENTS.md) (kısa canonical bullet)
- [docs/context-priority-rules.md §10 Agent İletişimi](./docs/context-priority-rules.md) (proje canonical detay)
- Global `~/.claude/CLAUDE.md` — "HARD RULE — Lokal Agent İletişimi: Mavis CLI" (tüm projeler için kapsamlı + örnek senaryolar)

### 0.1 Durumsal Cross-AI İstişre — Az Kanal Varsayımı (2026-07-18)

- Normal kodlama, test, küçük düzeltme, rutin PR ve geri alınabilir uygulama
  adımlarında istişre açma: `Consultation mode: none`.
- İkinci görüş gerçekten gerekiyorsa tek ve birincil kanal doğrudan
  `claude --model claude-opus-4-8` olur: `Consultation mode: single`.
  JSON `modelUsage` exact `claude-opus-4-8` değilse gerçek görüş sayılmaz.
- Yalnız geri döndürülemez, çok yüksek riskli veya açık insan/yetkili kararı
  gerektiren noktada Claude'a bir provider-distinct ikincil kanal ekle:
  `Consultation mode: dual`. MiniMax M3 veya Codex 5.6 SOL'dan yalnız biri
  seçilir; toplam iki kanal aşılmaz ve mümkünse paralel çağrılır.
- Cursor, wrapper-routed model ve AI uygulama penceresi istişre kanalı değildir.
- `REVISE` yoksa veya karar scope'u maddi değişmediyse rutin her push'ta yeniden
  review açma. Geçerli `REVISE` bulgusu düzeltildiyse yalnız seçilmiş kanal veya
  kanallar değişen exact scope üzerinde yeniden inceler.
- İstişre test/CI/live evidence/browser smoke/board/human gate yerine geçmez.
- Secret, PII veya raw credential prompt/argümana konmaz; UI fallback yapılmaz.

Canonical mod, attribution ve receipt semantiği:
[docs/context-priority-rules.md §11](./docs/context-priority-rules.md#cross-ai-three-channel).

### 1. No Closure Language

"Kapandı/bitti/gün sonu/pause/bekle" kelimeleri **YASAK**. Kullanıcı "dur/yeter/bitti" demedikçe iş aktif devam eder. Her ara rapor sonunda **bir sonraki aksiyon** olmalı.

Memory referans: `~/.claude/projects/<slug>/memory/feedback_no_closure_language.md`

### 2. No Option-List Approval

Commit sonrası "(a)(b)(c) seçenek listesi" **sormak yasak**. Sıradaki mantıklı işi direkt uygula. Kullanıcı genel onay ("devam", "yol haritası tamamla") varsa onay soruları gereksiz.

Memory referans: `~/.claude/projects/<slug>/memory/feedback_no_option_lists.md`

### 3. IP Sanitize

Dış kullanıcı-facing response/doc'ta gerçek IP'ler görünmez. `10.9.10.53`, `127.0.0.1`, `172.19.0.x` gibi iç ağ IP'leri sadece repo içi teknik dokümanda (ops okur).

### 4. D30 Immutable Artifact

Overlay image tag `sha-<short>` (immutable). `main-stable` (moving) YASAK. Cutover sırasında pod `imageID` == GHCR digest eşleşmeli.

### 5. D29 Up ≠ Functional ≠ Zanzibar-ready

Her deploy/cutover 3 katman ayrı kanıt:
- **Up:** Pod Running + TCP reachable
- **Functional:** Endpoint response shape (401 JWT vs 500)
- **Zanzibar-ready:** Allow + Deny enforce authoritative synthetic

### 6. D30 Atomic Cutover + 72h Warm Rollback

Weighted DNS (%10/50/100) YASAK. Dış proxy L4 backend atomic switch. T+72h staging-sw compose frozen+ayakta (rollback pointer).

### 7. SSH + sudo + kubectl yetkisi (genel kural — kullanıcı 2026-04-25 onayı)

Agent'ın **staging-sw sunucusuna SSH** ile erişim ve kubectl operasyonlarını **kullanıcıdan tekrar onay almadan** yapma yetkisi vardır. Bu yetki:

- `ssh halil@staging-sw "<command>"` — SSH komut çalıştırma
- `kubectl --context k3d-{test,prod} -n platform-{test,prod} ...` — read+write
- ConfigMap selective apply (low blast-radius tercih; D17 koruma DEPRECATED 2026-05-10; full overlay apply artık güvenli ama küçük diff için selective tercih edilir)
- Deployment rollout restart
- Pod logs, exec (debug için, kullanıcı bilgisi sızdırmadan)
- Sudo gerektiren ops işlemleri (örn. host nginx reload, edge release switch)

**İstisnalar (yine de onay gerek):**
- Prod cluster'a destructive değişiklik (D30 atomic cutover öncesi açık karar)
- Yeni image build/push (kullanıcı kaynak kod değişimi gördüğünde implicit ok)
- Kullanıcı credentials kullanımı (admin password gibi — kullanıcı paylaşırsa ok)

**Mantık:** Kullanıcı zaten sunucuya ortak (sürekli sunucudayım), her komutu agent vs kullanıcı koşması arasında pratik fark yok; ama otomasyonu agent yapıyor ki copy-paste workflow olmasın.

User mesajı (2026-04-25): "ssh ile sudo yetkin var gerekli işlemleir yapmak kural olarak ekle genel kural"

### 8. Continuous Autonomous Mode + Durumsal Cross-AI (KALICI ANA KURAL — 2026-07-18 güncel)

**HARD RULE**: Otomatik mod sürekli aktiftir; durmak yok, tüm işler bitene kadar devam.

**Karar verme kuralı**:
- Normal implementation/test akışını istişreyle yavaşlatma; otonom ilerle.
- Gerçek ikinci görüş noktasında yalnız direct Claude Opus 4.8 kullan.
- Geri döndürülemez/çok yüksek riskli/insan-yetkili kararda en fazla bir ek
  provider-distinct kanal kullan; mümkünse iki çağrıyı paralel yürüt.
- Cursor veya Cursor-routed model kullanma.
- Geçerli bulguları absorb et; `REVISE` kapanmadan hazır/merge-ready deme.
- Gerçek human gate istisnalarını AI kararıyla ikame etme; sağlayıcı/model
  erişilemiyorsa dürüstçe `tracked_pending` bırak, yapay `PASS` üretme.

**Çıktı**:
- `none` modda kısa gerekçe; `single/dual` modda sağlayıcı + exact model + exact
  base-tip/base/head/scope + verdict + evidence ref/digest kaydedilir.
- Plan iterasyonları kullanıcıya gösterilmez; seçilen az kanalın somut ve
  absorbe edilen bulguları kanıtlanır.

**İstisnalar** (yine kullanıcı onayı gerek):
- Repo arşivleme/silme/visibility değişimi (irreversible)
- Production destructive işlemler (D30 atomic cutover — açık karar bekleniyor)
- Credential paylaşımı (Vault token, admin password)
- Para harcaması (cloud provider, GitHub Actions limit aşımı)

**Mantık**: Kullanıcı sürekli iş + üç sağlayıcılı adversarial istişare ile yüksek
tempo iteration istiyor. Auto mode + provider-distinct consensus pattern'iyle
stratejik kararlar bağımsız itirazlara açılır, kullanıcı gereksiz yere interrupt edilmez.

User mesajı (2026-04-25): "durmak yok süreklid evam tüm işler biteene kadar otomaitk mode karar gerektğinde codex ile msp üzeri,nde otomaitk cevap al benim kararım sasyılacak kural olrak yaz bunu klıcı kural ana kural"

### 9. No Fake Work / No Cosmetic Operations (KALICI ANA KURAL — kullanıcı 2026-04-25)

**HARD RULE**: Sisteme gerçek fayda sağlamayan **fake/kozmetik iş yasak**. Görünür hareket / sıfır gerçek delta = adversarial yük; commit'leme, raporlama.

Detay kural seti **global** (`~/.claude/CLAUDE.md` — "HARD RULE — No Fake Work / No Cosmetic Operations"). Repo-spesifik tetikleyiciler:

- **Test koşmadan "tests added" merge etme** — pytest output paste'i veya CI run linki olmadan PR yeşil yapılmaz.
- **Skeleton commit** (`# TODO: implement`) bağımsız PR olarak ayrı çıkmaz; ya impl ile birlikte ya hiç.
- **Apply-without-verify**: `kubectl apply` sonrası `kubectl get` ile yeni state doğrulanmadan iş "done" sayılmaz.
- **Codex AGREE = plan kanıtı, run kanıtı değil**; impl sonrası kanıt ayrı kapı.
- **D29 disiplini ile uyumlu**: Up ≠ Functional ≠ Zanzibar-ready; her kapı için bağımsız çalıştırma kanıtı.
- **Filter-repo / migration sonrası** "% byte-identical" iddiaları diff komutu çıktısı ile beraber raporlanır.

**Karar kuralı (tek cümle)**: Her satır kod / her komut / her commit için *"Bu sistem state'ini doğrulanmış şekilde X→Y'e taşıdı mı, yoksa sadece görüntü mü verdi?"* — ikincisinde at, kullanıcıya rapor.

User mesajı (2026-04-25): "fake işlem istemiyorum sisteme gereksi olup fayda sağlamayan işlerde istemiyorum bunu ana kural olarak ekle"

## Pattern'ler

### Kustomize Overlay

- Base manifest'ler namespace **tanımsız** (overlay set eder)
- Overlay kustomization `namespace: platform-<env>` → tüm resource'lar o ns'e gider
- **İstisna:** `kustomize/base/eso/` kustomization `namespace: external-secrets` (ClusterSecretStore için). ghcr-pull ExternalSecret overlay-specific (Codex iter-5 Opsiyon B).

### Selective Apply (low blast-radius pattern)

`kubectl apply -k overlays/<env>` tüm overlay'i uygular — büyük yüzey, geniş etki. Tek bir ConfigMap/Deployment fix için yine de selective apply tercih edilir:

```bash
# Tek dosya apply
kubectl --context k3d-<env> -n platform-<env> apply -f kustomize/base/apps/<svc>/configmap.yaml

# Rolling restart (envFrom ConfigMap pickup için)
kubectl --context k3d-<env> -n platform-<env> rollout restart deploy/<svc>
```

> **NOT 2026-05-10**: Eski "D17 scale-to-zero patch'leri tekrar uygular → outage riski" gerekçesi DEPRECATED. HARD RULE — TEST Cluster Scale-to-Zero YASAK (global memory): test overlay artık `replicas=1` default; full apply scale=0 outage yaratmaz. Selective apply tercih sebebi sadece **blast radius** kontrolü.

### Codex Adversarial Protokol

Her büyük delta (10+ commit) sonrası Codex MCP **retrospektif ping-pong** yeni thread'de:
- VERDICT: AGREE / PARTIAL / REVISE / RED
- AGREE → direkt impl, plan onayı sorma (CLAUDE.md global kural)
- PARTIAL → absorb et, yeni iter submit et
- REVISE → absorb + karşı-tez + iter devam
- RED → kullanıcıya rapor + yön sor

### Commit Message Pattern

```
<type>(<scope>): <kısa başlık>

<body — neden, ne, kanıt>

<Codex iter referansı varsa>
<Co-Authored-By: Claude ...>
```

Types: `feat` / `fix` / `refactor` / `docs` / `chore` / `test`

## Yaygın Pitfalls

1. **base/eso doğrudan apply:** FQDN placeholder (`OVERLAY_MUST_OVERRIDE`) → sessiz drift yerine fail-closed. Her zaman `overlays/<env>/eso`.

2. **Full `apply -k` canlı cluster'a:** ~~D17 test overlay replicas=0 patch'leri aktif pod'u durdurur~~ DEPRECATED 2026-05-10 (test artık replicas=1 default; HARD RULE Scale-to-Zero YASAK). Selective apply hâlâ tercih sebebi: blast radius kontrolü.

3. **ConfigMap değişimi sonrası pod restart eksik:** `envFrom` otomatik pickup etmez. `kubectl rollout restart deploy` gerek.

4. **Tag drift runtime:** Overlay tag güncellensin ama pod imageID eski (staging-sw'de image import yapılmadıysa). Doğrulama:
   ```bash
   kubectl get pod -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
   ```

5. **Calico typha watch cache bozuk:** Bilinen pattern (2026-04-17 recovery). Fix:
   ```bash
   kubectl -n calico-system scale deploy calico-typha --replicas=0
   kubectl -n calico-system delete pod -l k8s-app=calico-node
   kubectl -n calico-system scale deploy calico-typha --replicas=1
   ```

## Hızlı Bağlam — MSSQL Şema Gezgini (Workcube)

**Kullanıcı kuralı (2026-04-26)**: Workcube MSSQL kaynak şeması her zaman schema-service üzerinden alınır. Agent **sentetik tablo/kolon/FK üretmemeli** — gerçek snapshot mevcuttur.

| Kaynak | Konum | İçerik |
|---|---|---|
| **Canonical snapshot (committed)** | `docs/migration/workcube-schema.json` (3.4 MB) | 1509 tablo, 26240 kolon, **1774 ilişki (FK)**, 27 domain. Sadece `workcube_mikrolink` canonical schema'sı (static master + HR + product). |
| **Live schema listesi** | `schema-service` `GET /api/v1/schema/schemas` (port 8096) | Cluster içindeki tüm aktif schema'ları döner — canonical + 43 tenant-only (`workcube_mikrolink_<id>`) + 276 year-tenant (`workcube_mikrolink_<year>_<id>`) = **319+ schema**. JWT auth (audience `schema-service`) veya internal API key. |
| **Live parametric snapshot** | `schema-service` `GET /api/v1/schema/snapshot?schema=<name>` | Belirli bir schema'nın full snapshot'ı (tablo + kolon + ilişki + domain). Year-tenant schema'lar transactional tablolar (`ACCOUNT_CARD`, `INVOICE`, `CARI_ACTIONS`, `STOCK_FIS`, vb.) buradan alınır. |
| **ETL allowlist** | `docs/migration/mssql-inventory.md` | 40 tablo (23 canonical match + 17 parametric) — rapor scope baseline. |

**Year-tenant schema'lar** (`workcube_mikrolink_<year>_<id>`) transactional tabloları barındırır; canonical snapshot'ta yok ama live endpoint ile **çekilebilir**. Örnek: `GET /api/v1/schema/snapshot?schema=workcube_mikrolink_2026_1` → 222 tablo döner (12 transactional finans tablosu dahil).

**Agent için pratik**: tablo/kolon/FK gereksiniminde **önce** `workcube-schema.json` oku (canonical hızlı yol). Parametric/year-tenant tablo için `schema-service /api/v1/schema/snapshot?schema=<name>` çağır. Sentetik şema yapma.

**Drift guard (Codex 019dc88c iter-4 + 019e2c59 iter-3 revize)**:
- Sentetik 17-tablo fixture işine **tekrar başlama**; daha önce yazılıp silindi (kural #9 ihlali tespit edildi).
- Agent **mevcut read-only schema-service endpoint'lerini** yetkili JWT ile **kullanabilir** (canlı evidence için). Ad-hoc crawler/script ve credential artefact commit edilmez.
- Faz 16.2.P **parametric ETL** sprint hâlâ deferred (ayrı sprint). Ama "schema-service yearly schema crawl tool" satırı eskimiş — `/schemas` + `/snapshot?schema=` endpoint'leri canlı, ayrı feature gereksiz.
- SEAL gate'inde schema cross-check için agent endpoint'ten direkt validation alabilir (kanıt: Annex 2A v2 PR #680).

## Repo İşleme

### Yeni Feature/Fix

1. `PLAN.md` ilgili Seviye/Faz altında karar var mı? yoksa D-karar ekle
2. Kustomize base/overlay değişim + build sanity (`kubectl kustomize ...`)
3. Codex plan-time istişare (yeni thread veya mevcut devam)
4. Commit + runbook referans güncelle (varsa)
5. Handoff doc update (büyük delta ise)

### Runbook Formatı

Her runbook: tetik → adımlar (süre + komut + beklenen + fail sinyali + devam eşiği) → rollback → referans. Örnek: `docs/D32-bootstrap-runbook.md`.

### Handoff D28 5-Alan

- **Bağlam:** Neden bu handoff?
- **İddia:** Ne yapıldı (commit özet)
- **İspatlar:** Canlı veya build sanity kanıt
- **İspatlamaz:** Henüz kanıtlanmamış (bekleyen functional)
- **Bilinen boşluk:** Pending iş + öncelik sırası

## Agent Session Akış

1. Oku: `AGENTS.md` → `docs/context-priority-rules.md`
2. Truth ayır: `docs/state/current-state.md` (canlı truth) + `docs/adr/0002-single-host-dual-cluster.md` (aktif mimari) + `PLAN.md` (roadmap/done kriteri)
3. Kontrol: `git log --oneline main..HEAD | head -10` + `git status`
4. Memory: `~/.claude/projects/<slug>/memory/MEMORY.md` → feedback kuralları
5. Codex thread: `PLAN.md` "Codex Thread" referanslar (ana + delta)
6. Historical gerekiyorsa: `docs/session-handoff-<latest>.md`
7. İş seçimi + board: **önemli/çok-adımlı iş — kullanıcı explicit atasa bile — çalışmadan önce claimed board issue olmalı** (paralel-oturum çakışma guard'ı; trivial tek-seferlik fix istisna). Oturum-başı ilk komut `scripts/board-sync.sh list` (In Progress + claim'li iş görünür) → iş seç → `board-sync.sh claim <issue>` (board issue yoksa önce aç ya da `backlog-add`+triage). Aktif iş + risk + milestone/gate `Status` [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (Project #2)'da canonical; çalışırken item `In Progress` + kanıt comment'i, bitince acceptance sonrası `Done`. Çalışırken keşfedilen scope-dışı iş/sorun → `board-sync.sh backlog-add` (`Backlog`'a alınır, kaybolmaz; ephemeral `spawn_task` chip tek başına yetmez). Protokol: `docs/board-protocol.md`.

## Test Öncesi

```bash
# Kustomize build sanity (apply etmeden)
kubectl kustomize kustomize/overlays/test
kubectl kustomize kustomize/overlays/prod
kubectl kustomize kustomize/overlays/test/eso
kubectl kustomize kustomize/overlays/prod/eso
kubectl kustomize kustomize/base/monitoring

# YAML lint (opsiyonel, CI'da otomatik)
yamllint kustomize/ helm-values/ argocd/ docs/
```

## Kaynaklar

- PLAN.md D-kararlar logu
- docs/session-handoff-<YYYY-MM-DD>-v<N>.md (en son durum özeti)
- docs/D32-bootstrap-runbook.md (prod host F1-F9)
- Codex thread `019d9a75` (ana) + `019da5f8` (delta retrospective)
