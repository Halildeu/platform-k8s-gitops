# PR-V2.1-Ops-A — Alert Receiver Selection Spike (Decision Record)

> **Belge kodu**: `PR-V2.1-Ops-A-spike`
> **Tarih**: 2026-05-14
> **Sahip**: Halil
> **Sprint**: V2.1 prod-readiness sub-wave
> **Plan-time parent**: `019e2650` (PMD v9.1 AGREE)
> **Spike review thread**: `019e267a` (Codex tur-1 REVISE_BEFORE_MERGE → 6 düzeltme absorb)
> **Status**: AGREE_AFTER_REVISIONS — tur-2 ping bekleniyor

---

## §1. Kapsam

Codex `019e2650` plan-time AGREE'de Ops-A alert receiver için 3-tier tercih sırası (PMD v9.1 §2.4):

| Tier | Path | Şart |
|---|---|---|
| Preferred A | AlertManager **native Slack receiver** | Slack webhook URL Vault'a yazılmış + ESO sync edilmiş + Alertmanager pod mount görüyor |
| Preferred B | OSS GitHub bridge (örn. `m-lab/alertmanager-github-receiver`) | Aktif maintenance + digest pin + non-root hardening + GitHub issue dedupe/close lifecycle + token Vault/ESO |
| Fallback C | GHA scheduled poller | K8s token → GitHub erişim sorunu nedeniyle weak |

Codex tur-2 ek şart (PMD v9.1 §2.4):
> "Uygun OSS receiver doğrulanamazsa P0'da custom receiver yazmak yerine **Slack secret external blocker** olarak raporlanmalı veya **'receiver selection spike'** açılmalı."

Bu doc spike output'u.

---

## §2. Live durum verify (2026-05-14)

### §2.1 Mevcut repo alert surface (Codex tur-1 R3 absorb)

Repo'da iki paralel alert surface zaten var:

| Surface | Konum | Durum | V2.1 Ops-A için tercih |
|---|---|---|---|
| **D43 fallback drill** | `helm-values/kube-prometheus-stack/values-test-d43-drill.yaml` + `kustomize/overlays/test/eso/alertmanager/externalsecret-alertmanager-fallback.yaml` | Test cluster'da LIVE drill window (mock URL `http://drill-slack-mock.local/webhook`) | ✅ **REUSE candidate** (Vault path + ESO pattern) |
| **alertmanager-bridge custom Python service** | `kustomize/base/monitoring/alertmanager-bridge/` + `helm-values/kube-prometheus-stack/values-prod.yaml:71-99` (prod default `alarm-receiver-bridge` webhook) | Prod LIVE | ❌ **Scope dışı V3 backlog** — placeholder/`apk add` pattern + ESO token TODO'ları |

**D43 reuse rationale**:
- Vault path `kv/platform/alertmanager-fallback` zaten mevcut (`SLACK_WEBHOOK_URL` + SMTP keys, 5 anahtar test cluster K8s Secret `alertmanager-fallback-secrets` 4d15h yaşında, `Ready=True`)
- ESO `alertmanager-fallback-secrets` → AlertManager pod mount `/etc/alertmanager/secrets/alertmanager-fallback-secrets/<key>` pattern Codex `019e0dea` iter-2 AGREE
- D43 drill window'da `SLACK_WEBHOOK_URL` mock kullanılıyor (`drill-slack-mock.local`); **gerçek prod Slack URL Vault path'ine yazılırsa** D43 drill kapanışı sonrası baseline AlertManager perf receiver kullanabilir

**alertmanager-bridge custom service exclude**:
- Mevcut prod default `alarm-receiver-bridge` webhook drift detection pipeline'ı; **perf alarmları için kullanılmaz**
- V2.1 P0/P1 scope dışı (Codex tur-2 NARROW: custom receiver yazma YASAK)
- V3 backlog'da explicit kalır

