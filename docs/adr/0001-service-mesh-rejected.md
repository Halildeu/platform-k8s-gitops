# 0001 — Service Mesh Rejected (Istio/Linkerd)

## Status

**Rejected** (2026-04-19)

## Context

Kubernetes ekosisteminde Service Mesh (Istio, Linkerd, Consul Connect) yaygın pattern. Sunduğu özellikler:

- Servisler-arası mTLS otomasyon
- Traffic management (canary, traffic splitting, fault injection)
- Observability (distributed tracing, metric aggregation otomatik)
- Security policy (mTLS zorunluluğu, authorization policy)

Platform K8s migration'ında Service Mesh kurulumu gündeme geldi mi? Bu ADR, "hayır — şu an için reddedildi" kararını belgeler.

## Decision

**Service Mesh KURULMAZ** bu platform için. Mevcut MVP mimarisi (ingress-nginx + NetworkPolicy + ESO + OpenFGA) yeterli.

## Consequences

### Pozitif (red kararının faydaları)

- **D27 Upstream-first prensibi uyumlu:** Native Kubernetes primitif'leri (Service, NetworkPolicy, Ingress) yeterli — Mesh gibi abstraction katmanı eklemek fayda-maliyet oranı düşük.
- **Operational basitlik:** Mesh control plane ek ops yükü (Istio Pilot/Galley/Citadel, Linkerd control-plane), her cluster'da 5-10 ek pod, debug karmaşıklığı artar.
- **Resource verimliliği:** Mesh sidecar (Envoy) pod başına ~50-100MB RAM + 50-200m CPU. 8 backend pod × sidecar = **fazladan ~800MB RAM + 400m-1600m CPU** (D22 bütçesini zorlar).
- **Debug karmaşıklığı:** Mesh sidecar traffic interception → sorun teşhisi "pod mi mesh mi" ayrımı gerektirir. Mevcut `kubectl logs` + `curl -k` direkt debug yaklaşımını bozar.
- **MVP hız avantajı:** Mesh kurulumu + config + tuning 2-4 hafta iş. MVP ship edebilmek için önceliksizleştirildi (D25 PoC dilim prensibi).
- **Authz Zanzibar native:** OpenFGA + permission-service pattern zaten hub-and-spoke authz sağlar. Mesh mTLS + authorization policy ek layer olurdu, değer paralel değil ikincil.

### Negatif (red maliyeti — kabul edildi)

- **mTLS yok:** Servisler-arası traffic plaintext (intra-cluster). Kubernetes ağı trust boundary (Calico NetworkPolicy + namespace isolation). Dış proxy + host nginx SSL termination + internal HTTP yeterli MVP için.
- **Distributed tracing manuel:** OTel SDK kod seviyesinde (Spring Boot) + Tempo backend. Mesh otomatik injection yerine. Kabul — D27 native tracing pattern.
- **Traffic management sınırlı:** Canary Argo Rollouts ile (DRAFT mevcut). Edge cutover atomic (D30 HARD RULE). Mesh traffic splitting gerekli değil.

## Alternatives

### A) Istio
- **Reddedildi:** Heavyweight (sidecar injection + control-plane). Operational karmaşıklık yüksek. MVP için aşırı.

### B) Linkerd
- **Reddedildi:** Daha hafif ama yine de ek ops yükü. Pod başına memory overhead (20-30MB) hâlâ var. MVP zamanlama önceliksizleştirdi.

### C) Consul Connect
- **Reddedildi:** Platform zaten Vault kullanıyor (HashiCorp stack kısmen). Ama Consul kurulumu ek iş.

### D) Seçilen — Native K8s + NetworkPolicy + OpenFGA + OTel
- **Kabul:** D27 upstream-first + D25 MVP PoC dilim prensibi. Seviye 2-5 kapsamındaki ihtiyaç için yeterli.

## Reversal Koşulları

Bu karar **post-cutover S5 sonrası** yeniden değerlendirilebilir eğer:

- Servisler-arası authn gereksinim Zanzibar + JWT ötesinde güçlenirse
- Çoklu tenant izolasyon mTLS zorunlu kılarsa
- Advanced traffic management (canary, A/B test, shadow traffic) MVP ötesi iş gerektirirse
- Scale 3+ cluster + cross-region olursa

Yeniden değerlendirme: ayrı ADR (0002-service-mesh-reconsidered.md) + Codex adversarial plan-time istişare.

## Referanslar

- PLAN.md D27 Upstream-first prensibi
- PLAN.md D25 MVP PoC dilim prensibi
- PLAN.md D22 CPU bütçesi (Mesh sidecar overhead'i bozacağı)
- docs/S2-X3-security-hygiene.md (NetworkPolicy + TLS boundary)
- docs/prod-cutover-smoke-runbook.md (atomic cutover D30 — mesh canary gereksiz)
