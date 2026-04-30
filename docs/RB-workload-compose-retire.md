# Runbook — Workload Compose Retire (post-T+72h)

> Sprint "Prod post-cutover compliance" PR-7.
>
> **Scope**: D30 atomic cutover sonrası eski platform-ssot prod compose
> dosyasının (DEAD CODE artifact) sınıflandırılmış retire prosedürü.
>
> **Bu runbook plan-only**. Canlı silme/archive operasyonu ayrı operator
> aksiyonu (kullanıcı SSH + onay). Bu PR sadece prosedür.

## Bağlam

PR-6 (`docs/prod-compose-inventory-2026-05-01.md`) inventory:
- **Workload residue container**: 0 (same-host atomic cutover ile hiç kullanılmadı)
- **DEAD CODE compose dosyası**: `/home/halil/platform/repo/deploy/docker-compose.prod.yml`
  - Eski platform-ssot prod compose (discovery-server + postgres-db + openfga + 8 backend + frontend)
  - Container yok, referans yok (canlı compose-up komutunda kullanılmıyor)
  - Hâlâ docs/runbook'larda atıf var (RB-vault-kms-autounseal, RB-compose-volume-ssot, RB-server-hardening-checklist)

## Retire kategorileri

| Kategori | Aksiyon | Operator-only? | Bu PR scope |
|---|---|---|---|
| (A) Compose dosya archive | `mv .../deploy/docker-compose.prod.yml .../deploy/docker-compose.prod.yml.archived-2026-05-01` | ✅ Evet (ssh) | Plan-only |
| (B) Docs cross-reference cleanup | `docs/RB-vault-kms-autounseal.md` + `docs/operations/RUNBOOKS/RB-{compose-volume-ssot,server-hardening-checklist}.md` | ❌ Hayır (PR ile) | Listede, follow-up PR |
| (C) Lokal-dev compose dokunulmaz | `/home/halil/platform/repo/backend/docker-compose.yml` lokal-dev only, retire YOK | — | Korunur |
| (D) GHA runner compose dokunulmaz | `gha-runner/docker-compose.yml` aktif, retire YOK | — | Korunur |
| (E) Kaynak repo decommission | platform-ssot repo'nun kendisi (Faz 19 Codex AGREE 019dc0ef) | ✅ Evet (ayrı sprint) | Out of sprint |

## (A) Compose dosya archive — operator runbook

