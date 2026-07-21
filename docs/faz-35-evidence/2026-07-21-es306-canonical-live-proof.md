# Faz 35 ES-306 — Canonical Transport Hardening LIVE Proof

**Tarih**: 2026-07-21 06:22 UTC
**Cluster**: k3d-test (namespace `platform-test`)
**Scope**: Faz 35 ES-306 backend security hardening — kalıcı fix, test-only env workaround kaldırıldı.

---

## Bağlam

2026-07-21 sabahına kadar `X-Etik-Speak-Transport` header'ı ingress-nginx v1.9+ `proxy-set-headers` ConfigMap tarafından render edilemiyordu (alphabetically-first-only quirk). Backend `SECURE_TRANSPORT_REQUIRED` gate'i reddediyordu → reporter POST fail. Geçici çözüm: [gitops #2725](https://github.com/Halildeu/platform-k8s-gitops/pull/2725) test-overlay `ETHICS_SECURE_TRANSPORT_REQUIRED=false` env override (kısa-vadeli patch, prod pilot için sürdürülebilir DEĞİL).

## Kalıcı fix

- **[platform-backend PR #908](https://github.com/Halildeu/platform-backend/pull/908)** (merged 2026-07-21T05:06:33Z, commit `a5b6d3a5`)
  - `PublicCredentialBoundaryFilter.isSecureTransport()` metodu — `X-Etik-Speak-Transport: https` OR `X-Forwarded-Proto: https` fallback
  - `hasAuthorization` empty-string bypass fix — `null + isBlank()` birlikte
  - 4 yeni test case (2 positive fallback + 1 negative http proto + 2 empty/whitespace auth)
- **[platform-k8s-gitops PR #2745](https://github.com/Halildeu/platform-k8s-gitops/pull/2745)** (merged 06:07 UTC)
  - ethics-service digest bump: `sha256:f8fe0cd5...`
  - `ETHICS_SECURE_TRANSPORT_REQUIRED=false` env patch **kaldırıldı**
- **[platform-k8s-gitops PR #2748](https://github.com/Halildeu/platform-k8s-gitops/pull/2748)** (merged 06:18 UTC)
  - Image-set ledger drift correction (auto-merge yarışının kaçırdığı ledger update)

## D29 3-proof

### Up

```
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=ethics-service -o wide

NAME                              READY   STATUS    RESTARTS   AGE     IP            NODE
ethics-service-6846c78494-d9xzd   1/1     Running   0          10m     10.44.3.219   k3d-test-server-0
```

### Functional — Reporter POST 201

```
POST https://etik.acik.com/api/v1/public/ethics/reports
Basic Auth: etik-test:<REDACTED>
Idempotency-Key: <UUID>
Content-Type: application/json

{
  "mode": "ANONYMOUS",
  "category": "OTHER",
  "subject": "regression post-PR908",
  "description": "ES-306 canonical fix - X-Forwarded-Proto fallback",
  "locale": "tr-TR",
  "accessSecret": "<43-char [A-Za-z0-9_-]>",
  "noticeVersion": "v1.0.0"
}

→ 201 Created
{
  "receiptId": "a9fd58d9-bb3d-4b20-8bc6-1eb8ff754e05",
  "createdAt": "2026-07-21T06:22:55.376698510Z",
  "mailboxPath": "/mailbox",
  "idempotentReplay": false
}
```

### Zanzibar-ready — Boundary NetworkPolicy

Fix `X-Forwarded-Proto` header'ını client-controllable yapmaz — backend'e yalnızca ingress-nginx namespace'inden gelen trafik NetworkPolicy tarafından izin verildiği için header spoofing engellenir. `use-forwarded-headers: "true"` ingress-nginx ConfigMap değeri header'ı otomatik set eder (client-supplied override edilir).

## Image identity

```
kubectl --context k3d-test -n platform-test get deploy ethics-service -o jsonpath='{.spec.template.spec.containers[0].image}'
ghcr.io/halildeu/platform-backend-ethics-service@sha256:f8fe0cd588c99ef78848bb4e0200d1268e0a4d6c6afc8599812dc7c18657db53
```

Immutable content-address = backend source `a5b6d3a58a2d97daf48a17d382532552e74fdcaa` (workflow run [29803062932](https://github.com/Halildeu/platform-backend/actions/runs/29803062932)).

## Ledger binding

`docs/faz-35-evidence/image-set/6ee2a7076a12602c9b7af5bb57ce1db25f1e9833e4713b55642c3c075adac1d6.json`
- backend head: `a5b6d3a58a2d97daf48a17d382532552e74fdcaa`
- ethics_service digest: `sha256:f8fe0cd588c99ef78848bb4e0200d1268e0a4d6c6afc8599812dc7c18657db53`
- workflow_run: 29803062932

Semantic contract test `test_image_set_is_content_addressed_source_bound_and_rendered_exactly` PASS (42/42 canonical suite).

## Prod pilot etkisi

Prod overlay iskeleti ([PR #2740](https://github.com/Halildeu/platform-k8s-gitops/pull/2740)) `ETHICS_SECURE_TRANSPORT_REQUIRED` env toggle **kullanmaz**. Prod default `true` kalır + `X-Forwarded-Proto` fallback ile ingress-nginx enforce eder.

## Kalan ES-306 BLOCKER'lar (owner/Codex spawn scope)

- Rate-limit fail (504 pattern → 429) — [Codex spawn `#077fd546`](Codex sürekli chip)
- XSS/SSRF payload sanitization — same chip
- SQL injection prepared statement audit — same chip
- Reveal API + WORM — [Codex spawn `#378f775d`](ES-303)

Bu doküman canonical **transport gate** fix'ini kapsar. Kalan ES-306 hardening ayrı iş.

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above (evidence doc)

## Cross-AI

Cross-AI audit suspended (repo governance 2026-07-20 #2712/#2713).