### §2.2 Secret delivery plane (Codex tur-1 R1 absorb)

**Önemli**: GitHub repo secret (`gh secret set SLACK_PERF_WEBHOOK_URL`) **runtime AlertManager secret DEĞİLDİR**.

Doğru kanal:
1. Owner → Vault `kv/platform/alertmanager-fallback` veya yeni `kv/platform/perf-alertmanager` path'ine `SLACK_WEBHOOK_URL` yazar (mevcut path reuse veya isolation kararı §3.1'de)
2. ESO `ExternalSecret` Vault'tan çekip K8s Secret oluşturur
3. AlertManager pod `alertmanagerSpec.secrets[]` ile Secret'i mount eder (`/etc/alertmanager/secrets/<name>/<key>`)
4. AlertManager config `slack_configs.api_url_file: /etc/alertmanager/secrets/<name>/SLACK_WEBHOOK_URL` (env injection DEĞİL, file mount)
5. Synthetic alert tetiklenir → AlertManager pod log "200 OK" Slack receipt → owner Slack workspace'inde mesaj görür

**Runtime kanıt**:
- ESO `SecretSynced=True`
- AlertManager pod env mount path mevcut + file size > 0
- Synthetic alert → AlertManager log
- Owner Slack workspace alarm receipt

### §2.3 OSS GitHub bridge — Adaylar

Live araştırma sonucu:

| Aday | Stars | Son GitHub commit | Son Docker image release | Verdict |
|---|:---:|---|---|---|
| `m-lab/alertmanager-github-receiver` | 49 | 2026-02-16 (3 ay) | **v0.11 / 2023-01-04** (3 yıl) | ❌ Image stale; source aktif ama prod-ready binary yok |
| `galexrt/alertmanager-githubfiles-receiver` | 5 | 2023-03-08 | n/a | ❌ Üç yıl güncelleme yok + low adoption |
| `stephen-soltesz/alertmanager-github-receiver-orig` | 0 | 2017-06-20 | n/a | ❌ Deprecated |
| `prometheus-msteams` | — | aktif | aktif | ❌ Teams hedefli, GitHub değil |
| `karma` | — | aktif | aktif | ❌ Alertmanager UI, issue bridge değil |

**Codex tur-1 R6 absorb**: "kullanılamaz" değil; **prod P0 receiver için unacceptable until digest pin + vuln scan + non-root proof + egress scope + token scope + failure-mode drill**. Image base 3 yıl eski (CVE patch yok); receiver GitHub token taşıyacak; supply-chain + runtime failure yüzeyi alarm receiver için anti-desired.

**Test-only exploratory allowance**: non-prod token + sıkı NetworkPolicy ile test cluster'da deneme YAPılabilir; ama V2.1 closure #4 synthetic proof yerine geçmez.

### §2.4 GHA scheduled poller (Fallback C)

K8s status CM'i okumak için GHA workflow'undan kubectl gerek → kube-config secret + GitHub Actions OIDC → K8s API. Mevcut platform-k8s-gitops repo'da bu pattern KURULU DEĞİL. 1-2 günlük spike + RBAC tasarımı + audit. V2.1 P0 ölçeğinde overhead yüksek; **V3 backlog**.

---

## §3. Decision

### §3.1 Recommended path: **D43 reuse + perf receiver implementation**

Codex tur-1 R2 (D43 reuse rationale) + Codex tur-2 NARROW (custom receiver YASAK) absorb. İki sub-decision owner'a:

**Decision A: Vault path** (owner choice)

- **Option A1**: REUSE `kv/platform/alertmanager-fallback` SLACK_WEBHOOK_URL → D43 drill ve perf-alerts aynı Slack kanalını kullanır
- **Option A2**: ISOLATION `kv/platform/perf-alertmanager` SLACK_WEBHOOK_URL → ayrı kanal (örn. `#perf-alerts` vs `#alerts-d43-drill`)

