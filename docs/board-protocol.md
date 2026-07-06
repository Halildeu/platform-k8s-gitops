# Board Protocol — platform Roadmap (GitHub Project #2)

> **Status**: ACTIVE (2026-05-18 — board automation iter-1..3)
> **Board**: [platform Roadmap](https://github.com/users/Halildeu/projects/2) (Project #2, owner `Halildeu`)
> **Codex consensus**: thread `019e3a0d` (AGREE — iter-1 plan)

Bu doküman **GitHub Project #2 "platform Roadmap"** board'unun agent'lar
tarafından nasıl okunup güncelleneceğini tanımlar. Board'u pasif bir snapshot
değil; **kendi kendine güncellenen, işi sürükleyen, oturumlar arası bağlam
taşıyan** aktif bir iş yüzeyi yapan kuralların kanonik kaynağıdır.

İlgili kural yüzeyleri: [AGENTS.md](../AGENTS.md) · [CLAUDE.md](../CLAUDE.md) ·
[docs/context-priority-rules.md](context-priority-rules.md) ·
[docs/notify/README.md](notify/README.md) (Faz 23 alt-seti).

---

## 1. Amaç

Board, **aktif iş + açık risk/issue + milestone/gate durumunun** kanonik
kaydıdır. Bir agent oturumu:

1. **Oturum başında** board'u okur, en yüksek öncelikli uygun işi seçer, claim eder.
2. **Çalışırken** item'ı `In Progress` yapar, ilerlemeyi issue'ya işler.
3. **Bitirince / PR merge'de** kanıt bırakır, item'ı doğru statüye taşır.

Disiplin elle hatırlanmaz — `scripts/board-sync.sh` mekaniği taşır.

---

## 2. Source-of-truth katmanları

| Katman | Kanonik içerik |
|---|---|
| **Board (Project #2)** | Aktif iş durumu, açık risk/issue, milestone/gate `Status` |
| **`docs/state/current-state.md`** | Runtime live truth (cluster state, post-deploy kanıt) |
| **`PLAN.md` + `docs/adr/*`** | Kararlar (D-kararlar, ADR) |
| **`docs/notify/*`** | Faz 23 spec (event-contract) + acceptance kriteri + evidence ledger |
| **Issue body + comment** | İtem-başına canlı handoff state'i + ilerleme/kanıt log'u |

Bir item için durum **hem board'da hem doc'ta bağımsız yürütülmez** — board
issue canonical. Drift kaynağıdır.

---

## 3. Item türü — draft vs gerçek issue

| Tür | Ne için | Otomasyon |
|---|---|---|
| **Draft item** | Umbrella, roadmap başlığı, faz özeti, aktif çalışılmayacak üst-seviye satır | Yok — PR/close/comment/assignee taşımaz |
| **Gerçek issue** | Agent'ın claim edeceği, PR bağlayacağı, state güncelleyeceği, devralınacak **her iş** | Tam — PR link, comment log, close event |

**Kural**: Aktif/ileriye dönük executable iş **gerçek issue olmadan başlamaz**.
Draft item üzerinde claim/state/handoff çalışmaz.

**Cross-repo ownership**: Issue, işin yapılacağı repo'da açılır — gitops işi
`platform-k8s-gitops`, backend `platform-backend`, web `platform-web`,
agent `platform-agent`. Board user-owned; issue repo-owned. (`platform-ssot`
hedef repo olarak kullanılmaz — DEPRECATED.)

**Feature-matrix satırları tek tek issue yapılmaz** — board firehose'a döner;
yalnız aktif çalışmaya alınan satır issue olur.

---

## 4. `Status` alanı semantiği

| Status | Anlam |
|---|---|
| **Backlog** | İş sırasında keşfedilmiş, henüz triage edilmemiş — **claim edilemez** (§16) |
| **Todo** | Triage edilmiş, başlanmadı; uygun (eligible) ise claim edilebilir |
| **In Progress** | Bir oturum tarafından claim'li + aktif çalışılıyor |
| **Blocked** | Dış bağımlılık / başka item / operator-gate nedeniyle ilerleyemiyor |
| **Needs Verify** | Merged / source-ready — **canlı/acceptance kanıtı bekliyor** (acceptance kuyruğu) |
| **Done** | ALL kabul kriteri accepted/live — yalnız deliberate issue-close sonrası |

**HARD kural — overclaim guard**:

- `Status=Done` **yalnız** issue gerçekten close edildikten sonra; issue
  body'sinde acceptance evidence yoksa agent issue'yu **close etmez**.
- `Needs Verify` issue kapanışı değil — acceptance kuyruğudur.
- PR merge bir runtime/GitOps issue'sunu **otomatik `Done` yapmaz** (§5).
- `needs-verification` benzeri açık doğrulama varken closure YASAK.
- `source-ready ≠ live-deployed ≠ accepted` (D29: Up ≠ Functional ≠ Zanzibar-ready).
- `Blocked` hem board `Status` hem issue'da bir `BLOCKED` comment'i ile
  işaretlenir — sadece biri yetmez.

### 4.1 Status Reconciliation Barrier

Bir issue icin yeni kanit issue'nun status yorumunu degistiriyorsa, sonraki
guclu operasyon sinirina gecmeden once status aynalari senkron olmalidir:

1. Project #2 `Status`
2. issue body `agent-state:v1 status`
3. son ilgili taxonomy comment (`PROGRESS`, `EVIDENCE`, `BLOCKED`,
   `READY-FOR-VERIFY`, `DONE-CANDIDATE`, `HANDOFF`)

Trigger'lar:

- live/runtime evidence eklendi
- PR merge evidence geldi
- blocker kalkti, degisti veya yeni blocker bulundu
- acceptance boundary degisti (`source-ready`, `live-smoked`, `accepted`
  gibi)
- issue body veya board status manuel/script ile degisti

Barrier, `stage`, `commit`, `push`, `pr_create`, `pr_update`,
`live_mutation`, `deploy`, `release`, `issue_close`, `recovery` ve
`key_rotation` oncesi uygulanir. Drift varken yalniz `local_edit` ve
`file_write` devam edebilir; daha guclu operasyonlar fail-closed olur.

Eger aynalar uyusmuyorsa veya Project mutation GraphQL/permission nedeniyle
yapilamiyorsa agent sunlari yapar:

- durumu gercek semantige gore yazar; `Blocked` hala gercekse `Needs Verify`
  yapmaz
- `MIRROR_DRIFT_DETECTED` / `REPAIR_MATERIALIZATION` ledger akisini kullanir
  (yeni event icat etmez)
- GitHub-visible comment ile hangi ayna stale, hangi evidence yeni ve hangi
  repair adimi gerekli yazar
- status reconcile tamamlanmadan yeni implementasyon dalina gecmez

`Blocked` onceliklidir: kalan operator gate, dis bagimlilik veya baska issue
blokluyorsa PR merge ya da live-smoke kaniti tek basina `Needs Verify`
yapmaz. `Needs Verify`, yalniz artik bilinen blocker kalmadiginda ve beklenen
is acceptance verification oldugunda kullanilir.

---

## 5. `Closes #N` vs `Tracked by #N`

PR merge'in issue'yu otomatik kapatması (`Closes/Fixes/Resolves`) **yalnız**
kapanış kriteri gerçekten PR merge ile biten **saf source/task issue'larında**
kullanılır.

**Runtime / GitOps / acceptance isteyen issue'larda** PR body'de:

```
Tracked by #N
Runtime evidence pending
```

`Closes/Fixes/Resolves` runtime tracking issue'larında **YASAK** — yoksa PR
merge issue'yu kapatır, `item-closed → Done` tetiklenir, canlı kanıt
olmadan board `Done` olur (overclaim).

CI enforcement: `gate-forbidden-close-keywords.yml` PR başlığı, PR gövdesi ve
commit mesajlarında `Closes/Fixes/Resolves #N` sınıfı GitHub issue referansını
yakalar. Guard sadece issue ref ile birlikte gelen close keyword'leri bloklar;
`Closes the bug class` gibi açıklayıcı metin false-positive üretmez.
Guard ayrıca `push` to `main` event'lerinde merge/squash commit body'lerini ve
`release` `published/edited` event'lerinde release name/body yüzeylerini de
tarar; post-merge otomasyon metni issue auto-close keyword'u üretirse CI
nonzero döner.

Akış: runtime issue PR-merge'de **kapanmaz** → agent canlı kanıt + acceptance
checklist'i issue'ya işler → `Needs Verify` → kabul → deliberate close → `Done`.

---

## 6. Issue gövdesi — agent-state şablonu

Her gerçek (executable) issue gövdesi **hybrid** yapıdadır: gövde = anlık
state (her zaman güncel), comment'ler = append-only log (§7).

Gövdenin başında makine-okunur blok + 5-alan state:

```markdown
## Agent State

<!-- agent-state:v1
status: todo            # backlog | todo | in-progress | blocked | needs-verify | done
claim_session: none     # claim eden oturum id'si
claim_worktree: none    # claim eden worktree path
claim_branch: none      # claim eden aktif branch
claim_updated_at: none  # son heartbeat ISO-8601
expires_at: none        # claim son kullanma ISO-8601
-->

**Faz:** ... · **Track:** ... · **Priority:** ... · **Kind:** issue
**Owner repo:** Halildeu/<repo>
**Blocked by:** ... · **Unblocks:** ...

### Context
<iş neden var; ilgili faz/gate/risk; kaynak doc'lar>

### Current Claim
<aktif oturum / worktree / branch / son heartbeat — yoksa "unclaimed">

### Evidence
- Source: <->
- Desired-state: <->
- Runtime/live: <->
- Browser/user-path: <->
- Does not prove: <->

### Remaining
<açık maddeler; blocker vs non-blocker ayrımı>

### Next Action
<taze oturumun ilk yapacağı somut adım>

### Related PRs
<->
```

Taze bir oturum In Progress issue'yu açar → gövdeyi okur → `Next Action`'dan
devam eder. Bu, oturumlar-arası handoff biriminin **kendisidir** (eski
oturum-başına markdown handoff doc'unun yerini alır).

Gövde editable olduğu için ezilme riski taşır → agent gövdeyi güncelledikten
sonra kısa bir `HANDOFF` veya `EVIDENCE` comment'i de bırakır (timeline
kaybolmasın).

---

## 7. Comment taxonomy

İlerleme/kanıt/audit comment'leri ilk kelimeyle tiplenir:

| Tip | Ne zaman |
|---|---|
| `CLAIM` | İşi claim ederken (§8) |
| `HEARTBEAT` | Uzun işte periyodik canlılık + `expires` ileri taşıma |
| `PROGRESS` | Anlamlı bir ara adım tamamlandı |
| `EVIDENCE` | Source / desired-state / live / browser kanıtı |
| `HANDOFF` | Oturum devrediyor — gövde state güncel, devam noktası net |
| `BLOCKED` | Blocker tespit edildi — sebep + kim/ne unblock eder |
| `READY-FOR-VERIFY` | İş source-ready/merged; acceptance kuyruğuna girdi |
| `DONE-CANDIDATE` | Acceptance evidence tam; close önerisi |

---

## 8. Claim protokolü (paralel-session güvenli)

Birden çok Claude oturumu paralel çalışır (ayrı worktree). İki oturumun aynı
item'ı kapmasını **deterministik** bir protokol engeller — GitHub'da gerçek
lock primitive'i yoktur.

Claim kimliği **issue assignee değildir** (tüm oturumlar aynı GitHub kullanıcısı
`Halildeu` — assignee oturumu ayırt etmez). Kimlik `CLAIM` comment'indedir.

**Protokol**:

1. Agent uygun (eligible, §9) bir issue seçer.
2. İlk write olarak `CLAIM` comment'i atar:
   ```
   CLAIM session=<id> worktree=<path> branch=<current-branch> at=<ISO> expires=<ISO + ~2h>
   ```
3. Hemen issue'nun **tüm** comment'lerini yeniden okur.
4. **Aktif** `CLAIM`'leri `created_at` artan sırada dizer. Bir CLAIM aktiftir:
   *süresi geçmemiş* **ve** aynı oturumdan sonraki bir `HANDOFF`/release
   comment'i ile geçersiz kılınmamış. Eşit timestamp → comment node id ile tiebreak.
5. **En erken aktif CLAIM kendisininkiyse** → claim kazanıldı: agent gövde
   `agent-state` bloğunu doldurur, board `Status` → `In Progress`.
6. Değilse → claim kaybedildi: agent `HANDOFF released=lost-race` comment'i
   atar (kendi CLAIM'ini geçersiz kılar) ve başka iş seçer.
7. Çalışırken periyodik `HEARTBEAT` — `claim_updated_at` + `expires` ileri taşınır.
8. **Stale claim**: `expires` geçmiş bir CLAIM geçersizdir; başka agent o
   issue'yu reclaim edebilir — reclaim CLAIM'inden sonra eski claim'i
   superseding olarak işaretleyen bir `PROGRESS`/`HANDOFF` notu bırakır.

İki racing agent comment ordering'i aynı total-order gördüğünden **aynı
kazananı** hesaplar. Stale-reaper mantığı `board-sync.sh` içindedir (her agent
başlangıçta çalıştırır) — ayrı scheduled job iterasyon-2'ye ertelendi.

### 8.1 Live-mutation guard (ADR-0023 Guardrail PR-8)

**Tetik**: P0-c gibi uzun-koşan live mutation işlerinde claim lease (default
`CLAIM_TTL_HOURS=2`) sessizce expire edip live mutation devam edebiliyor →
audit'te "claim unclaimed" gözüküyor. Codex thread `019e444d` Opsiyon A
absorb (fail-closed guard).

**Kullanım**: live-mutation script/runbook entrypoint'inde:

```bash
bash scripts/board/require-claim.sh <issue> \
  || { echo "Claim invalid — aborting mutation"; exit 1; }
```

`require-claim.sh` `$BOARD_SESSION_ID` ile issue body `<!-- agent-state:v1 -->`
bloğunu karşılaştırır: `claim_session`, `claim_worktree`, `claim_branch`,
`expires_at > now` (opsiyonel `--grace-minutes N` toleransı). Tüm kontroller
geçmezse exit 1 + tek-satır unblock önerisi (heartbeat / reclaim /
`CLAIM_TTL_HOURS=N` override).

**Uzun P0 için TTL override**: 2 saat genelde yetersiz. Hizmet-bazlı tipik
süreyi tahmin et + payı ile ayarla:
```bash
CLAIM_TTL_HOURS=6 bash scripts/board-sync.sh claim <issue>
```

**Kapsam dışı** (bilerek, Codex Opsiyon A focal):
- Worktree-level mkdir lock — aynı worktree'de paralel `git checkout/rebase`
  engelleme. Ayrı follow-up (operatör ergonomisi + local data-loss).
- Per-session worktree convention (her session kendi `git worktree add`).
  Önerilir ama bu PR'a sokulmadı.

---

## 9. Eligible-work filtresi

Agent "en yüksek öncelikli Todo"yu kör seçmez. Bir item **eligible**'dır:

- `Status = Todo` (veya stale-claim'li `In Progress`)
- `Blocked` değil
- `Kind != umbrella`
- Owner repo belli
- Acceptance kriteri / `Next Action` issue'da yazılı
- `Blocked by` bağımlılıkları çözülmüş

Sıralama: `Priority` (P0 → P3), sonra `created_at`.

`board-sync.sh claim` bu filtreyi claim-time'da **hard gate** uygular:
`Todo` veya lease'i geçmiş (stale) `In Progress` dışındaki Status
(`Backlog` / `Blocked` / `Needs Verify` / `Done`) ve `Kind=umbrella` issue'lar
için claim reddedilir — yanlış issue numarasıyla overclaim/rollback engellenir.
`Backlog` item önce triage edilip `Todo`ya alınmalı (§16).

---

## 10. Evidence taxonomy

Her issue'da kanıt 4 katmanda ayrılır (D29 disiplini + overclaim azaltma):

| Katman | Anlamı |
|---|---|
| **Source** | Kod/manifest merged — repo'da |
| **Desired-state** | GitOps overlay / config istenen değerde |
| **Runtime/live** | Cluster'da pod/endpoint canlı doğrulandı |
| **Browser/user-path** | Tarayıcıdan uçtan uca senaryo (HARD RULE) |

`Does not prove:` satırı her zaman doldurulur — neyin **henüz**
kanıtlanmadığı açıkça yazılır.

---

## 11. Oturum ritüeli

| An | Aksiyon |
|---|---|
| **Oturum başı** | `board-sync.sh list` → eligible iş; `board-sync.sh claim <issue>` |
| **Çalışırken** | board `Status=In Progress`; `PROGRESS`/`EVIDENCE` comment; `HEARTBEAT` |
| **PR açarken** | runtime issue → PR body `Tracked by #N` (`Closes` değil) |
| **İş source-ready** | `READY-FOR-VERIFY` comment; board `Status=Needs Verify` |
| **Acceptance tam** | `DONE-CANDIDATE` + canlı kanıt; deliberate issue-close → `Done` |
| **Oturum devri** | gövde `agent-state` güncel + `HANDOFF` comment |
| **Blocker** | board `Status=Blocked` + `BLOCKED` comment (sebep + unblock sahibi) |
| **Status drift** | §4.1 bariyeri; body + board + comment reconcile olmadan güçlü operasyona geçme |

**HARD RULE — claim-before-work (paralel-session çakışma guard'ı)**

Kullanıcı paralel çoklu-oturum çalıştırır — iki oturumun aynı işi yapması riski
buradan doğar.

- **Önemli / çok-adımlı / roadmap-visible iş** — kullanıcı ad-hoc atasa bile —
  çalışmaya başlamadan önce **claimed bir board issue** olmalı. Board issue
  yoksa önce açılır (gerekirse `backlog-add` → triage) + `claim`'lenir.
- Her oturumun **ilk komutu** `board-sync.sh list` — In Progress + claim'li işi
  görür, üstüne binmez.
- **İstisna**: trivial tek-seferlik fix board-dışı kalır — her küçük işi board'a
  almak §14 curated kuralını bozar; küçük bir fix'in iki kez yapılması ucuzdur.
  Pahalı çakışma büyük çok-adımlı iştedir; guard oraya odaklanır.

**Sınır (dürüst)**: kural *advisory*. Aynı board issue için yarışı §8
deterministik claim kesin çözer; ama (a) hiç board'a alınmayan iş ve (b) ritüeli
atlayan oturum disipline bağlıdır — GitHub'da zorlayıcı bir mutex yok. Gerçek bir
duplicate-work gözlenirse harness-enforced SessionStart hook değerlendirilir.

---

## 12. `scripts/board-sync.sh`

Ritüelin mekaniğini taşıyan script. Alt komutlar:

| Komut | İş |
|---|---|
| `list` | Eligible iş listesi (Priority sıralı) + In Progress claim durumu + `Backlog` sayısı |
| `claim <issue>` | Deterministik claim protokolü (§8) — winner re-read ile belirlenir |
| `heartbeat <issue>` | Aktif claim lease'ini uzat (`HEARTBEAT` comment + body `expires_at`) |
| `release <issue>` | Claim'i bırak — yalnız sahibi; başkasının claim'i ancak `--force-stale` + lease expired ise |
| `sync-state <issue>` | Gövde `agent-state` ↔ board `Status` senkron raporla |
| `verify <issue> --pr <N> --pr-repo <repo>` | PR-merge evidence — board `Status` → `Needs Verify` + makine-okunur `EVIDENCE` comment (idempotent: `pr_repo`+`pr` anahtarı) |
| `reap [--limit N]` | Lease'i geçmiş tüm `In Progress` claim'leri release et (scheduled reaper bunu çağırır) |
| `backlog-add "<title>" [--note] [--kind] [--repo]` | Keşfedilen scope-dışı işi `Backlog` issue olarak yakala (§16) |

`--dry-run` her komutta — write yapmadan ne yapacağını gösterir. `claim`
lease'i `CLAIM_TTL_HOURS` (default 2 saat) sonra dolar; uzun iş için
`heartbeat` ile lease ileri taşınır — winner hesabı yalnız lease dolmadan
atılan heartbeat'leri extension sayar (kopmuş zincir reclaim'e açık kalır).
Script başlangıçta `gh auth status` + project id sanity check yapar.

---

## 13. Board referansı (ID'ler)

`gh project item-edit` / GraphQL için (script bunları kullanır):

```
Project          PVT_kwHOCx7tY84BIN2d   (Project #2, owner Halildeu)

Status   field   PVTSSF_lAHOCx7tY84BIN2dzg4vgLw
  Backlog 81ee9923 · Todo da11d7ac · In Progress 6e2ec368 · Blocked 5f6aac96 · Needs Verify 516d2beb · Done a099a451
Faz      field   PVTSSF_lAHOCx7tY84BIN2dzhTGqF0
  Faz G a8f19c83 · Faz I a858eb09 · Faz 22 6fb80ca3 · Faz 23 7ff54758 · V2.1 b21e7ec5 · V3 68101ca0 · schema-service 0df88f76
Track    field   PVTSSF_lAHOCx7tY84BIN2dzhTGqHY
  gitops 4b80f631 · backend 110c9207 · web eb9e6ec7 · agent e36ee869 · ops d3935343
Priority field   PVTSSF_lAHOCx7tY84BIN2dzhTGqHk
  P0 951c13f7 · P1 00ad329c · P2 1831e102 · P3 e2dc8e72
Kind     field   PVTSSF_lAHOCx7tY84BIN2dzhTGxFk
  umbrella deb03eb5 · milestone 4efca8fc · gate ad398fa9 · risk e3a49d4e · issue 22b29779
```

> `Status` option ID'leri her `updateProjectV2Field` çağrısında **yeniden
> üretilir** (option-set replace — name-match ID korumaz; 2026-05-18'de iter-1
> `Blocked`+`Needs Verify` ve iter-3 `Backlog` ile 2 kez oldu). Bu alanı tekrar
> düzenlerken **tüm item'ların `Status` snapshot'ı önce alınır**, mutation
> sonrası geri yüklenir; `board-sync.sh` `STATUS_*` constants + bu tablo
> güncellenir.

---

## 14. Curated board — intake kuyruğu değil

Board roadmap/risk/faz yüzeyidir. Bir PR/issue **sadece açıldığı için**
board'a girmez. Roadmap-visible iş (faz/milestone/gate/risk/RAID state'ini
etkileyen) board'a alınır → `project-roadmap` label + Project #2 item-add.

Normal implementation/code PR board'a **eklenmez** — kendi repo'sunda kalır,
ilgili milestone/gate/risk issue'suna link verir. `project-roadmap` label
normal PR'lara verilmez. Native auto-add yalnız `project-roadmap` label'lı
item'ı çeker (4 repo).

**Backlog — tek meşru dar intake (iter-3)**: İş sırasında keşfedilen scope-dışı
iş/sorun kaybolmasın diye `board-sync.sh backlog-add` ile board'a `Backlog`
statüsünde alınır (§16). Bu firehose değil — agent keşfi *yargılayarak* alır;
`Backlog` item'lar roadmap lane'lerinden (Todo/In Progress/...) ayrıdır,
eligible değildir, triage bekler.

---

## 15. İterasyon-2 — board automation Actions

İter-1 disiplin + script üzerine, iter-2 iki GitHub Action ekler (Codex
`019e3a0d` AGREE). Her ikisi de **thin wrapper** — tüm board-mutation mantığı
`board-sync.sh`'de kalır. Auth: `ADD_TO_PROJECT_PAT` secret canonical;
`board-pr-evidence` workflow PAT-missing durumunda **GITHUB_TOKEN fallback**
ile comment-only path'e düşer (#1085, Codex `019e8079`). Permissions:
`contents: read` (checkout) + `issues: write` (GITHUB_TOKEN fallback
EVIDENCE comment için); project mutasyonları yalnız PAT ile.

### PAT-missing fallback davranışı (#1085)

`ADD_TO_PROJECT_PAT` secret unset olduğunda workflow boş `GH_TOKEN`'la
fail etmek yerine `secrets.GITHUB_TOKEN`'a düşer ve `BOARD_PAT_PRESENT=""`
sinyalini script'e iletir. `board-sync.sh verify` bu sinyalle alternatif
bir akışa girer:

| Half | PAT seeded | PAT missing (CI fallback) |
|---|---|---|
| Same-repo `Tracked by` EVIDENCE comment | ✓ | ✓ (GITHUB_TOKEN repo-scope) |
| Cross-repo `Tracked by` EVIDENCE comment | ✓ | ⏭ skip + warning (token cross-repo değil) |
| Body `agent-state` → `needs-verify` | ✓ | ⏭ skip (board mutate edilmiyorken body drift'i önler) |
| Board Status → `Needs Verify` | ✓ | ⏭ skip + step summary "Action required" |
| Project API preflight / item-list | ✓ | ⏭ skip (Project API PAT-only) |

Drift garantisi: PAT-missing path body'yi yazmaz **ve** board'u taşımaz —
ikisi de tek bir authority altında. PAT seedlenince mevcut comment'ler
idempotency anahtarıyla atlanır, ama body rewrite + board Status mutation
**çalışır** (iter-2 P1 absorb): `seen>0` artık duplicate comment'i bloklar,
state mutation'ı değil. Aynı item için PAT-missing → PAT-seeded geçiş
güvenli onarılır (comment tekrarlamaz, board hâlâ taşınır).

**Required `ADD_TO_PROJECT_PAT` scope (Codex 019e809d iter-3 must_fix)**:
Same token board mutation + issue R/W için kullanılıyor — sadece Projects
yetkisi yetersiz, repair run `gh issue view/comment/edit` aşamasında patlar.

| Yetki | Kapsam |
|---|---|
| Organization Projects (Halildeu) | Read & Write |
| Roadmap-tracked repo'larda Issues (her biri için) | Read & Write |
| Metadata (her repo) | Read |
| Cross-repo `Tracked by` refs için sibling repo erişimi | Aynı PAT'a o repo Issues R/W ekle (yoksa cross-repo refs skip kalır) |
| Classic PAT alternatifi | `repo` + `project` (veya `read:project` + `write:project`) |

Offline harness: `scripts/test/board-sync-verify-pat-missing.sh` — fake
`gh` shim ile **10 senaryoyu** deterministic koşturur:

1. PAT present — full path: Project API + EVIDENCE comment + body rewrite + board Status
2. PAT missing, same-repo — comment-only, Project API'ye DOKUNMAZ
3. PAT missing, cross-repo — soft-skip + `::warning::` annotation + step summary, network'e DOKUNMAZ
4. PAT missing, idempotent — pre-existing EVIDENCE → comment ATLANIR
5. PAT present REPAIR (iter-2 P1 + iter-3 P1 #2) — pre-existing EVIDENCE; comment ATLANIR ama body rewrite (`gh issue edit`) + board (`project item-edit`) STILL fire'lar
6. PAT missing, lowercase same-repo (iter-3 P1 #3) — case-insensitive compare, false cross-repo skip YOK
7. PAT missing, repo-only cross-repo shorthand — `platform-ai#N` aynı-owner
   cross-repo ref olarak normalize edilir ve PAT yokken no-network soft-skip
   alır; bare `#N` gibi aynı repo issue'suna düşmez
8. PAT missing, invalid owner#N typo — `Halildeu#N` gibi owner#N biçimli
   hata `Halildeu/Halildeu#N` gibi yanlış issue'ya gitmeden soft-skip alır
9. Workflow extraction — `Tracked by platform-ai#198` satırı `platform-ai#198`
   olarak çıkar, `#198` olarak kırpılmaz
10. Workflow guard — boş GH_TOKEN durumunda `::error::` + exit 1 (file-level grep assertion)

Yeni regression bu harness'la lokal yakalanır, gerçek merge beklemeden.

**`.github/workflows/board-pr-evidence.yml`** — `pull_request: closed` (merged).
PR body'sindeki `Tracked by <ref>` satırlarını parse eder, her ref için
`board-sync.sh verify` çağırır.

- Ref formatları: `#N`, `repo#N` (PR repo owner'ı ile aynı GitHub owner
  altında normalize edilir), `owner/repo#N`, tam issue URL'i — **cross-repo
  `Tracked by` desteklenir** (board user-owned, issue repo-owned).
- `Closes/Fixes/Resolves` parse EDİLMEZ — yalnız `Tracked by`. (`Closes`
  issue'yu native kapatır → `item-closed → Done`.)
- **Idempotent**: aynı PR tekrar event üretirse skip — idempotency anahtarı
  `pr_repo` + `pr` (PR numaraları repo-local; cross-repo collision önlenir).
  EVIDENCE ilk satırı: `EVIDENCE type=pr-merged pr_repo=<repo> pr=<N>
  issue_repo=<repo> at=<ts>`.
- Asla downgrade: `Done` / `Blocked` / `Needs Verify` item'a dokunmaz; board'da
  olmayan veya ambiguous ref → graceful skip (workflow fail değil). Gerçek
  fail yalnız auth/API/script hatası.
- `verify` PR-merge'de body `agent-state`'i `needs-verify` yapar + claim
  alanlarını `none`'a çeker — implementation claim'i bitti, acceptance başka
  oturum tarafından alınabilir.

**`.github/workflows/board-stale-reaper.yml`** — `schedule` saatlik (+
`workflow_dispatch` `dry_run` input). `board-sync.sh reap` çağırır → lease'i
geçmiş her `In Progress` claim'i release eder (`HANDOFF released=stale-reaper`
comment + body `todo` + board `Todo`).

- Conservative: yalnız `In Progress` + gerçek issue + kayıtlı `claim_session` +
  parse-edilebilir + geçmiş `expires_at`; `Blocked` / `Needs Verify` / `Done`
  asla dokunulmaz.
- Bounded: `--limit` (default 20) run başına.

**Düşürülen — `/claim` arbiter Action**: `board-sync.sh claim` deterministik
claim zaten race-correct (winner_of 8/8 unit-test); arbiter yalnız
`concurrency` serialization eklerdi — correctness gerektirmiyor + ikinci bir
claim giriş yolu açardı. Gerçek bir race-failure gözlenirse yeniden değerlendirilir.

---

## 16. İterasyon-3 — Backlog lane (keşfedilen işi yakalama)

İş sırasında çıkan scope-dışı iş/sorun (başka bug, eksik test, stale doc,
follow-up) **kaybolmamalı**. iter-3 bunun için `Backlog` statüsünü + tek-komut
yakalamayı ekler.

**Yakalama** — agent scope-dışı bir bulgu görünce:

```
board-sync.sh backlog-add "<kısa başlık>" --note "<bağlam>" [--repo <owner/repo>] [--kind issue|risk]
```

Bu, hedef repo'da `project-roadmap` label'lı bir issue açar (agent-state body,
`status: backlog`), Project #2'ye ekler, `Kind` + `Status=Backlog` set eder.
`backlog-add`, native `item-added → Todo` workflow'una karşı post-add status
reconcile yapar (item `Backlog`'da kalsın — bounded retry).

**Backlog ≠ eligible**: `Backlog` item'lar `board-sync.sh list` "Eligible"
bölümünde **görünmez**, claim edilemez (§9 hard-gate). `list` yalnız bir
Backlog **sayısı** gösterir (triage hatırlatması) — roadmap view kirlenmez.

**Triage** (insan/agent yargısı): Backlog item gözden geçirilir →

- gerçek iş ise → `Status=Todo` + `Faz` / `Track` / `Priority` + acceptance
  kriteri / `Next Action` doldurulur (board UI veya `gh project item-edit`);
  artık eligible.
- gürültü / geçersiz ise → issue kapatılır.

`Backlog` item triage edilmeden PR'da `Tracked by` ile bağlanmaz.

**`backlog-add` vs `spawn_task`** — farklı amaçlar, ikisi de gerekebilir:

| Mekanizma | Ne için | Kalıcılık |
|---|---|---|
| `backlog-add` | "Kaybolmasın, sonra triage edilsin" | Board'da kalıcı issue |
| `spawn_task` | "Şimdi paralel session'da yapılsın" | Ephemeral chip — board truth üretmez |

**Kural**: scope-dışı bulgu → **her zaman `backlog-add`** (kalıcı kayıt). Ek
olarak iş *şimdi paralel* yapılacaksa `spawn_task` da açılır. spawn_task tek
başına yeterli değildir — chip kaybolur, board'da iz bırakmaz.

---

## 17. Coordination Ledger v1 — paralel ajan claim/permission hardening

2026-06-13 Claude / Mavis / Codex ping-pong mutabakati sonucu paralel ajan
calismasi icin mevcut board claim disiplini `coordination-ledger` tabanli bir
izin katmaniyla guclendirilecek.

Canonical plan: [`docs/coordination-ledger-v1-plan.md`](./coordination-ledger-v1-plan.md)

Tracked by: [platform-k8s-gitops#1498](https://github.com/Halildeu/platform-k8s-gitops/issues/1498)

Temel kararlar:

- `board-sync require-claim --operation ...` read-only permission gate olacak.
- Project #2 `Status/Faz/Track/Priority/Kind` alanlari izin predicate'ine girecek.
- Mavis mesajlari claim, approval, recovery veya closure authority olmayacak.
- Runtime/gate PR'lar `Tracked by #N` kullanacak; `Closes/Fixes/Resolves #N` yasak kalacak.
- `gate-forbidden-close-keywords.yml` bu kuralı PR metadata + commit mesajları
  seviyesinde fail-closed denetleyecek.
- Invalid ledger suffix repo-wide fail-closed kabul edilecek.
- Takeover iki asamali olacak: `TAKEOVER_ACCEPTED` -> mirror verify -> `TAKEOVER_COMMITTED`.

Ilk implementation slice'i mevcut Project #2 + issue body mirror'lari uzerinden
read-only gate saglar:

```bash
bash scripts/board-sync.sh require-claim \
  --issue <issue> \
  --session "$BOARD_SESSION_ID" \
  --operation file_write
```

Bu komut GitHub write path'lerine dokunmaz; JSON `allowed=true|false`,
`deny_code` ve deny durumunda `deny_event_intent_id` uretir. `COORDINATION_LEDGER_PATH`
set edildiginde ayni read-only gate ledger replay sonucunu da permission
predicate'ine dahil eder. CAS-backed mirror write ve `DENY_RECORDED` retry
ayri helper'lar uzerinden gelir; reaper mutation ve takeover commit mekanigi
ayri implementation slice'laridir.

`record-deny` ilk implementation slice'inda fail-closed local audit debt queue
olarak calisir:

```bash
scripts/board-sync.sh record-deny --intent-file deny.json
```

CAS writer henuz yokken komut GitHub/Project'e yazmaz; intent'i
`.local/coordination-audit-debt.jsonl` dosyasina dedupe ederek ekler ve
`blocked_audit_debt` sonucu ile nonzero doner. Bu, pre-mutation wrapper'in
audit kaydi alinmadan mutation'a devam etmesini engeller.

### 17.1 Project GraphQL budget / mirror queue hardening

2026-06-13 ikinci Claude / Mavis / Codex ping-pong mutabakati sonucu Project
v2 GraphQL rate-limit problemi ayri bir implementation slice'i olarak kabul
edildi.

Problem REST fallback eksikligi degildir. PR create/merge, issue body/comment
ve check-run okuma REST ile devam edebilir. Sorun, Project #2 custom field
truth'unun GraphQL-only olmasi ve board hot path'te pahali `item-list` /
`item-edit` cagirilariyla tuketilmesidir.

Canonical ayrim:

- `project_item_id` sadece **locator cache**'tir; Project truth degildir.
- Project field catalog repo-level fixture'dir:
  `docs/coordination/project-field-catalog-v1.json`; her issue body'ye
  kopyalanmaz.
- `PROJECT-DEFERRED v1 key=...` marker'i low-risk Project mirror mutation
  borcunu kaydeder; board Status yerine gecmez.
- Queue sadece low-risk mirror repair icin kullanilir:
  `PR merged -> Needs Verify` ve release sonrasi `Todo` reconcile.
- `backlog-add` queue'ya alinmaz. GraphQL budget yoksa GitHub issue
  olusturmadan fail-closed olur; aksi halde board disi orphan capture riski
  dogar.
- Queue **asla** `Done`, `issue_close`, `live_mutation`, `deploy`, `recovery`
  veya `key_rotation` icin kullanilmaz.

Operation policy:

| Operation class | Project GraphQL yoksa davranis |
|---|---|
| `local_edit`, `file_write` | Devam edebilir; `require-claim` REST issue-body claim/lease kanıtını doğrular, board mutation implied degildir. |
| `commit`, `push`, `pr_create`, `pr_update` | REST issue/PR evidence valid ise devam edebilir; `require-claim` REST issue-body claim/lease kanıtını doğrular, yalniz low-risk Project mutation deferred edilir. |
| `release` | Issue-body claim REST ile bırakılır; Project `Status -> Todo` reconcile yalnız `PROJECT-DEFERRED` marker olarak kuyruğa alınır. |
| `backlog-add` | Fresh Project truth yoksa GitHub issue açmadan fail-closed olur; queue kullanılmaz. |
| `claim`, `list`, `sync-state`, `reap` | Fresh Project truth yoksa yeni claim veya authoritative board mutation yoktur; sadece clearly-labeled stale/read-only output olabilir. |
| `live_mutation`, `deploy`, `issue_close`, `recovery`, `key_rotation` | Fresh Project truth + valid claim yoksa fail-closed. |

Fresh Project truth kritik operasyonlar icin Project item lookup çıktısındaki
`refreshed_at_epoch` yaşının `PROJECT_TRUTH_TTL_SECONDS` (default 300 saniye)
altında kalmasıdır. `require-claim` sonucu bunu `project_truth` alanında
raporlar. Truth stale/missing/future ise veya GraphQL budget yoksa kritik
operasyon durur.

Budget guard:

```bash
bash scripts/board-sync.sh graphql-budget \
  --operation pr_update \
  --mutation-risk low-risk
```

`verify` komutu GraphQL exhausted ise `PR merged -> Needs Verify` mirror
mutation'ini GitHub-visible `PROJECT-DEFERRED v1` marker olarak kaydeder;
body `agent-state.status`'u `needs-verify` yapmaz ve Project #2 degismis gibi
sunmaz.

`drain-project-queue` idempotent, bounded, rate-aware ve no-downgrade olmak
zorundadir. Drain sirasinda Project item state degismisse item overwrite
edilmez; stale-skip audit marker'i uretilir.

#### 17.1.1 Project required-field hygiene

Project #2 required field drift'i icin read-only/default arac:

```bash
python3 scripts/board-hygiene-audit.py --json
```

Arac varsayilan live modda yalniz Project item payload'ini kullanir
(`title`, `body`, `repository`, `number`). Boylece board hygiene icin her item'da
ayri `gh issue view` cagrisi yapilmaz ve GraphQL/REST budget gereksiz
tuketilmez. Label/state tabanli daha zengin kontrol gerekiyorsa operator bilincli
olarak `--hydrate-issues` verir.

Apply modu yalniz deterministik alanlari yazar; `Faz`, `Priority` veya `Status`
icin yeterli kanit yoksa manual queue'da birakir:

```bash
python3 scripts/board-hygiene-audit.py --apply --max-mutations 75
```

Manual alanlari otomatik uydurmak yasaktir. Backfill sonrasi beklenen saglik
sinyali `proposal_count=0`; kalan `manual_count` triage borcudur, closure kaniti
degildir. Bu durumda ajan kalan manuel borcu issue timeline'inda veya handoff'ta
tek tek tahmin etmeden göstermek için markdown manual-exception raporu üretir:

```bash
python3 scripts/board-hygiene-audit.py \
  --manual-exception-report /tmp/project-2-manual-exceptions.md
```

Manual-exception raporu closure degildir; yalniz `Faz`/`Priority`/`Status`
gibi kanitla türetilemeyen alanlarin triage listesidir. Offline regresyon
guard'i:

```bash
bash scripts/test/board-hygiene-audit.sh
```

Scheduled visibility surface:

**`.github/workflows/board-hygiene-audit.yml`** — daily schedule +
`workflow_dispatch`. Default run is read-only: it executes
`scripts/board-hygiene-audit.py --json --manual-exception-report ...`, writes a
GitHub job summary, and uploads `audit.json` + manual exception markdown as an
artifact. If Project GraphQL budget is exhausted, scheduled read-only runs skip
with an explicit summary instead of burning retries; manual `apply=true` fails
closed when budget is insufficient. `apply=true` is bounded by
`max_mutations` and only applies deterministic proposals; manual fields stay
manual and must not be guessed.

Issue-scoped drain:

```bash
bash scripts/board-sync.sh drain-project-queue --issue <owner/repo#N> --limit 20
```

Drain terminal marker'lari:

- `PROJECT-DRAINED v1 key=...` — mutation applied veya already-target.
- `PROJECT-STALE-SKIP v1 key=...` — no-downgrade, forbidden target,
  unsupported mutation veya stale state.

Pending `PROJECT-DEFERRED v1 target="Needs Verify"` marker'i varken `claim`
reddedilir. Bu, PR merge evidence kuyruğa düşmüşken başka ajanların item'ı
yeniden `Todo/In Progress` gibi ele almasını engeller.

### 17.2 Coordination ledger replay verifier

Ledger replay verifier read-only/offline bir guard'dır:

```bash
python3 scripts/coordination/verify-ledger-replay.py <ledger.jsonl>
```

Guard `docs/coordination/ledger-event-authority-v1.json` dosyasındaki event
authority sözleşmesine göre JSONL ledger'ı genesis'ten replay eder ve ilk
invalid suffix'te nonzero döner. Kontroller:

- unknown event type fail-closed;
- unauthorized writer fail-closed;
- `payload_hash`, `previous_event_hash`, `event_hash` zinciri;
- `committed_at` geriye gitmez;
- aynı `event_uuid` yalnız byte-identical retry ise idempotent kabul edilir.

Bu verifier tek başına claim yetkisi vermez ve GitHub/Project yüzeylerini
mutate etmez. `require-claim`, `COORDINATION_LEDGER_PATH` set edildiginde bu
verifier'i read-only predicate girdisi olarak kullanir; ledger append veya
mirror repair yapmaz.

### 17.3 Coordination ledger local append writer

Local/offline append writer foundation:

```bash
python3 scripts/coordination/append-ledger-event.py \
  --ledger .local/coordination-ledger.jsonl \
  --expect-previous-hash <GENESIS|sha256:...> \
  --event-type <EVENT> \
  --writer-role <ROLE> \
  --payload-json '<json-object>'
```

Bu writer mevcut ledger'ı genesis'ten replay eder, invalid suffix varsa yazmayı
reddeder, `--expect-previous-hash` CAS guard'ını uygular, candidate ledger'ı
temp dosyada doğrular ve sadece sonra tek JSONL event append eder. Bu foundation
GitHub issue/comment, Project #2 veya PR mirror mutate etmez; remote/branch CAS
ve materialized comment binding sonraki coordination slice'ında tamamlanır.

### 17.4 Coordination ledger materialized comment binding

Replay verifier `comment_binding` alanını gördüğünde binding yapısını
fail-closed doğrular. Şu foundation yalnız offline doğrulama yapar:

- `surface=github_issue_comment`;
- `repository`, `issue`, `comment_id`, `author_id`, `author_login`,
  `author_type`;
- `raw_body_hash`;
- binding `payload_hash` event `payload_hash` ile birebir aynı;
- `updated_at == created_at` (edited comment reddedilir);
- `verification_mode=normal|degraded|recovery`;
- timestamp tolerance: normal `5m`, degraded/recovery `15m`.

Bu verifier GitHub comment fetch/create/edit yapmaz. Comment writer/fetch
verification ve CAS sonrası issue/Project/PR mirror mutation ayrı slice olarak
açık kalır.

### 17.5 Coordination ledger remote branch CAS append

Remote branch CAS append foundation:

```bash
scripts/coordination/append-ledger-branch.sh \
  --remote origin \
  --branch coordination-ledger \
  --ledger-path coordination-ledger/events.jsonl \
  --commit-title "coordination ledger append" \
  --commit-message "Tracked by #1498" \
  -- \
  --expect-previous-hash sha256:<last-ledger-event-hash> \
  --event-type <EVENT> \
  --writer-role <ROLE> \
  --payload-json '<json-object>'
```

Wrapper mevcut ledger branch'ini temp ref'e fetch eder, detached temp worktree
açar, local append writer ile JSONL event'i üretir, sadece ledger path diff'ini
commit eder ve `--force-with-lease` ile fetched branch OID'e karşı push eder.
Branch yarışında push reddedilir ve caller yeniden okuyup tekrar denemelidir.

Bu wrapper issue body, Project #2, PR body veya GitHub comment mutate etmez.
Mirror-safe emission, denial debt retry ve comment writer/fetch verification
ayrı slice olarak açık kalır.

### 17.6 Coordination ledger materialized comment writer/fetch path

Materialized comment helper:

```bash
python3 scripts/coordination/materialize-ledger-comment.py render ...
python3 scripts/coordination/materialize-ledger-comment.py verify --comment-json fetched-comment.json ...
python3 scripts/coordination/materialize-ledger-comment.py post ...
```

`render` deterministik GitHub issue comment gövdesi üretir. `verify`, fetch
edilmiş GitHub issue comment JSON'unu marker/body/timestamp kurallarıyla
doğrular ve ledger event için `comment_binding` JSON'u çıkarır. `post`, comment'i
`gh api` ile oluşturur, hemen geri fetch eder ve aynı verifier'dan geçirir.

Bu helper tek başına ledger event append etmez, Project #2 mutate etmez, issue
body veya PR body değiştirmez ve claim yetkisi vermez. Çıkan `comment_binding`
ancak remote branch CAS append writer ile ledger'a girdikten ve mirror-safe
emission tamamlandıktan sonra permission predicate girdisi olabilir.

### 17.7 Coordination ledger mirror-safe emission helper

Mirror-safe emission helper:

```bash
scripts/coordination/emit-ledger-event.sh \
  --repo Halildeu/platform-k8s-gitops \
  --issue <N> \
  --expect-previous-hash sha256:<last-ledger-event-hash> \
  --event-type <EVENT> \
  --writer-role <ROLE> \
  --payload-json '<json-object>' \
  --post-comment
```

Helper once payload hash'i canonical JSON ile hesaplar, materialized comment'i
olusturup/fetch edip verifier'dan gecirir, sonra `comment_binding` ile remote
branch CAS append writer'i cagirir. Ledger push'u `--force-with-lease` ile
basarili olmadan issue body, Project #2 veya PR body mirror'i mutate edilmez.

`--comment-json` modu yalniz offline fixture/test icindir. `--post-comment`
sonrasi remote CAS fail olursa olusan comment yetki vermez; orphan candidate
olarak reaper/orphan akisi tarafindan islenir.

### 17.8 Coordination ledger read-only reaper detector

Read-only reaper detector:

```bash
python3 scripts/coordination/reap-ledger-state.py \
  --ledger coordination-ledger/events.jsonl \
  --mirror-json mirror-snapshot.json \
  --audit-debt-jsonl .local/coordination-audit-debt.jsonl
```

Detector ledger'i verifier ile replay eder. Invalid suffix gorurse
`fail_closed=true` ve `LEDGER_INVALID_SUFFIX` finding'i uretir. Ledger valid
ise stale/expired claim, mirror drift/orphan ve orphan materialized comment
finding'lerini explicit mirror snapshot uzerinden raporlar. Local audit-debt
queue icin bounded dedupe sayaci ve CAS-backed retry komut bilgisini uretir.

Bu helper issue body, Project #2, PR body, comment veya ledger branch mutate
etmez. Ciktisi sonraki CAS-backed reaper/retry ve repair akislari icin
makine-okunur evidence input'udur.

### 17.9 Coordination ledger takeover/recovery flow planner

Takeover/recovery planner:

```bash
python3 scripts/coordination/takeover-recovery-flow.py \
  --ledger coordination-ledger/events.jsonl \
  --phase accept|commit|recovery \
  --repo Halildeu/platform-k8s-gitops \
  --issue <N> \
  --old-session <old> \
  --new-session <new>
```

`accept` fazi mevcut old-session claim'ini ledger'da gormeden plan uretmez ve
`TAKEOVER_ACCEPTED` payload'inda hem eski hem yeni oturum icin permission=false
tutar. `commit` fazi en son matching takeover event'i `TAKEOVER_ACCEPTED`
degilse veya issue body / Project / PR mirror verification JSON'u tam degilse
`TAKEOVER_COMMITTED` planlamaz. `recovery` fazi owner approval evidence JSON'u
olmadan `OWNER_APPROVAL_EVIDENCE` / `OWNER_APPROVED` planlamaz.

Planner read-only'dir: GitHub, Project, comment veya ledger mutate etmez.
Urettigi event planlari mevcut `emit-ledger-event.sh` + remote CAS hattindan
append edilmelidir.

### 17.10 Coordination ledger-backed require-claim predicate

`require-claim` varsayilan olarak Project #2 + issue body mirror predicate'i
ile calisir. Ledger replay predicate'i opsiyoneldir ve yalniz
`COORDINATION_LEDGER_PATH` set edildiginde devreye girer:

```bash
COORDINATION_LEDGER_PATH=coordination-ledger/events.jsonl \
  bash scripts/board-sync.sh require-claim \
  --issue <owner/repo#N> \
  --session "$BOARD_SESSION_ID" \
  --operation commit
```

Bu modda `scripts/board-sync.sh`, `scripts/coordination/ledger-claim-state.py`
ile ledger'i genesis'ten replay eder ve JSON sonucuna `ledger` alanini ekler.
Ledger state `active_winner` degilse, session uyusmuyorsa, claim expired/stale
ise, takeover pending ise veya ledger suffix invalid ise `require-claim`
fail-closed doner. Invalid suffix hem normal Project path'inde hem de
GraphQL-exhausted REST-only low-risk path'inde `invalid_ledger_suffix` olarak
deny edilir.

Bu gate read-only'dir. Ledger append, issue body edit, Project #2 field update,
PR body update, materialized comment post veya drift repair yapmaz. Bu
yuzeylerde mutation yalniz CAS-backed emitter / reaper / mirror-write
slice'lariyla gelir.

### 17.11 Coordination ledger post-CAS mirror writes

Post-CAS mirror writer:

```bash
python3 scripts/coordination/apply-ledger-mirrors.py \
  --cas-result emit-result.json \
  --plan mirror-write-plan.json \
  --apply
```

Bu helper yalniz `emit-ledger-event.sh` sonucunda gelen
`status=ledger_event_emitted_after_remote_cas` kanitini kabul eder. Mirror plan
icindeki `expected_event_uuid` ve `expected_event_hash`, CAS sonucundaki ledger
event ile birebir eslesmezse issue body, Project #2 veya PR body mutation
yapilmaz.

Mutation oncesi tum yuzeyler validate edilir:

- issue body `agent-state:v1` beklenen status/session ile eslesmeli;
- Project planindaki current fields no-downgrade kuralini gecmeli ve yazilar
  field catalog option id'leriyle yapilmali;
- PR body sadece `coordination-ledger-pr-mirror:v1` marker block icinde
  guncellenmeli; mevcut marker icin beklenen alanlar uyusmazsa fail-closed.

Kismi apply hatasinda helper `mirror_write_failed_repair_required` ve
`repair_debt[]` uretir; bu ciktinin kendisi permission grant degildir. Kalan
repair/retry akisi reaper veya CAS-backed audit debt retry slice'indadir.

### 17.12 Coordination ledger audit-debt retry

Audit-debt retry helper:

```bash
python3 scripts/coordination/retry-audit-debt.py \
  --queue .local/coordination-audit-debt.jsonl \
  --remote origin \
  --branch coordination-ledger \
  --ledger-path coordination-ledger/events.jsonl \
  --post-comment \
  --limit 20
```

Bu helper `record-deny` tarafindan uretilen append-only local
`coordination-audit-debt/v1` queue kayitlarini bounded ve dedupe edilmis sekilde
okur, her `deny_event_intent_id` icin deterministik `DENY_RECORDED` event UUID
uretir ve mevcut `emit-ledger-event.sh` + remote branch CAS hattindan ledger'a
append eder.

Kurallar:

- Queue otorite degildir; otorite sadece valid ledger event'idir.
- Basarili retry veya zaten ledger'da bulunan event icin queue'ya terminal marker
  eklenir, eski kayitlar rewrite edilmez.
- Invalid ledger suffix, CAS mismatch, comment materialization hatasi veya
  fixture eksikligi mutation oncesi fail-closed olur.
- `DENY_RECORDED` audit-only event'tir; claim yetkisi vermez, revoke yapmaz,
  issue body / Project #2 / PR mirror mutate etmez.

### 17.13 Coordination ledger PR mirror validation

PR mirror validator:

```bash
python3 scripts/coordination/validate-pr-mirrors.py \
  --ledger coordination-ledger/events.jsonl \
  --snapshot pr-mirror-snapshot.json
```

Snapshot format'i PR body'lerini offline verir. Helper valid ledger replay
olmadan hicbir marker'i kabul etmez. Her `coordination-ledger-pr-mirror:v1`
marker'i icin `coordination_state`, `event_uuid`, `event_hash`, `session`
alanlari zorunludur; marker event hash'i ledger event hash'iyle, marker
session'i event payload session/new_session/old_session alanlariyla uyusmazsa
fail-closed doner.

### 17.14 Coordination ledger append-only CI enforcement

Append-only guard:

```bash
python3 scripts/coordination/enforce-append-only-ledger.py \
  --old old-events.jsonl \
  --new new-events.jsonl
```

Guard eski ledger'in non-empty satirlarini yeni ledger'in exact prefix'i olarak
ister. Rewrite, reorder, deletion veya truncation reddedilir; sonra eski ve yeni
ledger verifier'dan gecirilir. `gate-coordination-ledger-replay` workflow'u PR
ve push event'lerinde `coordination-ledger/**/*.jsonl` diff'leri icin bu guard'i
calistirir.

### 17.15 Coordination surface secret scan

Coordination-specific scanner:

```bash
python3 scripts/coordination/scan-coordination-secrets.py
```

Scanner ledger, coordination docs ve coordination scripts yuzeylerinde
high-confidence secret pattern'lerini arar: GitHub token, GitHub PAT, AWS access
key, Google API key, Slack token, private key ve uzun bearer token. Generic
`TOKEN=` gibi source-code false-positive ureten kaliplari kullanmaz. Finding
varsa redacted snippet ile nonzero doner ve permission grant uretmez.

### 17.16 Coordination ledger tombstone/supersede flow

Tombstone/supersede planner:

```bash
python3 scripts/coordination/tombstone-supersede-flow.py \
  --ledger coordination-ledger/events.jsonl \
  --phase tombstone|supersede \
  --repo Halildeu/platform-k8s-gitops \
  --issue <old-issue> \
  --new-issue <new-issue> \
  --mirror-verification-json mirror-verification.json \
  --reason "<reason>"
```

`tombstone` fazi eski issue chain'inin permission uretememesi icin
`TOMBSTONE_CHAIN` event planlar. `supersede` fazi `SUPERSEDE_ISSUE` event'ini
yalniz issue body, Project ve PR mirror verification JSON'u tam ise planlar.
Planner read-only'dir; event planlari yine `emit-ledger-event.sh` + remote CAS
hattindan append edilmelidir.
