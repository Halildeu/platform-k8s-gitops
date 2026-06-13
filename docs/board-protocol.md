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
`gh` shim ile **7 senaryoyu** deterministic koşturur:

1. PAT present — full path: Project API + EVIDENCE comment + body rewrite + board Status
2. PAT present REPAIR (iter-2 P1 + iter-3 P1 #2) — pre-existing EVIDENCE; comment ATLANIR ama body rewrite (`gh issue edit`) + board (`project item-edit`) STILL fire'lar
3. PAT missing, same-repo — comment-only, Project API'ye DOKUNMAZ
4. PAT missing, cross-repo — soft-skip + `::warning::` annotation + step summary, network'e DOKUNMAZ
5. PAT missing, idempotent — pre-existing EVIDENCE → comment ATLANIR
6. PAT missing, lowercase same-repo (iter-3 P1 #3) — case-insensitive compare, false cross-repo skip YOK
7. Workflow guard — boş GH_TOKEN durumunda `::error::` + exit 1 (file-level grep assertion)

Yeni regression bu harness'la lokal yakalanır, gerçek merge beklemeden.

**`.github/workflows/board-pr-evidence.yml`** — `pull_request: closed` (merged).
PR body'sindeki `Tracked by <ref>` satırlarını parse eder, her ref için
`board-sync.sh verify` çağırır.

- Ref formatları: `#N`, `owner/repo#N`, tam issue URL'i — **cross-repo
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
`deny_code` ve deny durumunda `deny_event_intent_id` uretir. Ledger replay,
CAS writer, `record-deny`, reaper ve takeover mekanigi sonraki implementation
slice'laridir.

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
  `PR merged -> Needs Verify`, `backlog-add` reconcile, release sonrasi `Todo`
  reconcile.
- Queue **asla** `Done`, `issue_close`, `live_mutation`, `deploy`, `recovery`
  veya `key_rotation` icin kullanilmaz.

Operation policy:

| Operation class | Project GraphQL yoksa davranis |
|---|---|
| `local_edit`, `file_write` | Devam edebilir; board mutation implied degildir. |
| `commit`, `push`, `pr_create`, `pr_update` | REST issue/PR evidence valid ise devam edebilir; yalniz low-risk Project mutation deferred edilir. |
| `claim`, `list`, `sync-state`, `backlog-add`, `reap` | Fresh Project truth yoksa yeni claim veya authoritative board mutation yoktur; sadece clearly-labeled stale/read-only output olabilir. |
| `live_mutation`, `deploy`, `issue_close`, `recovery`, `key_rotation` | Fresh Project truth + valid claim yoksa fail-closed. |

Fresh Project truth kritik operasyonlar icin `refreshed_at <= 5 dakika` olarak
yorumlanir. Stale ise refresh denenir; GraphQL budget yoksa kritik operasyon
durur.

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