**Tercih**: A2 (isolation). Gerekçe: drill window aktif iken receiver çakışması; perf alarmları için dedicated kanal team focus. Tek owner action: yeni Vault path yazımı.

**Decision B: Drill window etkileşimi** (Codex tur-2 absorb)

- D43 drill window aktif iken AlertManager config drill values yüklü; baseline'a dönmek için `helm upgrade` drill values olmadan
- V2.1 Ops-A implementation: baseline `values-test.yaml` + `values-prod.yaml`'a perf-alerts receiver eklenir; drill window kapatıldığında perf receiver aktif kalır
- **DİKKAT**: D43 override **full Alertmanager config** taşıyor; Helm values merge'de `receivers`/`routes` array'leri baseline'daki perf receiver'ı **shadow edebilir**. Drill window aktifken perf route ancak `values-test-d43-drill.yaml` da patch edilirse çalışır. Tercih edilen yol: **synthetic Ops-A smoke öncesi drill override'ı kapat** veya impl PR'da drill override'a da perf receiver ekle.

**Implementation contract** (`PR-V2.1-Ops-A-impl` follow-up — **P0**, owner Vault write sonrası):

| Adım | Konum | Codex peer review |
|---|---|---|
| 1 | Owner Vault `kv/platform/perf-alertmanager` SLACK_WEBHOOK_URL yazar | — (owner action) |
| 2 | `kustomize/overlays/{test,prod}/eso/alertmanager/externalsecret-perf-alertmanager.yaml` yeni ESO manifest | impl PR |
| 3 | `helm-values/kube-prometheus-stack/values-{test,prod}.yaml` perf-alerts slack_configs receiver + route matcher (örn. `team=perf` veya `alertname=~"^Perf\|^FederationSmoke"`) + throttle (`group_interval: 5m`, `repeat_interval: 6h`) | impl PR |
| 4 | Synthetic PrometheusRule `perf-alerts-test` deploy (test cluster) → alert tetiklenir → AlertManager log "200 OK" Slack receipt | impl PR + owner Slack workspace verify |
| 5 | Runbook `docs/runbooks/V2.1-perf-alert-receiver.md` (owner + throttle + dedupe key + resolved lifecycle) | impl PR |

### §3.2 Acceptance (Codex tur-1 R4 absorb)

Spike decision record **proposed** in bu PR. Implementation OPEN — owner-action blocked (Vault write) veya impl PR pending.

V2.1 exit criteria #4 (Alert receiver synthetic proof + throttle/dedupe/runbook):
- 🟡 **Spike output committed**; receiver implementation OPEN
- Owner action gereksinim: Vault `kv/platform/perf-alertmanager` SLACK_WEBHOOK_URL yazımı (5-10 dk)
- Post-Vault: agent autonomous PR-V2.1-Ops-A-impl açar

### §3.3 Owner waiver template (Codex tur-1 R5 absorb)

Owner Slack erişimini reddederse veya 1-2 hafta geciktirse, **owner waiver** pattern uygulanır:

```yaml
# V2.1 exit #4 waiver — committed in CODEOWNERS/PMD-v9.1 appendix
# Codex tur-2 R4 absorb: audit-safe field set
waiver:
  item: "V2.1 exit criteria #4 (alert receiver synthetic proof)"
  decision: "approved | declined"                          # owner-explicit
  approved_by: "Halil"                                     # Codex tur-2 absorb
  approved_at: "YYYY-MM-DDTHH:MM:SSZ"                      # Codex tur-2 absorb
  expires_at: "YYYY-MM-DD"                                 # Codex tur-2 absorb (revisit)
  review_trigger: "Faz G cutover-freeze yaklaşımı"         # Codex tur-2 absorb (auto re-evaluate)
  accepted_risk: "Receiver synthetic proof yok; PMD §11 gap A persists; status writer monotonic alarm Slack delivery proof'a düşmez; manuel polling pattern devam"
  deferred_item: "PR-V2.1-Ops-A-impl"
  blocked_downstreams: ["PR-V2.1-Ops-B (status writer monotonic)", "PR-V2.1-B5b3e-Phase3 (Grafana auto-issue)"]
  v3_issue_id: "PERF-ARCH-V3 backlog: alert-receiver"
  faz_g_impact: "Faz G cutover-freeze öncesi pager-backed receiver gereksinim re-evaluate (PMD §10.6 hard gate)"
```