> **Yalnızca kullanıcı yetkisinde**. Agent SSH yetkisi var (CLAUDE.md HARD
> RULE #7) ama bu **arkaeolojik artefakt** kategorisinde — agent'ın direkt
> silmesi yerine kullanıcı onayı + lokal archive tercih edilir.

### Adım 1 — Pre-archive snapshot

```bash
ssh halil@staging-sw 'ls -la /home/halil/platform/repo/deploy/docker-compose.prod.yml; \
  wc -l /home/halil/platform/repo/deploy/docker-compose.prod.yml; \
  md5sum /home/halil/platform/repo/deploy/docker-compose.prod.yml'
```

Çıktıyı doc'a ekle (provenance kanıtı).

### Adım 2 — Archive (rename, NOT delete)

```bash
ssh halil@staging-sw '
  cd /home/halil/platform/repo/deploy/
  cp -p docker-compose.prod.yml docker-compose.prod.yml.archived-2026-05-01
  echo "# RETIRED 2026-05-01 — Sprint Prod post-cutover compliance PR-7" \
    | cat - docker-compose.prod.yml.archived-2026-05-01 \
    > docker-compose.prod.yml.archived-2026-05-01.tmp \
    && mv docker-compose.prod.yml.archived-2026-05-01.tmp \
       docker-compose.prod.yml.archived-2026-05-01
  ls -la docker-compose.prod.yml*
'
```

### Adım 3 — Live verify (compose still works for stateful)

```bash
# Stateful tier hâlâ healthy mi (D6 contract)?
ssh halil@staging-sw 'docker ps --format "{{.Names}}\t{{.Status}}" \
  | grep -E "platform-(pg|kc|vault)-(prod|test)"'

# Hiçbir DEAD compose'a bağlı container var mı?
ssh halil@staging-sw 'docker ps -a --format "{{.Names}}\t{{.Image}}" \
  | grep -E "platform-(api-gateway|auth|user|variant|core|report|schema|permission|frontend|discovery|openfga|nginx-stage)"'
```

Beklenen output: stateful 6 healthy + workload residue 0.

### Adım 4 — Original dosyayı kaldır (operator onayı sonrası)

```bash
ssh halil@staging-sw 'mv /home/halil/platform/repo/deploy/docker-compose.prod.yml \
                       /home/halil/platform/repo/deploy/docker-compose.prod.yml.removed-2026-05-01'
```

Veya tamamen sil (irreversible, archive yedek var):

```bash
ssh halil@staging-sw 'rm /home/halil/platform/repo/deploy/docker-compose.prod.yml'
```

### Adım 5 — Smoke after retire

```bash
# ai.acik.com hâlâ canlı (D29 3-katman)
curl -sk -o /dev/null -w 'frontend=%{http_code}\n' https://ai.acik.com/
curl -sk -o /dev/null -w 'gateway=%{http_code}\n' https://ai.acik.com/api/users/all
curl -sk -o /dev/null -w 'oidc=%{http_code}\n' https://ai.acik.com/realms/master/.well-known/openid-configuration
```

## (B) Docs cross-reference cleanup — follow-up PR

Aşağıdaki dosyalar `deploy/docker-compose.prod.yml` referansı içeriyor:

1. `docs/operations/RUNBOOKS/RB-vault-kms-autounseal.md:48,50` —
   `VAULT_SEAL_FILE` env-driven mount referans. **Aksiyon**: comment ekle
   "DEAD CODE 2026-05-01 sonrası, sadece historical context".
2. `docs/operations/RUNBOOKS/RB-compose-volume-ssot.md:22,155,223` —
   volume sync prosedürü. **Aksiyon**: header'a "RETIRED 2026-05-01" notu.
3. `docs/operations/RUNBOOKS/RB-server-hardening-checklist.md:46,50,210,212,243` —
   port binding 127.0.0.1 prefix referans. **Aksiyon**: D6 stateful only
   olarak revize.
4. `docs/operations/RUNBOOKS/RB-ubuntu-backend-github-vault-deploy.md:173` —
   backend deploy prosedürü. **Aksiyon**: header retire + k8s gitops
   deploy workflow'una yönlendir.

**Bu PR-7 follow-up'ı ayrı PR ile** (PR-7b veya post-sprint).

## (C) Lokal-dev compose — KORUNUR

`/home/halil/platform/repo/backend/docker-compose.yml` lokal Mac/Linux
geliştirici ortamı için. Staging-sw'de aktif çalışmıyor; retire YOK.

## (D) GHA runner compose — AKTİF

`platform-k8s-gitops/gha-runner/docker-compose.yml` — `platform-gha-runner-testai-deploy`
container (self-hosted GitHub Actions runner). Retire YOK.

## (E) Kaynak repo decommission — OUT OF SPRINT

platform-ssot repo'nun KENDİSİ Faz 19 (Codex AGREE 019dc0ef) ile decommission
yolunda. Bu prosedür eski compose dosyasından DAHA GENİŞ scope; ayrı sprint.

## Risk + rollback

**Risk (A archive)**:
- Eğer ileride bir runbook adım adım `docker-compose -f deploy/docker-compose.prod.yml`
  komutu çalıştırırsa, dosya yok → fail. **Mitigasyon**: archive dosya korunur
  (rename, not delete); restore kolay.
- Hardening checklist (RB-server-hardening-checklist.md) port binding referans —
  yalnızca docs, canlı etki yok.

**Rollback (A)**:
```bash
ssh halil@staging-sw 'mv /home/halil/platform/repo/deploy/docker-compose.prod.yml.archived-2026-05-01 \
                       /home/halil/platform/repo/deploy/docker-compose.prod.yml'
```

## NE YAPMA

- ❌ **Stateful compose dosyalarına dokunma** — `platform-pg-prod`, `platform-kc-prod`,
  `platform-vault-prod` D6 KALICI. Bu retire prosedürü ONLARI ETKİLEMEZ.
- ❌ **`gha-runner/docker-compose.yml` retire etme** — aktif runner, deploy
  workflow'lar buna bağımlı.
- ❌ **Direkt `rm` ile silme** (Adım 4 explicit operator onayı isteğine
  kadar). Önce archive (Adım 2), sonra remove (Adım 4).

## Sonraki adımlar

1. Bu PR (PR-7) merge → plan-only retire prosedürü canonical olur.
2. Operator (kullanıcı) Adım 1-3 koşturur, snapshot kanıtını
   `docs/postmortem-2026-05-XX-compose-retire.md` doküman olarak kayıtlar.
3. Adım 4 (gerçek silme/rename) operator onayı sonrası.
4. Follow-up PR-7b: docs cross-reference cleanup (4 dosya).

## Codex önerisi (019de00f)

> "Doğrudan silme bu sprint başında yapılmamalı. Önce inventory, sonra
> sınıflandırma. Sonra canlı apply gerektiren cleanup için ayrı operator/runbook PR."

Bu PR exactly **operator runbook** kapsamı; canlı silme aksiyonu agent SSH
yetkisi olsa da kullanıcı explicit onay bekleniyor (arkeolojik artefakt).

## Referans

- PR-6: `docs/prod-compose-inventory-2026-05-01.md` — inventory + sınıflandırma
- ADR-0002 D6: stateful prod K8s-dışı kalıcı (PG/KC/Vault dokunulmaz)
- Faz 19 Codex AGREE 019dc0ef — kaynak repo decommission scope (out of sprint)
- Codex thread: `019de00f-4b40-75c1-8ead-01b79c5819c1`
