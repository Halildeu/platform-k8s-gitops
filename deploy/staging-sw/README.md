# deploy/staging-sw/ — Host-Side Deploy Contract (staging-sw)

Bu dizin `staging-sw` sunucusunda **host-katmanı** çalışan script'lerin
source-of-truth'udur (kustomize/ArgoCD kapsamı DIŞI iş: cron @reboot vault
unseal, host-level bootstrap, vs.).

> Kapsam ayrımı:
> - `scripts/deploy/` (CI/gate yardımcı) ≠ `deploy/staging-sw/` (host runtime)
> - `bootstrap/` (k3d cluster provisioning + backup cron) ayrı bir alan;
>   staging-sw'ye özgü host-side script'ler burada.

## Dosyalar

| Dosya | Rol |
|---|---|
| [`vault-auto-unseal.sh`](./vault-auto-unseal.sh) | Vault (test + prod) auto-unseal, share-count preflight'lı |
| [`meeting-ai-private-gateway/`](./meeting-ai-private-gateway/) | Faz 24 GPU -> staging WireGuard + application-mTLS Caddy edge, exact firewall, rotation units |

## Deploy Chain (steady-state, initial apply sonrası)

**Host clone** (staging-sw'de zaten mevcut, bootstrap `cron` iş yükleri buradan
çalışıyor):

```
/home/halil/platform-k8s-gitops/   ← ana clone
```

**Runtime path** (cron ve manuel invoker'lar buraya bakar — initial apply
sonrasında symlink):

```
/home/halil/platform/scripts/vault-auto-unseal.sh
  → symlink → /home/halil/platform-k8s-gitops/deploy/staging-sw/vault-auto-unseal.sh
```

**Steady-state deploy** (initial apply tamamlandıktan sonra herhangi bir
değişiklik main'e merge edildiğinde):

```bash
ssh halil@staging-sw 'cd /home/halil/platform-k8s-gitops && git pull --ff-only'
```

Symlink dosyaya işaret ettiği için ekstra kopya adımı YOK. `git pull` yeterli.

> **Initial apply** (bu PR merge edildikten hemen sonra, tek-seferlik):
> Aşağıda "İlk Kurulum" bölümüne bakın. O adımlar tamamlanana kadar runtime
> path hâlâ eski (ex-symlink) canlı dosyaya işaret ediyor.

## Cron Kontratı (`crontab -l` `halil` user)

Vault unseal her reboot'ta iki ayrı `@reboot` satırıyla, ortam-explicit:

```cron
# Vault auto-unseal @reboot (test önce, prod sonra; docker readiness için gecikme)
@reboot sleep 45 && VAULT_CONTAINER=platform-vault-test INIT_FILE=/home/halil/bootstrap-drill/vault-init-test.json /home/halil/platform/scripts/vault-auto-unseal.sh >> /home/halil/platform/state/vault-unseal.log 2>&1
@reboot sleep 60 && VAULT_CONTAINER=platform-vault-prod INIT_FILE=/home/halil/bootstrap-drill/vault-init-prod.json /home/halil/platform/scripts/vault-auto-unseal.sh >> /home/halil/platform/state/vault-unseal.log 2>&1
```

Neden 45s/60s?
- `sleep 45` = docker + `platform-vault-test` container fully-ready
- `sleep 60` = 15s spacing → aynı log dosyasına paralel yazımı azaltır +
  prod'un test'ten sonra unseal olması operational sırası
- Cross-AI (Codex thread `019f37e3-dd1e-7f40-95b2-66c2e0d0b223`) verdict:
  30/35 yerine 45/60 daha güvenli

Neden env-explicit?
- Script default `VAULT_CONTAINER` **yok** (REQUIRED). 2026-07-06 öncesi
  default `platform-vault-1` (compose-era stale) idi ve cron env-siz
  çağırıyordu → 2 ay boyunca `vault-unseal.log` `FAILED (rc=1)` (silent, pre-patch
  script her zaman `exit 0` diyordu).

## Preflight Mantığı

`vault-auto-unseal.sh` shard feed etmeden ÖNCE 3 kapı:

1. **Live Total Shares**: `docker exec $VAULT_CONTAINER vault status -format=json`'dan `.n` okunur.
2. **Source share-count**: `INIT_FILE` set ise `.unseal_keys_b64 | length`,
   değilse `KEYS_DIR/vault-unseal-key-*` sayısı.
3. **Eşleşme kontrolü**: `source_count != live_total` → `PREFLIGHT FAIL` +
   `exit 1`.

Bu 2026-07-06 tarihinde `~/platform/state/vault/vault-init*.json` dosyalarının
canlı vault'lara **shape-mismatched** olduğu (test'e prod init, prod'a test
init) fark edildikten sonra eklendi. Canonical init dosyaları
`~/bootstrap-drill/vault-init-{test,prod}.json`; ayrıntı için
`/home/halil/platform/state/vault/README.md` (stale-swapped incident).