Bu waiver dili "V2.1 #4 geçti" anlamına gelmez; **OPEN-explicit deferred** olarak kayda alınır.

---

## §4. Bu spike'ın V2.1 scope etkisi

| V2.1 Item | Etki |
|---|---|
| **PR-V2.1-Ops-A** (alert receiver) | Implementation OPEN; **A2 isolation path identified** (D43 reuse seçeneği ek SMTP key risk); owner Vault write bekleniyor |
| **PR-V2.1-Ops-B** (status writer monotonic alert) | **Conditional on Ops-A unblock** — PrometheusRule üretilebilir ama **Slack delivery proof / receiver-backed acceptance üretemez** (Codex tur-2 R5 absorb) |
| **PR-V2.1-B5b3e-Phase3** (Grafana panel + auto-issue) | **Conditional on Ops-A unblock** — Grafana panel bağımsız üretilebilir ama auto-issue receiver-backed |
| V2.1 closure 9-madde #4 | OPEN (owner-action blocked); waiver pattern §3.3 hazır |

**Non-dependent V2.1 work may continue under owner-blocked exception**:
- PR-V2.1-M2a0/M2a1/M2a2 (auth measurement)
- PR-V2.1-B3b1 (Brotli)
- PR-V2.1-B3d0/B3d1/B3d2 (CSS critical)
- PR-V2.1-G2 (sliding baseline)
- PR-V2.1-ABM-1 (4-canary soak)
- PR-V2.1-GOV-1 (branch protection + cross-AI audit)

---

## §5. Onay

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Owner | Halil | 2026-05-14 | ☐ (Vault path write pending) |
| AI Consensus | Claude (spike) + Codex tur-1 REVISE_BEFORE_MERGE → tur-2 AGREE pending | 2026-05-14 | ⏳ |

---

## §6. Owner action checklist (Codex tur-1 R1 + R5 absorb)

Owner Vault'a `SLACK_PERF_WEBHOOK_URL` yazmak için (Vault root token kullanıcının kontrolünde):

```bash
# 1. Slack workspace → Apps → Incoming Webhooks → Add
#    Channel: #perf-alerts (veya tercih)
#    Webhook URL kopyala
#    Format: https://hooks.slack.com/services/T0000/B0000/XXXXXX

# 2. Slack webhook test (local proof — owner action; secret hijab)
read -r -s SLACK_WEBHOOK_URL                              # echo görünmez
printf 'URL prefix check: %s\n' "${SLACK_WEBHOOK_URL:0:30}"  # prefix bekleniyor: https://hooks.slack.com/services/
[[ "$SLACK_WEBHOOK_URL" =~ ^https://hooks\.slack\.com/services/ ]] && echo "OK prefix" || echo "FAIL prefix"
curl -X POST -H 'Content-Type: application/json' \
  -d '{"text":"V2.1 Ops-A handshake test"}' \
  "$SLACK_WEBHOOK_URL"
#    Expected: Slack channel'da "V2.1 Ops-A handshake test" mesajı

# 3. Vault'a yaz — A2 isolation path
#    HEDEF VAULT CONTEXT açık yaz:
#    Test cluster Vault:  VAULT_ADDR=https://vault-test.platform.local  (veya docker exec platform-vault-test)
#    Prod cluster Vault:  VAULT_ADDR=https://vault-prod.platform.local  (veya docker exec platform-vault-prod)
#
#    A2 (isolation) — RECOMMENDED — yeni path, çakışma yok:
VAULT_ADDR=https://vault-test.platform.local vault kv put kv/platform/perf-alertmanager \
  SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL"
VAULT_ADDR=https://vault-prod.platform.local vault kv put kv/platform/perf-alertmanager \
  SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL"
#
#    A1 (reuse) — DİKKAT: `kv put` SMTP keys'i EZER — `kv patch` zorunlu:
# VAULT_ADDR=https://vault-test.platform.local vault kv patch kv/platform/alertmanager-fallback \
#   SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL"

# 4. Owner local cleanup (terminal session sonu)
unset SLACK_WEBHOOK_URL

# 5. ESO sync proof (agent autonomous post-Vault):
kubectl --context k3d-test -n monitoring get externalsecret perf-alertmanager-secrets \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# Expected: True

# 6. AlertManager pod mount kanıt:
kubectl --context k3d-test -n monitoring exec alertmanager-... -- \
  ls -la /etc/alertmanager/secrets/perf-alertmanager-secrets/
# Expected: SLACK_WEBHOOK_URL file present, size > 0

# 7. Synthetic alert deploy (agent autonomous):
#    PrometheusRule perf-alerts-test → AlertManager log "200 OK" Slack receipt
```

