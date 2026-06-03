# RB-faz-23-m7-30day-stable-observation

**Faz 23 M8 (Multi-tenant Trigger Gate) PR-1 D — M7 v1 30-day stable observation runbook.**

> Canonical authority: `docs/notify/milestones.md §M8`. This runbook is the
> operator-facing wrapper around the observation harness emitted by
> `notify-m7-stable-recording-rule.yaml` + `notify-m7-stable-alert-rule.yaml`
> + `docs/scripts/m7-stable-evidence.sh`. Codex strategic verdict thread
> `019e8c24` (AGREE order D→B→A→C, multi-PR sequenced).

---

## 1. Bağlam

Faz 23 M8 DoD ilk maddesi: **M7 v1 stable (≥30 day in production)**. M7 v1
closure 2026-05-23 (Web Push browser-only DELIVERED end-to-end +
notification orchestrator + Teams + Slack threading + Tempo + bounce loop
9/9 source-side). Doğal 30-day mark: **2026-06-22+**. Bu runbook 30-gün
penceresinin başarıyla kapanıp kapanmadığını **gözlemleyen** ve evidence
artifact üreten dar bir gözlem ritüelidir.

**Codex 019e8c24 anti-pattern guards (zorunlu):**

- 30-gün penceresi **kısaltılmaz**, geriye dönük yazılmaz.
- M7 "green" denmez, **continuous_30d_ready=true** evidence olmadan.
- Bu observation harness sistem state'i **mutate etmez** — yalnızca okur.
- Absent metric (silent Prometheus / agent silence) **kanıt değildir**;
  evidence script `verdict=OBSERVATION_ABSENT` üretir + exit 3.

## 2. Topoloji

```
notify-dlq-slo-rule.yaml          ← terminal_total + burn_rate kaynak
   │
   ▼
notify-m7-stable-recording-rule.yaml
   │   notify:m7_v1:dispatch_success_rate:30d
   │   notify:m7_v1:dlq_burn_max:30d
   │   notify:m7_v1:dlq_burn_72h_max:30d
   │   notify:m7_v1:critical_alert_minutes:30d
   │   notify:m7_v1:observation_present:30d
   │   notify:m7_v1:stable_30d           ← boolean truth surface
   ▼
notify-m7-stable-alert-rule.yaml
   │   NotifyM7StableObservationRegression  (warning, ticket)
   │   NotifyM7StableObservationWindowReady (info, evidence trigger)
   ▼
docs/scripts/m7-stable-evidence.sh
   │   M7 stable_30d + continuous_30d_ready snapshot → JSON evidence
   ▼
docs/faz-23-evidence/YYYY-MM-DD-m7-v1-30day-stable-evidence.md
```

## 3. Stable_30d=1 koşulları (canonical)

### 3.1 Composite predicate (4 — hepsi aynı anda sağlanmalı)

| Predicate | Threshold | Rule |
|---|---|---|
| `dispatch_success_rate_30d` | ≥ 0.995 | `notify:m7_v1:dispatch_success_rate:30d` |
| `dlq_burn_24h_max_30d` | ≤ 1.0 | `notify:m7_v1:dlq_burn_max:30d` |
| `critical_alert_minutes_30d` | == 0 | `notify:m7_v1:critical_alert_minutes:30d` |
| `observation_coverage_30d` | ≥ 0.95 | `notify:m7_v1:observation_coverage:30d` |

Tüm 4 composite predicate aynı anda sağlanmalı → `stable_30d=1`. Tek bir
predicate fail → `stable_30d=0` ve **30 gün saati efektif resetlenir**.

### 3.2 Supplementary observability (composite'e dahil değil)

| Predicate | Threshold | Rule | Niye supplementary |
|---|---|---|---|
| `dlq_burn_72h_max_30d` | ≤ 1.0 | `notify:m7_v1:dlq_burn_72h_max:30d` | 24h burn yeterli composite kapı; 72h gradual drift için trend gözlemi (runbook investigation context) |

