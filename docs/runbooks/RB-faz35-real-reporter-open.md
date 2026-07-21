# RB-faz35 — Real reporter open (ES-313 go-live procedure)

> **Scope:** Faz 35 Etik Speak servisini **staff-only test cell**'ten **gerçek başvuran açılışı** ile prod cell'e taşıma. Bu prosedür yalnız **ES-311 7-imza pack**'in tam olduğu + **ES-312 controlled production pilot release gate**'inin tetiklendiği durumda uygulanır. Sektör-standardı: **EU 2019/1937 Art.9 internal reporting channels**, **ISO 37002:2021 §8.2 process for receiving reports**, **KVKK Md.10 aydınlatma yükümlülüğü**.

## Ön koşullar (all-must-pass)

Aşağıdaki checklist tam olmadan **açılış yapma**:

### Teknik gate (agent-verified)

- [ ] **ES-303**: Reveal API implemented + WORM attribution + integration test yeşil.
- [ ] **ES-306**: Rate-limit + input sanitization backend fix merged + verify.
- [ ] **ES-309**: Prod backup pipeline canlı + rehearsal başarılı + RPO/RTO belgelenmiş.
- [ ] **ES-310**: Prod overlay `kustomize/overlays/prod/activation/etik-speak/` merged + argo sync + smoke.
- [ ] `platform-prod/etik-speak` — 3/3 pod Running (Up + Functional + Zanzibar-ready) staff-only.
- [ ] Prod SLO monitor (Grafana) + Alertmanager route (PagerDuty) canlı.
- [ ] Prod backup drill (72 saat önce) başarılı + evidence artifact.
- [ ] Kill-switch drill executed (rollback verified within 5 dk).

### İmza gate (ES-311 owner-signed)

- [ ] Legal counsel — KVKK/GDPR/EU 2019/1937 compliance sign-off (doc ref + tarih).
- [ ] Privacy officer / DPO — PIA + anonymity threat model sign-off.
- [ ] Secret owner / Security lead — prod Vault + key custody + Reveal ceremony sign-off.
- [ ] Compliance officer — ISO 27002/37002 retention/legal-hold sign-off.
- [ ] Business owner — public communication + risk acceptance + go-live authorization.
- [ ] **Reveal Officer** atama (isim + KC user + ceremony contract).
- [ ] Emergency contact list (7/24 escalation + on-call rotation).

### Comms + legal gate

- [ ] `ai.acik.com/privacy` sayfası yayında + tr-TR aydınlatma metni (KVKK Md.10).
- [ ] `ai.acik.com/legal` sayfası yayında + whistleblower protection statement (EU 2019/1937).
- [ ] Employee onboarding materyalleri güncellendi (whistleblower hotline redirect: existing → Etik Speak).
- [ ] HR + Legal takım briefing tamamlandı.
- [ ] Union / employee representative bilgilendirme (yasal zorunlu ise).

## Aktivasyon adımları

### Faz 1 — staff-only prod pilot (T-0 → T+24h shadow)

1. **T-0**: Prod overlay merge + argo sync. `platform-prod/etik-speak` canlı, ancak **Basic Auth-gated** (test cell pattern gibi). Yalnız staff + owner test personaları erişebilir.
2. **T-0 + 1h**: Owner + Reveal Officer + on-call — 5-adım smoke prod'da (`ai.acik.com`), sentetik veri ile.
3. **T-0 + 4h**: SLO dashboard + Alertmanager idle → sağlıklı baseline.
4. **T-0 + 24h**: Shadow monitor completed, herhangi bir SEV1/SEV2 alert yok. Post-shadow review meeting.

### Faz 2 — gerçek başvuran açılışı (T+24h)

1. **T+24h**: Owner + Reveal Officer + Legal — go-live meeting (recording + minutes).
2. **Karar imza**: Business owner "go-live authorized" (dijital imza + zaman damgası + Reveal Officer contra-sign).
3. **Basic Auth kaldırma**:
   ```bash
   # kustomize/overlays/prod/activation/etik-speak/ingress-public-{api,ui}.yaml
   # nginx.ingress.kubernetes.io/auth-* annotations kaldır
   ```
4. Fresh PR + owner review + merge + argo sync + reconcile.
5. **T-live**: Real reporter open. `ai.acik.com/` erişilebilir + form doldurulabilir + receipt üretilir.
6. **T-live + 1h**: Owner monitör — real report gelirse:
   - Reveal Officer + Secret Owner + Legal shadow (ilk reporting cycle).
   - Staff response cycle verify.
   - Reporter mailbox follow-up verify.

### Faz 3 — public communication (T+48h)

1. Legal team → external announcement:
   - Kurumsal web sitesi press release.
   - Employee newsletter.
   - Contract vendor / supplier bildirimi.
2. Alternatif kanal (yedek e-posta + telefon) — Etik Speak birincil, geri kalan fallback.

## Metric — go-live sağlığı

Aşağıdaki metric'ler ilk **hafta boyunca günlük** raporlanır:

- Report intake rate (target: baseline expected)
- Report modality dağılımı (ANONYMOUS / CONFIDENTIAL / NAMED)
- Report category dağılımı
- Staff response time (median + p95)
- Reporter follow-up rate (mailbox re-login)
- Case closure time (NEW → CLOSED)
- Basic-auth 401 rate (public gate kaldırıldı → sıfır olmalı)
- SLO error budget consumption
- Alert incidence (SEV1/SEV2)

## Rollback (go-live sonrası kritik olay)

Kritik olay → `RB-faz35-emergency-kill-switch.md` uygula.

Yasal reveal talep → `RB-faz35-legal-reveal-request.md` uygula.

## Kayıt

Aktivasyon sonrası:

- Board issue **ES-313** Status → **Done**.
- Board issue **ES-312** Status → **Done**.
- Evidence artifact: `docs/faz-35-evidence/YYYY-MM-DD-real-reporter-open.md`.
- All approval signatures + timestamps + doc refs archived: `docs/faz-35-evidence/approvals/`.

## Referanslar

- `RB-faz35-incident-response.md`
- `RB-faz35-emergency-kill-switch.md`
- `RB-faz35-legal-reveal-request.md`
- `docs/legal/faz35-privacy-notice-tr.md`
- `docs/legal/faz35-retention-policy.md`
- Board: [Project #8](https://github.com/users/Halildeu/projects/8) — ES-311, ES-312, ES-313
