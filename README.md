# platform-k8s-gitops

Kubernetes GitOps manifest'leri — autonomous-orchestrator platformu.

## Amaç

Bu repo, `autonomous-orchestrator` platformunun Docker Compose'dan Kubernetes'e tam geçişi için GitOps manifest'lerini tutar. ArgoCD bu repo'dan sync ederek staging-sw cluster'ına deploy eder.

## Başlarken

Detaylı plan ve kararlar için → [PLAN.md](./PLAN.md)

## Dizin Yapısı

- `kustomize/base/` — ortam-bağımsız manifest'ler
- `kustomize/overlays/{local,test,prod}/` — ortam-özel yamalar
- `helm-values/` — 3. parti chart values (ingress-nginx, cert-manager, argocd, prometheus, loki, tempo)
- `host-compose/` — K8s dışında host'ta çalışacak PG/KC/Vault için Docker Compose
- `argocd/applications/` — ArgoCD Application CR'ları (app-of-apps)

## Ana Repo

Backend kaynak kodu + Dockerfile + application-k8s.yml profilleri ayrı repoda:
- `/Users/halilkocoglu/Documents/dev/` (autonomous-orchestrator)
