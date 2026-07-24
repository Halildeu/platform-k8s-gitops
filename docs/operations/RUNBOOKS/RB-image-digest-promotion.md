# Runbook — Image digest promotion (pin only what the registry will serve)

> Kaynak olay: 2026-07-24, tek günde **iki kesinti** aynı sebepten.
> İlgili: [#2863](https://github.com/Halildeu/platform-k8s-gitops/issues/2863) ·
> [#2876](https://github.com/Halildeu/platform-k8s-gitops/issues/2876) ·
> Guard: `scripts/governance/check_overlay_digest_pullable.py`

## Neden bu runbook var

Bir digest, bir insanın bakacağı **her yerde** doğru görünebilir ve yine de
çekilemez:

- build log'unda `pushing manifest for …@sha256:…` satırı **var**
- commit `main`'de **var**
- paket adı servisle **eşleşiyor**
- soy bağı (`git merge-base --is-ancestor`) **doğru**

Bunların hiçbiri "registry bu digest'i geri verir" demek değildir. Uygulanırsa
sonuç `ImagePullBackOff` + boş Endpoints + **servis kapalı**.

| Olay | Süre | Nasıl fark edildi |
|---|---|---|
| `auth-service` (#2863) | **106 dakika** | tesadüfen, başka bir iş sırasında |
| `user-service` (#2874→#2875) | dakikalar | promote eden kişi hemen ölçtüğü için |

İkisinin de tek eksiği aynıydı: **pin'lemeden önce çekmeyi denemek**.

## Sıra (atlanmaz)

### 1. Digest'i build log'undan ALMA — çekerek yakala

Build log'u **builder'ın ne push ettiğini** kaydeder; registry'nin **ne geri
vereceğini** değil. İkisi ayrışabilir (yetki, GC, farklı paket, yarım push).

Cluster'ın kendi kimliğiyle (`ghcr-pull`) çekip gerçek `imageID`'yi okuyun:

```bash
NS=platform-test
IMG=ghcr.io/halildeu/platform-backend-<servis>:sha-<kısa-commit>

kubectl -n "$NS" run digest-probe --restart=Never --image="$IMG" \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"ghcr-pull"}]}}' \
  --command -- sleep 20

# 15-60 sn bekleyip:
kubectl -n "$NS" get pod digest-probe \
  -o jsonpath='{.status.containerStatuses[0].imageID}'; echo
kubectl -n "$NS" delete pod digest-probe
```

- `imageID` **dolu** → bu digest bu cluster tarafından çekilebilir. Pin'lenecek
  değer budur.
- `imageID` **boş** + `ImagePullBackOff` → **pin'lemeyin**. Nedeni okuyun:

```bash
kubectl -n "$NS" describe pod digest-probe | grep -A3 Failed
```

| Mesaj | Anlamı |
|---|---|
| `403 Forbidden` | Cluster'ın GHCR kimliği bu pakete yetkisiz → **#2876** |
| `404 / not found` | Digest registry'de yok (yanlış paket, GC, hiç push edilmemiş) |
| `manifest unknown` | Referans var ama manifest çözülmüyor |

> PodSecurity `restricted` uygulanan namespace'lerde probe pod'u
> `runAsNonRoot` + `seccompProfile` + `capabilities.drop:[ALL]` ister;
> `--overrides` ile ekleyin ya da hazır manifesti kullanın.

### 2. Overlay'i pin'le

```yaml
  - name: <servis>
    newName: ghcr.io/halildeu/platform-backend-<servis>
    digest: sha256:<adım-1'de-ÇEKİLEN-digest>
```

Yorum satırına **neden** promote edildiğini yazın (hangi issue/PR, ne değişti).

### 3. PR aç — guard kendiliğinden koşar

`gate-overlay-digest-pullable` yalnız bu PR'ın **eklediği/değiştirdiği**
digest'leri sorgular ve verdict vermeden önce **kendini doğrular**: aynı paket
için `main`'de pinli (yani deploy'da çalışan) bir *control* digest'i okuyabiliyor
mu?

| Control | Yeni digest | Sonuç |
|---|---|---|
| 200 | 200 | **PASS** |
| 200 | 404 | **FAIL** — digest gerçekten registry'de yok, merge etmeyin |
| 404 | — | **INCONCLUSIVE** — guard okuyamıyor, hüküm vermiyor (exit 0) |

INCONCLUSIVE neden FAIL değil: GHCR, **yetkisiz** manifest sorgusuna da
**404** döner — "yok" ile "bakamadım" aynı koda düşer. Control olmadan guard,
kimliği süresi dolduğu gün bütün dürüst PR'ları kırardı. Bugün tam bu hatanın
bir örneği canlıda vardı: `EtikSpeakOpenFgaDown` SEV1, hiç ulaşamadığı bir
metrik ucu hakkında günlerce alarm veriyordu.

### 4. Uygula ve **ölç**

```bash
kubectl -n platform-test rollout status deploy/<servis> --timeout=420s
kubectl -n platform-test get endpoints <servis> -o jsonpath='{.subsets[*].addresses[*].ip}'; echo
```

Endpoints **boşsa** servis kapalıdır — rollout "başarılı" görünse bile.

## Geri alma (kesinti anında ilk hamle)

Önceki digest node cache'inde olduğu için GHCR'a çıkmadan geri döner:

```bash
kubectl -n platform-test set image deploy/<servis> <container>=<ÖNCEKİ_DIGEST>
kubectl -n platform-test rollout status deploy/<servis> --timeout=300s
kubectl -n platform-test get endpoints <servis> -o jsonpath='{.subsets[*].addresses[*].ip}'; echo
```

Önceki digest'i bulmak:

```bash
kubectl -n platform-test get rs -l app.kubernetes.io/name=<servis> \
  -o custom-columns='RS:.metadata.name,IMAGE:.spec.template.spec.containers[0].image' \
  --sort-by=.metadata.creationTimestamp
```

**Sonra git'i de geri alın.** Canlıyı düzeltip overlay'i bırakmak, bir sonraki
reconcile'da aynı kesintiyi geri getirir — ve canlı ↔ git ayrışması, #2863'te
teşhisi iki kez yanlış yönlendirdi.

## Guard'ı enforcing yapmak

Şu an private paketlerde INCONCLUSIVE çalışıyor: CI'ın kimliği
`read:packages` taşımıyor. `GHCR_TOKEN` secret'ı eklendiğinde guard **kod
değişikliği olmadan** enforcing'e geçer.

Aynı eksik, cluster tarafında #2876 olarak duruyor:

```bash
# değer stdin'den; argv'ye/history'ye düşmez
ssh aiserver 'read -rs T; printf "%s" "$T" | vault kv put kv/gitops/ghcr-token token=-'
kubectl -n platform-test annotate externalsecret ghcr-pull force-sync=$(date +%s) --overwrite
```

Ardından adım 1'deki probe ile **doğrulayın** — bu adım atlanmaz.

## Guard ne kanıtlar, ne kanıtlamaz

| | |
|---|---|
| **Kanıtlar** | Registry bu digest'i **CI'ın kimliğine** veriyor. Yakalar: yanlış paketten kopyalanmış digest, GC edilmiş imaj, hiç push edilmemiş manifest, harf hatası |
| **Kanıtlamaz** | **Cluster'ın** çekebileceği. CI ve cluster farklı kimlikler (CI: `GHCR_TOKEN`; cluster: `ghcr-pull` ← `kv/gitops/ghcr-token`). Cluster kimliği süresi dolduğunda CI yeşil kalırken cluster 403 alır — #2876 |

Bu yüzden adım 1'deki cluster probe'u guard'ın yerine geçmez; guard onun
öncesindeki ucuz elemedir.
