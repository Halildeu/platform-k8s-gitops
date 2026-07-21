# RB-faz35 — Emergency kill-switch (panic-off procedure)

> **Scope:** Faz 35 Etik Speak servisinin kritik güvenlik/veri-bütünlüğü olayı sırasında **immediate takedown**. Bu prosedür 24/7 herhangi bir on-call sorumlusu tarafından **owner onayı beklemeden** tetiklenebilir; post-hoc olay analizi + reactivation kararı ES-311 imzacılarına gider. Sektör-standardı: **NIST SP 800-61r2 §3.3.4 containment**, **EU 2019/1937 Art.16 disciplinary action prevention through channel integrity**.

## Ne zaman tetiklenir

- Veri sızıntısı sinyali (basic-auth brute-force başarısı + WORM audit tampering şüphesi)
- Reporter kimlik gizliliği tehlikeye girmiş (SSO/OAuth token misconfig, log leak)
- OpenFGA policy drift + explicit-allow'suz staff erişimi
- SEV1 alert 30 dakika içinde çözülemedi + incident-response `RB-faz35-incident-response.md` bunu direktifleştirdi
- Legal talep: yargı kararı ile servisin geçici durdurulması

## Ne yapar

**Test cluster** (`platform-test/etik-speak`) veya **prod cluster** (`platform-prod/etik-speak`) için:

```bash
# Kill-switch YAML overlay (fail-closed rollback):
# kustomize/overlays/<env>/deactivation/etik-speak/kustomization.yaml
# içeriği: 3 Deployment (ethics-service + etik-speak-manager + etik-speak-public)
# replicas=0, public ingress removed, prune=false safe (ArgoCD kaynak sahipliği
# korunur; sonraki reactivation için delete yapmadan geri döndürülebilir).
```

## Aktivasyon adımları

### 1. On-call decision + notification

```
# On-call takım: `#faz35-incidents` Slack + `on-call-oncalls` PagerDuty
# Karar bildirimi (owner post-hoc):
# "Etik Speak <env> kill-switch aktivasyonu: <SEV1-alert-id> + <ne bulundu>"
```

### 2. ArgoCD Application source path override (test)

```bash
ssh staging-sw
kubectl --context k3d-prod -n argocd patch app platform-test --type=merge -p '{
  "spec": {
    "source": {
      "path": "kustomize/overlays/test/deactivation/etik-speak"
    }
  }
}'
```

**Prod için** — bu prosedürün **ES-3 pilot sonrası, prod overlay+deactivation deploy edilmiş olduğu durumda**:

```bash
kubectl --context k3d-prod -n argocd patch app platform-prod --type=merge -p '{
  "spec": {
    "source": {
      "path": "kustomize/overlays/prod/deactivation/etik-speak"
    }
  }
}'
```

> ⚠️ **Not:** Bu ArgoCD Application source patch'i ArgoCD selfHeal döngüsünde **geri alınmaz** (source spec değişikliği hard override). Sync + reconcile başlar.

### 3. ArgoCD sync

```bash
kubectl --context k3d-prod -n argocd patch app platform-<env> --type=merge -p '{
  "operation": {
    "sync": {},
    "initiatedBy": {"username": "on-call-halil"}
  }
}'
```

### 4. Doğrulama

```bash
# Deployment scale-to-zero
kubectl --context k3d-<env> -n platform-<env> get pod -l app.kubernetes.io/part-of=etik-speak
# → No resources found (veya Terminating)

# Public reporter erişilebilirlik
curl -sSI --resolve etik.acik.com:443:<edge-ip> https://etik.acik.com/
# → HTTP 502 / 503 / 504 (backend yok)

# Staff manager erişilebilirlik
curl -sSI --resolve testai.acik.com:443:<edge-ip> https://testai.acik.com/ethic/
# → HTTP 502 / 503 / 504
```

### 5. Public communication

- `#faz35-incidents` Slack:
  > "Etik Speak servisi geçici olarak kapatıldı. Güvenlik olayı incelemesi
  > devam ediyor. Reactivation kararı ES-311 imzacıları tarafından verilecek.
  > Alternatif whistleblowing kanalı: [yedek e-posta / telefon]."
- `ai.acik.com/status` sayfası (production) — servis durumu güncellendi.
- Employee onboarding materyalleri (temporary redirect) — HR + Legal ile koordineli.

## Reactivation (post-incident)

Kill-switch'ten çıkış **ES-311 imzacılarının onayına** bağlıdır. Adımlar:

1. Root cause analysis + post-mortem (`docs/postmortems/faz35-YYYY-MM-DD-<slug>.md`).
2. Fix PR (kod / manifest / config) — cross-AI review (Codex + Claude review).
3. Reactivation kararı — `ES-311` 7-imza pack (legal + privacy + secret-owner + compliance + business + Reveal Officer + on-call).
4. `RB-faz35-real-reporter-open.md` prosedürü izle.
5. ArgoCD Application source path'i tekrar `activation/etik-speak`'e set et.
6. Reconciliation + smoke.

## Post-mortem template referansı

`docs/postmortems/faz35-YYYY-MM-DD-<slug>.md` içeriği:

```markdown
# Faz 35 Etik Speak — Post-mortem (YYYY-MM-DD)
## Severity: SEV1
## Duration: <start> — <end> (Xh Ym)
## Impact: (case sayısı, reporter etkileşimi, staff etkileşimi)
## Timeline:
- HH:MM — alert tetiklendi
- HH:MM — on-call ack
- HH:MM — root cause bulundu
- HH:MM — mitigation (kill-switch aktivasyonu)
- HH:MM — reactivation
## Root cause: (5 whys)
## Contributing factors:
## Action items:
- [ ] <owner> — <deadline> — <description>
## Lessons learned:
## Runbook updates: (bu runbook + related)
## ES-311 imzacı bildirimleri: (kim ne zaman bilgi aldı)
```

## Referanslar

- `RB-faz35-incident-response.md` — SEV1 → kill-switch escalation trigger
- `RB-faz35-real-reporter-open.md` — reactivation prosedürü
- `RB-faz35-legal-reveal-request.md` — legal talep sonrası kill-switch
- `kustomize/overlays/<env>/deactivation/etik-speak/kustomization.yaml`
- Board: [Project #8 ES-310](https://github.com/users/Halildeu/projects/8)
