# Faz 22 — Endpoint Admin / Endpoint Agent Plan (2026-05-21)

> ⚠️ **HISTORICAL DOCUMENT** (marked stale 2026-05-28 — Codex thread `019ea916` plan-time AGREE)
>
> **Current Faz 22 canonical truth sources** (do NOT use this doc for live state):
> - **`docs/state/current-state.md`** — live delta + status snapshot
> - **`docs/faz-22-software-deployment-plan.md`** — §0.1bis Truth Refresh 2026-05-29 (Faz 22.5 quick-wins canonical scope)
> - **`docs/faz-22.5-consensus-gate-tracker-m2-m7.md`** — M2-M7 + #1359 gate boundary matrix (source vs operator)
> - **`docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md`** — Plan A mass deployment ADR (ACTIVE 2026-05-26)
> - **`docs/adr/0012-EA-endpoint-admin-governance-charter.md`** — §22.2 + §22.3 (renamed → §22.4) governance
>
> Bu doc 2026-05-21'deki Endpoint Admin truth-refresh sprint'inde (board #924) hazırlandı; o tarihten sonra Faz 22 hattı genişledi: 22.2.A non-domain pilot live evidence + 22.3 mass deployment Plan A ADR-0029 + 22.5 software deployment quick-wins serisi. Aşağıdaki content **historical kayıt** olarak korunur; current iş kalemleri için yukarıdaki canonical truth source'larına bakın.

---

> **Status**: Draft v2 — controller (peer reviewer) şartlı GO; accepted defaults uygulandı; Plan A PR hazırlığına geçilebilir.
> **Issue**: [#924](https://github.com/Halildeu/platform-k8s-gitops/issues/924) (Endpoint Admin truth-refresh dokuman hizalama)
> **Working branch (bu oturum)**: `codex/endpoint-admin-truth-refresh-924` (origin/main'in behind 12 @ 2026-05-21T14:38Z; behind count **drift-prone** — main hareket ediyor; PR öncesi `git fetch` + son ölçüm zorunlu)
> **Co-existence**: ADR-0025 v2 sahibi paralel agent (charter reposition; thread `019e494f` iter-5 AGREE) + #924 claim sahibi farklı session (`roadmap-924-endpoint-admin-truth-refresh-dok`).
> **Rol**: Bu oturum kontrol/yönlendirme + Plan B/C destek; #924 yürütücüsü ayrı session.

---

## 1. Canlı kanıt (2026-05-21T14:38Z — drift refresh)

| Alan | Komut | Bulgu |
|---|---|---|
| Backend `origin/main` endpoint-admin tree | `git ls-tree -d origin/main` | `0` (kod main'de yok) |
| Backend side branch | `git branch -r \| grep endpoint-admin` | `origin/codex/be-001-endpoint-admin-service-platform-backend` mevcut |
| Backend divergence | `git rev-list --left-right --count origin/main...origin/codex/be-001-...` | **255 / 5** @ `2026-05-21T14:38:22Z` — **drift-prone** (245→250→252→255 son 24h; main hareket ediyor; PR öncesi son ölçüm zorunlu) |
| Backend side branch dosya sayısı | `git ls-tree -r ... \| wc -l` | 133 dosya `endpoint-admin-service/` |
| Backend PR durumu | `gh pr list --head codex/be-001-... --state open` | Açık PR yok; PR #61 side branch içine fix (main adoption değil) |
| Web `apps/mfe-endpoint-admin` | `git ls-tree -r origin/main apps/mfe-endpoint-admin \| wc -l` | **26** dosya scaffold + devices/audit/status pages + i18n |
| Agent `origin/main` son commit | `git log -1 origin/main` | `663db67 feat(ci): board-pr-evidence` |
| Agent CI son success | `gh run list --repo Halildeu/platform-agent` | `26030514275` "CI - Build, Test, Lab Signing" — conclusion success (2026-05-18) |
| Agent capability mismatch | `internal/inventory/inventory.go:43-57` raporlar `DISABLE_LOCAL_USER` + `ENABLE_LOCAL_USER`; `internal/commands/executor.go:51-94` switch'inde case yok → default `UNSUPPORTED` | ❗ Kod seviyesinde doğrulandı; pilot ön-koşulu blocker |
| GitOps test cluster | refresh metni + önceki tur kanıt | digest `sha256:5bb0fa2600...`, Deployment 1/1, health UP, no-JWT 401 → Up + basic Functional/fail-closed; full D29-EA Secured pending |
| Issue #924 board | `gh project item-list 2 --owner Halildeu` | `status: "In Progress"` (body'deki "Backlog" stale metin) |
| Issue #924 claim | body `agent-state:v1` bloğu | `claim_session: Halil-MacBook-Pro-84921-1779348092`, `claim_branch: roadmap-924-...-dok`, `claim_updated_at: 2026-05-21T08:39:55Z`, `expires_at: 2026-05-21T10:39:55Z` (heartbeat taze, ~12 dk kaldı) |

---

## 2. Co-existence durumu

Aynı host'ta paralel agent oturumları çalışıyor; iş paylaşımı:

| Konu | Sahip | Working branch | Çakışma |
|---|---|---|---|
| Endpoint Admin truth-refresh (#924) | Farklı session | `roadmap-924-endpoint-admin-truth-refresh-dok` | working tree'deki 5 endpoint-admin dosyası muhtemelen o agent'ın taslağı |
| ADR-0025 v2 QDMS reposition | Üçüncü agent | bilinmiyor (working tree'de M olarak duruyor) | Plan A 5 dosyası ile çakışma yok (file-level isolation) |
| Plan B (agent capability) | Bu oturum yürütebilir | `platform-agent` repo'sunda yeni | Farklı repo; çakışma yok |
| Plan C (backend reconciliation) | Bu oturum koordine edebilir | `platform-backend` repo'sunda yeni | Farklı repo; bu repo'da sadece digest bump PR'ı (sonradan) |

**Co-existence guard (Plan A için)**:

| G | Kural |
|---|---|
| G1 | Diğer agent'ın dosyasına dokunma (read-only) |
| G2 | Commit ayrımı — tek-amaçlı commit; ADR-0025 staging dışı |
| G3 | Push öncesi `git fetch` + log kontrolü; diğer commit varsa rebase (sadece kendi dosya; their stratejisi) |
| G4 | Conflict çıkarsa **revert yasak** (task constraint), dur, kullanıcıya rapor |
| G5 | Board görünürlük — her iş ayrı issue ile board'da |

---

## 3. Plan A — #924 Endpoint Admin truth-refresh (platform-k8s-gitops)

**Rol**: Bu oturum observer/support; yürütücü farklı session.

| Adım | İçerik | Sahip |
|---|---|---|
| A.0 | **Koordinasyon (accepted default)**: K1 — bu oturum kontrol/yönlendirme rolünde; #924 yürütücüsü farklı session. K2 (claim transfer) override edilmedi. | Controller / Yürütücü |
| A.1 | `scripts/board-sync.sh sync-state 924` → mevcut In Progress claim doğrula; expires_at geçtiyse `release` + yeni `claim` | Yürütücü session |
| A.2 | **PR kapsamı (kilit)**: `5 existing truth-refresh docs + 1 new planning doc`. Stage edilecekler: `PLAN.md`, `docs/state/current-state.md`, `docs/operations/services.yaml`, `docs/adr/0012-EA-endpoint-admin-governance-charter.md`, `docs/faz-22-evidence/2026-05-05-22-1-1b-d29-ea-canli.md`, **+ `docs/faz-22-endpoint-admin-plan-2026-05-21.md` (bu doküman, yeni)**. **Excluded**: `docs/adr/0025-enterprise-platform-charter.md` (diğer agent işi, kapsam dışı). Stage öncesi `git diff --check` ve scoped `git add -- <listed-files>`. | Yürütücü |
| A.3 | Patch'ler: (a) divergence sabit sayı yerine `Latest observed divergence: <value> @ <ISO-8601 Z>; drift-prone — main hareket ediyor; canonical reconciliation pending`; PR öncesi son ölçüm zorunlu. (b) "Bilinen riskler" alt-bölüm (capability mismatch source-pending + divergence drift + Windows VM stopped + TRACKING-ROADMAP drift) | Yürütücü |
| A.4 | Commit message: `docs(faz-22): endpoint-admin truth refresh #924 — backend canonical main missing + capability mismatch risk` (ADR-0025 ref YOK) | Yürütücü |
| A.4.5 | **Base drift check (PR öncesi zorunlu)**: behind count **drift-prone** (sırasıyla 9→12 gözlemlendi; her oturumda yeniden ölç). Sıra: `git fetch origin && git status -sb && git log HEAD..origin/main --name-only --pretty=format: | sort -u`. Dosya yüzeyi benim staged set ile **kesişmiyorsa** conflict riski yok (PR base=origin/main; GitHub otomatik merge eder). Kesişim varsa **revert YOK** (task constraint); dur, raporla, kullanıcı/controller kararı. Trivial fast-forward gerekiyorsa rebase uygulanır. | Yürütücü |
| A.5 | Push öncesi son `git fetch` + paralel oturum guard (diğer agent commit attı mı, G3); conflict varsa dur, raporla (G4) | Yürütücü |
| A.6 | PR aç → cross-AI peer review **tercih edilen disiplin** (Codex MCP yeni thread); araç erişim hatasında beklet/raporla — sistem durmaz, tool hatası acceptance kanıtı gibi yazılmaz | Yürütücü |
| A.7 | AGREE + CI yeşil → normal squash (`--admin` YASAK) + `ai-post-merge-cleanup.sh` | Yürütücü |
| A.8 | Post-merge: board #924 In Progress → Done (acceptance: merged SHA + review thread ref) | Yürütücü |

Bu oturum desteği: feedback/önerilerle yardım, kanıt sağlama, conflict tespitinde rapor.

---

## 4. Plan B — Agent capability mismatch (platform-agent)

**Rol**: Bu oturum yürütebilir (farklı repo; çakışma yok).
**Bağımlılık**: Plan A'dan bağımsız.

| Adım | İçerik |
|---|---|
| B.1 | `gh issue create -R Halildeu/platform-agent --label project-roadmap --title "AG-013 capability mismatch: DISABLE/ENABLE_LOCAL_USER reported but executor returns UNSUPPORTED"` body'de: kanıt referansları (inventory.go:50-54 + executor.go:51-94 + TRACKING-ROADMAP AG-013 satırı) + acceptance criteria |
| B.2 | `gh project item-add 2 --owner Halildeu --url <issue-url>` ile Project #2 board'a; manuel agent-state YAML body'ye eklenir (`scripts/board-sync.sh` agent repo'sunda yok) |
| B.3 | Branch `fix/agent-capability-mismatch`; claim heartbeat manuel |
| B.4 | **Fix tercih**: `inventory.go:50-54`'ten `CommandDisableLocalUser` + `CommandEnableLocalUser` **çıkar** (clean approach — adapter geldiğinde tekrar açılır). Adapter implementasyonu ayrı board issue. |
| B.5 | Yeni unit test `inventory_capability_test.go`: **dispatch behaviour assertion** — `RuntimeCapabilities()` içinde raporlanan her command, `LocalExecutor.Execute()` tarafından dispatch edilebilir olmalı (default `UNSUPPORTED`'a düşmemeli). Hedef: false advertising regression guard (geniş "switch case var mı" değil; gerçek dispatch ve non-UNSUPPORTED status assertion). |
| B.6 | **Aynı PR'a** `docs/TRACKING-ROADMAP.md` sync: WEB-001..WEB-005 "TODO → IN_PROGRESS (source-ready; runtime route acceptance backend main + Secured sonrası)"; AG-013 satırından eski capability mismatch notu çıkar |
| B.7 | `./scripts/test/local.sh` PASS + `./scripts/build/local.sh` PASS + `./scripts/build/windows-package.sh` PASS kanıtı PR body'de |
| B.8 | PR aç → cross-AI peer review tercih → AGREE → CI yeşil → normal squash |
| B.9 | **Fresh Windows VM smoke**: computer-use ile Parallels Windows 11 başlat → `windows-live.ps1` koş → capability sonrası regression doğrula → screenshots + log evidence |
| B' | (bu repo, follow-up küçük PR) `docs/adr/0012-EA-endpoint-admin-governance-charter.md` "Bilinen riskler"de capability mismatch satırını **"source-fixed; verification pending"** seviyesine düşür; AG-013 fix PR referansı ekle. **Tam kaldırma** ancak adapter implementasyonu + uzun süreli Windows smoke regression evidence sonrası. Aşamalı kapı: (a) source-fixed (B.4-B.8 sonrası); (b) verification pending (B.9 fresh smoke öncesi); (c) refreshed (B.9 sonrası); (d) closed (adapter PR + uzun süreli smoke). |

---

## 5. Plan C — Backend canonical main reconciliation (platform-backend)

**Rol**: Bu oturum koordine edebilir; büyük scope.
**Bağımlılık**: Plan B BE-011 agent live integration için gerek; aksi durumda paralel.

| Adım | İçerik |
|---|---|
| **C.0 PRE — dry-run conflict inventory** | Temp worktree (`git worktree add /tmp/be-reconcile-dryrun origin/main`); `git merge-tree origin/main origin/codex/be-001-endpoint-admin-service-platform-backend` ile çakışma yüzeyi listele: Maven module roots / `common-auth` / `Dockerfile` pattern / Flyway versiyonları / `RequireModule` annotation / RBAC config / `application-k8s.yml`. Çıktı: çakışan dosya sayısı + etki listesi (rapor olarak; kullanıcıya/Codex'e götürülür). |
| C.1 | `gh issue create -R Halildeu/platform-backend --label project-roadmap --title "Endpoint-admin canonical main reconciliation"` body'de: C.0 conflict inventory referansı + acceptance criteria (CI yeşil + BE-009 live + BE-013 live + image rebuild + GitOps digest bump) |
| C.2 | `gh project item-add 2 --owner Halildeu --url <issue-url>` Project #2 board'a |
| C.3 | **Codex strategic consult** (yeni thread): C.0 conflict inventory kanıtıyla "mega-PR mı, 3-4 sub-PR mı?" sorusu somut kanıtla. (HARD RULE #8: Codex Decision Authority + Plan Consensus Autonomy) |
| C.4 | Codex AGREE = kullanıcı kararı → direkt impl (plan onayı kullanıcıya tekrar sorulmaz) |
| C.5 | Reconciliation PR(lar); her PR cross-AI peer review tercih + AGREE → normal squash |
| C.6 | Backend image rebuild **canonical pipeline** (`platform-backend` repo'sunda; **ssot YASAK** — global HARD RULE 2026-05-06) |
| C.7 | **Bu repo'da** ayrı PR: `kustomize/overlays/test/...` digest pin yeni `sha256:...`'a güncelle; ADR-0023 test-overlay-authoritative + direct `kubectl set image/patch/edit` YASAK + scale-to-zero YASAK. Mevcut digest pod çalışmaya devam ederken yeni hazır olunca bump (TEST Cluster Scale-to-Zero YASAK + AGENTS.md §3) |
| C.8 | D29 üç katman ayrı evidence: (a) **Up** — pod imageID == GHCR digest match + Deployment 1/1; (b) **Functional** — admin endpoint allow/deny shape doğru + BE-013 maintenance token issue/validate/revoke/expire/audit; (c) **Secured/Zanzibar-ready** — OpenFGA tuple verify + persona allow/deny enforce + audit insert (BE-009 live + BE-013 live) |
| C.9 | BE-011 agent live integration smoke: Plan B capability-fixed agent → backend gerçek enroll/heartbeat/command/result |
| C.10 | Bu repo'da yüzde update PR: Backend canonicalization ~25% → ~70%+; "Bilinen riskler"den backend divergence drift satırını çıkar |

---

## 6. Yüzde mutabakat tablosu

| Alan | Refresh | Bu plan | Gerekçe |
|---|---:|---:|---|
| 22.0 Governance / repo split | ~80% | **80%** | ADR + repo placement var; #924 PR/board state hizası eksik |
| 22.1 GitOps test runtime | ~60% | **60%** | Up + basic Functional/fail-closed; full Secured pending |
| 22.1 Agent lab foundation | ~70% | **65%** | Foundation güçlü ama capability mismatch + fresh Windows smoke yok |
| 22.1 Backend canonicalization | ~25% | **25%** | Side branch olgun, main adoption yok |
| 22.1 Web source surface | ~25% | **35%** | 26-dosya scaffold `origin/main`'de + #287 fe-001 reapply meaningful; runtime gated |
| 22.2 IT pilot readiness | ~10% | **10%** | Sadece scope kararı (acik.local) |
| **Faz 22 toplam** | ~35% | **~33-35%** | Foundation + test runtime + agent lab; kabul kapıları büyük |

---

## 7. Bilinen riskler

| # | Risk | Etki | Mitigation |
|---|---|---|---|
| R1 | ❗ Agent capability mismatch (kritik) | Backend admin DISABLE/ENABLE_LOCAL_USER dispatch ederse Windows agent default'ta UNSUPPORTED döner; audit'te "agent fail" görünür, kök neden yanlış capability raporlama | **Aşamalı kapı**: (a) B.4-B.8 sonrası "source-fixed"; (b) B.9 fresh Windows smoke öncesi "verification pending"; (c) B.9 sonrası "pilot regression evidence refreshed"; (d) tam "closed" ancak adapter PR + uzun süreli smoke regression evidence sonrası. ADR/state risk listesinden hemen tam silmek YASAK. |
| R2 | Backend divergence drift devam ediyor | Main her gün ilerliyor (notify-23.7 webpush serisi 245→250→252); reconciliation geciktikçe rebase yükü artar | Plan C C.0 dry-run inventory + Codex consult kanıtla; reconciliation öncelik |
| R3 | Parallels Windows 11 VM stopped | AG-012/013/019 historical evidence taze değil; capability fix sonrası regression smoke koşmadan pilot riskli | Plan B.9 computer-use ile VM başlat + windows-live.ps1 koş |
| R4 | TRACKING-ROADMAP.md stale (Apr 29) | WEB-001..WEB-005 "TODO" yazıyor, scaffold mevcut; okur yanlış senkron | Plan B.6 aynı PR'da sync |
| R5 | #924 board state inconsistency | Body "Backlog" yazıyor ama board column "In Progress"; iki kaynak çakışıyor | Plan A.1 sync-state ile otoriter durumu netleştir |
| R6 | Paralel oturum claim çakışması | #924 claim farklı session'da (`roadmap-924-...-dok`); benim oturum aynı iş alanında | K1 observer rolü (default) ya da K2 claim transfer (kullanıcı) |
| R7 | Cross-AI peer review aracı erişim belirsizliği | Bu oturumda doğrulanan: **Claude CLI erişim hatası** (controller raporu). Codex / adversarial consult tool availability **ayrı doğrulanır** (Codex MCP'nin çalışma durumu kanıta dayalı değil). | Review discipline **tercih edilen disiplin** olarak uygulanır; **tool erişim hatası acceptance kanıtı gibi yazılmaz**. Araç yoksa: beklet, raporla, gerekirse alternatif review path (human reviewer); sistem durmaz ama "AGREE alındı" denmez. |

---

## 8. Controller decision — accepted defaults (applied 2026-05-21T11:03Z)

Controller (peer reviewer) tarafından accepted edilen ve **uygulanmış** kararlar:

1. **#924 koordinasyon yolu** — **K2 accepted, applied**: Bu oturum Plan A yürütücüsü. Claim 22 dakika önce expire olmuştu (10:39:55Z); `board-sync.sh claim 924` ile reclaim edildi (lease 2026-05-21T13:02:51Z; session `Halil-MacBook-Pro-64640-1779361371`; branch `codex/endpoint-admin-truth-refresh-924`; worktree `/Users/halilkocoglu/Documents/platform-k8s-gitops`). Issue body agent-state güncellendi. Controller/reviewer ayrı oturumda review/yönlendirme yapar.
   - K1 alternatifi (observer): override edildi.
   - Plan A.0 artık karar noktası **değil**; uygulanmış karar.
2. **Plan B fix tercihi** — **B-clean accepted**: Agent capability false advertising kapatılır (`inventory.go:50-54`'ten `DisableLocalUser` + `EnableLocalUser` çıkarılır). Gerçek Windows adapter implementasyonu **ayrı board issue + ayrı PR** (adapter geldiğinde capability listesine geri eklenir).
   - B-adapter alternatifi: tek-iter scope dışı; ayrı track.
3. **Plan C başlangıç sırası** — **C-paralel accepted**: Plan B ile paralel; **C.0 dry-run conflict inventory** Plan B ile birlikte başlatılabilir. Reconciliation impl C.0 + Codex strategic consult sonrası.
   - C-sıralı alternatifi: Plan A merge sonrasına ertelenmez; bağımsız track.

Override gerektiren stratejik sapma durumunda kullanıcı yine üst karar mercii (HARD RULE #8 Plan Consensus Autonomy).

---

## 9. Kural referansları

| Kural | Konum | Plan etkisi |
|---|---|---|
| Live truth > optimistic doc | [AGENTS.md §3](../AGENTS.md) | Tüm yüzde tablosu + risk register canlı kanıttan |
| No Closure Language | [docs/context-priority-rules.md §4.4](./context-priority-rules.md) | "Bitti/kapandı/tamamlandı" yasak; mevcut truth + sıradaki kapı dili |
| D29 üç katman | [docs/context-priority-rules.md §4.1](./context-priority-rules.md) | Plan C.8 — Up/Functional/Secured ayrı evidence |
| D30 immutable artifact | AGENTS.md §3 | Plan C.7 — digest pin; moving tag YASAK |
| Test overlay GitOps-authoritative | [ADR-0023](./adr/0023-promotion-pipeline.md) | Plan C.7 — overlay üzerinden değişim; direct kubectl YASAK |
| TEST Cluster Scale-to-Zero YASAK | Global memory (2026-05-10) | Plan C.7 — paralel multi-session geliştirme modeli korunur |
| Admin Merge YASAK | Global memory (2026-05-05) | Plan A.7 + B.8 + C.5 — `--admin` flag yok |
| Cross-AI peer review | Global memory (2026-05-05 + 2026-05-14) | Plan A.6 + B.8 + C.5 — tercih + tool unavailability fallback |
| HARD RULE #8 Codex Decision Authority | [CLAUDE.md §1.8](../CLAUDE.md) | Plan C.3 — strategic karar Codex consult |
| Plan Consensus Autonomy | Global memory (2026-04-17) | Plan C.4 — Codex AGREE → direkt impl |
| ssot DEPRECATED | Global memory (2026-05-06) + [CLAUDE.md](../CLAUDE.md) | Plan C.6 — canonical pipeline only |
| Board protocol claim-before-work | [docs/board-protocol.md](./board-protocol.md) | Plan A.1, B.1-B.3, C.1-C.3 — issue + claim + heartbeat |

---

## 10. Bu dokümanın kapsamı

- **Kapsamda**: Faz 22 Endpoint Admin / Endpoint Agent yol haritası, repo-aware iş ayrımı, co-existence guard
- **Kapsam dışı**: ADR-0025 v2 QDMS reposition (farklı agent), Faz 23 notification orchestration, Faz 24 charter implementation
- **Görev tetikleyici**: 2026-05-21 live/repo recheck + peer feedback absorb
- **Yaşam döngüsü**: Bu doküman draft v1; karar noktaları çözüldükten sonra v2 olarak güncellenir; Plan A merge sonrası "executed" durumuna geçer
