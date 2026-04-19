---
name: Bug
about: Drift, fail, unexpected behavior
title: "[BUG] "
labels: bug
---

## Tanım

<!-- Kısa: ne oldu, neyi bekliyordun -->

## Ortam

- Cluster: `<k3d-test|k3d-prod>`
- Namespace: `<platform-test|platform-prod|external-secrets|monitoring>`
- Commit: `<sha>` (git log main..HEAD)
- Trigger: `<deploy/cutover/chaos/manuel>`

## Gözlem

### Pod State
```
kubectl --context <ctx> -n <ns> get pods
# çıktı
```

### Logs
```
kubectl --context <ctx> -n <ns> logs <pod> --tail=50
# çıktı
```

### Events
```
kubectl --context <ctx> -n <ns> describe pod <pod>
# Events bölümü
```

## Beklenen vs Gerçek

| Katman | Beklenen | Gerçek |
|---|---|---|
| Up | Running 1/1 | ... |
| Functional | 200 JSON | ... |
| Zanzibar-ready | Allow+Deny enforce | ... |

## Ekran Görüntüsü / Dashboard

<!-- Grafana panel link veya PrometheusRule alert -->

## Etki

- [ ] Critical (rollback trigger)
- [ ] Warning (investigate)
- [ ] Observe (trend)

## Bilinen Benzer Pattern

<!-- Örn: 2026-04-17 Calico typha watch cache bozuk recovery pattern -->

## Çözüm Önerisi

<!-- Varsa -->
