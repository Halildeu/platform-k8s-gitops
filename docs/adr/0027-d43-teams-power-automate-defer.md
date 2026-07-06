# 0027 — D43 Teams Power Automate Fallback: SMTP Primary, Teams Deferred Asset-Preserved

> **Status**: Accepted
> **Tarih**: 2026-05-25
> **Karar otoritesi**: Codex thread `019e5bdb` (hibrit C strategic verdict — cross-AI peer review)
> **Antecedent reviews**: `019e5b9c` (SMTP-only D43 v1 acceptance — canonical, MERGED to main), `019e5ba9`/PR #1053 (Teams Power Automate pivot — audit-only superseded)
> **Öncüller**: [ADR-0013 — Notification orchestration](./0013-notification-orchestration.md) D43 (outage fallback bypass), [ADR-0024 — Graph mail adapter defer](./0024-graph-mail-adapter-defer.md) (parallel "deferred but asset-preserved" pattern reference), [RB-notification-outage-fallback.md](../runbooks/RB-notification-outage-fallback.md), [RB-prod-alertmanager-activation.md](../runbooks/RB-prod-alertmanager-activation.md)
> **Implementation State**: D43 outage fallback **SMTP-only source-side/desired-state canonical** (helm-values + ESO 4-key); **prod activation operator-bound** (Vault seed + helm upgrade + dual-receipt smoke — R9 mitigation row + board #854); production-ready claim YOK. Microsoft Teams Power Automate workflow **deferred**, **no active rendered config**, **no non-empty Vault secret**, **no Helm receiver block**
> **Yürütür**: Faz 23.x notification platform — operator incident channel routing track
> **Reactivation runbook**: [RB-d43-teams-reactivation-chain.md](../runbooks/RB-d43-teams-reactivation-chain.md) (post-trigger atomic activation chain)

---

## Context

D43 outage fallback (`notification-orchestrator` down olduğunda Alertmanager direkt external channel) için 2026-05-24'te iki çelişen yorum ortaya çıktı:

### Conflicting interpretation paths

**Path 1 — Codex thread `019e5b9c` (paralel agent, MERGED to main)**:
- Yorum: "Slack kullanmıyoruz teams kullanıyoruz" = chat workflow karmaşık + SaaS lifecycle riski; SMTP-only D43 v1 yeterli mitigation; Slack/Teams DEFER future trigger.
- Impl: `risk-register.md` R9 SMTP-only D43 v1 acceptance redefine; Slack DEFER (board #853 + #1012); `values-prod.yaml` `direct-fallback` block'tan `slack_configs` leg removed; ESO `externalsecret-alertmanager-fallback.yaml` `SLACK_WEBHOOK_URL` secretKey REMOVED + commented out (sadece `SMTP_*` keys aktif).
- Evidence: `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md`

**Path 2 — Codex thread `019e5ba9` (PR #1053, CLOSED 2026-05-25)**:
- Yorum: "Slack kullanmıyoruz teams kullanıyoruz" = Microsoft Teams adopt et; Teams Power Automate workflow webhook'a pivot et.
- Impl: helm-values `slack_configs` → `webhook_configs` (Teams Power Automate workflow URL); ESO `SLACK_WEBHOOK_URL` → `TEAMS_WEBHOOK_URL` rename; canonical runbooks tam Teams sweep; R27 NEW (Power Automate lifecycle drift, 7-step mitigation).
- Cross-AI iter-1..iter-5 chain, iter-5 AGREE ready_to_merge=true.

### Kullanıcı 2026-05-25 hibrit kararı (Opsiyon C)

> "Hibrit: SMTP primary + Teams future trigger optional"

- Main'in SMTP-only D43 v1 canonical kararı **korunur**
- Teams Power Automate workflow **asset-preserved dormant** (R23/ADR-0024 "deferred but asset-preserved" pattern paralel)
- Helm + ESO config Vault `TEAMS_WEBHOOK_URL` **non-rendered, no active dependency**
- Teams reactivation **trigger-driven**, planned değil

Bu çelişki resolution + hibrit yön normalizasyonu, ayrı bir ADR ile kanıtlanır (mevcut R9/R27/ADR-0024 üzerinde override yapmadan); ileride trigger gelirse [RB-d43-teams-reactivation-chain.md](../runbooks/RB-d43-teams-reactivation-chain.md) çalıştırılır.

---

## Decision

### D1 — SMTP Office 365 + Mailpit path D43 outage fallback canonical olarak korunur

Main'deki `019e5b9c` kanonik kararı korunur:

- `helm-values/kube-prometheus-stack/values-prod.yaml` `direct-fallback` receiver `email_configs` tek leg (SMTP smarthost `smtp.office365.com:587`)
- `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` `direct-fallback` receiver `email_configs` tek leg (Mailpit no-auth `mailpit.platform-test.svc.cluster.local:587`)
- ESO `externalsecret-alertmanager-fallback.yaml` `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` 4 key
- Vault path `kv/platform/alertmanager-fallback` 4 key (`SLACK_WEBHOOK_URL` removed; `TEAMS_WEBHOOK_URL` **not present**)
- R9 mitigation row `🟢 Mitigated (SMTP-only D43 v1; Slack DEFER per user decision 2026-05-24)` korunur

### D2 — Microsoft Teams Power Automate workflow deferred-but-asset-preserved

PR #1053 (Codex `019e5ba9` Teams Power Automate pivot impl) **audit-only superseded** kayıt olarak korunur. Implementation **canlıya alınmaz**. Audit malzemesi olarak kalır:

- PR #1053 closed diff'i historical reference olarak GitHub'da accessible
- Diff'teki helm-values + ESO + runbook + risk register değişiklikleri **template reactivation snippets** olarak [RB-d43-teams-reactivation-chain.md](../runbooks/RB-d43-teams-reactivation-chain.md) içinde fenced code block referansları
- R27 (Teams Power Automate workflow lifecycle drift) `⏳ DEFER asset-preserved` status (Active değil; dormant trigger conditional)

### D3 — Teams activation TRIGGER-driven, planned değil

Aktivation chain yalnız aşağıdaki tetik koşullarından **en az biri** geldiğinde çalıştırılır:

1. **SMTP outage / Office 365 mail delivery tenant break** — `alertmanager-fallback@acik.com` SMTP relay başarısız (App Password deprecation tenant impact veya policy change) ve D43 outage anında dual-receipt için Teams alternative gerekli
2. **Outbound port 587 ISP/firewall block recurrence** — staging-sw veya prod cluster outbound 587 SMTP block; alternative external channel zorunlu
3. **Operator/security tactical decision** — incident visibility için Teams dashboard/Adaptive Card daha hızlı triage sağlar (ops decision)
4. **Compliance/audit requirement** — chat-channel notification audit trail için Teams formal channel zorunlu
5. **Tenant Power Automate DLP/license/quota approval** — preflight gate'leri tamamlanmış + service-account/team-owned flow lifecycle hazır (R27 mitigation prerequisites met)

### D4 — Teams Power Automate workflow asset-preservation pattern

ADR-0024 "Graph mail adapter defer" paralel pattern (D4 referans):

- **Asset olarak korunan**: PR #1053 closed diff (helm-values + ESO + runbook + risk register snippet'leri); Codex thread `019e5ba9` iter-1..iter-5 review history; audit trail GitHub'da accessible
- **Asset olarak yaratılmayan**: Microsoft 365 Power Automate flow (operator tenant tarafında YARATILMAZ; reactivation chain'in 1. adımı flow setup)
- **Reactivation reaction time**: PR #1053 diff template snippet'leri sayesinde reactivation chain saatler içinde tamamlanabilir; aksi halde scratch'ten Teams pivot tasarımı + Codex review chain günleri alır
- Audit trail temizliği: PR #1053 audit kayıt + ADR-0027 + RB-d43-teams-reactivation-chain.md + R27 risk register entry birlikte tam çerçeve

### D5 — Reactivation chain ATOMIC; parçalı aktivasyon **yapılmaz**

Defer state'ten activation'a geçiş yalnız aşağıdaki **6 adım birlikte** owner-approved window'da çalıştırılır (RB-d43-teams-reactivation-chain.md §3). Parçalı aktivasyon (örn. sadece Vault seed + helm-values değişiklik; Power Automate flow setup skip) **YASAK**:

1. **Power Automate**: Service-account veya team-owned flow yarat (incoming HTTP request trigger → JSON schema parse → Adaptive Card post to channel); R27 7-step mitigation chain compliance (DLP/license/quota preflight + flow run-history monitoring + exported package backup); URL captured
2. **Vault**: `kv/platform/alertmanager-fallback.TEAMS_WEBHOOK_URL=<flow URL>` seed (stdin pipe + unset; HARD RULE no-token-log)
3. **ESO**: `externalsecret-alertmanager-fallback.yaml` `TEAMS_WEBHOOK_URL` secretKey add (uncomment template snippet from RB-d43-teams-reactivation-chain.md)
4. **Helm**: `values-prod.yaml` `direct-fallback` receiver `webhook_configs` block add (template snippet); rolling helm upgrade
5. **Smoke**: Synthetic Alertmanager API POST (synthetic NotifyServiceDown alert) → Teams Adaptive Card receipt + Power Automate flow run-history status=Success + run ID + SMTP receipt (3-channel defense-in-depth, NOT scale=0)
6. **Audit**: Evidence doc + risk register R27 status update (⏳ DEFER → 🟢 Mitigated active) + ADR-0027 status note (Decision active)

### D6 — Cross-thread reconciliation note

`019e5b9c` (SMTP-only D43 v1) **canonical**; `019e5ba9`/PR #1053 (Teams pivot) **audit-only superseded**. İki thread'in **merge edilmemesi** (Codex iter-1 verdict: "iki thread merge edilmez"); yeni Codex review thread (`019e5bdb`) tek normalize edilmiş hibrit C kararını review eder.

Provider-different cross-AI peer review compliance (HARD RULE 2026-05-05/14): Bu ADR'ı Codex thread `019e5bdb` (OpenAI) AGREE verdict aldı; Claude (Anthropic) implementer.

---

## Consequences

### Positive

- **Sıfır source-side desired-state operational risk** D43 outage fallback için (SMTP-only canonical source-side; Teams dormant external dependency olmayan path; prod activation hâlâ operator-bound R9/#854)
- **Audit consistency**: iki çelişen thread tek karar normalizasyonu ile çözüldü; ADR-0027 + R27 + RB-d43-teams-reactivation-chain.md tam çerçeve
- **Reactivation speed**: trigger geldiğinde PR #1053 diff template snippet'leri ile saatler içinde aktivasyon (Codex iter-1..iter-5 chain review'i tekrar koşturmaya gerek yok)
- **Pattern consistency**: ADR-0024 (Graph mail) ile aynı "deferred but asset-preserved" pattern; gelecek deferred-but-asset-preserved kararlar için referans

### Negative

- **Audit trail karmaşıklığı**: iki Codex thread + closed PR #1053 + ADR-0027 + R27 = 4 ayrı kayıt yüzeyi; reactivation sırasında operator hepsini koordine eder
- **Reactivation cost**: trigger geldiğinde 6-step atomic chain (Power Automate flow setup + Vault seed + ESO + helm + smoke + audit) ~4-8 saat operator iş yükü
- **Backwards compatibility**: PR #1053'teki helm-values + ESO diff Teams Power Automate v4 webhook payload + url_file pattern üzerine kurulmuş; gelecekte Power Automate API breaking change olursa diff template snippet'leri yeniden tasarlanır

### Neutral

- R23 (Graph mail SMTP single active path) + R27 (Teams Power Automate lifecycle drift) yapısal olarak benzer; ikisi de Microsoft 365 tenant external dependency için "deferred but asset-preserved" pattern uygular
- D43 v1 closure (SMTP-only) Faz 23.2.D **source-side scope** tam tamamlandı; **prod activation operator-bound** (R9 board #854 — Vault seed + helm upgrade + dual-receipt smoke + Operator v0.90.1 `auth_*_file` schema gap fix); production-ready claim için operator chain bekleniyor. Teams aktivasyon trigger gelirse v1.x patch milestone

---

## Alternatives Considered

### Alt-1: Teams Power Automate full activation (PR #1053 merge — Path 2)

- ✅ Codex iter-1..iter-5 review chain AGREE
- ❌ Main'in `019e5b9c` SMTP-only kararı revert gerekir; iki thread arasında "hangisi canonical" belirsiz
- ❌ Power Automate workflow lifecycle ext-dependency aktif olur; R27 active (7-step mitigation gerekli)
- ❌ Operator iş yükü artar (workflow setup + monthly synthetic smoke + tenant DLP review)

**Reddedildi**: Kullanıcı 2026-05-25 kararı hibrit (asset-preserved dormant) tercih etti.

### Alt-2: SMTP-only canonical, Teams audit-only kayıt (no reactivation chain)

- ✅ Minimum operational scope
- ❌ PR #1053 closed diff orphan asset olur; reactivation gerekirse scratch'ten yeniden tasarlanır
- ❌ Pattern consistency yok (ADR-0024 Graph mail "deferred but asset-preserved" ile asymmetric)
- ❌ Trigger geldiğinde reaction time günler-haftalar (audit trail rekonstruksiyonu + Codex review tekrar)

**Reddedildi**: Hibrit C'nin tam değeri reactivation chain'in template + ADR consistency'sinden geliyor.

### Alt-3: Helm/ESO active config'e Teams `webhook_configs` block commented olarak ekle (dormant comment)

- ✅ Reactivation tek uncomment ile
- ❌ Repo zaten Slack DEFER sonrası stale comment/runbook drift taşıyor (Codex iter-1 P1: "ileride 'commented desired state mi, karar mı?' belirsizliği yaratır")
- ❌ Helm template render hatasına yol açabilir (commented block YAML parser tarafından beklenmeyen şekilde işlenebilir)

**Reddedildi**: Codex Q1 Option A verdict — sadece runbook + risk register + ADR; helm/ESO active desired-state'e Teams ekleme.

---

## Validation

### Pre-activation (current state — dormant)

- ✅ `helm-values/values-prod.yaml` `direct-fallback` receiver tek leg (`email_configs` SMTP)
- ✅ `helm-values/values-test-d43-drill.yaml` `direct-fallback` receiver tek leg (`email_configs` Mailpit)
- ✅ ESO `externalsecret-alertmanager-fallback.yaml` 4 key (`SMTP_*` + no `TEAMS_WEBHOOK_URL`)
- ✅ Vault `kv/platform/alertmanager-fallback` 4 key (no `TEAMS_WEBHOOK_URL`)
- ✅ Risk register R9 `🟢 Mitigated (SMTP-only D43 v1)` korunur
- ✅ Risk register R27 `⏳ DEFER asset-preserved` yeni satır

### Post-activation (reactivation chain completed)

- ✅ Power Automate flow live + URL captured + exported package backup
- ✅ Vault `kv/platform/alertmanager-fallback.TEAMS_WEBHOOK_URL` non-empty
- ✅ ESO `externalsecret-alertmanager-fallback.yaml` `TEAMS_WEBHOOK_URL` secretKey added
- ✅ Helm `values-prod.yaml` `direct-fallback` receiver `webhook_configs` block + `email_configs` block (dual leg)
- ✅ Alertmanager pod restart + amtool config verify
- ✅ Synthetic API POST + Teams Adaptive Card receipt + flow run-history status + SMTP receipt + GitHub Issue (3-channel)
- ✅ R27 status `⏳ DEFER` → `🟢 Mitigated active` (7-step mitigation operational evidence)
- ✅ ADR-0027 Decision active note

---

## References

- Codex thread `019e5bdb` (hibrit C strategic AGREE verdict 2026-05-25)
- Codex thread `019e5b9c` (SMTP-only D43 v1 canonical — antecedent canonical)
- Codex thread `019e5ba9` (Teams Power Automate pivot — antecedent audit-only superseded)
- PR #1053 (Teams pivot impl closed superseded — audit reference)
- ADR-0024 "Graph mail adapter defer" — parallel deferred-but-asset-preserved pattern
- RB-d43-teams-reactivation-chain.md — operator atomic activation chain
- Risk register R9 (SMTP-only D43 v1 canonical) + R27 (Teams Power Automate dormant)
- Evidence: `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md` (SMTP-only acceptance, main canonical)
- HARD RULE Pre-Production Full Authority (CLAUDE.md global, 2026-04-29) + Plan Consensus Autonomy (kullanıcı plan onayı gerek olmadığında Codex AGREE → direkt impl)