### 3.3 30-day window ready koşulu

M8 DoD blocker #1 = `stable_30d == 1` AND `observation_coverage_30d ≥ 0.95`,
24 saat boyunca hold-down (`for: 24h` alert clause).

> **Codex iter-1 P0/coverage absorb (thread 019e8c24)**: önceki `min_over_time(stable_30d[30d]) == 1` formu
> (a) `stable_30d` zaten 30d-aggregate olduğu için teorik olarak 60d-window semantiği üretiyordu;
> (b) Prometheus retention reset veya yeni rule deploy sonrası az sample varsa false-positive '1' verebiliyordu.
> Yerine **coverage guard** + **stable_30d şu an=1 + 24h hold** üçlüsü canonical kapı.

### 3.4 Cross-rule sample-rate contract

`observation_coverage_30d` formula = `count_over_time(notify:dlq:burn_rate:24h[30d]) / 86400`.

Sabit `86400` = `30 day * 24 h * 60 min * 2 sample/min` (notify-dlq-slo-rule.yaml
recording group `interval: 30s`). Eğer notify-dlq-slo-rule.yaml `interval`
değişirse, **bu denominator da güncellenmelidir**. Cross-rule contract.

## 4. Operatör akışı

### 4.1 Günlük (otomatik) gözlem

- `NotifyM7StableObservationRegression` alarmı tetiklenirse → ticket aç;
  evidence script ile hangi predicate fail oldu rapor + işin kaynağına in.
- `NotifyM7StableObservationWindowReady` info-alarmı tetiklenirse → M8
  DoD blocker #1 karşılandı kanıtı; evidence collect + commit + M8 PR-2'ye
  geç.

### 4.2 Manuel evidence collection

```
./docs/scripts/m7-stable-evidence.sh \
  --context k3d-prod \
  --namespace monitoring \
  --out /tmp/m7-evidence.json
```

Çıktı:
- `evidence: /tmp/m7-evidence.json` (JSON dump, schema_version `m7-v1-30day-stable-evidence/v2`)
- `verdict: <M8_DOD_BLOCKER_MET|UNSTABLE|OBSERVATION_ABSENT>`
- Exit code: 0 / 2 / 3

Verdict yorumu:

| Verdict | Exit | Anlam | Sonraki adım |
|---|---|---|---|
| `M8_DOD_BLOCKER_MET` | 0 | stable_30d=1 AND coverage_30d ≥ 0.95 | Evidence commit + M8 PR-2 (Faz 21 charter draft) tetikle |
| `UNSTABLE` | 2 | predicate fail var (composite başarısız) | Evidence JSON'dan hangi predicate fail oldu tespit + investigate |
| `OBSERVATION_ABSENT` | 3 | Prometheus reachable değil / metric absent / coverage < 0.95 | Observability stack check + coverage düşüklüğünün kaynağını tespit |

> **Codex iter-1 P0/coverage absorb**: önceki `STABLE_BUT_WINDOW_IN_PROGRESS` (exit 1)
> ayrımı kaldırıldı. Coverage guard zaten "yeterli sample yok"u OBSERVATION_ABSENT
> olarak yakaladığı için ayrık bir window-progress state'i gereksiz; aynı zamanda
> önceki `min_over_time(stable_30d[30d])` semantik bug'ı dolaylı eradike edildi.

### 4.3 Evidence artifact commit

Evidence `M8_DOD_BLOCKER_MET` ise → şu konuma kopyala + commit:

```
docs/faz-23-evidence/$(date -u +%Y-%m-%d)-m7-v1-30day-stable-evidence.md
```

Body template:

