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

## Deploy Chain

**Host clone** (staging-sw'de zaten mevcut, cron bootstrap script'leri kullanıyor):

```
/home/halil/platform-k8s-gitops/   ← ana clone (bootstrap crons buradan çalışıyor)
```

**Runtime path'i** (cron ve manuel invoker'lar buraya bakar):

```
/home/halil/platform/scripts/vault-auto-unseal.sh
  → symlink → /home/halil/platform-k8s-gitops/deploy/staging-sw/vault-auto-unseal.sh
```

**Deploy adımı** (bu dizinde herhangi bir değişiklik main'e mergelendikten sonra):

```bash
ssh halil@staging-sw 'cd /home/halil/platform-k8s-gitops && git pull --ff-only'
```

Symlink zaten dosyaya işaret ettiği için ekstra kopya adımı YOK. `git pull`
yeterli. İlk kurulum runbook için aşağıya bakın.

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

## İlk Kurulum (Runbook)

Bu adımlar 2026-07-06 tarihinde staging-sw'de zaten yapıldı; buradaki listing
gelecekteki başka host'lar (staging-sw benzeri) için referans.

```bash
# 1. Clone (zaten mevcutsa atla)
sudo -u halil git clone git@github.com:Halildeu/platform-k8s-gitops.git /home/halil/platform-k8s-gitops

# 2. Runtime symlink (mevcut canlı script'i backup + symlink değiştir)
cd /home/halil/platform/scripts
mv vault-auto-unseal.sh vault-auto-unseal.sh.bak-<date>-pre-symlink
ln -s /home/halil/platform-k8s-gitops/deploy/staging-sw/vault-auto-unseal.sh vault-auto-unseal.sh

# 3. Cron güncelleme
crontab -e
# eski tek satırı sil, iki yeni @reboot satırını ekle (yukarıda "Cron Kontratı" bloğu).

# 4. Dry-run test (canlı unseal'i tetiklemeden yalnızca preflight):
VAULT_CONTAINER=platform-vault-test INIT_FILE=/home/halil/bootstrap-drill/vault-init-test.json /home/halil/platform/scripts/vault-auto-unseal.sh
# beklenen: "already unsealed" (canlı vault unsealed durumdaysa)
VAULT_CONTAINER=platform-vault-prod INIT_FILE=/home/halil/bootstrap-drill/vault-init-prod.json /home/halil/platform/scripts/vault-auto-unseal.sh
# aynı.
```

## Retired / Removed

**`platform-start.sh`** (compose-era cold-start orkestratörü) 2026-07-06'da
retire edildi:

- Referans verdiği `/home/halil/platform/repo/backend/docker-compose.prod.yml`
  host'ta yok
- Cron / systemd / bash_history hiçbirinde invoker referansı yok
- Gerçek workload k3d (in-docker) üzerinde; compose era bitmiş

Host'ta `/home/halil/platform/scripts/.archive/platform-start.sh.retired-20260706`
olarak arşivlendi. Repo'da tutulmuyor (compose-era relic; ana context yok).

**ssot host-residue**: `platform-ssot` repo'sunun deprecated clone'undan gelen
4 stale `vault-auto-unseal.sh` (+ 4 `platform-start.sh`) kopyası 2026-07-06'da
host'tan silindi (HARD RULE `platform-ssot` DEPRECATED).

## History

| Tarih | Ne oldu | Referans |
|---|---|---|
| 2026-07-06 | Host-deploy consolidation: SoT into repo + host symlink + cron env-explicit + platform-start retire + ssot residue temizliği | Board #2270, Codex thread `019f37e3-dd1e-7f40-95b2-66c2e0d0b223` |
| 2026-07-06 | Preflight added (share-count match) — stale-swapped-init incident sonrası | `~/platform/state/vault/README.md` |
