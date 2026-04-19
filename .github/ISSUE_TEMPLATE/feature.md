---
name: Feature / Enhancement
about: Yeni manifest, runbook, script, doc
title: "[FEAT] "
labels: enhancement
---

## Özet

<!-- 1-2 cümle -->

## Motivasyon

<!-- Neden? Hangi boşluğu doldurur? -->

## Kapsam

- [ ] Kustomize base değişim
- [ ] Overlay-specific (test/prod/eso)
- [ ] Helm values
- [ ] ArgoCD Application/Set
- [ ] Monitoring (PrometheusRule/Probe/dashboard/recording)
- [ ] Bootstrap script
- [ ] Runbook/doc

## D-Karar Gerekli mi?

- [ ] Evet — PLAN.md'ye D-karar eklenmeli (mimari değişim)
- [ ] Hayır — operasyonel iş

## HARD RULE Etki

- [ ] D17 scale-to-zero korunur
- [ ] D18 edge topolojisi uyumlu
- [ ] D29 3-katman acceptance uygulanabilir
- [ ] D30 immutable tag + atomic cutover
- [ ] IP sanitize + no-closure language

## Codex İstişare

- [ ] Plan-time adversarial review gerek (büyük scope)
- [ ] Küçük scope — tek turlu consult yeterli
- [ ] Operasyonel — Codex skip

## Referans

- PLAN.md D-karar: `<D<N>>`
- İlgili runbook: `<docs/...>`
- Handoff atıf: `<docs/session-handoff-*.md>`