## İlk Kurulum (Runbook — bu PR merge sonrası staging-sw'de uygulanacak)

Bu PR merge edildikten sonra tek-seferlik host apply. staging-sw benzeri
ilerideki host'lar için de referans.

```bash
# 1. Clone (staging-sw'de mevcut; başka host'ta ilk kez ise clone)
sudo -u halil git clone git@github.com:Halildeu/platform-k8s-gitops.git /home/halil/platform-k8s-gitops
# staging-sw'de: cd /home/halil/platform-k8s-gitops && git pull --ff-only

# 2. Runtime symlink (mevcut canlı script'i backup + symlink ile değiştir)
cd /home/halil/platform/scripts
mv vault-auto-unseal.sh vault-auto-unseal.sh.bak-<date>-pre-symlink
ln -s /home/halil/platform-k8s-gitops/deploy/staging-sw/vault-auto-unseal.sh vault-auto-unseal.sh

# 3. Cron güncelleme
crontab -e
# eski tek satırı sil, iki yeni @reboot satırını ekle (yukarıda "Cron Kontratı" bloğu).

# 4. Preflight dry-run (unseal YOK, PREFLIGHT_ONLY mode — canlı ya unsealed ya da sealed hangisi olursa olsun güvenli):
VAULT_CONTAINER=platform-vault-test INIT_FILE=/home/halil/bootstrap-drill/vault-init-test.json PREFLIGHT_ONLY=1 \
  /home/halil/platform/scripts/vault-auto-unseal.sh
# beklenen (sealed): "preflight OK ... PREFLIGHT_ONLY set — exiting without unseal (dry-run OK)"
# beklenen (already unsealed): "already unsealed"
VAULT_CONTAINER=platform-vault-prod INIT_FILE=/home/halil/bootstrap-drill/vault-init-prod.json PREFLIGHT_ONLY=1 \
  /home/halil/platform/scripts/vault-auto-unseal.sh
# aynı.
```

## Retired / Removed (host-side, PR merge sonrası uygulanacak)

**`platform-start.sh`** (compose-era cold-start orkestratörü) retire ediliyor:

- Referans verdiği `/home/halil/platform/repo/backend/docker-compose.prod.yml`
  host'ta yok
- Cron / systemd / bash_history hiçbirinde invoker referansı yok (2026-07-06
  taraması: bash_history 0 hit)
- Gerçek workload k3d (in-docker) üzerinde; compose era bitmiş

Post-merge host apply sırasında
`/home/halil/platform/scripts/.archive/platform-start.sh.retired-20260706`
altına arşivlenecek. Repo'da tutulmuyor (compose-era relic; SoT'a katkısı yok).

**ssot host-residue**: `platform-ssot` deprecated clone'undan gelen 4 stale
`vault-auto-unseal.sh` (+ 4 `platform-start.sh`) kopyası post-merge host apply
sırasında silinecek (HARD RULE `platform-ssot` DEPRECATED — canonical repo
`platform-{backend,web,k8s-gitops}`; host'ta ssot residue tutulmuyor). Sayım
(2026-07-06 tarama):

- `/home/halil/platform/repo/deploy/ubuntu/vault-auto-unseal.sh` (ssot clone)
- `/home/halil/platform/repo-worktrees/fix-stage-keycloak-detector/deploy/ubuntu/vault-auto-unseal.sh`
- `/home/halil/platform/repo-worktrees/fix-stage-deploy-postgres-conflict/deploy/ubuntu/vault-auto-unseal.sh`
- `/home/halil/actions-runner-stage/_work/platform-ssot/platform-ssot/deploy/ubuntu/vault-auto-unseal.sh`
  (GHA runner working-dir; auto-regenerated by jobs but ssot workflows are
  dead — no-op cleanup)

## History

| Tarih | Ne oldu | Referans |
|---|---|---|
| 2026-07-06 | Preflight added to live canonical script (share-count match) — stale-swapped-init incident sonrası | `~/platform/state/vault/README.md` |
| 2026-07-06 | Host-deploy consolidation (bu PR): SoT into repo. Post-merge host apply plan: symlink + cron env-explicit + platform-start retire + ssot residue temizliği | Board #2270, Codex threads `019f37e3-…` (plan-time) + `019f37e9-…` (post-impl) |