**Secret hijab** (Codex tur-2 R3 absorb):
- Inline `echo "https://hooks..."` YASAK (terminal history'ye düşer)
- `read -r -s` + variable interpolation tercih
- Secret value loglanmaz
- Owner local test sonrası `unset SLACK_WEBHOOK_URL`

**Secret existence proof — real Slack prefix guard** (mevcudiyet + format kanıt, value değil):
```bash
# Vault path mevcudiyet kontrolü + Slack URL prefix kanıtı (mock URL guard)
vault kv get -field=SLACK_WEBHOOK_URL kv/platform/perf-alertmanager | \
  python3 -c "import sys; v=sys.stdin.read().strip(); print('OK' if v.startswith('https://hooks.slack.com/services/') else 'FAIL: not a real Slack webhook URL')"
# Expected: OK
# NOT: Mevcut D43 drill `kv/platform/alertmanager-fallback` SLACK_WEBHOOK_URL 37c — büyük ihtimalle mock URL
# (drill-slack-mock.local); gerçek Slack receipt kanıtı için **prefix + Slack 200 OK proof** gerekli.
```

---

## §7. Codex tur-1 6 revision absorb mapping

| Revision | Section | Status |
|---|---|---|
| R1 Secret plane düzeltmesi | §2.2 (Vault/ESO runtime contract) + §6 (Vault write, not GitHub secret) | ✅ |
| R2 D43 reuse rationale | §2.1 (reuse candidate) + §3.1 Option A1/A2 owner decision | ✅ |
| R3 alertmanager-bridge explicit exclude | §2.1 (custom Python scope dışı V3) | ✅ |
| R4 Acceptance wording softening | §3.2 ("proposed", "OPEN" — "DEFER edildi" değil) | ✅ |
| R5 Waiver template | §3.3 (mini template + Faz G impact field) | ✅ |
| R6 m-lab hükmü keskinleştirme | §2.3 ("unacceptable until proof", test-only allowance) | ✅ |

---

## §8. Open question — owner decision

§3.1 Option A1 (REUSE `kv/platform/alertmanager-fallback`) **veya** A2 (ISOLATION `kv/platform/perf-alertmanager`)?

**Recommendation**: A2 (isolation) — drill window receiver çakışmasını önler + perf-alerts team focus.

Owner onay verirse → agent PR-V2.1-Ops-A-impl açar (Vault write sonrası).

---

🤖 Generated by Claude (Anthropic). Codex tur-1 REVISE_BEFORE_MERGE 6 revision absorb edildi (thread `019e267a`). Cross-AI tur-2 AGREE bekleniyor.