```markdown
# M7 v1 30-Day Stable Evidence (Faz 23 M8 DoD blocker #1)

Generated: <UTC timestamp>
Context: k3d-prod
Cluster verdict: M8_DOD_BLOCKER_MET

## Predicates

<JSON paste from m7-stable-evidence.sh output>

## Notes

- M7 v1 LIVE date: 2026-05-23 (RB-webpush-activation §3.11)
- Natural 30-day mark: 2026-06-22
- Evidence collection date: <YYYY-MM-DD>
- Continuous_30d_ready: true (min_over_time stable_30d[30d] == 1)

## Codex consult thread

019e8c24 — AGREE order D→B→A→C, M8 PR-1 D scope

## Anti-pattern guards (verified)

- [x] 30-gün penceresi kısaltılmadı
- [x] Geriye dönük backdate yapılmadı
- [x] Mutate-cluster-state yok
- [x] Absent metric = OBSERVATION_ABSENT (kanıt değil)
```

## 5. Failure modes + remediation

### 5.1 `OBSERVATION_ABSENT`

Sebepler:
- Prometheus scrape kesintide
- `kube-prometheus-stack` recording group disabled
- Namespace label drift (platform-prod ≠ scrape target)

Remediation:
- `kubectl -n monitoring get prometheusrule notification-orchestrator-m7-stable-recording -o yaml`
- `curl http://prometheus:9090/api/v1/rules | jq` ile rule loaded confirm
- Notify metrics scrape target reachable mı (`kubectl -n platform-prod get pod -l app=notification-orchestrator` + ServiceMonitor)

### 5.2 `UNSTABLE`

Sebepler (predicate bazlı):
- `success_rate < 0.995` → provider degradation; template lint regression; recipient invalidation storm
- `dlq_burn_24h_max > 1.0` → DLQ flush eden bir incident; Fast/Slow SLO alert paralel yanmalıydı (RB-notify-strict-subscriberid-cutover.md)
- `dlq_burn_72h_max > 1.0` → kademeli provider drift; budget recovery action
- `critical_alert_minutes > 0` → kontrol panelinde NotifyDlqSloBurnRateFast/Slow fire kaydı var; AlertManager ile ilişkilendir + GitHub issue track

Sonraki adım: predicate-specific incident investigation + 30-day clock yeniden başlar; stable_30d tekrar 1 olduktan sonra observation window yeniden açılır.

### 5.3 `STABLE_BUT_WINDOW_IN_PROGRESS`

Beklenen; doğal akış. Bir sonraki haftalık turda tekrar koş.

## 6. Anti-pattern reminders (KALICI)

| Yapma | Sebep |
|---|---|
| Evidence backdate (örn. "biz aslında 2026-05-15'te stable'dık") | Codex 019e8c24 anti-pattern; 30-gün penceresi kısaltılmaz |
| `stable_30d == 0` durumda M7 "green" demek | M7 v1 closure semantik kaybı; M8 blocker döngüsel açıklanmaz |
| Alert `NotifyM7StableObservationRegression` görmeden evidence göndermek | False-positive kabul olur; predicate fail rakipler tespit |
| `OBSERVATION_ABSENT` durumunu "muhtemelen OK" varsaymak | Anti-silence guard YASAK; absent ≠ stable |
| M8 PR-2 başlatmadan stable_30d=1 declare | Codex order D→B→A→C tersine işler; charter draft öncesi sequence ihlali |
| Observation harness'i mutating ops için kullanmak | OBSERVATION-ONLY scope; harness sistem state'i değiştirmez |

## 7. Bağlantı

- Plan: `docs/notify/milestones.md §M8` (canonical DoD)
- Bağımlı: `notify-dlq-slo-rule.yaml` (terminal_total + burn_rate recording rule kaynak)
- Önceki sprintlerde: M7 v1 LIVE 2026-05-23 — RB-webpush-activation §3.11
- Codex thread audit: `019e8c24` (plan-time strategic verdict, M8 readiness sprint order D→B→A→C)
- Sonraki PR'lar: PR-2 (B) Faz 21 charter draft → PR-3 (A) R10 mitigation execution → PR-4 (C) RB wrapper (Codex order).
