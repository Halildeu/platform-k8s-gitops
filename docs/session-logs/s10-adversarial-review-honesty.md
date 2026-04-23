# Session 10 — Codex Adversarial Review + 4-Faz Plan + Honesty Recovery Başlangıç

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 1211-1290)
> Canonical truth: `docs/state/current-state.md`

---

## Session 10 — Codex Adversarial Review + 4-Faz Plan + Honesty Recovery Başlangıç

> Trigger: kullanıcı "codex incelesin derinlemesine" + "kapsamlı uygulama planı" + "hand off"

### DDD. Codex Thread 1 (`019daa7f`) — Adversarial Review (xhigh effort)

**10 madde verdict**:
1. ADR-0002 mimari: **REVISE/HIGH** — "production-ready" yerine "taktik ara mimari"
2. Soft cutover: **RED/CRITICAL** → 2.tur **PARTIAL** — doğru ad "stateful split migration with compose-preserved workload"
3. ESO routing: **REVISE/HIGH** — root-neden analizi iki kez değişti (Docker bridge → Calico WL), packet kanıt yok
4. Frontend env-per-build: **REVISE/MEDIUM** — `main-stable` mutable tag D30 ile çelişiyor
5. KC admin reset: **REVISE/HIGH** — 5-tablo FK kapsamı belirsiz, resmi reset aranmadı
6. Vault PLACEHOLDER: **REVISE/HIGH** — matrix/kod/realm üçü çelişiyor (7 servis için secret matrix var, sadece user-service client'ı var)
7. Handoff 1207 satır: **RED/HIGH** — aynı dosyada "k3d-prod boş F-G başlamadı" + "G/H done %99.5" çelişkisi
8. PR cadence: **REVISE/HIGH** — governance metadata-ağırlıklı, branch protection advisory
9. **%99.5 iddiası**: **RED/CRITICAL** → 2.tur **RED devam**, ancak "operational continuity ~%65" diye yeniden adlandırılırsa yumuşar
10. Unvalidated assumptions: **RED/CRITICAL** — `/srv→/home`, port 8201→8301, Vault 1.21→1.17, k3d CLI yok, vb.

**Codex'in kapanış**: "9 session'da yapılmayıp yapılması zorunlu tek şey: **full restore + rollback rehearsal**. O yapılmadan ne 'production-ready', ne '72h warm rollback', ne de '%99.5' cümlesi teknik olarak savunulabilir."

### EEE. Codex Thread 2 (`019daad8`) — Kapsamlı Uygulama Planı

**4 Faz, 9-11 takvim günü + 72h soak**:

#### Faz 10 — Dürüstlük Recovery (D0-D1, 21-22 Nis)
- S10-T1: `docs/state/current-state.md` canonical (3h) ✅ **BU OTURUMDA YAPILDI**
- S10-T2: Handoff 1207 satır → 4 parça split (4h) — ~~PENDING~~ ✅ **2026-04-24 PR #53 CLOSED** (1290 satır → 10 session-logs s01..s10 + 55 satır index)
- S10-T3: `drift-ledger.md` + söylem revizyonu (4h) — ~~PENDING~~ ✅ **current-state.md §Live Delta + §Yasak Terimler ile dahil edildi (Session 10-27 truth evolution)**

#### Faz 11 — Secret Delivery Truth-Finding (D2-D4, 23-25 Nis)
- S11-T1: Packet-level hakikat çıkarımı — tcpdump + conntrack + iptables counter (1g)
- S11-T2: 4-saatlik kurtarma penceresi VEYA ADR-0003 pivot (1g)
- S11-T3: Prod secret-delivery kapanışı + ArgoCD test register + roleId UUID (4-6h)

#### Faz 12 — DR Cold Rollback Rehearsal (D5-D7, 26-28 Nis)
- S12-T1: Preserved volume envanter + drill klon oluştur (0.5g)
- S12-T2: Cold rollback boot + 2x independent smoke PASS (1-1.5g)
- S12-T3: Vault full rotation + cron real drill + ClusterIssuer karar (0.5-1g)

#### Faz 13 — Atomic Cutover (D8-D11, 29 Nis-3 May)
- S13-T1: T-24/T-8 freeze + son preflight (0.5g)
- S13-T2: T-0 atomic upstream switch + T+15 gate (2-3h aktif)
- S13-T3: 72h soak + warm rollback pencere + decommission kararı (72h pasif)

### FFF. 5-Sayaç Hedef Kapanış Matrix (Codex)

| Aşama | test-k8s | prod-stateful | prod-gitops | secret | dr |
|---|---:|---:|---:|---:|---:|
| Şu an (baseline) | 75 | 65 | 20 | 15 | **0** |
| Faz 10 çıkışı | 75 | 65 | 20 | 15 | 0 |
| Faz 11 çıkışı | 75 | 65 | 30 | **80** | 0 |
| Faz 12 çıkışı | 75 | **85** | 35 | 80 | **85** |
| Faz 13 + T+72h | 85 | **90** | **95** | **90** | 85 |

**Tavan ~%95** (tek host + warm rollback sınırı).

### GGG. Bu Oturumun Aksiyon Özeti

**Yapılan**:
1. Codex adversarial review alındı (thread 019daa7f)
2. 2. tur istişare: itirazlarım iletildi, verdict kalibre edildi
3. Kapsamlı 4-faz uygulama planı oluşturuldu (thread 019daad8)
4. `docs/state/current-state.md` canonical dosyası yazıldı (S10-T1 ✅)
5. `%99.5`, `Faz H done`, `soft cutover` söylemleri yasak terim listesine alındı
6. Yeni 5-sayaç skalaya göre baseline: **~%65 weighted** (tavan ~%95)

**Yapılmayan (sonraki oturum)**:
- S10-T2: Handoff 1207 satır physical split (session-logs/*.md)
- S10-T3: Drift-ledger ayrı dosya (şu an current-state içinde)
- Faz 11-12-13 komple

### HHH. Son Kullanıcı İletişim Notu

Önceki handoff'lardaki iyimserlik (%99.5, DONE LIVE, soft cutover) **geri çekildi**. Gerçek baseline:
- **Operasyonel continuity %65** (test + prod live, temel akış çalışıyor)
- **GitOps + DR %15-0** (ESO blocked, rollback kanıtsız)
- Cutover "yapılmadı" (stateful split var ama D30 atomic cutover yok)
- Minimum 9-11 gün iş kaldı (Faz 11-13)

Proje geriye gitmedi; anlatı dürüstleşti. Cutover tarihi Faz 11 sonrası commit edilebilir.
