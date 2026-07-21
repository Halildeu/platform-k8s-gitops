# RB-faz35 — Etik Speak incident response

> **Scope:** Faz 35 Etik Speak whistleblowing servisinin (public reporter + staff manager + backend) canlı ortamda oluşan olaylara yanıt. Test cell (`platform-test/etik-speak`) + prod cell (`platform-prod/etik-speak`) her ikisi de kapsam. Sektör-standardı: **ISO 27002:2022 §5.24 information security incident management**, **EU 2019/1937 Art.11 protection of whistleblowers**, **ISO 37002:2021 §9.1 monitoring**.

## Severity map (Alertmanager `severity` label)

| Severity | Anlam | Response time (SLA) | Kanal |
|---|---|---|---|
| **SEV1** | Whistleblower kanalı erişilemez veya veri bütünlüğü riski | 15 dk (7/24) | PagerDuty page + on-call SMS + kill-switch runbook link |
| **SEV2** | Staff/reporter deneyimi bozuk; kanal ayakta | 1 saat (iş saati) / 4 saat (mesai dışı) | Slack/Teams ticket + business-hours escalation |
| **SEV3** | Trend/gözlem; insan aksiyonu gerekmez | best-effort | Alert log summary weekly |

## Alert → aksiyon map

### SEV1

#### `EtikSpeakEthicsServiceDown`
1. On-call yanıt (max 15 dk): PagerDuty ack + Slack `#faz35-incidents` bildirim.
2. `kubectl --context <cluster> -n <ns> get pod -l app.kubernetes.io/name=ethics-service` — pod state?
   - `ImagePullBackOff` → GHCR registry veya image digest bulunamıyor; overlay digest revert.
   - `CrashLoopBackOff` → `kubectl logs --previous`; startup fail (DB, Vault, KC, OpenFGA dep).
   - `Pending` → resource quota, node capacity, PriorityClass.
3. Dep availability check: postgres + vault + keycloak + openfga hepsi Ready mi?
4. Recovery başarısız > 30dk → `RB-faz35-emergency-kill-switch.md` uygula.
5. Post-mortem: 72 saat içinde blameless post-mortem draft.

#### `EtikSpeakOpenFgaDown`
1. On-call ack + Slack `#faz35-incidents`.
2. OpenFGA StatefulSet + PVC durumu.
3. Recovery > 30dk → kill-switch (staff hiçbir case'e erişemez).
4. Reporter mailbox (read-only public path) OpenFGA-dependent değildir; reporter tarafı çalışır, staff response ertelenir.

#### `EtikSpeakIntakeErrorBudgetBurn`
1. On-call ack, immediate diagnosis.
2. Grafana `Etik Speak SLO` dashboard → 5xx breakdown (spesifik endpoint).
3. Backend log (`kubectl logs -l app.kubernetes.io/name=ethics-service --tail=200`) — exception pattern.
4. Bilinen exception:
   - `HikariPool exhaustion` → PG connection pool + PG server yükü.
   - `Vault permission denied` → AppRole cert/policy drift; `provision-test-pg-vault.sh` re-run.
   - `OpenFGA client error` → OpenFGA schema veya store-id yanlış eşleşme.
5. Rollback: son merge edilmiş ethics-service digest'i kontrol et; gerekirse önceki digest'e geri sar (`kubectl set image` YASAK — gitops digest bump PR + argo sync).

### SEV2

#### `EtikSpeakIntakeLatencyP95High` / `EtikSpeakStaffCaseListLatencyP95High`
1. Ticket aç, iş-saati response.
2. Grafana latency panel → hangi dep (PG, Vault, OpenFGA) darboğazı?
3. Circuit-breaker + backpressure metriklerini incele.
4. Aylık capacity review sırasında iyileştirme planla.

#### `EtikSpeakMailboxSessionFailRate`
1. Access-secret geçersizliği legitimate olabilir; brute-force sinyali de.
2. Cross-check: `EtikSpeakBasicAuthFailBurst` aynı zaman diliminde tetiklendi mi?
3. Evet ise: `etik-speak-public-gate` secret rotate + `RB-faz35-emergency-kill-switch.md` sadece **public gate** temporary tighten (rate-limit sıkılaştır, basic-auth password rotate).

#### `EtikSpeakBasicAuthFailBurst` / `EtikSpeakStaffAuthFailBurst`
1. Kaynak IP analizi (ingress-nginx access log; IP hash ile scan pattern tespit).
2. Kısa-vadeli: `nginx.ingress.kubernetes.io/whitelist-source-range` annotation (test cell'de) veya WAF rule (prod'da).
3. Uzun-vadeli: rate-limit tuning + CAPTCHA gate (ES-3 backend PR).
4. Persona compromise ise: KC user disable + Reveal officer'a bildir.

#### `EtikSpeakAuditOutboxBacklog`
1. WORM sink outage — downstream (S3-Object-Lock, DSSE signer, remote audit collector) sağlığı.
2. Backlog > 1 saat → **legal-obligation risk**; yasal audit korumasında gecikme.
3. Sink recovery + backlog drain rate.

### SEV3

#### `EtikSpeakRateLimitTrigger`
1. Legitimate surge ise: rate-limit artır (weekly review).
2. Abuse ise: source-IP block (WAF) + `EtikSpeakBasicAuthFailBurst` cross-check.

## Post-incident (72 saat içinde)

1. **Blameless post-mortem** doldur: `docs/postmortems/faz35-YYYY-MM-DD-<slug>.md`
2. Timeline + impact (case sayısı, reporter etkilenmesi, staff etkilenmesi, RTO/RPO breach).
3. Root cause (5 whys).
4. Action items (jira/board issue + owner + deadline).
5. Compliance sonucu: legal reveal veya notification gerekiyorsa `RB-faz35-legal-reveal-request.md` bağla.
6. Governance drift kaydı: ADR-0011 §2.3 boundary declaration + post-mortem doc reference.

## Referanslar

- Alertmanager rules: `kustomize/base/apps/etik-speak/monitoring/prometheusrule.yaml`
- Kill-switch: `docs/runbooks/RB-faz35-emergency-kill-switch.md`
- Legal reveal: `docs/runbooks/RB-faz35-legal-reveal-request.md`
- Real reporter open (post-incident re-open): `docs/runbooks/RB-faz35-real-reporter-open.md`
- Evidence log: `docs/faz-35-evidence/`
- Board issue Ana Sayfa: [Project #8](https://github.com/users/Halildeu/projects/8)
