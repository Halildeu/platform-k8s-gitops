# Runbook — Alertmanager → GitHub Issues köprüsünün token'ı (owner action)

> **Tetik:** Prometheus alarmları hiçbir yere ulaşmıyor; `alertmanager-bridge` log'unda
> `gh issue create failed: ... populate the GH_TOKEN environment variable`.
> **Sahibi:** owner (prod credential mutasyonu — agent yapamaz, ortam-kapsam HARD RULE).
> **Kaynak olay:** [#2863](https://github.com/Halildeu/platform-k8s-gitops/issues/2863) —
> `auth-service` 106 dakika ölü kaldı, hiçbir bildirim çıkmadı.

## Neden bu runbook var

Zincirin geri kalanı **onarıldı ve doğrulandı** (2026-07-24): test'te 25 PrometheusRule
uygulandı, `kube_*` serileri remote_write allowlist'ine eklendi (#2871 + `helm upgrade`),
prod'da Alertmanager + köprü **çalışıyor**, köprü alarmları **alıyor**. Tek eksik: köprünün
GitHub'a yazma yetkisi yok.

Sonuç bugün: **birikmiş kritik alarmlar kimseye ulaşmıyor** ve bunu haber verecek olan
öz-izleme alarmları da (`AlertmanagerBridgeGHTokenExternalSecretNotReady`,
`AlertmanagerBridgeGitHubDeliveryFailing`) aynı bozuk kanaldan geçmek zorunda — tavuk-yumurta.
Son 200 issue içinde **sıfır** alarm-kaynaklı kayıt bunun kanıtı.

## Mevcut durum (ölçüldü, k3d-prod / monitoring)

```
externalsecret/alertmanager-bridge-gh-token
  STATUS : SecretSyncedError      READY: False
  message: could not get secret data from provider
  vault  : kv/platform/alertmanager-bridge-gh
secret/alertmanager-bridge-gh-token → HİÇ OLUŞMAMIŞ
```

`.53 → .15` sunucu taşımasında geride kalan secret'lardan biri. **Önce eski sunucuda var mı
bakın** — büyük olasılıkla iş "yeni token üret" değil, **"bu tek anahtarı taşı"**.

## Adımlar

### 1. Anahtar eski Vault'ta duruyor mu (tercih edilen yol)

```bash
ssh staging-sw-legacy 'vault kv get -format=json kv/platform/alertmanager-bridge-gh' | jq -r '.data.data | keys[]'
```

Anahtar adlarını görürsünüz (değerleri yazdırmayın). Duruyorsa 2a, durmuyorsa 2b.

### 2a. Taşı (değer terminale/history'ye düşmeden)

```bash
ssh staging-sw-legacy 'vault kv get -field=token kv/platform/alertmanager-bridge-gh' \
  | ssh aiserver 'vault kv put kv/platform/alertmanager-bridge-gh token=-'
```

`token=-` → değeri **stdin'den** okur; argv'ye, shell history'ye, log'a düşmez.
(Alan adı 1. adımdaki çıktıyla birebir aynı olmalı.)

### 2b. Yeni token (eski anahtar yoksa)

GitHub'da bir **fine-grained PAT** üretin — kapsam: yalnız `Halildeu/platform-k8s-gitops`,
izin: **Issues: Read and write**. Başka hiçbir izin gerekmez. Sonra:

```bash
ssh aiserver 'read -rs T; printf "%s" "$T" | vault kv put kv/platform/alertmanager-bridge-gh token=-'
```

`read -rs` → yazarken ekrana basmaz.

### 3. ESO'yu hemen senkronize et (1 saat beklemeden)

```bash
kubectl --context k3d-prod -n monitoring annotate externalsecret alertmanager-bridge-gh-token \
  force-sync=$(date +%s) --overwrite
```

### 4. Doğrula

```bash
kubectl --context k3d-prod -n monitoring get externalsecret alertmanager-bridge-gh-token   # READY=True
kubectl --context k3d-prod -n monitoring get secret alertmanager-bridge-gh-token            # var olmalı
kubectl --context k3d-prod -n monitoring rollout restart deploy/alertmanager-bridge
kubectl --context k3d-prod -n monitoring logs deploy/alertmanager-bridge --tail=20 | grep -iE "issue|error"
```

**Beklenen:** `gh issue create failed` **kaybolur**; birikmiş kritik alarmlar bu repoda
issue olarak açılmaya başlar (köprü dedup'lı; resolved olunca issue'yu kendisi kapatır).

### 5. Uçtan uca kanıt (issue'yu kapatan koşul)

Gerçek bir kesinti beklemeyin — tek kullanımlık probe yeterli, mevcut hiçbir servise
dokunmaz (TEST Scale-to-Zero YASAK kuralıyla uyumlu):

```bash
kubectl --context k3d-test -n platform-test create deployment alert-e2e-probe \
  --image=ghcr.io/halildeu/this-image-does-not-exist:probe
# LimitRange minimum 32Mi ister:
kubectl --context k3d-test -n platform-test set resources deploy/alert-e2e-probe \
  --requests=cpu=10m,memory=32Mi --limits=cpu=50m,memory=64Mi
# ~15 dk sonra: bu repoda KubeDeploymentRolloutStuck issue'su açılmalı
kubectl --context k3d-test -n platform-test delete deploy alert-e2e-probe
# resolved sonrası köprü issue'yu kapatmalı
```

Bu adım geçtiğinde **#2863 kapatılabilir** — o ana kadar "izleme onarıldı" demek, olayın
kendi dersiyle çelişir.

## Rollback

Token'ı geri almak: `vault kv delete kv/platform/alertmanager-bridge-gh` + ESO secret silinir.
Köprü tekrar sessizleşir (mevcut duruma döner); başka hiçbir şey etkilenmez.

## Neden agent yapmadı

Prod credential mutasyonu owner-gated (ortam-kapsam HARD RULE: test otonom / **prod kritik**),
ve credential üretme/işleme agent için her ortamda yasak. Zincirin agent-doable kısmı
tamamlandı ve doğrulandı; kalan tek adım budur.

## İlgili

- [#2863](https://github.com/Halildeu/platform-k8s-gitops/issues/2863) — kaynak olay + tüm ölçümler
- `kustomize/base/monitoring/alertmanager-bridge/` — köprü manifest'leri + `alertmanager-bridge.py`
- `prometheusrule-alertmanager-bridge-{self-watch,gh-auth}.yaml` — köprünün öz-izleme kuralları
